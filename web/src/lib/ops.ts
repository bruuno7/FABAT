/**
 * «MANDO Ops» — capa de ADAPTACIÓN entre el backend del repositorio y la
 * interfaz final (pantalla `/ops`).
 *
 * QUÉ ES Y QUÉ NO ES
 * ------------------
 * Este archivo NO decide nada operativo: no reparte recursos, no prioriza, no
 * cambia estados. Todo lo operativo viene ya calculado por el backend
 * (`/api/board` → `lib/board.ts` → `lib/allocate.ts`). Aquí solo se TRADUCE ese
 * estado a las formas que pinta la interfaz: unidades con nombre, zonas del
 * plano, filas del manifiesto y CSV de exportación.
 *
 * REGLA DE HONESTIDAD (la misma del resto del repo)
 * -------------------------------------------------
 * El mock de diseño traía telemetría inventada: ETAs por segundo, velocidades
 * de simulación, «1x/2x», «142 unidades», porcentajes de «Network Pulse». Nada
 * de eso existe en el backend, así que NO se reproduce:
 *   · las unidades se derivan de la dotación REAL (`DEFAULT_CAPACITY`);
 *   · los porcentajes salen de los avisos y de la asignación reales;
 *   · donde no hay dato se dice «—» o «sin dato», no se rellena con ficción.
 * Las columnas de «ROUTE PROGRESS» y «ETA» del mock se sustituyen por
 * antigüedad del aviso y cobertura, que sí son medibles.
 *
 * MAPEO DE VOCABULARIO (diseño → contrato real)
 *   ALFA-n  ← recursos de tipo `medico`      (UVI móvil)
 *   SEG-0n  ← recursos de tipo `seguridad`   (patrulla rápida)
 *   APO-n   ← recursos de tipo `apoyo`       (logística / técnicos)
 *   MANDO-1 ← recurso de tipo `coordinacion`
 * Las capacidades salen de `DEFAULT_CAPACITY`, no de una lista escrita a mano.
 */

import {
  DEFAULT_CAPACITY,
  RESOURCE_ORDER,
  type ResourceKind,
} from "./allocate";
import type { Board, BoardEnv, BoardIncident } from "./board-types";
import {
  INCIDENT_TYPE_LABEL,
  STATUS_LABEL,
  TRIAGE_LABEL,
  type Channel,
  type IncidentStatus,
  type IncidentType,
  type TriageColor,
} from "./contract";
import { formatTime } from "./present";
import { normalizeSector } from "./venue";

/* ========================================================================== */
/*  1. Unidades (derivadas de la dotación real)                               */
/* ========================================================================== */

export type OpsUnit = {
  /** ALFA-1 · SEG-02 · APO-1 · MANDO-1 */
  id: string;
  kind: ResourceKind;
  /** Papel operativo legible (UVI móvil, patrulla rápida…). */
  role: string;
  busy: boolean;
  /** Aviso que está cubriendo, si está ocupada. */
  incidentId?: string;
  /** Punto de partida en el plano (mismo sistema que OPS_ZONES). */
  base: { x: number; y: number };
};

const UNIT_ROLE: Record<ResourceKind, string> = {
  medico: "UVI móvil",
  seguridad: "Patrulla rápida",
  apoyo: "Apoyo / logística",
  coordinacion: "Mesa MANDO · enlace",
};

const UNIT_PREFIX: Record<ResourceKind, string> = {
  medico: "ALFA",
  seguridad: "SEG",
  apoyo: "APO",
  coordinacion: "MANDO",
};

/**
 * Puntos base de cada unidad en el plano. Son POSICIONES DE PRESENTACIÓN
 * (dónde se dibuja su origen), no telemetría: el backend no publica GPS.
 */
const UNIT_BASES: Record<ResourceKind, { x: number; y: number }[]> = {
  medico: [
    { x: 300, y: 112 },
    { x: 872, y: 404 },
  ],
  seguridad: [
    { x: 940, y: 120 },
    { x: 940, y: 300 },
    { x: 96, y: 150 },
  ],
  apoyo: [
    { x: 120, y: 392 },
    { x: 196, y: 452 },
  ],
  coordinacion: [{ x: 520, y: 470 }],
};

