# Target Tracker — reference design

`reference_target_tracker.html` is the **design target** for the Target Tracker dashboard.
It is not produced by the pipeline. `build_target_tracker_reference.py` regenerates it.

Same shell as `reference_inventory_management.html` and `reference_stock_age_analysis.html`:
rail + main and nothing else inside `.app`, four layers, two views, `#<view>/<layer>` in the URL
so a tab is linkable and a screenshot tool can reach it without a click. The CSS variables,
`.card` / `.kpi` / `.rb` / `.pill` / `.caveats` / `.foot` components and the nav script are the
same system, so a styling fix lands on all three pages.

| | |
|---|---|
| Report | TARGET TRACKER · `4e9b98f8-5e85-4119-9f14-a187d090333e` |
| Dataset | `f34c5654-bf75-4fb3-b289-2676d8e38241` (verified via `GET /reports/{id}`) |
| Workspace | `6d383900-b84d-4bce-afb4-b95453bee00a` |
| Anchor | **Thursday 16 July 2026** |
| Population | CFH014, CFH017, CFH018, CFH021 — CFH022 excluded |
| Currency | **SAR** — Saudi Riyals. See defect 5. |

Every figure is live data pulled on 2026-08-18 and re-derived arithmetically. The generator
asserts that the two halves of July reconcile to the month-to-date gap, so a wrong number fails
the build rather than shipping.

## Why mid-July and not the latest day

The anchor is **deliberately not** the model's newest date. Mid-month is the moment the summary is
worth reading: there is still time to change what the month does. By day 28 the same page is a
review, not a decision aid. The reference is set where the product has to be good.

The pipeline uses the **latest date that has targets**, which is not the same as the latest date
with sales — see the defects below.

## The drill axis is time

The inventory pages drill through *place* and *merchandise*. This one drills through **time**,
because the report's stated priority is **Daily → WTD → MTD → YTD**. That order is an instruction,
not a ranking the model computes.

```
rail            Performance · Branches · Departments · Detail   |   All areas · Behind target only

Performance  hero verdict + three proof numbers
             "How we are doing right now"  4 KPI cards, one per period, in priority order
             "What has happened"           full-width day-by-day chart; surplus waterfall;
                                           which branches missed today
             "What is needed to catch up"  this week | this month, with projections
             "Important things to know about these numbers"
Branches     how each branch is doing this month | this week; full branch figures
Departments  this week so far | this month so far; full department figures
Detail       sections that stand out; week-by-week; month-by-month
```

**Structure is code-owned; prose is not.** Same inversion R6 makes, same reason: every horizon must
be *covered* whether or not it has a headline, and a prompt that decides layout will drop one on a
quiet day. The four layers, the KPI cards, the bars, the tables and the charts are deterministic.
The LLM fills prose slots only — hero headline and narrative, card notes — and every figure it may
quote is already in the page model.

### The two views

`All areas` and `Behind target only`. The second filters every breakdown to branches, departments
and sections missing target, and swaps the hero verdict. Totals still describe the whole business,
and the amber `.scoped` banner says so — the same contract the inventory pages use for their
high-risk views.

### Language

The audience is not assumed to have retail experience, or any analytics background. Every string on
the page is written for a general reader:

| Not this | This |
|---|---|
| attainment | % of target · how much of its target it reached |
| month-to-date / MTD | this month so far |
| the cushion | the surplus |
| handed back a third of the cushion | used up about one-third of the surplus |
| behind at every horizon | below target over every time period |
| the estate has slowed | almost every department has slowed |
| required rate | needed vs target |
| the largest single drag | the biggest shortfall |
| banked | built up |
| a structural problem | a long-running problem |

Numbers are always explained, never just stated: not "89.2%" but "89.2% of target, SAR 197.5K below
target". The rule applies to `aria-label`s too — a screen-reader user gets the same plain sentence,
not the technical one.

Currency is written **SAR** in the ~400 places it appears and expanded once, in the masthead, as
"all figures in Saudi Riyals (SAR)". Spelling it out at every figure would make the page unreadable.

### RAG

`≥100%` **On target** · `95–99.9%` **Watch** · `<95%` **Below target** ("behind" was jargon). One rule on every surface. Red row
highlighting (`tr.urgent`) is reserved for **behind** — an early version fired on any shortfall and
painted a 97.3% row the same as a 68.7% one.

### The narrative is connected, not four independent comparisons

