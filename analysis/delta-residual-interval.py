"""The Lighthouse residual, standardised on position AND bot count, WITH AN INTERVAL.

Everything on the board is priced against this number, so it is the last one that
should arrive as a point estimate.

Three deliberate choices, each one a lesson from today applied to this figure:

1. The bot-count slope is estimated from OTHER MAPS, never from the leg being
   explained. Alpha's catch: using leg 4's own slope to explain why leg 4 is high
   runs in the direction that inflates the explanation. Leave-one-map-out removes
   that, at the cost of assuming the slope transfers across maps - which is an
   assumption, and is stated rather than hidden.

2. Position is standardised NON-PARAMETRICALLY (Z bins), because that is what
   survived three bin widths. Bot count is adjusted LINEARLY, because there is not
   enough data to bin two covariates jointly - n is 19 and 18.

3. The interval is a MOVING-BLOCK bootstrap, block length 3 windows. Adjacent
   windows are autocorrelated - same firefight, same building, same route - so an
   i.i.d. bootstrap would understate the width. Blocks are the cheap correction and
   the residual autocorrelation within a block is the remaining understatement.

The interval covers median sampling error and slope uncertainty. It does NOT cover
the transfer assumption in (1) or the linearity in (2).
"""
import json
import glob
import random
import sys
from collections import defaultdict

LOGS = sorted(glob.glob(
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson"))
TARGET = "Lighthouse"
STEADY, ZW, BLOCK, NBOOT = 120.0, 150.0, 3, 4000
random.seed(20260729)

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
        z = (o.get("pos") or {}).get("z") or [0, 0]
        rows.append({
            "key": "%s|L%d|%s" % (m, leg, path[-18:-7]), "map": m,
            "p50": (o.get("framePct") or {}).get("p50") or 0.0,
            "z": (z[0] + z[1]) / 2.0,
            "total": (o.get("bots") or {}).get("total") or 0,
        })

by = defaultdict(list)
for r in rows:
    by[r["key"]].append(r)


def med(xs):
    s = sorted(xs)
    n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


def slope(v):
    xs = [r["total"] for r in v]
    ys = [r["p50"] for r in v]
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-9:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


# ---- leave-one-map-out slope ---------------------------------------------
donors = [(k, slope(v)) for k, v in by.items() if v[0]["map"] != TARGET]
donors = [(k, s) for k, s in donors if s is not None]
print("BOT-COUNT SLOPE, estimated from maps OTHER than %s\n" % TARGET)
for k, s in sorted(donors):
    print("  %-22s %+8.4f ms/bot" % (k, s))
donor_slopes = [s for _, s in donors]
print("\n  median %+.4f   range %+.4f .. %+.4f   n=%d legs"
      % (med(donor_slopes), min(donor_slopes), max(donor_slopes), len(donor_slopes)))
print("  (%s's own legs give %s - EXCLUDED by design, see docstring)"
      % (TARGET, ", ".join("%+.4f" % slope(by[k]) for k in sorted(by) if by[k][0]["map"] == TARGET
                           and slope(by[k]) is not None)))

ks = sorted(k for k in by if by[k][0]["map"] == TARGET)
A, B = by[ks[0]], by[ks[-1]]


def residual(a, b, s):
    """leg B's p50 minus leg A standardised onto B's route and B's bot count."""
    ba = defaultdict(list)
    for r in a:
        ba[int(r["z"] // ZW)].append(r["p50"])
    hits = [med(ba[int(r["z"] // ZW)]) for r in b if int(r["z"] // ZW) in ba]
    if not hits:
        return None
    pos_std = sum(hits) / len(hits)
    dtot = med([r["total"] for r in b]) - med([r["total"] for r in a])
    return med([r["p50"] for r in b]) - (pos_std + s * dtot)


raw = med([r["p50"] for r in B]) - med([r["p50"] for r in A])
point = residual(A, B, med(donor_slopes))
print("\n\nLIGHTHOUSE L%s -> L%s\n" % (ks[0].split("L")[-1], ks[-1].split("L")[-1]))
print("  raw gap                                    %6.3f ms" % raw)
print("  after position only (earlier finding)      %6.3f ms" % 1.887)
print("  after position AND bot count               %6.3f ms" % point)


def blocks(v, rng):
    """moving-block resample of one leg, preserving local autocorrelation"""
    v = sorted(v, key=lambda r: r["z"])
    n = len(v)
    out = []
    while len(out) < n:
        i = rng.randrange(max(1, n - BLOCK + 1))
        out.extend(v[i:i + BLOCK])
    return out[:n]


rng = random.Random(20260729)


def run(mode):
    """The width is dominated by the slope, and the right slope model is a judgement
    call, so report both rather than picking one silently.

      shared - the slope is one constant measured noisily by each leg. Resample
               donors and take the median: uncertainty shrinks as sqrt(n).
      leg    - the slope is genuinely map-specific. One donor leg is then a single
               draw of it, and the full between-leg spread is real uncertainty.
    """
    out = []
    for _ in range(NBOOT):
        if mode == "leg":
            s = donor_slopes[rng.randrange(len(donor_slopes))]
        else:
            s = med([donor_slopes[rng.randrange(len(donor_slopes))]
                     for _ in range(len(donor_slopes))])
        r = residual(blocks(A, rng), blocks(B, rng), s)
        if r is not None:
            out.append(r)
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out))]


print("\n  95%% block-bootstrap intervals, both slope models:\n")
for mode, label in (("shared", "slope one constant, measured noisily"),
                    ("leg", "slope genuinely map-specific")):
    a, b = run(mode)
    print("    %-38s %7.3f .. %7.3f ms" % (label, a, b))
lo, hi = run("shared")

prize = 0.42
print("\n  against a realistic prize of ~%.2f ms, the residual is %.1fx .. %.1fx"
      % (prize, lo / prize, hi / prize))
print("\n  What the interval does NOT cover: the cross-map transfer of the slope, and")
print("  linearity in bot count. Both are assumptions, not sampling error.")
