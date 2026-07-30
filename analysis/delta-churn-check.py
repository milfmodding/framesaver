#!/usr/bin/env python3
"""Attack Alpha's churn hypothesis: |d awake| tracks window p99 (rho 0.651 at
awake==1) in raid 1.5, read as wake/sleep transitions costing tail frames.

His own listed weakness is the one to press: churn windows may simply BE event
windows. The stand-by system wakes bots on player distance, so player MOVEMENT
causes churn; movement also causes streaming, physics and encounter load that
would fatten the tail with no per-transition cost at all.

Three tests, in order of decisiveness:
  1. Reproduce his Spearman table (same proxy, same strata) so any disagreement
     is located first.
  2. The third-variable table: pos.dist (player displacement per window) as the
     confounder. If displacement predicts p99 as well as churn does, and churn
     is itself predicted by displacement, the rank correlation has a common
     cause reading that stratifying on awake LEVEL cannot remove.
  3. The mechanism test, which needs no new counter: spike lines decompose the
     actual worst frames by phase. If churn's tail cost were wake transitions,
     spike phases in churn windows should lean AI/animator (UpdateManual runs
     under Update/ScriptRunBehaviourUpdate; un-cull lands in
     PreLateUpdate/DirectorUpdateAnimationBegin). If they lean streaming /
     physics / rendering, the tail belongs to movement, not transitions.

Known weaknesses:
  - The churn proxy is NET roster change, a strict lower bound on GROSS
    transitions, as Alpha said. A null here would be uninformative; only the
    positive readings are usable, and only comparatively.
  - Spike lines only cover frames above the 30 ms spike threshold; window p99
    (~16-28 ms) sits below it, so test 3 characterises the extreme tail, not
    p99 itself. Stated rather than hidden.
  - n=33 windows, and every stratified cell is small. Ranks only.
"""

import json
import math
import os
import statistics as st
from collections import Counter, defaultdict

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
R15 = "framesaver-20260729-215652-raid15-forceallroles"

