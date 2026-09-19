"""Genera `PROTOCOLOS.md` (hoja de validación para una persona con formación sanitaria) desde `protocolos.json`.

    python3 -m motor.protocolos.render_md

El JSON es la fuente de verdad: si Talía cambia algo, se cambia en el JSON y se vuelve a generar.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from motor.protocolos import load

OUT = Path(__file__).with_name("PROTOCOLOS.md")
BOX = "☐ validado ☐ cambiar"
KIND_ES = {"medical": "sanitario", "ambulance": "ambulancia", "security": "seguridad", "volunteer": "voluntario",
           "logistics": "logística", "tech": "técnico"}
TYPE_ES = {"bool": "sí / no / no sé", "number": "número", "enum": "opciones", "text": "texto libre", "zone_point": "zona + referencia"}
EN_WARN_END = "pendiente de revisión."

INTRO = """# Protocolos del agente de recogida — hoja de validación

> **⚠ AVISO DE SEGURIDAD.** Son instrucciones de apoyo para una **SIMULACIÓN de hackathon**. **No sustituyen
> al 112 ni a la formación en primeros auxilios.** En un despliegue real las valida y firma la dirección
> sanitaria del evento (y el 112 de la comunidad). Nada de esto se ha probado con pacientes ni con público.

Generado desde `protocolos.json` con `python3 -m motor.protocolos.render_md`. **No editar a mano:** los cambios
se hacen en el JSON y se regenera. Fuentes y lo que no se pudo verificar: `FUENTES.md`.

## Cómo validar esto en 15 minutos (Talía)

| Min | Parte | Qué mirar |
|---|---|---|
| 3 | **A. Decisiones** | Siete puntos donde las fuentes se contradicen o donde he decidido yo. Necesito un sí o un no. |
| 6 | **B. Instrucciones pendientes** | {n_pend} textos que NO estaban en la lista validada del Anexo C. Casilla por fila. Las {n_val} ya validadas solo necesitan un vistazo al inglés. |
| 5 | **C. Protocolos** | Sobre todo los 8 médicos: ¿las preguntas son las correctas y en ese orden?, ¿las señales de alarma disparan lo que deben? |
| 1 | **D. Lo que el agente nunca dice** | Lista corta; tachar o añadir. |

**Leyenda.** ✔ = redacción validada por la experta del consejo (Anexo C de `consejo/seguridad-eventos.md`), copiada
literal. **⚠ = extrapolación mía: no está literalmente en una fuente** (traducción, resumen, umbral, redacción
o decisión de diseño). Todo el inglés es traducción mía, fija y pretraducida: cuenta como ⚠ aunque el español esté validado.
**⚠ general:** las severidades (1–10), los recursos que se piden y el «tipo de Mando» NO salen de guías clínicas: copian
o aproximan la taxonomía del simulador. Y los disparadores (palabras clave) son una red de seguridad por subcadena,
sin acentos ni mayúsculas; no hace falta validarlos.

Cómo lee el agente cada protocolo: pregunta en orden; **envía en cuanto tiene los datos de «Enviar con»**, sin
esperar al resto; tras cada respuesta mira las señales de alarma **en orden y se queda con la primera que se
cumple**; «no sé» en una pregunta vital cuenta como la respuesta peligrosa; con una señal de «enviar ya» deja de
hacer preguntas no críticas. Nunca diagnostica: recoge hechos (responde / respira / sangra mucho).

## A. Decisiones que necesitan criterio sanitario

| # | Asunto | Qué dicen las fuentes | Qué he puesto | {box} |
|---|---|---|---|---|
| 1 | **Hielo en el golpe de calor** | SAMUR: «no enfriar directamente con hielo». ERC 2021: vale cualquier técnica disponible, incluidas bolsas de hielo. NHS: bolsas frías *envueltas* en axilas y cuello. | «Si hay hielo o bolsas frías, envuélvelas en tela y ponlas en cuello y axilas.» | {box} |
| 2 | **Apósito empapado** | SAMUR y guion telefónico MCW: no retirar, poner otro encima. St John Ambulance: retirar y poner uno nuevo. ERC 2021 no entra. | No retirar (SAMUR). | {box} |
| 3 | **Agua a un intoxicado consciente** | NHS: agua a sorbos si está consciente y traga. SAMUR: no dar de beber. | No se menciona el agua; solo «ni comida, ni más alcohol, ni café». | {box} |
| 4 | **Autoinyector de adrenalina** | NHS lo pone como primer paso para el público; ERC 2021: segunda dosis a los 5 min. | Única instrucción que toca medicación, y solo el dispositivo propio de la persona. ¿Se mantiene? | {box} |
| 5 | **RCP solo con las manos siempre** | ERC 2021: si no puedes ventilar, compresiones continuas. MCW usa ventilaciones en ahogamiento, atragantamiento y sobredosis. | Siempre solo manos (un desconocido, en un festival, guiado por texto o voz). | {box} |
| 6 | **Collarín y movilización** | SAMUR describe un collarín improvisado. ERC 2021: collarín NO recomendado; que la persona mantenga quieto el cuello. | ERC: no mover, no collarín. | {box} |
| 7 | **Profundidad de las compresiones** | ERC 2021 y St John: 5–6 cm, 100–120/min. La web de Cruz Roja Española abierta aún dice «unos 4 cm» (texto antiguo). | «Unos 5 centímetros, unas dos veces por segundo.» | {box} |

