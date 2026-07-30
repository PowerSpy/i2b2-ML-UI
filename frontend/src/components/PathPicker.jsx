/** Toggle set over concept path prefixes. Each selection becomes a SQL LIKE. */
export default function PathPicker({ label, tree, values, onChange, hint }) {
  function toggle(p) {
    onChange(values.includes(p) ? values.filter((v) => v !== p) : [...values, p]);
  }

  return (
    <div>
      {label && (
        <label className="mb-1 block text-xs text-neutral-500">{label}</label>
      )}
      {tree.length === 0 ? (
        <p className="text-xs text-neutral-500">no concept paths loaded</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {tree.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => toggle(p)}
              className={`rounded border px-2 py-1 text-xs ${
                values.includes(p)
                  ? "border-sky-600 bg-sky-950/60 text-sky-200"
                  : "border-neutral-700 text-neutral-400 hover:border-neutral-500"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      )}
      {hint && <p className="mt-1 text-xs text-neutral-500">{hint}</p>}
    </div>
  );
}
