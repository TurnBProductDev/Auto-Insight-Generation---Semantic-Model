"""Renders the SKU Overview page model to HTML, using the client-approved
reference design's own CSS verbatim (`reference_sku_overview.html`) - same
colour tokens, same component classes - so the published page matches what
was actually approved rather than a generic reinterpretation of it.

Self-contained: no external request, no build step. `nav`/`view` toggling is
the same small amount of inline JS the reference itself uses.
"""

from __future__ import annotations

from html import escape as _e
from typing import Any

# ---------------------------------------------------------------------------
# CSS - copied from reference_sku_overview.html, unchanged.
# ---------------------------------------------------------------------------

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
.pill-warn{background:var(--amber-tint);color:var(--amber-dk)}
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
.caveats{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--faint);
  border-radius:var(--r);padding:15px 18px;margin-top:20px}
.caveats h3{font-size:12px;font-weight:700;margin-bottom:9px}
.caveats ul{margin:0;padding-left:17px;color:var(--mid);font-size:11.5px;line-height:1.6}
.caveats li{margin-bottom:5px}
.foot{margin-top:18px;padding-top:12px;border-top:1px solid var(--line);
  display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;
  font-size:10.5px;color:var(--faint)}
.layer[hidden]{display:none}
.view[hidden]{display:none}
.viewbar{display:inline-flex;gap:3px;background:var(--soft);border:1px solid var(--line);
  border-radius:99px;padding:3px;margin-top:8px}
.viewbar button{all:unset;cursor:pointer;padding:6px 14px;border-radius:99px;font-size:11.5px;
  font-weight:650;color:var(--muted)}
