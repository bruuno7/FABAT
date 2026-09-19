# Centro de control

Pantalla nueva: `/centro`. La pantalla `/` conserva sus controles y sirve de alternativa.
`centro.html`, `centro.css` y `centro.js` usan solo recursos locales (`ui.js` y `plano.js`).
No se carga `interaction.js`: depende de los elementos de la pantalla anterior.

## Diseño

Paleta y tipografía: primer bloque `:root` en `static/centro.css`. El bloque
`[data-theme=dark]` define el tema oscuro; el claro es el predeterminado. Cambiar
`--font`, `--headline`, `--radius` y las variables de color. No descargar fuentes.
Las cuentas atrás, respuestas de llamada y SUPUESTO ROTO tienen estilos propios.
Falta revisión visual humana en el portátil/proyector del vídeo: el entorno de
Codex ha denegado la navegación a la demo local.

Espacio pausa/reanuda, S avanza, K salta al momento clave, R reinicia. A/V actúan
sobre la decisión visible del incidente seleccionado. Una evacuación preparada
exige escribir una nota que empiece por EVACUAR. Los controles usan la sesión de
operador existente: acceso en `/acceso`, sin almacenar tokens en la pantalla.
Solo se ofrece mensaje de cambio de orden cuando hay una llamada real que admite
intervención; no hay un endpoint para iniciar una llamada arbitraria al equipo.

## Previsión del gemelo

`forecast.py`: función pura sobre `World.twin()`, sin acciones nuevas. Primer cruce
por zona/recurso/métrica/umbral. Densidad ≥4 y ≥5 /m²; agua ≤0 L; unidades libres
médicas, ambulancia o seguridad ≤0; pérdida de una ruta desde una ambulancia hasta
un puesto médico o salida de transporte, usando la regla real del simulador.
No es una garantía clínica ni una previsión meteorológica.

El worker calcula fuera del cerrojo del reloj; la copia del gemelo se captura bajo
el cerrojo. Máximo una generación cada tres ticks; si supera 150 ms se duplica el
intervalo, hasta 24 ticks. Se observan los umbrales en cada reconstrucción de estado.
El historial conserva 256 episodios y 64 observaciones. No se mueve el plazo de una
previsión al recalcularla; nuevos episodios tienen sufijo de minuto.

- PREVISTO: cuenta atrás hasta el cruce estimado; después, «En observación».
- CUMPLIDO: se observó el umbral dentro de los 15 min.
- EVITADO: no hubo cruce durante los 15 min y existe intervención pertinente. El
  plan asociado se indica, pero la atribución es temporal, no una prueba causal.
- NO CUMPLIDO: no hubo cruce ni intervención registrada. No se cuenta como evitado.
- NO VERIFICABLE: faltan observaciones de esa ventana. No se cuenta como evitado.

Los servicios diferencian simulado, configurado sin verificar, operativo con evento,
degradado y caído. `voice_down` usa el plazo de caída del mundo, por lo que desaparece
al recuperarse el canal. Los errores históricos de HappyRobot siguen visibles.
No se inventa latencia ni se verifica la plataforma mediante llamadas adicionales.

## Medición

`python3 -m motor.harness forecast --n 200` escribe `motor/harness/out/forecast.json`.
Partición heldout, semilla 20260919, índices desde 700000; no hay agente ni acciones.
El mundo conserva sus sucesos futuros; el gemelo no los ve. La precisión se evalúa
por cruce en la ventana de 15 min, no por acertar el minuto exacto de la cuenta atrás.
Un cruce solo puede emparejarse con una previsión. Los dos umbrales de densidad
cuentan por separado. IC 95 % por bootstrap de casos. Se conservan también conteos
por métrica, ventanas censuradas, errores de ETA y huellas de código y casos.

Límite: el gemelo conoce las ecuaciones del simulador. Los resultados no validan
predicción de campo. En la muestra inicial N=200, los avisos de agua y disponibilidad
son sucesos futuros no anticipados: no ocultar sus falsos negativos.

## Cifra incorporada en MVP.md

