"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChatPanel } from "@/components/chat-panel";
import { Feed } from "@/components/feed";
import { IncidentDetail } from "@/components/incident-detail";
import { IncidentTable } from "@/components/incident-table";
import { InjectionPanel } from "@/components/injection-panel";
import { MobileNav } from "@/components/mobile-nav";
import { ResourceMeter } from "@/components/resources";
import { SeverityChart } from "@/components/severity-chart";
import { Sidebar, type PanelId, type QueueFilter } from "@/components/sidebar";
import { TriageChip } from "@/components/ui";
import { VenueMap } from "@/components/venue-map";
import { useBoard, useNow } from "@/components/use-board";
import { DEFAULT_CAPACITY, RESOURCE_ORDER } from "@/lib/allocate";
import type { Board, BoardIncident } from "@/lib/board-types";
import { decideIncident, setIncidentStatus } from "@/lib/client-api";

/* ============================================================================
 * MANDO — UNA SOLA PANTALLA (`/`)
 *
 * Composición:
 *   ┌──────────┬────────────────────────────────────────────────┐
 *   │          │  BARRA SUPERIOR: título · indicadores · aviso   │
 *   │ SIDEBAR  ├──────────────────────────────┬─────────────────┤
 *   │  azul    │                              │  RECURSOS       │
 *   │  marino  │      MAPA DEL RECINTO        │  (compacto)     │
 *   │          │      (protagonista)          ├─────────────────┤
 *   │          │                              │  CHAT           │
 *   │          ├──────────────────────────────┤  (colapsable)   │
 *   │          │  COLA DE INCIDENTES (tabla)  │                 │
 *   └──────────┴──────────────────────────────┴─────────────────┘
 *
 * PRESUPUESTO DE SATURACIÓN (verificado en el informe):
 *   · REGIONES (3): sidebar · mapa+cola · columna derecha.
 *   · MAPA: 76% del ancho útil (medido a 1600 px).
 *   · COLUMNA DERECHA (2 tarjetas): Recursos + Chat.
 *   · BARRA SUPERIOR: 2 indicadores + 1 aviso (por debajo del máximo de 3+1).
 *   · Mapa: 12 marcadores como máximo, el resto agrupado en su sector.
 *   · Cola: 8 filas por defecto, el resto tras "Ver todos".
 *   · TIPOGRAFÍA: 3 tamaños (t1/t2/t3).
 *   · Paneles secundarios: SOLO UNO desplegado a la vez (chat XOR preparación
 *     XOR traza XOR detalle). El detalle se abre a demanda, nunca expandiendo
 *     una fila de la tabla.
 * ========================================================================== */

/* -------------------------------------------------------------------------- */
/*  Indicadores de la barra superior                                           */
/* -------------------------------------------------------------------------- */

