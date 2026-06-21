"""The mock ShotGrid database and its DETERMINISTIC query executor.

A :class:`Database` is an in-memory collection of records loaded from a JSON
fixture (``fixtures/shotgrid.json``). :func:`execute_query` runs a validated
:class:`~slack_glue.schema.IntentQuery` against it with plain Python filtering:
exact match for scalar fields, "record has all requested tags" (AND) for the
``tags`` filter. No model judgment, no live ShotGrid, no network — given the
same fixture and query the result is byte-for-byte reproducible, which is what
makes the executor unit-testable and CI hermetic.

The executor only ever receives an already-validated query, so it can trust the
endpoint and field names; it never re-implements schema rules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import ENDPOINTS, IntentQuery

#: The packaged fixture dataset shipped inside the wheel.
FIXTURE_PATH: Path = Path(__file__).parent / "fixtures" / "shotgrid.json"

#: A single ShotGrid-style record (a plain JSON object).
Record = dict[str, Any]


@dataclass(frozen=True)
class Database:
    """An in-memory set of records keyed by kind ("shot" | "asset").

    Built by :func:`load_fixture`. Holds the parsed records grouped by kind so
    the executor can select the collection an endpoint maps to in O(1).
    """

    records: dict[str, list[Record]]

    def kinds(self) -> list[str]:
        """The record kinds present, sorted (e.g. ``["asset", "shot"]``)."""
        return sorted(self.records)

    def all(self, kind: str) -> list[Record]:
        """All records of one kind (empty list if the kind is absent)."""
        return list(self.records.get(kind, []))


@dataclass(frozen=True)
class QueryResult:
    """The outcome of running a query: matched records + accounting."""

    endpoint: str
    filters: dict[str, Any]
    records: list[Record]
    total_scanned: int

    @property
    def count(self) -> int:
        """Number of matched records."""
        return len(self.records)

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable summary of the query result."""
        return {
            "endpoint": self.endpoint,
            "filters": dict(self.filters),
            "count": self.count,
            "total_scanned": self.total_scanned,
            "records": [dict(r) for r in self.records],
        }


def load_fixture(path: str | Path | None = None) -> Database:
    """Load and group the JSON fixture into a :class:`Database`.

    ``path`` defaults to the packaged :data:`FIXTURE_PATH`. The fixture is a JSON
    object mapping kind -> list of records. Raises ``FileNotFoundError`` if the
    path is missing and ``ValueError`` if the JSON shape is not a kind->list map.
    """
    resolved = Path(path) if path is not None else FIXTURE_PATH
    if not resolved.exists():
        raise FileNotFoundError(f"fixture not found: {resolved}")

    raw = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"fixture must be a JSON object mapping kind -> records, got {type(raw).__name__}"
        )

    records: dict[str, list[Record]] = {}
    for kind, rows in raw.items():
        if not isinstance(rows, list):
            raise ValueError(f"fixture kind {kind!r} must map to a list, got {type(rows).__name__}")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(
                    f"fixture kind {kind!r} contains a non-object record: {type(row).__name__}"
                )
        records[kind] = list(rows)
    return Database(records=records)


def record_matches(record: Record, filters: dict[str, Any]) -> bool:
    """True iff a single record satisfies every filter (pure predicate).

    Factored out of :func:`execute_query` so the per-record match logic (scalar
    equality + tag-superset) is unit-testable in isolation.
    """
    for name, wanted in filters.items():
        if name == "tags":
            record_tags = record.get("tags", [])
            if not isinstance(record_tags, list):
                return False
            have = {str(t).lower() for t in record_tags}
            if not set(wanted).issubset(have):
                return False
        else:
            if record.get(name) != wanted:
                return False
    return True


def execute_query(query: IntentQuery, db: Database) -> QueryResult:
    """Run a validated query against the database, deterministically.

    Resolves the query's endpoint to a record kind via
    :data:`~slack_glue.schema.ENDPOINTS`, then filters that kind's records:
    scalar fields (``status``, ``reel``, ``dept``, ``asset_type``, ``sequence``)
    match by equality; ``tags`` matches records whose tag set is a superset of
    the requested tags (AND semantics). Returns matches in fixture order.
    """
    kind = ENDPOINTS[query.endpoint]
    candidates = db.all(kind)
    matched = [r for r in candidates if record_matches(r, query.filters)]
    return QueryResult(
        endpoint=query.endpoint,
        filters=dict(query.filters),
        records=matched,
        total_scanned=len(candidates),
    )
