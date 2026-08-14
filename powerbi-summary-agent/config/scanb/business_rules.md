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

Full background: this file. Every figure in it was verified by live query against the model on the date shown in the check log.

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
| BR-00 | One currency, unnamed, and figures as the model holds them | **[B]** |
| BR-26 | Always use the same word for the same thing | **[B]** |
| BR-28 | The three levers, and all 27 states they can be in | **[B][V]** |
| BR-32 | How to explain any revenue change | **[B]** |
| BR-01 | Which branches count for like-for-like | **[B]** |
| BR-02 | No branch is currently excluded | **[B][V]** |
| BR-03 | A new branch is shown, never counted as growth | **[B]** |
| BR-04 | Four tables hold the branch code, and they are not joined on it | **[V]** |
| BR-05 | No last-year figure means no percentage | **[B]** |
| BR-06 | Every branch is big enough to matter | **[V]** |
| ~~BR-07~~ | ~~retired~~ — see note | — |
| BR-08 | What each measure means | **[B]** |
| BR-09 | How the measures fit together | **[V]** |
| BR-10 | Transactions come from one table, at category level only | **[V]** |
| BR-29 | Transaction counts cannot be added up, and here there is nothing else to use | **[V]** |
| BR-31 | Transaction counts are category counts, and the true figure is unknown | **[V][B]** |
| BR-33 | About 8% of revenue has no department, section or category | **[V]** |
| BR-34 | Branch-level transaction counts are not reliable | **[V]** |
| BR-11 | Never show price without basket size | **[B]** |
| BR-12 | "Price effect" is not only price | **[B]** |
| BR-13 | Say what is driving growth and whether it will last | **[B]** |
| BR-14 | Read the two category measures together | **[B]** |
| BR-15 | When every branch moves the same way, suspect the calendar | **[B]** |
| BR-16 | Everything is monthly. There is no daily data at all | **[V]** |
| BR-17 | Both years are complete, and the data stops at 2023-12-31 | **[V]** |
| BR-18 | A full year against a full year | **[V][B]** |
| BR-19 | Last year is a column, not a date calculation | **[V]** |
| BR-30 | Reports must focus on the most recent period | **[B]** |
| BR-27 | Put a number on every comparison | **[B]** |
| BR-23 | The red / amber / green bands | **[B]** |
| BR-24 | Only report things big enough to matter | **[B]** |
| BR-25 | Say what the numbers actually cover | **[B]** |
| BR-20 | Never use `KEEPFILTERS` | **[V]** |
| BR-21 | Run one measure per query | **[V]** |
| BR-22 | Use the model's own measures, not raw columns | **[V]** |

> **BR-07 is retired.** It covered a data-loading fault that does not apply to this model.
> The number is retired and will not be reused.

---

# Section A — How we report

## BR-00 — One currency, unnamed, and figures as the model holds them **[B]**

> **Write money as a plain number with no currency code or symbol. Do not name a
> country, a market or a tax rate.**

| Thing | What it is here |
|---|---|
| Market | Not stated. Never name a country, city or region |
| Currency | **One currency, unnamed.** Write `104.97M`, never a currency code |
| Tax | **Do not mention tax.** Report the sale values the model holds, unadjusted |
| Reporting year | **The normal calendar year.** January is month 1 |
| Trading calendar | Not stated. See BR-15 for how to handle a calendar shift |

Sale values are taken from the model exactly as stored. Never add, remove or describe
a tax component, and never describe a figure as including or excluding tax — we do not
know which it is.

Because the currency is unnamed, a money figure must always carry its measure name so
the reader knows what it counts: "Revenue 104.97M", not "104.97M".
## BR-26 — Always use the same word for the same thing **[B]**

> **Use the approved name for every measure, every time. Never switch between two names
> for the same thing inside a report.**

| Approved name | What it means | Never call it |
|---|---|---|
| **Revenue** | Money taken, as the model holds it | Sales value, turnover, net sale value, GMV |
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
basket, 10 per item — 5,000 revenue.

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

## BR-01 — Which branches count for like-for-like **[B][V]**

> **Three branches trade in this model — ST1, ST3 and ST4 — and all three have last-year
> figures. Every one of them counts for like-for-like.**

Like-for-like means comparing the same branches in both years. All three qualify, so
**like-for-like equals the total.** There is no branch to leave out.

**We checked this (2026-08-04):** each branch returns a non-zero current *and* prior
revenue and unit figure.

