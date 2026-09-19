# FABAT — MANDO (HackSpain 2026, reto HappyRobot)

Para cualquier persona o agente de IA que abra este repo. Este repo es **público**.

1. **Ningún secreto en el repo**: API keys, tokens de Telegram, teléfonos reales, códigos de acceso. Van en `.env` o en `motor/server/contacts.local.json` (ambos ignorados por git).
2. No ejecutar `hackspain watch` ni `hackspain submit` sin `--draft` hasta la entrega final.
3. Nunca se marca un número de emergencias real ni un teléfono fuera de la lista blanca (`MANDO_ALLOWED_NUMBERS`).
4. Toda cifra de simulación lleva su N y dice que es simulación.
5. `git pull --rebase` antes de tocar nada; commits pequeños; si tocas una carpeta que no es tuya, avisa al equipo.

Empieza por `README.md` (qué es y cómo arrancar), `GUIA.md` (cómo se usa) y `docs/PLAN-GIRO.md` (diseño: el equipo de agentes decide). Inventario: `docs/INVENTARIO.md`.
Contrato entre módulos: `motor/INTERFACES.md` y `motor/contracts.py` (no se cambian sin avisar). Cada carpeta de `motor/` tiene su README.
`puente/` es la puerta pública en Vercel (Telegram y callbacks de HappyRobot → backend). Lo que ya no es la demo está en `archivo/` (no se borra).
