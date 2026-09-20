"""Generador de los textos de los avisos. Plantillas con huecos + variación con semilla; nada de LLM.

Voces: personal por radio o llamada (seco, con indicativo y «cambio»), centro de control tecleando,
sensores, y público por WhatsApp/SMS (faltas, mayúsculas, emojis, sin ubicación, varios idiomas).
Además: avisos ambiguos, duplicados con detalles que no coinciden, contradictorios, bromas y falsas
alarmas, y mensajes con el dato clave enterrado.

Todas las funciones reciben un `random.Random` ya sembrado y devuelven dicts con las claves del
`Report` del contrato: channel, source, lang, text y, solo si el canal lo sabe, zone_hint.
"""
from __future__ import annotations

import random
import unicodedata
from typing import Any

from .taxonomy import NEIGHBORS, TAXONOMY, ZONES

# ------------------------------------------------------------------ frases por tipo
# staff: lo que dice el personal (radio, llamada, operador). public: lo que escribe un asistente.
# en: asistente extranjero. sensor: lectura automática. Huecos: {person} {age} {n} {nbig} {min} {color}.

CORE: dict[str, dict[str, list[str]]] = {
    # ---- crowd
    "gate_saturation": {
        "staff": ["la cola se nos ha comido el vallado, tenemos un torno menos y sigue llegando gente",
                  "acceso saturado, calculo unas {nbig}0 personas esperando y el ritmo de entrada no da"],
        "public": ["llevamos {min} minutos parados en la cola y la gente empieza a empujar",
                   "esto no avanza nada, estamos apretadísimos en la entrada y hay gente agobiada"],
        "en": ["we've been stuck at the entrance for {min} minutes and people are starting to push"],
        "sensor": ["aforo {zone}: {occ} personas ({pct} % de capacidad), densidad {density} p/m², entrada neta +{n}0/min"],
    },
    "gate_crush_risk": {
        "staff": ["presión muy alta contra el vallado de acceso, hay gente gritando que no puede respirar",
                  "la gente de atrás empuja y los de delante están contra las vallas, esto se va de las manos"],
        "public": ["nos están aplastando contra las vallas de la entrada, hay una chica que no puede respirar",
                   "en la entrada no se puede ni mover los brazos, la gente grita, abrid algo por favor"],
        "en": ["people are getting crushed against the fences at the entrance, someone is screaming she can't breathe"],
        "sensor": ["aforo {zone}: densidad {density} p/m² (umbral 5,0), tendencia al alza desde hace {n} min"],
    },
    "front_pit_critical_density": {
        "staff": ["el foso está pasado de densidad, estamos sacando gente por encima de la valla de uno en uno",
                  "primera línea muy comprimida, hay oleadas laterales y ya hemos sacado a {n} mareados"],
        "public": ["delante del escenario no se puede respirar, nos movemos en ola y no controlamos los pies",
                   "estamos atrapados en las primeras filas, la gente se cae y no hay sitio para levantarla"],
        "en": ["front rows are way too packed, we're moving in waves and can't get out"],
        "sensor": ["contador front_pit: densidad {density} p/m² (umbral 5,0; riesgo 7,0), {occ} personas, +{n}0/min"],
    },
    "crowd_collapse": {
        "staff": ["caída en cadena, tengo a varias personas en el suelo unas encima de otras, necesito todo lo que haya",
                  "se ha venido abajo un grupo entero, hay atrapados debajo, calculo más de {n} heridos"],
        "public": ["se ha caído un montón de gente y hay personas debajo que no salen, esto es muy grave",
                   "la gente se ha caído como fichas de dominó, hay gente aplastada pidiendo ayuda"],
        "en": ["a whole group went down and there are people trapped underneath, this is really bad"],
    },
    "corridor_bottleneck": {
        "staff": ["el pasillo está taponado, se cruzan los que van y los que vuelven y no pasa nadie",
                  "embudo en el pasillo, flujo parado en los dos sentidos desde hace {n} minutos"],
        "public": ["el pasillo está colapsado, llevamos un rato sin poder avanzar ni volver",
                   "no se puede pasar por el pasillo, hay un tapón enorme y empieza a haber agobio"],
        "en": ["the walkway is totally jammed, nobody can move either way"],
        "sensor": ["contador {zone}: densidad {density} p/m², velocidad media de paso 0,2 m/s"],
    },
    "mass_entry_attempt": {
        "staff": ["grupo de unas {nbig} personas sin entrada intentando saltar el vallado, nos desbordan",
                  "intento de entrada en masa, han tumbado un tramo de valla y entran corriendo"],
        "public": ["hay un montón de gente saltando la valla de la entrada y empujando a los de seguridad",
                   "se están colando en masa por la entrada, han tirado una valla, qué miedo"],
        "en": ["a big group is storming the entrance fence, security can't hold them"],
    },
    "counterflow_exit": {
        "staff": ["tenemos contraflujo en la salida, los que salen chocan con gente que vuelve a entrar",
                  "la salida está parada, la gente se da la vuelta y se cruza con la que viene, hay empujones"],
        "public": ["en la salida la gente va en los dos sentidos y no cabe nadie, nos estamos chocando",
                   "queremos salir y no se puede, hay gente volviendo hacia dentro y está todo bloqueado"],
        "en": ["the exit is blocked, people are walking back in against everyone leaving"],
        "sensor": ["contador {zone}: flujo neto 0 personas/min, densidad {density} p/m²"],
    },
    "pmr_platform_overcrowded": {
        "staff": ["la plataforma PMR está por encima de aforo, se ha subido gente sin acreditación y no hay sitio para las sillas",
                  "plataforma de movilidad reducida desbordada, hay {n} sillas sin poder maniobrar"],
        "public": ["en la plataforma de sillas de ruedas se ha subido gente que no debería y no cabemos",
                   "voy en silla y la plataforma está llena de gente de pie, no puedo ni girar, me da miedo que se caiga alguien"],
        "en": ["the accessible platform is full of people who shouldn't be there, wheelchair users can't move"],
        "sensor": ["contador pmr: {occ} personas (aforo {cap})"],
    },
    "crowd_surge_general": {
        "staff": ["movimiento brusco de masa en pista, la gente corre sin saber de qué, hay caídos",
                  "estampida parcial en pista, algo ha asustado a la gente, tenemos varios por el suelo"],
        "public": ["todo el mundo se ha puesto a correr de repente, no sé qué pasa, hay gente por el suelo",
                   "ha habido una avalancha de gente, me han tirado, hay niños llorando"],
        "en": ["everyone suddenly started running, no idea why, people got knocked over"],
    },
    "stage_invasion": {
        "staff": ["han saltado {n} personas la valla del foso y van hacia el escenario",
                  "tengo gente subida al escenario, el regidor pide que los saquemos ya"],
        "public": ["hay gente saltando al escenario y los de seguridad corriendo detrás",
                   "unos tíos se han subido al escenario y se está liando delante"],
        "en": ["some guys jumped the barrier and climbed on stage"],
    },
    # ---- medical
    "cardiac_arrest": {
        "staff": ["varón de unos {age} años inconsciente, no respira, iniciamos RCP, necesito DESA y equipo médico ya",
                  "persona en parada, sin pulso, un compañero está con el masaje, que venga el DESA"],
        "public": ["{person} se ha desplomado y no respira, alguien le está haciendo el masaje",
                   "hay {person} tirado en el suelo que no responde ni respira, por favor mandad a alguien"],
        "en": ["{person_en} just collapsed and isn't breathing, someone is doing CPR, please send help"],
    },
    "heat_stroke": {
        "staff": ["persona con piel muy caliente y desorientada, posible golpe de calor, la tengo a la sombra",
                  "{person} de unos {age} años confuso y sin sudar, temperatura altísima, necesito médico"],
        "public": ["mi amiga está ardiendo, dice cosas raras y casi no se tiene en pie",
                   "{person} se ha mareado con el calor, está rojo y no contesta bien"],
        "en": ["my friend is burning hot and confused, she can barely stand, I think it's heat stroke"],
    },
    "multiple_heat_strokes": {
        "staff": ["llevo {n} desmayos por calor en diez minutos en la misma zona, no doy abasto",
                  "varios mareados por calor a la vez, {n} sentados en el suelo y dos que no responden bien"],
        "public": ["hay varias personas desmayadas por el calor aquí, por lo menos {n}",
                   "se está cayendo la gente del calor, hay {n} en el suelo y nadie tiene agua"],
        "en": ["several people have fainted from the heat here, at least {n}, nobody has water"],
    },
    "intoxication_overdose": {
        "staff": ["persona semiinconsciente, vómitos, los amigos dicen que ha mezclado alcohol con algo más",
                  "{person} de unos {age} años muy intoxicado, responde solo al dolor, pupilas raras"],
        "public": ["mi colega se ha tomado algo y no despierta, está vomitando y muy pálido",
                   "{person} está fatal, ha bebido mucho y creo que ha tomado algo más, no reacciona"],
        "en": ["my mate took something and won't wake up, he's throwing up and really pale"],
    },
    "anaphylaxis": {
        "staff": ["reacción alérgica grave, labios y cara hinchados, le cuesta respirar, no lleva adrenalina",
                  "{person} con anafilaxia tras comer, respiración con pitos, necesito médico con adrenalina"],
        "public": ["mi hermana es alérgica a los frutos secos, se le está hinchando la cara y no puede respirar bien",
                   "{person} ha comido algo y se le ha hinchado la boca, se ahoga"],
        "en": ["my sister has a nut allergy, her face is swelling and she can't breathe properly"],
    },
    "trauma_fall": {
        "staff": ["caída desde altura, posible fractura de tobillo, consciente y con mucho dolor",
                  "{person} se ha caído de los hombros de otro, golpe en la cabeza, sangra pero está consciente"],
        "public": ["{person} se ha caído y tiene el pie torcido de una forma muy rara, no puede andar",
                   "mi amigo se ha caído de una valla y se ha dado en la cabeza, sangra bastante"],
        "en": ["a girl fell off someone's shoulders and hit her head, she's bleeding"],
    },
    "seizure": {
        "staff": ["persona convulsionando en el suelo, le hemos hecho hueco, lleva más de un minuto",
                  "{person} de unos {age} años con crisis convulsiva, no tenemos antecedentes"],
        "public": ["{person} está en el suelo temblando con los ojos en blanco, no sabemos qué hacer",
                   "a una chica le está dando un ataque epiléptico, se sacude mucho"],
        "en": ["someone is having a seizure on the ground, shaking a lot, what do we do"],
    },
    "medical_post_saturated": {
        "staff": ["puesto lleno, tengo {n} camillas ocupadas y gente esperando fuera, no puedo recibir más",
                  "estamos saturados en el puesto, necesito derivar y una evacuación a hospital"],
        "public": ["en la carpa médica hay cola y dicen que no pueden atender a nadie más",
                   "he traído a mi amigo al puesto médico y está todo lleno, nos dicen que esperemos fuera"],
        "en": ["the medical tent is full, they told us to wait outside with my friend who's really unwell"],
    },
    "minor_injury": {
        "staff": ["corte leve en una mano, consciente y tranquilo, no corre prisa",
                  "esguince leve, la persona puede esperar sentada"],
        "public": ["me he cortado un poco con un vaso roto, no es grave pero sangra",
                   "mi amiga se ha torcido el tobillo, puede andar pero le duele"],
        "en": ["I cut my hand on a broken cup, not serious but it's bleeding a bit"],
    },
    "diabetic_emergency": {
        "staff": ["persona diabética sudorosa y confusa, posible hipoglucemia, no lleva su medidor",
                  "{person} de unos {age} años diabético, muy pálido y con temblores, casi no responde"],
        "public": ["mi novio es diabético, está temblando, sudando y no me contesta bien",
                   "{person} dice que es diabético y se está quedando como dormido"],
        "en": ["my boyfriend is diabetic, he's shaking and sweating and not making sense"],
    },
    "mass_food_poisoning": {
        "staff": ["llevo {n} personas con vómitos que han comido en el mismo puesto en la última hora",
                  "posible intoxicación alimentaria, varios casos con el mismo puesto de comida en común"],
        "public": ["hemos comido {n} en el mismo puesto y estamos todos vomitando",
                   "hay un montón de gente vomitando al lado de un puesto de comida, algo estaba malo"],
        "en": ["a bunch of us ate at the same stall and we're all throwing up"],
    },
    # ---- weather
    "extreme_heat_alert": {
        "staff": ["la estación marca {temp} grados y no hay sombra en pista, la gente empieza a sentarse en el suelo",
                  "aviso de temperatura extrema, {temp} grados, recomiendo reparto de agua y mensaje por pantallas"],
        "public": ["hace un calor insoportable y no hay ni una sombra, la gente lo está pasando mal",
                   "estamos a pleno sol y esto es un horno, poned agua o algo"],
        "en": ["it's unbearably hot and there's no shade anywhere, people are struggling"],
        "sensor": ["estación meteo: temperatura {temp} °C, índice de calor {heat_index} °C, alerta {alert}"],
    },
    "strong_wind_gusts": {
        "staff": ["rachas fuertes, las lonas de la estructura están flameando y una torre de luces se mueve",
                  "viento racheado de {wind} por hora, hay carteles sueltos y una carpa levantándose"],
        "public": ["el viento está moviendo mucho una torre de focos, da miedo estar debajo",
                   "se ha volado una lona y casi le da a gente, hay mucho viento"],
        "en": ["the wind is shaking one of the lighting towers, it doesn't look safe"],
        "sensor": ["estación meteo: racha {wind} km/h (umbral de estructuras 60 km/h), media 10 min {wind_avg} km/h"],
    },
    "storm_structures": {
        "staff": ["la tormenta ya está encima, rachas de {wind}, el techo del escenario trabaja mucho, producción pide parar",
                  "tormenta con aparato eléctrico y viento sobre el límite de la estructura, hay que despejar debajo"],
        "public": ["está cayendo una tormenta enorme y las pantallas gigantes se mueven, la gente sigue debajo",
                   "se mueve toda la estructura con el viento y la lluvia, sacad a la gente de ahí"],
        "en": ["huge storm, the big screens are swinging and people are still standing under them"],
        "sensor": ["estación meteo: racha {wind} km/h, lluvia intensa, límite de estructura superado, alerta {alert}"],
    },
    "lightning_nearby": {
        "staff": ["detector de rayos: descargas a menos de diez kilómetros y acercándose, protocolo dice parar",
                  "rayos a ocho kilómetros, tormenta avanzando hacia el recinto"],
        "public": ["están cayendo rayos muy cerca y seguimos todos aquí al aire libre",
                   "se ven relámpagos al lado, ¿no van a parar esto?"],
        "en": ["there's lightning really close and we're all standing in an open field"],
        "sensor": ["detector de rayos: descarga a {n} km, {nbig} descargas en 10 min, alerta {alert}"],
    },
    "heavy_rain_flooding": {
        "staff": ["se ha encharcado todo el paso, hay cables por el suelo con agua y la gente resbala",
                  "balsa de agua de un palmo, el paso está impracticable y ya ha habido resbalones"],
        "public": ["esto está inundado, hay un charco enorme y la gente se resbala",
                   "el suelo es un barrizal, se acaba de caer una señora"],
        "en": ["the path is flooded, people keep slipping in the mud"],
        "sensor": ["estación meteo: lluvia {nbig} mm/h, acumulado 1 h {nbig} mm"],
    },
    "hail_shelter_rush": {
        "staff": ["ha empezado a granizar y la gente corre en masa a meterse bajo las carpas, se están aplastando en la entrada",
                  "granizo fuerte, avalancha de gente buscando techo, las carpas no dan para tantos"],
        "public": ["está granizando y todo el mundo se mete a empujones debajo de las carpas, no cabemos",
                   "nos estamos aplastando bajo un toldo por el granizo, hay gente cayéndose"],
        "en": ["it's hailing and everyone is shoving to get under the tents, it's getting dangerous"],
    },
    # ---- aggression
    "fight": {
        "staff": ["pelea entre dos grupos, unas {n} personas implicadas, necesito apoyo",
                  "riña con botellas, hay uno sangrando por la ceja, que venga otra pareja"],
        "public": ["se están pegando unos tíos aquí al lado, hay uno sangrando",
                   "hay una pelea bastante fuerte, como {n} personas dándose"],
        "en": ["there's a fight right next to us, like {n} guys, one of them is bleeding"],
    },
    "chemical_submission": {
        "staff": ["chica muy desorientada, solo ha tomado una copa, las amigas sospechan que le han echado algo",
                  "posible sumisión química, mujer de unos {age} años semiinconsciente, un hombre intentaba llevársela"],
        "public": ["a mi amiga le han echado algo en la bebida, no se tiene en pie y un tío no se separa de ella",
                   "creo que me han puesto algo en la copa, me encuentro rarísima y no encuentro a mis amigas"],
        "en": ["I think someone spiked my friend's drink, she can barely stand and some guy keeps trying to take her away"],
    },
    "sexual_assault_report": {
        "staff": ["una chica nos dice que la han agredido sexualmente, está con nosotros, el agresor se ha ido hacia la pista",
                  "víctima de agresión sexual, solicita punto violeta, describe al agresor con camiseta {color}"],
        "public": ["un hombre me ha metido mano a la fuerza y me ha seguido, tengo miedo, necesito ayuda",
                   "han agredido a mi amiga, está llorando y no quiere moverse, el tío lleva camiseta {color}"],
        "en": ["a man assaulted my friend, she's crying and won't move, he's wearing a {color_en} shirt"],
    },
    "weapon_seen": {
        "staff": ["varón con una navaja en la mano, camiseta {color}, lo tenemos a la vista, no intervenimos solos",
                  "aviso de arma blanca, un individuo ha sacado un cuchillo en una discusión"],
        "public": ["un tío ha sacado una navaja aquí al lado, lleva camiseta {color}",
                   "hay uno con un cuchillo amenazando a otro, la gente se está apartando"],
        "en": ["a guy just pulled a knife near us, {color_en} shirt, people are backing away"],
    },
    "theft_gang": {
        "staff": ["nos llegan {n} denuncias de móviles robados en la misma zona en media hora, parece un grupo organizado",
                  "carteristas trabajando, varios afectados describen a los mismos dos individuos"],
        "public": ["nos han robado el móvil a {n} del grupo en un momento, hay una banda",
                   "me acaban de quitar el móvil del bolsillo y a la de al lado también"],
        "en": ["{n} of us just had our phones stolen, there's a gang working the crowd"],
    },
    "staff_assaulted": {
        "staff": ["han agredido a un compañero, puñetazo en la cara, el agresor sigue aquí y está muy alterado",
                  "agresión a personal de barra, le han tirado un vaso, tiene un corte"],
        "public": ["un tío le ha pegado a uno de seguridad y sigue ahí gritando",
                   "le han tirado un vaso a la camarera en la cara, está sangrando"],
        "en": ["some guy just punched a security guard and he's still there shouting"],
    },
    "harassment_group": {
        "staff": ["grupo de {n} hombres molestando a varias chicas, no las dejan irse, piden ayuda",
                  "nos avisan de acoso continuado de un grupo, las afectadas están con nosotros"],
        "public": ["hay un grupo de tíos que no nos deja en paz, nos rodean y nos tocan",
                   "unos chicos llevan un rato acosando a unas chicas, ellas ya no saben dónde meterse"],
        "en": ["a group of guys won't leave us alone, they keep surrounding us and touching us"],
    },
    "hate_incident": {
        "staff": ["grupo insultando y empujando a una pareja por ir de la mano, ambiente muy tenso",
                  "agresión verbal con insultos racistas a un chico, hay {n} increpándole"],
        "public": ["unos tíos nos están insultando y empujando por ser gais, tenemos miedo",
                   "le están gritando cosas racistas a un chico y le han tirado la bebida"],
        "en": ["some men are shouting homophobic abuse at us and shoving us"],
    },
    # ---- supply
    "water_out": {
        "staff": ["punto de agua seco, depósito a cero, tengo una cola de {nbig} personas y se están calentando",
                  "se ha acabado el agua del punto, la cisterna de reposición no ha llegado"],
        "public": ["no sale agua de las fuentes y hay una cola enorme, la gente se está enfadando",
                   "no hay agua en ningún grifo, llevamos {min} minutos esperando"],
        "en": ["the water point is dry and there's a massive queue, people are getting angry"],
        "sensor": ["depósito {zone}: nivel 0 l (mínimo operativo 500 l)"],
    },
    "food_shortage": {
        "staff": ["tres barras sin producto, la gente protesta pero sin más",
                  "nos hemos quedado sin género en varios puestos, reposición pendiente"],
        "public": ["no queda comida en casi ningún puesto", "llevamos media hora de cola y dicen que ya no hay nada"],
        "en": ["most of the food stalls have run out of food"],
    },
    "generator_fuel_low": {
        "staff": ["el generador dos está en reserva, le quedan unos {min} minutos y el camión de gasoil no aparece",
                  "nivel de combustible crítico en el grupo electrógeno, si cae se va la luz de la zona"],
        "sensor": ["generador {zone}: combustible {n} %, autonomía estimada {min} min"],
    },
    "medical_supplies_low": {
        "staff": ["nos quedan dos sueros y no hay más mantas térmicas ni apósitos, necesito reposición urgente",
                  "material bajo mínimos en el puesto, sin oxígeno de repuesto"],
    },
    "wristbands_out": {
        "staff": ["nos hemos quedado sin pulseras en el canje, la cola crece y no podemos validar a nadie",
                  "taquilla sin pulseras, {nbig} personas esperando y cada vez más nerviosas"],
        "public": ["dicen que no quedan pulseras y no nos dejan entrar, la cola es larguísima",
                   "llevamos {min} min en la cola del canje y no dan pulseras"],
        "en": ["they say they've run out of wristbands and won't let anyone in"],
    },
    "radio_batteries_low": {
        "staff": ["la mitad de los walkies del equipo están en rojo y no quedan baterías cargadas",
                  "nos quedamos sin radio en media hora si no llegan baterías"],
    },
    "ice_cooling_out": {
        "staff": ["sin hielo ni mantas frías y sigo recibiendo gente con calor",
                  "se ha acabado el hielo del puesto, no puedo enfriar a los pacientes"],
    },
    # ---- infra
    "power_outage_food": {
        "staff": ["se ha ido la luz en toda la zona de restauración, cámaras frigoríficas y TPV apagados, está a oscuras",
                  "apagón en restauración, los puestos con gas siguen cocinando a oscuras"],
        "public": ["se ha ido la luz en toda la zona de comida, no se ve nada y hay mucha gente",
                   "apagón en los food trucks, está todo a oscuras y la gente empuja"],
        "en": ["the power just went out in the whole food area, it's pitch dark"],
        "sensor": ["cuadro eléctrico food: sin tensión en las 3 fases"],
    },
    "cashless_down": {
        "staff": ["ha caído el sistema cashless, ningún puesto puede cobrar, las colas se están calentando",
                  "los datáfonos de pulsera no leen, llevamos {min} minutos sin cobrar y la gente se enfada"],
        "public": ["no funciona el pago con la pulsera en ningún sitio, no podemos comprar ni agua",
                   "las pulseras no van, hay colas enormes y la gente discute con los camareros"],
        "en": ["wristband payments are down everywhere, we can't even buy water"],
        "sensor": ["pasarela cashless: 0 transacciones en 5 min, {nbig} terminales sin latido"],
    },
    "stage_power_failure": {
        "staff": ["hemos perdido la acometida del escenario, sin sonido ni pantallas, el público empieza a silbar",
                  "corte de corriente en escenario, solo tenemos luz de emergencia"],
        "public": ["se ha ido el sonido y las pantallas en mitad de la canción, la gente se está poniendo nerviosa",
                   "se ha apagado todo el escenario, nadie dice nada"],
        "en": ["the stage just went dark and silent mid-song, the crowd is getting restless"],
        "sensor": ["cuadro eléctrico escenario: sin tensión, SAI al {n}0 %"],
    },
    "toilets_blocked": {
        "staff": ["un módulo entero de baños fuera de uso, atasco y rebose", "baños desbordados, hay que cerrar un bloque"],
        "public": ["los baños están desbordados, es asqueroso, no se puede entrar",
                   "la mitad de los baños están cerrados y la cola es de {min} minutos"],
        "en": ["half the toilets are overflowing and closed, the queue is insane"],
    },
    "barrier_failure": {
        "staff": ["ha cedido un tramo de valla antiavalancha, lo estamos aguantando a mano entre cuatro",
                  "valla rota, {n} metros abiertos y la gente se vence hacia delante"],
        "public": ["se ha roto una valla y la gente se cae hacia delante, los de seguridad la sujetan a pulso",
                   "la valla de delante se ha doblado, nos empujan contra ella"],
        "en": ["a barrier just gave way and people are falling forward, security is holding it by hand"],
    },
    "structure_damage": {
        "staff": ["una cercha ha cedido parcialmente, hay una pantalla colgando de un solo punto, hay que despejar debajo",
                  "estructura dañada, una carpa se ha vencido de un lado con gente dentro"],
        "public": ["hay una pantalla medio colgando encima de la gente, parece que se va a caer",
                   "se ha hundido un lado de una carpa, hay gente dentro"],
        "en": ["one of the big screens is hanging by one corner right above people"],
    },
    "lighting_failure": {
        "staff": ["se ha ido todo el alumbrado del tramo, la gente camina a oscuras con el móvil",
                  "sin luz en la ruta de salida, ya hemos tenido un par de tropiezos"],
        "public": ["no hay ni una luz en el camino de salida, no se ve el suelo",
                   "está todo a oscuras por aquí, se acaba de caer un chico"],
        "en": ["there are no lights at all on the way out, people are tripping over"],
        "sensor": ["alumbrado {zone}: circuito abierto, 0 de {n} luminarias"],
    },
    "comms_network_down": {
        "staff": ["la red está caída, no entran los WhatsApp del público y los walkies van con cortes",
                  "hemos perdido la red de datos del recinto, el repetidor no responde"],
        "sensor": ["repetidor principal: sin latido desde hace {n} min"],
    },
    "turnstile_failure": {
        "staff": ["tengo {n} tornos caídos, validamos a mano y la cola crece",
                  "los lectores de entrada no leen, estamos pasando a la gente de uno en uno"],
        "public": ["los tornos no funcionan y nos tienen aquí parados", "no leen las entradas en la puerta, la cola no se mueve"],
        "en": ["the ticket scanners aren't working and the queue isn't moving"],
        "sensor": ["tornos {zone}: {n} de 6 fuera de servicio"],
    },
    "gas_leak_food": {
        "staff": ["olor fuerte a gas en la trasera de los puestos, hemos cortado una bombona pero sigue oliendo",
                  "posible fuga de gas en cocinas, hay planchas encendidas al lado"],
        "public": ["huele muchísimo a gas al lado de los puestos de comida", "aquí huele a gas que echa para atrás"],
        "en": ["there's a really strong smell of gas by the food stalls"],
    },
    "small_fire": {
        "staff": ["conato de incendio, arde material junto a una instalación, lo atacamos con extintor pero no lo controlamos",
                  "fuego en un cuadro eléctrico, humo negro, necesito apoyo y bomberos"],
        "public": ["hay fuego en uno de los puestos, sale mucho humo", "se está quemando algo aquí, hay llamas y la gente corre"],
        "en": ["one of the stalls is on fire, there's a lot of smoke"],
    },
    # ---- resource
    "ambulance_blocked_by_crowd": {
        "staff": ["la ambulancia no puede avanzar, tenemos el pasillo lleno de gente y no abren paso",
                  "ambulancia interna parada, rodeada de público, no podemos ni dar marcha atrás"],
        "public": ["hay una ambulancia atascada entre la gente con las luces puestas y nadie se aparta",
                   "la ambulancia lleva un rato parada, no puede pasar"],
        "en": ["there's an ambulance stuck in the crowd with its lights on, nobody is moving out of the way"],
    },
    "injured_staff": {
        "staff": ["compañero lesionado, se ha hecho daño en la rodilla conteniendo una valla, no puede seguir",
                  "tengo a un vigilante con un golpe en la cabeza, consciente, lo retiro del servicio"],
    },
    "vehicle_breakdown": {
        "staff": ["la ambulancia interna no arranca, nos hemos quedado tirados", "avería en la ambulancia, pierde líquido y no mueve"],
    },
    "medical_team_overwhelmed": {
        "staff": ["estoy solo con tres pacientes, necesito otro equipo aquí ya",
                  "no damos abasto, tenemos {n} personas atendidas en el suelo y siguen llegando"],
    },
    # ---- info
    "lost_child": {
        "staff": ["tenemos a una madre que ha perdido a su hijo de {kid_age} años hace {min} minutos, camiseta {color}",
                  "menor extraviado, {kid_age} años, visto por última vez hace {min} minutos"],
        "public": ["he perdido a mi hijo, tiene {kid_age} años, lleva camiseta {color}, por favor ayudadme",
                   "no encuentro a mi hija de {kid_age} años, estaba a mi lado hace un momento"],
        "en": ["I've lost my son, he's {kid_age}, wearing a {color_en} t-shirt, please help me"],
    },
    "lost_vulnerable_adult": {
        "staff": ["señor mayor desorientado, no sabe con quién ha venido ni dónde está", "persona con discapacidad intelectual sola y muy nerviosa"],
        "public": ["mi padre tiene alzhéimer y se ha ido de nuestro lado, lleva camisa {color}",
                   "hay un señor mayor muy perdido que no sabe dónde está"],
        "en": ["my dad has dementia and wandered off, he's wearing a {color_en} shirt"],
    },
    "rumor_panic": {
        "staff": ["corre el bulo de que hay un tiroteo, la gente sale corriendo de la zona y no hay nada",
                  "se está moviendo por redes que hay una bomba, tenemos carreras y gente llorando"],
        "public": ["dicen que hay un tío con una pistola, todo el mundo corre", "me ha llegado por un grupo que hay una bomba, es verdad???"],
        "en": ["people are saying there's a shooter, everyone is running"],
    },
    "fake_staff_instructions": {
        "staff": ["hay alguien con chaleco reflectante que no es nuestro diciendo a la gente que evacúe",
                  "falso personal dando órdenes de salida, la gente le hace caso y se mueve hacia las puertas"],
        "public": ["un chico con chaleco nos dice que hay que evacuar, es verdad??", "nos están diciendo que salgamos todos pero por megafonía no dicen nada"],
        "en": ["a guy in a hi-vis vest is telling everyone to evacuate, is that real?"],
    },
    # ---- external
    "transport_cut_exit": {
        "staff": ["metro nos confirma línea cortada, las lanzaderas no dan para todos y la explanada se llena",
                  "sin servicio de metro hasta nuevo aviso, tengo miles de personas sin saber adónde ir"],
        "public": ["han cerrado el metro y no hay buses, estamos miles aquí tirados",
                   "no pasa ninguna lanzadera desde hace {min} minutos y cada vez hay más gente"],
        "en": ["the metro is closed and there are no shuttles, thousands of us are stuck here"],
    },
    "suspicious_object": {
        "staff": ["mochila abandonada junto a una valla, nadie la reclama, no la tocamos",
                  "bulto sospechoso sin dueño desde hace {min} minutos, hemos apartado a la gente unos metros"],
        "public": ["hay una mochila sola desde hace un rato y nadie sabe de quién es", "han dejado una maleta abandonada, da mal rollo"],
        "en": ["there's a backpack that's been left alone for ages, nobody knows whose it is"],
    },
    "bomb_threat_call": {
        "staff": ["han llamado a taquillas diciendo que hay un artefacto en el recinto, voz de varón, ha colgado",
                  "amenaza telefónica de bomba, sin ubicación concreta, llamada de {n}0 segundos"],
    },
    "artist_delay_cancel": {
        "staff": ["el artista no sale, management confirma retraso de al menos {min} minutos, el público ya silba",
                  "cancelación del cabeza de cartel confirmada, hay que comunicarlo antes de que se entere por redes"],
        "public": ["llevan {min} minutos de retraso y nadie dice nada, la gente empieza a tirar vasos",
                   "dicen en twitter que han cancelado, es verdad??? la gente se está cabreando"],
        "en": ["the headliner is {min} minutes late, no announcement, people are throwing cups"],
    },
    "drone_intrusion": {
        "staff": ["dron no autorizado sobrevolando al público a baja altura", "tenemos un dron encima del foso, no es de producción"],
        "public": ["hay un dron volando muy bajo encima de la gente", "un dron casi le da a uno en la cabeza"],
        "en": ["there's a drone flying really low over the crowd"],
    },
    "nearby_wildfire_smoke": {
        "staff": ["entra humo de un incendio de matorral al otro lado de la carretera, el viento lo trae hacia aquí",
                  "columna de humo cercana, empieza a oler fuerte y hay gente tosiendo"],
        "public": ["huele mucho a quemado y se ve humo detrás del recinto", "está entrando humo, hay gente tosiendo, ¿hay un incendio?"],
        "en": ["there's smoke coming over the fence and people are coughing, is there a fire?"],
    },
    "road_access_blocked": {
        "staff": ["accidente en la vía de servicio, acceso rodado cortado, una ambulancia externa no podría entrar",
                  "camión cruzado en el acceso de emergencias, tráfico dice que tarda {min} minutos"],
    },
}

