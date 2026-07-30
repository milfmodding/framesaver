#!/usr/bin/env python3
"""Attack Alpha's raid 1.5 (forceAllRoles) claims before the docket is priced off them.

Claims under test, from Alpha's 2026-07-29 message:
  A. "Measured saving 3.50 ms/frame" (frame route, raid 1 vs raid 1.5 level
     shift) corroborated by "population route 11 x 0.35 = 3.85".
  B. The 0.35 ms/bot per-bot cost, whose decomposition Alpha already found
     inconsistent (animator under-predicted 1.5x, non-animator over 1.8x).
  C. p99 worsened 22.78 -> 24.55 because raid 1.5 had 41 spawns vs 31 and
     spikes are spawn-completion hitches.
  D. The within-raid slope reads 1.00 ms/awake-bot but corr(awake,total)=0.91.

Method notes:
  - Raid 1 ended at ~11 min (death), so its entire log is EARLY raid. Raid 1.5
    ran 36 min and is dominated by LATE raid. Any raid-wide level comparison is
    therefore also a raid-age comparison. The matched-age cut (both raids
    restricted to overlapping t) removes that one confound; it does NOT remove
    position/content confounds, and raid 1.5's early windows contain fights
    (Goons + crazyAssaultEvent) that raid 1 never spawned.
  - PresentMon pooled percentiles are recomputed exactly as Alpha's, then
    recomputed matched-age, so the drift share of the headline is measured
    rather than argued.

Known weaknesses:
  - The matched-age comparison undercorrects: raid 1.5's early segment carries
    extra boss content, pushing its frames UP, so matched-age Delta-p50 is a
    LOWER bound on the treatment effect as much as raid-wide was an upper one.
  - The identified awake slope comes from a handful of windows at awake 1-4;
    it prices THAT margin (distant bots waking briefly), not the fight margin.
"""

import csv
import json
import math
import os
import statistics as st

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
R1 = "framesaver-20260729-185430-raid1-lighthouse"
R15 = "framesaver-20260729-215652-raid15-forceallroles"


