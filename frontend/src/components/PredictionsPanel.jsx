import { useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";
import Warning, { Warnings } from "./Warning.jsx";

/** Prediction facts written back by an apply run. */
export default function PredictionsPanel({ code, targetCohort, refreshKey = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!code) return;
    let alive = true;
    setData(null);
    setError(null);
    const qs = targetCohort
      ? `?target_cohort=${encodeURIComponent(targetCohort)}`
      : "";
    apiGet(`/predictions/${code}${qs}`)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [code, targetCohort, refreshKey]);

  if (!code) return null;
  if (error) return <p className="text-xs text-red-400">{error}</p>;
  if (!data) return <p className="text-xs text-neutral-500">loading…</p>;

  return (
    <div className="space-y-3">
      <div className="flex gap-8">
        <div>
          <p className="text-2xl font-semibold tabular-nums">
            {data.total.toLocaleString()}
          </p>
          <p className="text-xs uppercase tracking-wide text-neutral-500">
            predicted positive
          </p>
        </div>
        {data.scored != null && (
          <div>
            <p className="text-2xl font-semibold tabular-nums text-neutral-400">
              {data.scored.toLocaleString()}
            </p>
            <p className="text-xs uppercase tracking-wide text-neutral-500">
              scored
            </p>
          </div>
        )}
      </div>

      <Warning>{data.note}</Warning>
      <Warnings items={data.warnings} />

      {data.patients.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-neutral-500">
            first {data.patients.length} patient numbers
          </p>
          <p className="max-h-32 overflow-auto rounded bg-neutral-900 p-2 text-xs tabular-nums text-neutral-400">
            {data.patients.join(", ")}
          </p>
        </div>
      )}
    </div>
  );
}
