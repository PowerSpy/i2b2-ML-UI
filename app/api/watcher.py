import shlex
import time

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.core.docker_exec import exec, exec_detached

router = APIRouter()

WATCHER_CMD = "python -m i2b2_cdi.job.jobWatcher"
LOG = "/tmp/jobwatcher.log"

# The container ships neither pgrep nor ps, so the process table is read from
# /proc. The needle is split so this probe never matches its own command line,
# and the bash wrapper that launched the watcher is filtered out so the count
# reflects daemons rather than daemons plus their parents.
PROBE = """
import glob, os
skip = {os.getpid(), os.getppid()}
needle = "i2b2_cdi.job." + "jobWatcher"
hits = []
for path in glob.glob("/proc/[0-9]*/cmdline"):
    try:
        pid = int(path.split("/")[2])
    except ValueError:
        continue
    if pid in skip:
        continue
    try:
        raw = open(path, "rb").read().decode("utf8", "ignore")
    except OSError:
        continue
    cmdline = raw.replace(chr(0), " ").strip()
    if needle in cmdline and not cmdline.startswith("bash"):
        hits.append(str(pid) + " " + cmdline)
print(len(hits))
for h in hits:
    print(h)
"""


class Watcher_Status(BaseModel):
    running: bool
    count: int = 0
    detail: str = ""


class Watcher_Log(BaseModel):
    lines: str


@router.get("/watcher", response_model=Watcher_Status)
def watcher_status() -> Watcher_Status:
    # The venv has to be sourced first: there is no `python` on the container's
    # default PATH, so without this the probe exits 127 and every check reports
    # zero watchers. That silent always-stopped reading is worse than it looks —
    # watcher_start() trusts it, so each start spawns another daemon on top of
    # the one already polling.
    out = exec(settings.container,
               f"source {settings.etl_venv}",
               f"python -c {shlex.quote(PROBE)}")
    lines = out.stdout.strip().splitlines()
    count = int(lines[0]) if lines and lines[0].strip().isdigit() else 0
    return Watcher_Status(running=count > 0, count=count,
                          detail="\n".join(lines[1:]))


@router.post("/watcher/start", response_model=Watcher_Status)
def watcher_start() -> Watcher_Status:
    current = watcher_status()
    if current.running:
        return current

    exec_detached(
        settings.container,
        f"source {settings.etl_venv}",
        f"cd {settings.etl_app_dir}",
        f"nohup {WATCHER_CMD} >> {LOG} 2>&1",
    )
    time.sleep(1)
    return watcher_status()


@router.get("/watcher/log", response_model=Watcher_Log)
def watcher_log(lines: int = 100) -> Watcher_Log:
    out = exec(settings.container, f"tail -{int(lines)} {LOG} 2>/dev/null || true")
    return Watcher_Log(lines=out.stdout)