S, spikes, deaths = [], [], []
for line in open(os.path.join(LOGDIR, R15 + ".ndjson"), encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line:
        continue
    o = json.loads(line)
    if o["type"] == "sample":
        S.append(o)
    elif o["type"] == "spike":
        spikes.append(o)
    elif o["type"] == "death":
        deaths.append(o)

K = [o for o in S if o["state"] == "raid" and o["agents"]["live"] > 0]

# per-window rows, churn needs the previous window's awake
rows = []
for i in range(1, len(K)):
    a, b = K[i - 1], K[i]
    rows.append({
        "w": b["window"],
        "t": b["t"],
        "churn": abs(b["bots"]["awake"] - a["bots"]["awake"]),
        "awake": b["bots"]["awake"],
        "p99": b["framePct"]["p99"],
        "p50": b["framePct"]["p50"],
        "dist": b["pos"]["dist"],
        "deaths": sum(1 for d in deaths
                      if d.get("raidElapsed") and b["t"] - 60 < d["raidElapsed"] <= b["t"]),
    })


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


def sp(sel, xk, yk):
    xs = [r[xk] for r in sel]
    ys = [r[yk] for r in sel]
    return spearman(xs, ys)


print("TEST 1: reproduce Alpha's table (n=%d windows with a predecessor)" % len(rows))
one = [r for r in rows if r["awake"] == 1]
print("  churn vs p99                 %+0.3f   (Alpha +0.598)" % sp(rows, "churn", "p99"))
print("  awake level vs p99           %+0.3f   (Alpha +0.393)" % sp(rows, "awake", "p99"))
print("  churn vs awake               %+0.3f   (Alpha +0.581)" % sp(rows, "churn", "awake"))
print("  churn vs p99 | awake==1      %+0.3f   (Alpha +0.651, n=%d)" % (sp(one, "churn", "p99"), len(one)))
print()

print("TEST 2: the third variable Alpha could not name -- player displacement")
print("  pos.dist vs p99              %+0.3f" % sp(rows, "dist", "p99"))
print("  pos.dist vs churn            %+0.3f" % sp(rows, "dist", "churn"))
print("  pos.dist vs p99 | awake==1   %+0.3f" % sp(one, "dist", "p99"))
print("  churn vs p99 | awake==1 AND dist below median:")
med = st.median([r["dist"] for r in one])
lo = [r for r in one if r["dist"] < med]
hi = [r for r in one if r["dist"] >= med]
for label, grp in (("low-dist", lo), ("high-dist", hi)):
    if len(grp) >= 3:
        print("    %-9s (n=%2d)  churn~p99 %+0.3f   dist~p99 %+0.3f"
              % (label, len(grp), sp(grp, "churn", "p99"), sp(grp, "dist", "p99")))
    else:
        print("    %-9s (n=%2d)  too small to rank" % (label, len(grp)))
print("  deaths-in-window vs p99      %+0.3f   deaths vs churn %+0.3f"
      % (sp(rows, "deaths", "p99"), sp(rows, "deaths", "churn")))
print()

print("  window dump, sorted by p99 (top 12):")
print("   w    t     churn awake  dist   deaths  p99")
for r in sorted(rows, key=lambda r: -r["p99"])[:12]:
    print("  %2d %6.0f   %3d   %3d  %6.1f   %3d   %6.2f"
          % (r["w"], r["t"], r["churn"], r["awake"], r["dist"], r["deaths"], r["p99"]))
print()

print("TEST 3: what the worst frames were actually doing (spike phase leader)")
print("  spikes are frames > 30 ms; this is the extreme tail, above window p99.")
by_w = defaultdict(list)
for s in spikes:
    if s.get("state") != "raid":
        continue
    by_w[s["window"]].append(s)

churn_w = set(r["w"] for r in rows if r["churn"] > 0)
calm_w = set(r["w"] for r in rows if r["churn"] == 0)


def leader(s):
    ph = s.get("phases", {})
    flat = {k: v for k, v in ph.items() if "/" in k and isinstance(v, (int, float))}
    if not flat:
        return "none"
    return max(flat, key=flat.get)


def profile(ws, label):
    ss = [s for w in ws for s in by_w.get(w, [])]
    n = sum(1 for r in rows if r["w"] in ws)
    lead = Counter(leader(s) for s in ss)
    print("  %-28s %3d spikes in %2d windows (%.1f/window)"
          % (label, len(ss), n, len(ss) / n if n else float("nan")))
    for k, c in lead.most_common(5):
        print("      %-52s %3d" % (k, c))
    return ss


s_ch = profile(churn_w, "churn windows (churn>0):")
s_ca = profile(calm_w, "calm windows (churn==0):")
if s_ch and s_ca:
    print("  spike frame ms: churn med %.1f  calm med %.1f"
          % (st.median([s["frame"] for s in s_ch]), st.median([s["frame"] for s in s_ca])))
print()
print("  Reading guide: wake transitions execute under Update/ScriptRunBehaviourUpdate")
print("  (UpdateManual) and PreLateUpdate/DirectorUpdateAnimationBegin (un-cull).")
print("  Movement/streaming lands elsewhere. If churn windows' spikes lead in the")
print("  same phases as calm windows', the tail's composition does not change when")
print("  churn is present -- the churn correlation then rides on frequency of event")
print("  windows, not on a transition mechanism.")

# ------------------------------------------------------------ test 4: deaths-free

print()
print("TEST 4: the cut Alpha asked for -- churn varying with proximity and content held")
print("  pos.dist has a mass at zero (parked): %d of %d awake==1 windows"
      % (sum(1 for r in one if r["dist"] == 0), len(one)))
print("  so the dist median split degenerates; use fight adjacency (deaths in this")
print("  or the previous window) as the content control instead.")

dw = set()
for i, r in enumerate(rows):
    if r["deaths"] > 0:
        dw.add(r["w"])
        if i + 1 < len(rows):
            dw.add(rows[i + 1]["w"])

nofight = [r for r in one if r["w"] not in dw]
fight = [r for r in one if r["w"] in dw]
print("  awake==1, fight-adjacent excluded: n=%d (removed %d)" % (len(nofight), len(fight)))
print("    churn vs p99 | awake==1, no fight   %+0.3f" % sp(nofight, "churn", "p99"))
print("    (was +0.651 with fights in)")
print("  2x2 cell medians of p99, all windows:")
for cl, cn in (("churn>0", lambda r: r["churn"] > 0), ("churn=0", lambda r: r["churn"] == 0)):
    for fl, fn in (("fight", lambda r: r["w"] in dw), ("no fight", lambda r: r["w"] not in dw)):
        cell = [r["p99"] for r in rows if cn(r) and fn(r)]
        lab = "%s & %s" % (cl, fl)
        if cell:
            print("    %-20s n=%2d  p99 med %6.2f" % (lab, len(cell), st.median(cell)))
        else:
            print("    %-20s n= 0" % lab)

# spike composition with fights excluded
print("  spike phase leader, fight-adjacent windows excluded:")
ch_nf = [w for w in churn_w if w not in dw]
ca_nf = [w for w in calm_w if w not in dw]
profile(ch_nf, "churn, no fight:")
profile(ca_nf, "calm, no fight:")
