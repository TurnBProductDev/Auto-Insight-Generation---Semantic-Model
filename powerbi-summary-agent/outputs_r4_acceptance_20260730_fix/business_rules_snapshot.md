# Company Business Rules

These are our rules for how the numbers must be worked out and written up. The agent
follows them when it builds queries, looks for insights, and writes reports.

**These rules win.** If a rule here disagrees with the agent's normal way of doing
things, the rule here is what happens.

A copy of this file is saved with every run (`business_rules_snapshot.md`), so you can
always check which rules produced a given report.

This file is separate from `prompts/_global_rules.md`:

- `_global_rules.md` — permanent safety and tone rules. Rarely changes.
- `business_rules.md` — our business logic. This file. Changes as the business changes.

**Where these rules apply.** Every AI step uses them: report understanding, query
planning, query writing, insight detection, investigation, the insight report, **and
both summary generators**. So the rules shape the AI summary just as much as the deep
insight report.

Full background: `docs/business-repository/reports/R01-retail-brand-mis.md`.

---

## How to check this file

Every rule has a number, like `BR-01`. **The numbers never change meaning.** If a rule
is dropped, its number is retired rather than reused, so `BR-04` always means the same
thing. New rules get new numbers, which is why the numbers are not in perfect order
inside each section.

**To review this file quickly: read only the bold sentence under each number.** That
sentence is the rule. Everything after it explains why.

| Mark | What it means |
|---|---|
| **[V]** Checked | We ran a query against the live data and confirmed it. |
| **[B]** Business decision | The business told us this. It is true because we decided it. |
| **[A]** Assumption | Our best guess. **Someone needs to confirm it.** |

### All rules at a glance

| Number | Rule | Mark |
|---|---|---|
| BR-00 | Saudi Arabia, riyals, and no VAT in the figures | **[B]** |
| BR-26 | Always use the same word for the same thing | **[B]** |
| BR-28 | The three levers, and all 27 states they can be in | **[B][V]** |
| BR-32 | How to explain any revenue change | **[B]** |
| BR-01 | Which branches count for like-for-like | **[B]** |
| BR-02 | Leave CFH022 out of like-for-like | **[B][V]** |
| BR-03 | But still count CFH022 in total sales | **[B]** |
| BR-04 | Filter all four branch tables, not just one | **[V]** |
| BR-05 | No last-year figure means no percentage | **[B]** |
| BR-06 | Every branch is big enough to matter | **[V]** |
| ~~BR-07~~ | ~~CFH022 data cut-off~~ — **withdrawn**, see note | — |
| BR-08 | What each measure means | **[B]** |
| BR-09 | How the measures fit together | **[V]** |
| BR-10 | Transactions come from their own tables | **[V]** |
| BR-29 | Never add transactions across levels or categories | **[V]** |
| BR-31 | Transaction counts are category counts, not shopping trips | **[V][B]** |
| BR-11 | Never show price without basket size | **[B]** |
| BR-12 | "Price effect" is not only price | **[B]** |
| BR-13 | Say what is driving growth and whether it will last | **[B]** |
| BR-14 | Read the two category measures together | **[B]** |
| BR-15 | Ramadan and Eid move between months | **[B]** |
| BR-16 | We only have monthly sales, not daily | **[V]** |
| BR-17 | The daily table cannot do last-year comparisons | **[V]** |
| BR-18 | The last month is short, but both years match | **[V][B]** |
| BR-19 | Last year is a column, not a date calculation | **[V]** |
| BR-30 | Reports must focus on the most recent period | **[B]** |
| BR-27 | Put a number on every comparison | **[B]** |
| BR-23 | The red / amber / green bands | **[B]** |
| BR-24 | Only report things big enough to matter | **[B]** |
| BR-25 | Say what the numbers actually cover | **[B]** |
| BR-20 | Never use `KEEPFILTERS` | **[V]** |
| BR-21 | Run one measure per query | **[V]** |
| BR-22 | Use the model's own category measures | **[V]** |

> **BR-07 withdrawn (2026-07-29).** It said CFH022's data stops on 13 June. That is a
> data-loading fault, not business logic, and it is being fixed. Do not caveat CFH022
> for it. The number is retired and will not be reused.

---

# Section A — Where we trade

## BR-00 — Saudi Arabia, riyals, and no VAT in the figures **[B]**

> **This is a Saudi Arabian retail chain. All money is in Saudi Riyals (SAR), and all
> sales figures already exclude VAT.**

