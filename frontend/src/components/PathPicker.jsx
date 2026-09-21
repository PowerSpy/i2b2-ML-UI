import { Mono } from "../ui/Text.jsx";

/** Toggle set over concept path prefixes. Each selection becomes a SQL LIKE. */
export default function PathPicker({ label, tree, values, onChange, hint, id }) {
  function toggle(p) {
    onChange(values.includes(p) ? values.filter((v) => v !== p) : [...values, p]);
  }

  return (
    <div>
      {label && (
        <p className="mb-1.5 text-[12px] text-text-3" id={id}>
          {label}
        </p>
      )}
      {tree.length === 0 ? (
        <p className="text-[12px] text-text-muted">no concept paths loaded</p>
      ) : (
        <div className="flex flex-wrap gap-2" role="group" aria-labelledby={id}>
          {tree.map((p) => {
            const on = values.includes(p);
            return (
              <button
                key={p}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(p)}
                className={`min-h-[44px] rounded-btn border px-3 text-[12px] transition-colors ${
                  on
                    ? "border-accent bg-accent/10 text-text"
                    : "border-border-strong text-text-3 hover:border-text-muted hover:text-text-2"
                }`}
              >
                <Mono>{p}</Mono>
              </button>
            );
          })}
        </div>
      )}
      {hint && <p className="mt-2 text-[12px] leading-relaxed text-text-muted">{hint}</p>}
    </div>
  );
}
