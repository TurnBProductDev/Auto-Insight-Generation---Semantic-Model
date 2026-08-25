# SB Mart SKU Overview insight rules

- Treat the report as one stock position as at the semantic model snapshot date
  (`REP_SSR_STOCK_STATUS_REPORTV3[UPDATED_ON]`).
- Use USD (`sku_overview_currency`) and the model's SKU_STOCK_VALUE exposure only.
- EXPECTED_BURNOUT_DAYS carries a sentinel: 1000 and above means "no reliable
  velocity signal", never the safest SKU in the business. Exclude it and blank
  values from any burnout ranking.
- RECOMMENDED_ACTION = "STOCK OUT - PLACE ORDER" is the most urgent state - zero
  stock, nothing on order - and leads regardless of stock value, which is zero
  for every row in that state.
- Do not claim YoY, trend, causality, or a recommended reorder quantity from
  one snapshot.
- This dataset shares most of its RECOMMENDED_ACTION vocabulary with the
  separate Inventory Management report over a different Power BI dataset in
  the same workspace. Findings here may legitimately overlap with that
  report's - do not claim uniqueness that is not verified.
- Prioritize absolute USD exposure before extreme percentages on immaterial
  members.