| Thing | What it is here |
|---|---|
| Country | Saudi Arabia |
| Currency | Saudi Riyal — always write **SAR** |
| VAT | **Excluded.** Sales figures are net of the 15% VAT |
| Time zone | Asia/Riyadh (UTC+3, no clock changes) |
| Weekend | **Friday and Saturday** |
| Working week | Sunday to Thursday |
| Reporting year | **The normal calendar year.** January is month 1 |
| Biggest trading periods | **Ramadan and Eid al-Fitr**, then Eid al-Adha |
| Fixed national days | Founding Day (22 February), National Day (23 September) |

Because VAT is already excluded, never describe a figure as "including VAT", and never
add or remove VAT from a number.

---

# Section B — The words we use

## BR-26 — Always use the same word for the same thing **[B]**

> **Use the approved name for every measure, every time. Never switch between two names
> for the same thing inside a report.**

| Approved name | What it means | Never call it |
|---|---|---|
| **Revenue** | Money taken, excluding VAT | Sales value, turnover, net sale value, GMV |
| **Units** | Number of items sold | Quantity, qty, volume, pieces |
| **Transactions** | Number of bills | Footfall, bills, customers, visits, traffic |
| **Price** | Revenue divided by Units | ASP, average selling price, unit rate, revenue per unit |
| **Basket Value** | Revenue divided by Transactions | ATV, spend per transaction, average ticket |
| **Basket Size** | Units divided by Transactions | UPT, units per transaction, items per basket |
| **Branch** | One shop | Store, location, outlet, site |
| **Category** | A product grouping | Product group, class, segment |

**"Footfall" and "transactions" mean the same thing here. Always write
"transactions".** We do not count people walking in, only bills, so never call it
visitors, shoppers, or traffic.

Say **"like-for-like"** for a same-branch comparison against last year. Do not mix in
"comparable", "LFL" and "same-store" in the same report — pick like-for-like and stay
with it.

---

# Section C — What moves revenue

## BR-28 — The three levers, and all 27 states they can be in **[B][V]**

> **Revenue only changes for three underlying reasons: how many Transactions, how many
> items in each basket (Basket Size), and what each item costs (Price). Always say which
> of the three moved.**

The full chain:

```
Revenue  =  Transactions  x  Basket Size  x  Price
```

Two more measures are just combinations of those three:

```
Units         =  Transactions  x  Basket Size
Basket Value  =  Basket Size   x  Price
```

**Checked on our own like-for-like numbers:** Transactions +3.03%, Basket Size -4.17%,
Price +4.17% gives revenue +2.84% and units -1.27% — exactly what the data shows.

### Why Basket Value is not a fourth lever

Basket Value (Revenue / Transactions) is **not independent**. It is simply Basket Size
multiplied by Price:

```
Basket Value  =  Basket Size  x  Price
```

So there are only **three** levers that can move on their own. Basket Value is the
combined result of two of them, and it is still worth reporting because it answers
"what is each visit worth?" — but never present it as a separate cause. If Basket Value
moved, the reason is always Basket Size, Price, or both.

The same applies to Units, which is Transactions x Basket Size.

There is also a shorter, two-lever view of revenue, useful for a headline:

```
Revenue  =  Transactions  x  Basket Value      (how many, worth how much each)
```

Use the two-lever view to state the result, then the three-lever view to explain it.

### The state matrix — all 27 combinations

Each lever can be **Up (+)**, **Flat (0)** or **Down (-)**, giving 27 states. Every one
is listed below with the narrative to use. **If you cannot map the data to a state here,
stop and say so — never invent a narrative.**

Treat a lever as **Flat** when its change is within about 1%, matching the materiality
floor in BR-24.

The **Revenue** column tells you when you may state the direction without arithmetic:

- **Up** or **Down** — certain. Every moving lever points the same way.
- **Depends** — the levers pull against each other, so the direction is a question of
  size. **You must multiply the growth factors (BR-09) and compute it.** Twelve of the
  27 states are like this, so most of the time you compute.

#### Category A — Volume-led growth (healthy)

Real demand expansion. Revenue is certain to rise in all six.

| Transactions | Basket Size | Price | Revenue | Narrative |
|---|---|---|---|---|
| + | + | + | **Up** | **Absolute growth.** More customers, buying more items, at higher prices. |
| + | + | 0 | **Up** | **Pure volume growth.** More people buying more items at stable prices. |
| + | 0 | 0 | **Up** | **Transaction-led growth.** The rise comes entirely from more transactions. |
| 0 | + | 0 | **Up** | **Cross-sell growth.** The same customers are adding more items per basket. |
| + | 0 | + | **Up** | **Transaction and price growth.** More transactions at higher prices, baskets unchanged. |
| 0 | + | + | **Up** | **Basket and price growth.** Same customers, fuller and dearer baskets. |

#### Category B — Price-led growth and masking (risky)

