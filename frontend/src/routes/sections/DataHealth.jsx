import DeleteButton from "../../components/DeleteButton.jsx";
import { count, plural } from "../../lib/format.js";
import { useWorkspace } from "../../lib/workspace.jsx";
import DataHealthCard from "../../panels/DataHealthCard.jsx";
import DataQuality from "../../panels/DataQuality.jsx";
import WatcherLog from "../../panels/WatcherLog.jsx";
import { Card, CardHeader } from "../../ui/Card.jsx";
import Callout from "../../ui/Callout.jsx";
import { Dot } from "../../ui/Status.jsx";
import { Heading, Mono, Note, Num } from "../../ui/Text.jsx";

export default function DataHealth() {
  const { alerts, alertsKnown, models, refresh, containers, version, loading } =
    useWorkspace();
  const builtCount = models.filter((m) => m.is_built).length;

  return (
    <div className="space-y-6">
      <div>
        <Heading level={1} className="text-[24px] leading-tight">
          Data health
        </Heading>
        <Note className="mt-2">
          Silent failures are the norm here — a step can report success and load
          nothing. Everything on this page is read back from the warehouse after
          the fact.
        </Note>
      </div>

      <DataHealthCard />

      {/* Section 3.6 of the clinical review: two totals cannot tell a healthy
          warehouse from a badly polluted one. */}
      <DataQuality refreshKey={version} />

      <Card>
        <CardHeader
          title={
            <>
              <Num>{count(alertsKnown ? alerts.length : undefined)}</Num>{" "}
              {plural(alerts.length, "open problem")}
            </>
          }
          hint="Each of these is a state the warehouse will not complain about on its own."
        />
        <div className="mt-4 space-y-2.5">
          {!alertsKnown ? (
            <Callout tone="neutral" title="checking">
              Reading cohorts, models and the job table. Nothing is ruled out
              until those land.
            </Callout>
          ) : alerts.length === 0 ? (
            <Callout tone="positive" title="nothing flagged">
              No stopped watcher, no drifted or duplicated cohort, no model whose
              training data has been deleted, and no failed job in the last 20.
            </Callout>
          ) : (
            alerts.map((a) => (
              <Callout key={a.id} tone={a.tone} title={a.title}>
                {a.body}
              </Callout>
            ))
          )}
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Containers"
          hint="The two containers the backend shells into, and whether any call actually proves one answered."
        />
        <ul className="mt-4 space-y-2.5">
          {containers.map((c) => (
            <li
              key={c.id}
              className="flex items-start justify-between gap-4 rounded-row border border-border-soft bg-panel-sunk px-4 py-3"
            >
              <div className="min-w-0">
                <Mono className="text-[13px] text-text">{c.id}</Mono>
                <p className="mt-0.5 text-[11px] leading-relaxed text-text-muted">
                  {c.why ?? `${c.role} · proved by the ${c.via}`}
                </p>
              </div>
              <span className="flex shrink-0 items-center gap-2 text-[12px] text-text-2">
                <Dot
                  tone={
                    c.state === "reachable"
                      ? "positive"
                      : c.state === "unreachable"
                        ? "danger"
                        : "idle"
                  }
                />
                {c.state}
              </span>
            </li>
          ))}
        </ul>
        <Note className="mt-3">
          There is no container endpoint. The database row is inferred from the
          row-count query, which fails loudly. The ETL row has no sound probe:
          the watcher check ignores its exit code, and the registry read is
          cached after its first success. Uptime, image and restart count are
          not available anywhere in the API.
        </Note>
      </Card>

      <WatcherLog />

      <Card className="border-danger-edge">
        <CardHeader
          title="Danger zone"
          hint="These do not delete a dataset — the CLI ignores any path and truncates the warehouse tables wholesale."
        />
        <div className="mt-5 space-y-5">
          <div className="space-y-2.5">
            <DeleteButton
              endpoint="/delete-concepts"
              label="wipe all concepts"
              target="concepts"
              onDeleted={refresh}
            />
            {models.length > 0 && (
              <Callout tone="danger" title="this destroys every model">
                Models are concepts, so wiping concepts also destroys all{" "}
                <Num>{count(loading ? undefined : models.length)}</Num>{" "}
                {plural(models.length, "model")}{" "}
                — config and trained weights both
                {builtCount > 0 && (
                  <>
                    , including <Num>{count(builtCount)}</Num> already built
                  </>
                )}
                . There is no history and no undo.
              </Callout>
            )}
          </div>

          <div className="space-y-2.5 border-t border-border-soft pt-5">
            <DeleteButton
              endpoint="/delete-facts"
              label="wipe all facts"
              target="facts"
              onDeleted={refresh}
            />
            <Note>
              Wiping facts leaves models in place but strands them: they stay
              marked built while the data they learned from is gone. They show as{" "}
              <span className="text-danger">training data deleted</span>{" "}
              afterwards.
            </Note>
          </div>

          <Note className="border-t border-border-soft pt-5">
            Cohorts survive both, and are wiped from the cohorts section.
          </Note>
        </div>
      </Card>
    </div>
  );
}
