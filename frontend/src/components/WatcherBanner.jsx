import { useCallback, useEffect, useState } from "react";

import { apiGet, apiPost } from "../lib/api.js";

/**
 * With the watcher stopped, every training action returns success and then
 * nothing happens, forever. That makes this the most important thing on screen.
 */
export default function WatcherBanner({ onChange }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const res = await apiGet("/watcher");
      setStatus(res);
      setError(null);
      onChange?.(res.running);
    } catch (e) {
      setError(e.message);
      setStatus(null);
      onChange?.(false);
    }
  }, [onChange]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);

  async function start() {
    setBusy(true);
    try {
      const res = await apiPost("/watcher/start", {});
      setStatus(res);
      onChange?.(res.running);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <Bar tone="red">
        <span>can&apos;t reach the watcher: {error}</span>
      </Bar>
    );
  }

  if (!status) return null;

  if (status.running && status.count > 1) {
    return (
      <Bar tone="amber">
        <span>
          <strong className="font-semibold">
            {status.count} job watchers are running.
          </strong>{" "}
          They compete for the same queue — a job may be picked up twice.
        </span>
      </Bar>
    );
  }

  if (status.running) {
    return (
      <Bar tone="green">
        <span>job watcher running</span>
      </Bar>
    );
  }

  return (
    <Bar tone="red">
      <span>
        <strong className="font-semibold">Job watcher is stopped.</strong> Jobs
        will queue and never run — submitting still returns success.
      </span>
      <button
        onClick={start}
        disabled={busy}
        className="shrink-0 rounded bg-red-800 px-3 py-1 text-xs font-medium text-red-50 hover:bg-red-700 disabled:opacity-50"
      >
        {busy ? "starting…" : "Start watcher"}
      </button>
    </Bar>
  );
}

function Bar({ tone, children }) {
  const tones = {
    red: "border-red-900 bg-red-950/50 text-red-200",
    amber: "border-amber-900/70 bg-amber-950/30 text-amber-200",
    green: "border-neutral-800 bg-neutral-900/50 text-neutral-500",
  };
  return (
    <div
      className={`flex items-center justify-between gap-4 rounded-lg border px-4 py-2 text-xs ${tones[tone]}`}
    >
      {children}
    </div>
  );
}
