"""Value-capture claims for the thesis: does usage pay for NEAR's issuance? (decided by code, like every other claim)

Chain-side quantities are measured from the sampled blocks (census/supply.py). Intents revenue and the NEAR price are third-party series
(DefiLlama, committed snapshot) used exactly as published. Revenue is NEAR's net captured Intents revenue; per DefiLlama, since 2026-02-23 it is
used for open-market buybacks (not burned), so it is described as buyback-funding revenue and never as burn.
"""
from __future__ import annotations


def _p(x, d=1):
    return f"{x * 100:.{d}f}%"


def value_claims(res: dict) -> list[dict]:
    from . import thesis as T          # imported late: thesis imports this module
    sup = res.get("supply") or {}
    sw, val = sup.get("windows"), sup.get("value") or {}
    vw = (val.get("windows") or {})
    step = sup.get("issuance_step")
    claims = []

    if sw:
        a, b = sw["a"], sw["b"]
        v = T.NOT if b["burn_cover_ci"][1] < 1 else T.SUPPORTED if b["burn_cover_ci"][0] >= 1 else T.INCONCLUSIVE
        claims.append({
            "id": "C14", "verdict": v,
            "statement": "L1 fee burn alone covers NEAR's issuance (usage pays for the tokens minted).",
            "evidence": f"Estimated burn covered {_p(b['burn_cover'], 2)} of gross issuance in {b['periods'][0]}-{b['periods'][-1]} "
                        f"(95% CI {_p(b['burn_cover_ci'][0], 2)} to {_p(b['burn_cover_ci'][1], 2)}), against {_p(a['burn_cover'], 2)} in "
                        f"{a['periods'][0]}-{a['periods'][-1]}. Gross issuance = net supply growth + burn; burn is the header fee x 0.70 on protocol <= v86 "
                        f"and x 1.00 from v87 (NEAR gas docs)."})

    if step:
        claims.append({
            "id": "C15", "verdict": T.SUPPORTED if step["disjoint_intervals"] and step["relative_change"] < 0 else T.INCONCLUSIVE,
            "statement": "NEAR's net issuance (dilution) fell sharply during the study period.",
            "evidence": f"Measured from block-header supply, net issuance fell from {step['before']:.2f} NEAR/s ({step['before_pct_per_year']:.2f}% of supply per year) "
                        f"in {step['from']} to {step['after']:.2f} NEAR/s ({step['after_pct_per_year']:.2f}% per year) in {step['to']}, a {abs(step['relative_change']) * 100:.0f}% drop "
                        f"between consecutive sampled months with disjoint 95% intervals. The cause is not determined here."
                        + (f" Window averages: {sw['a']['net_issuance_ps']:.2f} -> {sw['b']['net_issuance_ps']:.2f} NEAR/s." if sw else "")})

    if vw.get("b"):
        b = vw["b"]
        ci = b["revenue_cover_ci"]
        v = T.NOT if ci[1] < 1 else T.SUPPORTED if ci[0] >= 1 else T.INCONCLUSIVE
        need = 1 / b["revenue_cover"] if b["revenue_cover"] else None
        claims.append({
            "id": "C16", "verdict": v,
            "statement": "NEAR Intents revenue covers NEAR's issuance in USD terms.",
            "evidence": f"Over {b['periods'][0]}-{b['periods'][-1]}, reported Intents revenue of ${b['intents_revenue_usd_day']:,.0f}/day covered {_p(b['revenue_cover'])} of "
                        f"gross issuance valued at ${b['issuance_usd_day']:,.0f}/day (95% CI of the cover {_p(ci[0])} to {_p(ci[1])}; the interval reflects the chain-side "
                        f"issuance estimate only, revenue and price are taken as published)."
                        + (f" At that price, revenue would have to grow about x{need:.1f} to cover issuance." if need else "")})

    if vw.get("a") and vw.get("b"):
        a, b = vw["a"], vw["b"]
        rev_x = b["intents_revenue_usd_day"] / a["intents_revenue_usd_day"] if a["intents_revenue_usd_day"] else None
        iss_x = b["issuance_usd_day"] / a["issuance_usd_day"]
        cov_x = b["revenue_cover"] / a["revenue_cover"] if a["revenue_cover"] else None
        v = T.SUPPORTED if b["revenue_cover_ci"][0] > a["revenue_cover_ci"][1] else T.NOT if b["revenue_cover_ci"][1] < a["revenue_cover_ci"][0] else T.INCONCLUSIVE
        claims.append({
            "id": "C17", "verdict": v,
            "statement": "Intents value capture relative to issuance is rising.",
            "evidence": f"Cover of issuance by Intents revenue: {_p(a['revenue_cover'])} ({a['periods'][0]}-{a['periods'][-1]}) -> {_p(b['revenue_cover'])} "
                        f"({b['periods'][0]}-{b['periods'][-1]})"
                        + (f", a x{cov_x:.1f} change. Decomposition: revenue x{rev_x:.1f} (${a['intents_revenue_usd_day']:,.0f} -> ${b['intents_revenue_usd_day']:,.0f}/day) and "
                           f"issuance valued in USD x{iss_x:.2f} (${a['issuance_usd_day']:,.0f} -> ${b['issuance_usd_day']:,.0f}/day), because issuance fell and the price moved." if rev_x and cov_x else ".")})

        l1a, l1b = a["l1_fees_usd_day"], b["l1_fees_usd_day"]
        claims.append({
            "id": "C18", "verdict": T.INFO,
            "statement": "Intents revenue is now large relative to L1 fees.",
            "evidence": f"Reported Intents revenue was x{a['revenue_vs_l1_fees']:.1f} L1 fees in {a['periods'][0]}-{a['periods'][-1]} and x{b['revenue_vs_l1_fees']:.1f} in "
                        f"{b['periods'][0]}-{b['periods'][-1]} (L1 fees ${l1a:,.0f} -> ${l1b:,.0f}/day, from block headers valued at the monthly average price). "
                        f"Combined with estimated L1 burn, revenue + burn covered {_p(b['combined_cover'])} of issuance."})
    return claims


def value_line(res: dict) -> str:
    """One generated paragraph on the value side, for THESIS.md and the dashboard."""
    sup = res.get("supply") or {}
    vw = (sup.get("value") or {}).get("windows") or {}
    sw = sup.get("windows")
    if not (sw and vw.get("a") and vw.get("b")):
        return ""
    a, b = vw["a"], vw["b"]
    return (f"On the value side, usage does not yet pay for issuance: estimated L1 burn covered {_p(sw['b']['burn_cover'], 2)} of gross issuance, and reported Intents revenue "
            f"covered {_p(b['revenue_cover'])} (up from {_p(a['revenue_cover'])}). Most of that rise is revenue growth (x{b['intents_revenue_usd_day'] / a['intents_revenue_usd_day']:.1f}); "
            f"the rest is a smaller issuance bill (x{b['issuance_usd_day'] / a['issuance_usd_day']:.2f} in USD).")
