# `agentes/` — sistema multiagente de apoyo

Cuatro agentes que preparan, escriben y revisan el trabajo sobre este repositorio. No tiene nada
que ver con «Mando»: Mando gestiona la crisis del festival y es el producto. Esto es la herramienta
con la que trabajamos nosotros, y vive aparte a propósito para no mezclarse con `motor/`.

Solo biblioteca estándar. Se ejecuta desde la raíz del repositorio, como todo lo demás.

```
python -m agentes doctor      # qué hay disponible y qué no
python -m agentes analizar    # agente 1: el contexto del repositorio
python -m agentes revisar motor/mando
python -m agentes pipeline --objetivo "…" --ficheros "a.py,b.py" --prueba "python -m unittest …"
python -m agentes happyrobot  # sonda de la plataforma
```

## Los cuatro

| Agente | Fichero | Qué hace | ¿Modelo? |
|---|---|---|---|
| **Context Analyzer** | `analizador.py` | Recorre el repositorio con `ast`: módulos, API pública, dueños, dependencias, reglas y guillotinas | no |
| **Prompt Architect** | `arquitecto.py` | Monta el prompt de sistema especializado para ese encargo y esa acción | no |
| **Implementer** | `implementador.py` | Pide el código y lo convierte en ficheros propuestos | **sí** |
| **Code Reviewer** | `revisor.py` | Sintaxis, límites, seguridad y casos límite | no |

Tres de los cuatro son deterministas, y no es por ahorrar: es la misma decisión que en el motor.
Un analizador que «resume el repositorio» con un modelo **inventa módulos que no existen**; un
`ast.parse` no. Y un revisor que a veces aprueba y a veces no el mismo código no es una puerta, es
una opinión. El modelo va donde hay lenguaje: escribir código. Lo demás se calcula.

Efecto lateral que resultó ser el importante: los tres agentes deterministas **no gastan cuota**.
Con una sola suscripción para cinco personas, eso es lo que hace que el sistema se pueda usar.

## El modo seco

Por defecto no hay llamada a ningún modelo. El implementador devuelve el **encargo listo para
pegar** en una sesión de Claude Code: el bloque de sistema y el bloque de encargo, ya montados.

No es un apaño para cuando falla la red, es el modo previsto. El flujo real del equipo es una
suscripción y una operadora, así que lo que hace falta a escala no es otra tubería que gaste cuota,
es el encargo bien escrito. Y el día que haya una clave, el mismo `pipeline` la usa con
`--proveedor`.

## El encargo

Todo entra por un `Encargo`, y son tres campos, no uno:

```python
Encargo(
    objetivo="registrar el aforo por sector en cada tick",
    ficheros_permitidos=["motor/world/sim.py"],       # la valla
    comando_prueba="python -m unittest motor.world.test_world",  # el examen
)
```

`Encargo.valido()` se queja si falta alguno. Sin la valla, el agente toca cualquier cosa; sin el
comando de prueba, dice que ha terminado y no hay forma de saberlo. Los dos son el mismo error
cometido dos veces, y los dos se pagan a las tres de la mañana.

## Lo que mira el revisor

Cuatro pasadas, en el orden en que conviene fallar: **sintaxis** (`ast.parse`), **límites** (la
valla, el tamaño, los contratos congelados), **seguridad** (credenciales, teléfonos reales,
`eval`, `shell=True`, órdenes prohibidas del evento) y **casos límite** (`except` pelado, red sin
`timeout`, argumento por defecto mutable, reloj o azar dentro del núcleo determinista).

El veredicto sale de los avisos por una regla fija, no de un juicio: algo que bloquea → `RECHAZA`;
algo grave → `ESPERA A UNA PERSONA`; solo avisos → `ACEPTA CON AVISOS`. Y cada aviso lleva **su
fuente**, un fichero que se puede abrir. El catálogo está en `reglas.py`.

Sobre el repositorio real encuentra 52 cosas, y ninguna es un bloqueo: seis llamadas de red sin
`timeout` en `test_server.py`, ocho errores que se descartan en silencio y 37 divisiones por algo
que puede valer cero. Las notas se enseñan con `--todo`.

### La salida de emergencia

Una línea se puede perdonar, **con motivo obligatorio**:

```python
JEFE = "+34612345678"  # revisor: ok teléfono inventado para el test del escáner
```

Sin motivo no vale. Obligar a escribir por qué es lo que separa una excepción justificada de un
«cállate», y queda en el diff para que alguien la discuta. La excepción no desaparece: se anota
como nota con su motivo, así que se puede auditar después.

### Tres cosas que aprendimos construyéndolo

Están en el código como comentario, porque van a volver a morder a alguien:

- El revisor **se marcaba a sí mismo**: el catálogo de reglas cita las órdenes prohibidas, así que
  detectaba «`hackspain watch`» dentro de la frase que lo prohíbe. Por eso esos patrones exigen que
  la orden **parezca una orden** y no una frase que la mencione.
- La primera versión de «división sin guarda» daba 131 avisos en `motor/`, ninguno accionable. Una
  regla con ese ruido enseña a no leer el informe. Estrechada a `len(...)`, `sum(...)` y nombres de
  contador, quedan 37.
- Bloqueaba `SECRET = "secreto-de-prueba"`, que existe de verdad en `motor/server/test_server.py`.
  Un escáner que bloquea por eso se desactiva el primer día, y eso es la forma segura de que no
  encuentre el que sí importa. Ahora lo que tiene **forma** de credencial real bloquea siempre, y
  una variable llamada `SECRET` con un literal dentro solo avisa.

El revisor se revisa a sí mismo en los tests, sin excluir nada: si no aprueba su propio paquete, no
tiene autoridad para revisar el de nadie. Ahora mismo sale `ACEPTA` con cinco notas.

## HappyRobot

`happyrobot.py` es el cliente del clúster EU para uso de la herramienta: `runs`, `sessions`,
`signals` y el diagnóstico. **No sustituye a `motor/server/comms_happyrobot.py`**, que es el
operativo y el que usa la demo; usa las mismas variables (`HR_API_BASE`, `HR_API_KEY`) para que no
haya dos convenciones.

Comprobado desde este repositorio el 19-sep a la 01:55, sin clave:

```
GET https://platform.eu.happyrobot.ai/api/v2/runs   →  401 {"error":"missing bearer token"}
```

Eso convierte dos suposiciones del expediente en hechos: **la URL base es correcta** y **la
autenticación es Bearer**. Lo que no se ha podido comprobar es ninguna respuesta con datos, porque
no hay `HR_API_KEY` en esta máquina. El detalle está en `NO-IMPLEMENTADO.md`.

El diagnóstico avisa si `HR_API_BASE` no apunta a `.eu.`, que es el fallo número uno documentado:
con el clúster equivocado la misma clave responde 401 o 404 y se pierde media hora buscándolo en
el sitio equivocado.

## Tests

```
python -m unittest agentes.test_agentes -v
```

61 tests, sin red y sin gasto: el implementador se prueba con un proveedor falso. Pasan igual con
la wifi de la sede caída, que es exactamente cuando van a hacer falta.

No toca nada de `motor/`. Los tests del motor siguen igual que estaban: 117 recogidos, con el fallo
conocido de `test_smart_hurts_more_than_random` y el error de importación de `test_server` (necesita
su propio `.venv`, se lanza con `uv run`). Ninguno de los dos es de aquí.
