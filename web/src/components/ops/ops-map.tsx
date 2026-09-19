"use client";

/**
 * Plano del recinto de «MANDO Ops».
 *
 * QUÉ SE CONSERVA DEL DISEÑO
 *   · el lienzo, las tarjetas de zona, el perímetro discontinuo, el foso, los PMA
 *     y la píldora «LIVE» con los botones flotantes.
 *
 * QUÉ CAMBIA (y por qué)
 *   · Las zonas son los 11 SECTORES REALES del contrato, no los rótulos
 *     decorativos del mock («TECH TENT», «PLAZA CENTRAL»). Así cada marcador cae
 *     en el sector que el extractor ha reconocido.
 *   · Los enlaces unidad → aviso son ASIGNACIONES REALES (`allocation`), no
 *     trayectorias animadas con una ETA inventada. Por eso no se pinta ningún
 *     «ETA 5s»: el backend no publica telemetría de posición ni de tiempo.
 *   · La capa «Carga» resalta los sectores CON AVISOS ABIERTOS (derivado de los
 *     reportes). No es una medición de aforo y así se rotula.
 */

import { useMemo } from "react";
import type { BoardIncident } from "@/lib/board-types";
import type { TriageColor } from "@/lib/contract";
import { TYPE_GLYPH } from "@/lib/present";
import {
  BUCKET_COLOR,
  OPS_DECOR,
  OPS_MAX_MARKERS,
  OPS_VIEWBOX,
  OPS_ZONES,
  type MapModel,
  type MapZone,
} from "@/lib/ops";

const ZONE_FILL: Record<MapZone["tone"], string> = {
  west: "#eff6ff",
  stage: "#e0e7ff",
  vip: "#e0e7ff",
  arena: "#ffffff",
  service: "#fffbeb",
  gate: "#e2e8f0",
};

const ZONE_STROKE: Record<MapZone["tone"], string> = {
  west: "#bfdbfe",
  stage: "#a5b4fc",
  vip: "#c7d2fe",
  arena: "#cbd5e1",
  service: "#fde68a",
  gate: "#94a3b8",
};

/** Rótulo del sector: el color NO va solo, lleva texto y recuento. */
const TRIAGE_RING: Record<TriageColor, string> = {
  negro: "#020617",
  rojo: "#ef4444",
  amarillo: "#f59e0b",
  verde: "#10b981",
  desconocido: "#94a3b8",
};

const SEVERITY_RANK: TriageColor[] = [
  "negro",
  "rojo",
  "amarillo",
  "verde",
  "desconocido",
];

function worstTriage(list: { triage: TriageColor }[]): TriageColor {
  let worst: TriageColor = "desconocido";
  let rank = SEVERITY_RANK.length;
  for (const item of list) {
    const idx = SEVERITY_RANK.indexOf(item.triage);
    if (idx >= 0 && idx < rank) {
      rank = idx;
      worst = item.triage;
    }
  }
  return worst;
}

