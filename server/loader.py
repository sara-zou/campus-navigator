"""Load every data/{campus_id}/ folder into an in-memory Campus, validating as it goes.

One pass per file: read a row, check it, convert it, store it. Any bad row raises
LoadError naming the file and row; a campus is only built once all its files pass.
"""
import csv
import math
from pathlib import Path


class LoadError(Exception):
    """A data file broke the contract. `row` is the line number (header = 1), or None for file-level errors."""

    def __init__(self, file, row, msg):
        self.file, self.row, self.msg = file, row, msg
        where = file if row is None else f"{file}:{row}"
        super().__init__(f"{where}: {msg}")


# --- row helpers ---

def read_rows(path, required_cols):
    """Yield (row_num, row_dict) for each data row, with every cell trimmed.

    Raises if the file is missing, the header lacks a required column, or a row
    has the wrong number of cells. Extra columns are allowed and ignored.
    """
    path = Path(path)
    file = path.name
    if not path.is_file():
        raise LoadError(file, None, "file not found")

    # utf-8-sig drops the BOM that Excel adds when saving CSVs
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader, [])]
        missing = [c for c in required_cols if c not in header]
        if missing:
            raise LoadError(file, None, f"missing columns: {', '.join(missing)}")

        for row_num, cells in enumerate(reader, start=2):
            if not cells:  # blank line, e.g. a trailing newline
                continue
            if len(cells) != len(header):
                raise LoadError(file, row_num, f"expected {len(header)} cells, got {len(cells)}")
            yield row_num, {col: cell.strip() for col, cell in zip(header, cells)}


def to_float(val, file, row, col):
    try:
        x = float(val)
    except ValueError:
        raise LoadError(file, row, f"{col} must be a number, got {val!r}") from None
    if not math.isfinite(x):
        raise LoadError(file, row, f"{col} must be a finite number, got {val!r}")
    return x


def to_int(val, file, row, col):
    try:
        return int(val)
    except ValueError:
        raise LoadError(file, row, f"{col} must be an integer, got {val!r}") from None


def to_bool_or_none(val, file, row, col):
    """'True' -> True, 'False' -> False, '' -> None (unknown). Anything else raises."""
    if val == "True":
        return True
    if val == "False":
        return False
    if val == "":
        return None
    raise LoadError(file, row, f"{col} must be True, False, or empty, got {val!r}")


def check_one_of(val, allowed, file, row, col):
    if val not in allowed:
        raise LoadError(file, row, f"{col} must be one of {sorted(allowed)}, got {val!r}")
    return val
