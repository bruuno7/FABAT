# Imagen del MVP de Mando (servidor + motor). No contiene secretos: todo entra por variables de entorno.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY motor/server/pyproject.toml motor/server/uv.lock motor/server/
RUN uv sync --project motor/server --frozen --no-dev
COPY motor motor
RUN python -m motor.cases generate --n 1000 --seed 1 --split heldout --out motor/cases/data/heldout.jsonl
ENV MANDO_PORT=8000
EXPOSE 8000
# Detrás de un proxy con TLS. MANDO_OPERATOR_TOKEN es obligatorio cuando se expone a internet.
CMD ["sh", "-c", "uv run --project motor/server python -m motor.server --case ${MANDO_CASE:-demo-1} --speed ${MANDO_SPEED:-1} --port ${MANDO_PORT} --comms ${MANDO_COMMS:-sim} --lan"]