Price is carrying the result while the volume levers are flat or falling.

| Transactions | Basket Size | Price | Revenue | Narrative |
|---|---|---|---|---|
| 0 | 0 | + | **Up** | **Pure inflation.** The whole rise depends on higher prices or a dearer mix. |
| - | - | + | Depends | **Price masking. Severe risk.** Revenue may rise while we lose customers and sell fewer items. |
| - | 0 | + | Depends | **Trading up on a shrinking base.** Fewer customers, each spending more. |
| + | - | + | Depends | **Thinner baskets, higher prices.** More transactions, but each holds fewer, dearer items. **This is our current pattern.** |
| 0 | - | + | Depends | **Basket thinning masked by price.** Baskets are emptying; only price hides it. |
| - | + | + | Depends | **Fewer, richer customers.** Revenue can look healthy while the base shrinks. |
| - | + | 0 | Depends | **Narrowing base, fuller baskets.** Remaining customers buy more, at stable prices. |

#### Category C — Discounting and trade-offs (margin watch)

Prices are down: promotions, markdowns, or a shift to cheaper alternatives. Revenue is
only part of the story — margin is not visible in this model, so never call these a
success on revenue alone.

| Transactions | Basket Size | Price | Revenue | Narrative |
|---|---|---|---|---|
| + | + | - | Depends | **Successful promotion.** Lower prices drove both more transactions and fuller baskets. |
| 0 | + | - | Depends | **Stock-up promotion.** The same customers bought more because prices fell. |
| + | 0 | - | Depends | **Transactions-only promotion.** Price cuts brought more transactions but did not fill baskets. |
| - | + | - | Depends | **Consolidation.** Fewer customers, bulk-buying cheaper items. |
| + | - | - | Depends | **More transactions, less value.** More transactions, each holding fewer and cheaper items. |
| 0 | 0 | - | **Down** | **Pure price reduction.** Volumes unchanged; the fall is entirely price. |
| - | 0 | - | **Down** | **Fewer customers, lower prices.** Both levers against us, baskets unchanged. |
| 0 | - | - | **Down** | **Thinner and cheaper baskets.** Transactions hold, but each is worth less on both counts. |

#### Category D — Contraction (the warning zone)

Say which lever is falling fastest.

| Transactions | Basket Size | Price | Revenue | Narrative |
|---|---|---|---|---|
| - | 0 | 0 | **Down** | **Transaction loss.** The fall is entirely fewer customers. |
| 0 | - | 0 | **Down** | **Basket thinning.** Customers hold up, but cross-selling is failing. |
| - | - | 0 | **Down** | **Volume collapse.** Both fewer customers and thinner baskets. |
| - | - | - | **Down** | **Severe decline.** Fewer customers, thinner baskets and lower prices at once. The most serious state. |
| + | - | 0 | Depends | **More transactions, thinner baskets.** Extra transactions are not converting into items. |

#### Category E — No material change

| Transactions | Basket Size | Price | Revenue | Narrative |
|---|---|---|---|---|
| 0 | 0 | 0 | **Flat** | **No material change.** All three levers are within the materiality floor. Say so plainly rather than reporting noise. |

### What follows from the matrix

- **Units are certain** when Transactions and Basket Size move the same way, or one is
  flat. When they pull against each other, compute.
- **Basket Value is certain** when Basket Size and Price move the same way, or one is
  flat. It is decided by those two alone, never by Transactions.
- **The dangerous states are the ones where Transactions fall but revenue may rise** —
  price masking, trading up on a shrinking base, and fewer richer customers. Losing
  customers is the hardest thing to reverse, so **say it plainly whenever transactions
  decline, even when revenue is up.**

### The same growth, opposite meanings

Two states can produce an identical revenue figure. Base: 100 transactions, 5 items per
basket, SAR 10 per item — SAR 5,000 revenue.

| State | Transactions | Basket Size | Price | Revenue | Units | Read |
|---|---|---|---|---|---|---|
| Fewer, richer customers | 90 | 5.5 | 11.00 | **+8.9%** | -1.0% | Lost 10% of customers |
| Successful promotion | 110 | 5.5 | 9.00 | **+8.9%** | +21.0% | Sold 21% more by cutting price |

Both report **+8.9% revenue growth**. One is losing customers; the other is buying
volume with margin. A report that says only "revenue grew 8.9%" tells the reader
nothing. **Always break the change into the three levers.**

### Which lever means what

- **Transactions up** — more people bought. Usually the healthiest signal.
- **Transactions down** — we are losing customers or visits. Most serious warning.
- **Basket Size up** — customers are buying more per trip. Range and cross-sell working.
- **Basket Size down** — baskets are thinning. Often the first sign of trouble, and it
  is easily hidden by a rising price.
