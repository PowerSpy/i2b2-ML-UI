/**
 * The typographic rules, as components.
 *
 * Every numeral, path, concept code and identifier in this app renders in IBM
 * Plex Mono. Going through these rather than typing `font-mono` by hand is
 * what keeps that true — a number in the body font is immediately obvious as a
 * component that was not used.
 */

/** Any figure. Tabular so columns of them line up on the decimal point. */
export function Num({ children, className = "" }) {
  return (
    <span className={`font-mono tabular-nums ${className}`}>{children}</span>
  );
}

/** A concept path, code, cohort name, class name or job id. */
export function Mono({ children, className = "", title }) {
  return (
    <span className={`font-mono ${className}`} title={title}>
      {children}
    </span>
  );
}

/**
 * 10–11px uppercase with wide tracking, in the dimmest text colour. Used for
 * every section label and every table header in the app.
 */
export function SectionLabel({ children, className = "" }) {
  return (
    <p
      className={`text-[10px] font-medium uppercase tracking-[0.085em] text-text-muted ${className}`}
    >
      {children}
    </p>
  );
}

/** A page or card heading. Space Grotesk 600, per the type rules. */
export function Heading({ level = 2, children, className = "" }) {
  const Tag = `h${level}`;
  return (
    <Tag className={`font-head font-semibold text-text ${className}`}>
      {children}
    </Tag>
  );
}

/** Explanatory prose under a heading or beside a control. */
export function Note({ children, className = "" }) {
  return (
    <p className={`text-[12px] leading-relaxed text-text-3 ${className}`}>
      {children}
    </p>
  );
}
