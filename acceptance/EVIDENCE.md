# slack-glue — Acceptance Evidence

- Generated: 2026-06-20T22:23:41
- Repo: `/Users/ehernand/personal_projects/postpro-kit/slack-glue`
- Runner: `acceptance/test_acceptance.py`
- Python: `3.12.11` (venv `/Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin`)
- Conditions: hermetic — replykit ScriptedModel/MockModel only; OPENAI/ANTHROPIC keys scrubbed; no network, no socket.
- **Result: 11/11 scenarios PASS** — all green.

| Scenario | Verdict |
|---|---|
| SC-01 | PASS |
| SC-02 | PASS |
| SC-03 | PASS |
| SC-04 | PASS |
| SC-05 | PASS |
| SC-06 | PASS |
| SC-07 | PASS |
| SC-08 | PASS |
| SC-09 | PASS |
| SC-10 | PASS |
| SC-11 | PASS |

---

## SC-01 — PASS

_SC-01 — Happy path: route -> validate -> execute -> format (shots)._

Command / inputs:

```
/Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/slack-glue ask 'approved vfx shots in reel 3 with greenscreen' --model scripted --script '@reply name=emit_query\nendpoint = /api/v1/shots\nstatus = approved\ndept = vfx\nreel = 3\ntags = greenscreen\n@end' --json
```

Exit code: `0`

Captured output:

```
{"ok": true, "request": "approved vfx shots in reel 3 with greenscreen", "query": {"endpoint": "/api/v1/shots", "filters": {"status": "approved", "reel": 3, "dept": "vfx", "tags": ["greenscreen"]}}, "result": {"endpoint": "/api/v1/shots", "filters": {"status": "approved", "reel": 3, "dept": "vfx", "tags": ["greenscreen"]}, "count": 2, "records": [{"id": "SHOT-0101", "status": "approved", "reel": 3, "dept": "vfx", "sequence": "RDR", "tags": ["greenscreen", "hero"]}, {"id": "SHOT-0102", "status": "approved", "reel": 3, "dept": "vfx", "sequence": "RDR", "tags": ["greenscreen", "crowd"]}]}, "text": "Found 2 records on /api/v1/shots (dept=vfx, reel=3, status=approved, tags=[greenscreen]):\n• SHOT-0101 — status=approved, reel=3, dept=vfx, sequence=RDR, tags=[greenscreen, hero]\n• SHOT-0102 — status=approved, reel=3, dept=vfx, sequence=RDR, tags=[greenscreen, crowd]", "telemetry": {"calls": 2, "total_input_tokens": 382, "total_output_tokens": 19, "total_repair_attempts": 0, "total_cost_usd": 0.0, "by_call": [{"model": "ScriptedModel", "input_tokens": 168, "output_tokens": 18, "repair_attempts": 0, "cost_usd": 0.0}, {"model": "ScriptedModel", "input_tokens": 214, "output_tokens": 1, "repair_attempts": 0, "cost_usd": 0.0}]}}
```

**Verdict: PASS**

---

## SC-02 — PASS

_SC-02 — Happy path on the second endpoint (assets); singular noun._

Command / inputs:

```
/Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/slack-glue ask 'approved character assets' --model scripted --script '@reply name=emit_query\nendpoint = /api/v1/assets\nstatus = approved\nasset_type = character\n@end' --json
```

Exit code: `0`

Captured output:

```
{"ok": true, "request": "approved character assets", "query": {"endpoint": "/api/v1/assets", "filters": {"status": "approved", "asset_type": "character"}}, "result": {"endpoint": "/api/v1/assets", "filters": {"status": "approved", "asset_type": "character"}, "count": 1, "records": [{"id": "AST-HERO-01", "status": "approved", "asset_type": "character", "dept": "anim", "tags": ["hero", "rigged"]}]}, "text": "Found 1 record on /api/v1/assets (asset_type=character, status=approved):\n• AST-HERO-01 — status=approved, dept=anim, asset_type=character, tags=[hero, rigged]", "telemetry": {"calls": 2, "total_input_tokens": 366, "total_output_tokens": 13, "total_repair_attempts": 0, "total_cost_usd": 0.0, "by_call": [{"model": "ScriptedModel", "input_tokens": 163, "output_tokens": 12, "repair_attempts": 0, "cost_usd": 0.0}, {"model": "ScriptedModel", "input_tokens": 203, "output_tokens": 1, "repair_attempts": 0, "cost_usd": 0.0}]}}
```

**Verdict: PASS**

---

## SC-03 — PASS

_SC-03 — Clarify on out-of-vocabulary enum value (validator rejects)._

Command / inputs:

```
/Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/slack-glue ask 'all greenlit shots' --model scripted --script '@reply name=emit_query\nendpoint = /api/v1/shots\nstatus = greenlit\n@end' --json
```

