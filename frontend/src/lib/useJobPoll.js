import { useEffect, useState } from "react";

import { apiGet } from "./api.js";

const TERMINAL = ["COMPLETED", "ERROR"];

/**
 * Polls the job table until `jobId` reaches a terminal status. Jobs are queued,
 * not run, by the POST that creates them — this is the only way to learn what
 * happened.
 */
export default function useJobPoll(jobId, { interval = 3000 } = {}) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    let timer = null;

    async function tick() {
      try {
        const jobs = await apiGet("/jobs?limit=20");
        if (!alive) return;
        const found = jobs.find((j) => j.id === jobId) ?? null;
        setJob(found);
        if (found && TERMINAL.includes(found.status)) return;
      } catch (e) {
        if (!alive) return;
        setError(e.message);
      }
      timer = setTimeout(tick, interval);
    }

    setJob(null);
    setError(null);
    tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, interval]);

  const status = job?.status ?? (jobId ? "SUBMITTED" : null);
  return { job, status, error, done: TERMINAL.includes(status) };
}
