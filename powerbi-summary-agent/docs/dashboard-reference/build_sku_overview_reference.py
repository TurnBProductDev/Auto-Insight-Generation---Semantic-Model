"""Render reference_sku_overview.html - the design target for SKU Overview.

    python build_sku_overview_reference.py

Every figure comes from sku_overview_facts.py, which reads sku_overview_scan.json
and refuses to produce facts if the model stops reconciling. Nothing here is
typed by hand. Rebuilding produces a byte-identical file.

Same shell as reference_daily_sales.html and the inventory references: rail +
main and nothing else inside .app, layers, two views, #<view>/<layer> in the URL
so a tab is linkable and a screenshot tool can reach it without a click.
"""
from __future__ import annotations

import html
import pathlib

import sku_overview_facts as SF

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "reference_sku_overview.html"

LAYERS = [
    ("overview", "Overview"),
    ("product", "One product in full"),
    ("selling", "What is selling"),
    ("action", "What needs action"),
    ("detail", "Departments and shops"),
]
VIEWS = [("all", "All products"), ("top", "Best sellers only")]

# The shared R6 shell, unchanged from reference_daily_sales.html so a styling
# fix lands on every page. Everything below the marked line is new to this
# report and nothing else uses it.
CSS = """
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

.hero{background:var(--rail);border-radius:var(--r);padding:20px 24px;margin-bottom:14px;
  display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:26px;align-items:center}
.hero-tag{display:inline-block;font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  font-weight:750;color:#f0c46a;background:rgba(240,196,106,.14);padding:4px 9px;
  border-radius:6px;margin-bottom:10px}
.hero h2{color:#fff;font-size:23px;line-height:1.22;letter-spacing:-.015em;font-weight:700}
.hero p{color:#a9c2bd;font-size:12.5px;margin-top:8px;max-width:60ch}
.hero-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.hs{border-left:2px solid rgba(255,255,255,.14);padding-left:12px}
.hs b{display:block;color:#fff;font-size:18px;font-weight:700;line-height:1.15}
.hs span{display:block;color:#7f9a95;font-size:10.5px;margin-top:3px;line-height:1.35}
.hs.crit b{color:#ff8b73}

.grid{display:grid;gap:14px;align-items:start}
.g-2{grid-template-columns:minmax(0,1.35fr) minmax(0,1fr)}
.g-2e{grid-template-columns:repeat(2,minmax(0,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:16px 18px;box-shadow:var(--shadow)}
.card>h3{font-size:13.5px;font-weight:700;letter-spacing:-.01em}
.card>.sub{font-size:11.5px;color:var(--muted);margin-top:2px;margin-bottom:12px}
.sect{margin:22px 0 10px;display:flex;align-items:baseline;gap:11px}
.sect h2{font-size:16px;font-weight:700;letter-spacing:-.015em}
.sect span{font-size:11.5px;color:var(--faint)}
.note{font-size:11.5px;color:var(--muted);margin-top:10px;line-height:1.5}
.mini-h{font-size:10px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
  font-weight:700;margin:14px 0 8px}

.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:13px 14px 12px;position:relative;overflow:hidden;box-shadow:var(--shadow)}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--faint)}
.kpi.crit::before{background:var(--red)} .kpi.good::before{background:var(--green)}
.kpi .lab{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);
  font-weight:650}
.kpi .val{font-size:21px;font-weight:750;line-height:1.1;margin:5px 0 2px;letter-spacing:-.02em}
.kpi.crit .val{color:var(--red)} .kpi.good .val{color:var(--green)}
.kpi .sub{font-size:10.5px;color:var(--muted);line-height:1.4;margin-top:2px}
.kpi .pill{margin-top:7px}

.pill{display:inline-block;font-size:9px;font-weight:750;letter-spacing:.05em;
  text-transform:uppercase;padding:2px 6px;border-radius:5px}
.pill-crit{background:var(--red-tint);color:var(--red)}
.pill-ok{background:var(--green-tint);color:var(--green)}
.pill-neutral{background:#eef2f6;color:var(--muted)}

.rbars{display:flex;flex-direction:column;gap:9px}
.rb{display:grid;grid-template-columns:214px minmax(0,1fr) 128px;gap:11px;align-items:center;
  font-size:12px}
.rb-l{font-weight:650;overflow:hidden;text-overflow:ellipsis}
.rb-l small{display:block;font-weight:400;font-size:9.5px;color:var(--faint);
  letter-spacing:.02em}
.rb-t{background:#eef2f6;border-radius:99px;height:10px;position:relative}
.rb-f{display:block;height:100%;border-radius:99px}
.rb-v{text-align:right;font-weight:700}
.rb-v small{display:block;font-weight:600;font-size:9px;color:var(--muted);
  text-transform:uppercase;letter-spacing:.05em}

.scroll{overflow-x:auto;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
  font-weight:700;white-space:nowrap}
td.n,th.n{text-align:right;white-space:nowrap}
td.c{color:var(--muted)}
td.crit{color:var(--red);font-weight:700} td.good{color:var(--green);font-weight:700}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--soft)}
.act{display:block;color:var(--faint);font-size:9.5px;font-weight:400;
  letter-spacing:.02em;margin-top:2px}

.dz{fill:var(--faint);font-size:9px} .dzv{fill:var(--ink);font-size:10px;font-weight:700}
.dzday{fill:var(--mid);font-size:10.5px;font-weight:650}
.dzsub{fill:var(--faint);font-size:9.5px}
.dzann{font-size:10.5px;font-weight:750}

.caveats{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--faint);
  border-radius:var(--r);padding:15px 18px;margin-top:20px}
.caveats h3{font-size:12px;font-weight:700;margin-bottom:9px}
.caveats ul{margin:0;padding-left:17px;color:var(--mid);font-size:11.5px;line-height:1.6}
.caveats li{margin-bottom:5px}
.foot{margin-top:18px;padding-top:12px;border-top:1px solid var(--line);
  display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;
  font-size:10.5px;color:var(--faint)}

.layer[hidden],.view[hidden]{display:none}
.scoped{background:var(--amber-tint);border:1px solid #e8d3a8;border-radius:var(--r);
  padding:11px 15px;font-size:11.5px;color:var(--amber-dk);margin-bottom:14px}

/* ---- new to this report ---- */
.store{display:inline-block;font-size:10px;font-weight:700;background:var(--teal-tint);
  color:var(--teal-dk);padding:2px 7px;border-radius:5px;letter-spacing:.03em}
.rank{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:50%;
  background:#eef2f6;font-size:9.5px;font-weight:700;color:var(--muted);
  margin-right:6px;vertical-align:1px}
.rank.r1{background:var(--green-tint);color:var(--green)}
.idcard{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;
  background:var(--line);border:1px solid var(--line);border-radius:var(--r);
  overflow:hidden;margin-bottom:14px}
.idcard>div{background:var(--card);padding:13px 15px}
.idcard .lab{font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--muted);font-weight:700}
.idcard .v{font-size:14px;font-weight:700;margin-top:4px;line-height:1.25}
.idcard .c{font-size:10.5px;color:var(--faint);margin-top:3px;line-height:1.35}
.pendcard{background:var(--soft);border:1px dashed var(--faint);border-radius:var(--r);
  padding:17px 19px}
.pend-h{display:flex;align-items:center;justify-content:space-between;gap:14px;
  flex-wrap:wrap;margin-bottom:9px}
.pend-h h3{font-size:13.5px;font-weight:700}
.pendcard p{font-size:12px;color:var(--mid);line-height:1.55;margin-top:8px}
.pend-b{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}
@media (max-width:1080px){.pend-b{grid-template-columns:minmax(0,1fr)}}
.spot{background:var(--amber-tint);border-left:3px solid var(--amber);
  border-radius:0 8px 8px 0;padding:11px 15px;margin-top:13px}
.spot .l{font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--amber-dk);font-weight:750;margin-bottom:4px}
.spot p{font-size:12px;line-height:1.5}
.todo{margin:0;padding-left:17px;font-size:12.5px;color:var(--mid);line-height:1.6}
.todo li{margin-bottom:8px}
.none{font-size:12.5px;color:var(--green);background:var(--green-tint);
  border-radius:8px;padding:12px 14px;font-weight:600}

@media (max-width:1080px){
  .kpis,.idcard{grid-template-columns:repeat(2,minmax(0,1fr))}
  .g-2,.g-2e{grid-template-columns:minmax(0,1fr)}
  .hero{grid-template-columns:minmax(0,1fr)}
  .rb{grid-template-columns:150px minmax(0,1fr) 104px}
}
@media (max-width:720px){.rail{display:none}}
@media print{
  .rail,.seg{display:none}.app{display:block}
  .card,.kpi,.hero{break-inside:avoid;box-shadow:none}
  body{background:#fff}
  .layer[hidden],.view[hidden]{display:block}
}
"""