.viewbar button[aria-current=true]{background:var(--teal);color:#fff}
.scoped-note{font-size:11px;color:var(--amber-dk);background:var(--amber-tint);
  border-radius:8px;padding:8px 12px;margin-bottom:14px}
.wk{display:flex;align-items:flex-end;gap:7px;height:118px;padding:14px 4px 0}
.wk-bar{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;
  height:100%;min-width:0}
.wk-val{font-size:9.5px;font-weight:700;color:var(--mid);margin-bottom:4px;white-space:nowrap}
.wk-fill{width:100%;background:var(--teal);border-radius:4px 4px 0 0;min-height:3px}
.wk-lab{font-size:9px;color:var(--faint);margin-top:5px;text-align:center;white-space:nowrap}
.price-range{position:relative;height:26px;background:#eef2f6;border-radius:99px;margin:10px 0 4px}
.price-now{position:absolute;top:-6px;width:2px;height:38px;background:var(--rail)}
.price-now::after{content:attr(data-label);position:absolute;top:-18px;left:50%;
  transform:translateX(-50%);font-size:9.5px;font-weight:700;white-space:nowrap;color:var(--ink)}
.price-lo,.price-hi{font-size:10px;color:var(--muted)}
.spot{background:var(--teal-tint);border:1px solid rgba(15,159,149,.25);border-radius:var(--r);
  padding:10px 13px;font-size:11.5px;color:var(--teal-dk);margin-top:10px}
.store{display:inline-block;font-size:10px;font-weight:700;background:var(--teal-tint);
  color:var(--teal-dk);padding:2px 7px;border-radius:5px;letter-spacing:.03em}
.rank{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:50%;
  background:#eef2f6;font-size:9.5px;font-weight:700;color:var(--muted);
  margin-right:6px;vertical-align:1px}
.rank.r1{background:var(--green-tint);color:var(--green)}
.pendcard{background:var(--soft);border:1px dashed var(--faint);border-radius:var(--r);
  padding:17px 19px}
.pend-h{display:flex;align-items:center;justify-content:space-between;gap:14px;
  flex-wrap:wrap;margin-bottom:9px}
.pend-h h3{font-size:13.5px;font-weight:700}
.pendcard p{font-size:12px;color:var(--mid);line-height:1.55;margin-top:8px}
@media (max-width:1080px){
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .g-2,.g-2e{grid-template-columns:minmax(0,1fr)}
  .hero{grid-template-columns:minmax(0,1fr)}
  .rb{grid-template-columns:150px minmax(0,1fr) 104px}
}
@media (max-width:720px){.rail{display:none}}
@media print{
  .rail{display:none}.app{display:block}
  .card,.kpi,.hero{break-inside:avoid;box-shadow:none}
  body{background:#fff}
  .layer[hidden]{display:block}
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
    document.querySelectorAll('[data-viewbtn]').forEach(function(b){b.setAttribute('aria-current', 'false')});
    btn.setAttribute('aria-current', 'true');
    document.querySelectorAll('.view').forEach(function(v){v.hidden = true});
    document.querySelectorAll('.view[data-view="' + btn.dataset.viewbtn + '"]').forEach(function(v){v.hidden = false});
  });
});
"""


def _fmt_money(text: str) -> str:
    return text.replace(" ", "&nbsp;", 1) if " " in text else text


def _kpi(card: dict) -> str:
    cls = "kpi"
    if card.get("crit"):
        cls += " crit"
    elif card.get("good"):
        cls += " good"
    pill = (f'<span class="pill pill-crit">{_e(card["pill"])}</span>'
           if card.get("pill") else "")
    return (f'<div class="{cls}"><p class="lab">{_e(card["label"])}</p>'
           f'<p class="val">{_fmt_money(_e(card["value"]))}</p>'
           f'<p class="sub">{_e(card.get("sub") or "")}</p>{pill}</div>')


def _rank_bar(bar: dict) -> str:
    color = f"var(--{bar['color']})" if bar["color"] != "faint" else "var(--faint)"
    return (
        f'<div class="rb"><div class="rb-l">{_e(bar["label"])}'
        f'<small>{_e(str(bar["model_name"]))}</small></div>'
        f'<div class="rb-t"><span class="rb-f" '
        f'style="width:{bar["width_pct"]:.2f}%;background:{color}"></span></div>'
        f'<div class="rb-v">{bar["count"]:,}<small>{_e(bar["urgency"])}</small></div></div>'
    )


def _worth_bar(item: dict) -> str:
    return (
        f'<div class="rb"><div class="rb-l">{_e(item["label"])}'
        f'<small>{item["count"]:,} lines</small></div>'
        f'<div class="rb-t"><span class="rb-f" style="width:{item["pct"]:.2f}%;'
        f'background:var(--{item["color"]})"></span></div>'
        f'<div class="rb-v">{_fmt_money(_e(item["value"]))}</div></div>'
    )


def _table(headers: list[str], rows: list[list[str]], *, num_cols: set[int] = frozenset()) -> str:
    thead = "".join(f'<th class="n">{_e(h)}</th>' if i in num_cols else f"<th>{_e(h)}</th>"
                    for i, h in enumerate(headers))
    body = []
    for row in rows:
        cells = "".join(f'<td class="n">{_e(c)}</td>' if i in num_cols else f"<td>{_e(c)}</td>"
                        for i, c in enumerate(row))
        body.append(f"<tr>{cells}</tr>")
    return (f'<div class="scroll"><table class="tbl"><thead><tr>{thead}</tr></thead>'
           f'<tbody>{"".join(body)}</tbody></table></div>')


def _overview_body(view: dict, currency: str, period_label: str) -> str:
    hero = view["hero"]
    stats = "".join(
        f'<div class="hs{" crit" if s.get("crit") else ""}"><b>{_fmt_money(_e(s["value"]))}</b>'
        f'<span>{_e(s["label"])}</span></div>'
        for s in hero["stats"])
    sub = f'<p>{_e(hero["sub"])}</p>' if hero.get("sub") else ""
    kpis = "".join(_kpi(k) for k in view["kpis"])
    bars = "".join(_rank_bar(b) for b in view["bars"])

    worth = view["worth"]
    peak_sales = max((w["raw"] for w in worth["sales_at_stake"]), default=0.0) or 1.0
    peak_arrive = max((w["raw"] for w in worth["stock_to_arrive"]), default=0.0) or 1.0
    for w in worth["sales_at_stake"]:
        w["pct"] = w["raw"] / peak_sales * 100.0
    for w in worth["stock_to_arrive"]:
        w["pct"] = w["raw"] / peak_arrive * 100.0
    sales_bars = "".join(_worth_bar(w) for w in worth["sales_at_stake"])
    arrive_bars = "".join(_worth_bar(w) for w in worth["stock_to_arrive"])

    caveats = "".join(f"<li>{_e(c)}</li>" for c in view["caveats"])
    scoped_note = (f'<div class="scoped-note">Showing <b>{_e(view["scope_label"])}</b> - every '
                   f'figure below is worked out again over just those products.</div>'
                   if view.get("scoped") else "")

    return f"""{scoped_note}<div class="hero"><div><span class="hero-tag">{_e(hero["tag"])}</span>
