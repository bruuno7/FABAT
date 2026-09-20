#!/bin/sh
# MVP de Mando en un comando. Uso:
#   ./mvp.sh            arranque local legacy; revisar antes el .env privado
#   ./mvp.sh lan        igual, accesible desde los móviles de la misma wifi
#   ./mvp.sh real       legacy con proveedores configurados; requiere autorización
#   ./mvp.sh operational  sala multicanal persistente, proveedores simulados por defecto
#   ./mvp.sh demo       doctor previo + caso reproducible, pausado y con plan B
#   ./mvp.sh check      suites Python y doctor sin red, en copia temporal aislada
#   ./mvp.sh preflight  ensayo operativo sin red; acepta --seed y --output
#   ./mvp.sh cifras     recalcula el titular del simulador (con N e intervalo)
set -e
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "Falta uv: https://docs.astral.sh/uv/"; exit 1; }
# Estos perfiles NO cargan .env ni generan datos en el checkout.
case "${1:-local}" in
  preflight) shift; exec uv run --project motor/server python -m motor.server.preflight "$@" ;;
  check)
    command -v node >/dev/null || { echo "Falta Node >=20 para los checks JS incluidos en Python."; exit 1; }
    node -e 'if (Number(process.versions.node.split(".")[0]) < 20) { console.error("Se requiere Node >=20."); process.exit(1); }'
    exec uv run --project motor/server python -c '
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


def local_sockets_only(event: str, args: tuple[object, ...]) -> None:
    if event == "socket.connect":
        address = args[1]
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1", "localhost"):
            raise OSError("check: red externa bloqueada")


sys.addaudithook(local_sockets_only)
source = Path.cwd()
git_binary = shutil.which("git")
if not git_binary:
    raise SystemExit("Falta Git para fingerprint de los escenarios.")
git_dir = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], check=True,
                         capture_output=True, text=True).stdout.strip()
with tempfile.TemporaryDirectory(prefix="resqval-check-") as temporary:
    root = Path(temporary) / "repo"
    # Conserva fuentes/fixtures; nunca copia secretos, bases ni artefactos locales.
    patterns = shutil.ignore_patterns(
        ".git",
        ".venv", "node_modules", "__pycache__", ".next", ".vercel", ".turbo",
        "*.pyc", "*.log", "*.sqlite*", "*.db", "*.db-*", "*.pem", "*.key",
        "contacts.local.json", "out", "runs", "regression_live",
    )
    def ignore(directory: str, names: list[str]) -> set[str]:
        excluded = patterns(directory, names)
        excluded.update(name for name in names if name.startswith(".env") and name != ".env.example")
        if Path(directory) == source / "motor/server":
            excluded.add("data")
        return excluded

    shutil.copytree(source, root, ignore=ignore)
    fixtures = subprocess.run(
        ["git", "ls-files", "-z", "motor/harness/out"], check=True,
        capture_output=True, text=True,
    ).stdout.split("\0")
    for name in filter(None, fixtures):
        fixture = source / name
        if fixture.is_file() and not fixture.is_symlink():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fixture, target)
    # Los escenarios limpian el entorno pero conservan PATH. El wrapper consulta
    # el checkout fuente sin copiar .git ni permitir refrescos de su índice.
    tools = Path(temporary) / "tools"
    tools.mkdir()
    git_wrapper = tools / "git"
    git_wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(git_binary)
                           + " --no-optional-locks --git-dir=" + shlex.quote(git_dir)
                           + " --work-tree=" + shlex.quote(str(source)) + " \"$@\"\n",
                           encoding="utf-8")
    git_wrapper.chmod(0o700)
    environment = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
    environment["PATH"] = str(tools) + os.pathsep + environment.get("PATH", "")
    os.environ.clear()
    os.environ.update(environment)
    os.environ.update(
        MANDO_OPERATIONAL="0", MANDO_EXTERNAL_DELIVERY="0", TELEGRAM_MODE="off",
        MANDO_COMMS="sim", MANDO_LLM="0", MANDO_CEREBRO="reglas",
        MANDO_DB=str(root / "check-history.sqlite"),
        MANDO_OPERATIONAL_DB=str(root / "check-operations.sqlite"),
        PYTHON_DOTENV_DISABLED="1", GIT_OPTIONAL_LOCKS="0",
    )
    os.chdir(root)
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    from motor.cases.__main__ import main as cases
    from motor.server.doctor import main as doctor

    print("SIMULACIÓN: copia temporal, proveedores desactivados, red externa bloqueada.", flush=True)
    report = root / "doctor.json"
    status = doctor(["--sin-red", "--json", str(report)])
    diagnosis = json.loads(report.read_text(encoding="utf-8"))
    # Ausencias esperadas en este perfil SIN credenciales, no fallos ignorados en producción.
    optional_here = {
        "HR_API_KEY", "HR_SECRET", "HR_WORKFLOW_WEBCALL", "MANDO_PUBLIC_URL",
        "contacts.local.json", "static/vendor/livekit-client.umd.min.js",
    }
    unexpected = [row["clave"] for row in diagnosis["comprobaciones"]
                  if row["estado"] != "ok" and row["nivel"] == "imprescindible"
                  and not (row["clave"] in optional_here and row["estado"] == "falta")]
    ledger_bad = any(row["clave"] == "ledger.sqlite" and row["estado"] != "ok"
                     for row in diagnosis["comprobaciones"])
    if status not in (0, 1) or unexpected or ledger_bad:
        raise SystemExit("Doctor: fallo obligatorio del perfil simulado; no se continúa.")
    if status:
        print("Doctor: faltan solo canales reales opcionales en check; NO acredita despliegue.", flush=True)
    for split, count in (("train", 3000), ("heldout", 1000)):
        print(f"SIMULACIÓN: corpus {split}, N={count}, semilla=1.", flush=True)
        if cases(["generate", "--n", str(count), "--seed", "1", "--split", split,
                  "--out", f"motor/cases/data/{split}.jsonl"]):
            raise SystemExit(1)
    modules = [
        "motor.world.test_world", "motor.cases.test_cases", "motor.cases.test_venue_phrasing",
        "motor.mando.test_mando", "motor.mando.test_victim_identity", "motor.mando.test_closure",
        "motor.harness.test_harness", "motor.harness.test_fixed_corpus",
        "motor.intake.test_intake", "motor.intake.test_location_source", "motor.intake.test_closure",
        "motor.baseline.test_baseline", "motor.protocolos.test_protocolos", "motor.evals.test_evals",
    ]
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    suite.addTests(unittest.defaultTestLoader.discover("motor/server", pattern="test_*.py", top_level_dir="."))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print("SIMULACIÓN: check-world, N=12 casos demo.", flush=True)
    world_status = cases(["check-world", "motor/cases/data/demo.jsonl"])
    raise SystemExit(0 if result.wasSuccessful() and world_status == 0 else 1)
