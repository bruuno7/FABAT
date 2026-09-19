(function () {
  'use strict';
  const U=MANDO_UI,$=id=>document.getElementById(id),E=U.esc;
  let current='',busy=false;
  function audience(text) {
    const labels={minutes_mean:'media en minutos',minutes_p80:'percentil 80 en minutos',dry_before_refill:'veces sin agua antes de reponer',consumption_l_per_min:'consumo en litros por minuto',search_min_mean:'búsqueda media en minutos',search_min_p80:'percentil 80 de búsqueda',sent:'llamadas realizadas',accepted:'llamadas aceptadas',smoothed_rate:'tasa estimada de respuesta',pooled_rate:'tasa conjunta de respuesta',medical:'equipo médico',security:'seguridad',ASK:'pregunta',weather_standdown_min:'minutos en calma'};
    return String(text??'').replace(/\b(minutes_mean|minutes_p80|dry_before_refill|consumption_l_per_min|search_min_mean|search_min_p80|sent|accepted|smoothed_rate|pooled_rate|medical|security|ASK|weather_standdown_min)\b/g,k=>labels[k]).replace(/supuestos?/gi,'datos de los que dependía el plan').replace(/frentes/gi,'incidentes').replace(/golpes?/gi,'imprevistos').replace(/replanificar/gi,'cambiar el plan');
  }
  const val=v=>v==null?'Sin dato':typeof v==='boolean'?(v?'Sí':'No'):typeof v==='object'?(v.order?'Orden: '+v.order.join(' → '):JSON.stringify(v)):U.num(v) !== '—'?U.num(v):String(v);
  function interval(row) {
    const ci=row.ci || row.ci95 || row.ci99;
    if(!Array.isArray(ci)||ci.length!==2||!ci.every(v=>typeof v==='number'&&Number.isFinite(v)))return '<span class="data-note">Intervalo no recibido</span>';
    const delta=row.delta ?? (typeof row.before==='number'&&typeof row.after==='number'?row.after-row.before:null);
    const extent=Math.max(.001,Math.abs(ci[0]),Math.abs(ci[1]),Math.abs(delta||0))*1.18;
    const x=v=>140+v/extent*110;
    return `<svg class="interval" viewBox="0 0 280 65" role="img" aria-label="Diferencia: ${E(val(delta))}. Intervalo: ${E(val(ci[0]))} a ${E(val(ci[1]))}"><line x1="30" x2="250" y1="28" y2="28" class="gridline"/><line x1="140" x2="140" y1="8" y2="43" class="threshold"/><line x1="${x(ci[0])}" x2="${x(ci[1])}" y1="28" y2="28" class="ci-line"/><path d="M${x(ci[0])} 20v16M${x(ci[1])} 20v16" class="ci-line"/>${delta!=null?`<circle cx="${x(delta)}" cy="28" r="4" fill="var(--amber)"/>`:''}<text x="${x(ci[0])}" y="57" text-anchor="middle">${E(val(ci[0]))}</text><text x="140" y="12" text-anchor="middle">0</text><text x="${x(ci[1])}" y="57" text-anchor="middle">${E(val(ci[1]))}</text></svg>`;
  }
  async function load() {
    if(busy)return;
    try {
      const d=await U.api('/api/memoria');
      const serialized=JSON.stringify(d); if(serialized===current)return; current=serialized;
      const focused=document.activeElement?.dataset,focusId=focused?.id,focusChoice=focused?.approve;
      const cmp=d.comparison;
      $('take').textContent=cmp?.verdict || (d.available?'Hay observaciones. Aún no hay comparación que permita afirmar una mejora.':'Todavía no hay observaciones del día 1.');
      if(cmp?.n!=null)$('take').append(` · N = ${cmp.n}`);
      let obs=Array.isArray(d.observations)?d.observations:[];
      // El backend antiguo solo publica la evidencia dentro de las propuestas: se identifica esa procedencia.
      if(!obs.length)obs=(d.proposals||[]).filter(p=>p.text||p.title).map(p=>({text:(p.text||p.title).split(/;?\s*propongo/i)[0],n:p.n,derived:true}));
      $('obs').innerHTML=obs.map(o=>`<li>${E(audience(o.text||o.observation||'Observación sin descripción'))} <small>N = ${E(o.n??o.evidence_n??'no indicado')}${o.derived?' · evidencia de la propuesta':''}</small></li>`).join('') || '<li>El servidor no entrega observaciones del día 1 todavía.</li>';
      $('src').textContent=d.proposals_source?'Fuente: '+d.proposals_source:'';
      $('props').innerHTML=(d.proposals||[]).map(p=>{
        const dec=p.decision,yes=dec?.status==='approved';
        const evidence=typeof p.evidence==='object'?Object.entries(p.evidence).map(([k,v])=>`${k}: ${val(v)}`).join(' · '):p.evidence;
        return `<article class="card ${dec?(yes?'ok':'no'):''}"><h3>${E(audience(p.title||p.text||p.param||p.id))}</h3><p>${E(val(p.from??p.old))} → ${E(val(p.value??p.new))}</p><p class="ev">Evidencia: ${E(audience(evidence||'No descrita'))} · N = ${E(p.n??p.evidence_n??'no indicado')}</p>${p.limited?'<p>Evidencia limitada: hacen falta más observaciones.</p>':''}${dec?`<p class="stamp ${yes?'ok':'no'}">${yes?'Aprobada':'Rechazada'} · ${E(dec.by||'persona responsable')}</p>`:''}<div class="row"><button data-id="${E(p.id)}" data-approve="true" ${yes?'disabled':''}>Aprobar</button><button class="veto" data-id="${E(p.id)}" data-approve="false" ${dec&&!yes?'disabled':''}>Rechazar</button></div></article>`;
      }).join('')||'<p>Sin propuestas pendientes.</p>';
      const rows=cmp?.rows||[];
      $('cmp').innerHTML=rows.map(r=>`<tr><th scope="row">${E(r.name||r.metric)}${r.split?`<small> · ${E(r.split)}</small>`:''}</th><td>${E(val(r.before))}</td><td>${E(val(r.after))}</td><td>${E(val(r.delta))}</td><td>${interval(r)}<small>${r.confidence!=null?`Confianza ${E(r.confidence>1?r.confidence:r.confidence*100)} %`:'Nivel de confianza no indicado'}</small></td><td>${E(r.n??cmp.n??'No indicado')}</td><td>${E(r.verdict||(r.significant===false?'Sin evidencia de mejora':r.significant===true?'Diferencia con evidencia':'Sin valoración'))}</td></tr>`).join('')||'<tr><td colspan="7">El servidor aún no entrega cifras antes/después ni intervalos. No se puede afirmar una mejora.</td></tr>';
      $('cmp-note').textContent='Simulación. '+(cmp?.fingerprint?'Huella del código medido: '+cmp.fingerprint+'. ':'')+'La línea marca el intervalo de la diferencia; el punto, la diferencia media. Si incluye cero, no demuestra una mejora.';
      $('ops').innerHTML=(d.operator_lessons||[]).map(o=>`<li>Min ${E(o.t)} · ${E(o.text)} ${o.note?`— ${E(o.note)}`:''}<small>Por ${E(o.by||'operador')}</small></li>`).join('')||'<li>Ninguna corrección todavía.</li>';
      if(focusId)Array.from($('props').querySelectorAll('button')).find(b=>b.dataset.id===focusId&&b.dataset.approve===focusChoice)?.focus({preventScroll:true});
    } catch(e){$('memory-status').textContent='No se pudo actualizar: '+e.message;}
  }
  $('props').onclick=async ev=>{
    const b=ev.target.closest('button[data-id]');if(!b||busy)return;
    busy=true;$('props').querySelectorAll('button').forEach(x=>x.disabled=true);
    try{const d=await U.api('/api/memoria/decide',{id:b.dataset.id,approve:b.dataset.approve==='true',by:'centro de control'});$('memory-status').textContent=d.applied_to_mando===false?'Decisión guardada. El servidor aún no la aplica a la configuración de Mando.':'Decisión registrada.';current='';}
    catch(e){$('memory-status').textContent=e.message;current='';}
    finally{busy=false;await load();}
  };
  load();setInterval(load,5000);
})();
