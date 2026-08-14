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

The full detail behind these rules lives in
`docs/business-repository/reports/R01-retail-brand-mis.md`.

---

## How to check this file

Every rule has a number, like `BR-01`. The numbers never change meaning, so you can say
"BR-04 is wrong" and everyone knows what you mean.

**To review this file quickly: read only the bold sentence under each number.** That
sentence is the rule. Everything after it explains why. If a bold sentence is wrong,
the rule is wrong — tell us the number.

Each rule is marked:

| Mark | What it means |
|---|---|
| **[V]** Checked | We ran a query against the live data and confirmed it. |
| **[B]** Business decision | The business told us this. It is true because we decided it. |
| **[A]** Assumption | Our best guess. **We need someone to confirm it.** |

### All rules at a glance

| Number | Rule | Mark |
|---|---|---|
| BR-00 | Where we trade and what that means | **[B]** |
| BR-01 | Which branches count for like-for-like | **[B]** |
| BR-02 | Leave CFH022 out of like-for-like | **[B][V]** |
| BR-03 | But still count CFH022 in total sales | **[B]** |
| BR-04 | Filter all four branch tables, not just one | **[V]** |
| BR-05 | No last-year figure means no percentage | **[B]** |
| BR-06 | Every branch is big enough to matter | **[V]** |
| BR-07 | CFH022's data stops earlier than the rest | **[V]** |
| BR-08 | What each measure means | **[B]** |
| BR-09 | The three sums that must always agree | **[V]** |
| BR-10 | Footfall means bills, and sits on its own table | **[V][A]** |
| BR-11 | Never show price per item without items per basket | **[B]** |
| BR-12 | "Price effect" is not only price | **[B]** |
| BR-13 | Say what is driving growth and whether it will last | **[B]** |
| BR-14 | Read the two category measures together | **[B]** |
| BR-15 | Ramadan and Eid move between months | **[B]** |
| BR-16 | We only have monthly sales, not daily | **[V]** |
| BR-17 | The daily table cannot do last-year comparisons | **[V]** |
| BR-18 | The last month is not finished | **[V]** |
| BR-19 | Last year is a column, not a date calculation | **[V]** |
| BR-20 | Never use `KEEPFILTERS` | **[V]** |
| BR-21 | Run one measure per query | **[V]** |
| BR-22 | Use the model's own category measures | **[V]** |
| BR-23 | The red / amber / green bands | **[B]** |
| BR-24 | Only report things big enough to matter | **[B]** |
| BR-25 | Say what the numbers actually cover | **[B]** |

---

# Section A — Where we trade

## BR-00 — Saudi Arabia **[B]**

> **This is a Saudi Arabian retail chain. Use the Saudi calendar, working week, and
> currency. Do not assume Western or Indian norms.**

| Thing | What it is here |
|---|---|
| Country | Saudi Arabia |
| Currency | Saudi Riyal (SAR) |
| Time zone | Asia/Riyadh (UTC+3, no daylight saving) |
| Weekend | **Friday and Saturday** |
| Working week | **Sunday to Thursday** |
| Big trading periods | **Ramadan and Eid al-Fitr**, then Eid al-Adha |
| Fixed national days | Founding Day (22 February), National Day (23 September) |

**Why this matters for the numbers:**

- **Ramadan and Eid move.** They follow the Islamic calendar, which is about 11 days
  shorter than the normal year. So they fall roughly 11 days earlier each year. A
  month can look much better or worse than last year purely because Ramadan moved into
  or out of it. See BR-15 — this is the single most common reason a month looks odd.
- **The weekend is Friday and Saturday**, not Saturday and Sunday. Any day-of-week
  work must use the Saudi week, or it will treat busy days as quiet ones.
- **All money figures are Saudi Riyals.** Never write a currency symbol we have not
  confirmed, and never convert to another currency.

**Still to confirm** (see Section G): whether sales figures are before or after the
15% VAT.

---

# Section B — Which branches to count

This is the most important section. If you get the branch list wrong, the maths will be
perfect and the answer will still be wrong.

## BR-01 — Which branches count for like-for-like **[B]**

> **For any comparison against last year, use only CFH014, CFH017, CFH018 and CFH021.**

"Like-for-like" means comparing the same branches in both years. Use only these four
branches for every last-year total, percentage, share, and ranking. Never use a total
that includes a new branch as the base for a like-for-like figure.

**Why:** growth only means something if the same shops were trading in both years.
Adding a new shop measures opening a shop, not growing the business.