function Marker({
  marker,
  selected,
  onSelect,
}: {
  marker: MapModel["markers"][number];
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const critical = marker.triage === "negro" || marker.triage === "rojo";
  const resolved = marker.status === "resuelto";
  const label = `${marker.ref} · ${marker.sector}. ${
    resolved ? "Resuelto" : marker.covered ? "Con recursos" : "Sin recursos"
  }${marker.unitIds.length > 0 ? `, asignado a ${marker.unitIds.join(" y ")}` : ""}.`;

  return (
    <g
      className="cursor-pointer"
      opacity={resolved ? 0.4 : 1}
      onClick={() => onSelect(marker.id)}
    >
      <title>{label}</title>
      {critical && !resolved && (
        <circle
          cx={marker.x}
          cy={marker.y}
          r={18}
          fill="none"
          stroke={TRIAGE_RING[marker.triage]}
          strokeDasharray="4,2"
          strokeWidth={2.5}
          opacity={0.7}
        />
      )}
      {selected && (
        <circle
          cx={marker.x}
          cy={marker.y}
          r={15.5}
          fill="none"
          stroke="#0058be"
          strokeWidth={2.5}
        />
      )}
      <circle
        cx={marker.x}
        cy={marker.y}
        r={12}
        fill={BUCKET_COLOR[marker.triage]}
        stroke="#ffffff"
        strokeWidth={2}
      />
      <text
        x={marker.x}
        y={marker.y + 0.5}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={11}
        fontWeight={700}
        fill="#ffffff"
        pointerEvents="none"
      >
        {TYPE_GLYPH[marker.type]}
      </text>
    </g>
  );
}

export function OpsMap({
  incidents,
  model,
  selectedId,
  onSelect,
  showLinks,
  onToggleLinks,
  showLoad,
  onToggleLoad,
  live,
  onToggleLive,
  totalUnits,
  busyUnits,
}: {
  incidents: BoardIncident[];
  model: MapModel;
  selectedId: string | null;
  onSelect: (id: string) => void;
  showLinks: boolean;
  onToggleLinks: () => void;
  showLoad: boolean;
  onToggleLoad: () => void;
  live: boolean;
  onToggleLive: () => void;
  totalUnits: number;
  busyUnits: number;
}) {
  const openBySector = useMemo(() => {
    const map = new Map<string, number>();
    for (const incident of incidents) {
      if (incident.status === "resuelto") continue;
      const sector = incident.extract?.sector;
      if (!sector) continue;
      map.set(sector, (map.get(sector) ?? 0) + 1);
    }
    return map;
  }, [incidents]);

  const markersBySector = useMemo(() => {
    const map = new Map<string, MapModel["markers"]>();
    for (const marker of model.markers) {
      const list = map.get(marker.sector);
      if (list) list.push(marker);
      else map.set(marker.sector, [marker]);
    }
    return map;
  }, [model.markers]);

  return (
    <div className="relative flex min-h-[460px] flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200/90 bg-white p-4 shadow-sm">
      <div className="z-10 mb-3 flex items-center justify-between">
        <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600">
          <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          <span className="font-mono text-[11px] tracking-tight text-slate-600">
            LIVE: {totalUnits} UNIDADES / {busyUnits} ACTIVOS
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onToggleLive}
            aria-pressed={live}
            title="Pausar o reanudar el refresco contra /api/board"
            className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-700 transition-colors hover:bg-slate-200"
          >
            <span
              className="material-symbols-outlined text-[15px] text-blue-600"
              aria-hidden="true"
            >
              {live ? "pause" : "play_arrow"}
            </span>
            {live ? "En vivo" : "Pausado"}
          </button>
          <button
            type="button"
            onClick={onToggleLinks}
            aria-pressed={showLinks}
            className={`rounded-lg border px-2.5 py-1 text-xs font-bold transition-colors ${
              showLinks
                ? "border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100"
                : "border-slate-200 bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            Trayectos
          </button>
          <button
            type="button"
            onClick={onToggleLoad}
            aria-pressed={showLoad}
            title="Resalta los sectores con avisos abiertos. Se deriva de los reportes: NO es una medición de aforo."
            className={`rounded-lg border px-2.5 py-1 text-xs font-bold transition-colors ${
              showLoad
                ? "border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100"
                : "border-slate-200 bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            Carga
          </button>
        </div>
      </div>

      <div className="relative flex flex-1 items-center justify-center overflow-hidden rounded-xl border border-slate-200/70 bg-[#f8fafc]">
        {/* DIAGRAMA DECORATIVO, igual que en la consola de `/`: la
            representación accesible es el manifiesto, que lista los mismos
            avisos en el mismo orden y abre la misma ficha. Si el SVG fuera
            `role="img"` con marcadores interactivos dentro, el lector de
            pantalla no podría alcanzarlos. */}
        <p className="sr-only">
          Plano esquemático del recinto con {model.markers.length} aviso(s)
          situados de {incidents.length}. La misma información, navegable con
          teclado, está en la tabla «Incident &amp; Fleet Manifest».
        </p>
        <svg
          id="ops-map-svg"
          viewBox={OPS_VIEWBOX}
          className="h-full w-full select-none"
          aria-hidden="true"
        >
          <defs>
            <marker
              id="ops-arrowhead"
              markerHeight="6"
              markerUnits="userSpaceOnUse"
              markerWidth="8"
              orient="auto"
              refX="7"
              refY="3"
            >
              <path d="M0,0 L8,3 L0,6 Z" fill="#334155" />
            </marker>
          </defs>

          <rect
            x={OPS_DECOR.perimeter.x}
            y={OPS_DECOR.perimeter.y}
            width={OPS_DECOR.perimeter.w}
            height={OPS_DECOR.perimeter.h}
            rx={14}
            fill="#ffffff"
            stroke="#cbd5e1"
            strokeDasharray="4,4"
            strokeWidth={1.5}
          />

          {/* Zonas = los 11 sectores reales del contrato */}
          {OPS_ZONES.map((zone) => {
            const open = openBySector.get(zone.sector) ?? 0;
            const here = markersBySector.get(zone.sector) ?? [];
            const worst = here.length > 0 ? worstTriage(here) : null;
            const tinted =
              showLoad &&
              open > 0 &&
              worst !== null &&
              (worst === "negro" || worst === "rojo");

            return (
              <g key={zone.sector}>
                <rect
                  x={zone.x}
                  y={zone.y}
                  width={zone.w}
                  height={zone.h}
                  rx={8}
                  fill={ZONE_FILL[zone.tone]}
                  stroke={ZONE_STROKE[zone.tone]}
                  strokeWidth={1}
                />
                {tinted && (
                  <rect
                    x={zone.x}
                    y={zone.y}
                    width={zone.w}
                    height={zone.h}
                    rx={8}
                    fill={BUCKET_COLOR[worst as TriageColor]}
                    fillOpacity={0.12}
                    stroke={BUCKET_COLOR[worst as TriageColor]}
                    strokeWidth={1.5}
                  />
                )}
                {zone.rotated ? (
                  <text
                    x={zone.x + zone.w / 2}
                    y={zone.y + zone.h / 2}
                    textAnchor="middle"
                    fontSize={9.5}
                    fontWeight={700}
                    fill="#475569"
                    transform={`rotate(-90 ${zone.x + zone.w / 2} ${zone.y + zone.h / 2})`}
                  >
                    {zone.label}
                  </text>
                ) : (
                  <>
                    <text
                      x={zone.x + 10}
                      y={zone.y + 18}
                      fontSize={10}
                      fontWeight={700}
                      fill="#334155"
                    >
                      {zone.label}
                      {open > 0 && (
                        <tspan fill="#64748b" fontSize={9} dx="6">
                          {open} abierto{open === 1 ? "" : "s"}
                        </tspan>
                      )}
                    </text>
                    {zone.sub && (
                      <text
                        x={zone.x + 10}
                        y={zone.y + 30}
                        fontSize={8.5}
                        fill="#64748b"
                      >
                        {zone.sub}
                      </text>
                    )}
                  </>
                )}
              </g>
            );
          })}

          {/* Elementos dibujados: no son sectores ni reciben marcadores */}
          <rect
            x={OPS_DECOR.foso.x}
            y={OPS_DECOR.foso.y}
            width={OPS_DECOR.foso.w}
            height={OPS_DECOR.foso.h}
            rx={4}
            fill="#fee2e2"
            stroke="#fca5a5"
            strokeWidth={1}
          />
          <text
            x={OPS_DECOR.foso.x + OPS_DECOR.foso.w / 2}
            y={OPS_DECOR.foso.y + 25}
            textAnchor="middle"
            fontSize={9.5}
            fontWeight={700}
            fill="#991b1b"
          >
            {OPS_DECOR.foso.label}
          </text>

          {OPS_DECOR.pma.map((post) => (
            <g key={post.id}>
              <rect
                x={post.x - 34}
                y={post.y - 17}
                width={68}
                height={34}
                rx={6}
                fill="#fef2f2"
                stroke="#ef4444"
                strokeWidth={1.2}
              />
              <text
                x={post.x}
                y={post.y - 2}
                textAnchor="middle"
                fontSize={9}
                fontWeight={700}
                fill="#991b1b"
              >
                {post.id}
              </text>
              <text
                x={post.x}
                y={post.y + 10}
                textAnchor="middle"
                fontSize={7.5}
                fontWeight={600}
                fill="#b91c1c"
              >
                {post.sub}
              </text>
            </g>
          ))}

          {/* Enlaces unidad → aviso: asignaciones reales */}
          {showLinks && (
            <g id="ops-links-layer">
              {model.links.map((link) => {
                const cx = (link.x1 + link.x2) / 2;
                const cy = (link.y1 + link.y2) / 2 - 24;
                const mx = (link.x1 + link.x2) / 2;
                const my = (link.y1 + link.y2) / 2 - 12;
                return (
                  <g key={`${link.unitId}-${link.incidentId}`}>
                    <path
                      className="ops-route-active"
                      d={`M ${link.x1} ${link.y1} Q ${cx} ${cy} ${link.x2} ${link.y2}`}
                      fill="none"
                      stroke={TRIAGE_RING[link.triage]}
                      strokeOpacity={0.55}
                      strokeWidth={2.5}
                      markerEnd="url(#ops-arrowhead)"
                    />
                    <g transform={`translate(${mx}, ${my})`}>
                      <rect
                        x={-38}
                        y={-9}
                        width={76}
                        height={18}
                        rx={4}
                        fill="#ffffff"
                        stroke={TRIAGE_RING[link.triage]}
                        strokeWidth={1}
                      />
                      <text
                        x={0}
                        y={3}
                        textAnchor="middle"
                        fontSize={8.5}
                        fontWeight={700}
                        fill="#0f172a"
                      >
                        {link.unitId} → {link.ref}
                      </text>
                    </g>
                  </g>
                );
              })}
            </g>
          )}

          {/* Marcadores de aviso */}
          {model.markers.map((marker) => (
            <Marker
              key={marker.id}
              marker={marker}
              selected={marker.id === selectedId}
              onSelect={onSelect}
            />
          ))}
        </svg>

        {/* Pulso del plan: datos reales de asignación */}
        <div className="absolute bottom-3 left-3 z-10 w-[230px] rounded-xl border border-slate-200/80 bg-white/90 p-3 text-slate-800 shadow-sm backdrop-blur-md">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[10px] font-bold tracking-wider text-slate-500 uppercase">
              Pulso del plan
            </span>
            <span
              aria-hidden="true"
              className={`h-2 w-2 rounded-full ${
                model.unplaced.length > 0 ? "bg-amber-500" : "bg-emerald-500"
              }`}
            />
          </div>
          <PulseRow
            label="Avisos situados"
            value={`${model.markers.length}`}
            total={model.markers.length + model.hidden + model.unplaced.length}
            barClass="bg-slate-700"
          />
          <PulseRow
            label="Fuera del presupuesto"
            value={`${model.hidden}`}
            total={model.markers.length + model.hidden + model.unplaced.length}
            barClass="bg-slate-300"
          />
          <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-2 text-[10px] text-slate-400">
            <span>Sin sector reconocible:</span>
            <span className="font-semibold text-slate-700">
              {model.unplaced.length} aviso(s)
            </span>
          </div>
          <p className="mt-1 text-[10px] leading-snug text-slate-400">
            Presupuesto de {OPS_MAX_MARKERS} marcadores. El resto sigue en el
            manifiesto.
          </p>
        </div>
      </div>
    </div>
  );
}

function PulseRow({
  label,
  value,
  total,
  barClass,
}: {
  label: string;
  value: string;
  total: number;
  barClass: string;
}) {
  const pct = total === 0 ? 0 : Math.round((Number(value) / total) * 100);
  return (
    <div className="mb-2">
      <div className="mb-1 flex items-center justify-between text-[11px] text-slate-600">
        <span className="font-medium">{label}</span>
        <span className="font-semibold text-slate-800">{value}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barClass}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
