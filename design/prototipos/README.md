# Prototipos de diseño — MANDO

## Qué es esto

`mando-prototipo.html` es un **prototipo visual estático (mockup)** de la interfaz de MANDO:
un único fichero HTML autocontenido (Tailwind por CDN + un SVG del recinto + JavaScript de
demostración) hecho para **explorar el aspecto** de la interfaz.

- Es la **fuente de diseño**: de aquí se porta el aspecto a la aplicación.
- El **producto es `web/`** (Next.js) junto con su capa de dominio (`web/src/lib/`). Ese es el
  código que se ejecuta y el que manda.
- Este prototipo se conserva en el repo **solo por trazabilidad** (poder volver a mirar de dónde
  salió el diseño). **No forma parte del producto y no se ejecuta**; no se construye ni se despliega.

Para verlo basta con abrirlo en un navegador (no necesita build). Requiere red: carga Tailwind y
las fuentes desde CDN.

## Datos: ficticios y escritos a mano

Todos los datos del prototipo (unidades, incidentes, aforos, estados, posiciones) son **ficticios
y están hardcodeados dentro del HTML** (`verificado`). No provienen del motor MANDO, ni de
HappyRobot, ni de ningún sistema externo.

## Afirmaciones del prototipo que no corresponden al sistema real — pendiente de decisión

> El equipo tiene **pendiente decidir** si se limpian estas afirmaciones del prototipo. No es una
> lista de trabajo obligatorio, y no se prescribe borrarlas.
>
> Lo que sí es criterio firme para quien porte el diseño: **ninguna de estas capacidades debe
> trasladarse a la app como si existiera**. La app debe seguir siendo honesta sobre lo que mide y
> lo que no mide.

| Afirmación en el prototipo | Realidad (`verificado`) |
|---|---|
| «EN TIEMPO REAL · GPS 1Hz» y las balizas móviles con posición | **No hay GPS ni telemetría.** Las posiciones y el movimiento son una animación de demostración sobre un trazado fijo. |
| «ETA 1m 08s · 32%» y el resto de ETAs | **Cifras calculadas por la animación**, no estimaciones reales. El sistema no calcula tiempos de llegada. |
| «Cruce con base de datos de pulseras RFID de menores» | Ese sistema **no existe**. |
| «Llamada automática prioritaria a centralita SUMMA 112» | **No existe**; no hay ninguna integración telefónica. |
| «Resultado Clasificación IA» | En el núcleo de MANDO **no hay IA ni LLM** (decisión explícita del proyecto: reglas deterministas). El prototipo llama «IA» a reglas locales de demostración. |
| «Sincronización en tiempo real con Agente HR» y «Enlace directo» | HappyRobot **no está conectado** en el prototipo. |
| Contadores, gravedades, incidentes y nombres de unidades | **Hardcodeados** en el HTML. |
| «Capa de densidad (estimación)» / personas por m² | **Decorativa**: no hay sensores de aforo. |

**Si se enseña el prototipo a alguien**, hay que decir explícitamente que es un mockup y que esas
capacidades son aspiracionales o ficticias, no funcionalidad del sistema. En un sistema de
coordinación de emergencias, afirmar telemetría o capacidades inexistentes es un problema serio de
credibilidad y, si el sistema llegara a usarse de verdad, de seguridad.

## Accesibilidad — no copiar tal cual al portar

Revisado sobre este fichero con `grep` (`verificado`):

- `::-webkit-scrollbar{display:none;}` (línea 4, dentro del `<style>` del `<head>`): **oculta el
  scroll**. No replicar en la app; rompe la orientación del usuario.
- Desactivación global de la selección de texto: **no** por la propiedad CSS `user-select` (que no
  aparece en el fichero: grep de `user-select`/`userSelect` sin resultados) sino por la **clase
  Tailwind `select-none`**, con el mismo efecto (no se puede seleccionar texto). Se aplica en tres
  sitios: el `<body>` (línea 20), el contenedor principal
  (`<div class="flex flex-col w-full h-[calc(100vh-52px)] overflow-hidden … select-none">`, línea 20)
  y el SVG del recinto (`<svg class="w-full h-full object-contain select-none" id="festival-map-svg" …>`,
  línea 67). No replicar en la app.
- Animaciones decorativas infinitas: el fichero protege **solo** la animación del flujo de los
  trayectos (`.route-active-stream`, `animation: dash-flow 1.2s linear infinite`, línea 12) con
  un guard de `@media (prefers-reduced-motion: reduce) { .route-active-stream { animation: none;
  stroke-dasharray: none } }` (líneas 14–19) y con el chequeo de JS del bucle de simulación
  (`prefersReducedMotion` en la línea 1050, usado en la línea 1061 para no mover las balizas). **No
  están protegidas** las animaciones de Tailwind `animate-pulse` (líneas 20, 46, 550 y 643; además
  el JS añade/quita la clase en las líneas ~1023/~1030) ni `animate-ping` (líneas 33, 243, 261, 279,
  407 y 908): siguen animándose en bucle aunque el usuario pida movimiento reducido. Al portar hay
  que revisar **todas** las animaciones, no solo la que sí tiene guard.
- Dependencias externas en runtime: Tailwind por CDN (`cdn.tailwindcss.com`), Material Symbols y
  fuentes de `fonts.googleapis.com` / `fonts.gstatic.com`. La app no debe depender de un CDN para
  la interfaz.

## Secretos

Revisado antes de commitear (`verificado`): `api_key`, `apikey`, `token`, `secret`, `password`,
`passwd`, `Bearer`, `Authorization`, `HR_SECRET`, `BotFather`, `sk-…`, emails, teléfonos, URLs con
credenciales (`://usuario:clave@`) y nombres reales. **Sin hallazgos**: el fichero solo contiene
datos ficticios de demo. Los únicos hosts externos son los CDN indicados arriba.

## Nota sobre el origen

Este prototipo se generó con ayuda de una herramienta de diseño (su origen exacto queda
`sin verificar`) y se conserva como referencia histórica del aspecto visual. No es una librería ni
un componente del proyecto, y no debe tomarse como código a integrar.
