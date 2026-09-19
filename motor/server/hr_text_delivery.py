"""Transporte de texto solicitado por un workflow, nunca por el modelo directamente."""
from fastapi import HTTPException


def deliver_text(session, event, bot):
    if event.get('recovered'):
        raise HTTPException(422, 'La autorización exige JSON completo')
    with session.lock:
        c = session.comms
        aid = c._wire_to_action.get(event.get('action_id'))
        expected = c.payloads.get(aid, {})
        approval = session._approval_record(aid) if aid else None
        if not approval or not event.get('approved_by') or any(
                event.get(k) != expected.get(k) for k in ('approved_by', 'message_text', 'audience')):
            raise HTTPException(403, 'Difusión sin aprobación o contenido autorizado')
        if approval.get('by') != event['approved_by']:
            raise HTTPException(403, 'El aprobador no coincide con el registro humano')
        if event.get('mode') == 'test':
            return dict(ok=True, test=True, delivered=0, failed=0)
        if aid in c.text_receipts:
            return dict(c.text_receipts[aid])
        audience = c.contacts.get('audiences', {}).get(event['audience'])
        if not isinstance(audience, dict):
            raise HTTPException(422, 'Audiencia no configurada en la lista blanca')
        destinations = audience.get('telegram', [])
        if not isinstance(destinations, list) or any(type(x) is not int for x in destinations):
            raise HTTPException(422, 'Lista de destinatarios Telegram inválida')
        text = event['message_text']
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise HTTPException(422, 'Texto inválido; no se recorta una instrucción aprobada')
        # Reservar antes de soltar el cerrojo: reintentar el webhook no duplica envíos.
        c.text_receipts[aid] = dict(ok=True, pending=True, delivered=0, failed=0)
    delivered = failed = 0
    for destination in dict.fromkeys(destinations):
        try:
            if bot is None or bot.mode == 'off':
                raise RuntimeError('Transporte Telegram no configurado')
            bot._call('sendMessage', {'chat_id': destination, 'text': text})
            delivered += 1
        except Exception:
            failed += 1
    # SMS sigue bloqueado hasta configurar un proveedor; jamás fingir entrega.
    sms = audience.get('sms', [])
    failed += len(sms) if isinstance(sms, list) else 1
    result = dict(ok=failed == 0, type='diffusion_result', action_id=event['action_id'],
                  delivered=delivered, failed=failed, pending=False)
    if not destinations and not sms:
        result.update(ok=False, error='empty_audience')
    with session.lock:
        c.text_receipts[aid] = result
        if hasattr(c, '_inflight'):
            c._inflight.pop(aid, None)
            c._closed.add(aid)
            c.calls[aid].update(stage='texto entregado' if result['ok'] else 'entrega parcial o fallida',
                                delivered=delivered, failed=failed, result='delivered' if result['ok'] else 'failed')
            c.revision += 1
        c.workflow_status.record('difusion', 'event', error='' if result['ok'] else 'Entrega parcial o fallida')
        session._rebuild()
    return dict(result)


def receipt(session, event):
    """El workflow devuelve el acuse del transporte, no una estimación del modelo."""
    with session.lock:
        c = session.comms
        aid = c._wire_to_action.get(event.get('action_id'))
        if not aid or c.calls.get(aid, {}).get('workflow') != 'difusion' or event.get('recovered'):
            raise HTTPException(403, 'Acuse sin solicitud de difusión válida')
        for key in ('delivered', 'failed'):
            if type(event.get(key)) is not int or event[key] < 0:
                raise HTTPException(422, 'Los contadores deben ser enteros no negativos')
        if event.get('mode') == 'test':
            return dict(ok=True, test=True)
        previous = c.text_receipts.get(aid)
        if previous:
            if previous.get('pending') or any(event[k] != previous[k] for k in ('delivered', 'failed')):
                raise HTTPException(409, 'Acuse incompatible con el transporte')
            return dict(ok=True, duplicate=True)
        if event.get('error') != 'approval_required' or event['delivered'] != 0:
            raise HTTPException(409, 'Falta el resultado verificado del transporte')
        c.text_receipts[aid] = dict(event)
        c._inflight.pop(aid, None)
        c._closed.add(aid)
        c.calls[aid].update(stage='error: falta aprobación', result='failed', delivered=0, failed=event['failed'])
        c.workflow_status.record('difusion', 'error', error='approval_required')
        c.revision += 1
        session._rebuild()
        return dict(ok=True)
