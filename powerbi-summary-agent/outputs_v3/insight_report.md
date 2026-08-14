# Key Insights
These like-for-like findings cover CFH014, CFH017, CFH018 and CFH021; CFH022 is shown separately as new-branch revenue.

**CFH021 revenue increased by about SAR 4.3M.** That was about 125.7% of the net like-for-like revenue change, because weaker performance elsewhere offset part of it. The increase was supported by higher transactions and more units, with average revenue per item and per transaction also higher. The gain was concentrated in mens fashion, grocery food, electronics and personal care. Check whether these gains were broad within each category or concentrated in a few product groups.

**CFH017 revenue decreased by about SAR 1.2M.** Units fell by about 208.5K and transactions by about 87.2K, so this was not just a change in average value per item. The decline was spread across several categories, led by fruit and vegetables, grocery food, mens fashion and personal care. That pattern suggests a broad demand slowdown in the branch rather than one isolated miss. Review CFH017 month by month to see when the decline widened most.

**CF-CONFECTIONERY units decreased by about 533.7K.** That was more than twice the total like-for-like units decline because other categories partly offset it. Most of the drop sat in CF-CHOCOLATE, especially CHOCOLATE COATED BARS, while the revenue decline was much smaller at about SAR 103.3K. This suggests fewer items were sold but average revenue per item rose materially. Check CF-CHOCOLATE by month and branch for transactions, basket size and price.

**FMCG FOOD units decreased by about 370.1K while revenue increased by about SAR 692.9K.** That units decline equalled 148.1% of the total like-for-like units decline, so revenue held up despite weaker item demand. The pattern was associated with higher average revenue per item rather than volume, with edible oils a clear positive and chocolate a major units drag. This means revenue growth in the division looks less secure than the headline suggests. Review the largest opposing groups, especially edible oils and chocolate, at a finer product level.

**CF-FRUIT & VEGETABLES revenue decreased by about SAR 683.8K.** Units also fell by about 216.2K, with the weakness spread across vegetables, imported fruits, local vegetables and imported vegetables. CFH017, CFH021 and CFH018 carried most of the decline, while CFH014 partly offset the revenue drop despite lower units. That pattern suggests average revenue per item rose in CFH014 while item demand still weakened. Compare the imported and local vegetable lines across the three weaker branches.

**CF-FRESH CHICKEN & PARTS revenue increased by about SAR 1.1M.** Units rose by about 188.3K and transactions by about 80.0K, so the gain came with stronger demand rather than price alone. Growth was shared across both FRESH CHICKEN and FRESH CHICKEN PARTS and appeared in all four branches. This makes it one of the strongest contributors inside the like-for-like base. Compare monthly performance by branch to see whether the lift was sustained or linked to a trading period.

**CF-MEAT revenue increased by about SAR 742.3K.** Units increased by about 160.9K and transactions by about 69.3K, while the mix shifted toward higher-volume chicken lines. Fresh chicken and chicken parts drove the increase, while beef and mutton were down. This suggests stronger sales in lower-average-value lines rather than a broad improvement across meat. Check SKU pricing and mix in chicken versus beef and mutton, especially in CFH018 and CFH021.

**CF-EDIBLE OILS revenue increased by about SAR 444.4K.** Units were down by 374 and transactions fell by about 2.4K, so the increase was associated with higher average revenue per item rather than more demand. VEGETABLE OIL more than offset a large decline in SUN FLOWER OIL, and the gain appeared across all four branches. This points to a shift in what sold within oils rather than category-wide volume growth. Investigate whether the change came from pricing, pack sizes or mix within the oil range.

**March revenue decreased by about SAR 2.0M, then April revenue increased by about SAR 2.1M.** April’s recovery was broad across all four branches, with the biggest lift in CFH021. The rebound was strongest in food-led groups such as fresh chicken and parts, edible oils and rice, while March weakness was concentrated in imported fruits and sunflower oil. That all-branch pattern is consistent with Ramadan or Eid moving trade between months, though it does not prove it on its own. Compare these months with holiday timing.

**FARM FRESH and FMCG FOOD accounted for about 73.3% of units and 55.8% of revenue.** These two divisions therefore shaped most of the overall result. Revenue resilience was associated with a few strong pockets, especially fresh chicken and parts and edible oils, while large everyday lines such as chocolate, vegetables and fruits pulled units down. This means the group result is heavily influenced by what happens inside these two divisions. Review the biggest winning and losing product groups within both divisions.

