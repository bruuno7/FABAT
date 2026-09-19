"""Espejo del despacho por Telegram: lo que decide HappyRobot, a la vista en la Sala de control.

Quién decide qué, dicho sin adornos: el bucle vivo es Telegram → HappyRobot (`fa-entrada-tg`,
`fa-despacho-tg`, `fa-respuesta-tg`) con su memoria en Twin. **Ahí decide un LLM.** Este módulo NO
decide nada: recibe por `POST /hr/events` lo que ya ha pasado allí y lo deja ver en la Sala, en la
ficha del incidente, en el panel de recursos y en el chat. Si el espejo se apaga, el despacho sigue
funcionando igual; lo único que se pierde es la pantalla.

Tres tipos de evento (contrato en ESPEJO-TELEGRAM.md): `tg_incident`, `tg_assignment`, `tg_approval`.

Identidades: alias o cargo. Nunca un `chat_id` ni un teléfono: el validador los rechaza con 422 en vez
de limpiarlos en silencio, para que un workflow mal configurado se note en la plataforma y no gotee
datos personales a la pantalla ni al vídeo.
"""
from __future__ import annotations

import re
import time
from typing import Any

from fastapi import HTTPException

from . import hr_routing

# --- vocabulario cerrado -----------------------------------------------------------------------
TIPOS = ('medica', 'aglomeracion', 'seguridad', 'incendio', 'clima', 'infraestructura', 'menor', 'otro')
GRAVEDADES = ('vital', 'emergencia', 'urgente', 'leve', 'sin_clasificar')
ESTADOS = ('pending', 'accepted', 'declined', 'timeout', 'covered')
DECISIONES = {'apr': 'aprobada', 'vet': 'vetada'}
# Oficios que el despacho de Telegram sabe convocar. `organizador` es quien aprueba, no quien acude.
ROLES = ('medico', 'enfermero', 'sanitario', 'ambulancia', 'seguridad', 'tecnico',
         'logistica', 'voluntario', 'jefe_zona', 'organizador')
ROLES_QUE_APRUEBAN = ('organizador', 'director', 'coordinador')
ROL_ES = {'medico': 'médico', 'enfermero': 'enfermero', 'sanitario': 'sanitario', 'ambulancia': 'ambulancia',
          'seguridad': 'seguridad', 'tecnico': 'técnico', 'logistica': 'logística', 'voluntario': 'voluntario',
          'jefe_zona': 'jefe de zona', 'organizador': 'organizador'}
# Con qué preset del mundo se parece cada tipo, por si el texto no trae ninguna palabra reconocible.
PRESET_DE_TIPO = {'medica': 'heat', 'aglomeracion': 'surge', 'seguridad': 'fight', 'incendio': 'smoke',
                  'infraestructura': 'barrier', 'menor': 'child'}
INTENTOS_MAX = 3            # el mismo tope que el Loop de `fa-despacho-tg`
MAX_MENSAJES = 60
MAX_CRONOLOGIA = 24

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


def _entero(data: dict, key: str, lo: int, hi: int) -> int | None:
    v = data.get(key)
    if v is None:
        return None
    if type(v) is not int or not lo <= v <= hi:
        raise HTTPException(422, f'{key} debe ser un entero entre {lo} y {hi}')
    return v


def _booleano(data: dict, key: str) -> bool:
    v = data.get(key, False)
    if type(v) is not bool:
        raise HTTPException(422, f'{key} debe ser booleano JSON')
    return v


