"""Suite 2 — comprensión: parser e intake. La reserva SOLO se mide, no se usa para ajustar."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from motor.contracts import Channel, Report
from motor.mando.free_text_bench import DEV, HARD_ZONES, HOLDOUT, score as score_free
from motor.mando.parser import HeuristicParser
from motor.mando.test_mando import real_zones

from .common import GRAVE_FAMILIES, EvalResult, ROOT, fail_ex, load_jsonl

FRASES = ROOT / "motor" / "mando" / "data"


def run(rapido: bool = False) -> list[EvalResult]:
    parser = HeuristicParser()
    zones = real_zones()
    n_dev = 40 if rapido else None
    n_res = 40 if rapido else None
    n_ft = 20 if rapido else None
    out: list[EvalResult] = []
    out.extend(_jsonl("C-dev", FRASES / "frases_sinteticas_dev.jsonl", parser, zones, n_dev,
                      "desarrollo (sí se puede mirar para ajustar el parser; esta batería NO lo ajusta)"))
    out.extend(_jsonl("C-reserva", FRASES / "frases_sinteticas_reserva.jsonl", parser, zones, n_res,
                      "RESERVA: solo se mide, no se mira para ajustar"))
    out.extend(_freetext(parser, zones, n_ft))
    return out


def _take(rows: list, n: int | None) -> list:
    return rows if n is None else rows[:n]


def _parse_row(parser: HeuristicParser, zones: dict, text: str) -> dict[str, Any]:
    return parser.parse(Report("r", 0, Channel.WHATSAPP, text), zones)


def _jsonl(prefix: str, path: Path, parser: HeuristicParser, zones: dict, n: int | None, note: str) -> list[EvalResult]:
    rows = _take(load_jsonl(path) if path.exists() else [], n)
    fam_ok = zone_ok = grave_ok = 0
    fam_fail: list[dict] = []
    zone_fail: list[dict] = []
    grave_fail: list[dict] = []
    n_grave = 0
    for i, row in enumerate(rows):
        gold_f, gold_z = row.get("family"), row.get("zone", None)
        p = _parse_row(parser, zones, row["text"])
        pred_f, pred_z = str(p.get("family") or ""), p.get("zone")
        if pred_f == str(gold_f):
            fam_ok += 1
        else:
            fam_fail.append(fail_ex(1, f"{path.name}:{i}", f"familia {pred_f!r} ≠ {gold_f!r}", texto=row["text"][:80]))
        want_z = gold_z if not isinstance(gold_z, list) else tuple(gold_z)
        z_ok = pred_z in (want_z if isinstance(want_z, tuple) else (want_z,))
        if z_ok:
            zone_ok += 1
        else:
            zone_fail.append(fail_ex(1, f"{path.name}:{i}", f"zona {pred_z!r} ≠ {gold_z!r}", texto=row["text"][:80]))
        if str(gold_f) in GRAVE_FAMILIES:
            n_grave += 1
            if pred_f == "info":
                grave_fail.append(fail_ex(1, f"{path.name}:{i}", "lo grave cayó en familia info", texto=row["text"][:80]))
            else:
                grave_ok += 1
    n = len(rows)
    return [
        EvalResult(id=f"{prefix}-familia", suite="comprension", description=f"Parser: familia correcta. {note}",
                   n=n, passed=fam_ok, failures=fam_fail, extra={"fuente": str(path.relative_to(ROOT))}),
        EvalResult(id=f"{prefix}-zona", suite="comprension", description=f"Parser: zona correcta. {note}",
                   n=n, passed=zone_ok, failures=zone_fail, extra={"fuente": str(path.relative_to(ROOT))}),
        EvalResult(id=f"{prefix}-grave-no-info", suite="comprension",
                   description=f"Lo grave (medical/aggression/crowd/external) no cae en familia info. {note}",
                   n=n_grave, passed=grave_ok, failures=grave_fail,
                   notes="N = filas con familia grave etiquetada."),
    ]


def _freetext(parser: HeuristicParser, zones: dict, n: int | None) -> list[EvalResult]:
    blocks = [("DEV", DEV), ("HOLDOUT", HOLDOUT), ("HARD", HARD_ZONES)]
    out = []
    for name, rows in blocks:
        sample = _take(list(rows), n)
        scored = score_free(sample, parser=parser, zones=zones)
        fam_fail = [{"seed": 1, "caso": f"free_text_bench.{name}", "detalle": " | ".join(m)} for m in scored["misses"]]
        # score() junta familia+zona+tipo; separamos familia/zona/grave a mano
        fam_ok = zone_ok = grave_ok = n_grave = 0
        fails_f, fails_z, fails_g = [], [], []
        for text, family, type_, zone in sample:
            p = _parse_row(parser, zones, text)
            fams = family if isinstance(family, tuple) else (family,)
            zs = zone if isinstance(zone, tuple) else (zone,)
            if str(p["family"]) in fams:
                fam_ok += 1
            else:
                fails_f.append(fail_ex(1, f"free_text:{name}", f"{p['family']} ≠ {family}", texto=text[:80]))
            if p["zone"] in zs:
                zone_ok += 1
            else:
                fails_z.append(fail_ex(1, f"free_text:{name}", f"zona {p['zone']!r} ≠ {zone!r}", texto=text[:80]))
            if any(f in GRAVE_FAMILIES for f in fams):
                n_grave += 1
                if str(p["family"]) == "info":
                    fails_g.append(fail_ex(1, f"free_text:{name}", "lo grave cayó en info", texto=text[:80]))
                else:
                    grave_ok += 1
        note = "Avisos libres escritos a mano (free_text_bench). HOLDOUT/HARD no se usan para ajustar aquí."
        tag = f"C-freetext-{name.lower()}"
        out += [
            EvalResult(id=f"{tag}-familia", suite="comprension", description=f"free_text {name}: familia. {note}",
                       n=len(sample), passed=fam_ok, failures=fails_f),
            EvalResult(id=f"{tag}-zona", suite="comprension", description=f"free_text {name}: zona. {note}",
                       n=len(sample), passed=zone_ok, failures=fails_z),
            EvalResult(id=f"{tag}-grave-no-info", suite="comprension",
                       description=f"free_text {name}: lo grave no cae en info.",
                       n=n_grave, passed=grave_ok, failures=fails_g),
        ]
    return out
