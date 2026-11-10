"""Minimal OpenTimestamps helper (stamp / upgrade / info) built on the `opentimestamps` library, for machines where the official `ots`
command-line tool cannot start (it needs a working OpenSSL binding; it fails on some Windows / Python 3.14 setups).

    python tools/ots.py stamp   predictions/predictions.csv     -> predictions/predictions.csv.ots   (pending until a Bitcoin block confirms)
    python tools/ots.py upgrade predictions/predictions.csv.ots                                      (run again hours later; fills in the Bitcoin block)
    python tools/ots.py info    predictions/predictions.csv.ots

Only the SHA-256 digest (plus a random nonce) is sent to the public calendar servers, never the file. The resulting .ots file is the standard
format: verify it with the official client (`ots verify FILE.ots`) or by dropping both files on https://opentimestamps.org.
Needs: pip install opentimestamps
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from opentimestamps.calendar import RemoteCalendar
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpAppend, OpSHA256
from opentimestamps.core.serialize import BytesDeserializationContext, StreamSerializationContext, BytesSerializationContext
from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

CALENDARS = ["https://alice.btc.calendar.opentimestamps.org", "https://bob.btc.calendar.opentimestamps.org",
             "https://finney.calendar.eternitywall.com"]


def stamp(path: Path) -> Path:
    with open(path, "rb") as fd:
        detached = DetachedTimestampFile.from_fd(OpSHA256(), fd)
    nonce_stamp = detached.timestamp.ops.add(OpAppend(os.urandom(16)))      # a random nonce keeps the submitted digest unlinkable to the file
    tip = nonce_stamp.ops.add(OpSHA256())
    ok = 0
    for url in CALENDARS:
        try:
            tip.merge(RemoteCalendar(url).submit(tip.msg, timeout=30))
            ok += 1
            print(f"  accepted by {url}")
        except Exception as e:
            print(f"  {url}: {type(e).__name__} {str(e)[:80]}")
    if not ok:
        raise SystemExit("no calendar accepted the digest")
    out = Path(str(path) + ".ots")
    with open(out, "wb") as fd:
        detached.serialize(StreamSerializationContext(fd))
    print(f"wrote {out} (sha256 of the file: {hashlib.sha256(Path(path).read_bytes()).hexdigest()})")
    return out


def _load(ots: Path) -> DetachedTimestampFile:
    return DetachedTimestampFile.deserialize(BytesDeserializationContext(Path(ots).read_bytes()))


def upgrade(ots: Path) -> None:
    detached = _load(ots)
    changed = 0
    def walk(ts: Timestamp):
        nonlocal changed
        for att in list(ts.attestations):
            if isinstance(att, PendingAttestation):
                try:
                    upgraded = RemoteCalendar(att.uri).get_timestamp(ts.msg, timeout=30)
                except Exception as e:                 # not yet confirmed in a Bitcoin block
                    print(f"  still pending at {att.uri}: {type(e).__name__}")
                    continue
                ts.merge(upgraded)
                changed += 1
        for _, child in list(ts.ops.items()):
            walk(child)
    walk(detached.timestamp)
    with open(ots, "wb") as fd:
        detached.serialize(StreamSerializationContext(fd))
    print(f"upgraded {changed} attestation(s)")
    info(ots)


def info(ots: Path) -> None:
    detached = _load(ots)
    print("file digest (sha256):", detached.file_digest.hex())
    btc = [(msg.hex()[:16], att.height) for msg, att in detached.timestamp.all_attestations() if isinstance(att, BitcoinBlockHeaderAttestation)]
    pend = [att.uri for _, att in detached.timestamp.all_attestations() if isinstance(att, PendingAttestation)]
    print("Bitcoin block attestations:", [h for _, h in btc] or "none yet")
    print("pending calendar attestations:", pend or "none")


if __name__ == "__main__":
    cmd, target = (sys.argv[1], Path(sys.argv[2])) if len(sys.argv) == 3 else (None, None)
    {"stamp": stamp, "upgrade": upgrade, "info": info}.get(cmd, lambda _: sys.exit(__doc__))(target)
