"use client";

import { useMemo, useState } from "react";
import type { BoardIncident } from "@/lib/board-types";
import {
  INCIDENT_TYPE_LABEL,
  TRIAGE_LABEL,
  type IncidentType,
  type TriageColor,
} from "@/lib/contract";
import { TRIAGE_GLYPH, TYPE_GLYPH } from "@/lib/present";
import {
  CORRIDORS,
  DIVERSION,
  EVAC_EXITS,
  EVAC_ROUTES,
  FENCE,
  FOSO,
  GATES,
  MARKER_R,
  MAX_VISIBLE_MARKERS,
  MEDICAL_POSTS,
  MEETING_POINT,
  PISTA_CENTRAL,
  SERVICE_VIALS,
  VENUE_VIEWBOX,
  WALKWAY_MAIN,
  ZONES,
  markerSlots,
  selectVisibleMarkers,
  worstTriage,
  type SectorGroup,
  type Zone,
} from "@/lib/venue";

/* ============================================================================
 * CODIFICACIÓN DOBLE (aprobada — no cambiar sin actualizar la leyenda)
 *
 *   COLOR + RELLENO del marcador  =  GRAVEDAD / TRIAGE
 *   GLIFO dentro del marcador     =  TIPO DE INCIDENTE
 *
 * El tipo NO usa color a propósito: el color está reservado a la gravedad, que
 * es lo que decide a quién se atiende antes. Dos escalas de color compitiendo en
 * el mismo lienzo rompen la lectura de prioridad de un vistazo.
 *
 * DÓNDE SE CAMBIA:
 *   · colores de triage  → tokens --color-triage-* en src/app/globals.css
 *   · glifos de tipo     → TYPE_GLYPH en src/lib/present.ts
 *   · geometría y zonas  → src/lib/venue.ts
 *
 * SECTORES vs INFRAESTRUCTURA (distinción que NO se debe romper):
 *   · ZONES = los 11 sectores del repo. Reciben los marcadores de incidente.
 *   · GATES / EVAC_EXITS / MEDICAL_POSTS / MEETING_POINT / viales = elementos
 *     DIBUJADOS de infraestructura. No están en el enum de dominio, no los
 *     produce el extractor y NUNCA reciben un marcador de incidente.
 *
 * PRESUPUESTO: máximo MAX_VISIBLE_MARKERS marcadores; el resto se cuenta como
 * "+K" en su sector y sigue accesible en la tabla.
 * ========================================================================== */

const TRIAGE_FILL: Record<TriageColor, string> = {
  negro: "var(--color-triage-negro)",
  rojo: "var(--color-triage-rojo)",
  amarillo: "var(--color-triage-amarillo)",
  verde: "var(--color-triage-verde)",
  desconocido: "url(#mando-hatch)", // rayado = "sin dato", no un color más
};

const TRIAGE_INK: Record<TriageColor, string> = {
  negro: "var(--color-triage-negro-ink)",
  rojo: "var(--color-triage-rojo-ink)",
  amarillo: "var(--color-triage-amarillo-ink)",
  verde: "var(--color-triage-verde-ink)",
  desconocido: "var(--color-triage-desconocido-ink)",
};

/** Solo el riesgo vital tiñe su sector: color reservado a lo que significa. */
const TINTED: TriageColor[] = ["negro", "rojo"];

/** Glifos de infraestructura, con presentación de texto forzada. */
const MEDICAL_GLYPH = "✚\uFE0E";
const MEETING_GLYPH = "⚑\uFE0E";
const EVAC_GLYPH = "▲\uFE0E";

function asTriage(value: string | undefined): TriageColor {
  return (value ?? "desconocido") as TriageColor;
}

/* -------------------------------------------------------------------------- */
/*  Marcador                                                                   */
/* -------------------------------------------------------------------------- */

