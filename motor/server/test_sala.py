"""Pruebas de la Sala de control (`/sala`). Desde la raíz del proyecto:

    uv run --project motor/server python -m unittest motor.server.test_sala -v
    node --check motor/server/static/sala.js

Cubren cinco cosas:

1. Que la pantalla se sirve en `/` y en `/sala`, sin CDN y sin secretos.
2. El CONTRATO: cada campo del estado que lee `static/sala.js` existe de verdad en `/api/state`,
   en los dos casos de demostración que se usan en el escenario (`demo-1` y `demo-gates`).
   Si alguien renombra un campo del motor, esta prueba se cae antes que la pantalla.
3. Que aprobar y vetar desde la sala funciona y exige operador cuando hay tokens configurados.
4. Que `/api/chats`, el panel «CHAT · AGENTE HR», no deja salir el contenido reservado.
5. Con `MANDO_CEREBRO=agente` y el cerebro falso, `agentes` y `GET /api/agentes/{id}` existen.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from motor.server.app import create_app

HERE = Path(__file__).resolve().parent
SECRET = "secreto-de-prueba"

# Lo que `sala.js` da por hecho que existe en `/api/state`. Cada entrada es «ruta: tipo esperado».
TOP_LEVEL = {
    "t": int, "clock": dict, "session": dict, "presentation": dict, "happyrobot": dict, "calls": dict,
    "incidents": list, "zones": list, "resources": list, "approvals": list, "actions": list, "plans": list,
    "forecasts": list, "fronts": list, "log": list, "reports": list, "strikes": list, "scoreboard": dict,
    "agentes": dict,
}
CALLS_KEYS = ("mode", "calls", "fallbacks", "in_flight_real", "real_sent")
PRESENTATION_KEYS = ("banner", "voice", "happyrobot")
CLOCK_KEYS = ("hhmm", "day", "show_phase")
# Huecos de workflow que pinta la columna «AGENTE HR»; vienen de motor/happyrobot/MAPA-WORKFLOWS.md.
WORKFLOW_SLOTS = ("sanitario", "seguridad", "tecnico", "logistica", "director", "externos", "difusion",
                  "relevo", "dispatch", "webcall", "intake", "voice", "chat")
# Campos de cada incidente, recurso y zona que la sala lee para pintar píldora, fila, marcador y baliza.
INCIDENT_KEYS = ("id", "family", "type", "zone", "zone_name", "severity", "priority", "status", "t_open",
                 "deadline", "needs", "assigned", "waiting", "label", "explain", "life_threat", "reserved")
RESOURCE_KEYS = ("id", "name", "kind", "zone", "status", "task", "eta")
ZONE_KEYS = ("id", "name", "density", "occupancy", "capacity", "ratio", "state", "flags")
# Lo que la ficha lee de cada previsión cuando el gemelo publica alguna.
FORECAST_KEYS = ("eta_min", "metric", "status", "current", "predicted", "threshold")
# Contrato compartido S.telegram (lo produce el espejo; si es null la Sala no pinta nada).
TELEGRAM_KEYS = ("staff", "asignaciones", "escaladas")
ASIGNACION_KEYS = ("incident_id", "rol", "estado", "alias", "eta_min", "desde_zona", "intento", "t")
ESCALADA_KEYS = ("incident_id", "rol", "motivo", "workflow_voz")


def interpolaciones(linea: str) -> list[str]:
    """Los `${...}` de una línea de JavaScript, contando llaves para no cortar los anidados."""
    fuera, i = [], 0
    while (i := linea.find("${", i)) != -1:
        depth, j = 1, i + 2
        while j < len(linea) and depth:
            depth += (linea[j] == "{") - (linea[j] == "}")
            j += 1
        if depth:
            break                                   # la interpolación sigue en la línea siguiente
        fuera.append(linea[i + 2:j - 1])
        i = j
    return fuera


def app_for(case: str):
    # threaded=False: el reloj solo avanza cuando la prueba lo pide, así la prueba es determinista.
    return create_app(case, threaded=False, secret=SECRET)


class PagesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = app_for("demo-1")
        self.c = TestClient(self.app)

    def tearDown(self) -> None:
        self.app.state.session.close()

    def test_sala_se_sirve_en_raiz_y_en_sala(self) -> None:
        for path in ("/", "/sala", "/static/sala.html", "/static/sala.css", "/static/sala.js", "/static/sala-plano.js"):
            self.assertEqual(self.c.get(path).status_code, 200, path)
        html = self.c.get("/sala").text
        self.assertEqual(self.c.get("/").text, html, "`/` y `/sala` son la misma pantalla")
        self.assertIn("Sala de control", html)
        for marca in ("MANDO", "112 EMERGENCIAS", "Mesa de inyección", "COLA ACTIVA DE INCIDENTES EN VIVO",
                      "RECURSOS TERRESTRES", "ABIERTOS POR GRAVEDAD", "CONVERSACIONES", "Enjambre"):
            self.assertIn(marca, html, marca)

    def test_las_otras_pantallas_siguen_en_su_sitio(self) -> None:
        # sala.html (no se toca) sigue enlazando; esas rutas redirigen a la Sala.
        for destino in ('href="/centro"', 'href="/clasico"', 'href="/informe"'):
            self.assertIn(destino, self.c.get("/sala").text, destino)
        for path in ("/centro", "/clasico", "/informe"):
            body = self.c.get(path).text
            self.assertIn("archivada", body, path)
            self.assertIn('href="/"', body, path)

    def test_sin_cdn_ni_secretos_en_la_pantalla(self) -> None:
        html = self.c.get("/sala").text
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
        self.assertNotIn("https://", html)
        for fichero in ("sala.html", "sala.js", "sala.css", "sala-plano.js"):
            texto = (HERE / "static" / fichero).read_text(encoding="utf-8")
            self.assertNotIn("cdn.", texto, fichero)
            self.assertNotIn("unpkg", texto, fichero)
            # Ningún teléfono ni token se pinta: la pantalla no nombra siquiera las variables de entorno.
            self.assertNotIn("HR_API_KEY", texto, fichero)
            self.assertNotIn("MANDO_OPERATOR_TOKEN", texto, fichero)
            self.assertFalse(re.search(r"\+\d{9,}", texto), fichero)

    def test_la_version_del_chip_es_la_del_proyecto(self) -> None:
        r = self.c.get("/api/version")
        self.assertEqual(r.status_code, 200)
        version = r.json()["version"]
        self.assertIn(version, (HERE / "pyproject.toml").read_text(encoding="utf-8"))

    def test_layout_dos_columnas_pestanas_sin_solape(self) -> None:
        """De 1280×720 a 1920×1080: nav + main en dos columnas; pestañas y HUD sin solapar el plano."""
        css = (HERE / "static" / "sala.css").read_text(encoding="utf-8")
        html = (HERE / "static" / "sala.html").read_text(encoding="utf-8")
        compact = re.sub(r"\s+", "", css)
        self.assertIn("grid-template-columns:var(--nav-w)minmax(0,1fr)", compact)
        self.assertNotIn("var(--aside-w)", compact)
        self.assertRegex(css, r"\.nav,\s*\.main\{[^}]*min-width:\s*0")
        self.assertRegex(css, r"\.band\{[^}]*position:\s*absolute")
        self.assertRegex(css, r"\.map\{[^}]*position:\s*relative")
        self.assertIn('role="tablist"', html)
        self.assertIn('id="tab-ahora"', html)
        self.assertIn('id="tab-enjambre"', html)
        self.assertIn('class="workspace"', html)
        self.assertIn('class="map"', html)
        mapa = html.split('class="map"', 1)[1].split("<!--", 1)[0]
        self.assertIn('class="band"', mapa)
        self.assertIn('id="plano"', mapa)

    def test_sala_js_pasa_node_check(self) -> None:
        r = subprocess.run(["node", "--check", str(HERE / "static" / "sala.js")],
                           capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr or r.stdout)

    def test_honestidad_del_prototipo(self) -> None:
        """Las afirmaciones del mockup que el motor no tiene no se copian como si existieran."""
        html = (HERE / "static" / "sala.html").read_text(encoding="utf-8")
        plano = (HERE / "static" / "sala-plano.js").read_text(encoding="utf-8")
        self.assertNotIn("GPS", html)
        self.assertIn("posición simulada", html)
        self.assertIn("estimación del simulador", html.lower())
        self.assertIn("Entorno de demo", html)
        self.assertIn("NO marca", html)
        self.assertIn("const DECOR", plano)
        self.assertIn("SIN DATOS", plano)

    def test_el_texto_del_publico_se_escapa(self) -> None:
        """Ningún dato se cuela crudo en el HTML: dentro de una plantilla con etiquetas, toda interpolación
        que sea directamente un campo del estado (`${i.label}`) es un fallo. Lo válido es `${E(...)}`."""
        js = (HERE / "static" / "sala.js").read_text(encoding="utf-8")
        montajes = [l for l in js.splitlines() if ".innerHTML" in l]
        self.assertEqual(len(montajes), 1, "solo `setHTML` monta HTML, y lo hace sobre un <template> aparte")
        self.assertIn("t.innerHTML = html", montajes[0])
        sospechosos = []
        for n, linea in enumerate(js.splitlines(), 1):
            if not re.search(r"<[a-z/]", linea):
                continue                                              # esta línea no monta HTML
            for expr in interpolaciones(linea):
                cuerpo = expr.split("?", 1)[1].strip() if "?" in expr else expr.strip()
                # Un campo suelto del estado, con o sin valor por defecto: eso sí acabaría crudo en la página.
                # `cls`, `g`, `n` y `length` los calcula la propia sala (clase CSS y cuentas), no vienen de fuera.
                if re.match(r"^[A-Za-z_$][\w$]*[.\[][^(]*$", cuerpo) and not re.search(r"\.(cls|g|n|length)$", cuerpo):
                    sospechosos.append(f"sala.js:{n}: ${{{expr}}}")
        self.assertEqual(sospechosos, [], "hay datos sin escapar dentro del HTML")


class ContratoDelEstadoTest(unittest.TestCase):
    """El contrato: lo que la pantalla lee tiene que existir en los dos casos de la demostración."""

    def comprobar_caso(self, case: str) -> None:
        app = app_for(case)
        try:
            c = TestClient(app)
            c.post("/api/control", json={"cmd": "step", "n": 14})
            s = c.get("/api/state").json()
            for clave, tipo in TOP_LEVEL.items():
                self.assertIn(clave, s, f"{case}: falta `{clave}` en /api/state")
                self.assertIsInstance(s[clave], tipo, f"{case}: `{clave}` cambió de tipo")
            for clave in CALLS_KEYS:
                self.assertIn(clave, s["calls"], f"{case}: falta `calls.{clave}`")
            for clave in PRESENTATION_KEYS:
                self.assertIn(clave, s["presentation"], f"{case}: falta `presentation.{clave}`")
            for clave in CLOCK_KEYS:
                self.assertIn(clave, s["clock"], f"{case}: falta `clock.{clave}`")
            for hueco in WORKFLOW_SLOTS:
                self.assertIn(hueco, s["happyrobot"], f"{case}: falta el workflow `{hueco}`")
                self.assertIn("configured", s["happyrobot"][hueco], f"{case}: `{hueco}` sin `configured`")
            self.assertTrue(s["incidents"], f"{case}: en el minuto 14 tiene que haber incidentes que pintar")
            for clave in INCIDENT_KEYS:
                self.assertIn(clave, s["incidents"][0], f"{case}: falta `incidents[].{clave}`")
            self.assertTrue(s["resources"], f"{case}: sin recursos no hay balizas")
            for clave in RESOURCE_KEYS:
                self.assertIn(clave, s["resources"][0], f"{case}: falta `resources[].{clave}`")
            self.assertTrue(s["zones"], f"{case}: sin zonas no hay plano")
            for clave in ZONE_KEYS:
                self.assertIn(clave, s["zones"][0], f"{case}: falta `zones[].{clave}`")
            self.assertIn("telegram", s, f"{case}: falta la clave `telegram` (puede ser null)")
            tg = s["telegram"]
            if isinstance(tg, dict) and "asignaciones" in tg:
                for clave in TELEGRAM_KEYS:
                    self.assertIn(clave, tg, f"{case}: falta `telegram.{clave}`")
                self.assertIn("disponibles", tg["staff"])
                self.assertIn("total", tg["staff"])
                if tg["asignaciones"]:
                    for clave in ASIGNACION_KEYS:
                        self.assertIn(clave, tg["asignaciones"][0], f"{case}: falta `telegram.asignaciones[].{clave}`")
                if tg.get("escaladas"):
                    for clave in ESCALADA_KEYS:
                        self.assertIn(clave, tg["escaladas"][0], f"{case}: falta `telegram.escaladas[].{clave}`")
            if s["forecasts"]:
                for clave in FORECAST_KEYS:
                    self.assertIn(clave, s["forecasts"][0], f"{case}: falta `forecasts[].{clave}`")
            crudo = json.dumps(s)
            self.assertNotIn("chat_id", crudo)
        finally:
            app.state.session.close()

    def test_demo_1(self) -> None:
        self.comprobar_caso("demo-1")

    def test_demo_gates(self) -> None:
        self.comprobar_caso("demo-gates")

    def test_el_plano_solo_usa_zonas_que_existen_en_el_motor(self) -> None:
        """`sala-plano.js` no puede inventarse zonas: cada caja es un id de motor/world/festival.json."""
        js = (HERE / "static" / "sala-plano.js").read_text(encoding="utf-8")
        bloque = js.split("const ZONES = {", 1)[1].split("\n  };", 1)[0]
        del_plano = set(re.findall(r"^\s{4}([a-z_0-9]+):", bloque, re.M))
        app = app_for("demo-1")
        try:
            reales = {z["id"] for z in TestClient(app).get("/api/state").json()["zones"]}
        finally:
            app.state.session.close()
        self.assertEqual(del_plano - reales, set(), "el plano pinta zonas que el motor no tiene")
        self.assertEqual(reales - del_plano, set(), "hay zonas del motor que el plano no pinta")


class DecisionesTest(unittest.TestCase):
    """Aprobar y vetar desde la sala: el mismo endpoint que usa el resto del sistema."""

    def setUp(self) -> None:
        self.app = app_for("demo-1")
        self.c = TestClient(self.app)
        self.c.post("/api/control", json={"cmd": "step", "n": 14})

    def tearDown(self) -> None:
        self.app.state.session.close()

    def pendiente(self) -> dict:
        ap = self.c.get("/api/state").json()["approvals"]
        self.assertTrue(ap, "en el minuto 14 tiene que haber alguna decisión esperando a una persona")
        return ap[0]

    def test_aprobar_registra_la_decision(self) -> None:
        a = self.pendiente()
        r = self.c.post("/api/approve", json={"action_id": a["id"], "ok": True, "note": "lo veo"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotEqual(r.json().get("ok"), False, r.text)
        s = self.c.get("/api/state").json()
        self.assertNotIn(a["id"], [x["id"] for x in s["approvals"]], "la decisión sigue pendiente tras aprobarla")

    def test_vetar_registra_la_decision(self) -> None:
        a = self.pendiente()
        r = self.c.post("/api/approve", json={"action_id": a["id"], "ok": False, "note": "no con este plan"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotEqual(r.json().get("ok"), False, r.text)

    def test_la_tarjeta_trae_los_dos_futuros_o_no_se_inventan(self) -> None:
        """La tarjeta de decisión pinta `if_approved` / `if_vetoed`; si el motor no los publica, se dice."""
        for a in self.c.get("/api/state").json()["approvals"]:
            card = a.get("card")
            if card is None:
                continue
            self.assertIsInstance(card, dict)
            for rama in ("if_approved", "if_vetoed"):
                if card.get(rama) is not None:
                    self.assertIsInstance(card[rama], dict, rama)

    def test_exige_operador_cuando_hay_tokens_configurados(self) -> None:
        previo = os.environ.get("MANDO_OPERATORS")
        os.environ["MANDO_OPERATORS"] = "Ana:coordinación:token-de-prueba"
        try:
            a = self.pendiente()
            sin = self.c.post("/api/approve", json={"action_id": a["id"], "ok": True})
            self.assertIn(sin.status_code, (401, 403), "sin token se puede aprobar: eso no puede pasar")
            con = self.c.post("/api/approve", json={"action_id": a["id"], "ok": True},
                              headers={"X-Mando-Operator": "token-de-prueba"})
            self.assertEqual(con.status_code, 200, con.text)
            # La mesa de inyección y el «¿y si…?» también son de operador.
            self.assertIn(self.c.post("/api/whatif", json={"kind": "divert", "zone": "gate_a"}).status_code, (401, 403))
        finally:
            if previo is None:
                os.environ.pop("MANDO_OPERATORS", None)
            else:
                os.environ["MANDO_OPERATORS"] = previo


class ChatPanelTest(unittest.TestCase):
    """`/api/chats` alimenta el panel «CHAT · AGENTE HR»: solo lectura y sin contenido reservado."""

    def setUp(self) -> None:
        self.app = app_for("demo-1")
        self.c = TestClient(self.app)

    def tearDown(self) -> None:
        self.app.state.session.close()

    def test_devuelve_las_conversaciones_de_los_canales(self) -> None:
        self.c.post("/api/chat", json={"text": "hay un desmayo en la pista central", "channel": "whatsapp"})
        self.c.post("/api/control", json={"cmd": "step", "n": 2})
        r = self.c.get("/api/chats")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("chats", body)
        self.assertGreaterEqual(body["n"], 1, "el aviso por chat no aparece en el panel")
        conv = body["chats"][-1]
        for clave in ("n", "channel", "lang", "reports", "done", "reserved", "messages"):
            self.assertIn(clave, conv, clave)
        self.assertTrue(any("desmayo" in m["text"] for m in conv["messages"]), conv)

    def test_no_deja_salir_el_contenido_reservado(self) -> None:
        self.c.post("/api/chat", json={"text": "soy de seguridad, RESERVADO: hay un arma en la puerta B",
                                       "channel": "whatsapp", "reserved": True})
        self.c.post("/api/control", json={"cmd": "step", "n": 2})
        crudo = self.c.get("/api/chats").text
        self.assertNotIn("arma en la puerta B", crudo, "el panel de chat filtra contenido reservado")
        reservadas = [c for c in self.c.get("/api/chats").json()["chats"] if c["reserved"]]
        for c in reservadas:
            self.assertIsNone(c["instruction"])
            for m in c["messages"]:
                self.assertIn("reservad", m["text"])

    def test_es_solo_lectura_y_de_operador(self) -> None:
        self.assertEqual(self.c.post("/api/chats", json={}).status_code, 405)
        previo = os.environ.get("MANDO_OPERATORS")
        os.environ["MANDO_OPERATORS"] = "Ana:coordinación:token-de-prueba"
        try:
            # La lectura del panel va con la misma identidad de operador que el resto de la sala.
            self.assertEqual(self.c.get("/api/chats", headers={"X-Mando-Operator": "token-de-prueba"}).status_code, 200)
        finally:
            if previo is None:
                os.environ.pop("MANDO_OPERATORS", None)
            else:
                os.environ["MANDO_OPERATORS"] = previo


class AgentesCerebroTest(unittest.TestCase):
    """Con MANDO_CEREBRO=agente y cerebro falso, la Sala tiene agentes en el estado."""

    def test_campos_agentes_tras_decidir(self) -> None:
        env = {"HR_SECRET": SECRET, "TELEGRAM_MODE": "off", "MANDO_CEREBRO": "agente", "MANDO_CEREBRO_TIMEOUT_S": "30"}
        with patch.dict(os.environ, env, clear=False):
            app = create_app("demo-gates", threaded=False, secret=SECRET)
            try:
                c = TestClient(app)
                h = {"X-Mando-Token": SECRET}
                r = c.post("/hr/tools/decidir", json={
                    "agente": "triaje", "incident_id": "nuevo", "zona": "front_pit",
                    "tipo": "crowd", "texto": "Foso saturado", "porque": "Aviso nuevo.",
                }, headers=h)
                self.assertEqual(r.status_code, 200, r.text)
                iid = r.json()["incident_id"]
                c.post("/hr/tools/decidir", json={
                    "agente": "prioridad", "incident_id": iid, "prioridad": 8,
                    "porque": "Densidad alta.", "confianza": 0.7,
                }, headers=h)
                st = c.get("/api/state").json()
                self.assertIn("agentes", st)
                self.assertIn(iid, st["agentes"])
                card = st["agentes"][iid]
                for clave in ("agentes", "ejecutado", "bloqueado", "espera_persona"):
                    self.assertIn(clave, card, clave)
                ag = card["agentes"]["triaje"]
                for clave in ("razonamiento", "confianza", "supuestos", "hora", "agente"):
                    self.assertIn(clave, ag, clave)
                self.assertIn("session", st)
                self.assertEqual(st["session"].get("cerebro"), "agente")
                det = c.get(f"/api/agentes/{iid}")
                self.assertEqual(det.status_code, 200, det.text)
                js = (HERE / "static" / "sala.js").read_text(encoding="utf-8")
                for marca in ("S.agentes", "/api/agentes/", "Equipo de agentes", "CÓMO LO HA DECIDIDO EL EQUIPO",
                              "switchTab", "panelEnjambre", "panelAprendizaje"):
                    self.assertIn(marca, js, marca)
            finally:
                app.state.session.close()
                app.state.chat.stop()


class TelegramPintadoTest(unittest.TestCase):
    """La Sala pinta S.telegram si existe; si es null, no inventa despacho."""

    def test_el_js_conoce_el_contrato(self) -> None:
        js = (HERE / "static" / "sala.js").read_text(encoding="utf-8")
        for marca in ("function telegramState", "Staff por Telegram", "ESCALADA POR VOZ",
                      "Telegram →", "ACUDE", "No puede → reasignando", "Cubierto",
                      "pendiente"):
            self.assertIn(marca, js, marca)
        self.assertNotIn("innerHTML = S.telegram", js)

    def test_demo_sin_espejo_no_rompe(self) -> None:
        app = app_for("demo-1")
        try:
            s = TestClient(app).get("/api/state").json()
            self.assertIn("telegram", s)
            self.assertTrue(s["telegram"] is None or isinstance(s["telegram"], dict))
        finally:
            app.state.session.close()

    def test_tras_el_demo_el_contrato_esta_completo(self) -> None:
        app = app_for("demo-gates")
        try:
            c = TestClient(app)
            r = c.post("/api/demo/telegram", json={"zone": "front_pit"})
            self.assertEqual(r.status_code, 200, r.text)
            tg = c.get("/api/state").json()["telegram"]
            self.assertIsInstance(tg, dict)
            for clave in TELEGRAM_KEYS:
                self.assertIn(clave, tg, clave)
            self.assertGreaterEqual(tg["staff"]["total"], tg["staff"]["disponibles"])
            self.assertTrue(tg["asignaciones"])
            self.assertTrue(tg["escaladas"])
            for a in tg["asignaciones"]:
                for clave in ASIGNACION_KEYS:
                    self.assertIn(clave, a, clave)
                self.assertIn(a["estado"], ("pending", "accepted", "declined", "timeout", "covered"))
            for e in tg["escaladas"]:
                for clave in ESCALADA_KEYS:
                    self.assertIn(clave, e, clave)
            crudo = json.dumps(tg)
            self.assertNotIn("chat_id", crudo)
        finally:
            app.state.session.close()


if __name__ == "__main__":
    unittest.main()
