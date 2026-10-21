# Copied from the sussexbiotools platform at commit af50b68. Do not edit.
"""The tool contract: a tool is a typed Python function plus a decorator.

    @tool(id="famsa_align", version="0.1.0", title="Align sequences (FAMSA)")
    def famsa_align(
        sequences: Annotated[Path, In(FASTA, "Sequences to align")],
        alignment: Annotated[Path, Out(ALIGNMENT)],
        guide_tree: Annotated[Literal["sl", "upgma", "nj"], Param("Guide tree method")] = "sl",
    ) -> None: ...

From the signature alone the package builds the CLI options, the web form,
input validation and the "choose a previous output" picker. The decorator
returns the function unchanged, so a tool is still an ordinary function
that tests can call directly.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import pkgutil
import re
import sys
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, get_args, get_origin

import yaml

from .formats import Format

log = logging.getLogger(__name__)


class ToolError(RuntimeError):
    """A tool ran but could not produce a valid result; the message is shown to the user."""


@dataclass(frozen=True)
class In:
    format: Format
    help: str = ""


@dataclass(frozen=True)
class Out:
    format: Format
    help: str = ""


@dataclass(frozen=True)
class Param:
    help: str = ""
    multiline: bool = False


@dataclass(frozen=True)
class InputSpec:
    name: str
    format: Format
    help: str


@dataclass(frozen=True)
class OutputSpec:
    name: str
    format: Format
    help: str

    @property
    def filename(self) -> str:
        return f"{self.name}{self.format.extension}"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: type
    default: Any
    help: str
    choices: tuple[str, ...] = ()
    multiline: bool = False

    @property
    def required(self) -> bool:
        return self.default is inspect.Parameter.empty


@dataclass
class ToolSpec:
    id: str
    version: str
    title: str
    description: str
    func: Callable[..., None] = field(repr=False)
    inputs: list[InputSpec]
    outputs: list[OutputSpec]
    params: list[ParamSpec]
    cpus: int = 1
    gpus: int = 0
    programs: tuple[str, ...] = ()
    source: str = ""  # "" for the platform's own tools, else the student source's name


REGISTRY: dict[str, ToolSpec] = {}

# A tool id, as written in @tool(id=...): lower case, digits and underscores.
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# The source whose modules are being imported right now (see load_tools); its
# name prefixes the ids of the tools they register, e.g. "jsmith.seq_stats".
_LOADING_SOURCE = ""

# Tool modules that failed to import: module name -> error message. They are
# left out so the rest of the platform keeps working, and listed on the home
# page and by `sussexbiotools tools` so the mistake is not hidden.
BROKEN: dict[str, str] = {}

_PARAM_TYPES = (str, int, float, bool)


def tool(
    *,
    id: str,
    version: str,
    title: str = "",
    cpus: int = 1,
    gpus: int = 0,
    programs: tuple[str, ...] = (),
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """Register a function as a tool."""

    def register(func: Callable[..., None]) -> Callable[..., None]:
        if not ID_RE.match(id):
            raise ValueError(f"tool id {id!r}: use lower-case letters, digits and underscores")
        full_id = f"{_LOADING_SOURCE}.{id}" if _LOADING_SOURCE else id
        if full_id in REGISTRY and REGISTRY[full_id].func is not func:
            raise ValueError(f"tool id {full_id!r} is already registered")
        inputs, outputs, params = _parse_signature(func)
        doc = inspect.getdoc(func) or ""
        REGISTRY[full_id] = ToolSpec(
            id=full_id,
            source=_LOADING_SOURCE,
            version=version,
            title=title or id,
            description=doc,
            func=func,
            inputs=inputs,
            outputs=outputs,
            params=params,
            cpus=cpus,
            gpus=gpus,
            programs=programs,
        )
        return func

    return register


def _parse_signature(
    func: Callable[..., None],
) -> tuple[list[InputSpec], list[OutputSpec], list[ParamSpec]]:
    hints = typing.get_type_hints(func, include_extras=True)
    inputs: list[InputSpec] = []
    outputs: list[OutputSpec] = []
    params: list[ParamSpec] = []
    for name, p in inspect.signature(func).parameters.items():
        hint = hints.get(name)
        base, meta = hint, None
        if get_origin(hint) is Annotated:
            base, *extras = get_args(hint)
            meta = next((m for m in extras if isinstance(m, (In, Out, Param))), None)
        if isinstance(meta, In):
            inputs.append(InputSpec(name, meta.format, meta.help))
        elif isinstance(meta, Out):
            outputs.append(OutputSpec(name, meta.format, meta.help))
        else:
            help_, multiline = (meta.help, meta.multiline) if meta else ("", False)
            if get_origin(base) is Literal:
                choices = tuple(str(c) for c in get_args(base))
                params.append(ParamSpec(name, str, p.default, help_, choices=choices))
            elif base in _PARAM_TYPES:
                params.append(ParamSpec(name, base, p.default, help_, multiline=multiline))
            else:
                raise TypeError(
                    f"{func.__name__}: parameter {name!r} needs an In, Out or "
                    f"Param annotation with type str, int, float, bool or Literal"
                )
    if not outputs:
        raise TypeError(f"{func.__name__}: a tool must declare at least one Out")
    return inputs, outputs, params


def coerce(spec: ParamSpec, value: Any) -> Any:
    """Convert a raw value from the CLI or a web form to the parameter's type."""
    if value is None or value == "":
        if spec.required:
            raise ValueError(f"{spec.name} is required")
        return spec.default
    if spec.choices:
        if str(value) not in spec.choices:
            raise ValueError(f"{spec.name} must be one of {', '.join(spec.choices)}")
        return str(value)
    if spec.type is bool:
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}
    return spec.type(value)