<h2>{_e(hero["headline"])}</h2>{sub}</div>
<div class="hero-stats">{stats}</div></div>
<div class="kpis">{kpis}</div>
<div class="sect"><h2>The whole position</h2><span>{_e(period_label or "")} &middot; 5 shops</span></div>
<div class="grid"><div class="card">
<h3>What the report says to do next</h3>
<p class="sub">Every product-shop line falls into one of these. The bar is how many lines, and the word beside it is how urgent - colour on its own never carries the meaning. The grey line under each name is what the model calls it.</p>
<div class="rbars">{bars}</div></div></div>
<div class="grid g-2" style="margin-top:14px">
<div class="card"><h3>What each problem is worth</h3>
<p class="sub">Two different measures, drawn on two scales rather than one - putting them on the same bar would suggest they can be added together, and they cannot.</p>
<p class="mini-h">Sales at stake &middot; what these products sold in 3 months</p>
<div class="rbars">{sales_bars}</div>
<p class="mini-h">Stock still to arrive &middot; what it will cost</p>
<div class="rbars">{arrive_bars}</div>
<p class="note">The sales figures say what is at risk if the shelf stays empty, not what has already been lost.</p></div>
<div class="card"><h3>Currency and coverage</h3>
<p class="sub">Every figure on this page.</p>
<p class="note">All money on this page is {_e(currency)}. Figures cover the five shops (ST1-ST5) only; the two warehouses hold stock but are never counted into a sales or shelf total.</p></div>
</div>
<div class="caveats"><h3>What these figures cover, and what they do not</h3><ul>{caveats}</ul></div>"""


def _selling_body(view: dict, currency: str) -> str:
    rules = view["rules"]
    parts = []

    top = rules.get("top_performers") or []
    if top:
        by_dept: dict[str, list] = {}
        for row in top:
            by_dept.setdefault(row["department"], []).append(row)
        parts.append('<div class="sect"><h2>The best sellers in each department</h2>'
                    '<span>last 4 weeks</span></div><div class="grid g-2e">')
        for dept, rows in by_dept.items():
            body = []
            for row in sorted(rows, key=lambda r: r["rank"]):
                rank_cls = "rank r1" if row["rank"] == 1 else "rank"
                body.append([
                    f'<span class="{rank_cls}">{row["rank"]}</span> {row["description"]}',
                    row["category"], f"{currency} {row['sales_1m']:,.0f}",
                    f"{row['qty_1m']:,.0f}",
                ])
            table = _table(["Product", "Category", "Sold, 4 weeks", "Units"], body, num_cols={2, 3})
            parts.append(f'<div class="card"><h3>{_e(dept)}</h3>'
                        f'<p class="sub">Top 3 products sold, added across the shops that carry them.</p>'
                        f'{table}</div>')
        parts.append("</div>")

    best_day = rules.get("best_day_yesterday") or []
    if best_day:
        rows = [[r["sku"], r["location"], f"{currency} {r['sales_value']:,.2f}",
                f"{r['sales_qty']:,.0f}"] for r in best_day[:10]]
        table = _table(["SKU", "Shop", "Sold that day", "Units"], rows, num_cols={2, 3})
        parts.append(
            '<div class="sect"><h2>A single strong day</h2><span>yesterday</span></div>'
            f'<div class="grid"><div class="card"><h3>Products that had their best day yesterday</h3>'
            '<p class="sub">A product only appears if yesterday beat every other day in its tracked '
            "window - not the same as yesterday's biggest sellers. Steady high-volume staples usually "
            'peaked on an earlier bulk-buy day and never show up here.</p>'
            f'{table}</div></div>')

    at_floor = rules.get("at_price_floor") or []
    if at_floor:
        rows = [[r["description"], r["location"], f"{r['price']:,.2f}",
                f"{r['min_price_90d']:,.2f}-{r['max_price_90d']:,.2f}",
                f"{currency} {r['sales_3m']:,.0f}"] for r in at_floor[:10]]
        table = _table(["Product", "Shop", "Price now", "90-day range", "Sold, 3 months"],
                       rows, num_cols={2, 3, 4})
        parts.append(
            '<div class="sect"><h2>Currently marked down</h2><span>at the 90-day price floor</span></div>'
            f'<div class="grid"><div class="card"><h3>At the cheapest point in 90 days</h3>'
            '<p class="sub">This states that a markdown is active, not that it caused any change in sales.</p>'
            f'{table}</div></div>')

    rank_movers = rules.get("rank_movers") or {}
    if rank_movers and not rank_movers.get("available", True):
        parts.append(
            '<div class="sect"><h2>One thing this report cannot answer yet</h2>'
            '<span>and what would fix it</span></div>'
            '<div class="grid"><div class="pendcard"><div class="pend-h">'
            '<h3>Which products climbed or fell in their category</h3>'
            '<span class="pill pill-neutral">Not available yet</span></div>'
            f'<p><b>Why it is not here.</b> {_e(rank_movers.get("reason", ""))}</p>'
            f'<p><b>What would fix it.</b> {_e(rank_movers.get("action", ""))}</p>'
            '</div></div>')

    if not view.get("rules_available"):
        parts.append('<div class="card"><p class="note">The eight insight rules were not computed '
                    'this run (no live connection) - this layer is only available on a live run.</p></div>')

    return "".join(parts)


def _action_body(view: dict, currency: str) -> str:
    rules = view["rules"]
    parts = []

    stockouts = rules.get("segment_a_stockouts") or {}
    if stockouts.get("count"):
        rows = [[r["description"], r["category"], r["location"],
                f"{currency} {r['sales_3m']:,.0f}",
                (f"{currency} {r['opp_loss']:,.0f}" if r.get("opp_loss") is not None else "-")]
               for r in stockouts.get("top") or []]
        table = _table(["Product", "Category", "Shop", "Sold, 3 months", "Est. loss/day"],
                       rows, num_cols={3, 4})
        parts.append(
            '<div class="sect"><h2>Shelves with a gap</h2>'
            '<span>the two problems that cost sales</span></div>'
            f'<div class="grid"><div class="card"><h3>Best sellers with an empty shelf</h3>'
            f'<p class="sub">{stockouts["count"]:,} Segment A Loc-SKUs are out of stock, an estimated '
            f'{currency} {stockouts.get("opp_loss_total", 0):,.0f} of Opportunity Loss (rows the model '
            'could not estimate are excluded, not counted as zero).</p>'
            f'{table}</div></div>')

    verge = rules.get("verge_stockout_in_warehouse") or []
    if verge:
        rows = [[r["description"], r["category"], r["location"],
                f"{r['current_stock']:,.0f}", f"{currency} {r['sales_3m']:,.0f}"]
               for r in verge[:10]]
        table = _table(["Product", "Category", "Shop", "Units left", "Sold, 3 months"],
                       rows, num_cols={3, 4})
        parts.append(
            '<div class="grid" style="margin-top:14px"><div class="card">'
            '<h3>Almost gone - but the stock already exists</h3>'
            f'<p class="sub">{len(verge)} lines are close to running out while the same product is '
            'sitting in a warehouse. Nothing needs buying; it needs moving.</p>'
            f'{table}</div></div>')

    non_moving = rules.get("non_moving_pending_order") or []
    overstock = rules.get("overstock_pending_order") or []
    if non_moving or overstock:
        parts.append(
            '<div class="sect"><h2>Orders worth a second look</h2>'
            '<span>stock is arriving that may not be needed</span></div><div class="grid g-2">')
        if non_moving:
            rows = [[r["description"], r["location"], f"{currency} {r['pending_value']:,.0f}",
                    f"{r['days_no_sale']:,.0f}"] for r in non_moving[:15]]
            table = _table(["Product", "Shop", "On order", "Days since last sale"],
                           rows, num_cols={2, 3})
            parts.append(f'<div class="card"><h3>Non-moving, with stock already on order</h3>{table}</div>')
        if overstock:
            rows = [[r["description"], r["location"], f"{currency} {r['excess_value']:,.0f}",
                    f"{currency} {r['pending_value']:,.0f}"] for r in overstock[:10]]
            table = _table(["Product", "Shop", "Excess already held", "More on order"],
                           rows, num_cols={2, 3})
            parts.append(f'<div class="card"><h3>Overstocked, with more already on order</h3>{table}</div>')
        parts.append("</div>")

    if not view.get("rules_available"):
        parts.append('<div class="card"><p class="note">The eight insight rules were not computed '
                    'this run (no live connection) - this layer is only available on a live run.</p></div>')

    return "".join(parts)


def _detail_body(view: dict, currency: str) -> str:
    detail = view.get("detail")
    if not detail:
        return ('<div class="card"><p class="note">Department and shop detail was not computed '
               'this run (no live connection) - this layer is only available on a live run.</p></div>')

    dept_rows = [[d["key"], f"{d['products']:,}", f"{d['lines']:,}",
                 f"{currency} {d['sales_1m']:,.0f}", f"{currency} {d['sales_3m']:,.0f}",
                 f"{currency} {d['stock_value']:,.0f}", f"{currency} {d['excess_value']:,.0f}"]
                for d in detail["departments"]]
    dept_table = _table(
        ["Department", "Products", "Lines", "Sold, 1 month", "Sold, 3 months",
         "Stock value", "Excess value"], dept_rows, num_cols={1, 2, 3, 4, 5, 6})

    shop_rows = [[s["key"], f"{s['products']:,}", f"{currency} {s['sales_1m']:,.0f}",
                 f"{currency} {s['sales_3m']:,.0f}", f"{currency} {s['stock_value']:,.0f}",
                 f"{currency} {s['excess_value']:,.0f}"] for s in detail["shops"]]
    shop_table = _table(
        ["Shop", "Products", "Sold, 1 month", "Sold, 3 months", "Stock value", "Excess value"],
        shop_rows, num_cols={1, 2, 3, 4, 5})

    quiet = detail.get("quiet_shop")
    quiet_html = (
        f'<div class="spot">{_e(quiet["key"])} sold nothing in the last month, despite '
        f'{currency} {quiet["sales_3m"]:,.0f} of sales in the last 3 months - worth checking '
        f'whether it is still trading normally.</div>' if quiet else "")

    wh_rows = [[w["location"], f"{w['lines']:,}", f"{currency} {w['stock_value']:,.0f}"]
              for w in detail["warehouses"]]
    wh_table = _table(["Warehouse", "Lines", "Stock value"], wh_rows, num_cols={1, 2})

    state_rows = [[row["label"], f"{row['rows']:,}", f"{currency} {row['sales_3m']:,.0f}",
                  f"{currency} {row['stock_value']:,.0f}"] for row in detail["states"]]
    state_table = _table(["Status", "Lines", "Sold, 3 months", "Stock value"],
                         state_rows, num_cols={1, 2, 3})

    return f"""<div class="sect"><h2>Every department</h2><span>never truncated</span></div>
