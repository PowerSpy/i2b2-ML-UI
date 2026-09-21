import { Dot } from "./Status.jsx";
import { SectionLabel } from "./Text.jsx";

const TONES = {
  warn: "border-warn-edge bg-warn-edge/35",
  danger: "border-danger-edge bg-danger-edge/35",
  positive: "border-positive-edge bg-positive-edge/30",
  neutral: "border-border-soft bg-panel-sunk",
};

const TITLE = {
  warn: "text-warn",
  danger: "text-danger",
  positive: "text-positive",
  neutral: "text-text-2",
};

/**
 * A tinted note. The title carries a status dot because the tint alone is not
 * allowed to be the signal.
 */
export default function Callout({ tone = "warn", title, children, className = "" }) {
  return (
    <div className={`rounded-card border p-4 ${TONES[tone] ?? TONES.neutral} ${className}`}>
      {title && (
        <p className={`mb-1.5 flex items-center gap-2 text-[12px] font-semibold ${TITLE[tone] ?? TITLE.neutral}`}>
          <Dot tone={tone} />
          {title}
        </p>
      )}
      <div className="text-[12px] leading-relaxed text-text-3">{children}</div>
    </div>
  );
}

/**
 * Nothing here yet, but there could be — no cohorts created, no models
 * defined. The reason is always a step the user has not taken.
 */
export function Empty({ children, className = "" }) {
  return (
    <div
      className={`rounded-row border border-dashed border-border px-4 py-6 text-center text-[12px] leading-relaxed text-text-muted ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * A panel the design calls for that the API cannot fill.
 *
 * Deliberately loud, and never rendered as a zero or a dash on its own: in a
 * system where a step can report success and load nothing, "0 rows rejected"
 * and "nobody counts rejected rows" have to look different. Every one of these
 * names the endpoint that would have to exist.
 */
export function NotReported({ label, children, className = "" }) {
  return (
    <div
      className={`rounded-row border border-dashed border-border-strong bg-panel-sunk/60 p-3 ${className}`}
    >
      <SectionLabel className="mb-1.5 flex items-center gap-1.5">
        <span aria-hidden="true" className="inline-block size-[7px] rounded-full border border-border-strong" />
        not reported by the API
      </SectionLabel>
      {label && <p className="mb-1 text-[12px] text-text-3">{label}</p>}
      {children && (
        <p className="text-[11px] leading-relaxed text-text-muted">{children}</p>
      )}
    </div>
  );
}

/** A failed request, shown where its data would have been. */
export function Failed({ what, error, className = "" }) {
  return (
    <div
      className={`rounded-row border border-danger-edge bg-danger-edge/35 p-3 text-[12px] leading-relaxed text-danger ${className}`}
    >
      <span className="flex items-center gap-2">
        <Dot tone="danger" />
        could not load {what}
      </span>
      {error && (
        <p className="mt-1 font-mono text-[11px] break-words text-text-3">{error}</p>
      )}
    </div>
  );
}
