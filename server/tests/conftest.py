import csv
import shutil
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "tiny-campus"
# One building "hq", two floors: south door e1 (floor 0, accessible) and north door e2 (floor 1,
# up a hill, accessible=False); stairs s0-s1 (15 s, steps) and elevator l0-l1 (35 s); room r101 on
# floor 1. Outdoor sidewalk o1-o2-o3-o4 joins the two doors' connectors.
INDOOR_FIXTURE = Path(__file__).parent / "fixtures" / "tiny-indoor"


@pytest.fixture
def tiny_campus():
    """Path to the untouched tiny-campus fixture. Read-only: don't write to it."""
    return FIXTURE


@pytest.fixture
def tiny_indoor():
    """Path to the untouched tiny-indoor fixture. Read-only: don't write to it."""
    return INDOOR_FIXTURE


@pytest.fixture
def broken_campus(tmp_path):
    """Copy the fixture into tmp_path and apply one edit to one file.

    `edit` gets the file as a list of rows (rows[0] is the header, so rows[i]
    is line i+1 of the file) and returns the edited rows.

        campus_dir = broken_campus("edges.csv", lambda rows: rows + [["w1", "w1", "1", "meters", "footway", "True"]])

    `fixture` picks the campus to copy (default tiny-campus; pass INDOOR_FIXTURE for tiny-indoor).
    """
    def make(file, edit, fixture=FIXTURE):
        campus_dir = tmp_path / fixture.name
        shutil.copytree(fixture, campus_dir)
        path = campus_dir / file
        with path.open(newline="") as f:
            rows = list(csv.reader(f))
        with path.open("w", newline="") as f:
            csv.writer(f).writerows(edit(rows))
        return campus_dir
    return make


def copy_campus(src, dest_root, campus_id):
    """Copy a campus folder under a new id, rewriting nodes.csv's campus_id to match."""
    dest = dest_root / campus_id
    shutil.copytree(src, dest)
    text = (dest / "nodes.csv").read_text().replace(f",{src.name},", f",{campus_id},")
    (dest / "nodes.csv").write_text(text)
    return dest
