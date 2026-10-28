"""Render an escaped, self-contained report; parsed HTML is never executed."""
from __future__ import annotations

from html import escape
from typing import Any


def _percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def render(result: dict[str, Any]) -> str:
    e = lambda value: escape(str(value), quote=True)
    rows, panels = [], []
    for parser in result["parsers"]:
        score = _percent(parser["headline"])
        rows.append(f'<tr><th>{e(parser["parser"])}</th><td>{score}</td>'
                    f'<td>{_percent(parser["coverage"])}</td><td>{parser["passed"]}/{parser["tests"]}</td>'
                    f'<td>{parser["documents"]}</td><td>{parser["failed"]}/{parser["pages"]}</td></tr>')
        families = "".join(f'<li><strong>{e(family)}</strong> {_percent(stats["score"])} '
                           f'· {stats["tests"]} tests · {stats["documents"]} documents</li>'
                           for family, stats in parser["scored"]["families"].items())
        detail_rows = "".join(f'<tr><td>{e(d["page_id"])}</td><td>{e(d["test_type"])}</td>'
                              f'<td>{e(d["test_id"])}</td><td class="{d["result"]}">{e(d["result"])}</td>'
                              f'<td>{e(d["why"])}</td><td>{e(", ".join(d["tags"]))}</td></tr>'
                              for d in parser["details"])
        panels.append(f'<section><h2>{e(parser["parser"])}</h2><p>Answered-page families</p>'
                      f'<ul>{families or "<li>No answered tests</li>"}</ul><details><summary>All verdicts</summary>'
                      f'<div class="scroll"><table><thead><tr><th>Page</th><th>Check</th><th>Test</th>'
                      f'<th>Result</th><th>Reason</th><th>Tags</th></tr></thead><tbody>{detail_rows}</tbody>'
                      '</table></div></details></section>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'">
<title>OCR Slice Benchmark</title><style>
:root{color-scheme:light}body{font:16px/1.55 system-ui,sans-serif;background:#f2f5f4;color:#142e31;margin:0}
main{max-width:1180px;margin:auto;padding:40px 24px}h1{font-size:clamp(2rem,5vw,3.7rem);letter-spacing:-.05em;margin:0}
.eyebrow{letter-spacing:.14em;text-transform:uppercase;color:#476b6a;font-size:.8rem;font-weight:700}
.lead{max-width:800px;font-size:1.1rem}.notice{border-left:4px solid #c78b31;padding:12px 18px;background:#fff5e5}
section,.board{background:white;border:1px solid #d1dfdc;border-radius:12px;padding:24px;margin:24px 0}
table{border-collapse:collapse;width:100%;text-align:left;font-size:.92rem}th,td{padding:12px;border-bottom:1px solid #dce7e5;vertical-align:top;overflow-wrap:anywhere}
thead{background:#eaf2ef}.scroll{overflow:auto}.pass{color:#196449}.fail{color:#a43b2f}summary{cursor:pointer;font-weight:650;padding:12px 0}footer{font-size:.8rem;color:#476b6a}li{margin:.3rem 0}
</style><main><p class="eyebrow">Document parsing / reproducible checks</p><h1>OCR Slice Benchmark</h1>''' + (
        f'<p class="lead">{e(result["description"])}</p><p class="notice">{e(result["note"])}</p>'
        f'<p>Slice requires all tags: <strong>{e(", ".join(result["tags_all"]) or "all tests")}</strong>.</p>'
        '<p>Headline = native mean of answered-page family scores × page coverage. '
        'Missing or failed pages lower coverage. Families retain their own test and document counts.</p>'
        '<div class="board scroll"><table><thead><tr><th>Parser</th><th>Headline</th><th>Coverage</th>'
        '<th>Passed checks</th><th>Documents</th><th>Failed pages</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div>' + "".join(panels)
        + f'<footer>Native scorer revision {e(result["source_revision"])}. '
        'A small slice is a diagnostic, not a representative benchmark.</footer></main></html>')
