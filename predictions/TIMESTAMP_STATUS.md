# Timestamp status

| | |
|---|---|
| Frozen on | 2026-11-10 |
| SHA-256 of `predictions.csv` | `bdd0c31262bf0ecfadea492e38ffe928675936a36801591e53fc88e738e4d5d8` |
| Submitted to calendars | `alice.btc.calendar.opentimestamps.org`, `bob.btc.calendar.opentimestamps.org`, `finney.calendar.eternitywall.com` (all three accepted) |
| Bitcoin confirmation | **confirmed** in blocks **975308** (mined 2026-11-10 14:41:27 UTC) and **975310** (mined 2026-11-10 14:54:47 UTC) |

Checked independently of the helper: the proof's file digest equals the SHA-256 of `predictions.csv`, and for both blocks the commitment in the proof
equals the block's merkle root as served by <https://blockstream.info/api>. Reproduce the check with `python tools/ots.py info predictions/predictions.csv.ots`,
the official `ots verify predictions/predictions.csv.ots`, or by dropping both files on <https://opentimestamps.org>.
