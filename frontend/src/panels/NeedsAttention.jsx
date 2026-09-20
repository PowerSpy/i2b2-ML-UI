import { useState } from "react";

import { Link } from "../lib/router.jsx";
import { useWorkspace } from "../lib/workspace.jsx";
import Button from "../ui/Button.jsx";
import Callout from "../ui/Callout.jsx";
import { SectionLabel } from "../ui/Text.jsx";

/**
 * Conditions the warehouse will not complain about on its own.
 *
 * Empty is a real result here and says so, rather than rendering nothing —
 * "no open problems" and "this panel is broken" have to be distinguishable.
 */
export default function NeedsAttention() {
  const { alerts } = useWorkspace();

  return (
    <section>
      <SectionLabel className="mb-2.5">Needs attention</SectionLabel>

      {alerts.length === 0 ? (
        <Callout tone="positive" title="nothing flagged">
          No stopped watcher, no drifted or duplicated cohort, no model whose
          data has been deleted, and no failed job in the last 20.
        </Callout>
      ) : (
        <div className="space-y-2.5">
          {alerts.map((alert) => (
            <AlertCard key={alert.id} alert={alert} />
          ))}
        </div>
      )}
    </section>
  );
}

function AlertCard({ alert }) {
  const { startWatcher, refresh } = useWorkspace();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await startWatcher();
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Callout tone={alert.tone} title={alert.title}>
      <p>{alert.body}</p>

      {alert.to && (
        <Link
          to={alert.to}
          className="mt-2 inline-block text-[12px] text-accent hover:underline"
        >
          open
        </Link>
      )}

      {alert.action?.kind === "start-watcher" && (
        <div className="mt-3">
          <Button variant="danger" onClick={start} disabled={busy}>
            {busy ? "starting…" : alert.action.label}
          </Button>
          {error && <p className="mt-2 text-[11px] text-danger">{error}</p>}
        </div>
      )}
    </Callout>
  );
}
