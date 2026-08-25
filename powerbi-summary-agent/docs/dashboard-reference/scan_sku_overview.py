"""Live read of the SKU OVERVIEW semantic model into sku_overview_scan.json.

One scan, no LLM, no writes outside this folder. Every figure the reference page
publishes is derived from this file by sku_overview_facts.py - nothing is typed
by hand.

    python scan_sku_overview.py            # rewrites sku_overview_scan.json

Scope, per the rules document: LOC_CODE IN {ST1..ST5}. The two warehouses are
storage, not selling locations, and are read only as the replenishment source
behind a shop-floor problem.

NOTE ON CURRENCY. This model mixes two bases and the scan keeps both raw so the
facts module owns the conversion in one place:

  already USD   SKU_STOCK_VALUE, EXCESS_STOCK_VALUE, PENDING_ORDERS_VALUE,
                AVG_DAILY_SALES_VALUE, 'TOP SALES DATES IN LOC'[sales_value]
  local         SALES_VALUE_LAST_1MONTH, SALES_VALUE_LAST_3MONTHS,
                OPP_LOSS_DUE_TO_STOCKOUT, RP, LC, min_rp, max_rp

Measured, not assumed: SKU_STOCK_VALUE / (CURRENT_STOCK x LC) is 0.27 across
93,904 rows, and OPP_LOSS_DUE_TO_STOCKOUT / AVG_DAILY_SALES_VALUE is exactly
1/0.27 on all 4,583 rows that carry one. Column names ending _local are in the
model's local currency; _usd are already converted.
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from src.tools.powerbi_executor import get_powerbi_token, run_dax  # noqa: E402

WORKSPACE = "2829a4af-2e07-4b43-b913-0a829a06bef4"
DATASET = "867a2a79-8360-44e5-856e-2543e5ab0d6e"
REPORT = "47003525-99b7-4121-8ecb-5f0b67b62d8b"

F = "REP_SSR_STOCK_STATUS_REPORTV3"
T = "'TOP SALES DATES IN LOC'"
W = "'WEEK SALES'"

SHOPS = '{"ST1","ST2","ST3","ST4","ST5"}'
VERGE_WH = '"ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE"'

_token = None
_calls = 0


def token():
    global _token
    if _token is None:
        _token = get_powerbi_token()
    return _token


def q(dax):
    global _calls
    _calls += 1
    ok, resp = run_dax(WORKSPACE, DATASET, dax, token())
    if not ok:
        raise RuntimeError("query failed: %s\n%s" % (str(resp)[:400], dax[:400]))
    result = resp["results"][0]
    if "error" in result:
        raise RuntimeError(
            "embedded error: %s\n%s" % (json.dumps(result["error"])[:400], dax[:400])
        )
    rows = result["tables"][0]["rows"]
    return [{k.split("[")[-1].rstrip("]"): v for k, v in r.items()} for r in rows]


def one(dax):
    rows = q(dax)
    return rows[0] if rows else {}


MEASURES = (
    ' "rows", COUNTROWS({F}),'
    ' "skus", DISTINCTCOUNT({F}[SKU_CODE]),'
    ' "stock_value_usd", SUM({F}[SKU_STOCK_VALUE]),'
    ' "stock_qty", SUM({F}[CURRENT_STOCK]),'
    ' "excess_value_usd", SUM({F}[EXCESS_STOCK_VALUE]),'
    ' "excess_qty", SUM({F}[EXCESS_STOCK]),'
    ' "pending_value_usd", SUM({F}[PENDING_ORDERS_VALUE]),'
    ' "pending_qty", SUM({F}[PENDING_ORDERS]),'
    ' "sales_1m_local", SUM({F}[SALES_VALUE_LAST_1MONTH]),'
    ' "sales_3m_local", SUM({F}[SALES_VALUE_LAST_3MONTHS]),'
    ' "qty_1m", SUM({F}[SALES_QTY_LAST_1MONTH]),'
    ' "qty_3m", SUM({F}[SALES_QTY_LAST_3MONTHS]),'
    ' "opp_day_local", SUM({F}[OPP_LOSS_DUE_TO_STOCKOUT])'
).format(F=F)

ROW_COLS = (
    "{F}[SKU_CODE], {F}[PART_DESCRIPTION], {F}[CATEGORY_NAME], {F}[DEPARTMENT],"
    " {F}[LOC_CODE], {F}[SKUSEGMENT]"
).format(F=F)


def seg(segment):
    """Extra predicate scoping a population to the top sales band."""
    return ' , {F}[SKUSEGMENT]="SEG_A"'.format(F=F) if segment else ""


def population(segment, anchor):
    """Every finding, computed over one population.

    segment=None is the whole business; segment="SEG_A" is the top sales band,
    which is what the second view on the page shows. Every row the second view
    prints is recomputed here, so that view owns its rows rather than reusing
    the wider one's.
    """
    s = seg(segment)
    y, m, d = anchor
    out = {}

    out["totals"] = one(
        "EVALUATE CALCULATETABLE(ROW({M}), {F}[LOC_CODE] IN {SH}{S})".format(
            M=MEASURES, F=F, SH=SHOPS, S=s
        )
    )
    for key, col in (("by_department", "DEPARTMENT"), ("by_store", "LOC_CODE"),
                     ("by_action", "RECOMMENDED_ACTION")):
        out[key] = q(
            "EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS({F}[{C}],{M}),"
            " {F}[LOC_CODE] IN {SH}{S})".format(F=F, C=col, M=MEASURES, SH=SHOPS, S=s)
        )

    # Rule 1 - the top 3 sellers in each department by last-month sales value,
    # ranked per product across the shops that carry it.
    rule1 = {}
    for row in out["by_department"]:
        dept = row["DEPARTMENT"]
        rule1[dept] = q(
            "EVALUATE TOPN(3, CALCULATETABLE(SUMMARIZECOLUMNS("
            "{F}[SKU_CODE], {F}[PART_DESCRIPTION], {F}[CATEGORY_NAME],"
            ' "sales_1m_local", SUM({F}[SALES_VALUE_LAST_1MONTH]),'
            ' "qty_1m", SUM({F}[SALES_QTY_LAST_1MONTH]),'
            ' "shops", DISTINCTCOUNT({F}[LOC_CODE])),'
            ' {F}[LOC_CODE] IN {SH}, {F}[DEPARTMENT]="{D}"{S}),'
            " [sales_1m_local], DESC) ORDER BY [sales_1m_local] DESC".format(
                F=F, SH=SHOPS, D=dept.replace('"', '""'), S=s
            )
        )
    out["rule1_top_by_department"] = rule1

    # Rule 3 - every product-shop whose single best day in the tracked window
    # was yesterday. RNK=1 is that pair's own best day.
    out["rule3_rows"] = q(
        "EVALUATE TOPN(10, CALCULATETABLE(SUMMARIZECOLUMNS("
        "{T}[SKU], {T}[LOC_CODE], {F}[PART_DESCRIPTION], {F}[CATEGORY_NAME], {F}[DEPARTMENT],"
        ' "value_usd", SUM({T}[sales_value]), "qty", SUM({T}[sales_quantity])),'
        " {T}[RNK]=1, {T}[doc_date]=DATE({Y},{M},{D}), {F}[LOC_CODE] IN {SH}{S}),"
        " [value_usd], DESC) ORDER BY [value_usd] DESC".format(T=T, F=F, Y=y, M=m, D=d, SH=SHOPS, S=s)
    )
    out["rule3_count"] = one(
        "EVALUATE CALCULATETABLE(ROW("
        ' "pairs", COUNTROWS({T}), "value_usd", SUM({T}[sales_value])),'
        " {T}[RNK]=1, {T}[doc_date]=DATE({Y},{M},{D}), {F}[LOC_CODE] IN {SH}{S})".format(
            T=T, F=F, Y=y, M=m, D=d, SH=SHOPS, S=s
        )
    )

    # Rule 4 - top-band products with an empty shelf. Already Segment A by
    # definition, so the scoped view repeats it unchanged and says so.
    stockout = ' {F}[SKUSEGMENT]="SEG_A", {F}[SKU_STOCK_STATUS]="STOCK OUT"'.format(F=F)
    out["rule4_totals"] = one(
        "EVALUATE CALCULATETABLE(ROW({M}), {F}[LOC_CODE] IN {SH},{P})".format(
            M=MEASURES, F=F, SH=SHOPS, P=stockout
        )
    )
    out["rule4_rows"] = q(
        "EVALUATE TOPN(10, CALCULATETABLE(SUMMARIZECOLUMNS({RC},"
        ' "sales_3m_local", SUM({F}[SALES_VALUE_LAST_3MONTHS]),'
        ' "qty_3m", SUM({F}[SALES_QTY_LAST_3MONTHS]),'
        ' "opp_day_local", SUM({F}[OPP_LOSS_DUE_TO_STOCKOUT]),'
        ' "oos_days", SUM({F}[STOCK_OUT_DAYS_3MONTHS]),'
        ' "reorder", SUM({F}[REORDER_LEVEL]),'
        ' "pending", SUM({F}[PENDING_ORDERS])),'
        " {F}[LOC_CODE] IN {SH},{P}), [sales_3m_local], DESC)"
        " ORDER BY [sales_3m_local] DESC".format(
            RC=ROW_COLS, F=F, SH=SHOPS, P=stockout
        )
    )
    out["rule4_opp_coverage"] = one(
        "EVALUATE CALCULATETABLE(ROW("
        ' "with_opp", CALCULATE(COUNTROWS({F}), FILTER({F}, {F}[OPP_LOSS_DUE_TO_STOCKOUT] > 0)),'
        ' "rows", COUNTROWS({F})),'
        " {F}[LOC_CODE] IN {SH},{P})".format(F=F, SH=SHOPS, P=stockout)
    )

    # Rule 5 - nearly out on the shelf, and the stock already exists upstream.
    out["rule5_totals"] = one(
        "EVALUATE CALCULATETABLE(ROW({M}), {F}[LOC_CODE] IN {SH},"
        " {F}[RECOMMENDED_ACTION]={V}{S})".format(
            M=MEASURES, F=F, SH=SHOPS, V=VERGE_WH, S=s
        )
    )
    out["rule5_rows"] = q(
        "EVALUATE TOPN(10, CALCULATETABLE(SUMMARIZECOLUMNS({RC},"
        ' "sales_3m_local", SUM({F}[SALES_VALUE_LAST_3MONTHS]),'
        ' "stock_qty", SUM({F}[CURRENT_STOCK]),'
        ' "reorder", SUM({F}[REORDER_LEVEL]),'
        ' "burnout", SUM({F}[EXPECTED_BURNOUT_DAYS])),'
        " {F}[LOC_CODE] IN {SH}, {F}[RECOMMENDED_ACTION]={V}{S}),"
        " [sales_3m_local], DESC) ORDER BY [sales_3m_local] DESC".format(
            RC=ROW_COLS, F=F, SH=SHOPS, V=VERGE_WH, S=s)
    )
    out["rule5_by_store"] = q(
        "EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS({F}[LOC_CODE],"
        ' "rows", COUNTROWS({F}),'
        ' "sales_3m_local", SUM({F}[SALES_VALUE_LAST_3MONTHS])),'
        " {F}[LOC_CODE] IN {SH}, {F}[RECOMMENDED_ACTION]={V}{S})".format(
            F=F, SH=SHOPS, V=VERGE_WH, S=s
        )
    )

    # Rule 6 - not selling at all, and more already on order.
    nm = ' {F}[RECOMMENDED_ACTION]="NON MOVING", {F}[PENDING_ORDERS] > 0'.format(F=F)
    out["rule6_totals"] = one(
        "EVALUATE CALCULATETABLE(ROW({M}), {F}[LOC_CODE] IN {SH},{P}{S})".format(
            M=MEASURES, F=F, SH=SHOPS, P=nm, S=s
        )
    )
    out["rule6_rows"] = q(
        "EVALUATE TOPN(25, CALCULATETABLE(SUMMARIZECOLUMNS({RC},"
        ' "pending", SUM({F}[PENDING_ORDERS]),'
        ' "pending_value_usd", SUM({F}[PENDING_ORDERS_VALUE]),'
        ' "days_no_sale", MAX({F}[DAYS_FROM_LAST_SALES]),'
        ' "stock_qty", SUM({F}[CURRENT_STOCK])),'
        " {F}[LOC_CODE] IN {SH},{P}{S}), [pending_value_usd], DESC)"
        " ORDER BY [pending_value_usd] DESC".format(
            RC=ROW_COLS, F=F, SH=SHOPS, P=nm, S=s
        )
    )
    out["rule6_by_store"] = q(
        "EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS({F}[LOC_CODE],"
        ' "rows", COUNTROWS({F}),'
        ' "pending_value_usd", SUM({F}[PENDING_ORDERS_VALUE])),'
        " {F}[LOC_CODE] IN {SH},{P}{S})".format(F=F, SH=SHOPS, P=nm, S=s)
    )

    # Rule 7 - already more than needed, and more still on order.
    ov = ' {F}[RECOMMENDED_ACTION]="OVERSTOCK", {F}[PENDING_ORDERS] > 0'.format(F=F)
    out["rule7_totals"] = one(
        "EVALUATE CALCULATETABLE(ROW({M}), {F}[LOC_CODE] IN {SH},{P}{S})".format(
            M=MEASURES, F=F, SH=SHOPS, P=ov, S=s
        )
    )
    out["rule7_rows"] = q(
        "EVALUATE TOPN(10, CALCULATETABLE(SUMMARIZECOLUMNS({RC},"
        ' "excess_value_usd", SUM({F}[EXCESS_STOCK_VALUE]),'
        ' "excess_qty", SUM({F}[EXCESS_STOCK]),'
        ' "pending", SUM({F}[PENDING_ORDERS]),'
        ' "pending_value_usd", SUM({F}[PENDING_ORDERS_VALUE]),'
        ' "stock_qty", SUM({F}[CURRENT_STOCK])),'
        " {F}[LOC_CODE] IN {SH},{P}{S}), [excess_value_usd], DESC)"
        " ORDER BY [excess_value_usd] DESC".format(
            RC=ROW_COLS, F=F, SH=SHOPS, P=ov, S=s
        )
    )
    out["rule7_by_store"] = q(
        "EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS({F}[LOC_CODE],"
        ' "rows", COUNTROWS({F}),'
        ' "excess_value_usd", SUM({F}[EXCESS_STOCK_VALUE]),'
        ' "pending_value_usd", SUM({F}[PENDING_ORDERS_VALUE])),'
        " {F}[LOC_CODE] IN {SH},{P}{S})".format(F=F, SH=SHOPS, P=ov, S=s)
    )

    # Rule 8 - selling at the cheapest price the window has seen. The price
    # spread and floor tests are the rule's own; both prices are local.
    out["rule8_rows"] = q(
        "EVALUATE VAR Base = ADDCOLUMNS(CALCULATETABLE(SUMMARIZE({F},"
        " {F}[SKU_CODE], {F}[PART_DESCRIPTION], {F}[CATEGORY_NAME], {F}[DEPARTMENT],"
        " {F}[LOC_CODE], {F}[SKUSEGMENT]), {F}[LOC_CODE] IN {SH}{S}),"
        ' "rp_local", CALCULATE(MAX(CURR_RP_SALES_DAYS[RP])),'
        ' "min_rp_local", CALCULATE(MIN({T}[min_rp])),'
        ' "max_rp_local", CALCULATE(MAX({T}[max_rp])),'
        ' "price_days", CALCULATE(MAX(CURR_RP_SALES_DAYS[SALES_DAYS])),'
        ' "sales_3m_local", CALCULATE(SUM({F}[SALES_VALUE_LAST_3MONTHS])),'
        ' "qty_3m", CALCULATE(SUM({F}[SALES_QTY_LAST_3MONTHS])))'
        " VAR AtFloor = FILTER(Base,"
        " NOT ISBLANK([rp_local]) && NOT ISBLANK([max_rp_local]) && [max_rp_local] > 0"
        " && ([max_rp_local] - [min_rp_local]) > [min_rp_local] * 0.03"
        " && [rp_local] <= [min_rp_local] * 1.001)"
        " RETURN TOPN(10, AtFloor, [sales_3m_local], DESC)"
        " ORDER BY [sales_3m_local] DESC".format(
            F=F, T=T, SH=SHOPS, S=s
        )
    )
    return out


def featured_story(sku, loc):
    """Everything the model holds about one product - the complete story."""
    story = {"sku": sku, "home_loc": loc}
    story["by_location"] = q(
        "EVALUATE CALCULATETABLE(SELECTCOLUMNS({F},"
        ' "loc", {F}[LOC_CODE], "loc_type", {F}[LOC_TYPE],'
        ' "status", {F}[SKU_STOCK_STATUS], "action", {F}[RECOMMENDED_ACTION],'
        ' "segment", {F}[SKUSEGMENT], "top_in_cat", {F}[TOP_SKU_IN_CAT],'
        ' "stock_qty", {F}[CURRENT_STOCK], "stock_value_usd", {F}[SKU_STOCK_VALUE],'
        ' "sales_1m_local", {F}[SALES_VALUE_LAST_1MONTH], "qty_1m", {F}[SALES_QTY_LAST_1MONTH],'
        ' "sales_3m_local", {F}[SALES_VALUE_LAST_3MONTHS], "qty_3m", {F}[SALES_QTY_LAST_3MONTHS],'
        ' "avg_daily_qty", {F}[AVG_DAILY_SALES_QTY], "avg_daily_value_usd", {F}[AVG_DAILY_SALES_VALUE],'
        ' "reorder", {F}[REORDER_LEVEL], "pending", {F}[PENDING_ORDERS],'
        ' "burnout_days", {F}[EXPECTED_BURNOUT_DAYS], "oos_days_3m", {F}[STOCK_OUT_DAYS_3MONTHS],'
        ' "active_days_3m", {F}[ACTIVE_DAYS_3MONTHS], "active_days_1m", {F}[ACTIVE_DAYS_1MONTH],'
        ' "days_from_last_sale", {F}[DAYS_FROM_LAST_SALES],'
        ' "days_from_last_stockout", {F}[DAYS_FROM_LAST_STOCKOUT],'
        ' "opp_day_local", {F}[OPP_LOSS_DUE_TO_STOCKOUT], "lead_days", {F}[AVG_LEAD_DAYS_LOCAL],'
        ' "lc_local", {F}[LC], "brand", {F}[BRAND_NAME], "supplier", {F}[SUPPLIER_NAME],'
        ' "section", {F}[SECTION], "category", {F}[CATEGORY_NAME], "department", {F}[DEPARTMENT],'
        ' "description", {F}[PART_DESCRIPTION], "sku_status", {F}[SKU_STATUS]),'
        ' {F}[SKU_CODE]="{S}")'.format(F=F, S=sku)
    )
    story["weekly"] = q(
        "EVALUATE CALCULATETABLE(SELECTCOLUMNS({W},"
        ' "loc", {W}[LOC_CODE], "week_no", {W}[WEEK_NO],'
        ' "week_start", {W}[week_start_date], "week_end", {W}[week_end_date],'
        ' "qty", {W}[sales_qty]),'
        ' {W}[SKU]="{S}")'.format(W=W, S=sku)
    )
    story["best_days"] = q(
        "EVALUATE CALCULATETABLE(SELECTCOLUMNS({T},"
        ' "loc", {T}[LOC_CODE], "date", {T}[doc_date], "rank", {T}[RNK],'
        ' "value_usd", {T}[sales_value], "qty", {T}[sales_quantity],'
        ' "min_rp_local", {T}[min_rp], "max_rp_local", {T}[max_rp]),'
        ' {T}[SKU]="{S}")'.format(T=T, S=sku)
    )
    story["price"] = q(
        "EVALUATE CALCULATETABLE(SELECTCOLUMNS(CURR_RP_SALES_DAYS,"
        ' "loc", CURR_RP_SALES_DAYS[LOC_CODE], "rp_local", CURR_RP_SALES_DAYS[RP],'
        ' "price_days", CURR_RP_SALES_DAYS[SALES_DAYS]),'
        ' CURR_RP_SALES_DAYS[SKU]="{S}")'.format(S=sku)
    )
    # How its own category is doing, so the product can be placed against peers.
    story["category_peers"] = q(
        "EVALUATE TOPN(8, CALCULATETABLE(SUMMARIZECOLUMNS("
        "{F}[SKU_CODE], {F}[PART_DESCRIPTION],"
        ' "sales_3m_local", SUM({F}[SALES_VALUE_LAST_3MONTHS]),'
        ' "qty_3m", SUM({F}[SALES_QTY_LAST_3MONTHS]),'
        ' "stock_qty", SUM({F}[CURRENT_STOCK])),'
        " {F}[LOC_CODE] IN {SH},"
        ' {F}[CATEGORY_NAME]="{C}"), [sales_3m_local], DESC)'
        " ORDER BY [sales_3m_local] DESC".format(
            F=F, SH=SHOPS,
            C=story["by_location"][0]["category"].replace('"', '""'),
        )
    )
    return story


def main():
    print("scanning SKU OVERVIEW ...")
    meta = one(
        "EVALUATE ROW("
        ' "as_at", MAX({F}[UPDATED_ON]),'
        ' "rows_all_locations", COUNTROWS({F}),'
        ' "skus_all_locations", DISTINCTCOUNT({F}[SKU_CODE]),'
        ' "locations", DISTINCTCOUNT({F}[LOC_CODE]),'
        ' "departments", DISTINCTCOUNT({F}[DEPARTMENT]),'
        ' "categories", DISTINCTCOUNT({F}[CATEGORY_NAME]),'
        ' "sections", DISTINCTCOUNT({F}[SECTION]))'.format(F=F)
    )
    as_at = str(meta["as_at"])[:10]
    y, m, d = (int(x) for x in as_at.split("-"))
    # "Yesterday" is the day before the model's own as-at stamp, recomputed
    # every run rather than hardcoded.
    import datetime

    yday = datetime.date(y, m, d) - datetime.timedelta(days=1)
    anchor = (yday.year, yday.month, yday.day)
    meta["yesterday"] = yday.isoformat()
    meta["workspace"] = WORKSPACE
    meta["dataset"] = DATASET
    meta["report"] = REPORT
    meta["shops"] = ["ST1", "ST2", "ST3", "ST4", "ST5"]

    # The conversion rate the model itself already applies to its USD columns,
    # measured rather than assumed, so the facts module can put the local
    # columns onto the same basis.
    rate = one(
        "EVALUATE VAR B = FILTER(CALCULATETABLE({F}, {F}[LOC_CODE] IN {SH}),"
        " {F}[CURRENT_STOCK] > 0 && {F}[LC] > 0)"
        " VAR R = ADDCOLUMNS(B, \"ratio\","
        " DIVIDE({F}[SKU_STOCK_VALUE], {F}[CURRENT_STOCK] * {F}[LC]))"
        ' RETURN ROW("n", COUNTROWS(R), "median", MEDIANX(R, [ratio]),'
        ' "avg", AVERAGEX(R, [ratio]))'.format(F=F, SH=SHOPS)
    )
    opp_rate = one(
        "EVALUATE VAR B = FILTER(CALCULATETABLE({F}, {F}[LOC_CODE] IN {SH}),"
        " {F}[OPP_LOSS_DUE_TO_STOCKOUT] > 0 && {F}[AVG_DAILY_SALES_VALUE] > 0)"
        " VAR R = ADDCOLUMNS(B, \"ratio\","
        " DIVIDE({F}[OPP_LOSS_DUE_TO_STOCKOUT], {F}[AVG_DAILY_SALES_VALUE]))"
        ' RETURN ROW("n", COUNTROWS(R), "min", MINX(R, [ratio]), "max", MAXX(R, [ratio]))'.format(
            F=F, SH=SHOPS
        )
    )

    scan = {
        "meta": meta,
        "currency_evidence": {"stock_value_over_qty_x_lc": rate,
                              "opp_loss_over_avg_daily_value": opp_rate},
        "all": population(None, anchor),
        "sega": population("SEG_A", anchor),
    }

    # The featured product is chosen by the rule agreed with the business: the
    # top-band product with an empty shelf carrying the most sales behind it.
    # Picked by an explicit max rather than by taking the first row - TOPN
    # decides WHICH rows come back, never their order, so "the first row" is
    # not "the biggest" until it has been sorted.
    top = max(
        scan["all"]["rule4_rows"], key=lambda r: r.get("sales_3m_local") or 0.0
    )
    scan["featured"] = featured_story(top["SKU_CODE"], top["LOC_CODE"])

    # The warehouses, read only as the replenishment source.
    scan["warehouses"] = q(
        "EVALUATE CALCULATETABLE(SUMMARIZECOLUMNS({F}[LOC_CODE],"
        ' "rows", COUNTROWS({F}),'
        ' "stock_value_usd", SUM({F}[SKU_STOCK_VALUE]),'
        ' "stock_qty", SUM({F}[CURRENT_STOCK])),'
        ' NOT({F}[LOC_CODE] IN {SH}))'.format(F=F, SH=SHOPS)
    )

    out = HERE / "sku_overview_scan.json"
    out.write_text(json.dumps(scan, indent=1, default=str), encoding="utf-8")
    print("wrote %s (%d queries, as at %s)" % (out.name, _calls, as_at))


if __name__ == "__main__":
    main()