function Marker({
  incident,
  x,
  y,
  selected,
  onSelect,
}: {
  incident: BoardIncident;
  x: number;
  y: number;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const triage = asTriage(incident.extract?.triage_color);
  const type = (incident.extract?.incident_type ?? "otro") as IncidentType;
  const sector = incident.extract?.sector ?? "sin sector";
  const resolved = incident.status === "resuelto";

  // Texto alternativo completo: gravedad + tipo + sector + estado. Es la versión
  // no visual del marcador (COMPLIANCE WCAG 1.1.1).
  const label = `${TRIAGE_LABEL[triage]}, ${INCIDENT_TYPE_LABEL[type]} en ${sector}. ${
    resolved ? "Resuelto" : incident.covered ? "Con recursos" : "Sin recursos"
  }.`;

  return (
    <g className="marker" opacity={resolved ? 0.45 : 1}>
      <title>{label}</title>
      {/* Área de impacto ampliada a 34px sin cambiar el dibujo: 24px es el
          mínimo legal pero incómodo con el ratón en una sala de control. */}
      <circle cx={x} cy={y} r={MARKER_R + 5} className="marker-halo" />
      {selected && (
        <circle cx={x} cy={y} r={MARKER_R + 4} className="marker-selected" />
      )}
      {/* Anillo OSCURO: sin él, ámbar (1.91:1) y gris se pierden sobre el mapa.
          El anillo es neutro: no compite con la escala de gravedad. */}
      <circle
        cx={x}
        cy={y}
        r={MARKER_R}
        className="marker-body"
        fill={TRIAGE_FILL[triage]}
      />
      <text x={x} y={y + 0.5} className="marker-glyph glyph" fill={TRIAGE_INK[triage]}>
        {TYPE_GLYPH[type]}
      </text>
      <rect
        x={x - MARKER_R}
        y={y - MARKER_R}
        width={MARKER_R * 2}
        height={MARKER_R * 2}
        fill="transparent"
        onClick={(ev) => {
          ev.stopPropagation();
          onSelect(incident.correlation_id);
        }}
      />
    </g>
  );
}

/* -------------------------------------------------------------------------- */
/*  Rótulo de sector                                                           */
/* -------------------------------------------------------------------------- */

function ZoneShape({
  zone,
  group,
  openCount,
  hidden,
}: {
  zone: Zone;
  group: SectorGroup | null;
  /** Abiertos en el sector contando TODOS los avisos, no solo los dibujados. */
  openCount: number;
  hidden: number;
}) {
  const worst = group ? asTriage(worstTriage(group.incidents)) : null;
  const tinted = openCount > 0 && worst !== null && TINTED.includes(worst);
  const outside = zone.kind === "outside" || zone.kind === "camp";
  const rx = zone.kind === "stage" ? 10 : 8;

  return (
    <g>
      <rect
        x={zone.x}
        y={zone.y}
        width={zone.w}
        height={zone.h}
        rx={rx}
        className={`map-zone${outside ? " map-zone-out" : ""}`}
      />
      {/* Tinte SOLO para vital/emergencia. Es un realce, nunca la única señal:
          van el rótulo del sector, el recuento y el chip de gravedad. */}
      {tinted && (
        <rect
          x={zone.x}
          y={zone.y}
          width={zone.w}
          height={zone.h}
          rx={rx}
          fill={TRIAGE_FILL[worst as TriageColor]}
          fillOpacity={0.1}
          stroke={TRIAGE_FILL[worst as TriageColor]}
          strokeWidth={1.5}
        />
      )}
      <text x={zone.x + 10} y={zone.y + 19} className="map-zone-label">
        {zone.label}
        {openCount > 0 && (
          <tspan className="map-zone-sub" dx="6">
            {openCount} abierto{openCount === 1 ? "" : "s"}
            {hidden > 0 ? ` (+${hidden})` : ""}
          </tspan>
        )}
      </text>
    </g>
  );
}

/* -------------------------------------------------------------------------- */
/*  Infraestructura dibujada                                                   */
/* -------------------------------------------------------------------------- */

function GateShape({ gate }: { gate: (typeof GATES)[number] }) {
  const left = gate.side === "left";
  return (
    <g>
      <circle
        cx={gate.x}
        cy={gate.y}
        r={4}
        className="map-infra"
        strokeWidth={2}
      />
      <text
        x={gate.x + (left ? -10 : 10)}
        y={gate.y - 1}
        className="map-infra-label"
        textAnchor={left ? "end" : "start"}
      >
        {gate.label}
      </text>
      {gate.sub && (
        <text
          x={gate.x + (left ? -10 : 10)}
          y={gate.y + 10}
          className="map-infra-sub"
          textAnchor={left ? "end" : "start"}
        >
          {gate.sub}
        </text>
      )}
    </g>
  );
}

function EvacExitShape({ exit }: { exit: (typeof EVAC_EXITS)[number] }) {
  // Flecha que apunta hacia fuera del recinto: canal de forma inequívoco.
  const len = 15;
  const tipX = exit.x + exit.dx * len;
  const tipY = exit.y + exit.dy * len;
  const perpX = -exit.dy;
  const perpY = exit.dx;

  return (
    <g>
      <path
        d={`M ${exit.x - perpX * 7} ${exit.y - perpY * 7} L ${tipX} ${tipY} L ${
          exit.x + perpX * 7
        } ${exit.y + perpY * 7} Z`}
        fill="var(--color-evac)"
      />
      <text
        x={exit.x + perpX * 16 + exit.dx * 4}
        y={exit.y + perpY * 16 + exit.dy * 4 + 3}
        className="map-evac-label"
        textAnchor="middle"
      >
        {exit.id}
      </text>
    </g>
  );
}

function MedicalPostShape({ post }: { post: (typeof MEDICAL_POSTS)[number] }) {
  const busy = post.status === "ocupado";
  return (
    <g>
      <rect
        x={post.x}
        y={post.y}
        width={post.w}
        height={post.h}
        rx={8}
        className={busy ? "map-infra-busy" : "map-infra-open"}
      />
      {/* Glifo + rótulo + estado textual: el estado no depende del color. */}
      <text
        x={post.x + 8}
        y={post.y + 17}
        className="map-infra-label"
      >
        {post.label}
      </text>
      <text x={post.x + 9} y={post.y + 30} className="map-infra-glyph glyph">
        {MEDICAL_GLYPH}
      </text>
      <text x={post.x + 24} y={post.y + 30} className="map-infra-sub">
        {busy ? "OCUPADO" : "LIBRE"}
      </text>
    </g>
  );
}

/* -------------------------------------------------------------------------- */
/*  Mapa                                                                       */
/* -------------------------------------------------------------------------- */

export function VenueMap({
  incidents,
  selectedId,
  onSelect,
  className = "",
}: {
  incidents: BoardIncident[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  className?: string;
}) {
  const [zoom, setZoom] = useState(1);
  const [flowLayer, setFlowLayer] = useState(true);

  const budget = useMemo(() => selectVisibleMarkers(incidents), [incidents]);

  const groups = useMemo(() => {
    const bySector = new Map<string, BoardIncident[]>();
    for (const incident of budget.visible) {
      const sector = incident.extract?.sector;
      if (!sector) continue;
      const list = bySector.get(sector);
      if (list) list.push(incident);
      else bySector.set(sector, [incident]);
    }
    const out = new Map<string, SectorGroup>();
    for (const zone of ZONES) {
      const list = bySector.get(zone.sector);
      if (!list) continue;
      list.sort((a, b) => a.correlation_id.localeCompare(b.correlation_id));
      out.set(zone.sector, {
        zone,
        incidents: list,
        openCount: list.filter((i) => i.status !== "resuelto").length,
      });
    }
    return out;
  }, [budget.visible]);

  const openBySector = useMemo(() => {
    const m = new Map<string, number>();
    for (const incident of incidents) {
      const sector = incident.extract?.sector;
      if (!sector || incident.status === "resuelto") continue;
      m.set(sector, (m.get(sector) ?? 0) + 1);
    }
    return m;
  }, [incidents]);

  const cx = 520;
  const cy = 350;
  const transform = `translate(${cx * (1 - zoom)} ${cy * (1 - zoom)}) scale(${zoom})`;

  return (
    <div
      className={`map-shell ${className}`}
      /* El SVG es un DIAGRAMA: la representación accesible con teclado y lector
         de pantalla es la tabla de incidentes, que lista lo mismo en el mismo
         orden de prioridad. La infraestructura se describe en la leyenda. */
      role="img"
      aria-label={`Plano esquemático del recinto: ${budget.visible.length} aviso(s) señalados de ${incidents.length}, con ${ZONES.length} sectores rotulados, ${GATES.length} puertas, ${EVAC_EXITS.length} salidas de emergencia y ${MEDICAL_POSTS.length} puestos médicos. El detalle se navega en la tabla de incidentes.`}
    >
      <svg
        viewBox={VENUE_VIEWBOX}
        className="h-full w-full"
        preserveAspectRatio="xMidYMid meet"
        aria-hidden="true"
      >
        <defs>
          <pattern
            id="mando-hatch"
            width="6"
            height="6"
            patternTransform="rotate(45)"
            patternUnits="userSpaceOnUse"
          >
            <rect width="6" height="6" fill="#dfe6f2" />
            <rect width="3" height="6" fill="#c9d3e4" />
          </pattern>
          <marker
            id="mando-arrow"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="5"
            orient="auto-start-reverse"
            viewBox="0 0 10 10"
          >
            <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="var(--color-map-vial)" />
          </marker>
        </defs>

        <g transform={transform}>
          <rect x={0} y={0} width={1040} height={700} className="map-zone-out" />

          {/* Valla perimetral */}
          <rect
            x={FENCE.x}
            y={FENCE.y}
            width={FENCE.w}
            height={FENCE.h}
            rx={FENCE.r}
            fill="none"
            stroke="var(--color-map-fence)"
            strokeWidth={2.5}
            strokeDasharray="10 6"
          />

          {/* Pasillos de circulación */}
          {CORRIDORS.map((c) => (
            <path key={c.label} d={c.d} className="map-corridor" />
          ))}
          <path d={WALKWAY_MAIN} className="map-corridor" />
          {CORRIDORS.map((c) => (
            <text
              key={`${c.label}-t`}
              x={c.lx}
              y={c.ly}
              className="map-corridor-label"
              textAnchor="middle"
            >
              {c.label}
            </text>
          ))}

          {/* Viales de ambulancia hasta los PMA */}
          {SERVICE_VIALS.map((v) => (
            <path
              key={v.id}
              d={v.d}
              className="map-vial"
              markerEnd="url(#mando-arrow)"
            />
          ))}

          {/* Rutas de evacuación */}
          {EVAC_ROUTES.map((d, i) => (
            <path key={i} d={d} className="map-evac" />
          ))}

          {/* Todas las zonas se dibujan siempre (con o sin avisos): el plano es
              fijo y así no hay saltos de layout cuando entra un incidente. */}
          {ZONES.map((zone) => (
            <ZoneShape
              key={zone.sector}
              zone={zone}
              group={groups.get(zone.sector) ?? null}
              openCount={flowLayer ? (openBySector.get(zone.sector) ?? 0) : 0}
              hidden={budget.hiddenBySector.get(zone.sector) ?? 0}
            />
          ))}

          {/* Subdivisiones del área de público */}
          <g>
            <rect
              x={FOSO.x}
              y={FOSO.y}
              width={FOSO.w}
              height={FOSO.h}
              rx={6}
              fill="none"
              stroke="var(--color-map-fence)"
              strokeWidth={1}
            />
            <text
              x={FOSO.x + FOSO.w / 2}
              y={FOSO.y + FOSO.h / 2}
              className="map-zone-sub"
              textAnchor="middle"
              transform={`rotate(-90 ${FOSO.x + FOSO.w / 2} ${FOSO.y + FOSO.h / 2})`}
            >
              {FOSO.label}
            </text>
            <rect
              x={PISTA_CENTRAL.x}
              y={PISTA_CENTRAL.y}
              width={PISTA_CENTRAL.w}
              height={PISTA_CENTRAL.h}
              rx={10}
              fill="none"
              stroke="var(--color-map-water)"
              strokeWidth={1.5}
              strokeDasharray="6 4"
            />
            <text
              x={PISTA_CENTRAL.x + PISTA_CENTRAL.w / 2}
              y={PISTA_CENTRAL.y + PISTA_CENTRAL.h / 2}
              className="map-zone-sub"
              textAnchor="middle"
            >
              {PISTA_CENTRAL.label}
            </text>
          </g>

          {/* Marcadores de incidente (dentro del presupuesto) */}
          {[...groups.values()].map((group) => {
            const slots = markerSlots(group.zone, group.incidents.length);
            return (
              <g key={group.zone.sector}>
                {group.incidents.map((incident, i) =>
                  slots[i] ? (
                    <Marker
                      key={incident.correlation_id}
                      incident={incident}
                      x={slots[i].x}
                      y={slots[i].y}
                      selected={incident.correlation_id === selectedId}
                      onSelect={onSelect}
                    />
                  ) : null,
                )}
              </g>
            );
          })}

          {/* INFRAESTRUCTURA (dibujada, nunca recibe incidentes) */}
          {MEDICAL_POSTS.map((post) => (
            <MedicalPostShape key={post.id} post={post} />
          ))}

          <g>
            <rect
              x={MEETING_POINT.x}
              y={MEETING_POINT.y}
              width={MEETING_POINT.w}
              height={MEETING_POINT.h}
              rx={8}
              className="map-infra"
              strokeDasharray="5 3"
            />
            <text
              x={MEETING_POINT.x + MEETING_POINT.w / 2}
              y={MEETING_POINT.y + 20}
              className="map-infra-sub"
              textAnchor="middle"
            >
              {MEETING_POINT.label}
            </text>
            <text
              x={MEETING_POINT.x + MEETING_POINT.w / 2}
              y={MEETING_POINT.y + 33}
              className="map-infra-glyph glyph"
              textAnchor="middle"
            >
              {MEETING_GLYPH}
            </text>
          </g>

          {GATES.map((gate) => (
            <GateShape key={gate.id} gate={gate} />
          ))}

          {/* Desvío activo Puerta A → Puerta C */}
          <path d={DIVERSION.d} className="map-vial" />
          <text
            x={DIVERSION.lx}
            y={DIVERSION.ly}
            className="map-infra-sub"
            fill="var(--color-map-vial)"
            textAnchor="middle"
            transform={`rotate(90 ${DIVERSION.lx} ${DIVERSION.ly})`}
          >
            {DIVERSION.label}
          </text>

          {EVAC_EXITS.map((exit) => (
            <EvacExitShape key={exit.id} exit={exit} />
          ))}
        </g>
      </svg>

      {/* Zoom + capa de flujo (presentación, no dato nuevo) */}
      <div className="absolute top-3 right-3 flex flex-col gap-1">
        <button
          type="button"
          className="btn btn-icon floating-card"
          onClick={() => setZoom((z) => Math.min(2.4, +(z + 0.35).toFixed(2)))}
          aria-label="Ampliar el mapa"
        >
          +
        </button>
        <button
          type="button"
          className="btn btn-icon floating-card"
          onClick={() => setZoom((z) => Math.max(1, +(z - 0.35).toFixed(2)))}
          aria-label="Reducir el mapa"
        >
          −
        </button>
        <button
          type="button"
          className="btn btn-icon floating-card"
          onClick={() => setZoom(1)}
          aria-label="Ajustar el mapa a la pantalla"
        >
          ⤢
        </button>
      </div>

      <button
        type="button"
        aria-pressed={flowLayer}
        onClick={() => setFlowLayer((v) => !v)}
        className="btn btn-sm floating-card absolute top-3 left-3"
        title="Resalta los sectores con avisos abiertos. Se deriva de los reportes: NO es una medición de aforo."
      >
        <span aria-hidden="true" className="glyph">{flowLayer ? "◉" : "○"}</span>
        Capa de flujo
      </button>

      <MapLegendInline />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Leyenda (en dos filas: gravedad / tipo + infraestructura)                  */
/* -------------------------------------------------------------------------- */

export const LEGEND_TRIAGE: TriageColor[] = [
  "negro",
  "rojo",
  "amarillo",
  "verde",
  "desconocido",
];

export const LEGEND_TYPES: IncidentType[] = [
  "medica",
  "aglomeracion",
  "agresion",
  "clima",
  "infra",
  "otro",
];

export { MAX_VISIBLE_MARKERS };

function MapLegendInline() {
  return (
    <div className="floating-card absolute bottom-3 left-3 max-w-[min(100%-14rem,44rem)] px-2.5 py-2">
      {/* Fila 1: gravedad = relleno */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="card-title">Gravedad</span>
        {LEGEND_TRIAGE.map((t) => (
          <span key={t} className={`tri tri-${t}`}>
            <span aria-hidden="true" className="tri-mark glyph">
              {TRIAGE_GLYPH[t]}
            </span>
            {TRIAGE_LABEL[t]}
          </span>
        ))}
      </div>

      {/* Fila 2: tipo = glifo, e infraestructura dibujada */}
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span className="card-title">Tipo</span>
        {LEGEND_TYPES.map((t) => (
          <span
            key={t}
            className="inline-flex items-center gap-1 text-t1 text-ink-2"
          >
            <span aria-hidden="true" className="glyph">
              {TYPE_GLYPH[t]}
            </span>
            {INCIDENT_TYPE_LABEL[t]}
          </span>
        ))}

        <span className="mx-0.5 h-3.5 w-px bg-outline-soft" aria-hidden="true" />

        <span className="inline-flex items-center gap-1 text-t1 text-ink-2">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-full border border-outline"
          />
          Puerta
        </span>
        <span className="inline-flex items-center gap-1 text-t1 text-ink-2">
          <span aria-hidden="true" style={{ color: "var(--color-evac)" }}>
            {EVAC_GLYPH}
          </span>
          Salida emergencia
        </span>
        <span className="inline-flex items-center gap-1 text-t1 text-ink-2">
          <span aria-hidden="true" className="glyph">
            {MEDICAL_GLYPH}
          </span>
          PMA
        </span>
        <span className="inline-flex items-center gap-1 text-t1 text-ink-2">
          <span aria-hidden="true" style={{ color: "var(--color-map-vial)" }}>
            ┄
          </span>
          Vial ambulancia
        </span>
      </div>

      <p className="sr-only">
        El relleno de cada marcador indica la gravedad de triage
        ({LEGEND_TRIAGE.map((t) => `${TRIAGE_LABEL[t]}`).join(", ")}). El glifo
        interior indica el tipo de incidente. La capa de flujo resalta los sectores
        con avisos abiertos y se deriva de los reportes, no de una medición de
        aforo.
      </p>
    </div>
  );
}
