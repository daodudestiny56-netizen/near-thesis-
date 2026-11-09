"""Single place for every tunable constant, so the methodology in METHODOLOGY.md maps to code 1:1."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DERIVED = ROOT / "data" / "derived"
LABELS = ROOT / "data" / "labels"
DOCS = ROOT / "docs"

# --- sampling -------------------------------------------------------------------------------
FIRST_PERIOD = "2021-01"          # first calendar month sampled
DENSE_FROM = "2024-01"            # every month from here on...
SPARSE_STRIDE = 3                 # ...and one month per quarter (Jan/Apr/Jul/Oct) before it, as a long baseline
BLOCKS_PER_PERIOD = 45            # uniformly random blocks drawn per calendar month
SEED = 20261101                   # fixed so a re-run draws the identical blocks
MAX_TX_PER_PERIOD = 160           # uniform random subsample of each month's sampled-block transactions (equal inclusion
                                  # probability, so ratio estimates stay unbiased; bounds API calls in busy months)
HISTORY_LIMIT = 200               # most recent signed transactions pulled per account (API max)
FULL_TX_PER_SIGNER = 3            # sample transactions per signer fetched in full (call shape)
FULL_TX_PER_PERIOD_CAP = 600      # ceiling on full-tx lookups per month to bound API calls

# --- classifier (see METHODOLOGY.md) ------------------------------------------------------------
MIN_OBS = 8                       # fewer observed signed txs than this => "low-activity", not classified
AUTOMATED_THRESHOLD = 50          # automation score (0-100) at or above which an account is "automated"
REST_GAP_SECONDS = 5 * 3600       # a silent stretch this long counts as "rest" (humans sleep, bots don't)
FAST_GAP_SECONDS = 5              # consecutive txs closer than this are machine-speed
PERIODIC_TOLERANCE = 0.10         # +-10% of the median gap counts as "on schedule"

# --- intents --------------------------------------------------------------------------------------
INTENTS_CONTRACT = "intents.near"

# --- analysis ---------------------------------------------------------------------------------------
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 7
