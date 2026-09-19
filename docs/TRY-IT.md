# Try MANDO in 2 minutes

For judges and mentors. Everything below uses a **simulated** 40,000-person festival unless your host configured real HappyRobot/Telegram credentials.

---

## 1. Open the control room

**Public URL (team will deploy):** `<PUBLIC_URL>/`

You should see **MANDO · Control room** — live map, incident queue, resource panel, and an **Agent HR** strip. A banner marks *Simulation · fictional venue*.

Optional operator login: `<PUBLIC_URL>/acceso` if the team set tokens.

---

## 2. Send a report (pick one)

### A — Telegram (real channel when the bot is live)

1. Open **`@fabat_happy_bot`** in Telegram.
2. Send location or `/zona gate_b`, then describe what you see — e.g. *“Person unconscious in the pit, not responding.”*
3. You get an acknowledgement and a safety instruction. The bot states this is a **simulation**.

### B — Web (always works on the public URL)

1. Open **`<PUBLIC_URL>/asistente`**
2. Tap a zone on the map (or type one).
3. Submit the same kind of message.

---

## 3. Watch the control room

Within seconds (simulated clock may need **Space** or ▶ if paused):

| What to look for | Where |
|---|---|
| New row in the queue | Center table — gravity pill, sector, status |
| Agent reasoning arriving | Right column · **Agent HR** / swarm messages |
| Decision card | Click the incident — priority, *why*, resources, plan assumptions |
| Plan still valid | Top band: *“The plan still holds”* |
| Plan broken | Top band turns red: **“THE PLAN IS NO LONGER VALID”** + which assumption failed |

Open the **Swarm** tab (if visible) to see specialists messaging each other and peer reviews.

In **HappyRobot** (if the team shares access): workflow **`prueba-ana-equipo`** → **Runs** tab shows the same incident chain (triage → priority → resources → notifications → watcher → critic → `decidir`).

---

## 4. Break the plan (jury)

The jury does **not** use a separate app — `/jurado` redirects to the public assistant.

1. On your phone: **`<PUBLIC_URL>/asistente`**
2. Tab **“Test the system”** / **“Poner a prueba”**
3. Spend one strike — e.g. **Close a gate**, **Storm**, or **Team stops answering**
4. Back on the control room: purple **JURY STRIKE** flash → assumption broken → **new plan** with a written *why*

You get **3 strikes per session** (then HTTP 429). The simulated venue changes; nothing hits the real world.

---

## 5. One-second learning proof (simulation)

On a machine with the repo cloned:

```sh
python3 -m motor.evals aprende --demo
```

**N=1** scenario (restaurant fire). Day 1 sends technician only; an approved lesson is injected; Day 2 sends **technician + security**. Output is labeled **simulation** — not a live festival metric.

Full bank: `python3 -m motor.evals equipo --n 40` → see `motor/evals/out/equipo-agentes.md`.

---

## 6. Optional — veto something grave

1. In the room, press **K** (key moment — loads `demo-1` if sim) or let an incident escalate.
2. When a **decision card** appears (stop show, external help, evacuate): press **V** to **veto**, or **A** to approve.
3. Grave actions need a **second confirm** click — the LLM cannot bypass this.

---

## Quick reference

| URL | Who |
|---|---|
| `<PUBLIC_URL>/` | Control room |
| `<PUBLIC_URL>/asistente` | Public / jury strikes |
| `https://t.me/fabat_happy_bot` | Telegram bot |
| HappyRobot EU editor | `prueba-ana-equipo` runs |

Spanish full manual: [`GUIA.md`](../GUIA.md). This is not an emergency service.
