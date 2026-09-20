import { useEffect, useState } from "react";

import { apiGet } from "./api.js";

const TERMINAL = ["COMPLETED", "ERROR"];

/**
 * Polls the job table until `jobId` reaches a terminal status. Jobs are queued,
 * not run, by the POST that creates them — this is the only way to learn what
 * happened.
 */
const MAX_INTERVAL = 15000;
/* A build takes seconds to minutes. Past this, something is wrong in a way
   more polling will not discover. */
const GIVE_UP_AFTER = 20 * 60 * 1000;

export default function useJobPoll(jobId, { interval = 3000 } = {}) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [gaveUp, setGaveUp] = useState(false);

  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    let timer = null;
    let delay = interval;
    const startedAt = Date.now();

    async function tick() {
      // Every poll is a psql call through `docker exec`. A fixed 3s interval
      // meant a long training run spent its whole duration re-asking, and a job
      // id that never appears polled forever with nothing on screen to say so.
      if (Date.now() - startedAt > GIVE_UP_AFTER) {
        if (alive) setGaveUp(true);
        return;
      }

      try {
        const jobs = await apiGet("/jobs?limit=20");
        if (!alive) return;
        const found = jobs.find((j) => j.id === jobId) ?? null;
        setJob(found);
        setError(null);
        if (found && TERMINAL.includes(found.status)) return;
        // Steady while the row is visible and moving; backs off when it is not,
        // which is the case that used to spin.
        delay = found ? interval : Math.min(delay * 1.5, MAX_INTERVAL);
      } catch (e) {
        if (!alive) return;
        setError(e.message);
        delay = Math.min(delay * 2, MAX_INTERVAL);
      }
      timer = setTimeout(tick, delay);
    }

    setJob(null);
    setError(null);
    setGaveUp(false);
    tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, interval]);

  const status = job?.status ?? (jobId ? "SUBMITTED" : null);
  return {
    job,
    status,
    error,
    gaveUp,
    done: TERMINAL.includes(status),
  };
}