- **Price up** — either we put prices up, or customers moved to dearer items. **The
  numbers alone cannot tell you which** (see BR-12).
- **Price down** — either discounting, or a shift to cheaper items.

## BR-32 — How to explain any revenue change **[B]**

> **Follow these four steps in order every time you explain a revenue change. Never
> state a narrative before you have computed the levers.**

1. **Work out the change in each lever.** Transactions, Basket Size and Price, each as
   a percentage against the same prior period.
2. **Find the dominant driver.** Work out how much of the revenue change each lever
   accounts for, and identify the largest. This is the single most useful sentence in
   the whole explanation.
3. **Map to the state matrix.** Read each lever as Up, Flat or Down (flat is within
   about 1%) and find that state in BR-28. **If the state is not in the matrix, stop
   and say the pattern could not be mapped — never improvise a narrative.**
4. **Write it in this order:**
   - the overall revenue change, with the figure;
   - the mapped narrative;
   - the dominant driver, named and quantified;
   - anything the matrix marks as a risk.

**Worked example, using our own like-for-like figures:**

> Like-for-like revenue rose **+2.84%**. Transactions rose **+3.03%**, Basket Size fell
> **-4.17%** and Price rose **+4.17%** — thinner baskets, higher prices. Growth came
> from more transactions and higher prices, while units fell **-1.27%**, so we sold less
> despite taking more.

**If the levers do not reconcile to the revenue change** (BR-09), report that as a data
problem and stop. Do not present a narrative built on numbers that do not add up.

### Use the same logic at every level

The report has a **category-level deep dive** showing these levers for each category.
**The same three-lever logic applies at every level**: overall business, branch,
department, section, and category. Use it everywhere, not just in the deep dive.

When a total moves, work down: which branches moved, then which departments, then which
categories — and at each level say whether it was Transactions, Basket Size, or Price.

---

# Section D — Which branches to count

Getting the branch list wrong makes the maths perfect and the answer still wrong.

## BR-01 — Which branches count for like-for-like **[B]**

> **For any comparison against last year, use only CFH014, CFH017, CFH018 and CFH021.**

Like-for-like means comparing the same branches in both years. Use only these four for
every last-year total, percentage, share and ranking. Never use a total that includes a
new branch as the base for a like-for-like figure.

**Why:** growth only means something if the same shops were trading in both years.

## BR-02 — Leave CFH022 out of like-for-like **[B][V]**

> **CFH022 is a new branch with no last-year trading at all. It must never appear in any
> like-for-like comparison.**

Leave it out of every like-for-like total, growth percentage, ranking, share and
concentration figure — in queries, in investigations, and in the words of the report.

**We checked this:** CFH022 shows exactly zero revenue and zero transactions for last
year in every month.

**Why it matters so much:**

| Measure | With CFH022 (wrong) | Without CFH022 (right) | Difference |
|---|---|---|---|
| Revenue growth | +12.61% | **+2.84%** | **9.76 points too high** |
| Units growth | +9.98% | **-1.27%** | **11.25 points too high** |
| Categories declining | 33.30% | **48.19%** | 14.89 points too low |

Include CFH022 and the business looks like it is growing strongly and selling more
items. Exclude it and **we are actually selling fewer items than last year.**

## BR-03 — But still count CFH022 in total sales **[B]**

> **Do not delete CFH022 from total current revenue. Show what it brought in on its own,
> and call it new-branch revenue — never growth.**

CFH022 brought in **SAR 11.9M**, about **8.7%** of all current revenue. Show that next
to the like-for-like result, clearly labelled as a new branch.

## BR-04 — Filter all four branch tables, not just one **[V]**

> **Four tables hold the branch number. A like-for-like calculation must filter all
> four: `MIS_BASE_FILE_MONTHLY_BRAND_TB`, `CAT_TRANSACTIONS`, `CAT_TABLE` and
> `MIS_DEEP_DIVE2`.**

**This is the easiest mistake to make and the hardest to spot.** Revenue and units sit
on the main table, transactions sit on `CAT_TRANSACTIONS`, and category counts sit on
`CAT_TABLE`. Filter only the main table and revenue growth is right while transaction
growth quietly still includes CFH022 — and nothing in the report shows it.

```dax
EVALUATE
CALCULATETABLE (
    ROW ( "Result", [revenue growth %] ),
    TREATAS ( { "CFH014", "CFH017", "CFH018", "CFH021" }, 'MIS_BASE_FILE_MONTHLY_BRAND_TB'[store_no] ),
    TREATAS ( { "CFH014", "CFH017", "CFH018", "CFH021" }, 'CAT_TRANSACTIONS'[store_no] ),
    TREATAS ( { "CFH014", "CFH017", "CFH018", "CFH021" }, 'CAT_TABLE'[store_no] ),
    TREATAS ( { "CFH014", "CFH017", "CFH018", "CFH021" }, 'MIS_DEEP_DIVE2'[store_no] )
)
```

