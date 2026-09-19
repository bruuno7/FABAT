"""Partes de campo firmados. RADIO/Report y Observation conservan el contrato común."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

from fastapi import HTTPException
from .privacy import scrub
from motor.contracts import Action, ActionKind, ActionStatus, Channel, ResourceStatus

STATUS = {
    'en_route':'En camino', 'on_scene':'En el sitio', 'stabilized':'Paciente estabilizado',
    'transport':'Traslado a puesto médico', 'needs_support':'Necesito apoyo', 'route_blocked':'Ruta bloqueada',
    'exhausted':'Recurso agotado', 'free':'Libre', 'note':'Parte de texto', 'new_notice':'Veo otra cosa',
    'false_alarm':'No ocurre / desmentido en el sitio',
}
ROLES = ('ambulancia', 'sanitario', 'seguridad', 'jefe de zona', 'voluntario', 'técnico', 'barras', 'accesos')
LABELS = {'medical':'equipo médico', 'ambulance':'ambulancia', 'security':'seguridad',
          'tech':'técnico', 'logistics':'logística', 'volunteer':'voluntariado'}


class FieldStaff:
    def __init__(self, session):
        self.s = session
        self.secret = os.environ.get('MANDO_STAFF_SECRET') or secrets.token_hex(32)
        self.events = {}
        self.operational_reports = set()
        self.latest = {}
        self.results = []

    def issue(self, unit, role):
        if unit not in self.s.world.resources or role not in ROLES:
            raise HTTPException(422, 'Unidad o cargo desconocido')
        data = dict(unit_id=unit, role=role, scene=self.s.session_id, issued=int(time.time()))
        payload = base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).decode().rstrip('=')
        sig = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return payload + '.' + sig

    def verify(self, token, unit=None):
        try:
            if not isinstance(token, str) or len(token) > 1024:
                raise ValueError()
            payload, sig = token.split('.', 1)
            expected = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                raise ValueError()
            data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
            if (data['scene'] != self.s.session_id or self.s.world.done() or self.s._stop.is_set()
                    or data['unit_id'] not in self.s.world.resources or (unit and data['unit_id'] != unit)):
                raise ValueError()
            return data
        except (ValueError, KeyError, TypeError):
            raise HTTPException(403, 'Enlace de unidad inválido o caducado; pide uno al centro')

    def links(self, unit, role, base):
        token = self.issue(unit, role)
        return dict(ok=True, unit_id=unit, token=token, url=base.rstrip('/') + '/personal#' + urlencode({'token':token}),
                    expires='Al finalizar o reiniciar esta escena')

    def orders(self, who):
        unit = who['unit_id']
        with self.s.lock:
            res = self.s.world.observe().resources[unit].to_dict()
            res.pop('contact', None)
            actions = getattr(self.s.agent, 'actions', {})
            rows = []
            for a in actions.values():
                if a.resource != unit or str(a.status) not in ('proposed', 'executing', 'done') or a.kind != ActionKind.DISPATCH:
                    continue
                inc = getattr(self.s.agent, 'incidents', {}).get(a.incident)
                if inc and str(inc.status) in ('resolved','false_alarm','failed'):
                    continue
                if str(a.status)=='done' and (not inc or unit not in inc.assigned):
                    continue
                rows.append(dict(id=a.id, resource=unit, incident=a.incident, zone=a.zone, text=a.why,
                                 result=(self.s.comms.calls.get(a.id) or {}).get('result'), status=str(a.status)))
            return scrub(dict(unit=res, role=who['role'], orders=rows, latest=self.latest.get(unit),
                        zones=[dict(id=z['id'], name=z['name']) for z in self.s.festival['zones']]))

    def validate(self, data):
        allowed = {'type','schema','event_id','hr_run_id','unit_token','unit_id','status','zone','needs_support','free_text', 'incident_id','channel'}
        if not isinstance(data, dict) or set(data)-allowed:
            raise HTTPException(422, 'Campos del parte desconocidos')
        for key, maximum in (('unit_id',40),('status',30),('zone',60),('free_text',400),('event_id',120),
                             ('incident_id',60),('unit_token',1024),('hr_run_id',120),('channel',10)):
            if key in data and (not isinstance(data[key], str) or len(data[key]) > maximum):
                raise HTTPException(422, f'{key} debe ser texto válido')
        if data.get('type') not in (None, 'staff_status') or data.get('schema') not in (None, 'mando.hr.v1'):
            raise HTTPException(422, 'Tipo o esquema de parte desconocido')
        if data.get('unit_id') not in self.s.world.resources or data.get('status') not in STATUS:
            raise HTTPException(422, 'Unidad o estado desconocido')
        if 'needs_support' in data and type(data['needs_support']) is not bool:
            raise HTTPException(422, 'needs_support debe ser booleano JSON')
        if data.get('channel', 'radio') not in ('radio','voice'):
            raise HTTPException(422, 'Canal del personal: radio o voice')
        if data.get('zone') and data['zone'] not in self.s.world.L.idx:
            raise HTTPException(422, 'Zona desconocida')
        if data['status']=='route_blocked' and not data.get('zone'):
            raise HTTPException(422, 'Indica la zona de la ruta bloqueada')
        if data['status'] in ('new_notice','note') and not data.get('free_text', '').strip():
            raise HTTPException(422, 'Falta el texto del parte')
        return data

    def status(self, data, token):
        who = self.verify(token, data.get('unit_id'))
        d = self.validate(data)
        with self.s.lock:
            unit, status = who['unit_id'], d['status']
            eid = d.get('event_id')
            key = (unit, eid)
            if eid and key in self.events:
                return dict(self.events[key], duplicate=True)
            resource = self.s.world.resources[unit]
            own = self.orders(who)['orders']
            iid = d.get('incident_id') or next((a['incident'] for a in reversed(own)), None)
            inc = getattr(self.s.agent, 'incidents', {}).get(iid)
            if d.get('incident_id') and not any(a['incident']==iid for a in own):
                raise HTTPException(403, 'Ese incidente no está asignado a tu unidad')
            if status == 'en_route' and resource.status == ResourceStatus.OFFLINE:
                raise HTTPException(409, 'La unidad está fuera de servicio; comunica libre antes de salir')
            zone = d.get('zone') or (inc.zone if inc else resource.zone)
            text = (STATUS[status] + (': ' + d['free_text'].strip() if d.get('free_text') else ''))[:400]
            if status == 'new_notice':
                out = self.s.report(d.get('channel','radio'), d['free_text'], zone, source=unit, via='personal')
            else:
                # Parte operativo: conserva el Report; la nueva evidencia entra por Observation y respuesta sitrep.
                out = self.s.report(d.get('channel','radio'), text, zone, source=unit, via='personal',
                                    update_of=inc.reports[0] if inc and inc.reports else None)
                self.operational_reports.add(out['report_id'])
                if inc and out['report_id'] not in inc.reports:
                    inc.reports.append(out['report_id'])
            rid = out['report_id']
            self.s._report_meta[rid].update(staff_unit=unit, source_label=LABELS.get(str(resource.kind), who['role']), staff_status=status)
            if status in ('route_blocked','exhausted'):
                self.s.world.inject({'kind':'resource_offline','resource':unit, 'reason':text})
                if status=='route_blocked':
                    self.s.world.inject({'kind':'zone_flag','zone':zone,'flag':'blocked','value':True})
            elif status == 'free':
                self.s.world.apply(Action('staff-free-' + rid, ActionKind.RECALL, self.s.world.t, resource=unit))
                self.s.world.inject({'kind':'resource_online','resource':unit})
            elif status in ('on_scene','stabilized','transport','needs_support'):
                # El parte real sustituye el desplazamiento simulado, no deja un temporizador que lo sobrescriba.
                self.s.world.travel.pop(unit, None)
                self.s.world.timed.pop(unit, None)
                resource.status, resource.eta, resource.zone = ResourceStatus.BUSY, 0, zone
                if inc:
                    for order in own:
                        if order['incident'] == inc.id:
                            action = self.s.agent.actions[order['id']]
                            if str(action.status) != 'done':
                                import copy
                                result = copy.deepcopy(action)
                                result.status = ActionStatus.DONE
                                self.results.append(result)
                            self.finish_comms(action.id, 'accept', text)
            elif status == 'en_route':
                resource.status = ResourceStatus.EN_ROUTE
            if inc and status in ('on_scene','stabilized','transport','needs_support','false_alarm','note'):
                # Usa exactamente el tratamiento existente «confirmado por quien está en el sitio».
                aid = 'staff-sitrep-' + rid
                a = Action(aid, ActionKind.ASK, self.s.world.t, incident=inc.id, resource=unit,
                           channel=Channel.RADIO, status=ActionStatus.DONE, params={'purpose':'sitrep','to':unit})
                self.s.agent.actions[aid] = a
                facts = {'exists':status!='false_alarm', 'zone':zone}
                if d.get('needs_support') or status=='needs_support':
                    facts['needs'] = dict(inc.needs)
                    kind = str(resource.kind)
                    facts['needs'][kind] = facts['needs'].get(kind, 0) + 1
                with self.s.comms._lock:
                    self.s.comms._inbox.append(dict(action_id=aid, result='answer', text=text, data=facts))
            self.latest[unit] = dict(status=status, text=text, t=self.s.world.t)
            self.s.log('staff_status', f'{unit} · {who["role"]}: {text}. Fuente autenticada; actualiza recurso y supuestos.',
                       rid, unit_id=unit, incident=iid, status=status, zone=zone)
            out = dict(ok=True, report_id=rid, status=status, duplicate=False, say_text='Parte recibido por el centro de control.')
            if eid:
                self.events[key] = out
            self.s._rebuild()
            self.s._wake.set()
            return out

    def answer(self, who, aid, result, reason):
        if result not in ('accept','reject') or not isinstance(reason, str) or len(reason)>400:
            raise HTTPException(422, 'Respuesta inválida')
        if result=='reject' and not reason.strip():
            raise HTTPException(422, 'Indica el motivo del rechazo')
        with self.s.lock:
            a = getattr(self.s.agent, 'actions', {}).get(aid)
            if not a or a.resource != who['unit_id'] or aid not in {x['id'] for x in self.orders(who)['orders']}:
                raise HTTPException(403, 'Esa orden no pertenece a tu unidad o ya no está vigente')
            key = ('order', aid)
            if key in self.events:
                raise HTTPException(409, 'Esta orden ya tiene respuesta')
            if result=='reject':
                a.status = ActionStatus.REJECTED
                a.params['error'] = 'rejected'
                self.s.world.apply(Action('staff-recall-' + aid, ActionKind.RECALL, self.s.world.t, resource=a.resource))
            self.finish_comms(aid, result, reason)
            self.events[key] = dict(ok=True)
            self.s.log('staff_status', f'{who["unit_id"]}: {"ACEPTA" if result=="accept" else "RECHAZA"} {aid}: {reason}', aid)
            self.s._rebuild()
            return dict(ok=True, say_text='Respuesta recibida.')

    def finish_comms(self, aid, result, text):
        with self.s.comms._lock:
            self.s.sim._pending = [p for p in self.s.sim._pending if p.get('action_id') != aid]
            self.s.comms._inflight.pop(aid, None)
            self.s.comms._closed.add(aid)
            self.s.comms._early.discard(aid)
            self.s.comms._inbox.append(dict(action_id=aid, result=result, text=text))
            call = self.s.comms.calls.get(aid)
            if call:
                call.update(result=result, detail=text, t_end=self.s.world.t)

    def observation(self, obs):
        obs.action_results.extend(self.results)
        self.results = []
        obs.new_reports = [r for r in obs.new_reports if r.id not in self.operational_reports]
        return obs


def external_notice(session, data):
    allowed = {'type','schema','event_id','source','text','zone','hr_run_id'}
    if set(data)-allowed or any(not isinstance(v, str) or len(v)>400 for v in data.values()):
        raise HTTPException(422, 'Aviso externo inválido')
    if not data.get('source') or not data.get('text') or (data.get('zone') and data['zone'] not in session.world.L.idx):
        raise HTTPException(422, 'Origen, texto y zona válidos requeridos')
    key = ('external', data.get('event_id'))
    with session.lock:
        if data.get('event_id') and key in session.staff.events:
            return dict(session.staff.events[key], duplicate=True)
        out = session.report('operator', data['text'], data.get('zone'), source=data['source'], via='external')
        session._report_meta[out['report_id']]['source_label'] = 'servicios externos'
        if data.get('event_id'):
            session.staff.events[key] = out
        session._rebuild()
        return out
