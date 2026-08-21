"""Build the Inventory Management reference page.

Every figure comes from inventory_management_facts, which reads
inventory_management_scan.json straight out of the semantic model. Nothing on
the page is typed in by hand.

The wording is deliberately everyday English: the page says "more stock than
needed" and prints "called Excess Stock in the model" underneath in small grey
type, so a general reader and the semantic model are both served. The queue
table does the same. Those two places are the ONLY ones where the model's own
vocabulary appears, and the auditor strips them before checking the rest of the
page for jargon.

Run me, then run audit_inventory_management_reference.py, then look at the
rendered page in a browser. All three steps matter: the auditor cannot see
layout, and a browser cannot check arithmetic.
"""
import html
import re

import os

import inventory_management_facts as F

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
def full(v):
    return "{:,.0f}".format(round(v))


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
PLAIN_RISK = {
    "Excess": "More stock than needed",
    "Ageing": "Stock getting old",
    "Dead": "Stock not selling",
    "OOS": "Nothing left to sell",
    "Verge": "About to run out",
    "Damage": "Damaged stock",
}

DIM_PLAIN = {
    "Value impact": "How much money",
    "Sales impact": "How much money",
    "SKU breadth": "How many products",
    "Duration": "How long it has gone on",
    "Severity": "How old the stock is",
    "Segment severity": "How important they are",
}


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
            '<p class="d-model">called <b>{name}</b> in the model</p>'
            '<p class="d-read">{read}</p></div>'
            '<span class="pill {pill}">{pill_lab}</span></div>'
            '<div class="d-nums"><span class="d-score">&minus;{p}</span>'
            '<span class="d-delta">points off the score</span></div>'
            '<div class="d-bar"><span style="width:{barw:.1f}%"></span></div>'
            '<p class="d-contrib"><b>{sh}</b> of the {lost} points lost</p>'
            '<div class="dims">{dims}</div>'
            '<p class="d-why">{why}</p>'
            '<p class="d-tol">{tol}</p></article>'.format(
                cls=cls, name=esc(name), plain=esc(PLAIN_RISK[key]),
                read=esc(READ[key]), pill=pill,
                pill_lab=pill_lab, p=pts(p), barw=sh, sh=pct(sh),
                lost=pts(F.LOST), dims=dims, why=WHY[key], tol=esc(TOL[key])))
    return "".join(out)


QUEUE_PLAIN = {
    "STOCK OUT - PLACE ORDER": "Sold out, nothing ordered",
    "STOCK OUT - AVAILABLE IN WAREHOUSE": "Sold out, but a warehouse has it",
    "STOCK OUT - ORDER PLACED": "Sold out, more on the way",
    "ON THE VERGE OF STOCK OUT - PLACE ORDER": "Nearly sold out, nothing ordered",
    "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE":
        "Nearly sold out, but a warehouse has it",
    "ON THE VERGE OF STOCK OUT - ORDER PLACED": "Nearly sold out, more on the way",
    "OVERSTOCK": "Far more stock than needed",
    "NON MOVING": "Not selling at all",
    "IN STOCK BUT NO SALES": "In stock, but nothing sold",
    "STOCK AVAILABLE - REORDER LEVEL UNKNOW": "In stock, no reorder level set",
    "STOCK AVAILABLE": "Selling normally",
    "NOT ACTIVE": "Switched off",
    "NA": "No reorder level set",
    "NEW LISTED SKU": "New product",
}

BAND_PLAIN = {
    "Excellent": "almost nothing wrong",
    "Healthy": "a few small problems",
    "Watch": "worth keeping an eye on",
    "At Risk": "needs work",
    "Critical": "a lot wrong at once",
    "Out of Stock": "nothing left to sell",
}

RISK_COL = {"Excess": "Too much", "Ageing": "Getting old", "Dead": "Not selling",
            "OOS": "Sold out", "Verge": "Nearly out", "Damage": "Damaged"}

MONTH = {"2026-05-01": "May", "2026-06-01": "June",
         "2026-07-01": "July", "2026-08-01": "August"}


READ = {
    "Excess": "{} more than the shops can sell in time".format(money(F.RD["Excess"]["val"])),
    "Ageing": "{} of stock over three months old".format(money(F.RD["Ageing"]["val"])),
    "Dead": "{} that has not sold at all".format(money(F.RD["Dead"]["val"])),
    "OOS": "{} products with nothing left".format(full(F.RD["OOS"]["skus"])),
    "Verge": "{} products about to run out".format(full(F.RD["Verge"]["skus"])),
    "Damage": "{} written off last month".format(money(F.RD["Damage"]["val"])),
}

_W3 = ("Worth up to 25 points. Money counts 50%, number of products 30%, "
       "the third thing 20%.")
TOL = {
    "Excess": _W3,
    "Ageing": _W3,
    "Dead": _W3,
    "OOS": _W3,
    "Verge": _W3,
    "Damage": "Worth up to 25 points. Money counts 70%, number of products 30%.",
}

