"""CLI del banco de pruebas. Desde la raíz del proyecto:

    python3 -m motor.harness run --agent mando --cases motor/cases/data/train.jsonl --n 300 --chaos none --label prueba
    python3 -m motor.harness compare --cases motor/cases/data/train.jsonl --n 1000 [--chaos smart]
    python3 -m motor.harness learn --rounds 4
    python3 -m motor.harness curve | report | regress
    python3 -m motor.harness headline            # el titular reproducible: Mando − lista fija, pareado, con N, IC y huella
    python3 -m motor.harness load                # curva de degradación con la carga (motor/cases/data/load.jsonl)
    python3 -m motor.harness pick --n 40         # casos heldout 4–5 ya comprobados, para elegir uno en cámara
    python3 -m motor.harness day2 --n 400        # día 1 → memoria → parámetros aprobados → día 2 y heldout, pareado
    python3 -m motor.harness --freeze all        # TODO lo anterior sobre una copia congelada del código

Salidas: `out/<fecha>-<etiqueta>/` + enlace `out/latest` + copia del último fichero de cada tipo en `out/`.
Nunca se borra nada de `out/` ni de `regression/`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zlib
from pathlib import Path
from typing import Any

from . import metrics as M
from . import regression
from .reviewer import Reviewer, top_failures
from .runner import (AgentFactory, assert_same_cases, code_fingerprint, load_cases, loaded_fingerprint, run_many)

HERE = Path(__file__).resolve().parent
OUT_ROOT = Path(os.environ.get("MOTOR_HARNESS_OUT") or (HERE / "out"))
DATA = Path(os.environ.get("MOTOR_HARNESS_DATA") or (HERE.parent / "cases" / "data"))
AGENT_ES = {"baseline": "Lista fija", "baseline_plus": "Lista fija + (fusiona y ordena)", "mando": "Mando (sin lecciones)",
            "mando_learned": "Mando (manual aprendido)", "mando_twin": "Mando con ensayo previo (gemelo)"}
_SESSION: Path | None = None


# ---------------------------------------------------------------------------- salidas

def session(label: str = "run") -> Path:
    """Directorio de esta ejecución: out/<fecha>-<etiqueta>/, con `out/latest` apuntando a él."""
    global _SESSION
    if _SESSION is None:
        _SESSION = OUT_ROOT / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}"
        _SESSION.mkdir(parents=True, exist_ok=True)
        link = OUT_ROOT / "latest"
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(_SESSION.name, target_is_directory=True)
        except OSError:
            pass
    return _SESSION


def _write(name: str, data: Any, label: str = "run") -> Path:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1, default=str)
    path = session(label) / name
    path.write_text(text, encoding="utf-8")
    tmp = OUT_ROOT / f".{name}.tmp"           # copia en out/ (sustitución atómica): otros procesos leen de ahí
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, OUT_ROOT / name)
    return path


def _read(name: str) -> Any:
    for path in ((_SESSION / name) if _SESSION else None, OUT_ROOT / name):
        if path is not None and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def load_lessons(which: str | None) -> list[dict[str, Any]]:
    """none | learned | learned_world | seed | ruta a un JSON {"lessons": [...]}."""
    if not which or which == "none":
        return []
    path = {"learned": OUT_ROOT / "playbook.learned.json", "learned_world": OUT_ROOT / "playbook.learned_world.json",
            "seed": HERE.parent / "mando" / "playbook.seed.json"}.get(which, Path(which))
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["lessons"] if isinstance(data, dict) else data


def _guard(fp0: str, where: str) -> None:
    """Aborta si el código en disco ya no es el que se cargó: las cifras mezclarían dos versiones."""
    now = code_fingerprint()
    if now != fp0:
        raise SystemExit(f"ABORTADO en {where}: la huella del código ha cambiado ({fp0} → {now}). Alguien está editando "
                         "motor/. Repite con el código quieto o usa `python3 -m motor.harness --freeze …`.")


def _line(name: str, agg: dict[str, Any]) -> str:
    s, w = agg["score"], agg["world_score"]
    return (f"{name:34s} N={agg['n']:<5d} score {s['mean']:6.2f} [{s['ci95'][0]:.2f}, {s['ci95'][1]:.2f}]  solo-mundo {w['mean']:6.2f}  "
            f"críticos fallidos {agg['critical_failed_total']}/{agg['critical_total']}  inseguras {agg['unsafe_total']}  "
            f"desperd. {agg['wasted_dispatches']['mean']}  1.ª atención {agg['time_to_first_attention']['mean']} min  ERRORES {agg['errors']}")


def _scores(results: list[dict[str, Any]], key: str = "score") -> list[float]:
    return [r["metrics"][key] for r in results]


# ---------------------------------------------------------------------------- run / compare

def cmd_run(a: argparse.Namespace) -> int:
    cases = load_cases(a.cases, a.n, a.offset)
    fp0 = loaded_fingerprint()
    lessons = load_lessons(a.playbook) if a.agent == "mando" else None
    t0 = time.time()
    results = run_many(cases, AgentFactory(a.agent, lessons), a.workers, a.chaos, a.label, a.budget, a.lookahead, detail=True)
    dt = time.time() - t0
    assert_same_cases({a.agent: results}, cases)
    agg = M.aggregate(results)
    print(_line(f"{a.agent} · caos={a.chaos}", agg))
    print(f"{len(cases)} casos en {dt:.1f} s ({len(cases) / max(dt, 1e-9):.0f} casos/s) · huella {fp0}")
    _guard(fp0, "run")
    _write(f"run_{a.label or a.agent}.json", {"code": fp0, "agent": a.agent, "chaos": a.chaos, "cases": str(a.cases),
                                              "seconds": round(dt, 2), "aggregate": agg, "by_family": M.by_family(results)}, "run")
    return 0


def _paired(x: list[dict[str, Any]], y: list[dict[str, Any]]) -> dict[str, Any]:
    out = M.paired_diff(_scores(x), _scores(y))
    out["world_score"] = M.paired_diff(_scores(x, "world_score"), _scores(y, "world_score"))
    return out


_PAIRS = (("mando", "baseline"), ("mando", "baseline_plus"), ("mando_learned", "mando"), ("mando_learned", "baseline"),
          ("mando_twin", "mando"), ("baseline_plus", "baseline"))


def _compare(cases: list[dict[str, Any]], a: argparse.Namespace, chaos: str, arms: list[tuple[str, AgentFactory]],
             save: bool = False) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    fp0 = loaded_fingerprint()
    runs: dict[str, list[dict[str, Any]]] = {}
    out: dict[str, Any] = {"code": fp0, "n": len(cases), "chaos": chaos, "budget": a.budget, "lookahead": a.lookahead, "agents": {}}
    for name, factory in arms:
        t0 = time.time()
        runs[name] = run_many(cases, factory, a.workers, chaos, f"compare-{chaos}-{name}" if save else None,
                              a.budget, a.lookahead, detail=True)
        agg = M.aggregate(runs[name])
        agg["seconds"] = round(time.time() - t0, 2)
        out["agents"][name] = {"aggregate": agg, "by_family": M.by_family(runs[name])}
        print(_line(AGENT_ES.get(name, name), agg))
    out["case_signature"] = assert_same_cases(runs, cases)     # mismos casos y semillas en TODOS los brazos, o se aborta
    out["errors"] = {n: [{"case_id": r["case_id"], "error": r.get("error")} for r in rs if r["metrics"].get("run_error")]
                     for n, rs in runs.items()}
    out["paired"] = {f"{x}_minus_{y}": _paired(runs[x], runs[y]) for x, y in _PAIRS if x in runs and y in runs}
    _guard(fp0, "compare")
    return out, runs


def _arms(learned: list[dict[str, Any]]) -> list[tuple[str, AgentFactory]]:
    arms = [("baseline", AgentFactory("baseline")), ("baseline_plus", AgentFactory("baseline_plus")),
            ("mando", AgentFactory("mando", []))]
    if learned:
        arms.append(("mando_learned", AgentFactory("mando", learned)))
    return arms


def cmd_compare(a: argparse.Namespace) -> int:
    cases = load_cases(a.cases, a.n, a.offset)
    learned = load_lessons("learned")
    out, runs = _compare(cases, a, a.chaos, _arms(learned), a.save)
    out.update(cases=str(a.cases), n_lessons=len(learned))
    by_id = {c["id"]: c for c in cases}
    out["top_failures"] = {name: top_failures(runs[name], by_id, 10) for name in runs if name.startswith("mando")}
    p = out["paired"]["mando_minus_baseline"]
    print(f"Mando − lista fija, pareado (mismos casos y semillas): {p['mean']:+.2f} IC95 {p['ci']} (N={p['n']}; "
          f"mejor en {p['better']}, peor en {p['worse']}) · huella {out['code']}")
    name = a.out or ("compare.json" if a.chaos == "none" else f"compare_{a.chaos}.json")
    print(f"escrito {_write(name, out, 'compare')}")
    return 0


# ---------------------------------------------------------------------------- headline

def cmd_headline(a: argparse.Namespace) -> int:
    """El número que aguanta: Mando (SIN lecciones) − lista fija, pareado, sin adversario y con Caos."""
    fp0 = loaded_fingerprint()
    arms = [("baseline", AgentFactory("baseline")), ("mando", AgentFactory("mando", []))]
    out: dict[str, Any] = {"code": fp0, "what": "Mando sin lecciones − lista fija; diferencia pareada en los mismos casos y semillas"}
    for key, path, n, chaos in (("train", a.train, a.n, "none"), ("heldout", a.heldout, a.n, "none"),
                                ("train_smart_chaos", a.train, a.n_chaos, "smart")):
        cases = load_cases(path, n)
        print(f"--- {key} · N={len(cases)} · caos={chaos}")
        res, _ = _compare(cases, a, chaos, arms)
        p = res["paired"]["mando_minus_baseline"]
        ag = {k: res["agents"][k]["aggregate"] for k in ("mando", "baseline")}
        out[key] = {"n": len(cases), "cases": str(path), "chaos": chaos, "budget": a.budget if chaos != "none" else 0,
                    "case_signature": res["case_signature"],
                    "mando": ag["mando"]["score"], "baseline": ag["baseline"]["score"],
                    "mando_world": ag["mando"]["world_score"], "baseline_world": ag["baseline"]["world_score"],
                    "critical_failed": {k: [ag[k]["critical_failed_total"], ag[k]["critical_total"]] for k in ag},
                    "errors": {k: ag[k]["errors"] for k in ag},
                    "paired_score": {k: p[k] for k in ("n", "mean", "ci", "level", "better", "worse", "evidence")},
                    "paired_world_score": p["world_score"]}
        print(f"    TITULAR {key}: Mando − lista fija = {p['mean']:+.2f} IC95 {p['ci']} (N={p['n']}) · solo-mundo "
              f"{p['world_score']['mean']:+.2f} IC95 {p['world_score']['ci']} · huella {fp0}")
    out["note"] = getattr(a, "note", "") or ""
    print(f"escrito {_write(getattr(a, 'name', None) or 'headline.json', out, 'headline')}")
    return 0


# ---------------------------------------------------------------------------- learn / curve

def _fold(case_id: str, round_no: int) -> int:
    """Mitad de análisis (0) o de validación (1). Por hash: el generador recorre los tipos en rueda y un corte
    par/impar deja tipos enteros en una sola mitad."""
    return zlib.crc32(f"{case_id}:{round_no}".encode()) % 2


TRACKS = {  # pista -> (bases de lección admitidas, métrica con que se valida)
    "mundo": (("world", "operator"), "world_score"),
    "todo": (("world", "operator", "grader"), "score"),
}


def _vs0(tr: list, he: list, tr0: list, he0: list) -> dict[str, Any]:
    return {split: {k: M.paired_diff(_scores(x, k), _scores(x0, k)) for k in ("score", "world_score")}
            for split, x, x0 in (("train", tr, tr0), ("heldout", he, he0))}


def cmd_learn(a: argparse.Namespace) -> int:
    train, held = load_cases(a.train, a.n_train), load_cases(a.heldout, a.n_heldout)
    fp0 = loaded_fingerprint()
    print(f"train N={len(train)} · heldout N={len(held)} (heldout nunca se usa para aprender) · huella {fp0}")
    ref, sig = {}, {}
    for name in ("baseline", "baseline_plus"):
        rt, rh = run_many(train, AgentFactory(name), a.workers), run_many(held, AgentFactory(name), a.workers)
        sig = {"train": assert_same_cases({name: rt}, train), "heldout": assert_same_cases({name: rh}, held)}
        ref[name] = {"train": M.aggregate(rt), "heldout": M.aggregate(rh)}

    def measure(playbook: list[dict[str, Any]], tag: str) -> tuple[list, list]:
        tr = run_many(train, AgentFactory("mando", playbook), a.workers, detail=True)
        he = run_many(held, AgentFactory("mando", playbook), a.workers, detail=False)
        assert_same_cases({f"mando {tag} train": tr}, train)
        assert_same_cases({f"mando {tag} heldout": he}, held)
        return tr, he

    tr0, he0 = measure([], "ronda 0")
    out: dict[str, Any] = {"code": fp0, "case_signature": sig, "train": str(a.train), "heldout": str(a.heldout),
                           "n_train": len(train), "n_heldout": len(held),
                           "reference": {k: {s: {m: v[s][m] for m in ("score", "world_score", "errors", "n")} for s in v}
                                         for k, v in ref.items()},
                           "tracks": {}}
    final_runs: dict[str, list[dict[str, Any]]] = {}
    for track, (bases, metric) in TRACKS.items():
        print(f"=== pista «{track}»: lecciones de {', '.join(bases)}; se valida con {metric}")
        reviewer = Reviewer("mando", workers=a.workers, metric=metric, bases=bases)
        playbook: list[dict[str, Any]] = []
        rounds: list[dict[str, Any]] = []
        tr, he = tr0, he0
        for r in range(a.rounds + 1):
            _guard(fp0, f"learn, pista {track}, ronda {r}")
            if r:
                tr, he = measure(playbook, f"ronda {r}")
            row: dict[str, Any] = {"round": r, "code": fp0, "n_lessons": len(playbook), "lesson_ids": [l["id"] for l in playbook],
                                   "train": M.aggregate(tr), "heldout": M.aggregate(he),
                                   "train_by_family": M.by_family(tr), "heldout_by_family": M.by_family(he),
                                   "vs_round0": _vs0(tr, he, tr0, he0)}
            rounds.append(row)
            d = row["vs_round0"]["heldout"][metric]
            print(f"ronda {r}: {len(playbook):2d} lecciones · train {row['train'][metric]['mean']:.2f} · heldout {row['heldout'][metric]['mean']:.2f} "
                  f"({metric}; heldout vs ronda 0: {d['mean']:+.2f} IC95 {d['ci']}, N={d['n']}) · críticos fallidos "
                  f"{row['train']['critical_failed_total']}/{row['train']['critical_total']} y "
                  f"{row['heldout']['critical_failed_total']}/{row['heldout']['critical_total']} · inseguras "
                  f"{row['train']['unsafe_total']}+{row['heldout']['unsafe_total']} · ERRORES {row['train']['errors']}+{row['heldout']['errors']}")
            if r == a.rounds:
                break
            A = [c for c in train if _fold(c["id"], r) == 0]
            B = [c for c in train if _fold(c["id"], r) == 1]
            rev = reviewer.review(tr, A, B, playbook, r + 1)
            row["review"] = {"analysis_n": len(A), "validation_n": len(B), "patterns": rev["n_patterns"],
                             "candidates": rev["n_candidates"], "accepted": len(rev["new"]), "verdicts": rev["verdicts"]}
            print(f"         revisor: {rev['n_patterns']} patrones (análisis N={len(A)}) → {rev['n_candidates']} candidatas → "
                  f"{len(rev['new'])} aceptadas (validación N={len(B)})")
            for l in rev["new"]:
                print(f"           + {l['id']} [{l['basis']}] (evidencia N={l['evidence_n']}): {l['text']}")
            if not rev["new"]:
                print("         sin lecciones nuevas: el manual ya no cambia; se paran las rondas de esta pista")
                break
            playbook = rev["playbook"]
        final_runs[track] = tr
        out["tracks"][track] = {"metric": metric, "bases": list(bases), "rounds": rounds, "playbook": playbook}
        _write("playbook.learned.json" if track == "todo" else "playbook.learned_world.json", {"code": fp0, "lessons": playbook}, "learn")
    _guard(fp0, "learn (final)")
    n_lessons = len(out["tracks"]["todo"]["playbook"])
    locked = regression.lock_fixed(train, tr0, final_runs["todo"], "mando",
                                   f"arreglado por el manual aprendido ({n_lessons} lecciones), huella {fp0}") if n_lessons else []
    reg = regression.regress(lessons=out["tracks"]["todo"]["playbook"])
    out.update(locked=locked, regression={k: reg[k] for k in ("n", "ok", "broken", "obsolete", "world")})
    _write("learn.json", out, "learn")
    print(f"regresión: {len(locked)} casos bloqueados ahora; {reg['n']} en total; {'todos pasan' if reg['ok'] else 'ROTOS: ' + str(len(reg['broken']))}")
    return cmd_curve(a)


def _check_learn(learn: dict[str, Any]) -> None:
    for track, t in learn["tracks"].items():
        for r in t["rounds"]:
            if r["train"]["n"] != learn["n_train"] or r["heldout"]["n"] != learn["n_heldout"]:
                raise SystemExit(f"ABORTADO: pista {track}, ronda {r['round']}: N={r['train']['n']}/{r['heldout']['n']} y se esperaban "
                                 f"{learn['n_train']}/{learn['n_heldout']}.")
            if r.get("code") != learn["code"]:
                raise SystemExit(f"ABORTADO: pista {track}, ronda {r['round']}: huella {r.get('code')} ≠ {learn['code']}. "
                                 "Una curva entre versiones distintas del código no es una curva de aprendizaje.")


def _verdict(d: dict[str, Any]) -> str:
    if d["evidence"] and d["mean"] > 0:
        return "hay evidencia de mejora"
    if d["evidence"] and d["mean"] < 0:
        return "EMPEORA"
    return "NO HAY EVIDENCIA DE APRENDIZAJE (el IC incluye el 0)"


def cmd_curve(a: argparse.Namespace) -> int:
    learn = _read("learn.json")
    if learn is None:
        print("no hay learn.json: ejecuta antes `learn`", file=sys.stderr)
        return 1
    _check_learn(learn)

    def pick(agg: dict[str, Any]) -> dict[str, Any]:
        o = {k: {m: agg[k][m] for m in ("n", "mean", "median", "p90", "ci95")}
             for k in ("score", "world_score", "time_to_first_attention", "minutes_over_5", "wasted_dispatches")}
        o.update(n=agg["n"], errors=agg["errors"], critical_failed=agg["critical_failed_total"], critical_total=agg["critical_total"],
                 critical_failed_rate=agg["critical_failed_rate"], unsafe_actions=agg["unsafe_total"])
        return o

    curve = {"code": learn["code"], "case_signature": learn["case_signature"], "n_train": learn["n_train"],
             "n_heldout": learn["n_heldout"], "reference": learn["reference"],
             "note": "score = fórmula completa; world_score = solo resultados del mundo (sin expected.must/must_not). "
                     "Pista «mundo»: sin lecciones de ajuste al corrector. vs_round0 = diferencia pareada con IC95.",
             "tracks": {}}
    for track, t in learn["tracks"].items():
        last = t["rounds"][-1]["vs_round0"]
        curve["tracks"][track] = {
            "metric": t["metric"], "bases": t["bases"],
            "verdict": {split: {k: _verdict(last[split][k]) for k in last[split]} for split in last},
            "rounds": [{"round": r["round"], "n_lessons": r["n_lessons"], "train": pick(r["train"]), "heldout": pick(r["heldout"]),
                        "vs_round0": r["vs_round0"],
                        "by_family": {"train": r["train_by_family"], "heldout": r["heldout_by_family"]}} for r in t["rounds"]]}
    print(f"escrito {_write('curve.json', curve, 'curve')}")
    return 0


# ---------------------------------------------------------------------------- load (degradación con la carga)

def _load_level(case: dict[str, Any]) -> int:
    """Frentes simultáneos del guion: `meta` si lo trae; si no, máximo de incidentes con ventana [t, plazo] solapada."""
    meta = case.get("meta", {})
    for k in ("load", "max_concurrent", "load_level", "simultaneous"):
        if isinstance(meta.get(k), int):
            return meta[k]
    spans = []
    for ev in case.get("events", []):
        inc = ev.get("incident") if ev.get("kind") == "incident" else None
        if inc and not ev.get("cond"):
            t0 = int(ev.get("t", 0))
            dl = inc.get("deadline")
            spans.append((t0, int(dl) if dl and dl > t0 else t0 + 15))
    return max((sum(1 for s, e in spans if s <= t <= e) for t, _ in spans), default=0)


def _has_surprise(case: dict[str, Any]) -> bool:
    return case.get("meta", {}).get("surprise_t") is not None


def _waiting_choice(result: dict[str, Any], case: dict[str, Any]) -> float | None:
    """¿Eligió bien a quién dejar esperando? Fracción de parejas de incidentes del guion de DISTINTO escalón de
    prioridad, abiertos a la vez y que compiten por el mismo tipo de recurso, en las que el prioritario no esperó más
    que el otro (o fue atendido antes). Escalones: `expected.priority_tiers`; si no, `expected.priority`; si no, gravedad."""
    incs = result.get("detail", {}).get("incidents", {})
    exp = case.get("expected", {})
    ids = [i for i in incs if incs[i].get("origin") == "case" and incs[i].get("needs")]
    if exp.get("priority_tiers"):
        rank = {iid: n for n, tier in enumerate(exp["priority_tiers"]) for iid in tier}
    elif exp.get("priority"):
        rank = {iid: n for n, iid in enumerate(exp["priority"])}
    else:
        rank = {iid: -incs[iid]["severity"] for iid in ids}
    ids = [i for i in ids if i in rank]
    end, good, total = 10 ** 6, 0, 0
    for x in ids:
        for y in ids:
            ax, ay = incs[x], incs[y]
            if rank[x] >= rank[y] or not set(ax["needs"]) & set(ay["needs"]):
                continue
            if ax["t_open"] > (ay.get("deadline") or end) or ay["t_open"] > (ax.get("deadline") or end):
                continue
            tx = ax["t_first_attention"] if ax.get("t_first_attention") is not None else end
            ty = ay["t_first_attention"] if ay.get("t_first_attention") is not None else end
            total += 1
            good += 1 if (tx - ax["t_open"]) <= (ty - ay["t_open"]) or tx <= ty else 0
    return good / total if total else None


def cmd_load(a: argparse.Namespace) -> int:
    path = Path(a.cases)
    if not path.exists():
        print(f"no existe {path}: el generador de casos aún no lo ha escrito", file=sys.stderr)
        return 1
    cases = load_cases(path, a.n)
    low = [c for c in load_cases(a.low, a.n_low) if 1 <= _load_level(c) <= 4] if a.low and Path(a.low).exists() else []
    cases += low       # niveles 1–4: casos de train, con el nivel calculado del guion (ventanas [t, plazo] solapadas)
    fp0 = loaded_fingerprint()
    arms = [("baseline", AgentFactory("baseline")), ("baseline_plus", AgentFactory("baseline_plus")), ("mando", AgentFactory("mando", []))]
    twin_ok = AgentFactory("mando", [], twin=True).twin_available()
    if twin_ok:
        arms.append(("mando_twin", AgentFactory("mando", [], twin=True)))
    runs = {name: run_many(cases, f, a.workers, detail=True) for name, f in arms}
    sig = assert_same_cases(runs, cases)
    out: dict[str, Any] = {"code": fp0, "case_signature": sig, "cases": str(path), "n": len(cases), "twin_available": twin_ok,
                           "n_load_file": len(cases) - len(low), "n_low_from_train": len(low),
                           "note": "level = frentes simultáneos del guion (meta.load en load.jsonl; en los casos de train que cubren "
                                   "los niveles 1–4, calculado de las ventanas [t, plazo]); imprevisto = meta.surprise_t presente", "arms": {}}
    levels = sorted({_load_level(c) for c in cases})
    for name, rs in runs.items():
        rows = []
        for lvl in levels:
            for label, want in (("todos", None), ("sin imprevisto", False), ("con imprevisto", True)):
                sel = [(c, r) for c, r in zip(cases, rs) if _load_level(c) == lvl and (want is None or _has_surprise(c) == want)]
                if not sel:
                    continue
                ms = [r["metrics"] for _, r in sel]
                rows.append({"level": lvl, "surprise": label, "n": len(sel), "errors": sum(1 for m in ms if m.get("run_error")),
                             "critical_failed": sum(m["critical_failed"] for m in ms), "critical_total": sum(m["n_critical"] for m in ms),
                             "critical_failed_per_case": M.describe([m["critical_failed"] for m in ms], 500),
                             "cases_with_critical_failed": sum(1 for m in ms if m["critical_failed"]),
                             "world_score": M.describe([m["world_score"] for m in ms], 500),
                             "time_to_first_attention": M.describe([m["time_to_first_attention"] for m in ms], 500),
                             "waiting_choice_ok": M.describe([_waiting_choice(r, c) for c, r in sel], 500)})
        out["arms"][name] = {"aggregate": M.aggregate(rs), "by_level": rows}
        print(f"--- {AGENT_ES.get(name, name)}")
        for row in rows:
            print(f"   {row['level']} frentes · {row['surprise']:15s} N={row['n']:<4d} críticos fallidos {row['critical_failed']}/{row['critical_total']} · "
                  f"solo-mundo {row['world_score']['mean']} {row['world_score']['ci95']} · 1.ª atención {row['time_to_first_attention']['mean']} min · "
                  f"deja esperando a quien toca {row['waiting_choice_ok']['mean']} (N={row['waiting_choice_ok']['n']}) · errores {row['errors']}")

    def first_failure(name: str) -> int | None:
        return next((r["level"] for r in out["arms"][name]["by_level"] if r["surprise"] == "todos" and r["critical_failed"] > 0), None)

    def cost(name: str) -> dict[str, Any]:
        rs = runs[name]
        return {"with_surprise": M.describe([r["metrics"]["world_score"] for c, r in zip(cases, rs) if _has_surprise(c)], 500),
                "without_surprise": M.describe([r["metrics"]["world_score"] for c, r in zip(cases, rs) if not _has_surprise(c)], 500)}

    out["first_level_with_critical_failed"] = {n: first_failure(n) for n in runs}
    out["surprise_cost"] = {n: cost(n) for n in runs}
    if twin_ok:
        out["twin_gain"] = _paired(runs["mando_twin"], runs["mando"])
    top = max(levels) if levels else 0

    def phrase(who: str, k: int | None) -> str:
        if k is None:
            return f"{who} no falla ningún crítico en ningún nivel medido (hasta {top} frentes)"
        return f"{who} mantiene 0 críticos fallidos hasta {k - 1} frentes y empieza a fallar en {k}" if k > min(levels) \
            else f"{who} ya falla críticos en el nivel más bajo medido ({k} frentes)"

    f = out["first_level_with_critical_failed"]
    out["sentence"] = f"{phrase('Mando', f['mando'])}; {phrase('la lista fija', f['baseline'])} (N={len(cases)}, huella {fp0})."
    print(out["sentence"])
    _guard(fp0, "load")
    print(f"escrito {_write('load.json', out, 'load')}")
    return 0


# ---------------------------------------------------------------------------- day2 (memoria → parámetros → medición)

def cmd_day2(a: argparse.Namespace) -> int:
    from . import day2 as D
    from motor.mando import memory as mem, tuning
    decisions = json.loads(Path(a.decisions).read_text(encoding="utf-8")) if a.approve == "file" else None
    if a.approve == "file" and not isinstance(decisions, dict):
        raise SystemExit("--decisions debe ser un JSON {\"C-01\": true, \"C-02\": false, …}")
    t0 = time.time()
    out, art = D.day2(load_cases(a.train, 2 * a.n), load_cases(a.heldout, a.n), a.n, workers=a.workers, approve=a.approve,
                      decisions=decisions, festival_seed=a.festival_seed, reference=not a.no_reference)
    out["seconds"] = round(time.time() - t0, 1)
    label = a.label or "day2"
    source = {"code": out["code"], "n_cases": out["day1"]["n"], "case_signature": out["day1"]["case_signature"],
              "festival_seed": a.festival_seed}
    _write("memory.day1.json", mem.dumps({**art["memory"].to_dict(), "source": source,
                                          "n_by_parameter": art["memory"].n_by_parameter()}), label)
    _write("params.proposed.json", art["proposals"].to_dict(), label)
    _write("params.approved.json", art["revised"].to_dict(), label)
    if not a.no_install and not os.environ.get("MOTOR_HARNESS_FROZEN"):
        # copia de trabajo para Mando y la pantalla: `Mando(params="approved")` / `Params.load()` leen de aquí
        art["memory"].save(mem.DEFAULT_PATH, source)
        art["proposals"].save(tuning.PROPOSED_PATH)
        art["proposals"].write_approved(tuning.APPROVED_PATH)
    for c in out["proposals"]["changes"]:
        print(f"  {c['id']} [{c['status']}] {c['text']}")
    for split, s in out["splits"].items():
        print(f"--- {s['sentence']}")
    print(f"escrito {_write('day2.json', out, label)} · huella {out['code']} · {out['seconds']} s")
    return cmd_report(a)


# ---------------------------------------------------------------------------- pick (casos para elegir en cámara)

def cmd_pick(a: argparse.Namespace) -> int:
    fp0 = loaded_fingerprint()
    pool = [c for c in load_cases(a.cases) if int(c.get("difficulty", 0)) >= 4]
    arms = _arms(load_lessons("learned"))
    runs = {name: run_many(pool, f, a.workers) for name, f in arms}
    assert_same_cases(runs, pool)
    # Mando además con otras dos semillas: en la demo las personas no contestan como SimComms
    extra = [run_many([dict(c, seed=int(c.get("seed", 0)) + k) for c in pool], AgentFactory("mando", []), a.workers) for k in (1, 2)]
    ok = []
    for i in range(len(pool)):
        every = [runs[n][i]["metrics"] for n in runs] + [e[i]["metrics"] for e in extra]
        mando = [runs[n][i]["metrics"] for n in runs if n.startswith("mando")] + [e[i]["metrics"] for e in extra]
        if any(m.get("run_error") for m in every) or any(m["critical_failed"] or m["unsafe_actions"] for m in mando):
            continue
        ok.append(i)
    ok.sort(key=lambda i: zlib.crc32(pool[i]["id"].encode()))      # orden por hash del id: NO por puntuación
    rows = [{"n": k + 1, "case_id": pool[i]["id"], "seed": pool[i].get("seed"), "difficulty": pool[i]["difficulty"],
             "families": pool[i]["families"], "primary_type": pool[i].get("meta", {}).get("primary_type"),
             "incidents": sum(1 for e in pool[i]["events"] if e.get("kind") == "incident"), "duration_min": pool[i]["duration_min"],
             "score": {n: runs[n][i]["metrics"]["score"] for n in runs}} for k, i in enumerate(ok[: a.n])]
    out = {"code": fp0, "cases": str(a.cases), "pool_n": len(pool), "passed_n": len(ok), "listed_n": len(rows),
           "filter": "heldout, dificultad 4–5; sin errores en ningún brazo; Mando (sin lecciones, con manual aprendido si lo hay, y con 2 "
                     "semillas más) sin críticos fallidos ni acciones inseguras. Orden por hash del id, no por puntuación.",
           "disclosure": f"Lista PREFILTRADA: pasan el filtro {len(ok)} de {len(pool)} casos heldout de dificultad 4–5. Si en cámara se dice "
                         "«caso nunca visto elegido por alguien de fuera», hay que decir también que se elige entre casos que Mando ya ha "
                         "corrido sin fallar críticos (nunca usados para aprender ni para ajustar nada).",
           "rows": rows}
    md = [f"# Casos heldout para elegir en cámara (huella {fp0})", "", out["disclosure"], "",
          "| N.º | Caso | Dificultad | Familias | Tipo principal | Incidentes | Lista fija | Mando |", "|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['n']} | {r['case_id']} | {r['difficulty']} | {', '.join(r['families'])} | {r['primary_type']} | {r['incidents']} | "
           f"{r['score']['baseline']:.0f} | {r['score']['mando']:.0f} |" for r in rows]
    _write("pick.json", out, "pick")
    print("\n".join(md))
    print(f"\nescrito {_write('pick.md', chr(10).join(md), 'pick')}")
    _guard(fp0, "pick")
    return 0


# ---------------------------------------------------------------------------- report

def _num(x: Any, nd: int = 2) -> str:
    return "—" if x is None else f"{x:.{nd}f}".replace(".", ",")


def _ci(ci: Any) -> str:
    return "—" if not ci else f"[{_num(ci[0])} – {_num(ci[1])}]"


def _check_compare(name: str, c: dict[str, Any]) -> None:
    for arm, d in c["agents"].items():
        if d["aggregate"]["n"] != c["n"]:
            raise SystemExit(f"ABORTADO: en {name} el brazo «{arm}» tiene N={d['aggregate']['n']} y no N={c['n']}.")
    if not c.get("case_signature"):
        raise SystemExit(f"ABORTADO: {name} no lleva la firma de casos y semillas: repite `compare`.")


def _compare_table(cmp: dict[str, Any]) -> list[str]:
    rows = ["| Agente | N | Errores | Score | IC 95 % | Solo-mundo | IC 95 % | Críticos fallidos | Inseguras | 1.ª atención (min) | Min·zona > 5/m² | Desperdiciados | `must` |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, d in cmp["agents"].items():
        g = d["aggregate"]
        rows.append(f"| {AGENT_ES.get(name, name)} | {g['n']} | {g['errors']} | {_num(g['score']['mean'])} | {_ci(g['score']['ci95'])} | "
                    f"{_num(g['world_score']['mean'])} | {_ci(g['world_score']['ci95'])} | "
                    f"{g['critical_failed_total']} de {g['critical_total']} ({_num(100 * (g['critical_failed_rate'] or 0), 1)} %) | {g['unsafe_total']} | "
                    f"{_num(g['time_to_first_attention']['mean'])} | {_num(g['minutes_over_5']['mean'])} | {_num(g['wasted_dispatches']['mean'])} | "
                    f"{_num(100 * (g['must_rate']['mean'] or 0), 1)} % |")
    return rows


def cmd_report(a: argparse.Namespace) -> int:
    cmp, learn, head, load = _read("compare.json"), _read("learn.json"), _read("headline.json"), _read("load.json")
    d2 = _read("day2.json")
    codes = {k: v.get("code") for k, v in (("compare", cmp), ("learn", learn), ("headline", head), ("load", load), ("day2", d2)) if v}
    md: list[str] = ["# Banco de pruebas de Mando — informe", "",
                     f"Generado por `python3 -m motor.harness report`. Huellas del código medido: {codes}. Huella en disco al generar: {code_fingerprint()}.",
                     "Toda cifra lleva su N. Es simulación, no dato de campo. Todos los brazos de cada tabla corren EXACTAMENTE los mismos casos "
                     "y semillas (se comprueba y se aborta si no). Una ejecución en la que revienta el agente o el puntuador no sale del N: "
                     "cuenta con score 0 y aparece en «Errores».",
                     "`score`: fórmula completa (`metrics.py`, fijada antes de medir). `solo-mundo` (`world_score`): la misma sin nada que dependa "
                     "de `expected.must`/`must_not` del generador de casos.", ""]
    if len(set(codes.values())) > 1:
        md += ["**AVISO: las secciones de este informe se midieron con huellas de código distintas; no mezclar cifras entre secciones.**", ""]
    summary: dict[str, Any] = {"codes": codes}
    if head:
        md += [f"## Titular reproducible (`python3 -m motor.harness headline`, huella {head['code']})", "",
               "| Conjunto | N | Mando | Lista fija | Diferencia pareada (score) | IC 95 % | Diferencia pareada (solo-mundo) | IC 95 % | Críticos fallidos Mando / lista | Errores |",
               "|---|---|---|---|---|---|---|---|---|---|"]
        for key, title in (("train", "train, sin adversario"), ("heldout", "heldout, sin adversario"),
                           ("train_smart_chaos", "train, con Caos (3 golpes)")):
            h = head.get(key)
            if h:
                cf = h["critical_failed"]
                md.append(f"| {title} | {h['n']} | {_num(h['mando']['mean'])} | {_num(h['baseline']['mean'])} | **{_num(h['paired_score']['mean'])}** | "
                          f"{_ci(h['paired_score']['ci'])} | {_num(h['paired_world_score']['mean'])} | {_ci(h['paired_world_score']['ci'])} | "
                          f"{cf['mando'][0]} de {cf['mando'][1]} / {cf['baseline'][0]} de {cf['baseline'][1]} | {h['errors']['mando']} / {h['errors']['baseline']} |")
        md.append("")
        summary["headline"] = head
    for key, title in (("compare.json", "Train, sin adversario"), ("compare_heldout.json", "HELDOUT (nunca visto), sin adversario"),
                       ("compare_random.json", "Train, con adversario al azar"), ("compare_smart.json", "Train, con adversario inteligente (Caos)")):
        c = _read(key)
        if not c:
            continue
        _check_compare(key, c)
        extra = "" if c["chaos"] == "none" else f", presupuesto {c['budget']} golpes"
        md += [f"## Comparación · {title} (N={c['n']}, mismas semillas{extra}, huella {c['code']})", "", *_compare_table(c), ""]
        for k, p in c["paired"].items():
            x, y = k.split("_minus_")
            md.append(f"- {AGENT_ES.get(x, x)} − {AGENT_ES.get(y, y)}, pareado: **{_num(p['mean'])}** IC 95 % {_ci(p['ci'])}; solo-mundo "
                      f"{_num(p['world_score']['mean'])} {_ci(p['world_score']['ci'])} (N={p['n']}; mejor en {p['better']}, peor en {p['worse']}).")
        md.append("")
        summary[key.replace(".json", "")] = {
            "n": c["n"], "chaos": c["chaos"], "code": c["code"], "paired": c["paired"],
            "agents": {n: {"label": AGENT_ES.get(n, n), **{m: d["aggregate"][m] for m in
                           ("n", "errors", "score", "world_score", "critical_failed_total", "critical_total", "unsafe_total",
                            "time_to_first_attention", "wasted_dispatches", "minutes_over_5")}} for n, d in c["agents"].items()}}
    if cmp:
        md += ["## Por familia de crisis (score medio, train sin adversario; N entre paréntesis)", "",
               "| Familia | " + " | ".join(AGENT_ES.get(n, n) for n in cmp["agents"]) + " |", "|---|" + "---|" * len(cmp["agents"])]
        for f in sorted({f for d in cmp["agents"].values() for f in d["by_family"]}):
            md.append(f"| {f} | " + " | ".join(f"{_num(d['by_family'].get(f, {}).get('mean'))} ({d['by_family'].get(f, {}).get('n', 0)})"
                                               for d in cmp["agents"].values()) + " |")
        md += ["", "## Los fallos más frecuentes de Mando (sin lecciones)", "",
               "| # | Patrón | Tipo (según Mando) | Detalle | Casos |", "|---|---|---|---|---|"]
        for i, f in enumerate(cmp["top_failures"].get("mando", [])[:10], 1):
            md.append(f"| {i} | {f['pattern']} | {f['agent_type'] or f['family'] or '—'} | {f['detail']} | {f['n_cases']} de {cmp['n']} (p. ej. {', '.join(f['examples'])}) |")
        md.append("")
        summary["top_failures"] = cmp["top_failures"].get("mando", [])[:10]
    if learn:
        _check_learn(learn)
        md += [f"## Aprendizaje (train N={learn['n_train']}, heldout N={learn['n_heldout']}, huella {learn['code']}; heldout nunca se usa para aprender)", "",
               "Dos pistas. **«mundo»**: solo lecciones que salen de resultados del mundo o de vetos de la persona, validadas con `solo-mundo`. "
               "**«todo»**: además, lecciones que recuperan reglas `must` del generador («notify X»): eso es AJUSTE AL CORRECTOR y se enseña aparte. "
               "Una lección entra solo si el IC 99 % de la diferencia pareada en validación excluye el 0.", ""]
        summary["learning"] = {"code": learn["code"], "n_train": learn["n_train"], "n_heldout": learn["n_heldout"], "tracks": {}}
        for track, t in learn["tracks"].items():
            md += [f"### Pista «{track}» (valida con `{t['metric']}`)", "",
                   "| Ronda | Lecciones | Train score | Train solo-mundo | Heldout score | Heldout solo-mundo | Heldout − ronda 0, pareado (solo-mundo) | IC 95 % | Críticos fallidos train / heldout | Errores |",
                   "|---|---|---|---|---|---|---|---|---|---|"]
            for r in t["rounds"]:
                tr, he, d = r["train"], r["heldout"], r["vs_round0"]["heldout"]["world_score"]
                md.append(f"| {r['round']} | {r['n_lessons']} | {_num(tr['score']['mean'])} | {_num(tr['world_score']['mean'])} | {_num(he['score']['mean'])} | "
                          f"{_num(he['world_score']['mean'])} | {_num(d['mean'])} | {_ci(d['ci'])} | {tr['critical_failed_total']} de {tr['critical_total']} / "
                          f"{he['critical_failed_total']} de {he['critical_total']} | {tr['errors']}+{he['errors']} |")
            last = t["rounds"][-1]["vs_round0"]
            md.append("")
            for split in ("train", "heldout"):
                for k in ("world_score", "score"):
                    d = last[split][k]
                    md.append(f"- {split}, `{k}`, última ronda − ronda 0 (pareado, N={d['n']}): {_num(d['mean'])} IC 95 % {_ci(d['ci'])} → **{_verdict(d)}**.")
            he0, heN = t["rounds"][0]["heldout"]["world_score"]["ci95"], t["rounds"][-1]["heldout"]["world_score"]["ci95"]
            md += [f"- Intervalos NO pareados de heldout (solo-mundo): ronda 0 {_ci(he0)}, última {_ci(heN)} → "
                   f"{'SE SOLAPAN' if heN[0] <= he0[1] else 'no se solapan'}.", ""]
            acc = [v for r in t["rounds"] for v in r.get("review", {}).get("verdicts", []) if v["accepted"]]
            rej = [v for r in t["rounds"] for v in r.get("review", {}).get("verdicts", []) if not v["accepted"]]
            if acc:
                md += ["| Id | Origen | Lección | Evidencia (N casos) | Validación |", "|---|---|---|---|---|"]
                md += [f"| {v['lesson']['id']} | {v['lesson']['basis']}{' (ajuste al corrector)' if v['lesson']['basis'] == 'grader' else ''} | "
                       f"{v['lesson']['text']} | {v['lesson']['evidence_n']} | {v['reason']} |" for v in acc]
            md += ["", f"Aceptadas {len(acc)}, rechazadas {len(rej)}. Con decenas de candidatas por ronda, incluso con IC del 99 % cabe alguna aceptación por azar.", ""]
            summary["learning"]["tracks"][track] = {
                "metric": t["metric"], "lessons": [v["lesson"] for v in acc], "rejected": len(rej),
                "verdict": {split: {k: _verdict(last[split][k]) for k in last[split]} for split in last},
                "rounds": [{"round": r["round"], "n_lessons": r["n_lessons"], "train": {m: r["train"][m] for m in ("score", "world_score")},
                            "heldout": {m: r["heldout"][m] for m in ("score", "world_score")}, "vs_round0": r["vs_round0"]} for r in t["rounds"]]}
        ref = learn["reference"]
        md += [f"Referencia: lista fija {_num(ref['baseline']['train']['score']['mean'])} (train) y {_num(ref['baseline']['heldout']['score']['mean'])} (heldout); "
               f"lista fija + {_num(ref['baseline_plus']['train']['score']['mean'])} y {_num(ref['baseline_plus']['heldout']['score']['mean'])}.", ""]
        reg = learn.get("regression", {})
        md += ["## Regresión", "", f"{reg.get('n', 0)} casos bloqueados (fallaban sin lecciones y el manual aprendido los arregla). "
               f"`python3 -m motor.harness regress` los re-ejecuta y falla si alguno vuelve a romperse. Estado: "
               f"{'todos pasan' if reg.get('ok') else 'HAY CASOS ROTOS'}.", ""]
        summary["learning"]["regression"] = reg
    if load:
        md += [f"## Degradación con la carga (N={load['n']}, huella {load['code']})", "", load["sentence"], ""]
        for name, d in load["arms"].items():
            md += [f"### {AGENT_ES.get(name, name)}", "",
                   "| Frentes | Imprevisto | N | Errores | Críticos fallidos | Solo-mundo | IC 95 % | 1.ª atención (min) | Deja esperando a quien toca |",
                   "|---|---|---|---|---|---|---|---|---|"]
            md += [f"| {r['level']} | {r['surprise']} | {r['n']} | {r['errors']} | {r['critical_failed']} de {r['critical_total']} | {_num(r['world_score']['mean'])} | "
                   f"{_ci(r['world_score']['ci95'])} | {_num(r['time_to_first_attention']['mean'])} | {_num(r['waiting_choice_ok']['mean'])} (N={r['waiting_choice_ok']['n']}) |"
                   for r in d["by_level"]]
            md.append("")
        if load.get("twin_gain"):
            g = load["twin_gain"]
            md += [f"Ensayo previo (gemelo sin futuro): Mando con gemelo − Mando sin gemelo, pareado: {_num(g['mean'])} IC 95 % {_ci(g['ci'])}; "
                   f"solo-mundo {_num(g['world_score']['mean'])} {_ci(g['world_score']['ci'])} (N={g['n']}).", ""]
        else:
            md += ["Ensayo previo (gemelo): NO medido: con esta huella no existían `World.twin` o el parámetro `twin` de Mando.", ""]
        summary["load"] = {k: load.get(k) for k in ("code", "n", "sentence", "first_level_with_critical_failed", "surprise_cost",
                                                    "twin_available", "twin_gain")}
    if d2:
        from .day2 import report_section
        md += report_section(d2)
        summary["day2"] = {"code": d2["code"], "n_per_arm": d2["n_per_arm"], "proposals": d2["proposals"]["changes"],
                           "splits": {k: {"sentence": s["sentence"], "compare": s["compare"]} for k, s in d2["splits"].items()}}
    if (OUT_ROOT / "BUGS.md").exists():
        md += ["## Fallos encontrados en otros módulos", "", "Ver `motor/harness/out/BUGS.md`.", ""]
    print(f"escrito {_write('report.md', chr(10).join(md), 'report')}")
    print(f"escrito {_write('summary.json', summary, 'report')}")
    return 0


def cmd_regress(a: argparse.Namespace) -> int:
    res = regression.regress(lessons=load_lessons(a.playbook))
    for r in res["rows"]:
        print(f"{'ok  ' if r['ok'] else 'ROTO'} {r['case_id']}  score {r['score']}  críticos {r['critical_failed']}  inseguras {r['unsafe_actions']}"
              + ("" if r["ok"] else "  ← " + "; ".join(r["broken"])))
    if res["obsolete"]:
        print(f"OBSOLETOS (bloqueados con otra versión del simulador; no se borran ni cuentan): {len(res['obsolete'])}")
    print(f"{res['n']} casos bloqueados vigentes; {'todos pasan' if res['ok'] else str(len(res['broken'])) + ' ROTOS'} · huella {code_fingerprint()}")
    return 0 if res["ok"] else 1


def cmd_all(a: argparse.Namespace) -> int:
    """Todo en UN proceso y una sola huella: headline → learn → compare ×4 → load → pick → report → regress."""
    session(a.label)
    base = dict(workers=a.workers, budget=a.budget, lookahead=a.lookahead, offset=0, save=False)
    cmd_headline(argparse.Namespace(**base, train=a.train, heldout=a.heldout, n=a.n, n_chaos=a.n_chaos))
    cmd_learn(argparse.Namespace(**base, rounds=a.rounds, train=a.train, heldout=a.heldout, n_train=a.n_train, n_heldout=a.n_heldout))
    for chaos, n, cases, name in (("none", a.n, a.train, None), ("none", a.n, a.heldout, "compare_heldout.json"),
                                  ("random", a.n_chaos, a.train, None), ("smart", a.n_chaos, a.train, None)):
        print(f"--- compare · {Path(cases).name} · caos={chaos} · N={n}")
        cmd_compare(argparse.Namespace(**base, cases=cases, n=n, chaos=chaos, out=name))
    if (DATA / "load.jsonl").exists():
        cmd_load(argparse.Namespace(**base, cases=str(DATA / "load.jsonl"), n=None, low=a.train, n_low=600))
    cmd_pick(argparse.Namespace(**base, cases=a.heldout, n=40))
    cmd_report(a)
    return cmd_regress(argparse.Namespace(playbook="learned"))


# ---------------------------------------------------------------------------- código congelado

def preflight(n: int = 6) -> None:
    """Antes de medir nada: unos pocos casos con cada brazo, en serie. Si alguno revienta (p. ej. se congeló el código
    de otro agente a medio editar) se ABORTA sin escribir ninguna cifra: otros procesos leen `out/`."""
    from .runner import run_case
    paths = [p for p in (DATA / "train.jsonl", DATA / "heldout.jsonl", DATA / "load.jsonl") if p.exists()]
    cases = [c for p in paths for c in load_cases(p, n)]
    arms = [AgentFactory("baseline"), AgentFactory("baseline_plus"), AgentFactory("mando", [])]
    if AgentFactory("mando", [], twin=True).twin_available():
        arms.append(AgentFactory("mando", [], twin=True))
    for factory in arms:
        for c in cases:
            try:
                run_case(c, factory, detail=False)
            except Exception as ex:      # noqa: BLE001
                import traceback
                raise SystemExit(f"ABORTADO en la comprobación previa: «{factory.name}» revienta en {c['id']}: {ex!r}\n"
                                 f"{traceback.format_exc()[-1200:]}\nNo se ha escrito ninguna cifra.")
    print(f"comprobación previa: {len(arms)} brazos × {len(cases)} casos sin errores · huella {loaded_fingerprint()}", flush=True)


def _wait_stable(seconds: int, timeout: int = 1200) -> None:
    """Espera a que nadie toque motor/ durante `seconds` segundos seguidos."""
    t0, last, since = time.time(), code_fingerprint(), time.time()
    while time.time() - since < seconds:
        if time.time() - t0 > timeout:
            raise SystemExit(f"ABORTADO: el código no ha estado quieto {seconds} s seguidos en {timeout} s.")
        time.sleep(5)
        now = code_fingerprint()
        if now != last:
            last, since = now, time.time()
            print(f"  … el código sigue cambiando (huella {now}); espero", flush=True)


def _freeze_and_rerun(argv: list[str], code_from: str | None) -> int:
    """Copia el código a out/_frozen/<huella>/motor y se re-ejecuta desde ahí: lo que se mide no puede cambiar
    a mitad aunque alguien edite motor/. `--code-from DIR` toma `mando/` y `world/` de una instantánea."""
    root = HERE.parent
    tmp = OUT_ROOT / "_frozen" / f"tmp-{os.getpid()}"
    dst = tmp / "motor"
    dst.mkdir(parents=True, exist_ok=True)
    for f in ("__init__.py", "contracts.py"):
        shutil.copy2(root / f, dst / f)
    ignore = shutil.ignore_patterns("__pycache__", "out", "runs", "regression", "data", "*.pyc")
    for folder in ("world", "mando", "baseline", "caos", "harness"):
        snap = Path(code_from) / folder if code_from and folder in ("mando", "world") else None
        shutil.copytree(snap if snap is not None and snap.exists() else root / folder, dst / folder, ignore=ignore)
    (tmp / "data").mkdir(exist_ok=True)
    for f in DATA.glob("*.jsonl"):          # los casos también se congelan: el generador puede reescribirlos a mitad
        shutil.copy2(f, tmp / "data" / f.name)
    fp = code_fingerprint(dst)
    final = OUT_ROOT / "_frozen" / f"{fp}-{time.strftime('%H%M%S')}"
    tmp.rename(final)
    env = dict(os.environ, MOTOR_HARNESS_OUT=str(OUT_ROOT), MOTOR_HARNESS_REG=str(regression.REG_DIR), MOTOR_HARNESS_DATA=str(final / "data"),
               MOTOR_HARNESS_RUNS=str(HERE / "runs"), MOTOR_HARNESS_FROZEN=fp)
    print(f"código congelado en {final} (huella {fp})", flush=True)
    return subprocess.run([sys.executable, "-m", "motor.harness", *argv], cwd=final, env=env).returncode


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["forecast"]:
        from .forecast_bench import main as forecast_main
        return forecast_main(argv[1:])
    ap = argparse.ArgumentParser(prog="python3 -m motor.harness", description="Banco de pruebas de Mando")
    ap.add_argument("--freeze", action="store_true", help="medir sobre una copia congelada del código (recomendado)")
    ap.add_argument("--code-from", default=None, help="con --freeze: carpeta con mando/ y world/ de una instantánea")
    ap.add_argument("--wait-stable", type=int, default=0, help="con --freeze: esperar a que motor/ lleve N segundos sin cambios")
    ap.add_argument("--no-preflight", action="store_true", help="saltarse la comprobación previa (no recomendado)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--workers", type=int, default=None)
        p.add_argument("--budget", type=int, default=3)
        p.add_argument("--lookahead", type=int, default=15)

    def sets(p: argparse.ArgumentParser) -> None:
        p.add_argument("--train", default=str(DATA / "train.jsonl"))
        p.add_argument("--heldout", default=str(DATA / "heldout.jsonl"))

    p = sub.add_parser("run"); common(p)
    p.add_argument("--chaos", choices=("none", "random", "smart"), default="none")
    p.add_argument("--agent", choices=("mando", "baseline", "baseline_plus"), default="mando")
    p.add_argument("--cases", default=str(DATA / "train.jsonl")); p.add_argument("--n", type=int, default=None)
    p.add_argument("--offset", type=int, default=0); p.add_argument("--label", default=None)
    p.add_argument("--playbook", default="none", help="none | learned | learned_world | seed | ruta")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("compare"); common(p)
    p.add_argument("--chaos", choices=("none", "random", "smart"), default="none")
    p.add_argument("--cases", default=str(DATA / "train.jsonl")); p.add_argument("--n", type=int, default=None)
    p.add_argument("--offset", type=int, default=0); p.add_argument("--save", action="store_true")
    p.add_argument("--out", default=None, help="nombre del fichero de salida (p. ej. compare_heldout.json)")
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("headline"); common(p); sets(p)
    p.add_argument("--n", type=int, default=1000); p.add_argument("--n-chaos", type=int, default=300)
    p.add_argument("--name", default=None, help="fichero de salida (por defecto headline.json)")
    p.add_argument("--note", default="", help="nota que se guarda con el resultado (p. ej. «Mando antes de quitar la fuga»)")
    p.set_defaults(fn=cmd_headline)

    p = sub.add_parser("learn"); common(p); sets(p)
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument("--n-train", type=int, default=None); p.add_argument("--n-heldout", type=int, default=None)
    p.set_defaults(fn=cmd_learn)

    sub.add_parser("curve").set_defaults(fn=cmd_curve)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    p = sub.add_parser("regress"); p.add_argument("--playbook", default="learned"); p.set_defaults(fn=cmd_regress)

    p = sub.add_parser("load"); common(p)
    p.add_argument("--cases", default=str(DATA / "load.jsonl")); p.add_argument("--n", type=int, default=None)
    p.add_argument("--low", default=str(DATA / "train.jsonl"), help="casos para los niveles 1–4")
    p.add_argument("--n-low", type=int, default=600)
    p.set_defaults(fn=cmd_load)

    p = sub.add_parser("day2"); common(p); sets(p)
    p.add_argument("--n", type=int, default=400, help="casos por brazo (día 1, día 2 de train y heldout): N ≥ 300 para afirmar algo")
    p.add_argument("--approve", choices=("criterion", "all", "none", "file"), default="criterion",
                   help="quién decide los cambios: operador simulado con criterio fijo (N ≥ 5), todo, nada, o un fichero")
    p.add_argument("--decisions", default=None, help="con --approve file: JSON {id de cambio: true|false}")
    p.add_argument("--festival-seed", type=int, default=2026, help="semilla del perfil oculto del recinto")
    p.add_argument("--no-reference", action="store_true", help="no correr el brazo de referencia (Mando sin parámetros)")
    p.add_argument("--no-install", action="store_true", help="no copiar memoria y parámetros aprobados a motor/mando/")
    p.add_argument("--label", default=None)
    p.set_defaults(fn=cmd_day2)

    p = sub.add_parser("pick"); common(p)
    p.add_argument("--cases", default=str(DATA / "heldout.jsonl")); p.add_argument("--n", type=int, default=40)
    p.set_defaults(fn=cmd_pick)

    p = sub.add_parser("all"); common(p); sets(p)
    p.add_argument("--rounds", type=int, default=4); p.add_argument("--n", type=int, default=1000)
    p.add_argument("--n-chaos", type=int, default=300); p.add_argument("--label", default="all")
    p.add_argument("--n-train", type=int, default=None, help="solo para pruebas rápidas: recorta train en `learn`")
    p.add_argument("--n-heldout", type=int, default=None, help="solo para pruebas rápidas: recorta heldout en `learn`")
    p.set_defaults(fn=cmd_all)

    args = ap.parse_args(argv)
    if args.freeze and not os.environ.get("MOTOR_HARNESS_FROZEN"):
        rest, skip = [], False
        for x in argv:
            if skip:
                skip = False
            elif x in ("--code-from", "--wait-stable"):
                skip = True
            elif x != "--freeze" and not x.startswith(("--code-from=", "--wait-stable=")):
                rest.append(x)
        for attempt in range(1, 6):
            if args.wait_stable:
                _wait_stable(args.wait_stable)
            code = _freeze_and_rerun(rest, args.code_from)
            if code != 3 or not args.wait_stable:
                return code
            print(f"la copia congelada no pasa la comprobación previa (intento {attempt}): se espera y se vuelve a congelar", flush=True)
        return 3
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if args.cmd not in ("report", "curve", "regress") and not args.no_preflight:
        try:
            preflight()
        except SystemExit as ex:
            print(ex, file=sys.stderr)
            return 3
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
