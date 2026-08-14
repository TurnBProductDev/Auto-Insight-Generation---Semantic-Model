# Key Insights
These findings use the comparable store group CFH014, CFH017, CFH018, and CFH021 unless noted otherwise.

**CFH021 revenue increased by about 4.3M.** This store delivered about 123.8% of the net revenue increase across the group, so its growth more than offset declines elsewhere. The increase came from more transactions and higher average revenue per unit. Mens fashion, grocery food, electronics, and personal care were the largest contributors, with added support from watches and selected oil lines. Compare CFH021 with CFH014, CFH017, and CFH018 to confirm whether the gap came mainly from pricing, assortment, or basket composition.

**April revenue increased by about 2.1M.** April contributed about 60.9% of the total increase after March declined by about 2.0M. The rebound was concentrated in edible oils, rice, and fresh chicken-related lines, and those areas also showed positive unit growth. March weakness was concentrated in imported fruits, sun flower oil, and imported vegetables rather than spread evenly across products. Compare March and April for these lines to confirm whether April reflects recovery or separate strength.

**CF-FRESH CHICKEN & PARTS revenue increased by about 1.1M.** This group contributed about 31.9% of the total revenue increase. The gain came mainly from selling more units and more transactions, although average revenue per unit declined. Growth was positive in all four comparable stores and across both fresh chicken and fresh chicken parts. Review price and sales mix changes within fresh chicken versus fresh chicken parts, especially in CFH014 and CFH018.

**CF-MEAT revenue increased by about 742K.** This category added about 21.4% of the total revenue increase. The gain came mainly from more units and more transactions, although average revenue per unit and per transaction declined. Fresh chicken and parts drove the increase, while fresh meat declined and partly offset it. Check whether pricing or the mix of products sold in chicken versus beef and mutton explains the lower average revenue levels.

**FMCG FOOD quantity declined by about 364.6K units while revenue increased by about 714K.** The revenue increase happened alongside about 37.3K more transactions. Our checks suggest the gain came mainly from stronger higher-revenue lines such as vegetable oil, edible oils, and dairy and desserts, while chocolate and sun flower oil pulled volume down. This pattern is associated with higher average revenue per unit rather than broad unit growth. Review revenue per unit by FMCG FOOD product group to confirm the effect.

**CF-FRUIT & VEGETABLES revenue declined by about 678K.** The drop was driven mainly by about 214.0K fewer units sold, even though average revenue per unit was higher. The weakness was concentrated in vegetables and imported lines, with the largest store declines in CFH017, CFH021, and CFH018, while CFH014 grew. This suggests the shortfall was concentrated in selected stores and products rather than evenly spread. Check imported and local produce mix and in-stock coverage in the weaker stores versus CFH014.

**SUN FLOWER OIL revenue declined by about 559K.** The drop came with about 43.3K fewer units and about 33.3K fewer transactions. Our checks showed declines in all four comparable stores, led by CFH014 and CFH021, while average revenue per unit increased. This suggests weaker customer purchasing frequency and volume, partly offset by a higher realized unit rate. Review availability, promotions, and stock position for sun flower oil in CFH014 and CFH021.

**CF-EDIBLE OILS revenue increased by about 449K.** Units were nearly flat and transactions were lower, so the increase came mainly from higher average revenue per unit and per transaction. Our checks showed gains in vegetable oil, other cooking oil, and olive oil, partly offset by the decline in sun flower oil. The uplift was broad-based across all four comparable stores. Check SKU pricing, pack-size mix, and promotions across edible oils, especially vegetable oil versus sun flower oil.

**CF-CONFECTIONERY quantity declined by about 529.6K units.** This represented about 222.1% of the total unit decline because gains in other areas partly offset it. The drop was almost entirely concentrated in chocolate, especially chocolate coated bars, and the largest store declines were in CFH021 and CFH018. Transactions also declined, suggesting weaker shopping activity as well as lower unit movement in that bar segment. Investigate SKU and pack-format performance in chocolate coated bars for CFH021 and CFH018.