## BR-05 — No last-year figure means no percentage **[B]**

> **If there is no valid last-year number to compare against, give the change in riyals
> or units and leave the percentage out.**

A percentage worked out from the wrong base is worse than none, because it looks
official.

## BR-06 — Every branch is big enough to matter **[V]**

> **We only have four like-for-like branches. Any one of them can move the group result.
> Always say which branches caused a group-level change.**

One branch is about a quarter of the business.

---

# Section E — The measures and the data behind them

## BR-08 — What each measure means **[B]**

> **Use these meanings exactly. Always call measures by name rather than adding up raw
> columns.**

| Measure | How it is worked out | Good direction | What it tells you |
|---|---|---|---|
| **Revenue** | Money taken, excluding VAT | Up | The headline result |
| **Units** | Items sold | Up | Real demand, with price stripped out |
| **Transactions** | Number of bills | Up | How many customers bought |
| **Price** | Revenue / Units | Depends | Average value of an item |
| **Basket Value** | Revenue / Transactions | Up | Average spend per bill |
| **Basket Size** | Units / Transactions | Up | Items in a bill |

Column names in this model have changed before. Measure names have stayed stable, so
use them.

## BR-09 — How the measures fit together **[V]**

> **On totals, the measures multiply exactly. On growth percentages, multiply the growth
> factors — never add the percentages together.**

**On totals** (levels), these are exact:

```
Revenue = Transactions x Basket Value
Revenue = Units        x Price
Units   = Transactions x Basket Size
```

**On growth**, percentages do **not** add up. To combine two growth rates, turn each
into a factor (+3% becomes 1.03), multiply, then subtract 1.

Worked from our own like-for-like figures — Transactions +3.0250%, Basket Value
-0.1752%:

| Method | Result | Actual revenue growth | Verdict |
|---|---|---|---|
| **Multiply the factors** — 1.030250 x 0.998248 - 1 | **+2.8445%** | +2.8445% | **Exact. Use this.** |
| Add the percentages — 3.0250 + (-0.1752) | +2.8498% | +2.8445% | Wrong by 0.0053 points |

Adding is only a rough approximation, and it drifts further apart the bigger the two
moves are. Always multiply.

**If the totals do not multiply out correctly, report a data problem before saying
anything about business performance.**

## BR-10 — Transactions come from their own tables **[V]**

> **The main revenue table has no transaction count. Transactions live in separate
> tables, at a different level for each one.**

| What you need | Where to get it | Grain | Has last year? |
|---|---|---|---|
| Transactions by **category** | `CAT_TRANSACTIONS[dist_bill_curr]` and `[dist_bill_ly]` | Month x Branch x Category | **Yes** |
| Transactions by **branch**, daily | `rep_dept_wise_perf_eval_rpt[LOC_BILLS]` | Day x Branch | **No — this year only** |
| Transactions by **department**, daily | `rep_dept_wise_perf_eval_rpt[DEP_BILLS]` | Day x Branch x Department | **No — this year only** |
| Transactions by **section**, daily | `rep_dept_wise_perf_eval_rpt[SEC_BILLS]` | Day x Branch x Section | **No — this year only** |

**Only `CAT_TRANSACTIONS` has last-year values.** Any transaction comparison against
last year must come from there. The daily table is this year only, so it can describe a
recent trend but can never produce a year-on-year figure.

In `rep_dept_wise_perf_eval_rpt` there is one row per day, branch, department and
section. `LOC_BILLS` and `DEP_BILLS` repeat on every row underneath them, so a plain
`SUM` counts them many times over. Take the value once per level:

```dax
// Correct: true branch transactions for a period
SUMX ( VALUES ( rep_dept_wise_perf_eval_rpt[TY_DATE] ),
       CALCULATE ( MAX ( rep_dept_wise_perf_eval_rpt[LOC_BILLS] ) ) )
```

## BR-29 — Never add transactions across levels or categories **[V]**

> **Transaction counts cannot be added up. A total for a bigger level must be taken from
> that level's own column, never by adding the smaller ones together.**

One basket holding bread, milk and a shirt is **one** transaction for the branch, but it
is counted in the Grocery department, the Dairy section and three different categories.
Adding those up counts the same shopper several times.

**Checked on one day (15 July 2026):**

