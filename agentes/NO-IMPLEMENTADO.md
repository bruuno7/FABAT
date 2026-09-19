# Lo que no se ha podido hacer, y por qué

Comprobado el **19-sep-2026 entre la 01:53 y las 02:30**, desde esta máquina. Todo lo de abajo son
comprobaciones reales, con su código de respuesta. Si algo cambia (aparece una clave, se recarga
una cuenta), casi nada de esto hay que reescribir: el sistema ya tiene el cliente puesto y solo
hace falta exportar la variable.

## 1 · HappyRobot: la plataforma responde, pero no hay clave

Lo que **sí** quedó comprobado, sin credencial:

| Prueba | Respuesta | Qué demuestra |
|---|---|---|
| `GET platform.eu.happyrobot.ai/api/v2/runs` | `401 {"error":"missing bearer token"}` | La URL base es correcta y la autenticación es **Bearer** |
| `GET platform.eu.happyrobot.ai/api/v2/workflows` | `401 {"error":"missing bearer token"}` | El camino existe |
| `GET mcp.platform.eu.happyrobot.ai/workflows/mcp` | `401 {"error":"invalid_token"}` | El servidor MCP está vivo y pide token |

Eso convierte dos suposiciones del expediente en hechos: la URL y el método de autenticación. Es
poco, pero es más de lo que teníamos, y ahorra la media hora de probar cabeceras a ciegas.

Lo que **no** se ha podido hacer, todo por la misma causa — **no hay `HR_API_KEY` en el entorno de
esta máquina**:

- Leer un `run` real, sus `sessions` o su transcripción.
- Publicar un `signal` contra una llamada viva (`POST /signals`), que es lo que demuestra el
  replanteo en mitad de una conversación.
- Listar los workflows de la cuenta para comprobar si los siete de `WORKFLOWS.md` existen ya.
- Comprobar si el número americano que menciona el founder está asignado.

**Qué hace falta para desbloquearlo.** Una persona exporta la clave y vuelve a lanzar el
diagnóstico. Nada más: el cliente y las llamadas están escritos y probados.

```
$env:HR_API_KEY = "…"          # PowerShell. Nunca en el repositorio.
python -m agentes happyrobot
```

No la he pedido ni la he buscado por el repositorio a propósito: las reglas dicen que las
credenciales son de una persona, y una clave de la plataforma es justo lo que no se pone en un
fichero.

## 2 · Ningún modelo alcanzable: los tres proveedores caídos

| Proveedor | Respuesta | Lectura |
|---|---|---|
| Anthropic | `400 · Your credit balance is too low to access the Anthropic API` | La clave `ANTHROPIC_API_KEY` **existe y es válida**, pero la cuenta de Console no tiene saldo |
| Helmcode | `403 · error code: 1010` | Protección anti-bot de Cloudflare delante de `api.helmcode.com`. Sin clave ni siquiera se llega a la autenticación |
| Compatible OpenAI (AI Gateway, OpenRouter) | falta `AGENTES_LLM_KEY` | No hay ninguna configurada en esta máquina |

Un detalle que conviene no confundir, porque cuesta dinero: `ANTHROPIC_API_KEY` es una clave de
**Console**, que se paga por uso, y **no** es la suscripción Claude Max de Ana. La suscripción no
tiene API: se usa desde la sesión de Claude Code. Cargar saldo en Console sería gasto nuevo, así
que no lo he hecho.

Aunque hubiera saldo, el proveedor de Anthropic **no se elige solo**: hay que pedirlo con
`--proveedor anthropic`. Gastar dinero o cuota es una decisión de una persona.

**Consecuencia sobre el diseño, que resultó ser buena.** Sin ningún modelo, el sistema tenía que
funcionar igual, y eso empujó a que tres de los cuatro agentes sean deterministas y a que el modo
seco entregue el encargo para pegar en Claude Code. Que es, mirándolo con calma, el flujo real del
equipo: una suscripción, una operadora y encargos escritos. Lo que parecía el apaño es lo que se
va a usar.

## 3 · Otras infraestructuras del expediente

- **Cloudflare AI Gateway** — no se ha configurado. Es un proxy con forma de OpenAI, así que el
  cliente `ProveedorOpenAICompat` ya sirve: se apunta `AGENTES_LLM_BASE` a la URL de la pasarela y
  funciona. No lo he hecho porque crear la pasarela es entrar en una cuenta y gastar cuota.