'
    ;;
esac
[ -f .env ] && { set -a; . ./.env; set +a; }
PORT="${MANDO_PORT:-8000}"; CASE="${MANDO_CASE:-demo-1}"; SPEED="${MANDO_SPEED:-1}"
case "${1:-local}" in
  operational) export MANDO_OPERATIONAL=1
         [ -n "${MANDO_OPERATOR_TOKEN:-}${MANDO_OPERATORS:-}" ] || { echo "Configura MANDO_OPERATOR_TOKEN (o MANDO_OPERATORS) en privado."; exit 1; }
         export MANDO_EXTERNAL_DELIVERY="${MANDO_EXTERNAL_DELIVERY:-0}"
         exec uv run --project motor/server python -m motor.server --port "$PORT" ;;
  demo) exec uv run --project motor/server python -m motor.server demo --case "${MANDO_DEMO_CASE:-demo-1}" --port "$PORT" ;;
  local) echo "Pantalla de mando:  http://127.0.0.1:$PORT      App del asistente:  http://127.0.0.1:$PORT/asistente"
         exec uv run --project motor/server python -m motor.server --case "$CASE" --speed "$SPEED" --port "$PORT" ;;
  lan)   exec uv run --project motor/server python -m motor.server --case "$CASE" --speed "$SPEED" --port "$PORT" --lan ;;
  real)  [ -n "$MANDO_ALLOWED_NUMBERS" ] || echo "AVISO: sin MANDO_ALLOWED_NUMBERS no se llamará a ningún teléfono."
         uv run --project motor/server python -m motor.server doctor --sin-red
         exec uv run --project motor/server python -m motor.server --case "$CASE" --speed "$SPEED" --port "$PORT" --comms happyrobot --lan ;;
  cifras) exec uv run --project motor/server python -m motor.harness headline ;;
  *) printf '%s\n' 'Uso: ./mvp.sh [operational|preflight|check|local|lan|demo|real|cifras]'; exit 1 ;;
esac
