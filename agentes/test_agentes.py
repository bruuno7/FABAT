"""Tests del sistema multiagente. Solo `unittest`, como el resto del repositorio.

    python -m unittest agentes.test_agentes -v

Lo que se comprueba, y por qué: de los cuatro agentes, tres son deterministas, así que se pueden
probar de verdad. El cuarto (el implementador) se prueba con un proveedor falso, sin red ni gasto:
así el test pasa igual en la sede con la wifi caída, que es cuando hará falta.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .analizador import AnalizadorDeContexto
from .arquitecto import ArquitectoDePrompts
from .contratos import (
    Accion,
    ContextPack,
    Encargo,
    FicheroPropuesto,
    ModoProveedor,
    Parche,
    Respuesta,
    Severidad,
    Veredicto,
)
from .implementador import Implementador, extraer_ficheros
from .orquestador import Orquestador
from .proveedores import ProveedorSeco
from .revisor import RevisorDeCodigo

RAIZ = Path(__file__).resolve().parent.parent

# Cadenas con forma de credencial, para probar el escáner. Se arman **por trozos** a propósito: así
# este fichero no contiene ninguna credencial completa y el revisor no tiene nada que perdonar. Es
# la misma razón por la que existe la marca `# revisor: ok`, pero sin gastar la excepción.
TELEFONO_FALSO = "+34" + "612345678"
CLAVE_HR_FALSA = "hr_" + "live_" + "supersecreto12345"
CLAVE_ANTHROPIC_FALSA = "sk-" + "ant-api03-" + "a" * 40


def encargo_de_prueba(**kwargs) -> Encargo:
    base = {
        "objetivo": "añadir una comprobación de aforo por sector al planificador",
        "ficheros_permitidos": ["motor/mando/planner.py"],
        "comando_prueba": "python -m unittest motor.mando.test_mando",
        "accion": Accion.IMPLEMENTAR,
    }
    base.update(kwargs)
    return Encargo(**base)


class ProveedorFalso:
    """Devuelve lo que se le diga. Sin red y sin gasto."""

    nombre = "falso"
    modo = ModoProveedor.OPENAI_COMPAT

    def __init__(self, texto: str = "", error: str = "") -> None:
        self.texto = texto
        self.error = error

    def disponible(self):
        return not self.error, "proveedor de prueba"

    def completar(self, sistema, usuario, max_tokens=4000):
        self.ultimo_sistema = sistema
        return Respuesta(self.texto, "falso-1", self.modo, error=self.error)


# ------------------------------------------------------------------------------------ el encargo


class TestEncargo(unittest.TestCase):
    def test_un_encargo_completo_es_valido(self):
        self.assertEqual(encargo_de_prueba().valido(), [])

    def test_sin_valla_ni_prueba_se_queja(self):
        problemas = Encargo(objetivo="hacer que funcione mejor todo esto").valido()
        self.assertEqual(len(problemas), 2)
        self.assertTrue(any("ficheros_permitidos" in p for p in problemas))
        self.assertTrue(any("comando_prueba" in p for p in problemas))

    def test_objetivo_vacio_no_es_encargo(self):
        self.assertTrue(any("deseo" in p for p in Encargo(objetivo="arregla").valido()))

    def test_la_huella_depende_del_contenido_y_no_del_reloj(self):
        a, b = encargo_de_prueba(), encargo_de_prueba()
        self.assertEqual(a.huella(), b.huella())
        self.assertNotEqual(a.huella(), encargo_de_prueba(objetivo="otra cosa distinta del todo").huella())


# --------------------------------------------------------------------------------- agente 1


class TestAnalizador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = AnalizadorDeContexto(RAIZ).analizar()

    def test_encuentra_los_modulos_del_motor(self):
        rutas = {m.ruta for m in self.ctx.modulos}
        for esperado in ("motor/mando", "motor/world", "motor/cases", "motor/server"):
            self.assertIn(esperado, rutas)

    def test_el_nucleo_es_solo_stdlib_y_el_servidor_no(self):
        self.assertTrue(self.ctx.modulo("motor/mando").solo_stdlib)
        servidor = self.ctx.modulo("motor/server")
        self.assertFalse(servidor.solo_stdlib)
        self.assertIn("fastapi", servidor.importa_externo)

    def test_extrae_api_publica_con_ast(self):
        mando = self.ctx.modulo("motor/mando")
        self.assertTrue(mando.publico, "el analizador no ha sacado ningún nombre público de motor/mando")

    def test_la_api_publica_no_son_los_tests(self):
        """Antes la lista de `motor/world` la copaban las clases `TestLoQueSea`, y el implementador
        acababa viendo los tests en vez de la API con la que tiene que trabajar."""
        for m in self.ctx.modulos:
            colados = [n for n in m.publico if n.startswith("test_")]
            self.assertEqual(colados, [], f"{m.ruta} trae tests en su API pública: {colados}")

    def test_trae_las_reglas_duras_con_fuente(self):
        duras = [r for r in self.ctx.reglas if r.severidad is Severidad.BLOQUEA]
        self.assertGreaterEqual(len(duras), 5)
        self.assertTrue(all(r.fuente for r in self.ctx.reglas), "hay una regla sin fuente")

    def test_es_reproducible(self):
        self.assertEqual(self.ctx.generado_con, AnalizadorDeContexto(RAIZ).analizar().generado_con)

    def test_el_contextpack_es_json(self):
        json.dumps(self.ctx.to_dict(), ensure_ascii=False)

    def test_no_se_mete_en_carpetas_prohibidas(self):
        for m in self.ctx.modulos:
            self.assertNotIn("material", m.ruta)
            self.assertNotIn("__pycache__", m.ruta)


# --------------------------------------------------------------------------------- agente 2


class TestArquitecto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = AnalizadorDeContexto(RAIZ).analizar()
        cls.arq = ArquitectoDePrompts(cls.ctx)

    def test_el_prompt_lleva_las_reglas_duras_y_la_valla(self):
        spec = self.arq.construir(encargo_de_prueba())
        self.assertIn("sin-secretos", spec.sistema)
        self.assertIn("motor/mando/planner.py", spec.sistema)
        self.assertIn("python -m unittest motor.mando.test_mando", spec.sistema)

    def test_se_especializa_por_accion(self):
        implementar = self.arq.construir(encargo_de_prueba(accion=Accion.IMPLEMENTAR)).sistema
        corregir = self.arq.construir(encargo_de_prueba(accion=Accion.CORREGIR)).sistema
        self.assertNotEqual(implementar, corregir)
        self.assertIn("reproduce", corregir.lower())

    def test_explicar_no_pide_ficheros(self):
        spec = self.arq.construir(
            Encargo(objetivo="explicar cómo se calcula la prioridad de un incidente", accion=Accion.EXPLICAR)
        )
        self.assertEqual(spec.formato_salida, "texto")
        self.assertIn("Sin bloques de fichero", spec.sistema)

    def test_avisa_del_contrato_congelado(self):
        spec = self.arq.construir(encargo_de_prueba(ficheros_permitidos=["motor/contracts.py"]))
        self.assertIn("congelado", spec.sistema)
        self.assertIn("buzon", spec.sistema)

    def test_un_encargo_incompleto_sale_dicho_en_el_prompt(self):
        spec = self.arq.construir(Encargo(objetivo="mejorar el rendimiento del planificador entero"))
        self.assertIn("incompleto", spec.usuario)

    def test_respeta_el_presupuesto_de_caracteres(self):
        spec = self.arq.construir(encargo_de_prueba(contexto_extra=""))
        self.assertLess(len(spec.sistema), 20000)
        self.assertIn("reglas", spec.piezas)

    def test_es_reproducible(self):
        a = self.arq.construir(encargo_de_prueba()).sistema
        b = ArquitectoDePrompts(self.ctx).construir(encargo_de_prueba()).sistema
        self.assertEqual(a, b)


# --------------------------------------------------------------------------------- agente 3


class TestImplementador(unittest.TestCase):
    def test_extrae_bloques_de_fichero(self):
        texto = (
            "Añado la comprobación.\n\n"
            "```fichero:motor/mando/planner.py\n"
            "def plan():\n    return []\n"
            "```\n"
        )
        ficheros = extraer_ficheros(texto)
        self.assertEqual(len(ficheros), 1)
        self.assertEqual(ficheros[0].ruta, "motor/mando/planner.py")
        self.assertIn("def plan", ficheros[0].contenido)

    def test_el_modo_seco_no_llama_a_nadie_y_devuelve_el_encargo(self):
        ctx = AnalizadorDeContexto(RAIZ).analizar()
        encargo = encargo_de_prueba()
        spec = ArquitectoDePrompts(ctx).construir(encargo)
        parche = Implementador(ProveedorSeco()).implementar(spec, encargo)
        self.assertTrue(parche.vacio)
        self.assertIn("SISTEMA", parche.encargo_para_humano)
        self.assertEqual(parche.proveedor, ModoProveedor.SECO)

    def test_un_proveedor_caido_no_rompe_nada_y_deja_el_encargo(self):
        ctx = AnalizadorDeContexto(RAIZ).analizar()
        encargo = encargo_de_prueba()
        spec = ArquitectoDePrompts(ctx).construir(encargo)
        parche = Implementador(ProveedorFalso(error="HTTP 429: sin cuota")).implementar(spec, encargo)
        self.assertTrue(parche.vacio)
        self.assertIn("429", parche.resumen)
        self.assertIn("pegar a mano", parche.encargo_para_humano)

    def test_una_respuesta_sin_bloques_se_dice_claramente(self):
        ctx = AnalizadorDeContexto(RAIZ).analizar()
        encargo = encargo_de_prueba()
        spec = ArquitectoDePrompts(ctx).construir(encargo)
        parche = Implementador(ProveedorFalso(texto="Creo que no hace falta cambiar nada aquí.")).implementar(
            spec, encargo
        )
        self.assertIn("no devolvió ningún bloque", parche.resumen)


# --------------------------------------------------------------------------------- agente 4


def parche_con(ruta: str, codigo: str) -> Parche:
    return Parche(ficheros=[FicheroPropuesto(ruta=ruta, contenido=codigo)])


class TestRevisorSintaxis(unittest.TestCase):
    def test_lo_que_no_compila_se_rechaza(self):
        rev = RevisorDeCodigo().revisar_parche(parche_con("x.py", "def roto(:\n    pass\n"))
        self.assertEqual(rev.veredicto, Veredicto.RECHAZA)
        self.assertTrue(any(a.regla == "sintaxis" for a in rev.avisos))

    def test_codigo_limpio_se_acepta(self):
        codigo = "from __future__ import annotations\n\n\ndef suma(a: int, b: int) -> int:\n    return a + b\n"
        rev = RevisorDeCodigo().revisar_parche(parche_con("motor/server/util.py", codigo))
        self.assertEqual(rev.veredicto, Veredicto.ACEPTA)


class TestRevisorLimites(unittest.TestCase):
    def test_salirse_de_la_valla_bloquea(self):
        encargo = encargo_de_prueba(ficheros_permitidos=["motor/mando/planner.py"])
        parche = parche_con("motor/world/sim.py", "x = 1\n")
        rev = RevisorDeCodigo(encargo).revisar_parche(parche)
        self.assertEqual(rev.veredicto, Veredicto.RECHAZA)
        self.assertTrue(any(a.regla == "fuera-de-la-valla" for a in rev.avisos))

    def test_pasarse_de_tamano_pide_una_persona(self):
        encargo = encargo_de_prueba(ficheros_permitidos=["a.py"], max_lineas=5)
        rev = RevisorDeCodigo(encargo).revisar_parche(parche_con("a.py", "x = 1\n" * 50))
        self.assertTrue(any(a.regla == "parche-demasiado-grande" for a in rev.avisos))

    def test_tocar_el_contrato_congelado_pide_una_persona(self):
        encargo = encargo_de_prueba(ficheros_permitidos=["motor/contracts.py"])
        rev = RevisorDeCodigo(encargo).revisar_parche(parche_con("motor/contracts.py", "X = 1\n"))
        self.assertEqual(rev.veredicto, Veredicto.PIDE_APROBACION)


class TestRevisorSeguridad(unittest.TestCase):
    def test_una_clave_en_el_fichero_bloquea(self):
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", f'CLAVE = "{CLAVE_ANTHROPIC_FALSA}"\n'))
        self.assertEqual(rev.veredicto, Veredicto.RECHAZA)
        self.assertTrue(any(a.regla == "sin-secretos" for a in rev.avisos))

    def test_la_clave_no_se_repite_entera_en_el_aviso(self):
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", f'CLAVE = "{CLAVE_ANTHROPIC_FALSA}"\n'))
        for a in rev.avisos:
            self.assertNotIn(
                CLAVE_ANTHROPIC_FALSA, a.mensaje, "el revisor ha vuelto a escribir el secreto entero"
            )

    def test_un_telefono_real_bloquea(self):
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", f'JEFE = "{TELEFONO_FALSO}"\n'))
        self.assertEqual(rev.veredicto, Veredicto.RECHAZA)

    def test_un_valor_de_relleno_no_bloquea_pero_queda_escrito(self):
        """`SECRET = "secreto-de-prueba"` existe de verdad en `motor/server/test_server.py`. Si el
        revisor bloquea por eso, alguien lo desactiva hoy y ya no encuentra el que sí importa."""
        rev = RevisorDeCodigo().revisar_parche(parche_con("t.py", 'SECRET = "secreto-de-prueba"\n'))
        self.assertEqual(rev.veredicto, Veredicto.ACEPTA)
        self.assertTrue(any(a.regla == "sin-secretos" for a in rev.avisos))

    def test_una_credencial_con_forma_real_bloquea_aunque_se_llame_de_prueba(self):
        rev = RevisorDeCodigo().revisar_parche(parche_con("t.py", f'CLAVE_DE_PRUEBA = "{CLAVE_HR_FALSA}"\n'))
        self.assertEqual(rev.veredicto, Veredicto.RECHAZA)

    def test_leer_una_clave_del_entorno_es_correcto(self):
        codigo = "import os\n\nCLAVE = os.environ.get('HR_API_KEY', '')\n"
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", codigo))
        self.assertEqual(rev.veredicto, Veredicto.ACEPTA, [str(a) for a in rev.avisos])

    def test_eval_bloquea(self):
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", "def f(t):\n    return eval(t)\n"))
        self.assertEqual(rev.veredicto, Veredicto.RECHAZA)

    def test_os_system_pide_una_persona(self):
        codigo = "import os\n\n\ndef f(x):\n    os.system(x)\n"
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", codigo))
        self.assertTrue(any(a.regla == "llamada-peligrosa" for a in rev.avisos))

    def test_las_ordenes_prohibidas_del_evento_se_detectan(self):
        for orden in ("hackspain watch", "hackspain submit --final", "git push --force origin main"):
            rev = RevisorDeCodigo().revisar_parche(parche_con("guion.sh", f"#!/bin/sh\n{orden}\n"))
            self.assertNotEqual(
                rev.veredicto, Veredicto.ACEPTA, f"no se ha detectado la orden prohibida: {orden}"
            )

    def test_submit_con_draft_no_molesta(self):
        rev = RevisorDeCodigo().revisar_parche(parche_con("guion.sh", "hackspain submit --draft\n"))
        self.assertEqual(rev.veredicto, Veredicto.ACEPTA, [str(a) for a in rev.avisos])

    def test_whole_run_en_adversarios_bloquea(self):
        modo = "whole_run"  # revisor: ok es el valor que se está probando, no una configuración
        rev = RevisorDeCodigo().revisar_parche(parche_con("t.py", f'MODO = "{modo}"\n'))
        self.assertEqual(rev.veredicto, Veredicto.RECHAZA)


class TestRevisorCasosLimite(unittest.TestCase):
    def test_red_sin_tiempo_de_espera(self):
        codigo = "import urllib.request\n\n\ndef f(u):\n    return urllib.request.urlopen(u)\n"
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", codigo))
        self.assertTrue(any(a.regla == "red-sin-tiempo-de-espera" for a in rev.avisos))

    def test_red_con_tiempo_de_espera_pasa(self):
        codigo = "import urllib.request\n\n\ndef f(u):\n    return urllib.request.urlopen(u, timeout=30)\n"
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", codigo))
        self.assertFalse(any(a.regla == "red-sin-tiempo-de-espera" for a in rev.avisos))

    def test_except_pelado_y_error_silencioso(self):
        codigo = "def f():\n    try:\n        pass\n    except:\n        pass\n"
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", codigo))
        claves = {a.regla for a in rev.avisos}
        self.assertIn("except-pelado", claves)
        self.assertIn("error-silencioso", claves)

    def test_defecto_mutable(self):
        codigo = "def f(xs=[]):\n    xs.append(1)\n    return xs\n"
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", codigo))
        self.assertTrue(any(a.regla == "defecto-mutable" for a in rev.avisos))

    def test_reloj_real_en_el_nucleo_pide_una_persona(self):
        codigo = "import time\n\n\ndef ahora():\n    return time.time()\n"
        rev = RevisorDeCodigo().revisar_parche(parche_con("motor/world/reloj.py", codigo))
        self.assertEqual(rev.veredicto, Veredicto.PIDE_APROBACION)
        self.assertTrue(any(a.regla == "nucleo-determinista" for a in rev.avisos))

    def test_el_mismo_reloj_fuera_del_nucleo_no_molesta(self):
        codigo = "import time\n\n\ndef ahora():\n    return time.time()\n"
        rev = RevisorDeCodigo().revisar_parche(parche_con("motor/server/reloj.py", codigo))
        self.assertFalse(any(a.regla == "nucleo-determinista" for a in rev.avisos))

    def test_azar_sin_semilla_en_el_nucleo(self):
        codigo = "import random\n\n\ndef tira():\n    return random.random()\n"
        rev = RevisorDeCodigo().revisar_parche(parche_con("motor/cases/gen.py", codigo))
        self.assertTrue(any(a.regla == "nucleo-determinista" for a in rev.avisos))

    def test_cliente_de_modelo_en_el_nucleo_bloquea(self):
        rev = RevisorDeCodigo().revisar_parche(parche_con("motor/mando/x.py", "import anthropic\n"))
        self.assertEqual(rev.veredicto, Veredicto.RECHAZA)

    def test_el_nucleo_no_habla_solo_con_el_exterior(self):
        rev = RevisorDeCodigo().revisar_parche(parche_con("motor/mando/x.py", "import urllib.request\n"))
        self.assertTrue(any(a.regla == "sin-llm-en-decision" for a in rev.avisos))


class TestVeredicto(unittest.TestCase):
    def test_sale_de_los_avisos_y_no_de_una_opinion(self):
        from .contratos import Aviso, Revision

        casos = [
            ([], Veredicto.ACEPTA),
            ([Aviso(Severidad.NOTA, "x", "m")], Veredicto.ACEPTA),
            ([Aviso(Severidad.AVISO, "x", "m")], Veredicto.ACEPTA_CON_AVISOS),
            ([Aviso(Severidad.GRAVE, "x", "m")], Veredicto.PIDE_APROBACION),
            ([Aviso(Severidad.BLOQUEA, "x", "m"), Aviso(Severidad.NOTA, "y", "m")], Veredicto.RECHAZA),
        ]
        for avisos, esperado in casos:
            self.assertEqual(Revision(avisos=avisos).resolver(), esperado)

    def test_lo_que_bloquea_manda_sobre_lo_demas(self):
        from .contratos import Aviso, Revision

        rev = Revision(avisos=[Aviso(Severidad.AVISO, "a", "m"), Aviso(Severidad.BLOQUEA, "b", "m")])
        self.assertEqual(rev.resolver(), Veredicto.RECHAZA)


# --------------------------------------------------------------------------------- orquestador


class TestOrquestador(unittest.TestCase):
    def test_la_pasada_completa_deja_traza_de_los_cuatro(self):
        res = Orquestador(RAIZ, ProveedorSeco()).ejecutar(encargo_de_prueba())
        agentes = [p.agente for p in res.traza.pasos]
        self.assertEqual(
            agentes, ["context-analyzer", "prompt-architect", "implementer", "code-reviewer"]
        )
        json.dumps(res.to_dict(), ensure_ascii=False)

    def test_no_escribe_nada_si_el_veredicto_no_lo_permite(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "AGENTS.md").write_text("# vacío\n", encoding="utf-8")
            orq = Orquestador(raiz, ProveedorSeco())
            res = orq.ejecutar(encargo_de_prueba())
            res.parche.ficheros = [FicheroPropuesto("fuera.py", "x = 1\n")]
            res.revision.avisos.append(
                __import__("agentes.contratos", fromlist=["Aviso"]).Aviso(Severidad.BLOQUEA, "x", "m")
            )
            res.revision.resolver()
            self.assertEqual(orq.aplicar(res), [])
            self.assertFalse((raiz / "fuera.py").exists())

    def test_no_escribe_fuera_de_la_raiz_ni_forzando(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp) / "repo"
            raiz.mkdir()
            orq = Orquestador(raiz, ProveedorSeco())
            res = orq.ejecutar(encargo_de_prueba())
            res.parche.ficheros = [FicheroPropuesto("../escapado.py", "x = 1\n")]
            self.assertEqual(orq.aplicar(res, forzar=True), [])
            self.assertFalse((Path(tmp) / "escapado.py").exists())

    def test_escribe_cuando_el_veredicto_lo_permite(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            orq = Orquestador(raiz, ProveedorSeco())
            res = orq.ejecutar(encargo_de_prueba(ficheros_permitidos=["nuevo/a.py"]))
            res.parche.ficheros = [FicheroPropuesto("nuevo/a.py", "x = 1\n")]
            res.revision.avisos.clear()
            res.revision.resolver()
            self.assertEqual(orq.aplicar(res), ["nuevo/a.py"])
            self.assertEqual((raiz / "nuevo" / "a.py").read_text(encoding="utf-8"), "x = 1\n")


# --------------------------------------------------------------------------------- happyrobot


class TestHappyRobot(unittest.TestCase):
    def test_apunta_al_cluster_eu(self):
        from .happyrobot import BASE_EU, ClienteHappyRobot

        self.assertIn("platform.eu.", BASE_EU)
        self.assertIn("eu", ClienteHappyRobot().diagnostico()["cluster"])

    def test_avisa_si_la_base_no_es_el_cluster_eu(self):
        from .happyrobot import ClienteHappyRobot

        d = ClienteHappyRobot(clave="", base="https://platform.happyrobot.ai/api/v2").diagnostico()
        self.assertIn("aviso_cluster", d)
        self.assertEqual(d["cluster"], "NO ES EU")

    def test_sin_clave_no_manda_cabecera_de_autorizacion(self):
        from .happyrobot import ClienteHappyRobot

        self.assertNotIn("Authorization", ClienteHappyRobot(clave="")._cabeceras())
        self.assertIn("Authorization", ClienteHappyRobot(clave="x")._cabeceras())

    def test_el_diagnostico_no_deja_escapar_la_clave(self):
        from .happyrobot import ClienteHappyRobot

        texto = json.dumps(ClienteHappyRobot(clave=CLAVE_HR_FALSA).diagnostico(), ensure_ascii=False)
        self.assertNotIn(CLAVE_HR_FALSA, texto)


class TestElPerdon(unittest.TestCase):
    def test_la_marca_con_motivo_perdona_y_deja_nota(self):
        codigo = f'X = "{TELEFONO_FALSO}"  # revisor: ok inventado para el test\n'
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", codigo))
        self.assertEqual(rev.veredicto, Veredicto.ACEPTA)
        self.assertTrue(any(a.regla == "perdonada" for a in rev.avisos), "la excepción no quedó anotada")

    def test_la_marca_sin_motivo_no_vale(self):
        codigo = f'X = "{TELEFONO_FALSO}"  # revisor: ok\n'
        rev = RevisorDeCodigo().revisar_parche(parche_con("a.py", codigo))
        self.assertEqual(rev.veredicto, Veredicto.RECHAZA)


class TestElSistemaSeRevisaASiMismo(unittest.TestCase):
    """Si el revisor no aprueba su propio paquete, no tiene autoridad para revisar el de nadie.

    Sin excluir el fichero de tests: las cadenas con forma de credencial que hacen falta para
    probar el escáner llevan su marca `# revisor: ok` con el motivo escrito.
    """

    def test_el_paquete_agentes_pasa_su_propia_revision(self):
        rev = RevisorDeCodigo().revisar_ruta(Path(__file__).resolve().parent)
        graves = [a for a in rev.avisos if a.severidad in (Severidad.BLOQUEA, Severidad.GRAVE)]
        self.assertEqual(graves, [], "\n".join(str(a) for a in graves))


if __name__ == "__main__":
    unittest.main()
