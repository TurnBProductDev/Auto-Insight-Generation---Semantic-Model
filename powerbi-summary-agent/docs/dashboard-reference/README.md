# Inventory dashboard - reference designs

Two hand-authored exemplars that define what a finished inventory dashboard should
look like. They are the **design target**, not generated output.

| File | Report | Figures | Opens in a browser |
|---|---|---|---|
| `reference_inventory_management.html` | Inventory Management | live, as at **19 Aug 2026** | yes |
| `reference_inventory_management_standardised.html` | Inventory Management, terminology per the business rules | live, as at **19 Aug 2026** | yes |
| `reference_stock_age_analysis.html` | Stock Age Analysis (WP5) | live, as at 12 Aug 2026 | yes |

The two Inventory Management pages are **both current and both maintained**. They carry
the same figures from the same scan and differ only in vocabulary and in one extra tab -
see *The standardised version* below. Neither replaces the other; the standardised page is
a separate file and the original is never rewritten by its build.

Everything below describes `reference_inventory_management.html`, the plain-language
page. The standardised page shares its scan, its facts module and its structure.

`reference_inventory_management.html` is **built, not typed**. Three files beside it
reproduce and check it, and they must stay in step with it:

| File | Job |
|---|---|
| `inventory_management_scan.json` | The raw read of the semantic model. The only source of figures. |
| `inventory_management_facts.py` | Derives every published figure from that scan. Asserts the model reconciles, and refuses to produce facts at all if it does not. |
| `build_inventory_management_reference.py` | Renders the page. Idempotent - rebuilding produces a byte-identical file. |
| `audit_inventory_management_reference.py` | Audits the **produced page**: 101 checks over the arithmetic, the document, the plain language, and the grounding of every figure in the prose. |
| `inventory_management_br_counts.json` | BR-08 / BR-26 / BR-28 counts. Kept separate from the main scan so the original page's inputs are provably untouched. |
| `build_inventory_management_standardised.py` | Renders the standardised page. Idempotent, and writes only its own file. |
| `audit_inventory_management_standardised.py` | Audits the standardised page: 168 checks, adding BR-03 synonyms, BR-31 state names, the exclusion list and the Overview tab. |
| `inventory_management_standard_counts.py` | Re-exports the BR counts for the auditor. |

```bash
python build_inventory_management_reference.py       # the plain-language page
python audit_inventory_management_reference.py       # 101 checks

python build_inventory_management_standardised.py    # the business-rules page
python audit_inventory_management_standardised.py    # 168 checks
```

Running either build never touches the other page. The standardised build was verified
against the original's checksum before and after.

The Inventory Management figures come from report `ea29c0ea-2b15-4b29-b506-82afa92b4240`
in workspace `2829a4af-2e07-4b43-b913-0a829a06bef4`, semantic model
**`16d47b06-f48c-4a50-9d61-3fc91791ad73`**. Neither reference is produced by the pipeline;
`src/domains/inventory/dashboard_html.py` is what must be brought up to them.

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

## The standardised version

`reference_inventory_management_standardised.html` is the same report with its terminology
aligned to **`business_rules_Inventory.md`**, which is the authority for KPI names,
inventory classifications and business language. It exists because the plain-language page
below optimises for a reader with no background, while a trained user reads the Power BI
report itself - and the two must not use different words for the same thing.

### What changed

Every approved name in **BR-03** is used, every time:

| Plain-language page | Standardised page | Rule |
|---|---|---|
| product | **SKU**, or **Loc-SKU** for one SKU at one Location | BR-03, BR-08 |
| shop | **Store**; **Location** for a Store or Warehouse | BR-03 |
| Department | **Division** | BR-02 |
| stock not selling | **Non-Moving** | BR-03, BR-24 |
| more stock than needed | **Excess Stock** | BR-03, BR-20 |
| sales missed | **Opportunity Loss** | BR-03, BR-16 |
| days of stock | **Burn-Out Days** | BR-03, BR-09 |
| written off | **Damage** | BR-03, BR-29 |
| plain description first | **Recommended Action state name first**, never abbreviated | BR-31 |
| no currency symbol | **USD** on every money figure | BR-00 analogue |

