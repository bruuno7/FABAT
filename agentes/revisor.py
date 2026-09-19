"""Agente 4 — **Code Reviewer**. Valida sintaxis, límites, seguridad y casos límite.

Determinista de arriba abajo: no llama a ningún modelo. Eso no es una limitación, es lo que hace
que sirva de puerta. Un revisor que a veces aprueba y a veces no el mismo código no es una puerta,
es una opinión; y el veredicto sale de los avisos por una regla fija (`Revision.resolver`), no de
un juicio.

Cuatro pasadas, en el orden en que conviene fallar:

1. **Sintaxis** — `ast.parse`. Si no compila, lo demás sobra.
2. **Límites** — la valla de ficheros, el tamaño, las rutas congeladas y las del núcleo.
3. **Seguridad** — credenciales, teléfonos reales, llamadas peligrosas, órdenes prohibidas del evento.
4. **Casos límite** — lo que se rompe con el jurado delante: `except` pelado, red sin tiempo de
   espera, argumento por defecto mutable, división sin guarda, reloj y azar en el núcleo.
"""
from __future__ import annotations

import ast
from pathlib import Path

from . import reglas
from .analizador import IGNORAR_DIR
from .contratos import Aviso, Encargo, Parche, Revision, Severidad


class RevisorDeCodigo:
    nombre = "code-reviewer"

    def __init__(self, encargo: Encargo | None = None) -> None:
        self.encargo = encargo

    # ------------------------------------------------------------------ entradas

    def revisar_parche(self, parche: Parche) -> Revision:
        rev = Revision()
        rev.comprobaciones = ["sintaxis", "limites", "seguridad", "casos-limite"]

        if parche.vacio:
            rev.avisos.append(
                Aviso(
                    Severidad.NOTA,
                    "parche-vacio",
                    "no hay ficheros que revisar"
                    + (" (modo seco: el encargo se ejecuta a mano)" if parche.encargo_para_humano else ""),
                )
            )
            rev.resolver()
            return rev

        self._limites_del_parche(parche, rev)
        for f in parche.ficheros:
            self._revisar_texto(f.ruta, f.contenido, rev)
        rev.resolver()
        return rev

    def revisar_ruta(self, ruta: str | Path) -> Revision:
        """Revisa un fichero o una carpeta que ya está en disco.

        Se salta las carpetas de `IGNORAR_DIR`, y con `.venv` dentro no es un detalle: sin esto el
        revisor audita pydantic y anyio, saca doce bloqueos que no son nuestros y el veredicto deja
        de significar nada.
        """
        p = Path(ruta)
        rev = Revision()
        rev.comprobaciones = ["sintaxis", "seguridad", "casos-limite"]
        if p.is_dir():
            objetivos = sorted(
                f for f in p.rglob("*.py")
                if not any(parte in IGNORAR_DIR or parte.endswith((".venv", "-env")) for parte in f.parts)
            )
        else:
            objetivos = [p]
        for f in objetivos:
            try:
                texto = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                rev.avisos.append(Aviso(Severidad.AVISO, "ilegible", f"no se puede leer: {e}", str(f)))
                continue
            self._revisar_texto(f.as_posix(), texto, rev)
        rev.resolver()
        return rev

    # ------------------------------------------------------------------ 2 · límites

    def _limites_del_parche(self, parche: Parche, rev: Revision) -> None:
        if self.encargo is None:
            return
        permitidos = {f.replace("\\", "/") for f in self.encargo.ficheros_permitidos}
        for f in parche.ficheros:
            if permitidos and f.ruta not in permitidos:
                rev.avisos.append(
                    Aviso(
                        Severidad.BLOQUEA,
                        "fuera-de-la-valla",
                        f"el parche toca «{f.ruta}», que no está en los ficheros permitidos "
                        f"({', '.join(sorted(permitidos)) or 'ninguno'})",
                        f.ruta,
                        fuente="Encargo.ficheros_permitidos",
                    )
                )
            if reglas.es_congelada(f.ruta):
                rev.avisos.append(
                    Aviso(
                        Severidad.GRAVE,
                        "contrato-congelado",
                        "cambia un contrato congelado: hay que avisar en `buzon/` antes de aplicarlo",
                        f.ruta,
                        fuente=reglas.POR_CLAVE["contrato-congelado"].fuente,
                    )
                )
        total = parche.lineas()
        if total > self.encargo.max_lineas:
            rev.avisos.append(
                Aviso(
                    Severidad.GRAVE,
                    "parche-demasiado-grande",
                    f"{total} líneas frente a un máximo de {self.encargo.max_lineas}: "
                    "un parche así no se revisa de madrugada, se parte",
                    fuente="Encargo.max_lineas",
                )
            )

    # ------------------------------------------------------------------ pasada por fichero

    def _revisar_texto(self, ruta: str, texto: str, rev: Revision) -> None:
        self._seguridad_textual(ruta, texto, rev)
        if not ruta.endswith(".py"):
            return
        try:
            arbol = ast.parse(texto, filename=ruta)
        except SyntaxError as e:
            rev.avisos.append(
                Aviso(
                    Severidad.BLOQUEA,
                    "sintaxis",
                    f"no compila: {e.msg}",
                    ruta,
                    e.lineno or 0,
                    "ast.parse",
                )
            )
            return
        self._seguridad_ast(ruta, arbol, rev)
        self._casos_limite(ruta, arbol, rev)

    # ------------------------------------------------------------------ 3 · seguridad

    def _seguridad_textual(self, ruta: str, texto: str, rev: Revision) -> None:
        lineas = texto.splitlines()

        def perdon(n: int) -> str:
            return reglas.perdonada(lineas[n - 1]) if 0 < n <= len(lineas) else ""

        for linea, descripcion, trozo, severidad in reglas.buscar_secretos(texto):
            motivo = perdon(linea)
            if motivo:
                # Perdonada, pero no borrada: queda como nota para que se pueda auditar la excepción.
                rev.avisos.append(
                    Aviso(Severidad.NOTA, "perdonada", f"{descripcion} — perdonada: {motivo}", ruta, linea)
                )
                continue
            cola = (
                ". Va a una variable de entorno, no al repositorio"
                if severidad is Severidad.BLOQUEA
                else ""
            )
            rev.avisos.append(
                Aviso(
                    severidad,
                    "sin-secretos",
                    f"{descripcion} (empieza por «{trozo}»){cola}",
                    ruta,
                    linea,
                    reglas.POR_CLAVE["sin-secretos"].fuente,
                )
            )
        for linea, clave, severidad, fragmento in reglas.buscar_ordenes_prohibidas(texto):
            motivo = perdon(linea)
            if motivo:
                rev.avisos.append(
                    Aviso(Severidad.NOTA, "perdonada", f"{clave} — perdonada: {motivo}", ruta, linea)
                )
                continue
            regla = reglas.POR_CLAVE.get(clave)
            rev.avisos.append(
                Aviso(
                    severidad,
                    clave,
                    f"orden prohibida por las reglas del proyecto: `{fragmento}`",
                    ruta,
                    linea,
                    regla.fuente if regla else "",
                )
            )

    def _seguridad_ast(self, ruta: str, arbol: ast.AST, rev: Revision) -> None:
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            nombre = _nombre_llamada(nodo)
            base = nombre.rsplit(".", 1)[-1]

            if base in ("eval", "exec") and "." not in nombre:
                sev, motivo = reglas.LLAMADAS_PELIGROSAS[base]
                rev.avisos.append(Aviso(sev, "llamada-peligrosa", motivo, ruta, nodo.lineno, "reglas.py"))
            elif nombre in ("os.system", "os.popen"):
                sev, motivo = reglas.LLAMADAS_PELIGROSAS[base]
                rev.avisos.append(Aviso(sev, "llamada-peligrosa", motivo, ruta, nodo.lineno, "reglas.py"))
            elif nombre in ("pickle.loads", "pickle.load"):
                rev.avisos.append(
                    Aviso(
                        Severidad.BLOQUEA,
                        "llamada-peligrosa",
                        "`pickle` sobre datos que no controlamos ejecuta código: usa JSON",
                        ruta,
                        nodo.lineno,
                        "reglas.py",
                    )
                )
            elif base == "run" and "subprocess" in nombre or base in ("Popen", "check_output", "call"):
                if any(k.arg == "shell" and getattr(k.value, "value", False) is True for k in nodo.keywords):
                    rev.avisos.append(
                        Aviso(
                            Severidad.GRAVE,
                            "shell-true",
                            "`shell=True` con texto que venga de fuera es inyección de órdenes",
                            ruta,
                            nodo.lineno,
                            "reglas.py",
                        )
                    )
            elif nombre.endswith("yaml.load") and not nodo.keywords:
                rev.avisos.append(
                    Aviso(Severidad.GRAVE, "yaml-inseguro", "usa `yaml.safe_load`", ruta, nodo.lineno)
                )

    # ------------------------------------------------------------------ 4 · casos límite

    def _casos_limite(self, ruta: str, arbol: ast.AST, rev: Revision) -> None:
        nucleo = reglas.es_nucleo(ruta)

        for nodo in ast.walk(arbol):
            # `except:` pelado — se traga hasta el Ctrl-C, y de madrugada eso es media hora perdida.
            if isinstance(nodo, ast.ExceptHandler) and nodo.type is None:
                rev.avisos.append(
                    Aviso(
                        Severidad.AVISO,
                        "except-pelado",
                        "`except:` sin tipo se traga KeyboardInterrupt y SystemExit: di qué esperas",
                        ruta,
                        nodo.lineno,
                    )
                )
            # `except ...: pass` — el fallo desaparece sin dejar rastro.
            if isinstance(nodo, ast.ExceptHandler) and len(nodo.body) == 1 and isinstance(nodo.body[0], ast.Pass):
                rev.avisos.append(
                    Aviso(
                        Severidad.AVISO,
                        "error-silencioso",
                        "el error se descarta sin dejar rastro. En la medición, un error cuenta como "
                        "fallo: nunca desaparece del N",
                        ruta,
                        nodo.lineno,
                        "reglas de medición D7",
                    )
                )
            # Argumento por defecto mutable.
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in list(nodo.args.defaults) + [d for d in nodo.args.kw_defaults if d]:
                    if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                        rev.avisos.append(
                            Aviso(
                                Severidad.AVISO,
                                "defecto-mutable",
                                f"`{nodo.name}` tiene un argumento por defecto mutable: se comparte "
                                "entre llamadas y da fallos que no se reproducen",
                                ruta,
                                nodo.lineno,
                            )
                        )
                        break
            # División por algo que de verdad puede valer cero.
            if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                sospechoso = _denominador_sospechoso(nodo.right)
                if sospechoso:
                    rev.avisos.append(
                        Aviso(
                            Severidad.NOTA,
                            "division-sin-guarda",
                            f"divides por {sospechoso}, que vale cero en cuanto la lista esté vacía. "
                            "Es la media que revienta la pantalla con el jurado delante",
                            ruta,
                            nodo.lineno,
                        )
                    )
            if isinstance(nodo, ast.Call):
                nombre = _nombre_llamada(nodo)
                # Red sin tiempo de espera: el fallo que deja la demo colgada sin mensaje.
                if nombre.endswith(("urlopen", "requests.get", "requests.post", "httpx.get", "httpx.post")):
                    if not any(k.arg in ("timeout", "timeout_s") for k in nodo.keywords):
                        rev.avisos.append(
                            Aviso(
                                Severidad.GRAVE,
                                "red-sin-tiempo-de-espera",
                                "llamada de red sin `timeout`: con mala wifi, la pantalla se queda "
                                "colgada y no dice por qué",
                                ruta,
                                nodo.lineno,
                            )
                        )
                # Reloj y azar dentro del núcleo determinista.
                if nucleo:
                    if nombre in ("datetime.now", "datetime.utcnow", "time.time", "time.monotonic"):
                        rev.avisos.append(
                            Aviso(
                                Severidad.GRAVE,
                                "nucleo-determinista",
                                f"`{nombre}` en el núcleo: el tiempo es siempre `t`, minutos enteros "
                                "desde el inicio. Con reloj real la partida deja de reproducirse",
                                ruta,
                                nodo.lineno,
                                reglas.POR_CLAVE["nucleo-determinista"].fuente,
                            )
                        )
                    if nombre.startswith("random.") and nombre != "random.Random":
                        rev.avisos.append(
                            Aviso(
                                Severidad.GRAVE,
                                "nucleo-determinista",
                                f"`{nombre}` usa el azar global: en el núcleo se pasa un `Random(semilla)`",
                                ruta,
                                nodo.lineno,
                                reglas.POR_CLAVE["nucleo-determinista"].fuente,
                            )
                        )
            # Red o cliente de modelo dentro del núcleo.
            if nucleo and isinstance(nodo, (ast.Import, ast.ImportFrom)):
                modulos = (
                    [a.name for a in nodo.names]
                    if isinstance(nodo, ast.Import)
                    else ([nodo.module] if nodo.module else [])
                )
                for mod in modulos:
                    raiz = (mod or "").split(".")[0]
                    if raiz in ("urllib", "http", "socket", "requests", "httpx"):
                        rev.avisos.append(
                            Aviso(
                                Severidad.GRAVE,
                                "sin-llm-en-decision",
                                f"el núcleo importa `{mod}`: ningún módulo del núcleo habla por su "
                                "cuenta con el exterior, se le inyecta un cliente",
                                ruta,
                                nodo.lineno,
                                reglas.POR_CLAVE["sin-llm-en-decision"].fuente,
                            )
                        )
                    if raiz in ("anthropic", "openai"):
                        rev.avisos.append(
                            Aviso(
                                Severidad.BLOQUEA,
                                "sin-llm-en-decision",
                                f"cliente de modelo (`{mod}`) dentro del núcleo determinista",
                                ruta,
                                nodo.lineno,
                                reglas.POR_CLAVE["sin-llm-en-decision"].fuente,
                            )
                        )


