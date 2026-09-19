/**
 * Lecciones deterministas del recinto (día 1 -> día 2).
 *
 * No es "memoria del agente": es agregación explícita sobre los avisos ya vistos.
 * Si un patrón se repite, el plan del día siguiente se ajusta.
 */
import {
  INCIDENT_TYPE_LABEL,
  type IncidentRow,
  type IncidentType,
} from "./contract";
import { requiredResources, RESOURCE_LABEL } from "./allocate";

export type Lesson = {
  key: string;
  type: IncidentType;
  sector: string;
  count: number;
  resources: string[];
  text: string;
};

/** Patrones repetidos (tipo + sector). `minCount` = umbral para considerarlo patrón. */
export function lessonsFrom(rows: IncidentRow[], minCount = 2): Lesson[] {
  const groups = new Map<string, { type: IncidentType; sector: string; rows: IncidentRow[] }>();

  for (const row of rows) {
    const type = row.extract?.incident_type;
    const sector = row.extract?.sector;
    if (!type || !sector) continue;
    const key = `${type}|${sector}`;
    const g = groups.get(key);
    if (g) g.rows.push(row);
    else groups.set(key, { type, sector, rows: [row] });
  }

  const lessons: Lesson[] = [];
  for (const [key, g] of groups) {
    if (g.rows.length < minCount) continue;
    const kinds = new Set<string>();
    for (const r of g.rows) {
      for (const k of requiredResources(r)) kinds.add(RESOURCE_LABEL[k]);
    }
    const resources = [...kinds];
    lessons.push({
      key,
      type: g.type,
      sector: g.sector,
      count: g.rows.length,
      resources,
      text: `${g.rows.length} avisos de ${INCIDENT_TYPE_LABEL[g.type].toLowerCase()} en ${g.sector}. Preposicionar ${resources.join(" + ")} antes del siguiente pico.`,
    });
  }

  return lessons.sort((a, b) => b.count - a.count);
}
