# Herramientas del agente cerebro (HappyRobot → backend MANDO)

El razonamiento vive en un agente LLM de HappyRobot. Este backend es sus **herramientas**, las **barandillas** y la **memoria**. El prompt de sistema (el mismo en local y en la plataforma) está en `PROMPT-CEREBRO.md`.

Base: `B=$MANDO_PUBLIC_URL` (túnel HTTPS; en local `http://127.0.0.1:8000`).  
Cabecera de todas: `X-Mando-Token: $HR_SECRET` (el mismo token que `POST /hr/events`).  
Cuerpo: JSON objeto. La plataforma manda a menudo un único parámetro `payload_json` (cadena con el objeto): el backend lo desempaqueta.  
Respuestas: texto corto + campos, ya pasadas por `privacy.scrub`. **Nunca** teléfonos, `chat_id`, tokens ni texto de un caso reservado.

Modo: `MANDO_CEREBRO=reglas|agente|hibrido` (defecto `reglas`: el planificador no cambia). En `agente`, si no llega `decidir` en `MANDO_CEREBRO_TIMEOUT_S` (defecto 8 s) actúa el plan B de reglas. Lo vital no espera.

## Cómo declararlas en HappyRobot

1. Workflow con un nodo **Prompt** (pega `PROMPT-CEREBRO.md`).
2. Bajo ese Prompt, un nodo **Tool** de tipo **Webhook** por cada herramienta (la plataforma solo deja Tools hijas de un Prompt).
3. Cada Tool:
   - Method `POST`
   - URL `B/hr/tools/<nombre>`
   - Header `X-Mando-Token` = secreto de callbacks (variable de entorno del workflow, no del informante)
   - Body: el parámetro `payload_json` (string). El LLM serializa el objeto de abajo. **No** pongas `callback_url` ni el token en los argumentos del agente.
4. Tras `decidir`, el Prompt emite el JSON final del prompt de sistema y termina.

---

## 1. `POST /hr/tools/contexto`

Cuerpo:

```json
{"tipo": "crowd", "zona": "gate_b", "texto": "Puerta B saturada"}
```

(`tipo`, `zona`, `texto` opcionales; texto ≤ 400.)

Respuesta de ejemplo (demo-gates, minuto 0, simulación):

```json
{
  "ok": true,
  "texto": "Contexto para decidir. Cifras de simulación. 0 incidentes abiertos. 15 recursos libres.",
  "minuto": 0,
  "aviso": {"tipo": "crowd", "zona": "gate_b"},
  "incidentes": [],
  "recursos_libres": {
    "medical": [{"id": "med_1", "nombre": "Equipo médico 1", "zona": "medical_1", "eta_min": 4, "estado": "available"}],
    "security": [{"id": "sec_2", "nombre": "Seguridad 2 (Puerta B)", "zona": "gate_b", "eta_min": 0, "estado": "available"}]
  },
  "recursos_ocupados": {},
  "zonas": [{"id": "gate_b", "nombre": "Puerta B", "densidad": 0.0, "tendencia": 0, "estado": "open", "bloqueos": []}],
  "previsiones": [{"que": "previsión del gemelo", "zona": "gate_b", "cuenta_atras_min": 8, "estado": "atencion"}],
  "decisiones_pendientes": [],
  "memoria": {"lecciones_aprobadas": [], "casos_parecidos": []},
  "cerebro": "reglas"
}
```

Los números exactos dependen del minuto y del caso. `lecciones_aprobadas` solo incluye las que una persona ha aprobado. `casos_parecidos` trae hasta 3 episodios (qué se hizo, cómo acabó).

---

## 2. `POST /hr/tools/ensayar`

Cuerpo:

```json
{"opciones": ["desviar puerta B → A y C", "mandar M2 al foso"], "minutos": 12}
```

Una o dos opciones, horizonte 10–15 min. Reutiliza el gemelo (`whatif` / `rehearsal`) y, en despacho, el recibo contrafactual (`recibo`, N=1). **No cambia el recinto.**

