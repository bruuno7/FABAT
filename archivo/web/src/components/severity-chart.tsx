"use client";

import { useMemo } from "react";
import type { BoardIncident } from "@/lib/board-types";
import { TRIAGE_LABEL, type TriageColor } from "@/lib/contract";
import { TRIAGE_GLYPH } from "@/lib/present";

/**
 * ÚNICO micrográfico de la pantalla. Está aquí porque responde a una de las tres
 * preguntas del test de 5 segundos —"¿qué tan grave?"— mostrando de un vistazo el
 * reparto de la demanda por gravedad. No es decorativo: si no aportara a la
 * decisión, no estaría.
 *
 * COMPLIANCE:
 *  - Las barras usan la variante `-text` del triage (>= 4.76:1 sobre blanco), no
 *    el relleno del chip: en tema claro el ámbar como barra fallaba AA (2.15:1).
 *  - Cada barra lleva glifo + etiqueta + cifra, así que el gráfico se entiende
 *    sin depender del color.
 *  - El ancho de barra se repite como número, no hay que medir a ojo.
 */

const ORDER: TriageColor[] = ["negro", "rojo", "amarillo", "verde", "desconocido"];

/*
 * COMPLIANCE (la trampa del tema claro): las barras usan la variante `-text` del
 * triage (>= 7.09:1 sobre blanco), NO el relleno del chip: el ámbar como barra
 * daba 2.15:1 y el verde 3.56:1, ambos por debajo de AA para gráficos.
 * Cada barra lleva además glifo + etiqueta + cifra: el color es redundante.
 */
const BAR: Record<TriageColor, string> = {
  negro: "bg-[var(--color-triage-negro-text)]",
  rojo: "bg-[var(--color-triage-rojo-text)]",
  amarillo: "bg-[var(--color-triage-amarillo-text)]",
  verde: "bg-[var(--color-triage-verde-text)]",
  desconocido: "bg-[var(--color-triage-desconocido-text)]",
};

export function SeverityChart({ incidents }: { incidents: BoardIncident[] }) {
  const counts = useMemo(() => {
    const open = incidents.filter((i) => i.status !== "resuelto");
    const m = new Map<TriageColor, number>();
    for (const t of ORDER) m.set(t, 0);
    for (const incident of open) {
      const t = (incident.extract?.triage_color ?? "desconocido") as TriageColor;
      m.set(t, (m.get(t) ?? 0) + 1);
    }
    return m;
  }, [incidents]);

  const max = Math.max(1, ...ORDER.map((t) => counts.get(t) ?? 0));
  const total = ORDER.reduce((n, t) => n + (counts.get(t) ?? 0), 0);

  return (
    <div>
      <ul className="flex flex-col gap-1.5">
        {ORDER.map((t) => {
          const n = counts.get(t) ?? 0;
          return (
            <li key={t} className="flex items-center gap-2">
              <span className="flex w-[5.6rem] shrink-0 items-center gap-1 text-t1 text-ink-2">
                <span aria-hidden="true" className="glyph">
                  {TRIAGE_GLYPH[t]}
                </span>
                {TRIAGE_LABEL[t]}
              </span>
              {/* Barra: el color es redundante, va con etiqueta y cifra */}
              <span
                className="h-2 flex-1 overflow-hidden rounded-full bg-surface-container"
                aria-hidden="true"
              >
                <span
                  className={`block h-full rounded-full ${BAR[t]}`}
                  style={{ width: `${Math.max(2, (n / max) * 100)}%` }}
                />
              </span>
              <span className="mono w-5 shrink-0 text-right text-t1 font-semibold text-ink">
                {n}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-t1 text-muted">
        {total} abierto{total === 1 ? "" : "s"} por gravedad
      </p>
    </div>
  );
}
