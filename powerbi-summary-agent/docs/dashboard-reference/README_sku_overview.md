# SKU Overview — reference design

`reference_sku_overview.html` is the **design target** for the SKU Overview dashboard — the
report that tracks every product in every shop, and follows one product's complete story
end to end. It is not produced by the pipeline.

Same shell as `reference_daily_sales.html`, `reference_target_tracker.html` and the two
inventory references: rail + main and nothing else inside `.app`, layers, two views,
`#<view>/<layer>` in the URL so a tab is linkable and a screenshot tool can reach it without
a click. The CSS variables, the `.card` / `.kpi` / `.rb` / `.pill` / `.caveats` / `.foot`
components and the nav script are the same system, so a styling fix lands on all five pages.

| | |
|---|---|
| Report | SKU OVERVIEW - MOBILE VIEW INCLUDED · `47003525-99b7-4121-8ecb-5f0b67b62d8b` |
| Dataset | `867a2a79-8360-44e5-856e-2543e5ab0d6e` (resolved via `GET /reports/{id}`) |
| Workspace | `2829a4af-2e07-4b43-b913-0a829a06bef4` (SB Mart) |
| Rulebook | *SKU Overview — Insight Rules*, Rules 1–8 |
| As at | **23 August 2026**, the model's own `UPDATED_ON` |
| Population | **ST1–ST5**. WH1/WH2 hold stock but do not sell |
| Currency | **USD** — see *The currency trap* below, which is the whole reason this page needed a decision before it could be built |

Every figure is live data pulled on 2026-08-24 and re-derived arithmetically.

## The four files

```bash
python scan_sku_overview.py                 # live read  -> sku_overview_scan.json  (55 queries)
python sku_overview_facts.py                # derive + reconcile, prints the fact sheet
python build_sku_overview_reference.py      # render     -> reference_sku_overview.html
python audit_sku_overview_reference.py      # 97 checks over the produced page
python mutate_sku_overview_audit.py         # 12 mutations, all of which must be caught
```

| File | Job |
|---|---|
| `sku_overview_scan.json` | The raw read of the semantic model. The only source of figures. |
| `sku_overview_facts.py` | Derives every published figure and owns the **one** currency conversion. **Refuses to produce facts at all if the model stops reconciling** (33 checks). |
| `build_sku_overview_reference.py` | Renders the page. Idempotent — rebuilding produces a byte-identical file. |
| `audit_sku_overview_reference.py` | Audits the **produced page**: arithmetic re-derived from the scan, prose grounding, rounding, vocabulary, document structure, self-containment. |
| `mutate_sku_overview_audit.py` | Breaks the page and the scan twelve ways and fails if any goes unnoticed. |

## The currency trap — read this first

**This model publishes money on two different bases, and nothing in it says so.** Putting
them on one page without converting compares numbers that are 3.7× apart. Measured, not
assumed:

| Column | Basis | Evidence |
|---|---|---|
| `SKU_STOCK_VALUE`, `EXCESS_STOCK_VALUE`, `PENDING_ORDERS_VALUE`, `AVG_DAILY_SALES_VALUE` | **already USD** | ratio to `CURRENT_STOCK × LC` is **0.27**, median exact, across 93,904 rows |
| `TOP SALES DATES IN LOC[sales_value]` | **already USD** | ratio to `qty × min_rp` floors at exactly 0.27 across 342,192 rows |
| `SALES_VALUE_LAST_1MONTH` / `_3MONTHS` | **local currency** | ratio to `LC` is 1.40 median — a retail markup, not 0.27 |
| `OPP_LOSS_DUE_TO_STOCKOUT` | **local, and it is ONE DAY** | `= AVG_DAILY_SALES_VALUE ÷ 0.27` **exactly** on all 4,583 rows that carry one (min = max = 3.7037) |
| `RP`, `LC`, `min_rp`, `max_rp` | **local** | these are shelf prices; the model never converts them |

Sales value is the ranking metric for Rules 1, 4, 5, 7 and 8, so this decides most numbers
on the page. **The agreed resolution:** multiply the local columns by **0.27** — the same
rate the model itself already applies — so the page is genuinely all-USD and internally
consistent. Using the true peg (0.2667) instead would put sales on a different basis from
stock and the page would not add up against itself.

`sku_overview_facts.usd()` is the only place this conversion happens. The scan keeps both
bases raw, and every column name says which it is (`_local` / `_usd`).

Two consequences the page states out loud rather than hiding:

- **Opportunity loss is a daily rate, not a running total.** The supplied source material
  presented it as *"has already cost …"*. It has not; it is what is estimated to be lost
  each day the shelf stays empty. It is also only populated on **1,728 of the 2,439** empty
  best-seller lines — a blank is not a zero, so the real figure is higher.
- **The live Inventory Management report publishes this same column unconverted**, labelled
  `USD 49,076/day`. This page publishes it converted (`USD 6,985/day` for the top band,
  `USD 13,230/day` across every empty shelf), so **the two reports will not agree on it**.
  That is disclosed in the caveats rather than quietly reconciled. The model fix is to
  publish one basis.

