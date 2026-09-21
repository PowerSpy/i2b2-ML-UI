import CohortsPanel from "../components/CohortsPanel.jsx";
import CohortPicker from "../components/CohortPicker.jsx";
import FileLoader from "../components/FileLoader.jsx";
import JobRunner from "../components/JobRunner.jsx";
import ModelForm from "../components/ModelForm.jsx";
import PathPicker from "../components/PathPicker.jsx";
import PredictionsPanel from "../components/PredictionsPanel.jsx";
import { count, plural } from "../lib/format.js";
import { href, Link } from "../lib/router.jsx";
import { useWorkspace } from "../lib/workspace.jsx";
import { Card, CardHeader } from "../ui/Card.jsx";
import Callout, { Empty } from "../ui/Callout.jsx";
import { Mono, Note, Num, SectionLabel } from "../ui/Text.jsx";

const SELECT =
  "min-h-[44px] w-full rounded-btn border border-border-strong bg-panel-sunk px-3 font-mono text-[13px] text-text-2";

/**
 * What to show beside a model's code in a dropdown. The ETL defaults a
 * description to the code itself, so falling straight through to it prints
 * the code twice; the path is more use in that case.
 */
function subtitle(m) {
  return m.description && m.description !== m.code ? m.description : m.path;
}

/** Step 1. Two CSVs: concepts declare the columns, facts hold the values. */
export function LoadStep({ project }) {
  const ws = useWorkspace();

  return (
    <Card>
      <CardHeader
        title="1 · Load"
        hint="Concepts declare your columns; facts hold one row per patient per value."
      />

      <Callout tone="neutral" className="mt-4">
        Anything loaded under <Mono className="text-text-2">{project.root}</Mono>{" "}
        lands in this project. A concepts CSV with paths under a different root
        creates a different project — the root segment of the path is the only
        grouping the warehouse has.
      </Callout>

      <Callout tone="warn" title="the filename suffix decides everything" className="mt-3">
        Filenames must end <Mono>concepts.csv</Mono> or <Mono>facts.csv</Mono>,
        lowercase. The loader globs by suffix; a name that does not match loads
        nothing, logs its banner and exits 0. Each load below reports rows
        actually gained rather than exit status.
      </Callout>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <FileLoader
          endpoint="/load-concepts"
          prompt="Drop a concepts CSV here, or click to browse"
          onLoaded={ws.refresh}
        />
        <FileLoader
          endpoint="/load-facts"
          prompt="Drop a facts CSV here, or click to browse"
          params={{ mrn_are_patient_numbers: true }}
          onLoaded={ws.refresh}
        />
      </div>
    </Card>
  );
}

/** Step 2. Named patient sets — the only thing the training engine reads. */
export function CohortsStep() {
  const ws = useWorkspace();

  return (
    <Card>
      <CardHeader
        title="2 · Cohorts"
        hint="Named groups of patients. You usually need three: one per class for training, plus the population you want to score."
      />

      <Callout tone="neutral" className="mt-4">
        Patient sets carry no concept path, so these{" "}
        <Num>{count(ws.loading ? undefined : ws.cohorts.length)}</Num> are shared across
        every project.
        Only the positive and negative sets are used for training; the third is
        for the apply step.
      </Callout>

      <div className="mt-5">
        <CohortsPanel
          cohorts={ws.cohorts}
          concepts={ws.concepts}
          definitions={ws.cohortDefs}
          onChange={ws.refresh}
          loading={ws.loading}
        />
      </div>
    </Card>
  );
}

