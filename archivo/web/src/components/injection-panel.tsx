"use client";

import { useCallback, useMemo, useState } from "react";
import type { InjectResponse } from "@/lib/board-types";
import { injectReport, resetBoard } from "@/lib/client-api";
import { useBoard } from "@/components/use-board";
import { allocate } from "@/lib/allocate";
import {
  INCIDENT_TYPE_LABEL,
  PERFIL_LABEL,
  type IncidentRow,
  type PerfilColor,
} from "@/lib/contract";
import { simulateExtract } from "@/lib/hr-sim";
import { TYPE_GLYPH } from "@/lib/present";
import { SCENARIOS, type Scenario, type ScenarioItem } from "@/lib/scenario";
import { TriageChip } from "./ui";

/*
 * MESA DE INYECCIÓN — herramienta de PREPARACIÓN, no de operación.
 *
 * Vive en un cajón que se abre desde la barra superior y nunca ocupa espacio
 * permanente: mientras se opera, la pantalla solo muestra mapa, recursos, chat y
 * cola. Al abrirse, se cierra cualquier otra zona secundaria (regla de
 * saturación: solo una desplegada a la vez).
 *
 * Reutiliza `src/lib/scenario.ts` tal cual (los tres escenarios y sus avisos) y
 * el extractor determinista real para previsualizar cada aviso.
 */

const PERFILES = Object.keys(PERFIL_LABEL) as PerfilColor[];

/* -------------------------------------------------------------------------- */
/*  Previsión determinista del escenario (solo lectura, sin lógica de dominio) */
/* -------------------------------------------------------------------------- */

type Verdict = "cubierto" | "tension" | "roto";

type Forecast = {
  critical: number;
  overflowCount: number;
  missing: string[];
  verdict: Verdict;
};

function forecastScenario(scenario: Scenario): Forecast {
  const rows: IncidentRow[] = scenario.items.map((item) => {
    const extract = simulateExtract({
      event: "public_report",
      channel: "webcall",
      reported_at: "2026-01-01T00:00:00.000Z",
      text: item.text,
      reporter: { perfil_color: item.perfil_color, display_name: item.reporter },
      location_hint: item.location_hint,
      correlation_id: `sim-${item.id}`,
    });
    return {
      correlation_id: `sim-${item.id}`,
      status: "nuevo",
      timeline: [],
      source: "sim",
      reported_at: "2026-01-01T00:00:00.000Z",
      updated_at: "2026-01-01T00:00:00.000Z",
      extract,
    };
  });

  const triages = rows.map((r) => r.extract?.triage_color ?? "desconocido");
  const allocation = allocate(rows);
  const missing = [...new Set(allocation.overflow.flatMap((o) => o.missing))];
  const vital = missing.some((k) => k === "medico" || k === "coordinacion");

  return {
    critical: triages.filter((t) => t === "negro" || t === "rojo").length,
    overflowCount: allocation.overflow.length,
    missing,
    verdict: !allocation.broken ? "cubierto" : vital ? "roto" : "tension",
  };
}

const VERDICT: Record<Verdict, { label: string; glyph: string; tone: string }> = {
  cubierto: { label: "cubre el escenario", glyph: "✓", tone: "text-ok" },
  tension: { label: "dotación en tensión", glyph: "!", tone: "text-warn" },
  roto: { label: "rompe recurso vital", glyph: "✖", tone: "text-danger" },
};

function resourceShort(kind: string): string {
  switch (kind) {
    case "medico":
      return "equipos médicos";
    case "seguridad":
      return "seguridad";
    case "apoyo":
      return "apoyo";
    case "coordinacion":
      return "coordinación";
    default:
      return kind;
  }
}

/* -------------------------------------------------------------------------- */

