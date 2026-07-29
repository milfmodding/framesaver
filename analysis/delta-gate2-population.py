"""Does gate 2 turn on WHICH QUANTITY, or on the 120-second warm-up discard?

I claimed the quantity: frame.max says Streets-only, period says every map.
Alpha says that mixed populations - a steady-state frame.max against an
all-windows period - and that the real cutter is the warm-up discard.

This checks both without assuming either. Per map, the worst frame.max and the
worst spike period, computed over the SAME window set each time.

Spike lines precede their window's sample line, so they are buffered and
flushed when the sample arrives. `raidElapsed` is measured from the first raid
window of each leg, which is what a 120 s steady-state cutoff means.
"""
import json
import glob
import sys
from collections import defaultdict

LOGS = sys.argv[1:] or sorted(glob.glob(
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson"))
GATE = 250.0
STEADY = 120.0

rows = []
for path in LOGS:
    pending, leg_start, prev = [], None, None
    for ln in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        t = o.get("type")
        if t == "spike":
            pending.append(o.get("period") or 0.0)
            continue
        if t != "sample":
            continue
        m = str(o.get("map") or "?")
        if m != prev:
            prev, leg_start = m, None
        if o.get("state") == "raid" and not o.get("final"):
            rows.append({
                "map": m,
                # EMITTED, not derived. See delta-gate-status.py for what
                # deriving it cost. `final` fragments excluded above.
                "elapsed": o.get("raidElapsed") or 0.0,
                "fmax": (o.get("frame") or {}).get("max") or 0.0,
                "pmax": max(pending) if pending else 0.0,
            })
        pending = []


def table(sel, label):
    by = defaultdict(list)
    for r in rows:
        if sel(r):
            by[r["map"]].append(r)
    f_fail = [m for m in by if max(r["fmax"] for r in by[m]) >= GATE]
    p_fail = [m for m in by if max(r["pmax"] for r in by[m]) >= GATE]
    print("\n%s  (n=%d windows, %d maps)" % (label, sum(len(v) for v in by.values()), len(by)))
    print("  %-16s %10s %10s" % ("map", "frame.max", "period.max"))
    for m in sorted(by, key=lambda k: -max(r["fmax"] for r in by[k])):
        v = by[m]
        print("  %-16s %10.1f %10.1f  %s" %
              (m, max(r["fmax"] for r in v), max(r["pmax"] for r in v),
               "FAILS" if max(r["fmax"] for r in v) >= GATE
               or max(r["pmax"] for r in v) >= GATE else ""))
    print("  maps failing on frame.max : %d of %d  %s" % (len(f_fail), len(by), sorted(f_fail)))
    print("  maps failing on period    : %d of %d  %s" % (len(p_fail), len(by), sorted(p_fail)))


table(lambda r: True, "ALL in-raid windows")
table(lambda r: r["elapsed"] >= STEADY, "STEADY STATE only (raidElapsed >= 120 s)")

dis = [r for r in rows if r["pmax"] >= GATE and r["fmax"] < GATE]
print("\nwindows where period >= %.0f but frame.max < %.0f: %d" % (GATE, GATE, len(dis)))
for r in sorted(dis, key=lambda r: -r["pmax"]):
    print("  %-16s elapsed %6.0f s  frame.max %7.1f  period %7.1f"
          % (r["map"], r["elapsed"], r["fmax"], r["pmax"]))

hidden = [r for r in rows if r["elapsed"] < STEADY and max(r["fmax"], r["pmax"]) >= GATE]
print("\nwindows the 120 s discard removes that carry a >= %.0f ms event: %d"
      % (GATE, len(hidden)))
seen = defaultdict(float)
for r in hidden:
    seen[r["map"]] = max(seen[r["map"]], max(r["fmax"], r["pmax"]))
for m in sorted(seen, key=lambda k: -seen[k]):
    print("  %-16s worst discarded event %8.1f ms" % (m, seen[m]))
