# Copied from the sussexbiotools platform at commit af50b68. Do not edit.
"""Run the lab's bioinformatics tools from the command line or a web page.

What a tool needs, importable in one line:

    from sussexbiotools import ALIGNMENT, FASTA, HTML, PDB, TSV, In, Out, Param, ToolError, tool
"""

__version__ = "0.1.0"

from .formats import ALIGNMENT, FASTA, HTML, PDB, TSV, Format, FormatError  # noqa: E402
from .registry import In, Out, Param, ToolError, tool  # noqa: E402

__all__ = [
    "ALIGNMENT",
    "FASTA",
    "HTML",
    "PDB",
    "TSV",
    "Format",
    "FormatError",
    "In",
    "Out",
    "Param",
    "ToolError",
    "tool",
]
