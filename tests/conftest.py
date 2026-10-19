"""Shared test helpers. Every test gets its own empty runs folder."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def runs_tmp(tmp_path, monkeypatch) -> Path:
    """Runs made by a test go in a throw-away folder, not your real runs/."""
    path = tmp_path / "runs"
    monkeypatch.setenv("SUSSEXBIOTOOLS_RUNS", str(path))
    return path


@pytest.fixture
def fasta(tmp_path) -> Path:
    """A small FASTA file: two short protein sequences."""
    path = tmp_path / "two.fasta"
    path.write_text(">short\nMKTAYIAK\n>longer\nMVLSPADKTNVKAAWGKVGA\n")
    return path