SCRIPT = """
(function(){
  var LAYERS = %s;

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

  var current = {view: 'all', layer: 'overview'};

  function apply(){
    setView(current.view);
    setLayer(current.layer);
    var hash = '#' + current.view + '/' + current.layer;
    if (location.hash !== hash){ history.replaceState(null, '', hash); }
  }

  function fromHash(){
    var parts = (location.hash || '').replace('#', '').split('/');
    if (parts[0] && document.querySelector('.view[data-view="' + parts[0] + '"]')){
      current.view = parts[0];
    }
    if (parts[1] && LAYERS.indexOf(parts[1]) !== -1){ current.layer = parts[1]; }
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
""" % ("[" + ",".join("'%s'" % k for k, _ in LAYERS) + "]")

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SKU Overview &mdash; reference dashboard</title>
<style>%(css)s</style>
</head>
<body>
<div class="app">
  <nav class="rail" aria-label="Sections">
    <div class="mark">AI</div>
    <div class="grp">Report</div>
    %(rail_layers)s
    <div class="grp">View</div>
    %(rail_views)s
    <p class="foot">Reference design.<br>Figures are the live position for %(as_at)s.</p>
  </nav>
<main><div class="page">
    <div class="masthead">
      <div>
        <p class="eyebrow">Stock &middot; product by shop</p>
        <h1>SKU Overview</h1>
        <p class="asat">%(as_at)s &middot; %(shops)s &middot; all money in US dollars</p>
      </div>
      <div class="seg" role="group" aria-label="View">%(seg)s</div>
    </div>
%(views)s
    <div class="foot"><span>%(footer_left)s</span><span>%(footer_right)s</span></div>
</div></main>
</div>
<script>%(script)s</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------

def e(s):
    return html.escape(str(s), quote=True)


def money(v, dp=0):
    """USD, always with the unit, because the model mixes two currencies."""
    return "USD&nbsp;{:,.{dp}f}".format(float(v), dp=dp)


def money_svg(v, dp=0):
    """SVG text has no HTML entities - a plain space or it prints literally."""
    return "USD {:,.{dp}f}".format(float(v), dp=dp)


def big(v):
    """A large figure shortened, for a headline only."""
    v = float(v)
    if abs(v) >= 1_000_000:
        return "USD&nbsp;{:,.2f}M".format(v / 1_000_000)
    if abs(v) >= 1_000:
        return "USD&nbsp;{:,.1f}K".format(v / 1_000)
    return money(v)


def n(v, dp=0):
    return "{:,.{dp}f}".format(float(v), dp=dp)


def pct(v, dp=1):
    return "{:,.{dp}f}%".format(float(v), dp=dp)


# --------------------------------------------------------------------------
# components - the shared R6 vocabulary
# --------------------------------------------------------------------------

def pill(text, tone="neutral"):
    return '<span class="pill pill-%s">%s</span>' % (tone, e(text))


def kpi(label, value, sub, tone="", pill_html=""):
    cls = "kpi" + ((" " + tone) if tone else "")
    return (
        '<div class="%s"><p class="lab">%s</p><p class="val">%s</p>'
        '<p class="sub">%s</p>%s</div>'
        % (cls, e(label), value, sub, pill_html)
    )


def card(title, sub, body, extra=""):
    return (
        '<div class="card%s"><h3>%s</h3><p class="sub">%s</p>%s</div>'
        % (extra, e(title), sub, body)
    )


def sect(title, note):
    return '<div class="sect"><h2>%s</h2><span>%s</span></div>' % (e(title), e(note))


def rbars(rows):
    """Ranked horizontal bars. rows = (label, sublabel, frac, value, tone)."""
    out = ['<div class="rbars">']
    for label, sub, frac, value, tone in rows:
        colour = {
            "crit": "var(--red)",
            "warn": "var(--amber)",
            "ok": "var(--teal)",
            "faint": "var(--faint)",
        }[tone]
        width = max(0.0, min(1.0, float(frac))) * 100.0
        out.append(
            '<div class="rb"><div class="rb-l">%s%s</div>'
            '<div class="rb-t"><span class="rb-f" style="width:%.2f%%;'
            'background:%s"></span></div>'
            '<div class="rb-v">%s</div></div>'
            % (
                e(label),
                ("<small>%s</small>" % e(sub)) if sub else "",
                width,
                colour,
                value,
            )
        )
    out.append("</div>")
    return "".join(out)


def table(headers, rows, min_width=640):
    """headers = (text, numeric?); rows = list of (cell_html, cls) tuples."""
    head = "".join(
        '<th%s>%s</th>' % (' class="n"' if num else "", e(t)) for t, num in headers
    )
    body = []
    for r in rows:
        cells = "".join(
            '<td%s>%s</td>' % ((' class="%s"' % c) if c else "", v) for v, c in r
        )
        body.append("<tr>%s</tr>" % cells)
    return (
        '<div class="scroll"><table style="min-width:%dpx"><thead><tr>%s</tr></thead>'
        "<tbody>%s</tbody></table></div>" % (min_width, head, "".join(body))
    )


def caveats(items):
    lis = "".join("<li>%s</li>" % i for i in items)
    return (
        '<div class="caveats"><h3>What these figures cover, and what they do not</h3>'
        "<ul>%s</ul></div>" % lis
    )


# --------------------------------------------------------------------------
# charts - each one earns its place
# --------------------------------------------------------------------------

def columns_chart(series, width=1180, height=210):
    """Grouped columns for the four weeks the model holds.

    Units, not money: the weekly table carries quantity only, and inventing a
    value for it would be inventing data.
    """
    labels = series["labels"]
    groups = series["groups"]          # [(name, [values], colour)]
    pad_l, pad_r, pad_t, pad_b = 44, 14, 16, 40
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    peak = max([v for _, vals, _ in groups for v in vals] + [1])
    slot = plot_w / max(1, len(labels))
    bar_w = min(38.0, (slot - 16) / max(1, len(groups)))

    out = [
        '<svg viewBox="0 0 %d %d" width="100%%" height="%d" role="img" '
        'aria-label="Units sold each week">' % (width, height, height)
    ]
    # baseline and two guides, so a bar can be read without counting pixels
    for f in (0.0, 0.5, 1.0):
        y = pad_t + plot_h * (1 - f)
        out.append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
            'stroke-width="1"/>'
            % (pad_l, y, width - pad_r, y, "#dfe7ec" if f else "#b8c6cc")
        )
        out.append(
            '<text class="dz" x="%.1f" y="%.1f" text-anchor="end">%s</text>'
            % (pad_l - 7, y + 3, n(peak * f))
        )
    for i, label in enumerate(labels):
        cx = pad_l + slot * i + slot / 2
        for g, (name, vals, colour) in enumerate(groups):
            v = vals[i]
            if v is None:
                continue
            h = plot_h * (float(v) / peak)
            x = cx - (bar_w * len(groups)) / 2 + g * bar_w
            y = pad_t + plot_h - h
            out.append(
                '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" '
                'fill="%s"><title>%s, %s: %s units</title></rect>'
                % (x, y, bar_w - 3, max(1.0, h), colour, label, name, n(v))
            )
            out.append(
                '<text class="dzv" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                % (x + (bar_w - 3) / 2, y - 4, n(v))
            )
        out.append(
            '<text class="dzday" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
            % (cx, height - pad_b + 17, label)
        )
    # legend sits on the baseline row, never floating over a bar
    lx = pad_l
    for name, _, colour in groups:
        out.append(
            '<rect x="%.1f" y="%.1f" width="9" height="9" rx="2" fill="%s"/>'
            % (lx, height - 13, colour)
        )
        out.append(
            '<text class="dzsub" x="%.1f" y="%.1f">%s</text>'
            % (lx + 13, height - 5, name)
        )
        lx += 22 + 6.6 * len(name)
    out.append("</svg>")
    return "".join(out)


