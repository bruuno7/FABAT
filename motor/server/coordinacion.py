"""Cuenta de coordinación pura. Minutos humanos = supuesto, nunca medición ni euros."""
from __future__ import annotations

import math
from typing import Any


def summarize(calls: list[dict], reports: list[dict], t: int, *, call_minutes: float = 3,
              message_minutes: float = 1, report_minutes: float = 1) -> dict[str, Any]:
    assumptions = {"call_minutes": call_minutes, "message_minutes": message_minutes, "report_minutes": report_minutes}
    for name, value in assumptions.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 60:
            raise ValueError(f"{name}: usa un número entre 0 y 60")
    unique = {str(c.get("action_id") or c.get("id")): c for c in calls if c.get("action_id") or c.get("id")}
    incoming = {str(r["id"]): r for r in reports if r.get("id") and str(r.get("channel")) != "sensor"}
    n_calls = sum(str(c.get("channel")) in ("voice", "web_call") for c in unique.values())
    n_messages = len(unique) - n_calls
    events, starts, ends = [], [], []
    for c in unique.values():
        start = int(c.get("t", 0))
        end = int(c["t_end"]) if c.get("t_end") is not None else max(start + 1, t)
        # Resolución del registro: un tick. Fin exclusivo; dos llamadas consecutivas no se solapan.
        end = max(start + 1, end)
        events.extend(((start, 1), (end, -1)))
        starts.append(start)
        ends.append(end)
    active = peak = 0
    for _, delta in sorted(events):
        active += delta
        peak = max(peak, active)
    serial_calls = n_calls * call_minutes
    total = serial_calls + n_messages * message_minutes + len(incoming) * report_minutes
    return {"N": len(unique) + len(incoming), "N_sessions": 1, "calls": n_calls, "messages": n_messages,
            "reports": len(incoming), "outbound": len(unique), "peak_simultaneous": peak,
            "peak_N": len(unique), "real_outbound": sum(bool(c.get("real")) for c in unique.values()),
            "simulated_outbound": sum(not c.get("real") for c in unique.values()),
            "elapsed_minutes": max(ends) - min(starts) if starts else 0,
            "serial_call_minutes": round(serial_calls, 2), "serial_minutes": round(total, 2),
            "assumptions": assumptions,
            "assumption": "Minutos por llamada, mensaje y aviso humano: supuesto editable, sin verificar.",
            "note": "Tiempo del recinto simulado; pico de comunicaciones salientes, resolución 1 min. "
                    "Avisos atendidos por el motor sin duración de atención: se cuentan, no se incluyen en el pico. "
                    "Intentos fallidos también cuentan. No mide horas ahorradas en campo."}
