"""Stage 7 - submission: draft the form text and the X post from the final results (numbers are computed).

Writes submission/SUBMISSION.md (git-ignored: it will hold personal details). Nothing is sent anywhere.
The fields only the human can supply (name, email, wallet, team size, demo post link) are left as explicit blanks.
"""
from __future__ import annotations

import json

from . import config as C

REPO = "https://github.com/daodudestiny56-netizen/near-thesis-"
LIVE = "https://near-agent-census.vercel.app"
TCO = 23                                   # X counts every URL as 23 characters
IDEA_MAX, POST_MAX = 2000, 280


def pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def x_length(text: str) -> int:
    import re
    return len(re.sub(r"https?://\S+", "x" * TCO, text))


def build() -> dict:
    res = json.loads((C.DERIVED / "results.json").read_text())
    vpath = C.DERIVED / "validation.json"
    val = json.loads(vpath.read_text()) if vpath.exists() else {}
    g, lw = res["generated_from"], res["latest_window"]["metrics"]
    span = res["latest_window"]["periods"]
    a, lo, hi = lw["tx_auto"], lw["tx_auto_t60"], lw["tx_auto_t40"]
    fi, fp = lw["fee_init_auto"], lw["fee_paid_auto"]
    t = val.get("test", {})
    claims = res.get("claims", [])
    verdicts = {}
    for c in claims:
        verdicts[c["verdict"]] = verdicts.get(c["verdict"], 0) + 1

    ab = (res.get("windows") or {}).get("abs") or {}
    sup = res.get("supply") or {}
    sw, vw, step = sup.get("windows") or {}, ((sup.get("value") or {}).get("windows")) or {}, sup.get("issuance_step")
    MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    tt, at = ab.get("total_tx_per_block"), ab.get("auto_tx_per_block")
    absn = (f" But total activity fell from {tt['per_s_a']:.0f} to {tt['per_s_b']:.0f} tx/s and automated activity from {at['per_s_a']:.0f} to {at['per_s_b']:.0f}, "
            "so the share rose because the rest fell faster.") if tt and at else ""
    valn = ""
    if sw and vw.get("a") and vw.get("b") and step:
        valn = (f" Does usage pay for issuance? Net issuance, measured from block headers, halved in {MONTHS[int(step['to'][5:]) - 1]} {step['to'][:4]}; "
                f"estimated fee burn covers {pct(sw['b']['burn_cover'], 1)} of issuance and reported Intents revenue (DefiLlama) {pct(vw['b']['revenue_cover'])}, "
                f"up from {pct(vw['a']['revenue_cover'])}.")
    names = {"info": "descriptive", "not_supported": "not supported"}
    verdict_txt = ", ".join(f"{n} {names.get(k, k)}" for k, n in sorted(verdicts.items()))
    clsn = (f" The classifier is validated on a held-out split ({pct(t['recall_automated'])} of labelled automated accounts found, {pct(t['recall_human'])} of humans kept human; "
            "the labels are biased, so that is an optimistic ceiling).") if t.get("n_classified") else ""
    predn = " Eight predictions for December 2026 are pre-registered (SHA-256, OpenTimestamps)." if (C.ROOT / "predictions" / "predictions.csv").exists() else ""

    idea = (
        "NEAR's pitch is that software, including AI agents, will transact on it, but nobody publishes a measured number. "
        f"The NEAR Agent Census is a re-runnable investment-thesis tool: a seeded random sample of {g['blocks']:,} blocks ({g['first']} to {g['last']}, {g['txs']:,} transactions); "
        "each transaction's real initiator (relayed NEP-366 meta-transactions go to the user, the relayer is the fee payer) is scored from its own on-chain history by an explainable rule list. "
        f"Result: {pct(a['point'])}% of sampled transactions come from software-like accounts (95% CI {pct(a['lo'])}-{pct(a['hi'])}).".replace("%%", "%")
        + absn + valn
        + f" {len(claims)} thesis claims get verdicts decided by code from confidence intervals ({verdict_txt}), including ones that cut against the thesis.{clsn}{predn} "
        "Anyone can verify: a live in-browser account checker (matches the Python pipeline on 30 real accounts), explorer links for sampled transactions, CI on Linux, "
        "and one command, python -m census reproduce, that rebuilds every number offline. Automated includes AI agents but cannot isolate them. Not investment advice."
    )
    cov = f"{sw['b']['burn_cover'] * 100:.1f}%" if sw else None
    post1 = (f"Software-like accounts initiate {pct(a['point'])} of NEAR transactions, but total activity fell {tt['per_s_a']:.0f} -> {tt['per_s_b']:.0f} tx/s. "
             f"Fee burn covers {cov} of issuance, Intents revenue {pct(vw['b']['revenue_cover'])}.\n\n"
             "Live account checker + 8 predictions frozen & timestamped.\n\nBuilt at NEAR HACKATHON @NEARProtocol #NEARHackathon") if (tt and vw.get("b")) else (
             f"Software-like accounts initiate {pct(a['point'])} of NEAR transactions (95% CI {pct(a['lo'])}-{pct(a['hi'])}).\n\nBuilt at NEAR HACKATHON @NEARProtocol #NEARHackathon")
    post2 = ("Every number is re-runnable (CI green on Linux), every verdict decided by code. Try any NEAR account live in your browser:\n\n"
             f"Live: {LIVE}\nCode: {REPO}\n\nWhich metric should we add next?")
    return {"idea": idea, "post1": post1, "post2": post2, "verdicts": verdicts}


