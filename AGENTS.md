# AGENTS.md — dueños por carpeta

| Área | Dueño | Notas |
|------|-------|-------|
| `motor/server` | Ana | Backend MANDO, adaptador HR, puente Telegram |
| `motor/happyrobot` | Bruno | Specs workflows, prompts, northstars, contrato webhook |
| `consejo/` | Consejo / lead | Decisiones de producto y pitch |
| `material/` | Compartido | Docs privadas (no secretos) |
| `buzon/` | Quien edite zona ajena | Dejar nota corta al dueño |

## Reglas

- Cambios en zona de otro → mensaje en `buzon/<dueño>-YYYYMMDD.md`.
- Nunca commitear API keys, tokens BotFather, `HR_SECRET`, passwords.
- No watch hackspain; no submit sin `--draft`.
- No leer código de rivales.
- Datos de pitch: etiquetar `verificado` / `sin verificar`.
