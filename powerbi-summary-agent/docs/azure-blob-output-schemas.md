# Azure Blob output schemas

This document describes every JSON document that the current pipeline is
configured to persist in Azure Blob Storage. It is intended for application
developers and for teams using these documents as context for an LLM.

## 1. Current Azure layout

The active `config/config.json` enables both Azure upload and Azure-backed
insight memory.

| Purpose | Container | Blob name | Update behavior | Intended consumer |
|---|---|---|---|---|
| Latest report summary | `insightgen` | `report_summary.json` | Replaced after each successful run | UI, API, LLM |
| Latest KPI insight cards | `insightgen` | `kpi_insights.json` | Replaced after each successful run | UI, API, LLM |
| Current insight-history feed | `insightgen` | `insight_history.json` | ETag-protected merge | UI, API, LLM |
| Immutable run history | `insightgen` | `history/{datasetId}/{YYYY}/{MM}/{DD}/{runId}.json` | Created once; never overwritten | Audit, recovery, LLM history |
| Cross-run novelty memory | `insightstate` | `{datasetId}/memory.json` | ETag-protected replacement | Agent internals only |
| Client KPI cards | `cityflower` | `ai-content/kpi/client/insights.json` | Replaced after each successful run | FastAPI / web app |
| Client seven-day alerts | `cityflower` | `ai-content/kpi/client/alerts.json` | ETag-protected rolling merge | FastAPI / web app |
| Client report summary | `cityflower` | `ai-content/report-summaries/client/{reportId}.json` | Replaced after each successful run | FastAPI / web app |
| Client report summary HTML | `cityflower` | `ai-content/report-summaries/client/{reportId}.html` | Replaced after each successful run | FastAPI / web app |

The configured storage account is `turnbtestblobstorage`, the shared blob
prefix is currently empty, and the active dataset ID is
`b3458a38-ad83-4e9a-b2f2-39d15c6aa22c`.

All of these blobs are UTF-8 JSON with the `application/json` content type.
Azure publication happens after the analytical graph completes. The latest API
files and history are published before the private memory is advanced, so a
failed delivery cannot make the next run suppress insights that users never
received.

The three client-facing JSON blobs are wrapped as
`{schemaVersion, client, generatedFor, generatedAt, expiresAt, sourceDatasets, payload}`;
FastAPI returns only `payload`. The HTML sibling is not wrapped and carries the
same provenance in Blob metadata. No private memory document is published into
a client container.

> Configuration proves that Azure upload is enabled; it does not by itself
> prove that a particular run reached Azure. Callers should monitor the run's
> upload status/logs for authentication, network, or ETag-conflict failures.

## 2. Which document should a consumer use?

| Need | Recommended document |
|---|---|
| Explain the current overall result | `report_summary.json` |
| Show or discuss the current actionable findings | `kpi_insights.json` |
| Review insights across multiple run dates | `insight_history.json` |
| Recover the exact published result of one execution | Immutable history blob |
| Decide whether a finding has already been reported | Private `memory.json` |

For a normal LLM assistant, provide the first three documents. Do **not** provide
`memory.json` unless the LLM is specifically implementing or diagnosing the
novelty policy. Memory is internal state, not a customer-facing knowledge base.

## 3. `report_summary.json`

### Purpose and lifecycle

This is the latest executive summary. It is a single JSON object and is
overwritten on every successfully published run. One memory-selected summary
perspective supplies the evidence; the LLM authors the headline and section
text, while code injects metric values and tones from that evidence. Unsupported
figures are rejected. The final object is validated with unknown fields
forbidden.

The corresponding application contract is `/report/summary?format=json`.

### Shape

```json
{
  "title": "AI Summary",
  "generatedAt": "2026-07-22",
  "headline": "Revenue increased, a change of +3.5M, while quantity declined.",
  "metrics": [
    {
      "label": "Revenue change",
      "value": "+3.5M",
      "tone": "positive"
    }
  ],
  "sections": [
    {
      "heading": "What's working",
      "tone": "positive",
      "points": [
        "Revenue change was +3.5M."
      ]
    },
    {
      "heading": "Risks",
      "tone": "warning",
      "points": ["Quantity change was -216.2K."]
    },
    {
      "heading": "Recommended actions",
      "tone": "info",
      "points": ["Investigate the quantity decline and confirm whether it persists."]
    }
  ]
}
```

