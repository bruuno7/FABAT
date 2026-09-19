"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { InjectResponse } from "@/lib/board-types";
import { injectReport } from "@/lib/client-api";
import {
  INCIDENT_TYPE_LABEL,
  PERFIL_LABEL,
  needsHumanCard,
  type PerfilColor,
} from "@/lib/contract";
import { TYPE_GLYPH, formatTime } from "@/lib/present";
import { PerfilChip, SeverityMeter, TriageChip } from "./ui";

/*
 * PUESTO DE LLAMADA — herramienta de operador, no app de mensajería.
 *
 * SEPARACIÓN DE PAPELES: aquí HABLA el agente. MANDO no decide en este panel; el
 * resultado operativo (gravedad, sector, recursos) vive en el mapa y la cola.
 *
 * Colapsado por defecto: en reposo solo ocupa su cabecera, y se despliega cuando
 * entra o se envía el primer turno de una conversación (`onIncoming`).
 *
 * COMPLIANCE:
 *  - RGPD Art. 9: seudónimo de sesión, sin nombre real ni datos de salud; el
 *    perfil es categoría OPERATIVA (protocolo), no diagnóstico.
 *  - La transcripción es un registro de operador (hora + rol), no burbujas.
 *  - La nota de entorno de demostración con datos ficticios es obligatoria y
 *    NO es lo mismo que el modo técnico del enlace (ver sidebar.tsx).
 */

const PERFILES = Object.keys(PERFIL_LABEL) as PerfilColor[];

const SCRIPTS = [
  "Hay una persona caída cerca del escenario principal",
  "No hay luz en los baños de la zona oeste",
  "Muchísima gente en la entrada y no se puede pasar",
];

type Message = {
  id: string;
  role: "caller" | "agent" | "system";
  text: string;
  at: string;
  extract?: InjectResponse["extract"];
};

/** Estado de la mesa respecto a la llamada en curso. */
type CallState = "libre" | "escuchando" | "operador";

const ROLE = {
  caller: { label: "Ciudadano", glyph: "◀", tone: "turn-caller" },
  agent: { label: "Agente HR", glyph: "▶", tone: "turn-agent" },
  system: { label: "Extractor", glyph: "✦", tone: "turn-system" },
} as const;

const CALL_LABEL: Record<CallState, { text: string; glyph: string; tone: string }> = {
  libre: { text: "Agente al mando", glyph: "▶", tone: "text-ok" },
  escuchando: { text: "Mesa escuchando", glyph: "◉", tone: "text-accent" },
  operador: { text: "Operador al mando", glyph: "◀", tone: "text-warn" },
};

function Turn({ message }: { message: Message }) {
  const meta = ROLE[message.role];
  const e = message.extract;

  return (
    <li className={`turn ${meta.tone}`}>
      <p className="flex items-center gap-1.5 text-t1 text-muted">
        <span className="mono font-medium">{formatTime(message.at)}</span>
        <span aria-hidden="true" className="glyph">{meta.glyph}</span>
        <span className="font-medium">{meta.label}</span>
      </p>

      {e ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <TriageChip color={e.triage_color ?? "desconocido"} />
          <span className="inline-flex items-center gap-1 text-t1 text-ink">
            <span aria-hidden="true" className="glyph">{TYPE_GLYPH[e.incident_type ?? "otro"]}</span>
            {INCIDENT_TYPE_LABEL[e.incident_type ?? "otro"]}
          </span>
          <span className="text-t1 text-ink-2">{e.sector ?? "sin sector"}</span>
          <SeverityMeter severity={e.severity} triage={e.triage_color ?? "desconocido"} />
        </div>
      ) : (
        <p className="mt-0.5 text-t2 leading-snug text-ink">{message.text}</p>
      )}
    </li>
  );
}