def tools_file() -> Path:
    """``tools.yaml`` at the top of the repository, unless SUSSEXBIOTOOLS_TOOLS_FILE says otherwise."""
    default = Path(__file__).resolve().parents[2] / "tools.yaml"
    return Path(os.environ.get("SUSSEXBIOTOOLS_TOOLS_FILE", default))


def display_order() -> list[str]:
    """Tool ids in the order listed in tools.yaml; an unreadable file means no set order."""
    path = tools_file()
    try:
        data = yaml.safe_load(path.read_text()) or {}
        order = data.get("order") or []
        if not isinstance(order, list) or not all(isinstance(t, str) for t in order):
            raise ValueError("'order' must be a list of tool ids")
    except FileNotFoundError:
        return []
    except (yaml.YAMLError, ValueError, AttributeError) as e:
        log.warning("ignoring %s: %s", path, e)
        return []
    return order


def tool_dirs() -> list[tuple[str, Path]]:
    """Extra folders of tools, as (source name, folder), besides the platform's own.

    On the server, SUSSEXBIOTOOLS_TOOL_DIRS lists each approved student source
    as ``name=/path/to/its/tools``, separated by ``;``. A folder without a
    name (``=/path`` or just ``/path``) loads with plain ids, as a student's
    own tools do on their machine (the toolkit sets that up by default).
    """
    raw = os.environ.get("SUSSEXBIOTOOLS_TOOL_DIRS")
    if raw is None:
        try:
            from ._toolkit import DEFAULT_TOOL_DIRS  # only in the students' toolkit
        except ImportError:
            return []
        raw = DEFAULT_TOOL_DIRS
    dirs = []
    for entry in filter(None, (e.strip() for e in raw.split(";"))):
        name, _, path = entry.rpartition("=")
        if name and not ID_RE.match(name):
            raise ValueError(f"SUSSEXBIOTOOLS_TOOL_DIRS: bad source name {name!r}")
        dirs.append((name, Path(path)))
    return dirs


def _source_package(name: str, folder: Path) -> str:
    """A package standing for one source's tools folder, so its modules import normally."""
    pkg_name = f"_sbt_source_{name or 'local'}"
    pkg = sys.modules.get(pkg_name)
    if pkg is None or list(pkg.__path__) != [str(folder)]:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(folder)]
        sys.modules[pkg_name] = pkg
    return pkg_name


def _import_tool_module(module: str, label: str, source: str = "") -> None:
    """Import one tool module; on any error, record it in BROKEN and carry on."""
    global _LOADING_SOURCE
    _LOADING_SOURCE = source
    try:
        importlib.import_module(module)
        BROKEN.pop(label, None)
    except Exception as e:  # any mistake in one tool file, from a typo to a bad annotation
        if label not in BROKEN:
            log.exception("tool module %s failed to load and is left out", label)
        BROKEN[label] = f"{type(e).__name__}: {e}"
    finally:
        _LOADING_SOURCE = ""


def load_tools() -> dict[str, ToolSpec]:
    """Every tool, in the order set by tools.yaml; unlisted tools follow, by title.

    Loads the platform's own tools, then each folder from tool_dirs(). The
    order file is read on each call, so a change shows on the next page load.
    """
    from . import tools

    present = set()
    for mod in pkgutil.iter_modules(tools.__path__):
        label = f"tools/{mod.name}.py"
        present.add(label)
        _import_tool_module(f"{tools.__name__}.{mod.name}", label)
    for source, folder in tool_dirs():
        pkg = _source_package(source, folder)
        for mod in pkgutil.iter_modules([str(folder)]):
            label = f"{source + '/' if source else ''}tools/{mod.name}.py"
            present.add(label)
            _import_tool_module(f"{pkg}.{mod.name}", label, source)
    for gone in set(BROKEN) - present:  # a broken file since deleted or renamed
        del BROKEN[gone]
    order = display_order()
    for unknown in sorted(set(order) - set(REGISTRY)):
        log.warning("%s lists %r, but there is no tool with that id", tools_file(), unknown)
    rank = {tool_id: i for i, tool_id in enumerate(order)}
    return dict(
        sorted(REGISTRY.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[1].title.lower()))
    )


def get_tool(tool_id: str) -> ToolSpec:
    load_tools()
    try:
        return REGISTRY[tool_id]
    except KeyError:
        raise KeyError(f"no tool called {tool_id!r}") from None


def tools_accepting(fmt: Format) -> list[tuple[ToolSpec, InputSpec]]:
    """Tools with an input of this format, for "use as input to..." menus."""
    return [(t, i) for t in load_tools().values() for i in t.inputs if i.format == fmt]
