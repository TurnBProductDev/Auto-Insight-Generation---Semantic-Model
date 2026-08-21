"""Derive every published figure of the Inventory Management reference page.

Everything comes from inventory_management_scan.json, read straight out of the
semantic model. No figure on the page is typed in by hand. The asserts are the
point: if the model stops reconciling, this refuses to produce facts at all.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(_HERE, "inventory_management_scan.json"),
                   encoding="utf8"))


def g(row, key):
    for k in row:
        if k == "[" + key + "]" or k.endswith("[" + key + "]"):
            return row[k]
    raise KeyError(key)


def num(row, key, default=0.0):
    v = g(row, key)
    return default if v is None else v


O = D["overall"]

# ---- headline -------------------------------------------------------------
SCORE = num(O, "Score")
LOST = num(O, "Lost")
STOCK = num(O, "Stock")
SKUS = int(num(O, "SKUs"))
ELIGIBLE = int(num(O, "Elig"))
SALES_BASE = num(O, "SalesBase")
AVG_SKU = num(O, "AvgSKU")

RISKS = [
    ("Excess", "Excess Stock", num(O, "Excess")),
    ("Ageing", "Ageing Stock", num(O, "Ageing")),
    ("Dead", "Dead Stock", num(O, "Dead")),
    ("OOS", "Out of Stock", num(O, "OOS")),
    ("Verge", "Verge of Stockout", num(O, "Verge")),
    ("Damage", "Damage", num(O, "Damage")),
]
assert abs(sum(r[2] for r in RISKS) - LOST) < 1e-9, "risks must sum to points lost"
assert abs(100 - LOST - SCORE) < 1e-9, "100 minus points lost must equal the score"


def share(pts):
    return pts / LOST * 100.0


# ---- per-risk detail ------------------------------------------------------
RD = {
    "Dead": dict(skus=int(num(O, "DeadSKU")), val=num(O, "DeadVal"),
                 dims=[("Value impact", num(O, "DeadValImp"), 0.5),
                       ("SKU breadth", num(O, "DeadSkuImp"), 0.3),
                       ("Duration", num(O, "DeadDurImp"), 0.2)]),
    "Excess": dict(skus=int(num(O, "ExcSKU")), val=num(O, "ExcVal"),
                   dims=[("Value impact", num(O, "ExcValImp"), 0.5),
                         ("SKU breadth", num(O, "ExcSkuImp"), 0.3),
                         ("Duration", num(O, "ExcDurImp"), 0.2)]),
    "Ageing": dict(skus=int(num(O, "AgeSKU")), val=num(O, "AgeVal"),
                   dims=[("Value impact", num(O, "AgeValImp"), 0.5),
                         ("SKU breadth", num(O, "AgeSkuImp"), 0.3),
                         ("Severity", num(O, "AgeSevImp"), 0.2)]),
    "Damage": dict(skus=int(num(O, "DmgSKU")), val=num(O, "DmgVal"),
                   dims=[("Value impact", num(O, "DmgValImp"), 0.7),
                         ("SKU breadth", num(O, "DmgSkuImp"), 0.3)]),
    "Verge": dict(skus=int(num(O, "VrgSKU")), val=num(O, "VrgVal"),
                  dims=[("Sales impact", num(O, "VrgSalImp"), 0.5),
                        ("SKU breadth", num(O, "VrgSkuImp"), 0.3),
                        ("Segment severity", num(O, "VrgSev"), 0.2)]),
    "OOS": dict(skus=int(num(O, "OosSKU")), val=num(O, "OosVal"),
                dims=[("Sales impact", num(O, "OosSalImp"), 0.5),
                      ("SKU breadth", num(O, "OosSkuImp"), 0.3),
                      ("Segment severity", num(O, "OosSev"), 0.2)]),
}
# every risk must reconcile to 25 * weighted sum of its own dimensions
for _key, _pts in [(r[0], r[2]) for r in RISKS]:
    _calc = min(25.0, 25.0 * sum(v * w for _, v, w in RD[_key]["dims"]))
    assert abs(_calc - _pts) < 1e-6, (_key, _calc, _pts)

# ---- stores, departments, sections ---------------------------------------
STORES = sorted(D["by_store"], key=lambda r: g(r, "LOC_CODE"))
DEPTS = sorted(D["by_department"], key=lambda r: num(r, "Score"))
SECTS = sorted(D["by_section"], key=lambda r: num(r, "Score"))
assert abs(sum(num(r, "Stock") for r in STORES) - STOCK) < 0.01
assert abs(sum(num(r, "Stock") for r in DEPTS) - STOCK) < 0.01
assert sum(int(num(r, "SKUs")) for r in DEPTS) == SKUS

# ---- trend (real, from SSR TREND) ----------------------------------------
_t = {}
for r in D["trend"]:
    _t.setdefault(str(g(r, "dates"))[:10], {})[g(r, "loc_code")] = num(r, "v")
TREND_DATES = sorted(_t)
STORE_TREND = {}
for _loc in [g(r, "LOC_CODE") for r in STORES]:
    STORE_TREND[_loc] = [_t[d].get(_loc, 0.0) for d in TREND_DATES]
TREND_STORE_TOTAL = [sum(v for k, v in _t[d].items() if str(k).startswith("ST"))
                     for d in TREND_DATES]

# ---- action queue ---------------------------------------------------------
QUEUE_ORDER = [
    ("STOCK OUT - PLACE ORDER", "Stock out &mdash; place order", "act", "most urgent"),
    ("STOCK OUT - AVAILABLE IN WAREHOUSE", "Stock out &mdash; held in a warehouse", "act", "free fix"),
    ("STOCK OUT - ORDER PLACED", "Stock out &mdash; order placed", "act", None),
    ("ON THE VERGE OF STOCK OUT - PLACE ORDER", "On the verge &mdash; place order", "act", None),
    ("ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE", "On the verge &mdash; held in a warehouse", "act", None),
    ("ON THE VERGE OF STOCK OUT - ORDER PLACED", "On the verge &mdash; order placed", "act", None),
    ("OVERSTOCK", "Overstock", "act", None),
    ("NON MOVING", "Not moving", "act", None),
    ("IN STOCK BUT NO SALES", "In stock but no sales", "act", None),
    ("STOCK AVAILABLE - REORDER LEVEL UNKNOW", "In stock, reorder level not set", "gap", None),
    ("STOCK AVAILABLE", "Stock available", "ok", None),
    ("NOT ACTIVE", "Not active", "ok", None),
    ("NA", "Reorder level unknown", "gap", None),
    ("NEW LISTED SKU", "Newly listed", "ok", None),
]
_q = {g(r, "RECOMMENDED_ACTION"): r for r in D["queue"]}
assert set(_q) == set(k for k, _a, _b, _c in QUEUE_ORDER)
QUEUE = []
for _key, _label, _kind, _tag in QUEUE_ORDER:
    _r = _q[_key]
    QUEUE.append(dict(key=_key, label=_label, kind=_kind, tag=_tag,
                      n=int(num(_r, "n")), val=num(_r, "val"),
                      po=num(_r, "po"), opp=num(_r, "opp"), exc=num(_r, "exc")))
assert sum(x["n"] for x in QUEUE) == SKUS, "the queue must account for every line"
NEEDS = [x for x in QUEUE if x["kind"] == "act"]
NEEDS_N = sum(x["n"] for x in NEEDS)
NEEDS_VAL = sum(x["val"] for x in NEEDS)
GAP = [x for x in QUEUE if x["kind"] == "gap"]
GAP_N = sum(x["n"] for x in GAP)
GAP_VAL = sum(x["val"] for x in GAP)
OK_N = sum(x["n"] for x in QUEUE if x["kind"] == "ok")
REST_N = SKUS - NEEDS_N
REST_VAL = STOCK - NEEDS_VAL
assert NEEDS_N + GAP_N + OK_N == SKUS

# ---- SKU health status ----------------------------------------------------
_hs = {g(r, "Health Status"): r for r in D["health_status"]}
HS_ORDER = ["Excellent", "Healthy", "Watch", "At Risk", "Critical", "Out of Stock"]
HEALTH = [dict(name=k, n=int(num(_hs[k], "n")), val=num(_hs[k], "val"),
               avg=num(_hs[k], "avg")) for k in HS_ORDER]
assert sum(x["n"] for x in HEALTH) == SKUS

# ---- age bands ------------------------------------------------------------
AGE_ORDER = ["0-03 MONTHS", "03-06 MONTHS", "06-09 MONTHS",
             "09-12 MONTHS", "12-24 MONTHS", "24+ MONTHS"]
_ab = {g(r, "NEW AGE"): num(r, "val") for r in D["age_bands_store"]}
AGE = [(k, _ab[k]) for k in AGE_ORDER]
AGE_TOTAL = sum(v for _k, v in AGE)
AGE_OVER3 = sum(v for k, v in AGE if k != "0-03 MONTHS")
AGE_OVER12 = _ab["12-24 MONTHS"] + _ab["24+ MONTHS"]

# ---- non-moving bands -----------------------------------------------------
NM_ORDER = ["30-60", "61-90", "91-120", "121-150", "151-180", ">180"]
_nm = {g(r, "NM DAYS TAG"): r for r in D["nm_bands"]}
NM = [(k, int(num(_nm[k], "n")), num(_nm[k], "val")) for k in NM_ORDER]
NM_180_N = int(num(_nm[">180"], "n"))
NM_180_VAL = num(_nm[">180"], "val")
NM_SHORT_N = int(num(_nm["30-60"], "n")) + int(num(_nm["61-90"], "n"))

# ---- damage ---------------------------------------------------------------
DAMAGE = sorted(((str(g(r, "month_date"))[:10], num(r, "val"), int(num(r, "n")))
                 for r in D["damage_month"]), key=lambda x: x[0])

# ---- segments -------------------------------------------------------------
_sg = {g(r, "SKU_SEGEMENT"): r for r in D["segments"]}
PRIME_OOS = int(num(_sg["SEG_A"], "oos")) + int(num(_sg["SEG_B"], "oos"))
OPP_SCOPED = num(D["opp_loss"], "scoped")

# ---- warehouses (present in the data, not scored) ------------------------
WH = [dict(loc=g(r, "LOC_CODE"), n=int(num(r, "n")), val=num(r, "val"),
           exc=num(r, "exc"), nm=int(num(r, "nm")), nmval=num(r, "nmval"))
      for r in D["wh_summary"]]
WH_VAL = sum(x["val"] for x in WH)

# ---- excess duration ------------------------------------------------------
EXC_DAYS = {g(r, "LOC_CODE"): num(r, "avgdays") for r in D["excess_days_dist"]}
EXC_BY_STORE = {g(r, "LOC_CODE"): num(r, "excval") for r in D["excess_days_dist"]}

if __name__ == "__main__":
    print("score %.4f  lost %.4f  stock %.2f  skus %d  eligible %d"
          % (SCORE, LOST, STOCK, SKUS, ELIGIBLE))
    for k, name, pts in RISKS:
        print("  %-18s %6.3f pts  %5.2f%% of loss  lines %6d  value %12.2f"
              % (name, pts, share(pts), RD[k]["skus"], RD[k]["val"]))
    print("queue lines", sum(x["n"] for x in QUEUE), "needs", NEEDS_N, "rest", REST_N)
    print("age total %.2f  over3 %.2f  over12 %.2f" % (AGE_TOTAL, AGE_OVER3, AGE_OVER12))
    print("trend dates", TREND_DATES)
    print("ST5 trend", [round(v) for v in STORE_TREND["ST5"]])
    print("prime oos", PRIME_OOS, "opp %.2f" % OPP_SCOPED, "wh val %.2f" % WH_VAL)
    print("nm >180", NM_180_N, "vs short bands", NM_SHORT_N)