def price_track(rows, width=520, height=132):
    """Where each shop's price sits inside the range the window has seen."""
    pad_l, pad_r, pad_t = 44, 60, 12
    plot_w = width - pad_l - pad_r
    lo = min(r["lo"] for r in rows)
    hi = max(r["hi"] for r in rows)
    span = (hi - lo) or 1.0
    step = 34
    out = [
        '<svg viewBox="0 0 %d %d" width="100%%" height="%d" role="img" '
        'aria-label="Price against the range seen in the window">'
        % (width, max(height, pad_t + step * len(rows) + 18),
           max(height, pad_t + step * len(rows) + 18))
    ]
    for i, r in enumerate(rows):
        y = pad_t + step * i + 12
        x0 = pad_l + plot_w * ((r["lo"] - lo) / span)
        x1 = pad_l + plot_w * ((r["hi"] - lo) / span)
        xn = pad_l + plot_w * ((r["now"] - lo) / span)
        out.append(
            '<text class="dzday" x="%.1f" y="%.1f" text-anchor="end">%s</text>'
            % (pad_l - 9, y + 4, r["loc"])
        )
        out.append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#dfe7ec" '
            'stroke-width="7" stroke-linecap="round"/>' % (x0, y, x1, y)
        )
        out.append(
            '<circle cx="%.1f" cy="%.1f" r="5.5" fill="%s"><title>%s: now %.2f, '
            'range %.2f to %.2f</title></circle>'
            % (xn, y, "#0f9f95", r["loc"], r["now"], r["lo"], r["hi"])
        )
        out.append(
            '<text class="dzv" x="%.1f" y="%.1f">%.2f</text>'
            % (width - pad_r + 8, y + 4, r["now"])
        )
    out.append(
        '<text class="dzsub" x="%.1f" y="%.1f">lowest %.2f</text>'
        % (pad_l, pad_t + step * len(rows) + 12, lo)
    )
    out.append(
        '<text class="dzsub" x="%.1f" y="%.1f" text-anchor="end">highest %.2f</text>'
        % (width - pad_r, pad_t + step * len(rows) + 12, hi)
    )
    out.append("</svg>")
    return "".join(out)


def share_split(parts, width=1180, height=64):
    """One bar split into named parts, each labelled with its own share."""
    total = sum(p[1] for p in parts) or 1.0
    x = 0.0
    out = ['<svg viewBox="0 0 %d %d" width="100%%" height="%d" role="img" '
           'aria-label="Split by share">' % (width, height, height)]
    for name, value, colour in parts:
        w = width * (value / total)
        out.append(
            '<rect x="%.1f" y="0" width="%.1f" height="26" fill="%s">'
            "<title>%s: %s of %s</title></rect>"
            % (x, max(1.0, w - 2), colour, name, n(value), n(total))
        )
        share = pct(100.0 * value / total)
        if w > 66:
            out.append(
                '<text class="dzann" x="%.1f" y="18" fill="#fff" '
                'text-anchor="middle">%s</text>' % (x + w / 2, share)
            )
            out.append(
                '<text class="dzsub" x="%.1f" y="44" text-anchor="middle">%s</text>'
                % (x + w / 2, name)
            )
        else:
            # Too narrow to print the share inside, and printing it beside the
            # segment lands it on top of the next one. It joins the label.
            out.append(
                '<text class="dzsub" x="%.1f" y="44">%s %s</text>'
                % (x, name, share)
            )
        x += w
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------
# how urgent is a state - colour is ALWAYS paired with the word
# --------------------------------------------------------------------------

URGENT = ("STOCK OUT - PLACE ORDER", "STOCK OUT - ORDER PLACED")
FIXABLE = ("STOCK OUT - AVAILABLE IN WAREHOUSE",
           "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE")
WATCH = ("ON THE VERGE OF STOCK OUT - PLACE ORDER",
         "ON THE VERGE OF STOCK OUT - ORDER PLACED",
         "OVERSTOCK", "NON MOVING", "IN STOCK BUT NO SALES",
         "IN STOCK BUT NO TRANSFERS")


def tone_for(state):
    if state in URGENT:
        return "crit", "Act now"
    if state in FIXABLE:
        return "warn", "Free fix"
    if state in WATCH:
        return "warn", "Watch"
    if state.startswith("STOCK AVAILABLE") and "UNKNOW" not in state:
        return "ok", "Healthy"
    return "faint", "No action"


def plain_state(state):
    """The model's own words, said plainly. Both are shown on the page."""
    return {
        "STOCK OUT - PLACE ORDER": "Shelf empty, nothing on order",
        "STOCK OUT - ORDER PLACED": "Shelf empty, more already ordered",
        "STOCK OUT - AVAILABLE IN WAREHOUSE": "Shelf empty, stock is in a warehouse",
        "ON THE VERGE OF STOCK OUT - PLACE ORDER": "Almost gone, nothing on order",
        "ON THE VERGE OF STOCK OUT - ORDER PLACED": "Almost gone, more already ordered",
        "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE":
            "Almost gone, stock is in a warehouse",
        "STOCK AVAILABLE": "On the shelf and selling",
        "STOCK AVAILABLE - REORDER LEVEL UNKNOW": "On the shelf, no reorder level set",
        "OVERSTOCK": "More on the shelf than needed",
        "NON MOVING": "Not selling at all",
        "IN STOCK BUT NO SALES": "On the shelf but not selling",
        "IN STOCK BUT NO TRANSFERS": "In stock, never sent to a shop",
        "NEW LISTED SKU": "Newly listed",
        "NOT ACTIVE": "No longer traded",
        "NA": "Not classified",
    }.get(state, state.title())


# --------------------------------------------------------------------------
# layer: overview
# --------------------------------------------------------------------------

