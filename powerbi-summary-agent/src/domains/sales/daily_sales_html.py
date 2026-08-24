"""Renders the Daily Sales page model to HTML, reusing the client-approved
reference design's CSS verbatim (`reference_daily_sales.html`) - same
colour tokens, same component classes (`.hero`, `.kpi`, `.mr`, `.rb`,
`.bul` bullet charts) - so the shipped page matches what was approved,
adapted only where the reduced scope requires it (see `daily_sales.py` and
`daily_sales_dashboard.py` for why Net Sales/Basket Value bands and
department-level Net Sales are absent).

Self-contained: no external request, no build step. Nav + view toggling is
the same small amount of inline JS the reference itself uses, in one
`<script>` tag.
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
.hero{background:var(--rail);border-radius:var(--r);padding:20px 24px;margin-bottom:14px}
.hero-tag{display:inline-block;font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  font-weight:750;color:#f0c46a;background:rgba(240,196,106,.14);padding:4px 9px;
  border-radius:6px;margin-bottom:10px}
.hero h2{color:#fff;font-size:23px;line-height:1.22;letter-spacing:-.015em;font-weight:700}
.hero p{color:#a9c2bd;font-size:12.5px;margin-top:8px;max-width:70ch}
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
.mini .act{color:var(--faint);font-size:11px}
.mini .pill{margin-top:8px}
.rbars{display:flex;flex-direction:column;gap:9px}
.rb{display:grid;grid-template-columns:160px minmax(0,1fr) 128px;gap:11px;align-items:center;
  font-size:12px}
.rb-l{font-weight:650;overflow:hidden;text-overflow:ellipsis}
.rb-l small{display:block;font-weight:400;font-size:10px;color:var(--muted)}
.rb-t{background:#eef2f6;border-radius:99px;height:10px;position:relative}
.rb-f{display:block;height:100%;border-radius:99px}
.rb-v{text-align:right;font-weight:700}
.rb-v small{display:block;font-weight:500;font-size:10px}
.scroll{overflow-x:auto;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:12px;min-width:560px}
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
.dza{fill:var(--teal-dk);font-size:9.5px;font-weight:650}
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
@media (max-width:1080px){
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .g-2,.g-2e,.minis{grid-template-columns:minmax(0,1fr)}
  .mr{grid-template-columns:110px minmax(0,1fr)}
  .mr-b{display:none}
}
@media (max-width:720px){.rail{display:none}}
@media print{
  .rail,.seg{display:none}.app{display:block}.card,.kpi,.hero{break-inside:avoid;box-shadow:none}
  body{background:#fff}
  .layer[hidden],.view[hidden]{display:block}
}
"""

_SCRIPT = """
document.querySelectorAll('[data-nav]').forEach(function(btn){
  btn.addEventListener('click', function(){
    document.querySelectorAll('[data-nav]').forEach(function(b){b.setAttribute('aria-current', 'false')});
    btn.setAttribute('aria-current', 'true');
    document.querySelectorAll('.layer').forEach(function(l){l.hidden = true});
    var target = document.querySelector('.layer[data-layer="' + btn.dataset.nav + '"]');
    if (target) target.hidden = false;
  });
});
document.querySelectorAll('[data-viewbtn]').forEach(function(btn){
  btn.addEventListener('click', function(){
    document.querySelectorAll('[data-viewbtn]').forEach(function(b){
      b.setAttribute('aria-pressed', b.dataset.viewbtn === btn.dataset.viewbtn ? 'true' : 'false');
      b.setAttribute('aria-current', b.dataset.viewbtn === btn.dataset.viewbtn ? 'true' : 'false');
    });
    document.querySelectorAll('.view').forEach(function(v){v.hidden = true});
    document.querySelectorAll('.view[data-view="' + btn.dataset.viewbtn + '"]').forEach(function(v){v.hidden = false});
  });
});
"""