Two further things the rules document forced, both of which made the page more correct:

- **BR-08 separates `#SKUs` from `#Loc-SKUs`, and the page had been conflating them.** The
  120,897 rows are Loc-SKUs - one SKU at one Location - covering 44,504 distinct SKUs. Every
  count now says which it is, and where a classification is stated across Locations the page
  gives both (Non-Moving is 31,608 Loc-SKUs and 22,510 SKUs), which is what **BR-26**
  requires.
- **BR-28's Unwanted SKUs were missing entirely.** 117 SKUs carry Excess Stock *and* have
  more arriving in Pending Orders, worth USD 7,840. The rules call this one of the most
  actionable signals in the report, and it is now in the Excess Stock story.

### Where two rules disagreed

Four sentences sat between conflicting rules; each was resolved toward the stricter reading
and is recorded here rather than left to be rediscovered:

| Phrase | Conflict | Resolution |
|---|---|---|
| "surplus above the threshold" | BR-20 uses *Surplus Qty*; BR-03 bans *surplus* as a name for Excess Stock | "only the portion above the coverage threshold counts as Excess Stock" |
| "write-off risk" | BR-25 says *write-off risk*; BR-03 bans *write-off* as a name for Damage | "obsolescence risk", which BR-25 also uses |
| "based on sales velocity" | BR-16 prescribes it; BR-33 bans *velocity* | "based on average daily sales and retail price" - BR-16's own formula |
| "replenishment need" | BR-30 uses it; BR-03 bans *Replenishment* as a name for Transfer | "the reorder decision" |

### The naming clash the page states rather than hides

The health-score model names one risk **Dead Stock**. BR-03 bans that phrase for the
classification the business calls **Non-Moving** - and they are the same thing. The page
uses Non-Moving throughout, prints the model measure name in small grey type under the risk
so a user can still find it in the model, and carries a caveat saying so. The same applies
to the model's *Verge of Stockout* against BR-17's *On the Verge of Stockout*.

The auditor enforces both directions: the banned synonyms must be absent, **and** all six
model measure names and all fourteen BR-31 state names must be present. "Standardise" can
never quietly become "delete the model's terminology".

### What was deliberately excluded

The rules document is written for one client. Carried over: rules, definitions, KPI
vocabulary, thresholds as concepts. **Not** carried over, and asserted absent by the
auditor: the Saudi and SAR references, the seven location codes, the nine named Divisions,
the named Sections, the lead-day and excess-threshold tables, and the buying team's name.
Where the page names a Location, Division or Section it is reading the semantic model's own
data, not that document.

### The Overview tab

The standardised version carries **six** tabs rather than five: an **Overview** leading on
the BR-08 headline measures, Stock Value by Location, the most urgent Recommended Actions
and the two figures that cover a period - then Inventory Health Score, Where to focus,
Locations, Divisions and Recommended Actions. The auditor asserts Overview exists, comes
first, carries the measures, and does *not* carry the score gauge.

---

## Everyday language, with the model's own words kept alongside

Someone with no business background has to be able to read this page. So it says **"more
stock than needed"** and prints *"called Excess Stock in the model"* underneath in small
grey type. Both readers are served, and the page can never drift from the semantic model's
vocabulary. The queue table does the same: the plain description on top, the model's own
code beneath it.

Words like *SKU*, *materiality*, *eligible*, *P90*, *breadth*, *velocity*, *burnout*,
*scoped* and *opportunity loss* appear nowhere else on the page, and the auditor fails the
build if one of them creeps back in. The two places where the model's vocabulary is
deliberately shown are stripped out before that check runs, and the auditor separately
asserts that all six model names and the queue codes are still present - so "simplify" can
never quietly become "delete the model's terminology".

Where a technical idea cannot be avoided, it is explained in the sentence that uses it. The
"90th-percentile benchmark" became *"products are only compared with similar products in the
same shop, so an expensive product does not look worse simply because it costs more"*.

