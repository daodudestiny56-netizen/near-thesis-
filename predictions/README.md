# Pre-registered predictions

Eight falsifiable expectations about NEAR on-chain activity in **December 2026**, written down *before* the data exist, so that a later reader can
tell what this census expected from what it merely explained afterwards.

| File | What it is |
|---|---|
| [`predictions.csv`](predictions.csv) | The eight predictions: statement, quantity, rule (operator and threshold), baseline at freeze time, which thesis claims they inform, and how to resolve them |
| [`predictions.csv.sha256`](predictions.csv.sha256) | SHA-256 of the CSV at freeze time: `bdd0c31262bf0ecfadea492e38ffe928675936a36801591e53fc88e738e4d5d8` |
| [`predictions.csv.ots`](predictions.csv.ots) | An [OpenTimestamps](https://opentimestamps.org) proof that the CSV existed no later than a Bitcoin block (see "Timestamp status") |

They are **model-based expectations about on-chain activity, not price forecasts**. Baselines in the CSV are read from this repository's committed
results at freeze time (2026-11-10); none is typed by hand. Some are deliberately uncertain (the Intents share and revenue series are volatile), and
a refuted prediction counts against the model as much as a confirmed one counts for it.

## Check that nothing changed since the freeze

```bash
python -m census predictions        # recomputes the SHA-256 and compares it with the frozen hash; refuses to continue if the file changed
sha256sum predictions/predictions.csv
git show predictions-frozen         # the annotated tag quotes the same hash and the date it was created
```

## Timestamp status

The `.ots` file was created by submitting the SHA-256 digest (plus a random nonce, never the file) to three public OpenTimestamps calendar servers
(`alice.btc`, `bob.btc`, `finney`). The proof has since been **upgraded and is confirmed in Bitcoin blocks 975308 and 975310**, both mined on 2026-11-10;
[`TIMESTAMP_STATUS.md`](TIMESTAMP_STATUS.md) records the details and the independent check against the block headers. To verify yourself:

* with the official client: `ots verify predictions/predictions.csv.ots` (it upgrades a pending proof automatically), or
* in a browser: drop `predictions.csv.ots` and `predictions.csv` on <https://opentimestamps.org>, or
* with this repository's helper if the official client will not start on your machine: `python tools/ots.py info predictions/predictions.csv.ots`.

## Resolve them (after 2026-12-31)

```bash
python -m census collect --first 2026-12 --last 2026-12   # draws the December block sample (seeded, so anyone gets the same blocks)
python -m census external                                  # refreshes the DefiLlama snapshot (Intents revenue, NEAR price)
python -m census reproduce && python -m census predictions
```

`python -m census predictions` prints each prediction as **confirmed**, **refuted** or **pending** against the new data and verifies the hash first.
A prediction whose data are missing stays *pending*; nothing is ever marked confirmed by default.
