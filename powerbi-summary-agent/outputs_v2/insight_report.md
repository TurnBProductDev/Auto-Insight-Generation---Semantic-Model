# Key Insights
Unless stated otherwise, year-on-year figures here use the like-for-like branches CFH014, CFH017, CFH018 and CFH021.

**CFH021 Revenue increased by about SAR 4.3M and more than offset weaker branches.** That branch delivered about 125.7% of the group’s net Revenue increase, with Transactions up 200.2K and Units up 148.2K. The gain came mainly from broad-based category growth in Mens Fashion, Grocery Food, Electronics and Personal Care, rather than one isolated line. It was associated with both more transactions and a higher average value per item. Check what changed in CFH021 across those categories versus last year.

**CF-CONFECTIONERY Units declined by about 533.7K, mainly in chocolate bars.** The drop came almost entirely from CF-CHOCOLATE, with CHOCOLATE COATED BARS making up about 86.4% of the category’s unit decline. Transactions fell by only 5.3K, far less than the Units decline, so the main evidenced contributor is fewer items purchased per transaction rather than a large loss of transactions. The weakness was spread across all four branches, especially CFH021 and CFH018. Review chocolate bar SKUs and pack sizes by branch.

**FMCG FOOD sold about 370.1K fewer Units even though Revenue still increased by about SAR 692.9K.** The shortfall was concentrated in CF-CHOCOLATE, with added drag from Pasta & Noodles, Croissant Brioche & Pastries, Nuts and Dry Fruits. The Revenue gain was associated mainly with a higher average value per item rather than more units, while unit declines were broad-based across all four branches. This pattern suggests Revenue was supported even as item demand weakened. Check item mix and pricing changes in chocolate and sunflower oil, especially in CFH014 and CFH017.

**CFH017 Revenue declined by about SAR 1.24M, the largest branch drag.** Units fell 208.5K and Transactions fell 87.2K, showing weaker demand as well as lower sales. The main pressure came from Fruit & Vegetables, Grocery Food and Mens Fashion, with further drag from Roastery, Personal Care and Electronics. Fresh-food and grocery lines appear to be the biggest likely contributors to the branch decline. Review month-by-month performance in those categories for CFH017.

**CF-FRUIT & VEGETABLES reduced Revenue by about SAR 683.8K and Units by 216.2K.** Most of the decline sat in vegetables and imported fruit lines, with imported vegetables, imported fruits and local vegetables the largest drags. CFH017, CFH021 and CFH018 all declined, while CFH014 was a partial offset with Revenue up despite lower Units. That pattern suggests weaker volumes were widespread, but average value per item may have held up better in CFH014. Compare imported versus local lines by branch.

**CF-FRESH CHICKEN & PARTS added about SAR 1.1M of Revenue through stronger demand.** Units rose 188.3K and Transactions rose 80.0K, with gains across all four branches. Both FRESH CHICKEN and FRESH CHICKEN PARTS contributed, so the uplift was broad within the group. Average value per item and per transaction were lower than last year, which means the gain came mainly from selling more rather than charging more. Review whether this was steady through the year or concentrated in specific months.

**CF-MEAT increased Revenue by about SAR 742.3K, but the average value per item fell.** Units rose 160.9K, and the increase was broad-based across all four branches. The gain was concentrated in chicken lines, while fresh meat lines declined, which is associated with the lower average value per item at category level. This suggests mix shifted toward faster-growing, lower-value meat lines rather than purely higher pricing. Compare chicken and fresh meat item rates in more detail.

**April Revenue increased by about SAR 2.1M after March fell by about SAR 2.0M.** April was the strongest month in the period series and all four branches improved, led by CFH021. The uplift was concentrated in Vegetable Oil, Basmati Rice, Fresh Chicken and Fresh Chicken Parts, with positive Units and mostly positive Transactions. Because Ramadan and Eid move between months, this swing may reflect calendar timing as well as trade. Compare March and April directly for imported fruits and sunflower oil.

**CF-EDIBLE OILS Revenue increased by about SAR 444.4K, with Vegetable Oil offsetting Sun Flower Oil weakness.** VEGETABLE OIL added about SAR 670.4K while SUN FLOWER OIL lost about SAR 560.1K. The combined movement varied by branch, with CFH018 the main positive contributor, and the overall pattern was associated more with a higher average value per item than with stronger demand. This points to a mix shift within oils rather than broad volume growth. Investigate SKU, promotion and pack-size changes by branch.

