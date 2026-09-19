"""Del aviso en bruto a una ficha estructurada.

`HeuristicParser` no usa ningún modelo: léxico por tipo (es/en y algo de fr/de/pt), alias de zonas,
negaciones, cantidades y lecturas de sensor. `LLMParser` cumple el mismo contrato y se enchufa
después. El resto de Mando solo ve el dict que devuelve `parse()`.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Callable, Protocol

from ..contracts import Channel, Family, Report, Zone
from .lexicon import (GATE, GATE_DIR, RELATIVE, TYPE_RE, TYPES, WEAK_RE, ZONE_RE, TypeSpec, generic_family,
                      spec_for)


_NEGATOR = re.compile(r"(?:^|\s)(?:no|sin|ningun\w*|tampoco|not|without|never|pas|aucun\w*|kein\w*|nicht|nao|sem)"
                      r"(?:\s+(?:hay|es|son|veo|vemos|se|ve|una?|el|la|los|las|is|are|any|a|de|d|ha|han|habido))"
                      r"{0,3}\s*$")
# Desmentido explícito: gana aunque el aviso nombre el incidente («falsa alarma lo del fuego»).
_ALL_CLEAR = re.compile(r"falsa alarma|false alarm|era (una )?broma|me he equivocado|me equivoque|all clear|never mind|"
                        r"fausse alerte|fehlalarm|alarme falso|aqui no (hay|pasa) nada|no veo nada")
# Desmentido débil: solo cuenta si el aviso no describe nada («igual no es nada» al final de un mensaje con una parada no desmiente).
_ALL_CLEAR_WEAK = re.compile(r"no es nada|no era nada|no pasa nada|no ha pasado nada|todo (ok|bien|en orden|controlado|tranquilo|"
                             r"normal)|ya esta (bien|resuelt|solucionad|atendid|controlad)|all good|nothing (is )?happening|"
                             r"everything (is )?(fine|ok)|\bresuelto\b|\bsolucionado\b|no hay nadie")
_VITALS_OK = re.compile(r"(?<!no )(?<!nao )(?<!ne )\b(respira\b|respira bien|esta respirando|consciente|ya esta de pie|"
                        r"se ha levantado|ya habla|esta hablando|is breathing|conscious\b|awake|talking)")
_HEDGE = re.compile(r"\bcreo\b|\bparece\b|quiza|igual\b|no estoy segur|no se si|me han dicho|dicen que|he oido|"
                    r"\bmaybe\b|not sure|i think|someone said|apparently|peut etre|vielleicht|\bacho\b")
_INTENSE = re.compile(r"\bgrave|muy mal|urgente|urgencia|rapido|socorro|\bayuda|\bhelp\b|\bsos\b|emergenc|"
                      r"por favor venid|corred|vite\b|hilfe|socorr")
_MILD = re.compile(r"\bleve|nada grave|poca cosa|pequen|sin importancia|\bminor\b|not serious|controlad")
_MINORS = re.compile(r"\bnin[oa]s?\b|\bmenor(es)?\b|\bbebe|\bhij[oa]|\bchild|\bkids?\b|\benfant|\bkind(er)?\b|crianca")
_STAFF = re.compile(r"jefe|seguridad|medic|sanitari|enfermer|tecnic|logistic|coordinador|operador|vigilante|"
                    r"ambulancia|voluntari|contador|estacion|sensor|\bsec \d|\bmed \d|\bamb \d|\btech \d|\bvol \d|\blog \d")

_NUM_WORDS = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "nueve": 9, "diez": 10, "doce": 12, "quince": 15, "veinte": 20, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "deux": 2, "trois": 3, "quatre": 4,
    "zwei": 2, "drei": 3, "vier": 4, "dois": 2, "duas": 2, "varios": 3, "varias": 3, "several": 3, "algunos": 3,
    "muchos": 10, "muchas": 10, "many": 10, "decenas": 20, "dozens": 20, "cientos": 100, "hundreds": 100,
}
_PERSON = (r"(?:personas?|gente|chic[oa]s?|chavales?|tios?|tias?|hombres?|mujer(?:es)?|nin[oa]s?|heridos?|"
           r"desmay\w+|inconscientes?|afectad\w+|casos?|golpes?|victimas?|people|persons?|guys?|girls?|injured|"
           r"cases|personnes|blesses|personen|verletzte|pessoas)")
_COUNT = re.compile(rf"\b(\d{{1,3}}|{'|'.join(_NUM_WORDS)})\s+(?:\w+\s+)?{_PERSON}")

# Lecturas de sensor: se leen del texto sin quitar la puntuación.
_S_RATIO = re.compile(r"(\d{2,6})\s*/\s*(\d{2,6})")
_S_PCT = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")
_S_DENS = re.compile(r"(?:densidad|density)\D{0,12}?(\d{1,2}(?:[.,]\d+)?)|(\d{1,2}(?:[.,]\d+)?)\s*(?:p|pers)?\s*/\s*m2")
_S_OCC = re.compile(r"(\d{2,6})\s*personas")
_S_CAP = re.compile(r"capacidad\D{0,6}(\d{2,6})")
_S_TEMP = re.compile(r"(?:temp\w*|grados)\D{0,12}?(\d{2}(?:[.,]\d+)?)|(\d{2}(?:[.,]\d+)?)\s*(?:°|º)\s*c?")
_S_WIND = re.compile(r"(?:viento|wind|rachas?|gusts?)\D{0,12}?(\d{1,3}(?:[.,]\d+)?)|(\d{1,3})\s*km/?h")
_S_WATER = re.compile(r"(?:agua|water|deposito|tank)\D{0,14}?(\d{1,6})\s*(?:l\b|litros|liters|litres)")

# Solo palabras largas y poco confundibles: «juego» no debe corregirse a «fuego».
_VOCAB = ["inconsciente", "desmayado", "desmayada", "respira", "infarto", "convulsiones", "sangrando", "avalancha",
          "empujando", "atascada", "saturada", "incendio", "tormenta", "escenario", "sospechosa", "abandonada",
          "unconscious", "breathing", "bleeding", "fainted", "pushing", "estructura", "plataforma", "puerta", "entrada"]


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """Minúsculas, sin tildes ni emojis ni puntuación, letras repetidas («ayudaaaa») reducidas."""
    s = _strip_accents(text.lower())
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"([a-z])\1{2,}", r"\1", s)
    return s.strip()


def _near(a: str, b: str, limit: int) -> bool:
    """Distancia de edición ≤ limit (1 o 2), con corte temprano."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return False
        prev = cur
    return prev[-1] <= limit