function unitId(kind: ResourceKind, index: number): string {
  if (kind === "coordinacion") return "MANDO-1";
  if (kind === "seguridad") return `SEG-0${index + 1}`;
  return `${UNIT_PREFIX[kind]}-${index + 1}`;
}

/** Todas las unidades de la dotación, sin ocupar. Determinista. */
export function buildUnits(): OpsUnit[] {
  const out: OpsUnit[] = [];
  for (const kind of RESOURCE_ORDER) {
    const total = DEFAULT_CAPACITY[kind];
    for (let i = 0; i < total; i += 1) {
      const bases = UNIT_BASES[kind];
      out.push({
        id: unitId(kind, i),
        kind,
        role: UNIT_ROLE[kind],
        busy: false,
        base: bases[i] ?? bases[0],
      });
    }
  }
  return out;
}

/**
 * Unidades con su ocupación REAL.
 *
 * Se recorre `allocation.assignments`, que ya viene en orden de prioridad y ya
 * decidió qué avisos se cubren. Para cada asignación se consume la siguiente
 * unidad libre de cada tipo: así el reparto de unidades concretas es
 * determinista y coherente con lo que el backend dice que está cubierto.
 */
export function deriveUnits(board: Board | null): OpsUnit[] {
  const units = buildUnits();
  if (!board) return units;

  const pool = new Map<ResourceKind, OpsUnit[]>();
  for (const unit of units) {
    const list = pool.get(unit.kind);
    if (list) list.push(unit);
    else pool.set(unit.kind, [unit]);
  }

  for (const assignment of board.allocation.assignments) {
    for (const kind of assignment.kinds) {
      const unit = pool.get(kind)?.shift();
      if (!unit) continue;
      unit.busy = true;
      unit.incidentId = assignment.correlation_id;
    }
  }
  return units;
}

export function unitsForIncident(units: OpsUnit[], id: string): OpsUnit[] {
  return units.filter((u) => u.incidentId === id);
}

export type FleetRow = {
  kind: ResourceKind;
  role: string;
  total: number;
  busy: number;
  free: number;
  units: OpsUnit[];
};

export type FleetTotals = {
  total: number;
  busy: number;
  free: number;
  rows: FleetRow[];
};

export function fleetTotals(units: OpsUnit[]): FleetTotals {
  const rows: FleetRow[] = RESOURCE_ORDER.map((kind) => {
    const list = units.filter((u) => u.kind === kind);
    const busy = list.filter((u) => u.busy).length;
    return {
      kind,
      role: UNIT_ROLE[kind],
      total: list.length,
      busy,
      free: list.length - busy,
      units: list,
    };
  });
  return {
    total: units.length,
    busy: units.filter((u) => u.busy).length,
    free: units.filter((u) => !u.busy).length,
    rows,
  };
}

/* ========================================================================== */
/*  2. Indicadores (todos calculados, ninguno escrito a mano)                  */
/* ========================================================================== */

const BUCKET_ORDER: TriageColor[] = [
  "negro",
  "rojo",
  "amarillo",
  "verde",
  "desconocido",
];

/** Etiqueta de gravedad en la escala del diseño (P1..P4 + sin triaje). */
const BUCKET_LABEL: Record<TriageColor, string> = {
  negro: "Vital (P1)",
  rojo: "Emergencia",
  amarillo: "Urgente",
  verde: "Leve",
  desconocido: "Sin triaje",
};

/** Colores del diseño para la gráfica de gravedad. */
export const BUCKET_COLOR: Record<TriageColor, string> = {
  negro: "#020617",
  rojo: "#f87171",
  amarillo: "#fbbf24",
  verde: "#10b981",
  desconocido: "#94a3b8",
};

export type SeverityBucket = {
  key: TriageColor;
  label: string;
  color: string;
  count: number;
  pct: number;
};

