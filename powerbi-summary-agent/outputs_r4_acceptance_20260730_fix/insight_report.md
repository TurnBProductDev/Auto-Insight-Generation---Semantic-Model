# Key Insights
These comparisons include only branches with both current and last-year data: CFH014, CFH017, CFH018 and CFH021.

**CF-CONFECTIONERY sold 548.5K fewer units (12.4%), moving from 4.4M to 3.9M compared with the same period last year.** This was 176.5% of the final overall drop. The area-by-area names were not available, so this report cannot explain the above-100% result safely. This report does not have a complete product-and-branch ranking. Check CF-CONFECTIONERY by product and branch to find where the change happened.

**CFH021 revenue rose by 4.2M (11.4%), from 36.8M to 40.9M compared with the same period last year.** It made up 138.3% of the total increase in revenue. CFH021 moved farther than the final total because CFH017 fell by 1.3M and CFH014 fell by 224.1K, partly offset by CFH018 up 374.8K. Revenue per item rose 9.1%, from 5.96 to 6.50, adding 3.4M. Units sold rose by 128.8K (2.1%), from 6.2M to 6.3M, adding 767.7K. Transactions increased by 192,338 (7.6%), from 2.5M to 2.7M. Check GM FASHION and FASHION by month in CFH021.

**April revenue rose by 2.1M (14.0%), from 15.1M to 17.2M compared with the same period last year.** It made up 69.8% of the overall increase. This report does not have a complete product-and-branch ranking. Check April by product and branch to find where the change happened.

**CFH017 revenue fell by 1.3M (5.9%), from 22.2M to 20.9M compared with the same period last year.** It reduced the overall increase by 43.3%. Units sold fell by 220.0K (6.8%), from 3.2M to 3.0M. This reduced revenue by 1.5M. Revenue per item rose 1.0%, from 6.91 to 6.98. This added back 209.4K and made the decline smaller. Check CFH017 by product and branch to find where the change happened.

# Data Quality Watch-outs
- Product-group and category drill-downs were partial in this run, so smaller supporting areas may be missing from the ranked lists. Check whether the underlying detailed extracts were limited before using them as complete league tables.

# Evidence Trail
- CF-CONFECTIONERY units decline signal `confectionery_chocolate_units_drop`
  - Manager brief: units 3.9M vs 4.4M, change -548.5K, -12.4% vs the same period last year; contribution 176.5% of total units decline of -310.7K.
  - Manager brief shows offset from all other categories combined: +237.8K units. `other_area_breakdown` was unavailable, so the names of those offsetting categories could not be confirmed from the brief.
  - Investigation used direct conclusion only; no new DAX probes were executed in this run.
  - Investigation conclusion states CF-CHOCOLATE accounted for -548.1K units and CHOCOLATE COATED BARS for -473.5K units.
  - Investigation conclusion states branch pattern: CFH021 -261.8K units; CFH018 -155.5K; CFH014 -104.1K; CFH017 -27.1K.
  - Investigation conclusion states transactions for the category fell by 6.1K overall, with the largest transaction decline in CFH017; CFH014 and CFH018 had transaction growth.
  - Because no supporting DAX rows were executed in this run, the detailed branch and sub-group figures rely on the accepted investigation conclusion rather than fresh query output.

- CFH021 revenue growth signal `cfh021_growth_dominates`
  - Manager brief: revenue 40.9M vs 36.8M, change 4.2M, +11.4% vs the same period last year; contribution 138.3% of total 3.0M.
  - Other branch breakdown from manager brief: CFH018 +374.8K; CFH017 -1.3M; CFH014 -224.1K; net of other branches -1.2M; reconciled true.
  - Decomposition by Units: `QTY Growth` 6,295,859.3625 vs 6,167,052.198, change +128,807.1646 (+2.0886%); associated revenue change +767,716.4446 (18.3478%); revenue per unit 6.5029 vs 5.9602, change +9.1048%; associated revenue change +3,416,520.3754 (81.6522%); reconciled true.
  - Decomposition by Transactions: `bills growth` 2,707,761 vs 2,515,423, change +192,338 (+7.6463%); associated revenue change +2,810,557.7641 (67.1701%); revenue per purchase 15.1199 vs 14.6126, change +3.4717%; associated revenue change +1,373,679.0559 (32.8299%); reconciled true.
  - Product-group DAX drill for `MIS_DEEP_DIVE2[product_group_name]` in CFH021 succeeded. Top returned growth rows included CF-WATCHES +339,716.78, CF-MENS TOP WEAR +310,128.66, CF-RECHARGEABLE TORCH +244,669.81, CF-SKIN CARE +231,772.33, CF-MENS BOTTOMS +229,773.65, CF-FRESH CHICKEN & PARTS +195,379.97.
  - Month DAX drill for `MIS_DEEP_DIVE2[month]` in CFH021 succeeded. Returned: month 1 +1,165,393.34; month 2 +1,459,469.77; month 3 -506,266.33; month 4 +1,019,128.89; month 5 +959,453.19; month 6 -69,549.10; month 7 +156,607.06.
  - Investigation conclusion: growth was broad-based, stronger early in the year, and not a steady improvement every month.

