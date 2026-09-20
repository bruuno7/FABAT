# MVP histórico: simulador y experimentos

**Este documento ya no es el arranque del producto operativo.** Para ResQval con SQLite persistente, usar [README.md](README.md), [MVP-OPERATIVO.md](MVP-OPERATIVO.md) y `./mvp.sh operational` con canales desactivados en ensayo.

## Dos recorridos que no deben confundirse

| Recorrido | Activación | Estado y finalidad |
|---|---|---|
| Operativo persistente | `MANDO_OPERATIONAL=1` / `./mvp.sh operational` | SQLite de MANDO, `/api/operations/*`, hechos explícitos y auditoría |
| Simulador heredado | Sin `MANDO_OPERATIONAL=1`; `./mvp.sh local` | Mundo sintético, reloj acelerable, `/api/state`, casos y comparaciones de políticas |

Una pantalla legacy no demuestra persistencia de la operación. Una aceptación generada por SimComms no es una llamada atendida. `web/` conserva un prototipo Next con `Map` en memoria: el Dockerfile raíz no lo empaqueta y Vercel raíz construye `puente`. Queda aislado, no es la sala operativa ni debe recibir sus mutaciones/webhooks. Se conserva su código, sin activarlo como segunda autoridad.

## Qué conserva el simulador

- Un mundo de festival de juguete (`motor/world`), catálogo de incidentes y recursos, generador de casos y harness de evaluación.
- Un planificador determinista con reglas, prioridades y supuestos; experimentos de imprevistos, aprobación humana y comparativas contra una política fija.
- Interfaces legacy de explicación: `/asistente`, `/duelo`, `/memoria`, `/caos`, `/informe`, entre otras. Son rutas del servidor legacy, **no una lista de pantallas operativas certificadas**.
- Adaptadores históricos de voz, Telegram y otros canales. Su código o configuración no prueba que todos los workflows estén publicados ni que todos los canales funcionen ahora.

No se mantiene como promesa del MVP que «recoge por todos los canales», «llama de verdad» o «ensaya cada decisión en un gemelo» de forma universal. El plano y los experimentos del recinto no son un gemelo calibrado con un evento real. El modo operativo valida y persiste sus propias transiciones.

## Lanzador y seguridad

Desde la raíz, tras instalar dependencias con `uv`:

```sh
./mvp.sh preflight --seed 1701 --output /tmp/resqval-preflight-nuevo
./mvp.sh check
```

Son los perfiles recomendados de comprobación sin proveedores. `check` genera **SIMULACIÓN train N=3000 y heldout N=1000**, semilla 1, en una copia temporal; ejecuta suites core/server y `check-world` (**SIMULACIÓN N=12 casos demo**). No basta ver corpus generado para declarar que los tests pasaron: manda su código de salida y el resumen de unittest.

Los perfiles siguientes son herramientas legacy; no son el ensayo del producto persistente:

- `./mvp.sh local`: servidor local del simulador si el entorno no activa el operativo.
- `./mvp.sh lan`: expone el servidor a la red; exige revisar permisos, origen y configuración.
- `./mvp.sh demo`: presentación legacy; no equivale al preflight operativo.
- `./mvp.sh real`: lee `.env`, diagnostica y puede contactar proveedores. No usar sin autorización, contactos consentidos y whitelist. `doctor --sin-red` no certifica la conectividad real.
- `./mvp.sh cifras`: recalcula comparativas del harness; no es telemetría de operaciones reales.

Para aislar el legacy, revisar `.env` antes de arrancar: `TELEGRAM_MODE=off`, LLM/cerebro externo desactivados, canales simulados y una ruta `MANDO_DB` nueva. **`MANDO_DB` es el ledger legacy; no reemplaza `MANDO_OPERATIONAL_DB`.** No usar la base de una presentación o de una operación para experimentos.

## Cifras, aprendizaje y evidencia

No se reproducen aquí porcentajes históricos sin un artefacto verificable del árbol actual. Toda cifra futura debe decir **SIMULACIÓN**, su N, semilla, corpus/política, revisión y métrica; las latencias del simulador no son tiempos de llegada de equipos ni latencias telefónicas. Un porcentaje sobre casos sintéticos no mide vidas salvadas.

El harness permite comparar políticas y manuales fuera de línea. No hay evidencia aquí de aprendizaje online autónomo en producción. La adaptación demostrable del operativo consiste en revisar el plan frente a información nueva persistida; aprobar una regla para ensayos posteriores no acredita entrenamiento de un modelo.

Los resultados finales de preflight y suites están pendientes de consolidar sobre la candidata local; no reutilizar recuentos de otra fase como si fueran una validación nueva. La evidencia histórica real es **Telegram → Vercel → Railway → HappyRobot, N=1 llamada telefónica de prueba**, `accept`, destino confirmado y ETA de **2 minutos**, con callbacks aplicados. No corresponde a webcall ni a `followup_question`, y no acredita el SHA/árbol actual.

El rápido operativo tiene un fork adaptado **no publicado/no live**; las pruebas de contrato adjuntas (**SIMULACIÓN N=11 casos de nodos puros y N=7 tests locales**) no validan el agente completo ni reemplazan las regresiones legacy. Estado y bloqueos: [runbook](MVP-OPERATIVO.md#estado-del-workflow-rápido).

El inventario detectó límites de las puertas legacy: `motor.evals` puede devolver cero aunque haya fallos y el harness puede aceptar un conjunto vacío al descartar fixtures obsoletos. Su corte estático de **SIMULACIÓN N=11 fixtures** tenía 0 vigentes y 11 obsoletos, sin ejecutar el harness. Conservar y revisar expectativas; no actualizar huellas automáticamente ni borrar casos para conseguir verde. Ver [pendientes](PENDIENTE.md).

## Documentos de referencia

- [motor/harness/README.md](motor/harness/README.md): evaluación y experimentos sintéticos.
- [motor/INTERFACES.md](motor/INTERFACES.md): contratos compartidos y contexto histórico del simulador; no sustituyen el contrato operativo.
- [motor/server/README.md](motor/server/README.md): servidor operativo frente a rutas legacy.
- [PRESENTACION.md](PRESENTACION.md): guion actual, plan B y afirmaciones permitidas.
- [PENDIENTE.md](PENDIENTE.md): puertas de aceptación, sin fechas de hackathon caducadas.

La documentación de experimentos es contexto histórico, no una garantía de disponibilidad ni un protocolo sanitario validado.
