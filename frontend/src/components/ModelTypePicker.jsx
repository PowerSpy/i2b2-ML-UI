import { useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";
import { defaultValues } from "../lib/hyperparams.js";

/**
 * Algorithm choice plus that algorithm's hyperparameters.
 *
 * The list comes from the container's MODEL_REGISTRY rather than a constant
 * here, because an option we offer that the container does not have would not
 * fail — the builder falls back to logistic regression and reports success.
 */
export default function ModelTypePicker({ value, onChange, values, onValuesChange }) {
  const [types, setTypes] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    apiGet("/ml-model-types")
      .then((d) => {
        if (!alive) return;
        setTypes(d);
        setError(null);
        // Seed the parent with the initial selection's fields and defaults —
        // without this the form would submit the default algorithm with no
        // hyperparameter values until the user touched the dropdown.
        const initial = d.find((t) => t.key === value) ?? d[0];
        if (initial) {
          onChange(initial.key, initial.fields);
          onValuesChange(defaultValues(initial.fields));
        }
      })
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
    // Runs once: re-seeding on every parent state change would wipe entries
    // as they are typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = types.find((t) => t.key === value) ?? null;
  const fields = selected?.fields ?? [];

  function pick(key) {
    const next = types.find((t) => t.key === key);
    onChange(key, next?.fields ?? []);
    // Each model has its own knobs, so carrying the previous model's entries
    // over would leave stale values in fields that happen to share an id.
    onValuesChange(defaultValues(next?.fields ?? []));
  }

  if (error) {
    return (
      <p className="rounded border border-amber-900 bg-amber-950/40 p-3 text-xs text-amber-300">
        Could not read the model registry: {error}
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div>
        <label className="mb-1 block text-xs text-neutral-500">algorithm</label>
        <select
          value={value}
          onChange={(e) => pick(e.target.value)}
          disabled={types.length === 0}
          className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-sm text-neutral-200 disabled:opacity-40"
        >
          {types.length === 0 && <option>loading…</option>}
          {types.map((t) => (
            <option key={t.key} value={t.key}>
              {t.name}
            </option>
          ))}
        </select>
        {selected?.note && (
          <p className="mt-1 text-xs text-neutral-500">{selected.note}</p>
        )}
      </div>

      {fields.length > 0 && (
        <div className="flex flex-wrap gap-3">
          {fields.map((f) => (
            <div key={f.id}>
              <label className="mb-1 block text-xs text-neutral-500">
                {f.label}
              </label>
              <input
                type="number"
                step="any"
                min={f.min}
                max={f.max}
                value={values[f.id] ?? ""}
                placeholder={f.allow_blank ? "unlimited" : ""}
                onChange={(e) =>
                  onValuesChange({ ...values, [f.id]: e.target.value })
                }
                className="w-40 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm"
              />
              <p className="mt-0.5 text-[10px] text-neutral-600">
                {f.min}–{f.max}
                {f.allow_blank ? ", or blank" : ""}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
