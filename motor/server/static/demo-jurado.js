/* global document, window, navigator, crypto, fetch, FormData */
"use strict";
const element = (id) => document.getElementById(id);
const names = { offered: "Oferta pendiente", accepted: "Aceptada", en_route: "En camino", arrived: "En destino", located: "Localizada", completed: "Completada", declined: "Rechazada", expired: "Caducada", cancelled: "Cancelada" };
const transitions = { offered: ["accept", "decline"], accepted: ["eta", "arrive"], en_route: ["arrive"], arrived: ["locate"], located: ["complete"] };
const actionNames = { accept: "Aceptar", decline: "Rechazar", eta: "Confirmar ETA", arrive: "Llegada", locate: "Localización", complete: "Finalización" };
let state, selected = "demo-organizador", busy = false, stopped = false;
function feedback(text, error = false) {
  element("feedback").textContent = text;
  element("feedback").dataset.error = String(error);
}
function node(tag, text) {
  const item = document.createElement(tag);
  item.textContent = text;
  return item;
}
function render() {
  const real = state.channels.mode === "real";
  element("mode").textContent = real
    ? "CANALES REALES habilitados · la configuración no confirma la entrega. Comprueba cada resultado en Comunicaciones."
    : "SIMULACIÓN · sin mensajes ni llamadas reales. Las acciones se guardan en la base aislada de esta demo.";
  element("phone-status").textContent = real
    ? (state.channels.phone.ready ? "Telefonía configurada. Falta comprobar una llamada y sus callbacks." : "Telefonía incompleta: revisa las variables del servidor.")
    : "En este ensayo no se realizan llamadas, aunque registres un móvil.";
  const actor = state.actors.find((item) => item.id === selected);
  element("actor-state").textContent = actor ? `${actor.name} · canal ${actor.channel} · ${actor.availability === "available" ? "disponibilidad declarada" : "disponibilidad por confirmar"}` : "Personaje no encontrado.";
  const tasks = element("tasks");
  tasks.replaceChildren();
  if (selected === "demo-organizador") {
    const link = node("a", `${state.incidents.length} incidentes · ${state.approvals.filter((a) => a.status === "pending").length} decisiones pendientes. Abrir Sala.`);
    link.href = "/sala";
    tasks.append(link);
  } else {
    for (const assignment of state.assignments.filter((item) => item.actor_id === selected)) {
      const card = node("article", "");
      const incident = state.incidents.find((item) => item.id === assignment.incident_id);
      card.append(node("strong", incident?.text || assignment.incident_id));
      card.append(node("p", `${names[assignment.status] || assignment.status} · ${assignment.zone} · ETA ${assignment.eta_min ?? "sin confirmar"}`));
      if (real && actor?.channel === "phone" && assignment.status === "offered") {
        card.append(node("p", "Atiende la llamada. La aceptación y la ETA aparecerán cuando llegue el callback; no las simulamos aquí."));
      } else {
        for (const kind of transitions[assignment.status] || []) {
          const button = node("button", actionNames[kind]);
          button.type = "button";
          button.disabled = busy;
          button.onclick = () => transition(kind, assignment);
          card.append(button);
        }
      }
      tasks.append(card);
    }
    if (!tasks.children.length) tasks.append(node("p", "Sin tareas todavía. Envía un aviso que necesite este rol."));
  }
}
async function refresh() {
  const response = await fetch("/api/operations/state", { cache: "no-store" });
  if (response.status === 401 || response.status === 403) {
    state = null;
    element("access").hidden = false;
    element("workspace").hidden = true;
    element("mode").textContent = "Inicia sesión para consultar y manejar la demo.";
    return;
  }
  if (!response.ok) throw new Error("No se pudo consultar MANDO.");
  state = await response.json();
  element("access").hidden = true;
  element("workspace").hidden = false;
  render();
}
async function command(kind, fields) {
  if (busy) return;
  busy = true;
  document.querySelectorAll("#workspace button").forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch("/api/operations/command", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, command_id: crypto.randomUUID(), ...fields }),
      signal: AbortSignal.timeout(15000),
    });
    const result = await response.json();
    if (!response.ok || result.ok !== true) throw new Error(`${result.error || "No autorizado"}. Revisa la Sala antes de volver a intentarlo.`);
    feedback("Registrado en MANDO. La entrega y la respuesta del equipo se comprueban por separado.");
  } catch (error) {
    feedback(`No se confirmó la operación: ${error.message} Actualiza la Sala; no se reenvía automáticamente.`, true);
  } finally {
    busy = false;
    document.querySelectorAll("#workspace button").forEach((button) => { button.disabled = false; });
    await refresh().catch(() => feedback("Sin conexión con MANDO; no se confirma ningún cambio.", true));
  }
}
function transition(kind, assignment) {
  const fields = { assignment_id: assignment.id, expected_version: assignment.version };
  if (kind === "eta") {
    const value = window.prompt(`Confirma el destino ${assignment.zone}. ¿En cuántos minutos llegas?`, "3");
    if (value === null) return;
    const eta = Number(value);
    if (!value.trim() || !Number.isInteger(eta) || eta < 0 || eta > 240) return feedback("Introduce entre 0 y 240 minutos.", true);
    Object.assign(fields, { eta_min: eta, destination_confirmed: true, destination_zone_id: assignment.zone });
  } else if (kind === "decline") {
    const reason = window.prompt("Motivo del rechazo");
    if (!reason?.trim()) return;
    fields.reason = reason;
  }
  if (!window.confirm(`Registrar manualmente «${actionNames[kind]}» para ${assignment.zone} en este ensayo?`)) return;
  command(kind, fields);
}
document.querySelectorAll("[data-actor]").forEach((button) => {
  button.onclick = () => {
    selected = button.dataset.actor;
    document.querySelectorAll("[data-actor]").forEach((other) => other.setAttribute("aria-pressed", String(other === button)));
    render();
  };
});
element("login").onsubmit = async (event) => {
  event.preventDefault();
  const token = new FormData(event.target).get("token");
  event.target.reset();
  try {
    const response = await fetch("/api/operator/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
    if (!response.ok) throw new Error("Token no autorizado.");
    feedback("");
    await refresh();
  } catch (error) { feedback(error.message, true); }
};
element("phone").onsubmit = (event) => {
  event.preventDefault();
  const address = String(new FormData(event.target).get("number")).trim();
  event.target.reset();
  if (!/^\+[1-9]\d{7,14}$/.test(address)) return feedback("El móvil debe estar en formato E.164.", true);
  if (!window.confirm("¿Este móvil pertenece a un participante que acepta recibir la llamada de demostración y está en MANDO_ALLOWED_NUMBERS?")) return;
  command("register_actor", { actor_id: "demo-medico", name: "Equipo médico · demo", roles: ["medico"], channel: "phone", address, availability: "available", zone: "medical_1" });
};
element("incident").onclick = () => {
  if (!window.confirm("Crear un incidente ficticio. En modo conectado puede llamar al médico. ¿Continuar?")) return;
  command("report", { text: element("sample").textContent, zone: "gate_b" });
};
element("copy").onclick = async () => {
  try { await navigator.clipboard.writeText(element("sample").textContent); feedback("Mensaje copiado. Envíalo en el bot de la demo."); }
  catch { feedback("Selecciona y copia el texto del aviso."); }
};
async function poll() {
  if (stopped) return;
  if (!busy) await refresh().catch(() => {
    element("mode").textContent = "SIN CONEXIÓN · los datos pueden estar desactualizados.";
  });
  if (!stopped) window.setTimeout(poll, 3000);
}
window.addEventListener("pagehide", () => { stopped = true; element("phone").reset(); });
poll();
