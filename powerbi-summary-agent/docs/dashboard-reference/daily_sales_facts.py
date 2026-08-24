"""Every figure the Daily Sales reference publishes, derived from daily_sales_scan.json.

Nothing here is typed by hand. The module refuses to produce facts at all if the
model does not reconcile, so a wrong number fails the build rather than shipping.

Rules enforced in code (see the Daily Sales Dashboard rulebook):
  BR-05  below P20 underperforming, above P80 outperforming, inside is neutral
  BR-08  actuals add across the two stores; a group band is derived, never stored
  BR-10  Basket Value and its benchmark are both Net Sales / Bills, same level
  BR-11  margin is revenue-weighted, never summed and never plain-averaged
  BR-12  department penetration = department Bills / total Bills, both stores
  BR-13  percentiles are per level and never add up
  BR-14  Bills overlap across levels and inside a level - never a clean count
  BR-17  rank a finding by the size of the gap in SAR, not by the percentage
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent
SCAN = HERE / "daily_sales_scan.json"

CURRENCY = "SAR"

# The store table publishes Net Sales at this scale; the department, section and
# category tables are at unit scale. Everything is brought onto the published
# scale so one page reads coherently. reconcile() proves the relationship holds
# on every store-day rather than assuming it.
PUBLISHED_SCALE = 0.27

BELOW, IN, ABOVE = "below", "in", "above"
VERDICT_WORD = {BELOW: "Underperforming", IN: "In band", ABOVE: "Outperforming"}

# The benchmark columns are stored to two decimals, so a comparison finer than that is
# noise, not a finding. Without this a store whose Net Sales equals its own P20 to the
# cent lands 4e-12 under it and is flagged as underperforming - which BR-17 would call
# nobody's business, and which is an artefact of binary floating point, not of trading.
EDGE_TOLERANCE = 0.005


def money(unit_value):
    """Bring a unit-scale figure onto the published scale."""
    return None if unit_value is None else unit_value * PUBLISHED_SCALE


def load() -> dict:
    return json.loads(SCAN.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- readings ---

@dataclass
class Reading:
    """One measure for one thing, placed against its own band (BR-05)."""
    key: str
    label: str
    unit: str                      # "money" | "count" | "pct"
    actual: float | None
    p20: float | None
    p50: float | None
    p80: float | None
    derived_band: bool = False     # band built from other bands (BR-08 / BR-10)
    summed_band: bool = False      # band is a sum of sub-group bands (BR-13)

    @property
    def verdict(self):
        if self.actual is None or self.p20 is None or self.p80 is None:
            return None
        tol = 0 if self.unit == "count" else EDGE_TOLERANCE
        if self.actual < self.p20 - tol:
            return BELOW
        if self.actual > self.p80 + tol:
            return ABOVE
        return IN

    @property
    def on_edge(self):
        """Level with a band edge to the stored precision - inside it, but worth saying."""
        if self.actual is None or self.p20 is None:
            return None
        tol = 0.005 if self.unit != "count" else 0
        if abs(self.actual - self.p20) <= tol:
            return "floor"
        if abs(self.actual - self.p80) <= tol:
            return "ceiling"
        return None

    @property
    def word(self) -> str:
        return VERDICT_WORD.get(self.verdict, "Not comparable")

    @property
    def vs_p50(self):
        if self.actual is None or self.p50 is None:
            return None
        return self.actual - self.p50

    @property
    def vs_p50_pct(self):
        if self.vs_p50 is None or not self.p50:
            return None
        return self.vs_p50 / self.p50 * 100

    @property
    def gap(self) -> float:
        """Signed distance outside the band; 0 inside it. BR-18 quotes this."""
        v = self.verdict
        if v == BELOW:
            return self.actual - self.p20
        if v == ABOVE:
            return self.actual - self.p80
        return 0.0

    @property
    def band_pos(self):
        """Where the actual sits: 0 at P20, 1 at P80. Clamped for drawing."""
        if self.actual is None or self.p20 is None or self.p80 is None:
            return None
        span = self.p80 - self.p20
        if span <= 0:
            return 0.5
        return max(-0.4, min(1.4, (self.actual - self.p20) / span))


def _weighted(num, den):
    if not den:
        return None
    return (num or 0.0) / den


def _basket_reading(sales: Reading, bills: Reading) -> Reading:
    """BR-10: Basket Value and its band are both Net Sales / Bills, one level."""
    def div(a, b):
        return (a / b) if (a is not None and b) else None
    return Reading(
        "basket", "Basket Value", "money",
        div(sales.actual, bills.actual),
        div(sales.p20, bills.p20), div(sales.p50, bills.p50), div(sales.p80, bills.p80),
        derived_band=True, summed_band=sales.summed_band,
    )


# --------------------------------------------------------------- the levels ---

@dataclass
class Entity:
    name: str
    store: str | None
    readings: dict
    band_rows: int = 1             # sub-group rows the band was added over (BR-13)
    live_rows: int = 1             # of those, the ones that recorded a sale today
    silent_p50: float = 0.0        # what the rows that recorded nothing usually take
    silent_bills_p50: int = 0
    sample_days: tuple = (0, 0)
    margin_sample_days: tuple = (0, 0)
    penetration: Reading | None = None
    parent: str | None = None
    extras: dict = field(default_factory=dict)

    def r(self, key: str) -> Reading:
        return self.readings[key]

    @property
    def below(self):
        return [x for x in self.readings.values() if x.verdict == BELOW]

    @property
    def above(self):
        return [x for x in self.readings.values() if x.verdict == ABOVE]

    @property
    def split_key(self) -> bool:
        """True when this name covers more than one sub-group row (BR-13/BR-14)."""
        return self.band_rows > 1

    @property
    def silent_rows(self) -> int:
        """Sub-groups under this name that recorded no sale at all today.

        Their benchmarks are deliberately kept out of the band above - a band
        summed over rows that could not contribute makes every merged name read
        below. They are reported on their own instead, because a group that
        normally sells and sold nothing is a finding, not a rounding error.
        """
        return max(0, self.band_rows - self.live_rows)


def _entity_from_rollup(name, store, row, parent=None) -> Entity:
    """Build an entity from an aggregated department / section / category row.

    Sales and cost are at unit scale here, so the margin is recovered as
    (sales - cost) / sales - which IS the revenue weighting BR-11 requires,
    exactly, with no sum of percentages anywhere.
    """
    sales_unit = row.get("actual_sales")
    cost_unit = row.get("actual_cost")
    margin_pct = None
    if sales_unit:
        margin_pct = (sales_unit - (cost_unit or 0.0)) / sales_unit * 100

    rows = int(row.get("row_count") or 1)
    sales = Reading("sales", "Net Sales", "money", money(sales_unit),
                    money(row.get("sales_p20")), money(row.get("sales_p50")),
                    money(row.get("sales_p80")), summed_band=rows > 1)
    bills = Reading("bills", "Bills", "count", row.get("actual_bills"),
                    row.get("bills_p20"), row.get("bills_p50"), row.get("bills_p80"),
                    summed_band=rows > 1)
    margin = Reading("margin", "Margin", "pct", margin_pct,
                     _weighted(row.get("margin_p20_num"), row.get("margin_p20_den")),
                     _weighted(row.get("margin_p50_num"), row.get("margin_p50_den")),
                     _weighted(row.get("margin_p80_num"), row.get("margin_p80_den")),
                     summed_band=rows > 1)
    basket = _basket_reading(sales, bills)

    return Entity(
        name=name, store=store, parent=parent,
        readings={"sales": sales, "bills": bills, "basket": basket, "margin": margin},
        band_rows=rows,
        live_rows=int(row.get("rows_with_actual") or 0),
        silent_p50=money(row.get("silent_p50")) or 0.0,
        silent_bills_p50=int(row.get("silent_bills_p50") or 0),
        sample_days=(row.get("sample_days_min") or 0, row.get("sample_days_max") or 0),
        margin_sample_days=(row.get("margin_sample_days_min") or 0,
                            row.get("margin_sample_days_max") or 0),
        extras={"rows_with_actual": int(row.get("rows_with_actual") or 0)},
    )


def _store_entity(day_rows, name, store) -> Entity:
    """Store, or the two-store total, for one day. Net Sales is already published.

    BR-08: the actuals add across the two stores because a bill belongs to one
    of them. The band is added the same way and marked derived - there is no
    stored group percentile, and percentiles do not add (BR-13).
    """
    def s(k):
        return sum((r.get(k) or 0.0) for r in day_rows)

    many = len(day_rows) > 1
    sales = Reading("sales", "Net Sales", "money", s("actual_sales"),
                    money(s("sales_p20")), money(s("sales_p50")), money(s("sales_p80")),
                    derived_band=many)
    bills = Reading("bills", "Bills", "count", int(s("actual_bills")),
                    int(s("bills_p20")), int(s("bills_p50")), int(s("bills_p80")),
                    derived_band=many)

    # BR-11: weight every margin by its own Net Sales, actual and benchmark alike.
    def wm(mk, wk):
        return _weighted(sum((r.get(mk) or 0.0) * (r.get(wk) or 0.0) for r in day_rows), s(wk))

    margin = Reading("margin", "Margin", "pct",
                     wm("actual_margin", "actual_sales"),
                     wm("margin_p20", "sales_p20"), wm("margin_p50", "sales_p50"),
                     wm("margin_p80", "sales_p80"), derived_band=many)
    basket = _basket_reading(sales, bills)

    return Entity(
        name=name, store=store,
        readings={"sales": sales, "bills": bills, "basket": basket, "margin": margin},
        sample_days=(min(r["sample_days"] for r in day_rows),
                     max(r["sample_days"] for r in day_rows)),
        margin_sample_days=(min(r["margin_sample_days"] for r in day_rows),
                            max(r["margin_sample_days"] for r in day_rows)),
    )


def _merge(rows, keys):
    """Add sub-group rows that share a name. Money adds; mins and maxes do not."""
    merged = {}
    for row in rows:
        k = tuple(row[x] for x in keys)
        tgt = merged.setdefault(k, {})
        for f, v in row.items():
            if not isinstance(v, (int, float)):
                continue
            if f.endswith("_min"):
                tgt[f] = min(tgt.get(f, v), v)
            elif f.endswith("_max"):
                tgt[f] = max(tgt.get(f, v), v)
            else:
                tgt[f] = tgt.get(f, 0) + v
    return merged


def _roll(scan, level, keys, store=None):
    rows = scan[level] if store is None else [r for r in scan[level] if r["store_no"] == store]
    out = []
    for k, row in _merge(rows, keys).items():
        parent = k[-2] if len(k) > 1 else None
        out.append(_entity_from_rollup(k[-1], store, row, parent))
    return [x for x in out if x.r("sales").actual is not None]


# ------------------------------------------------------------------- facts ---

def reconcile(scan: dict) -> dict:
    """Prove the model hangs together before any figure is published.

    Three independent checks, all of which have to hold:
      1. Department, Section and Category each add to the same day total.
      2. That total, on the published scale, is the store table's own Net Sales.
      3. Each store's stored margin is what its own cost and sales imply.
    """
    anchor = scan["anchor"]
    checks = []

    per_level = {}
    for level in ("departments", "sections", "categories"):
        tot = {}
        for row in scan[level]:
            tot[row["store_no"]] = tot.get(row["store_no"], 0.0) + (row.get("actual_sales") or 0.0)
        per_level[level] = tot

    base = per_level["departments"]
    for level in ("sections", "categories"):
        for st, v in per_level[level].items():
            ok = abs(v - base[st]) < 0.01
            checks.append((f"{level.capitalize()} add to the Departments total for {st}",
                           ok, base[st], v))
            if not ok:
                raise AssertionError(f"{level} do not reconcile for {st}: {v} vs {base[st]}")

    for row in scan["store_days"]:
        if row["tran_date"] != anchor:
            continue
        st = row["store_no"]
        expected = money(base[st])
        ok = abs(row["actual_sales"] - expected) < 0.01
        checks.append((f"Store Net Sales for {st} matches the levels below it",
                       ok, expected, row["actual_sales"]))
        if not ok:
            raise AssertionError(f"store total does not reconcile for {st}")

        implied = (base[st] - row["actual_cost"]) / base[st] * 100
        ok = abs(implied - row["actual_margin"]) < 0.01
        checks.append((f"Stored margin for {st} matches its own cost and sales",
                       ok, row["actual_margin"], implied))
        if not ok:
            raise AssertionError(f"margin does not reconcile for {st}")

    return {"anchor": anchor, "checks": checks}


def fmt_date(iso: str, style: str = "long") -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    dt = date(y, m, d)
    if style == "long":
        return f"{dt.strftime('%A')} {dt.day} {dt.strftime('%B %Y')}"
    if style == "short":
        return f"{dt.strftime('%a')} {dt.day}"
    return f"{dt.day} {dt.strftime('%b')}"


def build(scan: dict | None = None) -> dict:
    scan = scan or load()
    recon = reconcile(scan)
    anchor = scan["anchor"]

    day_rows = sorted((r for r in scan["store_days"] if r["tran_date"] == anchor),
                      key=lambda r: r["store_no"])
    stores = [r["store_no"] for r in day_rows]

    overall = _store_entity(day_rows, "Both stores", None)
    per_store = [_store_entity([r], r["store_no"], r["store_no"]) for r in day_rows]

    # ---- the 14-day run, both stores combined each day ----------------------
    by_date = {}
    for r in scan["store_days"]:
        by_date.setdefault(r["tran_date"], []).append(r)
    trend = []
    for d in sorted(by_date):
        e = _store_entity(by_date[d], d, None)
        trend.append({"date": d, "dow": by_date[d][0]["dow_name"],
                      "week_of_month": by_date[d][0]["week_of_month"], "e": e})

    store_trend = {
        st: [{"date": r["tran_date"], "dow": r["dow_name"], "e": _store_entity([r], st, st)}
             for r in sorted((x for x in scan["store_days"] if x["store_no"] == st),
                             key=lambda x: x["tran_date"])]
        for st in stores
    }

    # ---- levels below, on the anchor day ------------------------------------
    departments = _roll(scan, "departments", ["DEPARTMENT"])
    sections = _roll(scan, "sections", ["DEPARTMENT", "SECTION"])
    categories = _roll(scan, "categories", ["DEPARTMENT", "SECTION", "CATEGORY_NAME_2"])
    dept_by_store = {st: _roll(scan, "departments", ["DEPARTMENT"], st) for st in stores}

    # ---- BR-12 penetration: department Bills / total Bills, both stores ------
    total_bills = overall.r("bills").actual
    total_bills_p50 = overall.r("bills").p50
    for d in departments:
        b = d.r("bills")
        if b.actual is None:
            continue
        d.penetration = Reading(
            "penetration", "Share of baskets", "pct",
            b.actual / total_bills * 100 if total_bills else None,
            None,
            b.p50 / total_bills_p50 * 100 if total_bills_p50 else None,
            None, derived_band=True)

    no_trade = sorted({r["DEPARTMENT"] for r in scan["departments"]
                       if (r.get("rows_with_actual") or 0) == 0})
    silent = sorted((e for e in categories if e.silent_p50 > 0),
                    key=lambda e: e.silent_p50, reverse=True)

    # ---- BR-17: rank by the size of the gap in SAR, never the percentage ----
    def rank(xs, v):
        return sorted([x for x in xs if x.r("sales").verdict == v],
                      key=lambda x: abs(x.r("sales").gap), reverse=True)

    # how many of the 14 days each store, and the pair, landed outside the band
    def run_counts(series):
        out = {BELOW: 0, IN: 0, ABOVE: 0}
        for item in series:
            v = item["e"].r("sales").verdict
            if v:
                out[v] += 1
        return out

    return {
        "source": scan["source"],
        "anchor": anchor,
        "anchor_label": fmt_date(anchor),
        "anchor_dow": day_rows[0]["dow_name"],
        "week_of_month": day_rows[0]["week_of_month"],
        "window": scan["span"],
        "stores": stores,
        "reconciliation": recon,
        "overall": overall,
        "per_store": per_store,
        "trend": trend,
        "trend_counts": run_counts(trend),
        "store_trend": store_trend,
        "store_trend_counts": {st: run_counts(v) for st, v in store_trend.items()},
        "departments": departments,
        "sections": sections,
        "categories": categories,
        "dept_by_store": dept_by_store,
        "no_trade_departments": no_trade,
        "silent_categories": silent,
        "grain": scan["grain"],
        "below": {"departments": rank(departments, BELOW),
                  "sections": rank(sections, BELOW),
                  "categories": rank(categories, BELOW)},
        "above": {"departments": rank(departments, ABOVE),
                  "sections": rank(sections, ABOVE),
                  "categories": rank(categories, ABOVE)},
    }


if __name__ == "__main__":
    f = build()
    print(f"anchor {f['anchor_label']}  (week {f['week_of_month']} of the month)")
    print(f"window {f['window']['min']} .. {f['window']['max']}   stores {f['stores']}")
    print("\nreconciliation:")
    for name, ok, a, b in f["reconciliation"]["checks"]:
        print(f"  {'OK ' if ok else 'BAD'} {name:56} {a:14,.4f} vs {b:14,.4f}")
    for e in [f["overall"], *f["per_store"]]:
        print(f"\n{e.name}:")
        for r in e.readings.values():
            print(f"   {r.label:13} {r.actual:11,.2f}  band {r.p20:11,.2f} .. {r.p80:11,.2f}"
                  f"  P50 {r.p50:11,.2f}  {r.word:16} gap {r.gap:+11,.2f}"
                  f"  vs P50 {r.vs_p50_pct:+6.2f}%")
    print("\n14-day verdicts (both stores):", f["trend_counts"])
    for st, c in f["store_trend_counts"].items():
        print(f"   {st}: {c}")
    print(f"\ndepartments {len(f['departments'])}  sections {len(f['sections'])}"
          f"  categories {len(f['categories'])}   no trade: {f['no_trade_departments']}")
    for lvl in ("departments", "sections", "categories"):
        print(f"\n  below band {lvl} (ranked by SAR under P20):")
        for e in f["below"][lvl][:6]:
            r = e.r("sales")
            print(f"    {e.name[:34]:34} {r.actual:10,.2f}  P20 {r.p20:10,.2f}"
                  f"  {r.gap:+10,.2f}  rows={e.band_rows}")
        print(f"  above band {lvl}:")
        for e in f["above"][lvl][:4]:
            r = e.r("sales")
            print(f"    {e.name[:34]:34} {r.actual:10,.2f}  P80 {r.p80:10,.2f}  {r.gap:+10,.2f}")