## BR-02 — Leave CFH022 out of like-for-like **[B][V]**

> **CFH022 is a new branch. It has no last-year trading at all, so it must never appear
> in any like-for-like comparison.**

Leave it out of every like-for-like total, growth percentage, ranking, share, and
concentration figure. This applies everywhere: summary queries, insight scans,
investigation queries, repaired queries, and the words in the final report.

**We checked this:** CFH022 shows exactly zero sales and zero bills for last year in
**every single month**. There is nothing to compare it against.

**Here is why it matters so much:**

| Measure | With CFH022 (wrong) | Without CFH022 (right) | Difference |
|---|---|---|---|
| Sales growth | +12.61% | **+2.84%** | **9.76 points too high** |
| Units growth | +9.98% | **-1.27%** | **11.25 points too high** |
| Categories declining | 33.30% | **48.19%** | 14.89 points too low |

With CFH022 included, the business looks like it is growing strongly and selling more
items. Once it is removed, **we are actually selling fewer items than last year**. This
is not a small rounding difference. It changes the answer completely.

## BR-03 — But still count CFH022 in total sales **[B]**

> **Do not delete CFH022 from total current sales. Show what it brought in on its own,
> and call it new-branch sales — never growth.**

Total sales are still total sales. CFH022 brought in **11,906,056**, about **8.7%** of
all current sales. Show that figure next to the like-for-like result, clearly labelled
as a new branch. Never mix it into a growth percentage.

## BR-04 — Filter all four branch tables, not just one **[V]**

> **Four tables hold the branch number. A like-for-like calculation must filter all
> four: `MIS_BASE_FILE_MONTHLY_BRAND_TB`, `CAT_TRANSACTIONS`, `CAT_TABLE` and
> `MIS_DEEP_DIVE2`.**

**This is the easiest mistake to make and the hardest to spot.** Sales and units sit on
the main table, but bills sit on `CAT_TRANSACTIONS` and category counts sit on
`CAT_TABLE`. If you filter only the main table, sales growth is correct while footfall
growth quietly still includes CFH022 — and nothing in the report shows the mismatch.

This pattern works and has been tested:

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

**Why:** a percentage worked out from the wrong base is worse than no percentage,
because it looks official.

## BR-06 — Every branch is big enough to matter **[V]**

> **We only have four like-for-like branches. Any single branch can move the group
> result. Always say which branches caused a group-level change.**

One branch is about a quarter of the business. A group figure with no branch detail
hides what actually happened.

## BR-07 — CFH022's data stops earlier than the rest **[V]**

> **CFH022's data ends on 13 June. Every other branch runs to the latest date. Say this
> whenever you report CFH022's figure.**

Its June sales are **427,159** against a normal month of about **2,100,000**. That is a
part-month of data, not a collapse in trade. Never present CFH022's total as a full
period without saying its data stops early. Whether the data feed broke or the branch
stopped trading is still unanswered (Section G).

---

# Section C — What the measures mean

## BR-08 — What each measure means **[B]**

> **Use these meanings exactly. Always call measures by name rather than adding up raw
> columns.**

| Measure | What it is | Good direction | What it tells you |
|---|---|---|---|
| **Sales (Revenue)** | Money taken | Up | The headline result |
| **Units (Volume)** | Items sold | Up | Real demand, with price stripped out |
| **Footfall** | Number of bills | Up | How many customers bought |
| **ASP** | Sales divided by units | Depends | Average price per item |
| **ATV** | Sales divided by bills | Up | Average spend per visit |
| **UPT** | Units divided by bills | Up | How many items in a basket |

Column names in this model have changed before. Measure names have stayed stable, so
use them.

## BR-09 — The three sums that must always agree **[V]**

> **Sales = Footfall x ATV. Sales = Units x ASP. Units = Footfall x UPT. If these do not
> add up, report a data problem before saying anything about business performance.**

These always hold. They are not estimates.

**We checked them on the four like-for-like branches, and all three agree exactly:**

| Sum | Works out to | Reported | Agrees? |
|---|---|---|---|
| Footfall x ATV | +2.84% | Sales +2.84% | Yes |
| Footfall x UPT | -1.27% | Units -1.27% | Yes |
| Units x ASP | +2.85% | Sales +2.84% | Yes |

So the measures can be trusted. If they ever stop agreeing, that is the first thing to
report.

## BR-10 — Footfall means bills, and sits on its own table **[V][A]**

> **Footfall means the number of bills, from `CAT_TRANSACTIONS`. It is not a count of
> people walking in. Never call it visitors, and never use it to talk about how many
> browsers became buyers.**