**CFH014 and CFH021 accounted for about 63.6% of revenue and 63.6% of transactions.** Changes in these two branches therefore mattered most to the group result. The main gains were linked to vegetable oil, fresh chicken, hand torch and fresh chicken parts, while the biggest drags included sunflower oil, white rice and mens smart watches. This shows group performance was concentrated in a small number of lines inside the two largest branches. Check these winning and losing lines by branch-month for CFH014 and CFH021.

**CFH022 generated about SAR 11.9M of new-branch revenue.** It had no prior-year revenue, so this should be shown as new-branch revenue rather than like-for-like growth. The branch represented about 8.7% of current revenue across the five branches in view and was led by grocery food, fruit and vegetables, and staples. Its mix looks like normal branch trading, not a one-line distortion. Confirm the management pack shows CFH022 separately from the four-branch like-for-like result.

# Data Quality Watch-outs
- Transaction-based measures in this model use category-level counts rather than distinct shopping trips. Our checks showed growth percentages remain usable, but Basket Value and Basket Size should not be described as the average spend or items per shopper unless they are rebuilt from true branch transaction counts.
- Coverage below the grand total, branch and month levels is often partial in this run. The category, product-group and special-product-group checks were enough to support the findings above, but they should not be read as a full census of every lower-level segment unless a complete query is run.
- Some findings relied on reused scan evidence with no new query in the investigation step. Our checks still support those conclusions, but they are less directly auditable than the items backed by fresh drill queries in this run.

# Evidence Trail
- cfh021_drove_group_revenue_growth
  - Baseline signal: CFH021 revenue Growth SAR 4,292,580.82, 125.7248% of comparable total change; QTY Growth 148,226.4116; bills growth 200,213.
  - Decomposition provided and reconciled:
    - Using QTY Growth as driver: volume_effect SAR 883,660.2728; rate_effect SAR 3,408,920.5472; rate_current 6.5032 vs rate_prior 5.9616.
    - Using bills growth as driver: volume_effect SAR 2,926,287.4994; rate_effect SAR 1,366,293.3206; rate_current 15.1206 vs rate_prior 14.6159.
  - Drill query by `MIS_DEEP_DIVE2[item_category_name]` for CFH021 succeeded.
  - Largest positive category movements returned:
    - CF-MENS FASHION: revenue Growth SAR 809,632.74; QTY Growth 47,922; bills growth 37,075.
    - CF-GROCERY FOOD: revenue Growth SAR 591,962.81; QTY Growth 164,199.965; bills growth 47,584.
    - CF-ELECTRONICS: revenue Growth SAR 583,327.77; QTY Growth 14,620; bills growth 12,515.
    - CF-PERSONAL CARE: revenue Growth SAR 533,932.91; QTY Growth 56,229; bills growth 22,830.
  - Main offsets returned:
    - CF-FRUIT & VEGETABLES: revenue Growth SAR -279,109.08; QTY Growth -61,617.58507; bills growth 4,329.
    - CF-HOT FOOD: revenue Growth SAR -50,335.28.
    - CF-CONFECTIONERY: revenue Growth SAR -25,252.81; QTY Growth -255,849.45133; bills growth -2,095.

- cfh017_dragged_comparable_performance
  - Baseline signal: CFH017 revenue Growth SAR -1,235,046.25; QTY Growth -208,538.0729; bills growth -87,223; revenue decline equals -36.1731% of total comparable revenue change.
  - Drill query by `MIS_DEEP_DIVE2[item_category_name]` for CFH017 succeeded.
  - Largest negative category movements returned:
    - CF-FRUIT & VEGETABLES: revenue Growth SAR -300,808.23; QTY Growth -74,530.93419; bills growth -20,962.
    - CF-GROCERY FOOD: revenue Growth SAR -172,096.26; QTY Growth -60,346.34826; bills growth -15,826.
    - CF-MENS FASHION: revenue Growth SAR -157,904.44; QTY Growth -7,096; bills growth -4,250.
    - CF-PERSONAL CARE: revenue Growth SAR -106,284.36; QTY Growth -10,549; bills growth -5,567.
    - CF-ROASTERY: revenue Growth SAR -109,362.35; QTY Growth -9,264.7337; bills growth -3,374.
  - Drill query by `MIS_DEEP_DIVE2[product_group_name]` for CFH017 succeeded.
  - Largest negative product-group movements returned:
    - CF-VEGETABLES: revenue Growth SAR -216,565.99; QTY Growth -53,377.31426; bills growth -15,129.
    - CF-FRUITS: revenue Growth SAR -84,758.40; QTY Growth -21,257.34993.
    - CF-FRESH MEAT: revenue Growth SAR -87,804.54; QTY Growth -9,054.11632.
    - CF-NUTS: revenue Growth SAR -100,651.60; QTY Growth -4,930.9847.
    - CF-CHOCOLATE: revenue Growth SAR -65,979.60; QTY Growth -24,247.40874; bills growth -6,143.