def _bullet_svg(bullet: dict | None, verdict_key: str | None, *, height: float = 26.0) -> str:
    if not bullet:
        return '<p class="note">Not available.</p>'
    color = {"crit": "#cf4636", "good": "#2f8f4e", "neutral": "#12201e"}.get(verdict_key, "#12201e")
    w = bullet["width"]
    return (f'<svg class="bul" viewBox="0 0 {w:.0f} {height:.0f}" width="100%" height="{height:.0f}" '
           f'preserveAspectRatio="none" role="img" aria-hidden="true">'
           f'<rect x="{bullet["track_x"]:.1f}" y="{height/2-3:.1f}" width="{bullet["track_w"]:.1f}" '
           f'height="6" rx="3" fill="#eef2f6"/>'
           f'<rect x="{bullet["band_x"]:.1f}" y="{height/2-3:.1f}" width="{max(bullet["band_w"],1):.1f}" '
           f'height="6" rx="3" fill="#d7ece9"/>'
           f'<rect x="{bullet["p50_x"]:.1f}" y="{height/2-5.5:.1f}" width="1.8" height="11" rx="0.9" '
           f'fill="#087f79"/>'
           f'<rect x="{bullet["actual_x"]-1.6:.1f}" y="{height/2-7.5:.1f}" width="3.2" height="15" rx="1.6" '
           f'fill="{color}"/></svg>')


def _kpi(label: str, value: str, sub: str, verdict_key: str | None, bullet: dict | None,
        pill_class: str | None, pill_word: str | None) -> str:
    cls = "kpi"
    if verdict_key == "crit":
        cls += " crit"
    elif verdict_key == "good":
        cls += " good"
    pill = f'<span class="pill {pill_class}">{_e(pill_word)}</span>' if pill_class and pill_word else ""
    bul = _bullet_svg(bullet, verdict_key) if bullet else ""
    return (f'<div class="{cls}"><p class="lab">{_e(label)}</p><p class="val">{_e(value)}</p>'
           f'{bul}<p class="sub">{_e(sub)}</p>{pill}</div>')


def _mr(label: str, sub: str, measure: dict) -> str:
    if "verdict" not in measure:
        # Net Sales / Basket Value: an actual value may be known, but there is
        # never a trustworthy band to show alongside it (see daily_sales.py).
        value = measure.get("value", "—")
        return (f'<div class="mr"><div class="mr-l">{_e(label)}<small>{_e(sub)}</small></div>'
               f'<div class="mr-b"><p class="note">No reliable benchmark</p></div>'
               f'<div class="mr-v">{_e(value)}<small>actual only</small></div></div>')
    cls = "mr-v"
    if measure["verdict"]["key"] == "crit":
        cls += " crit"
    elif measure["verdict"]["key"] == "good":
        cls += " good"
    return (f'<div class="mr"><div class="mr-l">{_e(label)}<small>{_e(sub)}</small></div>'
           f'<div class="mr-b">{_bullet_svg(measure["bullet"], measure["verdict"]["key"])}</div>'
           f'<div class="{cls}">{_e(measure["value"])}<small>benchmark {_e(measure["band"])}</small>'
           f'<span class="pill {_e(measure["pill"])}">{_e(measure["verdict"]["word"])}</span></div></div>')


def _table(headers: list[str], rows: list[list[str]], *, num_cols: set[int] = frozenset(),
          urgent_rows: set[int] = frozenset()) -> str:
    thead = "".join(f'<th class="n">{_e(h)}</th>' if i in num_cols else f"<th>{_e(h)}</th>"
                    for i, h in enumerate(headers))
    body = []
    for ri, row in enumerate(rows):
        cells = "".join(f'<td class="n">{_e(c)}</td>' if i in num_cols else f"<td>{_e(c)}</td>"
                        for i, c in enumerate(row))
        cls = ' class="urgent"' if ri in urgent_rows else ""
        body.append(f"<tr{cls}>{cells}</tr>")
    return (f'<div class="scroll"><table><thead><tr>{thead}</tr></thead>'
           f'<tbody>{"".join(body)}</tbody></table></div>')