# Frases en otros idiomas para los tipos más «de público». Si falta, se usa la genérica de familia.
OTHER_LANG: dict[str, dict[str, list[str]]] = {
    "cardiac_arrest": {
        "fr": ["un homme est tombé par terre, il ne respire plus, vite s'il vous plaît"],
        "de": ["ein Mann ist zusammengebrochen und atmet nicht mehr, bitte schnell Hilfe"],
        "pt": ["um homem caiu no chão e não respira, por favor venham rápido"],
    },
    "heat_stroke": {
        "fr": ["mon amie est brûlante et elle dit n'importe quoi, elle ne tient plus debout"],
        "de": ["meine Freundin ist ganz heiß und verwirrt, sie kann kaum stehen"],
        "pt": ["a minha amiga está a arder de calor e confusa, quase não se aguenta em pé"],
    },
    "chemical_submission": {
        "fr": ["je crois qu'on a mis quelque chose dans le verre de ma copine, elle ne tient plus debout"],
        "de": ["ich glaube jemand hat meiner Freundin etwas ins Getränk getan, sie kann nicht mehr stehen"],
        "pt": ["acho que puseram alguma coisa na bebida da minha amiga, ela não se aguenta em pé"],
    },
    "lost_child": {
        "fr": ["j'ai perdu mon fils, il a {kid_age} ans, aidez-moi s'il vous plaît"],
        "de": ["ich habe meinen Sohn verloren, er ist {kid_age} Jahre alt, bitte helfen Sie mir"],
        "pt": ["perdi o meu filho, tem {kid_age} anos, por favor ajudem-me"],
    },
    "fight": {
        "fr": ["il y a une bagarre juste à côté, un mec saigne"],
        "de": ["hier gibt es eine Schlägerei, einer blutet"],
        "pt": ["há uma luta aqui ao lado, um rapaz está a sangrar"],
    },
    "front_pit_critical_density": {
        "fr": ["devant la scène on est écrasés, on ne peut plus respirer"],
        "de": ["vor der Bühne werden wir zerdrückt, man bekommt keine Luft"],
        "pt": ["à frente do palco estamos esmagados, não se consegue respirar"],
    },
    "gate_saturation": {
        "fr": ["on est bloqués à l'entrée depuis {min} minutes et ça pousse"],
        "de": ["wir stehen seit {min} Minuten am Eingang fest und die Leute drängeln"],
        "pt": ["estamos parados na entrada há {min} minutos e as pessoas começam a empurrar"],
    },
    "water_out": {
        "fr": ["il n'y a plus d'eau aux fontaines et la queue est énorme"],
        "de": ["es gibt kein Wasser mehr an den Wasserstellen und die Schlange ist riesig"],
        "pt": ["não há água nas fontes e a fila é enorme"],
    },
    "cashless_down": {
        "fr": ["le paiement par bracelet ne marche plus, on ne peut même pas acheter de l'eau"],
        "de": ["die Bezahlung mit dem Armband geht nicht, wir können nicht mal Wasser kaufen"],
        "pt": ["o pagamento com a pulseira não funciona, não conseguimos comprar nem água"],
    },
    "transport_cut_exit": {
        "fr": ["le métro est fermé et il n'y a pas de navettes, on est des milliers bloqués"],
        "de": ["die U-Bahn ist zu und es fahren keine Shuttles, wir stehen hier zu Tausenden"],
        "pt": ["o metro está fechado e não há autocarros, estamos milhares aqui parados"],
    },
    "suspicious_object": {
        "fr": ["il y a un sac à dos abandonné depuis un moment, personne ne sait à qui il est"],
        "de": ["hier steht seit einer Weile ein herrenloser Rucksack"],
        "pt": ["há uma mochila abandonada há algum tempo, ninguém sabe de quem é"],
    },
    "intoxication_overdose": {
        "fr": ["mon pote a pris quelque chose et il ne se réveille pas"],
        "de": ["mein Kumpel hat etwas genommen und wacht nicht mehr auf"],
        "pt": ["o meu amigo tomou alguma coisa e não acorda"],
    },
}