/** Step 3. Which concepts are inputs, which is the answer. Trains nothing. */
export function DefineStep({ project, onCreated, editingCode, onEdit }) {
  const ws = useWorkspace();
  const editingModel = project.models.find((m) => m.code === editingCode) ?? null;
  const editing = editingModel
    ? { model: editingModel, config: ws.configs[editingModel.code]?.data ?? null }
    : null;

  return (
    <Card>
      <CardHeader
        title="3 · Define"
        hint="Say which concepts are inputs and which is the outcome. Saving costs nothing and trains nothing, so keep several."
      />

      <Callout tone="neutral" className="mt-4">
        <strong className="text-text-2">Cohorts</strong> pick <em>which
        patients</em>. <strong className="text-text-2">Data paths</strong> and{" "}
        <strong className="text-text-2">label paths</strong> pick <em>which
        columns</em> — each one is a prefix match, so selecting{" "}
        <Mono>{project.root}/features</Mono> grabs everything beneath it in one
        click. The paths offered below are this project&apos;s subtree only.
        <br />
        <br />
        Re-saving with an existing code replaces that model&apos;s config and,
        once rebuilt, its trained weights. No history is kept.
      </Callout>

      {project.paths.length === 0 ? (
        <Empty className="mt-5">
          This subtree has no selectable path prefixes yet — a concept has to sit
          at least two levels deep for its parent to be pickable.
        </Empty>
      ) : (
        <div className="mt-5">
          <ModelForm
            // Remount on a change of target so the form's initial state is
            // re-derived; prefill lives in useState initialisers.
            key={editingCode ?? "new"}
            cohorts={ws.cohorts}
            tree={project.paths}
            concepts={project.concepts}
            editing={editing}
            onCancelEdit={() => onEdit?.(null)}
            // Models land under their project rather than one shared folder,
            // which is what let two studies collide in a flat namespace.
            pathPrefix={`/ML/${project.id}`}
            onCreated={(code) => {
              onCreated?.(code);
              ws.refresh();
            }}
          />

          {!editing && project.models.length > 0 && (
            <div className="mt-6 border-t border-border-soft pt-5">
              <SectionLabel className="mb-2.5">Edit an existing model</SectionLabel>
              <div className="flex flex-wrap gap-2">
                {project.models.map((m) => (
                  <button
                    key={m.code}
                    type="button"
                    onClick={() => onEdit?.(m.code)}
                    className="min-h-[44px] rounded-btn border border-border-strong px-3 font-mono text-[12px] text-text-3 hover:border-text-muted hover:text-text"
                  >
                    {m.code}
                  </button>
                ))}
              </div>
              <Note className="mt-2">
                Loads that model&apos;s stored config into the form above, so a
                one-field change does not mean retyping the rest.
              </Note>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/** Step 4. Queue a build. A background worker runs it, or does not. */
export function TrainStep({ project, selected, onSelect }) {
  const ws = useWorkspace();
  const model = project.models.find((m) => m.code === selected) ?? null;

  return (
    <Card>
      <CardHeader
        title="4 · Train"
        hint="Queues a background job and returns immediately. A separate worker polls that queue every ten seconds or so."
      />

      <Callout tone="neutral" className="mt-4">
        <Mono>PENDING → PROCESSING → COMPLETED</Mono> is the happy path. On{" "}
        <Mono>ERROR</Mono>, the stack trace on the job row is the only place the
        reason exists — and Postgres reports &ldquo;transaction is aborted&rdquo;
        for every statement after a real failure, so the message often names an
        innocent query. The true cause is earlier.
        <br />
        <br />
        The pipeline around the model is fixed — scaling, SMOTE, feature
        selection, then a grid search — but the classifier is whichever one was
        chosen in step 3.
      </Callout>

      <div className="mt-5 space-y-5">
        {project.models.length === 0 ? (
          <Empty>No model config in this project yet. Define one in step 3.</Empty>
        ) : (
          <>
            <div>
              <label className="mb-1.5 block text-[12px] text-text-3" htmlFor="train-model">
                model
              </label>
              <select
                id="train-model"
                value={selected ?? ""}
                onChange={(e) => onSelect(e.target.value || null)}
                className={SELECT}
              >
                <option value="">— pick a model —</option>
                {project.models.map((m) => (
                  <option key={m.code} value={m.code}>
                    {m.code}
                    {m.model_type ? ` [${m.model_type}]` : ""} —{" "}
                    {subtitle(m)}
                    {m.is_built ? " (built)" : ""}
                    {m.is_built && m.features_present === false
                      ? " — TRAINING DATA DELETED"
                      : ""}
                  </option>
                ))}
              </select>
            </div>

            {model && (
              <>
                <JobRunner
                  endpoint="/jobs/build"
                  body={{ path: model.path }}
                  label="Build model"
                  watcherRunning={!!ws.watcher?.running}
                  onDone={ws.refresh}
                />

                {model.is_built && (
                  <div className="border-t border-border-soft pt-5">
                    <Note>
                      This model is built. Its metrics, curves, confusion matrix
                      and provenance are on its own page — including whether the
                      estimator that was fitted matches the algorithm requested.
                    </Note>
                    <Link
                      to={href.model(model.code)}
                      className="mt-3 inline-flex min-h-[44px] items-center rounded-btn border border-border-strong px-4 text-[13px] text-text-2 hover:border-text-muted hover:text-text"
                    >
                      Open {model.code}
                    </Link>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

/** Step 5. Score a cohort; predictions come back as ordinary facts. */
export function ApplyStep({ project, selected, onSelect, targetCohort, onTarget, eventPaths, onEventPaths }) {
  const ws = useWorkspace();
  const model = project.models.find((m) => m.code === selected) ?? null;
  const built = project.models.filter((m) => m.is_built);

  const blocked = !model
    ? null
    : !model.is_built
      ? "This model has not been built. Applying an untrained one fails inside the job."
      : model.features_present === false
        ? "This model is trained, but none of the features it learned from still have facts — the data was deleted or reloaded since. Every prediction would come from zero-filled columns. Rebuild it first."
        : null;

  return (
    <Card>
      <CardHeader
        title="5 · Apply"
        hint="Scores a cohort and writes predictions back as facts."
      />

      <Callout tone="warn" title="only positives are saved" className="mt-4">
        Predicted-negative patients have no fact written at all, so a missing
        prediction is indistinguishable from a patient who was never scored.
        Probabilities are not stored either — just the yes/no. Any feature the
        model expects but cannot find is filled with zero rather than raising,
        which quietly degrades the prediction; that case is flagged below when it
        happens.
      </Callout>

      <div className="mt-5 space-y-5">
        {built.length === 0 ? (
          <Empty>
            No built model in this project. Train one in step 4 first — there is
            nothing to apply.
          </Empty>
        ) : (
          <>
            <div>
              <label className="mb-1.5 block text-[12px] text-text-3" htmlFor="apply-model">
                model
              </label>
              <select
                id="apply-model"
                value={selected ?? ""}
                onChange={(e) => onSelect(e.target.value || null)}
                className={SELECT}
              >
                <option value="">— pick a model —</option>
                {built.map((m) => (
                  <option key={m.code} value={m.code}>
                    {m.code} — {subtitle(m)}
                  </option>
                ))}
              </select>
            </div>

            {blocked && (
              <Callout tone="danger" title="cannot apply this model">
                {blocked}
              </Callout>
            )}

            {model?.is_built && !blocked && (
              <>
                <div>
                  <label className="mb-1.5 block text-[12px] text-text-3" htmlFor="apply-target">
                    target cohort
                  </label>
                  <CohortPicker
                    id="apply-target"
                    cohorts={ws.cohorts}
                    value={targetCohort}
                    onChange={onTarget}
                  />
                  <p className="mt-2 text-[12px] leading-relaxed text-text-muted">
                    Pick the population you want scored — normally a third
                    cohort, not the positive or negative training sets. Scoring a
                    model on the patients it learned from gives near-perfect
                    numbers that mean nothing.
                  </p>
                </div>

                <PathPicker
                  id="event-paths-label"
                  label="prediction event paths"
                  tree={project.paths}
                  values={eventPaths}
                  onChange={onEventPaths}
                  hint="Anchors predictions in time. Defaults to the model's own label paths; cannot be empty — the engine joins it into a WHERE clause with no fallback."
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
                  watcherRunning={!!ws.watcher?.running}
                  onDone={ws.refresh}
                />

                <div className="border-t border-border-soft pt-5">
                  <PredictionsPanel
                    code={model.code}
                    targetCohort={targetCohort}
                    refreshKey={ws.version}
                  />
                </div>
              </>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

/** Shared by the rail summaries, so the wording matches the panels. */
export function stepSummaries({ project, facts, cohorts, jobs }) {
  const built = project.models.filter((m) => m.is_built);
  const running = jobs.filter((j) => j.status === "PROCESSING").length;
  const queued = jobs.filter((j) => j.status === "PENDING").length;
  const drifted = cohorts.filter((c) => c.stale).length;

  return {
    load: `${count(project.concepts.length)} ${plural(project.concepts.length, "concept")}, ${count(facts)} facts warehouse-wide`,
    cohorts: cohorts.length
      ? `${count(cohorts.length)} named ${plural(cohorts.length, "set")}${drifted ? `, ${count(drifted)} drifted` : ", all live"}`
      : "no patient sets yet",
    define: project.models.length
      ? `${count(project.models.length)} model ${plural(project.models.length, "config")}`
      : "no model config yet",
    train: built.length
      ? `${count(built.length)} built${running ? `, ${count(running)} running` : ""}${queued ? `, ${count(queued)} queued` : ""}`
      : running || queued
        ? `${count(running)} running, ${count(queued)} queued`
        : "nothing built yet",
    // No endpoint aggregates prediction facts, and the job row does not record
    // which model it applied. Counting is per model, on demand.
    apply: built.length
      ? "prediction counts are per model, read on demand"
      : "nothing to apply yet",
  };
}
