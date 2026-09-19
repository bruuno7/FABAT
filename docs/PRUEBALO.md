# Pruébalo — qué ha cambiado y cómo probarlo (rama `ana`, sáb 19-sep 16:05)

## Qué ha cambiado (antes → ahora)

| | Antes (`main`) | Ahora (rama `ana`) |
|---|---|---|
| **Quién decide** | Un planificador con reglas (`motor/mando`) dentro de nuestro servidor. HappyRobot solo hablaba y entendía. | Un **equipo de agentes de HappyRobot**: triaje (qué información importa), prioridad (qué va primero), recursos (dónde van), avisos (a quién y cómo), vigía (cuándo tirar el plan) y crítico (revisa antes de ejecutar), coordinados por `prueba-ana-equipo`. |
| **Qué hace nuestro servidor** | Decidía y ejecutaba. | Es el **mundo y las manos** del equipo: le da contexto, le deja ensayar en el gemelo, ejecuta lo que decide y le pone **barandillas**. |
| **Barandillas** (no las decide un LLM, a propósito) | Implícitas en las reglas. | Explícitas en `/hr/tools/decidir`: evacuar / parar / ayuda externa → **siempre una persona**; riesgo vital → **despacho inmediato** aunque el agente calle; recurso o destino inválido → **bloqueado con el motivo**. |
| **Memoria** | Ledger de llamadas. | Además **episodios** (qué vio, qué razonó cada agente, qué decidió, qué pasó) y **lecciones** (propuestas por `prueba-ana-aprende`, aprobadas por una persona, que entran en el contexto la próxima vez). |
| **Si la plataforma no contesta** | — | Plan B: deciden las reglas pasados `MANDO_CEREBRO_TIMEOUT_S` segundos (lo vital no espera ni eso). |
| **Cómo se activa** | — | `MANDO_CEREBRO=reglas` (por defecto, todo como antes) · `agente` · `hibrido`. |

## Qué funciona HOY (comprobado a las 16:05)

- ✅ Servidor con configuración real y **abierto a internet por un túnel** (la URL está en `.env`, `MANDO_PUBLIC_URL`; cambia si el túnel se reconecta).
- ✅ **Herramientas del equipo** (`/hr/tools/contexto`, `ensayar`, `decidir`, `memoria/*`): responden por el túnel con el token y rechazan sin él (401). 16 tests en verde.
- ✅ **Cerebro local** (el mismo bucle sin la plataforma): `uv run --project motor/server python -m motor.server cerebro --case demo-1 --fake` → guarda el episodio en el ledger.
- ✅ **Equipo de agentes montado en HappyRobot** (11 workflows `prueba-ana-*`, en borrador). El coordinador `prueba-ana-equipo` tiene una rama rápida para riesgo vital, la extracción, el agente coordinador con los seis especialistas como herramientas, y las llamadas a `decidir` y `memoria/guardar`.
- ⏳ **Falta para la primera ejecución en la plataforma**: publicarlos en *development* (la plataforma exige abrir a mano «View Tool Call Result» en cada tool) y que Telegram (`fa-entrada-tg`, de Bruno) llame a `prueba-ana-equipo`.
- ⏳ En curso: una sola base de datos, decisiones por agente en el estado y panel «Cómo lo ha decidido el equipo» en la Sala; limpieza del repo.

## Cómo probarlo tú (de menos a más)

**1. Levantar el servidor** (en tu clon, rama `ana`; pide el `.env` a Ana: lleva claves y NO está en git):
```sh
git fetch && git checkout ana
set -a && . ./.env && set +a
uv run --project motor/server python -m motor.server --case demo-1 --port 8000 --comms happyrobot
```
Abre http://127.0.0.1:8000/ (Sala de control).

**2. Preguntar a las herramientas lo que ve el equipo** (otra terminal, mismo `.env` cargado):
```sh
curl -s -X POST "$MANDO_PUBLIC_URL/hr/tools/contexto" -H "content-type: application/json" \
  -H "X-Mando-Token: $HR_SECRET" -d '{"tipo":"medical","zona":"front_pit","texto":"una chica se ha desmayado en primera fila"}'
```
Deberías ver «Contexto para decidir… N incidentes abiertos… recursos libres» con la ETA de cada equipo.

**3. Comprobar una barandilla** (el agente pide evacuar → NO se ejecuta, sale una tarjeta para una persona):
```sh
curl -s -X POST "$MANDO_PUBLIC_URL/hr/tools/decidir" -H "content-type: application/json" -H "X-Mando-Token: $HR_SECRET" \
  -d '{"incident_id":"nuevo","prioridad":9,"porque":"prueba","acciones":[{"tipo":"evacuate","zona":"front_pit"}],"confianza":0.6,"requiere_persona":false}'
```
Deberías ver la acción en «bloqueadas» o «pendientes de persona», y la tarjeta en la Sala. (El formato exacto de la decisión está en `motor/happyrobot/cerebro/HERRAMIENTAS.md`.)

**4. Ver el bucle entero sin plataforma**: `uv run --project motor/server python -m motor.server cerebro --case demo-1 --fake`.

**5. En HappyRobot**: abre `prueba-ana-equipo` en el editor y mira la cadena (entrada → rama vital → extracción → coordinador con seis especialistas → decidir → memoria). Cuando esté publicado en development, se prueba con el hook `prueba-ana-equipo-hook` pasando `callback_url` = `MANDO_PUBLIC_URL` y `callback_token` = `HR_SECRET`.

## Qué es real y qué es simulado (dilo así)
Real: la plataforma HappyRobot y sus agentes, el bot de Telegram, los webhooks, la memoria en disco. Simulado: el recinto, la multitud, los recursos y el tiempo. Ningún teléfono suena mientras `MANDO_ALLOWED_NUMBERS` esté vacío.
