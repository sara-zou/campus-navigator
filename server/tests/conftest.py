import csv
import shutil
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "tiny-campus"


@pytest.fixture
def tiny_campus():
    """Path to the untouched tiny-campus fixture. Read-only: don't write to it."""
    return FIXTURE


@pytest.fixture
def broken_campus(tmp_path):
    """Copy the fixture into tmp_path and apply one edit to one file.

    `edit` gets the file as a list of rows (rows[0] is the header, so rows[i]
    is line i+1 of the file) and returns the edited rows.

        campus_dir = broken_campus("edges.csv", lambda rows: rows + [["w1", "w1", "1", "meters", "footway", "True"]])
    """
    def make(file, edit):
        campus_dir = tmp_path / FIXTURE.name
        shutil.copytree(FIXTURE, campus_dir)
        path = campus_dir / file
        with path.open(newline="") as f:
            rows = list(csv.reader(f))
        with path.open("w", newline="") as f:
            csv.writer(f).writerows(edit(rows))
        return campus_dir
    return make