| Branch | Current revenue | Share of revenue | Revenue vs last year |
|---|---|---|---|
| ST1 | 69.00M | **65.7%** | **-6.27%** |
| ST3 | 20.10M | 19.2% | **-8.65%** |
| ST4 | 15.87M | 15.1% | **+13.51%** |

**There is no `ST2`.** Confirmed by the business on 2026-08-04: the branch does not
exist. Do not refer to one, and do not treat the gap in the numbering as a missing or
closed branch.
## BR-02 — No branch is currently excluded **[B][V]**

> **Nothing is excluded from like-for-like today. If a branch ever appears with no
> last-year trading, it must be excluded from every like-for-like figure.**

The rule is kept because the situation can change. What it means today:

- Do not apply a branch filter to make a figure "like-for-like" — the unfiltered total
  already is one.
- Do not describe any figure as excluding a new branch. Nothing is being excluded.

**If a new branch does appear** (a branch with current revenue and zero prior revenue),
leave it out of every like-for-like total, growth percentage, ranking, share and
concentration figure — in queries, in investigations, and in the words of the report —
and report it separately under BR-03.

**We checked this (2026-08-04):** all three branches return a non-zero prior-year
revenue, so no exclusion applies.
## BR-03 — A new branch is shown, never counted as growth **[B]**

> **If a branch has no last-year trading, show what it brought in on its own and call it
> new-branch revenue — never growth.**

Nothing meets this description today (BR-02). The rule stands for when one does: show
the new branch's revenue next to the like-for-like result, clearly labelled as a new
branch, and keep it out of every percentage.
## BR-04 — Four tables hold the branch code, and they are not joined on it **[V]**

> **`MIS_DEEP_DIVE2`, `CAT_TRANSACTIONS`, `CAT_TABLE` and
> `MIS_BASE_FILE_MONTHLY_BRAND_TB` each carry `LOC_CODE`. The model has no
> relationship on `LOC_CODE` — the tables join on `KEY` only. A branch filter must be
> applied to every table it needs to affect.**

**This is the easiest mistake to make and the hardest to spot.** Revenue and units sit
on `MIS_DEEP_DIVE2`; transactions sit on `CAT_TRANSACTIONS`. Filter one and the other is
unaffected, so a "like-for-like" revenue figure can sit beside a transaction figure that
covers something else entirely — and nothing in the report shows it.

```dax
EVALUATE
CALCULATETABLE (
    ROW ( "Result", [revenue growth %] ),
    TREATAS ( { "ST1", "ST3", "ST4" }, 'MIS_DEEP_DIVE2'[LOC_CODE] ),
    TREATAS ( { "ST1", "ST3", "ST4" }, 'CAT_TRANSACTIONS'[LOC_CODE] ),
    TREATAS ( { "ST1", "ST3", "ST4" }, 'CAT_TABLE'[LOC_CODE] ),
    TREATAS ( { "ST1", "ST3", "ST4" }, 'MIS_BASE_FILE_MONTHLY_BRAND_TB'[LOC_CODE] )
)
```

Today all three branches are in scope (BR-02), so no branch filter is needed at all.
The rule matters the moment one is.

**See BR-34** for the consequence that cannot be filtered away: branch-level transaction
counts differ depending on which table you slice by.
## BR-05 — No last-year figure means no percentage **[B]**

> **If there is no valid last-year number to compare against, give the change in money terms
> or units and leave the percentage out.**

A percentage worked out from the wrong base is worse than none, because it looks
official.

## BR-06 — Every branch is big enough to matter **[V]**

> **We only have three like-for-like branches. Any one of them can move the group result.
> Always say which branches caused a group-level change.**

One branch is two thirds of the business (ST1, 65.7%).

---

# Section E — The measures and the data behind them

## BR-08 — What each measure means **[B]**

> **Use these meanings exactly. Always call measures by name rather than adding up raw
> columns.**

| Measure | How it is worked out | Good direction | What it tells you |
|---|---|---|---|
| **Revenue** | Money taken, as the model holds it (BR-00) | Up | The headline result |
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

## BR-10 — Transactions come from one table, at category level only **[V]**

> **The revenue table holds no transaction count. Every transaction figure in this model
> comes from `CAT_TRANSACTIONS`, whose grain is Month x Branch x Category. There is no
> other transaction source and no daily data of any kind.**

| What you need | Where to get it | Grain | Has last year? |
|---|---|---|---|
| Transactions | `CAT_TRANSACTIONS[CURRENT_YR_BILLS]` and `[PAST_YR_BILLS]` | Month x Branch x Category | **Yes** |

The model's measures are built on it:

