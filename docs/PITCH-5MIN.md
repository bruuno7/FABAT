# 5-minute VC pitch — MANDO

**Audience:** finalist pitch · English · ~5:00 at pace  
**Product:** MANDO — HappyRobot agent swarm + deterministic guardrails + control room  
**Honesty rule:** simulation labeled; every metric carries **N**; market sizes marked *to verify* unless sourced in-repo.

---

## 1. Problem & market (0:00–0:55)

**Problem**  
Mass events drown operators in channels that do not agree. The failure mode is not missing data — it is **late or absent coordination**.

**Proof point (sourced in repo):** Astroworld, 5 Nov 2021 — Houston Police timeline via ABC13: first 911 **21:07**, show ended **22:12** (~**65 minutes** with information, no stop decision). MANDO targets that class of failure.

**Who pays**  
- **Promoters and venue operators** legally required to run **self-protection plans** for outdoor events — e.g. Spain **RD 393/2007** (BOE, cited in `motor/server/exa_pitch.py`).  
- **Stadiums, fairs, multi-day festivals** with medical, security, and logistics stacks already on radio — they pay for **fewer wrong dispatches and faster replans**, not another chatbot.

**Market size** — *to verify*: global live-events production spend and insured liability costs; we have not pinned a TAM in this repo.

---

## 2. Product (0:55–1:45)

**One line:** A **self-correcting swarm** on HappyRobot that runs a **40,000-person simulated crisis**, acts through **real channels**, and **stops trusting its plan** when assumptions break.

**Stack**
- **HappyRobot** — triage, priority, resources, notifications, watcher, critic; orchestrator `prueba-ana-equipo`.
- **This repo** — venue twin, `/hr/tools/*`, **guardrails** (no LLM bypass), control room `/`.
- **Human** — approve/veto evacuate, stop show, external help.

**Not** a rules engine with a voice skin. **Not** fully autonomous — irreversible actions need a person.

---

## 3. Why now (1:45–2:15)

- **Voice and text agents in production** (HappyRobot and peers) — intake and dispatch are deployable today, not a research demo.
- **Regulatory pressure** on event self-protection plans (EU examples above).
- **Insurance and reputational cost** of crowd incidents post-Astroworld / Itaewon (Itaewon timing cited in `exa_pitch.py` — use carefully, verify victim counts before slides).

The missing layer is **multi-agent coordination with replanning and auditability** — that is MANDO.

---

## 4. Demo in 90 seconds (2:15–3:45)

*Screen plan — see `docs/VIDEO-3MIN.md` for beats.*

1. **0:00–0:15** — Telegram `@fabat_happy_bot`: real alert → control room in seconds.  
2. **0:15–0:30** — HappyRobot Runs: swarm chain visible.  
3. **0:30–0:45** — Decision card: priority, why, assumptions.  
4. **0:45–1:00** — Jury strike on `/asistente` → **THE PLAN IS NO LONGER VALID** → replan.  
5. **1:00–1:15** — Veto a grave action; show alternative path.  
6. **1:15–1:30** — `python3 -m motor.evals aprende --demo`: lesson changes day-2 dispatch (simulation, N=1).

Close demo: *“Try `https://mando-fabat.onrender.com` — instructions in `docs/TRY-IT.md`.”*

---

## 5. Traction & validation (3:45–4:15)

**What we can claim (repo evidence, simulation unless noted):**

| Claim | Evidence |
|---|---|
| Guardrails near-perfect | **39/40** at N=40, real LLM eval |
| Beats fixed list / rules on resources | **21/40** and **25/40** baselines vs **32/40** agent |
| Learning changes decisions without regressions | **4/40** changed, **0/40** regressions (eval bank) |
| Backend craft | **561** tests, 293-route smoke — `docs/BACKEND-VERIFIED.md` |
| Workflows published | Seven agent workflows in HappyRobot development (`docs/ESTADO.md`) |

**What we cannot claim yet:** production festival deployment, revenue, or priority quality at scale (**28/40** — known gap).

---

## 6. Business model (hypothesis) (4:15–4:35)

*Hypothesis — not validated in market.*

- **SaaS per event-day** — priced on venue capacity tier + channel bundle (Telegram, voice, SMS).  
- **Implementation** — workflow setup on HappyRobot, twin of venue layout, operator training.  
- **Upsell** — eval harness + regression bank for insurer / municipality audits.

Anchor value: **one prevented mass-casualty incident** vs. license cost — *to verify* with a pilot promoter.

---

## 7. Team (4:35–4:50)

| | |
|---|---|
| **Ana** | Agent architecture, tools, evals, guardrails |
| **Bruno** | Telegram + HappyRobot workflows |
| **Aibo** | Ledger, memory, real comms path |
| **Talía & Firdaous** | Control room, operator UX, film |

Built for **HackSpain 2026** / HappyRobot challenge — FABAT.

---

## 8. Six hard questions (prep answers)

**1. “Isn’t this just ChatGPT with workflows?”**  
No single prompt decides. Six specialists + critic on a blackboard; deterministic guardrails execute separately. Eval: **40/40** valid JSON, **39/40** guardrails — the LLM cannot evacuate alone.

**2. “What if the LLM is wrong on priority?”**  
Honestly: **28/40** at N=40 — our weakest metric. Mitigations: peer review, human veto, degraded rules fallback, continuous eval bank. We show failures in the repo.

**3. “Hallucinated phone numbers / 911?”**  
Whitelist-only `MANDO_ALLOWED_NUMBERS`; NEVER_DIAL list for real emergency lines; external help is a **card**, not a dialer.

**4. “Latency at 40k people?”**  
Design: vital branch dispatches immediately; full swarm in parallel where possible; watcher re-runs only affected agents. Median **~23 s** per scenario in N=40 LLM eval — simulation; production target <60 s end-to-end (*design goal, not certified*).

**5. “Who is liable when the agent messes up?”**  
Grave actions require human approval; audit ledger; lessons human-approved. Product positioning: **decision support**, operator remains accountable — legal framing *to verify* per jurisdiction.

**6. “Why won’t HappyRobot just build this?”**  
HappyRobot is the **runtime and channels**. MANDO is the **venue twin, guardrails, eval discipline, and operator room** — we are a reference stack on their platform, not a competitor to core infra.

---

## 6-line summary

1. Mass events fail when **information exists but nobody coordinates** — Astroworld ~65 minutes, sourced timeline.  
2. MANDO is a **HappyRobot agent swarm** plus a **simulated 40k venue**, twin rehearsal, and a **control room**.  
3. It **replans when assumptions break**; the jury can attack the world from a phone.  
4. **Humans keep evacuate / stop / external help**; guardrails scored **39/40** in simulation (N=40, real LLM).  
5. **Approved lessons** change later decisions; priority still **28/40** — we report that openly.  
6. **Try `https://mando-fabat.onrender.com`** or clone the repo — `docs/TRY-IT.md` — Spanish ops guide in `GUIA.md`.
