"""Is the Lighthouse rendering rise GPU-side or CPU-side?

FinishFrameRendering rose 0.52 ms between the two Lighthouse legs and - unlike every
other component - position standardisation explains NONE of it. Alpha has a candidate
(garment variety: more distinct 2048^2 diffuse maps resident) which would be a GPU-side
cost, and flagged it as untestable with current telemetry.

It is testable today. The session already has a PresentMon capture with CPUStartQPC,
and sample lines carry qpc, so the two join without a new field or a new raid.

  GPUBusy rose  -> a GPU-side mechanism is live; texture/material variety stays a candidate
  CPUBusy rose  -> the rise is CPU-side submission and garment variety is OUT, because
                   more distinct textures is not a CPU cost

This does not confirm garments either way - it decides whether the mechanism CLASS is
possible before anyone spends a telemetry field on it.
"""
import csv
import json
import sys
from collections import defaultdict

NDJSON = r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-20260728-225956-marathon.ndjson"
CSV = r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-20260728-225956-marathon.presentmon.csv"
MAP = "Lighthouse"

leg, prev, prevqpc = 0, None, None
windows = []
for ln in open(NDJSON, encoding="utf-8", errors="replace"):
    try:
        o = json.loads(ln)
    except ValueError:
        continue
    if o.get("type") != "sample":
        continue
    m = str(o.get("map"))
    if m != prev:
        prev, leg = m, leg + 1
    q = o.get("qpc")
    if (o.get("state") == "raid" and m == MAP and not o.get("final")
            and (o.get("raidElapsed") or 0) >= 120 and q and prevqpc):
        windows.append({"leg": leg, "lo": prevqpc, "hi": q})
    if q:
        prevqpc = q

if not windows:
    print("no windows")
    sys.exit(1)

lo = min(w["lo"] for w in windows)
hi = max(w["hi"] for w in windows)
bounds = sorted(windows, key=lambda w: w["lo"])

FIELDS = ("FrameTime", "CPUBusy", "CPUWait", "GPUTime", "GPUBusy", "GPUWait", "DisplayLatency")
acc = defaultdict(lambda: defaultdict(list))

with open(CSV, newline="", encoding="utf-8", errors="replace") as f:
    for row in csv.DictReader(f):
        try:
            q = int(row["CPUStartQPC"])
        except (ValueError, TypeError, KeyError):
            continue
        if q < lo or q > hi:
            continue
        # windows are contiguous and non-overlapping; linear scan is fine at this size
        for w in bounds:
            if w["lo"] < q <= w["hi"]:
                for fld in FIELDS:
                    try:
                        acc[w["leg"]][fld].append(float(row[fld]))
                    except (ValueError, TypeError, KeyError):
                        pass
                break


def med(xs):
    s = sorted(xs)
    n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


ks = sorted(acc)
if len(ks) < 2:
    print("only %d leg(s) joined - cannot compare" % len(ks))
    sys.exit(1)

A, B = acc[ks[0]], acc[ks[-1]]
print("%s leg%d vs leg%d, PresentMon frames joined on qpc: %d and %d\n"
      % (MAP, ks[0], ks[-1], len(A["FrameTime"]), len(B["FrameTime"])))
print("  %-16s %10s %10s %10s %8s" % ("", "leg A", "leg B", "delta", "%"))
for fld in FIELDS:
    a, b = med(A[fld]), med(B[fld])
    print("  %-16s %10.3f %10.3f %10.3f %7.0f%%"
          % (fld, a, b, b - a, 100.0 * (b - a) / a if a else 0))

print("\n  READ: FinishFrameRendering rose 0.518 ms across these legs.")
print("  A GPU-side rise supports the texture/material class. A CPU-side rise rules it out.")
