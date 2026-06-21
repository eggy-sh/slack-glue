"""Unit tests for the deterministic intent schema and validator.

The schema module is the sole authority on what a valid query is. These tests
pin accept-vs-reject behavior, normalization (int coercion, tag lowercasing /
dedup / order preservation), and the per-type rules of ``coerce_field_value``.
No model, no network — pure data in, structured issues out, never raises.
"""

from __future__ import annotations

import pytest

from slack_glue.schema import (
    ENDPOINTS,
    FIELD_TYPES,
    IntentQuery,
    ValidationIssue,
    coerce_field_value,
    validate_intent,
)


def test_endpoints_and_field_types_are_consistent() -> None:
    # Every endpoint with a field map is a known endpoint, and vice versa.
    assert set(ENDPOINTS) == set(FIELD_TYPES)


# --- validate_intent: happy paths ------------------------------------------


def test_valid_shots_query_normalizes_reel_and_tags() -> None:
    payload = {
        "endpoint": "/api/v1/shots",
        "filters": {
            "status": "approved",
            "dept": "vfx",
            "reel": "3",  # string digits -> int
            "tags": ["GreenScreen", "hero", "greenscreen", "hero"],  # dedup + lowercase
        },
    }
    query, issues = validate_intent(payload)
    assert issues == []
    assert isinstance(query, IntentQuery)
    assert query.endpoint == "/api/v1/shots"
    assert query.filters["reel"] == 3
    assert isinstance(query.filters["reel"], int)
    # Order preserved, lowercased, de-duplicated.
    assert query.filters["tags"] == ["greenscreen", "hero"]
    assert query.filters["status"] == "approved"
    assert query.filters["dept"] == "vfx"


def test_valid_assets_query() -> None:
    payload = {
        "endpoint": "/api/v1/assets",
        "filters": {"status": "final", "asset_type": "character", "tags": ["hero"]},
    }
    query, issues = validate_intent(payload)
    assert issues == []
    assert query is not None
    assert query.endpoint == "/api/v1/assets"
    assert query.filters == {"status": "final", "asset_type": "character", "tags": ["hero"]}


def test_empty_filters_is_valid() -> None:
    query, issues = validate_intent({"endpoint": "/api/v1/shots", "filters": {}})
    assert issues == []
    assert query is not None
    assert query.filters == {}


def test_missing_filters_key_defaults_to_empty() -> None:
    query, issues = validate_intent({"endpoint": "/api/v1/shots"})
    assert issues == []
    assert query is not None
    assert query.filters == {}


def test_as_dict_round_trips() -> None:
    query, _ = validate_intent(
        {"endpoint": "/api/v1/shots", "filters": {"reel": "2", "tags": ["a"]}}
    )
    assert query is not None
    assert query.as_dict() == {
        "endpoint": "/api/v1/shots",
        "filters": {"reel": 2, "tags": ["a"]},
    }


def test_integer_reel_passes_through() -> None:
    query, issues = validate_intent({"endpoint": "/api/v1/shots", "filters": {"reel": 4}})
    assert issues == []
    assert query is not None
    assert query.filters["reel"] == 4


# --- validate_intent: rejection paths --------------------------------------


def test_unknown_endpoint() -> None:
    query, issues = validate_intent({"endpoint": "/api/v1/widgets", "filters": {}})
    assert query is None
    assert [i.code for i in issues] == ["unknown_endpoint"]
    assert issues[0].field == "endpoint"


def test_missing_endpoint() -> None:
    query, issues = validate_intent({"filters": {"status": "approved"}})
    assert query is None
    assert [i.code for i in issues] == ["missing_endpoint"]


def test_empty_endpoint_string() -> None:
    query, issues = validate_intent({"endpoint": "", "filters": {}})
    assert query is None
    assert issues[0].code == "missing_endpoint"


def test_unknown_field() -> None:
    query, issues = validate_intent({"endpoint": "/api/v1/shots", "filters": {"frame_rate": "24"}})
    assert query is None
    assert [i.code for i in issues] == ["unknown_field"]
    assert issues[0].field == "frame_rate"


