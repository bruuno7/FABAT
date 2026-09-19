"""Niveles de autonomía: qué ejecuta Mando solo y qué espera el sí de una persona CON CARGO.

Regla práctica (dictamen de seguridad de eventos): reversible y de bajo arrepentimiento → sola; irreversible o de
efecto masivo → persona con cargo; íntimo o penal → ni tocarlo.

    APPROVE  evacuar, parar el concierto, pedir ayuda externa (ALWAYS_APPROVE del contrato), cerrar una zona,
             megafonía GENERAL (pista, frente de escenario o todo el recinto: un mensaje mal dicho por la PA
             principal provoca la carrera que se quiere evitar) y todo REROUTE cuyo ensayo (o, sin gemelo, su
             proyección) no deje el destino por debajo de 4 personas/m².
    AUTO     despachar, avisar, preguntar, restringir (no cerrar), reabastecer, megafonía de zona pequeña
             (puertas, pasillos, puntos de agua) y REROUTE ensayado con el destino < 4/m².

Toda acción que espera aprobación lleva una TARJETA DE DECISIÓN (`params["decision_card"]`): a qué cargo va y quién
es su suplente, las dos ramas ensayadas (si aprueba / si veta), la ventana para decidir y el minuto en que se escala
al suplente si nadie contesta. Una evacuación «preparada» ante una amenaza no la puede ejecutar un aprobador
automático: exige `approve(id, True, note)` con `note` que empiece por «EVACUAR».

Dos reglas que ninguna lección ni parámetro puede cambiar: lo de ALWAYS_APPROVE nunca sale en AUTO, y un despacho
nunca espera aprobación (una posible parada cardiaca no puede esperar a nadie).
"""
from __future__ import annotations

from typing import Any

from ..contracts import ALWAYS_APPROVE, Action, ActionKind, ActionStatus, Autonomy, Incident

_VERB = {
    ActionKind.EVACUATE: "EVACUAR", ActionKind.STOP_SHOW: "PARAR EL CONCIERTO",
    ActionKind.REQUEST_EXTERNAL: "PEDIR AYUDA EXTERNA", ActionKind.SET_ZONE: "CERRAR",
    ActionKind.DISPATCH: "ENVIAR EQUIPO", ActionKind.BROADCAST: "MEGAFONÍA", ActionKind.REROUTE: "DESVIAR",
    ActionKind.RESUPPLY: "REABASTECER", ActionKind.RECALL: "RETIRAR EQUIPO",
}

# Qué propone Mando si la persona veta: siempre hay un escalón menos drástico.
ALTERNATIVE = {
    ActionKind.EVACUATE: "restringir la entrada a la zona, desviar el flujo y avisar por megafonía",
    ActionKind.STOP_SHOW: "mensaje de calma por megafonía y refuerzo de seguridad en el frente",
    ActionKind.REQUEST_EXTERNAL: "resolver con recursos propios y tener al 112 preavisado",
    ActionKind.SET_ZONE: "restringir la zona en vez de cerrarla",
    ActionKind.DISPATCH: "mantener la vigilancia a distancia y esperar instrucciones",
    ActionKind.BROADCAST: "avisar solo al personal y a las pantallas de la zona afectada",
    ActionKind.REROUTE: "no desviar: restringir la entrada y reforzar el acceso",
}


SAFE_DENSITY = 4.0
GENERAL_PA = ("general", "stage_front")     # zonas cuya megafonía es la PA principal
DIRECTOR = "Director del Plan de Actuación"
DEPUTY = {DIRECTOR: "Jefe de seguridad del recinto (suplente del Director del Plan)",
          "Coordinador sanitario": DIRECTOR,
          "Responsable del punto violeta (con el consentimiento de la víctima)": DIRECTOR}


def level(action: Action, zone_kind: str | None = None) -> Autonomy:
    p = action.params
    if action.kind in ALWAYS_APPROVE:
        return Autonomy.APPROVE
    if action.kind == ActionKind.SET_ZONE and p.get("state") == "closed":
        return Autonomy.APPROVE
    if action.kind == ActionKind.BROADCAST and (action.zone is None or zone_kind in GENERAL_PA or p.get("scope") == "venue"):
        return Autonomy.APPROVE
    if action.kind == ActionKind.REROUTE and not p.get("cancel"):
        peak = p.get("dest_peak_density")
        return Autonomy.AUTO if peak is not None and peak < SAFE_DENSITY else Autonomy.APPROVE
    return Autonomy.AUTO  # incluye todo DISPATCH: una parada cardiaca nunca espera a nadie


