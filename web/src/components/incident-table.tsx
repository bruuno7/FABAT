"use client";

import { useMemo, useState } from "react";
import type { BoardIncident } from "@/lib/board-types";
import { INCIDENT_TYPE_LABEL, type IncidentType } from "@/lib/contract";
import { TYPE_GLYPH, formatAge, formatTime } from "@/lib/present";
import { NO_LOCATION, zoneForSector } from "@/lib/venue";
import { StatusChip, TriageChip } from "./ui";

/**
 * Cola de incidentes priorizada, en tabla.
 *
 * PRESUPUESTO DE SATURACIÓN: por defecto se muestran `DEFAULT_ROWS` filas (8).
 * El resto NO se pinta: se accede con el botón "Ver todos". Es una decisión
 * deliberada de calma — la pantalla responde a ¿dónde / qué tan grave / tengo
 * recursos?, no a "listar todo".
 *
 * COMPLIANCE:
 *  - Tabla semántica real (<table>) con <caption> y scope en las cabeceras:
 *    es la representación accesible del mapa (el SVG es un diagrama).
 *  - Navegación con flechas sobre <tbody> con aria-activedescendant: una sola
 *    parada de tabulación, los atajos no chocan con controles internos.
 *  - Cada fila lleva chip de gravedad (color + forma + glifo + texto) y el
 *    glifo del tipo: nada depende del color (WCAG 1.4.1).
 *  - RGPD Art. 9: NO se muestra el reportante ni el perfil. Son categoría
 *    especial (menor/PMR): se ven en el detalle, no en la vista principal.
 */

export const DEFAULT_ROWS = 8;

/** Criterios de orden que el operador puede cambiar. */
type Order = "prioridad" | "reciente";

export function IncidentTable({
  incidents,
  selectedId,
  onSelect,
  listRef,
  now,
  className = "",
  emptyHint,
}: {
  incidents: BoardIncident[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  listRef?: React.Ref<HTMLTableSectionElement>;
  /** null en el primer render: evita desajustes de hidratación. */
  now: Date | null;
  className?: string;
  /** Mensaje alternativo cuando el filtro deja la cola vacía. */
  emptyHint?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [order, setOrder] = useState<Order>("prioridad");

  const ordered = useMemo(() => {
    const list = incidents.slice();
    if (order === "reciente") {
      list.sort((a, b) => b.reported_at.localeCompare(a.reported_at));
    }
    // "prioridad" ya viene ordenado por /api/board (prioridad MANDO desc).
    return list;
  }, [incidents, order]);

  const shown = expanded ? ordered : ordered.slice(0, DEFAULT_ROWS);
  const hiddenCount = ordered.length - shown.length;

  if (incidents.length === 0) {
    return (
      <p className={`p-4 text-t2 text-muted ${className}`}>
        {emptyHint ??
          "Sin avisos. Abre «Preparación» para cargar el día 1 o el día 2."}
      </p>
    );
  }

  return (
    <div className={`flex min-h-0 flex-col ${className}`}>
      <div className="flex shrink-0 items-center gap-2 px-4 pt-1 pb-2">
        <label className="flex items-center gap-1.5 text-t1 text-muted">
          Ordenar por
          <select
            value={order}
            onChange={(e) => setOrder(e.target.value as Order)}
            className="field w-auto py-0.5 text-t1"
          >
            <option value="prioridad">Prioridad MANDO</option>
            <option value="reciente">Más reciente</option>
          </select>
        </label>

        <p className="ml-auto text-t1 text-muted">
          {shown.length} de {ordered.length}
        </p>        {hiddenCount > 0 && (
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setExpanded(true)}
          >
            Ver todos (+{hiddenCount})
          </button>
        )}
        {expanded && ordered.length > DEFAULT_ROWS && (
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setExpanded(false)}
          >
            Ver menos
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto scroll-thin">
        {/*
          PATRÓN ARIA: `role="grid"` sobre la tabla, con `tabIndex` y
          `aria-activedescendant` en el propio grid. Es el patrón del APG para
          tablas navegables con teclado: una sola parada de tabulación y las
          flechas mueven la fila activa sin robar el foco a los controles.
          (`aria-activedescendant` NO es válido sobre `tbody`, por eso va aquí.)
        */}
        <table
          className="tbl"
          role="grid"
          tabIndex={0}
          aria-activedescendant={selectedId ? `row-${selectedId}` : undefined}
          aria-label="Cola priorizada de incidentes"
        >
          <caption className="sr-only">
            Misma información que el plano, en orden de prioridad MANDO. Usa las
            flechas arriba y abajo para recorrer las filas.
          </caption>
          <thead>
            <tr role="row">
              <th role="columnheader" scope="col" aria-colindex={1} className="w-[7.5rem]">
                Gravedad
              </th>
              <th role="columnheader" scope="col" aria-colindex={2}>
                Tipo
              </th>
              <th role="columnheader" scope="col" aria-colindex={3}>
                Sector
              </th>
              <th role="columnheader" scope="col" aria-colindex={4} className="w-[7rem]">
                Estado
              </th>
              <th
                role="columnheader"
                scope="col"
                aria-colindex={5}
                className="w-[4.5rem] text-right"
              >
                Hora
              </th>
            </tr>
          </thead>
          <tbody ref={listRef}>
            {shown.map((incident) => (
              <Row
                key={incident.correlation_id}
                incident={incident}
                selected={incident.correlation_id === selectedId}
                onSelect={onSelect}
                now={now}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Row({
  incident,
  selected,
  onSelect,
  now,
}: {
  incident: BoardIncident;
  selected: boolean;
  onSelect: (id: string) => void;
  now: Date | null;
}) {
  const e = incident.extract ?? {};
  const type = (e.incident_type ?? "otro") as IncidentType;
  const placed = zoneForSector(e.sector) !== null;

  return (
    <tr
      id={`row-${incident.correlation_id}`}
      role="row"
      aria-selected={selected}
      aria-rowindex={1}
      onClick={() => onSelect(incident.correlation_id)}
      title={e.summary ?? incident.text ?? ""}
    >
      <td role="gridcell" className="w-[7.5rem]">
        <TriageChip color={e.triage_color ?? "desconocido"} />
      </td>
      <td role="gridcell">
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="text-t2">
            {TYPE_GLYPH[type]}
          </span>
          <span className="font-medium text-ink">
            {INCIDENT_TYPE_LABEL[type]}
          </span>
        </span>
      </td>
      <td role="gridcell">
        {placed ? (
          <span className="text-ink-2">{e.sector}</span>
        ) : (
          <span className="text-muted" title={NO_LOCATION}>
            {NO_LOCATION}
          </span>
        )}
      </td>
      <td role="gridcell" className="w-[7rem]">
        <StatusChip status={incident.status} />
      </td>
      <td role="gridcell" className="w-[4.5rem] text-right">
        <span className="mono text-t1 text-ink-2" title={formatTime(incident.reported_at)}>
          {now ? formatAge(incident.reported_at, now) : formatTime(incident.reported_at)}
        </span>
      </td>
    </tr>
  );
}
