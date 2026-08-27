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

## Amendment, 2026-08-25: five source fixes

Enabled on a live client, the tiles were unreadable. The worst one:

```
STOCK OUT - PLACE ORDER              Performance
+17.2K
of all Loc-SKUs in the stock position
```

Nobody could say what +17.2K was. The card's own `description` could:
*"17,215 Loc-SKUs are in STOCK OUT - PLACE ORDER, 12.4% of the 139,200 in the
position."* Every fact needed was computed; the card published none of them in a
form the tile could use, and three of the four it did publish were wrong.

| # | Defect | Fix |
|---|---|---|
| 1 | **A level published as a change.** `impact_value` is a count of what is in a state right now; `_compact_number(val, signed=True)` made it `+17.2K`, a rise of 17.2K that never happened. | Signals that are snapshots declare `value_kind: "level"` (`inventory/stock_health_signals._signal`, where the docstring already said there is no prior). A level is rendered unsigned. |
| 2 | **A comparison clause with its subject amputated.** `comparison_label` was `"of all Loc-SKUs in the stock position"` — the tail of `"12.4% of …"`. Printed under the count, the tile asserted 17.2K *was* the share: a false sentence from two true halves. | The share is part of the clause. Both sites in `stock_health_signals` now emit it. |
| 3 | **`metric` holds the segment, never the measure**, and fell back to the literal string `"Segment"` — which headed a tile on this client's home page. The measure name was on the signal (`"Loc-SKUs in a double-warning state"`) and discarded. | `_kpi_label` now reaches every card that has a segment, is capped at 48 characters, and drops the measure rather than the segment when only one fits. Classification dimensions (`recommended_action`, `status`, `bucket`, …) are no longer prefixed — `"Recommended Action STOCK OUT - PLACE ORDER"` is scaffolding. The `"Segment"` fallback is now `""`. |
| 4 | **A currency nobody configured.** `_kpi_currency` could not return "no currency"; it ended `return … else "SAR"`, and `ai_content_kpi_currency` was catalogued with default `"SAR"`. Only seven reports have their own key. | `_kpi_currency` returns `Optional[str]`; the catalogue default is now `""`. A report with no configured currency publishes no `unit`. |
| 5 | **A level claiming `"vs baseline"`.** A snapshot has no prior, no target and nothing it was measured against, but fell into the `"other"` branch and got a chip saying it did. | A level with a share is `share_of_total` and carries `shareOfTotalPct`; a level without one gets no `comparison` at all. |

The same card now:

```
Loc-SKUs in a double-warning state
17.2K                                    share of total
STOCK OUT - PLACE ORDER · 12.4% of all Loc-SKUs in the stock position
```

`scripts/replay_kpi_card_fields.py` passes, with two assertions inverted because
they encoded defect 4 (`"the currency default is SAR"`, `"no report-specific
currency and no generic override -> SAR default"`). `replay_config_schema` and
`replay_inventory_scan` pass unchanged. `replay_ai_content_publish` fails on an
Azure container-name argument both before and after these edits.

### The published summary now carries what a tile needs

Separate from the KPI card work, and the more useful of the two: the app's
"What changed today" strip is driven by the **Daily Sales scorecard** rather than
by the findings feed, because a block a reader scans every morning cannot change
what it measures from day to day.

`summary_payload` flattened each report KPI to `{label, value, tone}` — enough to
print "USD 55.3K" and nothing else. The page had already worked out that the
figure was 17.7K under its benchmark, that the verdict was Underperforming, and
where it sat inside its band; all three were dropped at the door.

`ReportMetric` is now additively extended with:

| Field | Meaning |
|---|---|
| `note` | "−USD 17.7K against the benchmark USD 73.0K" |
| `verdict` | "Underperforming" / "In band" / "On target" |
| `band` | `{actual, floor, benchmark?, ceiling}` — Daily Sales |
| `target` | `{value, attainmentPct}` — Target Tracker |

`band` travels as four numbers rather than as `daily_sales_dashboard.bullet`'s
geometry, which is computed for a 214px chart in this report's own HTML and means
nothing to a consumer rendering at another width. A card carries `band` **or**
`target`, never both — a target has no floor, and inventing one to fill the shape
would be a judgement the data does not support.

`target_tracker_publish` emits the same three on each period row, and the app
takes only "Today".

### Daily Sales cards were not tile-shaped

The Home strip is scoped to the two reports that describe a period — Daily Sales
and Target Tracker — and against that scope the Target Tracker card was well
formed and the Daily Sales cards were not. Three more fixes, same file pattern:

| Defect | Fix |
|---|---|
| **No delta.** `_assemble_kpi_card` computes one only from a target, so every declared-baseline card published `delta: ""`. A bare "-7.1K" cannot be read without knowing the base — it is a different day at a business turning 55K than at one turning 5M. | Signals may declare `delta_pct`. Daily Sales computes it from the band edge it missed (`_band_gap_pct`): 7.1K under a 62.4K floor is 11.4%. |
| **`"other"` / `"vs baseline"`.** A band is a threshold and the enum already has the name; "vs baseline" is true of anything. | Signals may declare `comparison_type` + `comparison_chip`, validated against `COMPARISON_TYPES`. Daily Sales declares `threshold` / `"vs normal band"`. |
| **No `unit`, no `goodDirection`,** because the signals carried no `metric_family` and the classifier will not guess. | Net Sales → `revenue`, Bills → `transactions`. Margin is left unset on purpose: it is a percentage and there is no honest entry for one. |

Plus `_kpi_label` no longer returns None when a signal has no segment. A
whole-business finding has none by design, and the measure name is a perfectly
good name on its own — "Net Sales vs its normal band" says what the number is,
where before the tile got nothing at all.

The card, before and after:

```
before   Segment                    after   Net Sales vs its normal band
         -7.1K                              -7.1K          ↓11.4%  vs normal band
         the normal net sales band          below the normal net sales band
         for the business on this           for the business on this weekday
         weekday
```

### Still open on this side

- **`valueType` on a quantity.** `ST1 — Quantity` was published as
  `valueType: "currency"`. Both classification tables map quantity to `count`,
  so that signal arrives with a revenue `metric_family` while its own metric
  name says Quantity. Not fixed here — it is upstream of this file, in whatever
  builds the Sales YoY signal.
- **`category` is `"Performance"` on nine of ten cards**, which is the catch-all
  bucket. It is why `valueType` is withheld on those cards, and it is a
  classification problem rather than a card problem.
- **Extended fields are per-report config.** On the run that prompted this, Sales
  YoY and Target Tracker had `ai_content_kpi_card_fields` on and Inventory Stock
  Health and Daily Sales did not, so one feed carried two contracts. That is
  legitimate and the app handles it, but it means `rank` is absent on some cards
  and the app falls back to severity ordering for the whole strip.

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
