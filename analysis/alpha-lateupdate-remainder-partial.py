"""Does the remainder track AWAKE, or just track a busy frame that happens to have more bots?

First pass gave rho(remainder, awake) = +0.443 in raid 1, which is not zero and not far off the
animator's +0.681. So "the remainder is not bot work" is not established. But awake also tracks
frame time (+0.518), and a busier moment has more of everything - so a raw correlation cannot
separate "the remainder is awake-bot work" from "awake and the remainder are both downstream of
a busy frame".

Two reads that can:

  1. rho(remainder SHARE of frame, awake). Dividing by frame time removes the common busyness
     term. If the remainder is genuinely awake-scaled, its SHARE rises as bots wake. If it is
     scene/UI/player work, the share is flat or falls while awake work crowds it out.
     The animator is the positive control again: its share MUST rise with awake.

  2. The magnitude. A correlation says direction, not price. Split each leg at its median awake
     and difference the remainder. That is the number that decides whether anything is here,
     and a rank correlation cannot supply it.

Reported per leg, never pooled: raid 1 and raid 1.5 sit at different awake-ages and the ramp
result says per-bot cost is not the same quantity at both.
"""
import json
import os

LOG = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
LEGS = [("raid 1  ", "framesaver-20260729-185430-raid1-lighthouse"),
        ("raid 1.5", "framesaver-20260729-215652-raid15-forceallroles")]

LATE = "PreLateUpdate/ScriptRunBehaviourLateUpdate"
ANIM = "PreLateUpdate/DirectorUpdateAnimationBegin"


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return float("nan")
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = 0.5 * (i + j) + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(xs, ys):
    n = len(xs)
    if n < 4:
        return float("nan")
    a, b = rank(xs), rank(ys)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = sum((v - ma) ** 2 for v in a) ** 0.5
    db = sum((v - mb) ** 2 for v in b) ** 0.5
    return num / (da * db) if da and db else float("nan")


def load(tag):
    rows = []
    for ln in open(os.path.join(LOG, tag + ".ndjson"), encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "sample" or o.get("state") != "raid" or o.get("final"):
            continue
        ph = o.get("phases") or {}
        late = (ph.get(LATE) or {}).get("avg")
        anim = (ph.get(ANIM) or {}).get("avg")
        pl = (o.get("playerLate") or {}).get("avg")
        fr = (o.get("frame") or {}).get("avg")
        b = o.get("bots") or {}
        if None in (late, pl, fr, anim, b.get("awake")) or not b.get("total"):
            continue
        rows.append(dict(rem=late - pl, anim=anim, fr=fr, awake=b["awake"],
                         remShare=(late - pl) / fr, animShare=anim / fr))
    return rows


for label, tag in LEGS:
    rows = load(tag)
    aw = [r["awake"] for r in rows]
    med = median(aw)
    lo = [r for r in rows if r["awake"] <= med]
    hi = [r for r in rows if r["awake"] > med]

    print("=== %s   %d windows   awake %d..%d (median %g)"
          % (label, len(rows), min(aw), max(aw), med))
    print("    SHARE-vs-AWAKE, the busyness-free read")
    print("      rho(remainder share, awake)  %+.3f" % spearman([r["remShare"] for r in rows], aw))
    print("      rho(animator  share, awake)  %+.3f   <- positive control"
          % spearman([r["animShare"] for r in rows], aw))
    if not hi:
        print("    MAGNITUDE: no window above the median awake - this leg cannot answer it")
        print("      (awake sits at %g for most of it, which is the whole point of the leg)" % med)
        print()
        continue
    d_rem = median([r["rem"] for r in hi]) - median([r["rem"] for r in lo])
    d_anim = median([r["anim"] for r in hi]) - median([r["anim"] for r in lo])
    d_aw = median([r["awake"] for r in hi]) - median([r["awake"] for r in lo])
    print("    MAGNITUDE, split at median awake: %d low / %d high, %g bots apart"
          % (len(lo), len(hi), d_aw))
    print("      remainder  %6.3f -> %6.3f  = %+.3f ms  (%+.4f ms per bot)"
          % (median([r["rem"] for r in lo]), median([r["rem"] for r in hi]),
             d_rem, d_rem / d_aw if d_aw else float("nan")))
    print("      animator   %6.3f -> %6.3f  = %+.3f ms  (%+.4f ms per bot)  <- control"
          % (median([r["anim"] for r in lo]), median([r["anim"] for r in hi]),
             d_anim, d_anim / d_aw if d_aw else float("nan")))
    if d_aw:
        print("      the remainder moves %.2f%% as much per bot as the animator does"
              % (100.0 * (d_rem / d_aw) / (d_anim / d_aw)) if d_anim else "")
    print()
