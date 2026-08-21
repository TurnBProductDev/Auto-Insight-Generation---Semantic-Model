# Business Rules — Inventory Management Report

These are the rules for how numbers must be worked out and written up. The agent follows
them when it builds queries, looks for insights, and writes summaries.

**These rules win.** If a rule here disagrees with the agent's normal way of doing things,
the rule here is what happens.

A copy of this file is saved with every run (`business_rules_IMR_snapshot.md`), so you can
always check which rules produced a given summary.

**Where these rules apply.** Every AI step uses them: report understanding, query planning,
query writing, insight detection, investigation, and the insight summary. The rules shape
the AI output just as much as the raw data does.

---

## How to check this file

Every rule has a number, like `BR-01`. Numbers never change meaning. If a rule is dropped,
its number is retired rather than reused. New rules get new numbers, which is why the
numbers may not be in perfect order inside each section.

**To review this file quickly: read only the bold sentence under each number.** That sentence
is the rule. Everything after it explains why.

| Mark | What it means |
|---|---|
| **[V]** Checked | Confirmed by querying the live data model. |
| **[B]** Business decision | The business told us this. True because we decided it. |
| **[A]** Assumption | Best guess. Someone needs to confirm it. |

### All rules at a glance

| Number | Rule | Mark |
|---|---|---|
| BR-00 | Saudi Arabia, riyals, and the closing-stock snapshot | **[B]** |
| BR-01 | The seven locations and their types | **[B][V]** |
| BR-02 | Division is the top level of the product hierarchy | **[B]** |
| BR-03 | Always use the same word for the same thing | **[B]** |
| BR-04 | Data inclusion criteria | **[B]** |
| BR-05 | The three dashboard views and what each covers | **[B]** |
| BR-06 | SKU segmentation: SEG_A to SEG_D | **[B][V]** |
| BR-07 | Critical SKUs — definition and why it matters | **[B][V]** |
| BR-08 | What each key measure means | **[B][V]** |
| BR-09 | Burn-Out Days — the core formula | **[B][V]** |
| BR-10 | Burn-Out Days — Overall view vs location view | **[B][V]** |
| BR-11 | The BD sentinel value of 1000 | **[V]** |
| BR-12 | BD bucketing — two sets of ranges | **[B][V]** |
| BR-13 | Warehouse sales velocity uses transfer-out, not store sales | **[B][V]** |
| BR-14 | Active Days definition | **[B][V]** |
| BR-15 | Stock-Out — definition and sub-states | **[B][V]** |
| BR-16 | Opportunity Loss — what it means and its limits | **[B][V]** |
| BR-17 | On the Verge of Stockout — definition | **[B][V]** |
| BR-18 | Lead Days by location and section type | **[B][V]** |
| BR-19 | Safety Days standard buffer | **[B][V]** |
| BR-20 | Excess Stock — definition and the active-days gate | **[B][V]** |
| BR-21 | Excess threshold table — per location per section | **[B][V]** |
| BR-22 | Excess in the Overall view uses the maximum threshold | **[B][V]** |
| BR-23 | Excess BD buckets | **[B][V]** |
| BR-24 | Non-Moving Stock — definition | **[B][V]** |
| BR-25 | Non-Moving buckets | **[B][V]** |
| BR-26 | Non-Moving in the Overall view | **[B]** |
| BR-27 | Pending Orders — scope and logic | **[B][V]** |
| BR-28 | Unwanted SKUs in pending orders | **[B][V]** |
| BR-29 | Damage and Expiry — source and lookback | **[B][V]** |
| BR-30 | SKU Stock Status — all states | **[B][V]** |
| BR-31 | Recommended Action — all 14 states | **[B][V]** |
| BR-32 | Stock Share — how it is calculated at each hierarchy level | **[B][V]** |
| BR-33 | Put a number on every comparison | **[B]** |
| BR-34 | Only report things big enough to matter | **[B]** |
| BR-35 | Say what the numbers actually cover | **[B]** |
| BR-36 | NCE classification — future feature, not active | **[B]** |

---

# Section A — Where We Operate

## BR-00 — Saudi Arabia, riyals, and the closing-stock snapshot **[B]**

> **This is a Saudi Arabian retail operation. All money is in Saudi Riyals (SAR). The
> dashboard shows a closing-stock snapshot as of the date displayed on the report header.**

| Thing | What it is here |
|---|---|
| Country | Saudi Arabia |
| Currency | Saudi Riyal — always write **SAR** |
| VAT | Excluded. All stock values are net of the 15% VAT |
| Snapshot type | Closing stock — data reflects the state as of the date shown on the dashboard |
| Weekend | Friday and Saturday |
| Working week | Sunday to Thursday |

Because VAT is already excluded, never describe a figure as "including VAT", and never add
or remove VAT from any number. The snapshot date matters: always state which date the data
covers when reporting stock figures.

---

## BR-01 — The seven locations and their types **[B][V]**

> **The operation has seven locations: two warehouses (CDC and CFW001) and five stores.
> Every rule, query, and summary must respect this structure.**

| Location | Type | Notes |
|---|---|---|
| CDC | WH (Warehouse) | Central Distribution Centre — primary warehouse, replenishes stores via transfers |
| CFW001 | WH (Warehouse) | Second warehouse — all CDC warehouse rules apply (lead days, excess thresholds, BD velocity) |
| CFH014 | SH (Store) | Distant store |
| CFH017 | SH (Store) | Distant store |
| CFH018 | SH (Store) | **Nearby store** — shorter lead times apply (see BR-18) |
| CFH021 | SH (Store) | Distant store |
| CFH022 | SH (Store) | Distant store |

