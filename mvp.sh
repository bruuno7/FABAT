#!/bin/sh
# MVP de Mando en un comando. Uso:
#   ./mvp.sh            arranca la pantalla de mando en local, todo simulado
#   ./mvp.sh lan        igual, accesible desde los móviles de la misma wifi
#   ./mvp.sh real       con HappyRobot y Telegram reales (lee .env)
#   ./mvp.sh demo       doctor previo + caso reproducible, pausado y con plan B
#   ./mvp.sh check      tests de todos los módulos + comprobación de configuración
#   ./mvp.sh cifras     recalcula el titular del banco de pruebas (con N e intervalo)
set -e
cd "$(dirname "$0")"
[ -f .env ] && { set -a; . ./.env; set +a; }
PORT="${MANDO_PORT:-8000}"; CASE="${MANDO_CASE:-demo-1}"; SPEED="${MANDO_SPEED:-1}"
command -v uv >/dev/null || { echo "Falta uv: brew install uv"; exit 1; }
# Los casos grandes no se versionan: se regeneran idénticos con la semilla.
[ -f motor/cases/data/train.jsonl ]   || python3 -m motor.cases generate --n 3000 --seed 1 --split train   --out motor/cases/data/train.jsonl
[ -f motor/cases/data/heldout.jsonl ] || python3 -m motor.cases generate --n 1000 --seed 1 --split heldout --out motor/cases/data/heldout.jsonl
case "${1:-local}" in
  demo) exec uv run --project motor/server python -m motor.server demo --case "${MANDO_DEMO_CASE:-demo-1}" --port "$PORT" ;;
  local) echo "Pantalla de mando:  http://127.0.0.1:$PORT      App del asistente:  http://127.0.0.1:$PORT/asistente"
         exec uv run --project motor/server python -m motor.server --case "$CASE" --speed "$SPEED" --port "$PORT" ;;
  lan)   exec uv run --project motor/server python -m motor.server --case "$CASE" --speed "$SPEED" --port "$PORT" --lan ;;
  real)  [ -n "$MANDO_ALLOWED_NUMBERS" ] || echo "AVISO: sin MANDO_ALLOWED_NUMBERS no se llamará a ningún teléfono."
         uv run --project motor/server python -m motor.server doctor || true
         exec uv run --project motor/server python -m motor.server --case "$CASE" --speed "$SPEED" --port "$PORT" --comms happyrobot --lan ;;
  check) python3 -m unittest motor.world.test_world motor.cases.test_cases motor.mando.test_mando motor.harness.test_harness
         uv run --project motor/server python -m unittest discover -s motor/server -p "test_*.py" -t .
         python3 -m motor.cases check-world motor/cases/data/demo.jsonl
         uv run --project motor/server python -m motor.server doctor || true ;;
  cifras) exec python3 -m motor.harness headline ;;
  *) sed -n '2,8p' "$0"; exit 1 ;;
esac
