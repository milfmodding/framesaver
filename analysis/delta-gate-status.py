"""Where do the marathon legs actually stand against the three current gates?

  1. p50 >= 60 fps on every map      (16.67 ms)
  2. no frame above ~250 ms in steady-state play
  3. p99 / p50 <= 2.0

Marathon logs only - one tag, one config, no protocol arms. The pooled corpus
figure for Streets is dragged down by the protocol runs, where the runner is
deliberately holding sightlines to maximise draw calls; those are experiment
arms, not gameplay, and must not be scored against a gameplay gate.
"""
import json
import glob
import sys
from collections import defaultdict

LOGS = sys.argv[1:] or sorted(glob.glob(r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/"
                        r"framesaver-20260728-*-marathon.ndjson"))
STEADY_S = 120.0

legs = defaultdict(list)
for path in LOGS:
    leg, prev, leg_start = 0, None, None
    for ln in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "sample":
            continue
        m = str(o.get("map") or "?")
        if m != prev:
            leg += 1
            prev = m
            leg_start = o.get("t")
        if o.get("state") != "raid":
            continue
        fp = o.get("framePct") or {}
        if not fp.get("p50") or not fp.get("p99"):
            continue
        # raidElapsed is EMITTED (read-marathon.py:139 reads it). Deriving it
        # from a leg start gave two different answers in two of my scripts and
        # neither matched the field. Do not reconstruct what is on the line.
        if (o.get("raidElapsed") or 0) < STEADY_S:
            continue
        # `final: true` is the truncated end-of-raid fragment every reader
        # excludes. Including it put Lighthouse at 54.6 fps against the true
        # 65.8 - a straddle of the release gate invented by one partial window.
        if o.get("final"):
            continue
        legs[(LOGS.index(path), leg, m)].append({
            "p50": fp["p50"], "p99": fp["p99"], "p999": fp.get("p999"),
            "max": (o.get("frame") or {}).get("max"),
        })


def median(xs):
    """True median. `s[len(s)//2]` silently returns the UPPER of two values at
    n=2, which is how a two-window map reported its worse window as its p50."""
    s = sorted(xs)
    if not s:
        return None
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2.0


print("marathon legs, steady state only (>= %.0f s into the leg)\n" % STEADY_S)
print("%-16s %3s  %8s %7s   %8s %9s  %8s" %
      ("map", "n", "p50 fps", "gate 1", "worst ms", "gate 2", "p99/p50"))
print("-" * 74)

fails = []
for k in sorted(legs):
    w = legs[k]
    if not w:
        continue
    p50 = median([x["p50"] for x in w])
    fps = 1000.0 / p50
    worst = max(x["max"] for x in w if x["max"] is not None)
    ratio = median([x["p99"] / x["p50"] for x in w])
    g1 = "MEETS" if fps >= 60 else "FAILS"
    g2 = "MEETS" if worst < 250 else "FAILS"
    g3 = "MEETS" if ratio <= 2.0 else "FAILS"
    if len(w) < 3:
        g1 = "n<3"
    print("%-16s %3d  %8.1f %7s   %8.1f %9s  %5.2f %s" %
          (k[2], len(w), fps, g1, worst, g2, ratio, g3))
    for name, verdict in (("1", g1), ("2", g2), ("3", g3)):
        if verdict == "FAILS":
            fails.append("%s leg%d gate %s" % (k[2], k[1], name))

print()
if fails:
    print("FAILURES: " + ", ".join(fails))
else:
    print("No gate failure on any steady-state marathon leg.")
print("\ngate 3 is computed per window then medianed - a scale-free shape")
print("constraint fails benign windows whose worst frame is 36 ms, so read it")
print("alongside 'worst ms' rather than on its own.")
