# Target Tracker — AI summary rulebook

The governing document for the Target Tracker AI summary. `reference_target_tracker.html`
in `docs/dashboard-reference/` is the worked example; this file is the rule set the
generator and the validator enforce.

Written for a reader with no retail or analytics background. That constraint is a rule,
not a preference — see §5.

---

## 1. Purpose

Turn actual-versus-target data into a short business story a manager can act on. Not a
restatement of the dashboard.

The summary answers, in this order:

1. How did the business do **today**, against today's target?
2. What has today done to **this week**?
3. What has this week done to **this month** — and can the month still be made?
4. Does the **year** change how any of that should be read?
5. Which branch, department or section needs attention?

---

## 2. Priority order — non-negotiable

**Daily → WTD → MTD → YTD.**

This is an instruction, not a ranking the model computes. Daily leads even on a quiet day.
YTD is context only: it appears when it changes how the nearer periods should be read, and
it never leads.

The summary must not present the same actual-vs-target comparison four times. Each period
must be read **through** the one before it:

- today's result is read as part of the current run of days;
- the week is read as what today did to it;
- the month is read as a surplus or deficit being built or spent;
- the year is read as precedent — has this shape happened before, and how did it end?

---

## 3. Scope definitions

| Period | Filter | Live flag on the model |
|---|---|---|
| Day | `TY_DATE = <anchor>` | `MAX DATE CHECK = 1` |
| WTD | `TY_DATE` between the week's Monday and the anchor | `YTW CHECK = 1` |
| MTD | `TY_DATE` between the 1st and the anchor | `max month = 1` |
| YTD | `TY_DATE` from 1 January to the anchor | all rows |
| Full week / month target | `SUM(ACTUAL_SALES_TARGET)` over the whole week / month | — |

**The anchor is the latest date that carries a target**, which is not always the latest date
that carries sales. When they differ, the summary says which date it used and why.

Weeks run **Monday to Sunday**.

### 3.1 Attainment is always against the elapsed target

Every percentage compares actual sales with the target for **the days that have already
passed** — never with the whole period's target. Otherwise a month reads "36% of target" on
day 11 and the number is meaningless.

Whole-period targets appear **only** in the catch-up arithmetic, and that block says so.

### 3.2 Definitions

```
% of target        = actual ÷ target × 100
above/below target = actual − target
needed to close    = full-period target − actual so far
needed vs target   = needed to close ÷ (full-period target − elapsed target) × 100
```

`needed vs target` above 100% means the remaining days must beat their own plan.

---

## 4. Page structure — code-owned

Four layers, fixed, in a rail. Two views.

```
Performance   hero verdict + three proof numbers
              "How we are doing right now"  — one KPI card per period, in priority order
              "What has happened"           — day-by-day chart; surplus split; today by branch
              "What is needed to catch up"  — this week | this month, with projections
              caveats
Branches      this month | this week; full branch figures with catch-up requirement
Departments   this week | this month; full department figures
Detail        sections that stand out; week-by-week; month-by-month
```

Views: **All areas** and **Below target only**. The second filters every breakdown and swaps
the hero verdict; totals still cover the whole business and the amber banner says so.

**Structure is code-owned; prose is not.** Every period must be *covered* whether or not it
has a headline — a prompt that decides layout will drop a layer on a quiet day. The layers,
KPI cards, meters, bars, tables and charts are deterministic. The LLM fills prose slots only:
the hero headline and narrative, and the note under each card. Every figure it may quote is
already in the page model.

Caveats appear **once**, on the layer the reader lands on.

---

## 5. Language

The audience is assumed to have no retail experience and no analytics background.

| Never write | Write |
|---|---|
| attainment | % of target · how much of its target it reached |
| month-to-date, MTD | this month so far |
| week-to-date, WTD | this week so far |
| the cushion | the surplus |
| handed back / banked | used up / built up |
| behind at every horizon | below target over every time period |
| the estate | all branches · the business |
| required rate | needed vs target |
| the largest single drag | the biggest shortfall |
| a structural problem | a long-running problem |
| Behind (status) | Below target |

Further rules:

- **Never state a bare number.** Not "89.2%" but "89.2% of target, SAR 197.5K below target".
- **Short sentences.** One idea each.
- **Spell out the arithmetic** when a figure is derived: say what was divided by what.
- The same rule applies to `aria-label`s. A screen-reader user gets the plain sentence.
- **No emojis.**

