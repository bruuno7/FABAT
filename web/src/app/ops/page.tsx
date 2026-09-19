"use client";

/**
 * MANDO Ops — interfaz final conectada al backend del repositorio.
 *
 * RUTA: `/ops`. No sustituye ni modifica la consola de `/`: son dos pantallas
 * independientes que leen el MISMO backend.
 *
 * BACKEND (todo son rutas ya existentes en `web/src/app/api/`):
 *   · GET    /api/board                        → tablero completo (refresco 2,5 s)
 *   · POST   /api/demo/public-report           → inyectar un aviso
 *   · POST   /api/incidents/[id]/decision      → firmar la actuación
 *   · GET    /api/incidents/[id]               → (no usado aquí)
 *   · DELETE /api/incidents                    → vaciar el tablero
 *
 * PRINCIPIO DE DISEÑO: esta pantalla NO decide nada. Traduce el estado que el
 * backend ya calculó (`lib/board.ts` → `lib/allocate.ts`) a la forma del diseño
 * y devuelve las acciones del operador por las mismas rutas que usa la consola.
 * Cualquier invento de telemetría del mock (ETAs, «1x/2x», 142 unidades) se ha
 * sustituido por el dato real o se ha retirado.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./ops.css";

import { OpsHeader } from "@/components/ops/header";
import { OpsKpiCards } from "@/components/ops/kpi-cards";
import { OpsManifestTable } from "@/components/ops/manifest-table";
import { OpsMap } from "@/components/ops/ops-map";
import { OpsSidebar, type OpsTab } from "@/components/ops/sidebar";
import {
  OpsIncidentDrawer,
  OpsInjectionDrawer,
  OpsToast,
} from "@/components/ops/drawers";
import {
  OpsAnalyticsView,
  OpsFleetView,
  OpsIncidentsView,
  OpsRoutesView,
} from "@/components/ops/views";
import { useBoard, useNow } from "@/components/use-board";
import type { Channel, PerfilColor } from "@/lib/contract";
import { formatTime } from "@/lib/present";
import { SCENARIOS } from "@/lib/scenario";
import {
  decideIncident,
  injectReport,
  resetBoard,
  setIncidentStatus,
} from "@/lib/client-api";
import {
  boardCsv,
  buildMapModel,
  claimStats,
  deriveUnits,
  downloadCsv,
  filterManifest,
  fleetTotals,
  manifestRows,
  severityBuckets,
  type ManifestFilter,
} from "@/lib/ops";

type Drawer = "incident" | "injection" | null;

export default function OpsPage() {
  const { board, error, live, setLive, reload } = useBoard(2500);
  const now = useNow(15000);

  const [tab, setTab] = useState<OpsTab>("dashboard");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ManifestFilter>("todas");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<Drawer>(null);
  const [showLinks, setShowLinks] = useState(true);
  const [showLoad, setShowLoad] = useState(true);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [toast, setToast] = useState<{
    message: string;
    tone: "ok" | "danger";
  } | null>(null);

  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /*
   * Material Symbols llega por hoja de estilos externa. Si no está disponible
   * (demo sin red), el navegador pintaría la ligadura como palabra y ésta
   * desbordaría los botones redondos. Se comprueba la fuente y, si falta, el
   * atributo `data-icons="off"` la sustituye por un punto neutro.
   */
  const [iconsReady, setIconsReady] = useState(true);
  useEffect(() => {
    let active = true;
    const update = () => {
      if (!active) return;
      try {
        setIconsReady(document.fonts.check('24px "Material Symbols Outlined"'));
      } catch {
        setIconsReady(true);
      }
    };
    void document.fonts.ready.then(update).catch(update);
    const timer = setTimeout(update, 2500);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);

  /* ---------------------------------------------------------------- datos */

  const incidents = useMemo(() => board?.incidents ?? [], [board]);
  const units = useMemo(() => deriveUnits(board), [board]);
  const fleet = useMemo(() => fleetTotals(units), [units]);
  const stats = useMemo(() => claimStats(board), [board]);
  const buckets = useMemo(() => severityBuckets(incidents), [incidents]);
  const model = useMemo(
    () => buildMapModel(incidents, units, now),
    [incidents, units, now],
  );
  const rows = useMemo(
    () => manifestRows(incidents, units, now),
    [incidents, units, now],
  );
  const visibleRows = useMemo(
    () => filterManifest(rows, filter, query),
    [rows, filter, query],
  );

  const selected = useMemo(
    () => incidents.find((i) => i.correlation_id === selectedId) ?? null,
    [incidents, selectedId],
  );

  const criticalCount = useMemo(
    () =>
      incidents.filter(
        (i) =>
          i.status !== "resuelto" &&
          (i.extract?.triage_color === "negro" ||
            i.extract?.triage_color === "rojo"),
      ).length,
    [incidents],
  );

  const pending = useMemo(
    () => incidents.filter((i) => i.needs_card && i.status !== "resuelto"),
    [incidents],
  );

  /** Progreso de los escenarios de demo, derivado del tablero (sobrevive al refresco). */
  const scenarioProgress = useMemo(() => {
    const injected = new Set<string>();
    for (const incident of incidents) {
      if (incident.correlation_id.startsWith("sim-d")) {
        injected.add(incident.correlation_id.replace(/^sim-/, ""));
      }
    }
    const out = {} as Record<"dia1" | "dia2", { done: number; total: number }>;
    for (const scenario of SCENARIOS) {
      out[scenario.id] = {
        done: scenario.items.filter((item) => injected.has(item.id)).length,
        total: scenario.items.length,
      };
    }
    return out;
  }, [incidents]);

  /* -------------------------------------------------------------- acciones */

  const showToast = useCallback(
    (message: string, tone: "ok" | "danger" = "ok") => {
      setToast({ message, tone });
      if (toastTimer.current) clearTimeout(toastTimer.current);
      toastTimer.current = setTimeout(() => setToast(null), 3200);
    },
    [],
  );

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  const openIncident = useCallback((id: string) => {
    setSelectedId(id);
    setDrawer("incident");
    setActionError(null);
  }, []);

  const closeDrawer = useCallback(() => {
    setDrawer(null);
    setActionError(null);
  }, []);

  // Escape cierra el cajón abierto (mismo atajo que la consola de `/`).
  useEffect(() => {
    function onKeyDown(ev: KeyboardEvent) {
      if (ev.key === "Escape") closeDrawer();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeDrawer]);

  const confirm = useCallback(
    async (action: string, note?: string) => {
      const current = selected;
      if (!current || !action) return;
      setBusy(true);
      setActionError(null);
      try {
        await decideIncident(current.correlation_id, action, note);
        await reload();
        closeDrawer();
        showToast(`Firma registrada en ${current.correlation_id}: ${action}`);
      } catch (err) {
        setActionError((err as Error).message);
        showToast((err as Error).message, "danger");
      } finally {
        setBusy(false);
      }
    },
    [selected, reload, closeDrawer, showToast],
  );

  const injectManual = useCallback(
    async (text: string, perfil: PerfilColor, channel: Channel) => {
      setBusy(true);
      setActionError(null);
      try {
        const result = await injectReport({
          text,
          channel,
          perfil_color: perfil,
          display_name:
            channel === "telegram" ? "Mesa de inyección (Telegram)" : "Aviso manual",
        });
        await reload();
        if (result.correlation_id) {
          setSelectedId(result.correlation_id);
          setDrawer("incident");
        }
        showToast(
          `Aviso clasificado como ${
            result.extract?.triage_color ?? "sin triage"
          } en ${result.extract?.sector ?? "sector desconocido"}`,
        );
      } catch (err) {
        setActionError((err as Error).message);
        showToast((err as Error).message, "danger");
      } finally {
        setBusy(false);
      }
    },
    [reload, showToast],
  );

  const loadScenario = useCallback(
    async (id: "dia1" | "dia2") => {
      const scenario = SCENARIOS.find((s) => s.id === id);
      if (!scenario) return;
      setBusy(true);
      setActionError(null);
      try {
        const already = new Set(
          incidents
            .filter((i) => i.correlation_id.startsWith("sim-d"))
            .map((i) => i.correlation_id.replace(/^sim-/, "")),
        );
        for (const item of scenario.items) {
          if (already.has(item.id)) continue;
          await injectReport({
            text: item.text,
            channel: "webcall",
            perfil_color: item.perfil_color,
            display_name: item.reporter,
            location_hint: item.location_hint,
            correlation_id: `sim-${item.id}`,
          });
        }
        await reload();
        showToast(`${scenario.name}: escenario inyectado.`);
      } catch (err) {
        setActionError((err as Error).message);
        showToast((err as Error).message, "danger");
      } finally {
        setBusy(false);
      }
    },
    [incidents, reload, showToast],
  );

  const toggleResolved = useCallback(async () => {
    const current = selected;
    if (!current) return;
    const next = current.status === "resuelto" ? "nuevo" : "resuelto";
    setBusy(true);
    setActionError(null);
    try {
      await setIncidentStatus(current.correlation_id, next);
      await reload();
      showToast(
        next === "resuelto"
          ? `${current.correlation_id}: marcado como resuelto.`
          : `${current.correlation_id}: reabierto.`,
      );
    } catch (err) {
      setActionError((err as Error).message);
      showToast((err as Error).message, "danger");
    } finally {
      setBusy(false);
    }
  }, [selected, reload, showToast]);

  const reset = useCallback(async () => {
    setBusy(true);
    setActionError(null);
    try {
      await resetBoard();
      setSelectedId(null);
      await reload();
      showToast("Tablero vaciado.");
    } catch (err) {
      setActionError((err as Error).message);
      showToast((err as Error).message, "danger");
    } finally {
      setBusy(false);
    }
  }, [reload, showToast]);

  const exportCsv = useCallback(() => {
    const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
    downloadCsv(`mando-ops-manifiesto-${stamp}.csv`, boardCsv(board, units));
    showToast(`CSV exportado con ${incidents.length} aviso(s).`);
  }, [board, units, incidents.length, showToast]);

  /* ----------------------------------------------------------------- vista */

  return (
    <div
      data-icons={iconsReady ? "on" : "off"}
      className="ops-root flex h-dvh w-full overflow-hidden bg-[#eef2f8] font-sans text-[#0b1c30] antialiased"
    >
      {/*
        Iconografía del diseño. Se carga por hoja de estilos y no con
        `next/font` porque la familia no está en los datos de fuentes de Next.
        Si no hay red, el navegador pinta la ligadura como texto y ningún botón
        queda mudo.
      */}
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
        precedence="ops-icons"
      />

      <OpsSidebar
        tab={tab}
        onTab={setTab}
        fleetTotal={fleet.total}
        criticalCount={criticalCount}
        planBroken={board?.allocation.broken ?? false}
        operatorName="Operador Jefe MANDO"
        connected={board !== null}
      />

      <div className="flex flex-1 flex-col overflow-hidden bg-[#eef2f8]">
        <OpsHeader
          query={query}
          onQuery={setQuery}
          onInject={() => setDrawer("injection")}
          hrMode={board?.env.hr_mode ?? "simulated"}
          hrHook={board?.env.hr_hook_tg ?? false}
          telegramToken={board?.env.telegram_token ?? false}
          criticalCount={criticalCount}
          segment={filter}
          onSegment={(value) => setFilter(value as ManifestFilter)}
          serverTime={board ? formatTime(board.server_time) : null}
        />

        <div className="ops-scroll flex-1 space-y-6 overflow-x-hidden overflow-y-auto p-6">
          {error && (
            <p
              role="alert"
              className="rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-xs font-semibold text-red-700"
            >
              No se pudo consultar el tablero: {error}
            </p>
          )}

          {!board && !error && (
            <p className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-medium text-slate-500">
              Conectando con <span className="mono">/api/board</span>…
            </p>
          )}

          {tab === "dashboard" && (
            <>
              <div className="grid grid-cols-12 gap-6">
                <div className="col-span-12 flex lg:col-span-8">
                  <OpsMap
                    incidents={incidents}
                    model={model}
                    selectedId={selectedId}
                    onSelect={openIncident}
                    showLinks={showLinks}
                    onToggleLinks={() => setShowLinks((v) => !v)}
                    showLoad={showLoad}
                    onToggleLoad={() => setShowLoad((v) => !v)}
                    live={live}
                    onToggleLive={() => setLive(!live)}
                    totalUnits={fleet.total}
                    busyUnits={fleet.busy}
                  />
                </div>
                <OpsKpiCards stats={stats} buckets={buckets} fleet={fleet} />
              </div>

              <OpsManifestTable
                rows={visibleRows}
                selectedId={selectedId}
                onSelect={openIncident}
                onInject={() => setDrawer("injection")}
                onExport={exportCsv}
                totalCount={rows.length}
              />
            </>
          )}

          {tab === "fleet" && (
            <OpsFleetView fleet={fleet} incidents={incidents} />
          )}

          {tab === "incidents" && (
            <OpsIncidentsView
              board={board}
              pending={pending}
              onSelect={openIncident}
              onInject={() => setDrawer("injection")}
            />
          )}

          {tab === "routes" && (
            <OpsRoutesView model={model} fleet={fleet} />
          )}

          {tab === "analytics" && (
            <OpsAnalyticsView
              board={board}
              stats={stats}
              buckets={buckets}
              fleet={fleet}
            />
          )}

          <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
            <span className="mono">
              {incidents.length} aviso(s) · {units.length} unidad(es) ·{" "}
              {model.links.length} despacho(s)
            </span>
            <span>
              Conectado a <span className="mono">/api/board</span> · refresco{" "}
              {live ? "cada 2,5 s" : "en pausa"}
            </span>
            <span>
              Los identificadores se acortan solo al pintarlos: el id completo va
              en el atributo <span className="mono">title</span>.
            </span>
          </footer>
        </div>
      </div>

      <OpsIncidentDrawer
        incident={selected}
        units={units}
        open={drawer === "incident" && selected !== null}
        onClose={closeDrawer}
        onConfirm={(action, note) => void confirm(action, note)}
        onToggleResolved={() => void toggleResolved()}
        busy={busy}
        error={actionError}
      />

      <OpsInjectionDrawer
        open={drawer === "injection"}
        onClose={closeDrawer}
        onLoadScenario={(id) => void loadScenario(id)}
        onInjectManual={(text, perfil, channel) =>
          void injectManual(text, perfil, channel)
        }
        onReset={() => void reset()}
        progress={scenarioProgress}
        busy={busy}
        error={actionError}
      />

      <OpsToast
        message={toast?.message ?? ""}
        visible={toast !== null}
        tone={toast?.tone ?? "ok"}
      />
    </div>
  );
}
