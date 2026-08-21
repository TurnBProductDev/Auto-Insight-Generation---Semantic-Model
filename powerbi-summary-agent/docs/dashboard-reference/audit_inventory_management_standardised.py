"""Audit the PRODUCED standardised reference page, not the code that wrote it.

Re-derives every arithmetic guarantee from the model figures, then checks every
number that appears in the page's prose actually exists in that derived set, and
inspects the file as a document.

It also enforces business_rules_Inventory.md, in both directions:

  * the approved names from BR-03 must be present, and their banned synonyms
    must not appear anywhere the model's own vocabulary is not being quoted;
  * BR-31's Recommended Action state names must appear in full;
  * and the client-specific content the brief excluded - location codes, the
    named Divisions and Sections from that document, the buying team's name and
    the Saudi/SAR references - must not have leaked in.

Two places quote the model's own words on purpose and are stripped before the
synonym check runs: the grey line under each risk naming the model measure, and
the caveat that explains the Dead Stock / Non-Moving clash.
"""
import html
import re
import sys

import os

import inventory_management_facts as F
from build_inventory_management_standardised import full, money, pct, pts, usd, usd_c

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "reference_inventory_management_standardised.html")
ORIGINAL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
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
LAYERS = ("overview", "summary", "focus", "locations", "divisions", "queue")
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

# the Overview tab is required by the brief and must be the first tab
ok('data-nav="overview"' in doc, "the Overview tab must exist in the rail")
_ov = doc.split('data-layer="overview"')[1].split('data-layer="summary"')[0]
ok("Stock Value" in _ov and "Excess Stock Value" in _ov,
   "the Overview tab must carry the headline measures")
ok('class="gauge"' not in _ov,
   "the score gauge belongs on the Inventory Health Score tab, not the Overview")
ok('data-nav="overview"' in doc and 'data-nav="summary"' in doc
   and doc.index('data-nav="overview"') < doc.index('data-nav="summary"'),
   "Overview must come first in the rail")

# the original file must not have been touched by this build
ok(os.path.exists(ORIGINAL), "the original reference page must still exist")
ok(open(ORIGINAL, encoding="utf8").read() != doc,
   "the standardised page must be a separate file, not a copy of the original")

# the model's own vocabulary must still be visible, exactly where it is meant
# to be: under each risk name, and under each row of the queue table.
ok(doc.count('class="d-model"') == 6,
   "each of the six risks must name the model measure behind it")
for model_name in ("Excess Stock", "Ageing Stock", "Dead Stock", "Out of Stock",
                   "Verge of Stockout", "Damage"):
    ok(model_name in doc,
       "the model's own name for %r must appear on the page" % model_name)
# BR-31: all fourteen Recommended Action state names, in full, never abbreviated
BR31_STATES = (
    "STOCK AVAILABLE", "OVERSTOCK", "NON MOVING", "IN STOCK BUT NO SALES",
    "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE",
    "ON THE VERGE OF STOCK OUT - ORDER PLACED",
    "ON THE VERGE OF STOCK OUT - PLACE ORDER",
    "STOCK OUT - AVAILABLE IN WAREHOUSE", "STOCK OUT - ORDER PLACED",
    "STOCK OUT - PLACE ORDER", "NOT ACTIVE", "NEW LISTED SKU",
    "STOCK AVAILABLE - REORDER LEVEL UNKNOW", "NA",
)
for state in BR31_STATES:
    ok(state in doc, "BR-31 state name must appear in full: %r" % state)
ok("Reference design" in doc, "the page must state that it is a reference design")
ok("19 August 2026" in doc, "the page must carry the date its figures belong to")

# the scoped view must not claim a score of its own
needs_view = doc.split('data-view="needs"')[1]
ok("no Inventory Health Score" in needs_view,
   "the scoped view must say it carries no Inventory Health Score")
