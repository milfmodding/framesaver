"""What the mod actually buys: animator cost per awake bot, fitted WITHIN each map across arms.

THE FINDING THIS FILE EXISTS FOR. Framesaver is an AI-stutter mod, and the AI scheduling is not
where its frame time comes from. Two measurements, both per awake bot per frame:

    stand-by gating   updateManual.awakeMs / awakeCalls    ~0.011 ms   (awake vs paused)
    animator cull     PreLateUpdate/DirectorUpdateAnimationBegin slope  ~0.22 ms

A factor of twenty. **Stand-by's value is that it identifies which bots are safe to cull; the
animator cull is where essentially all of the saving is.** Sophia said from memory that the cull
"had a pretty big impact" - this is that, quantified, and it was the pointer that found it.

THE PER-BOT SLOPE IS NOT CORROBORATED WITHIN AN ARM, AND THAT IS UNEXPLAINED. Read this before
quoting 0.211. The cross-arm fit says animator cost rises 0.211 ms per awake bot. But fitted
WITHIN a single arm, where awake count varies over windows and build/day/route are held constant,
the median slope is **0.091** and the mod-off arms are flat or slightly negative (Streets -0.002,
Interchange -0.058, Reserve -0.035).

A pre-registered prediction then failed. With the cull OFF nothing is culled, so every bot animates
and cost should track TOTAL bots. It does not: mod-off slopes against total are ~0 with |r| < 0.4
on seven of nine maps. **Within a raid, animator cost barely tracks bot count at all** - and if the
cross-arm gap were caused by the number of bots culled, it would have to.

So the honest position is: the cross-arm DIFFERENCE is real, large, and in the same direction on
seven maps. Its attribution to a per-bot cost is NOT established, and two analyses of the same data
disagree by 2.3x. Candidate explanations, none tested:

  * Vanilla already writes `CullUpdateTransforms` past `AnimatorCullDistance` (10 m), so most bots
    may already be cheap and only the few within 10 m cost anything - a count that is roughly
    constant within a raid. If so our cull buys much less than the cross-arm gap suggests, and the
    gap comes from something else.
  * `bots.awake` may be an instantaneous sample at window close while the phase figure is a mean
    over 30 s. Pairing a point estimate with a window mean attenuates any real within-arm slope
    toward zero. This one would RESCUE the slope and it is a question for Gamma, not a conclusion.
  * The mod-on legs are a different and partly unstamped binary, so the cross-arm gap may not be
    the mod at all.

What survives regardless: even the pessimistic 0.091 ms per bot is eight times the ~0.011 ms that
stand-by's own gating saves, so the ordering of the two mechanisms is robust while the coefficient
is not. Range 0.09-0.21, ratio 8-20x.

WHY THE SLOPE AND NOT THE DELTA. A mod-on-minus-mod-off delta on one map is a between-leg
difference: different day, different route, and for `20260728-225956-marathon` a `header.commit` of
`None`, i.e. an unidentified binary. The slope is fitted WITHIN a map across arms, so it survives
those; and it reproduces at 0.214 and 0.220 on two maps from five separate legs, which a
route-or-build artefact has no reason to do. The per-map deltas are printed too, and they are NOT
the result - the residual against them is large and named below.

WHY aiTotal IS THE WRONG FIELD, found by Beta 2026-07-31. `aiTotal` is `BotsController.method_0`
and does NOT contain `BotOwner.UpdateManual` (Telemetry.cs:1337 says so in the source). Stand-by
gates `UpdateManual`. So every "AI is N% of frame time" figure taken from `aiTotal` describes a
slice stand-by does not touch, and the honest per-bot number is 20x smaller than the one it gives.

DO NOT USE bots.animCulled AS THE CULLED COUNT. It is `CulledLastFrame`, which is
`CullSleepingBotAnimators.Value ? Sleeping.Count : 0` - it reports our intent, reads 0 the instant
the flag flips while the engine is still culling, and is an upper bound even when on. This file
regresses on `bots.awake`, which is measured either way. `animCullEngine` is the field that would
read the engine instead; until it exists, a latched arm and a clean arm are identical in the log.
"""
import collections
import glob
import json
import os
import statistics as S

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
ANIM = "PreLateUpdate/DirectorUpdateAnimationBegin"
WARMUP_SEC = 60


def arm_of(header_config):
    """standByEnabled dominates: with the subsystem off, forceAllRoles cannot act."""
    standby = header_config.get("standByEnabled")
    force = header_config.get("forceAllRoles")
    if standby is None or force is None:
        return "unknown"
    if not standby:
        return "modOff"
    return "forceAll" if force else "modOn"