The model column `loc_type` holds "SH" for all five stores and "WH" for both warehouses.
This column drives several calculations including Burn-Out Days velocity (BR-10) and
Opportunity Loss scope (BR-16). Always use it — never hardcode location codes to determine
the type.

**CFW001 follows all CDC warehouse rules.** Lead Days (7 days all sections), Safety Days
(2 days), Excess Thresholds, BD velocity (transfer-out quantity), and the no-Opportunity-Loss
rule all apply to CFW001 identically to CDC. When a rule references "CDC" as a warehouse
type, treat CFW001 the same way unless a rule explicitly states otherwise.

---

# Section B — The Words We Use

## BR-02 — Division is the top level of the product hierarchy **[B]**

> **The product hierarchy runs: Division > Section > Category > Brand > SKU. Always use
> "Division" for the top level, never "Department".**

The model column is named `DEPARTMENT`, but the business and the dashboard use "Division"
in all user-facing labels. The business rules document and all AI output use Division.

The full hierarchy:

```
Division (DEPARTMENT)  >  Section  >  Category  >  Brand  >  SKU (PART_NUMBER_SUP)
```

The nine divisions are: COMMUNICATION, ELECTRONICS, FASHION, FMCG FOOD, FMCG NON-FOOD,
GM FASHION, GM HOME WARE, GM OTHERS, HOME FASHION.

Additionally, each SKU has: Supplier, Packing, SKU Type (LOCAL / OVERSEAS).

## BR-03 — Always use the same word for the same thing **[B]**

> **Use the approved name for every metric, every time. Never switch between two names for
> the same thing inside a summary.**

| Approved name | What it means | Never call it |
|---|---|---|
| **Stock Value** | SAR value of on-hand inventory at landing cost | Inventory value, stock worth, asset value |
| **SKU** | A distinct product (identified by PART_NUMBER_SUP) | Item, product, article, code |
| **Burn-Out Days** | Days of stock remaining at current velocity | Burn rate, stock days, days of cover, DOC |
| **Division** | Top level of the product hierarchy | Department, category group |
| **Section** | Second level of the hierarchy | Sub-category, sub-division |
| **Category** | Third level of the hierarchy | Product class, group |
| **Excess Stock** | Stock beyond the approved coverage threshold | Overstock, surplus |
| **Non-Moving** | SKU with no sales while stock was available for 30 days | Dead stock, slow-moving, stagnant |
| **Opportunity Loss** | Estimated daily revenue lost due to stockout | Revenue loss, missed sales |
| **Pending Orders** | Unreceived released domestic purchase orders, last 90 days | Open POs, outstanding orders |
| **Damage** | Negative inventory adjustments (entry type 3, qty < 0) | Write-off, shrinkage, expiry |
| **Location** | A store or warehouse | Branch, outlet, site, shop |
| **Store** | A customer-facing location (loc_type = SH) | Branch, shop, outlet |
| **Warehouse** | CDC (loc_type = WH) | Distribution centre, DC, depot |
| **Transfer** | Movement of stock from CDC to a store | Replenishment, dispatch, delivery |

---

# Section C — Data Scope and Views

## BR-04 — Data inclusion criteria **[B]**

> **The dashboard includes only SKUs that meet at least one of three conditions. An SKU
> absent from all three is excluded.**

A SKU appears in the data if:

1. It has stock on hand (CURRENT_STOCK > 0) at any location, **or**
2. It recorded at least one sale or transfer in the last 90 days, **or**
3. It has a pending purchase order.

This means an out-of-stock SKU with no recent movement and no open order is invisible in
the dashboard. Never state a "zero SKU" as confirmation that a product does not exist in
the range — it may simply be inactive.

## BR-05 — The three dashboard views and what each covers **[B]**

> **Use the correct view when describing a figure. A number from the Overall view and the
> same number from the Stores & WH view are calculated differently.**

| View | What it shows | Key difference |
|---|---|---|
| **Overall** | All locations combined — one consolidated number | Burn-Out Days uses store velocity only (BR-10). Excess uses maximum threshold across locations (BR-22). Non-Moving counts a SKU once if it is NM at any location (BR-26). |
| **Stores & WH** | One selected location — store or CDC | Each metric is computed for that location only, using that location's own velocity. |
| **SKU Details** | Row-level SKU data | Mirrors the scope of whichever view launched it. Two variants: Overall SKU Details and Stores & WH SKU Details. |

Always say which view a figure comes from when reporting a number. "Total stock value is SAR
X" is incomplete. "Total stock value across all locations is SAR X" or "Total stock value at
CFH014 is SAR X" is correct.

---

# Section D — SKU Classification

## BR-06 — SKU segmentation: SEG_A to SEG_D **[B][V]**

> **Every SKU in every Special Product Group is ranked by revenue contribution and assigned
> a segment. Use the segment to prioritise findings.**

Segmentation is done within each Special Product Group (equivalent to Category level):

| Segment | Revenue contribution within the group | Priority |
|---|---|---|
| SEG_A | Top 50% | Highest |
| SEG_B | Next 30% | High |
| SEG_C | Next 15% | Medium |
| SEG_D | Bottom 5% | Lowest |

The model column is `SKUSEGMENT`. Always use segments to rank findings — a stockout in
SEG_A carries more weight than the same stockout in SEG_D.

## BR-07 — Critical SKUs — definition and why it matters **[B][V]**

> **A Critical SKU is one in SEG_A or SEG_B AND of LOCAL (domestic) procurement type. Only
> Critical SKUs are used for Opportunity Loss and for critical-count metrics.**

