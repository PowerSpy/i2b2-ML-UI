# Reference copies — not installed

Unmodified container files, mirrored here for reading. **Nothing in this
directory is copied into the container.** `apply.sh` installs an explicit
three-file list; these are not on it, and adding one here does not install it.

They are here because `docker-changes/README.md` sets the standard that
"without a copy in the repo there is no record of what the running container
actually contains" — and the files the ML path depends on most were the ones
missing.

| File | Why it matters |
|---|---|
| `i2b2_cdi/ML/build_model_ML_helper.py` | All the SQL (`get_dataframes`, the temp-table chain), `make_pipeline` — which every entry in `model_registry.py` calls — and both blob read/write functions |
| `i2b2_cdi/ML/mlHelper.py` | Metrics at the F1-optimal threshold, model pickling, `format_data_paths`, `load_pred_facts` |
| `i2b2_cdi/ML/mlEngine.py` | The 26-line shim the job watcher dispatches into |
| `i2b2_cdi/job/jobWatcher.py` | Polls `job` for PENDING rows every 10s |
| `i2b2_cdi/job/jobOrchestrator.py` | Engine dispatch, and `delete_facts` — which runs before **every** ML job, builds included |
| `i2b2_cdi/job/BaseEngine.py` | Reads the job row and the concept blob |

## Two behaviours worth knowing, both documented in the files above

**The blob has two encodings.** A newly created model is written through
`csv.writer` as a Python **repr** (single quotes). A re-saved one goes through
`PUT /etl/concepts` as a query parameter, written verbatim — real **JSON**
(double quotes). Same column, same code, different syntax. The container's
reader (`BaseEngine.py`, `build_model_ML_helper.py`) applies
`blob.replace("'", '"')` unconditionally: a *repair* on the first, *damage* on
the second. This is why `app/core/ml_blob.py` tries `json.loads`, then
`ast.literal_eval`, then the quote swap, in that order.

**`update_concept_blob` merges rather than replaces**, so any key the app adds
to a blob survives a build untouched — you only need a reader.

## Refreshing these

They came out of the container with `docker cp`, which works on a stopped
container:

```bash
docker cp i2b2-etl:/usr/src/app/i2b2_cdi/ML/build_model_ML_helper.py - | tar -xO \
  > docker-changes/reference/i2b2_cdi/ML/build_model_ML_helper.py
```

`/usr/src/app/.git` also exists inside the container, so a stock upstream
version can be recovered from there without pulling the image again.