```dax
[net bills CURRENT] = SUM ( CAT_TRANSACTIONS[CURRENT_YR_BILLS] )
[bills growth]      = SUM ( CAT_TRANSACTIONS[CURRENT_YR_BILLS] )
                    - SUM ( CAT_TRANSACTIONS[PAST_YR_BILLS] )
```

There is **no `net bills PAST` measure.** Get last year's transactions by subtracting:
`[net bills CURRENT] - [bills growth]`.

**What this rules out completely:**

- **No daily analysis of anything.** Revenue, units and transactions are all monthly
  (`DOC_MONTH`, 1 to 12). Never offer daily, weekly or day-of-week analysis.
- **No independent count at branch, department or section level.** Those levels do not
  have their own transaction column, so a figure for them can only ever be the category
  count rolled up — which double-counts baskets. See BR-29.

**We checked this (2026-08-04):** `CAT_TRANSACTIONS` has exactly the columns `KEY`,
`LOC_CODE`, `DOC_MONTH`, `CATEGORY_NAME`, `CURRENT_YR_BILLS`, `PAST_YR_BILLS`. No table
in the model holds a daily figure or a branch-level bill count.
## BR-29 — Transaction counts cannot be added up, and here there is nothing else to use **[V]**

> **One basket is counted once in every category it touches. Adding categories together
> counts the same shopper several times. This model has no independent count at any level
> above category, so every department, section and branch transaction figure it can
> produce is inflated.**

A basket holding bread, milk and a shirt is **one** shopping trip, but it appears in
three categories. `CAT_TRANSACTIONS` counts it three times.

Some retail models carry separate branch, department and section bill counts to fall
back on. **This model does not.** So:

- Transaction, Basket Value and Basket Size **growth percentages** are safe at any level:
  both years are counted the same way, so the change is valid.
- Transaction, Basket Value and Basket Size **levels** are not safe at any level above
  category. See BR-31 for what may and may not be written.
- **Never state a shopper-level fact.** Not "customers buy 1.2 items a visit", not
  "the average basket is 2.58". Those are artefacts of the counting method.

**We checked this (2026-08-04):** the model's implied Basket Size is **1.21 items per
bill** and Basket Value **2.58**. A basket of barely more than one item is not a shopping
trip; it is a category line. That is the inflation showing.
## BR-31 — Transaction counts are category counts, and the true figure is unknown **[V][B]**

> **The transaction figure is a category-level count added across categories, so it is
> several times higher than the number of shopping trips, and there is no true count
> anywhere in this model to compare it against. Use it for growth percentages only,
> and never present a basket level at all.**

**[V] What the model produces (2026-08-04, all three branches, full year):**

| Measure | Model figure | Safe to report? |
|---|---|---|
| Transactions | 40,684,328 | **Growth only** |
| Basket Value | 2.58 | **No — never as a level** |
| Basket Size | 1.21 items | **No — never as a level** |

**Why the levels are unusable:** 1.21 items per bill is below any plausible shopping
trip. The count is category lines, not baskets.

**Why there is no correction available:** correcting it would need a true count of
distinct bills per branch. **This model has no such column** (BR-10), so we cannot say what the true basket is — only that it is
larger than the model implies, by an unknown multiple.

**So:**

- **Growth percentages** built on the transaction figure **are safe to report.** Both
  years are counted identically, so the change is valid.
- **Levels must not appear.** Never write a spend-per-visit or items-per-visit figure,
  and never call the transaction count a number of customers, shoppers or visits. Call it
  what it is: **transactions**, or **category lines**.
- If asked for the real basket, say the model cannot support it and what would be needed:
  a branch-level distinct bill count.

## BR-33 — About 8% of revenue has no department, section or category **[V]**

> **Rows exist with a blank `DEPARTMENT`, `SECTION` and `CATEGORY_NAME`. They carry
> real revenue and real transactions. Never present them as a named area, and never
> quietly drop them from a total.**

**We checked this (2026-08-04):**

| What is unassigned | Amount | Share |
|---|---|---|
| Revenue | 7.97M | **7.6% of revenue** |
| Transactions | 4,285,689 | **10.5% of transactions** |
| Units | 9.15M | 18.7% of units |

The unassigned rows appear across **all three branches** and have a blank
`CATEGORY_NAME` as well, so they cannot be attributed to any level of the merchandise
hierarchy.

**How to handle them:**

- **Branch and company totals are correct** and include them. The three branch revenues
  add exactly to the company total, so no branch figure is missing anything.
- **A department, section or category breakdown does not add to the company total.** It
  is short by the unassigned amount. Say so rather than presenting the breakdown as
  complete.
