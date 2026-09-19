"use client";

import { useEffect, useState } from "react";
import type { BoardEnv } from "@/lib/board-types";
import type { BoardIncident } from "@/lib/board-types";

/*
 * BARRA LATERAL — navegación de UNA SOLA pantalla (230px, primary-container).
 *
 * No hay enlaces a rutas distintas: todo ocurre en `/`. Los ítems son FILTROS de
 * la cola y ACCIONES que abren paneles de la misma pantalla, cada uno con su
 * contador calculado de los datos reales (nada hardcodeado).
 * Al pie: número de emergencia europeo, modo técnico del enlace HR y la nota de
 * entorno de demostración.
 */

export type QueueFilter = "todas" | "graves" | "sin_recursos" | "por_sector";

export type PanelId = "chat" | "preparacion" | "traza" | "detalle";

const FILTERS: { id: QueueFilter; label: string; glyph: string }[] = [
  { id: "todas", label: "Todas", glyph: "▤\uFE0E" },
  { id: "graves", label: "Solo graves", glyph: "✖\uFE0E" },
  { id: "sin_recursos", label: "Sin recursos", glyph: "⚠\uFE0E" },
  { id: "por_sector", label: "Por sector", glyph: "◈\uFE0E" },
];

const PANELS: { id: PanelId; label: string; glyph: string }[] = [
  { id: "chat", label: "Chat ciudadano", glyph: "☎\uFE0E" },
  { id: "preparacion", label: "Preparación", glyph: "⛁\uFE0E" },
  { id: "traza", label: "Traza y patrones", glyph: "▦\uFE0E" },
];

/** Cuenta los avisos que cumplen cada filtro. Nada de cifras fijas. */
export function countByFilter(
  incidents: BoardIncident[],
  filter: QueueFilter,
): number {
  const open = incidents.filter((i) => i.status !== "resuelto");
  switch (filter) {
    case "graves":
      return open.filter((i) => {
        const t = i.extract?.triage_color;
        return t === "negro" || t === "rojo";
      }).length;
    case "sin_recursos":
      return open.filter((i) => !i.covered).length;
    case "por_sector":
      return new Set(
        open.map((i) => i.extract?.sector).filter(Boolean),
      ).size;
    default:
      return open.length;
  }
}