### Proving a wording pass changed only wording

The plain-language rewrite was applied to a page that had already been approved, so the
risk was not a bad sentence - it was quietly moving the furniture while claiming to reword
it. The check that settles it: reduce both the old and new HTML to their **tag + class
skeleton** in document order, with every scrap of text removed, then compare the two as
multisets. Anything left over is a structural change and has to be justified out loud.

Run positionally, that diff is useless - inserting one sentence makes every following table
row read as "moved". Compared as multisets it answers the real question: same elements, same
numbers? On this pass it came back with **zero removals** and exactly the additions that
were intended: six `p.d-model` lines and fourteen `span.act` codes. It also caught two
things that had crept in unnoticed - an explanatory note under a table, and a method
paragraph split in two - and both were reverted.

It caught a content loss as well: one caveat, the one about products with no reorder level,
had gone missing in the rewrite. Counting `<li>` elements is what found it.

## The Inventory Health Score - the story spine

### The score is the model's own, and every figure reconciles

An earlier version of this reference invented a five-driver composite (Availability, Cover
discipline, Movement, Buying quality, Data integrity) because the model held no score of
its own. **It does now.** `_HEALTH SCORE MEASURES` publishes an Inventory Health Score
built exactly as the Retail Inventory Health Score methodology describes it, and the
invented drivers have been removed. Using anything other than the model's own vocabulary
here is a defect: the page and the semantic model must say the same words.

Every SKU starts at 100 and loses points to six risks, each capped at 25:

| Risk | Points lost | Share of the loss | Behind it |
|---|---|---|---|
| Excess Stock | 12.5 | 30.2% | 1,823,947 above cover, 51,255 lines |
| Ageing Stock | 10.2 | 24.7% | 1,609,994 ageing, 56,852 lines |
| Dead Stock | 7.2 | 17.3% | 807,388 not moving, 31,606 lines |
| Out of Stock | 6.2 | 14.9% | 19,347 lines, 1,626,901 of sales at risk |
| Verge of Stockout | 4.6 | 11.1% | 1,700 lines, segment severity 89.0% |
| Damage | 0.7 | 1.8% | 106,624 written off in the latest month |
| **Total** | **41.5** | **100%** | **score 58.5 - Critical** |

Each risk is rebuilt from three dimensions rather than averaged from the level below -
value impact (50%), SKU breadth (30%), duration or severity (20%); 70/30 for damage, which
has no duration term - then multiplied by 25 and capped. The auditor re-derives all six
from their own dimensions and asserts they close on the published score.

Bands are the methodology's, not a design choice: **90+ Excellent, 80-89 Healthy, 70-79
Watch, 60-69 At Risk, below 60 Critical.** Out-of-stock lines start from 0 rather than 100,
are not floored, and are labelled Out of Stock rather than placed in a band.

Three rules this must keep:

- **The waterfall shows composition, not movement.** With one snapshot there is no movement
  to decompose. It runs 100 -> each risk -> 58.5, ordered biggest cause first, and the six
  deductions add to the whole of the loss so nothing is unexplained. Its axis floats and
  *says so*.
- **The weights, caps and bands are printed on the page**, on every risk card and in a
  "How the score is worked out" panel. A composite a manager cannot argue with is a
  composite they cannot act on.
- **The company score is not the average line.** The average scored line reads 71.9 against
  a company score of 58.5, and the page states why: the score is rebuilt from where the
  value and the breadth actually sit. Leaving that gap unexplained invites the reader to
  assume one of the two numbers is wrong.

### The focus sub-stories

Four areas, ordered by **what they are costing the score** - not by how much money they
hold. On this position that is Excess, Ageing, Dead and Out of Stock, which together account
for 36.1 of the 41.5 points lost. Each carries four slots:

```
What it is                 -> the figure, plainly, with the product count
Why it happened            -> the mechanism, not a restatement of the number
What it does to the score  -> its share of the points lost, in context
Do this                    -> one concrete next step, with the count to act on
```

