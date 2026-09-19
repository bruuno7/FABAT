"""Casos de demostración, escritos a mano. Vistosos, cortos y pensados para enseñarse en directo.

Los textos están escritos uno a uno; lo único que se deriva de la taxonomía son las expectativas
(`expected`), la prioridad y la dificultad, para que se puntúen igual que los generados. El caso d-09 es el
«nunca visto» (weather × aggression × external × supply); d-11 y d-12 son los de carga: seis frentes a la vez.
Horas y fases siguen el programa de `festival.json`. Por decisión del consejo (D4) aquí no hay violencia
sexual, amenaza de bomba, armas, menores en peligro ni atrapados: `validate.py` lo comprueba.
"""
from __future__ import annotations

from typing import Any

from .generator import FAMILY_ORDER, finish_case
from .taxonomy import (
    GLOBAL_MUST_NOT, INFO_QUALITY_TYPE, RESOURCE_STATE_TYPE, SHOW_PHASES, TAXONOMY, fill_rule, phase_at,
)


def _rep(channel: str, source: str, text: str, lang: str = "es", zone_hint: str | None = None,
         truth: str | None = None) -> dict[str, Any]:
    r: dict[str, Any] = {"channel": channel, "source": source, "lang": lang, "text": text}
    if zone_hint:
        r["zone_hint"] = zone_hint
    if truth:
        r["truth_incident"] = truth
    return r


def _inc(t: int, iid: str, type_id: str, zone: str, severity: int, deadline: int, reports: list[dict[str, Any]],
         unless: str | None = None) -> dict[str, Any]:
    ty = TAXONOMY[type_id]
    ev = {"t": t, "kind": "incident",
          "incident": {"id": iid, "family": ty.family.value, "type": type_id, "zone": zone, "severity": severity,
                       "deadline": deadline, "needs": dict(ty.needs)},
          "reports": reports}
    if unless:
        ev["cond"] = {"unless_resolved": unless}
    return ev


def _only(t: int, tag: str, ref: str, *reports: dict[str, Any]) -> dict[str, Any]:
    return {"t": t, "kind": "report_only", "tag": tag, "ref": ref, "reports": list(reports)}


def _world(t: int, unless: str | None = None, **effect: Any) -> dict[str, Any]:
    ev = {"t": t, "kind": "world", "effect": effect}
    if unless:
        ev["cond"] = {"unless_resolved": unless}
    return ev