FAMILY_GENERIC: dict[str, dict[str, list[str]]] = {
    "crowd": {"fr": ["il y a beaucoup trop de monde ici, on se fait écraser"], "de": ["hier ist es viel zu voll, wir werden zerdrückt"],
              "pt": ["há gente a mais aqui, estamos a ser esmagados"]},
    "medical": {"fr": ["quelqu'un a besoin d'un médecin ici, c'est grave"], "de": ["hier braucht jemand dringend einen Arzt"],
                "pt": ["alguém precisa de um médico aqui, é grave"]},
    "weather": {"fr": ["avec ce temps c'est dangereux ici, quelque chose va tomber"], "de": ["bei dem Wetter ist es hier gefährlich, gleich fällt etwas um"],
                "pt": ["com este tempo isto está perigoso, vai cair alguma coisa"]},
    "aggression": {"fr": ["quelqu'un se fait agresser ici, envoyez la sécurité"], "de": ["hier wird jemand angegriffen, bitte Security schicken"],
                   "pt": ["estão a agredir alguém aqui, mandem a segurança"]},
    "supply": {"fr": ["il n'y a plus rien ici et les gens s'énervent"], "de": ["hier gibt es nichts mehr und die Leute werden wütend"],
               "pt": ["já não há nada aqui e as pessoas estão a ficar nervosas"]},
    "infra": {"fr": ["quelque chose est en panne ici, tout est bloqué"], "de": ["hier ist etwas kaputt, nichts geht mehr"],
              "pt": ["há uma avaria aqui, está tudo parado"]},
    "resource": {"fr": ["l'ambulance est bloquée dans la foule"], "de": ["der Krankenwagen steckt in der Menge fest"],
                 "pt": ["a ambulância está presa no meio da multidão"]},
    "info": {"fr": ["les gens disent qu'il se passe quelque chose de grave, c'est vrai ?"], "de": ["die Leute sagen, es passiert etwas Schlimmes, stimmt das?"],
             "pt": ["as pessoas dizem que se passa algo grave, é verdade?"]},
    "external": {"fr": ["il y a un problème à la sortie, personne ne nous dit rien"], "de": ["am Ausgang gibt es ein Problem, niemand sagt uns etwas"],
                 "pt": ["há um problema na saída, ninguém nos diz nada"]},
}

