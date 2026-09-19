"""Comprensión determinista del mensaje de quien avisa: idioma, intención (orden, broma, «no lo sé», sí/no) y
CONCEPTOS (respira, responde, sangra, hay un arma…) que rellenan los slots de un protocolo.

No copia el léxico de Mando: importa su normalizador, su corrector de faltas, su detector de negaciones, su contador
de personas y sus alias de zona. Aquí solo está lo que Mando no necesita: entender la RESPUESTA a una pregunta.
Todos los patrones se aplican sobre texto normalizado (minúsculas, sin tildes ni puntuación; «isn't» → «isn t»).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from ..mando import parser as _mp
from ..mando.lexicon import RELATIVE  # noqa: F401  (se reexporta: el motor lo usa para bajar la confianza)
from ..mando.parser import normalize

# Piezas privadas del parser de Mando: se reutilizan si existen; si alguien las renombra, hay un sustituto mínimo.
_fix_typos = getattr(_mp, "_fix_typos", lambda s: s)
NEGATOR: re.Pattern = getattr(_mp, "_NEGATOR", re.compile(r"(?:^|\s)(?:no|sin|not|without|never)(?:\s+(?:hay|is|are|a))?\s*$"))
HEDGE: re.Pattern = getattr(_mp, "_HEDGE", re.compile(r"\bcreo\b|\bparece\b|not sure|i think|\bmaybe\b"))
COUNT: re.Pattern | None = getattr(_mp, "_COUNT", None)
NUM_WORDS: dict[str, int] = getattr(_mp, "_NUM_WORDS", {"un": 1, "una": 1, "dos": 2, "tres": 3, "one": 1, "two": 2, "three": 3})

EMOJI = {"🔥": " fuego ", "🩸": " sangre ", "🔪": " cuchillo ", "🥵": " mucho calor ", "🤕": " herido ", "🚑": " ambulancia ",
         "🆘": " ayuda ", "😵": " mareado ", "🥊": " pelea ", "👊": " pelea "}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# Palabras de las que depende una decisión vital: se corrigen también las letras bailadas («respria»), que el
# corrector de Mando (distancia de edición simple) no cubre.
_VITAL_WORDS = ("respira", "responde", "reacciona", "inconsciente", "consciente", "desmayado", "desmayada", "sangra",
                "sangrando", "convulsiones", "breathing", "responding", "unconscious", "bleeding", "despierta")


def _osa1(a: str, b: str) -> bool:
    """¿Distancia ≤ 1 contando una transposición de letras vecinas como un solo error?"""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:] or (a[i:i + 2] == b[i:i + 2][::-1] and a[i + 2:] == b[i + 2:])
    long_, short = (a, b) if len(a) > len(b) else (b, a)
    return long_[i + 1:] == short[i:]


def _fix_vital(norm: str) -> str:
    out = []
    for tok in norm.split():
        if len(tok) >= 6 and tok not in _VITAL_WORDS:
            tok = next((w for w in _VITAL_WORDS if w[0] == tok[0] and _osa1(tok, w)), tok)
        out.append(tok)
    return " ".join(out)


def prep(text: str) -> tuple[str, str]:
    """(low, norm): `low` conserva la puntuación (para trocear y sacar puntos de referencia); `norm` es el de Mando."""
    for k, v in EMOJI.items():
        text = text.replace(k, v)
    low = strip_accents(text.lower())
    return low, _fix_vital(_fix_typos(normalize(text)))


# ---------------------------------------------------------------------------- idioma
_EN = frozenset("the is are he she my not and at near by friend isn help please there someone i we they has it yes "
                "don know his her him with can t s m what where of to on people guy girl need".split())
_ES = frozenset("el la mi no y en un una se ha que esta hay junto los las por favor si lo amigo amiga ayuda al del "
                "de le me es con aqui alguien donde gente tio tia chico chica necesito estoy".split())


def detect_lang(norm: str, current: str | None) -> str:
    toks = norm.split()
    en = sum(1 for w in toks if w in _EN)
    es = sum(1 for w in toks if w in _ES)
    if current is None:
        return "en" if en > es else "es"
    if en >= es + 2 or (en > es and es == 0 and len(toks) <= 3):
        return "en"
    if es >= en + 2 or (es > en and en == 0 and len(toks) <= 3):
        return "es"
    return current


# ---------------------------------------------------------------------------- intenciones
ORDER = re.compile(
    r"\bevacu\w+|\bdesaloj\w+|para[dr]? el (concierto|festival|show)|det(en|ened) el (concierto|festival)|stop the (show|concert|music)|"
    r"abr[ea]d? (las|todas las) puertas|open (the|all) gates|cerrad? (la|las|el) (puerta|puertas|recinto)|close the gates|"
    r"manda[dr]? (a )?tod[oa]s|send (all|every)\w*|llama[dr]? al 112|call 911|te ordeno|os ordeno|i order you|es una orden|"
    r"that s an order|soy (el|la) (director|directora|jefe|jefa|responsable|organizador|organizadora|promotor|dueno)|"
    r"i am the (director|manager|head|owner|organi[sz]er)|i m the (director|manager|head|owner|organi[sz]er)|"
    r"cancela\w* (el|la|todos|todas|los|las)|anula\w* (el|la|los|las) (aviso|avisos|despacho)")
ROLE = re.compile(
    r"ignora\w* (tus|las|todas|lo)|ignore (all|your|the|previous)|olvida\w* (tus|las|todo)|forget (your|all|everything)|"
    r"eres ahora|ahora eres|you are now|actua como|act as|pretend (to be|you)|haz(te)? pasar por|system prompt|"
    r"modo (desarrollador|dios|admin)|developer mode|jailbreak|\bdan\b|(dame|muestra|ensename|dime) (tu|tus|el) (prompt|instrucciones)|"
    r"(show|tell|give) me your (prompt|instructions)|repite (tus|las) instrucciones|a partir de ahora (eres|responde)")
CHITCHAT = re.compile(
    r"\bchiste|\bjoke|que tiempo hace|weather like|quien eres|who are you|como te llamas|your name|\bpoema|\bpoem\b|\breceta|recipe|"
    r"^(hola|buenas|hello|hi|hey|ey|que tal|buenos dias|buenas tardes|buenas noches|test|prueba|probando)( .{0,12})?$|"
    r"cuentame algo|tell me something|eres (un|una) (robot|bot|ia|maquina)|are you (a|an) (robot|bot|ai|human)|te quiero|i love you")
# Preguntas que el agente NO contesta: qué le pasa (diagnóstico) y cuánto tardan (promesa de tiempo).
DIAGNOSIS_Q = re.compile(r"(^|\b)(es|sera|puede ser|sera que es) (un|una) \w+|que (le|me|nos) (pasa|ocurre)|que tiene\b|es grave|"
                         r"se va a morir|se esta muriendo\b.*\bverdad|what s wrong|is (it|he|she|this) (a|an|serious|dying|going to)|"
                         r"what does (he|she) have")
ETA_Q = re.compile(r"cuanto (van a |va a |vais a )?tarda\w*|cuando (llega|vienen|viene)\w*|cuanto (falta|queda)|tardan mucho|"
                   r"how long|when (will|are) (they|you|he|she)|how many minutes|\beta\b")
LAUGH = re.compile(r"\bja(ja)+\b|\bje(je)+\b|\bjaj\w*|\bha(ha)+\b|\blol\b|\bxd+\b|\blmao\b")
ALL_CLEAR = re.compile(
    r"falsa alarma|false alarm|era (una )?broma|es (una )?broma|it was a joke|just kidding|\bjk\b|"
    r"never mind|nevermind|olvidalo|ya no hace falta|no longer needed|ya esta (todo )?(resuelto|solucionado)|all good now|"
    r"no era nada|it was nothing")     # «me he equivocado» NO está: suele ser una corrección («espera, sí respira»)
DUNNO = re.compile(
    r"\bno (lo )?se\b|\bni idea|no tengo (ni )?idea|no estoy segur\w*|no sabria|no sabemos|i don t know|\bdont know|\bdunno|"
    r"\bnot sure|\bno idea|\bidk\b|no (lo )?veo bien|no puedo (ver|saber)|can t (see|tell)|no sabria decir")
# «no sé si respira»: la duda es sobre lo que viene detrás, no una respuesta.
DUNNO_ABOUT = re.compile(
    r"\b(?:no (?:lo )?se|no estoy segur\w*(?: de)?|no sabemos|i don t know|not sure|can t tell|no puedo (?:ver|saber)|no veo)"
    r"\s+(?:si|if|whether)\s+((?:\w+\s?){1,6})")
LEAVING = re.compile(r"tengo que (irme|colgar|dejarte)|me (voy|tengo que ir)|no puedo (seguir|hablar)|i have to go|gotta go|"
                     r"i can t (talk|stay)|\badios\b|\bbye\b|hasta luego")
DISTRESS = re.compile(r"socorro|\bayuda\w*|por favor|dios mio|madre mia|\bhelp\b|\bplease\b|oh my god|\bomg\b|se muere|"
                      r"se esta muriendo|\brapido\b|\bhurry\b|\bya\b.*\bya\b|\bcorred\b|dying|\bsos\b|\bjoder\b|\bmierda\b")
CONNECTOR = re.compile(r"\b(?:ademas|tambien|por otro lado|otra cosa|aparte|y luego|y otra|also|another thing|and also|as well|plus)\b")
SPLIT = re.compile(r"[.;!?\n]+|\s+(?:y|and|e)\s+|\b(?:ademas|tambien|por otro lado|otra cosa|aparte|also|another thing|as well|plus)\b")

# Un «sí» al principio vale aunque siga texto («yes I think so»). Un «no» solo si va suelto o con una coletilla conocida:
# «no respira» NO es un no a la pregunta que estaba en el aire.
_YES = re.compile(r"^\s*(?:si+|sip|vale|claro|afirmativo|correcto|exacto|eso es|asi es|yes|yeah|yep|yup|yess+|aja|ok|okay|"
                  r"creo que si|me parece que si|i think so|affirmative|right|ahora si)\b")
_NO = re.compile(r"^\s*(?:no+|nop|nope|nah|que va|negativo|para nada|en absoluto|creo que no|me parece que no|"
                 r"i don t think so|negative|not really|not yet|de momento no|por ahora no|todavia no|aun no|no mucho|no tanto|"
                 r"not much|no creo|no que yo sepa|not that i know)\s*(?:$|[,.;:!]|\bno\b)"
                 r"|^\s*no\s+(?:ningun\w*|nada|nadie|none|nobody|he s|she s|he is|she is|they)\b")


def bare_yes_no(low: str) -> bool | None:
    """Sí o no «sueltos» al principio del mensaje («no, no respira», «sí»). «no respira» NO es un no suelto."""
    s = re.sub(r"[¿¡]", "", low.replace("'", " ")).strip()
    if DUNNO.match(normalize(s)):
        return None
    if _YES.search(s):
        return True
    if _NO.search(s):
        return False
    return None


def is_distressed(raw: str, norm: str) -> bool:
    letters = [c for c in raw if c.isalpha()]
    caps = sum(1 for c in letters if c.isupper()) / len(letters) if len(letters) >= 8 else 0.0
    return caps > 0.6 or raw.count("!") >= 3 or bool(DISTRESS.search(norm))


# ---------------------------------------------------------------------------- conceptos
@dataclass(frozen=True)
class Concept:
    id: str
    aliases: tuple[str, ...]          # trozos del id de slot que apuntan a este concepto
    yes: str
    no: str
    fact: tuple[str, str]             # frase para Mando (sí, no): redactada para que su parser la entienda
    ack_es: tuple[str, str]           # lo que se le repite a la persona (sí, no)
    ack_en: tuple[str, str]
    weak_no: str = ""                 # indicio, no afirmación («se ha desmayado» → de entrada no responde)
    yes_first: bool = False           # el patrón afirmativo contiene un «no» («no puedo moverme»)


def _c(id_, aliases, yes, no, fact, ack_es, ack_en, **kw) -> Concept:
    return Concept(id_, tuple(aliases), yes, no, fact, ack_es, ack_en, **kw)


CONCEPTS: list[Concept] = [
    # va ANTES que `breathing`: en un slot «le cuesta respirar» el sí es el peligro, no al revés
    _c("breathing_trouble", ("breathing_trouble", "trouble", "difficult", "dificultad", "short_of_breath"),
       r"le cuesta respirar?|no puede respirar?|no puedo respirar?|se ahoga|se esta ahogando|respira (muy )?mal|pitidos|"
       r"le falta el aire|can t breathe|cannot breathe|trouble breathing|struggling to breathe|wheez|short of breath|no respir",
       r"respira bien|respira normal|breathing (fine|ok|okay|normally|well)",
       ("le cuesta respirar", "con respiración normal"), ("le cuesta respirar", "respira bien"),
       ("trouble breathing", "breathing fine"), yes_first=True),
    _c("breathing", ("breath", "respir"),
       r"(?<!puede )(?<!puedo )(?<!podemos )(?<!cuesta )\brespira\b|esta respirando|is breathing|s breathing|still breathing|"
       r"breathing (fine|ok|okay|normally|well)|\bbreathes\b",
       r"no respir|no esta respirando|sin respirar|dejado de respirar|no le noto (la )?respiracion|sin pulso|no tiene pulso|"
       r"not breathing|isn t breathing|stopped breathing|doesn t breathe|no pulse|no breathing|not breathe",
       ("con respiración normal", "no respira"), ("respira", "no respira"), ("breathing", "not breathing")),
    _c("responsive", ("respons", "conscious", "conscien", "awake", "responde", "alert"),
       r"\bconsciente|\bresponde\b|me responde|esta despiert|\bhabla\b|esta hablando|me contesta|ya se ha (levantado|despertado)|"
       r"se ha despertado|\bconscious|\bawake\b|\bresponsive|is responding|\bresponds\b|is talking|\balert\b|woke up",
       r"no responde|no reacciona|inconscient|no se despierta|no despierta|no se mueve|no contesta|no esta (consciente|despiert)|"
       r"sin conocimiento|perdido el conocimiento|unconscious|unresponsive|not respond|doesn t respond|isn t respond|"
       r"passed out|won t wake|not waking|not moving|isn t moving|out cold|not conscious|not awake",
       ("consciente", "inconsciente, no responde"), ("responde", "no responde"), ("responding", "not responding"),
       weak_no=r"desmay|desvanec|desplomad|fainted|collapsed|blacked out"),
    _c("heavy_bleeding", ("heavy", "severe_bleed", "abundant", "hemorr", "mucho"),
       r"sangra much|mucha sangre|muchisima sangre|no para de sangrar|sangra sin parar|a chorro|bleeding (a lot|heavily|badly)|"
       r"lots? of blood|won t stop bleeding|so much blood|hemorragia",
       r"sangra poco|poca sangre|no sangra much|un poco de sangre|not (bleeding )?(much|a lot)|a little blood|no es mucha|"
       r"no sangra|not bleeding|no blood",
       ("sangra mucho", "sangrado leve"), ("sangra mucho", "sangra poco"), ("heavy bleeding", "little bleeding")),
    _c("bleeding", ("bleed", "sangr", "blood"),
       r"sangr|bleed|\bblood", r"no sangra(?! much)|sin sangre|not bleeding|no blood|isn t bleeding",
       ("está sangrando", "sin hemorragia"), ("sangra", "no sangra"), ("bleeding", "not bleeding")),
    _c("confused", ("confus", "disorient", "mental", "desorient"),
       r"confus|desorientad|dice cosas raras|no sabe donde esta|delira|incoheren|disorient|not making sense|talking nonsense|"
       r"doesn t know where",
       r"no esta confus|habla (bien|normal)|esta lucid|not confused|making sense|\blucid|coherent",
       ("está confusa y desorientada", "orientada"), ("está confusa", "no está confusa"), ("confused", "not confused")),
    _c("hot_skin", ("hot", "skin", "caliente", "piel"),
       r"muy caliente|piel (muy )?(caliente|roja|seca)|esta ardiendo|\bquema\b|no suda|burning up|very hot|hot skin|"
       r"skin is (very )?(hot|red|dry)|not sweating",
       r"no esta (muy )?caliente|piel (fria|normal|fresca)|esta fri[oa]|not hot|skin is (cool|normal|cold)|suda mucho",
       ("piel muy caliente", "piel a temperatura normal"), ("piel muy caliente", "piel normal"), ("very hot skin", "skin not hot")),
    _c("seizure", ("seiz", "convuls"),
       r"convulsi|epilep|seizure|\bfitting\b|espasmos|se sacude",
       r"no (tiene |hay )?convulsi|sin convulsi|no seizure|not (having a )?seiz",
       ("convulsiones", "sin movimientos anormales"), ("convulsiones", "sin convulsiones"), ("seizure", "no seizure")),
    _c("weapon", ("weapon", "arma", "knife"),
       r"navaja|cuchillo|\barmas?\b|armad[oa]|pistola|botella rota|machete|\bknife|\bknives|\bguns?\b|weapon|broken bottle",
       r"sin armas?|no (hay|llevan|tienen|he visto|veo|vi) (ningun[a]? )?(armas?|nada)|ningun arma|no weapons?|unarmed|"
       r"didn t see (any|a) weapons?",
       ("hay un arma", "sin armas a la vista"), ("hay un arma", "sin armas"), ("a weapon", "no weapon")),
    _c("injured", ("injur", "herid", "hurt", "casualt", "danger", "peligro"),
       r"herid|sangr|injur|\bhurt\b|bleed|golpe en la cabeza|lesionad|wounded|en peligro|in danger",
       r"no hay (ningun |nadie )?herid|nadie (esta )?herid|sin heridos|ningun herido|no one (is |was )?(hurt|injured)|"
       r"nobody (is |was )?(hurt|injured)|no injur|nadie en peligro|no one (is )?in danger",
       ("hay heridos", "sin heridos"), ("hay heridos", "sin heridos"), ("someone hurt", "nobody hurt")),
    _c("ongoing", ("ongoing", "still", "active", "sigue", "continu"),
       r"siguen|se estan (pegando|peleando)|todavia|aun se|still (fighting|going|at it)|ahora mismo|right now",
       r"ya (han|se han|ha) (parado|separado|ido|terminado|acabado)|ya paro|se han ido|los han separado|has stopped|it s over|"
       r"they (have )?left|ya (termino|acabo)|stopped fighting|broken? (it )?up",
       ("la pelea sigue", "ya se han separado"), ("sigue", "ya ha parado"), ("still going", "it has stopped")),
    _c("people_down", ("fallen", "people_down", "falling", "caid", "on_ground", "en_el_suelo", "down"),
       r"gente (cayendo|en el suelo|caida|cayendose)|se cae la gente|se (han|estan) ca(ido|yendo)|han caido|"
       r"alguien (en el|se ha caido al) suelo|personas? en el suelo|people (are )?(falling|on the ground|down|fell)|"
       r"someone (fell|is down|on the ground)|pisote|trampl",
       r"nadie (se ha caido|en el suelo|caido)|no hay (nadie|gente) en el suelo|no one (has fallen|fell|is down|on the ground)|"
       r"nobody (fell|is down|on the ground)|todos de pie|everyone (is )?standing",
       ("gente cayendo al suelo", "nadie en el suelo"), ("hay gente en el suelo", "nadie en el suelo"),
       ("people on the ground", "nobody on the ground")),
    _c("pressure", ("pressure", "cant_move", "trapped", "crush", "cannot_move", "movement", "stuck", "presion", "atrapad"),
       r"no (puedo|podemos|se puede|pueden) (respirar?|mover|salir)|no me puedo mover|no nos podemos mover|nos ahogamos|aplast|"
       r"atrapad|mucha presion|nos aprietan|can t (breathe|move|get out)|cannot (breathe|move)|\bcrush|trapped|\bstuck\b|squeez|"
       r"pushed against",
       r"se pueden? mover|(nos )?podemos mover|puedo mover|podemos salir|se puede salir|can (still )?move|not (stuck|trapped)|"
       r"able to move",
       ("no se pueden mover, mucha presión, riesgo de aplastamiento", "la gente todavía puede moverse"),
       ("no os podéis mover", "os podéis mover"), ("you cannot move", "you can move"), yes_first=True),
    _c("can_move", ("can_move", "able_to_move", "puede_mover"),
       r"(nos )?podemos mover|puedo mover|se pueden? (mover|salir)|podemos salir|can (still )?move|able to move",
       r"no (puedo|podemos|se puede|pueden) (mover|salir)|no me puedo mover|no nos podemos mover|atrapad|can t (move|get out)|"
       r"cannot move|trapped|\bstuck\b",
       ("la gente todavía puede moverse", "no se pueden mover, mucha presión"), ("te puedes mover", "no te puedes mover"),
       ("you can move", "you cannot move")),
    _c("caller_inside", ("caller_in", "inside", "dentro", "affected"),
       r"estoy (dentro|en medio|atrapad)|estamos (dentro|en medio|atrapad)|me estan (aplastando|empujando)|nos estan|"
       r"no (puedo|podemos) (respirar?|mover|salir)|i m (inside|in the middle|stuck|trapped)|we re (inside|stuck|trapped)|"
       r"i can t (breathe|move)|we can t (breathe|move)",
       r"lo veo desde|estoy fuera|desde (fuera|lejos|arriba|la grada)|i m outside|watching from|from (outside|above)",
       ("quien avisa está dentro", "quien avisa lo ve desde fuera"), ("estás dentro", "lo ves desde fuera"),
       ("you are inside", "you are outside"), yes_first=True),
    _c("safe", ("safe", "segur", "salvo"),
       r"estoy (a salvo|segur[oa]|bien|con (un[ao]s? |mi |mis )?amig|acompanad)|sitio seguro|lugar seguro|i m safe|i am safe|"
       r"safe (place|now)|with (a |my )?friends?",
       r"no estoy (a salvo|segur|bien)|me (esta )?sig(ue|uiendo)|sigue aqui|esta aqui|tengo miedo|not safe|still here|"
       r"following me|i m scared|estoy sol[oa]",
       ("está en un sitio seguro", "NO está en un sitio seguro: que vaya seguridad"), ("", ""), ("", "")),
    _c("police_consent", ("police", "policia", "denunc"),
       r"quiero denunciar|llama\w* a la policia|quiero (que venga |a )?la policia|que venga la policia|call the police|"
       r"want (the )?police|press charges",
       r"no quiero (denunciar|policia|a la policia|que venga)|sin policia|nada de policia|no police|don t (call|want) (the )?police",
       ("consiente que se avise a la policía", "NO quiere que se avise a la policía"), ("", ""), ("", "")),
    _c("intox", ("alcohol", "drug", "intox", "substance", "bebid"),
       r"ha bebido|he bebido|borrach|alcohol|\bdrogas?\b|pastilla|ha tomado algo|se ha metido|\bdrunk|took something|\bdrugs\b|"
       r"\bpills\b|been drinking",
       r"no ha (bebido|tomado)|sin alcohol|no ha tomado nada|hasn t (drunk|taken)|not drunk|no drugs",
       ("ha tomado algo", "sin consumo conocido"), ("ha tomado algo", "no ha tomado nada"), ("took something", "took nothing")),
    _c("caller_has_child", ("has_child", "child_with", "found", "con_el_menor", "with_caller"),
       r"he encontrado|hemos encontrado|esta conmigo|lo tengo|la tengo|aqui conmigo|nin[oa] sol[oa]|found a (child|kid|boy|girl)|"
       r"is with me|(child|kid) alone",
       r"he perdido|hemos perdido|no (lo |la )?encuentr|se ha perdido|ha desaparecido|lost my|can t find|\bmissing\b|i lost|we lost",
       ("el menor está con quien avisa", "buscan a un menor perdido"), ("", ""), ("", "")),
]
_BY_ID = {c.id: c for c in CONCEPTS}
# Los patrones negativos empiezan SIEMPRE en principio de palabra: «uno sangra» contiene «no sangra» y «alguno respira»
# contiene «no respira»; sin este límite, una frase afirmativa se leería como su contraria.
_W = r"(?<![a-z0-9])"
_RX: dict[str, tuple[re.Pattern, re.Pattern, re.Pattern | None]] = {
    c.id: (re.compile(f"{_W}(?:{c.yes})" if c.yes_first else c.yes), re.compile(f"{_W}(?:{c.no})"),
           re.compile(c.weak_no) if c.weak_no else None) for c in CONCEPTS}

NUMBER_ALIASES = {"count": ("count", "people", "victim", "how_many", "afectad", "persona", "number", "cuant", "involved"),
                  "age": ("age", "edad")}
TEXT_ALIASES = {"clothing": ("cloth", "ropa", "vest", "wearing", "appearance"),
                "what": ("what", "happen", "descri", "problem", "que_", "situation")}
_AGE = re.compile(r"(\d{1,2}) (?:anos|ano|anitos|years?|yo\b|meses|months)|tiene (\d{1,2})\b|(?:is|he s|she s) (\d{1,2})\b")
_CLOTHES = re.compile(r"(?:lleva(?:ba)?|viste|vestid[oa] (?:de|con)|va (?:de|con)|wearing|dressed in|has an?)\s+([^.;!?\n]{3,80})")
_NUMBER = re.compile(r"\b(\d{1,3})\b")
POINT = re.compile(r"\b(detras de|delante de|junto a|al lado de|cerca de|enfrente de|frente a|a la altura de|debajo de|encima de|"
                   r"next to|near|behind|in front of|by the|beside|close to|under)\s+"
                   r"((?:(?!\s(?:y|and|pero|but|que|porque|no|hay)\s)[a-z0-9ñ ]){3,50})")


# Opciones de los slots `enum`: qué palabras de la persona apuntan a cada opción. La clave es el id de la opción (los
# protocolos las nombran en inglés). Lo que no esté aquí se casa por el propio nombre de la opción o por su número.
ENUM_SYNONYMS: dict[str, str] = {
    "normal": r"\bnormal|respira bien", "gasping_or_noisy": r"boquea|ronc|ronqu|ruidos?|jadea|gasp|snor|nois",
    "none": r"\bno respira|\bnada\b|ningun[oa]|not breathing|\bnone\b",
    "eating": r"\bcomia|comiendo|atragant|eating|chok", "sting_or_allergy": r"\bpico\b|picadura|avispa|abeja|alergi|sting|allerg|\bbee\b|wasp",
    "asthma": r"\basma|asthma|inhalador|inhaler", "crushed_in_crowd": r"aplast|apretuj|multitud|crush|crowd", "smoke": r"\bhumo|smoke",
    "fall": r"\bcaid|\bcaer|\bcayo|se ha caido|\bfall|\bfell", "glass_or_cut": r"cristal|vidrio|\bvaso|botella|\bcorte|cortado|glass|\bcut\b",
    "weapon_or_assault": r"navaja|cuchillo|\barma|agresi|pelea|apunal|knife|stab|assault|fight", "crush": r"aplast|crush",
    "ground_level": r"tropez|resbal|tripped|slipped", "from_height": r"altura|\bgrada|escalera|\btorre|desde (lo alto|arriba)|height|ladder",
    "hit_by_object": r"le ha (dado|caido)|le cayo|golpeado|hit by|struck by",
    "worse": r"a mas|\bpeor|empeora|cada vez mas|worse", "same": r"\bigual|\bsame", "easing": r"afloja|mejor|a menos|easing|better",
    "entering": r"\bentra|entering|going in", "leaving": r"\bsal(e|en|iendo)\b|leaving|going out", "both": r"\bambos|las dos|\bboth",
    "flames": r"llamas|\bfuego|flames|\bfire", "smoke_only": r"\bhumo|smoke", "smell_burning": r"huele a quemado|olor a quemado|burning smell",
    "smell_gas": r"\bgas\b", "moving": r"se mueve|tambale|moving|sway", "partly_fallen": r"una parte|parcial|partly",
    "fallen": r"se ha caido|\bcaid[oa]|fallen|collapsed", "stage": r"escenario|\bstage", "tower": r"\btorre|tower",
    "screen": r"pantalla|screen", "tent_or_canopy": r"\bcarpa|toldo|\btent|canopy", "fence_or_barrier": r"\bvalla|barrera|fence|barrier",
    "tree": r"\barbol|\btree", "other": r"\botr[ao]\b|\bother|amig", "open": r"aire libre|descubierto|in the open|outside",
    "under_tree": r"\barbol|\btree", "vehicle": r"\bcoche|vehiculo|\bcar\b|vehicle", "building": r"\bdentro|edificio|inside|building",
    "object": r"mochila|maleta|paquete|\bbolsa|\bobjeto|\bbulto|\bbag\b|package|backpack|object",
    "threat": r"amenaza|\bbomba|threat|\bbomb", "weapon": r"navaja|cuchillo|\barmas?\b|armad[oa]|pistola|knife|\bguns?\b|weapon",
    "me": r"\ba mi\b|\byo\b|\bme (ha|han)\b|\bmyself|\bto me\b",
    "found_child": r"he encontrado|hemos encontrado|esta conmigo|nin[oa] sol[oa]|menor sol[oa]|crio solo|found",
    "lost_my_child": r"he perdido|hemos perdido|no encuentr|se ha perdido|ha desaparecido|lost my|can t find|i lost|we lost",
    "with_person": r"estoy con|esta conmigo|with (him|her|them)", "looking_for_person": r"\bbusc|no encuentr|perdid|looking for|can t find",
    "seen": r"lo he visto|lo vi\b|lo estoy viendo|i saw|seen it", "told": r"me lo han|contado|dicen|he oido|told|heard",
    "lights": r"\bluces|\bluz\b|lights", "stage_sound": r"sonido|escenario|sound|stage", "food_stalls": r"\bbarras?\b|puestos|food",
    "payments": r"\bpago|datafono|\btpv|payment|card", "everything": r"\btodo\b|everything",
    "calm": r"tranquil|\bcalm", "restless": r"nervios|inquiet|restless", "pushing": r"empuj|pushing", "long": r"\blarga|\blong",
    "tense": r"tension|\btens[ao]|tense", "water": r"\bagua|water", "food": r"comida|\bfood", "ice": r"\bhielo|\bice\b",
    "medical_supplies": r"vendas|material|botiquin|medical", "empty": r"acabado|no queda|vacio|empty|run out|none left",
    "low": r"queda poco|\bpoco\b|\blow\b", "toilets": r"\bban[oa]s|aseos|\bwc\b|toilet", "barrier": r"\bvalla|barrera|barrier|fence",
    "flooding": r"inunda|charco|flood", "turnstile": r"\btornos?\b|turnstile", "one": r"\bun[oa]\b|solo un|\bone\b",
    "several": r"varios|varias|algun[oa]s|several", "all": r"\btod[oa]s\b|\ball\b",
}
_ENUM_RX = {k: re.compile(v) for k, v in ENUM_SYNONYMS.items()}


def detect_enum(options: list[Any], norm: str, pending: bool) -> Any:
    """Opción de un `enum`. Sin que se haya preguntado solo vale si UNA opción casa sin ambigüedad."""
    hits = []
    for i, o in enumerate(options):
        oid = o.get("id") if isinstance(o, dict) else o
        if oid == "unknown":
            continue
        names = [str(oid).replace("_", " ")]
        if isinstance(o, dict):
            names += [str(v) for v in (o.get("label") or {}).values()] if isinstance(o.get("label"), dict) else []
            names += [str(x) for x in o.get("match") or []]
        rx = _ENUM_RX.get(str(oid))
        if (rx is not None and rx.search(norm)) or any(normalize(n) and re.search(r"\b" + re.escape(normalize(n)) + r"\b", norm) for n in names):
            hits.append(oid)
        elif pending and norm.strip() == str(i + 1):
            hits.append(oid)
    if len(hits) == 1 or (pending and hits):
        return hits[0]
    return None


def concept_for(slot_id: str, slot_type: str) -> str | None:
    """Concepto que corresponde a un slot, por su id. Así los protocolos reales no tienen que usar mis nombres."""
    sid = slot_id.lower()
    table: dict[str, tuple[str, ...]]
    if slot_type == "bool":
        if sid in _BY_ID:
            return sid
        for c in CONCEPTS:
            if any(a in sid for a in c.aliases):
                return c.id
        return None
    table = NUMBER_ALIASES if slot_type == "number" else TEXT_ALIASES if slot_type == "text" else {}
    for cid, aliases in table.items():
        if sid == cid or any(a in sid for a in aliases):
            return cid
    return None


def detect_bool(concept: str, norm: str) -> tuple[bool, float] | None:
    """(valor, confianza) si el mensaje habla de este concepto."""
    yes, no, weak = _RX[concept]
    c = _BY_ID[concept]
    hedged = 0.55 if HEDGE.search(norm) else 0.85

    def _yes() -> tuple[bool, float] | None:
        m = yes.search(norm)
        if not m:
            return None
        return (False, hedged) if NEGATOR.search(norm[:m.start()]) else (True, hedged)

    def _no() -> tuple[bool, float] | None:
        return (False, hedged) if no.search(norm) else None

    for probe in ((_yes, _no) if c.yes_first else (_no, _yes)):
        hit = probe()
        if hit:
            return hit
    if weak is not None and weak.search(norm):
        return False, 0.6
    return None


def detect_number(concept: str, norm: str) -> int | None:
    if concept == "age":
        m = _AGE.search(norm)
        return int(next(g for g in m.groups() if g)) if m else None
    if concept == "count" and COUNT is not None:
        m = COUNT.search(norm)
        if m:
            g = m.group(1)
            return int(g) if g.isdigit() else NUM_WORDS.get(g)
    return None


def any_number(norm: str) -> int | None:
    m = _NUMBER.search(norm)
    if m:
        return int(m.group(1))
    for w in norm.split():
        if w in NUM_WORDS and w not in ("un", "una", "uno", "a"):
            return NUM_WORDS[w]
    return NUM_WORDS.get(norm.strip()) if norm.strip() in ("un", "una", "uno", "one") else None


def detect_text(concept: str, low: str) -> str | None:
    if concept == "clothing":
        m = _CLOTHES.search(low)
        return m.group(1).strip() if m else None
    return None


def match_phrases(match: dict[str, Any] | None, norm: str) -> bool | None:
    """Extensión opcional de un slot bool: `"match": {"yes": {"es": [...], "en": [...]}, "no": {...}}`."""
    if not isinstance(match, dict):
        return None
    for key, val in (("no", False), ("yes", True)):
        block = match.get(key) or {}
        phrases = [p for v in (block.values() if isinstance(block, dict) else [block]) for p in (v if isinstance(v, list) else [v])]
        if any(normalize(str(p)) and normalize(str(p)) in norm for p in phrases):
            return val
    return None


def fact(concept: str | None, slot_id: str, value: Any) -> str:
    """Frase para el texto del `Report`. El parser de Mando la va a leer: nada de «respira: no»."""
    if concept in _BY_ID and isinstance(value, bool):
        return _BY_ID[concept].fact[0 if value else 1]
    name = slot_id.replace("_", " ")
    if concept == "count" and isinstance(value, (int, float)):
        return f"{int(value)} personas afectadas" if value > 1 else ""
    if concept == "age" and isinstance(value, (int, float)):
        return f"edad {int(value)} años"
    if concept == "clothing":
        return f"viste: {value}"
    if concept == "what":
        return ""                       # el texto original ya va citado en el aviso
    if isinstance(value, bool):
        return f"{name} sí" if value else f"sin {name}"   # «sin» delante: el negador de Mando lo entiende
    return f"{name}: {value}"


def ack(concept: str | None, value: Any, lang: str) -> str:
    if concept in _BY_ID and isinstance(value, bool):
        c = _BY_ID[concept]
        return (c.ack_en if lang == "en" else c.ack_es)[0 if value else 1]
    return ""
