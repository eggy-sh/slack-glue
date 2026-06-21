"""Unit tests for the deterministic mock-ShotGrid database + executor.

The fixture load, the grouping, and the scalar-equality + tag-superset filtering
are all plain code. These tests pin the byte-for-byte reproducible behavior the
acceptance criteria depend on (e.g. the canonical approved/vfx/reel-3/greenscreen
query returning exactly SHOT-0101 and SHOT-0102 in fixture order).
"""

from __future__ import annotations

import json

import pytest

from slack_glue.database import (
    FIXTURE_PATH,
    Database,
    QueryResult,
    execute_query,
    load_fixture,
    record_matches,
)
from slack_glue.schema import validate_intent


def _query(endpoint: str, **filters: object):
    query, issues = validate_intent({"endpoint": endpoint, "filters": filters})
    assert issues == [], issues
    assert query is not None
    return query


# --- load_fixture ----------------------------------------------------------


def test_load_default_fixture_groups_by_kind(db: Database) -> None:
    assert db.kinds() == ["asset", "shot"]
    assert len(db.all("shot")) == 10
    assert len(db.all("asset")) == 6


def test_all_unknown_kind_is_empty(db: Database) -> None:
    assert db.all("sequence") == []


def test_load_missing_path_raises_file_not_found(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_fixture(tmp_path / "does-not-exist.json")


def test_load_bad_shape_top_level_not_object(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_fixture(bad)


def test_load_bad_shape_kind_not_list(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"shot": {"id": "X"}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_fixture(bad)


def test_load_bad_shape_record_not_object(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"shot": ["not-an-object"]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_fixture(bad)


def test_fixture_path_points_at_packaged_json() -> None:
    assert FIXTURE_PATH.name == "shotgrid.json"
    assert FIXTURE_PATH.exists()


# --- execute_query: the canonical acceptance query -------------------------


def test_canonical_shot_query_returns_two_in_fixture_order(db: Database) -> None:
    query = _query("/api/v1/shots", status="approved", dept="vfx", reel=3, tags=["greenscreen"])
    result = execute_query(query, db)
    assert isinstance(result, QueryResult)
    assert [r["id"] for r in result.records] == ["SHOT-0101", "SHOT-0102"]
    assert result.count == 2
    assert result.total_scanned == 10
    assert result.endpoint == "/api/v1/shots"


def test_multi_tag_and_semantics(db: Database) -> None:
    # Requires BOTH tags; only SHOT-0101 has greenscreen AND hero.
    query = _query("/api/v1/shots", tags=["greenscreen", "hero"])
    result = execute_query(query, db)
    assert [r["id"] for r in result.records] == ["SHOT-0101"]


def test_tag_superset_record_may_have_extra_tags(db: Database) -> None:
    # Requesting just "hero" matches every record that *contains* hero.
    query = _query("/api/v1/shots", tags=["hero"])
    result = execute_query(query, db)
    assert [r["id"] for r in result.records] == ["SHOT-0101", "SHOT-0104"]


def test_scalar_equality_only(db: Database) -> None:
    query = _query("/api/v1/shots", reel=2)
    result = execute_query(query, db)
    assert [r["id"] for r in result.records] == ["SHOT-0201", "SHOT-0202", "SHOT-0203"]


def test_zero_match_sets_total_scanned(db: Database) -> None:
    query = _query("/api/v1/shots", status="approved", reel=1, dept="vfx")
    result = execute_query(query, db)
    assert result.records == []
    assert result.count == 0
    assert result.total_scanned == 10


def test_no_filters_returns_all_of_kind(db: Database) -> None:
    query = _query("/api/v1/shots")
    result = execute_query(query, db)
    assert result.count == 10
    assert result.total_scanned == 10


def test_asset_endpoint_resolves_to_asset_kind(db: Database) -> None:
    query = _query("/api/v1/assets", asset_type="character")
    result = execute_query(query, db)
    assert [r["id"] for r in result.records] == ["AST-HERO-01", "AST-HERO-02"]
    assert result.total_scanned == 6


def test_query_result_as_dict(db: Database) -> None:
    query = _query("/api/v1/shots", status="approved", dept="vfx", reel=3, tags=["greenscreen"])
    payload = execute_query(query, db).as_dict()
    assert payload["endpoint"] == "/api/v1/shots"
    assert payload["count"] == 2
    assert payload["total_scanned"] == 10
    assert payload["filters"] == {
        "status": "approved",
        "dept": "vfx",
        "reel": 3,
        "tags": ["greenscreen"],
    }
    assert [r["id"] for r in payload["records"]] == ["SHOT-0101", "SHOT-0102"]


# --- record_matches: per-predicate branches --------------------------------


def test_record_matches_scalar_true() -> None:
    record = {"id": "X", "status": "approved", "reel": 3}
    assert record_matches(record, {"status": "approved", "reel": 3}) is True


def test_record_matches_scalar_false() -> None:
    record = {"id": "X", "status": "approved", "reel": 3}
    assert record_matches(record, {"reel": 2}) is False


def test_record_matches_missing_scalar_field() -> None:
    assert record_matches({"id": "X"}, {"status": "approved"}) is False


def test_record_matches_tag_superset_true() -> None:
    record = {"id": "X", "tags": ["greenscreen", "hero", "crowd"]}
    assert record_matches(record, {"tags": ["greenscreen", "hero"]}) is True


def test_record_matches_tag_subset_false() -> None:
    record = {"id": "X", "tags": ["greenscreen"]}
    assert record_matches(record, {"tags": ["greenscreen", "hero"]}) is False


def test_record_matches_tags_missing_or_wrong_type() -> None:
    assert record_matches({"id": "X"}, {"tags": ["a"]}) is False
    assert record_matches({"id": "X", "tags": "notalist"}, {"tags": ["a"]}) is False


def test_record_matches_empty_filters_always_true() -> None:
    assert record_matches({"id": "X"}, {}) is True


def test_database_is_frozen(db: Database) -> None:
    with pytest.raises((AttributeError, Exception)):
        db.records = {}  # type: ignore[misc]
