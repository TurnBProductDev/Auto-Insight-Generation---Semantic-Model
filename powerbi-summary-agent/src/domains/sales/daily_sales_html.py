"""Renders the Daily Sales page model to HTML.

The stylesheet is the client-approved reference design's
(`docs/dashboard-reference/reference_daily_sales.html`) carried verbatim, so
the shipped page is the approved page rather than something that merely
resembles it. Two faults found by rendering the previous version and looking
at it are pinned by `scripts/replay_daily_sales.py` and worth naming here,
because both were invisible to tests that only checked for strings:

  * `.hero` is a two-column GRID. Emitting the headline and the stat block
    as bare children of a non-grid `.hero` put the stats under the prose and
    lost the whole right-hand column. The skeleton assertion is `.hero`
    holds exactly two children, the second being `.hero-stats`.
  * `.app` is `display:flex` - a ROW - whose only children may be
    `nav.rail` and `main`. Anything else laid out as another column.

Self-contained: no external request, no build step, one `<script>` tag (two
nested ones kill every handler on the page, which is how the inventory
dashboard once shipped with a dead nav).
"""

from __future__ import annotations

from html import escape as _e

_STYLE = """
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
.hs.good b{color:#7fd6a0}

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
.mini-h:first-child{margin-top:0}

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
.bul{display:block;margin:2px 0 4px}

.pill{display:inline-block;font-size:9px;font-weight:750;letter-spacing:.05em;
  text-transform:uppercase;padding:2px 6px;border-radius:5px}
.pill-crit{background:var(--red-tint);color:var(--red)}
.pill-ok{background:var(--green-tint);color:var(--green)}
.pill-neutral{background:#eef2f6;color:var(--muted)}

.mrs{display:flex;flex-direction:column;gap:10px}
.mr{display:grid;grid-template-columns:122px minmax(64px,1fr) 152px;gap:12px;
  align-items:center;font-size:12px;min-width:0}
.mr-b{min-width:0}
.mr-l{font-weight:650}
.mr-l small{display:block;font-weight:400;font-size:10px;color:var(--muted);line-height:1.35}
.mr-v{text-align:right;font-weight:750;font-size:13px;white-space:nowrap;min-width:0}
.mr-v small{display:block;font-weight:500;font-size:10px;color:var(--muted);line-height:1.35;
  white-space:normal}
.mr-v.crit{color:var(--red)} .mr-v.good{color:var(--green)}
.mr-v .pill{margin-top:4px}

.minis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.mini{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:var(--soft)}
.mini b{display:block;font-size:14px;font-weight:750}
.mini>span{display:block;font-size:11.5px;color:var(--mid);margin-top:3px}
.mini>span.pill{display:inline-block;font-size:9px;color:inherit}
.mini .act{color:var(--faint);font-size:11px}
.mini .pill{margin-top:8px}

.rbars{display:flex;flex-direction:column;gap:9px}
.rb{display:grid;grid-template-columns:160px minmax(0,1fr) 128px;gap:11px;align-items:center;
  font-size:12px}
.rb-l{font-weight:650;overflow:hidden;text-overflow:ellipsis}
.rb-l small{display:block;font-weight:400;font-size:10px;color:var(--muted)}
.rb-t{background:#eef2f6;border-radius:99px;height:10px;position:relative}
.rb-tick{position:absolute;top:-3px;bottom:-3px;width:1.6px;background:var(--mid);
  opacity:.6;border-radius:2px}
.rb-f{display:block;height:100%;border-radius:99px}
.rb-v{text-align:right;font-weight:700}
.rb-v small{display:block;font-weight:500;font-size:10px}

.scroll{overflow-x:auto;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:12px;min-width:640px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
  font-weight:700;white-space:nowrap}
td.n,th.n{text-align:right;white-space:nowrap}
td.crit{color:var(--red);font-weight:700} td.good{color:var(--green);font-weight:700}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--soft)}
tr.urgent td{background:var(--red-tint)}
.act{color:var(--faint);font-size:11px;font-weight:400}

.dz{fill:var(--faint);font-size:9px} .dzv{fill:var(--ink);font-size:10.5px;font-weight:700}
.dzday{fill:var(--mid);font-size:10.5px;font-weight:650}
.dzsub{fill:var(--faint);font-size:9.5px}
.dza{fill:var(--teal-dk);font-size:9.5px;font-weight:650}
.dzann{font-size:10.5px;font-weight:750}

.caveats{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--faint);
  border-radius:var(--r);padding:15px 18px;margin-top:20px}
.caveats h3{font-size:12px;font-weight:700;margin-bottom:9px}
.caveats ul{margin:0;padding-left:17px;color:var(--mid);font-size:11.5px;line-height:1.6}
.caveats li{margin-bottom:5px}
.pagefoot{margin-top:18px;padding-top:12px;border-top:1px solid var(--line);
  display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;
  font-size:10.5px;color:var(--faint)}

@media (max-width:1080px){
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .g-2,.g-2e,.minis{grid-template-columns:minmax(0,1fr)}
  .hero{grid-template-columns:minmax(0,1fr)}
  .mr{grid-template-columns:110px minmax(0,1fr)}
  .mr-b{display:none}
}
@media (max-width:720px){.rail{display:none}}
@media print{
  .rail,.seg{display:none}.app{display:block}.card,.kpi,.hero{break-inside:avoid;box-shadow:none}
  body{background:#fff}
}

.layer[hidden],.view[hidden]{display:none}
.scoped{background:var(--amber-tint);border:1px solid #e8d3a8;border-radius:var(--r);
  padding:11px 15px;font-size:11.5px;color:var(--amber-dk);margin-bottom:14px}
@media print{.layer[hidden],.view[hidden]{display:block}}
"""