- **Never print a blank area name.** If an unassigned bucket has to be shown, label it
  **"Unassigned"** and say what it is: revenue with no merchandise classification.
- Never call an unassigned bucket the largest or smallest area, and never rank it
  against real areas.

This is a data-loading gap, not a business fact. It is worth fixing at source.

## BR-34 — Branch-level transaction counts are not reliable **[V]**

> **Transactions sliced by the revenue table's `LOC_CODE` and by
> `CAT_TRANSACTIONS[LOC_CODE]` give different answers. Never build a branch-level
> Basket Value, Basket Size or transaction figure.**

The two tables both carry `LOC_CODE` but the model does not join on it (BR-04), so which
column you group by changes the answer.

**We checked this (2026-08-04):**

| Branch | Sliced by `MIS_DEEP_DIVE2[LOC_CODE]` | Sliced by `CAT_TRANSACTIONS[LOC_CODE]` | Gap |
|---|---|---|---|
| ST1 | 22,808,961 | **25,537,427** | 2.73M |
| ST3 | 7,701,935 | **8,598,117** | 0.90M |
| ST4 | 5,887,743 | **6,548,784** | 0.66M |
| *(blank)* | 4,285,689 | — | — |

Both add to the same company total (40,684,328). The difference is that slicing by the
revenue table pushes 4.29M of transactions into a blank branch, because those
`CAT_TRANSACTIONS` rows have no matching `KEY` on the revenue side.

**So:**

- **Company-level** transaction growth is safe.
- **Department, section and category** transaction growth is safe: those levels filter
  correctly and add exactly to the company total (checked).
- **Branch-level** transactions are **not** safe. Do not report branch transaction
  counts, branch Basket Value or branch Basket Size, and do not build a three-lever
  split for a branch. A branch's **revenue and units** are reliable — use those.
- A branch story must be told with revenue and units only, and must say that the
  transaction split is not available at branch level.
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

## BR-15 — When every branch moves the same way, suspect the calendar **[B]**

> **When all branches move sharply the same way in the same month, assume the comparison
> period shifted before assuming trade was good or bad. Check it first.**

Moveable trading events — festivals, promotional seasons, public holidays — do not fall
in the same month every year. A month can drop heavily against last year purely because
a peak trading period moved out of it, with nothing wrong in the shops.

Three branches all falling by a similar amount in the same month is far more likely to
be the calendar than three branches independently having a bad month.

**No trading calendar is configured for this model.** So:

- Report the **pattern** — "all three branches fell together, which usually points at
  the comparison period rather than at trading" — and say the calendar needs checking.
- Do **not** name a festival, season or holiday as the cause. We have no calendar to
  support it.
- Still name the exceptions. A branch that moved much further than the others, or that
  is also weak over the full year, is not explained by a calendar shift and must be
  called out separately.
## BR-16 — Everything is monthly. There is no daily data at all **[V]**

> **Revenue, units and transactions are all held by month (`DOC_MONTH`, 1 to 12). No
> table in this model holds a daily figure.**

Do not offer daily, weekly or day-of-week analysis of anything. Month is the finest
grain available.

`MIS_DEEP_DIVE2[UPDATED_DATE]` is a load stamp, not a trading date. It records when the
row was refreshed. Never treat it as a business activity date, and never build a trend
on it.
## BR-17 — Both years are complete, and the data stops at 2023-12-31 **[V]**

> **All twelve months are present for both the current and prior year, so the comparison
> is a full year against a full year. The latest data is 2023-12-31.**

**We checked this (2026-08-04):** months 1 to 12 each return a non-zero current and prior
revenue, and `MAX(MIS_DEEP_DIVE2[UPDATED_DATE])` is 2023-12-31.

Two consequences:

- **No part-month caveat is needed.** Unlike a to-date model, nothing here is a partial
  period.
- **The data is not current.** Say what period the figures cover. Never imply the report
  describes recent trading, and never write "this month" or "currently" about a figure
  from a closed year.
## BR-18 — A full year against a full year **[V][B]**

> **The current period is a complete calendar year and the prior column covers the
> matching complete year, so the comparison is aligned.**

There is no partial period on either side, so no alignment warning is needed. Still say
which year the figures cover (BR-17).
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

- Name the months the movement sits in. "Down 559K, with most of it in May and
  June" beats "down 559K".
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

> "Revenue fell 559K, units fell 43.3K and transactions fell 33.3K."

The reader can then see the size of each move. Words like "much less" leave them
guessing.

Other rules for the writing:

