"""Catálogo de reglas duras del proyecto, en un solo sitio.

Cada regla lleva **su fuente**. Es a propósito: el revisor no tiene opiniones, aplica reglas que
alguien escribió en un fichero que se puede abrir. Si una regla no tiene fuente, no entra aquí.

Las usa `revisor.py` para decidir, y `arquitecto.py` para meterlas en el prompt de sistema: así el
implementador conoce de antemano el examen que va a pasar, que es la forma barata de aprobarlo.
"""
from __future__ import annotations

import re

from .contratos import Regla, Severidad

# --------------------------------------------------------------------------- reglas del proyecto

CATALOGO: list[Regla] = [
    Regla(
        "privacidad-repo",
        "Este repositorio es privado. Nada de aquí se copia al repositorio público, ni a gists, "
        "pastebins o servicios externos, hasta la entrega final.",
        "AGENTS.md regla 1",
        Severidad.BLOQUEA,
    ),
    Regla(
        "sin-secretos",
        "Ningún secreto en el repositorio: claves de API, tokens, teléfonos reales o el código de "
        "acceso a la documentación. Van en variables de entorno o en ficheros ignorados por git.",
        "AGENTS.md regla 3",
        Severidad.BLOQUEA,
    ),
    Regla(
        "permiso-humano",
        "Publicar, borrar, gastar cuota o dinero, tocar el repositorio público y enviar texto del "
        "proyecto a un servicio externo son decisiones de una persona, no del agente.",
        "AGENTS.md; reglas del proyecto",
        Severidad.GRAVE,
    ),
    Regla(
        "nucleo-determinista",
        "El núcleo (`motor/world`, `motor/mando`, `motor/cases`) es determinista y auditable a "
        "propósito: mismo caso y misma semilla, misma ejecución. Ni reloj real, ni aleatoriedad sin "
        "semilla, ni llamadas de red dentro del bucle de decisión.",
        "motor/contracts.py; reglas del motor",
        Severidad.GRAVE,
    ),
    Regla(
        "sin-llm-en-decision",
        "Ningún módulo del núcleo llama a una API de modelo por su cuenta: se le inyecta un cliente. "
        "El modelo va donde hay lenguaje, no donde hay que decidir.",
        "reglas del motor",
        Severidad.GRAVE,
    ),
    Regla(
        "solo-stdlib-en-nucleo",
        "El núcleo usa solo biblioteca estándar. Las dependencias viven en `motor/server`.",
        "README.md; INSTRUCCIONES.md §1",
        Severidad.AVISO,
    ),
    Regla(
        "contrato-congelado",
        "`motor/contracts.py` y `motor/INTERFACES.md` no se modifican sin avisar en el buzón.",
        "AGENTS.md",
        Severidad.GRAVE,
    ),
    Regla(
        "acciones-graves-con-aprobacion",
        "Evacuar, parar el concierto, avisar a servicios externos y cerrar una zona no se ejecutan "
        "sin aprobación humana registrada. El marcador de acciones inseguras se queda en cero.",
        "motor/happyrobot/NORTHSTARS.md",
        Severidad.BLOQUEA,
    ),
    Regla(
        "cifras-con-n",
        "Toda cifra lleva su N y su intervalo, y las de simulación se rotulan como tales. No se "
        "afirma «aprende» si los intervalos se solapan.",
        "reglas de medición D7",
        Severidad.AVISO,
    ),
    Regla(
        "cli-del-evento",
        "Prohibido `hackspain watch`. `hackspain submit` siempre con `--draft` hasta la entrega "
        "final, y nunca con `-y`.",
        "reglas del proyecto; entrega/REQUISITOS.md",
        Severidad.BLOQUEA,
    ),
    Regla(
        "adversarios-aislados",
        "Los escenarios adversarios se ejecutan en `agent_isolated`. `whole_run` dispara llamadas, "
        "SMS y webhooks de verdad.",
        "motor/happyrobot/TESTS.md",
        Severidad.BLOQUEA,
    ),
    Regla(
        "cluster-eu",
        "Todo lo de HappyRobot va al clúster EU (`platform.eu.happyrobot.ai`). Con el valor por "
        "defecto la misma clave responde 401 o 404: es el fallo número uno.",
        "motor/happyrobot/DOCS_CONFIRMADO.md",
        Severidad.AVISO,
    ),
    Regla(
        "sin-emergencias-reales",
        "Nunca se marca un número de emergencias real. El «112» de la demo es un móvil del equipo.",
        "INSTRUCCIONES.md §5",
        Severidad.BLOQUEA,
    ),
]

