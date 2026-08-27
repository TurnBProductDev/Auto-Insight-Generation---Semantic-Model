# Key Insights
These comparisons include only branches with both current and last-year data: ST1, ST2, ST3, ST4, and ST5.

**ST5 revenue rose by 2.6M (429.6%), from 607.0K to 3.2M compared with the same period last year.** It made up 74.2% of the overall increase. Units sold rose by 1.7M (418.0%), from 407.9K to 2.1M. This added 2.5M to revenue. Revenue per item rose 2.2%, from 1.49 to 1.52. This added 70.1K to the gain. Check ST5 by product and branch to find where the change happened.

**CONSUMER GOODS revenue rose by 2.0M (10.0%), from 20.1M to 22.1M compared with the same period last year.** It made up 57.1% of the overall increase. Units sold rose by 875.0K (6.0%), from 14.6M to 15.5M. This added 1.2M to revenue. Revenue per item rose 3.8%, from 1.37 to 1.43. This added 801.6K to the gain. Check CONSUMER GOODS by product and branch to find where the change happened.

**ST1 and ST4 generated 24.3M in revenue.** That was 58.7% of all revenue. Check the complete branch and product breakdown before ranking the areas inside this total.

**ST4 revenue rose by 1.2M (10.6%), from 11.2M to 12.4M compared with the same period last year.** It made up 33.8% of the overall increase. Units sold rose by 62.1K (0.9%), from 7.0M to 7.0M. This added 100.0K to revenue. Revenue per item rose 9.6%, from 1.61 to 1.77. This added 1.1M to the gain. Check ST4 by product and branch to find where the change happened.

# Data Quality Watch-outs
- No clear data-quality issue was flagged in the selected findings. Check that any follow-up product-group or section views use full results, because some supporting merchandise cuts were only partial ranked slices.

# Evidence Trail
- `st5_dominates_comparable_growth`
  - Baseline signal on `'MIS_DEEP_DIVE2'[store_no]` identified ST5 as contributing `revenue Growth = 2607588.7038`, from `net revenue PAST = 607046.4054` to `net revenue CURRENT = 3214635.1092`; impact share `74.2338%`.
  - Decomposition by `QTY Growth` reconciled: `driver_prior = 407921.023`, `driver_current = 2113071.8729`, `driver_change = 1705150.8499` (`418.01%`); revenue change split into `volume_effect = 2537514.9495` (`97.3127%`) and `rate_effect = 70073.7543` (`2.6873%`); rate `net revenue CURRENT / net qty CURRENT` moved from `1.4881` to `1.5213`.
  - Decomposition by `bills growth` reconciled: `driver_prior = 153381.0`, `driver_current = 794252.0`, `driver_change = 640871.0` (`417.8295%`); revenue split `volume_effect = 2536418.7016` (`97.2707%`) and `rate_effect = 71170.0022` (`2.7293%`); rate `net revenue CURRENT / net bills CURRENT` moved from `3.9578` to `4.0474`.
  - Executed DAX on `'MIS_DEEP_DIVE2'[item_category_name]` for `TREATAS({"ST5"}, 'MIS_DEEP_DIVE2'[store_no])`; query succeeded.
  - Top returned category gains in ST5: `PROVISIONS +867279.1959`, `REFRIDGERATED GOODS +330959.1285`, `GREEN GROCERIES +286236.9279`, `PERSONAL CARE +220522.2516`, `SPICE MARKET +164524.176`.
  - Supporting ST5 category quantities and bills from the same query included: `PROVISIONS QTY Growth +785815.05646, bills growth +228930`; `REFRIDGERATED GOODS QTY Growth +383560.975, bills growth +98999`; `GREEN GROCERIES QTY Growth +220323.8474, bills growth +111084`.
  - Investigation concluded and accepted after 1 executed query.

