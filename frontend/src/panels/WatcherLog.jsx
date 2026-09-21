import { useCallback, useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";
import Button from "../ui/Button.jsx";
import { Card, CardHeader } from "../ui/Card.jsx";
import { Empty, Failed } from "../ui/Callout.jsx";
import { Note } from "../ui/Text.jsx";

/**
 * The job watcher's own log.
 *
 * `/watcher/log` has always existed and was never called. When a job sits at
 * PENDING this is the one artifact that says why — the job row records
 * nothing until a watcher picks it up, so from the job's side a queue nobody
 * is reading looks identical to a queue that is simply busy.
 *
 * Collapsed by default: it is a tail of a file inside the container, fetched
 * over `docker exec`, and worth a round trip only when someone is debugging.
 */
export default function WatcherLog({ lines = 200 }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState({ loading: false });

  const load = useCallback(() => {
    setState({ loading: true });
    apiGet(`/watcher/log?lines=${encodeURIComponent(lines)}`)
      .then((data) => setState({ loading: false, data }))
      .catch((e) => setState({ loading: false, error: e.message }));
  }, [lines]);

  useEffect(() => {
    if (open && !state.data && !state.error && !state.loading) load();
  }, [open, load, state]);

  const text = state.data?.lines?.trimEnd();

  return (
    <Card>
      <CardHeader
        title="Watcher log"
        hint="What the background worker has been doing. The only place a job stuck at PENDING explains itself."
      >
        {open && (
          <Button onClick={load} disabled={state.loading}>
            {state.loading ? "reading…" : "refresh"}
          </Button>
        )}
        <Button onClick={() => setOpen((o) => !o)}>{open ? "hide" : "open"}</Button>
      </CardHeader>

      {open && (
        <div className="mt-4">
          {state.error ? (
            <Failed what="the watcher log" error={state.error} />
          ) : state.loading && !text ? (
            <Empty>Reading the log from the container…</Empty>
          ) : !text ? (
            <Empty>
              The log is empty. The watcher writes to it only once it has picked
              up a job, so a never-started watcher leaves nothing behind.
            </Empty>
          ) : (
            <>
              <pre className="max-h-[420px] overflow-auto rounded-row border border-border-soft bg-panel-sunk p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-text-3">
                {text}
              </pre>
              <Note className="mt-2">
                Last {lines} lines of <code>/tmp/jobwatcher.log</code> inside the
                ETL container. It is not rotated, and it is lost on{" "}
                <code>docker rm</code>.
              </Note>
            </>
          )}
        </div>
      )}
    </Card>
  );
}
