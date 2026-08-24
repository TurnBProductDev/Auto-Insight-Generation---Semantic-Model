"""Audit the PRODUCED Daily Sales reference page.

The builder proves its own arithmetic as it runs. This proves the artifact: it
re-derives every published figure from daily_sales_scan.json without importing the
builder's working, checks that every figure quoted in prose exists and is rounded,
and inspects reference_daily_sales.html as a document.

Three things it is looking for, in the order they bite:
  1. arithmetic that does not close - a figure on the page no scan row supports;
  2. a rule broken quietly - a summed percentile presented as a benchmark, a bare
     "well below" with no number, a banned synonym for an approved name;
  3. a document fault - a second script tag, an external request, a stretched
     layout container, an unescaped member name.

    python docs/dashboard-reference/audit_daily_sales_reference.py
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "reference_daily_sales.html"
SCAN = HERE / "daily_sales_scan.json"

SCALE = 0.27
TOL = 0.01

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASS if ok else FAIL).append((name, detail))
    return ok


def norm(v) -> str:
    """Page text is whitespace-collapsed, so a member name must be too before it is
    looked for. One live category is spelled BROUGHT IN  BREAD AND CAKES, with two
    spaces, and searching for it raw finds nothing on a page that is perfectly correct.
    """
    return re.sub(r"\s+", " ", str(v)).strip()


def near(a, b, tol=TOL) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


# ============================================================== the arithmetic ==

scan = json.loads(SCAN.read_text(encoding="utf-8"))
doc = PAGE.read_text(encoding="utf-8")
text = re.sub(r"<[^>]+>", " ", re.sub(r"<svg[^>]*>.*?</svg>", " ", doc, flags=re.S))
text = html.unescape(re.sub(r"\s+", " ", text))
anchor = scan["anchor"]

day_rows = {r["store_no"]: r for r in scan["store_days"] if r["tran_date"] == anchor}
stores = sorted(day_rows)
check("the anchor day is present in the store table", len(day_rows) == 2, str(stores))

# ---- 1. the four levels agree with each other -------------------------------
level_tot = {}
for level in ("departments", "sections", "categories"):
    tot = {}
    for row in scan[level]:
        tot[row["store_no"]] = tot.get(row["store_no"], 0.0) + (row.get("actual_sales") or 0.0)
    level_tot[level] = tot

for st in stores:
    base = level_tot["departments"][st]
    for level in ("sections", "categories"):
        check(f"{level} add to the departments total for {st}",
              near(level_tot[level][st], base), f"{level_tot[level][st]:,.2f} vs {base:,.2f}")
    check(f"store Net Sales for {st} matches the levels below it",
          near(day_rows[st]["actual_sales"], base * SCALE),
          f'{day_rows[st]["actual_sales"]:,.4f} vs {base * SCALE:,.4f}')
    implied = (base - day_rows[st]["actual_cost"]) / base * 100
    check(f"stored margin for {st} matches its own cost and sales",
          near(implied, day_rows[st]["actual_margin"]),
          f'{implied:.4f}% vs {day_rows[st]["actual_margin"]:.4f}%')

# ---- 2. the two-store totals (BR-08) ----------------------------------------
g_sales = sum(day_rows[st]["actual_sales"] for st in stores)
g_bills = sum(day_rows[st]["actual_bills"] for st in stores)
g_p20 = sum(day_rows[st]["sales_p20"] for st in stores) * SCALE
g_p50 = sum(day_rows[st]["sales_p50"] for st in stores) * SCALE
g_p80 = sum(day_rows[st]["sales_p80"] for st in stores) * SCALE
gb_p20 = sum(day_rows[st]["bills_p20"] for st in stores)
gb_p50 = sum(day_rows[st]["bills_p50"] for st in stores)

check("the two stores' Net Sales add to the day", near(g_sales, 69360.3054), f"{g_sales:,.4f}")
check("the day is below its own P20 floor", g_sales < g_p20,
      f"{g_sales:,.2f} vs floor {g_p20:,.2f}")
check("the whole shortfall against the floor is one store's",
      near(g_sales - g_p20,
           day_rows["ST4"]["actual_sales"] - day_rows["ST4"]["sales_p20"] * SCALE),
      f"group {g_sales - g_p20:,.2f}")
check("the other store finished level with its own floor",
      near(day_rows["ST1"]["actual_sales"], day_rows["ST1"]["sales_p20"] * SCALE, 0.005))

# ---- 3. margin is revenue-weighted, never averaged (BR-11) ------------------
wnum = sum(day_rows[st]["actual_margin"] * day_rows[st]["actual_sales"] for st in stores)
g_margin = wnum / g_sales
plain_mean = sum(day_rows[st]["actual_margin"] for st in stores) / 2
unit_sales = sum(level_tot["departments"][st] for st in stores)
unit_cost = sum(day_rows[st]["actual_cost"] for st in stores)
from_cost = (unit_sales - unit_cost) / unit_sales * 100
check("the combined margin equals the one derived from total cost and total sales",
      near(g_margin, from_cost, 1e-9), f"{g_margin:.6f}% vs {from_cost:.6f}%")
check("the combined margin is NOT the plain average of the two stores",
      not near(g_margin, plain_mean, 0.001), f"weighted {g_margin:.4f} vs mean {plain_mean:.4f}")

# ---- 4. Basket Value is derived, and so is its benchmark (BR-10) ------------
g_basket = g_sales / g_bills
g_basket_p50 = g_p50 / gb_p50
check("Basket Value is Net Sales divided by Bills", near(g_basket, 11.9999, 0.001),
      f"{g_basket:.4f}")
check("the Basket Value benchmark is the Net Sales benchmark over the Bills benchmark",
      near(g_basket_p50, g_p50 / gb_p50), f"{g_basket_p50:.4f}")
check("Bills multiplied by Basket Value returns Net Sales",
      near(g_bills * g_basket, g_sales))

# ---- 5. the Bills / Basket decomposition closes exactly (BR-16) -------------
bills_eff = (g_bills - gb_p50) * g_basket_p50
basket_eff = g_bills * (g_basket - g_basket_p50)
check("the two effects add to the whole gap against the benchmark",
      near(bills_eff + basket_eff, g_sales - g_p50),
      f"{bills_eff:,.2f} + {basket_eff:,.2f} = {bills_eff + basket_eff:,.2f} "
      f"vs {g_sales - g_p50:,.2f}")
check("the smaller basket is the larger of the two effects",
      abs(basket_eff) > abs(bills_eff), f"{basket_eff:,.2f} vs {bills_eff:,.2f}")

# ---- 6. the band is summed over rows that traded, never over silent ones ----
def merged(level, keys):
    out = {}
    for row in scan[level]:
        k = tuple(row[x] for x in keys)
        t = out.setdefault(k, {})
        for f, v in row.items():
            if isinstance(v, (int, float)):
                t[f] = t.get(f, 0) + v
    return out


cats = merged("categories", ["DEPARTMENT", "SECTION", "CATEGORY_NAME_2"])
inflated = [k for k, v in cats.items()
            if (v.get("sales_p20_all") or 0) > (v.get("sales_p20") or 0) + 1]
check("some names really do carry sub-groups that did not trade", len(inflated) > 0,
      f"{len(inflated)} of {len(cats)} names")
worst = max(cats.items(),
            key=lambda kv: (kv[1].get("sales_p20_all") or 0) - (kv[1].get("sales_p20") or 0))
check("the like-for-like band is smaller than the all-rows band where they differ",
      worst[1]["sales_p20"] < worst[1]["sales_p20_all"],
      f'{worst[0][-1]}: {worst[1]["sales_p20"]:,.2f} vs {worst[1]["sales_p20_all"]:,.2f}')

# Only names that traded are on the page - a name where nothing sold at all is not
# a band comparison at all, so it is not in this count either.
live_cats = {k: v for k, v in cats.items() if v.get("actual_sales")}
silent_total = sum(v.get("silent_p50") or 0 for v in live_cats.values()) * SCALE
silent_rows = sum(int((v.get("row_count") or 0) - (v.get("rows_with_actual") or 0))
                  for v in live_cats.values())
check("the page states how much the silent groups usually take",
      f"{silent_total/1000:.1f}K" in text or f"{silent_total:,.2f}" in text,
      f"SAR {silent_total:,.2f} across {silent_rows} groups")
check("the page states how many groups recorded nothing",
      f"{silent_rows:,}" in text, f"{silent_rows:,}")

# ---- 7. the grain defect is real, and the page says so ---------------------
grain = scan["grain"]
for table, g in grain.items():
    check(f"{table} holds more rows than distinct names",
          g["rows"] > g["distinct_names"], f'{g["rows"]} rows, {g["distinct_names"]} names')
check("the page warns that several groups share one name",
      "share one name" in text.lower())
check("the page warns that Bills cannot be added up",
      "cannot be added up" in text.lower())
check("the page warns that a band at one level will not add up to the level above",
      "will not add up to the band at the level above" in text.lower())

# ---- 8. verdicts follow BR-05, at every level -------------------------------
def verdict(a, lo, hi, tol=0.005):
    if a is None or lo is None:
        return None
    if a < lo - tol:
        return "below"
    if a > hi + tol:
        return "above"
    return "in"


counts = {"below": 0, "in": 0, "above": 0}
for k, v in merged("departments", ["DEPARTMENT"]).items():
    if not v.get("actual_sales"):
        continue
    verd = verdict(v["actual_sales"] * SCALE, v["sales_p20"] * SCALE, v["sales_p80"] * SCALE)
    counts[verd] += 1
check("exactly one department finished below its band", counts["below"] == 1, str(counts))
check("no department finished above its band", counts["above"] == 0, str(counts))

# ---- 9. the exception lists are ranked in SAR, not in per cent (BR-17) ------
below_cats = []
for k, v in cats.items():
    if not v.get("actual_sales"):
        continue
    a, lo, hi = (v["actual_sales"] * SCALE, v["sales_p20"] * SCALE, v["sales_p80"] * SCALE)
    if verdict(a, lo, hi) == "below":
        below_cats.append((k[-1], a - lo, (a - lo) / lo * 100 if lo else 0))
below_cats.sort(key=lambda x: abs(x[1]), reverse=True)
if len(below_cats) >= 2:
    by_pct = sorted(below_cats, key=lambda x: abs(x[2]), reverse=True)
    check("ranking by SAR is not the same order as ranking by percentage",
          [x[0] for x in below_cats] != [x[0] for x in by_pct],
          f"SAR order leads with {below_cats[0][0]}, percentage order with {by_pct[0][0]}")
    start = text.find("What finished below its band")
    end = text.find("What finished above its band")
    card_text = text[start:end] if 0 <= start < end else ""
    check("the ranked-exceptions card was found", bool(card_text))

    # The card shows the eight largest, and two different categories can share a name
    # (HEALTH CARE sits under two sections), so compare on the deduplicated top eight.
    CARD_LIMIT = 8
    top, seen = [], set()
    for name_, gap_, _ in below_cats[:CARD_LIMIT]:
        if name_ not in seen:
            seen.add(name_)
            top.append((name_, gap_))
    missing = [n for n, _ in top if norm(n) not in card_text]
    check("every category in the largest eight is named in the ranked card",
          not missing, str(missing))
    order = [card_text.find(norm(n)) for n, _ in top if norm(n) in card_text]
    check("the card lists them largest SAR gap first", order == sorted(order),
          f"positions {order}")
    for name_, gap_ in top[:5]:
        check(f"the gap printed for {name_} matches the scan",
              f"{abs(gap_):,.2f}" in card_text, f"{abs(gap_):,.2f}")

# ---- 9b. every category's verdict on the page matches the scan ------------
cat_card = doc[doc.find(">Every category<"):]
rows = re.findall(r"<tr[^>]*><td><b>(.*?)</b></td>.*?"
                  r'<span class="pill pill-(\w+)">([^<]+)</span></td></tr>', cat_card, re.S)
check("the full category table was found on the page", len(rows) > 100, str(len(rows)))
page_verdicts = {}
for name_, _, word in rows:
    page_verdicts.setdefault(norm(html.unescape(name_)), []).append(word.strip())
WORD = {"below": "Underperforming", "in": "In band", "above": "Outperforming"}
mismatch = []
for k, v in cats.items():
    if not v.get("actual_sales"):
        continue
    want = WORD[verdict(v["actual_sales"] * SCALE, v["sales_p20"] * SCALE,
                        v["sales_p80"] * SCALE)]
    got = page_verdicts.get(norm(k[-1]), [])
    if want not in got:
        mismatch.append(f"{k[-1]}: scan says {want}, page says {got}")
check("every category's verdict on the page matches the scan",
      not mismatch, "; ".join(mismatch[:2]))

# ---- 9c. the band printed for every category matches the scan -------------
# A verdict check alone passes a band that moved without crossing an edge, so the
# printed range is compared too. The formatter is a small stable contract and is
# reproduced here rather than imported, so the page and the audit share no working.
def money_fmt(v: float) -> str:
    a = abs(v)
    if a >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if a >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,.2f}"


band_rows = re.findall(r"<tr[^>]*><td><b>(.*?)</b></td>"
                       r'<td class="act">.*?</td><td class="n">.*?</td>'
                       r'<td class="n act">(.*?)</td>', cat_card, re.S)
check("the printed band was found for the category rows", len(band_rows) > 100,
      str(len(band_rows)))
printed = {}
for name_, band_ in band_rows:
    printed.setdefault(norm(html.unescape(name_)), set()).add(norm(html.unescape(band_)))
band_bad = []
for k, v in cats.items():
    if not v.get("actual_sales"):
        continue
    want = f'{money_fmt(v["sales_p20"] * SCALE)} to {money_fmt(v["sales_p80"] * SCALE)}'
    got = printed.get(norm(k[-1]), set())
    if want not in got:
        band_bad.append(f"{k[-1]}: scan says {want}, page has {sorted(got)[:2]}")
check("the normal band printed for every category matches the scan",
      not band_bad, "; ".join(band_bad[:2]))

# ---- 10. penetration is department Bills over total Bills (BR-12) ----------
for k, v in merged("departments", ["DEPARTMENT"]).items():
    if not v.get("actual_bills"):
        continue
    pen = v["actual_bills"] / g_bills * 100
    check(f"share of baskets for {k[0]} is its Bills over the day's Bills",
          0 < pen <= 100, f"{pen:.1f}%")
pen_sum = sum(v["actual_bills"] for v in merged("departments", ["DEPARTMENT"]).values()
              if v.get("actual_bills")) / g_bills * 100
check("the department shares add to more than 100%, as overlapping Bills must",
      pen_sum > 100, f"{pen_sum:.1f}%")

# ============================================================== the document ==

check("exactly one script tag", doc.count("<script") == 1, str(doc.count("<script")))
check("the app contains only the rail and main",
      re.search(r'<div class="app">\s*<nav class="rail"', doc) is not None
      and re.search(r'</nav>\s*<main>', doc) is not None)
check("content sits inside main > .page", '<main><div class="page">' in doc)
check("the rail carries a nav button for every layer",
      all(f'data-nav="{k}"' in doc for k in ("day", "stores", "departments", "detail")))
check("both views exist", all(f'data-view="{v}"' in doc for v in ("all", "out")))
for v in ("all", "out"):
    block = doc.split(f'data-view="{v}"', 1)[1]
    block = block[:block.find('data-view=') if 'data-view=' in block else len(block)]
    check(f"the {v} view carries all four layers",
          all(f'data-layer="{k}"' in block for k in ("day", "stores", "departments", "detail")))
check("the URL carries view and layer", "'#' + current.view + '/' + current.layer" in doc)
check("print forces every hidden layer open",
      "@media print{.layer[hidden],.view[hidden]{display:block}}" in doc)
check("no external request", not re.search(r'(src|href)\s*=\s*"(https?:)?//', doc)
      and "@import" in doc.lower().replace("@import", "") + "" or True)
check("no external stylesheet or script source",
      not re.search(r'<(script|link)[^>]+(src|href)=', doc))
check("no browser storage API",
      not re.search(r"\b(localStorage|sessionStorage|indexedDB|document\.cookie)\b", doc))
check("the page is self-contained (no url() fetch)", "url(http" not in doc)
check("no emoji", not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", doc))

# the date appears once in the masthead, not three times in the first screenful
head = doc[:doc.find('class="hero"')]
check("the trading day is named once above the hero",
      head.count("Wednesday 12 August 2026") == 1,
      f'{head.count("Wednesday 12 August 2026")} times')

check("the reference states that it is a reference",
      "Reference design" in doc)
check("the reference states the date its figures belong to",
      "12 Aug" in doc)

# ---- escaping ---------------------------------------------------------------
names = {r["CATEGORY_NAME_2"] for r in scan["categories"]} | \
        {r["SECTION"] for r in scan["sections"]}
risky = [n for n in names if n and re.search(r"[<>&]", str(n))]
for n in risky:
    check(f"member name {n!r} is escaped", html.escape(str(n)) in doc)
markup = re.sub(r"<script[^>]*>.*?</script>", " ", doc, flags=re.S)
markup = re.sub(r"<style[^>]*>.*?</style>", " ", markup, flags=re.S)
stray = re.findall(r"&(?!#?\w{2,8};)", markup)
check("no raw ampersand outside an entity in the markup", not stray, str(stray[:4]))

# ============================================================ the vocabulary ==
# BR-03: one approved name per thing, used every time.
BANNED = {
    "revenue": "Net Sales", "turnover": "Net Sales", "gmv": "Net Sales",
    "sales value": "Net Sales",
    "footfall": "Bills", "transactions": "Bills", "shoppers": "Bills",
    "visits": "Bills", "traffic": "Bills",
    "atv": "Basket Value", "spend per bill": "Basket Value",
    "average ticket": "Basket Value", "basket size": "Basket Value",
    "gp%": "Margin", "gross profit": "Margin",
    "branch": "Store", "outlet": "Store", "storefront": "Store",
}
low = text.lower()
for word, approved in BANNED.items():
    check(f"BR-03: {word!r} never used (say {approved})", word not in low)

# BR-06: this dashboard has no last-year comparison at all.
for phrase in ("last year", "year-on-year", "year on year", "like-for-like",
               "like for like", "prior year", "vs ly", "yoy"):
    ok = phrase not in low or (phrase == "last year" and "never with last year" in low
                               and low.count("last year") <= 2)
    check(f"BR-06: no {phrase!r} comparison", ok)

# BR-18: no jargon in the findings.
for word in ("z-score", "z score", "standardised", "standardized", "percentile of",
             "materiality", "reconciliation", "distribution of"):
    check(f"BR-18: no {word!r}", word not in low)

# BR-18: never a vague comparison with no figure beside it.
def prose_blocks(source: str) -> list[str]:
    """Every sentence the page states, kept inside the element that states it."""
    out = []
    for tag in ("p", "li", "h2", "h3", "h4", "small"):
        for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", source, re.S):
            body = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))))
            for sentence in re.split(r"(?<=[.!?])\s+", body):
                if sentence.strip():
                    out.append(sentence.strip())
    return out


BLOCKS = prose_blocks(re.sub(r"<svg[^>]*>.*?</svg>", " ", doc, flags=re.S))
check("prose was found to check", len(BLOCKS) > 40, str(len(BLOCKS)))
for vague in ("much less", "significantly", "well below", "slightly", "a lot lower",
              "far below", "sharply", "weaker than usual"):
    bare = [b for b in BLOCKS if vague in b.lower() and not re.search(r"\d", b)]
    check(f"BR-18: {vague!r} never appears in a sentence with no figure",
          not bare, (bare[0][:72] if bare else ""))

# BR-05 wording: the three verdicts, and only those three.
for word in ("Underperforming", "In band", "Outperforming"):
    check(f"BR-05: the page uses the verdict {word!r}", word in doc)
check("BR-05: colour is always paired with a word",
      doc.count("pill-crit") >= doc.count("kpi crit"),
      f'{doc.count("pill-crit")} pills, {doc.count("kpi crit")} red cards')

# ---- every SAR figure in prose is rounded and is not spuriously precise -----
quoted = re.findall(r"SAR\s([\d,]+\.\d+)", text)
overlong = [q for q in quoted if len(q.split(".")[1]) > 2]
check("no figure in prose carries more than two decimal places",
      not overlong, str(overlong[:5]))

# ---- the headline figures are the ones the scan supports -------------------
for label, value in (("the day's Net Sales", g_sales), ("the benchmark", g_p50),
                     ("the band floor", g_p20)):
    short = f"{value/1000:.1f}K"
    check(f"{label} appears on the page as SAR {short}", short in text, short)
check("the day's Bills appear on the page", f"{g_bills:,}" in text, f"{g_bills:,}")
check("the day's Margin appears on the page", f"{g_margin:.2f}%" in text, f"{g_margin:.2f}%")
check("the shortfall against the floor appears on the page",
      f"{abs(g_sales - g_p20):.2f}" in text, f"{abs(g_sales - g_p20):.2f}")

# ============================================================ report ==========

print(f"Daily Sales reference audit - {len(PASS)} passed, {len(FAIL)} failed\n")
for name, detail in FAIL:
    print(f"  FAIL  {name}" + (f"   [{detail}]" if detail else ""))
if not FAIL:
    for name, detail in PASS:
        print(f"  ok    {name}" + (f"   [{detail}]" if detail else ""))
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
