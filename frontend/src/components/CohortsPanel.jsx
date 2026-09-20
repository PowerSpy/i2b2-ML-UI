import { useState } from "react";

import { apiDelete, apiPost } from "../lib/api.js";
import { count } from "../lib/format.js";
import Button from "../ui/Button.jsx";
import Callout, { Empty } from "../ui/Callout.jsx";
import { Status } from "../ui/Status.jsx";
import { Table, Td, Th, ThHidden } from "../ui/Table.jsx";
import { Mono, Num } from "../ui/Text.jsx";

const NAME_RE = /^[A-Za-z0-9_-]{1,80}$/;

const FIELD =
  "min-h-[44px] w-full rounded-btn border border-border-strong bg-panel-sunk px-3 text-[13px] text-text placeholder:text-text-muted";

/**
 * Recorded size against live membership.
 *
 * Cohorts survive `wipe concepts` and `wipe facts`, so the set_size recorded
 * when the set was built and the number of members that still have facts drift
 * apart. Both are shown; a mismatch is the "drifted" state.
 */
export function CohortsTable({ cohorts, onDelete, busy }) {
  if (!cohorts.length) {
    return (
      <Empty>
        No patient sets yet. A cohort is every patient holding one concept code
        — you need one per class to train, plus one for the population you want
        to score.
      </Empty>
    );
  }

  return (
    <Table>
      <thead>
        <tr>
          <Th>name</Th>
          <Th>id</Th>
          <Th align="right">recorded</Th>
          <Th align="right">live</Th>
          <Th>state</Th>
          {onDelete && <ThHidden>delete</ThHidden>}
        </tr>
      </thead>
      <tbody>
        {cohorts.map((c) => {
          const live = c.live ?? c.size;
          const drift = live - c.size;
          return (
            <tr key={c.id}>
              <Td>
                <Mono className="text-text">{c.name}</Mono>
              </Td>
              <Td>
                <Num className="text-text-muted">{c.id}</Num>
              </Td>
              <Td align="right">
                <Num>{count(c.size)}</Num>
              </Td>
              <Td align="right">
                <Num className={c.stale ? "text-warn" : "text-text-2"}>
                  {count(live)}
                </Num>
              </Td>
              <Td>
                {c.duplicate ? (
                  <Status tone="danger">duplicate name</Status>
                ) : c.stale ? (
                  <Status tone="warn">
                    drifted — {count(Math.abs(drift))}{" "}
                    {drift < 0 ? "lost since" : "added since"}
                  </Status>
                ) : (
                  <Status tone="positive">stable</Status>
                )}
              </Td>
              {onDelete && (
                <Td align="right">
                  <button
                    type="button"
                    onClick={() => onDelete(c.id)}
                    disabled={busy}
                    className="min-h-[44px] px-2 text-[12px] text-danger hover:underline disabled:opacity-50"
                  >
                    delete
                  </button>
                </Td>
              )}
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

/** The table plus the controls that change it. */
export default function CohortsPanel({ cohorts, concepts, onChange }) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [wipeArmed, setWipeArmed] = useState(false);

  const duplicate = cohorts.some((c) => c.name === name);
  const validName = NAME_RE.test(name);
  const canCreate = validName && !duplicate && code && !busy;

  async function run(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChange?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const create = () =>
    run(async () => {
      await apiPost("/cohorts", { name, concept_code: code });
      setName("");
    });

  const remove = (id) => run(() => apiDelete(`/cohorts/${id}`));

  const wipe = () => {
    setWipeArmed(false);
    return run(() => apiDelete("/cohorts"));
  };

  return (
    <div className="space-y-5">
      <CohortsTable cohorts={cohorts} onDelete={remove} busy={busy} />

      {cohorts.some((c) => c.stale) && (
        <Callout tone="warn" title="stale membership">
          A stale cohort still lists members whose facts were wiped. Training on
          one silently uses fewer patients than its size suggests.
        </Callout>
      )}

      {cohorts.some((c) => c.duplicate) && (
        <Callout tone="danger" title="ambiguous name">
          Two or more patient sets share a name. Training resolves a cohort name
          to <em>every</em> set carrying it and unions them, so a model would
          train on the combination rather than the one you meant. Delete the
          ones you do not want — models refuse to save against an ambiguous
          name.
        </Callout>
      )}

      <div className="space-y-3 border-t border-border-soft pt-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-52">
            <label className="mb-1.5 block text-[12px] text-text-3" htmlFor="cohort-name">
              name
            </label>
            <input
              id="cohort-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="positive_cases"
              className={`${FIELD} font-mono`}
            />
          </div>
          <div className="min-w-0 flex-1">
            <label className="mb-1.5 block text-[12px] text-text-3" htmlFor="cohort-code">
              from concept code
            </label>
            <select
              id="cohort-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className={`${FIELD} font-mono`}
            >
              <option value="">— pick a concept —</option>
              {concepts.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code} {c.type ? `(${c.type})` : ""}
                </option>
              ))}
            </select>
          </div>
          <Button variant="primary" onClick={create} disabled={!canCreate}>
            {busy ? "working…" : "Create cohort"}
          </Button>
        </div>

        {name && !validName && (
          <p className="text-[12px] text-danger">
            letters, digits, underscore and hyphen only (max 80)
          </p>
        )}
        {duplicate && (
          <p className="text-[12px] text-danger">
            a cohort called <Mono>{name}</Mono> already exists — names must be
            unique
          </p>
        )}
        {concepts.length === 0 && (
          <p className="text-[12px] text-text-muted">
            no concepts loaded, so there is nothing to build a cohort from
          </p>
        )}
        <p className="text-[12px] text-text-muted">
          Pick an <Mono>assertion</Mono> concept, not a <Mono>float</Mono> one. A
          cohort from a measurement column means &ldquo;everyone who has that
          measurement&rdquo; — usually everybody, with no error.
        </p>
      </div>

      {error && (
        <Callout tone="danger" title="request failed">
          {error}
        </Callout>
      )}

      {cohorts.length > 0 && (
        <div className="border-t border-border-soft pt-4">
          {wipeArmed ? (
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-[12px] text-text-2">
                Delete all <Num>{cohorts.length}</Num> cohorts?
              </span>
              <Button variant="danger" onClick={wipe}>
                yes, delete all
              </Button>
              <Button onClick={() => setWipeArmed(false)}>cancel</Button>
            </div>
          ) : (
            <Button variant="quiet" className="px-0" onClick={() => setWipeArmed(true)}>
              <span className="text-danger">delete all cohorts</span>
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
