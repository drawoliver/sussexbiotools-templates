"""Tests for the example tool. Run them with: uv run pytest"""

from sussexbiotools import runs
from sussexbiotools.registry import get_tool


def table_rows(runs_dir, run_id):
    lines = (runs_dir / run_id / "outputs" / "table.tsv").read_text().splitlines()
    return [line.split("\t") for line in lines[1:]]


def test_reports_every_sequence(fasta, runs_tmp):
    # Run the tool exactly as the platform does: make the run, then execute it.
    run_id = runs.create_run(get_tool("sequence_lengths"), {}, {"sequences": fasta})
    m = runs.execute(run_id)
    assert m["status"] == "succeeded", m["error"]
    assert table_rows(runs_tmp, run_id) == [["short", "8"], ["longer", "20"]]


def test_short_sequences_can_be_left_out(fasta, runs_tmp):
    run_id = runs.create_run(get_tool("sequence_lengths"), {"min_length": 10}, {"sequences": fasta})
    assert runs.execute(run_id)["status"] == "succeeded"
    assert table_rows(runs_tmp, run_id) == [["longer", "20"]]


def test_a_negative_setting_is_refused(fasta):
    run_id = runs.create_run(get_tool("sequence_lengths"), {"min_length": -1}, {"sequences": fasta})
    m = runs.execute(run_id)
    assert m["status"] == "failed" and "cannot be negative" in m["error"]