```
Critical SKU = SKUSEGMENT IN {SEG_A, SEG_B} AND SKU_TYPE = "LOCAL"
```

The `TOP_SKU_IN_CAT` column flags this as "Y" for SEG_A and SEG_B, "N" for SEG_C and D.

**Why LOCAL only:** domestic SKUs have short replenishment cycles. A stockout in a LOCAL
critical SKU can be acted on within days. OVERSEAS SKUs have long lead times (30–120 days
for non-GCC/GCC procurement), making the same urgency signal misleading — so they are
excluded from the critical flag and from Opportunity Loss.

Never present Opportunity Loss for an OVERSEAS SKU, even if it is in SEG_A.

---

# Section E — The Measures and What They Mean

## BR-08 — What each key measure means **[B][V]**

> **Use these meanings exactly. Never restate a measure by describing its raw column instead
> of its business meaning.**

| Measure | How it is built | What it tells you |
|---|---|---|
| **Stock Value** | SUM of SKU_STOCK_VALUE | SAR value of all on-hand stock at landing cost |
| **#SKUs** | DISTINCTCOUNT of PART_NUMBER_SUP where CURRENT_STOCK > 0 | Number of distinct products currently in stock |
| **#Loc-SKUs** | DISTINCTCOUNT of locsku | Number of location-product combinations with stock |
| **Burn-Out Days** | Current Stock / Avg Daily Sales Qty | How many days current stock will last at the current rate |
| **Excess Stock Value** | SUM of EXCESS_STOCK_VALUE | SAR value of stock held beyond the approved coverage threshold |
| **Opportunity Loss / Day** | Avg Daily Sales Qty × Avg Retail Price | Estimated daily revenue lost per stockout SKU (critical SKUs, stores only) |
| **Pending Orders Value** | SUM of PENDING_ORDERS_VALUE | SAR value of unreceived domestic purchase orders placed in last 90 days |
| **Damage Value** | SUM of negative adjustment values (last 90 days) | SAR value of stock written off via negative inventory adjustments |
| **Stock Share** | Stock Value / Parent Stock Value | Share of this item's stock value within its immediate parent level |

## BR-09 — Burn-Out Days — the core formula **[B][V]**

> **Burn-Out Days = Current Stock / Average Daily Sales Qty. Both inputs must come from the
> same location scope. Never mix stock from one scope with velocity from another.**

```
Burn-Out Days = CURRENT_STOCK / AVG_DAILY_SALES_QTY

AVG_DAILY_SALES_QTY = Sales Qty (last 90 days) / Active Days
```

Active Days are defined in BR-14. The formula is computed at the SKU-location level and then
aggregated. Do not compute BD by aggregating stock and velocity separately and then dividing
— always divide at the SKU level first.

## BR-10 — Burn-Out Days — Overall view vs location view **[B][V]**

> **The Overall view calculates BD using store sales velocity only. The Stores & WH view
> calculates BD using that location's own velocity, including warehouse transfers for CDC.**

This is the single most important distinction in the model between the two views.

| View | Stock used | Velocity used |
|---|---|---|
| **Overall** | Sum of stock across all locations (stores + both warehouses) | Sum of AVG_DAILY_SALES_QTY from **stores only** (loc_type = SH) |
| **Stores & WH (store)** | Stock at that store | AVG_DAILY_SALES_QTY at that store |
| **Stores & WH (CDC)** | Stock at CDC | Transfer-out quantity at CDC (not store sales) |
| **Stores & WH (CFW001)** | Stock at CFW001 | Transfer-out quantity at CFW001 (not store sales) |

**Why this design:** the Overall view is asking "if we treat all stock as one pool, how many
days does it last at the rate stores are selling?" Warehouse stock will ultimately reach
customers through stores, so store velocity is the right denominator for both warehouses.

When reporting an Overall BD figure, always note that the denominator is store sales
velocity only.

## BR-11 — The BD sentinel value of 1000 **[V]**

> **When a SKU has stock but zero average daily sales, BD is set to 1000. This is a
> sentinel — it means "no velocity", not that the stock lasts 1000 days.**

```
If CURRENT_STOCK > 0 AND AVG_DAILY_SALES_QTY = 0  →  BD = 1000
```

Do not write "this SKU has 1000 days of stock." Write "this SKU has stock but no sales
velocity — it cannot burn through without demand." The 1000 value exists to allow the BD
column to hold a number rather than a blank, and to push the SKU into the highest BD bucket.

## BR-12 — BD bucketing — two sets of ranges **[B][V]**

> **Two separate BD bucket sets exist in the model. Use the right one for the right view.**

The **Overall / Deep Dive** buckets (BD TAGS table, TAG2 column):

| Bucket | Range |
|---|---|
| 0-10 | 0 to 10 days |
| 11-20 | 11 to 20 days |
| 21-30 | 21 to 30 days |
| 31-45 | 31 to 45 days |
| 46-60 | 46 to 60 days |
| 61-90 | 61 to 90 days |
| 91-120 | 91 to 120 days |
| OVER 120 | More than 120 days (including the 1000 sentinel) |

The **Stores & WH summary** buckets (bdseries table, BDTAG column):

| Bucket | Range |
|---|---|
| 0-10 | 0 to 10 days |
| 11-20 | 11 to 20 days |
| 21-30 | 21 to 30 days |
| 31-45 | 31 to 45 days |
| 45+ | More than 45 days |

The deep-dive view further breaks the 45+ bucket into granular bands. The summary view
collapses everything above 45 days into one bucket for a quicker read.

