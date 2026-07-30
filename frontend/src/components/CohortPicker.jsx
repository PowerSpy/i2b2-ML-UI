/**
 * Cohorts are resolved by exact name, and a miss trains on an empty set without
 * erroring — so this is never a text input.
 */
export default function CohortPicker({ cohorts, value, onChange, placeholder = "— pick a cohort —" }) {
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-sm text-neutral-200"
    >
      <option value="">{placeholder}</option>
      {cohorts.map((c) => (
        <option key={c.id} value={c.name}>
          {c.name} ({c.size.toLocaleString()})
        </option>
      ))}
    </select>
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

  return (
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
          {c.name}{" "}
          <span className="text-neutral-500">{c.size.toLocaleString()}</span>
        </button>
      ))}
    </div>
  );
}