Respuesta de ejemplo:

```json
{
  "ok": true,
  "texto": "Ensayo en el gemelo: estado de ahora, sin futuro. No cambia el recinto.",
  "minutos": 12,
  "opciones": [
    {"texto": "desviar puerta B → A y C", "kind": "reroute", "N": 1,
     "numeros": [{"hacia": "gate_a", "pico": 1.86, "min_sobre_4": 0, "veredicto": "mejor"},
                 {"hacia": "gate_c", "pico": 1.86, "min_sobre_4": 0, "veredicto": "mejor"}],
     "supuestos": ["Ensayo en el gemelo: estado de ahora, sin futuro. No cambia nada en el recinto."]},
    {"texto": "mandar M2 al foso", "kind": "dispatch", "resource": "med_2", "zona": "front_pit", "N": 1,
     "numeros": {"pico": 1.6, "llegada": {"med_2": 4}, "min_sobre_4": 0},
     "recibo": {"veredicto": "mixto", "texto": "El recurso llegó solo en la rama alternativa; la otra no llegó dentro de 12 min. Diferencia de tiempo censurada.", "N": 1},
     "supuestos": ["El gemelo copia el estado de ahora y no conoce el guion futuro.", "Horizonte 12 min; más allá sobreestima."]}
  ],
  "supuestos": ["El gemelo copia el estado de ahora y no conoce el guion futuro.", "Horizonte 10–15 min; más allá sobreestima."]
}
```

---

## 3. `POST /hr/tools/decidir`

El agente **entrega** la decisión. El backend aplica barandillas y ejecuta lo permitido.

### Esquema JSON de la decisión

```json
{
  "incident_id": "M-001",
  "fusionar_con": null,
  "prioridad": 7,
  "porque": "Justificación breve con hechos.",
  "avisar": [{"rol": "sanitario", "canal": "voz", "mensaje": "Acude al foso."}],
  "recursos": ["med_2"],
  "acciones": [{"kind": "reroute", "zone": "gate_b", "to": "gate_a"}],
  "supuestos": ["El equipo acepta en 3 min"],
  "vigilar": ["densidad puerta B"],
  "confianza": 0.72,
  "requiere_persona": false,
  "zona": "front_pit",
  "tipo": "crowd",
  "texto": "aviso opcional si incident_id es nuevo"
}
```

| Campo | Tipo | Notas |
|---|---|---|
| `incident_id` | string | id existente, o `"nuevo"` |
| `fusionar_con` | string \| omitir | id de otro incidente |
| `prioridad` | número 0–10 | obligatorio si se manda; no palabras («alta») |
| `porque` | string ≤ 400 | **obligatorio** |
| `avisar` | lista ≤ 8 | `{rol\|recurso, canal, mensaje}`. Destino = alias/rol, **nunca** un teléfono |
| `recursos` | lista ≤ 8 | ids (`med_2`) o `{id, zona}` |
| `acciones` | lista ≤ 8 | `{kind, zone?, to?, resource?}`. `kind`: `dispatch`, `reroute`, `evacuate`, `stop_show`, `request_external`, `notify`, … |
| `supuestos`, `vigilar` | lista de textos cortos | ≤ 8 |
| `confianza` | 0–1 | |
| `requiere_persona` | bool | |
| `agente` | string | `triaje` \| `prioridad` \| `recursos` \| `avisos` \| `vigia` \| `critico` \| `equipo` (defecto). Un especialista entrega un voto **parcial**; el backend los compone en una decisión conjunta por incidente. Si dos agentes chocan (misma prioridad distinta, mismo recurso a zonas distintas, evacuar vs desvío…), **no se ejecuta** y la respuesta trae `conflicto`. Las barandillas se aplican a la conjunta. |

Barandillas (deterministas, no las decide el LLM):

