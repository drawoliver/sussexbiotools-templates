"""Count the sequences in a FASTA file and report each one's length.

A deliberately small example of a sussexbiotools tool. Copy it, rename it,
and replace the body with your own work. The parts every tool has:

- the @tool decorator, giving the tool a permanent id, a version and a title;
- typed arguments: input files (In), output files (Out), settings (Param);
- a docstring, shown as the tool's description on the website;
- clear reporting: print() goes to the run's log, ToolError stops the run
  with a message the user sees.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from Bio import SeqIO

from sussexbiotools import FASTA, TSV, In, Out, Param, ToolError, tool


@tool(id="sequence_lengths", version="0.1.0", title="Sequence lengths")
def sequence_lengths(
    sequences: Annotated[Path, In(FASTA, "Sequences to measure")],
    table: Annotated[Path, Out(TSV, "One row per sequence: its id and length")],
    min_length: Annotated[int, Param("Leave out sequences shorter than this")] = 0,
) -> None:
    """One row per sequence with its id and length, optionally leaving out short ones."""
    if min_length < 0:
        raise ToolError("min_length cannot be negative")

    kept = 0
    with table.open("w") as fh:
        fh.write("id\tlength\n")
        for rec in SeqIO.parse(sequences, "fasta"):
            if len(rec.seq) < min_length:
                print(f"{rec.id}: {len(rec.seq)} residues, shorter than {min_length}, left out")
                continue
            fh.write(f"{rec.id}\t{len(rec.seq)}\n")
            kept += 1
    print(f"{kept} sequences written")
