# Client onboarding UI

Configure a new Power BI dashboard/client for this agent, probe the live model,
validate the result and deploy the scheduled job — without touching a terminal.

The design brief is [`config-ui-execution-plan.md`](config-ui-execution-plan.md).
This document is what was built and how to run it.

```bash
cd powerbi-summary-agent
pip install -r requirements.txt -r requirements-ui.txt
python -m src.api.app                    # http://127.0.0.1:8020
python -m src.api.app --allow-deploy     # also expose the ARM endpoints
```

---

## Written for the person filling it in

Two hundred settings is not a form anyone can complete, and the names in this
repo (`azure_blob_prefix`, `summary_r6_enabled`, "reconciled") mean nothing to
the person onboarding a client. So the app's language is a deliverable in its
own right, and it is tested like one.

Every key carries three separate pieces of prose in `config_schema.py`:

| Field | Who reads it | Example (`azure_blob_prefix`) |
|---|---|---|
| `label` | everyone | "Folder name inside the container" |
| `help` | everyone | "Each client must have its own folder name here. If two clients share one, the second run of the day overwrites the first client's files - and nothing reports an error, so you would only notice days later when the app shows the wrong figures." |
| `detail` | maintainers, behind a "More detail" link | "Not dataset-scoped, unlike memory and history, which key on dataset_id and cannot collide." |

and a **tier** deciding whether the wizard shows it at all by default:

| Tier | Count | Meaning |
|---|---|---|
| `essential` | 31 | a new client cannot work until someone answers this |
| `standard` | 118 | worth a look; the default is usually right |
| `expert` | 53 | leave it alone unless you know exactly why |

The wizard opens on **essential only** - 31 questions spread over eight steps,
never more than 12 on any one - with a "Show" control to widen it. The counts
are asserted by the smoke test, so the form cannot quietly grow back.

