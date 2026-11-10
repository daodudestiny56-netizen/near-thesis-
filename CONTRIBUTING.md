# Contributing

The census is meant to be extended and *checked*. The one rule that matters: **no number in the dashboard, `THESIS.md`, `RESULTS.md` or the README headline
may be typed by hand.** Every figure comes from `data/derived/` through code, so it is re-decided when the data change.

## Run it

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v        # offline; the browser-parity test is skipped without Chrome/Edge + playwright
python -m census reproduce                      # classify -> validate -> analyze -> thesis -> report -> dashboard, from the committed data
python -m http.server 8000 --directory docs     # open http://localhost:8000
```

CI (`.github/workflows/ci.yml`) runs the same on Ubuntu with Python 3.10 (oldest numpy/pandas the requirements allow) and 3.12, and fails if
`RESULTS.md` or `THESIS.md` change after `reproduce`.

## Where things go

| To change | Edit | Then |
|---|---|---|
| A classifier rule | `census/classify.py` (`RULES`) **and** the matching test in `dashboard_template.html` (`RULE_TESTS`) | `python -m unittest` (the browser-parity test fails if the two disagree) |
| A new measured quantity | `analyze.py` / `insights.py` / `supply.py`, then surface it in `report.py` and `dashboard_template.html` | add a test with synthetic data of known answer |
| A thesis claim | `thesis.py` or `thesis_value.py` (a claim is a statement plus a verdict decided from an interval) | `python -m census thesis` |
| Validation labels | `census/labels.py`; record removals in the generated `data/labels/review_notes.md` | tune on the **dev** split only (`python -m census validate --dev-only`) |
| The sample | `census/config.py`, then `python -m census collect` (hours anonymously; a free FastNEAR key in `.env` speeds it up) | re-run `reproduce` |

## Conventions

* **Rankings must be total orders.** Break ties explicitly (`util.ranked`, `util.top_value`); an arbitrary tie-break once changed an output between pandas versions.
* **Report limits next to results.** A finding that cannot be computed, or that depends on a third-party series, says so where it appears.
* **Pre-registered predictions are frozen.** `predictions/predictions.csv` is never edited; a new set means a new directory and a new timestamp.
* **Third-party data are snapshots.** `python -m census external` refreshes `data/external/`; it is deliberately not part of `reproduce`.
