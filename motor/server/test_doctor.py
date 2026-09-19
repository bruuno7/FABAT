"""Tests del comando `doctor`. Solo `unittest`, como el resto del repositorio.

    uv run --project motor/server python -m unittest motor.server.test_doctor -v

Se prueban de verdad las dos cosas que importan de un diagnóstico: que **detecte lo que falta** y
que **no se equivoque cuando todo está bien**. Un doctor que siempre dice que falta algo es tan
inútil como uno que siempre dice que todo va bien: en los dos casos nadie lo mira.

Todo se prueba con el entorno inyectado, así que pasa igual de bien en un portátil con la cadena
configurada que en uno vacío, y sin llamar a la red (`sondear_red=False`).
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from . import doctor

# Una cadena de la que sí se puede decir «está completa», para el caso en que todo va bien.
ENTORNO_COMPLETO = {
    "HR_API_BASE": "https://platform.eu.happyrobot.ai/api/v2",
    "HR_API_KEY": "clave-de-prueba",
    "HR_SECRET": "secreto-de-prueba",
    "HR_WORKFLOW_WEBCALL": "mando-despacho-webcall",
    "HR_HOOK_DISPATCH": "https://platform.eu.happyrobot.ai/hooks/despacho",
    "MANDO_CALLBACK_URL": "https://algo.trycloudflare.com",
    "MANDO_OPERATOR_TOKEN": "operador-de-prueba", "MANDO_MCP_TOKEN": "mcp-de-prueba",
    "TELEGRAM_MODE": "off",
}


class BaseDoctor(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patch = mock.patch.dict(os.environ, {}, clear=True)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def con_entorno(self, **valores: str) -> None:
        for k, v in valores.items():
            os.environ[k] = v

    def diagnosticar(self, raiz: Path | None = None) -> doctor.Diagnostico:
        """Diagnostica sin sondear la red y, si se pide, con una raíz de mentira."""
        if raiz is None:
            return doctor.diagnosticar(sondear_red=False)
        with mock.patch.object(doctor, "RAIZ", raiz):
            return doctor.diagnosticar(sondear_red=False)

    def estado(self, d: doctor.Diagnostico, clave: str) -> str:
        for c in d.comprobaciones:
            if c.clave == clave:
                return c.estado
        self.fail(f"el doctor no ha mirado «{clave}», que es de las que importan")

    def raiz_completa(self, contactos: dict | None = None) -> Path:
        """Una raíz de mentira con todo lo que no viaja en git: la lista blanca y la librería.

        Hace falta porque media cadena son **ficheros que git ignora**, no variables de entorno: una
        raíz solo con el entorno puesto no está completa, y el doctor tiene razón al decir que no.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        (raiz / "contacts.local.json").write_text(
            json.dumps(contactos if contactos is not None else {"resources": {"medical": {"number": "+34600111222"}}}),
            encoding="utf-8",
        )
        vendor = raiz / "static" / "vendor"
        vendor.mkdir(parents=True)
        (vendor / "livekit-client.umd.min.js").write_bytes(b"// de mentira: solo se mira que exista\n")
        os.environ["MANDO_CONTACTS"] = str(raiz / "contacts.local.json")
        return raiz