Validation findings carry a plain `title` (the setting's label, not its key), a
message that says what will actually happen, and a `fix` that says what to do:

> **Folder name inside the container**
> The client 'cityflower' already saves its files to exactly this place:
> container 'insightgen', the top level. Whichever of the two runs second would
> overwrite the other's reports, and nothing would report an error.
> *What to do:* Give this client a folder name of its own - the client's own
> name is a good choice.

`replay_config_ui.py::test_plain_language` asserts this holds: that every
actionable error carries a fix, that the collision error names the other client
and the consequence rather than a key, and that internal vocabulary
(`reconcile`, `coverage_kind`, `TREATAS`) never reaches a message. The schema
replay asserts the same for help text, and that every key has a label and a
tier.

## Why it is a wizard and not a settings page

Several config values cannot be sensibly chosen before the model has been
inspected, and a wrong value degrades output **silently** rather than failing:

| Key | Unanswerable until the probe reports |
|---|---|
| `summary_focus_allowed_roles`, `summary_coverage_roles` | which hierarchy levels the model actually exposes |
| `summary_focus_role_aliases` | whether the generic patterns match this client's naming |
| `summary_dashboard_entity_role` | whether the entity dimension resolves at all |
| `insight_comparable_population`, `insight_excluded_entities` | which entities the model returns, and how they classify |
| `insight_recent_week_enabled`, `insight_daily_enabled` | whether a genuine business **date** axis exists |

So the order is the product: **Connect → Probe → Configure → Author → Deploy.**

---

## The schema is the single source of truth

`src/config_schema.py` catalogues every key — type, default, group, help text,
per-client flag, and the destructive-default traps. Two things read it:

- **`main.build_initial_state`** builds the graph state from
  `config_schema.state_defaults(cfg)`, so there is no second copy of a default
  to drift. Adding a key to the schema is the only edit needed for it to reach
  the pipeline.
- **The UI** renders its whole form from `GET /api/schema`, so it cannot carry
  its own stale copy of the key list.

`scripts/replay_config_schema.py` asserts the two directions cannot separate:
every config key any module reads is catalogued; every key any committed config
sets is catalogued; every schema default matches the literal fallback in `src/`;
`build_initial_state` emits exactly the `in_state` keys; and no key is offered
as configurable while being unreachable from a config.

That last check found two real problems on its first run:

- **`summary_llm_authoring_enabled`** was read as
  `state.get("summary_llm_authoring_enabled", True)` in two modules but never
  copied out of the config, so setting it in `config.json` did nothing. It is
  now `in_state`, with the same `True` default the fallback already produced.
- Two stale fallback literals disagreed with `main.py`
  (`summary_focus_max_rows_per_breakdown` 15 vs 12,
  `summary_dashboard_max_queries` 1 vs 2). Unreachable in a real run, since
  `build_initial_state` always populates both — but landmines. Aligned.

`insight_now_override` is deliberately **not** in the schema: it is a state-only
test hook, so offering it in the UI would be a lie.

---

## What the probe reports

`src/services/probe.py::run_probe` runs the pre-fork nodes plus the
focus-universe scan **in process**, into a temporary output and memory
location — no LLM call, no production memory/history write, no published
output. `scripts/probe_summary_universe.py` is a thin CLI over the same call,
so the two can never disagree about what a model supports.

- primary value metric, fact table, and whether the **entity dimension
  resolved**
- measure families, marking any whose prior is reconstructed as
  `current − change`
- resolved hierarchy roles with member counts, **`reconciled`** and
  `pool_capped`
- mirrored levels that were collapsed
- entity classification: comparable / excluded / current-only / prior-only
- candidate time axes and, with `--deep`, the per-axis verdict and `data_as_of`

It then translates those findings into **recommendations** — real config keys
with the evidence behind them, appliable individually or all at once — and into
**blocking errors**. A level that did not reconcile is a hard stop: its ranked
percentages would be wrong, and wrong quietly.

`--deep` (the "thorough check" tick-box in the UI) additionally runs
`baseline_coverage`, which is what gives the period resolver real trend
evidence. Without it the time-axis verdicts read "not probed" rather than being
guessed from metadata - guessing is exactly how a load/posting date gets treated
as business activity.

The findings are phrased for the reader, not the maintainer. "The parts do not
add up to the whole for: department" rather than "diagnostics_reconciled=false";
"These date columns record when data was loaded into the dashboard, not when
trading happened" rather than "batch_date". Each recommendation states the
evidence behind it, so applying it is a decision rather than an act of faith.

### Verified against the live scanb model

```
resolved roles:
   department       depth=20 column=DEPARTMENT     members=6  reconciled=True  pool_capped=False
   section          depth=25 column=SECTION        members=29 reconciled=True  pool_capped=False
   category         depth=30 column=CATEGORY_NAME  members=30 reconciled=True  pool_capped=True
entity dimension : UNRESOLVED
freshness        : data_as_of=2023-12-31 status=stale   (MIS_DEEP_DIVE2[UPDATED_DATE] verdict=batch_date)

recommended config:
   summary_focus_allowed_roles  = ["department","section","category"]
   summary_dashboard_entity_role = "department"   # entity=unresolved, so it must be pinned
   insight_recent_week_enabled  = false           # no current business-day axis
   insight_daily_enabled        = false
```

The entity recommendation independently reproduces what
`config/scanb/config.json` already pins by hand.

---

## Where files actually go

There is not one cloud destination, there are **three**, and they serve
different audiences. Sixteen storage fields in one column cannot convey that, so
the "Where it goes" step opens with a panel that resolves the settings into the
paths the next run will write. `src/services/storage.py::plan` mirrors the rules
in `azure_blob.py`, `insight_history.py` and `ai_content_publisher.py`.

**1. The agent's own store** — `azure_blob_*`. Every client shares one container
and is kept apart **only by `azure_blob_prefix`**:

```
insightgen/report_summary.json                      <- cityflower (prefix "")
insightgen/insight_history.json
insightgen/history/{dataset-id}/2026/08/13/{run}.json
insightgen/scanb/report_summary.json                <- scanb (prefix "scanb")
insightgen/scanb/history/{dataset-id}/…
```

The dated records are filed under the dataset ID and cannot clash. The four
files at the top are named identically for every client — which is why a prefix
collision is a blocking error, not a warning.

**2. Your app's storage** — `ai_content_*`. A container per client, named by
`ai_content_client`. **This is the one the web app reads.**

```
cityflower/ai-content/kpi/client/insights.json
cityflower/ai-content/kpi/client/alerts.json
cityflower/ai-content/report-summaries/client/{report-id}.json
cityflower/ai-content/report-summaries/client/{report-id}.html
```

The file name is the Power BI **report** ID, because that is what the app asks
for. An empty `ai_content_report_ids` means "discover them from Power BI", which
is what cityflower does; scanb pins one explicitly.

**3. Private memory** — `insight_memory_storage`, `summary_memory_storage`,
`azure_blob_memory_*`. Filed under the dataset ID, so clients cannot clash even
sharing a folder. No app ever reads it.

```
insightstate/{dataset-id}/memory.json
insightstate/summary-memory/{dataset-id}/memory.json
```

`replay_config_ui.py::test_storage_plan` pins the preview to the **real layout
observed in the live account**, so a change in either the path rules or the
preview shows up as a failing test rather than a misleading panel.

## What validation refuses

`src/services/validate.py`. Errors block a deployment; warnings do not, but
every one is something a reviewer should have read.

Each of these is reported with the setting's plain name, what will happen, and
what to do about it.

| Guard | Why it is an error, not a warning |
|---|---|
| `azure_blob_prefix` collision | not dataset-scoped: two clients sharing a container and prefix overwrite each other's `api/*.json`, days before anyone notices |
| `ai_content_client` container missing | the container is not created automatically; publishing just fails |
| `output_folder` ≠ `outputs` in a container | `/app` is root-owned; only `/app/outputs` is writable |
| `summary_r4_enabled` / `summary_r6_enabled` absent | reverts to the R1–R3 summary with no error — exactly how production drifted |
| unsupported IANA timezone, `insight_business_timezone: "auto"` | rejected loudly at run time |
| a focus role, entity role or entity code the probe did not find | it can never produce anything |
| `summary_now_override` set | a test hook that freezes "today" |
| no probe, or a failed probe, before a container deploy | a reconciliation failure must block |

**Env wins over config**, and a silent disagreement between the two is the most
likely deployment bug in the whole project. So the checks run against the
*resolved* values (`validate.effective`), and every disagreement is reported by
key. Presence is what counts, not truthiness: `AZURE_BLOB_PREFIX=""` overrides a
configured prefix back to the container root, which is where another client's
payloads already live — that case has its own test.

---

## Deployment

Three files become three job secrets; `src/container_entrypoint.py` materialises
them into `/app/outputs/runtime-config/` so the rulebooks land as siblings of
the config, exactly as `file_io` expects.

| Env var | File | Secret |
|---|---|---|
| `AGENT_CONFIG_B64` | `config.json` | `agent-config-b64` |
| `AGENT_RULES_B64` | `business_rules.md` | `agent-rules-b64` |
| `AGENT_SUMMARY_RULES_B64` | `summary_business_rules.md` | `agent-summary-rules-b64` |

Two details that break the obvious implementation:

- **The secrets exceed the command line.** A 45 KB rulebook base64s to ~61 KB,
  past the 32,767-character Windows limit, so `az containerapp job secret set`
  fails. `src/services/deploy.py` talks to ARM over HTTPS with the payload in
  the request body, where no such limit applies.
- **A naive PATCH drops secrets.** ARM replaces the whole array and never
  returns a stored value — only the name. `merge_secrets` reads the existing
  names, re-sends the ones it does not own *by name only* (which tells ARM to
  keep the stored value), preserves Key Vault references with their identity,
  and writes the union.

`POST /api/deploy/preview` renders the exact ARM body with every secret value
redacted, and makes no network call. Deployment endpoints are **off** unless
`--allow-deploy` / `CONFIG_UI_ALLOW_DEPLOY=1`: they need Contributor on the
resource group, and an unauthenticated page holding that could create arbitrary
jobs. `allowedJobNames` in the request body adds a server-side allow-list.

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/schema` | the catalogue the form renders from |
| GET | `/api/clients` | every `config/<client>/` on disk |
| GET/PUT/DELETE | `/api/clients/{name}` | read, write, remove a client |
| GET | `/api/clients/{name}/defaults` | a fresh config, every key explicit |
| POST | `/api/clients/{name}/clone` | start from an existing client |
| GET | `/api/clients/{name}/bundle` | the three files as a zip |
| GET | `/api/diff?left=&right=` | which keys two clients disagree on |
| POST | `/api/resolve-dataset` | report id → dataset id |
| POST | `/api/probe` | start a probe; returns a job id |
| GET | `/api/jobs/{id}?offset=N` | status plus the log lines after N |
| POST | `/api/validate` | blocking errors vs warnings |
| POST | `/api/deploy`, `/api/deploy/preview`, `/api/deploy/start` | ARM |

Long operations are jobs, not requests (`src/services/jobs.py`): a probe is
30–120 seconds, a full run 4–5 minutes. The runner is in-memory on purpose —
this is the local-first tool — but the submit/status/cancel interface is what a
hosted version re-points at a real queue.

---

## Writing a client

`src/services/clients.py` writes `config/<client>/` and preserves the existing
file's key order and line endings, so re-saving a hand-authored client produces
a **byte-identical** file and the diff shows only what changed. Verified against
`config/scanb/config.json`, `config/experiment/config.json` and
`config/config.json`.

Cloning copies both rulebooks and every shared key and deliberately **clears**
the per-client ones — carrying over `azure_blob_prefix` is precisely how one
client overwrites another's payloads.

A new client is written with **every key explicit**, because a key left out does
not error; it changes behaviour.

---

## Tests

```bash
python scripts/replay_config_schema.py    # the schema cannot drift from the code
python scripts/replay_config_ui.py        # services + API, no credentials needed
```

Both are offline. `replay_config_ui.py` covers the byte-identical round trip,
every destructive-default guard, env-vs-config disagreement, the ARM secret
merge, the probe's finding translation, the job runner, the API surface
(including that deployment stays shut by default), and the wording itself -
that every actionable error says what to do, and that no message leaks internal
vocabulary.

The rendered page has its own optional smoke test — the only JavaScript
dependency in the repo:

```bash
npm install jsdom
python -m src.api.app --port 8021 &
node scripts/smoke_config_ui.js src/api/static http://127.0.0.1:8021
```

It drives the real wizard through every screen inside jsdom and asserts the DOM
that comes out - including that the form opens on 31 questions rather than 202,
that role choices appear by their plain names, and that findings lead with the
setting's name and a "What to do".

---

## Not built

- **Hosting** (plan Phase 3.2–3.6). `Dockerfile.ui` builds the image and
  documents the internal-ingress + Entra ID + managed-identity shape, but
  nothing is deployed. Do not expose `--allow-deploy` without authentication.
- **Versioned config records in the `agent-config` blob container** (plan 2.5).
  `config/<client>/` plus git is the store today.
- **Post-run verification** (plan 2.4) beyond `/api/deploy/start` and the
  executions list; `scripts/audit_summary_dashboard.py` is still run by hand.
- **Plan Phase 4** — live preview, probe history, scheduled re-probe.
