import { PlotFigure, usePlots } from "../components/PlotsPanel.jsx";
import { Centre, LeftRail, RightRail } from "../layout/Shell.jsx";
import { count, plural, score, seconds } from "../lib/format.js";
import { clfMismatch } from "../lib/projects.js";
import { href, Link } from "../lib/router.jsx";
import { useWorkspace } from "../lib/workspace.jsx";
import PipelineRailStub from "../panels/PipelineRailStub.jsx";
import { Card, CardHeader } from "../ui/Card.jsx";
import Callout, { Empty, Failed, NotReported } from "../ui/Callout.jsx";
import { Pill, Status } from "../ui/Status.jsx";
import { KeyValue, KeyValueList } from "../ui/Table.jsx";
import { Heading, Mono, Note, Num, SectionLabel } from "../ui/Text.jsx";

export default function Model({ code }) {
  const ws = useWorkspace();
  const model = ws.models.find((m) => m.code === code) ?? null;
  const project = ws.projects.find((p) => p.models.some((m) => m.code === code)) ?? null;
  const metrics = ws.metrics[code]?.data ?? null;
  const metricsError = ws.metrics[code]?.error ?? null;
  const config = ws.configs[code]?.data ?? null;

  // Plots are a few hundred KB of base64 in the concept blob, so they are a
  // separate request made only by this page.
  const plots = usePlots(model?.is_built ? code : null, ws.version);

  if (!model) {
    return (
      <>
        <LeftRail width={258} />
        <Centre>
          <Empty>
            {ws.loading
              ? "Reading the warehouse…"
              : `No model with the code ${code}. It may have been wiped — models are concepts, so deleting concepts destroys them.`}
          </Empty>
        </Centre>
        <RightRail width={300} />
      </>
    );
  }

  const counts = metrics?.counts ?? {};
  const usedCohorts = cohortsUsed(ws.cohorts, config);

  return (
    <>
      <LeftRail width={258}>
        <PipelineRailStub project={project} active="model" model={model.code} />
      </LeftRail>

      <Centre>
        <div className="space-y-5">
          <div>
            <p className="mb-1.5 text-[12px] text-text-muted">
              {project && (
                <>
                  <Link to={href.project(project.id)} className="hover:text-text-2">
                    {project.name}
                  </Link>{" "}
                  /{" "}
                  <Link to={href.benchmark(project.id)} className="hover:text-text-2">
                    Benchmark
                  </Link>{" "}
                  /{" "}
                </>
              )}
              <Mono>{model.code}</Mono>
            </p>
            <div className="flex flex-wrap items-baseline gap-3">
              <Heading level={1} className="text-[22px] leading-tight">
                {metrics?.model_name ?? model.model_type ?? model.code}
              </Heading>
              {project?.best?.model.code === model.code && <Pill tone="positive">best</Pill>}
              {!model.is_built && <Status tone="idle">config only, never built</Status>}
            </div>
            {model.description && (
              <Note className="mt-2">{model.description}</Note>
            )}
          </div>

          {!model.is_built ? (
            <Callout tone="warn" title="nothing has been trained yet">
              This model exists as a config only. Metrics, curves and a confusion
              matrix appear once a build job completes — defining a model trains
              nothing.
            </Callout>
          ) : metricsError ? (
            <Failed what="this model's metrics" error={metricsError} />
          ) : !metrics ? (
            <Empty>Reading stored metrics…</Empty>
          ) : (
            <>
              <MetricStrip metrics={metrics} counts={counts} />

              <div className="grid gap-3.5 lg:grid-cols-2">
                <Card>
                  <SectionLabel className="mb-3">ROC curve</SectionLabel>
                  {plots.loading ? (
                    <Empty>Loading plots…</Empty>
                  ) : plots.error ? (
                    <Failed what="the diagnostic plots" error={plots.error} />
                  ) : plots.data?.images?.plot_roc ? (
                    <PlotFigure code={code} name="plot_roc" images={plots.data.images} />
                  ) : (
                    <Empty>
                      This build produced no ROC plot — it predates the plotting
                      patch, or matplotlib was unavailable when it ran. Rebuild to
                      get one.
                    </Empty>
                  )}
                </Card>

                <Card>
                  <SectionLabel className="mb-3">Decision curve</SectionLabel>
                  <NotReported label="net benefit against treat-all and treat-none">
                    The build produces ROC, precision–recall, calibration,
                    confusion-matrix and feature-importance plots. No net-benefit
                    curve is computed anywhere in the ETL container, so there is
                    nothing to render here.
                  </NotReported>
                  <Note className="mt-3">
                    The calibration plot below is the closest thing this build
                    stores: it shows whether the predicted probabilities mean
                    what they say, which is what a decision curve would depend
                    on.
                  </Note>
                </Card>
              </div>

              <div className="grid gap-3.5 lg:grid-cols-2">
                <ConfusionMatrix counts={counts} atHalf={plots.data?.counts_at_half} note={plots.data?.note} />
                <Card>
                  <SectionLabel className="mb-3">Performance by subgroup</SectionLabel>
                  <NotReported label="score by sex, age band or site">
                    One headline number can hide a model that works for some
                    patients and not others — but nothing stores per-subgroup
                    scores. The build records one set of metrics over the whole
                    held-out split, and no endpoint re-scores a slice of it.
                  </NotReported>
                </Card>
              </div>

              <OtherPlots code={code} plots={plots} />

              <Features metrics={metrics} />
            </>
          )}
        </div>
      </Centre>

      <RightRail width={300}>
        <Provenance model={model} metrics={metrics} config={config} />
        <Limitations
          model={model}
          metrics={metrics}
          counts={counts}
          usedCohorts={usedCohorts}
        />
        <Reproducibility usedCohorts={usedCohorts} config={config} />
      </RightRail>
    </>
  );
}

