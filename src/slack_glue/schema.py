"""The strict intent-query schema and its DETERMINISTIC validator.

An :class:`IntentQuery` is the contract the natural-language step must produce:
an ``endpoint`` plus a ``filters`` mapping. This module owns the *only*
definition of what a valid query looks like — the set of endpoints, the set of
filterable fields per endpoint, and each field's expected value type. Validation
is pure code: no model judgment, no network. Invalid intent is rejected with a
list of structured :class:`ValidationIssue` objects so the caller can either
fail fast or ask the producer to clarify.

This module is the schema authority for the whole package. The router emits raw
dicts; this module decides whether they are queries or garbage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- Schema definition (the deterministic source of truth) -----------------

#: Allowed endpoints, mapped to the record "kind" they query in the database.
ENDPOINTS: dict[str, str] = {
    "/api/v1/shots": "shot",
    "/api/v1/assets": "asset",
}

#: Per-endpoint filterable fields mapped to a value-type tag understood by the
#: validator and executor: "str" | "int" | "str_list" | "enum:<a|b|c>".
#: This is the closed vocabulary the NL step must map onto; anything else is
#: an invalid intent (rejected deterministically).
FIELD_TYPES: dict[str, dict[str, str]] = {
    "/api/v1/shots": {
        "status": "enum:approved|in_progress|omit|final|pending",
        "reel": "int",
        "dept": "enum:vfx|comp|anim|lighting|layout",
        "tags": "str_list",
        "sequence": "str",
    },
    "/api/v1/assets": {
        "status": "enum:approved|in_progress|omit|final|pending",
        "asset_type": "enum:character|prop|environment|fx",
        "dept": "enum:vfx|comp|anim|lighting|layout",
        "tags": "str_list",
    },
}


@dataclass(frozen=True)
class ValidationIssue:
    """One structured validation failure (field-scoped where possible)."""

    code: str  # e.g. "unknown_endpoint" | "unknown_field" | "bad_type" | "bad_enum"
    field: str  # "" for whole-query issues (e.g. unknown endpoint / missing endpoint)
    message: str


@dataclass(frozen=True)
class IntentQuery:
    """A validated, normalized API query: endpoint + typed filters.

    Instances of this class are only ever produced by :func:`validate_intent`,
    so holding one is proof the query is well-formed against :data:`ENDPOINTS`
    and :data:`FIELD_TYPES`. Values are normalized (ints coerced, tag lists
    de-duplicated and lowercased).
    """

    endpoint: str
    filters: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable form of the query."""
        return {"endpoint": self.endpoint, "filters": dict(self.filters)}


def _enum_members(field_type: str) -> list[str]:
    """Extract the allowed members from an ``enum:a|b|c`` type tag."""
    return field_type[len("enum:") :].split("|")


def coerce_field_value(field_type: str, raw: Any) -> tuple[Any | None, str | None]:
    """Coerce/validate one field value against its type tag.

    Returns ``(normalized_value, None)`` on success or ``(None, reason)`` on
    failure. Pure helper shared by :func:`validate_intent`; exposed for unit
    testing each type rule (int, str, str_list, enum) in isolation.
    """
    if field_type == "int":
        if isinstance(raw, bool):  # bool is an int subclass; reject it explicitly
            return None, "expected an integer, got a boolean"
        if isinstance(raw, int):
            return raw, None
        if isinstance(raw, str):
            text = raw.strip()
            try:
                return int(text), None
            except ValueError:
                return None, f"expected an integer, got {raw!r}"
        return None, f"expected an integer, got {type(raw).__name__}"

    if field_type == "str":
        if isinstance(raw, str):
            value = raw.strip()
            if not value:
                return None, "expected a non-empty string"
            return value, None
        return None, f"expected a string, got {type(raw).__name__}"

    if field_type == "str_list":
        if isinstance(raw, str):
            items = [raw]
        elif isinstance(raw, (list, tuple)):
            items = list(raw)
        else:
            return None, f"expected a list of strings, got {type(raw).__name__}"
        normalized: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, str):
                return None, f"expected string tags, got {type(item).__name__}"
            tag = item.strip().lower()
            if not tag:
                continue
            if tag in seen:
                continue
            seen.add(tag)
            normalized.append(tag)
        if not normalized:
            return None, "expected at least one non-empty tag"
        return normalized, None

    if field_type.startswith("enum:"):
        members = _enum_members(field_type)
        if not isinstance(raw, str):
            return None, f"expected one of {members}, got {type(raw).__name__}"
        value = raw.strip()
        if value not in members:
            return None, f"{value!r} is not one of {members}"
        return value, None

    # Unknown type tag — a schema bug, not user input. Be loud but don't crash.
    return None, f"unknown field type {field_type!r}"


def validate_intent(payload: Any) -> tuple[IntentQuery | None, list[ValidationIssue]]:
    """Deterministically validate a raw intent payload against the schema.

    ``payload`` is whatever the NL step produced (expected: a dict with
    ``endpoint`` and ``filters``). Returns ``(query, [])`` when valid, or
    ``(None, issues)`` with one or more :class:`ValidationIssue` describing every
    problem found (unknown endpoint, unknown field, wrong value type, bad enum
    member, malformed shape). Never raises on bad input — bad input is data.

    Normalization on success: ``reel`` coerced to ``int``; ``tags`` lowercased,
    stripped, de-duplicated, order-preserved; enum/str values stripped.
    """
    if not isinstance(payload, dict):
        return None, [
            ValidationIssue(
                code="bad_shape",
                field="",
                message=f"intent must be an object, got {type(payload).__name__}",
            )
        ]

    endpoint = payload.get("endpoint")
    if not endpoint or not isinstance(endpoint, str):
        return None, [
            ValidationIssue(
                code="missing_endpoint",
                field="endpoint",
                message="intent is missing a non-empty 'endpoint'",
            )
        ]

    if endpoint not in ENDPOINTS:
        return None, [
            ValidationIssue(
                code="unknown_endpoint",
                field="endpoint",
                message=(f"unknown endpoint {endpoint!r}; expected one of {sorted(ENDPOINTS)}"),
            )
        ]

    raw_filters = payload.get("filters", {})
    if raw_filters is None:
        raw_filters = {}
    if not isinstance(raw_filters, dict):
        return None, [
            ValidationIssue(
                code="bad_shape",
                field="filters",
                message=f"'filters' must be an object, got {type(raw_filters).__name__}",
            )
        ]

    field_types = FIELD_TYPES[endpoint]
    issues: list[ValidationIssue] = []
    filters: dict[str, Any] = {}

    for name, raw in raw_filters.items():
        field_type = field_types.get(name)
        if field_type is None:
            issues.append(
                ValidationIssue(
                    code="unknown_field",
                    field=name,
                    message=(
                        f"unknown filter {name!r} for {endpoint}; allowed: {sorted(field_types)}"
                    ),
                )
            )
            continue
        value, reason = coerce_field_value(field_type, raw)
        if reason is not None:
            code = "bad_enum" if field_type.startswith("enum:") else "bad_type"
            issues.append(ValidationIssue(code=code, field=name, message=f"{name}: {reason}"))
            continue
        filters[name] = value

    if issues:
        return None, issues
    return IntentQuery(endpoint=endpoint, filters=filters), []