# ------------------------------------------------------------------ ubicaciones

LOC_STAFF: dict[str, list[str]] = {
    "gate_a": ["en puerta A", "acceso A"], "gate_b": ["en puerta B", "acceso B"], "gate_c": ["en puerta C", "acceso C"],
    "front_pit": ["en el foso, frente de escenario", "primera línea, lado {side}"],
    "stage_2": ["en el escenario 2", "en el escenario pequeño, el 2"],
    "general": ["en pista general, a la altura de la torre de sonido", "pista general, cuadrante {side}"],
    "vip": ["en zona VIP"], "pmr": ["en la plataforma PMR"],
    "food": ["en restauración", "zona de barras y food trucks"], "toilets": ["en el bloque de baños"],
    "water_n": ["en el punto de agua norte"], "water_s": ["en el punto de agua sur"],
    "medical_1": ["en el puesto médico 1"], "medical_2": ["en el puesto médico 2"],
    "corridor_n": ["en el pasillo norte"], "corridor_s": ["en el pasillo sur, ruta de ambulancia"],
    "backstage": ["en backstage"], "exit_transport": ["en la explanada de lanzaderas", "en la salida a metro y lanzaderas"],
}
LOC_PUBLIC: dict[str, dict[str, list[str]]] = {
    "es": {
        "gate_a": ["en la entrada A", "en la puerta A", "en la cola de la entrada A"],
        "gate_b": ["en la entrada B", "en la puerta B"], "gate_c": ["en la puerta C", "en la entrada pequeña, la C"],
        "front_pit": ["delante del todo", "en primera fila", "pegados a la valla del escenario"],
        "stage_2": ["en el escenario 2", "delante del escenario 2", "en la zona del escenario pequeño"],
        "general": ["en medio de la pista", "por la torre de sonido", "a la altura de la mesa de mezclas"],
        "vip": ["en la zona vip"], "pmr": ["en la plataforma de las sillas de ruedas"],
        "food": ["en los food trucks", "en la zona de comida", "al lado del puesto de hamburguesas"],
        "toilets": ["en los baños", "en la cola de los baños"],
        "water_n": ["en las fuentes de agua de arriba", "en el punto de agua norte"],
        "water_s": ["en las fuentes de abajo", "en el punto de agua sur"],
        "medical_1": ["en la carpa médica de al lado del escenario"], "medical_2": ["en la carpa médica de arriba, la norte"],
        "corridor_n": ["en el pasillo que va a los food trucks", "en el pasillo norte"],
        "corridor_s": ["en el pasillo de abajo, por donde pasan las ambulancias", "en el pasillo sur"],
        "backstage": ["detrás del escenario"],
        "exit_transport": ["en la salida de los buses", "donde las lanzaderas", "en la salida hacia el metro"],
    },
    "en": {
        "gate_a": ["at gate A"], "gate_b": ["at gate B"], "gate_c": ["at gate C"],
        "front_pit": ["right at the front barrier", "in the front rows"], "stage_2": ["at stage 2", "in front of stage 2"],
        "general": ["in the main crowd near the sound tower"],
        "vip": ["in the VIP area"], "pmr": ["on the accessible platform"], "food": ["at the food trucks"],
        "toilets": ["by the toilets"], "water_n": ["at the north water point"], "water_s": ["at the south water point"],
        "medical_1": ["at the medical tent near the stage"], "medical_2": ["at the north medical tent"],
        "corridor_n": ["on the north walkway"], "corridor_s": ["on the south walkway"], "backstage": ["behind the stage"],
        "exit_transport": ["at the shuttle bus exit", "at the exit to the metro"],
    },
    "fr": {z: [n] for z, n in {
        "gate_a": "vers l'entrée A", "gate_b": "vers l'entrée B", "gate_c": "vers l'entrée C",
        "front_pit": "contre la barrière devant la scène", "stage_2": "vers la scène 2",
        "general": "vers la tour du son", "vip": "dans la zone VIP",
        "pmr": "sur la plateforme PMR", "food": "vers les food trucks", "toilets": "vers les toilettes",
        "water_n": "au point d'eau nord", "water_s": "au point d'eau sud", "medical_1": "devant la tente médicale",
        "medical_2": "devant la tente médicale", "corridor_n": "dans l'allée nord", "corridor_s": "dans l'allée sud",
        "backstage": "derrière la scène", "exit_transport": "à la sortie des navettes"}.items()},
    "de": {z: [f"bei {n}"] for z, n in {
        "gate_a": "Eingang A", "gate_b": "Eingang B", "gate_c": "Eingang C", "front_pit": "der Absperrung vor der Bühne",
        "stage_2": "Bühne 2",
        "general": "dem Soundturm", "vip": "dem VIP-Bereich", "pmr": "der Rollstuhlplattform", "food": "den Foodtrucks",
        "toilets": "den Toiletten", "water_n": "der Wasserstelle Nord", "water_s": "der Wasserstelle Süd",
        "medical_1": "dem Sanitätszelt", "medical_2": "dem Sanitätszelt", "corridor_n": "dem Nordweg",
        "corridor_s": "dem Südweg", "backstage": "dem Backstage", "exit_transport": "dem Shuttle-Ausgang"}.items()},
    "pt": {z: [n] for z, n in {
        "gate_a": "junto à entrada A", "gate_b": "junto à entrada B", "gate_c": "junto à entrada C",
        "front_pit": "junto à grade em frente ao palco", "stage_2": "junto ao palco 2",
        "general": "junto à torre de som", "vip": "na zona VIP",
        "pmr": "na plataforma de mobilidade reduzida", "food": "junto às roulottes de comida",
        "toilets": "junto às casas de banho", "water_n": "no ponto de água norte", "water_s": "no ponto de água sul",
        "medical_1": "junto à tenda médica", "medical_2": "junto à tenda médica", "corridor_n": "no corredor norte",
        "corridor_s": "no corredor sul", "backstage": "nos bastidores", "exit_transport": "na saída dos autocarros"}.items()},
}
LOC_VAGUE = {
    "es": ["por aquí", "cerca de una barra", "no sé dónde estoy, se ve una torre de luces", "al lado de una bandera grande",
           "donde hay mucha gente", "cerca de unos baños creo"],
    "en": ["somewhere near a bar", "I don't know where exactly, near a big flag", "near some lights tower"],
}
ENTRANCE_VAGUE = ["en la entrada", "en una de las puertas", "en los accesos"]