- **Short sentences.** One idea each. A branch manager should understand it first time.
- **Be brief.** Say it once. Do not restate the same movement in three ways.
- **Lead with the number**, then the explanation.
- **Round sensibly.** 559K, not 558,877.87, in the main text. Keep the exact
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

**All three branches are in scope** (BR-01), so these apply to the total.

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

## BR-22 — Use the model's own measures, not raw columns **[V]**

> **Call the model's existing measures rather than rebuilding their logic from raw
> columns.**

`CATEGORY_NAME` **does** exist in this model, on `MIS_DEEP_DIVE2`, `CAT_TABLE`,
`CAT_TRANSACTIONS` and `MIS_BASE_FILE_MONTHLY_BRAND_TB`, so category work can group on
it directly. Even so, take the *values* from the named measures — `net revenue CURRENT`,
`net qty CURRENT`, `net bills CURRENT`, `bills growth` and their prior counterparts —
because the measure definitions are the agreed logic and the column names have changed
before.

`MIS_BASE_FILE_MONTHLY_BRAND_TB` additionally carries `BRAND_NAME`, `SUPPLIER_NAME` and
values two and three years back. Those are available for a deeper cut, but nothing in
these rules depends on them, and no rule has been checked against them.

---

# Section J — Still to confirm

| # | Question | Affects |
|---|---|---|
| 1 | What is the true number of shopping trips? No column in the model holds one | BR-31 — no basket level can be stated until this exists |
| 2 | Why do 7.6% of revenue rows have no department, section or category? | BR-33 — a loading gap to fix at source |
| 3 | Why do 4.29M transactions have no matching `KEY` on the revenue table? | BR-34 — blocks all branch-level basket measures |
| 4 | Is there a trading calendar (festivals, seasons) for this market? | BR-15 — without it a calendar shift can be flagged but never named |

Answered and closed: the reporting year is the calendar year (BR-00), all three branches
are like-for-like and there is no `ST2` (BR-01), both years are complete (BR-17), and
transactions exist only at category level (BR-10).

---

# What we have checked, and when

| Date | What we checked | Result |
|---|---|---|
| 2026-08-04 | Every table, column, measure and relationship in the model | BR-04, BR-10, BR-16, BR-19, BR-22 confirmed |
| 2026-08-04 | Per-branch current and prior revenue and units | BR-01 confirmed — three branches, all with both years |
| 2026-08-04 | Whether any branch has zero prior-year revenue | BR-02 confirmed — none does, so nothing is excluded |
| 2026-08-04 | The three-lever chain against real figures | BR-28 confirmed exact: -2.04% x +4.11% x -6.10% multiplies to -4.2269%, the actual revenue change |
| 2026-08-04 | Transactions by department, against the company total | BR-29 confirmed — department slices add exactly to 40,684,328 |
| 2026-08-04 | Transactions sliced by each table's `LOC_CODE` | **BR-34 added** — branch figures differ by 0.66M to 2.73M between tables |
| 2026-08-04 | Rows with a blank `DEPARTMENT` | **BR-33 added** — 7.97M revenue, 10.5% of transactions, unassigned |
| 2026-08-04 | Month coverage and the data watermark | BR-17 confirmed — 12 months both years, latest 2023-12-31 |
| 2026-08-04 | Whether `ST2` exists | Business confirmed it does not — BR-01 closed |
| 2026-08-04 | The implied Basket Size and Basket Value levels | BR-31 confirmed — 1.21 items per bill, so levels are unusable |

---

# Change log

| Date | What changed |
|---|---|
| 2026-08-04 | Created for this model from our standard retail rulebook, then verified against this model by live query. **Rewritten:** BR-00 (currency unnamed, no market or tax named), BR-01/02/03 (three branches, all like-for-like, nothing excluded), BR-04 (four tables carry `LOC_CODE` and are not joined on it), BR-10 (transactions exist only in `CAT_TRANSACTIONS`, at category level, no daily data anywhere), BR-29 and BR-31 (no independent count at any level, so no basket level may be stated at all — there is no true count to correct against), BR-15 (calendar discipline kept, festival names removed, no calendar configured), BR-16/17/18 (monthly only; both years complete; data stops 2023-12-31), BR-22 (`CATEGORY_NAME` exists here). **Added:** BR-33 (7.6% of revenue unassigned to any merchandise level) and BR-34 (branch-level transaction counts unreliable, so no branch three-lever split). **Kept unchanged:** BR-26, BR-28, BR-32, BR-05, BR-06, BR-08, BR-09, BR-11, BR-12, BR-13, BR-14, BR-19, BR-20, BR-21, BR-23, BR-24, BR-25, BR-27, BR-30. |
