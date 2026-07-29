"""Intervals on the component table. Delta rule: a number that ranks other work carries an
interval or it does not get to rank anything - and I published that table without one.

Delta bootstrap puts the STANDARDISED residual at -1.695..3.991, containing zero, with the
width dominated by the bot-count slope. The question this answers is different and narrower:
are the RAW between-leg component deltas - which involve no slope and no standardisation -
distinguishable from zero at this n?

Moving-block bootstrap, block 3 windows, because adjacent 60 s windows in one raid are
autocorrelated and an i.i.d. resample would understate every interval.
"""
import json, glob, os, random, statistics as st
from collections import defaultdict

random.seed(20260729)          # fixed: Date/random are not available in some contexts and
B = 4000                       # a moving target here would make this unreproducible
BLOCK = 3

rows = []
for path in sorted(glob.glob(r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson")):
    stem = os.path.basename(path).split("-marathon")[0].replace("framesaver-", "")
    leg, prev = 0, None
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        try: o = json.loads(ln)
        except ValueError: continue
        if o.get("type") != "sample" or o.get("state") != "raid": continue
        m = str(o.get("map") or "?")
        if m != prev: prev, leg = m, leg + 1
        if o.get("final") or (o.get("raidElapsed") or 0) < 120: continue
        rows.append((("%s %s L%d" % (stem, m, leg)), o))

by = defaultdict(list)
for k, o in rows: by[k].append(o)
lh = [k for k in sorted(by) if "Lighthouse" in k and len(by[k]) >= 5]
a, b = lh

COMP = [
    ("frame.avg (the raw gap)",        lambda o: (o.get("frame") or {}).get("avg")),
    ("rendering FinishFrameRendering", lambda o: (o.get("phases") or {}).get("PostLateUpdate/FinishFrameRendering", {}).get("avg")),
    ("animation Begin+End",            lambda o: sum((o.get("phases") or {}).get(p, {}).get("avg") or 0.0
                                                     for p in ("PreLateUpdate/DirectorUpdateAnimationBegin",
                                                               "PreLateUpdate/DirectorUpdateAnimationEnd"))),
    ("script Update",                  lambda o: (o.get("phases") or {}).get("Update/ScriptRunBehaviourUpdate", {}).get("avg")),
    ("script LateUpdate",              lambda o: (o.get("phases") or {}).get("PreLateUpdate/ScriptRunBehaviourLateUpdate", {}).get("avg")),
    ("playerLate",                     lambda o: (o.get("playerLate") or {}).get("avg")),
    ("aiTotal",                        lambda o: (o.get("aiTotal") or {}).get("avg")),
    ("coroutines DelayedDynamicFR",    lambda o: (o.get("phases") or {}).get("Update/ScriptRunDelayedDynamicFrameRate", {}).get("avg")),
    ("particles",                      lambda o: (o.get("phases") or {}).get("PreLateUpdate/ParticleSystemBeginUpdateAll", {}).get("avg")),
]
GROUPS = [x for x in (set(k for o in by[a] for k in (o.get("phases") or {}) if "/" not in k)) ]

def series(k, f):
    return [v for v in (f(o) for o in by[k]) if v is not None]

def blocks(v, n):
    out = []
    while len(out) < n:
        i = random.randrange(0, max(1, len(v) - BLOCK + 1))
        out.extend(v[i:i + BLOCK])
    return out[:n]

def boot_diff(va, vb):
    d = st.median(vb) - st.median(va)
    reps = sorted(st.median(blocks(vb, len(vb))) - st.median(blocks(va, len(va))) for _ in range(B))
    return d, reps[int(0.025 * B)], reps[int(0.975 * B)]

print("RAW between-leg component deltas, moving-block bootstrap 95%% (B=%d, block=%d)\n" % (B, BLOCK))
print("  %-34s %8s  %-20s %s" % ("component", "delta", "95% interval", ""))
print("  " + "-" * 76)
for name, f in COMP:
    va, vb = series(a, f), series(b, f)
    if len(va) < 5 or len(vb) < 5:
        print("  %-34s   (too few windows)" % name); continue
    d, lo, hi = boot_diff(va, vb)
    excl = "EXCLUDES ZERO" if (lo > 0 or hi < 0) else "contains zero"
    print("  %-34s %+8.3f  [%+.3f, %+.3f]  %s" % (name, d, lo, hi, excl))

# The unaccounted row, computed per window so it gets an interval like everything else.
def unacc(o):
    ph = o.get("phases") or {}
    fr = (o.get("frame") or {}).get("avg")
    if fr is None: return None
    return fr - sum((ph.get(g) or {}).get("avg") or 0.0 for g in GROUPS if "/" not in g)
va, vb = series(a, unacc), series(b, unacc)
d, lo, hi = boot_diff(va, vb)
print("  %-34s %+8.3f  [%+.3f, %+.3f]  %s" % ("outside every player-loop group", d, lo, hi,
      "EXCLUDES ZERO" if (lo > 0 or hi < 0) else "contains zero"))
