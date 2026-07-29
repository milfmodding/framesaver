"""Is the residual TEMPORAL (drift) or BETWEEN-RAID (content)? It decides a recommendation
already sent to Sophia.

Delta's discriminator: framePct.p50 against raidElapsed WITHIN a leg.
  monotone within legs                  -> temporal. Time-ordering control is needed and
                                           it displaces the design work.
  flat within legs, different between    -> raid content. A random effect between raids,
                                           fixed by within-raid arms, which is already the plan.

Two things Delta's framing does not guard against, both handled here.

1. WITHIN A LEG, TIME AND POSITION ARE CONFOUNDED. raidElapsed rises as the player walks
   somewhere else, and Delta has just shown position is worth ~1.15 ms on this very map. A
   positive time slope is therefore NOT sufficient for "temporal". So the awake-bot count is
   carried as a second predictor: if the time slope survives controlling for it, that is
   evidence the clock matters beyond what the player was doing.

2. A SLOPE PER LEG IS A SAMPLE OF ONE PER LEG. Reported per leg with its CI and pooled, and
   the pooled test is a SIGN test on the per-leg slopes rather than a mean of them, because
   the question is "do legs agree on a direction" and one steep leg should not decide it.

Refuses to report on fewer than 4 legs.
"""
import json
import glob
import os
import sys
from collections import defaultdict

LOGS = sys.argv[1:] or sorted(glob.glob(
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson"))
STEADY = 120.0

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
            p50 = (o.get("framePct") or {}).get("p50")
            if p50 is None:
                continue
            rows.append({"leg": "%s %s L%d" % (stem, m, leg),
                         "t": (o.get("raidElapsed") or 0.0) / 60.0,
                         "p50": p50,
                         "awake": (o.get("bots") or {}).get("awake") or 0})

by = defaultdict(list)
for r in rows:
    by[r["leg"]].append(r)
usable = {k: v for k, v in by.items() if len(v) >= 5}
if len(usable) < 4:
    print("only %d legs with >=5 steady-state windows - refusing to report" % len(usable))
    sys.exit(2)


def ols1(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-9:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    resid = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if n <= 2:
        return None
    return {"b": b, "ci": 1.96 * (resid / (n - 2) / sxx) ** 0.5,
            "r2": 0.0 if syy <= 1e-12 else max(0.0, 1.0 - resid / syy)}


def ols2(x1, x2, ys):
    """Slope on x1 controlling for x2, via residualising x1 on x2 (Frisch-Waugh)."""
    f = ols1(x2, x1)
    if f is None:
        return None
    n = len(x1)
    m2 = sum(x2) / n
    m1 = sum(x1) / n
    a = m1 - f["b"] * m2
    r1 = [v - (a + f["b"] * w) for v, w in zip(x1, x2)]
    if sum(v * v for v in r1) <= 1e-9:
        return None
    return ols1(r1, ys)


print("WITHIN-LEG TIME TREND in framePct.p50 (ms per minute of raidElapsed)\n")
print("%-30s %3s %9s %-22s %-22s" % ("leg", "n", "span min", "p50 ~ time", "p50 ~ time | awake"))
print("-" * 92)
raw, ctl = [], []
for leg in sorted(usable):
    v = sorted(usable[leg], key=lambda r: r["t"])
    ts = [r["t"] for r in v]
    ys = [r["p50"] for r in v]
    aw = [float(r["awake"]) for r in v]
    f1, f2 = ols1(ts, ys), ols2(ts, aw, ys)

    def cell(f):
        if not f:
            return "%-22s" % "(degenerate)"
        star = "*" if f["b"] - f["ci"] > 0 or f["b"] + f["ci"] < 0 else " "
        return "%7.3f +/- %-7.3f %s" % (f["b"], f["ci"], star)
    print("%-30s %3d %9.1f %s %s"
          % (leg, len(v), max(ts) - min(ts), cell(f1), cell(f2)))
    if f1:
        raw.append(f1)
    if f2:
        ctl.append(f2)

print("\n(* = CI excludes zero)")


def signtest(fits, label):
    pos = sum(1 for f in fits if f["b"] > 0)
    n = len(fits)
    sig = sum(1 for f in fits if f["b"] - f["ci"] > 0)
    signeg = sum(1 for f in fits if f["b"] + f["ci"] < 0)
    s = sorted(f["b"] for f in fits)
    print("  %-22s %2d legs, %2d positive, %2d significantly up, %2d significantly DOWN, median %+.3f"
          % (label, n, pos, sig, signeg, s[n // 2]))


print("\nPOOLED SIGN TEST - do legs agree on a direction?")
signtest(raw, "p50 ~ time")
signtest(ctl, "p50 ~ time | awake")

print("""
READING THE RESULT
  Most legs positive and several significant     -> temporal. Drift control leads, and the
                                                    recommendation already sent stands.
  Split roughly evenly around zero               -> NOT temporal within a raid. The between-leg
                                                    gap is a raid-level random effect, i.e.
                                                    content, and within-raid arms already fix it.
                                                    The sent recommendation needs correcting.""")
