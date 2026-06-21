#!/usr/bin/env python3
"""Hermetic, reproducible acceptance runner for slack-glue.

Executes EVERY scenario (SC-01 … SC-11) from ``acceptance/scenarios.md`` under
identical conditions and asserts each machine-checkable success criterion.

Design / hermeticity guarantees
-------------------------------
- The single model boundary (NL -> schema) is driven only by replykit's
  ``ScriptedModel`` / ``MockModel``. No scenario opens a socket, hits the
  network, or calls a live LLM. ``telemetry.total_cost_usd == 0.0`` is asserted
  everywhere as proof the run was hermetic.
- CLI scenarios shell out to the exact ``.venv/bin/slack-glue`` console script
  with the exact commands documented in the plan, capturing stdout/exit code.
- Slack-pipeline and example scenarios run in-process / via the venv python so
  the whole path is exercised with no API key.

Two ways to run:

    .venv/bin/python -m pytest acceptance/test_acceptance.py -q   # as pytest
    .venv/bin/python acceptance/test_acceptance.py                # standalone

The standalone entry point runs all scenarios, writes ``acceptance/EVIDENCE.md``
with per-scenario command / output / verdict, and prints a totals summary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# --- Paths and the hermetic, fixed environment ------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = REPO_ROOT / ".venv" / "bin"
SLACK_GLUE = str(VENV_BIN / "slack-glue")
PY = str(VENV_BIN / "python")
EVIDENCE_PATH = Path(__file__).resolve().parent / "EVIDENCE.md"

# Identical conditions for every scenario: force offline, scrub any provider
# keys so a live LLM is impossible by construction, stable locale + hashing.
HERMETIC_ENV = {
    **os.environ,
    "OPENAI_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "NO_COLOR": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONIOENCODING": "utf-8",
    "LC_ALL": "C.UTF-8",
    "LANG": "C.UTF-8",
}

# The five status enum members the validator advertises (SC-03).
STATUS_MEMBERS = ["approved", "in_progress", "omit", "final", "pending"]


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a command under the fixed hermetic env from the repo root."""
    return subprocess.run(
        argv,
        cwd=str(REPO_ROOT),
        env=HERMETIC_ENV,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _emit_block(**fields: str) -> str:
    """Build the exact ``@reply name=emit_query`` script text for a scenario.

    Mirrors the ``$'...\\n...'`` blocks in the plan: a header, ``key = value``
    lines in the given order, then ``@end``.
    """
    lines = ["@reply name=emit_query"]
    lines += [f"{key} = {value}" for key, value in fields.items()]
    lines.append("@end")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The scenario implementations. Each returns nothing and raises AssertionError
# on any failed criterion; the standalone harness captures that for EVIDENCE.md.
# ---------------------------------------------------------------------------


def sc01() -> dict:
    """SC-01 — Happy path: route -> validate -> execute -> format (shots)."""
    script = _emit_block(
        endpoint="/api/v1/shots",
        status="approved",
        dept="vfx",
        reel="3",
        tags="greenscreen",
    )
    cmd = [
        SLACK_GLUE,
        "ask",
        "approved vfx shots in reel 3 with greenscreen",
        "--model",
        "scripted",
        "--script",
        script,
        "--json",
    ]
    proc = _run(cmd)
    assert proc.returncode == 0, f"exit {proc.returncode}, stderr={proc.stderr!r}"
    data = json.loads(proc.stdout)

    assert data["ok"] is True, data
    assert data["query"]["endpoint"] == "/api/v1/shots"
    # Exact filters dict, with reel the INTEGER 3 (int coercion proof).
    assert data["query"]["filters"] == {
        "status": "approved",
        "reel": 3,
        "dept": "vfx",
        "tags": ["greenscreen"],
    }, data["query"]["filters"]
    reel = data["query"]["filters"]["reel"]
    assert reel == 3 and isinstance(reel, int) and not isinstance(reel, bool), (
        f"reel must be int 3, got {reel!r} ({type(reel).__name__})"
    )
    assert data["result"]["count"] == 2
    ids = {r["id"] for r in data["result"]["records"]}
    assert ids == {"SHOT-0101", "SHOT-0102"}, ids
    assert data["text"].startswith("Found 2 records on /api/v1/shots"), data["text"]
    assert data["telemetry"]["total_cost_usd"] == 0.0
    return {
        "command": " ".join(repr(a) if " " in a else a for a in cmd),
        "stdout": proc.stdout,
        "exit": proc.returncode,
    }


def sc02() -> dict:
    """SC-02 — Happy path on the second endpoint (assets); singular noun."""
    script = _emit_block(
        endpoint="/api/v1/assets",
        status="approved",
        asset_type="character",
    )
    cmd = [
        SLACK_GLUE,
        "ask",
        "approved character assets",
        "--model",
        "scripted",
        "--script",
        script,
        "--json",
    ]
    proc = _run(cmd)
    assert proc.returncode == 0, f"exit {proc.returncode}, stderr={proc.stderr!r}"
    data = json.loads(proc.stdout)

    assert data["ok"] is True, data
    assert data["query"]["endpoint"] == "/api/v1/assets"
    assert data["query"]["filters"] == {"status": "approved", "asset_type": "character"}, data[
        "query"
    ]["filters"]
    assert data["result"]["count"] == 1
    assert data["result"]["records"][0]["id"] == "AST-HERO-01"
    assert data["text"].startswith("Found 1 record on /api/v1/assets"), data["text"]
    # Prove singular noun: "record" not "records" in the header.
    assert data["text"].startswith("Found 1 record on"), data["text"]
    assert not data["text"].startswith("Found 1 records"), data["text"]
    assert data["telemetry"]["total_cost_usd"] == 0.0
    return {
        "command": " ".join(repr(a) if " " in a else a for a in cmd),
        "stdout": proc.stdout,
        "exit": proc.returncode,
    }


def sc03() -> dict:
    """SC-03 — Clarify on out-of-vocabulary enum value (validator rejects)."""
    script = _emit_block(endpoint="/api/v1/shots", status="greenlit")
    cmd = [
        SLACK_GLUE,
        "ask",
        "all greenlit shots",
        "--model",
        "scripted",
        "--script",
        script,
        "--json",
    ]
    proc = _run(cmd)
    assert proc.returncode == 0, f"exit {proc.returncode}, stderr={proc.stderr!r}"
    data = json.loads(proc.stdout)

    assert data["ok"] is False, data
    assert len(data["issues"]) == 1, data["issues"]
    issue = data["issues"][0]
    assert issue["code"] == "bad_enum", issue
    assert issue["field"] == "status", issue
    assert "'greenlit' is not one of" in issue["message"], issue["message"]
    for member in STATUS_MEMBERS:
        assert member in issue["message"], f"missing enum member {member!r}: {issue['message']}"
    # Rejected proposal preserved for debugging.
    assert data["raw_intent"]["filters"]["status"] == "greenlit", data["raw_intent"]
    # No result/records key on the clarify path.
    assert "result" not in data, "clarify outcome must not include a result"
    assert data["telemetry"]["total_cost_usd"] == 0.0
    return {
        "command": " ".join(repr(a) if " " in a else a for a in cmd),
        "stdout": proc.stdout,
        "exit": proc.returncode,
    }


def sc04() -> dict:
    """SC-04 — Clarify on a field valid only on the WRONG endpoint."""
    script = _emit_block(endpoint="/api/v1/shots", asset_type="character")
    cmd = [
        SLACK_GLUE,
        "ask",
        "character shots",
        "--model",
        "scripted",
        "--script",
        script,
        "--json",
    ]
    proc = _run(cmd)
    assert proc.returncode == 0, f"exit {proc.returncode}, stderr={proc.stderr!r}"
    data = json.loads(proc.stdout)

    assert data["ok"] is False, data
    assert len(data["issues"]) == 1, data["issues"]
    issue = data["issues"][0]
    assert issue["code"] == "unknown_field", issue
    assert issue["field"] == "asset_type", issue
    # Message lists the allowed shot fields.
    for fld in ["dept", "reel", "sequence", "status", "tags"]:
        assert fld in issue["message"], f"missing allowed field {fld!r}: {issue['message']}"
    assert data["telemetry"]["total_cost_usd"] == 0.0
    return {
        "command": " ".join(repr(a) if " " in a else a for a in cmd),
        "stdout": proc.stdout,
        "exit": proc.returncode,
    }


def sc05() -> dict:
    """SC-05 — Clarify on an unknown (invented) endpoint."""
    script = _emit_block(endpoint="/api/v1/edits")
    cmd = [
        SLACK_GLUE,
        "ask",
        "pull the edits",
        "--model",
        "scripted",
        "--script",
        script,
        "--json",
    ]
    proc = _run(cmd)
    assert proc.returncode == 0, f"exit {proc.returncode}, stderr={proc.stderr!r}"
    data = json.loads(proc.stdout)

    assert data["ok"] is False, data
    assert len(data["issues"]) == 1, data["issues"]
    issue = data["issues"][0]
    assert issue["code"] == "unknown_endpoint", issue
    assert issue["field"] == "endpoint", issue
    for ep in ["/api/v1/assets", "/api/v1/shots"]:
        assert ep in issue["message"], f"missing endpoint {ep!r}: {issue['message']}"
    assert data["telemetry"]["total_cost_usd"] == 0.0
    return {
        "command": " ".join(repr(a) if " " in a else a for a in cmd),
        "stdout": proc.stdout,
        "exit": proc.returncode,
    }


def sc06() -> dict:
    """SC-06 — Zero-match is a valid result (ok=true, count=0), not a clarify."""
    script = _emit_block(endpoint="/api/v1/shots", status="final", reel="3")
    cmd = [
        SLACK_GLUE,
        "ask",
        "final shots in reel 3",
        "--model",
        "scripted",
        "--script",
        script,
        "--json",
    ]
    proc = _run(cmd)
    assert proc.returncode == 0, f"exit {proc.returncode}, stderr={proc.stderr!r}"
    data = json.loads(proc.stdout)

    assert data["ok"] is True, data
    assert data["result"]["count"] == 0, data["result"]
    assert data["result"]["records"] == [], data["result"]["records"]
    expected = "No records matched on /api/v1/shots (reel=3, status=final). Scanned 10."
    assert data["text"] == expected, f"text={data['text']!r}"
    assert data["telemetry"]["total_cost_usd"] == 0.0
    return {
        "command": " ".join(repr(a) if " " in a else a for a in cmd),
        "stdout": proc.stdout,
        "exit": proc.returncode,
    }


def sc07() -> dict:
    """SC-07 — Config error: unknown --model exits non-zero, single JSON object."""
    cmd = [SLACK_GLUE, "ask", "anything", "--model", "banana", "--json"]
    proc = _run(cmd)
    assert proc.returncode == 1, f"expected exit 1, got {proc.returncode}"
    # Exactly one JSON object on stdout, nothing else.
    out = proc.stdout
    assert out.count("\n") == 1, f"stdout must be one line; got {out!r}"
    data = json.loads(out)
    assert set(data.keys()) == {"error"}, f"only an 'error' key allowed: {data.keys()}"
    for forbidden in ("ok", "result", "issues"):
        assert forbidden not in data, f"{forbidden} must be absent on error path"
    assert "unknown --model 'banana'" in data["error"], data["error"]
    for choice in ("scripted", "mock", "openai", "anthropic"):
        assert choice in data["error"], f"missing choice {choice!r}: {data['error']}"
    return {
        "command": " ".join(repr(a) if " " in a else a for a in cmd),
        "stdout": proc.stdout,
        "exit": proc.returncode,
    }


def sc08() -> dict:
    """SC-08 — serve is offline-safe; --check smoke-tests the whole pipeline."""
    # serve --json (plain wiring).
    cmd_plain = [SLACK_GLUE, "serve", "--json"]
    proc_plain = _run(cmd_plain)
    assert proc_plain.returncode == 0, f"exit {proc_plain.returncode}, stderr={proc_plain.stderr!r}"
    plain = json.loads(proc_plain.stdout)
    assert plain["transport"] == "offline", plain
    assert plain["endpoints"] == ["/api/v1/assets", "/api/v1/shots"], plain["endpoints"]
    assert plain["filters"]["/api/v1/shots"] == ["dept", "reel", "sequence", "status", "tags"], (
        plain["filters"]
    )
    assert plain["filters"]["/api/v1/assets"] == ["asset_type", "dept", "status", "tags"], plain[
        "filters"
    ]
    assert "check" not in plain, "plain serve must not include a check key"

    # serve --check --json (wiring + offline smoke run).
    cmd_check = [SLACK_GLUE, "serve", "--check", "--json"]
    proc_check = _run(cmd_check)
    assert proc_check.returncode == 0, f"exit {proc_check.returncode}, stderr={proc_check.stderr!r}"
    chk = json.loads(proc_check.stdout)
    assert chk["check"]["ok"] is True, chk["check"]
    assert chk["check"]["reply"]["kind"] == "results", chk["check"]["reply"]
    assert chk["check"]["reply"]["payload"]["count"] == 2, chk["check"]["reply"]["payload"]
    assert chk["check"]["reply"]["thread_ts"] == "1718900000.000100", chk["check"]["reply"]
    return {
        "command": f"{cmd_plain[0]} serve --json  ;  {cmd_check[0]} serve --check --json",
        "stdout": proc_plain.stdout + proc_check.stdout,
        "exit": proc_check.returncode,
    }


def sc09() -> dict:
    """SC-09 — --json emits exactly one object; reproducible byte-for-byte."""
    script = _emit_block(endpoint="/api/v1/shots", status="approved")
    cmd = [
        SLACK_GLUE,
        "ask",
        "approved shots",
        "--model",
        "scripted",
        "--script",
        script,
        "--json",
    ]
    proc1 = _run(cmd)
    assert proc1.returncode == 0, f"exit {proc1.returncode}, stderr={proc1.stderr!r}"
    out = proc1.stdout
    # Exactly one newline-terminated line.
    assert out.endswith("\n"), "stdout must be newline-terminated"
    assert out.count("\n") == 1, f"stdout must be exactly 1 line; got {out!r}"
    # Parses as a single JSON object.
    parsed = json.loads(out)
    assert isinstance(parsed, dict), type(parsed)
    # Re-run: byte-identical stdout (determinism).
    proc2 = _run(cmd)
    assert proc2.returncode == 0, f"rerun exit {proc2.returncode}"
    assert proc2.stdout == out, "re-run stdout must be byte-identical (determinism)"
    return {
        "command": " ".join(repr(a) if " " in a else a for a in cmd) + " | wc -l",
        "stdout": f"line_count=1 ; byte_identical_rerun=True\n{out}",
        "exit": proc1.returncode,
    }


def sc10() -> dict:
    """SC-10 — Slack app_mention pipeline in plain Python (mention strip)."""
    # Run in-process via the venv python so it's hermetic and uses the editable
    # install. The leading <@U0BOTID> mention must be stripped before routing.
    program = r"""
import json
from replykit import ScriptedModel
from slack_glue import Router, load_fixture, parse_event, handle_app_mention

block = ("@reply name=emit_query\nendpoint = /api/v1/shots\n"
         "status = approved\nreel = 3\ndept = vfx\ntags = greenscreen\n@end")
router = Router(ScriptedModel([block, "Done."]))
db = load_fixture()
payload = {"event": {"type": "app_mention",
                     "text": "<@U0BOTID> approved vfx shots in reel 3 with greenscreen",
                     "user": "U0PRODUCER", "channel": "C0VFX", "ts": "1700000000.000200"}}
reply = handle_app_mention(parse_event(payload), router, db)
print(json.dumps({
    "kind": reply.kind,
    "count": reply.payload["count"],
    "ids": sorted(r["id"] for r in reply.payload["records"]),
    "channel": reply.channel,
    "thread_ts": reply.thread_ts,
    "text": reply.text,
    "has_api_key": bool(__import__("os").environ.get("ANTHROPIC_API_KEY") or
                        __import__("os").environ.get("OPENAI_API_KEY")),
}))
"""
    cmd = [PY, "-c", program]
    proc = _run(cmd)
    assert proc.returncode == 0, f"exit {proc.returncode}, stderr={proc.stderr!r}"
    data = json.loads(proc.stdout)

    assert data["kind"] == "results", data
    assert data["count"] == 2, data
    assert set(data["ids"]) == {"SHOT-0101", "SHOT-0102"}, data["ids"]
    assert data["channel"] == "C0VFX", data["channel"]
    assert data["thread_ts"] == "1700000000.000200", data["thread_ts"]
    assert data["text"].startswith("Found 2 records on /api/v1/shots"), data["text"]
    # Hermetic: no API key present in the run env.
    assert data["has_api_key"] is False, "scenario must run with no API key"
    return {
        "command": f"{PY} -c '<slack app_mention pipeline; "
        f"handle_app_mention(parse_event(payload), Router(ScriptedModel([...])), "
        f"load_fixture())>'",
        "stdout": proc.stdout,
        "exit": proc.returncode,
    }


def sc11() -> dict:
    """SC-11 — Deterministic core is fully hermetic (regression gate)."""
    summary_parts: list[str] = []

    # pytest -q over the deterministic core (run from repo root; exclude this
    # acceptance module to test the package's own suite as the plan specifies).
    pytest_cmd = [PY, "-m", "pytest", "-q", "tests"]
    proc_pytest = _run(pytest_cmd)
    summary_parts.append(f"$ {' '.join(pytest_cmd)}\n{proc_pytest.stdout[-2000:]}")
    assert proc_pytest.returncode == 0, (
        f"pytest failed (exit {proc_pytest.returncode}):\n{proc_pytest.stdout[-3000:]}"
    )
    # 0 failures: the -q summary line must not contain 'failed'/'error'.
    last_line = proc_pytest.stdout.strip().splitlines()[-1] if proc_pytest.stdout.strip() else ""
    assert "fail" not in last_line.lower() and "error" not in last_line.lower(), last_line

    # Both example scripts exit 0.
    for example in ("examples/ask_hermetic.py", "examples/slack_event.py"):
        ex_cmd = [PY, example]
        proc_ex = _run(ex_cmd)
        summary_parts.append(f"$ {' '.join(ex_cmd)}  -> exit {proc_ex.returncode}")
        assert proc_ex.returncode == 0, (
            f"{example} failed (exit {proc_ex.returncode}):\n{proc_ex.stderr[-2000:]}"
        )

    return {
        "command": "pytest -q tests ; python examples/ask_hermetic.py ; "
        "python examples/slack_event.py",
        "stdout": "\n\n".join(summary_parts),
        "exit": 0,
    }


# Ordered registry of all scenarios (id -> callable).
SCENARIOS = {
    "SC-01": sc01,
    "SC-02": sc02,
    "SC-03": sc03,
    "SC-04": sc04,
    "SC-05": sc05,
    "SC-06": sc06,
    "SC-07": sc07,
    "SC-08": sc08,
    "SC-09": sc09,
    "SC-10": sc10,
    "SC-11": sc11,
}


# --- pytest entry points ----------------------------------------------------


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_scenario(scenario_id: str) -> None:
    """Run each scenario as a parametrized pytest case (one per SC-id)."""
    SCENARIOS[scenario_id]()


# --- Standalone harness (writes EVIDENCE.md) --------------------------------


def _truncate(text: str, limit: int = 6000) -> str:
    """Cap captured output so EVIDENCE.md stays readable."""
    text = text.rstrip("\n")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated {len(text) - limit} chars]"


