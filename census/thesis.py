"""Stage 6a - thesis: evaluate each claim of the thesis against the data and write THESIS.md.

Every verdict is decided by code from confidence intervals, and every number in THESIS.md is formatted
from results.json / validation.json. Only the structure and the stated caveats are written by hand.
Re-running the pipeline on new data re-decides every verdict, including ones that cut against the thesis.
"""
from __future__ import annotations

import json

from . import config as C
from .util import jsonable

SUPPORTED, NOT, INCONCLUSIVE, INFO = "supported", "not_supported", "inconclusive", "info"
LABEL = {SUPPORTED: "SUPPORTED", NOT: "NOT SUPPORTED", INCONCLUSIVE: "INCONCLUSIVE", INFO: "DESCRIPTIVE"}


def pct(x, d=0):
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def pts(x, d=1):
    return "n/a" if x is None else f"{x * 100:+.{d}f} pts"


def _diff_verdict(m: dict | None) -> str:
    if not m:
        return INCONCLUSIVE
    if m["diff_lo"] > 0:
        return SUPPORTED
    if m["diff_hi"] < 0:
        return NOT
    return INCONCLUSIVE


def evaluate(res: dict, val: dict) -> list[dict]:
    claims = []
    lw = (res.get("latest_window") or {}).get("metrics", {})
    win = res.get("windows")
    wm = (win or {}).get("metrics", {})
    span = res.get("latest_window", {}).get("periods", [])
    span_txt = f"{span[0]} to {span[-1]}" if span else "the latest months"

    # C1 -- level
    m = lw.get("tx_auto")
    if m:
        v = SUPPORTED if m["lo"] > 0.5 else NOT if m["hi"] < 0.5 else INCONCLUSIVE
        claims.append({
            "id": "C1", "verdict": v,
            "statement": "Software already initiates the majority of NEAR transactions.",
            "evidence": f"Pooled over {span_txt}: {pct(m['point'])} of sampled transactions are initiated by automated accounts "
                        f"(95% CI {pct(m['lo'])} to {pct(m['hi'])}); the majority line (50%) is "
                        f"{'below' if m['lo'] > 0.5 else 'above' if m['hi'] < 0.5 else 'inside'} the interval.",
        })

    # C2 -- trend of the share
    for cid, name, text, noun in (
        ("C2", "tx_auto", "The automated share of transactions is rising.", "automated share of transactions"),
        ("C3", "fee_init_auto", "Automated accounts account for a rising share of fees.", "share of fees initiated by automated accounts"),
        ("C4", "to_intents", "Traffic addressed to NEAR Intents is growing as a share of transactions.", "share of transactions addressed to intents.near"),
    ):
        m = wm.get(name)
        if m:
            claims.append({
                "id": cid, "verdict": _diff_verdict(m), "statement": text,
                "evidence": f"{win['a'][0]}–{win['a'][-1]} → {win['b'][0]}–{win['b'][-1]}: {noun} went {pct(m['a'], 1)} → {pct(m['b'], 1)} "
                            f"({pts(m['diff'])}, 95% CI {pts(m['diff_lo'])} to {pts(m['diff_hi'])}).",
            })
        else:
            claims.append({"id": cid, "verdict": INCONCLUSIVE, "statement": text,
                           "evidence": "Not testable yet: the first-vs-latest comparison needs at least 12 densely sampled months."})

    # C2 caveat + C9 -- does the rise survive without the lifetime-volume rules?
    nl = wm.get("tx_auto_nolife")
    if nl:
        for c in claims:
            if c["id"] == "C2":
                c["evidence"] += (f" Without the lifetime-volume rules (which grow with account age by construction) the same comparison is "
                                  f"{pct(nl['a'], 1)} \u2192 {pct(nl['b'], 1)} ({pts(nl['diff'])}, 95% CI {pts(nl['diff_lo'])} to {pts(nl['diff_hi'])}).")
        claims.append({
            "id": "C9", "verdict": _diff_verdict(nl),
            "statement": "The rise in the automated share is not an artefact of lifetime-volume rules, which grow with account age.",
            "evidence": f"With those rules removed, the automated share goes {pct(nl['a'], 1)} \u2192 {pct(nl['b'], 1)} "
                        f"({pts(nl['diff'])}, 95% CI {pts(nl['diff_lo'])} to {pts(nl['diff_hi'])}). "
                        f"The headline rise is {pts(wm['tx_auto']['diff'])}, so part of its size comes from those rules and the rest survives without them."
                        if wm.get("tx_auto") else "",
        })

    # C10-C13 -- absolute levels (per second, so the 2025 block-time change does not distort the comparison)
    ab = (win or {}).get("abs", {})

    def ratio_verdict(m):
        if not m or m.get("ratio_per_s_lo") is None:
            return INCONCLUSIVE
        return SUPPORTED if m["ratio_per_s_lo"] > 1 else NOT if m["ratio_per_s_hi"] < 1 else INCONCLUSIVE

    def per_s(m, key, unit, d=2):
        return f"{m['per_s_a']:.{d}f} \u2192 {m['per_s_b']:.{d}f} {unit}"

    if ab.get("auto_tx_per_block"):
        m = ab["auto_tx_per_block"]
        claims.append({"id": "C10", "verdict": ratio_verdict(m),
                       "statement": "Software-driven activity is growing in absolute terms (automated transactions per second).",
                       "evidence": f"{win['a'][0]}-{win['a'][-1]} \u2192 {win['b'][0]}-{win['b'][-1]}: {per_s(m, 'auto', 'automated tx/s', 1)} "
                                   f"(x{m['ratio_per_s']:.2f}, 95% CI x{m['ratio_per_s_lo']:.2f} to x{m['ratio_per_s_hi']:.2f}); per block {m['a']:.1f} \u2192 {m['b']:.1f}. "
                                   f"Block time fell from {ab['_sec_per_block']['a']:.2f} s to {ab['_sec_per_block']['b']:.2f} s, which the per-second figure corrects for."})
    if ab.get("auto_fee_per_block"):
        m = ab["auto_fee_per_block"]
        claims.append({"id": "C11", "verdict": ratio_verdict(m),
                       "statement": "Automated accounts generate more fee burn in absolute terms (NEAR per second).",
                       "evidence": f"{per_s(m, 'fee', 'NEAR/s', 4)} (x{m['ratio_per_s']:.2f}, 95% CI x{m['ratio_per_s_lo']:.2f} to x{m['ratio_per_s_hi']:.2f}); "
                                   f"fees initiated by automated accounts, from the per-transaction burnt amount."})
    if ab.get("intents_tx_per_block"):
        m = ab["intents_tx_per_block"]
        v = SUPPORTED if m["diff_lo"] > 0 else NOT if m["diff_hi"] < 0 else INCONCLUSIVE
        claims.append({"id": "C12", "verdict": v,
                       "statement": "Traffic addressed to NEAR Intents is growing in absolute terms (transactions per second).",
                       "evidence": f"{per_s(m, 'intents', 'tx/s', 2)} (per-block change {m['diff']:+.2f}, 95% CI {m['diff_lo']:+.2f} to {m['diff_hi']:+.2f}). "
                                   "A lower bound: only transactions addressed to intents.near are counted."})
    if ab.get("total_tx_per_block"):
        t, tf = ab["total_tx_per_block"], ab.get("total_fee_per_block")
        h = ab.get("human_tx_per_block")
        claims.append({"id": "C13", "verdict": INFO,
                       "statement": "Total network activity per second changed between the two windows.",
                       "evidence": f"All transactions {per_s(t, 'tx', 'tx/s', 1)} (x{t['ratio_per_s']:.2f}, CI x{t['ratio_per_s_lo']:.2f} to x{t['ratio_per_s_hi']:.2f})"
                                   + (f"; human-like {per_s(h, 'h', 'tx/s', 1)} (x{h['ratio_per_s']:.2f})" if h else "")
                                   + (f"; total fee burn {per_s(tf, 'f', 'NEAR/s', 4)} (x{tf['ratio_per_s']:.2f}, CI x{tf['ratio_per_s_lo']:.2f} to x{tf['ratio_per_s_hi']:.2f})." if tf else ".")})
    for c in claims:        # a rising share must not be read as rising activity
        if c["id"] == "C2" and any(x["id"] == "C10" and x["verdict"] != SUPPORTED for x in claims):
            c["evidence"] += " Caution: the share can rise because other activity fell; see C10 and C13 for absolute levels."

    # C5 -- who pays
    a, b = lw.get("fee_init_auto"), lw.get("fee_paid_auto")
    if a and b:
        overlap = not (a["hi"] < b["lo"] or b["hi"] < a["lo"])
        claims.append({
            "id": "C5", "verdict": INFO,
            "statement": "The account that pays a fee is often not the account that initiated the transaction (relayers, NEP-366).",
            "evidence": f"Over {span_txt}, automated accounts initiated {pct(a['point'])} of fees (CI {pct(a['lo'])}-{pct(a['hi'])}) "
                        f"while on-chain fee payers classified as automated paid {pct(b['point'])} (CI {pct(b['lo'])}-{pct(b['hi'])}); "
                        f"the two intervals {'overlap' if overlap else 'do not overlap'}. "
                        f"{pct(lw.get('relayed', {}).get('point'))} of transactions were relayed.",
        })

    # C6 -- robustness to the cut-off
    t40, t50, t60 = lw.get("tx_auto_t40"), lw.get("tx_auto"), lw.get("tx_auto_t60")
    if t40 and t50 and t60:
        spread = t40["point"] - t60["point"]
        claims.append({
            "id": "C6", "verdict": SUPPORTED if spread <= 0.10 else NOT,
            "statement": "The headline share is robust to where the 'automated' cut-off is placed (within 10 points between thresholds 40 and 60).",
            "evidence": f"Automated share at threshold 60 / 50 / 40: {pct(t60['point'])} / {pct(t50['point'])} / {pct(t40['point'])} "
                        f"(a {abs(spread) * 100:.0f}-point spread). "
                        + ("The level is therefore reported as a range." if spread > 0.10 else ""),
        })

    # C7 -- classifier quality (held-out)
    t = (val or {}).get("test") or {}
    if t and t.get("n_classified", 0) >= 10:
        lo = min(t["recall_automated_ci"][0], t["recall_human_ci"][0])
        pt = min(t["recall_automated"], t["recall_human"])
        v = SUPPORTED if lo >= 0.70 else INCONCLUSIVE if pt >= 0.80 else NOT
        claims.append({
            "id": "C7", "verdict": v,
            "statement": "The classifier separates labelled software from labelled people on held-out accounts.",
            "evidence": f"Test split (n={t['n_classified']} classified of {t['n_labelled']} labelled): recall for automated {pct(t['recall_automated'])} "
                        f"(Wilson CI {pct(t['recall_automated_ci'][0])}–{pct(t['recall_automated_ci'][1])}), for human {pct(t['recall_human'])} "
                        f"(CI {pct(t['recall_human_ci'][0])}–{pct(t['recall_human_ci'][1])}), balanced accuracy {pct(t['balanced_accuracy'])}. "
                        f"The labels are biased toward self-declared bots and engaged humans, so this is an optimistic ceiling.",
        })
    else:
        claims.append({"id": "C7", "verdict": INCONCLUSIVE, "statement": "The classifier separates labelled software from labelled people on held-out accounts.",
                       "evidence": "Not yet testable: too few labelled accounts matched the sample."})

    # C8 -- concentration
    c = res.get("concentration") or {}
    if c.get("automated_accounts_in_sample"):
        claims.append({
            "id": "C8", "verdict": INFO,
            "statement": "Automated activity is concentrated in a small number of accounts.",
            "evidence": f"{c['accounts_for_half_of_automated_txs']} of the {c['automated_accounts_in_sample']} automated accounts in the sample "
                        f"({c['periods'][0]}–{c['periods'][-1]}) produce half of all automated transactions.",
        })
    claims.sort(key=lambda c: int(c["id"][1:]))
    return claims