Exit code: `0`

Captured output:

```
{"ok": false, "request": "all greenlit shots", "raw_intent": {"endpoint": "/api/v1/shots", "filters": {"status": "greenlit"}}, "issues": [{"code": "bad_enum", "field": "status", "message": "status: 'greenlit' is not one of ['approved', 'in_progress', 'omit', 'final', 'pending']"}], "text": "I couldn't map your request (\"all greenlit shots\") onto a valid query.\nHere's what tripped me up:\n• [status] status: 'greenlit' is not one of ['approved', 'in_progress', 'omit', 'final', 'pending']\nCould you rephrase or specify a known endpoint/field/value?", "telemetry": {"calls": 2, "total_input_tokens": 363, "total_output_tokens": 10, "total_repair_attempts": 0, "total_cost_usd": 0.0, "by_call": [{"model": "ScriptedModel", "input_tokens": 163, "output_tokens": 9, "repair_attempts": 0, "cost_usd": 0.0}, {"model": "ScriptedModel", "input_tokens": 200, "output_tokens": 1, "repair_attempts": 0, "cost_usd": 0.0}]}}
```

**Verdict: PASS**

---

## SC-04 — PASS

_SC-04 — Clarify on a field valid only on the WRONG endpoint._

Command / inputs:

```
/Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/slack-glue ask 'character shots' --model scripted --script '@reply name=emit_query\nendpoint = /api/v1/shots\nasset_type = character\n@end' --json
```

Exit code: `0`

Captured output:

```
{"ok": false, "request": "character shots", "raw_intent": {"endpoint": "/api/v1/shots", "filters": {"asset_type": "character"}}, "issues": [{"code": "unknown_field", "field": "asset_type", "message": "unknown filter 'asset_type' for /api/v1/shots; allowed: ['dept', 'reel', 'sequence', 'status', 'tags']"}], "text": "I couldn't map your request (\"character shots\") onto a valid query.\nHere's what tripped me up:\n• [asset_type] unknown filter 'asset_type' for /api/v1/shots; allowed: ['dept', 'reel', 'sequence', 'status', 'tags']\nCould you rephrase or specify a known endpoint/field/value?", "telemetry": {"calls": 2, "total_input_tokens": 361, "total_output_tokens": 10, "total_repair_attempts": 0, "total_cost_usd": 0.0, "by_call": [{"model": "ScriptedModel", "input_tokens": 162, "output_tokens": 9, "repair_attempts": 0, "cost_usd": 0.0}, {"model": "ScriptedModel", "input_tokens": 199, "output_tokens": 1, "repair_attempts": 0, "cost_usd": 0.0}]}}
```

**Verdict: PASS**

---

## SC-05 — PASS

_SC-05 — Clarify on an unknown (invented) endpoint._

Command / inputs:

```
/Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/slack-glue ask 'pull the edits' --model scripted --script '@reply name=emit_query\nendpoint = /api/v1/edits\n@end' --json
```

Exit code: `0`

Captured output:

```
{"ok": false, "request": "pull the edits", "raw_intent": {"endpoint": "/api/v1/edits", "filters": {}}, "issues": [{"code": "unknown_endpoint", "field": "endpoint", "message": "unknown endpoint '/api/v1/edits'; expected one of ['/api/v1/assets', '/api/v1/shots']"}], "text": "I couldn't map your request (\"pull the edits\") onto a valid query.\nHere's what tripped me up:\n• [endpoint] unknown endpoint '/api/v1/edits'; expected one of ['/api/v1/assets', '/api/v1/shots']\nCould you rephrase or specify a known endpoint/field/value?", "telemetry": {"calls": 2, "total_input_tokens": 360, "total_output_tokens": 7, "total_repair_attempts": 0, "total_cost_usd": 0.0, "by_call": [{"model": "ScriptedModel", "input_tokens": 163, "output_tokens": 6, "repair_attempts": 0, "cost_usd": 0.0}, {"model": "ScriptedModel", "input_tokens": 197, "output_tokens": 1, "repair_attempts": 0, "cost_usd": 0.0}]}}
```

**Verdict: PASS**

---

## SC-06 — PASS

_SC-06 — Zero-match is a valid result (ok=true, count=0), not a clarify._

Command / inputs:

```
/Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/slack-glue ask 'final shots in reel 3' --model scripted --script '@reply name=emit_query\nendpoint = /api/v1/shots\nstatus = final\nreel = 3\n@end' --json
```

Exit code: `0`

Captured output:

