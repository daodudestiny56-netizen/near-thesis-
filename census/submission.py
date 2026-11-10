"""Stage 7 - submission: draft the form text and the X post from the final results (numbers are computed).

Writes submission/SUBMISSION.md (git-ignored: it will hold personal details). Nothing is sent anywhere.
The fields only the human can supply (name, email, wallet, team size, demo post link) are left as explicit blanks.
"""
from __future__ import annotations

import json

from . import config as C

REPO = "https://github.com/daodudestiny56-netizen/near-thesis-"
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
    absn = ""
    if ab.get("auto_tx_per_block") and ab.get("total_tx_per_block"):
        at, tt = ab["auto_tx_per_block"], ab["total_tx_per_block"]
        absn = (f" But in absolute terms total activity fell from {tt['per_s_a']:.0f} to {tt['per_s_b']:.0f} tx/s and automated activity from "
                f"{at['per_s_a']:.0f} to {at['per_s_b']:.0f} tx/s, so the share rose because other activity fell faster.")
    cls = (f" On a held-out test split the classifier finds {pct(t['recall_automated'])} of labelled automated accounts and keeps "
           f"{pct(t['recall_human'])} of labelled humans human (labels are biased toward self-declared bots and engaged humans, so that is an optimistic ceiling).") if t.get("n_classified") else ""
    names = {"info": "descriptive", "not_supported": "not supported"}
    verdict_txt = ", ".join(f"{n} {names.get(k, k)}" for k, n in sorted(verdicts.items()))

    idea = (
        "NEAR's pitch is that software, including AI agents, will transact on it, but nobody publishes a measured number. "
        "The NEAR Agent Census is a re-runnable investment-thesis tool that estimates how much of NEAR's activity is software. "
        f"It draws a seeded random sample of {g['blocks']:,} blocks ({g['first']} to {g['last']}, {g['txs']:,} transactions), resolves each "
        "transaction's real initiator (relayed NEP-366 meta-transactions are attributed to the user, with the relayer tracked as fee payer), "
        "profiles that account from its own on-chain history and scores it with an explainable rule list. "
        f"Result: over {span[0]} to {span[-1]}, {pct(a['point'])} of sampled transactions were initiated by software-like accounts "
        f"(95% CI {pct(a['lo'])}-{pct(a['hi'])}; {pct(lo['point'])}-{pct(hi['point'])} across classifier cut-offs), "
        f"which initiated {pct(fi['point'])} of fees and paid {pct(fp['point'])}.{absn}"
        f"{cls} Each claim of the thesis gets a verdict decided by code from confidence intervals ({verdict_txt}), "
        "including ones that cut against it. The dashboard lets anyone verify: random sampled transactions link to an explorer, "
        "and any account's verdict shows the exact rules that fired. NEAR fits because per-account history is public, meta-transactions split "
        "who acts from who pays, function-call keys shape agent behaviour, and NEAR Intents traffic is measured. "
        "One command, python -m census reproduce, rebuilds every number offline. Automated includes AI agents but cannot isolate them. Not investment advice."
    )
    if ab.get("total_tx_per_block") and ab.get("auto_tx_per_block"):
        tt, at = ab["total_tx_per_block"], ab["auto_tx_per_block"]
        post1 = (
            f"Software-like accounts initiate {pct(a['point'])} of NEAR transactions (95% CI {pct(a['lo'])}-{pct(a['hi'])}).\n\n"
            f"But total activity fell {tt['per_s_a']:.0f} -> {tt['per_s_b']:.0f} tx/s: the share rose because everything else shrank faster.\n\n"
            f"Random-sample census, every number re-runnable. Built at NEAR HACKATHON @NEARProtocol #NEARHackathon"
        )
    else:
        post1 = (
            f"Is NEAR becoming the chain software lives on? We measured it.\n\n"
            f"In a random sample of {g['blocks']:,} NEAR blocks, software-like accounts initiated {pct(a['point'])} of transactions "
            f"(95% CI {pct(a['lo'])}-{pct(a['hi'])}). Every number re-runnable.\n\n"
            f"Built at NEAR HACKATHON @NEARProtocol #NEARHackathon"
        )
    intents = ab.get("intents_tx_per_block")
    post2 = (
        f"On NEAR, meta-tx split who acts from who pays: software-like accounts initiated {pct(fi['point'])} of fees but paid {pct(fp['point'])}."
        + (f" Intents traffic: {intents['per_s_a']:.1f} -> {intents['per_s_b']:.1f} tx/s." if intents else "")
        + f"\n\nVerify any claim on the dashboard. Which metric should we add next?\n\n{REPO}"
    )
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
           "| NEAR wallet (mainnet) | ____ |", f"| Repository | {REPO} |", "| Demo post (X) link | ____ (after you post) |",
           "| Consent | read the notice aloud to yourself, then tick it |\n",
           f"## What did you build? ({len(d['idea'])} chars, limit 2000)\n", d["idea"] + "\n",
           f"## X post 1: attach the video ({n1}/{POST_MAX} chars, URLs counted as {TCO})\n", "```", d["post1"], "```\n",
           f"## X post 2: reply to post 1 ({n2}/{POST_MAX} chars)\n", "```", d["post2"], "```\n",
           "Tag @NearLegion and @NearBuilders as well if you want more amplification (optional)."]
    assert n1 <= POST_MAX and n2 <= POST_MAX, f"X post too long: {n1}, {n2}"
    out_dir = C.ROOT / "submission"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "SUBMISSION.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote submission/SUBMISSION.md (idea {len(d['idea'])} chars; posts {n1} and {n2} chars)")


if __name__ == "__main__":
    run()
