# Key Insights
These comparisons include only branches with both current and last-year data: ST1, ST2, ST3, ST4 and ST5.

**ST5 revenue rose by 2.6M (456.4%), from 577.7K to 3.2M compared with the same period last year.** It made up 73.0% of the overall increase. Units sold rose by 1.7M (450.8%), from 383.6K to 2.1M. This added 2.6M to revenue. Revenue per item rose 1.0%, from 1.51 to 1.52. This added 32.2K to the gain. Check ST5 by product and branch to find where the change happened.

**CONSUMER GOODS revenue rose by 2.1M (10.3%), from 20.0M to 22.0M compared with the same period last year.** It made up 56.9% of the overall increase. Units sold rose by 927.3K (6.4%), from 14.5M to 15.4M. This added 1.3M to revenue. Revenue per item rose 3.7%, from 1.38 to 1.43. This added 781.6K to the gain. Check CONSUMER GOODS by product and branch to find where the change happened.

**ST4 revenue rose by 1.2M (10.8%), from 11.2M to 12.4M compared with the same period last year.** It made up 33.2% of the overall increase. Units sold rose by 77.0K (1.1%), from 6.9M to 7.0M. This added 124.1K to revenue. Revenue per item rose 9.5%, from 1.61 to 1.77. This added 1.1M to the gain. Check ST4 by product and branch to find where the change happened.

**PROVISIONS revenue rose by 950.0K (9.5%), from 10.0M to 10.9M compared with the same period last year.** It made up 26.3% of the overall increase. Units sold rose by 279.2K (3.0%), from 9.2M to 9.5M. This added 302.1K to revenue. Revenue per item rose 6.3%, from 1.08 to 1.15. This added 647.9K to the gain. Check PROVISIONS by product and branch to find where the change happened.

# Data Quality Watch-outs
- Some supporting detail is incomplete because several hierarchy views returned only partial top rows. Check whether the report owner can extract full ranked outputs for item, product and special product groups.
- The labels PROVISIONS, REFRIDGERATED GOODS and PERSONAL CARE could not be confirmed inside the CONSUMER GOODS drill. Check how those business labels map to the available hierarchy members before using them as exact sub-division totals.
- PROVISIONS shows a fall in revenue per purchase, but the percentage display is labelled as positive in the manager-ready output. Check the sign handling for that percentage label.

# Evidence Trail
- ST5 store finding `st5_drove_comparable_growth`
  - Baseline signal: ST5 `revenue Growth` = 2,636,901.4428, from `net revenue PAST` 577,733.6664 to `net revenue CURRENT` 3,214,635.1092; share of total = 72.9561%.
  - Decomposition by `QTY Growth`: `net qty PAST` 383,603.204 to `net qty CURRENT` 2,113,071.8729, change 1,729,468.6689; `volume_effect` 2,604,702.6317 and `rate_effect` 32,198.8111; reconciled = true.
  - Decomposition by `bills growth`: 144,551 to 794,252, change 649,701; `volume_effect` 2,596,690.0318 and `rate_effect` 40,211.4110; reconciled = true.
  - Probe on `'MIS_DEEP_DIVE2'[item_category_name]` for ST5 succeeded. Largest returned `revenue Growth` rows included PROVISIONS 876,324.6306, REFRIDGERATED GOODS 334,497.1437, GREEN GROCERIES 290,223.3321, PERSONAL CARE 223,411.0599, SPICE MARKET 165,923.4780.
  - Same probe showed corresponding ST5 growth in quantity and bills, including PROVISIONS `QTY Growth` 798,386.74246 and `bills growth` 231,946; REFRIDGERATED GOODS `QTY Growth` 388,079.975 and `bills growth` 100,439.
  - Probe on `'MIS_DEEP_DIVE2'[product_group_name]` for ST5 succeeded but returned partial top rows only. Largest visible rows included SNACKS 37,270.2033, BISCUITS 35,210.9673, WASHING DETERGENT 40,854.2157, INSTANT DRINKS 32,288.7222.
  - Probe on `'MIS_DEEP_DIVE2'[special_product_group_name]` for ST5 succeeded but returned partial top rows only. Visible rows included SOAP 50,028.9399, WASHING POWDER FRONT LOAD 40,854.2157, MASALA 31,313.5092, POTATO CHIPS 26,357.8320, FRESH MILK 27,888.3567.
  - Investigation explanation references COVRD CHOCO BARS AND TAB at 71,319.5388 revenue growth, 279,292.08325 quantity growth and 13,950 bills growth, but that row was not present in the returned probe rows shown here.
  - Conclusion status: accepted.

