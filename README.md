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
| `GET` | `/api/ml-model-types` | Algorithms the container's registry can build |
| `GET`/`POST` | `/api/ml-concepts` | Model configs |
| `GET` | `/api/ml-concepts/{code}/config\|metrics\|plots` | Stored config, metrics, diagnostic plots |
| `POST` | `/api/jobs/build`, `/api/jobs/apply` | Queue a job; returns its id |
| `GET` | `/api/jobs` | Recent job rows |
| `GET`/`POST` | `/api/watcher`, `/api/watcher/start`, `/api/watcher/log` | Job watcher state |

Interactive docs at `http://127.0.0.1:8003/docs`.

## CSV requirements

The i2b2 loader takes a **directory**, not a file, and globs it for filenames
ending in `concepts.csv` or `facts.csv`. The upload endpoints handle the
directory part — each upload gets its own directory — but **the filename suffix
still matters**. A file named `breastcancer_concepts.csv` is picked up;
`breastcancer.csv` is silently ignored.

"Silently" is literal: when the glob matches nothing, the CLI logs its options
banner, does nothing, and exits 0.