**FARM FRESH and FMCG FOOD together added about SAR 903K of Revenue, while Units fell 429.5K.** Together they represent about 73.3% of current Units and 55.8% of current Revenue. Gains in Fresh Chicken & Parts and Edible Oils partly offset declines in Vegetables, Fresh Meat and Fruits. This means these two divisions are strongly associated with the group pattern of higher Revenue but weaker item demand. Review the weaker Farm Fresh lines, especially in CFH017.

**CFH014 and CFH021 together account for about SAR 80.0M of current Revenue, with CFH021 setting the direction more strongly.** Together they make up about 63.6% of current Revenue and 63.6% of Transactions. CFH021 owns most of the largest positive category movements, while CFH014 looks more mixed and includes declines in major categories such as Grocery Food. That means the current group direction is more closely associated with CFH021’s category mix than with CFH014’s. Compare the two branches on the latest complete month.

**CFH022 current Revenue reached about SAR 11.9M as new-branch sales.** It has no last-year Revenue, so this is new-branch Revenue rather than like-for-like growth. The sales mix was broad, led by Grocery Food, Fruit & Vegetables, Staples, Personal Care and Chilled & Dairy, suggesting an everyday-shopping profile rather than one narrow category. This current Revenue is material to total sales but should remain separate from year-on-year growth commentary. Confirm the full category split beyond the leading rows.

# Data Quality Watch-outs
- Most category, product-group and special-product-group evidence is from partial top-row cuts rather than full distributions. The coverage matrix marks these levels as partial and not trusted for completeness, so the owner should verify whether any meaningful contributors sit outside the returned rows before final publication.
- The branch comparison between CFH014 and CFH021 is based on all-available comparable evidence, not explicitly the latest complete month. Our checks showed the pattern is useful, but the owner should verify the same split for the most recent month because the summary should lead with the latest period.
- The April follow-up confirmed April drivers, but it did not re-run March at the same detail. Our checks showed imported fruits and sunflower oil were March drags in the period scan, so the owner should verify the month-to-month comparison directly before treating that explanation as settled.

# Evidence Trail
- `confectionery_units_decline_centered_on_chocolate_bars`
  - Reused investigation conclusion only; no additional DAX probe executed.
  - Comparable Units in `CF-CONFECTIONERY` fell from 4.40M to 3.87M, a change of -533.7K.
  - `CF-CHOCOLATE` contributed -533.3K Units; `CHOCOLATE COATED BARS` contributed -461.4K Units, about 86.4% of the category decline.
  - Branch split of unit decline: `CFH021` -255.8K, `CFH018` -151.2K, `CFH014` -101.8K, `CFH017` -24.9K.
  - `bills growth` for the category was only -5.3K, far smaller than the Units decline.

- `fmcg_food_units_down_despite_revenue_growth`
  - Reused investigation conclusion only; no additional DAX probe executed.
  - `FMCG FOOD` had `QTY Growth` -370.1K and `revenue Growth` +692.9K across the four branches.
  - Main unit drags cited from reused evidence: `CF-CHOCOLATE` -533.3K Units and -SAR 103.0K Revenue; `CF-PASTA & NOODLES` -19.4K Units; `CF-CROISSANT BRIOCHE&PASTRIES` -11.7K; `CF-NUTS` -10.5K; `CF-DRY FRUITS` -7.7K.
  - Special-product-group drag cited from reused evidence: `SUN FLOWER OIL` -43.4K Units and -SAR 560.1K Revenue; `WHOLE CHICKEN` -16.2K Units.
  - Branch unit decline from reused evidence: `CFH014` -151.0K, `CFH017` -88.5K, `CFH018` -67.2K, `CFH021` -63.4K.
  - Signal decomposition stated revenue split of -SAR 1.664M from Units and +SAR 2.357M from average revenue per item.