_SCRIPT = """
(function(){
  var LAYERS = ['day','stores','departments','detail'];
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
  var current = {view: 'all', layer: 'day'};
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
"""

_TONE_FILL = {"crit": "#cf4636", "good": "#2f8f4e", "neutral": "#12201e", None: "#12201e"}


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------

def _card(title: str, sub: str, body: str, note: str = "", *, title_html: str = "") -> str:
    """`title` is escaped; `title_html` is for the few headings that carry an
    em dash entity, and is never built from data."""
    head = f"<h3>{title_html or _e(title)}</h3>" if (title or title_html) else ""
    subtitle = f'<p class="sub">{_e(sub)}</p>' if sub else ""
    tail = f'<p class="note">{_e(note)}</p>' if note else ""
    return f'<div class="card">{head}{subtitle}{body}{tail}</div>'


def _sect(title: str, note: str) -> str:
    return f'<div class="sect"><h2>{_e(title)}</h2><span>{_e(note)}</span></div>'


def _pill(pill: str, word: str) -> str:
    return f'<span class="pill {_e(pill)}">{_e(word)}</span>'


def _bullet_svg(geometry: dict | None, label: str) -> str:
    if not geometry:
        return ""
    width = geometry["width"]
    fill = _TONE_FILL.get(geometry.get("tone"), "#12201e")
    return (
        f'<svg class="bul" viewBox="0 0 {width:.0f} 26" width="100%" height="26" '
        f'preserveAspectRatio="none" role="img" aria-label="{_e(label)}">'
        f'<rect x="{geometry["track_x"]:.1f}" y="10.0" width="{geometry["track_w"]:.1f}" '
        f'height="6" rx="3" fill="#eef2f6"/>'
        f'<rect x="{geometry["band_x"]:.1f}" y="10.0" width="{geometry["band_w"]:.1f}" '
        f'height="6" rx="3" fill="#d7ece9"/>'
        f'<rect x="{geometry["p50_x"] - 0.9:.1f}" y="7.5" width="1.8" height="11" rx="0.9" '
        f'fill="#087f79"/>'
        f'<rect x="{geometry["actual_x"] - 1.6:.1f}" y="5.5" width="3.2" height="15" rx="1.6" '
        f'fill="{fill}"/></svg>')


def _kpi(entry: dict) -> str:
    tone = f' {entry["tone"]}' if entry.get("tone") in ("crit", "good") else ""
    bullet = _bullet_svg(entry.get("bullet"), f'{entry["label"]} {entry["value"]}, {entry["note"]}')
    return (f'<div class="kpi{tone}"><p class="lab">{_e(entry["label"])}</p>'
            f'<p class="val">{_e(entry["value"])}</p>{bullet}'
            f'<p class="sub">{_e(entry["note"])}</p>'
            f'{_pill(entry["pill"], entry["word"])}</div>')