**Verificado en simulación, N = 200 casos heldout nuevos:** 28 de 32 previsiones
con seguimiento completo se cumplieron en su ventana de 15 min: **precisión 87,5 %
[IC 95 %: 74,3–96,9]**, **exhaustividad 59,6 % [44,2–72,6]** sobre 47 cruces reales,
y **antelación mediana 7,5 min [4–13]** entre los 28 aciertos. Se censuraron 12
previsiones sin seguimiento completo. Fuente reproducible: `harness/out/forecast.json`;
IC por remuestreo de casos. **Límites:** el gemelo conoce la dinámica del simulador;
no es evidencia de campo ni prueba causal de daños evitados. No conoce sucesos
futuros del caso: en esta muestra no anticipó 8 roturas de agua ni 11 agotamientos
de recursos. La precisión mide cruce dentro de 15 min, no el minuto exacto anunciado.

## Integración aplicada tras recibir `arreglos.fin`

La integración se aplicó después de comprobar esta señal con `ls`:
`/private/tmp/claude-501/-Users-anayang-workspace-hackspain-2026/33b883d3-f777-44a1-b0cb-7e6d71495c0a/scratchpad/arreglos.fin`.
Se releyó `app.py` justo antes de editarlo. No se ejecutó git. Estos son los puntos de integración:

1. Importar `ForecastService` de `.forecast` en `app.py`. En `Session.__init__`,
   inicializar `self._forecast = None` antes del primer `_rebuild`; dentro de
   `if threaded`, crear `self._forecast = ForecastService(self)`. No crear worker
   en los ensayos sin hilos; así se conserva su determinismo.
   El control K también crea el worker después de `prepare_key_moment`, cuando
   arranca el reloj de la nueva sesión; hay una regresión específica para este caso.
2. En `_rebuild`, después de construir/proyectar `self._state` y antes de serializar:
   llamar `self._forecast.observe()` si existe (necesita el estado recién construido),
   y asignar `self._state['forecasts'] = self._forecast.view() if self._forecast else []`.
   El worker hace los ensayos fuera del cerrojo y llama `_rebuild` para publicarlos.
   Añadir en ese estado `service_health: {comms_down: dict(self.world.comms_down)}`
   para la caída/recuperación, y `event_name: self.festival.get('name')`.
3. En `Session.close`, llamar `self._forecast.close()` si existe. Agregar
   `'/centro': 'centro.html'` al diccionario `pages`. Son datos comunes de API/SSE.
4. En la navegación existente de `static/index.html`, un enlace a `/centro`;
   no cambiar el JavaScript ni los atajos de `/`.
5. En `motor/harness/__main__.py`, justo después de obtener `argv` en `main`:

   ```python
   if argv[:1] == ['forecast']:
       from .forecast_bench import main as forecast_main
       return forecast_main(argv[1:])
   ```

   El benchmark no usa git ni el preflight de otros comandos. Ejecutar entonces
   `python3 -m motor.harness forecast --n 200` y copiar el párrafo anterior a MVP.md.
6. Verificar `/centro` y `forecasts` tanto en `/api/state` como en el SSE con
   TestClient, probar cierre del worker y caída/recuperación de voz. Después, la
   suite completa y el arranque/curl del encargo cuando el entorno permita sockets.

## Verificación local

Las 20 pruebas nuevas de previsiones, benchmark e integración pasan; `/centro`
responde 200 por ASGI y API/SSE contienen `forecasts`. Incluyen fallo del worker,
recuperación de voz y reinicio con K. Pasan `node --check` y las pruebas de lógica
de `test_centro.cjs`. Tres ensayos `demo-1` producen salida idéntica y `ok: true`.
La suite compartida tiene pruebas de otros trabajos aún pendientes de integración;
el informe final está en el mensaje del buzón sobre centro-previsiones.

El arranque solicitado con `./mvp.sh demo`, puerto 8768 y comunicaciones simuladas,
se intentó y falló por `PermissionError` al abrir el puerto. No se pudo hacer el
curl ni la revisión visual. El navegador también rechazó automáticamente abrir
la demo local porque el acceso figura denegado por el usuario; no se intentó
sortearlo. Log del arranque: `/private/tmp/mando-centro-demo-launch.log`.
