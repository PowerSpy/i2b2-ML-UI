import { useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";
import { downloadCsv } from "../lib/csv.js";
import { count, plural } from "../lib/format.js";
import Button from "../ui/Button.jsx";
import { Card, CardHeader } from "../ui/Card.jsx";
import Callout, { Empty, Failed } from "../ui/Callout.jsx";
import { Stat } from "../ui/Meter.jsx";
import { Pill } from "../ui/Status.jsx";
import { Table, Td, Th } from "../ui/Table.jsx";
import { Mono, Note, Num, SectionLabel } from "../ui/Text.jsx";

/**
 * Whether the warehouse is healthy or quietly polluted.
 *
 * Total facts and total concepts cannot tell those apart: a dataset loaded
 * three times reports a bigger number and looks like more data. Everything
 * here is a read, and it is deliberately a separate request from the rest of
 * the app — the duplicate scan is the one query that touches every row.
 */
export default function DataQuality({ refreshKey = 0 }) {
  const [state, setState] = useState({ loading: true });

  useEffect(() => {
    let alive = true;
    setState({ loading: true });
    apiGet("/data-quality")
      .then((data) => alive && setState({ loading: false, data }))
      .catch((e) => alive && setState({ loading: false, error: e.message }));
    return () => {
      alive = false;
    };
  }, [refreshKey]);

  if (state.loading) return <Card><Empty>Scanning every fact row…</Empty></Card>;
  if (state.error)
    return (
      <Card>
        <Failed what="the data quality scan" error={state.error} />
      </Card>
    );

  const d = state.data;
  const dupPct = d.facts.total ? (100 * d.facts.duplicates) / d.facts.total : 0;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Duplicate and orphan rows"
          hint="Two rows are the same observation when patient, concept, date and value all match. Loading the same CSV twice produces these, and every other count in this app counts them."
        />
        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Stat value={count(d.facts.total)} label="fact rows" sub="what every count reports" />
          <Stat
            value={count(d.facts.distinct)}
            label="distinct observations"
            sub="what the data actually contains"
          />
          <Stat
            value={count(d.facts.duplicates)}
            label="exact duplicates"
            tone={d.facts.duplicates > 0 ? "warn" : undefined}
            sub={`${dupPct.toFixed(1)}% of the table`}
          />
        </div>

        {d.facts.duplicates > 0 && (
          <Callout tone="warn" title="counts are inflated" className="mt-4">
            <Num className="text-text-2">{count(d.facts.duplicates)}</Num> rows
            repeat an observation already present. Training reads the fact table
            directly, so a patient with a value loaded three times carries three
            times the weight of one loaded once.
          </Callout>
        )}

        {d.orphan_facts > 0 && (
          <Callout tone="danger" title="facts with no declared concept" className="mt-3">
            <Num className="text-text-2">{count(d.orphan_facts)}</Num>{" "}
            {plural(d.orphan_facts, "row")} reference a concept code that is not
            in <Mono>concept_dimension</Mono>. No path-based selection can reach
            them, so they are invisible to every cohort and every feature path
            while still counting towards the totals above.
          </Callout>
        )}
      </Card>

      <Card>
        <CardHeader
          title="Per dataset"
          hint="Each fact lands in exactly one row here, so these plus the orphans account for the whole table."
        />
        <div className="mt-4">
          <Table>
            <thead>
              <tr>
                <Th>root</Th>
                <Th align="right">facts</Th>
                <Th align="right">patients</Th>
                <Th align="right">concepts</Th>
              </tr>
            </thead>
            <tbody>
              {d.datasets.map((x) => (
                <tr key={x.root}>
                  <Td>
                    {x.ambiguous ? (
                      <span className="text-warn">{x.root}</span>
                    ) : (
                      <Mono className="text-text">{x.root}</Mono>
                    )}
                  </Td>
                  <Td align="right">
                    <Num>{count(x.facts)}</Num>
                  </Td>
                  <Td align="right">
                    <Num>{count(x.patients)}</Num>
                  </Td>
                  <Td align="right">
                    <Num>{count(x.concepts)}</Num>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      </Card>

      {d.colliding_codes.length > 0 && (
        <Card>
          <CardHeader
            title={
              <>
                <Num>{count(d.colliding_codes.length)}</Num> colliding{" "}
                {plural(d.colliding_codes.length, "concept code")}
              </>
            }
            hint="The same code declared under more than one dataset. i2b2 stores facts against the code, not the path, so both datasets write into one bucket."
          />
          <div className="mt-4 space-y-2">
            {d.colliding_codes.map((c) => (
              <div
                key={c.code}
                className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-row border border-warn-edge bg-warn-edge/25 px-4 py-3"
              >
                <Mono className="text-[13px] text-text">{c.code}</Mono>
                <span className="text-[12px] text-text-3">declared under</span>
                {c.under.map((u) => (
                  <Pill key={u} tone="warn">
                    {u}
                  </Pill>
                ))}
              </div>
            ))}
          </div>
          <Callout tone="danger" title="what this breaks" className="mt-4">
            A cohort built from a colliding code selects patients from every
            dataset that declares it, and a feature path picks up the other
            study&apos;s values. Neither raises an error — the model simply
            trains on a population nobody chose.
          </Callout>
        </Card>
      )}

      {d.patient_overlap.length > 0 && (
        <Card>
          <CardHeader
            title="Shared patients"
            hint="Patient numbers appearing under two datasets, counting only concepts that belong to exactly one of them."
          />
          <div className="mt-4 space-y-2">
            {d.patient_overlap.map((o) => (
              <div
                key={`${o.left}-${o.right}`}
                className="flex items-center justify-between gap-3 rounded-row border border-border-soft bg-panel-sunk px-4 py-3"
              >
                <span className="text-[12px] text-text-2">
                  <Mono>{o.left}</Mono> and <Mono>{o.right}</Mono>
                </span>
                <Num className="text-[13px] text-warn">{count(o.shared)}</Num>
              </div>
            ))}
          </div>
          <Note className="mt-3">
            Two studies sharing patient numbers is either one cohort measured
            twice or, more often, a reload that reused numbering.
          </Note>
        </Card>
      )}

      {d.concepts_without_facts.length > 0 && (
        <Card>
          <CardHeader
            title={
              <>
                <Num>{count(d.concepts_without_facts.length)}</Num> declared{" "}
                {plural(d.concepts_without_facts.length, "concept")} with no facts
              </>
            }
            hint="Declared in a concepts CSV but never populated. Folder nodes legitimately have none; a measurement column with none means its facts never loaded."
          />
          <div className="mt-4 flex flex-wrap gap-1.5">
            {d.concepts_without_facts.map((c) => (
              <Pill key={c}>{c}</Pill>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Per concept"
          hint="Facts and distinct patients for every code carrying data, busiest first."
        >
          <Button
            onClick={() =>
              downloadCsv(
                "concept_counts.csv",
                ["code", "facts", "patients"],
                d.concepts.map((c) => [c.code, c.facts, c.patients]),
              )
            }
          >
            export
          </Button>
        </CardHeader>
        <div className="mt-4 max-h-[420px] overflow-y-auto">
          <Table>
            <thead>
              <tr>
                <Th>code</Th>
                <Th align="right">facts</Th>
                <Th align="right">patients</Th>
                <Th align="right">facts per patient</Th>
              </tr>
            </thead>
            <tbody>
              {d.concepts.map((c) => {
                const per = c.patients ? c.facts / c.patients : 0;
                return (
                  <tr key={c.code}>
                    <Td>
                      <Mono className="text-text">{c.code}</Mono>
                    </Td>
                    <Td align="right">
                      <Num>{count(c.facts)}</Num>
                    </Td>
                    <Td align="right">
                      <Num>{count(c.patients)}</Num>
                    </Td>
                    <Td align="right">
                      {/* One value per patient is the norm. Above that means
                          repeated loads or genuinely repeated measurements,
                          and nothing else distinguishes the two. */}
                      <Num className={per > 1.5 ? "text-warn" : "text-text-3"}>
                        {per.toFixed(1)}
                      </Num>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </div>
        <SectionLabel className="mt-3">
          facts per patient above 1.5 is flagged — repeated loads look exactly
          like repeated measurements here
        </SectionLabel>
      </Card>
    </div>
  );
}