**CFH017 revenue declined by about 1.2M.** This store accounted for about 35.3% of the total revenue decrease across the comparable group. The decline came mainly from fewer units and fewer transactions, while average revenue per unit improved slightly. The largest shortfalls were in fruit and vegetables, grocery food, mens fashion, personal care, and electronics, partly offset by frozen food and meat. Check fruit and vegetables and grocery food in CFH017 to identify the specific groups behind the shortfall.

**FARM FRESH and FMCG FOOD currently account for about 13.6M units.** Together they make up about 73.3% of current units in the comparable group, along with large shares of transactions and revenue. FMCG FOOD contributes most of that combined unit base and most of the recent unit decline between the two divisions. This means recent quantity softness appears more associated with FMCG FOOD than with FARM FRESH. Check a division-by-product breakdown to separate which groups are driving each division.

**CFH014 and CFH021 currently account for about 79.8M of revenue.** Together they represent about 63.6% of current revenue in the comparable store base, as well as similar shares of current transactions and units. The available checks suggest this concentration is linked to large grocery food, personal care, fruit and vegetables, skin care, vegetables, and edible oils businesses in the pair. Some supporting category views were partial, so the exact split by group is not complete. Check a full store-by-category breakdown without row limits to quantify each group's exact share.

**CFH022 currently records about 11.9M of revenue with no prior-period history.** It also has current quantity and transactions but zero prior-period values in the store scope scan. Our checks suggest this is broad-based current trading rather than a single-category spike, so it should not be read as year-over-year growth. The main evidenced contributor is broad sales across grocery food, fruit and vegetables, staples, and personal care rather than one isolated line. Confirm whether CFH022 is newly opened, newly onboarded, remapped, or missing prior-period data.

# Data Quality Watch-outs
- CFH022 appears as a current-only store rather than a normal year-over-year movement. Our checks showed about 11.9M in current revenue with zero prior-period revenue, quantity, and transactions, so verify whether this store is newly opened, newly onboarded, remapped, or missing prior-period history before using it in performance comparisons.
- Several supporting breakdowns are incomplete because product, item-category, and special-product-group coverage is marked partial or untrusted in the model scan. Our checks relied on top-returned rows in those areas, so verify whether any material categories sit outside the returned rows before treating concentration findings as exhaustive.

# Evidence Trail
- `cfh021_dominates_comparable_growth`
  - Baseline comparable entities identified `CFH014`, `CFH017`, `CFH018`, `CFH021` as the active comparable population; signal value `revenue Growth = 4,296,708.76` for `CFH021`, `impact_share = 123.8455`.
  - Decomposition by `QTY Growth`: revenue change `4,296,708.76` split into `volume_effect = 901,441.3646` and `rate_effect = 3,395,267.3954`; rate moved from `5.9624` to `6.5033`; reconciled.
  - Decomposition by `bills growth`: revenue change `4,296,708.76` split into `volume_effect = 2,944,010.0732` and `rate_effect = 1,352,698.6868`; revenue per bill moved from `14.6204` to `15.1215`; reconciled.
  - DAX by `'MIS_DEEP_DIVE2'[item_category_name]` for `store_no = CFH021` returned top revenue growers including `CF-MENS FASHION +808,680.65`, `CF-GROCERY FOOD +594,022.42`, `CF-ELECTRONICS +582,879.02`, `CF-PERSONAL CARE +534,583.50`, `CF-WATCHES & SUNGLASSES +328,775.93`, `CF-TOYS +309,406.24`.
  - Same query showed supporting transaction growth in major categories, including `CF-GROCERY FOOD bills growth +47,764`, `CF-MENS FASHION +37,065`, `CF-PERSONAL CARE +22,902`.
  - DAX by `'MIS_DEEP_DIVE2'[product_group_name]` returned top product groups including `CF-WATCHES +341,613.59`, `CF-MENS TOP WEAR +310,896.53`, `CF-RECHARGEABLE TORCH +245,237.70`, `CF-SKIN CARE +236,458.05`, `CF-FRESH CHICKEN & PARTS +196,497.88`, `CF-EDIBLE OILS +127,920.35`.
  - DAX by `'MIS_DEEP_DIVE2'[special_product_group_name]` returned contributors including `HAND TORCH +226,612.35`, `VEGETABLE OIL +198,738.30`, `MENS WATCH +183,188.17`, `FRESH CHICKEN +128,639.96`, `LADIES SMART WATCHES +117,680.36`.
  - Investigation concluded after 3 successful DAX queries.

