import { useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";
import { defaultValues, valuesFromOverrides } from "../lib/hyperparams.js";
import Callout from "../ui/Callout.jsx";
import { Num } from "../ui/Text.jsx";

const FIELD =
  "min-h-[44px] rounded-btn border border-border-strong bg-panel-sunk px-3 text-[13px] text-text placeholder:text-text-muted";

/**
 * Algorithm choice plus that algorithm's hyperparameters.
 *
 * The list comes from the container's MODEL_REGISTRY rather than a constant
 * here, because an option we offer that the container does not have would not
 * fail — the builder falls back to logistic regression and reports success.
 */
export default function ModelTypePicker({
  value,
  onChange,
  values,
  onValuesChange,
  // A stored grid to seed from, when editing an existing model. Without it
  // the form reseeds to defaults and a one-field edit resets the rest.
  initialOverrides = null,
}) {
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
          onValuesChange(
            initialOverrides
              ? valuesFromOverrides(initial.fields, initialOverrides)
              : defaultValues(initial.fields),
          );
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
      <Callout tone="warn" title="model registry unreadable">
        {error}. Until this clears, the algorithm list cannot be trusted to match
        what the container can build.
      </Callout>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1.5 block text-[12px] text-text-3" htmlFor="algorithm">
          algorithm
        </label>
        <select
          id="algorithm"
          value={value}
          onChange={(e) => pick(e.target.value)}
          disabled={types.length === 0}
          className={`${FIELD} w-full font-mono disabled:opacity-40`}
        >
          {types.length === 0 && <option>loading…</option>}
          {types.map((t) => (
            <option key={t.key} value={t.key}>
              {t.name}
            </option>
          ))}
        </select>
        {selected?.note && (
          <p className="mt-2 text-[12px] leading-relaxed text-text-muted">
            {selected.note}
          </p>
        )}
      </div>

      {fields.length > 0 && (
        <div className="flex flex-wrap gap-3">
          {fields.map((f) => (
            <div key={f.id}>
              <label className="mb-1.5 block text-[12px] text-text-3" htmlFor={`hp-${f.id}`}>
                {f.label}
              </label>
              <input
                id={`hp-${f.id}`}
                type="number"
                step="any"
                min={f.min}
                max={f.max}
                value={values[f.id] ?? ""}
                placeholder={f.allow_blank ? "unlimited" : ""}
                onChange={(e) => onValuesChange({ ...values, [f.id]: e.target.value })}
                className={`${FIELD} w-40 font-mono tabular-nums`}
              />
              <p className="mt-1 text-[10px] text-text-muted">
                <Num>
                  {f.min}–{f.max}
                </Num>
                {f.allow_blank ? ", or blank to search the default range" : ""}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
