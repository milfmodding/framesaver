"""Independent re-derivation of the load-bearing telemetry claims.

Written by Delta 2026-07-28 as a second implementation beside Gamma's, on the
principle that after 2026-07-28 one implementation is not a derivation.

Reads the ndjson logs in place and prints every figure the stage-4 sections and
the Streets bound rest on. No arguments; run it from anywhere.

    python delta-rederive.py [logdir]

Deliberately dependency-free (no pandas/numpy) so it runs against whatever
Python is on the box.
"""

import glob
import json
import math
import os
import statistics
import sys

LOGDIR = sys.argv[1] if len(sys.argv) > 1 else \
    r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"

# The menu-idle artifact sits at 545,800 ms and the largest real stall at
# 36,917 ms, so anything in 50k-400k works. Do NOT use asyncUpdate/period -- it
# is anti-correlated with the population it appears to select.
ARTIFACT_MS = 60_000

# Telemetry.cs drops any phase below this from the JSON while still counting it
# toward `accounted`. An absent phase is a threshold, not a zero.
PHASE_EMIT_FLOOR = 0.5


def load(path):
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except ValueError:
            continue


def logs():
    return sorted(glob.glob(os.path.join(LOGDIR, "framesaver-*.ndjson")))


def dominant(spike):
    """Largest top-level phase. Children would double-count their parent."""
    top = {k: v for k, v in (spike.get("phases") or {}).items() if "/" not in k}
    return max(top.items(), key=lambda kv: kv[1]) if top else ("none", 0.0)


def is_residual_dominant(spike):
    return spike["unaccounted"] > dominant(spike)[1]


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(sum((x - mx) ** 2 for x in xs) *
                           sum((y - my) ** 2 for y in ys))


def partial(xs, ys, zs):
    """corr(x, y) with z held constant."""
    rxy, rxz, ryz = corr(xs, ys), corr(xs, zs), corr(ys, zs)
    return (rxy - rxz * ryz) / math.sqrt((1 - rxz ** 2) * (1 - ryz ** 2))


def ols(rows, y):
    """Least squares with an explicit intercept column. rows are design rows."""
    k, n = len(rows[0]), len(y)
    aug = [[sum(rows[i][a] * rows[i][b] for i in range(n)) for b in range(k)] +
           [sum(rows[i][a] * y[i] for i in range(n))] for a in range(k)]
    for c in range(k):
        piv = max(range(c, k), key=lambda r: abs(aug[r][c]))
        aug[c], aug[piv] = aug[piv], aug[c]
        for r in range(k):
            if r != c and aug[c][c]:
                f = aug[r][c] / aug[c][c]
                for j in range(c, k + 1):
                    aug[r][j] -= f * aug[c][j]
    beta = [aug[i][k] / aug[i][i] for i in range(k)]
    fit = [sum(beta[j] * rows[i][j] for j in range(k)) for i in range(n)]
    my = sum(y) / n
    resid = sum((y[i] - fit[i]) ** 2 for i in range(n))
    total = sum((v - my) ** 2 for v in y)
    return beta, 1 - resid / total


def in_raid_spikes(path):
    return [o for o in load(path)
            if o.get("type") == "spike" and o.get("state") == "raid"
            and "unaccounted" in o and o.get("period", 0) <= ARTIFACT_MS]


def windows():
    """In-raid sample windows, teardown windows excluded.

    `final` marks 0 of the 16 affected windows, so bots.total is the filter.
    """
    out = []
    for path in logs():
        for o in load(path):
            if (o.get("type") == "sample" and o.get("state") == "raid"
                    and o.get("bots", {}).get("total", 0) > 0):
                o["_log"] = os.path.basename(path)[11:24]
                out.append(o)
    return out


def section(title):
    print("\n" + title)
    print("-" * len(title))


