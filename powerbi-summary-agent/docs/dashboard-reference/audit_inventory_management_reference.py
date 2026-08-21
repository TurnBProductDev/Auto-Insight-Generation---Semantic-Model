"""Audit the PRODUCED reference page, not the code that wrote it.

Re-derives every arithmetic guarantee from the model figures, then checks every
number that appears in the page's prose actually exists in that derived set, and
inspects the file as a document.
"""
import html
import re
import sys

import os

import inventory_management_facts as F
from build_inventory_management_reference import full, money, pct, pts

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "reference_inventory_management.html")

fails = []
checks = 0


def ok(cond, msg):
    global checks
    checks += 1
    if not cond:
        fails.append(msg)


doc = open(PATH, encoding="utf8").read()

# ---------------------------------------------------------------- arithmetic
ok(abs(sum(r[2] for r in F.RISKS) - F.LOST) < 1e-9,
   "the six risks must sum to the points lost")
ok(abs(100 - F.LOST - F.SCORE) < 1e-9, "100 less the points lost must equal the score")
for key, name, p in F.RISKS:
    calc = min(25.0, 25.0 * sum(v * w for _n, v, w in F.RD[key]["dims"]))
    ok(abs(calc - p) < 1e-6, "%s must equal 25 x its weighted dimensions" % name)
    ok(p <= 25.0 + 1e-9, "%s must not exceed the 25-point cap" % name)
    ok(sum(w for _n, _v, w in F.RD[key]["dims"]) == 1.0,
       "%s dimension weights must sum to 1" % name)
ok(sum(x["n"] for x in F.QUEUE) == F.SKUS, "the queue must account for every line")
ok(F.NEEDS_N + F.GAP_N + F.OK_N == F.SKUS, "the three queue kinds must partition every line")
ok(sum(x["n"] for x in F.HEALTH) == F.SKUS, "health bands must account for every line")
ok(abs(sum(F.num(r, "Stock") for r in F.STORES) - F.STOCK) < 0.01,
   "store stock must reconcile to the total")
ok(abs(sum(F.num(r, "Stock") for r in F.DEPTS) - F.STOCK) < 0.01,
   "department stock must reconcile to the total")
ok(abs(sum(F.num(r, "Stock") for r in F.SECTS) - F.STOCK) < 0.01,
   "section stock must reconcile to the total")
ok(abs(F.AGE_TOTAL - sum(v for _k, v in F.AGE)) < 0.01, "age bands must sum to their total")
ok(F.AGE_OVER12 <= F.AGE_OVER3, "over-twelve-months must be a subset of over-three-months")
ok(F.RD["Excess"]["val"] < F.STOCK,
   "the surplus must be smaller than the stock value it sits inside")
ok(F.OPP_SCOPED < F.num(F.D["opp_loss_unscoped"], "unscoped"),
   "the published sales-at-risk figure must be the scoped, smaller one")

# no warehouse may appear in any scored table
for r in F.STORES:
    ok(not str(F.g(r, "LOC_CODE")).startswith("WH"),
       "no warehouse may appear among the scored stores")
ok(len(F.WH) == 2 and all(x["loc"].startswith("WH") for x in F.WH),
   "the warehouse block must hold only warehouses")

