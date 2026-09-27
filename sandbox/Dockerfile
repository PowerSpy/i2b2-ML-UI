# The sandbox a researcher's feature transform runs in.
#
# It holds no credentials, no warehouse client and no application code. The
# only things that reach it are a JSON request on stdin and the pinned
# libraries below; the only thing that leaves is a JSON response on stdout.
#
# Build it with `./sandbox/build.sh`, not `docker build` - the script verifies
# the pins against the live ETL container first, and an unverified image is
# worse than no image because the dev loop would quietly stop meaning anything.

# Matched to the ETL container's interpreter. build.sh passes the probed value;
# the default is here so `docker build` fails on a mismatch rather than
# silently using whatever is newest.
ARG PYTHON_VERSION=UNPROBED
FROM python:${PYTHON_VERSION}-slim

# No pip cache and no compiler in the final image. The transform imports
# libraries; it never builds one.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Thread pools sized for the host's core count inside a --cpus 1.0 cgroup
    # produce contention that reads as a slow transform. One thread each.
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

WORKDIR /sandbox

COPY requirements.txt /sandbox/requirements.txt
RUN python -m pip install -r /sandbox/requirements.txt

COPY runner /sandbox/runner

# Compiled at build time so the read-only filesystem at runtime costs nothing,
# and so a syntax error in the runner surfaces here rather than as a container
# that exits before it can write a response.
RUN python -m compileall -q /sandbox/runner

# Set after compileall, which would otherwise write the cache to /tmp and
# leave the read-only filesystem to be discovered at runtime. Needed because
# the interpreter tries to write a cache for every module it imports.
ENV PYTHONPYCACHEPREFIX=/tmp/pycache

# nobody. Also set at `docker run` time - both, because an image that is only
# safe when the caller remembers a flag is an image that will run as root.
USER 65534:65534

ENTRYPOINT ["python", "-m", "runner.run"]
