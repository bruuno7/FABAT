/**
 * Catálogo de acciones para la tarjeta de decisión.
 * Determinista: la propuesta sale del tipo/triage/perfil, no de un LLM.
 * El humano confirma o edita (consejo/DECISION.md: tarjeta para lo grave).
 */
import type { IncidentRow } from "./contract";
import { requiredResources, RESOURCE_LABEL } from "./allocate";

const BY_TYPE: Record<string, string[]> = {
  medica: [
    "Desplegar equipo médico al sector",
    "Activar ruta de evacuación sanitaria",
    "Escalar a 112 / recurso externo",
  ],
  agresion: [
    "Enviar seguridad al sector",
    "Aislar la zona y cerrar accesos",
    "Retener testigos y avisar a coordinación",
  ],
  aglomeracion: [
    "Abrir vía alternativa y dispersar flujo",
    "Cerrar acceso al sector hasta bajar densidad",
    "Reforzar seguridad en el cuello de botella",
  ],
  clima: [
    "Activar protocolo de refugio en carpas",
    "Pausar actividad del escenario",
    "Reforzar drenaje y zonas de barro",
  ],
  infra: [
    "Enviar equipo técnico al sector",
    "Activar generador de respaldo",
    "Reencaminar flujo a zona sin incidencia",
  ],
  otro: ["Inspeccionar el sector", "Asignar equipo de apoyo"],
};

/** Obligatorias cuando hay riesgo vital: nunca se decide solo con el tipo. */
const CRITICAL: string[] = [
  "Escalar a 112 / recurso externo",
  "Parar el espectáculo y pedir silencio",
];

export function suggestActions(row: Pick<IncidentRow, "extract">): string[] {
  const e = row.extract ?? {};
  const type = e.incident_type ?? "otro";
  const out = new Set<string>();

  for (const action of BY_TYPE[type] ?? BY_TYPE.otro) out.add(action);

  if (e.perfil_color === "menor") {
    out.add("Activar protocolo de menor: localizar tutor");
  }
  if (e.perfil_color === "pmr") {
    out.add("Asegurar ruta accesible antes de mover");
  }
  if (e.triage_color === "negro" || e.triage_color === "rojo") {
    for (const a of CRITICAL) out.add(a);
  }

  return [...out];
}

/** Resumen corto de la propuesta de MANDO, sin ejecutar nada. */
export function proposeSummary(row: Pick<IncidentRow, "extract">): string {
  const kinds = requiredResources(row).map((k) => RESOURCE_LABEL[k]);
  const e = row.extract ?? {};
  const triage =
    e.triage_color && e.triage_color !== "desconocido"
      ? `triage ${e.triage_color}`
      : "sin triage";
  return `Propuesta: ${triage}, asignar ${kinds.join(" + ")}`;
}

export const DECIDED_BY_DEFAULT = "Mesa ResQval";
