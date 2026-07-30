import { useEffect, useState } from "react";

import { apiDelete, apiGet, apiPost } from "../lib/api.js";
import Warning from "./Warning.jsx";

const NAME_RE = /^[A-Za-z0-9_-]{1,80}$/;

/**
 * Cohorts survive `wipe concepts` / `wipe facts`, so recorded set_size and live
 * membership drift apart. Both are shown; a mismatch is flagged.
 */
export default function CohortsPanel({ cohorts, concepts, onChange }) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [sizes, setSizes] = useState({});
  const [wipeArmed, setWipeArmed] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all(
      cohorts.map((c) =>
        apiGet(`/cohorts/${c.id}/size`)
          .then((s) => [c.id, s])
          .catch(() => [c.id, null]),
      ),
    ).then((pairs) => {
      if (alive) setSizes(Object.fromEntries(pairs));
    });
    return () => {
      alive = false;
    };
  }, [cohorts]);

  const duplicate = cohorts.some((c) => c.name === name);
  const validName = NAME_RE.test(name);
  const canCreate = validName && !duplicate && code && !busy;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await apiPost("/cohorts", { name, concept_code: code });
      setName("");
      onChange?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id) {
    setBusy(true);
    setError(null);
    try {
      await apiDelete(`/cohorts/${id}`);
      onChange?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function wipe() {
    setBusy(true);
    setError(null);
    setWipeArmed(false);
    try {
      await apiDelete("/cohorts");
      onChange?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-neutral-500">
        A cohort is every patient holding the concept code you pick. Build one
        per class for training, plus one for the population you want to score.
      </p>

      {cohorts.length > 0 && (
        <table className="w-full text-left text-xs">
          <thead className="text-neutral-500">
            <tr>
              <th className="pb-2 font-normal">name</th>
              <th className="pb-2 font-normal">id</th>
              <th className="pb-2 text-right font-normal">recorded</th>
              <th className="pb-2 text-right font-normal">live</th>
              <th />
            </tr>
          </thead>
          <tbody className="text-neutral-300">
            {cohorts.map((c) => {
              const live = sizes[c.id];
              return (
                <tr key={c.id} className="border-t border-neutral-800/70">
                  <td className="py-2">{c.name}</td>
                  <td className="py-2 text-neutral-500">{c.id}</td>
                  <td className="py-2 text-right tabular-nums">
                    {c.size.toLocaleString()}
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {live == null ? (
                      <span className="text-neutral-600">…</span>
                    ) : (
                      <span
                        className={live.stale ? "text-amber-400" : undefined}
                      >
                        {live.live.toLocaleString()}
                        {live.stale && " stale"}
                      </span>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    <button
                      onClick={() => remove(c.id)}
                      disabled={busy}
                      className="text-red-400 hover:text-red-300 disabled:opacity-50"
                    >
                      delete
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {cohorts.some((c) => sizes[c.id]?.stale) && (
        <Warning>
          A stale cohort still lists members whose facts were wiped. Training on
          one silently uses fewer patients than its size suggests.
        </Warning>
      )}

      <div className="flex flex-wrap items-end gap-2 border-t border-neutral-800 pt-4">
        <div>
          <label className="mb-1 block text-xs text-neutral-500">name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="positive_cases"
            className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-sm"
          />
        </div>
        <div className="min-w-0 flex-1">
          <label className="mb-1 block text-xs text-neutral-500">
            from concept code
          </label>
          <select
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-sm"
          >
            <option value="">— pick a concept —</option>
            {concepts.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} {c.type ? `(${c.type})` : ""}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={create}
          disabled={!canCreate}
          className="rounded bg-sky-800 px-3 py-1.5 text-sm text-sky-50 hover:bg-sky-700 disabled:opacity-40"
        >
          {busy ? "working…" : "Create"}
        </button>
      </div>

      {name && !validName && (
        <p className="text-xs text-red-400">
          letters, digits, underscore and hyphen only (max 80)
        </p>
      )}
      {duplicate && (
        <p className="text-xs text-red-400">
          a cohort called {name} already exists — names must be unique
        </p>
      )}
      {concepts.length === 0 && (
        <p className="text-xs text-neutral-500">
          no concepts loaded, so there is nothing to build a cohort from
        </p>
      )}

      {error && (
        <p className="rounded border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          {error}
        </p>
      )}

      {cohorts.length > 0 && (
        <div className="border-t border-neutral-800 pt-3 text-xs">
          {wipeArmed ? (
            <span className="flex items-center gap-2">
              <span className="text-neutral-300">
                Delete all {cohorts.length} cohorts?
              </span>
              <button
                onClick={wipe}
                className="rounded bg-red-900 px-2 py-1 text-red-100 hover:bg-red-800"
              >
                yes, delete
              </button>
              <button
                onClick={() => setWipeArmed(false)}
                className="rounded border border-neutral-700 px-2 py-1 text-neutral-300"
              >
                cancel
              </button>
            </span>
          ) : (
            <button
              onClick={() => setWipeArmed(true)}
              className="text-red-400 hover:text-red-300"
            >
              delete all cohorts
            </button>
          )}
        </div>
      )}
    </div>
  );
}
