import { useRef, useState } from "react";

import { apiUpload } from "../lib/api.js";

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
    <section className="space-y-4">
      {children}

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-lg border-2 border-dashed p-10 text-center transition-colors ${
          dragging
            ? "border-sky-400 bg-sky-950/30"
            : "border-neutral-700 hover:border-neutral-500"
        }`}
      >
        <p className="text-sm text-neutral-300">{busy ? "Loading…" : prompt}</p>
        {name && !busy && (
          <p className="mt-2 text-xs text-neutral-500">{name}</p>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => upload(e.target.files?.[0])}
        />
      </div>

      {error && (
        <p className="rounded border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-3">
          <p className="text-sm">
            status:{" "}
            <span
              className={
                result.status === "ok" ? "text-emerald-400" : "text-red-400"
              }
            >
              {result.status}
            </span>
          </p>
          <Output label="stdout" text={result.stdout} />
          <Output label="stderr" text={result.stderr} />
        </div>
      )}
    </section>
  );
}

function Output({ label, text }) {
  if (!text) return null;
  return (
    <div>
      <p className="mb-1 text-xs uppercase tracking-wide text-neutral-500">
        {label}
      </p>
      <pre className="max-h-64 overflow-auto rounded bg-neutral-900 p-3 text-xs whitespace-pre-wrap text-neutral-300">
        {text}
      </pre>
    </div>
  );
}
