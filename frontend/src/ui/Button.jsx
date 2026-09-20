/**
 * Every button in the app, at a 44px minimum height.
 *
 * `primary` is the accent fill and there is at most one per panel; `default` is
 * the outlined workhorse; `danger` is for the two-step deletes, which are the
 * only irreversible actions here; `quiet` is a text button that still meets the
 * height floor through padding rather than looking like a link.
 */
const VARIANTS = {
  primary:
    "bg-accent text-ground font-semibold hover:bg-accent/90 disabled:bg-accent/30 disabled:text-ground/60",
  default:
    "border border-border-strong bg-panel text-text-2 hover:border-text-muted hover:text-text disabled:text-text-muted",
  danger:
    "border border-danger/50 bg-danger-edge/40 text-danger hover:border-danger hover:bg-danger-edge disabled:text-danger/40",
  quiet:
    "text-text-3 hover:text-text disabled:text-text-muted",
};

export default function Button({
  variant = "default",
  type = "button",
  className = "",
  children,
  ...rest
}) {
  return (
    <button
      type={type}
      className={`inline-flex min-h-[44px] items-center justify-center gap-2 rounded-btn px-4 text-[13px] transition-colors disabled:cursor-not-allowed ${
        VARIANTS[variant] ?? VARIANTS.default
      } ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/**
 * A button that navigates. Same geometry, rendered as an anchor so that
 * middle-click and "open in new tab" behave.
 */
export function ButtonLink({ variant = "default", className = "", children, ...rest }) {
  return (
    <a
      className={`inline-flex min-h-[44px] items-center justify-center gap-2 rounded-btn px-4 text-[13px] transition-colors ${
        VARIANTS[variant] ?? VARIANTS.default
      } ${className}`}
      {...rest}
    >
      {children}
    </a>
  );
}
