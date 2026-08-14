# Key Insights
These comparisons use the available current-versus-last-year records in this model, at monthly and merchandise levels, for the full year ending 2023-12-31.

**Revenue fell by 4.4M in August-December compared with the stated comparison period.** This five-month stretch made up 95.9% of the full-year revenue decline of 4.6M. The remaining months reduced revenue by 192.1K. Our checks did not measure a business reason for this decline. Check the month-by-month category trend for August and October.

**TECHNOLOGY revenue fell by 2.0M (20.1%), from 9.9M to 7.9M compared with the stated comparison period.** Our checks did not measure a business reason for this decline. Review the monthly path within TECHNOLOGY to see whether the drop was concentrated in a few months or spread through the year.

**CONSUMER GOODS revenue fell by 1.5M (3.2%), from 47.0M to 45.6M compared with the stated comparison period.** Units rose by 486,524.24 in the same comparison. Our checks did not measure a business reason for the revenue decline. Review average revenue per item within CONSUMER GOODS to see whether lower average value per item explains revenue falling while units rose.

**FRESH FOOD revenue fell by 1.5M (6.9%), from 21.0M to 19.6M compared with the stated comparison period.** Our checks did not measure a business reason for this decline. The investigation noted a similar pattern in GREEN GROCERIES, but the manager brief for that area was not supplied. Investigate item pricing and mix within GREEN GROCERIES to test whether lower average revenue per item may explain the value decline.

# Data Quality Watch-outs
- Some checked revenue decline sits in rows with no department, section, or category name. Check how unassigned sales are loaded and labelled before treating merchandise totals as complete.
- Branch comparison scope could not be confirmed from the metadata used in this run. Check the branch population behind these results before reusing them as matched comparisons.
- Several merchandise breakdowns were only partial in this run. Check whether the queries returned only selected movers rather than a complete ranking.

# Evidence Trail
- august_to_december_revenue_decline
  - Signal summary: revenue down 4,440,787.8658 across August-December; share of full-year decline 95.8541%.
  - Manager fact brief: `change_display = 4.4M`; `share_of_total_pct_display = 95.9%`; `total_change_display = 4.6M`; `other_change_display = 192.1K`; no percentage available for the August-December block itself.
  - Probe 1 succeeded: `SUMMARIZECOLUMNS('MIS_DEEP_DIVE2'[CATEGORY_NAME], TREATAS({8,9,10,11,12}, 'MIS_DEEP_DIVE2'[DOC_MONTH]), "Revenue Growth", [revenue Growth], "Revenue Current", [net revenue CURRENT], "Revenue Past", [net revenue PAST], "Units Growth", [QTY Growth], "Units Current", [net qty CURRENT], "Units Past", [net qty PAST])`.
  - Largest checked category declines in August-December from Probe 1: LED TV -582,105.2055; BLANKET DOUBLE -401,228.4932; TORCHES -355,660.2740; ROASTED NUTS ROASTERY -342,902.0082; FRESH MUTTON OTHER -289,931.2110.
  - Probe 1 also showed unassigned category rows: `CATEGORY_NAME = blank`, revenue growth -111,551.7808; revenue current 3,297,309.5890; revenue past 3,408,861.3699; units growth +172,624.0.
  - Probe 2 succeeded: `SUMMARIZECOLUMNS('MIS_DEEP_DIVE2'[DEPARTMENT], TREATAS({8,9,10,11,12}, 'MIS_DEEP_DIVE2'[DOC_MONTH]), "Revenue Growth", [revenue Growth], "Revenue Current", [net revenue CURRENT], "Revenue Past", [net revenue PAST], "Units Growth", [QTY Growth])`.
  - Department changes from Probe 2: CONSUMER GOODS -1,555,187.9890; TECHNOLOGY -1,347,947.3973; LIFESTYLE -1,244,350.2356; HOME & LIVING -294,641.6712; blank department -111,551.7808; FRESH FOOD +112,891.2082.
  - Probe 3 succeeded: `SUMMARIZECOLUMNS('MIS_DEEP_DIVE2'[SECTION], TREATAS({8,9,10,11,12}, 'MIS_DEEP_DIVE2'[DOC_MONTH]), "Revenue Growth", [revenue Growth], "Revenue Current", [net revenue CURRENT], "Revenue Past", [net revenue PAST], "Units Growth", [QTY Growth])`.
  - Section changes from Probe 3 included: PERSONAL CARE -772,489.1781; CONSUMER DEVICES -722,413.9726; ENTERTAINMENTS -625,533.4247; HOME TEXTILES -543,405.2055; PROVISIONS -539,626.8466.
  - Temporal context supplied separately: worst period drill was October, period change -1,730,714.71; top category segments LED TV -151,762.47, BLANKET DOUBLE -146,308.22, TORCHES -107,897.81.
  - Investigation concluded and accepted after 3 probe executions.

