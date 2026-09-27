import { useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";
import { downloadCsv } from "../lib/csv.js";
import { count, plural, score } from "../lib/format.js";
import Button from "../ui/Button.jsx";
import { Card, CardHeader } from "../ui/Card.jsx";
import Callout, { Empty, Failed } from "../ui/Callout.jsx";
import Meter from "../ui/Meter.jsx";
import { Pill } from "../ui/Status.jsx";
import { Table, Td, Th } from "../ui/Table.jsx";
import { Mono, Note, Num } from "../ui/Text.jsx";

/**
 * The shape of the data, without a single patient row.
 *
 * This is what makes it possible to write a feature transform against data you
 * are not allowed to see: column names, types, how often each is populated,
 * and where the values sit. Everything is an aggregate and everything small is
 * withheld.
 */
export default function DataDictionary({ endpoint, title, hint }) {
  const [state, setState] = useState({ loading: true });

  useEffect(() => {
    let alive = true;
    setState({ loading: true });
    apiGet(endpoint)
      .then((data) => alive && setState({ loading: false, data }))
      .catch((e) => alive && setState({ loading: false, error: e.message }));
    return () => {
      alive = false;
    };
  }, [endpoint]);

  if (state.loading) {
    return (
      <Card>
        <Empty>Reading column shapes…</Empty>
      </Card>
    );
  }
  if (state.error) {
    return (
      <Card>
        <Failed what="the data dictionary" error={state.error} />
      </Card>
    );
  }

  const d = state.data;
  const withheld = d.columns.filter((c) => c.suppressed.length > 0).length;

  return (
    <Card>
      <CardHeader title={title} hint={hint}>
        <Button
          onClick={() =>
            downloadCsv(
              "data_dictionary.csv",
              ["code", "name", "kind", "patients_with_value", "fill_rate",
               "n_distinct", "low_p01", "p25", "p50", "p75", "high_p99",
               "mean", "sd", "withheld"],
              d.columns.map((c) => [
                c.code, c.name ?? "", c.kind, c.patients_with_value ?? "",
                c.fill_rate ?? "", c.n_distinct ?? "", c.low ?? "", c.p25 ?? "",
                c.p50 ?? "", c.p75 ?? "", c.high ?? "", c.mean ?? "",
                c.sd ?? "", c.suppressed.join(" ") || "",
              ]),
            )
          }
        >
          export
        </Button>
      </CardHeader>

      <div className="mt-4 flex flex-wrap items-baseline gap-x-8 gap-y-2">
        <span className="text-[12px] text-text-3">
          scope <Mono className="text-text-2">{d.scope}</Mono>
        </span>
        <span className="text-[12px] text-text-3">
          patients{" "}
          {d.patients_in_scope == null ? (
            <Withheld min={d.min_cell} />
          ) : (
            <Num className="text-text-2">{count(d.patients_in_scope)}</Num>
          )}
        </span>
        <span className="text-[12px] text-text-3">
          columns <Num className="text-text-2">{count(d.columns.length)}</Num>
        </span>
      </div>

      <Note className="mt-3">{d.note}</Note>

      {d.columns.length === 0 ? (
        <Empty className="mt-4">
          No concepts in this scope. For a model, that means its data paths
          resolved to nothing — which is also why its build would have no
          features.
        </Empty>
      ) : (
        <div className="mt-4 max-h-[520px] overflow-y-auto">
          <Table>
            <thead>
              <tr>
                <Th>code</Th>
                <Th>kind</Th>
                <Th align="right">patients</Th>
                <Th>fill</Th>
                <Th align="right">p01</Th>
                <Th align="right">median</Th>
                <Th align="right">p99</Th>
                <Th>values</Th>
              </tr>
            </thead>
            <tbody>
              {d.columns.map((c) => (
                <Row key={c.code} c={c} minCell={d.min_cell} />
              ))}
            </tbody>
          </Table>
        </div>
      )}

      <Callout tone="neutral" title="what these numbers are" className="mt-4">
        {d.basis}
        {withheld > 0 && (
          <>
            {" "}
            <Num className="text-text-2">{count(withheld)}</Num>{" "}
            {plural(withheld, "column")} had something withheld.
          </>
        )}
      </Callout>
    </Card>
  );
}

/**
 * A withheld value, shown in place rather than left blank.
 *
 * Blank reads as "no data" and a dash reads as "not loaded yet". Neither is
 * what happened, and the difference matters: someone deciding whether a column
 * is usable needs to know it exists and is simply too sparse to describe.
 */
function Withheld({ min, reason }) {
  return (
    <Pill
      tone="warn"
      className="cursor-help"
      // title, so the rule is one hover away rather than only in a doc.
      title={reason ?? `withheld: fewer than ${min} patients`}
    >
      &lt; {min}
    </Pill>
  );
}

function Row({ c, minCell }) {
  const small = c.patients_with_value == null;

  return (
    <tr>
      <Td>
        <Mono className="text-text">{c.code}</Mono>
        {c.name && c.name !== c.code && (
          <span className="ml-2 text-[11px] text-text-muted">{c.name}</span>
        )}
        {c.mixed_valtype && (
          <Pill tone="danger" className="ml-2" title="Some rows are numeric and some are text. The text ones become NaN in the frame, and the build does not mention it.">
            mixed types
          </Pill>
        )}
      </Td>
      <Td>
        <span className="text-[12px] text-text-3">{c.kind}</span>
        {c.integer_like && (
          <span className="ml-1.5 text-[10px] text-text-muted">int</span>
        )}
      </Td>
      <Td align="right">
        {small ? <Withheld min={minCell} reason={c.reason} />
               : <Num>{count(c.patients_with_value)}</Num>}
      </Td>
      <Td>
        {c.fill_rate == null ? (
          <span className="text-[11px] text-text-muted">—</span>
        ) : (
          <span className="flex items-center gap-2">
            <Meter
              value={c.fill_rate}
              tone={c.fill_rate < 0.4 ? "warn" : "positive"}
              className="w-[70px]"
            />
            <Num className="text-[11px] text-text-3">
              {Math.round(c.fill_rate * 100)}%
            </Num>
          </span>
        )}
      </Td>
      <Numeric v={c.low} />
      <Numeric v={c.p50} />
      <Numeric v={c.high} />
      <Td>
        {c.kind === "categorical" ? (
          <Levels c={c} minCell={minCell} />
        ) : c.low == null && !small ? (
          <Withheld min={minCell} reason={c.reason} />
        ) : (
          <span className="text-[11px] text-text-muted">
            {c.n_distinct == null ? "" : `${count(c.n_distinct)} distinct`}
          </span>
        )}
      </Td>
    </tr>
  );
}

function Numeric({ v }) {
  return (
    <Td align="right">
      {v == null ? (
        <span className="text-[11px] text-text-muted">—</span>
      ) : (
        <Num className="text-text-2">{score(v, Number.isInteger(v) ? 0 : 1)}</Num>
      )}
    </Td>
  );
}

function Levels({ c, minCell }) {
  if (c.levels.length === 0) {
    return (
      <span className="flex items-center gap-1.5">
        <Withheld
          min={minCell}
          reason="Only one level was large enough to show, and with a total published the rest would be arithmetic."
        />
      </span>
    );
  }
  return (
    <span className="flex flex-wrap gap-1">
      {c.levels.map((lv) => (
        <Pill key={lv.value} title={`${lv.count} patients`}>
          {lv.value}
        </Pill>
      ))}
      {c.other_count > 0 && (
        <Pill tone="warn" title={`${c.other_count} patients across levels too small to name`}>
          other {c.other_count}
        </Pill>
      )}
    </span>
  );
}
