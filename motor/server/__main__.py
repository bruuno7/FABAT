"""Arranque: `uv run --project motor/server python -m motor.server --case demo-1 --speed 1`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Cargar .env ANTES de importar .app: HappyRobotComms lee MANDO_VOICE_MODE / HR_* al construirse.
# No pisa variables ya presentes en el entorno (override=False).
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(_env_path, override=False)
except ImportError:
    pass

import uvicorn

from .app import create_app, lan_ip


def main() -> None:
    if sys.argv[1:2] == ["doctor"]:   # python -m motor.server doctor
        from .doctor import main as doctor
        raise SystemExit(doctor(sys.argv[2:]))
    if sys.argv[1:2] == ["cerebro"]:
        from .cerebro_llm import main as cerebro
        raise SystemExit(cerebro(sys.argv[2:]))
    if sys.argv[1:2] == ['ensayo']:
        from .ensayo import main as ensayo
        raise SystemExit(ensayo(sys.argv[2:]))
    if sys.argv[1:2] == ['demo']:
        from .presentation import demo
        demo(sys.argv[2:])
        return
    ap = argparse.ArgumentParser(description="Pantalla de mando (solo red local)")
    ap.add_argument("--case", default="demo-1", help="demo-N, demo-gates o un id de demo.jsonl / heldout.jsonl")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--speed", type=float, default=1.0, help="minutos simulados por segundo real")
    ap.add_argument("--comms", choices=["sim", "happyrobot"], default="sim")
    ap.add_argument("--playbook", choices=["auto", "learned", "seed", "none"], default="auto",
                    help="manual de Mando: auto = el aprendido por el banco de pruebas si existe")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lan", action="store_true", help="escuchar en la red local (móviles del jurado). Nunca internet")
    ap.add_argument("--play", action="store_true", help="arrancar con el reloj en marcha")
    args = ap.parse_args()

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    app = create_app(args.case, seed=args.seed, speed=args.speed, comms_mode=args.comms, autoplay=args.play, port=args.port,
                     playbook=args.playbook)
    print(f"Pantalla de mando:  http://127.0.0.1:{args.port}/")
    if args.lan:
        print(f"Página del jurado:  http://{lan_ip()}:{args.port}/jurado   (QR en /qr)")
    tg = app.state.telegram
    print("Bot de Telegram:    " + ("arrancando (long polling, sin túnel)" if tg is not None else "apagado (falta TELEGRAM_BOT_TOKEN)"))
    uvicorn.run(app, host=host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
