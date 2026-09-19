"use client";

/**
 * Barra lateral de «MANDO Ops».
 *
 * Los contadores de las pestañas son datos REALES: la dotación sale de la
 * capacidad del backend y los «críticos» de los avisos abiertos con triage
 * vital o emergencia. El mock traía «14 U» y «3 Crit» escritos a mano.
 */

export type OpsTab = "dashboard" | "fleet" | "incidents" | "routes" | "analytics";

type NavItem = {
  id: OpsTab;
  label: string;
  icon: string;
  badge?: { text: string; cls: string };
};

export function OpsSidebar({
  tab,
  onTab,
  fleetTotal,
  criticalCount,
  planBroken,
  operatorName,
  connected,
}: {
  tab: OpsTab;
  onTab: (tab: OpsTab) => void;
  fleetTotal: number;
  criticalCount: number;
  planBroken: boolean;
  operatorName: string;
  connected: boolean;
}) {
  const items: NavItem[] = [
    { id: "dashboard", label: "Dashboard", icon: "space_dashboard" },
    {
      id: "fleet",
      label: "Fleet / Recursos",
      icon: "ambulance",
      badge: { text: `${fleetTotal} U`, cls: "bg-[#162544] text-blue-300" },
    },
    {
      id: "incidents",
      label: "Incidentes / Triage",
      icon: "medical_services",
      badge:
        criticalCount > 0
          ? { text: `${criticalCount} Crit`, cls: "bg-red-500/20 text-red-300" }
          : { text: "0 Crit", cls: "bg-emerald-500/20 text-emerald-300" },
    },
    { id: "routes", label: "Rutas & Evac", icon: "directions_run" },
    { id: "analytics", label: "Analítica & Tiempos", icon: "timer" },
  ];

  return (
    <aside className="z-30 flex h-full w-[240px] shrink-0 flex-col justify-between border-r border-[#15233e] bg-[#0d192e] text-white shadow-2xl">
      <div className="flex flex-col">
        <div className="flex items-center gap-3 p-5 pb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-md shadow-blue-500/20">
            <span className="material-symbols-outlined text-[24px]" aria-hidden="true">
              local_shipping
            </span>
          </div>
          <div className="flex flex-col">
            <span className="flex items-center gap-1 text-[17px] leading-tight font-extrabold tracking-tight text-white">
              MANDO
              <span className="text-sm font-semibold text-blue-400">Ops</span>
            </span>
            <span className="text-[10.5px] font-medium tracking-wide text-slate-400 uppercase">
              Command Admin · {fleetTotal} U
            </span>
          </div>
        </div>

        <div className="px-3 py-2">
          <nav className="flex flex-col gap-1.5" aria-label="Vistas de MANDO Ops">
            {items.map((item) => {
              const active = item.id === tab;
              return (
                <button
                  key={item.id}
                  type="button"
                  aria-current={active ? "page" : undefined}
                  onClick={() => onTab(item.id)}
                  className={`flex w-full items-center gap-3 rounded-xl px-3.5 py-2.5 text-left text-[13.5px] transition-all ${
                    active
                      ? "bg-blue-600 font-semibold text-white shadow-md shadow-blue-600/30"
                      : "font-medium text-slate-400 hover:bg-[#162544] hover:text-white"
                  }`}
                >
                  <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
                    {item.icon}
                  </span>
                  <span className="flex flex-1 items-center justify-between">
                    <span>{item.label}</span>
                    {item.badge && (
                      <span
                        className={`rounded-md px-1.5 py-0.5 text-[10px] font-bold ${item.badge.cls}`}
                      >
                        {item.badge.text}
                      </span>
                    )}
                  </span>
                </button>
              );
            })}
          </nav>
        </div>
      </div>

      <div className="border-t border-[#162544] bg-[#091222]/80 p-3">
        <div className="flex items-center justify-between rounded-xl border border-slate-700/50 bg-[#162544]/60 p-2.5">
          <div className="flex items-center gap-2.5">
            <div className="relative">
              <div className="flex h-9 w-9 items-center justify-center rounded-full border border-blue-400 bg-slate-700 text-xs font-bold text-white">
                OP
              </div>
              <span
                className={`absolute right-0 bottom-0 h-2.5 w-2.5 rounded-full ring-2 ring-[#0d192e] ${
                  connected ? "bg-emerald-400" : "bg-amber-400"
                }`}
              />
            </div>
            <div className="flex flex-col">
              <span className="text-[12.5px] font-bold tracking-tight text-white">
                {operatorName}
              </span>
              <span className="flex items-center gap-1 font-mono text-[10px] text-slate-400">
                <span
                  aria-hidden="true"
                  className={`h-1.5 w-1.5 rounded-full ${
                    connected ? "bg-emerald-400" : "bg-amber-400"
                  }`}
                />
                {connected ? "SINCRONIZANDO" : "SIN CONEXIÓN"}
              </span>
            </div>
          </div>
          <span
            aria-hidden="true"
            className="material-symbols-outlined text-[18px] text-slate-400"
          >
            more_vert
          </span>
        </div>

        <p
          className={`mt-2 rounded-lg px-2 py-1.5 text-[10.5px] leading-snug font-semibold ${
            planBroken
              ? "bg-red-500/15 text-red-300"
              : "bg-emerald-500/15 text-emerald-300"
          }`}
          role="status"
        >
          {planBroken ? "✖ Plan saturado: déficit de recursos" : "✓ Plan cubierto"}
        </p>
      </div>
    </aside>
  );
}