export function ChatPanel({
  expanded,
  onToggle,
  onIncoming,
  onResult,
  className = "",
}: {
  expanded: boolean;
  onToggle: () => void;
  /** Se llama al abrirse una conversación (primer turno del ciudadano). */
  onIncoming?: () => void;
  onResult?: (result: InjectResponse) => void;
  className?: string;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [perfil, setPerfil] = useState<PerfilColor>("adulto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [callState, setCallState] = useState<CallState>("libre");
  const bottom = useRef<HTMLDivElement>(null);
  const seq = useRef(0);

  useEffect(() => {
    if (!expanded) return;
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages, expanded]);

  const send = useCallback(
    async (value: string) => {
      const trimmed = value.trim();
      if (!trimmed || busy) return;
      setBusy(true);
      setError(null);
      setText("");
      seq.current += 1;
      const stamp = new Date().toISOString();

      setMessages((prev) => [
        ...prev,
        { id: `c-${stamp}-${seq.current}`, role: "caller", text: trimmed, at: stamp },
      ]);
      onIncoming?.();

      try {
        const result = await injectReport({
          text: trimmed,
          channel: "webcall",
          perfil_color: perfil,
          display_name: "Llamante",
        });

        if (result.extract) {
          setMessages((prev) => [
            ...prev,
            {
              id: `s-${Date.now()}-${seq.current}`,
              role: "system",
              text: "Extracto",
              at: new Date().toISOString(),
              extract: result.extract,
            },
          ]);
        }
        if (result.reply_text) {
          setMessages((prev) => [
            ...prev,
            {
              id: `a-${Date.now()}-${seq.current}`,
              role: "agent",
              text: result.reply_text ?? "",
              at: new Date().toISOString(),
            },
          ]);
        }
        onResult?.(result);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [busy, perfil, onResult, onIncoming],
  );

  const latestExtract = useMemo(
    () =>
      [...messages].reverse().find((m) => m.role === "system" && m.extract)?.extract ??
      null,
    [messages],
  );
  const needsHuman = useMemo(
    () => (latestExtract ? needsHumanCard({ extract: latestExtract }) : false),
    [latestExtract],
  );

  const call = CALL_LABEL[callState];

  return (
    <div className={`flex min-h-0 flex-col ${className}`}>
      {/* Cabecera: en reposo es TODO lo que ocupa el chat */}
      <header className="flex shrink-0 items-center gap-2 px-4 py-3">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span aria-hidden="true" className="text-t1 text-muted">
            {expanded ? "▾" : "▸"}
          </span>
          <span className="truncate text-t2 font-semibold text-ink">
            Chat ciudadano
          </span>
        </button>

        {latestExtract && (
          <TriageChip color={latestExtract.triage_color ?? "desconocido"} />
        )}
        {needsHuman && (
          <span
            className="inline-flex shrink-0 items-center gap-1 text-t1 font-semibold text-danger"
            title="Gravedad negra o roja: requiere confirmación humana"
          >
            <span aria-hidden="true" className="glyph">⚠</span>
          </span>
        )}
        <span className="shrink-0 text-t1 text-muted">
          {messages.length === 0 ? "sin llamada" : `${messages.length} turnos`}
        </span>
      </header>

      {expanded && (
        <>
          {/* Controles de la mesa + estado de la llamada */}
          <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-y border-outline-soft bg-surface-low px-3 py-1.5">
            <span
              className={`inline-flex items-center gap-1.5 text-t1 font-medium ${call.tone}`}
            >
              <span aria-hidden="true" className="glyph">{call.glyph}</span>
              {call.text}
            </span>

            <span className="ml-auto flex items-center gap-1.5">
              {/* COMPLIANCE: los dos controles llevan etiqueta textual, no solo
                  color, y aria-pressed para que el lector anuncie el estado. */}
              <button
                type="button"
                aria-pressed={callState === "escuchando"}
                onClick={() =>
                  setCallState((s) => (s === "escuchando" ? "libre" : "escuchando"))
                }
                className="btn btn-sm"
              >
                ◉ Escuchar
              </button>
              <button
                type="button"
                aria-pressed={callState === "operador"}
                onClick={() =>
                  setCallState((s) => (s === "operador" ? "libre" : "operador"))
                }
                className={`btn btn-sm ${callState === "operador" ? "btn-primary" : ""}`}
              >
                ◀ Tomar el control
              </button>
            </span>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto scroll-thin p-3">
            {messages.length === 0 ? (
              <p className="text-t1 leading-relaxed text-muted">
                Sin conversación activa. Escribe lo que diría el ciudadano, o usa
                un guion, para abrir una llamada.
              </p>
            ) : (
              <ol className="flex flex-col gap-2">
                {messages.map((message) => (
                  <Turn key={message.id} message={message} />
                ))}
                <div ref={bottom} />
              </ol>
            )}
          </div>

          {error && (
            <p
              role="alert"
              className="mx-3 mb-1 flex items-center gap-1.5 text-t1 font-medium text-danger"
            >
              <span aria-hidden="true" className="glyph">✖</span> {error}
            </p>
          )}

          <div className="shrink-0 border-t border-outline-soft p-3">
            <div className="mb-2 flex flex-wrap gap-1.5">
              {SCRIPTS.map((phrase) => (
                <button
                  key={phrase}
                  type="button"
                  onClick={() => void send(phrase)}
                  disabled={busy}
                  className="btn btn-sm max-w-full"
                  title={phrase}
                >
                  <span className="truncate">{phrase}</span>
                </button>
              ))}
            </div>

            <div className="flex items-end gap-2">
              <label className="min-w-0 flex-1">
                <span className="sr-only">Lo que dice el ciudadano</span>
                <textarea
                  value={text}
                  onChange={(ev) => setText(ev.target.value)}
                  onKeyDown={(ev) => {
                    if (ev.key === "Enter" && !ev.shiftKey) {
                      ev.preventDefault();
                      void send(text);
                    }
                  }}
                  rows={2}
                  placeholder="Habla el ciudadano… (Enter envía)"
                  className="field resize-none"
                />
              </label>
              <button
                type="button"
                disabled={busy || text.trim() === ""}
                onClick={() => void send(text)}
                className="btn btn-primary"
              >
                {busy ? "…" : "Enviar"}
              </button>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-t1 text-muted">Perfil</span>
              {PERFILES.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPerfil(p)}
                  aria-pressed={perfil === p}
                  className={`min-h-6 rounded-md px-0.5 ${
                    perfil === p ? "ring-2 ring-accent" : "opacity-70 hover:opacity-100"
                  }`}
                >
                  <PerfilChip color={p} />
                </button>
              ))}
            </div>

            {/* COMPLIANCE (RGPD Art. 9): minimización + aviso de datos ficticios.
                Esta nota NO es el indicador de modo técnico del enlace: protege
                frente al RGPD y es obligatoria. */}
            <p className="mt-2 text-t1 leading-snug text-muted">
              Seudónimo de sesión{" "}
              <strong className="font-medium text-ink-2">Llamante</strong>: no se
              pide nombre real ni datos de salud. Entorno de demostración con datos
              ficticios.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
