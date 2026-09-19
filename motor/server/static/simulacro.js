/* Simulacro aislado: datos del servidor, sin cifras decorativas ni HTML de entradas externas. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), {api,esc:E,num:N}=window.MANDO_UI;
  let map=null, festival=null, running=false, polling=false, lastJob=null;
  const locked=new Map();
  const say=text=>{$('feedback').textContent=text;};
  const stateLabels={idle:'Listo para atacar el plan',running:'Caos está atacando el plan',completed:'Simulacro terminado',cancelled:'Cancelado · resultados parciales',limited:'Presupuesto agotado · resultados parciales',error:'No se pudo terminar el simulacro'};
  function render(s){
    const job=`${s.session_id}:${s.t}:${s.seed}:${s.requested_N}`;if(job!==lastJob){locked.clear();lastJob=job;}
    running=s.status==='running';
    $('start').disabled=running;$('cancel').disabled=!running;
    $('progress').max=s.requested_N||Number($('sample').value);$('progress').value=s.N||0;
    $('progress-title').textContent=stateLabels[s.status]||s.status;
    $('progress-count').textContent=`N = ${s.N||0} / ${s.requested_N||0} · ${s.failures||0} roturas · ${s.errors||0} errores`;
    $('map-caption').textContent=`Estado del minuto ${s.t??'—'} · frecuencia sobre N = ${s.N||0} ataques`;
    if(s.note)$('method').textContent=s.note;
    if(s.status!=='idle')say(`${s.case||''} · semilla ${s.seed} · ${s.elapsed_s==null?'Calculando':N(s.elapsed_s,1)+' s reales'} · ${s.cpu_s==null?'':N(s.cpu_s,1)+' s CPU'}${s.status==='limited'?' · N parcial: no se completó lo solicitado.':''}${s.error?' · Error: '+s.error:''}`);
    if(map)for(const [id,z] of Object.entries(map.zones)){
      const count=s.zones?.[id]||0,pct=s.N?count/s.N:0;
      z.rect.style.fill=count?`hsl(${Math.max(8,48-pct*150)} 72% ${Math.max(68,94-pct*70)}%)`:'#edf0eb';
      z.dens.textContent=s.N?`${N(pct*100,1)} %`:'—';z.pct.textContent=`${count} / ${s.N||0}`;
      z.state.textContent='roturas';
      z.g.setAttribute('aria-label',`${id}: ${count} roturas sobre N = ${s.N||0}`);
    }
    $('resources').innerHTML=(festival?.resources||[]).map(r=>{const count=s.resources?.[r.id]||0;return `<div class="resource-heat"><strong>${E(r.name||r.id)}</strong>${N(s.N?100*count/s.N:0)} % · ${count}/${s.N||0}</div>`;}).join('');
    $('weaknesses').innerHTML=(s.weaknesses||[]).map((w,i)=>`<article class="weakness"><div class="frequency">${N(w.percent)} % <small>· ${w.failures}/${w.N}</small></div><h3>${i+1}. ${E(w.label)}</h3><p>N = ${w.N} ataques totales; este golpe se probó ${w.exposed_N} veces.</p><div class="plan-b"><strong>Plan B de Mando</strong><p>${w.plans.length?w.plans.map(E).join(' · '):'Sin plan sustituto observado en 15 min.'}</p><p>${w.recovery_median_min==null?'Recuperación no observada':`Mediana ${N(w.recovery_median_min)} min hasta ejecutar el plan B · N = ${w.recovery_N}`}. Sin recuperación medible: ${w.censored_N}/${w.failures}.</p></div><button data-lock="${w.example}" ${locked.has(w.example)?'disabled':''}>${locked.has(w.example)?'Bloqueado':'Bloquear como test de regresión'}</button><p class="lock-result" role="status">${E(locked.get(w.example)||'')}</p></article>`).join('')||`<p class="empty">${s.N?'No se han medido roturas adicionales en los ataques terminados. No demuestra que el plan sea seguro.':'Inicia el simulacro para ver los puntos débiles.'}</p>`;
  }
  async function poll(){if(polling)return;polling=true;try{render(await api('/api/simulacro/status'));}catch(e){say(e.message);}finally{polling=false;}}
  $('sample').addEventListener('change',()=>{$('start').textContent=`Atacar el plan ${$('sample').value} veces`;});
  $('drill-form').addEventListener('submit',async e=>{e.preventDefault();$('start').disabled=true;try{render(await api('/api/simulacro/start',{n:Number($('sample').value),seed:Number($('seed').value)}));}catch(error){say(error.message);$('start').disabled=false;}});
  $('cancel').addEventListener('click',async()=>{try{await api('/api/simulacro/cancel',{});say('Cancelación solicitada; terminando el paso actual.');}catch(e){say(e.message);}});
  $('weaknesses').addEventListener('click',async event=>{const button=event.target.closest('[data-lock]');if(!button)return;button.disabled=true;try{const r=await api('/api/regression/lock',{simulacro_index:Number(button.dataset.lock),author:'operador',note:'Mapa de fragilidad'});const message=`Prueba permanente nº ${r.n}. Disponible en el panel de regresión.`;locked.set(Number(button.dataset.lock),message);button.nextElementSibling.textContent=message;button.textContent='Bloqueado';}catch(e){button.disabled=false;button.nextElementSibling.textContent=e.message;}});
  api('/api/festival').then(f=>{festival=f;map=window.PLANO.build($('fragility-map'),f);poll();}).catch(e=>say(e.message));
  setInterval(()=>{if(!document.hidden)poll();},1200);
})();
