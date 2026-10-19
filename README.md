# My sussexbiotools tools

Your own tools for the lab's sussexbiotools platform. Write them here, test
them on your own machine, push, and once Tony has approved a commit your
tools appear on the lab's site as `<your name>.<tool id>`.

The full guide is **Writing sussexbiotools Tools** (ask Tony for the link).

## Start

```bash
uv sync                                   # install everything, exactly as locked
uv run pytest                             # the example's tests should pass
uv run sussexbiotools tools               # lists the tools in tools/
uv run sussexbiotools run sequence_lengths --sequences some.fasta
uv run sussexbiotools runs                # your runs (in runs/, ignored by git)
```

## Where things go

| | |
|---|---|
| `tools/` | Your tools: one file (or folder) per tool. `sequence_lengths.py` is an example to copy. |
| `tests/` | Tests for your tools. Every tool needs them. |
| `src/sussexbiotools/` | The toolkit: a copy of the platform's tool contract. **Do not edit**; it is replaced when the platform changes. |

Import everything a tool needs from the toolkit:

```python
from sussexbiotools import FASTA, TSV, In, Out, Param, ToolError, tool
```

## Getting a tool onto the site

1. `uv run pytest` passes on your machine.
2. Push. GitHub runs the same tests (the Actions tab, or the tick on your commit).
3. Tell Tony the commit you want live. He reviews it and approves it; a few
   minutes later it is on the site, or the site's footer says why not.
