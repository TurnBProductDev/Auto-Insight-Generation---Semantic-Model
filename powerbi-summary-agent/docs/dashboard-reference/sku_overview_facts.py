"""Derive every figure the SKU Overview reference page publishes.

    python sku_overview_facts.py        # prints the fact sheet

Reads sku_overview_scan.json and nothing else. The builder imports `facts()`;
nothing on the page is typed by hand.

THE ONE THING THIS MODULE EXISTS FOR: the model publishes money on two different
bases, and putting them on one page without converting would compare numbers
that are 3.7x apart. Every `*_local` figure is multiplied by RATE here, in one
place, and the result is USD. Nothing downstream converts anything.

It refuses to produce facts at all if the model stops reconciling - a page built
on figures that do not add up is worse than no page.
"""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SCAN = HERE / "sku_overview_scan.json"

# The rate the model itself already applied to its USD columns. Measured from
# the scan, not chosen: SKU_STOCK_VALUE / (CURRENT_STOCK x LC) is 0.27 to the
# median across 93,904 rows. Using the true peg instead would put sales on a
# different basis from stock and the page would not add up against itself.
RATE = 0.27

SHOPS = ["ST1", "ST2", "ST3", "ST4", "ST5"]


class ModelDoesNotReconcile(Exception):
    """Raised rather than publishing figures that do not add up."""


def usd(local):
    """Local currency -> USD, the only place this conversion happens."""
    if local is None:
        return 0.0
    return float(local) * RATE


def num(v):
    return 0.0 if v is None else float(v)


_UNITS = ("gm", "kg", "ltr", "ml", "mm", "cm", "pcs", "w", "kw")


def pretty(name):
    """Make a shouted product name readable without inventing anything.

    The model stores names in capitals with a trailing pack code. Title-casing
    alone turns 1300GM into 1300Gm, so unit suffixes are put back down and
    runs of whitespace are collapsed. No word is added or removed.
    """
    import re

    s = re.sub(r"\s+", " ", str(name).strip()).title()
    for u in _UNITS:
        s = re.sub(r"(\d)%s\b" % u.title(), r"\1" + u, s)
    return s