def test_field_valid_for_other_endpoint_is_unknown_here() -> None:
    # asset_type is a valid /assets field but unknown for /shots.
    query, issues = validate_intent(
        {"endpoint": "/api/v1/shots", "filters": {"asset_type": "character"}}
    )
    assert query is None
    assert issues[0].code == "unknown_field"
    assert issues[0].field == "asset_type"


def test_bad_type_reel_non_numeric() -> None:
    query, issues = validate_intent({"endpoint": "/api/v1/shots", "filters": {"reel": "abc"}})
    assert query is None
    assert [i.code for i in issues] == ["bad_type"]
    assert issues[0].field == "reel"


def test_bad_enum_status() -> None:
    query, issues = validate_intent(
        {"endpoint": "/api/v1/shots", "filters": {"status": "greenlit"}}
    )
    assert query is None
    assert [i.code for i in issues] == ["bad_enum"]
    assert issues[0].field == "status"


def test_multiple_issues_collected() -> None:
    query, issues = validate_intent(
        {
            "endpoint": "/api/v1/shots",
            "filters": {"status": "greenlit", "reel": "x", "bogus": "1"},
        }
    )
    assert query is None
    codes = {i.code for i in issues}
    assert codes == {"bad_enum", "bad_type", "unknown_field"}


# --- validate_intent: never raises on bad shapes ---------------------------


@pytest.mark.parametrize("payload", [None, 42, "a string", [1, 2, 3], 3.14])
def test_non_dict_payload_returns_issue_not_raise(payload: object) -> None:
    query, issues = validate_intent(payload)
    assert query is None
    assert [i.code for i in issues] == ["bad_shape"]


def test_non_dict_filters_returns_issue() -> None:
    query, issues = validate_intent({"endpoint": "/api/v1/shots", "filters": [1, 2]})
    assert query is None
    assert issues[0].code == "bad_shape"
    assert issues[0].field == "filters"


def test_null_filters_treated_as_empty() -> None:
    query, issues = validate_intent({"endpoint": "/api/v1/shots", "filters": None})
    assert issues == []
    assert query is not None
    assert query.filters == {}


# --- coerce_field_value: table-driven --------------------------------------


@pytest.mark.parametrize(
    ("field_type", "raw", "expected"),
    [
        ("int", "3", 3),
        ("int", 5, 5),
        ("int", "  7  ", 7),
        ("str", "RDR", "RDR"),
        ("str", "  ALY  ", "ALY"),
        ("str_list", "greenscreen", ["greenscreen"]),
        ("str_list", ["A", "a", "B"], ["a", "b"]),
        ("str_list", ["x", "", "y"], ["x", "y"]),
        ("enum:approved|final", "approved", "approved"),
        ("enum:approved|final", " final ", "final"),
    ],
)
def test_coerce_field_value_success(field_type: str, raw: object, expected: object) -> None:
    value, reason = coerce_field_value(field_type, raw)
    assert reason is None
    assert value == expected


@pytest.mark.parametrize(
    ("field_type", "raw"),
    [
        ("int", "abc"),
        ("int", True),  # bool rejected even though it's an int subclass
        ("int", 3.5),
        ("int", None),
        ("str", 123),
        ("str", "   "),
        ("str_list", 5),
        ("str_list", [1, 2]),
        ("str_list", ["", "  "]),  # all-blank -> no usable tag
        ("enum:approved|final", "greenlit"),
        ("enum:approved|final", 7),
        ("totally-unknown-type", "x"),
    ],
)
def test_coerce_field_value_failure(field_type: str, raw: object) -> None:
    value, reason = coerce_field_value(field_type, raw)
    assert value is None
    assert isinstance(reason, str) and reason


def test_validation_issue_is_frozen() -> None:
    issue = ValidationIssue(code="bad_type", field="reel", message="nope")
    with pytest.raises((AttributeError, Exception)):
        issue.code = "other"  # type: ignore[misc]


def test_intent_query_is_frozen() -> None:
    query = IntentQuery(endpoint="/api/v1/shots", filters={})
    with pytest.raises((AttributeError, Exception)):
        query.endpoint = "/api/v1/assets"  # type: ignore[misc]
