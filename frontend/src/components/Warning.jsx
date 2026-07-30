/** Amber callout. Most of this workflow's failure modes are silent, not loud. */
export default function Warning({ children }) {
  if (!children) return null;
  return (
    <p className="rounded border border-amber-900/70 bg-amber-950/30 p-3 text-xs text-amber-200">
      {children}
    </p>
  );
}

export function Warnings({ items }) {
  if (!items?.length) return null;
  return (
    <div className="space-y-2">
      {items.map((w) => (
        <Warning key={w}>{w}</Warning>
      ))}
    </div>
  );
}
