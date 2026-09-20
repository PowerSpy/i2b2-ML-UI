/** Shared formatting. Every one of these feeds a mono span. */

/** Thousands-separated, with an em dash for "we do not have this number". */
export function count(n) {
  return typeof n === "number" && Number.isFinite(n) ? n.toLocaleString() : "—";
}

/** Metrics are compared column-against-column, so the width is fixed. */
export function score(n, digits = 2) {
  return typeof n === "number" && Number.isFinite(n) ? n.toFixed(digits) : "—";
}

export function seconds(n) {
  return typeof n === "number" && Number.isFinite(n) ? `${n.toFixed(1)}s` : "—";
}

/**
 * "HeartDisease" -> "Heart Disease". Purely a display nicety over the concept
 * path, which is always shown verbatim underneath it.
 */
export function titleFromSegment(segment) {
  const spaced = segment
    .replace(/[_-]+/g, " ")
    .replace(/([a-z\d])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .trim();
  return spaced || segment;
}

/**
 * The job table stores timestamps as strings in the database's own format.
 * Anything Date cannot parse is shown as-is rather than as "Invalid Date".
 */
export function ago(value) {
  if (!value) return null;
  const then = new Date(value.includes("T") ? value : value.replace(" ", "T"));
  if (Number.isNaN(then.getTime())) return value;

  const secs = Math.round((Date.now() - then.getTime()) / 1000);
  if (secs < 0) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** First non-empty line, for showing a stack trace's headline in a list row. */
export function firstLine(text, max = 90) {
  if (!text) return null;
  const line = text.split("\n").find((l) => l.trim()) ?? "";
  const trimmed = line.trim();
  return trimmed.length > max ? `${trimmed.slice(0, max - 1)}…` : trimmed;
}

export function plural(n, one, many = `${one}s`) {
  return n === 1 ? one : many;
}