/**
 * Five tiles. Brier score is not among them because the build does not compute
 * one — the five here are all read from the stored blob.
 */
function MetricStrip({ metrics, counts }) {
  const t = metrics.thresholded ?? {};
  const tp = counts.true_positive;
  const fp = counts.false_positive;
  const tn = counts.true_negative;
  const fn = counts.false_negative;
  const total = [tp, fp, tn, fn].every((n) => typeof n === "number")
    ? tp + fp + tn + fn
    : null;

  const tiles = [
    {
      label: "roc auc",
      value: score(metrics.headline?.roc_auc),
      tone: "positive",
      sub: "no confidence interval is reported",
    },
    {
      label: "accuracy",
      value: score(t.accuracy),
      sub: total != null ? `${count(tp + tn)} of ${count(total)}` : null,
    },
    {
      label: "precision",
      value: score(t.precision),
      sub: typeof tp === "number" && typeof fp === "number"
        ? `${count(tp)} of ${count(tp + fp)} flagged`
        : null,
    },
    {
      label: "recall",
      value: score(t.recall),
      sub: typeof tp === "number" && typeof fn === "number"
        ? `${count(tp)} of ${count(tp + fn)} cases`
        : null,
    },
    {
      label: "f1",
      value: score(t.f1),
      sub: "the threshold every tile but roc auc uses",
    },
  ];

  return (
    <>
      <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-5">
        {tiles.map((tile) => (
          <Card key={tile.label} sunk className="p-4">
            <Num
              className={`block text-[26px] leading-none ${
                tile.tone === "positive" ? "text-positive" : "text-text"
              }`}
            >
              {tile.value}
            </Num>
            <SectionLabel className="mt-2">{tile.label}</SectionLabel>
            {tile.sub && (
              <p className="mt-1 text-[11px] leading-snug text-text-muted">{tile.sub}</p>
            )}
          </Card>
        ))}
      </div>
      <Note>{metrics.threshold_note}</Note>
    </>
  );
}

