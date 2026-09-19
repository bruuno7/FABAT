import { DEFAULT_CAPACITY, RESOURCE_LABEL, RESOURCE_ORDER } from "@/lib/allocate";
import type { Board } from "@/lib/board-types";

/**
 * Recursos, con SEGMENTOS POR UNIDAD (patrón de la referencia de estilo):
 * una cápsula por unidad de dotación, ocupada con el color de acento y libre en
 * gris con borde discontinuo. Dice de un vistazo cuántos equipos quedan.
 *
 * COMPLIANCE (WCAG 1.4.1 + 1.1.1):
 *  - La ocupación NO se comunica solo por color: el recuento "usado/total" va
 *    como TEXTO y cada grupo de segmentos tiene su nombre accesible.
 *  - El estado de saturación lleva glifo + texto ("sin cubrir" / "sin déficit").
 *  - `role="img"` con aria-label por recurso: un lector de pantalla no debe
 *    intentar leer 8 cápsulas decorativas.
 *
 * El déficit se calcula de `allocation.overflow` real; no hay contadores fijos.
 */
export function ResourceMeter({ board }: { board: Board }) {
  const { remaining, overflow } = board.allocation;

  const deficit = new Map<string, number>();
  for (const o of overflow) {
    for (const k of o.missing) deficit.set(k, (deficit.get(k) ?? 0) + 1);
  }

  return (
    <ul className="flex flex-col gap-3">
      {RESOURCE_ORDER.map((kind) => {
        const total = DEFAULT_CAPACITY[kind];
        const left = remaining[kind];
        const used = total - left;
        const short = deficit.get(kind) ?? 0;

        return (
          <li key={kind}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-t2 font-medium text-ink">
                {RESOURCE_LABEL[kind]}
              </span>
              <span className="mono text-t1 text-ink-2">
                {used}/{total}
              </span>
            </div>

            <div
              className="mt-1 flex gap-1"
              role="img"
              aria-label={`${RESOURCE_LABEL[kind]}: ${used} de ${total} en uso, ${left} libre(s)`}
            >
              {Array.from({ length: total }, (_, i) => {
                const busy = i < used;
                return (
                  <span
                    key={i}
                    aria-hidden="true"
                    className={`meter-seg flex-1 ${
                      busy ? "meter-seg-busy" : ""
                    } ${busy && short > 0 && i === used - 1 ? "meter-seg-short" : ""}`}
                    style={busy ? undefined : { borderStyle: "dashed" }}
                  >
                    {busy ? `U${i + 1}` : "LIBRE"}
                  </span>
                );
              })}
            </div>

            {/* Estado: glifo + texto, nunca solo color */}
            <p
              className={`mt-1 flex items-center gap-1 text-t1 font-medium ${
                short > 0 ? "text-danger" : "text-ok"
              }`}
            >
              <span aria-hidden="true" className="glyph">
                {short > 0 ? "✖\uFE0E" : "✓\uFE0E"}
              </span>
              {short > 0 ? `${short} aviso(s) sin cubrir` : "sin déficit"}
            </p>
          </li>
        );
      })}
    </ul>
  );
}