## BR-13 — Warehouse sales velocity uses transfer-out, not store sales **[B][V]**

> **When calculating BD for either warehouse (CDC or CFW001), the velocity input is
> transfer-out quantity, not store sales. Warehouses do not sell to customers — they
> transfer to stores.**

The `AVG_DAILY_SALES_QTY` column at CDC and CFW001 is populated with the average daily
transfer-out quantity, not retail sales. This is handled in the source data before it
reaches the model. The formula is the same (BR-09), only the business meaning of "sales"
changes.

Never describe a warehouse's BD as "days of stock at current sales rate." Write "days of
stock at the current transfer-out rate."

This applies to both CDC and CFW001. Whenever a rule references warehouse BD or warehouse
velocity, it covers both warehouse locations.

## BR-14 — Active Days definition **[B][V]**

> **Active Days are the number of days within the last 90 days when the SKU had stock on
> hand at the location and was eligible for sale or transfer.**

```
Active Days = days in last 90 days when CURRENT_STOCK > 0 at that location
```

Active Days matter for two things:

1. **BD calculation:** AVG_DAILY_SALES_QTY = Sales Qty / Active Days (not divided by 90).
   A SKU that was in stock for only 30 of the last 90 days has its sales divided by 30,
   not 90, giving a true daily rate.

2. **Excess Stock eligibility:** a SKU must have 30 or more Active Days in the last 90 days
   to be considered for excess classification (BR-20). Fewer than 30 Active Days means the
   velocity is too thin to judge excess reliably.

---

# Section F — Stockout and Replenishment

## BR-15 — Stock-Out — definition and sub-states **[B][V]**

> **A SKU is Out-of-Stock when CURRENT_STOCK = 0 at a store. Three sub-states tell the
> buying team what action is available.**

Stock-Out only applies to stores. Neither CDC nor CFW001 (the warehouses) are described as
"out of stock" in the buying context — they are the replenishment source.

The three sub-states of `RECOMMENDED_ACTION`:

| Sub-state | Meaning | Buying team action |
|---|---|---|
| STOCK OUT - AVAILABLE IN WAREHOUSE | Zero stock at the store; CDC has stock | Initiate internal transfer immediately |
| STOCK OUT - ORDER PLACED | Zero stock at the store; a purchase order is already open | Monitor incoming order; consider emergency transfer from CDC if available |
| STOCK OUT - PLACE ORDER | Zero stock; no warehouse stock; no open order | Raise a purchase order without delay |

Always use the sub-state when reporting a stockout. "Out of stock" alone is not enough
information for the buying team.

## BR-16 — Opportunity Loss — what it means and its limits **[B][V]**

> **Opportunity Loss is the estimated daily revenue lost due to a stockout SKU. It is shown
> only for Critical SKUs (SEG_A/B, LOCAL) at stores. Never show it for CDC or for
> OVERSEAS SKUs.**

```
Opportunity Loss / Day = Avg Daily Sales Qty × Avg Retail Price
```

The model column is `OPP_LOSS_DUE_TO_STOCKOUT` (pre-computed in the source system).

Hard limits:

- **Stores only.** Opportunity Loss is never calculated or shown for either warehouse (CDC or CFW001).
- **Critical SKUs only.** SEG_C and SEG_D stockouts do not carry an Opportunity Loss figure.
- **OVERSEAS SKUs excluded.** Even if an OVERSEAS SKU is SEG_A, no Opportunity Loss is shown.

When writing about Opportunity Loss, always say it is an estimate based on sales velocity
and retail price. Do not describe it as confirmed lost revenue — it is a model-based
approximation of what the business could have earned if the SKU were in stock.

## BR-17 — On the Verge of Stockout — definition **[B][V]**

> **A SKU is On the Verge of Stockout when its Burn-Out Days are less than the combined
> Lead Days and Safety Days for its location and section.**

```
Verge of Stockout = BD < (Lead Days + Safety Days)
```

If stock will run out before the replenishment can arrive, the SKU needs action now. The
verge classification is forward-looking: it triggers before the stockout happens.

The same three sub-states apply as for stockouts (BR-15), replacing "STOCK OUT" with
"ON THE VERGE OF STOCK OUT":

| Sub-state | Meaning |
|---|---|
| ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE | BD below trigger; CDC has stock — transfer now |
| ON THE VERGE OF STOCK OUT - ORDER PLACED | BD below trigger; order already open — monitor timing |
| ON THE VERGE OF STOCK OUT - PLACE ORDER | BD below trigger; no warehouse stock; no open order — order immediately |

## BR-18 — Lead Days by location and section type **[B][V]**

> **Lead Days vary by location and by whether the section is a food or non-food category.
> CFH018 has shorter lead times because it is geographically close to the warehouse.**

Lead Days are defined in the LEAD DAYS TABLE, set by the City Flower buying team. The
current configuration:

| Location | Type | Section type | Lead Days | Notes |
|---|---|---|---|---|
| CDC | Warehouse | All sections | 7 | Domestic procurement |
| CFW001 | Warehouse | All sections | 7 | Same rules as CDC |
| CFH014 | Distant store | Non-food sections | 7 | |
| CFH014 | Distant store | Food sections | 2 | Fast food replenishment |
| CFH017 | Distant store | Non-food sections | 7 | |
| CFH017 | Distant store | Food sections | 2 | Fast food replenishment |
| CFH018 | **Nearby store** | Non-food sections | 3 | Geographically close to CDC |
| CFH018 | **Nearby store** | Food sections | 1 | Perishable items, short cycle |
| CFH021 | Distant store | Non-food sections | 7 | |
| CFH021 | Distant store | Food sections | 2 | Fast food replenishment |
| CFH022 | Distant store | Non-food sections | 7 | |
| CFH022 | Distant store | Food sections | 2 | Fast food replenishment |

