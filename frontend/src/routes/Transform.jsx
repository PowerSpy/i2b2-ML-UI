import { useEffect, useState } from "react";

import { Centre, LeftRail, RightRail } from "../layout/Shell.jsx";
import { apiDelete, apiGet, apiPost, apiPut } from "../lib/api.js";
import { count } from "../lib/format.js";
import { Link, useRoute } from "../lib/router.jsx";
import PipelineRailStub from "../panels/PipelineRailStub.jsx";
import Button from "../ui/Button.jsx";
import Callout, { Empty, Failed } from "../ui/Callout.jsx";
import { Card, CardHeader, Row } from "../ui/Card.jsx";
import CodeEditor from "../ui/CodeEditor.jsx";
import { Dot, Pill } from "../ui/Status.jsx";
import { Table, Td, Th } from "../ui/Table.jsx";
import { Heading, Mono, Note, Num } from "../ui/Text.jsx";

const TEMPLATE = `def transform(df):
    """Engineer features for this model.

    df   one row per patient, one column per concept code.
         Missing values are NaN. Keep the index you are given - patient
         numbers are matched back by it after this returns.

    Return the DataFrame. Every column must be numeric and finite.
    """
    return df
`;

/**
 * Write a feature transform, and run it against data that is not real.
 *
 * The frame here is generated from the published data dictionary, so nothing
 * on this page has ever been a patient row. That is why it shows output: when
 * this same code runs against real data it will report counts and nothing
 * else. The two must not look alike.
 */
