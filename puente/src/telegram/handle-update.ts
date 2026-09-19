import { timingSafeEqual } from "node:crypto";
import type { Env } from "../lib/hr-client.js";
import {
  fetchMandoRoster,
  forwardToHappyRobot,
  postMandoRoster,
  telegramAnswerCallback,
  telegramSendMessage,
} from "../lib/hr-client.js";
import { STAFF_ROLES, STAFF_ROLE_LABELS, type StaffRole } from "../lib/contract.js";
import {
  BOT_HELP,
  buildAck,
  parseCommand,
  parseCommandLine,
  parseStaffRole,
  displayNameFromUser,
  guessLocationHint,
  staffOccupancyText,
  telegramUpdateToPublicReport,
  telegramUpdateToStaffResponse,
  type TelegramUpdate,
} from "../lib/telegram-map.js";
import type { IncidentStore } from "../hr/store.js";
import {
  createStaffStore,
  type StaffStore,
} from "./staff-store.js";
import { globalRateLimiter } from "../lib/rate-limit.js";

export type HandleResult = {
  ok: boolean;
  ignored?: boolean;
  correlation_id?: string;
  command?: string;
  kind?: string;
  hr?: { ok: boolean; skipped: boolean; status: number };
  replies: string[];
};

/**
 * Core bot logic: commands locally; free text → ACK + HappyRobot Incoming Hook;
 * botones del personal → HR_HOOK_TG_RESPONSE.
 */
export async function handleTelegramUpdate(
  env: Env,
  update: TelegramUpdate,
  store?: IncidentStore,
  staff: StaffStore = createStaffStore(),
): Promise<HandleResult> {
  if (update.callback_query) {
    return handleCallback(env, update, staff);
  }

  const msg = update.message;
  if (!msg) {
    return { ok: true, ignored: true, replies: [] };
  }

  const chatId = String(msg.chat.id);
  const fromId = msg.from?.id != null ? String(msg.from.id) : chatId;
  const display = displayNameFromUser(msg.from, fromId);

  // ── Photo ──────────────────────────────────────────────────────────────
  if (msg.photo && msg.photo.length > 0) {
    if (!globalRateLimiter.allow(chatId)) {
      const wait = globalRateLimiter.secondsUntilReset(chatId);
      const reply = `⏳ Tu aviso anterior aún está siendo procesado. Espera ${wait}s antes de enviar otro. Si es una emergencia grave llama al 112.`;
      await telegramSendMessage(env.telegramBotToken, chatId, reply);
      return { ok: true, replies: [reply] };
    }
    const caption = msg.caption?.trim();
    const hint = caption ? guessLocationHint(caption) : undefined;
    const ref = `tg-${chatId}-${update.update_id}`.slice(-6).toUpperCase();
    const zoneNote = hint ? ` · Zona: ${hint}` : "";
    const reply = `📷 Ref ${ref}${zoneNote}\nFoto recibida. Si puedes, añade también un texto describiendo la situación.`;
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, replies: [reply] };
  }

  // ── Location (GPS) ─────────────────────────────────────────────────────
  if (msg.location) {
    if (!globalRateLimiter.allow(chatId)) {
      const wait = globalRateLimiter.secondsUntilReset(chatId);
      const reply = `⏳ Tu aviso anterior aún está siendo procesado. Espera ${wait}s antes de enviar otro. Si es una emergencia grave llama al 112.`;
      await telegramSendMessage(env.telegramBotToken, chatId, reply);
      return { ok: true, replies: [reply] };
    }
    const { latitude, longitude } = msg.location;
    const ref = `tg-${chatId}-${update.update_id}`.slice(-6).toUpperCase();
    const reply = `📍 Ref ${ref} · Ubicación GPS recibida (${latitude.toFixed(5)}, ${longitude.toFixed(5)}).\nCoordinación está en camino. Permanece donde estás si es seguro.`;
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, replies: [reply] };
  }

  if (!msg.text?.trim()) {
    return { ok: true, ignored: true, replies: [] };
  }

  const text = msg.text.trim();
  const command = parseCommand(text);

  if (command === "start" || command === "ayuda" || command === "help") {
    const reply = BOT_HELP;
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, command, replies: [reply] };
  }

  if (command === "ping") {
    const reply = "pong — puente Telegram activo";
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, command, replies: [reply] };
  }

  if (command === "rol") {
    const reply = await claimRole(env, staff, chatId, fromId, display, text);
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, command, replies: [reply] };
  }

  if (command === "estado") {
    await hydrateStaff(env, staff);
    const mine = staff.getByChat(chatId);
    const reply = staffOccupancyText(staff.list(), mine?.role);
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, command, replies: [reply] };
  }

  if (command === "baja") {
    await hydrateStaff(env, staff);
    const previous = staff.release(chatId);
    try {
      await postMandoRoster(env.mandoBackendUrl, env.hrSecret, {
        action: "release",
        chat_id: chatId,
      });
    } catch {
      // MANDO caído: el puesto queda suelto en esta instancia.
    }
    const reply = previous
      ? `Dejas el puesto ${STAFF_ROLE_LABELS[previous.role]}. Puesto liberado.`
      : "No tenías ningún puesto registrado. Usa /rol para registrarte.";
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, command, replies: [reply] };
  }

  if (command) {
    const reply = `Comando /${command} no reconocido.\n\n${BOT_HELP}`;
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, command, replies: [reply] };
  }

  // ── Rate limiting (only for incident reports, not commands) ───────────────
  if (!globalRateLimiter.allow(chatId)) {
    const wait = globalRateLimiter.secondsUntilReset(chatId);
    const reply = `⏳ Tu aviso anterior aún está siendo procesado. Espera ${wait}s antes de enviar otro. Si es una emergencia grave llama al 112.`;
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, replies: [reply] };
  }

  const report = telegramUpdateToPublicReport(update);
  if (!report) {
    return { ok: true, ignored: true, replies: [] };
  }

  const ack = buildAck(report.correlation_id!, report.location_hint, report.text);
  await telegramSendMessage(env.telegramBotToken, chatId, ack);

  store?.upsert({
    correlation_id: report.correlation_id!,
    channel: "telegram",
    text: report.text,
    updated_at: new Date().toISOString(),
  });

  const fwd = await forwardToHappyRobot(
    env.hrHookTg,
    report,
    env.hrHookApiKey,
  );

  const replies = [ack];

  // Sin HR configurado: respuesta local útil
  if (fwd.skipped) {
    const local =
      "⚠️ El sistema de coordinación no está disponible en este momento. " +
      "Tu aviso ha quedado registrado. Ref: " +
      report.correlation_id +
      ". Si es urgente llama al 112.";
    await telegramSendMessage(env.telegramBotToken, chatId, local);
    replies.push(local);
  }

  console.info("[telegram] report", {
    correlation_id: report.correlation_id,
    fwd_ok: fwd.ok,
    fwd_skipped: fwd.skipped ?? false,
    fwd_status: fwd.status,
  });

  return {
    ok: true,
    correlation_id: report.correlation_id,
    hr: {
      ok: fwd.ok,
      skipped: fwd.skipped ?? false,
      status: fwd.status,
    },
    replies,
  };
}