# ---------------------------------------------------------------- document
ok(doc.count("<script") == 1, "exactly one script tag")
ok(doc.count("<style") == 1, "exactly one style tag")
ok(not re.findall(r'(?:src|href)="(?!#)[^"]+"', doc), "no external references")
ok(doc.count("<svg") == doc.count("</svg>"), "every svg must be closed")
ok(not re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", doc), "no emojis")
ok(re.search(r'<div class="app"><nav class="rail"', doc),
   "the rail must be the first child of .app")
ok(len(re.findall(r'data-view="\w+"', doc)) == 2, "two views")
LAYERS = ("summary", "focus", "locations", "divisions", "queue")
ok(len(re.findall(r'data-layer="\w+"', doc)) == 2 * len(LAYERS),
   "six layers in each of the two views")
for layer in LAYERS:
    ok(len(re.findall(r'data-layer="%s"' % layer, doc)) == 2,
       "layer %s must exist in both views, so no nav button lands on a blank page" % layer)
ok(re.search(r"var LAYERS = \[", doc),
   "the page script must declare its layer list")
for layer in LAYERS:
    ok("'%s'" % layer in re.search(r"var LAYERS = \[[^\]]*\]", doc).group(0),
       "layer %s must be in the page script's layer list" % layer)

# a format placeholder that never got substituted would print as literal braces
_prose_only = re.sub(r"<style[^>]*>.*?</style>", " ", doc, flags=re.S)
_prose_only = re.sub(r"<script[^>]*>.*?</script>", " ", _prose_only, flags=re.S)
ok(not re.findall(r"\{[a-z_0-9]+\}", _prose_only),
   "no unsubstituted placeholder may reach the page: %s"
   % re.findall(r"\{[a-z_0-9]+\}", _prose_only)[:5])

# the model's own vocabulary must still be visible, exactly where it is meant
# to be: under each risk name, and under each row of the queue table.
ok(doc.count('class="d-model"') == 6,
   "each of the six risks must name what the model calls it")
for model_name in ("Excess Stock", "Ageing Stock", "Dead Stock", "Out of Stock",
                   "Verge of Stockout", "Damage"):
    ok(model_name in doc,
       "the model's own name for %r must appear on the page" % model_name)
for model_code in ("STOCK OUT - PLACE ORDER", "NON MOVING", "OVERSTOCK",
                   "NEW LISTED SKU", "NOT ACTIVE"):
    ok(model_code in doc,
       "the queue must show the model's own code %r" % model_code)
ok("Reference design" in doc, "the page must state that it is a reference design")
ok("19 August 2026" in doc, "the page must carry the date its figures belong to")

# the scoped view must not claim a score of its own
needs_view = doc.split('data-view="needs"')[1]
ok("no score" in needs_view, "the scoped view must say it carries no score")
ok(needs_view.count("does not have its own breakdown") >= 3,
   "each breakdown layer in the scoped view must point at the view that owns it")

# honesty about the history
ok("shape only" in doc, "the illustrative line must be marked as shape only")
ok("no past values" in doc, "the page must state that no past values are implied")

# banned vocabulary, and the claim that August rose
text = html.unescape(re.sub(r"<[^>]+>", " ", doc))
for banned in ("risen every month", "dead stock write-off is",
               "because of", "caused by", "due to a promotion"):
    ok(banned not in text.lower(), "banned phrasing: %r" % banned)

# ------------------------------------------------------- plain language
# The model's own vocabulary is deliberately shown in two places and nowhere
# else: the small "called X in the model" line on each risk card, and the grey
# code under each row of the queue table. Strip those, then the rest of the
# page has to read as everyday English.
_plain = re.sub(r"<style[^>]*>.*?</style>", " ", doc, flags=re.S)
_plain = re.sub(r"<script[^>]*>.*?</script>", " ", _plain, flags=re.S)
_plain = re.sub(r"<svg[^>]*>.*?</svg>", " ", _plain, flags=re.S)
_plain = re.sub(r'<p class="d-model">.*?</p>', " ", _plain, flags=re.S)
_plain = re.sub(r'<span class="act">[A-Z0-9 \-]+</span>', " ", _plain)
_plain = html.unescape(re.sub(r"<[^>]+>", " ", _plain)).lower()
for word in ("sku", "materiality", "reconcil", "eligible", "p90", "percentile",
             "breadth", "normalis", "aggregat", "granular", "velocity",
             "burnout", "opportunity loss", "utilisation", "cover discipline",
             "scoped", "estate", "composite", "dimension", "drag on the score"):
    ok(word not in _plain,
       "jargon a general reader would not know: %r" % word)

# ---------------------------------------------------------------- grounding
allowed = set()


def allow(v):
    allowed.add(full(v))
    allowed.add(money(v))
    allowed.add(pts(v))
    for dp in (0, 1, 2):
        allowed.add(pct(v, dp))
    allowed.add("{:.0f}".format(v))
    allowed.add("{:.1f}".format(v))


for v in (F.SCORE, F.LOST, F.STOCK, F.SKUS, F.ELIGIBLE, F.AVG_SKU, F.WH_VAL,
          F.NEEDS_N, F.NEEDS_VAL, F.GAP_N, F.GAP_VAL, F.OK_N, F.REST_N,
          F.AGE_TOTAL, F.AGE_OVER3, F.AGE_OVER12, F.NM_180_N, F.NM_180_VAL,
          F.NM_SHORT_N, F.PRIME_OOS, F.OPP_SCOPED, 100, 25, 180, 90, 12, 5583,
          214739.1729, 7896, 353377.4175):
    allow(v)
for _k, _n, p in F.RISKS:
    allow(p)
    allow(F.share(p))
for d in F.RD.values():
    allow(d["skus"])
    allow(d["val"])
    for _n, v, w in d["dims"]:
        allow(v * 100)
        allow(w * 100)
        allowed.add("{:.0f}".format(w * 100))
for x in F.QUEUE:
    for v in (x["n"], x["val"], x["po"], x["exc"], x["opp"]):
        allow(v)
for x in F.HEALTH:
    allow(x["n"]); allow(x["val"]); allow(x["avg"])
for coll in (F.STORES, F.DEPTS, F.SECTS):
    for r in coll:
        for k in ("Score", "Stock", "SKUs", "Excess", "Ageing", "Dead",
                  "OOS", "Verge", "Damage"):
            try:
                allow(F.num(r, k))
            except KeyError:
                pass
for x in F.WH:
    for v in (x["n"], x["val"], x["exc"], x["nm"], x["nmval"]):
        allow(v)
for _k, v in F.AGE:
    allow(v)
for _k, n, v in F.NM:
    allow(n); allow(v)
for _d, v, n in F.DAMAGE:
    allow(v); allow(n)
for series in F.STORE_TREND.values():
    for v in series:
        allow(v)
for v in F.TREND_STORE_TOTAL:
    allow(v)
for v in F.EXC_DAYS.values():
    allow(v)
for v in F.EXC_BY_STORE.values():
    allow(v)
# derived figures the prose legitimately states
allow(sum(r[2] for r in F.RISKS[:4]))
allow(sum(r[2] for r in F.RISKS[:4]) / F.LOST * 100)
allow(F.RISKS[0][2] + F.RISKS[1][2] + F.RISKS[2][2])
allow((F.RISKS[0][2] + F.RISKS[1][2] + F.RISKS[2][2]) / F.LOST * 100)
allow(sum(x["n"] for x in F.NEEDS[:6]))
allow(sum(x["exc"] for x in F.WH))
allow(F.NEEDS_N / F.SKUS * 100)
allow(F.AGE_OVER3 / F.AGE_TOTAL * 100)
allow(F.RD["Excess"]["val"] / F.STOCK * 100)
allow(min(v for k, v in F.EXC_DAYS.items() if k != "ST5"))
_st5 = F.STORE_TREND["ST5"]
allow((_st5[0] - _st5[-1]) / _st5[0] * 100)
# figures the plain-language page derives and states
allow(max(F.num(r, "Score") for r in F.STORES))
allow(min(F.num(r, "Score") for r in F.STORES))
allow(F.num(F.DEPTS[-1], "Score") - F.num(F.DEPTS[0], "Score"))
allow(len(F.STORES))
allow(len(F.QUEUE))
allow(len(F.NEEDS))
allow(len(F.SECTS))
allow(len(F.DEPTS))
# score bands from the methodology, and axis/scale labels
for lit in ("90", "100", "80", "89", "70", "79", "60", "69", "50", "40", "30", "20",
            "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "13", "14",
            "16", "19", "24", "25", "12", "15", "35", "45", "55", "65", "75", "85", "95"):
    allowed.add(lit)
for v in F.TREND_STORE_TOTAL + [max(F.TREND_STORE_TOTAL) * 1.06 * f
                                for f in (0, .25, .5, .75, 1)]:
    allowed.add(money(v))

# only prose is grounded; svg geometry is code-owned
prose = doc
prose = re.sub(r"<svg[^>]*>.*?</svg>", " ", prose, flags=re.S)
prose = re.sub(r"<style[^>]*>.*?</style>", " ", prose, flags=re.S)
prose = re.sub(r"<script[^>]*>.*?</script>", " ", prose, flags=re.S)
prose = re.sub(r"style=\"[^\"]*\"", " ", prose)
prose = html.unescape(re.sub(r"<[^>]+>", " ", prose))

# the semantic model id is an identifier, not a figure
prose = prose.replace("16d47b06", " ")

ungrounded = []
# a figure is not touching a letter on either side, and does not keep sentence
# punctuation: "106,624," is the figure 106,624 followed by a comma.
for tok in re.findall(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?[MK%]?(?![A-Za-z0-9])", prose):
    tok = tok.rstrip(".,")
    if not tok or tok in allowed:
        continue
    if re.fullmatch(r"20\d{2}", tok):        # a year
        continue
    ungrounded.append(tok)

ok(not ungrounded, "every figure in the prose must exist in the model: %s"
   % sorted(set(ungrounded))[:25])

MAX_DP = 2
overprecise = [t for t in re.findall(r"(?<![A-Za-z0-9])\d[\d,]*\.(\d+)", prose)
               if len(t) > MAX_DP]
ok(not overprecise, "no figure may carry more than %d decimal places: %s"
   % (MAX_DP, overprecise[:10]))

print("audit: %d checks, %d failed" % (checks, len(fails)))
for f in fails:
    print("  FAIL:", f)
sys.exit(1 if fails else 0)
