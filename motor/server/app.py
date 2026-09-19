"""Servidor local de la pantalla de mando. Ejecuta el ciclo de INTERFACES.md con un reloj configurable.

    uv run --project motor/server python -m motor.server --case demo-1 --speed 1

Solo escucha en 127.0.0.1 salvo que se pida `--lan` (red local, para los móviles del jurado).
"""
from __future__ import annotations

import asyncio
import copy
import hmac
import json
import os
import re
import secrets
import socket
import threading
import time
import traceback
import unicodedata
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from motor.contracts import ALWAYS_APPROVE, Action, ActionKind, ActionStatus
from motor.world import SimComms, World, load_festival

from . import intake, memoria, regression_live, views, whatif, validation, privacy, cerebro
from .comms_happyrobot import HappyRobotComms, load_contacts, public_base, shared_secret
from . import telegram_bot, hr_config, llm_parser_factory
from .ledger import open_ledger
from .security import SecurityGuard, require_operator, operator_authenticated
from .telegram_bot import safety_instruction
from .forecast import ForecastService
from .multi import Operators, identity, label, configured
from .personal import FieldStaff, external_notice
from . import espejo_telegram
from .espejo_telegram import TelegramMirror
from . import tg_roster
from .state_refresh import StateRefresh
from .evidence_runtime import ReceiptService, action_from_dict, evidence

HERE = Path(__file__).resolve().parent
MOTOR = HERE.parent
STATIC = HERE / "static"
CASES_DIR = MOTOR / "cases" / "data"
WORLD_DEMO = MOTOR / "world" / "demo_case.json"
HARNESS_OUT = MOTOR / "harness" / "out"

EFFECT_KINDS = {"resource_offline", "resource_online", "resource_no_answer", "resource_rejects", "zone_state",
                "zone_inflow", "zone_flag", "weather", "comms_down", "incident", "transport_cut"}

# ---------------------------------------------------------------- agente y adversario (de otras carpetas)

JURY_BUDGET = 3  # golpes del jurado por partida, como el presupuesto de Caos


def project_version() -> str:
    """Versión declarada en `motor/server/pyproject.toml`. Si no se puede leer, se dice, no se inventa."""
    try:
        import tomllib
        with (HERE / "pyproject.toml").open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except Exception:
        return "sin declarar"


def load_agent_class(kind: str = "mando") -> tuple[Any, str]:
    if kind in ("baseline", "baseline-reroute"):
        try:
            from motor.baseline import Baseline, BaselineReroute
            return (BaselineReroute, "lista fija con desvío") if kind == "baseline-reroute" else (Baseline, "lista fija")
        except Exception:
            from .fallback_agent import FallbackAgent
            return FallbackAgent, "relleno (lista fija no disponible)"
    try:
        from motor.mando import Mando  # type: ignore[attr-defined]
        return Mando, "Mando"
    except Exception:
        pass
    try:
        from motor.mando.mando import Mando
        return Mando, "Mando"
    except Exception:
        from .fallback_agent import FallbackAgent
        return FallbackAgent, "relleno (Mando no disponible)"


def load_playbook(which: str) -> tuple[Any, str]:
    """`learned` = manual con las lecciones que dejó el banco de pruebas; `seed` = el de partida; `none` = vacío."""
    try:
        from motor.mando.playbook import Playbook
    except Exception:
        return None, "sin manual"
    learned = HARNESS_OUT / "playbook.learned.json"
    try:
        if which in ("learned", "auto") and learned.exists():
            pb = Playbook.load(learned)
            return pb, f"aprendido ({len(pb.lessons)} lecciones)"
        if which == "none":
            return Playbook(), "vacío"
        pb = Playbook.load()
        return pb, f"de partida ({len(pb.lessons)} lecciones)"
    except Exception:
        return None, "sin manual (no se pudo leer)"


def load_chaos(seed: int) -> Any:
    try:
        from motor.caos import Chaos  # type: ignore[attr-defined]
    except Exception:
        return None
    for kwargs in ({"seed": seed}, {}):
        try:
            return Chaos(**kwargs)
        except TypeError:
            continue
        except Exception:
            return None
    return None


# ---------------------------------------------------------------- casos

def _jsonl(path: Path):
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield line


def list_cases() -> list[dict[str, Any]]:
    out = [{"id": "demo-gates", "alias": "demo-gates", "title": "Puerta B atascada: comparación de decisiones",
            "difficulty": 4, "families": ["crowd", "medical", "info"], "duration_min": 90}]
    for n, line in enumerate(_jsonl(CASES_DIR / "demo.jsonl"), 1):
        c = json.loads(line)
        meta = c.get("meta", {})
        out.append({"id": c["id"], "alias": f"demo-{n}", "title": meta.get("title", c["id"]), "story": meta.get("story", ""),
                    "difficulty": c.get("difficulty"), "families": c.get("families", []), "duration_min": c.get("duration_min")})
    return out


def load_case(case_id: str) -> dict[str, Any]:
    if case_id in ("demo-gates", "world-demo", "demo-0"):
        return json.loads(WORLD_DEMO.read_text(encoding="utf-8"))
    m = re.fullmatch(r"demo-(\d+)", case_id)
    if m:
        for n, line in enumerate(_jsonl(CASES_DIR / "demo.jsonl"), 1):
            if n == int(m.group(1)):
                return json.loads(line)
    needle = f'"{case_id}"'
    for name in ("demo.jsonl", "heldout.jsonl"):
        for line in _jsonl(CASES_DIR / name):
            if needle in line[:200] or needle in line:
                c = json.loads(line)
                if c.get("id") == case_id:
                    return c
    raise KeyError(case_id)


# ---------------------------------------------------------------- avisos y golpes del jurado

JURY_INCIDENTS: dict[str, dict[str, Any]] = {
    "collapse": {"label": "Persona desplomada, no responde", "family": "medical", "type": "cardiac_arrest", "severity": 10,
                 "deadline_min": 6, "needs": {"medical": 1, "ambulance": 1},
                 "text": "Hay una persona en el suelo que no responde y no respira bien, ¡ayuda!",
                 "words": ("no respira", "no responde", "inconsciente", "desplom", "infarto", "collapsed", "not breathing")},
    "heat": {"label": "Golpe de calor", "family": "medical", "type": "heat_stroke", "severity": 7, "deadline_min": 12,
             "needs": {"medical": 1}, "text": "Una chica se ha mareado por el calor, está muy roja y casi no habla",
             "words": ("calor", "mare", "desmay", "heat", "faint")},
    "fight": {"label": "Pelea", "family": "aggression", "type": "fight", "severity": 6, "deadline_min": 10,
              "needs": {"security": 2}, "text": "Hay una pelea entre varios tíos, se están pegando fuerte",
              "words": ("pelea", "pegando", "fight", "puñet")},
    "child": {"label": "Menor perdido", "family": "info", "type": "lost_child", "severity": 7, "deadline_min": 18,
              "needs": {"security": 1, "volunteer": 1}, "text": "He encontrado a un niño de unos seis años solo y llorando, no encuentra a sus padres",
              "words": ("niñ", "menor", "perdid", "child", "kid")},
    "smoke": {"label": "Humo o fuego", "family": "infra", "type": "small_fire", "severity": 8, "deadline_min": 8,
              "needs": {"security": 2, "tech": 1}, "text": "Sale humo de un puesto de comida y huele a quemado, hay llamas pequeñas",
              "words": ("humo", "fuego", "llamas", "quemad", "fire", "smoke")},
    "harassment": {"label": "Acoso a una persona", "family": "aggression", "type": "harassment_group", "severity": 5,
                   "deadline_min": 12, "needs": {"security": 1}, "text": "Un grupo está acosando a una chica y no la dejan irse",
                   "words": ("acos", "molest", "harass")},
    "barrier": {"label": "Valla rota", "family": "infra", "type": "barrier_failure", "severity": 8, "deadline_min": 10,
                "needs": {"tech": 1, "security": 2}, "text": "Se ha soltado una valla y la gente se apoya encima, va a ceder",
                "words": ("valla", "barrera", "barrier")},
    "surge": {"label": "Empujones, la gente se aplasta", "family": "crowd", "type": "crowd_surge_general", "severity": 8,
              "deadline_min": 10, "needs": {"security": 2, "medical": 1},
              "text": "Hay una avalancha, la gente empuja y nos estamos aplastando, no podemos salir",
              "words": ("aplast", "avalancha", "empuj", "crush", "agobi")},
}

STRIKE_PRESETS: dict[str, dict[str, Any]] = {
    "block_ambulance": {"label": "Bloquear la ambulancia",
                        "effect": {"kind": "resource_offline", "resource": "amb_1", "n": 15, "reason": "bloqueada por la multitud"}},
    "close_gate": {"label": "Cerrar una puerta", "effect": {"kind": "zone_state", "zone": "gate_a", "state": "closed"}},
    "no_answer": {"label": "Un equipo deja de contestar", "effect": {"kind": "resource_no_answer", "resource": "auto", "n": 8}},
    "food_blackout": {"label": "Apagón en restauración", "effect": {"kind": "zone_flag", "zone": "food", "flag": "power", "value": False}},
    "storm": {"label": "Tormenta", "effect": {"kind": "weather", "rain": True, "wind_kmh": 72, "alert": "tormenta"}},
    "voice_down": {"label": "Cortar el canal de voz", "effect": {"kind": "comms_down", "channel": "voice", "n": 10}},
}


def _plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def needs_approval(a: Action) -> bool:
    """Lo que el bucle NO aplica sin una aprobación registrada: lo que el contrato marca siempre, cerrar una zona y
    cualquier otra acción que el propio agente haya marcado como `approve` (megafonía general, desvíos sin ensayar…)."""
    return (a.kind in ALWAYS_APPROVE or (a.kind == ActionKind.SET_ZONE and a.params.get("state") == "closed")
            or str(a.autonomy) == "approve")


# ---------------------------------------------------------------- sesión

