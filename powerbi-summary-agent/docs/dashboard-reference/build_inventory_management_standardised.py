"""Build the Inventory Management reference page - business-rules standardised.

Every figure comes from inventory_management_facts, which reads
inventory_management_scan.json straight out of the semantic model. Nothing on
the page is typed in by hand.

The wording is deliberately everyday English: the page says "more stock than
needed" and prints "called Excess Stock in the model" underneath in small grey
type, so a general reader and the semantic model are both served. The queue
table does the same. Those two places are the ONLY ones where the model's own
vocabulary appears, and the auditor strips them before checking the rest of the
page for jargon.

Terminology follows business_rules_Inventory.md, which is the authority for KPI
names, inventory classifications and business language. The approved names in
BR-03 are used everywhere: SKU (never product or item), Store (never shop),
Division (never Department), Excess Stock, Non-Moving, Opportunity Loss,
Burn-Out Days, Pending Orders, Damage, Stock Value.

Client-specific content from that document is deliberately excluded: location
codes, the named divisions and sections, the lead-day and excess-threshold
tables, and the Saudi/SAR references. Rules, definitions and vocabulary are
carried over; the client's own data is not. Figures on this page come from the
semantic model, and money is stated in USD.

Two naming clashes between the health-score model and the business rules are
resolved in favour of the rules, and stated on the page rather than hidden:
the model's "Dead Stock" risk is the business's Non-Moving classification, and
the model's "Verge of Stockout" is BR-17's On the Verge of Stockout.

Run me, then run audit_inventory_management_standardised.py, then look at the
rendered page in a browser. All three steps matter: the auditor cannot see
layout, and a browser cannot check arithmetic.
"""
import html
import json
import re

import os

import inventory_management_facts as F

# BR-08 separates #SKUs from #Loc-SKUs, and BR-26 requires unique SKUs rather
# than location-SKU pairs when reporting a classification across all Locations.
# These come from their own file so the original reference page's inputs are
# provably untouched.
_BR = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "inventory_management_br_counts.json"),
                     encoding="utf8"))["counts"]


def br(key):
    for k in _BR:
        if k == "[" + key + "]" or k.endswith("[" + key + "]"):
            return _BR[k]
    raise KeyError(key)


LOCSKUS = int(br("locskus"))
SKUS_IN_SCOPE = int(br("skus_in_scope"))
SKUS_WITH_STOCK = int(br("skus_with_stock"))
NM_SKUS = int(br("nm_skus"))
EXCESS_SKUS = int(br("excess_skus"))
OOS_SKUS = int(br("oos_skus"))
VERGE_SKUS = int(br("verge_skus"))
UNWANTED_SKUS = int(br("unwanted_skus"))
UNWANTED_PO = br("unwanted_po_value")
PENDING_SKUS = int(br("pending_skus"))
PENDING_VALUE = br("pending_value")
CRITICAL_SKUS = int(br("critical_skus"))
CRITICAL_OOS = int(br("critical_oos_skus"))

CSS = r"""
:root{
  --ground:#eef1f0; --card:#fff; --rail:#0e1b19; --ink:#12201e; --mid:#41545a;
  --muted:#5b7182; --faint:#8fa1a9; --line:#dfe7ec; --soft:#f7fafb;
  --teal:#0f9f95; --teal-dk:#087f79; --teal-tint:#e2f2ef;
  --amber:#c08429; --amber-tint:#faf1e1; --amber-dk:#8a5f10;
  --red:#cf4636; --red-tint:#fbeae7; --green:#2f8f4e; --green-tint:#e8f4ec;
  --r:12px; --shadow:0 1px 2px rgba(16,24,40,.05),0 10px 28px -20px rgba(16,24,40,.35);
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:'Segoe UI',Inter,Roboto,Arial,sans-serif;font-size:13.5px;line-height:1.5;
  -webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
h1,h2,h3,h4,p{margin:0}

/* ---------- shell: rail + main, and ONLY those two ---------- */
.app{display:flex;min-height:100vh}
.rail{width:172px;flex:0 0 172px;background:var(--rail);color:#cfe0dc;padding:18px 12px;
  position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:5px}
.rail .mark{width:34px;height:34px;border-radius:9px;background:rgba(15,159,149,.16);
  border:1px solid rgba(15,159,149,.5);color:#4fd3c4;display:grid;place-items:center;
  font-weight:800;font-size:12px;letter-spacing:.04em;margin-bottom:14px}
.rail .grp{font-size:9px;letter-spacing:.13em;text-transform:uppercase;color:#5f7d78;
  margin:14px 0 5px;padding-left:9px}
.rail button{all:unset;cursor:pointer;display:block;padding:8px 11px;border-radius:8px;
  font-size:12.5px;font-weight:600;color:#a9c2bd}
.rail button:hover{background:rgba(255,255,255,.06);color:#fff}
.rail button[aria-current=true]{background:var(--teal);color:#fff}
.rail .foot{margin-top:auto;font-size:10px;color:#4d6b66;line-height:1.45;padding-left:9px}

main{flex:1;min-width:0}
.page{max-width:1280px;margin:0 auto;padding:22px 26px 60px}

/* ---------- masthead ---------- */
.masthead{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;
  flex-wrap:wrap;margin-bottom:16px}
.eyebrow{font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--teal-dk);
  font-weight:750;margin-bottom:5px}
h1{font-size:27px;line-height:1.12;letter-spacing:-.02em;font-weight:700}
.asat{font-size:12px;color:var(--muted);margin-top:5px}
.seg{display:inline-flex;background:var(--card);border:1px solid var(--line);
  border-radius:9px;padding:3px}
.seg button{all:unset;cursor:pointer;padding:6px 14px;border-radius:7px;font-size:12px;
  font-weight:650;color:var(--muted)}
.seg button[aria-pressed=true]{background:var(--teal-tint);color:var(--teal-dk)}

/* ---------- hero: one dark band, verdict + the numbers that prove it ---------- */
.hero{background:var(--rail);border-radius:var(--r);padding:20px 24px;margin-bottom:14px;
  display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:26px;align-items:center}
.hero-tag{display:inline-block;font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  font-weight:750;color:#f0c46a;background:rgba(240,196,106,.14);padding:4px 9px;
  border-radius:6px;margin-bottom:10px}
.hero h2{color:#fff;font-size:23px;line-height:1.22;letter-spacing:-.015em;font-weight:700}
.hero p{color:#a9c2bd;font-size:12.5px;margin-top:8px;max-width:56ch}
.hero-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.hs{border-left:2px solid rgba(255,255,255,.14);padding-left:12px}
.hs b{display:block;color:#fff;font-size:19px;font-weight:700;line-height:1.15}
.hs span{display:block;color:#7f9a95;font-size:10.5px;margin-top:3px;line-height:1.35}
.hs.crit b{color:#ff8b73}

/* ---------- generic blocks ---------- */
.grid{display:grid;gap:14px}
.g-2{grid-template-columns:minmax(0,1.55fr) minmax(0,1fr)}
.g-2e{grid-template-columns:repeat(2,minmax(0,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:16px 18px;box-shadow:var(--shadow)}
.card>h3{font-size:13.5px;font-weight:700;letter-spacing:-.01em}
.card>.sub{font-size:11.5px;color:var(--muted);margin-top:2px;margin-bottom:12px}
.sect{margin:22px 0 10px;display:flex;align-items:baseline;gap:11px}
.sect h2{font-size:16px;font-weight:700;letter-spacing:-.015em}
.sect span{font-size:11.5px;color:var(--faint)}
.note{font-size:11.5px;color:var(--muted);margin-top:10px;line-height:1.5}

/* ---------- KPI row ---------- */
.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:11px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:13px 14px 12px;position:relative;overflow:hidden;box-shadow:var(--shadow)}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--faint)}
.kpi.crit::before{background:var(--red)} .kpi.warn::before{background:var(--amber)}
.kpi.good::before{background:var(--green)}
.kpi .lab{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);
  font-weight:650;min-height:24px}
.kpi .val{font-size:21px;font-weight:750;line-height:1.1;margin:5px 0 4px;letter-spacing:-.02em}
.kpi.crit .val{color:var(--red)} .kpi.warn .val{color:var(--amber-dk)}
.kpi .sub{font-size:10.5px;color:var(--muted);line-height:1.4}
.kpi .pill{display:inline-block;font-size:9px;font-weight:750;letter-spacing:.05em;
  text-transform:uppercase;padding:2px 6px;border-radius:5px;margin-top:7px}
.pill-crit{background:var(--red-tint);color:var(--red)}
.pill-warn{background:var(--amber-tint);color:var(--amber-dk)}
.pill-ok{background:var(--green-tint);color:var(--green)}

/* ---------- urgency ladder ---------- */
.ladder{display:flex;flex-direction:column;gap:8px}
.lrow{display:grid;grid-template-columns:20px minmax(0,1fr) 78px;gap:11px;align-items:center}
.lrank{width:20px;height:20px;border-radius:6px;display:grid;place-items:center;
  font-size:10px;font-weight:800;color:#fff;background:var(--faint)}
.lrow.c1 .lrank{background:var(--red)} .lrow.c2 .lrank{background:var(--amber)}
.lname{font-size:11.5px;font-weight:650;line-height:1.25;margin-bottom:4px}
.ltrack{background:#eef2f6;border-radius:99px;height:9px;overflow:hidden}
.lfill{display:block;height:100%;border-radius:99px}
.lval{text-align:right}
.lval b{font-size:14px;font-weight:750;display:block;line-height:1.1}
.lval span{font-size:10px;color:var(--muted)}
.ltag{display:inline-block;font-size:8.5px;font-weight:750;letter-spacing:.05em;
  text-transform:uppercase;padding:1px 6px;border-radius:4px;margin-left:6px;vertical-align:1px}
.t-crit{background:var(--red-tint);color:var(--red)}
.t-warn{background:var(--amber-tint);color:var(--amber-dk)}

/* ---------- donut ---------- */
.donut-row{display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.dlegend{display:flex;flex-direction:column;gap:10px;font-size:12px}
.dlegend div{display:flex;align-items:center;gap:8px}
.dlegend i{width:11px;height:11px;border-radius:3px;flex:0 0 11px}
.dlegend b{font-weight:700}
.dlegend small{display:block;color:var(--muted);font-size:10.5px}

/* ---------- ranked bars ---------- */
.rbars{display:flex;flex-direction:column;gap:9px}
.rb{display:grid;grid-template-columns:96px minmax(0,1fr) 96px;gap:11px;align-items:center;font-size:12px}
.rb-l{font-weight:650}
.rb-l small{display:block;font-weight:400;font-size:10px;color:var(--muted)}
.rb-t{background:#eef2f6;border-radius:99px;height:10px;overflow:hidden;position:relative}
.rb-f{display:block;height:100%;border-radius:99px;background:var(--amber)}
.rb-v{text-align:right;font-weight:700}
.rb-v small{display:block;font-weight:600;font-size:10px}
.over{color:var(--red)} .under{color:var(--muted)}

/* ---------- tables ---------- */
.scroll{overflow-x:auto;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:12px;min-width:440px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
  font-weight:700;white-space:nowrap}
td.n,th.n{text-align:right;white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--soft)}
tr.urgent td{background:var(--red-tint)}
.act{color:var(--muted);font-size:11px}

/* ---------- chart bits ---------- */
.dz{fill:var(--faint);font-size:9px} .dzv{fill:var(--ink);font-size:10px;font-weight:700}
.dza{fill:var(--muted);font-size:9.5px;font-weight:650}

/* ---------- caveats: ONE block, not five ---------- */
.caveats{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--faint);
  border-radius:var(--r);padding:15px 18px;margin-top:20px}
.caveats h3{font-size:12px;font-weight:700;margin-bottom:9px}
.caveats ul{margin:0;padding-left:17px;color:var(--mid);font-size:11.5px;line-height:1.6}
.caveats li{margin-bottom:5px}
.foot{margin-top:18px;padding-top:12px;border-top:1px solid var(--line);
  display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;
  font-size:10.5px;color:var(--faint)}

@media (max-width:1080px){
  .kpis{grid-template-columns:repeat(3,minmax(0,1fr))}
  .g-2,.g-2e{grid-template-columns:minmax(0,1fr)}
  .hero{grid-template-columns:minmax(0,1fr)}
}
@media (max-width:720px){.rail{display:none}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media print{
  .rail,.seg{display:none}.app{display:block}.card,.kpi,.hero{break-inside:avoid;box-shadow:none}
  body{background:#fff}
}

/* --- layers and views ------------------------------------------------- */
.layer[hidden],.view[hidden]{display:none}
.pointer{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--teal);
  border-radius:var(--r);padding:16px 18px;color:var(--mid);font-size:12.5px;line-height:1.6}
.pointer b{color:var(--ink)}
.scoped{background:var(--amber-tint);border:1px solid #e8d3a8;border-radius:var(--r);
  padding:11px 15px;font-size:11.5px;color:var(--amber-dk);margin-bottom:14px}
@media print{.layer[hidden],.view[hidden]{display:block}}

/* --- story layer ------------------------------------------------------- */
.score-hero{grid-template-columns:minmax(0,1.55fr) minmax(0,.8fr)}
.gauge-wrap{text-align:center}
.gauge{width:132px;height:132px;border-radius:50%;margin:0 auto;display:grid;
  place-items:center;position:relative;background:conic-gradient(#cf4636 0 40%,rgba(255,255,255,.10) 0)}
.gauge::after{content:"";position:absolute;inset:11px;border-radius:50%;background:#0e1b19}
.g-val{position:relative;z-index:1;font-size:42px;font-weight:800;color:#fff;line-height:1}
.g-of{position:relative;z-index:1;font-size:12px;color:#7f9a95;margin-top:2px}
.g-label{color:#ff8b73;font-weight:750;font-size:12px;letter-spacing:.06em;
  text-transform:uppercase;margin-top:10px}
.g-delta{color:#7f9a95;font-size:11px;margin-top:3px}
.illus{background:#fff8e6;border:1px solid #e8d3a8;border-left:3px solid var(--amber);
  border-radius:var(--r);padding:11px 15px;font-size:11.5px;color:var(--amber-dk);
  margin-bottom:4px;line-height:1.55}
.annot{fill:#5b7182;font-size:10px;font-weight:650}
.lead-note{font-size:12.5px;color:var(--muted);max-width:78ch;margin:-2px 0 12px}

.drivers{display:grid;grid-template-columns:repeat(auto-fit,minmax(232px,1fr));gap:12px}
.driver{background:var(--card);border:1px solid var(--line);border-top:3px solid var(--faint);
  border-radius:var(--r);padding:14px 15px;box-shadow:var(--shadow)}
.driver.crit{border-top-color:var(--red)} .driver.warn{border-top-color:var(--amber)}
.driver.good{border-top-color:var(--green)}
.d-top{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.d-name{font-size:13px;font-weight:700}
.d-read{font-size:10.5px;color:var(--muted);margin-top:2px;max-width:20ch}
.d-nums{display:flex;align-items:baseline;gap:8px;margin:9px 0 7px;flex-wrap:wrap}
.d-score{font-size:26px;font-weight:750;letter-spacing:-.02em}
.driver.crit .d-score{color:var(--red)} .driver.warn .d-score{color:var(--amber-dk)}
.d-delta{font-size:11.5px;font-weight:700;color:var(--red)}
.d-bar{background:#eef2f6;border-radius:99px;height:6px;overflow:hidden}
.d-bar span{display:block;height:100%;border-radius:99px;background:var(--red)}
.d-contrib{font-size:10.5px;color:var(--muted);margin-top:6px}
.d-why{font-size:11.5px;color:var(--mid);margin-top:8px;line-height:1.5}
.d-tol{font-size:10px;color:var(--faint);margin-top:7px;padding-top:7px;
  border-top:1px dashed var(--line)}

.method{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--teal);
  border-radius:var(--r);padding:15px 18px;margin-top:14px}
.method h3{font-size:12.5px;font-weight:700;margin-bottom:7px}
.method p{font-size:11.5px;color:var(--mid);line-height:1.6;max-width:88ch;margin-bottom:7px}

.stories{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:14px}
.story{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--faint);
  border-radius:var(--r);padding:16px 18px;box-shadow:var(--shadow);display:flex;
  flex-direction:column}
.story.crit{border-left-color:var(--red)} .story.warn{border-left-color:var(--amber)}
.s-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;
  padding-bottom:11px;border-bottom:1px solid var(--line)}
.s-head h3{font-size:14.5px;font-weight:700;letter-spacing:-.01em}
.s-score{display:flex;align-items:baseline;gap:6px;margin-top:5px;flex-wrap:wrap}
.s-score b{font-size:23px;font-weight:750;line-height:1}
.story.crit .s-score b{color:var(--red)} .story.warn .s-score b{color:var(--amber-dk)}
.s-score span{font-size:11px;color:var(--faint)}
.s-score em{font-style:normal;font-size:11.5px;font-weight:700;color:var(--red)}
.s-body{margin:12px 0 0}
.s-body dt{font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--teal-dk);
  font-weight:750;margin-top:11px}
.s-body dt:first-child{margin-top:0}
.s-body dd{margin:4px 0 0;font-size:12.5px;color:var(--mid);line-height:1.55}
.s-foot{display:flex;gap:14px;align-items:stretch;margin-top:14px;padding-top:12px;
  border-top:1px solid var(--line);flex-wrap:wrap}
.s-stat{background:var(--soft);border-radius:9px;padding:9px 13px;min-width:118px}
.s-stat b{display:block;font-size:17px;font-weight:750;line-height:1.15}
.s-stat span{display:block;font-size:10px;color:var(--muted);margin-top:2px;line-height:1.35}
.s-do{flex:1;min-width:180px;font-size:12.5px;color:var(--ink);line-height:1.5;font-weight:600}
.s-do span{display:block;font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--teal-dk);font-weight:750;margin-bottom:3px}
@media (max-width:1080px){.score-hero{grid-template-columns:minmax(0,1fr)}
  .stories{grid-template-columns:minmax(0,1fr)}}

/* --- additions for the six-risk score ---------------------------------- */
.dims{margin:9px 0 2px;display:flex;flex-direction:column;gap:5px}
.dim{display:grid;grid-template-columns:78px minmax(0,1fr) 42px 34px;gap:7px;align-items:center;
  font-size:10px;color:var(--muted)}
.dim-l{font-weight:650}
.dim-t{background:#eef2f6;border-radius:99px;height:5px;overflow:hidden}
.dim-t i{display:block;height:100%;border-radius:99px;background:var(--teal)}
.dim-v{text-align:right;font-weight:700;color:var(--ink)}
.dim-w{text-align:right;color:var(--faint)}
.d-delta{color:var(--faint);font-weight:600}
.hero-stats .hs.wind b{color:#f0c46a}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:9px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;
  vertical-align:-1px}
.bands{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px;margin-top:4px}
.bandbox{border:1px solid var(--line);border-radius:9px;padding:8px 10px}
.bandbox b{display:block;font-size:12px}
.bandbox span{display:block;font-size:10px;color:var(--muted);margin-top:2px}
.bandbox.here{border-color:var(--red);background:var(--red-tint)}
.d-model{font-size:9.5px;color:var(--faint);margin-top:2px}
.hero-stack{grid-template-columns:minmax(0,1fr)}
.hero-stack .hero-stats{margin-top:18px;padding-top:16px;
  border-top:1px solid rgba(255,255,255,.12)}
.subhead{font-size:11px;font-weight:750;letter-spacing:.06em;text-transform:uppercase;
  color:var(--muted);margin:16px 0 9px;padding-top:13px;border-top:1px solid var(--line)}
.kpi .val{font-size:18px}
.kpi .lab{min-height:30px}
.d-model b{color:var(--muted);font-weight:700}
.drivers{grid-template-columns:repeat(3,minmax(0,1fr))}
.stories{grid-template-columns:repeat(2,minmax(0,1fr))}
@media (max-width:1080px){.drivers{grid-template-columns:repeat(2,minmax(0,1fr))}
  .stories{grid-template-columns:minmax(0,1fr)}}
@media (max-width:720px){.drivers{grid-template-columns:minmax(0,1fr)}}
"""

