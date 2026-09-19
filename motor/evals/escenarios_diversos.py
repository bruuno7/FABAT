"""Banco de escenarios diversos para el eval del equipo. Simulación; cada cifra lleva su N.

Mezcla avisos de calma a caos, recintos distintos (mismo motor) y casos heldout regenerables.
"""
from __future__ import annotations

from typing import Any, Iterator

REQUIRED_TAGS = frozenset({
    "leve", "muchos", "contradictorio", "rumor", "sin_zona", "parada_ambulancia",
    "tormenta", "incendio_food", "agresion", "menor", "apagon", "puerta",
    "agua", "rechazo", "silencio", "segundo_grave", "golpe_jurado",
    "deporte", "feria", "edificio",
})


def _e(eid: str, titulo: str, *, familia: str, tipo: str, zona: str | None, texto: str,
       tags: tuple[str, ...], recinto: str = "festival", vital: bool = False,
       prio_min: float = 0, prio_max: float = 10, recursos_kind: tuple[str, ...] = (),
       grave: bool = False, avisar: tuple[str, ...] = (), **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": eid, "titulo": titulo, "familia": familia, "tipo": tipo, "zona": zona,
        "texto": texto, "tags": tags, "recinto": recinto, "vital": vital,
        "prio_min": prio_min, "prio_max": prio_max, "recursos_kind": recursos_kind,
        "grave": grave, "avisar": avisar,
    }
    row.update(extra)
    return row


