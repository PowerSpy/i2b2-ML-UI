import { Num, SectionLabel } from "./Text.jsx";

const FILL = {
  positive: "bg-positive",
  warn: "bg-warn",
  danger: "bg-danger",
  accent: "bg-accent",
  neutral: "bg-text-muted",
};

/**
 * The inline bar beside a score.
 *
 * Purely an aid to scanning a column — the number next to it is the value, and
 * every caller renders one, so the bar is aria-hidden rather than a progressbar
 * that a screen reader would read out twice.
 */
export default function Meter({ value, max = 1, tone = "neutral", className = "" }) {
  const pct =
    typeof value === "number" && Number.isFinite(value)
      ? Math.max(0, Math.min(1, value / max)) * 100
      : 0;

  return (
    <span
      aria-hidden="true"
      className={`inline-block h-[5px] w-full overflow-hidden rounded-full bg-border-soft ${className}`}
    >
      <span
        className={`block h-full rounded-full ${FILL[tone] ?? FILL.neutral}`}
        style={{ width: `${pct}%` }}
      />
    </span>
  );
}

/**
 * One headline figure: a large mono number over a small uppercase label, with
 * an optional line of context beneath.
 */
export function Stat({ value, label, sub, tone, size = "md", className = "" }) {
  const sizes = {
    sm: "text-[19px]",
    md: "text-[26px]",
    lg: "text-[32px]",
  };
  const tones = {
    positive: "text-positive",
    warn: "text-warn",
    danger: "text-danger",
    accent: "text-accent",
  };

  return (
    <div className={className}>
      <Num className={`block leading-none ${sizes[size] ?? sizes.md} ${tones[tone] ?? "text-text"}`}>
        {value}
      </Num>
      <SectionLabel className="mt-2">{label}</SectionLabel>
      {sub && <p className="mt-1 text-[11px] leading-snug text-text-muted">{sub}</p>}
    </div>
  );
}
