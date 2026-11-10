"""Record a <60 s narrated demo of the dashboard as an MP4. Captions and narration are built from results.json, so every
number on screen and in the voice-over is real.

    python tools/make_video.py [output.mp4] [--voice en-NG-AbeoNeural] [--rate +0%]

African English voices (Microsoft neural voices via edge-tts): en-NG-AbeoNeural / en-NG-EzinneNeural (Nigeria),
en-KE-ChilembaNeural / en-KE-AsiliaNeural (Kenya), en-ZA-LukeNeural / en-ZA-LeahNeural (South Africa),
en-TZ-ElimuNeural / en-TZ-ImaniNeural (Tanzania).

Needs: playwright (pip install playwright) with Google Chrome or Edge installed, edge-tts (pip install edge-tts; sends the narration text
to Microsoft's speech service, internet required), and imageio-ffmpeg for ffmpeg. This is a presentation helper, not part of the pipeline.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 720
MAX_SECONDS = 58
GAP = 0.45                                     # breathing room after each spoken line

ap = argparse.ArgumentParser()
ap.add_argument("out", nargs="?", default=str(Path.home() / "Desktop" / "near-agent-census-demo.mp4"))
ap.add_argument("--voice", default="en-NG-AbeoNeural")
ap.add_argument("--rate", default="+0%")
args = ap.parse_args()
OUT = Path(args.out)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

res = json.loads((ROOT / "data/derived/results.json").read_text())
lw = res["latest_window"]["metrics"]
ab = (res.get("windows") or {}).get("abs") or {}
pct = lambda x: f"{x * 100:.0f}"
n = {v: sum(1 for c in res.get("claims", []) if c["verdict"] == v) for v in ("supported", "not_supported", "inconclusive")}

# ---- the script: (caption shown on screen, line spoken aloud). All numbers come from results.json. --------------------------
SCRIPT = {
    "hook": ("", "How much of NEAR is software? We measured it."),
    "headline": (
        f"{pct(lw['tx_auto']['point'])}% of sampled NEAR transactions come from software-like accounts "
        f"(95% CI {pct(lw['tx_auto']['lo'])}-{pct(lw['tx_auto']['hi'])}%). Fees they initiate: {pct(lw['fee_init_auto']['point'])}%.",
        f"{pct(lw['tx_auto']['point'])} percent of sampled NEAR transactions come from software-like accounts, with a confidence interval of "
        f"{pct(lw['tx_auto']['lo'])} to {pct(lw['tx_auto']['hi'])}. They initiate {pct(lw['fee_init_auto']['point'])} percent of fees."),
    "share": ("And the share jumped in 2026. Every point carries its interval.",
              "That share jumped in twenty twenty-six."),
}
if ab.get("total_tx_per_block") and ab.get("auto_tx_per_block"):
    tt, at = ab["total_tx_per_block"], ab["auto_tx_per_block"]
    SCRIPT["twist"] = (
        f"But total activity fell from {tt['per_s_a']:.0f} to {tt['per_s_b']:.0f} tx/s, and automated from {at['per_s_a']:.0f} to {at['per_s_b']:.0f}. "
        "The share rose because human-like activity fell faster.",
        f"But total activity fell from {tt['per_s_a']:.0f} to {tt['per_s_b']:.0f} transactions per second, and automated from "
        f"{at['per_s_a']:.0f} to {at['per_s_b']:.0f}. The share rose because human-like activity fell faster.")
SCRIPT["verify"] = ("Verify it yourself: every verdict shows the exact rules that fired, and every sampled transaction links to an explorer.",
                    "Verify it yourself: every verdict shows the rules that fired, and every transaction links to an explorer.")
SCRIPT["thesis"] = (
    f"The thesis, tested by code: {n['supported']} supported, {n['not_supported']} not supported, {n['inconclusive']} inconclusive. Evidence, not conviction.",
    f"The thesis, tested by code: {n['supported']} supported, {n['not_supported']} not supported, {n['inconclusive']} inconclusive.")
SCRIPT["close"] = ("", "One command rebuilds every number. Evidence, not conviction.")

OVERLAY_CSS = """
#cap{position:fixed;left:0;right:0;bottom:0;padding:18px 40px 22px;background:linear-gradient(transparent,rgba(0,0,0,.86) 38%);
  color:#fff;font:600 27px/1.3 system-ui,Segoe UI,sans-serif;z-index:9999;text-shadow:0 1px 4px #000;transition:opacity .3s}
#card{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#0b0b0b;color:#f0efec;
  z-index:10000;font-family:system-ui,Segoe UI,sans-serif;text-align:center;padding:0 80px}