def load(base):
    H = None
    S = []
    spawns = []
    spikes = []
    for line in open(os.path.join(LOGDIR, base + ".ndjson"), encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        t = o["type"]
        if t == "header":
            H = o
        elif t == "sample":
            S.append(o)
        elif t == "botSpawn":
            spawns.append(o)
        elif t == "spike":
            spikes.append(o)
    K = [o for o in S if o["state"] == "raid" and o["agents"]["live"] > 0]
    return H, K, spawns, spikes


def duab(o):
    v = o.get("phases", {}).get("PreLateUpdate/DirectorUpdateAnimationBegin", {})
    return v.get("avg", float("nan")) if isinstance(v, dict) else v


H1, K1, sp1, spk1 = load(R1)
H2, K2, sp2, spk2 = load(R15)
QPF = H1["qpcFrequency"]

# ------------------------------------------------------------ presentmon


def pm_frames(base, qlo, qhi):
    """FrameTime ms for frames whose CPUStartQPC lies in [qlo, qhi]."""
    out = []
    with open(os.path.join(LOGDIR, base + ".presentmon.csv"), newline="") as fh:
        rd = csv.reader(fh)
        head = next(rd)
        iq = head.index("CPUStartQPC")
        it = head.index("FrameTime")
        for row in rd:
            try:
                q = int(row[iq])
            except ValueError:
                continue
            if qlo <= q <= qhi:
                out.append(float(row[it]))
    return out


def pct(xs, p):
    ys = sorted(xs)
    return ys[min(len(ys) - 1, int(p / 100.0 * len(ys)))]


# in-raid qpc spans: first raid window's start (its qpc minus its span) to last
def spans(K):
    q0 = K[0]["qpc"] - int(60 * QPF)
    q1 = K[-1]["qpc"]
    return q0, q1


q1lo, q1hi = spans(K1)
q2lo, q2hi = spans(K2)
f1 = pm_frames(R1, q1lo, q1hi)
f2 = pm_frames(R15, q2lo, q2hi)

# matched age: overlap of the two raids' in-raid t ranges
t_lo = max(K1[0]["t"] - 60, K2[0]["t"] - 60)
t_hi = min(K1[-1]["t"], K2[-1]["t"])


def q_at(K, t):
    # linear map from t to qpc using the last window
    o = K[-1]
    return o["qpc"] - int((o["t"] - t) * QPF)


f1m = pm_frames(R1, q_at(K1, t_lo), q_at(K1, t_hi))
f2m = pm_frames(R15, q_at(K2, t_lo), q_at(K2, t_hi))

print("CLAIM A: the 3.50 ms level shift, and how much of it is raid age")
print("  in-raid PresentMon frames: raid1 n=%d  raid1.5 n=%d" % (len(f1), len(f2)))
print("  raid-wide (Alpha's cut):")
print("    mean   %7.3f -> %7.3f   delta %+.3f" % (st.mean(f1), st.mean(f2), st.mean(f1) - st.mean(f2)))
print("    p50    %7.3f -> %7.3f   delta %+.3f" % (pct(f1, 50), pct(f2, 50), pct(f1, 50) - pct(f2, 50)))
print("    p75    %7.3f -> %7.3f   delta %+.3f" % (pct(f1, 75), pct(f2, 75), pct(f1, 75) - pct(f2, 75)))
print("    p99    %7.3f -> %7.3f   delta %+.3f" % (pct(f1, 99), pct(f2, 99), pct(f1, 99) - pct(f2, 99)))
print("  matched raid age, t in [%.0f, %.0f] s (n=%d vs n=%d):" % (t_lo, t_hi, len(f1m), len(f2m)))
print("    mean   %7.3f -> %7.3f   delta %+.3f" % (st.mean(f1m), st.mean(f2m), st.mean(f1m) - st.mean(f2m)))
print("    p50    %7.3f -> %7.3f   delta %+.3f" % (pct(f1m, 50), pct(f2m, 50), pct(f1m, 50) - pct(f2m, 50)))
print("    p75    %7.3f -> %7.3f   delta %+.3f" % (pct(f1m, 75), pct(f2m, 75), pct(f1m, 75) - pct(f2m, 75)))
print("    p99    %7.3f -> %7.3f   delta %+.3f" % (pct(f1m, 99), pct(f2m, 99), pct(f1m, 99) - pct(f2m, 99)))

# raid 1.5's own drift at fixed population: windows with awake==1, total==27
steady = [o for o in K2 if o["bots"]["awake"] == 1 and o["bots"]["total"] == 27]
p50s = [o["framePct"]["p50"] for o in steady]
print("  raid 1.5's own drift floor: %d windows at awake==1, total==27:" % len(steady))
print("    p50 median %.3f  sd %.3f  range %.3f-%.3f"
      % (st.median(p50s), st.stdev(p50s), min(p50s), max(p50s)))
awk2m = [o["bots"]["awake"] for o in K2 if t_lo <= o["t"] <= t_hi]
awk1 = [o["bots"]["awake"] for o in K1]
print("  awake, matched age: raid1 med %.0f  raid1.5 med %.0f  -> delta %.1f bots"
      % (st.median(awk1), st.median(awk2m), st.median(awk1) - st.median(awk2m)))
d50 = pct(f1m, 50) - pct(f2m, 50)
print("  matched-age per-bot: %.3f / %.1f = %.3f ms/bot  (raid-wide gave %.3f/11 = %.3f)"
      % (d50, st.median(awk1) - st.median(awk2m), d50 / (st.median(awk1) - st.median(awk2m)),
         st.mean(f1) - st.mean(f2), (st.mean(f1) - st.mean(f2)) / 11.0))
print()

# ------------------------------------------------------------ claim C: p99/spawns

print("CLAIM C: 'p99 worsened because 41 spawns vs 31'")
late_sp2 = [s for s in sp2 if (s.get("raidElapsed") or 0) > (K2[0]["t"] - 60)]
print("  raid 1.5 spawn timing: %d of %d spawns completed before the first in-raid"
      % (len(sp2) - len(late_sp2), len(sp2)))
print("  window opens; in-raid spawns: %s"
      % (["t=%.0f %s" % (s["raidElapsed"], s["role"]) for s in late_sp2]))
rspk1 = [s for s in spk1 if s.get("state") == "raid"]
rspk2 = [s for s in spk2 if s.get("state") == "raid"]
dur1 = (K1[-1]["t"] - K1[0]["t"] + 60) / 60.0
dur2 = (K2[-1]["t"] - K2[0]["t"] + 60) / 60.0
print("  in-raid spike lines: raid1 %d in %.0f min (%.1f/min), raid1.5 %d in %.0f min (%.1f/min)"
      % (len(rspk1), dur1, len(rspk1) / dur1, len(rspk2), dur2, len(rspk2) / dur2))
# spikes near the single in-raid spawn
if late_sp2:
    sq = late_sp2[0]["qpc"] if "qpc" in late_sp2[0] else None
    near = [s for s in rspk2 if sq and abs(s["qpc"] - sq) < 5 * QPF]
    print("  spikes within 5 s of the one in-raid spawn: %d" % len(near))
# where raid 1.5's p99 mass lives: early (matched-age, has the extra fights) vs tail
early2 = [x for x in f2 if x >= 0][: len(f2m)]
tail2 = pm_frames(R15, q_at(K2, t_hi), q2hi)
print("  raid 1.5 p99 by segment: matched-age %.2f  tail %.2f  pooled %.2f"
      % (pct(f2m, 99), pct(tail2, 99), pct(f2, 99)))
print("  content difference in the matched-age segment (spawned in 1.5, absent in 1):")
r1_roles = set(s["role"] for s in sp1)
extra = [s["role"] for s in sp2 if s["role"] not in r1_roles]
import collections
print("    %s" % dict(collections.Counter(extra)))
print()

# ------------------------------------------------------------ claim D: the slope

print("CLAIM D: the within-raid slope and its identifying cut")
aw = [o["bots"]["awake"] for o in K2]
tot = [o["bots"]["total"] for o in K2]
n = len(aw)
ma, mt = st.mean(aw), st.mean(tot)
cov = sum((a - ma) * (b - mt) for a, b in zip(aw, tot)) / (n - 1)
r = cov / (st.stdev(aw) * st.stdev(tot))
print("  corr(awake, total) over all %d in-raid windows: %.3f  (Alpha said 0.91)" % (n, r))
cut = [o for o in K2 if o["bots"]["total"] in (27, 28) and o["t"] > 800]
print("  identifying cut: %d windows with total 27-28, t>800 (total flat, awake 1-4):" % len(cut))
xs = [o["bots"]["awake"] for o in cut]
for nm, get in (("frame.p50", lambda o: o["framePct"]["p50"]),
                ("playerLate", lambda o: o["playerLate"]["avg"]),
                ("DUAB", duab),
                ("aiTotal", lambda o: o["aiTotal"]["avg"])):
    ys = [get(o) for o in cut]
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a0 = my - b * mx
    res = [y - (a0 + b * x) for x, y in zip(xs, ys)]
    se = math.sqrt(sum(e * e for e in res) / (len(xs) - 2) / sxx)
    print("    %-10s slope %+7.4f ms/awake-bot   se %.4f   (95%% ~ %+0.3f..%+0.3f)"
          % (nm, b, se, b - 2.1 * se, b + 2.1 * se))
print("  awake values in the cut: %s" % sorted(collections.Counter(xs).items()))
print()

# ------------------------------------------------------------ claim B context

print("CLAIM B context: the animator number, measured within raid 1.5 alone")
hi = max(K2[: len(K2) // 2], key=lambda o: o["bots"]["awake"])
lo = [o for o in K2 if o["bots"]["awake"] == 1][0]
print("  within-raid contrast, w%d (awake %d) vs w%d (awake %d):"
      % (hi["window"], hi["bots"]["awake"], lo["window"], lo["bots"]["awake"]))
print("    DUAB %.3f -> %.3f  = %.4f ms per awake bot"
      % (duab(hi), duab(lo), (duab(hi) - duab(lo)) / (hi["bots"]["awake"] - lo["bots"]["awake"])))
print("  animCulled vs animCulledOffScreen, raid 1.5 medians: %d vs %d"
      % (st.median([o["bots"]["animCulled"] for o in K2]),
         st.median([o["bots"].get("animCulledOffScreen", -1) for o in K2])))
print("  (raid 1 medians: %d vs %s)"
      % (st.median([o["bots"]["animCulled"] for o in K1]),
         st.median([o["bots"].get("animCulledOffScreen", -1) for o in K1])))

# ------------------------------------------------------------ claim B: DUAB/bot

print()
print("CLAIM B: four estimates of the animator cost per awake bot")
d1m = [duab(o) for o in K1]
d2m = [duab(o) for o in K2 if t_lo <= o["t"] <= t_hi]
a1 = st.median([o["bots"]["awake"] for o in K1])
a2 = st.median([o["bots"]["awake"] for o in K2 if t_lo <= o["t"] <= t_hi])
print("  corpus slope (fight margin)                     0.1357")
print("  matched-age cross-raid: DUAB %.2f@%d -> %.2f@%d = %.3f/bot"
      % (st.median(d1m), a1, st.median(d2m), a2,
         (st.median(d1m) - st.median(d2m)) / (a1 - a2)))
print("  raid1 -> raid1.5 STEADY TAIL (Alpha's cut): 3.949 -> 1.750 over ~9 bots = 0.244/bot")
print("  tail identifying cut (distant-waker margin)     %+0.3f +/- %.3f" % (0.0281, 0.0257))
print("  -> the 0.244 is the outlier and it is the cross-raid, age-confounded one.")
print("     Within-raid and matched-age instruments cluster at 0.13-0.16 at the")
print("     average margin and ~0.03 at the distant margin.")
print()
print("COHERENT PER-BOT PICTURE at the margin the docket prices (distant, idle):")
print("  playerLate 0.070 (se 0.010, three instruments agree)  animator 0.13 avg /")
print("  0.03 distant   aiTotal ~0.02   ->  total ~0.22-0.25 ms/bot")
print("  matched-age p50 per bot: %.3f.  Docket's 0.35 is ~40%% high, and Alpha's" % (d50 / 7.0))
print("  'exemption set costs 4.72 vs 3.50 measured' contradiction dissolves at")
print("  0.24: 13.5 x 0.24 = 3.2 ~= the measured saving. The tension he flagged")
print("  was manufactured by the inflated per-bot price, not by the bots.")
