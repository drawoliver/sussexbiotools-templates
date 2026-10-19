# Copied from the sussexbiotools platform at commit 37d69ba. Do not edit.
"""Run folders: the history, the provenance and the hand-off between tools.

Every run is one folder under the runs directory:

    <runs>/<run id>/
        manifest.json     what was run, by whom, on what, and what came out
        inputs/           uploaded or copied input files
        outputs/          the tool's outputs, read-only once the run succeeds
        log.txt           everything the tool printed

There is no database. Listing and searching read the manifests. An input
taken from an earlier run is written as ``@<run id>:<file>`` and recorded,
not copied, so any result can be traced back through its inputs.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .formats import FormatError
from .registry import ToolError, ToolSpec, coerce, get_tool

MANIFEST = "manifest.json"
LOG = "log.txt"
ACTIVE = {"queued", "running"}


class RunError(ValueError):
    """A run could not be created as requested."""


def runs_dir() -> Path:
    path = Path(os.environ.get("SUSSEXBIOTOOLS_RUNS", Path.cwd() / "runs"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def code_version() -> str:
    """Git commit of the installed code, with ``-dirty`` if it has local edits."""
    here = Path(__file__).resolve().parent
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=here,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=here,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return f"{sha}-dirty" if dirty else sha
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def read_manifest(run_id: str) -> dict[str, Any]:
    path = runs_dir() / run_id / MANIFEST
    if not path.is_file():
        raise RunError(f"no run called {run_id!r}")
    return json.loads(path.read_text())


def write_manifest(manifest: dict[str, Any]) -> None:
    folder = runs_dir() / manifest["id"]
    tmp = folder / f".{MANIFEST}.tmp"
    tmp.write_text(json.dumps(manifest, indent=2) + "\n")
    tmp.replace(folder / MANIFEST)


def _reap(m: dict[str, Any]) -> dict[str, Any]:
    """Mark a run failed if its process on this machine has gone without finishing."""
    if m["status"] != "running" or m.get("host") != socket.gethostname() or not m.get("pid"):
        return m
    try:
        os.kill(m["pid"], 0)
    except ProcessLookupError:
        m.update(
            status="failed",
            finished=now(),
            error="the process ended without finishing (killed, or the machine restarted)",
        )
        write_manifest(m)
    except PermissionError:
        pass  # alive, but owned by another user
    return m


def get_run(run_id: str) -> dict[str, Any]:
    return _reap(read_manifest(run_id))


def list_runs(tool: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Manifests, newest first. Run ids start with a timestamp, so names sort by time."""
    out = []
    for folder in sorted(runs_dir().iterdir(), reverse=True):
        if not (folder / MANIFEST).is_file():
            continue
        m = _reap(json.loads((folder / MANIFEST).read_text()))
        if tool and m["tool"] != tool:
            continue
        out.append(m)
        if limit and len(out) >= limit:
            break
    return out


def parse_ref(value: str) -> tuple[str, str] | None:
    """``@<run>:<file>`` -> (run, file); anything else -> None."""
    if not value.startswith("@") or ":" not in value:
        return None
    run_id, _, name = value[1:].partition(":")
    return run_id, name


def resolve_ref(run_id: str, name: str) -> Path:
    """Path to a finished run's output, refusing anything else."""
    m = read_manifest(run_id)
    if m["status"] != "succeeded":
        raise RunError(f"run {run_id} has not succeeded (status {m['status']})")
    outputs = {o["file"]: o for o in m["outputs"].values()}
    if name not in outputs:
        raise RunError(f"run {run_id} has no output {name!r}; it has {', '.join(outputs)}")
    return runs_dir() / run_id / "outputs" / name


