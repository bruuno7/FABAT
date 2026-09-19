/* Detalle y ensayo del centro de control. El estado llega del render de app.js. */
(function () {
  'use strict';
  const U=MANDO_UI, $=id=>document.getElementById(id), E=U.esc;
  let S=null, selection=null, returnFocus=null, tested=null, request=0, sound=false, audio=null, lastIds=null, session=null;
  const decisionTests=new Map(), reportDetails=new Map();
  const markup=new WeakMap();
  const setHTML=(el,html)=>{if(el && markup.get(el)!==html) {el.innerHTML=html;markup.set(el,html);}};
  function related() {
    if(!S||!selection) return {incidents:[],reports:[],plans:[],resources:[],calls:[]};
    const incident=selection.incident || S.reports.find(r=>r.id===selection.report)?.incident;
    const zone=selection.zone || S.incidents.find(i=>i.id===incident)?.zone;
    const incidents=S.incidents.filter(i=>incident ? i.id===incident : zone && i.zone===zone);
    const ids=new Set(incidents.map(i=>i.id));
    const reports=S.reports.filter(r=>r.id===selection.report || ids.has(r.incident) || (!incident && zone && r.zone_hint===zone));
    const plans=S.plans.filter(p=>ids.has(p.incident));
    const resourceIds=new Set(S.actions.filter(a=>ids.has(a.incident)).map(a=>a.resource));
    plans.forEach(p=>(p.steps||[]).forEach(a=>resourceIds.add(a.resource)));
    return {zone,incidents,reports,plans,resources:S.resources.filter(r=>resourceIds.has(r.id)||(!incident&&r.zone===zone)),calls:(S.calls?.calls||[]).filter(c=>ids.has(c.incident))};
  }
  function highlight() {
    const r=related(), ids=new Set(r.incidents.map(i=>i.id)), reps=new Set(r.reports.map(i=>i.id)), teams=new Set(r.resources.map(i=>i.id));
    document.querySelectorAll('[data-incident],[data-report],[data-zone],[data-resource],[data-plan]').forEach(el=>{
      const d=el.dataset, on=!!selection && ((d.zone && d.zone===r.zone)||(d.incident&&ids.has(d.incident))||(d.report&&reps.has(d.report))||(d.resource&&teams.has(d.resource))||(d.plan&&r.plans.some(p=>p.id===d.plan)));
      el.classList.toggle('linked',on);
      if(el.getAttribute('role')==='button') el.setAttribute('aria-pressed',String(on));
    });
  }
  function choose(data, trigger) {
    selection=data; returnFocus=trigger || document.activeElement; tested=null; request++;
    $('detail-panel').hidden=false; $('detail-title').textContent='Detalle del aviso';
    const r=related(); window.dispatchEvent(new CustomEvent("mando:selection",{detail:r.incidents[0]?.id || null})); setupWhatif(r.zone); detail(); highlight(); $('detail-close').focus({preventScroll:true});
  }
  function close() { $('detail-panel').hidden=true; selection=null; request++; window.dispatchEvent(new CustomEvent('mando:selection',{detail:null})); highlight(); if(returnFocus?.isConnected) returnFocus.focus({preventScroll:true}); }
  function slotValue(value) {
    if(value===true)return 'Sí';if(value===false)return 'No';if(value==null)return 'Pendiente';
    if(typeof value!=='object')return String(value);
    if(Array.isArray(value))return value.map(slotValue).join(', ');
    if('zone' in value || 'point' in value)return [S.zones.find(z=>z.id===value.zone)?.name || value.zone,value.point].filter(Boolean).join(' · ') || 'Pendiente';
    return Object.values(value).map(slotValue).join(' · ');
  }
  function slotsHTML(chat) {
    const raw=chat?.state?.slots;
    const slots=Array.isArray(raw)?raw:raw&&typeof raw==='object'?Object.entries(raw).map(([id,v])=>typeof v==='object'&&v!==null?{id,...v}:{id,label:id,value:v}):[];
    return slots.length ? `<div class="detail-slots">${slots.map(s=>`<div data-slot="${E(s.id||s.label)}" class="detail-slot ${s.value!=null?'filled':''}"><span>${E(s.label||s.id)}</span><b>${E(slotValue(s.value))}</b>${s.confidence!=null?`<small>Confianza: ${E(s.confidence)}</small>`:''}</div>`).join('')}</div>` : '<p class="data-note">La conversación aún no ha enviado fichas de datos.</p>';
  }
  function instructionHTML(value) {
    if(!value) return '<p class="data-note">No se ha recibido ninguna instrucción.</p>';
    if(typeof value==='string') return `<p>${E(value)}</p>`;
    return `<b>${E(value.title||'Instrucción enviada')}</b><ol>${(value.steps||[]).map(s=>`<li>${E(typeof s==='string'?s:s.text||'')}</li>`).join('')}</ol>`;
  }
  function detail() {
    if(!selection||!S) return;
    const r=related();
    r.reports.forEach(rep=>{
      const key=S.session.id+':'+rep.id;
      if(!rep.chat?.instruction && !reportDetails.has(key)) {
        reportDetails.set(key,null);
        U.api('/api/report/'+encodeURIComponent(rep.id)).then(d=>reportDetails.set(key,d)).catch(()=>reportDetails.set(key,{})).finally(()=>{if(selection){detail();highlight();}});
      }
    });
    const zone=S.zones.find(z=>z.id===r.zone), inc=r.incidents[0];
    $('detail-title').textContent=inc?.label || zone?.name || 'Detalle del aviso';
    const priority=r.incidents.map(i=>`<article><h3>Prioridad ${U.num(i.priority)} de 10 · ${E(i.zone_name||'Ubicación pendiente')}</h3><p>${E(i.explain||'Todavía no hay explicación de prioridad.')}</p></article>`).join('') || '<p>Selecciona un aviso o una zona con incidentes para ver su prioridad.</p>';
    const plans=r.plans.slice(-4).reverse().map(p=>`<article class="detail-plan ${p.invalidated_by?'obsolete':''}" data-plan="${E(p.id)}"><h3>${E(p.objective)}</h3><p>${E(p.why||'')}</p><p class="data-note">${E(p.id)} · minuto ${E(p.t)}</p><ol>${(p.steps||[]).map(a=>`<li>${E(a.why||a.reason||a.kind)} · ${E(a.status||'')}</li>`).join('')}</ol><h4>De qué depende</h4><ul>${(p.assumptions||[]).map(a=>`<li class="${a.holds===false?'bad':''}">${a.holds===false?'Ya no se cumple: ':''}${E(a.text)}</li>`).join('')}</ul><p class="rehearsal">${p.rehearsal?.length?'Ensayo: '+p.rehearsal.map(x=>E(x.label)+(x.value!=null?' · '+E(x.value)+' '+E(x.unit||''):'')+(x.chosen?' · elegida':'')).join(' / '):'No se ha recibido la línea del ensayo.'}</p></article>`).join('');
    const reps=r.reports.map(rep=>`<article data-report="${E(rep.id)}"><h3>${U.channel(rep.via||rep.channel)} ${E(U.labels[rep.via||rep.channel]||'Aviso')} · ${E(rep.source||'')}</h3><p>${E(rep.text)}</p>${slotsHTML(rep.chat)}<h4>Qué se le dijo a la persona</h4>${instructionHTML(rep.chat?.instruction || rep.instruction || reportDetails.get(S.session.id+':'+rep.id)?.safety)}</article>`).join('');
    const calls=r.calls.map(c=>`<article><h3>${E(c.title||c.to||'Equipo')} · ${E(({accept:'Acepta',reject:'Rechaza',no_answer:'No contesta'})[c.result]||c.stage||'Llamando')}</h3><p>${E(c.text||'')}</p>${(c.transcript||[]).map(l=>`<p><b>${E(l.who)}:</b> ${E(l.text)}</p>`).join('')}${c.signal?`<p>Cambio de orden: ${E(c.signal.text)}</p>`:''}</article>`).join('');
    const before=new Map(Array.from($('detail-body').querySelectorAll('[data-report] [data-slot]')).map(el=>[el.closest('[data-report]').dataset.report+':'+el.dataset.slot,el.textContent]));
    setHTML($('detail-body'),`${zone?`<p class="detail-density">${E(zone.name)} · <b>${U.num(zone.density)} personas/m²</b></p>`:''}${priority}<h2>Plan y ensayo</h2>${plans||'<p class="data-note">Todavía no hay plan para esta selección.</p>'}<h2>Llamadas</h2>${calls||'<p class="data-note">Sin llamadas asociadas todavía.</p>'}<h2>Conversación y datos</h2>${reps||'<p class="data-note">Sin avisos asociados todavía.</p>'}`);
    if(!matchMedia('(prefers-reduced-motion: reduce)').matches) $('detail-body').querySelectorAll('[data-report] [data-slot].filled').forEach(el=>{const key=el.closest('[data-report]').dataset.report+':'+el.dataset.slot;if(before.has(key)&&before.get(key)!==el.textContent)el.animate([{background:'#194450'},{background:'transparent'}],{duration:1100});});
    if(tested && tested.session!==S.session.id) invalidate();
    if(tested && tested.t!==S.t) {$('whatif-order').disabled=true;$('whatif-status').textContent=`El reloj ha avanzado desde el minuto ${tested.t}. Vuelve a ensayar antes de ordenar.`;}
  }
  function invalidate(){tested=null;request++;$('whatif-run').disabled=false;$('whatif-order').disabled=true;setHTML($('whatif-chart'),'');$('whatif-status').textContent='Ensaya primero. El recinto no cambia hasta que ordenas la alternativa.';}
  function setupWhatif(zone) {
    $('whatif-form').hidden=!zone; if(!zone) return;
    $('whatif-zone').value=zone;
    $('whatif-to').innerHTML=S.zones.filter(z=>z.id!==zone).map(z=>`<option value="${E(z.id)}">${E(z.name||z.id)}</option>`).join('');
    $('whatif-origin').textContent=S.zones.find(z=>z.id===zone)?.name||zone;
    invalidate(); toggleControls();
  }
  function toggleControls(){const kind=$('whatif-kind').value;$('reroute-controls').hidden=kind!=='reroute';$('zone-controls').hidden=kind!=='set_zone';}
  function action(){return {kind:$('whatif-kind').value,zone:$('whatif-zone').value,to:$('whatif-to').value,fraction:Number($('whatif-fraction').value)/100,state:$('whatif-state').value,minutes:15};}
  $('whatif-form').addEventListener('input',()=>{invalidate();toggleControls();$('fraction-value').textContent=$('whatif-fraction').value+' %';});
  $('whatif-form').addEventListener('submit',async ev=>{
    ev.preventDefault(); const seq=++request, a=action(), sid=S.session.id;
    $('whatif-run').disabled=true; $('whatif-order').disabled=true; $('whatif-status').textContent='Ensayando los próximos 15 minutos…';
    try { if(S.session.running) {await U.api('/api/control',{cmd:'pause'}); if(seq!==request)return;} const result=await U.api('/api/whatif',a); if(seq!==request||sid!==S.session.id) return;
      tested={...result,session:sid,input:a};
      const zones=Object.keys(result.zones||result.mando?.series||{});
      $('whatif-view-zone').innerHTML=zones.map(z=>`<option value="${E(z)}">${E(result.zones?.[z]||z)}</option>`).join('');
      if(zones.includes(a.zone)) $('whatif-view-zone').value=a.zone;
      drawTrial(); $('whatif-order').disabled=result.t!==S.t;
      $('whatif-status').textContent=`Tu alternativa: ${result.verdict||'sin valoración'}. Ensayo del minuto ${result.t}, reloj en pausa para comparar. ${result.note||''}`;
    }catch(e){if(seq===request)$('whatif-status').textContent=e.message;}finally{$('whatif-run').disabled=false;}
  });
  function drawTrial(){if(tested)setHTML($('whatif-chart'),U.comparison(tested,$('whatif-view-zone').value)+ '<p class="data-note">La línea de Mando mantiene las órdenes actuales; el ensayo no calcula sus decisiones futuras.</p>');}
  $('whatif-view-zone').onchange=drawTrial;
  $('whatif-order').onclick=async()=>{
    if(!tested||tested.t!==S.t) return; const current=tested; $('whatif-order').disabled=true;
    try {const j=await U.api('/api/whatif/order',{action:current.action,by:'centro de control',note:`Alternativa ensayada en el minuto ${current.t}`}); $('whatif-status').textContent=`Orden enviada: ${j.order?.text||j.order?.id||'registrada'}.`;tested=null;}
    catch(e){$('whatif-status').textContent=e.message;$('whatif-order').disabled=!tested||tested.t!==S.t;}
  };
  $('detail-close').onclick=close;
  document.addEventListener('click',ev=>{const el=ev.target.closest('[data-select]');if(!el)return;choose({incident:el.dataset.incident,report:el.dataset.report,zone:el.dataset.zone},el);});
  document.addEventListener('keydown',ev=>{
    if(ev.key==='Escape'&&!$('detail-panel').hidden){ev.preventDefault();close();}
    const el=ev.target.closest('[data-select]');if(el&&(ev.key==='Enter'||ev.key===' ')){ev.preventDefault();ev.stopImmediatePropagation();el.click();}
    if(ev.key.toLowerCase()==='m'&&!ev.ctrlKey&&!ev.metaKey&&!ev.altKey&&!/INPUT|TEXTAREA|SELECT/.test(ev.target.tagName)){ev.preventDefault();toggleSound();}
  },true);
  function toggleSound(){sound=!sound;$('btn-sound').setAttribute('aria-pressed',String(sound));$('btn-sound').textContent=`Sonido ${sound?'sí':'no'} · M`;if(sound){try{audio=audio||new (window.AudioContext||window.webkitAudioContext)();audio.resume().then(chime).catch(()=>{});}catch(e){sound=false;$('btn-sound').textContent='Sonido no disponible';$('btn-sound').setAttribute('aria-pressed','false');}}}
  function chime(){if(!sound||!audio||audio.state!=='running')return;const o=audio.createOscillator(),g=audio.createGain();o.frequency.value=640;g.gain.setValueAtTime(.035,audio.currentTime);g.gain.exponentialRampToValueAtTime(.001,audio.currentTime+.13);o.connect(g);g.connect(audio.destination);o.start();o.stop(audio.currentTime+.14);}
  $('btn-sound').onclick=toggleSound;
  function funnel(){
    const f=S.funnel;
    setHTML($('funnel'),f?`<strong>${U.num(f.reports,0)} avisos → ${U.num(f.incidents,0)} incidentes → ${U.num(f.actions,0)} acciones</strong><div class="channels">${['voice','sms','telegram','email','web','sensor'].map(ch=>`<span>${U.channel(ch)}${U.labels[ch]} <b>${U.num(!f.by_channel?null:ch==='web'?(f.by_channel.web||0)+(f.by_channel.chat||0):f.by_channel[ch]||0,0)}</b></span>`).join('')}${Object.entries(f.by_channel||{}).filter(([ch])=>!['voice','sms','telegram','email','web','chat','sensor'].includes(ch)).map(([ch,n])=>`<span>${U.channel(ch)}${E(U.labels[ch]||ch)} <b>${U.num(n,0)}</b></span>`).join('')}</div>`:'<span>Embudo de avisos pendiente del servidor</span>');
    const tg={off:'sin configurar',starting:'conectando',on:'conectado',error:'error de conexión'};
    $('integrations').textContent=`Telegram: ${tg[S.telegram_bot?.status]||'sin datos'} · HappyRobot: ${S.calls?.mode==='happyrobot'?`modo híbrido · ${S.calls.real_sent??0} llamadas reales · ${S.calls.fallbacks??0} pasadas a simulación`:'llamadas simuladas'} · Recogida de avisos: ${S.intake?.delegated?'HappyRobot':'local'}`;
  }
  function decisions(){
    const a=S.approvals[0], box=$('decision-graph');if(!a||!box)return;
    const supplied=a.card?.series;
    if(supplied?.mando&&supplied?.alternative){setHTML(box,Object.keys(supplied.mando.series||{}).map(z=>U.comparison(supplied,z,['Si vetas','Si apruebas'])).join(''));return;}
    const key=S.session.id+':'+a.id;
    if(decisionTests.has(key)) {const d=decisionTests.get(key);setHTML(box,d?.error?`<p class="data-note">${E(d.error)}</p>`:d?Object.keys(d.zones||{}).slice(0,2).map(z=>U.comparison(d,z,['Si vetas · mantener órdenes','Si apruebas'])).join('')+`<p class="data-note">Ensayo al minuto ${d.t}; mantiene las demás órdenes actuales.</p>`:'<p>Calculando los dos futuros…</p>');return;}
    const full=S.actions.find(x=>x.id===a.id);
    if(!full||!['reroute','set_zone','stop_show'].includes(full.kind)){setHTML(box,'<p class="data-note">Las curvas de esta decisión no llegan del servidor. Arriba se muestran sus consecuencias disponibles.</p>');return;}
    decisionTests.set(key,null);
    U.api('/api/whatif',{...full.params,kind:full.kind,zone:full.zone,minutes:15}).then(d=>decisionTests.set(key,d)).catch(e=>decisionTests.set(key,{error:e.message})).finally(()=>{if(S.approvals[0]?.id===a.id)decisions();});
  }
  window.addEventListener('mando:state',ev=>{
    S=ev.detail;
    if(session!==S.session.id){session=S.session.id;lastIds=null;decisionTests.clear();reportDetails.clear();if(selection)close();}
    const ids=new Set(S.reports.map(r=>r.id));if(lastIds&&[...ids].some(id=>!lastIds.has(id)))chime();lastIds=ids;
    funnel(); detail(); highlight(); decisions();
  });
})();
