"""Agente 2 — **Prompt Architect**. Construye el prompt de sistema especializado para cada encargo.

No llama a ningún modelo: ensambla. Un modelo que escribe el prompt de otro modelo añade una
fuente de variación donde justamente hace falta lo contrario, y gasta cuota de la que no sobra.

La idea de fondo: **el prompt de sistema es el examen que va a pasar el código**. El revisor
(agente 4) aplica un catálogo de reglas concreto; el arquitecto mete ese mismo catálogo en el
prompt. Así el implementador sabe de antemano por qué le van a rechazar el parche, que es la forma
barata de que no se lo rechacen.

Cuatro bloques fijos, en este orden, porque es el que aguanta un recorte por presupuesto:

1. **Quién eres y qué se te prohíbe** — las reglas duras, nunca se recorta.
2. **Dónde estás** — el módulo, su dueño, su API pública, sus convenciones.
3. **La valla** — los ficheros que puedes tocar y ninguno más.
4. **El examen** — el formato de salida y el comando que demuestra que has terminado.
"""
from __future__ import annotations

from .contratos import Accion, ContextPack, Encargo, PromptSpec, Severidad

PRESUPUESTO_CARACTERES = 14000

# Qué se le pide de más a cada acción. Es la «especialización» del prompt.
ESPECIALIZACION: dict[Accion, str] = {
    Accion.IMPLEMENTAR: (
        "Escribes código nuevo. Antes de la primera línea, di en una frase qué vas a hacer y qué "
        "has decidido NO hacer. Si el encargo es ambiguo, **no elijas por tu cuenta en algo que "
        "cambie el contrato**: escribe la pregunta y para."
    ),
    Accion.CORREGIR: (
        "Arreglas un fallo. Primero reproduce: di qué línea lo causa y por qué. Después el arreglo "
        "**mínimo**. Añade el caso que fallaba como test, o el arreglo no vale: un fallo sin test "
        "vuelve. No aproveches para limpiar de paso."
    ),
    Accion.REFACTOR: (
        "Cambias la forma, no el comportamiento. Los tests existentes tienen que pasar **sin "
        "tocarlos**: si necesitas cambiar un test, no es un refactor y hay que decirlo."
    ),
    Accion.DOCUMENTAR: (
        "Escribes documentación. Solo lo que has comprobado leyendo el código: cada afirmación, con "
        "su fichero. Lo que supongas va marcado como suposición. No inventes ejemplos que no has "
        "ejecutado."
    ),
    Accion.EXPLICAR: (
        "Respondes una pregunta. No propones cambios ni escribes ficheros. Si la respuesta no está "
        "en el código, dilo en vez de deducirla."
    ),
    Accion.REVISAR: (
        "Revisas código ajeno. Señalas solo lo que rompe una regla del catálogo o un caso límite "
        "concreto, con su línea. Nada de preferencias de estilo."
    ),
}

FORMATO: dict[str, str] = {
    "diff": (
        "FORMATO DE SALIDA — obligatorio.\n"
        "Para cada fichero que toques, un bloque exactamente así:\n\n"
        "```fichero:<ruta/relativa/desde/la/raiz.py>\n"
        "<contenido completo del fichero después del cambio>\n"
        "```\n\n"
        "Contenido **completo**, no fragmentos ni «... resto igual ...»: el revisor lo pasa por "
        "`ast.parse` y un fragmento no compila. Fuera de esos bloques, solo una explicación corta."
    ),
    "texto": "FORMATO DE SALIDA — prosa en español. Sin bloques de fichero: este encargo no toca ficheros.",
}