function TopIndicators({ board }: { board: Board | null }) {
  /*
   * HIDRATACIÓN / SALTO DE LAYOUT: los tres indicadores se renderizan SIEMPRE,
   * también cuando `board` es `null` (servidor y primer render de cliente), con
   * un marcador «—» de ancho reservado. Antes se montaban condicionados a
   * `{board && …}`, así que aparecían tras el fetch y reflowaban la barra
   * superior (el buscador es `flex-1` y encogía de golpe).
   *
   * `board` es `null` en el servidor y en el primer render de cliente, así que
   * el marcado coincide y no hay desajuste. Después solo cambian las cifras.
   */
  const incidents = board?.incidents ?? [];
  const open = incidents.filter((i) => i.status !== "resuelto");
  const critical = open.filter((i) => {
    const t = i.extract?.triage_color;
    return t === "negro" || t === "rojo";
  }).length;
  const totalUnits = RESOURCE_ORDER.reduce((n, k) => n + DEFAULT_CAPACITY[k], 0);
  const freeUnits = board
    ? RESOURCE_ORDER.reduce((n, k) => n + board.allocation.remaining[k], 0)
    : null;

  /*
   * 3 indicadores (el máximo del presupuesto), todos calculados de los datos:
   *   ACTIVOS   · avisos abiertos
   *   CRÍTICOS  · gravedad vital o emergencia
   *   RECURSOS  · unidades libres / dotación total
   * COMPLIANCE: cada uno lleva glifo + etiqueta + cifra; el color solo refuerza.
   */
  const items = [
    {
      label: "Activos",
      value: board ? String(open.length) : "—",
      glyph: "▣",
      tone: "text-ink",
    },
    {
      label: "Críticos",
      value: board ? String(critical) : "—",
      glyph: critical > 0 ? "⚠" : "✓",
      tone: critical > 0 ? "text-danger" : "text-ink",
    },
    {
      label: "Recursos",
      value: freeUnits === null ? "—" : `${freeUnits}/${totalUnits}`,
      glyph: "▦",
      tone: "text-ink",
    },
  ];

  return (
    <dl className="flex items-center gap-4">
      {items.map((item) => (
        <div key={item.label} className="flex items-baseline gap-1.5">
          <dt className="text-t1 text-muted">{item.label}</dt>
          <dd
            className={`flex items-baseline gap-1 text-t3 font-semibold ${item.tone}`}
          >
            <span aria-hidden="true" className="glyph text-t1">
              {item.glyph}
            </span>
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function SaturationBanner({ board }: { board: Board | null }) {
  /*
   * HIDRATACIÓN / SALTO DE LAYOUT: la píldora se renderiza SIEMPRE, con un
   * estado neutro mientras no hay datos (`board === null` en servidor y primer
   * render de cliente → marcado idéntico). Antes se montaba condicionada a
   * `{board && …}` y al aparecer empujaba los botones de la barra superior.
   *
   * El estado neutro NO afirma nada sobre el plan: dice que aún no se sabe.
   */
  const broken = board?.allocation.broken ?? false;

  if (!board) {
    return (
      <span className="banner banner-neutral" role="status" aria-live="polite">
        <span aria-hidden="true" className="glyph">○</span>
        Plan · comprobando
      </span>
    );
  }

  if (!broken) {
    return (
      <span role="status" aria-live="polite" className="banner banner-calm">
        <span aria-hidden="true" className="glyph">✓</span>
        Plan cubierto
      </span>
    );
  }

  return (
    <span role="alert" aria-live="assertive" className="banner banner-broken">
      <span aria-hidden="true" className="alert-pulse glyph">✖</span>
      El plan ha dejado de valer
      <span className="font-normal">
        · {board.allocation.overflow.length} sin recursos
      </span>
    </span>
  );
}

/** Tarjeta flotante sobre el mapa: responde "¿tengo recursos?" de un vistazo. */
function FloatingCapacity({ board }: { board: Board }) {
  const { remaining, overflow } = board.allocation;
  const broken = overflow.length > 0;
  const totalLeft = Object.values(remaining).reduce((a, b) => a + b, 0);

  return (
    <div className="floating-card absolute bottom-3 right-3 w-[12.5rem] px-3 py-2.5">
      <p className="card-title">{broken ? "Plan sin capacidad" : "Capacidad"}</p>
      <p
        className={`mt-1 flex items-baseline gap-1.5 text-t3 font-semibold ${
          broken ? "text-danger" : "text-ok"
        }`}
      >
        <span aria-hidden="true" className="text-t2">
          {broken ? "✖" : "✓"}
        </span>
        {totalLeft} libre{totalLeft === 1 ? "" : "s"}
      </p>
      <p className="mt-1 text-t1 leading-snug text-muted">
        {broken
          ? `${overflow.length} aviso(s) sin cubrir`
          : "Demanda abierta cubierta"}
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Página                                                                     */
/* -------------------------------------------------------------------------- */

export default function ControlPage() {
  const { board, error, live, setLive, reload } = useBoard();
  const now = useNow();

  const [filter, setFilter] = useState<QueueFilter>("todas");
  const [query, setQuery] = useState("");
  /** Solo UN panel secundario abierto a la vez. */
  const [openPanel, setOpenPanel] = useState<PanelId | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [armedAction, setArmedAction] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const tableRef = useRef<HTMLTableSectionElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const incidents = useMemo(() => board?.incidents ?? [], [board]);

  /* --- Filtro de la cola + búsqueda (misma pantalla, no ruta) -------------- */
  const filtered = useMemo(() => {
    const open = incidents.filter((i) => i.status !== "resuelto");
    let base: BoardIncident[];
    switch (filter) {
      case "graves":
        base = open.filter((i) => {
          const t = i.extract?.triage_color;
          return t === "negro" || t === "rojo";
        });
        break;
      case "sin_recursos":
        base = open.filter((i) => !i.covered);
        break;
      case "por_sector":
        // "Por sector" ordena agrupando por sector, no filtra: es una vista.
        base = open
          .slice()
          .sort((a, b) =>
            (a.extract?.sector ?? "").localeCompare(
              b.extract?.sector ?? "",
              "es",
            ),
          );
        break;
      default:
        base = open;
    }

    const q = query.trim().toLowerCase();
    if (!q) return base;
    // Solo texto operativo: NO se busca por nombre de reportante (minimización).
    return base.filter((i) => {
      const e = i.extract ?? {};
      const haystack = [
        e.sector,
        e.summary,
        i.correlation_id,
        i.text,
        e.incident_type,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [incidents, filter, query]);

  // La selección es estable frente al refresco de 2,5 s: si el aviso sigue en el
  // tablero, sigue seleccionado. Si desaparece, cae a null sin tocar el foco.
  const selected = useMemo(
    () => incidents.find((i) => i.correlation_id === selectedId) ?? null,
    [incidents, selectedId],
  );
  const activeIndex = selected
    ? filtered.findIndex((i) => i.correlation_id === selected.correlation_id)
    : -1;

  const action = useMemo(() => {
    if (!selected) return "";
    if (armedAction && selected.suggested.includes(armedAction)) return armedAction;
    return selected.suggested[0] ?? "";
  }, [selected, armedAction]);

  const select = useCallback((id: string) => {
    setSelectedId(id);
    setOpenPanel("detalle");
    setArmedAction(null);
    setNote("");
    setActionError(null);
  }, []);

  const togglePanel = useCallback((p: PanelId) => {
    setOpenPanel((current) => (current === p ? null : p));
  }, []);

  const closePanel = useCallback(() => {
    setOpenPanel(null);
    setSelectedId(null);
    setArmedAction(null);
    setNote("");
    setActionError(null);
  }, []);

  const move = useCallback(
    (delta: number) => {
      if (filtered.length === 0) return;
      const from = activeIndex < 0 ? 0 : activeIndex;
      const next = Math.min(filtered.length - 1, Math.max(0, from + delta));
      select(filtered[next].correlation_id);
    },
    [filtered, activeIndex, select],
  );

  const confirm = useCallback(async () => {
    if (!selected || selected.status === "resuelto" || !action) return;
    setBusy(true);
    setActionError(null);
    try {
      await decideIncident(
        selected.correlation_id,
        action,
        note.trim() || undefined,
      );
      setNote("");
      setArmedAction(null);
      await reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [selected, action, note, reload]);

  const resolve = useCallback(async () => {
    if (!selected) return;
    setBusy(true);
    setActionError(null);
    try {
      await setIncidentStatus(
        selected.correlation_id,
        selected.status === "resuelto" ? "nuevo" : "resuelto",
      );
      await reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [selected, reload]);

  /* --- Atajos de teclado --------------------------------------------------- */
  useEffect(() => {
    function onKeyDown(ev: KeyboardEvent) {
      const target = ev.target as HTMLElement | null;
      const tag = target?.tagName;
      const typing =
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT" ||
        target?.isContentEditable === true;

      if (ev.key === "Escape") {
        if (typing) {
          target?.blur();
          return;
        }
        closePanel();
        return;
      }
      if (typing) return;
      if (ev.altKey || ev.ctrlKey || ev.metaKey) return;

      switch (ev.key) {
        case "ArrowDown":
        case "j":
        case "J":
          ev.preventDefault();
          move(1);
          return;
        case "ArrowUp":
        case "k":
        case "K":
          ev.preventDefault();
          move(-1);
          return;
        case "Home":
          ev.preventDefault();
          if (filtered.length > 0) select(filtered[0].correlation_id);
          return;
        case "End":
          ev.preventDefault();
          if (filtered.length > 0) {
            select(filtered[filtered.length - 1].correlation_id);
          }
          return;
        case "Enter":
          if (tag === "BUTTON" || tag === "A") return;
          ev.preventDefault();
          void confirm();
          return;
        case "r":
        case "R":
          ev.preventDefault();
          void resolve();
          return;
        case "p":
        case "P":
          ev.preventDefault();
          setLive(!live);
          return;
        case "/":
          ev.preventDefault();
          searchRef.current?.focus();
          return;
        case "c":
        case "C":
          ev.preventDefault();
          togglePanel("chat");
          return;
        case "t":
        case "T":
          ev.preventDefault();
          togglePanel("traza");
          return;
        default:
          if (/^[1-4]$/.test(ev.key)) {
            ev.preventDefault();
            const order: QueueFilter[] = [
              "todas",
              "graves",
              "sin_recursos",
              "por_sector",
            ];
            setFilter(order[Number(ev.key) - 1]);
          }
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    move,
    confirm,
    resolve,
    filtered,
    select,
    closePanel,
    togglePanel,
    live,
    setLive,
  ]);

  // Mantiene visible la fila activa sin provocar saltos de scroll.
  useEffect(() => {
    if (!selectedId) return;
    document
      .getElementById(`row-${selectedId}`)
      ?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  const tableHidden = filtered.length > 0 && filter !== "todas";
  const drawerOpen =
    openPanel === "detalle" || openPanel === "preparacion" || openPanel === "traza";

  return (
    <div className="flex min-h-0 flex-1 flex-col md:flex-row">
      <Sidebar
        incidents={incidents}
        filter={filter}
        onFilter={setFilter}
        openPanel={openPanel}
        onTogglePanel={togglePanel}
      />

      <MobileNav
        filter={filter}
        onFilter={setFilter}
        openPanel={openPanel}
        onTogglePanel={togglePanel}
      />

      <main
        id="contenido"
        className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 p-3 xl:overflow-hidden"
      >
        {/* ------------------------- BARRA SUPERIOR -------------------------
            3 indicadores + 1 aviso + buscador + acciones. Es el máximo del
            presupuesto: nada más entra aquí. */}
        <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="text-t3 font-semibold text-ink">Sala de control</h1>

          <label className="relative min-w-[11rem] flex-1 md:max-w-[18rem]">
            <span className="sr-only">Buscar por zona, tipo o ID</span>
            <span
              aria-hidden="true"
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[13px] text-outline"
            >
              ⌕
            </span>
            <input
              ref={searchRef}
              type="search"
              value={query}
              onChange={(ev) => setQuery(ev.target.value)}
              onKeyDown={(ev) => {
                if (ev.key === "Escape") {
                  setQuery("");
                  ev.currentTarget.blur();
                }
              }}
              placeholder="Buscar por zona, tipo o ID…"
              className="field pl-7"
            />
          </label>

          <TopIndicators board={board} />

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <SaturationBanner board={board} />            <button
              type="button"
              onClick={() => setLive(!live)}
              aria-pressed={live}
              className="btn btn-sm"
              title="Pausar o reanudar el refresco cada 2,5 s"
            >
              <span aria-hidden="true" className="glyph">{live ? "●" : "○"}</span>
              {live ? "En vivo" : "Pausado"}
            </button>
            <button
              type="button"
              aria-pressed={openPanel === "preparacion"}
              onClick={() => togglePanel("preparacion")}
              className="btn btn-sm"
            >
              <span aria-hidden="true" className="glyph">
                ⛁
              </span>
              Mesa de inyección
            </button>
          </div>
        </header>

        {error && (
          <p
            role="alert"
            className="flex shrink-0 items-center gap-1.5 text-t1 font-medium text-danger"
          >
            <span aria-hidden="true" className="glyph">✖</span> Error consultando el tablero: {error}
          </p>
        )}

        {/* ------------------- MAPA (con la cola debajo) · COLUMNA DERECHA ---- */}
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_var(--right-w)]">
          {/* Región 2: mapa + cola */}
          <div className="flex min-h-0 flex-col gap-3">
            <div className="relative flex min-h-[46vh] flex-1 flex-col overflow-hidden xl:min-h-0">
              <VenueMap
                incidents={filtered}
                selectedId={selected?.correlation_id ?? null}
                onSelect={select}
                className="flex-1"
              />
              {board && <FloatingCapacity board={board} />}
            </div>

            {/* Cola de incidentes: 8 filas por defecto */}
            <section
              className="card max-h-[42vh] shrink-0 xl:max-h-[34vh]"
              aria-labelledby="cola-title"
            >
              <header className="card-head">
                <h2 id="cola-title" className="card-title">
                  Cola priorizada
                </h2>
                <span className="text-t1 text-muted">
                  ↑ ↓ navegar · Enter decidir · R resolver
                </span>
              </header>
              <IncidentTable
                incidents={filtered}
                selectedId={selected?.correlation_id ?? null}
                onSelect={select}
                listRef={tableRef}
                now={now}
                emptyHint={
                  tableHidden
                    ? "Ningún aviso cumple este filtro. Vuelve a «Todas» en la barra lateral."
                    : undefined
                }
                className="min-h-0 flex-1"
              />
            </section>
          </div>

          {/* Región 3: columna derecha, 2 tarjetas */}
          <div className="flex min-h-0 flex-col gap-3">
            <section className="card shrink-0" aria-labelledby="recursos-title">
              <header className="card-head">
                <h2 id="recursos-title" className="card-title">
                  Recursos
                </h2>
              </header>
              <div className="card-body">
                {board ? (
                  <ResourceMeter board={board} />
                ) : (
                  <p className="text-t1 text-muted">Cargando…</p>
                )}
              </div>
            </section>

            <section
              className={`card flex flex-col ${openPanel === "chat" ? "min-h-0 flex-1" : "shrink-0"}`}
              aria-labelledby="chat-title"
            >
              <h2 id="chat-title" className="sr-only">
                Chat ciudadano
              </h2>
              <ChatPanel
                expanded={openPanel === "chat"}
                onToggle={() => togglePanel("chat")}
                onIncoming={() =>
                  // Al abrirse una conversación se despliega el chat. Si hay un
                  // cajón abierto, se cierra: solo una zona secundaria a la vez.
                  setOpenPanel((p) => (p === "chat" ? p : "chat"))
                }
                onResult={() => void reload()}
                className={openPanel === "chat" ? "min-h-0 flex-1" : ""}
              />

              {/* Cuando el chat está colapsado, la tarjeta sigue aportando la
                  pregunta "¿qué tan grave?": es el único micrográfico. */}
              {openPanel !== "chat" && board && (
                <div className="border-t border-outline-soft px-4 pb-3 pt-2.5">
                  <h3 className="card-title">Abiertos por gravedad</h3>
                  <div className="mt-2">
                    <SeverityChart incidents={board.incidents} />
                  </div>
                </div>
              )}
            </section>
          </div>
        </div>

        {/* ------------------- CAJONES A DEMANDA (uno a la vez) ------------------- */}
        {drawerOpen && (
          <aside
            className="drawer fixed inset-y-0 right-0 z-40 flex w-[min(24rem,100vw)] flex-col pt-3"
            aria-label={
              openPanel === "preparacion"
                ? "Preparación"
                : openPanel === "traza"
                  ? "Traza y patrones"
                  : "Detalle del incidente"
            }
          >
            {openPanel === "preparacion" ? (
              <InjectionPanel onClose={closePanel} />
            ) : openPanel === "traza" ? (
              <>
                <DrawerHead title="Traza y patrones" onClose={closePanel} />
                <div className="min-h-0 flex-1 overflow-y-auto scroll-thin px-4 py-3">
                  <Feed entries={board?.feed ?? []} limit={80} />

                  {board && board.lessons.length > 0 && (
                    <>
                      <h3 className="card-title mt-4">
                        Patrones del recinto ({board.lessons.length})
                      </h3>
                      <ul className="mt-2 flex flex-col gap-2">
                        {board.lessons.map((lesson) => (
                          <li
                            key={lesson.key}
                            className="rounded-lg bg-surface-low px-3 py-2"
                          >
                            <p className="flex items-baseline gap-2">
                              <span className="mono text-t1 font-semibold text-ink">
                                ×{lesson.count}
                              </span>
                              <span className="text-t1 font-medium text-ink-2">
                                {lesson.sector}
                              </span>
                            </p>
                            <p className="mt-0.5 text-t1 leading-snug text-muted">
                              {lesson.text}
                            </p>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
              </>
            ) : selected && board ? (
              <IncidentDetail
                incident={selected}
                action={action}
                onActionChange={setArmedAction}
                note={note}
                onNoteChange={setNote}
                onConfirm={() => void confirm()}
                onResolve={() => void resolve()}
                onClose={() => {
                  closePanel();
                  tableRef.current?.focus();
                }}
                busy={busy}
                error={actionError}
                decidedByDefault={board.decided_by_default ?? "Mesa MANDO"}
              />
            ) : (
              <>
                <DrawerHead title="Detalle del incidente" onClose={closePanel} />
                <p className="px-4 py-3 text-t1 text-muted">
                  Selecciona una fila de la cola o un marcador del mapa.
                </p>
              </>
            )}
          </aside>
        )}

        {/* Pie discreto: solo lo justo para saber de cuándo es el dato */}
        <footer className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 text-t1 text-muted">
          <span className="mono">
            {incidents.length} aviso(s)
            {filter !== "todas" && ` · ${filtered.length} en el filtro`}
          </span>
          {selected && (
            <span className="inline-flex items-center gap-1.5">
              seleccionado
              <TriageChip color={selected.extract?.triage_color ?? "desconocido"} />
            </span>
          )}
        </footer>
      </main>
    </div>
  );
}

function DrawerHead({ title, onClose }: { title: string; onClose: () => void }) {
  return (
    <header className="flex shrink-0 items-center gap-2 border-b border-outline-soft px-4 pb-2.5">
      <h2 className="text-t2 font-semibold text-ink">{title}</h2>
      <button
        type="button"
        onClick={onClose}
        className="btn btn-icon ml-auto"
        aria-label="Cerrar"
      >
        ✕
      </button>
    </header>
  );
}
