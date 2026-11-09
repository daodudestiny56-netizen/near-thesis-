"""Record a <60 s silent demo of the dashboard as an MP4 (captions are drawn from results.json, so every
number on screen is real).

    python tools/make_video.py [output.mp4]

Needs: playwright (pip install playwright) and Google Chrome or Edge installed; ffmpeg comes from the
imageio-ffmpeg package (pip install imageio-ffmpeg). This is a presentation helper, not part of the pipeline.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Desktop" / "near-agent-census-demo.mp4"
W, H = 1280, 720
MAX_SECONDS = 58

res = json.loads((ROOT / "data/derived/results.json").read_text())
val = json.loads((ROOT / "data/derived/validation.json").read_text()) if (ROOT / "data/derived/validation.json").exists() else {}
M = res["monthly"]
last = M[-1]
pct = lambda x, d=0: "n/a" if x is None else f"{x * 100:.{d}f}%"
T = val.get("test", {})
lw = res["latest_window"]["metrics"]

OVERLAY_CSS = """
#cap{position:fixed;left:0;right:0;bottom:0;padding:18px 40px 22px;background:linear-gradient(transparent,rgba(0,0,0,.86) 38%);
  color:#fff;font:600 27px/1.3 system-ui,Segoe UI,sans-serif;z-index:9999;text-shadow:0 1px 4px #000;transition:opacity .3s}
#card{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#0b0b0b;color:#f0efec;
  z-index:10000;font-family:system-ui,Segoe UI,sans-serif;text-align:center;padding:0 80px}
#card h1{font-size:60px;margin:0 0 18px;letter-spacing:-.02em;line-height:1.1}
#card p{font-size:28px;color:#c3c2b7;margin:6px 0;max-width:1000px;line-height:1.35}
#card code{font:26px ui-monospace,Consolas,monospace;background:#232321;padding:10px 18px;border-radius:8px;color:#fff;margin-top:22px;display:inline-block}
"""


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    t0 = time.time()
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome")
        except Exception:
            browser = pw.chromium.launch(channel="msedge")
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp),
                                  record_video_size={"width": W, "height": H}, color_scheme="dark")
        page = ctx.new_page()
        page.goto((ROOT / "docs/index.html").as_uri())
        page.wait_for_timeout(600)
        page.add_style_tag(content=OVERLAY_CSS)
        page.evaluate("document.body.insertAdjacentHTML('beforeend','<div id=card></div><div id=cap style=opacity:0></div>')")
        start = time.time() - t0                      # scenes start here; everything before is trimmed

        def card(html):
            page.evaluate("h=>{document.getElementById('card').innerHTML=h;document.getElementById('card').style.display='flex'}", html)

        def hide_card():
            page.evaluate("document.getElementById('card').style.display='none'")

        def cap(text):
            page.evaluate("t=>{const c=document.getElementById('cap');c.textContent=t;c.style.opacity=t?1:0}", text)

        def goto(selector, dy=-10):
            page.evaluate("([s,d])=>{const e=document.querySelector(s);window.scrollTo({top:e.getBoundingClientRect().top+scrollY+d,behavior:'smooth'})}", [selector, dy])

        def sweep(selector, steps=26, ms=95):
            box = page.locator(f"{selector} svg").first.bounding_box()
            if not box:
                return
            y = box["y"] + box["height"] * 0.45
            for i in range(steps):
                page.mouse.move(box["x"] + 60 + (box["width"] - 100) * i / (steps - 1), y)
                page.wait_for_timeout(ms)

        # 1. hook ------------------------------------------------------------------------------------------
        card("<h1>How much of NEAR<br>is software?</h1><p>A random-sample census with error bars, not a guess.</p>")
        page.wait_for_timeout(4200)
        # 2. headline ---------------------------------------------------------------------------------------
        hide_card(); page.evaluate("window.scrollTo(0,0)")
        cap(f"{pct(lw['tx_auto']['point'])} of sampled NEAR transactions were initiated by software-like accounts "
            f"(95% CI {pct(lw['tx_auto']['lo'])}-{pct(lw['tx_auto']['hi'])}). Across classifier cut-offs: {pct(lw['tx_auto_t60']['point'])}-{pct(lw['tx_auto_t40']['point'])}.")
        page.wait_for_timeout(7000)
        # 3. trend --------------------------------------------------------------------------------------------
        goto("#c-share"); page.wait_for_timeout(800)
        cap("Every point carries its interval. Strict and lenient cut-offs are shown, not hidden.")
        sweep("#c-share"); page.wait_for_timeout(900)
        # 4. fingerprint ------------------------------------------------------------------------------------
        if page.locator("#c-hour").count():
            goto("#c-hour"); page.wait_for_timeout(700)
            cap({"human_more_rhythmic": "People keep a daily rhythm; software has less of one. Tested with a bootstrap, not eyeballed.",
                 "automated_more_rhythmic": "Surprise: automated traffic keeps the stronger daily rhythm. Reported as found.",
                 "no_clear_difference": "Do software and people keep different hours? No clear difference, and we report that as found.",
                 }.get(res["hourly"].get("rhythm_verdict"), "Daily rhythm of automated vs human-like activity."))
            sweep("#c-hour", steps=22); page.wait_for_timeout(1200)
        # 5. verify -------------------------------------------------------------------------------------------
        goto("#c-lookup", dy=-80); page.wait_for_timeout(700)
        cap("Verify it yourself: any account's verdict shows the exact rules that fired. No black box.")
        page.wait_for_timeout(4800)
        goto("#c-spot", dy=-80); page.wait_for_timeout(600)
        cap("Every sampled transaction links to a public explorer.")
        page.wait_for_timeout(3600)
        # 6. thesis -------------------------------------------------------------------------------------------
        goto("#c-claims", dy=-90); page.wait_for_timeout(700)
        n = {v: sum(1 for c in res.get("claims", []) if c["verdict"] == v) for v in ("supported", "not_supported", "inconclusive")}
        cap(f"The thesis, tested by code: {n['supported']} supported, {n['not_supported']} not supported, {n['inconclusive']} inconclusive. Evidence, not conviction.")
        page.wait_for_timeout(6000)
        # 7. close ---------------------------------------------------------------------------------------------
        cap("")
        card("<h1>One command rebuilds every number</h1><p>Evidence, not conviction.</p><code>python -m census reproduce</code>"
             "<p style='margin-top:26px;font-size:24px'>github.com/daodudestiny56-netizen/near-thesis-</p>")
        page.wait_for_timeout(5000)
        end = time.time() - t0
        ctx.close()
        webm = next(tmp.glob("*.webm"))
        browser.close()

    length = min(end - start, MAX_SECONDS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-ss", f"{start:.2f}", "-i", str(webm), "-t", f"{length:.2f}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-r", "30", "-an", "-movflags", "+faststart", str(OUT)]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"wrote {OUT} ({length:.1f} s, {OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
