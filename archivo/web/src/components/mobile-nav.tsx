"use client";

import type { PanelId, QueueFilter } from "./sidebar";

const FILTERS: { id: QueueFilter; label: string }[] = [
  { id: "todas", label: "Todas" },
  { id: "graves", label: "Solo graves" },
  { id: "sin_recursos", label: "Sin recursos" },
  { id: "por_sector", label: "Por sector" },
];

const PANELS: { id: PanelId; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "preparacion", label: "Inyección" },
  { id: "traza", label: "Traza" },
];

/**
 * Navegación equivalente para pantallas estrechas, donde la barra lateral no
 * cabe. Son FILTROS y PANELES de la misma pantalla, no rutas: así ocultar la
 * barra lateral no deja la app sin forma de operar (COMPLIANCE: la navegación
 * debe seguir existiendo y ser operable).
 */
export function MobileNav({
  filter,
  onFilter,
  openPanel,
  onTogglePanel,
}: {
  filter: QueueFilter;
  onFilter: (f: QueueFilter) => void;
  openPanel: PanelId | null;
  onTogglePanel: (p: PanelId) => void;
}) {
  return (
    <nav
      aria-label="Filtros y paneles"
      className="flex shrink-0 flex-wrap items-center gap-1 border-b border-outline-soft bg-sidebar px-3 py-2 md:hidden"
    >
      <span className="mr-1.5 text-t2 font-bold tracking-tight text-white">
        MANDO
      </span>
      {FILTERS.map((f) => (
        <button
          key={f.id}
          type="button"
          aria-pressed={filter === f.id}
          onClick={() => onFilter(f.id)}
          className={`rounded-lg px-2.5 py-1 text-t1 font-medium ${
            filter === f.id
              ? "bg-sidebar-active font-bold text-white"
              : "text-[#cdd6ea]"
          }`}
        >
          {f.label}
        </button>
      ))}
      <span className="mx-1 h-4 w-px bg-white/20" aria-hidden="true" />
      {PANELS.map((p) => (
        <button
          key={p.id}
          type="button"
          aria-pressed={openPanel === p.id}
          onClick={() => onTogglePanel(p.id)}
          className={`rounded-lg px-2.5 py-1 text-t1 font-medium ${
            openPanel === p.id
              ? "bg-sidebar-active font-bold text-white"
              : "text-[#cdd6ea]"
          }`}
        >
          {p.label}
        </button>
      ))}
      <span className="mono ml-auto text-t2 font-bold text-white">112</span>
    </nav>
  );
}