HANDMADE: list[dict[str, Any]] = [
    _e("d-leve-unico", "Uno solo, leve", familia="medical", tipo="minor_injury", zona="general",
       texto="Un chico se ha torcido el tobillo en la explanada; camina, pide hielo.",
       tags=("leve", "calma"), prio_min=1, prio_max=4, recursos_kind=("medical",)),
    _e("d-muchos", "Cuatro avisos a la vez, dos equipos libres", familia="medical", tipo="cardiac_arrest",
       zona="front_pit",
       texto="A la vez: 1) persona que no respira en primera fila; 2) cola molesta en puerta B; "
             "3) baño sin papel; 4) alguien pide hielo. Solo hay un médico y un seguridad libres.",
       tags=("muchos", "caos"), vital=True, prio_min=9, prio_max=10, recursos_kind=("medical", "ambulance"),
       previos=[{"zona": "gate_b", "tipo": "crowd", "prioridad": 4, "porque": "Cola molesta en B, no urgente."},
                {"zona": "toilets", "tipo": "infra", "prioridad": 2, "porque": "Baño sin papel."}]),
    _e("d-contradictorio", "Dos versiones que no cuadran", familia="medical", tipo="cardiac_arrest",
       zona="general",
       texto="Uno dice que un señor no respira junto a la torre de sonido. Otro, un minuto después: "
             "ya se levantó y se fue andando, no vengáis.",
       tags=("contradictorio",), vital=True, prio_min=8, prio_max=10, recursos_kind=("medical",)),
    _e("d-rumor", "Bulo de desalojo", familia="info", tipo="rumor_panic", zona="general",
       texto="Corre el rumor de que hay que evacuar todo el recinto por una bomba; nadie ha visto nada. "
             "Gente corre hacia el fondo.",
       tags=("rumor",), prio_min=5, prio_max=8, recursos_kind=("security",), grave=True),
    _e("d-sin-zona", "Aviso sin zona", familia="medical", tipo="heat_stroke", zona=None,
       texto="Una chica se ha desmayado, está muy roja y casi no habla. No sé dónde estamos.",
       tags=("sin_zona",), prio_min=6, prio_max=9, recursos_kind=("medical",)),
    _e("d-parada-ambulancia", "Parada con la ambulancia bloqueada", familia="medical", tipo="cardiac_arrest",
       zona="corridor_s",
       texto="Varón en parada, pasillo sur, hay RCP. La ambulancia interna no puede avanzar: la gente no abre paso.",
       tags=("parada_ambulancia", "vital"), vital=True, prio_min=9, prio_max=10,
       recursos_kind=("medical", "security"),
       efectos=[{"kind": "resource_offline", "resource": "amb_1", "n": 20, "reason": "bloqueada por la multitud"}]),
    _e("d-tormenta", "Tormenta sobre estructuras", familia="weather", tipo="storm_structures", zona="front_pit",
       texto="Viento 70 km/h, lluvia fuerte, el escenario cruje y hay alertas de estructura. ¿Paramos?",
       tags=("tormenta",), prio_min=8, prio_max=10, recursos_kind=("tech", "security"), grave=True,
       efectos=[{"kind": "weather", "rain": True, "wind_kmh": 72, "alert": "tormenta"}]),
    _e("d-incendio-restauracion", "Incendio en restauración", familia="infra", tipo="small_fire", zona="food",
       texto="Sale humo y llamas pequeñas de un puesto de comida en restauración; huele a quemado, hay gente alrededor.",
       tags=("incendio_food",), prio_min=7, prio_max=10, recursos_kind=("tech", "security"), grave=True),
    _e("d-agresion", "Pelea con herido", familia="aggression", tipo="fight", zona="food",
       texto="Pelea entre dos grupos en restauración, uno sangra de la ceja, no sueltan.",
       tags=("agresion",), prio_min=5, prio_max=8, recursos_kind=("security",), avisar=("security_lead",)),
    _e("d-menor", "Menor perdido", familia="info", tipo="lost_child", zona="gate_b",
       texto="He encontrado a un niño de unos seis años solo y llorando junto a la puerta principal; no encuentra a sus padres.",
       tags=("menor", "reservado"), prio_min=6, prio_max=9, recursos_kind=("security", "volunteer"),
       avisar=("security_lead",)),
    _e("d-apagon", "Caída de la luz en restauración", familia="infra", tipo="power_outage_food", zona="food",
       texto="Se ha ido la luz en toda la zona de restauración; cajas muertas, gente empujando en la oscuridad.",
       tags=("apagon",), prio_min=5, prio_max=8, recursos_kind=("tech", "security"),
       efectos=[{"kind": "zone_flag", "zone": "food", "flag": "power", "value": False}]),
    _e("d-puerta", "Puerta saturada", familia="crowd", tipo="gate_saturation", zona="gate_b",
       texto="La puerta principal está a rebosar, la cola no avanza y hay empujones; el contador marca densidad alta.",
       tags=("puerta",), prio_min=5, prio_max=8, recursos_kind=("security", "volunteer")),
    _e("d-agua", "Sin agua con calor", familia="supply", tipo="water_out", zona="water_n",
       texto="El punto de agua norte está seco, cola de cincuenta personas al sol, 40 °C, la cisterna no llega.",
       tags=("agua",), prio_min=6, prio_max=9, recursos_kind=("logistics", "volunteer"),
       efectos=[{"kind": "zone_flag", "zone": "water_n", "flag": "water_l", "value": 0}]),
    _e("d-rechazo", "Un equipo rechaza", familia="medical", tipo="intoxication_overdose", zona="toilets",
       texto="Chico inconsciente que ha mezclado cosas en la cola de los baños. El médico más cercano dice que no puede, está con otro paciente.",
       tags=("rechazo",), prio_min=7, prio_max=10, recursos_kind=("medical",),
       efectos=[{"kind": "resource_rejects", "resource": "med_1", "reason": "otro paciente", "n": 10}]),
    _e("d-silencio", "El staff no contesta", familia="crowd", tipo="gate_saturation", zona="gate_b",
       texto="Sigue la saturación en la puerta principal. El equipo de seguridad asignado no contesta desde hace más de 60 segundos.",
       tags=("silencio",), prio_min=5, prio_max=8, recursos_kind=("security",),
       cambio={"tipo": "silencio"},
       efectos=[{"kind": "resource_no_answer", "resource": "sec_2", "n": 8}]),
    _e("d-segundo-grave", "Segundo grave mientras se atiende uno", familia="medical", tipo="cardiac_arrest",
       zona="general",
       texto="Mientras el médico 2 atiende un mareo en restauración, llega: persona en el suelo en pista, no responde y no respira.",
       tags=("segundo_grave", "vital"), vital=True, prio_min=9, prio_max=10, recursos_kind=("medical",),
       previos=[{"zona": "food", "tipo": "medical", "prioridad": 5, "porque": "Mareo en restauración.",
                 "recursos": ["med_2"]}]),
    _e("d-golpe-cierra-puerta", "Golpe del jurado: cierran una puerta", familia="crowd", tipo="gate_saturation",
       zona="gate_a",
       texto="La puerta norte se ha cerrado de golpe (golpe de jurado). La cola se desvía sola hacia la principal.",
       tags=("golpe_jurado",), prio_min=5, prio_max=8, recursos_kind=("security",),
       efectos=[{"kind": "zone_state", "zone": "gate_a", "state": "closed", "reason": "golpe jurado"}]),
    _e("d-deporte-grada", "Evento deportivo: avalancha en grada", familia="crowd", tipo="crowd_surge_general",
       zona="front_pit", recinto="deporte",
       texto="Estadio de fútbol, mismo motor. Oleada en el fondo sur (mapeado a frente de escenario): la gente se aplasta contra la valla. No es un festival.",
       tags=("deporte", "caos"), prio_min=7, prio_max=10, recursos_kind=("security", "medical"), grave=True),
    _e("d-deporte-rcp", "Evento deportivo: parada en graderío", familia="medical", tipo="cardiac_arrest",
       zona="general", recinto="deporte",
       texto="Partido. Un espectador en la grada general no respira. DESA más cercano al puesto médico. Recinto: estadio, no festival.",
       tags=("deporte", "vital"), vital=True, prio_min=9, prio_max=10, recursos_kind=("medical", "ambulance")),
    _e("d-feria-caseta", "Feria: incendio en caseta", familia="infra", tipo="small_fire", zona="food",
       recinto="feria",
       texto="Feria de abril. Llama en una caseta de restauración (zona food). Gente bebiendo alrededor. Mismo motor, otro recinto.",
       tags=("feria", "incendio_food"), prio_min=7, prio_max=10, recursos_kind=("tech", "security"), grave=True),
    _e("d-feria-nino", "Feria: menor perdido entre casetas", familia="info", tipo="lost_child", zona="food",
       recinto="feria",
       texto="Feria. Niña de cinco años sola entre casetas, llora, no habla. Punto de encuentro no está a la vista.",
       tags=("feria", "menor"), prio_min=6, prio_max=9, recursos_kind=("security", "volunteer")),
    _e("d-edificio-evac", "Edificio: evacuación por humo en planta", familia="infra", tipo="small_fire",
       zona="food", recinto="edificio",
       texto="Edificio de oficinas. Humo en la planta de cafetería (mapeada a restauración). Alguien pide evacuar las 8 plantas. No es un festival.",
       tags=("edificio",), prio_min=8, prio_max=10, recursos_kind=("security", "tech"), grave=True),
    _e("d-edificio-ascensor", "Edificio: persona atrapada, no vital", familia="medical", tipo="trauma_fall",
       zona="corridor_n", recinto="edificio",
       texto="Centro comercial. Persona atrapada en un ascensor entre plantas; habla, no sangra, está asustada.",
       tags=("edificio", "leve"), prio_min=3, prio_max=6, recursos_kind=("tech", "medical")),
    _e("d-broma", "Broma de cerveza", familia="info", tipo="false_alarm_prank", zona="gate_b",
       texto="SOCORRO se ha desmayado mi dignidad en la cola, es una emergencia nacional 😂 cerveza.",
       tags=("leve",), prio_min=0, prio_max=3, recursos_kind=()),
    _e("d-valla", "Valla que cede", familia="infra", tipo="barrier_failure", zona="front_pit",
       texto="Ha cedido un tramo de valla; la aguantamos a mano. Pido técnico y otra pareja.",
       tags=("caos",), prio_min=7, prio_max=10, recursos_kind=("tech", "security")),
    _e("d-calor", "Alerta de calor extremo", familia="weather", tipo="extreme_heat_alert", zona="general",
       texto="Sensor: 40 °C, índice de calor 44, alerta naranja. Aún no hay desmayos.",
       tags=("calma",), prio_min=4, prio_max=7, recursos_kind=("logistics", "volunteer")),
    _e("d-rayos", "Rayos a menos de 10 km", familia="weather", tipo="lightning_nearby", zona="general",
       texto="Rayos a 8 km. El público está al descubierto. ¿Paramos el concierto?",
       tags=("tormenta",), prio_min=7, prio_max=10, recursos_kind=("security",), grave=True),
    _e("d-objeto", "Mochila abandonada", familia="external", tipo="suspicious_object", zona="gate_b",
       texto="Mochila negra abandonada en el torno 3 de la puerta principal. Nadie la reclama. No la tocamos.",
       tags=("caos",), prio_min=8, prio_max=10, recursos_kind=("security",), grave=True),
    _e("d-intox", "Sobredosis en baños", familia="medical", tipo="intoxication_overdose", zona="toilets",
       texto="Chico pálido que no despierta, ha vomitado, los amigos dicen que mezcló cosas. Cola de baños.",
       tags=("caos",), prio_min=6, prio_max=9, recursos_kind=("medical",)),
    _e("d-acoso", "Grupo que no deja irse a alguien", familia="aggression", tipo="harassment_group", zona="toilets",
       texto="Un grupo está acosando a una chica junto a los aseos y no la dejan irse.",
       tags=("agresion",), prio_min=5, prio_max=8, recursos_kind=("security",)),
    _e("d-contraflujo", "Contraflujo en la salida", familia="crowd", tipo="counterflow_exit", zona="exit_transport",
       texto="A la salida se cruzan los que entran con los que se van; el metro está lleno y hay empujones.",
       tags=("puerta",), prio_min=5, prio_max=8, recursos_kind=("security", "volunteer")),
    _e("d-comms", "Se cae la red de radios", familia="infra", tipo="comms_network_down", zona="backstage",
       texto="La red de radios del staff ha caído. Telegram sigue. Varios equipos en silencio de radio.",
       tags=("silencio",), prio_min=5, prio_max=8, recursos_kind=("tech",),
       efectos=[{"kind": "comms_down", "channel": "voice", "n": 10}]),
    _e("d-cashless", "Cae el pago", familia="infra", tipo="cashless_down", zona="food",
       texto="No funciona el pago en las barras. Colas y gente enfadada, todavía no hay pelea.",
       tags=("leve",), prio_min=3, prio_max=6, recursos_kind=("tech",)),
    _e("d-pmr", "Plataforma PMR desbordada", familia="crowd", tipo="pmr_platform_overcrowded", zona="pmr",
       texto="La plataforma PMR está llena, hay sillas que no pueden salir y una persona angustiada.",
       tags=("leve",), prio_min=4, prio_max=7, recursos_kind=("security", "volunteer")),
    _e("d-dron", "Dron no autorizado", familia="external", tipo="drone_intrusion", zona="front_pit",
       texto="Un dron vuela bajo sobre el público del frente. No es de producción.",
       tags=("calma",), prio_min=4, prio_max=7, recursos_kind=("security",), grave=True),
    _e("d-retraso-artista", "Cancelan al cabeza de cartel", familia="external", tipo="artist_delay_cancel",
       zona="front_pit",
       texto="Producción: el cabeza de cartel cancela. El público no lo sabe. Riesgo de empujón a la salida.",
       tags=("muchos",), prio_min=5, prio_max=8, recursos_kind=("security",)),
    _e("d-anafilaxia", "Alergia grave", familia="medical", tipo="anaphylaxis", zona="food",
       texto="Chica con alergia, se le hincha la boca tras un pincho, dice que no lleva el boli. Restauración.",
       tags=("caos",), vital=True, prio_min=8, prio_max=10, recursos_kind=("medical", "ambulance")),
    _e("d-golpe-ambulancia", "Golpe: bloquean la ambulancia", familia="resource", tipo="ambulance_blocked_by_crowd",
       zona="corridor_s",
       texto="Golpe del jurado: la ambulancia se queda clavada en el pasillo sur. Hay una parada abierta en pista.",
       tags=("golpe_jurado", "parada_ambulancia"), vital=True, prio_min=8, prio_max=10,
       recursos_kind=("security",),
       previos=[{"zona": "general", "tipo": "medical", "prioridad": 10,
                 "porque": "Parada en pista, no respira.", "recursos": ["med_1"]}],
       efectos=[{"kind": "resource_offline", "resource": "amb_1", "n": 15, "reason": "golpe jurado"}]),
    _e("d-ingles", "Aviso en inglés sin sitio", familia="medical", tipo="intoxication_overdose", zona=None,
       texto="pls help my mate took something and wont wake up, throwing up, dont know which toilet",
       tags=("sin_zona",), prio_min=6, prio_max=9, recursos_kind=("medical",)),
    _e("d-desmentido", "Desmienten el aviso anterior", familia="info", tipo="contradictory_reports", zona="general",
       texto="Lo del señor de la torre de sonido ya está, se ha levantado y se ha ido. Era un mareo.",
       tags=("contradictorio",), prio_min=2, prio_max=7, recursos_kind=("medical",),
       previos=[{"zona": "general", "tipo": "medical", "prioridad": 9,
                 "porque": "Aviso de parada en torre de sonido."}]),
    _e("d-fuga-gas", "Huele a gas en cocinas", familia="infra", tipo="small_fire", zona="food",
       texto="Huele a gas en las cocinas de restauración, un cocinero ha cerrado la llave, pide técnico y vaciar la zona.",
       tags=("incendio_food",), prio_min=8, prio_max=10, recursos_kind=("tech", "security"), grave=True),
    _e("d-turno", "Fin de turno sin relevo", familia="resource", tipo="shift_end_no_relief", zona="gate_c",
       texto="Seguridad de la puerta sur acaba turno y no hay relevo. La puerta sigue abierta con cola.",
       tags=("rechazo",), prio_min=4, prio_max=7, recursos_kind=("security",),
       efectos=[{"kind": "resource_offline", "resource": "sec_5", "n": 30, "reason": "fin de turno"}]),
]