## The structure

```
rail        Overview · One product in full · What is selling · What needs action ·
            Departments and shops        |    All products · Best sellers only

Overview    hero verdict + three proof numbers
            4 KPI cards
            full width: every product line by what to do next   (the argument)
            2-up: what each problem is worth | best sellers' share of range vs sales
            one caveats block
One product the featured product, end to end — identity, 4 KPI cards,
            weekly units shop by shop, the same product in 3 shops with 3 different
            problems, price against its own range, what to do next, its category
What is     Rules 1-3: top 3 per department; yesterday's standouts;
selling     and the one insight that is honestly not available
What needs  Rules 4-8: empty shelf on a best seller; the free refill;
action      ordering dead stock; ordering more surplus; markdowns
Departments every department, every shop, and all 14 instruction states
and shops
```

**Structure is code-owned, prose is not** — the same inversion R6 makes, for the same
reason: every finding must be *covered* whether or not it has a headline.

### The drill axis is the product

The Daily Sales page drills through time and the Target Tracker through periods. This one
drills through **the product**, because that is what the report is: one row per product per
shop. The second layer exists to prove the point the whole report rests on — that the answer
is not the same in every shop.

### The two views

`All products` and `Best sellers only` (the model's top sales band, `SEG_A`). The second
**owns its rows**: every total, department, shop, instruction state and finding is
recomputed over just those products by a second pass of the scan, so the rows on that page
add up to the totals on that page. Rule 4 is the one exception and says so — it only ever
covered best sellers, so it is identical in both views.

Best sellers are **11.2% of product lines and 55.2% of sales**, which is why the scoped view
earns its place.

## The featured product

Chosen by a stated rule — *the top-band product with an empty shelf carrying the most sales
behind it* — and asserted in both the facts module and the auditor, so the page's lead story
is always the story the rule promises.

On this position that is **Doux Whole Chicken 1300gm C10** at **ST2**, and it is a better
worked example than anything that could have been invented:

| Shop | State | Stock | Sold, 3 months |
|---|---|---|---|
| ST1 | **not selling** — last sale 39 days ago | 1 unit | USD 22,467 (the most of the three) |
| ST3 | **almost gone** — 4 days of stock | 184 units | USD 16,980 |
| ST2 | **shelf empty**, nothing on order | 0 | USD 14,357, USD 170.22/day being missed |
| WH2 | warehouse, also empty — so ST2 cannot be refilled internally | 0 | — |

Its weekly run at ST2 is a clean decline into the stockout: **161 → 93 → 75 → 35 units**, a
fall of 78.3%. ST1 does not appear on that chart at all, because it recorded no sale in any
of the four weeks — and the page says so rather than leaving a gap.

It is also **number one in its category**, which is what makes the empty shelf worth leading
on.

### One observation the page makes carefully

ST1 is charging **the most it has charged for this product in the window** (17.95 against a
low of 16.00) **and has not sold one for 39 days**. The page states both facts and then says
in as many words that it *cannot* tell you whether the price is the reason — the model holds
no record of what the price was on any given day. That restraint is the rule, not a
stylistic choice.

## What this model cannot do

Each one changes what the page is allowed to claim:

- **No rank history.** The model computes each product's position in its category *as it
  stands today* and keeps no record of what it was. Rule 2 (climbers and fallers) is
  therefore **not buildable**, and the page says so in a card of its own, with what would
  fix it, rather than approximating it from a single-period field. Do not infer movement
  from `SALES_GAP` or `ACTIVE_DAYS`; neither is a rank history.
- **Four weeks of weekly units, and only for ST1–ST4.** `WEEK SALES` is the only genuine
  time series in the model. It is quantity only — no money — and ST5 is absent from it. Four
  weeks is stated as recent shape and never called a trend.
- **`min_rp` / `max_rp` carry no date.** They are the whole-window range for a product-shop
  pair, identical on every dated row. The page can say a price has moved and is currently at
  the bottom of its range; it cannot say when it moved.
- **`LOC_TYPE` is `SH` for all seven locations**, warehouses included. It does **not**
  separate shops from warehouses — only `LOC_CODE IN {ST1..ST5}` does. Any rule written
  against `loc_type = 'SH'` will silently include the warehouses.
- **Opportunity loss is populated on 24.8% of stockout rows** (4,583 of 18,495 across all
  locations).
- **One instruction state, *in stock but never sent to a shop*, exists only at the
  warehouses**, so the shops show 14 of the model's 15 states. The page says which and why —
  an absent state and a state the source never produces look identical, and only one of them
  is good news.
- **ST5 recorded no sales at all in the last four weeks**, having sold USD 208,755 in the
  three months before. It still holds USD 62,473 of stock. The page surfaces this as a
  finding and asks whether the shop is closing or whether its sales have stopped reaching
  the report — it does not guess.

## Language

Everyday words, with the model's own term shown beside them in small grey type, exactly as
the inventory plain-language reference does. The auditor enforces **both directions**.

| Never | Always |
|---|---|
| SKU | **product**; *product-shop line* for one product in one shop |
| store, location, outlet, branch | **shop** |
| opportunity loss | **sales being missed**, always with *each day* |
| burnout days | **days of stock** |
| velocity, how fast it moves | **units sold each week** |
| dead stock, non-moving | **not selling at all** (with `NON MOVING` shown beside it) |
| excess, surplus stock | **more on the shelf than needed** |
| Segment A / SEG_A | **best sellers** (with `SEG_A` named once) |

`SKU`, `materiality`, `velocity`, `burnout`, `P90`, `eligible`, `Loc-SKU` and `breadth`
appear nowhere on the page, and the auditor fails the build if one creeps back in. The
places where the model's vocabulary is deliberately shown are stripped out before that check
runs, and the auditor separately asserts that `NON MOVING`, `OVERSTOCK`,
`STOCK OUT - PLACE ORDER`, `ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE` and `SEG_A`
are all still present — so "simplify" can never quietly become "delete the model's
terminology".

**Colour never carries meaning on its own.** Every severity stripe is paired with a word:
`ACT NOW`, `FREE FIX`, `WATCH`, `HEALTHY`, `NO ACTION`.

## Verify it before calling it done

Run the auditor, then **render the page and look at every tab**. The URL carries the state:

```
chrome --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
  --user-data-dir=<tmp> --screenshot=out.png --window-size=1500,2300 \
  "file:///<abs path>/reference_sku_overview.html#all/product"
```

Layers are `#all/overview`, `#all/product`, `#all/selling`, `#all/action`, `#all/detail`,
and the same five under `#top/`.

Faults only a screenshot caught on this page, none of which any test would have found:

- **`&middot;` and `&mdash;` printed literally** in four places. They were HTML entities
  passed through the escaper, which is doing exactly its job. Entities that are meant to
  render must be written as the character, not the entity, anywhere a string goes through
  `e()`. Same class of fault as the mangled regex the Target Tracker README records.
- **The surplus table was clipped**, losing its last two columns and truncating values to
  `USD 3`. A six-column table does not fit the narrow half of a two-up; both order tables
  are now full width.
- **A 25-row table swallowed the section** beside a 10-row one. Capped at ten with a line
  saying what is not shown.
- **The "not available yet" card ran one narrow column down a full-width card**, leaving
  half the page white. Its three paragraphs are now a two-column block.
- **The 11.2% share was invisible** — too narrow to print inside its own segment, and
  printing it beside the segment landed it on top of the next one. It joins the label.
- **Products and product-shop lines were identical columns** in the shop table (one row per
  product per shop), which reads as a bug. One column, and a sentence saying why.

Structural invariants the page holds: `.app` contains **only** `nav.rail` and `main`;
content lives in `main > .page`; there is exactly **one** `<script>` tag. One self-contained
file, no external requests, no storage APIs, everything escaped, print rules force hidden
views open.

### The auditor is mutation-tested

`mutate_sku_overview_audit.py` breaks the page and the scan twelve ways — a second script
tag, an external stylesheet, a local-currency label, a raw float in the prose, a deleted
caveat, a dropped insight, banned jargon, a department that no longer adds up, a featured
product that is not the largest stockout, an opportunity-loss basis that is no longer one
day, stock value on an out-of-stock line, and surplus larger than the holding it sits in.
All twelve must be caught.

Two of them **were missed** on the first run, and the fix made the auditor genuinely
stronger: the honesty checks ran against the whole page, so a caveat deleted from *one* view
was still found in the other and passed. They now run **per view**. A mutation whose target
is not present is reported as `NO-OP`, never as a pass.

### Keeping this honest

Same three guards as the other references: the rail and this README both state **"Reference
design"** and the date the figures belong to; the page is rebuilt from `sku_overview_scan.json`
and never edited by hand; and the auditor runs after any change.

Do **not** wire this file into the pipeline or publish it to a client container — it is
documentation.

## Open items for the model owner

1. **Publish one currency.** Half the money columns are converted and half are not, with
   nothing in the model to say which is which. This is the single largest source of wrong
   numbers in anything built on this model.
2. **Decide the opportunity-loss basis** and make the Inventory Management report and this
   one agree.
3. **Snapshot the category rank weekly** so Rule 2 becomes buildable. About a month of
   snapshots makes it useful.
4. **Publish a dated price series.** `min_rp`/`max_rp` describe a range with no date, so no
   before-and-after price question can be answered.
5. **Extend `WEEK SALES` beyond four weeks and include ST5**, so the weekly picture can be
   read as a trend and covers every shop.
6. **Confirm what is happening at ST5** — four weeks with no recorded sales is either a
   wind-down or a broken feed, and the report cannot tell which.