def layer_overview(f, a, scope):
    m = f["meta"]
    t = a["totals"]
    so, rf = a["stockout"], a["refill"]
    do, su = a["dead_on_order"], a["surplus_on_order"]
    whole = f["all"]["totals"]

    if scope == "all":
        head = (
            "%s of your best-selling product lines have an empty shelf. "
            "That is about %s of sales a day you cannot make."
            % (n(so["rows"]), money(so["opp_day_usd"]))
        )
        lede = (
            "A further %s lines are close to running out &mdash; and for those the "
            "stock is already sitting in a warehouse, so they can be put back on "
            "the shelf today without buying anything."
            % n(rf["rows"])
        )
    else:
        head = (
            "Your best sellers are %s of all product lines but %s of everything sold."
            % (pct(100.0 * t["rows"] / whole["rows"]),
               pct(100.0 * t["sales_3m_usd"] / whole["sales_3m_usd"]))
        )
        lede = (
            "That is why a gap here matters more than a gap anywhere else. "
            "Every figure in this view counts only these products."
        )

    hero = (
        '<div class="hero"><div><span class="hero-tag">%s</span><h2>%s</h2>'
        "<p>%s</p></div>"
        '<div class="hero-stats">%s</div></div>'
        % (
            e("Stock position as at " + m["as_at_long"]),
            head,
            lede,
            "".join(
                '<div class="hs%s"><b>%s</b><span>%s</span></div>' % (c, v, e(s))
                for v, s, c in [
                    (n(so["rows"]), "best-seller lines with nothing on the shelf", ""),
                    (money(so["opp_day_usd"]),
                     "of sales missed every day on those lines", " crit"),
                    (n(rf["rows"]),
                     "lines a warehouse could refill today", ""),
                ]
            ),
        )
    )

    kpis = (
        '<div class="kpis">%s</div>'
        % "".join(
            [
                kpi("Products tracked", n(t["skus"]),
                    "across %s product-shop lines in %d shops"
                    % (n(t["rows"]), len(m["shops"]))),
                kpi("Stock on the shelf", big(t["stock_value_usd"]),
                    "%s units, valued at what it cost" % n(t["stock_qty"])),
                kpi("Sold, last 4 weeks", big(t["sales_1m_usd"]),
                    "%s over the last 3 months" % big(t["sales_3m_usd"])),
                kpi("Sales missed each day", money(t["opp_day_usd"]),
                    "across every line with an empty shelf", "crit",
                    pill("Act now", "crit")),
            ]
        )
    )

    # The lead chart carries the argument: what the report says to do next.
    states = [r for r in a["by_action"] if r["rows"] > 0][:10]
    peak = max(r["rows"] for r in states) if states else 1
    rows = []
    for r in states:
        tone, word = tone_for(r["name"])
        rows.append(
            (
                plain_state(r["name"]),
                r["name"],
                r["rows"] / peak,
                "%s<small>%s</small>" % (n(r["rows"]), word),
                tone,
            )
        )
    lead = card(
        "What the report says to do next",
        "Every product-shop line falls into one of these. The bar is how many "
        "lines, and the word beside it is how urgent &mdash; colour on its own "
        "never carries the meaning. The grey line under each name is what the "
        "model calls it.",
        rbars(rows),
        "",
    )

    # What each problem is worth, so the reader can see where to spend effort.
    worth = [
        ("Empty shelf, best sellers", "%s lines" % n(so["rows"]),
         so["sales_3m_usd"], "crit"),
        ("Almost gone, stock in a warehouse", "%s lines" % n(rf["rows"]),
         rf["sales_3m_usd"], "warn"),
        ("More on order than needed", "%s lines" % n(su["rows"]),
         su["pending_value_usd"], "warn"),
        ("On order but not selling", "%s lines" % n(do["rows"]),
         do["pending_value_usd"], "warn"),
    ]
    shelf, order = worth[:2], worth[2:]
    speak = max([w[2] for w in shelf] + [1.0])
    opeak = max([w[2] for w in order] + [1.0])
    worth_html = card(
        "What each problem is worth",
        "Two different measures, so they are drawn on two scales rather than "
        "one — putting them on the same bar would suggest they can be added "
        "together, and they cannot.",
        '<p class="mini-h">Sales at stake · what these products sold in 3 months</p>'
        + rbars([(lab, sub, v / speak, money(v), tone)
                 for lab, sub, v, tone in shelf])
        + '<p class="mini-h">Stock still to arrive · what it will cost</p>'
        + rbars([(lab, sub, v / opeak, money(v), tone)
                 for lab, sub, v, tone in order])
        + '<p class="note">The sales figures say what is at risk if the shelf '
          "stays empty, not what has already been lost.</p>",
    )

    sega, allv = f["sega"]["totals"], f["all"]["totals"]
    split = card(
        "Best sellers are a small part of the range and most of the sales",
        "The model sorts every product into four sales bands. The top band is "
        "called SEG_A. Both bars cover the same five shops.",
        share_split(
            [("Top band", sega["rows"], "#0f9f95"),
             ("Everything else", allv["rows"] - sega["rows"], "#cbd8dd")],
            width=520, height=64,
        )
        + '<p class="mini-h">Share of product lines</p>'
        + share_split(
            [("Top band", sega["sales_3m_usd"], "#0f9f95"),
             ("Everything else",
              allv["sales_3m_usd"] - sega["sales_3m_usd"], "#cbd8dd")],
            width=520, height=64,
        )
        + '<p class="mini-h">Share of sales, last 3 months</p>'
        + '<p class="note">One product line in nine is a best seller, and between '
          "them they bring in more than half of everything the shops sell.</p>",
    )

    return (
        hero
        + kpis
        + sect("The whole position",
               "%s · %d shops" % (m["as_at_long"], len(m["shops"])))
        + '<div class="grid">%s</div>' % lead
        + '<div class="grid g-2" style="margin-top:14px">%s%s</div>' % (worth_html, split)
        + page_caveats(f, a, scope)
    )


# --------------------------------------------------------------------------
# layer: one product in full
# --------------------------------------------------------------------------

STATE_WORD = {
    "empty": ("Shelf is empty", "crit"),
    "running out": ("Almost gone", "crit"),
    "stalled": ("Not selling", "warn"),
    "trading": ("Selling normally", "ok"),
}