def run() -> None:
    d = build()
    assert 20 <= len(d["idea"]) <= IDEA_MAX, f"idea is {len(d['idea'])} chars (limit 20-{IDEA_MAX})"
    n1, n2 = x_length(d["post1"]), x_length(d["post2"])
    out = ["# Submission draft (generated; contains blanks only you can fill)\n",
           "Submit at https://nearhackathon.com/#apply before **14 Nov 2026 23:59 UTC**. Repository must be **public**.\n",
           "## Fields only you can supply (never guessed)\n",
           "| Field | Value |", "|---|---|",
           "| Project name | NEAR Agent Census (2-80 chars) |",
           "| Team lead name | ____ |", "| Email | ____ |", "| Team size | ____ (1, 2 - 4, 4 - 6, 6 - 8, 8+) |",
           "| Tracks | Investment Thesis (`thesis`); add others only if you want |",
           "| NEAR wallet (mainnet) | ____ |", f"| Repository | {REPO} |", f"| Website (optional field) | {LIVE} |", "| Demo post (X) link | ____ (after you post) |",
           "| Consent | read the notice aloud to yourself, then tick it |\n",
           f"## What did you build? ({len(d['idea'])} chars, limit 2000)\n", d["idea"] + "\n",
           f"## X post 1: attach the video ({n1}/{POST_MAX} chars, URLs counted as {TCO})\n", "```", d["post1"], "```\n",
           f"## X post 2: reply to post 1 ({n2}/{POST_MAX} chars)\n", "```", d["post2"], "```\n",
           "## If you post again: change the form entry\n",
           "Posting a new X post does not change what the form holds. Either (a) post the new video as a reply under the post already submitted (no change needed), or "
           "(b) use https://nearhackathon.com/request-changes with the email, NEAR wallet and repository link from the submission, tick **Demo post link** (and **What did you build**), "
           "and leave a Discord or Telegram handle. The organisers review it by hand.\n",
           f"### New \"What did you build?\" ({len(d['idea'])} chars, limit 2000)\n", d["idea"] + "\n",
           "Tag @NearLegion and @NearBuilders as well if you want more amplification (optional)."]
    assert n1 <= POST_MAX and n2 <= POST_MAX, f"X post too long: {n1}, {n2}"
    out_dir = C.ROOT / "submission"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "SUBMISSION.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote submission/SUBMISSION.md (idea {len(d['idea'])} chars; posts {n1} and {n2} chars)")


if __name__ == "__main__":
    run()