**[V]** The main sales table has no bill count at all, so any footfall figure uses two
tables — and both must be filtered the same way (BR-04).

**[A]** We are assuming bills only count people who bought something. If a door counter
exists somewhere, this rule changes. Please confirm.

---

# Section D — How to read a change

Section C says what the numbers are. This section says what you may and may not
conclude from them.

## BR-11 — Never show price per item without items per basket **[B]**

> **Always show ASP and UPT together, and say which one is driving sales.**

If the price per item is rising while items per basket are falling, price is hiding a
shrinking basket. Showing the price rise on its own makes that look like good news.

A rising average price is **not automatically good**. It is good if customers are
choosing better products. It is bad if we simply put prices up and people bought less.
**The numbers alone cannot tell you which.** You need a breakdown by category. Say which
one the evidence supports, or say honestly that both are still possible.

## BR-12 — "Price effect" is not only price **[B]**

> **When a sales change is split into a units part and a price part, the price part also
> includes what was sold, not just what it cost. Never call it a price rise.**

Call it the change in average value per item, and say it may reflect a different mix of
products as much as a change in prices.

## BR-13 — Say what is driving growth and whether it will last **[B]**

> **Say where growth came from — more customers, bigger baskets, or higher prices — and
> say how safe that is.**

If growth rests on one thing only, it is more fragile than the headline suggests. Say so
**even when the headline looks good**. Someone reading a positive number deserves to
know it is standing on one leg.

## BR-14 — Read the two category measures together **[B]**

> **Never report how many categories are declining without also reporting whether those
> categories are a growing or shrinking part of sales.**

One tells you how many categories are struggling. The other tells you whether the
struggling ones matter more or less than last year. Half the categories declining sounds
alarming, but if those categories are a shrinking share of sales, the picture is better
than it looks. You need both.

## BR-15 — Ramadan and Eid move between months **[B]**

> **When every branch moves sharply the same way in the same month, assume it is Ramadan
> or Eid moving between months. Check that first, before saying trade was good or bad.**

Ramadan and Eid follow the Islamic calendar and fall about 11 days earlier each year.
So trade shifts between months from one year to the next. A month can drop heavily
against last year simply because Ramadan has moved out of it, with nothing wrong in the
shops at all.

Four separate branches all falling by a similar amount in the same month is far more
likely to be the calendar than four branches independently having a bad month. Always
check the Ramadan dates for both years before blaming performance.

---

# Section E — Dates and periods

## BR-16 — We only have monthly sales, not daily **[V]**

> **Sales and units are held by month (1 to 12). There is no daily sales data.**

`max_date` tells you the last day with data in that month. Do not offer daily, weekly,
or day-of-week analysis of sales or units — it does not exist. Say so plainly rather
than implying we can go deeper than we can.

## BR-17 — The daily table cannot do last-year comparisons **[V]**

> **`rep_dept_wise_perf_eval_rpt` holds this year's bill counts only. Never use it for
> anything compared to last year.**

Three reasons: it has **no last-year rows**, it holds **bills only** (no sales or
units), and its **last date runs past the point where data actually stops**, so a recent
window taken from it would include days that are empty or not real yet.

## BR-18 — The last month is not finished **[V]**

> **The current period runs to date and its final month is incomplete. Always say what
> the figures actually cover, and never treat a part-month as a full one.**

We do not yet know whether the last-year column covers the same part-month. Until that
is confirmed, treat any comparison involving the final month as provisional.

## BR-19 — Last year is a column, not a date calculation **[V]**

> **This model stores last year's figures as ordinary columns on the same row. Do not
> use `SAMEPERIODLASTYEAR`, `DATEADD` or `PARALLELPERIOD`.**

Each row already holds both years, so no date filtering is needed to compare them.
Filtering to a month filters both years together and keeps them lined up.

---

# Section F — Working with this model

## BR-20 — Never use `KEEPFILTERS` **[V]**

> **`KEEPFILTERS('Table'[Col] = "value")` fails on this model. Use
> `FILTER(SUMMARIZECOLUMNS(...), ...)` or `TREATAS` instead.**

It reliably errors with "a single value for column cannot be determined". When filtering
several values at once, use a proper multi-value `TREATAS`, never one value with commas
inside it.

## BR-21 — Run one measure per query **[V]**

> **Do not put several measures into a single `EVALUATE ROW(...)`.**

If one measure fails, the whole query fails and you lose every other result with it.
There is no partial answer.