def _rank_bars(rows: list[dict], *, metric: str = "bills", by: str = "gap") -> str:
    """Ranked by the absolute size of the gap outside the band (never by
    percentage) - a small part of the business moving a lot is still small."""
    ranked = [r for r in rows if r[metric]["gap"]]
    ranked.sort(key=lambda r: -abs(r[metric]["gap"] or 0))
    if not ranked:
        return '<p class="note">Nothing finished outside its band at this level.</p>'
    peak = max(abs(r[metric]["gap"] or 0) for r in ranked) or 1.0
    parts = []
    for r in ranked[:10]:
        gap = r[metric]["gap"] or 0
        color = "#cf4636" if gap < 0 else "#2f8f4e"
        parts.append(
            f'<div class="rb"><div class="rb-l">{_e(r["name"])}<small>{_e(r.get("parent") or "")}</small></div>'
            f'<div class="rb-t"><span class="rb-f" style="width:{abs(gap)/peak*100:.1f}%;'
            f'background:{color}"></span></div>'
            f'<div class="rb-v">{"+" if gap > 0 else "-"}{abs(gap):,.0f}<small>{_e(r[metric]["value"])}</small></div>'
            f'</div>')
    return f'<div class="rbars">{"".join(parts)}</div>'


def _trend_svg(chart: dict) -> str:
    points = chart["points"]
    if not points:
        return '<p class="note">Not enough history.</p>'
    width, height = 1180, 290
    left, right, top, bottom = 54, 1122, 30, 228
    all_vals = [p["actual_pct"] for p in points] + [p["p20_pct"] for p in points] + [p["p80_pct"] for p in points]
    lo, hi = min(all_vals + [90]), max(all_vals + [110])
    pad = (hi - lo) * 0.08 or 5
    lo, hi = lo - pad, hi + pad
    n = len(points)
    step = (right - left) / max(n - 1, 1)

    def x(i: int) -> float:
        return left + i * step

    def y(v: float) -> float:
        return bottom - (v - lo) / (hi - lo) * (bottom - top)

    grid = []
    gv = round(lo / 10) * 10
    while gv <= hi:
        yy = y(gv)
        grid.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{right}" y2="{yy:.1f}" stroke="#e6edf1" '
                    f'stroke-width="1"/><text class="dz" x="{left-8}" y="{yy+3:.1f}" '
                    f'text-anchor="end">{gv:.0f}%</text>')
        gv += 10
    bench_y = y(100.0)
    grid.append(f'<line x1="{left}" y1="{bench_y:.1f}" x2="{right}" y2="{bench_y:.1f}" stroke="#087f79" '
               f'stroke-width="1.4" stroke-dasharray="4 3" stroke-opacity="0.8"/>'
               f'<text class="dza" x="{right+6}" y="{bench_y+3:.1f}">benchmark</text>')

    band_top = " ".join(f'{x(i):.1f},{y(p["p80_pct"]):.1f}' for i, p in enumerate(points))
    band_bottom = " ".join(f'{x(i):.1f},{y(p["p20_pct"]):.1f}' for i, p in enumerate(reversed(points)))
    band_path = f'<polygon points="{band_top} {band_bottom}" fill="#0f9f95" fill-opacity="0.16"/>'

    line_pts = " ".join(f'{x(i):.1f},{y(p["actual_pct"]):.1f}' for i, p in enumerate(points))
    line_path = f'<polyline points="{line_pts}" fill="none" stroke="#12201e" stroke-width="2"/>'

    circles = []
    for i, p in enumerate(points):
        r = 2.8
        fill = "#12201e"
        if p["actual_pct"] == max(pp["actual_pct"] for pp in points):
            r, fill = 4.8, "#2f8f4e"
        if p["actual_pct"] == min(pp["actual_pct"] for pp in points):
            r, fill = 4.8, "#cf4636"
        circles.append(f'<circle cx="{x(i):.1f}" cy="{y(p["actual_pct"]):.1f}" r="{r}" fill="{fill}" '
                       f'stroke="#fff" stroke-width="1.4"/>')

    labels = []
    for i, p in enumerate(points):
        if i % max(1, n // 10) == 0 or i == n - 1:
            day = p["date"][-2:] + "/" + p["date"][5:7]
            labels.append(f'<text class="dzday" x="{x(i):.1f}" y="{bottom+18}" text-anchor="middle">{day}</text>')

    aria_label = (f"Bills each day as a percentage of that day's own benchmark, "
                 f'{chart["inside_count"]} of {chart["total"]} days inside the normal band.')
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" '
           f'aria-label="{_e(aria_label)}">'
           f'{"".join(grid)}{band_path}{line_path}{"".join(circles)}{"".join(labels)}</svg>')


