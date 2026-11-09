"""Stage 5 - dashboard: bake results into one self-contained static page (docs/index.html).

No build step and no network at view time: the data is embedded as JSON and every chart is plain
SVG drawn by ~150 lines of vanilla JavaScript, so the page works offline, on GitHub Pages, or by
double-clicking the file.
"""
from __future__ import annotations

import json
from pathlib import Path

import base64

from . import config as C
from .classify import RULES
from .util import jsonable

TEMPLATE = Path(__file__).with_name("dashboard_template.html")


def run() -> None:
    results = json.loads((C.DERIVED / "results.json").read_text())
    vpath = C.DERIVED / "validation.json"
    validation = json.loads(vpath.read_text()) if vpath.exists() else {}
    rules = [{"name": r.name, "points": r.points, "why": r.why} for r in RULES]
    payload = json.dumps(jsonable({"results": results, "validation": validation, "rules": rules}),
                         allow_nan=False).replace("</", "<\\/")
    font = base64.b64encode((C.ROOT / "census" / "assets" / "BricolageGrotesque-latin.woff2").read_bytes()).decode()
    face = ('@font-face{font-family:"Bricolage Grotesque";font-style:normal;font-weight:200 800;font-display:swap;'
            f'src:url(data:font/woff2;base64,{font}) format("woff2")}}')
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*FONT*/", face).replace("/*DATA*/", payload)
    C.DOCS.mkdir(exist_ok=True)
    out = C.DOCS / "index.html"
    out.write_text(html, encoding="utf-8")
    (C.DOCS / ".nojekyll").write_text("")
    print(f"wrote {out} ({len(html) / 1024:.0f} KiB)")


if __name__ == "__main__":
    run()