Food sections within FMCG FOOD are: CF-BAKERY, CF-CHILLED & DAIRY, CF-CONFECTIONERY,
CF-FROZEN FOOD, CF-GROCERY FOOD, CF-ROASTERY, CF-STAPLES.

All other sections are non-food and use the higher lead day value for their location.

**CFH018 is permanently classified as the nearby store.** If new stores are added, their
lead times will be configured in the LEAD DAYS TABLE — do not assume a new location uses
CFH018's lead times without confirmation.

**CFW001 is permanently classified as a warehouse.** Its lead days (7 days, all sections)
and Safety Days (2 days) match CDC exactly, confirmed in the LEAD DAYS TABLE.

Note: The buying team also references 30-day (GCC) and 120-day (non-GCC countries) lead
times for overseas procurement at CDC. These are procurement planning figures and are not
stored in the LEAD DAYS TABLE or used in the Verge of Stockout calculation in this model.
Only domestic lead times drive the verge calculation.

## BR-19 — Safety Days standard buffer **[B][V]**

> **A 2-day safety buffer is added to Lead Days for every location and every section.
> This buffer is uniform — never 0, never location-specific.**

```
Total Trigger = Lead Days + 2 Safety Days
```

Example: CFH014, non-food section — Lead Days = 7, Safety Days = 2, trigger = 9 days.
A SKU with BD = 8 at CFH014 is On the Verge of Stockout.

Example: CFH018, food section — Lead Days = 1, Safety Days = 2, trigger = 3 days.
A SKU with BD = 2 at CFH018 food is On the Verge of Stockout.

---

# Section G — Excess and Non-Moving Stock

## BR-20 — Excess Stock — definition and the active-days gate **[B][V]**

> **A SKU is Excess when its BD exceeds the coverage threshold for that location-section
> combination, AND it had 30 or more Active Days in the last 90 days.**

```
Excess Stock = BD > Excess Threshold Days  AND  Active Days >= 30

Surplus Qty = Stock Qty − (Threshold Days × Avg Daily Sales Qty)
```

The active-days gate matters. A SKU that was barely in stock for the last 90 days has
unreliable velocity, so calling it excess could be wrong. The 30-active-day floor ensures
only SKUs with enough trading history are flagged.

**What to report:**
- **Excess Stock Value:** the SAR value of the surplus quantity only (not the whole stock)
- **#Excess SKUs:** count of SKUs where EXCESS_STOCK > 0
- **Excess Stock Share:** Excess Stock Value / Total Stock Value

Do not describe the full stock value of an excess SKU as "excess value" — only the portion
above the threshold is excess.

## BR-21 — Excess threshold table — per location per section **[B][V]**

> **Coverage thresholds are set per location per section by the buying team. They are
> stable business decisions and do not change until explicitly revised.**

Thresholds are stored in the EXCESS THRESHOLD table (LOC_CODE + SECTION + EXCESS_DAYS).
A threshold of 0 days means no excess classification applies for that section at that location.

**Full threshold reference (EXCESS_DAYS):**

| Section | CDC / CFW001 (Warehouses) | Stores (CFH014–022) |
|---|---|---|
| CF-BAKERY | 0 | 15 |
| CF-BEAUTY PRODUCTS | 30 | 60 |
| CF-CHILLED & DAIRY | 15 | 45 |
| CF-CONFECTIONERY | 15 | 45 |
| CF-CROCKERY | 90 | 105 |
| CF-DELICATESSEN | 0 | 30 |
| CF-EGGS | 0 | 15 |
| CF-ELECTRICALS | 180 | 90 |
| CF-ELECTRONICS | 90 | 60 |
| CF-FASHION JWELRY&HAIR ACCS | 90 | 90 |
| CF-FOOT WEAR | 90 | 120 |
| CF-FROZEN FOOD | 15 | 45 |
| CF-FRUIT & VEGETABLES | 0 | 6 |
| CF-GROCERY FOOD | 15 | 45 |
| CF-HOME ACCESSORIES | 90 | 105 |
| CF-HOME CARE | 30 | 60 |
| CF-HOME DECORE | 120 | 120 |
| CF-HOME LINEN | 60 | 90 |
| CF-INFANT UTILITIES | 90 | 120 |
| CF-KIDS FASHION | 90 | 120 |
| CF-LADIES FASHION | 90 | 120 |
| CF-LADIES HAND BAGS | 30 | 60 |
| CF-LAND LINE | 0 | 0 |
| CF-LUGGAGE | 60 | 45 |
| CF-MEAT | 30 | 12 |
| CF-MENS FASHION | 90 | 90 |
| CF-MOBILE ACCESSORIES | 90 | 60 |
| CF-PERFUMES | 60 | 60 |
| CF-PERSONAL ACCESSORIES | 75 | 90 |
| CF-PERSONAL CARE | 30 | 60 |
| CF-PERSONAL GROOMING | 30 | 60 |
| CF-PLASTICS | 90 | 105 |
| CF-ROASTERY | 15 | 45 |
| CF-SMART WATCHES | 60 | 90 |
| CF-SPORTS | 90 | 60 |
| CF-STAPLES | 15 | 45 |
| CF-STATIONARY | 75 | 75 |
| CF-TOYS | 45 | 75 |
| CF-UTENSILS | 90 | 105 |
| CF-WATCHES & SUNGLASSES | 30 | 60 |