def _fix_typos(norm: str) -> str:
    out = []
    for tok in norm.split():
        if len(tok) >= 6 and tok not in _VOCAB:
            limit = 2 if len(tok) >= 10 else 1
            for w in _VOCAB:
                if w[0] == tok[0] and _near(tok, w, limit):
                    tok = w
                    break
        out.append(tok)
    return " ".join(out)


def _num(s: str | None) -> float | None:
    return float(s.replace(",", ".")) if s else None


class Parser(Protocol):
    def parse(self, report: Report, zones: dict[str, Zone]) -> dict[str, Any]: ...


class HeuristicParser:
    """Parser determinista. Devuelve siempre las claves del contrato y algunas de apoyo:
    life_threat, threat, count, minors, all_clear, vitals_ok, negated, secondary, sensor, sitewide."""

    def __init__(self) -> None:
        self._names: dict[tuple, list[tuple[str, str]]] = {}

    # ---------------------------------------------------------------- zonas
    def _zone_names(self, zones: dict[str, Zone]) -> list[tuple[str, str]]:
        key = tuple(zones)
        if key not in self._names:
            pairs = []
            for z in zones.values():
                pairs.append((normalize(z.id), z.id))
                n = normalize(z.name)
                if len(n) >= 4:
                    pairs.append((n, z.id))
            pairs.sort(key=lambda p: -len(p[0]))
            self._names[key] = pairs
        return self._names[key]

    @staticmethod
    def _gate_by_direction(word: str, zones: dict[str, Zone]) -> str | None:
        """«entrada norte», «main gate»: primero por el nombre de la puerta, luego por sus vecinos."""
        word = {"north": "norte", "south": "sur", "main": "principal"}.get(word, word)
        gates = [z for z in zones.values() if z.kind == "gate"]
        for z in gates:
            if word in normalize(z.name).split():
                return z.id
        if word == "principal":
            return None
        mark = "_n" if word == "norte" else "_s"
        hits = [z.id for z in gates if any(n.endswith(mark) for n in z.neighbors)
                and not any(n.endswith("_s" if mark == "_n" else "_n") for n in z.neighbors)]
        return hits[0] if len(hits) == 1 else None

    def find_zones(self, norm: str, zones: dict[str, Zone]) -> list[str]:
        """Zonas mencionadas. Gana la mención más específica (la más larga): «en el pasillo que va a los
        food trucks» es el pasillo, no la restauración; a igualdad, la primera."""
        hits: list[tuple[int, int, str]] = []
        for m in GATE.finditer(norm):
            hits.append((-len(m.group(0)), m.start(), f"gate_{m.group(1)}"))
        for m in GATE_DIR.finditer(norm):
            z = self._gate_by_direction(m.group(1) or m.group(2), zones)
            if z:
                hits.append((-len(m.group(0)), m.start(), z))
        for zid, rx in ZONE_RE:
            m = rx.search(norm)
            if m:
                hits.append((-len(m.group(0)), m.start(), zid))
        padded = f" {norm} "
        for name, zid in self._zone_names(zones):
            i = padded.find(f" {name} ")
            if i >= 0:
                hits.append((-len(name), i, zid))
        seen, out = set(), []
        for _, _, zid in sorted(hits):
            if zid in zones and zid not in seen:
                seen.add(zid)
                out.append(zid)
        return out

    # ---------------------------------------------------------------- sensores
    @staticmethod
    def _sensor(low: str) -> dict[str, float]:
        out: dict[str, float] = {}
        m = _S_RATIO.search(low)
        if m and int(m.group(2)) > 0:
            out["occupancy"], out["capacity"] = int(m.group(1)), int(m.group(2))
            out["ratio"] = int(m.group(1)) / int(m.group(2))
        occ, cap = _S_OCC.search(low), _S_CAP.search(low)
        if "ratio" not in out and occ and cap and int(cap.group(1)) > 0:
            out["occupancy"], out["capacity"] = int(occ.group(1)), int(cap.group(1))
            out["ratio"] = out["occupancy"] / out["capacity"]
        m = _S_DENS.search(low)
        if m:
            out["density"] = _num(m.group(1) or m.group(2))
        m = _S_TEMP.search(low)
        if m:
            out["temp_c"] = _num(m.group(1) or m.group(2))
        m = _S_WIND.search(low)
        if m:
            out["wind_kmh"] = _num(m.group(1) or m.group(2))
        m = _S_WATER.search(low)
        if m:
            out["water_l"] = _num(m.group(1))
        if "ratio" not in out and re.search(r"aforo|ocupaci|occupan|capacity|lleno", low):
            m = _S_PCT.search(low)
            if m:
                out["ratio"] = _num(m.group(1)) / 100
        return out

    @staticmethod
    def _from_sensor(s: dict[str, float], zone_kind: str | None) -> tuple[str, int] | None:
        """(tipo, gravedad) que implica una lectura, o None si está en rango normal."""
        found: list[tuple[int, str]] = []
        ratio, dens = s.get("ratio"), s.get("density")
        if ratio is not None and ratio >= 0.9:
            found.append((max(6, min(8, 6 + round((ratio - 0.9) * 10))), "gate_saturation"))
        if dens is not None and dens >= 4.0:
            found.append((9, "crush_risk") if dens >= 5 else (6, "gate_saturation"))
        if s.get("temp_c", 0) >= 35:
            found.append((7 if s["temp_c"] >= 38 else 6, "heat_wave"))
        if s.get("wind_kmh", 0) >= 50:
            found.append((9 if s["wind_kmh"] >= 70 else 7, "high_wind"))
        if "water_l" in s and s["water_l"] <= 150:
            found.append((6, "water_out"))
        if not found:
            return None
        sev, type_ = max(found)
        return type_, sev

    # ---------------------------------------------------------------- aviso completo
    def parse(self, report: Report, zones: dict[str, Zone]) -> dict[str, Any]:
        raw = report.text or ""
        low = _strip_accents(raw.lower())
        norm = _fix_typos(normalize(raw))

        zone = report.zone_hint if report.zone_hint in zones else None
        candidates = self.find_zones(norm, zones)
        if zone is None and candidates:
            zone = candidates[0]

        matched: list[TypeSpec] = []
        negated: list[str] = []
        hits = 0
        for spec, rx in TYPE_RE:
            ok = neg = False
            for m in rx.finditer(norm):
                # «no respira» lleva la negación dentro del patrón; «no hay fuego» la lleva delante
                if _NEGATOR.search(norm[:m.start()]):
                    neg = True
                else:
                    ok = True
                    hits += 1
            if ok:
                matched.append(spec)
            elif neg:
                negated.append(spec.type)

        sensor = self._sensor(low) if (report.channel == Channel.SENSOR or _S_RATIO.search(low)
                                       or "densidad" in low or "density" in low) else {}
        zone_kind = zones[zone].kind if zone else None
        sensor_type = self._from_sensor(sensor, zone_kind) if sensor else None

        all_clear = bool(_ALL_CLEAR.search(norm)) or (not matched and (bool(negated) or bool(_ALL_CLEAR_WEAK.search(norm))))
        vitals_ok = bool(_VITALS_OK.search(norm)) and not any(s_.type == "cardiac_arrest" for s_ in matched)

        if not matched:   # «cola», «tornos»: a falta de otra cosa, sí describen una saturación
            for spec_, rx in WEAK_RE:
                m_ = rx.search(norm)
                if m_ and not _NEGATOR.search(norm[:m_.start()]):
                    matched.append(spec_)
                    hits += 1
        generic = life_sig = threat_sig = False
        matched.sort(key=lambda s: (-s.severity, s.type))
        from_sensor = bool(sensor_type) and (not matched or sensor_type[1] >= matched[0].severity)
        if from_sensor:
            spec, severity = TYPES[sensor_type[0]], sensor_type[1]
        elif matched:
            spec, severity = matched[0], matched[0].severity
        else:
            # Tipo no reconocido: no se adivina. Familia y señales genéricas, tipo unknown_<familia>, menos confianza.
            family, life_sig, threat_sig = generic_family(norm)
            spec = TYPES[f"unknown_{family.value}"]
            severity = 8 if (life_sig or threat_sig) else spec.severity
            generic = True
        if spec.type == "gate_saturation" and zone_kind not in ("gate", None):
            spec = TYPES["bottleneck"]
            severity = min(severity, 7) if sensor_type else spec.severity
        informational = bool(sensor) and sensor_type is None and not matched

        # una lectura de aforo sola pide gestión de flujo, no un equipo; solo el umbral de aplastamiento (6,5/m²) mueve a dos
        if from_sensor and not matched and spec.family == Family.CROWD:
            dens = sensor.get("density") or 0.0
            needs = {"security": 2} if dens >= 6.5 else {}
        else:
            needs = {"medical": 1} if (generic and life_sig) else dict(spec.needs)
        for s_ in matched:   # un segundo tipo solo suma recursos si es de riesgo vital («pelea y uno no respira»)
            if s_.life_threat:
                for k, n in s_.needs.items():
                    needs[k] = max(needs.get(k, 0), n)

        count = 1
        m = _COUNT.search(norm)
        if m:
            g = m.group(1)
            count = int(g) if g.isdigit() else _NUM_WORDS.get(g, 1)
        minors = bool(_MINORS.search(norm))
        if not generic and not sensor_type:
            if count >= 10:
                severity += 2
            elif count >= 3:
                severity += 1
            if _INTENSE.search(norm) or raw.count("!") >= 3:
                severity += 1
            if _MILD.search(norm) and not spec.life_threat:
                severity -= 2
        if count >= 3 and "medical" in needs:
            needs["medical"] = min(3, needs["medical"] + 1)
        severity = max(1, min(10, severity))

        conf = {Channel.SENSOR: 0.95, Channel.OPERATOR: 0.95, Channel.RADIO: 0.85, Channel.VOICE: 0.8,
                Channel.SMS: 0.6, Channel.WHATSAPP: 0.55}.get(report.channel, 0.6)
        staff = bool(_STAFF.search(normalize(report.source)))
        if staff:
            conf += 0.1
        if hits >= 2:
            conf += 0.1
        elif hits == 1:
            conf += 0.05
        if _HEDGE.search(norm):
            conf -= 0.25
        if generic:
            conf -= 0.15
        missing: list[str] = []
        if generic and not all_clear and not informational:
            missing.append("type")
        relative = zone is not None and report.zone_hint is None and bool(RELATIVE.search(norm))
        if relative:
            conf -= 0.05   # «detrás de los baños»: la zona es la del punto de referencia, con algo menos de certeza
        if zone is None and not spec.sitewide and not informational:
            missing.append("zone")
            conf -= 0.1
        if len(candidates) > 1 and report.zone_hint is None:
            conf -= 0.05
        conf = round(max(0.05, min(0.99, conf)), 2)

        return {
            "type": spec.type, "family": spec.family, "zone": zone, "severity": severity, "needs": needs,
            "confidence": conf, "missing": missing,
            "life_threat": spec.life_threat or life_sig, "threat": spec.threat or threat_sig, "sitewide": spec.sitewide,
            "generic": generic, "reserved": spec.reserved or threat_sig or (minors and spec.family.value == "aggression"),
            "zone_relative": relative,
            "count": count, "minors": minors, "all_clear": all_clear, "vitals_ok": vitals_ok,
            "negated": negated, "secondary": [s.type for s in matched if s.type != spec.type],
            "sensor": sensor, "informational": informational, "staff": staff, "zone_candidates": candidates,
        }