## BR-22 — Use the model's own category measures **[V]**

> **For counting categories and working out at-risk sales, call the model's existing
> measures rather than rebuilding the logic from raw columns.**

Category names differ between the desktop file and the published model —
`CATEGORY_NAME` does not exist here, and `special_product_group_name` is used instead.
Rebuilding the logic would mean guessing. The model's own measures already do it
correctly.

---

# Section G — Reporting standards

## BR-23 — The red / amber / green bands **[B]**

> **Use these bands. Units and UPT are deliberately the toughest — standing still is
> already red.**

| Measure | Good direction | Red | Amber | Green |
|---|---|---|---|---|
| Sales growth | Up | below -3% | -3% to 0% | 0% or better |
| Units growth | Up | **below 0%** | 0% to 2% | 2% or better |
| Footfall growth | Up | below -3% | -3% to 0% | 0% or better |
| ASP growth | Up | below -3% | -3% to 0% | 0% or better |
| ATV growth | Up | below -3% | -3% to 0% | 0% or better |
| UPT growth | Up | **below 0%** | 0% to 2% | 2% or better |
| Categories declining | **Down** | above 55% | 40% to 55% | below 40% |
| At-risk sales share change | **Down** | above +3 points | -3 to +3 points | -3 points or better |

**Why units and UPT are toughest:** units tell you real demand with price stripped out,
and UPT tells you whether the range is working. The others can all move on price alone,
so they get a little more room before turning red.

**Always work these out on the four like-for-like branches** (BR-01). A status based on
all five branches is not a valid status.

## BR-24 — Only report things big enough to matter **[B]**

> **A finding must be worth a manager's time. An unusual-looking change on a tiny part
> of the business is not a finding.**

Judge both how big the change is and how much of the business it covers. Put the
biggest, most meaningful ones first.

## BR-25 — Say what the numbers actually cover **[B]**

> **Always say which period and which branches a figure covers. Never present a partial
> or differently-filtered number as if it were the full picture.**

If a query failed, say so and carry on with what you have. If the evidence is
incomplete, keep it marked as needing checking rather than presenting it as settled. A
report that quietly leaves out what it could not work out cannot be trusted.

---

# Section H — Still to confirm

These affect the rules above. Until someone answers, follow the rule as written and put
the caveat in the report.

| # | Question | Affects |
|---|---|---|
| 1 | Are sales figures before or after the 15% VAT? | BR-00, BR-08 |
| 2 | Does the last-year column cover the same part-month as this year? | BR-18, and every current figure |
| 3 | Did CFH022's data feed break, or did the branch stop trading on 13 June? | BR-07, BR-03 |
| 4 | Does footfall count only people who bought, with no door counter anywhere? | BR-10 |
| 5 | Is our reporting year the normal calendar year? | BR-15, BR-16 |
| 6 | Is the price-versus-basket split caused by price rises or by a change in what sells? | BR-11 — needs a category breakdown |

---

# What we have checked, and when

| Date | What we checked | Result |
|---|---|---|
| 2026-07-28 | The four like-for-like branches, and CFH022's zero last year | BR-01 and BR-02 confirmed against live data |
| 2026-07-28 | All eight measures, with and without CFH022 | BR-02 table; the error is 9.76 points on sales, 11.25 on units |
| 2026-07-28 | Which tables hold the branch number, and that the query pattern runs | BR-04 confirmed |
| 2026-07-28 | The three sums, on like-for-like branches | BR-09 all agree exactly |
| 2026-07-28 | Every table, column and measure in the model | BR-10, BR-16, BR-17, BR-19, BR-22 confirmed |
| 2026-07-28 | The latest data date and the refresh time | BR-18 confirmed; data is current, not old |
| 2026-07-28 | CFH022 month by month | BR-07 confirmed |

**Not yet checked against data:** BR-00 and BR-15. The business told us we trade in
Saudi Arabia, and the Ramadan effect follows from that, but we have not yet matched
Ramadan dates against the monthly figures to prove it. That is question 6 above.

---

# Change log

| Date | What changed |
|---|---|
| 2026-07-28 | Added BR-00 (Saudi Arabia: calendar, working week, currency). Rewrote BR-15 around Ramadan and Eid instead of generic calendar effects. Rewrote the whole file in plainer language. |
| 2026-07-28 | Split into sections with fixed rule numbers and check marks. Added BR-04, BR-07, BR-09, BR-10, BR-17 and BR-23. Corrected the date and data-age rules after checking the live model. |
| Earlier | Like-for-like rules and the branch list. |
