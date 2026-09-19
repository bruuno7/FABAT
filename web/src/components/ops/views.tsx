"use client";

/**
 * Vistas secundarias de «MANDO Ops»: flota, triage, rutas/evacuación y analítica.
 *
 * NOTA DE HONESTIDAD: la vista de rutas NO inventa estado de viales. El backend
 * no publica telemetría de evacuación, así que se enseña el PLAN del recinto
 * (infraestructura declarada en `lib/venue.ts`) rotulado como referencia, y
 * aparte los enlaces unidad → aviso, que sí son asignaciones reales.
 */

import type { Board, BoardIncident } from "@/lib/board-types";
import {
  CHANNEL_LABEL,
  INCIDENT_TYPE_LABEL,
  TRIAGE_LABEL,
  type IncidentType,
  type TriageColor,
} from "@/lib/contract";
import {
  CHANNEL_GLYPH,
  formatTime,
  TYPE_GLYPH,
} from "@/lib/present";
import { EVAC_EXITS, GATES } from "@/lib/venue";
import {
  BUCKET_COLOR,
  FEED_TONE_CLASS,
  channelCounts,
  hrCallbackUrl,
  integrationRows,
  opsRef,
  telegramReports,
  type ClaimStats,
  type FleetTotals,
  type MapModel,
  type SeverityBucket,
} from "@/lib/ops";

/* ========================================================================== */
/*  1. Flota / Recursos                                                        */
/* ========================================================================== */