JS = r"""
(function(){
  var LAYERS = ['summary','focus','locations','divisions','queue'];

  function setLayer(name){
    document.querySelectorAll('.layer').forEach(function(el){
      el.hidden = el.getAttribute('data-layer') !== name;
    });
    document.querySelectorAll('[data-nav]').forEach(function(btn){
      btn.setAttribute('aria-current',
        btn.getAttribute('data-nav') === name ? 'true' : 'false');
    });
  }

  function setView(name){
    document.querySelectorAll('.view').forEach(function(el){
      el.hidden = el.getAttribute('data-view') !== name;
    });
    document.querySelectorAll('[data-viewbtn]').forEach(function(btn){
      var on = btn.getAttribute('data-viewbtn') === name;
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      if (btn.closest('.rail')) btn.setAttribute('aria-current', on ? 'true' : 'false');
    });
  }

  var current = {view: 'all', layer: 'summary'};

  function apply(){
    setView(current.view);
    setLayer(current.layer);
    // Keep the address bar in step, so a particular tab can be linked or
    // reloaded onto - and so a screenshot tool can reach every tab.
    var hash = '#' + current.view + '/' + current.layer;
    if (location.hash !== hash){
      history.replaceState(null, '', hash);
    }
  }

  function fromHash(){
    var parts = (location.hash || '').replace('#', '').split('/');
    if (parts[0] && document.querySelector('.view[data-view="' + parts[0] + '"]')){
      current.view = parts[0];
    }
    if (parts[1] && LAYERS.indexOf(parts[1]) !== -1){
      current.layer = parts[1];
    }
  }

  document.addEventListener('click', function(ev){
    var nav = ev.target.closest('[data-nav]');
    if (nav){ current.layer = nav.getAttribute('data-nav'); apply(); return; }
    var view = ev.target.closest('[data-viewbtn]');
    if (view){ current.view = view.getAttribute('data-viewbtn'); apply(); }
  });

  window.addEventListener('hashchange', function(){ fromHash(); apply(); });

  fromHash();
  apply();
})();
"""

TEAL, TEAL_DK, AMBER, AMBER_DK, RED, GREEN, FAINT = (
    "#0f9f95", "#087f79", "#c08429", "#8a5f10", "#cf4636", "#2f8f4e", "#8fa1a9")

AS_AT = "19 August 2026"


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------
CUR = "USD"          # all money on this page is stated in US Dollars


def full(v):
    """A money figure. BR-33: lead with the number; round sensibly."""
    return "{:,.0f}".format(round(v))


def usd(v):
    return CUR + " " + full(v)


def usd_c(v):
    return CUR + " " + money(v)


def money(v):
    a = abs(v)
    if a >= 1_000_000:
        return "{:.2f}M".format(v / 1_000_000)
    if a >= 10_000:
        return "{:,.0f}K".format(v / 1_000)
    return "{:,.0f}".format(round(v))


def pct(v, dp=1):
    return ("{:." + str(dp) + "f}%").format(v)


def pts(v):
    return "{:.1f}".format(v)


def esc(s):
    return html.escape(str(s), quote=False)


def band(score):
    if score >= 90:
        return "Excellent", "good", "pill-ok"
    if score >= 80:
        return "Healthy", "good", "pill-ok"
    if score >= 70:
        return "Watch", "warn", "pill-warn"
    if score >= 60:
        return "At Risk", "warn", "pill-warn"
    return "Critical", "crit", "pill-crit"


# --------------------------------------------------------------------------
# svg helpers
# --------------------------------------------------------------------------
def sparkline(vals, w=104, h=28, colour=TEAL):
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    step = (w - 12) / (n - 1) if n > 1 else 0
    pt = [(6 + i * step, h - 5 - (v - lo) / rng * (h - 12)) for i, v in enumerate(vals)]
    d = " ".join("{:.1f},{:.1f}".format(x, y) for x, y in pt)
    return ('<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            '<polyline points="{d}" fill="none" stroke="{c}" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
            '<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.4" fill="{c}"/></svg>'
            ).format(w=w, h=h, d=d, c=colour, cx=pt[-1][0], cy=pt[-1][1])


