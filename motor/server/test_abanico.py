"""Enjambre en abanico: el backend lanza especialistas HR en paralelo.

    uv run --project motor/server python -m unittest motor.server.test_abanico -v
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from motor.server.app import create_app

SECRET = "secreto-de-prueba-abanico"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PAPELES = ("triaje", "prioridad", "recursos", "avisos", "vigia", "critico")
OLA1 = ("triaje", "prioridad", "recursos", "avisos", "vigia")
WIDS = {p: f"wf-{p}" for p in PAPELES}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(cond, seconds: float = 6.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.04)
    return False


def vote_for(papel: str, **extra) -> dict:
    base = {
        "agente": papel,
        "incident_id": extra.pop("incident_id", "nuevo"),
        "zona": extra.pop("zona", "front_pit"),
        "tipo": extra.pop("tipo", "crowd"),
        "confianza": 0.7,
        "supuestos": ["El recinto sigue igual."],
        "porque": extra.pop("porque", f"Recomiendo el voto de {papel}."),
        "razonamiento": extra.pop("razonamiento", f"Recomiendo el voto de {papel}."),
    }
    if papel == "triaje":
        base.update(fusionar_con=None, clasificacion="nuevo")
    elif papel == "prioridad":
        base["prioridad"] = extra.pop("prioridad", 6)
    elif papel == "recursos":
        base["recursos"] = extra.pop("recursos", ["med_1"])
    elif papel == "avisos":
        base["avisar"] = extra.pop("avisar", [{"rol": "sanitario", "canal": "telegram",
                                              "mensaje": "Acude al foso."}])
    elif papel == "vigia":
        base.update(sigue_valido=True, vigilar=["silencio >60 s"], relanzar=[], afectados=[])
    elif papel == "critico":
        base.update(veredicto=extra.pop("veredicto", "APROBAR"), requiere_persona=False,
                    acciones=extra.pop("acciones", []), correcciones=extra.pop("correcciones", []))
    base.update(extra)
    return base


class FakeHR:
    """API de HappyRobot falsa: POST runs + GET run/nodes/outputs."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.launches: list[dict] = []
        self.delays: dict[str, float] = {p: 0.12 for p in PAPELES}
        self.hang: set[str] = set()
        self.down = False
        self.results: dict[str, dict] = {p: vote_for(p) for p in PAPELES}
        self.runs: dict[str, dict] = {}
        self._n = 0
        self.port = free_port()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # noqa: ARG002
                return

            def _auth(self) -> bool:
                return self.headers.get("Authorization") == f"Bearer {SECRET}"

            def _json(self, code: int, body: dict) -> None:
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:  # noqa: N802
                if not self._auth():
                    return self._json(401, {"error": "auth"})
                path = urlparse(self.path).path.rstrip("/")
                parts = path.split("/")
                if not (len(parts) >= 5 and parts[-1] == "runs" and "workflows" in parts):
                    return self._json(404, {"error": "ruta"})
                if fake.down:
                    return self._json(500, {"error": "plataforma caída"})
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                wid = parts[parts.index("workflows") + 1]
                papel = next((p for p, w in WIDS.items() if w == wid), wid)
                with fake.lock:
                    fake._n += 1
                    rid = f"run-{fake._n}-{papel}"
                    fake.runs[rid] = {"papel": papel, "ready": False, "wid": wid}
                    fake.launches.append({
                        "t": time.monotonic(), "papel": papel, "workflow": wid,
                        "run_id": rid, "payload": body.get("payload") or {},
                        "environment": body.get("environment"),
                    })
                delay = 999.0 if papel in fake.hang else float(fake.delays.get(papel) or 0.05)

                def finish() -> None:
                    time.sleep(delay)
                    with fake.lock:
                        run = fake.runs.get(rid)
                        if run is not None:
                            run["ready"] = True
                            run["vote"] = dict(fake.results.get(papel) or vote_for(papel))

                threading.Thread(target=finish, daemon=True).start()
                self._json(200, {"run_id": rid})

            def do_GET(self) -> None:  # noqa: N802
                if not self._auth():
                    return self._json(401, {"error": "auth"})
                path = urlparse(self.path).path.rstrip("/")
                parts = [p for p in path.split("/") if p]
                if "runs" not in parts:
                    return self._json(404, {"error": "ruta"})
                i = parts.index("runs")
                rid = parts[i + 1] if i + 1 < len(parts) else ""
                with fake.lock:
                    run = fake.runs.get(rid)
                if run is None:
                    return self._json(404, {"error": "run"})
                rest = parts[i + 2:]
                if not run["ready"]:
                    if rest[:1] == ["nodes"]:
                        return self._json(200, {"data": []})
                    return self._json(200, {"status": "running", "run_id": rid})
                vote = run.get("vote") or {}
                if rest[:1] == ["nodes"]:
                    return self._json(200, {"data": [{
                        "name": "Devolver resultado validado",
                        "status": "completed",
                        "output_id": f"out-{rid}",
                        "node_persistent_id": "devolver-resultado",
                    }]})
                if rest[:1] == ["outputs"] and len(rest) >= 2:
                    return self._json(200, {"data": {"payload_json": vote}})
                return self._json(200, {"status": "completed", "run_id": rid, "output": vote})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v2"

    def close(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=3)

    def launches_of(self, papel: str) -> list[dict]:
        with self.lock:
            return [x for x in self.launches if x["papel"] == papel]