function ConfusionMatrix({ counts, atHalf, note }) {
  const cells = [
    { key: "true_negative", label: "true negative", tone: "text-text" },
    { key: "false_positive", label: "false positive", tone: "text-warn" },
    { key: "false_negative", label: "false negative", tone: "text-danger" },
    { key: "true_positive", label: "true positive", tone: "text-text" },
  ];

  const have = cells.some((c) => typeof counts[c.key] === "number");

  return (
    <Card>
      <SectionLabel className="mb-3">Confusion matrix</SectionLabel>

      {!have ? (
        <NotReported label="counts at the reported threshold">
          This build stored no confusion counts. Only builds made since the
          metrics patch record them.
        </NotReported>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2.5">
            {cells.map((c) => (
              <div
                key={c.key}
                className={`rounded-row border p-4 ${
                  c.key === "false_negative"
                    ? "border-danger-edge bg-danger-edge/30"
                    : "border-border-soft bg-panel-sunk"
                }`}
              >
                <Num className={`block text-[24px] leading-none ${c.tone}`}>
                  {count(counts[c.key])}
                </Num>
                <SectionLabel className="mt-2">{c.label}</SectionLabel>
              </div>
            ))}
          </div>

          {typeof counts.false_negative === "number" &&
            typeof counts.true_positive === "number" && (
              <Note className="mt-3">
                <Num className="text-text-2">{count(counts.false_negative)}</Num>{" "}
                missed {plural(counts.false_negative, "case")} out of{" "}
                <Num className="text-text-2">
                  {count(counts.false_negative + counts.true_positive)}
                </Num>{" "}
                positives, at the F1-optimal threshold.
              </Note>
            )}
        </>
      )}

      {/*
        The plots are drawn at the 0.5 cutoff the stored model predicts at, not
        at the F1-optimal threshold the metrics use. The backend keeps the two
        apart deliberately, so showing only one would misstate what the model
        does when it is actually applied.
      */}
      {atHalf && Object.keys(atHalf).length > 0 && (
        <div className="mt-4 border-t border-border-soft pt-4">
          <SectionLabel className="mb-2">At the 0.5 cutoff the model predicts at</SectionLabel>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-[12px]">
            {[
              ["tp", "true positive"],
              ["fp", "false positive"],
              ["tn", "true negative"],
              ["fn", "false negative"],
            ].map(([key, label]) => (
              <span key={key} className="text-text-3">
                {label} <Num className="text-text-2">{count(atHalf[key])}</Num>
              </span>
            ))}
          </div>
          {note && <Note className="mt-2">{note}</Note>}
        </div>
      )}
    </Card>
  );
}

const EXTRA_PLOTS = ["plot_pr", "plot_calibration", "plot_feature_importance", "plot_confusion_matrix"];

function OtherPlots({ code, plots }) {
  const images = plots.data?.images ?? {};
  const available = EXTRA_PLOTS.filter((name) => images[name]);
  if (!available.length) return null;

  return (
    <Card>
      <CardHeader
        title="Other diagnostic plots"
        hint="Drawn at build time and stored in the concept blob. Feature importance is absent for KNN, naive Bayes and the dummy baseline, which expose neither coefficients nor importances."
      />
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {available.map((name) => (
          <PlotFigure key={name} code={code} name={name} images={images} />
        ))}
      </div>
    </Card>
  );
}

function Features({ metrics }) {
  if (!metrics.features?.length) return null;

  return (
    <Card>
      <CardHeader
        title={
          <>
            <Num>{count(metrics.features.length)}</Num>{" "}
            {plural(metrics.features.length, "feature")} selected
          </>
        }
        hint="What survived feature selection inside the build pipeline, not everything the data paths offered."
      />
      <div className="mt-4 flex flex-wrap gap-2">
        {metrics.features.map((f) => (
          <Pill key={f}>{f}</Pill>
        ))}
      </div>
    </Card>
  );
}

function Provenance({ model, metrics, config }) {
  const hyper = Object.entries(metrics?.hyperparameters ?? {});

  return (
    <section>
      <SectionLabel className="mb-2.5">Provenance</SectionLabel>
      <KeyValueList>
        <KeyValue label="concept code" value={model.code} />
        <KeyValue label="path" value={model.path} />
        <KeyValue
          label="requested"
          value={metrics?.model_name ?? model.model_type ?? "not recorded"}
        />
        <KeyValue label="clf_type">
          {metrics?.clf_type ? (
            <Mono className={clfMismatch(metrics) ? "text-danger" : "text-text-2"}>
              {metrics.clf_type}
            </Mono>
          ) : (
            <span className="text-text-muted">not recorded</span>
          )}
        </KeyValue>
        <KeyValue
          label="positive set"
          value={(config?.positive_patient_set ?? []).join(", ") || "—"}
        />
        <KeyValue
          label="negative set"
          value={(config?.negative_patient_set ?? []).join(", ") || "—"}
        />
        <KeyValue
          label="features"
          value={
            metrics?.features?.length != null
              ? `${count(metrics.features.length)} concepts`
              : "—"
          }
        />
        <KeyValue label="test size" value={String(config?.test_size ?? "—")} />
        <KeyValue label="random seed" value={String(config?.random_seed ?? "—")} />
        <KeyValue label="fit time" value={seconds(metrics?.build_time_sec)} />
      </KeyValueList>

      {hyper.length > 0 && (
        <div className="mt-3">
          <SectionLabel className="mb-2">Hyperparameter overrides</SectionLabel>
          <div className="flex flex-wrap gap-1.5">
            {hyper.map(([k, v]) => (
              <Pill key={k}>
                {k.replace(/^clf__/, "")}={JSON.stringify(v).replace(/^\[|\]$/g, "")}
              </Pill>
            ))}
          </div>
        </div>
      )}

      <NotReported label="build timestamp" className="mt-3">
        Nothing records when a model was built. The blob stores how long the fit
        took but not when it ran, and the job row that ran it is not linked to
        the model.
      </NotReported>
    </section>
  );
}

