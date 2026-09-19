"""Suite 5 — notificaciones raras por HTTP contra TestClient. El reloj tiene que seguir."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .common import ROOT, EvalResult, fail_ex, isolate_server_env, restore_env

SECRET = "evals-hr-secret"
HR = {"X-Mando-Token": SECRET}


def _ensure_fastapi() -> str | None:
    try:
        import fastapi  # noqa: F401
        from fastapi.testclient import TestClient  # noqa: F401
        return None
    except ImportError:
        venv = ROOT / "motor" / "server" / ".venv"
        for p in venv.glob("lib/python*/site-packages"):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))
        try:
            import fastapi  # noqa: F401
            from fastapi.testclient import TestClient  # noqa: F401
            return None
        except ImportError:
            return "no se pudo importar FastAPI/TestClient (¿motor/server/.venv?)"


def _clock(client) -> int:
    return int(client.get("/api/state").json()["t"])


def _step(client) -> int:
    r = client.post("/api/control", json={"cmd": "step", "n": 1})
    return r.status_code, _clock(client)


def _ok_status(code: int, expect: str) -> bool:
    if expect == "4xx":
        return 400 <= code < 500
    if expect == "2xx":
        return 200 <= code < 300
    if expect == "2xx|4xx":
        return 200 <= code < 500
    return False


def run(rapido: bool = False) -> list[EvalResult]:
    missing = _ensure_fastapi()
    if missing:
        return [EvalResult(id="N-http", suite="notificaciones", description="HTTP raro contra TestClient",
                           n=0, passed=0, notes=missing)]
    from fastapi.testclient import TestClient
    from motor.server.app import create_app

    old = isolate_server_env()
    cases = _cases(rapido)
    results: list[EvalResult] = []
    app = None
    try:
        app = create_app("demo-gates", threaded=False, secret=SECRET)
        client = TestClient(app, raise_server_exceptions=False)
        for spec in cases:
            results.append(_one(client, spec))
    except Exception as ex:
        results.append(EvalResult(
            id="N-http-setup", suite="notificaciones",
            description="Arranque del TestClient para notificaciones raras",
            n=1, passed=0, failures=[fail_ex(0, "demo-gates", repr(ex))],
        ))
    finally:
        if app is not None:
            try:
                app.state.session.close()
            except Exception:
                pass
            try:
                app.state.chat.stop()
            except Exception:
                pass
        restore_env(old)
    return results


def _cases(rapido: bool) -> list[dict[str, Any]]:
    all_cases = [
        {"id": "N-vacio", "expect": "4xx",
         "description": "POST /api/report vacío",
         "call": lambda c: c.post("/api/report", json={})},
        {"id": "N-enorme", "expect": "4xx",
         "description": "cuerpo > 8192 bytes",
         "call": lambda c: c.post("/api/report", content=b"x" * 9000,
                                  headers={"content-type": "application/json"})},
        {"id": "N-emojis", "expect": "2xx|4xx",
         "description": "aviso solo emojis",
         "call": lambda c: c.post("/api/report", json={"channel": "whatsapp", "text": "🔥🔥🔥💀"})},
        {"id": "N-json-roto", "expect": "4xx",
         "description": "JSON roto en /api/report",
         "call": lambda c: c.post("/api/report", content=b"{no json",
                                  headers={"content-type": "application/json"})},
        {"id": "N-duplicados", "expect": "2xx",
         "description": "dos avisos idénticos",
         "call": lambda c: (c.post("/api/report", json={"channel": "sms", "text": "hay una pelea en la barra"}),
                            c.post("/api/report", json={"channel": "sms", "text": "hay una pelea en la barra"}))},
        {"id": "N-contradiccion", "expect": "2xx",
         "description": "avisos contradictorios",
         "call": lambda c: (c.post("/api/report", json={"text": "fuego grande en la barra", "zone": "food"}),
                            c.post("/api/report", json={"text": "no hay ningún fuego, está todo bien", "zone": "food"}))},
        {"id": "N-desmentido", "expect": "2xx",
         "description": "desmentido / falsa alarma",
         "call": lambda c: (c.post("/api/report", json={"text": "un chico no responde delante del escenario", "zone": "front_pit"}),
                            c.post("/api/report", json={"text": "era broma, falsa alarma, no pasa nada", "zone": "front_pit"}))},
        {"id": "N-callback-tardio", "expect": "2xx|4xx",
         "description": "callback dispatch_result tardío de acción inexistente",
         "call": lambda c: c.post("/hr/events", json={
             "schema": "mando.hr.v1", "type": "dispatch_result", "message": "dispatch_result",
             "event_id": "eval-late-1", "action_id": "A-NOEXISTE", "result": "accept",
             "final": True, "eta_min": "3",
         }, headers=HR)},
        {"id": "N-callback-duplicado", "expect": "2xx|4xx",
         "description": "callback duplicado (mismo event_id)",
         "call": lambda c: (
             c.post("/hr/events", json={
                 "schema": "mando.hr.v1", "message": "progress", "event_id": "eval-dup-1",
                 "action_id": "A-0001", "stage": "call_started", "mode": "live",
             }, headers=HR),
             c.post("/hr/events", json={
                 "schema": "mando.hr.v1", "message": "progress", "event_id": "eval-dup-1",
                 "action_id": "A-0001", "stage": "call_started", "mode": "live",
             }, headers=HR),
         )},
        {"id": "N-callback-otra-escena", "expect": "2xx|4xx",
         "description": "callback de otra escena",
         "call": lambda c: c.post("/hr/events", json={
             "schema": "mando.hr.v1", "type": "dispatch_result", "message": "dispatch_result",
             "event_id": "eval-other-scene", "action_id": "s-otraescena:A-0001",
             "result": "accept", "final": True,
         }, headers=HR)},
        {"id": "N-hr-json-roto", "expect": "4xx",
         "description": "JSON roto en /hr/events (con token)",
         "call": lambda c: c.post("/hr/events", content=b"{broken",
                                  headers={**HR, "content-type": "application/json"})},
    ]
    return all_cases[:6] if rapido else all_cases


def _one(client, spec: dict[str, Any]) -> EvalResult:
    t0 = _clock(client)
    try:
        raw = spec["call"](client)
    except Exception as ex:
        return EvalResult(id=spec["id"], suite="notificaciones", description=spec["description"],
                          n=1, passed=0, failures=[fail_ex(0, "demo-gates", f"excepción {ex!r}")])
    resps = raw if isinstance(raw, tuple) else (raw,)
    codes = [r.status_code for r in resps]
    status_ok = all(_ok_status(code, spec["expect"]) for code in codes)
    detail = ""
    if spec["id"] == "N-callback-duplicado" and len(resps) == 2 and resps[1].status_code < 300:
        body = {}
        try:
            body = resps[1].json()
        except Exception:
            body = {}
        if body.get("duplicate") is not True and resps[1].status_code == 200:
            # duplicate flag es el tratamiento correcto; si no viene, aún vale 2xx si el reloj sigue
            detail = "segundo callback 200 sin duplicate=true"
    step_code, t1 = _step(client)
    clock_ok = step_code == 200 and t1 > t0
    ok = status_ok and clock_ok
    fails = []
    if not ok:
        fails.append(fail_ex(0, "demo-gates",
                             f"status={codes} expect={spec['expect']} step={step_code} t {t0}→{t1} {detail}".strip()))
    return EvalResult(
        id=spec["id"], suite="notificaciones", description=spec["description"] + " — 4xx o tratamiento correcto y el reloj sigue.",
        n=1, passed=int(ok), failures=fails,
        extra={"status": codes, "t0": t0, "t1": t1, "expect": spec["expect"]},
    )
