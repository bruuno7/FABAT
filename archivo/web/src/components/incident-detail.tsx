"use client";

import { RESOURCE_LABEL } from "@/lib/allocate";
import type { BoardIncident } from "@/lib/board-types";
import type { TimelineEntry } from "@/lib/contract";
import {
  formatDateTime,
  formatTime,
  reporterRef,
  timelineGlyph,
} from "@/lib/present";
import {
  ChannelTag,
  KeyCap,
  PerfilChip,
  SeverityMeter,
  StatusChip,
  TriageChip,
  TypeTag,
} from "./ui";

const KIND_LABEL: Record<TimelineEntry["kind"], string> = {
  report_in: "Aviso recibido",
  hr_extract: "Extracto HR",
  hr_reply: "Respuesta al ciudadano",
  hr_needs_human: "Intervención humana",
  hr_session_ended: "Fin de sesión",
  allocation: "Asignación",
  decision: "Decisión",
  status: "Estado",
};

/**
 * Cajón de detalle del incidente. Se abre a demanda (fila de la tabla o marcador
 * del mapa) y NO se incrusta en el flujo principal: así el mapa y la tabla
 * mantienen su calma.
 *
 * COMPLIANCE:
 *  - RGPD Art. 9: el reportante va seudonimizado y degradado; el perfil se trata
 *    como categoría operativa (protocolo), nunca como diagnóstico médico.
 *  - Traza auditable VISIBLE, no en un <details> colapsado: quién decidió qué y
 *    cuándo es material de auditoría.
 *  - La decisión exige confirmación humana explícita; el botón es la acción
 *    primaria y tiene 44px de alto.
 */