<div class="grid"><div class="card">
<p class="sub">Every department that carries stock in the five shops, ranked by 3-month sales.</p>
{dept_table}</div></div>
<div class="sect"><h2>Every shop</h2><span>never truncated</span></div>
<div class="grid"><div class="card">
<p class="sub">All five shops, ranked by 3-month sales.</p>
{shop_table}{quiet_html}</div></div>
<div class="grid g-2" style="margin-top:14px">
<div class="card"><h3>The two warehouses</h3>
<p class="sub">Reference only - warehouses hold stock but do not sell, so they are never added into a shop total. They appear elsewhere only when a warehouse is the fix for a shop's empty shelf.</p>
{wh_table}</div>
<div class="card"><h3>Every status, in full</h3>
<p class="sub">The same breakdown the Overview rank bars show, as a complete table with the sales figure the bars alone cannot carry.</p>
{state_table}</div>
</div>"""


def _product_body(product: dict | None, currency: str) -> str:
    if not product:
        return ('<div class="card"><p class="note">No action rule had a candidate to feature today - '
               'a genuinely quiet day, not a missing computation.</p></div>')

    subject = product["subject"]
    totals = product["totals"]
    status = product["status"]
    weekly = product["weekly_chart"]
    price = product["price"]
    category = product.get("category")

    header = f"""<div class="hero"><div><span class="hero-tag">One product in full</span>
