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
first_dense = next((r for r in M if r["period"] >= "2024-01"), M[0])

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
        card(f"<h1>Is NEAR becoming the chain<br>software lives on?</h1><p>We measured it: a re-runnable census of automated behaviour on NEAR.</p>")
        page.wait_for_timeout(4500)
        # 2. headline ---------------------------------------------------------------------------------------
        hide_card(); page.evaluate("window.scrollTo(0,0)")
        cap(f"In {last['period']}, accounts behaving like software initiated {pct(last['tx_auto'])} of sampled NEAR transactions "
            f"(95% CI {pct(last['tx_auto_lo'])}–{pct(last['tx_auto_hi'])}).")
        page.wait_for_timeout(6500)
        goto("#c-share"); page.wait_for_timeout(900)
        cap(f"Since {first_dense['period']}: {pct(first_dense['tx_auto'])} → {pct(last['tx_auto'])}. Every point has an interval, not a guess.")
        sweep("#c-share"); page.wait_for_timeout(1200)
        # 3. fees ------------------------------------------------------------------------------------------
        goto("#c-fees"); page.wait_for_timeout(700)
        cap(f"Who initiates is not who pays: automated accounts initiate {pct(last['fee_init_auto'])} of fees, "
            f"but relayers make automated payers {pct(last['fee_paid_auto'])}.")
        sweep("#c-fees", steps=22); page.wait_for_timeout(1500)
        # 4. validation -------------------------------------------------------------------------------------
        goto("#c-valid"); page.wait_for_timeout(700)
        if T:
            cap(f"Held-out test: finds {pct(T['recall_automated'])} of labelled bots, keeps {pct(T['recall_human'])} of humans human. "
                f"Labels are biased, so we say so.")
        else:
            cap("The classifier is validated against labels built from evidence it never sees.")
        page.wait_for_timeout(6500)
        # 5. forecast ---------------------------------------------------------------------------------------
        goto("#c-forecast"); page.wait_for_timeout(700)
        cap("A trend line with its uncertainty shown, and a plain warning: this is not a prediction.")
        page.wait_for_timeout(5500)
        # 6. close -------------------------------------------------------------------------------------------
        cap("")
        card("<h1>One command rebuilds every number</h1><p>Evidence, not conviction.</p><code>python -m census reproduce</code>"
             "<p style='margin-top:26px;font-size:24px'>github.com/daodudestiny56-netizen/near-thesis-</p>")
        page.wait_for_timeout(6000)
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
