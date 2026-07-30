"""How long does raid warm-up actually last? WARMUP_S = 120 was inherited, never derived.

Gamma found that a SECONDS threshold is not window-length neutral. `raidElapsed` is stamped at the
window close, so at 60 s windows the values cluster near 60/120/180 and `>= 120` discards exactly the
window covering 0-60 s. At 30 s windows the same threshold discards the windows closing at 31, 61 and
91 - so the kept data starts at 90 s instead of 60 s. **The steady-state population moves 30 s
without anyone editing the constant.**

They offered two options: leave it, or express the discard in WINDOWS instead of seconds. Both are
conventions, and choosing between conventions is only necessary because the underlying question was
never asked:

    how long does the raid actually take to settle?

If it settles inside the first window, a one-window rule is right and 120 s is over-discarding at
every length. If it takes two minutes, then seconds are the honest unit and the window-based rule
would under-discard at 30 s. The answer decides the convention instead of the convention deciding
the answer.

WHY THIS IS NOT CIRCULAR. It measures frame time against elapsed raid time using ALL in-raid windows
including the ones warm-up would exclude - the excluded population is the subject, so it cannot be
filtered by the thing under test. That is the trap in asking a steady-state question with a
steady-state filter applied.

WHAT WOULD MAKE IT INCONCLUSIVE, named first: if per-window frame time never settles, or if the
early-window elevation is smaller than the between-leg spread, then no threshold is derivable from
this corpus and 120 stays a convention that must simply be declared. That is a real possible answer.
"""
import glob
import json
import os
from collections import defaultdict

LOG = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return float("nan")
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


# Per leg: the ordered sequence of (raidElapsed, frame.avg, worst) for in-raid windows, so early
# windows can be compared against that SAME leg's later baseline. Cross-leg levels differ by map and
# roster, so an absolute threshold pooled across legs would measure the map mix, not warm-up.
legs = defaultdict(list)
for path in sorted(glob.glob(os.path.join(LOG, "framesaver-*.ndjson"))):
    stem = os.path.basename(path).replace("framesaver-", "").replace(".ndjson", "")
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "sample" or o.get("state") != "raid":
            continue
        fr = o.get("frame") or {}
        if fr.get("avg") is None:
            continue
        legs[(stem, o.get("raid"), str(o.get("map")))].append(
            (o.get("raidElapsed") or 0.0, fr["avg"], fr.get("max"), bool(o.get("final"))))

print("WHERE raidElapsed ACTUALLY LANDS, to confirm the boundary-clustering claim")
allel = sorted(e for v in legs.values() for e, _a, _m, _f in v)
buckets = defaultdict(int)
for e in allel:
    buckets[int(e // 30) * 30] += 1
for lo in sorted(buckets)[:8]:
    print("    raidElapsed %3d-%3d s : %3d windows" % (lo, lo + 29, buckets[lo]))
print()

# Within-leg ratio of each early window to that leg's own late baseline. Legs with fewer than 5
# in-raid windows cannot supply a baseline and are skipped rather than pooled.
print("EACH EARLY WINDOW vs ITS OWN LEG'S LATER BASELINE (median of windows past 180 s)")
print("  ordinal  n legs   median frame ratio   median worst-frame ratio")
by_ord = defaultdict(list)
by_ord_worst = defaultdict(list)
for key, rows in legs.items():
    rows = [r for r in rows if not r[3]]           # drop `final`; it is truncated
    if len(rows) < 5:
        continue
    late = [a for e, a, _m, _f in rows if e >= 180.0]
    late_w = [m for e, _a, m, _f in rows if e >= 180.0 and m]
    if len(late) < 2:
        continue
    base, base_w = median(late), (median(late_w) if late_w else None)
    if not base:
        continue
    for i, (e, a, m, _f) in enumerate(rows[:4]):
        by_ord[i].append(a / base)
        if m and base_w:
            by_ord_worst[i].append(m / base_w)
for i in sorted(by_ord):
    w = by_ord_worst.get(i) or []
    print("  window %d  %4d      %6.3f x            %s"
          % (i + 1, len(by_ord[i]), median(by_ord[i]),
             ("%6.2f x" % median(w)) if w else "n/a"))

print()
print("READ IT AS: a ratio near 1.000 means that window was already at the leg's own steady level,")
print("so discarding it costs data and buys nothing. The WORST-frame column is the one warm-up")
print("actually damages - a mean can look settled while the tail has not.")
print()
print("The decision this informs: if only window 1 is elevated, the honest rule is ONE WINDOW, which")
print("is stable across window lengths and matches the stated intent ('skip each leg's raid-init")
print("window'). If elevation persists into window 2 at 60 s, then the real warm-up is ~120 s and")
print("SECONDS is the honest unit - in which case 30 s windows must discard four, not three, and the")
print("current threshold under-discards rather than over-discards.")
