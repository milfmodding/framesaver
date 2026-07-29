"""What fraction of `aiTotal` is the brain tick?

`aiTotal` times BotsController.method_0, which calls AICoreController.Update()
alongside four siblings (ArtilleryZones, BotSmokesVision, AiTaskManager,
Bots.UpdateByUnity, EventsController). The A/B's effect size depends on the
brain tick's SHARE of that, which nobody has measured.

Method: within a map, regress aiTotal.avg on agents.live. The brain tick walks
`live` agents, so its cost scales with `live`; a component that does not scale
lands in the intercept. Then brainShare ~= slope * live / aiTotal.

WITHIN MAP ONLY, and that is not a stylistic preference. Pooling this exact
shape across maps is what produced the withdrawn per-bot slope - 0.623 pooled
against Factory's +0.101 at r=0.16. Every map is reported separately and they
are never averaged.

UPPER BOUND, not an estimate: `Bots.UpdateByUnity` also scales with bot count,
so the slope credits the brain tick with cost that is not its own. Every
assumption pushes the same way, which makes it safe to argue against the
experiment and unsafe to argue for it.
"""
import json
import glob
import sys
from collections import defaultdict

LOGS = sys.argv[1:] or sorted(glob.glob(
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*.ndjson"))
MIN_N = 8

acc = defaultdict(list)
for path in LOGS:
    for ln in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "sample" or o.get("state") != "raid":
            continue
        ai = (o.get("aiTotal") or {}).get("avg")
        live = (o.get("agents") or {}).get("live")
        if ai is None or not live:
            continue
        acc[str(o.get("map"))].append((float(live), float(ai)))


def ols(pts):
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    syy = sum((p[1] - my) ** 2 for p in pts)
    if sxx == 0 or syy == 0:
        return None
    b = sxy / sxx
    return {"slope": b, "intercept": my - b * mx, "r": sxy / (sxx * syy) ** 0.5,
            "n": n, "mx": mx, "my": my}


print("aiTotal.avg vs agents.live, WITHIN MAP. Never pooled.\n")
print("%-16s %4s %7s %7s %10s %10s %8s   %s" %
      ("map", "n", "live", "aiTot", "slope", "intercept", "r", "brain share (upper)"))
print("-" * 96)
for m in sorted(acc, key=lambda k: -len(acc[k])):
    pts = acc[m]
    if len(pts) < MIN_N:
        print("%-16s %4d   -- too few windows to fit --" % (m, len(pts)))
        continue
    f = ols(pts)
    if not f:
        print("%-16s %4d   -- no variance in live --" % (m, len(pts)))
        continue
    share = f["slope"] * f["mx"] / f["my"] if f["my"] else float("nan")
    print("%-16s %4d %7.1f %7.3f %10.5f %10.4f %8.2f   %5.0f%%%s" %
          (m, f["n"], f["mx"], f["my"], f["slope"], f["intercept"], f["r"],
           100.0 * share,
           "  <- weak fit, do not use" if abs(f["r"]) < 0.4 else ""))

print("\nRead the r column first. A share computed off a slope with r ~ 0.1 is")
print("noise wearing a percentage sign - that is how the per-bot slope went")
print("wrong, and the fix was per-map fits, not a better estimator.")