/** Reparto de avisos ABIERTOS por gravedad. */
export function severityBuckets(incidents: BoardIncident[]): SeverityBucket[] {
  const open = incidents.filter((i) => i.status !== "resuelto");
  const total = open.length;
  return BUCKET_ORDER.map((key) => {
    const count = open.filter(
      (i) => (i.extract?.triage_color ?? "desconocido") === key,
    ).length;
    return {
      key,
      label: BUCKET_LABEL[key],
      color: BUCKET_COLOR[key],
      count,
      pct: total === 0 ? 0 : Math.round((count / total) * 100),
    };
  });
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}

/** Minutos entre el aviso y la firma humana de su decisión. */
function assignMinutes(row: BoardIncident): number | null {
  const decidedAt = row.decision?.decided_at;
  if (!decidedAt) return null;
  const from = new Date(row.reported_at).getTime();
  const to = new Date(decidedAt).getTime();
  if (Number.isNaN(from) || Number.isNaN(to) || to < from) return null;
  return (to - from) / 60000;
}

export type ClaimStats = {
  open: number;
  covered: number;
  uncovered: number;
  coveragePct: number;
  /** Avisos que exigen tarjeta de decisión humana. */
  needsCard: number;
  resolved: number;
  /** Mediana de minutos hasta la firma; `null` si aún no hay ninguna. */
  medianAssignMin: number | null;
  assignedCount: number;
};

export function claimStats(board: Board | null): ClaimStats {
  const incidents = board?.incidents ?? [];
  const open = incidents.filter((i) => i.status !== "resuelto");
  const covered = open.filter((i) => i.covered).length;
  const mins = incidents
    .map(assignMinutes)
    .filter((m): m is number => m !== null);

  return {
    open: open.length,
    covered,
    uncovered: open.length - covered,
    coveragePct: open.length === 0 ? 100 : Math.round((covered / open.length) * 100),
    needsCard: open.filter((i) => i.needs_card).length,
    resolved: incidents.filter((i) => i.status === "resuelto").length,
    medianAssignMin: median(mins),
    assignedCount: mins.length,
  };
}

export function minutesAgo(iso: string, now: Date | null): number | null {
  if (!now) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.round((now.getTime() - t) / 60000));
}

export function ageLabel(iso: string, now: Date | null): string {
  const mins = minutesAgo(iso, now);
  if (mins === null) return "—";
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  return `${h} h ${String(mins % 60).padStart(2, "0")} m`;
}

/* ========================================================================== */
/*  3. Plano del recinto                                                       */
/* ========================================================================== */

export const OPS_VIEWBOX = "0 0 1000 520";

/**
 * Los 11 sectores del contrato, colocados en el lienzo del diseño.
 * La clave `sector` DEBE coincidir con el `sector` que emite el extractor
 * (`lib/hr-sim.ts`) y con el de `lib/venue.ts`.
 */
export type MapZone = {
  sector: string;
  label: string;
  sub?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  tone: "west" | "stage" | "vip" | "arena" | "service" | "gate";
  /** Rótulo girado 90° (para franjas estrechas). */
  rotated?: boolean;
};

export const OPS_ZONES: MapZone[] = [
  {
    sector: "Campamento",
    label: "CAMPAMENTO",
    sub: "ZONA OESTE · NO ACTIVA",
    x: 40,
    y: 35,
    w: 130,
    h: 230,
    tone: "west",
  },
  {
    sector: "Parking",
    label: "PARKING LOGÍSTICA P1",
    sub: "VIAL EXCLUSIVO SERVICIOS",
    x: 40,
    y: 285,
    w: 160,
    h: 200,
    tone: "west",
  },
  {
    sector: "Escenario principal",
    label: "ESCENARIO PRINCIPAL",
    sub: "FRONT STAGE",
    x: 330,
    y: 50,
    w: 380,
    h: 90,
    tone: "stage",
  },
  {
    sector: "Zona VIP",
    label: "ZONA VIP & PRODUCTION",
    sub: "ACCESO ACREDITADO",
    x: 715,
    y: 50,
    w: 225,
    h: 90,
    tone: "vip",
  },
  {
    sector: "Baños",
    label: "ZONA BAÑOS WC",
    x: 235,
    y: 195,
    w: 75,
    h: 270,
    tone: "service",
    rotated: true,
  },
  {
    sector: "Zona Norte",
    label: "PISTA CENTRAL · ZONA NORTE",
    sub: "AFORO MÁXIMO 18.000 PAX",
    x: 330,
    y: 195,
    w: 380,
    h: 150,
    tone: "arena",
  },
  {
    sector: "Zona de food trucks",
    label: "FOOD TRUCKS & BARRAS",
    x: 735,
    y: 195,
    w: 205,
    h: 150,
    tone: "service",
  },
  {
    sector: "Zona Oeste",
    label: "ZONA OESTE",
    x: 330,
    y: 352,
    w: 175,
    h: 58,
    tone: "arena",
  },
  {
    sector: "Zona Sur",
    label: "ZONA SUR",
    x: 515,
    y: 352,
    w: 195,
    h: 58,
    tone: "arena",
  },
  {
    sector: "Zona Este",
    label: "ZONA ESTE",
    x: 720,
    y: 352,
    w: 220,
    h: 58,
    tone: "arena",
  },
  {
    sector: "Entrada",
    label: "ENTRADA GENERAL · TORNOS ACCESO",
    x: 330,
    y: 418,
    w: 380,
    h: 62,
    tone: "gate",
  },
];