def staff_location(rng: random.Random, zone: str, slots: dict[str, Any] | None = None) -> str:
    """Ubicación del personal por radio. Si la zona aún no tiene frase propia, se usa su nombre:
    añadir una zona a `festival.json` no puede tumbar la generación de casos."""
    options = LOC_STAFF.get(zone)
    if options:
        return rng.choice(options).format(**(slots or {}))
    return f"en {ZONES[zone]['name'].lower()}"


def public_location(rng: random.Random, lang: str, zone: str) -> str:
    """Ubicación exacta del público. Sin frase para esa zona en ese idioma: se calla la ubicación
    (en español se usa el nombre de la zona). Mejor omitirla que inventarla en otro idioma."""
    options = (LOC_PUBLIC.get(lang) or LOC_PUBLIC["es"]).get(zone)
    if options:
        return rng.choice(options)
    return f"en {ZONES[zone]['name'].lower()}" if lang == "es" else ""

# ------------------------------------------------------------------ piezas

LANG_WEIGHTS = (("es", 70), ("en", 18), ("fr", 4), ("de", 4), ("pt", 4))
CALLSIGNS = {
    "security": ["Seguridad {k}", "Sierra {k}", "jefe de seguridad {k}"],
    "medical": ["Médico {k}", "Mike {k}", "coordinadora médica"],
    "ambulance": ["Ambulancia interna", "Alfa 1"],
    "tech": ["Técnico {k}", "Tango {k}"],
    "logistics": ["Logística", "Lima 1"],
    "volunteer": ["Voluntarios {k}", "coordinador de voluntarios"],
}
PERSON_ES = ["un chico", "una chica", "un señor", "una señora", "un chaval", "un hombre mayor"]
PERSON_EN = ["a guy", "a girl", "an older man", "a woman", "a young lad"]
COLORS = [("roja", "red"), ("negra", "black"), ("amarilla", "yellow"), ("blanca", "white"), ("verde", "green"), ("azul", "blue")]
RADIO_ASK = {
    "security": ["Solicito apoyo", "Necesito otra pareja", "Pido refuerzo"],
    "medical": ["Solicito equipo médico", "Necesito sanitarios ya", "Que venga un médico"],
    "ambulance": ["Solicito ambulancia", "Necesito traslado"],
    "tech": ["Solicito técnico", "Que venga mantenimiento"],
    "logistics": ["Solicito reposición", "Necesito logística"],
    "volunteer": ["Me vendrían bien voluntarios", "Pido manos para ordenar a la gente"],
}
URGENT_ES = ["ayuda", "socorro", "por favor venid", "URGENTE", "oye", "hola", "perdonad", ""]
URGENT_EN = ["help", "please hurry", "hi", "URGENT", "omg", ""]
EMOJIS = ["😰", "🆘", "🙏", "😭", "🚑", "‼️", "😱", "⚠️"]
SHORTHAND = (("porque", "xq"), ("por favor", "porfa"), ("también", "tb"), (" que ", " q "), (" por ", " x "), ("donde", "dnd"))


