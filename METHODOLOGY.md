# Methodology

This document says exactly what the NEAR Agent Census measures, how, and where it can be wrong. It
contains no result numbers; those are generated into [RESULTS.md](RESULTS.md) and the
[dashboard](docs/index.html) by the code, so they cannot drift from the method.

## 1. The question

> What share of NEAR's on-chain activity, and of the fees it pays, comes from accounts that behave like software?

"Behave like software" is a *behavioural* definition. We cannot see who or what holds a key, only what
the key does. The measure therefore includes AI agents, trading and keeper bots, oracle updaters and
relayers, and it cannot separate an LLM agent from a cron job. We call the class **automated**.
Treat the result as an upper-level measure of agent activity, not a headcount of AI agents.

## 2. Data

Everything comes from the public [FastNEAR Transactions API](https://docs.fastnear.com/tx)
(`tx.main.fastnear.com/v0`). It needs no account; an optional free key only raises the rate limit.
Three calls are used: `block` (with its transactions), `account` (an account's signed-transaction
history) and `transactions` (full transaction bodies).

We did not use the NEAR BigQuery public dataset as the primary source because NEAR Lake, which feeds it,
was deprecated on 24 March 2026 and we could not confirm the dataset is current. We did not use NearBlocks
because its free tier (about 10k calls/month) cannot support a census.

## 3. Sampling design

NEAR produces roughly 144,000 blocks a day, so a full crawl through a public API is not realistic. The
census is a **random sample**, which also gives honest error bars.

* **Periods.** Every calendar month from `DENSE_FROM` (2024-01) to today, plus four baseline months (2022-01, 2022-07, 2023-01,
  2023-07). 2021 is excluded: its blocks hold about one transaction per 25 blocks, too few to measure. Constants live in
  [census/config.py](census/config.py).
* **Blocks.** For each dense month, 45 block heights are drawn uniformly at random from that month's height range; baseline months
  draw 200 (early blocks hold few transactions). The seed is fixed, so a re-run draws the same blocks. Skipped heights are dropped.
* **Transactions.** Every transaction in a sampled block is in the sample. A transaction's chance of being
  sampled is the same as any other's in that month, so ratios of sums are unbiased estimators of
  network-wide ratios.
* **Intervals.** Transactions in one block are correlated (one bot can fire many), so intervals come from a
  **cluster bootstrap over blocks** (1000 resamples, fixed seed), not from a binomial formula.

Only **transaction-weighted and fee-weighted** shares are reported. A share of *distinct accounts* would be
biased toward bots, because a bot appears in almost every sampled block while a once-a-week human almost
never does. Account-level questions are answered with concentration statistics instead.

## 4. Who is the actor? Initiator versus fee payer

NEAR supports meta-transactions (NEP-366): a **relayer** signs and pays for a transaction a **user** authored.
We keep both identities for every transaction:

* **Initiator** = `real_signer_id` (the user behind a relayed transaction, otherwise the signer).
* **Fee payer** = `signer_id` (the relayer, for relayed transactions).

Classifying the initiator answers "who is acting"; classifying the payer answers "who bears the cost". They
differ exactly when relayers subsidise users, which on NEAR is common.

## 5. Features (behaviour only)

Each account is profiled from its **last 200 transactions signed before the end of the month**
(`/v0/account`, `is_real_signer`). Computed in [census/features.py](census/features.py):

| Feature | Meaning | Why it separates software from people |
|---|---|---|
| `txs_count_total` | lifetime signed transactions | machines sign orders of magnitude more |
| `rate_per_day` | transactions per day inside the window | sustained throughput |
| `fast_share` | share of gaps ≤ 5 s | machine-speed bursts |
| `periodic_share` | share of gaps within ±10% of the median gap | schedules (cron, keepers) |
| `rest_per_day` | silent stretches ≥ 5 h per day (needs ≥ 2 days of window) | humans sleep |
| `hour_coverage` | share of the 24 UTC hours with activity (needs ≥ 2 days) | round-the-clock operation |
| `fail_rate` | share of failed transactions | retrying scripts |
| `fc_key_share` | share of sampled txs shaped like a function-call-key transaction | agents are often given restricted keys |

**Function-call keys.** A function-call key can only call one contract and cannot attach a deposit
([docs](https://docs.near.org/protocol/accounts-contracts/access-keys)). Historic key permissions are not
exposed by the API, so we use a *shape proxy*: exactly one `FunctionCall` action with zero deposit
(unwrapping a meta-transaction's delegate action first). The proxy is necessary but not sufficient, so it
carries a small weight (5 points), and the ablation in the validation report shows what it contributes.

**NEAR Intents.** We report the share of transactions addressed to `intents.near`. That is a lower bound on
intents involvement: deposits routed through token contracts are visible only in the subsample of
transactions we fetch in full. Intents use is not a classifier feature, because relayers that serve every
user would otherwise look automated for the wrong reason.

Account names, NEAR Social profiles and every other off-chain signal are **not** classifier inputs. They are
used only to build validation labels (section 7), so labels and classifier are independent.

## 6. Classifier

A transparent additive rule list ([census/classify.py](census/classify.py)): each rule is a named condition
with a point value, and an account's score is the clipped sum (0 to 100). Score ≥ 50 means **automated**.
Accounts with fewer than 8 observed transactions are **low_activity**: there is not enough evidence to judge,
so they are never silently called human. Every share is reported with that class broken out, so the reader
sees a lower bound (low-activity as human) and an upper bound (low-activity as automated).

We chose rules over a trained model deliberately: with a small, biased label set a fitted model would mostly
memorise the labelling shortcuts, while a rule list can be audited line by line and ablated.

## 7. Validation

* **Labels** ([census/labels.py](census/labels.py), [data/labels/](data/labels/)). *Human:* the account has a
  NEAR Social (SocialDB) profile name, an on-chain identity a person wrote about themselves. *Automated:* the
  account id declares an automated role (`bot`, `relayer`, `keeper`, `oracle`, `solver`, …) or is documented
  infrastructure. Every candidate was reviewed (by Claude Code, with the author able to audit it); removals and their reasons are recorded in
  [data/labels/review_notes.md](data/labels/review_notes.md).
* **Split.** Half the labels are a **held-out test split** chosen by a hash of the account id, so the split
  cannot be cherry-picked. Rule weights were set while looking at the **dev** split only. Headline accuracy is
  **test only**.
* **Reported.** Coverage (how often we abstain), per-class recall with Wilson 95% intervals, precision, balanced
  accuracy, ROC AUC of the raw score, a threshold sweep, and a leave-one-rule-out ablation.

### Tuning history (full disclosure)

The held-out test split was not scored or printed during tuning (`python -m census validate --dev-only` withholds it). Changes made, in order:

1. **Initial weights** were set from first principles before any label existed.
2. **Volume weights raised** (`lifetime_volume_very_high` 20 → 25, `sustained_rate_very_high` 15 → 25) after the dev split showed
   high-volume infrastructure (MPC nodes, relayers signing 1,000+ txs/day) scoring just under the threshold. Dev recall for
   automated accounts moved from 0.43 to 0.79; human recall stayed at 0.99. Four dev errors remain (moderate-rate watchers
   and one ambiguous account); they were **not** chased, to avoid fitting individual accounts on a small label set.

### Known limits of the validation (please read)

1. **Label bias.** Human labels over-represent people who filled in a profile; automated labels over-represent
   bots that announce themselves. Stealthy bots and anonymous humans are under-represented, so measured accuracy
   is **optimistic** for exactly the hard cases.
2. **Not a ground truth for "AI agent".** There is no public registry of which accounts are LLM agents.
   Labels distinguish software from people, not agents from scripts.
3. **Window truncation.** For accounts with more than 200 recent transactions the window may cover only minutes,
   so circadian features are undefined; the classifier then relies on volume, rate and gap structure.
4. **Mini-app users.** Telegram mini-app games (e.g. `*.tg`) are human-driven but may click at regular
   intervals. Where behaviour looks automated, the classifier will say so; we do not override it.

## 8. Fees

Fee per transaction is the indexer's per-transaction `tokens_burnt`. In a 6-transaction cross-check this was
about 88% of the sum of `tokens_burnt` over the full receipt tree; we did not establish why (refund receipts are
the likely cause), so fee **shares** are reported rather than absolute amounts, and treated as proportional.

**Protocol break.** Through protocol version 86, contracts received 30% of the gas they burned; from version 87
all of it is burned ([gas docs](https://docs.near.org/protocol/transactions/gas)). Fee levels are not comparable
across that boundary; shares of fees are less affected but not immune.

## 9. Shares are not activity: absolute levels, and why there is no forecast

A *share* is a ratio. It rises when the numerator rises **or when the denominator falls**, so a rising automated share is not by itself evidence
that software activity is growing. The census therefore also reports **absolute levels**:

* `automated transactions per second` = (automated share of sampled transactions) × (mean transactions per block, read from every sampled block's
  header) ÷ (seconds per block). The header totals are observed for every sampled block, not only for the capped transaction sample.
* `fee burn per second`, built the same way from the headers' `tokens_burnt`.
* Block time is **measured**, not assumed: seconds per block = (latest − earliest sampled timestamp) ÷ (highest − lowest sampled height) within each month.
  It fell from about 1.2 s (2024-H1) to about 0.6 s (latest months), so per-block comparisons would flatter the recent period; per-second figures correct for it.
* Intervals are a bootstrap over blocks (the share and the header mean are resampled together).

**No forecast is shown.** An earlier design extrapolated a logit-linear trend of the share. The monthly series contains a **step change** (total activity per
block falls about five-fold between 2026-03 and 2026-04), and a straight line through a step would fabricate a smooth path. `analyze.trend_forecast`
remains in the code for reference but is deliberately not displayed or used in any claim. A reader who wants a forecast should model the regimes, not the line.

**Sensitivity to the lifetime-volume rules.** Two classifier rules use an account's lifetime transaction count, which grows with age by construction. The pipeline
recomputes the trend with those rules removed (`tx_auto_nolife`) and reports both, so the size of the rise is not overstated.

## 10. Supply, burn and value capture: does usage pay for issuance?

**Measured from the sampled blocks** ([census/supply.py](census/supply.py)). Each block header carries `total_supply`, `tokens_burnt` and `protocol_version`.

* **Net issuance** = slope of `total_supply` against block time, an OLS fit over the month's sampled blocks. Within a month supply grows almost exactly
  linearly (R² about 0.9999 in the months checked), so the slope is well determined; the interval is a bootstrap over blocks.
* **Burn** = header fee × 0.70 on blocks with `protocol_version` ≤ 86, × 1.00 from v87. NEAR's gas docs: up to v86 contracts received 30% of the gas they
  burned (not removed from supply); from v87 all of it is burned. The 0.70 is applied to the whole header fee, which is an approximation (the 30% applies to
  gas burned while contracts execute). Using the full fee instead would raise the burn estimate by at most 1/0.7; the conclusion that burn covers a small share of
  issuance does not depend on it. The first sampled block with version ≥ 87 is in 2026-11, so almost the whole study period is on the old rule.
* **Gross issuance** = net issuance + burn (tokens minted per second). **Coverage** = burn ÷ gross issuance.
* No inflation rate is assumed: the halving of net issuance between 2025-10 and 2025-11 (4.9% to 2.4% of supply per year) is read off the headers.
  Its cause is **not** determined here.

**Third-party inputs, used as published** ([census/external.py](census/external.py), committed under `data/external/` with the retrieval date).
Intents **revenue** and **fees** and the **NEAR price** come from DefiLlama. Per DefiLlama's methodology (stored verbatim in the snapshot): *Fees* are gross
fees charged on NEAR Intents swaps; *Revenue* is NEAR's net captured revenue, measured as NEAR/wNEAR swept into its revenue wallets and, since 2026-02-23, used to
buy back NEAR on the open market (**not burned**). This repository does not verify those figures; it uses them exactly as published, drops the newest (partial)
day, and drops the first (partial) month of Intents data.

* Coverage in USD = revenue per day ÷ (gross issuance per second × 86,400 × the month's average NEAR price).
* The interval on that coverage reflects the **issuance estimate only**; revenue and price are taken as given.
* A rise in coverage is **decomposed** into revenue growth and a smaller USD issuance bill, because issuance halved inside the Intents window; one number would hide that.
* The calculator on the dashboard treats revenue as set in USD by swap activity, so a higher NEAR price makes issuance more expensive in USD. That is an
  assumption of the calculator, not a finding.

## 11. Breakpoints and the in-browser checker

**Breakpoints are detected, not asserted.** The month-to-month change with the largest |log ratio| between two *consecutive* sampled months is found for total
activity (separately for the largest rise and the largest fall) and for net issuance. The sparse 2022-2023 baseline months are never compared with each other. The
pair is chosen from the data, so "the intervals are disjoint" describes the step; it is not an independent test of it. Protocol v87 is marked at the first sampled
month containing a block with version ≥ 87.

**The live checker** (dashboard, "Verify it yourself") is a JavaScript port of `census/features.py` and `census/classify.py`. It scores an account from its latest 200
signed transactions as of now, omits the call-shape rule (which needs full transactions), and is **tested to match the Python output exactly** (score, class, the
rules that fired, and every numeric feature to 1e-9) on 30 real accounts: `tests/test_supply.py`, fixture `tests/fixtures/live_parity.json`. Its example chips include
one account the pipeline gets wrong, labelled as a known miss.

## 12. What would change the conclusion

See [THESIS.md](THESIS.md), "What would change my mind".

## 13. Reproducing

```bash
python -m census reproduce      # offline, from the committed sample: classify -> validate -> analyze -> thesis -> report -> dashboard
python -m census collect        # re-draw the sample from the live API (about 2-3 hours anonymous)
python -m census external       # refresh the third-party snapshot (DefiLlama: Intents revenue, NEAR price); explicit, never part of reproduce
python -m unittest discover -s tests
```

The block draw is seeded, so `collect` selects the same heights; transactions in those blocks are immutable, so
the sample reproduces exactly. Account histories are read "as of month end", so they are stable for past months.
