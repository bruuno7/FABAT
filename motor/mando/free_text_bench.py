"""Avisos libres escritos A MANO para medir el parser (no salen de ninguna plantilla de `motor/cases`).

Se escribieron ANTES de rehacer el léxico y no se tocan para que cuadren. DEV se usa para ajustar alias y
vocabulario; HOLDOUT solo se mide. Cada fila: (texto, familia esperada, tipo esperado o None, zona esperada).
- tipo None = el aviso no tiene por qué caer en un tipo concreto del léxico: solo se puntúa la familia.
- zona None = el aviso no dice dónde (lo correcto es devolver None y preguntar); una tupla = vale cualquiera.

    python3 -m motor.mando.free_text_bench
"""
from __future__ import annotations

DEV = [
    ("Hay un señor tirado en el suelo detrás de los baños, no se mueve", "medical", "unconscious_person", "toilets"),
    ("mi novia se ha desmayado junto a la barra, venid porfa", "medical", "fainting", "food"),
    ("pelea gorda al lado de la puerta C, hay cuatro tíos dándose", "aggression", "fight", "gate_c"),
    ("en la zona vip se ha ido la luz", "infra", "power_outage", "vip"),
    ("huele a quemado cerca del backstage y sale humo", "infra", "fire", "backstage"),
    ("no queda agua en la fuente del norte", "supply", "water_out", "water_n"),
    ("estamos aplastados en primera fila, no podemos respirar", "crowd", "crush_risk", "front_pit"),
    ("there's a guy with a knife near gate A", "aggression", "weapon", "gate_a"),
    ("my friend is not breathing, we're by the toilets", "medical", "cardiac_arrest", "toilets"),
    ("la cola de la puerta B no avanza desde hace media hora", "crowd", "gate_saturation", "gate_b"),
    ("se ha perdido mi hijo de 6 años, estábamos en la zona de comida", "info", "lost_child", "food"),
    ("una chica dice que la han tocado sin su permiso en la pista", "aggression", "sexual_assault", "general"),
    ("el datáfono no funciona en ninguna barra", "infra", "payment_down", "food"),
    ("le ha dado un ataque epiléptico a un chaval frente al escenario", "medical", "seizure", "front_pit"),
    ("hay una mochila abandonada junto a la puerta A", "external", "suspicious_object", "gate_a"),
    ("la plataforma para sillas de ruedas está abarrotada, no cabemos", "crowd", None, "pmr"),
    ("viento muy fuerte, se mueve la carpa de la zona vip", "weather", "high_wind", "vip"),
    ("necesito un médico, un hombre mayor con dolor en el pecho, pasillo sur", "medical", None, "corridor_s"),
    ("han robado tres móviles en el foso", "aggression", "theft", "front_pit"),
    ("no salen autobuses y la parada está a reventar de gente", "external", None, "exit_transport"),
]

HOLDOUT = [
    ("un chico se ha caído de la valla y sangra por la cabeza, estamos entre la barra y los baños", "medical", "injury", ("food", "toilets")),
    ("se están pegando en la cola de los baños", "aggression", "fight", "toilets"),
    ("no hay luz en el pasillo norte, la gente va a oscuras", "infra", "power_outage", "corridor_n"),
    ("mi amigo ha tomado algo y está muy mal, no reacciona, estamos en mitad de la pista", "medical", None, "general"),
    ("somebody fainted right in front of the stage", "medical", "fainting", "front_pit"),
    ("fire behind the food trucks!!", "infra", "fire", "food"),
    ("la puerta principal está colapsada, no cabe un alma", "crowd", "gate_saturation", "gate_b"),
    ("un dron está volando sobre la pista", "external", "drone", "general"),
    ("señora mayor mareada por el calor en el punto de agua sur", "medical", None, "water_s"),
    ("tormenta eléctrica acercándose, se ven rayos", "weather", "storm", None),
    ("los baños están atascados y sale agua por el suelo", "infra", "toilets_failure", "toilets"),
    ("un hombre sigue a una chica y no la deja en paz, zona vip", "aggression", None, "vip"),
    ("necesitamos ayuda!! no sé dónde estamos, hay mucha gente y una chica en el suelo que no responde", "medical", "unconscious_person", None),
    ("paquete sospechoso debajo de una mesa en restauración", "external", "suspicious_object", "food"),
    ("el generador del backstage se está quedando sin gasoil", "supply", "fuel_shortage", "backstage"),
    ("kind verloren, wir sind am eingang b", "info", "lost_child", "gate_b"),
    ("il y a une bagarre près des toilettes", "aggression", "fight", "toilets"),
    ("la ambulancia no puede pasar por el pasillo sur, está lleno de gente", ("resource", "crowd"), None, "corridor_s"),
    ("alguien ha llamado diciendo que hay una bomba", "external", "unknown_external", None),
    ("se ha soltado un trozo del vallado frente al escenario, peligro", "infra", None, "front_pit"),
]