def _pick_lang(rng: random.Random) -> str:
    return rng.choices([l for l, _ in LANG_WEIGHTS], weights=[w for _, w in LANG_WEIGHTS])[0]


def _slots(rng: random.Random, ctx: dict[str, Any] | None = None, avoid: dict[str, Any] | None = None) -> dict[str, Any]:
    """Valores de los huecos. `avoid` fuerza detalles distintos (para duplicados que no coinciden)."""
    ctx = ctx or {}
    color = rng.choice(COLORS)
    s: dict[str, Any] = {
        "person": rng.choice(PERSON_ES), "person_en": rng.choice(PERSON_EN),
        "age": rng.choice([20, 25, 30, 35, 40, 50, 55, 60, 70]), "kid_age": rng.randint(4, 11),
        "n": rng.randint(2, 6), "nbig": rng.randint(20, 60), "min": rng.choice([5, 10, 15, 20, 25, 30]),
        "color": color[0], "color_en": color[1], "side": rng.choice(["izquierdo", "derecho", "centro"]),
    }
    if avoid:
        for key, pool in (("person", PERSON_ES), ("age", [20, 30, 40, 50, 60]), ("n", [2, 3, 4, 5, 6, 8]),
                          ("color", [c[0] for c in COLORS])):
            rest = [v for v in pool if v != avoid.get(key)]
            s[key] = rng.choice(rest)
        s["color_en"] = dict(COLORS)[s["color"]]
    temp = ctx.get("temp_c", 28)
    wind = ctx.get("wind_kmh", 15)
    s.update({
        "zone": ctx.get("zone", ""), "occ": ctx.get("occupancy", 0), "cap": ctx.get("capacity", 0),
        "pct": round(100 * ctx.get("occupancy", 0) / ctx["capacity"]) if ctx.get("capacity") else 0,
        "density": str(ctx.get("density", 0.0)).replace(".", ","),
        "temp": temp, "heat_index": temp + 4, "wind": wind, "wind_avg": max(5, wind - 18),
        "alert": ctx.get("alert") or "amarilla",
    })
    return s