function Limitations({ model, metrics, counts, usedCohorts }) {
  const items = [];

  if (typeof counts.n_samples === "number") {
    items.push(
      <>
        Trained on <Num className="text-text-2">{count(counts.n_samples)}</Num>{" "}
        patients
        {typeof counts.n_pos === "number" && typeof counts.n_neg === "number" && (
          <>
            {" "}
            (<Num className="text-text-2">{count(counts.n_pos)}</Num> positive,{" "}
            <Num className="text-text-2">{count(counts.n_neg)}</Num> negative)
          </>
        )}
        , from one source.
      </>,
    );
  }

  const mismatch = clfMismatch(metrics);
  if (mismatch) {
    items.push(
      <>
        Asked for <Mono className="text-text-2">{mismatch.expected}</Mono> and
        fitted <Mono className="text-danger">{mismatch.actual}</Mono>. The
        registry is not wired through — these numbers describe a different model.
      </>,
    );
  }

  if (metrics && !metrics.clf_type) {
    items.push(
      <>
        The estimator class was not recorded, so what actually trained cannot be
        confirmed from here.
      </>,
    );
  }

  if (model.features_present === false) {
    items.push(
      <>
        None of the features this model learned from still have facts. Applying
        it would score every patient off zero-filled columns.
      </>,
    );
  }

  const drifted = usedCohorts.filter((c) => c.stale);
  if (drifted.length) {
    items.push(
      <>
        <Mono className="text-text-2">{drifted.map((c) => c.name).join(", ")}</Mono>{" "}
        {plural(drifted.length, "has", "have")} drifted since training, so the
        set this model claims to have learned from no longer matches the one on
        record.
      </>,
    );
  }

  items.push(
    <>
      Not validated against any external cohort. Nothing in this system scores a
      model against data it did not come from.
    </>,
  );

  return (
    <Callout tone="warn" title="Known limitations">
      <ul className="space-y-2">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </Callout>
  );
}

/**
 * Whether re-running the definition today would select the same patients.
 *
 * Answerable, because the cohort list carries both the size recorded when the
 * set was built and the number of members that still have facts.
 */
function Reproducibility({ usedCohorts, config }) {
  if (!config) {
    return (
      <Callout tone="neutral" title="Reproducibility">
        This model&apos;s stored config could not be read, so there is no way to
        tell which patient sets it used.
      </Callout>
    );
  }

  if (!usedCohorts.length) {
    return (
      <Callout tone="danger" title="Reproducibility">
        The cohorts this model names no longer exist. Re-running its definition
        today would train on an empty set — which the engine does without
        erroring.
      </Callout>
    );
  }

  const unstable = usedCohorts.filter((c) => c.stale || c.duplicate);

  return unstable.length ? (
    <Callout tone="warn" title="Reproducibility">
      <Mono className="text-text-2">{unstable.map((c) => c.name).join(", ")}</Mono>{" "}
      {plural(unstable.length, "has", "have")} changed since this model was
      built. Re-running the definition today would select a different set of
      patients.
    </Callout>
  ) : (
    <Callout tone="positive" title="Reproducibility">
      All <Num className="text-text-2">{count(usedCohorts.length)}</Num> cohorts
      behind this model still match their recorded size. Re-running the
      definition today would select the same patients.
    </Callout>
  );
}

function cohortsUsed(cohorts, config) {
  const names = new Set([
    ...(config?.positive_patient_set ?? []),
    ...(config?.negative_patient_set ?? []),
  ]);
  return cohorts.filter((c) => names.has(c.name));
}