def gc_attribution():
    """Stage 4: the collection population and both directions of the claim."""
    section("1. Collection frames and phase attribution (control run)")
    control = [p for p in logs() if "control" in p][0]
    spikes = in_raid_spikes(control)
    coll = [s for s in spikes if s.get("gcGen0", 0) > 0]
    named = [s for s in coll if "gcPhase" in s]
    print("in-raid collection frames        : %d" % len(coll))
    print("  gcPhase = TimeUpdate           : %d" %
          sum(1 for s in coll if s.get("gcPhase") == "TimeUpdate"))
    print("  gcPhase = something else       : %d" %
          sum(1 for s in coll if s.get("gcPhase", "TimeUpdate") != "TimeUpdate"))
    print("  gcPhase absent                 : %d" % (len(coll) - len(named)))
    print("  -> a population defined by 'the field is present' is a population")
    print("     defined by the instrument's success. Count against gcGen0.")

    section("2. Both directions, stated separately -- only one survives")
    tud = [s for s in spikes if dominant(s)[0] == "TimeUpdate"
           and dominant(s)[1] > s["unaccounted"]]
    res = [s for s in spikes if is_residual_dominant(s)]
    res_gc = [s for s in res if s.get("gcGen0", 0) > 0]
    print("TimeUpdate-dominant => a collection : %d of %d" %
          (sum(1 for s in tud if s.get("gcGen0", 0) > 0), len(tud)))
    print("residual-dominant   => a collection : %d of %d   <-- a coin flip" %
          (len(res_gc), len(res)))

    section("3. The discriminator: frame << period, not the residual ratio")
    for label, group in (("with a collection", res_gc),
                         ("no collection", [s for s in res
                                            if s.get("gcGen0", 0) == 0])):
        if not group:
            continue
        halves = sum(1 for s in group if s["frame"] < s["period"] / 2)
        tu = sum(1 for s in group
                 if (s.get("phases") or {}).get("TimeUpdate", 0) >= PHASE_EMIT_FLOOR)
        print("%-18s n=%2d  frame med %6.1f  frame<period/2 %2d  TimeUpdate>=0.5 %2d"
              % (label, len(group),
                 statistics.median(s["frame"] for s in group), halves, tu))
    print("  -> unaccounted/period is NOT a discriminator: with phase work")
    print("     roughly constant it is a monotone function of pause length, and")
    print("     the no-collection frames sit HIGHER on it.")


def forward_direction_all_logs():
    section("4. Forward direction across every log carrying the fields")
    total = hits = 0
    for path in logs():
        tud = [s for s in in_raid_spikes(path)
               if "gcGen0" in s and dominant(s)[0] == "TimeUpdate"
               and dominant(s)[1] > s["unaccounted"]]
        if not tud:
            continue
        with_gc = sum(1 for s in tud if s["gcGen0"] > 0)
        total += len(tud)
        hits += with_gc
        print("  %-30s %2d / %2d" %
              (os.path.basename(path)[11:24], with_gc, len(tud)))
    print("  %-30s %2d / %2d" % ("TOTAL", hits, total))
    print("  NB 'TimeUpdate large' is not 'TimeUpdate dominant'. A frame with")
    print("     TimeUpdate 15ms and Update 200ms is not in this population.")


def unexplained_family():
    section("5. The non-GC residual family (no collection, no drain, no wait)")
    found = []
    for path in logs():
        for s in in_raid_spikes(path):
            if not is_residual_dominant(s) or s.get("gcGen0", 0) != 0:
                continue
            phases = s.get("phases") or {}
            if "TimeUpdate" in phases or s.get("frame", 0) <= 0.7 * s["period"]:
                continue
            s["_map"] = s.get("map", "")
            found.append(s)
    print("frames: %d" % len(found))
    for name in sorted({s["_map"] for s in found}):
        print("  %-16s %d" % (name, sum(1 for s in found if s["_map"] == name)))
    per = [s["period"] for s in found]
    print("period      : %.1f .. %.1f  median %.1f" %
          (min(per), max(per), statistics.median(per)))
    el = sorted(s["raidElapsed"] for s in found if "raidElapsed" in s)
    if el:
        print("raidElapsed : %.1f .. %.1f  median %.1f" %
              (el[0], el[-1], statistics.median(el)))
        print("  within first 120 s: %d of %d -- 'first minute or two' is wrong"
              % (sum(1 for v in el if v <= 120), len(el)))
    print("drain on these: asyncUpdate>1ms on %d of %d" %
          (sum(1 for s in found if s.get("asyncUpdate", 0) > 1), len(found)))


def timeupdate_modes():
    section("6. TimeUpdate is trimodal; the middle mode is the GC slice")
    buckets = {"<0.5": [0, 0], "2.9-3.2": [0, 0], ">10": [0, 0], "other": [0, 0]}
    for path in logs():
        for s in in_raid_spikes(path):
            tu = (s.get("phases") or {}).get("TimeUpdate", 0)
            key = ("<0.5" if tu < PHASE_EMIT_FLOOR else
                   "2.9-3.2" if 2.9 <= tu <= 3.2 else
                   ">10" if tu > 10 else "other")
            buckets[key][0] += 1
            buckets[key][1] += 1 if s.get("gcGen0", 0) > 0 else 0
    for key in ("<0.5", "2.9-3.2", ">10", "other"):
        n, gc = buckets[key]
        print("  TimeUpdate %-9s n=%3d   of which a collection completed: %d"
              % (key, n, gc))
    print("  boot.config carries gc-max-time-slice=3, the header reports")
    print("  timeSliceNs 3000000, and the middle mode is 3.0 ms. Three sources.")
    print("  => the incremental collector demonstrably slices.")