### Fields

| JSON path | Type | Required | Meaning |
|---|---|---:|---|
| `title` | string | Yes | Display title, currently defaulting to `AI Summary`. |
| `generatedAt` | string | Yes | Payload creation date in `YYYY-MM-DD` form. This is the process clock's date, not necessarily the data watermark. |
| `headline` | string | Yes | One current-run executive takeaway that includes the primary evidence-backed figure. |
| `metrics` | array | Yes | Up to four evidence-backed supporting tiles. May be empty when no usable metric fact exists. |
| `metrics[].label` | string | Yes | Short presentation label for the code-injected evidence value. |
| `metrics[].value` | string | Yes | Presentation-formatted value, such as `122.6M`, `-1.2%`, or explanatory text. It is **not a numeric field**. |
| `metrics[].tone` | enum string | Yes | One of `positive`, `critical`, `warning`, `info`, or `teal`. This is a display hint, not a measured severity score. |
| `sections` | array | Yes | Ordered narrative sections. |
| `sections[].heading` | string | Yes | Normally the stable layout headings `What's working`, `Risks`, and `Recommended actions`. |
| `sections[].tone` | enum string | Yes | Same tone enum as metric tiles. |
| `sections[].points` | string array | Yes | Ordered, presentation-ready bullet text. All figures should be preserved verbatim when an LLM restates them. |

### LLM interpretation

- Use `headline` for the first answer sentence and `sections[].points` for
  supporting context.
- Preserve values exactly as strings. Do not silently expand `122.6M` into a
  guessed raw number or recalculate percentages from rounded display values.
- The normal completed-summary taxonomy is fixed and ordered: `What's working`,
  `Risks`, then `Recommended actions`. Honest no-new-perspective states may use a
  minimal `Summary` section instead.
- `generatedAt` says when this JSON was built. Statements about data freshness
  should come from the content itself unless a separate data-as-of field is
  added later.

## 4. `kpi_insights.json`

### Purpose and lifecycle

This is the latest set of material insight cards. Its root is a JSON array, not
an object. It is overwritten on every successfully published run. Card prose is
LLM-authored from deterministic signal facts, while values, percentages,
directions, severity enums, and stat figures are filled by code. Unknown fields
and invalid enum values are rejected before publication.

The corresponding application contract is `/kpi/insights`.

### Shape

```json
[
  {
    "id": 1,
    "severity": "warning",
    "category": "Quantity",
    "metric": "Example segment",
    "value": "-208.3K",
    "delta": "97.2%",
    "deltaDirection": "down",
    "description": "Example segment sold 208.3K fewer units, accounting for about 97.2% of the total decline in unit sales. The decline came mainly from fewer items being sold.",
    "displayTime": "3:18 PM",
    "isoDate": "2026-07-22",
    "comparisonLabel": "of the total decline in unit sales",
    "insight": {
      "title": "Example unit drag",
      "summary": "The decline was concentrated in this segment.",
      "stats": [
        {"label": "Unit sales change", "value": "-208.3K"},
        {"label": "Share of unit sales decline", "value": "97.2%"}
      ],
      "action": "Review the detailed category and store breakdown."
    }
  }
]
```

### Card fields