| Branch | True branch transactions | Add up departments | Add up sections |
|---|---|---|---|
| CFH014 | **2,842** | 4,739 (**1.7x too high**) | 6,371 (**2.2x too high**) |
| CFH017 | **1,220** | 2,098 (1.7x) | 2,983 (2.4x) |
| CFH018 | **1,951** | 2,803 (1.4x) | 3,558 (1.8x) |
| CFH021 | **2,543** | 4,190 (1.6x) | 5,484 (2.2x) |

So: take branch transactions from `LOC_BILLS`, department transactions from
`DEP_BILLS`, section transactions from `SEC_BILLS`, and category transactions from
`CAT_TRANSACTIONS`. **Each level has its own count. Use it.**

The same applies to Basket Value and Basket Size — work them out **within one level**,
using that level's own transaction count. Never mix a category revenue with a branch
transaction count.

## BR-31 — Transaction counts are category counts, not shopping trips **[V][B]**

> **The transaction figure used in our growth measures is a category-level count added
> across categories. It is about three times higher than the true number of shopping
> trips. Use it for growth percentages, but never present Basket Value as the average
> spend of a shopper.**

**[V]** For January to July, the model's transaction figure and the true branch count
are very different:

| Branch | Model transaction figure | True branch transactions | Ratio |
|---|---|---|---|
| CFH014 | 2,582,050 | 788,477 | **3.3x** |
| CFH017 | 1,313,073 | 348,756 | **3.8x** |
| CFH018 | 1,714,919 | 623,853 | **2.8x** |
| CFH021 | 2,699,298 | 843,121 | **3.2x** |

This makes the level figures misleading, even though the growth percentages are fine
because both years are counted the same way:

| Measure | From the model | True figure |
|---|---|---|
| Basket Value | SAR 15.10 | **SAR 48.17** |
| Basket Size | 2.23 items | **7.12 items** |

**Confirmed by the business on 29 July 2026:** `LOC_BILLS` **is** the count of distinct
shopping trips per branch. So the right-hand column above is the truth, and the model's
Basket Value and Basket Size levels are wrong by roughly three times.

**So:**

- **Growth percentages** built on the model's transaction figure **are safe to report.**
  Both years are counted the same way, so the change is valid.
- **Level figures from the model are not.** Never write "customers spend about SAR 15 a
  visit" or "customers buy about 2 items per visit". The real basket is about
  **SAR 48** and about **7 items**.
- When reporting an actual basket level, use the true branch count from `LOC_BILLS`,
  and say which figure you used.
- Never mix the two. A growth percentage from the model's count and a level from
  `LOC_BILLS` must not appear in the same sentence as though they were the same measure.

---

# Section F — How to read a change

## BR-11 — Never show price without basket size **[B]**

> **Always show Price and Basket Size together, and say which one is driving revenue.**

A rising Price with a falling Basket Size means price is hiding a shrinking basket.
Showing the price rise alone makes that look like good news.

A rising Price is **not automatically good**. It is good if customers chose better
products. It is bad if we simply put prices up and people bought less. **The numbers
alone cannot tell you which** — you need a category breakdown. Say which one the
evidence supports, or say honestly that both are still possible.

## BR-12 — "Price effect" is not only price **[B]**

> **When a revenue change is split into a units part and a price part, the price part
> also covers what was sold, not just what it cost. Never call it a price rise.**

Call it the change in average value per item, and say it may reflect a different mix of
products as much as a change in prices.

## BR-13 — Say what is driving growth and whether it will last **[B]**

> **Say which of the three levers moved, and say how safe that is.**

Growth resting on one lever is more fragile than the headline suggests. Say so **even
when the headline looks good.**

## BR-14 — Read the two category measures together **[B]**

> **Never report how many categories are declining without also reporting whether those
> categories are a growing or shrinking part of revenue.**

Half the categories declining sounds alarming, but if those categories are a shrinking
share of revenue, the picture is better than it looks. You need both.

## BR-15 — Ramadan and Eid move between months **[B]**

> **When every branch moves sharply the same way in the same month, assume Ramadan or
> Eid moved between months. Check that first, before saying trade was good or bad.**

Ramadan and Eid follow the Islamic calendar and fall about 11 days earlier each year, so
trade shifts between months from one year to the next. A month can drop heavily against
last year purely because Ramadan moved out of it, with nothing wrong in the shops.

Four branches all falling by a similar amount in the same month is far more likely to be
the calendar than four branches independently having a bad month.

---

# Section G — Dates and periods

## BR-16 — We only have monthly revenue, not daily **[V]**

> **Revenue and units are held by month (1 to 12). There is no daily revenue data.**

Do not offer daily, weekly or day-of-week analysis of revenue or units. Daily data
exists for transactions only (BR-10).