def _strip_accents(text: str) -> str:
    kept = (c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn" or c == "\u0303")
    return unicodedata.normalize("NFC", "".join(kept))  # quita tildes pero respeta la ñ


def _typo(rng: random.Random, word: str) -> str:
    if len(word) < 5:
        return word
    i = rng.randint(1, len(word) - 3)
    mode = rng.random()
    if mode < 0.5:
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]  # letras bailadas
    if mode < 0.8:
        return word[:i] + word[i + 1:]                           # letra comida
    return word[:i] + word[i] + word[i:]                         # letra repetida


def _noise(rng: random.Random, text: str, lang: str, level: float) -> str:
    """Ensucia un mensaje de público: faltas, abreviaturas, mayúsculas, emojis."""
    if lang == "es" and rng.random() < 0.7 * level:
        text = _strip_accents(text)
    if lang == "es" and rng.random() < 0.5 * level:
        for a, b in SHORTHAND:
            text = text.replace(a, b)
    if lang == "en" and rng.random() < 0.5 * level:
        text = text.replace("please", "pls").replace("people", "ppl").replace("you", "u")
    words = text.split(" ")
    for _ in range(rng.choice([0, 1, 1, 2]) if level > 0.3 else 0):
        k = rng.randrange(len(words))
        words[k] = _typo(rng, words[k])
    text = " ".join(words)
    if rng.random() < 0.6 * level:
        text = text.replace(",", "").replace("¿", "").replace("¡", "")
    roll = rng.random()
    if roll < 0.2 * level:
        text = text.upper()
    elif roll < 0.7:
        text = text.lower()
    if rng.random() < 0.5 * level:
        text += rng.choice({"es": ["!!!", "!!", "...", " ya", " rapido", " porfa"], "en": ["!!!", "!!", " pls", " hurry"]}.get(lang, ["!!!", "!!"]))
    if rng.random() < 0.5 * level:
        text += " " + "".join(rng.choice(EMOJIS) for _ in range(rng.randint(1, 3)))
    return text.strip()


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _core(rng: random.Random, type_id: str, voice: str, lang: str = "es") -> tuple[str, str]:
    """Devuelve (plantilla, idioma efectivo). Si el tipo no tiene esa voz o idioma, cae al más cercano."""
    entry = CORE[type_id]
    if voice == "public":
        if lang in ("fr", "de", "pt"):
            pool = OTHER_LANG.get(type_id, {}).get(lang) or FAMILY_GENERIC[TAXONOMY[type_id].family.value][lang]
            return rng.choice(pool), lang
        if lang == "en" and "en" in entry:
            return rng.choice(entry["en"]), "en"
        if "public" in entry:
            return rng.choice(entry["public"]), "es"
        return rng.choice(entry["staff"]), "es"
    return rng.choice(entry.get(voice) or entry["staff"]), "es"


def voices_of(type_id: str) -> list[str]:
    return [v for v in ("staff", "public", "sensor") if v in CORE[type_id]]


def _staff_kind(type_id: str, rng: random.Random) -> str:
    needs = list(TAXONOMY[type_id].needs) or ["security"]
    fam = TAXONOMY[type_id].family.value
    if fam in ("medical",):
        return "medical"
    if fam in ("infra",):
        return "tech" if "tech" in needs else needs[0]
    return rng.choice(needs) if rng.random() < 0.3 else needs[0]


# ------------------------------------------------------------------ avisos


def staff_report(rng: random.Random, type_id: str, zone: str, ctx: dict[str, Any] | None = None,
                 slots: dict[str, Any] | None = None) -> dict[str, Any]:
    """Personal del festival por radio, llamada o tecleado por el operador."""
    s = slots or _slots(rng, ctx)
    tpl, _ = _core(rng, type_id, "staff")
    core = tpl.format(**s)
    kind = _staff_kind(type_id, rng)
    if kind == "ambulance":
        kind = "medical"
    callsign = rng.choice(CALLSIGNS[kind]).format(k=rng.randint(1, 3))
    loc = staff_location(rng, zone, s)
    ask = rng.choice(RADIO_ASK[kind])
    channel = rng.choices(["radio", "voice", "operator"], weights=[55, 30, 15])[0]
    if channel == "radio":
        text = rng.choice([
            f"Control de {callsign}. {_cap(core)}. {_cap(loc)}. {ask}. Cambio.",
            f"{callsign} para Control, prioridad. {_cap(loc)}: {core}. {ask}, cambio.",
            f"Control, aquí {callsign}, {loc}. {_cap(core)}. {ask}. Cambio.",
        ])
    elif channel == "voice":
        text = rng.choice([
            f"Hola, soy {callsign}, estoy {loc}. {_cap(core)}. {ask}, por favor.",
            f"Oye, te llamo desde {loc.removeprefix('en ')}. {_cap(core)}. {ask}.",
        ])
    else:
        text = f"[{TAXONOMY[type_id].label}] {_cap(loc)}: {core}."
        callsign = "operador centro de control"
    return {"channel": channel, "source": callsign.lower() if channel != "operator" else callsign, "lang": "es", "text": text}


def public_report(rng: random.Random, type_id: str, zone: str, ctx: dict[str, Any] | None = None, *,
                  lang: str | None = None, location: str = "auto", slots: dict[str, Any] | None = None,
                  noise: float | None = None) -> dict[str, Any]:
    """Asistente por WhatsApp o SMS. `location`: exact | vague | none | auto."""
    s = slots or _slots(rng, ctx)
    tpl, lang = _core(rng, type_id, "public", lang or _pick_lang(rng))
    core = tpl.format(**s)
    if location == "auto":
        location = rng.choices(["exact", "vague", "none"], weights=[55, 25, 20])[0]
    loc = ""
    if location == "exact":
        loc = public_location(rng, lang, zone)
    elif location == "vague":
        loc = rng.choice(LOC_VAGUE[lang]) if lang in LOC_VAGUE else ""
    urgent = rng.choice(URGENT_ES if lang == "es" else URGENT_EN if lang == "en" else [""])
    parts = [p for p in (urgent, core, loc) if p]
    if loc and rng.random() < 0.4:
        parts = [p for p in (urgent, loc, core) if p]
    text = _noise(rng, ", ".join(parts), lang, rng.uniform(0.3, 1.0) if noise is None else noise)
    channel = rng.choices(["whatsapp", "sms"], weights=[85, 15])[0]
    out = {"channel": channel, "source": "asistente" if lang == "es" else f"asistente ({lang})", "lang": lang, "text": text}
    if channel == "whatsapp" and location == "exact" and loc and rng.random() < 0.15:
        out["zone_hint"] = zone  # escaneó el QR de zona
    return out


