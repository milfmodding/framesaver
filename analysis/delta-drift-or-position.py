"""Is the Lighthouse 3.08 ms gap DRIFT, or is it WHERE SHE WAS?

Alpha reads two visits to one map in one session, 69.1 vs 57.0 fps on framePct.p50,
as unexplained within-session drift, and concludes drift control outranks every
design question. The quantity is real. "Drift" is a name that presumes a TEMPORAL
mechanism, and nobody has tested that against the obvious alternative: the two legs
have Z centroids 276 units apart on a map that is long in Z.

Their Z spans overlap heavily, so windows can be matched by location and the gap
recomputed within matched bins. Two outcomes, both decisive:

  gap SURVIVES matching -> temporal, Alpha is right, drift control leads
  gap COLLAPSES         -> location, the within-leg ABAB already handles it, and
                           the design questions are not blocked

Also decomposes the gap by component, because a mechanism that moves rendering is a
different mechanism from one that moves game logic.
"""
import json
import sys
from collections import defaultdict

PATH = sys.argv[1] if len(sys.argv) > 1 else \
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-20260728-225956-marathon.ndjson"
MAP = "Lighthouse"
BIN = 100.0  # metres of Z per bin

leg, prev = 0, None
legs = defaultdict(list)
for ln in open(PATH, encoding="utf-8", errors="replace"):
    try:
        o = json.loads(ln)
    except ValueError:
        continue
    if o.get("type") != "sample" or o.get("state") != "raid":
        continue
    m = str(o.get("map"))
    if m != prev:
        prev, leg = m, leg + 1
    if o.get("final") or (o.get("raidElapsed") or 0) < 120:
        continue
    if m == MAP:
        legs[leg].append(o)


def med(xs):
    s = sorted(xs)
    if not s:
        return 0.0
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def p50(w):
    return (w.get("framePct") or {}).get("p50") or 0.0


def zc(w):
    z = (w.get("pos") or {}).get("z") or [0, 0]
    return (z[0] + z[1]) / 2.0


ks = sorted(legs)
A, B = legs[ks[0]], legs[ks[-1]]
print("%s: leg%d n=%d vs leg%d n=%d\n" % (MAP, ks[0], len(A), ks[-1], len(B)))

raw = med([p50(w) for w in B]) - med([p50(w) for w in A])
print("UNMATCHED gap  %.3f ms  (%.1f -> %.1f fps)"
      % (raw, 1000.0 / med([p50(w) for w in A]), 1000.0 / med([p50(w) for w in B])))

# ---- matched on Z ---------------------------------------------------------
bins = defaultdict(lambda: ([], []))
for w in A:
    bins[int(zc(w) // BIN)][0].append(w)
for w in B:
    bins[int(zc(w) // BIN)][1].append(w)

print("\nMATCHED ON Z  (%.0f m bins, bins holding windows from BOTH legs)\n" % BIN)
print("  %-16s %6s %6s %9s %9s %9s" % ("Z band", "nA", "nB", "p50 A", "p50 B", "gap"))
gaps, wts = [], []
for b in sorted(bins):
    a, c = bins[b]
    if not a or not c:
        continue
    ga, gb = med([p50(w) for w in a]), med([p50(w) for w in c])
    gaps.append(gb - ga)
    wts.append(min(len(a), len(c)))
    print("  %6.0f..%-8.0f %6d %6d %9.3f %9.3f %9.3f"
          % (b * BIN, (b + 1) * BIN, len(a), len(c), ga, gb, gb - ga))

if gaps:
    wsum = sum(g * w for g, w in zip(gaps, wts)) / sum(wts)
    print("\n  matched bins %d, windows paired %d" % (len(gaps), sum(wts)))
    print("  MATCHED gap  median %.3f ms   weighted %.3f ms" % (med(gaps), wsum))
    print("  DO NOT READ THE MEDIAN. Most bins hold one window per leg, and a single")
    print("  window's p50 is noise; the median over bins weights a 1v1 bin the same as")
    print("  a 6v10 one. Use the standardisation below, which uses every window.")

    # Direct standardisation: leg A's per-band cost, weighted by leg B's exposure.
    # "What would leg A have measured had it walked leg B's route?"
    for width in (100.0, 150.0, 200.0):
        ba, bb = defaultdict(list), defaultdict(list)
        for w in A:
            ba[int(zc(w) // width)].append(p50(w))
        for w in B:
            bb[int(zc(w) // width)].append(p50(w))
        num = den = 0.0
        unmatched = 0
        for b, ws in bb.items():
            if b in ba:
                num += med(ba[b]) * len(ws)
                den += len(ws)
            else:
                unmatched += len(ws)
        if not den:
            continue
        std = num / den
        ra, rb = med([p50(w) for w in A]), med([p50(w) for w in B])
        print("\n  bin %.0f m: leg A %.3f -> %.3f standardised to leg B's route"
              % (width, ra, std))
        print("    gap %.3f -> residual %.3f   position explains %.0f%%   unmatched %d/%d"
              % (rb - ra, rb - std, 100.0 * (1 - (rb - std) / (rb - ra)), unmatched, len(B)))
else:
    print("\n  no overlapping bins - the legs do not share ground, so the gap is")
    print("  NOT ESTIMABLE separately from position with this data")

# ---- what moved -----------------------------------------------------------
def ph(w, k):
    return ((w.get("phases") or {}).get(k) or {}).get("avg") or 0.0


COMP = [
    ("frame.avg", lambda w: (w.get("frame") or {}).get("avg") or 0.0),
    ("gameUpdate", lambda w: (w.get("gameUpdate") or {}).get("avg") or 0.0),
    ("  animBegin", lambda w: ph(w, "PreLateUpdate/DirectorUpdateAnimationBegin")),
    ("  aiTotal", lambda w: (w.get("aiTotal") or {}).get("avg") or 0.0),
    ("  playerLate", lambda w: (w.get("playerLate") or {}).get("avg") or 0.0),
    ("FinishFrameRendering", lambda w: ph(w, "PostLateUpdate/FinishFrameRendering")),
    ("ScriptRunBehaviourUpdate", lambda w: ph(w, "Update/ScriptRunBehaviourUpdate")),
]
print("\nWHAT MOVED  (median, unmatched)\n")
print("  %-26s %9s %9s %9s %7s" % ("component", "leg A", "leg B", "delta", "%ofgap"))
fa = med([(w.get("frame") or {}).get("avg") or 0.0 for w in A])
fb = med([(w.get("frame") or {}).get("avg") or 0.0 for w in B])
fgap = fb - fa
for name, f in COMP:
    a, b = med([f(w) for w in A]), med([f(w) for w in B])
    print("  %-26s %9.3f %9.3f %9.3f %6.0f%%"
          % (name, a, b, b - a, 100.0 * (b - a) / fgap if fgap else 0))

print("\nCONTEXT\n")
for name, f in (("bots.total", lambda w: (w.get("bots") or {}).get("total") or 0),
                ("bots.awake", lambda w: (w.get("bots") or {}).get("awake") or 0),
                ("proc.wsMb", lambda w: (w.get("proc") or {}).get("wsMb") or 0),
                ("proc.notResidentMb", lambda w: (w.get("proc") or {}).get("notResidentMb") or 0),
                ("proc.faultsDelta", lambda w: (w.get("proc") or {}).get("faultsDelta") or 0)):
    print("  %-20s %10.0f %10.0f" % (name, med([f(w) for w in A]), med([f(w) for w in B])))
