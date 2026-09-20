"""Suite 6 — lectura de northstars y tests de HappyRobot. Sin inventar nada que no esté escrito."""
from __future__ import annotations

import re
from pathlib import Path

from .common import ROOT, EvalResult, fail_ex

DOCS = {
    "mapa": ROOT / "motor" / "happyrobot" / "MAPA-WORKFLOWS.md",
    "plataforma": ROOT / "motor" / "happyrobot" / "AUDITORIA-PLATAFORMA.md",
    "total": ROOT / "analisis" / "AUDITORIA-TOTAL.md",
}


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _first(text: str, *patterns: str) -> str | None:
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0).strip()
    return None


def run(rapido: bool = False) -> list[EvalResult]:
    out: list[EvalResult] = []
    quotes: dict[str, list[str]] = {}

    mapa = _read(DOCS["mapa"])
    if mapa is None:
        out.append(EvalResult(id="P-mapa-evals", suite="plataforma", description="MAPA-WORKFLOWS.md",
                              n=1, passed=0, failures=[fail_ex(0, "MAPA-WORKFLOWS.md", "fichero no encontrado")]))
    else:
        found = []
        for pat in (
            r"N=32 casos distintos, 26 aprobados / 6 suspendidos[^\n]*",
            r"38 nodos aprobados, 16 fallidos y 1 omitido",
            r"test-all asociado: \*\*38 nodos aprobados, 16 fallidos y 1 omitido\*\*",
            r"Northstars activas, con ejemplo positivo y negativo",
        ):
            hit = _first(mapa, pat)
            if hit:
                found.append(hit)
        n56 = len(re.findall(r"^\| mando-.*\| 7 \|", mapa, re.M))
        quotes["mapa"] = found + [f"filas de 7 northstars en la tabla de validación: {n56}"]
        ok = "26 aprobados" in mapa and "6 suspendidos" in mapa
        extra = {
            "n_casos_documentados": 32 if "N=32" in mapa else None,
            "aprobados_documentados": 26 if "26 aprobados" in mapa else None,
            "suspendidos_documentados": 6 if "6 suspendidos" in mapa else None,
            "filas_7_northstars": n56,
            "northstars_si_8x7": n56 * 7 if n56 else None,
            "citas": found[:6],
            "fuente": "motor/happyrobot/MAPA-WORKFLOWS.md",
        }
        out.append(EvalResult(
            id="P-mapa-evals", suite="plataforma",
            description="Lectura: tests simulados y northstars en MAPA-WORKFLOWS.md (p. ej. 26/32).",
            n=1, passed=int(ok), failures=[] if ok else [fail_ex(0, "MAPA-WORKFLOWS.md", "no aparece 26 aprobados / 6 suspendidos")],
            extra=extra, notes="Solo lectura. No se ha ejecutado test_all en esta batería.",
        ))

    plat = _read(DOCS["plataforma"])
    if plat is None:
        out.append(EvalResult(id="P-auditoria", suite="plataforma", description="AUDITORIA-PLATAFORMA.md",
                              n=1, passed=0, failures=[fail_ex(0, "AUDITORIA-PLATAFORMA.md", "fichero no encontrado")]))
    else:
        ns32 = "8 northstars activas por agente preparado, 32 total" in plat or "32 total" in plat
        cites = []
        for pat in (
            r"\*\*8 northstars activas por agente preparado, 32 total\*\*[^\n]*",
            r"N=4 pruebas locales, 4 correctas\.",
            r"Auditoría estática: \*\*N=66 nodos\*\*[^\n]*",
            r"Serializadores actuales: \*\*N=42/42 casos locales correctos\*\*",
            r"Error running tests \(HTTP 400\):[^\n]+",
            r"Error triggering coverage assessment \(HTTP 400\):[^\n]+",
        ):
            hit = _first(plat, pat)
            if hit:
                cites.append(hit[:240])
        quotes["plataforma"] = cites
        out.append(EvalResult(
            id="P-auditoria-northstars", suite="plataforma",
            description="Lectura: 8 northstars × 4 agentes = 32, y bloqueos de assess_coverage / test_all chat.",
            n=1, passed=int(ns32),
            failures=[] if ns32 else [fail_ex(0, "AUDITORIA-PLATAFORMA.md", "no aparece el recuento de 32 northstars")],
            extra={"citas": cites, "fuente": "motor/happyrobot/AUDITORIA-PLATAFORMA.md",
                   "assess_coverage": "HTTP 400" if "assess-coverage" in plat or "assess_coverage" in plat else "no citado"},
            notes="N=0 evaluaciones conversacionales actuales según el propio documento histórico; la reanudación MCP sí lista 32 northstars leídas.",
        ))

    total = _read(DOCS["total"])
    if total is None:
        out.append(EvalResult(id="P-total", suite="plataforma", description="analisis/AUDITORIA-TOTAL.md",
                              n=1, passed=0, failures=[fail_ex(0, "AUDITORIA-TOTAL.md", "fichero no encontrado")]))
    else:
        cites = []
        for pat in (
            r"24 evals nuevos y4 reutilizados;28 lanzamientos y28 veredictos\.[^\n]*",
            r"\| Teléfono v2 \| 7 \| 0 \| 7 \|[^\n]*",
            r"\| Webcall v3 \| 7 \| 2 \| 5 \|[^\n]*",
            r"\| Voz v1 \| 7 \| 4 \| 3 \|[^\n]*",
            r"\| Voz v2 \| 7 \| 4 \| 3 \|[^\n]*",
        ):
            hit = _first(total, pat)
            if hit:
                cites.append(hit)
        quotes["total"] = cites
        ok = "28 lanzamientos" in total and "28 veredictos" in total
        extra = {
            "telefono_v2": "0/7 passed bruto" if "| Teléfono v2 |" in total else None,
            "webcall_v3": "2/7" if "| Webcall v3 |" in total else None,
            "voz_v1": "4/7" if "| Voz v1 |" in total else None,
            "voz_v2": "4/7" if "| Voz v2 |" in total else None,
            "citas": cites,
            "fuente": "analisis/AUDITORIA-TOTAL.md",
            "aviso": "Las 30 northstars leídas son 8+8+6+8 registros por versión; no 30 reglas distintas.",
        }
        out.append(EvalResult(
            id="P-voz-simulada", suite="plataforma",
            description="Lectura: evals de voz simulada (28 lanzamientos) en AUDITORIA-TOTAL.md.",
            n=1, passed=int(ok),
            failures=[] if ok else [fail_ex(0, "AUDITORIA-TOTAL.md", "no aparecen 28 lanzamientos/veredictos")],
            extra=extra,
            notes="No se han relanzado evals de voz. Cifras copiadas del documento. Sin transcripciones inventadas.",
        ))

    # recuento conjunto que el usuario citó (56 / 26/32) SOLO si está escrito
    mapa_txt = mapa or ""
    n56_written = "56 northstars" in mapa_txt
    # MAPA tiene 8 filas × 7 = 56; lo decimos como producto de la tabla, no como cifra suelta inventada
    out.append(EvalResult(
        id="P-resumen-vocabulario", suite="plataforma",
        description="HappyRobot: northstars, Adversarial Agents (conversación) vs Caos (mundo), Audits & Tests.",
        n=3, passed=sum(1 for p in DOCS.values() if p.exists()),
        extra={
            "citas_por_doc": quotes,
            "26_de_32": "MAPA-WORKFLOWS.md: N=32 casos distintos, 26 aprobados / 6 suspendidos" if mapa and "26 aprobados" in mapa else "no encontrado",
            "56_northstars": (
                "escrito literalmente en MAPA" if n56_written
                else ("8 workflows × 7 northstars en la tabla de validación de MAPA = 56"
                      if mapa and len(re.findall(r"^\| mando-.*\| 7 \|", mapa_txt, re.M)) == 8
                      else "no se afirma 56: no hay 8 filas de 7 en MAPA" if mapa else "MAPA ausente")
            ),
        },
        notes=("Su adversario ataca la conversación; el nuestro ataca el mundo. "
               "Esta batería es el Audits & Tests de decisión + diálogo local. No se ha llamado a la API de la plataforma."),
    ))
    return out
