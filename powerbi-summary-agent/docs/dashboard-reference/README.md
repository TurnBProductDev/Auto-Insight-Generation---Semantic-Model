# Inventory dashboard — reference designs

Two hand-authored exemplars that define what a finished inventory dashboard should
look like. They are the **design target**, not generated output.

| File | Report | Opens in a browser, no server needed |
|---|---|---|
| `reference_inventory_management.html` | Inventory Management (WP7) | yes |
| `reference_stock_age_analysis.html` | Stock Age Analysis (WP5) | yes |

Both carry the **real live figures as at 2026-08-12**, so the layout is proven against
the actual shape of the data rather than against invented numbers. Neither is produced
by the pipeline; `src/domains/inventory/dashboard_html.py` is what must be brought up
to them.

---

## Why these exist

The generated pages were correct and unreadable. Screenshotting the real output showed
five problems that no test could have caught, because every one of them is a *layout*
failure on a page whose every *number* was right:

1. **The hero was broken.** It inherits `.hero{grid-template-columns:1.1fr 1fr}` from the
   sales renderer, which expects four children. The inventory hero emits three, so the
   headline landed in the second column and floated right with the narrative underneath
   it on the left.
2. **`Stock position as at 2026-08-12` printed three times** in the first 120px — page
   subtitle, view context, hero eyebrow.
3. **A fifteen-row urgency ladder swallowed the summary.** The full queue is detail; a
   summary shows the top of it.
4. **One narrow column down a 1500px page.** Enormous dead space right and below.
5. **Five identical grey caveat boxes** stacked at the end, which reads as a broken page
   rather than as five distinct cautions.

---

## The interaction model

Both references are **working pages**, not flat mockups. The first cut had no JavaScript
at all, so every nav button was dead and only the summary was ever visible — a reference
that defines the target has to demonstrate the behaviour, not just the composition.

- **Four layers per view**, one visible at a time: `summary`, `locations`, `divisions`,
  `queue`. The rail switches them and marks the active one with `aria-current="true"`.
- **Two views**, switched from either the rail or the segment control in the masthead:
  `all`, and a scoped second view (`Needs action only` / `High-risk only`). Both controls
  stay in sync.
- **The URL carries the state** as `#<view>/<layer>` — for example
  `reference_inventory_management.html#needs/queue`. This makes a tab linkable, survives a
  reload, and is what lets a screenshot tool reach every tab without a click:

  ```
  chrome --headless=new --screenshot=out.png --window-size=1400,1100 \
      "file:///…/reference_inventory_management.html#needs/queue"
  ```

- **Print shows everything.** `@media print` overrides `[hidden]`, so a printed page
  carries all four layers rather than whichever tab happened to be open.

### The two scoped views are deliberately different, and that is the point

| | Owns its breakdowns? | Why |
|---|---|---|
| Inventory Management — *Needs action only* | **No** | The location and division splits are calculated across all stock, not across the lines needing action. Showing them scoped would print rows that do not add to this view's own totals. Each breakdown layer carries a **pointer** naming the view that does own them. |
| Stock Age — *High-risk only* | **Yes** | The scan carries a `high_risk` column per location and per division, so the breakdowns genuinely reconcile: the seven locations and the ten divisions each add to SAR 3.86M exactly. |

This is the same `owns_breakdowns` / `pointer` contract the R6 sales dashboard already
uses. A scoped view must either own its rows or say plainly that it does not — silently
reusing the wider view's rows is the failure it exists to prevent.

## The structure both references follow

```
rail (172px, dark)  |  page (max 1280px)
                    |
                    |  masthead      title · as-at · view toggle          ← the date, ONCE
                    |  hero          dark band: verdict + 3 proof stats
                    |  ─ Inventory summary ─────────────────────────────
                    |  2-up          lead chart (1.55fr) | shape chart (1fr)
                    |  KPI row       6 cards, severity stripe + pill
                    |  ─ Where it sits ────────────────────────────────
                    |  2-up equal    by location | by division
                    |  ─ Detail ────────────────────────────────────────
                    |  full tables + supporting charts
                    |  caveats       ONE block, bulleted
                    |  footer        provenance
```

