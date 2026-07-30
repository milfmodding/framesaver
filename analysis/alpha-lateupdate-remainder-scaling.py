"""Is the unattributed ScriptRunBehaviourLateUpdate remainder bot-scaled?

Gamma's park argument is that `skipLate` was TRUE in both legs, so the remainder is what
SURVIVED our lever rather than what awaits it. That is correctly scoped - skipLate suppresses
the LateUpdate of SLEEPING bots - but the conclusion drawn from it ("the lever most likely to
act has already been pulled") is one step stronger than the premise. skipLate says nothing about
AWAKE bots' LateUpdate, and sleeping more bots is precisely our lever, so if the remainder
contained awake-bot work the lever would still reach it.

That is a testable question and it does not need the config at all. WITHIN each leg, regress
the remainder on awake count. If the remainder is awake-bot work, it tracks awake. If it is
scene/UI/player work it tracks frame time and not awake.

Within-raid, because between-leg contrasts are not an instrument for effects this size - the
established floor is 0.259 ms pooled. The two-leg comparison is reported too, but only as a
consistency read on a within-leg answer, never as the answer.

Spearman rather than Pearson: awake count is a small-integer ladder with an uneven population
at each rung, and we care about monotone tracking, not linearity.
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
    """Average ranks, so ties on the awake ladder do not invent an ordering."""
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


for label, tag in LEGS:
    path = os.path.join(LOG, tag + ".ndjson")
    if not os.path.isfile(path):
        print("skip %s: no ndjson" % label)
        continue

    skip_late = None
    rows = []
    for ln in open(path, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "sample" or o.get("state") != "raid":
            continue
        cfg = o.get("cfg") or {}
        if "skipLate" in cfg:
            skip_late = cfg["skipLate"] if skip_late is None else (skip_late and cfg["skipLate"])
        ph = o.get("phases") or {}
        late = (ph.get(LATE) or {}).get("avg")
        anim = (ph.get(ANIM) or {}).get("avg")
        pl = (o.get("playerLate") or {}).get("avg")
        fr = (o.get("frame") or {}).get("avg")
        bots = o.get("bots") or {}
        awake = bots.get("awake")
        total = bots.get("total")
        if None in (late, pl, fr, awake) or o.get("final"):
            continue
        # Steady state only: a window with no roster is pre-spawn or post-raid, and the
        # remainder there is measuring a different world.
        if not total:
            continue
        rows.append(dict(late=late, pl=pl, rem=late - pl, fr=fr, awake=awake,
                         anim=anim or 0.0, share=100.0 * (late - pl) / fr))

    if len(rows) < 4:
        print("%s: only %d steady-state windows, not enough" % (label, len(rows)))
        continue

    print("=== %s   skipLate=%s   %d steady-state windows" % (label, skip_late, len(rows)))
    print("    median LateUpdate  %6.3f ms" % median([r["late"] for r in rows]))
    # Median of the per-window SHARE, not median(pl)/median(late). The two quantities are
    # measured in the same window, so they are paired, and a ratio of two medians need not be
    # attained in any window that happened. This line carried the wrong form while the file's
    # own purpose was to correct that error elsewhere.
    print("    median playerLate  %6.3f ms  (%.0f%% of it, per-window share)"
          % (median([r["pl"] for r in rows]),
             100.0 * median([r["pl"] / r["late"] for r in rows if r["late"]])))
    print("    median REMAINDER   %6.3f ms  = %.2f%% of a %.3f ms frame"
          % (median([r["rem"] for r in rows]), median([r["share"] for r in rows]),
             median([r["fr"] for r in rows])))
    print("    median animator    %6.3f ms" % median([r["anim"] for r in rows]))
    aw = [r["awake"] for r in rows]
    print("    awake count        min %d  median %g  max %d" % (min(aw), median(aw), max(aw)))
    print("    rho(remainder, awake)      %+.3f" % spearman([r["rem"] for r in rows], aw))
    print("    rho(remainder, frame)      %+.3f" % spearman([r["rem"] for r in rows],
                                                            [r["fr"] for r in rows]))
    print("    rho(animator,  awake)      %+.3f   <- the positive control: a KNOWN bot-scaled"
          % spearman([r["anim"] for r in rows], aw))
    print("                                        leaf must track awake in this same window set,")
    print("                                        or the test cannot detect scaling at all")
    print("    rho(frame,     awake)      %+.3f" % spearman([r["fr"] for r in rows], aw))
    print()
