# Enjambre en abanico

El coordinador de HappyRobot llama a los seis especialistas **en serie**: la latencia es la
suma. En `MANDO_CEREBRO=abanico` **nuestro backend** (la pizarra) lanza triaje, prioridad,
recursos, avisos y vigía **en paralelo** por la API de la plataforma y compone la decisión
a medida que llegan (planificación «anytime»). El crítico entra después, con la decisión
ya ejecutada. La latencia pasa de la suma a la del más lento; la Sala enseña las tarjetas
según van llegando.

No se toca la plataforma: mismos workflows de especialista, mismo `entrada_json`.

## Por qué es más rápido y más robusto

- **Rápido:** cinco POST `/workflows/{id}/runs` a la vez; se sondea cada 2 s. En cuanto hay
  triaje + prioridad + recursos se ejecuta (con barandillas). Avisos y vigía pueden llegar
  tarde; el crítico se lanza entonces.
- **Robusto:** si un agente no contesta en `MANDO_ABANICO_TIMEOUT_S` (45 s) se sigue con los
  demás y se anota. Si la plataforma falla entera (sin clave, sin ids, o todos los POST
  caen), el mismo abanico corre con el LLM local (`cerebro_llm.py`) y se rotula
  `fuente=local`. Si también falla, deciden las reglas y la Sala pone en rojo
  «modo degradado: reglas». Lo vital se despacha al instante, como ya existía.
- **Gratis para el reto:** no hace falta un DAG paralelo en HappyRobot (el coordinador de la
  plataforma no puede cablear `execute_in_parallel` con nodos dinámicos).

Cadena, nunca en silencio: **plataforma → LLM local → reglas rotuladas**. Lo único fijo son
las barandillas (lista blanca, lo grave → persona, despacho vital ya).

## Variables (sin secretos en el repo)

| Variable | Defecto | Qué |
|---|---|---|
| `MANDO_CEREBRO` | `reglas` | `abanico` activa este modo |
| `MANDO_ABANICO_TIMEOUT_S` | 45 | tope por agente (reloj de pared) |
| `MANDO_ABANICO_POLL_S` | 2 | sondeo de cada run |
| `HR_API_BASE` | clúster EU `/api/v2` | base de la API |
| `HR_API_KEY` | vacío | Bearer. Nunca en git |
| `HR_AGENTE_TRIAJE` … `_CRITICO` | vacío | id/slug de cada workflow especialista |
| `MANDO_PUBLIC_URL` | — | `callback_url` que se pasa a cada run |
| `HR_SECRET` | — | `callback_token` |

El cuerpo de cada run es `{"environment":"development","payload":{"entrada_json", "callback_url", "callback_token"}}`.
`entrada_json` lleva el aviso **y** el contexto que ya calcula el backend, para que el
especialista no tenga que pedirlo.

Lectura del resultado (en este orden): `GET {HR_API_BASE}/runs/{run_id}` → si hace falta
`GET …/runs/{run_id}/nodes` buscando el nodo **Devolver resultado validado** (o el tool
`entregar_resultado`) → `GET …/runs/{run_id}/outputs/{output_id}`.

## Estado que ve la Sala

`S.agentes[inc].abanico = {lanzados, llegados:[{papel, s}], primera_decision_s, final_s, fuente: plataforma|local|reglas}`.
Cada tarjeta de especialista lleva su latencia (`Recursos · 18 s`). Línea:
«Primera decisión en 21 s · enjambre completo en 44 s».

Nada reservado ni tokens salen en claro (`callback_token` no se pinta).

## Cómo probarlo contra la plataforma real

1. Copia `.env.example` → `.env`. `MANDO_CEREBRO=abanico`, `HR_API_KEY`, los seis
   `HR_AGENTE_*` (ids de development), `MANDO_PUBLIC_URL` del túnel, `HR_SECRET`.
2. Arranca el servidor. En la Sala, operador:

```sh
curl -sS -X POST "$MANDO_PUBLIC_URL/api/demo/abanico" \
  -H "content-type: application/json" \
  -H "X-Mando-Operator: $MANDO_OPERATOR_TOKEN" \
  -d '{"zone":"front_pit"}'
```

Eso mete un aviso de mareo de prueba y lanza el abanico. En «Equipo de agentes» las
seis tarjetas van apareciendo con sus segundos. Un aviso real (Telegram, `/api/report`)
hace lo mismo.

Batería local (API falsa, sin plataforma):

```sh
uv run --project motor/server python -m unittest motor.server.test_abanico -v
```
