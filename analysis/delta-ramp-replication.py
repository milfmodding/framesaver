#!/usr/bin/env python3
"""The raid-1 UpdateManual ramp: does it replicate in raid 1.5, and does it track
corpse count?

Raid 1's awake ms/call rose 0.0338 -> 0.1018 monotonically at constant awake
count -- the largest unexplained effect on the board (Alpha, 2026-07-29, after
withdrawing the GClass479 candidate). Candidate tested here: accumulating
registry scans (corpses/loot grow monotonically with deaths; LootingBots is
installed in both raids), which predicts ms/call tracks CUMULATIVE DEATHS and
should replicate in raid 1.5, which has MORE deaths (14 vs 11) over a raid
three times longer.

Result: raid 1.5 does not ramp. ms/call sits flat at 0.010-0.017 for 33
minutes, 19 of those windows at constant cumulative deaths with only wobble
(rho(t) +0.50 over a 0.007 amplitude vs raid 1's 0.075 rise). The corpse
hypothesis is dead, and the discriminating difference between the raids is the
STRUCTURE of the awake population:

  raid 1    ~10 exemption-role bots awake CONTINUOUSLY, the same individuals
            for the whole raid, ramping 3x
  raid 1.5  awake ~1-4 TRANSIENTS that wake near the player and sleep again,
            flat at a level 3-7x below raid 1's

Reading: per-bot UpdateManual cost grows with CONTINUOUS TIME AWAKE (or with
accumulated engagement -- the two are confounded within raid 1, since its
permanently-awake bots were also the ones fighting). Sleeping resets or
prevents the accumulation. Whatever accumulates lives per-bot: enemy memory,
cover sets, or a SAIN/BigBrain layer's state -- both raids carry the same mod
set, so the mods are not excluded as the owner of the growth.

Consequences if the awake-age reading holds:
  - The corpus per-bot slope (~0.37) was fitted on populations dominated by
    permanently-awake exemption bots deep into raids -- the RAMPED rate. Raid
    1.5's 0.22-0.25 measured fresh transients. Both are right; per-bot cost is
    a function of awake-age, and quoting either without its age is the same
    margin error as fight-vs-distant.
  - Role-aware 350 m keeps its bots awake PERMANENTLY, so it pays the ramped
    end-state rate, not the fresh rate. Its price rises with raid length.
  - The stand-by system's benefit is not only the sleeping bots' per-frame
    cost; recycling bots through sleep caps the ramp. That benefit is invisible
    to every per-frame per-bot instrument we own and appears only in ms/call
    trajectories.

Discriminating instrument for raid 2+ (ask Beta): per-bot continuous-awake age
(seconds since last un-pause) and per-bot UpdateManual ms, bucketed by age.
Age-vs-engagement separates the two candidate owners; per-bot rather than
pooled separates one old bot from many young ones.

Known weaknesses:
  - Two raids, one map. Raid 1's ramp could still be content (an escalating
    fight) rather than age; raid 1.5's flat could be idleness. The awake-age
    counter decides.
  - Raid 1's per-call LEVEL starts 2.4x above raid 1.5's (0.034 vs 0.014),
    so role composition (rogues vs scavs) affects the level independently of
    any ramp.
"""

import json
import math
import os
import statistics as st
from collections import Counter
from itertools import groupby

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
RAIDS = (
    ("raid1", "framesaver-20260729-185430-raid1-lighthouse.ndjson"),
    ("raid1.5", "framesaver-20260729-215652-raid15-forceallroles.ndjson"),
)


def rows(fn):
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
    out = []
    for o in S:
        u = o["updateManual"]
        if not u["awakeCalls"]:
            continue
        cum = sum(1 for d in D if d.get("raidElapsed") and d["raidElapsed"] <= o["t"])
        out.append((o["window"], o["t"], o["bots"]["awake"], cum, u["awakeMs"] / u["awakeCalls"]))
    return out


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
    R = rows(fn)
    print("=== %s" % name)
    print("   w    t   awake cumDeaths  ms/call")
    for w, t, a, c, m in R:
        print("  %2d %6.0f %4d %6d %11.4f" % (w, t, a, c, m))
    print("  all windows: ms/call ~ cumDeaths rho %+0.3f   ms/call ~ t rho %+0.3f"
          % (spearman([c for _, _, _, c, _ in R], [m for *_, m in R]),
             spearman([t for _, t, _, _, _ in R], [m for *_, m in R])))
    common = Counter(a for _, _, a, _, _ in R).most_common(1)[0][0]
    C = [(t, c, m) for _, t, a, c, m in R if a == common]
    if len(C) >= 5:
        print("  awake==%d stratum (n=%d): ~cumDeaths rho %+0.3f   ~t rho %+0.3f"
              % (common, len(C), spearman([c for _, c, _ in C], [m for _, _, m in C]),
                 spearman([t for t, _, _ in C], [m for _, _, m in C])))
        print("  constant-cumDeaths plateaus (deaths flat, time moving):")
        for c, grp in groupby(C, key=lambda x: x[1]):
            g = list(grp)
            if len(g) >= 4:
                print("    cum=%d n=%d  ms/call %.4f -> %.4f  rho(t) %+0.3f"
                      % (c, len(g), g[0][2], g[-1][2],
                         spearman([t for t, _, _ in g], [m for _, _, m in g])))
    print()