- CONSUMER GOODS division finding `consumer_goods_dominates_division_results`
  - Baseline signal: CONSUMER GOODS `revenue Growth` = 2,057,807.4354, from `net revenue PAST` 19,965,011.6358 to `net revenue CURRENT` 22,022,819.0712; share of total = 56.9341%.
  - Decomposition by `QTY Growth`: 14,507,537.5504 to 15,434,856.5801, change 927,319.0296; `volume_effect` 1,276,159.7309 and `rate_effect` 781,647.7045; reconciled = true.
  - Decomposition by `bills growth`: 4,924,987 to 5,426,505, change 501,518; `volume_effect` 2,033,063.7838 and `rate_effect` 24,743.6516; reconciled = true.
  - No new DAX drill was run in this investigation; accepted by reuse of prior evidence.
  - Investigation explanation states visible category or subgroup contributors included COOKING OILS 257,788.4184, FRESH DAIRY 192,067.4349, HEALTH AND BEAUTY CARE 189,742.9698, RICE 163,753.7013; and special-product-group contributors COOKING OILS 333,439.2081, SNACKS 139,218.4044, BASMATI RICE 119,043.1971.
  - Investigation explanation also states ST5 contributed 1,658,253.8511 of CONSUMER GOODS growth, about 80.6% of the division increase.
  - Investigation explanation notes PROVISIONS, REFRIDGERATED GOODS and PERSONAL CARE were not confirmed as available dimension values in the reused rows.
  - Conclusion status: accepted.

- ST4 store finding `st4_revenue_growth_led_by_higher_revenue_per_unit`
  - Baseline signal: ST4 `revenue Growth` = 1,201,105.5543, from `net revenue PAST` 11,154,890.3004 to `net revenue CURRENT` 12,355,995.8547; share of total = 33.2314%.
  - Decomposition by `QTY Growth`: `net qty PAST` 6,919,700.7812 to `net qty CURRENT` 6,996,660.7501, change 76,959.9689; `volume_effect` 124,063.1694 and `rate_effect` 1,077,042.3849; reconciled = true.
  - Decomposition by `bills growth`: 2,841,926 to 3,032,568, change 190,642; `volume_effect` 748,292.0374 and `rate_effect` 452,813.5169; reconciled = true.
  - Probe on `'MIS_DEEP_DIVE2'[item_category_name]` for ST4 succeeded. Largest returned positive `revenue Growth` rows included PERSONAL CARE 190,096.6725, LADIES APPAREL 186,022.2429, ENTERTAINMENTS 175,587.4287, PROVISIONS 134,805.9294, TOYS 85,895.4645.
  - Same probe showed mixed quantity patterns: PROVISIONS `QTY Growth` -134,115.66752 with positive `revenue Growth` 134,805.9294; CLEANING ESSENSTIALS `QTY Growth` -1,459 with positive `revenue Growth` 10,957.1589.
  - Probe on `'MIS_DEEP_DIVE2'[product_group_name]` for ST4 succeeded but returned partial top rows only. Visible rows included HOME LINEN PRODUCTS 37,437.2037, BROUGHT IN BREAD AND CAKES 17,052.1308, LONG LIFE DAIRY PRODUCTS 15,066.8532, BISCUITS 15,299.3205.
  - Investigation explanation concludes the strongest evidenced answer is at item-category level because product-group output was truncated.
  - Conclusion status: accepted.