export function IncidentDetail({
  incident,
  action,
  onActionChange,
  note,
  onNoteChange,
  onConfirm,
  onResolve,
  onClose,
  busy,
  error,
  decidedByDefault,
}: {
  incident: BoardIncident;
  action: string;
  onActionChange: (action: string) => void;
  note: string;
  onNoteChange: (note: string) => void;
  onConfirm: () => void;
  onResolve: () => void;
  onClose: () => void;
  busy: boolean;
  error: string | null;
  decidedByDefault: string;
}) {
  const e = incident.extract ?? {};
  const triage = e.triage_color ?? "desconocido";
  const perfil = e.perfil_color ?? incident.reporter?.perfil_color;
  const resolved = incident.status === "resuelto";
  const pendingDecision = !resolved && !incident.decision;
  const options =
    incident.suggested.length > 0 ? incident.suggested : ["Inspeccionar el sector"];

  return (
    <div className="flex min-h-0 flex-1 flex-col" aria-label={`Incidente ${incident.correlation_id}`}>
      <header className="flex shrink-0 items-start gap-2 border-b border-outline-soft px-4 py-3">
        <div className="min-w-0 flex-1">
          <TriageChip color={triage} />
          <p className="mt-1.5 text-t3 font-semibold leading-tight text-ink">
            {e.sector ?? "sin ubicación precisa"}
          </p>
          <p className="mono mt-0.5 text-t1 text-muted">
            {incident.correlation_id}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="btn btn-icon shrink-0"
          aria-label="Cerrar el detalle"
        >
          ✕
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <TypeTag type={e.incident_type ?? "otro"} />
          <StatusChip status={incident.status} />
          {incident.channel && <ChannelTag channel={incident.channel} />}
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <SeverityMeter severity={e.severity} triage={triage} />
          <span
            className="mono text-t1 text-muted"
            title={formatDateTime(incident.reported_at)}
          >
            {formatTime(incident.reported_at)}
          </span>
        </div>

        <p className="mt-2.5 text-t2 leading-snug text-ink">
          {e.summary ?? incident.text ?? "(sin texto)"}
        </p>

        {/* COMPLIANCE RGPD Art. 9: datos personales seudonimizados y degradados */}
        <p className="mt-2 text-t1 leading-snug text-muted">
          Reportante{" "}
          <span className="mono text-ink-2">
            {reporterRef(incident.reporter?.external_id, incident.correlation_id)}
          </span>
          · solo categoría operativa, sin identidad real ni datos de salud.
        </p>

        {perfil && (
          <p className="mt-1.5 flex items-center gap-1.5 text-t1 text-muted">
            Protocolo asociado: <PerfilChip color={perfil} />
          </p>
        )}

        {/* Cobertura: glifo + texto, no solo color */}
        <p
          className={`mt-2.5 inline-flex items-center gap-1.5 text-t2 font-medium ${
            resolved
              ? "text-muted"
              : incident.covered
                ? "text-ok"
                : "text-danger"
          }`}
        >
          <span aria-hidden="true" className="glyph">
            {resolved ? "✓" : incident.covered ? "▣" : "✖"}
          </span>
          {resolved
            ? "Cerrado: recursos liberados"
            : incident.covered
              ? "Recursos asignados"
              : `Sin recursos · falta ${incident.missing
                  .map((m) => RESOURCE_LABEL[m])
                  .join(" + ")}`}
        </p>

        {/* Decisión */}
        <div className="mt-3.5 border-t border-outline-soft pt-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="card-title">Decisión</h3>
            {pendingDecision && incident.needs_card && (
              <span className="inline-flex items-center gap-1 text-t1 font-semibold text-danger">
                <span aria-hidden="true" className="glyph">⚠</span> requiere humano
              </span>
            )}
          </div>

          {incident.decision ? (
            <div className="mt-2 rounded-lg border border-outline-soft bg-surface-low px-3 py-2">
              <p className="flex items-center gap-1.5 text-t2 font-medium text-ink">
                <span aria-hidden="true" className="text-ok">
                  ✔
                </span>
                {incident.decision.action}
              </p>
              {incident.decision.note && (
                <p className="mt-1 text-t1 text-ink-2">{incident.decision.note}</p>
              )}
              <p className="mono mt-1 text-t1 text-muted">
                {incident.decision.decided_by} ·{" "}
                {formatDateTime(incident.decision.decided_at)}
              </p>
            </div>
          ) : resolved ? (
            <p className="mt-1.5 text-t1 text-muted">
              Cerrado sin decisión registrada en la traza.
            </p>
          ) : (
            <form
              className="mt-2"
              onSubmit={(ev) => {
                ev.preventDefault();
                onConfirm();
              }}
            >
              <fieldset>
                <legend className="sr-only">Acción a ejecutar</legend>
                <div className="flex flex-col gap-1">
                  {options.map((option, i) => {
                    const id = `act-${incident.correlation_id}-${i}`;
                    const checked = action === option;
                    return (
                      <label
                        key={option}
                        htmlFor={id}
                        className={`flex cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-1.5 text-t2 ${
                          checked
                            ? "border-accent bg-surface-container text-ink"
                            : "border-transparent text-ink-2 hover:bg-surface-low"
                        }`}
                      >
                        <input
                          id={id}
                          type="radio"
                          name={`action-${incident.correlation_id}`}
                          value={option}
                          checked={checked}
                          onChange={() => onActionChange(option)}
                          className="mt-0.5"
                        />
                        <span className="leading-snug">{option}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>

              <label className="mt-2 block">
                <span className="text-t1 font-medium text-muted">
                  Nota para la traza (opcional)
                </span>
                <textarea
                  value={note}
                  onChange={(ev) => onNoteChange(ev.target.value)}
                  rows={2}
                  className="field mt-1 resize-y"
                  placeholder="p. ej. confirmado con jefe de seguridad"
                />
              </label>

              {error && (
                <p className="mt-2 flex items-center gap-1.5 text-t1 font-medium text-danger">
                  <span aria-hidden="true" className="glyph">✖</span> {error}
                </p>
              )}

              <button
                type="submit"
                disabled={busy || !action}
                className="btn btn-primary btn-lg mt-2.5 w-full"
              >
                {busy ? "Confirmando…" : "Confirmar decisión"}
                <KeyCap>Enter</KeyCap>
              </button>
              <p className="mt-1.5 text-t1 text-muted">
                Se registrará como{" "}
                <strong className="font-medium text-ink-2">{decidedByDefault}</strong>
              </p>
            </form>
          )}

          <button
            type="button"
            disabled={busy}
            onClick={onResolve}
            className="btn mt-2 w-full"
          >
            {resolved ? "Reabrir incidente" : "Marcar resuelto"}
            <KeyCap>R</KeyCap>
          </button>
        </div>

        {/* Traza auditable: visible y legible (COMPLIANCE traza auditable) */}
        <div className="mt-3.5 border-t border-outline-soft pt-3">
          <h3 className="card-title">Traza auditable ({incident.timeline.length})</h3>
          {incident.timeline.length === 0 ? (
            <p className="mt-1.5 text-t1 text-muted">Sin entradas todavía.</p>
          ) : (
            <ol className="mt-2 flex flex-col gap-2">
              {incident.timeline.map((entry, i) => (
                <li key={`${entry.at}-${i}`} className="flex gap-2">
                  <span
                    aria-hidden="true"
                    className="mt-px shrink-0 text-t2 text-muted"
                  >
                    {timelineGlyph(entry.kind)}
                  </span>
                  <span className="min-w-0">
                    <span className="flex flex-wrap items-baseline gap-x-1.5">
                      <span className="mono text-t1 font-medium text-ink-2">
                        {formatTime(entry.at)}
                      </span>
                      <span className="text-t1 text-muted">
                        {KIND_LABEL[entry.kind] ?? entry.kind}
                      </span>
                    </span>
                    <span className="block text-t1 leading-snug text-ink-2">
                      {entry.text}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </div>
  );
}
