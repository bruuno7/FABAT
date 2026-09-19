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
    Source = root.EventSource, later = root.setTimeout.bind(root), cancel = root.clearTimeout.bind(root) }) {
    let source = null, timer = null, retry = null, stopped = false, inFlight = null;
    let streamSerial = 0, delay = 2000, live = false;

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
        if (accepted) {
          delay = 2000;
          if (!live) onStatus("poll");
        }
        return accepted;
      } catch {
        if (!stopped && !live) {
          delay = Math.min(delay * 2, 15000);
          onStatus("offline");
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
        } catch {
          active.onerror();
        }
      });
      active.onerror = () => {
        if (stopped || active !== source) return;
        live = false;
        onStatus("reconnecting");
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
      cancel(timer); cancel(retry);
    }

    onStatus("connecting");
    refresh().finally(schedulePoll);
    openStream();
    return { refresh, stop };
  }

  root.SALA_SYNC = { snapshotGate, connect };
})(typeof window === "undefined" ? globalThis : window);
