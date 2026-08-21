"""Render the Stock Age Analysis report as one self-contained HTML file.

Same constraints as the R6 dashboard: inline CSS, inline SVG, no external
request, everything escaped. The age axis is drawn as an ordered bar because the
*order* is the finding - a pie or an unordered bar would throw away the one
thing that matters about these bands.
"""

from __future__ import annotations

from html import escape
from typing import Any

_CSS = """
:root { --ink:#12263f; --muted:#5a6b7f; --line:#dfe6ee; --bg:#ffffff;
        --fresh:#2e9e6b; --mid:#c9a227; --risk:#c0562e; --crit:#9b2c2c; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#e8eef5; --muted:#9fb0c2; --line:#2b3a4b; --bg:#0f1720; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
.wrap { max-width:1040px; margin:0 auto; padding:32px 20px 64px; }
.eyebrow { font-size:12px; letter-spacing:.12em; text-transform:uppercase;
           color:var(--muted); margin:0 0 6px; }
h1 { font-size:28px; margin:0 0 4px; }
.asat { color:var(--muted); margin:0 0 28px; font-size:14px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
        gap:12px; margin:0 0 32px; }
.kpi { border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
.kpi .label { font-size:12px; color:var(--muted); margin:0 0 4px; }
.kpi .value { font-size:22px; font-weight:600; }
.kpi .sub { font-size:12px; color:var(--muted); margin-top:2px; }
h2 { font-size:18px; margin:34px 0 10px; }
p { margin:0 0 12px; max-width:78ch; }
table { border-collapse:collapse; width:100%; font-size:14px; }
th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }
th { font-size:12px; text-transform:uppercase; letter-spacing:.06em;
     color:var(--muted); font-weight:600; }
td.n, th.n { text-align:right; font-variant-numeric:tabular-nums; }
.scroll { overflow-x:auto; }
.bar { display:flex; height:26px; border-radius:6px; overflow:hidden;
       border:1px solid var(--line); margin:6px 0 10px; }
.bar span { display:block; }
.legend { display:flex; flex-wrap:wrap; gap:14px; font-size:12px;
          color:var(--muted); margin-bottom:18px; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:2px;
            margin-right:5px; vertical-align:middle; }
.note { border-left:3px solid var(--line); padding:8px 0 8px 14px;
        color:var(--muted); font-size:13px; margin:14px 0; }
.tag { display:inline-block; font-size:11px; padding:2px 7px; border-radius:99px;
       border:1px solid var(--line); color:var(--muted); }
.tag.risk { color:var(--risk); border-color:var(--risk); }
.tag.crit { color:var(--crit); border-color:var(--crit); }
footer { margin-top:40px; padding-top:16px; border-top:1px solid var(--line);
         color:var(--muted); font-size:12px; }
@media print { body { background:#fff; } .wrap { padding:0; } }
"""

_BAND_COLOUR = {
    "0-03 MONTHS": "var(--fresh)",
    "03-06 MONTHS": "#6bbf8a",
    "06-09 MONTHS": "var(--mid)",
    "09-12 MONTHS": "#d98324",
    "12-24 MONTHS": "var(--risk)",
    "24+ MONTHS": "var(--crit)",
}


def _sar(value: Any, currency: str = "SAR") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if abs(number) >= 1_000_000:
        return f"{currency} {number / 1_000_000:.2f}M".strip()
    if abs(number) >= 1_000:
        return f"{currency} {number / 1_000:.0f}K".strip()
    return f"{currency} {number:,.0f}".strip()


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "-"


