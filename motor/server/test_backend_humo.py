"""Humo de todas las rutas GET/POST y /hr/tools: ningún 500, ninguna traza, 401 sin token."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from motor.server.app import create_app

SECRET = "secreto-de-prueba-humo"
UNICODE = "Puerta B saturada 🚨 — 漢字 café"
HUGE = "x" * 20_000
TRACE_MARKERS = ("Traceback (most recent call last)", 'File "/', "starlette.middleware", "pydantic_core")

PLACEHOLDERS = {
    "report_id": "j-no-existe",
    "incident_id": "no-existe",
    "session_id": "no-existe",
    "code": "XX-1",
    "n": "99",
    "call_id": "abc",
    "action_id": "A-no",
    "aid": "A-no",
    "iid": "i-no",
}

TOOL_VALID = {
    "/hr/tools/contexto": {"tipo": "crowd", "zona": "gate_b", "texto": "Cola en B"},
    "/hr/tools/ensayar": {"opciones": ["desviar puerta B → C"], "minutos": 8},
    "/hr/tools/decidir": {"incident_id": "nuevo", "prioridad": 6, "zona": "front_pit",
                          "porque": "Aviso de humo del backend, simulación N=1."},
    "/hr/tools/cambio": {"tipo": "rechazo", "zona": "front_pit"},
    "/hr/tools/memoria/guardar": {"id": "ce-humo-1", "tipo": "crowd", "zona": "gate_b",
                                  "razonamiento": "episodio de prueba", "resultado": {"texto": "ok"}},
    "/hr/tools/memoria/buscar": {"tipo": "crowd", "zona": "gate_b"},
    "/hr/tools/memoria/lecciones": {"accion": "listar"},
    "/hr/tools/pizarra/publicar": {"de": "prioridad", "para": "todos", "tipo": "observacion",
                                   "texto": "Observación de humo."},
    "/hr/tools/pizarra/leer": {"agente": "prioridad", "n": 5},
    "/hr/tools/zona": {"zona": "gate_b"},
    "/hr/tools/recurso": {"recurso": "med_1"},
    "/hr/tools/rutas": {"de": "gate_a", "a": "front_pit"},
    "/hr/tools/staff": {"rol": "medical"},
    "/hr/tools/previsiones": {},
    "/hr/tools/incidentes_parecidos": {"tipo": "crowd"},
    "/hr/tools/protocolo": {"tipo": "unresponsive_person"},
    "/hr/tools/confianza": {"familia": "crowd"},
    "/hr/tools/acciones_posibles": {"zona": "front_pit"},
    "/hr/tools/comparar_opciones": {"opciones": ["despachar médico", "vigilar"]},
    "/hr/tools/analizar_situacion": {},
    "/hr/tools/resultado": {"agente": "recursos", "familia": "crowd", "resultado": "aceptó"},
    "/hr/tools/prompt/proponer": {"agente": "prioridad", "cuerpo": "# prueba\n", "evidencia": {"n": 3, "ids": ["ce-1"]}},
    "/hr/tools/prompt/listar": {"agente": "prioridad"},
    "/hr/tools/prompt/comparar": {"agente": "prioridad"},
}

POST_VALID = {
    "/api/control": {"cmd": "step", "n": 1},
    "/api/report": {"text": "Hay una persona mareada en puerta B", "zone": "gate_b"},
    "/api/chat": {"text": "hola", "channel": "web"},
    "/api/strike": {"preset": "storm"},
    "/api/whatif": {"kind": "stop_show"},
    "/api/session": {"case_id": "demo-gates"},
    "/hr/events": {"type": "public_report", "channel": "web", "description": "Mareo en B",
                   "location": "Puerta B", "hr_run_id": "humo-1"},
    "/hr/identify": {"from_number": "+34600000002"},
    "/hr/approval_check": {"action_id": "A-no"},
    "/hr/webcall/next": {},
    "/hr/tools/contexto": TOOL_VALID["/hr/tools/contexto"],
}


def _fill(path: str) -> str:
    out = path
    for key, value in PLACEHOLDERS.items():
        out = out.replace("{" + key + "}", value)
    return out


def _trace(text: str) -> str | None:
    for marker in TRACE_MARKERS:
        if marker in text:
            return marker
    return None


class HumoTest(unittest.TestCase):
    summary: list[dict] = []

    def setUp(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        self._db = tmp.name
        self.env = patch.dict(os.environ, {
            "HR_SECRET": SECRET, "TELEGRAM_MODE": "off", "MANDO_DB": self._db,
            "MANDO_CEREBRO": "", "MANDO_PUBLIC_URL": "", "MANDO_LLM": "0",
            "HR_HOOK_INTAKE": "", "TELEGRAM_BOT_TOKEN": "",
        }, clear=False)
        self.env.start()
        os.environ.pop("MANDO_CEREBRO", None)
        self.app = create_app("demo-1", threaded=False, secret=SECRET)
        self.c = TestClient(self.app, raise_server_exceptions=False)
        self.s = self.app.state.session
        self.h = {"X-Mando-Token": SECRET}
        self.addCleanup(self.s.close)
        self.addCleanup(self.app.state.chat.stop)
        self.addCleanup(self.env.stop)
        self.addCleanup(lambda: Path(self._db).unlink(missing_ok=True))

    def record(self, method: str, path: str, status: int, note: str = "") -> None:
        HumoTest.summary.append({"method": method, "path": path, "status": status, "note": note})

    def check(self, resp, *, path: str = "") -> None:
        hit = _trace(resp.text)
        self.assertIsNone(hit, f"traza {hit!r} en {path}: {resp.text[:300]}")
        if resp.status_code >= 500:
            self.assertIn(resp.status_code, (502, 503), f"{path} → {resp.status_code}: {resp.text[:400]}")
            self.assertIn("error", resp.text)

    def routes(self) -> list[tuple[str, str]]:
        out = []
        for route in self.app.routes:
            methods = getattr(route, "methods", None) or set()
            path = getattr(route, "path", None)
            if not path:
                continue
            for method in methods:
                if method in ("GET", "POST"):
                    out.append((method, path))
        extra = [
            ("GET", "/"), ("GET", "/sala"), ("GET", "/jurado"), ("GET", "/asistente"),
            ("GET", "/acceso"), ("GET", "/static/style.css"), ("GET", "/static/plano.js"),
            ("GET", "/static/llamada.js"), ("GET", "/qr"), ("GET", "/llamada/abc"),
            ("POST", "/mcp"), ("POST", "/api/operator/login"),
        ]
        return sorted(set(out + extra))

    def test_todas_las_rutas_sin_500_ni_traza(self) -> None:
        seen = 0
        for method, path in self.routes():
            if "{" in path and path.count("{") != path.count("}"):
                continue
            url = _fill(path)
            if "{}" in url or "{" in url:
                continue
            if method == "GET":
                if path in ("/api/stream", "/api/duel/stream"):
                    url = path + "?limit=1"
                resp = self.c.get(url)
            else:
                if path.startswith("/hr/") or path == "/mcp":
                    resp = self.c.post(url, json={})
                    self.check(resp, path=url + " sin token")
                    if path == "/mcp":
                        self.assertIn(resp.status_code, (401, 503))
                        self.record(method, path, resp.status_code, "sin token")
                        seen += 1
                        continue
                    self.assertEqual(resp.status_code, 401, f"{url} sin token → {resp.status_code}")
                    bad = self.c.post(url, json={}, headers={"X-Mando-Token": "malo"})
                    self.check(bad, path=url + " token malo")
                    self.assertEqual(bad.status_code, 401)
                body = POST_VALID.get(path, {})
                headers = dict(self.h) if path.startswith("/hr/") else {}
                resp = self.c.post(url, json=body, headers=headers)
            self.check(resp, path=url)
            self.record(method, path, resp.status_code)
            seen += 1
        self.assertGreaterEqual(seen, 80, f"pocas rutas ejercidas: {seen}")

    def test_tools_cuerpos_malos_unicode_y_enormes(self) -> None:
        tools = sorted(p for _, p in self.routes() if p.startswith("/hr/tools/") and "{" not in p)
        self.assertGreaterEqual(len(tools), 20, tools)
        payloads = [
            ("vacio", {}),
            ("unicode", {"texto": UNICODE, "zona": UNICODE, "tipo": UNICODE, "porque": UNICODE,
                         "agente": UNICODE, "opciones": [UNICODE], "de": UNICODE}),
            ("tipos", {"zona": 1, "prioridad": "alta", "texto": ["x"], "minutos": [], "n": True,
                       "limit": {"a": 1}, "confianza": "mucho", "recursos": "med_1"}),
            ("enorme", {"texto": HUGE, "porque": HUGE, "zona": "gate_b", "tipo": "crowd"}),
        ]
        for path in tools:
            r401 = self.c.post(path, json={})
            self.check(r401, path=path)
            self.assertEqual(r401.status_code, 401)
            broken = self.c.post(path, content=b"{", headers={**self.h, "Content-Type": "application/json"})
            self.check(broken, path=path + " json roto")
            self.assertIn(broken.status_code, (400, 422))
            array = self.c.post(path, json=["no", "objeto"], headers=self.h)
            self.check(array, path=path + " array")
            self.assertIn(array.status_code, (400, 422))
            for name, body in payloads:
                resp = self.c.post(path, json=body, headers=self.h)
                self.check(resp, path=f"{path} {name}")
                self.record("POST", path, resp.status_code, name)
            valid = self.c.post(path, json=TOOL_VALID.get(path, {}), headers=self.h)
            self.check(valid, path=f"{path} valido")
            self.record("POST", path, valid.status_code, "valido")

    def test_ciclo_equipo_agentes_y_estado_publico(self) -> None:
        def post(path, body):
            r = self.c.post(path, json=body, headers=self.h)
            self.check(r, path=path)
            self.assertEqual(r.status_code, 200, r.text)
            return r.json()

        ctx = post("/hr/tools/contexto", {"tipo": "crowd", "zona": "gate_b", "texto": "Cola en B"})
        self.assertIn("zonas", ctx)
        sit = post("/hr/tools/analizar_situacion", {})
        self.assertIn("modo", sit)
        opened = post("/hr/tools/decidir", {
            "agente": "triaje", "incident_id": "nuevo", "prioridad": 6, "zona": "front_pit",
            "porque": "Mareo en el foso, simulación N=1.", "tipo": "crowd",
        })
        iid = opened["incident_id"]
        acts = post("/hr/tools/acciones_posibles", {"incidente": iid})
        self.assertGreaterEqual(acts.get("n") or len(acts.get("opciones") or []), 1)
        ens = post("/hr/tools/ensayar", {"opciones": ["mandar M2 al foso", "desviar puerta B → C"], "minutos": 10})
        self.assertTrue(ens.get("opciones"))
        cmp_ = post("/hr/tools/comparar_opciones", {
            "opciones": [o.get("texto") or o for o in (acts.get("opciones") or [])[:4]] or ["despachar", "vigilar"],
        })
        self.assertTrue(cmp_.get("tabla") or cmp_.get("elige") or cmp_.get("ok"))

        post("/hr/tools/decidir", {
            "agente": "prioridad", "incident_id": iid, "prioridad": 7,
            "porque": "El foso sube; prioridad 7.", "tipo": "crowd",
        })
        post("/hr/tools/decidir", {
            "agente": "recursos", "incident_id": iid, "prioridad": 6,
            "porque": "Hay médico libre.", "tipo": "crowd", "recursos": ["med_2"],
        })
        prop = post("/hr/tools/pizarra/publicar", {
            "de": "recursos", "para": "todos", "incidente": iid, "tipo": "propuesta",
            "texto": "Mandar med_2 al foso.",
        })
        obj = post("/hr/tools/pizarra/publicar", {
            "de": "critico", "para": "recursos", "incidente": iid, "tipo": "objecion",
            "enlaza": prop["id"], "texto": "Ese médico cubre otra cola.", "gravedad": "alta",
        })
        self.assertTrue(obj.get("ok"), obj)
        blocked = post("/hr/tools/decidir", {
            "agente": "equipo", "incident_id": iid, "prioridad": 6,
            "porque": "Ejecutar pese a la objeción.", "recursos": ["med_2"],
        })
        self.assertTrue(blocked.get("resolver_primero") or blocked.get("objeciones") or not blocked.get("ok")
                        or blocked.get("aceptadas") == [], blocked)
        leer = post("/hr/tools/pizarra/leer", {"agente": "critico", "incidente": iid, "n": 10})
        self.assertTrue(leer.get("mensajes") is not None)

        post("/hr/tools/memoria/guardar", {
            "id": "ce-humo-ciclo", "agente": "recursos", "tipo": "crowd", "zona": "front_pit",
            "razonamiento": "ciclo de humo", "resultado": {"texto": "objeción alta"},
        })
        lec = post("/hr/tools/memoria/lecciones", {
            "accion": "proponer", "id": "L-humo-1",
            "texto": "Si el crítico objeta en alta, no despachar ese recurso.",
            "evidencia": {"ids": ["ce-humo-ciclo"], "n": 3}, "tipo": "crowd", "para_agente": "recursos",
        })
        self.assertEqual(lec.get("estado"), "propuesta", lec)
        apr = self.c.post("/api/memoria/lecciones", json={"id": "L-humo-1", "accion": "aprobar", "by": "Ana"})
        self.check(apr, path="/api/memoria/lecciones aprobar")
        self.assertEqual(apr.status_code, 200, apr.text)
        rev = self.c.post("/api/memoria/lecciones", json={"id": "L-humo-1", "accion": "revocar", "by": "Ana"})
        self.check(rev, path="/api/memoria/lecciones revocar")
        self.assertEqual(rev.status_code, 200, rev.text)

        ad = self.c.get("/api/adaptacion")
        self.check(ad, path="/api/adaptacion")
        self.assertIn("umbrales", ad.json())
        agentes = self.c.get(f"/api/agentes/{iid}")
        self.check(agentes, path=f"/api/agentes/{iid}")
        self.assertEqual(agentes.status_code, 200, agentes.text)
        exp = self.c.get("/api/explica")
        self.check(exp, path="/api/explica")
        self.assertIn("enjambre", exp.json())

        st = self.s.state()
        for key in ("agentes", "enjambre", "telegram"):
            self.assertIn(key, st, key)
        self.assertIn(iid, st["agentes"])
        self.assertTrue(st["enjambre"].get("mensajes") is not None or st["enjambre"].get("agentes") is not None)
        self.assertIsInstance(st["telegram"], dict)
        blob = json.dumps({"agentes": st["agentes"], "enjambre": st["enjambre"]}, ensure_ascii=False)
        self.assertNotIn(SECRET, blob)
        self.record("CICLO", "/hr/tools/*", 200, iid)


def _clean_status(status: int, text: str) -> str | None:
    if _trace(text):
        return "traza"
    if status == 500:
        return "500"
    return None


def live_smoke(base: str, secret: str) -> dict:
    """Humo contra un servidor vivo. Devuelve conteos y fallos."""
    import httpx
    token = {"X-Mando-Token": secret}
    rows: list[dict] = []
    failures: list[str] = []
    app = create_app("demo-1", threaded=False, secret=secret)
    try:
        paths = []
        for route in app.routes:
            methods = getattr(route, "methods", None) or set()
            path = getattr(route, "path", None)
            if path:
                for method in methods:
                    if method in ("GET", "POST"):
                        paths.append((method, path))
    finally:
        app.state.session.close()
        app.state.chat.stop()
    paths = sorted(set(paths + [("GET", "/"), ("GET", "/acceso"), ("POST", "/mcp")]))
    with httpx.Client(base_url=base, timeout=8.0) as c:
        n = 0
        for method, path in paths:
            url = _fill(path)
            if "{" in url:
                continue
            if method == "GET":
                if path in ("/api/stream", "/api/duel/stream"):
                    url = path + "?limit=1"
                r = c.get(url)
            else:
                if path.startswith("/hr/") or path == "/mcp":
                    r = c.post(url, json={})
                    err = _clean_status(r.status_code, r.text)
                    if err:
                        failures.append(f"{method} {url} sin token: {err} {r.status_code}")
                    n += 1
                    rows.append({"method": method, "path": path, "status": r.status_code, "note": "sin token"})
                    if path == "/mcp":
                        continue
                    r = c.post(url, json=TOOL_VALID.get(path) or POST_VALID.get(path, {}), headers=token)
                else:
                    r = c.post(url, json=POST_VALID.get(path, {}))
            err = _clean_status(r.status_code, r.text)
            if err:
                failures.append(f"{method} {url}: {err} {r.status_code} {r.text[:160]}")
            rows.append({"method": method, "path": path, "status": r.status_code, "note": "vivo"})
            n += 1
        for path, body in TOOL_VALID.items():
            for name, payload in (("vacio", {}), ("unicode", {"texto": UNICODE, "zona": UNICODE, "porque": UNICODE}),
                                  ("tipos", {"limit": {"a": 1}, "prioridad": "alta", "zona": 1}),
                                  ("valido", body)):
                r = c.post(path, json=payload, headers=token)
                err = _clean_status(r.status_code, r.text)
                if err:
                    failures.append(f"POST {path} {name}: {err} {r.status_code}")
                rows.append({"method": "POST", "path": path, "status": r.status_code, "note": name})
                n += 1
            r = c.post(path, content=b"{", headers={**token, "Content-Type": "application/json"})
            err = _clean_status(r.status_code, r.text)
            if err:
                failures.append(f"POST {path} json-roto: {err}")
            n += 1
        ctx = c.post("/hr/tools/contexto", json={"tipo": "crowd", "zona": "gate_b"}, headers=token)
        sit = c.post("/hr/tools/analizar_situacion", json={}, headers=token)
        d = c.post("/hr/tools/decidir", json={
            "agente": "triaje", "incident_id": "nuevo", "prioridad": 6, "zona": "front_pit",
            "porque": "Humo vivo, simulación N=1.", "tipo": "crowd",
        }, headers=token)
        n += 3
        iid = (d.json() or {}).get("incident_id") if d.status_code == 200 else None
        if iid:
            c.post("/hr/tools/acciones_posibles", json={"incidente": iid}, headers=token)
            c.post("/hr/tools/ensayar", json={"opciones": ["mandar M2 al foso"], "minutos": 8}, headers=token)
            c.post("/hr/tools/comparar_opciones", json={"opciones": ["despachar", "vigilar"]}, headers=token)
            c.post("/hr/tools/decidir", json={
                "agente": "prioridad", "incident_id": iid, "prioridad": 7,
                "porque": "El foso sube.", "tipo": "crowd",
            }, headers=token)
            prop = c.post("/hr/tools/pizarra/publicar", json={
                "de": "recursos", "para": "todos", "incidente": iid, "tipo": "propuesta",
                "texto": "Mandar med_2.",
            }, headers=token)
            pid = prop.json().get("id") if prop.status_code == 200 else ""
            c.post("/hr/tools/pizarra/publicar", json={
                "de": "critico", "para": "recursos", "incidente": iid, "tipo": "objecion",
                "enlaza": pid, "texto": "Objeción de humo vivo.", "gravedad": "alta",
            }, headers=token)
            c.post("/hr/tools/memoria/guardar", json={
                "id": "ce-vivo", "tipo": "crowd", "zona": "front_pit", "resultado": {"texto": "ok"},
            }, headers=token)
            c.post("/hr/tools/memoria/lecciones", json={
                "accion": "proponer", "id": "L-vivo", "texto": "Lección de humo vivo.",
                "evidencia": {"ids": ["ce-vivo"], "n": 3},
            }, headers=token)
            c.post("/api/memoria/lecciones", json={"id": "L-vivo", "accion": "aprobar", "by": "Ana"})
            c.post("/api/memoria/lecciones", json={"id": "L-vivo", "accion": "revocar", "by": "Ana"})
            n += 10
            st = c.get("/api/state").json()
            for key in ("agentes", "enjambre", "telegram"):
                if key not in st:
                    failures.append(f"estado público sin {key}")
            ad = c.get("/api/adaptacion")
            ag = c.get(f"/api/agentes/{iid}")
            ex = c.get("/api/explica")
            n += 4
            for r, name in ((ctx, "contexto"), (sit, "analizar"), (d, "decidir"), (ad, "adaptacion"),
                            (ag, "agentes"), (ex, "explica")):
                err = _clean_status(r.status_code, r.text)
                if err:
                    failures.append(f"ciclo {name}: {err} {r.status_code}")
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[str(row["status"])] = by_status.get(str(row["status"]), 0) + 1
    return {"base": base, "n": n, "by_status": by_status, "failures": failures, "rows": rows}


if __name__ == "__main__":
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8861"
    secret = os.environ.get("HR_SECRET") or SECRET
    out = live_smoke(base, secret)
    print(json.dumps({k: out[k] for k in ("base", "n", "by_status", "failures")}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if out["failures"] else 0)