def _identidad(valor: str, key: str) -> str:
    """Alias o cargo. Un `chat_id` o un teléfono disfrazado de alias no entra."""
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
        self.staff: dict[tuple[str, str], dict[str, Any]] = {}   # (alias, rol) -> estado visto
        self.mensajes: list[dict[str, Any]] = []
        self.events: dict[str, dict[str, Any]] = {}              # event_id -> respuesta (idempotencia)

    # ------------------------------------------------------------------ entrada
    def handle(self, ev: dict[str, Any]) -> dict[str, Any]:
        kind = str(ev.get('type') or '')
        if ev.get('recovered'):
            raise HTTPException(422, 'El espejo de Telegram exige JSON válido completo')
        handler = {'tg_incident': self._incident, 'tg_assignment': self._assignment,
                   'tg_approval': self._approval}.get(kind)
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

    # ------------------------------------------------------------------ tg_incident
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
        zona = _texto(ev, 'zona', 60) or None
        if zona is not None and zona not in self.s.world.L.idx:
            raise HTTPException(422, 'Zona desconocida')
        prioridad = _entero(ev, 'prioridad', 0, 10)
        requiere = _booleano(ev, 'requiere_aprobacion')
        informante = _identidad(_texto(ev, 'alias_informante', 40), 'alias_informante')
        recursos = self._recursos(ev.get('recursos_requeridos'))
        if iid in self.incidentes:
            return dict(ok=True, duplicate=True, incident_id=iid,
                        report_id=self.incidentes[iid]['report_id'])

        # El aviso entra por el contrato normal: mismo camino que cualquier otro canal, misma fusión.
        out = self.s.report('whatsapp', texto, zona, source='HappyRobot · Telegram', via='telegram',
                            where=zona, understood='happyrobot', preset_hint=PRESET_DE_TIPO.get(tipo),
                            extracted={'category': tipo, 'severity_label': gravedad,
                                       'priority_hr': prioridad, 'source_agent': 'fa-entrada-tg'})
        item = {'id': iid, 'report_id': out['report_id'], 'texto': texto, 'tipo': tipo, 'zona': zona,
                'gravedad': gravedad, 'prioridad': prioridad, 'requiere_aprobacion': requiere,
                'recursos_requeridos': recursos, 'informante': informante, 'aprobacion': None,
                'asignaciones': [], 'cronologia': [], 'hr_run_id': _texto(ev, 'hr_run_id', 120),
                't': self.s.world.t}
        self.incidentes[iid] = item
        pedido = ', '.join(f'{ROL_ES.get(r["rol"], r["rol"])}×{r["cantidad"]}' for r in recursos) or 'sin roles'
        self._apunta(item, f'Aviso por Telegram, entendido por HappyRobot ({gravedad}). Pide: {pedido}')
        self._mensaje('informante', informante or 'Asistente', texto)
        self.s.log('telegram_espejo',
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

    # ------------------------------------------------------------------ tg_assignment
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
        timeout_s = _entero(ev, 'timeout_s', 0, 3600)
        motivo = _texto(ev, 'motivo', 200)
        zona = _texto(ev, 'from_zone', 60) or None
        if zona is not None and zona not in self.s.world.L.idx:
            raise HTTPException(422, 'from_zone desconocida')

        fila = next((a for a in item['asignaciones'] if a['rol'] == rol and a['alias'] == alias
                     and a['intento'] == intento), None)
        if fila is None:
            fila = {'rol': rol, 'alias': alias, 'intento': intento, 'estado': estado,
                    'eta_min': None, 'from_zone': None, 'timeout_s': None, 'motivo': '',
                    't': self.s.world.t, 'desde': time.monotonic()}
            item['asignaciones'].append(fila)
        fila.update(estado=estado, t=self.s.world.t)
        if eta is not None:
            fila['eta_min'] = eta
        if zona is not None:
            fila['from_zone'] = zona
        if timeout_s is not None:
            fila['timeout_s'] = timeout_s
        if motivo:
            fila['motivo'] = motivo
        if estado == 'pending':
            fila['desde'] = time.monotonic()

        if alias:
            self.staff[(alias, rol)] = {'alias': alias, 'rol': rol, 'estado': estado,
                                        'zona': zona or self.staff.get((alias, rol), {}).get('zona'),
                                        't': self.s.world.t}
        self._apunta(item, self._frase(fila))
        self._mensaje('staff' if estado in ('accepted', 'declined') else 'mando',
                      alias or ROL_ES.get(rol, rol), self._frase(fila))
        self.s.log('telegram_espejo', f'Espejo de Telegram · {item["id"]}: {self._frase(fila)}',
                   item['report_id'], incident=item['id'])
        return dict(ok=True, duplicate=False, incident_id=item['id'], estado=estado,
                    escalada=self._escalada(item) is not None)

    # ------------------------------------------------------------------ tg_approval
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
        item['aprobacion'] = {'decision': decision, 'etiqueta': DECISIONES[decision], 'por': por,
                              'nota': nota, 't': self.s.world.t}
        frase = f'El {por} ha {DECISIONES[decision]} la actuación por Telegram' + (f': {nota}' if nota else '')
        self._apunta(item, frase)
        self._mensaje('organizador', por, frase)
        self.s.log('telegram_espejo', f'Espejo de Telegram · {item["id"]}: {frase}. '
                   'Decisión tomada en Telegram; la tarjeta de decisión de la Sala sigue siendo la que manda aquí.',
                   item['report_id'], incident=item['id'])
        return dict(ok=True, duplicate=False, incident_id=item['id'], decision=decision)

    def _incidente(self, ev: dict[str, Any]) -> dict[str, Any]:
        iid = _texto(ev, 'incident_id', 60, obligatorio=True)
        item = self.incidentes.get(iid)
        if item is None:
            raise HTTPException(404, f'No hay ningún aviso de Telegram con id {iid} en esta partida')
        return item

    # ------------------------------------------------------------------ redacción
    def _apunta(self, item: dict[str, Any], texto: str) -> None:
        item['cronologia'].append({'t': self.s.world.t, 'texto': texto})
        del item['cronologia'][:-MAX_CRONOLOGIA]

    def _mensaje(self, quien: str, nombre: str, texto: str) -> None:
        self.mensajes.append({'de': quien, 'nombre': nombre, 'texto': texto[:400], 't': self.s.world.t})
        del self.mensajes[:-MAX_MENSAJES]

    def _frase(self, fila: dict[str, Any]) -> str:
        """Los rótulos del diseño, uno por estado. Es el texto de la columna AGENTE HR."""
        rol, alias = ROL_ES.get(fila['rol'], fila['rol']), fila['alias'] or 'sin alias'
        if fila['estado'] == 'pending':
            espera = fila.get('timeout_s')
            return f'Telegram → {rol}: pendiente' + (f' {espera} s' if espera else '')
        if fila['estado'] == 'accepted':
            eta = f' · {fila["eta_min"]} min' if fila.get('eta_min') is not None else ''
            desde = f' · desde {self._zona(fila["from_zone"])}' if fila.get('from_zone') else ''
            return f'ACUDE {alias}{eta}{desde}'
        if fila['estado'] == 'declined':
            return (f'No puede → reasignando (intento {fila["intento"] + 1})'
                    + (f': {fila["motivo"]}' if fila.get('motivo') else ''))
        if fila['estado'] == 'timeout':
            return f'Sin respuesta de {alias} en Telegram (intento {fila["intento"]})'
        return 'Cubierto'

    def _zona(self, zid: str | None) -> str:
        if not zid:
            return '—'
        return next((z['name'] for z in self.s.festival['zones'] if z['id'] == zid), zid)

    # ------------------------------------------------------------------ escalada por voz
    def _escalada(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Nadie ha aceptado y ya no quedan intentos: la Sala PROPONE llamar por HappyRobot.

        Propone, no llama: el botón lo pulsa una persona y el workflow es el mismo enrutado de voz que
        usa el resto del sistema (`hr_routing`), sin una segunda tabla que se desincronice."""
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
            return {'rol': rol, 'rol_es': ROL_ES.get(rol, rol), 'slot': slot,
                    'workflow': hr_routing.WORKFLOW_NAMES.get(slot, 'mando-despacho-telefono'),
                    'intentos': max(a['intento'] for a in filas),
                    'por_que': f'{INTENTOS_MAX} avisos por Telegram sin nadie que acuda; '
                               f'queda la llamada por voz ({ROL_ES.get(rol, rol)}).'}
        return None

    # ------------------------------------------------------------------ lo que ve la Sala
    def view(self) -> dict[str, Any]:
        incidentes = []
        escaladas = []
        for item in self.incidentes.values():
            escalada = self._escalada(item)
            ultima = item['asignaciones'][-1] if item['asignaciones'] else None
            aceptada = next((a for a in reversed(item['asignaciones']) if a['estado'] == 'accepted'), None)
            resumen = ultima and self._frase(aceptada or ultima)
            if escalada:
                resumen = f'Nadie acude · proponer llamada por voz ({escalada["rol_es"]})'
            incidentes.append({
                'id': item['id'], 'report_id': item['report_id'], 'texto': item['texto'],
                'tipo': item['tipo'], 'zona': item['zona'], 'zona_nombre': self._zona(item['zona']),
                'gravedad': item['gravedad'], 'prioridad': item['prioridad'],
                'requiere_aprobacion': item['requiere_aprobacion'],
                'recursos_requeridos': [dict(r) for r in item['recursos_requeridos']],
                'informante': item['informante'], 'aprobacion': item['aprobacion'],
                'asignaciones': [dict(a, frase=self._frase(a), from_zone_nombre=self._zona(a.get('from_zone')),
                                      desde=None) for a in item['asignaciones']],
                'cronologia': [dict(c) for c in item['cronologia']],
                'resumen': resumen or 'Telegram: sin asignaciones todavía',
                'clase': self._clase(aceptada, ultima, escalada),
                'escalada': escalada, 't': item['t'],
            })
            if escalada:
                escaladas.append(dict(escalada, incident_id=item['id'], report_id=item['report_id']))
        # «Disponible» = no está atendiendo ningún aviso ahora mismo. Quien dijo «no puedo» a UN aviso
        # sigue disponible para otro; quien no contestó se cuenta aparte para no inflar la cifra.
        atendiendo = sum(1 for m in self.staff.values() if m['estado'] in ('accepted', 'pending'))
        sin_respuesta = sum(1 for m in self.staff.values() if m['estado'] == 'timeout')
        return {
            'activo': bool(self.incidentes),
            'fuente': 'HappyRobot · Telegram (fa-entrada-tg / fa-despacho-tg / fa-respuesta-tg)',
            'nota': 'Espejo de solo lectura: quien decide y despacha es HappyRobot sobre Telegram, con memoria en Twin.',
            'intentos_max': INTENTOS_MAX,
            'incidentes': incidentes,
            'staff': {'titulo': 'Staff por Telegram', 'libres': len(self.staff) - atendiendo,
                      'total': len(self.staff), 'atendiendo': atendiendo, 'sin_respuesta': sin_respuesta,
                      'regla': 'Disponible = no está atendiendo ningún aviso ahora. Solo cuenta el personal '
                               'que ha aparecido en este despacho, no la plantilla del recinto.',
                      'miembros': sorted((dict(m) for m in self.staff.values()),
                                         key=lambda m: (m['rol'], m['alias']))},
            'mensajes': [dict(m) for m in self.mensajes],
            'escaladas': escaladas,
        }

    @staticmethod
    def _clase(aceptada: dict | None, ultima: dict | None, escalada: dict | None) -> str:
        if escalada:
            return 'escalada'
        if aceptada:
            return 'acepta'
        if ultima is None:
            return 'idle'
        return {'pending': 'call', 'declined': 'reject', 'timeout': 'reject', 'covered': 'accept'}.get(
            ultima['estado'], 'idle')


# --------------------------------------------------------------------------------------------
# Secuencia de demostración: el bucle entero sin plataforma ni Telegram. Solo operador.
def secuencia_demo(session: Any, zona: str = 'front_pit') -> list[dict[str, Any]]:
    """Aviso → 2 asignaciones → una acepta con ETA y zona, otra rechaza → reasignación → timeout →
    propuesta de escalada por voz. Devuelve los eventos tal y como los mandaría HappyRobot."""
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
        dict(base, type='tg_assignment', event_id=f'{iid}-1', incident_id=iid, rol='medico',
             estado='pending', alias='Marta', intento=1, timeout_s=40),
        dict(base, type='tg_assignment', event_id=f'{iid}-2', incident_id=iid, rol='seguridad',
             estado='pending', alias='Iván', intento=1, timeout_s=40),
        dict(base, type='tg_assignment', event_id=f'{iid}-3', incident_id=iid, rol='medico',
             estado='accepted', alias='Marta', eta_min=3, from_zone='gate_a', intento=1),
        dict(base, type='tg_assignment', event_id=f'{iid}-4', incident_id=iid, rol='seguridad',
             estado='declined', alias='Iván', intento=1, motivo='está conteniendo la valla'),
        dict(base, type='tg_assignment', event_id=f'{iid}-5', incident_id=iid, rol='seguridad',
             estado='pending', alias='Nadia', intento=2, timeout_s=40),
        dict(base, type='tg_assignment', event_id=f'{iid}-6', incident_id=iid, rol='seguridad',
             estado='timeout', alias='Nadia', intento=2),
        dict(base, type='tg_assignment', event_id=f'{iid}-7', incident_id=iid, rol='seguridad',
             estado='pending', alias='Bruno', intento=3, timeout_s=40),
        dict(base, type='tg_assignment', event_id=f'{iid}-8', incident_id=iid, rol='seguridad',
             estado='timeout', alias='Bruno', intento=3),
    ]
