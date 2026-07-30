#!/usr/bin/env python3
"""Bound corpse dilution of updateManual ms/call from the existing logs.

Beta's trace: BotsClass.UpdateByUnity walks its set with no liveness test, the
guard is inside UpdateManual, and a corpse keeps StandByType active -- so dead
bots COULD be called and stamped into awakeMs/awakeCalls at near-zero cost,
diluting ms/call. With 14 corpses vs 1 awake late in raid 1.5, full dilution
would be ~15x -- quantitatively sufficient for the whole 6-10x level gap that
the awake-age resolution currently owns.

The trace establishes the path exists. It does not establish the population is
nonempty: if SPT removes dead bots from the walked set quickly, corpse calls
are transient. The logs decide this by an IDENTITY, not an argument:

    awakeCalls / frames  ==  bots.awake         (if no corpse calls)
    awakeCalls / frames  ==  bots.awake + D     (if D corpses are called)

pausedCalls/frames vs bots.asleep is the control identity (corpses are never
paused, so it should hold exactly regardless), and unstampedCalls catches any
corpse call that failed before the stamp. Counts at window granularity include
mid-window transitions (a bot awake half the window contributes 0.5), so the
test is excess-vs-zero SUSTAINED across windows, with death windows expected
to show transient excess from the legitimate pre-death fraction.

Known weaknesses:
  - Window-level counts cannot see a corpse that is called for less than the
    removal latency if that latency is a few frames; the bound covers what a
    window can see, stated as such.
  - bots.awake is sampled at window END; a bot that slept mid-window creates
    excess that is not a corpse. Direction: inflates the apparent excess, so
    the bound is conservative (an overestimate of dilution).
"""

import json
import math
import os
import statistics as st

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
RAIDS = (
    ("raid1", "framesaver-20260729-185430-raid1-lighthouse.ndjson"),
    ("raid1.5", "framesaver-20260729-215652-raid15-forceallroles.ndjson"),
)


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0 + 1
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


for name, fn in RAIDS:
    S, D = [], []
    for line in open(os.path.join(LOGDIR, fn), encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        if o["type"] == "sample" and o["state"] == "raid" and o["agents"]["live"] > 0:
            S.append(o)
        elif o["type"] == "death":
            D.append(o)

    print("=== %s" % name)
    print("   w  awake  aCalls/fr  excess | asleep  pCalls/fr  excess | unst/fr  dthW  cumD  pend")
    rows = []
    for o in S:
        u = o["updateManual"]
        fr = o["frames"]
        aw, sl = o["bots"]["awake"], o["bots"]["asleep"]
        acf = u["awakeCalls"] / fr
        pcf = u["pausedCalls"] / fr
        ucf = u.get("unstampedCalls", 0) / fr
        dw = sum(1 for d in D if d.get("raidElapsed") and o["t"] - 60 < d["raidElapsed"] <= o["t"])
        cum = sum(1 for d in D if d.get("raidElapsed") and d["raidElapsed"] <= o["t"])
        rows.append({"w": o["window"], "exA": acf - aw, "exP": pcf - sl, "u": ucf,
                     "dw": dw, "cum": cum})
        print("  %2d  %4d  %8.2f  %+6.2f  | %4d  %9.2f  %+6.2f  | %6.3f  %3d  %3d  %4d"
              % (o["window"], aw, acf, acf - aw, sl, pcf, pcf - sl, ucf, dw, cum,
                 o["agents"]["pendingRemoval"]))

    calm = [r for r in rows if r["dw"] == 0]
    death = [r for r in rows if r["dw"] > 0]
    print("  awake-side excess: death windows med %+0.2f (n=%d), calm windows med %+0.2f (n=%d)"
          % (st.median([r["exA"] for r in death]) if death else float("nan"), len(death),
             st.median([r["exA"] for r in calm]) if calm else float("nan"), len(calm)))
    print("  calm-window excess vs CUMULATIVE corpses: rho %+0.3f  (dilution predicts ~ +1 per corpse)"
          % spearman([r["cum"] for r in calm], [r["exA"] for r in calm]))
    print("  max sustained (calm) excess %+0.2f against a corpse population of %d-%d"
          % (max(r["exA"] for r in calm), min(r["cum"] for r in calm), max(r["cum"] for r in calm)))
    print("  unstamped calls/frame: max %.3f" % max(r["u"] for r in rows))
    print()