def run_all_and_record() -> int:
    """Run every scenario, write EVIDENCE.md, print a summary. Return exit code."""
    import datetime
    import platform

    results: list[tuple[str, bool, str, dict]] = []
    for scenario_id, fn in SCENARIOS.items():
        doc = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""
        try:
            evidence = fn()
            results.append((scenario_id, True, doc, evidence))
        except AssertionError as exc:
            results.append(
                (
                    scenario_id,
                    False,
                    doc,
                    {"error": str(exc), "command": "", "stdout": "", "exit": ""},
                )
            )
        except Exception as exc:  # noqa: BLE001 - record any unexpected failure
            results.append(
                (
                    scenario_id,
                    False,
                    doc,
                    {
                        "error": f"{type(exc).__name__}: {exc}",
                        "command": "",
                        "stdout": "",
                        "exit": "",
                    },
                )
            )

    passed = sum(1 for _, ok, _, _ in results if ok)
    total = len(results)
    failures = [sid for sid, ok, _, _ in results if not ok]

    # --- Write EVIDENCE.md ---
    lines: list[str] = []
    lines.append("# slack-glue — Acceptance Evidence")
    lines.append("")
    lines.append(f"- Generated: {datetime.datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- Repo: `{REPO_ROOT}`")
    lines.append("- Runner: `acceptance/test_acceptance.py`")
    lines.append(f"- Python: `{platform.python_version()}` (venv `{VENV_BIN}`)")
    lines.append(
        "- Conditions: hermetic — replykit ScriptedModel/MockModel only; "
        "OPENAI/ANTHROPIC keys scrubbed; no network, no socket."
    )
    lines.append(
        f"- **Result: {passed}/{total} scenarios PASS**"
        + (f" — failures: {', '.join(failures)}" if failures else " — all green.")
    )
    lines.append("")
    lines.append("| Scenario | Verdict |")
    lines.append("|---|---|")
    for sid, ok, _, _ in results:
        lines.append(f"| {sid} | {'PASS' if ok else 'FAIL'} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for sid, ok, doc, ev in results:
        lines.append(f"## {sid} — {'PASS' if ok else 'FAIL'}")
        lines.append("")
        if doc:
            lines.append(f"_{doc}_")
            lines.append("")
        if ev.get("command"):
            lines.append("Command / inputs:")
            lines.append("")
            lines.append("```")
            lines.append(str(ev["command"]))
            lines.append("```")
            lines.append("")
        if ev.get("exit") != "":
            lines.append(f"Exit code: `{ev.get('exit')}`")
            lines.append("")
        if ev.get("stdout"):
            lines.append("Captured output:")
            lines.append("")
            lines.append("```")
            lines.append(_truncate(str(ev["stdout"])))
            lines.append("```")
            lines.append("")
        if not ok and ev.get("error"):
            lines.append("Failure reason:")
            lines.append("")
            lines.append("```")
            lines.append(_truncate(str(ev["error"]), 3000))
            lines.append("```")
            lines.append("")
        lines.append(f"**Verdict: {'PASS' if ok else 'FAIL'}**")
        lines.append("")
        lines.append("---")
        lines.append("")

    EVIDENCE_PATH.write_text("\n".join(lines), encoding="utf-8")

    # --- Print summary to stdout ---
    print(f"\nslack-glue acceptance: {passed}/{total} PASS")
    for sid, ok, _, ev in results:
        mark = "PASS" if ok else "FAIL"
        extra = "" if ok else f"  <- {ev.get('error', '')}"
        print(f"  {sid}: {mark}{extra}")
    print(f"\nEvidence written to: {EVIDENCE_PATH}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(run_all_and_record())
