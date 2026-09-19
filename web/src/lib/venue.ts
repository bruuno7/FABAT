/**
 * Geometría del recinto para el mapa esquemático en SVG.
 *
 * CAPA DE PRESENTACIÓN, no de dominio. Este archivo NO decide nada operativo:
 * solo traduce un `sector` (texto que ya produce el extractor determinista) a
 * una zona dibujable y reparte los marcadores dentro de ella.
 *
 * Por qué SVG y no un proveedor de mapas: el recinto es un festival, no
 * geografía real. Un plano esquemático dibujado por nosotros permite rotular
 * todos los sectores, no necesita API key y no manda coordenadas de personas a
 * un tercero (COMPLIANCE: minimización de datos, RGPD Art. 5).
 *
 * FUENTE DE VERDAD DE LOS SECTORES: `src/lib/hr-sim.ts` (constante SECTORS).
 * Si allí cambia un sector, hay que cambiarlo aquí también.
 */
import type { BoardIncident } from "./board-types";
import type { TriageColor } from "./contract";

export const VENUE_VIEWBOX = "0 0 1040 700";

/** Literal exacto que emite el extractor cuando no puede ubicar el aviso. */
export const NO_LOCATION = "Sin ubicación precisa";

export type ZoneKind =
  | "stage"
  | "arena"
  | "service"
  | "gate"
  | "outside"
  | "camp";

export type Zone = {
  /** Debe coincidir exactamente con el `sector` del contrato. */
  sector: string;
  /** Etiqueta corta para rotular dentro del plano. */
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
  kind: ZoneKind;
};

/**
 * Zonas del recinto. Todas delimitadas y rotuladas.
 * Orden = orden de dibujo (fondo → frente) y de tabulación si se usa como lista.
 */
export const ZONES: Zone[] = [
  // Fuera del recinto
  { sector: "Parking", label: "Parking", x: 40, y: 70, w: 200, h: 240, kind: "outside" },
  { sector: "Campamento", label: "Campamento", x: 40, y: 350, w: 200, h: 280, kind: "camp" },

  // Recinto — fila superior (escenario y palco)
  { sector: "Escenario principal", label: "Escenario principal", x: 320, y: 80, w: 380, h: 110, kind: "stage" },
  { sector: "Zona VIP", label: "Zona VIP", x: 720, y: 80, w: 250, h: 110, kind: "arena" },

  // Recinto — segunda fila
  { sector: "Zona Norte", label: "Zona Norte", x: 320, y: 215, w: 380, h: 110, kind: "arena" },
  { sector: "Baños", label: "Baños", x: 720, y: 215, w: 250, h: 110, kind: "service" },

  // Recinto — tercera fila
  { sector: "Zona Oeste", label: "Zona Oeste", x: 320, y: 355, w: 175, h: 110, kind: "arena" },
  { sector: "Zona de food trucks", label: "Food trucks", x: 515, y: 355, w: 185, h: 110, kind: "service" },
  { sector: "Zona Este", label: "Zona Este", x: 720, y: 355, w: 250, h: 110, kind: "arena" },

  // Recinto — fila inferior (sur y puerta)
  { sector: "Zona Sur", label: "Zona Sur", x: 320, y: 490, w: 380, h: 135, kind: "arena" },
  { sector: "Entrada", label: "Entrada", x: 720, y: 490, w: 250, h: 135, kind: "gate" },
];

export const ZONE_BY_SECTOR: Map<string, Zone> = new Map(
  ZONES.map((z) => [normalizeSector(z.sector), z]),
);