def load():
    return json.loads(SCAN.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# reconciliation - run before anything is published
# --------------------------------------------------------------------------

def _close(a, b, tol=0.02):
    return abs(float(a) - float(b)) <= tol


def reconcile(scan):
    """Prove the scan adds up. Returns the checks; raises if one fails."""
    checks = []

    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    for scope in ("all", "sega"):
        pop = scan[scope]
        tot = pop["totals"]
        for key, field in (("by_department", "DEPARTMENT"), ("by_store", "LOC_CODE"),
                           ("by_action", "RECOMMENDED_ACTION")):
            for col in ("rows", "stock_value_usd", "sales_3m_local", "excess_value_usd"):
                parts = sum(num(r.get(col)) for r in pop[key])
                whole = num(tot.get(col))
                check(
                    "%s / %s sums to the total on %s" % (scope, key, col),
                    _close(parts, whole, max(0.02, abs(whole) * 1e-9)),
                    "parts %.4f vs whole %.4f" % (parts, whole),
                )

        # The five shops are the whole population - nothing else is in a total.
        stores = {r["LOC_CODE"] for r in pop["by_store"]}
        check("%s / only the five shops are in scope" % scope,
              stores == set(SHOPS), sorted(stores))

        # A stockout holds no stock. If this ever fails the status column has
        # stopped meaning what the rules document says it means.
        check("%s / out-of-stock lines hold no stock" % scope,
              _close(num(pop["rule4_totals"]["stock_value_usd"]), 0.0),
              pop["rule4_totals"]["stock_value_usd"])

        # Excess is the surplus above cover, never the whole holding.
        r7 = pop["rule7_totals"]
        check("%s / excess is smaller than the stock it sits in" % scope,
              num(r7["excess_value_usd"]) <= num(r7["stock_value_usd"]) + 0.02,
              "excess %.2f vs stock %.2f" % (num(r7["excess_value_usd"]),
                                             num(r7["stock_value_usd"])))

    # The currency evidence itself, so a model change cannot silently move the
    # rate out from under the page.
    ev = scan["currency_evidence"]
    check("stock value is local x 0.27",
          _close(ev["stock_value_over_qty_x_lc"]["median"], RATE, 0.001),
          ev["stock_value_over_qty_x_lc"])
    opp = ev["opp_loss_over_avg_daily_value"]
    check("opportunity loss is exactly one day, on the local basis",
          _close(opp["min"], 1 / RATE, 1e-6) and _close(opp["max"], 1 / RATE, 1e-6),
          opp)

    # The featured product must be the biggest thing on the stockout list, or
    # the page's lead story is not the story the selection rule promises.
    feat = scan["featured"]
    biggest = max(scan["all"]["rule4_rows"],
                  key=lambda r: num(r.get("sales_3m_local")))
    check("the featured product is the largest stockout",
          biggest["SKU_CODE"] == feat["sku"] and biggest["LOC_CODE"] == feat["home_loc"],
          "%s @ %s" % (biggest["SKU_CODE"], biggest["LOC_CODE"]))

    bad = [c for c in checks if not c["ok"]]
    if bad:
        raise ModelDoesNotReconcile(
            "the model no longer reconciles; refusing to publish figures:\n"
            + "\n".join("  - %s (%s)" % (c["name"], c["detail"]) for c in bad)
        )
    return checks


# --------------------------------------------------------------------------
# the featured product - one product's complete story
# --------------------------------------------------------------------------

def featured(scan):
    f = scan["featured"]
    rows = f["by_location"]
    head = rows[0]
    home = f["home_loc"]

    shops = [r for r in rows if r["loc"] in SHOPS]
    depots = [r for r in rows if r["loc"] not in SHOPS]
    shops.sort(key=lambda r: -num(r["sales_3m_local"]))

    here = next(r for r in shops if r["loc"] == home)

    weekly = {}
    for w in f["weekly"]:
        weekly.setdefault(w["loc"], []).append(w)
    for loc in weekly:
        weekly[loc].sort(key=lambda w: w["week_start"])

    best = {}
    for b in f["best_days"]:
        best.setdefault(b["loc"], []).append(b)
    for loc in best:
        best[loc].sort(key=lambda b: b["rank"])

    price = {p["loc"]: p for p in f["price"]}

    # The three states this one product is in at the same time. This is the
    # whole point of the layer: one product, three different problems.
    def state(r):
        if r["stock_qty"] == 0:
            return "empty"
        if num(r["days_from_last_sale"]) >= 30:
            return "stalled"
        if num(r["burnout_days"]) and num(r["burnout_days"]) <= 7:
            return "running out"
        return "trading"

    for r in shops:
        r["state"] = state(r)
        r["sales_3m_usd"] = usd(r["sales_3m_local"])
        r["sales_1m_usd"] = usd(r["sales_1m_local"])
        r["opp_day_usd"] = usd(r["opp_day_local"])
        r["price_local"] = price.get(r["loc"], {}).get("rp_local")
        r["weekly"] = weekly.get(r["loc"], [])
        r["best_days"] = best.get(r["loc"], [])

    for r in depots:
        r["sales_3m_usd"] = usd(r["sales_3m_local"])
        r["opp_day_usd"] = usd(r["opp_day_local"])

    total_3m = sum(r["sales_3m_usd"] for r in shops)
    total_qty_3m = sum(num(r["qty_3m"]) for r in shops)

    # The four-week run at the shop that is out of stock. The model holds only
    # four weeks, so this is stated as four weeks and never called a trend.
    run = here["weekly"]
    run_first = num(run[0]["qty"]) if run else 0.0
    run_last = num(run[-1]["qty"]) if run else 0.0

    peers = sorted(scan["featured"]["category_peers"],
                   key=lambda r: -num(r["sales_3m_local"]))
    rank = next((i + 1 for i, p in enumerate(peers)
                 if p["SKU_CODE"] == f["sku"]), None)

    return {
        "sku": f["sku"],
        "name": pretty(head["description"]),
        "raw_name": head["description"],
        "department": head["department"],
        "section": pretty(head["section"]),
        "category": pretty(head["category"]),
        "brand": head["brand"],
        "supplier": head["supplier"],
        "segment": head["segment"],
        "top_in_category": head["top_in_cat"] == "Y",
        "home": home,
        "here": here,
        "shops": shops,
        "depots": depots,
        "shops_carrying": len(shops),
        "total_3m_usd": total_3m,
        "total_qty_3m": total_qty_3m,
        "empty": [r for r in shops if r["state"] == "empty"],
        "stalled": [r for r in shops if r["state"] == "stalled"],
        "running_out": [r for r in shops if r["state"] == "running out"],
        "run": run,
        "run_first": run_first,
        "run_last": run_last,
        "run_drop_pct": (100.0 * (run_last - run_first) / run_first) if run_first else None,
        "peers": [
            dict(p, name=pretty(p["PART_DESCRIPTION"]),
                 sales_3m_usd=usd(p["sales_3m_local"]),
                 is_this=p["SKU_CODE"] == f["sku"])
            for p in peers
        ],
        "rank_in_category": rank,
        "best_day": (max(f["best_days"], key=lambda b: num(b["value_usd"]))
                     if f["best_days"] else None),
    }


# --------------------------------------------------------------------------
# the eight findings
# --------------------------------------------------------------------------

def _pick(r, *names):
    """The model returns a column's name with the case the table declares it,
    and the same idea is spelled LOC_CODE in one table and loc_code in another.
    """
    for n in names:
        if r.get(n) is not None:
            return r[n]
    return None


def _rows(raw, extra=None):
    out = []
    for r in raw:
        d = {
            "sku": _pick(r, "SKU_CODE", "SKU", "sku"),
            "name": pretty(_pick(r, "PART_DESCRIPTION") or ""),
            "category": pretty(_pick(r, "CATEGORY_NAME") or ""),
            "department": _pick(r, "DEPARTMENT"),
            "loc": _pick(r, "LOC_CODE", "loc_code"),
            "segment": _pick(r, "SKUSEGMENT"),
        }
        for k, v in r.items():
            if k.endswith("_local"):
                d[k[:-6] + "_usd"] = usd(v)
            d[k] = v
        out.append(d)
    return out


def findings(scan, scope):
    pop = scan[scope]
    tot = pop["totals"]
    r4, r5 = pop["rule4_totals"], pop["rule5_totals"]
    r6, r7 = pop["rule6_totals"], pop["rule7_totals"]

    def by_store(key):
        out = []
        for r in pop[key]:
            d = {"loc": _pick(r, "LOC_CODE", "loc_code"),
                 "rows": int(num(r.get("rows")))}
            for k, v in r.items():
                if k.endswith("_local"):
                    d[k[:-6] + "_usd"] = usd(v)
                elif k.endswith("_usd"):
                    d[k] = num(v)
            out.append(d)
        return sorted(out, key=lambda r: -r["rows"])

    top_by_dept = {}
    for dept, rows in pop["rule1_top_by_department"].items():
        top_by_dept[dept] = _rows(
            sorted(rows, key=lambda r: -num(r.get("sales_1m_local")))
        )

    return {
        "totals": {
            "rows": int(num(tot["rows"])),
            "skus": int(num(tot["skus"])),
            "stock_value_usd": num(tot["stock_value_usd"]),
            "stock_qty": num(tot["stock_qty"]),
            "excess_value_usd": num(tot["excess_value_usd"]),
            "sales_1m_usd": usd(tot["sales_1m_local"]),
            "sales_3m_usd": usd(tot["sales_3m_local"]),
            "qty_3m": num(tot["qty_3m"]),
            "opp_day_usd": usd(tot["opp_day_local"]),
        },
        "by_department": sorted(
            [
                {
                    "name": r["DEPARTMENT"],
                    "rows": int(num(r["rows"])),
                    "skus": int(num(r["skus"])),
                    "sales_1m_usd": usd(r["sales_1m_local"]),
                    "sales_3m_usd": usd(r["sales_3m_local"]),
                    "stock_value_usd": num(r["stock_value_usd"]),
                    "excess_value_usd": num(r["excess_value_usd"]),
                }
                for r in pop["by_department"]
            ],
            key=lambda r: -r["sales_1m_usd"],
        ),
        "by_store": sorted(
            [
                {
                    "name": r["LOC_CODE"],
                    "rows": int(num(r["rows"])),
                    "skus": int(num(r["skus"])),
                    "sales_1m_usd": usd(r["sales_1m_local"]),
                    "sales_3m_usd": usd(r["sales_3m_local"]),
                    "stock_value_usd": num(r["stock_value_usd"]),
                    "excess_value_usd": num(r["excess_value_usd"]),
                }
                for r in pop["by_store"]
            ],
            key=lambda r: r["name"],
        ),
        "by_action": sorted(
            [
                {
                    "name": r["RECOMMENDED_ACTION"],
                    "rows": int(num(r["rows"])),
                    "stock_value_usd": num(r["stock_value_usd"]),
                    "sales_3m_usd": usd(r["sales_3m_local"]),
                }
                for r in pop["by_action"]
            ],
            key=lambda r: -r["rows"],
        ),
        # 1 - best sellers
        "top_sellers": top_by_dept,
        # 3 - yesterday's standouts
        "standouts": _rows(pop["rule3_rows"]),
        "standout_pairs": int(num(pop["rule3_count"].get("pairs"))),
        "standout_value_usd": num(pop["rule3_count"].get("value_usd")),
        # 4 - top band, empty shelf
        "stockout": {
            "rows": int(num(r4["rows"])),
            "skus": int(num(r4["skus"])),
            "sales_3m_usd": usd(r4["sales_3m_local"]),
            "opp_day_usd": usd(r4["opp_day_local"]),
            "with_estimate": int(num(pop["rule4_opp_coverage"]["with_opp"])),
            "of_rows": int(num(pop["rule4_opp_coverage"]["rows"])),
            "list": _rows(pop["rule4_rows"]),
        },
        # 5 - nearly out, stock upstream
        "refill": {
            "rows": int(num(r5["rows"])),
            "skus": int(num(r5["skus"])),
            "sales_3m_usd": usd(r5["sales_3m_local"]),
            "stock_value_usd": num(r5["stock_value_usd"]),
            "list": _rows(pop["rule5_rows"]),
            "by_store": by_store("rule5_by_store"),
        },
        # 6 - not selling, more on order
        "dead_on_order": {
            "rows": int(num(r6["rows"])),
            "pending_value_usd": num(r6["pending_value_usd"]),
            "pending_qty": num(r6["pending_qty"]),
            "list": _rows(pop["rule6_rows"]),
            "by_store": by_store("rule6_by_store"),
        },
        # 7 - too much already, more on order
        "surplus_on_order": {
            "rows": int(num(r7["rows"])),
            "excess_value_usd": num(r7["excess_value_usd"]),
            "stock_value_usd": num(r7["stock_value_usd"]),
            "pending_value_usd": num(r7["pending_value_usd"]),
            "list": _rows(pop["rule7_rows"]),
            "by_store": by_store("rule7_by_store"),
        },
        # 8 - marked down to the floor
        "markdowns": _rows(pop["rule8_rows"]),
    }


def facts():
    scan = load()
    checks = reconcile(scan)
    meta = scan["meta"]
    return {
        "meta": {
            "as_at": str(meta["as_at"])[:10],
            "yesterday": meta["yesterday"],
            "workspace": meta["workspace"],
            "dataset": meta["dataset"],
            "report": meta["report"],
            "shops": meta["shops"],
            "departments": int(meta["departments"]),
            "categories": int(meta["categories"]),
            "sections": int(meta["sections"]),
            "rate": RATE,
        },
        "checks": checks,
        "all": findings(scan, "all"),
        "sega": findings(scan, "sega"),
        "featured": featured(scan),
        "warehouses": [
            {"name": r["LOC_CODE"], "rows": int(num(r["rows"])),
             "stock_value_usd": num(r["stock_value_usd"])}
            for r in scan["warehouses"]
        ],
    }


def money(v, dp=0):
    return "USD {:,.{dp}f}".format(v, dp=dp)


def main():
    f = facts()
    m, a, ft = f["meta"], f["all"], f["featured"]
    print("SKU OVERVIEW - fact sheet, as at %s" % m["as_at"])
    print("  %d checks, all passing" % len(f["checks"]))
    print("  rate applied to local columns: %.2f" % m["rate"])
    t = a["totals"]
    print("\nTHE POSITION (%s)" % ", ".join(m["shops"]))
    print("  %-34s %s" % ("product-shop lines", "{:,}".format(t["rows"])))
    print("  %-34s %s" % ("products", "{:,}".format(t["skus"])))
    print("  %-34s %s" % ("stock on hand", money(t["stock_value_usd"])))
    print("  %-34s %s" % ("sold, last 4 weeks", money(t["sales_1m_usd"])))
    print("  %-34s %s" % ("sold, last 3 months", money(t["sales_3m_usd"])))
    print("  %-34s %s per day" % ("sales being missed", money(t["opp_day_usd"])))

    print("\nTHE EIGHT FINDINGS")
    so, rf = a["stockout"], a["refill"]
    do, su = a["dead_on_order"], a["surplus_on_order"]
    print("  1 best sellers      top 3 in each of %d departments" % m["departments"])
    print("  2 rank movers       NOT AVAILABLE - the model keeps no rank history")
    print("  3 yesterday's best  %s lines had their best day, %s"
          % ("{:,}".format(a["standout_pairs"]), money(a["standout_value_usd"])))
    print("  4 empty shelf       %s lines, %s of sales behind them, %s/day missed"
          % ("{:,}".format(so["rows"]), money(so["sales_3m_usd"]), money(so["opp_day_usd"])))
    print("  5 free refill       %s lines, %s of sales behind them"
          % ("{:,}".format(rf["rows"]), money(rf["sales_3m_usd"])))
    print("  6 dead, on order    %s lines, %s arriving"
          % ("{:,}".format(do["rows"]), money(do["pending_value_usd"])))
    print("  7 surplus, on order %s lines, %s surplus, %s arriving"
          % ("{:,}".format(su["rows"]), money(su["excess_value_usd"]),
             money(su["pending_value_usd"])))
    print("  8 marked down       %d products at their lowest price" % len(a["markdowns"]))

    print("\nTHE FEATURED PRODUCT")
    print("  %s (%s)" % (ft["name"], ft["sku"]))
    print("  %s / %s / %s" % (ft["department"], ft["section"], ft["category"]))
    print("  in %d shops, %s over 3 months, %s units"
          % (ft["shops_carrying"], money(ft["total_3m_usd"]),
             "{:,.0f}".format(ft["total_qty_3m"])))
    for r in ft["shops"]:
        print("    %-4s %-12s stock %-7s %s over 3 months%s"
              % (r["loc"], r["state"], "{:,.0f}".format(num(r["stock_qty"])),
                 money(r["sales_3m_usd"]),
                 "  (%s/day missed)" % money(r["opp_day_usd"], 2)
                 if r["opp_day_usd"] else ""))
    if ft["run"]:
        print("  four weeks at %s: %s"
              % (ft["home"], " -> ".join("%.0f" % num(w["qty"]) for w in ft["run"])))


if __name__ == "__main__":
    main()
