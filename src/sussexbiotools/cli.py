# Copied from the sussexbiotools platform at commit 37d69ba. Do not edit.
"""Command line: ``sussexbiotools run <tool> ...``, ``runs``, ``show``, ``serve``.

Each tool gets its own ``run`` subcommand, generated from its signature, so
``sussexbiotools run famsa_align --help`` lists exactly that tool's options.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import time
from pathlib import Path
from typing import Annotated, Any

import click
import typer

from . import runs
from .registry import BROKEN, ToolSpec, load_tools

app = typer.Typer(
    help="Run the lab's bioinformatics tools and browse their history.",
    no_args_is_help=True,
    add_completion=False,
)
run_app = typer.Typer(
    help="Run a tool. See `sussexbiotools tools` for the list.", no_args_is_help=True
)
app.add_typer(run_app, name="run")


def _follow(run_id: str) -> dict[str, Any]:
    """Print the run's log as it grows, until the run finishes."""
    path = runs.runs_dir() / run_id / runs.LOG
    pos = 0
    while True:
        m = runs.get_run(run_id)
        if path.is_file():
            with path.open() as fh:
                fh.seek(pos)
                chunk = fh.read()
                pos = fh.tell()
            if chunk:
                typer.echo(chunk, nl=False)
        if m["status"] not in runs.ACTIVE:
            return m
        time.sleep(1)


def _command_for(spec: ToolSpec):
    def command(**kwargs: Any) -> None:
        detach = kwargs.pop("detach")
        inputs = {i.name: kwargs.pop(i.name) for i in spec.inputs}
        try:
            run_id = runs.create_run(spec, kwargs, inputs)
        except runs.RunError as e:
            raise typer.BadParameter(str(e)) from e
        runs.launch(run_id)
        typer.echo(f"run {run_id}")
        if detach:
            return
        m = _follow(run_id)
        if m["status"] != "succeeded":
            typer.secho(f"{m['status']}: {m['error']}", fg="red", err=True)
            raise typer.Exit(1)
        for name, out in m["outputs"].items():
            typer.echo(f"  {name}: @{run_id}:{out['file']}  ({out['summary']})")

    params = []
    for i in spec.inputs:
        params.append(
            inspect.Parameter(
                i.name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=str,
                default=typer.Option(
                    ...,
                    metavar="FILE|@RUN:FILE",
                    help=f"{i.format.label}: a file, or @<run>:<file> "
                    f"from an earlier run. {i.help}",
                ),
            )
        )
    for p in spec.params:
        params.append(
            inspect.Parameter(
                p.name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=str if p.choices else p.type,
                default=typer.Option(
                    ... if p.required else p.default,
                    help=p.help,
                    metavar="|".join(p.choices) if p.choices else None,
                    click_type=click.Choice(p.choices) if p.choices else None,
                ),
            )
        )
    params.append(
        inspect.Parameter(
            "detach",
            inspect.Parameter.KEYWORD_ONLY,
            annotation=bool,
            default=typer.Option(False, help="Start the run and return without waiting."),
        )
    )
    command.__signature__ = inspect.Signature(params)
    command.__doc__ = spec.description
    return command


for _spec in load_tools().values():
    run_app.command(name=_spec.id, help=_spec.description)(_command_for(_spec))


@app.command()
def tools() -> None:
    """List the available tools."""
    for spec in load_tools().values():
        ins = ", ".join(f"{i.name} ({i.format.name})" for i in spec.inputs) or "-"
        outs = ", ".join(f"{o.name} ({o.format.name})" for o in spec.outputs)
        typer.echo(f"{spec.id}  v{spec.version}\n  {spec.title}\n  in: {ins}\n  out: {outs}\n")
    for module, error in BROKEN.items():
        typer.secho(f"NOT LOADED: {module}: {error}", fg="red", err=True)


@app.command("runs")
def list_runs(
    tool: str = typer.Option(None, help="Only runs of this tool."),
    limit: int = typer.Option(20, help="How many to show."),
) -> None:
    """List recent runs, newest first."""
    for m in runs.list_runs(tool=tool, limit=limit):
        typer.echo(f"{m['id']}  {m['status']:<9}  {m['user']}")


@app.command()
def show(run_id: str) -> None:
    """Print a run's manifest."""
    try:
        typer.echo(json.dumps(runs.get_run(run_id), indent=2))
    except runs.RunError as e:
        raise typer.BadParameter(str(e)) from e


@app.command(hidden=True)
def execute(run_id: str) -> None:
    """Run a queued run in this process (used by the executors)."""
    m = runs.execute(run_id)
    raise typer.Exit(0 if m["status"] == "succeeded" else 1)


def _who(by: str | None) -> str:
    import getpass

    return by or getpass.getuser()


@app.command()
def delete(
    run_ids: Annotated[list[str], typer.Argument(help="Runs to move to the bin.")],
    by: Annotated[str | None, typer.Option(help="Recorded as who deleted them.")] = None,
) -> None:
    """Move finished runs to the bin (restore them with `restore`)."""
    failed = False
    for run_id in run_ids:
        try:
            runs.delete_run(run_id, by=_who(by))
            typer.echo(f"deleted {run_id}")
        except runs.RunError as e:
            typer.secho(str(e), fg="red", err=True)
            failed = True
    raise typer.Exit(1 if failed else 0)


@app.command()
def deleted() -> None:
    """List runs in the bin."""
    for m in runs.list_trash():
        typer.echo(
            f"{m['id']}  {m.get('user', '')}  deleted {m['deleted_at']} by {m['deleted_by']}"
        )


