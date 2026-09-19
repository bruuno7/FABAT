"use client";

/**
 * Tarjetas de indicadores de «MANDO Ops».
 *
 * Cada cifra sale del backend (`/api/board`). Donde el mock enseñaba un valor
 * de guion se enseña el real, y si no hay dato se dice «—»:
 *   · «Avg. Response Time 3.8 min / SLA 84 %» → mediana REAL de minutos hasta la
 *     firma humana, con el número de avisos que la componen (su N).
 *   · «Resource Efficiency 92 %» → unidades libres sobre la dotación real.
 *   · «Incidentes por gravedad» → recuento real por triage del contrato.
 */

import type { ReactNode } from "react";
import type { ResourceKind } from "@/lib/allocate";
import type { ClaimStats, FleetTotals, SeverityBucket } from "@/lib/ops";

const RING_R = 38;
const RING_C = 2 * Math.PI * RING_R;

const KIND_COLOR: Record<ResourceKind, string> = {
  medico: "#f87171",
  seguridad: "#64748b",
  apoyo: "#cbd5e1",
  coordinacion: "#94a3b8",
};

function Donut({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex h-20 w-20 items-center justify-center">
      <svg className="h-full w-full -rotate-90" viewBox="0 0 100 100" aria-hidden="true">
        {children}
      </svg>
    </div>
  );
}