class ArquitectoDePrompts:
    nombre = "prompt-architect"

    def __init__(self, contexto: ContextPack) -> None:
        self.contexto = contexto

    # ------------------------------------------------------------------ bloques

    def _bloque_reglas(self) -> str:
        duras = [r for r in self.contexto.reglas if r.severidad in (Severidad.BLOQUEA, Severidad.GRAVE)]
        lineas = [
            "Eres un agente de programación dentro de un repositorio PRIVADO de un hackathon.",
            "Trabajas en español. Escribes código sobrio, sin adornos y del mismo estilo que el que ya hay.",
            "",
            "REGLAS DURAS. Romper una de estas hace que el parche se rechace entero:",
        ]
        for r in duras:
            lineas.append(f"  · [{r.clave}] {r.texto}  (fuente: {r.fuente})")
        lineas += [
            "",
            "Y dos que no son de código, pero cuestan igual de caras:",
            "  · Si algo exige publicar, borrar, gastar cuota o dinero, **no lo hagas**: escríbelo y para.",
            "  · Si no sabes algo, dilo. No inventes rutas, funciones, cifras ni fuentes.",
        ]
        return "\n".join(lineas)

    def _bloque_sitio(self, encargo: Encargo) -> str:
        lineas = ["DÓNDE ESTÁS."]
        vistos: set[str] = set()
        for ruta in encargo.ficheros_permitidos:
            m = self.contexto.modulo(ruta.replace("\\", "/").rsplit("/", 1)[0])
            if m is None or m.ruta in vistos:
                continue
            vistos.add(m.ruta)
            lineas.append(
                f"  · `{m.ruta}` — dueño: {m.dueno}. {m.ficheros} ficheros, {m.lineas} líneas, "
                f"{'solo biblioteca estándar' if m.solo_stdlib else 'usa ' + ', '.join(m.importa_externo)}."
            )
            if m.publico:
                muestra = ", ".join(m.publico[:12])
                extra = f" (y {len(m.publico) - 12} más)" if len(m.publico) > 12 else ""
                lineas.append(f"      API pública que ya existe: {muestra}{extra}")
            if m.tests:
                lineas.append(f"      Tests: {', '.join(m.tests)}")
        if not vistos:
            lineas.append("  · Fichero nuevo, fuera de los paquetes existentes.")
        lineas.append("")
        lineas.append("CONVENCIONES DE LA CASA:")
        lineas += [f"  · {c}" for c in self.contexto.convenciones]
        return "\n".join(lineas)

    def _bloque_valla(self, encargo: Encargo) -> str:
        lineas = [
            "LA VALLA. Estos son los únicos ficheros que puedes tocar:",
        ]
        lineas += [f"  · {f}" for f in encargo.ficheros_permitidos] or ["  · (ninguno)"]
        lineas += [
            "",
            "Cualquier otro fichero: **no se toca**, ni para un import, ni para un arreglo obvio, ni "
            "para ordenar. Si de verdad hace falta tocar otro, escribe por qué y para.",
            f"Tamaño máximo del cambio: {encargo.max_lineas} líneas. Si no cabe, el encargo está mal "
            "partido: dilo en vez de entregar medio parche.",
        ]
        congeladas = [f for f in encargo.ficheros_permitidos if "contracts.py" in f or "INTERFACES" in f]
        if congeladas:
            lineas.append(
                "AVISO: el encargo incluye un fichero de contrato congelado "
                f"({', '.join(congeladas)}). Cambiarlo obliga a avisar en `buzon/`: dilo en el resumen."
            )
        return "\n".join(lineas)

    def _bloque_examen(self, encargo: Encargo) -> str:
        formato = FORMATO["texto" if encargo.accion is Accion.EXPLICAR else "diff"]
        lineas = [formato, "", "CÓMO SE COMPRUEBA QUE HAS TERMINADO:"]
        if encargo.comando_prueba:
            lineas.append(f"  $ {encargo.comando_prueba}")
            lineas.append("  Tiene que pasar. Si no lo has podido ejecutar, dilo con esas palabras.")
        else:
            lineas.append("  (este encargo no trae comando de prueba: es un aviso, no una comodidad)")
        lineas += [
            "",
            "Después te revisa un agente automático que comprueba, en este orden: que el Python "
            "compile con `ast.parse`; que no salgas de la valla ni del tamaño; que no haya "
            "credenciales, teléfonos reales ni llamadas peligrosas; y los casos límite de siempre "
            "(`except` pelado, argumento por defecto mutable, red sin tiempo de espera, división sin "
            "guarda). Ese examen lo conoces: apruébalo a la primera.",
        ]
        return "\n".join(lineas)

    # ------------------------------------------------------------------ entrada principal

    def construir(self, encargo: Encargo) -> PromptSpec:
        problemas = encargo.valido()
        bloques: list[tuple[str, str]] = [
            ("reglas", self._bloque_reglas()),
            ("especializacion", "TU TAREA CONCRETA.\n" + ESPECIALIZACION[encargo.accion]),
            ("sitio", self._bloque_sitio(encargo)),
            ("valla", self._bloque_valla(encargo)),
            ("examen", self._bloque_examen(encargo)),
        ]
        if self.contexto.hitos:
            bloques.insert(
                3,
                (
                    "reloj",
                    "EL RELOJ. El proyecto va por fases con hora de corte; propón cambios que quepan "
                    "en una:\n" + "\n".join(f"  · {h}" for h in self.contexto.hitos[:4]),
                ),
            )

        # Recorte por presupuesto: se cae de abajo arriba, y «reglas» nunca se cae.
        recortado: list[str] = []
        while sum(len(b[1]) for b in bloques) > PRESUPUESTO_CARACTERES and len(bloques) > 2:
            for i in range(len(bloques) - 1, 0, -1):
                if bloques[i][0] not in ("reglas", "examen", "valla"):
                    recortado.append(bloques.pop(i)[0])
                    break
            else:
                break

        sistema = "\n\n".join(texto for _, texto in bloques)

        usuario_lineas = [f"ENCARGO ({encargo.huella()}): {encargo.objetivo}"]
        if encargo.contexto_extra:
            usuario_lineas += ["", "CONTEXTO QUE TE DAN:", encargo.contexto_extra]
        if problemas:
            usuario_lineas += [
                "",
                "AVISO: este encargo llega incompleto. Antes de escribir código, di si puedes "
                "seguir igualmente o qué te falta:",
            ] + [f"  · {p}" for p in problemas]
        usuario = "\n".join(usuario_lineas)

        return PromptSpec(
            sistema=sistema,
            usuario=usuario,
            accion=encargo.accion,
            formato_salida="texto" if encargo.accion is Accion.EXPLICAR else "diff",
            piezas=[n for n, _ in bloques],
            caracteres=len(sistema) + len(usuario),
            recortado=recortado,
        )


def construir(contexto: ContextPack, encargo: Encargo) -> PromptSpec:
    return ArquitectoDePrompts(contexto).construir(encargo)
