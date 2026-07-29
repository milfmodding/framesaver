"""Alpha's component families, standardised on position AND bot count, each with an interval.

He asked me to re-rank his table after standardisation. My own rule from an hour ago -
a number that ranks other work carries an interval or it does not get to rank anything -
applies to the table as much as to the total, so every row gets one.

`unaccounted` is carried as its own row rather than absorbed, at his request: it is the
largest unnamed item and would otherwise disappear into the thing it is 20% of. It is
computed as frame.avg minus the sum of TOP-LEVEL player-loop groups only - keys with no
'/' - because the telemetry emits parents and children together and summing all 145 keys
double-counts, which is the error his own first pass made.

Method as in delta-residual-interval.py: position standardised non-parametrically on Z
bins, bot count adjusted linearly with a LEAVE-ONE-MAP-OUT slope fitted per component,
moving-block bootstrap for the interval. The slope is drawn as the median of resampled
donor legs - the narrower of the two models - so these intervals are the OPTIMISTIC ones.
"""
import json
import glob
import random
from collections import defaultdict

LOGS = sorted(glob.glob(
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson"))
TARGET, STEADY, ZW, BLOCK, NBOOT = "Lighthouse", 120.0, 150.0, 3, 3000

FAMILIES = [
    ("rendering", ["PostLateUpdate/FinishFrameRendering"]),
    ("animation", ["PreLateUpdate/DirectorUpdateAnimationBegin",
                   "PreLateUpdate/DirectorUpdateAnimationEnd"]),
    ("script Update", ["Update/ScriptRunBehaviourUpdate"]),
    ("script LateUpdate", ["PreLateUpdate/ScriptRunBehaviourLateUpdate"]),
    # TWO phases carry this leaf name under different parents - Update/ at 0.46-0.60 ms
    # and PostLateUpdate/ at 0.004. Alpha's row is the Update one; I first took the
    # PostLateUpdate one and got a level of 0.004. Match on the full path, never the leaf.
    ("delayed/dynamic", ["Update/ScriptRunDelayedDynamicFrameRate"]),
    ("particles", ["PreLateUpdate/ParticleSystemBeginUpdateAll"]),
    ("present wait", ["TimeUpdate/WaitForLastPresentationAndUpdateTime"]),
]

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
        ph = o.get("phases") or {}
        z = (o.get("pos") or {}).get("z") or [0, 0]
        r = {"key": "%s|L%d|%s" % (m, leg, path[-18:-7]), "map": m,
             "z": (z[0] + z[1]) / 2.0, "total": (o.get("bots") or {}).get("total") or 0}
        for name, keys in FAMILIES:
            r[name] = sum((ph.get(k) or {}).get("avg") or 0.0 for k in keys)
        frame = (o.get("frame") or {}).get("avg") or 0.0
        groups = sum(v.get("avg") or 0.0 for k, v in ph.items() if "/" not in k)
        r["frame"] = frame
        r["unaccounted"] = frame - groups
        rows.append(r)

by = defaultdict(list)
for r in rows:
    by[r["key"]].append(r)


def med(xs):
    s = sorted(xs)
    n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


def fit(v, fld):
    xs = [r["total"] for r in v]
    ys = [r[fld] for r in v]
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-9:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def blocks(v, rng):
    v = sorted(v, key=lambda r: r["z"])
    n = len(v)
    out = []
    while len(out) < n:
        i = rng.randrange(max(1, n - BLOCK + 1))
        out.extend(v[i:i + BLOCK])
    return out[:n]


def residual(a, b, fld, s):
    ba = defaultdict(list)
    for r in a:
        ba[int(r["z"] // ZW)].append(r[fld])
    hits = [med(ba[int(r["z"] // ZW)]) for r in b if int(r["z"] // ZW) in ba]
    if not hits:
        return None
    dtot = med([r["total"] for r in b]) - med([r["total"] for r in a])
    return med([r[fld] for r in b]) - (sum(hits) / len(hits) + s * dtot)


ks = sorted(k for k in by if by[k][0]["map"] == TARGET)
A, B = by[ks[0]], by[ks[-1]]
rng = random.Random(20260729)

print("LIGHTHOUSE L1 -> L4, families standardised on position AND bot count\n")
print("  %-18s %8s %8s %9s %22s" % ("family", "level B", "raw d", "std d", "95% interval"))
print("  " + "-" * 70)

out = []
for name in [f[0] for f in FAMILIES] + ["unaccounted", "frame"]:
    donors = [fit(v, name) for k, v in by.items() if v[0]["map"] != TARGET]
    donors = [d for d in donors if d is not None]
    if not donors:
        continue
    raw = med([r[name] for r in B]) - med([r[name] for r in A])
    pt = residual(A, B, name, med(donors))
    boot = []
    for _ in range(NBOOT):
        s = med([donors[rng.randrange(len(donors))] for _ in range(len(donors))])
        r = residual(blocks(A, rng), blocks(B, rng), name, s)
        if r is not None:
            boot.append(r)
    boot.sort()
    lo, hi = boot[int(0.025 * len(boot))], boot[int(0.975 * len(boot))]
    out.append((name, med([r[name] for r in B]), raw, pt, lo, hi))

for name, lvl, raw, pt, lo, hi in out:
    star = "" if lo <= 0 <= hi else "  EXCLUDES 0"
    print("  %-18s %8.3f %8.3f %9.3f   %7.3f .. %7.3f%s"
          % (name, lvl, raw, pt, lo, hi, star))

print("\n  Verifying Alpha's unaccounted row:")
for lbl, v in (("L1", A), ("L4", B)):
    gs = med([r["frame"] - r["unaccounted"] for r in v])
    print("    %s  groups %7.3f   frame %7.3f   unaccounted %+7.3f"
          % (lbl, gs, med([r["frame"] for r in v]), med([r["unaccounted"] for r in v])))

n_excl = sum(1 for _, _, _, _, lo, hi in out if not (lo <= 0 <= hi))
print("\n  families whose standardised delta excludes zero: %d of %d" % (n_excl, len(out)))
print("  These are the OPTIMISTIC intervals (shared-slope model). The map-specific")
print("  model is roughly 2.5x wider, and no row survives it.")
