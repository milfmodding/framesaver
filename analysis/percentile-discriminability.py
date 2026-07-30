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

p75 IS IN THE LADDER BEFORE IT HAS EVER BEEN LOGGED. The gate moved to p75
primary on 2026-07-30 and the field ships in the next build, so this is written
against data that does not exist yet: a metric is not fit to gate on until it
has cleared this ratio, and nominating it first and checking afterwards is the
order that lets a flattering answer through. Every key reports the window count
behind it, so a run predating the field reads as a coverage gap rather than
silently scoring p75 over whichever handful of windows happened to carry it.
"""

import glob
import json
import os
import statistics
import sys

LOGDIR = "F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs"

# Below this many windows (or neighbour pairs) a key is reported, not scored.
MIN_N = 8


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

    keys = ("p50", "p75", "p95", "p99", "p999")
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
                # A key missing from either neighbour makes no pair at all,
                # rather than a difference of zero. Absent and unchanged are
                # different facts and only one of them is evidence of stability.
                if k in a["framePct"] and k in b["framePct"]:
                    noise[k].append(abs(b["framePct"][k] - a["framePct"][k]))

    n_pct = sum(1 for w in allw if w.get("framePct"))
    seen = {}
    hdr = (f"{'':6s} {'windows':>8s} {'pairs':>6s} {'corpus IQR':>11s} "
           f"{'neighbour IQR':>14s} {'discriminability':>17s}")
    print(hdr)
    print("-" * len(hdr))
    for k in keys:
        vals = [w["framePct"][k] for w in allw
                if w.get("framePct") and k in w["framePct"]]
        seen[k] = len(vals)
        # An IQR over a handful of values is arithmetic, not a spread. Refusing
        # to score is the honest output; a ratio computed from four windows
        # would be quoted like one computed from four hundred.
        if len(vals) < MIN_N or len(noise[k]) < MIN_N:
            print(f"{k:6s} {len(vals):8d} {len(noise[k]):6d} "
                  f"{'':11s} {'':14s} {'too few to score':>17s}")
            continue
        sig, noi = iqr(vals), iqr(noise[k])
        ratio = sig / noi if noi else float("inf")
        flag = "  <-- cannot separate" if ratio < 2 else ""
        print(f"{k:6s} {len(vals):8d} {len(noise[k]):6d} {sig:11.1f} "
              f"{noi:14.1f} {ratio:17.1f}{flag}")

    # Unscored has two causes and they are not the same problem. Absent from
    # every window means the build predates the field. Present but short of
    # pairs means it IS logged and never landed in two consecutive same-cfg
    # neighbours - a field that arrived mid-session, or a cfg edited every
    # window. Collapsing them would report a live instrument as a missing one.
    absent = [k for k in keys if seen[k] == 0]
    unpaired = [k for k in keys if seen[k] and len(noise[k]) < MIN_N]
    if absent:
        print(f"\n{n_pct} in-raid windows carry framePct; {', '.join(absent)} "
              f"absent from all of them.\nThe build predates the field: a "
              f"coverage gap, not a null result, and one raid clears it.")
    if unpaired:
        for k in unpaired:
            print(f"\n{k} is logged in {seen[k]} windows but forms only "
                  f"{len(noise[k])} same-cfg neighbour pairs.\nIt has a corpus "
                  f"spread and no noise floor to judge it against, so it is "
                  f"present\nand still unscorable - not the same as absent.")

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