LLM_PROMPT = """Eres el lector de avisos del centro de control de un festival de 40.000 personas.
Te llega UN aviso (texto libre de un asistente o del personal, o una lectura de sensor), en cualquier
idioma, con faltas, mayúsculas o emojis. Devuelve SOLO un objeto JSON, sin texto alrededor:

{{"type": "<uno de: {types}>",
  "family": "<crowd|medical|weather|aggression|supply|infra|resource|info|external>",
  "zone": "<uno de: {zones}> o null si el aviso no permite saberlo",
  "severity": <entero 1-10>,
  "needs": {{"<security|medical|ambulance|tech|logistics|volunteer>": <n>}},
  "confidence": <0-1: cuánto te fías de que el incidente existe y está donde dices>,
  "missing": ["zone" | "type" | ...datos imprescindibles que faltan],
  "life_threat": <true si puede ser parada cardiaca, persona inconsciente o que no respira>,
  "all_clear": <true si el aviso dice que NO pasa nada o que era falsa alarma>,
  "vitals_ok": <true si dice que la persona respira o está consciente>,
  "count": <personas afectadas, 1 si no se dice>,
  "minors": <true si hay menores>}}

Reglas: no inventes la zona; «no respira» es riesgo vital, «respira» no; una negación («no hay fuego»)
no es un incendio; si dudas entre dos gravedades, la mayor; nunca contestes al autor del aviso.

Canal: {channel} · Origen: {source} · Zona que da el canal: {zone_hint}
Aviso: «{text}»"""