def _e(value: Any) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def render(report: dict, eyebrow: str = "Inventory") -> str:
    header = report.get("header") or {}
    bands = (report.get("distribution") or {}).get("bands") or []
    split = report.get("risk_split") or {}
    currency = str(report.get("currency") or "SAR")

    parts: list[str] = []
    parts.append(f"<style>{_CSS}</style>")
    parts.append('<div class="wrap">')
    parts.append(f'<p class="eyebrow">{_e(eyebrow)}</p>')
    parts.append(f"<h1>{_e(report.get('report_name'))}</h1>")
    # Non-negotiable 18: the position is stated as at a date, never as a span.
    parts.append(f'<p class="asat">Stock position {_e(report.get("period_label"))}'
                 f' &middot; {int(header.get("locations") or 0)} locations'
                 f' &middot; {int(header.get("skus") or 0):,} SKUs</p>')

    parts.append('<div class="kpis">')
    for label, value, sub in (
        ("Stock value", _sar(header.get("total_value"), currency), "all locations"),
        ("Aged stock", _sar(header.get("aged_value"), currency),
         f"{_pct(header.get('aged_share_pct'))} of stock value"),
        ("High-risk (12+ months)", _sar(header.get("high_risk_value"), currency),
         f"{_pct(header.get('high_risk_share_pct'))} of stock value"),
        ("Aged and non-moving", _sar(header.get("aged_non_moving"), currency),
         "highest-risk combination"),
    ):
        parts.append(f'<div class="kpi"><p class="label">{_e(label)}</p>'
                     f'<div class="value">{_e(value)}</div>'
                     f'<div class="sub">{_e(sub)}</div></div>')
    parts.append("</div>")

    # --- the age profile, drawn in order because the order IS the finding ---
    parts.append("<h2>Where the stock sits by age</h2>")
    total = float(header.get("total_value") or 0) or 1.0
    parts.append('<div class="bar">')
    for band in bands:
        width = max(0.0, float(band.get("value") or 0)) / total * 100.0
        colour = _BAND_COLOUR.get(str(band.get("name", "")).upper(), "var(--muted)")
        parts.append(
            f'<span style="width:{width:.4f}%;background:{colour}" '
            f'title="{_e(band.get("name"))}: {_e(_sar(band.get("value"), currency))}"></span>')
    parts.append("</div>")
    parts.append('<div class="legend">')
    for band in bands:
        colour = _BAND_COLOUR.get(str(band.get("name", "")).upper(), "var(--muted)")
        parts.append(f'<span><i style="background:{colour}"></i>'
                     f'{_e(band.get("name"))} {_e(_pct(band.get("share_pct")))}</span>')
    parts.append("</div>")

    parts.append('<div class="scroll"><table><thead><tr>'
                 '<th>Age band</th><th class="n">Stock value</th>'
                 '<th class="n">Share</th><th class="n">Of which aged</th>'
                 '<th class="n">This band or older</th><th></th>'
                 "</tr></thead><tbody>")
    for band in sorted(bands, key=lambda b: b.get("cumulative_older_pct") or 0):
        tag = ""
        if band.get("high_risk"):
            crit = str(band.get("name", "")).upper().startswith("24+")
            tag = (f'<span class="tag {"crit" if crit else "risk"}">'
                   f'{"write-off risk" if crit else "high risk"}</span>')
        parts.append(
            f'<tr><td>{_e(band.get("name"))}</td>'
            f'<td class="n">{_e(_sar(band.get("value"), currency))}</td>'
            f'<td class="n">{_e(_pct(band.get("share_pct")))}</td>'
            f'<td class="n">{_e(_sar(band.get("aged_value"), currency))}</td>'
            f'<td class="n">{_e(_pct(band.get("cumulative_older_pct")))}</td>'
            f"<td>{tag}</td></tr>")
    parts.append("</tbody></table></div>")

    # --- narrative, in the rulebook's order ---
    parts.append("<h2>What stands out</h2>")
    for line in report.get("narrative") or []:
        parts.append(f"<p>{_e(line)}</p>")

    # --- aged x non-moving, kept as four cells so nothing is double-counted ---
    parts.append("<h2>Aged and non-moving are separate things</h2>")
    parts.append('<div class="scroll"><table><thead><tr><th></th>'
                 '<th class="n">Not selling</th><th class="n">Still selling</th>'
                 "</tr></thead><tbody>")
    parts.append(f'<tr><td>Aged</td><td class="n">{_e(_sar(split.get("aged_non_moving"), currency))}</td>'
                 f'<td class="n">{_e(_sar(split.get("aged_moving"), currency))}</td></tr>')
    parts.append(f'<tr><td>Not aged</td><td class="n">{_e(_sar(split.get("fresh_non_moving"), currency))}</td>'
                 f'<td class="n">{_e(_sar(split.get("fresh_moving"), currency))}</td></tr>')
    parts.append("</tbody></table></div>")
    parts.append('<p class="note">These two measures overlap, so they are never '
                 "added together into a single at-risk figure.</p>")

    for title, key, first in (("Divisions holding the most aged stock", "divisions", "Division"),
                              ("Locations holding the most aged stock", "locations", "Location"),
                              ("Sections holding the most aged stock", "sections", "Section")):
        rows = report.get(key) or []
        if not rows:
            continue
        parts.append(f"<h2>{_e(title)}</h2>")
        parts.append(f'<div class="scroll"><table><thead><tr><th>{_e(first)}</th>'
                     '<th class="n">Aged stock</th><th class="n">Stock value</th>'
                     '<th class="n">Aged share</th></tr></thead><tbody>')
        for row in rows:
            value = float(row.get("total") or 0)
            share = (float(row.get("value") or 0) / value * 100.0) if value else None
            parts.append(f'<tr><td>{_e(row.get("name"))}</td>'
                         f'<td class="n">{_e(_sar(row.get("value"), currency))}</td>'
                         f'<td class="n">{_e(_sar(value, currency))}</td>'
                         f'<td class="n">{_e(_pct(share))}</td></tr>')
        parts.append("</tbody></table></div>")

    sku_types = report.get("sku_types") or []
    if sku_types:
        parts.append("<h2>Locally bought against imported</h2>")
        parts.append('<div class="scroll"><table><thead><tr><th>Type</th>'
                     '<th class="n">Stock value</th><th class="n">Aged stock</th>'
                     '<th class="n">Aged share</th></tr></thead><tbody>')
        for row in sku_types:
            value = float(row.get("value") or 0)
            share = (float(row.get("aged") or 0) / value * 100.0) if value else None
            parts.append(f'<tr><td>{_e(row.get("name"))}</td>'
                         f'<td class="n">{_e(_sar(value, currency))}</td>'
                         f'<td class="n">{_e(_sar(row.get("aged"), currency))}</td>'
                         f'<td class="n">{_e(_pct(share))}</td></tr>')
        parts.append("</tbody></table></div>")

    # --- limitations, stated rather than left for the reader to discover ---
    parts.append("<h2>What this report does not show</h2>")
    migration = report.get("migration") or {}
    if not migration.get("available"):
        parts.append(f'<p class="note">{_e(migration.get("reason"))}</p>')
    for caveat in report.get("caveats") or []:
        parts.append(f'<p class="note">{_e(caveat)}</p>')
    parts.append('<p class="note">This report shows how old stock is and which '
                 "aged stock is not selling. It does not say why stock is "
                 "ageing, or what to do about it.</p>")

    failed = [name for name, ok in (report.get("checks") or {}).items() if not ok]
    if failed:
        parts.append('<p class="note">Some figures did not reconcile and are '
                     f"withheld: {_e(', '.join(failed))}.</p>")

    parts.append(f"<footer>Stock position {_e(report.get('period_label'))}. "
                 f"All values are {_e(currency)} at landing cost, excluding VAT.</footer>")
    parts.append("</div>")
    return "\n".join(parts)
