"""Cliente LLM inyectable en CascadeParser (Helmcode / Cloudflare AI Gateway / Vercel).

No llama a la red salvo que haya clave Y `MANDO_LLM=1`. El núcleo del motor sigue sin importar
APIs: este módulo vive en el servidor y fabrica un `client(prompt)->str` para `LLMParser`.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable


def llm_configured() -> tuple[bool, str]:
    """¿Hay clave y se ha pedido encender el LLM en demo? No prueba la red."""
    key = (os.environ.get("AGENTES_LLM_KEY") or os.environ.get("HELMCODE_API_KEY") or "").strip()
    base = (os.environ.get("AGENTES_LLM_BASE") or "https://api.helmcode.com/v1").rstrip("/")
    on = os.environ.get("MANDO_LLM", "").strip().lower() in ("1", "true", "yes", "on")
    if not key:
        return False, f"sin AGENTES_LLM_KEY/HELMCODE_API_KEY (base sería {base})"
    if not on:
        return False, f"clave presente; pon MANDO_LLM=1 para usarla en demo ({base})"
    return True, f"MANDO_LLM=1 → {base}"


def _chat(prompt: str, *, base: str, key: str, model: str, timeout_s: float = 25.0) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 400,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "Devuelve solo JSON válido del esquema pedido. Sin markdown."},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"HTTP {ex.code}: {detail}") from ex
    except urllib.error.URLError as ex:
        raise RuntimeError(f"red: {ex.reason}") from ex
    choices = data.get("choices") or [{}]
    return str((choices[0].get("message") or {}).get("content") or "")


def make_client() -> Callable[[str], str] | None:
    """Devuelve cliente o None si no debe usarse LLM (sin clave o MANDO_LLM apagado)."""
    ok, _ = llm_configured()
    if not ok:
        return None
    base = (os.environ.get("AGENTES_LLM_BASE") or "https://api.helmcode.com/v1").rstrip("/")
    key = (os.environ.get("AGENTES_LLM_KEY") or os.environ.get("HELMCODE_API_KEY") or "").strip()
    model = os.environ.get("AGENTES_LLM_MODEL") or "deepseek-v4-flash"

    def client(prompt: str) -> str:
        return _chat(prompt, base=base, key=key, model=model)

    return client


def build_cascade_parser() -> Any | None:
    """CascadeParser(heurístico, LLM) si MANDO_LLM=1 y hay clave; si no, None (Mando usa heurístico)."""
    client = make_client()
    if client is None:
        return None
    from motor.mando.parser import CascadeParser, HeuristicParser, LLMParser
    rules = HeuristicParser()
    return CascadeParser(rules, LLMParser(client=client, fallback=rules))


def status_for_doctor() -> dict[str, str]:
    key = bool((os.environ.get("AGENTES_LLM_KEY") or os.environ.get("HELMCODE_API_KEY") or "").strip())
    base = (os.environ.get("AGENTES_LLM_BASE") or "https://api.helmcode.com/v1").rstrip("/")
    on = os.environ.get("MANDO_LLM", "").strip().lower() in ("1", "true", "yes", "on")
    gw = "cloudflare" if "cloudflare" in base else ("vercel" if "vercel" in base else "helmcode_direct")
    return {
        "key_set": "yes" if key else "no",
        "mando_llm": "on" if on else "off",
        "base": base,
        "gateway": gw,
        "model": os.environ.get("AGENTES_LLM_MODEL") or "deepseek-v4-flash",
    }