def outputs_of_format(
    fmt_name: str, limit: int = 50, visible: Callable[[dict[str, Any]], bool] | None = None
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(manifest, output) pairs from successful runs with outputs of this format.

    ``visible`` limits the search to runs the caller may see (the web app
    passes "this person's runs").
    """
    found = []
    for m in list_runs():
        if m["status"] != "succeeded" or (visible and not visible(m)):
            continue
        for out in m["outputs"].values():
            if out["format"] == fmt_name:
                found.append((m, out))
        if len(found) >= limit:
            break
    return found


def create_run(
    spec: ToolSpec, params: dict[str, Any], inputs: dict[str, str | Path], user: str | None = None
) -> str:
    """Make the run folder and manifest. ``inputs`` values are paths or ``@run:file`` refs."""
    unknown = set(params) - {p.name for p in spec.params}
    if unknown:
        raise RunError(f"{spec.id} has no parameter {', '.join(sorted(unknown))}")
    try:
        values = {p.name: coerce(p, params.get(p.name)) for p in spec.params}
    except ValueError as e:
        raise RunError(str(e)) from e

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_id = f"{stamp}_{spec.id}_{uuid.uuid4().hex[:4]}"
    folder = runs_dir() / run_id
    (folder / "inputs").mkdir(parents=True)
    (folder / "outputs").mkdir()

    recorded: dict[str, dict[str, Any]] = {}
    for inp in spec.inputs:
        raw = inputs.get(inp.name)
        if raw is None or raw == "":
            shutil.rmtree(folder)
            raise RunError(f"input {inp.name!r} ({inp.format.label}) is required")
        ref = parse_ref(str(raw))
        try:
            if ref:
                path = resolve_ref(*ref)
                entry = {"from_run": ref[0], "file": ref[1]}
            else:
                src = Path(raw)
                if not src.is_file():
                    raise RunError(f"input {inp.name!r}: no such file {src}")
                path = folder / "inputs" / src.name
                if src.resolve() != path.resolve():
                    shutil.copy2(src, path)
                entry = {"from_run": None, "file": f"inputs/{src.name}"}
            entry["summary"] = inp.format.validate(path)
        except (RunError, FormatError) as e:
            shutil.rmtree(folder)
            raise RunError(f"input {inp.name!r}: {e}") from e
        entry["sha256"] = sha256(path)
        entry["format"] = inp.format.name
        recorded[inp.name] = entry

    write_manifest(
        {
            "id": run_id,
            "tool": spec.id,
            "tool_version": spec.version,
            "code_version": code_version(),
            "user": user or getpass.getuser(),
            "host": None,
            "status": "queued",
            "created": now(),
            "started": None,
            "finished": None,
            "params": values,
            "inputs": recorded,
            "outputs": {},
            "error": None,
        }
    )
    return run_id


def input_path(run_id: str, entry: dict[str, Any]) -> Path:
    if entry["from_run"]:
        return runs_dir() / entry["from_run"] / "outputs" / entry["file"]
    return runs_dir() / run_id / entry["file"]


def execute(run_id: str) -> dict[str, Any]:
    """Run a queued run in this process. The local and remote executors both end up here."""
    m = read_manifest(run_id)
    if m["status"] != "queued":
        raise RunError(f"run {run_id} is {m['status']}, not queued")
    spec = get_tool(m["tool"])
    folder = runs_dir() / run_id
    m.update(status="running", started=now(), host=socket.gethostname(), pid=os.getpid())
    write_manifest(m)

    kwargs: dict[str, Any] = dict(m["params"])
    for name, entry in m["inputs"].items():
        kwargs[name] = input_path(run_id, entry)
    for out in spec.outputs:
        kwargs[out.name] = folder / "outputs" / out.filename

    try:
        spec.func(**kwargs)
        produced = {}
        for out in spec.outputs:
            path = folder / "outputs" / out.filename
            produced[out.name] = {
                "file": out.filename,
                "format": out.format.name,
                "summary": out.format.validate(path),
                "sha256": sha256(path),
            }
            path.chmod(0o444)
        m.update(status="succeeded", outputs=produced)
    except (ToolError, FormatError) as e:
        print(f"error: {e}", file=sys.stderr)
        m.update(status="failed", error=str(e))
    except Exception as e:
        traceback.print_exc()
        m.update(status="failed", error=f"unexpected {type(e).__name__}: {e}")
    m["finished"] = now()
    write_manifest(m)
    return m


def run_env() -> dict[str, str]:
    """The environment a tool run gets: the service's, minus its secrets and access list.

    The web app holds the session and sign-in-link secrets in its environment
    (from the root-only settings file). Tool code must never see them: a tool
    that could read the link secret could mint a sign-in link for anyone.
    """
    hidden = ("SECRET", "LINK_USERS")
    env = {k: v for k, v in os.environ.items() if not any(h in k for h in hidden)}
    env.update(SUSSEXBIOTOOLS_RUNS=str(runs_dir()), PYTHONUNBUFFERED="1")
    return env


def launch(run_id: str) -> None:
    """Start a queued run in a detached process on this machine.

    The process outlives whoever started it (a web request, a closed
    terminal). Remote hosts will get the same command over SSH.
    """
    folder = runs_dir() / run_id
    with (folder / LOG).open("ab") as log:
        subprocess.Popen(
            [sys.executable, "-m", "sussexbiotools", "execute", run_id],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=folder,
            start_new_session=True,
            env=run_env(),
        )


def log_tail(run_id: str, lines: int = 200) -> str:
    path = runs_dir() / run_id / LOG
    if not path.is_file():
        return ""
    return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])


# --------------------------------------------------------------------------
# Deleting runs
#
# Deleting moves a run into the bin (<runs>/.trash), where it is out of every
# list and cannot be used as an input. It can be restored until it is
# purged: on request, or automatically after the bin's retention period.
# Every action is appended to <runs>/.deletions.log with who and when.
# --------------------------------------------------------------------------

TRASH = ".trash"
DELETIONS_LOG = ".deletions.log"


def trash_dir() -> Path:
    path = runs_dir() / TRASH
    path.mkdir(exist_ok=True)
    return path


def _check_run_id(run_id: str) -> None:
    """Refuse anything that is not a plain run folder name (no paths, no hidden names)."""
    if not run_id or "/" in run_id or "\\" in run_id or run_id.startswith("."):
        raise RunError(f"not a run id: {run_id!r}")


def _record(action: str, run_id: str, owner: str, by: str) -> None:
    entry = {"at": now(), "action": action, "run": run_id, "owner": owner, "by": by}
    with (runs_dir() / DELETIONS_LOG).open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def dependents(run_id: str) -> list[str]:
    """Runs that used one of this run's outputs as an input."""
    return [
        m["id"]
        for m in list_runs()
        if any(e.get("from_run") == run_id for e in m.get("inputs", {}).values())
    ]


def delete_run(run_id: str, by: str) -> dict[str, Any]:
    """Move a finished run to the bin. Returns its manifest."""
    _check_run_id(run_id)
    m = get_run(run_id)
    if m["status"] in ACTIVE:
        raise RunError(f"run {run_id} is still {m['status']}; wait for it to finish")
    m.update(deleted_by=by, deleted_at=now())
    write_manifest(m)
    (runs_dir() / run_id).rename(trash_dir() / run_id)
    _record("deleted", run_id, m.get("user", ""), by)
    return m


def list_trash() -> list[dict[str, Any]]:
    """Manifests of runs in the bin, most recently deleted first."""
    found = []
    for folder in trash_dir().iterdir():
        if (folder / MANIFEST).is_file():
            found.append(json.loads((folder / MANIFEST).read_text()))
    return sorted(found, key=lambda m: m.get("deleted_at", ""), reverse=True)


def trashed_run(run_id: str) -> dict[str, Any]:
    _check_run_id(run_id)
    path = trash_dir() / run_id / MANIFEST
    if not path.is_file():
        raise RunError(f"no deleted run called {run_id!r}")
    return json.loads(path.read_text())


def restore_run(run_id: str, by: str) -> dict[str, Any]:
    """Bring a run back from the bin."""
    m = trashed_run(run_id)
    if (runs_dir() / run_id).exists():
        raise RunError(f"a run called {run_id} already exists")
    (trash_dir() / run_id).rename(runs_dir() / run_id)
    m.pop("deleted_by", None)
    m.pop("deleted_at", None)
    write_manifest(m)
    _record("restored", run_id, m.get("user", ""), by)
    return m


def purge_run(run_id: str, by: str) -> None:
    """Remove a run from the bin for good: its files are deleted."""
    m = trashed_run(run_id)
    shutil.rmtree(trash_dir() / run_id)
    _record("purged", run_id, m.get("user", ""), by)


def trash_days() -> int:
    """How long deleted runs stay in the bin (SUSSEXBIOTOOLS_TRASH_DAYS, default 30)."""
    try:
        return max(0, int(os.environ.get("SUSSEXBIOTOOLS_TRASH_DAYS", "30")))
    except ValueError:
        return 30


def purge_expired(days: int | None = None) -> list[str]:
    """Purge runs deleted more than ``days`` ago (default: trash_days()). Returns their ids."""
    days = trash_days() if days is None else days
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
    expired = [m["id"] for m in list_trash() if m.get("deleted_at", "") <= cutoff]
    purged = []
    for run_id in expired:
        try:
            purge_run(run_id, by="automatic")
            purged.append(run_id)
        except OSError as e:  # one stubborn folder must not stop the rest
            print(f"could not purge {run_id}: {e}", file=sys.stderr)
    return purged


def clean_uploads(hours: int = 24) -> int:
    """Remove files uploaded on a tool form but never run, older than ``hours``."""
    staging = runs_dir() / ".uploads"
    if not staging.is_dir():
        return 0
    cutoff = time.time() - hours * 3600
    removed = 0
    for folder in staging.iterdir():
        if folder.stat().st_mtime < cutoff:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    return removed