export default function Transform() {
  const { params } = useRoute();
  const code = params.code;

  const [source, setSource] = useState(TEMPLATE);
  const [saved, setSaved] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  const [frame, setFrame] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const [hostile, setHostile] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      apiGet(`/ml-concepts/${encodeURIComponent(code)}/transform`).catch((e) => ({ error: e })),
      apiGet(`/ml-concepts/${encodeURIComponent(code)}/transform/frame`).catch(() => null),
    ]).then(([t, f]) => {
      if (!alive) return;
      if (t?.error) {
        setLoadError(t.error.message);
      } else {
        setSaved(t);
        if (t.present && t.source) setSource(t.source);
      }
      setFrame(f);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [code]);

  const dirty = saved?.present ? source !== saved.source : source !== TEMPLATE;

  async function run() {
    setBusy("run");
    setNotice(null);
    setResult(null);
    try {
      setResult(
        await apiPost(`/ml-concepts/${encodeURIComponent(code)}/transform/dry-run`, {
          source,
          hostile,
        }),
      );
    } catch (e) {
      setNotice({ tone: "danger", text: e.message });
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    setBusy("save");
    setNotice(null);
    try {
      const r = await apiPut(`/ml-concepts/${encodeURIComponent(code)}/transform`, { source });
      setSaved({ present: true, source, sha256: r.sha256, saved_at: r.saved_at, intact: true });
      setNotice({
        tone: r.warnings?.length ? "warn" : "positive",
        text: r.warnings?.length
          ? r.warnings.join(" ")
          : "Saved, and read back from the database to confirm it stored intact.",
      });
    } catch (e) {
      setNotice({ tone: "danger", text: e.message });
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    setBusy("delete");
    setNotice(null);
    try {
      const r = await apiDelete(`/ml-concepts/${encodeURIComponent(code)}/transform`);
      setSaved({ present: false });
      setSource(TEMPLATE);
      setNotice({ tone: "warn", text: r.warnings.join(" ") });
    } catch (e) {
      setNotice({ tone: "danger", text: e.message });
    } finally {
      setBusy(null);
    }
  }

  if (loading || loadError) {
    return (
      <Shell code={code}>
        <Card>
          {loadError ? (
            <Failed what="this model's transform" error={loadError} />
          ) : (
            <Empty>Loading the transform…</Empty>
          )}
        </Card>
      </Shell>
    );
  }

  return (
    <Shell code={code}>
      <Card>
        <CardHeader
          title={`Feature transform — ${code}`}
          hint="Your code runs against generated rows. Nothing on this page has ever been a patient."
        >
          {saved?.present && (
            <Button variant="danger" onClick={remove} disabled={!!busy}>
              {busy === "delete" ? "removing…" : "remove"}
            </Button>
          )}
          <Button onClick={run} disabled={!!busy}>
            {busy === "run" ? "running…" : "dry run"}
          </Button>
          <Button variant="primary" onClick={save} disabled={!!busy || !dirty}>
            {busy === "save" ? "saving…" : dirty ? "save" : "saved"}
          </Button>
        </CardHeader>

        {saved?.present && saved.intact === false && (
          <Callout tone="danger" title="the stored transform is damaged" className="mt-4">
            {saved.problem}
          </Callout>
        )}

        {notice && (
          <Callout
            tone={notice.tone}
            title={
              notice.tone === "danger"
                ? "that did not work"
                : notice.tone === "warn"
                  ? "done, with a consequence"
                  : "saved"
            }
            className="mt-4"
          >
            {notice.text}
          </Callout>
        )}

        <div className="mt-4">
          <CodeEditor
            value={source}
            onChange={setSource}
            placeholder="def transform(df): ..."
            minHeight={340}
          />
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <Note>
            Stored base64-encoded inside the model, because the blob is repaired
            by a quote swap when the container reads it. One apostrophe stored
            raw corrupts the whole model.
          </Note>
          {saved?.sha256 && (
            <span className="text-[11px] text-text-muted">
              sha256 <Mono>{saved.sha256.slice(0, 12)}</Mono>
              {saved.saved_at ? ` · ${saved.saved_at}` : ""}
            </span>
          )}
        </div>
      </Card>

      <FramePanel frame={frame} hostile={hostile} onHostile={setHostile} />

      {result && <ResultPanel result={result} />}
    </Shell>
  );
}

/**
 * The page furniture, so the loading state and the page itself sit in the same
 * three-column shell every other route uses.
 */
function Shell({ code, children }) {
  return (
    <>
      <LeftRail width={258}>
        <PipelineRailStub />
      </LeftRail>
      <Centre>
        <div className="mb-4">
          <Link href={`/model/${encodeURIComponent(code)}`} className="text-[12px] text-text-3">
            back to <Mono>{code}</Mono>
          </Link>
        </div>
        <div className="flex flex-col gap-4">{children}</div>
      </Centre>
      <RightRail width={300} />
    </>
  );
}

/**
 * What the dry-run frame looks like, before anything runs.
 *
 * The warnings are the point. A column the dictionary withheld arrives here
 * all-NaN, and a column the build cannot read arrives empty however full it
 * looks in the warehouse. Code written against either behaves differently in
 * production, which is exactly what a dev loop is supposed to rule out.
 */
function FramePanel({ frame, hostile, onHostile }) {
  if (!frame) {
    return (
      <Card>
        <Empty>The shape of the development frame is not available for this model.</Empty>
      </Card>
    );
  }

  const kinds = Object.entries(frame.kinds ?? {});

  return (
    <Card>
      <CardHeader
        title="the frame your code will see"
        hint="Generated from published aggregates. Columns are independent, so there is no correlation structure and none is implied."
      >
        <label className="flex cursor-pointer items-center gap-2 text-[12px] text-text-3">
          <input
            type="checkbox"
            checked={hostile}
            onChange={(e) => onHostile(e.target.checked)}
            className="accent-accent"
          />
          hostile mode
        </label>
      </CardHeader>

      <div className="mt-4 flex flex-wrap items-baseline gap-x-8 gap-y-2 text-[12px] text-text-3">
        <span>
          rows <Num className="text-text-2">{count(frame.n_rows)}</Num>
        </span>
        <span>
          columns <Num className="text-text-2">{count(frame.n_columns)}</Num>
        </span>
        <span>
          all-NaN rows <Num className="text-text-2">{count(frame.all_nan_rows)}</Num>
        </span>
        {kinds.map(([k, n]) => (
          <span key={k}>
            {k} <Num className="text-text-2">{count(n)}</Num>
          </span>
        ))}
      </div>

      {hostile && (
        <Note className="mt-3">
          Fill rates halved, tails widened, more all-NaN rows. The cheapest way
          to find out that your code assumes a column is always populated.
        </Note>
      )}

      {frame.sandbox_available === false && (
        <Callout tone="warn" title="the sandbox is not available" className="mt-4">
          {frame.sandbox_unavailable_reason}
        </Callout>
      )}

      {frame.warnings?.length > 0 && (
        <Callout tone="warn" title="about this frame" className="mt-4">
          <ul className="mt-1 flex flex-col gap-1">
            {frame.warnings.map((w) => (
              <li key={w} className="text-[12px]">
                {w}
              </li>
            ))}
          </ul>
        </Callout>
      )}
    </Card>
  );
}

const ERROR_TITLES = {
  rejected: "rejected before it ran",
  raised: "your code raised",
  invalid_output: "the returned frame cannot be used",
  timeout: "it ran too long",
  memory: "it ran out of memory",
  crashed: "the sandbox failed",
  protocol: "the sandbox failed",
};

function ResultPanel({ result }) {
  if (!result.ok) {
    return (
      <Card>
        <CardHeader title="the transform did not pass" />
        <Callout
          tone="danger"
          title={ERROR_TITLES[result.error?.kind] ?? "failed"}
          className="mt-4"
        >
          <pre className="whitespace-pre-wrap font-mono text-[12px] leading-relaxed">
            {result.error?.message}
          </pre>
        </Callout>
        {result.logs && <Logs text={result.logs} />}
      </Card>
    );
  }

  const r = result.report;
  return (
    <Card>
      <CardHeader
        title="what your transform did"
        hint={`${result.duration_ms} ms, on generated rows`}
      >
        <Pill tone={r.changed ? "positive" : "warn"}>
          <Dot tone={r.changed ? "positive" : "warn"} /> {r.changed ? "changed" : "unchanged"}
        </Pill>
      </CardHeader>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="rows in" value={r.rows_in} />
        <Stat label="rows out" value={r.rows_out} tone={r.rows_dropped ? "warn" : undefined} />
        <Stat label="columns in" value={r.columns_in} />
        <Stat label="columns out" value={r.columns_out} />
      </div>

      {(r.columns_added.length > 0 || r.columns_removed.length > 0) && (
        <div className="mt-4 flex flex-wrap gap-2">
          {r.columns_added.map((c) => (
            <Pill key={c} tone="positive">
              added <Mono>{c}</Mono>
            </Pill>
          ))}
          {r.columns_removed.map((c) => (
            <Pill key={c} tone="danger">
              removed <Mono>{c}</Mono>
            </Pill>
          ))}
        </div>
      )}

      {r.warnings?.length > 0 && (
        <Callout tone="warn" title="worth reading" className="mt-4">
          <ul className="mt-1 flex flex-col gap-1">
            {r.warnings.map((w) => (
              <li key={w} className="text-[12px]">
                {w}
              </li>
            ))}
          </ul>
        </Callout>
      )}

      {result.logs && <Logs text={result.logs} />}

      <Preview title="output" preview={result.preview} />
      <Preview title="input" preview={result.input_preview} />

      <Note className="mt-4">
        These rows are generated. A real build reports counts and never returns a
        row of the frame.
      </Note>
    </Card>
  );
}

function Stat({ label, value, tone }) {
  return (
    <Row>
      <div className="text-[10px] uppercase tracking-[0.08em] text-text-muted">{label}</div>
      <Num className={`text-[17px] ${tone === "warn" ? "text-warn" : "text-text"}`}>
        {count(value)}
      </Num>
    </Row>
  );
}

function Logs({ text }) {
  return (
    <div className="mt-4">
      <Heading level={3} className="text-[11px] uppercase tracking-[0.08em] text-text-muted">
        printed output
      </Heading>
      <pre className="mt-2 max-h-[220px] overflow-auto rounded-row border border-border-soft bg-panel-sunk p-3 font-mono text-[11.5px] leading-relaxed text-text-3">
        {text}
      </pre>
    </div>
  );
}

function Preview({ title, preview }) {
  const rows = preview?.rows ?? [];
  if (rows.length === 0) return null;

  return (
    <div className="mt-4">
      <Heading level={3} className="text-[11px] uppercase tracking-[0.08em] text-text-muted">
        {title} · first {rows.length} rows
      </Heading>
      <div className="mt-2 max-h-[300px] overflow-auto">
        <Table>
          <thead>
            <tr>
              <Th>index</Th>
              {preview.columns.map((c, i) => (
                <Th key={c} align="right">
                  <span className="flex flex-col items-end">
                    <Mono>{c}</Mono>
                    <span className="text-[9px] font-normal text-text-muted">
                      {preview.dtypes?.[i]}
                    </span>
                  </span>
                </Th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={preview.index?.[i] ?? i}>
                <Td>
                  <Mono className="text-text-muted">{preview.index?.[i]}</Mono>
                </Td>
                {row.map((v, j) => (
                  <Td key={j} align="right">
                    {v === null ? (
                      // Not a blank. A blank reads as "nothing here"; this cell
                      // is NaN and code has to handle it.
                      <span className="text-[11px] text-text-muted">NaN</span>
                    ) : (
                      <Num className="text-text-2">
                        {typeof v === "number" ? round(v) : String(v)}
                      </Num>
                    )}
                  </Td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </div>
  );
}

function round(v) {
  if (Number.isInteger(v)) return String(v);
  return String(Math.round(v * 1000) / 1000);
}