"""


def link(url: str) -> str:
    if not url.startswith("http"):
        return url
    host = urlparse(url).netloc.replace("www.", "")
    return f"[{host}]({url})"


def esc(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def value(v) -> str:
    if v is True:
        return "sí"
    if v is False:
        return "no"
    if v == "unknown":
        return "no sé"
    return f"`{v}`" if isinstance(v, str) else str(v)


def cond(c: dict) -> str:
    if not c:
        return "*(en cualquier otro caso)*"
    parts = []
    for slot, exp in c.items():
        if isinstance(exp, dict):
            txt = " y ".join(f"{'≥' if k == 'gte' else '≤'} {n}" for k, n in exp.items())
        elif isinstance(exp, list):
            txt = "= " + " o ".join(value(v) for v in exp)
        else:
            txt = "= " + value(exp)
        parts.append(f"`{slot}` {txt}")
    return " **y** ".join(parts)


def then(t: dict) -> str:
    needs = " + ".join(f"{n} {KIND_ES[k]}" for k, n in t["needs"].items())
    bits = ["**RIESGO VITAL**" if t["life_risk"] else "sin riesgo vital", f"severidad ≥ {t['severity_min']}", needs,
            "**enviar ya**" if t["dispatch_now"] else "informar a control"]
    if "mando_type_hint" in t:
        bits.append(f"tipo Mando `{t['mando_type_hint']}`")
    if "switch_to" in t:
        bits.append(f"pasa a `{t['switch_to']}`")
    return " · ".join(bits)


def steps(lst: list[str]) -> str:
    return "<br>".join(f"{i}. {esc(s)}" for i, s in enumerate(lst, 1))


def instruction_catalogue(doc: dict) -> tuple[list[dict], dict[str, list[str]]]:
    seen: dict[str, dict] = {}
    used: dict[str, list[str]] = {}
    for p in doc["protocols"]:
        for ins in p["instructions"]:
            seen.setdefault(ins["id"], ins)
            used.setdefault(ins["id"], []).append(p["id"])
    return list(seen.values()), used


def render(doc: dict) -> str:
    catalogue, used = instruction_catalogue(doc)
    validated = [i for i in catalogue if i.get("status") == "validada_anexo_c"]
    pending = [i for i in catalogue if i.get("status") != "validada_anexo_c"]
    out = [INTRO.format(n_pend=len(pending), n_val=len(validated), box=BOX)]

    out.append(f"## B. Instrucciones al público ({len(catalogue)})\n")
    out.append(f"### B1. Pendientes de validar ({len(pending)}) — todas llevan ⚠\n")
    out.append(f"| Clave | Pasos (texto exacto que dirá el agente) | Fuente principal | ⚠ Qué es mío | {BOX} |")
    out.append("|---|---|---|---|---|")
    for i in pending:
        src = ", ".join(link(u) for u in [i["source"], *i.get("sources_extra", [])])
        out.append(f"| `{i['id']}` | {steps(i['steps']['es'])} | {src} | ⚠ {esc(i.get('warn', 'Redacción propia.'))} | {BOX} |")
    out.append(f"\n### B2. Ya validadas en el Anexo C ({len(validated)}) — texto español literal; ⚠ solo el inglés\n")
    out.append(f"| Clave | Español (✔ validado) | Inglés (⚠ traducción mía) | Respaldo en fuente abierta | {BOX} |")
    out.append("|---|---|---|---|---|")
    for i in validated:
        src = ", ".join(link(u) for u in [i["source"], *i.get("sources_extra", [])] if u.startswith("http")) or "— (sin fuente abierta)"
        tail = i.get("warn", "").partition(EN_WARN_END)[2].strip()  # lo que haya además del aviso común sobre el inglés
        note = f"<br>⚠ {esc(tail)}" if tail else ""
        out.append(f"| `{i['id']}` | ✔ {' '.join(esc(s) for s in i['steps']['es'])}{note} | {' '.join(esc(s) for s in i['steps']['en'])} | {src} | {BOX} |")
    out.append(f"\n### B3. Inglés de las pendientes (para quien revise la traducción)\n")
    out.append("| Clave | Steps (EN) |")
    out.append("|---|---|")
    for i in pending:
        out.append(f"| `{i['id']}` | {steps(i['steps']['en'])} |")

    out.append(f"\n## C. Protocolos ({len(doc['protocols'])})\n")
    out.append("Van ordenados de más a menos crítico: si un aviso encaja con varios, gana el que aparece antes.\n")
    for n, p in enumerate(doc["protocols"], 1):
        ext = p["handoff"]["external"]
        ext_txt = "ninguno" if ext is None else f"{ext['kind']} (**siempre con aprobación humana**" + (", y con consentimiento de la víctima" if ext.get("requires_consent") else "") + ")"
        tag = " · **[RESERVADO]**" if p["sensitive"] else ""
        out.append(f"### {n}. {p['label']['es']} · `{p['id']}`{tag}\n")
        out.append(f"Familia `{p['family']}` · tipo de Mando `{p['mando_type_hint']}` · **Enviar con:** {', '.join('`' + s + '`' for s in p['dispatch_as_soon_as'])} · "
                   f"**Avisa a:** {', '.join(p['handoff']['notify'])} · **Externo:** {ext_txt}\n")
        if p["sensitive"]:
            out.append("> Tono neutro, solo las preguntas críticas, no se repite lo contado, sin megafonía, en pantalla solo «Incidente reservado», paso inmediato a una persona.\n")
        out.append("| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |")
        out.append("|---|---|---|---|---|---|")
        for k, s in enumerate(p["slots"], 1):
            opts = "<br>" + ", ".join(f"`{o}`" for o in s["options"]) if s["type"] == "enum" else ""
            warn = f"<br>⚠ {esc(s['warn'])}" if "warn" in s else ""
            out.append(f"| {k} | **{esc(s['question']['es'])}**<br>{esc(s['question']['en'])}<br>`{s['id']}` | {TYPE_ES[s['type']]}{opts} | "
                       f"{'**sí**' if s['critical'] else 'no'} | {cond(s['ask_if']) if 'ask_if' in s else '—'} | {esc(s.get('why', ''))}{warn} |")
        out.append("\n| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |")
        out.append("|---|---|---|")
        for f in p["red_flags"]:
            warn = f"<br>⚠ {esc(f['warn'])}" if "warn" in f else ""
            out.append(f"| {cond(f['if'])} | {then(f['then'])}{warn} | `{f['then']['instruction']}` |")
        out.append(f"\nInstrucciones disponibles: {', '.join('`' + i['id'] + '`' for i in p['instructions'])}.")
        if "hint_warn" in p:
            out.append(f"\n⚠ {p['hint_warn']}")
        out.append(f"\nFuentes: {' · '.join(link(u) for u in p['sources'])}\n")
        out.append(f"**{BOX}:** ______________________________________________\n")

    g = doc["global"]
    out.append("## D. Reglas globales\n")
    out.append(f"**Apertura:** «{g['opening']['es']}» / “{g['opening']['en']}”\n")
    out.append("**Si no sabe decir dónde está** (se prueban en este orden):\n")
    for item in g["location_questions"]:
        out.append(f"- «{item['es']}» / “{item['en']}”")
    out.append(f"\n**Frase de paso en incidentes reservados:** «{g['reserved_handling']['es']}» / “{g['reserved_handling']['en']}”\n")
    for rule in g.get("reserved_rules", []):
        out.append(f"- {rule}")
    out.append(f"\n### D1. Lo que el agente nunca dice ({len(g['never_say'])})\n")
    out.append(f"| Nunca | Por qué | {BOX} |")
    out.append("|---|---|---|")
    for item in g["never_say"]:
        out.append(f"| {esc(item['es'])} | {esc(item['why'])} | {BOX} |")
    out.append(f"\n### D2. Cuándo deja de preguntar ({len(g['stop_rules'])})\n")
    for k, rule in enumerate(g["stop_rules"], 1):
        out.append(f"{k}. {rule}")
    tpl = g.get("external_report_template")
    if tpl:
        out.append(f"\n### D3. Parte al 112 — plantilla {tpl['scheme']}\n")
        out.append("El agente solo lo RELLENA con hechos; lo envía una persona tras aprobarlo.\n")
        out.append("| Letra | Contenido | Sale de los slots |")
        out.append("|---|---|---|")
        for f in tpl["fields"]:
            out.append(f"| **{f['letter']}** | {esc(f['es'])} | {', '.join('`' + s + '`' for s in f['from_slots']) or '—'} |")
        out.append(f"\n⚠ {tpl['warn']} Fuente: {link(tpl['source'])}")
    if g.get("context_notes"):
        out.append("\n### D4. Contexto (el agente no lo aplica)\n")
        for note in g["context_notes"]:
            head, _, url = note.rpartition("Fuente: ")
            out.append(f"- {head}Fuente: {link(url)}" if head else f"- {note}")
    return "\n".join(out) + "\n"


def main() -> None:
    OUT.write_text(render(load()), encoding="utf-8")
    print(f"{OUT}: escrito")


if __name__ == "__main__":
    main()