# Nombres de denominador que suelen valer cero. Marcar **toda** división por una variable daba 131
# avisos en `motor/` de los que ninguno era accionable, y una regla con ese ruido enseña a no leer
# el informe. Estrechada a esto quedan los pocos que importan: la media de una lista vacía.
_DENOMINADOR_CERO = ("len", "sum", "count")
_NOMBRE_CONTADOR = ("total", "count", "cuenta", "num", "n_", "size", "denom", "muestras")


def _denominador_sospechoso(nodo: ast.expr) -> str:
    """Describe el denominador si puede valer cero; cadena vacía si no hay motivo para avisar."""
    if isinstance(nodo, ast.Call):
        nombre = _nombre_llamada(nodo)
        if nombre.rsplit(".", 1)[-1] in _DENOMINADOR_CERO:
            return f"`{nombre}(…)`"
    if isinstance(nodo, ast.Name):
        bajo = nodo.id.lower()
        if bajo == "n" or any(p in bajo for p in _NOMBRE_CONTADOR):
            return f"`{nodo.id}`"
    return ""


def _nombre_llamada(nodo: ast.Call) -> str:
    """`os.system(...)` → `os.system`; `foo()` → `foo`. Devuelve cadena vacía si es raro."""
    partes: list[str] = []
    actual: ast.AST = nodo.func
    while isinstance(actual, ast.Attribute):
        partes.append(actual.attr)
        actual = actual.value
    if isinstance(actual, ast.Name):
        partes.append(actual.id)
    return ".".join(reversed(partes))


def revisar_parche(parche: Parche, encargo: Encargo | None = None) -> Revision:
    return RevisorDeCodigo(encargo).revisar_parche(parche)


def revisar_ruta(ruta: str | Path) -> Revision:
    return RevisorDeCodigo().revisar_ruta(ruta)