#card h1{font-size:60px;margin:0 0 18px;letter-spacing:-.02em;line-height:1.1}
#card p{font-size:28px;color:#c3c2b7;margin:6px 0;max-width:1000px;line-height:1.35}
#card code{font:26px ui-monospace,Consolas,monospace;background:#232321;padding:10px 18px;border-radius:8px;color:#fff;margin-top:22px;display:inline-block}
"""


def duration(path: Path) -> float:
    """Length of an audio file in seconds, read from ffmpeg's banner."""
    err = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", err)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


async def _synth(text: str, path: Path) -> None:
    await edge_tts.Communicate(text, args.voice, rate=args.rate).save(str(path))


def synthesise(tmp: Path) -> dict[str, tuple[Path, float]]:
    out = {}
    for key, (_, spoken) in SCRIPT.items():
        path = tmp / f"{key}.mp3"
        asyncio.run(_synth(spoken, path))
        out[key] = (path, duration(path))
    return out


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    audio = synthesise(tmp)
    planned = sum(d + GAP for _, d in audio.values())
    print(f"voice {args.voice}: narration {sum(d for _, d in audio.values()):.1f} s, planned video about {planned:.1f} s")
    if planned > MAX_SECONDS:
        raise SystemExit(f"Planned length {planned:.1f} s exceeds {MAX_SECONDS} s. Shorten SCRIPT or raise --rate (for example +8%).")

    events: list[tuple[float, Path]] = []
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

        def sweep(selector, steps=24, ms=95):
            box = page.locator(f"{selector} svg").first.bounding_box()
            if not box:
                return
            y = box["y"] + box["height"] * 0.45
            for i in range(steps):
                page.mouse.move(box["x"] + 60 + (box["width"] - 100) * i / (steps - 1), y)
                page.wait_for_timeout(ms)

        def scene(key, action=None, mid=None):
            """Start the narration line now, run `action`, then hold until the line (plus a short gap) has finished."""
            path, dur = audio[key]
            began = time.time()
            events.append((began - t0 - start, path))
            cap(SCRIPT[key][0])
            if action:
                action()
            if mid:                                    # a second action halfway through a long line
                page.wait_for_timeout(max(0, (dur * 0.5 - (time.time() - began)) * 1000))
                mid()
            page.wait_for_timeout(max(0, (dur + GAP - (time.time() - began)) * 1000))

        scene("hook", action=lambda: card("<h1>How much of NEAR<br>is software?</h1><p>A random-sample census with error bars, not a guess.</p>"))
        scene("headline", action=lambda: (hide_card(), page.evaluate("window.scrollTo(0,0)")))
        scene("share", action=lambda: (goto("#c-share"), page.wait_for_timeout(500), sweep("#c-share")))
        if "twist" in audio and page.locator("#c-abs-tx").count():
            scene("twist", action=lambda: (goto("#c-abs-tx", dy=-70), page.wait_for_timeout(500), sweep("#c-abs-tx", steps=26, ms=100)))
        scene("verify", action=lambda: goto("#c-lookup", dy=-80), mid=lambda: goto("#c-spot", dy=-80))
        scene("thesis", action=lambda: goto("#c-claims", dy=-90))
        scene("close", action=lambda: card("<h1>One command rebuilds every number</h1><p>Evidence, not conviction.</p><code>python -m census reproduce</code>"
                                           "<p style='margin-top:26px;font-size:24px'>github.com/daodudestiny56-netizen/near-thesis-</p>"))
        end = time.time() - t0
        ctx.close()
        webm = next(tmp.glob("*.webm"))
        browser.close()

    length = min(end - start, MAX_SECONDS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, "-y", "-ss", f"{start:.2f}", "-i", str(webm)]
    for _, path in events:
        cmd += ["-i", str(path)]
    parts = [f"[{i + 1}:a]adelay={int(t * 1000)}|{int(t * 1000)}[a{i}]" for i, (t, _) in enumerate(events)]
    mix = "".join(f"[a{i}]" for i in range(len(events))) + f"amix=inputs={len(events)}:normalize=0,volume=1.6,apad[aout]"
    cmd += ["-filter_complex", ";".join(parts + [mix]), "-map", "0:v", "-map", "[aout]", "-t", f"{length:.2f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-r", "30", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(OUT)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr[-1500:])
    print(f"wrote {OUT} ({length:.1f} s, {OUT.stat().st_size / 1e6:.1f} MB, voice {args.voice})")


if __name__ == "__main__":
    main()