- PROVISIONS category finding `provisions_large_category_gain_with_rate_pressure_per_bill`
  - Baseline signal: PROVISIONS `revenue Growth` = 950,001.9579, from `net revenue PAST` 9,956,122.4952 to `net revenue CURRENT` 10,906,124.4531; share of total = 26.2841%.
  - Decomposition by `QTY Growth`: 9,201,066.6754 to 9,480,274.3206, change 279,207.6452; `volume_effect` 302,119.9188 and `rate_effect` 647,882.0391; reconciled = true.
  - Decomposition by `bills growth`: 2,435,421 to 2,701,866, change 266,445; `volume_effect` 1,089,240.4468 and `rate_effect` -139,238.4889; reconciled = true.
  - No new DAX drill was run in this investigation; accepted by reuse of prior evidence.
  - Investigation explanation states product-group contributors included COOKING OILS 257,788.4184 with 17.1K more bills and 29.7K more quantity, RICE 163,753.7013 with 17.8K more bills and 34.9K more quantity, ETHNIC FOODS 99.6K with 35.4K more bills and 52.2K more quantity.
  - Investigation explanation states special-product-group contributors included COOKING OILS 333,439.2081 with 37.2K more bills and BASMATI RICE 119,043.1971 with 19.0K more bills.
  - Investigation explanation states store concentration was high: ST5 contributed 876.3K of the 950.0K PROVISIONS increase, with 231.9K of the 266.4K bills increase and 798.4K of the 279.2K quantity increase; ST1 and ST2 declined.
  - Manager fact brief for transactions shows `rate_change_pct` raw value -1.2606 but display string "1.3%", indicating a sign-label issue in the supplied brief.
  - Conclusion status: accepted.

- Shared scope and coverage
  - `resolved_entity_scope.active_comparable_population` = ST4, ST1, ST3, ST2, ST5; `excluded_from_comparison` = none; `new_entities` = none; `prior_only_entities` = none.
  - `temporal.reason`: no valid business time axis found; sub-annual monitoring disabled because only a load/posting-date column exists.
  - Coverage matrix marks `'MIS_DEEP_DIVE2'[store_no]` as trusted and complete/partial depending on query; division, item category, product group and special product group coverage are partial, with product and special product group not trusted for full coverage.

# Confidence & Caveats
- ST5 insight: high confidence on the size of the increase and the unit-driven breakdown, supported by the baseline signal plus three successful drills. Confidence is lower on the exact special product group ranking because the returned rows were partial.
- CONSUMER GOODS insight: moderate confidence on the division increase and its transaction-led profile from the manager brief and baseline signal. Confidence is lower on named internal contributors because this investigation relied on reused evidence and did not run a fresh drill here.
- ST4 insight: high confidence on the store increase and the stronger revenue-per-item contribution, supported by the baseline signal and two successful drills. Confidence is moderate on which lower levels explain it because the product-group output was truncated.
- PROVISIONS insight: moderate confidence on the category increase and the fall in revenue per purchase, supported by reconciled decomposition. Confidence is lower on the exact lines behind that pressure because the investigation reused prior evidence and no fresh drill was run in this step.
- General limits: hierarchy coverage is partial for division, item category, product group and special product group. No daily or weekly analysis was available, and load-date fields were not used for trading-period interpretation.

# Suggested Follow-ups
- For ST5: Which `special_product_group_name` members account for most of ST5's 2.6M increase, and what are their current, prior and change values for revenue, quantity and transactions?
- For ST5: Which ST5 categories had the largest changes in revenue per item versus items purchased per transaction?
- For CONSUMER GOODS: Which exact `item_category_name` and `product_group_name` members inside CONSUMER GOODS contributed most to the 2.1M increase?
- For CONSUMER GOODS: How do the business labels PROVISIONS, REFRIDGERATED GOODS and PERSONAL CARE map to the available model hierarchy members before reporting sub-division contributors?
- For ST4: Which `special_product_group_name` members inside ST4 PROVISIONS and PERSONAL CARE had the largest increases in revenue per item?
- For ST4: Where did revenue rise while quantity fell inside ST4, and was that pattern concentrated in a few lines or spread widely?
- For PROVISIONS: Which `product_group_name` or `special_product_group_name` members had lower revenue per purchase than last year while transactions increased?
- For PROVISIONS: Which stores besides ST5 reduced the category result, and which PROVISIONS lines explain those declines?
- Outside this model: Were there assortment, pricing, or operational changes by store that align with these movements? That would need source data beyond the sales model.