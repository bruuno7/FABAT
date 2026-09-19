# Integración y presentación — 19 septiembre

Alcance autorizado: B primero, C después; A se pospone si compromete la entrega.
Sin git salvo las dos lecturas de doctor autorizadas; sin túneles, publicaciones ni secretos.

- [x] B: resolver workflows desde entorno, conservar overrides, cablear ASK/NOTIFY y estado público.
- [x] B: fusionar doctor y sus pruebas de Aibo, conservar compatibilidad de checks y listar URLs.
- [x] B: Telegram poll/send_only/off, misma recogida por chat desde webhook, pruebas con bot falso.
- [x] B: guía de conexión de diez pasos y pruebas de integración contra mocks.
- [x] C: arranque demo, timeouts acotados y rótulos de degradación.
- [x] C: reinicio completo y salto determinista, ensayo con siete hitos repetido tres veces.
- [x] C: autenticación pública, límites por cliente/tamaño, privacidad y regresiones.
- [x] C: lista de comprobación y ejecución completa de servidor y núcleo.

Diseño: ampliar los adaptadores y Session existentes, sin cambiar contratos del núcleo.
Las URLs resueltas no certifican que un workflow esté publicado. Estado y SSE nunca incluyen secretos.
Verificación: unittest con HTTP falso local, ensayos deterministas y comprobación sintáctica de JS.

Resultado: servidor `Ran 138 tests in 59.717s` / `OK`; núcleo solicitado `Ran 83 tests in 0.689s` / `OK`.
Tres ensayos iguales (7/7 hitos), cada uno N=1, críticos fallidos 1/2. A no implementada.
No se han comprobado plataforma, audio ni Telegram reales. Verificación visual pendiente: navegador local bloqueado por permisos.
