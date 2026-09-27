# The transform sandbox

A researcher writes a `transform(df)` function. This is the container it runs
in and the code that drives it.

```
app/api/transform.py      the endpoint
app/core/synthetic.py     builds a plan from the published data dictionary
app/core/sandbox.py       the `docker run` line, and reading its exit code
sandbox/Dockerfile        the image
sandbox/build.sh          pins it to the ETL container's libraries
sandbox/runner/           what runs inside: guard, materialize, run, validate
```

## The claim, stated precisely

**No egress. Not "no data access."**

On the real path — which does not exist yet; see *Status* — the transform sees
every patient row it transforms. That is what a feature transform is. What it
cannot do is send those rows anywhere.

Anyone approving a run should know which of those two they are being asked to
trust. The distinction belongs in the UI copy, not only in this file.

## What is actually holding the line

`--network none`.

That is the control. There is no DNS, no route, no loopback to anything but
itself. A transform that calls `socket.create_connection(("i2b2-pg", 5432))`
fails because there is no network, not because something noticed it trying.

Everything else on the command line is hygiene — it turns a mistake into a
clean error instead of a confusing one:

| Flag | What it prevents |
|---|---|
| `--user 65534:65534` | running as root inside the container |
| `--read-only` | writing anywhere except the scratch tmpfs |
| `--tmpfs /tmp:noexec,nosuid` | writing a file and then executing it |
| `--cap-drop ALL`, `--security-opt no-new-privileges` | regaining privilege |
| `--memory 2g --memory-swap 2g` | thrashing instead of dying; see below |
| `--cpus 1.0`, `--pids-limit 128` | starving the host |
| `--log-driver none` | a researcher's `print` landing in the host's logs |

No mounts of any kind, no environment carrying a credential, and no docker
socket — mounting the socket into the sandbox would make the whole thing
decorative, since it is root on the host.

`--memory-swap` equal to `--memory` is the non-obvious one. Without it an
over-allocating transform swaps, runs slowly, and then trips the wall clock —
so it is reported as a *timeout*, and the researcher goes off to optimise code
that is not slow.

## The import allowlist is ergonomics, not security

`runner/guard.py` rejects `import os`. It is trivially bypassable —
`pd.read_csv` opens a file and `pd.read_sql` opens a socket, and neither is an
`import`. Anyone trying to get around it will.

It exists so that `import requests`, pasted in from a notebook, produces a
clear sentence in a second instead of a confusing failure thirty seconds later
inside a container with no DNS.

**A design that claims otherwise will be believed and then breached.** Treat a
pass from the guard as "nothing obviously wrong", never as "this code is safe".

## Two details that are easy to get wrong

**fd 1 is taken away from user code before any of it runs.** `runner/run.py`
dups the real stdout to a private descriptor and points fd 1 at stderr. Without
that, one `print(df)` in a transform lands in the middle of the JSON response
and the host reports a parse error at a character offset, with nothing pointing
at the debug line that caused it. Two layers: a Python-level
`redirect_stdout` so prints come back as `logs`, and the descriptor-level one
underneath for anything writing to the fd directly.

**The frame's index is opaque ids above 1,000,000, never a `RangeIndex` and
never patient numbers.** The validator's rule is that the returned index must
be a subset of the one handed in — which is what makes row filtering safe. But
against a `0..n-1` index, `reset_index(drop=True)` after a filter produces
`0..k-1`, which *is* a valid subset. The check would pass, every row would be
renumbered, and every prediction would be written against the wrong patient,
silently. Ids above a floor make that renumbering impossible to mistake for a
filter. **The real hook must use the same scheme.**

## Version pinning is a refusal, not a warning

The dev loop's whole promise is "if it runs here it runs there". That promise
is worth exactly as much as the version match behind it: between pandas 1.x and
2.x, `groupby` defaults, silent downcasting and copy-on-write all changed
behaviour without changing an API.

So `build.sh` reads the versions out of the running ETL container and refuses
to build on a mismatch, rather than warning.

```sh
./sandbox/build.sh probe     # read the versions, write requirements.txt
./sandbox/build.sh           # verify, then build
```

`requirements.txt` ships holding `UNPROBED`, and the build refuses while it
does. Do not hand-edit the pins to make a build go through — a guess is worse
than a stop, because nothing downstream can tell the difference.

## The synthetic frame is a shape, not data

It is generated from the published data dictionary and nothing else, so it
provably carries nothing that was not already published. Two consequences worth
knowing before writing code against it:

**Columns are independent.** There is no correlation structure and none is
implied. The frame exists so code can *run* — names, dtypes, NaN patterns,
ranges, row counts. Do not use it to estimate anything. Independent marginals
are *obviously* fake, and that obviousness is deliberate: a plausible-but-fake
correlation would let someone validate an imputation, ship it, and have the
real run quietly differ while reporting success.

**A column the dictionary withheld arrives all-NaN.** Too few patients to
describe means there was nothing to draw from. The column is still in the frame
— leaving it out would make `df['x']` raise in development and work in
production — but it is empty here and **not empty in production**. The dry-run
report warns per column. Code that skips such a column here will meet real
values there.

`hostile: true` halves every fill rate, widens the tails and multiplies the
all-NaN rows. It is the cheapest way to find out that a transform assumes a
column is always populated.

## Status

Implemented: the dry-run path, end to end, against fabricated data.

Not implemented: the real-data path. That runs inside the ETL container via a
hook in `apply_build_model_ml.py`, with the host polling a spool directory —
the ETL container gains no docker access and no new network route. Until it
exists, nothing in this directory has ever seen a patient row.

## Unverified

The Docker daemon was unreachable while this was written, so:

- the image has never been built
- `build.sh probe` has never run against a live ETL container, and the pinned
  versions are therefore placeholders
- no container has ever been launched with the flags in `app/core/sandbox.py`
- the escape attempts that would prove the isolation — a socket to `i2b2-pg`,
  `open("/etc/passwd")`, `[0]*10**9` asserting *memory* rather than *timeout*,
  `while True: pass` asserting *timeout* rather than *memory* — have not been
  run

What *has* been verified is everything inside the container: `runner/` is
driven as a real subprocess by `tests/test_sandbox_runner.py`, which covers the
guard, the generator, the transform call, the validator and the fd-1
redirection. `tests/test_sandbox_args.py` asserts the flags are passed and that
an exit code becomes the right sentence — it does not assert that the flags
work.

## Residual risk this does not close

**The output frame is a leak channel and no sandbox fixes it.** A transform can
encode raw values into a column it returns; those flow into the model, into
`selected_features`, into `metrics`, and on the apply path into
`observation_fact` as per-patient predictions. This is model inversion, and it
is inherent to "your code produces the features the model trains on".

The mitigations are not technical barriers: keep apply custodian-gated, record
`transform_sha256` on every model so any prediction set is traceable back to
the code that made it, and hold the invariant that **no endpoint ever returns a
row of the real transformed frame**. The dry run returns frame contents
precisely because that data is fabricated; the real run must return aggregate
counts and nothing else. The two must not look alike.
