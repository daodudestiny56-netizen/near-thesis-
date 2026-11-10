"""The README section "How NEAR and its builders can use this with investors", generated from the results.

Every number is read from results.json, validation.json and predictions/, so the section is re-decided whenever the data are. The text
makes only claims the research supports, and each benefit names the limit that goes with it.
"""
from __future__ import annotations

import csv
import json

from . import config as C

START, END = "<!-- USE:START -->", "<!-- USE:END -->"


def _pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def block(res: dict, val: dict) -> str | None:
    lw = res["latest_window"]["metrics"]
    ab = (res.get("windows") or {}).get("abs") or {}
    sup = res.get("supply") or {}
    sw, vw, step = sup.get("windows") or {}, ((sup.get("value") or {}).get("windows")) or {}, sup.get("issuance_step")
    if not (ab.get("total_tx_per_block") and sw and vw.get("a") and vw.get("b") and step):
        return None
    tt, at = ab["total_tx_per_block"], ab["auto_tx_per_block"]
    t = val.get("test") or {}
    regimes = {g["kind"]: g for g in res.get("regimes", [])}
    pred_file = C.ROOT / "predictions" / "predictions.csv"
    n_pred = len(list(csv.DictReader(open(pred_file, encoding="utf-8")))) if pred_file.exists() else 0
    need = 1 / vw["b"]["revenue_cover"] if vw["b"]["revenue_cover"] else None
    rev_x = vw["b"]["intents_revenue_usd_day"] / vw["a"]["intents_revenue_usd_day"]
    span = res["latest_window"]["periods"]

    L = [START, "",
         "## How NEAR and its builders can use this with investors", "",
         "Investors typically ask three questions about a chain: *is the activity real, is it growing, and does it pay for itself?* Many answers rest on one headline "
         "number. This research gives NEAR teams five things that are harder to dismiss than a headline, each with the evidence behind it and the limit that "
         "goes with it. Nothing here is investment advice, and \"automated\" includes AI agents but cannot isolate them.", "",
         "| | What it gives you | Why an investor should care | How to use it |",
         "|---|---|---|---|",
         f"| **1. A quality-of-activity metric** | The share of activity that comes from software-like accounts ({_pct(lw['tx_auto']['point'])} over {span[0]} to {span[-1]}, "
         f"95% CI {_pct(lw['tx_auto']['lo'])}-{_pct(lw['tx_auto']['hi'])}), validated on held-out accounts "
         + (f"({_pct(t['recall_automated'])} of labelled automated accounts found, {_pct(t['recall_human'])} of humans kept human)" if t.get("n_classified") else "")
         + ". | Raw transaction counts are easy for software to inflate. A split with stated error bars is harder to wave away than \"billions of transactions\". | "
         "Quote *human-like vs software-like* activity, with the interval, next to any activity claim. Check your own top callers with the live checker. |",
         f"| **2. The share-versus-activity guard** | Total activity fell {tt['per_s_a']:.0f} to {tt['per_s_b']:.0f} tx/s and automated activity {at['per_s_a']:.0f} to {at['per_s_b']:.0f} tx/s, "
         "while the software *share* rose. | A rising share can mean the rest left, not that software grew. Presenting only one of the two misleads in either direction, "
         "and a sceptical investor will find the other. | Always show the share **and** the absolute level. The dashboard's \"Absolute\" section does it for you. |",
         f"| **3. A numerate value-capture story** | Estimated L1 burn covers {_pct(sw['b']['burn_cover'], 1)} of gross issuance; reported Intents revenue covers {_pct(vw['b']['revenue_cover'])}, "
         f"up from {_pct(vw['a']['revenue_cover'])} (revenue x{rev_x:.1f}); net issuance itself halved in {step['to']}. | Usage not yet paying for issuance is the usual bear case. Here it is "
         "measured, with the gap and the trend stated, and not argued. |"
         + (f" Turn it into a milestone: at the measured price, Intents revenue would need to grow about x{need:.1f} to cover issuance. Report progress against that number. |" if need else " Report progress against the measured gap. |"),
         f"| **4. A reproducible due-diligence kit** | One command (`python -m census reproduce`) rebuilds every number; a live checker scores *any* NEAR account in the browser; "
         "random sampled transactions link to an explorer. | Investors and analysts can verify instead of trusting a deck: check a counterparty, audit the sampling, rerun the maths. "
         "Evidence someone else can reproduce is cheap to trust. | Send the dashboard link and the one-line reproduce command with the deck. Offer the live checker for counterparties. |",
         (f"| **5. Early warning and accountability** | {n_pred} predictions for December 2026, frozen, hashed and confirmed in Bitcoin blocks before the data exist, plus breakpoints detected from the data "
          f"(an activity collapse in {regimes['activity']['at']}, the issuance step in {regimes['issuance']['at']}, protocol v87 first seen in {regimes['v87']['at']})." if all(k in regimes for k in ("activity", "issuance", "v87")) and n_pred else
          "| **5. Early warning and accountability** | Breakpoints detected from the data. ")
         + " | A track record of stating expectations first and resolving them in public is rare and builds credibility; regime changes are what investor updates most need to explain. | "
         "Re-run `collect` for each new month (a few minutes per month anonymously, faster with a free FastNEAR key), publish the updated figures on a fixed cadence, and resolve the predictions "
         "in public in January 2027, whichever way they land. |",
         "",
         "**Using it over the long term.** Refresh the sample monthly and keep the method fixed, so each investor update is comparable with the last. Lead with the "
         "three numbers that carry the story (software-like share *and* absolute activity, and how much of issuance usage covers). Let the "
         "[thesis verdicts](THESIS.md) change when the data do, including the ones that cut against NEAR. A thesis whose verdicts can go either way is more "
         "credible to an investor than one that can only go up.", "",
         "**Limits to state alongside any of these.** The classifier is validated on labels biased toward self-declared bots, so its accuracy is an optimistic ceiling; "
         "Intents revenue and the NEAR price are third-party series used as published; the sample gives sampling error, not certainty; and none of it predicts price.",
         "", END]
    return "\n".join(L)


def write(res: dict, val: dict) -> None:
    readme = C.ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    if START not in text or END not in text:
        return
    new = block(res, val)
    if new is None:
        return
    readme.write_text(text[:text.index(START)] + new + text[text.index(END) + len(END):], encoding="utf-8")
    print("updated README investor-use section")
