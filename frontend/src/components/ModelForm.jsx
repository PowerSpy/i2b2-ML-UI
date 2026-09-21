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

/** A "model" is a concept whose blob holds the config. Defining one trains nothing. */
export default function ModelForm({ cohorts, tree, concepts = [], onCreated }) {
  const [code, setCode] = useState("");
  const [description, setDescription] = useState("");
  const [positive, setPositive] = useState([]);
  const [negative, setNegative] = useState([]);
  const [dataPaths, setDataPaths] = useState([]);
  const [labelPaths, setLabelPaths] = useState([]);
  const [advanced, setAdvanced] = useState(false);
  const [opts, setOpts] = useState(Object.fromEntries(ADVANCED));
  const [modelType, setModelType] = useState("logistic");
  const [hyperFields, setHyperFields] = useState([]);
  const [hyperValues, setHyperValues] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [hyperErrors, setHyperErrors] = useState([]);

  const path = code ? `/ML/Diagnosis/${code}` : "";
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
            className={`${FIELD} font-mono`}
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
        <Button variant="primary" onClick={submit} disabled={!canSubmit}>
          {busy ? "saving…" : "Save model config"}
        </Button>
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