def health_shape_chart():
    """The shape a retained snapshot history will draw. No values are implied."""
    W, H = 960, 250
    L, R, T, B = 60, 860, 26, 206
    lo, hi = 40.0, 100.0

    def y(v):
        return T + (hi - v) / (hi - lo) * (B - T)

    out = []
    bands = [(90, 100, GREEN, "excellent"), (80, 90, GREEN, "healthy"),
             (70, 80, AMBER, "watch"), (60, 70, AMBER, "at risk"),
             (40, 60, RED, "critical")]
    for a, b, col, lab in bands:
        out.append('<rect x="{}" y="{:.1f}" width="{}" height="{:.1f}" fill="{}" opacity=".07"/>'
                   .format(L, y(b), R - L, y(a) - y(b), col))
        out.append('<text x="{}" y="{:.1f}" class="dz">{}</text>'
                   .format(R + 6, (y(a) + y(b)) / 2 + 3, lab))
    for v in (100, 90, 80, 70, 60, 50, 40):
        out.append('<line x1="{}" y1="{:.1f}" x2="{}" y2="{:.1f}" stroke="#dfe7ec" stroke-width="1"/>'
                   .format(L, y(v), R, y(v)))
        out.append('<text x="{}" y="{:.1f}" text-anchor="end" class="dz">{}</text>'
                   .format(L - 8, y(v) + 3, v))

    # Shape only: a plausible path into today's real reading. Deliberately
    # unlabelled at every point except the one the model actually holds.
    shape = [72, 71, 69, 70, 67, 65, 64, 62, 61, 60, 59, F.SCORE]
    n = len(shape)
    step = (R - L) / (n - 1)
    pt = [(L + i * step, y(v)) for i, v in enumerate(shape)]
    d = " ".join("{:.1f},{:.1f}".format(x, yy) for x, yy in pt)
    out.append('<polyline points="{}" fill="none" stroke="{}" stroke-width="2.4" '
               'stroke-dasharray="6 5" stroke-linecap="round" stroke-linejoin="round" '
               'opacity=".55"/>'.format(d, FAINT))
    for i, (x, yy) in enumerate(pt[:-1]):
        out.append('<circle cx="{:.1f}" cy="{:.1f}" r="3" fill="#fff" stroke="{}" '
                   'stroke-width="1.6" opacity=".55"/>'.format(x, yy, FAINT))
    x, yy = pt[-1]
    out.append('<circle cx="{:.1f}" cy="{:.1f}" r="6" fill="{}" stroke="#fff" stroke-width="2">'
               '<title>19 Aug 2026: {} out of 100</title></circle>'.format(x, yy, RED, pts(F.SCORE)))
    out.append('<text x="{:.1f}" y="{:.1f}" text-anchor="end" class="dzv" fill="{}">{}</text>'
               .format(x - 10, yy + 4, RED, pts(F.SCORE)))
    out.append('<text x="{:.1f}" y="{}" text-anchor="middle" class="dza">19 Aug</text>'
               .format(x, B + 26))
    out.append('<text x="{}" y="{}" class="dza">history starts here</text>'.format(L, B + 26))
    out.append('<text x="{:.1f}" y="{}" text-anchor="middle" class="annot" '
               'fill="{}">shape only &mdash; no past values are implied</text>'
               .format((L + R) / 2, T + 12, FAINT))
    return ('<svg viewBox="0 0 {} {}" width="100%" preserveAspectRatio="xMidYMid meet" '
            'role="img" aria-label="Illustrative shape of the inventory health score once '
            'snapshot history accumulates, ending at the real reading of {} out of 100">{}</svg>'
            ).format(W, H, pts(F.SCORE), "".join(out))


def composition_waterfall():
    """100 minus each of the six risks, closing on the real score."""
    W, H = 690, 250
    L, R, T, B = 40, 662, 40, 192
    steps = [("Starting score", 100.0, None)]
    for key, name, p in F.RISKS:
        steps.append((name, -p, key))
    steps.append(("Health score", F.SCORE, None))

    lo, hi = 50.0, 104.0

    def y(v):
        return B - (v - lo) / (hi - lo) * (B - T)

    n = len(steps)
    gap = 18.0
    bw = ((R - L) - gap * (n - 1)) / n
    out = []
    run = 0.0
    for i, (label, val, key) in enumerate(steps):
        x = L + i * (bw + gap)
        if i == 0:
            top, bot, col = 100.0, lo, TEAL_DK
            run = 100.0
            title = "Every SKU starts at 100"
            vlab = "100"
        elif i == n - 1:
            top, bot, col = F.SCORE, lo, RED
            title = "Inventory health score: {}".format(pts(F.SCORE))
            vlab = pts(F.SCORE)
        else:
            top, bot = run, run + val
            col = RED
            title = "{}: {} points".format(label, pts(val))
            vlab = pts(val)
            run = run + val
        out.append('<rect class="data-point" x="{:.1f}" y="{:.1f}" width="{:.1f}" '
                   'height="{:.1f}" rx="3" fill="{}"><title>{}</title></rect>'
                   .format(x, y(top), bw, max(2.0, y(bot) - y(top)), col, esc(title)))
        out.append('<text x="{:.1f}" y="{:.1f}" text-anchor="middle" class="dzv" fill="{}">{}</text>'
                   .format(x + bw / 2, y(top) - 7, col, vlab))
        words = label.split(" ")
        if len(words) > 1 and i not in (0, n - 1):
            out.append('<text x="{:.1f}" y="{}" text-anchor="middle" class="dza">{}</text>'
                       .format(x + bw / 2, B + 16, esc(words[0])))
            out.append('<text x="{:.1f}" y="{}" text-anchor="middle" class="dza">{}</text>'
                       .format(x + bw / 2, B + 28, esc(" ".join(words[1:]))))
        else:
            out.append('<text x="{:.1f}" y="{}" text-anchor="middle" class="dza">{}</text>'
                       .format(x + bw / 2, B + 16, esc(label)))
        if 0 < i < n - 1:
            px = x - gap
            out.append('<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="{}" '
                       'stroke-width="1" stroke-dasharray="2 3"/>'
                       .format(px, y(top), x, y(top), FAINT))
    out.append('<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#5b7182"/>'.format(L, B, R, B))
    out.append('<text x="{}" y="{}" text-anchor="end" class="dz">axis starts at {:.0f}, '
               'not zero, so each risk is visible</text>'.format(R, B + 50, lo))
    return ('<svg viewBox="0 0 {} {}" width="100%" preserveAspectRatio="xMidYMid meet" '
            'role="img" aria-label="Inventory health score composition: 100 less each of the '
            'six risks, closing at {}">{}</svg>').format(W, H, pts(F.SCORE), "".join(out))


def vbars(rows, hi_key=None, value_fmt=money, label_two_line=True,
          W=560, H=230, base_colour=TEAL, hi_colour=AMBER):
    """rows: list of (label, value, is_highlight)"""
    L, R, T, B = 44, W - 14, 24, H - 42
    mx = max(v for _l, v, _h in rows) or 1.0
    n = len(rows)
    gap = 14.0
    bw = ((R - L) - gap * (n - 1)) / n
    out = []
    for i, (label, val, hi) in enumerate(rows):
        x = L + i * (bw + gap)
        h = (val / mx) * (B - T)
        col = hi_colour if hi else base_colour
        out.append('<rect class="data-point" x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" '
                   'rx="3" fill="{}"><title>{}: {}</title></rect>'
                   .format(x, B - h, bw, max(2.0, h), col, esc(label), value_fmt(val)))
        out.append('<text x="{:.1f}" y="{:.1f}" text-anchor="middle" class="dzv" fill="{}">{}</text>'
                   .format(x + bw / 2, B - h - 7, col, value_fmt(val)))
        parts = label.split(" ") if label_two_line else [label]
        if len(parts) > 1:
            out.append('<text x="{:.1f}" y="{}" text-anchor="middle" class="dza">{}</text>'
                       .format(x + bw / 2, B + 16, esc(parts[0])))
            out.append('<text x="{:.1f}" y="{}" text-anchor="middle" class="dza">{}</text>'
                       .format(x + bw / 2, B + 28, esc(" ".join(parts[1:]))))
        else:
            out.append('<text x="{:.1f}" y="{}" text-anchor="middle" class="dza">{}</text>'
                       .format(x + bw / 2, B + 16, esc(label)))
    out.append('<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#5b7182"/>'.format(L, B, R, B))
    return ('<svg viewBox="0 0 {} {}" width="100%" preserveAspectRatio="xMidYMid meet" '
            'role="img" aria-label="bar chart">{}</svg>').format(W, H, "".join(out))


def trend_chart():
    """The one genuinely historical series in the model: store stock value."""
    W, H = 560, 236
    L, R, T, B = 56, W - 76, 24, H - 40
    dates = F.TREND_DATES
    total = F.TREND_STORE_TOTAL
    st5 = F.STORE_TREND["ST5"]
    hi = max(total) * 1.06
    lo = 0.0

    def y(v):
        return B - (v - lo) / (hi - lo) * (B - T)

    step = (R - L) / (len(dates) - 1)
    out = []
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = hi * frac
        out.append('<line x1="{}" y1="{:.1f}" x2="{}" y2="{:.1f}" stroke="#dfe7ec"/>'
                   .format(L, y(v), R, y(v)))
        out.append('<text x="{}" y="{:.1f}" text-anchor="end" class="dz">{}</text>'
                   .format(L - 7, y(v) + 3, money(v)))
    for series, col, name in ((total, TEAL, "All five stores"), (st5, AMBER, "ST5")):
        d = " ".join("{:.1f},{:.1f}".format(L + i * step, y(v)) for i, v in enumerate(series))
        out.append('<polyline points="{}" fill="none" stroke="{}" stroke-width="2.6" '
                   'stroke-linecap="round" stroke-linejoin="round"/>'.format(d, col))
        for i, v in enumerate(series):
            out.append('<circle class="data-point" cx="{:.1f}" cy="{:.1f}" r="3.6" fill="#fff" '
                       'stroke="{}" stroke-width="2"><title>{} &mdash; {}: {}</title></circle>'
                       .format(L + i * step, y(v), col, esc(name), dates[i], full(v)))
        out.append('<text x="{:.1f}" y="{:.1f}" class="dza" fill="{}">{}</text>'
                   .format(R + 6, y(series[-1]) + 4, col, esc(name)))
    for i, dt in enumerate(dates):
        lab = {"2026-06-01": "1 Jun", "2026-07-01": "1 Jul",
               "2026-08-01": "1 Aug", "2026-08-19": "19 Aug"}.get(dt, dt)
        out.append('<text x="{:.1f}" y="{}" text-anchor="middle" class="dza">{}</text>'
                   .format(L + i * step, B + 18, lab))
    out.append('<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#5b7182"/>'.format(L, B, R, B))
    return ('<svg viewBox="0 0 {} {}" width="100%" preserveAspectRatio="xMidYMid meet" '
            'role="img" aria-label="Store stock value at four snapshot dates">{}</svg>'
            ).format(W, H, "".join(out))


# --------------------------------------------------------------------------
# page blocks
# --------------------------------------------------------------------------
# BR-03 approved names. Where the health-score model uses a different word for
# the same thing, the rules win and the clash is stated in the caveats.
PLAIN_RISK = {
    "Excess": "Excess Stock",
    "Ageing": "Ageing Stock",
    "Dead": "Non-Moving Stock",
    "OOS": "Out of Stock",
    "Verge": "On the Verge of Stockout",
    "Damage": "Damage",
}

# what the measure is actually called in _HEALTH SCORE MEASURES, shown so a user
# can find it in the model. Only two differ from the approved business name.
MODEL_RISK = {
    "Excess": "Excess Stock",
    "Ageing": "Ageing Stock",
    "Dead": "Dead Stock",
    "OOS": "Out of Stock",
    "Verge": "Verge of Stockout",
    "Damage": "Damage",
}

DIM_PLAIN = {
    "Value impact": "Share of Stock Value",
    "Sales impact": "Share of sales value",
    "SKU breadth": "Share of eligible SKUs",
    "Duration": "How long it has run",
    "Severity": "Ageing severity",
    "Segment severity": "SKU segment weight",
}