### Non-negotiables

- **Summary first, then breakdowns.** The first section is the whole position. Nothing
  above it except the verdict.
- **The date appears once**, in the masthead.
- **Two columns wherever content allows.** A 1280px page running one narrow column is
  the single biggest reason the generated version looked unfinished.
- **The lead chart carries the report's argument.** Inventory Management leads with the
  urgency ladder (its whole point is that the biggest bar is *not* at the top). Stock Age
  leads with the age distribution and its aged portion.
- **A summary shows the top of a list, never all of it.** Six queue rows in the summary;
  all fifteen in Detail, with a line saying so.
- **One caveats block**, bulleted, at the end. Never one box per caution.
- **Every card states its own reading rule** in a `.sub` under the heading and a `.note`
  under the content — what the bar is, what the number beside it means.

### The severity convention

`.kpi` and `.rb-v small` carry a severity stripe or colour, and it is **always paired
with a word** (`OFF TRACK`, `ACT NOW`, `WATCH`, `HEALTHY`, or the rate itself against a
stated company average). Colour alone never carries meaning — red/green is exactly the
pair a red-green colourblind reader cannot separate.

### The palette

Inherited from `summary_dashboard_html`, unchanged:

| Token | Hex | Job |
|---|---|---|
| teal | `#0f9f95` | the calm series, totals, brand |
| amber | `#c08429` | the flagged series (aged / above cover) |
| red | `#cf4636` | status: critical only |
| green | `#2f8f4e` | status: healthy only |
| faint | `#8fa1a9` | neutral / no-action marks |

**teal + amber is the only two-series pair**, and it passes all six palette checks
against the white card surface (CVD separation ΔE 13.0 protan, normal-vision 19.8,
contrast ≥3:1). Do not introduce a third series colour — fold into "other", facet, or
use small multiples.

There is deliberately **no dark mode**: the sales dashboard commits to one light,
print-friendly world, and making only the inventory pages differ would recreate the
drift the shared renderer exists to prevent.

---

## Gap between these and what the code currently produces

| # | Reference does | `dashboard_html.py` currently does | Fix sits in |
|---|---|---|---|
| 1 | Hero is a self-contained dark band | Inherits the sales 2-column hero and breaks | `_hero` + its own CSS |
| 2 | Date once, in the masthead | Three times | `render` / `_view_html` |
| 3 | Summary = 2-up lead + shape chart | Single column, stacked | `_view_html` |
| 4 | Six queue rows in summary, all in Detail | All fifteen in summary | `charts.queue_ladder(limit=)` |
| 5 | Locations and divisions side by side | Separate full-width layers | layer composition |
| 6 | One caveats block | One `.note-band` per caveat | `render` |
| 7 | KPI cards carry a severity pill | Stripe only, no word | `_kpi` |
| 8 | Unmeasurable states say so (`FOOTWEAR — not set`) | Prints `SAR 0` | `stock_health.build` (gap 2) |
| 9 | Scoped view states it does not own breakdowns | Shows the wider view's unfiltered rows | `_stock_health_view` |
| 10 | `#view/layer` in the URL | No routing | `_script` |

Items 1–7, 9 and 10 are presentation and can be done without touching any figure. Item 8
needs the threshold scan and is tracked separately.

Item 9 is a live defect, not only a design gap: the generated *Needs action only* view
states that its totals will not match the all-stock view, and then prints unfiltered
location and division tables underneath that sentence.

---

## Rules for keeping these honest

These are exemplars, so they carry real numbers and can therefore go stale or, worse, be
mistaken for output. Two guards:

- Every reference states **"Reference design"** in the rail and the date the figures
  belong to. Never remove that.
- The figures are the committed `outputs_ageing/report_ageing.json` and
  `outputs_stock_health/report_stock_health.json` as at 2026-08-12. If a reference is
  updated with newer figures, update the date in the rail and the masthead together.

Do **not** wire these files into the pipeline or publish them to a client container —
they are documentation. The pipeline writes `report_dashboard_*.html`.
