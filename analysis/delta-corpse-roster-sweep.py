#!/usr/bin/env python3
"""Close the two questions Alpha's deadAwake message left open, from disk.

Q1 (the older corpus): were corpses inside bots.awake in the 22 pre-ledger
logs, inflating every per-awake-bot denominator? The corpses-stay-on-roster
premise makes a prediction that needs no death ledger: bots.total stays PINNED
AT PEAK for the whole raid, because nothing leaves. Sweep all 24 logs for the
total trajectory (peak, final, count of mid-raid drops) plus the
awake+asleep==total identity.

Q2 (the transient): in the death windows themselves, are the +-1-2 excess
excursions transitions or transient corpse residency? Both are anti-correlated
and total-conserving at window level, as Alpha said -- but they differ in
MAGNITUDE per death. Align deaths to windows by QPC (raidElapsed and window t
have different zero points -- an earlier version of this check mis-assigned
every death by ~90 s) and compare the death window's excess against the
alive-fraction-only prediction sum((1-f)) for instant removal vs the residency
prediction (>= post-death fraction f per corpse).

Results (2026-07-30):
  - 19 of 21 logs with in-raid bots data show bots.total FALLING mid-raid;
    the remaining 2-3 are short/kill-free logs where the test has no power.
    Corpses-stay is refuted everywhere it is testable, without a ledger.
  - Cleanest death windows (no concurrent churn): raid1 w14, two deaths,
    instant-removal predicts +0.72, observed +0.72 EXACT; raid1 w10 predicts
    +0.28, observed +0.30. Corpse residency ~ 0 at 60 s granularity even
    inside the death window.

Instrument-role note for raid 2: deadAwake is a one-shot roster sample at
window end -- against a sub-window transient it reads nonzero only if the
sample lands inside the residency, so deadAwake ~ 0 is the PREDICTED value and
confirms nothing about the transient. deadAwake settles the steady-state claim;
deadCalls (integrating over every call) prices the transient. Assigning the
transient question to deadAwake would be a check that cannot fail.
"""

import glob
import json
import os

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"

print("Q1: roster trajectory, all logs (corpses-stay predicts drops == 0 at peak)")
print("%-42s %5s %5s %5s %6s" % ("log", "peak", "final", "drops", "id-ok"))
for fn in sorted(glob.glob(os.path.join(LOGDIR, "framesaver-*.ndjson"))):
    tot = []
    mismatch = 0
    for line in open(fn, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        if o["type"] != "sample" or o.get("state") != "raid":
            continue
        b = o.get("bots")
        if not b or "total" not in b or b["total"] <= 0:
            continue
        tot.append(b["total"])
        if b["awake"] + b["asleep"] != b["total"]:
            mismatch += 1
    base = os.path.basename(fn)[11:-7]
    if not tot:
        print("%-42s  no in-raid bots data" % base)
        continue
    drops = sum(1 for i in range(1, len(tot)) if tot[i] < tot[i - 1])
    print("%-42s %5d %5d %5d %6s" % (base, max(tot), tot[-1], drops,
                                     "ok" if not mismatch else "%d!" % mismatch))

print()
print("Q2: per-death excess vs instant-removal prediction (QPC-aligned)")
for name, fn in (("raid1", "framesaver-20260729-185430-raid1-lighthouse.ndjson"),
                 ("raid1.5", "framesaver-20260729-215652-raid15-forceallroles.ndjson")):
    S, D, QPF = [], [], None
    for line in open(os.path.join(LOGDIR, fn), encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        if o["type"] == "header":
            QPF = o["qpcFrequency"]
        elif o["type"] == "sample" and o["state"] == "raid" and o["agents"]["live"] > 0:
            S.append(o)
        elif o["type"] == "death" and "qpc" in o:
            D.append(o)

    def exc(o):
        return o["updateManual"]["awakeCalls"] / o["frames"] - o["bots"]["awake"]

    print("=== %s" % name)
    bywin = {}
    for d in D:
        for i, o in enumerate(S):
            if o["qpc"] - 60 * QPF < d["qpc"] <= o["qpc"]:
                f = (o["qpc"] - d["qpc"]) / (60.0 * QPF)
                bywin.setdefault(i, []).append(f)
                break
    for i, fs in sorted(bywin.items()):
        o = S[i]
        pred_instant = sum(1 - f for f in fs)
        pred_resident = sum(fs) + pred_instant
        nxt = exc(S[i + 1]) if i + 1 < len(S) else float("nan")
        print("  w%-2d deaths=%d  predicted: instant %+0.2f / resident >= %+0.2f"
              "   observed %+0.2f   next-window %+0.2f"
              % (o["window"], len(fs), pred_instant, pred_resident, exc(o), nxt))