WHY = {
    "Excess": ("{n} products have more stock than they can sell in the time the business "
               "agreed. Almost all of it has been sitting far longer than the score allows "
               "for, so this is not a recent mistake."
               .format(n=full(F.RD["Excess"]["skus"]))),
    "Ageing": ("Half of all the products the shops can measure hold stock over three months "
               "old, and {v} of it is over a year old.".format(v=money(F.AGE_OVER12))),
    "Dead": ("{n} products have not sold at all. The worst part is the oldest: {a} of them "
             "have not sold in over six months, more products than the one-to-two month and "
             "two-to-three month groups put together ({b})."
             .format(n=full(F.RD["Dead"]["skus"]), a=full(F.NM_180_N),
                     b=full(F.NM_SHORT_N))),
    "OOS": ("{w} of these are missing from a shop but sitting in a warehouse, so they only "
            "need moving. The other {o} have none anywhere and nothing on order."
            .format(w=full(F.QUEUE[1]["n"]), o=full(F.QUEUE[0]["n"]))),
    "Verge": ("Very few products, but the ones about to run out are the ones that sell best, "
              "which is why this still costs {p} points.".format(p=pts(F.RISKS[4][2]))),
    "Damage": ("Write-offs have climbed steeply: {}. August is only nineteen days and is "
               "already close to the whole of July."
               .format(", ".join("{} in {}".format(money(v), MONTH[d])
                                 for d, v, _n in F.DAMAGE))),
}