- `cfh021_drove_group_revenue_growth`
  - Baseline signal: `CFH021` `revenue Growth` +4,292,580.82; `bills growth` +200,213; `QTY Growth` +148,226.4116.
  - Signal decomposition by Units: `volume_effect` +883,660.2728 and `rate_effect` +3,408,920.5472; `rate_current` 6.5032 vs `rate_prior` 5.9616; reconciled true.
  - Signal decomposition by Transactions: `volume_effect` +2,926,287.4994 and `rate_effect` +1,366,293.3206; `rate_current` 15.1206 vs `rate_prior` 14.6159; reconciled true.
  - DAX probe by `'MIS_DEEP_DIVE2'[item_category_name]` for `CFH021` returned top revenue growers including `CF-MENS FASHION` +809,632.74 with `bills growth` +37,075; `CF-GROCERY FOOD` +591,962.81 with +47,584; `CF-ELECTRONICS` +583,327.77 with +12,515; `CF-PERSONAL CARE` +533,932.91 with +22,830; `CF-WATCHES & SUNGLASSES` +329,772.77.
  - DAX probe by `'MIS_DEEP_DIVE2'[product_group_name]` returned `CF-WATCHES` +342,557.37 and +10,649 bills; `CF-MENS TOP WEAR` +311,698.85 and +12,034; `CF-RECHARGEABLE TORCH` +246,310.72 and +3,644; `CF-SKIN CARE` +236,497.23 and +11,086; `CF-MENS BOTTOMS` +230,912.84 and +6,064.
  - DAX probe by `'MIS_DEEP_DIVE2'[special_product_group_name]` returned `HAND TORCH` +227,447.13; `VEGETABLE OIL` +197,809.85; `MENS WATCH` +183,849.33; `FRESH CHICKEN` +129,129.52.
  - All three DAX probes succeeded.

- `fruit_vegetables_complex_drove_decline`
  - Reused investigation conclusion only; no additional DAX probe executed.
  - `CF-FRUIT & VEGETABLES` had `QTY Growth` -216.2K and `revenue Growth` -SAR 683.8K.
  - Category split from reused evidence: `CF-VEGETABLES` -140.3K Units and -SAR 515.8K; `CF-FRUITS` -75.6K Units and -SAR 165.2K.
  - Product-group detail from reused evidence: `IMPORTED VEGETABLES` -75.9K Units and -SAR 314.5K; `IMPORTED FRUITS` -94.9K Units and -SAR 287.9K; `LOCAL VEGETABLES` -77.7K Units and -SAR 211.4K; `LOCAL FRUITS` +19.3K Units and +SAR 122.7K.
  - Branch revenue split from reused evidence: `CFH017` -SAR 300.8K, `CFH021` -SAR 279.1K, `CFH018` -SAR 264.5K, `CFH014` +SAR 160.7K with Units still down 13.2K.

- `cfh017_largest_branch_drag`
  - Baseline signal: `CFH017` `revenue Growth` -1,235,046.25; `QTY Growth` -208,538.0729; `bills growth` -87,223.
  - DAX probe by `'MIS_DEEP_DIVE2'[item_category_name]` for `CFH017` sorted ascending `Revenue Growth` succeeded.
  - Largest returned category drags: `CF-FRUIT & VEGETABLES` -300,808.23 with `bills growth` -20,962; `CF-GROCERY FOOD` -172,096.26 with -15,826; `CF-MENS FASHION` -157,904.44 with -4,250; `CF-ROASTERY` -109,362.35 with -3,374; `CF-PERSONAL CARE` -106,284.36 with -5,567; `CF-ELECTRONICS` -96,300.44 with -772.
  - DAX probe by `'MIS_DEEP_DIVE2'[product_group_name]` for `CFH017` sorted ascending `Revenue Growth` succeeded.
  - Largest returned product-group drags: `CF-VEGETABLES` -216,565.99 with -15,129 bills; `CF-NUTS` -100,651.60 with -2,999; `CF-FRESH MEAT` -87,804.54 with -2,350; `CF-FRUITS` -84,758.40 with -5,928; `CF-CHOCOLATE` -65,979.60 with -6,143.
  - Investigation concluded branch weakness was concentrated in fresh-food and grocery lines.

