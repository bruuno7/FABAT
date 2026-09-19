# Base de datos del historial

MANDO guarda en SQLite el mismo estado público y ya enmascarado que entrega `/api/state`. El grabador no
importa objetos del motor: recibe diccionarios, elimina campos de contacto o credenciales como segunda
defensa y hace upserts idempotentes en un hilo propio. Si el disco falla, el reloj continúa.

## Configuración y apertura

- Ruta predeterminada: `motor/server/data/mando.db`.
- Ruta alternativa: `MANDO_DB=/ruta/mando.db`.
- Desactivada: `MANDO_DB=off`.
- SQLite usa WAL, claves foráneas en cada conexión de escritura y migraciones con `PRAGMA user_version`.

```sh
sqlite3 motor/server/data/mando.db
.tables
.headers on
.mode column
PRAGMA user_version;
```

`motor/server/data/` está ignorado: una base real puede contener el relato operativo de una prueba y no
debe versionarse.

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
  └── eventos  (log append-only)
```

Todas las tablas llevan `escena_id`; una referencia repetida en dos reinicios nunca mezcla partidas.
`acciones` conserva minuto inicial, último observado y terminal. `eventos` usa una huella estable más el
ordinal de eventos idénticos: repetir una instantánea no duplica filas, pero dos líneas iguales del log sí
se conservan. Las tablas se crean aunque el estado todavía no exponga previsiones, operadores o partes.

## Diez consultas útiles

1. Últimas escenas grabadas:

```sql
SELECT id, caso, semilla, inicio, fin, fin_min, modo_comunicaciones
FROM escenas ORDER BY inicio DESC LIMIT 10;
```

2. Línea de tiempo para el vídeo:

```sql
SELECT minuto, tipo, texto
FROM eventos WHERE escena_id = 's-…' ORDER BY minuto, huella;
```

3. Incidentes por familia y gravedad, siempre con N:

```sql
SELECT familia, gravedad, count(*) AS n
FROM incidentes WHERE escena_id = 's-…'
GROUP BY familia, gravedad ORDER BY gravedad DESC;
```

4. Tiempo hasta la primera acción:

```sql
SELECT id, etiqueta, primera_accion_min - apertura_min AS minutos
FROM incidentes
WHERE escena_id = 's-…' AND primera_accion_min IS NOT NULL
ORDER BY minutos DESC;
```

5. Qué avisos se fusionaron en cada incidente:

```sql
SELECT x.incidente_id, a.minuto, a.canal, a.fuente, a.texto
FROM aviso_incidente x
JOIN avisos a ON a.escena_id=x.escena_id AND a.id=x.aviso_id
WHERE x.escena_id = 's-…'
ORDER BY x.incidente_id, a.minuto;
```

6. Planes reemplazados y motivo:

```sql
SELECT incidente_id, version, objetivo, porque, sustituye_a
FROM planes WHERE escena_id = 's-…'
ORDER BY incidente_id, version;
```

7. Supuestos que se rompieron:

```sql
SELECT p.incidente_id, s.plan_id, s.texto, s.rotura_min
FROM supuestos s
JOIN planes p ON p.escena_id=s.escena_id AND p.id=s.plan_id
WHERE s.escena_id = 's-…' AND s.estado='roto'
ORDER BY s.rotura_min;
```

8. Resultado y latencia de llamadas:

```sql
SELECT workflow, resultado, count(*) AS n, round(avg(latencia_ms), 1) AS latencia_media_ms
FROM llamadas WHERE escena_id = 's-…'
GROUP BY workflow, resultado ORDER BY workflow, resultado;
```

9. Decisiones humanas y sus dos futuros ensayados:

```sql
SELECT minuto, accion_id, resultado, operador, papel, nota, latencia_s,
       futuro_aprobar_json, futuro_vetar_json
FROM decisiones WHERE escena_id = 's-…'
ORDER BY minuto;
```

10. Actividad y tiempo ocupado por recurso:

```sql
SELECT destinatario AS recurso, count(*) AS acciones,
       min(inicio_min) AS desde_min, max(coalesce(fin_min, ultimo_min)) AS hasta_min,
       sum(max(0, coalesce(fin_min, ultimo_min)-coalesce(inicio_min, ultimo_min))) AS ocupado_min
FROM acciones WHERE escena_id = 's-…'
GROUP BY destinatario ORDER BY ocupado_min DESC;
```

## Lectura desde la interfaz

`/historial` y todos los `GET /api/historial/*` requieren operador. Hay filtros paginados para incidentes,
ficha agregada, decisiones, recursos, servicios y resumen. Las exportaciones por escena son:

```text
/api/historial/export.json?escena=s-…
/api/historial/export.csv?escena=s-…
```

El resumen adjunta `N` a la mediana de primera acción, latencia humana, llamadas y acierto de previsiones.
La interfaz crea nodos con `textContent`; no interpreta texto del público como HTML.

## Límites

SQLite es apropiado para una demo y para **un solo proceso de servidor**. WAL evita que las consultas
bloqueen el escritor, pero no sustituye coordinación distribuida, copias de seguridad ni control de acceso
de base de datos. En producción se migraría a PostgreSQL conservando las tablas, claves compuestas e
índices; el `Recorder` seguiría recibiendo el mismo estado público.
