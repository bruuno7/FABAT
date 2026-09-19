# Una sola base de datos

MANDO guarda en **un único SQLite** el historial de la partida (el mismo estado público ya
enmascarado de `/api/state`), la auditoría de llamadas, los episodios de cada agente del
equipo y las lecciones. El módulo de acceso es `motor/server/memoria_db.py`. `ledger.py` y
`db.py` son fachadas: misma API de siempre, mismo fichero. Un solo hilo escritor con cola
acotada; si el disco falla, el reloj continúa.

## Configuración y apertura

- Ruta predeterminada: `motor/server/data/mando.db`.
- Ruta: `MANDO_DB=/ruta/mando.db`. Si no está, se acepta `MANDO_LEDGER_PATH` (alias, no otra base).
- Historial desactivado: `MANDO_DB=off` (el ledger puede seguir si hay `MANDO_LEDGER_PATH`).
- SQLite usa WAL, claves foráneas en cada conexión de escritura y migraciones con `PRAGMA user_version` (ahora 3).

```sh
sqlite3 motor/server/data/mando.db
.tables
.headers on
.mode column
PRAGMA user_version;
```

`motor/server/data/` y cualquier `*.db` / `*.sqlite` están ignorados: una base real puede
contener el relato de una prueba y no se versiona.

Privacidad: nada de teléfonos, tokens ni `chat_id`. Lo reservado solo deja categoría y zona.

## Esquema

```text
escenas
  ├── avisos ──< aviso_incidente >── incidentes
  │                                      ├── planes ──< supuestos
  │                                      ├── acciones ──< llamadas
  │                                      │              └── decisiones
  │                                      ├── previsiones
  │                                      └── partes_personal
  ├── operadores
  ├── servicios_muestras
  ├── golpes
  └── eventos              (log de la partida, huella + ordinal)

sessions                   (una partida / un harness)
  ├── events               (append-only; claves aviso→incidente→plan→acción→llamada)
  ├── episodes             (cierre de una llamada / despacho)
  ├── cerebro_episodes     (un episodio por agente: entrada, contexto, razonamiento, decisión…)
  └── cerebro_lecciones    (propuesta / aprobada / rechazada / revocada + para_agente + evidencia)

pizarra                    (mensajes del enjambre; enlaza + gravedad)
agente_confianza           (aciertos, N, puntuación bayesiana por agente y familia)
adaptacion_eventos         (modo, ritmo, activación)
prompt_versiones           (cuerpo, diff, evidencia, activa, reversible)
especialista_aporte        (n y cambios de la decisión por agente y familia)
```

Todas las tablas de historial llevan `escena_id`. `events` del ledger lleva `session_id` y
las columnas de correlación `aviso_id`, `incidente_id`, `plan_id`, `accion_id`, `llamada_id`.
`cerebro_episodes.agente` es `triaje|prioridad|recursos|avisos|vigia|critico|equipo`.

## Consultas útiles

Las diez del historial siguen igual (escenas, línea de tiempo, incidentes, planes, supuestos,
llamadas, decisiones, recursos). Añadidas:

```sql
-- Correlación aviso → incidente → acción
SELECT incidente_id, aviso_id, plan_id, accion_id, event_type, ts_unix
FROM events WHERE session_id = 's-…' ORDER BY ts_unix;

-- Qué dijo cada agente
SELECT agente, tipo, zona, razonamiento, confianza
FROM cerebro_episodes WHERE session_id = 's-…' ORDER BY ts_unix;

-- Lecciones pendientes de una persona
SELECT id, texto, n, estado, by_who FROM cerebro_lecciones ORDER BY ts_unix DESC;
```

## Lectura desde la interfaz

`/historial` y `GET /api/historial/*` requieren operador. El estado público lleva `agentes`
(por incidente: voto, ejecutado, bloqueado, espera a persona). Detalle: `GET /api/agentes/{id}`.

## Límites

SQLite sirve para la demo y **un solo proceso**. WAL no sustituye copias de seguridad. En
producción se migraría a PostgreSQL conservando tablas y claves; el escritor seguiría
recibiendo el estado público.