def layer_product(f, scope):
    p = f["featured"]
    m = f["meta"]
    here = p["here"]

    empty = len(p["empty"])
    stalled = len(p["stalled"])
    running = len(p["running_out"])

    hero = (
        '<div class="hero"><div><span class="hero-tag">%s</span><h2>%s</h2>'
        "<p>%s</p></div>"
        '<div class="hero-stats">%s</div></div>'
        % (
            e("The largest gap on the shelf"),
            e("%s is the number one seller in its category — and %s has none of it."
              % (p["name"], p["home"])),
            e(
                "%d shops sell it. %s is empty, %s has %s days of stock left, and %s "
                "has not sold a single unit in %d days. The warehouse that would "
                "normally refill them is empty too."
                % (
                    p["shops_carrying"],
                    p["home"],
                    p["running_out"][0]["loc"] if running else "none",
                    n(p["running_out"][0]["burnout_days"]) if running else "0",
                    p["stalled"][0]["loc"] if stalled else "none",
                    int(SF.num(p["stalled"][0]["days_from_last_sale"])) if stalled else 0,
                )
            ),
            "".join(
                '<div class="hs%s"><b>%s</b><span>%s</span></div>' % (c, v, e(s))
                for v, s, c in [
                    (money(p["total_3m_usd"]), "sold over the last 3 months", ""),
                    (n(p["total_qty_3m"]), "units sold over the same 3 months", ""),
                    ("No. %s" % p["rank_in_category"],
                     "best seller in %s" % p["category"], ""),
                ]
            ),
        )
    )

    ident = (
        '<div class="idcard"><div><p class="lab">Product</p><p class="v">%s</p>'
        '<p class="c">%s</p></div>'
        '<div><p class="lab">Where it sits</p><p class="v">%s</p>'
        '<p class="c">%s &rsaquo; %s</p></div>'
        '<div><p class="lab">Sales band</p><p class="v">%s</p>'
        '<p class="c">the model\'s top band, called %s</p></div>'
        '<div><p class="lab">Bought from</p><p class="v">%s</p>'
        '<p class="c">brand %s</p></div></div>'
        % (
            e(p["name"]), e("product code " + p["sku"]),
            e(p["category"]), e(p["department"]), e(p["section"]),
            "Best seller", e(p["segment"]),
            e(p["supplier"]), e(p["brand"]),
        )
    )

    kpis = (
        '<div class="kpis">%s</div>'
        % "".join(
            [
                kpi("Sold, last 3 months", money(p["total_3m_usd"]),
                    "%s units across %d shops"
                    % (n(p["total_qty_3m"]), p["shops_carrying"])),
                kpi("Shops with an empty shelf", "%d of %d" % (empty, p["shops_carrying"]),
                    "%s has been out %d of the last 90 days"
                    % (here["loc"], int(SF.num(here["oos_days_3m"]))),
                    "crit", pill("Act now", "crit")),
                kpi("Sales missed each day at %s" % here["loc"],
                    money(here["opp_day_usd"], 2),
                    "the model's own estimate for this line", "crit"),
                kpi("Days of stock left at %s"
                    % (p["running_out"][0]["loc"] if running else "any shop"),
                    n(p["running_out"][0]["burnout_days"]) if running else "0",
                    "it holds %s of the %s units left across every shop"
                    % (n(p["running_out"][0]["stock_qty"]) if running else "0",
                       n(sum(SF.num(r["stock_qty"]) for r in p["shops"]))),
                    "crit", pill("Watch", "crit")),
            ]
        )
    )

    # The four-week run. Units, because the weekly table holds no money.
    weeks = []
    groups = []
    colours = {"ST1": "#0f9f95", "ST2": "#cf4636", "ST3": "#c08429",
               "ST4": "#087f79", "ST5": "#8fa1a9"}
    with_weeks = [r for r in p["shops"] if r["weekly"]]
    if with_weeks:
        weeks = [w["week_start"][:10] for w in with_weeks[0]["weekly"]]
        labels = ["w/c " + w[8:10] + " " + MONTHS[int(w[5:7]) - 1] for w in weeks]
        for r in sorted(with_weeks, key=lambda r: r["loc"]):
            byweek = {w["week_start"][:10]: SF.num(w["qty"]) for w in r["weekly"]}
            groups.append((r["loc"], [byweek.get(w) for w in weeks],
                           colours.get(r["loc"], "#0f9f95")))
    no_weeks = [r["loc"] for r in p["shops"] if not r["weekly"]]

    run_note = (
        "%s sold %s units in the week beginning %s and %s units in the week "
        "beginning %s — a fall of %s. It ran out during that run."
        % (here["loc"], n(p["run_first"]), labels[0][4:] if with_weeks else "",
           n(p["run_last"]), labels[-1][4:] if with_weeks else "",
           pct(abs(p["run_drop_pct"])) if p["run_drop_pct"] is not None else "n/a")
    )
    if no_weeks:
        run_note += (
            " %s does not appear on this chart at all, because it recorded no "
            "sale of this product in any of the four weeks." % ", ".join(no_weeks)
        )

    lead = card(
        "Units sold each week, shop by shop",
        "The four weeks the model keeps. Bars are units, not money &mdash; the "
        "weekly table holds quantity only. Four weeks is a short run, so read "
        "this as the recent shape and not as a long-term trend.",
        columns_chart({"labels": labels, "groups": groups}) if groups
        else '<p class="note">No weekly sales were recorded for this product.</p>',
    ) + '<p class="note">%s</p>' % e(run_note)

    # The same product, three shops, three different problems.
    rows = []
    for r in p["shops"]:
        word, tone = STATE_WORD[r["state"]]
        last = r["days_from_last_sale"]
        rows.append([
            ("<b>%s</b>" % e(r["loc"]), ""),
            (pill(word, tone) + '<small class="act">%s</small>' % e(r["action"]), ""),
            (n(r["stock_qty"]), "n"),
            (n(r["burnout_days"]) if SF.num(r["burnout_days"]) else "&mdash;", "n"),
            (money(r["sales_3m_usd"]), "n"),
            ("%d days ago" % int(SF.num(last)) if last is not None else "&mdash;", "n"),
        ])
    shops_tbl = card(
        "The same product, %d shops, %d different problems"
        % (p["shops_carrying"], len({r["state"] for r in p["shops"]})),
        "This is the whole point of looking at one product: the answer is not "
        "the same in every shop, so one instruction to the buying team would be "
        "wrong in two of the three.",
        table(
            [("Shop", False), ("What is happening", False), ("Units left", True),
             ("Days of stock", True), ("Sold, 3 months", True), ("Last sold", True)],
            rows, min_width=620,
        ),
    )

    # Price, against the range the window has seen.
    ptrack = [
        {"loc": r["loc"], "now": SF.num(r["price_local"]),
         "lo": min(SF.num(b["min_rp_local"]) for b in r["best_days"]),
         "hi": max(SF.num(b["max_rp_local"]) for b in r["best_days"])}
        for r in p["shops"] if r["price_local"] and r["best_days"]
    ]
    price_notes = []
    for r in ptrack:
        shop = next((s for s in p["shops"] if s["loc"] == r["loc"]), None)
        at_top = r["hi"] > r["lo"] and (r["now"] - r["lo"]) / (r["hi"] - r["lo"]) >= 0.9
        if at_top and shop and shop["state"] == "stalled":
            price_notes.append(
                "<b>%s is charging the most it has charged for this product in "
                "the window (%s, against a low of %s) and has not sold one for "
                "%d days.</b> Those are two separate facts. This report cannot "
                "tell you whether the price is the reason — it holds no "
                "record of what the price was on any given day."
                % (r["loc"], n(r["now"], 2), n(r["lo"], 2),
                   int(SF.num(shop["days_from_last_sale"])))
            )
    price_card = card(
        "The price it sells at, against its own range",
        "The bar is the range this shop has charged over the last 90 days; the "
        "dot is the price today. Prices are in the local currency the model "
        "stores them in, not USD — the model does not convert them.",
        (price_track(ptrack) if ptrack
         else '<p class="note">No current price is held for these shops.</p>')
        + "".join('<p class="note">%s</p>' % x for x in price_notes),
    )

    # What to do, tied to the counts.
    actions = []
    if empty:
        actions.append(
            "<b>Order it for %s.</b> The shelf is empty, nothing is on order, "
            "and the warehouse cannot cover it. The supplier takes about %d days."
            % (here["loc"], int(SF.num(here["lead_days"])))
            if SF.num(here["lead_days"]) else
            "<b>Order it for %s.</b> The shelf is empty, nothing is on order, "
            "and the warehouse cannot cover it." % here["loc"]
        )
    if running:
        r = p["running_out"][0]
        actions.append(
            "<b>Order it for %s too.</b> It has %s units left, about %s days of "
            "selling, and it holds all but %s of the units left anywhere."
            % (r["loc"], n(r["stock_qty"]), n(r["burnout_days"]),
               n(sum(SF.num(x["stock_qty"]) for x in p["shops"])
                 - SF.num(r["stock_qty"])))
        )
    if stalled:
        r = p["stalled"][0]
        actions.append(
            "<b>Ask what happened at %s.</b> It sold %s of this product over three "
            "months &mdash; more than any other shop &mdash; and has now sold none "
            "for %d days, with %s unit left on the shelf."
            % (r["loc"], money(r["sales_3m_usd"]),
               int(SF.num(r["days_from_last_sale"])), n(r["stock_qty"]))
        )
    best = p["best_day"]
    if best:
        actions.append(
            "<b>For scale:</b> the best single day this product has had in the "
            "window was %s units at %s on %s, worth %s."
            % (n(best["qty"]), best["loc"], long_date(best["date"][:10]),
               money(best["value_usd"]))
        )
    todo = card(
        "What to do next",
        "Each line below is tied to a figure in the tables above. Nothing here "
        "says why the sales changed &mdash; the report cannot see that.",
        '<ul class="todo">%s</ul>' % "".join("<li>%s</li>" % a for a in actions),
    )

    peers_rows = [
        [
            ("<b>%s</b>" % e(pr["name"]) if pr["is_this"] else e(pr["name"]), ""),
            (money(pr["sales_3m_usd"]), "n"),
            (n(pr["qty_3m"]), "n"),
            (n(pr["stock_qty"]), "n"),
        ]
        for pr in p["peers"]
    ]
    peers = card(
        "How it compares with the rest of its category",
        "Every product in %s, across the five shops, over the last 3 months. "
        "This product is in bold." % p["category"],
        table(
            [("Product", False), ("Sold, 3 months", True), ("Units", True),
             ("Units on shelf now", True)],
            peers_rows, min_width=520,
        ),
    )

    scoped_note = ""
    if scope == "top":
        scoped_note = (
            '<div class="scoped">This product is itself a best seller, so this '
            "section is the same in both views.</div>"
        )

    return (
        scoped_note
        + hero
        + ident
        + kpis
        + sect("How it is selling", "the four weeks the model keeps")
        + '<div class="grid">%s</div>' % lead
        + sect("Where it stands right now", "one product, shop by shop")
        + '<div class="grid g-2">%s%s</div>' % (shops_tbl, price_card)
        + '<div class="grid g-2" style="margin-top:14px">%s%s</div>' % (todo, peers)
    )