- `consumer_goods_leads_division_growth_and_scale`
  - Baseline signal on `'MIS_DEEP_DIVE2'[division_name]` identified `CONSUMER GOODS` with `revenue Growth = 2004495.2523`, from `20134207.8378` to `22138703.0901`; impact share `57.0647%`.
  - Decomposition by `QTY Growth` reconciled: `14645940.6988` to `15520937.4861`, change `874996.7873` (`5.9743%`); revenue split into `volume_effect = 1202883.9618` (`60.0093%`) and `rate_effect = 801611.2905` (`39.9907%`); revenue per item moved `1.3747` to `1.4264`.
  - Decomposition by `bills growth` reconciled: `4970945.0` to `5456676.0`, change `485731.0` (`9.7714%`); revenue split `1967394.3098` (`98.1491%`) from more transactions and `37100.9425` (`1.8509%`) from higher revenue per purchase; rate moved `4.0504` to `4.0572`.
  - No new DAX query was executed in this investigation; conclusion relied on prior scan outputs and partial ranked merchandise cuts referenced in the investigation summary.
  - Investigation summary reported store contributions within `CONSUMER GOODS`: `ST5 +1640544.3999`, `ST4 +331057.9404`, `ST3 +188089.1037`; `ST1` and `ST2` declined, but exact decline amounts were not supplied here.
  - Investigation summary also cited partial product-level positives: `COOKING OILS +256169.5065`, `FRESH DAIRY +189487.0179`, `HEALTH AND BEAUTY CARE +184513.1886`, `RICE +159017.6097`; special product groups `COOKING OILS +333468.6813`, `SNACKS +134709.7851`, `BASMATI RICE +116960.7951`.
  - Coverage matrix marks `'MIS_DEEP_DIVE2'[product_group_name]`, `'MIS_DEEP_DIVE2'[special_product_group_name]`, and `'MIS_DEEP_DIVE2'[item_category_name]` as `partial` and `trusted_coverage = false` for these merchandise cuts.
  - Investigation concluded and accepted with no additional executed query.

- `st1_st4_concentrate_store_sales_base`
  - Baseline concentration signal on `'MIS_DEEP_DIVE2'[store_no]` identified `ST1` and `ST4` with `net revenue CURRENT = 24303873.5037`, share of current total `58.6633%`.
  - Same signal reported `net bills CURRENT = 5988292.0` and `net qty CURRENT = 13103971.9744` for ST1 and ST4 together.
  - No new DAX query was executed in this investigation; conclusion relied on previously available concentration cuts described in the investigation summary.
  - Investigation summary cited current item-category revenue within ST1 and ST4: `PROVISIONS 6074365.3704`, `PERSONAL CARE 3256780.0734`, `GREEN GROCERIES 3058478.1522`; combined `12389623.596`, about `51.0%` of the ST1+ST4 revenue stake.
  - Same summary cited category transaction and quantity context: `PROVISIONS bills 1546570, qty 5234244.14275`; `PERSONAL CARE bills 656680, qty 1574930`; `GREEN GROCERIES bills 1358908, qty 2185284.21856`.
  - Product-group examples from the same summary: `VEGETABLES revenue 1431445.2948, bills 817674`; `HEALTH AND BEAUTY CARE revenue 1335201.9885, bills 259458`; `COOKING OILS revenue 1134567.6642, bills 220737`; `FRESH POULTRY revenue 1041464.7468, bills 249377`.
  - Coverage matrix marks product-group and item-category concentration views as partial or top-ranked rather than complete, so the cited merchandise concentration is indicative but not exhaustive.
  - Investigation concluded and accepted with no additional executed query.