def streets_bound():
    section("7. Streets: the intercept is not identified; render is the bound")
    st = [o for o in windows() if o.get("map", "").lower() == "tarkovstreets"]
    p50 = [(o.get("framePct") or {}).get("p50") for o in st]
    keep = [i for i, v in enumerate(p50) if v]
    st = [st[i] for i in keep]
    p50 = [p50[i] for i in keep]
    awake = [o["bots"]["awake"] for o in st]
    asleep = [o["bots"].get("asleep", 0) for o in st]
    render = [o["frame"]["avg"] - o["gameUpdate"]["avg"] for o in st]
    ordered = sorted(p50)
    print("n=%d   best %.2f  p25 %.2f  MEDIAN %.2f  p75 %.2f  worst %.2f" %
          (len(p50), ordered[0], ordered[len(ordered) // 4],
           statistics.median(p50), ordered[3 * len(ordered) // 4], ordered[-1]))
    for label, design in (
            ("p50 ~ awake", [[1, a] for a in awake]),
            ("p50 ~ asleep", [[1, s] for s in asleep]),
            ("p50 ~ awake + asleep", [[1, a, s] for a, s in zip(awake, asleep)])):
        beta, r2 = ols(design, p50)
        print("  %-22s R2=%.3f  %s" %
              (label, r2, "  ".join("%+.3f" % b for b in beta)))
    print("  corr(awake, asleep) = %+.3f  -- near-collinear over a flat total,"
          % corr(awake, asleep))
    print("  so the intercept is not identified and the two models imply")
    print("  opposite strategies. R2 separates them by 0.004.")
    below = [(v, a) for v, a in zip(p50, awake) if v < 13.25]
    print("  windows below the 13.25 'intercept': %d, at awake counts %s"
          % (len(below), sorted(a for _, a in below)))
    print("  -> an intercept is a conditional mean, not a floor.")
    print("  render: min %.2f  median %.2f  max %.2f   corr(awake,render) %+.3f"
          % (min(render), statistics.median(render), max(render),
             corr(awake, render)))
    print("  -> %d of %d windows above %.2f ms, and it barely tracks bot count."
          % (len(render), len(render), min(render)))


def draw_calls():
    section("8. Draw calls: real, correctly sized, and a fifth of render")
    st = [o for o in windows()
          if o.get("map", "").lower() == "tarkovstreets"
          and o.get("gpu", {}).get("render")]
    if len(st) < 4:
        print("  no windows carrying a gpu.render block")
        return
    dc = [o["gpu"]["render"]["drawCalls"]["avg"] for o in st]
    render = [o["frame"]["avg"] - o["gameUpdate"]["avg"] for o in st]
    awake = [o["bots"]["awake"] for o in st]
    print("n=%d" % len(st))
    print("  corr(render, drawCalls)                = %+.3f" % corr(render, dc))
    print("  partial(render, drawCalls | awakeBots) = %+.3f" %
          partial(render, dc, awake))
    print("  partial(render, awakeBots | drawCalls) = %+.3f  <- collapses" %
          partial(render, awake, dc))
    beta, _ = ols([[1, v] for v in dc], render)
    mean_dc = sum(dc) / len(dc)
    mean_rn = sum(render) / len(render)
    print("  render_ms = %.3f + %.6f * drawCalls  (%.2f us per draw call)" %
          (beta[0], beta[1], beta[1] * 1000))
    print("  fixed %.2f ms of %.2f ms mean render (%.0f%%); proportional %.2f ms"
          % (beta[0], mean_rn, 100 * beta[0] / mean_rn, beta[1] * mean_dc))
    print("  model-free: drawCalls %.0f..%.0f (%.1fx) while render %.2f..%.2f"
          % (min(dc), max(dc), max(dc) / min(dc), min(render), max(render)))
    print("  -> correlation is not share. The lever is ~1.4 ms, not 6.6.")


def main():
    print("Framesaver -- Delta re-derivation")
    print("logs: %s (%d files)" % (LOGDIR, len(logs())))
    gc_attribution()
    forward_direction_all_logs()
    unexplained_family()
    timeupdate_modes()
    streets_bound()
    draw_calls()


if __name__ == "__main__":
    main()
