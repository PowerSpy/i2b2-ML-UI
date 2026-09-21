import { Mono } from "./Text.jsx";

/** A data table. Header cells use the same 10px uppercase as section labels. */
export function Table({ children, className = "" }) {
  return (
    <table className={`w-full border-collapse text-left text-[13px] ${className}`}>
      {children}
    </table>
  );
}

// Columns are sized by their content, so without a gutter a right-aligned
// number sits flush against the next column's left-aligned label.
const GUTTER = "pr-5 last:pr-0";

export function Th({ children, align = "left", className = "" }) {
  return (
    <th
      scope="col"
      className={`border-b border-border-soft pb-2.5 text-[10px] font-medium uppercase tracking-[0.085em] text-text-muted ${GUTTER} ${
        align === "right" ? "text-right" : "text-left"
      } ${className}`}
    >
      {children}
    </th>
  );
}

export function Td({ children, align = "left", className = "" }) {
  return (
    <td
      className={`border-b border-border-soft py-3 align-middle text-text-2 ${GUTTER} ${
        align === "right" ? "text-right" : "text-left"
      } ${className}`}
    >
      {children}
    </td>
  );
}

/**
 * The right-rail key/value list: run configuration, provenance.
 *
 * The value is always mono, because every value in these lists is a number, a
 * path, a cohort name or a class name.
 */
export function KeyValueList({ children, className = "" }) {
  return <dl className={`space-y-0 ${className}`}>{children}</dl>;
}

export function KeyValue({ label, children, value, title }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border-soft py-2.5 last:border-b-0">
      <dt className="shrink-0 text-[12px] text-text-3">{label}</dt>
      <dd className="min-w-0 text-right text-[12px] text-text-2">
        {children ?? (
          // Concept paths have no spaces, so break-all is the only thing that
          // wraps them. The title carries the unbroken value for copying.
          <Mono className="break-all" title={title ?? value}>
            {value}
          </Mono>
        )}
      </dd>
    </div>
  );
}

/** A column that holds a visual only, so the header is for screen readers. */
export function ThHidden({ children, className = "" }) {
  return (
    <Th className={className}>
      <span className="sr-only">{children}</span>
    </Th>
  );
}