```
{"ok": true, "request": "final shots in reel 3", "query": {"endpoint": "/api/v1/shots", "filters": {"status": "final", "reel": 3}}, "result": {"endpoint": "/api/v1/shots", "filters": {"status": "final", "reel": 3}, "count": 0, "records": []}, "text": "No records matched on /api/v1/shots (reel=3, status=final). Scanned 10.", "telemetry": {"calls": 2, "total_input_tokens": 370, "total_output_tokens": 13, "total_repair_attempts": 0, "total_cost_usd": 0.0, "by_call": [{"model": "ScriptedModel", "input_tokens": 165, "output_tokens": 12, "repair_attempts": 0, "cost_usd": 0.0}, {"model": "ScriptedModel", "input_tokens": 205, "output_tokens": 1, "repair_attempts": 0, "cost_usd": 0.0}]}}
```

**Verdict: PASS**

---

## SC-07 — PASS

_SC-07 — Config error: unknown --model exits non-zero, single JSON object._

Command / inputs:

```
/Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/slack-glue ask anything --model banana --json
```

Exit code: `1`

Captured output:

```
{"error": "unknown --model 'banana'; choose scripted|mock|openai|anthropic"}
```

**Verdict: PASS**

---

## SC-08 — PASS

_SC-08 — serve is offline-safe; --check smoke-tests the whole pipeline._

Command / inputs:

```
/Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/slack-glue serve --json  ;  /Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/slack-glue serve --check --json
```

Exit code: `0`

Captured output:

```
{"transport": "offline", "note": "This command opens no socket. It prints how to wire a real Slack app.", "env": [{"name": "SLACK_BOT_TOKEN", "purpose": "Bot token (xoxb-...) used to post replies via chat.postMessage."}, {"name": "SLACK_SIGNING_SECRET", "purpose": "Verifies inbound Events API request signatures."}, {"name": "SLACK_APP_TOKEN", "purpose": "App-level token (xapp-...) if you use Socket Mode instead of HTTP."}], "wiring": ["Create a Slack app and add the 'app_mentions:read' and 'chat:write' bot scopes.", "Subscribe to the 'app_mention' bot event in Event Subscriptions.", "Point the Request URL at your handler (HTTP) or enable Socket Mode.", "On each app_mention, call slack_glue.parse_event(payload) then handle_app_mention(event, router, db).", "Post SlackReply.text back with chat.postMessage, threading on SlackReply.thread_ts."], "handler": "from slack_glue import Router, load_fixture, parse_event, handle_app_mention; reply = handle_app_mention(parse_event(payload), Router(model), load_fixture())", "endpoints": ["/api/v1/assets", "/api/v1/shots"], "filters": {"/api/v1/shots": ["dept", "reel", "sequence", "status", "tags"], "/api/v1/assets": ["asset_type", "dept", "status", "tags"]}}
{"transport": "offline", "note": "This command opens no socket. It prints how to wire a real Slack app.", "env": [{"name": "SLACK_BOT_TOKEN", "purpose": "Bot token (xoxb-...) used to post replies via chat.postMessage."}, {"name": "SLACK_SIGNING_SECRET", "purpose": "Verifies inbound Events API request signatures."}, {"name": "SLACK_APP_TOKEN", "purpose": "App-level token (xapp-...) if you use Socket Mode instead of HTTP."}], "wiring": ["Create a Slack app and add the 'app_mentions:read' and 'chat:write' bot scopes.", "Subscribe to the 'app_mention' bot event in Event Subscriptions.", "Point the Request URL at your handler (HTTP) or enable Socket Mode.", "On each app_mention, call slack_glue.parse_event(payload) then handle_app_mention(event, router, db).", "Post SlackReply.text back with chat.postMessage, threading on SlackReply.thread_ts."], "handler": "from slack_glue import Router, load_fixture, parse_event, handle_app_mention; reply = handle_app_mention(parse_event(payload), Router(model), load_fixture())", "endpoints": ["/api/v1/assets", "/api/v1/shots"], "filters": {"/api/v1/shots": ["dept", "reel", "sequence", "status", "tags"], "/api/v1/assets": ["asset_type", "dept", "status", "tags"]}, "check": {"request": "<@U0BOTID> get me all approved VFX shots from Reel 3 with green screen", "reply": {"kind": "results", "text": "Found 2 records on /api/v1/shots (dept=vfx, reel=3, status=approved, tags=[greenscreen]):\n• SHOT-0101 — status=approved, reel=3, dept=vfx, sequence=RDR, tags=[greenscreen, hero]\n• SHOT-0102 — status=approved, reel=3, dept=vfx, sequence=RDR, tags=[greenscreen, crowd]", "payload": {"endpoint": "/api/v1/shots", "filters": {"status": "approved", "reel": 3, "dept": "vfx", "tags": ["greenscreen"]}, "count": 2, "records": [{"id": "SHOT-0101", "status": "approved", "reel": 3, "dept": "vfx", "sequence": "RDR", "tags": ["greenscreen", "hero"]}, {"id": "SHOT-0102", "status": "approved", "reel": 3, "dept": "vfx", "sequence": "RDR", "tags": ["greenscreen", "crowd"]}]}, "channel": "C0VFXCHAN", "thread_ts": "1718900000.000100"}, "ok": true}}
```

