(function (root) {
  "use strict";

  function snapshotGate({ revision = "revision", session = () => "operational", onReset = () => {} } = {}) {
    let current = null;
    const retired = new Set();
    return {
      accept(next) {
        if (!next || !Number.isSafeInteger(next[revision]) || next[revision] < 0) return false;
        const id = session(next);
        if (!id || retired.has(id)) return false;
        if (current) {
          const previous = session(current);
          if (id === previous && next[revision] < current[revision]) return false;
          if (id !== previous) {
            retired.add(previous);
            onReset();
          }
        }
        current = next;
        return true;
      },
      current: () => current,
    };
  }

  function connect({ stateURL, streamURL, accept, onStatus, fetcher = root.fetch.bind(root),
    Source = root.EventSource, later = root.setTimeout.bind(root), cancel = root.clearTimeout.bind(root), staleAfter = 0 }) {
    let source = null, timer = null, retry = null, health = null, stopped = false, inFlight = null;
    let streamSerial = 0, delay = 2000, live = false, stateFailed = false;

    // El SSE del servidor usa comentarios keepalive, invisibles a EventSource.
    // Una lectura de verificación acotada detecta conexiones silenciosamente congeladas.
    function armHealth() {
      cancel(health); health = null;
      if (stopped || !live || staleAfter <= 0) return;
      health = later(() => {
        health = null;
        onStatus("stale");
        refresh(true).finally(armHealth);
      }, staleAfter);
    }

    function schedulePoll() {
      if (stopped || live || timer !== null) return;
      timer = later(() => {
        timer = null;
        refresh().finally(schedulePoll);
      }, delay);
    }

    async function readState(serial) {
      const controller = new AbortController();
      const timeout = later(() => controller.abort(), 10000);
      try {
        const response = await fetcher(stateURL, { credentials: "same-origin", cache: "no-store", signal: controller.signal });
        if (response.status === 401 || response.status === 403) {
          stop();
          onStatus("auth");
          return false;
        }
        if (!response.ok) throw new Error("state unavailable");
        const state = await response.json();
        if (stopped || serial !== streamSerial) return false;
        const accepted = accept(state);
        stateFailed = false;
        if (accepted) {
          delay = 2000;
          onStatus(live ? "live" : "poll");
          armHealth();
        }
        return accepted;
      } catch {
        if (!stopped && serial === streamSerial) {
          live = false;
          stateFailed = true;
          cancel(health); health = null;
          delay = Math.min(delay * 2, 15000);
          onStatus("offline");
          schedulePoll();
          scheduleReconnect();
        }
        return false;
      } finally {
        cancel(timeout);
      }
    }

    function refresh(fresh = false) {
      if (stopped) return Promise.resolve(false);
      if (fresh && inFlight) return inFlight.then(() => refresh());
      if (!inFlight) inFlight = readState(streamSerial).finally(() => { inFlight = null; });
      return inFlight;
    }

    function openStream() {
      if (stopped || !Source) return;
      if (source) source.close();
      let active;
      try {
        active = source = new Source(streamURL);
      } catch {
        live = false;
        onStatus("offline");
        schedulePoll();
        scheduleReconnect();
        return;
      }
      active.addEventListener("state", (event) => {
        if (stopped || active !== source) return;
        try {
          if (!accept(JSON.parse(event.data))) return;
          streamSerial += 1;
          live = true;
          delay = 2000;
          cancel(timer); timer = null;
          cancel(retry); retry = null;
          onStatus("live");
          armHealth();
        } catch {
          active.onerror();
        }
      });
      active.onerror = () => {
        if (stopped || active !== source) return;
        live = false;
        cancel(health); health = null;
        onStatus(stateFailed ? "offline" : "reconnecting");
        schedulePoll();
        scheduleReconnect();
      };
      scheduleReconnect();
    }

    function scheduleReconnect() {
      if (retry !== null || stopped || !Source) return;
      retry = later(() => {
        retry = null;
        if (!live) openStream();
      }, 15000);
    }

    function stop() {
      stopped = true;
      if (source) source.close();
      cancel(timer); cancel(retry); cancel(health);
    }

    onStatus("connecting");
    refresh().finally(schedulePoll);
    openStream();
    return { refresh, stop };
  }

  root.SALA_SYNC = { snapshotGate, connect };
})(typeof window === "undefined" ? globalThis : window);
