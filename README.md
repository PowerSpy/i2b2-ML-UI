# i2b2 ML UI

A small web UI over the [i2b2](https://www.i2b2.org/) CDI loader. The i2b2 ETL
tooling is a CLI that runs inside a Docker container; this wraps the parts you
actually use day to day — loading concepts and facts from CSV, checking what
landed in the database, and clearing it out — behind a FastAPI backend and a
React frontend.

## How it works

The backend does not talk to i2b2 over a network API. It shells out to
`docker exec` against the running i2b2 containers:

- **Loads** stage the uploaded CSV on the host, `docker cp` it into the ETL
  container, and run `python -m i2b2_cdi <concept|fact> load` there.
- **Counts** run `psql` inside the Postgres container.
- **Deletes** run `python -m i2b2_cdi <concept|fact> delete` in the ETL container.

All of this goes through [`app/core/docker_exec.py`](app/core/docker_exec.py),
which wraps `subprocess.run(["docker", "exec", ...])` and returns the return
code, stdout, and stderr. Every loader response hands that output straight to the
UI, because the CLI's own logging is usually the only way to tell what happened.

```
frontend (Vite, :5173)  ──/api──▶  FastAPI (:8003)  ──docker exec──▶  i2b2-etl
                                          └─────────docker exec──────▶  i2b2-pg
```

## Requirements

- Python 3.11+
- Node 18+
- Docker, with the i2b2 stack running (`i2b2-etl` and `i2b2-pg` containers)

## Before the app will work

Three things live outside this repo's Python and JS, and none of them are
optional. All are covered in [`docker-changes/README.md`](docker-changes/README.md).

**1. Install the container-side code.** Model selection, diagnostic plots and
the validation fixes live inside `i2b2-etl`. It has no bind mounts, so they sit
in its writable layer: they survive `docker restart` and are lost on
`docker rm`.

```bash
./docker-changes/apply.sh
```

**2. Publish the ETL API.** The container exposes port 5000 and publishes
nothing, so the backend cannot reach it. A socat sidecar bridges it:

```bash
docker run -d --name i2b2-etl-proxy --network i2b2-net \
  --restart unless-stopped -p 5001:5000 \
  alpine/socat TCP-LISTEN:5000,fork,reuseaddr TCP:i2b2-etl:5000
```

**3. Issue yourself a session id.** Authentication is not password-based — see
the comment in `config.template.yaml`. Copy that file to `config.yaml` (it is
gitignored) and fill in the session id.

Sanity check once all three are done: `GET /api/ml-model-types` should list nine
algorithms. If it 503s, step 1 did not take.

The backend runs on the **host**, not in a container — it needs the `docker` CLI
on its PATH and permission to exec into the i2b2 containers.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

cd frontend && npm install
```

## Running

Two processes, in separate terminals:

```bash
.venv/bin/python main.py     # backend on http://127.0.0.1:8003
cd frontend && npm run dev   # frontend on http://localhost:5173
```

Open the frontend URL. Vite proxies `/api` to the backend, so the browser only
ever talks to one origin. If port 5173 is taken, Vite picks the next free port —
the proxy follows automatically, but `cors_origins` in the config still lists
5173, which only matters if you call the API cross-origin.

## Configuration

Settings live in [`app/core/config.py`](app/core/config.py) and can be overridden
by environment variables or a `.env` file:

| Setting | Default | Notes |
| --- | --- | --- |
| `container` | `i2b2-etl` | Container the ETL CLI runs in |
| `db_container` | `i2b2-pg` | Container `psql` runs in |
| `host` / `port` | `127.0.0.1` / `8003` | Backend bind address |
| `cors_origins` | `localhost:5173` | Allowed browser origins |

`container` and `db_container` are separate on purpose: the ETL container ships
`psql` but has no local Postgres server, so count queries have to run against the
database container itself.

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness check |
| `POST` | `/api/load-concepts` | Upload a concepts CSV |
| `POST` | `/api/load-facts` | Upload a facts CSV (`?mrn_are_patient_numbers=`) |
| `GET` | `/api/verify-load` | Row counts for concepts and facts |
| `DELETE` | `/api/delete-concepts` | Delete all concepts (**and every model**) |
| `DELETE` | `/api/delete-facts` | Delete all facts |
| `GET` | `/api/concepts`, `/api/concept-tree` | Concept list and selectable path prefixes |
| `GET`/`POST`/`DELETE` | `/api/cohorts` | Patient sets, with live size and duplicate-name flags |
| `GET` | `/api/cohorts/{id}/definition` | The concept a cohort selected on, where anything recorded it |
| `GET` | `/api/data-quality` | Duplicate, orphan and colliding rows across the warehouse |
| `GET` | `/api/ml-model-types` | Algorithms the container's registry can build |
| `GET`/`POST` | `/api/ml-concepts` | Model configs |
| `DELETE` | `/api/ml-concepts/{code}` | Delete **one** model, rather than wiping every concept |
| `GET` | `/api/ml-concepts/{code}/config\|metrics\|plots` | Stored config, metrics, diagnostic plots |
| `POST` | `/api/jobs/build`, `/api/jobs/apply` | Queue a job; returns its id |
| `GET` | `/api/jobs` | Recent job rows |
| `POST` | `/api/jobs/{id}/reset` | Return a job stranded at `PROCESSING` to `PENDING` |
| `GET`/`POST` | `/api/watcher`, `/api/watcher/start`, `/api/watcher/log` | Job watcher state |

Interactive docs at `http://127.0.0.1:8003/docs`.

Two of these report less than you might expect, on purpose:

- **`/api/cohorts/{id}/definition`** returns `recorded: false` for every patient
  set this app created. Those go through the ETL's test helper, which writes a
  fixed `\i2b2\Diagnoses\ICD10\E11\` item_key into every query it makes — so
  the stored definition names a Type 2 Diabetes code regardless of the actual
  concept. It is withheld rather than shown, because a heart cohort labelled as
  diabetes is worse than one labelled as unknown.
- **`/api/data-quality`** attributes each fact to exactly one dataset. A concept
  code declared under two roots (`age` is, on the review instance) cannot belong
  to either, so those facts are counted in their own bucket. Joining
  `observation_fact` to `concept_dimension` directly instead double-counts them
  and invents patient overlap between datasets that share none.

## CSV requirements

The i2b2 loader takes a **directory**, not a file, and globs it for filenames
ending in `concepts.csv` or `facts.csv`. The upload endpoints handle the
directory part — each upload gets its own generated directory — but **the
filename suffix still matters**. A file named `breastcancer_concepts.csv` is
picked up; `breastcancer.csv` is not.

The CLI itself is silent about this: when the glob matches nothing it logs its
options banner, does nothing, and exits 0. The upload endpoints no longer let it
get that far — a name that would be ignored is rejected with **400** up front,
and the message says why. Names are also restricted to letters, digits, dot,
underscore and hyphen, up to 120 characters, because the name crosses into a
shell command inside the container. Anything else is rejected rather than
cleaned up.

Uploads are capped at 512 MB and both the host and container copies are deleted
once the load finishes, however it finishes.

## Researcher code execution, and what it does not protect against

Researchers can write a Python `transform(df)` that engineers features for
their own model. It runs in a container with `--network none`, no credentials,
no host mounts and a read-only root. The claim is **no egress, not no data
access**: on a real build the code sees every patient row it transforms, and
what it cannot do is send those rows anywhere. Anyone approving a run should
know which of those two they are being trusted with.

`sandbox/README.md` covers the mechanism. What follows is what it does *not*
close, because a control whose limits are not written down gets believed beyond
them.

**1. The output frame is an unclosed leak channel.** A transform can encode raw
values into a column it returns. Those flow into the model, into
`selected_features`, into `metrics`, and on the apply path into
`observation_fact` as per-patient predictions. No sandbox fixes this — it is
model inversion, and it is inherent to "your code produces the features the
model trains on".

What exists instead is traceability and containment: apply is gated,
`transform_sha256` is stamped on every trained model so any prediction set
leads back to the exact code that produced it, and no endpoint returns a row of
the real transformed frame. That last one is an invariant with a test behind
it, not a convention.

**2. The import allowlist is ergonomics, not security.** `guard.py` rejects
`import os`, and `pd.read_csv` opens a file without being an import. It is
there so a `import requests` pasted from a notebook produces a clear sentence
in a second instead of a confusing failure inside a container with no DNS.
Treat a pass as "nothing obviously wrong", never as "this code is safe".

**3. Differencing attacks are not prevented.** Cell-size suppression at k=11
stops a single small count being published. It does nothing against someone who
runs repeated builds over shifting cohorts and subtracts the results —
k-anonymity has no answer to an adaptive querier. The audit log is the
detection story here, not prevention. **A query budget is out of scope**, and
saying so is more honest than implying the threshold covers it.

**4. Suppression applies to researchers, not custodians.** A custodian loads
the data and can delete it. Withholding a count of four orphan facts from the
person whose job is to fix those four facts would make `/data-quality` useless
for its only purpose while protecting nothing they cannot already read.

**5. A transform build depends on this backend being up.** The ETL container
spools the frame out and waits; if nothing answers, the build fails. It fails
loudly and by name, and the job queue refuses at submission time rather than
letting a job hang — but it is a new way for a build to fail that has nothing
to do with the model.

**6. The concept blob is the wrong long-term home for source code.** It already
holds a pickled model and five base64 PNGs. Storing the transform there was the
right call for now — no new storage, and it inherits an existing round trip
that is now tested — but if transforms get used seriously the answer is a table
or version-controlled files with the blob holding only a hash. Decide that
before the blob grows a fourth kind of payload.

**7. The docker-socket privilege is the dominant risk if this is ever exposed.**
This process can `docker exec` into the i2b2 containers, which is
root-equivalent on the host. On loopback that is an accepted risk. Publicly
reachable it means any RCE in this process is host root, from the internet.
That wants splitting before exposure: a public-facing API with no docker
access, talking over loopback to a small privileged helper with a fixed command
allowlist and no shell. Architectural, not a config flag.

### Cell-size suppression

k = 11, matching the CMS cell-size suppression policy — a published rule to
point a reviewer at rather than a number we picked. Three rules, in
`app/core/redact.py`:

- **Suppressed is null, never zero.** "Two patients" and "no patients" must not
  render identically, and a zero says the second confidently.
- **Suppressed says so.** Every payload carries a `suppressed` list naming the
  withheld fields, because a bare null is ambiguous between "small", "not
  applicable" and "not loaded yet".
- **Complementary suppression.** If one cell of a group goes, the whole group
  goes including totals — `tn = n_samples - tp - fp - fn`, so publishing three
  cells and a total publishes the fourth.

The confusion-matrix *image* is withheld along with the counts, because
`model_plots.py` draws the raw cell counts onto the heatmap. Redacting the
numbers and serving that PNG would have been theatre.
