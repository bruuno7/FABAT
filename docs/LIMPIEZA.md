# Limpieza (19-sep-2026) — qué se movió y cómo deshacerlo

Nada se ha borrado. Lo que no entra en la demo vive en `archivo/` **con la misma ruta relativa**. El servidor ya no carga esos HTML: las URLs antiguas redirigen a `/` (Sala). APIs (`/api/duel/*`, `/api/memoria`, `/api/historial/*`, `/api/personal/*`, `/api/simulacro/*`, `/api/explica`) siguen.

No se ha tocado: `motor/server/static/sala*`, `motor/server/memoria_db.py`, cerebro/tools (`cerebro.py`, `cerebro_llm.py`, `cerebro_tools.py`, `motor/happyrobot/cerebro/`, `motor/happyrobot/equipo/`), `puente/src`.

## Cómo deshacer (un bloque)

Desde la raíz del repo:

```sh
mv archivo/agentes agentes
mv archivo/web web
mv archivo/design design
mv archivo/MVP.md archivo/PENDIENTE.md archivo/LEEME-COMPARTIR-EQUIPO.txt .
mkdir -p motor/server/static motor/evals/out
mv archivo/motor/server/CENTRO.md archivo/motor/server/PENDIENTE.md archivo/motor/server/PLAN-BC.md archivo/motor/server/telegram_espejo.py motor/server/
mv archivo/motor/server/static/* motor/server/static/
mv archivo/motor/evals/out/* motor/evals/out/
```

Después habría que restaurar a mano las rutas de `app.py` / `team_routes.py` / `historial_routes.py` / `evidence_routes.py` que ahora redirigen (están en el historial de la rama).

## Listado exacto (origen → `archivo/` + misma ruta)

### Árboles enteros
- `agentes/` → `archivo/agentes/` (apoyo al desarrollo, no producto; nadie del servidor lo importaba)
- `web/` → `archivo/web/` (Next.js; `/api/board` es local, no el backend MANDO)
- `design/` → `archivo/design/` (prototipo HTML/PNG)

### Raíz
- `MVP.md` → `archivo/MVP.md`
- `PENDIENTE.md` → `archivo/PENDIENTE.md`
- `LEEME-COMPARTIR-EQUIPO.txt` → `archivo/LEEME-COMPARTIR-EQUIPO.txt`

### Documentos y módulo muerto del servidor
- `motor/server/CENTRO.md` → `archivo/motor/server/CENTRO.md`
- `motor/server/PENDIENTE.md` → `archivo/motor/server/PENDIENTE.md`
- `motor/server/PLAN-BC.md` → `archivo/motor/server/PLAN-BC.md`
- `motor/server/telegram_espejo.py` → `archivo/motor/server/telegram_espejo.py` (no lo importaba nadie; el vivo es `espejo_telegram.py`)

### Pantallas y JS/CSS que ya no son la interfaz
Todo de `motor/server/static/` → `archivo/motor/server/static/`:

`app.js`, `ASISTENTE-PENDIENTE.md`, `caos.html`, `centro-equipo.css`, `centro-equipo.js`, `centro.css`, `centro.html`, `centro.js`, `curva.html`, `duelo.html`, `duelo.js`, `evidence.css`, `evidence.js`, `FRONT-PENDIENTE.md`, `historial.css`, `historial.html`, `historial.js`, `index.html` (vista clásica), `informe.html`, `interaction.js`, `memoria.html`, `memoria.js`, `pages.css`, `personal.css`, `personal.html`, `personal.js`, `simulacro.css`, `simulacro.html`, `simulacro.js`, `test_centro.cjs`

Se quedan en `static/`: `sala*`, `asistente*`, `jurado*`, `llamada*`, `ui.js`, `plano.js`, `style.css`, `chat-tab.js`, `pulseras.json`.

### Salida generada
- `motor/evals/out/informe.md` → `archivo/motor/evals/out/informe.md`
- `motor/evals/out/resultados.json` → `archivo/motor/evals/out/resultados.json`

`motor/harness/out/` y `*.db` ya estaban fuera de git (`.gitignore`); no se han movido porque el servidor lee `playbook.learned.json` de ahí si existe.

## Ajustes de código (para que lo archivado no se cargue)

- `app.py`: solo sirve `/`, `/sala`, `/jurado`, `/asistente`, `/llamada`. `/centro` `/clasico` `/curva` `/caos` `/memoria` `/informe` `/duelo` (este llama `D()` para la API) contestan un aviso HTML 200 generado en código, sin leer `archivo/`.
- `team_routes.py` `/personal`, `historial_routes.py` `/historial` (sigue exigiendo operador), `evidence_routes.py` `/simulacro`: igual, aviso 200; las APIs no se tocan.
- Tests de páginas: comprueban el aviso, no el HTML viejo.
- `./mvp.sh check` no lee `.env` (túnel, tokens y `MANDO_DB` de la demo contaminaban la batería).

`archivo/README.md` resume el porqué.
