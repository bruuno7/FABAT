"""Selección de destinatario; no altera los contratos del núcleo."""
from motor.contracts import ActionKind


WORKFLOW_NAMES = {
    'sanitario': 'mando-despacho-sanitario',
    'seguridad': 'mando-despacho-seguridad',
    'tecnico': 'mando-despacho-tecnico',
    'logistica': 'mando-despacho-logistica',
    'director': 'mando-escalada-director',
    'externos': 'mando-aviso-servicios-externos',
    'difusion': 'mando-difusion-publico',
    'relevo': 'mando-relevo-y-refuerzo',
    'personal': 'mando-ingesta-personal',
    'sms': 'mando-ingesta-sms',
    'avisos_externos': 'mando-avisos-externos',
    'email': 'mando-ingesta-email',
}

# Oficio dicho por una persona (o por HappyRobot en Telegram) -> ranura de workflow.
ROLE_SLOTS = {
    'medical': 'sanitario', 'sanitario': 'sanitario', 'medico': 'sanitario', 'médico': 'sanitario',
    'enfermero': 'sanitario', 'ambulance': 'sanitario', 'ambulancia': 'sanitario',
    'security': 'seguridad', 'seguridad': 'seguridad', 'jefe_sector': 'seguridad', 'jefe de sector': 'seguridad',
    'jefe_zona': 'seguridad', 'jefe de zona': 'seguridad',
    'tech': 'tecnico', 'tecnico': 'tecnico', 'técnico': 'tecnico',
    'logistics': 'logistica', 'logistica': 'logistica', 'logística': 'logistica',
    'volunteer': 'relevo', 'voluntario': 'relevo',
    'organizador': 'director', 'director': 'director',
    'staff_entradas': 'logistica', 'entradas': 'logistica',
    'bomberos': 'seguridad', 'bombero': 'seguridad',
    'policia': 'seguridad', 'policía': 'seguridad',
}


def slot_for_role(role):
    """Ranura de workflow de un oficio suelto. Misma tabla que usa `workflow_slot`."""
    return ROLE_SLOTS.get(str(role or '').strip().lower())


def workflow_slot(action, resource=None):
    """Los roles sin ResourceKind viajan en params; no se añaden tipos al núcleo."""
    p = action.params
    role = str(p.get('to') or p.get('recipient_role') or '').strip().lower()
    if p.get('decision_for'):
        return 'director'
    if action.kind == ActionKind.REQUEST_EXTERNAL:
        return 'externos'
    if action.kind == ActionKind.BROADCAST or role in ('public', 'publico', 'público'):
        return 'difusion'
    if action.kind == ActionKind.RESUPPLY or role in ('supplier', 'proveedor', 'logistica', 'logística'):
        return 'logistica'
    if p.get('relief') or role in ('reserve', 'reserva', 'voluntario', 'volunteer', 'relevo'):
        return 'relevo'
    if resource is not None:
        return {'medical': 'sanitario', 'ambulance': 'sanitario', 'security': 'seguridad',
                'tech': 'tecnico', 'logistics': 'logistica', 'volunteer': 'relevo'}.get(str(resource.kind), 'dispatch')
    role_slot = slot_for_role(role)
    if role_slot:
        return role_slot
    if action.kind == ActionKind.ASK:
        return 'followup' if p.get('followup') else 'ask'
    return 'notify' if action.kind == ActionKind.NOTIFY else 'dispatch'


def endpoint(comms, slot):
    import os
    if comms.launch_mode == 'runs':
        wid = comms.workflows.get(slot)
        return f'{comms.api_base}/workflows/{wid}/runs' if wid and os.environ.get('HR_API_KEY') else ''
    return comms.hooks.get(slot, '')


def generic_retry(comms, aid, why):
    """Reserva un único intento genérico. El llamador hace la red fuera del cerrojo."""
    import time
    with comms._lock:
        call = comms.calls.get(aid, {})
        flight = comms._inflight.get(aid)
        slot = call.get('workflow')
        hook = endpoint(comms, 'dispatch')
        if (not flight or aid in comms._closed or aid in comms._early or not hook or
                slot not in WORKFLOW_NAMES or slot in ('difusion', 'personal', 'sms', 'email', 'avisos_externos') or
                flight.get('generic_attempted') or endpoint(comms, slot) == hook):
            return None
        flight.update(generic_attempted=True, deadline=time.monotonic() + comms.fallback_s)
        call.update(workflow='dispatch', stage='respaldo: despacho genérico')
        call.setdefault('workflow_history', []).append('dispatch')
        comms.revision += 1
    comms.on_log('action', f'HappyRobot {aid}: {slot} falla ({why}); reenvío al despacho genérico', aid, real=True)
    return hook


