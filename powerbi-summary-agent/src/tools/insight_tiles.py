"""Shared insight markdown parser + deterministic chart-spec helpers.

The standalone HTML tile board (``insight_tiles.html``) was removed; nothing
generates that artifact any more. What remains here is reused elsewhere and
must stay:

  * ``insights_from_markdown`` / ``_insights_from_md`` - the '# Key Insights'
    heading/body parser shared with ``insight_history`` (so the history screen
    and any consumer interpret an insight paragraph identically) and exercised
    by the offline replay tests.
  * the deterministic chart-spec / inline-SVG helpers (``_resolve_chart``,
    ``_rate_kpi_html``, the ``_svg_*`` builders, ...), which the rate-outlier
    replay test uses to validate chart selection from a signal's OWN structured
    data (never parsed from prose).
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

    # Peer-growth rate outlier (Phase 8): a KPI of the segment's own growth % plus
    # the careful "unusually fast relative to N peers" sub-line and the peer median.
    # `stat_basis` is set ONLY on this signal type, so it is a safe discriminator -
    # checked BEFORE the impact_share-is-None branch below (a rate signal has no
    # annual share and would otherwise fall into the current-only badge).
    if sig.get("stat_basis") and isinstance(sig.get("reported_growth_pct"), (int, float)):
        return {"type": "rate_kpi", "growth_pct": sig.get("reported_growth_pct"),
                "peer_median": sig.get("peer_median_reported_pct"),
                "peer_count": sig.get("peer_count"), "metric": metric}

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


def _rate_kpi_html(spec):
    g = spec.get("growth_pct")
    num = (("+" if g >= 0 else "") + _pct(g)) if isinstance(g, (int, float)) else "-"
    n = spec.get("peer_count")
    sub = (f"unusually fast relative to {n} peers" if isinstance(n, int) and n > 0
           else "unusually fast relative to peers")
    med = spec.get("peer_median")
    med_line = (f'<div class="kpi-sub">peer median {med:+.1f}%</div>'
                if isinstance(med, (int, float)) else "")
    return (f'<div class="kpi"><div class="kpi-num">{html.escape(num)}</div>'
            f'<div class="kpi-sub">{html.escape(sub)}</div>{med_line}</div>')


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
    if t == "rate_kpi":
        return _rate_kpi_html(spec)
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
