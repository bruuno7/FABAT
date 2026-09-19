# Protocolos del agente de recogida — hoja de validación

> **⚠ AVISO DE SEGURIDAD.** Son instrucciones de apoyo para una **SIMULACIÓN de hackathon**. **No sustituyen
> al 112 ni a la formación en primeros auxilios.** En un despliegue real las valida y firma la dirección
> sanitaria del evento (y el 112 de la comunidad). Nada de esto se ha probado con pacientes ni con público.

Generado desde `protocolos.json` con `python3 -m motor.protocolos.render_md`. **No editar a mano:** los cambios
se hacen en el JSON y se regenera. Fuentes y lo que no se pudo verificar: `FUENTES.md`.

## Cómo validar esto en 15 minutos (Talía)

| Min | Parte | Qué mirar |
|---|---|---|
| 3 | **A. Decisiones** | Siete puntos donde las fuentes se contradicen o donde he decidido yo. Necesito un sí o un no. |
| 6 | **B. Instrucciones pendientes** | 33 textos que NO estaban en la lista validada del Anexo C. Casilla por fila. Las 14 ya validadas solo necesitan un vistazo al inglés. |
| 5 | **C. Protocolos** | Sobre todo los 8 médicos: ¿las preguntas son las correctas y en ese orden?, ¿las señales de alarma disparan lo que deben? |
| 1 | **D. Lo que el agente nunca dice** | Lista corta; tachar o añadir. |

**Leyenda.** ✔ = redacción validada por la experta del consejo (Anexo C de `consejo/seguridad-eventos.md`), copiada
literal. **⚠ = extrapolación mía: no está literalmente en una fuente** (traducción, resumen, umbral, redacción
o decisión de diseño). Todo el inglés es traducción mía, fija y pretraducida: cuenta como ⚠ aunque el español esté validado.
**⚠ general:** las severidades (1–10), los recursos que se piden y el «tipo de Mando» NO salen de guías clínicas: copian
o aproximan la taxonomía del simulador. Y los disparadores (palabras clave) son una red de seguridad por subcadena,
sin acentos ni mayúsculas; no hace falta validarlos.

Cómo lee el agente cada protocolo: pregunta en orden; **envía en cuanto tiene los datos de «Enviar con»**, sin
esperar al resto; tras cada respuesta mira las señales de alarma **en orden y se queda con la primera que se
cumple**; «no sé» en una pregunta vital cuenta como la respuesta peligrosa; con una señal de «enviar ya» deja de
hacer preguntas no críticas. Nunca diagnostica: recoge hechos (responde / respira / sangra mucho).

## A. Decisiones que necesitan criterio sanitario

| # | Asunto | Qué dicen las fuentes | Qué he puesto | ☐ validado ☐ cambiar |
|---|---|---|---|---|
| 1 | **Hielo en el golpe de calor** | SAMUR: «no enfriar directamente con hielo». ERC 2021: vale cualquier técnica disponible, incluidas bolsas de hielo. NHS: bolsas frías *envueltas* en axilas y cuello. | «Si hay hielo o bolsas frías, envuélvelas en tela y ponlas en cuello y axilas.» | ☐ validado ☐ cambiar |
| 2 | **Apósito empapado** | SAMUR y guion telefónico MCW: no retirar, poner otro encima. St John Ambulance: retirar y poner uno nuevo. ERC 2021 no entra. | No retirar (SAMUR). | ☐ validado ☐ cambiar |
| 3 | **Agua a un intoxicado consciente** | NHS: agua a sorbos si está consciente y traga. SAMUR: no dar de beber. | No se menciona el agua; solo «ni comida, ni más alcohol, ni café». | ☐ validado ☐ cambiar |
| 4 | **Autoinyector de adrenalina** | NHS lo pone como primer paso para el público; ERC 2021: segunda dosis a los 5 min. | Única instrucción que toca medicación, y solo el dispositivo propio de la persona. ¿Se mantiene? | ☐ validado ☐ cambiar |
| 5 | **RCP solo con las manos siempre** | ERC 2021: si no puedes ventilar, compresiones continuas. MCW usa ventilaciones en ahogamiento, atragantamiento y sobredosis. | Siempre solo manos (un desconocido, en un festival, guiado por texto o voz). | ☐ validado ☐ cambiar |
| 6 | **Collarín y movilización** | SAMUR describe un collarín improvisado. ERC 2021: collarín NO recomendado; que la persona mantenga quieto el cuello. | ERC: no mover, no collarín. | ☐ validado ☐ cambiar |
| 7 | **Profundidad de las compresiones** | ERC 2021 y St John: 5–6 cm, 100–120/min. La web de Cruz Roja Española abierta aún dice «unos 4 cm» (texto antiguo). | «Unos 5 centímetros, unas dos veces por segundo.» | ☐ validado ☐ cambiar |


## B. Instrucciones al público (47)

### B1. Pendientes de validar (33) — todas llevan ⚠