class Session:
    callback_url = ""  # lo fija create_app: adónde devuelve HappyRobot los webhooks
    chat_router: Any = None    # lo fija create_app: (session, action) -> canal. Preguntas a quien está en una conversación de recogida
    ask_router: Any = None     # lo fija create_app: (session, action) -> bool. El bot de Telegram se queda las preguntas a los suyos
    extra_state: Any = None    # lo fija create_app: () -> dict con lo que no es de la partida (telegram, enlaces)

    def __init__(self, case: dict[str, Any], *, seed: int | None = None, speed: float = 1.0, comms_mode: str = "sim",
                 autoplay: bool = False, threaded: bool = True, playbook: str = "auto", agent_kind: str = "mando",
                 replay: dict[str, Any] | None = None, auto_approve_min: int | None = None, local_params: bool = True) -> None:
        self.case = case
        self.playbook_choice = playbook
        self.local_params = local_params
        self.agent_kind = agent_kind
        self.replay = replay                      # test bloqueado que se re-ejecuta: {n, author, inputs, before}
        self.auto_approve_min = auto_approve_min  # solo en /duelo: un «operador simulado» aprueba a los N minutos
        self.inputs: list[dict[str, Any]] = []    # todo lo que entra de fuera, con su minuto: permite repetir la partida
        self._replay_i = 0
        self.replay_result: dict[str, Any] | None = None
        self.locked_tests: list[dict[str, Any]] = []
        self._seen_breaks = 0
        self._awaiting_seen: dict[str, float] = {}
        self._escalated: set[str] = set()
        self.decision_latency: list[dict[str, Any]] = []
        self.seed = int(seed if seed is not None else case.get("seed", 0))
        self.session_id = f"s-{secrets.token_hex(8)}"
        self.speed = max(0.1, min(64.0, float(speed)))
        self.comms_mode = comms_mode if comms_mode in ("sim", "happyrobot") else "sim"
        self.slow_on_call = os.environ.get("HR_SLOW_ON_CALL", "1") != "0"
        self.running = autoplay
        self.lock = threading.RLock()
        self.version = 0
        self._state_json = "{}"
        self._state: dict[str, Any] = {}
        self.server_log: list[dict[str, Any]] = []
        self.approvals: dict[str, dict[str, Any]] = {}
        self.strikes: list[dict[str, Any]] = []
        self.unsafe_blocked = 0
        self.agent_errors = 0
        self.engine_error = None
        self._snapshot: dict[str, Any] = {}
        self._n_jury = 0
        self._prev_occ: dict[str, int] = {}
        self._report_extra: dict[str, dict[str, Any]] = {}
        self._report_meta: dict[str, dict[str, Any]] = {}   # por report_id: canal real, pulsera, vía de entendimiento, instrucción
        self._report_caps: dict[str, str] = {}
        self._report_public_refs: dict[str, str] = {}
        self._followers: dict[str, float] = {}              # report_id -> última vez que su autor miró el estado (página web)
        self.web_asks: dict[str, dict[str, Any]] = {}       # action_id -> {report, question}: pregunta de Mando a un informante web
        self.report_refs: dict[str, str] = {}               # report_ref de la plataforma (una conversación) -> primer report_id
        self.operator_orders: list[dict[str, Any]] = []     # correcciones del operador tras un «¿y si…?»: lecciones candidatas
        self._equipo: dict[str, dict[str, Any]] = {}
        self._equipo_raw: dict[tuple[str, str], dict[str, Any]] = {}

        self.festival = load_festival()
        self.world = World.from_case(case, self.seed)
        self.sim = SimComms(self.world, self.seed)
        self.ledger = open_ledger()
        self.comms = HappyRobotComms(self.world, self.sim, session_id=self.session_id, mode=self.comms_mode,
                                     contacts=load_contacts(), incident_lookup=self._incident_for_comms,
                                     is_approved=self._approval_record, on_log=self.log, ledger=self.ledger)
        try:
            voice = getattr(self.comms, "voice_mode", os.environ.get("MANDO_VOICE_MODE", "web_call"))
            self.ledger.session_start(self.session_id, case_id=str(case.get("id") or ""),
                                      voice_mode=str(voice), speed=self.speed, comms_mode=self.comms_mode)
        except Exception:
            pass
        if not public_base() and Session.callback_url:
            self.comms.callback_url = Session.callback_url
        self.comms.external_ask = self._route_ask
        try:
            self.comms.ask_wait_s = float(os.environ.get("MANDO_ASK_WAIT_S", "45"))
        except ValueError:
            self.comms.ask_wait_s = 45.0
        agent_cls, self.agent_name = load_agent_class(agent_kind)
        pb, self.playbook_name = load_playbook(playbook) if agent_kind == "mando" else (None, "lista fija, sin manual")
        kwargs: dict[str, Any] = {"playbook": pb, "comms": self.comms}
        if local_params and agent_kind == "mando" and memoria.LOCAL_APPROVED_PATH.exists():
            kwargs["params"] = str(memoria.LOCAL_APPROVED_PATH)
        self.llm_parser = False
        if agent_kind == "mando":
            cascade = llm_parser_factory.build_cascade_parser()
            if cascade is not None:
                kwargs["parser"] = cascade
                self.llm_parser = True
        self.twin = False
        try:  # el gemelo para ensayar: solo si el mundo ya lo ofrece y el agente lo acepta
            import inspect
            if hasattr(self.world, "twin") and "twin" in inspect.signature(agent_cls.__init__).parameters:
                kwargs["twin"] = lambda: self.world.twin()
                self.twin = True
        except (TypeError, ValueError):
            pass
        try:
            self.agent = agent_cls(**kwargs)
        except Exception:
            self.log("chaos", "Mando no arranca: " + traceback.format_exc(limit=1).strip().splitlines()[-1] + ". Entra el agente de relleno")
            from .fallback_agent import FallbackAgent
            self.agent, self.agent_name = FallbackAgent(comms=self.comms), "relleno (Mando falló al arrancar)"
        cerebro.attach(self)
        self.chaos = load_chaos(self.seed)

        self.operators = Operators(self)
        self.staff = FieldStaff(self)
        self.tg_mirror = TelegramMirror(self)   # espejo del despacho por Telegram (HappyRobot decide, aquí solo se ve)
        self._tg_approval_marks: dict[str, dict[str, Any]] = {}  # action_id → sello Telegram (sin ejecutar por defecto)
        self.refresh = StateRefresh(self)
        self.receipts = ReceiptService()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._forecast: ForecastService | None = None
        self._rebuild()
        self._thread: threading.Thread | None = None
        if threaded:
            self._forecast = ForecastService(self)
            self._thread = threading.Thread(target=self._loop, name="mando-clock", daemon=True)
            self._thread.start()

    # ------------------------------------------------------------ reloj
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self.running and not self.world.done():
                    self.tick()
                    speed = self.speed
                    if self.slow_on_call and self.comms.view()["in_flight_real"]:
                        speed = min(speed, 0.2)
                    self._wake.wait(1.0 / speed)
                else:
                    with self.lock:
                        self.comms.sweep()
                        if self.comms.revision != self._comms_revision:
                            self._rebuild()
                    self._wake.wait(0.25)
            except Exception as exc:
                # El hilo sigue vivo; un mundo posiblemente inconsistente queda pausado.
                with self.lock:
                    self.running = False
                    self.engine_error = {"type": type(exc).__name__, "t": self.world.t}
                    self.log("engine_error", f"ERROR del motor: {type(exc).__name__}. Simulación pausada")
                    try:
                        self._rebuild()
                    except Exception:
                        self._state.update(engine_error=self.engine_error, version=self.version + 1)
                        self._state.setdefault("session", {})["running"] = False
                        self._state_json = json.dumps(self._state, ensure_ascii=False, default=str)
                        self.version += 1
                self._wake.wait(0.25)
            self._wake.clear()

    def close(self) -> None:
        self._stop.set()
        self.refresh.close()
        self.receipts.close()
        self._wake.set()
        if self._forecast is not None:
            self._forecast.close()
        thread = getattr(self, "_thread", None)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        self.comms.close()
        led = getattr(self, "ledger", None)
        if led is not None:
            try:
                led.close()
            except Exception:
                pass
        recorder = getattr(self, "recorder", None)
        if recorder is not None:
            recorder.close()

    def tick(self) -> None:
        """Un minuto simulado, con el ciclo exacto de INTERFACES.md."""
        with self.lock:
            if self.world.done():
                self.running = False
                return
            self._apply_replay()
            self._auto_approve()
            obs = self.staff.observation(self.world.observe())
            self._wait_for_people()
            try:
                actions = self.agent.tick(obs)
            except Exception as exc:
                self.agent_errors += 1
                self.engine_error = {"type": type(exc).__name__, "t": self.world.t, "source": "agent"}
                self.log("engine_error", f"ERROR del agente: {type(exc).__name__}. El mundo sigue")
                actions = []
            actions = cerebro.after_tick(self, actions)
            for a in actions:
                if a.status == ActionStatus.AWAITING_APPROVAL:
                    continue
                if needs_approval(a) and not self._approval_record(a.id):
                    self.unsafe_blocked += 1
                    self.log("approval", f"BLOQUEADA {a.id} ({a.kind}): exige aprobación humana y no la tiene", a.id)
                    continue
                self.receipts.capture(self.world, a, human=a.id in self.approvals)
                self.world.apply(a)
            self._signal_broken_plans()
            self.world.step()
            self.receipts.observe(self.world)
            if self.world.done():
                self.running = False
            self._rebuild()
            if self.world.done() and self.replay and self.replay_result is None:
                self.replay_result = regression_live.save_result(self.replay["n"], self._state["metrics"])
                verdict = "PASA" if self.replay_result["passed"] else "NO PASA"
                self.log("lesson", f"TEST Nº {self.replay['n']} (autor: {self.replay['author']}): {verdict} · críticos fallidos "
                                   f"antes {self.replay['before'].get('critical_failed')}, ahora {self.replay_result['critical_failed']}")
                self._rebuild()

    def _wait_for_people(self) -> None:
        """El plazo de confirmación de una persona es real, no HOLD_MAX minutos acelerados del núcleo."""
        if self.replay or self.agent_kind != "mando":
            return
        now = time.monotonic()
        for inc in getattr(self.agent, "incidents", {}).values():
            meta = getattr(self.agent, "meta", {}).get(inc.id)
            if meta is None or not meta.hold:
                continue
            reports = [self._report_meta[r] for r in inc.reports if r in self._report_meta
                       and self._report_meta[r].get("via") in ("web", "chat", "telegram")]
            if not reports:
                continue
            with self.comms._lock:
                deadlines = [f["deadline"] for f in self.comms._inflight.values()
                             if f.get("external") and f["action"].incident == inc.id]
            deadline = max(deadlines, default=max(r.get("received_at", now) for r in reports) + self.comms.ask_wait_s)
            if now <= deadline:
                meta.hold_since = self.world.t
            else:
                meta.hold = False
                meta.dirty = "sin respuesta de la persona: actuar con la información disponible"

    def _apply_replay(self) -> None:
        """Re-ejecución determinista: cada entrada grabada vuelve a entrar en su mismo minuto, antes del tick."""
        if not self.replay:
            return
        items = self.replay["inputs"]
        while self._replay_i < len(items) and items[self._replay_i]["t"] <= self.world.t:
            it = items[self._replay_i]
            self._replay_i += 1
            if it["kind"] == "report":
                self.report(it["channel"], it["text"], it.get("zone"), preset=it.get("preset"), source=it.get("source", "jurado"),
                            lang=it.get("lang", "es"), wristband=it.get("wristband"), via=it.get("via"), where=it.get("where"),
                            understood=it.get("understood"), update_of=it.get("update_of"))
            elif it["kind"] == "operator_order":
                self.operator_order(it["action"], by=it.get("by", "operador-1"), note=it.get("note", ""))
            elif it["kind"] == "strike":
                self.strike(it["effect"], origin=it.get("origin", "jury"), label=it.get("label", ""), author=it.get("author", ""),
                            enforce_budget=False, client_id=it.get("client_id"))
            elif it["kind"] == "approve":
                self.approve(it["action_id"], it["ok"], it.get("note", ""), by=it.get("by", "operador-1"))

    def _auto_approve(self) -> None:
        if self.auto_approve_min is None:
            return
        for a in self._snapshot.get("actions", []):
            if a.get("status") == "awaiting_approval" and self.world.t - int(a.get("t") or 0) >= self.auto_approve_min:
                self.approve(a["id"], True, "operador simulado del duelo", by="operador-simulado")

    def _signal_broken_plans(self) -> None:
        """Si se rompe un supuesto con alguien AL TELÉFONO por ese incidente, la orden cambia dentro de la llamada."""
        live = self.comms.live_real_calls()
        if not live:
            return
        try:
            snap = self.agent.snapshot()
        except Exception:
            return
        new = [e for e in snap.get("log", []) if e.get("kind") == "assumption_broken" and e.get("t") == self.world.t]
        if not new:
            return
        h = self._humanizer()
        for e in new:
            inc = (e.get("data") or {}).get("incident")
            old_plan = (e.get("data") or {}).get("plan")
            nxt = next((p for p in snap.get("plans", []) if p.get("supersedes") == old_plan), None)
            for call in live:
                if call.get("incident") != inc or not call.get("stage") or call.get("result"):
                    continue
                acts = {a["id"]: a for a in snap.get("actions", [])}
                redo = next((acts[x] for x in (nxt or {}).get("steps", []) if x in acts and acts[x].get("resource") == call.get("resource")
                             and acts[x].get("kind") == "dispatch" and acts[x]["id"] != call["action_id"]), None)
                if redo and redo.get("zone") and redo["zone"] != call.get("zone"):
                    text = f"Cambio de planes: ve a {h(redo['zone'])}, no a {h(call.get('zone') or '')}."
                else:  # su orden no cambia, pero lo que ha dejado de ser verdad le afecta: se le dice, sin jerga interna
                    m = re.search(r"«([^»]+)»", str(e.get("text", "")))
                    text = h(f"Aviso: ha dejado de cumplirse «{m.group(1) if m else 'un supuesto del plan'}». "
                             f"Tu orden no cambia: sigue hacia {call.get('zone') or 'tu destino'}.")
                threading.Thread(target=self.comms.change_orders, args=(call["action_id"], text, {"incident_id": inc}), daemon=True).start()

    def _humanizer(self) -> views.Humanizer:
        if not hasattr(self, "_hum"):
            obs = self.world.observe()
            self._hum = views.Humanizer({z.id: z.name for z in obs.zones.values()}, {r.id: r.name for r in obs.resources.values()})
        return self._hum

    def control(self, cmd: str, value: Any = None) -> None:
        if cmd == "play":
            self.running = True
        elif cmd == "pause":
            self.running = False
        elif cmd == "toggle":
            self.running = not self.running
        elif cmd == "step":
            self.running = False
            self.tick()
        elif cmd == "speed":
            try:
                self.speed = max(0.1, min(64.0, float(value)))
            except TypeError:
                raise ValueError("velocidad ilegible")
        else:
            raise ValueError(cmd)
        self._wake.set()
        self._rebuild()

    # ------------------------------------------------------------ entradas de personas
    def log(self, kind: str, text: str, ref: str | None = None, **data: Any) -> None:
        inc = None
        agent = getattr(self, "agent", None)
        action = getattr(agent, "actions", {}).get(ref)
        if action is not None:
            inc = self._incident_for_comms(action.incident)
        elif ref in getattr(agent, "incidents", {}):
            inc = self._incident_for_comms(ref)
        if (getattr(self, "_report_meta", {}).get(ref, {}).get("reserved") or (inc or {}).get("reserved") or data.get("reserved")):
            text = "Incidente reservado"
            data = {k: v for k, v in data.items() if k in ("via", "understood", "real", "fallback")}
        self.server_log.append({"t": int(getattr(self.world, "t", 0)) if hasattr(self, "world") else 0, "kind": kind,
                                "text": privacy.scrub(text), "ref": ref, "data": privacy.scrub(data), "src": "server"})

    def _approval_record(self, action_id: str) -> dict[str, Any] | None:
        rec = self.approvals.get(action_id)
        return rec if rec and rec.get("ok") else None

    def approve(self, action_id: str, ok: bool, note: str = "", by: str = "operador-1") -> bool:
        if type(ok) is not bool:
            raise ValueError("ok debe ser booleano")
        with self.lock:
            pending = {a["id"] for a in self._snapshot.get("actions", []) if a.get("status") == "awaiting_approval"}
            if action_id not in pending:
                return False
            proposal = next(a for a in self._snapshot["actions"] if a["id"] == action_id)
            self.agent.approve(action_id, ok, note)
            current = next((a for a in self.agent.snapshot().get("actions", []) if a["id"] == action_id), None)
            if current is None or current.get("status") == "awaiting_approval":
                return False
            if not ok:
                self.receipts.capture(self.world, action_from_dict(proposal), accepted=False, human=True)
            self.approvals[action_id] = {"approval_id": f"ap-{len(self.approvals) + 1:04d}", "ok": bool(ok), "by": by,
                                         "t": self.world.t, "note": note, "used": False}
            asked = next((int(a.get("t") or 0) for a in self._snapshot.get("actions", []) if a["id"] == action_id), self.world.t)
            seen = self._awaiting_seen.pop(action_id, None)
            if by != "operador-simulado":  # latencia de decisión HUMANA: desde que se pide hasta que alguien decide
                self.decision_latency.append({"action": action_id, "sim_min": self.world.t - asked,
                                              "real_s": round(time.monotonic() - seen, 1) if seen else None})
            if not self.replay:
                self.inputs.append({"t": self.world.t, "kind": "approve", "action_id": action_id, "ok": bool(ok), "note": note, "by": by})
            self._rebuild()
        self._wake.set()
        return True

    def report(self, channel: str, text: str, zone: str | None = None, *, preset: str | None = None,
               source: str = "jurado", lang: str = "es", extracted: dict[str, Any] | None = None,
               wristband: str | None = None, via: str | None = None, where: str | None = None,
               understood: str | None = None, preset_hint: str | None = None, update_of: str | None = None) -> dict[str, Any]:
        """Aviso de una persona. Si se reconoce de qué habla, nace un incidente VERDADERO en el mundo (quien avisa
        es la verdad del caso); si no, entra solo el aviso y Mando tendrá que preguntar.

        `via` = canal REAL (telegram, email, web…; el contrato solo conoce voice/sms/whatsapp/…). `where` = dónde nace el
        incidente verdadero cuando el canal no sabe la zona (no se le chiva a Mando). `wristband` = código de pulsera de
        demostración: sus etiquetas de asistencia suben la gravedad UN escalón y viajan en el texto; el acceso VIP no cambia
        nada; una pulsera «Personal» marca el aviso como verificado. Por aquí solo se CREAN avisos."""
        text = (text or "").strip()[:400]
        zones = {z["id"] for z in self.festival["zones"]}
        zone = zone if zone in zones else None
        where = where if where in zones else None
        prof = intake.wristband(wristband)
        with self.lock:
            if not self.replay:
                self.inputs.append({"t": self.world.t, "kind": "report", "channel": channel, "text": text, "zone": zone,
                                    "preset": preset, "source": source, "lang": lang, "wristband": wristband, "via": via,
                                    "where": where, "understood": understood, "update_of": update_of})
            self._n_jury += 1
            rid = f"j-{self._n_jury:03d}"
            spec = JURY_INCIDENTS.get(preset or "")
            if spec is None and text:
                plain = _plain(text)
                spec = next((s for s in JURY_INCIDENTS.values() if any(_plain(w) in plain for w in s["words"])), None)
            if spec is None:
                spec = JURY_INCIDENTS.get(preset_hint or "")
            said = text or (spec["text"] if spec else "")
            safety = safety_instruction(said)
            seen_source = source
            if prof is not None:
                if prof["tags"]:
                    said = f"{said} Persona con: {', '.join(prof['tags'])}."[:400]
                if prof["verified_staff"]:
                    seen_source = f"{source} · personal verificado ({prof.get('role') or 'personal'})"[:60]
            contract_channel = channel if channel in ("voice", "sms", "whatsapp", "radio", "operator", "sensor") else "whatsapp"
            rep = {"id": rid, "channel": contract_channel, "source": seen_source, "lang": lang, "text": said, "zone_hint": zone}
            first = self._report_meta.get(update_of or "")
            if first is not None:
                # ACTUALIZACIÓN de un aviso que ya entró (conversación que sigue): mismo incidente verdadero, nunca uno nuevo
                spec = None
                self.world.inject({"kind": "report_only", "reports": [dict(rep, truth_incident=first.get("truth"))]})
            elif spec is not None:
                t = self.world.t
                severity = min(10, spec["severity"] + (1 if prof and prof["raises_priority"] else 0))
                self.world.inject({"kind": "incident", "incident": {
                    "id": f"jx{self._n_jury}", "family": spec["family"], "type": spec["type"], "zone": zone or where or "general",
                    "severity": severity, "deadline": t + spec["deadline_min"], "needs": dict(spec["needs"])},
                    "reports": [rep]})
            else:
                self.world.inject({"kind": "report_only", "reports": [rep]})
            truth_id = first.get("truth") if first is not None else (f"jx{self._n_jury}" if spec is not None else None)
            if extracted:
                self._report_extra[rid] = extracted
            real = via or ("telegram" if source.startswith("telegram:") else "web" if source in ("jurado", "asistente") else contract_channel)
            self._report_meta[rid] = {"received_at": time.monotonic(), "via": real, "understood": understood or "local", "safety": safety[1] if safety else None,
                                      "truth": truth_id, "update_of": update_of if first is not None else None,
                                      "wristband": {k: prof[k] for k in ("code", "access", "tags", "verified_staff")} if prof else None}
            self._report_meta[rid]["reserved"] = bool((first or {}).get("reserved")) or (str((extracted or {}).get("sensitive")).lower() == "true") or privacy.sensitive(
                self.world.reports[-1], self.world.observe().zones)
            how = "entendido por HappyRobot" if understood == "happyrobot" else "entendido en local"
            self.log("report", f"Aviso de {source} por {real}: «{rep['text'][:80]}» · {how}"
                     + (f" · pulsera {prof['access']}" + (f" ({', '.join(prof['tags'])})" if prof["tags"] else "") if prof else ""),
                     rid, origin=source, extracted=extracted or {}, via=real, understood=understood or "local")
            if real == "chat":
                self.refresh.request()
            else:
                self._rebuild()
        return {"ok": True, "report_id": rid, "recognized": spec["label"] if spec else None,
                "safety": safety[1] if safety else None, "understood": understood or "local"}

    # ------------------------------------------------------------ preguntas de Mando a quien avisó
    def _route_ask(self, action: Action) -> str:
        """¿Esta pregunta va a alguien que avisó por un canal NUESTRO y está ahí para contestar? Telegram, o la página web
        de quien sigue su aviso. Devuelve el canal o "" (= que conteste HappyRobot o la simulación, como siempre)."""
        if (action.resource or action.params.get("purpose") == "sitrep"
                or action.params.get("to") in self.world.resources
                or str(action.params.get("to") or "").startswith("responsable")):
            return ""   # la pregunta es para un equipo o para el responsable de zona, no para quien avisó
        if Session.chat_router is not None:
            try:
                channel = Session.chat_router(self, action)
                if channel:
                    return channel
            except Exception:
                pass
        if Session.ask_router is not None:
            try:
                if Session.ask_router(self, action):
                    return "telegram"
            except Exception:
                pass
        now = time.monotonic()
        rid = next((r for r in action.params.get("reports") or [] if now - self._followers.get(r, -1e9) < 8.0
                    or self._report_meta.get(r, {}).get("via") in ("web", "chat", "telegram")), None)
        if rid is None:
            return ""
        self.web_asks[action.id] = {"report": rid, "question": str(action.params.get("message") or "¿Puedes darme más detalles?")}
        return "web"

    def answer_report(self, report_id: str, text: str) -> bool:
        aid = next((a for a, w in self.web_asks.items() if w["report"] == report_id and a not in self.comms._closed), None)
        if aid is None:
            return False
        ok = self.comms.answer_external(aid, text, channel="web")
        self._wake.set()
        return ok

    # ------------------------------------------------------------ «¿y si…?»: el operador corrige con una orden suya
    def operator_order(self, d: dict[str, Any], by: str = "operador-1", note: str = "") -> dict[str, Any]:
        """La persona ha ENSAYADO una alternativa y la ordena. Entra como acción manual; si Mando tenía pendiente una
        decisión del mismo tipo sobre esa zona, queda vetada; y se apunta como lección candidata para la memoria."""
        zone_names = {z["id"]: z["name"] for z in self.festival["zones"]}
        with self.lock:
            n = len(self.operator_orders) + 1
            action = whatif.candidate(d, set(zone_names), self.world.t, action_id=f"OP-{n:03d}")
            action.why = f"corrección del operador ({by})" + (f": {note}" if note else "")
            vetoed = [a["id"] for a in self._snapshot.get("actions", []) if a.get("status") == "awaiting_approval"
                      and a.get("kind") == str(action.kind) and a.get("zone") == action.zone]
            for aid in vetoed:
                self.approve(aid, False, f"el operador ordena otra cosa ({action.id})", by=by)
            if not self.replay:
                self.inputs.append({"t": self.world.t, "kind": "operator_order", "action": dict(d), "by": by, "note": note})
            self.approvals[action.id] = {"approval_id": f"ap-op-{n:03d}", "ok": True, "by": by, "t": self.world.t, "note": note, "used": True}
            self.receipts.capture(self.world, action, human=True)
            self.world.apply(action)
            h = self._humanizer()
            what = h(f"{str(action.kind).upper()} {action.zone or ''}" + (f" → {action.params['to']} ({round(action.params['fraction'] * 100)} %)"
                     if action.params.get("to") else f" {action.params.get('state', '')}")).strip()
            rec = {"id": action.id, "t": self.world.t, "by": by, "action": dict(d), "text": what, "vetoed": vetoed, "note": note}
            self.operator_orders.append(rec)
            self.log("approval", f"CORRECCIÓN DEL OPERADOR {action.id}: {what}" + (f" · veta {', '.join(vetoed)}" if vetoed else ""), action.id)
            self.log("lesson", f"LECCIÓN CANDIDATA: en este caso una persona prefirió «{what}» a lo que proponía Mando"
                     + (f" ({note})" if note else ""), action.id, candidate=True)
            self._rebuild()
        self._wake.set()
        return rec

    def jury_left(self, client_id: str | None = None) -> int:
        return max(0, JURY_BUDGET - sum(1 for k in self.strikes if k["origin"] == "jury"
                                      and (client_id is None or k.get("client_id") == client_id)))

    def strike(self, effect: dict[str, Any], origin: str = "jury", label: str = "", author: str = "",
               enforce_budget: bool = True, client_id: str | None = None) -> dict[str, Any]:
        with self.lock:
            effect = validation.strike_effect(effect, self.world)
            if origin == "jury" and enforce_budget and (self.jury_left() <= 0 or self.jury_left(client_id) <= 0):
                raise PermissionError("El jurado ya ha gastado sus 3 golpes en esta partida")
            if effect["kind"] == "resource_no_answer" and effect.get("resource") == "auto":
                moving = [r for r in self.world.observe().resources.values() if str(r.status) == "en_route"]
                effect = dict(effect, resource=moving[0].id if moving else "sec_2")
            self.world.inject({"kind": "world", "effect": effect})
            item = {"n": len(self.strikes) + 1, "t": self.world.t, "origin": origin, "label": label or effect["kind"], "effect": effect,
                    "author": author[:40], "client_id": client_id, "outcome": "pending", "broke": None, "new_plan": None,
                    "id": f"{self.session_id}-strike-{len(self.strikes) + 1}", "broken": [], "new_plans": [], "locked_test": None}
            if not self.replay:
                self.inputs.append({"t": self.world.t, "kind": "strike", "effect": effect, "origin": origin,
                                    "label": item["label"], "author": item["author"], "client_id": client_id})
            self.strikes.append(item)
            who = "DEL JURADO" if origin == "jury" else "DE CAOS" if origin == "chaos" else "DE " + origin.upper()
            self.log("chaos", f"GOLPE {who}: {item['label']}", None, effect=effect, origin=origin)
            self._rebuild()
        return item

    def chaos_suggestions(self) -> dict[str, Any]:
        with self.lock:
            raw, source = None, "relleno"
            if self.chaos is not None and hasattr(self.chaos, "suggest"):
                try:
                    raw, source = self.chaos.suggest(self.world, self.agent), "caos"
                except Exception:
                    self.log("chaos", "Caos falló al sugerir: " + traceback.format_exc(limit=1).strip().splitlines()[-1])
            unit = f"daño estimado a {getattr(self.chaos, 'lookahead', '?')} min" if source == "caos" else None
            items = [_norm_suggestion(dict(s, damage_unit=unit) if isinstance(s, dict) else s) for s in (raw or [])]
            items = [s for s in items if s]
            if not items:
                items, source = self._builtin_suggestions(), "relleno"
            return {"source": source, "t": self.world.t, "suggestions": items[:8]}

    def _builtin_suggestions(self) -> list[dict[str, Any]]:
        """Sugerencias mínimas mientras `motor/caos` no exista. Sin estimación de daño: no se inventa."""
        obs = self.world.observe()
        out: list[dict[str, Any]] = []
        for r in obs.resources.values():
            if str(r.status) == "en_route":
                out.append({"label": f"{r.name} deja de contestar", "why": f"Va de camino a {r.task or 'un incidente'}: el plan depende de que llegue",
                            "damage": None, "effect": {"kind": "resource_no_answer", "resource": r.id, "n": 8}})
        if any(i.get("family") == "medical" and i.get("status") not in ("resolved", "false_alarm", "failed")
               for i in self._snapshot.get("incidents", [])):
            out.append({"label": "Bloquear la ambulancia", "why": "Hay un incidente médico abierto y solo hay una ambulancia interna",
                        "damage": None, "effect": STRIKE_PRESETS["block_ambulance"]["effect"]})
        for z in obs.zones.values():
            if z.flags.get("reroute_to"):
                to = z.flags["reroute_to"]
                out.append({"label": f"Más gente hacia {obs.zones[to].name}", "why": f"Mando desvía {z.name} hacia ahí: el supuesto es que aguanta",
                            "damage": None, "effect": {"kind": "zone_inflow", "zone": to, "per_min": 200, "n": 15}})
        for key in ("voice_down", "storm", "food_blackout"):
            out.append(dict(STRIKE_PRESETS[key], why="Golpe genérico", damage=None))
        return out

    # ------------------------------------------------------------ estado para la pantalla
    def _incident_for_comms(self, incident_id: str | None) -> dict[str, Any] | None:
        if not incident_id:
            return None
        live = getattr(self.agent, "incidents", None)
        if isinstance(live, dict) and incident_id in live:
            d = live[incident_id].to_dict()
            d["reserved"] = d.get("reserved") or any(self._report_meta.get(r, {}).get("reserved") for r in d.get("reports", []))
            try:  # «posible parada cardiaca», no «cardiac_arrest»: es lo que se va a DECIR por teléfono
                from motor.mando.planner import label
                d["label"] = label(live[incident_id])
            except Exception:
                d["label"] = str(d.get("type", "")).replace("_", " ")
            return d
        return next((i for i in self._snapshot.get("incidents", []) if i.get("id") == incident_id), None)

    def _rebuild(self) -> None:
        with self.lock:
            for rid in privacy.private_reports(self.world.reports, self._report_meta, self.world.observe().zones):
                self._report_meta.setdefault(rid, {})["reserved"] = True
            try:
                snap = self.agent.snapshot() or {}
            except Exception:
                snap = self._snapshot
            self._comms_revision = self.comms.revision
            self._snapshot = snap
            from .hr_routing import prepare_outputs
            prepare_outputs(self, snap)
            self._state = privacy.project(self.operators.enrich(self._build_state(copy.deepcopy(snap))), self.world.reports,
                                          self._report_meta, self.world.observe().zones)
            if self._forecast is not None:
                self._forecast.observe()
            self._state["forecasts"] = self._forecast.view() if self._forecast is not None else []
            self._state["service_health"] = {"comms_down": dict(self.world.comms_down)}
            self._state["event_name"] = self.festival.get("name")
            from . import equipo as equipo_mod
            from . import enjambre as enjambre_mod
            self._state["agentes"] = equipo_mod.public_view(self, self._state)
            self._state["enjambre"] = enjambre_mod.public_view(self, self._state)
            self._state_json = json.dumps(self._state, ensure_ascii=False, default=str)
            self.version += 1
        recorder = getattr(self, "recorder", None)
        if recorder is not None:
            recorder.offer(self._state)

    def state(self) -> dict[str, Any]:
        return self._state

    def state_json(self) -> str:
        return self._state_json

    def _build_state(self, snap: dict[str, Any]) -> dict[str, Any]:
        w = self.world
        obs = w.observe()
        zones = []
        for z in obs.zones.values():
            prev = self._prev_occ.get(z.id, z.occupancy)
            zones.append({"id": z.id, "name": z.name, "kind": z.kind, "area_m2": z.area_m2, "capacity": z.capacity,
                          "occupancy": z.occupancy, "density": round(z.density, 2),
                          "ratio": round(z.occupancy / z.capacity, 3) if z.capacity else 0, "state": z.state,
                          "flags": z.flags, "delta": z.occupancy - prev})
        self._prev_occ = {z.id: z.occupancy for z in obs.zones.values()}
        real = set(self.comms.contacts["resources"]) if self.comms_mode == "happyrobot" else set()
        resources = [dict(r.to_dict(), real=r.id in real) for r in obs.resources.values()]
        for r in resources:
            r.pop("contact", None)  # los teléfonos no salen nunca a la pantalla ni al vídeo

        h = self._humanizer()
        zone_names = {z["id"]: z["name"] for z in zones}
        res_by_id = {r["id"]: r for r in resources}
        incidents = [dict(i) for i in _as_list(snap.get("incidents"))]
        actions = [dict(a) for a in _as_list(snap.get("actions"))]
        for a in actions:
            origen = a.get("origen") or (a.get("params") or {}).get("origen")
            if origen:
                a["origen"] = origen
        plans = _as_list(snap.get("plans"))
        by_action = {a.get("id"): a for a in actions}
        rep_inc = {rid: i.get("id") for i in incidents for rid in i.get("reports", [])}
        meta = self._report_meta
        reports = [{"id": r.id, "t": r.t, "channel": str(r.channel), "text": r.text, "lang": r.lang,
                    # el alias de Telegram es interno: a la pantalla solo llega «telegram»
                    "source": "telegram" if r.source.startswith("telegram:") and "verificado" not in r.source else re.sub(r"^telegram:\d+ · ", "", r.source),
                    "via": (meta.get(r.id) or {}).get("via") or str(r.channel), "understood": (meta.get(r.id) or {}).get("understood"),
                    "wristband": (meta.get(r.id) or {}).get("wristband"), "chat": (meta.get(r.id) or {}).get("chat"),
                    "zone_hint": r.zone_hint, "incident": rep_inc.get(r.id)} for r in w.reports[-60:]]
        plan_view = []
        for p in plans:
            steps = [dict({k: by_action[s].get(k) for k in ("id", "kind", "status", "resource", "zone", "why", "autonomy")},
                          reason=(by_action[s].get("params") or {}).get("reason"))
                     for s in p.get("steps", []) if s in by_action]
            plan_view.append(dict(p, steps=steps))
        agent_log = [dict(e, src="agent") for e in _as_list(snap.get("log"))]
        self.server_log = privacy.project({"incidents": incidents, "actions": actions, "log": self.server_log},
                                          w.reports, self._report_meta, w.observe().zones)["log"]
        log = sorted(agent_log[-160:] + self.server_log[-80:], key=lambda e: e.get("t", 0))[-140:]

        # lo reservado se enmascara ANTES de salir del servidor; después, ids → nombres que entiende una persona
        hidden = views.mask_reserved(incidents, reports, plan_view, log)
        for r in reports:
            if r.get("incident") in hidden:
                r["wristband"] = r["chat"] = None
        for i in incidents:
            i["explain"] = h(i.get("explain", ""))
            i["zone_name"] = zone_names.get(i.get("zone") or "")
            # pulseras asociadas a sus avisos: acceso y etiquetas, con texto (no solo color). Nunca en un incidente reservado
            i["wristbands"] = [] if i["id"] in hidden else [m["wristband"] for rid in i.get("reports", [])
                                                           if (m := meta.get(rid)) and m.get("wristband")]
        for e in log:
            e["text"] = h(e.get("text", ""))
        per_incident: dict[str, int] = {}
        for p in plan_view:
            p["objective"], p["why"] = h(p.get("objective", "")), h(p.get("why", ""))
            for st in p["steps"]:
                st["why"], st["reason"] = h(st.get("why", "")), h(st.get("reason"))
            for a in p.get("assumptions", []):
                a["text"] = h(a.get("text", ""))
            p["rehearsal"] = views.rehearsal(p, log)
            # replanificaciones repetidas del mismo incidente: se cuentan, no se apilan
            per_incident[p.get("incident") or p["id"]] = per_incident.get(p.get("incident") or p["id"], 0) + 1
            p["version"] = per_incident[p.get("incident") or p["id"]]
        for p in plan_view:
            p["versions_total"] = per_incident[p.get("incident") or p["id"]]

        approvals = []
        for a in actions:
            if a.get("status") != "awaiting_approval":
                continue
            self._awaiting_seen.setdefault(a["id"], time.monotonic())
            a = dict(a, why=h(a.get("why", "")), zone_name=zone_names.get(a.get("zone") or ""))
            a["card"] = views.decision_card(a, w.t)
            mark = self._tg_approval_marks.get(a["id"])
            if mark:
                a["telegram_decision"] = mark
            if a["card"] and a["card"]["escalated"] and a["id"] not in self._escalated:
                self._escalated.add(a["id"])
                self.log("approval", f"SIN DECISIÓN en {a['card']['window_min'] or '?'} min: {a['id']} ESCALA AL SUPLENTE"
                         + (f" ({a['card']['deputy']})" if a["card"]["deputy"] else ""), a["id"])
            a.pop("params", None)
            approvals.append(a)
        fronts = views.fronts(snap, incidents, actions, res_by_id, zone_names, w.t)
        by_inc = {i["id"]: i for i in incidents}
        for f in fronts:
            f["wristbands"] = by_inc.get(f["id"], {}).get("wristbands", [])
        truth = w.truth()
        views.strike_consequences(self.strikes, agent_log, plans, h)
        board = views.score_strikes(self.strikes, truth.get("incidents", {}), w.t, w.done())
        board.update(budget=JURY_BUDGET, left=self.jury_left(),
                     can_lock=any(k["outcome"] == "failed" for k in self.strikes), next_n=regression_live.next_number(),
                     culprit=next((k for k in reversed(self.strikes) if k["outcome"] == "failed"), None),
                     locked=self.locked_tests[-1] if self.locked_tests else None)

        meta = self.case.get("meta", {})
        return {
            "version": self.version + 1,
            "session": {"id": self.session_id, "case": self.case.get("id"), "title": meta.get("title", ""),
                        "story": meta.get("story", ""), "seed": self.seed, "running": self.running, "speed": self.speed,
                        "done": w.done(), "comms_mode": self.comms_mode, "agent": self.agent_name, "playbook": self.playbook_name,
                        "chaos": self.chaos is not None, "duration_min": self.case.get("duration_min"),
                        "agent_kind": self.agent_kind, "twin": self.twin, "cerebro": cerebro.mode(),
                        "cerebro_cadena": getattr(self, "_cerebro_cadena", None) or (
                            "plataforma" if cerebro.mode() == "agente" else cerebro.mode()),
                        "modo_degradado": cerebro.ETIQUETA_DEGRADADO if getattr(self, "_cerebro_degradado", False) else None,
                        "replay": dict({k: self.replay[k] for k in ("n", "author", "before")}, result=self.replay_result) if self.replay else None},
            "engine_error": self.engine_error,
            "fronts": fronts, "scoreboard": board,
            "t": w.t, "clock": obs.clock, "weather": obs.weather,
            "zones": zones, "resources": resources, "incidents": incidents, "reports": reports,
            "plans": plan_view, "approvals": approvals, "actions": actions[-60:], "log": log,
            "calls": self.comms.view(), "strikes": self.strikes[-10:],
            "metrics": self._metrics(snap, incidents, plans, truth),
            "lessons": snap.get("lessons", {}), "counters": snap.get("counters", {}),
            "funnel": self._funnel(w, incidents, truth),
            "operator_orders": self.operator_orders[-10:],
            **(Session.extra_state() if Session.extra_state is not None else {"telegram": {"status": "off"}, "links": {}}),
        }

    def _funnel(self, w: Any, incidents: list[dict[str, Any]], truth: dict[str, Any]) -> dict[str, Any]:
        """«Llegan cien mensajes y solo tres cambian algo»: N avisos recibidos → M incidentes → K acciones, por canal REAL
        y por vía de entendimiento. Un aviso «cambia algo» si abrió un incidente (no si se fusionó o era ruido)."""
        by_channel: dict[str, int] = {}
        by_understood = {"happyrobot": 0, "local": 0}
        for r in w.reports:
            m = self._report_meta.get(r.id) or {}
            ch = m.get("via") or str(r.channel)
            by_channel[ch] = by_channel.get(ch, 0) + 1
            if m:
                by_understood[m.get("understood") or "local"] = by_understood.get(m.get("understood") or "local", 0) + 1
        openers = {i["reports"][0] for i in incidents if i.get("reports")}
        acted = [a for a in truth.get("actions", []) if str(a.get("kind")) not in ("merge", "dismiss")]
        n = len(w.reports)
        return {"reports": n, "incidents": len(incidents), "actions": len(acted), "by_channel": by_channel,
                "by_understood": by_understood, "changed_something": len(openers),
                "per_100": round(100 * len(openers) / n, 1) if n else None}

    def _metrics(self, snap: dict[str, Any], incidents: list[dict[str, Any]], plans: list[dict[str, Any]],
                 truth: dict[str, Any]) -> dict[str, Any]:
        t_inc = truth.get("incidents", {})
        crit = [i for i in t_inc.values() if int(i.get("severity", 0)) >= 8]
        crit_failed = sum(1 for i in crit if str(i.get("status")) == "failed")
        firsts = [i["first_action_t"] - i["t_open"] for i in incidents
                  if i.get("first_action_t") is not None and i.get("t_open") is not None]
        if not firsts:
            firsts = [i["t_first_dispatch"] - i["t_open"] for i in t_inc.values() if i.get("t_first_dispatch") is not None]
        calls = list(self.comms.calls.values())
        failed = [c for c in calls if c.get("result") in ("reject", "no_answer")]
        ok_by_inc: dict[str, int] = {}
        for c in calls:
            if c.get("result") == "accept" and c.get("incident"):
                ok_by_inc[c["incident"]] = max(ok_by_inc.get(c["incident"], -1), c.get("t", 0))
        recovered = sum(1 for c in failed if c.get("incident") and ok_by_inc.get(c["incident"], -1) >= c.get("t", 0))
        unsafe = sum(1 for a in truth.get("actions", []) if _needs_approval_dict(a) and not self._approval_record(a.get("id", "")))
        counters = snap.get("counters", {})
        view = self.comms.view()
        return {
            "critical_failed": crit_failed, "critical_total": len(crit),
            "incidents_total": len(t_inc), "incidents_resolved": sum(1 for i in t_inc.values() if str(i.get("status")) == "resolved"),
            "time_to_first_action": round(sum(firsts) / len(firsts), 1) if firsts else None, "time_to_first_action_n": len(firsts),
            "replans": counters.get("replans", sum(1 for p in plans if p.get("supersedes"))),
            "assumptions_broken": counters.get("assumptions_broken", sum(1 for p in plans if p.get("invalidated_by"))),
            "calls_total": len(calls), "calls_failed": len(failed), "calls_recovered": recovered,
            "unsafe_actions": unsafe, "unsafe_blocked": self.unsafe_blocked,
            "approvals_requested": counters.get("approvals", len(self.approvals)),
            "wasted_dispatches": len(truth.get("wasted_dispatches", []) or []),
            "merges": counters.get("merges"), "false_alarms": counters.get("false_alarms"),
            "voice_turn_latency_ms": view["turn_latency_ms"], "voice_turn_latency_n": view["turn_latency_n"],
            "hook_rtt_ms": view["hook_rtt_ms"], "strikes": len(self.strikes), "agent_errors": self.agent_errors,
            "first_word_ms": view["first_word_ms"], "first_word_n": view["first_word_n"],
            "signal_rtt_ms": view["signal_rtt_ms"], "signals": view["signals"],
            "minutes_over_5": sum((truth.get("minutes_over_5") or {}).values()),
            "fronts_now": sum(1 for i in incidents if i.get("status") not in views.CLOSED),
            "fronts_peak": self._fronts_peak(incidents),
            "decision_latency_min": (round(sum(d["sim_min"] for d in self.decision_latency) / len(self.decision_latency), 1)
                                     if self.decision_latency else None),
            "decision_latency_s": (round(sum(d["real_s"] for d in self.decision_latency if d["real_s"] is not None)
                                         / max(1, sum(1 for d in self.decision_latency if d["real_s"] is not None)), 1)
                                   if any(d["real_s"] is not None for d in self.decision_latency) else None),
            "decision_latency_n": len(self.decision_latency),
            "peak_density": max((z.get("density", 0) for z in (truth.get("peak_density") or {}).values()), default=0),
        }

    def _fronts_peak(self, incidents: list[dict[str, Any]]) -> int:
        now = sum(1 for i in incidents if i.get("status") not in views.CLOSED)
        self._peak = max(getattr(self, "_peak", 0), now)
        return self._peak

    def lock_as_test(self, author: str, note: str = "") -> dict[str, Any]:
        with self.lock:
            rec = regression_live.lock(case=self.case, seed=self.seed, playbook=self.playbook_choice, inputs=list(self.inputs),
                                       metrics=self._state.get("metrics", {}), author=author, t=self.world.t, note=note)
            self.locked_tests.append({"n": rec["n"], "author": rec["author"]})
            culprit = next((k for k in reversed(self.strikes) if k["outcome"] == "failed"), None)
            if culprit is not None:
                culprit["locked_test"] = rec["n"]
            self.log("lesson", f"FALLO BLOQUEADO COMO TEST DE REGRESIÓN Nº {rec['n']} · autor: {rec['author']}")
            self._rebuild()
        return rec

    def informe(self) -> dict[str, Any]:
        with self.lock:
            st = self._state
            truth = self.world.truth()
            t_inc = {k: {kk: v.get(kk) for kk in ("type", "zone", "severity", "status", "t_open", "t_first_dispatch",
                                                   "t_first_attention", "t_resolved", "t_failed", "origin")}
                     for k, v in truth.get("incidents", {}).items()}
            result = {"session": st["session"], "t": st["t"], "clock": st["clock"], "metrics": st["metrics"],
                    "zone_names": {z["id"]: z["name"] for z in st["zones"]},
                    "incidents": st["incidents"], "truth_incidents": t_inc, "plans": st["plans"],
                    "approvals": [dict(v, action=k) for k, v in self.approvals.items()], "strikes": self.strikes,
                    "scoreboard": st.get("scoreboard"), "locked_tests": self.locked_tests, "decision_latency": self.decision_latency,
                    "calls": st["calls"]["calls"], "lessons": st["lessons"],
                    "log": [e for e in st["log"] if e.get("kind") in ("assumption_broken", "plan", "approval", "chaos", "lesson")],
                    "peak_density": truth.get("peak_density", {})}
            result.update(self.operators.report())
            result.update(evidence(self))
            return privacy.project(result, self.world.reports, self._report_meta, self.world.observe().zones)

    def public_report_ref(self, report_id: str | None) -> str | None:
        if report_id is None:
            return None
        with self.lock:
            if report_id not in self._report_public_refs:
                ref = secrets.token_urlsafe(24)
                self._report_public_refs[report_id] = ref
                self._report_caps[ref] = report_id
            return self._report_public_refs[report_id]

    def report_status(self, report_id: str, follow: bool = False) -> dict[str, Any]:
        """Todo lo que quien avisó necesita para seguir SU aviso. Si el incidente es reservado, solo lo neutro."""
        if follow:
            self._followers[report_id] = time.monotonic()
        st = self._state
        meta = self._report_meta.get(report_id) or {}
        ask = next(({"action_id": a, "question": w["question"]} for a, w in self.web_asks.items()
                    if w["report"] == report_id and a in self.comms._inflight), None)
        base = {"report_id": report_id, "safety": meta.get("safety"), "via": meta.get("via"), "understood": meta.get("understood"),
                "wristband": meta.get("wristband"), "ask": ask}
        if meta.get("reserved"):
            base.update(safety=None, ask=None, wristband=None)
        inc = next((i for i in st.get("incidents", []) if report_id in i.get("reports", [])), None)
        if inc is None:
            known = report_id in self._report_meta or any(r["id"] == report_id for r in st.get("reports", []))
            return dict(base, found=False, known=known, text="Aviso recibido. Mando todavía no lo ha clasificado." if known
                        else "No encuentro ese aviso en esta partida.")
        status = str(inc.get("status"))
        if inc.get("reserved") or inc.get("zone_masked"):
            return dict(base, safety=None, ask=None, found=True, reserved=True, incident=inc["id"], label="Incidente reservado", status=status,
                        status_text="Tu aviso está en el centro de control y se está atendiendo.", priority=None, priority_why=None,
                        reports_total=None, merged_with=0, doing="", explain="", resource=None, call=None, wristband=None)
        acts = [a for a in st.get("actions", []) if a.get("incident") == inc["id"] and a.get("kind") in ("dispatch", "ask", "request_external")]
        names = {r["id"]: r for r in st.get("resources", [])}
        doing = "; ".join(f"{a['kind']} {names.get(a.get('resource'), {}).get('name', '')} ({a['status']})".strip() for a in acts[-3:])
        calls = [c for c in self.comms.calls.values() if c.get("incident") == inc["id"] and c.get("kind") == "dispatch"]
        call = calls[-1] if calls else None
        call_view = None
        if call is not None:
            word = {"accept": "acepta", "reject": "rechaza", "no_answer": "no contesta"}.get(str(call.get("result")), "llamando")
            call_view = {"state": word, "stage": call.get("stage"), "eta_min": call.get("eta_min"), "real": bool(call.get("real"))}
        front = next((f for f in st.get("fronts", []) if f["id"] == inc["id"]), None)
        rid = next((r for r in (inc.get("assigned") or []) if r in names), None) or (call or {}).get("resource")
        res = names.get(rid) if rid else None
        resource = None
        if res is not None:
            kind_es = {"security": "seguridad", "medical": "equipo médico", "ambulance": "ambulancia", "tech": "técnicos",
                       "logistics": "logística", "volunteer": "voluntarios"}.get(str(res.get("kind")), "equipo")
            resource = {"name": res["name"], "role": (call or {}).get("title") or f"Jefe de {kind_es} · {res['name']}",
                        "status": res.get("status"), "eta_min": res.get("eta") or (front or {}).get("eta")}
        explain = inc.get("explain", "")
        return dict(base, found=True, reserved=False, incident=inc["id"], label=inc.get("label") or str(inc.get("type", "")).replace("_", " "),
                    priority=inc.get("priority"), priority_why=(explain.split(". ")[0][:160] if explain else None), status=status,
                    status_text=views.STATE_ES.get(status, status), reports_total=len(inc.get("reports", [])),
                    merged_with=max(0, len(inc.get("reports", [])) - 1), doing=doing, explain=explain,
                    zone_name=inc.get("zone_name"), resource=resource, call=call_view, why_waiting=(front or {}).get("why_waiting"))