- confectionery_chocolate_drove_units_decline
  - Baseline signal: CF-CONFECTIONERY QTY Growth -533,734.5959, equal to 213.6075% of total comparable Units decline.
  - Investigation concluded from reused evidence; no new query executed in this run.
  - Reported category totals:
    - CF-CONFECTIONERY Units from 4.4M to 3.9M in the four like-for-like branches.
    - CF-CHOCOLATE contributed -533,309.5959 Units.
    - CHOCOLATE COATED BARS contributed -461,381.2012 Units.
    - Smaller negatives: CHOCOLATE BAGS -26.7K, CHEWING GUM MINT & MOUTH FRESH -25.8K, GIFT PACK CONFECTIONERY -25.0K.
  - Branch split reported:
    - CFH021 -255.8K Units; CFH018 -151.2K; CFH014 -101.8K; CFH017 -24.9K.
    - Transactions down in CFH021 (-2,095) and CFH017 (-6,415); CFH014 and CFH018 had higher transactions but lower Units.
  - Revenue context reported:
    - CF-CONFECTIONERY revenue down SAR 103.3K.
    - CHOCOLATE COATED BARS revenue down SAR 30.9K.

- fmcg_food_volume_down_revenue_up
  - Baseline signal: FMCG FOOD QTY Growth -370,120.72; 148.1271% of total Units decline; revenue Growth SAR 692,876.41.
  - Investigation concluded from reused evidence; no new query executed in this run.
  - Division totals reported:
    - Current revenue SAR 47.46M.
  - Branch split reported:
    - Units down in all branches: CFH014 -151.0K; CFH017 -88.5K; CFH018 -67.2K; CFH021 -63.4K.
    - Revenue growth by branch: CFH021 +SAR 552.6K; CFH018 +SAR 335.5K; CFH017 -SAR 200.1K; CFH014 +SAR 4.8K.
  - Product-group patterns reported:
    - CF-EDIBLE OILS: +SAR 444.4K revenue; -374 Units.
    - CF-FROZEN POULTRY: +SAR 169.0K revenue; -4.9K Units.
    - CF-DRY FRUITS: +SAR 63.2K revenue; -7.7K Units.
    - CF-CHOCOLATE: -533.3K Units; -SAR 103.0K revenue.
    - SUN FLOWER OIL: -SAR 560.1K revenue; -43.4K Units.
    - VEGETABLE OIL: +SAR 670.4K revenue; +30.3K Units.

- fruit_vegetables_broad_decline
  - Baseline signal: CF-FRUIT & VEGETABLES revenue Growth SAR -683,753.3; QTY Growth -216,203.1651; impact share 86.5273%.
  - Investigation concluded from reused evidence; no new query executed in this run.
  - Product-group split reported:
    - CF-VEGETABLES: SAR -515.8K revenue; -140.3K Units.
    - CF-FRUITS: SAR -165.2K revenue; -75.6K Units.
  - Special product-group split reported:
    - IMPORTED VEGETABLES: SAR -314.5K revenue; -75.9K Units.
    - IMPORTED FRUITS: SAR -287.9K revenue; -94.9K Units.
    - LOCAL VEGETABLES: SAR -211.4K revenue; -77.7K Units.
    - LOCAL FRUITS: +SAR 122.7K revenue; +19.3K Units.
  - Branch split reported:
    - CFH017: SAR -300.8K revenue; -74.5K Units.
    - CFH021: SAR -279.1K revenue; -61.6K Units.
    - CFH018: SAR -264.5K revenue; -66.8K Units.
    - CFH014: +SAR 160.7K revenue; -13.2K Units.

