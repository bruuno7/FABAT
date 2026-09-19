# Recibos, simulacro y cuenta de coordinación

Simulación del recinto, nunca dato de campo. No cambian contratos ni llaman a la plataforma.

- `recibo.calculate(world, action, accepted=True, minutes=15, later=[], observed=None)`:
  función pura; copia exacta anterior a la decisión con RNG y sucesos programados.
  Quita la acción en el contrafactual, o aplica la propuesta vetada. Mantiene las otras
  órdenes y entradas observadas. Compara picos por zona y llegada del recurso al destino.
  La llegada no acredita disponer de DESA: por eso no se rotula como tiempo hasta DESA.
  Los efectos de varias decisiones NO se suman. Puede haber efectos contrapuestos.
- `ReceiptService`: captura máximo 10 decisiones (prioriza humanas frente a automáticas),
  registra hasta 15 minutos y calcula en un hilo. Publica pendientes, excluidas y censura.
  Sin seguimiento no dice «no cambió nada». Incidentes reservados se excluyen de la salida.
- `SimulacroService`: copia el estado actual y Mando, conecta únicamente SimComms. Su
  gemelo elimina sucesos futuros; reusa `caos.catalogue`, `harness.SimOperator` y `score`.
  Cada golpe se compara con la misma rama sin golpe. N = ataques muestreados de Caos al
  MISMO estado, NO N planes o casos independientes. Se varían oleadas (180/260/340 por min).
  Rotura = supuesto adicional roto, crítico adicional fallido o minutos-zona >5 adicionales.
  Recuperación = primer plan sustituto que se ejecuta, NO incidente resuelto. Mediana solo
  de recuperados, con N y censurados. Conserva errores en el denominador, sin confundirlos
  con éxitos. Semilla fija -> prefijo fijo; cancelación/tiempo -> N parcial explícito.
  Un trabajo a la vez, 60 s / 12 s CPU, cesión cooperativa para 25 % promedio de un núcleo.
- Regresión: `/api/regression/lock` acepta `simulacro_index`. Guarda caso, semilla, entradas
  del prefijo, manual, parámetros y golpe. `run_locked` reconstruye el prefijo y vuelve a
  ensayar, sin sustituir la escena. La condición permanente es cero roturas adicionales;
  un fallo bloqueado sigue fallando hasta que se corrige (no se marca arreglado al guardarlo).
- Coordinación: historial completo de comunicaciones salientes, nunca la vista de las 12
  últimas. Deduplica por action_id. Pico por intervalos [inicio, fin), resolución 1 min.
  Avisos atendidos por el motor: sin duración registrada; no entran en el pico. Sensores
  excluidos del trabajo humano. Se cuentan intentos fallidos; tiempo de llamadas no es ahorro.
  Supuestos editables 0–60 min: 3 por llamada, 1 por mensaje y 1 por aviso, sin verificar.

Pantallas: `/simulacro`; bloque compartido en `/centro` y `/informe`; recibo por incidente.
Rutas de lectura `/api/evidence`, `/api/simulacro/status`; POST start/cancel requieren operador.
`/api/informe` incluye `recibos` y `coordinacion`, sin simulación síncrona en el reloj.

Validación: `motor/server/.venv/bin/python -m unittest motor.server.test_recibo
motor.server.test_simulacro motor.server.test_coordinacion -v`. Sin git ni hackspain.
