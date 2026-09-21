import { useState } from "react";

import { apiPost } from "../lib/api.js";
import { buildOverrides } from "../lib/hyperparams.js";
import Button from "../ui/Button.jsx";
import Callout from "../ui/Callout.jsx";
import { Mono } from "../ui/Text.jsx";
import { CohortMultiPicker } from "./CohortPicker.jsx";
import ModelTypePicker from "./ModelTypePicker.jsx";
import PathPicker from "./PathPicker.jsx";

const ADVANCED = [
  ["time_buffer", 0],
  ["sample_size_limit", 100000],
  ["test_size", 0.5],
  ["random_seed", 0.42],
];

const FIELD =
  "min-h-[44px] w-full rounded-btn border border-border-strong bg-panel-sunk px-3 text-[13px] text-text placeholder:text-text-muted";

/**
 * Assertion concepts the data paths would pull in as features but the label
 * paths do not claim.
 *
 * Mirrors the check the backend enforces at save time, so the problem shows up
 * while the paths are being picked rather than on submit. The backend remains
 * authoritative — this is only here to shorten the feedback loop.
 */
function strayAssertions(concepts, dataPaths, labelPaths) {
  if (!dataPaths.length) return [];
  const under = (paths) => (c) =>
    paths.some((p) => c.path === p || c.path.startsWith(`${p}/`));

  return concepts
    .filter((c) => c.type === "assertion")
    .filter(under(dataPaths))
    .filter((c) => !under(labelPaths)(c))
    .map((c) => c.code);
}

/**
 * A "model" is a concept whose blob holds the config. Defining one trains
 * nothing.
 *
 * `editing` is an existing model plus its stored blob. Without it, changing
 * one hyperparameter meant retyping the code, description, both cohort sets,
 * both path sets and the algorithm from memory — and a re-save overwrites the
 * config outright, so a half-remembered form silently replaced the real one.
 *
 * `pathPrefix` is where the concept lands. It follows the project rather than
 * a hardcoded folder, so two studies do not share one flat namespace.
 */