# --------------------------------------------------------------------------
# layer: what is selling
# --------------------------------------------------------------------------

def layer_selling(f, a, scope):
    m = f["meta"]
    cards = []
    for dept, rows in sorted(a["top_sellers"].items()):
        if not rows:
            cards.append(card(dept.title(), "No product in this department "
                              "recorded a sale in the last 4 weeks.", ""))
            continue
        cats = {r["category"] for r in rows}
        body = table(
            [("Product", False), ("Category", False),
             ("Sold, 4 weeks", True), ("Units", True)],
            [
                [
                    ('<span class="rank%s">%d</span> %s'
                     % (" r1" if i == 0 else "", i + 1, e(r["name"])), ""),
                    (e(r["category"]), "c"),
                    (money(r["sales_1m_usd"]), "n good" if i == 0 else "n"),
                    (n(r["qty_1m"]), "n"),
                ]
                for i, r in enumerate(rows)
            ],
            min_width=460,
        )
        note = ""
        if len(cats) == 1:
            note = ('<p class="note">All three come from one category, %s.</p>'
                    % e(list(cats)[0]))
        cards.append(card(dept.title(),
                          "The three products that sold the most in the last "
                          "4 weeks, added up across the shops that carry them.",
                          body + note))

    best = '<div class="grid g-2e">%s</div>' % "".join(cards)

    # Rule 3 - yesterday's standouts.
    st_rows = [
        [
            (e(r["name"]), ""),
            (e(r["category"]), "c"),
            ('<span class="store">%s</span>' % e(r["loc"]), ""),
            (money(r["value_usd"], 2), "n good" if i == 0 else "n"),
            (n(r["qty"]), "n"),
        ]
        for i, r in enumerate(a["standouts"])
    ]
    standouts = card(
        "Products that had their best day yesterday",
        "Every product has a best day somewhere in the last 90 days. These had "
        "theirs on %s. In total %s product-shop lines did, worth %s."
        % (m["yesterday_long"], n(a["standout_pairs"]),
           money(a["standout_value_usd"])),
        table(
            [("Product", False), ("Category", False), ("Shop", False),
             ("Sold that day", True), ("Units", True)],
            st_rows, min_width=620,
        )
        + '<p class="note"><b>Read this the right way.</b> These are not the '
        "biggest sellers. A product only appears if yesterday beat every other "
        "day it has had in the window, so steady high-volume lines &mdash; bulk "
        "rice, cooking oil &mdash; usually peaked weeks ago on a big restock day "
        "and never show up here. Use it to spot a one-off spike worth asking "
        "about, not as a sales league table.</p>",
    )

    # Rule 2 - honestly absent.
    pending = (
        '<div class="pendcard"><div class="pend-h"><h3>Which products climbed or '
        'fell in their category</h3>%s</div>'
        '<div class="pend-b">'
        "<div><p>This would answer: <em>which product just became the number one "
        "seller in its category, and which one just dropped off the top?</em> "
        "It needs two readings taken at different times — today&rsquo;s "
        "position against last month&rsquo;s.</p>"
        "<p><b>Why it is not here.</b> The model works out each "
        "product&rsquo;s position in its category as it stands today, but it "
        "keeps no record of what that position was a week or a month ago. There "
        "is nothing to compare today against. That is a gap in what is being "
        "saved, not a gap in the analysis.</p></div>"
        "<div><p><b>What would fix it.</b> Save that position for every product "
        "once a week into a table of its own. About a month after that starts, "
        "this section can show two lists: products newly at number one, and "
        "products that have just lost it.</p>"
        "<p>Until then it stays empty rather than being filled with a stand-in "
        "figure that would read as fact. The same is true of the four weeks of "
        "weekly units the model does keep — useful for shape, too short to "
        "call a trend.</p></div></div></div>"
        % pill("Not available yet", "neutral")
    )

    return (
        sect("The best sellers in each department",
             "last 4 weeks · %d departments" % m["departments"])
        + best
        + sect("A single strong day", m["yesterday_long"])
        + '<div class="grid">%s</div>' % standouts
        + sect("One thing this report cannot answer yet", "and what would fix it")
        + '<div class="grid">%s</div>' % pending
    )


# --------------------------------------------------------------------------
# layer: what needs action
# --------------------------------------------------------------------------

def _shop_bars(rows, value_key, label):
    if not rows:
        return ""
    peak = max(SF.num(r.get(value_key)) for r in rows) or 1.0
    return (
        '<p class="mini-h">%s</p>' % e(label)
        + rbars([
            (r["loc"], "%s lines" % n(r["rows"]),
             SF.num(r.get(value_key)) / peak,
             money(SF.num(r.get(value_key))),
             "crit" if i == 0 and len(rows) > 1
             and SF.num(rows[0].get(value_key)) > 2 * SF.num(rows[1].get(value_key))
             else "warn")
            for i, r in enumerate(rows)
        ])
    )


def _concentration(rows, noun):
    """Say plainly when one shop owns a problem - it changes who to talk to."""
    if len(rows) < 2:
        return ""
    total = sum(r["rows"] for r in rows)
    top = rows[0]
    share = 100.0 * top["rows"] / total if total else 0.0
    if share < 60.0:
        return (
            '<div class="spot"><p class="l">Spread across the shops</p><p>These '
            "%s are not concentrated in one shop &mdash; the largest share is %s "
            "at %s. Treat them as separate cases rather than as one process "
            "problem.</p></div>" % (e(noun), pct(share), e(top["loc"]))
        )
    return (
        '<div class="spot"><p class="l">One shop owns this</p><p>%s of the %s '
        "%s sit at <b>%s</b> &mdash; %s of them. That points at one shop&rsquo;s "
        "ordering routine rather than at %s separate mistakes.</p></div>"
        % (n(top["rows"]), n(total), e(noun), e(top["loc"]), pct(share), n(total))
    )


SHOW_ROWS = 10


def more_note(shown, total):
    """Say what a table is not showing, rather than quietly truncating."""
    if total <= shown:
        return ""
    return ('<p class="note">Showing the %s largest of %s. The full list is in '
            "the report itself.</p>" % (n(min(shown, SHOW_ROWS)), n(total)))