- `march_april_period_swing_dominated_year_change`
  - Baseline signal: April `revenue Growth` +2,112,426.17; March `revenue Growth` -2,043,504.72.
  - Temporal metadata flagged March as the worst month, with top special-product-group drags `IMPORTED FRUITS` -326,093.18, `SUN FLOWER OIL` -138,628.07, `IMPORTED VEGETABLES` -134,362.38.
  - DAX probe by `'MIS_DEEP_DIVE2'[product_group_name]` with `TREATAS({4}, 'MIS_DEEP_DIVE2'[month])` succeeded.
  - Top April product-group gains returned: `CF-FRESH CHICKEN & PARTS` +233,063.62 with `QTY Growth` +37,387 and `Bills Growth` +16,231; `CF-EDIBLE OILS` +217,244.10 with +8,261 Units and +8,906 bills; `CF-RICE` +212,921.52 with +7,318.67 Units and +5,119 bills; `CF-WATCHES` +124,199.92.
  - DAX probe by `'MIS_DEEP_DIVE2'[special_product_group_name]` for April succeeded.
  - Top April special-product-group gains returned: `VEGETABLE OIL` +286,917.65 with +15,187 Units and +13,309 bills; `BASMATI RICE` +157,385.32; `FRESH CHICKEN` +121,461.15; `FRESH CHICKEN PARTS` +111,602.47; `CHOCOLATE COATED BARS` +73,177.42 with `QTY Growth` -8,928.74776 and `Bills Growth` +2,188.
  - DAX probe by `'MIS_DEEP_DIVE2'[store_no]` for April succeeded: `CFH021` +1,019,128.89, `CFH014` +508,905.98, `CFH018` +364,771.51, `CFH017` +219,619.79.
  - March was not re-queried at the same detail in this investigation.

- `farm_fresh_and_fmcg_food_dominate_mix`
  - Reused investigation conclusion only; no additional DAX probe executed.
  - Baseline concentration signal: combined `net qty CURRENT` 13,644,163.0367, or 73.3331% of comparable Units; combined `net revenue CURRENT` SAR 70,216,044.13, or 55.8111% of comparable Revenue.
  - Reused evidence stated combined `revenue Growth` +SAR 903K, `QTY Growth` -429.5K, `bills growth` +63.7K.
  - Branch revenue contributions from reused evidence: `CFH021` +SAR 610K, `CFH018` +SAR 390K, `CFH014` +SAR 369K, `CFH017` -SAR 466K.
  - Reused evidence cited internal contributors: `CF-FRESH CHICKEN & PARTS` +SAR 1.11M; `CF-EDIBLE OILS` +SAR 444K; drags `CF-VEGETABLES` -SAR 516K, `CF-FRESH MEAT` -SAR 368K, `CF-FRUITS` -SAR 165K.

- `cfh014_and_cfh021_dominate_comparable_base`
  - Baseline concentration signal: `CFH014` and `CFH021` combined `net revenue CURRENT` 80,014,173.18, or 63.5991% of comparable Revenue; combined `net bills CURRENT` 5,298,461, or 63.5624% of comparable Transactions.
  - DAX probe by `'MIS_DEEP_DIVE2'[store_no]` and `'MIS_DEEP_DIVE2'[item_category_name]` for stores `CFH014`,`CFH021` succeeded.
  - Returned largest positive rows were mostly `CFH021`: `CF-MENS FASHION` +809,632.74; `CF-GROCERY FOOD` +591,962.81; `CF-ELECTRONICS` +583,327.77; `CF-PERSONAL CARE` +533,932.91; `CF-WATCHES & SUNGLASSES` +329,772.77; `CF-TOYS` +309,269.23.
  - `CFH014` visible positive rows included `CF-FRUIT & VEGETABLES` +160,685.08 with `QTY Growth` -13,240.87869 and `bills growth` +28,260; `CF-MEAT` +156,047.69; `CF-ROASTERY` +117,978.15.
  - `CFH014` visible negative rows included `CF-GROCERY FOOD` -133,839.74, `CF-HOME LINEN` -95,832.02, `CF-UTENSILS` -94,335.60.
  - Investigation noted this was not explicitly month-specific.

- `fresh_chicken_parts_and_chicken_supported_growth`
  - Baseline signal: `CF-FRESH CHICKEN & PARTS` `revenue Growth` +1,110,054.25; `QTY Growth` +188,331.0; `bills growth` +80,035.
  - Signal decomposition by Units: `volume_effect` +1,452,312.3763; `rate_effect` -342,258.1263; `rate_current` 7.1769 vs `rate_prior` 7.7115; reconciled true.
  - Signal decomposition by Transactions: `volume_effect` +1,138,184.6491; `rate_effect` -28,130.3991; `rate_current` 14.1345 vs `rate_prior` 14.2211; reconciled true.
  - Reused evidence gave branch revenue gains: `CFH014` +442.1K, `CFH018` +336.4K, `CFH021` +197.4K, `CFH017` +134.1K.
  - Reused evidence gave subgroup detail: `FRESH CHICKEN` +630.9K Revenue, +66,335 Units, +39,136 bills; `FRESH CHICKEN PARTS` +479.2K Revenue, +121,996 Units, +40,899 bills.

