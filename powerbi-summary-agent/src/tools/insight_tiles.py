"""Renders detected insight signals as a standalone HTML tile board.

Each tile = a bold heading + a data-driven inline-SVG chart + a "See more"
disclosure (native <details>, zero JavaScript) that reveals the full
synthesized insight paragraph.

Design contract:
  * Dependency-free (no external libs, no JS), light/dark aware, corporate-navy
    chrome matching html_report.py; diverging blue/red data palette (dataviz).
  * The chart per tile is chosen DETERMINISTICALLY from each signal's OWN
    structured data (impact/share, price-volume decomposition, breakdown rows).
    No number is ever parsed out of prose -- the prose supplies only the heading
    and the see-more text. This is why the board regenerates correctly for any
    future run's signals, not just this one.

Chart resolver (first match wins):
    concentration signal              -> donut (share vs rest)
    current-only signal (no prior)    -> KPI + "not comparable" badge
    overall price/volume decomposition-> waterfall (volume -> rate -> net)
    breakdown rows available          -> diverging bar (top movers)
    signal-level decomposition        -> waterfall
    (floor, always works)             -> KPI + share meter
"""

import html
import re
from datetime import datetime, timezone

# Emoji strip (mirrors html_report.py -- prompts forbid them, strip defensively).
_EMOJI = re.compile(
    "[" "\U0001F000-\U0001FAFF" "☀-➿" "⬀-⯿"
    "️" "‍" "]+"
)
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _human(n):
    """Compact business number: 4193897 -> '4.2M', -184939 -> '-184.9K'."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    sign = "-" if n < 0 else ""
    a = abs(n)
    if a >= 1e6:
        return f"{sign}{a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}{a / 1e3:.0f}K"
    if a >= 1:
        return f"{sign}{a:.0f}"
    return f"{sign}{a:.2f}"


def _pct(n):
    try:
        return f"{float(n):.1f}%"
    except (TypeError, ValueError):
        return str(n)


def _inline(text):
    text = _EMOJI.sub("", text)
    text = html.escape(text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


# --------------------------------------------------------------------------- #
# Structured-data extraction (no prose)
# --------------------------------------------------------------------------- #
def _dim_key(row):
    for k, v in row.items():
        if isinstance(v, str):
            return k
    return next(iter(row))


def _tables(clean_data, coverage):
    """query_name -> rows, merged from both structured scan artifacts."""
    out = {}
    for src in (coverage, clean_data):
        for q in (src or {}).get("queries", []) or []:
            name = q.get("query_name")
            rows = q.get("rows")
            if name and isinstance(rows, list):
                out.setdefault(name, rows)
    return out


def _metric_for_signal(sig, stat):
    cid = sig.get("candidate_id")
    pool = (stat.get("business_candidates") or []) + (stat.get("data_quality_candidates") or [])
    for c in pool:
        if c.get("id") == cid and c.get("metric"):
            return c["metric"]
    desc = sig.get("description") or ""
    if "QTY Growth" in desc or "net qty" in desc:
        return "QTY Growth"
    return "revenue Growth"


def _breakdown_rows(sig, inv, tables, metric):
    """Prefer the investigator's within-segment probe rows; else the signal's
    evidence_query scan table (peer ranking). Returns (rows, source)."""
    if inv:
        for p in inv.get("probes", []) or []:
            if p.get("tool") == "run_dax":
                rows = p.get("rows")
                if isinstance(rows, list) and rows and any(metric in r for r in rows):
                    return rows, "probe"
    eq = sig.get("evidence_query")
    if eq and eq in tables:
        rows = tables[eq]
        if rows and any(metric in r for r in rows):
            return rows, "peer"
    return None, None


def _mover_items(rows, metric, top_each=4):
    items = []
    for r in rows:
        if metric not in r:
            continue
        try:
            v = float(r[metric])
        except (TypeError, ValueError):
            continue
        if v != v:  # NaN
            continue
        items.append((str(r[_dim_key(r)]), v))
    items.sort(key=lambda x: x[1])
    neg = [x for x in items if x[1] < 0][:top_each]
    pos = [x for x in items if x[1] > 0][-top_each:]
    sel = neg + pos if (neg or pos) else items[:top_each]
    sel.sort(key=lambda x: x[1], reverse=True)
    return sel


def _pv_steps(d):
    try:
        vol = float(d["volume_effect"])
        rate = float(d["rate_effect"])
        net = float(d["revenue_change"])
    except (TypeError, ValueError, KeyError):
        return None
    return [("Volume effect", vol, "flow"),
            ("Rate effect", rate, "flow"),
            ("Net change", net, "total")]


def _resolve_chart(sig, inv, stat, tables):
    cid = sig.get("candidate_id") or ""
    sid = sig.get("id") or ""
    seg = sig.get("affected_segment") or ""
    metric = _metric_for_signal(sig, stat)

    if "concentration" in cid or "concentration" in sid:
        return {"type": "donut", "share": sig.get("impact_share"),
                "members": sig.get("segment_members") or [seg],
                "value": sig.get("impact_value"), "metric": metric}

    # Recent-week (Phase 3 calendar / Phase 3b rolling): a KPI of the completed
    # window's value + its delta % (never a "share of change" - that share does
    # not exist for a weekly/rolling move). Calendar and rolling share the same
    # payload/tile type; only wording differs via window_mode.
    rw = sig.get("recent_week")
    if rw:
        return {"type": "week_kpi", "value": rw.get("actual"),
                "change_pct": rw.get("change_pct"), "week_start": rw.get("week_start"),
                "window_mode": rw.get("window_mode", "calendar"), "metric": metric}

    # Daily anomaly incident (Phase 3b): a KPI of the incident's actual value +
    # its deviation from what was expected. Checked via episode_start/end
    # rather than id/candidate_id naming, since those are the fields
    # _copy_candidate_facts reliably sets for this signal type.
    if sig.get("episode_start") is not None and sig.get("episode_end") is not None:
        expected = sig.get("expected_total")
        impact = sig.get("impact_value")
        change_pct = (impact / abs(expected) * 100.0
                      if isinstance(expected, (int, float)) and expected
                      and isinstance(impact, (int, float)) else None)
        actual = sig.get("actual_total") if sig.get("actual_total") is not None else impact
        label = f"{sig.get('episode_start')}..{sig.get('episode_end')}"
        return {"type": "week_kpi", "value": actual, "change_pct": change_pct,
                "week_start": label, "window_mode": "daily", "metric": metric}

    if "current_only" in cid or sig.get("impact_share") is None:
        return {"type": "badge", "value": sig.get("impact_value"),
                "label": seg, "badge": "New store - not comparable", "metric": metric}

    opv = stat.get("overall_price_volume") or []
    if seg.lower() == "overall" or sid.startswith("overall"):
        steps = _pv_steps(opv[0]) if opv else None
        if steps:
            return {"type": "waterfall", "steps": steps, "metric": metric}

    rows, source = _breakdown_rows(sig, inv, tables, metric)
    if rows:
        items = _mover_items(rows, metric)
        if items:
            return {"type": "bar", "items": items, "metric": metric,
                    "highlight": seg if source == "peer" else None}

    decomp = sig.get("decomposition")
    if decomp:
        steps = _pv_steps(decomp[0])
        if steps:
            return {"type": "waterfall", "steps": steps, "metric": metric}

    return {"type": "meter", "value": sig.get("impact_value"),
            "share": sig.get("impact_share"), "metric": metric}


# --------------------------------------------------------------------------- #
# SVG chart builders  (viewBox coords; width:100% scales into the card)
# --------------------------------------------------------------------------- #
def _svg_open(w, h):
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" '
            f'role="img" preserveAspectRatio="xMidYMid meet" '
            f'font-family="Segoe UI, system-ui, sans-serif">')


def _t(x, y, s, cls, anchor="start", size=11, weight="400"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'font-size="{size}" font-weight="{weight}" class="{cls}">'
            f'{html.escape(s)}</text>')


def _trunc(s, n=30):
    return s if len(s) <= n else s[: n - 1] + "…"


def _svg_diverging_bar(spec):
    items = spec["items"]
    hi = (spec.get("highlight") or "").lower()
    W, rowH, pad = 340, 30, 12
    H = pad + rowH * len(items) + 6
    cx = 168.0
    maxabs = max((abs(v) for _, v in items), default=1) or 1
    scale = 150.0 / maxabs
    out = [_svg_open(W, H)]
    out.append(f'<line x1="{cx}" y1="{pad}" x2="{cx}" y2="{H-6}" class="axis"/>')
    for i, (label, v) in enumerate(items):
        top = pad + i * rowH
        bar_y = top + 12
        w = abs(v) * scale
        pos = v >= 0
        x = cx if pos else cx - w
        cls = "pos" if pos else "neg"
        emph = ' data-hi="1"' if hi and label.lower() == hi else ""
        weight = "700" if emph else "400"
        out.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{max(w,1):.1f}" height="11" '
                   f'rx="2.5" class="{cls}"{emph}/>')
        out.append(_t(8, top + 9, _trunc(label, 40), "lbl", size=11, weight=weight))
        # value label: outside the bar end, but flip inside (white) if it would
        # overflow the viewBox edge.
        txt = _human(v)
        est = len(txt) * 6.2
        end = (cx + w) if pos else (cx - w)
        if pos and end + est > W - 2:
            vx, va, vcls = end - 4, "end", "valin"
        elif (not pos) and end - est < 2:
            vx, va, vcls = end + 4, "start", "valin"
        else:
            vx, va, vcls = (end + 4, "start", "val") if pos else (end - 4, "end", "val")
        out.append(_t(vx, bar_y + 9.5, txt, vcls, anchor=va, size=10.5, weight="600"))
    out.append("</svg>")
    return "".join(out)


def _svg_waterfall(spec):
    steps = spec["steps"]
    W, H = 340, 188
    top, bottom = 30, 150
    running = 0.0
    floats = []  # (label, y_start_val, y_end_val, kind, delta)
    lo, high = 0.0, 0.0
    for label, val, kind in steps:
        if kind == "total":
            s, e = 0.0, val
        else:
            s, e = running, running + val
            running = e
        floats.append((label, s, e, kind, val))
        lo, high = min(lo, s, e), max(high, s, e)
    span = (high - lo) or 1.0

    def y(v):
        return bottom - (v - lo) / span * (bottom - top)

    n = len(floats)
    slot = (W - 24) / n
    bw = min(slot - 22, 54)
    out = [_svg_open(W, H)]
    out.append(f'<line x1="10" y1="{y(0):.1f}" x2="{W-10}" y2="{y(0):.1f}" class="axis"/>')
    prev_x2 = prev_y = None
    for i, (label, s, e, kind, val) in enumerate(floats):
        cxs = 12 + slot * i + (slot - bw) / 2
        py_s, py_e = y(s), y(e)
        top_px = min(py_s, py_e)          # rect top is the SMALLER pixel value
        h = max(abs(py_s - py_e), 2)
        cls = "total" if kind == "total" else ("pos" if val >= 0 else "neg")
        out.append(f'<rect x="{cxs:.1f}" y="{top_px:.1f}" width="{bw:.1f}" height="{h:.1f}" '
                   f'rx="2.5" class="{cls}"/>')
        # connector from previous bar's end to this bar's start
        if prev_x2 is not None and kind != "total":
            out.append(f'<line x1="{prev_x2:.1f}" y1="{prev_y:.1f}" x2="{cxs:.1f}" '
                       f'y2="{py_s:.1f}" class="conn"/>')
        prev_x2, prev_y = cxs + bw, py_e
        vlabel = ("+" if val >= 0 and kind != "total" else "") + _human(val)
        out.append(_t(cxs + bw / 2, top_px - 5, vlabel, "val", anchor="middle",
                      size=11, weight="600"))
        out.append(_t(cxs + bw / 2, H - 14, _trunc(label, 16), "lbl",
                      anchor="middle", size=10.5))
    out.append("</svg>")
    return "".join(out)


def _svg_donut(spec):
    share = float(spec.get("share") or 0)
    W, H, r, sw = 340, 172, 58, 24
    cx, cy = W / 2, 86
    import math
    C = 2 * math.pi * r
    frac = max(0.0, min(share, 100.0)) / 100.0
    out = [_svg_open(W, H)]
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke-width="{sw}" '
               f'class="track"/>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke-width="{sw}" '
               f'class="pos-stroke" stroke-linecap="round" '
               f'stroke-dasharray="{C*frac:.1f} {C:.1f}" '
               f'transform="rotate(-90 {cx} {cy})"/>')
    out.append(_t(cx, cy - 2, _pct(share), "big", anchor="middle", size=30, weight="700"))
    out.append(_t(cx, cy + 16, "of comparable total", "lbl", anchor="middle", size=11))
    out.append("</svg>")
    return "".join(out)


def _svg_meter(spec):
    val = spec.get("value")
    share = spec.get("share")
    W, H = 340, 120
    out = [_svg_open(W, H)]
    out.append(_t(14, 44, _human(val), "big", size=34, weight="700"))
    out.append(_t(16, 66, "impact value", "lbl", size=11))
    if share is not None:
        frac = max(0.0, min(abs(float(share)), 100.0)) / 100.0
        y = 90
        out.append(f'<rect x="14" y="{y}" width="312" height="12" rx="6" class="track-fill"/>')
        out.append(f'<rect x="14" y="{y}" width="{312*frac:.1f}" height="12" rx="6" class="pos"/>')
        over = abs(float(share)) > 100
        cap = _pct(share) + (" (offset elsewhere)" if over else "")
        out.append(_t(14, y + 28, f"{cap} of total change", "lbl", size=11))
        if over:
            out.append(f'<line x1="326" y1="{y-3}" x2="326" y2="{y+15}" class="axis"/>')
    out.append("</svg>")
    return "".join(out)


def _kpi_badge_html(spec):
    return (f'<div class="kpi"><div class="kpi-num">{html.escape(_human(spec.get("value")))}</div>'
            f'<div class="kpi-sub">current-period value</div>'
            f'<div class="chip warn">{html.escape(spec.get("badge",""))}</div></div>')


def _week_kpi_html(spec):
    mode = spec.get("window_mode", "calendar")
    cp = spec.get("change_pct")
    if isinstance(cp, (int, float)):
        arrow = "▲" if cp >= 0 else "▼"
        if mode == "rolling":
            sub = f"{arrow} {abs(cp):.1f}% vs the prior 7 days"
        elif mode == "daily":
            sub = f"{arrow} {abs(cp):.1f}% vs expected"
        else:
            sub = f"{arrow} {abs(cp):.1f}% week over week"
    else:
        sub = {"rolling": "trailing 7 days", "daily": "daily incident"}.get(
            mode, "most recent completed week")
    wk = spec.get("week_start") or ""
    if not wk:
        week_line = ""
    elif mode == "rolling":
        week_line = f'<div class="kpi-sub">trailing 7 days ending {html.escape(str(wk))}</div>'
    elif mode == "daily":
        week_line = f'<div class="kpi-sub">{html.escape(str(wk))}</div>'
    else:
        week_line = f'<div class="kpi-sub">week of {html.escape(str(wk))}</div>'
    return (f'<div class="kpi"><div class="kpi-num">{html.escape(_human(spec.get("value")))}</div>'
            f'<div class="kpi-sub">{html.escape(sub)}</div>{week_line}</div>')


def _chart_html(spec):
    t = spec["type"]
    if t == "bar":
        return _svg_diverging_bar(spec)
    if t == "waterfall":
        return _svg_waterfall(spec)
    if t == "donut":
        return _svg_donut(spec)
    if t == "meter":
        return _svg_meter(spec)
    if t == "badge":
        return _kpi_badge_html(spec)
    if t == "week_kpi":
        return _week_kpi_html(spec)
    return ""


def _legend(spec):
    t = spec["type"]
    if t in ("bar", "waterfall"):
        m = "revenue" if "revenue" in (spec.get("metric") or "") else "units"
        return (f'<div class="legend"><span><i class="sw pos"></i>increase ({m})</span>'
                f'<span><i class="sw neg"></i>decrease ({m})</span></div>')
    if t == "donut":
        return (f'<div class="legend"><span><i class="sw pos"></i>'
                f'{html.escape(", ".join(spec.get("members") or []))}</span></div>')
    return ""


# --------------------------------------------------------------------------- #
# Insight text <-> signal pairing
# --------------------------------------------------------------------------- #
def insights_from_markdown(md):
    """Return [(heading, body)] from the '# Key Insights' section only."""
    paras, cur, in_sec = [], [], False
    for raw in (md or "").replace("\r\n", "\n").split("\n"):
        s = raw.strip()
        if s.startswith("# "):
            if cur:
                paras.append(" ".join(cur)); cur = []
            in_sec = "key insight" in s.lower()
            continue
        if not in_sec:
            continue
        if not s:
            if cur:
                paras.append(" ".join(cur)); cur = []
            continue
        cur.append(s)
    if cur:
        paras.append(" ".join(cur))
    res = []
    for p in paras:
        m = re.match(r"\*\*(.+?)\*\*\s*(.*)", p, re.S)
        if m:
            res.append((m.group(1).strip(), m.group(2).strip()))
        # Key-insight paragraphs are required to begin with a bold takeaway.
        # Ignore unbolded prose such as the one-time comparison-scope sentence;
        # treating it as an insight would create an extra tile and mis-pair the
        # real paragraphs with their structured signals.
    return res


# Backward-compatible private alias for callers/tests that predate the history
# feed.  New code should use the public name so the tile board and persisted
# history cannot drift to different interpretations of an insight paragraph.
_insights_from_md = insights_from_markdown


def _shares_in(text):
    return {round(float(x), 1) for x in re.findall(r"([\d.]+)\s*%", text)}


def _score(head, body, sig):
    """How strongly a signal is the SUBJECT of a paragraph. A segment named in
    the heading (the subject) outranks a share merely cited in the body -- this
    stops the overall/rate-led paragraph, which cites a high-growth segment's
    percentage, from stealing that segment's signal."""
    seg = (sig.get("affected_segment") or "")
    members = [m for m in (sig.get("segment_members") or []) if m]
    sh = sig.get("impact_share")
    hl, bl = head.lower(), body.lower()
    s = 0.0
    if seg and seg.lower() in hl:
        s += 5 + len(seg) * 0.01           # prefer the more specific segment
    if members and all(m.lower() in hl for m in members):
        s += 4
    if sh is not None and round(abs(float(sh)), 1) in _shares_in(head + " " + body):
        s += 2
    if seg and seg.lower() in bl:
        s += 1
    return s


