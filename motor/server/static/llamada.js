/* Página de quien hace de jefe de equipo (enlace secreto) y del puesto de control cuando escucha o TOMA una llamada.
   El token de LiveKit se pide al servidor SOLO al pulsar; la API key de HappyRobot no sale nunca de allí.
   La conexión WebRTC usa `livekit-client` (lo mismo que envuelve `@happyrobot-ai/sdk/voice`), que hay que dejar en
   static/vendor/livekit-client.umd.min.js: no se carga de ningún CDN. El micrófono exige HTTPS o localhost. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const id = decodeURIComponent(location.pathname.split("/").pop());
  const q = new URLSearchParams(location.search);
  const desk = id === "puesto", action = q.get("accion"), takeover = q.get("modo") === "toma";
  const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })
    .then((r) => r.json().then((j) => { if (!r.ok) throw new Error(j.error || "error"); return j; }));
  const say = (text, err) => { $("msg").textContent = text; $("msg").className = "msg" + (err ? " err" : ""); };
  let room = null, poll = null;

  function lines(list) {
    const box = $("lines"); box.textContent = "";
    (list || []).slice(-5).forEach((l) => { const p = document.createElement("p"), e = document.createElement("em");
      p.className = l.who === "mando" ? "m" : "p"; e.textContent = l.who === "mando" ? "Mando" : "Tú"; p.append(e, l.text); box.append(p); });
  }
  function watch() {
    if (desk) return;
    poll = setInterval(() => fetch("/api/webcall/" + encodeURIComponent(id)).then((r) => r.json()).then((c) => {
      lines(c.transcript);
      if (c.result || c.over) { clearInterval(poll); $("mock").hidden = true; $("live").hidden = true; $("ring").textContent = "LLAMADA TERMINADA";
        say(c.result === "accept" ? "Aceptado. Gracias." : c.result === "reject" ? "Rechazado: Mando ya está buscando a otro equipo." : "La llamada ha terminado."); if (room) room.disconnect(); }
    }).catch(() => {}), 1000);
  }

  async function connect(tok) {
    if (String(tok.url || "").startsWith("mock:")) {   // HappyRobot de mentira: no hay audio, se contesta con botones
      if (!desk) $("mock").hidden = false;
      return say(desk ? (takeover ? "Llamada tomada (plataforma de mentira: sin audio)." : "Escuchando (plataforma de mentira: sin audio).") : "Plataforma de mentira: contesta con los botones.");
    }
    if (window.NO_LIVEKIT || !window.LivekitClient) return say("Falta static/vendor/livekit-client.umd.min.js: sin esa librería este navegador no puede abrir el audio.", true);
    const LK = window.LivekitClient;
    room = new LK.Room();
    room.on(LK.RoomEvent.TrackSubscribed, (track) => { if (track.kind === "audio") track.attach($("audio")); });
    room.on(LK.RoomEvent.Disconnected, () => say("Llamada desconectada."));
    await room.connect(tok.url, tok.token);
    if (!desk || takeover) await room.localParticipant.setMicrophoneEnabled(true);  // quien solo escucha no publica audio
    await room.startAudio();
    $("live").hidden = false;
    say(desk ? (takeover ? "Tienes la llamada: el agente de voz se ha retirado. Habla." : "Escuchando sin que se te oiga.") : "En línea. Habla con normalidad: puedes decir que no.");
  }

  $("pick").onclick = async () => {
    $("pick").disabled = true; say("Conectando…");
    try {
      const tok = desk ? await post(`/api/call/${encodeURIComponent(action)}/token`, { takeover }) : await post(`/api/webcall/${encodeURIComponent(id)}/answer`);
      $("pick").hidden = true; $("ring").textContent = "EN LLAMADA";
      await connect(tok); watch();
    } catch (e) { $("pick").disabled = false; say("No se pudo abrir la llamada: " + e.message, true); }
  };
  $("mock").onclick = (ev) => { const r = ev.target.dataset.r; if (r) { $("mock").hidden = true; post(`/api/webcall/${encodeURIComponent(id)}/mock_answer`, { result: r }).catch((e) => say(e.message, true)); } };
  $("hang").onclick = () => { if (room) room.disconnect(); $("live").hidden = true; };

  if (desk) {
    $("ring").textContent = takeover ? "TOMAR LA LLAMADA" : "ESCUCHAR LA LLAMADA"; $("title").textContent = "Acción " + (action || "");
    $("pick").textContent = takeover ? "TOMAR AHORA" : "ESCUCHAR";
    say(takeover ? "Al entrar tú, el agente de voz se retira y sigues tú con la persona." : "Entras como oyente oculto.");
  } else {
    fetch("/api/webcall/" + encodeURIComponent(id)).then((r) => { if (!r.ok) throw new Error(); return r.json(); }).then((c) => {
      $("title").textContent = "Orden para " + c.title; $("order").textContent = c.order_text; $("order").hidden = false; lines(c.transcript);
      if (c.over) { $("pick").hidden = true; $("ring").textContent = "LLAMADA TERMINADA"; }
    }).catch(() => { $("title").textContent = "Esta llamada ya no existe"; $("pick").hidden = true; });
  }
})();