# Ubicaciones difíciles, escritas a mala idea contra mis propios alias (solo se puntúa la zona). Se miden tal cual.
HARD_ZONES = [
    ("se ha caído una chica, estoy al fondo, cerca de donde venden las cervezas", "medical", None, "food"),
    ("pelea en la cola para entrar, la de la derecha", "aggression", None, None),
    ("hay un señor inconsciente justo debajo de la pantalla grande de la izquierda", "medical", None, None),
    ("pelea en los servicios portátiles de al lado del escenario", "aggression", None, "toilets"),
    ("un chico sangrando, saliendo del recinto hacia el parking", "medical", None, "exit_transport"),
    ("se ha desmayado una mujer donde los minusválidos", "medical", None, "pmr"),
    ("necesitan ayuda en el puesto de la cruz roja, hay una pelea", "aggression", None, ("medical_1", "medical_2", None)),
    ("chica inconsciente en el césped del centro", "medical", None, "general"),
    ("there is a fight by the main entrance", "aggression", None, "gate_b"),
    ("someone fainted at the bar next to the VIP area", "medical", None, ("food", "vip")),
    ("pelea en los tornos de acceso, puerta c", "aggression", None, "gate_c"),
    ("un chico herido al lado de la mesa de sonido", "medical", None, "general"),
    ("pelea en la zona de acampada", "aggression", None, None),
    ("hay un herido junto a las taquillas", "medical", None, None),
    ("fuego detrás de la barra principal, en la zona de carga", "infra", None, "food"),
    ("un desmayo entre el escenario y la zona vip", "medical", None, ("front_pit", "vip")),
    ("señora herida en la rampa de la plataforma de discapacitados", "medical", None, "pmr"),
    ("pelea en el camino que lleva a la salida norte", "aggression", None, "gate_a"),
    ("desmayo aquí en la fuente, la que está pegada a la puerta A", "medical", None, ("water_n", "gate_a")),
    ("herido frente al puesto de socorro 2", "medical", None, "medical_2"),
]


def score(rows, parser=None, zones=None) -> dict:
    from motor.contracts import Channel, Report
    from motor.mando.parser import HeuristicParser
    from motor.mando.test_mando import real_zones
    parser, zones = parser or HeuristicParser(), zones or real_zones()
    out = {"n": len(rows), "family": 0, "zone": 0, "type_n": 0, "type": 0, "misses": []}
    for text, family, type_, zone in rows:
        p = parser.parse(Report("r", 0, Channel.WHATSAPP, text), zones)
        fam_ok = str(p["family"]) in (family if isinstance(family, tuple) else (family,))
        zone_ok = p["zone"] in (zone if isinstance(zone, tuple) else (zone,))
        type_ok = type_ is None or p["type"] == type_
        out["family"] += fam_ok
        out["zone"] += zone_ok
        out["type_n"] += type_ is not None
        out["type"] += type_ is not None and type_ok
        if not (fam_ok and zone_ok and type_ok):
            out["misses"].append((text[:60], f"{p['family']}/{p['type']}/{p['zone']}", f"esperado {family}/{type_}/{zone}"))
    return out


if __name__ == "__main__":
    import argparse
    import os
    ap = argparse.ArgumentParser(description="Banco de avisos libres (N aparte; no mezclar con headline)")
    ap.add_argument("--llm", action="store_true",
                    help="CascadeParser+LLM (gasta cuota). Requiere AGENTES_LLM_KEY y MANDO_LLM=1")
    args = ap.parse_args()
    parser = None
    tag = "heurístico"
    if args.llm:
        os.environ.setdefault("MANDO_LLM", "1")
        try:
            from motor.server.llm_parser_factory import build_cascade_parser, llm_configured
            ok, why = llm_configured()
            if not ok:
                raise SystemExit(f"--llm no disponible: {why}")
            parser = build_cascade_parser()
            tag = "cascada+LLM"
        except SystemExit:
            raise
        except Exception as ex:
            raise SystemExit(f"--llm falló al construir parser: {ex}") from ex
    for name, rows in (("DEV", DEV), ("HOLDOUT", HOLDOUT), ("UBICACIONES DIFÍCILES", HARD_ZONES)):
        r = score(rows, parser=parser)
        print(f"{name} [{tag}]: N={r['n']} · familia {r['family']}/{r['n']} · zona {r['zone']}/{r['n']} · "
              f"tipo {r['type']}/{r['type_n']} (solo filas con tipo esperado)")
        for miss in r["misses"]:
            print("   ✗", *miss, sep=" | ")
