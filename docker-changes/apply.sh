#!/usr/bin/env bash
#
# Reinstalls the container-side changes this UI depends on.
#
# The i2b2-etl container has no bind mounts, so everything here lives in its
# writable layer: it survives `docker restart` but is lost on `docker rm`.
# Run this after any recreate.
#
# Idempotent - re-running it overwrites the same three files and re-checks.

set -euo pipefail

CONTAINER="${CONTAINER:-i2b2-etl}"
ML_DIR="/usr/src/app/i2b2_cdi/ML"
FACT_DIR="/usr/src/app/i2b2_cdi/fact"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> target container: $CONTAINER"
docker inspect "$CONTAINER" >/dev/null

# Keep a pristine copy inside the container the first time only, so a second
# run cannot overwrite the original with an already-patched file.
echo "==> backing up the stock files (first run only)"
docker exec "$CONTAINER" bash -lc \
  "cd $ML_DIR && [ -f apply_build_model_ml.py.orig ] || cp apply_build_model_ml.py apply_build_model_ml.py.orig"
docker exec "$CONTAINER" bash -lc \
  "cd $FACT_DIR && [ -f fact_validation_helper.py.orig ] || cp fact_validation_helper.py fact_validation_helper.py.orig"

# The validator is *copied* from the sandbox rather than kept as a second
# copy here. The container and the sandbox have to agree about what a valid
# transform output is; two hand-maintained files would drift, and the way they
# would drift is one side accepting a frame the other rejects.
echo "==> staging the shared transform validator"
cp "$HERE/../sandbox/runner/validate.py" "$HERE/i2b2_cdi/ML/transform_validate.py"

echo "==> copying files in"
for f in apply_build_model_ml.py model_registry.py model_plots.py transform_hook.py transform_validate.py; do
    docker cp "$HERE/i2b2_cdi/ML/$f" "$CONTAINER:$ML_DIR/$f"
    echo "    ML/$f"
done
docker cp "$HERE/i2b2_cdi/fact/fact_validation_helper.py" \
          "$CONTAINER:$FACT_DIR/fact_validation_helper.py"
echo "    fact/fact_validation_helper.py"

# Stale .pyc files shadow the new source until something invalidates them.
docker exec "$CONTAINER" bash -lc "rm -rf $ML_DIR/__pycache__ $FACT_DIR/__pycache__"

echo "==> restarting $CONTAINER"
docker restart "$CONTAINER" >/dev/null

echo "==> waiting for the app to come up"
for _ in $(seq 1 60); do
    if docker exec "$CONTAINER" bash -lc "test -d /usr/src/app" >/dev/null 2>&1; then break; fi
    sleep 1
done

echo "==> verifying the transform hook imports"
docker exec "$CONTAINER" bash -lc "cd /usr/src/app && .venv/bin/python -c '
from i2b2_cdi.ML.transform_hook import run_transform, read_source
from i2b2_cdi.ML import transform_validate
print(\"transform hook: ok\")
'"

echo "==> verifying the registry imports"
docker exec "$CONTAINER" bash -lc "cd /usr/src/app && .venv/bin/python -c '
from i2b2_cdi.ML.model_registry import MODEL_REGISTRY
from i2b2_cdi.ML.model_plots import generate_plots
print(\"registry:\", list(MODEL_REGISTRY.keys()))
'"

# Worth its own check: a syntax error here takes down fact loading entirely,
# and the upstream patch this file derives from shipped exactly that.
echo "==> verifying the fact validator imports"
docker exec "$CONTAINER" bash -lc "cd /usr/src/app && .venv/bin/python -c '
from i2b2_cdi.fact.fact_validation_helper import validate_fact_row
print(\"fact validator: ok\")
'"

echo "==> verifying the builder is wired to the registry"
docker exec "$CONTAINER" bash -lc \
  "grep -q 'from i2b2_cdi.ML.model_registry import build_model' $ML_DIR/apply_build_model_ml.py" \
  && echo "    ok"

cat <<'EOF'

Done. Two things this script deliberately does not do:

  1. jobWatcher restarts itself - it is in the container's own start command,
     roughly 75s after the container comes up (there is a `sleep 60` first).
     Do not start it by hand; a second one races the first for queued jobs.

  2. Models with a feature transform need the i2b2 ML UI backend running.
     Their code is executed on the host, in a sandbox container with no
     network - this container only writes a request and waits. A build
     submitted while the backend is down is refused at queue time rather
     than hanging.

  3. The API is not reachable from the host on its own - this container
     publishes no ports. Start the proxy once:

       docker run -d --name i2b2-etl-proxy --network i2b2-net \
         --restart unless-stopped -p 5001:5000 \
         alpine/socat TCP-LISTEN:5000,fork,reuseaddr TCP:i2b2-etl:5000

Confirm a real build afterwards: a `dummy` model should land at ROC-AUC ~0.5
and report clf_type=DummyClassifier. The registry falls back to logistic
regression for an unknown model_type without erroring, so a model that trains
is not by itself proof the wiring is live.
EOF
