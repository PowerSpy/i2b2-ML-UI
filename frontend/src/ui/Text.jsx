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

/**
 * A value that exists and is deliberately not shown.
 *
 * This has to look different from `format.js`'s em dash, which means "we do
 * not have this number". The two are easy to conflate and mean opposite
 * things: a dash says the app failed to fetch something, this says the app
 * fetched it and chose not to publish it. Someone deciding whether a cohort is
 * usable needs to know which they are looking at.
 *
 * Rendered as a bordered chip rather than styled text so it reads as a
 * deliberate object on the page. The rule is one hover away via `title`,
 * rather than living only in a document nobody has open.
 */
export function Withheld({ min = 11, reason, className = "" }) {
  return (
    <span
      className={`inline-flex cursor-help items-center gap-1 rounded-btn border border-warn/40 bg-warn-edge/40 px-1.5 py-0.5 font-mono text-[10px] leading-none text-warn ${className}`}
      title={reason ?? `Withheld: fewer than ${min} patients.`}
    >
      &lt;{min}
    </span>
  );
}

/**
 * Text withheld for a reason other than a small count — an ETL traceback, a
 * patient list. No threshold to quote, so it says what it is.
 */
export function NotShown({ reason, children = "not shown", className = "" }) {
  return (
    <span
      className={`inline-flex cursor-help items-center rounded-btn border border-border-strong px-1.5 py-0.5 font-mono text-[10px] leading-none text-text-muted ${className}`}
      title={reason ?? "Withheld from researcher accounts."}
    >
      {children}
    </span>
  );
}
