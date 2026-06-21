# slack-glue — Scenario Acceptance Suite

End-to-end acceptance scenarios for `slack-glue`, the cross-department intent
router that turns a messy Slack production request into a strict, validated query
and runs it against a mock ShotGrid.

## Scope and method

- **One evaluation method: pass/fail.** Every scenario below has an explicit,
  machine-checkable success criterion (exact exit code, specific `--json` field
  values, structural invariants on the reply payload). There are no rubric
  scenarios: `slack-glue` produces deterministic structured output, not free
  prose, so nothing here requires human judgment to score. A scenario passes iff
  *all* of its listed assertions hold; otherwise it fails.
- **Hermetic by construction.** The single model boundary (NL → schema) is driven
  by replykit's `ScriptedModel` / `MockModel`. No scenario opens a socket, hits a
  network, or calls a live LLM. `telemetry.total_cost_usd` is therefore `0.0`
  everywhere, which is itself an asserted invariant (proof the run was hermetic).
- **AI discipline.** The model is used *only* to translate fuzzy phrasing onto the
  closed schema vocabulary. All parsing, validation, timecode/enum/int coercion,
  query execution, counting, and reply formatting are deterministic code and are
  asserted byte-for-byte. No scenario adds a model call; scenarios that exercise
  "the model proposed X" feed X via a scripted `@reply emit_query` block.
- **Fixture.** The packaged fixture `src/slack_glue/fixtures/shotgrid.json` holds
  **10 shots + 6 assets**. Record counts in the criteria are derived from that
  fixture and are stable as long as it is unchanged.

### How to run

All commands use the repo venv. From the repo root:

```bash
.venv/bin/slack-glue ask "<request>" --model scripted --script "<@reply block>" --json
.venv/bin/slack-glue serve [--check] --json
.venv/bin/python -m pytest -q          # the deterministic core (149 tests)
.venv/bin/python examples/ask_hermetic.py
.venv/bin/python examples/slack_event.py
```

`--json` prints **exactly one JSON object** to stdout and nothing else (asserted
in SC-09). Pipe to `jq`/`python -c` to check fields. Exit code is `0` for any
routed outcome (hit *or* clarify) and non-zero only for a configuration error.

---

## Capability → scenario coverage

| Capability | Scenarios |
|---|---|
| NL → schema routing (the one model boundary, hermetic) | SC-01, SC-02, SC-10 |
| Deterministic schema validation (accept vs clarify) | SC-03, SC-04, SC-05 |
| Deterministic query execution (scalar eq + tag-superset AND) | SC-01, SC-02, SC-06 |
| Deterministic Slack-text + JSON formatting | SC-01, SC-06 |
| `ask` CLI `--json` contract (hit / clarify / config error) | SC-01, SC-03, SC-07, SC-09 |
| `serve` offline wiring + `--check` smoke test (no socket) | SC-08 |
| Slack `app_mention` pipeline → `SlackReply` | SC-08, SC-10 |
| Telemetry (token/cost accounting; hermetic = \$0.00) | SC-01 (and asserted across all) |
| Edge / failure handling | SC-04, SC-05, SC-06, SC-07, SC-11 |

---

## Scenarios

### SC-01 — Happy path: route → validate → execute → format (shots)

**Capability:** NL → schema routing; execution; formatting; `ask --json` hit contract.
**Kind:** pass/fail.

A producer asks for approved VFX shots in Reel 3 with green screen. The scripted
model emits the corresponding `emit_query` block; the deterministic core
validates, executes against the fixture, and formats.

```bash
.venv/bin/slack-glue ask "approved vfx shots in reel 3 with greenscreen" \
  --model scripted \
  --script $'@reply name=emit_query\nendpoint = /api/v1/shots\nstatus = approved\ndept = vfx\nreel = 3\ntags = greenscreen\n@end' \
  --json
```

**Success criteria (all must hold):**
- Exit code `0`.
- `.ok == true`.
- `.query.endpoint == "/api/v1/shots"` and `.query.filters == {"status":"approved","reel":3,"dept":"vfx","tags":["greenscreen"]}` — note `reel` is the **integer** `3` (not `"3"`), proving deterministic int coercion.
- `.result.count == 2`.
- The set of `.result.records[].id` equals `{"SHOT-0101","SHOT-0102"}`.
- `.text` starts with `Found 2 records on /api/v1/shots`.
- `.telemetry.total_cost_usd == 0.0` (hermetic).

---

### SC-02 — Happy path on the second endpoint (assets)

**Capability:** routing + execution across both endpoints; correct kind selection.
**Kind:** pass/fail.

