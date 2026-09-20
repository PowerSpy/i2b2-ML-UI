import { useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";
import { count } from "../lib/format.js";
import Callout from "../ui/Callout.jsx";
import { Stat } from "../ui/Meter.jsx";
import { Num, SectionLabel } from "../ui/Text.jsx";

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
    apiGet(`/predictions/${encodeURIComponent(code)}${qs}`)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [code, targetCohort, refreshKey]);

  if (!code) return null;
  if (error)
    return (
      <Callout tone="danger" title="could not read predictions">
        {error}
      </Callout>
    );
  if (!data) return <p className="text-[12px] text-text-muted">loading…</p>;

  return (
    <div className="space-y-4">
      <div className="flex gap-10">
        <Stat value={count(data.total)} label="predicted positive" />
        {data.scored != null && (
          <Stat value={count(data.scored)} label="scored" tone={undefined} />
        )}
      </div>

      <Callout tone="warn" title="absence is not a negative">
        {data.note}
      </Callout>

      {data.warnings.map((w) => (
        <Callout key={w} tone="danger" title="features missing">
          {w}
        </Callout>
      ))}

      {data.patients.length > 0 && (
        <div>
          <SectionLabel className="mb-1.5">
            first <Num>{data.patients.length}</Num> patient numbers
          </SectionLabel>
          <p className="max-h-32 overflow-auto rounded-row border border-border-soft bg-panel-sunk p-3 font-mono text-[11px] leading-relaxed tabular-nums text-text-3">
            {data.patients.join(", ")}
          </p>
        </div>
      )}
    </div>
  );
}