async function handleCallback(
  env: Env,
  update: TelegramUpdate,
  staff: StaffStore,
): Promise<HandleResult> {
  const cq = update.callback_query!;
  await telegramAnswerCallback(env.telegramBotToken, cq.id);

  const chatId = String(cq.message?.chat.id ?? cq.from.id);
  await hydrateStaff(env, staff);
  const role = staff.getByChat(chatId)?.role;
  const mapped = telegramUpdateToStaffResponse(update, { role });
  if (!mapped) {
    return { ok: true, ignored: true, replies: [] };
  }

  const fwd = await forwardToHappyRobot(
    env.hrHookTgResponse,
    mapped,
    env.hrHookApiKey,
    "HR_HOOK_TG_RESPONSE not configured",
  );

  const replies: string[] = [];
  if (fwd.skipped) {
    const local =
      "HappyRobot aún no está enlazado (falta HR_HOOK_TG_RESPONSE). " +
      "Tu respuesta quedó registrada en el puente. Ref: " +
      mapped.correlation_id;
    await telegramSendMessage(env.telegramBotToken, mapped.chat_id, local);
    replies.push(local);
  } else if (!fwd.ok) {
    const local = "No pude pasar tu respuesta a control. Inténtalo de nuevo.";
    await telegramSendMessage(env.telegramBotToken, mapped.chat_id, local);
    replies.push(local);
  }

  console.info("[telegram] staff_response", {
    kind: mapped.kind,
    correlation_id: mapped.correlation_id,
    assignment_id: mapped.assignment_id,
    fwd_ok: fwd.ok,
    fwd_skipped: fwd.skipped ?? false,
    fwd_status: fwd.status,
  });

  return {
    ok: true,
    correlation_id: mapped.correlation_id,
    kind: mapped.kind,
    hr: {
      ok: fwd.ok,
      skipped: fwd.skipped ?? false,
      status: fwd.status,
    },
    replies,
  };
}