- `st4_growth_is_revenue_led`
  - Baseline signal on `'MIS_DEEP_DIVE2'[store_no]` identified ST4 with `revenue Growth = 1186833.168`, from `11236228.3863` to `12423061.5543`; impact share `33.7872%`.
  - Decomposition by `QTY Growth` reconciled: `6973097.3419` to `7035177.9891`, change `62080.6472` (`0.8903%`); revenue split `volume_effect = 100034.7903` (`8.4287%`) and `rate_effect = 1086798.3777` (`91.5713%`); revenue per item moved from `1.6114` to `1.7658`.
  - Decomposition by `bills growth` reconciled: `2865206.0` to `3049579.0`, change `184373.0` (`6.4349%`); revenue split `volume_effect = 723039.5079` (`60.9217%`) and `rate_effect = 463793.6601` (`39.0783%`); revenue per purchase moved from `3.9216` to `4.0737`.
  - Executed DAX on `'MIS_DEEP_DIVE2'[item_category_name]` for `TREATAS({"ST4"}, 'MIS_DEEP_DIVE2'[store_no])`; query succeeded.
  - Largest positive ST4 category gains returned: `MENS APPAREL +217209.2436`, `PERSONAL CARE +188853.0795`, `LADIES APPAREL +185630.3541`, `ENTERTAINMENTS +175617.8118`, `PROVISIONS +130864.6125`.
  - Quantity context from the same query: `MENS APPAREL +47572`, `PERSONAL CARE +58309`, `LADIES APPAREL +61079`, `ENTERTAINMENTS +15239`, while `PROVISIONS QTY Growth = -141067.30419`.
  - Additional returned negatives/small offsets included `GLASS ITEMS -3408.5529`, `OTHER -707.7618`, `CONSUMER DEVICES -4.2282`, `BABY CLOTHING -31.4739`.
  - Investigation concluded and accepted after 1 executed query.

# Confidence & Caveats
- ST5 insight: high confidence. Supported by the baseline store result, two reconciled decompositions, and one successful category drilldown. The category breakdown is still a ranked output rather than a guaranteed full merchandise census.
- CONSUMER GOODS insight: medium confidence. The main division movement is well supported by the baseline result and two reconciled decompositions, but the merchandise explanation relied on partial ranked cuts and no fresh query in this investigation.
- ST1 and ST4 concentration insight: medium confidence. The store-level concentration is directly supported, but the merchandise concentration detail came from partial top-ranked views without a new complete decomposition.
- ST4 insight: high confidence. Supported by the baseline store result, two reconciled decompositions, and one successful category drilldown. Sub-category detail below item category was not checked.
- Time caveat: sub-annual trend monitoring was disabled because no valid business time axis was found by the scan, even though business rules reference `MIS_DEEP_DIVE2[Month]`. This run therefore supports the supplied year-on-year comparisons, not month-by-month sequencing.
- Coverage caveat: several merchandise dimensions in the coverage matrix are marked `partial` and `trusted_coverage = false`, especially product-group and special-product-group views.
- Query caveat: no probe failed in the selected investigations.

# Suggested Follow-ups
- For ST5: Which `MIS_DEEP_DIVE2[product_group_name]` values inside PROVISIONS, REFRIDGERATED GOODS, and GREEN GROCERIES account for most of ST5’s increase?
- For ST5: Did the rise come from more items per transaction or simply more transactions? The model can test this with `QUANTITY PER TRANSACTION CURRENT YEAR`, `QUANTITY PER TRANSACTION PAST YEAR`, and related store filters.
- For CONSUMER GOODS: Which full sections within the division increased or declined across ST1-ST5, not just the top-ranked product groups?
- For CONSUMER GOODS: How much of the division increase came specifically from ST5 within each major product group? This can be answered inside the current model with a cross-filtered store-by-product-group query.
- For ST1 and ST4 concentration: What share of total current revenue, transactions, and units does each major category contribute for these two stores versus the full five-store base?
- For ST1 and ST4 concentration: Is the concentration stable month to month on the business month axis `MIS_DEEP_DIVE2[Month]`? That would require a valid month-enabled query path in the model for this report run.
- For ST4: Which `MIS_DEEP_DIVE2[product_group_name]` values inside PROVISIONS, MENS APPAREL, and LADIES APPAREL explain the higher revenue per item?
- For ST4: Did average revenue per item rise because of a different mix of products being sold? Product-level checks may help, but confirming price-list or promotion effects would need data outside this model.