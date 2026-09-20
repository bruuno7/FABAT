# Herramientas del agente cerebro (HappyRobot → backend MANDO)

El razonamiento vive en un agente LLM de HappyRobot. Este backend es sus **herramientas**, las **barandillas** y la **memoria**. El prompt de sistema (el mismo en local y en la plataforma) está en `PROMPT-CEREBRO.md`.

Base: `B=$MANDO_PUBLIC_URL` (túnel HTTPS; en local `http://127.0.0.1:8000`).
Cabecera de todas: `X-Mando-Token: $HR_SECRET` (el mismo token que `POST /hr/events`).
Cuerpo: JSON objeto. La plataforma manda a menudo un único parámetro `payload_json` (cadena con el objeto): el backend lo desempaqueta.
Respuestas: texto corto + campos, ya pasadas por `privacy.scrub`. **Nunca** teléfonos, `chat_id`, tokens ni texto de un caso reservado.

Modo: `MANDO_CEREBRO=reglas|agente|hibrido` (defecto `reglas`: el planificador no cambia). En `agente` decide HappyRobot. Si no llega `decidir` en `MANDO_CEREBRO_TIMEOUT_S` (defecto 8 s) decide el **equipo local con LLM** (`cerebro_llm.py`, mismos prompts y pizarra). Las reglas de `motor/mando` solo entran si también falla el LLM local: la Sala lo rotula en rojo (`session.modo_degradado` = «modo degradado: reglas») y queda en el log. Lo único determinista son las **barandillas** (lo grave necesita persona; lo vital se despacha ya; lista blanca): no eligen qué hacer, impiden lo prohibido y garantizan lo mínimo. Tras un despacho vital, el equipo razona el resto. Lo vital no espera.

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

Entre 1 y 5 opciones, horizonte 10–15 min. Reutiliza el gemelo (`whatif` / `rehearsal`) y, en despacho, el recibo contrafactual (`recibo`, N=1). **No cambia el recinto.** Las que el gemelo no sepa interpretar vuelven como `no_ensayable` (el agente elige, no el backend).

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
 "evidencia": {"ids": ["ce-1", "ce-2"], "n": 2}, "tipo": "crowd", "zona": "gate_b",
 "para_agente": "recursos"}
{"accion": "aprobar", "id": "L-…", "by": "Ana"}
{"accion": "rechazar", "id": "L-…", "by": "Ana"}
{"accion": "revocar", "id": "L-…", "by": "Ana"}
```

**Aprobar/rechazar/revocar es solo operador** (`X-Mando-Operator` o loopback): desde la Sala o `/memoria` (`POST /api/memoria/lecciones`). Una lección propuesta **no** sale en `contexto`. `para_agente` opcional: esa lección solo llega a ese agente (más las globales) en `contexto` y `pizarra/leer`.

---

## 6. Pizarra

### `POST /hr/tools/pizarra/publicar`

```json
{"de": "recursos", "para": "prioridad", "incidente": "M-001", "tipo": "revision",
 "enlaza": "P-abc", "texto": "La prioridad 9 gasta el único médico; bajar a 6.",
 "confianza": 0.7, "gravedad": "alta", "datos": {}}
```

`tipo`: observacion|propuesta|decision|revision|objecion|correccion|pregunta|respuesta. `para`: agente o `todos`. Una `revision`/`objecion`/`correccion` **enlaza** el id de la propuesta. Objeción de gravedad `alta` bloquea `decidir` (salvo lo vital) y, si no se resuelve en `MANDO_ENJAMBRE_OBJECION_S` (defecto 45 s), escala a una persona.

### `POST /hr/tools/pizarra/leer`

```json
{"agente": "recursos", "incidente": "M-001", "n": 12}
```

Lo dirigido a ese agente primero; lecciones aprobadas suyas + globales; sin texto de incidentes reservados.

El estado público (`GET /api/state`) expone `S.enjambre` = `{modo, agentes: [{id, estado, ultimo_mensaje, confianza, n, tendencia, lecciones_activas}], mensajes: [últimos 50], aristas: [{de, para, n}]}`.

## 7. Observar (herramientas pequeñas)

Todas `POST /hr/tools/<nombre>`, mismo token, respuesta corta.

| Tool | Cuerpo | Ejemplo real (demo-gates / demo-1, simulación) |
|---|---|---|
| `zona` | `{"zona":"gate_b"}` | densidad, tendencia, accesos, bloqueos, incidentes en ella |
| `recurso` | `{"recurso":"med_1","zona":"front_pit"}` | dónde está, qué hace, ETA a la zona, carga del día |
| `rutas` | `{"de":"gate_a","a":"front_pit"}` | ETA y alternativas vía otras zonas, con bloqueos |
| `staff` | `{"rol":"medical"}` | personal por rol + estado Telegram/voz del espejo |
| `previsiones` | `{}` | gemelo a 5, 10 y 15 min |
| `incidentes_parecidos` | `{"tipo":"crowd","zona":"gate_b"}` | episodios: qué se hizo y cómo acabó |
| `protocolo` | `{"tipo":"unresponsive_person"}` | instrucción oficial de `motor/protocolos` |
| `confianza` | `{"familia":"crowd"}` | puntuación por agente; N<3 → «sin evidencia» |

## 8. Opciones, comparar, rama

### `POST /hr/tools/acciones_posibles`

```json
{"incidente": "M-001", "zona": "front_pit"}
```

Catálogo amplio (≥ 6 cuando existan) con requisitos, coste, tiempo, riesgo y si exige persona: despachar cada candidato, reasignar, dividir, preposicionar, Telegram, voz, preguntar al informante, jefe de zona, megafonía (persona si es general), desviar, abrir/cerrar acceso, reponer, vigilar, escalar, ayuda externa (siempre persona), parar o evacuar (siempre persona). **No elige.**

### `POST /hr/tools/comparar_opciones`

```json
{"opciones": ["mandar M2 al foso", "desviar puerta B → A", "vigilar sin actuar"], "minutos": 12}
```

Puntúa con vidas en riesgo, tiempo hasta atención, densidad máxima prevista, recursos que quedan, reversibilidad. Devuelve la tabla. **Elige el agente.**

### `POST /hr/tools/analizar_situacion`

```json
{"incidente": "M-001"}
```

Señales (¿vital?, ¿varios a la vez?, ¿contradicciones?, ¿falta ubicación?, ¿recurso crítico agotado?, ¿plan roto?, ¿degradado?, ¿volátil?) y **modo** calma|carga|crisis. El coordinador elige la rama y la publica en la pizarra con su porqué.

### `POST /hr/tools/resultado`

Al cerrar o al llegar aceptó/rechazó/silencio/llegó/evitó/cumplió: actualiza la confianza bayesiana del agente.

## 9. Prompts versionados

`POST /hr/tools/prompt/proponer` (diff + evidencia N). Aprobar/revertir: `POST /api/prompt/versiones` (operador). Una versión no aprobada **nunca** se usa. `GET /api/adaptacion`: modo, autonomía, ritmo del vigía, especialistas, lecciones y versiones activas.

---

## Cerebro local (sin la plataforma)

```bash
python -m motor.server cerebro --case demo-1 --fake
```

Sin `--fake` usa `llm_parser_factory` si `MANDO_LLM=1` y hay clave. En local simula el **equipo** (prompts en `motor/happyrobot/equipo/`, en paralelo donde no hay dependencia): cada agente lee y publica en la pizarra, el crítico deja revisiones y el vigía solo reactiva lo afectado. JSON inválido → un reintento. `--fake` es el cerebro determinista de tests (misma entrada → misma salida; **otra situación → otro razonamiento**).
