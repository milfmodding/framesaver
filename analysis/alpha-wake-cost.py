"""What does WAKING a distant bot cost, and how much of that can slicing discount?

Sophia's rule 3 wakes distant bots and runs them 1-in-5, expecting to pay 20%.
The 20% only applies to work the BRAIN SCHEDULER dispatches. Framesaver's three
sleeping-bot savings are all gated on BotStandByType.paused, and none of them is
dispatched by the brain scheduler:

  animator CullCompletely   SleepingBotAnimatorPatch          -> Unity, per frame
  Player.LateUpdate skip    SkipSleepingPlayerLateUpdatePatch -> Unity, per frame
  Player world tick skip    SkipSleepingWorldTickPatch        -> GameWorld.PlayerTick

Wake a bot and all three return at 100%, whatever the brain period is. So the
question is the size of those three against the one term the discount reaches.

Slopes on bots.awake, within leg, steady state - the same estimator as the rest of
the corpus work, so the numbers are comparable to 0.021 (aiTotal) and 0.136 (anim).
"""
import json
import glob
import os
import sys
from collections import defaultdict

LOGS = sys.argv[1:] or sorted(glob.glob(
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson"))
STEADY = 120.0
ANIM = "PreLateUpdate/DirectorUpdateAnimationBegin"

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
            ph = o.get("phases") or {}
            rows.append({
                "leg": "%s %s L%d" % (stem, m, leg),
                "awake": b.get("awake") or 0,
                "anim": (ph.get(ANIM) or {}).get("avg") or 0.0,
                "late": (o.get("playerLate") or {}).get("avg") or 0.0,
                "tick": (o.get("playerTick") or {}).get("avg") or 0.0,
                "ai": (o.get("aiTotal") or {}).get("avg") or 0.0,
            })

if not rows:
    print("NO ROWS - refusing to report.")
    sys.exit(2)


def ols(xs, ys):
    n = len(xs)
    if n < 4:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-9:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    resid = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 0.0 if syy <= 1e-12 else max(0.0, 1.0 - resid / syy)
    return {"b": b, "ci": 1.96 * (resid / (n - 2) / sxx) ** 0.5, "r2": r2}


def med(v):
    s = sorted(v)
    return s[len(s) // 2] if s else float("nan")


by = defaultdict(list)
for r in rows:
    by[r["leg"]].append(r)

acc = defaultdict(list)
# Per-leg fits kept keyed as well as accumulated. The subtotal below is a SUM of three slopes
# fitted on the SAME legs, so it is paired and must be summed per leg and aggregated last.
# `acc[f]` drops None fits, so pairing its lists by index would align different legs.
per_leg = {}
for leg in by:
    v = by[leg]
    xs = [r["awake"] for r in v]
    fits = {}
    for f in ("anim", "late", "tick", "ai"):
        res = ols(xs, [r[f] for r in v])
        fits[f] = res
        if res:
            acc[f].append(res)
    per_leg[leg] = fits

print("cost of ONE MORE AWAKE BOT, by component (ms/bot, within leg, steady state)\n")
print("%-34s %9s %6s %8s %10s" % ("component", "ms/bot", "legs", "med R2", "CI>0 legs"))
print("-" * 72)
paused_gated_wrong = 0.0
LABEL = {
    "anim": "animator state machine  [paused]",
    "late": "Player.LateUpdate       [paused]",
    "tick": "Player world tick       [paused]",
    "ai":   "brain tick          [SLICEABLE]",
}
for f in ("anim", "late", "tick", "ai"):
    v = acc[f]
    if not v:
        continue
    b = med([x["b"] for x in v])
    print("%-34s %9.4f %6d %8.2f %10d"
          % (LABEL[f], b, len(v), med([x["r2"] for x in v]),
             sum(1 for x in v if x["b"] - x["ci"] > 0)))
    if f != "ai":
        paused_gated_wrong += b

# FIXED 2026-07-30. `paused_gated` was built by adding three medians taken across legs, which is
# the aggregation-order defect: the three slopes come from the SAME legs and are paired, so a sum
# of their medians need not be attained by any leg that happened. This is the number that priced
# the role-distance proposal at 1.25 ms, so the wrong form left the file and reached Sophia.
# Built per leg and aggregated last; the wrong form is retained beside it so the size is visible.
PAUSED = ("anim", "late", "tick")
per_leg_sums = [sum(per_leg[lg][f]["b"] for f in PAUSED)
                for lg in per_leg if all(per_leg[lg].get(f) for f in PAUSED)]
paused_gated = med(per_leg_sums) if per_leg_sums else float("nan")
ai_vals = [per_leg[lg]["ai"]["b"] for lg in per_leg if per_leg[lg].get("ai")]
ai = med(ai_vals)
print("-" * 72)
print("%-34s %9.4f   <- returns at 100%% when a bot is woken   (%d of %d legs carry all three)"
      % ("paused-gated subtotal", paused_gated, len(per_leg_sums), len(per_leg)))
print("%-34s %9.4f   <- the only term a 1-in-5 period discounts" % ("brain tick", ai))
print("%-34s %9.4f   <- sum of medians, the WRONG form, for size only (%+.4f)"
      % ("  [aggregation-order check]", paused_gated_wrong, paused_gated_wrong - paused_gated))
print("\nnote: UpdateManual's 22 subsystem ticks are NOT in aiTotal (which times the brain")
print("      scheduler) and have no phase of their own in the telemetry. The one term")
print("      Sophia's 20%% actually applies to is therefore UNMEASURED - so this is a")
print("      lower bound on the wake cost, not an estimate of it.")

print("\nwhat rule 3 costs, if it wakes N distant bots (paused-gated terms at 100%,")
print("brain at 20%, subsystems unknown and additional)")
# The denominator is an EXTERNAL constant, not measured here, and it is named so nobody reads
# the percentages as self-contained. Found while auditing this file: it previously also computed
# `base` as the median per-window SUM of the four components and then never used it, while the
# percentages divided by this hardcoded 12.58 - an unused variable sitting one line above a magic
# number is how a reader concludes the number was derived. `base` was a component subtotal
# anyway, not a frame time, so using it would have been worse than dropping it.
P50_MS_EXTERNAL = 12.58
comp = med([r["anim"] + r["late"] + r["tick"] + r["ai"] for r in rows])
print("  (denominator %.2f ms is an external p50, not from this file; the four components"
      " here median %.2f ms per frame)" % (P50_MS_EXTERNAL, comp))
print("  %-6s %12s %14s" % ("N", "added ms", "as %% of p50 %.2fms" % P50_MS_EXTERNAL))
for n in (5, 10, 15, 20):
    add = n * (paused_gated - 0.8 * ai)
    print("  %-6d %12.2f %13.0f%%" % (n, add, 100.0 * add / P50_MS_EXTERNAL))
print("\n  for scale: the ENTIRE proposal, both levers perfect, is worth 1.25 ms")