| JSON path | Type | Required | Meaning |
|---|---|---:|---|
| `[]` | array | Yes | Zero or more current-run cards. An empty array means no cards were generated for that run. |
| `[].id` | integer | Yes | One-based display order for this payload. It is regenerated every run and is **not a stable insight ID**. |
| `[].severity` | enum string | Yes | One of `critical`, `warning`, `positive`, or `info`. Determined by signal kind and magnitude. |
| `[].category` | string | Yes | Short display family such as `Revenue`, `Quantity`, `Transactions`, or `Data Quality`. |
| `[].metric` | string | Yes | The affected business segment/member. Despite the field name, this is often a store, category, or product group rather than a Power BI measure name. |
| `[].value` | string | Yes | Signed, compact display impact, for example `+766.3K` or `-560.6K`. Not a raw number. |
| `[].delta` | string | Yes | Absolute display magnitude for the comparison described by `comparisonLabel`; may be an empty string when no comparison applies. |
| `[].deltaDirection` | enum string | Yes | `up` or `down`; this carries the sign for the front-card `delta`. |
| `[].description` | string | Yes | Plain-language main message stating what changed, the exact amount, the percentage in context when available, and the main evidenced contributor. |
| `[].displayTime` | string | Yes | Payload-generation time in 12-hour display form. It uses the process clock and has no offset in the value. |
| `[].isoDate` | string | Yes | Payload-generation date in `YYYY-MM-DD` form. |
| `[].comparisonLabel` | string | Yes | Defines what `delta` means. This field must be read together with `delta`. |
| `[].insight` | object | Yes | Expanded content for the back/detail view of the card. |

### Expanded insight fields

| JSON path | Type | Required | Meaning |
|---|---|---:|---|
| `[].insight.title` | string | Yes | Short insight title. |
| `[].insight.summary` | string | Yes | Plain-language interpretation of the evidence. |
| `[].insight.stats` | array | Yes | Up to three display statistics. |
| `[].insight.stats[].label` | string | Yes | Contextual stat label, such as `Revenue change`, `Share of revenue increase`, `Offset to revenue increase`, `Change from units sold`, `Week over week`, `Vs expected`, or `Segments`. |
| `[].insight.stats[].value` | string | Yes | Display-formatted statistic. Calculation shorthand is not exposed in this manager-facing field. |
| `[].insight.action` | string | Yes | Recommended follow-up analysis or business check; it is not an automatically executed action. |

### Conditional meaning of `delta`

`delta` does not always use the same denominator. Always inspect
`comparisonLabel`.

| Signal type | `delta` means | Typical `comparisonLabel` |
|---|---|---|
| Normal current/prior finding | Absolute contribution to or offset against the total increase/decline | `of the total increase in revenue`, `of the total decline in unit sales`, or `offsetting the total increase in revenue` |
| Concentration finding | Share of the current metric | `of current revenue` |
| Calendar-week finding | Absolute week-over-week percent | `week over week (from YYYY-MM-DD)` |
| Rolling-week finding | Absolute percent versus the prior seven days | `vs the prior 7 days (ending YYYY-MM-DD)` |
| Daily incident | Absolute deviation as a percent of expected | `vs expected (start..end)` |
| No comparable delta | Empty string | `current period` |

The front-card `delta` is an absolute magnitude; use `deltaDirection` for the
segment movement. The contextual label explains whether the segment contributed
to the overall increase/decline or moved against it.

### LLM interpretation

- Treat each array element as one independent current finding.
- Use `description` for a short answer; use `insight.summary` for detail and
  `insight.action` only when the user asks what to do next.
- Never compare two `delta` fields without first checking both
  `comparisonLabel` values.
- Never join cards across runs using `id`. This schema intentionally contains
  no stable story key.
- `severity` is a presentation classification. It is not a probability,
  confidence score, or priority ranking.

## 5. `insight_history.json`

### Purpose and lifecycle

This is the minimal, app-facing history projection. It groups completed runs by
local calendar date and keeps the newest dates and runs first. The producer
updates it with an Azure ETag (`If-Match`) and retries on concurrent changes, so
two overlapping publishers do not silently lose a run.

Unlike immutable history entries, the feed deliberately omits dataset ID, run
ID, full timestamps, and counts. It is optimized for one UI/API read.

### Shape

```json
{
  "timezone": "Asia/Kolkata",
  "history": [
    {
      "date": "2026-07-22",
      "runs": [
        {
          "time": "15:19:12",
          "status": "completed",
          "insights": [
            {
              "heading": "Example segment was the clearest unit drag.",
              "content": "The evidence showed the decline was concentrated..."
            }
          ]
        }
      ]
    }
  ]
}
```

