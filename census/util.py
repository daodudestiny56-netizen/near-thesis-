"""Small shared helpers."""
from __future__ import annotations

import gzip
import io
import math

import numpy as np


def jsonable(o):
    """Recursively convert numpy scalars/arrays and NaN/inf into plain JSON-safe values (NaN -> null)."""
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, np.generic):
        return jsonable(o.item())
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


def top_value(s):
    """Most frequent value of a Series; ties go to the alphabetically first value.

    `value_counts()` orders ties differently across pandas versions, which once changed an output table between CI machines.
    """
    vc = s.value_counts()
    return sorted(vc[vc == vc.max()].index)[0]


def ranked(df, by: str, key: str, secondary: list[str] | None = None):
    """Sort a frame by `by` descending, then `secondary` descending, then the index/`key` ascending: a total order, so ties never depend on pandas."""
    cols = [by] + (secondary or [])
    out = df.reset_index().sort_values(cols + [key], ascending=[False] * len(cols) + [True], kind="mergesort")
    return out.set_index(key)


def write_csv_gz(df, path) -> None:
    """Write a DataFrame as a gzip CSV with a zeroed header timestamp, so re-runs are byte-identical."""
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz,             io.TextIOWrapper(gz, encoding="utf-8", newline="") as fh:
        df.to_csv(fh, index=False, lineterminator="\n")   # LF everywhere: the default is os.linesep, so Windows and Linux runs would differ