Note: Thresholds for all five stores (CFH014, CFH017, CFH018, CFH021, CFH022) are
identical. Both warehouses (CDC and CFW001) share the same threshold set, which differs
from the stores and reflects the longer acceptable stock cover appropriate for a
distribution centre.

## BR-22 — Excess in the Overall view uses the maximum threshold **[B][V]**

> **The Overall view cannot apply location-specific thresholds. Instead it uses the
> highest threshold across all locations for each section as the excess cutoff.**

The Overall view consolidates stock across all locations. Since each location has its own
threshold, the Overall view takes the maximum threshold for the SKU's section across all
locations. This is a conservative approach — a SKU is only flagged as excess overall if
it exceeds even the most generous threshold in the network.

When reporting Overall excess, state this qualification: the figure reflects stock
exceeding the maximum acceptable coverage across all locations.

## BR-23 — Excess BD buckets **[B][V]**

> **Excess stock is further analysed by how many days of excess cover remain, using five
> buckets. The excess BD is calculated the same way as regular BD but applied only to the
> surplus quantity.**

```
Excess BD = Excess Qty / Avg Daily Sales Qty (store velocity)
```

Buckets (EXCESS BDTAGS table):

| Bucket | Range |
|---|---|
| 0-30 | 0 to 30 days of excess |
| 31-60 | 31 to 60 days |
| 61-90 | 61 to 90 days |
| 91-120 | 91 to 120 days |
| OVER 120 | More than 120 days |

Higher excess BD means the surplus will take longer to sell through — the greater the risk
of capital lock-up and potential write-off. Always note the excess BD bucket when reporting
a large excess stock finding.

## BR-24 — Non-Moving Stock — definition **[B][V]**

> **A SKU is Non-Moving when it has recorded zero sales in the last 30 days while having
> stock available throughout all 30 of those days. Both conditions must be true together.**

```
Non-Moving = zero sales in last 30 days  AND  stock available for all 30 of those days
```

The 30-day window is the standard business definition, aligned with the 90-day lookback
used across the rest of the report (BR-00).

**Why both conditions matter:**
A SKU that ran out of stock halfway through the 30-day window is not non-moving — it is
a stockout. A SKU that had sales 31 days ago but nothing since is non-moving. The
availability condition prevents misclassifying stockouts as non-moving.

The `RECOMMENDED_ACTION` values for Non-Moving are:
- NON MOVING — no pending order exists
- NON MOVING - ORDER PLACED — the SKU is non-moving but a purchase order has already been placed

Seeing "NON MOVING - ORDER PLACED" is a double warning: the SKU is not selling and more
stock is arriving. This situation warrants immediate review of the open order.

## BR-25 — Non-Moving buckets **[B][V]**

> **Non-Moving SKUs are segmented by how long they have been inactive. Longer inactivity
> means higher risk of obsolescence and write-off.**

Buckets (NMDAYS table, NMDAYSTAG column, per location-SKU):

| Bucket | Range | Risk level |
|---|---|---|
| 30-60 | 30 to 60 days without sales | Monitor |
| 61-90 | 61 to 90 days | Elevated — review for promotion |
| 91-120 | 91 to 120 days | High — consider markdown or transfer |
| 121-150 | 121 to 150 days | Very high |
| 151-180 | 151 to 180 days | Serious — write-off risk rising |
| >180 | More than 180 days | Critical — likely dead stock |

Always report the NM bucket distribution, not just the total. A business with all
non-moving stock in the 30-60 day range is in a very different position from one with
most of it beyond 180 days.

## BR-26 — Non-Moving in the Overall view **[B]**

> **In the Overall view, a SKU is counted as Non-Moving if it is in a Non-Moving state at
> any single location. The SKU count is unique SKUs, not location-SKU pairs.**

This means one SKU that is non-moving at three stores is counted once in the #NM SKUs
figure for the Overall view. When reporting Overall NM SKU counts, do not describe them
as "instances" or "cases" — they are distinct products.

The NM Stock Value in the Overall view is the sum of non-moving stock values across all
locations where the SKU is NM — so the value is additive even though the SKU count is not.

---

# Section H — Pending Orders and Damage

## BR-27 — Pending Orders — scope and logic **[B][V]**

> **Pending Orders covers domestic (LOCAL) purchase orders only, with Released status,
> created within the last 90 days, and not yet received.**

The 90-day window is a business decision, applied uniformly across all locations and all
sections.

The data comes from the source system's purchase tables:
- Document type = 1 (Purchase Order)
- Status = 1 (Released)
- Order date within last 90 days
- Quantity not yet received (outstanding quantity > 0)

**Overseas orders are excluded.** Pending Orders only tracks domestic procurement. This
aligns with the Critical SKU definition (BR-07) — the focus is on the actionable short
cycle.

Metrics to report:
- **Pending Orders Value** — SAR value of outstanding quantities across all open orders
- **#Pending Order SKUs** — distinct SKUs included in pending orders
- **#Unwanted SKUs** — see BR-28

## BR-28 — Unwanted SKUs in pending orders **[B][V]**

> **An Unwanted SKU is one that appears in pending orders but is also currently flagged as
> having excess stock. More stock is arriving for a product that is already overstocked.**

```
Unwanted SKU = present in pending orders  AND  EXCESS_STOCK > 0
```

This is one of the most actionable signals in the report. The buying team should review
every unwanted SKU and consider cancelling or delaying the pending order where possible.

