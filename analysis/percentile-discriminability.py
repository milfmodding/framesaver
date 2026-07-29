#!/usr/bin/env python3
"""Does each percentile DISCRIMINATE, or is its spread just its own noise?

Stability alone cannot pick a metric. A constant is perfectly stable and useless.
The quantity that matters is the ratio

    spread across all conditions  /  spread between identical-cfg neighbours

which is the same shape as the self-calibrating floor: the instrument's own noise
sets the smallest difference it can honestly report. Below ~2 the metric cannot
separate a real change from the next window along.

Reported alongside is what p99 MEANS as a count, because "p99 = 27.4 ms" and
"1% of frames exceeded 27.4 ms" are the same statement read along two axes, and
only one of them is well conditioned.
"""

import glob
import json
import os
import statistics
import sys

LOGDIR = "F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs"


def load_windows(path):
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "sample" and d.get("state") == "raid":
                out.append(d)
    return out


def iqr(vals):
    s = sorted(vals)
    return s[int(0.75 * len(s)) - 1] - s[int(0.25 * len(s)) - 1]


def main():
    paths = sorted(glob.glob(os.path.join(LOGDIR, "*.ndjson")))
    per_log = {p: load_windows(p) for p in paths}
    allw = [w for ws in per_log.values() for w in ws]
    print(f"{len(paths)} logs, {len(allw)} in-raid windows\n")

    keys = ("p50", "p95", "p99", "p999")
    noise = {k: [] for k in keys}
    for ws in per_log.values():
        for a, b in zip(ws, ws[1:]):
            if b.get("window") != a.get("window", -99) + 1:
                continue
            if a.get("cfg") != b.get("cfg") or a.get("final") or b.get("final"):
                continue
            if not a.get("framePct") or not b.get("framePct"):
                continue
            for k in keys:
                noise[k].append(abs(b["framePct"][k] - a["framePct"][k]))

    hdr = (f"{'':6s} {'corpus IQR':>11s} {'neighbour IQR':>14s} "
           f"{'discriminability':>17s}")
    print(hdr)
    print("-" * len(hdr))
    for k in keys:
        vals = [w["framePct"][k] for w in allw if w.get("framePct")]
        sig, noi = iqr(vals), iqr(noise[k])
        ratio = sig / noi if noi else float("inf")
        flag = "  <-- cannot separate" if ratio < 2 else ""
        print(f"{k:6s} {sig:11.1f} {noi:14.1f} {ratio:17.1f}{flag}")

    # The count reading of the same ladder. A window of n frames has, by
    # construction, n/100 frames at or above p99 and n/1000 at or above p999 --
    # so the "sample size" behind each is fixed and tiny at the deep end.
    ns = [w["n"] for w in allw if w.get("n")]
    med_n = statistics.median(ns)
    print(f"\nmedian window: {med_n:.0f} frames")
    for k, frac in (("p95", 0.05), ("p99", 0.01), ("p999", 0.001)):
        print(f"  {k:5s} is the {med_n * frac:6.1f}th worst frame "
              f"-> counting sqrt(n) noise alone is "
              f"{100.0 / (med_n * frac) ** 0.5:5.1f}% of the count")

    return 0


if __name__ == "__main__":
    sys.exit(main())
