import { useCallback, useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";

/** Row counts straight from observation_fact. `refreshKey` re-runs it. */
export default function VerifyPanel({ refreshKey = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setData(await apiGet("/verify-load"));
    } catch (e) {
      setError(e.message);
      setData(null);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, refreshKey]);

  return (
    <section className="rounded-lg border border-neutral-800 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-neutral-400">Database</h2>
        <button
          onClick={refresh}
          disabled={busy}
          className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:border-neutral-500 disabled:opacity-50"
        >
          {busy ? "checking…" : "refresh"}
        </button>
      </div>

      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

      {data && (
        <div className="mt-3 flex gap-8">
          <Stat label="facts" value={data.facts} />
          <Stat label="concepts" value={data.concepts} />
          {data.status !== "ok" && (
            <p className="self-end text-xs text-red-400">
              query failed — counts may be stale
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function Stat({ label, value }) {
  return (
    <div>
      <p className="text-2xl font-semibold tabular-nums">
        {value.toLocaleString()}
      </p>
      <p className="text-xs uppercase tracking-wide text-neutral-500">{label}</p>
    </div>
  );
}