Today's miss is read as *the sixth in a row*; the week as *what today did to it*; the month as *a
surplus built in the first ten days and being spent now*; and the year appears **only as
precedent** — March and June are the two months that lost the same way. The figure that ties it
together is the date the surplus runs out.

## What the data supports — and what it does not

Five defects, each verified by query, none assumed.

1. **No target data for August 2026.** `ACTUAL_SALES_TARGET` and `MONTHLY_TARGET` are NULL on all
   2,682 August rows. Targets run 1 Jan – 31 Jul only. The pipeline must anchor on the latest date
   **that carries a target**, not on `MAX_DATE`, and say which date it used.
2. **No prior year.** `DOC_YR` holds 2026 alone, and the columns `LY_SALES`, `LY_SAME_DAY_SALES`,
   `LYLY_SALES`, `LY_SAME_DAY_DATE` do not exist. Every prior-year measure in the model
   (`DAILY GROWTH`, `MTD GROWTH`, `YTD GROWTH`, `LAST YEAR SALES`, `ty sales`, `SALES TARGET`,
   `SALES TO MEET TARGET FINAL`, and the whole WEEK set on `CUR MONTH SALES`) **fails at query
   time**. The page is pure actual-vs-target and says so.
3. **`MTD_TARGET` and `WTD_TARGET` are the same broken expression.** Both filter `MTD_CHECK = "Y"`,
   true on all 44,127 rows, so both return the full year target of SAR 136.7M. Neither may be used.
4. **`CURRENT MTD REVENUE 1`, `CURRENT YTD REVENUE 1` and `CURRENT week REVENUE 1` are identical.**
   They differentiate only through report-page filter context, which a headless query does not have.
5. **The model says the wrong currency.** Four rows of its own `Metrics description` table read
   "Current Day Revenue in **QAR**", "Current year MTD sales in QAR", and so on. The group is
   Saudi-based and every other City Flower dashboard uses SAR. The description table is stale; the
   figures are Saudi Riyals. Do not read the currency off that table.

### Scope definitions

| Period | Filter | Live flag |
|---|---|---|
| Day | `TY_DATE = <anchor>` | `MAX DATE CHECK = 1` |
| WTD | `TY_DATE` between the week's Monday and the anchor | `YTW CHECK = 1` |
| MTD | `TY_DATE` between the 1st and the anchor | `max month = 1` |
| YTD | `TY_DATE` from 1 Jan to the anchor | all rows |
| Full week / month target | `SUM(ACTUAL_SALES_TARGET)` over the whole week / month | — |

**Every period is measured against the target for the days that have passed**, never the whole
period — otherwise a month reads "36% of target" on day 11 and the number means nothing. Whole-period targets
appear only in the close-out arithmetic, which is labelled as such.

## Week-to-date early in the week

On a Monday, WTD is one day and identical to Daily. The layer still reports it honestly and leans on
the **last complete week** for trajectory, so it earns its place instead of restating the daily
figure. The reference anchor is a Thursday (4 of 7 days), with week 28 as the contrast.

## Verify it before calling it done

Render and look at every tab. The URL carries the state, so each is reachable directly:

```
chrome --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
  --user-data-dir=<tmp> --screenshot=out.png --window-size=1500,2200 \
  "file:///<abs path>/reference_target_tracker.html#all/performance"
```

Faults only a screenshot caught on this page:

- The day-by-day chart was in a `g-2` side column, scaled to half width, with unreadable axis type
  and ambiguous `F10`-style labels. It now has the full page width and reads `Fri 10`.
- Moving it left the surplus card alone in a two-column row — the "one narrow column, enormous dead
  space" fault the inventory README lists. Today's branch attribution now sits beside it, which is
  also the highest-priority content that was missing from the landing layer.
- `tr.urgent` painted Watch rows the same red as Behind rows.
- The caveats block sat on `Detail`, which most readers never open. It belongs on the landing layer.

Structural invariants the page holds, and why they matter (all three broke on the first inventory
dashboard): `.app` contains **only** `nav.rail` and `main`; content lives in `main > .page`; there is
exactly **one** `<script>` tag. One self-contained file, no external requests, no storage APIs,
everything escaped, print rules force hidden views open.

---

# Version 2 — built to the client rules document

`reference_target_tracker_rules.html` is a **second, parallel reference**, governed by
`target_tracker_insight_rules.md` (the client's Target Tracker AI Insights Generation Rules,
kept here beside the page it governs). Regenerate with
`build_target_tracker_rules_reference.py`.

