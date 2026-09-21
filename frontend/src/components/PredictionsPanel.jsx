import { useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";
import { downloadCsv } from "../lib/csv.js";
import { count, plural } from "../lib/format.js";
import Button from "../ui/Button.jsx";
import Callout from "../ui/Callout.jsx";
import { Stat } from "../ui/Meter.jsx";
import { Num, SectionLabel } from "../ui/Text.jsx";

// How many patient numbers to pull back. Large enough that the panel is the
// whole result rather than a sample, small enough to stay one request.
const LIMIT = 10000;

/** Prediction facts written back by an apply run. */
export default function PredictionsPanel({ code, targetCohort, refreshKey = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!code) return;
    let alive = true;
    setData(null);
    setError(null);
    // The endpoint defaults to 100 patients, which made a 5,000-patient
    // result unretrievable from here. Ask for the lot; the response is a list
    // of patient numbers, so even a large set is small.
    const params = new URLSearchParams({ limit: String(LIMIT) });
    if (targetCohort) params.set("target_cohort", targetCohort);
    const qs = `?${params}`;
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
          <div className="mb-1.5 flex items-baseline justify-between gap-3">
            <SectionLabel>
              <Num>{count(data.patients.length)}</Num> predicted-positive
              {" "}
              {plural(data.patients.length, "patient number")}
              {data.total > data.patients.length && (
                <> — of <Num>{count(data.total)}</Num>, truncated</>
              )}
            </SectionLabel>
            <Button
              onClick={() =>
                downloadCsv(
                  `${code}_predictions.csv`,
                  ["patient_num"],
                  data.patients.map((pn) => [pn]),
                )
              }
            >
              export csv
            </Button>
          </div>
          <p className="max-h-32 overflow-auto rounded-row border border-border-soft bg-panel-sunk p-3 font-mono text-[11px] leading-relaxed tabular-nums text-text-3">
            {data.patients.join(", ")}
          </p>
        </div>
      )}
    </div>
  );
}