### Fields

| JSON path | Type | Required | Meaning |
|---|---|---:|---|
| `timezone` | string | Yes | IANA timezone used to interpret every date/time in the feed. Currently `Asia/Kolkata`. |
| `history` | array | Yes | Date groups, newest first. |
| `history[].date` | string | Yes | Local run date in `YYYY-MM-DD` form. |
| `history[].runs` | array | Yes | Runs for that date, newest first. |
| `history[].runs[].time` | string | Yes | Local time in `HH:MM:SS` 24-hour form. Combine it with the enclosing `date` and root `timezone`. |
| `history[].runs[].status` | enum-like string | Yes | Currently `completed` or `no_new_insights`. Consumers should tolerate future status values. |
| `history[].runs[].insights` | array | Yes | Presentation-ready insight paragraphs. Empty when status is `no_new_insights`. |
| `history[].runs[].insights[].heading` | string | Yes | Bold takeaway parsed from the final insight report. |
| `history[].runs[].insights[].content` | string | Yes | Supporting evidence and interpretation for that takeaway. |

### LLM interpretation

- Use this file for questions such as “what changed between runs?” or “what was
  reported last week?”
- Respect the array ordering, but use `date` plus `time` for explicit sorting.
- A repeated business topic in two runs is not guaranteed to have identical
  wording. This feed has no stable identity field; exact novelty identity lives
  only in private memory.
- `no_new_insights` means the completed report yielded no insight paragraphs. It
  does not mean the underlying business data was absent or unchanged.

## 6. Immutable history entry

### Purpose and lifecycle

Each completed report also creates one self-contained recovery/audit document.
The blob is uploaded with `overwrite=false`. A retry with the same `runId` keeps
the originally published document unchanged.

Current path pattern:

```text
insightgen/history/b3458a38-ad83-4e9a-b2f2-39d15c6aa22c/YYYY/MM/DD/runId.json
```

In Azure Container Apps Jobs, `runId` normally comes from
`CONTAINER_APP_JOB_EXECUTION_NAME`. Other schedulers can set
`INSIGHT_HISTORY_RUN_ID`. Local fallback IDs use a timestamp with microseconds
and UTC offset. Unsafe path characters are replaced.

### Shape

```json
{
  "schemaVersion": 1,
  "datasetId": "b3458a38-ad83-4e9a-b2f2-39d15c6aa22c",
  "runId": "example-run-id",
  "date": {
    "iso": "2026-07-22",
    "display": "22 July 2026",
    "timezone": "Asia/Kolkata"
  },
  "runAt": "2026-07-22T15:19:12+05:30",
  "status": "completed",
  "insightCount": 1,
  "insights": [
    {
      "heading": "Example segment was the clearest unit drag.",
      "content": "The evidence showed the decline was concentrated..."
    }
  ]
}
```

### Fields

| JSON path | Type | Required | Meaning |
|---|---|---:|---|
| `schemaVersion` | integer | Yes | History-entry contract version; currently `1`. |
| `datasetId` | string | Yes | Power BI semantic-model/dataset identifier. |
| `runId` | string | Yes | Idempotency and audit identifier for this execution. |
| `date.iso` | string | Yes | Local calendar date, `YYYY-MM-DD`. |
| `date.display` | string | Yes | Human-readable date, for example `22 July 2026`. |
| `date.timezone` | string | Yes | IANA timezone used for the run date. |
| `runAt` | string | Yes | ISO 8601/RFC 3339-style timestamp with seconds and UTC offset. This is the authoritative run timestamp. |
| `status` | enum-like string | Yes | `completed` when at least one insight exists; otherwise `no_new_insights`. |
| `insightCount` | integer | Yes | Must equal `insights.length`. |
| `insights` | array | Yes | Same heading/content objects exposed in the history feed. |
| `insights[].heading` | string | Yes | Insight takeaway. |
| `insights[].content` | string | Yes | Full supporting paragraph. |

For a new integration, prefer this document over reconstructing a run from the
minimal feed when stable execution identity, dataset identity, or a full
timestamp is required.

