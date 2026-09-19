"""Espejo del despacho por Telegram: lo que decide HappyRobot, a la vista en la Sala de control.

Quién decide qué: el bucle vivo es Telegram → HappyRobot (`fa-entrada-tg`, `fa-despacho-tg`,
`fa-respuesta-tg`) con memoria en Twin. **Ahí decide un LLM.** Este módulo NO decide nada: recibe por
`POST /hr/events` lo que ya ha pasado allí y expone `S.telegram` con el contrato compartido.

Tipos (detalle en ESPEJO-TELEGRAM.md): `tg_incident`, `tg_assignment`, `tg_staff`, `tg_approval`.

Identidades: alias o cargo. Nunca `chat_id` ni teléfono: el validador devuelve 422 para que un workflow
mal configurado se note en la plataforma y no gotee datos personales al estado público.

`tg_approval` se registra en el log (autor «organizador por Telegram»). Si coincide con una acción de
Mando pendiente de aprobación, la tarjeta de la Sala se marca como decidida en Telegram; la acción grave
solo se ejecuta si `MANDO_TRUST_TG_APPROVAL=1` (por defecto no).
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

from fastapi import HTTPException

from motor.mando.lexicon import GATE, GATE_DIR, ZONE_RE

from . import hr_routing
from .telegram_bot import match_zone

TIPOS = ('medica', 'aglomeracion', 'seguridad', 'incendio', 'clima', 'infraestructura', 'menor', 'otro')
GRAVEDADES = ('vital', 'emergencia', 'urgente', 'leve', 'sin_clasificar')
ESTADOS = ('pending', 'accepted', 'declined', 'timeout', 'covered')
DECISIONES = {'apr': 'aprobada', 'vet': 'vetada'}
ROLES = ('medico', 'enfermero', 'sanitario', 'ambulancia', 'seguridad', 'tecnico',
         'logistica', 'voluntario', 'jefe_zona', 'organizador')
ROLES_QUE_APRUEBAN = ('organizador', 'director', 'coordinador')
AUTOR_TG = 'organizador por Telegram'
ROL_ES = {'medico': 'médico', 'enfermero': 'enfermero', 'sanitario': 'sanitario', 'ambulancia': 'ambulancia',
          'seguridad': 'seguridad', 'tecnico': 'técnico', 'logistica': 'logística', 'voluntario': 'voluntario',
          'jefe_zona': 'jefe de zona', 'organizador': 'organizador'}
PRESET_DE_TIPO = {'medica': 'heat', 'aglomeracion': 'surge', 'seguridad': 'fight', 'incendio': 'smoke',
                  'infraestructura': 'barrier', 'menor': 'child'}
INTENTOS_MAX = 3
MAX_MENSAJES = 60

_PHONE = re.compile(r'(\+\d[\d\s().-]{6,})|(\d{7,})')


def _texto(data: dict, key: str, maximo: int, *, obligatorio: bool = False) -> str:
    v = data.get(key)
    if v is None and not obligatorio:
        return ''
    if not isinstance(v, str) or len(v) > maximo:
        raise HTTPException(422, f'{key} debe ser texto de {maximo} caracteres como mucho')
    v = v.strip()
    if obligatorio and not v:
        raise HTTPException(422, f'Falta {key}')
    return v


def _entero(data: dict, key: str, lo: int, hi: int, *, obligatorio: bool = False) -> int | None:
    v = data.get(key)
    if v is None:
        if obligatorio:
            raise HTTPException(422, f'Falta {key}')
        return None
    if isinstance(v, bool):
        raise HTTPException(422, f'{key} debe ser un entero entre {lo} y {hi}')
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() == 'null':
            if obligatorio:
                raise HTTPException(422, f'Falta {key}')
            return None
        try:
            v = int(s, 10)
        except ValueError:
            raise HTTPException(422, f'{key} debe ser un entero entre {lo} y {hi}')
    elif not isinstance(v, int):
        raise HTTPException(422, f'{key} debe ser un entero entre {lo} y {hi}')
    if not lo <= v <= hi:
        raise HTTPException(422, f'{key} debe ser un entero entre {lo} y {hi}')
    return v


def _booleano(data: dict, key: str, *, default: bool = False) -> bool:
    if key not in data:
        return default
    v = data[key]
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ('', 'null', 'false', '0', 'no'):
            return False
        if s in ('true', '1', 'yes', 'si', 'sí'):
            return True
        raise HTTPException(422, f'{key} debe ser booleano JSON o cadena true/false')
    raise HTTPException(422, f'{key} debe ser booleano JSON o cadena true/false')


def _resolver_zona(session: Any, raw: str | None, campo: str = 'zona') -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise HTTPException(422, f'{campo} debe ser texto')
    texto = raw.strip()
    if not texto or texto.lower() == 'null':
        return None
    ids = session.world.L.idx
    if texto in ids:
        return texto
    zones = {z['id']: z['name'] for z in session.festival['zones']}
    hit = match_zone(texto, zones)
    if hit and hit in ids:
        return hit
    q = texto.lower()
    m = GATE.search(q)
    if m:
        gate = f'gate_{m.group(1)}'
        if gate in ids:
            return gate
    m = GATE_DIR.search(q)
    if m:
        word = (m.group(1) or m.group(2) or '').lower()
        word = {'north': 'norte', 'south': 'sur', 'main': 'principal'}.get(word, word)
        for zid, name in zones.items():
            if word in name.lower().split():
                return zid
    for zid, rx in ZONE_RE:
        if zid in ids and rx.search(q):
            return zid
    session.log('espejo_telegram', f'Zona desconocida «{texto[:60]}» en {campo}: se guarda como null')
    return None


def _identidad(valor: str, key: str) -> str:
    if _PHONE.search(valor):
        raise HTTPException(422, f'{key}: alias o cargo, nunca un chat_id ni un teléfono')
    return valor


def _campos(data: dict, permitidos: set[str]) -> None:
    sobra = set(data) - permitidos
    if sobra:
        raise HTTPException(422, 'Campos desconocidos: ' + ', '.join(sorted(sobra)))


class TelegramMirror:
    """Copia de solo lectura del despacho que lleva HappyRobot por Telegram."""

    def __init__(self, session: Any) -> None:
        self.s = session
        self.incidentes: dict[str, dict[str, Any]] = {}
        self.staff: dict[tuple[str, str], dict[str, Any]] = {}
        self.staff_disponibles: int | None = None
        self.staff_total: int | None = None
        self.mensajes: list[dict[str, Any]] = []
        self.events: dict[str, dict[str, Any]] = {}

    def handle(self, ev: dict[str, Any]) -> dict[str, Any]:
        kind = str(ev.get('type') or '')
        if ev.get('recovered'):
            raise HTTPException(422, 'El espejo de Telegram exige JSON válido completo')
        handler = {'tg_incident': self._incident, 'tg_assignment': self._assignment,
                   'tg_staff': self._staff, 'tg_approval': self._approval}.get(kind)
        if handler is None:
            raise HTTPException(422, f'Tipo de espejo de Telegram desconocido: {kind}')
        eid = _texto(ev, 'event_id', 120)
        with self.s.lock:
            if eid and eid in self.events:
                return dict(self.events[eid], duplicate=True)
            out = handler(ev)
            if eid:
                self.events[eid] = out
            self.s._rebuild()
        self.s._wake.set()
        return out

    def _incident(self, ev: dict[str, Any]) -> dict[str, Any]:
        _campos(ev, {'type', 'schema', 'event_id', 'hr_run_id', 'run_url', 'id', 'texto', 'tipo', 'zona',
                     'gravedad', 'prioridad', 'recursos_requeridos', 'requiere_aprobacion', 'alias_informante'})
        iid = _texto(ev, 'id', 60, obligatorio=True)
        texto = _texto(ev, 'texto', 400, obligatorio=True)
        tipo = _texto(ev, 'tipo', 40) or 'otro'
        if tipo not in TIPOS:
            raise HTTPException(422, 'tipo desconocido: ' + ', '.join(TIPOS))
        gravedad = _texto(ev, 'gravedad', 20) or 'sin_clasificar'
        if gravedad not in GRAVEDADES:
            raise HTTPException(422, 'gravedad desconocida: ' + ', '.join(GRAVEDADES))
        zona = _resolver_zona(self.s, _texto(ev, 'zona', 60) or None, 'zona')
        prioridad = _entero(ev, 'prioridad', 0, 10)
        requiere = _booleano(ev, 'requiere_aprobacion')
        informante = _identidad(_texto(ev, 'alias_informante', 40), 'alias_informante')
        recursos = self._recursos(ev.get('recursos_requeridos'))
        if iid in self.incidentes:
            return dict(ok=True, duplicate=True, incident_id=iid,
                        report_id=self.incidentes[iid]['report_id'])

        out = self.s.report('whatsapp', texto, zona, source='HappyRobot · Telegram', via='telegram',
                            where=zona, understood='happyrobot', preset_hint=PRESET_DE_TIPO.get(tipo),
                            extracted={'category': tipo, 'severity_label': gravedad,
                                       'priority_hr': prioridad, 'source_agent': 'fa-entrada-tg'})
        item = {'id': iid, 'report_id': out['report_id'], 'texto': texto, 'tipo': tipo, 'zona': zona,
                'gravedad': gravedad, 'prioridad': prioridad, 'requiere_aprobacion': requiere,
                'recursos_requeridos': recursos, 'informante': informante, 'aprobacion': None,
                'asignaciones': [], 't': self.s.world.t}
        self.incidentes[iid] = item
        pedido = ', '.join(f'{ROL_ES.get(r["rol"], r["rol"])}×{r["cantidad"]}' for r in recursos) or 'sin roles'
        self._mensaje('informante', informante or 'Asistente', texto)
        self.s.log('espejo_telegram',
                   f'Espejo de Telegram: aviso {iid} entendido por HappyRobot ({tipo} · {gravedad}); pide {pedido}',
                   out['report_id'], incident=iid)
        return dict(ok=True, duplicate=False, incident_id=iid, report_id=out['report_id'])

    def _recursos(self, valor: Any) -> list[dict[str, Any]]:
        if valor is None:
            return []
        if not isinstance(valor, list) or len(valor) > 8:
            raise HTTPException(422, 'recursos_requeridos debe ser una lista de 8 elementos como mucho')
        salida = []
        for item in valor:
            if not isinstance(item, dict):
                raise HTTPException(422, 'recursos_requeridos: cada elemento es {rol, cantidad}')
            _campos(item, {'rol', 'cantidad'})
            rol = _texto(item, 'rol', 30, obligatorio=True)
            if rol not in ROLES:
                raise HTTPException(422, 'rol desconocido: ' + ', '.join(ROLES))
            cantidad = _entero(item, 'cantidad', 1, 10)
            salida.append({'rol': rol, 'cantidad': cantidad if cantidad is not None else 1})
        return salida

    def _assignment(self, ev: dict[str, Any]) -> dict[str, Any]:
        _campos(ev, {'type', 'schema', 'event_id', 'hr_run_id', 'run_url', 'incident_id', 'rol', 'estado',
                     'alias', 'eta_min', 'from_zone', 'intento', 'timeout_s', 'motivo'})
        item = self._incidente(ev)
        rol = _texto(ev, 'rol', 30, obligatorio=True)
        if rol not in ROLES:
            raise HTTPException(422, 'rol desconocido: ' + ', '.join(ROLES))
        estado = _texto(ev, 'estado', 20, obligatorio=True)
        if estado not in ESTADOS:
            raise HTTPException(422, 'estado desconocido: ' + ', '.join(ESTADOS))
        alias = _identidad(_texto(ev, 'alias', 40), 'alias')
        eta = _entero(ev, 'eta_min', 0, 240)
        intento = _entero(ev, 'intento', 1, INTENTOS_MAX + 2) or 1
        motivo = _texto(ev, 'motivo', 200)
        zona = _resolver_zona(self.s, _texto(ev, 'from_zone', 60) or None, 'from_zone')

        fila = next((a for a in item['asignaciones'] if a['rol'] == rol and a['alias'] == alias
                     and a['intento'] == intento), None)
        if fila is None:
            fila = {'rol': rol, 'alias': alias, 'intento': intento, 'estado': estado,
                    'eta_min': None, 'from_zone': None, 'motivo': '', 't': self.s.world.t}
            item['asignaciones'].append(fila)
        fila.update(estado=estado, t=self.s.world.t)
        if eta is not None:
            fila['eta_min'] = eta
        if zona is not None:
            fila['from_zone'] = zona
        if motivo:
            fila['motivo'] = motivo

        if alias:
            self.staff[(alias, rol)] = {'alias': alias, 'rol': rol, 'estado': estado,
                                        'zona': zona or self.staff.get((alias, rol), {}).get('zona'),
                                        't': self.s.world.t}
        self._mensaje('staff' if estado in ('accepted', 'declined') else 'mando',
                      alias or ROL_ES.get(rol, rol), self._frase(fila))
        self.s.log('espejo_telegram', f'Espejo de Telegram · {item["id"]}: {self._frase(fila)}',
                   item['report_id'], incident=item['id'])
        return dict(ok=True, duplicate=False, incident_id=item['id'], estado=estado,
                    escalada=self._escalada(item) is not None)

    def _staff(self, ev: dict[str, Any]) -> dict[str, Any]:
        _campos(ev, {'type', 'schema', 'event_id', 'hr_run_id', 'run_url', 'disponibles', 'total'})
        disponibles = _entero(ev, 'disponibles', 0, 500, obligatorio=True)
        total = _entero(ev, 'total', 0, 500, obligatorio=True)
        if disponibles > total:
            raise HTTPException(422, 'disponibles no puede superar a total')
        self.staff_disponibles = disponibles
        self.staff_total = total
        self.s.log('espejo_telegram', f'Espejo de Telegram · staff {disponibles}/{total} disponibles')
        return dict(ok=True, duplicate=False, disponibles=disponibles, total=total)

    def _approval(self, ev: dict[str, Any]) -> dict[str, Any]:
        _campos(ev, {'type', 'schema', 'event_id', 'hr_run_id', 'run_url', 'incident_id', 'decision', 'por', 'nota'})
        item = self._incidente(ev)
        decision = _texto(ev, 'decision', 8, obligatorio=True)
        if decision not in DECISIONES:
            raise HTTPException(422, "decision debe ser 'apr' o 'vet'")
        por = _identidad(_texto(ev, 'por', 30, obligatorio=True), 'por')
        if por not in ROLES_QUE_APRUEBAN:
            raise HTTPException(422, 'por debe ser un cargo: ' + ', '.join(ROLES_QUE_APRUEBAN))
        nota = _texto(ev, 'nota', 200)
        etiqueta = 'APRUEBA' if decision == 'apr' else 'VETA'
        ok = decision == 'apr'
        pending = self._acciones_pendientes(item)
        item['aprobacion'] = {'decision': decision, 'etiqueta': DECISIONES[decision], 'por': por,
                              'nota': nota, 't': self.s.world.t, 'autor': AUTOR_TG,
                              'acciones': [a['id'] for a in pending]}
        for action in pending:
            self.s._tg_approval_marks[action['id']] = {
                'label': etiqueta,
                'por': AUTOR_TG,
                'text': f'Decidido en Telegram por el organizador: {etiqueta}',
                'decision': decision,
                't': self.s.world.t,
            }
        trust = os.environ.get('MANDO_TRUST_TG_APPROVAL', '') == '1'
        ejecutadas = 0
        if trust and pending:
            for action in pending:
                if self.s.approve(action['id'], ok, nota, by=AUTOR_TG):
                    ejecutadas += 1
        frase = f'{AUTOR_TG}: {etiqueta}' + (f' — {nota}' if nota else '')
        if pending:
            frase += f' ({len(pending)} tarjeta(s) de la Sala marcada(s)'
            frase += '; ejecutada(s)' if ejecutadas else '; sin ejecutar: MANDO_TRUST_TG_APPROVAL≠1'
            frase += ')'
        self._mensaje('organizador', por, frase)
        self.s.log('espejo_telegram', f'Espejo de Telegram · {item["id"]}: {frase}',
                   item['report_id'], incident=item['id'])
        return dict(ok=True, duplicate=False, incident_id=item['id'], decision=decision,
                    marked=len(pending), executed=ejecutadas)

    def _mando_incident(self, item: dict[str, Any]) -> str | None:
        report_id = item.get('report_id')
        if not report_id:
            return None
        for inc in self.s._snapshot.get('incidents', []):
            if report_id in inc.get('reports', []):
                return inc.get('id')
        return None

    def _acciones_pendientes(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        mando_inc = self._mando_incident(item)
        if not mando_inc:
            return []
        return [a for a in self.s._snapshot.get('actions', [])
                if a.get('status') == 'awaiting_approval' and a.get('incident') == mando_inc]

    def _incidente(self, ev: dict[str, Any]) -> dict[str, Any]:
        iid = _texto(ev, 'incident_id', 60, obligatorio=True)
        item = self.incidentes.get(iid)
        if item is None:
            raise HTTPException(404, f'No hay ningún aviso de Telegram con id {iid} en esta partida')
        return item

    def _mensaje(self, quien: str, nombre: str, texto: str) -> None:
        self.mensajes.append({'de': quien, 'nombre': nombre, 'texto': texto[:400], 't': self.s.world.t})
        del self.mensajes[:-MAX_MENSAJES]

    def _frase(self, fila: dict[str, Any]) -> str:
        rol, alias = ROL_ES.get(fila['rol'], fila['rol']), fila['alias'] or 'sin alias'
        if fila['estado'] == 'pending':
            return f'Telegram → {rol}: pendiente'
        if fila['estado'] == 'accepted':
            eta = f' · {fila["eta_min"]} min' if fila.get('eta_min') is not None else ''
            desde = f' · desde {fila["from_zone"]}' if fila.get('from_zone') else ''
            return f'ACUDE {alias}{eta}{desde}'
        if fila['estado'] == 'declined':
            return f'No puede → reasignando (intento {fila["intento"] + 1})'
        if fila['estado'] == 'timeout':
            return f'Sin respuesta de {alias} en Telegram (intento {fila["intento"]})'
        return 'Cubierto'

    def _escalada(self, item: dict[str, Any]) -> dict[str, Any] | None:
        for recurso in item['recursos_requeridos'] or [{'rol': a['rol']} for a in item['asignaciones']]:
            rol = recurso['rol']
            filas = [a for a in item['asignaciones'] if a['rol'] == rol]
            if not filas or any(a['estado'] in ('accepted', 'covered') for a in filas):
                continue
            if any(a['estado'] == 'pending' for a in filas):
                continue
            if max(a['intento'] for a in filas) < INTENTOS_MAX:
                continue
            slot = hr_routing.slot_for_role(rol) or 'dispatch'
            motivo = (f'{INTENTOS_MAX} avisos por Telegram sin nadie que acuda; '
                      f'queda la llamada por voz ({ROL_ES.get(rol, rol)}).')
            return {'rol': rol, 'motivo': motivo,
                    'workflow_voz': hr_routing.WORKFLOW_NAMES.get(slot, 'mando-despacho-telefono')}
        return None

    def _staff_counts(self) -> dict[str, int]:
        if self.staff_disponibles is not None and self.staff_total is not None:
            return {'disponibles': self.staff_disponibles, 'total': self.staff_total}
        atendiendo = sum(1 for m in self.staff.values() if m['estado'] in ('accepted', 'pending'))
        total = len(self.staff)
        return {'disponibles': max(0, total - atendiendo), 'total': total}

    def view(self) -> dict[str, Any] | None:
        """Contrato compartido con la Sala (`S.telegram`). `None` si el espejo no ha recibido nada."""
        if not self.incidentes and self.staff_disponibles is None and not self.staff:
            return None
        asignaciones = []
        escaladas = []
        for item in self.incidentes.values():
            for a in item['asignaciones']:
                asignaciones.append({
                    'incident_id': item['id'], 'rol': a['rol'], 'estado': a['estado'], 'alias': a['alias'],
                    'eta_min': a.get('eta_min'), 'desde_zona': a.get('from_zone'), 'intento': a['intento'], 't': a['t'],
                })
            esc = self._escalada(item)
            if esc:
                escaladas.append({'incident_id': item['id'], 'rol': esc['rol'],
                                  'motivo': esc['motivo'], 'workflow_voz': esc['workflow_voz']})
        return {'staff': self._staff_counts(), 'asignaciones': asignaciones, 'escaladas': escaladas}


def secuencia_demo(session: Any, zona: str = 'front_pit') -> list[dict[str, Any]]:
    """Aviso → 2 asignaciones → una acepta con ETA y zona, otra rechaza → reasignación → timeout → escalada."""
    if zona not in session.world.L.idx:
        zona = next(iter(session.world.L.ids))
    n = len(session.tg_mirror.incidentes) + 1
    iid = f'tg-demo-{n}'
    base = {'schema': 'mando.hr.v1'}
    return [
        dict(base, type='tg_incident', event_id=f'{iid}-0', id=iid,
             texto='Una chica se ha desmayado por el calor junto a la valla, no responde bien',
             tipo='medica', zona=zona, gravedad='emergencia', prioridad=8, requiere_aprobacion=False,
             alias_informante='Asistente', recursos_requeridos=[{'rol': 'medico', 'cantidad': 1},
                                                                {'rol': 'seguridad', 'cantidad': 1}]),
        dict(base, type='tg_staff', event_id=f'{iid}-s', disponibles=4, total=5),
        dict(base, type='tg_assignment', event_id=f'{iid}-1', incident_id=iid, rol='medico',
             estado='pending', alias='Marta', intento=1),
        dict(base, type='tg_assignment', event_id=f'{iid}-2', incident_id=iid, rol='seguridad',
             estado='pending', alias='Iván', intento=1),
        dict(base, type='tg_assignment', event_id=f'{iid}-3', incident_id=iid, rol='medico',
             estado='accepted', alias='Marta', eta_min=3, from_zone='gate_a', intento=1),
        dict(base, type='tg_assignment', event_id=f'{iid}-4', incident_id=iid, rol='seguridad',
             estado='declined', alias='Iván', intento=1, motivo='está conteniendo la valla'),
        dict(base, type='tg_assignment', event_id=f'{iid}-5', incident_id=iid, rol='seguridad',
             estado='pending', alias='Nadia', intento=2),
        dict(base, type='tg_assignment', event_id=f'{iid}-6', incident_id=iid, rol='seguridad',
             estado='timeout', alias='Nadia', intento=2),
        dict(base, type='tg_assignment', event_id=f'{iid}-7', incident_id=iid, rol='seguridad',
             estado='pending', alias='Bruno', intento=3),
        dict(base, type='tg_assignment', event_id=f'{iid}-8', incident_id=iid, rol='seguridad',
             estado='timeout', alias='Bruno', intento=3),
    ]
