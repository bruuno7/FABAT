/**
 * Primitivas de presentación de la consola MANDO.
 *
 * COMPLIANCE (transversal):
 *  - Ningún chip comunica solo por color: todos incluyen glifo + etiqueta
 *    textual; el triage añade además forma de borde y relleno distinto.
 *  - Todos los interactivos usan .btn / .field, que fijan foco y tamaño mínimo.
 *  - Los colores viven en globals.css (@theme), no en este archivo.
 */
import {
  CHANNEL_LABEL,
  INCIDENT_TYPE_LABEL,
  PERFIL_LABEL,
  STATUS_LABEL,
  TRIAGE_LABEL,
  type Channel,
  type IncidentStatus,
  type IncidentType,
  type PerfilColor,
  type TriageColor,
} from "@/lib/contract";
import type { FeedTone } from "@/lib/board-types";
import {
  CHANNEL_GLYPH,
  FEED_TONE,
  PERFIL_GLYPH,
  STATUS_GLYPH,
  TRIAGE_GLYPH,
  TYPE_GLYPH,
} from "@/lib/present";

export {
  formatAge,
  formatDateTime,
  formatTime,
  localZoneLabel,
} from "@/lib/present";

/* -------------------------------------------------------------------------- */
/*  Chips                                                                      */
/* -------------------------------------------------------------------------- */

export function TriageChip({
  color,
  size = "sm",
}: {
  color: TriageColor;
  size?: "sm" | "md" | "lg";
}) {
  const sizeCls = size === "lg" ? "tri-lg" : size === "md" ? "tri-md" : "";
  return (
    <span className={`tri tri-${color} ${sizeCls}`}>
      {/* glifo + forma + borde + etiqueta = 4 canales redundantes al color */}
      <span aria-hidden="true" className="tri-mark">
        {TRIAGE_GLYPH[color]}
      </span>
      <span>{TRIAGE_LABEL[color]}</span>
    </span>
  );
}

export function PerfilChip({ color }: { color: PerfilColor }) {
  return (
    <span className={`pf pf-${color}`}>
      <span aria-hidden="true" className="glyph">{PERFIL_GLYPH[color]}</span>
      <span>{PERFIL_LABEL[color]}</span>
    </span>
  );
}

export function StatusChip({ status }: { status: IncidentStatus }) {
  return (
    <span className={`st st-${status}`}>
      <span aria-hidden="true" className="glyph">{STATUS_GLYPH[status]}</span>
      <span>{STATUS_LABEL[status]}</span>
    </span>
  );
}

export function FeedToneChip({ tone }: { tone: FeedTone }) {
  const meta = FEED_TONE[tone];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm text-[0.6rem] font-bold uppercase tracking-wider ${meta.className} border-l-2 px-1 py-px`}
    >
      <span aria-hidden="true" className="glyph">{meta.glyph}</span>
      <span>{meta.label}</span>
    </span>
  );
}

export function TypeTag({ type }: { type: IncidentType }) {
  return (
    <span className="inline-flex items-center gap-1 text-[0.72rem] font-semibold text-ink-2">
      <span aria-hidden="true" className="glyph">{TYPE_GLYPH[type]}</span>
      <span>{INCIDENT_TYPE_LABEL[type]}</span>
    </span>
  );
}

export function ChannelTag({ channel }: { channel: Channel }) {
  return (
    <span className="inline-flex items-center gap-1 text-[0.68rem] text-muted">
      <span aria-hidden="true" className="glyph">{CHANNEL_GLYPH[channel]}</span>
      <span>{CHANNEL_LABEL[channel]}</span>
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/*  Contenedores                                                               */
/* -------------------------------------------------------------------------- */

export function Panel({
  title,
  right,
  children,
  className = "",
  bodyClassName = "p-2",
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-head">
        <h2 className="panel-title">{title}</h2>
        {right}
      </header>
      <div className={`panel-body ${bodyClassName}`}>{children}</div>
    </section>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <p className="text-[0.72rem] leading-relaxed text-muted">{children}</p>;
}

/* -------------------------------------------------------------------------- */
/*  Severidad                                                                  */
/* -------------------------------------------------------------------------- */

export function SeverityMeter({
  severity,
  triage,
}: {
  severity?: number;
  triage: TriageColor;
}) {
  const value = severity ?? 0;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`sev sev-${triage}`} aria-hidden="true">
        {[1, 2, 3, 4, 5].map((i) => (
          <span key={i} className={`sev-bar ${i <= value ? "sev-fill" : ""}`} />
        ))}
      </span>
      {/* Texto alternativo numérico: la severidad no depende del relleno */}
      <span className="mono text-[0.66rem] text-ink-2">
        Sev {severity ?? "?"}/5
      </span>
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/*  Teclado                                                                    */
/* -------------------------------------------------------------------------- */

export function KeyCap({ children }: { children: React.ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}

export function Shortcut({ keys, label }: { keys: string[]; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap">
      {keys.map((k) => (
        <KeyCap key={k}>{k}</KeyCap>
      ))}
      <span className="text-[0.64rem] text-muted">{label}</span>
    </span>
  );
}