export function Sidebar({
  incidents,
  filter,
  onFilter,
  openPanel,
  onTogglePanel,
}: {
  incidents: BoardIncident[];
  filter: QueueFilter;
  onFilter: (f: QueueFilter) => void;
  openPanel: PanelId | null;
  onTogglePanel: (p: PanelId) => void;
}) {
  const [env, setEnv] = useState<BoardEnv | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (alive) {
          setEnv((await res.json()) as BoardEnv);
          setHealthFailed(false);
        }
      } catch {
        if (alive) setHealthFailed(true);
      }
    }
    const first = setTimeout(() => void load(), 0);
    const t = setInterval(() => void load(), 30000);
    return () => {
      alive = false;
      clearTimeout(first);
      clearInterval(t);
    };
  }, []);

  const live = env?.hr_mode === "live";

  /*
   * HIDRATACIÓN — este bloque es el que antes provocaba un cambio ESTRUCTURAL:
   * se montaba con `{env && <p>…</p>}`, así que el servidor y el primer render
   * de cliente NO incluían el nodo y aparecía después, empujando el pie de la
   * barra (salto de layout perceptible).
   *
   * Ahora el <p> se renderiza SIEMPRE, con el mismo tamaño reservado
   * (`min-h`) en servidor y en el primer render de cliente: `env` es `null` en
   * ambos, así que el marcado coincide exactamente y no hay desajuste de
   * hidratación. Después del montaje solo cambia el TEXTO, no la estructura.
   *
   * No se usa `suppressHydrationWarning`: no hace falta tapar nada, porque el
   * primer render de cliente es idéntico al del servidor por construcción.
   */
  const hrLabel = healthFailed
    ? "Agente HR · sin datos"
    : env
      ? live
        ? "Agente HR · enlace directo"
        : "Agente HR · enlace local"
      : "Agente HR · comprobando";

  const hrDot = healthFailed
    ? "bg-[#f4c56a]"
    : live
      ? "bg-[#4edea3]"
      : "bg-[#7d889f]";

  const hrTitle = healthFailed
    ? "No se pudo consultar el estado del enlace con el agente"
    : env
      ? live
        ? "El extracto lo produce el workflow de HappyRobot"
        : "El extracto lo produce el extractor determinista local (HR_HOOK_TG sin configurar)"
      : "Comprobando el estado del enlace con el agente…";

  return (
    <aside className="sidebar hidden shrink-0 flex-col justify-between md:flex">
      <div className="flex flex-col">
        {/* Marca */}
        <div className="flex items-center gap-2 px-6 py-4">
          <span
            aria-hidden="true"
            className="h-2.5 w-2.5 shrink-0 rounded-full bg-[#2170e4]"
          />
          <span className="text-[19px] font-bold leading-none tracking-wide text-white">
            MANDO
          </span>
          <span className="ml-auto rounded-full bg-white/10 px-2 py-0.5 text-[11px] font-semibold text-[#cdd6ea]">
            40K PAX
          </span>
        </div>
        <p className="px-6 pb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#9aa4b8]">
          Festival Abierto
        </p>

        {/* Filtros de la cola (misma pantalla) */}
        <nav aria-label="Filtros de control" className="flex flex-col gap-0.5 px-2 pt-1">
          <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#8b96ac]">
            Filtros de control
          </p>
          {FILTERS.map((f) => {
            const n = countByFilter(incidents, f.id);
            return (
              <button
                key={f.id}
                type="button"
                aria-pressed={filter === f.id}
                onClick={() => onFilter(f.id)}
                className="side-link"
              >
                <span aria-hidden="true" className="glyph text-[15px]">
                  {f.glyph}
                </span>
                <span className="min-w-0 flex-1 truncate">{f.label}</span>
                {/* Ancho fijo + tabular-nums: el contador pasa de 0 a 17 al
                    cargar el tablero sin reflow ni salto de layout. */}
                <span className="mono w-6 shrink-0 text-right text-[11px] tabular-nums">
                  {n}
                </span>
              </button>
            );
          })}
        </nav>

        {/* Paneles de la misma pantalla */}
        <div className="mt-3 flex flex-col gap-0.5 px-2">
          <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#8b96ac]">
            Paneles
          </p>
          {PANELS.map((p) => (
            <button
              key={p.id}
              type="button"
              aria-pressed={openPanel === p.id}
              onClick={() => onTogglePanel(p.id)}
              className="side-link"
            >
              <span aria-hidden="true" className="glyph text-[15px]">
                {p.glyph}
              </span>
              <span className="min-w-0 flex-1 truncate">{p.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Pie */}
      <div className="flex flex-col gap-3 p-3">
        <hr className="border-white/10" />

        {/*
          COMPLIANCE — dos cosas distintas que NO se deben confundir:
          (a) MODO TÉCNICO DEL ENLACE (esta línea): si el workflow real de
              HappyRobot está configurado (`HR_HOOK_TG`), el extracto lo produce
              HR; si no, lo produce el extractor determinista local. Se muestra
              sobrio y veraz: la interfaz se presenta como un sistema en
              operación, pero no miente sobre el origen del dato.
          (b) FICCIÓN DE LOS DATOS (abajo): los avisos son ficticios. Es una
              obligación RGPD y se queda siempre, en cualquier modo.
        */}
        <p
          className="flex min-h-[1.9rem] items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px] text-[#cdd6ea]"
          title={hrTitle}
        >
          <span
            aria-hidden="true"
            className={`h-2 w-2 shrink-0 rounded-full ${hrDot}`}
          />
          {hrLabel}
        </p>

        {/* COMPLIANCE (emergencias): número europeo, siempre a la vista */}
        <div className="rounded-xl bg-white/8 px-3 py-2.5">
          <p className="text-[11px] text-[#9aa4b8]">Recurso externo</p>
          <p className="mt-0.5 flex items-baseline gap-1.5">
            <span className="mono text-[19px] font-bold leading-none text-white">
              112
            </span>
            <span className="text-[11px] leading-tight text-[#cdd6ea]">
              emergencias (UE)
            </span>
          </p>
        </div>

        {/* COMPLIANCE (RGPD Art. 5/9): aviso permanente de datos ficticios */}
        <p
          className="flex items-start gap-1.5 px-0.5 text-[11px] leading-snug text-[#9aa4b8]"
          title="Entorno de demostración con datos ficticios. No hay datos de personas reales."
        >
          <span aria-hidden="true" className="glyph">
            ◇
          </span>
          Entorno de demostración · datos ficticios
        </p>
      </div>
    </aside>
  );
}
