"""Directorio privado rol↔chat_id y cerrojo del despacho por Telegram.

Twin no está provisionado en este workspace: HappyRobot no puede guardar el mapa.
Este módulo es el sustituto durable. `chat_id` nunca sale por `/api/state`.

El puente POST `/rol` y `/baja` aquí. `fa-despacho-tg` y `fa-respuesta-tg` consultan
y mutan asignaciones (primer `acc` gana; el resto queda `covered`; `dec` reasigna).
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

SEATS = ('medico', 'staff_entradas', 'organizador', 'bomberos', 'policia')
SEAT_ES = {
    'medico': 'médico',
    'staff_entradas': 'staff entradas',
    'organizador': 'organizador',
    'bomberos': 'bomberos',
    'policia': 'policía',
}
# Oficio del bot → vocabulario del espejo (Sala). Los 5 puestos viven también en ROLES del espejo.
SEAT_TO_ESPEJO = {
    'medico': 'medico',
    'staff_entradas': 'staff_entradas',
    'organizador': 'organizador',
    'bomberos': 'bomberos',
    'policia': 'policia',
}
TIPO_ESPEJO = {
    'medica': 'medica',
    'aglomeracion': 'aglomeracion',
    'seguridad': 'seguridad',
    'agresion': 'seguridad',
    'incendio': 'incendio',
    'clima': 'clima',
    'infraestructura': 'infraestructura',
    'infra': 'infraestructura',
    'falta_recursos': 'infraestructura',
    'menor': 'menor',
    'otro': 'otro',
}
ROLE_PREFERENCE = {
    'medica': ('medico',),
    'incendio': ('bomberos', 'policia'),
    'seguridad': ('policia', 'bomberos'),
    'agresion': ('policia', 'bomberos'),
    'aglomeracion': ('staff_entradas', 'policia', 'organizador'),
    'infraestructura': ('staff_entradas', 'organizador'),
    'infra': ('staff_entradas', 'organizador'),
    'falta_recursos': ('staff_entradas', 'organizador'),
    'clima': ('organizador', 'staff_entradas'),
    'menor': ('staff_entradas', 'medico', 'organizador'),
    'otro': ('organizador', 'staff_entradas'),
}
GRAVEDAD_DE_SEVERIDAD = {
    5: 'vital', 4: 'emergencia', 3: 'urgente', 2: 'leve', 1: 'sin_clasificar',
}
BUSY = ('pending', 'accepted')
DEFAULT_PATH = Path(__file__).resolve().parent / 'data' / 'tg_roster.db'


def configured_path(value: str | Path | None = None) -> Path | None:
    raw = str(value) if value is not None else os.environ.get('MANDO_TG_ROSTER', '')
    raw = raw.strip()
    if raw.lower() == 'off':
        return None
    if raw:
        return Path(raw).expanduser()
    if os.environ.get('MANDO_DB', '').strip().lower() == 'off':
        return None
    return DEFAULT_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _texto(data: dict, key: str, maximo: int, *, obligatorio: bool = False) -> str:
    v = data.get(key)
    if v is None and not obligatorio:
        return ''
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        v = str(int(v) if float(v).is_integer() else v)
    if not isinstance(v, str) or len(v) > maximo:
        raise HTTPException(422, f'{key} debe ser texto de {maximo} caracteres como mucho')
    v = v.strip()
    if obligatorio and not v:
        raise HTTPException(422, f'Falta {key}')
    return v


def _tipo_espejo(raw: str) -> str:
    key = (raw or 'otro').strip().lower()
    return TIPO_ESPEJO.get(key, 'otro' if key not in TIPO_ESPEJO.values() else key)


def _gravedad(data: dict) -> str:
    raw = _texto(data, 'gravedad', 20).lower()
    if raw in GRAVEDAD_DE_SEVERIDAD.values():
        return raw
    sev = data.get('severity', data.get('prioridad'))
    try:
        n = int(sev)
    except (TypeError, ValueError):
        n = 3
    return GRAVEDAD_DE_SEVERIDAD.get(max(1, min(5, n)), 'urgente')


def _callback(kind: str, assignment_id: str, extra: str = '') -> str:
    parts = [kind, assignment_id]
    if extra:
        parts.append(extra)
    data = '|'.join(parts)
    return data[:64]


class TelegramRoster:
    """Un puesto = un chat. Persistente en SQLite (o memoria si MANDO_DB=off)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = configured_path(path)
        self._lock = threading.Lock()
        self._local = threading.local()
        self._memory = sqlite3.connect(':memory:', check_same_thread=False) if self.path is None else None
        if self._memory is not None:
            self._memory.row_factory = sqlite3.Row
            self._migrate(self._memory)

    def close(self) -> None:
        db = getattr(self._local, 'db', None)
        if db is not None:
            db.close()
            self._local.db = None
        if self._memory is not None:
            self._memory.close()
            self._memory = None

    def clear_assignments(self) -> None:
        """Las partidas se reinician; los puestos reclamados se quedan."""
        with self._lock:
            db = self._db()
            db.execute('DELETE FROM tg_assignments')
            db.execute('DELETE FROM tg_incidents')
            db.commit()

    def _db(self) -> sqlite3.Connection:
        if self._memory is not None:
            return self._memory
        db = getattr(self._local, 'db', None)
        if db is None:
            assert self.path is not None
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, check_same_thread=False)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA journal_mode = WAL')
            db.execute('PRAGMA foreign_keys = ON')
            self._migrate(db)
            self._local.db = db
        return db

    @staticmethod
    def _migrate(db: sqlite3.Connection) -> None:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS tg_seats (
                role TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL UNIQUE,
                alias TEXT NOT NULL DEFAULT '',
                claimed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tg_incidents (
                id TEXT PRIMARY KEY,
                texto TEXT NOT NULL,
                tipo TEXT NOT NULL,
                zona TEXT NOT NULL DEFAULT '',
                gravedad TEXT NOT NULL,
                prioridad INTEGER,
                alias_informante TEXT NOT NULL DEFAULT '',
                correlation_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tg_assignments (
                id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                rol TEXT NOT NULL,
                alias TEXT NOT NULL DEFAULT '',
                chat_id TEXT NOT NULL,
                estado TEXT NOT NULL,
                intento INTEGER NOT NULL DEFAULT 1,
                eta_min INTEGER,
                from_zone TEXT,
                motivo TEXT NOT NULL DEFAULT '',
                correlation_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tg_asg_incident ON tg_assignments(incident_id, rol, estado);
        """)
        db.commit()

    def seats_view(self) -> dict[str, Any]:
        with self._lock:
            return self._seats_unlocked()

    def _seats_unlocked(self) -> dict[str, Any]:
        db = self._db()
        rows = {row['role']: dict(row) for row in db.execute('SELECT * FROM tg_seats')}
        busy = {row['chat_id'] for row in db.execute(
            "SELECT DISTINCT chat_id FROM tg_assignments WHERE estado IN ('pending','accepted')")}
        seats = []
        for role in SEATS:
            row = rows.get(role)
            item = {'rol': role, 'label': SEAT_ES[role], 'claimed': row is not None}
            if row:
                item.update(chat_id=row['chat_id'], alias=row['alias'],
                            claimed_at=row['claimed_at'], busy=row['chat_id'] in busy)
            else:
                item.update(chat_id=None, alias='', claimed_at=None, busy=False)
            seats.append(item)
        claimed = [s for s in seats if s['claimed']]
        return {
            'seats': seats,
            'total': len(SEATS),
            'claimed': len(claimed),
            'disponibles': sum(1 for s in claimed if not s['busy']),
        }

    def claim(self, data: dict[str, Any], mirror: Any | None = None) -> dict[str, Any]:
        role = _texto(data, 'role', 30, obligatorio=True).lower()
        if role not in SEATS:
            raise HTTPException(422, 'puesto desconocido: ' + ', '.join(SEATS))
        chat_id = _texto(data, 'chat_id', 40, obligatorio=True)
        alias = _texto(data, 'alias', 40) or 'staff'
        with self._lock:
            db = self._db()
            holder = db.execute('SELECT * FROM tg_seats WHERE role=?', (role,)).fetchone()
            if holder and holder['chat_id'] != chat_id:
                return {'ok': False, 'reason': 'taken', 'holder': {
                    'rol': role, 'alias': holder['alias'], 'chat_id': holder['chat_id']}}
            mine = db.execute('SELECT * FROM tg_seats WHERE chat_id=?', (chat_id,)).fetchone()
            previous = dict(mine) if mine and mine['role'] != role else None
            if mine and mine['role'] != role:
                db.execute('DELETE FROM tg_seats WHERE chat_id=?', (chat_id,))
            db.execute("""INSERT INTO tg_seats(role, chat_id, alias, claimed_at)
                          VALUES(?,?,?,?) ON CONFLICT(role) DO UPDATE SET
                          chat_id=excluded.chat_id, alias=excluded.alias, claimed_at=excluded.claimed_at""",
                       (role, chat_id, alias, _now()))
            db.commit()
            view = self._seats_unlocked()
        out = {'ok': True, 'role': role, 'alias': alias, 'previous': previous, **view}
        self._mirror_staff(mirror, out)
        return out

    def release(self, data: dict[str, Any], mirror: Any | None = None) -> dict[str, Any]:
        chat_id = _texto(data, 'chat_id', 40, obligatorio=True)
        with self._lock:
            db = self._db()
            previous = db.execute('SELECT * FROM tg_seats WHERE chat_id=?', (chat_id,)).fetchone()
            if previous:
                db.execute('DELETE FROM tg_seats WHERE chat_id=?', (chat_id,))
                db.commit()
            view = self._seats_unlocked()
        out = {'ok': True, 'previous': dict(previous) if previous else None, **view}
        self._mirror_staff(mirror, out)
        return out

    def dispatch(self, data: dict[str, Any], mirror: Any | None = None) -> dict[str, Any]:
        texto = _texto(data, 'texto', 400) or _texto(data, 'text', 400) or _texto(data, 'summary', 400)
        if not texto:
            raise HTTPException(422, 'Falta texto')
        tipo_in = _texto(data, 'tipo', 40) or _texto(data, 'incident_type', 40) or 'otro'
        tipo = _tipo_espejo(tipo_in)
        zona = _texto(data, 'zona', 60) or _texto(data, 'sector', 60) or _texto(data, 'location', 60)
        gravedad = _gravedad(data)
        prioridad = data.get('prioridad', data.get('severity'))
        try:
            prioridad_n = int(prioridad) if prioridad is not None else 5
        except (TypeError, ValueError):
            prioridad_n = 5
        alias_inf = _texto(data, 'alias_informante', 40) or 'Asistente'
        correlation = _texto(data, 'correlation_id', 120)
        iid = _texto(data, 'incident_id', 60) or _texto(data, 'id', 60)
        if not iid:
            iid = ('tg-' + (correlation or uuid.uuid4().hex[:12]))[:60]
        rol_pedido = _texto(data, 'rol', 30).lower()
        with self._lock:
            db = self._db()
            existing = db.execute('SELECT * FROM tg_incidents WHERE id=?', (iid,)).fetchone()
            if existing is None:
                db.execute("""INSERT INTO tg_incidents(id, texto, tipo, zona, gravedad, prioridad,
                              alias_informante, correlation_id, created_at)
                              VALUES(?,?,?,?,?,?,?,?,?)""",
                           (iid, texto, tipo, zona, gravedad, prioridad_n, alias_inf, correlation, _now()))
            pick = self._next_seat(db, iid, tipo_in, rol_pedido or None)
            if pick is None:
                db.commit()
                view = self._seats_unlocked()
                out = {'ok': True, 'dispatched': False, 'reason': 'no_staff',
                       'incident_id': iid, 'outbound': None, **view}
            else:
                assignment = self._create_assignment(db, iid, pick, correlation)
                db.commit()
                view = self._seats_unlocked()
                out = {'ok': True, 'dispatched': True, 'incident_id': iid,
                       'assignment_id': assignment['id'], 'rol': assignment['rol'],
                       'alias': assignment['alias'], 'chat_id': assignment['chat_id'],
                       'intento': assignment['intento'],
                       'outbound': self._offer_message(assignment, texto, tipo, zona, gravedad),
                       **view}
        self._mirror_incident(mirror, iid, texto, tipo, zona, gravedad, prioridad_n, alias_inf,
                              new=existing is None)
        if out.get('dispatched'):
            self._mirror_assignment(mirror, out['incident_id'], out['rol'], 'pending',
                                    out['alias'], out['intento'])
        self._mirror_staff(mirror, out)
        return out

    def staff_response(self, data: dict[str, Any], mirror: Any | None = None) -> dict[str, Any]:
        kind = _texto(data, 'kind', 16, obligatorio=True).lower()
        callback = _texto(data, 'callback_data', 64)
        assignment_id = _texto(data, 'assignment_id', 80)
        extra = ''
        if callback:
            parts = callback.replace(':', '|').split('|')
            kind = (parts[0] or kind).lower()[:16]
            if len(parts) > 1 and not assignment_id:
                assignment_id = parts[1]
            if len(parts) > 2:
                extra = parts[2]
        if not assignment_id:
            raise HTTPException(422, 'Falta assignment_id')
        chat_id = _texto(data, 'chat_id', 40, obligatorio=True)
        alias = _texto(data, 'alias', 40)
        reporter = data.get('reporter') if isinstance(data.get('reporter'), dict) else {}
        if not alias:
            alias = str(reporter.get('display_name') or '')[:40]
        if kind == 'eta' and extra.isdigit():
            data = dict(data, eta_min=int(extra))
        if kind == 'loc' and extra:
            data = dict(data, from_zone=extra)

        with self._lock:
            db = self._db()
            fila = db.execute('SELECT * FROM tg_assignments WHERE id=?', (assignment_id,)).fetchone()
            if fila is None:
                raise HTTPException(404, f'No hay asignación {assignment_id}')
            fila = dict(fila)
            if fila['chat_id'] != chat_id:
                raise HTTPException(403, 'Ese botón no es de este chat')
            alias = alias or fila['alias']
            incident = dict(db.execute('SELECT * FROM tg_incidents WHERE id=?',
                                       (fila['incident_id'],)).fetchone())
            if kind == 'acc':
                out = self._accept(db, fila, alias)
            elif kind == 'dec':
                out = self._decline(db, fila, alias, incident)
            elif kind == 'eta':
                out = self._set_eta(db, fila, data)
            elif kind == 'loc':
                out = self._set_loc(db, fila, data)
            elif kind in ('apr', 'vet'):
                out = {'ok': True, 'estado': 'approval', 'kind': kind, 'incident_id': fila['incident_id'],
                       'assignment_id': assignment_id, 'outbound': None, 'next_outbound': None}
            else:
                raise HTTPException(422, f'kind desconocido: {kind}')
            db.commit()
            out.update(self._seats_unlocked())

        if kind in ('apr', 'vet') and mirror is not None:
            self._mirror_approval(mirror, fila['incident_id'], kind, alias or 'organizador')
        elif kind != 'apr' and kind != 'vet':
            self._mirror_assignment(mirror, out.get('incident_id', fila['incident_id']),
                                    out.get('rol', fila['rol']), out.get('estado', fila['estado']),
                                    alias, out.get('intento', fila['intento']),
                                    eta=out.get('eta_min'), from_zone=out.get('from_zone'),
                                    motivo=out.get('motivo', ''))
            if out.get('covered_alias'):
                self._mirror_assignment(mirror, out['incident_id'], out['rol'], 'covered',
                                        out['covered_alias'], out.get('intento', 1))
            if out.get('next'):
                nxt = out['next']
                self._mirror_assignment(mirror, nxt['incident_id'], nxt['rol'], 'pending',
                                        nxt['alias'], nxt['intento'])
        self._mirror_staff(mirror, out)
        return out

    def _next_seat(self, db: sqlite3.Connection, incident_id: str, tipo: str,
                   rol_pedido: str | None) -> dict[str, Any] | None:
        declined = {row['chat_id'] for row in db.execute(
            "SELECT chat_id FROM tg_assignments WHERE incident_id=? AND estado='declined'",
            (incident_id,))}
        covered_roles = {row['rol'] for row in db.execute(
            "SELECT rol FROM tg_assignments WHERE incident_id=? AND estado IN ('accepted','covered','pending')",
            (incident_id,))}
        order = (rol_pedido,) if rol_pedido in SEATS else ROLE_PREFERENCE.get(tipo, ROLE_PREFERENCE['otro'])
        seats = {row['role']: dict(row) for row in db.execute('SELECT * FROM tg_seats')}
        for role in order:
            if role in covered_roles:
                continue
            row = seats.get(role)
            if not row or row['chat_id'] in declined:
                continue
            return {'rol': role, 'chat_id': row['chat_id'], 'alias': row['alias']}
        return None

    def _create_assignment(self, db: sqlite3.Connection, incident_id: str, pick: dict[str, Any],
                           correlation: str) -> dict[str, Any]:
        prev = db.execute(
            'SELECT max(intento) AS n FROM tg_assignments WHERE incident_id=? AND rol=?',
            (incident_id, pick['rol'])).fetchone()
        intento = int(prev['n'] or 0) + 1
        aid = f"asg-{uuid.uuid4().hex[:10]}"
        now = _now()
        db.execute("""INSERT INTO tg_assignments(id, incident_id, rol, alias, chat_id, estado, intento,
                      correlation_id, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (aid, incident_id, pick['rol'], pick['alias'], pick['chat_id'], 'pending',
                    intento, correlation, now, now))
        return {'id': aid, 'incident_id': incident_id, 'rol': pick['rol'], 'alias': pick['alias'],
                'chat_id': pick['chat_id'], 'intento': intento, 'estado': 'pending'}

    def _accept(self, db: sqlite3.Connection, fila: dict[str, Any], alias: str) -> dict[str, Any]:
        winner = db.execute("""SELECT * FROM tg_assignments WHERE incident_id=? AND rol=?
                               AND estado='accepted' AND id<>?""",
                            (fila['incident_id'], fila['rol'], fila['id'])).fetchone()
        now = _now()
        if winner is not None:
            db.execute("UPDATE tg_assignments SET estado='covered', alias=?, updated_at=? WHERE id=?",
                       (alias, now, fila['id']))
            return {'ok': True, 'estado': 'covered', 'incident_id': fila['incident_id'],
                    'assignment_id': fila['id'], 'rol': fila['rol'], 'alias': alias,
                    'intento': fila['intento'], 'covered_alias': winner['alias'],
                    'outbound': {
                        'event': 'telegram_send', 'chat_id': fila['chat_id'],
                        'text': (f'Este aviso ya lo cubre {winner["alias"]} '
                                 '(simulación). Gracias.'),
                    }, 'next_outbound': None}
        db.execute("UPDATE tg_assignments SET estado='accepted', alias=?, updated_at=? WHERE id=?",
                   (alias, now, fila['id']))
        ask_eta = fila.get('eta_min') is None
        return {'ok': True, 'estado': 'accepted', 'incident_id': fila['incident_id'],
                'assignment_id': fila['id'], 'rol': fila['rol'], 'alias': alias,
                'intento': fila['intento'],
                'outbound': self._eta_loc_message(fila) if ask_eta else None,
                'next_outbound': None}

    def _decline(self, db: sqlite3.Connection, fila: dict[str, Any], alias: str,
                 incident: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        db.execute("""UPDATE tg_assignments SET estado='declined', alias=?, motivo=?, updated_at=?
                      WHERE id=?""", (alias, 'no puede acudir', now, fila['id']))
        pick = self._next_seat(db, fila['incident_id'], incident['tipo'], None)
        next_asg = self._create_assignment(db, fila['incident_id'], pick, fila.get('correlation_id') or '') if pick else None
        outbound = {
            'event': 'telegram_send', 'chat_id': fila['chat_id'],
            'text': 'Anotado. Busco a otro (simulación).',
        }
        next_outbound = None
        nxt = None
        if next_asg:
            next_outbound = self._offer_message(next_asg, incident['texto'], incident['tipo'],
                                                incident['zona'], incident['gravedad'])
            nxt = {'assignment_id': next_asg['id'], 'rol': next_asg['rol'], 'alias': next_asg['alias'],
                   'chat_id': next_asg['chat_id'], 'intento': next_asg['intento'],
                   'incident_id': next_asg['incident_id']}
        return {'ok': True, 'estado': 'declined', 'incident_id': fila['incident_id'],
                'assignment_id': fila['id'], 'rol': fila['rol'], 'alias': alias,
                'intento': fila['intento'], 'motivo': 'no puede acudir',
                'outbound': outbound, 'next_outbound': next_outbound, 'next': nxt}

    def _set_eta(self, db: sqlite3.Connection, fila: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        try:
            eta = int(data.get('eta_min'))
        except (TypeError, ValueError):
            raise HTTPException(422, 'eta_min debe ser un entero 0–240')
        if not 0 <= eta <= 240:
            raise HTTPException(422, 'eta_min debe ser un entero 0–240')
        db.execute("UPDATE tg_assignments SET eta_min=?, estado='accepted', updated_at=? WHERE id=?",
                   (eta, _now(), fila['id']))
        return {'ok': True, 'estado': 'accepted', 'incident_id': fila['incident_id'],
                'assignment_id': fila['id'], 'rol': fila['rol'], 'alias': fila['alias'],
                'intento': fila['intento'], 'eta_min': eta, 'from_zone': fila.get('from_zone'),
                'outbound': {
                    'event': 'telegram_send', 'chat_id': fila['chat_id'],
                    'text': f'ETA {eta} min anotada (simulación).',
                }, 'next_outbound': None}

    def _set_loc(self, db: sqlite3.Connection, fila: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        zona = _texto(data, 'from_zone', 60, obligatorio=True)
        db.execute("UPDATE tg_assignments SET from_zone=?, estado='accepted', updated_at=? WHERE id=?",
                   (zona, _now(), fila['id']))
        return {'ok': True, 'estado': 'accepted', 'incident_id': fila['incident_id'],
                'assignment_id': fila['id'], 'rol': fila['rol'], 'alias': fila['alias'],
                'intento': fila['intento'], 'eta_min': fila.get('eta_min'), 'from_zone': zona,
                'outbound': {
                    'event': 'telegram_send', 'chat_id': fila['chat_id'],
                    'text': f'Posición «{zona}» anotada (simulación).',
                }, 'next_outbound': None}

    def _offer_message(self, assignment: dict[str, Any], texto: str, tipo: str,
                       zona: str, gravedad: str) -> dict[str, Any]:
        rol = SEAT_ES.get(assignment['rol'], assignment['rol'])
        zona_txt = zona or 'zona no indicada'
        body = (f'SIMULACIÓN · {rol}\n'
                f'Urgencia: {gravedad} · {zona_txt}\n'
                f'{texto[:280]}\n\n'
                '¿Puedes acudir? Esto es una simulación de hackathon, no un servicio de emergencias.')
        return {
            'event': 'telegram_send',
            'chat_id': assignment['chat_id'],
            'text': body,
            'correlation_id': assignment['id'],
            'reply_markup': {'inline_keyboard': [[
                {'text': 'Acepto', 'callback_data': _callback('acc', assignment['id'])},
                {'text': 'No puedo', 'callback_data': _callback('dec', assignment['id'])},
            ]]},
        }

    def _eta_loc_message(self, fila: dict[str, Any]) -> dict[str, Any]:
        aid = fila['id']
        return {
            'event': 'telegram_send',
            'chat_id': fila['chat_id'],
            'text': ('Anotado. ¿ETA y desde dónde? (simulación)\n'
                     'Los minutos y la zona son una estimación para la demo.'),
            'correlation_id': aid,
            'reply_markup': {'inline_keyboard': [
                [
                    {'text': 'ETA 2 min', 'callback_data': _callback('eta', aid, '2')},
                    {'text': 'ETA 5 min', 'callback_data': _callback('eta', aid, '5')},
                    {'text': 'ETA 10 min', 'callback_data': _callback('eta', aid, '10')},
                ],
                [
                    {'text': 'Foso', 'callback_data': _callback('loc', aid, 'front_pit')},
                    {'text': 'Acceso A', 'callback_data': _callback('loc', aid, 'gate_a')},
                    {'text': 'Escenario', 'callback_data': _callback('loc', aid, 'main_stage')},
                ],
            ]},
        }

    def _mirror_incident(self, mirror: Any, iid: str, texto: str, tipo: str, zona: str,
                         gravedad: str, prioridad: int, alias: str, *, new: bool) -> None:
        if mirror is None or not new:
            return
        rol = ROLE_PREFERENCE.get(tipo, ROLE_PREFERENCE['otro'])[0]
        try:
            mirror.handle({
                'type': 'tg_incident', 'schema': 'mando.hr.v1',
                'event_id': f'{iid}-0', 'id': iid, 'texto': texto, 'tipo': tipo,
                'zona': zona or None, 'gravedad': gravedad, 'prioridad': min(10, max(0, int(prioridad))),
                'requiere_aprobacion': False, 'alias_informante': alias[:40],
                'recursos_requeridos': [{'rol': SEAT_TO_ESPEJO.get(rol, rol), 'cantidad': 1}],
            })
        except HTTPException:
            pass

    def _mirror_assignment(self, mirror: Any, incident_id: str, rol: str, estado: str,
                           alias: str, intento: int, *, eta: int | None = None,
                           from_zone: str | None = None, motivo: str = '') -> None:
        if mirror is None:
            return
        ev: dict[str, Any] = {
            'type': 'tg_assignment', 'schema': 'mando.hr.v1',
            'event_id': f'{incident_id}-{rol}-{estado}-{intento}-{uuid.uuid4().hex[:6]}',
            'incident_id': incident_id, 'rol': SEAT_TO_ESPEJO.get(rol, rol),
            'estado': estado, 'alias': alias, 'intento': intento,
        }
        if eta is not None:
            ev['eta_min'] = eta
        if from_zone:
            ev['from_zone'] = from_zone
        if motivo:
            ev['motivo'] = motivo
        try:
            mirror.handle(ev)
        except HTTPException:
            pass

    def _mirror_staff(self, mirror: Any, view: dict[str, Any]) -> None:
        if mirror is None:
            return
        try:
            mirror.handle({
                'type': 'tg_staff', 'schema': 'mando.hr.v1',
                'event_id': f'staff-{uuid.uuid4().hex[:10]}',
                'disponibles': int(view.get('disponibles') or 0),
                'total': int(view.get('total') or len(SEATS)),
            })
        except HTTPException:
            pass

    def _mirror_approval(self, mirror: Any, incident_id: str, kind: str, por: str) -> None:
        cargo = por if por in ('organizador', 'director', 'coordinador') else 'organizador'
        try:
            mirror.handle({
                'type': 'tg_approval', 'schema': 'mando.hr.v1',
                'event_id': f'{incident_id}-{kind}-{uuid.uuid4().hex[:6]}',
                'incident_id': incident_id, 'decision': kind, 'por': cargo,
            })
        except HTTPException:
            pass