def _mr(entry: dict) -> str:
    tone = f' {entry["tone"]}' if entry.get("tone") in ("crit", "good") else ""
    bullet = _bullet_svg(entry.get("bullet"), f'{entry["label"]} {entry["value"]}, {entry["note"]}')
    return (f'<div class="mr"><div class="mr-l">{_e(entry["label"])}'
            f'<small>{_e(entry["band"])}</small></div>'
            f'<div class="mr-b">{bullet}</div>'
            f'<div class="mr-v{tone}">{_e(entry["value"])}'
            f'<small>{_e(entry["note"])}</small>'
            f'{_pill(entry["pill"], entry["word"])}</div></div>')


def _table(block: dict) -> str:
    numeric = set(block.get("numeric") or [])
    urgent = set(block.get("urgent") or [])
    thead = "".join(f'<th class="n">{_e(head)}</th>' if i in numeric else f"<th>{_e(head)}</th>"
                    for i, head in enumerate(block["headers"]))
    body = []
    for index, row in enumerate(block["rows"]):
        cells = []
        for i, cell in enumerate(row):
            classes = ["n"] if i in numeric else []
            text = str(cell)
            if i in numeric and text.startswith("−"):
                classes.append("crit")
            elif i in numeric and text.startswith("+"):
                classes.append("good")
            attr = f' class="{" ".join(classes)}"' if classes else ""
            inner = f"<b>{_e(text)}</b>" if i == 0 else _e(text)
            cells.append(f"<td{attr}>{inner}</td>")
        row_class = ' class="urgent"' if index in urgent else ""
        body.append(f"<tr{row_class}>{''.join(cells)}</tr>")
    if not body:
        body.append(f'<tr><td colspan="{len(block["headers"])}">Nothing to show here '
                    f'on this day.</td></tr>')
    return (f'<div class="scroll"><table><thead><tr>{thead}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def _rank_bars(bars: list[dict], empty: str) -> str:
    if not bars:
        return f'<p class="note">{_e(empty)}</p>'
    parts = []
    for bar in bars:
        colour = _TONE_FILL.get(bar.get("tone"), "#0f9f95")
        tick = (f'<span class="rb-tick" style="left:{bar["tick"]:.1f}%"></span>'
                if bar.get("tick") is not None else "")
        sub = bar.get("sub") or "&nbsp;"
        parts.append(
            f'<div class="rb"><div class="rb-l">{_e(bar["name"])}'
            f'<small>{_e(sub) if bar.get("sub") else sub}</small></div>'
            f'<div class="rb-t"><span class="rb-f" style="width:{bar["width"]:.1f}%;'
            f'background:{colour}"></span>{tick}</div>'
            f'<div class="rb-v">{_e(bar["value"])}'
            f'<small class="act">{_e(bar.get("note") or "")}</small></div></div>')
    return f'<div class="rbars">{"".join(parts)}</div>'


def _share_bars(bars: list[dict]) -> str:
    shaped = [{**bar, "tone": "short" if bar.get("short") else "at"} for bar in bars]
    if not shaped:
        return '<p class="note">No basket shares are available for this day.</p>'
    parts = []
    for bar in shaped:
        colour = "#c08429" if bar["tone"] == "short" else "#0f9f95"
        tick = (f'<span class="rb-tick" style="left:{bar["tick"]:.1f}%"></span>'
                if bar.get("tick") is not None else "")
        parts.append(
            f'<div class="rb"><div class="rb-l">{_e(bar["name"])}'
            f'<small>{_e(bar["sub"])}</small></div>'
            f'<div class="rb-t"><span class="rb-f" style="width:{bar["width"]:.1f}%;'
            f'background:{colour}"></span>{tick}</div>'
            f'<div class="rb-v">{_e(bar["value"])}'
            f'<small class="act">{_e(bar["note"])}</small></div></div>')
    return f'<div class="rbars">{"".join(parts)}</div>'


# ---------------------------------------------------------------------------
# charts
# ---------------------------------------------------------------------------

def _trend_svg(chart: dict, title: str, *, width: int = 1180, height: int = 290) -> str:
    """`width` is the viewBox width, and it must be chosen to suit the column
    the chart lands in. The SVG carries no `height` attribute: with both
    `width="100%"` and a fixed height the browser letterboxes the drawing
    inside the taller box, which put a 106px chart in the middle of a 250px
    band of white in the half-width store cards."""
    points = chart["points"]
    left, right, top, bottom = 54, width - 58, 30, height - 62
    values = [p["actual_pct"] for p in points]
    values += [p["p20_pct"] for p in points if p["p20_pct"] is not None]
    values += [p["p80_pct"] for p in points if p["p80_pct"] is not None]
    low, high = min(values + [95.0]), max(values + [105.0])
    pad = (high - low) * 0.08 or 5.0
    low, high = low - pad, high + pad
    count = len(points)
    step = (right - left) / max(count - 1, 1)

    def x(index: int) -> float:
        return left + index * step

    def y(value: float) -> float:
        return bottom - (value - low) / (high - low) * (bottom - top)

    grid = []
    line = round(low / 10.0) * 10.0
    while line <= high:
        if line >= low:
            position = y(line)
            grid.append(
                f'<line x1="{left}" y1="{position:.1f}" x2="{right}" y2="{position:.1f}" '
                f'stroke="#e6edf1" stroke-width="1"/>'
                f'<text class="dz" x="{left - 8}" y="{position + 3:.1f}" text-anchor="end">'
                f'{line:.0f}%</text>')
        line += 10.0
    benchmark = y(100.0)
    grid.append(
        f'<line x1="{left}" y1="{benchmark:.1f}" x2="{right}" y2="{benchmark:.1f}" '
        f'stroke="#087f79" stroke-width="1.4" stroke-dasharray="4 3" stroke-opacity="0.8"/>'
        f'<text class="dza" x="{right + 6}" y="{benchmark + 3:.1f}">benchmark</text>')

    band = ""
    if all(p["p20_pct"] is not None and p["p80_pct"] is not None for p in points):
        upper = " ".join(f'{x(i):.1f},{y(p["p80_pct"]):.1f}' for i, p in enumerate(points))
        lower = " ".join(f'{x(i):.1f},{y(p["p20_pct"]):.1f}'
                         for i, p in reversed(list(enumerate(points))))
        band = f'<polygon points="{upper} {lower}" fill="#0f9f95" fill-opacity="0.16"/>'

    path = " ".join(f'{x(i):.1f},{y(p["actual_pct"]):.1f}' for i, p in enumerate(points))
    line_svg = f'<polyline points="{path}" fill="none" stroke="#12201e" stroke-width="2"/>'

    dots = []
    for index, point in enumerate(points):
        radius, fill = 2.8, "#12201e"
        if point["below"]:
            radius, fill = 4.8, "#cf4636"
        elif point["above"]:
            radius, fill = 4.8, "#2f8f4e"
        dots.append(f'<circle cx="{x(index):.1f}" cy="{y(point["actual_pct"]):.1f}" '
                    f'r="{radius}" fill="{fill}" stroke="#fff" stroke-width="1.4"/>')

    labels = []
    # About one label per 80 viewBox units, so a narrow chart thins them out
    # instead of overprinting.
    every = max(1, count // max(1, int((right - left) / 80)))
    for index, point in enumerate(points):
        last = index == count - 1
        # The final day always gets a label; a periodic one sitting right
        # beside it is dropped rather than printed on top of it.
        if last or (index % every == 0 and (count - 1 - index) >= every):
            labels.append(f'<text class="dzday" x="{x(index):.1f}" y="{bottom + 20}" '
                          f'text-anchor="middle">{_e(point["label"])}</text>')

    return (f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
            f'aria-label="{_e(title)}">{"".join(grid)}{band}{line_svg}'
            f'{"".join(dots)}{"".join(labels)}</svg>')


def _bridge_svg(bridge: dict, aria: str) -> str:
    """A four-bar waterfall: the benchmark, the Bills effect, the Basket
    effect, and the day. The two effects add to the gap exactly, so the last
    bar closes on the day's real Net Sales rather than on a rounded total."""
    steps = bridge["steps"]
    width, height = 560, 280
    baseline, ceiling = 228.0, 51.6
    peak = max(abs(step["value"]) for step in steps if step["kind"] == "total") or 1.0
    scale = (baseline - ceiling) / peak

    bar_w, gap = 92.0, 42.0
    slot = bar_w + gap
    parts = [f'<line x1="20" y1="{baseline}" x2="{width - 14}" y2="{baseline}" stroke="#dfe7ec"/>']
    running = 0.0
    bars = []
    for index, step in enumerate(steps):
        x = 30.0 + index * slot
        if step["kind"] == "total":
            bottom_value, top_value = 0.0, step["value"]
            running = step["value"]
        else:
            start = running
            running = start + step["value"]
            bottom_value, top_value = min(start, running), max(start, running)
        y_top = baseline - top_value * scale
        bar_h = max((top_value - bottom_value) * scale, 2.0)
        colour = "#087f79" if step["kind"] == "total" and index == 0 else (
            "#cf4636" if step["kind"] == "total" else "#c08429")
        if step["kind"] == "total" and index == len(steps) - 1 and step["value"] >= steps[0]["value"]:
            colour = "#2f8f4e"
        text_fill = ' fill="#8a5f10"' if step["kind"] == "delta" else ""
        bars.append((x, y_top, bar_h, colour, step, text_fill))
    for index, (x, y_top, bar_h, colour, step, text_fill) in enumerate(bars):
        if index:
            previous = bars[index - 1]
            # From the previous bar's RIGHT edge, not its left: a connector
            # starting at the left is drawn straight across the bar it came from.
            parts.append(f'<line x1="{previous[0] + bar_w:.0f}" y1="{y_top:.1f}" '
                         f'x2="{x:.0f}" y2="{y_top:.1f}" stroke="#8fa1a9" stroke-width="1" '
                         f'stroke-dasharray="3 3"/>')
        centre = x + bar_w / 2.0
        from .daily_sales_dashboard import money, signed_money
        currency = bridge.get("currency") or ""
        label = (money(step["value"], currency) if step["kind"] == "total"
                 else signed_money(step["value"], currency))
        parts.append(
            f'<rect x="{x:.0f}" y="{y_top:.1f}" width="{bar_w:.0f}" height="{bar_h:.1f}" '
            f'rx="2" fill="{colour}"/>'
            f'<text class="dzv" x="{centre:.1f}" y="{y_top - 9:.1f}" text-anchor="middle"'
            f'{text_fill}>{_e(label)}</text>'
            f'<text class="dzday" x="{centre:.1f}" y="252" text-anchor="middle">'
            f'{_e(step["label"])}</text>'
            f'<text class="dzsub" x="{centre:.1f}" y="266" text-anchor="middle">'
            f'{_e(step["sub"])}</text>')
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" '
            f'aria-label="{_e(aria)}">{"".join(parts)}</svg>')


# ---------------------------------------------------------------------------
# layers
# ---------------------------------------------------------------------------

def _hero_html(hero: dict) -> str:
    stats = "".join(
        f'<div class="hs{" " + stat["tone"] if stat.get("tone") in ("crit", "good") else ""}">'
        f'<b>{_e(stat["value"])}</b><span>{_e(stat["label"])}</span></div>'
        for stat in hero.get("stats") or [])
    return (f'<div class="hero"><div>'
            f'<span class="hero-tag">{_e(hero.get("tag") or "")}</span>'
            f'<h2>{_e(hero.get("headline") or "")}</h2>'
            f'<p>{_e(hero.get("narrative") or "")}</p></div>'
            f'<div class="hero-stats">{stats}</div></div>')


def _day_body(page: dict) -> str:
    kpis = "".join(_kpi(entry) for entry in page["kpis"])

    trend = page.get("trend")
    trend_html = ""
    if trend:
        title = (f"Each of the last {trend['total']} days as a percentage of its own benchmark, "
                 f"with the normal band shaded. {trend['inside']} days landed inside the band.")
        below = [p for p in trend["points"] if p["below"]]
        tail = ""
        if len(below) == 1:
            from . import daily_sales as _ds
            tail = (f" {_ds.day_label(below[0]['date'])} is the only day in the window that "
                    f"finished below it.")
        trend_html = _card(
            "Net Sales against the normal band, day by day",
            f"Both stores together · {trend['window']} · each day scored against its own weekday",
            _trend_svg(trend, title),
            "The shaded band is the normal band for that weekday, and the dashed line is the "
            f"benchmark. {trend['inside']} of the {trend['total']} days landed inside the "
            f"band.{tail}")

    bridge = page.get("bridge")
    bridge_html = ""
    if bridge:
        bridge_html = _card(
            "What carried the day",
            "Net Sales is Bills multiplied by Basket Value, so the gap belongs to one of them "
            "or to both",
            _bridge_svg({**bridge, "currency": page["currency"]}, bridge["note"]),
            bridge["note"])

    across = "".join(_mr(entry) for entry in page["look_across"])
    look_down = page["look_down"]
    minis = "".join(
        f'<div class="mini"><b>{_e(store["name"])}</b>'
        f'<span>{_e(store["headline"])}</span>'
        f'<span class="act">{_e(store["detail"])}</span>'
        f'{_pill(store["pill"], store["word"])}</div>'
        for store in look_down["stores"])

    caveats = "".join(f'<li><b>{_e(item["lead"])}</b>{_e(item["body"])}</li>'
                      for item in page["caveats"])

    across_card = _card(
        "", "Every measure on this day, each against its own normal band",
        f'<div class="mrs">{across}</div>',
        "A measure inside the band is normal for this weekday and is not a move.",
        title_html="Look across &mdash; the four measures side by side")
    look_down_card = _card(
        "", "The stores, then the department underneath the weaker one",
        f'<div class="minis">{minis}</div>', look_down["sentence"],
        title_html="Look down &mdash; where the day sits")

    # Layer order is the reference's: the trend runs full width, the bridge
    # sits beside "Look across", and "Look down" gets its own full-width row.
    # Putting the 1180-wide trend into a half-width column shrinks it to a
    # sparkline and leaves the card mostly white.
    trend_row = (f'<div class="grid" style="margin-top:14px">{trend_html}</div>'
                 if trend_html else "")
    if bridge_html:
        middle = f'<div class="grid g-2" style="margin-top:14px">{bridge_html}{across_card}</div>'
    else:
        middle = f'<div class="grid" style="margin-top:14px">{across_card}</div>'

    return (
        f'{_hero_html(page["hero"])}'
        f'{_sect("The day", page["as_at_label"])}'
        f'<div class="kpis">{kpis}</div>'
        f'{trend_row}'
        f'{middle}'
        f'<div class="grid" style="margin-top:14px">{look_down_card}</div>'
        f'<div class="caveats"><h3>What these figures cover, and what they do not</h3>'
        f'<ul>{caveats}</ul></div>')


def _stores_body(page: dict) -> str:
    cards = "".join(
        _card(store["name"],
              "All four measures against this store's own benchmark for this weekday",
              f'<div class="mrs">{"".join(_mr(row) for row in store["measures"])}</div>',
              store["note"])
        for store in page["stores"])
    html = (f'{_sect("Stores", page["as_at_label"] + " · each store on its own band")}'
            f'<div class="grid g-2e">{cards}</div>')

    trends = page.get("store_trends") or []
    if trends:
        blocks = "".join(
            _card("", "Net Sales against this store's own normal band",
                  _trend_svg(store["chart"],
                             f'{store["name"]} Net Sales against its normal band, '
                             f'{store["chart"]["inside"]} of {store["chart"]["total"]} days '
                             f'inside the band', width=620, height=300),
                  store["note"],
                  title_html=(f'{_e(store["name"])} &mdash; the last '
                              f'{store["chart"]["total"]} days'))
            for store in trends)
        html += (f'{_sect("The last two weeks", "One store at a time")}'
                 f'<div class="grid g-2e">{blocks}</div>')
    return html


def _departments_body(page: dict) -> str:
    block = page["departments"]
    table = _card(
        "Every department on this day",
        "Both stores together · each department against its own benchmark table",
        _table(block["table"]),
        "Share of baskets is this department's Bills divided by the day's Bills across every "
        "store, with the benchmark share beside it. One basket can touch several departments, "
        "so these shares do not add to 100%.")
    bars = _card(
        "How many baskets each department reached",
        "Share of the day's Bills, with the benchmark share marked",
        _share_bars(block["share_bars"]),
        "The mark on each bar is that department's usual share for this weekday. A bar short of "
        "its mark reached fewer baskets than normal. The shares do not add to 100% because one "
        "basket can touch several departments.")
    outside_body = (
        _rank_bars(block["below"], "Nothing finished below its normal band at this level "
                                   "on this day.")
        + '<h4 class="mini-h">Above the band</h4>'
        + _rank_bars(block["above"], "Nothing finished above its normal band at this level "
                                      "on this day."))
    outside = _card(
        "Departments outside their band",
        f"Ranked by the size of the gap in {page['currency']}, not by the percentage",
        outside_body,
        "A department can sit far from its band and still be small. Ranking by "
        f"{page['currency']} keeps the biggest gap at the top.")

    by_store = _card(
        "Each department, store by store",
        "The same department in each store, against that store's own benchmark",
        _table(block["by_store"]),
        "A department can sit inside its band across every store while one of them is outside "
        "its own, so all are shown.")

    return (f'{_sect("Departments", page["as_at_label"])}'
            f'<div class="grid">{table}</div>'
            f'<div class="grid g-2" style="margin-top:14px">{bars}{outside}</div>'
            f'{_sect("Store by store", "The same departments, split between the stores")}'
            f'<div class="grid">{by_store}</div>')


def _detail_body(page: dict) -> str:
    currency = page["currency"]
    sections, categories = page["sections"], page["categories"]

    below = _card(
        "What finished below its band",
        f"Sections and categories, ranked by the size of the gap in {currency}",
        ('<h4 class="mini-h">Sections</h4>'
         + _rank_bars(sections["below"][:10],
                      "Nothing finished below its normal band at this level on this day.")
         + '<h4 class="mini-h">Categories</h4>'
         + _rank_bars(categories["below"][:10],
                      "Nothing finished below its normal band at this level on this day.")),
        "A small gap on a small part of the business is not a finding. These are ordered by how "
        f"many {currency} the gap is worth.")

    above = _card(
        "What finished above its band",
        "The same ranking, for the parts that beat their ceiling",
        ('<h4 class="mini-h">Sections</h4>'
         + _rank_bars(sections["above"][:10],
                      "Nothing finished above its normal band at this level on this day.")
         + '<h4 class="mini-h">Categories</h4>'
         + _rank_bars(categories["above"][:10],
                      "Nothing finished above its normal band at this level on this day.")),
        "A day below its band overall can still hold parts that beat their own.")

    silent = page["silent"]
    silent_card = _card(
        "Groups that recorded nothing today",
        "Counted separately, never folded into a band comparison",
        _table(silent["table"]),
        f"{silent['total']:,} groups across the day recorded no sale at all. On a matching past "
        f"day they take {silent['benchmark']} between them. They are kept out of the band "
        f"comparisons above, because a benchmark that includes groups which could not "
        f"contribute would make every name read below its band."
        + (f" The {silent['shown']} categories holding the most silent trade are listed here, "
           f"of {silent['of']} with any." if silent["of"] > silent["shown"] else ""))

    full_sections = _card(
        "Every section",
        f"{page['counts']['sections']} sections with a sale on this day",
        _table(sections["table"]))
    full_categories = _card(
        "Every category",
        f"{page['counts']['categories']} categories with a sale on this day",
        _table(categories["table"]))

    return (f'{_sect("Detail", "Sections and categories · " + page["as_at_label"])}'
            f'<div class="grid g-2e">{below}{above}</div>'
            f'<div class="grid" style="margin-top:14px">{silent_card}</div>'
            f'{_sect("The full lists", "Every row, all stores together")}'
            f'<div class="grid">{full_sections}</div>'
            f'<div class="grid" style="margin-top:14px">{full_categories}</div>')


def _investigation_body(page: dict) -> str:
    entries = page.get("investigation") or []
    if not entries:
        return ""
    from .daily_sales_dashboard import signed_money
    currency = page.get("currency") or ""
    cards = []
    for entry in entries:
        drills = "".join(
            f'<h4 class="mini-h">By {_e(drill["role"])}</h4>'
            + _table({"headers": ["Name", "Against the benchmark"],
                      "rows": [[row["name"], signed_money(row["value"], currency)]
                               for row in drill["rows"]],
                      "numeric": [1], "urgent": []})
            for drill in entry["drills"])
        cards.append(_card(f'{entry["segment"]} ({entry["dimension"]})',
                           f'{entry["rounds"]} round(s) of drill-down',
                           drills, entry["narrative"]))
    budget = page.get("investigation_budget") or {}
    note = (f'<p class="note">Investigation budget: {budget.get("used", 0)} of '
            f'{budget.get("total", 0)} queries used across every hotspot this run.</p>')
    return (f'{_sect("Why here", "adaptive drill-down, by the size of the gap")}'
            f'<div class="grid g-2e">{"".join(cards)}</div>{note}')


# ---------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------

def _scoped_page(page: dict) -> dict:
    """The "outside the band only" view: the same page with every grain
    filtered to the rows that finished outside their band. The day and store
    layers are unchanged - the whole business and each store are the subject
    either way, never a filtered list."""
    def _keep(rows: list[dict]) -> list[dict]:
        return [row for row in rows if row["net_sales"]["verdict"]["key"] in ("crit", "good")]

    from . import daily_sales_dashboard as _db

    scoped = dict(page)
    currency = page["currency"]
    whole = page.get("whole") or {}
    whole_bills = (whole.get("bills") or {}).get("actual")
    whole_bills_p50 = (whole.get("bills") or {}).get("p50")

    departments = _keep(page["departments"]["rows"])
    scoped["departments"] = {
        **page["departments"], "rows": departments,
        "table": _db._grain_table(departments, currency, with_parent=False,
                                  whole_bills=whole_bills, whole_bills_p50=whole_bills_p50,
                                  with_share=True),
        "share_bars": _db._share_bars(departments, whole_bills, whole_bills_p50),
        "by_store": _db._by_store_table(departments, page["store_names"], currency),
    }
    for key in ("sections", "categories"):
        rows = _keep(page[key]["rows"])
        scoped[key] = {
            **page[key], "rows": rows,
            "table": _db._grain_table(rows, currency, with_parent=True,
                                      whole_bills=whole_bills, whole_bills_p50=whole_bills_p50),
        }
    scoped["counts"] = {"departments": len(departments),
                        "sections": len(scoped["sections"]["rows"]),
                        "categories": len(scoped["categories"]["rows"])}
    return scoped


_SCOPE_NOTE = ("This view keeps only the parts of the business that finished outside their "
               "normal Net Sales band. The day and the stores are shown in full either way.")


def _views(page: dict, scoped: dict, body_fn, *, scope: bool) -> str:
    all_html = body_fn(page)
    out_html = body_fn(scoped if scope else page)
    banner = f'<div class="scoped">{_e(_SCOPE_NOTE)}</div>' if scope else ""
    return (f'<div class="view" data-view="all">{all_html}</div>'
            f'<div class="view" data-view="out" hidden>{banner}{out_html}</div>')


def render(page: dict, *, eyebrow: str = "Sales") -> str:
    scoped = _scoped_page(page)
    layers = [("day", "The day"), ("stores", "Stores"),
              ("departments", "Departments"), ("detail", "Detail")]
    current = ' aria-current="true"'
    nav = "".join(
        f'<button data-nav="{key}"{current if index == 0 else ""}>{_e(label)}</button>'
        for index, (key, label) in enumerate(layers))

    day_html = _views(page, scoped, _day_body, scope=False)
    stores_html = _views(page, scoped, _stores_body, scope=False)
    departments_html = _views(
        page, scoped, lambda p: _departments_body(p) + _investigation_body(p), scope=True)
    detail_html = _views(page, scoped, _detail_body, scope=True)

    body = (f'<div class="layer" data-layer="day">{day_html}</div>'
            f'<div class="layer" data-layer="stores" hidden>{stores_html}</div>'
            f'<div class="layer" data-layer="departments" hidden>{departments_html}</div>'
            f'<div class="layer" data-layer="detail" hidden>{detail_html}</div>')

    title = _e(page.get("title") or "Daily Sales")
    checks = page.get("checks") or {}
    failed = [name for name, ok in checks.items() if not ok]
    footer = (f'<div class="pagefoot"><span>{_e(page.get("last_updated") or "")}</span>'
              f'<span>' + (f'{len(checks) - len(failed)} of {len(checks)} reconciliation checks '
                           f'passed' if failed else
                           f'All {len(checks)} reconciliation checks passed') + '</span></div>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="app" id="report">
<nav class="rail" aria-label="Sections">
<div class="mark">AI</div>
<div class="grp">Report</div>
{nav}
<div class="grp">View</div>
<button data-viewbtn="all" aria-current="true">All areas</button>
<button data-viewbtn="out">Outside the band only</button>
<p class="foot">Figures are the live position for {_e(page.get("as_at_label") or "")}.</p>
</nav>
<main><div class="page">
<div class="masthead"><div>
<p class="eyebrow">{_e(eyebrow)} &middot; Daily benchmark</p>
<h1>{title}</h1>
<p class="asat">{_e(page.get("masthead_sub") or "")}</p>
</div><div class="seg" role="group" aria-label="View">
<button data-viewbtn="all" aria-pressed="true">All areas</button>
<button data-viewbtn="out" aria-pressed="false">Outside the band only</button></div></div>
{body}
{footer}
</div></main>
</div>
<script>{_SCRIPT}</script>
</body>
</html>"""