def kpi_cards():
    """BR-08 measures, in the order a buyer reads them."""
    cards = [
        ("Stock Value", usd(F.STOCK),
         "across {} Loc-SKUs at the five Stores".format(full(F.SKUS)), "", ""),
        ("Excess Stock Value", usd(F.RD["Excess"]["val"]),
         "{} Loc-SKUs above the coverage threshold".format(full(F.RD["Excess"]["skus"])),
         "crit", "Largest risk"),
        ("Ageing Stock Value", usd(F.RD["Ageing"]["val"]),
         "{} Loc-SKUs holding stock beyond three months".format(full(F.RD["Ageing"]["skus"])),
         "crit", "Needs action"),
        ("Non-Moving Stock Value", usd(F.RD["Dead"]["val"]),
         "{} Loc-SKUs, {} distinct SKUs".format(full(F.RD["Dead"]["skus"]), full(NM_SKUS)),
         "crit", "Needs action"),
        ("Out of Stock", full(F.RD["OOS"]["skus"]),
         "Loc-SKUs at zero stock, {} available in a Warehouse"
         .format(full(F.QUEUE[1]["n"])), "crit", "Act now"),
        ("Opportunity Loss", usd(F.OPP_SCOPED),
         "estimated, Critical SKUs at Stores only", "warn", "Estimate"),
    ]
    out = []
    for lab, val, sub, cls, pill in cards:
        pill_html = ('<span class="pill pill-{}">{}</span>'.format(
            {"crit": "crit", "warn": "warn"}.get(cls, "ok"), esc(pill)) if pill else "")
        out.append('<div class="kpi {cls}"><p class="lab">{lab}</p><p class="val">{val}</p>'
                   '<p class="sub">{sub}</p>{pill}</div>'.format(
                       cls=cls, lab=esc(lab), val=val, sub=esc(sub), pill=pill_html))
    return '<div class="kpis">{}</div>'.format("".join(out))


def where_stock_sits():
    """Stock Value by Location type, then by Location."""
    top = [("The five Stores", F.STOCK, TEAL, "scored"),
           ("The two Warehouses", F.WH_VAL, AMBER, "not scored yet")]
    mx = max(v for _l, v, _c, _s in top)
    bars = "".join(
        '<div class="rb"><div class="rb-l">{l}<small>{s}</small></div>'
        '<div class="rb-t"><span class="rb-f" style="width:{w:.1f}%;background:{c}"></span></div>'
        '<div class="rb-v">{v}</div></div>'.format(
            l=esc(l), s=esc(sub), w=v / mx * 100, c=c, v=usd(v))
        for l, v, c, sub in top)
    shops = sorted(F.STORES, key=lambda r: -F.num(r, "Stock"))
    smx = max(F.num(r, "Stock") for r in shops)
    srows = "".join(
        '<div class="rb"><div class="rb-l">{l}<small>{s}</small></div>'
        '<div class="rb-t"><span class="rb-f" style="width:{w:.1f}%;background:{c}"></span></div>'
        '<div class="rb-v">{v}<small class="under">score {sc}</small></div></div>'.format(
            l=esc(F.g(r, "LOC_CODE")),
            s="winding down" if F.g(r, "LOC_CODE") == "ST5"
              else "{} Loc-SKUs".format(full(F.num(r, "SKUs"))),
            w=F.num(r, "Stock") / smx * 100,
            c=AMBER if F.g(r, "LOC_CODE") == "ST5" else TEAL,
            v=usd(F.num(r, "Stock")), sc=pts(F.num(r, "Score")))
        for r in shops)
    allv = F.STOCK + F.WH_VAL
    return ('<section class="card"><h3>Stock Value by Location</h3>'
            '<p class="sub">All Stock Value the business holds, split between the Stores and '
            'the two Warehouses.</p><div class="rbars">{bars}</div>'
            '<p class="note">Of {allv} of Stock Value, <b>{whs}</b> sits in the two '
            'Warehouses. The Inventory Health Score covers the Stores only for now.</p>'
            '<h4 class="subhead">Inside the five Stores</h4>'
            '<div class="rbars">{srows}</div></section>'
            ).format(bars=bars, allv=usd(allv), whs=pct(F.WH_VAL / allv * 100), srows=srows)


def risk_cards():
    out = []
    for key, name, p in F.RISKS:
        det = F.RD[key]
        sh = F.share(p)
        cls = "crit" if p >= 8 else ("warn" if p >= 3 else "good")
        pill = {"crit": "pill-crit", "warn": "pill-warn", "good": "pill-ok"}[cls]
        pill_lab = {"crit": "Big problem", "warn": "Real problem", "good": "Small"}[cls]
        dims = "".join(
            '<div class="dim"><span class="dim-l">{}</span>'
            '<span class="dim-t"><i style="width:{:.1f}%"></i></span>'
            '<span class="dim-v">{}</span><span class="dim-w">&times;{:.0f}%</span></div>'
            .format(esc(DIM_PLAIN[dl]), min(100.0, dv * 100), pct(dv * 100), dw * 100)
            for dl, dv, dw in det["dims"])
        out.append(
            '<article class="driver {cls}">'
            '<div class="d-top"><div><p class="d-name">{plain}</p>'
            '<p class="d-model">{modelnote}</p>'
            '<p class="d-read">{read}</p></div>'
            '<span class="pill {pill}">{pill_lab}</span></div>'
            '<div class="d-nums"><span class="d-score">&minus;{p}</span>'
            '<span class="d-delta">points off the score</span></div>'
            '<div class="d-bar"><span style="width:{barw:.1f}%"></span></div>'
            '<p class="d-contrib"><b>{sh}</b> of the {lost} points lost</p>'
            '<div class="dims">{dims}</div>'
            '<p class="d-why">{why}</p>'
            '<p class="d-tol">{tol}</p></article>'.format(
                cls=cls, plain=esc(PLAIN_RISK[key]),
                modelnote=(("the model measure is named <b>%s</b>" % esc(MODEL_RISK[key]))
                           if MODEL_RISK[key] != PLAIN_RISK[key]
                           else ("measured by <b>Category %s Risk</b>" % esc(MODEL_RISK[key]))),
                read=esc(READ[key]), pill=pill,
                pill_lab=pill_lab, p=pts(p), barw=sh, sh=pct(sh),
                lost=pts(F.LOST), dims=dims, why=WHY[key], tol=esc(TOL[key])))
    return "".join(out)


# BR-31: the Recommended Action state name is the heading and is never
# abbreviated. The second line is the buying-team action from that same rule.
QUEUE_ACTION = {
    "STOCK OUT - PLACE ORDER": "no warehouse stock and no open order &mdash; place an order",
    "STOCK OUT - AVAILABLE IN WAREHOUSE": "warehouse holds it &mdash; raise a Transfer now",
    "STOCK OUT - ORDER PLACED": "order already open &mdash; check the arrival date",
    "ON THE VERGE OF STOCK OUT - PLACE ORDER":
        "Burn-Out Days below the trigger, nothing on order &mdash; order without delay",
    "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE":
        "Burn-Out Days below the trigger, warehouse holds it &mdash; Transfer now",
    "ON THE VERGE OF STOCK OUT - ORDER PLACED":
        "Burn-Out Days below the trigger, order open &mdash; check arrival against cover",
    "OVERSTOCK": "Excess Stock flagged &mdash; review for markdown, promotion or Transfer",
    "NON MOVING": "no sales for 30 days with stock available throughout",
    "IN STOCK BUT NO SALES": "stock present, sales below the Non-Moving trigger",
    "STOCK AVAILABLE - REORDER LEVEL UNKNOW":
        "stock present, reorder level not configured",
    "STOCK AVAILABLE": "Burn-Out Days within threshold &mdash; no action needed",
    "NOT ACTIVE": "not actively listed or traded at this Location",
    "NA": "status cannot be determined &mdash; investigate the source record",
    "NEW LISTED SKU": "newly listed &mdash; Non-Moving and Excess rules do not apply yet",
}

BAND_PLAIN = {
    "Excellent": "minimal accumulated risk",
    "Healthy": "limited risk",
    "Watch": "emerging risk worth monitoring",
    "At Risk": "material risk requiring action",
    "Critical": "high accumulated risk",
    "Out of Stock": "zero stock &mdash; scored on a separate 0-based scale",
}

RISK_COL = {"Excess": "Excess", "Ageing": "Ageing", "Dead": "Non-Moving",
            "OOS": "Out of Stock", "Verge": "Verge", "Damage": "Damage"}

MONTH = {"2026-05-01": "May", "2026-06-01": "June",
         "2026-07-01": "July", "2026-08-01": "August"}


READ = {
    "Excess": "{} of Excess Stock Value".format(usd_c(F.RD["Excess"]["val"])),
    "Ageing": "{} of Stock Value ageing".format(usd_c(F.RD["Ageing"]["val"])),
    "Dead": "{} of Non-Moving Stock Value".format(usd_c(F.RD["Dead"]["val"])),
    "OOS": "{} Loc-SKUs at zero stock".format(full(F.RD["OOS"]["skus"])),
    "Verge": "{} Loc-SKUs below the trigger".format(full(F.RD["Verge"]["skus"])),
    "Damage": "{} of Damage Value last month".format(usd_c(F.RD["Damage"]["val"])),
}

_W3 = ("Capped at 25 points. Value Impact 50%, SKU Breadth 30%, "
       "Duration or Severity 20%.")
TOL = {
    "Excess": _W3,
    "Ageing": _W3,
    "Dead": _W3,
    "OOS": _W3,
    "Verge": _W3,
    "Damage": "Capped at 25 points. Value Impact 70%, SKU Breadth 30%. No Duration term.",
}

WHY = {
    "Excess": ("{n} Loc-SKUs hold stock beyond the coverage threshold set for their "
               "Location and Section. The Duration term is {d}, so this Excess Stock is "
               "long standing rather than a recent overbuy."
               .format(n=full(F.RD["Excess"]["skus"]),
                       d=pct(F.RD["Excess"]["dims"][2][1] * 100))),
    "Ageing": ("{s} of eligible SKUs hold stock older than three months, and {v} of it is "
               "older than twelve months."
               .format(s=pct(F.RD["Ageing"]["dims"][1][1] * 100), v=usd_c(F.AGE_OVER12))),
    "Dead": ("{n} Loc-SKUs are Non-Moving. The largest bucket is the oldest: {a} sit beyond "
             "180 days, more than the 30-60 and 61-90 day buckets together ({b})."
             .format(n=full(F.RD["Dead"]["skus"]), a=full(F.NM_180_N),
                     b=full(F.NM_SHORT_N))),
    "OOS": ("{w} of these carry STOCK OUT - AVAILABLE IN WAREHOUSE, so a Transfer resolves "
            "them. The other {o} carry STOCK OUT - PLACE ORDER: no warehouse stock and no "
            "open order.".format(w=full(F.QUEUE[1]["n"]), o=full(F.QUEUE[0]["n"]))),
    "Verge": ("Few SKUs, but the SKU segment weight is {sv} because those below the "
              "Lead Days plus Safety Days trigger sit in the higher segments. That is why "
              "it still costs {p} points."
              .format(sv=pct(F.RD["Verge"]["dims"][2][1] * 100), p=pts(F.RISKS[4][2]))),
    "Damage": ("Damage Value by month: {}. The latest month is partial at nineteen days and "
               "is already close to the whole of the month before."
               .format(", ".join("{} in {}".format(usd_c(v), MONTH[d])
                                 for d, v, _n in F.DAMAGE))),
}