- `monthly_revenue_swings_centered_in_april_and_march`
  - Month-series signal showed `April revenue Growth = 2,112,426.17` (`60.8872%` of reconciled total) and `March = -2,043,504.72` (`-58.9006%`); January `+1,747,127.27`, February `+1,736,824.44`.
  - Temporal worst-period drill identified March top negative special-product groups as `IMPORTED FRUITS -326,093.18`, `SUN FLOWER OIL -138,628.07`, `IMPORTED VEGETABLES -134,362.38`.
  - DAX by `'MIS_DEEP_DIVE2'[product_group_name]` for `month = 4` and comparable stores returned top April growers including `CF-FRESH CHICKEN & PARTS +233,063.62`, `CF-EDIBLE OILS +217,244.10`, `CF-RICE +212,921.52`, `CF-SKIN CARE +140,646.34`, `CF-WATCHES +124,199.92`, `CF-CHOCOLATE +94,271.02`.
  - Same April query showed positive quantity growth for these groups, including `CF-FRESH CHICKEN & PARTS +37,387`, `CF-EDIBLE OILS +8,261`, `CF-RICE +7,318.67`.
  - DAX by `'MIS_DEEP_DIVE2'[special_product_group_name]` for `month = 4` and comparable stores returned `VEGETABLE OIL +286,917.65`, `BASMATI RICE +157,385.32`, `FRESH CHICKEN +121,461.15`, `FRESH CHICKEN PARTS +111,602.47`, `MENS WATCH +76,939.75`.
  - Investigation concluded after 2 successful DAX queries.

- `fresh_chicken_parts_group_growth_with_rate_pressure`
  - Signal reported `revenue Growth = 1,108,089.71`, `impact_share = 31.9388`, `QTY Growth = 188,093`, `bills growth = 79,941`.
  - Decomposition by `QTY Growth`: revenue change `1,108,089.71` split into `volume_effect = 1,451,286.2538` and `rate_effect = -343,196.5438`; revenue per unit moved from `7.7158` to `7.1778`; reconciled.
  - Decomposition by `bills growth`: revenue change `1,108,089.71` split into `volume_effect = 1,137,149.8353` and `rate_effect = -29,060.1253`; revenue per bill moved from `14.2249` to `14.1351`; reconciled.
  - Reused investigation evidence showed positive revenue growth across all comparable stores: `CFH014 +441,690.95`, `CFH018 +336,109.87`, `CFH021 +196,497.88`, `CFH017 +133,791.01`.
  - Reused evidence also showed special-product subgroups `FRESH CHICKEN +629,357.23` and `FRESH CHICKEN PARTS +478,732.48`.
  - No additional DAX executed; investigation concluded from reused evidence.

- `meat_growth_driven_by_volume_with_lower_rate`
  - Signal reported `revenue Growth = 742,010.12`, `impact_share = 21.3872`, `QTY Growth = 160,709.8193`, `bills growth = 69,255`.
  - Decomposition by `QTY Growth`: revenue change `742,010.12` split into `volume_effect = 1,913,706.8492` and `rate_effect = -1,171,696.7292`; revenue per unit moved from `11.9078` to `10.3878`; reconciled.
  - Decomposition by `bills growth`: revenue change `742,010.12` split into `volume_effect = 1,447,089.4134` and `rate_effect = -705,079.2934`; revenue per bill moved from `20.8951` to `19.2041`; reconciled.
  - Reused evidence showed growth concentrated in `CF-FRESH CHICKEN & PARTS +1,108,089.71` with `QTY Growth +188,093` and `bills growth +79,941`, offset by `CF-FRESH MEAT -366.1K`.
  - Reused evidence cited special-product groups `FRESH CHICKEN +629.4K` and `FRESH CHICKEN PARTS +478.7K`, offset by declines in beef and mutton lines.
  - Reused store split showed all four comparable stores positive, led by `CFH018 +302.0K` and `CFH021 +236.2K`.
  - No additional DAX executed; investigation concluded from reused evidence.

