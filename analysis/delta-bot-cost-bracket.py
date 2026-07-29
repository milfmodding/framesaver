"""Bracket the marginal bot, and check whether the anim slope survives its own intercept.

Alpha is right that my headline used the frame slope I had just told him to discard.
But his replacement - the sum of the two bot-driven phases - is a LOWER bound, not
a corrected estimate: a bot also costs playerLate, playerTick and physics. Swapping
an over-estimate for an under-estimate is not a fix, it is the same error mirrored.

So: name every bot-attributable component that is separately timed, sum the slopes,
and report the pair as a BRACKET. Also regress on bots.total, which does not track
player proximity the way awake does and is the right predictor for "raise the raid
population" anyway.

Third check, which is the one that decides whether the anim slope is even usable:
slope x mean(awake) must be LESS than mean(anim level), because animation also has a
player-and-scenery intercept that cannot be negative. If it is not, the slope is
inflated and the ratio built on it is too.
"""
import json
import glob
import sys
from collections import defaultdict

LOGS = sys.argv[1:] or sorted(glob.glob(
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson"))
STEADY = 120.0
ANIM = "PreLateUpdate/DirectorUpdateAnimationBegin"
# Separately timed and bot-attributable. Rendering phases are deliberately excluded:
# they are real bot cost but inseparable from player proximity, which is the confound.
COMPONENTS = ("ai", "anim", "late", "tick")

rows = []
for path in LOGS:
    leg, prev = 0, None
    for ln in open(path, encoding="utf-8", errors="replace"):
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
            # Key on the file too: merging two sessions into one leg reintroduces the
            # drift confound the within-leg design exists to remove. Alpha's catch.
            "leg": "%s L%d %s" % (m, leg, path[-18:-7]),
            "awake": b.get("awake") or 0,
            "total": b.get("total") or 0,
            "asleep": b.get("asleep") or 0,
            "frame": (o.get("frame") or {}).get("avg") or 0.0,
            "ai": (o.get("aiTotal") or {}).get("avg") or 0.0,
            "anim": (ph.get(ANIM) or {}).get("avg") or 0.0,
            "late": (o.get("playerLate") or {}).get("avg") or 0.0,
            "tick": (o.get("playerTick") or {}).get("avg") or 0.0,
        })


def ols(xs, ys):
    n = len(xs)
    if n < 4:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-9:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    resid = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    se = (resid / (n - 2) / sxx) ** 0.5
    return {"b": b, "a": a, "ci": 1.96 * se, "n": n, "mx": mx, "my": my}


by = defaultdict(list)
for r in rows:
    by[r["leg"]].append(r)


def med(xs):
    s = sorted(xs)
    return s[len(s) // 2] if s else 0.0


print("legs: %d, windows: %d\n" % (len(by), len(rows)))

# ---- 1. the bracket -------------------------------------------------------
per_leg = {}
for leg, v in by.items():
    xs = [r["awake"] for r in v]
    fits = {f: ols(xs, [r[f] for r in v]) for f in COMPONENTS}
    ffit = ols(xs, [r["frame"] for r in v])
    tfit = ols([r["total"] for r in v], [r["frame"] for r in v])
    if not ffit or any(fits[f] is None for f in COMPONENTS):
        continue
    per_leg[leg] = {"frame": ffit, "total": tfit, **fits}

print("MARGINAL BOT, ms per +1 bot (median over %d legs)\n" % len(per_leg))
print("  %-28s %10s" % ("component (~awake)", "slope"))
comp_sum = 0.0
for f in COMPONENTS:
    s = med([per_leg[l][f]["b"] for l in per_leg])
    comp_sum += s
    print("  %-28s %10.4f" % (f, s))
print("  %-28s %10.4f   <- Alpha's figure, a LOWER bound" % ("sum of named components", comp_sum))
fslope = med([per_leg[l]["frame"]["b"] for l in per_leg])
print("  %-28s %10.4f   <- my figure, an UPPER bound" % ("whole frame ~awake", fslope))
tslope = med([per_leg[l]["total"]["b"] for l in per_leg if per_leg[l]["total"]])
print("  %-28s %10.4f   <- population predictor" % ("whole frame ~total", tslope))

base = med([r["frame"] for r in rows])
print("\n  +10 bots from a %.2f ms frame (%.1f fps):" % (base, 1000.0 / base))
for lbl, s in (("lower (components)", comp_sum), ("population (~total)", tslope),
               ("upper (frame~awake)", fslope)):
    nf = base + 10 * s
    print("    %-22s %6.2f ms  %5.1f fps  %s"
          % (lbl, nf, 1000.0 / nf, "GATE" if 1000.0 / nf < 60 else ""))

# ---- 2. does the anim slope survive its own intercept? --------------------
print("\nINTERCEPT CHECK  (slope x mean(awake) must be < mean level; the rest is player+scenery)\n")
print("  %-14s %8s %8s %9s %9s %9s" % ("leg", "meanAwk", "slope", "predicted", "meanLevel", "intercept"))
bad = 0
for leg in sorted(per_leg):
    f = per_leg[leg]["anim"]
    pred = f["b"] * f["mx"]
    flag = ""
    if f["a"] < 0:
        bad += 1
        flag = "  <- NEGATIVE intercept"
    print("  %-14s %8.1f %8.4f %9.3f %9.3f %9.3f%s"
          % (leg.split()[0][:14], f["mx"], f["b"], pred, f["my"], f["a"], flag))
print("\n  legs with a negative animation intercept: %d of %d" % (bad, len(per_leg)))

# ---- 3. how much of the animation cost is even reachable? ----------------
print("\nREACHABILITY  (rule 5 can only touch bots that are awake; asleep are already culled)\n")
print("  median awake %.1f, asleep %.1f, total %.1f"
      % (med([r["awake"] for r in rows]), med([r["asleep"] for r in rows]),
         med([r["total"] for r in rows])))
print("  median animBegin level      %.3f ms" % med([r["anim"] for r in rows]))
print("  median aiTotal level        %.3f ms" % med([r["ai"] for r in rows]))
print("  anim slope x median awake   %.3f ms  <- ceiling on rule 5, if every awake bot were cullable"
      % (med([per_leg[l]["anim"]["b"] for l in per_leg]) * med([r["awake"] for r in rows])))
print("\n  LEVEL ratio anim/ai         %.2fx   (assumption-free, no noisy denominator)"
      % (med([r["anim"] for r in rows]) / med([r["ai"] for r in rows])))