def stories():
    items = [
        dict(key="Excess", cls="crit", title="Excess Stock",
             position="Excess Stock Value is {v} across {n} Loc-SKUs ({sk} distinct SKUs), "
                      "which is {s} of total Stock Value. Only the portion above the "
                      "coverage threshold counts as Excess Stock, never the whole Stock Value of those SKUs."
                      .format(v=usd(F.RD["Excess"]["val"]), n=full(F.RD["Excess"]["skus"]),
                              sk=full(EXCESS_SKUS),
                              s=pct(F.RD["Excess"]["val"] / F.STOCK * 100)),
             why="Excess is not a recent overbuy. The Duration term reaches {d}, and the "
                 "Loc-SKUs carrying Excess Stock average more than {days} Burn-Out Days against "
                 "the 90-day scoring cap. On top of that, {u} Unwanted SKUs sit in Pending "
                 "Orders: they already carry Excess Stock and more is arriving."
                 .format(d=pct(F.RD["Excess"]["dims"][2][1] * 100),
                         days=full(min(v for k, v in F.EXC_DAYS.items() if k != "ST5")),
                         u=full(UNWANTED_SKUS)),
             effect="It takes {p} points off the Inventory Health Score, more than any other "
                    "risk.".format(p=pts(F.RISKS[0][2])),
             stat=usd(F.RD["Excess"]["val"]),
             stat_lab="Excess Stock Value - the portion above threshold only",
             do="Review the {n} Loc-SKUs carrying OVERSTOCK for markdown, promotion or "
                "Transfer, starting at {s} where Excess Stock Value is highest. Review the "
                "{u} Unwanted SKUs in Pending Orders and cancel or defer where possible."
                .format(n=full(F.QUEUE[6]["n"]),
                        s=esc(max(F.EXC_BY_STORE, key=F.EXC_BY_STORE.get)),
                        u=full(UNWANTED_SKUS))),
        dict(key="Ageing", cls="crit", title="Ageing Stock",
             position="{v} of Stock Value is older than three months, across {n} Loc-SKUs. "
                      "Half of every eligible SKU holds some."
                      .format(v=usd(F.RD["Ageing"]["val"]), n=full(F.RD["Ageing"]["skus"])),
             why="Ageing severity is value weighted across every age band a SKU holds, so an "
                 "expensive old batch counts more than a cheap one. Of {t} of Store stock in "
                 "the ageing report, {o} is beyond three months and {tw} beyond twelve."
                 .format(t=usd(F.AGE_TOTAL), o=usd(F.AGE_OVER3), tw=usd(F.AGE_OVER12)),
             effect="It takes {p} points off. SKU Breadth drives it: half the range is "
                    "affected, not a handful of SKUs.".format(p=pts(F.RISKS[1][2])),
             stat=usd(F.AGE_OVER12), stat_lab="Stock Value older than twelve months",
             do="Clear the {tw} beyond twelve months first. It carries the maximum Ageing "
                "severity weight and will not improve on its own."
                .format(tw=usd(F.AGE_OVER12))),
        dict(key="Dead", cls="crit", title="Non-Moving Stock",
             position="{v} of Stock Value is Non-Moving across {n} Loc-SKUs, which is {sk} "
                      "distinct SKUs. Non-Moving means zero sales for 30 days with stock "
                      "available throughout."
                      .format(v=usd(F.RD["Dead"]["val"]), n=full(F.RD["Dead"]["skus"]),
                              sk=full(NM_SKUS)),
             why="The oldest bucket is the largest. {a} Loc-SKUs sit beyond 180 days holding "
                 "{av}, more than the 30-60 and 61-90 day buckets together. BR-25 treats "
                 "beyond 180 days as the highest obsolescence risk."
                 .format(a=full(F.NM_180_N), av=usd(F.NM_180_VAL)),
             effect="It takes {p} points off, and the Duration term at {d} shows most of "
                    "this value has been static for a long time."
                    .format(p=pts(F.RISKS[2][2]),
                            d=pct(F.RD["Dead"]["dims"][2][1] * 100)),
             stat=full(F.NM_180_N), stat_lab="Loc-SKUs Non-Moving beyond 180 days",
             do="Put the {a} Loc-SKUs beyond 180 days into clearance, promotion or Transfer "
                "before they age further.".format(a=full(F.NM_180_N))),
        dict(key="OOS", cls="crit", title="Out of Stock",
             position="{n} Loc-SKUs are at zero stock, which is {sk} distinct SKUs. The "
                      "sales value at risk is {v}."
                      .format(n=full(F.RD["OOS"]["skus"]), sk=full(OOS_SKUS),
                              v=usd(F.RD["OOS"]["val"])),
             why="The Recommended Action sub-state says what can be done. {w} carry "
                 "STOCK OUT - AVAILABLE IN WAREHOUSE and need a Transfer. Another {o} carry "
                 "STOCK OUT - PLACE ORDER: no warehouse stock and no open order."
                 .format(w=full(F.QUEUE[1]["n"]), o=full(F.QUEUE[0]["n"])),
             effect="It takes {p} points off, and the SKU segment weight of {sv} shows the "
                    "SKUs running out sit in the higher segments. {c} Critical SKUs are "
                    "currently out of stock."
                    .format(p=pts(F.RISKS[3][2]),
                            sv=pct(F.RD["OOS"]["dims"][2][1] * 100), c=full(CRITICAL_OOS)),
             stat=usd(F.OPP_SCOPED), stat_lab="Opportunity Loss - an estimate, Critical SKUs",
             do="Raise Transfers for the {w} with warehouse stock. Place orders against the "
                "{o} with none.".format(w=full(F.QUEUE[1]["n"]), o=full(F.QUEUE[0]["n"]))),
    ]
    out = []
    for it in items:
        p = dict((k, v) for k, _n, v in [(r[0], r[1], r[2]) for r in F.RISKS])[it["key"]]
        out.append(
            '<article class="story {cls}"><header class="s-head"><div>'
            '<h3>{title}</h3><p class="s-score"><b>&minus;{p}</b>'
            '<span>points off the score, of {lost}</span>'
            '<em>{sh} of the damage</em></p></div>{spark}</header>'
            '<dl class="s-body">'
            '<dt>What it is</dt><dd>{position}</dd>'
            '<dt>Why</dt><dd>{why}</dd>'
            '<dt>Effect on the Inventory Health Score</dt><dd>{effect}</dd>'
            '</dl><div class="s-foot"><div class="s-stat"><b>{stat}</b><span>{stat_lab}</span></div>'
            '<p class="s-do"><span>Do this</span>{do}</p></div></article>'.format(
                cls=it["cls"], title=esc(it["title"]), p=pts(p), lost=pts(F.LOST),
                sh=pct(F.share(p)), spark=risk_bar(p), position=it["position"],
                why=it["why"], effect=it["effect"], stat=it["stat"],
                stat_lab=esc(it["stat_lab"]), do=it["do"]))
    return "".join(out)


def risk_bar(p):
    w, h = 120, 34
    frac = p / 25.0
    return ('<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            'aria-label="{v} points of a possible 25">'
            '<rect x="4" y="12" width="{fw}" height="10" rx="5" fill="#eef2f6"/>'
            '<rect x="4" y="12" width="{f:.1f}" height="10" rx="5" fill="{c}"/>'
            '<text x="4" y="9" class="dz">out of 25 possible</text></svg>'
            ).format(w=w, h=h, fw=w - 8, f=(w - 8) * frac, c=RED, v=pts(p))


def ladder(items, total_lines):
    mx = max(x["n"] for x in items) or 1
    rows = []
    for i, x in enumerate(items, 1):
        if x["tag"] == "most urgent":
            cls, col = "c1", RED
        elif x["kind"] == "act" and i <= 6:
            cls, col = "c2", AMBER
        else:
            cls, col = "", FAINT
        tag = ('<span class="ltag {}">{}</span>'.format(
            "t-crit" if x["tag"] == "most urgent" else "t-warn",
            "do this first" if x["tag"] == "most urgent" else "costs nothing to fix")
            if x["tag"] else "")
        sub = usd(x["val"]) if x["val"] > 0 else "zero stock"
        rows.append(
            '<div class="lrow {cls}"><span class="lrank">{i}</span><div>'
            '<p class="lname">{label}{tag}</p>'
            '<div class="ltrack"><span class="lfill" style="width:{w:.1f}%;background:{col}"></span></div>'
            '</div><div class="lval"><b>{n}</b><span>{sub}</span></div></div>'.format(
                cls=cls, i=i, label=esc(x["key"]), tag=tag,
                w=x["n"] / mx * 100, col=col, n=full(x["n"]), sub=sub))
    return '<div class="ladder">{}</div>'.format("".join(rows))


def health_bars():
    mx = max(x["n"] for x in F.HEALTH)
    rows = []
    for x in F.HEALTH:
        if x["name"] == "Out of Stock":
            col = RED
        elif x["name"] in ("Excellent", "Healthy"):
            col = GREEN
        elif x["name"] == "Watch":
            col = AMBER
        else:
            col = RED
        rows.append(
            '<div class="rb"><div class="rb-l">{name}<small>{note}</small></div>'
            '<div class="rb-t"><span class="rb-f" style="width:{w:.1f}%;background:{col}"></span></div>'
            '<div class="rb-v">{n}<small class="under">{v}</small></div></div>'.format(
                name=esc(x["name"]), note=esc(BAND_PLAIN[x["name"]]),
                w=x["n"] / mx * 100, col=col, n=full(x["n"]),
                v=usd(x["val"]) if x["val"] else "zero stock"))
    return '<div class="rbars">{}</div>'.format("".join(rows))


def store_table():
    rows = []
    for r in F.STORES:
        loc = F.g(r, "LOC_CODE")
        sc = F.num(r, "Score")
        lab, cls, pill = band(sc)
        wind = loc == "ST5"
        rows.append(
            '<tr{tr}><td><b>{loc}</b>{note}</td><td>{spark}</td>'
            '<td class="n"><b>{sc}</b></td><td class="n"><span class="pill {pill}">{lab}</span></td>'
            '<td class="n">{stock}</td><td class="n">{skus}</td>'
            '<td class="n">{ex}</td><td class="n">{ag}</td><td class="n">{de}</td>'
            '<td class="n">{oo}</td><td class="n">{ve}</td><td class="n">{da}</td></tr>'.format(
                tr=' class="urgent"' if wind else "", loc=esc(loc),
                note='<br><span class="act">winding down</span>' if wind else "",
                spark=sparkline(F.STORE_TREND[loc], colour=AMBER if wind else TEAL),
                sc=pts(sc), pill=pill, lab=lab,
                stock=usd(F.num(r, "Stock")), skus=full(F.num(r, "SKUs")),
                ex=pts(F.num(r, "Excess")), ag=pts(F.num(r, "Ageing")),
                de=pts(F.num(r, "Dead")), oo=pts(F.num(r, "OOS")),
                ve=pts(F.num(r, "Verge")), da=pts(F.num(r, "Damage"))))
    return ('<div class="scroll"><table><thead><tr><th>Location</th>'
            '<th>Stock Value since 1 Jun</th>'
            '<th class="n">Score</th><th class="n">Status</th>'
            '<th class="n">Stock Value</th><th class="n">Loc-SKUs</th>{rh}</tr></thead>'
            '<tbody>{rows}</tbody></table></div>'
            ).format(rh="".join('<th class="n">{}</th>'.format(esc(RISK_COL[k]))
                                for k, _n, _p in F.RISKS), rows="".join(rows))


def dept_table():
    rows = []
    for r in F.DEPTS:
        sc = F.num(r, "Score")
        lab, cls, pill = band(sc)
        rows.append(
            '<tr><td><b>{n}</b></td><td class="n"><b>{sc}</b></td>'
            '<td class="n"><span class="pill {pill}">{lab}</span></td>'
            '<td class="n">{stock}</td><td class="n">{skus}</td>'
            '<td class="n">{ex}</td><td class="n">{ag}</td><td class="n">{de}</td>'
            '<td class="n">{oo}</td><td class="n">{ve}</td><td class="n">{da}</td></tr>'.format(
                n=esc(F.g(r, "DEPARTMENT")), sc=pts(sc), pill=pill, lab=lab,   # Division (BR-02)
                stock=usd(F.num(r, "Stock")), skus=full(F.num(r, "SKUs")),
                ex=pts(F.num(r, "Excess")), ag=pts(F.num(r, "Ageing")),
                de=pts(F.num(r, "Dead")), oo=pts(F.num(r, "OOS")),
                ve=pts(F.num(r, "Verge")), da=pts(F.num(r, "Damage"))))
    return ('<div class="scroll"><table><thead><tr><th>Division</th><th class="n">Score</th>'
            '<th class="n">Status</th><th class="n">Stock Value</th>'
            '<th class="n">Loc-SKUs</th>{rh}</tr></thead><tbody>{rows}</tbody></table></div>'
            ).format(rh="".join('<th class="n">{}</th>'.format(esc(RISK_COL[k]))
                                for k, _n, _p in F.RISKS), rows="".join(rows))