- `fmcg_food_volume_down_revenue_still_up`
  - Signal reported `QTY Growth = -364,641.2883`, `impact_share = 152.8766`, `revenue Growth = 713,542.89`, `bills growth = 37,336`.
  - Investigation explanation cited store decomposition: `CFH021 +557.2K revenue`, `QTY Growth -61.9K`, `bills growth +38.8K`; `CFH018 +336.9K revenue`, `QTY Growth -66.0K`, `bills growth +45.6K`; `CFH014` nearly flat revenue with `QTY Growth -149.2K`; `CFH017` down in both revenue and volume.
  - Reused evidence within FMCG FOOD identified major negative quantity contributors `CF-CHOCOLATE -529.2K units` with `revenue Growth -100.4K`, and `SUN FLOWER OIL -43.3K units` with `revenue Growth -558.9K`.
  - Offsetting reused contributors included `VEGETABLE OIL +675.3K revenue`, `+30.8K units`; `CF-EDIBLE OILS +448.7K revenue`; `CF-DAIRY & DESSERTS +315.9K revenue`, `+51.6K units`.
  - No additional DAX executed; investigation concluded from reused evidence.

- `fruit_and_vegetables_decline_in_revenue_and_volume`
  - Signal reported `revenue Growth = -677,690.02`, `impact_share = -19.5333`, `QTY Growth = -213,974.2031`.
  - Decomposition by `QTY Growth`: revenue change `-677,690.02` split into `volume_effect = -995,131.6133` and `rate_effect = 317,441.5933`; revenue per unit moved from `4.6507` to `4.7687`; reconciled.
  - Decomposition by `bills growth`: revenue change `-677,690.02` split into `volume_effect = -107,396.3683` and `rate_effect = -570,293.6517`; revenue per bill moved from `7.88` to `7.5446`; reconciled.
  - Reused evidence by product group showed `CF-VEGETABLES -514.6K revenue`, `QTY Growth -139.2K`; `CF-FRUITS -160.4K revenue`, `QTY Growth -74.5K`.
  - Reused evidence by special-product group showed `IMPORTED VEGETABLES -313.5K`, `IMPORTED FRUITS -284.1K`, `LOCAL VEGETABLES -211.2K`, partly offset by `LOCAL FRUITS +123.7K`.
  - Reused store split showed `CFH017 -301.2K`, `CFH021 -274.9K`, `CFH018 -264.9K`, partly offset by `CFH014 +163.2K`.
  - No additional DAX executed; investigation concluded from reused evidence.

- `sun_flower_oil_decline`
  - Signal reported `revenue Growth = -558,877.87`, `impact_share = -16.1087`, `QTY Growth = -43,321`, `bills growth = -33,323`.
  - Decomposition by `QTY Growth`: revenue change `-558,877.87` split into `volume_effect = -786,257.3594` and `rate_effect = 227,379.4894`; revenue per unit moved from `18.1496` to `20.058`; reconciled.
  - Decomposition by `bills growth`: revenue change `-558,877.87` split into `volume_effect = -704,219.9918` and `rate_effect = 145,342.1218`; revenue per bill moved from `21.1332` to `22.5016`; reconciled.
  - DAX by `'MIS_DEEP_DIVE2'[store_no]` for `special_product_group_name = SUN FLOWER OIL` and comparable stores returned: `CFH014 revenue Growth -218,699.29`, `QTY Growth -19,576`, `bills growth -14,841`; `CFH021 -211,664.84`, `QTY Growth -12,255`, `bills growth -10,191`; `CFH018 -72,835.14`; `CFH017 -55,678.60`.
  - Reused evidence noted that the segment maps entirely to one visible item category `CF-GROCERY FOOD` and one product group `CF-EDIBLE OILS` in this model.
  - Investigation concluded after 1 successful DAX query.