def _day_body(page: dict) -> str:
    hero = page["hero"]
    whole = page["whole"]
    kpis = "".join([
        _kpi("Net Sales", whole["net_sales"]["value"], "No reliable benchmark at this time", None, None, None, None),
        _kpi("Bills", whole["bills"]["value"], f"benchmark {whole['bills']['band']}",
            whole["bills"]["verdict"]["key"], whole["bills"]["bullet"], whole["bills"]["pill"],
            whole["bills"]["verdict"]["word"]),
        _kpi("Basket Value", whole["basket_value"]["value"], "No reliable benchmark at this time",
            None, None, None, None),
        _kpi("Margin", whole["margin"]["value"], f"benchmark {whole['margin']['band']}",
            whole["margin"]["verdict"]["key"], whole["margin"]["bullet"], whole["margin"]["pill"],
            whole["margin"]["verdict"]["word"]),
    ])

    trend = page.get("sparkline_chart")
    trend_html = ""
    if trend:
        trend_html = (
            '<div class="card"><h3>Bills against the normal band, day by day</h3>'
            f'<p class="sub">Both stores together &middot; each day scored against its own weekday benchmark '
            f'&middot; {trend["inside_count"]} of {trend["total"]} days inside the band</p>'
            f'{_trend_svg(trend)}'
            '<p class="note">The shaded band is the normal band for that weekday, and the dashed line is the '
            'benchmark. Net Sales has no reliable day-by-day benchmark yet, so Bills carries this trend.</p></div>')

    mrs = "".join([
        _mr("Net Sales", "no reliable benchmark", whole["net_sales"]),
        _mr("Bills", f"benchmark {whole['bills']['band']}", whole["bills"]),
        _mr("Basket Value", "no reliable benchmark", whole["basket_value"]),
        _mr("Margin", f"benchmark {whole['margin']['band']}", whole["margin"]),
    ])

    minis = "".join(
        f'<div class="mini"><b>{_e(s["label"])}</b>'
        f'<span>Bills {_e(s["bills"]["value"])} &middot; Margin {_e(s["margin"]["value"])}</span>'
        f'<span class="act">Net Sales {_e(s["net_sales"]["value"])} &middot; '
        f'Basket Value {_e(s["basket_value"]["value"])}</span>'
        f'<span class="pill {_e(s["bills"]["pill"])}">{_e(s["bills"]["verdict"]["word"])} (Bills)</span> '
        f'<span class="pill {_e(s["margin"]["pill"])}">{_e(s["margin"]["verdict"]["word"])} (Margin)</span></div>'
        for s in page["stores"])

    caveats = "".join(f"<li>{_e(c)}</li>" for c in page["caveats"])

    return f"""<div class="hero"><span class="hero-tag">{_e(hero["tag"])}</span>
<h2>{_e(hero["headline"])}</h2><p>{_e(hero["sub"])}</p></div>
<div class="sect"><h2>The day</h2><span>{_e(page["as_at"])}</span></div>
<div class="kpis">{kpis}</div>
<div class="grid" style="margin-top:14px">{trend_html}</div>
<div class="grid g-2" style="margin-top:14px">
<div class="card"><h3>Look across &mdash; the four measures side by side</h3>
<p class="sub">Every measure on this day; Bills and Margin against their own normal band</p>
<div class="mrs">{mrs}</div>
<p class="note">A measure inside the band is normal for this weekday and is not a move.</p></div>
<div class="card"><h3>Look down &mdash; where the day sits</h3>
<p class="sub">Each store, Bills and Margin against its own benchmark</p>
<div class="minis">{minis}</div></div>
</div>
<div class="caveats"><h3>What these figures cover, and what they do not</h3><ul>{caveats}</ul></div>"""