def _pair(paras, signals):
    """Global best-score assignment of paragraphs to signals (one-to-one), then
    the left-over/segment-less signal (typically 'overall') fills any remaining
    paragraph."""
    scored = []
    for pi, (head, body) in enumerate(paras):
        for si, sig in enumerate(signals):
            sc = _score(head, body, sig)
            if sc > 0:
                scored.append((sc, pi, si))
    scored.sort(key=lambda x: x[0], reverse=True)
    p2s, used = {}, set()
    for sc, pi, si in scored:
        if pi in p2s or si in used:
            continue
        p2s[pi] = si
        used.add(si)
    remaining = [si for si in range(len(signals)) if si not in used]
    for pi in range(len(paras)):
        if pi in p2s or not remaining:
            continue
        pick = next((si for si in remaining
                     if (signals[si].get("affected_segment") or "").lower()
                     in ("overall", "")), remaining[0])
        p2s[pi] = pick
        remaining.remove(pick)
    return [(head, body, signals[p2s[pi]] if pi in p2s else None)
            for pi, (head, body) in enumerate(paras)]


# --------------------------------------------------------------------------- #
# Page assembly
# --------------------------------------------------------------------------- #
def build_html(report_md, signals, investigations, stat_candidates,
               clean_data=None, coverage=None, title="Insight Board",
               eyebrow="Power BI Insight Report"):
    signals = signals or []
    tables = _tables(clean_data, coverage)
    inv_by_id = {}
    for iv in (investigations or []):
        sid = (iv.get("signal") or {}).get("id")
        if sid:
            inv_by_id[sid] = iv

    paras = insights_from_markdown(report_md)
    pairs = _pair(paras, signals) if paras else [
        (s.get("description", "")[:90], s.get("description", ""), s) for s in signals
    ]

    tiles = []
    for head, body, sig in pairs:
        chart_html = legend_html = metric_line = ""
        kind = "business"
        if sig:
            kind = sig.get("kind", "business")
            spec = _resolve_chart(sig, inv_by_id.get(sig.get("id")),
                                  stat_candidates or {}, tables)
            chart_html = _chart_html(spec)
            legend_html = _legend(spec)
            iv = sig.get("impact_value")
            sh = sig.get("impact_share")
            bits = []
            if iv is not None:
                bits.append(f"<strong>{html.escape(_human(iv))}</strong> impact")
            if sh is not None:
                bits.append(f"<strong>{html.escape(_pct(sh))}</strong> of total change")
            metric_line = " &middot; ".join(bits)
        chip = ('<span class="chip dq">data quality</span>'
                if kind == "data_quality" else "")
        body_html = _inline(body) if body else ""
        metric_span = f'<span class="metricline">{metric_line}</span>' if metric_line else ""
        cap = (f'<div class="cap">{legend_html}{metric_span}</div>'
               if (legend_html or metric_line) else "")
        tiles.append(f"""      <article class="tile">
        <div class="tile-head"><h3>{_inline(head)}</h3>{chip}</div>
        <div class="chart">{chart_html}</div>
        {cap}
        <details><summary></summary><p>{body_html}</p></details>
      </article>""")

    generated = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    return _PAGE.format(
        title=html.escape(_EMOJI.sub("", title)),
        eyebrow=html.escape(eyebrow),
        generated=generated,
        count=len(tiles),
        tiles="\n".join(tiles),
    )