- `edible_oils_revenue_up_without_volume_gain`
  - Signal reported `revenue Growth = 448,691.84`, `impact_share = 12.9328`, `QTY Growth = 137`, `bills growth = -1,940`.
  - Decomposition by `QTY Growth`: revenue change `448,691.84` split into `volume_effect = 2,139.4881` and `rate_effect = 446,552.3519`; revenue per unit moved from `15.6167` to `16.8493`; reconciled.
  - Decomposition by `bills growth`: revenue change `448,691.84` split into `volume_effect = -35,303.2164` and `rate_effect = 483,995.0564`; revenue per bill moved from `18.1975` to `19.7647`; reconciled.
  - Reused evidence by special-product group showed `VEGETABLE OIL +675.3K`, `OTHER COOKING OIL +199.1K`, `OLIVE OIL +65.2K`, offset by `SUN FLOWER OIL -558.9K`.
  - Reused store split showed broad-based gains: `CFH018 +159.4K`, `CFH014 +141.3K`, `CFH021 +127.9K`, `CFH017 +20.1K`.
  - Reused evidence stated that item-category drill does not add detail because `CF-EDIBLE OILS` sits entirely within `CF-GROCERY FOOD` in this model.
  - No additional DAX executed; investigation concluded from reused evidence.

- `confectionery_chocolate_volume_decline`
  - Signal reported `QTY Growth = -529,636.4292`, `impact_share = 222.0511`.
  - Reused evidence showed segment quantity moved from `4.39M` to `3.86M`.
  - Reused evidence localized the decline to `product_group_name = CF-CHOCOLATE` with `QTY Growth -529.2K`, and mainly `special_product_group_name = CHOCOLATE COATED BARS` with `QTY Growth -458.7K`.
  - Reused store breakdown identified largest quantity declines in `CFH021 -254.6K`, `CFH018 -150.0K`, `CFH014 -100.9K`, `CFH017 -24.2K`.
  - Reused evidence also noted `bills growth = -5,139` for the segment overall and `bills growth = -1,606` for `CHOCOLATE COATED BARS`.
  - No additional DAX executed; investigation concluded from reused evidence.

- `cfh017_decline_across_revenue_qty_and_bills`
  - Signal reported `revenue Growth = -1,223,427.93`, `impact_share = -35.2633`, `QTY Growth = -206,845.8959`, `bills growth = -86,580`.
  - Decomposition by `QTY Growth`: revenue change `-1,223,427.93` split into `volume_effect = -1,429,308.8521` and `rate_effect = 205,880.9221`; revenue per unit moved from `6.91` to `6.979`; reconciled.
  - Decomposition by `bills growth`: revenue change `-1,223,427.93` split into `volume_effect = -1,364,596.4402` and `rate_effect = 141,168.5102`; revenue per bill moved from `15.7611` to `15.8686`; reconciled.
  - DAX by `'MIS_DEEP_DIVE2'[item_category_name]` for `store_no = CFH017` returned largest negative categories: `CF-FRUIT & VEGETABLES -301,160.19`, `QTY Growth -74,434.78919`, `bills growth -20,975`; `CF-GROCERY FOOD -169,788.55`, `QTY Growth -60,088.34826`, `bills growth -15,674`; `CF-MENS FASHION -157,901.26`, `QTY Growth -7,101`, `bills growth -4,243`; `CF-PERSONAL CARE -103,905.29`; `CF-ELECTRONICS -94,270.16`; `CF-CONFECTIONERY -65,992.30`.
  - Same DAX showed offsets from `CF-FROZEN FOOD +177,920.37` and `CF-MEAT +46,021.03`.
  - Investigation concluded after 1 successful DAX query.