| Clave | Pasos (texto exacto que dirá el agente) | Fuente principal | ⚠ Qué es mío | ☐ validado ☐ cambiar |
|---|---|---|---|---|
| `cpr_hands_only` | 1. Pon el móvil en altavoz y déjalo junto a la persona.<br>2. Ponla boca arriba en el suelo y arrodíllate a su lado.<br>3. Pon el talón de una mano en el centro del pecho y la otra mano encima.<br>4. Con los brazos rectos, aprieta fuerte y rápido, sin parar.<br>5. Hunde el pecho unos 5 centímetros, unas dos veces por segundo. Cuenta en voz alta.<br>6. Deja que el pecho suba del todo después de cada compresión.<br>7. Si te cansas, que otra persona te releve sin parar.<br>8. Sigue hasta que el equipo sanitario te releve. | [genoplivning.dk](https://genoplivning.dk/wp-content/uploads/2021/03/04_Basic-Life-Support.pdf), [mcw.edu](https://www.mcw.edu/-/media/MCW/Departments/Emergency-Medicine/EMS/Telecommunicator-CPR-Program-Dispatch-Protocols-In-House.pdf), [sja.org.uk](https://www.sja.org.uk/first-aid-advice/cpr/) | ⚠ Traducción y simplificación propias de ERC 2021 (centro del pecho, 5-6 cm, 100-120/min, reexpansión completa, altavoz) y del guion de RCP telefónica de MCW. «Unos 5 cm» y «dos veces por segundo» son redondeos míos de 5-6 cm y 100-120/min. | ☐ validado ☐ cambiar |
| `aed_arrives` | 1. Cuando llegue el desfibrilador, enciéndelo y haz lo que diga.<br>2. Pega los parches en el pecho desnudo, como indica el dibujo.<br>3. Que nadie toque a la persona mientras analiza o da la descarga.<br>4. Después, sigue con las compresiones enseguida. | [genoplivning.dk](https://genoplivning.dk/wp-content/uploads/2021/03/04_Basic-Life-Support.pdf) | ⚠ Traducción resumida propia de la sección «When and how to use an AED» de ERC 2021. | ☐ validado ☐ cambiar |
| `recovery_position_steps` | 1. Arrodíllate a su lado y estírale las piernas.<br>2. El brazo más cercano a ti, en ángulo recto con la palma hacia arriba.<br>3. El otro brazo cruzado sobre el pecho, con el dorso de la mano contra su mejilla.<br>4. Dobla la rodilla más alejada y tira de ella para girar a la persona hacia ti.<br>5. Échale la cabeza un poco hacia atrás para que respire bien.<br>6. Si se ha dado un golpe fuerte en la cabeza o el cuello, no la muevas salvo que vomite o no respire bien. | [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf), [www2.cruzroja.es](https://www2.cruzroja.es/web/ahora/-/que-es-la-posicion-lateral-de-seguridad-y-cuando-se-utiliza), [sja.org.uk](https://www.sja.org.uk/first-aid-advice/recovery-position/) | ⚠ Pasos 1-5: traducción resumida de ERC 2021 Primeros auxilios. Paso 6: síntesis propia de Cruz Roja («no conviene moverla si se sospecha de lesiones graves en la columna…») y de St John (si no mantiene la vía aérea, se coloca igualmente). | ☐ validado ☐ cambiar |
| `stay_with_person` | 1. Quédate con la persona hasta que llegue el equipo.<br>2. Si deja de responder o de respirar bien, dímelo enseguida. | [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) | ⚠ Redacción propia; SAMUR solo dice «nunca deje sola a la víctima» y avisar de los cambios. | ☐ validado ☐ cambiar |
| `choking_cough` | 1. Anímale a toser fuerte.<br>2. No le des golpes en la espalda mientras pueda toser.<br>3. Si deja de poder toser o hablar, dímelo enseguida. | [genoplivning.dk](https://genoplivning.dk/wp-content/uploads/2021/03/04_Basic-Life-Support.pdf), [mcw.edu](https://www.mcw.edu/-/media/MCW/Departments/Emergency-Medicine/EMS/Telecommunicator-CPR-Program-Dispatch-Protocols-In-House.pdf) | ⚠ ERC dice «Encourage the victim to cough» y reserva golpes y compresiones para la tos ineficaz; el paso 2 es mi redacción en negativo de esa regla. | ☐ validado ☐ cambiar |
| `choking_back_blows` | 1. Ponte a su lado e inclínala hacia delante.<br>2. Dale hasta 5 golpes fuertes entre los omóplatos con el talón de la mano.<br>3. Si no sale: ponte detrás, rodéale la cintura y pon el puño entre el ombligo y las costillas.<br>4. Agarra el puño con la otra mano y tira fuerte hacia dentro y hacia arriba, hasta 5 veces.<br>5. Alterna 5 golpes y 5 compresiones hasta que lo expulse.<br>6. Si deja de responder, túmbala en el suelo y dímelo: te guío con las compresiones en el pecho. | [genoplivning.dk](https://genoplivning.dk/wp-content/uploads/2021/03/04_Basic-Life-Support.pdf), [sja.org.uk](https://www.sja.org.uk/first-aid-advice/choking/) | ⚠ Traducción propia, casi literal, de la sección «Foreign body airway obstruction» de ERC 2021. | ☐ validado ☐ cambiar |
| `breathing_sit_up` | 1. Que se siente, un poco inclinada hacia delante, y aflójale la ropa del cuello.<br>2. Si tiene su inhalador, ayúdale a usarlo.<br>3. No la dejes sola. Si deja de responder, dímelo. | [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf), [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) | ⚠ ERC 2021: «Assist individuals with asthma who are experiencing difficulty in breathing with their bronchodilator administration». SAMUR: posición semisentada y aflojar ropa. «Inclinada hacia delante» es añadido mío. | ☐ validado ☐ cambiar |
| `allergy_wait` | 1. Que se tumbe. Si le cuesta respirar, que se quede sentada.<br>2. Que no se ponga de pie ni camine, aunque se encuentre mejor.<br>3. No le des de comer ni de beber.<br>4. No la dejes sola. Si deja de responder, dímelo. | [nhs.uk](https://www.nhs.uk/conditions/anaphylaxis/), [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) | ⚠ Traducción resumida propia de NHS (Anaphylaxis) y SAMUR (Reacciones alérgicas). | ☐ validado ☐ cambiar |
| `bleeding_detail` | 1. Siéntala o túmbala.<br>2. Si la prenda se empapa, pon otra encima sin quitar la primera y aprieta más fuerte.<br>3. No le des de comer ni de beber.<br>4. Si se marea, túmbala y súbele las piernas. | [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf), [mcw.edu](https://www.mcw.edu/-/media/MCW/Departments/Emergency-Medicine/EMS/Telecommunicator-CPR-Program-Dispatch-Protocols-In-House.pdf), [sja.org.uk](https://www.sja.org.uk/first-aid-advice/severe-bleeding/) | ⚠ Traducción resumida propia de SAMUR, capítulo Hemorragias. OJO: St John Ambulance dice lo contrario en el paso 2 (retirar el apósito empapado y poner uno nuevo); SAMUR y el guion telefónico de MCW dicen no retirar. Se sigue a SAMUR. El torniquete NO se indica al público (ERC: fabricado y con formación). | ☐ validado ☐ cambiar |
| `bleeding_object` | 1. No saques lo que tenga clavado.<br>2. Aprieta a los dos lados del objeto, juntando los bordes de la herida. | [sja.org.uk](https://www.sja.org.uk/first-aid-advice/severe-bleeding/) | ⚠ Traducción propia de St John Ambulance. | ☐ validado ☐ cambiar |
| `allergy_autoinjector` | 1. Si lleva su inyector de adrenalina, que se lo ponga ya; ayúdale si hace falta.<br>2. Si a los 5 minutos no mejora y tiene otro, que se ponga el segundo. | [nhs.uk](https://www.nhs.uk/conditions/anaphylaxis/), [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf) | ⚠ DECISIÓN A VALIDAR: es la única instrucción que toca medicación. Es el dispositivo propio y prescrito de la persona; NHS lo indica al público y ERC 2021 recoge la segunda dosis a los 5 min. El agente no recomienda ningún otro fármaco. | ☐ validado ☐ cambiar |
| `seizure_extra` | 1. Ponle algo blando debajo de la cabeza.<br>2. Mira la hora: importa cuánto dura.<br>3. No le des agua ni comida hasta que esté del todo despierta.<br>4. Quédate con ella hasta que llegue el equipo. | [epilepsy.org.uk](https://www.epilepsy.org.uk/info/first-aid/tonic-clonic-convulsive-seizures-first-aid), [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) | ⚠ Traducción resumida propia de Epilepsy Action y SAMUR. | ☐ validado ☐ cambiar |
| `heat_cool_now` | 1. Llévala a la sombra ya y quítale la ropa que sobre.<br>2. Échale agua por la piel y la ropa y abanícala sin parar.<br>3. Si hay hielo o bolsas frías, envuélvelas en tela y ponlas en cuello y axilas.<br>4. No le des de beber si está confusa o no traga bien.<br>5. No la dejes sola. Si deja de responder, dímelo. | [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf), [nhs.uk](https://www.nhs.uk/conditions/heat-exhaustion-heatstroke/), [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) | ⚠ Síntesis propia de ERC 2021 («commence additional cooling using any technique immediately available»), NHS (agua, abanicar, bolsas frías envueltas en axilas y cuello) y SAMUR. OJO: SAMUR dice «no enfriar directamente con hielo» y ERC admite hielo; por eso «envueltas en tela». A decidir por Talía. | ☐ validado ☐ cambiar |
| `faint_lie_down` | 1. Túmbala boca arriba y súbele las piernas.<br>2. Aflójale la ropa apretada y que le dé el aire. Que la gente no se agolpe.<br>3. No le des de comer ni de beber hasta que esté del todo recuperada.<br>4. Cuando se recupere, que se siente despacio antes de ponerse de pie. | [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf), [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf) | ⚠ Traducción resumida propia de SAMUR, capítulo Lipotimia. | ☐ validado ☐ cambiar |
| `intox_stay` | 1. No la dejes sola: puede ahogarse con su vómito.<br>2. Si está despierta, siéntala. Si se duerme y no despierta, ponla de lado.<br>3. No le des comida, más alcohol ni café, y no la hagas vomitar.<br>4. Abrígala. No la metas en agua fría. | [nhs.uk](https://www.nhs.uk/conditions/alcohol-poisoning/), [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) | ⚠ Traducción resumida propia de NHS (Alcohol poisoning) y SAMUR. OJO: NHS permite agua a sorbos si está consciente y traga; SAMUR dice no dar de beber. Se ha omitido el agua. A decidir por Talía. | ☐ validado ☐ cambiar |
| `trauma_do_not_move` | 1. No la muevas, salvo que ahí corra peligro.<br>2. Pídele que no mueva la cabeza ni el cuello.<br>3. No intentes colocarle un hueso torcido.<br>4. No le des de comer ni de beber. Quédate con ella. | [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf), [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf), [www2.cruzroja.es](https://www2.cruzroja.es/web/ahora/-/que-es-la-posicion-lateral-de-seguridad-y-cuando-se-utiliza) | ⚠ Síntesis propia de ERC 2021 (que mantenga el cuello estable por sí misma; no alinear fracturas; collarín no recomendado) y Cruz Roja/SAMUR (no mover). OJO: SAMUR describe un collarín improvisado; ERC 2021 lo desaconseja. Se sigue a ERC. | ☐ validado ☐ cambiar |
| `crowd_if_fallen` | 1. Si te caes, hazte una bola para protegerte.<br>2. Levántate en cuanto puedas. | [cdc.gov](https://www.cdc.gov/yellow-book/hcp/travel-for-work-other/mass-gatherings.html) | ⚠ Traducción literal propia de CDC Yellow Book. | ☐ validado ☐ cambiar |
| `crowd_leave_early` | 1. Si notas gente pegada a los dos hombros a la vez, sal de ahí ya.<br>2. Ve hacia donde haya menos gente, andando y sin empujar.<br>3. Aléjate de vallas y paredes.<br>4. No dejes mochilas ni bolsas en el suelo. | [kqed.org](https://www.kqed.org/news/11930646/8-tips-to-follow-if-youre-trapped-in-a-crushing-crowd), [time.com](https://time.com/6226680/how-to-survive-crowd-crush-south-korea/), [gkstill.com](https://www.gkstill.com/Support/crowd-density/CrowdDensity-1.html) | ⚠ Traducción resumida propia de los consejos de Mehdi Moussaïd (Max Planck) en KQED y de G. Keith Still en Time («si parece demasiado lleno, no vayas»). | ☐ validado ☐ cambiar |
| `queue_wait` | 1. No empujes ni intentes colarte.<br>2. Si quieres salir de la cola, hazlo hacia un lado, nunca contra la gente que viene detrás.<br>3. Si alguien se encuentra mal, avisa al personal con chaleco. | [hse.gov.uk](https://www.hse.gov.uk/event-safety/crowd-management-controls.htm) | ⚠ Redacción propia. HSE lo dice como obligación del organizador («a safe way people can get out of a queue without having to move against those queuing behind them»), no como consejo al público. | ☐ validado ☐ cambiar |
| `smoke_low` | 1. Si hay humo, agáchate: junto al suelo el aire está más limpio.<br>2. No vuelvas a por tus cosas.<br>3. Si huele a gas, no enciendas mecheros ni nada eléctrico. | [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf), [112.jcyl.es](https://112.jcyl.es/web/es/consejos-recomendaciones/lugares-publicos.html), [112.cantabria.es](https://112.cantabria.es/consejos-de-autoproteccion/grandes-aglomeraciones) | ⚠ Traducción resumida propia de SAMUR (inhalación de humo) y de 112 Castilla y León / Cantabria (no recoger pertenencias). | ☐ validado ☐ cambiar |
| `wind_away` | 1. Aléjate de lo que pueda caer: torres, pantallas, carpas y vallas.<br>2. No te refugies junto a muros, vallas ni árboles.<br>3. No toques cables caídos. | [112.jcyl.es](https://112.jcyl.es/web/es/consejos-recomendaciones/vientos.html), [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/riscos_naturals/ventades/index.html) | ⚠ Adaptación propia al recinto de los consejos de 112 Castilla y León y Protección Civil de Cataluña (andamios, anuncios, muros, árboles, cables). | ☐ validado ☐ cambiar |
| `weather_lightning` | 1. Las carpas y las tiendas no protegen de los rayos.<br>2. Si tienes cerca un edificio cerrado o un coche cerrado, métete dentro.<br>3. Aléjate de árboles, torres, farolas y vallas metálicas.<br>4. Espera 30 minutos desde el último trueno antes de volver. | [weather.gov](https://www.weather.gov/safety/lightning-outdoors), [weather.gov](https://www.weather.gov/media/safety/lightning/Lightning_Safety_Toolkit_Outdoor_Venues.pdf), [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/riscos_naturals/tempestes_electriques/index.html), [112.castillalamancha.es](https://112.castillalamancha.es/proteccion-civil/consejos/tormentas-y-rayos) | ⚠ Traducción resumida propia de NWS y Protección Civil de Cataluña. OJO: en un recinto de 40.000 personas no hay refugio para todos; a dónde se manda a la gente lo decide el plan del evento, no el agente. Esta instrucción es solo para quien pregunta. | ☐ validado ☐ cambiar |
| `suspicious_move_first` | 1. Aléjate primero del objeto; seguimos hablando cuando estés lejos.<br>2. No avises tú a la gente de alrededor: lo hace el personal. | [gov.uk](https://www.gov.uk/government/publications/crowded-places-guidance/unattended-and-suspicious-items) | ⚠ La guía abierta (gov.uk) dice «do not use radios within 15 metres»; la mención a móviles solo la vi en un resumen de buscador de ProtectUK (página no abierta: 404). Por prudencia se pide alejarse antes de seguir usando el móvil. El paso 2 es criterio de la experta (Anexo C y NS-27), sin fuente abierta. | ☐ validado ☐ cambiar |
| `threat_noted` | 1. Gracias. Lo he anotado tal cual y ya está en control de seguridad.<br>2. No lo comentes con otras personas ni lo publiques. | [cruzroja.es](https://www.cruzroja.es/guiaprevencionNew/aviso-bomba.html), [gov.uk](https://www.gov.uk/government/publications/crowded-places-guidance/bomb-threats) | ⚠ Redacción propia a partir de Cruz Roja («toma nota lo más textual posible», «evita toda acción que pueda llevar a cundir el pánico») y gov.uk. El agente nunca valora la credibilidad (NS-27). | ☐ validado ☐ cambiar |
| `violet_unsafe` | 1. Si puedes, acércate a personal con chaleco o a un sitio con más gente.<br>2. Sigo aquí contigo. Te paso con una persona. | [violenciagenero.igualdad.gob.es](https://violenciagenero.igualdad.gob.es/wp-content/uploads/RECOMENDACIONES-PARA-LA-IMPLANTACION-DE-PUNTOS-VIOLETA_-maquetado.pdf) | ⚠ Redacción propia. La fuente pide «preservar la seguridad» y «no dejar sola a la persona agredida», pero no da un texto para quien sigue en riesgo. | ☐ validado ☐ cambiar |
| `spiking_self` | 1. No te quedes a solas: busca a alguien de confianza.<br>2. Id juntos hacia el personal con chaleco o el puesto médico.<br>3. Te paso con una persona. | [sspa.juntadeandalucia.es](https://www.sspa.juntadeandalucia.es/servicioandaluzdesalud/sites/default/files/sincfiles/wsas-media-mediafile_sasdocumento/2022/protocolo_sumision_quimica_15082022.pdf), [violenciagenero.igualdad.gob.es](https://violenciagenero.igualdad.gob.es/wp-content/uploads/RECOMENDACIONES-PARA-LA-IMPLANTACION-DE-PUNTOS-VIOLETA_-maquetado.pdf) | ⚠ Redacción propia a partir de «deben estar siempre acompañadas» (SAS 2022) y de las recomendaciones de puntos violeta. El «id hacia el puesto médico» es extrapolación al recinto. | ☐ validado ☐ cambiar |
| `spiking_other` | 1. No la dejes sola ni con desconocidos.<br>2. Si puede andar, acompáñala hacia el personal con chaleco o el puesto médico.<br>3. Si deja de responder pero respira, ponla de lado y dímelo. | [sspa.juntadeandalucia.es](https://www.sspa.juntadeandalucia.es/servicioandaluzdesalud/sites/default/files/sincfiles/wsas-media-mediafile_sasdocumento/2022/protocolo_sumision_quimica_15082022.pdf), [violenciagenero.igualdad.gob.es](https://violenciagenero.igualdad.gob.es/wp-content/uploads/RECOMENDACIONES-PARA-LA-IMPLANTACION-DE-PUNTOS-VIOLETA_-maquetado.pdf), [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf) | ⚠ Redacción propia a partir de SAS 2022 («siempre acompañadas») e Igualdad («si la víctima está somnolienta… se actuará con la mayor diligencia»). «Ni con desconocidos» es añadido mío. | ☐ validado ☐ cambiar |
| `vulnerable_stay` | 1. Quédate con ella, sin agobiarla.<br>2. Háblale despacio y con frases cortas.<br>3. Si hay mucho ruido, acompáñala a un sitio más tranquilo que esté cerca y dime cuál. | [ticketfairy.com](https://www.ticketfairy.com/blog/lost-child-and-vulnerable-persons-protocols-at-festivals) | ⚠ Adaptación propia de las pautas de Ticket Fairy (tono respetuoso, lenguaje sencillo, rincón tranquilo). Fuente de sector, no clínica. | ☐ validado ☐ cambiar |
| `vulnerable_searching` | 1. Quédate donde la viste por última vez.<br>2. Dinos cómo es y cómo va vestida. | [ticketfairy.com](https://www.ticketfairy.com/blog/lost-child-and-vulnerable-persons-protocols-at-festivals) | ⚠ Calco propio de la instrucción validada `lost_child_parent`, aplicada a adultos. | ☐ validado ☐ cambiar |
| `no_run` | 1. No corras, no grites y no empujes.<br>2. Camina hacia un lado, donde haya menos gente.<br>3. No reenvíes lo que has oído: en control lo estamos comprobando. | [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/mes_consells_dautoproteccio/grans_concentracions_persones/index.html) | ⚠ Paso 1 de Protección Civil de Cataluña («evita chillar, correr o empujar»). Pasos 2 y 3: redacción propia. | ☐ validado ☐ cambiar |
| `power_keep_away` | 1. No toques cables, cuadros eléctricos ni generadores.<br>2. Si ves chispas o huele a quemado, aléjate y avisa al personal con chaleco. | [hse.gov.uk](https://www.hse.gov.uk/event-safety/electrical-safety.htm), [112.jcyl.es](https://112.jcyl.es/web/es/consejos-recomendaciones/vientos.html) | ⚠ Redacción propia. HSE lo formula como deber del organizador (que el público no pueda tocar la instalación); 112 CyL: «no toque cables ni postes». | ☐ validado ☐ cambiar |
| `dark_stay` | 1. Si donde estás es seguro, quédate ahí.<br>2. Usa la linterna del móvil.<br>3. Si te mueves, hazlo despacio, sin correr ni empujar. | [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/mes_consells_dautoproteccio/grans_concentracions_persones/index.html) | ⚠ Redacción propia. Solo «sin correr ni empujar» sale de la fuente; lo demás es sentido común sin fuente abierta. | ☐ validado ☐ cambiar |
| `barrier_away` | 1. Aléjate de la valla y no te apoyes en ella.<br>2. Avisa al personal con chaleco. | [kqed.org](https://www.kqed.org/news/11930646/8-tips-to-follow-if-youre-trapped-in-a-crushing-crowd) | ⚠ Redacción propia; la fuente solo dice evitar paredes y objetos sólidos en una multitud densa. | ☐ validado ☐ cambiar |

### B2. Ya validadas en el Anexo C (14) — texto español literal; ⚠ solo el inglés

| Clave | Español (✔ validado) | Inglés (⚠ traducción mía) | Respaldo en fuente abierta | ☐ validado ☐ cambiar |
|---|---|---|---|---|
| `not_responding` | ✔ Quédate con la persona. Que otro vaya a por el personal con chaleco y pida un desfibrilador. Si no respira normal: aprieta fuerte y rápido en el centro del pecho, sin parar. | Stay with the person. Send someone else to fetch staff in a vest and ask for a defibrillator. If they are not breathing normally: push hard and fast on the centre of the chest, without stopping. | [genoplivning.dk](https://genoplivning.dk/wp-content/uploads/2021/03/04_Basic-Life-Support.pdf), [mcw.edu](https://www.mcw.edu/-/media/MCW/Departments/Emergency-Medicine/EMS/Telecommunicator-CPR-Program-Dispatch-Protocols-In-House.pdf) | ☐ validado ☐ cambiar |
| `unconscious_breathing` | ✔ Si respira, ponla de lado. No la dejes sola. Vigila que siga respirando. | If they are breathing, roll them onto their side. Do not leave them alone. Keep checking that they are still breathing. | [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf), [www2.cruzroja.es](https://www2.cruzroja.es/web/ahora/-/que-es-la-posicion-lateral-de-seguridad-y-cuando-se-utiliza), [sja.org.uk](https://www.sja.org.uk/first-aid-advice/recovery-position/) | ☐ validado ☐ cambiar |
| `crowd_pressure` | ✔ No empujes. Brazos delante del pecho. No te agaches. Sal en diagonal hacia los lados cuando afloje. | Do not push. Keep your arms in front of your chest. Do not bend down. Work your way out diagonally to the side when the pressure eases. | [cdc.gov](https://www.cdc.gov/yellow-book/hcp/travel-for-work-other/mass-gatherings.html), [kqed.org](https://www.kqed.org/news/11930646/8-tips-to-follow-if-youre-trapped-in-a-crushing-crowd), [time.com](https://time.com/6226680/how-to-survive-crowd-crush-south-korea/) | ☐ validado ☐ cambiar |
| `fire_or_structure` | ✔ Aléjate de ahí andando, sin correr, y no vuelvas. Avisa al personal con chaleco. | Walk away from there, without running, and do not go back. Tell staff in a vest. | [112.jcyl.es](https://112.jcyl.es/web/es/consejos-recomendaciones/lugares-publicos.html), [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/mes_consells_dautoproteccio/grans_concentracions_persones/index.html) | ☐ validado ☐ cambiar |
| `bleeding` | ✔ Aprieta fuerte sobre la herida con una prenda. No sueltes. | Press hard on the wound with a piece of clothing. Do not let go. | [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf), [mcw.edu](https://www.mcw.edu/-/media/MCW/Departments/Emergency-Medicine/EMS/Telecommunicator-CPR-Program-Dispatch-Protocols-In-House.pdf), [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) | ☐ validado ☐ cambiar |
| `seizure` | ✔ No la sujetes ni le metas nada en la boca. Aparta lo que pueda golpearla. Cuando pare, ponla de lado. | Do not hold them down or put anything in their mouth. Move away anything that could hurt them. When it stops, roll them onto their side. | [epilepsy.org.uk](https://www.epilepsy.org.uk/info/first-aid/tonic-clonic-convulsive-seizures-first-aid), [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf), [cruzroja.es](https://www.cruzroja.es/guiaprevencionNew/primeros-auxilios.html) | ☐ validado ☐ cambiar |
| `heat` | ✔ Llévala a la sombra. Mójale la piel y la ropa y abanícala. Si está despierta y traga bien, agua a sorbos. | Move them into the shade. Wet their skin and clothes and fan them. If they are awake and can swallow well, give sips of water. | [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf), [nhs.uk](https://www.nhs.uk/conditions/heat-exhaustion-heatstroke/), [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) | ☐ validado ☐ cambiar |
| `weather` | ✔ Aléjate de torres, carpas y vallas. | Keep away from towers, tents and fences. | [weather.gov](https://www.weather.gov/media/safety/lightning/Lightning_Safety_Toolkit_Outdoor_Venues.pdf), [112.jcyl.es](https://112.jcyl.es/web/es/consejos-recomendaciones/vientos.html) | ☐ validado ☐ cambiar |
| `suspicious_object` | ✔ No lo toques ni lo muevas. Aléjate y díselo al personal con chaleco. | Do not touch it or move it. Move away and tell staff in a vest. | [gov.uk](https://www.gov.uk/government/publications/crowded-places-guidance/unattended-and-suspicious-items) | ☐ validado ☐ cambiar |
| `aggression` | ✔ Aléjate y no te enfrentes. Ve hacia el personal con chaleco.<br>⚠ PROHIBIDA en violencia sexual (Anexo C). | Move away and do not confront anyone. Go towards staff in a vest. | [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) | ☐ validado ☐ cambiar |
| `violet` | ✔ Te creemos. No es culpa tuya. Si puedes, ve con alguien de confianza hacia el personal con chaleco. Te paso con una persona. | We believe you. It is not your fault. If you can, go with someone you trust towards staff in a vest. I am putting you through to a person. | [violenciagenero.igualdad.gob.es](https://violenciagenero.igualdad.gob.es/wp-content/uploads/RECOMENDACIONES-PARA-LA-IMPLANTACION-DE-PUNTOS-VIOLETA_-maquetado.pdf) | ☐ validado ☐ cambiar |
| `lost_child` | ✔ Quédate con el menor en ese sitio. No os mováis. Pide a otra persona que avise al personal con chaleco. | Stay with the child where you are. Do not move. Ask someone else to tell staff in a vest. | [ticketfairy.com](https://www.ticketfairy.com/blog/lost-child-and-vulnerable-persons-protocols-at-festivals) | ☐ validado ☐ cambiar |
| `lost_child_parent` | ✔ Quédate donde lo viste por última vez. Dinos edad y cómo va vestido. | Stay where you last saw them. Tell us their age and what they are wearing. | [ticketfairy.com](https://www.ticketfairy.com/blog/lost-child-and-vulnerable-persons-protocols-at-festivals) | ☐ validado ☐ cambiar |
| `generic_stay_safe` | ✔ Ponte en un sitio seguro. Si empeora, escribe otra vez. | Get to a safe place. If it gets worse, message again. | — (sin fuente abierta) | ☐ validado ☐ cambiar |

### B3. Inglés de las pendientes (para quien revise la traducción)

| Clave | Steps (EN) |
|---|---|
| `cpr_hands_only` | 1. Put your phone on speaker and leave it next to the person.<br>2. Lay them flat on their back on the ground and kneel by their side.<br>3. Put the heel of one hand on the centre of the chest and your other hand on top.<br>4. With your arms straight, push hard and fast, without stopping.<br>5. Push the chest down about 5 centimetres, about twice a second. Count out loud.<br>6. Let the chest come all the way up after each push.<br>7. If you get tired, have someone else take over without stopping.<br>8. Keep going until the medical team takes over. |
| `aed_arrives` | 1. When the defibrillator arrives, switch it on and do what it says.<br>2. Stick the pads on the bare chest as shown in the picture.<br>3. Nobody touches the person while it analyses or gives the shock.<br>4. Then go straight back to chest compressions. |
| `recovery_position_steps` | 1. Kneel beside them and straighten their legs.<br>2. Put the arm nearest you at a right angle, palm up.<br>3. Bring the other arm across the chest, back of the hand against their cheek.<br>4. Bend the far knee and pull on it to roll the person towards you.<br>5. Tilt the head back slightly so they can breathe.<br>6. If they took a hard blow to the head or neck, do not move them unless they vomit or cannot breathe well. |
| `stay_with_person` | 1. Stay with the person until the team arrives.<br>2. If they stop responding or breathing well, tell me at once. |
| `choking_cough` | 1. Encourage them to cough hard.<br>2. Do not hit their back while they can still cough.<br>3. If they can no longer cough or speak, tell me right away. |
| `choking_back_blows` | 1. Stand to their side and lean them forwards.<br>2. Give up to 5 sharp blows between the shoulder blades with the heel of your hand.<br>3. If it does not come out: stand behind them, put your arms round their waist and place your fist between the navel and the ribs.<br>4. Grasp your fist with the other hand and pull sharply inwards and upwards, up to 5 times.<br>5. Alternate 5 back blows and 5 abdominal thrusts until it comes out.<br>6. If they stop responding, lay them on the ground and tell me: I will guide you through chest compressions. |
| `breathing_sit_up` | 1. Have them sit up, leaning slightly forwards, and loosen clothing round the neck.<br>2. If they have their own inhaler, help them use it.<br>3. Do not leave them alone. If they stop responding, tell me. |
| `allergy_wait` | 1. Have them lie down. If breathing is hard, let them stay sitting up.<br>2. They must not stand or walk, even if they feel better.<br>3. No food or drink.<br>4. Do not leave them alone. If they stop responding, tell me. |
| `bleeding_detail` | 1. Sit or lay them down.<br>2. If the cloth soaks through, put another on top without removing the first and press harder.<br>3. No food or drink.<br>4. If they feel faint, lay them down and raise their legs. |
| `bleeding_object` | 1. Do not pull out anything stuck in the wound.<br>2. Press on either side of the object, pushing the edges of the wound together. |
| `allergy_autoinjector` | 1. If they carry their adrenaline auto-injector, they should use it now; help them if needed.<br>2. If they are no better after 5 minutes and have a second one, they should use it. |
| `seizure_extra` | 1. Put something soft under their head.<br>2. Check the time: how long it lasts matters.<br>3. No water or food until they are fully awake.<br>4. Stay with them until the team arrives. |
| `heat_cool_now` | 1. Move them into the shade now and take off any extra clothing.<br>2. Pour water over their skin and clothes and keep fanning them.<br>3. If there is ice or cold packs, wrap them in cloth and put them on the neck and armpits.<br>4. Do not give drinks if they are confused or cannot swallow well.<br>5. Do not leave them alone. If they stop responding, tell me. |
| `faint_lie_down` | 1. Lay them on their back and raise their legs.<br>2. Loosen tight clothing and give them air. Keep people from crowding round.<br>3. No food or drink until they have fully recovered.<br>4. When they recover, have them sit up slowly before standing. |
| `intox_stay` | 1. Do not leave them alone: they could choke on their vomit.<br>2. If awake, sit them up. If they pass out and will not wake, roll them onto their side.<br>3. No food, no more alcohol, no coffee, and do not make them vomit.<br>4. Keep them warm. Do not put them in cold water. |
| `trauma_do_not_move` | 1. Do not move them unless they are in danger where they are.<br>2. Ask them to keep their head and neck still.<br>3. Do not try to straighten a bent limb.<br>4. No food or drink. Stay with them. |
| `crowd_if_fallen` | 1. If you fall, protect yourself by curling into a ball.<br>2. Get up as soon as you can. |
| `crowd_leave_early` | 1. If you feel people pressed against both your shoulders at once, leave now.<br>2. Head for where there are fewer people, walking and without pushing.<br>3. Keep away from fences and walls.<br>4. Do not put backpacks or bags on the ground. |
| `queue_wait` | 1. Do not push or try to jump the queue.<br>2. If you want to leave the queue, step out to the side, never back against the people behind you.<br>3. If someone feels unwell, tell staff in a vest. |
| `smoke_low` | 1. If there is smoke, keep low: the air is cleaner near the ground.<br>2. Do not go back for your belongings.<br>3. If you smell gas, do not light anything or switch anything on. |
| `wind_away` | 1. Keep away from anything that could fall: towers, screens, tents and fences.<br>2. Do not shelter next to walls, fences or trees.<br>3. Do not touch fallen cables. |
| `weather_lightning` | 1. Tents and canopies do not protect you from lightning.<br>2. If a closed building or a closed car is near, get inside.<br>3. Keep away from trees, towers, light poles and metal fences.<br>4. Wait 30 minutes after the last thunder before going back. |
| `suspicious_move_first` | 1. Move away from the item first; we will carry on once you are well away.<br>2. Do not warn the people around you yourself: staff will do that. |
| `threat_noted` | 1. Thank you. I have written it down exactly and security control already has it.<br>2. Do not discuss it with others or post it. |
| `violet_unsafe` | 1. If you can, move towards staff in a vest or somewhere with more people.<br>2. I am still here with you. I am putting you through to a person. |
| `spiking_self` | 1. Do not stay on your own: find someone you trust.<br>2. Go together towards staff in a vest or the medical post.<br>3. I am putting you through to a person. |
| `spiking_other` | 1. Do not leave them alone or with strangers.<br>2. If they can walk, go with them towards staff in a vest or the medical post.<br>3. If they stop responding but are breathing, roll them onto their side and tell me. |
| `vulnerable_stay` | 1. Stay with them without crowding them.<br>2. Speak slowly, in short sentences.<br>3. If it is very noisy, take them somewhere quieter close by and tell me where. |
| `vulnerable_searching` | 1. Stay where you last saw them.<br>2. Tell us what they look like and what they are wearing. |
| `no_run` | 1. Do not run, shout or push.<br>2. Walk to the side, where there are fewer people.<br>3. Do not pass on what you heard: control is checking it. |
| `power_keep_away` | 1. Do not touch cables, electrical boxes or generators.<br>2. If you see sparks or smell burning, move away and tell staff in a vest. |
| `dark_stay` | 1. If where you are is safe, stay there.<br>2. Use your phone torch.<br>3. If you move, go slowly, without running or pushing. |
| `barrier_away` | 1. Move away from the barrier and do not lean on it.<br>2. Tell staff in a vest. |

## C. Protocolos (24)

Van ordenados de más a menos crítico: si un aviso encaja con varios, gana el que aparece antes.

### 1. Persona que no responde · `unresponsive_person`

Familia `medical` · tipo de Mando `cardiac_arrest` · **Enviar con:** `location_point` · **Avisa a:** medical_lead · **Externo:** ambulance (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Responde si le hablas fuerte y le tocas el hombro?**<br>Do they respond if you speak loudly and tap their shoulder?<br>`responsive` | sí / no / no sé | **sí** | — | reconocer parada: primera de las dos preguntas de la RCP telefónica (ERC 2021, SJA, MCW) |
| 3 | **¿Respira con normalidad? Mírale el pecho diez segundos.**<br>Are they breathing normally? Watch their chest for ten seconds.<br>`breathing_normal` | sí / no / no sé | **sí** | `responsive` = no o no sé | reconocer parada: segunda pregunta; no responde + no respira normal = RCP (ERC 2021) |
| 4 | **¿Cómo es su respiración: normal, a boqueadas o con ronquidos, o no respira?**<br>How is their breathing: normal, gasping or snoring, or not breathing?<br>`breathing_description` | opciones<br>`normal`, `gasping_or_noisy`, `none`, `unknown` | **sí** | `responsive` = no o no sé **y** `breathing_normal` = no sé | la respiración agónica (boqueadas, ronquidos, gemidos) se confunde con estar vivo y es parada (ERC 2021; guion MCW paso 3) |
| 5 | **¿Hay alguien contigo que pueda ir a por un desfibrilador?**<br>Is someone with you who can go and fetch a defibrillator?<br>`helper_available` | sí / no / no sé | no | — | quien hace compresiones no debe dejarlas; otro trae el DESA (ERC 2021, Anexo C) |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `responsive` = no o no sé **y** `breathing_normal` = no | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya** | `cpr_hands_only` |
| `responsive` = no o no sé **y** `breathing_description` = `gasping_or_noisy` o `none` o no sé | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya** | `cpr_hands_only` |
| `responsive` = no o no sé **y** `breathing_normal` = sí | **RIESGO VITAL** · severidad ≥ 8 · 1 sanitario · **enviar ya**<br>⚠ severity_min 8 es criterio propio: inconsciente que respira sigue siendo urgencia vital (vía aérea). | `unconscious_breathing` |
| `responsive` = no o no sé | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya**<br>⚠ «No sé» en un slot vital se trata como el peor caso: ERC acepta el sobretriaje («will moderately overtriage»). | `not_responding` |
| `responsive` = sí | sin riesgo vital · severidad ≥ 6 · 1 sanitario · **enviar ya**<br>⚠ Persona que sí responde (mareo, dolor en el pecho, desmayo recuperado): se envía sanitario igualmente; severidad 6 es criterio propio. | `stay_with_person` |

Instrucciones disponibles: `not_responding`, `cpr_hands_only`, `aed_arrives`, `unconscious_breathing`, `recovery_position_steps`, `stay_with_person`.

Fuentes: [genoplivning.dk](https://genoplivning.dk/wp-content/uploads/2021/03/04_Basic-Life-Support.pdf) · [mcw.edu](https://www.mcw.edu/-/media/MCW/Departments/Emergency-Medicine/EMS/Telecommunicator-CPR-Program-Dispatch-Protocols-In-House.pdf) · [sja.org.uk](https://www.sja.org.uk/first-aid-advice/cpr/) · [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf) · [theconversation.com](https://theconversation.com/112-y-061-asi-funcionan-los-telefonos-de-emergencias-sanitarias-243736)

**☐ validado ☐ cambiar:** ______________________________________________

### 2. Dificultad para respirar o atragantamiento · `breathing_choking`

Familia `medical` · tipo de Mando `anaphylaxis` · **Enviar con:** `location_point` · **Avisa a:** medical_lead · **Externo:** ambulance (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Puede hablar o toser?**<br>Can they speak or cough?<br>`can_speak_cough` | sí / no / no sé | **sí** | — | separa obstrucción leve de grave (ERC 2021; guion MCW: «Are they able to cough or able to speak?») |
| 3 | **¿Está despierta y te responde?**<br>Are they awake and answering you?<br>`responsive` | sí / no / no sé | **sí** | — | si no responde se pasa al protocolo de persona que no responde |
| 4 | **¿Qué pasó justo antes: comía, le picó algo, tiene asma?**<br>What happened just before: eating, a sting, do they have asthma?<br>`cause` | opciones<br>`eating`, `sting_or_allergy`, `asthma`, `crushed_in_crowd`, `smoke`, `unknown` | no | — | orienta la instrucción sin diagnosticar |
| 5 | **¿Lleva su inhalador encima?**<br>Do they have their inhaler with them?<br>`has_inhaler` | sí / no / no sé | no | `cause` = `asthma` | ERC 2021: ayudar con su propio broncodilatador |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `responsive` = no o no sé | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya** · pasa a `unresponsive_person` | `cpr_hands_only` |
| `can_speak_cough` = no **y** `cause` = `eating` | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya** | `choking_back_blows` |
| `cause` = `crushed_in_crowd` | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad + 1 sanitario · **enviar ya** · tipo Mando `crowd_surge_general` | `crowd_pressure` |
| `cause` = `smoke` | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad + 1 sanitario · **enviar ya** · tipo Mando `small_fire` | `fire_or_structure` |
| `cause` = `sting_or_allergy` | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 ambulancia · **enviar ya** · tipo Mando `anaphylaxis` | `allergy_wait` |
| `can_speak_cough` = no o no sé | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 ambulancia · **enviar ya** | `breathing_sit_up` |
| `can_speak_cough` = sí **y** `cause` = `eating` | sin riesgo vital · severidad ≥ 6 · 1 sanitario · **enviar ya** | `choking_cough` |
| `can_speak_cough` = sí | sin riesgo vital · severidad ≥ 7 · 1 sanitario · **enviar ya** | `breathing_sit_up` |
| *(en cualquier otro caso)* | **RIESGO VITAL** · severidad ≥ 8 · 1 sanitario + 1 ambulancia · **enviar ya** | `breathing_sit_up` |

Instrucciones disponibles: `choking_cough`, `choking_back_blows`, `breathing_sit_up`, `cpr_hands_only`, `allergy_wait`, `crowd_pressure`, `fire_or_structure`.

⚠ La taxonomía de Mando no tiene tipo «atragantamiento»: se usa `anaphylaxis` como perfil operativo más cercano (vía aérea, sanitario + ambulancia, 6-8 min).

Fuentes: [genoplivning.dk](https://genoplivning.dk/wp-content/uploads/2021/03/04_Basic-Life-Support.pdf) · [mcw.edu](https://www.mcw.edu/-/media/MCW/Departments/Emergency-Medicine/EMS/Telecommunicator-CPR-Program-Dispatch-Protocols-In-House.pdf) · [sja.org.uk](https://www.sja.org.uk/first-aid-advice/choking/) · [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf) · [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf)

**☐ validado ☐ cambiar:** ______________________________________________

### 3. Hemorragia o herida grave · `severe_bleeding`

Familia `medical` · tipo de Mando `trauma_fall` · **Enviar con:** `location_point` · **Avisa a:** medical_lead · **Externo:** ambulance (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Sangra mucho: a chorro o empapando la ropa?**<br>Is it bleeding a lot: spurting or soaking through clothes?<br>`bleeding_heavy` | sí / no / no sé | **sí** | — | hemorragia que amenaza la vida: presión directa inmediata (ERC 2021)<br>⚠ «A chorro o empapando la ropa» es mi forma de describir «severe, life-threatening bleeding»; la fuente no da umbral. |
| 3 | **¿Está despierta y te responde?**<br>Are they awake and answering you?<br>`responsive` | sí / no / no sé | **sí** | — | si no responde se pasa al protocolo de persona que no responde |
| 4 | **¿Tiene algo clavado en la herida?**<br>Is something stuck in the wound?<br>`object_embedded` | sí / no / no sé | no | — | no se extrae; se presiona a los lados (St John Ambulance) |
| 5 | **¿Cómo se ha hecho la herida?**<br>How did the wound happen?<br>`cause` | opciones<br>`fall`, `glass_or_cut`, `weapon_or_assault`, `crush`, `unknown` | no | — | si fue una agresión o un arma, seguridad va con el sanitario |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `responsive` = no o no sé | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya** · pasa a `unresponsive_person` | `bleeding` |
| `cause` = `weapon_or_assault` | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 2 seguridad + 1 ambulancia · **enviar ya** · tipo Mando `weapon_seen`<br>⚠ Pasa a tratamiento reservado (sin megafonía, policía con aprobación) aunque el protocolo no sea `sensitive`. | `bleeding` |
| `bleeding_heavy` = sí o no sé | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 ambulancia · **enviar ya** | `bleeding` |
| `object_embedded` = sí | sin riesgo vital · severidad ≥ 7 · 1 sanitario · **enviar ya** | `bleeding_object` |
| `bleeding_heavy` = no | sin riesgo vital · severidad ≥ 4 · 1 sanitario · informar a control | `bleeding` |

Instrucciones disponibles: `bleeding`, `bleeding_detail`, `bleeding_object`.

⚠ La taxonomía no tiene tipo «hemorragia»: se usa `trauma_fall` con severity_min 9 si sangra mucho; si no, `minor_injury` es razonable.

Fuentes: [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf) · [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) · [mcw.edu](https://www.mcw.edu/-/media/MCW/Departments/Emergency-Medicine/EMS/Telecommunicator-CPR-Program-Dispatch-Protocols-In-House.pdf) · [sja.org.uk](https://www.sja.org.uk/first-aid-advice/severe-bleeding/)

**☐ validado ☐ cambiar:** ______________________________________________

### 4. Reacción alérgica grave · `allergic_reaction`

Familia `medical` · tipo de Mando `anaphylaxis` · **Enviar con:** `location_point` · **Avisa a:** medical_lead · **Externo:** ambulance (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Le cuesta respirar o tragar?**<br>Are they having trouble breathing or swallowing?<br>`breathing_trouble` | sí / no / no sé | **sí** | — | signo de anafilaxia (NHS); Anexo C: sube a riesgo vital |
| 3 | **¿Tiene hinchados los labios, la cara o la lengua?**<br>Are their lips, face or tongue swollen?<br>`swelling` | sí / no / no sé | **sí** | — | signo de anafilaxia (NHS); Anexo C: «labios o cara hinchados» es riesgo vital |
| 4 | **¿Está despierta y te responde?**<br>Are they awake and answering you?<br>`responsive` | sí / no / no sé | **sí** | — | si no responde se pasa al protocolo de persona que no responde |
| 5 | **¿Lleva encima su inyector de adrenalina?**<br>Do they carry their adrenaline auto-injector?<br>`has_autoinjector` | sí / no / no sé | no | — | NHS: usarlo es el primer paso; ERC 2021: segunda dosis a los 5 min |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `responsive` = no o no sé | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya** · pasa a `unresponsive_person` | `allergy_wait` |
| `has_autoinjector` = sí **y** `breathing_trouble` = sí | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 ambulancia · **enviar ya** | `allergy_autoinjector` |
| `has_autoinjector` = sí **y** `swelling` = sí | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 ambulancia · **enviar ya** | `allergy_autoinjector` |
| `breathing_trouble` = sí o no sé | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 ambulancia · **enviar ya** | `allergy_wait` |
| `swelling` = sí | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 ambulancia · **enviar ya** | `allergy_wait` |
| `breathing_trouble` = no **y** `swelling` = no | sin riesgo vital · severidad ≥ 6 · 1 sanitario · **enviar ya** | `allergy_wait` |
| *(en cualquier otro caso)* | **RIESGO VITAL** · severidad ≥ 8 · 1 sanitario + 1 ambulancia · **enviar ya** | `allergy_wait` |

Instrucciones disponibles: `allergy_wait`, `allergy_autoinjector`.

Fuentes: [nhs.uk](https://www.nhs.uk/conditions/anaphylaxis/) · [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf) · [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf)

**☐ validado ☐ cambiar:** ______________________________________________

### 5. Convulsión · `seizure`

Familia `medical` · tipo de Mando `seizure` · **Enviar con:** `location_point` · **Avisa a:** medical_lead · **Externo:** ambulance (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Sigue con las sacudidas ahora mismo?**<br>Are they still jerking right now?<br>`still_seizing` | sí / no / no sé | **sí** | — | decide la instrucción: durante la crisis no se toca; después se valora la respiración |
| 3 | **Ahora que ha parado, ¿respira con normalidad?**<br>Now that it has stopped, are they breathing normally?<br>`breathing_after` | sí / no / no sé | **sí** | `still_seizing` = no | ERC 2021: una parada puede empezar con movimientos como de convulsión; se valora al parar |
| 4 | **¿Lleva más de cinco minutos con sacudidas?**<br>Has the jerking lasted more than five minutes?<br>`over_5_min` | sí / no / no sé | **sí** | `still_seizing` = sí | criterio de ambulancia (Epilepsy Action, SAMUR) |
| 5 | **¿Se ha golpeado la cabeza al caer?**<br>Did they hit their head when they fell?<br>`head_hit` | sí / no / no sé | no | — | lesión asociada: criterio de ambulancia (Epilepsy Action: «seriously injured during the seizure») |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `still_seizing` = no **y** `breathing_after` = no o no sé | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya** | `cpr_hands_only` |
| `over_5_min` = sí | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 ambulancia · **enviar ya** | `seizure` |
| `still_seizing` = no **y** `breathing_after` = sí | sin riesgo vital · severidad ≥ 7 · 1 sanitario · **enviar ya** | `unconscious_breathing` |
| `still_seizing` = sí o no sé | **RIESGO VITAL** · severidad ≥ 8 · 1 sanitario · **enviar ya** | `seizure` |
| *(en cualquier otro caso)* | **RIESGO VITAL** · severidad ≥ 7 · 1 sanitario · **enviar ya** | `seizure` |

Instrucciones disponibles: `seizure`, `seizure_extra`, `unconscious_breathing`, `cpr_hands_only`.

Fuentes: [epilepsy.org.uk](https://www.epilepsy.org.uk/info/first-aid/tonic-clonic-convulsive-seizures-first-aid) · [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) · [genoplivning.dk](https://genoplivning.dk/wp-content/uploads/2021/03/04_Basic-Life-Support.pdf) · [cruzroja.es](https://www.cruzroja.es/guiaprevencionNew/primeros-auxilios.html)

**☐ validado ☐ cambiar:** ______________________________________________

### 6. Golpe de calor o desmayo por calor · `heat_illness`

Familia `medical` · tipo de Mando `heat_stroke` · **Enviar con:** `location_point` · **Avisa a:** medical_lead · **Externo:** ambulance (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Está despierta y te responde?**<br>Are they awake and answering you?<br>`responsive` | sí / no / no sé | **sí** | — | si no responde se pasa al protocolo de persona que no responde |
| 3 | **¿Está confusa, dice cosas raras o no sabe dónde está?**<br>Are they confused, talking strangely or unsure where they are?<br>`confused` | sí / no / no sé | **sí** | `responsive` = sí | confusión, agitación o desorientación con calor = golpe de calor (ERC 2021); Anexo C: riesgo vital |
| 4 | **¿Tiene la piel muy caliente al tocarla?**<br>Does their skin feel very hot to the touch?<br>`skin_hot` | sí / no / no sé | **sí** | — | temperatura elevada (ERC 2021); piel caliente (NHS, SAMUR) |
| 5 | **¿Cuántas personas están así?**<br>How many people are like this?<br>`people_count` | número | no | — | varias a la vez cambia el tipo de incidente y pide logística (agua, hielo) |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `responsive` = no o no sé | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya** · pasa a `unresponsive_person` | `not_responding` |
| `confused` = sí o no sé | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 logística · **enviar ya**<br>⚠ severity_min 9 y la necesidad de logística (hielo, agua) vienen del dictamen de la experta (Anexo B), no de una guía. | `heat_cool_now` |
| `skin_hot` = sí | **RIESGO VITAL** · severidad ≥ 8 · 1 sanitario + 1 logística · **enviar ya** | `heat_cool_now` |
| `people_count` ≥ 2 | sin riesgo vital · severidad ≥ 8 · 2 sanitario + 1 logística · **enviar ya** · tipo Mando `multiple_heat_strokes` | `heat` |
| `responsive` = sí **y** `confused` = no **y** `skin_hot` = no | sin riesgo vital · severidad ≥ 5 · 1 sanitario · **enviar ya** | `faint_lie_down` |
| *(en cualquier otro caso)* | sin riesgo vital · severidad ≥ 7 · 1 sanitario · **enviar ya** | `heat` |

Instrucciones disponibles: `heat`, `heat_cool_now`, `faint_lie_down`, `not_responding`.

Fuentes: [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf) · [nhs.uk](https://www.nhs.uk/conditions/heat-exhaustion-heatstroke/) · [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf)

**☐ validado ☐ cambiar:** ______________________________________________

### 7. Intoxicación por alcohol o drogas · `intoxication`

Familia `medical` · tipo de Mando `intoxication_overdose` · **Enviar con:** `location_point` · **Avisa a:** medical_lead · **Externo:** ambulance (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Se despierta si le hablas fuerte y le tocas el hombro?**<br>Do they wake if you speak loudly and tap their shoulder?<br>`responsive` | sí / no / no sé | **sí** | — | Anexo C: «ha tomado algo y no despierta» es riesgo vital |
| 3 | **¿Respira con normalidad? Mírale el pecho diez segundos.**<br>Are they breathing normally? Watch their chest for ten seconds.<br>`breathing_normal` | sí / no / no sé | **sí** | `responsive` = no o no sé | reconocer parada: segunda pregunta; no responde + no respira normal = RCP (ERC 2021) |
| 4 | **¿Crees que le han echado algo en la bebida?**<br>Do you think someone put something in their drink?<br>`spiked_suspected` | sí / no / no sé | no | — | si sí, pasa al protocolo reservado de sumisión química |
| 5 | **¿Sabes qué ha tomado?**<br>Do you know what they took?<br>`substance` | texto libre | no | — | dato para el equipo sanitario (SAMUR); nunca se juzga ni se repite |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `responsive` = no o no sé **y** `breathing_normal` = no o no sé | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya** · pasa a `unresponsive_person` | `cpr_hands_only` |
| `responsive` = no o no sé **y** `breathing_normal` = sí | **RIESGO VITAL** · severidad ≥ 8 · 1 sanitario · **enviar ya** | `unconscious_breathing` |
| `responsive` = no o no sé | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 ambulancia · **enviar ya** | `not_responding` |
| `spiked_suspected` = sí | sin riesgo vital · severidad ≥ 8 · 1 sanitario + 1 seguridad · **enviar ya** · tipo Mando `chemical_submission` · pasa a `chemical_submission` | `intox_stay` |
| `responsive` = sí | sin riesgo vital · severidad ≥ 6 · 1 sanitario · **enviar ya** | `intox_stay` |

Instrucciones disponibles: `intox_stay`, `unconscious_breathing`, `recovery_position_steps`, `cpr_hands_only`, `not_responding`.

Fuentes: [nhs.uk](https://www.nhs.uk/conditions/alcohol-poisoning/) · [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) · [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf) · [www2.cruzroja.es](https://www2.cruzroja.es/web/ahora/-/que-es-la-posicion-lateral-de-seguridad-y-cuando-se-utiliza)

**☐ validado ☐ cambiar:** ______________________________________________

### 8. Caída o traumatismo · `fall_trauma`

Familia `medical` · tipo de Mando `trauma_fall` · **Enviar con:** `location_point` · **Avisa a:** medical_lead · **Externo:** ambulance (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Está despierta y te responde?**<br>Are they awake and answering you?<br>`responsive` | sí / no / no sé | **sí** | — | si no responde se pasa al protocolo de persona que no responde |
| 3 | **¿Sangra mucho?**<br>Is there a lot of bleeding?<br>`bleeding_heavy` | sí / no / no sé | **sí** | — | hemorragia grave: presión directa inmediata (ERC 2021) |
| 4 | **¿Se ha caído desde una altura o le ha golpeado algo?**<br>Did they fall from a height or did something hit them?<br>`mechanism` | opciones<br>`ground_level`, `from_height`, `hit_by_object`, `unknown` | no | — | SAMUR: sospechar lesión de columna en caídas de altura e impactos violentos |
| 5 | **¿Puede mover brazos y piernas?**<br>Can they move their arms and legs?<br>`can_move_limbs` | sí / no / no sé | no | — | SAMUR: presumir gravedad si ha perdido movilidad o sensibilidad |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `responsive` = no o no sé | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya** · pasa a `unresponsive_person` | `not_responding` |
| `bleeding_heavy` = sí | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 ambulancia · **enviar ya** | `bleeding` |
| `can_move_limbs` = no | **RIESGO VITAL** · severidad ≥ 8 · 1 sanitario + 1 ambulancia · **enviar ya** | `trauma_do_not_move` |
| `mechanism` = `from_height` o `hit_by_object` | **RIESGO VITAL** · severidad ≥ 8 · 1 sanitario + 1 ambulancia · **enviar ya** | `trauma_do_not_move` |
| `responsive` = sí | sin riesgo vital · severidad ≥ 5 · 1 sanitario · **enviar ya** | `trauma_do_not_move` |
| *(en cualquier otro caso)* | sin riesgo vital · severidad ≥ 5 · 1 sanitario · **enviar ya** | `trauma_do_not_move` |

Instrucciones disponibles: `trauma_do_not_move`, `bleeding`, `not_responding`.

Fuentes: [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf) · [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) · [www2.cruzroja.es](https://www2.cruzroja.es/web/ahora/-/que-es-la-posicion-lateral-de-seguridad-y-cuando-se-utiliza)

**☐ validado ☐ cambiar:** ______________________________________________

### 9. Aglomeración, empujones o riesgo de aplastamiento · `crowd_crush`

Familia `crowd` · tipo de Mando `crowd_surge_general` · **Enviar con:** `location_point` · **Avisa a:** security_lead, medical_lead · **Externo:** 112 (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Estás tú dentro de la zona apretada?**<br>Are you inside the packed area yourself?<br>`caller_trapped` | sí / no / no sé | **sí** | — | si quien avisa está dentro, primero va la instrucción de autoprotección |
| 3 | **¿Hay gente en el suelo o que no puede respirar?**<br>Are people on the ground or unable to breathe?<br>`people_down` | sí / no / no sé | **sí** | — | caída en cadena o asfixia por compresión: riesgo vital (Still, en Time) |
| 4 | **¿Puedes moverte o salir por tu cuenta?**<br>Can you move or get out on your own?<br>`can_move` | sí / no / no sé | **sí** | — | sin movimiento propio la densidad ronda el límite (Still: 5 p/m² es el tope; Moussaïd: contacto en ambos hombros ≈ 6) |
| 5 | **¿Va a más o se está aflojando?**<br>Is it getting worse or easing?<br>`trend` | opciones<br>`worse`, `same`, `easing`, `unknown` | no | — | la tendencia importa más que la foto (dictamen de la experta) |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `people_down` = sí | **RIESGO VITAL** · severidad ≥ 10 · 2 sanitario + 2 seguridad + 1 ambulancia · **enviar ya** · tipo Mando `crowd_collapse` | `crowd_pressure` |
| `caller_trapped` = sí **y** `can_move` = no | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad + 1 sanitario · **enviar ya** | `crowd_pressure` |
| `trend` = `worse` | **RIESGO VITAL** · severidad ≥ 8 · 2 seguridad + 1 sanitario · **enviar ya** | `crowd_pressure` |
| `caller_trapped` = sí | sin riesgo vital · severidad ≥ 7 · 2 seguridad + 1 sanitario · **enviar ya** | `crowd_pressure` |
| `caller_trapped` = no | sin riesgo vital · severidad ≥ 7 · 2 seguridad + 1 sanitario · **enviar ya** | `crowd_leave_early` |
| *(en cualquier otro caso)* | sin riesgo vital · severidad ≥ 7 · 2 seguridad + 1 sanitario · **enviar ya** | `crowd_pressure` |

Instrucciones disponibles: `crowd_pressure`, `crowd_if_fallen`, `crowd_leave_early`.

⚠ Si la zona es `front_pit`, Mando debe leerlo como `front_pit_critical_density`; si es una puerta, como `gate_crush_risk`. El agente nunca dice «evacuad» ni «parad»: eso es de una persona con cargo.

Fuentes: [cdc.gov](https://www.cdc.gov/yellow-book/hcp/travel-for-work-other/mass-gatherings.html) · [kqed.org](https://www.kqed.org/news/11930646/8-tips-to-follow-if-youre-trapped-in-a-crushing-crowd) · [time.com](https://time.com/6226680/how-to-survive-crowd-crush-south-korea/) · [gkstill.com](https://www.gkstill.com/Support/crowd-density/CrowdDensity-1.html) · [hse.gov.uk](https://www.hse.gov.uk/event-safety/crowd-management-monitoring.htm) · [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/mes_consells_dautoproteccio/grans_concentracions_persones/index.html)

**☐ validado ☐ cambiar:** ______________________________________________

### 10. Puerta o acceso saturado · `gate_saturation`

Familia `crowd` · tipo de Mando `gate_saturation` · **Enviar con:** `location_point`, `pressure` · **Avisa a:** gates, security_lead · **Externo:** ninguno

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿En qué puerta o acceso estás? Dime algo que veas cerca.**<br>Which gate or entrance are you at? Tell me something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Hay empujones o gente apretada contra las vallas?**<br>Is there pushing, or people pressed against the barriers?<br>`pressure` | sí / no / no sé | **sí** | — | separa cola larga de riesgo de aplastamiento en puerta |
| 3 | **¿Hay alguien en el suelo o que se encuentre mal?**<br>Is anyone on the ground or feeling unwell?<br>`people_down` | sí / no / no sé | **sí** | — | añade sanitario |
| 4 | **¿La cola avanza?**<br>Is the queue moving?<br>`moving` | sí / no / no sé | no | — | cola parada + llegada continua = la presión crece |
| 5 | **¿La gente está entrando o saliendo?**<br>Are people coming in or going out?<br>`direction` | opciones<br>`entering`, `leaving`, `both`, `unknown` | no | — | a la salida el riesgo es el contraflujo |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `people_down` = sí | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad + 1 sanitario · **enviar ya** · tipo Mando `gate_crush_risk` | `crowd_pressure` |
| `pressure` = sí o no sé | **RIESGO VITAL** · severidad ≥ 8 · 2 seguridad + 1 sanitario · **enviar ya** · tipo Mando `gate_crush_risk` | `crowd_pressure` |
| `direction` = `both` | sin riesgo vital · severidad ≥ 7 · 2 seguridad + 1 voluntario · **enviar ya** · tipo Mando `counterflow_exit` | `queue_wait` |
| `pressure` = no | sin riesgo vital · severidad ≥ 5 · 1 seguridad + 1 voluntario · **enviar ya** | `queue_wait` |

Instrucciones disponibles: `crowd_pressure`, `queue_wait`.

⚠ Regla dura de Mando: nunca se cierra una puerta con presión detrás. El agente no sugiere cerrar ni dice por dónde entrar; eso lo decide control.

Fuentes: [hse.gov.uk](https://www.hse.gov.uk/event-safety/crowd-management-controls.htm) · [hse.gov.uk](https://www.hse.gov.uk/event-safety/crowd-management-monitoring.htm) · [gkstill.com](https://www.gkstill.com/Support/crowd-density/CrowdDensity-1.html) · [cdc.gov](https://www.cdc.gov/yellow-book/hcp/travel-for-work-other/mass-gatherings.html)

**☐ validado ☐ cambiar:** ______________________________________________

### 11. Humo o fuego · `smoke_fire`

Familia `infra` · tipo de Mando `small_fire` · **Enviar con:** `location_point` · **Avisa a:** security_lead, production · **Externo:** fire (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Estás tú lejos del humo o del fuego?**<br>Are you yourself away from the smoke or fire?<br>`caller_safe` | sí / no / no sé | **sí** | — | si no, primero la instrucción de alejarse |
| 3 | **¿Ves llamas, solo humo o solo huele?**<br>Do you see flames, only smoke, or just a smell?<br>`what_seen` | opciones<br>`flames`, `smoke_only`, `smell_burning`, `smell_gas`, `unknown` | **sí** | — | dimensiona el envío |
| 4 | **¿Hay alguien atrapado o herido?**<br>Is anyone trapped or hurt?<br>`people_hurt` | sí / no / no sé | **sí** | — | añade sanitario y sube a riesgo vital |
| 5 | **¿Es en una cocina o cerca de bombonas?**<br>Is it in a kitchen or near gas bottles?<br>`near_kitchen_gas` | sí / no / no sé | no | — | HSE: el GLP es el riesgo de proceso típico en eventos |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `people_hurt` = sí | **RIESGO VITAL** · severidad ≥ 10 · 2 seguridad + 1 sanitario + 1 técnico · **enviar ya** | `fire_or_structure` |
| `what_seen` = `smell_gas` | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad + 1 técnico · **enviar ya** · tipo Mando `gas_leak_food` | `smoke_low` |
| `what_seen` = `flames` | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad + 1 técnico · **enviar ya** | `fire_or_structure` |
| `near_kitchen_gas` = sí | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad + 1 técnico · **enviar ya** | `fire_or_structure` |
| `caller_safe` = no | **RIESGO VITAL** · severidad ≥ 8 · 2 seguridad + 1 técnico · **enviar ya** | `fire_or_structure` |
| `what_seen` = `smoke_only` o `smell_burning` o no sé | sin riesgo vital · severidad ≥ 8 · 2 seguridad + 1 técnico · **enviar ya** | `fire_or_structure` |
| *(en cualquier otro caso)* | sin riesgo vital · severidad ≥ 8 · 2 seguridad + 1 técnico · **enviar ya** | `fire_or_structure` |

Instrucciones disponibles: `fire_or_structure`, `smoke_low`.

⚠ El agente nunca pide a quien avisa que alerte a los de alrededor (Anexo C: siembra la carrera) ni que apague el fuego.

Fuentes: [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) · [112.jcyl.es](https://112.jcyl.es/web/es/consejos-recomendaciones/lugares-publicos.html) · [112.cantabria.es](https://112.cantabria.es/consejos-de-autoproteccion/grandes-aglomeraciones) · [hse.gov.uk](https://www.hse.gov.uk/event-safety/fire-safety.htm) · [hse.gov.uk](https://www.hse.gov.uk/event-safety/incidents-and-emergencies.htm)

**☐ validado ☐ cambiar:** ______________________________________________

### 12. Viento o estructura en riesgo · `wind_structure`

Familia `weather` · tipo de Mando `strong_wind_gusts` · **Enviar con:** `location_point` · **Avisa a:** production, security_lead · **Externo:** 112 (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Hay alguien herido o atrapado?**<br>Is anyone hurt or trapped?<br>`people_hurt` | sí / no / no sé | **sí** | — | riesgo vital y sanitario |
| 3 | **¿Se mueve, se ha caído una parte o se ha caído entera?**<br>Is it moving, has part fallen, or has it all come down?<br>`state` | opciones<br>`moving`, `partly_fallen`, `fallen`, `unknown` | **sí** | — | separa preaviso de daño |
| 4 | **¿Hay gente debajo o pegada a la estructura?**<br>Are people under or right next to the structure?<br>`people_under` | sí / no / no sé | **sí** | — | despejar el entorno es la primera medida del escalón de viento (dictamen de la experta) |
| 5 | **¿Qué es: escenario, torre, pantalla, carpa, valla u otra cosa?**<br>What is it: stage, tower, screen, tent, fence or something else?<br>`what` | opciones<br>`stage`, `tower`, `screen`, `tent_or_canopy`, `fence_or_barrier`, `tree`, `other` | no | — | a quién se manda (técnico de estructuras) |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `people_hurt` = sí | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 técnico + 2 seguridad · **enviar ya** · tipo Mando `structure_damage` | `wind_away` |
| `state` = `partly_fallen` o `fallen` | **RIESGO VITAL** · severidad ≥ 9 · 1 técnico + 1 seguridad · **enviar ya** · tipo Mando `structure_damage` | `wind_away` |
| `state` = `moving` o no sé **y** `people_under` = sí o no sé | **RIESGO VITAL** · severidad ≥ 8 · 1 técnico + 1 seguridad · **enviar ya** | `wind_away` |
| `state` = `moving` o no sé | sin riesgo vital · severidad ≥ 6 · 1 técnico + 1 seguridad · **enviar ya** | `weather` |

Instrucciones disponibles: `weather`, `wind_away`.

⚠ Los escalones de viento (≈40 preaviso, ≈50 despejar, ≈60 parar) son criterio de la experta sin fuente abierta; no se han llevado a datos. Parar el espectáculo es decisión humana.

Fuentes: [112.jcyl.es](https://112.jcyl.es/web/es/consejos-recomendaciones/vientos.html) · [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/riscos_naturals/ventades/index.html) · [hse.gov.uk](https://www.hse.gov.uk/event-safety/incidents-and-emergencies.htm)

**☐ validado ☐ cambiar:** ______________________________________________

### 13. Tormenta o rayos · `storm_lightning`

Familia `weather` · tipo de Mando `lightning_nearby` · **Enviar con:** `location_point`, `anyone_struck` · **Avisa a:** coordinator, production · **Externo:** ninguno

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Le ha caído un rayo a alguien o hay heridos?**<br>Has anyone been struck by lightning or hurt?<br>`anyone_struck` | sí / no / no sé | **sí** | — | riesgo vital |
| 3 | **¿Has visto rayos o has oído truenos?**<br>Have you seen lightning or heard thunder?<br>`lightning_seen` | sí / no / no sé | no | — | dato para control; NWS: con tormenta cerca ningún sitio al aire libre es seguro |
| 4 | **¿Dónde estás: al aire libre, bajo una carpa, un árbol, o dentro?**<br>Where are you: in the open, under a tent, a tree, or indoors?<br>`shelter` | opciones<br>`open`, `tent_or_canopy`, `under_tree`, `vehicle`, `building`, `unknown` | no | — | carpas y árboles no son refugio (NWS, Protección Civil de Cataluña) |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `anyone_struck` = sí | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia · **enviar ya** · pasa a `unresponsive_person` | `not_responding` |
| `shelter` = `tent_or_canopy` o `under_tree` o `open` | sin riesgo vital · severidad ≥ 8 · 2 seguridad · informar a control | `weather_lightning` |
| `lightning_seen` = sí | sin riesgo vital · severidad ≥ 8 · 2 seguridad · informar a control | `weather_lightning` |
| *(en cualquier otro caso)* | sin riesgo vital · severidad ≥ 6 · 1 seguridad · informar a control | `weather` |

Instrucciones disponibles: `weather`, `weather_lightning`, `not_responding`.

⚠ Un aviso de rayos del público es INFORMACIÓN para control, no un despacho: suspender o evacuar es decisión humana con el dato meteorológico. La plantilla del NWS para recintos propone, como valores editables, preaviso a 15 y 12 millas, evacuar a 8 millas (≈13 km) y reanudar a los 30 min del último trueno.

Fuentes: [weather.gov](https://www.weather.gov/safety/lightning-outdoors) · [weather.gov](https://www.weather.gov/media/safety/lightning/Lightning_Safety_Toolkit_Outdoor_Venues.pdf) · [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/riscos_naturals/tempestes_electriques/index.html) · [112.castillalamancha.es](https://112.castillalamancha.es/proteccion-civil/consejos/tormentas-y-rayos)

**☐ validado ☐ cambiar:** ______________________________________________

### 14. Objeto sospechoso o amenaza · `suspicious_object_threat` · **[RESERVADO]**

Familia `external` · tipo de Mando `suspicious_object` · **Enviar con:** `kind`, `location_point` · **Avisa a:** security_lead · **Externo:** police (**siempre con aprobación humana**)

> Tono neutro, solo las preguntas críticas, no se repite lo contado, sin megafonía, en pantalla solo «Incidente reservado», paso inmediato a una persona.

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Es un objeto abandonado, una amenaza o alguien con un arma?**<br>Is it an unattended item, a threat, or someone with a weapon?<br>`kind` | opciones<br>`object`, `threat`, `weapon` | **sí** | — | cada caso va a un tipo distinto de Mando; no se valora la credibilidad |
| 2 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 3 | **¿Estás ya lejos de ahí?**<br>Are you already well away from it?<br>`caller_away` | sí / no / no sé | **sí** | — | gov.uk: despejar (100 m para un bulto pequeño) y quedar fuera de la línea de visión; la distancia la fija seguridad, no el agente |
| 4 | **¿Alguien lo ha tocado o movido?**<br>Has anyone touched or moved it?<br>`touched` | sí / no / no sé | no | `kind` = `object` | gov.uk: «do not touch it further» |
| 5 | **¿Cuáles fueron las palabras exactas de la amenaza?**<br>What were the exact words of the threat?<br>`threat_words` | texto libre | no | `kind` = `threat` | Cruz Roja y gov.uk: anotar el mensaje lo más textual posible; NO se repite a quien avisa |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `kind` = `weapon` | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad · **enviar ya** · tipo Mando `weapon_seen` | `aggression` |
| `kind` = `object` **y** `caller_away` = no o no sé | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad · **enviar ya** | `suspicious_move_first` |
| `kind` = `object` | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad · **enviar ya** | `suspicious_object` |
| `kind` = `threat` | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad · **enviar ya** · tipo Mando `bomb_threat_call` | `threat_noted` |

Instrucciones disponibles: `suspicious_object`, `suspicious_move_first`, `threat_noted`, `aggression`.

⚠ No se preguntan los detalles HOT (oculto, claramente sospechoso, típico del lugar): obligaría a acercarse. El HOT y las 4 C (confirmar, despejar, comunicar, controlar) los hace seguridad en el sitio. Sin megafonía; evacuar lo deciden las Fuerzas y Cuerpos de Seguridad.

Fuentes: [gov.uk](https://www.gov.uk/government/publications/crowded-places-guidance/unattended-and-suspicious-items) · [gov.uk](https://www.gov.uk/government/publications/crowded-places-guidance/bomb-threats) · [cruzroja.es](https://www.cruzroja.es/guiaprevencionNew/aviso-bomba.html)

**☐ validado ☐ cambiar:** ______________________________________________

### 15. Agresión o acoso sexual · `sexual_violence` · **[RESERVADO]**

Familia `aggression` · tipo de Mando `sexual_assault_report` · **Enviar con:** `location_point` · **Avisa a:** violet_point · **Externo:** police (**siempre con aprobación humana**, y con consentimiento de la víctima)

> Tono neutro, solo las preguntas críticas, no se repite lo contado, sin megafonía, en pantalla solo «Incidente reservado», paso inmediato a una persona.

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Estás en un sitio seguro ahora?**<br>Are you somewhere safe right now?<br>`safe_now` | sí / no / no sé | **sí** | — | NS-25: es una de las dos únicas preguntas permitidas; Igualdad: preservar la seguridad |
| 2 | **¿Dónde estás?**<br>Where are you?<br>`location_point` | zona + referencia | **sí** | — | NS-25: segunda y última pregunta; la zona NO se muestra en pantalla compartida |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `safe_now` = no o no sé | **RIESGO VITAL** · severidad ≥ 9 · 1 seguridad · **enviar ya** | `violet_unsafe` |
| `safe_now` = sí | sin riesgo vital · severidad ≥ 9 · 1 seguridad · **enviar ya** | `violet` |

Instrucciones disponibles: `violet`, `violet_unsafe`.

⚠ No se pide relato, descripción ni confirmación por repetición. Seguridad va a localizar y vigilar con discreción, no «al incidente». Policía solo con consentimiento de la víctima adulta, salvo menor, agresor presente o riesgo (criterio de la experta; cotejar con LO 10/2022). Si es acoso de un grupo sin agresión, Mando puede leerlo como `harassment_group`. La instrucción `aggression` está PROHIBIDA aquí.

Fuentes: [violenciagenero.igualdad.gob.es](https://violenciagenero.igualdad.gob.es/wp-content/uploads/RECOMENDACIONES-PARA-LA-IMPLANTACION-DE-PUNTOS-VIOLETA_-maquetado.pdf) · consejo/seguridad-eventos.md (Anexo C, lista validada por la experta del consejo)

**☐ validado ☐ cambiar:** ______________________________________________

### 16. Sospecha de sumisión química · `chemical_submission` · **[RESERVADO]**

Familia `aggression` · tipo de Mando `chemical_submission` · **Enviar con:** `location_point` · **Avisa a:** violet_point, medical_lead · **Externo:** police (**siempre con aprobación humana**, y con consentimiento de la víctima)

> Tono neutro, solo las preguntas críticas, no se repite lo contado, sin megafonía, en pantalla solo «Incidente reservado», paso inmediato a una persona.

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Te ha pasado a ti o a otra persona?**<br>Did it happen to you or to someone else?<br>`who` | opciones<br>`me`, `other` | **sí** | — | cambia la instrucción |
| 2 | **¿Dónde estás?**<br>Where are you?<br>`location_point` | zona + referencia | **sí** | — | la zona NO se muestra en pantalla compartida |
| 3 | **¿Está despierta y te responde?**<br>Are they awake and answering you?<br>`responsive` | sí / no / no sé | **sí** | `who` = `other` | Igualdad: somnolencia o pérdida de consciencia exige actuar con la mayor diligencia y 112 |
| 4 | **¿Hay alguien de confianza contigo?**<br>Is someone you trust with you?<br>`accompanied` | sí / no / no sé | no | — | SAS 2022: «deben estar siempre acompañadas» |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `who` = `other` **y** `responsive` = no o no sé | **RIESGO VITAL** · severidad ≥ 10 · 1 sanitario + 1 ambulancia + 1 seguridad · **enviar ya** · pasa a `unresponsive_person` | `unconscious_breathing` |
| `who` = `other` | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 seguridad · **enviar ya** | `spiking_other` |
| `who` = `me` | **RIESGO VITAL** · severidad ≥ 9 · 1 sanitario + 1 seguridad · **enviar ya** | `spiking_self` |

Instrucciones disponibles: `spiking_self`, `spiking_other`, `unconscious_breathing`.

⚠ Aquí el sanitario SÍ es urgente: las sustancias dejan de detectarse en sangre pasadas unas 72 h (SAS 2022) y el cuadro puede empeorar. El agente no habla de pruebas ni de denuncia: eso lo explica una persona.

Fuentes: [sspa.juntadeandalucia.es](https://www.sspa.juntadeandalucia.es/servicioandaluzdesalud/sites/default/files/sincfiles/wsas-media-mediafile_sasdocumento/2022/protocolo_sumision_quimica_15082022.pdf) · [violenciagenero.igualdad.gob.es](https://violenciagenero.igualdad.gob.es/wp-content/uploads/RECOMENDACIONES-PARA-LA-IMPLANTACION-DE-PUNTOS-VIOLETA_-maquetado.pdf) · consejo/seguridad-eventos.md (Anexo C, lista validada por la experta del consejo)

**☐ validado ☐ cambiar:** ______________________________________________

### 17. Pelea o agresión · `fight_assault`

Familia `aggression` · tipo de Mando `fight` · **Enviar con:** `location_point` · **Avisa a:** security_lead · **Externo:** police (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Has visto algún arma u objeto peligroso?**<br>Have you seen any weapon or dangerous object?<br>`weapon` | sí / no / no sé | **sí** | — | con arma pasa a tratamiento reservado: sin megafonía, policía con aprobación |
| 3 | **¿Hay alguien herido?**<br>Is anyone hurt?<br>`injured` | sí / no / no sé | **sí** | — | añade sanitario |
| 4 | **¿Estás tú a salvo, lejos de la pelea?**<br>Are you safe, away from the fight?<br>`caller_safe` | sí / no / no sé | **sí** | — | si no, primero la instrucción de alejarse |
| 5 | **¿Cuántas personas están peleando?**<br>How many people are fighting?<br>`people_count` | número | no | — | dimensiona el envío de seguridad |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `weapon` = sí | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad · **enviar ya** · tipo Mando `weapon_seen` | `aggression` |
| `injured` = sí | sin riesgo vital · severidad ≥ 7 · 2 seguridad + 1 sanitario · **enviar ya** | `aggression` |
| `people_count` ≥ 5 | sin riesgo vital · severidad ≥ 7 · 3 seguridad · **enviar ya**<br>⚠ El umbral de 5 personas y las 3 parejas de seguridad son criterio propio. | `aggression` |
| `weapon` = no o no sé | sin riesgo vital · severidad ≥ 5 · 2 seguridad · **enviar ya** | `aggression` |

Instrucciones disponibles: `aggression`.

⚠ Nunca se piden descripciones de sospechosos por este canal ni se difunden (dictamen, Anexo D). Si la víctima es personal del evento, Mando lo lee como `staff_assaulted`.

Fuentes: [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) · consejo/seguridad-eventos.md (Anexo C, lista validada por la experta del consejo)

**☐ validado ☐ cambiar:** ______________________________________________

### 18. Menor perdido o encontrado · `lost_child` · **[RESERVADO]**

Familia `info` · tipo de Mando `lost_child` · **Enviar con:** `role`, `location_point` · **Avisa a:** security_lead, gates · **Externo:** police (**siempre con aprobación humana**)

> Tono neutro, solo las preguntas críticas, no se repite lo contado, sin megafonía, en pantalla solo «Incidente reservado», paso inmediato a una persona.

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Has encontrado a un menor o has perdido al tuyo?**<br>Have you found a child, or lost your own?<br>`role` | opciones<br>`found_child`, `lost_my_child` | **sí** | — | Anexo C: son dos instrucciones distintas |
| 2 | **¿Dónde estás ahora? Dime la zona y algo que veas cerca.**<br>Where are you now? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 3 | **¿Qué edad tiene?**<br>How old are they?<br>`age` | número | **sí** | `role` = `lost_my_child` | descripción para los equipos y las puertas; con los muy pequeños se escala antes |
| 4 | **¿Cómo va vestido?**<br>What are they wearing?<br>`clothing` | texto libre | **sí** | `role` = `lost_my_child` | descripción; va por canal reservado, nunca por megafonía |
| 5 | **¿Dónde lo viste por última vez?**<br>Where did you last see them?<br>`last_seen` | zona + referencia | no | `role` = `lost_my_child` | punto de partida de la búsqueda |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `role` = `lost_my_child` **y** `age` ≤ 5 | sin riesgo vital · severidad ≥ 8 · 1 seguridad + 1 voluntario · **enviar ya**<br>⚠ El corte de 5 años es criterio propio; la fuente de sector solo dice «immediately if the child is very young». | `lost_child_parent` |
| `role` = `lost_my_child` | sin riesgo vital · severidad ≥ 7 · 1 seguridad + 1 voluntario · **enviar ya** | `lost_child_parent` |
| `role` = `found_child` | sin riesgo vital · severidad ≥ 7 · 1 seguridad + 1 voluntario · **enviar ya** | `lost_child` |

Instrucciones disponibles: `lost_child`, `lost_child_parent`.

⚠ NUNCA megafonía con el nombre o la descripción del menor. NS-26: el agente no dice dónde está un menor ni confirma que hay un aviso a quien dice ser familiar. No se pide el nombre del menor por este canal (lo recoge el personal en persona). Dos personas acreditadas con el menor, entrega solo a tutor verificado con documento. Escalar a policía si no aparece en 15-20 min (experta, sin fuente abierta) o 30 min (Ticket Fairy).

Fuentes: [ticketfairy.com](https://www.ticketfairy.com/blog/lost-child-and-vulnerable-persons-protocols-at-festivals) · [nipperbout.com](https://www.nipperbout.com/tips-and-tales/tips-planning-lost-child-services-at-events) · [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/mes_consells_dautoproteccio/grans_concentracions_persones/index.html) · [112.cantabria.es](https://112.cantabria.es/consejos-de-autoproteccion/grandes-aglomeraciones) · consejo/seguridad-eventos.md (Anexo C, lista validada por la experta del consejo)

**☐ validado ☐ cambiar:** ______________________________________________

### 19. Persona vulnerable desorientada · `vulnerable_person`

Familia `info` · tipo de Mando `lost_vulnerable_adult` · **Enviar con:** `role`, `location_point` · **Avisa a:** security_lead, gates · **Externo:** police (**siempre con aprobación humana**)

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Estás con esa persona o la estás buscando?**<br>Are you with that person, or looking for them?<br>`role` | opciones<br>`with_person`, `looking_for_person` | **sí** | — | cambia la instrucción |
| 2 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 3 | **¿Está herida o se encuentra mal?**<br>Are they hurt or feeling unwell?<br>`unwell` | sí / no / no sé | **sí** | `role` = `with_person` | la confusión puede ser calor, azúcar bajo o un golpe: si hay duda va un sanitario (ERC 2021: la hipoglucemia parece embriaguez) |
| 4 | **¿Cómo es y cómo va vestida?**<br>What do they look like and what are they wearing?<br>`description` | texto libre | no | `role` = `looking_for_person` | para equipos y puertas, por canal reservado |
| 5 | **¿Dónde la viste por última vez?**<br>Where did you last see them?<br>`last_seen` | zona + referencia | no | `role` = `looking_for_person` | punto de partida de la búsqueda |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `unwell` = sí o no sé | sin riesgo vital · severidad ≥ 7 · 1 sanitario + 1 voluntario · **enviar ya** | `vulnerable_stay` |
| `role` = `with_person` | sin riesgo vital · severidad ≥ 6 · 1 voluntario + 1 seguridad · **enviar ya** | `vulnerable_stay` |
| `role` = `looking_for_person` | sin riesgo vital · severidad ≥ 6 · 1 voluntario + 1 seguridad · **enviar ya** | `vulnerable_searching` |

Instrucciones disponibles: `vulnerable_stay`, `vulnerable_searching`.

⚠ No es `sensitive` en la taxonomía, pero el nombre y la descripción tampoco se megafonean.

Fuentes: [ticketfairy.com](https://www.ticketfairy.com/blog/lost-child-and-vulnerable-persons-protocols-at-festivals) · [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf) · [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/mes_consells_dautoproteccio/grans_concentracions_persones/index.html)

**☐ validado ☐ cambiar:** ______________________________________________

### 20. Gente corriendo o rumor de peligro · `rumor_running`

Familia `info` · tipo de Mando `rumor_panic` · **Enviar con:** `location_point`, `people_running` · **Avisa a:** security_lead, coordinator · **Externo:** ninguno

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Hay gente corriendo ahora mismo?**<br>Are people running right now?<br>`people_running` | sí / no / no sé | **sí** | — | la carrera es el peligro, sea cierto o no el motivo |
| 3 | **¿Hay alguien en el suelo o herido?**<br>Is anyone on the ground or hurt?<br>`people_down` | sí / no / no sé | **sí** | — | añade sanitario |
| 4 | **¿Lo has visto tú o te lo han contado?**<br>Did you see it yourself, or were you told?<br>`seen_directly` | opciones<br>`seen`, `told`, `unknown` | no | — | distingue testigo de rumor sin valorar a la persona |
| 5 | **¿Qué dice la gente que pasa?**<br>What are people saying is happening?<br>`what_heard` | texto libre | no | — | se anota literal para control; no se repite ni se confirma |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `people_down` = sí | **RIESGO VITAL** · severidad ≥ 9 · 2 seguridad + 1 sanitario · **enviar ya** · tipo Mando `crowd_surge_general` | `no_run` |
| `people_running` = sí o no sé | **RIESGO VITAL** · severidad ≥ 8 · 2 seguridad · **enviar ya** | `no_run` |
| `people_running` = no | sin riesgo vital · severidad ≥ 6 · 2 seguridad · informar a control | `no_run` |

Instrucciones disponibles: `no_run`.

⚠ El agente nunca confirma ni desmiente el rumor. El mensaje al público por megafonía es pregrabado y lo aprueba una persona (HSE: «pre-agreed wording for public announcements»).

Fuentes: [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/mes_consells_dautoproteccio/grans_concentracions_persones/index.html) · [hse.gov.uk](https://www.hse.gov.uk/event-safety/incidents-and-emergencies.htm) · [112.jcyl.es](https://112.jcyl.es/web/es/consejos-recomendaciones/lugares-publicos.html)

**☐ validado ☐ cambiar:** ______________________________________________

### 21. Apagón o fallo eléctrico · `power_outage`

Familia `infra` · tipo de Mando `power_outage_food` · **Enviar con:** `location_point`, `what_off` · **Avisa a:** production · **Externo:** ninguno

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Ves chispas, cables sueltos u olor a quemado?**<br>Do you see sparks, loose cables, or smell burning?<br>`hazard` | sí / no / no sé | **sí** | — | riesgo eléctrico o de incendio: sube la prioridad |
| 3 | **¿Qué se ha apagado: luces, escenario, barras o pagos?**<br>What has gone off: lights, stage, bars or payments?<br>`what_off` | opciones<br>`lights`, `stage_sound`, `food_stalls`, `payments`, `everything`, `unknown` | **sí** | — | cada uno es un tipo distinto en Mando |
| 4 | **¿Está la zona a oscuras?**<br>Is the area in the dark?<br>`dark` | sí / no / no sé | no | — | a oscuras hay caídas y contraflujo (taxonomía: lighting_failure) |
| 5 | **¿Cómo está la gente: tranquila, nerviosa o empujando?**<br>How are people: calm, restless or pushing?<br>`crowd_mood` | opciones<br>`calm`, `restless`, `pushing`, `unknown` | no | — | un corte en el escenario puede acabar en avalancha |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `hazard` = sí | **RIESGO VITAL** · severidad ≥ 9 · 1 técnico + 2 seguridad · **enviar ya** · tipo Mando `small_fire` | `power_keep_away` |
| `crowd_mood` = `pushing` | **RIESGO VITAL** · severidad ≥ 8 · 2 seguridad + 1 sanitario · **enviar ya** · tipo Mando `crowd_surge_general` | `crowd_pressure` |
| `what_off` = `stage_sound` | sin riesgo vital · severidad ≥ 7 · 2 técnico · **enviar ya** · tipo Mando `stage_power_failure` | `dark_stay` |
| `dark` = sí | sin riesgo vital · severidad ≥ 7 · 1 técnico + 1 voluntario · **enviar ya** · tipo Mando `lighting_failure` | `dark_stay` |
| `what_off` = `payments` | sin riesgo vital · severidad ≥ 5 · 1 técnico · **enviar ya** · tipo Mando `cashless_down` | `generic_stay_safe` |
| `what_off` = `lights` o `food_stalls` o `everything` o no sé | sin riesgo vital · severidad ≥ 6 · 1 técnico + 1 seguridad · **enviar ya** | `power_keep_away` |

Instrucciones disponibles: `power_keep_away`, `dark_stay`, `crowd_pressure`, `generic_stay_safe`.

Fuentes: [hse.gov.uk](https://www.hse.gov.uk/event-safety/electrical-safety.htm) · [112.jcyl.es](https://112.jcyl.es/web/es/consejos-recomendaciones/vientos.html) · [interior.gencat.cat](https://interior.gencat.cat/es/arees_dactuacio/proteccio_civil/consells_autoproteccio_emergencia/mes_consells_dautoproteccio/grans_concentracions_persones/index.html)

**☐ validado ☐ cambiar:** ______________________________________________

### 22. Falta de agua o suministros · `water_supplies_out`

Familia `supply` · tipo de Mando `water_out` · **Enviar con:** `location_point`, `what` · **Avisa a:** production · **Externo:** ninguno

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿En qué punto de agua o barra estás? Dime algo que veas cerca.**<br>Which water point or bar are you at? Tell me something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Qué falta: agua, comida, hielo u otra cosa?**<br>What is missing: water, food, ice or something else?<br>`what` | opciones<br>`water`, `food`, `ice`, `medical_supplies`, `other` | **sí** | — | el agua con calor es urgente; la comida no |
| 3 | **¿Hay alguien que se encuentre mal por el calor?**<br>Is anyone feeling unwell from the heat?<br>`people_unwell` | sí / no / no sé | **sí** | — | la cadena calor → sin agua → golpes de calor es la que hay que cortar pronto |
| 4 | **¿Se ha acabado del todo o queda poco?**<br>Has it run out completely, or is there a little left?<br>`level` | opciones<br>`empty`, `low`, `unknown` | no | — | plazo para reponer |
| 5 | **¿Cómo está la cola: tranquila, muy larga o con tensión?**<br>How is the queue: calm, very long, or tense?<br>`queue_mood` | opciones<br>`calm`, `long`, `tense`, `unknown` | no | — | la taxonomía prevé que `water_out` degenere en pelea |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `people_unwell` = sí | sin riesgo vital · severidad ≥ 8 · 1 sanitario + 1 logística · **enviar ya** · pasa a `heat_illness` | `heat` |
| `queue_mood` = `tense` | sin riesgo vital · severidad ≥ 7 · 1 logística + 1 seguridad · **enviar ya** | `generic_stay_safe` |
| `what` = `water` | sin riesgo vital · severidad ≥ 6 · 1 logística + 1 voluntario · **enviar ya** | `generic_stay_safe` |
| `what` = `ice` | sin riesgo vital · severidad ≥ 6 · 1 logística · **enviar ya** · tipo Mando `ice_cooling_out` | `generic_stay_safe` |
| `what` = `medical_supplies` | sin riesgo vital · severidad ≥ 6 · 1 logística · **enviar ya** · tipo Mando `medical_supplies_low` | `generic_stay_safe` |
| `what` = `food` o `other` | sin riesgo vital · severidad ≥ 3 · 1 logística · informar a control · tipo Mando `food_shortage` | `generic_stay_safe` |

Instrucciones disponibles: `heat`, `generic_stay_safe`.

⚠ Sin guía abierta sobre qué decir al público cuando falta agua (la Purple Guide es de pago). Las severidades copian la taxonomía de Mando.

Fuentes: [nhs.uk](https://www.nhs.uk/conditions/heat-exhaustion-heatstroke/) · [semicyuc.org](https://semicyuc.org/wp-content/uploads/2021/09/RCP-Guias-ERC-2021-08-Primeros-auxilios-Resuscitation-2021.pdf)

**☐ validado ☐ cambiar:** ______________________________________________

### 23. Fallo de baños o de infraestructura · `infrastructure_failure`

Familia `infra` · tipo de Mando `toilets_blocked` · **Enviar con:** `location_point`, `what` · **Avisa a:** production · **Externo:** ninguno

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 2 | **¿Qué falla: baños, una valla, el suelo, los tornos u otra cosa?**<br>What is failing: toilets, a barrier, the ground, turnstiles or something else?<br>`what` | opciones<br>`toilets`, `barrier`, `flooding`, `turnstile`, `other` | **sí** | — | una valla cedida es un incidente grave de multitudes; un baño, no |
| 3 | **¿Puede hacerse daño alguien ahora mismo?**<br>Could someone get hurt right now?<br>`danger_now` | sí / no / no sé | **sí** | — | separa mantenimiento de urgencia |
| 4 | **¿Hay alguien herido?**<br>Is anyone hurt?<br>`people_hurt` | sí / no / no sé | no | — | añade sanitario |
| 5 | **¿Falla uno, varios o todos?**<br>Is it one, several or all of them?<br>`scale` | opciones<br>`one`, `several`, `all`, `unknown` | no | — | dimensiona |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `people_hurt` = sí | sin riesgo vital · severidad ≥ 7 · 1 sanitario + 1 técnico · **enviar ya** · pasa a `fall_trauma` | `generic_stay_safe` |
| `what` = `barrier` | **RIESGO VITAL** · severidad ≥ 8 · 1 técnico + 2 seguridad · **enviar ya** · tipo Mando `barrier_failure` | `barrier_away` |
| `danger_now` = sí o no sé | sin riesgo vital · severidad ≥ 7 · 1 técnico + 1 seguridad · **enviar ya** | `generic_stay_safe` |
| `what` = `flooding` | sin riesgo vital · severidad ≥ 5 · 1 técnico + 1 logística · **enviar ya** · tipo Mando `heavy_rain_flooding` | `generic_stay_safe` |
| `what` = `turnstile` | sin riesgo vital · severidad ≥ 4 · 1 técnico + 1 voluntario · **enviar ya** · tipo Mando `turnstile_failure` | `queue_wait` |
| `what` = `toilets` o `other` | sin riesgo vital · severidad ≥ 3 · 1 técnico · informar a control | `generic_stay_safe` |

Instrucciones disponibles: `generic_stay_safe`, `barrier_away`, `queue_wait`.

⚠ Sin guía abierta específica; las severidades copian la taxonomía de Mando. Es el protocolo que más tranquilamente puede esperar (`may_wait`).

Fuentes: [hse.gov.uk](https://www.hse.gov.uk/event-safety/crowd-management-controls.htm) · [kqed.org](https://www.kqed.org/news/11930646/8-tips-to-follow-if-youre-trapped-in-a-crushing-crowd)

**☐ validado ☐ cambiar:** ______________________________________________

### 24. Aviso sin clasificar (recogida genérica) · `unknown`

Familia `info` · tipo de Mando `ambiguous_report` · **Enviar con:** `location_point`, `danger_now` · **Avisa a:** coordinator · **Externo:** ninguno

| # | Pregunta (ES / EN) | Respuesta | Crítica | Solo si… | Por qué se pregunta |
|---|---|---|---|---|---|
| 1 | **¿Qué está pasando?**<br>What is happening?<br>`what` | texto libre | **sí** | — | 112 y SAMUR: qué ocurre |
| 2 | **¿Dónde estás exactamente? Dime la zona y algo que veas cerca.**<br>Where exactly are you? Tell me the area and something you can see nearby.<br>`location_point` | zona + referencia | **sí** | — | sin ubicación no se puede enviar a nadie (112 y SAMUR: primero el lugar, con puntos de referencia) |
| 3 | **¿Hay alguien en peligro ahora mismo?**<br>Is anyone in danger right now?<br>`danger_now` | sí / no / no sé | **sí** | — | decide si se envía ya sin saber más |
| 4 | **¿Cuántas personas están afectadas?**<br>How many people are affected?<br>`people_count` | número | no | — | SAMUR: número de heridos; METHANE: N |
| 5 | **¿Estás tú a salvo?**<br>Are you safe yourself?<br>`caller_safe` | sí / no / no sé | no | — | PAS: proteger va antes que socorrer (Cruz Roja) |

| Señal de alarma (se mira en este orden) | Entonces | Instrucción que se da |
|---|---|---|
| `danger_now` = sí o no sé | **RIESGO VITAL** · severidad ≥ 8 · 1 seguridad + 1 sanitario · **enviar ya**<br>⚠ Enviar seguridad + sanitario a ciegas ante «peligro ahora» es criterio propio: es la pareja que cubre más casos. | `generic_stay_safe` |
| `caller_safe` = no | **RIESGO VITAL** · severidad ≥ 7 · 1 seguridad · **enviar ya** | `generic_stay_safe` |
| `danger_now` = no | sin riesgo vital · severidad ≥ 4 · 1 voluntario · informar a control | `generic_stay_safe` |

Instrucciones disponibles: `generic_stay_safe`.

⚠ En cuanto `what` encaje con los disparadores de otro protocolo, se cambia a ese protocolo conservando los slots ya rellenos (mismos ids: location_point, responsive, people_count…).

Fuentes: [madrid.es](https://www.madrid.es/UnidadesDescentralizadas/Emergencias/Samur-PCivil/Samur/ApartadosSecciones/09_QueHacerEnEmergencias/Ficheros/Guia_PrimerosAuxilios_SAMUR.pdf) · [112.gencat.cat](https://112.gencat.cat/es/us-del-112/preguntes-frequeents/index.html) · [theconversation.com](https://theconversation.com/112-y-061-asi-funcionan-los-telefonos-de-emergencias-sanitarias-243736) · [cruzroja.es](https://www.cruzroja.es/guiaprevencionNew/primeros-auxilios.html) · [jesip.org.uk](https://www.jesip.org.uk/joint-doctrine/early-stages-of-an-incident-m-ethane/) · [jesip.org.uk](https://www.jesip.org.uk/wp-content/uploads/2022/03/Posters_METHANE_OCT2021.pdf)

**☐ validado ☐ cambiar:** ______________________________________________

## D. Reglas globales

**Apertura:** «Centro de control del festival. ¿Qué pasa y dónde estás?» / “Festival control centre. What is happening and where are you?”

**Si no sabe decir dónde está** (se prueban en este orden):

- «¿Dónde estás exactamente? Dime la zona y algo que veas cerca.» / “Where exactly are you? Tell me the area and something you can see nearby.”
- «¿Qué tienes cerca: una barra, una torre, una puerta, los baños?» / “What is near you: a bar, a tower, a gate, the toilets?”
- «¿Estás más cerca del escenario o de la salida?» / “Are you nearer the stage or the exit?”
- «¿Puedes compartir tu ubicación desde el móvil?» / “Can you share your location from your phone?”
- «¿Hay alguien con chaleco cerca de ti?» / “Is there someone in a staff vest near you?”

**Frase de paso en incidentes reservados:** «Gracias por avisar. No hace falta que me cuentes nada más. Te paso ahora con una persona del equipo.» / “Thank you for telling us. You do not need to tell me anything more. I am putting you through to a person on the team now.”

- En pantalla compartida solo «Incidente reservado» y el destinatario (p. ej. punto violeta): sin zona, sin texto, sin tipo.
- Nunca megafonía. Nunca radio en abierto: de persona a persona, por teléfono o mensaje directo.
- Policía y cualquier servicio externo: solo con aprobación humana; en violencia sexual y sumisión química con víctima adulta, además con su consentimiento (salvo menor, agresor presente o riesgo).
- No se repite al informante lo que ha contado, no se pide confirmación por repetición, no se pide relato ni descripción del agresor.
- El agente no valora credibilidad, no promete resultados y no informa a terceros (ni a quien dice ser familiar).

### D1. Lo que el agente nunca dice (21)

| Nunca | Por qué | ☐ validado ☐ cambiar |
|---|---|---|
| «Cálmate» / «tranquilízate» | No calma a nadie y suena a reproche. En su lugar: decir qué se está haciendo («ya va un equipo») y dar una tarea concreta. (Northstars del proyecto; SAMUR pide calma al que ayuda, no se la ordena a la víctima.) | ☐ validado ☐ cambiar |
| «Llegan en X minutos» | No se prometen tiempos (NS-05): el agente no controla el recorrido. Se dice «ya va un equipo hacia ahí». | ☐ validado ☐ cambiar |
| «Es un infarto / un golpe de calor / está borracho / es un ataque de ansiedad» | El agente no diagnostica ni clasifica pacientes (SAMUR, «Qué NO hacer»: intentar hacer diagnósticos médicos; dictamen, Anexo D). | ☐ validado ☐ cambiar |
| «No parece grave» / «seguro que no es nada» | Minimizar retrasa la ayuda y no es una valoración que le corresponda. Todo aviso se reenvía (NS-08). | ☐ validado ☐ cambiar |
| «Antes de enviar a nadie necesito que me digas…» | Nunca se retrasa el envío por seguir preguntando: en el 112 «durante la llamada, la ayuda está en camino» (The Conversation, 112/061). | ☐ validado ☐ cambiar |
| «Entendido: agresión sexual en los aseos, ¿correcto?» (repetir o confirmar contenido sensible) | NS-25: no se repite el hecho, no se pide confirmación, no se piden detalles. La taxonomía lo prohíbe (`echo report_content`). | ☐ validado ☐ cambiar |
| «¿Por qué no te fuiste?» / «¿habías bebido?» / «¿qué llevabas puesto?» / «¿seguro que fue así?» | Juzga y culpa. Igualdad: «escucha activa, sin juicios» y «reconocer en todo momento la credibilidad de su relato». | ☐ validado ☐ cambiar |
| «Tienes que denunciar» / «voy a llamar a la policía» | Igualdad: «no presionarla en ningún momento… respetar sus tiempos y sus elecciones». Policía solo con consentimiento (adulta) y aprobación humana. | ☐ validado ☐ cambiar |
| «No te enfrentes» dicho a una víctima de violencia sexual | Anexo C: es culparla. La instrucción `aggression` solo vale para peleas. | ☐ validado ☐ cambiar |
| «Avisa a los de alrededor» / «corred» / «salid todos» | Siembra la carrera (`rumor_panic`). Anexo C; Cruz Roja: «evita toda acción que pueda llevar a cundir el pánico»; Protección Civil: no correr, no gritar, no empujar. | ☐ validado ☐ cambiar |
| Las palabras «bomba», «atentado», «estampida», «pánico» o «evacuación» dichas por el agente al público | Las decide y las dice una persona con cargo, con mensaje pregrabado (HSE: «pre-agreed wording for public announcements»). Sin fuente abierta sobre vocabulario concreto: es criterio de la experta. | ☐ validado ☐ cambiar |
| «¿Seguro que es una bomba?» / «¿no será una broma?» | NS-27: no se valora la credibilidad de una amenaza; la valora la policía (gov.uk: «Police will assess the credibility of the threat»). Se anota literal y se pasa. | ☐ validado ☐ cambiar |
| «Tu hijo está en…» / «sí, tenemos un aviso de ese niño» a quien dice ser familiar | NS-26: nunca se dice dónde está un menor ni se confirma un aviso sobre él. La entrega es en persona, a tutor verificado, con dos miembros del personal. | ☐ validado ☐ cambiar |
| Nombre o descripción de un menor, de una víctima o de un sospechoso por megafonía o canal abierto | Ticket Fairy: nunca anunciar el nombre del menor; dictamen (Anexo D): lo sensible no va por la malla ni por la PA. | ☐ validado ☐ cambiar |
| «Sujétale» / «métele algo en la boca para que no se muerda la lengua» | Epilepsy Action y SAMUR: no sujetar ni meter nada en la boca. | ☐ validado ☐ cambiar |
| «Dale agua» / «dale algo de comer» a quien está inconsciente, convulsionando, confuso o con alergia grave | Riesgo de atragantamiento (SAMUR en todos esos capítulos; Epilepsy Action). | ☐ validado ☐ cambiar |
| «Hazle vomitar» / «dale un café» / «métele en la ducha fría» | NHS (alcohol poisoning): no provocar el vómito, no cafeína, no agua fría. | ☐ validado ☐ cambiar |
| «Sácale lo que tiene clavado» / «hazle un torniquete con el cinturón» | St John: no extraer objetos. ERC 2021: torniquete fabricado y, si es improvisado, solo con formación; el público hace presión directa. | ☐ validado ☐ cambiar |
| «Ponle un collarín» / «muévela a un sitio mejor» | ERC 2021: el collarín no se recomienda en primeros auxilios; no se mueve salvo peligro (Cruz Roja). | ☐ validado ☐ cambiar |
| «Cierra la puerta» / «entrad por la otra puerta» / cualquier orden de flujo al público | Regla dura de Mando: no se cierra una puerta con presión detrás; los desvíos los decide control tras el ensayo en el gemelo. | ☐ validado ☐ cambiar |
| Cualquier consejo médico, dosis o medicamento que no esté en `instructions` | Solo texto aprobado, literal y pretraducido (NS-17 corregida: nada de traducción en caliente). | ☐ validado ☐ cambiar |

### D2. Cuándo deja de preguntar (15)

1. ENVÍO ANTES QUE PREGUNTAS: en cuanto estén rellenos los slots de `dispatch_as_soon_as`, se envía el aviso a Mando; el resto de preguntas se hacen con la ayuda ya en camino.
2. BANDERA ROJA = PARAR: si se cumple una `red_flag` con `dispatch_now`, se envía, se da SU instrucción y ya no se hacen preguntas no críticas (`critical: false`).
3. LAS BANDERAS SE EVALÚAN EN ORDEN y gana la primera que se cumple: las más graves y específicas van primero en la lista.
4. «NO SÉ» ES EL PEOR CASO: un slot `bool` admite true, false o "unknown"; en un slot crítico, "unknown" se trata como la respuesta peligrosa y no se insiste más de una vez (ERC 2021 acepta el sobretriaje).
5. NO SE PREGUNTA LO YA DICHO: antes de preguntar, se rellenan los slots con lo que la persona contó en su primer mensaje.
6. MÁXIMO 5 PREGUNTAS por aviso y cada pregunta se repite como mucho una vez; si sigue sin respuesta, se envía con lo que hay y el slot queda en "unknown".
7. QUIEN AVISA PRIMERO: si quien avisa está en peligro (atrapado, con humo, junto a una pelea o a un objeto sospechoso), primero su instrucción de autoprotección y después las preguntas.
8. MANOS OCUPADAS: si la persona está haciendo compresiones o apretando una herida, se acabaron las preguntas; solo ánimo, conteo y «sigue, ya van».
9. UNA INSTRUCCIÓN CADA VEZ, con el texto literal de `instructions` en el idioma de la persona (es o en). Nunca texto generado ni traducido en caliente. Si habla otro idioma, se usa el inglés.
10. PROTOCOLOS SENSIBLES (`sensitive: true`): solo las preguntas `critical`, sin pedir relato ni descripción, sin repetir lo contado, tono neutro, frase de `reserved_handling` y paso inmediato a una persona.
11. CAMBIO DE ESTADO: si la persona dice que ha cambiado algo («ya no respira», «ha empezado a convulsionar», «ahora hay humo»), se vuelve a los slots críticos o se cambia de protocolo (`switch_to`) conservando los slots con el mismo id.
12. SILENCIO: si con un riesgo vital abierto la persona deja de contestar 60 segundos, se envía lo que haya y se le manda por texto la instrucción que corresponda (el umbral de 60 s es criterio propio).
13. CIERRE: se termina diciendo qué se ha hecho («tu aviso está en control y ya va un equipo») y cómo volver a avisar; nunca un tiempo de llegada.
14. NUNCA SE DESCARTA: un aviso que parece broma o duplicado se reenvía igual marcado como tal; filtrar es cosa de Mando y de las personas.
15. DESEMPATE DE DISPARADORES: si el texto encaja con varios protocolos, gana el que aparece antes en `protocols` (van ordenados de más a menos crítico); `unknown` es siempre el último recurso.

### D3. Parte al 112 — plantilla ETHANE (METHANE si una persona con cargo declara incidente mayor)

El agente solo lo RELLENA con hechos; lo envía una persona tras aprobarlo.

| Letra | Contenido | Sale de los slots |
|---|---|---|
| **M** | ¿Se ha declarado incidente mayor? Sí/No, con fecha y hora. (Solo lo declara una persona con cargo; el agente lo deja en blanco. Si es No, el parte es ETHANE.) | — |
| **E** | ¿Cuál es la ubicación exacta? Lo más precisa posible y en un sistema que entiendan todos: zona del recinto, punto de referencia y puerta más cercana | `location_point`, `last_seen` |
| **T** | ¿Qué tipo de incidente es? En hechos y sin diagnóstico («persona que no responde y no respira normal») | `what`, `kind`, `cause`, `mechanism`, `what_seen`, `state` |
| **H** | ¿Qué peligros hay o puede haber? Multitud densa, humo, estructura, arma, tormenta | `pressure`, `trend`, `hazard`, `weapon`, `near_kitchen_gas`, `people_under` |
| **A** | ¿Cuáles son las mejores rutas de entrada Y de salida, y el punto de encuentro? (Lo pone Mando desde el plano, no quien avisa.) | — |
| **N** | ¿Cuántas víctimas hay y en qué estado? En hechos: responde / respira / sangra mucho (la clasificación P1-P3 la hace un sanitario, no el agente) | `people_count`, `responsive`, `breathing_normal`, `bleeding_heavy`, `people_down` |
| **E** | ¿Qué servicios de emergencia hay ya en el lugar y cuáles y cuántos hacen falta? Equipo sanitario del evento, DESA, seguridad; ambulancia, bomberos, policía | — |

⚠ JESIP es doctrina británica; en España cada 112 autonómico tiene su propio formulario. Se usa como plantilla ordenada del parte, que SIEMPRE aprueba una persona. Las preguntas son traducción propia del póster oficial de JESIP; los ejemplos de recinto y el reparto de qué slot alimenta cada letra son míos. Fuente: [jesip.org.uk](https://www.jesip.org.uk/wp-content/uploads/2022/03/Posters_METHANE_OCT2021.pdf)

### D4. Contexto (el agente no lo aplica)

- Triaje START (solo contexto, el agente NO clasifica pacientes): valora por este orden si camina, si respira por sí misma, la frecuencia respiratoria, la perfusión (pulso radial o relleno capilar < 2 s) y si obedece órdenes; categorías inmediato (rojo), demorado (amarillo), leve (verde) y expectante (negro). Sirve para entender por qué «no responde / no respira» va delante de todo cuando hay varias víctimas. El umbral clásico de 30 respiraciones/min no aparecía en la página abierta: sin verificar. Fuente: [chemm.hhs.gov](https://chemm.hhs.gov/incident-primer/triage/start-triage)
- Densidad de multitudes (G. Keith Still): 2 p/m² es el límite habitual de planificación de eventos, 4 p/m² en colas en movimiento, 4,7 p/m² en gradas de pie (Green Guide) y 5 p/m² el tope para zonas de pie. Fuente: [gkstill.com](https://www.gkstill.com/Support/crowd-density/CrowdDensity-1.html)
