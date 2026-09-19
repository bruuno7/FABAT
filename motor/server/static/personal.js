(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const statuses = {en_route:'En camino',on_scene:'En el sitio',stabilized:'Paciente estabilizado',transport:'Traslado a puesto médico',needs_support:'Necesito apoyo',route_blocked:'Ruta bloqueada',exhausted:'Recurso agotado',free:'Libre'};
  let token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('mando.unit') || '', who = null, busy = false;
  if (location.hash) history.replaceState(null,'',location.pathname);
  const tell = (text, error=false) => { $('confirmation').textContent=text; $('confirmation').classList.toggle('error',error); };
  async function api(path, data) {
    const r=await fetch(path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json','X-Mando-Unit':token},body:data?JSON.stringify(data):undefined});
    const j=await r.json(); if(!r.ok)throw new Error(j.error||j.detail||'No se ha podido enviar'); return j;
  }
  function option(select, id, name) { const o=document.createElement('option');o.value=id;o.textContent=name;select.append(o); }
  async function refresh() {
    if(!token || busy)return;
    try {
      const j=await api('/api/personal/me');who=j.unit;
      sessionStorage.setItem('mando.unit',token);
      $('identity').textContent=`${who.name} · ${j.role}`;$('setup').hidden=true;$('work').hidden=false;
      if(!$('zone').options.length) {j.zones.forEach(z=>option($('zone'),z.id,z.name));$('zone').value=who.zone;}
      const previous=$('orders').dataset.signature, signature=JSON.stringify(j.orders);
      if(previous!==signature){$('orders').dataset.signature=signature;$('orders').replaceChildren();
        if(!j.orders.length)$('orders').textContent='Sin órdenes pendientes. Puedes enviar un parte o un aviso nuevo.';
        j.orders.forEach(a=>{const el=document.createElement('article'),p=document.createElement('p');p.textContent=`${a.id} · ${a.text}`;el.append(p);
          for(const [result,label] of [['accept','Aceptar'],['reject','Rechazar']]){const b=document.createElement('button');b.textContent=a.result?`${a.result==='accept'?'ACEPTADA':'RESPONDIDA'}`:label;b.disabled=!!a.result;b.onclick=()=>send(`/api/personal/order/${encodeURIComponent(a.id)}`,{result,reason:$('detail').value});el.append(b);}$('orders').append(el);});}
    } catch(e){tell(e.message,true);who=null;$('work').hidden=true;$('setup').hidden=false;}
  }
  async function send(path, data) {
    if(busy)return;busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);
    tell('Enviando…');
    try { const j=await api(path,data);tell(j.say_text||'Recibido.');$('detail').value='';if(navigator.vibrate)navigator.vibrate(40); }
    catch(e){tell(e.message,true);}finally{busy=false;$('orders').dataset.signature='';document.querySelectorAll('button').forEach(b=>b.disabled=false);await refresh();}
  }
  Object.entries(statuses).forEach(([status,label])=>{const b=document.createElement('button');b.dataset.status=status;b.textContent=label;$('statuses').append(b);});
  document.addEventListener('click',e=>{const b=e.target.closest('[data-status]');if(!b||!who)return;
    send('/api/personal/status',{unit_id:who.id,status:b.dataset.status,zone:$('zone').value,free_text:$('detail').value,needs_support:b.dataset.status==='needs_support',event_id:crypto.getRandomValues(new Uint32Array(4)).join('-')});});
  $('open').onclick=()=>{try{const u=new URL($('link').value,location.origin);token=new URLSearchParams(u.hash.slice(1)).get('token')||'';$('link').value='';if(!token)throw new Error();refresh();}catch{tell('Pega el enlace completo del centro.',true);}};
  fetch('/api/personal/catalog').then(r=>r.json()).then(j=>{j.units.forEach(u=>option($('unit'),u.id,u.name));j.roles.forEach(r=>option($('role'),r,r));});
  tell(token?'Comprobando tu unidad…':'Necesitas el enlace del centro para enviar partes.');refresh();setInterval(refresh,2500);
})();
