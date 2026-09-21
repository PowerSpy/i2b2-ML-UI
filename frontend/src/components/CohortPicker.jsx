import { count } from "../lib/format.js";
import Callout from "../ui/Callout.jsx";
import { Mono, Num } from "../ui/Text.jsx";

/**
 * The size a cohort will actually train on, and why it might not be what the
 * recorded number says.
 *
 * `size` is what the set recorded when it was built; `live` counts the members
 * that still have facts. The two diverge after a reload, and the pickers are
 * where that matters — the cohort table flagged it, while the define and apply
 * steps showed the stale number with no marker.
 */
function label(c) {
  const live = c.live ?? c.size;
  return live === c.size ? count(live) : `${count(live)} of ${count(c.size)}`;
}

function suffix(c) {
  const parts = [];
  if (c.stale) parts.push("stale");
  if (c.duplicate) parts.push("duplicate name");
  return parts.length ? ` — ${parts.join(", ")}` : "";
}

const SELECT =
  "w-full min-h-[44px] rounded-btn border border-border-strong bg-panel-sunk px-3 font-mono text-[13px] text-text-2";

/**
 * Cohorts are resolved by exact name, and a miss trains on an empty set without
 * erroring — so this is never a text input.
 */
export default function CohortPicker({
  id,
  cohorts,
  value,
  onChange,
  placeholder = "— pick a cohort —",
}) {
  const chosen = cohorts.find((c) => c.name === value) ?? null;

  return (
    <div className="space-y-2">
      {/* The caller renders the <label>, so its htmlFor needs this id to
          land on the real control rather than on nothing. */}
      <select
        id={id}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className={SELECT}
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

export function CohortMultiPicker({ labelledBy, cohorts, values, onChange }) {
  function toggle(name) {
    onChange(
      values.includes(name) ? values.filter((v) => v !== name) : [...values, name],
    );
  }

  if (!cohorts.length) {
    return <p className="text-[12px] text-text-muted">no cohorts yet</p>;
  }

  const chosen = cohorts.filter((c) => values.includes(c.name));

  return (
    <div className="space-y-2">
      {/* A set of toggles, not a single control, so it is a labelled group
          rather than something a <label for> could point at. */}
      <div className="flex flex-wrap gap-2" role="group" aria-labelledby={labelledBy}>
        {cohorts.map((c) => {
          const on = values.includes(c.name);
          return (
            <button
              key={c.id}
              type="button"
              aria-pressed={on}
              onClick={() => toggle(c.name)}
              className={`min-h-[44px] rounded-btn border px-3 text-left text-[12px] transition-colors ${
                on
                  ? "border-accent bg-accent/10 text-text"
                  : "border-border-strong text-text-3 hover:border-text-muted hover:text-text-2"
              }`}
            >
              <Mono>{c.name}</Mono>{" "}
              <Num className="text-text-muted">{label(c)}</Num>
              {(c.stale || c.duplicate) && (
                <span className="ml-1.5 text-warn">!</span>
              )}
            </button>
          );
        })}
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
    <div className="space-y-2">
      {duplicate.length > 0 && (
        <Callout tone="danger" title="ambiguous cohort name">
          <Mono className="text-text-2">{duplicate.join(", ")}</Mono>: more than
          one patient set has this name. Training resolves a name to{" "}
          <em>every</em> matching set and unions them, so the model would train
          on a population you did not choose. Delete the duplicates first.
        </Callout>
      )}
      {stale.length > 0 && (
        <Callout tone="warn" title="stale members">
          <Mono className="text-text-2">{stale.join(", ")}</Mono>: some members
          no longer have facts, usually because the data was reloaded after the
          cohort was built. Training will use only the live ones.
        </Callout>
      )}
    </div>
  );
}