class Duel:
    """Pantalla partida: MISMO caso, MISMA semilla y MISMOS golpes; a la izquierda la lista fija, a la derecha Mando.
    Un solo reloj mueve los dos mundos a la vez. Lo grave de Mando lo aprueba un operador simulado a los 2 minutos."""

    def __init__(self, case: dict[str, Any], *, seed: int | None = None, speed: float = 4.0, autoplay: bool = False,
                 threaded: bool = True, playbook: str = "auto", baseline: str = "reroute") -> None:
        if baseline not in ("reroute", "fixed"):
            raise ValueError("baseline debe ser reroute o fixed")
        self.baseline = baseline
        self.case, self.speed, self.running = case, max(0.1, min(64.0, float(speed))), autoplay
        self.left = Session(case, seed=seed, threaded=False, agent_kind="baseline-reroute" if baseline == "reroute" else "baseline")
        self.right = Session(case, seed=seed, threaded=False, playbook=playbook, auto_approve_min=2)
        self.sides = (self.left, self.right)
        self.version = 0
        self.lock = threading.RLock()
        self._json = "{}"
        self._stop, self._wake = threading.Event(), threading.Event()
        self._rebuild()
        if threaded:
            threading.Thread(target=self._loop, name="duelo-clock", daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.running and not self.done():
                self.tick()
                self._wake.wait(1.0 / self.speed)
            else:
                self._wake.wait(0.25)
            self._wake.clear()

    def done(self) -> bool:
        return all(s.world.done() for s in self.sides)

    def tick(self) -> None:
        with self.lock:
            for s in self.sides:
                s.tick()
            if self.done():
                self.running = False
            self._rebuild()

    def control(self, cmd: str, value: Any = None) -> None:
        if cmd in ("play", "pause"):
            self.running = cmd == "play"
        elif cmd == "toggle":
            self.running = not self.running
        elif cmd == "step":
            self.running = False
            self.tick()
        elif cmd == "speed":
            try:
                self.speed = max(0.1, min(64.0, float(value)))
            except TypeError:
                raise ValueError("velocidad ilegible")
        else:
            raise ValueError(cmd)
        self._wake.set()
        self._rebuild()

    def report(self, *args: Any, **kwargs: Any) -> None:
        with self.lock:
            for s in self.sides:
                s.report(*args, **kwargs)
            self._rebuild()

    def strike(self, effect: dict[str, Any], **kwargs: Any) -> None:
        with self.lock:
            for s in self.sides:
                s.strike(dict(effect), enforce_budget=False, **kwargs)
            self._rebuild()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        for s in self.sides:
            s.close()

    @staticmethod
    def _side(s: Session) -> dict[str, Any]:
        st, m = s.state(), s.state()["metrics"]
        peaks = s.world.truth().get("peak_density", {})
        peak_zone = max(peaks, key=lambda z: peaks[z].get("density", 0), default=None)
        return {"peak_zone": peak_zone, "n": 1,
                "peak_zone_name": next((z["name"] for z in st["zones"] if z["id"] == peak_zone), None),
                "reroutes": [{"from": z["id"], "to": z["flags"]["reroute_to"]} for z in st["zones"] if z["flags"].get("reroute_to")],
                "agent": s.agent_name, "kind": s.agent_kind, "zones": st["zones"], "resources": st["resources"],
                "incidents": [{k: i.get(k) for k in ("id", "label", "type", "zone", "priority", "severity", "status", "life_threat")}
                              for i in st["incidents"]],
                "log": [e for e in st["log"] if e.get("kind") in ("plan", "assumption_broken", "action", "chaos", "approval")][-5:],
                "plans": len(st["plans"]), "strikes": st["strikes"],
                "score": {"critical_failed": m["critical_failed"], "critical_total": m["critical_total"],
                          "peak_density": m["peak_density"], "minutes_over_5": m["minutes_over_5"],
                          "replans": m["replans"], "unsafe_actions": m["unsafe_actions"]}}

    def _rebuild(self) -> None:
        with self.lock:
            st = self.right.state()
            self.version += 1
            self._json = json.dumps({
                "version": self.version, "t": self.right.world.t, "clock": st["clock"], "weather": st["weather"],
                "session": {"case": self.case.get("id"), "title": self.case.get("meta", {}).get("title", ""), "seed": self.right.seed,
                            "running": self.running, "speed": self.speed, "done": self.done(),
                            "duration_min": self.case.get("duration_min"), "auto_approve_min": 2, "baseline": self.baseline},
                "left": self._side(self.left), "right": self._side(self.right)}, ensure_ascii=False, default=str)

    def state_json(self) -> str:
        return self._json


def _as_list(x: Any) -> list[dict[str, Any]]:
    if isinstance(x, dict):
        x = list(x.values())
    out = []
    for e in x or []:
        out.append(e if isinstance(e, dict) else e.to_dict() if hasattr(e, "to_dict") else {})
    return out


def _needs_approval_dict(a: dict[str, Any]) -> bool:
    kind = str(a.get("kind"))
    if str(a.get("status")) in ("awaiting_approval", "proposed"):
        return False
    return kind in {str(k) for k in ALWAYS_APPROVE} or (kind == "set_zone" and (a.get("params") or {}).get("state") == "closed")


def _norm_suggestion(s: Any) -> dict[str, Any] | None:
    if hasattr(s, "to_dict"):
        s = s.to_dict()
    elif hasattr(s, "__dict__") and not isinstance(s, dict):
        s = dict(s.__dict__)
    if not isinstance(s, dict):
        return None
    effect = s.get("effect") or s.get("strike") or s.get("event")
    if isinstance(effect, dict) and effect.get("kind") == "world" and "effect" in effect:
        effect = effect["effect"]
    if not isinstance(effect, dict) or effect.get("kind") not in EFFECT_KINDS:
        return None
    damage = next((s[k] for k in ("damage", "estimated_damage", "expected_damage", "harm", "score", "delta") if s.get(k) is not None), None)
    return {"label": str(s.get("label") or s.get("title") or s.get("name") or effect["kind"]),
            "why": str(s.get("why") or s.get("reason") or s.get("rationale") or ""), "damage": damage,
            "damage_unit": s.get("damage_unit") or s.get("unit"), "effect": effect,
            "extra": {k: v for k, v in s.items() if k in ("n", "samples", "baseline", "after", "cost", "target", "assumption")}}


# ---------------------------------------------------------------- curva de aprendizaje (si el banco la dejó)

def load_curve() -> dict[str, Any]:
    out: dict[str, Any] = {"available": False}
    for name in ("curve.json", "summary.json"):
        p = HARNESS_OUT / name
        if p.exists():
            try:
                out[name.split(".")[0]] = json.loads(p.read_text(encoding="utf-8"))
                out["available"] = True
            except ValueError:
                out[name + "_error"] = "JSON ilegible"
    return out


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no envía nada: solo pregunta al sistema qué interfaz usaría
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------- aplicación

def create_app(case_id: str = "demo-gates", *, seed: int | None = None, speed: float = 1.0, comms_mode: str = "sim",
               autoplay: bool = False, threaded: bool = True, secret: str | None = None, port: int = 8000,
               playbook: str = "auto", local_params: bool = True) -> FastAPI:
    import contextlib

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        async with contextlib.AsyncExitStack() as stack:
            if app.state.mcp is not None:   # el gestor de sesiones del servidor MCP vive lo que viva la app
                await stack.enter_async_context(app.state.mcp.session_manager.run())
            try:
                yield
            finally:
                if app.state.telegram is not None:
                    app.state.telegram.stop()
                app.state.chat.stop()
                app.state.simulacro.close()
                app.state.session.close()
                app.state.tg_roster.close()

    app = FastAPI(title="Mando", docs_url=None, redoc_url=None, lifespan=lifespan)
    configured()  # configuración inválida: fallar al arrancar, no a media operación
    app.add_middleware(SecurityGuard)
    app.state.port = port
    app.state.mcp = app.state.telegram = None
    Session.callback_url = f"http://127.0.0.1:{port}"
    app.state.session = Session(load_case(case_id), seed=seed, speed=speed, comms_mode=comms_mode,
                                autoplay=autoplay, threaded=threaded, playbook=playbook, local_params=local_params)
    app.state.tg_roster = tg_roster.TelegramRoster()
    app.state.threaded = threaded
    app.state.duel = None
    from .db import History, Recorder
    app.state.history = History()

    def record(session: Session) -> None:
        session.recorder = Recorder(on_warning=lambda message: session.log("database", message))
        session.recorder.offer(session.state())

    record(app.state.session)

    def S() -> Session:
        return app.state.session

    from .operator_audit import OperatorAudit
    app.add_middleware(OperatorAudit, get_session=S)

    def D() -> Duel:
        if app.state.duel is None:
            app.state.duel = Duel(load_case("demo-gates"), threaded=app.state.threaded, playbook=playbook, baseline="reroute")
        return app.state.duel

    # ---- entrada común de avisos y golpes: la usan /api/report, el bot de Telegram, el servidor MCP y los workflows
    delegated = intake.DelegatedIntake(lambda: S().comms.callback_url, lambda *a, **k: S().log(*a, **k))
    app.state.intake = delegated

    def submit_report(channel: str, text: str, zone: str | None = None, *, delegate: bool = True, **kw: Any) -> dict[str, Any]:
        """Mismo camino para todos los canales. Con `HR_HOOK_INTAKE`, el texto libre lo ENTIENDE primero HappyRobot (bloquea
        como mucho `HR_INTAKE_TIMEOUT_S`: no llamar desde el bucle asyncio); si no contesta, entra con el parser propio."""
        session = S()
        ev = None
        if delegate and text and not kw.get("preset") and delegated.hook:
            real = kw.get("via") or ("telegram" if str(kw.get("source", "")).startswith("telegram:") else "web")
            ev, why = delegated.understand(text=text, channel=real, source=str(kw.get("source") or ""), zone_hint=zone,
                                           lang=str(kw.get("lang") or "es"))
            if ev is None:
                S().log("report", f"Entendimiento delegado no disponible ({why}): este aviso se entiende en local")
        if S() is not session or session._stop.is_set():
            return {'ok': False, 'stale': True, 'report_id': None}
        if ev is not None:
            sr = intake.structured_report(ev, {z["id"]: z["name"] for z in S().festival["zones"]})
            kw.update(understood="happyrobot", extracted=sr["extracted"], where=kw.get("where") or sr["where"],
                      preset_hint=sr["preset_hint"])
            if sr["extracted"].get("location") and _plain(sr["extracted"]["location"]) not in _plain(text):
                text = f"{text} Lugar: {sr['extracted']['location']}."[:400]
        if app.state.duel is not None:
            app.state.duel.report(channel, text, zone, **kw)
        out = session.report(channel, text, zone, **kw)
        delegated.remember(ev, out["report_id"])
        return out

    def submit_strike(preset_key: str, *, author: str = "", origin: str = "jury", extra: dict[str, Any] | None = None, client_id: str | None = None) -> dict[str, Any]:
        preset = STRIKE_PRESETS.get(preset_key)
        if preset is None:
            raise ValueError("golpe desconocido")
        effect = dict(preset["effect"], **(extra or {}))
        item = S().strike(effect, origin=origin, label=preset["label"], author=author[:40], client_id=client_id or author)
        if app.state.duel is not None:
            app.state.duel.strike(effect, origin=origin, label=preset["label"])
        return {"strike": item, "left": S().jury_left(client_id or author), "global_left": S().jury_left()}

    app.state.submit_report = submit_report

    def understand(text: str, channel: str, zone_hint: str | None, lang: str) -> dict[str, Any] | None:
        """Lo que `IntakeSession` usa para ENTENDER un texto cuando hay workflow de texto en HappyRobot; None = en local."""
        ev, _ = delegated.understand(text=text, channel=channel, source="chat", zone_hint=zone_hint, lang=lang)
        return intake.structured_report(ev, {z["id"]: z["name"] for z in S().festival["zones"]})["extracted"] if ev else None

    from .chat import ChatHub
    hub = app.state.chat = ChatHub(S, submit_report, understand=lambda *a: understand(*a) if delegated.hook else None,
                                   wristband=intake.wristband)
    Session.chat_router = staticmethod(hub.route_ask)

    def links() -> dict[str, Any]:
        base = public_base() or f"http://{lan_ip()}:{app.state.port}"
        bot = (app.state.telegram.username if app.state.telegram is not None and app.state.telegram.username
               else os.environ.get("TELEGRAM_BOT_USERNAME", "")).lstrip("@")
        urls = hr_config.workflow_urls()
        return {"webcall_public": hr_config.safe_url(urls['voice']), "chat": hr_config.safe_url(urls['chat']), "telegram": f"https://t.me/{bot}" if bot else None,
                "jurado": base + "/jurado", "asistente": base + "/asistente",
                "email": os.environ.get("HR_INTAKE_EMAIL") or None, "sms": '/canal/sms' if os.environ.get("HR_SMS_NUMBER") else None}

    def extra_state() -> dict[str, Any]:
        from .presentation import channels
        tg = app.state.telegram
        workflows = S().comms.workflow_status.view()
        workflows['intake'] = delegated.workflow_status.view()['intake']
        workflows['intake']['configured'] = bool(delegated.hook)
        mirror = S().tg_mirror.view()
        bot = tg.view() if tg is not None else {"status": "off"}
        # Contrato compartido de despacho en `telegram` cuando hay espejo; si no, el bot (centro, /asistente).
        return {"telegram": mirror if mirror is not None else bot, "telegram_bot": bot,
                "links": links(), "happyrobot": workflows,
                "presentation": channels(S(), tg, delegated),
                "intake": {"delegated": bool(delegated.hook), "timeout_s": delegated.timeout_s, **delegated.stats}}

    Session.extra_state = staticmethod(extra_state)

    def replace_session(new: Session) -> None:
        old = S()
        old.close()
        app.state.session = new
        record(new)
        delegated.reset()
        hub._sync()
        if app.state.telegram is not None:
            app.state.telegram._sync_session()
        app.state.tg_roster.clear_assignments()
        new._rebuild()

    def operator(request: Request) -> None:
        """Aprobar, mover el reloj, tomar una llamada o bloquear un test es cosa del puesto de control, no de un móvil
        del público: solo desde esta máquina, o con `MANDO_OPERATOR_TOKEN` en la cabecera `X-Mando-Operator`."""
        require_operator(request)

    def token() -> str:
        return secret if secret is not None else shared_secret()

    def check_token(request: Request) -> None:
        expected = token()
        if not expected:
            raise HTTPException(503, "Secreto de webhooks sin configurar (HR_SECRET)")
        got = request.headers.get("X-Mando-Token") or request.headers.get("X-HR-Secret") or ""
        if not hmac.compare_digest(got.encode(), expected.encode()):
            raise HTTPException(401, "Token incorrecto")

    from . import cerebro_tools
    cerebro_tools.mount(app, S, check_token, operator)

    _FIELD = re.compile(r'"(action_id|type|message|result|resultado|eta_min|hr_run_id|hr_session_id|reason|call_status|report_ref|'
                        r'channel|stage|reply_to|event_id|field|value)"\s*:\s*"((?:[^"\\\n]|\\.)*)"')

    async def hr_body(request: Request) -> dict[str, Any]:
        """Cuerpo de un webhook de la plataforma. RIESGO conocido (PLATAFORMA_REAL §2): si no escapa comillas y saltos de
        línea al sustituir variables, un `transcript` con comillas llega como JSON ROTO. No se devuelve 500: se recuperan
        los campos cortos con una expresión regular, se deja escrito en el registro y se sigue."""
        raw = await request.body()
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
        text = raw.decode("utf-8", "replace")
        got: dict[str, Any] = {}
        for k, v in _FIELD.findall(text):
            got.setdefault(k, v)   # gana la primera aparición: los campos cortos van ANTES que el texto largo
        if not got.get("type") and not got.get("message"):
            raise HTTPException(400, "JSON inválido")
        got["recovered"] = True
        S().log("action", f"Webhook de HappyRobot con JSON ROTO ({len(raw)} bytes): recuperados {', '.join(k for k in got if k != 'recovered')}. "
                          "Quitar `transcript` del cuerpo del nodo o escaparlo en la plataforma")
        return got

    _CHAT_TYPES = ("public_report", "public_report_update", "report_status_query")

    def check_hr(request: Request) -> str:
        """"hr" con `HR_SECRET`; "chat" con `HR_CHAT_TOKEN` (el del widget de chat, que es PÚBLICO en el navegador: solo
        sirve para avisos y consultas de estado, nunca para resultados de llamadas ni aprobaciones)."""
        got = (request.headers.get("X-Mando-Token") or request.headers.get("X-HR-Secret") or "").encode()
        chat_token = os.environ.get("HR_CHAT_TOKEN", "")
        if chat_token and chat_token != token() and hmac.compare_digest(got, chat_token.encode()):
            return "chat"
        check_token(request)
        return "hr"

    async def body(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "JSON inválido")
        if not isinstance(data, dict):
            raise HTTPException(400, "Se esperaba un objeto JSON")
        if "text" in data and not isinstance(data["text"], str):
            raise HTTPException(422, "text debe ser texto")
        for key in ("zone", "zone_hint", "preset"):
            if data.get(key) is not None and not isinstance(data[key], str):
                raise HTTPException(422, f"{key} debe ser texto")
        for key in ("ok", "approve", "autoplay", "takeover"):
            if key in data and type(data[key]) is not bool:
                raise HTTPException(422, f"{key} debe ser un booleano JSON")
        return data

    # ---- páginas
    # Interfaz de supervisión: Sala. Público / jurado: /asistente y /jurado.
    # Las pantallas viejas viven en archivo/motor/server/static/; las rutas redirigen aquí.
    pages = {"/": "sala.html", "/sala": "sala.html", "/jurado": "jurado.html"}
    for route, fname in pages.items():
        app.add_api_route(route, (lambda f=fname: FileResponse(STATIC / f, headers={"Cache-Control": "no-store"})),
                          methods=["GET"], include_in_schema=False)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def _archived_page() -> HTMLResponse:
        return HTMLResponse(
            '<!doctype html><meta charset="utf-8"><title>MANDO</title>'
            '<p>Pantalla archivada. <a href="/">Sala de control</a>.</p>',
            headers={"Cache-Control": "no-store"})

    for _old in ("/centro", "/clasico", "/curva", "/caos", "/memoria", "/informe"):
        def _redir(_name=_old.strip("/")) -> HTMLResponse:
            return _archived_page()
        _redir.__name__ = f"old_{_old.strip('/')}"
        app.add_api_route(_old, _redir, methods=["GET"], include_in_schema=False)

    @app.get("/duelo", include_in_schema=False)
    def duel_page() -> HTMLResponse:
        D()  # la API /api/duel/* sigue viva; GET /duelo no carga el HTML archivado
        return _archived_page()

    @app.get("/asistente", include_in_schema=False)
    def asistente_page() -> FileResponse:
        """La app móvil del asistente (la escribe otro agente). Mientras no exista, se sirve la página del jurado."""
        f = STATIC / "asistente.html"
        return FileResponse(f if f.exists() else STATIC / "jurado.html", headers={"Cache-Control": "no-store"})

    @app.get('/canal/sms')
    def sms_link():
        number = os.environ.get('HR_SMS_NUMBER', '')
        if not re.fullmatch(r'\+[1-9]\d{7,14}', number):
            raise HTTPException(404, 'SMS sin configurar')
        return Response(status_code=307, headers={'Location': 'sms:' + number, 'Cache-Control': 'no-store'})

    @app.get("/llamada/{call_id}", include_in_schema=False)
    def llamada_page(call_id: str) -> FileResponse:
        return FileResponse(STATIC / "llamada.html", headers={"Cache-Control": "no-store"})

    @app.get("/qr")
    def qr(request: Request, path: str = "/asistente") -> Response:
        import io

        import segno
        if not re.fullmatch(r"/[A-Za-z0-9_\-/#]{0,80}", path):
            raise HTTPException(400, "Ruta no válida")
        base = (os.environ.get("MANDO_PUBLIC_URL") or f"http://{lan_ip()}:{request.url.port or app.state.port}").rstrip("/")
        if path == "/telegram" and links()["telegram"]:
            base, path = links()["telegram"], ""
        elif path == "/voz" and links()["webcall_public"]:
            base, path = links()["webcall_public"], ""
        buf = io.BytesIO()
        segno.make(base + path, error="m").save(buf, kind="svg", scale=8, border=2, dark="#0b1016", light="#ffffff", xmldecl=False)
        return Response(buf.getvalue(), media_type="image/svg+xml", headers={"X-Jurado-Url": base + path, "Cache-Control": "no-store"})

    # ---- estado
    @app.get("/api/state")
    def state() -> Response:
        return Response(S().state_json(), media_type="application/json")

    @app.get("/api/stream")
    async def stream(limit: int = 0) -> StreamingResponse:
        async def gen():
            last, sent, idle = -1, 0, 0.0
            while True:
                s = S()
                revision = (s.session_id, s.version)
                if revision != last:
                    last, idle = revision, 0.0
                    yield f"event: state\ndata: {s.state_json()}\n\n"
                    sent += 1
                    if limit and sent >= limit:
                        return
                await asyncio.sleep(0.1)
                idle += 0.1
                if idle >= 10:
                    idle = 0.0
                    yield ": vivo\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/cases")
    def cases() -> list[dict[str, Any]]:
        return list_cases()

    @app.get("/api/festival")
    def festival() -> dict[str, Any]:
        f = load_festival()
        return {"zones": [{k: z.get(k) for k in ("id", "name", "kind", "area_m2", "capacity")} for z in f["zones"]],
                "edges": f["edges"], "jury_incidents": {k: v["label"] for k, v in JURY_INCIDENTS.items()},
                "strike_presets": {k: v["label"] for k, v in STRIKE_PRESETS.items()}}

    @app.get("/api/version")
    def version() -> dict[str, Any]:
        """Versión del proyecto (la de `motor/server/pyproject.toml`): la pinta el chip de la Sala de control."""
        return {"version": project_version()}

    @app.post("/api/session")
    async def new_session(request: Request) -> dict[str, Any]:
        operator(request)
        d = await body(request)
        old = S()
        try:
            case = d["case"] if isinstance(d.get("case"), dict) else load_case(str(d.get("case_id") or d.get("case") or "demo-gates"))
        except KeyError:
            raise HTTPException(404, "Caso no encontrado")
        try:
            new = Session(case, seed=d.get("seed"), speed=float(d.get("speed", old.speed)),
                          comms_mode=str(d.get("comms", old.comms_mode)), autoplay=bool(d.get("autoplay", False)),
                          threaded=app.state.threaded, playbook=str(d.get("playbook", old.playbook_choice)))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"El caso no se puede cargar: {e}")
        replace_session(new)
        return {"ok": True, "session": new.state()["session"]}

    @app.post("/api/control")
    async def control(request: Request) -> dict[str, Any]:
        operator(request)
        d = await body(request)
        cmd = str(d.get("cmd") or d.get("action") or "")
        s = S()
        if cmd == "reset":
            new = Session(s.case, seed=s.seed, speed=s.speed, comms_mode=s.comms_mode, threaded=app.state.threaded,
                          playbook=s.playbook_choice, local_params=s.local_params)
            replace_session(new)
            return {"ok": True, "session": new.state()["session"]}
        if cmd == 'key_moment':
            from .ensayo import prepare_key_moment
            new = Session(load_case(os.environ.get('MANDO_DEMO_CASE', 'demo-1')), speed=s.speed,
                          comms_mode='sim', threaded=False, playbook='seed', local_params=False)
            try:
                moment = await asyncio.to_thread(prepare_key_moment, new)
            except ValueError as exc:
                new.close()
                raise HTTPException(400, str(exc))
            replace_session(new)
            if app.state.threaded:
                new._forecast = ForecastService(new)
                new._thread = threading.Thread(target=new._loop, name='mando-clock', daemon=True)
                new._thread.start()
            return {'ok': True, 'session': new.state()['session'], 'moment': moment}
        try:
            n = int(d.get("n", 1)) if cmd == "step" else 1
            for _ in range(max(1, min(n, 600))):
                s.control(cmd, d.get("value"))
        except ValueError:  # solo la orden desconocida o un valor ilegible; un fallo interno no se disfraza de 400
            raise HTTPException(400, "Orden desconocida: play | pause | toggle | step | speed | reset")
        return {"ok": True, "session": s.state()["session"], "t": s.world.t}

    # ---- personas
    @app.post("/api/report")
    async def report(request: Request) -> dict[str, Any]:
        d = await body(request)
        if not (d.get("text") or d.get("preset")):
            raise HTTPException(400, "Falta el texto del aviso")
        if not operator_authenticated(request):
            d.update(channel='whatsapp', source='asistente', wristband=None)
        source = str(d.get("source") or "jurado")[:40]
        if source.startswith("telegram:"):
            source = "jurado"   # ese prefijo es del bot: desde la web no se suplanta
        args = (str(d.get("channel") or "whatsapp"), str(d.get("text") or "")[:400], d.get("zone"))
        kw = {"preset": d.get("preset"), "source": source, "lang": str(d.get("lang") or "es"),
              "wristband": str(d.get("wristband") or "")[:16] or None}
        session = S()
        out = await asyncio.to_thread(submit_report, *args, **kw)
        if not operator_authenticated(request):
            rid = out.get("report_id")
            out["report_id"] = session.public_report_ref(out.get("report_id"))
            out["report_refs"] = {out["report_id"]: rid} if rid else {}
        return out

    def resolve_report(session: Session, ref: str, request: Request) -> str:
        rid = session._report_caps.get(ref)
        if rid is None and operator_authenticated(request):
            rid = ref
        if rid is None:
            raise HTTPException(404, "Ese aviso no existe")
        return rid

    @app.get("/api/report/{report_id}")
    def report_status(report_id: str, request: Request) -> dict[str, Any]:
        session = S()
        rid = resolve_report(session, report_id, request)
        return dict(session.report_status(rid, follow=True), report_id=report_id)

    @app.post("/api/report/{report_id}/answer")
    async def report_answer(report_id: str, request: Request) -> dict[str, Any]:
        """Quien avisó contesta a la pregunta que le ha hecho Mando: vuelve como respuesta de comunicaciones."""
        d = await body(request)
        session = S()
        rid = resolve_report(session, report_id, request)
        text = str(d.get("text") or "").strip()[:400]
        if not text:
            raise HTTPException(400, "Falta la respuesta")
        if not session.answer_report(rid, text):
            raise HTTPException(409, "Ese aviso no tiene ninguna pregunta pendiente")
        return {"ok": True}

    # ---- agente de recogida: la persona habla y el agente pregunta lo que falta
    @app.post("/api/chat")
    async def chat_turn(request: Request) -> dict[str, Any]:
        d = await body(request)
        if str(d.get("session_id") or "").startswith("tg-"):
            raise HTTPException(403, "Sesión reservada para Telegram")
        text = str(d.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "Falta el texto")
        if not operator_authenticated(request):
            d.update(channel='web', source=None, pulsera=None)
        zones = {z["id"] for z in S().festival["zones"]}
        session = S()
        out = await asyncio.to_thread(hub.turn, str(d.get("session_id") or "")[:40] or None, text,
                                       channel=str(d.get("channel") or "web")[:20], lang=str(d.get("lang") or "es")[:5],
                                       zone_hint=d.get("zone_hint") if d.get("zone_hint") in zones else None,
                                       pulsera=str(d.get("pulsera") or "")[:16] or None,
                                       source=str(d.get("source") or "")[:40] or None, preset=d.get("preset"),
                                       client_id=str(d.get("client_id") or "")[:80] or None)
        if not operator_authenticated(request):
            ids = set(out.get("reports", [])) | ({out["report_id"]} if out.get("report_id") else set())
            out["report_refs"] = {session.public_report_ref(r): r for r in ids}
            out["report_id"] = session.public_report_ref(out.get("report_id"))
            out["reports"] = [session.public_report_ref(r) for r in out.get("reports", [])]
        return out

    @app.get("/api/chat/{session_id}/events")
    async def chat_events(session_id: str, after: int = 0, limit: int = 0) -> StreamingResponse:
        """SSE con lo que Mando le cuenta a ESA persona: preguntas (`ask`) y cambios de estado de su incidente (`status`)."""
        if session_id.startswith("tg-"):
            raise HTTPException(403, "Sesión reservada para Telegram")
        if hub.events_after(session_id, after) is None:
            raise HTTPException(404, "Esa conversación no existe")

        async def gen():
            seq, sent, idle = after, 0, 0.0
            while True:
                for e in hub.events_after(session_id, seq) or []:
                    seq = e["seq"]
                    yield f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                    sent += 1
                    if limit and sent >= limit:
                        return
                await asyncio.sleep(0.3)
                idle += 0.3
                if idle >= 10:
                    idle = 0.0
                    yield ": vivo\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/chats")
    def chats_overview(request: Request) -> dict[str, Any]:
        """SOLO LECTURA y solo operador: las conversaciones vivas de los canales, para el panel «CHAT · AGENTE HR»
        de la Sala de control. No permite escribir ni continuar ninguna conversación. Nunca salen el identificador
        secreto de la conversación ni el contenido de un aviso reservado (se sustituye por su rótulo)."""
        operator(request)
        s = S()
        texts = {r.id: r.text for r in s.world.reports}
        with hub._lock:
            rooms = [c for c in hub.chats.values() if c.get("mando_session") == s.session_id]
        out = []
        for c in rooms:
            ids = list(c.get("reports") or [])
            reserved = bool(c.get("reserved")) or any((s._report_meta.get(r) or {}).get("reserved") for r in ids)
            msgs = [{"who": "persona", "text": "(aviso reservado)" if reserved else texts.get(r, "")} for r in ids[-3:]]
            msgs += [{"who": "mando", "text": "(conversación reservada)" if reserved else str(e.get("text") or "")}
                     for e in list(c.get("events") or [])[-3:]]
            instruction = c.get("instruction") if isinstance(c.get("instruction"), dict) else None
            out.append({"n": c.get("n"), "channel": str(c.get("channel") or "web"), "lang": str(c.get("lang") or "es"),
                        "reports": len(ids), "done": bool(c.get("done")), "reserved": reserved,
                        "instruction": None if reserved or not instruction else instruction.get("title"),
                        "messages": [m for m in msgs if m["text"]]})
        out.sort(key=lambda x: x["n"] or 0)
        return privacy.scrub({"chats": out[-8:], "n": len(out)})

    @app.get("/api/pulsera/{code}")
    def pulsera(code: str) -> dict[str, Any]:
        prof = intake.wristband(code)
        if prof is None:
            raise HTTPException(404, "Pulsera desconocida")
        return dict(prof, demo=True, note="Perfil inventado para la demo. La pulsera no da ubicación.")

    @app.post("/api/strike")
    async def strike(request: Request) -> dict[str, Any]:
        d = await body(request)
        preset = STRIKE_PRESETS.get(str(d.get("preset") or ""))
        gate_choice = d.get("preset") == "close_gate" and d.get("zone") in ("gate_a", "gate_b", "gate_c")
        if (preset is None or (d.get("zone") is not None and not gate_choice)
                or any(d.get(k) is not None for k in ("resource", "channel", "n"))):
            operator(request)  # el público solo lanza el efecto predefinido, sin ampliarlo
        effect = dict(preset["effect"]) if preset else d.get("effect")
        if not isinstance(effect, dict):
            raise HTTPException(400, "Falta «effect» o «preset»")
        for k in ("zone", "resource", "channel", "n"):
            if preset and d.get(k) is not None:
                effect[k] = d[k]
        origin, label = str(d.get("origin") or "jury"), str(d.get("label") or (preset or {}).get("label") or "")
        if origin != "jury":
            operator(request)  # la consola de Caos es del equipo; el público solo tiene sus 3 golpes
        try:
            item = S().strike(effect, origin=origin, label=label, author=str(d.get("author") or "")[:40],
                              client_id=str(d.get("client_id") or "anonymous")[:80])
        except ValueError as e:
            raise HTTPException(400, str(e))
        except PermissionError as e:
            raise HTTPException(429, str(e))
        if app.state.duel is not None:
            app.state.duel.strike(effect, origin=origin, label=label)
        left = S().jury_left(item.get("client_id"))
        item = next(k for k in S().state()["strikes"] if k["n"] == item["n"])
        return {"ok": True, "strike": item, "left": left, "global_left": S().jury_left(), "strike_id": item["n"], "follow": f"/api/strike/{item['n']}",
                "broke": item.get("broke"), "new_plan": item.get("new_plan")}

    @app.get("/api/strike/{n}")
    def strike_result(n: int) -> dict[str, Any]:
        """Qué hizo ese golpe: el supuesto que se rompió tras él (si alguno) y el plan que nació. Se rellena en los ticks siguientes."""
        k = next((k for k in S().state()["strikes"] if k.get("n") == n), None)
        if k is None:
            raise HTTPException(404, "Ese golpe no existe en esta partida")
        return dict(k, ok=True, now=S().world.t)

    # ---- «¿y si…?»: ensayo de una alternativa en el gemelo. NUNCA toca el mundo real.
    @app.post("/api/whatif")
    async def whatif_run(request: Request) -> dict[str, Any]:
        operator(request)
        d = await body(request)
        s = S()
        if not hasattr(s.world, "twin"):
            raise HTTPException(501, "Este mundo no ofrece gemelo")
        try:
            with s.lock:
                return dict(whatif.rehearse(s.world, d, {z["id"]: z["name"] for z in s.festival["zones"]}), ok=True)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/whatif/order")
    async def whatif_order(request: Request) -> dict[str, Any]:
        """«Ordenar esto»: la alternativa ensayada entra como corrección del operador (acción manual + veto + lección candidata)."""
        operator(request)
        d = await body(request)
        try:
            return S().operators.correction(d.get("action") if isinstance(d.get("action"), dict) else d,
                                            str(d.get("note") or "")[:160], identity(request), d.get("decision_id"))
        except ValueError as e:
            raise HTTPException(400, str(e))

    # ---- memoria día 1 → día 2
    @app.get("/api/memoria")
    def memoria_view() -> dict[str, Any]:
        out = memoria.overview(S().operator_orders)
        led = getattr(S(), "ledger", None)
        if led is not None:
            out["cerebro_lecciones"] = led.list_lecciones()
        return out

    @app.get("/api/ledger/stats")
    def ledger_stats(request: Request) -> dict[str, Any]:
        """Totales del ledger local (auditoría de llamadas). Solo operador."""
        operator(request)
        led = getattr(S(), "ledger", None)
        if led is None:
            from .ledger import open_ledger
            return open_ledger().stats()
        return led.stats()

    @app.post("/api/ledger/export")
    def ledger_export(request: Request) -> dict[str, Any]:
        """Mezcla episodios del ledger en memory.day1.json (contactos). Solo operador."""
        operator(request)
        led = getattr(S(), "ledger", None)
        if led is None:
            from .ledger import open_ledger
            led = open_ledger()
        real_only = request.query_params.get("real_only", "").lower() in ("1", "true", "yes")
        merge = request.query_params.get("merge", "1").lower() not in ("0", "false", "no")
        return led.export_to_memory(real_only=real_only, merge=merge)

    @app.post("/api/memoria/decide")
    async def memoria_decide(request: Request) -> dict[str, Any]:
        operator(request)
        d = await body(request)
        if d.get("approve") is None or not d.get("id"):
            raise HTTPException(400, "Hacen falta «id» y «approve»")
        try:
            return memoria.decide(str(d["id"]), bool(d["approve"]), str(d.get("by") or "operador-1"))
        except KeyError:
            raise HTTPException(404, "Esa propuesta no existe")

    @app.get("/api/jury")
    def jury_info(client_id: str | None = None) -> dict[str, Any]:
        b = S().state().get("scoreboard", {})
        return {"left": S().jury_left(client_id), "global_left": S().jury_left(), "budget": JURY_BUDGET, "jury": b.get("jury"), "mando": b.get("mando")}

    # ---- el test con tu nombre
    @app.get("/api/regression")
    def regression_list() -> list[dict[str, Any]]:
        return regression_live.list_tests()

    @app.post("/api/regression/lock")
    async def regression_lock(request: Request) -> dict[str, Any]:
        operator(request)
        d = await body(request)
        if "simulacro_index" in d:
            if type(d["simulacro_index"]) is not int:
                raise HTTPException(422, "simulacro_index debe ser entero")
            try:
                return app.state.simulacro.lock_test(d["simulacro_index"], str(d.get("author") or "operador"), str(d.get("note") or ""))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        return {"ok": True, "test": S().lock_as_test(str(d.get("author") or ""), str(d.get("note") or ""))}

    @app.post("/api/regression/run")
    async def regression_run(request: Request) -> dict[str, Any]:
        operator(request)
        d = await body(request)
        try:
            rec = regression_live.load(int(d.get("n", 0)))
        except (KeyError, ValueError, TypeError):
            raise HTTPException(404, "Ese test no existe")
        if rec.get("simulacro"):
            import asyncio
            from .simulacro import run_locked
            try:
                return await asyncio.to_thread(run_locked, rec)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        new = Session(rec["case"], seed=rec["seed"], speed=float(d.get("speed", 16)), comms_mode="sim", autoplay=True,
                      threaded=app.state.threaded, playbook=str(d.get("playbook") or rec.get("playbook") or "auto"),
                      replay={"n": rec["n"], "author": rec["author"], "inputs": rec["inputs"], "before": rec["before"]})
        replace_session(new)
        return {"ok": True, "n": rec["n"], "session": new.state()["session"]}

    # ---- pantalla partida
    @app.get("/api/duel/state")
    def duel_state() -> Response:
        return Response(D().state_json(), media_type="application/json")

    @app.get("/api/duel/stream")
    async def duel_stream(limit: int = 0) -> StreamingResponse:
        async def gen():
            last, sent = -1, 0
            while True:
                d = D()
                if d.version != last:
                    last = d.version
                    yield f"event: state\ndata: {d.state_json()}\n\n"
                    sent += 1
                    if limit and sent >= limit:
                        return
                await asyncio.sleep(0.1)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/duel/session")
    async def duel_session(request: Request) -> dict[str, Any]:
        operator(request)
        d = await body(request)
        if d.get("baseline", "reroute") not in ("reroute", "fixed"):
            raise HTTPException(422, "baseline debe ser reroute o fixed")
        try:
            case = d["case"] if isinstance(d.get("case"), dict) else load_case(str(d.get("case_id") or "demo-gates"))
        except KeyError:
            raise HTTPException(404, "Caso no encontrado")
        if app.state.duel is not None:
            app.state.duel.close()
        app.state.duel = Duel(case, seed=d.get("seed"), speed=float(d.get("speed", 4)), autoplay=bool(d.get("autoplay", False)),
                              threaded=app.state.threaded, playbook=str(d.get("playbook") or playbook), baseline=str(d.get("baseline") or "reroute"))
        return {"ok": True}

    @app.post("/api/duel/control")
    async def duel_control(request: Request) -> dict[str, Any]:
        operator(request)
        d = await body(request)
        cmd = str(d.get("cmd") or "")
        duel = D()
        if cmd == "reset":
            duel.close()
            app.state.duel = Duel(duel.case, seed=duel.right.seed, speed=duel.speed, threaded=app.state.threaded, playbook=playbook, baseline=duel.baseline)
            return {"ok": True}
        if cmd == "close":
            duel.close()
            app.state.duel = None
            return {"ok": True}
        try:
            for _ in range(max(1, min(int(d.get("n", 1)) if cmd == "step" else 1, 600))):
                duel.control(cmd, d.get("value"))
        except ValueError:
            raise HTTPException(400, "Orden desconocida")
        return {"ok": True, "t": duel.right.world.t}

    # ---- llamada web: enlace secreto para quien hace de jefe de equipo. El token se pide al descolgar y solo va ahí.
    def _hr(fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except KeyError:
            raise HTTPException(404, "Esa llamada no existe")
        except Exception as e:
            raise HTTPException(502, f"La plataforma no ha contestado ({type(e).__name__})")

    @app.get("/api/webcalls")
    def webcalls(request: Request) -> list[dict[str, Any]]:
        operator(request)
        return S().comms.pending_webcalls()

    @app.get("/api/webcall/{call_id}")
    def webcall_info(call_id: str) -> dict[str, Any]:
        c = S().comms
        wc = c.webcalls.get(call_id)
        if wc is None:
            raise HTTPException(404, "Esa llamada no existe")
        call = c.calls.get(wc["action_id"], {})
        return {"title": wc["title"], "order_text": wc["order_text"], "answered": wc["answered"], "result": call.get("result"),
                "over": wc["action_id"] in c._closed, "transcript": call.get("transcript", []), "signal": call.get("signal")}

    @app.post("/api/webcall/{call_id}/answer")
    def webcall_answer(call_id: str) -> dict[str, Any]:
        return _hr(S().comms.answer_webcall, call_id)

    @app.post("/api/webcall/{call_id}/mock_answer")
    async def webcall_mock_answer(call_id: str, request: Request) -> dict[str, Any]:
        """Solo contra `mock_happyrobot` (API en 127.0.0.1): lo que la persona diría por el micrófono."""
        import httpx
        c = S().comms
        wc = c.webcalls.get(call_id)
        if wc is None or not re.match(r"https?://(127\.0\.0\.1|localhost)[:/]", c.api_base):
            raise HTTPException(404, "Solo disponible con el HappyRobot de mentira")
        run_id = c.calls.get(wc["action_id"], {}).get("hr_run_id")
        d = await body(request)
        root = c.api_base.split("/api/")[0]
        await asyncio.to_thread(httpx.post, f"{root}/mock/answer/{run_id}", json={"result": str(d.get("result") or "accept")}, timeout=5)
        return {"ok": True}

    @app.post("/api/call/{action_id}/token")
    async def call_token(action_id: str, request: Request) -> dict[str, Any]:
        """ESCUCHAR o TOMAR una llamada viva desde el puesto de control (`should_takeover`)."""
        operator(request)
        d = await body(request)
        s, who = S(), identity(request)
        key = s.operators.reserve_call(action_id, who) if d.get("takeover") else None
        try:
            return await asyncio.to_thread(_hr, s.comms.takeover_token, action_id, bool(d.get("takeover")))
        except Exception:
            if key:
                with s.lock:
                    s.operators.decisions.pop(key, None)
                    s.operators.event(who, 'no se pudo tomar la llamada', action_id)
                    s._rebuild()
            raise

    @app.post("/api/call/{action_id}/signal")
    async def call_signal(action_id: str, request: Request) -> dict[str, Any]:
        operator(request)
        d = await body(request)
        return {"ok": await asyncio.to_thread(S().comms.change_orders, action_id, str(d.get("text") or "")[:300])}

    @app.get("/api/chaos/suggest")
    def chaos_suggest(request: Request) -> dict[str, Any]:
        operator(request)
        return S().chaos_suggestions()

    @app.post("/api/demo/telegram")
    async def demo_telegram(request: Request) -> dict[str, Any]:
        """Reproduce en local la secuencia entera del despacho por Telegram, sin plataforma ni bot:
        aviso → dos asignaciones → una acepta con ETA y zona, otra rechaza → reasignación → timeout →
        propuesta de escalada por voz. Solo operador: mete un aviso de verdad en el mundo."""
        operator(request)
        d = await body(request)
        zone = str(d.get("zone") or "front_pit")
        s = S()
        events = espejo_telegram.secuencia_demo(s, zone)
        salidas = [await asyncio.to_thread(s.tg_mirror.handle, ev) for ev in events]
        mirror = s.tg_mirror.view() or {}
        return {"ok": True, "n": len(events), "events": events, "results": salidas,
                "telegram": mirror, "escaladas": mirror.get("escaladas", [])}

    @app.post("/api/approve")
    async def approve(request: Request) -> dict[str, Any]:
        operator(request)
        d = await body(request)
        ok = d.get("ok", d.get("approve"))
        if not d.get("action_id") or ok is None:
            raise HTTPException(400, "Hacen falta «action_id» y «ok»")
        return S().operators.decide(str(d["action_id"]), ok, str(d.get("note") or "")[:200], identity(request))

    @app.get("/api/explica")
    @app.get("/porque")
    def api_explica(incident_id: str | None = None) -> dict[str, Any]:
        from .explica import explica
        return privacy.scrub(explica(S().state(), incident_id))

    @app.get("/api/explica/{incident_id}")
    def api_explica_id(incident_id: str) -> dict[str, Any]:
        from .explica import explica
        return privacy.scrub(explica(S().state(), incident_id))

    @app.get("/api/informe")
    def informe() -> dict[str, Any]:
        return S().informe()

    @app.get("/api/curve")
    def curve() -> dict[str, Any]:
        return load_curve()

    # ---- directorio Telegram (privado: chat_id no sale por /api/state) ----
    @app.get("/hr/tg/roster")
    async def hr_tg_roster_get(request: Request) -> dict[str, Any]:
        check_token(request)
        role = (request.query_params.get("role") or "").strip().lower()
        view = await asyncio.to_thread(app.state.tg_roster.seats_view)
        if role:
            seats = [s for s in view["seats"] if s["rol"] == role]
            return {**view, "seats": seats}
        return view

    @app.post("/hr/tg/roster")
    async def hr_tg_roster_post(request: Request) -> dict[str, Any]:
        check_token(request)
        data = await body(request)
        action = str(data.get("action") or "claim").strip().lower()
        if action == "list":
            return await asyncio.to_thread(app.state.tg_roster.seats_view)
        if action == "release":
            return await asyncio.to_thread(app.state.tg_roster.release, data, S().tg_mirror)
        if action == "claim":
            return await asyncio.to_thread(app.state.tg_roster.claim, data, S().tg_mirror)
        raise HTTPException(422, "action debe ser claim, release o list")

    @app.post("/hr/tg/dispatch")
    async def hr_tg_dispatch(request: Request) -> dict[str, Any]:
        check_token(request)
        data = await body(request)
        return await asyncio.to_thread(app.state.tg_roster.dispatch, data, S().tg_mirror)

    @app.post("/hr/tg/staff-response")
    async def hr_tg_staff_response(request: Request) -> dict[str, Any]:
        check_token(request)
        data = await body(request)
        return await asyncio.to_thread(app.state.tg_roster.staff_response, data, S().tg_mirror)

    # ---- webhooks de HappyRobot (contrato mando.hr.v1). Responder primero y deprisa.
    @app.post("/hr/events")
    async def hr_events(request: Request) -> dict[str, Any]:
        who = check_hr(request)
        try:
            ev = validation.webhook(await hr_body(request))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if ev.get("schema") not in (None, "mando.hr.v1"):
            raise HTTPException(400, "Esquema desconocido")
        s = S()
        kind = str(ev.get("type") or ev.get("message") or "")
        if who == "chat" and kind not in _CHAT_TYPES:
            raise HTTPException(403, "Ese token solo sirve para avisos y consultas de estado")
        if kind in ('decision', 'decision_pending'):
            from .hr_routing import apply_decision
            return await asyncio.to_thread(apply_decision, s, ev if kind == 'decision' else dict(ev, decision=''))
        if kind == 'text_delivery_request':
            from .hr_text_delivery import deliver_text
            return await asyncio.to_thread(deliver_text, s, ev, app.state.telegram)
        if kind == 'diffusion_result':
            from .hr_text_delivery import receipt
            return await asyncio.to_thread(receipt, s, ev)
        if kind.startswith('tg_'):
            # Espejo del despacho por Telegram. `tg_*` desconocido es un workflow mal configurado en la
            # plataforma: 422 y que se vea, en vez del 200 «stale» del resto de eventos correlacionados.
            return await asyncio.to_thread(s.tg_mirror.handle, ev)
        channel = ev.get('channel') or (ev.get('report') or {}).get('channel')
        if who == 'chat' and channel not in (None, 'web', 'chat', 'chatbot'):
            raise HTTPException(403, 'El token del widget solo admite su canal web')
        if who == 'chat':
            # El bloque report prevalece también sobre source plano o de extracted.
            ev['report'] = dict(ev.get('report') or {}, source='asistente')
            ev['channel'] = 'web'   # prevalece también sobre extracted.channel en structured_report
        if kind in ('staff_status', 'external_notice'):
            if ev.get('recovered'):
                raise HTTPException(422, 'El parte requiere JSON válido completo')
            if kind == 'staff_status':
                out = await asyncio.to_thread(s.staff.status, ev, ev.get('unit_token', ''))
            else:
                out = await asyncio.to_thread(external_notice, s, ev)
            s.comms.workflow_status.record('personal' if kind == 'staff_status' else 'avisos_externos', 'event')
            s._rebuild()
            return out
        if kind in _CHAT_TYPES:
            channel = ev.get('channel') or (ev.get('report') or {}).get('channel')
            workflow = ('voice' if channel in ('voice', 'web_call') else 'chat' if channel in ('chat', 'chatbot')
                        else channel if channel in ('email', 'sms') else 'intake')
            tracker = delegated.workflow_status if workflow == 'intake' else s.comms.workflow_status
            tracker.record(workflow, 'event', run_url=ev.get('run_url'))
        if kind == "report_status_query":
            return hr_status_query(ev)
        if kind == "public_report_update":
            out = await asyncio.to_thread(hr_report_update, ev)
            s._rebuild()
            return out
        if ev.get("type") == "public_report":
            out = await asyncio.to_thread(hr_public_report, ev)
            s._rebuild()
            return out
        if ev.get("message") == "public_report":
            rep = ev.get("report") or {}
            if not ev.get("final", True):
                return {"ok": True, "duplicate": False, "report_id": None, "ref_spoken": None, "say_text": None}
            eid = str(ev.get("event_id") or "")
            if eid and eid in s.comms._seen_events:
                return {"ok": True, "duplicate": True, "report_id": None, "ref_spoken": None, "say_text": None}
            s.comms._seen_events.add(eid)
            if ev.get("mode") == "test":
                s.log("report", "Aviso de prueba recibido (no entra al mundo)")
                return {"ok": True, "duplicate": False, "report_id": None, "ref_spoken": None, "say_text": None}
            r = s.report(str(rep.get("channel") or "whatsapp"), str(rep.get("text") or ""), rep.get("zone_hint"),
                         source=str(rep.get("source") or "asistente"), lang=str(rep.get("lang") or "es"),
                         extracted=ev.get("extracted") if isinstance(ev.get("extracted"), dict) else None)
            return {"ok": True, "duplicate": False, "report_id": r["report_id"], "ref_spoken": r["report_id"].split("-")[-1].lstrip("0"),
                    "say_text": "Aviso recibido. El centro de control ya lo tiene."}
        with s.lock:
            out = s.comms.on_event(ev)
            s._rebuild()
        s._wake.set()
        return out

    def hr_public_report(ev: dict[str, Any]) -> dict[str, Any]:
        """Lo que devuelven los workflows de ingesta (`mando-avisos-webcall`, `mando-ingesta-<canal>`): un aviso ya
        estructurado, de cualquier canal. Entra al mundo por el mismo camino que `/api/report`."""
        s = S()
        none = {"ok": True, "duplicate": False, "report_id": None, "ref_spoken": None, "say_text": None}
        state = delegated.deliver(ev)
        if state == "taken":    # lo esperaba un aviso nuestro (entendimiento delegado): lo mete en el mundo quien lo mandó
            return dict(none, delegated=True)
        if state == "late":
            s.log("report", "HappyRobot devolvió un aviso entendido fuera de plazo: ya había entrado en local, no se duplica")
            return dict(none, duplicate=True, report_id=delegated.report_of(ev), late=True)
        sr = intake.structured_report(ev, {z["id"]: z["name"] for z in s.festival["zones"]})
        ref = sr["report_ref"]
        eid = str(ev.get("event_id") or (f"{sr['hr_run_id']}-report" if sr["hr_run_id"] else ""))
        if ref:   # conversación guiada: el aviso entra EN CALIENTE (partial) y el final solo lo completa
            eid = f"{ref}-{'partial' if sr['partial'] else 'final'}"
            first = s.report_refs.get(ref)
            if first is not None:
                with s.lock:
                    dup = eid in s.comms._seen_events
                    s.comms._seen_events.add(eid)
                    s._report_extra.setdefault(first, {}).update(sr["extracted"])
                    if str(sr["extracted"].get("sensitive")).lower() == "true":
                        s._report_meta.setdefault(first, {})["reserved"] = True
                if not dup and not sr["partial"]:
                    s.log("report", f"La conversación del aviso {first} ha terminado: ficha completa" + (f" ({sr['extracted'].get('category')})" if sr["extracted"].get("category") else ""), first)
                return dict(none, duplicate=dup, report_id=first, ref_spoken=first.split("-")[-1].lstrip("0"))
        with s.lock:
            if eid and eid in s.comms._seen_events:
                return dict(none, duplicate=True)
            if eid:
                s.comms._seen_events.add(eid)
        if not sr["text"]:
            raise HTTPException(400, "El aviso no trae texto, descripción ni transcripción")
        if ev.get("mode") == "test":
            s.log("report", "Aviso de prueba recibido (no entra al mundo)")
            return none
        if sr['real_channel'] == 'telegram' and sr['reply_to'] and app.state.telegram is not None:
            try:
                result = app.state.telegram.receive_report(sr['reply_to'], sr['text'], sr)
                if ref and result.get('report_id'):
                    s.report_refs[ref] = result['report_id']
                return result
            except ValueError:
                raise HTTPException(422, 'reply_to de Telegram debe ser un chat_id')
        r = submit_report(sr["channel"], sr["text"], sr["zone"], delegate=False, source=sr["source"], lang=sr["lang"],
                          extracted=sr["extracted"], via=sr["real_channel"], where=sr["where"], understood="happyrobot",
                          preset_hint=sr["preset_hint"])
        if ref:
            s.report_refs[ref] = r["report_id"]
        return {"ok": True, "duplicate": False, "report_id": r["report_id"], "ref_spoken": r["report_id"].split("-")[-1].lstrip("0"),
                "say_text": "Aviso recibido. El centro de control ya lo tiene.", "safety": r.get("safety")}

    def hr_report_update(ev: dict[str, Any]) -> dict[str, Any]:
        """`actualizar_aviso(campo, valor)` de la conversación guiada: se enlaza al MISMO aviso, nunca abre otro incidente."""
        s = S()
        ref = str(ev.get("report_ref") or "")
        first = s.report_refs.get(ref)
        if first is None:
            return {"ok": True, "duplicate": False, "report_id": None, "unknown_ref": True}
        field, value = str(ev.get("field") or ""), str(ev.get("value") or "")
        eid = str(ev.get("event_id") or f"{ref}-update-{field}-{value}"[:120])
        with s.lock:
            if eid in s.comms._seen_events:
                return {"ok": True, "duplicate": True, "report_id": first}
            s.comms._seen_events.add(eid)
            s._report_extra.setdefault(first, {})[field] = value
        if not value.strip():
            return {"ok": True, "duplicate": False, "report_id": first}
        meta = s._report_meta.get(first) or {}
        zones = {z["id"]: z["name"] for z in s.festival["zones"]}
        where = telegram_bot.match_zone(value, zones) if telegram_bot._plain(field) in ("ubicacion", "location") else None
        old = next((r for r in s.world.reports if r.id == first), None)
        r = submit_report(str(old.channel) if old else "voice", intake.update_text(field, value), None, delegate=False,
                          source=old.source if old else "asistente", via=meta.get("via"), understood="happyrobot", update_of=first, where=where)
        return {"ok": True, "duplicate": False, "report_id": first, "update_id": r["report_id"]}

    def hr_status_query(ev: dict[str, Any]) -> dict[str, Any]:
        """`consultar_estado`: el agente de la plataforma REPITE `say_text` tal cual. Corto, neutro, sin tiempos."""
        s = S()
        first = s.report_refs.get(str(ev.get("report_ref") or ""))
        info = s.report_status(first) if first else {}
        status = str(info.get("status") or "unknown") if info.get("found") else "unknown"
        if status == "open" and (info.get("call") or {}).get("state") == "acepta":
            status = "assigned"
        return {"ok": True, "say_text": intake.SAY_STATUS.get(status, intake.SAY_STATUS["unknown"]), "report_id": first}

    @app.post("/hr/identify")
    async def hr_identify(request: Request) -> dict[str, Any]:
        check_token(request)
        d = await body(request)
        return S().comms.identify(str(d.get("from_number") or ""))

    @app.post("/hr/approval_check")
    async def hr_approval_check(request: Request) -> dict[str, Any]:
        check_token(request)
        d = await body(request)
        s = S()
        aid = str(d.get("action_id") or "")
        rec = s.approvals.get(aid)
        act = next((a for a in s.state().get("actions", []) if a.get("id") == aid), None)
        reason = None
        if d.get("session_id") and d["session_id"] != s.session_id:
            reason = "otra sesión"
        elif rec is None or not rec.get("ok"):
            reason = "sin aprobación de una persona"
        elif d.get("approval_id") != rec["approval_id"]:
            reason = "approval_id no coincide"
        elif rec.get("used"):
            reason = "aprobación ya usada"
        elif s.world.t - rec["t"] > 10:
            reason = "aprobación caducada (más de 10 min)"
        if reason:
            s.log("approval", f"HappyRobot pregunta por {aid}: NO aprobada ({reason})", aid)
            return {"ok": True, "approved": False, "kind": act.get("kind") if act else None, "approved_by": None,
                    "approved_t": None, "reason": reason}
        rec["used"] = True
        return {"ok": True, "approved": True, "kind": act.get("kind") if act else None, "approved_by": rec["by"],
                "approved_t": rec["t"], "reason": None}

    @app.post("/hr/webcall/next")
    async def hr_webcall(request: Request) -> dict[str, Any]:
        check_token(request)
        await body(request)
        order = S().comms.next_webcall_order()
        return {"ok": True, "has_order": order is not None, "order": order}

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"ok": False, "error": exc.detail}, status_code=exc.status_code)

    # ---- servidor MCP propio en /mcp (Streamable HTTP), protegido por MANDO_MCP_TOKEN
    try:
        from starlette.routing import Route

        from .mcp_server import TokenGuard, build_mcp
        app.state.mcp = build_mcp(S, lambda *a, **k: submit_report(*a, delegate=False, **k))
        app.router.routes.append(Route("/mcp", endpoint=TokenGuard(app.state.mcp.streamable_http_app())))
    except ImportError:   # sin el SDK `mcp` instalado el resto del servidor funciona igual
        app.state.mcp = None

    # ---- bot de Telegram (long polling): solo si hay TELEGRAM_BOT_TOKEN
    app.state.telegram = telegram_bot.start_from_env(get_session=S, submit_report=submit_report, submit_strike=submit_strike,
                                                     strike_presets=STRIKE_PRESETS, wristband=intake.wristband)
    if app.state.telegram is not None:
        app.state.telegram.chat_hub = hub
        Session.ask_router = staticmethod(lambda session, action: app.state.telegram.route_ask(session, action))
        app.state.telegram.on_change = lambda: S()._rebuild()
    else:
        Session.ask_router = None
    from .team_routes import install as install_team
    install_team(app, S, lambda: public_base() or f"http://{lan_ip()}:{app.state.port}")
    from .evidence_routes import register as register_evidence
    register_evidence(app, S, STATIC)
    from .historial_routes import install as install_history
    install_history(app, app.state.history, STATIC)
    S()._rebuild()
    return app