Version 1 above is unchanged. The two are alternatives, not a revision — v1 is the compact
four-layer page; v2 is the full analyst briefing the rules specify.

## What the rules changed

| | Version 1 | Version 2 |
|---|---|---|
| Layers | 4 — Performance, Branches, Departments, Detail | **7** — Executive Pulse, Yesterday, Last 7 Days, This Week, This Month, This Year, Management Attention (§32) |
| Organising axis | time, four periods | time, but **Yesterday leads and gets its own layer** (§7) |
| Views | All areas / Below target only | **one view** — the rules define one report; a scope toggle would be invention |
| Breakdowns | four independent cuts | a **diagnostic chain**: company → branch → department → section (§26) |
| Pace | required rate vs remaining target | **run-rate and Target Pace Index** for week and month (§9, §11, §14) |
| History | 8 weeks, 7 months | **30-day exception test, 7-day journey, 4-week trajectory, 3-month benchmark, quarters** (§7.2, §8, §10, §13, §17) |
| Ending | caveats | **Management Attention** — five ranked items, no new facts (§33) |

## Findings that only appear in v2

The extra history the rules demand surfaced three things v1 could not see:

- **Yesterday is not a record.** At 95.1% it is the **12th weakest of the last 30 days** — the
  weakest was 22 June at 74.3%. §7.2 forbids claiming a record when the difference is not
  meaningful, so the page says so explicitly and reports the honest finding instead: 7.1 points
  below the 30-day average, and the sixth miss in a row.
- **CFH018 is the sharpest mover on the page.** 110.9% across seven days but 92.1% yesterday, a
  fall of 18.8 points. It is still the strongest branch for the month, so the page flags it to
  watch rather than to act on (§12 deteriorating areas).
- **CFH017 is a structural risk, not a bad day.** Below target yesterday, this week, this month
  and this year, and it has missed in **four of seven months**. That is all five of §19's
  conditions, and it is why it leads Management Attention.

## Two places where following the rules required care

**The run-rate KPI is misleading on a Thursday.** §9 defines Required Run Rate as remaining
target ÷ remaining days. Here that gives SAR 657.6K/day against a current SAR 406.5K/day — a
pace index of 0.62, implying a 61.8% uplift. But the three days left are Friday, Saturday and
Sunday, which carry far larger targets than midweek. Measured against their own targets those
days need **111.1%**, not 161.8%. The page shows the rules' KPI and then says plainly why the
attainment figure is the fairer read. §35's integrity gate requires exactly this.

**Contribution to shortfall can exceed 100%.** §3 defines it as entity shortfall ÷ overall
shortfall. CFH017 was SAR 39.1K short against a company net miss of SAR 27.3K — 143%. Rather
than print a number that reads as broken, the page expresses each branch as a share of the
**total shortfall across branches that missed** (83%), and states separately that CFH017 alone
was short by more than the whole company miss. Same fact, no confusing percentage.

## Visual discipline

§29 caps a visual at roughly a quarter of its block and §30 requires every visual to carry its
interpretation. Every chart is wrapped in `.mini` (max 560px) — a 520-wide viewBox stretched to
a 1230px card was filling half the page — and every one has a note under it. The visual set is
the rules' own: target pulse bar, ranked strip, contribution bars, 7-day journey, pace gauge,
benchmark cards, trajectory, persistence heat strip.

## What the rules forbid, and the page honours

§23 and §24: no invented causes. The diagnostic chain card says so in as many words — *"This is
a chain of arithmetic, not of cause. It shows where the shortfall sits, not why it happened —
the report has no data on promotions, stock, staffing or footfall, so it does not guess."*

## Verify

```
chrome --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
  --user-data-dir=<tmp> --screenshot=out.png --window-size=1500,1400 \
  "file:///<abs path>/reference_target_tracker_rules.html#yesterday"
```

Layers are `#pulse`, `#yesterday`, `#last7`, `#wtd`, `#mtd`, `#ytd`, `#attention`.

Faults the screenshots caught here: a department that *missed* target listed under "held the day
up" (a `[:3]` slice of a two-item set); the 4-week trajectory ballooning to half the page; and a
note claiming "three of the last four weeks reached target" when the chart plainly showed two —
the count is now computed, not written. The build also asserts that branch variances sum to the
company variance and that CFH017's departments sum to its shortfall; the second assert failed
first time and caught a missing department.
