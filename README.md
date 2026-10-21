# My sussexbiotools tools

Your own tools for the lab's sussexbiotools platform. Write them here, test
them on your own machine, push, and once Tony has approved a commit your
tools appear on the lab's site as `<your name>.<tool id>`.

The full guide is **Writing sussexbiotools Tools** (ask Tony for the link).

## Start

Either work in your web browser, with nothing to install: on this
repository's page choose **Code > Codespaces > Create codespace on main**
and wait a few minutes the first time; everything below is already
installed. Or work on your own machine with `uv` and `git`. Either way:

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
| `.devcontainer/` | Sets up a codespace: the server's Python version, `uv`, and your locked packages. |

In a codespace, commit and push before you stop work: a codespace left
unused is deleted after 30 days, and anything not pushed goes with it.

Import everything a tool needs from the toolkit:

```python
from sussexbiotools import FASTA, TSV, In, Out, Param, ToolError, tool
```

## Setting up (once)

If you have just made this repository from the template:

1. Keep it named `sussexbiotools`, and private.
2. **Settings > Collaborators**: add `drawoliver`, so Tony can review it.
3. Send Tony your full name, Sussex email, GitHub username and this
   repository's address. He sends back your name on the site, a deploy key
   and, later, your personal sign-in link.
4. **Settings > Deploy keys > Add deploy key**: paste the key, title
   "sussexbiotools server", **Allow write access off**. The server can then
   read this repository and nothing else.

The guide's section 3 has the details.

## Getting a tool onto the site

1. `uv run pytest` passes on your machine.
2. Push to `main`. GitHub runs the same tests (the Actions tab, or the tick on your commit).
3. Ask Tony to approve your newest commit (or send its full id). He reviews
   it and approves that exact commit; a few minutes later it is on the site,
   or the site's footer says why not.

Pushing alone never changes the site: only an approved commit does.