- **Exa** — no integrado. Tiene sentido para verificar datos del pitch, pero no para este sistema:
  aquí las fuentes son ficheros del repositorio, y para eso `ast` es mejor que una búsqueda
  neuronal.
- **Telnyx / número de teléfono** — fuera de alcance. Comprar un número es gasto, y según el
  founder lo cubre HappyRobot: lo pide una persona, no esto.

## 4 · Límites del propio sistema, que no son de acceso

Estos no se arreglan con una clave. Son decisiones tomadas con el reloj en la mano, y conviene que
estén escritas antes de que alguien se lleve la sorpresa:

- **El implementador no aplica parches de verdad, reescribe ficheros completos.** Pide el contenido
  final, no un diff, porque un `diff` mal formado por un modelo es imposible de aplicar y muy fácil
  de generar. El precio es que no sirve para cambios pequeños en ficheros grandes: el modelo tiene
  que devolver el fichero entero.
- **El revisor no ejecuta el `comando_prueba`.** Lo mete en el prompt y lo deja en la traza, pero no
  lanza los tests: ejecutar código recién generado por un modelo sin que nadie lo mire es
  exactamente lo que las reglas no dejan hacer. Lo lanza una persona.
- **La detección de órdenes prohibidas exige que la orden parezca una orden.** Se detecta
  `hackspain submit` al principio de una línea, pero **no** dentro de una cadena como
  `run("hackspain submit")`. Fue necesario: el propio catálogo de reglas cita esas órdenes al
  describirlas, y el revisor se marcaba a sí mismo.
- **La marca `# revisor: ok <motivo>` se puede abusar.** Perdona la línea entera, y nadie comprueba
  que el motivo sea cierto. Lo único que la sostiene es que queda escrita en el diff y anotada en el
  informe: es una convención de equipo, no un control técnico.
- **«División sin guarda» sigue teniendo ruido.** Quedan 37 avisos en `motor/`, y algunos serán
  falsos: saber si un denominador puede ser cero requiere ejecutar el código, no leerlo. Por eso es
  nota y por eso está oculta salvo `--todo`.
- **El analizador solo entiende Python.** De los `.md` saca la primera línea, los dueños y las
  guillotinas, y nada más. El TypeScript del panel no lo mira.
- **No hay integración con `buzon/`.** El sistema no escribe mensajes al buzón cuando un parche toca
  un fichero de otra persona: lo dice en el veredicto y lo escribe una persona. Automatizarlo sería
  editar por encima del trabajo de otro, que es justo lo que el buzón evita.

## 5 · Lo que sí se ha comprobado funcionando

Para que la lista de arriba no dé una impresión equivocada:

- Los 61 tests pasan (`python -m unittest agentes.test_agentes`), sin red y sin gasto.
- El analizador lee el repositorio real: 9 módulos, los dueños de `AGENTS.md`, las guillotinas de
  `MVP.md`, y detecta que el núcleo es solo biblioteca estándar mientras `motor/server` usa FastAPI.
- El revisor encuentra 52 cosas reales en `motor/`, ninguna de ellas un bloqueo, y se aprueba a sí
  mismo (`ACEPTA`, cinco notas) sin excluir su propio fichero de tests.
- La pasada completa deja traza de los cuatro agentes en `agentes/salida/`, con el encargo listo
  para pegar.
- **No se ha tocado nada de `motor/`.** Sus tests siguen igual: 117 recogidos, con el fallo conocido
  de `test_smart_hurts_more_than_random` y el error de importación de `test_server`, que necesita su
  propio `.venv`. Ninguno de los dos viene de aquí.

Durante la construcción, el sistema encontró cinco fallos suyos que estaban de verdad, y esa fue la
mejor prueba de que sirve: se metía en `.venv` y auditaba pydantic; `ContextPack.modulo()` devolvía
`motor` en vez de `motor/server`; se marcaba su propio catálogo de reglas; bloqueaba un
`SECRET = "secreto-de-prueba"` legítimo del repositorio; y metía las clases de test en la «API
pública» que le enseña al implementador. Los cinco están arreglados y con test que lo fija.