async function claimRole(
  env: Env,
  staff: StaffStore,
  chatId: string,
  fromId: string,
  display: string,
  text: string,
): Promise<string> {
  const line = parseCommandLine(text);
  const roleArg = line?.args[0];
  const pinArg = line?.args[1];
  await hydrateStaff(env, staff);
  const occupancy = () => staffOccupancyText(staff.list(), staff.getByChat(chatId)?.role);

  if (!roleArg) {
    return [
      "Uso: /rol <puesto> [pin]",
      "Puestos válidos: medico, staff_entradas, organizador, bomberos, policia.",
      "",
      occupancy(),
    ].join("\n");
  }

  const role = parseStaffRole(roleArg);
  if (!role) {
    return `Puesto «${roleArg}» no existe. Válidos: medico, staff_entradas, organizador, bomberos, policia.`;
  }

  if (env.requireSecrets && !env.staffPin) {
    return "El PIN de personal no está configurado. No se pueden tomar puestos en este entorno.";
  }

  if (env.staffPin) {
    if (!pinArg) {
      return `Uso: /rol ${role} <PIN>`;
    }
    if (!pinsEqual(env.staffPin, pinArg)) {
      return "PIN incorrecto.";
    }
  }

  const already = staff.getByChat(chatId);
  if (already?.role === role) {
    return `Ya tienes el puesto ${STAFF_ROLE_LABELS[role]}.`;
  }

  let remote;
  try {
    remote = await postMandoRoster(env.mandoBackendUrl, env.hrSecret, {
      action: "claim",
      role,
      chat_id: chatId,
      alias: display,
    });
  } catch {
    remote = {
      result: { ok: false, status: 0, body: "MANDO request failed", skipped: true },
      view: null,
    };
  }
  if (remote.view) {
    applyRoster(staff, remote.view.seats);
  }
  const persistLocal = () =>
    staff.claim({
      chat_id: chatId,
      user_id: fromId,
      role,
      display_name: display,
      claimed_at: new Date().toISOString(),
    });
  if (!remote.result.skipped) {
    if (remote.view?.reason === "taken" || remote.view?.ok === false) {
      const holder = remote.view.holder?.alias || "otro chat";
      return `Ese puesto ya lo tiene ${holder}. /estado para ver ocupados.`;
    }
    if (!remote.result.ok) {
      return "No pude guardar el puesto en MANDO. Inténtalo de nuevo.";
    }
    if (!staff.getByChat(chatId) || staff.getByChat(chatId)?.role !== role) {
      const result = persistLocal();
      if (!result.ok) {
        return `Ese puesto ya lo tiene ${result.holder.display_name}. /estado para ver ocupados.`;
      }
    }
  } else {
    const result = persistLocal();
    if (!result.ok) {
      return `Ese puesto ya lo tiene ${result.holder.display_name}. /estado para ver ocupados.`;
    }
  }

  const switched = already && already.role !== role
    ? `Dejas ${STAFF_ROLE_LABELS[already.role]} y tomas ${STAFF_ROLE_LABELS[role]}.`
    : `Puesto ${STAFF_ROLE_LABELS[role]} tomado.`;
  const pinNote =
    !env.staffPin && !env.requireSecrets
      ? "\nSin PIN en local: cualquier miembro del equipo puede registrar puestos."
      : "";
  return switched + pinNote;
}

async function hydrateStaff(env: Env, staff: StaffStore): Promise<void> {
  try {
    const { view } = await fetchMandoRoster(env.mandoBackendUrl, env.hrSecret);
    if (view) applyRoster(staff, view.seats);
  } catch {
    // MANDO caído: se usa la caché local de este proceso.
  }
}

function applyRoster(
  staff: StaffStore,
  seats: { rol?: string; claimed?: boolean; chat_id?: string | null; alias?: string; claimed_at?: string | null }[],
): void {
  const roles = new Set<string>(STAFF_ROLES);
  const claims = seats.flatMap((seat) => {
    const role = seat.rol;
    const chatId = seat.chat_id;
    if (!seat.claimed || !role || !roles.has(role) || !chatId) return [];
    return [{
      chat_id: chatId,
      user_id: chatId,
      role: role as StaffRole,
      display_name: seat.alias || `tg:${chatId}`,
      claimed_at: seat.claimed_at || new Date().toISOString(),
    }];
  });
  staff.replaceAll(claims);
}

function pinsEqual(expected: string, got: string): boolean {
  const a = Buffer.from(expected);
  const b = Buffer.from(got);
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}