<h2>{_e(subject["description"])}</h2>
<p>{_e(subject["sku_code"])} &middot; {_e(subject.get("category") or "")} &middot; {_e(subject["reason"])}</p></div>
<div class="hero-stats">
<div class="hs"><b>{currency} {totals["stock_value"]:,.0f}</b><span>stock value, all shops</span></div>
<div class="hs crit"><b>{currency} {totals["opp_loss"]:,.0f}</b><span>estimated Opportunity Loss/day</span></div>
<div class="hs"><b>{totals["shops_with_stock"]}/{totals["shops_with_stock"] + totals["shops_out"]}</b><span>shops carrying stock today</span></div>
</div></div>"""

    status_rows = [[s["location"], s["label"], f"{s['current_stock']:,.0f}",
                    f"{currency} {s['sales_3m']:,.0f}",
                    (f"{s['burnout']:,.0f} days" if s.get("burnout") is not None else "-"),
                    (f"{currency} {s['opp_loss']:,.0f}" if s.get("opp_loss") is not None else "-")]
                   for s in status]
    status_table = _table(
        ["Shop", "Status", "Units on shelf", "Sold, 3 months", "Days of stock left", "Est. loss/day"],
        status_rows, num_cols={2, 3, 4, 5})

    peak_qty = max((w["qty"] for w in weekly), default=0.0) or 1.0
    bars = "".join(
        f'<div class="wk-bar"><span class="wk-val">{w["qty"]:,.0f}</span>'
        f'<span class="wk-fill" style="height:{max(w["height_pct"], 2.0):.1f}%"></span>'
        f'<span class="wk-lab">{_e(w["label"])}</span></div>'
        for w in weekly)
    weekly_html = (
        f'<div class="wk">{bars}</div>' if weekly else
        '<p class="note">No weekly sales history is available for this product yet.</p>')

    per_shop_price = price.get("per_shop") or []
    price_html = ""
    if per_shop_price:
        rows = [[p["location"], f"{p['price']:,.2f}"] for p in per_shop_price]
        price_table = _table(["Shop", "Price now"], rows, num_cols={1})
        range_note = (
            f'<p class="note">Priced between {price["min_90d"]:,.2f} and {price["max_90d"]:,.2f} '
            f'over the last 90 days.</p>'
            if price.get("min_90d") is not None and price.get("max_90d") is not None else "")
        price_html = price_table + range_note
    else:
        price_html = '<p class="note">No current price is recorded for this product.</p>'

    category_html = ""
    if category:
        share = product.get("share_of_category_pct")
        vs_avg = product.get("vs_category_avg_pct")
        share_line = (f"<li>This product is {share:.1f}% of its category's 3-month sales "
                     f"({_e(category['category'])}, {category['cat_skus']:,} products).</li>"
                     if share is not None else "")
        avg_line = (f"<li>It sold {'more' if vs_avg >= 0 else 'less'} than the category's average "
                   f"product by {abs(vs_avg):.1f}% over 3 months "
                   f"(category average: {currency} {category['avg_sales_3m_per_sku']:,.0f}).</li>"
                   if vs_avg is not None else "")
        category_html = f'<div class="card"><h3>Compared to its category</h3><ul class="note">{share_line}{avg_line}</ul></div>'

    return f"""{header}
