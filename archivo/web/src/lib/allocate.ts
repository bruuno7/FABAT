/**
 * Asignación determinista de recursos. Cero LLM: reglas explícitas.
 *
 * Es el corazón de MANDO: HappyRobot habla; aquí se decide quién va a dónde y,
 * sobre todo, se detecta cuándo el plan ha dejado de valer (demanda > capacidad).
 */
import type { IncidentRow, IncidentType, PerfilColor, TriageColor } from "./contract";

export type ResourceKind = "medico" | "seguridad" | "apoyo" | "coordinacion";

export const RESOURCE_LABEL: Record<ResourceKind, string> = {
  medico: "Equipos médicos",
  seguridad: "Seguridad",
  apoyo: "Apoyo / logística",
  coordinacion: "Coordinación",
};

export const RESOURCE_ORDER: ResourceKind[] = [
  "medico",
  "seguridad",
  "apoyo",
  "coordinacion",
];

/** Capacidad por defecto del recinto (dotación demo). */
export const DEFAULT_CAPACITY: Record<ResourceKind, number> = {
  medico: 2,
  seguridad: 3,
  apoyo: 2,
  coordinacion: 1,
};

const TRIAGE_WEIGHT: Record<TriageColor, number> = {
  negro: 100,
  rojo: 80,
  amarillo: 50,
  desconocido: 30,
  verde: 10,
};

const PERFIL_BONUS: Partial<Record<PerfilColor, number>> = {
  menor: 6,
  pmr: 5,
  vip: 0,
};

/** Qué recursos exige un incidente según tipo, gravedad y perfil. */
export function requiredResources(
  row: Pick<IncidentRow, "extract">,
): ResourceKind[] {
  const e = row.extract ?? {};
  const type: IncidentType = e.incident_type ?? "otro";
  const severity = e.severity ?? 3;
  const perfil = e.perfil_color;
  const out = new Set<ResourceKind>();

  switch (type) {
    case "medica":
      out.add("medico");
      if (perfil === "pmr" || perfil === "menor") out.add("apoyo");
      break;
    case "agresion":
      out.add("seguridad");
      if (severity >= 4) out.add("medico");
      break;
    case "aglomeracion":
      out.add("seguridad");
      out.add("coordinacion");
      break;
    case "clima":
      out.add("apoyo");
      if (severity >= 4) out.add("coordinacion");
      break;
    case "infra":
      out.add("apoyo");
      if (severity >= 4) out.add("seguridad");
      break;
    default:
      out.add("apoyo");
  }

  return RESOURCE_ORDER.filter((k) => out.has(k));
}

/** Prioridad de cola: triage manda, severidad ajusta, perfil modula. */
export function priorityScore(row: Pick<IncidentRow, "extract">): number {
  const e = row.extract ?? {};
  const triage: TriageColor = e.triage_color ?? "desconocido";
  const severity = e.severity ?? 3;
  const perfil = e.perfil_color ? (PERFIL_BONUS[e.perfil_color] ?? 0) : 0;
  return TRIAGE_WEIGHT[triage] + severity * 4 + perfil;
}

export type Assignment = {
  correlation_id: string;
  kinds: ResourceKind[];
  priority: number;
};

export type Overflow = {
  correlation_id: string;
  missing: ResourceKind[];
  priority: number;
};

export type Allocation = {
  assignments: Assignment[];
  overflow: Overflow[];
  remaining: Record<ResourceKind, number>;
  /** true cuando algún incidente abierto no puede ser cubierto. */
  broken: boolean;
  /** Firma estable del estado de saturación (para no repetir avisos). */
  signature: string;
};

/**
 * Reparte recursos en orden de prioridad. Un incidente se cubre solo si todos
 * los recursos que exige están disponibles; si no, va a `overflow`.
 */
export function allocate(
  rows: IncidentRow[],
  capacity: Record<ResourceKind, number> = DEFAULT_CAPACITY,
): Allocation {
  const open = rows.filter((r) => r.status !== "resuelto");
  const ordered = [...open].sort((a, b) => {
    const diff = priorityScore(b) - priorityScore(a);
    if (diff !== 0) return diff;
    return a.reported_at.localeCompare(b.reported_at);
  });

  const remaining: Record<ResourceKind, number> = { ...capacity };
  const assignments: Assignment[] = [];
  const overflow: Overflow[] = [];

  for (const row of ordered) {
    const kinds = requiredResources(row);
    const missing = kinds.filter((k) => remaining[k] <= 0);

    if (missing.length === 0) {
      for (const k of kinds) remaining[k] -= 1;
      assignments.push({
        correlation_id: row.correlation_id,
        kinds,
        priority: priorityScore(row),
      });
    } else {
      overflow.push({
        correlation_id: row.correlation_id,
        missing,
        priority: priorityScore(row),
      });
    }
  }

  const signature = overflow
    .map((o) => `${o.correlation_id}:${o.missing.join("+")}`)
    .sort()
    .join("|");

  return {
    assignments,
    overflow,
    remaining,
    broken: overflow.length > 0,
    signature,
  };
}

export function isCovered(
  allocation: Allocation,
  correlationId: string,
): boolean {
  return allocation.assignments.some((a) => a.correlation_id === correlationId);
}
