"""Lanzamiento opt-in del workflow rápido; las decisiones llegan por las tools."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx

from motor.mando.mando import Mando

from . import abanico, cerebro, hr_config

if TYPE_CHECKING:
    from .app import Session

MAX_INFLIGHT = 3
MAX_RUNS = 100
POLL_S = 2.0


def configuration() -> dict:
    missing = []
    workflow = (os.environ.get("HR_WORKFLOW_RAPIDO") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", workflow):
        missing.append("HR_WORKFLOW_RAPIDO")
    if not abanico.api_base():
        missing.append("HR_API_BASE")
    if not abanico.api_key():
        missing.append("HR_API_KEY")
    if not abanico.callback_token():
        missing.append("HR_SECRET")
    try:
        url = urlsplit(abanico.callback_url())
        valid_url = (url.scheme in ("http", "https") and url.hostname
                     and not url.username and not url.password
                     and url.path in ("", "/") and not url.query and not url.fragment)
    except ValueError:
        valid_url = False
    if not valid_url:
        missing.append("MANDO_PUBLIC_URL (URL base, sin /hr/events)")
    if hr_config.environment() not in ("development", "production"):
        missing.append("HR_ENV (development o production)")
    if cerebro.mode() != "agente":
        missing.append("MANDO_CEREBRO=agente")
    return {"ready": not missing, "missing": missing, "workflow": "prueba-ana-rapido",
            "environment": hr_config.environment(), "timeout_s": cerebro.timeout_s()}


@dataclass
class Aviso:
    text: str
    channel: str
    zone: str | None
    lang: str
    received_at: float


@dataclass
class Run:
    incident_id: str
    report_id: str
    correlation_id: str
    status: str = "pendiente"
    run_id: str = ""
    error: str = ""
    received: bool = False


class RapidoRunner:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.reports: dict[str, Aviso] = {}
        self.runs: dict[str, Run] = {}
        self.requests: dict[str, tuple[str, str | None, str]] = {}
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []

    def note_report(self, rid: str, text: str, channel: str, zone: str | None, lang: str) -> None:
        if cerebro.mode() == "agente" and os.environ.get("HR_WORKFLOW_RAPIDO"):
            self.reports[rid] = Aviso(text, channel, zone, lang, time.time())

    def launch_pending(self) -> None:
        agent = self.session.agent
        if (self.stop.is_set() or not self.reports or not configuration()["ready"]
                or not isinstance(agent, Mando)):
            return
        active = sum(t.is_alive() for t in self.threads)
        for inc in agent.live:
            if inc.id in self.runs or inc.id in self.session._cerebro_decided:
                continue
            rid = next((r for r in inc.reports if r in self.reports), None)
            if rid is None or active >= MAX_INFLIGHT or len(self.runs) >= MAX_RUNS:
                continue
            aviso = self.reports[rid]
            run = Run(inc.id, rid, f"{self.session.session_id}:{rid}")
            self.runs[inc.id] = run
            entrada = {"texto": aviso.text, "canal": aviso.channel, "zona_sugerida": aviso.zone or "",
                       "idioma": aviso.lang, "remitente": "informante", "correlation_id": run.correlation_id,
                       "incident_id": inc.id, "aviso_at": aviso.received_at}
            fields = ("texto", "canal", "zona_sugerida", "idioma", "remitente", "correlation_id")
            payload = dict({key: entrada[key] for key in fields}, transcripcion="",
                           entrada_json=json.dumps(entrada, ensure_ascii=False),
                           callback_url=abanico.callback_url(), callback_token=abanico.callback_token())
            thread = threading.Thread(target=self._run, args=(run, payload), daemon=True,
                                      name=f"rapido-{inc.id}")
            self.threads.append(thread)
            thread.start()
            active += 1

    def submit(self, request_id: str, text: str, zone: str | None) -> dict:
        with self.session.lock:
            old = self.requests.get(request_id)
            if old is not None:
                if old[:2] != (text, zone):
                    raise ValueError("request_id ya usado para otro aviso")
                return {"ok": True, "duplicate": True, "report_id": old[2]}
            if self.stop.is_set() or not configuration()["ready"]:
                raise RuntimeError("Completa la configuración de HappyRobot antes de lanzar")
            if not isinstance(self.session.agent, Mando) or self.session.world.done():
                raise RuntimeError("Inicia una sesión con el motor MANDO activo")
            if len(self.requests) >= MAX_RUNS or len(self.runs) >= MAX_RUNS:
                raise RuntimeError("Límite de pruebas de esta sesión alcanzado")
            if sum(t.is_alive() for t in self.threads) >= MAX_INFLIGHT:
                raise RuntimeError("Ya hay tres workflows en curso; espera a que terminen")
            result = self.session.report("operator", text, zone, source="operador", via="web")
            self.requests[request_id] = (text, zone, result["report_id"])
            self.session.tick()
            self.session.tick()
            run = next((r for r in self.runs.values() if r.report_id == result["report_id"]), None)
            return dict(result, duplicate=False, workflow_status=run.status if run else "sin_ejecucion")

    def bind_decision(self, body: dict) -> dict:
        correlation = str(body.get("correlation_id") or "")
        if not re.fullmatch(r"s-[0-9a-f]{16}:.+", correlation):
            return body
        with self.session.lock:
            run = next((r for r in self.runs.values() if r.correlation_id == correlation), None)
            if run is None or self.stop.is_set():
                raise ValueError("correlation_id no corresponde a una ejecución de esta sesión")
            if body.get("incident_id") not in (None, "", "nuevo", run.incident_id):
                raise ValueError("incident_id no corresponde a correlation_id")
            return dict(body, incident_id=run.incident_id)

    def record_decision(self, result: dict) -> None:
        with self.session.lock:
            run = self.runs.get(str(result.get("incident_id") or ""))
            if run is None:
                return
            run.received = True
            status = "decision_recibida" if result.get("ok") else "decision_bloqueada"
            self._update(run, status)

    def view(self) -> dict:
        rows = []
        for run in self.runs.values():
            row = asdict(run)
            phases = self.session._equipo.get(run.incident_id, {}).get("fases", {})
            row["rapida"] = run.received or "rapida" in phases
            row["revision"] = "revision" in phases
            if row["rapida"] and not run.received:
                row["status"] = "decision_recibida"
            rows.append(row)
        config = configuration()
        if not isinstance(self.session.agent, Mando):
            config["ready"] = False
            config["missing"].append("Motor MANDO no disponible")
        return dict(config, runs=rows[-20:])

    def close(self) -> None:
        self.stop.set()
        for thread in self.threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2)

    def _update(self, run: Run, status: str, error: str = "") -> None:
        with self.session.lock:
            if self.stop.is_set():
                return
            if run.received and status not in ("decision_recibida", "decision_bloqueada"):
                return
            if (run.status, run.error) == (status, error):
                return
            run.status, run.error = status, error
            self.session.log("cerebro", f"Workflow rápido · {run.incident_id} · {status}", run.incident_id)
            self.session._rebuild()

    def _received(self, run: Run) -> bool:
        with self.session.lock:
            return run.received or "rapida" in self.session._equipo.get(run.incident_id, {}).get("fases", {})

    def _run(self, run: Run, payload: dict) -> None:
        deadline = time.monotonic() + cerebro.timeout_s()
        try:
            with httpx.Client(timeout=8.0) as client:
                if self.stop.is_set():
                    return
                rid = abanico.lanzar_run(os.environ["HR_WORKFLOW_RAPIDO"].strip(), payload, client)
                with self.session.lock:
                    run.run_id = rid
                    if not self.stop.is_set():
                        self.session._rebuild()
                self._update(run, "en_curso")
                while not self.stop.is_set():
                    if self._received(run):
                        return
                    if time.monotonic() >= deadline:
                        self._update(run, "timeout", "No llegó la decisión rápida dentro del plazo")
                        return
                    response = client.get(f"{abanico.api_base()}/runs/{rid}",
                                          headers={"Authorization": f"Bearer {abanico.api_key()}"})
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, dict):
                        raise ValueError("Respuesta de run inválida")
                    status = str(data.get("status") or "")
                    if status in ("failed", "canceled", "cancelled"):
                        self._update(run, "fallido", f"HappyRobot: {status}")
                        return
                    if status in ("completed", "succeeded"):
                        self._update(run, "esperando_callback")
                    self.stop.wait(POLL_S)
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
            self._update(run, "fallido", f"Error al consultar HappyRobot ({type(exc).__name__})")