```bash
.venv/bin/slack-glue ask "approved character assets" \
  --model scripted \
  --script $'@reply name=emit_query\nendpoint = /api/v1/assets\nstatus = approved\nasset_type = character\n@end' \
  --json
```

**Success criteria:**
- Exit code `0`; `.ok == true`.
- `.query.endpoint == "/api/v1/assets"`; `.query.filters == {"status":"approved","asset_type":"character"}`.
- `.result.count == 1` and `.result.records[0].id == "AST-HERO-01"`.
- `.text` starts with `Found 1 record on /api/v1/assets` (singular noun `record`, proving deterministic pluralization).
- `.telemetry.total_cost_usd == 0.0`.

---

### SC-03 — Clarify on out-of-vocabulary enum value

**Capability:** deterministic schema validation rejects a value the model invented; field-scoped clarify.
**Kind:** pass/fail.

The model emits `status = greenlit`, which is not a member of the `status` enum.
The validator (not the model) rejects it.

```bash
.venv/bin/slack-glue ask "all greenlit shots" \
  --model scripted \
  --script $'@reply name=emit_query\nendpoint = /api/v1/shots\nstatus = greenlit\n@end' \
  --json
```

**Success criteria:**
- Exit code `0` (a clarify is a normal outcome, not an error).
- `.ok == false`.
- `.issues` has exactly one element with `.issues[0].code == "bad_enum"` and `.issues[0].field == "status"`.
- `.issues[0].message` contains `'greenlit' is not one of` and lists the five valid members (`approved`, `in_progress`, `omit`, `final`, `pending`).
- `.raw_intent.filters.status == "greenlit"` (the rejected proposal is preserved for debugging).
- No `result`/`records` key is present (nothing was executed).
- `.telemetry.total_cost_usd == 0.0`.

---

### SC-04 — Clarify on a field that is unknown for the chosen endpoint

**Capability:** per-endpoint field-vocabulary enforcement (a valid field on the *wrong* endpoint).
**Kind:** pass/fail (edge).

`asset_type` is a real schema field, but only for `/api/v1/assets`. Emitted
against `/api/v1/shots` it must be rejected as an unknown filter — exercising the
deterministic `unknown_field` path (this is the field key that the `emit_query`
tool accepts, so routing reaches validation rather than failing earlier).

```bash
.venv/bin/slack-glue ask "character shots" \
  --model scripted \
  --script $'@reply name=emit_query\nendpoint = /api/v1/shots\nasset_type = character\n@end' \
  --json
```

**Success criteria:**
- Exit code `0`; `.ok == false`.
- Exactly one issue: `.issues[0].code == "unknown_field"`, `.issues[0].field == "asset_type"`.
- `.issues[0].message` lists the allowed shot fields: `['dept', 'reel', 'sequence', 'status', 'tags']`.
- `.telemetry.total_cost_usd == 0.0`.

---

### SC-05 — Clarify on an unknown endpoint

**Capability:** the endpoint allow-list is a closed contract; an invented endpoint is rejected.
**Kind:** pass/fail (edge).

```bash
.venv/bin/slack-glue ask "pull the edits" \
  --model scripted \
  --script $'@reply name=emit_query\nendpoint = /api/v1/edits\n@end' \
  --json
```

**Success criteria:**
- Exit code `0`; `.ok == false`.
- Exactly one issue: `.issues[0].code == "unknown_endpoint"`, `.issues[0].field == "endpoint"`.
- `.issues[0].message` lists the two real endpoints `['/api/v1/assets', '/api/v1/shots']`.
- `.telemetry.total_cost_usd == 0.0`.

---

### SC-06 — Zero-match is a valid result, not a clarify

**Capability:** execution semantics + zero-match formatting; the accept/zero-result distinction.
**Kind:** pass/fail (edge).

A perfectly valid query that simply matches no records must succeed (`ok=true`,
`count=0`) and render the deterministic "no records matched" line with the scan
count — it must **not** be conflated with a clarify. (`status=final, reel=3`
matches nothing in the fixture.)

```bash
.venv/bin/slack-glue ask "final shots in reel 3" \
  --model scripted \
  --script $'@reply name=emit_query\nendpoint = /api/v1/shots\nstatus = final\nreel = 3\n@end' \
  --json
```

**Success criteria:**
- Exit code `0`; `.ok == true` (valid query, even with no matches).
- `.result.count == 0` and `.result.records == []`.
- `.text == "No records matched on /api/v1/shots (reel=3, status=final). Scanned 10."` (exact string: filters rendered sorted, scan count = 10 shots).
- `.telemetry.total_cost_usd == 0.0`.

---

