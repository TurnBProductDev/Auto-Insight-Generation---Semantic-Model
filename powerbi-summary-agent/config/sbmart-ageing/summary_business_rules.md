# SB Mart Ageing summary rules

## What the report says, and in what order

- Lead with 24+ months, then 12-24 months, then aged and non-moving.
- Always state the snapshot date and USD value.
- Separate total aged exposure from the aged-and-non-moving intersection.
- Mention reconciliation or classification limitations prominently.

## What "aged" means, and why it is not the model's own flag

- **Aged is stock in the 09-12, 12-24 and 24+ month bands**, summed from
  `NEW AGE`. Nine months or more.
- It is **not** `AGE_ABOVE_9`. That column is defective in the source model:
  measured on 23 August 2026 it returns `Y` for the 09-12 and 12-24 bands and
  **`N` for 24+ MONTHS**, so it silently omits the oldest and worst stock. The
  gap was USD 90,714 - aged stock reads USD 751,607 (13.1%) through the flag
  against USD 842,321 (14.7%) through the bands. `AGE_ABOVE_12` does include
  24+, so the flag set is internally inconsistent rather than uniformly
  exclusive.
- The same definition is used on every date, which is what makes two positions
  comparable. If `AGE_ABOVE_9` is corrected in the source model, the two will
  agree and this note can be retired.
- The model's own `[aged stock share]` measure is excluded for a separate
  reason: its numerator does not reconcile to the Stock Value exposure this
  report uses. The report states that exclusion on the page.

## Comparing today against an earlier position

Two histories exist and they answer different questions. They are kept as
separate sections and are never merged, because merging them produces one
comparison whose window silently changes length.

- **The reference position** is the source model's own `REP_SSR_SAG_HIST`. It
  moves only when the source system re-freezes it, so the window is "since
  whenever that was" rather than a fixed number of days. The page states both
  dates and the day count every time.
- **The last reading** is the scan this pipeline kept on its previous run. This
  is the day-on-day lane and the one the trend is built from.

**Value totals may only be compared when the valuation basis is unchanged, and
that is checked from the data rather than assumed.** On the 14-to-23 August 2026
pair the check refused: ST5 held a byte-identical quantity on both dates
(79,838 units) while its stock value moved from 0.78 to 0.21 per unit. Stock
that did not move cannot lose 73% of its worth, so what changed is how VALUE is
worked out. Whenever the check refuses:

- Absolute value movement is **not** published, and the reason is printed in
  plain words on the page.
- **Shares and counts are still published**, because a share compares two
  figures taken from the same table on the same day, so whatever rescaled them
  cancels. Aged share of value, aged share of units, each band's share of the
  mix, and product counts are all safe.
- A finding is only called solid when the money reading and the unit reading
  agree, and the page says so when they do.

Band-to-band movement is counted in **units** for the same reason.

## The clearance outlook

- Estimated from each product's average daily sales quantity over a **30 day**
  window (`ageing_clearance_days`).
- It **assumes each sale takes the oldest stock first**, which the source data
  does not guarantee. Read it as "this division is slow to turn over", never as
  a promise about the next 30 days. The page states this.
- An estimate above 100% is capped for display: a division cannot clear more
  than it holds.
- A division with no recorded sales is reported as **never clearing at the
  current pace**, not as zero days.
- Selling velocity belonging to products that map to no division is **declared
  on the page**, not silently dropped. It was 25% of the total on 23 August
  2026, so the divisions shown may clear slightly faster than stated.

## The category review line

- A category is over the line when more than **30%** of its own stock value is
  aged (`ageing_category_threshold_pct`). This is a review threshold the
  business chose; it can be moved and is not a rule in the source data.
- The **count** treats every carried category equally. Categories holding no
  stock are excluded from both the count and the denominator - an empty
  category cannot fail a threshold.
- The **list** is ordered by money stuck, never by percentage. Sorting on share
  puts a category holding four dollars of entirely-old stock at the top on a
  perfect 100%: a true number and a useless instruction. The page names that
  category and its amount so the ordering explains itself.

## The stuck product lines

- Selected at an ageing risk score of **-70 or worse** (the source model scores
  0 healthy to -100 worst, so lower is worse), holding at least **USD 500**, and
  carrying one of the source's own excess or no-sales statuses.
- Ordered by money at stake, because the score has already done the selecting.
- The table is the top of a much longer list and says so, naming the number of
  lines at the same score across the whole business.
- **A line can sell briskly and still show the worst score**, when one old
  purchase batch is stuck behind newer stock of the same product. The page
  explains this rather than leaving it as a contradiction.

## Two value bases, never blended

`REP_SSR_STOCK_STATUS` carries its own stock value on a **different basis** from
the ageing table: USD 13.03M against USD 5.73M on 23 August 2026. Neither is
wrong; they are different measures of the same shelves.

- The clearance outlook is expressed in **units and days**, which the gap does
  not touch.
- Any money column sourced from the stock-status table is labelled as such, and
  is never added to the headline stock value.
- The page footer states only that values are USD and are the stock value held
  in the source report. It does **not** assert a costing convention, because the
  ageing table's basis was measured moving and no rulebook defines it.