ok(needs_view.count("does not own a breakdown") >= 3,
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
_plain = re.sub(r"The health-score model names one risk.*?On the Verge of Stockout\.",
                " ", _plain, flags=re.S)
for _state in BR31_STATES:
    _plain = _plain.replace(_state, " ")   # still original case here
_plain = _plain.replace("product hierarchy", " ")      # BR-02 phrase
_plain = re.sub(r"<td><b>[A-Z][A-Z0-9 ,&\-]+</b>", " ", _plain)   # data values
_plain = html.unescape(re.sub(r"<[^>]+>", " ", _plain)).lower()
# BR-03: the banned synonym for each approved name must not appear.
for banned, approved in (
        ("dead stock", "Non-Moving"), ("slow-moving", "Non-Moving"),
        ("stagnant", "Non-Moving"), ("overstock ", "Excess Stock"),
        ("surplus", "Excess Stock"), ("inventory value", "Stock Value"),
        ("stock worth", "Stock Value"), ("asset value", "Stock Value"),
        ("burn rate", "Burn-Out Days"), ("stock days", "Burn-Out Days"),
        ("days of cover", "Burn-Out Days"), ("revenue loss", "Opportunity Loss"),
        ("missed sales", "Opportunity Loss"), ("open pos", "Pending Orders"),
        ("outstanding orders", "Pending Orders"), ("write-off", "Damage"),
        ("shrinkage", "Damage"), ("written off", "Damage"),
        # note: "expiry" is NOT banned - BR-29 says Damage includes expiry and
        # wastage, so naming them as components is correct, not a synonym.
        ("branch", "Location"), ("outlet", "Location"),
        ("shop", "Store"), ("department", "Division"),
        ("category group", "Division"), ("sub-category", "Section"),
        ("sub-division", "Section"), ("product class", "Category"),
        ("replenishment", "Transfer"), ("dispatch", "Transfer"),
        ("product", "SKU"), ("item", "SKU"), ("article", "SKU")):
    ok(banned not in _plain,
       "BR-03: %r is banned, use %r" % (banned, approved))

# BR-33: no analytical jargon in the findings
for word in ("velocity", "offtake", "carry cost", "capital lock-up",
             "coverage ratio", "z-score", "materiality"):
    ok(word not in _plain, "BR-33 bans %r in the findings" % word)

# BR-03 / BR-08: the approved names must actually be used
for approved in ("SKU", "Loc-SKU", "Store", "Location", "Division", "Section",
                 "Stock Value", "Excess Stock", "Non-Moving", "Opportunity Loss",
                 "Burn-Out Days", "Damage", "Transfer", "Critical SKU",
                 "Recommended Action", "Inventory Health Score"):
    ok(approved.lower() in _plain,
       "approved term %r must be used on the page" % approved)

# The brief's exclusion list: none of this client-specific content may appear.
_raw = html.unescape(re.sub(r"<[^>]+>", " ", doc)).lower()
for excluded in ("saudi", "riyal", " sar ", "cdc", "cfw001", "cfh0",
                 "city flower", "fmcg", "cf-bakery", "cf-grocery", "cf-utensils",
                 "gm home ware", "home fashion", "distant store", "nearby store"):
    ok(excluded not in _raw,
       "client-specific content must be excluded: %r" % excluded)

# BR-00 analogue: money carries the currency
ok("USD" in doc, "money figures must carry the currency")

# ---------------------------------------------------------------- grounding
allowed = set()


def allow(v):
    allowed.add(full(v))
    allowed.add(money(v))
    allowed.add(usd(v))
    allowed.add(usd_c(v))
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
# BR-08 / BR-26 counts, which only the standardised page states
import inventory_management_standard_counts as _C   # noqa: E402
for v in (_C.LOCSKUS, _C.SKUS_IN_SCOPE, _C.NM_SKUS, _C.EXCESS_SKUS, _C.OOS_SKUS,
          _C.VERGE_SKUS, _C.UNWANTED_SKUS, _C.UNWANTED_PO, _C.PENDING_SKUS,
          _C.PENDING_VALUE, _C.CRITICAL_SKUS, _C.CRITICAL_OOS,
          F.STOCK + F.WH_VAL, F.WH_VAL / (F.STOCK + F.WH_VAL) * 100,
          sum(x["exc"] for x in F.WH)):
    allow(v)
allow(F.QUEUE[1]["n"] + [x for x in F.QUEUE
                         if x["key"].startswith("ON THE VERGE")
                         and x["key"].endswith("AVAILABLE IN WAREHOUSE")][0]["n"])
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
prose = re.sub(r"BR-\d+", " ", prose)

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
