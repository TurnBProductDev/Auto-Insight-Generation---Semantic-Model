# Daily Sales — reference design

`reference_daily_sales.html` is the **design target** for the Daily Sales dashboard — the
report that scores each trading day against its own same-weekday benchmark band
(P20 / P50 / P80). It is not produced by the pipeline.

Same shell as `reference_target_tracker.html` and the two inventory references: rail + main
and nothing else inside `.app`, four layers, two views, `#<view>/<layer>` in the URL so a tab
is linkable and a screenshot tool can reach it without a click. The CSS variables, the
`.card` / `.kpi` / `.rb` / `.pill` / `.caveats` / `.foot` components and the nav script are
the same system, so a styling fix lands on all four pages.

| | |
|---|---|
| Report | DAILY_SALES_DASHBOARD · `6ddd2afa-a1b4-443c-854d-e1ec4ad88e77` |
| Dataset | `8d111712-9ea8-4a65-9bb9-58f00e49d379` (verified via `GET /reports/{id}`) |
| Workspace | `2829a4af-2e07-4b43-b913-0a829a06bef4` |
| Rulebook | Daily Sales Dashboard business rules, BR-00 … BR-19 |
| Anchor | **Wednesday 12 August 2026**, week 2 of the month |
| Population | **ST1 and ST4** — the only two stores in the model |
| Currency | **SAR** — Saudi Riyals, net of VAT (BR-00) |

Every figure is live data pulled on 2026-08-21 and re-derived arithmetically.

## The four files

```bash
python scan_daily_sales.py                 # live read  -> daily_sales_scan.json
python daily_sales_facts.py                # derive + reconcile, prints the fact sheet
python build_daily_sales_reference.py      # render      -> reference_daily_sales.html
python audit_daily_sales_reference.py      # 124 checks over the produced page
python mutate_daily_sales_audit.py         # 11 mutations, all of which must be caught
```

| File | Job |
|---|---|
| `daily_sales_scan.json` | The raw read of the semantic model. The only source of figures. |
| `daily_sales_facts.py` | Derives every published figure. **Refuses to produce facts at all if the model does not reconcile.** |
| `build_daily_sales_reference.py` | Renders the page. Asserts the store split and the Bills × Basket decomposition as it runs. |
| `audit_daily_sales_reference.py` | Audits the **produced page**: arithmetic re-derived from the scan, prose grounding, rulebook vocabulary, document structure. |
| `mutate_daily_sales_audit.py` | Breaks the page eleven ways and asserts the auditor objects to every one. |

## The drill axis is the hierarchy

The Target Tracker page drills through **time**, because its stated priority is
Daily → WTD → MTD → YTD. This one drills through the **hierarchy**, because BR-07 defines
four levels each owning its own benchmark table, and BR-15 says to investigate a measure
outside its band in two directions — *across* the other measures at the same level, and
*down* to the level below.

```
rail        The day · Stores · Departments · Detail   |   All areas · Outside the band only

The day     hero verdict + three proof numbers
            4 KPI cards, one per measure, each on its own band bullet
            full-width: Net Sales against the normal band, day by day
            "What carried the day"  Bills × Basket Value waterfall
            "Look across"           all four measures side by side      (BR-15)
            "Look down"             the two stores, then the department (BR-15)
            "What these figures cover, and what they do not"
Stores      ST1 and ST4, four measures each; then each store's own 14 days
Departments every department; share of baskets; ranked exceptions; store by store
Detail      what fell below its band | what beat it; groups that recorded nothing;
            every section; every category
```

**Structure is code-owned, prose is not** — the same inversion R6 makes, for the same
reason: every level must be *covered* whether or not it has a headline, and a prompt that
decides layout will drop one on a quiet day.

### The two views

`All areas` and `Outside the band only`. The second filters every breakdown to the stores,
departments, sections and categories that finished outside their band, and carries the amber
`.scoped` banner saying the day's own totals still describe the whole business. It **owns its
rows** — each row is its own band comparison, so nothing is reused from the wider view.

### The band bullet is the page's argument in one shape

Every measure everywhere is drawn the same way: a track, the normal band shaded on it, the
benchmark as a tick, the day as a marker coloured only if it left the band. BR-05 says
colour marks the exceptions only, and it is **always paired with the word** —
`Underperforming` / `In band` / `Outperforming` — never colour alone.

### The lead chart is band-relative, not in SAR

The first version plotted 14 days of Net Sales in SAR. The days are not the same size —
Friday is the Saudi weekend and takes about three times a Tuesday here — so the line was
dominated by two Fridays and the one day that fell out of its band was invisible at the
bottom of the plot. It is now **each day as a percentage of its own benchmark**, with the
band shaded around it. Every day is comparable, the exceptions are the only marks that leave
the shading, and the SAR figure is printed on every day that finished outside it, so no money
is lost from the page.

