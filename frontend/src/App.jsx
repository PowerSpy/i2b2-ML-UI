import { useCallback, useEffect, useState } from "react";

import CohortPicker from "./components/CohortPicker.jsx";
import CohortsPanel from "./components/CohortsPanel.jsx";
import DeleteButton from "./components/DeleteButton.jsx";
import FileLoader from "./components/FileLoader.jsx";
import Intro from "./components/Intro.jsx";
import JobRunner from "./components/JobRunner.jsx";
import MetricsPanel from "./components/MetricsPanel.jsx";
import ModelForm from "./components/ModelForm.jsx";
import PathPicker from "./components/PathPicker.jsx";
import PredictionsPanel from "./components/PredictionsPanel.jsx";
import StepCard from "./components/StepCard.jsx";
import VerifyPanel from "./components/VerifyPanel.jsx";
import WatcherBanner from "./components/WatcherBanner.jsx";
import { apiGet } from "./lib/api.js";

export default function App() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [watcherRunning, setWatcherRunning] = useState(false);

  const [concepts, setConcepts] = useState([]);
  const [tree, setTree] = useState([]);
  const [cohorts, setCohorts] = useState([]);
  const [models, setModels] = useState([]);
  const [loadError, setLoadError] = useState(null);

  // Bumped whenever something changed the warehouse, to re-pull everything.
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((n) => n + 1), []);

  const [selectedModel, setSelectedModel] = useState(null);
  const [targetCohort, setTargetCohort] = useState(null);
  const [eventPaths, setEventPaths] = useState([]);

  useEffect(() => {
    apiGet("/health").then(setHealth).catch((e) => setHealthError(e.message));
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([
      apiGet("/concepts"),
      apiGet("/concept-tree"),
      apiGet("/cohorts"),
      apiGet("/ml-concepts"),
    ])
      .then(([c, t, co, m]) => {
        if (!alive) return;
        setConcepts(c);
        setTree(t);
        setCohorts(co);
        setModels(m);
        setLoadError(null);
      })
      .catch((e) => alive && setLoadError(e.message));
    return () => {
      alive = false;
    };
  }, [version]);

  const model = models.find((m) => m.code === selectedModel) ?? null;

  // Apply reads prediction_event_paths from the job, not the blob, so seed it
  // from the model's own label_paths rather than making the user guess.
  useEffect(() => {
    if (!selectedModel) return;
    let alive = true;
    apiGet(`/ml-concepts/${selectedModel}/config`)
      .then((cfg) => alive && setEventPaths(cfg.label_paths ?? []))
      .catch(() => alive && setEventPaths([]));
    return () => {
      alive = false;
    };
  }, [selectedModel]);

  return (
    <main className="min-h-screen bg-neutral-950 p-8 text-neutral-100">
      <div className="mx-auto max-w-3xl space-y-6">
        <header className="flex items-baseline justify-between">
          <h1 className="text-2xl font-semibold">i2b2 ML UI</h1>
          <span className="text-xs text-neutral-500">
            backend:{" "}
            {healthError ? (
              <span className="text-red-400">{healthError}</span>
            ) : health ? (
              <span className="text-emerald-400">{health.status}</span>
            ) : (
              "checking…"
            )}
          </span>
        </header>

        <WatcherBanner onChange={setWatcherRunning} />
        <Intro />
        <VerifyPanel refreshKey={version} />

        {loadError && (
          <p className="rounded border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
            {loadError}
          </p>
        )}

        <StepCard
          n={1}
          title="Load data"
          hint="Two CSVs: concepts declare your columns, facts hold the values."
          done={concepts.length > 0}
          help={
            <>
              <p>
                <strong className="text-neutral-300">Concepts CSV</strong> —{" "}
                <code>type,path,code</code>. One row per column in your data,
                plus one per label. <code>path</code> is a tree position you
                invent, e.g. <code>/MyData/features/glucose</code>; the
                convention is a <code>features/</code> subtree and a separate{" "}
                <code>label/</code> subtree. <code>type</code> is{" "}
                <code>float</code> for numbers, <code>assertion</code> for
                labels.
              </p>
              <p>
                <strong className="text-neutral-300">Facts CSV</strong> —{" "}
                <code>mrn,code,value,start_date</code>. One row per patient per
                value — so a 500-patient, 30-column dataset becomes 15,000 rows.
                Assertion rows leave <code>value</code> blank.
              </p>
              <p className="text-amber-300/80">
                Filenames must end <code>concepts.csv</code> or{" "}
                <code>facts.csv</code>, lowercase. The loader globs by suffix; a
                name that doesn&apos;t match loads nothing and still reports
                success.
              </p>
            </>
          }
        >
          <div className="space-y-6">
            <FileLoader
              endpoint="/load-concepts"
              prompt="Drop a concepts CSV here, or click to browse"
              onLoaded={bump}
            />
            <FileLoader
              endpoint="/load-facts"
              prompt="Drop a facts CSV here, or click to browse"
              params={{ mrn_are_patient_numbers: true }}
              onLoaded={bump}
            />
          </div>
        </StepCard>

        <StepCard
          n={2}
          title="Cohorts"
          hint={`Named groups of patients. You usually need three. ${cohorts.length} so far.`}
          done={cohorts.length > 0}
          blocked={
            concepts.length === 0
              ? "Load concepts and facts first — a cohort is built from a concept code."
              : null
          }
          help={
            <>
              <p>
                A cohort is every patient who has a fact with the concept code
                you pick. The name is only a lookup label — the{" "}
                <strong className="text-neutral-300">code</strong> decides who is
                in it.
              </p>
              <p>
                For a classifier you normally build three: one from your positive
                label, one from your negative label, and one for the population
                you eventually want to score. Only the first two are used for
                training; the third is for step 5.
              </p>
              <p>
                <strong className="text-neutral-300">
                  Why bother, when the labels are already facts?
                </strong>{" "}
                The training engine only reads patient sets. It never looks at
                your label facts directly, so labelled data still needs a cohort
                per class.
              </p>
              <p>
                Pick an <code>assertion</code> concept, not a{" "}
                <code>float</code> one. A cohort from a measurement column means
                &ldquo;everyone who has that measurement&rdquo; — usually
                everybody, with no error.
              </p>
            </>
          }
        >
          <CohortsPanel
            cohorts={cohorts}
            concepts={concepts}
            onChange={bump}
          />
        </StepCard>

        <StepCard
          n={3}
          title="Define a model"
          hint="Say which concepts are inputs and which is the answer. Trains nothing."
          done={models.length > 0}
          blocked={
            cohorts.length === 0
              ? "Create at least one positive and one negative cohort first."
              : null
          }
          help={
            <>
              <p>
                A model here is just a concept whose config is stored alongside
                it. Saving costs nothing and trains nothing, so keep several.
              </p>
              <p>
                <strong className="text-neutral-300">Cohorts</strong> pick{" "}
                <em>which patients</em>.{" "}
                <strong className="text-neutral-300">Data paths</strong> and{" "}
                <strong className="text-neutral-300">label paths</strong> pick{" "}
                <em>which columns</em> — each one is a prefix match, so selecting{" "}
                <code>/MyData/features</code> grabs everything beneath it in one
                click.
              </p>
              <p>
                Keep the two disjoint: data paths are the inputs, label paths are
                the outcome. Nothing under <code>/ML</code> belongs in either —
                that is where models themselves live.
              </p>
              <p>
                Re-saving with an existing code replaces that model&apos;s
                trained weights with no history kept.
              </p>
            </>
          }
        >
          <ModelForm
            cohorts={cohorts}
            tree={tree}
            onCreated={(code) => {
              setSelectedModel(code);
              bump();
            }}
          />
        </StepCard>

        <StepCard
          n={4}
          title="Train"
          hint="Queues a background job. Expect a wait before anything moves."
          done={model?.is_built}
          blocked={
            models.length === 0 ? "Define a model config first." : null
          }
          help={
            <>
              <p>
                Submitting does not train — it adds a row to a queue and returns
                immediately. A separate worker polls that queue every ~10
                seconds, so <code>PENDING</code> for a few seconds is normal.
              </p>
              <p>
                <code>PENDING → PROCESSING → COMPLETED</code> is the happy path.
                If the banner at the top is red, the worker is stopped and the
                job will sit at <code>PENDING</code> forever.
              </p>
              <p>
                On <code>ERROR</code>, the stack trace shown here is the only
                place the reason exists. Note that Postgres reports{" "}
                <em>&ldquo;transaction is aborted&rdquo;</em> for every statement
                after a real failure, so the message often names an innocent
                query — the true cause is earlier.
              </p>
              <p>
                Training uses a fixed pipeline (scaling, SMOTE, feature
                selection, logistic regression with a grid search), so there are
                no algorithm choices to make.
              </p>
            </>
          }
        >
          <div className="space-y-4">
            <ModelPicker
              models={models}
              value={selectedModel}
              onChange={setSelectedModel}
            />
            {model && (
              <>
                <JobRunner
                  endpoint="/jobs/build"
                  body={{ path: model.path }}
                  label="Build model"
                  watcherRunning={watcherRunning}
                  onDone={bump}
                />
                {model.is_built && (
                  <div className="border-t border-neutral-800 pt-4">
                    <MetricsPanel code={model.code} refreshKey={version} />
                  </div>
                )}
              </>
            )}
          </div>
        </StepCard>

        <StepCard
          n={5}
          title="Apply"
          hint="Scores a cohort and writes predictions back as facts."
          blocked={
            !model?.is_built
              ? "Build a model first — applying an untrained one fails inside the job."
              : null
          }
          help={
            <>
              <p>
                Pick the population you want scored — normally the third cohort
                from step 2, not the positive or negative training sets. Scoring
                a model on the patients it learned from gives near-perfect
                numbers that mean nothing.
              </p>
              <p>
                <strong className="text-neutral-300">Only positives are saved.</strong>{" "}
                Predicted-negative patients have no fact written at all, so a
                missing prediction is indistinguishable from a patient who was
                never scored. Probabilities are not stored either — just the
                yes/no.
              </p>
              <p>
                Any feature the model expects but cannot find in the target data
                is filled with zero rather than raising an error, which quietly
                degrades the prediction. That case is flagged below if it
                happens.
              </p>
            </>
          }
        >
          {model?.is_built && (
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-xs text-neutral-500">
                  target cohort
                </label>
                <CohortPicker
                  cohorts={cohorts}
                  value={targetCohort}
                  onChange={setTargetCohort}
                />
              </div>
              <PathPicker
                label="prediction event paths"
                tree={tree}
                values={eventPaths}
                onChange={setEventPaths}
                hint="Anchors predictions in time. Defaults to the model's label paths; cannot be empty."
              />
              <JobRunner
                endpoint="/jobs/apply"
                body={{
                  path: model.path,
                  // A list, not a string: the engine iterates it, so a bare
                  // string is walked character by character and resolves to
                  // nothing (patient_set.py:21).
                  target_patient_set: targetCohort ? [targetCohort] : [],
                  prediction_event_paths: eventPaths,
                }}
                label="Apply model"
                disabled={!targetCohort || eventPaths.length === 0}
                watcherRunning={watcherRunning}
                onDone={bump}
              />
              <div className="border-t border-neutral-800 pt-4">
                <PredictionsPanel
                  code={model.code}
                  targetCohort={targetCohort}
                  refreshKey={version}
                />
              </div>
            </div>
          )}
        </StepCard>

        <details className="rounded-lg border border-red-950 p-4">
          <summary className="cursor-pointer text-sm text-red-400">
            Danger zone
          </summary>
          <div className="mt-4 space-y-3">
            <p className="text-xs text-neutral-500">
              These do not delete a dataset — the CLI ignores any path and
              truncates the warehouse tables wholesale.
            </p>
            <DeleteButton
              endpoint="/delete-concepts"
              label="wipe all concepts"
              target="concepts"
              onDeleted={bump}
            />
            <DeleteButton
              endpoint="/delete-facts"
              label="wipe all facts"
              target="facts"
              onDeleted={bump}
            />
            <p className="text-xs text-neutral-500">
              Cohorts survive both, and are wiped from step 2.
            </p>
          </div>
        </details>
      </div>
    </main>
  );
}

function ModelPicker({ models, value, onChange }) {
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-sm text-neutral-200"
    >
      <option value="">— pick a model —</option>
      {models.map((m) => (
        <option key={m.code} value={m.code}>
          {m.code} — {m.description ?? m.path}
          {m.is_built ? " (built)" : ""}
        </option>
      ))}
    </select>
  );
}