## 7. Private `{datasetId}/memory.json`

### Purpose and lifecycle

This document is the agent's internal cross-run state. It prevents the same
deterministic story from being reported repeatedly and carries daily/rolling
observation cursors. It lives in the separate `insightstate` container.

At the beginning of a run, the blob is downloaded into an isolated runtime
folder. After the real reports, API payloads, and history have all been
delivered, the committed memory is uploaded using the ETag obtained during the
download. A concurrent writer causes a conflict instead of a lost update. A
corrupt memory is never treated as empty and is never overwritten silently.

This is **not** an API response and should not be exposed to an end-user LLM.
Its keys and optional fields serve suppression logic and may evolve more readily
than the presentation contracts.

### Root shape

```json
{
  "schema_version": 1,
  "watermark": "2026-07-21",
  "records": {
    "high:v1:0123...cdef": {
      "level": "high",
      "first_reported": "2026-07-22",
      "last_reported": "2026-07-22",
      "times_reported": 1,
      "re_alert_count": 0,
      "kind": "business",
      "segment": ["example segment"],
      "metric": "model::revenue",
      "dimension": ["'model'[category]"],
      "analysis_type": "change_contribution",
      "period_anchor": "2026-07",
      "direction": -1,
      "impact_value": -208269.4391,
      "description": "Deterministic source finding...",
      "covered_story_keys": ["high:v1:0123...cdef"]
    }
  },
  "journal": {
    "2026-07-22": [
      {
        "story_key": "high:v1:0123...cdef",
        "level": "high",
        "id": "example_signal_id",
        "description": "Deterministic source finding...",
        "impact_value": -208269.4391,
        "kind": "business"
      }
    ]
  },
  "daily_cursor": {},
  "rolling_state": {}
}
```

### Root fields

| JSON path | Type | Required | Meaning |
|---|---|---:|---|
| `schema_version` | integer | Yes | Internal memory schema version; currently `1`. Note the snake_case name. |
| `watermark` | string or null | Yes | Greatest derived business-data date committed with reported signals. It is a data watermark, not a run timestamp. |
| `records` | object/map | Yes | Story key to suppression record. |
| `journal` | object/map | Yes | Report date (`YYYY-MM-DD`) to the signals reported that day. Same-day runs merge by story key. |
| `daily_cursor` | object/map | Yes | Business-date-axis reference to latest fully analyzed effective date. Often empty when daily analysis is disabled. |
| `rolling_state` | object/map | Yes | Rolling story key to the latest observed rolling state. Often empty when rolling-week analysis is disabled. |

### Story keys

Each `records` key has this form:

```text
{level}:v1:{64-character SHA-256 hex digest}
```

`level` is normally one of `high`, `period`, `recent_week`,
`recent_week_rolling`, or `daily`. The hash is derived from canonical stable
identity fields such as dataset, comparable scope, analysis type, canonical
metric, dimension/axis, segment, and the relevant period anchor. Mutable values
such as direction, impact, daily episode end, and rolling percent are excluded
from the hash so the same story keeps one identity as its observed value changes.

Story keys are opaque. Consumers must not attempt to reverse them or recreate
them with a different normalization implementation.

### Primary story record