def addressee(action: Action, inc: Incident | None) -> str:
    """El cargo que de verdad decide (RD 393/2007): no «un operador con un botón»."""
    if action.kind == ActionKind.REQUEST_EXTERNAL:
        service = str(action.params.get("kind") or action.params.get("service") or "")
        if inc is not None and inc.type == "sexual_assault":
            return "Responsable del punto violeta (con el consentimiento de la víctima)"
        if service in ("ambulance", "medical"):
            return "Coordinador sanitario"
    return DIRECTOR


def decision_card(action: Action, inc: Incident | None, t: int, approved: Any = None, vetoed: Any = None,
                  life_threat: bool = False) -> dict[str, Any]:
    """Tarjeta para lo grave. `approved` y `vetoed` son `rehearsal.Outcome` (o None si no hay gemelo)."""
    who = addressee(action, inc)
    window = 3 if life_threat else 10
    if vetoed is not None:   # la ventana sale del ensayo: minutos hasta el aplastamiento o hasta el pico si no se hace nada
        crush = min(vetoed.crush_at.values(), default=None)
        peak_zone = max(vetoed.peak, key=lambda z: vetoed.peak[z]) if vetoed.peak else None
        window = crush if crush else (vetoed.peak_at[peak_zone] if peak_zone and vetoed.peak[peak_zone] >= SAFE_DENSITY else window)
    window = max(2, min(15, int(window)))

    def branch(o: Any) -> dict[str, Any] | None:
        if o is None:
            return None
        return {"peak_density": round(o.worst, 2), "minutes_over_4": sum(o.over4.values()),
                "crush_at_min": min(o.crush_at.values(), default=None), "by_zone": o.to_dict()["peak_density"],
                "minutes": o.minutes}
    return {"addressee": who, "deputy": DEPUTY.get(who, DIRECTOR), "if_approved": branch(approved),
            "if_vetoed": branch(vetoed), "rehearsed": approved is not None and vetoed is not None,
            "window_min": window, "asked_at": t, "escalate_at": t + max(2, (window + 1) // 2), "escalated_at": None,
            "answered_at": None}


def card_line(card: dict[str, Any]) -> str:
    """Las dos ramas en una frase: «si apruebas: 4,0/m² · si no: 6,5/m² en 9 min»."""
    a, v = card.get("if_approved"), card.get("if_vetoed")
    if not a or not v:
        return f"ventana para decidir: {card['window_min']} min"

    def one(b: dict[str, Any]) -> str:
        text = f"{str(b['peak_density']).replace('.', ',')}/m² de pico"
        if b.get("crush_at_min"):
            text += f", aplastamiento en {b['crush_at_min']} min"
        elif b.get("minutes_over_4"):
            text += f", {b['minutes_over_4']} min por encima de 4/m²"
        return text
    return f"si apruebas: {one(a)} · si no: {one(v)} · ventana: {card['window_min']} min"


def gate(action: Action, zone_kind: str | None = None) -> Action:
    """Fija autonomía y estado. Si hace falta aprobación, reescribe `why` para leerlo en cinco segundos."""
    action.autonomy = level(action, zone_kind)
    if action.autonomy == Autonomy.AUTO:
        action.status = ActionStatus.EXECUTING
        return action
    action.status = ActionStatus.AWAITING_APPROVAL
    verb = _VERB.get(action.kind, str(action.kind).upper())
    where = f" {action.zone}" if action.zone else ""
    alt = ALTERNATIVE.get(action.kind)
    action.params.setdefault("reason", action.why)
    action.why = f"¿{verb}{where}? {action.why}." + (f" Si dices no: {alt}." if alt else "")
    return action


def veto_lesson(action: Action, inc: Incident | None, note: str, n: int) -> dict[str, Any]:
    """Lección candidata a partir de un veto. No entra sola en el manual: la valida el revisor."""
    when: dict[str, Any] = {}
    if inc is not None:
        when["type"] = inc.type
    if action.zone:
        when["zone"] = action.zone
    forbid: dict[str, Any] = {"kind": str(action.kind)}
    if action.kind == ActionKind.SET_ZONE:
        forbid["state"] = action.params.get("state")
    return {
        "id": f"V-{n:03d}", "when": when, "then": {"forbid_action": forbid},
        "text": f"el operador vetó «{str(action.kind)}»" + (f" en {action.zone}" if action.zone else "")
                + (f": {note}" if note else ""),
        "source": "veto del operador", "evidence_n": 1,
    }
