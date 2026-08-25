# Handoff: extended KPI tile fields

**Audience:** whoever owns the web app that reads
`ai-content/kpi/client/insights.json`.

**Status:** the agent side is built behind `ai_content_kpi_card_fields` (code default
`false`). Enable it only for a client whose app tolerates the new keys; older clients
can remain on today's contract. This follows the same rollout pattern as `reportId`
(`docs/phase5-app-contract-change.md`) — read that one first if you haven't already.

Everything stated here was verified against the agent code on 2026-08-25, from
`kpi-tile-schema-proposal.md`, not assumed.

---

## What's new

Nine additive, optional fields on every card, each present **only when the underlying
finding actually supports it** — there is no guessed unit, no invented direction, no
fabricated baseline. A card missing a field means exactly what it means today for
`reportId`: the app draws nothing for that field rather than something wrong.

```jsonc
{
  "id": 356989147,
  "reportId": "target_tracker",
  "severity": "critical",
  "category": "Performance",
  "metric": "ST2",
  "value": "-334.8K",
  "delta": "11.1%",
  "deltaDirection": "down",
  "description": "...",
  "displayTime": "9:15 AM",
  "isoDate": "2026-08-24",
  "comparisonLabel": "against its target for this month so far",
  "insight": { "...": "..." },

  "label": "Branch ST2 — Sales against target",     // NEW
  "rawValue": -334800.0,                              // NEW
  "unit": "QAR",                                      // NEW (currency only)
  "valueType": "currency",                            // NEW
  "goodDirection": "up",                              // NEW
  "comparison": {                                     // NEW
    "type": "target",
    "label": "vs target",
    "baselineValue": 3010000.0
  },
  "target": { "value": 3010000.0, "attainmentPct": 88.9 },  // NEW
  "rank": 1                                           // NEW
}
```

`shareOfTotalPct` is the ninth field — a number, present only on a card whose
comparison is genuinely a share of a total (`comparison.type == "share_of_total"`),
never on a target/prior-period/peer-comparison card even when the underlying signal
happens to carry an unrelated percentage of its own (a target-tracker attainment gap,
for instance — checked explicitly so the two are never conflated).

### Field-by-field

| Field | Type | When present |
|---|---|---|
| `label` | string | Whenever the card has a segment. Built from the finding's own dimension + segment + metric name (`"Branch ST2 — Sales against target"`) — not a lookup, since in this pipeline the segment code (`ST2`, `CFH017`, …) *is* the model's own identity for that entity, there is no separate "real name" to resolve. |
| `rawValue` | number | Whenever `value` is. The exact float behind the formatted string. |
| `unit` | string | Only alongside `valueType: "currency"`. Resolved from that report's own currency setting (`target_tracker_currency`, `ageing_currency`, …), or the new `ai_content_kpi_currency` fallback for a report with none of its own. |
| `valueType` | `currency \| count` | Only when the finding's measure family is unambiguous (revenue/stock value → currency; quantity/transactions → count). A card on the catch-all "Performance" bucket (SKU counts, health scores, anything the classifier can't place) gets neither — guessing here is exactly the class of bug already seen in this feed (a queue-length count on a currency-shaped sentence). `percent`, `ratio` and `days` are declared in the type for a future signal to opt into explicitly; nothing emits them yet. |
| `goodDirection` | `up \| down \| neutral` | Revenue/quantity/transaction findings → `up`. A data-quality finding → `neutral`. A peer-growth outlier → `up`. Everything else — notably any inventory "stock value" finding, where more stock is good or bad depending on which measure it is — is left absent rather than guessed. |
| `comparison.type` | enum | Whenever the card has a delta at all. One of `target`, `prior_period`, `same_period_last_year`, `share_of_total`, `threshold`, `peer_comparison`, or `other` (a declared, non-target baseline — an inventory policy band or a snapshot position — whose exact shape isn't machine-readable on the signal). **Two values beyond the original proposal's five** (`peer_comparison`, `other`) exist because this pipeline has comparison kinds the proposal's enum didn't anticipate; both are additive and safe to ignore if unhandled. |
| `comparison.label` | string | A short chip label (≤ ~18 chars: "vs target", "week over week", "vs peer median", …) — this also covers the proposal's separate `contextShort` idea; we didn't ship a second near-duplicate short-caption field. |
| `comparison.baselineValue` | number | The number the card's value is being measured against, in the same units as `rawValue`. Absent for `share_of_total` (a share isn't measured against a baseline value). |
| `target.value` / `target.attainmentPct` | numbers | Only when the signal carries a numeric target (currently: Target Tracker cards). |
| `rank` | integer | Always, when the flag is on. The card's position in this run's materiality ordering — 1 is the most material finding published. |

### Deliberately not in this drop

Three fields from the proposal are **not implemented**, on purpose — each needs either
new aggregation this pipeline doesn't do today, or a decision only your side can make:

- **`period{grain,start,end,partial}`** — would require emitting the same finding at
  day/week/month grain, each independently computed. Every detector today natively
  produces one grain (Target Tracker is month-to-date, recent-week is week-over-week,
  daily incidents are day-level); making the Daily/Weekly/Monthly toggle on Home live
  needs new aggregation work, not just a new field.
- **`series`** (sparkline) — some per-entity daily history exists in one report (Daily
  Sales) but isn't wired to individual findings anywhere. Needs its own follow-up.
- **`thresholds{warn,critical}`** — needs agreed operating bands per metric, which is a
  business decision, not a code task; the agent side has no way to guess a "warn" cut.
- **`drilldown.moduleId`** — this is entirely your side's routing id; the agent has no
  way to know it. `drilldown.reportId` and `.filters` would be trivial to add once you
  hand back a `reportId → moduleId` map, matching the note in the proposal's own §2.4.

---

## What the app needs to do

**Required**

1. **Accept the unknown fields.** Same as the `reportId` rollout — relax strict
   validation or add the nine keys above as optional.
2. **Guard every visual on its field being present**, exactly as the proposal
   specifies. A card with no `target` should not render an attainment bar; a card with
   no `goodDirection` should keep colouring the delta by `severity` as it does today.

**Recommended**

3. Use `comparison.type` to group/route tiles instead of parsing `comparisonLabel`
   prose.
4. Treat `comparison.type` as an open set — a value you don't recognise yet
   (`peer_comparison`, `other`, or a future addition) should render like a generic
   comparison chip, not be dropped or crash the card.

---

## Rollout order

Same two-sided sequence as the `reportId` change:

1. **App ships first** — tolerate the new keys, guard every new visual on presence.
   Safe to sit on; nothing changes in the feed yet.
2. **Confirm back to us.**
3. **We flip `ai_content_kpi_card_fields: true`** per client. Cards then start carrying
   the new fields, only where the finding supports them.
4. **Rollback** is flipping the flag off — the feed reverts to exactly today's shape.

---

## Questions to send back to us

1. Do you want `moduleId` wired up? If so, send the `reportId → moduleId` map and we'll
   add `drilldown` in a follow-up.
2. Is the Daily/Weekly/Monthly toggle on Home still the priority? If so, `period` is the
   next piece of work, and it's the most expensive item on this list — worth confirming
   before we start.
3. Are there agreed warn/critical bands for any metric today, or does `thresholds` wait
   until there are?
