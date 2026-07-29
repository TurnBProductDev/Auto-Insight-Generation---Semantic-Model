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


# ScanB design tokens - mirrors wwwroot/css/theme.css and the palette used by
# summary_visual.py, so the insight report and the AI summary read as one
# product. Kept outside the f-string assembly below so CSS braces need no
# escaping. Keep in sync if the app's theme moves.
_STYLE = """
:root{
  --sb-teal:#2dbdad; --sb-teal-strong:#148D8B; --sb-teal-soft:#f0fdfa;
  --sb-chrome:#1a3035;
  --sb-page-bg:#f0f2f4; --sb-surface:#ffffff; --sb-surface-alt:#f8fafc;
  --sb-text:#1a2a2e; --sb-text-muted:#506675; --sb-text-faint:#8a9ba8;
  --sb-border:#e8edf0; --sb-border-strong:#d7e0e5;
  --sb-shadow-sm:0 3px 10px rgba(26,42,46,.08);
  --sb-font-sans:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --sb-teal:#3ccbb9; --sb-teal-strong:#2dbdad; --sb-teal-soft:rgba(45,189,173,.10);
  --sb-chrome:#14262a;
  --sb-page-bg:#0b1415; --sb-surface:#121d1f; --sb-surface-alt:#182527;
  --sb-text:#edf5f3; --sb-text-muted:#b4c6c2; --sb-text-faint:#7f948f;
  --sb-border:#233335; --sb-border-strong:#2e4144;
  --sb-shadow-sm:0 3px 10px rgba(0,0,0,.40);
  color-scheme:dark;
}}
:root[data-theme="dark"]{
  --sb-teal:#3ccbb9; --sb-teal-strong:#2dbdad; --sb-teal-soft:rgba(45,189,173,.10);
  --sb-chrome:#14262a;
  --sb-page-bg:#0b1415; --sb-surface:#121d1f; --sb-surface-alt:#182527;
  --sb-text:#edf5f3; --sb-text-muted:#b4c6c2; --sb-text-faint:#7f948f;
  --sb-border:#233335; --sb-border-strong:#2e4144;
  --sb-shadow-sm:0 3px 10px rgba(0,0,0,.40);
  color-scheme:dark;
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--sb-page-bg);color:var(--sb-text);
  font-family:var(--sb-font-sans);font-size:14.5px;line-height:1.68;
  -webkit-font-smoothing:antialiased}
.sheet{max-width:940px;margin:36px auto 56px;background:var(--sb-surface);
  border:1px solid var(--sb-border);border-radius:16px;overflow:hidden;
  box-shadow:var(--sb-shadow-sm)}

header.report-header{background:var(--sb-chrome);color:#eef6f4;padding:34px 56px 26px}
header.report-header .eyebrow{display:inline-flex;align-items:center;gap:7px;
  text-transform:uppercase;letter-spacing:.14em;font-size:10.5px;font-weight:700;
  color:var(--sb-teal);margin-bottom:12px}
header.report-header .eyebrow::before{content:"";width:6px;height:6px;
  border-radius:50%;background:var(--sb-teal)}
header.report-header h1{font-size:26px;line-height:1.26;margin:0 0 16px;
  font-weight:700;letter-spacing:-.022em}
header.report-header .meta{display:flex;gap:8px;flex-wrap:wrap;
  border-top:1px solid rgba(255,255,255,.14);padding-top:14px}
header.report-header .meta span{font-size:11.5px;color:rgba(255,255,255,.66);
  background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.10);
  border-radius:999px;padding:4px 11px}
header.report-header .meta span strong{color:#ffffff;font-weight:650}

main.report-body{padding:38px 56px 24px}
h2{font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;
  color:var(--sb-teal-strong);margin:40px 0 16px;padding-top:20px;
  border-top:1px solid var(--sb-border);display:flex;align-items:center;gap:8px}
h2::before{content:"";width:14px;height:2px;border-radius:2px;background:var(--sb-teal)}
h2:first-child{margin-top:0;padding-top:0;border-top:none}
h3{font-size:14.5px;font-weight:700;color:var(--sb-text);margin:24px 0 8px;
  letter-spacing:-.012em}
p{margin:0 0 14px;max-width:74ch;color:var(--sb-text-muted)}
p strong{color:var(--sb-text)}
ul{margin:0 0 16px;padding-left:20px;list-style:none}
li{margin-bottom:9px;position:relative;padding-left:4px;color:var(--sb-text-muted)}
li::before{content:"";position:absolute;left:-14px;top:.62em;width:6px;height:6px;
  border-radius:50%;background:var(--sb-teal);opacity:.75}
ul.nested{margin:8px 0 4px;padding-left:18px}
ul.nested li::before{width:5px;height:2px;top:.78em;border-radius:1px;
  background:var(--sb-border-strong);opacity:1}

table.kv{width:100%;border-collapse:collapse;margin:4px 0 20px;font-size:14px;
  border:1px solid var(--sb-border);border-radius:10px;overflow:hidden}
table.kv td{padding:10px 16px;border-bottom:1px solid var(--sb-border);
  vertical-align:top}
table.kv tr:last-child td{border-bottom:none}
table.kv tr:nth-child(odd) td{background:var(--sb-surface-alt)}
td.kv-name{width:42%;font-weight:650;color:var(--sb-text);
  border-right:1px solid var(--sb-border)}
td.kv-value{color:var(--sb-text-muted);font-variant-numeric:tabular-nums}

code{background:var(--sb-surface-alt);border:1px solid var(--sb-border);
  padding:1.5px 6px;border-radius:6px;font-size:12.5px;
  font-family:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;
  color:var(--sb-teal-strong)}
strong{font-weight:700;color:var(--sb-text)}

footer.report-footer{margin:22px 56px 0;padding:18px 0 34px;
  border-top:1px solid var(--sb-border);font-size:11.5px;line-height:1.6;
  color:var(--sb-text-faint)}

@media (max-width:760px){
  .sheet{margin:0;border-radius:0;border-left:none;border-right:none}
  header.report-header,main.report-body{padding-left:22px;padding-right:22px}
  footer.report-footer{margin-left:22px;margin-right:22px}
}
@media print{
  body{background:#fff}
  .sheet{margin:0;max-width:none;border:none;border-radius:0;box-shadow:none}
  header.report-header{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  h2{break-after:avoid}
  table.kv,li{break-inside:avoid}
}
"""