def load():
    """(map, arm) -> list of per-window rows. Warm-up applied; teardown window dropped."""
    out = collections.defaultdict(list)
    legs = collections.defaultdict(set)
    for path in sorted(glob.glob(os.path.join(LOGDIR, "*.ndjson"))):
        arm, rows = None, []
        for ln in open(path, encoding="utf-8-sig", errors="replace"):
            ln = ln.strip()
            if not ln.endswith("}"):
                continue
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            if o.get("type") == "header":
                arm = arm_of(o.get("config") or {})
                continue
            if o.get("type") != "sample" or o.get("state") != "raid":
                continue
            el, ws = o.get("raidElapsed"), o.get("windowSec")
            if el is None or ws is None or el - ws < WARMUP_SEC:
                continue
            rows.append(o)
        # Teardown is the last in-raid window of each segment: its census reads after the game
        # object is gone. Identified by segment position, because `final` marks only some of them.
        seen = collections.defaultdict(list)
        for o in rows:
            seen[(o.get("raid"), str(o.get("map")))].append(o)
        for (_raid, mp), ws in seen.items():
            for o in ws[:-1]:
                ph = (o.get("phases") or {}).get(ANIM)
                b = o.get("bots") or {}
                if not isinstance(ph, dict) or ph.get("avg") is None or b.get("awake") is None:
                    continue
                out[(mp, arm)].append({"anim": ph["avg"], "awake": b["awake"],
                                       "asleep": b.get("asleep"), "frame": (o.get("frame") or {}).get("avg")})
                legs[(mp, arm)].add(os.path.basename(path))
    return out, legs


# Minimum spread in awake bots for a slope to be worth printing. A fit whose arms differ by one
# or two bots divides a small numerator by a smaller denominator and produces a large, unstable
# number - Interchange's arms are 1.5 bots apart and returned 2.156 ms/bot with an intercept of
# -7.6 ms, an impossible negative floor. It was the biggest figure in the table and would have been
# the one quoted. The two maps this excludes are exactly the two where it should: Factory cannot
# sleep anyone in either arm, and Interchange is where vanilla already sleeps most of the map, so
# neither has a lever arm to fit against.
MIN_AWAKE_SPREAD = 5.0


def fit(points):
    """Least-squares slope and intercept of anim against awake. Needs >=2 distinct x."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    n = len(xs)
    if n < 2 or len(set(xs)) < 2:
        return None, None
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None, None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return slope, my - slope * mx


def main():
    data, legs = load()
    if not data:
        print("REFUSED: no windows carry %s - the player-loop profiler was off" % ANIM)
        return 2

    print("ANIMATOR COST vs AWAKE BOTS, per window. Arm medians first, then the within-map fit.")
    print()
    print("  %-14s %-9s %4s %9s %9s %8s %8s %5s"
          % ("map", "arm", "n", "animMs", "frameMs", "awake", "asleep", "legs"))
    print("  " + "-" * 78)
    per_map = collections.defaultdict(list)
    for (mp, arm) in sorted(data):
        rr = data[(mp, arm)]
        aw = S.median([r["awake"] for r in rr])
        an = S.median([r["anim"] for r in rr])
        fr = [r["frame"] for r in rr if r["frame"] is not None]
        print("  %-14s %-9s %4d %9.3f %9s %8.1f %8s %5d"
              % (mp, arm, len(rr), an, "%.2f" % S.median(fr) if fr else "-", aw,
                 "%.1f" % S.median([r["asleep"] for r in rr if r["asleep"] is not None]),
                 len(legs[(mp, arm)])))
        per_map[mp].append((aw, an, arm))

    print()
    print("  WITHIN-MAP FIT of animator ms against awake bots, one point per ARM. A slope that")
    print("  reproduces across maps drawn from different legs is not a route or build artefact.")
    print()
    print("  %-14s %5s %14s %12s %s" % ("map", "arms", "ms per awake bot", "intercept", "points"))
    print("  " + "-" * 78)
    slopes, weak = [], []
    for mp in sorted(per_map):
        pts = sorted(per_map[mp])
        slope, icept = fit([(a, n) for a, n, _ in pts])
        shown = " ".join("%s:%.1f->%.2f" % (a[:7], x, y) for x, y, a in pts)
        if slope is None:
            print("  %-14s %5d   one arm only - no within-map contrast available" % (mp, len(pts)))
            continue
        spread = max(p[0] for p in pts) - min(p[0] for p in pts)
        if spread < MIN_AWAKE_SPREAD:
            weak.append((mp, slope, spread, shown))
            continue
        slopes.append((mp, slope))
        print("  %-14s %5d %14.3f %12.3f %s" % (mp, len(pts), slope, icept, shown))

    if weak:
        print()
        print("  EXCLUDED - lever arm under %.0f awake bots, so the slope is unstable and NOT a"
              % MIN_AWAKE_SPREAD)
        print("  measurement. Printed so the exclusion is visible rather than silent:")
        for mp, slope, spread, shown in weak:
            print("  %-14s arms %.1f bots apart, would have read %.3f ms/bot   %s"
                  % (mp, spread, slope, shown))

    print()
    if len(slopes) >= 2:
        vals = [s for _, s in slopes]
        print("  slopes: %s" % ", ".join("%s %.3f" % (m, s) for m, s in slopes))
        print("  median %.3f ms of animator cost per awake bot, over %d map(s) with a real lever arm."
              % (S.median(vals), len(vals)))
        print()
        print("  Compare updateManual: ~0.011 ms per awake bot per frame is what stand-by's own")
        print("  gating saves. The cull is the mechanism; stand-by only chooses its targets.")
    print()
    print("  WHAT THIS DOES NOT EXPLAIN. On Woods the p75 arm delta is 7.0 ms and the animator")
    print("  accounts for ~2.6 of it. The mod-on leg there stamps header.commit = None, so that")
    print("  delta compares against an unidentified binary and is not quoted. The slope is the")
    print("  result; the delta is not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
