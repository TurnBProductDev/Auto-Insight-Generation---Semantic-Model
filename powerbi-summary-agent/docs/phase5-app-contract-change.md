# Handoff: KPI insight feed becomes multi-report

**Audience:** whoever owns the web app that reads
`ai-content/kpi/client/insights.json` and `ai-content/kpi/client/alerts.json`.

**Status:** the agent side is built but **switched off**. Nothing in the feed changes until
someone sets `ai_content_multi_report_feed: true` in the agent config. Do not enable it
until the app changes below have shipped.

Everything stated here was verified against the agent code on 2026-08-18, not assumed.

---

## Why this is changing

The feed carries findings from **one** report today (Sales vs Previous Year). Three more
reports now exist — Target Tracker, Stock Age Analysis, Inventory Management — and they
need to appear in the same feed. There is one feed per *client*, not per report:

```
ai-content/report-summaries/client/{report_id}.{json,html}   ← already per report
ai-content/kpi/client/insights.json                          ← ONE per client
ai-content/kpi/client/alerts.json                            ← ONE per client
```

So the feed has to say which report each card came from, and the app has to stop assuming
every card describes the same report.

---

## What changes in the payload

### 1. A new field on every card: `reportId`

```jsonc
{
  "id": 1043216,
  "reportId": "target_tracker",     // NEW
  "severity": "warning",
  "category": "Sales",
  "metric": "CFH017",
  "value": "-45.9K",
  "delta": "8.7%",
  "deltaDirection": "down",
  "description": "...",
  "displayTime": "9:15 AM",
  "isoDate": "2026-08-18",
  "comparisonLabel": "vs target",
  "insight": { "title": "...", "summary": "...", "stats": [...], "action": "..." }
}
```

`reportId` is a short stable slug, **not** a Power BI GUID. Current values:

| `reportId` | Report | Client |
|---|---|---|
| `sales_yoy` | Sales vs Previous Year | cityflower, scanb |
| `target_tracker` | Target Tracker | cityflower |
| `stock_age_analysis` | Stock Age Analysis | *(config pending)* |
| `inventory_management` | Inventory Management | *(config pending)* |

Treat it as an opaque string. Do not parse it, and do not hardcode the list — new reports
will be added. If you need a display name, map it in the app or ask us to add a
`reportName` field too.

### 2. `id` stops being 1, 2, 3

**This is the part most likely to break something.**

Today `id` is a per-run sequence starting at 1 (`enumerate(signals, start=1)` in
`api_payloads.py`). Every run of every report produces cards numbered from 1.

With several reports writing into one feed that guarantees **duplicate `id` values in a
single JSON array**. If the app uses `id` as a React key, a dedupe key, a click target or
a "seen" marker, it will silently mis-render — two different cards claiming to be card 1.

When multi-report mode is on, `id` becomes a **large, stable, collision-free integer**
derived from the report id plus the finding's identity. Two consequences:

- It is **no longer small or sequential.** Expect values in the millions. It stays within
  signed 32-bit range, so `int` columns are safe.
- It is **stable across runs for the same finding.** If a card for the same finding is
  republished tomorrow it keeps the same `id`. That is a feature — it lets you track
  read/dismissed state — but only if you are not currently assuming a fresh id per run.

`id` remains typed as an integer. Nothing needs to change if you only use it as a key.

### 3. The feed gets longer and mixes reports

- Card count per client rises from **3** to a configured total of **10**, shared between
  whichever reports ran that day.
- Cards from different reports are **interleaved**, sorted newest date first — they are not
  grouped by report.
- A report that produces nothing on a given day contributes nothing. The set of `reportId`
  values present will vary day to day. Do not assume all four always appear.
- Every contributing report is guaranteed at least one slot before the list is truncated,
  so a quiet report is never fully crowded out by a loud one.

### 4. Retention behaviour is unchanged, but now per report

`alerts.json` keeps seven calendar days. Previously a same-day re-run replaced *all*
same-day cards. Now a run replaces only **its own report's** cards for that date and leaves
other reports' cards alone. Nothing to do in the app — just be aware that the same-day set
can grow through the day as different reports finish.

---

## What the app needs to do

**Required**

1. **Accept the unknown field.** If the card is validated (TypeScript type, JSON schema,
   pydantic, Zod, …), add `reportId: string` or relax the model to allow unknown keys.
   This is the blocking change — the agent side is ready and waiting on it.
2. **Stop assuming `id` is small, sequential or per-run.** Confirm nothing sorts by `id`
   expecting insertion order, and nothing derives position from it. Sort by `isoDate` (and
   `severity` if you need a tiebreak) instead.
3. **Stop assuming one report per feed.** Anything that reads "the report" from feed-level
   context and applies it to every card must now read `reportId` per card.

**Recommended**

4. **Show which report a card came from** — a small label or badge. Without it, a stock
   finding and a sales finding sit side by side with no way to tell them apart.
5. **Let users filter by report.** `reportId` is exactly the filter key.

**Optional**

6. Use the now-stable `id` for read/dismissed state, since a republished card keeps its id.

---

## Rollout order

The two sides can ship independently, in this order:

1. **App ships first** — tolerate `reportId`, stop relying on `id` being sequential. At this
   point nothing has changed in the feed, so this is a no-op deploy that is safe to sit on.
2. **Confirm back to us.**
3. **We flip `ai_content_multi_report_feed: true`** per client. The feed then starts
   carrying `reportId` and multi-report cards.
4. **Rollback** is flipping the flag off. The feed reverts to today's exact shape —
   sequential ids, one report, three cards, no `reportId`.

Because the flag is per client, cityflower and scanb can be migrated separately.

---

## How to test before we enable anything

Ask us for a sample multi-report `insights.json` — we can generate one offline without
touching production, from committed scan fixtures. Check that:

- the app renders a feed whose `id` values are large and non-sequential;
- cards from two different `reportId` values render together without collapsing,
  de-duplicating or overwriting each other;
- a feed of 10 cards renders acceptably in whatever surface shows them;
- a card with an unfamiliar `reportId` (e.g. `stock_age_analysis`) does not crash or get
  filtered out.

---

## Questions to send back to us

1. Does the app validate the card shape strictly today, and where?
2. Is `id` used for anything beyond a render key?
3. Do you want a `reportName` display string on the card, or will you map the slug yourself?
4. Is 10 cards the right feed length for the surface that renders them, or should we tune it?
