import { count } from "../lib/format.js";
import { useWorkspace } from "../lib/workspace.jsx";
import Button from "../ui/Button.jsx";
import { Card, CardHeader } from "../ui/Card.jsx";
import { Failed, NotReported } from "../ui/Callout.jsx";
import { Stat } from "../ui/Meter.jsx";

/**
 * What is actually in the warehouse.
 *
 * Two of the four panels the design calls for have no endpoint behind them.
 * They are rendered as explicit "not reported" rather than as zeroes, because
 * in this system "nothing was rejected" and "nobody counts rejections" are
 * very different claims and a 0 would read as the first one.
 */
export default function DataHealthCard({ project = null }) {
  const { verify, refresh, loading, concepts } = useWorkspace();

  // An em dash until the read lands: a confident 0 here would claim the
  // warehouse is empty when it has simply not been asked yet.
  const conceptCount = loading
    ? undefined
    : project
      ? project.concepts.length
      : concepts.length;
  const sparse = project
    ? project.concepts.filter((c) => !c.type).length
    : concepts.filter((c) => !c.type).length;

  return (
    <Card>
      <CardHeader
        title="Data health"
        hint={
          project
            ? "Fact counts come from the whole warehouse; concept counts are this project's subtree."
            : "Row counts read straight from the database, not from any loader's response."
        }
      >
        <Button onClick={refresh} disabled={loading}>
          {loading ? "re-scanning…" : "re-scan"}
        </Button>
      </CardHeader>

      {verify?.error ? (
        <Failed what="the row counts" error={verify.error} className="mt-4" />
      ) : (
        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            value={count(verify?.data?.facts)}
            label="facts loaded"
            sub="one row per patient per value, warehouse-wide"
          />
          <Stat
            value={count(conceptCount)}
            label="concepts declared"
            sub={
              sparse > 0
                ? `${sparse} with no declared type`
                : project
                  ? "in this subtree"
                  : "across every subtree"
            }
          />
          <NotReported label="values auto-corrected">
            The loader repairs blanks and <code>?</code> tokens as it goes but
            never counts them. Only its stdout mentions them, and only per run.
          </NotReported>
          <NotReported label="rows rejected">
            No endpoint returns a rejection count. A load that rejected every row
            still exits 0 — the rows-gained figure on each upload is the only
            signal.
          </NotReported>
        </div>
      )}

      {verify?.data && verify.data.status !== "ok" && (
        <p className="mt-4 text-[12px] text-danger">
          The count query failed inside the database container — these numbers
          are stale.
        </p>
      )}
    </Card>
  );
}
