"""Contrato común del sistema multiagente. Todos los agentes importan de aquí y nadie más define
estos tipos.

Mismas reglas que `motor/contracts.py`: solo biblioteca estándar, todo serializable con `to_dict()`,
y nada de aleatoriedad ni de reloj real dentro de la lógica. El reloj solo aparece en la traza, que
es un registro, no una decisión. Mismo repositorio + mismo encargo = mismo prompt.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol


class _Str(str, Enum):
    def __str__(self) -> str:  # para que el JSON y los logs lleven el valor, no «Clase.MIEMBRO»
        return self.value


class Accion(_Str):
    """Qué se le pide al sistema. El arquitecto de prompts especializa según esto."""

    IMPLEMENTAR = "implementar"  # código nuevo
    CORREGIR = "corregir"        # arreglar un fallo concreto, con su reproducción
    REFACTOR = "refactor"        # mismo comportamiento, mejor forma
    DOCUMENTAR = "documentar"    # README, contrato, comentarios
    EXPLICAR = "explicar"        # no toca ficheros: solo responde
    REVISAR = "revisar"          # solo pasa por el revisor


class Severidad(_Str):
    BLOQUEA = "bloquea"  # no se aplica el parche bajo ningún concepto
    GRAVE = "grave"      # se aplica solo con aprobación humana explícita
    AVISO = "aviso"      # se aplica, pero queda escrito
    NOTA = "nota"        # informativo


class Veredicto(_Str):
    ACEPTA = "acepta"
    ACEPTA_CON_AVISOS = "acepta_con_avisos"
    PIDE_APROBACION = "pide_aprobacion"  # hay algo GRAVE: decide una persona
    RECHAZA = "rechaza"


class ModoProveedor(_Str):
    SECO = "seco"              # sin red: el implementador devuelve el encargo, no el código
    ANTHROPIC = "anthropic"
    OPENAI_COMPAT = "openai_compat"  # Helmcode, AI Gateway, OpenRouter


# --------------------------------------------------------------------------------------- contexto


@dataclass
class Modulo:
    """Un paquete del repositorio, tal y como lo ve el analizador."""

    ruta: str
    dueno: str = "sin dueño declarado"
    ficheros: int = 0
    lineas: int = 0
    publico: list[str] = field(default_factory=list)   # nombres de nivel superior (ast)
    tests: list[str] = field(default_factory=list)     # ficheros test_*.py
    solo_stdlib: bool = True
    importa_externo: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Regla:
    """Una regla dura del proyecto, con su fuente. El revisor solo aplica reglas con fuente."""

    clave: str
    texto: str
    fuente: str
    severidad: Severidad = Severidad.GRAVE

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "severidad": str(self.severidad)}


@dataclass
class ContextPack:
    """Lo que extrae el analizador. Es la entrada de todos los demás agentes."""

    raiz: str
    generado_con: str = ""              # huella del repositorio, no fecha: así es reproducible
    modulos: list[Modulo] = field(default_factory=list)
    reglas: list[Regla] = field(default_factory=list)
    duenos: dict[str, str] = field(default_factory=dict)
    convenciones: list[str] = field(default_factory=list)
    hitos: list[str] = field(default_factory=list)      # guillotinas con hora
    documentos: dict[str, str] = field(default_factory=dict)  # fichero -> primera línea útil
    avisos: list[str] = field(default_factory=list)     # lo que el analizador no pudo leer

    def modulo(self, ruta: str) -> Modulo | None:
        """El módulo más específico que contiene esa ruta.

        Tiene que ser el más largo, no el primero: `motor/server/app.py` está dentro de `motor` y
        de `motor/server`, y la respuesta útil es la segunda.
        """
        candidatos = [m for m in self.modulos if m.ruta == ruta or ruta.startswith(m.ruta + "/")]
        return max(candidatos, key=lambda m: len(m.ruta)) if candidatos else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raiz": self.raiz,
            "generado_con": self.generado_con,
            "modulos": [m.to_dict() for m in self.modulos],
            "reglas": [r.to_dict() for r in self.reglas],
            "duenos": self.duenos,
            "convenciones": self.convenciones,
            "hitos": self.hitos,
            "documentos": self.documentos,
            "avisos": self.avisos,
        }


# ----------------------------------------------------------------------------------------- encargo


@dataclass
class Encargo:
    """Un trabajo para el sistema. Es la unidad de `buzon/`: objetivo, valla y prueba.

    Los tres campos obligatorios salen de la regla del equipo (MVP.md §2.3): sin el comando de
    prueba, un agente dice que ha terminado y no hay forma de saberlo.
    """

    objetivo: str
    ficheros_permitidos: list[str] = field(default_factory=list)
    comando_prueba: str = ""
    accion: Accion = Accion.IMPLEMENTAR
    contexto_extra: str = ""
    max_lineas: int = 400          # límite de tamaño del parche
    pide_aprobacion_humana: bool = False

    def valido(self) -> list[str]:
        """Devuelve la lista de problemas del encargo. Vacía = el encargo se puede ejecutar."""
        problemas: list[str] = []
        if len(self.objetivo.strip()) < 15:
            problemas.append("el objetivo tiene menos de 15 caracteres: no es un encargo, es un deseo")
        if self.accion is not Accion.EXPLICAR and not self.ficheros_permitidos:
            problemas.append("sin `ficheros_permitidos` no hay valla: el agente puede tocar cualquier cosa")
        if self.accion in (Accion.IMPLEMENTAR, Accion.CORREGIR, Accion.REFACTOR) and not self.comando_prueba:
            problemas.append("sin `comando_prueba` no hay forma de comprobar que ha terminado")
        return problemas

    def huella(self) -> str:
        crudo = json.dumps(
            {
                "objetivo": self.objetivo,
                "ficheros": sorted(self.ficheros_permitidos),
                "prueba": self.comando_prueba,
                "accion": str(self.accion),
                "extra": self.contexto_extra,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "accion": str(self.accion), "huella": self.huella()}


@dataclass
class PromptSpec:
    """Lo que produce el arquitecto: el prompt de sistema y el de usuario, ya especializados."""

    sistema: str
    usuario: str
    accion: Accion = Accion.IMPLEMENTAR
    formato_salida: str = "diff"
    piezas: list[str] = field(default_factory=list)   # qué bloques se han metido, para auditar
    caracteres: int = 0
    recortado: list[str] = field(default_factory=list)  # qué se dejó fuera por presupuesto

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "accion": str(self.accion)}


# ------------------------------------------------------------------------------------ implementación


@dataclass
class FicheroPropuesto:
    ruta: str
    contenido: str
    modo: str = "crear"  # crear | reemplazar | parchear

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Parche:
    """Lo que produce el implementador. En modo seco lleva `encargo_para_humano` y ningún fichero."""

    ficheros: list[FicheroPropuesto] = field(default_factory=list)
    resumen: str = ""
    proveedor: ModoProveedor = ModoProveedor.SECO
    modelo: str = ""
    encargo_para_humano: str = ""
    crudo: str = ""   # respuesta literal del modelo, para poder auditar

    @property
    def vacio(self) -> bool:
        return not self.ficheros

    def lineas(self) -> int:
        return sum(f.contenido.count("\n") + 1 for f in self.ficheros)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ficheros": [f.to_dict() for f in self.ficheros],
            "resumen": self.resumen,
            "proveedor": str(self.proveedor),
            "modelo": self.modelo,
            "lineas": self.lineas(),
            "encargo_para_humano": self.encargo_para_humano,
        }


# --------------------------------------------------------------------------------------- revisión


@dataclass
class Aviso:
    """Un hallazgo del revisor. Siempre lleva regla y fuente: no hay opiniones sueltas."""

    severidad: Severidad
    regla: str
    mensaje: str
    fichero: str = ""
    linea: int = 0
    fuente: str = ""

    def __str__(self) -> str:
        donde = f"{self.fichero}:{self.linea}" if self.fichero else "-"
        return f"[{self.severidad}] {self.regla} · {donde} · {self.mensaje}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "severidad": str(self.severidad)}


@dataclass
class Revision:
    veredicto: Veredicto = Veredicto.ACEPTA
    avisos: list[Aviso] = field(default_factory=list)
    comprobaciones: list[str] = field(default_factory=list)  # qué se miró, aunque saliera limpio

    def por_severidad(self, s: Severidad) -> list[Aviso]:
        return [a for a in self.avisos if a.severidad is s]

    def resolver(self) -> Veredicto:
        """El veredicto sale de los avisos, no de una opinión: así es reproducible."""
        if self.por_severidad(Severidad.BLOQUEA):
            self.veredicto = Veredicto.RECHAZA
        elif self.por_severidad(Severidad.GRAVE):
            self.veredicto = Veredicto.PIDE_APROBACION
        elif self.por_severidad(Severidad.AVISO):
            self.veredicto = Veredicto.ACEPTA_CON_AVISOS
        else:
            self.veredicto = Veredicto.ACEPTA
        return self.veredicto

    def to_dict(self) -> dict[str, Any]:
        return {
            "veredicto": str(self.veredicto),
            "avisos": [a.to_dict() for a in self.avisos],
            "comprobaciones": self.comprobaciones,
        }


# ------------------------------------------------------------------------------------------ traza


@dataclass
class PasoTraza:
    agente: str
    entrada: str
    salida: str
    ms: int = 0
    notas: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Traza:
    """Registro auditable de una pasada completa. Es lo que se enseña, no lo que se cuenta."""

    encargo: str = ""
    pasos: list[PasoTraza] = field(default_factory=list)
    veredicto: Veredicto = Veredicto.ACEPTA

    def anotar(self, agente: str, entrada: str, salida: str, ms: int = 0, notas: list[str] | None = None) -> None:
        self.pasos.append(PasoTraza(agente, entrada, salida, ms, notas or []))

    def to_dict(self) -> dict[str, Any]:
        return {
            "encargo": self.encargo,
            "veredicto": str(self.veredicto),
            "pasos": [p.to_dict() for p in self.pasos],
        }


# --------------------------------------------------------------------------------------- proveedor


@dataclass
class Respuesta:
    texto: str
    modelo: str = ""
    proveedor: ModoProveedor = ModoProveedor.SECO
    tokens_entrada: int = 0
    tokens_salida: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class Proveedor(Protocol):
    """Lo que necesita el implementador. Ningún agente construye un cliente por su cuenta:
    se le inyecta uno, igual que en `motor/`."""

    nombre: str
    modo: ModoProveedor

    def disponible(self) -> tuple[bool, str]: ...

    def completar(self, sistema: str, usuario: str, max_tokens: int = 4000) -> Respuesta: ...
