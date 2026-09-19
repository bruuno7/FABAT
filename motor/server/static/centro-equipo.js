/* Coordinación compartida; la pantalla principal conserva sus atajos. */
(() => {
  'use strict';
  const E = x => String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let me=null,state={},selected=null,mine=false,lastSeq=0,scene=null;
  const panel=document.createElement('section');panel.className='team-panel';panel.id='team-panel';
  panel.innerHTML='<div id="team-identity"></div><div id="team-presence"></div><p id="team-notice" role="status" aria-live="polite"></p><details><summary>Enlaces del personal</summary><form id="team-links"><label>Unidad<select name="unit_id"></select></label><label>Cargo<select name="role"></select></label><button>Generar enlace y QR</button></form><div id="team-link-result"></div></details><details><summary>Aviso de 112 / servicios externos</summary><form id="team-external"><label>Servicio<input name="source" required maxlength="60" placeholder="112 / bomberos / transporte"></label><label>Aviso<textarea name="text" required maxlength="400"></textarea></label><button>Registrar aviso externo</button></form></details><label><input type="checkbox" id="team-mine"> Los míos</label><div id="team-incident"></div>';
  document.querySelector('main')?.before(panel);
  const $=id=>document.getElementById(id);
  const notify=text=>{$('team-notice').textContent=text;};
  async function api(path,data){const r=await fetch(path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined});const j=await r.json();if(!r.ok)throw new Error(j.error||j.detail||'No se pudo completar');return j;}
  async function identify(){try{const j=await api('/api/operators/me');me=j.operator;$('team-identity').innerHTML=j.local?`<form id="team-local"><label>Tu nombre<input name="name" value="${E(me.name)}" required maxlength="60"></label><label>Papel<select name="role">${j.roles.map(r=>`<option ${r===me.role?'selected':''}>${E(r)}</option>`).join('')}</select></label><button>Usar identidad</button></form>`:`<strong>${E(me.name)} · ${E(me.role)}</strong>`;const f=$('team-local');if(f)f.onsubmit=async e=>{e.preventDefault();try{await api('/api/operators/local',Object.fromEntries(new FormData(f)));await identify();heartbeat();}catch(x){notify(x.message);}};heartbeat();}catch(e){notify(e.message);}}
  function render(){
    const team=state.operators||{};
    $('team-presence').textContent=(team.presence||[]).map(p=>`${p.operator.name} (${p.operator.role})${p.incident?' · '+p.incident:''}`).join('  /  ')||'Sin otras personas conectadas';
    const i=(state.incidents||[]).find(i=>i.id===selected);
    let content='';
    if(i){const owner=i.owner,own=owner?.id===me?.id;content=`<h3>${E(i.id)} · coordinación</h3><p>Sugerido: ${E(i.suggested_role)} · ${owner?'Lo lleva '+E(owner.name)+' ('+E(owner.role)+')':'Sin responsable'}</p><p>${E(i.sources_text)}</p><button id="team-claim">${own?'Soltar incidente':'Lo llevo yo'}</button><form id="team-note"><label>Nota del incidente<textarea name="text" maxlength="400" required placeholder="@sanitario mira ${E(i.id)}"></textarea></label><button>Añadir nota</button></form><ul>${(team.notes?.[i.id]||[]).map(n=>`<li>${E(n.operator.name)}: ${E(n.verb.replace(/^nota: /,''))}</li>`).join('')}</ul>`;}
    const pending=(team.manual_pending||[]);if(pending.length)content+=`<h3>Correcciones pendientes · 1 de 2</h3>${pending.map((p,n)=>`<p>${E(JSON.stringify(p.action))} <button data-team-manual="${n}">Segunda firma</button></p>`).join('')}`;
    // No reemplazar un formulario mientras alguien escribe.
    if(!$('team-incident').contains(document.activeElement)){
      $('team-incident').innerHTML=content;
      if(i){$('team-claim').onclick=async()=>{try{await api(`/api/incidents/${encodeURIComponent(i.id)}/claim`,{claim:i.owner?.id!==me?.id});}catch(e){notify(e.message);}};
      $('team-note').onsubmit=async e=>{e.preventDefault();try{await api(`/api/incidents/${encodeURIComponent(i.id)}/note`,Object.fromEntries(new FormData(e.target)));e.target.reset();notify('Nota compartida.');}catch(x){notify(x.message);}};}
      document.querySelectorAll('[data-team-manual]').forEach(b=>b.onclick=async()=>{try{const p=pending[Number(b.dataset.teamManual)];const j=await api('/api/whatif/order',{action:p.action,decision_id:p.key});notify(j.pending?'1 de 2 firmas':'Corrección aprobada.');}catch(e){notify(e.message);}});
    }
    for(const event of team.events||[]){if(event.seq>lastSeq){if(lastSeq&&event.operator.id!==me?.id)notify(`${event.operator.name}: ${event.verb}`);lastSeq=event.seq;}}
    window.dispatchEvent(new CustomEvent('mando:team-filter',{detail:{mine,operator:me?.id}}));
  }
  async function heartbeat(){if(!me)return;try{await api('/api/operators/presence',{incident:(state.incidents||[]).some(i=>i.id===selected)?selected:null});}catch(e){notify(e.message);}}
  window.addEventListener('mando:state',e=>{state=e.detail;if(scene!==state.session?.id){scene=state.session?.id;lastSeq=0;selected=null;}render();});
  window.addEventListener('mando:selection',e=>{if(selected===e.detail)return;selected=e.detail;render();heartbeat();});
  $('team-mine').onchange=e=>{mine=e.target.checked;render();};
  $('team-links').onsubmit=async e=>{e.preventDefault();try{const d=Object.fromEntries(new FormData(e.target));const j=await api('/api/personal/links',d);const r=await fetch('/api/personal/qr',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});if(!r.ok)throw new Error('No se pudo generar el QR');const old=$('team-link-result').querySelector('img');if(old)URL.revokeObjectURL(old.src);$('team-link-result').innerHTML=`<a href="${E(j.url)}" target="_blank" rel="noopener noreferrer">Abrir ${E(j.unit_id)}</a><label>Enlace para compartir<input readonly value="${E(j.url)}"></label><img alt="QR del enlace de la unidad"><small>Caduca con esta escena.</small>`;$('team-link-result').querySelector('img').src=URL.createObjectURL(await r.blob());}catch(x){notify(x.message);}};
  $('team-external').onsubmit=async e=>{e.preventDefault();try{await api('/api/external-notice',Object.fromEntries(new FormData(e.target)));e.target.reset();notify('Aviso externo recibido.');}catch(x){notify(x.message);}};
  api('/api/personal/catalog').then(j=>{for(const u of j.units)$('team-links').elements.unit_id.add(new Option(u.name,u.id));for(const r of j.roles)$('team-links').elements.role.add(new Option(r,r));}).catch(e=>notify(e.message));
  identify();setInterval(heartbeat,10000);
})();