- fresh_chicken_and_parts_strength
  - Baseline signal: CF-FRESH CHICKEN & PARTS revenue Growth SAR 1,110,054.25; bills growth 80,035; QTY Growth 188,331.0; 32.5122% of comparable total revenue change.
  - Investigation concluded from reused evidence; no new query executed in this run.
  - Special product-group split reported:
    - FRESH CHICKEN: +SAR 630.9K revenue; +66.3K Units; +39.1K Transactions.
    - FRESH CHICKEN PARTS: +SAR 479.2K revenue; +122.0K Units; +40.9K Transactions.
  - Branch split reported:
    - CFH014 +SAR 442.1K; CFH018 +SAR 336.4K; CFH021 +SAR 197.4K; CFH017 +SAR 134.1K.

- meat_growth_but_lower_average_value
  - Baseline signal: CF-MEAT revenue Growth SAR 742,310.17; QTY Growth 160,856.3733.
  - Decomposition provided and reconciled:
    - Using QTY Growth as driver: volume_effect SAR 1,914,104.9225; rate_effect SAR -1,171,794.7525; rate_current 10.3846 vs rate_prior 11.8995.
    - Using bills growth as driver: volume_effect SAR 1,448,084.2244; rate_effect SAR -705,774.0544; rate_current 19.1996 vs rate_prior 20.8865.
  - Investigation concluded from reused evidence; no new query executed in this run.
  - Movement details reported:
    - CF-FRESH CHICKEN & PARTS: +SAR 1.11M revenue; +188.3K Units; +80.0K Transactions.
    - FRESH CHICKEN: +SAR 630.9K; +66.3K Units; +39.1K Transactions.
    - FRESH CHICKEN PARTS: +SAR 479.2K; +122.0K Units; +40.9K Transactions.
    - FRESH MEAT BEEF: -SAR 162.1K.
    - FRESH MEAT MUTTON: -SAR 160.7K.
  - Branch contribution reported:
    - CFH018 +SAR 302.2K; CFH021 +SAR 237.8K; CFH014 +SAR 156.0K; CFH017 +SAR 46.3K.

- edible_oils_shifted_to_higher_value_mix
  - Baseline signal: CF-EDIBLE OILS revenue Growth SAR 444,434.3; QTY Growth -374.0; bills growth -2,356.
  - Decomposition provided and reconciled:
    - Using QTY Growth as driver: volume_effect SAR -5,838.7507; rate_effect SAR 450,273.0507; rate_current 16.8516 vs rate_prior 15.6116.
    - Using bills growth as driver: volume_effect SAR -42,859.4734; rate_effect SAR 487,293.7734; rate_current 19.7656 vs rate_prior 18.1916.
  - Investigation concluded from reused evidence; no new query executed in this run.
  - Product details reported:
    - VEGETABLE OIL: +SAR 670.4K; +30,329 Units; +22,520 Transactions.
    - SUN FLOWER OIL: -SAR 560.1K; -43,428 Units; -33,409 Transactions.
    - OTHER COOKING OIL: +SAR 201.5K.
  - Branch split reported:
    - CFH018 +SAR 159.4K; CFH014 +SAR 139.9K; CFH021 +SAR 125.8K; CFH017 +SAR 19.3K.

- march_april_calendar_swing
  - Baseline signal: March revenue Growth SAR -2,043,504.72; April revenue Growth SAR 2,112,426.17.
  - Temporal context provided:
    - Worst period drill flagged March with top negatives IMPORTED FRUITS SAR -326,093.18, SUN FLOWER OIL SAR -138,628.07, IMPORTED VEGETABLES SAR -134,362.38.
  - Drill query by `MIS_DEEP_DIVE2[product_group_name]` for month 4 succeeded.
  - Top April product-group gains returned:
    - CF-FRESH CHICKEN & PARTS +SAR 233,063.62; QTY Growth 37,387.
    - CF-EDIBLE OILS +SAR 217,244.10; QTY Growth 8,261.
    - CF-RICE +SAR 212,921.52; QTY Growth 7,318.67.
    - CF-SKIN CARE +SAR 140,646.34.
    - CF-WATCHES +SAR 124,199.92.
  - Drill query by `MIS_DEEP_DIVE2[special_product_group_name]` for month 4 succeeded.
  - Top April special-product-group gains returned:
    - VEGETABLE OIL +SAR 286,917.65; QTY Growth 15,187.
    - BASMATI RICE +SAR 157,385.32; QTY Growth 5,572.02.
    - FRESH CHICKEN +SAR 121,461.15; QTY Growth 12,366.
    - FRESH CHICKEN PARTS +SAR 111,602.47; QTY Growth 25,021.
    - CHOCOLATE COATED BARS +SAR 73,177.42; QTY Growth -8,928.74776.
  - Drill query by `MIS_DEEP_DIVE2[store_no]` for month 4 succeeded.
  - All-branch April revenue gains returned:
    - CFH021 +SAR 1,019,128.89; QTY Growth 75,489.2553; bills growth 47,137.
    - CFH014 +SAR 508,905.98; QTY Growth 42,802.4454; bills growth 38,473.
    - CFH018 +SAR 364,771.51; QTY Growth 28,426.62255; bills growth 19,596.
    - CFH017 +SAR 219,619.79; QTY Growth 28,977.49933; bills growth 3,068.