def bottom_line(claims: list[dict], res: dict) -> str:
    """One generated paragraph that states what the verdicts jointly say (branches on the computed verdicts)."""
    by = {c["id"]: c for c in claims}
    v = lambda i: by.get(i, {}).get("verdict")
    ab = ((res.get("windows") or {}).get("abs")) or {}
    if not ab or v("C2") is None:
        return "Not enough dense months yet to compare two windows; see the verdict table."
    t, a, f = ab.get("total_tx_per_block"), ab.get("auto_tx_per_block"), ab.get("auto_fee_per_block")
    h = ab.get("human_tx_per_block")
    rel_up, abs_up = v("C2") == SUPPORTED, v("C10") == SUPPORTED
    nums = (f"Total activity went {t['per_s_a']:.1f} \u2192 {t['per_s_b']:.1f} tx/s, automated {a['per_s_a']:.1f} \u2192 {a['per_s_b']:.1f} tx/s"
            + (f", human-like {h['per_s_a']:.1f} \u2192 {h['per_s_b']:.1f} tx/s" if h else "")
            + f"; fee burn by automated accounts {f['per_s_a']:.4f} \u2192 {f['per_s_b']:.4f} NEAR/s.") if t and a and f else ""
    if rel_up and abs_up:
        return "Software's share of NEAR activity is rising and its absolute activity is rising too. " + nums
    if rel_up and not abs_up:
        rel = ((res.get("windows") or {}).get("metrics") or {}).get("relayed")
        relayed = (f" The relayed share of transactions went {pct(rel['a'])} \u2192 {pct(rel['b'])}." if rel else "")
        return ("**Software's share of NEAR activity rose, but software activity did not.** The share rose because the rest of the activity "
                "(classified human-like) fell faster than automated activity did. " + nums + relayed + " The data therefore supports "
                "\"NEAR activity is increasingly dominated by software\" and does **not** support \"software activity on NEAR is growing\".")
    return "The automated share did not rise detectably between the two windows. " + nums