@app.command()
def restore(
    run_ids: Annotated[list[str], typer.Argument(help="Deleted runs to bring back.")],
    by: Annotated[str | None, typer.Option(help="Recorded as who restored them.")] = None,
) -> None:
    """Bring runs back from the bin."""
    for run_id in run_ids:
        runs.restore_run(run_id, by=_who(by))
        typer.echo(f"restored {run_id}")


@app.command()
def purge(
    run_ids: Annotated[
        list[str] | None, typer.Argument(help="Deleted runs to remove for good.")
    ] = None,
    expired: Annotated[
        bool, typer.Option(help="Remove every run past the bin's retention period.")
    ] = False,
    by: Annotated[str | None, typer.Option(help="Recorded as who removed them.")] = None,
) -> None:
    """Remove runs from the bin for good (their files are deleted)."""
    if expired:
        gone = runs.purge_expired()
        typer.echo(f"purged {len(gone)} expired run(s) (kept for {runs.trash_days()} days)")
    for run_id in run_ids or []:
        runs.purge_run(run_id, by=_who(by))
        typer.echo(f"purged {run_id}")
    if not expired and not run_ids:
        raise typer.BadParameter("give run ids, or --expired")


@app.command("clean-uploads")
def clean_uploads(
    hours: Annotated[int, typer.Option(help="Remove unused uploads older than this.")] = 24,
) -> None:
    """Remove files uploaded on tool forms but never used in a run."""
    typer.echo(f"removed {runs.clean_uploads(hours)} unused upload(s)")


@app.command("check-tools")
def check_tools() -> None:
    """Fail if any tool file does not load (used by tests and auto-deploy)."""
    found = load_tools()
    for module, error in BROKEN.items():
        typer.secho(f"NOT LOADED: {module}: {error}", fg="red", err=True)
    typer.echo(f"{len(found)} tools loaded, {len(BROKEN)} not loaded")
    raise typer.Exit(1 if BROKEN else 0)


# Commands for the server only. The students' toolkit carries this same file
# without the web app, and there these commands do not appear.
SERVER = importlib.util.find_spec("sussexbiotools.web") is not None


def server_command(*args: Any, **kwargs: Any):
    return app.command(*args, **kwargs) if SERVER else (lambda func: func)


@server_command()
def sources(
    file: Annotated[Path | None, typer.Option(help="The sources list to read.")] = None,
    tsv: Annotated[bool, typer.Option(help="name, repo, commit per line, for scripts.")] = False,
) -> None:
    """List the approved student tool sources (tool-sources.yaml)."""
    from .sources import SourceError, load_sources

    try:
        found = load_sources(file)
    except SourceError as e:
        raise typer.BadParameter(str(e)) from e
    for s in found:
        typer.echo(
            f"{s.name}\t{s.repo}\t{s.commit}" if tsv else f"{s.name}  {s.commit[:7]}  {s.repo}"
        )


@server_command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Address to listen on."),
    port: int = typer.Option(8100, help="Port to listen on."),
) -> None:
    """Start the web interface."""
    from .web.app import start

    start(host=host, port=port)


DEFAULT_ENV_PATH = Path("/etc/sussexbiotools.env")


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a systemd EnvironmentFile the way systemd does: KEY=value, no shell."""
    values = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line[0] in "#;" or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@server_command()
def link(
    emails: Annotated[
        list[str] | None, typer.Argument(help="Addresses to make sign-in links for.")
    ] = None,
    all_users: Annotated[
        bool, typer.Option("--all", help="Every address in SUSSEXBIOTOOLS_LINK_USERS.")
    ] = False,
    env_file: Annotated[
        Path, typer.Option(help="The service's settings file, holding the link secret.")
    ] = DEFAULT_ENV_PATH,
) -> None:
    """Print personal sign-in links for the campus address.

    Links are derived from the address and a secret, so the same address always
    gives the same link: a lost link is simply printed again. The address must
    be in SUSSEXBIOTOOLS_LINK_USERS (and the service restarted after adding it).
    """
    from .web import auth

    try:
        os.environ.update(read_env_file(env_file))
    except FileNotFoundError:
        raise typer.BadParameter(f"no such file: {env_file}") from None
    except PermissionError:
        raise typer.BadParameter(
            f"cannot read {env_file}: it holds the secret, run with sudo"
        ) from None
    if not os.environ.get("SUSSEXBIOTOOLS_LINK_SECRET"):
        raise typer.BadParameter(f"{env_file} does not set SUSSEXBIOTOOLS_LINK_SECRET")
    base = os.environ.get("SUSSEXBIOTOOLS_BASE_URL", "").rstrip("/")
    if not base:
        raise typer.BadParameter(
            f"{env_file} does not set SUSSEXBIOTOOLS_BASE_URL (the campus address)"
        )

    known = auth.link_users()
    wanted = known if all_users else [e.strip().lower() for e in emails or []]
    if not wanted:
        raise typer.BadParameter("give one or more addresses, or --all")
    unknown = [e for e in wanted if e not in known]
    if unknown:
        raise typer.BadParameter(
            f"not in SUSSEXBIOTOOLS_LINK_USERS: {', '.join(unknown)}. "
            f"Add them to {env_file} and restart the service first, or their link will not work."
        )
    for email in wanted:
        typer.echo(f"{email:<32} {base}{auth.LINK_PREFIX}{auth.link_token(email)}")
    typer.echo(
        f"\nSign-ins last {auth.session_days()} days. Ask people to bookmark the link: "
        "opening it again signs them straight back in.",
        err=True,
    )
