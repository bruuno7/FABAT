# MANDO

**MANDO: a self-correcting swarm of HappyRobot agents that runs a 40,000-person festival crisis — and knows when its own plan has stopped being valid.**

HackSpain 2026 · HappyRobot challenge · team FABAT · **simulated** open-air festival (*Festival Abierto*). In a real emergency, call your local emergency number (112 in Spain).

> Spanish walkthrough: [`GUIA.md`](GUIA.md) · How the agent reasons: [`COMO-DECIDE.md`](COMO-DECIDE.md) · Challenge coverage: [`COBERTURA-RETO.md`](COBERTURA-RETO.md)

---

## The problem

At a packed venue, reports arrive at once: heat exhaustion, a crush risk, a fight, cardiac arrest, a gate that won't open. Treat each alert in isolation and you send two teams to the same spot, leave the worst case uncovered, and keep executing a plan whose assumptions already failed.

**Astroworld, 5 Nov 2021 (Houston):** per the Houston Police timeline reported by [ABC13](https://abc13.com/), the first 911 call was at **21:07** and the show ended at **22:12** — roughly **65 minutes** with information in the system and **no decision to stop the show**. The failure was coordination under uncertainty, not missing sensors.

MANDO is built for that gap: decide with incomplete data, act through real channels, replan when the world moves, and keep a human in charge of irreversible calls.

---

## What it does (five moves)

1. **Ingest** — Telegram, voice, web (`/asistente`), SMS/email (when configured); normalize to structured incidents.
2. **Swarm decide** — HappyRobot specialists (triage, priority, resources, notifications, watcher, critic) debate on a shared blackboard, then commit.
3. **Rehearse & guard** — Twin the venue *now* (no scripted future); deterministic guardrails block evacuate / stop show / external help without a human.
4. **Act** — Dispatch staff (Telegram buttons or voice), write to the ledger, update the control room in real time.
5. **Learn** — Close episodes → proposed lessons with evidence (N) → human approval → changed decisions next day (simulation).

---

## Architecture

```
Channels (Telegram / voice / web / SMS)
        │
        ▼
HappyRobot swarm ──► triage · priority · resources · notifications · watcher · critic
        │                    (blackboard, peer review, learned confidence per agent)
        ▼
This repo: /hr/tools/*  →  guardrails (non-LLM)  →  simulated venue + twin
        │                                              │
        ▼                                              ▼
Real side-effects (calls, messages, ledger)     Control room (/) — approve / veto / lessons
        │
        └──────────────── learning loop (approved lessons → next incident)
```

HappyRobot **orchestrates and reasons**; this repo is the **world, tools, guardrails, and screen**. If the platform times out, the same prompts run on a local LLM, then rules as last resort — always labeled *degraded* in the room.

---

## What makes it different

| Idea | What it means |
|---|---|
| **Anytime option fan** | ≥6 branches per incident (`acciones_posibles`); compare in the twin before choosing — not a fixed playbook. |
| **Two speeds** | Life-threatening dispatch **now**; the swarm reasons the rest (who else to notify, which resource, what to watch). |
| **Self-review** | The watcher asks “does this plan still hold?” on every material change; broken assumptions trigger a visible replan. |
| **Learned agent confidence** | Each specialist earns a score by situation type (with N); the coordinator weights voices that have been right. |
| **Human-approved lessons** | Lessons are proposed with evidence, approved in the room, reversible — and can change the next decision. |
| **Guardrails an LLM cannot bypass** | Evacuate / stop / external help → always a person; whitelist-only destinations; vital dispatch does not wait for debate. |
| **The jury breaks the world** | Anyone on `/asistente` can spend strikes that hit the simulated venue — the swarm must adapt. |

---

## Results (simulation, real LLM)

From `motor/evals/out/equipo-agentes.md` — **N=40** scenarios, **real LLM** (OpenRouter), labeled simulation:

| Metric | Score |
|---|---|
| Guardrails (grave without human; vital in first minute) | **39/40** |
| Priority in expected range | **28/40** |
| Valid resource of expected type | **32/40** |
| Valid JSON (no fake fallback) | **40/40** |
| First resource vs fixed list (light baseline) | **21/40** |
| First resource vs rules baseline | **25/40** |

**Learning day 1 → day 2** (same N=40 scenarios, deterministic eval brain — simulation): **4/40** decisions changed, **1/40** errors not repeated, **0/40** regressions; **priority did not improve** (28/40 both days); resources 29/40 → 30/40. Example lesson: restaurant fire → send technician **and** security together.

Reproduce: `python3 -m motor.evals equipo --n 40` · one-minute demo: `python3 -m motor.evals aprende --demo`

Backend smoke: **561** unit tests OK (`docs/BACKEND-VERIFICADO.md`).

---

## Try it in 2 minutes

Judges: **[`docs/TRY-IT.md`](docs/TRY-IT.md)** — public control room, Telegram bot, break the plan, learning demo.

---

## Run locally (3 commands)

Python ≥3.12 and [`uv`](https://docs.astral.sh/uv/). From repo root; without `.env` everything is simulated and labeled.

```sh
cp .env.example .env    # optional — secrets stay local
./mvp.sh                # Control room http://127.0.0.1:8000/ · public /asistente
./mvp.sh check          # unit tests + doctor
```

`./mvp.sh demo` — paused scene for presenting. `./mvp.sh real` — HappyRobot + Telegram when `.env` is filled. `./mvp.sh lan` — same on Wi‑Fi (QR at `/qr`).

---

## Real vs simulated

| | Real (with credentials) | Always simulated |
|---|---|---|
| Venue, crowd, weather, clock | — | Yes |
| Who decides | HappyRobot agent swarm (or local LLM fallback) | Rule engine only if degraded — shown in red |
| Public reports | Telegram `@fabat_happy_bot`, `/asistente` | Eval banks |
| Staff dispatch | HappyRobot voice / Telegram to **whitelist** numbers | `SimComms` — banner says so |
| Grave actions | Human approve/veto in the room | Simulated operator in evals |
| Metrics above | — | Simulation; every N stated |

Never dials a real emergency line. Secrets only in `.env` (public repo).

---

## Honest limitations

- **Priority is still weak** (28/40 at N=40) — the main open quality gap.
- **The festival is fiction** — all venue numbers are simulation unless marked otherwise.
- **HappyRobot runs** need a configured tunnel (`MANDO_PUBLIC_URL`), API keys, and published workflows; platform outages have blocked live triggers during development.
- **Voice/Telegram** are optional; default `./mvp.sh` is fully offline-simulated.
- **Learning** improves some resources, not priority yet; lessons require human approval.
- **`/jurado`** redirects to `/asistente` (strikes live under “Test the system”).

---

## Team

| Person | Focus |
|---|---|
| **Ana** | Agent brain, tools, re-evaluate, learn, evals, repo hygiene |
| **Bruno** | Telegram bridge & HappyRobot `fa-*` workflows |
| **Aibo** | Ledger, memory, real voice path |
| **Talía & Firdaous** | Control room UX, reasoning & lessons visible, video |

Built for the HappyRobot challenge at HackSpain 2026. Tools contract: [`motor/happyrobot/cerebro/HERRAMIENTAS.md`](motor/happyrobot/cerebro/HERRAMIENTAS.md).
