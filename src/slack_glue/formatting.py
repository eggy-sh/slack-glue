"""DETERMINISTIC rendering of results into Slack text and JSON.

Every function here is pure string/JSON formatting — no model, no network. Given
the same query result the Slack reply and the JSON payload are byte-for-byte
reproducible, which is exactly what makes them golden-testable. The model is
never asked to "write a nice summary": the deterministic core owns the wording,
counts, and field layout.
"""

from __future__ import annotations

from typing import Any

from .database import QueryResult, Record
from .schema import ValidationIssue

#: Maximum records rendered inline in a Slack reply before a "+N more" footer.
SLACK_RECORD_LIMIT: int = 10

#: Fields shown per record bullet, in order. Only those present are rendered, so
#: shots and assets share one deterministic layout without special-casing.
_RECORD_FIELDS: tuple[str, ...] = (
    "status",
    "reel",
    "dept",
    "asset_type",
    "sequence",
    "tags",
)


def _format_filters(filters: dict[str, Any]) -> str:
    """Render a filters dict as a stable, human-readable clause string."""
    if not filters:
        return "no filters"
    parts: list[str] = []
    for key in sorted(filters):
        value = filters[key]
        if isinstance(value, list):
            rendered = ", ".join(str(v) for v in value)
            parts.append(f"{key}=[{rendered}]")
        else:
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def _format_record_line(record: Record) -> str:
    """Render one record as a Slack bullet: ``• ID — k=v, k=v``."""
    rid = record.get("id", "<no-id>")
    details: list[str] = []
    for field_name in _RECORD_FIELDS:
        if field_name not in record:
            continue
        value = record[field_name]
        if isinstance(value, list):
            details.append(f"{field_name}=[{', '.join(str(v) for v in value)}]")
        else:
            details.append(f"{field_name}={value}")
    if details:
        return f"• {rid} — {', '.join(details)}"
    return f"• {rid}"


def format_records_slack(result: QueryResult, *, limit: int = SLACK_RECORD_LIMIT) -> str:
    """Render a :class:`QueryResult` as a Slack-friendly plain-text reply.

    Deterministic layout: a header line with the match count and endpoint, then
    one bullet per record (id + a few key fields), truncated to ``limit`` with a
    "+N more" footer when the result is larger. A zero-match result renders a
    clear "no records matched" line listing the applied filters.
    """
    filters_clause = _format_filters(result.filters)
    if result.count == 0:
        return (
            f"No records matched on {result.endpoint} ({filters_clause}). "
            f"Scanned {result.total_scanned}."
        )

    noun = "record" if result.count == 1 else "records"
    header = f"Found {result.count} {noun} on {result.endpoint} ({filters_clause}):"
    lines = [header]
    shown = result.records[:limit]
    for record in shown:
        lines.append(_format_record_line(record))
    remaining = result.count - len(shown)
    if remaining > 0:
        lines.append(f"…and {remaining} more.")
    return "\n".join(lines)


def format_records_json(result: QueryResult) -> dict[str, Any]:
    """Render a :class:`QueryResult` as a JSON-serializable object.

    The stable machine contract for ``--json`` and for a real Slack app to post
    as a structured payload: ``{"endpoint", "filters", "count", "records"}``.
    """
    return {
        "endpoint": result.endpoint,
        "filters": dict(result.filters),
        "count": result.count,
        "records": [dict(r) for r in result.records],
    }


def format_validation_error(issues: list[ValidationIssue]) -> str:
    """Render schema-validation failures as a Slack-friendly message.

    Lists each issue (field-scoped where applicable) so a producer can see why
    the request was rejected. Deterministic and order-stable.
    """
    if not issues:
        return "The request is valid."
    header = "I couldn't turn that into a valid query:"
    lines = [header]
    for issue in issues:
        if issue.field:
            lines.append(f"• [{issue.field}] {issue.message}")
        else:
            lines.append(f"• {issue.message}")
    return "\n".join(lines)


def format_clarification(issues: list[ValidationIssue], request: str) -> str:
    """Render an ask-to-clarify prompt back to the requester.

    Built deterministically from the validation issues — the tool tells the user
    *which* part of their ask it could not map (e.g. an unknown status) and
    invites a rephrase. No model call: the issues already carry the specifics.
    """
    lines = [f'I couldn\'t map your request ("{request}") onto a valid query.']
    if issues:
        lines.append("Here's what tripped me up:")
        for issue in issues:
            if issue.field:
                lines.append(f"• [{issue.field}] {issue.message}")
            else:
                lines.append(f"• {issue.message}")
    lines.append("Could you rephrase or specify a known endpoint/field/value?")
    return "\n".join(lines)
