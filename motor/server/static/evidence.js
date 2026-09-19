/* Recibos y cuenta de coordinación compartidos por centro e informe. */
(() => {
  'use strict';
  const E=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const N=v=>Number(v||0).toLocaleString('es-ES',{maximumFractionDigits:1});
  let data=null,busy=false;
  const rendered=new WeakMap();
  function setHTML(host,text){if(rendered.get(host)!==text||!host.children.length){rendered.set(host,text);host.innerHTML=text;}}
  const assumptions={call_minutes:3,message_minutes:1,report_minutes:1};
  const titles={mejor:'Lo que evitó',peor:'La decisión empeoró el resultado',mixto:'Efectos mixtos',sin_cambio:'No cambió nada medible',sin_seguimiento:'Sin seguimiento',error:'Recibo no disponible'};
  function receipt(r){return `<article class="receipt ${E(r.verdict)}"><p class="evidence-meta">${r.human?(r.accepted?'Aprobación humana':'Veto humano'):'Decisión de Mando'} · ${E(r.id)} · minuto ${N(r.t)} · N = ${r.N||1} par</p><h3>${r.accepted===false&&r.benefit>0?(r.verdict==='mixto'?'El veto mejoró el balance, con efectos mixtos':'El veto humano mejoró el resultado'):E(titles[r.verdict]||'Recibo')}</h3><p>${E(r.text)}</p><small>${r.factual_source==='observado_en_simulador'?'Comparado con lo observado en el simulador':'Dos ramas simuladas'} · ${N(r.minutes)} min${r.censored?' · seguimiento incompleto':''}.</small><details><summary>Condiciones de esta comparación</summary><p>${E(r.note||'Sin estimación disponible.')}</p></details></article>`;}
  function paintReceipts(){
    if(!data)return;
    const receipts=data.recibos||{},items=receipts.items||[];
    for(const host of document.querySelectorAll('[data-receipt-incident]')){
      const rows=items.filter(r=>r.incident===host.dataset.receiptIncident);
      const text='<h2>Recibo</h2>'+ (rows.map(receipt).join('')||`<p class="evidence-meta">${receipts.pending?'En seguimiento o calculando en segundo plano.':'Sin decisión medida para este incidente.'} Simulación · N = ${rows.length} decisiones.</p>`);
      setHTML(host,text);
    }
    const host=document.getElementById('evidence-receipts');
    if(host){
      const useful=items.filter(r=>r.verdict!=='sin_cambio'),none=items.filter(r=>r.verdict==='sin_cambio');
      const text=`<h2>Lo que evitó cada decisión</h2><p class="evidence-meta">Simulación · N = ${items.length} decisiones · ${receipts.pending||0} pendientes · ${receipts.skipped||0} fuera del límite. No sumar los efectos: las decisiones pueden solaparse.</p>${useful.map(receipt).join('')||'<p>Aún no hay efectos medidos.</p>'}<h2>Decisiones que no sirvieron</h2><p class="evidence-meta">Sin cambio medible en este horizonte; no demuestra inutilidad fuera del simulador.</p>${none.map(receipt).join('')||'<p>N = 0 decisiones sin efecto medible.</p>'}`;
      setHTML(host,text);
    }
  }
  function setupCoordination(){
    const host=document.getElementById('evidence-coordination');if(!host||host.children.length)return;
    host.innerHTML=`<div class="coord-title"><h2>La cuenta de coordinación</h2><span>Simulación · N = 1 ejecución</span></div><p class="coord-hero" id="coord-headline">Esperando comunicaciones</p><div class="coord-grid"><p><b id="coord-peak">—</b><span>comunicaciones simultáneas · pico</span></p><p><b id="coord-messages">—</b><span>mensajes salientes</span></p><p><b id="coord-reports">—</b><span>avisos atendidos</span></p><p><b id="coord-total">—</b><span>min humanos en serie · supuesto</span></p></div><fieldset><legend>Supuesto editable, sin verificar</legend><label><input id="coord-call" data-assumption="call_minutes" type="number" min="0" max="60" step="0.5" value="3"> min por llamada humana</label><label><input data-assumption="message_minutes" type="number" min="0" max="60" step="0.5" value="1"> min por mensaje</label><label><input data-assumption="report_minutes" type="number" min="0" max="60" step="0.5" value="1"> min por aviso atendido</label></fieldset><p class="evidence-meta" id="coord-sample"></p><details><summary>Cómo se cuenta</summary><p class="evidence-meta" id="coord-note"></p></details><p role="status" id="coord-error"></p>`;
    host.addEventListener('change',e=>{const key=e.target.dataset.assumption;if(!key)return;if(!e.target.checkValidity()||e.target.value===''){$('coord-error').textContent='Introduce minutos entre 0 y 60.';return;}assumptions[key]=Number(e.target.value);$('coord-error').textContent='';paintCoordination();});
  }
  const $=id=>document.getElementById(id);
  function paintCoordination(){
    setupCoordination();const c=data?.coordinacion;if(!c||!$('coord-headline'))return;
    $('coord-headline').textContent=`${N(c.calls)} llamadas en ${N(c.elapsed_minutes)} min · una persona: ${N(c.calls*assumptions.call_minutes)} min`;
    $('coord-peak').textContent=N(c.peak_simultaneous);$('coord-messages').textContent=N(c.messages);$('coord-reports').textContent=N(c.reports);
    $('coord-total').textContent=N(c.calls*assumptions.call_minutes+c.messages*assumptions.message_minutes+c.reports*assumptions.report_minutes);
    $('coord-sample').textContent=`N = ${c.N} comunicaciones · ${c.real_outbound} salientes reales y ${c.simulated_outbound} simuladas. Pico calculado sobre N = ${c.peak_N} salientes.`;
    $('coord-note').textContent=c.note;
  }
  async function poll(){if(busy||document.hidden)return;busy=true;try{const r=await fetch('/api/evidence');if(!r.ok)throw new Error('No se pudo cargar la evidencia.');data=await r.json();paintCoordination();paintReceipts();}catch(e){const el=$('coord-error');if(el)el.textContent=e.message;}finally{busy=false;}}
  new MutationObserver(()=>paintReceipts()).observe(document.body,{subtree:true,childList:true});
  setupCoordination();poll();setInterval(poll,1500);
})();