def _stores_body(page: dict) -> str:
    cards = []
    for s in page["stores"]:
        mrs = "".join([
            _mr("Net Sales", "no reliable benchmark", s["net_sales"]),
            _mr("Bills", f"benchmark {s['bills']['band']}", s["bills"]),
            _mr("Basket Value", "no reliable benchmark", s["basket_value"]),
            _mr("Margin", f"benchmark {s['margin']['band']}", s["margin"]),
        ])
        cards.append(f'<div class="card"><h3>{_e(s["label"])}</h3>'
                     f'<p class="sub">Bills and Margin against this store&rsquo;s own benchmark; '
                     f'Net Sales/Basket Value shown without a band</p>'
                     f'<div class="mrs">{mrs}</div></div>')
    return (f'<div class="sect"><h2>Stores</h2><span>{_e(page["as_at"])}</span></div>'
           f'<div class="grid g-2e">{"".join(cards)}</div>')


def _grain_body(page: dict, key: str, title: str, view: str) -> str:
    rows = page[key]["outside" if view == "out" else "all"]
    bars = _rank_bars(rows, metric="bills")
    table_rows = []
    urgent = set()
    for i, r in enumerate(rows):
        if r["bills"]["verdict"]["key"] == "crit":
            urgent.add(i)
        table_rows.append([
            r["name"], r.get("parent") or "", r["bills"]["value"], r["bills"]["band"],
            r["bills"]["verdict"]["word"], r["margin"]["value"], r["margin"]["band"],
            r["margin"]["verdict"]["word"], f"{r['group_count']} group(s)",
        ])
    headers = ["Name", "Sits under", "Bills", "Bills band", "Bills verdict",
              "Margin", "Margin band", "Margin verdict", "Groups merged"]
    table = _table(headers, table_rows, num_cols={2, 3, 5, 6}, urgent_rows=urgent)
    return (f'<div class="sect"><h2>{_e(title)}</h2><span>{_e(page["as_at"])} &middot; ranked by the '
           f'size of the Bills gap</span></div>'
           f'<div class="grid"><div class="card"><h3>Furthest outside their Bills band</h3>'
           f'<p class="sub">Ranked by Bills, not by percentage &mdash; a small part of the business '
           f'moving a lot is still small</p>{bars}</div></div>'
           f'<div class="grid" style="margin-top:14px"><div class="card">'
           f'<h3>All {title.lower()}</h3>{table}'
           f'<p class="note">Net Sales is not shown at this level - see the caveats on the day layer '
           f'for why. Margin is a Bills-weighted average where a name covers more than one group.</p>'
           f'</div></div>')


