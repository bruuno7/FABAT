# 3-minute video script (judges · San Francisco)

**Format:** 3:00 total · designed for **silent viewing** — every beat has on-screen text.  
**Label:** simulated festival unless a shot explicitly shows a real phone call.  
**Record on real platform** where marked 🎬.

---

## 0:00–0:15 · Hook

| Time | Visual | On-screen text (large) | Voice-over |
|---|---|---|---|
| 0:00–0:03 | Phone: Telegram chat typing | `REAL ALERT` | A real message hits the festival. |
| 0:03–0:07 | Split: phone + control room `<PUBLIC_URL>/` | `3 SECONDS → CONTROL ROOM` | Three seconds later it is in the control room. |
| 0:07–0:11 | HappyRobot Runs tab 🎬 | `SWARM RUNNING` | Six agents are already working. |
| 0:11–0:15 | Room: resource dispatched | `TEAM DISPATCHED` | A team is on the way — no human typed the playbook. |

**Caption bar (whole block):** *MANDO — self-correcting agent swarm for a 40,000-person crisis*

---

## 0:15–0:35 · Problem

| Time | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 0:15–0:22 | Black + timeline graphic | `ASTROWORLD · 5 NOV 2021` `21:07 first 911 · 22:12 show ends` `~65 MIN WITH INFO · NO STOP DECISION` *Source: Houston Police timeline via ABC13* | Information existed. Nobody decided in time. |
| 0:22–0:28 | Crowd stock or simulated map | `40,000 PEOPLE · ONE VENUE · MANY CHANNELS` | One venue. Many channels. One coordination brain. |
| 0:28–0:35 | Logo lock-up | `NOT A CHATBOT` `DECIDE · ACT · REPLAN · LEARN` | Not a FAQ bot — a system that commits and adapts. |

---

## 0:35–1:05 · Swarm at work

| Time | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 0:35–0:45 | 🎬 HappyRobot editor: `prueba-ana-equipo` graph | `TRIAGE → PRIORITY → RESOURCES → NOTIFY → WATCHER → CRITIC` | Specialists as tools, not a fixed chain. |
| 0:45–0:52 | 🎬 Runs: expand one run, tool calls scrolling | `BLACKBOARD + PEER REVIEW` | They read each other and object before acting. |
| 0:52–1:00 | Control room: incident card open | `PRIORITY 9.2` `WHY: visible sentence` `PLAN + ASSUMPTIONS` | Every number has a because. Every plan names what must stay true. |
| 1:00–1:05 | Twin / rehearsal snippet (ensayo) | `REHEARSED IN TWIN — NOT GUESSWORK` | Options compared in a copy of the venue — simulation. |

---

## 1:05–1:35 · Jury breaks the plan

| Time | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 1:05–1:12 | Phone `/asistente` → **Test the system** | `JURY STRIKE · 1 OF 3` | The audience can break the world. |
| 1:12–1:18 | Tap **Close a gate** or **Storm** | `ASSUMPTION BROKEN` | An assumption dies. |
| 1:18–1:25 | Room: red plan band | **`THE PLAN IS NO LONGER VALID`** `OLD PLAN STRUCK · NEW PLAN` | The watcher does not pretend nothing happened. |
| 1:25–1:35 | 🎬 HappyRobot: watcher / re-eval branch OR room log | `WATCHER → REPLAN → REASSIGN` | Re-prioritize. Re-notify. Re-dispatch. |

---

## 1:35–1:55 · Human gate

| Time | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 1:35–1:42 | Decision card: stop show / external help | `GRAVE ACTION` `LLM CANNOT AUTO-RUN` | Evacuate, stop, external help — always a person. |
| 1:42–1:48 | Finger hovers **VETO** | `TWO FUTURES · REHEARSED` | Two futures, side by side. |
| 1:48–1:55 | Press **V** · second confirm | `VETOED · ALTERNATIVE PATH` | The human said no. The system pivots. |

---

## 1:55–2:25 · Learning day 1 → day 2

| Time | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 1:55–2:02 | Terminal: `python3 -m motor.evals aprende --demo` | `SIMULATION · N=1` | One minute, same fire twice. |
| 2:02–2:10 | Terminal output highlight | `DAY 1: tech only` `LESSON APPROVED` `DAY 2: tech + security` | A lesson from yesterday changes today's dispatch. |
| 2:10–2:18 | Room: Learning / Memoria tab if available | `HUMAN APPROVES · REVERSIBLE` | Nothing self-writes without approval. |
| 2:18–2:25 | Text slide | `N=40 BANK: 4/40 decisions changed · 0 regressions · priority unchanged (28/40)` *simulation* | Honest scoreboard — priority still hard. |

---

## 2:25–2:50 · Numbers

| Time | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 2:25–2:35 | Table animate in | `GUARDRAILS 39/40` `JSON 40/40` `RESOURCES 32/40` `PRIORITY 28/40` *N=40 · real LLM · simulation* | Guardrails nearly perfect. Priority still our gap. |
| 2:35–2:42 | Second column | `vs FIXED LIST 21/40` `vs RULES 25/40` | Beats naive baselines on the same alerts. |
| 2:42–2:50 | Backend badge | `561 UNIT TESTS OK` | Craftsmanship in the repo, not just a demo skin. |

---

## 2:50–3:00 · Close

| Time | Visual | On-screen text | Voice-over |
|---|---|---|---|
| 2:50–2:55 | Montage: Telegram → Room → HR Runs | `TRY IT · README · <PUBLIC_URL>` | Try it yourself. |
| 2:55–3:00 | End card | `MANDO` `HappyRobot swarm · human guardrails · learns when you let it` `github.com/…/FABAT-ana` | MANDO — coordination that knows when its plan broke. |

---

## Shots to record on real infrastructure 🎬

1. Telegram message → visible in control room (real bot).
2. HappyRobot **`prueba-ana-equipo`** — Runs tab with tool chain.
3. Web call or Telegram dispatch — staff **Accept** / **Can't** (whitelist phone).
4. Jury strike → red plan band in production URL.

Everything else can be screen capture from `./mvp.sh demo` with *Simulation* banner visible.

---

## Production notes

- Keep **Simulation · fictional venue** visible at least once.
- Never imply Astroworld numbers beyond the sourced 65-minute timeline.
- If audio is on, keep VO short; captions carry the story.
- End QR: `<PUBLIC_URL>/asistente` + repo link.
