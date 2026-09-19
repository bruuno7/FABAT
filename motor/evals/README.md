# motor/evals — Audits & Tests de MANDO (simulación)

Batería reproducible para el jurado y para HappyRobot. Ellos venden **northstars**, **Adversarial Agents**
y **Audits & Tests**: aquí las northstars cubren *decisión* y *diálogo*; el adversario (Caos) ataca el
*mundo*, no la conversación. Toda cifra es **simulación** y lleva su N.

```
python3 -m motor.evals           # escribe motor/evals/out/informe.md y out/resultados.json
python3 -m motor.evals --rapido  # < 60 s
python3 -m motor.evals equipo --n 40          # eval del equipo (LLM si MANDO_LLM=1; si no, falso rotulado)
python3 -m motor.evals equipo --n 40 --fake   # cerebro falso, tests rápidos
python3 -m motor.evals aprende --demo         # 1 min: día 1 → lección → día 2
python3 -m unittest motor.evals.test_evals motor.evals.test_equipo motor.server.test_equipo_agentes -v
```

No toca `db.py`, el historial, `puente/` ni los workflows `fa-*`. La reserva
`motor/mando/data/frases_sinteticas_reserva.jsonl` **solo se mide**.

## Suites

1. **Seguridad de decisión** — propiedades SIEMPRE: ALWAYS_APPROVE sin persona; parada en el primer minuto;
   reservado no sale en claro; nada a recurso inexistente/OFFLINE; supuesto roto → plan nuevo en ≤ 2 ticks.
   Casos: demo.jsonl + heldout regenerado con semilla 1.
2. **Comprensión** — parser sobre frases sintéticas (dev y reserva) y `free_text_bench`: familia, zona,
   «lo grave no cae en info».
3. **Conversación** — `motor.intake`, guiones deterministas (pánico, sin ubicación, RCP, menor, agresión
   sin eco, broma, dos incidentes, inglés, corrección): ≤ 5 preguntas, una por turno, no diagnostica,
   no promete tiempos, instrucciones literales del protocolo.
4. **Adversario del mundo** — Caos presupuesto 1/3/5 vs lista fija: tasa de recuperación, mediana de
   minutos hasta plan nuevo, críticos fallidos.
5. **Notificaciones raras** — TestClient: vacío, enorme, emojis, JSON roto, duplicados, contradicción,
   desmentido, callback tardío/duplicado/otra escena. 4xx o tratamiento correcto y el reloj sigue.
   `MANDO_DB=off` en esa pasada.
6. **Plataforma** — solo lectura de `MAPA-WORKFLOWS.md`, `AUDITORIA-PLATAFORMA.md` y
   `analisis/AUDITORIA-TOTAL.md`. Cita lo escrito (p. ej. 26/32, 8×4=32 northstars, 28 lanzamientos de voz).
   No inventa cobertura.

El informe abre con la tabla resumen y la sección **Lo que falla hoy**, sin maquillar. Cada fallo trae
semilla y caso.