- `meat_growth_came_with_lower_average_value_per_item`
  - Baseline signal: `CF-MEAT` `revenue Growth` +742,310.17; `QTY Growth` +160,856.3733.
  - Signal decomposition by Units: `volume_effect` +1,914,104.9225; `rate_effect` -1,171,794.7525; `rate_current` 10.3846 vs `rate_prior` 11.8995; reconciled true.
  - Signal decomposition by Transactions: `volume_effect` +1,448,084.2244; `rate_effect` -705,774.0544; `rate_current` 19.1996 vs `rate_prior` 20.8865; reconciled true.
  - Reused evidence linked the increase mainly to `CF-FRESH CHICKEN & PARTS` +SAR 1.11M and +188.3K Units.
  - Reused evidence cited offsets from `CF-FRESH MEAT` -SAR 367.7K and -27.5K Units, including `FRESH MEAT BEEF` -SAR 162.1K and `FRESH MEAT MUTTON` -SAR 160.7K.
  - Branch growth from reused evidence: all four branches positive, led by `CFH018` +SAR 302.2K and `CFH021` +SAR 237.8K.

- `edible_oils_split_between_vegetable_oil_gain_and_sun_flower_oil_loss`
  - Baseline signal stated `VEGETABLE OIL` +670,411.93 Revenue and +22,520 bills; `SUN FLOWER OIL` -560,076.04 Revenue and -33,409 bills; `CF-EDIBLE OILS` +444,434.3 Revenue with `QTY Growth` -374.0, driven mainly by `rate_effect` +450,273.0507.
  - Signal decomposition for the positive `VEGETABLE OIL` movement: by Units `volume_effect` +398,239.8529 and `rate_effect` +272,172.0771; by Transactions `volume_effect` +340,079.3277 and `rate_effect` +330,332.6023.
  - DAX probe filtered to special groups `VEGETABLE OIL`, `SUN FLOWER OIL`, `OTHER COOKING OIL` and summarized by `'MIS_DEEP_DIVE2'[product_group_name]` succeeded.
  - Returned `CF-EDIBLE OILS` totals for that filtered set: `net revenue CURRENT` 5,291,260.27; `net revenue PAST` 4,979,447.06; `revenue Growth` +311,813.21; `QTY Growth` -6,437.0; `bills growth` -6,706.
  - DAX probe by `'MIS_DEEP_DIVE2'[store_no]` for `VEGETABLE OIL` and `SUN FLOWER OIL` succeeded: `CFH018` +104,028.41; `CFH014` +22,817.63; `CFH017` -1,065.53; `CFH021` -15,444.62.
  - Investigation conclusion noted the swing was concentrated mainly in `CFH018` and secondarily in `CFH014`.

- `cfh022_new_branch_revenue_is_material`
  - Baseline signal: `CFH022` `net revenue CURRENT` 11,906,055.96 and `net revenue PAST` 0.0.
  - Reused investigation conclusion only; no additional DAX probe executed.
  - Reused evidence listed leading categories: `CF-GROCERY FOOD` SAR 2.21M, `CF-FRUIT & VEGETABLES` SAR 1.13M, `Staples` SAR 1.06M, `CF-PERSONAL CARE` SAR 0.96M, `CF-CHILLED & DAIRY` SAR 0.83M.
  - Reused evidence listed leading product groups: `Rice` SAR 0.68M, `Fruits` SAR 0.62M, `Edible Oils` SAR 0.53M, `Vegetables` SAR 0.51M, `Chocolate` SAR 0.48M.
  - Reused evidence listed leading special-product groups including `Imported Fruits` SAR 0.51M and `Basmati Rice` SAR 0.33M.
  - No full-coverage breakdown was run; conclusion explicitly recommended a full decomposition.