def heldout_escenarios(n: int = 8) -> list[dict[str, Any]]:
    from motor.cases import iter_cases
    out: list[dict[str, Any]] = []
    for case in iter_cases(seed=1, split="heldout", start=0, n=max(n * 3, n)):
        ev = next((e for e in (case.get("events") or []) if e.get("kind") == "incident"), None)
        if not ev:
            continue
        inc = ev.get("incident") or {}
        reps = ev.get("reports") or []
        texto = str((reps[0] or {}).get("text") or inc.get("type") or "")[:400]
        out.append(_e(
            f"heldout-{case.get('id')}",
            f"Heldout {case.get('id')}",
            familia=str(inc.get("family") or ""),
            tipo=str(inc.get("type") or ""),
            zona=inc.get("zone"),
            texto=texto,
            tags=("heldout",),
            vital=str(inc.get("type") or "") == "cardiac_arrest",
            prio_min=max(0, int(inc.get("severity") or 5) - 2),
            prio_max=min(10, int(inc.get("severity") or 5) + 1),
            heldout_id=case.get("id"),
            case_id=case.get("id"),
        ))
        if len(out) >= n:
            break
    return out


def handmade() -> list[dict[str, Any]]:
    return list(HANDMADE)


def todos(n: int | None = None) -> list[dict[str, Any]]:
    bank = handmade() + heldout_escenarios(8)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for e in bank:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        out.append(e)
    if n is not None:
        n = max(1, int(n))
        if n >= len(out):
            return out
        held = [e for e in out if e.get("heldout_id")]
        hand = [e for e in out if not e.get("heldout_id")]
        n_held = min(len(held), 8 if n >= 40 else max(0, n // 10))
        n_hand = max(0, n - n_held)
        return (hand[:n_hand] + held[:n_held])[:n]
    return out


def por_id(eid: str) -> dict[str, Any]:
    for e in todos():
        if e["id"] == eid:
            return e
    raise KeyError(eid)


def iter_n(n: int) -> Iterator[dict[str, Any]]:
    yield from todos(n)