def would_change_my_mind(claims: list[dict], res: dict) -> list[str]:
    by = {c["id"]: c for c in claims}
    out = []
    lw = (res.get("latest_window") or {}).get("metrics", {})
    m = lw.get("tx_auto")
    if m:
        out.append(f"**C1 flips** if a larger or later sample puts the whole 95% interval on one side of 50%: it is currently "
                   f"{pct(m['lo'])}–{pct(m['hi'])}, so it is **{LABEL[by['C1']['verdict']].lower()}** today. More blocks per month narrows it; the code exposes `BLOCKS_PER_PERIOD`.")
    out.append("**The trend claims (C2–C4) flip** if the first-vs-latest difference interval moves to one side of zero. "
               "A falling automated share, or a falling intents share, would be evidence **against** the adoption thesis and would be reported as such.")
    out.append("**The absolute-growth claims (C10-C12) flip** if the per-second ratio interval moves above 1 (software activity or its fee burn "
               "growing) or the Intents level keeps rising; they are decided from the same bootstrap as the share claims.")
    out.append("**The classifier claim (C7) fails** if a labelled set built by someone else (for example a published registry of agent accounts) "
               "gives materially lower recall than the self-built labels. The label builder is `census/labels.py`; swapping in other labels is one CSV.")
    out.append("**The framing fails** if most automated activity turns out to be relayers and games rather than economic agents: "
               "the top-account table on the dashboard lets a reader judge that directly, and nothing in this method can rule it out.")
    return out