def apply_decision(session, event):
    """El cerrojo y la política multioperador son los mismos que /api/approve.

    HR_SECRET autentica el transporte. El nonce emitido y el cargo destinatario
    vinculan esta respuesta a una solicitud concreta de esta partida.
    """
    from fastapi import HTTPException
    if event.get('recovered'):
        raise HTTPException(422, 'La decisión exige JSON completo')
    decision = event.get('decision')
    if decision not in ('approve', 'veto'):
        return {'ok': False, 'pending': True, 'error': 'explicit_decision_required'}
    note = event.get('note', '')
    if not isinstance(note, str):
        raise HTTPException(422, 'note debe ser texto')
    with session.lock:
        comms = session.comms
        with comms._lock:
            wire_id = event.get('action_id')
            aid = comms._wire_to_action.get(wire_id)
            call = comms.calls.get(aid, {})
            target = call.get('decision_for')
            role = call.get('decision_role')
            if not target or role not in ('director', 'suplente') or event.get('by_role') != role:
                raise HTTPException(403, 'Decisión sin solicitud telefónica o cargo válido')
            if aid in comms._closed:
                return {'ok': True, 'duplicate': True}
            if event.get('mode') == 'test':
                return {'ok': True, 'test': True}
            who = {'id': 'phone-' + role, 'name': 'por teléfono: ' + role, 'role': 'coordinación'}
            # Identidad estable: repetir llamadas no aporta una segunda firma.
            if hasattr(session, 'operators'):
                out = session.operators.decide(target, decision == 'approve', note[:200], who)
            else:
                if not session.approve(target, decision == 'approve', note[:200], by=who['name']):
                    raise HTTPException(409, 'Esa acción no está esperando aprobación')
                out = {'ok': True, 'pending': False}
            comms._closed.add(aid)
            comms._inflight.pop(aid, None)
            call.update(result=decision, stage='decisión registrada', t_end=session.world.t)
            comms.workflow_status.record('director', 'event')
            session._rebuild()
            return out


def prepare_outputs(session, snapshot):
    """Solicitudes telefónicas y difusión aprobada; el gemelo no espera la red."""
    from motor.contracts import Action, Channel
    c = session.comms
    if c.mode != 'happyrobot':
        return
    for item in snapshot.get('actions', []):
        original = session.agent.actions.get(item['id'])
        if original is None:
            continue
        if item.get('status') == 'awaiting_approval' and c.voice_mode == 'phone':
            card = original.params.get('decision_card') or {}
            role = 'suplente' if card.get('escalated_at') is not None else 'director'
            if not c.contacts.get('roles', {}).get(role):
                continue
            aid = f"decision:{original.id}:{role}"
            if aid in c.calls:
                continue
            branches = []
            for number, key in enumerate(('if_approved', 'if_vetoed'), 1):
                branch = card.get(key) or {}
                density = branch.get('peak_density')
                branches.append(f"Futuro {number}: densidad máxima {density} personas por metro cuadrado, "
                                f"ensayo N=1, horizonte {branch.get('minutes')} minutos."
                                if density is not None else f"Futuro {number}: sin ensayo disponible.")
            incident = session._incident_for_comms(original.incident) or {}
            why = 'Incidente reservado; consulte la decisión en pantalla segura' if incident.get('reserved') else original.why
            text = f"Decisión pendiente {original.id}: {why}. " + ' '.join(branches)
            request = Action(aid, ActionKind.NOTIFY, session.world.t, zone=original.zone,
                             params={'to': role, 'decision_for': original.id, 'message': text}, channel=Channel.VOICE)
            c.send(request)
        elif item.get('kind') == 'broadcast' and item.get('status') in ('executing', 'done'):
            if original.id not in c.calls and session._approval_record(original.id):
                c.send(original)