# Confidence & Caveats
- CFH021 growth insight: high confidence. Supported by baseline branch totals, two reconciled breakdowns of the Revenue increase, and three successful drill-down queries by category, product group and special product group.
- Confectionery decline insight: medium confidence. The concentration and branch split were clearly stated in the concluded investigation, but no fresh drill query was run in this trail.
- FMCG FOOD insight: medium confidence. The conclusion was specific and internally consistent, including a quantified breakdown of Revenue versus Units, but it relied on reused evidence rather than new query output in this run.
- CFH017 drag insight: high confidence. Supported by baseline branch totals plus two successful drill-down queries showing the same pattern at category and product-group level.
- Fruit & Vegetables decline insight: medium confidence. The conclusion was detailed and branch-specific, but it came from reused evidence without fresh drill queries here.
- Fresh Chicken & Parts growth insight: medium confidence. The finding is supported by reconciled breakdowns and clear reused branch and subgroup evidence, but no new drill query was executed in this run.
- Meat mix-shift insight: medium confidence. The supplied breakdown strongly supports lower average revenue per item, and the reused investigation gives plausible contributors, but the underlying product-level query is not shown here.
- March-April swing insight: medium to high confidence. April was verified with three successful queries and the period series is complete, but March was not re-queried at matching detail, so the explanation for the swing remains partly indicative.
- Edible oils split insight: medium confidence. Supported by the baseline signal and two successful follow-up queries, but one verification query returned `CF-EDIBLE OILS` growth of SAR 311.8K for the filtered oil set, while the signal cited SAR 444.4K at full product-group level, so the narrower filter should not be treated as the whole category.
- Dominance of FARM FRESH and FMCG FOOD: medium confidence. The concentration is clear, but most contributor detail came from reused evidence and partial category coverage.
- Dominance of CFH014 and CFH021, with CFH021 more trend-setting: medium confidence. The concentration base is complete and the store-by-category query supports the pattern, but the evidence is not limited to the latest complete month.
- CFH022 new-branch Revenue insight: medium confidence. The existence and size of current-only Revenue are clear, but the category mix detail was reused and explicitly incomplete.
- General caveat: the coverage matrix marks several non-branch dimensions as partial rather than complete. That limits confidence that every relevant contributor was captured outside the explicitly complete branch and month views.
- No query failures were reported in the investigation probes shown here.

# Suggested Follow-ups
- Which categories made CFH021 outperform in the latest complete month, not just over the full available period? Run the same `store_no` by `item_category_name` split for the latest month only.
- What exactly drove the chocolate bar decline? Review `CHOCOLATE COATED BARS` at SKU or pack-size level by branch; this may require data outside the current model if SKU detail is not published here.
- Is FMCG FOOD’s Revenue growth coming from price changes or a shift in what sold? Compare item-level rates and mix inside `CF-CHOCOLATE` and `SUN FLOWER OIL`; separating pricing from mix may need SKU-level commercial data.
- Was CFH017’s decline a one-month break or a sustained issue? Run month-by-month category splits for `CF-FRUIT & VEGETABLES`, `CF-GROCERY FOOD` and `CF-MENS FASHION`.
- Are imported fruit and vegetable lines the main issue in Fruit & Vegetables? Compare `IMPORTED FRUITS`, `IMPORTED VEGETABLES`, `LOCAL FRUITS` and `LOCAL VEGETABLES` by branch and month.
- Did Fresh Chicken & Parts grow steadily or around specific trading periods? Check monthly branch-by-subgroup trends for `FRESH CHICKEN` and `FRESH CHICKEN PARTS`.
- Is the lower average value per item in Meat mainly a mix shift toward chicken? Compare item rates between chicken and fresh meat groups, ideally at product or SKU level.
- Did the March-April swing mainly reflect Ramadan and Eid timing? Re-run March and April side by side by `special_product_group_name`; confirming calendar effects may also need an external trading calendar.
- Why did Vegetable Oil gain while Sun Flower Oil lost? Compare branch-level SKU assortment, promotions and pack sizes for those two oil groups; promotion detail may require data outside this model.
- How much of total current sales depends on CFH021 and CFH014 in the latest complete month? Recalculate branch shares for the latest month so the summary reflects the most recent trend.
- What is the full mix of CFH022’s SAR 11.9M current Revenue? Run a full, not top-N, category/product-group/special-product-group breakdown for `CFH022`.