| Field | Type | Presence | Meaning |
|---|---|---|---|
| `level` | string | Always | Temporal/story level. |
| `first_reported` | date string | Always | First report date. |
| `last_reported` | date string | Always | Most recent report date. |
| `times_reported` | integer | Always | Number of commits that reported this story. |
| `re_alert_count` | integer | Always | Reserved re-alert counter; currently initialized to zero and should not be used as the sole re-alert indicator. |
| `kind` | string | Primary records | Usually `business` or `data_quality`. |
| `segment` | string array | Primary records | Canonical, normalized segment members used for identity. |
| `metric` | string | Primary records | Canonical metric family/bundle, not necessarily a display label. |
| `dimension` | string array | High-level records | Canonical grouping references. |
| `analysis_type` | string | Primary records | Deterministic finding type. |
| `period_anchor` | string | High/period records | Reporting bucket used in identity, such as `2026-07`. |
| `axis` | string | Daily/weekly records | Canonical business date axis. |
| `anchor` | string | Period/calendar-week/daily records | Period label, week start, or incident start used in identity. |
| `week_start`, `week_end` | date string | Weekly records | Observed completed window bounds. |
| `change_pct` | number | Rolling records | Latest structured rolling change percent. |
| `episode_end` | date string | Daily records | Latest incident end; mutable and not part of the story hash. |
| `peak_z` | number | Daily records | Daily incident peak robust-z value. |
| `direction` | integer | Primary records | `-1`, `0`, or `1` based on the signed impact. |
| `impact_value` | number or null | Primary records | Raw deterministic impact. Unlike the public payload values, this is numeric. |
| `description` | string | Primary records | Deterministic source finding, not the final presentation paragraph. |
| `covered_story_keys` | string array | Primary records | Primary plus any related stories merged into the reported signal. |

A related story that was merged into another signal has a deliberately smaller
record containing the common report counters plus `merged_into`, whose value is
the primary story key. This is enough to suppress the related story in a future
run without duplicating the full content.

### Journal entry

| Field | Type | Meaning |
|---|---|---|
| `story_key` | string | Stable story identity. |
| `level` | string | Story level. |
| `id` | string or null | Signal ID from that run; useful for diagnosis but not stable cross-run identity. |
| `description` | string or null | Deterministic finding text. |
| `impact_value` | number or null | Raw signed impact. |
| `kind` | string | Usually `business` or `data_quality`. |

### Rolling-state value

When rolling monitoring is enabled, each `rolling_state[storyKey]` value has:

```json
{
  "active": true,
  "impact_value": -12345.0,
  "change_pct": -8.4,
  "direction": -1,
  "observed_through": "2026-07-21"
}
```

The snapshot advances forward only. It is recorded even when the reading was
observed but not selected for the user-facing report.

## 8. Data-contract rules for an LLM integration

Use the following rules in the consuming system prompt or tool description:

```text
The JSON is evidence from a Power BI analysis pipeline.

1. Preserve all display-formatted figures exactly. Do not perform arithmetic on
   values containing K, M, B, %, slashes, or explanatory text.
2. In KPI cards, interpret delta only with comparisonLabel and use
   deltaDirection for the front-card direction.
3. Do not treat KPI id, headings, array positions, or prose as stable identity.
4. Do not present severity or tone as statistical confidence.
5. Distinguish payload-generation dates from the business data's as-of date.
6. Treat insight.action as a recommended follow-up, not an executed action or a
   proven causal conclusion.
7. Use report_summary for the current overview, kpi_insights for current
   findings, and insight_history for prior-run context.
8. Do not use private memory.json as customer-facing evidence.
9. If an exact numeric calculation is required, state that the public contract
   contains presentation strings and request a raw numeric source.
```

### Recommended LLM envelope

When passing several blobs to one model, wrap them with explicit source labels
rather than concatenating anonymous JSON:

```json
{
  "contractVersion": 1,
  "currentSummary": {"source": "report_summary.json", "data": {}},
  "currentInsights": {"source": "kpi_insights.json", "data": []},
  "history": {"source": "insight_history.json", "data": {}}
}
```

`contractVersion` in this wrapper belongs to the consuming application; it is
not currently stored in Azure. Adding a wrapper is useful because the actual KPI
payload has an array root while the other two public payloads have object roots.

## 9. Important non-outputs

The pipeline writes many local diagnostic artifacts, plus Markdown and HTML
reports, under `outputs/`. The Azure uploader currently selects only
`outputs/api/*.json`, the history documents described above, and the isolated
memory store. Therefore files such as `report_summary.md`, `insight_report.md`,
`insight_signals.json`, evidence artifacts, DAX, logs, and HTML are **not** part
of the current Azure output contract.

This also means the public Azure payloads are excellent for display and LLM
summarization but do not expose complete raw numeric facts for downstream
calculation. If arithmetic or analytics is a future requirement, add a separate
versioned machine-data payload rather than making consumers parse compact
presentation strings.
