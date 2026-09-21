/**
 * Status is a dot *and* a word, never a colour on its own.
 *
 * Roughly one reader in twelve cannot separate the warn amber from the danger
 * red, and "failed" versus "done" is the difference between a model that
 * exists and one that does not. The word is the signal; the dot is emphasis.
 */

const DOT = {
  positive: "bg-positive",
  warn: "bg-warn",
  danger: "bg-danger",
  accent: "bg-accent",
  neutral: "bg-text-muted",
  idle: "bg-border-strong",
};

const TEXT = {
  positive: "text-positive",
  warn: "text-warn",
  danger: "text-danger",
  accent: "text-accent",
  neutral: "text-text-3",
  idle: "text-text-muted",
};

export function Dot({ tone = "neutral", className = "" }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block size-[7px] shrink-0 rounded-full ${DOT[tone] ?? DOT.neutral} ${className}`}
    />
  );
}

export function Status({ tone = "neutral", children, className = "" }) {
  return (
    <span className={`inline-flex items-center gap-2 text-[12px] ${TEXT[tone] ?? TEXT.neutral} ${className}`}>
      <Dot tone={tone} />
      {children}
    </span>
  );
}

/** A tag: a registry key, a concept type, a role marker. Never a status. */
export function Pill({ children, tone = "neutral", className = "" }) {
  const tones = {
    neutral: "border-border bg-panel-sunk text-text-3",
    accent: "border-accent/40 bg-accent/10 text-accent",
    positive: "border-positive-edge bg-positive-edge/40 text-positive",
    warn: "border-warn-edge bg-warn-edge/50 text-warn",
    danger: "border-danger-edge bg-danger-edge/50 text-danger",
  };
  return (
    <span
      className={`inline-flex items-center rounded-btn border px-2 py-1 font-mono text-[11px] ${tones[tone] ?? tones.neutral} ${className}`}
    >
      {children}
    </span>
  );
}

/** Job statuses, mapped once so every list agrees on what red means. */
export const JOB_TONE = {
  SUBMITTED: "neutral",
  PENDING: "warn",
  PROCESSING: "accent",
  COMPLETED: "positive",
  ERROR: "danger",
};

export function jobTone(status) {
  return JOB_TONE[status] ?? "neutral";
}