Those four headings are the plain-language versions of the original slots. The shape did
not change; only the words did.

The first slot is **"What it is", not "What changed"** - deliberately. The model holds one
health snapshot, so there is no change to state, and a slot headed "What changed" could only
be filled with something invented. It becomes "What changed" the day a second snapshot
lands.

### Honesty rule for the history

Snapshot history has only just begun to be captured. The score line under "The story"
therefore shows **the shape the chart will take and nothing else**: it is dashed, its
points are unlabelled, it carries the words *"shape only - no past values are implied"*
inside the plot, and a banner above it says the same. Only the final point - the real
19 August reading - is drawn solid and given a value.

Drawing a plausible line with invented values on it would have been worse than drawing
nothing, because every one of those values would have been quotable. The auditor enforces
both markers.

The one **genuinely historical** series in the model is store stock value at four dates
(1 Jun, 1 Jul, 1 Aug, 19 Aug), from `SSR TREND`. It sits on the Locations layer, labelled
as the real series, and it is what exposes the ST5 wind-down: 815,718 -> 62,478, down
92.3%.

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
                    |  hero          dark band: verdict + gauge + 3 proof stats
                    |  banner        the one thing that would be misread
                    |  ─ The story ─────────────────────────────────────
                    |  full width    the lead chart, whatever carries the argument
                    |  2-up          supporting chart (1.55fr) | distribution (1fr)
                    |  ─ The six problems ──────────────────────────────
                    |  cards         6 across 3 columns, severity pill + own weights
                    |  method        how the score is worked out
                    |  caveats       ONE block, bulleted
                    |  footer        provenance
```

That is the *summary* layer. Four more sit behind the rail — **Where to focus**
(the sub-stories, then the evidence behind them), **Shops**, **Departments** and
**Every product** — and each of the two views carries all five.

### Non-negotiables

- **Summary first, then breakdowns.** The first section is the whole position. Nothing
  above it except the verdict.
- **The date appears once**, in the masthead.
- **Two columns wherever content allows.** A 1280px page running one narrow column is
  the single biggest reason the generated version looked unfinished.
- **The lead chart carries the report's argument, and gets the full page width.**
  Inventory Management leads with the health score against its bands; Stock Age leads with
  the age distribution and its aged portion. A chart that carries the argument and is then
  squeezed into a 1.55fr column renders its own axis labels at 7px — that was one of the
  three layout faults caught by rendering this rewrite.
- **Six cards go three across, not auto-fit.** `repeat(auto-fit,minmax(232px,1fr))` lays
  six cards out 5+1 at 1280px and four stories 3+1, orphaning the last one beside a gap the
  width of two cards. Fixed column counts that divide the card count exactly.
- **A summary shows the top of a list, never all of it.** Six queue rows under
  "Where to focus"; all fourteen in Action queue, with a line saying so.
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
| 3 | Summary = full-width chart, then a 2-up | Single column, stacked | `_view_html` |
| 4 | Six queue rows in summary, all fourteen in Detail | All fifteen in summary | `charts.queue_ladder(limit=)` |
| 5 | Locations and divisions each own a layer | Separate full-width layers | layer composition |
| 6 | One caveats block | One `.note-band` per caveat | `render` |
| 7 | Risk cards carry a severity pill and their own weights | Stripe only, no word | `_kpi` |
| 8 | Unmeasurable states say so (`FOOTWEAR - no cover threshold set`) | Prints `0` | `stock_health.build` (gap 2) |
| 9 | Scoped view states it does not own breakdowns, in all three layers | Shows the wider view's unfiltered rows | `_stock_health_view` |
| 10 | `#view/layer` in the URL | No routing | `_script` |
| 11 | Opens on the model's own Inventory Health Score | Opens on the work queue | new `inventory_health.py` + `dashboard.py` |
| 12 | Four focus sub-stories (what it is / why / effect / do this) | KPI cards and tables only | `dashboard.py` |
| 13 | Queue and estate split demoted to "the evidence behind those four" | They are the summary | layer composition |
| 14 | Every nav button reaches a layer in **both** views | n/a | `_view_html` |
| 15 | Everyday language, with the model's own term shown beside it | Emits the model's term alone | `dashboard.py` + `charts.py` |

