/**
 * The size a cohort will actually train on, and why it might not be what the
 * recorded number says.
 *
 * `size` is what the set recorded when it was built; `live` counts the members
 * that still have facts. The two diverge after a reload, and the pickers are
 * where that matters — the cohort list in step 2 flagged it, while steps 3 and
 * 5 showed the stale number with no marker.
 */
function label(c) {
  const live = c.live ?? c.size;
  return live === c.size
    ? live.toLocaleString()
    : `${live.toLocaleString()} of ${c.size.toLocaleString()}`;
}

function suffix(c) {
  const parts = [];
  if (c.stale) parts.push("stale");
  if (c.duplicate) parts.push("duplicate name");
  return parts.length ? ` — ${parts.join(", ")}` : "";
}

/**
 * Cohorts are resolved by exact name, and a miss trains on an empty set without
 * erroring — so this is never a text input.
 */
export default function CohortPicker({ cohorts, value, onChange, placeholder = "— pick a cohort —" }) {
  const chosen = cohorts.find((c) => c.name === value) ?? null;

  return (
    <div className="space-y-1">
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-sm text-neutral-200"
      >
        <option value="">{placeholder}</option>
        {cohorts.map((c) => (
          <option key={c.id} value={c.name}>
            {c.name} ({label(c)}){suffix(c)}
          </option>
        ))}
      </select>
      <Notes cohorts={chosen ? [chosen] : []} />
    </div>
  );
}

export function CohortMultiPicker({ cohorts, values, onChange }) {
  function toggle(name) {
    onChange(
      values.includes(name)
        ? values.filter((v) => v !== name)
        : [...values, name],
    );
  }

  if (!cohorts.length) {
    return <p className="text-xs text-neutral-500">no cohorts yet</p>;
  }

  const chosen = cohorts.filter((c) => values.includes(c.name));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {cohorts.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => toggle(c.name)}
            className={`rounded border px-2 py-1 text-xs ${
              values.includes(c.name)
                ? "border-sky-600 bg-sky-950/60 text-sky-200"
                : "border-neutral-700 text-neutral-400 hover:border-neutral-500"
            }`}
          >
            {c.name} <span className="text-neutral-500">{label(c)}</span>
            {(c.stale || c.duplicate) && (
              <span className="ml-1 text-amber-400">!</span>
            )}
          </button>
        ))}
      </div>
      <Notes cohorts={chosen} />
    </div>
  );
}

/** Explains the markers, but only for cohorts actually selected. */
function Notes({ cohorts }) {
  const duplicate = cohorts.filter((c) => c.duplicate).map((c) => c.name);
  const stale = cohorts.filter((c) => c.stale).map((c) => c.name);
  if (!duplicate.length && !stale.length) return null;

  return (
    <div className="space-y-1 text-xs">
      {duplicate.length > 0 && (
        <p className="text-red-400">
          {duplicate.join(", ")}: more than one patient set has this name.
          Training resolves a name to <em>every</em> matching set and unions
          them, so the model would train on a population you did not choose.
          Delete the duplicates in step 2 first.
        </p>
      )}
      {stale.length > 0 && (
        <p className="text-amber-300/80">
          {stale.join(", ")}: some members no longer have facts, usually because
          the data was reloaded after the cohort was built. Training will use
          only the live ones.
        </p>
      )}
    </div>
  );
}