export function OpsFleetView({
  fleet,
  incidents,
}: {
  fleet: FleetTotals;
  incidents: BoardIncident[];
}) {
  const byId = new Map(incidents.map((i) => [i.correlation_id, i]));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900">
            Cuadrante operativo de flota y recursos
          </h2>
          <p className="text-xs text-slate-500">
            Estado real de la dotación declarada por el backend (no hay
            telemetría de posición)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-800">
            {fleet.total} unidades en plantilla
          </span>
          <span className="rounded-full bg-red-100 px-3 py-1 text-xs font-bold text-red-800">
            {fleet.busy} ocupadas
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
        {fleet.rows.map((row) => (
          <section
            key={row.kind}
            className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <span className="text-sm font-bold text-slate-900">{row.role}</span>
              <span
                className={`rounded-md px-2 py-0.5 text-xs font-bold ${
                  row.free === 0
                    ? "bg-red-100 text-red-700"
                    : "bg-emerald-100 text-emerald-700"
                }`}
              >
                {row.free}/{row.total} LIBRES
              </span>
            </div>

            {row.units.map((unit) => {
              const incident = unit.incidentId ? byId.get(unit.incidentId) : undefined;
              return (
                <div
                  key={unit.id}
                  className={`flex items-center justify-between rounded-xl border p-3 ${
                    unit.busy
                      ? "border-red-200 bg-red-50"
                      : "border-emerald-200 bg-emerald-50"
                  }`}
                >
                  <div className="min-w-0">
                    <div className="text-xs font-bold text-slate-900">{unit.id}</div>
                    <div className="truncate text-[11px] font-medium text-slate-600">
                      {incident
                        ? `${INCIDENT_TYPE_LABEL[
                            incident.extract?.incident_type ?? "otro"
                          ]} · ${incident.extract?.sector ?? "sin sector"}`
                        : `${row.role} en base`}
                    </div>
                  </div>
                  <div className="text-right">
                    <span
                      className={`font-mono text-xs font-bold ${
                        unit.busy ? "text-red-600" : "text-emerald-600"
                      }`}
                    >
                      {unit.busy ? "OCUPADA" : "DISPONIBLE"}
                    </span>
                    {incident && (
                      <div className="text-[10px] text-slate-500">
                        {opsRef(incident.correlation_id)}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {row.units.length === 0 && (
              <p className="text-[11px] text-slate-500">
                Sin unidades de este tipo en la dotación.
              </p>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}

/* ========================================================================== */
/*  2. Incidentes / Triage                                                     */
/* ========================================================================== */

const TONE_CLASS = FEED_TONE_CLASS;

export function OpsIncidentsView({
  board,
  pending,
  onSelect,
  onInject,
}: {
  board: Board | null;
  pending: BoardIncident[];
  onSelect: (id: string) => void;
  onInject: () => void;
}) {
  const incidents = board?.incidents ?? [];
  const integrations = integrationRows(board?.env);
  const telegram = telegramReports(incidents)
    .filter((i) => i.reply_text || i.text)
    .slice(-2)
    .reverse();
  const channels = channelCounts(incidents);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900">
            Mando Triage — cola unificada
          </h2>
          <p className="text-xs text-slate-500">
            Avisos que exigen firma humana y estado real de los canales de
            entrada
          </p>
        </div>
        <button
          type="button"
          onClick={onInject}
          className="flex items-center gap-1 rounded-xl bg-red-600 px-3.5 py-1.5 text-xs font-bold text-white transition-colors hover:bg-red-700"
        >
          <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
            add_alert
          </span>
          Inyectar aviso
        </button>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between text-sm font-bold text-slate-900">
            <span>Avisos pendientes de firma MANDO</span>
            <span className="text-xs font-medium text-slate-500">
              {pending.length} en cola
            </span>
          </div>

          {pending.length === 0 && (
            <p className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">
              Ningún aviso abierto exige tarjeta de decisión humana ahora mismo.
            </p>
          )}

          {pending.map((incident) => {
            const triage: TriageColor = incident.extract?.triage_color ?? "desconocido";
            return (
              <button
                key={incident.correlation_id}
                type="button"
                onClick={() => onSelect(incident.correlation_id)}
                className="w-full space-y-2 rounded-xl border border-red-200 bg-red-50 p-4 text-left transition-colors hover:bg-red-100"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-bold text-red-700">
                    {opsRef(incident.correlation_id)} ·{" "}
                    {INCIDENT_TYPE_LABEL[
                      incident.extract?.incident_type ?? "otro"
                    ].toUpperCase()}
                  </span>
                  <span
                    className="rounded px-2 py-0.5 text-[10px] font-bold text-white"
                    style={{ background: BUCKET_COLOR[triage] }}
                  >
                    {TRIAGE_LABEL[triage].toUpperCase()}
                  </span>
                </div>
                <p className="text-xs font-medium text-slate-700">
                  {incident.extract?.summary ?? incident.text ?? "Sin resumen"}
                </p>
                <div className="text-[11px] font-bold text-red-600">
                  {incident.covered
                    ? "Con recursos asignados. Falta la firma de la mesa."
                    : "Sin recursos disponibles. Requiere decisión de firma."}
                </div>
              </button>
            );
          })}
        </section>

        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between text-sm font-bold text-slate-900">
            <span>Integración HappyRobot &amp; Telegram</span>
            <span className="text-xs font-medium text-slate-500">
              {integrations.filter((r) => r.ok).length}/{integrations.length}{" "}
              activas
            </span>
          </div>

          <ul className="space-y-1.5">
            {integrations.map((row) => (
              <li
                key={row.key}
                className="flex items-start justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
              >
                <span className="flex items-start gap-2 text-[11px]">
                  <span
                    aria-hidden="true"
                    className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                      row.ok ? "bg-emerald-500" : "bg-amber-500"
                    }`}
                  />
                  <span>
                    <span className="block font-bold text-slate-800">
                      {row.label}
                    </span>
                    <span className="block text-slate-500">{row.detail}</span>
                  </span>
                </span>
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                    row.ok
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-amber-100 text-amber-800"
                  }`}
                >
                  {row.ok ? "OK" : "FALTA"}
                </span>
              </li>
            ))}
          </ul>

          <div className="rounded-lg border border-slate-200 px-3 py-2 text-[11px]">
            <span className="block font-bold text-slate-800">
              URL que debe llamar HappyRobot
            </span>
            <span className="mono block truncate text-slate-500" title={hrCallbackUrl(board?.env)}>
              {hrCallbackUrl(board?.env)}
            </span>
            <span className="mt-0.5 block text-slate-400">
              Callback de vuelta en <span className="mono">/api/hr/events</span> ·
              webhook del bot en <span className="mono">/api/telegram/webhook</span>
            </span>
          </div>

          {channels.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-3">
              <span className="text-[11px] font-bold text-slate-700">
                Avisos por canal:
              </span>
              {channels.map((c) => (
                <span
                  key={c.channel}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600"
                >
                  <span aria-hidden="true" className="glyph">
                    {CHANNEL_GLYPH[c.channel]}
                  </span>
                  {CHANNEL_LABEL[c.channel]}
                  <span className="mono font-bold text-slate-800">{c.count}</span>
                </span>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between text-sm font-bold text-slate-900">
          <span>Bot de Telegram — avisos del público</span>
          <span className="text-xs font-medium text-slate-500">
            {telegram.length} reciente(s)
          </span>
        </div>

        {telegram.length === 0 && (
          <p className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
            Todavía no ha entrado ningún aviso por <span className="mono">/api/telegram/webhook</span>.
            Si el bot no está conectado, en la Mesa de inyección puedes elegir el
            canal «Telegram» para recorrer el mismo camino.
          </p>
        )}

        {telegram.map((incident) => (
          <div
            key={incident.correlation_id}
            className="space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] text-slate-500">
                {opsRef(incident.correlation_id)} · chat{" "}
                {incident.reporter?.chat_id ?? "—"}
              </span>
              <span className="text-[10px] text-slate-400">
                {formatTime(incident.reported_at)}
              </span>
            </div>
            <p className="text-slate-800 italic">
              “{incident.text ?? incident.extract?.summary ?? "—"}”
            </p>
            {incident.reply_text && (
              <p className="rounded-lg bg-white p-2 text-[11px] text-slate-700">
                <span className="font-semibold">
                  Respuesta que se envía al ciudadano:{" "}
                </span>
                {incident.reply_text}
              </p>
            )}
            <div className="flex items-center justify-between border-t border-slate-200 pt-2">
              <span className="font-bold text-emerald-700">
                Triage {TRIAGE_LABEL[incident.extract?.triage_color ?? "desconocido"]}
              </span>
              <button
                type="button"
                onClick={() => onSelect(incident.correlation_id)}
                className="font-bold text-blue-600 hover:underline"
              >
                Abrir ficha
              </button>
            </div>
          </div>
        ))}

        <p className="text-[10px] leading-snug text-slate-400">
          El texto de respuesta vive en el aviso, pero el backend no guarda el
          acuse de entrega de Telegram: no se muestra «entregado» porque no hay
          dato que lo sostenga.
        </p>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-bold text-slate-900">Traza reciente</h3>
        <ul className="mt-2 space-y-1.5">
          {(board?.feed ?? []).slice(0, 10).map((entry) => (
            <li
              key={entry.id}
              className={`border-l-2 py-0.5 pl-2 text-[11px] leading-snug ${
                TONE_CLASS[entry.tone] ?? TONE_CLASS.info
              }`}
            >
              <span className="mono text-slate-400">{formatTime(entry.at)}</span>{" "}
              {entry.text}
            </li>
          ))}
          {(board?.feed ?? []).length === 0 && (
            <li className="text-[11px] text-slate-500">
              Sin eventos todavía.
            </li>
          )}
        </ul>
      </section>
    </div>
  );
}

/* ========================================================================== */
/*  3. Rutas & Evacuación                                                      */
/* ========================================================================== */

export function OpsRoutesView({
  model,
  fleet,
}: {
  model: MapModel;
  fleet: FleetTotals;
}) {
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-slate-900">
          Plan de evacuación del recinto
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Infraestructura declarada en el plano del recinto. Es{" "}
          <strong className="font-semibold">referencia del plan</strong>, no
          telemetría: el backend no publica estado de viales.
        </p>
        <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {EVAC_EXITS.map((exit) => (
            <div
              key={exit.id}
              className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center"
            >
              <div className="text-xs font-bold text-slate-800">{exit.id}</div>
              <div className="text-[11px] font-semibold text-slate-500">
                Salida señalizada
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-5">
          {GATES.map((gate) => (
            <div
              key={gate.id}
              className="rounded-xl border border-slate-200 p-3 text-center"
            >
              <div className="text-xs font-bold text-slate-800">{gate.label}</div>
              <div className="text-[11px] text-slate-500">{gate.sub}</div>
              {gate.diverted && (
                <div className="mt-1 text-[10px] font-bold text-amber-700">
                  Desvío declarado
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-bold text-slate-900">
          Despachos activos ({model.links.length})
        </h3>
        <p className="mt-0.5 text-xs text-slate-500">
          Enlaces unidad → aviso generados por la asignación real. Sin ETA: el
          backend no estima tiempos de llegada.
        </p>
        {model.links.length === 0 ? (
          <p className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
            No hay ninguna unidad despachada. {fleet.free} de {fleet.total}{" "}
            unidades siguen en base.
          </p>
        ) : (
          <ul className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
            {model.links.map((link) => (
              <li
                key={`${link.unitId}-${link.incidentId}`}
                className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
              >
                <span className="font-mono font-bold text-slate-800">
                  {link.unitId}
                </span>
                <span aria-hidden="true" className="text-slate-400">
                  →
                </span>
                <span className="font-mono font-semibold text-blue-700">
                  {link.ref}
                </span>
                <span
                  className="rounded px-1.5 py-0.5 text-[10px] font-bold text-white"
                  style={{ background: BUCKET_COLOR[link.triage] }}
                >
                  {TRIAGE_LABEL[link.triage]}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/* ========================================================================== */
/*  4. Analítica & Tiempos                                                     */
/* ========================================================================== */

export function OpsAnalyticsView({
  board,
  stats,
  buckets,
  fleet,
}: {
  board: Board | null;
  stats: ClaimStats;
  buckets: SeverityBucket[];
  fleet: FleetTotals;
}) {
  const incidents = board?.incidents ?? [];
  const byType = new Map<IncidentType, number>();
  for (const incident of incidents) {
    const type = incident.extract?.incident_type ?? "otro";
    byType.set(type, (byType.get(type) ?? 0) + 1);
  }
  const typeRows = [...byType.entries()].sort((a, b) => b[1] - a[1]);

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-slate-900">
          Analítica de tiempos y rendimiento
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Consolidado del turno. Toda cifra lleva su N; no hay SLA declarado.
        </p>

        <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
          <Metric
            label="Tiempo mediano hasta la firma"
            value={
              stats.medianAssignMin === null
                ? "—"
                : `${stats.medianAssignMin.toFixed(1)} min`
            }
            note={`N = ${stats.assignedCount} aviso(s) con decisión firmada`}
          />
          <Metric
            label="Avisos abiertos"
            value={`${stats.open}`}
            note={`${stats.covered} con recursos · ${stats.uncovered} sin recursos`}
          />
          <Metric
            label="Avisos cerrados"
            value={`${stats.resolved}`}
            note={`de ${incidents.length} aviso(s) recibidos en el turno`}
          />
          <Metric
            label="Ocupación de la dotación"
            value={`${fleet.total === 0 ? "—" : Math.round((fleet.busy / fleet.total) * 100)}%`}
            note={`${fleet.busy}/${fleet.total} unidades · N = ${fleet.total}`}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-bold text-slate-900">
            Reparto por gravedad
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Avisos abiertos (N = {buckets.reduce((n, b) => n + b.count, 0)})
          </p>
          <ul className="mt-3 space-y-2">
            {buckets.map((bucket) => (
              <li key={bucket.key} className="flex items-center gap-3 text-xs">
                <span
                  aria-hidden="true"
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ background: bucket.color }}
                />
                <span className="w-32 font-medium text-slate-700">
                  {bucket.label}
                </span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <span
                    className="block h-full rounded-full"
                    style={{
                      width: `${bucket.pct}%`,
                      background: bucket.color,
                    }}
                  />
                </span>
                <span className="mono w-16 text-right font-semibold text-slate-800">
                  {bucket.count} ({bucket.pct}%)
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-bold text-slate-900">Reparto por tipo</h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Avisos recibidos (N = {incidents.length})
          </p>
          {typeRows.length === 0 ? (
            <p className="mt-3 text-xs text-slate-500">
              Sin avisos en el turno todavía.
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {typeRows.map(([type, count]) => (
                <li
                  key={type}
                  className="flex items-center justify-between text-xs"
                >
                  <span className="flex items-center gap-2 font-medium text-slate-700">
                    <span aria-hidden="true" className="glyph text-slate-500">
                      {TYPE_GLYPH[type]}
                    </span>
                    {INCIDENT_TYPE_LABEL[type]}
                  </span>
                  <span className="mono font-semibold text-slate-800">
                    {count}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <span className="text-xs font-bold tracking-wide text-slate-500 uppercase">
        {label}
      </span>
      <div className="mt-1 text-2xl font-black text-slate-900">{value}</div>
      <span className="text-[11px] font-medium text-slate-500">{note}</span>
    </div>
  );
}