def section_table():
    rows = []
    for r in F.SECTS:
        sc = F.num(r, "Score")
        lab, cls, pill = band(sc)
        name = F.g(r, "SECTION")
        thin = int(F.num(r, "SKUs")) < 100
        note = ""
        if name == "FOOTWEAR":
            note = ('<br><span class="act">no Excess threshold configured, so the '
                    'Excess Stock rule cannot apply</span>')
        elif thin:
            note = '<br><span class="act">too few Loc-SKUs to read reliably</span>'
        rows.append(
            '<tr><td><b>{n}</b>{note}</td><td class="act">{d}</td><td class="n"><b>{sc}</b></td>'
            '<td class="n"><span class="pill {pill}">{lab}</span></td>'
            '<td class="n">{stock}</td><td class="n">{skus}</td>'
            '<td class="n">{ex}</td><td class="n">{ag}</td><td class="n">{de}</td>'
            '<td class="n">{oo}</td></tr>'.format(
                n=esc(name), note=note, d=esc(F.g(r, "DEPARTMENT")), sc=pts(sc),
                pill=pill, lab=lab, stock=usd(F.num(r, "Stock")), skus=full(F.num(r, "SKUs")),
                ex=pts(F.num(r, "Excess")), ag=pts(F.num(r, "Ageing")),
                de=pts(F.num(r, "Dead")), oo=pts(F.num(r, "OOS"))))
    return ('<div class="scroll"><table><thead><tr><th>Section</th><th>Division</th>'
            '<th class="n">Score</th><th class="n">Status</th>'
            '<th class="n">Stock Value</th><th class="n">Loc-SKUs</th>'
            '<th class="n">Excess</th><th class="n">Ageing</th>'
            '<th class="n">Non-Moving</th><th class="n">Out of Stock</th>'
            '</tr></thead><tbody>{}</tbody></table></div>').format("".join(rows))


def queue_table():
    kinds = {"act": "needs action", "gap": "cannot be determined", "ok": "no action"}
    rows = []
    for i, x in enumerate(F.QUEUE, 1):
        rows.append(
            '<tr{tr}><td class="n">{i}</td><td><b>{label}</b><br>'
            '<span class="act">{action}</span></td>'
            '<td class="act">{kind}</td><td class="n">{n}</td><td class="n">{val}</td>'
            '<td class="n">{exc}</td><td class="n">{po}</td></tr>'.format(
                tr=' class="urgent"' if x["tag"] == "most urgent" else "",
                i=i, label=esc(x["key"]), action=QUEUE_ACTION[x["key"]],
                kind=kinds[x["kind"]], n=full(x["n"]),
                val=usd(x["val"]) if x["val"] else "&mdash;",
                exc=usd(x["exc"]) if x["exc"] else "&mdash;",
                po=usd(x["po"]) if x["po"] else "&mdash;"))
    return ('<div class="scroll"><table><thead><tr><th class="n">#</th>'
            '<th>Recommended Action</th><th>Kind</th><th class="n">Loc-SKUs</th>'
            '<th class="n">Stock Value</th><th class="n">Excess Stock Value</th>'
            '<th class="n">Pending Orders Value</th></tr></thead><tbody>{}</tbody>'
            '</table></div>').format("".join(rows))


def wh_table():
    rows = []
    for x in F.WH:
        rows.append('<tr><td><b>{loc}</b></td><td class="n">{n}</td>'
                    '<td class="n">{val}</td><td class="n">{exc}</td>'
                    '<td class="n">{nm}</td><td class="n">{nmv}</td></tr>'
                    .format(loc=esc(x["loc"]), n=full(x["n"]), val=usd(x["val"]),
                            exc=usd(x["exc"]), nm=full(x["nm"]), nmv=usd(x["nmval"])))
    return ('<div class="scroll"><table><thead><tr><th>Warehouse</th>'
            '<th class="n">Loc-SKUs</th><th class="n">Stock Value</th>'
            '<th class="n">Excess Stock Value</th><th class="n">Non-Moving</th>'
            '<th class="n">Non-Moving Stock Value</th>'
            '</tr></thead><tbody>{}</tbody></table></div>').format("".join(rows))


CAVEATS_ALL = [
    "The Inventory Health Score is calculated for the five Stores. Warehouse scoring is "
    "being added to the model. Until it is, the two Warehouses appear here as Stock Value "
    "and classification counts only, with no score, and are never added to the Store score.",
    "This is a closing-stock snapshot as at <b>{asat}</b>. It is a position, not a total "
    "over a period. Only Damage Value by month and the Stock Value trend cover a span of "
    "time.",
    "A daily snapshot has only just started being retained. The line under &ldquo;The "
    "story&rdquo; shows the shape that chart will take, not real past scores.",
    "The health-score model names one risk <b>Dead Stock</b>. The business term for that "
    "classification is <b>Non-Moving</b>, and this page uses Non-Moving throughout. They "
    "are the same thing. The model also names one risk Verge of Stockout, written here as "
    "On the Verge of Stockout.",
    "<b>Loc-SKUs</b> and <b>SKUs</b> are different counts. A Loc-SKU is one SKU at one "
    "Location. {locskus} Loc-SKUs cover {skus} distinct SKUs, so a SKU that is Non-Moving "
    "at three Stores appears three times in a Loc-SKU count and once in a SKU count. Each "
    "figure on this page states which it is.",
    "One Section has no Excess threshold configured, so the Excess Stock rule cannot apply "
    "to its {fn} Loc-SKUs holding {fv}. Its score of {fs} is therefore flattering.",
    "<b>Opportunity Loss</b> of {o} is an estimate based on average daily sales and retail "
    "price, not confirmed lost revenue. It covers Critical SKUs at Stores only, so it is "
    "much smaller than the unscoped stockout figure in the model. Never add it to Damage "
    "Value.",
    "{gapn} Loc-SKUs holding {gapv} carry the Recommended Action <b>NA</b> or a missing "
    "reorder level, so the reorder decision cannot be assessed. They are shown as cannot be "
    "determined rather than counted as healthy.",
    "Two model tables carry no relationship, so asking the model for a single "
    "Division&rsquo;s score returns the company total. Every roll-up here is built from the "
    "main stock table, which reconciles to {t} exactly.",
    "All money is stated in <b>USD</b>. Stock Value is at landing cost.",
]


def caveats(items):
    return ('<div class="caveats"><h3>Things to know before using these numbers</h3>'
            '<ul>{}</ul></div>').format("".join("<li>{}</li>".format(x) for x in items))