/** Elementos DIBUJADOS: no son sectores y nunca reciben marcadores. */
export const OPS_DECOR = {
  perimeter: { x: 25, y: 20, w: 950, h: 480 },
  foso: {
    x: 385,
    y: 148,
    w: 270,
    h: 40,
    label: "FOSO DE SEGURIDAD (FRONT STAGE)",
  },
  pma: [
    { id: "PMA 1", sub: "PASILLO NORTE", x: 300, y: 112 },
    { id: "PMA 2", sub: "FOOD TRUCKS ESTE", x: 872, y: 404 },
  ],
};

const ZONE_BY_SECTOR = new Map(
  OPS_ZONES.map((z) => [normalizeSector(z.sector), z]),
);

/** Zona dibujable de un sector del contrato, o `null` si no se puede ubicar. */
export function opsZoneForSector(sector: string | undefined): MapZone | null {
  if (!sector) return null;
  return ZONE_BY_SECTOR.get(normalizeSector(sector)) ?? null;
}

const SLOT_R = 12;
const SLOT_GAP = 8;
const SLOT_PAD = 14;
/** Franja superior de la zona reservada al rótulo. */
const SLOT_LABEL_BAND = 26;

/** Rejilla determinista de marcadores dentro de una zona (mismo N → mismas x/y). */
export function opsSlots(
  zone: Pick<MapZone, "x" | "y" | "w" | "h">,
  count: number,
): { x: number; y: number }[] {
  if (count <= 0) return [];
  const innerW = zone.w - SLOT_PAD * 2;
  const innerH = zone.h - SLOT_LABEL_BAND - SLOT_PAD;
  const step = SLOT_R * 2 + SLOT_GAP;
  const cols = Math.max(1, Math.min(4, Math.floor((innerW + SLOT_GAP) / step)));
  const rows = Math.max(1, Math.floor((innerH + SLOT_GAP) / step));
  const total = Math.min(count, cols * rows);

  const slots: { x: number; y: number }[] = [];
  for (let i = 0; i < total; i += 1) {
    const row = Math.floor(i / cols);
    const col = i % cols;
    const inRow = Math.min(cols, total - row * cols);
    const rowWidth = inRow * SLOT_R * 2 + (inRow - 1) * SLOT_GAP;
    const startX = zone.x + zone.w / 2 - rowWidth / 2 + SLOT_R;
    const startY = zone.y + SLOT_LABEL_BAND + SLOT_R;
    slots.push({
      x: Math.round(startX + col * step),
      y: Math.round(startY + row * step),
    });
  }
  return slots;
}

/* ========================================================================== */
/*  4. Modelo del plano                                                        */
/* ========================================================================== */

export type MapMarker = {
  id: string;
  x: number;
  y: number;
  triage: TriageColor;
  type: IncidentType;
  sector: string;
  status: IncidentStatus;
  covered: boolean;
  priority: number;
  unitIds: string[];
  /** Rótulo corto y legible del aviso. */
  ref: string;
  ageMin: number | null;
};

export type MapLink = {
  unitId: string;
  incidentId: string;
  ref: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  triage: TriageColor;
};