- `farm_fresh_fmcg_food_dominate_comparable_base`
  - Signal reported combined current concentration: `net qty CURRENT = 13,600,365.1784` (`73.3231%` of comparable total), `net bills CURRENT = 5,530,716` (`66.5602%`), `net revenue CURRENT = 69,997,402.04` (`55.8017%`).
  - Reused evidence split combined quantity approximately into `FMCG FOOD 10.00M` and `FARM FRESH 3.60M`; recent quantity decline approximately `FMCG FOOD -364.6K` versus `FARM FRESH -57.5K`.
  - Reused store contributions to combined current quantity were approximately `CFH021 4.40M`, `CFH014 3.93M`, `CFH018 2.91M`, `CFH017 2.36M`; largest quantity decline approximately `CFH017 -145.5K`.
  - Reused evidence cited large product groups inside the pair such as `CF-CHOCOLATE 3.86M qty`, `CF-VEGETABLES 1.64M`, `CF-FRUITS 1.05M`, `CF-BEVERAGES-COLD 0.90M`.
  - Investigation explicitly noted the model did not provide a direct `division_name` by `product_group_name` split from the bundled evidence, so attribution of exact subcategories to each division remained incomplete.

- `cfh014_cfh021_concentrate_store_base`
  - Signal reported combined current concentration for `CFH014` and `CFH021`: `net revenue CURRENT = 79,767,474.21` (`63.5904%` of comparable total), `net bills CURRENT = 5,281,348` (`63.5592%`), `net qty CURRENT = 11,639,592.743` (`62.752%`).
  - Reused evidence cited large current item categories within the two-store pair including `CF-GROCERY FOOD 10.58M`, `CF-PERSONAL CARE 9.54M`, `CF-FRUIT & VEGETABLES 8.91M`.
  - Reused evidence cited large product groups including `CF-VEGETABLES 4.38M`, `CF-SKIN CARE 4.36M`, `CF-EDIBLE OILS 3.74M`.
  - Investigation noted that reused gapfill breakdowns were partial and advised that a full decomposition without `TOPN` would be needed for exact shares.
  - No additional DAX executed; investigation concluded from reused evidence.

- `cfh022_current_only_store_outside_comparable_base`
  - Baseline entity-scope evidence identified `CFH022` as excluded from comparison and as a new/current-only entity.
  - Signal reported `net revenue CURRENT = 11,906,055.96` with no prior-period value in entity scope.
  - Reused evidence also cited `current quantity = 2,113,071.87` and `current bills = 794,252`, with zero prior-period revenue, quantity, and transactions.
  - Reused evidence listed broad current trading across item categories including `CF-GROCERY FOOD ~2.21M`, `CF-FRUIT & VEGETABLES ~1.13M`, `CF-STAPLES ~1.06M`, `CF-PERSONAL CARE ~0.96M`.
  - Reused product-group examples included `CF-RICE ~0.68M`, `CF-FRUITS ~0.62M`, `CF-EDIBLE OILS ~0.53M`.
  - No additional DAX executed; investigation concluded from reused evidence.