export function OpsKpiCards({
  stats,
  buckets,
  fleet,
}: {
  stats: ClaimStats;
  buckets: SeverityBucket[];
  fleet: FleetTotals;
}) {
  const totalBucket = buckets.reduce((n, b) => n + b.count, 0);
  const median = stats.medianAssignMin;
  const rings = fleet.rows.filter((r) => r.total > 0);
  let offsetAcc = 0;
  /* Sin avisos abiertos, «100 % cubierto» sería una verdad vacía: se dice «—». */
  const hasOpen = stats.open > 0;

  return (
    <div className="col-span-12 flex flex-col gap-4 lg:col-span-4">
      {/* 1. Tiempo hasta la firma humana */}
      <div className="flex flex-col justify-between rounded-2xl border border-slate-200/90 bg-white p-4 text-slate-900 shadow-sm">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
            Tiempo hasta asignación
          </span>
          <span className="material-symbols-outlined text-[18px] text-slate-400" aria-hidden="true">
            schedule
          </span>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <div>
            <div className="flex items-baseline gap-1">
              <span className="text-3xl font-extrabold tracking-tight text-slate-900">
                {median === null ? "—" : median.toFixed(1)}
              </span>
              <span className="text-xs font-medium text-slate-400">
                {median === null ? "sin firmas" : "min"}
              </span>
            </div>
            <span className="mt-0.5 flex items-center gap-1 text-[11px] font-medium text-slate-600">
              <span className="material-symbols-outlined text-[13px] text-emerald-600" aria-hidden="true">
                {median === null ? "pending" : "trending_down"}
              </span>
              Mediana de {stats.assignedCount} aviso(s) firmado(s)
            </span>
            <p className="mt-1.5 text-[10px] text-slate-400">
              No se mide contra un SLA: el recinto no tiene uno declarado.
            </p>
          </div>
          <div className="relative flex h-20 w-20 items-center justify-center">
            <Donut>
              <circle cx="50" cy="50" r={RING_R} fill="none" stroke="#f1f5f9" strokeWidth="6" />
              <circle
                cx="50"
                cy="50"
                r={RING_R}
                fill="none"
                stroke="#475569"
                strokeDasharray={RING_C}
                strokeDashoffset={
                  RING_C * (1 - (hasOpen ? stats.coveragePct : 0) / 100)
                }
                strokeLinecap="round"
                strokeWidth="6"
              />
            </Donut>
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
              <span className="text-xs font-bold text-slate-800">
                {hasOpen ? `${stats.coveragePct}%` : "—"}
              </span>
              <span className="text-[7.5px] font-medium tracking-wider text-slate-400 uppercase">
                cubiertos
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* 2. Eficiencia de recursos */}
      <div className="flex flex-col rounded-2xl border border-slate-200/90 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
            Eficiencia de recursos
          </span>
          <span className="material-symbols-outlined text-[18px] text-slate-400" aria-hidden="true">
            verified
          </span>
        </div>
        <div className="mt-1 flex items-center justify-between">
          <div>
            <div className="flex items-baseline gap-1">
              <span className="text-3xl font-extrabold tracking-tight text-slate-900">
                {fleet.total === 0
                  ? "—"
                  : Math.round((fleet.busy / fleet.total) * 100)}
              </span>
              <span className="text-xs font-normal text-slate-400">% ocupado</span>
            </div>
            <span className="mt-0.5 flex items-center gap-1 text-[11px] font-medium text-slate-600">
              <span className="material-symbols-outlined text-[13px] text-emerald-600" aria-hidden="true">
                verified_user
              </span>
              {fleet.free} de {fleet.total} unidades libres
            </span>
          </div>
          <Donut>
            <circle cx="50" cy="50" r={RING_R} fill="none" stroke="#f1f5f9" strokeWidth="6" />
            {rings.map((row) => {
              const share = RING_C * (row.total / fleet.total);
              const el = (
                <circle
                  key={row.kind}
                  cx="50"
                  cy="50"
                  r={RING_R}
                  fill="none"
                  stroke={KIND_COLOR[row.kind]}
                  strokeDasharray={`${share} ${RING_C - share}`}
                  strokeDashoffset={-offsetAcc}
                  strokeWidth="6"
                />
              );
              offsetAcc += share;
              return el;
            })}
          </Donut>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 border-t border-slate-100 pt-2.5 text-[11px]">
          {fleet.rows.map((row) => (
            <div key={row.kind} className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="h-2 w-2 rounded-full"
                style={{ background: KIND_COLOR[row.kind] }}
              />
              <span className="font-medium text-slate-500">
                {row.role} ({row.free} libres)
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* 3. Avisos por gravedad */}
      <div className="flex flex-1 flex-col rounded-2xl border border-slate-200/90 bg-white p-4 shadow-sm">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
            Avisos por gravedad
          </span>
          <span className="rounded-md border border-slate-100 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-500">
            {totalBucket} abiertos
          </span>
        </div>
        <div className="my-auto flex items-center gap-4">
          <div className="relative flex h-20 w-20 shrink-0 items-center justify-center">
            <Donut>
              <circle cx="50" cy="50" r="36" fill="none" stroke="#f1f5f9" strokeWidth="8" />
              {(() => {
                const C = 2 * Math.PI * 36;
                let acc = 0;
                return buckets
                  .filter((b) => b.count > 0)
                  .map((b) => {
                    const len = C * (b.count / Math.max(1, totalBucket));
                    const el = (
                      <circle
                        key={b.key}
                        cx="50"
                        cy="50"
                        r="36"
                        fill="none"
                        stroke={b.color}
                        strokeDasharray={`${len} ${C - len}`}
                        strokeDashoffset={-acc}
                        strokeWidth="8"
                      />
                    );
                    acc += len;
                    return el;
                  });
              })()}
            </Donut>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-sm font-bold text-slate-800">{totalBucket}</span>
              <span className="text-[7.5px] font-medium tracking-wider text-slate-400 uppercase">
                avisos
              </span>
            </div>
          </div>
          <div className="flex-1 space-y-1.5 text-[11px]">
            {buckets.map((b) => (
              <div key={b.key} className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 font-medium text-slate-600">
                  <span
                    aria-hidden="true"
                    className="h-2 w-2 rounded-full"
                    style={{ background: b.color }}
                  />
                  {b.label}
                </span>
                <span className="font-semibold text-slate-800">
                  {b.count} ({b.pct}%)
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
