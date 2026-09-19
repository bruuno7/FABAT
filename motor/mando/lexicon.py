"""Léxico de Mando: REGLAS escritas a mano, no un modelo. Tipos de incidente con su respuesta de protocolo,
señales genéricas para lo que no se reconoce, y alias de zonas.

Procedencia (importa, porque el banco de pruebas tiene una partición que el agente «nunca ha visto»):
- Nada de este fichero sale de `motor/cases/` (ni taxonomía, ni plantillas de frases). Los patrones son vocabulario
  general de emergencias escrito a mano; los nombres de zona salen del enunciado y de `motor/world/festival.json`;
  `crush_risk`, `water_out` y `structure_risk` son los tipos que el simulador genera solo (README de `motor/world`).
- Lo que NO está aquí no se adivina: `generic_family()` clasifica por familia y señales, el tipo queda como
  `unknown_<familia>`, baja la confianza y la política es conservadora (ver `planner._ask_first`).
- `test_mando.TestNoHeldoutLeak` falla si aparece aquí un tipo de la partición solo-heldout.

Los patrones se aplican sobre texto normalizado: minúsculas, sin tildes, sin puntuación. Son raíces:
«desmay» cubre desmayo, desmayado, desmayó.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..contracts import Family


@dataclass(frozen=True)
class TypeSpec:
    type: str
    family: Family
    severity: int
    needs: dict[str, int]
    deadline: int | None        # minutos desde que se abre; estimación de Mando, no la verdad del caso
    group: str                  # tipos del mismo grupo se correlacionan como un solo incidente
    patterns: tuple[str, ...] = ()
    weak: tuple[str, ...] = ()  # patrones que también son contexto («en la cola de…»): solo cuentan si no hay otro tipo
    life_threat: bool = False   # se despacha aunque la confianza sea baja
    threat: bool = False        # amenaza: Mando no decide, escala a la persona
    sitewide: bool = False      # no necesita zona para actuar
    heat: bool = False          # cuenta para el patrón de calor
    reserved: bool = False      # caso sensible: ni megafonía ni detalle en pantalla pública
    notify: tuple[str, ...] = ()   # security_lead, medical_lead, production, violet_point, coordinator, gates, all_leads
    external: str = ""          # ambulance | police | fire | transport (siempre con aprobación)
    restrict: bool = False
    reroute: bool = False
    broadcast: str = ""         # mensaje de megafonía; vacío = NO se usa megafonía
    stop_show: bool = False     # se PROPONE (aprobación)
    evacuate: bool = False      # se PROPONE (aprobación)
    close: bool = False         # se PROPONE cerrar la zona (aprobación)


M, C, W, A, S, I, R, N, X = (Family.MEDICAL, Family.CROWD, Family.WEATHER, Family.AGGRESSION, Family.SUPPLY,
                             Family.INFRA, Family.RESOURCE, Family.INFO, Family.EXTERNAL)

CALM = "Por favor, mantened la calma y seguid las indicaciones del personal."
WATER = "Hace mucho calor: bebed agua a menudo y buscad sombra. Hay puntos de agua gratis al norte y al sur."
SPACE = "Por favor, dad un paso atrás y dejad espacio. Hay accesos y zonas con más sitio."

# Combinaciones de vocabulario, con contexto próximo: no son frases del banco.
_GAP = r"(?:\s+\w+){0,6}\s+"
_STRUCTURE = r"\b(?:valla|vallado|barrera|carpa|torre|estructura|pantalla|soporte|escenario|plataforma|rampa|suelo|aseos|fence|barrier)\b"
_DAMAGE = r"(?:caid[oa]|rot[oa]|cedi\w*|cede|doblad\w*|doblao|inclinad\w*|cruje|hund\w*|suelt\w*|soltad\w*|tambalea\w*|down\b|broke\w*)"
_BAG = r"\b(?:mochila|maleta|bolsa|paquete|bulto|objeto|bag|package|backpack|suitcase)\b"
_SUSPECT = r"(?:sin duen\w*|abandonad\w*|sospechos\w*|rar[oa]\b|nadie lo recoge|unattended|weird|unclaimed)"
_STAFF_WORD = r"(?:personal|staff|stewards?|seguridad|voluntari\w*|sanitari\w*|medic\w*|tecnic\w*|camarer\w*|supervisor|crew|relevo)"
_STOCK = r"(?:agua|comida|hielo|botellas?|vasos?|papel|jabon|vendas?|suero|material|kits?|snacks?|cubatas?|tallas?)\b"
_SHORTAGE = r"(?:no (?:\w+ ){0,2}(?:hay|queda\w*)|sin|faltan?|agotad\w*|acab\w*)"


def _t(type_, family, severity, needs, deadline, group, patterns, **kw) -> TypeSpec:
    return TypeSpec(type_, family, severity, needs, deadline, group, tuple(patterns), **kw)


SPECS = [
    # ------------------------------------------------------------------ médicos
    _t("cardiac_arrest", M, 10, {"medical": 1, "ambulance": 1}, 5, "person_down", [
        r"no respira", r"no esta respirando", r"sin pulso", r"no tiene pulso", r"par[ao]da? cardi", r"paro cardi",
        r"infarto", r"ataque al corazon", r"\brcp\b", r"\bdesa\b", r"desfibrilador", r"not breathing",
        r"isn t breathing", r"stopped breathing", r"no pulse", r"cardiac arrest", r"heart attack", r"\bcpr\b",
        r"ne respir\w* p", r"arret cardiaque", r"crise cardiaque", r"atmet nicht", r"herzstillstand",
        r"herzinfarkt", r"nao respira", r"sem pulso"], life_threat=True, notify=("medical_lead",), external="ambulance"),
    _t("unconscious_person", M, 9, {"medical": 1}, 8, "person_down", [
        r"inconscient", r"no reacciona", r"no responde\b", r"no se mueve", r"no despierta", r"no se despierta",
        r"tirad[oa] en el suelo", r"tendid[oa] en el suelo", r"unconscious", r"unresponsive",
        r"not responding", r"passed out", r"collapsed", r"not moving", r"ne reagit p", r"bewusstlos",
        r"reagiert nicht", r"desacordad", r"nao reage"], life_threat=True),
    _t("breathing_difficulty", M, 8, {"medical": 1}, 8, "person_down", [
        r"no puede respirar", r"le cuesta respirar", r"se ahoga", r"se esta ahogando", r"atragant", r"\basma",
        r"can t breathe", r"cannot breathe", r"choking", r"asthma", r"n arrive pas a respirer",
        r"bekommt keine luft", r"nao consegue respirar"], life_threat=True),
    _t("fainting", M, 6, {"medical": 1}, 12, "person_down", [
        r"desmay", r"desvanec", r"se ha caido redond", r"perdio el conocimiento", r"ha perdido el conocimiento",
        r"perdida de conocimiento", r"faint", r"blacked out", r"evanoui", r"ohnmacht", r"ohnmachtig",
        r"desmai"], life_threat=True, heat=True),
    _t("seizure", M, 8, {"medical": 1}, 8, "person_down", [r"convulsi", r"epilep", r"seizure", r"krampfanfall"]),
    _t("allergic_reaction", M, 8, {"medical": 1}, 8, "medical_other", [
        r"alergi", r"anafila", r"allergic", r"anaphyla", r"se le hincha", r"allergie"]),
    _t("heat_stroke", M, 7, {"medical": 1}, 15, "heat", [
        r"golpes? de calor", r"insolacion", r"deshidrat", r"heat ?stroke", r"sunstroke", r"heat exhaustion",
        r"dehydrat", r"coup de chaleur", r"hitzschlag", r"insolacao"], heat=True),
    _t("intoxication", M, 6, {"medical": 1}, 15, "intox", [
        r"sobredosis", r"overdose", r"intoxic", r"borrach", r"coma etilico", r"ha tomado algo", r"pastillas",
        r"\bdrog(?:as?|ad[oa]s?)\b", r"burundanga", r"le han echado algo", r"\bdrunk\b", r"spiked", r"ivre\b", r"betrunken"]),
    _t("injury", M, 5, {"medical": 1}, 20, "injury", [
        r"herid", r"sangr", r"fractura", r"se ha caido", r"se cayo", r"esguince", r"\bcortes?\b", r"brecha",
        r"golpe en la cabeza", r"tobillo", r"quemadura", r"injur", r"bleed", r"broken (leg|arm|ankle)",
        r"\bhurt\b", r"wounded", r"blesse", r"verletzt", r"ferid"]),
    _t("dizziness", M, 4, {"medical": 1}, 25, "heat", [
        r"\bmare[oa]", r"se encuentra mal", r"se siente mal", r"vomit", r"dizzy", r"feeling sick",
        r"feels sick", r"nausea", r"malaise", r"schwindel", r"tontura"], heat=True),

    # ------------------------------------------------------------------ multitud
    _t("crush_risk", C, 9, {"security": 2, "medical": 1}, 6, "crowd", [
        r"aplast", r"avalancha", r"estampida", r"gente cayendo", r"se cae (la )?gente", r"nos ahogamos",
        r"no podemos respirar", r"\bcrush", r"stampede", r"trampl", r"ecras", r"bousculade", r"gedrange",
        r"esmag", r"pisote"], restrict=True, reroute=True, broadcast=SPACE, notify=("security_lead",)),
    _t("crowd_surge", C, 8, {"security": 2}, 10, "crowd", [
        r"empuj", r"mucha presion", r"apretad", r"no cabe", r"demasiada gente", r"muchisima gente",
        r"mucha gente", r"agobi", r"abarrotad", r"desbord", r"pushing", r"too many people", r"overcrowd",
        r"packed", r"trop de monde", r"zu viele", r"muita gente"], reroute=True, broadcast=SPACE),
    _t("gate_saturation", C, 7, {"security": 1}, 20, "crowd", [
        r"atasc", r"colaps", r"cola enorme", r"no avanza", r"saturad", r"tapon", r"embudo", r"bottleneck", r"jammed",
        r"cuello de botella", r"agolp",
        r"gridlock", r"embouteill", r"\bstau\b", r"\bfila enorme"],
       weak=(r"\bcolas?\b", r"\btornos?\b", r"\bqueues?\b", r"turnstile"), reroute=True,
       broadcast="Este acceso está lleno: hay otras puertas con menos espera."),
    _t("lost_child", N, 5, {"security": 1}, 30, "lost", [
        r"nin[oa] (pequen[oa] )?(perdid|extraviad)", r"menor (perdid|extraviad)", r"perdido una? (nin[oa]|menor|hij[oa])", r"(se )?ha perdido (a )?(su|mi) hij", r"no encuentr\w+ a (mi|su) hij",
        r"nin[oa] sol[oa]", r"lost (child|kid|boy|girl)", r"missing (child|kid)", r"enfant perdu",
        r"kind verloren", r"crianca perdida"], reserved=True, notify=("gates", "security_lead")),

    # ------------------------------------------------------------------ meteorología
    _t("storm", W, 7, {}, 20, "weather", [
        r"tormenta", r"\brayos?\b", r"relampag", r"truen", r"lightning", r"thunder", r"\bstorm", r"orage",
        r"gewitter", r"tempestade"], sitewide=True, stop_show=True, notify=("production",),
       broadcast="Se acerca una tormenta: alejaos de torres, pantallas y estructuras."),
    _t("high_wind", W, 7, {"tech": 1}, 20, "weather", [
        r"viento", r"\brachas?\b", r"vendaval", r"\bwind", r"\bgusts?\b", r"vent fort", r"sturm",
        r"(?:sombrillas?|paraguas|lonas?|toldos?)" + _GAP + r"volando"],
       sitewide=True, restrict=True, notify=("production",)),
    _t("heavy_rain", W, 4, {}, 30, "weather", [
        r"lluvia", r"llov", r"lluev", r"diluvi", r"graniz", r"\brain", r"\bhail", r"pluie", r"\bregen", r"chuva",
        r"\bflood", r"encharc", r"\bbarro\b"],
       sitewide=True),
    _t("heat_wave", W, 6, {"logistics": 1}, 30, "heat_env", [
        r"ola de calor", r"calor extremo", r"calor insoportable", r"temperatura", r"heat ?wave",
        r"extreme heat", r"canicule", r"hitzewelle"], sitewide=True, broadcast=WATER, notify=("medical_lead",)),

    # ------------------------------------------------------------------ agresiones (nunca megafonía)
    _t("weapon", A, 9, {"security": 2}, 5, "violence", [
        r"navaja", r"cuchillo", r"\barmas?\b", r"armad[oa]", r"pistola", r"\bknife", r"\bguns?\b", r"weapon", r"apunal", r"\bstabb",
        r"couteau", r"messer", r"\bfaca\b"], threat=True, reserved=True, notify=("security_lead",), external="police"),
    _t("sexual_assault", A, 8, {"security": 1}, 8, "violence_sexual", [
        r"agresion sexual", r"abus[oa]", r"tocamient", r"(la|me|le) han tocado", r"violacion", r"violad",
        r"acos[oa]", r"punto violeta", r"sexual", r"harass", r"grop(?:ed|ing)", r"belastig",
        r"no (?:la|le|me) deja en paz"],
       reserved=True, notify=("violet_point",), external="police"),
    _t("fight", A, 6, {"security": 2}, 10, "violence", [
        r"pelea", r"se estan pegando", r"se pegan", r"punetazo", r"\bbronca", r"\brina\b", r"agresion",
        r"agredi", r"\bfight", r"brawl", r"punch", r"bagarre", r"schlagerei", r"\bbriga",
        r"paliza", r"pegand", r"\bhitting\b", r"\bassault\b"]),
    _t("theft", A, 3, {"security": 1}, 45, "theft", [
        r"\brob(?:o|an|a|ado|ando|aron)\b", r"hurt[oa]", r"carterista", r"me han quitado",
        r"stolen", r"\btheft", r"pickpocket", r"\bvole\b", r"gestohlen", r"roubo"]),

    # ------------------------------------------------------------------ suministros
    _t("water_out", S, 6, {"logistics": 1}, 20, "water", [
        r"no (hay|queda|sale) agua", r"sin agua", r"acab\w* el agua", r"falta agua", r"agua agotad",
        r"fuentes? secas?", r"0 litros", r"no water", r"out of water", r"water (ran|has run) out", r"plus d eau",
        r"kein wasser", r"sem agua"], reroute=True,
       broadcast="Este punto de agua está sin servicio unos minutos: hay agua en el otro punto."),
    _t("fuel_shortage", S, 5, {"logistics": 1}, 30, "fuel", [
        _SHORTAGE + _GAP + r"(?:combustible|gasoil|gasoleo|fuel|diesel)\b",
        r"combustible", r"gasoil", r"gasoleo", r"\bfuel\b", r"diesel"], notify=("production",)),
    _t("medical_supplies", S, 5, {"logistics": 1}, 30, "medsupply", [
        r"sin material", r"faltan? (vendas|suero|material|medic)", r"out of (bandages|supplies)",
        _SHORTAGE + _GAP + r"(?:vendas?|suero|material|kits?)\b"], notify=("medical_lead",)),
    _t("food_shortage", S, 3, {"logistics": 1}, 60, "food", [
        r"sin comida", r"no (?:\w+ ){0,2}queda comida", r"out of food", r"no (more )?food"]),

    # ------------------------------------------------------------------ infraestructura
    _t("fire", I, 9, {"security": 1, "tech": 1}, 5, "fire", [
        r"fuego", r"incendi", r"\bhumo\b", r"en llamas", r"\bllamas\b", r"\barde\b", r"ardiendo",
        r"huele a quemado", r"\bfire\b", r"smoke", r"flames", r"\bfeu\b", r"feuer", r"rauch", r"\bfogo\b",
        r"fumaca", r"\bconato\b", r"chisp", r"\bsparks?\b", r"cortocircuit", r"electrocut"], restrict=True, external="fire"),
    _t("structure_risk", I, 9, {"tech": 1, "security": 1}, 8, "structure", [
        _STRUCTURE + _GAP + _DAMAGE, r"soltad\w*" + _GAP + _STRUCTURE,
        r"(?:riesgo|peligro)" + _GAP + _STRUCTURE,
        r"se (esta )?(cae|mueve|tambalea|inclina) (?:la |el |una? )?" + _STRUCTURE,
        r"torre de (sonido|luces)", r"\btruss",
        r"valla (rota|caida|ha cedido|cedio|cede)", r"barrera (rota|caida|ha cedido|cedio|cede)", r"\bgrada",
        r"derrumb", r"collaps(ing|ed) (stage|tower|structure)", r"structure", r"barrier (broke|fail|gave)",
        r"scaffold", r"effondr", r"einsturz"], restrict=True, close=True),
    _t("power_outage", I, 6, {"tech": 1}, 20, "power", [
        r"apagon", r"sin luz", r"se ha ido la luz", r"se fue la luz", r"no hay luz", r"corte de luz",
        r"sin electricidad", r"a oscuras", r"power (outage|cut|is out|failure)", r"blackout",
        r"no power", r"panne de courant", r"stromausfall", r"sem luz"], notify=("production",)),
    _t("network_down", I, 4, {"tech": 1}, 30, "network", [
        r"sin cobertura", r"no hay red", r"wifi (?:no|sin|fall)", r"radio no funciona", r"walkies? (no|sin)",
        r"network (is )?down", r"no signal"], sitewide=True, notify=("all_leads",)),
    _t("sound_failure", I, 4, {"tech": 1}, 30, "sound", [
        r"sin sonido", r"no se oye", r"megafonia (no|fall)", r"no sound", r"sound (is )?down",
        r"sonido" + _GAP + r"(?:pet\w*|fall\w*|pitido)"], notify=("production",)),
    _t("toilets_failure", I, 3, {"tech": 1}, 60, "toilets", [
        r"(?:ban[oa]s?|aseos?|wc|inodoros?) (?:estan? )?(atascad|inundad|rot|cerrad|desbord)",
        r"toilets? (are |is )?(blocked|flooded|broken|overflow)"]),
    _t("payment_down", I, 3, {"tech": 1}, 60, "payment", [
        r"datafono", r"cashless", r"no (se puede|deja|podemos) pagar", r"\btpv\b", r"pulseras? no",
        r"payment", r"card reader", r"contactless"], sitewide=True, notify=("production",)),

    # ------------------------------------------------------------------ recursos propios
    _t("resource_down", R, 5, {}, 15, "resource", [
        r"no contesta", r"fuera de servicio", r"averiad", r"pinchazo", r"fin de turno", r"no podemos ir",
        r"no podemos llegar", r"ambulancia bloquead", r"out of service", r"broke down", r"can t get through"],
       notify=("coordinator",)),

    # ------------------------------------------------------------------ externos
    _t("suspicious_object", X, 9, {"security": 1}, 10, "threat", [
        _BAG + r"(?:\s+\w+){0,10}\s+" + _SUSPECT,
        r"(mochila|maleta|bolsa|paquete|bulto|objeto) (abandonad|sospechos|sol[oa]\b|sin duen)",
        r"unattended (bag|package|backpack)", r"suspicious", r"colis suspect", r"sac abandonne",
        r"verdachtig", r"sospechos"], threat=True, reserved=True, restrict=True, notify=("security_lead",),
       external="police", evacuate=True),
    _t("transport_cut", X, 6, {"security": 1}, 30, "transport", [
        r"metro (cortado|cerrado|averia|no funciona|suspendido)", r"lanzaderas? (no|sin|cortad|suspendid)",
        r"sin (buses|autobuses|trenes|metro|lanzaderas)", r"huelga", r"cercanias", r"no hay taxis",
        r"shuttles? (are |is )?(down|cancel|not)", r"no (trains|buses|shuttles)",
        r"transport (cut|strike|is down|suspend)"], sitewide=True, reroute=True, external="transport",
       broadcast="Hay un corte en el transporte de vuelta. No hay prisa por salir: os iremos informando."),
    _t("artist_delay", X, 5, {"security": 1}, 30, "artist", [
        r"artista", r"cabeza de cartel", r"se retrasa", r"retraso", r"cancela", r"no va a salir",
        r"headliner", r"\bdelay", r"cancel"], sitewide=True, notify=("production",),
       broadcast="El concierto empezará con retraso. Gracias por la paciencia: os iremos informando."),
    _t("drone", X, 5, {"security": 1}, 20, "drone", [r"\bdron\b", r"\bdrones?\b"], notify=("security_lead",),
       external="police"),
]

TYPES: dict[str, TypeSpec] = {s.type: s for s in SPECS}
TYPES["bottleneck"] = _t("bottleneck", C, 6, {"security": 1}, 20, "crowd", [], reroute=True,
                         broadcast="Esta zona está llena: usad los pasos alternativos.")
# Observación propia (no sale de ningún aviso): el depósito se va a acabar antes de lo que tarda en llegar la reposición.
TYPES["water_low"] = _t("water_low", S, 4, {"logistics": 1}, 30, "water", [])
TYPES["heat_cluster"] = _t("heat_cluster", S, 7, {}, 20, "pattern_heat", [], broadcast=WATER, notify=("medical_lead",))
TYPES["intox_cluster"] = _t("intox_cluster", M, 7, {}, 20, "pattern_intox", [], notify=("medical_lead", "security_lead"))
TYPES["aggression_cluster"] = _t("aggression_cluster", A, 6, {}, 20, "pattern_aggr", [], notify=("security_lead",))

# Lo no reconocido: una ficha genérica por familia. Sin recursos por defecto (los dice quien está en el sitio o los
# pone la señal de riesgo vital), sin megafonía, sin nada externo: solo a quién hay que avisar.
_LEAD = {M: ("medical_lead",), C: ("security_lead",), W: ("production",), A: ("security_lead",), S: ("coordinator",),
         I: ("production",), R: ("coordinator",), N: (), X: ("security_lead",)}
for _fam, _lead in _LEAD.items():
    TYPES[f"unknown_{_fam.value}"] = _t(f"unknown_{_fam.value}", _fam, 5 if _fam != N else 3, {}, 20,
                                        f"unknown_{_fam.value}", [], notify=_lead)
TYPES["unknown"] = TYPES["unknown_info"]


def spec_for(type_: str, family: Family | str | None = None) -> TypeSpec:
    """Ficha del tipo. Si el tipo no está en el léxico (lo propone un LLM, o lo nombra quien está en el sitio
    al contestar a una pregunta), la genérica de su familia: se actúa por familia, no se inventa protocolo."""
    s = TYPES.get(type_)
    if s:
        return s
    try:
        return TYPES[f"unknown_{Family(family).value}"]
    except ValueError:
        return TYPES["unknown_info"]


TYPE_RE = [(s, re.compile("|".join(f"(?:{p})" for p in s.patterns))) for s in SPECS]
WEAK_RE = [(s, re.compile("|".join(f"(?:{p})" for p in s.weak))) for s in SPECS if s.weak]

# ---------------------------------------------------------------------------- señales genéricas (lo no reconocido)

LIFE_RISK = re.compile(r"no respira|inconscient|no reacciona|no responde\b|sangra much|se muere|muriendo|atrapad|"
                       r"aplastad|se ahoga|convuls|muy grave|dolor en el pecho|dying|trapped|bleeding (a lot|heavily|badly)|"
                       r"unconscious|not breathing|chest pain")
THREAT = re.compile(r"\bbomba\b|explosiv|amenaza|atentado|sospechos|\barmas?\b|armad[oa]|pistola|disparo|\bbomb\b|"
                    r"threat|suspicious|gunshots?|shooting")
# Pistas de familia, de más a menos específica. Vocabulario general: no describe tipos, solo «de qué va».
FAMILY_CUES: list[tuple[Family, re.Pattern]] = [
    (R, re.compile(_SHORTAGE + _GAP + _STAFF_WORD + r"\b|"
                   r"no\s+" + _STAFF_WORD + r"\b|"
                   r"(?:cero|mas|more)\s+" + _STAFF_WORD + r"\b|"
                   r"ambulanc\w*" + _GAP + r"no puede pasar")),
    (S, re.compile(_SHORTAGE + _GAP + _STOCK + r"|sold out|"
                   r"(?:bidones?|barricas?|depositos?)" + _GAP + r"vaci[oa]s?")),
    (I, re.compile(r"tuberi|cables? pelad|(?:suelo|pavimento)" + _GAP + r"levantad")),
    (M, re.compile(r"medic|sanitari|enfermer|doctor|ambulanc|dolor|enferm[oa]|\bpecho\b|paramedic|first aid|\bsick\b|"
                   r"\bpain\b|medecin|\barzt\b|respira|en el suelo|on the ground|"
                   r"diabet|insulina|fiebre|fever|hinch(?:ad|ao)|torcid|tiemb|tembl|ojos en blanco|no puede andar")),
    (A, re.compile(r"agres|violen|insult|\bpega|golpea|attack|molest|siguiendo a (?:chicas?|mujeres?)")),
    (X, re.compile(r"policia|bomberos|trafico|carretera|autobus|\bbuses\b|\bmetro\b|\btren|taxi|parada\b|lanzadera")),
    (I, re.compile(r"\brot[oa]s?\b|averia|no funciona|estropead|\bfuga\b|\bcables?\b|broken|"
                   r"not working|kaputt|en panne")),
    (S, re.compile(r"no queda|se ha acabado|se acabo|\bfaltan?\b|agotad|run out|ran out")),
    (W, re.compile(r"lluv|viento|calor|tormenta|graniz|\bfrio\b|weather|\brain|\bwind|\bheat\b|too hot|mojadisim")),
    (R, re.compile(r"companer|\bunidad\b|vehiculo|walkie|\bturno\b")),
    (C, re.compile(r"\bgente\b|multitud|aglomeraci|\baforo\b|crowd|people|foule|menge|\bpetad[oa]s?\b")),
]


def generic_family(norm: str) -> tuple[Family, bool, bool]:
    """(familia, riesgo vital, amenaza) a partir de señales genéricas, para un aviso sin tipo reconocido."""
    life, threat = bool(LIFE_RISK.search(norm)), bool(THREAT.search(norm))
    if threat:
        return X, life, True
    if life:
        return M, True, False
    for family, rx in FAMILY_CUES:
        if rx.search(norm):
            return family, False, False
    return N, False, False


# ---------------------------------------------------------------------------- zonas

GATE = re.compile(r"\b(?:puerta|gate|acceso|entrada|entree|porte|tor|eingang|portao|porta|entrance|tornos?)s?\s+"
                  r"((?:a(?!\s+(?:la|el|los|las|un|una|mi|su|pie|lot|few|big)\b))|[bc])\b")
GATE_DIR = re.compile(r"\b(?:puerta|acceso|entrada|salida|gate|entrance|exit)\s+(norte|sur|principal|north|south|main)\b"
                      r"|\b(north|south|main)\s+(?:gate|entrance)\b")
# «detrás de los baños», «junto a la barra»: la zona es la del punto de referencia, con algo menos de confianza.
RELATIVE = re.compile(r"\b(detras de|delante de|junto a|al lado de|cerca de|enfrente de|frente a|a la altura de|pasad[oa]s?|"
                      r"antes de|entre|next to|near|behind|in front of|by the|beside|close to|pres de|a cote de|neben|"
                      r"hinter|perto de|ao lado de)\b")

ZONE_ALIASES: list[tuple[str, str]] = [
    ("backstage", r"backstage|camerinos?|detras del escenario|bambalinas|zona de artistas|behind the stage|"
                  r"derriere la scene|hinter der buhne|bastidores"),
    ("front_pit", r"\bfoso\b|primeras? (filas?|lineas?)|front ?pit|\bpit\b|(frente|delante) (de|del|al) escenario|"
                  r"pegad\w+ al escenario|(al )?pie del? escenario|vallad?[oa] (del|frente al) escenario|"
                  r"(in )?front of (the )?stage|front rows?|devant la scene|vor der buhne|frente ao palco|\bmosh|"
                  r"\bescenario\b|\bstage\b|\bscene\b|\bbuhne\b|\bpalco\b"),
    ("pmr", r"\bpmr\b|plataforma( (accesible|elevada|pmr|de sillas|para sillas)( de ruedas)?)?|movilidad reducida|"
            r"sillas? de ruedas|minusvalid|discapacitad|wheelchair|accessible platform|disabled (area|platform)|rollstuhl|"
            r"fauteuils? roulants?"),
    ("vip", r"(zona |area |sector )?\bvip\b|\bpalcos?\b"),
    ("medical_1", r"(puesto medico|puesto de socorro|enfermeria|botiquin|cruz roja|medical (post|tent|point))\s*(1|uno|sur|del sur|"
                  r"junto al? escenario)|south (?:med(?:ical)?|first aid)(?: (?:tent|post|point))?"),
    ("medical_2", r"(puesto medico|puesto de socorro|enfermeria|botiquin|cruz roja|medical (post|tent|point))\s*(2|dos|norte|"
                  r"del norte)|north (?:med(?:ical)?|first aid)(?: (?:tent|post|point))?"),
    ("water_n", r"(puntos?|fuentes?|grifos?) (de agua )?(del |de la zona )?norte|agua (del )?norte|north water|"
                r"water (point |station )?north|north refill|point d eau nord|wasserstelle nord|ponto de agua norte"),
    ("water_s", r"(puntos?|fuentes?|grifos?) (de agua )?(del |de la zona )?sur|agua (del )?sur|south water|"
                r"water (point |station )?south|south refill|point d eau sud|wasserstelle sud|ponto de agua sul"),
    ("corridor_n", r"(pasillo|corredor|paso) (del )?norte|north(ern)? (corridor|walkway|path)|couloir nord|nordgang"),
    ("corridor_s", r"(pasillo|corredor|paso) (del )?sur|south(ern)? (corridor|walkway|path)|ruta de (la )?ambulancias?|"
                   r"ambulance route|couloir sud|sudgang"),
    ("food", r"\bbarras?\b|\bbar(?:es)?\b|(zona|puestos?|area) de (comidas?|bebidas?)|restauracion|food ?trucks?|foodtrucks?|"
             r"food (court|area|zone|stands?|stalls?)|\bcantina\b|hamburgues|cervezas?|\bcopas\b|essensbereich|\bcomida\b"),
    ("toilets", r"\bban[oa]s?\b|\baseos?\b|\bwc\b|lavabos?|urinarios|\bservicios\b|\btoilets?\b|restrooms?|bathrooms?|"
                r"\bloos?\b|toilettes|toiletten|casas? de banho|banheiros?"),
    ("exit_transport", r"\bsalidas?\b|lanzaderas?|\bmetro\b|paradas?( de (bus|autobus|taxi)s?)?|autobuses|\bbuses\b|"
                       r"shuttles?|\bexit\b|bus stop|parking|aparcamiento|\bsortie\b|ausgang|\bsaida\b|navettes?"),
    ("general", r"\bpista\b|zona general|explanada|centro del recinto|en medio de(l publico| la gente)|main (area|field|crowd)|"
                r"\bcampa\b|\bcesped\b|(mesa|control|cabina) de sonido|\bfoh\b|general admission"),
    ("camping", r"camping|acampada"),
]
ZONE_RE = [(z, re.compile(p)) for z, p in ZONE_ALIASES]