def _case(n: int, title: str, story: str, *, day: int, hhmm: str, duration: int, phase: str, weather: str,
          weather_now: dict[str, Any], events: list[dict[str, Any]], info: list[str], resource_state: str,
          perts: list[str], chain: list[tuple[str, str]] = (), occupancy: dict[str, int] | None = None,
          offline: list[str] = (), shift_ends: dict[str, int] | None = None, state_resource: str = "",
          false_alarms: list[str] = (), never_seen: bool = False, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    events = sorted(events, key=lambda e: e["t"])
    incidents = [(e["incident"], "cond" in e) for e in events if e["kind"] == "incident"]
    primary = max((i for i, c in incidents if not c), key=lambda i: i["severity"])
    must: list[str] = []
    must_not: list[str] = list(GLOBAL_MUST_NOT)
    for inc, cond in incidents:
        ty = TAXONOMY[inc["type"]]
        skip_ask = "ambiguous" in info and inc is primary
        t_open = next(e["t"] for e in events if e.get("incident") is inc)
        show_on = phase_at(day, hhmm, t_open) in SHOW_PHASES  # fuera de concierto no hay nada que parar
        must += [fill_rule(r, i=inc["id"], z=inc["zone"]) + (" if spawned" if cond else "") for r in ty.must
                 if show_on or not r.startswith("stop_show")]
        must_not += [fill_rule(r, i=inc["id"], z=inc["zone"]) for r in ty.must_not if not (skip_ask and r.startswith("ask before"))]
    types = [i["type"] for i, _ in incidents]
    for q in info:
        if q in INFO_QUALITY_TYPE and q != "false_alarms":
            ty = TAXONOMY[INFO_QUALITY_TYPE[q]]
            types.append(ty.id)
            must += [fill_rule(r, i=primary["id"], z=primary["zone"]) for r in ty.must]
            must_not += [fill_rule(r, i=primary["id"], z=primary["zone"]) for r in ty.must_not]
    for fa in false_alarms:
        ty = TAXONOMY["false_alarm_prank"]
        types.append(ty.id)
        must += [fill_rule(r, i=fa) for r in ty.must]
        must_not += [fill_rule(r, i=fa) for r in ty.must_not]
    if resource_state != "full":
        ty = TAXONOMY[RESOURCE_STATE_TYPE[resource_state]]
        types.append(ty.id)
        must += [fill_rule(r, i=primary["id"], z=primary["zone"], r=state_resource) for r in ty.must]
        must_not += [fill_rule(r, i=primary["id"], z=primary["zone"], r=state_resource) for r in ty.must_not]
    types = list(dict.fromkeys(types))
    families = {TAXONOMY[t].family.value for t in types}
    initial: dict[str, Any] = {"occupancy": dict(occupancy or {}), "weather": weather_now,
                               "resources_offline": list(offline)}
    if shift_ends:
        initial["shift_ends"] = shift_ends
    quality = next((q for q in ("contradictory", "ambiguous", "false_alarms", "buried", "duplicated") if q in info), "clean")
    case = {
        "id": f"c-d{n:06d}", "seed": n, "split": "demo", "day": day, "start_hhmm": hhmm, "duration_min": duration,
        "families": [f for f in FAMILY_ORDER if f in families], "difficulty": 0,
        "initial": initial, "events": events,
        "expected": {"must": list(dict.fromkeys(must)), "must_not": list(dict.fromkeys(must_not))},
        "meta": {"title": title, "story": story, "phase": phase, "weather": weather, "info_quality": quality,
                 "resource_state": resource_state, "perturbations": perts, "chain": [list(c) for c in chain],
                 "primary": primary["id"], "primary_type": primary["type"], "types": types,
                 "combos": [[TAXONOMY[i["type"]].family.value, i["type"], p] for i, _ in incidents for p in perts],
                 "never_seen": never_seen, **(meta or {})},
    }
    case = finish_case(case)
    if case["meta"].get("load"):  # más frentes que equipos: se le quita el equipo a lo menor, lo grave no hace cola
        ty = TAXONOMY["all_busy_higher_priority"]
        top = case["expected"]["priority"][0]
        case["expected"]["must"] += [fill_rule(r, i=top) for r in ty.must]
        case["expected"]["must_not"] += [fill_rule(r, i=top) for r in ty.must_not]
        case["meta"]["types"].append(ty.id)
        case["families"] = [f for f in FAMILY_ORDER if f in set(case["families"]) | {"resource"}]
    return case


def demo_cases() -> list[dict[str, Any]]:
    normal = {"temp_c": 27, "wind_kmh": 12, "rain": False, "alert": None}
    cases = []

    cases.append(_case(
        1, "Parada cardiaca con la ambulancia atrapada",
        "Un embudo en el pasillo sur parece menor hasta que entra una parada y la ambulancia se queda bloqueada en ese mismo pasillo. "
        "Tres personas cuentan la parada con edades y sitios distintos y una cuarta dice que ya está resuelto.",
        day=2, hhmm="22:40", duration=60, phase="headliner", weather="normal", weather_now=normal,
        occupancy={"corridor_s": 5900},
        info=["duplicated", "contradictory"], resource_state="full", perts=["resource_offline"],
        chain=[("corridor_bottleneck", "ambulance_blocked_by_crowd")],
        events=[
            _inc(2, "i1", "corridor_bottleneck", "corridor_s", 6, 22, [
                _rep("sensor", "sensor corridor_s", "SENSOR contador corridor_s: densidad 3,9 p/m², velocidad media de paso 0,2 m/s", zone_hint="corridor_s"),
                _rep("radio", "voluntarios 2", "Control de Voluntarios 2. El pasillo sur está taponado, se cruzan los que van a los baños con los que vuelven. No pasa nadie. Cambio.")]),
            _inc(5, "i2", "cardiac_arrest", "general", 10, 10, [
                _rep("whatsapp", "asistente", "AYUDA un señor se a caido redondo y no respira!!! una chica le esta haciendo el masaje, estamos x la torre de sonido 🆘🆘")]),
            _only(6, "duplicate", "i2",
                  _rep("whatsapp", "asistente (en)", "older man collapsed near the sound tower, maybe 60?? a nurse is doing cpr, send someone NOW", lang="en", truth="i2"),
                  _rep("radio", "sierra 3", "Control de Sierra 3, prioridad. Varón de unos cuarenta y cinco años en parada, pista general cuadrante derecho, hay RCP por testigos. Necesito DESA y médico ya. Cambio.", truth="i2")),
            _world(8, kind="resource_offline", resource="amb_1", reason="bloqueada por la multitud"),
            _inc(8, "i3", "ambulance_blocked_by_crowd", "corridor_s", 9, 16, [
                _rep("radio", "alfa 1", "Alfa 1 para Control. Estamos parados en el pasillo sur, la gente no abre paso ni con las luces, no podemos ni dar marcha atrás. Necesito seguridad para abrir pasillo. Cambio.")]),
            _only(9, "contradictory", "i2",
                  _rep("whatsapp", "asistente", "lo del señor de la torre de sonido ya esta, se a levantado y se a ido andando, no hace falta q vengais", truth="i2")),
        ]))

    cases.append(_case(
        2, "Densidad crítica en el foso y una valla que cede",
        "El contador del foso pasa de 5 p/m² justo cuando empieza el tema más conocido. Parar el concierto lo aprueba una persona; "
        "todo lo demás sale solo. A los seis minutos entra más gente todavía y cede un tramo de valla.",
        day=2, hhmm="23:10", duration=60, phase="headliner", weather="normal", weather_now=normal,
        occupancy={"front_pit": 13500},
        info=["duplicated", "false_alarms"], false_alarms=["fa1"], resource_state="full", perts=["zone_inflow"],
        events=[
            _inc(1, "i1", "front_pit_critical_density", "front_pit", 9, 12, [
                _rep("sensor", "sensor front_pit", "SENSOR contador front_pit: densidad 5,4 p/m² (umbral 5,0; riesgo 6,5), 13500 personas, +60/min", zone_hint="front_pit"),
                _rep("radio", "jefe de seguridad de sector foso", "Control de jefe de sector foso. Primera línea muy comprimida, hay oleadas laterales y ya hemos sacado a cuatro mareados por encima de la valla. Pido refuerzo y sanitarios. Cambio.")]),
            _only(3, "duplicate", "i1",
                  _rep("whatsapp", "asistente", "delante del todo no se puede respirar nos movemos en ola y no controlo los pies SACADNOS 😭😭", truth="i1"),
                  _rep("whatsapp", "asistente (de)", "vor der Bühne ist es viel zu eng, man bekommt keine Luft!!", lang="de", truth="i1")),
            _only(4, "false_alarm", "fa1",
                  _rep("whatsapp", "asistente", "SOCORRO mi amigo Dani se ha quedado sin cerveza, es una emergencia nacional 🍺😂")),
            _world(6, kind="zone_inflow", zone="front_pit", per_min=120, n=10),
            _inc(7, "i2", "barrier_failure", "front_pit", 9, 16, [
                _rep("radio", "sierra 2", "Sierra 2 para Control, prioridad. Ha cedido un tramo de valla antiavalancha en el lado izquierdo del foso, la aguantamos a mano entre cuatro. Solicito técnico y otra pareja. Cambio.")]),
        ]))

    cases.append(_case(
        3, "Calor: agua agotada, golpes de calor, puesto saturado",
        "El encadenamiento de manual. La cisterna de reposición rechaza el encargo y la temperatura sube a mitad de caso: "
        "el plan «reponer agua en 10 min» deja de ser cierto y hay que tirarlo.",
        day=1, hhmm="17:30", duration=75, phase="concerts", weather="heat",
        weather_now={"temp_c": 40, "wind_kmh": 8, "rain": False, "alert": "naranja"},
        info=["clean"], resource_state="rejects", state_resource="log_1", perts=["weather_shift"],
        chain=[("water_out", "multiple_heat_strokes"), ("multiple_heat_strokes", "medical_post_saturated")],
        events=[
            _inc(1, "i1", "extreme_heat_alert", "general", 6, 31, [
                _rep("sensor", "estación meteo", "SENSOR estación meteo: temperatura 40 °C, índice de calor 44 °C, alerta naranja", zone_hint="general")]),
            _inc(4, "i2", "water_out", "water_n", 7, 22, [
                _rep("radio", "logística", "Logística para Control. Punto de agua norte seco, depósito a cero, tengo una cola de cincuenta personas al sol. La cisterna de reposición no ha llegado. Cambio."),
                _rep("whatsapp", "asistente", "no sale agua de las fuentes de arriba y hay una cola enorme, la gente se esta enfadando")]),
            _world(4, kind="zone_flag", zone="water_n", flag="water_l", value=0),
            _world(6, kind="resource_rejects", resource="log_1", reason="la cisterna está retenida en el acceso rodado"),
            _world(10, kind="weather", temp_c=42, alert="roja"),
            _inc(24, "i3", "multiple_heat_strokes", "water_n", 9, 37, [
                _rep("radio", "médico 2", "Control de Médico 2. Llevo cinco desmayos por calor en diez minutos en la cola del agua norte, dos no responden bien. No doy abasto. Cambio."),
                _rep("whatsapp", "asistente (en)", "several people have fainted in the water queue, at least 5, nobody has water", lang="en")], unless="i2"),
            _inc(40, "i4", "medical_post_saturated", "medical_1", 8, 58, [
                _rep("voice", "coordinadora médica", "Hola, soy la coordinadora médica, estoy en el puesto 1. Tengo las seis camillas ocupadas y gente esperando fuera al sol. Necesito derivar al puesto 2 y una evacuación a hospital.")], unless="i3"),
        ]))

    cases.append(_case(
        4, "Aviso en inglés sin ubicación y un equipo que dice que no",
        "El aviso llega en inglés y sin sitio claro; el equipo médico más cercano rechaza la orden porque está con otro paciente. "
        "Un camarero cuenta lo mismo por teléfono con otros detalles y WhatsApp se cae ocho minutos.",
        day=2, hhmm="21:15", duration=60, phase="concerts", weather="normal", weather_now=normal,
        info=["duplicated"], resource_state="rejects", state_resource="med_2", perts=["comms_down"],
        events=[
            _world(2, kind="resource_rejects", resource="med_2", reason="estamos con otro paciente en el puesto norte"),
            _inc(3, "i1", "intoxication_overdose", "toilets", 8, 14, [
                _rep("whatsapp", "asistente (en)", "pls help my mate took something and wont wake up, hes throwing up and really pale. we r in some toilet queue, dont know which one", lang="en")]),
            _inc(5, "i2", "fight", "food", 6, 15, [
                _rep("radio", "sierra 4", "Control de Sierra 4. Pelea entre dos grupos en restauración, unas seis personas, uno sangra por la ceja. Necesito otra pareja. Cambio.")]),
            _only(6, "duplicate", "i1",
                  _rep("voice", "personal de barra", "Hola, llamo de la barra que está pegada a los baños. Hay un chico de unos veinte años tirado en la cola, vomitando, los amigos dicen que ha mezclado cosas. Responde solo si le pellizcas.", truth="i1")),
            _world(9, kind="comms_down", channel="whatsapp", n=8),
        ]))

    cases.append(_case(
        5, "Objeto sin dueño en la puerta: Mando no decide, escala",
        "Una mochila sin dueño en la puerta con más cola, a los veinte minutos de abrir. El agente acordona, pide policía con "
        "aprobación y calla por megafonía; evacuar no es suyo. Entre medias llega una broma y un metro que descarga 900 personas.",
        day=3, hhmm="15:20", duration=60, phase="doors", weather="normal", weather_now=normal,
        occupancy={"gate_b": 2100},
        info=["false_alarms"], false_alarms=["fa1"], resource_state="full", perts=["zone_inflow"],
        chain=[("suspicious_object", "rumor_panic")],
        events=[
            _inc(2, "i1", "gate_saturation", "gate_b", 6, 27, [
                _rep("sensor", "sensor gate_b", "SENSOR aforo gate_b: 2100 personas (88 % de capacidad), densidad 3,5 p/m², entrada neta +40/min", zone_hint="gate_b")]),
            _inc(5, "i2", "suspicious_object", "gate_b", 9, 14, [
                _rep("radio", "jefe de seguridad de accesos", "Control de jefe de accesos. Mochila negra abandonada junto al torno tres de puerta B, nadie la reclama desde hace diez minutos. No la tocamos. Hemos apartado a la gente unos metros. Cambio.")]),
            _only(6, "false_alarm", "fa1",
                  _rep("whatsapp", "asistente", "se ha desmayado mi dignidad en la cola de la puerta B jaja 😂")),
            _only(7, "duplicate", "i2",
                  _rep("whatsapp", "asistente", "an dejado una mochila sola en la entrada B y la gente se esta poniendo nerviosa, alguien la mira??", truth="i2")),
            _world(9, kind="zone_inflow", zone="gate_b", per_min=90, n=12),
            _inc(16, "i3", "rumor_panic", "general", 7, 27, [
                _rep("radio", "sierra 5", "Sierra 5 para Control. Corre el bulo de que están desalojando por lo de la puerta B, tengo gente corriendo hacia el fondo de la pista y llorando. Aquí no hay nada. Cambio.")], unless="i2"),
        ]))

    cases.append(_case(
        6, "Apagón en restauración, cae el cashless y se calienta la cola",
        "El generador avisa con tiempo; si no se repone, se va la luz, caen los datáfonos y la cola acaba a golpes. "
        "El técnico más cercano no contesta durante ocho minutos.",
        day=1, hhmm="20:45", duration=70, phase="concerts", weather="normal", weather_now=normal,
        occupancy={"food": 4300},
        info=["clean"], resource_state="no_answer", state_resource="tech_1", perts=["zone_flag"],
        chain=[("generator_fuel_low", "power_outage_food"), ("power_outage_food", "cashless_down"), ("cashless_down", "fight")],
        events=[
            _inc(2, "i1", "generator_fuel_low", "food", 6, 14, [
                _rep("sensor", "sensor food", "SENSOR generador food: combustible 6 %, autonomía estimada 12 min", zone_hint="food"),
                _rep("radio", "tango 2", "Control de Tango 2. El generador de restauración está en reserva y el camión de gasoil no aparece. Si cae, se va la luz de toda la zona. Cambio.")]),
            _world(3, kind="resource_no_answer", resource="tech_1", n=8),
            _inc(15, "i2", "power_outage_food", "food", 7, 32, [
                _rep("whatsapp", "asistente", "se a ido la luz en toda la zona de comida no se ve nada y hay muchisima gente"),
                _rep("sensor", "sensor food", "SENSOR cuadro eléctrico food: sin tensión en las 3 fases", zone_hint="food")], unless="i1"),
            _world(15, unless="i1", kind="zone_flag", zone="food", flag="power", value=False),
            _inc(17, "i3", "cashless_down", "food", 6, 40, [
                _rep("radio", "coordinador de barras", "Control de Barras. Ha caído el cashless, ningún puesto puede cobrar ni agua. Las colas se están calentando. Cambio.")], unless="i1"),
            _inc(30, "i4", "fight", "food", 7, 41, [
                _rep("whatsapp", "asistente (en)", "theres a fight at the food trucks, like 5 guys, people are angry because nothing works", lang="en")], unless="i3"),
        ]))

    cases.append(_case(
        7, "Salida del día 3: metro cortado, un mayor desorientado y fin de turno",
        "Todo a la vez en la explanada de salida, un cuarto de hora después del último bis. La hija escribe en portugués. A una "
        "pareja de seguridad se le acaba el turno sin relevo a los seis minutos y el alumbrado del pasillo sur se va.",
        day=3, hhmm="23:00", duration=70, phase="egress", weather="normal", weather_now={"temp_c": 22, "wind_kmh": 10, "rain": False, "alert": None},
        occupancy={"exit_transport": 5200},
        info=["clean"], resource_state="shift_end", state_resource="sec_3", shift_ends={"sec_3": 6}, perts=["zone_inflow"],
        chain=[("transport_cut_exit", "counterflow_exit")],
        events=[
            _inc(2, "i1", "transport_cut_exit", "exit_transport", 8, 24, [
                _rep("voice", "enlace de transporte", "Hola, soy el enlace con Metro. Nos confirman la línea cortada hasta nuevo aviso. Las lanzaderas no dan para todos y la explanada se está llenando.")]),
            _world(2, kind="transport_cut", mode="metro", n=45),
            _inc(4, "i2", "lost_vulnerable_adult", "corridor_s", 7, 28, [
                _rep("whatsapp", "asistente (pt)", "o meu pai tem Alzheimer e afastou-se de nós no corredor para a saída dos autocarros, tem 78 anos, camisa amarela, por favor ajudem-me 😭", lang="pt")]),
            _world(6, kind="resource_offline", resource="sec_3", reason="fin de turno sin relevo"),
            _inc(9, "i3", "lighting_failure", "corridor_s", 6, 24, [
                _rep("radio", "voluntarios 1", "Control de Voluntarios 1. Se ha ido todo el alumbrado del pasillo sur, la gente camina a oscuras con el móvil y ya ha habido un tropiezo. Cambio.")]),
            _world(12, kind="zone_inflow", zone="exit_transport", per_min=150, n=15),
            _inc(26, "i4", "counterflow_exit", "gate_c", 8, 40, [
                _rep("whatsapp", "asistente", "en la salida la gente se da la vuelta xq no hay metro y nos chocamos con los q vienen, no cabe nadie")], unless="i1"),
        ]))

    cases.append(_case(
        8, "Tormenta con estructuras: parar es decisión humana",
        "Viento que pasa a tormenta en seis minutos. Mando despeja y manda técnicos solo; parar el concierto y evacuar el foso "
        "los propone con su porqué y espera el sí.",
        day=2, hhmm="22:20", duration=60, phase="headliner", weather="wind",
        weather_now={"temp_c": 24, "wind_kmh": 58, "rain": False, "alert": "amarilla"},
        info=["clean"], resource_state="one_offline", state_resource="tech_2", offline=["tech_2"],
        perts=["weather_shift", "zone_flag"], chain=[("strong_wind_gusts", "storm_structures")],
        events=[
            _inc(1, "i1", "strong_wind_gusts", "front_pit", 7, 16, [
                _rep("sensor", "estación meteo", "SENSOR estación meteo: racha 62 km/h (umbral de estructuras 60 km/h), media 10 min 44 km/h", zone_hint="front_pit"),
                _rep("radio", "técnico 1", "Control de Técnico 1. Las lonas del techo del escenario están flameando y una torre de luces se mueve. Cambio.")]),
            _world(6, kind="weather", wind_kmh=84, rain=True, alert="roja"),
            _inc(7, "i2", "storm_structures", "front_pit", 10, 17, [
                _rep("radio", "producción", "Producción para Control, prioridad. Tormenta encima, rachas de ochenta y cuatro, el techo trabaja muy por encima del límite. Pedimos parar y despejar debajo. Cambio."),
                _rep("whatsapp", "asistente", "las pantallas gigantes se mueven muchisimo y la gente sigue debajo, sacadnos de aqui")]),
            _inc(8, "i3", "lightning_nearby", "general", 8, 20, [
                _rep("sensor", "estación meteo", "SENSOR detector de rayos: descarga a 6 km, 31 descargas en 10 min, alerta roja", zone_hint="general")]),
            _inc(10, "i4", "heavy_rain_flooding", "corridor_s", 6, 35, [
                _rep("radio", "alfa 1", "Alfa 1 para Control. El pasillo sur tiene un palmo de agua y cables por el suelo, la ruta de ambulancia está comprometida. Cambio.")]),
            _world(12, kind="zone_flag", zone="vip", flag="structure_ok", value=False),
        ]))

    cases.append(_case(
        9, "NUNCA VISTO: tormenta a la salida, agresión a un auxiliar y metro cortado",
        "Junta familias que en train jamás coinciden (weather × aggression × external × supply). El concierto ya ha acabado: no hay "
        "nada que parar, hay que sacar a 40.000 personas bajo rayos con el metro cortado. Un auxiliar agredido en la cola de "
        "lanzaderas llega contado en inglés dentro de un mensaje largo; un equipo no contesta y la radio cae ocho minutos.",
        day=3, hhmm="22:50", duration=70, phase="egress", weather="storm",
        weather_now={"temp_c": 21, "wind_kmh": 52, "rain": True, "alert": "naranja"},
        occupancy={"exit_transport": 4100},
        info=["buried"], resource_state="no_answer", state_resource="sec_1", perts=["comms_down", "transport_cut"],
        chain=[("transport_cut_exit", "counterflow_exit")], never_seen=True,
        events=[
            _inc(1, "i1", "lightning_nearby", "general", 8, 15, [
                _rep("sensor", "estación meteo", "SENSOR detector de rayos: descarga a 8 km, 22 descargas en 10 min, alerta naranja", zone_hint="general")]),
            _world(2, kind="resource_no_answer", resource="sec_1", n=10),
            _inc(3, "i2", "transport_cut_exit", "exit_transport", 8, 23, [
                _rep("voice", "enlace de transporte", "Soy el enlace con Metro. Línea cortada por la tormenta, sin previsión. Las lanzaderas tampoco salen con esta lluvia.")]),
            _world(3, kind="transport_cut", mode="metro", n=50),
            _inc(6, "i3", "staff_assaulted", "exit_transport", 7, 16, [
                _rep("whatsapp", "asistente (en)", "Hi, sorry, not sure this is the right number. We came from Dublin for the weekend and it's been great, really. We're in the shuttle queue and it's chaos with the metro closed, and a man just punched one of your stewards in the face because she wouldn't let him skip the line, she's on the ground with her nose bleeding and he's still here shouting at the others. Also is there anywhere dry to wait? Thanks", lang="en")]),
            _inc(9, "i4", "medical_supplies_low", "medical_1", 6, 32, [
                _rep("radio", "médico 3", "Control de Médico 3. Nos quedan dos mantas térmicas y la gente llega empapada y tiritando. Necesito reposición urgente en el puesto 1. Cambio.")]),
            _world(11, kind="comms_down", channel="radio", n=8),
            _inc(27, "i5", "counterflow_exit", "corridor_s", 8, 41, [
                _rep("whatsapp", "asistente (fr)", "à la sortie les gens font demi-tour parce qu'il n'y a pas de métro, on se rentre dedans, ça pousse fort", lang="fr")], unless="i2"),
        ]))

    cases.append(_case(
        10, "El jurado es el público",
        "Pensado para la sala: cada juez manda un WhatsApp desde su asiento contando lo mismo a su manera (cuatro idiomas, "
        "edades que no coinciden, una broma y un «ya está bien»). El equipo médico que recibe la llamada puede decir que no.",
        day=2, hhmm="21:40", duration=45, phase="concerts", weather="normal", weather_now=normal,
        info=["duplicated", "contradictory", "false_alarms"], false_alarms=["fa1"],
        resource_state="rejects", state_resource="med_2", perts=["resource_rejects"],
        events=[
            _inc(2, "i1", "anaphylaxis", "food", 9, 9, [
                _rep("whatsapp", "asistente", "AYUDA mi hermana es alergica a los frutos secos se le esta inchando la cara y no respira bien!!! 🆘")]),
            _only(3, "duplicate", "i1",
                  _rep("whatsapp", "asistente (en)", "a girl at the food trucks is having an allergic reaction, her lips are huge, she's maybe 16", lang="en", truth="i1"),
                  _rep("whatsapp", "asistente (fr)", "vers les food trucks une femme d'une trentaine d'années s'étouffe, son visage gonfle, vite", lang="fr", truth="i1")),
            _only(4, "false_alarm", "fa1",
                  _rep("whatsapp", "asistente", "emergencia: mi novia quiere irse antes del cabeza de cartel 😂")),
            _world(4, kind="resource_rejects", resource="med_2", reason="estamos con otro paciente, no podemos movernos"),
            _only(5, "contradictory", "i1",
                  _rep("whatsapp", "asistente", "falsa alarma lo de la chica de los food trucks, ya esta bien", truth="i1"),
                  _rep("whatsapp", "asistente (de)", "bei den Foodtrucks, sie atmet immer schlechter, bitte schnell!!", lang="de", truth="i1")),
            _inc(6, "i2", "minor_injury", "general", 2, 40, [
                _rep("whatsapp", "asistente", "me e cortado un poco con un vaso roto, no es grave pero sangra")]),
        ]))
    cases.append(_case(
        11, "Seis frentes a la vez",
        "En diez minutos se abren seis frentes de seis familias y no hay técnicos para todos (uno está de baja). Mando tiene que "
        "ordenar: le quita el técnico a los baños, deja en espera lo que puede esperar y no pone a nadie entre la persona "
        "que no responde y su equipo médico. El viento sube por escalones: 42, luego 52 km/h.",
        day=2, hhmm="20:40", duration=60, phase="concerts", weather="wind",
        weather_now={"temp_c": 25, "wind_kmh": 42, "rain": False, "alert": "amarilla"},
        occupancy={"gate_b": 2000},
        info=["clean"], resource_state="one_offline", state_resource="tech_2", offline=["tech_2"], perts=["weather_shift"],
        meta={"load": 6, "window": [1, 11], "surprise_t": None, "surprise_kind": None,
              "demand": {"tech": 2, "security": 4, "volunteer": 2, "logistics": 1, "medical": 2, "ambulance": 1},
              "supply": {"tech": 1, "security": 5, "volunteer": 3, "logistics": 1, "medical": 3, "ambulance": 1},
              "scarce_kinds": ["tech"], "distinct_families": 6},
        events=[
            _inc(1, "i1", "toilets_blocked", "toilets", 3, 45, [
                _rep("radio", "mantenimiento", "Control de Mantenimiento. Un módulo entero de baños fuera de uso por atasco, hay que cerrar el bloque. No corre prisa. Cambio.")]),
            _inc(3, "i2", "gate_saturation", "gate_b", 6, 28, [
                _rep("sensor", "sensor gate_b", "SENSOR aforo gate_b: 2000 personas (83 % de capacidad), densidad 3,3 p/m², entrada neta +50/min", zone_hint="gate_b"),
                _rep("radio", "jefe de seguridad de accesos", "Control de jefe de accesos. Puerta B con un torno menos y sigue llegando gente del metro. La cola ya se sale del vallado. Cambio.")]),
            _inc(5, "i3", "water_out", "water_s", 7, 25, [
                _rep("radio", "logística", "Logística para Control. Punto de agua sur seco, depósito a cero y cola de cuarenta personas. Cambio.")]),
            _world(5, kind="zone_flag", zone="water_s", flag="water_l", value=0),
            _inc(7, "i4", "staff_assaulted", "food", 7, 18, [
                _rep("radio", "sierra 4", "Control de Sierra 4. Le han tirado un vaso a una camarera en restauración, tiene un corte en la ceja y el tipo sigue aquí muy alterado. Necesito otra pareja y un sanitario. Cambio.")]),
            _world(9, kind="weather", wind_kmh=52, alert="naranja"),
            _inc(9, "i5", "strong_wind_gusts", "front_pit", 8, 22, [
                _rep("sensor", "estación meteo", "SENSOR estación meteo: racha 52 km/h (escalones 40/50/60), media 10 min 41 km/h", zone_hint="front_pit"),
                _rep("radio", "producción", "Producción para Control. Las lonas del techo flamean y una torre de luces se mueve. Necesito un técnico arriba ya. Cambio.")]),
            _inc(11, "i6", "cardiac_arrest", "front_pit", 10, 16, [
                _rep("radio", "jefe de seguridad de sector foso", "Control de jefe de sector foso, prioridad. Persona que no responde en el foso, lado derecho, la hemos sacado por encima de la valla. No respira bien. Necesito equipo médico y DESA ya. Cambio."),
                _rep("whatsapp", "asistente", "delante a la derecha an sacado a un chico q no se mueve, esta en el suelo detras de la valla 🆘")]),
        ]))

    cases.append(_case(
        12, "Seis frentes y el imprevisto del jurado",
        "Seis frentes abiertos en diez minutos con siete parejas de seguridad pedidas y cinco en el recinto. El séptimo frente "
        "NO está en el caso: lo inyecta una persona de la sala desde el móvil cuando quiera (menú en `meta.surprise_menu`, "
        "en el formato de `WorldAPI.inject`). Se ve en pantalla a quién deja Mando esperando y por qué.",
        day=3, hhmm="21:05", duration=60, phase="headliner", weather="normal", weather_now=normal,
        occupancy={"corridor_s": 6300},
        info=["clean"], resource_state="full", perts=["none"],
        meta={"load": 6, "window": [1, 10], "surprise_t": None, "surprise_kind": "injected_by_person",
              "demand": {"security": 7, "volunteer": 2, "medical": 1}, "supply": {"security": 5, "volunteer": 3, "medical": 3},
              "scarce_kinds": ["security"], "distinct_families": 5,
              "surprise_menu": [
                  {"label": "Persona que no responde en el foso",
                   "effect": {"kind": "incident",
                              "incident": {"id": "j1", "family": "medical", "type": "cardiac_arrest", "zone": "front_pit",
                                           "severity": 10, "deadline": 6, "needs": {"medical": 1, "ambulance": 1}},
                              "reports": [{"channel": "whatsapp", "source": "jurado", "lang": "es",
                                           "text": "hay una persona en el suelo delante del escenario que no responde"}]}},
                  {"label": "La ambulancia interna se queda bloqueada", "effect": {"kind": "resource_offline", "resource": "amb_1", "reason": "bloqueada por la multitud", "n": 15}},
                  {"label": "Se cierra el pasillo sur (ruta sanitaria)", "effect": {"kind": "zone_state", "zone": "corridor_s", "state": "closed", "reason": "vallado caído"}},
                  {"label": "Metro cortado", "effect": {"kind": "transport_cut", "mode": "metro", "n": 30}},
                  {"label": "Cae la radio ocho minutos", "effect": {"kind": "comms_down", "channel": "radio", "n": 8}},
              ]},
        events=[
            _inc(1, "i1", "theft_gang", "general", 4, 36, [
                _rep("radio", "sierra 4", "Control de Sierra 4. Nos llegan tres denuncias de móviles robados en la misma zona de pista en media hora, parece un grupo organizado. Sin prisa. Cambio.")]),
            _inc(3, "i2", "corridor_bottleneck", "corridor_s", 6, 25, [
                _rep("sensor", "sensor corridor_s", "SENSOR contador corridor_s: densidad 3,5 p/m², velocidad media de paso 0,2 m/s", zone_hint="corridor_s")]),
            _inc(5, "i3", "lost_vulnerable_adult", "general", 6, 30, [
                _rep("whatsapp", "asistente", "mi padre tiene alzheimer y se a ido de nuestro lado, lleva camisa verde, estabamos x la torre de sonido")]),
            _inc(6, "i4", "artist_delay_cancel", "front_pit", 6, 22, [
                _rep("voice", "regidor de escenario", "Soy el regidor. El artista no sale, management confirma al menos veinte minutos de retraso. El público ya silba y empiezan a volar vasos.")]),
            _inc(8, "i5", "fight", "food", 7, 19, [
                _rep("radio", "sierra 2", "Control de Sierra 2. Pelea entre dos grupos en restauración, unas seis personas, botellas por medio. Necesito otra pareja. Cambio.")]),
            _inc(10, "i6", "intoxication_overdose", "toilets", 8, 22, [
                _rep("whatsapp", "asistente (en)", "my mate took something and won't wake up, he's throwing up and really pale, we're by the toilets", lang="en")]),
        ]))
    return cases