## BR-17 — The daily table cannot do last-year comparisons **[V]**

> **`rep_dept_wise_perf_eval_rpt` holds this year's transactions only. Never use it for
> anything compared to last year.**

It has no last-year rows and no revenue or units. Its last few dates also carry empty
rows beyond the point where real data stops, so always ignore dates after the latest
date that actually has values.

## BR-18 — The last month is short, but both years match **[V][B]**

> **The current period runs to date, so the final month is part of a month. The
> last-year column covers the same part-month, so the comparison is fair.**

Confirmed by the business on 29 July 2026. Still say what the figures cover, but there
is no need to warn that the comparison is misaligned — it is not.

## BR-19 — Last year is a column, not a date calculation **[V]**

> **This model stores last year's figures as ordinary columns on the same row. Do not
> use `SAMEPERIODLASTYEAR`, `DATEADD` or `PARALLELPERIOD`.**

Each row already holds both years, so no date filtering is needed to compare them.

## BR-30 — Reports must focus on the most recent period **[B]**

> **Both the summary and the insight report are about what is happening now. Lead with
> the latest complete month, not the whole year to date.**

How to choose the period:

1. **Normally** — use the **latest complete month**, and compare it with the same month
   last year.
2. **If the current month has enough data** (about a week or more of trading), you may
   lead with the current month so far, but say clearly that it is a part-month.
3. **Early in a month** (fewer than about seven days of trading), do **not** lead with
   it. There is too little data to mean anything. Use the last complete month instead
   and say why.

Always give the year-to-date position as background, but the headline belongs to the
recent trend. A report that only gives seven months of totals hides what changed last
month.

### In the insight report

The same focus applies, with one important qualification: **findings are ranked by how
big they are, not by how recent they are.** Do not drop or demote a large finding for
being older. Recency is context you must add, not a filter.

For every finding, say **when** it happened:

- Name the months the movement sits in. "Down SAR 559K, with most of it in May and
  June" beats "down SAR 559K".
- Say whether it is **still happening** in the latest complete month, or whether it has
  stopped. A decline that ended in March is a very different matter from one still
  running in July.
- When a year-to-date figure is driven by one or two months, say so. A whole-period
  total that hides a single bad month is misleading.
- Where a finding is confined to older months and the recent trend has reversed, state
  the reversal in the same finding rather than leaving the reader with the stale
  direction.

Lead the report with what is happening now. A finding that is both large and current
outranks one that is merely large.

---

# Section H — How to write it

## BR-27 — Put a number on every comparison **[B]**

> **Every comparison must carry a figure. Never write "much less", "slightly", "broadly"
> or "significantly" on their own.**

If you say something moved, say by how much. If you compare two things, give both
numbers.

**Not acceptable** (taken from a real report):

> "revenue fell much less than units while transactions slipped only slightly"

**Acceptable:**

> "Revenue fell SAR 559K, units fell 43.3K and transactions fell 33.3K."

The reader can then see the size of each move. Words like "much less" leave them
guessing.

Other rules for the writing:

- **Short sentences.** One idea each. A branch manager should understand it first time.
- **Be brief.** Say it once. Do not restate the same movement in three ways.
- **Lead with the number**, then the explanation.
- **Round sensibly.** SAR 559K, not SAR 558,877.87, in the main text. Keep the exact
  figure for the evidence section.
- **No jargon.** Never write volume effect, rate effect, share of total change,
  materiality, reconciliation, z-score, probe, signal or trail in the main findings.
- Use the approved names from BR-26, every time.

## BR-23 — The red / amber / green bands **[B]**

> **Use these bands. Units and Basket Size are deliberately the toughest — standing
> still is already red.**

| Measure | Good direction | Red | Amber | Green |
|---|---|---|---|---|
| Revenue growth | Up | below -3% | -3% to 0% | 0% or better |
| Units growth | Up | **below 0%** | 0% to 2% | 2% or better |
| Transactions growth | Up | below -3% | -3% to 0% | 0% or better |
| Price growth | Up | below -3% | -3% to 0% | 0% or better |
| Basket Value growth | Up | below -3% | -3% to 0% | 0% or better |
| Basket Size growth | Up | **below 0%** | 0% to 2% | 2% or better |
| Categories declining | **Down** | above 55% | 40% to 55% | below 40% |
| At-risk revenue share change | **Down** | above +3 points | -3 to +3 points | -3 points or better |

**Why Units and Basket Size are toughest:** units show real demand with price stripped
out, and Basket Size shows whether the range is working. The others can all move on
price alone.

**Always work these out on the four like-for-like branches** (BR-01).

## BR-24 — Only report things big enough to matter **[B]**