def stories():
    items = [
        dict(key="Excess", cls="crit", title="Too much stock was bought",
             position="{v} of stock is more than the shops can sell in the time the business "
                      "agreed. That is {n} products, and {s} of everything the shops hold."
                      .format(v=full(F.RD["Excess"]["val"]), n=full(F.RD["Excess"]["skus"]),
                              s=pct(F.RD["Excess"]["val"] / F.STOCK * 100)),
             why="This did not happen recently. Almost all of it has been sitting far longer "
                 "than the score allows for, and the products holding it average more than "
                 "{days} days of stock. The money has already been spent, so the only way "
                 "back is to sell it."
                 .format(days=full(min(v for k, v in F.EXC_DAYS.items() if k != "ST5"))),
             effect="It takes {p} points off the score, more than any other problem."
                    .format(p=pts(F.RISKS[0][2])),
             stat=full(F.RD["Excess"]["val"]),
             stat_lab="the extra only, not the whole value of those products",
             do="Go through the {n} products with far too much stock. Mark them down, "
                "promote them, or move them to a shop that can sell them. Start with {s}, "
                "which has the most."
                .format(n=full(F.QUEUE[6]["n"]),
                        s=esc(max(F.EXC_BY_STORE, key=F.EXC_BY_STORE.get)))),
        dict(key="Ageing", cls="crit", title="Stock is getting old",
             position="{v} of stock is over three months old, spread across {n} products. "
                      "Half of every product the shops can measure holds some."
                      .format(v=full(F.RD["Ageing"]["val"]), n=full(F.RD["Ageing"]["skus"])),
             why="The ageing report looks at each batch of a product separately, so an "
                 "expensive old batch counts for more than a cheap one. Of {t} of shop stock "
                 "in that report, {o} is over three months old and {tw} is over a year."
                 .format(t=full(F.AGE_TOTAL), o=full(F.AGE_OVER3), tw=full(F.AGE_OVER12)),
             effect="It takes {p} points off. What makes it bad is how widespread it is: "
                    "half the shelves, not a few bad products."
                    .format(p=pts(F.RISKS[1][2])),
             stat=full(F.AGE_OVER12), stat_lab="of shop stock is over a year old",
             do="Clear the {tw} that is over a year old first. It counts the most against "
                "the score and it will not get better on its own."
                .format(tw=full(F.AGE_OVER12))),
        dict(key="Dead", cls="crit", title="Some stock has stopped selling",
             position="{v} of stock across {n} products has not sold at all."
                      .format(v=full(F.RD["Dead"]["val"]), n=full(F.RD["Dead"]["skus"])),
             why="The worst part is the oldest. {a} products have not sold in over six "
                 "months, holding {av}. That is more products than the one-to-two month and "
                 "two-to-three month groups put together."
                 .format(a=full(F.NM_180_N), av=full(F.NM_180_VAL)),
             effect="It takes {p} points off, and most of that money has been sitting still "
                    "for a long time.".format(p=pts(F.RISKS[2][2])),
             stat=full(F.NM_180_N), stat_lab="products with no sale in over six months",
             do="Put those {a} products into a clearance, or move them to a shop where they "
                "might sell, before they get any older.".format(a=full(F.NM_180_N))),
        dict(key="OOS", cls="crit", title="Some products have nothing left to sell",
             position="{n} products are sold out. The sales at stake are worth {v}."
                      .format(n=full(F.RD["OOS"]["skus"]), v=full(F.RD["OOS"]["val"])),
             why="There are two different problems here. {w} products are missing from a "
                 "shop but sitting in a warehouse, so they only need moving and that costs "
                 "nothing. The other {o} have none anywhere and nothing on order."
                 .format(w=full(F.QUEUE[1]["n"]), o=full(F.QUEUE[0]["n"])),
             effect="It takes {p} points off, and the products running out are the ones that "
                    "sell best: {pr} of them are in the top two selling groups."
                    .format(p=pts(F.RISKS[3][2]), pr=full(F.PRIME_OOS)),
             stat=full(F.OPP_SCOPED), stat_lab="of sales already missed on the best sellers",
             do="Move the {w} from the warehouse today. Order the {o} that have none "
                "anywhere.".format(w=full(F.QUEUE[1]["n"]), o=full(F.QUEUE[0]["n"]))),
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
            '<dt>Why it happened</dt><dd>{why}</dd>'
            '<dt>What it does to the score</dt><dd>{effect}</dd>'
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
        sub = full(x["val"]) if x["val"] > 0 else "no stock left"
        rows.append(
            '<div class="lrow {cls}"><span class="lrank">{i}</span><div>'
            '<p class="lname">{label}{tag}</p>'
            '<div class="ltrack"><span class="lfill" style="width:{w:.1f}%;background:{col}"></span></div>'
            '</div><div class="lval"><b>{n}</b><span>{sub}</span></div></div>'.format(
                cls=cls, i=i, label=esc(QUEUE_PLAIN[x["key"]]), tag=tag,
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
                v=full(x["val"]) if x["val"] else "no stock left"))
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
                note='<br><span class="act">closing down</span>' if wind else "",
                spark=sparkline(F.STORE_TREND[loc], colour=AMBER if wind else TEAL),
                sc=pts(sc), pill=pill, lab=lab,
                stock=full(F.num(r, "Stock")), skus=full(F.num(r, "SKUs")),
                ex=pts(F.num(r, "Excess")), ag=pts(F.num(r, "Ageing")),
                de=pts(F.num(r, "Dead")), oo=pts(F.num(r, "OOS")),
                ve=pts(F.num(r, "Verge")), da=pts(F.num(r, "Damage"))))
    return ('<div class="scroll"><table><thead><tr><th>Shop</th><th>Stock since 1 Jun</th>'
            '<th class="n">Score</th><th class="n">How it reads</th>'
            '<th class="n">Stock value</th><th class="n">Products</th>{rh}</tr></thead>'
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
                n=esc(F.g(r, "DEPARTMENT")), sc=pts(sc), pill=pill, lab=lab,
                stock=full(F.num(r, "Stock")), skus=full(F.num(r, "SKUs")),
                ex=pts(F.num(r, "Excess")), ag=pts(F.num(r, "Ageing")),
                de=pts(F.num(r, "Dead")), oo=pts(F.num(r, "OOS")),
                ve=pts(F.num(r, "Verge")), da=pts(F.num(r, "Damage"))))
    return ('<div class="scroll"><table><thead><tr><th>Department</th><th class="n">Score</th>'
            '<th class="n">How it reads</th><th class="n">Stock value</th>'
            '<th class="n">Products</th>{rh}</tr></thead><tbody>{rows}</tbody></table></div>'
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
            note = ('<br><span class="act">no stock-cover setting, so the '
                    '&ldquo;too much&rdquo; check cannot run</span>')
        elif thin:
            note = '<br><span class="act">too few products here to mean much</span>'
        rows.append(
            '<tr><td><b>{n}</b>{note}</td><td class="act">{d}</td><td class="n"><b>{sc}</b></td>'
            '<td class="n"><span class="pill {pill}">{lab}</span></td>'
            '<td class="n">{stock}</td><td class="n">{skus}</td>'
            '<td class="n">{ex}</td><td class="n">{ag}</td><td class="n">{de}</td>'
            '<td class="n">{oo}</td></tr>'.format(
                n=esc(name), note=note, d=esc(F.g(r, "DEPARTMENT")), sc=pts(sc),
                pill=pill, lab=lab, stock=full(F.num(r, "Stock")), skus=full(F.num(r, "SKUs")),
                ex=pts(F.num(r, "Excess")), ag=pts(F.num(r, "Ageing")),
                de=pts(F.num(r, "Dead")), oo=pts(F.num(r, "OOS"))))
    return ('<div class="scroll"><table><thead><tr><th>Section</th><th>Department</th>'
            '<th class="n">Score</th><th class="n">How it reads</th>'
            '<th class="n">Stock value</th><th class="n">Products</th>'
            '<th class="n">Too much</th><th class="n">Getting old</th>'
            '<th class="n">Not selling</th><th class="n">Sold out</th>'
            '</tr></thead><tbody>{}</tbody></table></div>').format("".join(rows))


def queue_table():
    kinds = {"act": "needs work", "gap": "cannot tell", "ok": "nothing to do"}
    rows = []
    for i, x in enumerate(F.QUEUE, 1):
        rows.append(
            '<tr{tr}><td class="n">{i}</td><td><b>{label}</b><br>'
            '<span class="act">{model}</span></td>'
            '<td class="act">{kind}</td><td class="n">{n}</td><td class="n">{val}</td>'
            '<td class="n">{exc}</td><td class="n">{po}</td></tr>'.format(
                tr=' class="urgent"' if x["tag"] == "most urgent" else "",
                i=i, label=esc(QUEUE_PLAIN[x["key"]]), model=esc(x["key"]),
                kind=kinds[x["kind"]], n=full(x["n"]),
                val=full(x["val"]) if x["val"] else "&mdash;",
                exc=full(x["exc"]) if x["exc"] else "&mdash;",
                po=full(x["po"]) if x["po"] else "&mdash;"))
    return ('<div class="scroll"><table><thead><tr><th class="n">#</th>'
            '<th>What is happening</th><th>Kind</th><th class="n">Products</th>'
            '<th class="n">Stock value</th><th class="n">Of which extra</th>'
            '<th class="n">On order</th></tr></thead><tbody>{}</tbody></table></div>'
            ).format("".join(rows))


def wh_table():
    rows = []
    for x in F.WH:
        rows.append('<tr><td><b>{loc}</b></td><td class="n">{n}</td><td class="n">{val}</td>'
                    '<td class="n">{exc}</td><td class="n">{nm}</td><td class="n">{nmv}</td></tr>'
                    .format(loc=esc(x["loc"]), n=full(x["n"]), val=full(x["val"]),
                            exc=full(x["exc"]), nm=full(x["nm"]), nmv=full(x["nmval"])))
    return ('<div class="scroll"><table><thead><tr><th>Warehouse</th>'
            '<th class="n">Products</th><th class="n">Stock value</th>'
            '<th class="n">More than needed</th><th class="n">Not selling</th>'
            '<th class="n">Value not selling</th>'
            '</tr></thead><tbody>{}</tbody></table></div>').format("".join(rows))


CAVEATS_ALL = [
    "The score covers the five shops &mdash; <b>ST1, ST2, ST3, ST4 and ST5</b>. Warehouse "
    "scoring is being added to the model. Until it is there, the two warehouses appear here "
    "as stock figures only, with no score, and are never added to the shop score.",
    "These are the figures on <b>19 August 2026</b>, like a photograph of one moment. They "
    "are not totals for a month or a year. Only the damage figures and the shop stock line "
    "cover a stretch of time.",
    "A daily copy of these figures has only just started being saved. The line under "
    "&ldquo;The story&rdquo; shows the shape that chart will take, not real past scores.",
    "<b>FOOTWEAR</b> is missing its stock-cover setting, so the &ldquo;more than "
    "needed&rdquo; check cannot run on it at all. That is {n} products holding {v}. Its "
    "score of {s} looks better than it should.",
    "The <b>sales missed</b> figure of {o} counts only the products that sell best. There is "
    "a much larger figure in the model that counts everything, and it does not mean the same "
    "thing.",
    "Two of the model&rsquo;s tables are not linked up, so asking it for a single "
    "department&rsquo;s score gives the whole-company number instead. Everything on this "
    "page is worked out from the main stock table, which adds up to {t} exactly.",
    "{gapn} products holding {gapv} have no reorder level set, so the model cannot tell "
    "whether they are stocked correctly. They are shown as <i>cannot tell</i> rather than "
    "counted as fine.",
    "The numbers have no currency sign. They are in the money the group reports in.",
]


def caveats(items):
    return ('<div class="caveats"><h3>Things to know before using these numbers</h3>'
            '<ul>{}</ul></div>').format("".join("<li>{}</li>".format(x) for x in items))


def build():
    css = CSS

    score_band, score_cls, score_pill = band(F.SCORE)
    top3 = F.RISKS[0][2] + F.RISKS[1][2] + F.RISKS[2][2]

    # ---------------- summary layer, all-stock view -----------------------
    hero = (
        '<section class="hero score-hero">'
        '<div><span class="hero-tag">Stock health &middot; {bandl}</span>'
        '<h2>The shops score {score} out of 100. Three quarters of what they have lost is '
        'stock they already bought and are not selling.</h2>'
        '<p>Too much stock, stock getting old and stock that has stopped selling together '
        'take {top3} of the {lost} points lost &mdash; {tsh} of the damage. Products actually '
        'running out, which is what usually gets the attention, takes {oos}.</p>'
        '<div class="hero-stats" style="margin-top:16px">'
        '<div class="hs crit"><b>{lost}</b><span>points lost out of 100</span></div>'
        '<div class="hs"><b>{stock}</b><span>of shop stock covered</span></div>'
        '<div class="hs"><b>{oosn}</b><span>products with nothing left to sell</span></div>'
        '</div></div>'
        '<div class="gauge-wrap"><div class="gauge" style="background:conic-gradient({red} 0 {pctv:.1f}%,'
        'rgba(255,255,255,.10) 0)"><span class="g-val">{score}</span><span class="g-of">/100</span></div>'
        '<p class="g-label">{bandu}</p>'
        '<p class="g-delta">{lost} points lost across six problems</p></div></section>'
    ).format(bandl=score_band.lower(), score=pts(F.SCORE), top3=pts(top3), lost=pts(F.LOST),
             tsh=pct(top3 / F.LOST * 100), oos=pts(F.RISKS[3][2]), stock=full(F.STOCK),
             oosn=full(F.RD["OOS"]["skus"]), red=RED, pctv=F.SCORE, bandu=score_band)

    bands_html = "".join(
        '<div class="bandbox{here}"><b>{r}</b><span>{n}</span></div>'.format(
            here=" here" if n == score_band else "", r=r, n=n)
        for r, n in [("90 &ndash; 100", "Excellent"), ("80 &ndash; 89", "Healthy"),
                     ("70 &ndash; 79", "Watch"), ("60 &ndash; 69", "At Risk"),
                     ("Below 60", "Critical")])

    summary_all = (
        hero +
        '<div class="illus">A daily copy of these figures has only just started being '
        'saved, so there is no real history yet. The line below shows <b>the shape this chart '
        'will take</b> once there is. It has no past values on it on purpose. The only real '
        'point is the one at 19 August.</div>'

        '<div class="sect"><h2>The story</h2><span>the score, and what it is made of</span></div>'
        '<section class="card"><h3>The score once history builds up</h3>'
        '<p class="sub">The bands never move, so a score is judged against a fixed standard '
        'rather than against how it happened to wobble. The dashed line is shape only.</p>'
        + health_shape_chart() +
        '<div class="bands">' + bands_html + '</div></section>'
        '<div class="grid g-2" style="margin-top:14px">'
        '<section class="card"><h3>What takes the points off</h3>'
        '<p class="sub">Every product starts at 100. Each of the six problems takes points '
        'off, never more than 25 each. The six add up to the whole drop, so nothing is left '
        'unexplained.</p>'
        + composition_waterfall() +
        '<p class="note">Read it left to right: the score starts at 100, each problem takes '
        'points off, and it finishes at <b>{score}</b>. Biggest cause first, which is not the '
        'order the rules number them in.</p></section>'
        '<section class="card"><h3>How every product scores</h3>'
        '<p class="sub">Each product gets its own score too. Products that have sold out are '
        'scored a different way and are not put in one of the five bands.</p>'
        + health_bars() +
        '<p class="note">The average product scores <b>{avg}</b>, much better than the '
        'company score of <b>{score}</b>. That is not a mistake. The company score is worked '
        'out from where the money and the problems actually are, so {ex} of extra stock counts '
        'for far more than a long list of small, healthy products.</p>'
        '</section></div>'

        '<div class="sect"><h2>The six problems</h2>'
        '<span>what each one costs, and the three things behind it</span></div>'
        '<div class="drivers">' + risk_cards() + '</div>'

        '<div class="method"><h3>How the score is worked out</h3>'
        '<p>Every product in every shop starts with <b>100 points</b>, and six problems can '
        'take points off it. How many points a problem takes depends on three things: '
        '<b>how much money</b> is caught up in it (this counts most, half the weight), '
        '<b>how many products</b> it touches (a third), and <b>how long it has been going '
        'on</b> or how serious it is (a fifth). Damaged stock is the exception &mdash; it has '
        'no &ldquo;how long&rdquo; part, so money counts 70% and number of products 30%. Each '
        'problem can take at most <b>25 points</b>, so no single problem can wreck the score '
        'on its own.</p>'
        '<p>Products are only compared with <b>similar products in the same shop</b>. That way '
        'an expensive product does not look worse simply because it costs more than a cheap '
        'one.</p>'
        '<p>A product that has <b>already sold out</b> is treated differently on purpose. It '
        'starts at 0 instead of 100, and it can go below zero if other problems pile on top. '
        'Today {oosn} products are on that path, averaging {oosavg}. They are labelled '
        '&ldquo;Out of Stock&rdquo; rather than put in one of the five bands, because a product '
        'with nothing on the shelf cannot fairly be compared with one that has stock.</p>'
        '<p>The score is a summary. It is not a replacement for the actual numbers, which are '
        'in <b>Shops</b>, <b>Departments</b> and <b>Every product</b>.</p></div>'
    ).format(avg=pts(F.AVG_SKU), score=pts(F.SCORE), ex=money(F.RD["Excess"]["val"]),
             oosn=full([h for h in F.HEALTH if h["name"] == "Out of Stock"][0]["n"]),
             oosavg=pts([h for h in F.HEALTH if h["name"] == "Out of Stock"][0]["avg"]))

    # ---------------- focus layer ----------------------------------------
    focus_all = (
        '<div class="sect"><h2>Where to focus</h2>'
        '<span>the four biggest problems, and what to do about each</span></div>'
        '<p class="lead-note">These four cause {four} of the {lost} points lost &mdash; {sh} '
        'of the damage. They are put in order of how much they are hurting, not of how much '
        'money they hold.</p>'
        '<div class="stories">{stories}</div>'
        '<div class="sect"><h2>The evidence behind those four</h2>'
        '<span>where the numbers come from</span></div>'
        '<div class="grid g-2">'
        '<section class="card"><h3>The most urgent jobs</h3>'
        '<p class="sub">The six situations costing sales right now, biggest first. All '
        'fourteen are under <b>Every product</b>.</p>{ladder}'
        '<p class="note">These six cover <b>{six}</b> products. Every one of the {skus} '
        'products is accounted for under <b>Every product</b>.</p></section>'
        '<section class="card"><h3>How old the stock is</h3>'
        '<p class="sub">Shop stock split by how long it has been sitting there. One product '
        'can hold stock in several age groups at once.</p>{age}'
        '<div class="legend"><span><i style="background:{teal}"></i>under three months old'
        '</span><span><i style="background:{amber}"></i>three months or older</span></div>'
        '<p class="note"><b>{over3}</b> out of {total} is already over three months old '
        '&mdash; {o3pct} of it &mdash; and <b>{over12}</b> is over a year, which counts worst '
        'of all.</p></section></div>'
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
        '<div class="sect"><h2>Shops</h2><span>how each of the five is doing</span></div>'
        '<section class="card"><h3>The five shops</h3>'
        '<p class="sub">Each shop&rsquo;s score, what it holds, and how many points each '
        'problem takes off it. The small line shows its stock across the four dates.</p>'
        + store_table() +
        '<p class="note">Every shop is in the bottom two bands. The spread is narrow &mdash; '
        '{lo} to {hi} &mdash; so these problems are spread right across the shops rather than '
        'sitting in one bad one.</p></section>'
        '<div class="grid g-2e" style="margin-top:14px">'
        '<section class="card"><h3>Shop stock over time</h3>'
        '<p class="sub">The only real history the model holds: the value of stock in the shops '
        'on four dates. This is stock value, not the score.</p>' + trend_chart() +
        '<p class="note">Stock across the five shops has fallen from {t0} to {t1} since '
        '1 June. Nearly all of that is ST5.</p></section>'
        '<section class="card"><h3>ST5 is closing down</h3>'
        '<p class="sub">Read it separately from the other four. Its numbers do not mean the '
        'same thing as a shop that is trading normally.</p>'
        '<div class="rbars">{st5bars}</div>'
        '<p class="note">ST5 now holds {v} across {n} products, down <b>{drop}</b> since '
        '1 June. It has <b>no products with too much stock and none that have stopped '
        'selling</b>, and only four of the fourteen situations appear there at all. Its '
        '&ldquo;sold out&rdquo; score is at the full 25-point maximum, which is exactly what '
        'you would expect from a shop running its stock down. It is not a failure to '
        'fix.</p></section></div>'
        '<div class="sect"><h2>Warehouses</h2>'
        '<span>shown for information &mdash; not scored yet</span></div>'
        '<section class="card"><h3>WH1 and WH2</h3>'
        '<p class="sub">The score covers the five shops. Warehouse scoring is being added to '
        'the model. These are the same checks read straight from the stock data, with no score '
        'attached.</p>'
        + wh_table() +
        '<p class="note">The warehouses hold <b>{whv}</b> &mdash; more than all five shops '
        'put together &mdash; and <b>{whe}</b> of that is more than is needed. Read these '
        'beside the shop figures, never added to them.</p></section>'
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
        '<div class="sect"><h2>Departments and sections</h2>'
        '<span>which parts of the shop are worst</span></div>'
        '<section class="card"><h3>By department</h3>'
        '<p class="sub">Four departments. Each one is worked out from its own products, not '
        'averaged from the sections inside it.</p>' + dept_table() +
        '<p class="note"><b>{wn}</b> is the worst at {ws}, {gap} points below <b>{bn}</b> at '
        '{bs}. Almost all of that gap is old stock and stock that is not selling &mdash; {wa} '
        'and {wd} points against {ba} and {bd}.</p></section>'
        '<section class="card" style="margin-top:14px"><h3>By section</h3>'
        '<p class="sub">All twenty, worst first. Sections with fewer than 100 products are '
        'marked &mdash; their scores swing on a handful of items, so do not read much into '
        'them.</p>'
        + section_table() +
        '<p class="note">The worst section with real size behind it is <b>{ms}</b> at {mss} '
        'across {msn} products, where running out of stock alone takes {mso} of the 25 points '
        'available.</p></section>'
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
        '<div class="sect"><h2>Every product</h2>'
        '<span>all fourteen situations, nothing left out</span></div>'
        '<section class="card"><h3>All fourteen situations</h3>'
        '<p class="sub">In order of urgency: what is costing sales right now, then what is '
        'about to, then the money already tied up. Nine need work, two cannot be judged, and '
        'three are fine. The grey line under each name is what the model calls it.</p>'
        + queue_table() +
        '<p class="note">The fourteen add up to <b>{skus}</b> products exactly. '
        '<b>{needs}</b> need work, holding <b>{needsv}</b>. Another <b>{gapn}</b> holding '
        '{gapv} have no reorder level set, so the model cannot say whether they are stocked '
        'correctly &mdash; that is a gap in the data, not a clean bill of health. The other '
        '{okn} are selling normally, new, or switched off.</p></section>'
        '<div class="grid g-2e" style="margin-top:14px">'
        '<section class="card"><h3>How long stock has gone without selling</h3>'
        '<p class="sub">Shop products that have stopped selling, grouped by how long it has '
        'been. Only these count towards the &ldquo;not selling&rdquo; problem.</p>'
        '{nm}'
        '<p class="note">The longest group is the biggest: <b>{n180}</b> products have not '
        'sold in over six months, holding {v180}. The score treats anything past six months as '
        'the worst it can be, so these cannot get any worse &mdash; only harder to '
        'sell.</p></section>'
        '<section class="card"><h3>Stock written off, by month</h3>'
        '<p class="sub">Stock damaged or thrown away, at all locations. The score reads the '
        'latest month only, which is why this moves faster than the other five.</p>'
        '{dmg}'
        '<p class="note">Write-offs climbed steeply from May to July. August is shown to the '
        '{asat} only &mdash; {aug} in nineteen days, already close to the whole of July at '
        '{jul} &mdash; so it is not a full month and cannot be read as a fall. The figure used '
        'in the score is {scored}, the shops&rsquo; share of the latest month.</p>'
        '</section></div>'
    ).format(skus=full(F.SKUS), needs=full(F.NEEDS_N), needsv=full(F.NEEDS_VAL),
             gapn=full(F.GAP_N), gapv=full(F.GAP_VAL), okn=full(F.OK_N),
             nm=vbars([(k, v, k == ">180") for k, _n, v in F.NM], label_two_line=False,
                      W=560, H=228),
             n180=full(F.NM_180_N), v180=full(F.NM_180_VAL),
             dmg=vbars(dmg_rows, label_two_line=False, W=560, H=228),
             asat="19th", aug=full(F.DAMAGE[-1][1]), jul=full(F.DAMAGE[-2][1]),
             scored=full(F.RD["Damage"]["val"]))

    cav_all = list(CAVEATS_ALL)
    cav_all[3] = cav_all[3].format(
        n=full(5583), v=full(214739.1729),
        s=pts([F.num(r, "Score") for r in F.SECTS if F.g(r, "SECTION") == "FOOTWEAR"][0]))
    cav_all[4] = cav_all[4].format(o=full(F.OPP_SCOPED))
    cav_all[5] = cav_all[5].format(t=full(F.STOCK))
    cav_all[6] = cav_all[6].format(gapn=full(F.GAP_N), gapv=full(F.GAP_VAL))
    cav_all[6] = cav_all[6].format(gapn=full(F.GAP_N), gapv=full(F.GAP_VAL))

    # ---------------- needs-action view -----------------------------------
    needs_hero = (
        '<section class="hero"><div>'
        '<span class="hero-tag">Only the products that need work</span>'
        '<h2>{needs} of the {skus} products are in a situation that needs work.</h2>'
        '<p>They hold {val} of stock. This view counts only those products, so its totals will '
        'not match the all-stock view. There is no score here, because a score worked out on '
        'only the worst products would not mean anything.</p></div>'
        '<div class="hero-stats">'
        '<div class="hs crit"><b>{needs}</b><span>products needing work</span></div>'
        '<div class="hs"><b>{val}</b><span>of stock tied up in them</span></div>'
        '<div class="hs"><b>{shr}</b><span>of every product in the shops</span></div>'
        '</div></section>'
    ).format(needs=full(F.NEEDS_N), skus=full(F.SKUS), val=full(F.NEEDS_VAL),
             shr=pct(F.NEEDS_N / F.SKUS * 100))

    pointer = ('<div class="pointer"><b>This view does not have its own breakdown by shop, '
               'department or section.</b> Those splits are worked out across all the stock, '
               'not just the products needing work, so showing them here would print rows that '
               'do not add up to this view&rsquo;s own totals. Switch to <b>All stock</b> to '
               'read them.</div>')

    needs_ladder = ladder(F.NEEDS, F.NEEDS_N)
    needs_scoped = ('<div class="scoped">This view counts only products in a situation that '
                    'needs work. Its totals will not match the all-stock view, and that is '
                    'expected.</div>')

    cav_needs = [
        "Everything here counts only the <b>{n} products that need work</b>. The totals will "
        "not match the all-stock view, and that is expected.".format(n=full(F.NEEDS_N)),
        "There is <b>no score</b> on this view. The score is worked out across every product; "
        "working it out again on only the worst ones would not mean anything.",
        "These are the figures on <b>{}</b>, not totals for a period.".format(AS_AT),
        "One situation the rules describe &mdash; a product that is not selling and has more "
        "on order &mdash; returns nothing at all. Either there are none, or the source system "
        "is not producing it.",
        "The five situations left out account for the other {r} products: {o} selling "
        "normally, new or switched off, and {g} the model cannot judge because they have no "
        "reorder level."
        .format(r=full(F.REST_N), o=full(F.OK_N), g=full(F.GAP_N)),
    ]

    # ---------------- assemble --------------------------------------------
    def layer(name, body, hidden=False):
        return '<div class="layer" data-layer="{}"{}>{}</div>'.format(
            name, " hidden" if hidden else "", body)

    view_all = ('<div class="view" data-view="all">'
                + layer("summary", summary_all)
                + layer("focus", focus_all, True)
                + layer("locations", locations_all, True)
                + layer("divisions", divisions_all, True)
                + layer("queue", queue_all, True)
                + caveats(cav_all)
                + '<div class="foot"><span>Reference design &mdash; INVENTORY MANAGEMENT REPORT, '
                  'semantic model 16d47b06. Figures read on {asat}.</span>'
                  '<span>The score and its six problems come from the model&rsquo;s own '
                  '_HEALTH SCORE MEASURES.</span></div></div>').format(asat=AS_AT)

    view_needs = ('<div class="view" data-view="needs" hidden>'
                  + layer("summary", needs_hero + '<div class="sect"><h2>Every situation that '
                          'needs work</h2><span>nine of the fourteen</span></div>' + needs_scoped
                          + '<section class="card"><h3>In urgency order</h3>'
                            '<p class="sub">What is costing sales right now, then what is '
                            'about to, then the money already tied up.</p>' + needs_ladder
                          + '<p class="note">These nine add up to <b>{n}</b> products '
                            'holding <b>{v}</b>.</p></section>'.format(n=full(F.NEEDS_N),
                                                                       v=full(F.NEEDS_VAL)))
                  + layer("focus", '<div class="sect"><h2>Where to focus</h2>'
                          '<span>not shown for this view</span></div>' + pointer, True)
                  + layer("locations", '<div class="sect"><h2>Shops</h2>'
                          '<span>not shown for this view</span></div>' + pointer, True)
                  + layer("divisions", '<div class="sect"><h2>Departments and sections</h2>'
                          '<span>not shown for this view</span></div>' + pointer, True)
                  + layer("queue", '<div class="sect"><h2>Every product</h2>'
                          '<span>the nine situations that need work</span></div>'
                          + '<section class="card"><h3>Every situation that needs work</h3>'
                            '<p class="sub">All nine, in urgency order. The five that are '
                            'fine, informational, or cannot be judged are left out.</p>'
                          + needs_ladder + '</section>', True)
                  + caveats(cav_needs)
                  + '<div class="foot"><span>Reference design &mdash; only the products '
                    'needing work.</span><span>AI-assisted analysis</span></div></div>')

    rail = (
        '<nav class="rail" aria-label="Sections"><div class="mark">AI</div>'
        '<div class="grp">Report</div>'
        '<button data-nav="summary" aria-current="true">The health score</button>'
        '<button data-nav="focus">Where to focus</button>'
        '<button data-nav="locations">Shops</button>'
        '<button data-nav="divisions">Departments</button>'
        '<button data-nav="queue">Every product</button>'
        '<div class="grp">View</div>'
        '<button data-viewbtn="all" aria-current="true">All stock</button>'
        '<button data-viewbtn="needs">Only what needs work</button>'
        '<p class="foot">Reference design.<br>Figures are the real position on '
        '{asat}.</p></nav>'.format(asat=AS_AT.replace(" ", "&nbsp;")))

    masthead = (
        '<div class="masthead"><div>'
        '<p class="eyebrow">Inventory</p>'
        '<h1>How the stock is doing</h1>'
        '<p class="asat">The position on {asat} &middot; {n} shops &middot; {skus} '
        'products</p></div>'
        '<div class="seg" role="group" aria-label="View">'
        '<button data-viewbtn="all" aria-pressed="true">All stock</button>'
        '<button data-viewbtn="needs" aria-pressed="false">Only what needs work</button>'
        '</div></div>'.format(asat=AS_AT, n=len(F.STORES), skus=full(F.SKUS)))

    script = JS

    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>Inventory Management &mdash; reference dashboard</title>\n"
            "<style>" + css + "</style>\n</head>\n<body>\n<div class=\"app\">"
            + rail + "<main><div class=\"page\">" + masthead + view_all + view_needs
            + "</div></main></div>\n<script>" + script + "</script>\n</body>\n</html>\n")


if __name__ == "__main__":
    out = build()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "reference_inventory_management.html")
    open(path, "w", encoding="utf8").write(out)
    print("wrote", path, len(out), "bytes")
