"""Identidades y coordinación de operadores, siempre bajo el cerrojo de la escena."""
from collections import Counter
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from http.cookies import CookieError, SimpleCookie

from fastapi import HTTPException, Request
from motor.contracts import ALWAYS_APPROVE
from .privacy import scrub

LOCAL_SECRET = secrets.token_hex(32)
LOCAL_COOKIE = 'mando_local_operator'
ROLES = ('coordinación', 'sanitario', 'seguridad', 'accesos', 'técnico')


def configured():
    """No se devuelven estos registros al navegador: contienen las credenciales."""
    rows = []
    legacy = os.environ.get('MANDO_OPERATOR_TOKEN', '')
    if legacy:
        rows.append(dict(id='operador-1', name='operador-1', role='coordinación', token=legacy))
    raw = os.environ.get('MANDO_OPERATORS', '').strip()
    for item in re.split(r'[,;\n]', raw):
        if not item.strip():
            continue
        parts = item.strip().split(':', 2)
        if len(parts) != 3 or any(not p.strip() for p in parts):
            raise ValueError('MANDO_OPERATORS debe contener nombre:papel:token')
        name, role, token = (p.strip() for p in parts)
        if len(name) > 60 or len(role) > 40 or any(r['token'] == token for r in rows):
            raise ValueError('Nombre/papel demasiado largo o token duplicado')
        oid = 'op-' + hashlib.sha256((name + ':' + role).encode()).hexdigest()[:16]
        if any(r['id'] == oid for r in rows):
            raise ValueError('Operador duplicado')
        rows.append(dict(id=oid, name=name, role=role, token=token))
    return rows


def public_identity(row):
    return dict(id=row['id'], name=scrub(row['name']), role=scrub(row['role']))


def token_identity(token):
    return next((r for r in configured() if hmac.compare_digest(token.encode(), r['token'].encode())), None)


def credential_identity(scope):
    from .security import COOKIE_NAME, COOKIE_TTL, _signature
    request = Request(scope)
    header = request.headers.get('x-mando-operator')
    if header is not None:
        return token_identity(header)
    try:
        cookie = SimpleCookie(request.headers.get('cookie', '')).get(COOKIE_NAME)
        if cookie:
            issued, signature = cookie.value.split('.', 1)
            if 0 <= time.time() - int(issued) < COOKIE_TTL:
                return next((r for r in configured() if hmac.compare_digest(signature, _signature(issued, r['token']))), None)
    except (CookieError, ValueError, TypeError):
        pass
    return None


def local_mode(scope):
    return (not os.environ.get('MANDO_PUBLIC_URL', '').strip() and not configured()
            and (scope.get('client') or ('',))[0] in ('127.0.0.1', '::1', 'localhost', 'testclient'))


