#!/usr/bin/env bash
#
# Build the transform sandbox image, but only if its libraries match the ones
# the real build uses.
#
# The dev loop's promise is "if it runs here it runs there". That promise is
# worth exactly as much as the version match behind it: a pandas minor bump
# changes groupby defaults, silent downcasting and copy-on-write semantics
# without changing a single API, so a transform validated against the wrong
# version passes here and fails on a job row with an error naming neither.
#
# So this script refuses rather than warns. A stale image that looks fine is
# worse than no image, because nothing downstream can tell the difference.
#
#   ./sandbox/build.sh probe    read versions from the ETL container, pin them
#   ./sandbox/build.sh          verify the pins, then build
#   ./sandbox/build.sh verify   verify only
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${SANDBOX_IMAGE:-i2b2-ml-sandbox:local}"
ETL="${ETL_CONTAINER:-i2b2-etl}"
REQ="$HERE/requirements.txt"
PINFILE="$HERE/.python-version"

# pyarrow is not optional: the real-data path hands the frame over as
# parquet so dtypes survive, and a dtype that differs between here and
# the ETL is precisely what this pinning exists to prevent.
PACKAGES=(pandas numpy scikit-learn scipy pyarrow)

die() { echo "build.sh: $*" >&2; exit 1; }

require_docker() {
  command -v docker >/dev/null 2>&1 || die "docker is not on PATH."
  docker info >/dev/null 2>&1 || die "the docker daemon is not reachable."
  docker inspect -f '{{.State.Running}}' "$ETL" 2>/dev/null | grep -q true \
    || die "container '$ETL' is not running. Its library versions are the
        reference for this image, so there is nothing to build against.
        Start the i2b2 stack and try again."
}

# The interpreter the build actually runs under.
#
# **Not `python3`.** The container's start command is
# `source /usr/src/app/.venv/bin/activate && ... python -m i2b2_cdi...`, so the
# model is trained by the venv. The system python3 has none of these libraries,
# and asking it reported every package MISSING while the venv was sitting there
# fully populated - and then, once that was papered over, reported a version
# match that did not exist. A probe pointed at the wrong interpreter is worse
# than no probe, because it answers confidently.
#
# Override with ETL_PYTHON if the layout changes.
ETL_PYTHON_CANDIDATES="${ETL_PYTHON:-} /usr/src/app/.venv/bin/python python3"

etl_python() {
  local c
  for c in $ETL_PYTHON_CANDIDATES; do
    [ -n "$c" ] || continue
    if docker exec "$ETL" sh -c "command -v '$c' >/dev/null 2>&1 || [ -x '$c' ]"; then
      echo "$c"
      return 0
    fi
  done
  die "no usable python inside '$ETL'. Tried: $ETL_PYTHON_CANDIDATES"
}

