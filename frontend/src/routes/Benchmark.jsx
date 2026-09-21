import { useMemo } from "react";

import { Centre, LeftRail, RightRail } from "../layout/Shell.jsx";
import { downloadCsv } from "../lib/csv.js";
import { count, score, seconds } from "../lib/format.js";
import { clfMismatch, findProject, leaderboard } from "../lib/projects.js";
import { href, Link } from "../lib/router.jsx";
import { useWorkspace } from "../lib/workspace.jsx";
import PipelineRailStub from "../panels/PipelineRailStub.jsx";
import Button from "../ui/Button.jsx";
import { Card, CardHeader } from "../ui/Card.jsx";
import Callout, { Empty, NotReported } from "../ui/Callout.jsx";
import Meter from "../ui/Meter.jsx";
import { Pill } from "../ui/Status.jsx";
import { KeyValue, KeyValueList, Table, Td, Th, ThHidden } from "../ui/Table.jsx";
import { Heading, Mono, Note, Num, SectionLabel } from "../ui/Text.jsx";

export default function Benchmark({ id }) {
  const ws = useWorkspace();
  const project = findProject(ws.projects, id);

  const rows = useMemo(
    () => (project ? leaderboard(project.models.filter((m) => m.is_built), ws.metrics) : []),
    [project, ws.metrics],
  );

  if (!project) {
    return (
      <>
        <LeftRail width={258} />
        <Centre>
          <Empty>
            {ws.loading ? "Reading the warehouse…" : "No project matches this path."}
          </Empty>
        </Centre>
        <RightRail width={300} />
      </>
    );
  }

  const split = splitAgreement(rows, ws.configs);

  return (
    <>
      <LeftRail width={258}>
        <PipelineRailStub project={project} active="benchmark" />
      </LeftRail>

      <Centre>
        <div className="space-y-5">
          <div className="flex items-start justify-between gap-6">
            <div className="max-w-2xl">
              <p className="mb-1.5 text-[12px] text-text-muted">
                <Link to={href.project(project.id)} className="hover:text-text-2">
                  {project.name}
                </Link>{" "}
                / Benchmark
              </p>
              <Heading level={1} className="text-[22px] leading-tight">
                {count(rows.length)} built {rows.length === 1 ? "model" : "models"}, ranked
              </Heading>
              <Note className="mt-2">
                Every row is read from the metrics that model stored at build
                time. The <Mono>clf_type</Mono> column is the estimator class
                that was really fitted — a miswired registry falls back to
                logistic regression without erroring, so the algorithm asked for
                is not evidence of what ran.
              </Note>
            </div>
            {rows.length > 0 && (
              <Button className="shrink-0" onClick={() => exportCsv(project, rows)}>
                export table
              </Button>
            )}
          </div>

          {rows.length === 0 ? (
            <Empty>
              No built model in this project. Train one and it appears here.
            </Empty>
          ) : (
            <>
              <Card>
                <Table>
                  <thead>
                    <tr>
                      <Th className="w-8">#</Th>
                      <Th>algorithm</Th>
                      <Th>clf_type</Th>
                      <Th align="right">roc auc</Th>
                      <ThHidden className="w-[120px]">roc auc, as a bar</ThHidden>
                      <Th align="right">f1</Th>
                      <Th align="right">recall</Th>
                      <Th align="right">fit time</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => {
                      const auc = row.metrics.headline?.roc_auc;
                      const mismatch = clfMismatch(row.metrics);
                      return (
                        <tr key={row.model.code}>
                          <Td>
                            <Num className="text-text-muted">{i + 1}</Num>
                          </Td>
                          <Td>
                            <Link
                              to={href.model(row.model.code)}
                              className="hover:underline"
                            >
                              <span className={i === 0 ? "text-text" : "text-text-2"}>
                                {row.metrics.model_name ??
                                  row.model.model_type ??
                                  "not recorded"}
                              </span>
                              <Mono className="ml-2 text-[11px] text-text-muted">
                                {row.model.code}
                              </Mono>
                            </Link>
                          </Td>
                          <Td>
                            {row.metrics.clf_type ? (
                              <Mono
                                className={`text-[12px] ${mismatch ? "text-danger" : "text-text-3"}`}
                              >
                                {row.metrics.clf_type}
                              </Mono>
                            ) : (
                              <span className="text-[12px] text-text-muted">
                                not recorded
                              </span>
                            )}
                          </Td>
                          <Td align="right">
                            <Num className={i === 0 ? "text-positive" : "text-text"}>
                              {score(auc)}
                            </Num>
                          </Td>
                          <Td>
                            <Meter value={auc} tone={i === 0 ? "positive" : "neutral"} />
                          </Td>
                          <Td align="right">
                            <Num className="text-text-2">
                              {score(row.metrics.thresholded?.f1)}
                            </Num>
                          </Td>
                          <Td align="right">
                            <Num className="text-text-2">
                              {score(row.metrics.thresholded?.recall)}
                            </Num>
                          </Td>
                          <Td align="right">
                            <Num className="text-text-3">
                              {seconds(row.metrics.build_time_sec)}
                            </Num>
                          </Td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>

                <Note className="mt-4">
                  f1 and recall are reported at the F1-optimal threshold; the
                  stored model predicts at 0.5. ROC AUC is threshold-free, which
                  is why the ranking uses it.
                </Note>
              </Card>

              <div className="grid gap-3.5 lg:grid-cols-2">
                <BaselineCheck rows={rows} />
                <LeakageCheck rows={rows} />
              </div>

              {!split.agree && (
                <Callout tone="danger" title="not one split">
                  {split.reason} The ranking therefore reflects the sample as
                  much as the algorithm. Rebuild the models against the same
                  cohorts, paths and seed before reading anything into the order.
                </Callout>
              )}
            </>
          )}
        </div>
      </Centre>

      <RightRail width={300}>
        <RunConfiguration rows={rows} split={split} />
        <Registry />
        <Callout tone="neutral" title="ranking is not a verdict">
          A 0.03 AUC gap on a few hundred patients is inside the noise. Open any
          model to see its confusion matrix and the flags on its cohorts before
          choosing one.
        </Callout>
      </RightRail>
    </>
  );
}

/**
 * A dummy classifier should land at 0.50. If it comes out high, the split or
 * the label is wrong and every row above it is meaningless — which is exactly
 * the failure this system will not report on its own.
 */
function BaselineCheck({ rows }) {
  const dummy = rows.find(
    (r) => r.metrics.clf_type === "DummyClassifier" || r.metrics.model_name === "DummyBaseline",
  );

  if (!dummy) {
    return (
      <Callout tone="warn" title="no baseline in this project">
        None of these models is a dummy classifier. Without one at 0.50, nothing
        here rules out a broken split or a leaked label — every number above
        would look the same either way.
      </Callout>
    );
  }

  const auc = dummy.metrics.headline?.roc_auc;
  const ok = typeof auc === "number" && auc >= 0.4 && auc <= 0.6;

  return ok ? (
    <Callout tone="positive" title="baseline check passed">
      <Mono className="text-text-2">{dummy.model.code}</Mono> landed at{" "}
      <Num className="text-text-2">{score(auc)}</Num> ROC AUC, which is what a
      coin flip should score.
    </Callout>
  ) : (
    <Callout tone="danger" title="baseline check failed">
      <Mono className="text-text-2">{dummy.model.code}</Mono> is a dummy
      classifier and scored <Num className="text-text-2">{score(auc)}</Num>{" "}
      rather than about 0.50. The split or the label is wrong, and every row
      above it is meaningless.
    </Callout>
  );
}

const LEAKAGE_AUC = 0.98;

function LeakageCheck({ rows }) {
  const suspicious = rows.filter(
    (r) => (r.metrics.headline?.roc_auc ?? 0) >= LEAKAGE_AUC,
  );

  if (!suspicious.length) {
    return (
      <Callout tone="neutral" title="no model above 0.98">
        Nothing here scores high enough to suggest a feature recorded after the
        outcome. Per-feature scores are not available — no endpoint trains on
        one feature at a time, so a single strong predictor cannot be isolated
        from this page.
      </Callout>
    );
  }

  return (
    <Callout tone="warn" title="one model explains too much">
      <Mono className="text-text-2">
        {suspicious.map((r) => r.model.code).join(", ")}
      </Mono>{" "}
      reaches {score(suspicious[0].metrics.headline.roc_auc)} ROC AUC. On
      clinical data that usually means a feature recorded after the diagnosis
      rather than before it.
    </Callout>
  );
}

/**
 * The shared run configuration — if there is one.
 *
 * Models here are built one at a time, each with its own stored blob, so "the
 * split" is an assumption rather than a fact. This reads every model's config
 * and says plainly whether they actually agree.
 */
function RunConfiguration({ rows, split }) {
  const top = rows[0];
  const config = top ? split.config : null;

  return (
    <section>
      <SectionLabel className="mb-2.5">Run configuration</SectionLabel>

      {!config ? (
        <Empty>No built model to read a configuration from.</Empty>
      ) : (
        <>
          <KeyValueList>
            <KeyValue
              label="positive set"
              value={(config.positive_patient_set ?? []).join(", ") || "—"}
            />
            <KeyValue
              label="negative set"
              value={(config.negative_patient_set ?? []).join(", ") || "—"}
            />
            <KeyValue
              label="features"
              value={(config.data_paths ?? []).join(", ") || "—"}
            />
            <KeyValue
              label="label"
              value={(config.label_paths ?? []).join(", ") || "—"}
            />
            <KeyValue label="test size" value={String(config.test_size ?? "—")} />
            <KeyValue label="random seed" value={String(config.random_seed ?? "—")} />
          </KeyValueList>

          <p className="mt-2.5 text-[11px] leading-relaxed text-text-muted">
            {split.agree
              ? `Read from every model's stored blob — all ${rows.length} agree on cohorts, paths, test size and seed.`
              : "Read from the top-ranked model's blob. The others disagree, so this describes one row rather than the run."}
          </p>

          <NotReported label="patient counts per set" className="mt-3">
            The blob stores cohort names, not the sizes used at training time.
            Current live sizes are on the cohorts table, but a cohort can have
            drifted since the model was built.
          </NotReported>
        </>
      )}
    </section>
  );
}

function Registry() {
  const { modelTypes, modelTypesResult } = useWorkspace();

  return (
    <section>
      <SectionLabel className="mb-2.5">Registry</SectionLabel>
      {modelTypesResult?.error ? (
        <Callout tone="warn" title="registry unreadable">
          {modelTypesResult.error}
        </Callout>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {modelTypes.map((t) => (
              <Pill key={t.key}>{t.key}</Pill>
            ))}
          </div>
          <p className="mt-2.5 text-[11px] leading-relaxed text-text-muted">
            Read from <Mono>MODEL_REGISTRY</Mono> inside the ETL container at
            request time, so a newly installed algorithm appears here without
            touching this page. Being in this list is not the same as having been
            built — only the table on the left has been.
          </p>
        </>
      )}
    </section>
  );
}

/** Do these models actually share a split? */
const SPLIT_KEYS = [
  ["positive_patient_set", "positive cohorts"],
  ["negative_patient_set", "negative cohorts"],
  ["data_paths", "feature paths"],
  ["label_paths", "label paths"],
  ["test_size", "test size"],
  ["random_seed", "random seed"],
];

function splitAgreement(rows, configs) {
  const first = rows.length ? configs[rows[0].model.code]?.data : null;
  if (!first || rows.length < 2) return { agree: true, config: first ?? null };

  const differing = [];
  for (const [key, label] of SPLIT_KEYS) {
    const baseline = JSON.stringify(first[key] ?? null);
    const varies = rows
      .slice(1)
      .some((r) => JSON.stringify(configs[r.model.code]?.data?.[key] ?? null) !== baseline);
    if (varies) differing.push(label);
  }

  return differing.length
    ? {
        agree: false,
        config: first,
        reason: `These models do not share the same ${differing.join(", ")}.`,
      }
    : { agree: true, config: first };
}

/** Client-side CSV of exactly the rows on screen. No endpoint is involved. */
function exportCsv(project, rows) {
  downloadCsv(
    `${project.id}_benchmark.csv`,
    ["rank", "code", "algorithm", "clf_type", "roc_auc", "f1", "recall", "build_time_sec"],
    rows.map((r, i) => [
      i + 1,
      r.model.code,
      r.metrics.model_name ?? r.model.model_type ?? "",
      r.metrics.clf_type ?? "",
      r.metrics.headline?.roc_auc ?? "",
      r.metrics.thresholded?.f1 ?? "",
      r.metrics.thresholded?.recall ?? "",
      r.metrics.build_time_sec ?? "",
    ]),
  );
}
