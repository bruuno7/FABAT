import type { FeedEntry } from "@/lib/board-types";
import { FEED_TONE, feedKindGlyph, formatTime } from "@/lib/present";

/**
 * Traza del sistema (registro global). Vive en un cajón a demanda: en una consola
 * de emergencias el registro de qué pasó y cuándo es material de auditoría, pero
 * NO necesita estar en pantalla permanentemente. Así se calma la vista principal
 * sin perder el requisito de traza auditable.
 *
 * COMPLIANCE: tono + glifo + etiqueta textual, nunca solo color.
 */
export function Feed({
  entries,
  limit = 80,
  className = "",
}: {
  entries: FeedEntry[];
  limit?: number;
  className?: string;
}) {
  if (entries.length === 0) {
    return (
      <p className={`text-t1 text-muted ${className}`}>
        Sin actividad todavía. Inyecta un aviso desde Simulación o desde el chat.
      </p>
    );
  }

  return (
    <ol className={`flex flex-col gap-1.5 overflow-y-auto scroll-thin ${className}`}>
      {entries.slice(0, limit).map((entry) => {
        const tone = FEED_TONE[entry.tone];
        return (
          <li
            key={entry.id}
            className={`flex items-start gap-1.5 border-l-2 py-0.5 pl-2 text-t1 ${tone.className}`}
          >
            <span className="mono shrink-0 font-medium opacity-80">
              {formatTime(entry.at)}
            </span>
            <span aria-hidden="true" className="shrink-0">
              {feedKindGlyph(entry.kind)}
            </span>
            <span className="shrink-0 font-semibold uppercase tracking-wide opacity-90">
              {tone.label}
            </span>
            <span className="min-w-0 leading-snug">{entry.text}</span>
          </li>
        );
      })}
    </ol>
  );
}