def _investigation_body(page: dict) -> str:
    entries = page.get("investigation") or []
    if not entries:
        budget = page.get("investigation_budget")
        note = ("Investigation is not enabled for this run." if budget is None else
               "No hotspot needed a deeper drill-down today.")
        return f'<div class="card"><p class="note">{_e(note)}</p></div>'
    cards = []
    for e in entries:
        drills = "".join(
            f'<p class="mini-h">By {_e(d["role"])}</p>'
            + _table(["Name", "Bills gap"],
                    [[r["name"], f'{r["value"]:+,.0f}'] for r in d["rows"]], num_cols={1})
            for d in e["drills"])
        cards.append(
            f'<div class="card"><h3>{_e(e["segment"])} ({_e(e["dimension"])})</h3>'
            f'<p class="sub">{e["rounds"]} round(s) of drill-down</p>'
            f'{drills}<p class="note">{_e(e["narrative"])}</p></div>')
    budget = page.get("investigation_budget") or {}
    budget_note = (f'<p class="note">Investigation budget: {budget.get("used", 0)} of '
                  f'{budget.get("total", 0)} queries used across every hotspot this run.</p>')
    return (f'<div class="sect"><h2>Why here</h2><span>adaptive drill-down, Bills only</span></div>'
           f'<div class="grid g-2e">{"".join(cards)}</div>{budget_note}')


def _view_wrap(page: dict, body_fn) -> str:
    """`body_fn(page, view)` where `view` is `"all"` or `"out"`. A layer with
    no per-view content (Day/Stores show the whole business either way)
    passes a `body_fn` that ignores `view`."""
    all_html = body_fn(page, "all")
    out_html = body_fn(page, "out")
    return (f'<div class="view" data-view="all">{all_html}</div>'
           f'<div class="view" data-view="out" hidden>'
           f'<div class="scoped">This view keeps only the parts of the business that finished outside '
           f'their normal Bills or Margin band.</div>'
           f'{out_html}</div>')


def render(page: dict, *, eyebrow: str = "Sales") -> str:
    layers = [("day", "The day"), ("stores", "Stores"), ("departments", "Departments"), ("detail", "Detail")]
    current_attr = ' aria-current="true"'
    nav = "".join(
        f'<button data-nav="{key}"{current_attr if i == 0 else ""}>{_e(label)}</button>'
        for i, (key, label) in enumerate(layers))

    day_html = _view_wrap(page, lambda p, v: _day_body(p))
    stores_html = _view_wrap(page, lambda p, v: _stores_body(p))
    departments_html = (_view_wrap(page, lambda p, v: _grain_body(p, "departments", "Departments", v))
                        + _investigation_body(page))
    detail_html = _view_wrap(page, lambda p, v: (
        _grain_body(p, "sections", "Sections", v) + _grain_body(p, "categories", "Categories", v)))

    body = (
        f'<div class="layer" data-layer="day">{day_html}</div>'
        f'<div class="layer" data-layer="stores" hidden>{stores_html}</div>'
        f'<div class="layer" data-layer="departments" hidden>{departments_html}</div>'
        f'<div class="layer" data-layer="detail" hidden>{detail_html}</div>'
    )

    title = _e(page.get("title") or "Daily Sales")
    as_at = _e(str(page.get("as_at") or ""))
    stores_label = _e(" and ".join(page.get("store_names") or []))
    currency = _e(page.get("currency") or "")
    view_toggle = ('<div class="seg" role="group" aria-label="View">'
                   '<button data-viewbtn="all" aria-pressed="true">All areas</button>'
                   '<button data-viewbtn="out" aria-pressed="false">Outside the band only</button></div>')

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
<p class="foot">Figures are the live position for {as_at}.</p>
</nav>
<main><div class="page">
<div class="masthead"><div>
<p class="eyebrow">{_e(eyebrow)} &middot; Daily benchmark</p>
<h1>{title}</h1>
<p class="asat">{_e(page.get("dow_name") or "")} &middot; week {page.get("week_of_month")} of the month &middot; {stores_label} &middot; all figures in {currency}</p>
</div>{view_toggle}</div>
{body}
</div></main>
</div>
<script>{_SCRIPT}</script>
</body>
</html>"""