/** Compara sectores sin depender de mayúsculas, tildes o espacios sobrantes. */
export function normalizeSector(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

/** Devuelve la zona dibujable de un `sector`, o null si el sector no está en el plano. */
export function zoneForSector(sector: string | undefined): Zone | null {
  if (!sector) return null;
  const key = normalizeSector(sector);
  if (key === normalizeSector(NO_LOCATION)) return null;
  return ZONE_BY_SECTOR.get(key) ?? null;
}

/* -------------------------------------------------------------------------- */
/*  Reparto de marcadores dentro de una zona                                  */
/* -------------------------------------------------------------------------- */

export const MARKER_R = 12;
const MARKER_GAP = 7;
const ZONE_PAD_X = 16;
/** Deja libre la franja superior de la zona, donde va su rótulo. */
const ZONE_PAD_TOP = 32;
const ZONE_PAD_BOTTOM = 12;

/**
 * Reparte N marcadores en una rejilla centrada dentro de la zona. El reparto es
 * determinista (mismo N → mismas posiciones) para que el refresco cada 2,5 s no
 * mueva los puntos en pantalla.
 */
export function markerSlots(zone: Zone, count: number): { x: number; y: number }[] {
  if (count <= 0) return [];
  const innerW = zone.w - ZONE_PAD_X * 2;
  const innerH = zone.h - ZONE_PAD_TOP - ZONE_PAD_BOTTOM;
  const step = MARKER_R * 2 + MARKER_GAP;
  const cols = Math.max(1, Math.min(6, Math.floor((innerW + MARKER_GAP) / step)));
  const rows = Math.max(1, Math.floor((innerH + MARKER_GAP) / step));
  const capacity = cols * rows;
  const total = Math.min(count, capacity);

  const slots: { x: number; y: number }[] = [];
  for (let i = 0; i < total; i++) {
    const row = Math.floor(i / cols);
    const col = i % cols;
    const inRow = Math.min(cols, total - row * cols);
    const rowWidth = inRow * MARKER_R * 2 + (inRow - 1) * MARKER_GAP;
    const startX = zone.x + zone.w / 2 - rowWidth / 2 + MARKER_R;
    const startY = zone.y + ZONE_PAD_TOP + MARKER_R;
    slots.push({
      x: Math.round(startX + col * step),
      y: Math.round(startY + row * step),
    });
  }
  return slots;
}

/* -------------------------------------------------------------------------- */
/*  Agrupación por sector                                                     */
/* -------------------------------------------------------------------------- */

export type SectorGroup = {
  zone: Zone;
  incidents: BoardIncident[];
  openCount: number;
};

export type VenueLayout = {
  groups: SectorGroup[];
  /** Avisos sin sector reconocible → nunca se inventa una posición para ellos. */
  unplaced: BoardIncident[];
};

/** Orden de gravedad para decidir el "peor triage" de un sector. */
export const TRIAGE_SEVERITY_ORDER: readonly TriageColor[] = [
  "negro",
  "rojo",
  "amarillo",
  "verde",
  "desconocido",
];

/**
 * Agrupa los avisos por zona del plano. Los que no tienen sector (o tienen uno
 * que no está en el recinto) van a `unplaced`, que se muestra aparte.
 *
 * El orden de los marcadores dentro de cada sector se fija por
 * `correlation_id` para que el refresco no los reordene ni los haga saltar.
 */
export function buildVenueLayout(incidents: BoardIncident[]): VenueLayout {
  const byZone = new Map<string, BoardIncident[]>();
  const unplaced: BoardIncident[] = [];

  for (const incident of incidents) {
    const zone = zoneForSector(incident.extract?.sector);
    if (!zone) {
      unplaced.push(incident);
      continue;
    }
    const list = byZone.get(zone.sector);
    if (list) list.push(incident);
    else byZone.set(zone.sector, [incident]);
  }

  const groups: SectorGroup[] = [];
  for (const zone of ZONES) {
    const list = byZone.get(zone.sector);
    if (!list || list.length === 0) continue;
    list.sort((a, b) => a.correlation_id.localeCompare(b.correlation_id));
    groups.push({
      zone,
      incidents: list,
      openCount: list.filter((i) => i.status !== "resuelto").length,
    });
  }

  unplaced.sort((a, b) => a.correlation_id.localeCompare(b.correlation_id));
  return { groups, unplaced };
}

/** Peor triage de un conjunto de avisos (para el rótulo del sector). */
export function worstTriage(incidents: BoardIncident[]): TriageColor {
  let worst: TriageColor = "desconocido";
  let rank = TRIAGE_SEVERITY_ORDER.length;
  for (const incident of incidents) {
    const t: TriageColor = incident.extract?.triage_color ?? "desconocido";
    const idx = TRIAGE_SEVERITY_ORDER.indexOf(t);
    if (idx >= 0 && idx < rank) {
      rank = idx;
      worst = t;
    }
  }
  return worst;
}

/* -------------------------------------------------------------------------- */
/*  Presupuesto de marcadores                                                  */
/* -------------------------------------------------------------------------- */

/**
 * PRESUPUESTO DE SATURACIÓN: como máximo `max` marcadores dibujados a la vez.
 * El resto no desaparece: se contabiliza en el rótulo del sector como "+K", y
 * sigue siendo accesible en la tabla (que lista todo) y en el detalle.
 *
 * Se eligen por prioridad MANDO descendente, así lo que se ve primero es lo que
 * más importa. El desempate por `correlation_id` mantiene el reparto estable
 * entre refrescos (no hay saltos).
 */
export const MAX_VISIBLE_MARKERS = 12;

export type MarkerBudget = {
  visible: BoardIncident[];
  /** Cuántos avisos quedan sin marcador en cada sector. */
  hiddenBySector: Map<string, number>;
  totalHidden: number;
};

export function selectVisibleMarkers(
  incidents: BoardIncident[],
  max: number = MAX_VISIBLE_MARKERS,
): MarkerBudget {
  const placed = incidents
    .filter((i) => zoneForSector(i.extract?.sector) !== null)
    .slice()
    .sort((a, b) => {
      const diff = b.priority - a.priority;
      if (diff !== 0) return diff;
      return a.correlation_id.localeCompare(b.correlation_id);
    });

  const visible = placed.slice(0, max);
  const hiddenBySector = new Map<string, number>();
  let totalHidden = 0;

  for (const incident of placed.slice(max)) {
    const sector = incident.extract?.sector ?? "";
    hiddenBySector.set(sector, (hiddenBySector.get(sector) ?? 0) + 1);
    totalHidden += 1;
  }

  return { visible, hiddenBySector, totalHidden };
}

/* -------------------------------------------------------------------------- */
/*  Trazado estático del plano                                                */
/* -------------------------------------------------------------------------- */

/** Perímetro del recinto (valla). */
export const FENCE = { x: 296, y: 52, w: 712, h: 596, r: 14 };

/** Pasillos de circulación (Pasillo Norte / Pasillo Sur). */
export const CORRIDORS = [
  { d: "M 320 172 L 968 172", label: "PASILLO NORTE", lx: 500, ly: 176 },
  { d: "M 320 466 L 968 466", label: "PASILLO SUR", lx: 500, ly: 470 },
];

/** Eje vertical de circulación entre pasillos. */
export const WALKWAY_MAIN = "M 706 96 L 706 620";

/**
 * INFRAESTRUCTURA DEL RECINTO — NO son sectores.
 *
 * Distinción que no se debe romper: los 11 sectores de ZONES son los que produce
 * el extractor (`sector` → coordenadas de incidente). Puertas, salidas de
 * emergencia, PMA y punto de encuentro son elementos DIBUJADOS: no se añaden al
 * enum, no se añaden al extractor y no reciben marcadores de incidente.
 */
export type Gate = {
  id: string;
  label: string;
  sub?: string;
  x: number;
  y: number;
  /** Orientación del rótulo respecto al punto. */
  side: "left" | "right" | "up" | "down";
  /** Desvío activo hacia otra puerta (como en la referencia). */
  diverted?: boolean;
};

export const GATES: Gate[] = [
  { id: "A", label: "PUERTA A", sub: "ACCESO NORTE", x: 984, y: 120, side: "left" },
  { id: "B", label: "PUERTA B", sub: "ACCESO ESTE", x: 984, y: 300, side: "left" },
  { id: "C", label: "PUERTA C", sub: "ACCESO SUR", x: 984, y: 560, side: "left", diverted: true },
  { id: "D", label: "PUERTA D", sub: "VEHÍCULOS", x: 296, y: 610, side: "right" },
  { id: "X", label: "BACKSTAGE", sub: "ARTISTAS", x: 984, y: 78, side: "left" },
];

/** Desvío activo: Puerta A → Puerta C (mismo patrón que la referencia). */
export const DIVERSION = {
  d: "M 1000 150 Q 1046 330 1000 545",
  label: "DESVÍO ACTIVO",
  lx: 1032,
  ly: 348,
};

export type EvacExit = {
  id: string;
  x: number;
  y: number;
  /** Dirección hacia la que apunta la salida (fuera del recinto). */
  dx: number;
  dy: number;
};

/** Salidas de emergencia señalizadas, una por lado (EVAC-N/S/E/O). */
export const EVAC_EXITS: EvacExit[] = [
  { id: "EVAC-N", x: 500, y: 52, dx: 0, dy: -1 },
  { id: "EVAC-S", x: 500, y: 648, dx: 0, dy: 1 },
  { id: "EVAC-E", x: 1008, y: 220, dx: 1, dy: 0 },
  { id: "EVAC-O", x: 296, y: 120, dx: -1, dy: 0 },
];

/** Ruta de evacuación señalizada que une las salidas con el eje central. */
export const EVAC_ROUTES = [
  "M 500 58 L 500 172",
  "M 500 644 L 500 466",
  "M 1000 220 L 706 220",
  "M 300 120 L 500 120 L 500 168",
];

export type MedicalPost = {
  id: string;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Estado operativo. Hoy es estático: la app no recibe telemetría de PMA. */
  status: "libre" | "ocupado";
  note?: string;
};

/**
 * PMA (Puestos Médicos Avanzados) y punto de encuentro.
 *
 * COMPLIANCE: `status` es un dato de INFRAESTRUCTURA de demostración, no un dato
 * clínico ni de personas. No se muestra ninguna categoría especial aquí.
 */
export const MEDICAL_POSTS: MedicalPost[] = [
  { id: "PMA-1", label: "PMA 1", x: 316, y: 80, w: 92, h: 74, status: "ocupado", note: "OCUPADO" },
  { id: "PMA-2", label: "PMA 2", x: 872, y: 372, w: 88, h: 66, status: "libre", note: "LIBRE" },
];

export const MEETING_POINT = {
  label: "PUNTO DE ENCUENTRO",
  x: 316,
  y: 560,
  w: 150,
  h: 44,
};

/** Viales de acceso para ambulancias hasta los PMA (borde + guiones). */
export const SERVICE_VIALS = [
  { id: "V-1", d: "M 262 117 L 316 117" },
  { id: "V-2", d: "M 706 340 L 760 405 L 872 405" },
];

/** Subdivisiones del área de público: foso y pista central. */
export const FOSO = { x: 470, y: 232, w: 34, h: 96, label: "FOSO" };
export const PISTA_CENTRAL = {
  x: 512,
  y: 232,
  w: 180,
  h: 96,
  label: "PISTA CENTRAL",
};
