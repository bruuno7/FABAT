"use client";

/**
 * Cajones de «MANDO Ops»: ficha de incidente (firma humana) y mesa de inyección.
 *
 * El cajón de ficha NO ejecuta nada por su cuenta: recoge la acción elegida y la
 * envía a `POST /api/incidents/[id]/decision`, que es quien firma. La lista de
 * actuaciones propuestas viene del backend (`suggested`), no del mock.
 */

import { useEffect, useState } from "react";
import type { BoardIncident } from "@/lib/board-types";
import {
  CHANNEL_LABEL,
  INCIDENT_TYPE_LABEL,
  PERFIL_LABEL,
  TRIAGE_LABEL,
  type Channel,
  type PerfilColor,
} from "@/lib/contract";
import { formatDateTime, formatTime, timelineGlyph } from "@/lib/present";
import { BUCKET_COLOR, opsRef, statusChip, type OpsUnit } from "@/lib/ops";
import { SCENARIOS } from "@/lib/scenario";
import { RESOURCE_LABEL } from "@/lib/allocate";

const PERFILES = Object.keys(PERFIL_LABEL) as PerfilColor[];
const CHANNELS = Object.keys(CHANNEL_LABEL) as Channel[];

/* ========================================================================== */
/*  Ficha de incidente                                                         */
/* ========================================================================== */

