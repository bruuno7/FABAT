/**
 * Capa de PRESENTACIÓN. No contiene lógica de dominio: solo etiquetas, glifos
 * y formateo. Se mantiene separada para que la auditoría de cumplimiento
 * encuentre en un único sitio todo lo que codifica información de forma
 * redundante (color + texto + glifo + forma).
 *
 * COMPLIANCE (WCAG 1.4.1 "Use of Color"): en MANDO ningún color porta
 * información por sí solo. Cada enum operativo tiene:
 *   - una etiqueta textual (en lib/contract.ts, etiquetas del dominio)
 *   - un glifo inequívoco (aquí)
 *   - una forma/clase CSS distinta cuando aplica (globals.css: .tri-*, .pf-*)
 */
import type {
  Channel,
  IncidentStatus,
  IncidentType,
  PerfilColor,
  TriageColor,
} from "./contract";
import type { FeedTone } from "./board-types";

/*
 * ============================================================================
 * ICONOGRAFÍA
 *
 * La referencia de estilo del usuario usa Material Symbols Outlined. En esta app
 * NO se puede cargar con `next/font/google` (se comprobó: el paquete de datos de
 * fuentes de Next —1942 familias— no incluye Material Symbols, porque es una
 * fuente de iconos con ejes variables). Cargarla por CDN está descartado en
 * producción, y añadir un subconjunto local no cabía en el presupuesto.
 *
 * FALLBACK ACEPTADO: se conservan GLIFOS TIPOGRÁFICOS. Para que sean seguros hay
 * dos medidas:
 *   1. todos los glifos llevan VARIATION SELECTOR-15 (U+FE0E), que pide
 *      explícitamente presentación de TEXTO y evita que el sistema los pinte
 *      como emoji a color (el problema real de accesibilidad: un lector de
 *      pantalla anunciaría "busts in silhouette" en vez de "aglomeración");
 *   2. la clase CSS `.glyph` añade `font-variant-emoji: text` como refuerzo.
 *
 * MAPEO SEMÁNTICO (equivale a los iconos que pedía la referencia):
 *   médica        → medical_services / emergency   → ✚
 *   aglomeración  → group                          → ≋
 *   agresión      → swords / front_hand            → ⚑
 *   clima         → bolt / campaign                → ☈
 *   infraestructura → build / power_off            → ⚙
 *   otro          → info                           → •
 * Los NOMBRES de Material Symbols quedan anotados para que, si algún día se
 * añade la fuente, el cambio sea solo de glifo y no de semántica.
 *
 * COMPLIANCE (WCAG 1.4.1): el icono NUNCA va solo. Siempre acompaña a su
 * etiqueta textual (las etiquetas viven en lib/contract.ts), y los glifos
 * decorativos van con aria-hidden="true".
 * ============================================================================
 */

/** Pide presentación de TEXTO (no emoji) para un glifo. */
function txt(glyph: string): string {
  return `${glyph}\uFE0E`;
}

/** Glifo de triage. Se elige por FORMA, no por color, para leerse en monocromo. */
export const TRIAGE_GLYPH: Record<TriageColor, string> = {
  negro: txt("✖"), // aspa = riesgo vital
  rojo: txt("▲"), // triángulo = emergencia
  amarillo: txt("◆"), // rombo = urgente
  verde: txt("●"), // círculo = leve
  desconocido: txt("?"), // interrogante = sin dato
};

/**
 * Glifo de perfil. `♿` es el símbolo estándar de accesibilidad (ISO 7000) y va
 * forzado a presentación de texto.
 */
export const PERFIL_GLYPH: Record<PerfilColor, string> = {
  menor: txt("◍"),
  pmr: txt("♿"),
  adulto: txt("○"),
  personal: txt("▦"),
  vip: txt("★"),
};

export const STATUS_GLYPH: Record<IncidentStatus, string> = {
  nuevo: txt("◌"),
  asignado: txt("▶"),
  escalado: txt("▲"),
  resuelto: txt("✓"),
};

