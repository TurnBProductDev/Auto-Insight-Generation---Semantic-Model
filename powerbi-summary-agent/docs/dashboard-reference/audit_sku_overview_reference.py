"""Audit the PRODUCED reference_sku_overview.html.

    python audit_sku_overview_reference.py

The replay proves the code; this proves the artifact. It re-derives every
arithmetic guarantee straight from sku_overview_scan.json - deliberately not
through the builder - then reads the written page as a document: is every
figure in the prose real and rounded, is the vocabulary right, is the file
self-contained, is it laid out the way the house style requires.

Exits non-zero on any failure.
"""
from __future__ import annotations

import html as _html
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "reference_sku_overview.html"
SCAN = HERE / "sku_overview_scan.json"

RATE = 0.27
SHOPS = ["ST1", "ST2", "ST3", "ST4", "ST5"]

FAILS = []
PASSES = []


def check(name, ok, detail=""):
    (PASSES if ok else FAILS).append((name, detail))


def num(v):
    return 0.0 if v is None else float(v)


def close(a, b, tol=0.51):
    return abs(float(a) - float(b)) <= tol


# --------------------------------------------------------------------------

def text_of(h):
    """The page's readable text, with tags, SVG and style removed."""
    t = re.sub(r"<style[^>]*>.*?</style>", " ", h, flags=re.S)
    t = re.sub(r"<script[^>]*>.*?</script>", " ", t, flags=re.S)
    t = re.sub(r"<svg[^>]*>.*?</svg>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    # Unescape BEFORE collapsing whitespace: &nbsp; only becomes a space
    # character once unescaped, so doing it the other way round leaves a
    # non-breaking space inside every money figure and "USD 1,234" never
    # matches anything.
    return re.sub(r"\s+", " ", _html.unescape(t))


def main():
    if not PAGE.exists():
        print("no page - run build_sku_overview_reference.py first")
        return 1
    h = PAGE.read_text(encoding="utf-8")
    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    txt = text_of(h)
    meta = scan["meta"]

    # ---------------------------------------------------------------- money
    check("no other currency appears anywhere",
          "SAR" not in h and "QAR" not in h)
    check("money is labelled USD", h.count("USD") > 100, h.count("USD"))
    # A bare local-currency total must never reach the page. The 3-month sales
    # total in local units is the one most likely to be published unconverted.
    local_total = num(scan["all"]["totals"]["sales_3m_local"])
    check("the unconverted sales total is not on the page",
          "{:,.0f}".format(local_total) not in txt,
          "{:,.0f}".format(local_total))
    converted = local_total * RATE
    check("the converted sales total IS on the page",
          "{:,.0f}".format(converted) in txt
          or "{:,.2f}M".format(converted / 1e6) in txt,
          "{:,.0f}".format(converted))

    check("the daily missed-sales figure reads as money on the page",
          "USD {:,.0f}".format(num(scan["all"]["totals"]["opp_day_local"]) * RATE) in txt,
          "USD {:,.0f}".format(num(scan["all"]["totals"]["opp_day_local"]) * RATE))

    # The rate is stated, so a reader can reproduce the conversion.
    check("the conversion rate is stated", "0.27" in txt)

    # ---------------------------------------------------------- arithmetic
    for scope, key in (("all", "all"), ("sega", "sega")):
        pop = scan[scope]
        tot = pop["totals"]
        for group in ("by_department", "by_store"):
            for col in ("rows", "stock_value_usd", "sales_3m_local"):
                parts = sum(num(r.get(col)) for r in pop[group])
                check("%s: %s adds to the total on %s" % (scope, group, col),
                      close(parts, num(tot.get(col)), max(0.5, abs(num(tot.get(col))) * 1e-9)),
                      "%.2f vs %.2f" % (parts, num(tot.get(col))))
        check("%s: only the five shops are counted" % scope,
              {r["LOC_CODE"] for r in pop["by_store"]} == set(SHOPS))
        check("%s: out-of-stock lines carry no stock value" % scope,
              close(num(pop["rule4_totals"]["stock_value_usd"]), 0.0))
        r7 = pop["rule7_totals"]
        check("%s: surplus is never larger than the stock holding it" % scope,
              num(r7["excess_value_usd"]) <= num(r7["stock_value_usd"]) + 0.02,
              "%.2f vs %.2f" % (num(r7["excess_value_usd"]), num(r7["stock_value_usd"])))

    # The headline figures the page leads on, re-derived here.
    so = scan["all"]["rule4_totals"]
    check("the empty-shelf line count is published",
          "{:,}".format(int(num(so["rows"]))) in txt, int(num(so["rows"])))
    check("the empty-shelf daily figure is converted, not raw",
          "{:,.0f}".format(num(so["opp_day_local"]) * RATE) in txt)

    # Opportunity loss is one day, on the local basis. If that stops being
    # true the page's wording is wrong, not just its number.
    opp = scan["currency_evidence"]["opp_loss_over_avg_daily_value"]
    check("opportunity loss is still exactly one day's sales",
          close(opp["min"], 1 / RATE, 1e-6) and close(opp["max"], 1 / RATE, 1e-6), opp)

    # ------------------------------------------------------ featured product
    f = scan["featured"]
    biggest = max(scan["all"]["rule4_rows"], key=lambda r: num(r.get("sales_3m_local")))
    check("the featured product is the largest stockout",
          biggest["SKU_CODE"] == f["sku"] and biggest["LOC_CODE"] == f["home_loc"],
          "%s @ %s" % (biggest["SKU_CODE"], biggest["LOC_CODE"]))
    shops = [r for r in f["by_location"] if r["loc"] in SHOPS]
    check("every shop that carries the featured product is on the page",
          all(r["loc"] in txt for r in shops),
          [r["loc"] for r in shops])
    home = next(r for r in shops if r["loc"] == f["home_loc"])
    check("the featured product's home shop is shown holding no stock",
          num(home["stock_qty"]) == 0.0, home["stock_qty"])
    # Its weekly run must be on the page as units, every value.
    run = sorted([w for w in f["weekly"] if w["loc"] == f["home_loc"]],
                 key=lambda w: w["week_start"])
    for w in run:
        check("weekly units for %s week of %s are published"
              % (w["loc"], w["week_start"][:10]),
              "{:,.0f}".format(num(w["qty"])) in txt, w["qty"])
    check("the featured product's decline is stated as a fall",
          "fall of" in txt)
    # A shop with no weekly rows must be named as absent, not silently omitted.
    absent = [r["loc"] for r in shops
              if not [w for w in f["weekly"] if w["loc"] == r["loc"]]]
    if absent:
        check("a shop missing from the weekly chart is named",
              all(("%s does not appear" % a) in txt for a in absent), absent)

    # ------------------------------------------------------------- rounding
    # A figure quoted at more than two decimals is a raw float that escaped.
    bad = re.findall(r"USD\s*[\d,]+\.\d{3,}", txt)
    check("no money figure carries more than 2 decimals", not bad, bad[:5])
    bad_pct = re.findall(r"\d+\.\d{3,}\s*%", txt)
    check("no percentage carries more than 2 decimals", not bad_pct, bad_pct[:5])

    # ------------------------------------------------------------ structure
    check("exactly one script tag", h.count("<script") == 1, h.count("<script"))
    body = re.search(r'<div class="app">(.*)</div>\s*<script', h, re.S)
    check("the app shell exists", bool(body))
    if body:
        inner = body.group(1).strip()
        check("nav.rail is the first child of .app",
              inner.startswith('<nav class="rail"'))
        check(".app holds only the rail and main",
              inner.count("<nav") == 1 and inner.count("<main") == 1,
              (inner.count("<nav"), inner.count("<main")))
    check("content lives in main > .page", '<main><div class="page">' in h)
    layers = re.findall(r'data-layer="(\w+)"', h)
    views = sorted(set(re.findall(r'data-view="(\w+)"', h)))
    check("two views", views == ["all", "top"], views)
    check("five layers in each view", len(layers) == 10, len(layers))
    for k in ("overview", "product", "selling", "action", "detail"):
        check("layer %s exists in both views" % k, layers.count(k) == 2)
        check("layer %s has a nav button" % k, 'data-nav="%s"' % k in h)
    check("the URL carries view and layer", "'#' + current.view + '/'" in h)
    check("print rules force hidden layers open",
          re.search(r"@media print\{[^}]*\.layer\[hidden\]", h, re.S) is not None
          or ".layer[hidden],.view[hidden]{display:block}" in h)

    # ------------------------------------------------------ self-containment
    external = re.findall(r'(?:src|href)\s*=\s*"(?!#)([^"]+)"', h)
    check("no external requests", not external, external[:3])
    check("no browser storage APIs",
          "localStorage" not in h and "sessionStorage" not in h)
    check("the ampersand in a real name is escaped", "Home &amp; Living" in h)
    markup = re.sub(r"<script[^>]*>.*?</script>", " ", h, flags=re.S)
    stray = re.findall(
        r"&(?!amp;|lt;|gt;|quot;|#39;|nbsp;|rsquo;|rsaquo;|mdash;|middot;)", markup)
    check("no unescaped ampersands in the markup", not stray, stray[:5])

    # ----------------------------------------------------------- vocabulary
    # Words a reader with no background will not know. The model's own terms
    # are shown deliberately in .act and .c spans, which are stripped first.
    shown = re.sub(r'<small class="act">.*?</small>', " ", h, flags=re.S)
    shown = re.sub(r'<p class="c">.*?</p>', " ", shown, flags=re.S)
    shown = re.sub(r'<div class="rb-l">[^<]*<small>.*?</small></div>',
                   " ", shown, flags=re.S)
    shown_txt = text_of(shown).replace("SKU Overview", "this report")
    shown_txt = re.sub(r"<small>[^<]*</small>", " ", shown_txt)
    for word in ("SKU", "materiality", "velocity", "burnout", "P90",
                 "opportunity loss", "eligible", "Loc-SKU", "breadth"):
        check("jargon absent: %s" % word,
              not re.search(r"\b%s\b" % re.escape(word), shown_txt, re.I), word)
    # ...and the model's own vocabulary must still be present somewhere, so
    # "simplify" can never quietly become "delete the model's terminology".
    for term in ("NON MOVING", "OVERSTOCK", "STOCK OUT - PLACE ORDER",
                 "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE", "SEG_A"):
        check("the model's own term is still shown: %s" % term, term in txt, term)

    # -------------------------------------------------------------- honesty
    # Every view must carry these in its own right. Checking the page as a
    # whole passes when one view has silently lost them, which is exactly the
    # failure two mutations exposed.
    views_html = {}
    for name in ("all", "top"):
        seg = h.split('<div class="view" data-view="%s"' % name)
        if len(seg) > 1:
            rest = seg[1]
            for other in ("all", "top"):
                rest = rest.split('<div class="view" data-view="%s"' % other)[0]
            views_html[name] = text_of(rest)
    check("both views were located for inspection",
          set(views_html) == {"all", "top"}, sorted(views_html))

    for vname, vtxt in sorted(views_html.items()):
        check("%s view: the unavailable insight is stated, not omitted" % vname,
              "Not available yet" in vtxt and "keeps no record" in vtxt)
        check("%s view: the daily figure is called a rate, not a total" % vname,
              "daily rate, not a running total" in vtxt)
        check("%s view: the clash with Inventory Management is disclosed" % vname,
              "Inventory Management report" in vtxt)
        check("%s view: a blank estimate is not treated as a zero" % vname,
              "blank is not a zero" in vtxt)
        check("%s view: the four-week series is not called a trend" % vname,
              "not as a long-term trend" in vtxt)
        check("%s view: warehouses are excluded from selling totals" % vname,
              "do not sell" in vtxt)
    check("the markdown section refuses a causal claim",
          "does not show that" in txt or "cannot tell you whether" in txt)
    check("one caveats block only", h.count('class="caveats"') == 2,
          h.count('class="caveats"'))
    check("the scoped view states its scope",
          h.count('class="scoped"') == 5, h.count('class="scoped"'))
    # An empty result must read as a result, not as a missing table.
    sega6 = int(num(scan["sega"]["rule6_totals"]["rows"]))
    if sega6 == 0:
        check("an empty finding says so rather than showing nothing",
              'class="none"' in h)

    # Colour is never the only carrier of meaning.
    for word in ("Act now", "Free fix", "Watch", "Healthy"):
        check("severity word present: %s" % word, word in txt, word)

    # ------------------------------------------------------------- the date
    as_at = str(meta["as_at"])[:10]
    d, mth, y = int(as_at[8:10]), int(as_at[5:7]), int(as_at[:4])
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    long_date = "%d %s %d" % (d, months[mth - 1], y)
    check("the as-at date is on the page", long_date in txt, long_date)
    check("the page says it is a reference design", "Reference design" in txt)

    # ------------------------------------------------------------- report
    print("SKU Overview reference - audit")
    print("  %d checks passed" % len(PASSES))
    if FAILS:
        print("  %d FAILED:" % len(FAILS))
        for name, detail in FAILS:
            print("    x %s  %s" % (name, detail))
        return 1
    print("  no failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