def render(res: dict, val: dict, claims: list[dict]) -> str:
    g = res["generated_from"]
    sup = [c for c in claims if c["verdict"] == SUPPORTED]
    against = [c for c in claims if c["verdict"] in (NOT, INCONCLUSIVE)]
    info = [c for c in claims if c["verdict"] == INFO]
    L = []
    w = L.append
    w("# Investment thesis\n")
    w("_Generated by `python -m census thesis` from the committed sample. Every number and every verdict below is computed; "
      "only the structure and the caveats are written by hand. Re-running on new data re-decides each verdict._\n")
    w("## The claim\n")
    w("> NEAR's long-term value depends on software, not only people, transacting on it. The measurable preconditions are that "
      "automated activity is **large**, **growing**, and **economically material** (it pays fees).\n")
    w(f"This is a hypothesis taken from the project brief, not a result. The census tests each part of it on a random sample of "
      f"{g['blocks']:,} NEAR blocks ({g['first']} → {g['last']}, {g['txs']:,} transactions). "
      "\"Automated\" means *behaves like software*: it includes AI agents, trading and keeper bots, oracles and relayers, "
      "and behaviour alone cannot separate them (see [METHODOLOGY.md](METHODOLOGY.md)).\n")
    w("## Bottom line\n")
    w(bottom_line(claims, res) + "\n")
    w("## Verdicts\n")
    w("| # | Claim | Verdict | Evidence |")
    w("|---|---|---|---|")
    for c in claims:
        w(f"| {c['id']} | {c['statement']} | **{LABEL[c['verdict']]}** | {c['evidence']} |")
    w("\n## Evidence for\n")
    w("\n".join(f"* **{c['id']}.** {c['statement']} {c['evidence']}" for c in sup) or "_No claim is supported at the 95% level by the current sample._")
    w("\n## Evidence against, and what the data cannot say\n")
    w("\n".join(f"* **{c['id']} ({LABEL[c['verdict']].lower()}).** {c['statement']} {c['evidence']}" for c in against) or "_Every testable claim is supported._")
    if info:
        w("\n### Descriptive findings (no verdict)\n")
        w("\n".join(f"* **{c['id']}.** {c['statement']} {c['evidence']}" for c in info))
    w("\n### Limits no amount of data fixes\n")
    w("* **Automated is not the same as AI agent.** Behaviour cannot tell an LLM agent from a cron job or a relayer. The measure is an upper-level proxy for agent activity.")
    w("* **Validation labels are biased** toward self-declared bots and engaged humans; stealthy bots and anonymous humans are under-represented, so accuracy is optimistic exactly where it matters.")
    w("* **A relayed user is not an agent.** Relayers pay and sign transactions that humans author; the census attributes the *initiator* (and reports the payer separately), but mini-app users whose clicks look regular can still be classed as automated.")
    w("* **Fee levels are not comparable across protocol v87**, when contracts stopped receiving 30% of burnt gas and all of it began to be burned ([gas docs](https://docs.near.org/protocol/transactions/gas)). Shares are used for that reason.")
    w("* **Sample, not census of every block.** Intervals describe sampling noise only.\n")
    w("## What would change my mind\n")
    w("\n".join(f"{i}. {t}" for i, t in enumerate(would_change_my_mind(claims, res), 1)))
    w("\n## Why this matters for an investor\n")
    w("NEAR's execution fees are paid in NEAR and, from protocol v87, burned in full. Fee share by automated accounts is therefore a direct, "
      "measurable link between software activity and token demand for gas. This repository measures that link; it does **not** estimate price, "
      "and nothing here is investment advice.\n")
    w("## Reproduce\n")
    w("```bash\npython -m census reproduce   # re-decides every verdict above from data/derived/\n```\n")
    return "\n".join(L) + "\n"


def run() -> None:
    res = json.loads((C.DERIVED / "results.json").read_text())
    vpath = C.DERIVED / "validation.json"
    val = json.loads(vpath.read_text()) if vpath.exists() else {}
    claims = evaluate(res, val)
    res["claims"] = claims
    res["thesis_changes_mind"] = would_change_my_mind(claims, res)
    res["bottom_line"] = bottom_line(claims, res)
    (C.DERIVED / "results.json").write_text(json.dumps(jsonable(res), indent=1))
    (C.ROOT / "THESIS.md").write_text(render(res, val, claims), encoding="utf-8")
    print("wrote THESIS.md: " + ", ".join(f"{c['id']}={LABEL[c['verdict']]}" for c in claims))


if __name__ == "__main__":
    run()