<div class="sect"><h2>Status in every shop</h2><span>today</span></div>
<div class="grid"><div class="card">{status_table}</div></div>
<div class="grid g-2" style="margin-top:14px">
<div class="card"><h3>Weekly sales, all shops combined</h3>
<p class="sub">As many recent weeks as the model has recorded.</p>
{weekly_html}</div>
<div class="card"><h3>Price</h3>
<p class="sub">Current price per shop and where it sits against its own 90-day range.</p>
{price_html}</div>
</div>
{f'<div class="grid" style="margin-top:14px">{category_html}</div>' if category_html else ""}"""


def _view_wrap(page: dict, body_fn) -> str:
    views = page["views"]
    all_html = body_fn(views["all"])
    top = views.get("top")
    if not top:
        return f'<div class="view" data-view="all">{all_html}</div>'
    top_html = body_fn(top)
    return (f'<div class="view" data-view="all">{all_html}</div>'
           f'<div class="view" data-view="top" hidden>{top_html}</div>')


def render(page: dict, *, eyebrow: str = "Inventory") -> str:
    layers = [
        ("overview", "Overview"),
        ("selling", "What is selling"),
        ("action", "What needs action"),
        ("detail", "Departments and shops"),
        ("product", "One product in full"),
    ]
    current_attr = ' aria-current="true"'
    nav = "".join(
        f'<button data-nav="{key}"{current_attr if i == 0 else ""}>{_e(label)}</button>'
        for i, (key, label) in enumerate(layers))

    title = _e(page.get("title") or "SKU Overview")
    as_at = _e(str(page.get("period_label") or page.get("as_at") or ""))
    currency = _e(page.get("currency") or "")
    period_label = str(page.get("period_label") or "")

    overview_html = _view_wrap(page, lambda v: _overview_body(v, currency, period_label))
    selling_html = _view_wrap(page, lambda v: _selling_body(v, currency))
    action_html = _view_wrap(page, lambda v: _action_body(v, currency))
    detail_html = _view_wrap(page, lambda v: _detail_body(v, currency))
    product_html = _product_body(page.get("product"), currency)

    body = (
        f'<div class="layer" data-layer="overview">{overview_html}</div>'
        f'<div class="layer" data-layer="selling" hidden>{selling_html}</div>'
        f'<div class="layer" data-layer="action" hidden>{action_html}</div>'
        f'<div class="layer" data-layer="detail" hidden>{detail_html}</div>'
        f'<div class="layer" data-layer="product" hidden>{product_html}</div>'
    )

    view_toggle = ""
    if page["views"].get("top"):
        view_toggle = (
            '<div class="viewbar">'
            '<button data-viewbtn="all" aria-current="true">All products</button>'
            '<button data-viewbtn="top">Best sellers only</button>'
            '</div>')

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
<p class="foot">Figures are the live position {as_at}.</p>
</nav>
<main><div class="page">
<div class="masthead"><div>
<p class="eyebrow">{_e(eyebrow)} &middot; product by shop</p>
<h1>{title}</h1>
<p class="asat">{as_at} &middot; ST1, ST2, ST3, ST4, ST5 &middot; all money in {currency}</p>
{view_toggle}
</div></div>
{body}
</div></main>
</div>
<script>{_SCRIPT}</script>
</body>
</html>"""
