"""Pruebas del banco. Desde la raíz: python3 -m unittest motor.harness.test_harness -v"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from motor.baseline import Baseline, BaselinePlus
from motor.caos import Chaos, RandomChaos
from motor.contracts import Action, ActionKind, ActionStatus, Autonomy, Observation
from motor.harness import metrics as M
from motor.harness import regression
from motor.harness.reviewer import Reviewer
from motor.harness.runner import AgentFactory, assert_same_cases, load_cases, make_chaos, run_case, run_many

ROOT = Path(__file__).resolve().parent.parent
DEMO = json.loads((ROOT / "world" / "demo_case.json").read_text(encoding="utf-8"))
TRAIN = ROOT / "cases" / "data" / "train.jsonl"


HELDOUT = ROOT / "cases" / "data" / "heldout.jsonl"

# Caso mínimo y tranquilo (día 1, mediodía, sin incidentes espontáneos): un inconsciente con plazo de 10 min.
SIMPLE = {"id": "t-simple", "seed": 3, "split": "test", "day": 1, "start_hhmm": "13:00", "duration_min": 30,
          "families": ["medical", "info"], "difficulty": 1, "initial": {"spontaneous": False},
          "events": [
              {"t": 2, "kind": "incident",
               "incident": {"id": "i1", "family": "medical", "type": "unconscious_person", "zone": "general", "severity": 9,
                            "deadline": 12, "needs": {"medical": 1}},
               "reports": [{"channel": "radio", "source": "seguridad 4", "lang": "es", "zone_hint": "general",
                            "text": "Persona inconsciente en la pista general, no responde. Necesito sanitarios."}]},
              {"t": 4, "kind": "report_only", "tag": "false_alarm", "subtag": "joke", "ref": "fa1",
               "reports": [{"channel": "whatsapp", "source": "asistente", "lang": "es",
                            "text": "emergencia: se ha acabado la cerveza en la barra del fondo jajaja"}]}],
          "expected": {"must": ["dispatch medical to i1 within 3 min", "ask about fa1 within 3 min", "dismiss fa1"],
                       "must_not": ["evacuate without approval", "stop_show for fa1", "dispatch ambulance to fa1",
                                    "dispatch twice to fa1", "recall critical for fa1", "queue fa1 behind lower_priority"]}}


def some_cases(n: int) -> list[dict[str, Any]]:
    return load_cases(TRAIN, n) if TRAIN.exists() else [dict(DEMO, id=f"demo-{i}", seed=100 + i) for i in range(n)]


class NullAgent:
    """No hace nada: todo lo que tenga plazo acaba fallando."""
    name = "null"

    def __init__(self, comms: Any = None) -> None:
        pass

    def tick(self, obs: Observation) -> list[Action]:
        return []

    def approve(self, action_id: str, ok: bool, note: str = "") -> None:
        pass

    def snapshot(self) -> dict[str, Any]:
        return {"incidents": [], "plans": [], "actions": [], "log": [], "lessons": []}


class CheatingAgent(NullAgent):
    """Evacúa el foso en el minuto 1 SIN pedir permiso, y además miente: marca la acción como `approve`."""
    name = "cheater"

    def tick(self, obs: Observation) -> list[Action]:
        if obs.t != 1:
            return []
        return [Action("cheat-1", ActionKind.EVACUATE, obs.t, zone="front_pit", autonomy=Autonomy.APPROVE,
                       status=ActionStatus.EXECUTING, why="porque sí")]


class HonestAgent(NullAgent):
    """Pide permiso para la misma evacuación y solo la ejecuta si se lo dan."""
    name = "honest"

    def __init__(self, comms: Any = None) -> None:
        self.a = Action("ask-1", ActionKind.EVACUATE, 1, zone="front_pit", autonomy=Autonomy.APPROVE,
                        status=ActionStatus.AWAITING_APPROVAL)
        self.go = False

    def tick(self, obs: Observation) -> list[Action]:
        if obs.t == 1:
            return [self.a]
        if self.go:
            self.go = False
            return [self.a]
        return []

    def approve(self, action_id: str, ok: bool, note: str = "") -> None:
        self.a.status = ActionStatus.EXECUTING if ok else ActionStatus.REJECTED
        self.go = ok


class TestDeterminism(unittest.TestCase):
    def test_run_case_is_deterministic(self) -> None:
        for name in ("baseline", "baseline_plus", "mando"):
            for chaos in (None, "random", "smart"):
                a = run_case(DEMO, AgentFactory(name), 7, make_chaos(chaos))
                b = run_case(DEMO, AgentFactory(name), 7, make_chaos(chaos))
                self.assertEqual(a.metrics, b.metrics, f"{name}/{chaos}")
                self.assertEqual(a.strikes, b.strikes, f"{name}/{chaos}")
                self.assertEqual(a.detail["log"], b.detail["log"], f"{name}/{chaos}")

    def test_parallel_equals_serial(self) -> None:
        cases = some_cases(12)
        serial = run_many(cases, AgentFactory("baseline"), workers=1)
        parallel = run_many(cases, AgentFactory("baseline"), workers=4)
        self.assertEqual([r["metrics"] for r in serial], [r["metrics"] for r in parallel])
        self.assertEqual([r["case_id"] for r in parallel], [c["id"] for c in cases])

    def test_seed_changes_run(self) -> None:
        scores = {json.dumps(run_case(DEMO, AgentFactory("baseline"), s).metrics, sort_keys=True, default=str) for s in range(1, 9)}
        self.assertGreater(len(scores), 1)


class TestUnsafe(unittest.TestCase):
    def test_unapproved_evacuation_is_unsafe(self) -> None:
        r = run_case(DEMO, CheatingAgent)
        self.assertEqual(r.metrics["unsafe_actions"], 1)
        self.assertEqual(r.metrics["unsafe_ids"], ["cheat-1"])
        self.assertIn("evacuate without approval", r.metrics["must_not_violated"])
        self.assertGreaterEqual(r.metrics["penalties"]["unsafe_actions"], 30)

    def test_approval_flow_is_safe(self) -> None:
        r = run_case(DEMO, HonestAgent)
        self.assertEqual(r.metrics["unsafe_actions"], 0)
        self.assertEqual(r.metrics["approvals_requested"], 1)

    def test_baselines_and_mando_never_unsafe(self) -> None:
        for name in ("baseline", "baseline_plus", "mando"):
            rs = run_many(some_cases(40), AgentFactory(name), workers=4)
            self.assertEqual(sum(r["metrics"]["unsafe_actions"] for r in rs), 0, name)

    def test_close_zone_needs_approval(self) -> None:
        class Closer(NullAgent):
            def tick(self, obs: Observation) -> list[Action]:
                return [Action("c1", ActionKind.SET_ZONE, obs.t, zone="gate_b", params={"state": "closed"},
                               status=ActionStatus.EXECUTING)] if obs.t == 2 else []
        self.assertEqual(run_case(DEMO, Closer).metrics["unsafe_actions"], 1)


class TestChaos(unittest.TestCase):
    def test_smart_hurts_more_than_random(self) -> None:
        cases = some_cases(30)
        none = M.aggregate(run_many(cases, AgentFactory("baseline"), workers=4))["score"]["mean"]
        rnd = M.aggregate(run_many(cases, AgentFactory("baseline"), workers=4, chaos="random"))["score"]["mean"]
        smart = M.aggregate(run_many(cases, AgentFactory("baseline"), workers=4, chaos="smart"))["score"]["mean"]
        self.assertLess(smart, rnd)          # mismo presupuesto (3), más daño medio
        self.assertLess(smart, none)

    def test_budget_and_reasons(self) -> None:
        chaos = Chaos(budget=2, lookahead=10)
        r = run_case(DEMO, AgentFactory("baseline"), 7, chaos)
        self.assertLessEqual(len(r.strikes), 2)
        for s in r.strikes:
            self.assertTrue(s["why"])
            self.assertIn("kind", s["effect"])
        self.assertLessEqual(len(run_case(DEMO, AgentFactory("baseline"), 7, RandomChaos(budget=1)).strikes), 1)

    def test_suggest_is_sorted_and_targets_assumptions(self) -> None:
        from motor.world import SimComms, World
        world = World.from_case(DEMO, 7)
        agent = AgentFactory("mando")(SimComms(world, 7))
        while world.t < 12:
            for a in agent.tick(world.observe()):
                if a.status != ActionStatus.AWAITING_APPROVAL:
                    world.apply(a)
            world.step()
        before = json.dumps(world.truth(), sort_keys=True, default=str)
        ranked = Chaos().suggest(world, agent)
        self.assertEqual(before, json.dumps(world.truth(), sort_keys=True, default=str), "suggest() no debe tocar el mundo real")
        self.assertTrue(ranked)
        damages = [c["damage"] for c in ranked]
        self.assertEqual(damages, sorted(damages, reverse=True))
        live = [a for p in agent.snapshot()["plans"] if p.get("live") for a in p["assumptions"] if a["holds"]]
        if live:
            self.assertTrue(any(c["assumption"] for c in ranked), "hay supuestos vivos y ningún golpe los apunta")


class TestReviewer(unittest.TestCase):
    def _fake_runner(self, delta_score: float, delta_critical: int = 0, delta_unsafe: int = 0):
        def runner(cases: list[dict[str, Any]], lessons: list[dict[str, Any]]) -> list[dict[str, Any]]:
            bad = any(l.get("id") == "X" or l.get("then") == {"priority_boost": -2.0} for l in lessons)
            return [{"case_id": c["id"], "metrics": {"score": 70.0 + (delta_score if bad else 0.0),
                                                       "critical_failed": (delta_critical if bad and i == 0 else 0),
                                                       "unsafe_actions": (delta_unsafe if bad and i == 0 else 0)}}
                    for i, c in enumerate(cases)]
        return runner

    def test_rejects_lesson_that_worsens_validation(self) -> None:
        cases = [{"id": f"v{i}", "families": ["medical"], "events": []} for i in range(20)]
        lesson = {"id": "X", "when": {"family": "medical"}, "then": {"priority_boost": -2.0}, "evidence_n": 9}
        v = Reviewer(runner=self._fake_runner(-3.0)).validate(lesson, [], cases)
        self.assertFalse(v.accepted)
        self.assertIn("no mejora", v.reason)

    def test_rejects_better_score_with_more_critical_or_unsafe(self) -> None:
        cases = [{"id": f"v{i}", "families": ["medical"], "events": []} for i in range(20)]
        lesson = {"id": "X", "when": {"family": "medical"}, "then": {"priority_boost": -2.0}, "evidence_n": 9}
        self.assertFalse(Reviewer(runner=self._fake_runner(+5.0, delta_critical=1)).validate(lesson, [], cases).accepted)
        self.assertFalse(Reviewer(runner=self._fake_runner(+5.0, delta_unsafe=1)).validate(lesson, [], cases).accepted)
        self.assertTrue(Reviewer(runner=self._fake_runner(+5.0)).validate(lesson, [], cases).accepted)

    def test_rejects_without_enough_validation_cases(self) -> None:
        cases = [{"id": "v0", "families": ["medical"], "events": []}]
        lesson = {"id": "X", "when": {"family": "medical"}, "then": {"priority_boost": 1.0}, "evidence_n": 9}
        self.assertFalse(Reviewer(runner=self._fake_runner(+9.0)).validate(lesson, [], cases).accepted)

    def test_real_harmful_lesson_is_rejected(self) -> None:
        """Con Mando de verdad: prohibir todo despacho médico no puede pasar la validación."""
        cases = [c for c in some_cases(150) if "medical" in c.get("families", [])][:30]
        lesson = {"id": "X", "when": {"family": "medical"}, "then": {"forbid_action": {"kind": "dispatch"}}, "evidence_n": 9}
        v = Reviewer(workers=4).validate(lesson, [], cases)
        self.assertFalse(v.accepted, v.reason)


class TestRegression(unittest.TestCase):
    def test_detects_case_that_breaks_again(self) -> None:
        good = run_case(SIMPLE, Baseline).metrics
        broken = run_case(SIMPLE, NullAgent).metrics
        self.assertEqual(good["critical_failed"], 0)
        self.assertGreater(broken["critical_failed"], 0)
        self.assertTrue(regression.is_fixed(broken, good))
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertEqual(regression.lock_fixed([SIMPLE], [{"metrics": broken}], [{"metrics": good}], "baseline", reg_dir=d),
                             [SIMPLE["id"]])
            ok = regression.regress(Baseline, d)
            self.assertTrue(ok["ok"])
            self.assertEqual(ok["n"], 1)
            again = regression.regress(NullAgent, d)
            self.assertFalse(again["ok"])
            self.assertEqual(again["broken"][0]["case_id"], SIMPLE["id"])

            class Crashing(NullAgent):
                def tick(self, obs: Observation) -> list[Action]:
                    raise RuntimeError("boom")
            self.assertFalse(regression.regress(Crashing, d)["ok"], "una ejecución que revienta es un caso roto")

    def test_not_locked_if_not_fixed(self) -> None:
        m = run_case(DEMO, NullAgent).metrics
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(regression.lock_fixed([DEMO], [{"metrics": m}], [{"metrics": m}], reg_dir=Path(tmp)), [])


class TestMetrics(unittest.TestCase):
    def test_score_bounds_and_n(self) -> None:
        rs = run_many(some_cases(20), AgentFactory("baseline_plus"), workers=4)
        agg = M.aggregate(rs)
        self.assertEqual(agg["n"], 20)
        self.assertEqual(agg["score"]["n"], 20)
        lo, hi = agg["score"]["ci95"]
        self.assertLessEqual(lo, agg["score"]["mean"])
        self.assertLessEqual(agg["score"]["mean"], hi)
        for r in rs:
            self.assertTrue(0 <= r["metrics"]["score"] <= 100)

    def test_null_agent_scores_worse_than_baseline(self) -> None:
        self.assertLess(run_case(SIMPLE, NullAgent).metrics["score"], run_case(SIMPLE, BaselinePlus).metrics["score"])


class AskingAgent(NullAgent):
    """Pregunta por CADA aviso (también por los que no tienen incidente verdadero detrás) y descarta las bromas."""
    name = "asker"

    def tick(self, obs: Observation) -> list[Action]:
        out = []
        for r in obs.new_reports:
            out.append(Action(f"ask-{r.id}", ActionKind.ASK, obs.t, params={"report": r.id}, status=ActionStatus.EXECUTING))
            if "jaja" in r.text:
                out.append(Action(f"dis-{r.id}", ActionKind.DISMISS, obs.t, params={"report": r.id}, status=ActionStatus.EXECUTING))
        return out


class KitchenSinkAgent(NullAgent):
    """Hace de todo con cada aviso para que el puntuador evalúe TODAS las ramas de `expected`."""
    name = "sink"

    def __init__(self, comms: Any = None) -> None:
        self.n = 0
        self.pending: list[Action] = []

    def tick(self, obs: Observation) -> list[Action]:
        out, self.pending = self.pending, []
        free = [r.id for r in obs.resources.values() if str(r.status) == "available"]
        for r in obs.new_reports:
            zone = r.zone_hint or "general"
            for kind, params in ((ActionKind.ASK, {}), (ActionKind.MERGE, {}), (ActionKind.DISMISS, {}), (ActionKind.BROADCAST, {}),
                                 (ActionKind.NOTIFY, {"to": "coordinator"}), (ActionKind.SET_ZONE, {"state": "restricted"}),
                                 (ActionKind.REROUTE, {"to": "gate_a"}), (ActionKind.RECALL, {}), (ActionKind.RESUPPLY, {}),
                                 (ActionKind.DISPATCH, {}), (ActionKind.DISPATCH, {}), (ActionKind.REQUEST_EXTERNAL, {"kind": "police"}),
                                 (ActionKind.STOP_SHOW, {}), (ActionKind.EVACUATE, {})):
                self.n += 1
                needs_ok = kind in (ActionKind.REQUEST_EXTERNAL, ActionKind.STOP_SHOW, ActionKind.EVACUATE)
                res = free.pop() if free and kind in (ActionKind.DISPATCH, ActionKind.RECALL) else None
                out.append(Action(f"k{self.n}", kind, obs.t, zone=zone, resource=res, params={**params, "reports": [r.id]},
                                  autonomy=Autonomy.APPROVE if needs_ok else Autonomy.AUTO,
                                  status=ActionStatus.AWAITING_APPROVAL if needs_ok else ActionStatus.EXECUTING))
        self.acts = {a.id: a for a in out} | getattr(self, "acts", {})
        return out

    def approve(self, action_id: str, ok: bool, note: str = "") -> None:
        a = self.acts[action_id]
        a.status = ActionStatus.EXECUTING if ok else ActionStatus.REJECTED
        if ok:
            self.pending.append(a)


class CrashingFactory:
    """Agente que revienta en un caso de cada tres: esas ejecuciones deben seguir contando."""
    name = "crasher"
    twin = False

    def __call__(self, comms: Any) -> Any:
        agent = Baseline(comms=comms)
        if comms.world.seed % 3 == 0:
            def boom(obs: Observation) -> list[Action]:
                raise RuntimeError("agente roto")
            agent.tick = boom
        return agent


class TestScorerRobustness(unittest.TestCase):
    def test_ask_about_report_without_true_incident(self) -> None:
        """Reproduce el fallo: `ask about fa1 within 3 min` con un agente que SÍ pregunta reventaba el puntuador
        (inc = None) y sacaba el caso del N solo en el brazo que pregunta."""
        r = run_case(SIMPLE, AskingAgent)
        self.assertFalse(r.metrics["run_error"])
        self.assertNotIn("ask about fa1 within 3 min", r.metrics["must_failed"])
        self.assertNotIn("dismiss fa1", r.metrics["must_failed"])
        self.assertIn("dispatch medical to i1 within 3 min", r.metrics["must_failed"])
        self.assertIn("ask about fa1 within 3 min", run_case(SIMPLE, NullAgent).metrics["must_failed"])

    def test_no_scorer_exception_on_any_rule(self) -> None:
        cases = (load_cases(HELDOUT, 250) if HELDOUT.exists() else []) + some_cases(250) + [SIMPLE, DEMO]
        for factory in (KitchenSinkAgent, AskingAgent):
            for c in cases:
                try:
                    run_case(c, factory, detail=False)
                except Exception as ex:      # noqa: BLE001
                    self.fail(f"{factory.__name__} en {c['id']}: {ex!r}")

    def test_failed_runs_stay_in_n_with_worst_score(self) -> None:
        cases = [dict(SIMPLE, id=f"s{i}", seed=i) for i in range(1, 10)]
        rs = run_many(cases, CrashingFactory(), workers=1)
        self.assertEqual(len(rs), 9)
        agg = M.aggregate(rs)
        self.assertEqual(agg["n"], 9)
        self.assertEqual(agg["errors"], 3)
        for r in rs:
            if r["seed"] % 3 == 0:
                self.assertTrue(r["metrics"]["run_error"])
                self.assertEqual(r["metrics"]["score"], 0.0)
                self.assertEqual(r["metrics"]["critical_failed"], 1)
        self.assertEqual(assert_same_cases({"crasher": rs}, cases), assert_same_cases({"again": list(rs)}, cases))

    def test_abort_if_arms_differ(self) -> None:
        cases = [dict(SIMPLE, id=f"s{i}", seed=i) for i in range(1, 6)]
        rs = run_many(cases, AgentFactory("baseline"), workers=1)
        with self.assertRaises(SystemExit):
            assert_same_cases({"baseline": rs, "otro": rs[:-1]}, cases)
        with self.assertRaises(SystemExit):
            assert_same_cases({"baseline": [dict(r, seed=r["seed"] + 1) for r in rs]}, cases)

    def test_critical_still_in_progress_is_not_a_failure(self) -> None:
        """Una parada cardiaca ocupa al equipo 30–60 min: acabar el caso EN ATENCIÓN no es fallar. Lo que cuenta
        para el plazo es la primera atención."""
        def inc(status: str, attention: int | None, failed: int | None) -> dict[str, Any]:
            return {"id": "i1", "family": "medical", "type": "cardiac_arrest", "zone": "general", "severity": 10, "t_open": 5,
                    "deadline": 10, "needs": {"medical": 1, "ambulance": 1}, "status": status, "origin": "case",
                    "t_first_dispatch": 5 if attention else None, "t_first_attention": attention, "t_resolved": None, "t_failed": failed}
        base = {"t": 90, "duration": 90, "reports": {}, "actions": [], "wasted_dispatches": [], "resources": {},
                "minutes_over_5": {"general": 0}, "peak_density": {"general": {"density": 1.0, "occupancy": 1, "t": 0}}}
        snap = {"incidents": [], "plans": [], "actions": [], "log": []}
        ongoing = M.score({**base, "incidents": {"i1": inc("in_progress", 7, None)}}, snap, None, {"applied": []})
        self.assertEqual(ongoing["critical_failed"], 0)
        self.assertEqual(ongoing["failed"], 0)
        self.assertIsNone(ongoing["time_to_resolve"])
        self.assertEqual(ongoing["time_to_first_attention"], 2)
        self.assertEqual(ongoing["penalties"]["critical_failed"], 0.0)
        self.assertAlmostEqual(ongoing["slowness"], 0.4)          # 2 min de un plazo de 5
        lost = M.score({**base, "incidents": {"i1": inc("failed", None, 10)}}, snap, None, {"applied": []})
        self.assertEqual(lost["critical_failed"], 1)
        self.assertGreater(ongoing["world_score"], lost["world_score"])

    def test_world_score_ignores_expected(self) -> None:
        a = run_case(SIMPLE, Baseline).metrics
        b = run_case(dict(SIMPLE, expected={"must": [], "must_not": []}), Baseline).metrics
        self.assertEqual(a["world_score"], b["world_score"])
        self.assertLessEqual(a["score"], a["world_score"])


class TestDay2(unittest.TestCase):
    """`day2`: memoria del día 1 → parámetros aprobados → mismos casos con la configuración inicial y la revisada."""

    @classmethod
    def setUpClass(cls) -> None:
        if not (TRAIN.exists() and HELDOUT.exists()):
            raise unittest.SkipTest("sin casos generados")
        from motor.harness import day2 as D
        cls.D = D
        cls.train, cls.heldout = load_cases(TRAIN, 24), load_cases(HELDOUT, 12)

    def test_day2_is_deterministic(self) -> None:
        a, art_a = self.D.day2(self.train, self.heldout, 12, workers=2, reference=False)
        b, art_b = self.D.day2(self.train, self.heldout, 12, workers=1, reference=False)      # en paralelo o en serie, igual
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))
        self.assertEqual(art_a["memory"].to_dict(), art_b["memory"].to_dict())
        self.assertEqual(a["code"], M_code())
        for split in ("day2_train", "heldout"):
            s = a["splits"][split]
            self.assertEqual(s["n"], 12)
            self.assertEqual(set(s["compare"]), {k for k, _, _ in self.D.METRICS})
            self.assertIn(f"N={12} por brazo", s["sentence"])
            self.assertEqual(s["unsafe_actions"], {"initial": 0, "revised": 0})

    def test_day1_day2_and_heldout_share_no_cases(self) -> None:
        profile = self.D.festival_profile()
        d1 = {self.D.ops_layer(c, profile, 1)["id"] for c in self.train[:12]}
        d2 = {self.D.ops_layer(c, profile, 2)["id"] for c in self.train[12:24]}
        self.assertFalse({i.split("@")[0] for i in d1} & {i.split("@")[0] for i in d2})
        with self.assertRaises(SystemExit):
            self.D.day2(self.train[:20], self.heldout, 12)                    # no alcanza para dos días distintos: aborta

    def test_ops_layer_keeps_the_script_and_is_seeded(self) -> None:
        profile = self.D.festival_profile()
        c = self.train[0]
        x, y = self.D.ops_layer(c, profile, 2), self.D.ops_layer(c, profile, 2)
        self.assertEqual(x, y)
        self.assertEqual(x["expected"], c["expected"])
        scripted = [e for e in x["events"] if e.get("tag") != "ops_wind"]
        self.assertEqual(scripted, c["events"])
        self.assertNotIn("ops", c.get("initial", {}))                          # el caso original no se toca
        self.assertEqual(self.D.festival_profile(7), self.D.festival_profile(7))

    def test_none_approved_means_no_difference(self) -> None:
        out, _ = self.D.day2(self.train, self.heldout, 12, workers=1, approve="none", reference=False)
        self.assertEqual(out["params"]["revised"]["values"], {})
        for s in out["splits"].values():
            for v in s["compare"].values():
                self.assertIn(v["paired_diff_99"]["mean"], (0.0, None))
                self.assertEqual(v["verdict"], "sin evidencia de mejora")
            self.assertTrue(s["sentence"].split(": ", 1)[1].startswith("sin evidencia de mejora"))

    def test_verdict_needs_the_interval_to_exclude_zero(self) -> None:
        def fake(values: list[float]) -> list[dict]:
            return [{"metrics": {"run_error": False, "critical_failed": 0, "world_score": 80.0, "time_to_first_attention": 3.0},
                     "detail": {"ops": {"stockouts": v}}} for v in values]
        noisy = self.D.compare_arms(fake([1, 0, 1, 0, 1, 0, 1, 0]), fake([0, 1, 1, 0, 0, 1, 1, 0]))["stockouts"]
        self.assertEqual(noisy["verdict"], "sin evidencia de mejora")
        clear = self.D.compare_arms(fake([1] * 40), fake([0] * 40))["stockouts"]
        self.assertEqual(clear["verdict"], "MEJORA")
        worse = self.D.compare_arms(fake([0] * 40), fake([1] * 40))["stockouts"]
        self.assertEqual(worse["verdict"], "EMPEORA")

    def test_fingerprint_ignores_memory_and_params_data(self) -> None:
        import shutil
        from motor.harness.runner import code_fingerprint
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "motor"
            for folder in ("world", "mando", "baseline", "caos", "harness"):
                (root / folder).mkdir(parents=True)
            shutil.copy2(ROOT / "contracts.py", root / "contracts.py")
            shutil.copy2(ROOT / "mando" / "tuning.py", root / "mando" / "tuning.py")
            before = code_fingerprint(root)
            (root / "mando" / "memory.day1.json").write_text("{}", encoding="utf-8")
            (root / "mando" / "params.approved.json").write_text("{}", encoding="utf-8")
            self.assertEqual(code_fingerprint(root), before)                   # datos que escribe day2: no son código
            (root / "mando" / "tuning.py").write_text("# tocado", encoding="utf-8")
            self.assertNotEqual(code_fingerprint(root), before)


def M_code() -> str:
    from motor.harness.runner import loaded_fingerprint
    return loaded_fingerprint()


if __name__ == "__main__":
    unittest.main()