### SC-07 — Configuration error: unknown `--model` exits non-zero, single JSON object

**Capability:** `ask --json` config-error contract; exit-code discipline.
**Kind:** pass/fail (failure case).

```bash
.venv/bin/slack-glue ask "anything" --model banana --json; echo "exit=$?"
```

**Success criteria:**
- Exit code **non-zero** (`1`).
- stdout is **exactly one** JSON object of the form `{"error": "..."}` and contains no other key (`ok`, `result`, `issues` all absent).
- `.error` contains `unknown --model 'banana'` and lists the valid choices `scripted|mock|openai|anthropic`.
- Nothing is printed to stdout besides that single object (the contract holds even on the error path).

---

### SC-08 — `serve` is offline-safe and `--check` smoke-tests the whole pipeline

**Capability:** `serve` wiring instructions + `--check` end-to-end smoke run; no socket / no network.
**Kind:** pass/fail.

```bash
.venv/bin/slack-glue serve --json                 # plain wiring
.venv/bin/slack-glue serve --check --json         # wiring + offline smoke run
```

**Success criteria — `serve --json`:**
- Exit code `0`.
- `.transport == "offline"`; `.endpoints == ["/api/v1/assets","/api/v1/shots"]`.
- `.filters` maps each endpoint to its sorted field list (shots: `["dept","reel","sequence","status","tags"]`; assets: `["asset_type","dept","status","tags"]`).
- No `check` key is present (no pipeline was run).

**Success criteria — `serve --check --json`:**
- Exit code `0`.
- `.check.ok == true`.
- `.check.reply.kind == "results"`.
- `.check.reply.payload.count == 2` (the built-in sample mention resolves to the same 2 Reel-3 greenscreen shots as SC-01).
- `.check.reply.thread_ts == "1718900000.000100"` (the reply threads on the triggering message `ts`, proving the `app_mention` → `SlackReply` threading path).

---

### SC-09 — `--json` emits exactly one object on stdout (machine-composability)

**Capability:** the cross-cutting `--json` single-object interop contract.
**Kind:** pass/fail.

```bash
.venv/bin/slack-glue ask "approved shots" \
  --model scripted \
  --script $'@reply name=emit_query\nendpoint = /api/v1/shots\nstatus = approved\n@end' \
  --json | wc -l
```

**Success criteria:**
- stdout is exactly **1** line (one newline-terminated JSON object).
- That line parses as a single JSON object (e.g. `python -c 'import sys,json; json.loads(sys.stdin.read())'` exits `0`).
- Re-running the identical command yields byte-identical stdout (determinism / reproducibility).

---

### SC-10 — Slack `app_mention` pipeline in plain Python (mention strip → reply)

**Capability:** `parse_event` → `handle_app_mention` → `SlackReply`; mention stripping; reply `kind` tagging.
**Kind:** pass/fail.

Drives the full Slack path directly (this is what the `slack_event.py` example
demonstrates and what `test_slack.py` covers), with a `ScriptedModel`, against a
standard Events-API envelope. The leading `<@BOTID>` mention must be stripped
before routing.

```python
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
print(reply.kind, reply.payload["count"], reply.channel, reply.thread_ts)
```

**Success criteria:**
- `reply.kind == "results"`.
- `reply.payload["count"] == 2`; record ids `{"SHOT-0101","SHOT-0102"}`.
- `reply.channel == "C0VFX"` and `reply.thread_ts == "1700000000.000200"` (threads on the event `ts`).
- `reply.text` starts with `Found 2 records on /api/v1/shots`.
- Runs with no network and no API key (hermetic; the only model is the `ScriptedModel`).

---

### SC-11 — Deterministic core is fully hermetic (regression gate)

**Capability:** the whole deterministic core; CI hermeticity guarantee.
**Kind:** pass/fail (regression / edge gate).

```bash
.venv/bin/python -m pytest -q
.venv/bin/python examples/ask_hermetic.py
.venv/bin/python examples/slack_event.py
```

**Success criteria:**
- `pytest` exits `0` with **0 failures** (current suite: 149 passed).
- Both example scripts exit `0`.
- The run makes no network call and requires no API key (enforced by construction:
  the only model in any of these paths is a replykit `ScriptedModel` / `MockModel`).

---

## Pass condition for the suite

The suite **passes** iff every scenario SC-01 … SC-11 passes (all assertions in
each scenario hold). Any failed assertion fails that scenario and the suite.
Because the evaluation is uniformly pass/fail over deterministic structured
output, the result is reproducible: the same fixture + same scripted blocks yield
the same verdict on every run, with `total_cost_usd == 0.0` throughout.