def _app(**env):
    base = {
        "HR_SECRET": SECRET, "TELEGRAM_MODE": "off", "MANDO_CEREBRO": "abanico",
        "MANDO_ABANICO_TIMEOUT_S": "2", "MANDO_ABANICO_POLL_S": "0.05",
        "MANDO_CEREBRO_TIMEOUT_S": "30", "MANDO_LLM": "0", "MANDO_PUBLIC_URL": "http://abanico.test",
        "MANDO_OPERATOR_TOKEN": "op-abanico",
        "HR_API_KEY": SECRET, **{f"HR_AGENTE_{p.upper()}": WIDS[p] for p in PAPELES},
    }
    base.update(env)
    ctx = patch.dict(os.environ, base, clear=False)
    ctx.start()
    app = create_app("demo-gates", threaded=False, secret=SECRET)
    return app, ctx


class AbanicoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hr = FakeHR()
        self.addCleanup(self.hr.close)
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        self._db = tmp.name
        self.app, self._env = _app(HR_API_BASE=self.hr.base, MANDO_DB=self._db)
        self.addCleanup(self._env.stop)
        self.addCleanup(lambda: Path(self._db).unlink(missing_ok=True))
        self.c = TestClient(self.app)
        self.s = self.app.state.session
        self.addCleanup(self.s.close)
        self.addCleanup(self.app.state.chat.stop)
        self.h = {"X-Mando-Token": SECRET}
        self.op = {"X-Mando-Operator": "op-abanico"}

    def aviso(self, text: str = "Una chica se ha mareado por el calor, está muy roja y casi no habla",
              zone: str = "front_pit") -> str:
        out = self.s.report("voice", text, zone=zone)
        rid = str(out.get("report_id") or "")
        self.s.tick()
        self.s.tick()
        for i in self.s.state().get("incidents") or []:
            if rid and rid in (i.get("reports") or []):
                return i["id"]
        open_ = [i for i in self.s.state().get("incidents") or []
                 if i.get("status") not in ("resolved", "false_alarm", "failed")]
        if open_:
            return max(open_, key=lambda i: int(i.get("t_open") or 0))["id"]
        return rid or "nuevo"

    def card(self, iid: str) -> dict:
        st = self.s.state()
        self.assertIn(iid, st.get("agentes") or {}, st.get("agentes"))
        return st["agentes"][iid]

    def wait_card(self, iid: str, pred, seconds: float = 5.0) -> dict:
        ok = wait_for(lambda: iid in (self.s.state().get("agentes") or {}) and pred(self.s.state()["agentes"][iid]),
                      seconds)
        self.assertTrue(ok, self.s.state().get("agentes"))
        return self.card(iid)

    def test_paralelo_real_no_es_la_suma(self) -> None:
        for p in OLA1:
            self.hr.delays[p] = 0.35
        t0 = time.monotonic()
        iid = self.aviso()
        card = self.wait_card(
            iid,
            lambda c: {"triaje", "prioridad", "recursos"} <= {x["papel"] for x in (c.get("abanico") or {}).get("llegados") or []},
        )
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 1.1, f"parece serie: {elapsed:.2f}s")
        self.assertGreaterEqual(elapsed, 0.30)
        with self.hr.lock:
            ola = [x for x in self.hr.launches if x["papel"] in OLA1]
        self.assertGreaterEqual(len(ola), 5, ola)
        span = max(x["t"] for x in ola) - min(x["t"] for x in ola)
        self.assertLess(span, 0.25, f"lanzamientos no simultáneos: {span:.2f}s")
        ab = card["abanico"]
        self.assertEqual(ab["fuente"], "plataforma")
        papeles = {x["papel"] for x in ab["llegados"]}
        self.assertTrue({"triaje", "prioridad", "recursos"} <= papeles, papeles)

    def test_composicion_anytime_antes_de_que_lleguen_todos(self) -> None:
        self.hr.delays.update(triaje=0.08, prioridad=0.08, recursos=0.08, avisos=0.9, vigia=0.9, critico=0.08)
        iid = self.aviso()
        card = self.wait_card(iid, lambda c: (c.get("abanico") or {}).get("primera_decision_s") is not None,
                              seconds=3)
        papeles = {x["papel"] for x in card["abanico"]["llegados"]}
        self.assertTrue({"triaje", "prioridad", "recursos"} <= papeles, papeles)
        self.assertNotIn("avisos", papeles)
        self.assertIsNone(card["abanico"].get("final_s"))
        self.assertTrue(card.get("ejecutado"), card)
        self.wait_card(iid, lambda c: (c.get("abanico") or {}).get("final_s") is not None, seconds=3)

    def test_timeout_de_un_agente_sigue_con_los_demas(self) -> None:
        os.environ["MANDO_ABANICO_TIMEOUT_S"] = "0.45"
        self.hr.hang.add("vigia")
        self.hr.delays.update(triaje=0.05, prioridad=0.05, recursos=0.05, avisos=0.05, critico=0.05)
        iid = self.aviso()
        card = self.wait_card(iid, lambda c: "vigia" in ((c.get("abanico") or {}).get("timeouts") or []),
                              seconds=3)
        self.assertIn("prioridad", card["agentes"])
        self.assertTrue(card.get("ejecutado") or card.get("agentes"), card)
        self.assertNotIn("vigia", {x["papel"] for x in card["abanico"]["llegados"]})
        self.assertIn("vigia", card["abanico"]["timeouts"])

    def test_caida_total_llm_local_luego_reglas(self) -> None:
        self.hr.down = True
        from motor.server.cerebro_llm import fake_team

        def local_ok(session, aviso, **kwargs):
            iid_now = str((aviso or {}).get("incident_id") or "nuevo")
            ctx = {"aviso": aviso or {}, "incidentes": [{"id": iid_now, "zona": "front_pit", "vital": False}],
                   "recursos_libres": {"medical": [{"id": "med_1", "eta_min": 2}]}}
            votos = fake_team(ctx)
            from motor.server import cerebro_tools
            out = cerebro_tools.decidir(session, dict(votos["prioridad"], agente="equipo",
                                                      recursos=votos["recursos"]["recursos"],
                                                      porque=votos["prioridad"]["porque"]))
            return {"ok": True, "resultado": out, "votos": votos}

        with patch("motor.server.abanico.ciclo_local", side_effect=local_ok):
            iid = self.aviso()
            card = self.wait_card(iid, lambda c: (c.get("abanico") or {}).get("fuente") == "local",
                                  seconds=3)
        self.assertEqual(card["abanico"]["fuente"], "local")
        self.assertNotEqual(self.s.state()["session"].get("modo_degradado"),
                            "modo degradado: reglas")

        self.hr.down = True
        with patch("motor.server.abanico.ciclo_local", return_value=None):
            iid2 = self.aviso("Hay una pelea entre varios tíos, se están pegando fuerte", zone="gate_c")
            card2 = self.wait_card(iid2, lambda c: (c.get("abanico") or {}).get("fuente") == "reglas",
                                   seconds=3)
        self.assertEqual(card2["abanico"]["fuente"], "reglas")
        self.assertEqual(self.s.state()["session"].get("modo_degradado"), "modo degradado: reglas")

    def test_critico_objeta_alto_vigia_rehace_grave_a_persona(self) -> None:
        self.hr.results["critico"] = vote_for(
            "critico", veredicto="CORREGIR", requiere_persona=True,
            correcciones=[{"agente": "recursos", "texto": "Falta perímetro"}],
            acciones=[{"kind": "evacuate", "zone": "front_pit"}],
            porque="Objeción alta: evacuar el foso exige una persona.",
        )
        self.hr.delays.update(triaje=0.05, prioridad=0.05, recursos=0.05, avisos=0.05, vigia=0.05, critico=0.08)
        iid = self.aviso()
        self.wait_card(iid, lambda c: (c.get("agentes") or {}).get("critico"), seconds=4)
        self.assertTrue(wait_for(lambda: len(self.hr.launches_of("vigia")) >= 2, 3),
                        self.hr.launches_of("vigia"))
        self.assertTrue(wait_for(lambda: bool(self.s.state().get("approvals")
                                              or (self.s.state().get("agentes") or {}).get(iid, {}).get("espera_persona")),
                                 3),
                        {"ap": self.s.state().get("approvals"), "card": self.card(iid)})

    def test_nada_reservado_en_claro_ni_secretos(self) -> None:
        iid = self.aviso("Agresión sexual en los aseos, la han tocado y no la dejan irse.", zone="toilets")
        self.wait_card(iid, lambda c: (c.get("abanico") or {}).get("llegados"), seconds=4)
        blob = json.dumps(self.s.state(), ensure_ascii=False).lower()
        self.assertNotIn("sexual", blob)
        self.assertNotIn("tocado", blob)
        self.assertNotIn(SECRET.lower(), blob)
        self.assertNotIn("callback_token", blob)
        card = self.card(iid)
        for ag in (card.get("agentes") or {}).values():
            self.assertIn(ag.get("razonamiento"), (None, "", "(reservado)"))

    def test_barandilla_vital_al_instante(self) -> None:
        self.hr.hang.update(OLA1)
        os.environ["MANDO_ABANICO_TIMEOUT_S"] = "8"
        self.s.report("voice", "Hay una persona en el suelo que no responde y no respira bien, ¡ayuda!",
                      zone="front_pit")
        self.s.tick()
        self.s.tick()
        assigned = [r for r in self.s.state()["resources"]
                    if r["id"].startswith("med") and r.get("status") != "available"]
        incs = [i for i in self.s.state()["incidents"] if i.get("life_threat") or (i.get("priority") or 0) >= 8]
        self.assertTrue(assigned or any(i.get("assigned") for i in incs),
                        {"res": self.s.state()["resources"], "inc": self.s.state()["incidents"]})

    def test_demo_abanico_y_payload_de_runs(self) -> None:
        r = self.c.post("/api/demo/abanico", json={"zone": "front_pit"}, headers=self.op)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body.get("ok"), body)
        self.assertTrue(body.get("incident_id"), body)
        self.assertTrue(wait_for(lambda: self.hr.launches, 3), self.hr.launches)
        pay = self.hr.launches[0]["payload"]
        self.assertEqual(self.hr.launches[0]["environment"], "development")
        self.assertIn("entrada_json", pay)
        self.assertEqual(pay.get("callback_url"), "http://abanico.test")
        self.assertEqual(pay.get("callback_token"), SECRET)
        entrada = pay["entrada_json"]
        if isinstance(entrada, str):
            entrada = json.loads(entrada)
        self.assertTrue(entrada.get("contexto") or entrada.get("aviso"), entrada)

    def test_sala_js_tarjetas_y_linea_de_tiempos(self) -> None:
        js = (HERE / "static" / "sala.js").read_text(encoding="utf-8")
        self.assertIn("Primera decisión en", js)
        self.assertIn("enjambre completo", js)
        r = subprocess.run(["node", "--check", str(HERE / "static" / "sala.js")],
                           capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr or r.stdout)

    def test_env_example_sin_valores_reales(self) -> None:
        texto = (ROOT / ".env.example").read_text(encoding="utf-8")
        for name in ("HR_AGENTE_TRIAJE", "HR_AGENTE_PRIORIDAD", "HR_AGENTE_RECURSOS",
                     "HR_AGENTE_AVISOS", "HR_AGENTE_VIGIA", "HR_AGENTE_CRITICO",
                     "MANDO_ABANICO_TIMEOUT_S"):
            self.assertIn(name, texto, name)
        for line in texto.splitlines():
            if line.startswith("HR_AGENTE_"):
                self.assertTrue(line.strip().endswith("=") or "=" in line and not line.split("=", 1)[1].strip(),
                                line)


if __name__ == "__main__":
    unittest.main()
