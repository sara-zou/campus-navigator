from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import DATA_ENV_VAR, DEFAULT_DATA_ROOT, create_app, resolve_data_root
from conftest import copy_campus
from loader import LoadError


@pytest.fixture
def data_root(tmp_path, tiny_campus):
    """A data folder holding one copy of tiny-campus."""
    copy_campus(tiny_campus, tmp_path, "tiny-campus")
    return tmp_path


def get(root, url):
    return TestClient(create_app(root)).get(url)


# --- data root ---

def test_data_root_argument_beats_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv(DATA_ENV_VAR, "/from/env")
    assert resolve_data_root(tmp_path) == tmp_path


def test_data_root_from_env_var(monkeypatch):
    monkeypatch.setenv(DATA_ENV_VAR, "/from/env")
    assert str(resolve_data_root()) == "/from/env"


def test_data_root_default_is_repo_data(monkeypatch):
    monkeypatch.delenv(DATA_ENV_VAR, raising=False)
    assert resolve_data_root() == DEFAULT_DATA_ROOT
    assert DEFAULT_DATA_ROOT == Path(__file__).resolve().parents[2] / "data"


def test_create_app_uses_env_var(monkeypatch, data_root):
    monkeypatch.setenv(DATA_ENV_VAR, str(data_root))
    res = TestClient(create_app()).get("/campuses")
    assert [c["id"] for c in res.json()] == ["tiny-campus"]


# --- startup ---

def test_create_app_raises_on_bad_campus(broken_campus):
    campus_dir = broken_campus("nodes.csv", lambda rows: rows + [["w1"] + rows[3][1:]])  # duplicate node id
    with pytest.raises(LoadError):
        create_app(campus_dir.parent)


def test_create_app_raises_on_missing_data_folder(tmp_path):
    with pytest.raises(LoadError, match="data folder not found"):
        create_app(tmp_path / "nope")


# --- GET /campuses ---

def test_campuses_lists_id_and_bounds(data_root):
    res = get(data_root, "/campuses")
    assert res.status_code == 200
    assert res.json() == [{"id": "tiny-campus", "bounds": [[42.0005, -71.0050], [42.0055, -71.0005]]}]


def test_campuses_multiple_sorted(tmp_path, tiny_campus):
    copy_campus(tiny_campus, tmp_path, "tiny-campus")
    copy_campus(tiny_campus, tmp_path, "second-campus")
    res = get(tmp_path, "/campuses")
    assert [c["id"] for c in res.json()] == ["second-campus", "tiny-campus"]
