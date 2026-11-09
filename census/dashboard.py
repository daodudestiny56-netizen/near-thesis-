"""Stage 5 - dashboard: bake results into one self-contained static page (docs/index.html).

No build step and no network at view time: the data is embedded as JSON and every chart is plain
SVG drawn by ~150 lines of vanilla JavaScript, so the page works offline, on GitHub Pages, or by
double-clicking the file.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config as C
from .util import jsonable

TEMPLATE = Path(__file__).with_name("dashboard_template.html")


def run() -> None:
    results = json.loads((C.DERIVED / "results.json").read_text())
    vpath = C.DERIVED / "validation.json"
    validation = json.loads(vpath.read_text()) if vpath.exists() else {}
    payload = json.dumps(jsonable({"results": results, "validation": validation}), allow_nan=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/", payload)
    C.DOCS.mkdir(exist_ok=True)
    out = C.DOCS / "index.html"
    out.write_text(html, encoding="utf-8")
    (C.DOCS / ".nojekyll").write_text("")
    print(f"wrote {out} ({len(html) / 1024:.0f} KiB)")


if __name__ == "__main__":
    run()