- division_mix_concentrated_in_farm_fresh_and_fmcg_food
  - Baseline signal: FARM FRESH and FMCG FOOD hold 13,644,163.0367 current Units (73.3331%), 5,549,380 current Transactions (66.5726%), and SAR 70,216,044.13 current Revenue (55.8111%).
  - Investigation concluded from reused evidence; no new query executed in this run.
  - Branch-level summary reported for these divisions:
    - CFH014 +SAR 369K revenue growth; CFH018 +SAR 390K; CFH021 +SAR 610K; CFH017 -SAR 466K.
    - All four branches showed lower Units than last year, ranging from -82.1K to -146.5K.
  - Product-group examples reported:
    - Positive: CF-FRESH CHICKEN & PARTS +SAR 1.11M; CF-EDIBLE OILS +SAR 444K.
    - Negative Units-heavy lines: CF-CHOCOLATE -533.3K Units; CF-VEGETABLES -140.3K Units; CF-FRUITS -75.6K Units.

- branch_base_concentrated_in_cfh014_cfh021
  - Baseline signal: CFH014 and CFH021 hold SAR 80,014,173.18 of current revenue, 63.5991% of comparable total; net bills CURRENT 5,298,461, 63.5624% of total.
  - Drill query by `MIS_DEEP_DIVE2[special_product_group_name]` for CFH014 and CFH021 succeeded.
  - Largest positive special-product-group movements returned:
    - VEGETABLE OIL: +SAR 439,322.4; QTY Growth 18,504; bills growth 14,062.
    - FRESH CHICKEN: +SAR 418,612.07; QTY Growth 44,446; bills growth 24,607.
    - HAND TORCH: +SAR 264,406.98; QTY Growth 3,871; bills growth 3,173.
    - FRESH CHICKEN PARTS: +SAR 220,956.98; QTY Growth 58,190; bills growth 20,876.
    - EGG BOX PACK: +SAR 179,433.21; QTY Growth 13,157; bills growth 12,108.
  - Largest negative special-product-group movements returned:
    - SUN FLOWER OIL: SAR -431,949.39; QTY Growth -31,937; bills growth -25,124.
    - WHITE RICE: SAR -187,824.29; QTY Growth -6,999; bills growth -5,530.
    - MENS SMART WATCHES: SAR -168,583.17; QTY Growth -209; bills growth -872.
    - MENS T SHIRT: SAR -127,720.4; QTY Growth -8,000; bills growth -5,192.
    - FRESH MEAT BEEF: SAR -118,491.4; QTY Growth -6,337.81132; bills growth -1,263.
  - Investigation explanation also reported item-category and product-group winners in these two branches:
    - CF-MENS FASHION +SAR 782.7K; CF-ELECTRONICS +SAR 639.8K; CF-GROCERY FOOD +SAR 458.1K; CF-PERSONAL CARE +SAR 457.9K; CF-MEAT +SAR 393.8K.
    - CF-FRESH CHICKEN & PARTS +SAR 639.6K; CF-WATCHES +SAR 280.6K; CF-MENS TOP WEAR +SAR 274.8K; CF-EDIBLE OILS +SAR 265.7K; CF-RECHARGEABLE TORCH +SAR 257.9K.

- cfh022_new_branch_revenue
  - Baseline signal: CFH022 current net revenue CURRENT SAR 11,906,055.96; no net revenue PAST.
  - Investigation concluded from reused evidence; no new query executed in this run.
  - Reported context:
    - CFH022 equals about 8.7% of current revenue across five branches: SAR 11.91M of SAR 137.72M.
    - Largest item categories reported: CF-GROCERY FOOD SAR 2.21M; CF-FRUIT & VEGETABLES SAR 1.13M; CF-STAPLES SAR 1.06M.
    - Largest product groups reported: CF-RICE SAR 684.7K; CF-FRUITS SAR 616.0K.