class TestDetectaLoQueFalta(BaseDoctor):
    def test_sin_nada_configurado_la_demo_es_simulada(self):
        d = self.diagnosticar()
        self.assertEqual(d.modo, "simulada")
        self.assertTrue(d.faltan_imprescindibles())

    def test_dice_que_criterios_del_mvp_se_caen(self):
        d = self.diagnosticar()
        texto = " ".join(d.criterios_en_riesgo)
        self.assertIn("run real", texto)
        self.assertIn("real: true", texto)

    def test_con_la_cadena_completa_la_demo_esta_configurada(self):
        self.con_entorno(**ENTORNO_COMPLETO)
        d = self.diagnosticar(self.raiz_completa())
        self.assertEqual(d.modo, "configurada", [f"{c.clave}={c.estado}" for c in d.faltan_imprescindibles()])
        self.assertEqual(d.criterios_en_riesgo, [])

    def test_avisa_si_la_base_no_es_el_cluster_eu(self):
        """Es el fallo número uno documentado: con el clúster equivocado la clave responde 401."""
        self.con_entorno(HR_API_BASE="https://platform.happyrobot.ai/api/v2")
        d = self.diagnosticar()
        self.assertEqual(self.estado(d, "HR_API_BASE"), "aviso")
        consecuencia = next(c.consecuencia for c in d.comprobaciones if c.clave == "HR_API_BASE")
        self.assertIn("401", consecuencia)

    def test_sin_clave_la_configuracion_es_incompleta(self):
        """La falta de clave debe diferenciarse de una avería del servicio."""
        self.con_entorno(HR_API_BASE="https://platform.eu.happyrobot.ai/api/v2")
        d = self.diagnosticar()
        self.assertIn(self.estado(d, "HR_API_KEY"), ("falta",))

    def test_el_callback_local_avisa_de_que_no_hay_ida_y_vuelta(self):
        self.con_entorno(MANDO_CALLBACK_URL="http://127.0.0.1:8000")
        d = self.diagnosticar()
        self.assertEqual(self.estado(d, "MANDO_CALLBACK_URL"), "aviso")
        self.assertIn("no puede llamar a 127.0.0.1", " ".join(d.criterios_en_riesgo))

    def test_sin_la_libreria_de_livekit_la_llamada_no_abre_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.diagnosticar(Path(tmp))
        self.assertEqual(self.estado(d, "static/vendor/livekit-client.umd.min.js"), "falta")
        consecuencia = next(
            c.consecuencia for c in d.comprobaciones
            if c.clave == "static/vendor/livekit-client.umd.min.js"
        )
        self.assertIn("unpkg.com", consecuencia, "no dice de dónde sacarla, y a las 3:00 eso es media hora")

    def test_sin_lista_blanca_todo_lo_contesta_la_simulacion(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.diagnosticar(Path(tmp))
        self.assertEqual(self.estado(d, "contacts.local.json"), "falta")
        self.assertIn("SimComms", " ".join(d.criterios_en_riesgo))

    def test_el_modo_hook_exige_la_url_del_hook(self):
        self.con_entorno(HR_LAUNCH_MODE="hook", MANDO_VOICE_MODE="phone")
        with mock.patch.object(doctor.hr_config, "workflow_urls", return_value={}):
            d = self.diagnosticar()
        self.assertEqual(self.estado(d, "HR_HOOK_DISPATCH"), "falta")
        self.assertEqual(doctor.IMPRESCINDIBLE, next(
            c.nivel for c in d.comprobaciones if c.clave == "HR_HOOK_DISPATCH"
        ))

    def test_en_modo_runs_el_hook_no_hace_falta(self):
        self.con_entorno(HR_LAUNCH_MODE="runs")
        d = self.diagnosticar()
        self.assertNotIn("HR_HOOK_DISPATCH", [c.clave for c in d.faltan_imprescindibles()])


class TestSeguridadDeLaListaBlanca(BaseDoctor):
    """Nunca se marca un número de emergencias. Si el doctor no lo ve, nadie lo ve."""

    def test_caza_un_numero_de_emergencia_en_la_lista_blanca(self):
        d = self.diagnosticar(self.raiz_completa({"resources": {"medical": {"number": "112"}}}))
        self.assertEqual(self.estado(d, "contacts.local.json"), "falta")
        consecuencia = next(c.consecuencia for c in d.comprobaciones if c.clave == "contacts.local.json")
        self.assertIn("NEVER_DIAL", consecuencia)

    def test_un_numero_normal_no_molesta(self):
        d = self.diagnosticar(self.raiz_completa({"resources": {"medical": {"number": "+34600111222"}}}))
        self.assertEqual(self.estado(d, "contacts.local.json"), "ok")


class TestNoFiltraNiEscribe(BaseDoctor):
    def test_el_informe_no_lleva_ninguna_credencial(self):
        secreto = "clave-que-no-debe-salir-123456"
        self.con_entorno(**{**ENTORNO_COMPLETO, "HR_API_KEY": secreto})
        d = self.diagnosticar()
        texto = json.dumps(d.to_dict(), ensure_ascii=False)
        self.assertNotIn(secreto, texto, "el doctor ha escrito la clave en su propio informe")

    def test_el_diagnostico_es_json(self):
        json.dumps(self.diagnosticar().to_dict(), ensure_ascii=False)

    def test_diagnosticar_no_escribe_nada_en_el_repositorio(self):
        antes = {p: p.stat().st_mtime_ns for p in Path(doctor.RAIZ).rglob("*") if p.is_file()}
        self.diagnosticar()
        despues = {p: p.stat().st_mtime_ns for p in Path(doctor.RAIZ).rglob("*") if p.is_file()}
        self.assertEqual(antes, despues, "el doctor ha tocado ficheros: tiene que ser de solo lectura")


class TestLaCliNoSeHaRoto(BaseDoctor):
    """El arranque sin subcomando está en el README y en el manual de la demo: no se rompe."""

    def test_sigue_aceptando_los_mismos_argumentos(self):
        from .__main__ import main as arranque  # noqa: F401  (importa sin ejecutar)

        fuente = (Path(doctor.RAIZ) / "__main__.py").read_text(encoding="utf-8")
        for bandera in ("--case", "--speed", "--comms", "--lan", "--play", "--port", "--playbook"):
            self.assertIn(bandera, fuente, f"desapareció {bandera} del arranque")

    def test_doctor_se_intercepta_antes_de_arrancar_el_servidor(self):
        fuente = (Path(doctor.RAIZ) / "__main__.py").read_text(encoding="utf-8")
        self.assertIn('sys.argv[1:2] == ["doctor"]', fuente)
        self.assertLess(
            fuente.index('== ["doctor"]'), fuente.index("argparse.ArgumentParser"),
            "el doctor se intercepta después de argparse: `python -m motor.server doctor` fallaría",
        )


class TestConfiguracionYRed(BaseDoctor):
    def test_emergencias_en_todos_los_campos_y_lista(self):
        for campo in ("to_number", "number", "phone", "telefono"):
            with self.subTest(campo=campo):
                d = self.diagnosticar(self.raiz_completa({"resources": {"medical": {campo: "+34112"}}}))
                self.assertEqual(self.estado(d, "contacts.local.json"), "falta")
                self.assertNotIn("+34112", json.dumps(d.to_dict()))
        for lista in (["112"], "112,+34600111222"):
            d = self.diagnosticar(self.raiz_completa({"resources": {"medical": "112"}, "allowed_numbers": lista}))
            self.assertEqual(self.estado(d, "contacts.local.json"), "falta")
        d = self.diagnosticar(self.raiz_completa({"resources": {"medical": ""}, "allowed_numbers": ["911"]}))
        self.assertEqual(self.estado(d, "contacts.local.json"), "falta")

    def test_contacts_configurado_precede_raiz(self):
        raiz = self.raiz_completa({"resources": {"medical": {"to_number": "+34600111222"}}})
        alternate = raiz / "alternate.json"
        alternate.write_text(json.dumps({"resources": {"medical": {"phone": "112"}}}))
        self.con_entorno(MANDO_CONTACTS=str(alternate))
        self.assertEqual(self.estado(self.diagnosticar(raiz), "contacts.local.json"), "falta")

    def test_webcall_no_exige_hook_y_phone_no_exige_livekit(self):
        self.con_entorno(**ENTORNO_COMPLETO)
        raiz = self.raiz_completa()
        with mock.patch.object(doctor.hr_config, "workflow_urls", return_value={}):
            self.assertNotIn("HR_HOOK_DISPATCH", [c.clave for c in self.diagnosticar(raiz).faltan_imprescindibles()])
        self.con_entorno(MANDO_VOICE_MODE="phone")
        (raiz / "static/vendor/livekit-client.umd.min.js").unlink()
        self.assertNotIn("static/vendor/livekit-client.umd.min.js", [c.clave for c in self.diagnosticar(raiz).faltan_imprescindibles()])

    def test_public_url_precede_callback_y_exige_tokens(self):
        self.con_entorno(MANDO_PUBLIC_URL="https://public.example", MANDO_CALLBACK_URL="http://127.0.0.1:8000")
        d = self.diagnosticar()
        self.assertEqual(self.estado(d, "MANDO_PUBLIC_URL"), "ok")
        self.assertNotIn("MANDO_CALLBACK_URL", [c.clave for c in d.comprobaciones])
        self.assertTrue({"MANDO_OPERATOR_TOKEN", "MANDO_MCP_TOKEN"}.issubset({c.clave for c in d.faltan_imprescindibles()}))

    def test_tabla_urls_no_filtra_userinfo_query_fragmento_o_numeros(self):
        self.con_entorno(HR_HOOK_DISPATCH="https://usuario:password@example.org/hooks/dispatch?key=secretquery#secretfragment",
                         MANDO_ALLOWED_NUMBERS="+34600111222", HR_API_KEY="secretapi")
        d = self.diagnosticar(self.raiz_completa())
        texto = json.dumps(d.to_dict())
        for secreto in ("usuario", "password", "secretquery", "secretfragment", "+34600111222", "secretapi"):
            self.assertNotIn(secreto, texto)
        self.assertIn("https://example.org/hooks/dispatch", texto)

    def test_sin_red_cli_no_hace_peticiones_ni_consume_argv(self):
        self.con_entorno(**ENTORNO_COMPLETO, TELEGRAM_BOT_TOKEN="123456:" + "a" * 24)
        with mock.patch.object(doctor.httpx, "request", side_effect=AssertionError("red")), \
             mock.patch.object(doctor.httpx, "post", side_effect=AssertionError("red")), redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.main(["--sin-red"]), 1)  # sin contactos
        with mock.patch.object(doctor, "diagnosticar", return_value=doctor.Diagnostico()), \
             mock.patch("sys.argv", ["unittest", "--no-es-argumento-del-doctor"]), redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.main(), 0)

    def test_sondas_telegram_solo_getme_y_getwebhookinfo(self):
        for mode in ("poll", "send_only", "off"):
            with self.subTest(mode=mode):
                respuestas = [mock.Mock(json=lambda: {"ok": True, "result": {"username": "test_bot"}}),
                              mock.Mock(json=lambda: {"ok": True, "result": {"url": "https://hidden.example/secret-webhook"}})]
                with mock.patch.object(doctor.httpx, "post", side_effect=respuestas) as post:
                    d = doctor.diagnosticar(env={"TELEGRAM_MODE": mode, "TELEGRAM_BOT_TOKEN": "123456:" + "a" * 24})
                if mode == "off":
                    post.assert_not_called()
                    self.assertNotIn("TELEGRAM_BOT_TOKEN", [c.clave for c in d.comprobaciones])
                else:
                    self.assertEqual([c.args[0].rsplit("/", 1)[-1] for c in post.call_args_list], ["getMe", "getWebhookInfo"])
                    self.assertEqual(self.estado(d, "TELEGRAM_WEBHOOK"), "aviso" if mode == "poll" else "ok")
                self.assertNotIn("secret-webhook", json.dumps(d.to_dict()))

    def test_401_sin_clave_no_certifica_cluster_y_con_clave_rechazada(self):
        for key in ("", "clave-prueba"):
            with mock.patch.object(doctor, "_get", return_value=(401, "")):
                d = doctor.diagnosticar(env={"HR_API_BASE": "http://127.0.0.1:9876/api/v2", "HR_API_KEY": key, "TELEGRAM_MODE": "off"})
            c = next(c for c in d.comprobaciones if c.clave == "plataforma EU")
            self.assertEqual(c.estado, "falta" if key else "aviso")
            self.assertIn("comprueba clúster" if key else "no demuestra", c.consecuencia)

    def test_avisa_poll_con_tunel_y_cors_vacio(self):
        self.con_entorno(MANDO_PUBLIC_URL="https://tunnel.example", TELEGRAM_MODE="poll", MANDO_VOICE_MODE="web_call")
        d = self.diagnosticar()
        self.assertEqual(self.estado(d, "TELEGRAM_MODE espejo"), "aviso")
        self.assertEqual(self.estado(d, "MANDO_CORS_ORIGINS"), "aviso")

    def test_rechaza_voice_mode_desconocido(self):
        self.con_entorno(MANDO_VOICE_MODE="phone_call")
        self.assertEqual(self.estado(self.diagnosticar(), "MANDO_VOICE_MODE"), "falta")

    def test_configuracion_completa_sin_red_sale_cero_sin_afirmar_llamada_real(self):
        self.con_entorno(**ENTORNO_COMPLETO)
        raiz = self.raiz_completa()
        with mock.patch.object(doctor, "RAIZ", raiz), redirect_stdout(io.StringIO()) as salida:
            self.assertEqual(doctor.main(["--sin-red"]), 0)
        self.assertIn("pendientes de verificar", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
