"use client";

/**
 * Barra superior de «MANDO Ops»: buscador, estado del canal y acciones.
 * El punto rojo de notificaciones aparece solo si hay avisos críticos abiertos
 * (dato real), no de forma permanente como en el mock.
 */

/**
 * Estado de una integración. El color NO va solo: lleva punto + etiqueta +
 * texto del estado, y el detalle largo en el `title`.
 */
function IntegrationPill({
  label,
  ok,
  okText,
  offText,
  title,
}: {
  label: string;
  ok: boolean;
  okText: string;
  offText: string;
  title: string;
}) {
  return (
    <span
      title={title}
      className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium ${
        ok
          ? "border-slate-200 bg-slate-50 text-slate-600"
          : "border-amber-200 bg-amber-50 text-amber-800"
      }`}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-amber-500"}`}
      />
      <span className="font-semibold">{label}</span>
      <span>{ok ? okText : offText}</span>
    </span>
  );
}

export function OpsHeader({
  query,
  onQuery,
  onInject,
  hrMode,
  hrHook,
  telegramToken,
  criticalCount,
  segment,
  onSegment,
  serverTime,
}: {
  query: string;
  onQuery: (value: string) => void;
  onInject: () => void;
  hrMode: "live" | "simulated";
  hrHook: boolean;
  telegramToken: boolean;
  criticalCount: number;
  segment: string;
  onSegment: (value: string) => void;
  serverTime: string | null;
}) {
  return (
    <header className="z-20 flex h-[60px] shrink-0 items-center justify-between border-b border-slate-200/80 bg-white px-6">
      <div className="relative w-[380px] max-w-[46vw]">
        <span
          aria-hidden="true"
          className="material-symbols-outlined absolute top-1/2 left-3.5 -translate-y-1/2 text-[19px] text-slate-400"
        >
          search
        </span>
        <label className="sr-only" htmlFor="ops-search">
          Buscar avisos por sector, tipo o identificador
        </label>
        <input
          id="ops-search"
          value={query}
          onChange={(ev) => onQuery(ev.target.value)}
          placeholder="Buscar avisos por sector, tipo o ID…"
          className="h-9 w-full rounded-full border border-slate-200 bg-slate-100 pr-4 pl-10 text-[13px] font-medium text-slate-800 transition-all placeholder:text-slate-400 hover:bg-slate-100/80 focus:border-transparent ring-blue-500 focus:ring-2 focus:outline-none"
          type="search"
        />
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <IntegrationPill
            label="HappyRobot"
            ok={hrMode === "live"}
            okText="en vivo"
            offText="simulado"
            title={
              hrMode === "live"
                ? "Los avisos salen al Incoming Hook de HappyRobot"
                : "Sin HR_HOOK_TG: el tramo HappyRobot se genera local"
            }
          />
          <IntegrationPill
            label="Telegram"
            ok={telegramToken}
            okText="bot activo"
            offText="sin token"
            title={
              telegramToken
                ? "TELEGRAM_BOT_TOKEN configurado: se responde al ciudadano"
                : "Sin TELEGRAM_BOT_TOKEN no se responde por Telegram"
            }
          />
          {/* La caída del Incoming Hook deja HR en modo simulado aunque haya
              canal: se avisa aparte para no dar por bueno un envío que no sale. */}
          {hrMode === "live" && !hrHook && (
            <span
              className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-800"
              title="Modo en vivo sin Incoming Hook configurado"
            >
              Hook HR sin configurar
            </span>
          )}
        </div>

        <div className="h-5 w-[1px] bg-slate-200" />

        <label className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
          <span className="sr-only">Filtrar el manifiesto</span>
          <select
            value={segment}
            onChange={(ev) => onSegment(ev.target.value)}
            className="h-8 rounded-full border border-slate-200 bg-slate-50 px-2.5 text-xs font-medium text-slate-700"
          >
            <option value="todas">Todos los avisos</option>
            <option value="abiertos">Solo abiertos</option>
            <option value="criticos">Solo críticos</option>
            <option value="sin_recursos">Sin recursos</option>
          </select>
        </label>

        <span className="relative flex h-8 w-8 items-center justify-center rounded-full text-slate-600">
          <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
            notifications
          </span>
          {criticalCount > 0 && (
            <>
              <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-red-500 ring-2 ring-white" />
              <span className="sr-only">
                {criticalCount} aviso(s) crítico(s) abierto(s)
              </span>
            </>
          )}
        </span>

        <button
          type="button"
          onClick={onInject}
          className="flex h-8 w-8 items-center justify-center rounded-full text-slate-600 transition-colors hover:bg-slate-100"
          title="Mesa de inyección de avisos"
        >
          <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
            tune
          </span>
          <span className="sr-only">Abrir la mesa de inyección</span>
        </button>

        <span
          className="flex h-8 w-8 items-center justify-center rounded-full text-slate-600"
          title="Consola de operación en /"
        >
          <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
            help_outline
          </span>
        </span>

        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-tr from-blue-700 to-indigo-500 text-xs font-bold text-white shadow-sm">
          OP
        </div>

        <span className="mono hidden text-[11px] text-slate-400 2xl:inline" title="Hora del servidor">
          {serverTime ?? "—"}
        </span>
      </div>
    </header>
  );
}