- `evacuate` / `stop_show` / `request_external` → **tarjeta** a una persona, nunca se ejecutan solas.
- Riesgo vital → despacho médico inmediato aunque el agente no lo pida.
- Destino fuera de la lista blanca de zonas o de `MANDO_ALLOWED_NUMBERS` → bloqueado, el agente recapacita.
- Recurso inexistente u ocupado → bloqueado con el motivo.

Respuesta de ejemplo (evacuar → tarjeta):

```json
{
  "ok": true,
  "texto": "Aceptadas 1, bloqueadas 0. Porque: Densidad extrema: hay que evacuar el foso.",
  "incident_id": "M-001",
  "nuevo": true,
  "origen": "agente HR",
  "aceptadas": [{"ok": true, "kind": "evacuate", "action_id": "A-0001", "tarjeta": true,
                 "status": "awaiting_approval", "motivo": "evacuar / parar / ayuda externa → persona",
                 "origen": "agente HR"}],
  "bloqueadas": [],
  "confianza": 0.7,
  "requiere_persona": true
}
```

El origen `agente HR` sale en la Sala (`/api/state` → `incidents[].origin`, `actions[].origen`, `agentes`) y en `GET /api/explica`. `S.agentes` (por incidente): qué dijo cada agente (razonamiento resumido, confianza, supuestos, hora), qué se ejecutó, qué se bloqueó y por qué, qué espera a una persona. Detalle: `GET /api/agentes/{incident_id}`.

---

## 4. `POST /hr/tools/cambio`

La usa el vigía (y `mando-reevalua`) cuando algo se mueve.

```json
{"tipo": "rechazo", "incident_id": "M-001", "recurso": "med_1"}
```

`tipo`: `rechazo` | `silencio` | `dato_nuevo` | `sensor` | `prevision` | `golpe`. Opcionales: `incident_id`, `zona`, `recurso`, `texto`.

Respuesta: `afectados` = incidentes abiertos y planes que quedan tocados (id, zona, supuestos). **No cambia el recinto.**

---

## 5. Memoria (la misma SQLite, `MANDO_DB`)

### `POST /hr/tools/memoria/guardar`

```json
{
  "id": "ce-…",
  "agente": "prioridad",
  "tipo": "crowd",
  "zona": "gate_b",
  "franja": "20:00",
  "entrada": {},
  "contexto": {},
  "razonamiento": "…",
  "decision": {},
  "acciones": [],
  "respuestas": {},
  "resultado": {"texto": "…"},
  "tiempos": {"total_s": 1.2}
}
```

Respuesta: `{"ok": true, "id": "ce-…", "texto": "episodio guardado en el ledger"}`.

### `POST /hr/tools/memoria/buscar`

```json
{"tipo": "crowd", "zona": "gate_b", "franja": "20:00", "texto": "desvío", "limit": 8}
```

Respuesta: `{"ok": true, "texto": "1 casos", "casos": [{"id": "…", "que_se_hizo": "…", "como_acabo": "…"}]}`.

### `POST /hr/tools/memoria/lecciones`

```json
{"accion": "listar"}
{"accion": "proponer", "texto": "Nunca desviar B hacia C si C ya va a 4/m²",
 "evidencia": {"ids": ["ce-1", "ce-2"], "n": 2}, "tipo": "crowd", "zona": "gate_b"}
{"accion": "aprobar", "id": "L-…", "by": "Ana"}
{"accion": "rechazar", "id": "L-…", "by": "Ana"}
```

**Aprobar/rechazar es solo operador** (`X-Mando-Operator` o loopback): desde la Sala o `/memoria` (`POST /api/memoria/lecciones`). Una lección propuesta **no** sale en `contexto`.

---

## Cerebro local (sin la plataforma)

```bash
python -m motor.server cerebro --case demo-1 --fake
```

Sin `--fake` usa `llm_parser_factory` si `MANDO_LLM=1` y hay clave. En local simula el **equipo** (prompts en `motor/happyrobot/equipo/`, en paralelo donde no hay dependencia). JSON inválido → un reintento. `--fake` es el cerebro determinista de tests.