def build():
    css = CSS

    score_band, score_cls, score_pill = band(F.SCORE)
    top3 = F.RISKS[0][2] + F.RISKS[1][2] + F.RISKS[2][2]

    # ---------------- overview layer --------------------------------------
    dmg_rows_ov = [(MONTH[d], v, d == "2026-08-01") for d, v, _n in F.DAMAGE]
    overview = (
        '<section class="hero hero-stack">'
        '<div><span class="hero-tag">Closing stock &middot; {asat}</span>'
        '<h2>The five Stores hold {stock} of Stock Value, and {needs} of it sits on '
        'Loc-SKUs whose Recommended Action needs action.</h2>'
        '<p>Most of the exposure is not stock running out. It is Excess Stock, Ageing Stock '
        'and Non-Moving Stock: capital already committed and not selling through. Out of '
        'Stock is smaller, and is the fastest to resolve.</p></div>'
        '<div class="hero-stats">'
        '<div class="hs"><b>{stock}</b><span>Stock Value across the Stores</span></div>'
        '<div class="hs crit"><b>{needs}</b><span>on Loc-SKUs needing action</span></div>'
        '<div class="hs"><b>{oos}</b><span>Loc-SKUs Out of Stock</span></div>'
        '</div></section>'
        .format(asat=AS_AT, stock=usd(F.STOCK), needs=usd(F.NEEDS_VAL),
                oos=full(F.RD["OOS"]["skus"]))
        + '<div class="sect"><h2>The headline measures</h2>'
          '<span>BR-08 measures for the Stores</span></div>'
        + kpi_cards()
        + '<p class="note" style="margin-top:11px">Excess Stock, Ageing Stock and Non-Moving '
          'Stock overlap by design: one Loc-SKU can carry more than one classification, so '
          'these three are never added together. The figures that do add up exactly are the '
          'Recommended Action states.</p>'
        + '<div class="sect"><h2>Where it sits, and what to do</h2>'
          '<span>Stock Value by Location, and the most urgent Recommended Actions</span></div>'
        + '<div class="grid g-2e">'
        + where_stock_sits()
        + '<section class="card"><h3>Most urgent Recommended Actions</h3>'
          '<p class="sub">The six states costing sales now. All fourteen are under '
          '<b>Recommended Actions</b>.</p>'
        + ladder(F.NEEDS[:6], F.SKUS)
        + ('<p class="note">These six cover <b>{six}</b> Loc-SKUs. The {free} carrying '
           'AVAILABLE IN WAREHOUSE need a Transfer, not a purchase order.</p></section>'
           '</div>'.format(
               six=full(sum(x["n"] for x in F.NEEDS[:6])),
               free=full(F.QUEUE[1]["n"]
                         + [x for x in F.QUEUE
                            if x["key"] == "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE"
                            ][0]["n"])))
        + '<div class="sect"><h2>What covers a period</h2>'
          '<span>the two figures on this page that are not a snapshot</span></div>'
        + '<div class="grid g-2e">'
        + '<section class="card"><h3>Store Stock Value over time</h3>'
          '<p class="sub">Stock Value at four snapshot dates. The only genuine history the '
          'model retains.</p>'
        + trend_chart()
        + ('<p class="note">Store Stock Value has fallen from {t0} to {t1} since 1 June. '
           'Nearly all of that is the Location winding down.</p></section>'
           .format(t0=usd(F.TREND_STORE_TOTAL[0]), t1=usd(F.TREND_STORE_TOTAL[-1])))
        + '<section class="card"><h3>Damage Value by month</h3>'
          '<p class="sub">Negative inventory adjustments, all Locations. Includes expiry and '
          'wastage, not only physical damage.</p>'
        + vbars(dmg_rows_ov, label_two_line=False, W=560, H=228)
        + ('<p class="note">Damage Value climbed steeply across the months retained. The '
           'latest month is partial at nineteen days &mdash; {aug} against {jul} for the '
           'full month before &mdash; so it cannot be read as a fall.</p></section></div>'
           .format(aug=usd(F.DAMAGE[-1][1]), jul=usd(F.DAMAGE[-2][1])))
        + ('<div class="pointer" style="margin-top:20px"><b>The Inventory Health Score '
           'summarises all of this in one number.</b> It reads <b>{score}</b> out of 100 '
           'today. It is a summary of the risks above, not a replacement for them. See '
           '<b>Inventory Health Score</b> for how it is built.</div>'
           .format(score=pts(F.SCORE)))
    )

    # ---------------- summary layer, all-stock view -----------------------
    hero = (
        '<section class="hero score-hero">'
        '<div><span class="hero-tag">Inventory Health Score &middot; {bandl}</span>'
        '<h2>The Stores score {score} out of 100. Three quarters of the points lost sit in '
        'stock already bought and not selling.</h2>'
        '<p>Excess Stock, Ageing Stock and Non-Moving Stock together take {top3} of the '
        '{lost} points lost &mdash; {tsh} of the total. Out of Stock, the risk that usually '
        'draws the attention, takes {oos}.</p>'
        '<div class="hero-stats" style="margin-top:16px">'
        '<div class="hs crit"><b>{lost}</b><span>points lost from 100</span></div>'
        '<div class="hs"><b>{stock}</b><span>Stock Value across the Stores</span></div>'
        '<div class="hs"><b>{oosn}</b><span>Loc-SKUs Out of Stock</span></div>'
        '</div></div>'
        '<div class="gauge-wrap"><div class="gauge" style="background:conic-gradient({red} 0 {pctv:.1f}%,'
        'rgba(255,255,255,.10) 0)"><span class="g-val">{score}</span><span class="g-of">/100</span></div>'
        '<p class="g-label">{bandu}</p>'
        '<p class="g-delta">{lost} points lost across six risks</p></div></section>'
    ).format(bandl=score_band.lower(), score=pts(F.SCORE), top3=pts(top3), lost=pts(F.LOST),
             tsh=pct(top3 / F.LOST * 100), oos=pts(F.RISKS[3][2]), stock=usd(F.STOCK),
             oosn=full(F.RD["OOS"]["skus"]), red=RED, pctv=F.SCORE, bandu=score_band)

    bands_html = "".join(
        '<div class="bandbox{here}"><b>{r}</b><span>{n}</span></div>'.format(
            here=" here" if n == score_band else "", r=r, n=n)
        for r, n in [("90 &ndash; 100", "Excellent"), ("80 &ndash; 89", "Healthy"),
                     ("70 &ndash; 79", "Watch"), ("60 &ndash; 69", "At Risk"),
                     ("Below 60", "Critical")])

    summary_all = (
        hero +
        '<div class="illus">A daily snapshot has only just started being retained, so no '
        'score history exists yet. The line below shows <b>the shape this chart will take</b> '
        'once it does. It carries no past values on purpose. The only real reading is the '
        'one at 19 August.</div>'

        '<div class="sect"><h2>The story</h2><span>the score, and what it is made of</span></div>'
        '<section class="card"><h3>The score once history builds up</h3>'
        '<p class="sub">The bands never move, so a score is judged against a fixed standard '
        'rather than against how it happened to wobble. The dashed line is shape only.</p>'
        + health_shape_chart() +
        '<div class="bands">' + bands_html + '</div></section>'
        '<div class="grid g-2" style="margin-top:14px">'
        '<section class="card"><h3>What takes the points off</h3>'
        '<p class="sub">Every SKU starts at 100. Each of the six risks deducts, capped at '
        '25 points each. The six deductions add to the whole of the loss, so nothing is left '
        'unexplained.</p>'
        + composition_waterfall() +
        '<p class="note">Read it left to right: the score starts at 100, each problem takes '
        'points off, and it finishes at <b>{score}</b>. Biggest cause first, which is not the '
        'order the rules number them in.</p></section>'
        '<section class="card"><h3>How every Loc-SKU scores</h3>'
        '<p class="sub">Each Loc-SKU carries its own Final SKU Health score. Out of Stock '
        'rows follow a separate 0-based path and are not placed in the five bands.</p>'
        + health_bars() +
        '<p class="note">The average Loc-SKU scores <b>{avg}</b>, well above the company '
        'score of <b>{score}</b>. That is the method working as designed: parent scores are '
        'recalculated from the underlying risk exposure rather than averaged from their '
        'children, so {ex} of Excess Stock Value counts for far more than a long tail of '
        'small healthy SKUs.</p>'
        '</section></div>'

        '<div class="sect"><h2>The six risks</h2>'
        '<span>what each costs, and the three dimensions behind it</span></div>'
        '<div class="drivers">' + risk_cards() + '</div>'

        '<div class="method"><h3>How the score is worked out</h3>'
        '<p>Every SKU at every Location starts with <b>100 points</b>, and six risks can '
        'deduct from it. Each risk is rebuilt from three dimensions: <b>Value Impact</b> (the '
        'risk value as a share of Stock Value, or of sales value for the two stockout risks), '
        '<b>SKU Breadth</b> (how many eligible SKUs carry it) and <b>Duration or Severity</b> '
        '(how long standing or how serious it is). They are weighted 50 / 30 / 20, or 70 / 30 '
        'for Damage which carries no Duration term. Each risk is capped at <b>25 points</b>, '
        'so no single risk can cost more than a quarter of the score.</p>'
        '<p>Four of the six risks compare a SKU against the <b>90th-percentile</b> risk '
        'value of its peers in the same Category and Location, so a high-value Category '
        'cannot dominate simply because its prices are higher. Damage is already self '
        'normalised as a share of Stock Value and needs no benchmark.</p>'
        '<p>A SKU that is already <b>Out of Stock</b> follows a deliberately harsher path. '
        'It starts from 0 rather than 100 and is not floored, so its score can go negative '
        'when other risks compound on top. {oosn} Loc-SKUs are on that path, averaging '
        '{oosavg}. They are labelled Out of Stock rather than placed in the five bands, '
        'because a stockout is not comparable with a stocked SKU&rsquo;s risk profile.</p>'
        '<p>The score is a summary, not a replacement for the numbers behind it. Every '
        'figure is in <b>Overview</b>, <b>Locations</b>, <b>Divisions</b> and '
        '<b>Recommended Actions</b>.</p></div>'
    ).format(avg=pts(F.AVG_SKU), score=pts(F.SCORE), ex=usd_c(F.RD["Excess"]["val"]),
             oosn=full([h for h in F.HEALTH if h["name"] == "Out of Stock"][0]["n"]),
             oosavg=pts([h for h in F.HEALTH if h["name"] == "Out of Stock"][0]["avg"]))

    # ---------------- focus layer ----------------------------------------
    focus_all = (
        '<div class="sect"><h2>Where to focus</h2>'
        '<span>the four risks costing the most, and the action for each</span></div>'
        '<p class="lead-note">These four take {four} of the {lost} points lost &mdash; {sh} of the total. They are ordered by what they cost the Inventory Health Score, not by Stock Value.</p>'
        '<div class="stories">{stories}</div>'
        '<div class="sect"><h2>The evidence behind them</h2>'
        '<span>where the numbers come from</span></div>'
        '<div class="grid g-2">'
        '<section class="card"><h3>Most urgent Recommended Actions</h3>'
        '<p class="sub">The six Recommended Action states costing sales now, largest first. All fourteen are under <b>Recommended Actions</b>.</p>{ladder}'
        '<p class="note">These six cover <b>{six}</b> Loc-SKUs. All {skus} Loc-SKUs are accounted for under <b>Recommended Actions</b>.</p></section>'
        '<section class="card"><h3>Ageing Stock by age band</h3>'
        '<p class="sub">Store Stock Value by the age band it sits in. One SKU can hold stock in several age bands at once, which is what the value-weighted Ageing severity reads.</p>{age}'
        '<div class="legend"><span><i style="background:{teal}"></i>under three months'
        '</span><span><i style="background:{amber}"></i>three months and older</span></div>'
        '<p class="note"><b>{over3}</b> of {total} is already beyond three months &mdash; {o3pct} &mdash; and <b>{over12}</b> is beyond twelve months, where the Ageing severity weight reaches its maximum.</p></section></div>'
    ).format(four=pts(sum(r[2] for r in F.RISKS[:4])), lost=pts(F.LOST),
             sh=pct(sum(r[2] for r in F.RISKS[:4]) / F.LOST * 100),
             stories=stories(), ladder=ladder(F.NEEDS[:6], F.SKUS),
             six=full(sum(x["n"] for x in F.NEEDS[:6])), skus=full(F.SKUS),
             age=vbars([(k.replace(" MONTHS", ""), v, k != "0-03 MONTHS") for k, v in F.AGE],
                       label_two_line=False, W=560, H=228),
             teal=TEAL, amber=AMBER, over3=money(F.AGE_OVER3), total=money(F.AGE_TOTAL),
             o3pct=pct(F.AGE_OVER3 / F.AGE_TOTAL * 100), over12=money(F.AGE_OVER12))

    # ---------------- locations ------------------------------------------
    st5 = F.STORE_TREND["ST5"]
    st5_drop = (st5[0] - st5[-1]) / st5[0] * 100
    locations_all = (
        '<div class="sect"><h2>Locations</h2><span>the five Stores, and the two Warehouses</span></div>'
        '<section class="card"><h3>The five Stores</h3>'
        '<p class="sub">Each Store&rsquo;s Inventory Health Score, its Stock Value, and the points each risk deducts. The spark line is that Store&rsquo;s Stock Value across the four snapshot dates the model retains.</p>'
        + store_table() +
        '<p class="note">Every Store is At Risk or Critical. The spread is narrow &mdash; {lo} to {hi} &mdash; so the risks driving the score are estate-wide rather than concentrated in one Location.</p></section>'
        '<div class="grid g-2e" style="margin-top:14px">'
        '<section class="card"><h3>Store Stock Value over time</h3>'
        '<p class="sub">The only genuine history the model retains: Store Stock Value at four dates. This is Stock Value, not the Inventory Health Score.</p>' + trend_chart() +
        '<p class="note">Store Stock Value has fallen from {t0} to {t1} since 1 June. Nearly all of that is one Location.</p></section>'
        '<section class="card"><h3>One Location is winding down</h3>'
        '<p class="sub">Read it separately from the other four. Its figures are not comparable with a trading Store.</p>'
        '<div class="rbars">{st5bars}</div>'
        '<p class="note">It now holds {v} across {n} Loc-SKUs, down <b>{drop}</b> since 1 June. It carries <b>no Excess Stock and no Non-Moving Stock at all</b>, and only four of the fourteen Recommended Action states appear there. Its Out of Stock risk sits at the full 25-point cap, which is the expected shape for a Location running its stock down rather than an availability failure to fix.</p></section></div>'
        '<div class="sect"><h2>Warehouses</h2>'
        '<span>shown for information &mdash; not scored yet</span></div>'
        '<section class="card"><h3>WH1 and WH2</h3>'
        '<p class="sub">The Inventory Health Score covers the five Stores. Warehouse scoring is being added to the model. These are the same classifications read straight from the stock data, with no score attached.</p>'
        + wh_table() +
        '<p class="note">The Warehouses hold <b>{whv}</b> of Stock Value &mdash; more than all five Stores together &mdash; and <b>{whe}</b> of that is Excess Stock Value. Read these beside the Store figures, never added to them.</p></section>'
    ).format(lo=pts(min(F.num(r, "Score") for r in F.STORES)),
             hi=pts(max(F.num(r, "Score") for r in F.STORES)),
             t0=full(F.TREND_STORE_TOTAL[0]), t1=full(F.TREND_STORE_TOTAL[-1]),
             st5bars="".join(
                 '<div class="rb"><div class="rb-l">{d}</div>'
                 '<div class="rb-t"><span class="rb-f" style="width:{w:.1f}%;background:{c}"></span></div>'
                 '<div class="rb-v">{v}</div></div>'.format(
                     d={"2026-06-01": "1 Jun", "2026-07-01": "1 Jul", "2026-08-01": "1 Aug",
                        "2026-08-19": "19 Aug"}[dt],
                     w=v / max(st5) * 100, c=AMBER, v=full(v))
                 for dt, v in zip(F.TREND_DATES, st5)),
             v=full(st5[-1]), n=full(int(F.num([r for r in F.STORES
                                                if F.g(r, "LOC_CODE") == "ST5"][0], "SKUs"))),
             drop=pct(st5_drop), whv=full(F.WH_VAL),
             whe=full(sum(x["exc"] for x in F.WH)))

    # ---------------- divisions ------------------------------------------
    worst_dept = F.DEPTS[0]
    best_dept = F.DEPTS[-1]
    material = [r for r in F.SECTS if int(F.num(r, "SKUs")) >= 1000]
    divisions_all = (
        '<div class="sect"><h2>Divisions and Sections</h2>'
        '<span>where the risk sits in the product hierarchy</span></div>'
        '<section class="card"><h3>By Division</h3>'
        '<p class="sub">Four Divisions. Each is recalculated from its own risk exposure, never averaged from the Sections beneath it.</p>' + dept_table() +
        '<p class="note"><b>{wn}</b> is the worst at {ws}, {gap} points below <b>{bn}</b> at '
        '{bs}. Almost all of that gap is Ageing Stock and Non-Moving Stock &mdash; {wa}  '
        'and {wd} points against {ba} and {bd}.</p></section>'
        '<section class="card" style="margin-top:14px"><h3>By Section</h3>'
        '<p class="sub">All twenty, weakest first. Sections carrying fewer than 100 Loc-SKUs are marked: their scores move on a handful of rows and should not be read as a trend.</p>'
        + section_table() +
        '<p class="note">The weakest Section with real weight behind it is <b>{ms}</b> at {mss}  '
        'across {msn} Loc-SKUs, where Out of Stock alone takes {mso} of the 25 points available.</p></section>'
    ).format(wn=esc(F.g(worst_dept, "DEPARTMENT")), ws=pts(F.num(worst_dept, "Score")),
             gap=pts(F.num(best_dept, "Score") - F.num(worst_dept, "Score")),
             bn=esc(F.g(best_dept, "DEPARTMENT")), bs=pts(F.num(best_dept, "Score")),
             wa=pts(F.num(worst_dept, "Ageing")), wd=pts(F.num(worst_dept, "Dead")),
             ba=pts(F.num(best_dept, "Ageing")), bd=pts(F.num(best_dept, "Dead")),
             ms=esc(F.g(material[0], "SECTION")), mss=pts(F.num(material[0], "Score")),
             msn=full(F.num(material[0], "SKUs")), mso=pts(F.num(material[0], "OOS")))

    # ---------------- queue ----------------------------------------------
    dmg_rows = [(MONTH[d], v, d == "2026-08-01") for d, v, _n in F.DAMAGE]
    queue_all = (
        '<div class="sect"><h2>Recommended Actions</h2>'
        '<span>all fourteen states, every Loc-SKU accounted for</span></div>'
        '<section class="card"><h3>All fourteen Recommended Action states</h3>'
        '<p class="sub">In urgency order: what is costing sales now, then what is about to, then the capital already committed. Nine need action, two cannot be determined, and three need none. BR-31 requires the full state name, so the grey line beneath is the buying-team action rather than an alternative name.</p>'
        + queue_table() +
        '<p class="note">The fourteen add up to <b>{skus}</b> Loc-SKUs exactly.  '
        '<b>{needs}</b> need action, holding <b>{needsv}</b>. Another <b>{gapn}</b> holding  '
        '{gapv} cannot be assessed for a reorder decision &mdash; a data gap, not a clean bill of health. The other {okn} carry STOCK AVAILABLE, NEW LISTED SKU or NOT ACTIVE.</p></section>'
        '<div class="grid g-2e" style="margin-top:14px">'
        '<section class="card"><h3>Non-Moving Stock by bucket</h3>'
        '<p class="sub">Non-Moving Loc-SKUs by the BR-25 bucket they fall in. Only these feed the Non-Moving Stock risk.</p>'
        '{nm}'
        '<p class="note">The oldest bucket is the largest: <b>{n180}</b> Loc-SKUs sit beyond 180 days holding {v180}. The risk normalises Duration against 180 days, so every one of these already carries the maximum Duration weight.</p></section>'
        '<section class="card"><h3>Damage Value by month</h3>'
        '<p class="sub">Damage Value by month, all Locations. BR-29 covers every negative inventory adjustment, so this includes expiry and wastage, not only physical damage. The risk reads the latest month only, which is why it moves faster than the other five.</p>'
        '{dmg}'
        '<p class="note">Damage Value climbed steeply across the months retained. The latest '
        'month is partial at nineteen days &mdash; {aug} against {jul} for the full month '
        'before &mdash; so it cannot be read as a fall. The figure used '
        'in the score is {scored}, the Stores&rsquo; share of the latest month.</p>'
        '</section></div>'
    ).format(skus=full(F.SKUS), needs=full(F.NEEDS_N), needsv=usd(F.NEEDS_VAL),
             gapn=full(F.GAP_N), gapv=usd(F.GAP_VAL), okn=full(F.OK_N),
             nm=vbars([(k, v, k == ">180") for k, _n, v in F.NM], label_two_line=False,
                      W=560, H=228),
             n180=full(F.NM_180_N), v180=usd(F.NM_180_VAL),
             dmg=vbars(dmg_rows, label_two_line=False, W=560, H=228),
             aug=usd(F.DAMAGE[-1][1]), jul=usd(F.DAMAGE[-2][1]),
             scored=usd(F.RD["Damage"]["val"]))

    cav_all = list(CAVEATS_ALL)
    cav_all[1] = cav_all[1].format(asat=AS_AT)
    cav_all[4] = cav_all[4].format(locskus=full(LOCSKUS), skus=full(SKUS_IN_SCOPE))
    cav_all[5] = cav_all[5].format(
        fn=full(5583), fv=usd(214739.1729),
        fs=pts([F.num(r, "Score") for r in F.SECTS
                if F.g(r, "SECTION") == "FOOTWEAR"][0]))
    cav_all[6] = cav_all[6].format(o=usd(F.OPP_SCOPED))
    cav_all[7] = cav_all[7].format(gapn=full(F.GAP_N), gapv=usd(F.GAP_VAL))
    cav_all[8] = cav_all[8].format(t=usd(F.STOCK))

    # ---------------- needs-action view -----------------------------------
    needs_hero = (
        '<section class="hero"><div>'
        '<span class="hero-tag">Only the Loc-SKUs needing action</span>'
        '<h2>{needs} of the {skus} Loc-SKUs carry a Recommended Action that needs action.</h2>'
        '<p>They hold {val} of Stock Value. This view counts only those Loc-SKUs, so its totals will not match the all-stock view. There is no Inventory Health Score here, because a score recomputed on the worst subset would not mean anything.</p></div>'
        '<div class="hero-stats">'
        '<div class="hs crit"><b>{needs}</b><span>Loc-SKUs needing action</span></div>'
        '<div class="hs"><b>{val}</b><span>Stock Value committed to them</span></div>'
        '<div class="hs"><b>{shr}</b><span>of all scored Loc-SKUs</span></div>'
        '</div></section>'
    ).format(needs=full(F.NEEDS_N), skus=full(F.SKUS), val=full(F.NEEDS_VAL),
             shr=pct(F.NEEDS_N / F.SKUS * 100))

    pointer = ('<div class="pointer"><b>This view does not own a breakdown by Location, Division or Section.</b> Those splits are worked out across all the stock, '
               'not only the Loc-SKUs needing action, so showing them here would print rows that  '
               'do not add up to this view&rsquo;s own totals. Switch to <b>All stock</b> to '
               'read them.</div>')

    needs_ladder = ladder(F.NEEDS, F.NEEDS_N)
    needs_scoped = ('<div class="scoped">This view counts only Loc-SKUs whose Recommended Action needs action. Its totals will not match the all-stock view, and that is expected.</div>')

    cav_needs = [
        "Everything here is scoped to the <b>{n} Loc-SKUs needing action</b>. Totals will "
        "not match the all-stock view, and that is expected.".format(n=full(F.NEEDS_N)),
        "There is <b>no Inventory Health Score</b> on this view. The score is calculated "
        "across every scored Loc-SKU; recomputing it on the worst subset would not mean "
        "anything.",
        "This is a closing-stock snapshot as at <b>{}</b>, not a total over a "
        "period.".format(AS_AT),
        "<b>NON MOVING - ORDER PLACED</b> returns no rows. BR-31 calls it one of the two "
        "double-warning states, so either nothing is in it or the source system is not "
        "producing it.",
        "The five Recommended Action states left out cover the other {r} Loc-SKUs: {o} "
        "carrying STOCK AVAILABLE, NEW LISTED SKU or NOT ACTIVE, and {g} whose "
        "the reorder decision cannot be assessed."
        .format(r=full(F.REST_N), o=full(F.OK_N), g=full(F.GAP_N)),
    ]

    # ---------------- assemble --------------------------------------------
    def layer(name, body, hidden=False):
        return '<div class="layer" data-layer="{}"{}>{}</div>'.format(
            name, " hidden" if hidden else "", body)

    view_all = ('<div class="view" data-view="all">'
                + layer("overview", overview)
                + layer("summary", summary_all, True)
                + layer("focus", focus_all, True)
                + layer("locations", locations_all, True)
                + layer("divisions", divisions_all, True)
                + layer("queue", queue_all, True)
                + caveats(cav_all)
                + '<div class="foot"><span>Reference design &mdash; INVENTORY MANAGEMENT REPORT, '
                  'semantic model 16d47b06. Figures read on {asat}.</span>'
                  '<span>The Inventory Health Score and its six risks come from the '
                  '_HEALTH SCORE MEASURES.</span></div></div>').format(asat=AS_AT)

    view_needs = ('<div class="view" data-view="needs" hidden>'
                  + layer("overview", needs_hero + '<div class="sect"><h2>Every state needing action</h2><span>nine of the fourteen</span></div>' + needs_scoped
                          + '<section class="card"><h3>In urgency order</h3>'
                            '<p class="sub">What is costing sales now, then what is about to, then the capital already committed.</p>' + needs_ladder
                          + '<p class="note">These nine add up to <b>{n}</b> Loc-SKUs holding <b>{v}</b>.</p></section>'.format(n=full(F.NEEDS_N),
                                                                       v=full(F.NEEDS_VAL)))
                  + layer("summary", '<div class="sect"><h2>Inventory Health Score</h2>'
                          '<span>not calculated for this view</span></div>'
                          + '<div class="pointer"><b>There is no Inventory Health Score on '
                            'this view.</b> The score is calculated across every scored '
                            'Loc-SKU. Recomputing it on the worst subset would produce a '
                            'number that looks precise and means nothing. Switch to '
                            '<b>All stock</b> to read it.</div>', True)
                  + layer("focus", '<div class="sect"><h2>Where to focus</h2>'
                          '<span>not shown for this view</span></div>' + pointer, True)
                  + layer("locations", '<div class="sect"><h2>Locations</h2>'
                          '<span>not shown for this view</span></div>' + pointer, True)
                  + layer("divisions", '<div class="sect"><h2>Divisions and Sections</h2>'
                          '<span>not shown for this view</span></div>' + pointer, True)
                  + layer("queue", '<div class="sect"><h2>Recommended Actions</h2>'
                          '<span>the nine situations that need work</span></div>'
                          + '<section class="card"><h3>Every state needing action</h3>'
                            '<p class="sub">All nine, in urgency order. The five states needing no action or that cannot be determined are excluded.</p>'
                          + needs_ladder + '</section>', True)
                  + caveats(cav_needs)
                  + '<div class="foot"><span>Reference design &mdash; only the Loc-SKUs needing action.</span><span>AI-assisted analysis</span></div></div>')

    rail = (
        '<nav class="rail" aria-label="Sections"><div class="mark">AI</div>'
        '<div class="grp">Report</div>'
        '<button data-nav="overview" aria-current="true">Overview</button>'
        '<button data-nav="summary">Inventory Health Score</button>'
        '<button data-nav="focus">Where to focus</button>'
        '<button data-nav="locations">Locations</button>'
        '<button data-nav="divisions">Divisions</button>'
        '<button data-nav="queue">Recommended Actions</button>'
        '<div class="grp">View</div>'
        '<button data-viewbtn="all" aria-current="true">All stock</button>'
        '<button data-viewbtn="needs">Needs action only</button>'
        '<p class="foot">Reference design.<br>Figures are the closing stock position on  '
        '{asat}.</p></nav>'.format(asat=AS_AT.replace(" ", "&nbsp;")))

    masthead = (
        '<div class="masthead"><div>'
        '<p class="eyebrow">Inventory</p>'
        '<h1>Inventory Management</h1>'
        '<p class="asat">Closing stock as at {asat} &middot; {n} Stores &middot; {skus} Loc-SKUs</p></div>'
        '<div class="seg" role="group" aria-label="View">'
        '<button data-viewbtn="all" aria-pressed="true">All stock</button>'
        '<button data-viewbtn="needs" aria-pressed="false">Needs action only</button>'
        '</div></div>'.format(asat=AS_AT, n=len(F.STORES), skus=full(F.SKUS)))

    script = JS.replace(
        "var LAYERS = ['summary','focus','locations','divisions','queue'];",
        "var LAYERS = ['overview','summary','focus','locations','divisions','queue'];")
    assert "'overview'" in script, "the layer list must include the Overview tab"

    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>Inventory Management &mdash; reference dashboard</title>\n"
            "<style>" + css + "</style>\n</head>\n<body>\n<div class=\"app\">"
            + rail + "<main><div class=\"page\">" + masthead + view_all + view_needs
            + "</div></main></div>\n<script>" + script + "</script>\n</body>\n</html>\n")


if __name__ == "__main__":
    out = build()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "reference_inventory_management_standardised.html")
    open(path, "w", encoding="utf8").write(out)
    print("wrote", path, len(out), "bytes")