> **A finding must be worth a manager's time. An odd-looking change on a tiny part of
> the business is not a finding.**

Judge both how big the change is and how much of the business it covers.

## BR-25 — Say what the numbers actually cover **[B]**

> **Always say which period and which branches a figure covers.**

If a query failed, say so and carry on with what you have. If the evidence is
incomplete, keep it marked as needing checking rather than presenting it as settled.

---

# Section I — Working with this model

## BR-20 — Never use `KEEPFILTERS` **[V]**

> **`KEEPFILTERS('Table'[Col] = "value")` fails on this model. Use
> `FILTER(SUMMARIZECOLUMNS(...), ...)` or `TREATAS` instead.**

It errors with "a single value for column cannot be determined". For several values at
once, use a proper multi-value `TREATAS`.

## BR-21 — Run one measure per query **[V]**

> **Do not put several measures into a single `EVALUATE ROW(...)`.**

If one measure fails, the whole query fails and you lose every other result with it.

## BR-22 — Use the model's own category measures **[V]**

> **For counting categories and working out at-risk revenue, call the model's existing
> measures rather than rebuilding the logic from raw columns.**

`CATEGORY_NAME` does not exist in the published model; `special_product_group_name` is
used instead. Rebuilding the logic would mean guessing.

---

# Section J — Still to confirm

| # | Question | Affects |
|---|---|---|
| 1 | Is the price-versus-basket split caused by price rises or by a change in what sells? | BR-11 — needs a category breakdown |

Answered and closed: VAT is excluded (BR-00), the reporting year is the calendar year
(BR-00), the part-month comparison is aligned across both years (BR-18), and
`LOC_BILLS` is the true count of shopping trips (BR-31).

---

# What we have checked, and when

| Date | What we checked | Result |
|---|---|---|
| 2026-07-28 | The four like-for-like branches, and CFH022's zero last year | BR-01, BR-02 confirmed |
| 2026-07-28 | All eight measures, with and without CFH022 | BR-02 table; error is 9.76 points on revenue |
| 2026-07-28 | Which tables hold the branch number | BR-04 confirmed |
| 2026-07-28 | Every table, column and measure in the model | BR-10, BR-16, BR-17, BR-19, BR-22 confirmed |
| 2026-07-29 | Whether growth percentages add or multiply | **BR-09 corrected** — they multiply; adding was wrong |
| 2026-07-29 | The three-lever chain against real figures | BR-28 confirmed exact |
| 2026-07-29 | Department and section transactions against branch totals (15 July) | BR-29 confirmed — adding overstates by 1.4x to 2.4x |
| 2026-07-29 | Model transaction figure against true branch transactions | BR-31 confirmed — model figure is about 3x higher |
| 2026-07-29 | Which AI steps load this file | Confirmed: all of them, including both summary generators |

---

# Change log

| Date | What changed |
|---|---|
| 2026-07-29 | Incorporated the 3-lever revenue matrix rulebook into **BR-28** and completed it: the source listed 17 of the 27 possible states, so the 10 unmapped ones were added (an unmapped state is exactly the hallucination risk the source warns about). Added a Revenue verdict to every row — 7 states are certainly up, 7 certainly down, 1 flat, and 12 must be computed. Narrative names were reworded to obey BR-26 (no "footfall", "traffic" or "visits"). Added **BR-32**, the four-step procedure for explaining any revenue change, including naming the dominant driver. |
| 2026-07-29 | Expanded **BR-28** with all eight lever combinations and their Units, Basket Value and Revenue outcomes, plus why Basket Value is a result of two levers rather than a lever of its own. Extended **BR-30** to the insight report: recency is required context on every finding, but never a reason to demote a large one. Confirmed **BR-31** — `LOC_BILLS` is the true shopping-trip count, so the model's Basket Value and Basket Size *levels* are wrong by about three times while its growth percentages remain valid. |
| 2026-07-29 | **Corrected BR-09** — growth rates multiply, they do not add; the old table mixed the two methods. Added BR-26 (standard names), BR-27 (put a number on every comparison), BR-28 (the five levers, with worked patterns), BR-29 (transactions cannot be added up), BR-30 (summary focuses on the recent period), BR-31 (transaction counts are category counts). Confirmed VAT is excluded, the calendar year is normal, and the part-month comparison is aligned. **Withdrew BR-07** (CFH022 cut-off is a data fault being fixed). |
| 2026-07-28 | Added BR-00 (Saudi Arabia). Rewrote BR-15 around Ramadan and Eid. Plainer language throughout. |
| 2026-07-28 | Split into sections with fixed rule numbers and check marks. |
| Earlier | Like-for-like rules and the branch list. |
