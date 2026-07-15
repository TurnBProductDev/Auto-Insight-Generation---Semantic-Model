"""Renders the final Markdown report as a standalone, professional HTML document.

No external Markdown library is used (none is in requirements.txt) — the
reports' shape is fixed and simple (H1 section headers, paragraphs, `-`
bullet lists, one nesting level), so a small dependency-free parser covers it.

Styling goals: corporate navy/charcoal palette, document header band, clean
typographic hierarchy, Key Metrics as a two-column table, print-friendly,
dark-mode aware, and strictly no emojis (stripped defensively on render).
"""

import html
import re
from datetime import datetime, timezone

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")

# Emoji / pictograph ranges. The LLM prompts forbid emojis, but strip
# defensively so a slip can never reach the published document.
_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # pictographs, emoticons, symbols
    "☀-➿"           # misc symbols + dingbats
    "⬀-⯿"           # misc symbols and arrows
    "︎️"            # variation selectors
    "‍"                  # zero-width joiner
    "]+"
)

# "Metric name: value" bullets under the Key Metrics section become table rows.
_METRIC_LINE = re.compile(r"^(.{1,80}?):\s+(.+)$")


def _inline(text: str) -> str:
    text = html.escape(text)
    text = _INLINE_CODE.sub(r"<code>\1</code>", text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


def _markdown_to_html(md_text: str) -> str:
    lines = md_text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    list_depth = 0          # 0 = no list open, 1 = <ul>, 2 = nested <ul>
    table_open = False
    in_metrics_section = False

    def flush_para():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def close_lists(to_depth: int = 0):
        nonlocal list_depth
        while list_depth > to_depth:
            out.append("</ul>")
            list_depth -= 1

    def close_table():
        nonlocal table_open
        if table_open:
            out.append("</tbody></table>")
            table_open = False

    def close_blocks():
        flush_para()
        close_lists()
        close_table()

    for raw in lines:
        line = raw.strip()

        if not line:
            close_blocks()
            continue

        if line.startswith("# "):
            close_blocks()
            heading = line[2:].strip()
            in_metrics_section = "key metric" in heading.lower()
            out.append(f"<h2>{_inline(heading)}</h2>")
            continue

        if line.startswith("## "):
            close_blocks()
            out.append(f"<h3>{_inline(line[3:].strip())}</h3>")
            continue

        if line.startswith("- ") or line.startswith("* "):
            flush_para()
            item = line[2:].strip()
            nested = raw != raw.lstrip() and list_depth >= 1  # indented bullet

            # Key Metrics "name: value" bullets render as a table instead.
            m = _METRIC_LINE.match(item) if (in_metrics_section and not nested) else None
            if m:
                close_lists()
                if not table_open:
                    out.append('<table class="kv"><tbody>')
                    table_open = True
                out.append(
                    f"<tr><td class=\"kv-name\">{_inline(m.group(1))}</td>"
                    f"<td class=\"kv-value\">{_inline(m.group(2))}</td></tr>"
                )
                continue

            close_table()
            target_depth = 2 if nested else 1
            close_lists(target_depth)
            while list_depth < target_depth:
                out.append('<ul class="nested">' if list_depth == 1 else "<ul>")
                list_depth += 1
            out.append(f"<li>{_inline(item)}</li>")
            continue

        close_lists()
        close_table()
        para.append(line)

    close_blocks()
    return "\n".join(out)


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --ink: #1f2937;
    --ink-soft: #5b6472;
    --ink-faint: #8a93a1;
    --rule: #e3e7ec;
    --rule-strong: #cfd6de;
    --navy: #16324f;
    --navy-deep: #102538;
    --accent: #1f4e79;
    --accent-soft: #eef3f8;
    --bg: #eef0f3;
    --panel: #ffffff;
  }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-text-size-adjust: 100%; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: "Segoe UI", -apple-system, "Helvetica Neue", Arial, sans-serif;
    font-size: 15px;
    line-height: 1.7;
  }}
  .sheet {{
    max-width: 900px;
    margin: 40px auto 56px;
    background: var(--panel);
    border: 1px solid var(--rule);
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 1px 2px rgba(16, 37, 56, 0.06), 0 12px 32px rgba(16, 37, 56, 0.08);
  }}
  header.report-header {{
    background: linear-gradient(135deg, var(--navy-deep) 0%, var(--navy) 62%, #1d3e5e 100%);
    color: #f4f7fa;
    padding: 40px 64px 34px;
  }}
  header.report-header .eyebrow {{
    text-transform: uppercase;
    letter-spacing: 0.18em;
    font-size: 11px;
    font-weight: 600;
    color: #9db8d1;
    margin-bottom: 10px;
  }}
  header.report-header h1 {{
    font-size: 27px;
    line-height: 1.25;
    margin: 0 0 14px;
    font-weight: 650;
    letter-spacing: -0.01em;
  }}
  header.report-header .meta {{
    display: flex;
    gap: 28px;
    flex-wrap: wrap;
    font-size: 12.5px;
    color: #b9c9da;
    border-top: 1px solid rgba(255, 255, 255, 0.16);
    padding-top: 14px;
  }}
  header.report-header .meta span strong {{
    color: #e8eef4;
    font-weight: 600;
  }}
  main.report-body {{ padding: 44px 64px 28px; }}
  h2 {{
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--accent);
    margin: 44px 0 16px;
    padding-top: 22px;
    border-top: 1px solid var(--rule);
  }}
  h2:first-child {{ margin-top: 0; padding-top: 0; border-top: none; }}
  h3 {{
    font-size: 15px;
    font-weight: 650;
    color: var(--ink);
    margin: 26px 0 8px;
  }}
  p {{ margin: 0 0 14px; max-width: 72ch; }}
  ul {{ margin: 0 0 16px; padding-left: 20px; list-style: none; }}
  li {{ margin-bottom: 9px; position: relative; padding-left: 4px; }}
  li::before {{
    content: "";
    position: absolute;
    left: -14px;
    top: 0.62em;
    width: 6px;
    height: 6px;
    border-radius: 1px;
    background: var(--accent);
    opacity: 0.55;
  }}
  ul.nested {{ margin: 8px 0 4px; padding-left: 18px; }}
  ul.nested li::before {{
    width: 5px;
    height: 2px;
    top: 0.75em;
    border-radius: 0;
    opacity: 0.4;
  }}
  table.kv {{
    width: 100%;
    border-collapse: collapse;
    margin: 4px 0 20px;
    font-size: 14.5px;
    border: 1px solid var(--rule);
  }}
  table.kv td {{
    padding: 9px 16px;
    border-bottom: 1px solid var(--rule);
    vertical-align: top;
  }}
  table.kv tr:last-child td {{ border-bottom: none; }}
  table.kv tr:nth-child(odd) td {{ background: var(--accent-soft); }}
  td.kv-name {{
    width: 42%;
    font-weight: 600;
    color: var(--ink);
    border-right: 1px solid var(--rule);
  }}
  td.kv-value {{
    color: var(--ink-soft);
    font-variant-numeric: tabular-nums;
  }}
  code {{
    background: var(--accent-soft);
    border: 1px solid var(--rule);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 12.5px;
    font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
    color: var(--accent);
  }}
  strong {{ font-weight: 650; color: var(--ink); }}
  footer.report-footer {{
    margin: 20px 64px 0;
    padding: 18px 0 36px;
    border-top: 1px solid var(--rule-strong);
    font-size: 11.5px;
    line-height: 1.6;
    color: var(--ink-faint);
  }}
  @media (max-width: 720px) {{
    .sheet {{ margin: 0; border-radius: 0; border-left: none; border-right: none; }}
    header.report-header, main.report-body {{ padding-left: 24px; padding-right: 24px; }}
    footer.report-footer {{ margin-left: 24px; margin-right: 24px; }}
  }}
  @media print {{
    body {{ background: #ffffff; }}
    .sheet {{ margin: 0; max-width: none; border: none; border-radius: 0; box-shadow: none; }}
    header.report-header {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    h2 {{ break-after: avoid; }}
    table.kv, li {{ break-inside: avoid; }}
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --ink: #dde2e9;
      --ink-soft: #a6afbc;
      --ink-faint: #7d8794;
      --rule: #313843;
      --rule-strong: #3d4552;
      --accent: #8fb4d9;
      --accent-soft: #232a33;
      --bg: #14171c;
      --panel: #1b1f26;
    }}
    .sheet {{ box-shadow: none; }}
  }}
</style>
</head>
<body>
  <div class="sheet">
    <header class="report-header">
      <div class="eyebrow">{eyebrow}</div>
      <h1>{title}</h1>
      <div class="meta">
        <span><strong>Generated</strong>&ensp;{generated}</span>
        <span><strong>Source</strong>&ensp;Connected Power BI semantic model</span>
        <span><strong>Method</strong>&ensp;Automated DAX analysis</span>
      </div>
    </header>
    <main class="report-body">
{body}
    </main>
    <footer class="report-footer">
      This document was generated automatically from the connected semantic model.
      Figures reflect only the queries executed in this run; see the limitations
      or caveats section above for coverage gaps.
    </footer>
  </div>
</body>
</html>
"""


def render(summary_markdown: str, title: str = "Report Summary",
           eyebrow: str = "Power BI Analysis") -> str:
    """Convert the agent's Markdown report into a standalone HTML document."""
    body = _markdown_to_html(_EMOJI.sub("", summary_markdown))
    generated = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    return _TEMPLATE.format(
        title=html.escape(_EMOJI.sub("", title)),
        eyebrow=html.escape(eyebrow),
        generated=generated,
        body=body,
    )
