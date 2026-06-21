"""Golden tests for the deterministic Slack / JSON formatters.

The deterministic core owns all wording, counts, truncation, and field layout —
the model never writes a summary. These tests pin exact strings (golden) and the
stable JSON shape so any drift is caught.
"""

from __future__ import annotations

from slack_glue.database import QueryResult
from slack_glue.formatting import (
    SLACK_RECORD_LIMIT,
    format_clarification,
    format_records_json,
    format_records_slack,
    format_validation_error,
)
from slack_glue.schema import ValidationIssue


def _result(records, *, endpoint="/api/v1/shots", filters=None, total=10) -> QueryResult:
    return QueryResult(
        endpoint=endpoint,
        filters=filters if filters is not None else {},
        records=records,
        total_scanned=total,
    )


def test_format_records_slack_multi_record_golden() -> None:
    records = [
        {
            "id": "SHOT-0101",
            "status": "approved",
            "reel": 3,
            "dept": "vfx",
            "tags": ["greenscreen", "hero"],
        },
        {
            "id": "SHOT-0102",
            "status": "approved",
            "reel": 3,
            "dept": "vfx",
            "tags": ["greenscreen", "crowd"],
        },
    ]
    result = _result(
        records, filters={"status": "approved", "reel": 3, "dept": "vfx", "tags": ["greenscreen"]}
    )
    text = format_records_slack(result)
    expected = (
        "Found 2 records on /api/v1/shots "
        "(dept=vfx, reel=3, status=approved, tags=[greenscreen]):\n"
        "• SHOT-0101 — status=approved, reel=3, dept=vfx, tags=[greenscreen, hero]\n"
        "• SHOT-0102 — status=approved, reel=3, dept=vfx, tags=[greenscreen, crowd]"
    )
    assert text == expected


def test_format_records_slack_singular_noun() -> None:
    result = _result([{"id": "SHOT-0101", "status": "approved"}], filters={"status": "approved"})
    text = format_records_slack(result)
    assert text.startswith("Found 1 record on /api/v1/shots")


def test_format_records_slack_truncates_with_more_footer() -> None:
    records = [{"id": f"SHOT-{i:04d}"} for i in range(SLACK_RECORD_LIMIT + 3)]
    result = _result(records, total=SLACK_RECORD_LIMIT + 3)
    text = format_records_slack(result)
    lines = text.splitlines()
    # 1 header + SLACK_RECORD_LIMIT bullets + 1 "more" footer.
    assert len(lines) == 1 + SLACK_RECORD_LIMIT + 1
    assert lines[-1] == "…and 3 more."
    assert lines[0].startswith(f"Found {SLACK_RECORD_LIMIT + 3} records")


def test_format_records_slack_custom_limit() -> None:
    records = [{"id": f"SHOT-{i:04d}"} for i in range(5)]
    result = _result(records, total=5)
    text = format_records_slack(result, limit=2)
    assert "…and 3 more." in text


def test_format_records_slack_zero_match_lists_filters() -> None:
    result = _result([], filters={"status": "approved", "reel": 1, "dept": "vfx"}, total=10)
    text = format_records_slack(result)
    assert text == (
        "No records matched on /api/v1/shots (dept=vfx, reel=1, status=approved). Scanned 10."
    )


def test_format_records_slack_zero_match_no_filters() -> None:
    result = _result([], filters={}, total=10)
    text = format_records_slack(result)
    assert "no filters" in text


def test_format_records_json_stable_shape() -> None:
    records = [{"id": "SHOT-0101", "status": "approved", "tags": ["greenscreen"]}]
    result = _result(records, filters={"status": "approved"})
    payload = format_records_json(result)
    assert payload == {
        "endpoint": "/api/v1/shots",
        "filters": {"status": "approved"},
        "count": 1,
        "records": [{"id": "SHOT-0101", "status": "approved", "tags": ["greenscreen"]}],
    }
    # No total_scanned in the formatter contract (that's QueryResult.as_dict).
    assert "total_scanned" not in payload


def test_format_records_json_is_a_copy() -> None:
    records = [{"id": "SHOT-0101"}]
    result = _result(records)
    payload = format_records_json(result)
    payload["records"][0]["id"] = "MUTATED"
    assert records[0]["id"] == "SHOT-0101"


def test_format_validation_error_lists_issues_in_order() -> None:
    issues = [
        ValidationIssue(code="bad_enum", field="status", message="status: 'greenlit' is not valid"),
        ValidationIssue(
            code="unknown_field", field="frame_rate", message="unknown filter 'frame_rate'"
        ),
    ]
    text = format_validation_error(issues)
    lines = text.splitlines()
    assert lines[0] == "I couldn't turn that into a valid query:"
    assert lines[1] == "• [status] status: 'greenlit' is not valid"
    assert lines[2] == "• [frame_rate] unknown filter 'frame_rate'"


def test_format_validation_error_whole_query_issue_has_no_field_prefix() -> None:
    issues = [ValidationIssue(code="no_query", field="", message="no query emitted")]
    text = format_validation_error(issues)
    assert text.splitlines()[1] == "• no query emitted"


def test_format_validation_error_empty_is_valid_message() -> None:
    assert format_validation_error([]) == "The request is valid."


def test_format_clarification_includes_request_and_issues() -> None:
    issues = [
        ValidationIssue(code="unknown_endpoint", field="endpoint", message="unknown endpoint")
    ]
    text = format_clarification(issues, "get me the widgets")
    assert "get me the widgets" in text
    assert "• [endpoint] unknown endpoint" in text
    assert text.endswith("Could you rephrase or specify a known endpoint/field/value?")


def test_format_clarification_order_stable() -> None:
    issues = [
        ValidationIssue(code="a", field="f1", message="m1"),
        ValidationIssue(code="b", field="f2", message="m2"),
    ]
    first = format_clarification(issues, "req")
    second = format_clarification(issues, "req")
    assert first == second
    assert first.index("m1") < first.index("m2")
