import { useState } from "react";

import { apiPost } from "../lib/api.js";
import { buildOverrides } from "../lib/hyperparams.js";
import { CohortMultiPicker } from "./CohortPicker.jsx";
import ModelTypePicker from "./ModelTypePicker.jsx";
import PathPicker from "./PathPicker.jsx";
import Warning, { Warnings } from "./Warning.jsx";

const ADVANCED = [
  ["time_buffer", 0],
  ["sample_size_limit", 100000],
  ["test_size", 0.5],
  ["random_seed", 0.42],
];

/** A "model" is a concept whose blob holds the config. Defining one trains nothing. */
export default function ModelForm({ cohorts, tree, onCreated }) {
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

  const canSubmit = missing.length === 0 && !apostrophe && !busy;

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
    <div className="space-y-4">
      <div className="flex gap-2">
        <div>
          <label className="mb-1 block text-xs text-neutral-500">code</label>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="my_model"
            className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-sm"
          />
        </div>
        <div className="min-w-0 flex-1">
          <label className="mb-1 block text-xs text-neutral-500">
            description
          </label>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What this model predicts"
            className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-sm"
          />
        </div>
      </div>

      {path && <p className="text-xs text-neutral-500">path: {path}</p>}

      {apostrophe && (
        <p className="text-xs text-red-400">
          no apostrophes — the blob is stored single-quoted and repaired before
          parsing, so one apostrophe corrupts the whole config
        </p>
      )}

      <div>
        <label className="mb-1 block text-xs text-neutral-500">
          positive cohorts
        </label>
        <CohortMultiPicker
          cohorts={cohorts}
          values={positive}
          onChange={setPositive}
        />
      </div>
      <div>
        <label className="mb-1 block text-xs text-neutral-500">
          negative cohorts
        </label>
        <CohortMultiPicker
          cohorts={cohorts}
          values={negative}
          onChange={setNegative}
        />
      </div>

      {overlap.length > 0 && (
        <Warning>
          {overlap.join(", ")} is in both classes. Patients in both are dropped
          from <em>both</em>, not assigned to one.
        </Warning>
      )}

      <div className="space-y-3 border-t border-neutral-800 pt-4">
        <p className="text-xs text-neutral-500">
          Each selection is a prefix match over your loaded concepts — pick the
          subtree, not individual columns.
        </p>
        <PathPicker
          label="data paths (features)"
          tree={tree}
          values={dataPaths}
          onChange={setDataPaths}
          hint="The model's inputs. Usually one folder, e.g. /YourData/features"
        />
        <PathPicker
          label="label paths"
          tree={tree}
          values={labelPaths}
          onChange={setLabelPaths}
          hint="Where the outcome lives, e.g. /YourData/label — must not overlap the data paths"
        />
      </div>

      <div className="space-y-3 border-t border-neutral-800 pt-4">
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
          <ul className="space-y-0.5 text-xs text-red-400">
            {hyperErrors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <button
          onClick={() => setAdvanced((a) => !a)}
          className="text-xs text-neutral-500 hover:text-neutral-300"
        >
          {advanced ? "hide" : "show"} advanced
        </button>
        {advanced && (
          <div className="mt-2 flex flex-wrap gap-3">
            {ADVANCED.map(([key]) => (
              <div key={key}>
                <label className="mb-1 block text-xs text-neutral-500">
                  {key}
                </label>
                <input
                  type="number"
                  step="any"
                  value={opts[key]}
                  onChange={(e) =>
                    setOpts({ ...opts, [key]: Number(e.target.value) })
                  }
                  className="w-32 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm"
                />
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-1">
        <button
          onClick={submit}
          disabled={!canSubmit}
          className="rounded bg-sky-800 px-3 py-1.5 text-sm text-sky-50 hover:bg-sky-700 disabled:opacity-40"
        >
          {busy ? "saving…" : "Save model config"}
        </button>
        {missing.length > 0 && (
          <p className="text-xs text-amber-300/80">
            Still needed: {missing.join(", ")}. Nothing is saved — and step 4
            only lists models that have been.
          </p>
        )}
      </div>

      <Warnings items={warnings} />
      {error && (
        <p className="rounded border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
