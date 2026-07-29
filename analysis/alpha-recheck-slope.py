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

print("\nC4  THE +10 BOT CONSEQUENCE, UNDER EACH ESTIMATOR")
base = med([r["frame"] for r in rows])
print("    baseline median frame %.2f ms (%.1f fps)" % (base, 1000.0 / base))
for label, slope in (("frame~awake (Delta disowns this one as confounded)",
                      med([x["b"] for x in acc["fr_aw"]])),
                     ("animBegin + aiTotal, both ~awake (the bot-driven phases)",
                      med([x["b"] for x in acc["an_aw"]]) + med([x["b"] for x in acc["ai_aw"]])),
                     ("animBegin + aiTotal, both ~total",
                      med([x["b"] for x in acc["an_to"]]) + med([x["b"] for x in acc["ai_to"]]))):
    new = base + 10.0 * slope
    print("      %-56s %5.3f ms/bot -> %5.2f ms (%.1f fps)"
          % (label, slope, new, 1000.0 / new))

ai, an = med([x["b"] for x in acc["ai_aw"]]), med([x["b"] for x in acc["an_aw"]])
print("\n    animation : AI ratio on the awake predictor = %.1fx" % (an / ai) if ai else "")
ai2, an2 = med([x["b"] for x in acc["ai_to"]]), med([x["b"] for x in acc["an_to"]])
print("    animation : AI ratio on the total predictor = %.1fx" % (an2 / ai2) if ai2 else "")