# Confidence & Caveats
- CFH021 growth insight: high confidence. Supported by the baseline store signal, two reconciled decompositions, and 3 successful DAX breakdowns across item category, product group, and special product group.
- Monthly March-April swing insight: moderate confidence. Supported by the complete month series, the March worst-period drill, and 2 successful April DAX breakdowns. Direct March-versus-April product comparisons were not run.
- Fresh chicken and parts insight: moderate confidence. Supported by the reconciled decompositions and reused store and subgroup breakdowns, but no fresh DAX was run in this investigation.
- Meat insight: moderate confidence. Supported by reconciled decompositions and reused subgroup and store evidence. The detailed subgroup evidence is summarized from the investigation trail rather than freshly queried here.
- FMCG FOOD insight: moderate confidence. Supported by the main division signal and reused store and subgroup evidence. A direct new division-by-product query was not run.
- Fruit and vegetables decline insight: moderate confidence. Supported by reconciled decompositions and reused product, subgroup, and store breakdowns, but not by fresh DAX in this run.
- Sun flower oil decline insight: high confidence. Supported by reconciled decompositions plus 1 successful store-level DAX query showing decline in all comparable stores.
- Edible oils insight: moderate confidence. Supported by reconciled decompositions and reused subgroup and store breakdowns. No fresh DAX was run for this signal.
- Confectionery quantity decline insight: moderate confidence. Supported by consistent reused evidence across product group, special product group, store, and transaction movement, but not by fresh DAX in this run.
- CFH017 decline insight: high confidence. Supported by the baseline signal, two reconciled decompositions, and 1 successful item-category DAX breakdown.
- FARM FRESH and FMCG FOOD concentration insight: moderate confidence. Current concentration is clear, but exact division-by-product attribution was not available from the bundled evidence.
- CFH014 and CFH021 concentration insight: moderate confidence. Store concentration is clear, but supporting category and product views were partial and not exhaustive.
- CFH022 watch-out: high confidence. Entity scope is trusted and complete, and the resolved scope explicitly excludes `CFH022` from comparable analysis.
- No failed queries were reported in the investigations provided. However, several findings rely on reused evidence rather than directly returned query tables, and some dimension-level scans are partial or untrusted in the coverage matrix.
- Department and section dimensions were not investigated here, and no findings are made from other fact tables outside the evidence supplied.

# Suggested Follow-ups
- Why is CFH021 outperforming peers so strongly? Compare revenue per unit, revenue per transaction, and category composition for CFH021 versus CFH014, CFH017, and CFH018 at `item_category_name` and `product_group_name`.
- What changed between March and April in the key rebound lines? Run a direct month comparison for edible oils, rice, fresh chicken, imported fruits, imported vegetables, and sun flower oil using `'MIS_DEEP_DIVE2'[month]` by `product_group_name` and `special_product_group_name`.
- What is behind lower average revenue per unit in fresh chicken and meat? Check item or SKU-level price, the mix of products sold, and promotions for `FRESH CHICKEN`, `FRESH CHICKEN PARTS`, beef, and mutton; item-level pricing or promotion detail may require data outside this model.
- Why did FMCG FOOD lose units while revenue still grew? Break `division_name = FMCG FOOD` down by `product_group_name` and `special_product_group_name` with revenue per unit and revenue per transaction measures.
- Why are fruit and vegetables weak in CFH017, CFH018, and CFH021 but positive in CFH014? Compare imported versus local lines by store and month; availability or stock-out validation may require inventory data outside this model.
- Why did sun flower oil decline across all stores? Review store-level month trends for `SUN FLOWER OIL`; promotion, stock, and supplier availability checks likely need data outside this model.
- Which edible oil lines offset the sun flower oil decline? Quantify store-by-subgroup contributions for `VEGETABLE OIL`, `OTHER COOKING OIL`, `OLIVE OIL`, and `SUN FLOWER OIL`, and compare unit rates over time.
- What exactly drove the confectionery unit loss? Drill `CHOCOLATE COATED BARS` by store and then to item level if available; item, pack-size, and availability confirmation may need data outside this model.
- Why is CFH017 underperforming? Drill CFH017 from `item_category_name` into `product_group_name` for `CF-FRUIT & VEGETABLES` and `CF-GROCERY FOOD`.
- Which groups make CFH014 and CFH021 so large in current revenue? Run full, non-`TOPN` decompositions for those stores by `item_category_name` and `product_group_name`.
- Which groups make up the FARM FRESH versus FMCG FOOD current base? Run a direct `division_name` by `product_group_name` breakdown for the comparable stores.
- How should CFH022 be reported operationally? Confirm whether the store is newly opened, newly mapped, or missing prior-period data; this verification likely requires store master, onboarding, or data-load records outside this model.