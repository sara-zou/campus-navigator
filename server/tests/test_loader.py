import pytest

from loader import LoadError, check_one_of, read_rows, to_bool_or_none, to_float, to_int

BUILDING_COLS = ["building_id", "name", "polygon_geojson"]


# --- LoadError ---

def test_load_error_format_with_row():
    assert str(LoadError("edges.csv", 5, "bad cost")) == "edges.csv:5: bad cost"


def test_load_error_format_without_row():
    assert str(LoadError("edges.csv", None, "file not found")) == "edges.csv: file not found"


# --- read_rows ---

def test_read_rows_yields_line_numbers_from_2(tiny_campus):
    rows = list(read_rows(tiny_campus / "buildings.csv", BUILDING_COLS))
    assert [n for n, _ in rows] == [2, 3]
    assert rows[0][1]["building_id"] == "bA"


def test_read_rows_missing_file(tmp_path):
    with pytest.raises(LoadError, match="buildings.csv: file not found"):
        list(read_rows(tmp_path / "buildings.csv", BUILDING_COLS))


def test_read_rows_missing_column_names_file_and_column(broken_campus):
    campus_dir = broken_campus("buildings.csv", lambda rows: [r[1:] for r in rows])
    with pytest.raises(LoadError, match="buildings.csv: missing columns: building_id"):
        list(read_rows(campus_dir / "buildings.csv", BUILDING_COLS))


def test_read_rows_extra_column_is_ignored(broken_campus):
    campus_dir = broken_campus("buildings.csv", lambda rows: [r + ["extra"] for r in rows])
    rows = list(read_rows(campus_dir / "buildings.csv", BUILDING_COLS))
    assert len(rows) == 2


def test_read_rows_short_row_raises_with_line_number(broken_campus):
    def drop_last_cell_of_line_3(rows):
        rows[2] = rows[2][:-1]
        return rows

    campus_dir = broken_campus("buildings.csv", drop_last_cell_of_line_3)
    with pytest.raises(LoadError, match="buildings.csv:3: expected 3 cells, got 2"):
        list(read_rows(campus_dir / "buildings.csv", BUILDING_COLS))


def test_read_rows_trims_cells(broken_campus):
    campus_dir = broken_campus("buildings.csv", lambda rows: [[f"  {c} " for c in r] for r in rows])
    _, row = next(read_rows(campus_dir / "buildings.csv", BUILDING_COLS))
    assert row["building_id"] == "bA"
    assert row["name"] == "Building A"


# --- converters ---

def test_to_float_valid():
    assert to_float("6.36", "f.csv", 2, "cost") == 6.36


@pytest.mark.parametrize("val", ["", "abc", "nan", "inf"])
def test_to_float_invalid(val):
    with pytest.raises(LoadError, match="f.csv:2: cost"):
        to_float(val, "f.csv", 2, "cost")


def test_to_int_valid():
    assert to_int("0", "f.csv", 2, "floor") == 0


@pytest.mark.parametrize("val", ["", "1.5", "abc"])
def test_to_int_invalid(val):
    with pytest.raises(LoadError, match="f.csv:2: floor"):
        to_int(val, "f.csv", 2, "floor")


@pytest.mark.parametrize("val, expected", [("True", True), ("False", False), ("", None)])
def test_to_bool_or_none_valid(val, expected):
    assert to_bool_or_none(val, "f.csv", 2, "accessible") is expected


@pytest.mark.parametrize("val", ["true", "false", "yes", "1", "0", "Ture"])
def test_to_bool_or_none_invalid(val):
    with pytest.raises(LoadError, match="f.csv:2: accessible"):
        to_bool_or_none(val, "f.csv", 2, "accessible")


def test_check_one_of_valid():
    assert check_one_of("meters", {"meters"}, "f.csv", 2, "cost_unit") == "meters"


def test_check_one_of_invalid_lists_allowed_values():
    with pytest.raises(LoadError, match=r"cost_unit must be one of \['meters'\], got 'feet'"):
        check_one_of("feet", {"meters"}, "f.csv", 2, "cost_unit")