def local_cookie(name, role):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or role not in ROLES:
        raise HTTPException(422, 'Nombre y papel válidos requeridos')
    import base64
    row = dict(id='local-' + secrets.token_hex(12), name=name.strip(), role=role, issued=int(time.time()))
    payload = base64.urlsafe_b64encode(json.dumps(row, ensure_ascii=False).encode()).decode().rstrip('=')
    sig = hmac.new(LOCAL_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + '.' + sig


def identity(request: Request) -> dict[str, str]:
    from .security import require_operator
    require_operator(request)
    row = credential_identity(request.scope)
    if row:
        return public_identity(row)
    if local_mode(request.scope):
        import base64
        try:
            payload, sig = request.cookies.get(LOCAL_COOKIE, '').split('.', 1)
            expected = hmac.new(LOCAL_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if hmac.compare_digest(sig, expected):
                row = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
                if 0 <= time.time() - row['issued'] < 28800:
                    return public_identity(row)
        except (ValueError, KeyError, TypeError):
            pass
    return dict(id='operador-1', name='operador-1', role='coordinación')


def label(who):
    return who["name"] if who["id"] == "operador-1" else f"{who['name']} ({who['role']})"


def suggested_role(incident):
    if str(incident.get('type', '')).startswith('gate'):
        return 'accesos'
    return {'medical':'sanitario', 'aggression':'seguridad', 'crowd':'seguridad', 'infra':'técnico'}.get(str(incident.get('family')), 'coordinación')


class Operators:
    def __init__(self, session):
        self.s = session
        self.present = {}
        self.claims = {}
        self.notes = {}
        self.decisions = {}
        self.votes = {}
        self.audit = []
        self.manual = {}

    def event(self, who, verb, ref=None, **data):
        item = dict(seq=len(self.audit) + 1, operator=dict(who), verb=verb, ref=ref,
                    t=self.s.world.t, at=time.time(), **data)
        self.audit.append(item)
        self.s.log('operator', f'{label(who)}: {verb}', ref, operator=who, **data)
        return item

    def conflict(self, record):
        age = max(0, int(time.time() - record['at']))
        raise HTTPException(409, f"ya lo decidió {label(record['operator'])} hace {age} s")

    def available(self, key):
        if key in self.decisions:
            self.conflict(self.decisions[key])

    def vote(self, key, who, kind, ok):
        required = 2 if os.environ.get('MANDO_TWO_PERSON') == '1' and kind in ALWAYS_APPROVE and ok else 1
        votes = self.votes.setdefault(key, {})
        if ok and who['id'] in votes:
            self.conflict(votes[who['id']])
        if ok:
            seen = self.s._awaiting_seen.get(key)
            votes[who['id']] = self.event(who, 'aprueba', key,
                                          real_s=round(time.monotonic()-seen, 3) if seen is not None else None)
        return len(votes), required

    def decide(self, aid, ok, note, who):
        with self.s.lock:
            self.available(aid)
            a = getattr(self.s.agent, 'actions', {}).get(aid)
            if a is None or str(a.status) != 'awaiting_approval':
                raise HTTPException(409, 'Esa acción ya no está esperando aprobación')
            if ok and aid in self.manual:
                raise HTTPException(409, 'Hay una corrección esperando firma; revisa esa orden concreta')
            if ok and str(a.kind) == 'evacuate' and a.params.get('prepared') and not note.strip().upper().startswith('EVACUAR'):
                raise HTTPException(422, 'La evacuación preparada exige una nota que empiece por EVACUAR')
            count, required = self.vote(aid, who, a.kind, ok)
            if ok and count < required:
                self.s._rebuild()
                return dict(ok=True, pending=True, votes=count, required=required)
            if not self.s.approve(aid, ok, note, by=label(who)):
                self.votes.get(aid, {}).pop(who['id'], None)
                raise HTTPException(409, 'Esa acción ya no está esperando aprobación')
            record = self.event(who, 'aprobación completada' if ok else 'veta', aid, note=scrub(note),
                                real_s=self.s.decision_latency[-1].get('real_s') if self.s.decision_latency else None)
            self.decisions[aid] = record
            actors = [v['operator'] for v in self.votes.get(aid, {}).values()] if ok else [who]
            self.s.approvals[aid].update(operators=actors, at=record['at'])
            if self.s.decision_latency:
                self.s.decision_latency[-1].update(operator=who, operators=actors, at=record['at'])
            self.s._rebuild()
            return dict(ok=True, pending=False, votes=count if ok else 0, required=required)

    def heartbeat(self, who, incident=None):
        with self.s.lock:
            if incident is not None and incident not in getattr(self.s.agent, 'incidents', {}):
                raise HTTPException(404, 'Incidente desconocido')
            self.present[who['id']] = dict(operator=who, incident=incident, seen=time.monotonic())
            self.s._rebuild()
            return self.view()

    def claim(self, iid, who, take):
        with self.s.lock:
            self.check_incident(iid)
            old = self.claims.get(iid)
            if not take and old and old['id'] != who['id']:
                raise HTTPException(409, f'Lo lleva {label(old)}; puede soltarlo esa persona')
            if take:
                self.claims[iid] = dict(who)
            else:
                self.claims.pop(iid, None)
            self.event(who, 'lo llevo yo' if take else 'suelta el incidente', iid)
            self.s._rebuild()
            return dict(ok=True, previous=old, owner=self.claims.get(iid))

    def check_incident(self, iid):
        if iid not in getattr(self.s.agent, 'incidents', {}):
            raise HTTPException(404, 'Incidente desconocido')

    def note(self, iid, who, text):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 400:
            raise HTTPException(422, 'Nota de 1 a 400 caracteres requerida')
        with self.s.lock:
            self.check_incident(iid)
            safe = scrub(text.strip())
            row = self.event(who, 'nota: ' + safe, iid, mentions=re.findall(r'@([\wáéíóúñ]+)', safe))
            self.notes.setdefault(iid, []).append(row)
            self.s._rebuild()
            return dict(ok=True)

    def reserve_call(self, aid, who):
        with self.s.lock:
            key = 'call:' + aid
            self.available(key)
            if aid not in self.s.comms.calls:
                raise HTTPException(404, 'Llamada desconocida')
            self.decisions[key] = self.event(who, 'toma la llamada', aid)
            self.s._rebuild()
            return key

    def correction(self, d, note, who, target=None):
        from .whatif import candidate
        with self.s.lock:
            a = candidate(d, set(self.s.world.L.ids), self.s.world.t)
            pending = [x['id'] for x in self.s._snapshot.get('actions', []) if x['kind']==str(a.kind)
                       and x.get('zone')==a.zone and x['status']=='awaiting_approval']
            key = target or (pending[0] if pending else 'manual:' + hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest())
            self.available(key)
            if target and target not in pending and not (target.startswith('manual:') and target in self.manual):
                raise HTTPException(409, 'La decisión corregida ya no está pendiente')
            if key in self.votes and self.votes[key] and key not in self.manual:
                raise HTTPException(409, 'La orden original tiene una firma; veta antes de proponer una corrección')
            previous = self.manual.get(key)
            if previous and previous != d:
                raise HTTPException(409, 'Ya hay otra corrección esperando segunda firma')
            count, required = self.vote(key, who, a.kind, True)
            self.manual[key] = dict(d)
            if count < required:
                self.s._rebuild()
                return dict(ok=True, pending=True, votes=count, required=required)
            rec = self.s.operator_order(d, by=label(who), note=note)
            event = self.event(who, 'corrige', rec['id'], action=d)
            for aid in set(pending + [key]):
                self.decisions[aid] = event
            rec['operators'] = [v['operator'] for v in self.votes[key].values()]
            self.s._rebuild()
            return dict(ok=True, order=rec)

    def view(self):
        now = time.monotonic()
        return dict(presence=[dict(operator=r['operator'], incident=r['incident']) for r in self.present.values() if now-r['seen']<35],
                    claims=dict(self.claims), notes=dict(self.notes), events=self.audit[-30:],
                    two_person=os.environ.get('MANDO_TWO_PERSON')=='1',
                    votes={k:len(v) for k,v in self.votes.items()},
                    manual_pending=[dict(key=k, action=d, votes=len(self.votes.get(k, {})), required=2)
                                    for k,d in self.manual.items() if k not in self.decisions])

    def enrich(self, state):
        state['operators'] = self.view()
        reports = {r.id:r for r in self.s.world.reports}
        for inc in state.get('incidents', []):
            inc['owner'] = self.claims.get(inc['id'])
            inc['suggested_role'] = suggested_role(inc)
            groups = Counter()
            seen = set()
            for rid in inc.get('reports', []):
                r = reports.get(rid)
                if r is None:
                    continue
                meta = self.s._report_meta.get(rid, {})
                root = meta.get('update_of') or rid
                staff = meta.get('staff_unit')
                key = ('staff', staff) if staff else ('report', root)
                if key in seen:
                    continue
                seen.add(key)
                category = meta.get('source_label') or ('sensor' if str(r.channel)=='sensor' else 'operador' if str(r.channel)=='operator' else 'público')
                groups[category] += 1
            inc['sources'] = dict(groups)
            inc['sources_text'] = f"{sum(groups.values())} fuentes: " + ', '.join(f'{k} ×{v}' for k,v in groups.items())
        for a in state.get('approvals', []):
            a['votes'] = len(self.votes.get(a['id'], {}))
            a['required'] = 2 if os.environ.get('MANDO_TWO_PERSON')=='1' and a['kind'] in ALWAYS_APPROVE else 1
        return state

    def report(self):
        per = {}
        for row in self.audit:
            if row['verb'] in ('aprueba', 'veta') and row.get('real_s') is not None:
                who = row['operator']
                item = per.setdefault(who['id'], dict(operator=who, values=[]))
                item['values'].append(row['real_s'])
        return dict(operator_audit=self.audit, operator_latency=[dict(operator=x['operator'], n=len(x['values']),
            mean_s=round(sum(x['values'])/len(x['values']), 3), max_s=max(x['values'])) for x in per.values()])