export function InjectionPanel({ onClose }: { onClose: () => void }) {
  const { board, reload } = useBoard(3000);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [autoBusy, setAutoBusy] = useState(false);
  const [last, setLast] = useState<InjectResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [perfil, setPerfil] = useState<PerfilColor>("adulto");

  // "Ya inyectado" se deriva del tablero: sobrevive a recargas.
  const injected = useMemo(() => {
    const ids = new Set<string>();
    for (const incident of board?.incidents ?? []) {
      if (incident.correlation_id.startsWith("sim-d")) {
        ids.add(incident.correlation_id.replace(/^sim-/, ""));
      }
    }
    return ids;
  }, [board]);

  const injectItem = useCallback(
    async (item: ScenarioItem) => {
      setBusyId(item.id);
      setError(null);
      try {
        const result = await injectReport({
          text: item.text,
          channel: "webcall",
          perfil_color: item.perfil_color,
          display_name: item.reporter,
          location_hint: item.location_hint,
          correlation_id: `sim-${item.id}`,
        });
        setLast(result);
        await reload();
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setBusyId(null);
      }
    },
    [reload],
  );

  const runScenario = useCallback(
    async (scenarioId: "dia1" | "dia2") => {
      const scenario = SCENARIOS.find((s) => s.id === scenarioId);
      if (!scenario) return;
      setAutoBusy(true);
      setError(null);
      try {
        for (const item of scenario.items) {
          if (injected.has(item.id)) continue;
          await injectItem(item);
          await new Promise((r) => setTimeout(r, 220));
        }
      } finally {
        setAutoBusy(false);
      }
    },
    [injected, injectItem],
  );

  const submitManual = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setBusyId("manual");
    setError(null);
    try {
      const result = await injectReport({
        text: trimmed,
        channel: "telegram",
        perfil_color: perfil,
        display_name: "Aviso manual",
      });
      setLast(result);
      setText("");
      await reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyId(null);
    }
  }, [text, perfil, reload]);

  const forecasts = useMemo(
    () =>
      SCENARIOS.map((scenario) => ({
        scenario,
        forecast: forecastScenario(scenario),
      })),
    [],
  );

  const contrast = useMemo(() => {
    const dia1 = forecasts.find((f) => f.scenario.id === "dia1")?.forecast;
    const dia2 = forecasts.find((f) => f.scenario.id === "dia2")?.forecast;
    if (!dia1 || !dia2) return null;
    return {
      dia1,
      dia2,
      deficit1: dia1.missing.map(resourceShort).join(" + ") || "nada",
      deficit2: dia2.missing.map(resourceShort).join(" + ") || "nada",
    };
  }, [forecasts]);

  const injectedCount = (scenario: Scenario) =>
    scenario.items.filter((i) => injected.has(i.id)).length;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex shrink-0 items-center gap-2 border-b border-outline-soft px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-t2 font-semibold text-ink">Preparación</h2>
          <p className="text-t1 text-muted">
            Inyecta avisos de prueba. Herramienta de preparación: no ocupa espacio
            durante la operación.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="btn btn-icon shrink-0"
          aria-label="Cerrar preparación"
        >
          ✕
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin px-4 py-3">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={autoBusy}
            onClick={() => void runScenario("dia1")}
            className="btn btn-primary"
          >
            Cargar día 1
          </button>
          <button
            type="button"
            disabled={autoBusy}
            onClick={() => void runScenario("dia2")}
            className="btn"
          >
            Cargar día 2
          </button>
          <button
            type="button"
            disabled={autoBusy}
            onClick={async () => {
              setAutoBusy(true);
              setError(null);
              try {
                await resetBoard();
                setLast(null);
                await reload();
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setAutoBusy(false);
              }
            }}
            className="btn"
          >
            Vaciar
          </button>
        </div>

        {error && (
          <p
            role="alert"
            className="mt-2 flex items-center gap-1.5 text-t1 font-medium text-danger"
          >
            <span aria-hidden="true" className="glyph">✖</span> {error}
          </p>
        )}

        {/* Contraste día 1 / día 2, medido y sin maquillar */}
        {contrast && (
          <p className="mt-2 text-t1 leading-snug text-ink-2">
            <strong className="font-medium text-ink">Día 1</strong>:{" "}
            {contrast.dia1.critical} crítico(s), agota{" "}
            <strong className="font-medium text-ink">{contrast.deficit1}</strong>.{" "}
            <strong className="font-medium text-ink">Día 2</strong>:{" "}
            {contrast.dia2.critical} críticos, rompe{" "}
            <strong className="font-medium text-danger">{contrast.deficit2}</strong>
            .
          </p>
        )}

        {/* Escenarios */}
        <div className="mt-3 flex flex-col gap-3">
          {forecasts.map(({ scenario, forecast }) => {
            const done = injectedCount(scenario);
            const meta = VERDICT[forecast.verdict];
            return (
              <section key={scenario.id}>
                <div className="flex items-baseline justify-between gap-2">
                  <h3 className="text-t2 font-semibold text-ink">
                    {scenario.name}
                  </h3>
                  <span className="mono text-t1 text-ink-2">
                    {done}/{scenario.items.length}
                  </span>
                </div>
                <p className={`mt-0.5 flex items-center gap-1.5 text-t1 ${meta.tone}`}>
                  <span aria-hidden="true" className="glyph">{meta.glyph}</span>
                  <span className="font-medium">{meta.label}</span>
                  {forecast.overflowCount > 0 && (
                    <span className="text-muted">
                      · {forecast.overflowCount} sin recursos
                    </span>
                  )}
                </p>

                <ul className="mt-1.5">
                  {scenario.items.map((item) => {
                    const isInjected = injected.has(item.id);
                    const isBusy = busyId === item.id;
                    return (
                      <li key={item.id} className="border-b border-outline-soft last:border-0">
                        <button
                          type="button"
                          disabled={busyId !== null || autoBusy}
                          onClick={() => void injectItem(item)}
                          aria-label={`Inyectar aviso: ${item.text}`}
                          className="flex w-full items-start gap-2 py-1.5 text-left disabled:opacity-60"
                        >
                          <span
                            aria-hidden="true"
                            className="shrink-0 pt-0.5 text-t1 text-muted"
                          >
                            {isInjected ? "✓" : isBusy ? "…" : "▷"}
                          </span>
                          <span className="min-w-0 text-t1 leading-snug text-ink-2">
                            {item.text}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
        </div>

        {/* Aviso manual */}
        <div className="mt-4 border-t border-outline-soft pt-3">
          <h3 className="card-title">Aviso manual</h3>
          <label className="mt-1.5 block">
            <span className="sr-only">Texto del ciudadano</span>
            <textarea
              value={text}
              onChange={(ev) => setText(ev.target.value)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
                  ev.preventDefault();
                  void submitManual();
                }
              }}
              rows={2}
              placeholder="p. ej. Una persona se ha caído en la zona sur"
              className="field resize-y"
            />
          </label>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <label className="text-t1 text-muted">
              Perfil
              <select
                value={perfil}
                onChange={(ev) => setPerfil(ev.target.value as PerfilColor)}
                className="field ml-1.5 inline-block w-auto py-0.5"
              >
                {PERFILES.map((p) => (
                  <option key={p} value={p}>
                    {PERFIL_LABEL[p]}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={busyId !== null || autoBusy || text.trim() === ""}
              onClick={() => void submitManual()}
              className="btn btn-primary"
            >
              Inyectar
            </button>
          </div>
          <p className="mt-1.5 text-t1 leading-snug text-muted">
            El perfil es categoría operativa, no un dato clínico: no se declara
            diagnóstico médico.
          </p>

          {last?.extract && (
            <div className="mt-2 rounded-lg bg-surface-low px-3 py-2" aria-live="polite">
              <p className="card-title">Extracto resultante</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <TriageChip color={last.extract.triage_color ?? "desconocido"} />
                <span className="inline-flex items-center gap-1 text-t1 text-ink-2">
                  <span aria-hidden="true" className="glyph">
                    {TYPE_GLYPH[last.extract.incident_type ?? "otro"]}
                  </span>
                  {INCIDENT_TYPE_LABEL[last.extract.incident_type ?? "otro"]}
                </span>
                <span className="text-t1 text-muted">{last.extract.sector}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