## What the day says

| | Figure | Band | Verdict |
|---|---|---|---|
| Net Sales | SAR 69,360.31 | 69,459.09 – 85,206.91 | **SAR 98.79 below the floor** |
| Bills | 5,780 | 5,671 – 6,296 | In band |
| Basket Value | SAR 12.00 | 12.25 – 13.53 | SAR 0.25 below the floor |
| Margin | 23.18% | 21.80% – 22.98% | **Above the ceiling** |

Three findings the arithmetic forces, each asserted in the build:

- **The whole group shortfall is one store.** ST4 finished SAR 98.79 under its own floor;
  ST1 landed *exactly* on its floor at SAR 38,040.48. Because BR-08 builds the group band by
  adding the two store bands, the group gap is the sum of the two store gaps — so the group
  miss is ST4's miss, to the halala.
- **The basket carried the day, not the number of baskets.** Net Sales is Bills × Basket
  Value, so `(Q1−Q0)·R0 + Q1·(R1−R0)` splits the SAR 7,068.35 gap against the benchmark
  exactly: 201 fewer Bills took off SAR 2,568.49, and each basket holding SAR 0.78 less took
  off SAR 4,499.86. The smaller basket is 64% of it.
- **It was the most profitable day in the window.** Margin at 23.18% is above its ceiling and
  is the highest of the 14 days. A soft day on takings was not a soft day on profitability,
  and BR-15's "look across" is what surfaces that.

Twelve of the fourteen days landed inside their band; 12 August is the only one below it.

## Three things about this model that shaped the page

### 1. The rulebook's store list does not match the model

BR-01 and BR-02 scope the report to **CFH014 and CFH021** and say to drop a third store. The
model holds exactly **two** stores, `ST1` and `ST4`, and no third. `CFH014` and `CFH021`
appear in one place only — `oos_dummy`, the table the model itself labels *"Illustrative dummy
data - pending real OOS feed"*, alongside department names (`FMCG FOOD`, `ELECTRONICS`,
`FASHION`) that do not exist anywhere else in the model.

BR-01's *intent* — two stores, nothing else in any total — is honoured against the real store
codes. **BR-01/BR-02 should be rewritten to name ST1 and ST4**, and the Section I open item
"which store code is the third, out-of-scope one" should be closed as "there isn't one".

### 2. The four benchmark tables are not unique at their stated grain

BR-07 says one row per date × store × department, and so on down. That is not what the tables
hold:

| Table | Rows on the anchor day | Distinct name keys |
|---|---|---|
| `departmentbenchmark` | 23 | 12 |
| `sectionbenchmark` | 87 | 46 |
| `categorybenchmark` | 1,596 | 245 |

One store-day carries **three rows named LIFESTYLE** and **six named LADIES APPAREL**. They
are real, different groups of merchandise — one of the three LIFESTYLE rows is exactly the
footwear business, and its three FOOTWEAR section rows add to it to the penny. The column that
identifies them (a department or section code) is not in the model.

The page adds their **Net Sales**, which is safe — money is counted once. It does **not** claim
their added bands are benchmarks: BR-13 says percentiles never add, and a caveat says so in as
many words. Their **Bills** are added too, which counts a basket that touched two sub-groups
twice — BR-14's own warning, happening *inside* a single department rather than between
departments. That is stated rather than hidden.

**The fix is in the model, not the page: publish the code column.**

### 3. A band summed over groups that did not trade is not a band

This one is a trap of the page's own making, caught while building it. Summing a name's rows,
`SUM(actual_sales)` skips the rows with no sale while `SUM(sales_p20)` includes every row's
floor — so a name whose sub-groups mostly went quiet reads far below a band it never had.
Measured: `LADIES T SHIRTS` in ST1 covers 20 sub-group rows of which **5 traded**. Compared
against all 20 floors it read SAR 197 short; compared like for like against the 5 that traded
it is *above* its floor. The first reading was pure artefact.

So every band on this page is summed over **the rows that actually traded**, and what went
quiet is reported separately, because it is a finding in its own right: **557 sub-groups
recorded no sale at all on this day, and on a matching past day they take SAR 6.2K between
them.** That is the "Groups that recorded nothing today" table on the Detail layer.

## What the model's own measures currently return

The four benchmark tables carry Net Sales at two different scales — the store table publishes
at the page's scale, the three levels below it are at unit scale — and the store table's
percentile columns are at the level scale rather than the store one. Everything on this page is
brought onto one scale before anything is compared, and `reconcile()` proves the relationship
holds on **every** store-day rather than assuming it, so a change to the model's scaling fails
the build instead of shipping.

