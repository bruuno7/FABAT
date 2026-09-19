import "server-only";
import { allocate } from "./allocate";
import { RESOURCE_LABEL } from "./allocate";
import type { Store } from "./store";

/**
 * Vigila la saturación y avisa cuando el plan deja de valer.
 * Se compara una firma para no repetir el mismo aviso en cada ingesta.
 */
const state = globalThis as unknown as { __mandoPlanSig?: string };

export function syncPlanFeed(store: Store, force = false): void {
  const allocation = allocate(store.list());
  const sig = allocation.signature;
  const prev = state.__mandoPlanSig ?? "";
  if (!force && sig === prev) return;
  const wasBroken = prev !== "";
  state.__mandoPlanSig = sig;

  if (!sig) {
    if (force || wasBroken) {
      store.notify(
        "Plan cubierto: toda la demanda abierta tiene recursos asignados.",
        "plan_ok",
        "ok",
      );
    }
    return;
  }

  const detail = allocation.overflow
    .slice(0, 3)
    .map((o) => {
      const missing = o.missing.map((m) => RESOURCE_LABEL[m]).join(" + ");
      return `falta ${missing}`;
    })
    .join(" · ");

  store.notify(
    `El plan ha dejado de valer: ${allocation.overflow.length} aviso(s) sin recursos (${detail}).`,
    "plan_broken",
    "danger",
  );
}

/** Al vaciar el tablero hay que olvidar la firma anterior. */
export function resetPlanSignature(): void {
  state.__mandoPlanSig = "";
}
