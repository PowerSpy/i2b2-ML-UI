import { useEffect, useState } from "react";

import DeleteButton from "./components/DeleteButton.jsx";
import FileLoader from "./components/FileLoader.jsx";
import VerifyPanel from "./components/VerifyPanel.jsx";
import { apiGet } from "./lib/api.js";

export default function App() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);
  const [mrnArePatientNumbers, setMrnArePatientNumbers] = useState(true);
  // Bumped after a successful load so VerifyPanel re-queries.
  const [loaded, setLoaded] = useState(0);

  useEffect(() => {
    apiGet("/health").then(setHealth).catch((e) => setError(e.message));
  }, []);

  const onLoaded = () => setLoaded((n) => n + 1);

  return (
    <main className="min-h-screen bg-neutral-950 p-8 text-neutral-100">
      <div className="mx-auto max-w-2xl space-y-8">
        <header className="flex items-baseline justify-between">
          <h1 className="text-2xl font-semibold">i2b2 ML UI</h1>
          <span className="text-xs text-neutral-500">
            backend:{" "}
            {error ? (
              <span className="text-red-400">{error}</span>
            ) : health ? (
              <span className="text-emerald-400">{health.status}</span>
            ) : (
              "checking…"
            )}
          </span>
        </header>

        <VerifyPanel refreshKey={loaded} />

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium text-neutral-400">
              Load concepts
            </h2>
            <DeleteButton
              endpoint="/delete-concepts"
              label="delete concepts"
              target="concepts"
              onDeleted={onLoaded}
            />
          </div>
          <FileLoader
            endpoint="/load-concepts"
            prompt="Drop a concepts CSV here, or click to browse"
            onLoaded={onLoaded}
          />
        </div>

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium text-neutral-400">Load facts</h2>
            <DeleteButton
              endpoint="/delete-facts"
              label="delete facts"
              target="facts"
              onDeleted={onLoaded}
            />
          </div>
          <FileLoader
            endpoint="/load-facts"
            prompt="Drop a facts CSV here, or click to browse"
            params={{ mrn_are_patient_numbers: mrnArePatientNumbers }}
            onLoaded={onLoaded}
          >
            <label className="flex items-center gap-2 text-sm text-neutral-300">
              <input
                type="checkbox"
                checked={mrnArePatientNumbers}
                onChange={(e) => setMrnArePatientNumbers(e.target.checked)}
                className="accent-sky-500"
              />
              MRNs are patient numbers
            </label>
          </FileLoader>
        </div>
      </div>
    </main>
  );
}