### 5.1 Currency

**Saudi Riyals, written `SAR`**, expanded once in the masthead as "all figures in Saudi
Riyals (SAR)".

The model's own `Metrics description` table says **QAR** on four rows. It is stale. Do not
read the currency from that table.

---

## 6. Bands

`≥ 100%` **On target** · `95–99.9%` **Watch** · `< 95%` **Below target**

One rule on every surface — KPI cards, bars, tables, pills. Red row highlighting is reserved
for **Below target**; a 97.3% row must not be painted the same as a 68.7% one.

---

## 7. What earns a place

Rank candidates by **size of the gap in value**, then share of the total gap, then how far
from target, then persistence, then recency.

- **Never rank on percentage alone.** A small branch at 75% is not more important than a
  large branch at 88% with three times the shortfall. Show the percentage and the value
  together, always.
- **Do not manufacture problems.** If performance is healthy, say so.
- **Do not repeat a finding** across layers unless its meaning has changed.
- If a period has nothing worth saying, say less.

---

## 8. Named findings the summary must make when true

- **A run of consecutive days below (or above) target**, with its length.
- **A surplus being built or spent**: how much was built, over which days, how much has gone,
  and — when a run is active — the date the surplus would be exhausted at the current rate.
- **One branch explaining more than the whole company gap.** State it plainly: without that
  branch the day would have finished above target.
- **A branch below target over every period**, which separates a long-running problem from a
  bad day.
- **Catch-up requirement** for the week and the month, expressed as a percentage of what the
  remaining days are already targeted to sell.
- **A week-to-date that is one or two days old** must be reported honestly and paired with the
  last complete week, so the section says something rather than restating the daily figure.

---

## 9. Forbidden

- **Never invent a cause.** The model holds sales and targets only. No promotions, stock,
  staffing, weather, footfall or competitor activity. The summary says *where* a gap sits,
  never *why*.
- **No comparison with last year.** The model holds 2026 only, and the prior-year columns do
  not exist. Every prior-year measure in the model errors at query time.
- **Do not use `MTD_TARGET` or `WTD_TARGET`.** Both filter `MTD_CHECK = "Y"`, which is true on
  every row, so both return the full year target. Compute scope targets from
  `ACTUAL_SALES_TARGET` over the date range.
- **Do not use `CURRENT MTD REVENUE 1`, `CURRENT YTD REVENUE 1` or `CURRENT week REVENUE 1`
  unfiltered.** All three are the same expression and differentiate only through report-page
  filter context, which a headless query does not have.
- **No forecasting language.** Projections are arithmetic that carries a stated rate forward,
  and must be labelled as such.
- **Never present a figure that is not in the page model.**

---

## 10. Missing data

- If a period has no target, report the actual sales and say plainly that no target is set.
  Do not show a blank comparison or a zero.
- If the latest date has no target, fall back to the latest date that has one and say so.
- If a target is zero or trivially small, use the value difference, not the percentage.
- One non-trading department carries sales against no target. Exclude it from the percentage
  tables and note it if it is large enough to matter.

---

## 11. Population

Four trading branches: **CFH014, CFH017, CFH018, CFH021**.

**CFH022 is excluded** — no trading activity from 1 August 2026, consistent with the Sales
performance report.

Hierarchy is **branch → department → section**. A section finding must be read inside its
department; a department finding inside the business. Do not jump from the company total to
an unrelated section.

---

## 12. Output

| Artifact | What it is |
|---|---|
| `report_target_tracker.html` | the four-layer page, one self-contained file |
| `report_target_tracker.md` | the business document — the same story as prose |
| `report_target_tracker.json` | the page model, for the auditor and the API payload |

The HTML is one file: inline CSS, inline SVG, exactly one `<script>`, no external requests,
no browser storage, everything escaped, print rules force hidden views open.

---

## 13. Quality gate

Before the summary ships:

- Every figure traces to the scan or is derived from it arithmetically.
- The two halves of the month reconcile to the month's surplus.
- Branch values sum to the company value.
- Every figure quoted in prose exists in the page model and is rounded.
- Every period is covered.
- No banned vocabulary (§5), no invented cause (§9), no bare number.
- The page has been **rendered and looked at**. Layout faults on a page whose numbers are all
  correct are invisible to string assertions.