export const TYPE_GLYPH: Record<IncidentType, string> = {
  // medical_services / emergency
  medica: txt("✚"),
  // group
  aglomeracion: txt("≋"),
  // swords / front_hand
  agresion: txt("⚑"),
  // bolt / campaign — ☈ (U+2608, tormenta) no tiene presentación emoji
  clima: txt("☈"),
  // build / power_off
  infra: txt("⚙"),
  // info
  otro: txt("•"),
};

export const CHANNEL_GLYPH: Record<Channel, string> = {
  telegram: txt("✈"),
  webcall: txt("☎"),
  sms: txt("✉"),
  voice: txt("♪"),
  whatsapp: txt("◍"),
  other: txt("◇"),
};

/** El feed también es color + texto + glifo, nunca solo color. */
export const FEED_TONE: Record<
  FeedTone,
  { label: string; glyph: string; className: string }
> = {
  info: { label: "Info", glyph: txt("•"), className: "tone-info" },
  ok: { label: "Bajo control", glyph: txt("✓"), className: "tone-ok" },
  warn: { label: "Aviso", glyph: "!", className: "tone-warn" },
  danger: { label: "Crítico", glyph: txt("✖"), className: "tone-danger" },
};

const KIND_GLYPH: Record<string, string> = {
  report_in: txt("▼"),
  extract_ready: txt("✦"),
  agent_reply: txt("↩"),
  needs_human: txt("⚠"),
  session_ended: txt("■"),
  decision: txt("✔"),
  plan_broken: txt("✖"),
  plan_ok: txt("✔"),
  status: txt("•"),
};

export function feedKindGlyph(kind: string): string {
  return KIND_GLYPH[kind] ?? "•";
}

/** Glifos de la traza auditable de un incidente (ver IncidentDetail). */
const TIMELINE_GLYPH: Record<string, string> = {
  report_in: txt("▼"),
  hr_extract: txt("✦"),
  hr_reply: txt("↩"),
  hr_needs_human: txt("⚠"),
  hr_session_ended: txt("■"),
  allocation: txt("▣"),
  decision: txt("✔"),
  status: txt("•"),
};

export function timelineGlyph(kind: string): string {
  return TIMELINE_GLYPH[kind] ?? txt("•");
}

/* ---------------------------------------------------------------------------
   Formateo de tiempo (COMPLIANCE: es-ES + hora local legible + zona horaria)
   --------------------------------------------------------------------------- */

/** HH:MM:SS en la hora local del operador. */
export function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--:--";
  return d.toLocaleTimeString("es-ES", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Fecha + hora + zona horaria, para trazas auditables. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "fecha desconocida";
  return d.toLocaleString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
}

/** Minutos transcurridos desde `iso` hasta `now` (para antigüedad en cola). */
export function minutesSince(iso: string, now: Date = new Date()): number {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 0;
  return Math.max(0, Math.floor((now.getTime() - d.getTime()) / 60000));
}

/** Antigüedad compacta: 0m, 7m, 1h 12m. */
export function formatAge(iso: string, now: Date = new Date()): string {
  const mins = minutesSince(iso, now);
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

/** Zona horaria local abreviada, p. ej. "GMT+2". */
export function localZoneLabel(date: Date = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat("es-ES", {
      timeZoneName: "shortOffset",
    }).formatToParts(date);
    return parts.find((p) => p.type === "timeZoneName")?.value ?? "";
  } catch {
    const mins = -date.getTimezoneOffset();
    const sign = mins >= 0 ? "+" : "-";
    const abs = Math.abs(mins);
    return `UTC${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(
      abs % 60,
    ).padStart(2, "0")}`;
  }
}

/* ---------------------------------------------------------------------------
   Minimización de datos (COMPLIANCE: RGPD Art. 9)
   --------------------------------------------------------------------------- */

/**
 * Identificador seudónimo corto para el reportante. Se muestra ESTE en primer
 * plano; el nombre/alias queda degradado a texto secundario.
 */
export function reporterRef(externalId?: string, correlationId?: string): string {
  if (externalId) return externalId.slice(0, 14);
  if (correlationId) return `ref-${correlationId.slice(-6)}`;
  return "ref-??????";
}