def render(summary_markdown: str, title: str = "Report Summary",
           eyebrow: str = "Power BI Analysis") -> str:
    """Convert the agent's Markdown report into a standalone HTML document."""
    body = _markdown_to_html(_EMOJI.sub("", summary_markdown))
    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    safe_title = html.escape(_EMOJI.sub("", title))
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{safe_title}</title>\n<style>{_STYLE}</style>\n</head>\n<body>\n"
        '  <div class="sheet">\n'
        '    <header class="report-header">\n'
        f'      <div class="eyebrow">{html.escape(eyebrow)}</div>\n'
        f"      <h1>{safe_title}</h1>\n"
        '      <div class="meta">\n'
        f"        <span><strong>Generated</strong>&ensp;{generated}</span>\n"
        "        <span><strong>Source</strong>&ensp;Power BI semantic model</span>\n"
        "        <span><strong>Method</strong>&ensp;Automated DAX analysis</span>\n"
        "      </div>\n"
        "    </header>\n"
        '    <main class="report-body">\n'
        f"{body}\n"
        "    </main>\n"
        '    <footer class="report-footer">\n'
        "      This document was generated automatically from the connected semantic model.\n"
        "      Figures reflect only the queries executed in this run and the business rules\n"
        "      in force at the time; see the limitations or caveats section above for\n"
        "      coverage gaps.\n"
        "    </footer>\n"
        "  </div>\n"
        "</body>\n</html>\n"
    )
