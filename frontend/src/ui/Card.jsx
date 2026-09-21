import { Heading, Note } from "./Text.jsx";

/**
 * The one card shape: 12px radius, 1px border, 18px of padding.
 *
 * `sunk` is for a panel nested inside another card — a table body, a log, a
 * metric tile — which reads as recessed rather than as a second card.
 */
export function Card({ children, className = "", sunk = false, as: Tag = "section" }) {
  return (
    <Tag
      className={`rounded-card border p-[18px] ${
        sunk
          ? "border-border-soft bg-panel-sunk"
          : "border-border bg-panel"
      } ${className}`}
    >
      {children}
    </Tag>
  );
}

/**
 * Title on the left, controls on the right. Baseline-aligned so a button and a
 * heading of different sizes still sit on one line.
 */
export function CardHeader({ title, hint, children, className = "" }) {
  return (
    <div className={`flex items-start justify-between gap-4 ${className}`}>
      <div className="min-w-0">
        <Heading level={2} className="text-[15px] leading-tight">
          {title}
        </Heading>
        {hint && <Note className="mt-1">{hint}</Note>}
      </div>
      {children && <div className="flex shrink-0 items-center gap-2">{children}</div>}
    </div>
  );
}

/** A row inside a list-style card. 9px radius, per the token rules. */
export function Row({ children, className = "", as: Tag = "div", ...rest }) {
  return (
    <Tag
      className={`rounded-row border border-border-soft bg-panel-sunk px-4 py-3 ${className}`}
      {...rest}
    >
      {children}
    </Tag>
  );
}