export type MapModel = {
  markers: MapMarker[];
  links: MapLink[];
  /** Avisos fuera del presupuesto de marcadores (siguen en la tabla). */
  hidden: number;
  /** Avisos sin sector reconocible: no se les inventa una posición. */
  unplaced: BoardIncident[];
};

/** Presupuesto de marcadores visibles a la vez. */
export const OPS_MAX_MARKERS = 16;

/** Rótulo corto de un aviso. No se inventa un identificador: se acorta el real. */
export function opsRef(id: string): string {
  return id.length > 14 ? `${id.slice(0, 13)}…` : id;
}

export function buildMapModel(
  incidents: BoardIncident[],
  units: OpsUnit[],
  now: Date | null,
  max: number = OPS_MAX_MARKERS,
): MapModel {
  const placed: BoardIncident[] = [];
  const unplaced: BoardIncident[] = [];
  for (const incident of incidents) {
    if (opsZoneForSector(incident.extract?.sector)) placed.push(incident);
    else unplaced.push(incident);
  }

  // Prioridad MANDO descendente; empate por id para que el refresco no reordene.
  const sorted = [...placed].sort((a, b) => {
    const diff = b.priority - a.priority;
    if (diff !== 0) return diff;
    return a.correlation_id.localeCompare(b.correlation_id);
  });
  const visible = sorted.slice(0, max);

  const byZone = new Map<string, BoardIncident[]>();
  for (const incident of visible) {
    const zone = opsZoneForSector(incident.extract?.sector);
    if (!zone) continue;
    const list = byZone.get(zone.sector);
    if (list) list.push(incident);
    else byZone.set(zone.sector, [incident]);
  }

  const markers: MapMarker[] = [];
  const positionById = new Map<string, { x: number; y: number }>();

  for (const zone of OPS_ZONES) {
    const list = byZone.get(zone.sector);
    if (!list || list.length === 0) continue;
    list.sort((a, b) => a.correlation_id.localeCompare(b.correlation_id));
    const slots = opsSlots(zone, list.length);
    list.forEach((incident, i) => {
      const slot = slots[i];
      if (!slot) return;
      positionById.set(incident.correlation_id, slot);
      markers.push({
        id: incident.correlation_id,
        x: slot.x,
        y: slot.y,
        triage: incident.extract?.triage_color ?? "desconocido",
        type: incident.extract?.incident_type ?? "otro",
        sector: zone.sector,
        status: incident.status,
        covered: incident.covered,
        priority: incident.priority,
        unitIds: unitsForIncident(units, incident.correlation_id).map((u) => u.id),
        ref: opsRef(incident.correlation_id),
        ageMin: minutesAgo(incident.reported_at, now),
      });
    });
  }

  // Enlaces unidad → aviso: son las asignaciones REALES del backend.
  const links: MapLink[] = [];
  for (const unit of units) {
    if (!unit.busy || !unit.incidentId) continue;
    const to = positionById.get(unit.incidentId);
    if (!to) continue;
    const marker = markers.find((m) => m.id === unit.incidentId);
    links.push({
      unitId: unit.id,
      incidentId: unit.incidentId,
      ref: marker?.ref ?? opsRef(unit.incidentId),
      x1: unit.base.x,
      y1: unit.base.y,
      x2: to.x,
      y2: to.y,
      triage: marker?.triage ?? "desconocido",
    });
  }

  return { markers, links, hidden: sorted.length - visible.length, unplaced };
}

/* ========================================================================== */
/*  5. Manifiesto (tabla inferior) y CSV                                       */
/* ========================================================================== */

export type ManifestRow = {
  id: string;
  ref: string;
  incident: BoardIncident;
  triage: TriageColor;
  type: IncidentType;
  sector: string;
  status: IncidentStatus;
  covered: boolean;
  needsCard: boolean;
  priority: number;
  units: OpsUnit[];
  ageMin: number | null;
  ageLabel: string;
  /** 0..1 para la barra comparativa de antigüedad (la más vieja = 1). */
  ageRatio: number;
  reportedAt: string;
};

