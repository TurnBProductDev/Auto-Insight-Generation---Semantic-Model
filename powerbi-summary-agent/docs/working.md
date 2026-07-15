# How this works

Brief internal doc on connectivity and query flow. For node-by-node pipeline details see the root [CLAUDE.md](../../CLAUDE.md); for DAX-writing rules see [dax-authoring.md](dax-authoring.md).

## 1. How we connect to the semantic model

Auth is **headless MSAL (device/browser + refresh-token cache)** against the Power BI REST API — not `Connect-PowerBIServiceAccount` / PowerShell. An earlier PowerShell-subprocess approach hung because interactive login can't surface through a captured subprocess, so this was replaced.

- Client: `1950a258-227b-4e31-a9cf-717495945fc2` — the well-known **Azure PowerShell public client**. Needs no app registration.
- Tenant: `tenant_id` in the active `config.json`, overridden by the
  `POWERBI_TENANT_ID` environment variable. Both the parent MVP and full agent
  resolve the tenant from configuration rather than source code.
- Scope requested: `https://analysis.windows.net/powerbi/api/.default`.
- Token cache: repo-root **`.pbi_token_cache.json`** (gitignored — holds a refresh token). Both the MVP script and the agent's executor point at this same file, so only the very first run ever pops a browser window; every run after that is silent (`acquire_token_silent`).

```
app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
token = app.acquire_token_silent(...)  or  app.acquire_token_interactive(...)  on first run
```

Tenant-side requirements: **Execute Queries** setting must be enabled, and the signed-in user needs read/build permission on the target dataset.

## 2. How the semantic model is accessed (identifying it)

The model is identified purely by two GUIDs in `config/config.json`:

```json
{ "workspace_id": "...", "dataset_id": "..." }
```

`main.py` refuses to run if either is missing or still says `PASTE_...`. There's no discovery step — the model to summarize is always explicit config, not inferred.

## 3. How queries are made (the request itself)

Every query — metadata or business data — goes through the same REST call, `run_dax()` in [powerbi_executor.py](../src/tools/powerbi_executor.py):

```
POST https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets/{dataset_id}/executeQueries
Authorization: Bearer <token>
{ "queries": [{ "query": "<DAX text>" }], "serializerSettings": { "includeNulls": true } }
```

One query per HTTP call. The response's rows live at `results[0].tables[0].rows`; `extract_rows()` pulls them out. A subtlety: Power BI can return **HTTP 200 with an error embedded in `results[0].error`** (e.g. a measure whose formula references a column that no longer exists) — the executor checks for this explicitly and reclassifies it as `"failed"`, otherwise a real error would look like "succeeded with 0 rows."

There's also a PowerShell path (`execution_mode: "powershell"` → `scripts/execute_dax.ps1`) that shells out and reads back JSON, used only if you explicitly opt in; Python REST is the default and falls back automatically if PowerShell throws.

## 4. Where the DAX itself comes from

The model isn't queried blind — the agent reads it first, then writes DAX against what it actually found:

1. **Metadata read** (`metadata_reader.py`) — four fixed introspection queries, always via the Python/REST path regardless of `execution_mode`:
   `EVALUATE INFO.VIEW.TABLES()`, `INFO.VIEW.COLUMNS()`, `INFO.VIEW.MEASURES()`, `INFO.VIEW.RELATIONSHIPS()`.
   Columns get classified into `date_fields` / `numeric_fields` / `categorical_fields` by data-type keyword matching, hidden columns are dropped.
2. **Report understanding** (LLM) reads that metadata and infers domain, fact/dim tables, key measures/dimensions.
3. **DAX planner** (LLM) turns that understanding into a handful of free-text *intents* ("top 15 X by Y, descending") — not a fixed template menu.
4. **DAX generator** (LLM) writes the actual `EVALUATE ...` statement per intent.
5. **Validator** (deterministic, regex) extracts every `'Table'[Column]` / bare `[Measure]` token from the generated text and cross-checks it against the real metadata sets — this is the schema guardrail against a hallucinated table/column/measure name. Anything that doesn't check out is held back as `skipped_dax_queries` rather than run.
6. **Execution** runs every validated query one by one via `run_dax()`. Anything skipped by the validator, or that Power BI returned an error for, gets **one repair attempt**: the exact rejection/error text is handed back to the DAX generator to rewrite, revalidated, and re-run once before being given up on.
7. Results are normalized and handed to the report-writing LLMs.

## Quick mental model

```
config.json (workspace/dataset GUIDs)
        │
        ▼
MSAL token (cached, silent after first login)
        │
        ▼
executeQueries REST call ──► INFO.VIEW.* (metadata)
        │                         │
        │                         ▼
        │                 LLM plans + writes DAX against real table/column/measure names
        │                         │
        └────────────◄── validate (regex against metadata) ── repair-once-if-rejected
        │
        ▼
executeQueries REST call ──► business data rows
        │
        ▼
normalize → LLM summary → outputs/report_summary.md
```