def write_from_state(state, filename="insight_tiles.html", report_md=None):
    """Convenience used by the insight branch: pull artifacts off graph state.

    `report_md` is passed explicitly by the synthesizer node because the freshly
    generated report is not yet on `state` when the node calls this.
    """
    from . import file_io
    understanding = state.get("report_understanding") or {}
    domain = understanding.get("domain") if isinstance(understanding, dict) else None
    title = f"{domain} Insight Board" if domain else "Insight Board"
    doc = build_html(
        report_md=report_md if report_md is not None else state.get("insight_report", ""),
        signals=state.get("insight_signals", []),
        investigations=state.get("insight_investigations", []),
        stat_candidates=state.get("insight_stat_candidates", {}),
        clean_data=state.get("insight_clean_data", {}),
        coverage=state.get("baseline_coverage_clean_data", {}),
        title=title,
    )
    file_io.write_text(state, filename, doc)
    return doc


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg:#eef0f3; --panel:#ffffff; --rule:#e3e7ec; --rule-strong:#cfd6de;
    --navy:#16324f; --navy-deep:#102538; --accent:#1f4e79; --accent-soft:#eef3f8;
    --ink:#1f2937; --ink-soft:#5b6472; --ink-faint:#8a93a1;
    --pos:#2a78d6; --neg:#e34948; --total:#16324f;
    --track:#e6ebf1; --grid:#c9d2dc; --warn:#b7791f; --warn-soft:#fdf3e2;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:"Segoe UI",-apple-system,"Helvetica Neue",Arial,sans-serif;
    font-size:15px; line-height:1.6; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:0 24px 64px; }}
  header.board-header {{
    background:linear-gradient(135deg,var(--navy-deep) 0%,var(--navy) 62%,#1d3e5e 100%);
    color:#f4f7fa; padding:36px 0 30px; }}
  header.board-header .inner {{ max-width:1180px; margin:0 auto; padding:0 24px; }}
  .eyebrow {{ text-transform:uppercase; letter-spacing:.18em; font-size:11px;
    font-weight:600; color:#9db8d1; margin-bottom:8px; }}
  header.board-header h1 {{ font-size:26px; margin:0 0 12px; font-weight:650;
    letter-spacing:-.01em; }}
  header.board-header .meta {{ display:flex; gap:26px; flex-wrap:wrap; font-size:12.5px;
    color:#b9c9da; border-top:1px solid rgba(255,255,255,.16); padding-top:12px; }}
  header.board-header .meta strong {{ color:#e8eef4; font-weight:600; }}
  .grid {{ display:grid; gap:20px; margin-top:28px;
    grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); }}
  .tile {{ background:var(--panel); border:1px solid var(--rule); border-radius:8px;
    padding:18px 18px 14px; box-shadow:0 1px 2px rgba(16,37,56,.05),0 8px 22px rgba(16,37,56,.06);
    display:flex; flex-direction:column; }}
  .tile-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }}
  .tile h3 {{ font-size:14.5px; font-weight:650; color:var(--ink); margin:0 0 12px;
    line-height:1.35; }}
  .chart {{ margin:2px 0 6px; }}
  .cap {{ display:flex; justify-content:space-between; align-items:center; gap:10px;
    flex-wrap:wrap; margin-top:2px; }}
  .legend {{ display:flex; gap:14px; font-size:11px; color:var(--ink-soft); }}
  .legend .sw {{ display:inline-block; width:10px; height:10px; border-radius:2px;
    margin-right:5px; vertical-align:-1px; }}
  .legend .sw.pos {{ background:var(--pos); }}
  .legend .sw.neg {{ background:var(--neg); }}
  .metricline {{ font-size:11.5px; color:var(--ink-soft); }}
  details {{ margin-top:10px; border-top:1px solid var(--rule); padding-top:8px; }}
  summary {{ cursor:pointer; font-size:12.5px; font-weight:600; color:var(--accent);
    list-style:none; user-select:none; }}
  summary::-webkit-details-marker {{ display:none; }}
  summary::before {{ content:"\\25B8  See more"; }}
  details[open] summary::before {{ content:"\\25BE  See less"; }}
  details p {{ margin:10px 0 2px; font-size:13.5px; color:var(--ink-soft); line-height:1.65; }}
  .chip {{ font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.06em;
    padding:3px 7px; border-radius:20px; white-space:nowrap; }}
  .chip.dq {{ background:var(--warn-soft); color:var(--warn); }}
  .chip.warn {{ background:var(--warn-soft); color:var(--warn); display:inline-block; margin-top:8px; }}
  .kpi {{ text-align:center; padding:14px 0 6px; }}
  .kpi-num {{ font-size:38px; font-weight:700; color:var(--total); letter-spacing:-.02em; }}
  .kpi-sub {{ font-size:11.5px; color:var(--ink-faint); margin-top:2px; }}
  /* SVG classes */
  svg .axis {{ stroke:var(--grid); stroke-width:1; }}
  svg .conn {{ stroke:var(--grid); stroke-width:1; stroke-dasharray:2 2; }}
  svg .pos {{ fill:var(--pos); }}
  svg .neg {{ fill:var(--neg); }}
  svg .total {{ fill:var(--total); }}
  svg .track {{ stroke:var(--track); }}
  svg .track-fill {{ fill:var(--track); }}
  svg .pos-stroke {{ stroke:var(--pos); }}
  svg .lbl {{ fill:var(--ink-soft); }}
  svg .val {{ fill:var(--ink); }}
  svg .valin {{ fill:#ffffff; }}
  svg .big {{ fill:var(--total); }}
  svg [data-hi="1"] {{ stroke:var(--total); stroke-width:1.5; }}
  footer {{ margin-top:30px; font-size:11.5px; color:var(--ink-faint); line-height:1.6; }}
  @media (max-width:560px) {{ .grid {{ grid-template-columns:1fr; }} }}
  @media (prefers-color-scheme:dark) {{
    :root {{
      --bg:#14171c; --panel:#1b1f26; --rule:#313843; --rule-strong:#3d4552;
      --accent:#8fb4d9; --accent-soft:#232a33; --ink:#dde2e9; --ink-soft:#a6afbc;
      --ink-faint:#7d8794; --pos:#3987e5; --neg:#e66767; --total:#8fb4d9;
      --track:#2b333d; --grid:#3a4552; --warn:#e0a94b; --warn-soft:#33291a;
    }}
    .tile {{ box-shadow:none; }}
  }}
</style>
</head>
<body>
  <header class="board-header">
    <div class="inner">
      <div class="eyebrow">{eyebrow}</div>
      <h1>{title}</h1>
      <div class="meta">
        <span><strong>Generated</strong>&ensp;{generated}</span>
        <span><strong>Insights</strong>&ensp;{count}</span>
        <span><strong>Source</strong>&ensp;Connected Power BI semantic model</span>
      </div>
    </div>
  </header>
  <div class="wrap">
    <div class="grid">
{tiles}
    </div>
    <footer>
      Each chart is generated only from the structured evidence behind its insight
      (contribution values, price/volume decomposition, and scan breakdown rows).
      Percentages above 100% mean a segment's movement was partly offset elsewhere in the comparable base.
    </footer>
  </div>
</body>
</html>
"""
