"use client";

/**
 * Manifiesto inferior de «MANDO Ops».
 *
 * ADAPTACIÓN DECLARADA DE COLUMNAS. El mock pedía «ROUTE PROGRESS» y
 * «EFFICIENCY / ETA» con porcentajes y cuentas atrás por segundo. El backend no
 * publica progreso de ruta ni ETA (no hay telemetría de posición), así que esas
 * dos columnas se sustituyen por cantidades que SÍ existen:
 *   · ANTIGÜEDAD — minutos desde que entró el aviso, con barra comparativa
 *     (la barra es relativa al aviso más viejo de la tabla, no un SLA).
 *   · PRIORIDAD / FIRMA — la prioridad MANDO y si exige tarjeta humana.
 * Las filas, los recursos asignados, el sector y el estado son datos reales.
 */

import {
  BUCKET_COLOR,
  opsRef,
  statusChip,
  type ManifestRow,
} from "@/lib/ops";
import { INCIDENT_TYPE_LABEL, TRIAGE_LABEL } from "@/lib/contract";
import { TYPE_GLYPH } from "@/lib/present";

/** Zona horaria local, para no enseñar dos relojes distintos en la misma tabla. */
function localTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("es-ES", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function OpsManifestTable({
  rows,
  selectedId,
  onSelect,
  onInject,
  onExport,
  totalCount,
}: {
  rows: ManifestRow[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onInject: () => void;
  onExport: () => void;
  totalCount: number;
}) {
  return (
    <div className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm">
      <div className="flex flex-col items-start justify-between gap-3 border-b border-slate-100 pb-4 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-base font-extrabold tracking-tight text-slate-900">
            Incident &amp; Fleet Manifest
          </h2>
          <p className="mt-0.5 text-xs font-medium text-slate-500">
            Trazabilidad del turno y respuesta real asignada a cada aviso
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={onInject}
            className="flex items-center gap-1.5 rounded-xl bg-[#0d192e] px-4 py-2 text-xs font-bold text-white shadow-sm transition-all hover:bg-slate-800"
          >
            <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
              add
            </span>
            <span>Añadir aviso</span>
          </button>
          <button
            type="button"
            onClick={onExport}
            className="rounded-xl bg-slate-100 px-3.5 py-2 text-xs font-bold text-slate-700 transition-colors hover:bg-slate-200"
          >
            Exportar CSV
          </button>
        </div>
      </div>

      <div className="ops-scroll mt-2 overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <caption className="sr-only">
            Manifiesto de avisos: identificador, tipo y recursos, sector, estado,
            antigüedad y prioridad. Se muestran {rows.length} de {totalCount}{" "}
            aviso(s).
          </caption>
          <thead>
            <tr className="border-b border-slate-100 text-[11px] font-bold tracking-wider text-slate-400 uppercase">
              <th scope="col" className="px-3 py-3">
                Aviso
              </th>
              <th scope="col" className="px-3 py-3">
                Tipo / Recursos
              </th>
              <th scope="col" className="px-3 py-3">
                Sector
              </th>
              <th scope="col" className="px-3 py-3">
                Estado
              </th>
              <th scope="col" className="px-3 py-3">
                Antigüedad
              </th>
              <th scope="col" className="px-3 py-3 text-right">
                Prioridad / Firma
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-xs">
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-slate-500">
                  Ningún aviso cumple el filtro. Usa el buscador o cambia el
                  segmento de la barra superior.
                </td>
              </tr>
            )}
            {rows.map((row) => {
              const chip = statusChip(row.status);
              const selected = row.id === selectedId;
              return (
                <tr
                  key={row.id}
                  id={`ops-row-${row.id}`}
                  aria-selected={selected}
                  onClick={() => onSelect(row.id)}
                  className={`group cursor-pointer transition-colors ${
                    selected ? "bg-blue-50" : "hover:bg-slate-50"
                  }`}
                >
                  <td className="px-3 py-3.5">
                    <button
                      type="button"
                      onClick={(ev) => {
                        ev.stopPropagation();
                        onSelect(row.id);
                      }}
                      className="font-mono font-bold text-slate-600 group-hover:text-blue-600"
                      title={row.id}
                    >
                      {row.ref}
                    </button>
                    <div className="mt-0.5 text-[10px] text-slate-400">
                      {localTime(row.reportedAt)}
                    </div>
                  </td>

                  <td className="px-3 py-3.5">
                    <div className="flex items-center gap-2.5">
                      <div
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-slate-200 text-[13px] font-bold"
                        style={{
                          background: `${BUCKET_COLOR[row.triage]}1a`,
                          color: BUCKET_COLOR[row.triage],
                        }}
                        aria-hidden="true"
                      >
                        {TYPE_GLYPH[row.type]}
                      </div>
                      <div className="min-w-0">
                        <div className="truncate font-semibold text-slate-800 group-hover:text-blue-600">
                          {INCIDENT_TYPE_LABEL[row.type]} ·{" "}
                          {TRIAGE_LABEL[row.triage]}
                        </div>
                        <div className="truncate text-[10px] text-slate-400">
                          {row.units.length > 0
                            ? row.units.map((u) => u.id).join(" + ")
                            : "Sin recurso asignado"}
                        </div>
                      </div>
                    </div>
                  </td>

                  <td className="px-3 py-3.5">
                    <div className="font-medium text-slate-700">{row.sector}</div>
                    <div className="text-[10px] text-slate-400">
                      {row.incident.channel
                        ? `Canal: ${row.incident.channel}`
                        : "Canal: —"}
                    </div>
                  </td>

                  <td className="px-3 py-3.5">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[10px] font-extrabold tracking-wide uppercase ${chip.cls}`}
                    >
                      <span className="material-symbols-outlined text-[12px]" aria-hidden="true">
                        {row.status === "resuelto"
                          ? "check_circle"
                          : row.covered
                            ? "play_circle"
                            : "error"}
                      </span>
                      {chip.label}
                    </span>
                    <div className="mt-1 text-[10px] text-slate-400">
                      {row.covered ? "Con recursos" : "Sin recursos"}
                    </div>
                  </td>

                  <td className="w-48 px-3 py-3.5">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.round(row.ageRatio * 100)}%`,
                            background: BUCKET_COLOR[row.triage],
                          }}
                        />
                      </div>
                      <span className="font-mono text-[11px] font-bold text-slate-700">
                        {row.ageLabel}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[10px] text-slate-400">
                      Barra relativa al aviso más antiguo
                    </div>
                  </td>

                  <td className="px-3 py-3.5 text-right">
                    <div className="font-mono font-bold text-slate-800">
                      P{row.priority}
                    </div>
                    <div className="text-[10px] font-semibold">
                      {row.needsCard ? (
                        <span className="text-red-600">Requiere firma humana</span>
                      ) : row.units.length > 0 ? (
                        <span className="text-emerald-600">Asignado</span>
                      ) : (
                        <span className="text-slate-400">En cola</span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-3 border-t border-slate-100 pt-2 text-[10px] text-slate-400">
        Prioridad = gravedad × perfil (`lib/allocate.ts`). No hay ETA ni progreso
        de ruta porque el backend no publica telemetría de posición: la antigüedad
        y la asignación son los dos datos medibles. Identificador interno de
        ejemplo: <span className="mono">{opsRef("sim-d2-1")}</span>.
      </p>
    </div>
  );
}