def sensor_report(rng: random.Random, type_id: str, zone: str, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = dict(ctx or {}, zone=zone)
    tpl, _ = _core(rng, type_id, "sensor")
    source = "estación meteo" if TAXONOMY[type_id].family.value == "weather" else f"sensor {zone}"
    return {"channel": "sensor", "source": source, "lang": "es", "text": "SENSOR " + tpl.format(**_slots(rng, ctx)),
            "zone_hint": zone}


def primary_reports(rng: random.Random, type_id: str, zone: str, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Avisos limpios con los que nace un incidente: 1–3, mezclando voces disponibles."""
    voices = voices_of(type_id)
    first = rng.choice(voices)
    chosen = [first]
    for v in voices:
        if v != first and rng.random() < 0.35:
            chosen.append(v)
    out = []
    for v in chosen:
        if v == "staff":
            out.append(staff_report(rng, type_id, zone, ctx))
        elif v == "sensor":
            out.append(sensor_report(rng, type_id, zone, ctx))
        else:
            out.append(public_report(rng, type_id, zone, ctx, location="exact" if len(chosen) == 1 else "auto"))
    return out


AMBIGUOUS: dict[str, list[str]] = {
    "crowd": ["hay problemas {where}", "{where} hay mucho lío, la gente está muy nerviosa", "algo pasa {where}, mucha gente empujando"],
    "medical": ["necesitamos ayuda aquí YA", "hay alguien que está mal {where}", "venid rápido por favor es urgente"],
    "weather": ["esto se está poniendo muy feo {where}", "con este tiempo aquí va a pasar algo"],
    "aggression": ["hay lío {where}, mandad a alguien", "está pasando algo chungo con unos tíos {where}"],
    "supply": ["aquí no queda nada y la gente se está calentando", "se ha acabado {where} y hay mucha cola"],
    "infra": ["algo se ha roto {where}", "no funciona nada {where}", "hay un problema técnico {where}, no sé qué es"],
    "resource": ["Control, tenemos un problema con un vehículo, os cuento luego", "hay algo parado {where} que no debería"],
    "info": ["hay alguien perdido {where}", "la gente anda diciendo cosas raras {where}"],
    "external": ["hay un problema en la salida", "algo raro {where}, no sé si es importante"],
}


def ambiguous_report(rng: random.Random, type_id: str, zone: str) -> dict[str, Any]:
    """Aviso verdadero pero sin el qué o sin el dónde («hay problemas en la entrada» sin decir cuál)."""
    fam = TAXONOMY[type_id].family.value
    if zone.startswith("gate_"):
        where = rng.choice(ENTRANCE_VAGUE)
    else:
        where = {"front_pit": "por el escenario", "backstage": "por el escenario", "food": "por la zona de barras",
                 "toilets": "por la zona de barras y baños"}.get(zone, rng.choice(["por aquí", "donde estamos nosotros", "en mi zona"]))
    text = rng.choice(AMBIGUOUS[fam]).format(where=where)
    if rng.random() < 0.35:
        return {"channel": "radio", "source": f"voluntarios {rng.randint(1, 3)}", "lang": "es",
                "text": f"Control de Voluntarios. {_cap(text)}. Eh... no veo bien desde aquí. Cambio."}
    return {"channel": rng.choice(["whatsapp", "whatsapp", "sms"]), "source": "asistente", "lang": "es",
            "text": _noise(rng, text, "es", 0.8)}


RAMBLE_BEFORE = [
    "Hola buenas, perdonad que moleste, no sé si este es el número correcto. Estamos aquí desde las cinco con unos amigos y la verdad es que todo muy bien organizado, solo que",
    "Buenas noches, quería comentar varias cosas. Lo primero que el sonido se oye regular desde atrás. Lo segundo, y no sé si tiene importancia,",
    "Hola! Una pregunta, ¿a qué hora sale el último bus? Es que venimos de fuera. Ah y otra cosa,",
]
RAMBLE_AFTER = [
    "Bueno eso, y que si se puede pagar con tarjeta en las barras. Gracias!",
    "En fin, que a ver si lo miráis. Por cierto, ¿dónde están las taquillas de objetos perdidos?",
    "Igual no es nada, vosotros sabréis. Un saludo y enhorabuena por el festival.",
]


def buried_report(rng: random.Random, type_id: str, zone: str, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """El dato clave va enterrado en mitad de un mensaje largo y educado."""
    tpl, _ = _core(rng, type_id, "public", "es")
    core = tpl.format(**_slots(rng, ctx))
    loc = public_location(rng, "es", zone)
    text = f"{rng.choice(RAMBLE_BEFORE)} {core} {loc}. {rng.choice(RAMBLE_AFTER)}"
    return {"channel": "whatsapp", "source": "asistente", "lang": "es", "text": text}


DETAIL_MISMATCH = ["creo que son dos personas", "es una persona sola", "lleva así unos {min} minutos", "acaba de pasar ahora mismo",
                   "ya hay gente de seguridad mirando", "no hay nadie del festival por aquí"]


def duplicate_reports(rng: random.Random, type_id: str, zone: str, ctx: dict[str, Any] | None = None,
                      k: int = 2, base_slots: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """El mismo incidente contado por otras personas: cambia el idioma, los detalles (edad, número,
    color) no coinciden y a veces la ubicación apunta a la zona de al lado."""
    out = []
    avoid = base_slots or _slots(rng, ctx)
    staff_used = False
    for _ in range(k):
        s = _slots(rng, ctx, avoid=avoid)
        where = rng.choice(NEIGHBORS[zone]) if rng.random() < 0.3 else zone
        if "public" in CORE[type_id] and (staff_used or rng.random() < 0.75):
            r = public_report(rng, type_id, where, ctx, slots=s, location=rng.choice(["exact", "exact", "vague"]))
            if r["lang"] == "es" and rng.random() < 0.5:
                r["text"] += " " + _noise(rng, rng.choice(DETAIL_MISMATCH).format(**s), "es", 0.6)
        else:
            r = staff_report(rng, type_id, where, ctx, slots=s)
            staff_used = True
        if where != zone:
            r.pop("zone_hint", None)
        out.append(r)
        avoid = s
    return out


CONTRA_RESOLVED_PUBLIC = ["falsa alarma lo de antes {loc}, ya está bien", "lo de {loc} ya está, se ha levantado solo y se ha ido",
                          "no mandéis a nadie {loc}, no era nada"]
CONTRA_RESOLVED_STAFF = ["Control de {cs}. Lo de {loc} está controlado, no mandéis más gente. Cambio.",
                         "{cs} para Control. {loc_cap} sin novedad, yo no veo nada de lo que decís. Cambio."]
CONTRA_DOWNPLAY = ["no es para tanto lo de {loc}, están exagerando", "lo de {loc} son cuatro gatos, no pasa nada grave"]


def contradictory_report(rng: random.Random, type_id: str, zone: str, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Aviso que contradice a los anteriores mientras el incidente sigue vivo: «ya está resuelto»,
    «no es para tanto» o el mismo hecho situado en otra zona que no es vecina."""
    kind = rng.choice(["resolved", "resolved_staff", "downplay", "other_zone"])
    loc = public_location(rng, "es", zone)
    if kind == "other_zone":
        far = [z for z in LOC_STAFF if z != zone and z not in NEIGHBORS[zone] and not z.startswith("medical")]
        r = public_report(rng, type_id, rng.choice(far), ctx, lang="es", location="exact") if "public" in CORE[type_id] \
            else staff_report(rng, type_id, rng.choice(far), ctx)
        r.pop("zone_hint", None)
        return r
    if kind == "resolved_staff":
        cs = rng.choice(CALLSIGNS["security"]).format(k=rng.randint(1, 5))
        staff_loc = staff_location(rng, zone, {"side": "centro"})
        text = rng.choice(CONTRA_RESOLVED_STAFF).format(cs=cs, loc=staff_loc, loc_cap=_cap(staff_loc))
        return {"channel": "radio", "source": cs.lower(), "lang": "es", "text": text}
    pool = CONTRA_RESOLVED_PUBLIC if kind == "resolved" else CONTRA_DOWNPLAY
    return {"channel": "whatsapp", "source": "asistente", "lang": "es",
            "text": _noise(rng, rng.choice(pool).format(loc=loc), "es", 0.6)}


JOKES = [
    ("es", "jajaja hay un zombie en la pista {loc} 🧟 mandad al ejército"),
    ("es", "SOCORRO mi amigo Dani se ha quedado sin cerveza, es una emergencia nacional 🍺😂"),
    ("es", "hay una bomba... de sabor en el puesto de tacos 🌮🔥 jajaja"),
    ("es", "se ha desmayado mi dignidad {loc} jaja"),
    ("en", "help there's a guy dancing so badly {loc} it should be illegal 😂"),
    ("en", "emergency: my girlfriend wants to leave before the headliner lol"),
]
MISTAKES = [
    ("es", "creo que hay humo {loc}, huele a quemado"),                # es la máquina de humo o una parrilla
    ("es", "he oído como disparos {loc}!!"),                           # eran petardos o pirotecnia del show
    ("es", "hay un chico tirado en el suelo {loc} que no se mueve"),   # estaba durmiendo y se levanta
    ("en", "I think someone fainted {loc} but I'm not sure, maybe he's just sitting down"),
    ("es", "me han dicho que han cerrado todas las salidas, es verdad??"),
]


def false_alarm_report(rng: random.Random, zone: str | None = None, kind: str | None = None) -> dict[str, Any]:
    """Broma (joke), error de buena fe (mistake) o lectura espuria de sensor (sensor)."""
    kind = kind or rng.choice(["joke", "mistake"])
    zone = zone or rng.choice(list(LOC_PUBLIC["es"]))
    if kind == "sensor":
        area = ZONES[zone]["area_m2"]
        return {"channel": "sensor", "source": f"sensor {zone}", "lang": "es", "zone_hint": zone,
                "text": f"SENSOR aforo {zone}: densidad {rng.choice(['9,8', '11,2', '0,0', '14,5'])} p/m² "
                        f"(1 muestra aislada; lectura anterior {str(round(rng.uniform(0.4, 1.6), 1)).replace('.', ',')} p/m², área {area} m²)"}
    lang, tpl = rng.choice(JOKES if kind == "joke" else MISTAKES)
    loc = public_location(rng, lang, zone)
    text = tpl.format(loc=loc)
    return {"channel": "whatsapp", "source": "asistente" if lang == "es" else f"asistente ({lang})", "lang": lang,
            "text": text if kind == "joke" else _noise(rng, text, lang, 0.5)}