# Describes what is *installed*, not what a requirements file intended. On this
# container the two differ: requirements.txt declares pandas==2.3.0 and the
# venv runs 2.3.3.
probe_versions() {
  local py; py="$(etl_python)"
  echo "interpreter=$py"
  # Quoted heredoc via the container's shell: a bare `docker exec ... /usr/...`
  # argument gets rewritten to a host path by Git Bash on Windows.
  docker exec "$ETL" sh -c "'$py' -c '
import importlib.metadata as m, sys
print(\"python=%d.%d\" % sys.version_info[:2])
for p in (\"pandas\", \"numpy\", \"scikit-learn\", \"scipy\", \"pyarrow\"):
    try:
        print(\"%s=%s\" % (p, m.version(p)))
    except Exception:
        print(\"%s=MISSING\" % p)
'" 2>/dev/null || die "could not run '$py' inside '$ETL'."
}

cmd_probe() {
  require_docker
  local out py
  out="$(probe_versions)"
  echo "$out" | sed 's/^/  /' >&2

  py="$(echo "$out" | sed -n 's/^python=//p')"
  [ -n "$py" ] || die "no python version came back from '$ETL'."
  echo "build.sh: probed $(echo "$out" | sed -n 's/^interpreter=//p')" >&2

  # Nothing installed is not the same as nothing declared. If the interpreter
  # genuinely has no ML libraries, fall back to the pins the container declares
  # so the dry run still works - but record that they are *declared*, so
  # `verify` can never claim a match it has not observed.
  #
  # Reaching this branch is now itself a warning sign: it usually means the
  # probe found the wrong interpreter rather than that the container is
  # broken. The declared pins are not reliable either - this container
  # declares pandas==2.3.0 and its venv runs 2.3.3.
  local source="installed"
  for p in "${PACKAGES[@]}"; do
    if [ "$(echo "$out" | sed -n "s/^${p}=//p")" = "MISSING" ]; then
      source="declared"
      break
    fi
  done

  if [ "$source" = "declared" ]; then
    echo "build.sh: '$ETL' has no ML libraries installed - it cannot run a" >&2
    echo "          model build in this state. Falling back to the versions" >&2
    echo "          it declares in /usr/src/app/requirements.txt." >&2
    local declared
    # Via the container's shell, not `docker exec cat /usr/...`: on Windows,
    # Git Bash rewrites a leading-slash argument into a host path, so that
    # form goes looking for the file under the Git installation directory.
    # A quoted script string is passed through untouched.
    declared="$(docker exec "$ETL" sh -c 'cat /usr/src/app/requirements.txt' 2>/dev/null)" \
      || die "'$ETL' has neither the libraries installed nor a
        requirements.txt to read them from. There is nothing to pin to."
    for p in "${PACKAGES[@]}"; do
      local v
      v="$(echo "$declared" | grep -iE "^${p}==" | head -1 | cut -d= -f3)"
      [ -n "$v" ] || die "'$ETL' declares no version for $p."
      out="$(echo "$out" | sed "s/^${p}=MISSING$/${p}=${v}/")"
    done
  fi

  {
    if [ "$source" = "declared" ]; then
      echo "# Pinned to the versions '$ETL' DECLARES in its requirements.txt."
      echo "#"
      echo "# It does not have them installed, so it cannot currently run a"
      echo "# model build and these pins have not been observed running"
      echo "# anything. Re-probe once the container's dependencies are"
      echo "# installed - until then the dev loop's promise that behaviour"
      echo "# here predicts behaviour there is unverified."
    else
      echo "# Pinned to the libraries installed in the '$ETL' container."
    fi
    echo "# Written by sandbox/build.sh probe on $(date -u +%Y-%m-%dT%H:%M:%SZ)."
    echo "#"
    echo "# Do not hand-edit. Re-probe after any change to the ETL image:"
    echo "#     ./sandbox/build.sh probe"
    echo "#"
    echo "# A mismatch between these and the container is not a warning. The"
    echo "# whole point of the dev loop is that behaviour here predicts"
    echo "# behaviour there, and a version skew silently ends that."
    echo
    for p in "${PACKAGES[@]}"; do
      echo "${p}==$(echo "$out" | sed -n "s/^${p}=//p")"
    done
  } > "$REQ"

  echo "$py" > "$PINFILE"
  echo "$source" > "$HERE/.pin-source"
  echo "build.sh: pinned to python $py and:" >&2
  grep -v '^#' "$REQ" | grep . | sed 's/^/  /' >&2
}

cmd_verify() {
  grep -q 'UNPROBED' "$REQ" && die "requirements.txt still holds placeholders.
        Run './sandbox/build.sh probe' against a running stack first. Editing
        the pins by hand defeats the check that makes this image meaningful."

  require_docker
  local out mismatch=0
  out="$(probe_versions)"

  if [ "$(cat "$HERE/.pin-source" 2>/dev/null)" = "declared" ]; then
    echo "build.sh: pins came from '$ETL''s requirements.txt, not from" >&2
    echo "          libraries it actually has. Nothing to verify against." >&2
    echo "          The image will build; the version match is a claim, not" >&2
    echo "          an observation, until the container's deps are installed." >&2
    return 0
  fi

  for p in "${PACKAGES[@]}"; do
    local want have
    want="$(sed -n "s/^${p}==//p" "$REQ" | head -1)"
    have="$(echo "$out" | sed -n "s/^${p}=//p")"
    if [ "$want" != "$have" ]; then
      echo "build.sh: $p is pinned at $want but '$ETL' runs $have" >&2
      mismatch=1
    fi
  done

  local want_py have_py
  want_py="$(cat "$PINFILE" 2>/dev/null || echo '')"
  have_py="$(echo "$out" | sed -n 's/^python=//p')"
  if [ "$want_py" != "$have_py" ]; then
    echo "build.sh: python is pinned at ${want_py:-unset} but '$ETL' runs $have_py" >&2
    mismatch=1
  fi

  [ "$mismatch" -eq 0 ] || die "refusing to build against a version skew.
        Re-probe with './sandbox/build.sh probe', then re-validate any saved
        transform - one of them may have been developed against behaviour the
        real build no longer has."

  echo "build.sh: pins match '$ETL'." >&2
}

cmd_build() {
  cmd_verify
  docker build \
    --build-arg "PYTHON_VERSION=$(cat "$PINFILE")" \
    -t "$IMAGE" \
    "$HERE"
  echo "build.sh: built $IMAGE" >&2
}

case "${1:-build}" in
  probe)  cmd_probe ;;
  verify) cmd_verify ;;
  build)  cmd_build ;;
  *)      die "unknown command '${1}'. Use probe, verify or build." ;;
esac