def layer_action(f, a, scope):
    so, rf = a["stockout"], a["refill"]
    do, su = a["dead_on_order"], a["surplus_on_order"]

    # 4 - empty shelf on a best seller
    so_rows = [
        [
            (e(r["name"]), ""),
            (e(r["category"]), "c"),
            ('<span class="store">%s</span>' % e(r["loc"]), ""),
            (money(r["sales_3m_usd"]), "n crit"),
            (n(r["qty_3m"]), "n"),
            (n(r["oos_days"]), "n"),
        ]
        for r in so["list"]
    ]
    c4 = card(
        "Best sellers with an empty shelf",
        "%s product-shop lines, covering %s products. Between them they sold %s "
        "over the last 3 months, and the model puts the sales now being missed "
        "at %s a day."
        % (n(so["rows"]), n(so["skus"]), money(so["sales_3m_usd"]),
           money(so["opp_day_usd"])),
        table(
            [("Product", False), ("Category", False), ("Shop", False),
             ("Sold, 3 months", True), ("Units", True), ("Days out, 90", True)],
            so_rows, min_width=680,
        )
        + '<p class="note">The daily figure covers only the %s lines of %s that '
        "carry an estimate &mdash; the model does not work one out for every "
        "empty shelf. A blank is not a zero, so the real figure is higher than "
        "this.</p>" % (n(so["with_estimate"]), n(so["of_rows"])),
    )

    # 5 - the free fix
    rf_rows = [
        [
            (e(r["name"]), ""),
            (e(r["category"]), "c"),
            ('<span class="store">%s</span>' % e(r["loc"]), ""),
            (n(r["stock_qty"]), "n"),
            (n(r["burnout"]), "n"),
            (money(r["sales_3m_usd"]), "n"),
        ]
        for r in rf["list"]
    ]
    c5 = card(
        "Almost gone — but the stock already exists",
        "%s lines are close to running out while the same product is sitting in "
        "a warehouse. Nothing needs buying; it needs moving. Between them they "
        "sold %s over the last 3 months."
        % (n(rf["rows"]), money(rf["sales_3m_usd"])),
        table(
            [("Product", False), ("Category", False), ("Shop", False),
             ("Units left", True), ("Days of stock", True), ("Sold, 3 months", True)],
            rf_rows, min_width=680,
        )
        + _shop_bars(rf["by_store"], "sales_3m_usd",
                     "Sales at stake, by shop"),
    )

    # 6 - not selling, more coming
    if do["rows"]:
        do_rows = [
            [
                (e(r["name"]), ""),
                (e(r["category"]), "c"),
                ('<span class="store">%s</span>' % e(r["loc"]), ""),
                (n(r["pending"]), "n"),
                (money(r["pending_value_usd"]), "n crit"),
                (n(r["days_no_sale"]) if r["days_no_sale"] is not None
                 else "&mdash;", "n"),
            ]
            for r in do["list"][:SHOW_ROWS]
        ]
        c6body = table(
            [("Product", False), ("Category", False), ("Shop", False),
             ("Units on order", True), ("Value on order", True),
             ("Days since last sale", True)],
            do_rows, min_width=700,
        ) + more_note(len(do["list"]), do["rows"]) + _concentration(do["by_store"], "orders")
    else:
        c6body = ('<p class="none">No product in this view has stopped selling '
                  "while more is still on order. That is the result you want "
                  "here.</p>")
    c6 = card(
        "Ordering more of something that is not selling",
        "%s lines have recorded no sale at all and still have a purchase order "
        "outstanding, worth %s. Small in number, but it is money about to be "
        "spent on stock that has already shown it does not move."
        % (n(do["rows"]), money(do["pending_value_usd"])),
        c6body,
    )

    # 7 - too much already, more coming
    su_rows = [
        [
            (e(r["name"]), ""),
            (e(r["category"]), "c"),
            ('<span class="store">%s</span>' % e(r["loc"]), ""),
            (money(r["excess_value_usd"]), "n crit"),
            (n(r["excess_qty"]), "n"),
            (money(r["pending_value_usd"]), "n"),
        ]
        for r in su["list"]
    ]
    c7 = card(
        "Ordering more of something there is already too much of",
        "%s lines already hold more than the shop needs, and more is on the way "
        "&mdash; %s of surplus on the shelf with a further %s still to arrive."
        % (n(su["rows"]), money(su["excess_value_usd"]),
           money(su["pending_value_usd"])),
        table(
            [("Product", False), ("Category", False), ("Shop", False),
             ("Surplus value", True), ("Surplus units", True), ("On order", True)],
            su_rows, min_width=680,
        )
        + _concentration(su["by_store"], "orders")
        + '<p class="note">Surplus means only the part above what the shop is '
        "meant to hold, never the whole value sitting there. The whole holding "
        "on these lines is %s.</p>" % money(su["stock_value_usd"]),
    )

    # 8 - marked down
    md_rows = [
        [
            (e(r["name"]), ""),
            ('<span class="store">%s</span>' % e(r["loc"]), ""),
            (n(r["rp_local"], 2), "n"),
            (n(r["max_rp_local"], 2), "n"),
            (money(r["sales_3m_usd"]), "n"),
        ]
        for r in a["markdowns"]
    ]
    c8 = card(
        "Products now at their lowest price in 90 days",
        "A genuine markdown, not a rounding difference: the price has moved by "
        "more than 3% across the window and today sits at the bottom of it.",
        table(
            [("Product", False), ("Shop", False), ("Price now", True),
             ("Highest it has been", True), ("Sold, 3 months", True)],
            md_rows, min_width=560,
        )
        + '<p class="note"><b>What this does and does not show.</b> It confirms '
        "the price is genuinely lower than it has been. It does not show that "
        "the lower price is why these products are selling &mdash; some of them "
        "(fresh milk, chicken) sell steadily at almost any price. Prices here "
        "are in the local currency the model stores, not USD.</p>",
    )

    return (
        sect("Shelves with a gap", "the two problems that cost sales")
        + '<div class="grid">%s</div>' % c4
        + '<div class="grid" style="margin-top:14px">%s</div>' % c5
        + sect("Orders that look wrong", "money about to be spent")
        + '<div class="grid">%s</div>' % c6
        + '<div class="grid" style="margin-top:14px">%s</div>' % c7
        + sect("Prices", "what is currently marked down")
        + '<div class="grid">%s</div>' % c8
    )


# --------------------------------------------------------------------------
# layer: every department and shop
# --------------------------------------------------------------------------

def layer_detail(f, a, scope):
    dep_rows = [
        [
            (e(r["name"].title()), ""),
            (n(r["skus"]), "n"),
            (n(r["rows"]), "n"),
            (money(r["sales_1m_usd"]), "n"),
            (money(r["sales_3m_usd"]), "n"),
            (money(r["stock_value_usd"]), "n"),
            (money(r["excess_value_usd"]), "n"),
        ]
        for r in a["by_department"]
    ]
    deps = card(
        "Every department",
        "All %d departments, biggest seller first. Nothing is left out."
        % len(a["by_department"]),
        table(
            [("Department", False), ("Products", True), ("Product-shop lines", True),
             ("Sold, 4 weeks", True), ("Sold, 3 months", True),
             ("Stock on shelf", True), ("Surplus", True)],
            dep_rows, min_width=760,
        ),
    )

    shop_rows = [
        [
            ('<span class="store">%s</span>' % e(r["name"]), ""),
            (n(r["skus"]), "n"),
            (money(r["sales_1m_usd"]),
             "n crit" if r["sales_1m_usd"] == 0 else "n"),
            (money(r["sales_3m_usd"]), "n"),
            (money(r["stock_value_usd"]), "n"),
            (money(r["excess_value_usd"]), "n"),
        ]
        for r in a["by_store"]
    ]
    quiet = [r for r in a["by_store"]
             if r["sales_1m_usd"] == 0 and r["sales_3m_usd"] > 0]
    quiet_note = ""
    if quiet:
        q = quiet[0]
        quiet_note = (
            '<div class="spot"><p class="l">One shop has gone quiet</p><p>'
            "<b>%s recorded no sales at all in the last 4 weeks</b>, having "
            "sold %s over the 3 months before that. It still holds %s of stock "
            "and %s products. This report cannot say why &mdash; only that the "
            "shop has stopped recording sales. Worth confirming whether it is "
            "closing, or whether its sales have stopped reaching this report."
            "</p></div>"
            % (e(q["name"]), money(q["sales_3m_usd"]),
               money(q["stock_value_usd"]), n(q["skus"]))
        )
    shops = card(
        "Every shop",
        "The five selling locations. The two warehouses are not here — "
        "they hold stock but do not sell, so putting them in a sales table "
        "would overstate the business. Each product appears once per shop, so "
        "the product count is also the line count.",
        table(
            [("Shop", False), ("Products", True),
             ("Sold, 4 weeks", True), ("Sold, 3 months", True),
             ("Stock on shelf", True), ("Surplus", True)],
            shop_rows, min_width=700,
        )
        + quiet_note
        + '<p class="note">Warehouses, for reference: %s. They are counted '
          "nowhere else on this page.</p>"
        % "; ".join(
            "%s holds %s across %s lines"
            % (e(w["name"]), money(w["stock_value_usd"]), n(w["rows"]))
            for w in f["warehouses"]
        ),
    )

    act_rows = []
    for r in a["by_action"]:
        tone, word = tone_for(r["name"])
        act_rows.append([
            (e(plain_state(r["name"])) + '<small class="act">%s</small>' % e(r["name"]), ""),
            (pill(word, "crit" if tone == "crit" else
                  ("ok" if tone == "ok" else "neutral")), ""),
            (n(r["rows"]), "n"),
            (money(r["sales_3m_usd"]), "n"),
            (money(r["stock_value_usd"]), "n"),
        ])
    acts = card(
        "Every instruction the report gives",
        "All %d states that appear in the shops, most lines first. This is the "
        "full list behind the chart on the Overview — nothing is hidden "
        "behind a top ten. One further state, <em>in stock but never sent to a "
        "shop</em>, appears only at the warehouses and so is not counted here."
        % len(a["by_action"]),
        table(
            [("What to do next", False), ("Urgency", False), ("Lines", True),
             ("Sold, 3 months", True), ("Stock on shelf", True)],
            act_rows, min_width=680,
        ),
    )

    return (
        sect("Departments", "every one, with nothing rolled up")
        + '<div class="grid">%s</div>' % deps
        + sect("Shops", "the five selling locations")
        + '<div class="grid">%s</div>' % shops
        + sect("The full instruction list", "every state the model publishes")
        + '<div class="grid">%s</div>' % acts
    )


