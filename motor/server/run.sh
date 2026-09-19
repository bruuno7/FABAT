#!/bin/sh
# Arranca la pantalla de mando desde la raíz del proyecto. Argumentos extra: --case demo-3 --speed 4 --lan --comms happyrobot
cd "$(dirname "$0")/../.." || exit 1
exec uv run --project motor/server python -m motor.server "$@"
