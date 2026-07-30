"""Re-derivation of Delta's marginal-bot-cost slope, with three checks Delta's version
cannot perform.

C1 LEG COLLISION. Delta keys legs as "<map> L<n>" with n reset per FILE, so the first
    Lighthouse of one log and the first Lighthouse of another share a key and merge into
    one "leg". Merging two visits to a map across sessions is exactly the drift confound
    the within-leg design exists to remove. Keyed here by (file, index, map).

C2 WRONG PREDICTOR FOR THE QUESTION. The proposal is about raid POPULATION, which is
    bots.total. Delta regresses on bots.awake. If the brain ticks sleeping bots too -
    which is Delta's own claim in their point 2 - then AI cost responds to total while
    awake-count misses it, and the AI share is understated by construction.

C3 B2's SIGN, AS A MEASUREMENT. Does a sleeping bot cost the same at the brain as an
    awake one? Delta answers from a code comment. Measure it: compare how well aiTotal
    is explained by total vs by awake, and fit both predictors together where the
    conditioning allows. Perfect anti-collinearity (awake + asleep == total, with total
    near-constant within a leg) may make the joint fit unavailable - report that rather
    than quoting an unstable coefficient.
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
                "map": m,
                "awake": b.get("awake") or 0,
                "asleep": b.get("asleep") or 0,
                "total": b.get("total") or 0,
                "frame": (o.get("frame") or {}).get("avg") or 0.0,
                "ai": (o.get("aiTotal") or {}).get("avg") or 0.0,
                "anim": (ph.get(ANIM) or {}).get("avg") or 0.0,
            })

if not rows:
    print("NO ROWS - refusing to report. Check the glob and the predicates.")
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
    se = (resid / (n - 2) / sxx) ** 0.5
    r2 = 0.0 if syy <= 1e-12 else max(0.0, 1.0 - resid / syy)
    return {"b": b, "ci": 1.96 * se, "n": n, "r2": r2, "lo": min(xs), "hi": max(xs)}


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-12 or syy <= 1e-12:
        return None
    return sxy / (sxx * syy) ** 0.5


def med(v):
    s = sorted(v)
    return s[len(s) // 2] if s else float("nan")


by = defaultdict(list)
for r in rows:
    by[r["leg"]].append(r)

print("C1  LEG KEYING")
print("    windows %d, legs under (file,index,map) keying: %d" % (len(rows), len(by)))
collapsed = len(set(k.split(None, 1)[1] for k in by))
print("    legs under Delta's (index,map) keying:          %d" % collapsed)
if collapsed != len(by):
    print("    -> COLLISION CONFIRMED: %d of Delta's legs are two sessions merged"
          % (len(by) - collapsed))
else:
    print("    -> no collision; Delta's keying happened to be safe here")

print("\nC2  SAME SLOPE, TWO PREDICTORS (per leg, steady state, non-final)")
hdr = "%-30s %3s %8s %8s   %-21s %-21s %-21s"
print(hdr % ("leg", "n", "awk rng", "tot rng", "ai ~ awake", "ai ~ total", "anim ~ awake"))
print("-" * 122)
acc = defaultdict(list)
# Keyed by leg as well as accumulated, because anything PAIRED must be built per leg and
# aggregated last. `acc[k]` drops None fits, so two of its lists can have different lengths and
# pairing them by list index silently aligns different legs. See the C4/C5 note below.
per_leg = {}
for leg in sorted(by):
    v = by[leg]
    aw = [r["awake"] for r in v]
    to = [r["total"] for r in v]
    fits = {
        "ai_aw": ols(aw, [r["ai"] for r in v]),
        "ai_to": ols(to, [r["ai"] for r in v]),
        "an_aw": ols(aw, [r["anim"] for r in v]),
        "an_to": ols(to, [r["anim"] for r in v]),
        "fr_aw": ols(aw, [r["frame"] for r in v]),
        "fr_to": ols(to, [r["frame"] for r in v]),
    }

    def cell(f):
        return "%7.4f +/- %-7.4f" % (f["b"], f["ci"]) if f else "%-21s" % "(x constant)"
    print(hdr % (leg, len(v), "%d-%d" % (min(aw), max(aw)), "%d-%d" % (min(to), max(to)),
                 cell(fits["ai_aw"]), cell(fits["ai_to"]), cell(fits["an_aw"])))
    per_leg[leg] = fits
    for k, f in fits.items():
        if f:
            acc[k].append(f)

print("\n    medians across legs (ms per +1 bot)")
for k, label in (("ai_aw", "aiTotal  ~ awake"), ("ai_to", "aiTotal  ~ total"),
                 ("an_aw", "animBeg  ~ awake"), ("an_to", "animBeg  ~ total"),
                 ("fr_aw", "frame    ~ awake"), ("fr_to", "frame    ~ total")):
    f = acc[k]
    if not f:
        continue
    excl = sum(1 for x in f if x["b"] - x["ci"] > 0)
    print("      %-18s %8.4f   legs %2d, slope CI excludes zero in %d, median R2 %.2f"
          % (label, med([x["b"] for x in f]), len(f), excl, med([x["r2"] for x in f])))

print("\nC3  DOES A SLEEPING BOT COST THE SAME AT THE BRAIN?")
print("    If the brain ticks everyone, aiTotal tracks TOTAL at least as well as AWAKE.")
ai_aw_r2, ai_to_r2 = med([x["r2"] for x in acc["ai_aw"]]), med([x["r2"] for x in acc["ai_to"]])
print("    median R2   aiTotal~awake %.3f   aiTotal~total %.3f" % (ai_aw_r2, ai_to_r2))
cs = [c for c in (corr([r["awake"] for r in by[l]], [r["asleep"] for r in by[l]])
                  for l in sorted(by)) if c is not None]
print("    within-leg corr(awake, asleep): median %.2f over %d legs" % (med(cs), len(cs)))
print("    (strongly negative => awake and asleep are near-redundant given total, so a")
print("     joint two-predictor fit is ill-conditioned and is NOT reported here)")

def paired(k1, k2, op):
    """op(fit1.b, fit2.b) per LEG, then the median. Never op on two medians.

    FIXED 2026-07-30. This block previously summed and divided medians taken across legs -
    med(an_aw) + med(ai_aw), and an/ai as a ratio of two medians. Both are the aggregation-order
    defect: the two slopes are fitted on the SAME legs, so they are paired, and a sum or ratio of
    two medians need not be attained by any leg that happened. It is also the exact error already
    written into my own notes on 2026-07-29 (a +0.457 animation-family delta that was +0.394 built
    per window) - the lesson was recorded and this instance was left standing in the file named
    `recheck-slope`. Recording a rule is not applying it.

    Pairing is by LEG NAME, not list index, because `acc[k]` omits None fits and two of its lists
    can therefore be different lengths - which would align different legs and never complain.
    """
    vals, dropped = [], 0
    for leg, f in per_leg.items():
        a, b = f.get(k1), f.get(k2)
        if not a or not b:
            dropped += 1
            continue
        try:
            vals.append(op(a["b"], b["b"]))
        except ZeroDivisionError:
            dropped += 1
    return (med(vals) if vals else None), len(vals), dropped


print("\nC4  THE +10 BOT CONSEQUENCE, UNDER EACH ESTIMATOR")
base = med([r["frame"] for r in rows])
print("    baseline median frame %.2f ms (%.1f fps)" % (base, 1000.0 / base))
sum_aw, n_aw, d_aw = paired("an_aw", "ai_aw", lambda a, b: a + b)
sum_to, n_to, d_to = paired("an_to", "ai_to", lambda a, b: a + b)
rows_out = [("frame~awake (Delta disowns this one as confounded)",
             med([x["b"] for x in acc["fr_aw"]]), len(acc["fr_aw"]), 0),
            ("animBegin + aiTotal, both ~awake (the bot-driven phases)", sum_aw, n_aw, d_aw),
            ("animBegin + aiTotal, both ~total", sum_to, n_to, d_to)]
for label, slope, n, dropped in rows_out:
    if slope is None:
        print("      %-56s (no leg carries both fits)" % label)
        continue
    new = base + 10.0 * slope
    print("      %-56s %5.3f ms/bot -> %5.2f ms (%.1f fps)   legs %d%s"
          % (label, slope, new, 1000.0 / new, n,
             ", %d dropped" % dropped if dropped else ""))

# What the old estimator said, kept visible so the size of the defect is on the record rather
# than quietly corrected away. If these two lines ever agree, that is luck and not validation -
# on one of our two legs an identical aggregation-order error agreed to 0.001 ms.
old_aw = med([x["b"] for x in acc["an_aw"]]) + med([x["b"] for x in acc["ai_aw"]])
old_to = med([x["b"] for x in acc["an_to"]]) + med([x["b"] for x in acc["ai_to"]])
print("    aggregation-order check (sum of medians, the WRONG form, for size only):")
print("      ~awake  wrong %.4f  vs paired %.4f  = %+.4f ms/bot (%+.2f ms at +10 bots)"
      % (old_aw, sum_aw, old_aw - sum_aw, 10.0 * (old_aw - sum_aw)) if sum_aw else "")
print("      ~total  wrong %.4f  vs paired %.4f  = %+.4f ms/bot (%+.2f ms at +10 bots)"
      % (old_to, sum_to, old_to - sum_to, 10.0 * (old_to - sum_to)) if sum_to else "")

print("\nC5  ANIMATION : AI RATIO, per leg then aggregated")
for pred, k_an, k_ai in (("awake", "an_aw", "ai_aw"), ("total", "an_to", "ai_to")):
    r, n, dropped = paired(k_an, k_ai, lambda a, b: a / b)
    wrong = (med([x["b"] for x in acc[k_an]]) / med([x["b"] for x in acc[k_ai]])
             if acc[k_ai] and med([x["b"] for x in acc[k_ai]]) else None)
    if r is None:
        print("    on the %-5s predictor: no leg carries both fits" % pred)
        continue
    print("    on the %-5s predictor: %.1fx   (legs %d%s)"
          % (pred, r, n, ", %d dropped" % dropped if dropped else ""))
    if wrong:
        print("      ratio-of-medians, the wrong form, would say %.1fx" % wrong)