# --------------------------------------------------------------------------
# one caveats block, at the end of the layer that owns it
# --------------------------------------------------------------------------

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def long_date(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return "%d %s %d" % (d, MONTHS_LONG[m - 1], y)


def page_caveats(f, a, scope):
    m = f["meta"]
    so = a["stockout"]
    items = [
        "<b>This is one day&rsquo;s position, not a trend.</b> Every figure is "
        "the state of the shelves on %s. The only history the model keeps is "
        "four weeks of weekly units and the best sales days of the last 90 "
        "days." % e(m["as_at_long"]),

        "<b>The figures cover the five shops only</b> (%s). The two warehouses "
        "hold stock but do not sell, so they are never added into a sales or "
        "shelf total. They appear only where a warehouse is the fix for a shop "
        "problem." % ", ".join(m["shops"]),

        "<b>Money on this page is US dollars, and the model does not store it "
        "that way throughout.</b> Stock, surplus and on-order values arrive "
        "already converted. Sales values and the missed-sales estimate arrive "
        "in the local currency, and are converted here at the same rate the "
        "model itself uses (%.2f) so that everything on the page can be "
        "compared. Shelf prices are shown in the local currency and are "
        "labelled where they appear." % m["rate"],

        "<b>The missed-sales figure is a daily rate, not a running total.</b> "
        "It is what the model estimates is being lost each day the shelf stays "
        "empty. It is not the amount lost so far, and it is only worked out for "
        "%s of the %s empty best-seller lines &mdash; a blank is not a zero, so "
        "the true figure is higher." % (n(so["with_estimate"]), n(so["of_rows"])),

        "<b>The Inventory Management report states this same figure differently.</b> "
        "That report publishes it without the conversion applied here, so the two "
        "reports will not agree on it. The underlying column is the same one.",

        "<b>Product positions within a category cannot be compared over time.</b> "
        "The model works out today&rsquo;s position but keeps no record of past "
        "ones, so the climbers-and-fallers section is empty rather than estimated.",

        "<b>A product&rsquo;s best-day list is not a sales league table.</b> "
        "A product appears there only if yesterday beat all its own recent days, "
        "which favours smaller, less predictable lines over steady big sellers.",

        "<b>Stock is valued at what it cost, sales at what they sold for.</b> "
        "The two are not the same measure and the page never adds one to the other.",

        "<b>Prices can be shown as low but not dated.</b> The model holds the "
        "highest and lowest price over the window with no date attached, so the "
        "page can say a price has moved and is currently at the bottom of its "
        "range, but not when it changed.",
    ]
    if scope == "top":
        items.insert(
            1,
            "<b>This view counts only the top sales band</b> (the model calls it "
            "%s). Every table and every total has been worked out again over "
            "just those products, so the rows on this page add up to the totals "
            "on this page. The empty-shelf section is the same in both views "
            "because it only ever covered best sellers."
            % f["sega"]["totals"].get("_band", "SEG_A"),
        )
    return caveats(items)


# --------------------------------------------------------------------------
# a view, and the page
# --------------------------------------------------------------------------

def build_view(f, scope):
    a = f["all"] if scope == "all" else f["sega"]
    banner = ""
    if scope == "top":
        banner = (
            '<div class="scoped">This view keeps only the products in the '
            "model&rsquo;s top sales band. Every figure below, including the "
            "totals, has been worked out again over just those products.</div>"
        )
    layers = {
        "overview": layer_overview(f, a, scope),
        "product": layer_product(f, scope),
        "selling": layer_selling(f, a, scope),
        "action": layer_action(f, a, scope),
        "detail": layer_detail(f, a, scope),
    }
    parts = []
    for i, (key, _label) in enumerate(LAYERS):
        # The product layer states its own scoping, so the generic banner there
        # would be a second caution saying almost the same thing - two stacked
        # amber boxes read as a broken page rather than as one caveat.
        head = "" if key == "product" else banner
        parts.append(
            '<div class="layer" data-layer="%s"%s>%s%s</div>'
            % (key, "" if i == 0 else " hidden", head, layers[key])
        )
    return (
        '<div class="view" data-view="%s"%s>%s</div>'
        % (scope, "" if scope == "all" else " hidden", "".join(parts))
    )


def render(f):
    m = f["meta"]
    rail_layers = "".join(
        '<button data-nav="%s"%s>%s</button>'
        % (k, ' aria-current="true"' if i == 0 else "", e(lab))
        for i, (k, lab) in enumerate(LAYERS)
    )
    rail_views = "".join(
        '<button data-viewbtn="%s"%s>%s</button>'
        % (k, ' aria-current="true"' if i == 0 else "", e(lab))
        for i, (k, lab) in enumerate(VIEWS)
    )
    seg = "".join(
        '<button data-viewbtn="%s" aria-pressed="%s">%s</button>'
        % (k, "true" if i == 0 else "false", e(lab))
        for i, (k, lab) in enumerate(VIEWS)
    )
    return TEMPLATE % {
        "css": CSS,
        "script": SCRIPT,
        "rail_layers": rail_layers,
        "rail_views": rail_views,
        "seg": seg,
        "as_at": e(m["as_at_long"]),
        "shops": e(", ".join(m["shops"])),
        "views": "".join(build_view(f, k) for k, _ in VIEWS),
        "footer_left": e("SKU Overview · report %s" % m["report"][:8]),
        "footer_right": e("Reference design · figures are the live "
                          "position on %s" % m["as_at_long"]),
    }


def main():
    f = SF.facts()
    f["meta"]["as_at_long"] = long_date(f["meta"]["as_at"])
    f["meta"]["yesterday_long"] = long_date(f["meta"]["yesterday"])
    html_text = render(f)
    OUT.write_text(html_text, encoding="utf-8")

    # Assertions that must hold in the produced page, checked as it is written.
    assert html_text.count("<script") == 1, "exactly one script tag"
    assert "SAR" not in html_text and "QAR" not in html_text, "no other currency"
    for k, _ in LAYERS:
        assert 'data-layer="%s"' % k in html_text, k
    print("wrote %s (%d KB, %d checks passed in facts)"
          % (OUT.name, len(html_text.encode("utf-8")) // 1024, len(f["checks"])))


if __name__ == "__main__":
    main()
