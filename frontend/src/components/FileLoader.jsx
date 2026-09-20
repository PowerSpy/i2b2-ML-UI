import { useRef, useState } from "react";

import { apiUpload } from "../lib/api.js";
import { count, plural } from "../lib/format.js";
import Callout from "../ui/Callout.jsx";
import { Num, SectionLabel } from "../ui/Text.jsx";

/**
 * Drop target for one CSV upload. `endpoint` is the loader route, `params` any
 * query string the route takes, `children` extra controls above the drop zone.
 */
export default function FileLoader({ endpoint, prompt, params, children, onLoaded }) {
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [name, setName] = useState(null);
  const inputRef = useRef(null);

  async function upload(file) {
    if (!file) return;
    setName(file.name);
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const res = await apiUpload(endpoint, file, params);
      setResult(res);
      if (res.status === "ok") onLoaded?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    upload(e.dataTransfer.files?.[0]);
  }

  return (
    <section className="space-y-3">
      {children}

      <button
        type="button"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`w-full cursor-pointer rounded-card border border-dashed p-8 text-center transition-colors ${
          dragging
            ? "border-accent bg-accent/5"
            : "border-border hover:border-border-strong"
        }`}
      >
        <p className="text-[13px] text-text-2">{busy ? "Loading…" : prompt}</p>
        {name && !busy && (
          <p className="mt-1.5 font-mono text-[11px] text-text-muted">{name}</p>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => upload(e.target.files?.[0])}
        />
      </button>

      {error && (
        <Callout tone="danger" title="upload failed">
          {error}
        </Callout>
      )}

      {result && (
        <div className="space-y-3">
          {/*
            Rows gained, not exit status. The loader exits 0 whether it ingested
            the file or skipped it, so "ok" on its own never meant anything had
            been loaded.
          */}
          <p className="text-[13px]">
            {result.rows_loaded != null ? (
              <span className={result.rows_loaded > 0 ? "text-positive" : "text-danger"}>
                <Num>{count(result.rows_loaded)}</Num>{" "}
                {plural(result.rows_loaded, "row")} loaded
              </span>
            ) : (
              <span className="text-text-3">
                status:{" "}
                <span className={result.status === "ok" ? "text-positive" : "text-danger"}>
                  {result.status}
                </span>
              </span>
            )}
          </p>

          {result.note && (
            <Callout tone="warn" title="nothing was loaded">
              {result.note}
            </Callout>
          )}

          <Output label="stdout" text={result.stdout} />
          <Output label="stderr" text={result.stderr} />
        </div>
      )}
    </section>
  );
}

/**
 * The CLI's own log. Usually the only place the reason for a failure exists,
 * so it is shown in full rather than summarised.
 */
function Output({ label, text }) {
  if (!text) return null;
  return (
    <div>
      <SectionLabel className="mb-1.5">{label}</SectionLabel>
      <pre className="max-h-64 overflow-auto rounded-row border border-border-soft bg-panel-sunk p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-text-3">
        {text}
      </pre>
    </div>
  );
}