POR_CLAVE: dict[str, Regla] = {r.clave: r for r in CATALOGO}


# ------------------------------------------------------------------- patrones que busca el revisor

# Secretos. Se busca la **forma** de la credencial, no la palabra «clave»: así no saltan los
# comentarios que hablan de claves ni los nombres de variables de entorno, que son inocentes.
#
# Dos niveles a propósito. Lo que tiene forma de credencial de verdad (`sk-ant-…`, `hr_live_…`)
# bloquea pase lo que pase: nadie escribe eso por accidente. El patrón genérico («una variable que
# se llama SECRET con un literal dentro») avisa, porque el repositorio está lleno de
# `SECRET = "secreto-de-prueba"` legítimos y un revisor que bloquea por eso se desactiva el primer
# día, que es la única forma segura de que no encuentre el que sí importa.
PATRONES_SECRETO: list[tuple[str, str, Severidad]] = [
    (r"sk-ant-[A-Za-z0-9_\-]{20,}", "clave de Anthropic escrita en el fichero", Severidad.BLOQUEA),
    (r"sk-[A-Za-z0-9]{32,}", "clave con forma de OpenAI escrita en el fichero", Severidad.BLOQUEA),
    (r"hr_(live|test)_[A-Za-z0-9]{10,}", "clave de HappyRobot escrita en el fichero", Severidad.BLOQUEA),
    (r"xoxb-[A-Za-z0-9\-]{10,}", "token de Slack escrito en el fichero", Severidad.BLOQUEA),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "token de GitHub escrito en el fichero", Severidad.BLOQUEA),
    (r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.", "JSON Web Token escrito en el fichero", Severidad.BLOQUEA),
    (r"(?<![\d/\-])\+34[\s\-]?[6-9]\d{8}\b", "teléfono español real escrito en el fichero", Severidad.BLOQUEA),
    (
        r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*[\"'][^\"'{}$\s]{12,}[\"']",
        "una variable de credencial con un literal dentro: comprobar que no es real",
        Severidad.AVISO,
    ),
]

# Marcas de valor de relleno. Si el literal lleva una de estas, el patrón genérico baja a nota.
RELLENOS = (
    "prueba", "test", "ejemplo", "example", "dummy", "fake", "placeholder", "changeme",
    "cambiame", "xxxx", "tu-clave", "your-", "<", "…", "...",
)

# Llamadas peligrosas, por nombre de función.
LLAMADAS_PELIGROSAS: dict[str, tuple[Severidad, str]] = {
    "eval": (Severidad.BLOQUEA, "`eval` ejecuta lo que le den: con un aviso del público delante, es una puerta abierta"),
    "exec": (Severidad.BLOQUEA, "`exec` ejecuta lo que le den"),
    "compile": (Severidad.GRAVE, "`compile` sobre texto que no controlamos es ejecución de código"),
    "__import__": (Severidad.GRAVE, "importación dinámica: difícil de auditar"),
    "system": (Severidad.GRAVE, "`os.system` lanza una orden del sistema sin escapar nada"),
    "popen": (Severidad.GRAVE, "`os.popen` lanza una orden del sistema sin escapar nada"),
    "loads_pickle": (Severidad.BLOQUEA, "`pickle.loads` sobre datos ajenos ejecuta código"),
}

# Órdenes prohibidas del evento, por si aparecen en un script o en documentación generada.
#
# El tercer campo dice si el patrón hay que **anclar** a algo que parezca de verdad una orden. Hace
# falta porque este mismo fichero escribe «Prohibido `hackspain watch`» al describir la regla, y un
# revisor que se marca su propio catálogo no sirve de puerta. Anclado = desde el principio de la
# línea hasta la orden no hay ninguna letra: vale `$ hackspain watch` o la orden sola, no vale una
# frase que la mencione. El precio es que no se detecta dentro de una cadena como
# `run("hackspain submit")`, y queda dicho en NO-IMPLEMENTADO.md.
ANCLA_ORDEN = r"^[^A-Za-zÀ-ÿ]*"

# Salida de emergencia, en la propia línea y **con motivo obligatorio**:
#
#     JEFE = "+34612345678"  # revisor: ok teléfono inventado para el test del escáner
#
# Hace falta porque los tests del escáner tienen que escribir cosas con forma de credencial, y sin
# esto el revisor rechaza para siempre su propio paquete, que es la forma segura de que alguien lo
# desactive. Sin motivo no vale: obligar a escribir por qué es lo que separa una excepción
# justificada de un «cállate», y queda en el diff para que alguien la discuta.
MARCA_PERDON = re.compile(r"#\s*revisor:\s*ok\s+(?P<motivo>\S.*)$")


def perdonada(linea: str) -> str:
    """Devuelve el motivo si la línea lleva la marca con explicación; cadena vacía si no."""
    m = MARCA_PERDON.search(linea)
    return m.group("motivo").strip() if m else ""

ORDENES_PROHIBIDAS: list[tuple[str, str, Severidad, bool]] = [
    (r"hackspain\s+watch", "cli-del-evento", Severidad.BLOQUEA, True),
    (r"hackspain\s+submit(?![^\n]*--draft)", "cli-del-evento", Severidad.BLOQUEA, True),
    (r"hackspain\s+submit[^\n]*\s-y\b", "cli-del-evento", Severidad.BLOQUEA, True),
    (r"git\s+push\s+--force", "permiso-humano", Severidad.GRAVE, True),
    (r"hackspain\s+--json[^\n|]*\|\s*jq", "cli-del-evento", Severidad.AVISO, True),
    # Este sí va sin anclar: es un valor de configuración, no una orden, y da igual dónde aparezca.
    (r"[\"']whole_run[\"']", "adversarios-aislados", Severidad.BLOQUEA, False),
]

# Rutas del núcleo, donde el determinismo es obligatorio.
RUTAS_NUCLEO = ("motor/world", "motor/mando", "motor/cases", "motor/caos", "motor/baseline")

# Rutas que nadie toca sin avisar en el buzón.
RUTAS_CONGELADAS = ("motor/contracts.py", "motor/INTERFACES.md")


def es_nucleo(ruta: str) -> bool:
    limpia = ruta.replace("\\", "/")
    return any(limpia.startswith(p) for p in RUTAS_NUCLEO)


def es_congelada(ruta: str) -> bool:
    limpia = ruta.replace("\\", "/")
    return any(limpia == p or limpia.endswith("/" + p) for p in RUTAS_CONGELADAS)


def buscar_secretos(texto: str) -> list[tuple[int, str, str, Severidad]]:
    """Devuelve (línea, descripción, fragmento recortado, severidad).

    El fragmento **nunca sale entero**: se enseñan los seis primeros caracteres, lo justo para
    encontrarlo en el fichero sin volver a escribir el secreto en un informe, un log o un pitch.
    """
    hallazgos: list[tuple[int, str, str, Severidad]] = []
    for numero, linea in enumerate(texto.splitlines(), 1):
        for patron, descripcion, severidad in PATRONES_SECRETO:
            m = re.search(patron, linea)
            if not m:
                continue
            trozo = m.group(0)
            sev = severidad
            if severidad is Severidad.AVISO and any(r in trozo.lower() for r in RELLENOS):
                sev = Severidad.NOTA
            hallazgos.append((numero, descripcion, trozo[:6] + "…" if len(trozo) > 6 else "…", sev))
    return hallazgos


def buscar_ordenes_prohibidas(texto: str) -> list[tuple[int, str, Severidad, str]]:
    hallazgos: list[tuple[int, str, Severidad, str]] = []
    for numero, linea in enumerate(texto.splitlines(), 1):
        for patron, clave, severidad, anclar in ORDENES_PROHIBIDAS:
            completo = (ANCLA_ORDEN if anclar else "") + patron
            if re.search(completo, linea):
                hallazgos.append((numero, clave, severidad, linea.strip()[:100]))
    return hallazgos