Items 11-13 are now **buildable against real figures** - the score exists in the model, so
they no longer wait on retained history. Only the score's *trend* does.

Item 14 is a defect this rewrite fixed in the reference itself: the previous version had no
`focus` layer inside the scoped view, so clicking "Where to focus" there hid every layer and
left a blank page. Both views now carry all five layers, and the auditor asserts it.

## Rules for keeping these honest

These are exemplars, so they carry real numbers and can therefore go stale or, worse, be
mistaken for output. Three guards:

- Every reference states **"Reference design"** in the rail and the date the figures belong
  to. Never remove that.
- Inventory Management is rebuilt from `inventory_management_scan.json`, never edited by
  hand. To refresh it: re-run the scan against the model, replace that file, then rebuild
  and audit. Update the date in the rail, the masthead and this README together - the
  builder takes it from `AS_AT`.
- **Run the auditor after any change, and look at the rendered page.** The auditor catches
  arithmetic, grounding and jargon; it cannot see layout. Both matter, and only one of them
  is automated. Rendering is what caught every layout fault in this work: a chart too small
  to read once squeezed into a column, six risk cards wrapping 5+1, four stories wrapping
  3+1, and a card left half empty because it held only two bars.
- **Keep the plain-language pass honest.** If a new sentence seems to need a technical word,
  either explain it in the same sentence or add the word to the auditor's jargon list and
  find another way to say it. That list is the specification, not a suggestion.
- **If you are asked to reword the page and change nothing else, prove it.** Keep a copy of
  the page before the pass, then compare tag+class skeletons as multisets (see above). "I
  only changed the words" is very easy to believe and very easy to get wrong.

```
chrome --headless=new --screenshot=out.png --window-size=1500,2500 \
    "file:///.../reference_inventory_management.html#all/summary"
```

Do **not** wire these files into the pipeline or publish them to a client container - they
are documentation. The pipeline writes `report_dashboard_*.html`.

## What the model cannot currently do

Recorded here because each one changes what the page is allowed to claim:

- **Warehouses are not scored.** `FCT SKU HEALTH`, `LOC_CATEGORY_HEALTH` and
  `P90 CATEGORY STORE` hold ST1-ST5 only. Warehouse scoring is planned; until it lands the
  page states which locations the score covers, and shows WH1/WH2 as stock evidence with no
  score attached, never added to the store total.
- **`LOC_CATEGORY_HEALTH` and `P90 CATEGORY STORE` carry no relationships.** Slicing the
  score by `LOC_CATEGORY_HEALTH[DEPARTMENT]` returns the company total for all four
  departments. Every roll-up on the page is built from `REP_SSR_STOCK_STATUS_REPORTV2`
  instead, which propagates correctly and reconciles to 4,964,930 exactly.
- **FOOTWEAR has no cover threshold**, so its Excess risk scores zero across 5,583 lines
  holding 214,739 - its 64.1 is flattering. The threshold table names the section
  `CF-FOOT WEAR`; the stock data names it `FOOTWEAR`; the two never match. `CF-COMPUTER ACC`
  is a single line and is marked as unreadable.
- **7,896 lines holding 353,377 carry no usable reorder level.** They are shown as *cannot
  assess* in the queue rather than counted as healthy, which is why the queue splits three
  ways rather than two.
- **Sales at risk must be published scoped.** The model's own `OPPORTUNITY LOSS` column is
  already restricted to prime actionable lines at stores and reads 59,051. The unscoped
  stockout column reads 313,038 - 6.4x - and is not comparable.
- **ST5 is a wind-down**, confirmed with the business. It is kept in the estate table and
  flagged, never silently excluded and never read as an availability failure.
- **Values carry no currency symbol.** The model declares none, and the methodology
  document's worked examples use a different one from the group. The page states the unit
  once, in the caveats.
