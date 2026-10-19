# Copied from the sussexbiotools platform at commit d2e18a9. Do not edit.
"""File formats that tool inputs and outputs declare.

Each format checks that a file really is what it claims to be and returns a
one-line summary for the web pages. The checks are deliberately strict: a
run stops before the tool starts if an input does not parse.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from Bio import AlignIO, SeqIO


class FormatError(ValueError):
    """A file does not match its declared format."""


@dataclass(frozen=True)
class Format:
    name: str
    label: str
    extension: str
    check: Callable[[Path], str] = field(repr=False, compare=False)

    def validate(self, path: Path) -> str:
        """Return a short summary of ``path``, or raise FormatError."""
        if not path.is_file():
            raise FormatError(f"{path.name}: file not found")
        if path.stat().st_size == 0:
            raise FormatError(f"{path.name}: file is empty")
        try:
            return self.check(path)
        except FormatError:
            raise
        except Exception as e:  # parser errors come in many types
            raise FormatError(f"{path.name}: not valid {self.label} ({e})") from e


def _fasta(path: Path) -> str:
    lengths = [len(r.seq) for r in SeqIO.parse(path, "fasta")]
    if not lengths:
        raise FormatError(f"{path.name}: no FASTA records")
    if any(n == 0 for n in lengths):
        raise FormatError(f"{path.name}: contains an empty sequence")
    span = f"{min(lengths)}" if min(lengths) == max(lengths) else f"{min(lengths)}-{max(lengths)}"
    return f"{len(lengths)} sequences, length {span}"


def _alignment(path: Path) -> str:
    aln = AlignIO.read(path, "fasta")  # raises if the rows differ in length
    if len(aln) < 2:
        raise FormatError(f"{path.name}: an alignment needs at least two sequences")
    return f"{len(aln)} sequences x {aln.get_alignment_length()} columns"


def _pdb(path: Path) -> str:
    atoms = 0
    chains: set[str] = set()
    with path.open() as fh:
        for line in fh:
            if line.startswith(("ATOM  ", "HETATM")):
                atoms += 1
                chains.add(line[21])
    if not atoms:
        raise FormatError(f"{path.name}: no ATOM or HETATM records")
    return f"{atoms} atoms, chains {''.join(sorted(chains))}"


def _tsv(path: Path) -> str:
    with path.open() as fh:
        header = fh.readline().rstrip("\n").split("\t")
        rows = sum(1 for line in fh if line.strip())
    return f"{rows} rows x {len(header)} columns"


def _html(path: Path) -> str:
    head = path.read_text(errors="replace")[:2000].lower()
    if "<html" not in head and "<!doctype html" not in head:
        raise FormatError(f"{path.name}: does not look like an HTML page")
    return f"HTML page, {path.stat().st_size // 1024} KB"


FASTA = Format("fasta", "FASTA sequences", ".fasta", _fasta)
ALIGNMENT = Format("alignment", "aligned FASTA", ".aln.fasta", _alignment)
PDB = Format("pdb", "PDB structure", ".pdb", _pdb)
TSV = Format("tsv", "tab-separated table", ".tsv", _tsv)
HTML = Format("html", "HTML page", ".html", _html)

FORMATS: dict[str, Format] = {f.name: f for f in (FASTA, ALIGNMENT, PDB, TSV, HTML)}