- April revenue growth signal `cand_09_period_change_contribution`
  - Manager brief: April revenue 17.2M vs 15.1M, change 2.1M, +14.0% vs the same period last year; contribution 69.8% of total 3.0M.
  - Product-group DAX drill for April succeeded. Top returned rows included CF-FRESH CHICKEN & PARTS +233,063.62, CF-EDIBLE OILS +217,244.10, CF-RICE +212,921.52, CF-SKIN CARE +140,646.34, CF-WATCHES +124,199.92, CF-CHOCOLATE +94,271.02.
  - Same drill returned supporting quantity and transaction changes for those rows, including CF-FRESH CHICKEN & PARTS units +37,387 and transactions +16,231; CF-EDIBLE OILS units +8,261 and transactions +8,906; CF-RICE units +7,318.67 and transactions +5,119.
  - Branch DAX drill for April succeeded. Returned: CFH021 +1,019,128.89; CFH014 +508,905.98; CFH018 +364,771.51; CFH017 +219,619.79.
  - Investigation conclusion: April uplift was broad-based, concentrated in CFH021, and spread across several product groups rather than one isolated line.

- CFH017 revenue decline signal `cfh017_decline_drags_group`
  - Manager brief: revenue 20.9M vs 22.2M, change -1.3M, -5.9% vs the same period last year; effect on total change -43.3%.
  - Decomposition by Units: `QTY Growth` 2,997,270.1 vs 3,217,269.1739, change -219,999.0739 (-6.8381%); associated revenue change -1,519,556.4741 (115.9832%); revenue per unit 6.977 vs 6.9071, change +1.0115%; associated revenue change +209,404.4141 (-15.9832%); reconciled true.
  - Decomposition by Transactions: `bills growth` 1,318,259 vs 1,410,374, change -92,115 (-6.5312%); associated revenue change -1,451,374.3839 (110.7791%); revenue per purchase 15.8632 vs 15.7561, change +0.6799%; associated revenue change +141,222.3239 (-10.7791%); reconciled true.
  - Item-category DAX drill for `MIS_DEEP_DIVE2[item_category_name]` in CFH017 succeeded. Largest negative returned rows included CF-FRUIT & VEGETABLES revenue -306,364.81, units -75,782.86419, transactions -21,715; CF-GROCERY FOOD revenue -182,138.69, units -62,504.38826, transactions -16,687; CF-MENS FASHION revenue -160,596.86, units -7,276, transactions -4,389.
  - Product-group DAX drill for `MIS_DEEP_DIVE2[product_group_name]` in CFH017 succeeded. Largest negative returned rows included CF-VEGETABLES revenue -219,878.04, units -54,290.67926, transactions -15,672; CF-NUTS -104,118.87; CF-FRESH MEAT -91,849.71; CF-FRUITS -87,002.93.
  - Investigation conclusion: decline was broad-based and mainly tied to lower units and transactions, not lower revenue per item.

# Confidence & Caveats
- CF-CONFECTIONERY insight: medium confidence. The manager brief supports the size of the units decline, but no fresh DAX drill was run in this execution and no measured reason was confirmed.
- CFH021 insight: high confidence. Supported by the manager brief, two successful DAX drills, and reconciled decompositions by Units and Transactions.
- April insight: medium confidence. Supported by the manager brief and two successful DAX drills, but no exact decomposition was provided for Price, Basket Size, or Transactions at total-month level.
- CFH017 insight: high confidence. Supported by the manager brief, two successful DAX drills, and reconciled decompositions by Units and Transactions.
- Detailed product-group, item-category, and special-product-group coverage is marked partial in the coverage matrix, so returned ranked lists may not be exhaustive.
- No query failures were reported in the executed DAX steps for this run.
- The model’s transaction-based level figures can differ from true shopping-trip levels under company rules, so transaction growth is usable here, but basket level interpretations should be handled separately.

# Suggested Follow-ups
- CF-CONFECTIONERY: Which months and branches account for the 548.5K units decline? (Drill `MIS_DEEP_DIVE2[month]` and `MIS_DEEP_DIVE2[store_no]` for CF-CONFECTIONERY.)
- CF-CONFECTIONERY: Did chocolate lines, especially CHOCOLATE COATED BARS, lose sales because of range, stock, or promotions? (Needs more category detail in this model; stock and promotion confirmation would need data outside this model.)
- CFH021: Which months and product groups inside CFH021 produced the 4.2M increase, and did revenue per item or units carry each gain? (Drill `MIS_DEEP_DIVE2[month]` by `division_name`, `item_category_name`, and `product_group_name` for CFH021.)
- CFH021: Did GM FASHION and FASHION gains come from pricing, mix of products sold, or more items sold? (Needs a deeper category drill in this model; margin would need data outside this model.)
- April: Was April’s 2.1M increase mainly a seasonal shift or a sustained improvement? (Compare April with March and May by branch and category in this model; holiday calendar interpretation needs business context outside the model.)
- April: Which April gains remained visible in the latest month? (Run month-by-month follow-up by branch and product group within the comparable branches.)
- CFH017: Which months caused the 1.3M decline in CFH017, and did the weakness persist into the latest month? (Drill `MIS_DEEP_DIVE2[month]` for CFH017 by `item_category_name` and `product_group_name`.)
- CFH017: Were stock availability, range changes, or local promotions behind the lower sales in Fruit & Vegetables and Grocery Food? (Stock and promotion checks need data outside this model.)