Always report #Unwanted SKUs alongside Pending Orders Value to give the full picture.
A high Pending Orders Value is less concerning if #Unwanted SKUs is low; a high unwanted
count even with a modest pending value is a process signal.

## BR-29 — Damage and Expiry — source and lookback **[B][V]**

> **Damage covers all negative inventory adjustments recorded in the source system over
> the last 90 days. It is not limited to physical damage — it includes expiry, wastage,
> and any write-off recorded as a negative adjustment.**

Source filter:
- Entry Type = 3 (adjustment)
- Quantity < 0

The lookback window is 90 days, a business decision applied uniformly across all locations.

**Monthly trend:** the dashboard shows Damage Value by month for the last 4 months. This
trend is important — a sudden spike in one month signals an event (product expiry batch,
physical damage incident) rather than a structural problem.

**No opportunity loss for damage.** Damage Value and Opportunity Loss are separate concepts.
Never add them together or imply one causes the other.

Damage Value is always a negative number in the source (it represents stock leaving the
books). Report it as an absolute SAR loss figure, without the negative sign, and state
it as a cost or write-off.

---

# Section I — Stock Status and Recommended Actions

## BR-30 — SKU Stock Status — all states **[B][V]**

> **The SKU_STOCK_STATUS column carries a simplified health label for each location-SKU
> row. Use it for filtering and grouping, not as the operational signal.**

SKU_STOCK_STATUS is the classification layer. RECOMMENDED_ACTION (BR-31) is the operational
output. The two work together — Stock Status answers "what category of situation is this?"
while Recommended Action answers "what should the buying team do?"

| SKU_STOCK_STATUS | What it means |
|---|---|
| STOCK AVAILABLE | SKU has stock; BD is within acceptable range; no other flags |
| EXCESS STOCK | SKU has stock; BD exceeds the section coverage threshold |
| VERGE OF STOCK OUT | SKU has stock; BD is below the lead time + safety days trigger |
| STOCK OUT | SKU has zero stock at this location |
| STOCK AVAILABLE BUT NO SALES | SKU has stock; no sales recorded recently; not yet at 30-day NM threshold |
| STOCK AVAILABLE BUT NO TRANSFERS | SKU has stock at CDC; no transfers recorded recently |
| REORDER LEVEL UNKNOWN | Reorder level not configured — cannot assess replenishment need |
| NOT ACTIVE | SKU is not actively listed or traded at this location |
| NEW SKU | SKU is newly listed; insufficient history for reliable classification |

## BR-31 — Recommended Action — all 14 states **[B][V]**

> **The RECOMMENDED_ACTION column is the operational output of the model. Every location-SKU
> row carries one of 14 states. Always use the full state name — never abbreviate.**

| Recommended Action | Situation | What the buying team should do |
|---|---|---|
| STOCK AVAILABLE | Stock is healthy; BD within threshold; no flags | No action needed |
| OVERSTOCK | Excess stock flagged; BD exceeds coverage threshold | Review for markdown, promotion, or inter-store transfer |
| NON MOVING | No sales in 30+ days; stock available throughout | Investigate demand; consider promotion, transfer, or clearance |
| NON MOVING - ORDER PLACED | Non-moving AND a purchase order is already open | Urgent: review and cancel or defer the open order |
| IN STOCK BUT NO SALES | Stock present; recent sales below the NM threshold (not yet 30 days) | Monitor; flag for follow-up if no sales in next 30 days |
| IN STOCK BUT NO TRANSFERS | Stock present at CDC; no outbound transfers recently | Check store demand signals; consider push transfer |
| ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE | BD below lead+safety trigger; CDC has stock | Transfer from CDC to store immediately |
| ON THE VERGE OF STOCK OUT - ORDER PLACED | BD below trigger; purchase order already open | Check order ETA vs BD; if ETA is too late, transfer from CDC if available |
| ON THE VERGE OF STOCK OUT - PLACE ORDER | BD below trigger; no warehouse stock; no open order | Place purchase order without delay |
| STOCK OUT - AVAILABLE IN WAREHOUSE | Zero stock at store; CDC has stock | Transfer from CDC to store immediately |
| STOCK OUT - ORDER PLACED | Zero stock; PO already open | Check order ETA; consider emergency transfer from CDC |
| STOCK OUT - PLACE ORDER | Zero stock; no warehouse stock; no open order | Place emergency purchase order |
| NOT ACTIVE | SKU not active at this location | No inventory action; review range planning |
| NEW LISTED SKU | SKU newly added; insufficient trading history | Monitor; do not apply NM or excess rules yet |
| NA | Status cannot be determined — data gap or edge case | Investigate the source record |

**The double-warning states.** Two states require the most urgent attention because they
combine two problems at once:
- **NON MOVING - ORDER PLACED:** the SKU is already stagnant and more stock is incoming
- **STOCK OUT - PLACE ORDER:** zero stock with no recovery plan in place

Report these first when summarising critical findings.

---

# Section J — How to Write It

## BR-32 — Stock Share — how it is calculated at each hierarchy level **[B][V]**

> **Stock Share is always relative to the immediate parent level, not to the total stock.
> Never describe a section's share as a share of total company stock unless it actually is.**

At the top level, Division Stock Share = Division Stock Value / Total Stock Value.

When drilling down:

| Level | Denominator |
|---|---|
| Division | Total Stock Value across all divisions |
| Section | The Division's Stock Value |
| Category | The Section's Stock Value |
| Brand | The Category's Stock Value |
| SKU | The Brand's Stock Value |

