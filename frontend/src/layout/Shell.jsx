import TopBar from "./TopBar.jsx";

/**
 * The app shell: a 62px bar, then a flex row that fills the rest of the window.
 *
 * The three columns scroll independently. That is the point of the restructure
 * — the rails hold context (what state the warehouse is in, what is queued,
 * what a path means) and the centre holds the thing being worked on, so
 * scrolling one must not take the other off screen.
 */
export default function Shell({ children }) {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-ground">
      <TopBar />
      <div className="flex min-h-0 flex-1">{children}</div>
    </div>
  );
}

export function LeftRail({ width = 216, children, className = "" }) {
  return (
    <aside
      style={{ width, minWidth: width }}
      className={`flex min-h-0 flex-col border-r border-border bg-panel ${className}`}
    >
      {children}
    </aside>
  );
}

export function RightRail({ width = 330, children, className = "" }) {
  return (
    <aside
      style={{ width, minWidth: width }}
      className={`min-h-0 overflow-y-auto border-l border-border bg-panel px-4 py-5 ${className}`}
    >
      <div className="space-y-5">{children}</div>
    </aside>
  );
}

/**
 * The centre column. Carries the id the router scrolls back to the top on a
 * route change — the window itself never scrolls here.
 */
export function Centre({ children, className = "" }) {
  return (
    <main id="centre" className={`min-w-0 flex-1 overflow-y-auto ${className}`}>
      <div className="mx-auto max-w-[1100px] px-7 py-6">{children}</div>
    </main>
  );
}