export function manifestRows(
  incidents: BoardIncident[],
  units: OpsUnit[],
  now: Date | null,
): ManifestRow[] {
  const ages = incidents
    .map((i) => minutesAgo(i.reported_at, now))
    .filter((m): m is number => m !== null);
  const maxAge = ages.length > 0 ? Math.max(...ages, 1) : 1;

  return incidents.map((incident) => {
    const ageMin = minutesAgo(incident.reported_at, now);
    return {
      id: incident.correlation_id,
      ref: opsRef(incident.correlation_id),
      incident,
      triage: incident.extract?.triage_color ?? "desconocido",
      type: incident.extract?.incident_type ?? "otro",
      sector: incident.extract?.sector ?? "Sin ubicación precisa",
      status: incident.status,
      covered: incident.covered,
      needsCard: incident.needs_card,
      priority: incident.priority,
      units: unitsForIncident(units, incident.correlation_id),
      ageMin,
      ageLabel: ageLabel(incident.reported_at, now),
      ageRatio: ageMin === null ? 0 : Math.min(1, ageMin / maxAge),
      reportedAt: incident.reported_at,
    };
  });
}

export type ManifestFilter =
  | "todas"
  | "abiertos"
  | "criticos"
  | "sin_recursos";

export function filterManifest(
  rows: ManifestRow[],
  filter: ManifestFilter,
  query: string,
): ManifestRow[] {
  let base = rows;
  switch (filter) {
    case "abiertos":
      base = rows.filter((r) => r.status !== "resuelto");
      break;
    case "criticos":
      base = rows.filter(
        (r) =>
          r.status !== "resuelto" &&
          (r.triage === "negro" || r.triage === "rojo"),
      );
      break;
    case "sin_recursos":
      base = rows.filter((r) => r.status !== "resuelto" && !r.covered);
      break;
    default:
      base = rows;
  }

  const q = query.trim().toLowerCase();
  if (!q) return base;
  // Solo texto operativo: no se busca por datos del reportante (minimización).
  return base.filter((r) =>
    [
      r.sector,
      r.incident.extract?.summary,
      r.incident.extract?.incident_type,
      r.incident.text,
      r.ref,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(q),
  );
}

/** Etiqueta y color del chip de estado, con la escala REAL del contrato. */
export function statusChip(status: IncidentStatus): {
  label: string;
  cls: string;
} {
  switch (status) {
    case "asignado":
      return { label: STATUS_LABEL.asignado.toUpperCase(), cls: "bg-blue-100 text-blue-700" };
    case "escalado":
      return { label: STATUS_LABEL.escalado.toUpperCase(), cls: "bg-red-100 text-red-700" };
    case "resuelto":
      return { label: STATUS_LABEL.resuelto.toUpperCase(), cls: "bg-emerald-100 text-emerald-700" };
    default:
      return { label: STATUS_LABEL.nuevo.toUpperCase(), cls: "bg-slate-100 text-slate-700" };
  }
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

/** CSV del manifiesto con los datos REALES del tablero. */
export function boardCsv(board: Board | null, units: OpsUnit[]): string {
  const incidents = board?.incidents ?? [];
  const header = [
    "aviso",
    "estado",
    "gravedad",
    "tipo",
    "sector",
    "prioridad",
    "unidades_asignadas",
    "cubierto",
    "tarjeta_humana",
    "reportado",
    "inicio_aviso",
    "decision_firmada",
    "texto",
  ];
  const lines = [header.map(csvCell).join(";")];

  for (const incident of incidents) {
    const assigned = unitsForIncident(units, incident.correlation_id)
      .map((u) => u.id)
      .join(" + ");
    lines.push(
      [
        incident.correlation_id,
        STATUS_LABEL[incident.status],
        TRIAGE_LABEL[incident.extract?.triage_color ?? "desconocido"],
        INCIDENT_TYPE_LABEL[incident.extract?.incident_type ?? "otro"],
        incident.extract?.sector ?? "",
        incident.priority,
        assigned,
        incident.covered ? "sí" : "no",
        incident.needs_card ? "sí" : "no",
        incident.reported_at,
        formatTime(incident.reported_at),
        incident.decision ? `${incident.decision.decided_at} (${incident.decision.action})` : "",
        incident.text ?? incident.extract?.summary ?? "",
      ]
        .map(csvCell)
        .join(";"),
    );
  }
  return lines.join("\r\n");
}

/** Descarga un CSV generado en el navegador. No envía nada a ningún servidor. */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/* ========================================================================== */
/*  6. Traza (feed)                                                            */
/* ========================================================================== */

/** Color del tono de un evento del feed (nunca va solo: lleva texto y hora). */
export const FEED_TONE_CLASS: Record<string, string> = {
  info: "border-slate-300 text-slate-600",
  ok: "border-emerald-400 text-emerald-700",
  warn: "border-amber-400 text-amber-700",
  danger: "border-red-400 text-red-700",
};

/* ========================================================================== */
/*  7. Integraciones: HappyRobot y Telegram                                    */
/* ========================================================================== */

/**
 * Estado de las dos integraciones que el backend del repo ya implementa:
 *   · HappyRobot → `POST /api/hr/events`  (callback con `x-hr-secret`)
 *                  y aviso saliente a `HR_HOOK_TG` desde `lib/pipeline.ts`.
 *   · Telegram   → `POST /api/telegram/webhook` (con `x-telegram-bot-api-secret-token`)
 *                  y respuesta al ciudadano desde `lib/hr-client.ts`.
 *
 * SOLO SE PUBLICAN BOOLEANOS, nunca valores: `lib/env.ts#envSummary` está
 * diseñado así (`AGENTS.md`: ningún token en pantalla). Aquí solo se etiqueta.
 */
export type IntegrationRow = {
  key: string;
  label: string;
  ok: boolean;
  detail: string;
};

export function integrationRows(env: BoardEnv | undefined): IntegrationRow[] {
  const live = env?.hr_mode === "live";
  return [
    {
      key: "hr",
      label: "HappyRobot",
      ok: live,
      detail: live
        ? "Workflow en vivo: los avisos se envían al Incoming Hook"
        : "Simulado: falta HR_HOOK_TG, el tramo HR se genera local",
    },
    {
      key: "hr_hook",
      label: "Incoming Hook de avisos",
      ok: Boolean(env?.hr_hook_tg),
      detail: env?.hr_hook_tg
        ? "HR_HOOK_TG configurado: los avisos salen a HappyRobot"
        : "Sin HR_HOOK_TG: no se envían avisos a la plataforma",
    },
    {
      key: "hr_secret",
      label: "Firma del callback HR",
      ok: Boolean(env?.hr_secret),
      detail: env?.hr_secret
        ? "HR_SECRET exigido en /api/hr/events"
        : "Sin firmar (solo aceptable en local)",
    },
    {
      key: "telegram",
      label: "Bot de Telegram",
      ok: Boolean(env?.telegram_token),
      detail: env?.telegram_token
        ? "TELEGRAM_BOT_TOKEN configurado: se responde al ciudadano"
        : "Sin configurar: no se responde por Telegram",
    },
    {
      key: "telegram_secret",
      label: "Firma del webhook de Telegram",
      ok: Boolean(env?.telegram_secret),
      detail: env?.telegram_secret
        ? "TELEGRAM_WEBHOOK_SECRET verificado"
        : "Sin verificar el origen del webhook",
    },
  ];
}

/** URL pública que HappyRobot debe llamar. No es un secreto: ya la publica `/api/health`. */
export function hrCallbackUrl(env: BoardEnv | undefined): string {
  return env?.mando_callback_url ?? "—";
}

/** Avisos que han entrado por el bot de Telegram. */
export function telegramReports(incidents: BoardIncident[]): BoardIncident[] {
  return incidents.filter((i) => i.channel === "telegram");
}

export type ChannelCount = { channel: Channel; count: number };

/** Volumen real por canal de entrada (el mock solo enseñaba Telegram). */
export function channelCounts(incidents: BoardIncident[]): ChannelCount[] {
  const counts = new Map<Channel, number>();
  for (const incident of incidents) {
    const channel: Channel = incident.channel ?? "other";
    counts.set(channel, (counts.get(channel) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([channel, count]) => ({ channel, count }))
    .sort((a, b) => b.count - a.count);
}