Example: GM HOME WARE holds 8% of total stock. Within GM HOME WARE, CF-UTENSILS holds
67%. That 67% is CF-UTENSILS' share of GM HOME WARE — not of total stock. Always say
"67% of GM HOME WARE's stock value" not "67% of total stock."

## BR-33 — Put a number on every comparison **[B]**

> **Every comparison must carry a figure. Never write "much higher", "slightly above",
> "broadly in line" on their own.**

If something moved, say by how much in SAR or as a percentage. If two things are compared,
give both figures.

Not acceptable:
> "Excess stock is significantly higher at CFH014 than at other stores."

Acceptable:
> "Excess stock at CFH014 is SAR 3.2M, compared to SAR 1.1M at CFH017 and SAR 0.9M at CFH018."

Other writing rules:
- **Short sentences.** One idea each. A store manager should understand it first time.
- **Lead with the number**, then the explanation.
- **Round sensibly.** SAR 3.2M in the headline, exact figure in supporting detail.
- **No jargon.** Never write "velocity", "offtake rate", "carry cost", "capital lock-up",
  "coverage ratio", "z-score", or "materiality" in the main findings.
- Use the approved names from BR-03, every time.

## BR-34 — Only report things big enough to matter **[B]**

> **A finding must be worth a manager's time. A small change on a tiny slice of the business
> is not a finding.**

Judge both the size of the change and the size of the business it affects. A 50% increase
in excess stock in CF-LAND LINE (threshold 0 days — no excess applies) is noise. A 5%
increase in excess stock in CF-ELECTRONICS (SAR millions) is a finding.

## BR-35 — Say what the numbers actually cover **[B]**

> **Always state which location, which date, and which scope a figure covers.**

If the figure is from the Overall view: say "across all locations."
If it is location-specific: name the location.
If it covers a specific division or section: name it.
If the data has a known gap or a query failed: say so and carry on with what you have.

---

# Section K — Future Features

## BR-36 — NCE classification — future feature, not active **[B]**

> **The NCEtag column (CENTRAL / ESSENTIAL / SEASONAL) exists in the model but is not
> currently populated. Do not use it in any calculation or summary.**

NCE (Central / Essential / Seasonal) is a planned SKU classification layer. The column
is blank in all current data. Until it is activated:
- Do not filter by NCEtag
- Do not describe any stock as "central", "essential", or "seasonal" based on this column
- Do not report NCE-based metrics

When NCE is activated, this rule will be updated to replace this placeholder with the
full classification logic.

---

# Section L — Still to Confirm

| # | Question | Affects |
|---|---|---|
| 1 | What is the exact source system formula for OPP_LOSS_DUE_TO_STOCKOUT? Dashboard PPT states Avg Daily Sales Qty × Avg Retail Price for critical SKUs. Needs source-system confirmation. | BR-16 |
| 2 | CFW001 confirmed as a second warehouse; all CDC warehouse rules apply. Not yet present in the main fact table — data will be added when the warehouse goes live. | BR-01 — closed |
| 3 | MOBILE GADGETS section was found in the data (e.g., CF-MOBILE GADGETS). Should this be added to the lead days reference in BR-18 as a non-food section? | BR-18 |

---

# What We Have Checked, and When

| Date | What we checked | Result |
|---|---|---|
| 2026-08-11 | All 6 location codes and their loc_type values | BR-01 confirmed |
| 2026-08-11 | All 14 RECOMMENDED_ACTION values from live data | BR-31 confirmed |
| 2026-08-11 | All SKU_STOCK_STATUS values from live data | BR-30 confirmed |
| 2026-08-11 | Full EXCESS THRESHOLD table across all locations | BR-21 confirmed |
| 2026-08-11 | Full LEAD DAYS TABLE across all locations and sections | BR-18 confirmed |
| 2026-08-11 | NMDAYS bucket structure (30-60 through >180) | BR-25 confirmed |
| 2026-08-11 | BD sentinel value of 1000 confirmed in chksgc_BDmeasure DAX | BR-11 confirmed |
| 2026-08-11 | BD bucket sets from both bdseries and BD TAGS tables | BR-12 confirmed |
| 2026-08-11 | Excess BD buckets from EXCESS BDTAGS table | BR-23 confirmed |
| 2026-08-11 | SGC_stockvalue, SGC_skus measures — store velocity only in denominator | BR-10 confirmed |
| 2026-08-11 | excessstockskus uses EXCESS_STOCK > 0 from main fact table | BR-20 confirmed |
| 2026-08-11 | SKUSEGMENT values SEG_A/B/C/D and TOP_SKU_IN_CAT Y/N confirmed | BR-06, BR-07 confirmed |
| 2026-08-11 | NCEtag column is blank across all rows in live data | BR-36 confirmed |
| 2026-08-11 | DAMAGE DATA table: damage_value confirmed as negative; monthly grain | BR-29 confirmed |

---

# Change Log

| Date | What changed |
|---|---|
| 2026-08-11 | Initial version created from full model exploration and documentation review. 36 rules across 12 sections. All rules verified against the live Power BI Desktop model (localhost:49270). |
| 2026-08-11 | **v2:** CFW001 added as a second warehouse (loc_type = WH). All CDC warehouse rules applied to CFW001: 7-day lead days (all sections), 2-day Safety Days, same excess thresholds as CDC, transfer-out velocity for BD, no Opportunity Loss. Updated BR-01 (location table), BR-10 (Overall BD denominator), BR-13 (warehouse velocity), BR-15 (stockout scope), BR-16 (Opportunity Loss exclusion), BR-18 (lead days matrix), BR-21 (threshold table header and note). CFW001 open item in Section L closed. |