class LLMParser:
    """Mismo contrato que `HeuristicParser`. No llama a ninguna API por sí mismo: hay que inyectarle
    `client`, una función `(prompt: str) -> str` que devuelva el JSON. Si la respuesta no es válida
    y hay `fallback`, se usa el parser heurístico."""

    def __init__(self, client: Callable[[str], str] | None = None, fallback: Parser | None = None) -> None:
        self.client = client
        self.fallback = fallback

    def prompt(self, report: Report, zones: dict[str, Zone]) -> str:
        return LLM_PROMPT.format(types=", ".join(TYPES), zones=", ".join(zones), channel=report.channel,
                                 source=report.source or "desconocido", zone_hint=report.zone_hint or "ninguna",
                                 text=report.text)

    def parse(self, report: Report, zones: dict[str, Zone]) -> dict[str, Any]:
        if self.client is None:
            raise NotImplementedError("LLMParser necesita un cliente: LLMParser(client=mi_funcion)")
        try:
            raw = self.client(self.prompt(report, zones))
            data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
            return self._validate(data, zones)
        except (ValueError, KeyError, TypeError):
            if self.fallback is None:
                raise
            return self.fallback.parse(report, zones)

    @staticmethod
    def _validate(d: dict[str, Any], zones: dict[str, Zone]) -> dict[str, Any]:
        spec = spec_for(str(d.get("type", "unknown")), d.get("family"))
        zone = d.get("zone") if d.get("zone") in zones else None
        missing = [str(x) for x in d.get("missing", [])]
        if zone is None and not spec.sitewide and "zone" not in missing:
            missing.append("zone")
        return {
            "type": str(d.get("type") or spec.type), "family": spec.family, "zone": zone,
            "severity": max(1, min(10, int(d.get("severity", spec.severity)))),
            "needs": {str(k): int(v) for k, v in (d.get("needs") or spec.needs).items()},
            "confidence": max(0.05, min(0.99, float(d.get("confidence", 0.6)))), "missing": missing,
            "life_threat": bool(d.get("life_threat", spec.life_threat)), "threat": spec.threat,
            "sitewide": spec.sitewide, "generic": str(d.get("type") or "") not in TYPES, "reserved": spec.reserved,
            "zone_relative": False, "count": int(d.get("count", 1)), "minors": bool(d.get("minors", False)),
            "all_clear": bool(d.get("all_clear", False)), "vitals_ok": bool(d.get("vitals_ok", False)),
            "negated": [], "secondary": [], "sensor": {}, "informational": False, "staff": False,
            "zone_candidates": [zone] if zone else [],
        }


class CascadeParser:
    """Reglas primero; solo lo que las reglas NO reconocen (`generic`) pasa al modelo, si se ha enchufado uno.
    Es la vía prevista para los textos no reconocidos: el núcleo sigue siendo determinista y el modelo no ve el resto."""

    def __init__(self, rules: Parser, llm: Parser | None = None) -> None:
        self.rules = rules
        self.llm = llm

    def parse(self, report: Report, zones: dict[str, Zone]) -> dict[str, Any]:
        p = self.rules.parse(report, zones)
        if self.llm is None or not p.get("generic") or p.get("all_clear") or p.get("informational"):
            return p
        try:
            q = self.llm.parse(report, zones)
        except Exception:     # el modelo falla o no está: valen las reglas
            return p
        if q.get("zone") is None:
            q["zone"], q["missing"] = p["zone"], [x for x in q.get("missing", []) if x != "zone" or p["zone"] is None]
        q["life_threat"] = bool(q.get("life_threat") or p["life_threat"])   # una señal de riesgo vital nunca se pierde
        q["threat"] = bool(q.get("threat") or p["threat"])
        q["reserved"] = bool(q.get("reserved") or p["reserved"])
        return q
