"""Two questions the corpus can answer without a raid.

A. What is the BETWEEN-RAID noise floor on FinishFrameRendering? The garment
   manipulation is necessarily between-raid - the pool is written at template load -
   so its power is set by how much this component moves between unmanipulated legs
   of the same map, not by the size of the dose. Measure that directly.

B. Does playerLate carry the corpse signature? Corpses stay Players, so they keep
   taking LateUpdate, and bots.total counts LIVE bots only - verified, it DECLINES
   within every leg. So a corpse-driven cost RISES while every population predictor
   we own FALLS. That is a sign test, not a magnitude test, and it needs no new field:

     playerLate rising against raidElapsed while bots.total falls -> corpse-shaped
     playerLate tracking bots.total                               -> population, not corpses
"""
import json
import glob
import sys
from collections import defaultdict

LOGS = sys.argv[1:] or sorted(glob.glob(
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson"))
STEADY = 120.0
REND = "PostLateUpdate/FinishFrameRendering"

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
        m = str(o.get("map"))
        if m != prev:
            prev, leg = m, leg + 1
        if o.get("final") or (o.get("raidElapsed") or 0) < STEADY:
            continue
        b = o.get("bots") or {}
        rows.append({
            "key": "%s|L%d|%s" % (m, leg, path[-18:-7]), "map": m,
            "elapsed": o.get("raidElapsed") or 0.0,
            "late": (o.get("playerLate") or {}).get("avg") or 0.0,
            "rend": ((o.get("phases") or {}).get(REND) or {}).get("avg") or 0.0,
            "total": b.get("total") or 0, "awake": b.get("awake") or 0,
        })

by = defaultdict(list)
for r in rows:
    by[r["key"]].append(r)


def med(xs):
    s = sorted(xs)
    n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


def ols(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-9:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    resid = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    return b, 1.96 * (resid / (n - 2) / sxx) ** 0.5, n


# ---- A. between-raid noise floor -----------------------------------------
print("A. BETWEEN-RAID NOISE FLOOR  (same map, different legs, no manipulation)\n")
bymap = defaultdict(list)
for k, v in by.items():
    bymap[v[0]["map"]].append((k, med([r["rend"] for r in v]), med([r["late"] for r in v])))
print("  %-16s %28s %28s" % ("map", "FinishFrameRendering", "playerLate"))
dr, dl = [], []
for m in sorted(bymap):
    v = bymap[m]
    if len(v) < 2:
        continue
    rs = [x[1] for x in v]
    ls = [x[2] for x in v]
    print("  %-16s %8s -> %-8s d=%-6.3f %8s -> %-8s d=%.3f"
          % (m, "%.3f" % min(rs), "%.3f" % max(rs), max(rs) - min(rs),
             "%.3f" % min(ls), "%.3f" % max(ls), max(ls) - min(ls)))
    dr.append(max(rs) - min(rs))
    dl.append(max(ls) - min(ls))
if dr:
    print("\n  median |delta| between legs of one map:  rendering %.3f ms   playerLate %.3f ms"
          % (med(dr), med(dl)))
    print("  A between-raid A/B cannot resolve an effect smaller than this.")

# ---- B. the corpse signature ---------------------------------------------
print("\n\nB. DOES playerLate RISE WHILE bots.total FALLS?\n")
print("  %-26s %4s %22s %22s %14s" %
      ("leg", "n", "late ~ elapsed (ms/min)", "late ~ total (ms/bot)", "total trend"))
up = down = 0
for k in sorted(by):
    v = sorted(by[k], key=lambda r: r["elapsed"])
    fe = ols([r["elapsed"] / 60.0 for r in v], [r["late"] for r in v])
    ft = ols([r["total"] for r in v], [r["late"] for r in v])
    tt = ols([r["elapsed"] / 60.0 for r in v], [float(r["total"]) for r in v])
    if not fe:
        continue
    sig = fe[0] - fe[1] > 0
    if sig:
        up += 1
    if fe[0] + fe[1] < 0:
        down += 1
    print("  %-26s %4d %10.4f +/- %-8.4f %s %10.4f +/- %-8.4f %+9.2f bots/min"
          % (k.split("|")[0][:24] + "|" + k.split("|")[1], fe[2], fe[0], fe[1],
             "RISE" if sig else "    ",
             ft[0] if ft else 0, ft[1] if ft else 0, tt[0] if tt else 0))
print("\n  legs where playerLate significantly RISES with time-in-raid: %d" % up)
print("  legs where it significantly FALLS:                            %d" % down)
print("\n  Corpse-shaped requires RISE while bots.total trends down. Read both columns.")
