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

* **Periods.** Every calendar month from `DENSE_FROM` (2024-01) to today, plus one month per quarter
  (January, April, July, October) from 2021 as a long baseline. Constants live in
  [census/config.py](census/config.py).
* **Blocks.** For each month, 45 block heights are drawn uniformly at random from that month's height range,
  with a fixed seed, so a re-run draws the same blocks. Skipped heights are dropped.
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
  infrastructure. Every candidate was reviewed by a person; removals and their reasons are recorded in
  [data/labels/review_notes.md](data/labels/review_notes.md).
* **Split.** Half the labels are a **held-out test split** chosen by a hash of the account id, so the split
  cannot be cherry-picked. Rule weights were set while looking at the **dev** split only. Headline accuracy is
  **test only**.
* **Reported.** Coverage (how often we abstain), per-class recall with Wilson 95% intervals, precision, balanced
  accuracy, ROC AUC of the raw score, a threshold sweep, and a leave-one-rule-out ablation.

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

## 9. Trend extrapolation

The dashboard fits a line to the logit of the monthly automated share over the last 24 months and projects 12
months ahead, once per bootstrap replicate, so the band reflects **sampling uncertainty only**. It excludes model
risk and regime change and is not a prediction. It exists so a reader can see how much a trend line is worth
given this much noise, which is usually less than the line suggests.

## 10. What would change the conclusion

See [THESIS.md](THESIS.md), "What would change my mind".

## 11. Reproducing

```bash
python -m census reproduce      # offline, from the committed sample: classify -> validate -> analyze -> dashboard
python -m census collect        # re-draw the sample from the live API (about 2-3 hours anonymous)
python -m unittest discover -s tests
```

The block draw is seeded, so `collect` selects the same heights; transactions in those blocks are immutable, so
the sample reproduces exactly. Account histories are read "as of month end", so they are stable for past months.