- technology_revenue_decline
  - Signal summary: TECHNOLOGY revenue current 7,916,819.7260; prior 9,907,943.6986; change -1,991,123.9726.
  - Manager fact brief: `current_display = 7.9M`; `prior_display = 9.9M`; `change_display = 2.0M`; `change_pct_display = 20.1%`.
  - No new DAX probe was executed in this investigation; conclusion was accepted from previously available evidence.
  - Investigation explanation states section split: CONSUMER DEVICES -1.00M and ENTERTAINMENTS -0.99M.
  - Investigation explanation states LED TV contributed -916,983.0137, about 91.5% of the CONSUMER DEVICES decline and about 46.1% of the TECHNOLOGY decline.
  - Investigation explanation also states LED TV and TORCHES together contributed 1.45M of the 1.99M department decline.
  - Supporting August-December probe evidence on period-specific movement inside TECHNOLOGY: CONSUMER DEVICES -722,413.9726; ENTERTAINMENTS -625,533.4247; LED TV -582,105.2055.
  - Investigation concluded and accepted with 0 additional probe executions.

- consumer_goods_revenue_transactions_divergence
  - Signal summary: CONSUMER GOODS revenue current 45,556,332.1507; prior 47,047,585.3836; change -1,491,253.2329; units change +486,524.24; transactions change -1,224,468.0.
  - Manager fact brief: `current_display = 45.6M`; `prior_display = 47.0M`; `change_display = 1.5M`; `change_pct_display = 3.2%`.
  - No new DAX probe was executed in this investigation; conclusion was accepted from previously available evidence.
  - Investigation explanation states section split: SPICE MARKET -648.6K revenue and -46.5K transactions; PROVISIONS -394.6K revenue and -323.1K transactions; PERSONAL CARE -293.2K revenue and -637.4K transactions; BEVERAGES +95.5K revenue despite -100.7K transactions.
  - Investigation explanation states largest category transaction declines: UNISEX -243.5K; ROASTED NUTS ROASTERY -170.4K; MEN`S NEEDS -151.5K; HOME CLEANERS -131.9K; BISCUITS -129.6K; ROASTERY group -127.7K.
  - Investigation explanation also notes units growth in MINERAL WATER +789.7K with transactions -36.1K, and COFFEE AND TEA +361.0K with transactions -39.2K.
  - Supporting August-December probe evidence on sections within this department: SPICE MARKET -174,102.0932; PROVISIONS -539,626.8466; PERSONAL CARE -772,489.1781 in that five-month window.
  - Department-level transaction growth context is usable under business rules; branch-level transaction levels are not.
  - Investigation concluded and accepted with 0 additional probe executions.

- fresh_food_and_green_groceries_mixed_volume_value
  - Signal summary: FRESH FOOD revenue current 19,592,778.3479; prior 21,046,633.1699; change -1,453,854.8219; units change +427,618.51; transactions change +348,278.0.
  - Manager fact brief: `current_display = 19.6M`; `prior_display = 21.0M`; `change_display = 1.5M`; `change_pct_display = 6.9%`.
  - No new DAX probe was executed in this investigation; conclusion was accepted from previously available evidence.
  - Investigation explanation states concentrated `CATEGORY_NAME_2` declines: MUTTON -647.2K; FRUITS -298.0K; VEGETABLES -275.4K; SALADS -246.3K.
  - Investigation explanation states units rose in those groups: FRUITS +64.3K; VEGETABLES +257.3K; SALADS +72.9K.
  - Investigation explanation states GREEN GROCERIES revenue -819,637.3014 with units +394,409.0 and transactions +269,083.0.
  - Supporting August-December department probe showed FRESH FOOD +112,891.2082 in that five-month period, so the full-year decline did not come from August-December alone.
  - Investigation concluded and accepted with 0 additional probe executions.

# Confidence & Caveats
- August-December decline: moderate confidence. Three supporting probes were run and concluded cleanly across department, section, and category views.
- TECHNOLOGY decline: moderate confidence. The investigation concluded, but it reused prior evidence and ran no fresh query in this run.
- CONSUMER GOODS decline: moderate confidence. The investigation concluded, but the detailed supporting numbers came from reused evidence rather than a fresh probe here.
- FRESH FOOD decline: moderate confidence. The finding is internally consistent, but the supporting drilldown was reused and not re-queried in this run.
- Merchandise hierarchy caveat: unassigned rows exist with blank department, section, and category, so merchandise breakdowns do not fully add to the company total.
- Scope caveat: the branch comparison population was not identified in this run, and metadata warned that no high-confidence entity or location dimension was confirmed.
- Coverage caveat: several dimensions were marked partial in the coverage matrix, so some lists reflect checked movers rather than a full ranked population.
- Time caveat: the model is monthly only, and the data ends at 2023-12-31.

# Suggested Follow-ups
- What changed in late 2023 to create almost all of the annual revenue decline? Review monthly category trends for LED TV, BLANKET DOUBLE, and TORCHES across August to December, especially October.
- Was the TECHNOLOGY decline concentrated in a few months or sustained all year? Check month-by-month revenue and units within TECHNOLOGY.
- Why did CONSUMER GOODS sell more units but record lower revenue? Compare average revenue per item over time within CONSUMER GOODS.
- Did FRESH FOOD lose value because of lower prices or a shift toward cheaper items? Review item-level pricing and assortment mix within GREEN GROCERIES.
- How much of the merchandise story is hidden in unassigned rows? Check why sales records are arriving without department, section, or category labels.
- Which branches are in the comparison population for these findings? Confirm branch scope before using these results in branch-matched reporting.