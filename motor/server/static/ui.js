/* Utilidades de las pantallas: SVG local, sin librerías ni recursos externos. */
(function () {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = (n, d = 1) => n == null || !Number.isFinite(Number(n)) ? '—' : Number(n).toLocaleString('es-ES', {maximumFractionDigits:d});
  async function api(url, body) {
    const r = await fetch(url, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const j = await r.json();
    if (!r.ok || j.ok === false) throw new Error(typeof (j.detail || j.error) === 'string' ? j.detail || j.error : `No se pudo completar (${r.status}).`);
    return j;
  }
  const paths = {
    voice:'M7 3H3v4c0 8 6 14 14 14h4v-4l-5-2-2 2a13 13 0 0 1-7-7l2-2Z',
    sms:'M3 4h18v13H9l-6 4ZM7 8h10M7 12h7',
    telegram:'m2 10 20-8-5 20-6-7-5 3 2-7 10-6-7 10',
    email:'M2 5h20v14H2ZM2 5l10 8L22 5',
    web:'M3 3h18v18H3ZM3 8h18M7 5h1M11 5h1M7 12h10M7 16h7',
    sensor:'M12 4v16M8 8v8M4 10v4M16 8v8M20 10v4'
  };
  function channel(ch) {
    ch = ({chat:'web',whatsapp:'sms',operator:'web',radio:'voice'})[ch] || ch;
    return `<svg class="channel-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[ch] || paths.web}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  }
  const labels = {voice:'Voz',sms:'SMS',telegram:'Telegram',email:'Email',web:'Web',chat:'Web',sensor:'Sensor',radio:'Radio',whatsapp:'Mensajería',operator:'Operador'};
  function graph(left, right, opts = {}) {
    const a = Array.isArray(left) ? left.map(v => typeof v === 'number' && Number.isFinite(v) ? v : null) : [];
    const b = Array.isArray(right) ? right.map(v => typeof v === 'number' && Number.isFinite(v) ? v : null) : [];
    if (!a.some(v => v !== null) || !b.some(v => v !== null)) return '<p class="data-note">El servidor aún no entrega las dos series minuto a minuto.</p>';
    const n = Math.max(a.length,b.length), max = Math.max(6,...a.filter(v=>v!==null),...b.filter(v=>v!==null))*1.08;
    const x = i => 42 + i * 426 / Math.max(1,n-1), y = v => 162 - v / max * 132;
    const line = (values,cls) => { let pen=false; return `<path class="${cls}" d="${values.map((v,i)=>{if(v===null){pen=false;return '';}const p=`${pen?'L':'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;pen=true;return p;}).join(' ')}"/>`; };
    const names = opts.labels || ['Lo que hará Mando','Tu alternativa'];
    const title = `${opts.zone || 'Densidad'}: personas por metro cuadrado, ${n} minutos`;
    const stats = values => { const valid=values.filter(v=>v!==null); return `pico ${num(Math.max(...valid))}/m² · ${valid.filter(v=>v>4).length} min > 4 · ${valid.filter(v=>v>5).length} min > 5`; };
    return `<figure class="density-chart"><figcaption>${esc(title)} <small>Simulación · N = 1 ensayo por opción</small></figcaption>
      <svg viewBox="0 0 490 198" role="img" aria-label="${esc(title)}. ${esc(names[0])}: ${stats(a)}. ${esc(names[1])}: ${stats(b)}">
      ${[0,2,4,5,Math.ceil(max)].map(v=>`<line class="${v===4||v===5?'threshold':'gridline'}" x1="42" x2="468" y1="${y(v)}" y2="${y(v)}"/><text x="32" y="${y(v)+4}" text-anchor="end">${v}</text>`).join('')}
      ${line(a,'curve-mando')}${line(b,'curve-alt')}
      <text x="42" y="184">+1 min</text><text x="468" y="184" text-anchor="end">+${n} min</text></svg>
      <div class="chart-key"><span class="key-mando">${esc(names[0])}: ${stats(a)}</span><span class="key-alt">${esc(names[1])}: ${stats(b)}</span></div>
      <details><summary>Ver cifras por minuto</summary><table><thead><tr><th>Minuto</th><th>${esc(names[0])}</th><th>${esc(names[1])}</th></tr></thead><tbody>${Array.from({length:n},(_,i)=>`<tr><td>+${i+1}</td><td>${num(a[i],3)}</td><td>${num(b[i],3)}</td></tr>`).join('')}</tbody></table></details></figure>`;
  }
  function comparison(result, zone, labels) {
    return graph(result?.mando?.series?.[zone],result?.alternative?.series?.[zone], {zone:result?.zones?.[zone] || zone, labels});
  }
  window.MANDO_UI = {esc,num,api,channel,labels,graph,comparison};
})();