export default function ModelForm({
  cohorts,
  tree,
  concepts = [],
  onCreated,
  onCancelEdit,
  editing = null,
  pathPrefix = "/ML/Diagnosis",
}) {
  const blob = editing?.config ?? null;
  const [code, setCode] = useState(editing?.model.code ?? "");
  const [description, setDescription] = useState(
    // The ETL defaults a description to the code; that is not worth carrying
    // back into the field as if the user had typed it.
    editing && editing.model.description !== editing.model.code
      ? (editing.model.description ?? "")
      : "",
  );
  const [positive, setPositive] = useState(blob?.positive_patient_set ?? []);
  const [negative, setNegative] = useState(blob?.negative_patient_set ?? []);
  const [dataPaths, setDataPaths] = useState(blob?.data_paths ?? []);
  const [labelPaths, setLabelPaths] = useState(blob?.label_paths ?? []);
  const [advanced, setAdvanced] = useState(false);
  const [opts, setOpts] = useState(() => {
    const base = Object.fromEntries(ADVANCED);
    if (!blob) return base;
    for (const key of Object.keys(base)) {
      if (typeof blob[key] === "number") base[key] = blob[key];
    }
    return base;
  });
  const [modelType, setModelType] = useState(blob?.model_type ?? "logistic");
  const [hyperFields, setHyperFields] = useState([]);
  const [hyperValues, setHyperValues] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [hyperErrors, setHyperErrors] = useState([]);

  // An edit keeps the concept where it already is; moving it would create a
  // second model rather than change this one.
  const path = editing ? editing.model.path : code ? `${pathPrefix}/${code}` : "";
  const apostrophe = description.includes("'");
  const overlap = positive.filter((p) => negative.includes(p));

  // Named so the button can say what it is still waiting for. A disabled
  // button on a form long enough to scroll is otherwise silent: the fields
  // holding it back are off-screen above the button you are clicking.
  const missing = [
    !code && "code",
    !description && "description",
    !positive.length && "at least one positive cohort",
    !negative.length && "at least one negative cohort",
    !dataPaths.length && "at least one data path",
  ].filter(Boolean);

  const stray = strayAssertions(concepts, dataPaths, labelPaths);

  const canSubmit = missing.length === 0 && !apostrophe && stray.length === 0 && !busy;

  async function submit() {
    const hyper = buildOverrides(modelType, hyperFields, hyperValues);
    if (!hyper.ok) {
      setHyperErrors(hyper.errors);
      return;
    }
    setHyperErrors([]);
    setBusy(true);
    setError(null);
    setWarnings([]);
    try {
      const res = await apiPost("/ml-concepts", {
        code,
        path,
        description,
        blob: {
          positive_patient_set: positive,
          negative_patient_set: negative,
          data_paths: dataPaths,
          label_paths: labelPaths,
          model_type: modelType,
          hyperparameters: hyper.overrides,
          ...opts,
        },
      });
      setWarnings(res.warnings ?? []);
      onCreated?.(res.code);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      {editing && (
        <Callout tone="warn" title="this replaces the saved config">
          Saving overwrites <Mono className="text-text-2">{code}</Mono>&apos;s
          stored config, and its trained weights once it is rebuilt. No history
          is kept, and the model stays marked built against the old weights
          until then.
        </Callout>
      )}

      <div className="flex flex-wrap gap-3">
        <div className="w-52">
          <label className="mb-1.5 block text-[12px] text-text-3" htmlFor="model-code">
            code
          </label>
          <input
            id="model-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="my_model"
            readOnly={!!editing}
            title={editing ? "The code identifies the concept and cannot change in an edit" : undefined}
            className={`${FIELD} font-mono ${editing ? "text-text-3" : ""}`}
          />
        </div>
        <div className="min-w-0 flex-1">
          <label className="mb-1.5 block text-[12px] text-text-3" htmlFor="model-desc">
            description
          </label>
          <input
            id="model-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What this model predicts"
            className={FIELD}
          />
        </div>
      </div>

      {path && (
        <p className="text-[12px] text-text-muted">
          path: <Mono className="text-text-3">{path}</Mono>
        </p>
      )}

      {apostrophe && (
        <Callout tone="danger" title="no apostrophes">
          The blob is stored single-quoted and repaired before parsing, so one
          apostrophe corrupts the whole config.
        </Callout>
      )}

      <div>
        <p className="mb-1.5 text-[12px] text-text-3" id="positive-label">
          positive cohorts
        </p>
        <CohortMultiPicker
          labelledBy="positive-label"
          cohorts={cohorts}
          values={positive}
          onChange={setPositive}
        />
      </div>
      <div>
        <p className="mb-1.5 text-[12px] text-text-3" id="negative-label">
          negative cohorts
        </p>
        <CohortMultiPicker
          labelledBy="negative-label"
          cohorts={cohorts}
          values={negative}
          onChange={setNegative}
        />
      </div>

      {overlap.length > 0 && (
        <Callout tone="warn" title="cohort in both classes">
          <Mono className="text-text-2">{overlap.join(", ")}</Mono> is in both
          classes. Patients in both are dropped from <em>both</em>, not assigned
          to one.
        </Callout>
      )}

      <div className="space-y-4 border-t border-border-soft pt-5">
        <p className="text-[12px] leading-relaxed text-text-muted">
          Each selection is a prefix match over your loaded concepts — pick the
          subtree, not individual columns.
        </p>
        <PathPicker
          id="data-paths-label"
          label="data paths (features)"
          tree={tree}
          values={dataPaths}
          onChange={setDataPaths}
          hint="The model's inputs. Usually one folder, e.g. /YourData/features"
        />
        <PathPicker
          id="label-paths-label"
          label="label paths"
          tree={tree}
          values={labelPaths}
          onChange={setLabelPaths}
          hint="Where the outcome lives, e.g. /YourData/label. A data path may contain it, as long as the label paths claim every outcome concept inside."
        />

        {stray.length > 0 && (
          <Callout tone="warn" title="outcome concept fed in as a feature">
            <Mono className="text-text-2">{stray.join(", ")}</Mono>{" "}
            {stray.length === 1 ? "is an outcome concept" : "are outcome concepts"}{" "}
            your data paths would feed in as{" "}
            {stray.length === 1 ? "a feature" : "features"}. Assertions carry no
            value, so the build runs for a while and then fails with an error
            that names neither the concept nor the path. Either narrow the data
            paths, or add {stray.length === 1 ? "its" : "their"} folder to the
            label paths.
          </Callout>
        )}
      </div>

      <div className="space-y-3 border-t border-border-soft pt-5">
        <ModelTypePicker
          initialOverrides={blob?.hyperparameters ?? null}
          value={modelType}
          onChange={(key, fields) => {
            setModelType(key);
            setHyperFields(fields);
            setHyperErrors([]);
          }}
          values={hyperValues}
          onValuesChange={setHyperValues}
        />
        {hyperErrors.length > 0 && (
          <ul className="space-y-1 text-[12px] text-danger">
            {hyperErrors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <Button variant="quiet" className="px-0" onClick={() => setAdvanced((a) => !a)}>
          {advanced ? "hide" : "show"} advanced
        </Button>
        {advanced && (
          <div className="mt-2 flex flex-wrap gap-3">
            {ADVANCED.map(([key]) => (
              <div key={key}>
                <label className="mb-1.5 block text-[12px] text-text-3" htmlFor={`adv-${key}`}>
                  <Mono>{key}</Mono>
                </label>
                <input
                  id={`adv-${key}`}
                  type="number"
                  step="any"
                  value={opts[key]}
                  onChange={(e) => setOpts({ ...opts, [key]: Number(e.target.value) })}
                  className={`${FIELD} w-40 font-mono tabular-nums`}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={submit} disabled={!canSubmit}>
            {busy ? "saving…" : editing ? `Save changes to ${code}` : "Save model config"}
          </Button>
          {editing && <Button onClick={onCancelEdit}>cancel</Button>}
        </div>
        {missing.length > 0 && (
          <p className="text-[12px] text-warn">
            Still needed: {missing.join(", ")}. Nothing is saved — and the train
            step only lists models that have been.
          </p>
        )}
      </div>

      {warnings.map((w) => (
        <Callout key={w} tone="warn" title="saved, with a caveat">
          {w}
        </Callout>
      ))}
      {error && (
        <Callout tone="danger" title="save rejected">
          {error}
        </Callout>
      )}
    </div>
  );
}