export function OpsIncidentDrawer({
  incident,
  units,
  open,
  onClose,
  onConfirm,
  onToggleResolved,
  busy,
  error,
}: {
  incident: BoardIncident | null;
  units: OpsUnit[];
  open: boolean;
  onClose: () => void;
  onConfirm: (action: string, note?: string) => void;
  onToggleResolved: () => void;
  busy: boolean;
  error: string | null;
}) {
  const [checked, setChecked] = useState<string[]>([]);
  const [armed, setArmed] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const id = incident?.correlation_id ?? null;
  const suggested = incident?.suggested ?? [];
  const suggestedKey = suggested.join("\u241f");

  /*
   * Reinicio de la firma SOLO al cambiar de aviso o su lista de actuaciones.
   * La clave es el CONTENIDO de `suggested`, no su identidad: `buildBoard()`
   * devuelve un array nuevo en cada refresco (2,5 s) y si se dependiera de su
   * referencia se borraría la nota y la selección mientras el operador escribe.
   */
  useEffect(() => {
    setChecked(suggested);
    setArmed(null);
    setNote("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, suggestedKey]);

  const triage = incident?.extract?.triage_color ?? "desconocido";
  const action = armed ?? checked[0] ?? suggested[0] ?? "";
  const chip = incident ? statusChip(incident.status) : null;
  const assigned = incident
    ? units.filter((u) => u.incidentId === incident.correlation_id)
    : [];

  return (
    <aside
      id="ops-drawer-incident"
      aria-hidden={!open}
      inert={!open}
      aria-label="Ficha de incidente"
      className={`fixed top-0 right-0 bottom-0 z-50 flex w-[460px] max-w-[100vw] transform flex-col border-l border-slate-200 bg-white shadow-2xl transition-transform duration-300 ${
        open ? "translate-x-0" : "pointer-events-none translate-x-full"
      }`}
    >
      <div className="flex items-start justify-between border-b border-slate-200 bg-slate-50 p-5">
        <div className="flex items-start gap-3">
          <div
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-lg font-black"
            style={{ background: `${BUCKET_COLOR[triage]}1a`, color: BUCKET_COLOR[triage] }}
          >
            <span className="material-symbols-outlined text-[22px]" aria-hidden="true">
              emergency
            </span>
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-lg font-extrabold text-slate-900">
                {incident ? opsRef(incident.correlation_id) : "—"}
              </span>
              <span
                className="rounded-full px-2 py-0.5 text-[10px] font-extrabold text-white"
                style={{ background: BUCKET_COLOR[triage] }}
              >
                {TRIAGE_LABEL[triage].toUpperCase()}
              </span>
              {incident?.extract?.perfil_color === "menor" && (
                <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-700">
                  MENOR EDAD
                </span>
              )}
              {chip && (
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${chip.cls}`}
                >
                  {chip.label}
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs font-medium text-slate-600">
              {incident
                ? `${INCIDENT_TYPE_LABEL[
                    incident.extract?.incident_type ?? "otro"
                  ]} · ${incident.extract?.sector ?? "sin sector"}`
                : "Selecciona un aviso en el plano o en el manifiesto."}
            </p>
            {incident && (
              <span className="font-mono text-[10px] text-slate-400">
                Notificado: {formatDateTime(incident.reported_at)}
              </span>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-200"
          aria-label="Cerrar ficha"
        >
          <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
            close
          </span>
        </button>
      </div>

      {incident && (
        <>
          <div className="ops-scroll flex-1 space-y-4 overflow-y-auto p-5">
            {incident.needs_card && (
              <div className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-3.5 text-red-900">
                <span
                  className="material-symbols-outlined text-[24px] text-red-600"
                  aria-hidden="true"
                >
                  gavel
                </span>
                <div className="text-xs">
                  <div className="font-bold tracking-wide uppercase">
                    Requiere confirmación humana
                  </div>
                  <div className="mt-0.5 text-red-700">
                    El motor propone el protocolo; la mesa MANDO firma. Ninguna
                    acción grave se ejecuta sola.
                  </div>
                </div>
              </div>
            )}

            {(incident.text || incident.extract?.summary) && (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 text-xs">
                <span className="text-[10px] font-bold tracking-wide text-slate-400 uppercase">
                  Texto del aviso ({incident.channel ?? "canal desconocido"})
                </span>
                <p className="mt-1 font-medium text-slate-800 italic">
                  “{incident.text ?? incident.extract?.summary}”
                </p>
              </div>
            )}

            <div className="space-y-2">
              <span className="text-xs font-bold tracking-wide text-slate-800 uppercase">
                Actuaciones propuestas ({suggested.length})
              </span>
              {suggested.length === 0 && (
                <p className="text-xs text-slate-500">
                  El backend no ha propuesto actuaciones para este aviso.
                </p>
              )}
              {suggested.map((suggestion) => {
                const isChecked = checked.includes(suggestion);
                return (
                  <label
                    key={suggestion}
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 ${
                      action === suggestion
                        ? "border-blue-300 bg-blue-50"
                        : "border-slate-200 bg-white hover:bg-slate-50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() =>
                        setChecked((prev) =>
                          prev.includes(suggestion)
                            ? prev.filter((s) => s !== suggestion)
                            : [...prev, suggestion],
                        )
                      }
                      className="mt-0.5 rounded"
                    />
                    <span
                      className="flex-1 text-xs"
                      onClick={() => setArmed(suggestion)}
                    >
                      <span className="block font-bold text-slate-900">
                        {suggestion}
                      </span>
                      <span className="mt-0.5 block text-slate-500">
                        {action === suggestion
                          ? "Se firmará esta actuación."
                          : "Pulsa para elegirla como actuación firmada."}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>

            <label className="block">
              <span className="text-xs font-bold tracking-wide text-slate-800 uppercase">
                Nota de la firma (opcional)
              </span>
              <textarea
                value={note}
                onChange={(ev) => setNote(ev.target.value)}
                rows={2}
                className="mt-1.5 w-full rounded-xl border border-slate-200 p-2.5 text-xs focus:ring-2 focus:ring-blue-500 focus:outline-none"
                placeholder="p. ej. se moviliza UVI externa por no haber recurso libre"
              />
            </label>

            {assigned.length > 0 && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3.5 text-xs text-emerald-900">
                <span className="font-bold uppercase">Recursos asignados:</span>
                <p className="mt-0.5">
                  {assigned.map((u) => `${u.id} (${u.role})`).join(" · ")}
                </p>
              </div>
            )}

            {!incident.covered && incident.missing.length > 0 && (
              <div className="rounded-xl border border-red-300 bg-red-50 p-3.5 text-xs text-red-800">
                <span className="font-bold uppercase">
                  Sin disponibilidad inmediata:
                </span>
                <p className="mt-0.5">
                  Falta {incident.missing.map((k) => RESOURCE_LABEL[k]).join(" + ")}.
                  La prioridad de este aviso es P{incident.priority}.
                </p>
              </div>
            )}

            <div>
              <span className="text-xs font-bold tracking-wide text-slate-800 uppercase">
                Traza ({incident.timeline.length})
              </span>
              <ul className="mt-2 space-y-1.5">
                {incident.timeline.map((entry, i) => (
                  <li
                    key={`${entry.at}-${i}`}
                    className="border-l-2 border-slate-200 pl-2 text-[11px] leading-snug text-slate-600"
                  >
                    <span className="mono text-slate-400">
                      {formatTime(entry.at)}
                    </span>{" "}
                    <span aria-hidden="true" className="glyph">
                      {timelineGlyph(entry.kind)}
                    </span>{" "}
                    {entry.text}
                  </li>
                ))}
                {incident.timeline.length === 0 && (
                  <li className="text-[11px] text-slate-500">
                    Sin eventos registrados.
                  </li>
                )}
              </ul>
            </div>
          </div>

          <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50 p-5">
            <div>
              <div className="text-[10px] font-bold tracking-wide text-slate-400 uppercase">
                Autoridad firmante
              </div>
              <div className="text-xs font-bold text-slate-800">
                {incident.decision?.decided_by ?? "Mesa MANDO"}
              </div>
              {incident.decision && (
                <div className="text-[10px] text-slate-500">
                  Ya firmado: {incident.decision.action}
                </div>
              )}
            </div>
            <div className="flex flex-col items-end gap-1">
              {error && (
                <span role="alert" className="text-[11px] font-semibold text-red-600">
                  {error}
                </span>
              )}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={onToggleResolved}
                  className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs font-bold text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                >
                  {incident.status === "resuelto" ? "Reabrir" : "Marcar resuelto"}
                </button>
                <button
                  type="button"
                  disabled={busy || action === ""}
                  onClick={() => onConfirm(action, note.trim() || undefined)}
                  className="flex items-center gap-1.5 rounded-xl bg-red-600 px-4 py-2.5 text-xs font-bold text-white shadow-md transition-colors hover:bg-red-700 disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
                    verified
                  </span>
                  <span>{busy ? "Firmando…" : "Confirmar decisión"}</span>
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </aside>
  );
}

/* ========================================================================== */
/*  Mesa de inyección                                                          */
/* ========================================================================== */

export function OpsInjectionDrawer({
  open,
  onClose,
  onLoadScenario,
  onInjectManual,
  onReset,
  progress,
  busy,
  error,
}: {
  open: boolean;
  onClose: () => void;
  onLoadScenario: (id: "dia1" | "dia2") => void;
  onInjectManual: (text: string, perfil: PerfilColor, channel: Channel) => void;
  onReset: () => void;
  progress: Record<"dia1" | "dia2", { done: number; total: number }>;
  busy: boolean;
  error: string | null;
}) {
  const [text, setText] = useState("");
  const [perfil, setPerfil] = useState<PerfilColor>("adulto");
  const [channel, setChannel] = useState<Channel>("telegram");

  return (
    <aside
      id="ops-drawer-injection"
      aria-hidden={!open}
      inert={!open}
      aria-label="Mesa de inyección"
      className={`fixed top-0 right-0 bottom-0 z-50 flex w-[420px] max-w-[100vw] transform flex-col border-l border-slate-200 bg-white shadow-2xl transition-transform duration-300 ${
        open ? "translate-x-0" : "pointer-events-none translate-x-full"
      }`}
    >
      <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 p-5">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-[22px] text-blue-600" aria-hidden="true">
            playlist_add
          </span>
          <h3 className="font-bold text-slate-900">Mesa de inyección</h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-200"
          aria-label="Cerrar mesa de inyección"
        >
          <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
            close
          </span>
        </button>
      </div>

      <div className="ops-scroll flex-1 space-y-5 overflow-y-auto p-5 text-xs">
        <div className="space-y-3">
          <span className="text-[11px] font-bold tracking-wide text-slate-900 uppercase">
            Escenarios de estrés preconfigurados:
          </span>

          {SCENARIOS.map((scenario) => {
            const isDia2 = scenario.id === "dia2";
            const p = progress[scenario.id];
            const done = p.done >= p.total && p.total > 0;
            return (
              <div
                key={scenario.id}
                className={`space-y-2 rounded-xl border p-3.5 ${
                  isDia2 ? "border-red-200 bg-red-50/40" : "border-slate-200 bg-white"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-900">{scenario.name}</span>
                  <span
                    className={`rounded px-2 py-0.5 text-[10px] font-bold ${
                      isDia2
                        ? "bg-red-600 text-white"
                        : "bg-emerald-100 text-emerald-800"
                    }`}
                  >
                    {isDia2 ? "SATURACIÓN" : "CONTROLADO"}
                  </span>
                </div>
                <p className="text-[11px] text-slate-500">{scenario.subtitle}</p>
                <p className="mono text-[10px] text-slate-500">
                  Inyectados {p.done}/{p.total}
                </p>
                <button
                  type="button"
                  disabled={busy || done}
                  onClick={() => onLoadScenario(scenario.id)}
                  className={`w-full rounded-lg py-1.5 font-bold transition-colors disabled:opacity-50 ${
                    isDia2
                      ? "bg-red-600 text-white hover:bg-red-700"
                      : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                  }`}
                >
                  {done ? "Escenario ya cargado" : `Cargar ${scenario.name}`}
                </button>
              </div>
            );
          })}

          <button
            type="button"
            disabled={busy}
            onClick={onReset}
            className="w-full rounded-lg border border-slate-200 py-1.5 font-bold text-slate-600 hover:bg-slate-100 disabled:opacity-50"
          >
            Vaciar el tablero
          </button>
        </div>

        <div className="space-y-2 border-t border-slate-100 pt-3">
          <span className="text-[11px] font-bold tracking-wide text-slate-900 uppercase">
            Inyectar aviso manual:
          </span>
          <textarea
            value={text}
            onChange={(ev) => setText(ev.target.value)}
            rows={3}
            className="w-full rounded-xl border border-slate-200 p-2.5 text-xs focus:ring-2 focus:ring-blue-500 focus:outline-none"
            placeholder="Ej: Dos intoxicados en la carpa este no responden a estímulos…"
          />
          <label className="flex items-center gap-2 text-[11px] text-slate-600">
            Perfil
            <select
              value={perfil}
              onChange={(ev) => setPerfil(ev.target.value as PerfilColor)}
              className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs"
            >
              {PERFILES.map((p) => (
                <option key={p} value={p}>
                  {PERFIL_LABEL[p]}
                </option>
              ))}
            </select>
          </label>
          {/* El canal decide el camino real en el backend: `telegram` y `webcall`
              entran por el mismo `processReport`, pero Telegram además responde
              al ciudadano si hay TELEGRAM_BOT_TOKEN. */}
          <label className="flex items-center gap-2 text-[11px] text-slate-600">
            Canal
            <select
              value={channel}
              onChange={(ev) => setChannel(ev.target.value as Channel)}
              className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs"
            >
              {CHANNELS.map((c) => (
                <option key={c} value={c}>
                  {CHANNEL_LABEL[c]}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={busy || text.trim() === ""}
            onClick={() => {
              onInjectManual(text.trim(), perfil, channel);
              setText("");
            }}
            className="flex w-full items-center justify-center gap-1 rounded-xl bg-blue-600 py-2 font-bold text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
              bolt
            </span>
            {busy ? "Inyectando…" : "Clasificar e inyectar"}
          </button>
          <p className="text-[10px] leading-snug text-slate-400">
            El aviso entra por el mismo camino que un reporte real: extractor
            determinista y reevaluación del plan. El perfil es categoría
            operativa, no un dato clínico. Con el canal Telegram y el bot
            configurado, el backend además responde al ciudadano.
          </p>
        </div>

        {error && (
          <p role="alert" className="rounded-lg bg-red-50 p-2 text-[11px] font-semibold text-red-700">
            {error}
          </p>
        )}
      </div>

      <div className="flex justify-end border-t border-slate-200 bg-slate-50 p-4">
        <button
          type="button"
          onClick={onClose}
          className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 hover:bg-slate-100"
        >
          Cerrar
        </button>
      </div>
    </aside>
  );
}

/* ========================================================================== */
/*  Aviso emergente                                                            */
/* ========================================================================== */

export function OpsToast({
  message,
  visible,
  tone = "ok",
}: {
  message: string;
  visible: boolean;
  tone?: "ok" | "danger";
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed bottom-6 left-1/2 z-[60] flex -translate-x-1/2 transform items-center gap-2.5 rounded-xl border border-slate-700 bg-[#0a1526] px-4 py-2.5 text-white shadow-2xl transition-all duration-300 ${
        visible ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-24 opacity-0"
      }`}
    >
      <span
        className={`material-symbols-outlined text-[20px] ${
          tone === "danger" ? "text-red-400" : "text-emerald-400"
        }`}
        aria-hidden="true"
      >
        {tone === "danger" ? "error" : "check_circle"}
      </span>
      <span className="text-xs font-semibold">{message}</span>
    </div>
  );
}