# Confidence & Caveats
- CFH021 growth: high confidence. Supported by the baseline branch result, two reconciled breakdowns of the revenue change, and a successful category drill.
- CFH017 decline: high confidence. Supported by the baseline branch result and two successful drill queries showing the same broad-based weakness.
- Confectionery/chocolate units decline: medium confidence. The conclusion is detailed and internally consistent, but no fresh query was run during investigation in this run.
- FMCG FOOD units down but revenue up: medium confidence. The result is clear in the baseline signal and the reported group details, but the investigation relied on reused evidence rather than a new drill.
- Fruit and vegetables decline: medium confidence. The branch and product details are specific, but they came from reused evidence without a fresh query in this run.
- Fresh chicken and parts strength: medium confidence. The contribution is clear and broad-based, but the investigation did not run a new query in this run.
- Meat growth with lower average revenue per item: medium confidence. Two reconciled breakdowns support the pattern, but the deeper line and branch explanation came from reused evidence.
- Edible oils higher-value pattern: medium confidence. The reconciled breakdown strongly supports the direction, but the detailed mix explanation was not freshly queried in this run.
- March-April swing: high confidence for the existence and breadth of the swing. Three successful April drill queries support the branch and category pattern. Confidence is lower on the holiday interpretation because the model does not contain Ramadan or Eid dates.
- Division concentration in FARM FRESH and FMCG FOOD: medium confidence. The concentration figures are solid, but the internal driver explanation relied on reused evidence.
- Branch concentration in CFH014 and CFH021: high confidence. The concentration figures are solid and the branch-pair drill query succeeded.
- CFH022 new-branch revenue: high confidence. The branch has current revenue and no prior revenue in the supplied evidence, matching the configured exclusion from like-for-like.
- General caveats:
  - Lower-level coverage is partial in several dimensions per the coverage matrix, so examples below branch and month level are strong contributors, not a guaranteed full ranking of every segment unless directly queried.
  - This model stores transactions from category-level counts for year-on-year work. Those growth rates are usable, but transaction-based levels such as Basket Value and Basket Size should be treated carefully.
  - No queries failed in the supplied investigations, but several investigations concluded from reused scan evidence with zero new probe executions.

# Suggested Follow-ups
- Why did CFH021 grow so strongly in a few categories? Drill CF-MENS FASHION, CF-GROCERY FOOD, CF-ELECTRONICS and CF-PERSONAL CARE to `product_group_name`, then by month within CFH021.
- When did CFH017 weaken most, and was it broad or concentrated? Run a month-by-month breakdown for CFH017 across the largest losing categories and product groups.
- Why did confectionery lose so many units while revenue held up better? Check CF-CHOCOLATE, especially CHOCOLATE COATED BARS, by branch and month for Units, Transactions, Basket Size and Price.
- Is FMCG FOOD revenue being supported by a few higher-value pockets? Compare CF-EDIBLE OILS, CF-CHOCOLATE, CF-FROZEN POULTRY and CF-DRY FRUITS at product-group and, if available, item level.
- Are fruit and vegetable losses mainly imported or local, and in which branches? Split CF-FRUIT & VEGETABLES by branch and `special_product_group_name`, focusing on CFH017, CFH018 and CFH021.
- Is fresh chicken strength sustained or event-driven? Review monthly performance by branch for FRESH CHICKEN and FRESH CHICKEN PARTS.
- Is meat growth coming from pricing or from a shift toward lower-value chicken lines? This model can test branch and product-group mix further, but separating true price change from product mix would likely need SKU-level price files outside the current evidence.
- What explains the edible oils shift? Within this model, compare VEGETABLE OIL, SUN FLOWER OIL and OTHER COOKING OIL by branch and month; confirming pack-size or ticket price changes would likely need SKU-level data outside this run.
- Was the March-April swing mainly Ramadan or Eid timing? The model can compare March and April patterns by branch and category again, but confirming the calendar effect needs holiday-date mapping outside this model.
- Why do FARM FRESH and FMCG FOOD dominate the group result? Drill both divisions to product-group and branch-month level to isolate which large lines are supporting revenue and which are reducing units.
- Which lines inside CFH014 and CFH021 matter most to group performance now? Split the main winning and losing special product groups by branch and month for these two branches.
- How should management reporting present the new branch? Show two lines side by side for the same period: four-branch like-for-like revenue and separate CFH022 new-branch revenue of SAR 11.9M.