"""Population headroom per map, BRACKETED.

Delta's headroom table (+2 Lighthouse, +37 Woods, ...) uses a single slope of
0.146 ms/bot, which is `frame ~ total` - and that is the weakest fit in the whole
corpus: its CI excludes zero in 2 of 10 legs at median R2 0.07. A precise-looking
table on top of a fit that cannot reject "no relationship" is the interval-narrower-
than-its-evidence shape, which is the error Delta caught in Alpha yesterday.

The bracket is not sampling error, it is the ESTIMAND: what an added bot costs
depends on whether it is awake.

  0.146 ms/bot   frame ~ total   - added bots mostly asleep, the roster-size reading
  0.278 ms/bot   sum of the four bot-driven phase slopes on awake (Delta)
  0.370 ms/bot   frame ~ awake   - confounded upward by player proximity

Reported for every leg so the reader can see which conclusions are slope-driven
and which are baseline-driven. The ORDERING is baseline-driven and survives the
bracket; the magnitudes do not.
"""
import json
import glob
import os
import sys
from collections import defaultdict

LOGS = sys.argv[1:] or sorted(glob.glob(
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson"))
STEADY = 120.0
GATE_MS = 1000.0 / 60.0
SLOPES = (("total", 0.146), ("awake-components", 0.278), ("awake-frame", 0.370))

rows = []
for path in LOGS:
    stem = os.path.basename(path).split("-marathon")[0].replace("framesaver-", "")
    leg, prev = 0, None
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for ln in fh:
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            if o.get("type") != "sample" or o.get("state") != "raid":
                continue
            m = str(o.get("map") or "?")
            if m != prev:
                prev, leg = m, leg + 1
            if o.get("final") or (o.get("raidElapsed") or 0) < STEADY:
                continue
            b = o.get("bots") or {}
            # The gate is p50, so the headroom comparison must use framePct.p50 - NOT
            # frame.avg, which is what the slope fits use. Mixing them would compare a
            # mean-derived level against a median-defined gate. Both carried so the
            # difference is visible rather than assumed away.
            pct = o.get("framePct") or {}
            p50 = pct.get("p50")
            if p50 is None:
                continue
            rows.append({"leg": "%s %s L%d" % (stem, m, leg),
                         "frame": p50,
                         "avg": (o.get("frame") or {}).get("avg") or 0.0,
                         "awake": b.get("awake") or 0, "total": b.get("total") or 0})

if not rows:
    print("NO ROWS - refusing to report.")
    sys.exit(2)


def med(v):
    s = sorted(v)
    return s[len(s) // 2] if s else float("nan")


by = defaultdict(list)
for r in rows:
    by[r["leg"]].append(r)

print("headroom to p50 >= 60 fps (%.2f ms), steady state, per leg\n" % GATE_MS)
print("%-30s %3s %6s %6s %8s %7s %7s   %s"
      % ("leg", "n", "awake", "total", "p50 ms", "p50 fps", "avg fps",
         "bots addable at 0.146 / 0.278 / 0.370"))
print("-" * 126)
for leg in sorted(by, key=lambda k: -med([r["frame"] for r in by[k]])):
    v = by[leg]
    lvl = med([r["frame"] for r in v])
    slack = GATE_MS - lvl
    cells = []
    for _, s in SLOPES:
        cells.append("over" if slack <= 0 else "%d" % int(slack / s))
    print("%-30s %3d %6d %6d %8.2f %7.1f %7.1f   %s"
          % (leg, len(v), med([r["awake"] for r in v]), med([r["total"] for r in v]),
             lvl, 1000.0 / lvl, 1000.0 / med([r["avg"] for r in v]),
             " / ".join("%-4s" % c for c in cells)))

print("\ncorpus-wide steady-state medians: awake %d, total %d, p50 %.2f ms (%.1f fps), n %d"
      % (med([r["awake"] for r in rows]), med([r["total"] for r in rows]),
         med([r["frame"] for r in rows]), 1000.0 / med([r["frame"] for r in rows]), len(rows)))

print("\nwhat 1.25 ms of PERFECT recovery (both levers) buys, at each slope")
for name, s in SLOPES:
    print("  %-18s %5.2f extra bots" % (name, 1.25 / s))
print("\n  For scale: recovering both levers perfectly is worth fewer added bots than")
print("  the gap between the best and worst leg of a single evening on ONE map.")