**Verdict: PASS**

---

## SC-09 — PASS

_SC-09 — --json emits exactly one object; reproducible byte-for-byte._

Command / inputs:

```
/Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/slack-glue ask 'approved shots' --model scripted --script '@reply name=emit_query\nendpoint = /api/v1/shots\nstatus = approved\n@end' --json | wc -l
```

Exit code: `0`

Captured output:

```
line_count=1 ; byte_identical_rerun=True
{"ok": true, "request": "approved shots", "query": {"endpoint": "/api/v1/shots", "filters": {"status": "approved"}}, "result": {"endpoint": "/api/v1/shots", "filters": {"status": "approved"}, "count": 5, "records": [{"id": "SHOT-0101", "status": "approved", "reel": 3, "dept": "vfx", "sequence": "RDR", "tags": ["greenscreen", "hero"]}, {"id": "SHOT-0102", "status": "approved", "reel": 3, "dept": "vfx", "sequence": "RDR", "tags": ["greenscreen", "crowd"]}, {"id": "SHOT-0104", "status": "approved", "reel": 3, "dept": "vfx", "sequence": "RDR", "tags": ["fullcg", "hero"]}, {"id": "SHOT-0201", "status": "approved", "reel": 2, "dept": "vfx", "sequence": "ALY", "tags": ["greenscreen"]}, {"id": "SHOT-0303", "status": "approved", "reel": 1, "dept": "comp", "sequence": "INT", "tags": ["greenscreen", "matte"]}]}, "text": "Found 5 records on /api/v1/shots (status=approved):\n• SHOT-0101 — status=approved, reel=3, dept=vfx, sequence=RDR, tags=[greenscreen, hero]\n• SHOT-0102 — status=approved, reel=3, dept=vfx, sequence=RDR, tags=[greenscreen, crowd]\n• SHOT-0104 — status=approved, reel=3, dept=vfx, sequence=RDR, tags=[fullcg, hero]\n• SHOT-0201 — status=approved, reel=2, dept=vfx, sequence=ALY, tags=[greenscreen]\n• SHOT-0303 — status=approved, reel=1, dept=comp, sequence=INT, tags=[greenscreen, matte]", "telemetry": {"calls": 2, "total_input_tokens": 361, "total_output_tokens": 10, "total_repair_attempts": 0, "total_cost_usd": 0.0, "by_call": [{"model": "ScriptedModel", "input_tokens": 162, "output_tokens": 9, "repair_attempts": 0, "cost_usd": 0.0}, {"model": "ScriptedModel", "input_tokens": 199, "output_tokens": 1, "repair_attempts": 0, "cost_usd": 0.0}]}}
```

**Verdict: PASS**

---

## SC-10 — PASS

_SC-10 — Slack app_mention pipeline in plain Python (mention strip)._

Command / inputs:

```
/Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/python -c '<slack app_mention pipeline; handle_app_mention(parse_event(payload), Router(ScriptedModel([...])), load_fixture())>'
```

Exit code: `0`

Captured output:

```
{"kind": "results", "count": 2, "ids": ["SHOT-0101", "SHOT-0102"], "channel": "C0VFX", "thread_ts": "1700000000.000200", "text": "Found 2 records on /api/v1/shots (dept=vfx, reel=3, status=approved, tags=[greenscreen]):\n\u2022 SHOT-0101 \u2014 status=approved, reel=3, dept=vfx, sequence=RDR, tags=[greenscreen, hero]\n\u2022 SHOT-0102 \u2014 status=approved, reel=3, dept=vfx, sequence=RDR, tags=[greenscreen, crowd]", "has_api_key": false}
```

**Verdict: PASS**

---

## SC-11 — PASS

_SC-11 — Deterministic core is fully hermetic (regression gate)._

Command / inputs:

```
pytest -q tests ; python examples/ask_hermetic.py ; python examples/slack_event.py
```

Exit code: `0`

Captured output:

```
$ /Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/python -m pytest -q tests
........................................................................ [ 48%]
........................................................................ [ 96%]
.....                                                                    [100%]
149 passed in 0.18s


$ /Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/python examples/ask_hermetic.py  -> exit 0

$ /Users/ehernand/personal_projects/postpro-kit/slack-glue/.venv/bin/python examples/slack_event.py  -> exit 0
```

**Verdict: PASS**

---
