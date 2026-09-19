/* Centro del evento. Las decisiones y sus cifras proceden del estado del servidor. */
(() => {
  'use strict';
  const U = window.MANDO_UI, $ = id => document.getElementById(id), A = x => Array.isArray(x) ? x : [];
  const safeText = value => String(value ?? '').replace(/(?<!\w)\+?\d(?:[\s().-]*\d){8,14}(?!\w)/g, '[dato privado]').replace(/(?:Bearer\s+|(?:token|api[_ -]?key)\s*[:=]\s*)\S+/gi, '[credencial oculta]');
  const E = value => U.esc(safeText(value)), N = U.num;
  const CLOSED = new Set(['resolved', 'false_alarm', 'failed', 'closed']);
  let S = {}, selected = null, filter = 'all', planMap = null, festival = null, flow = false, session = null, connected = false;
  const htmlCache = new WeakMap(), decisionNotes = new Map();
  const receipts = new Map(), sending = new Set();
  let teamFilter = {mine:false,operator:null}, announcedSelection;
  function announceSelection() { if(announcedSelection!==selected){announcedSelection=selected;window.dispatchEvent(new CustomEvent('mando:selection',{detail:selected}));} }
  window.addEventListener('mando:team-filter',event=>{teamFilter=event.detail;renderList();});
  let zoneFilter = null, detailClosed = false, pendingConfirmation = null, feedbackTimer, sound = false, audioContext;
  const actionNames = {ask:'preguntar dónde está',dispatch:'enviar un equipo',reroute:'desviar el flujo de personas',open_gate:'abrir la puerta',close_gate:'cerrar la puerta',stop_show:'parar el espectáculo',evacuate:'evacuar la zona',request_external:'pedir ayuda externa',external:'pedir ayuda externa',notify:'avisar al equipo',followup:'comprobar cómo evoluciona',merge:'reunir los avisos',dismiss:'cerrar el aviso',resupply:'reponer suministros',set_gate:'cambiar el acceso'};
  function human(value) {
    let result = String(value ?? '');
    for (const [key,label] of Object.entries(actionNames)) result=result.replace(new RegExp('\\b'+key+'\\b','gi'),label);
    for (const entity of [...A(S.zones),...A(S.resources)]) if(entity.id&&entity.name) result=result.split(entity.id).join(entity.name);
    return result.replace(/\b(?:M|P|A|S|I|OP)-\d+(?:-[\w-]+)?\b/g,'').replace(/\b(?:tick|ticks)\b/gi,'min').replace(/\bseed\s*[:=]?\s*\d*/gi,'').replace(/\s{2,}/g,' ').trim();
  }
  const H = value => E(human(value));
  function title(i) { return i.label ? human(i.label) : ({medical:'Atención médica',crowd:'Aglomeración',security:'Aviso de seguridad',logistics:'Incidencia de servicios'})[i.family] || 'Incidente en '+zone(i.zone); }
  function atTime(t) {
    if(t==null || !S.clock?.hhmm || S.t==null)return '';
    const [hh,mm]=S.clock.hhmm.split(':').map(Number), mins=((hh*60+mm+Number(t)-Number(S.t))%1440+1440)%1440;
    return `${String(Math.floor(mins/60)).padStart(2,'0')}:${String(mins%60).padStart(2,'0')}`;
  }
  function ago(t) { return t==null||S.t==null?'':Math.max(0,S.t-t)===0?'Ahora':`Hace ${N(Math.max(0,S.t-t),0)} min`; }
  function notice(message) { text('feedback',message);clearTimeout(feedbackTimer);feedbackTimer=setTimeout(()=>text('feedback',''),9000); }
  function status(i) {
    if(i.forecast)return {label:'◷ '+forecastLabel(i),css:i.status==='EVITADO'?'good':'previsto'};
    return i.rank>=8?{label:'▲ CRÍTICO',css:'critico'}:i.rank>=4?{label:'! ATENCIÓN',css:'atencion'}:{label:'ⓘ INFORMATIVO',css:'informativo'};
  }
  function visibleItems() {
    return items().filter(i=>(!teamFilter.mine||i.owner?.id===teamFilter.operator)&&(!zoneFilter||i.zone===zoneFilter))
      .filter(i=>filter==='all'||filter==='forecast'&&i.forecast||filter==='critical'&&!i.forecast&&i.rank>=8||filter==='attention'&&!i.forecast&&i.rank>=4&&i.rank<8);
  }
  function selectItem(id, focus=false) { selected=id;detailClosed=false;renderList();renderDetail();renderMap();announceSelection();if(focus)$('detail').focus({preventScroll:true}); }
  function html(el, value) {
    if (htmlCache.get(el) === value) return;
    const focused = document.activeElement, inside = focused && el.contains(focused);
    const identity = inside ? {id:focused.id, data:{...focused.dataset}, value:focused.value, start:focused.selectionStart, end:focused.selectionEnd} : null;
    el.innerHTML = value; htmlCache.set(el, value);
    if (identity) {
      const replacement = Array.from(el.querySelectorAll('button,input,a,textarea')).find(node => identity.id ? node.id===identity.id : Object.keys(identity.data).length && Object.entries(identity.data).every(([k,v])=>node.dataset[k]===v));
      if (replacement) { if (/INPUT|TEXTAREA/.test(replacement.tagName)) { replacement.value=identity.value; if (identity.start!=null) replacement.setSelectionRange(identity.start,identity.end); } replacement.focus({preventScroll:true}); }
    }
  }
  function text(id, value) { $(id).textContent = safeText(value); }
  function zone(id) { return A(S.zones).find(z => z.id === id)?.name || 'Ubicación pendiente'; }
  function resource(id) { return A(S.resources).find(r => r.id === id)?.name || (/^[\w]+_\d+$/.test(id||'')?'Equipo asignado':id) || 'Sin asignar'; }
  function calls(id) { return A(S.calls?.calls).filter(c => c.incident === id); }
  function reports(id) { return A(S.reports).filter(r => r.incident === id); }
  function teams(id) {
    const front=A(S.fronts).find(f=>f.id===id), incident=A(S.incidents).find(i=>i.id===id);
    if(Array.isArray(front?.resources)) return front.resources.map(r=>typeof r==='string'?r:resource(r.resource||r.id)).join(', ');
    const assigned=front?.team || incident?.assigned;
    if(Array.isArray(assigned))return assigned.map(r=>resource(typeof r==='string'?r:r.resource||r.id)).join(', ');
    return [...new Set(A(S.actions).filter(a=>a.incident===id&&a.resource&&a.status==='executing').map(a=>resource(a.resource)))].join(', ');
  }
  function callStatus(c) { return ({accept:'✓ Equipo confirmado',reject:'✕ El equipo no puede acudir',no_answer:'! Sin respuesta del equipo'})[c?.result] || (c?.result ? '✓ Llamada finalizada' : '◷ Contactando con el equipo'); }
  function forecastTitle(p) {
    const target = p.metric === 'free_units' ? ({medical:'Equipos médicos',ambulance:'Ambulancias',security:'Seguridad'})[p.resource] || 'Recurso crítico' : zone(p.zone);
    return `${target}: ${p.metric === 'density' ? N(p.threshold) + ' personas/m²' : p.metric === 'water_l' ? 'sin agua' : p.metric === 'route_blocked' ? 'ruta sanitaria bloqueada' : 'sin unidades libres'}`;
  }
  function forecastLabel(p) { return ({NO_CUMPLIDO:'NO CUMPLIDO',NO_VERIFICABLE:'NO VERIFICABLE'})[p.status] || p.status || 'PREVISTO'; }
  function items() {
    const real = A(S.incidents).filter(i => !CLOSED.has(i.status)).map(i => ({...i, forecast:false, rank:Number(i.priority) || 0}));
    const predicted = A(S.forecasts).map(p => ({...p, forecast:true, rank:p.status === 'PREVISTO' ? (p.severity === 'critico' ? 9 : 7) : 0}));
    return [...real, ...predicted].sort((a,b) => b.rank-a.rank || (a.eta_min ?? 99)-(b.eta_min ?? 99) || String(a.id).localeCompare(String(b.id)));
  }
  function renderMetrics() {
    const rows = [], active = A(S.incidents).filter(i => !CLOSED.has(i.status));
    if (Array.isArray(S.incidents)) rows.push(['Incidentes activos',N(active.length,0),`${active.filter(i => Number(i.priority)>=8 || Number(i.severity)>=8).length} críticos · ${A(S.approvals).length} decisiones pendientes`]);
    if (Array.isArray(S.resources)) rows.push(['Equipos desplegados',`${S.resources.filter(r => ['busy','en_route'].includes(r.status)).length}`,`${S.resources.filter(r => r.status==='available').length} libres · ${S.resources.filter(r => r.status==='offline').length} no disponibles`]);
    if (S.metrics?.time_to_first_action != null) rows.push(['Tiempo hasta la primera acción',`${N(S.metrics.time_to_first_action)} min`,S.metrics.time_to_first_action_n!=null?`Media · N = ${N(S.metrics.time_to_first_action_n,0)}`:'Media de esta ejecución']);
    if (Array.isArray(S.zones) && S.zones.length) {
      const total = S.zones.reduce((n,z) => n+(Number(z.occupancy)||0),0), capacity = S.zones.reduce((n,z) => n+(Number(z.capacity)||0),0), dense = [...S.zones].sort((a,b)=>(b.density||0)-(a.density||0))[0];
      rows.push([capacity?'Nivel de aforo total':'Personas dentro del recinto',capacity?N(100*total/capacity)+' %':N(total,0),`${N(total,0)} personas${dense.density!=null?' · '+zone(dense.id)+': '+N(dense.density)+' personas/m²':''}`]);
      text('attendance',`${N(total,0)} asistentes`);
    }
    html($('metrics'),rows.map(([label,value,note])=>`<div class="metric"><label>${E(label)}</label><strong>${E(value)}</strong><small>${E(note)}</small></div>`).join(''));
  }
  function renderList() {
    const list = items(), visible = visibleItems();
    text('active-count',`${A(S.incidents).filter(i=>!CLOSED.has(i.status)).length} activos`);
    $('clear-zone').hidden=!zoneFilter;text('clear-zone',zoneFilter?`${zone(zoneFilter)} · Quitar filtro ×`:'');
    html($('incidents'),visible.map(i => {
      const isCritical = i.rank>=8, channel = reports(i.id)[0]?.via || reports(i.id)[0]?.channel;
      const c = calls(i.id).at(-1), team = teams(i.id), label=status(i), front=A(S.fronts).find(f=>f.id===i.id);
      return `<button class="incident-card ${label.css} ${selected===i.id?'selected':''} ${i.status==='EVITADO'?'evited':''}" data-item="${E(i.id)}" aria-pressed="${selected===i.id}">
      <span class="card-top"><span class="badge ${label.css}">${E(label.label)}</span><small>${E(ago(i.issued_t??i.t_open))}</small></span>
      <h3>${i.forecast?E(forecastTitle(i)):H(title(i))}</h3>
      ${i.forecast?`<span class="countdown">${i.status==='PREVISTO'?(i.eta_min!=null?`En ${N(i.eta_min,0)} min`:'En observación'):E(forecastLabel(i))}</span><p>Previsión del gemelo · si nadie actúa</p>`:`<p class="why">${H(front?.why_waiting||i.explain||reports(i.id)[0]?.text||'Mando está revisando el aviso.')}</p>${c?`<span class="call-status ${E(c.result||'')}">${callStatus(c)}</span>`:''}`}
      ${!i.forecast&&(i.owner||i.suggested_role)?`<span class="team-owner">${i.owner?'Lo lleva '+E(i.owner.name):'Sin responsable'}${i.suggested_role?' · sugerido: '+E(i.suggested_role):''}${i.sources_text?'<br>'+H(i.sources_text):''}</span>`:''}
      <span class="card-bottom"><span>${team?H(team)+(front?.eta!=null?' · llega en '+N(front.eta,0)+' min':''):i.forecast?'◷ Gemelo':channel?U.channel(channel)+E(U.labels[channel]||'Aviso recibido'):'Pendiente de asignación'}</span>${!i.forecast&&i.priority!=null?`<span class="priority" title="Prioridad sobre 10">${N(i.rank,0)}<small>/10</small></span>`:''}</span></button>`;
    }).join('') || (Array.isArray(S.incidents)&&!S.incidents.some(i=>!CLOSED.has(i.status))&&filter==='all'&&!zoneFilter&&!teamFilter.mine?`<div class="empty"><strong>✓ Todo en orden · 0 incidentes activos</strong>${A(S.incidents).filter(i=>['resolved','closed'].includes(i.status)).at(-1)?'Último resuelto: '+H(title(A(S.incidents).filter(i=>['resolved','closed'].includes(i.status)).at(-1))):'Los nuevos avisos aparecerán aquí.'}</div>`:'<p class="empty">No hay avisos en este filtro.</p>'));
    const forecasts=A(S.forecasts), counts=status=>forecasts.filter(p=>p.status===status).length;
    text('forecast-count',forecasts.length?`${counts('PREVISTO')} previstos · ${counts('EVITADO')} evitados* · ${counts('CUMPLIDO')} cumplidos · ${counts('NO_CUMPLIDO')} no cumplidos · ${counts('NO_VERIFICABLE')} sin verificar. *Asociación temporal al plan.`:'');
    const next=list.find(i=>i.forecast&&i.status==='PREVISTO');
    html($('anticipation'),next?`<small>◷ PREVISTO · previsión del gemelo</small><strong>${E(forecastTitle(next))}${next.eta_min!=null?' en '+N(next.eta_min,0)+' min':''} si nadie actúa</strong><small>Las órdenes actuales continúan. Simulación · N = 1 ensayo.</small>`:'<strong>Sin previsiones de riesgo publicadas</strong><small>Selecciona una zona para ver sus avisos. El gemelo no garantiza lo que ocurrirá.</small>');
  }
  function planHTML(p, old=false) {
    return `<article class="plan ${old?'old':'new'}"><h4>${old?'Plan anterior: ':'Plan recomendado: '}${H(p.objective||'Coordinación del incidente')}</h4>${p.id?`<small class="reference">Referencia ${E(p.id)}</small>`:''}<p>${H(p.why||'')}</p><ol class="steps">${A(p.steps).map(a=>`<li>${H(a.why||a.reason||actionNames[a.kind]||'Actuación en curso')}${a.resource?' · '+E(resource(a.resource)):''}</li>`).join('')}</ol>${A(p.assumptions).length?`<strong>Supuestos del plan</strong><ul>${A(p.assumptions).map(a=>`<li class="assumption ${a.holds===false?'bad':''}">${a.holds===false?'✕ SUPUESTO ROTO: ':a.holds===true?'✓ ':'? Por verificar: '}${H(a.text)}</li>`).join('')}</ul>`:''}${A(p.rehearsal).length?`<p><b>Efectividad ensayada</b> · simulación, N = 1 por opción</p><ul>${A(p.rehearsal).map(r=>`<li>${H(r.label)}${r.value!=null?' '+(typeof r.value==='number'?N(r.value):H(r.value))+' '+E(r.unit||''):''}${r.chosen?' · ✓ elegido':''}</li>`).join('')}</ul>`:''}</article>`;
  }
  function branch(b, label) { return `<div class="branch"><strong>${label}</strong><p>${H(b?.text||(A(b?.figures).length?'Proyección del gemelo':'Sin futuro ensayado disponible'))}</p>${A(b?.figures).filter(f=>f.v!=null).map(f=>`<p>${H(f.k)}: <b>${N(f.v)}</b></p>`).join('')}${b?.horizon_min!=null?`<small>Durante ${N(b.horizon_min,0)} min</small>`:''}</div>`; }
  function approvalLabel(a) { return ({evacuate:'Aprobar evacuación',stop_show:'Aprobar parada del espectáculo',request_external:'Aprobar ayuda externa',external:'Aprobar ayuda externa',reroute:'Aprobar desvío de personas',open_gate:'Aprobar apertura de la puerta',close_gate:'Aprobar cierre de la puerta',set_gate:'Aprobar cambio de acceso'})[a.kind] || 'Aprobar el plan'; }
  function decisionHTML(a) {
    const c=a.card||{}, prepared=A(S.actions).find(x=>x.id===a.id)?.params?.prepared && a.kind==='evacuate';
    return `<section class="decision"><h3>Necesita tu decisión${a.required===2?` · ${N(a.votes||0,0)} de 2 firmas`:''}</h3><p>${H(c.question||a.why||actionNames[a.kind]||'Autorizar el plan propuesto')}</p>${c.remaining_min!=null?`<strong class="countdown">${c.remaining_min===0?'Plazo agotado':N(c.remaining_min,0)+' min para decidir'}</strong>`:''}${c.role||c.deputy?`<p>${H(c.role||'')}${c.deputy?' · suplente: '+H(c.deputy):''}${c.escalated?' · Avisado el suplente':''}</p>`:''}<div class="branches">${branch(c.if_approved,'✓ Si apruebas')}${branch(c.if_vetoed,'✕ Si no apruebas')}</div><small>${c.rehearsed?'Dos futuros ensayados en el gemelo · N = 1 por opción':'Consecuencias disponibles; ensayo no confirmado'}</small><label class="decision-note" for="note-${E(a.id)}">${prepared?'Orden expresa obligatoria: escribe EVACUAR y tu instrucción':'Nota de decisión (opcional)'}</label><textarea id="note-${E(a.id)}" data-decision-note="${E(a.id)}" maxlength="400" rows="2">${E(decisionNotes.get(a.id)||'')}</textarea><div class="decision-controls"><button class="primary" data-approve="${E(a.id)}" ${sending.has(a.id)?'disabled':''}>✓ ${E(approvalLabel(a))}</button><button data-veto="${E(a.id)}" ${sending.has(a.id)?'disabled':''}>Vetar · V</button></div><small>El reloj del recinto sigue hasta que lo pauses.</small></section>`;
  }
  function renderDetail() {
    const item=items().find(i=>i.id===selected);
    if(!item||detailClosed){html($('detail'),'<p class="empty">Selecciona un incidente o una previsión para ver qué pasa, qué hará Mando y qué necesita decidir una persona.</p>'+(!detailClosed?A(S.approvals).slice(0,1).map(decisionHTML).join(''):''));return;}
    if(item.forecast){
      const p=item, unit=p.metric==='density'?' /m²':p.metric==='water_l'?' L':'';
      html($('detail'),`<div class="detail-intro"><span class="badge ${p.status==='EVITADO'?'good':'previsto'}">◷ ${E(forecastLabel(p))}</span><h3>${E(forecastTitle(p))}</h3>${p.status==='PREVISTO'&&p.eta_min!=null?`<strong class="countdown">En ${N(p.eta_min,0)} min</strong>`:''}<p>Previsión del gemelo si nadie actúa. Las órdenes actuales continúan, sin acciones nuevas.</p><div class="facts">${p.current!=null?`<div><small>Valor al prever</small>${N(p.current)}${unit}</div>`:''}${p.predicted!=null?`<div><small>Valor previsto</small>${N(p.predicted)}${unit}</div>`:''}</div>${p.threshold!=null?`<p>Umbral de aviso: ${N(p.threshold)}${unit}</p>`:''}${atTime(p.issued_t)?`<p>Emitida a las ${E(atTime(p.issued_t))}${atTime(p.due_t)?' · prevista para las '+E(atTime(p.due_t)):''}.</p>`:''}${p.intervention?`<article class="plan new"><h4>Plan asociado</h4><p>${H(A(S.plans).find(plan=>plan.id===p.intervention.id)?.objective||'Intervención registrada')}</p><p>${p.status==='EVITADO'?'El umbral no se observó durante el seguimiento. ':''}Asociación temporal; no demuestra que el plan fuera la causa.</p></article>`:''}<p>${p.status==='NO_VERIFICABLE'?'Faltan observaciones. No se contabiliza como evitada ni como error de predicción.':p.status==='NO_CUMPLIDO'?'La previsión no se cumplió y no hay una intervención asociada. Cuenta como error, no como evitada.':p.status==='CUMPLIDO'?'El umbral previsto se ha observado.':'El gemelo conoce la dinámica del simulador, pero no los sucesos futuros del caso.'}</p><small>Simulación · N = 1 ensayo</small></div>`);return;
    }
    const plans=A(S.plans).filter(p=>p.incident===item.id), latest=plans.at(-1), broken=[...plans].reverse().find(p=>p.invalidated_by || A(p.assumptions).some(a=>a.holds===false));
    const related=new Set([item.id,...plans.map(p=>p.id),...A(S.actions).filter(a=>a.incident===item.id).map(a=>a.id),...reports(item.id).map(r=>r.id)]);
    const logs=A(S.log).filter(e=>related.has(e.ref)||e.data?.incident===item.id||related.has(e.data?.plan)).slice(-12);
    const callList=calls(item.id), live=callList.find(c=>c.can_take), approvals=A(S.approvals).filter(a=>a.incident===item.id), label=status(item), receipt=receipts.get(item.id);
    const front=A(S.fronts).find(f=>f.id===item.id);
    html($('detail'),`${broken||approvals.length?`<div class="broken-banner" role="status"><strong>${broken?'▲ SUPUESTO ROTO':'▲ Requiere intervención'}</strong>${broken?'<p>Requiere intervención · el plan anterior ha dejado de ser válido.</p>':''}</div>`:''}
    <div class="detail-intro"><span class="badge ${label.css}">${E(label.label)}</span><h3>${H(title(item))}</h3><p class="summary">${H(item.explain||reports(item.id)[0]?.text||'Mando está revisando el aviso.')}</p><small class="reference">Referencia ${E(item.id)}</small><div class="facts"><div><small>Ubicación exacta</small><b>${E(item.zone_name||zone(item.zone))}</b>${item.location?'<p>'+E(item.location)+'</p>':''}</div><div><small>Equipos asignados</small><b>${H(teams(item.id)||'Sin equipo asignado')}</b>${front?.eta!=null?`<p>De camino · llega en ${N(front.eta,0)} min</p>`:''}</div></div></div>
    ${receipt?`<p class="decision-receipt">✓ ${E(receipt.message)} · hace ${N(Math.max(0,Math.floor((Date.now()-receipt.at)/1000)),0)} s</p>`:''}
    ${broken?`<div class="plan-comparison"><div><strong>Plan anterior</strong><s>${H(broken.objective||'Plan invalidado')}</s></div><div><strong>Nuevo plan</strong>${latest&&latest!==broken?H(latest.objective||'Plan actualizado'):'Mando está preparando la alternativa.'}</div></div>`:''}
    ${approvals.slice(0,1).map(decisionHTML).join('')}${approvals.length>1?`<p class="muted">Quedan ${approvals.length-1} decisiones adicionales para este incidente.</p>`:''}
    ${latest&&latest!==broken?planHTML(latest):!latest?'<p class="empty">Mando aún no ha publicado un plan.</p>':''}
    ${broken?`<details><summary>Revisar el supuesto que falló</summary>${planHTML(broken,true)}</details>`:''}
    ${callList.map(c=>`<article class="plan"><small>${c.real?'HappyRobot · real':'Voz simulada'}</small><strong class="call-status ${E(c.result||'')}">${callStatus(c)}</strong><p>${H(c.title||'Coordinación del equipo')}</p>${c.eta_min!=null?`<p>Llegada: ${N(c.eta_min,0)} min</p>`:''}${c.signal?.text?`<p>Cambio de orden: ${H(c.signal.text)}</p>`:''}</article>`).join('')}
    <section data-receipt-incident="${E(item.id)}" aria-label="Recibo del incidente"></section>
    <h2>Cronología del incidente</h2><ol class="timeline">${logs.map(e=>`<li>${atTime(e.t)||ago(e.t)?`<time>${E(atTime(e.t)||ago(e.t))}</time>`:''}${H(e.text)}</li>`).join('')||'<li>Aún no hay eventos asociados.</li>'}</ol>
    ${live?`<form class="direct" data-signal="${E(live.action_id||live.id)}"><h2>Comunicaciones directas</h2><label for="message-team">Mensaje al equipo en la llamada HappyRobot</label><input id="message-team" name="message" maxlength="400" required autocomplete="off"><button type="submit">Mensaje al equipo</button></form>`:''}`);
  }
  function renderMap() {
    if(!planMap||!S.zones)return;
    const selectedItem=items().find(i=>i.id===selected), P=window.PLANO;
    for(const z of A(S.zones)){
      const r=planMap.zones[z.id];if(!r)continue;
      const incidents=items().filter(i=>i.zone===z.id&&!i.forecast), critical=incidents.some(i=>i.rank>=8), attention=incidents.length>0;
      const forecast=A(S.forecasts).some(p=>p.zone===z.id&&p.status==='PREVISTO');
      r.g.setAttribute('class',`zone ${z.density>=5?'d-red':z.density>=4?'d-amber':'d-green'} ${critical?'incident-critical':attention?'incident-attention':''} ${forecast?'has-forecast':''} ${z.state==='closed'?'blocked':''} ${selectedItem?.zone===z.id||zoneFilter===z.id?'selected':''}`);
      r.g.setAttribute('role','button');r.g.setAttribute('aria-label',`${safeText(z.name)}: ${N(z.density)} personas por metro cuadrado. ${critical?'Crítico. ':''}${incidents.length} incidentes. ${forecast?'Previsión activa. ':''}${z.state==='closed'?'Bloqueada. ':''}Filtrar avisos de esta zona.`);
      r.g.setAttribute('aria-pressed',String(selectedItem?.zone===z.id||zoneFilter===z.id));
      r.dens.textContent=N(z.density)+' /m²';r.pct.textContent=flow?`${N(z.occupancy,0)} pers. · ${N((z.ratio||0)*100,0)} %`:'';
      r.state.textContent=z.state==='closed'?'▧ Bloqueada':critical||z.density>=5?'▲ Crítico':attention||z.density>=4||z.state==='restricted'?'! Atención':forecast?'◷ Previsto':'✓ Normal';
    }
    planMap.gReroutes.replaceChildren();planMap.gTokens.replaceChildren();
    for(const z of A(S.zones)){
      const to=z.flags?.reroute_to;if(to&&P.ZONES[to]&&P.ZONES[z.id]){const [a,b]=P.edgePoints(z.id,to);P.el('path',{d:`M${a.x} ${a.y}L${b.x} ${b.y}`,class:'reroute','marker-end':'url(#arr)'},planMap.gReroutes);}
    }
    for(const edge of Object.values(planMap.edges)){
      if(!edge.flow)continue;
      const z=A(S.zones).find(z=>z.id===edge.a), reverse=A(S.zones).find(z=>z.id===edge.b);
      const n=(z?.flags?.flow_out?.[edge.b]||0)-(reverse?.flags?.flow_out?.[edge.a]||0);
      edge.flow.style.display=n?'':'none';edge.flow.setAttribute('stroke-width',Math.min(12,2+Math.abs(n)/50));
      edge.flow.setAttribute('marker-end',n>0?'url(#arr)':'');edge.flow.setAttribute('marker-start',n<0?'url(#arr)':'');
    }
    const offsets={};
    A(S.resources).filter(r=>r.status!=='offline').forEach(r=>{if(!P.ZONES[r.zone])return;const z=P.ZONES[r.zone],i=offsets[r.zone]||0;offsets[r.zone]=i+1;const x=z.x+z.w-18-(i%6)*16,y=z.y+z.h-13-Math.floor(i/6)*16;
      const dot=P.el('circle',{cx:x,cy:y,r:6,class:'team'},planMap.gTokens);P.el('title',{},dot).textContent=safeText(`${r.name} · ${r.status==='available'?'libre':'desplegado'}`);
    });
  }
  function runLink(value) {
    try{const u=new URL(value);if(u.protocol!=='https:'||!/^platform(?:\.eu)?\.happyrobot\.ai$/.test(u.hostname)||!u.pathname.includes('/runs/'))return '';u.search='';u.hash='';u.username='';u.password='';return `<a href="${U.esc(u.href)}" target="_blank" rel="noopener noreferrer">Ver registro de la llamada</a>`;}catch{return '';}
  }
  function renderServices() {
    const pres=S.presentation||{}, workflows=S.happyrobot||{}, health=S.service_health||{}, rows=[], states=[];
    function add(name,status,last,note,extra=''){states.push({name,status,note});rows.push(`<article class="service ${E(status)}"><strong>${E(name)}</strong><span class="status">${E(({caido:'✕ Caído',degradado:'! Degradado',operativo:'✓ Operativo',simulado:'◷ Simulado',pendiente:'? Sin verificar'})[status]||status)}</span><small>${E(last?'Último evento: '+last:'Sin evento observado')}</small>${note?`<small>${H(note)}</small>`:''}${extra}</article>`);}
    const down=channel=>Math.max(Number(health.comms_down?.[channel])||0,Number(health.comms_down?.all)||0)>Number(S.t||0);
    const latest=ch=>{const rs=A(S.reports).filter(r=>(r.via||r.channel)===ch);return rs.length?'min '+rs.at(-1).t:null;};
    const voiceSim=/simulad/.test(pres.voice||'')||S.calls?.mode==='sim';
    add('Canal de voz',down('voice')?'caido':voiceSim?'simulado':S.calls?.real_sent?'operativo':'pendiente',A(S.calls?.calls).at(-1)?.t!=null?'min '+A(S.calls.calls).at(-1).t:null,down('voice')?'Plan B: voz simulada; canal interrumpido':pres.voice,S.calls?.turn_latency_ms!=null?`<small>Turno: ${N(S.calls.turn_latency_ms,0)} ms · N = ${N(S.calls.turn_latency_n,0)}</small>`:'');
    for(const ch of ['web','telegram','email','sms','sensor']){
      const tg=S.telegram||{}, last=latest(ch), simulated=ch==='sensor'||(ch!=='telegram'&&ch!=='web'&&!workflows[ch]?.configured);
      const status=down(ch)?'caido':ch==='telegram'?tg.status==='error'?'caido':tg.status==='on'?'operativo':'pendiente':simulated?'simulado':last||ch==='web'&&connected?'operativo':'pendiente';
      add('Canal '+(U.labels[ch]||ch),status,last,ch==='telegram'&&status==='caido'?'Plan B: avisar por la web':ch==='sensor'?'Sensores del simulador':status==='pendiente'?'Sin prueba de conexión':null);
    }
    const names={dispatch:'Despacho por teléfono',webcall:'Despacho Web call',ask:'Consulta al equipo',notify:'Aviso al equipo',external:'Apoyo externo',followup:'Seguimiento',intake:'Ingesta texto / Telegram',chat:'Chat del asistente',voice:'Ingesta de voz',email:'Ingesta email',sms:'Ingesta SMS',sanitario:'Equipos sanitarios',seguridad:'Seguridad',tecnico:'Infraestructura',logistica:'Logística y proveedores',director:'Decisión del director',externos:'Servicios externos (prueba)',difusion:'Difusión de texto aprobada',relevo:'Relevo y refuerzo',personal:'Partes de personal',avisos_externos:'Avisos externos entrantes'};
    const keys=new Set(['dispatch','webcall','voice','intake','email','sms',...Object.keys(workflows)]);
    for(const key of keys){const w=workflows[key]||{}, voiceKey=['dispatch','webcall','voice','ask'].includes(key);const state=voiceKey&&down('voice')?'caido':w.last_error?'degradado':!w.configured?(S.calls?.mode==='sim'?'simulado':'pendiente'):w.last_event?'operativo':'pendiente';add(names[key]||key,state,w.last_event,w.last_error?'Plan B local · '+w.last_error:!w.configured?'Sin workflow configurado':w.last_request?'Último envío: '+w.last_request:w.last_event?'Evento recibido':'Configurado; esperando evento',runLink(w.run_url)+(w.latency_ms!=null?`<small>Latencia: ${N(w.latency_ms,0)} ms</small>`:''));}
    html($('services'),rows.join(''));
    const failed=states.filter(s=>s.status==='caido'||s.status==='degradado');
    const allConnected=states.length>0&&states.every(s=>s.status==='operativo');
    text('services-summary',!connected?'↻ Reconectando con el centro':failed.length?'! '+failed.map(s=>s.name).join(', ')+' · revisar plan B':allConnected?'✓ Todos los canales conectados':voiceSim?'◷ Voz simulada · consulta el estado de cada canal':'? Canales pendientes de verificar');
    $('services-summary').className=allConnected?'good-text':failed.length?'critical-key':'muted';
    text('service-note',pres.banner||'Estado observado; «configurado» no acredita una ejecución real');
  }
  function render(state) {
    if(!state||typeof state!=='object')return;
    if(session!==state.session?.id){session=state.session?.id;selected=null;zoneFilter=null;detailClosed=false;decisionNotes.clear();receipts.clear();announcedSelection=undefined;$('confirm-decision').close();pendingConfirmation=null;}
    const previousAlerts=new Set(A(S.approvals).map(a=>a.id));
    S=state;
    if(!detailClosed&&(!selected||!items().some(i=>i.id===selected)))selected=visibleItems()[0]?.id||null;
    if(pendingConfirmation&&!A(S.approvals).some(a=>a.id===pendingConfirmation.id)){$('confirm-decision').close();pendingConfirmation=null;notice('La decisión ha cambiado o ya la ha atendido otra persona.');}
    text('event-name',S.event_name||festival?.name||'Centro de control');
    text('honesty',`Recinto simulado${S.presentation?.voice?' · voz '+S.presentation.voice:''}`);
    text('clock',S.clock?.hhmm||'—');
    text('connection',connected?(S.session?.running?'● En vivo':'● En vivo · simulación en pausa'):'↻ Reconectando…');
    $('reconnecting').hidden=connected;
    text('play',S.session?.running?'Pausar · Espacio':'Iniciar · Espacio');
    text('notification-count',A(S.approvals).length?N(S.approvals.length,0):'');
    renderMetrics();renderList();renderDetail();renderMap();renderServices();
    if($('resources-dialog').open)renderResources();
    if(sound&&A(S.approvals).some(a=>!previousAlerts.has(a.id)))chime();
    window.dispatchEvent(new CustomEvent("mando:state",{detail:S}));announceSelection();
  }
  async function command(url,body){try{const result=await U.api(url,body);notice(result.pending?`${result.votes} de ${result.required} firmas; falta otra persona.`:'Acción registrada.');return result;}catch(e){notice(human(e.message)+' Si requiere operador, entra por «Operador · acceso».');return null;}}
  async function decide(id, ok, confirmed=false) {
    const note=decisionNotes.get(id)||'', approval=A(S.approvals).find(a=>a.id===id), action=A(S.actions).find(a=>a.id===id)||approval;
    if(!approval||sending.has(id))return;
    if(ok && action?.kind==='evacuate' && action.params?.prepared && !/^EVACUAR/i.test(note.trim())){
      notice('Esta evacuación preparada exige una orden expresa: escribe EVACUAR y la instrucción en la nota.');
      $('note-'+id)?.focus();return;
    }
    if(ok&&!confirmed&&['evacuate','stop_show','request_external','external'].includes(action?.kind)){
      pendingConfirmation={id,session};text('confirm-title',approvalLabel(approval));
      text('confirm-consequence',human(approval.card?.if_approved?.text||approval.card?.question||approval.why||actionNames[action.kind]));
      text('confirm-approve','Confirmar: '+(actionNames[action.kind]||'aprobar el plan'));
      $('confirm-decision').showModal();return;
    }
    sending.add(id);renderDetail();const decisionSession=session;
    const result=await command('/api/approve',{action_id:id,ok,...(note?{note}:{})});sending.delete(id);
    if(result&&decisionSession===session){
      const message=result.pending?`Firmado por ti · ${result.votes} de ${result.required} firmas; falta otra persona`:ok?'Aprobado por ti':'Vetado por ti';
      receipts.set(approval.incident,{message,at:Date.now()});notice(message+' · hace 0 s');
      // No hay una API de deshacer: nunca simular que se puede retirar la orden.
      if(!result.pending)S={...S,approvals:A(S.approvals).filter(a=>a.id!==id)};
      renderDetail();
    }
  }
  $('confirm-approve').onclick=()=>{const pending=pendingConfirmation;pendingConfirmation=null;$('confirm-decision').close();if(pending?.session===session)decide(pending.id,true,true);};
  $('confirm-decision').addEventListener('close',()=>{pendingConfirmation=null;});
  document.addEventListener('input',event=>{const id=event.target.dataset?.decisionNote;if(id)decisionNotes.set(id,event.target.value);});
  document.addEventListener('click',event=>{
    const b=event.target.closest('button');if(!b)return;
    if(b.dataset.item)selectItem(b.dataset.item);
    if(b.dataset.filter){filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));renderList();}
    if(b.dataset.control)command('/api/control',{cmd:b.dataset.control});
    if(b.dataset.approve||b.dataset.veto)decide(b.dataset.approve||b.dataset.veto,!!b.dataset.approve);
    if(b.dataset.view){
      document.querySelectorAll('[data-view]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));
      if(b.dataset.view==='resources'){renderResources();const team=$('team-panel');if(team)$('resources-dialog').appendChild(team);$('resources-dialog').showModal();}
      else if(b.dataset.view==='map')$('map').querySelector('[data-zone]')?.focus();
      else if(b.dataset.view==='incidents')$('incidents').querySelector('[data-item]')?.focus();
      else{zoneFilter=null;filter='all';document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.filter==='all')));renderList();renderMap();}
    }
  });
  document.addEventListener('submit',event=>{const f=event.target.closest('[data-signal]');if(!f)return;event.preventDefault();command('/api/call/'+encodeURIComponent(f.dataset.signal)+'/signal',{text:new FormData(f).get('message')});});
  $('map').addEventListener('click',event=>{const id=event.target.closest('[data-zone]')?.dataset.zone;if(!id)return;zoneFilter=id;selectItem(visibleItems()[0]?.id||null);const z=A(S.zones).find(z=>z.id===id);text('map-note',`${zone(id)}${z?.density!=null?' · '+N(z.density)+' personas/m² · atención desde 4,0':''}. ${visibleItems().length} avisos en este filtro.`);});
  $('map').addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
  document.addEventListener('keydown',event=>{
    if(event.repeat||event.ctrlKey||event.metaKey||event.altKey||event.defaultPrevented)return;
    if($('confirm-decision').open||$('resources-dialog').open)return;
    if(event.key==='Escape'){event.preventDefault();closeDetail();return;}
    if(/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)||event.target.isContentEditable)return;
    const key=event.key.toLowerCase(), commands={' ':'toggle',s:'step',k:'key_moment',r:'reset'};
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)&&($('incidents').contains(event.target)||event.target===$('incidents'))){
      event.preventDefault();const list=visibleItems(), current=list.findIndex(i=>i.id===(event.target.dataset?.item||selected));
      const index=event.key==='Home'?0:event.key==='End'?list.length-1:Math.max(0,Math.min(list.length-1,current+(event.key==='ArrowDown'?1:-1)));
      if(list[index]){selectItem(list[index].id);Array.from($('incidents').querySelectorAll('[data-item]')).find(b=>b.dataset.item===list[index].id)?.focus();}return;
    }
    if(key==='enter'&&event.target.dataset?.item){event.preventDefault();selectItem(event.target.dataset.item,true);return;}
    if(key==='e'){event.preventDefault();toggleLarge();return;}
    if(key===' '&&event.target.closest?.('button,a,summary,[data-zone]'))return;
    if(commands[key]){event.preventDefault();command('/api/control',{cmd:commands[key]});}
    const visibleDecision=detailClosed?null:selected&&!items().find(i=>i.id===selected)?.forecast?A(S.approvals).find(a=>a.incident===selected):!selected?A(S.approvals)[0]:null;
    if((key==='a'||key==='v')&&visibleDecision){event.preventDefault();decide(visibleDecision.id,key==='a');}
  });
  function setFlow(value){flow=value;$('flows').setAttribute('aria-pressed',String(flow));$('general').setAttribute('aria-pressed',String(!flow));$('map').classList.toggle('show-flows',flow);renderMap();}
  $('flows').onclick=()=>setFlow(true);$('general').onclick=()=>setFlow(false);
  $('clear-zone').onclick=()=>{zoneFilter=null;renderList();renderMap();text('map-note','Selecciona una zona para filtrar sus avisos.');};
  function closeDetail(){selected=null;detailClosed=true;renderList();renderDetail();renderMap();announceSelection();$('incidents').focus({preventScroll:true});}
  $('close-detail').onclick=closeDetail;
  $('notifications').onclick=()=>{const urgent=A(S.approvals).find(a=>items().some(i=>i.id===a.incident)), first=items().find(i=>!i.forecast&&i.rank>=8);zoneFilter=null;filter='all';document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.filter==='all')));selectItem(urgent?.incident||first?.id||items()[0]?.id||null,true);};
  function toggleLarge(){const value=document.body.classList.toggle('large');$('large').setAttribute('aria-pressed',String(value));text('large',value?'Tamaño normal · E':'Pantalla grande · E');}
  $('large').onclick=toggleLarge;
  if(new URLSearchParams(location.search).get('escena')==='1')toggleLarge();
  function chime(){try{if(!audioContext)return;const tone=audioContext.createOscillator(),gain=audioContext.createGain();tone.connect(gain);gain.connect(audioContext.destination);tone.frequency.value=660;gain.gain.setValueAtTime(.035,audioContext.currentTime);gain.gain.exponentialRampToValueAtTime(.001,audioContext.currentTime+.2);tone.start();tone.stop(audioContext.currentTime+.2);}catch{}}
  $('sound').onclick=async()=>{try{if(!sound){const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)throw new Error('Sonido no disponible en este navegador.');audioContext=audioContext||new Audio();await audioContext.resume();}sound=!sound;$('sound').setAttribute('aria-pressed',String(sound));text('sound',sound?'Sonido activado':'Sonido apagado');}catch(e){notice(e.message);}};
  function renderResources(){html($('resources-list'),A(S.resources).map(r=>`<article class="resource-row"><h3>${E(r.name||'Equipo')}</h3><p>${E(({available:'✓ Disponible',en_route:'◷ De camino',busy:'! Atendiendo un incidente',offline:'✕ No disponible'})[r.status]||'Estado sin confirmar')}${r.status==='en_route'&&r.eta!=null?' · llega en '+N(r.eta,0)+' min':''}</p>${r.zone?'<p>'+E(zone(r.zone))+'</p>':''}</article>`).join('')||'<p>No se han recibido datos de los equipos.</p>');}
  try{$('first-visit').hidden=localStorage.getItem('mando-centro-tips')==='seen';}catch{$('first-visit').hidden=false;}
  $('dismiss-tips').onclick=()=>{$('first-visit').hidden=true;try{localStorage.setItem('mando-centro-tips','seen');}catch{}};
  function theme(dark){document.documentElement.dataset.theme=dark?'dark':'light';$('theme').setAttribute('aria-pressed',String(dark));text('theme',dark?'Modo claro':'Modo oscuro');$('theme').setAttribute('aria-label',dark?'Activar modo claro':'Activar modo oscuro');}
  try{theme(localStorage.getItem('mando-centro-theme')==='dark');}catch{theme(false);}
  $('theme').onclick=()=>{const dark=document.documentElement.dataset.theme!=='dark';theme(dark);try{localStorage.setItem('mando-centro-theme',dark?'dark':'light');}catch{}};
  async function loadInitial(){
    try{const [f,s]=await Promise.all([U.api('/api/festival'),U.api('/api/state')]);festival=f;planMap=window.PLANO.build($('map'),f,{selectable:true});connected=true;render(S.session?.id?S:s);}
    catch(e){connected=false;$('reconnecting').hidden=false;text('connection','↻ Reconectando…');notice('No se pudo cargar el recinto. Reintentamos automáticamente.');setTimeout(loadInitial,5000);}
  }
  loadInitial();
  const stream=new EventSource('/api/stream');
  stream.addEventListener('state',event=>{try{connected=true;render(JSON.parse(event.data));}catch{text('feedback','No se pudo interpretar la actualización; esperando la siguiente.');}});
  stream.onerror=()=>{connected=false;$('reconnecting').hidden=false;text('connection','↻ Reconectando…');renderServices();};
})();