The consequence inside Power BI is worth flagging separately: `[Sales vs Bench %]`,
`[Sales Verdict]` and `[Sales Band Pos]` compare the store table's actual against the store
table's percentiles without that adjustment, so **on the report itself every store-day reads
below P20** and the verdict measures are wrong at store level. Department, section and category
level are unaffected. This is a model fix, not a page fix.

Two smaller notes: `oos_dummy` and the six `OOS *` measures are labelled illustrative in the
model and are excluded here, matching the rulebook's decision to drop the stock section
entirely; and `_Underperformers` picks its four rows by `z`, which is why `GLASS ITEMS` — a
**SAR 20** shortfall — sits in it beside a SAR 1,634 one. BR-17 requires ranking by the size of
the gap in SAR, so this page does that, and the auditor asserts the SAR order is not the
percentage order.

## Language

BR-03 gives one approved name per thing, and the auditor enforces it in both directions —
banned synonyms absent, approved names present:

| Never | Always |
|---|---|
| revenue, sales value, turnover, GMV | **Net Sales** |
| footfall, transactions, customers, visits, traffic | **Bills** |
| ATV, spend per bill, average ticket, basket size | **Basket Value** |
| GP, GP%, profit | **Margin** |
| target, expected, norm | **Benchmark** (the P50) |
| range, expected range | **Normal band** (P20–P80) |
| branch, location, outlet, site | **Store** |

BR-06 is enforced too: the page carries no comparison with last year, and the only mention of
the phrase is the caveat saying there isn't one. BR-18 bans a vague comparison with no figure
beside it — `significantly`, `well below`, `slightly` and four more are checked **per sentence,
inside the element that states it**, because a check scoped to a character window finds a
number belonging to the chart next door and passes a claim that carries none.

One deliberate exception: **"group"** is used for the two-store total, and **"sub-group"** for
the unlabelled rows in §2. BR-03 bans *group* as a name for Department / Section / Category,
which is not what either use means — and BR-08 itself says "group benchmark band" and "group
figure".

## Verify it before calling it done

Run the auditor, then **render the page and look at every tab**. The URL carries the state, so
each is reachable directly:

```
chrome --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
  --user-data-dir=<tmp> --screenshot=out.png --window-size=1500,2050 \
  "file:///<abs path>/reference_daily_sales.html#all/day"
```

Layers are `#all/day`, `#all/stores`, `#all/departments`, `#all/detail`, and the same four
under `#out/`.

Faults only a screenshot caught on this page, none of which any test would have found — every
one is a layout fault on a page whose every number was right:

- **The "Look across" card overflowed its column** and threw its three verdict pills off the
  right edge of the page. Four fixed-ish grid columns do not fit the narrow half of a
  1.35fr/1fr row; the pill now sits inside the value cell.
- **`SAR&nbsp;0.78` printed literally** inside the waterfall. SVG text has no HTML entities, so
  SVG labels get a plain-space formatter — the same class of fault as the mangled regex the
  Target Tracker README records.
- **The departments table was clipped**, losing its last two columns, and the card beside it
  held two sentences and 300px of white. The table is now full width and the row beneath it
  carries real content — how many baskets each department reached, and the same five
  departments split by store.
- **Grid children stretched to the tallest card**, so a short card printed a block of white
  rather than ending. `align-items:start`.
- **`.mini span{display:block}` caught the verdict pill too**, stretching a 60px pill into a
  full-width bar.
- **Every x-axis label collided** on the 560px per-store charts, and two exception labels in a
  row overlapped on the wide one.

Structural invariants the page holds, all three of which broke on the first inventory
dashboard: `.app` contains **only** `nav.rail` and `main`; content lives in `main > .page`;
there is exactly **one** `<script>` tag. One self-contained file, no external requests, no
storage APIs, everything escaped, print rules force hidden views open.

### A verdict must not turn on floating point

ST1's Net Sales equals its own P20 to the cent. In binary it landed 4×10⁻¹² under it, and the
first build put the store on the problem list for it. Comparisons are now made at the precision
the model stores its percentiles to — two decimals — and a figure sitting on an edge reads
*level with its P20 floor*, which is both true and not an exception. Without it, BR-17's "a
finding must be worth a manager's time" is decided by a rounding artefact.

### Keeping this honest

Same three guards as the other references: the rail and this README both state **"Reference
design"** and the date the figures belong to; the page is rebuilt from `daily_sales_scan.json`
and never edited by hand; and the auditor runs after any change. The auditor is itself
mutation-tested — `mutate_daily_sales_audit.py` breaks the page and the scan eleven ways and
fails if any one goes unnoticed, because an auditor that passes proves nothing until it has
been shown to fail. It reports a mutation whose target is not on the page as **NO-OP** rather
than counting it as a pass; two of the first mutations written were silent no-ops that looked
exactly like successes.
