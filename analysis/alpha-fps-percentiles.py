"""FPS percentiles across the corpus, from PresentMon frames, restricted to in-raid time.

SOPHIA ASKED FOR p75 AND IT IS NOT IN THE TELEMETRY. `framePct` carries p50/p95/p99/p999
only. But PresentMon records every frame, so any percentile is available from the capture -
using the join already in the harness rather than a new field or a new raid.

Join rule taken from analysis/delta-render-cpu-or-gpu.py rather than restated: PresentMon
`CPUStartQPC` against sample-line `qpc`, matched BY CONTAINMENT between consecutive window
boundaries, not by nearest. A second statement of a rule is a second place for it to be wrong.

THE METHODOLOGICAL POINT, and it is the difference between an honest answer and a flattering
one: a raw percentile over the whole capture includes MENU and LOADING frames. Menus render
a static screen at hundreds of fps, so pooling them drags every percentile toward the good
end - and there are thousands of them per session. Only frames contained by an in-raid,
non-final window are counted here.

PERCENTILE DIRECTION IS A TRAP AND BOTH LABELS ARE PRINTED. Frame TIME and FPS run opposite
ways, so the 75th percentile of frame time is the 25th percentile of fps. "p75 fps" can mean
either the stricter-than-typical number (75% of frames are at least this fast) or the
flattering one. The first is almost always what someone anchoring a performance gate wants,
so it leads - but both appear, named, so nobody has to guess which was quoted.

    python analysis/alpha-fps-percentiles.py
"""
import csv
import glob
import json
import os
from collections import defaultdict

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"


def pct(sorted_vals, p):
    """Linear-interpolated percentile on an already-sorted list."""
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return sorted_vals[0]
    i = p * (n - 1)
    lo = int(i)
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo)


def in_raid_windows(ndjson):
    """Contiguous [lo, hi) qpc spans for in-raid, non-final windows, tagged by map."""
    spans, prevqpc = [], None
    for ln in open(ndjson, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "sample":
            continue
        q = o.get("qpc")
        if o.get("state") == "raid" and not o.get("final") and q and prevqpc:
            spans.append({"map": str(o.get("map")), "lo": prevqpc, "hi": q,
                          "elapsed": o.get("raidElapsed") or 0})
        if q:
            prevqpc = q
    return spans


def main():
    pairs = []
    for csvp in sorted(glob.glob(os.path.join(LOGDIR, "*.presentmon.csv"))):
        nd = csvp[: -len(".presentmon.csv")] + ".ndjson"
        if os.path.isfile(nd):
            pairs.append((nd, csvp))

    if not pairs:
        print("REFUSED: no matched ndjson/presentmon pairs in %s" % LOGDIR)
        return 2

    per_map = defaultdict(list)
    # Which runs contributed how many frames to each map. A per-map percentile pools RAW FRAMES,
    # which is the correct estimator (a percentile of pooled frames, not a median of per-leg
    # percentiles) but it weights each leg by its frame COUNT. A long leg therefore dominates its
    # map, and a "Lighthouse p75" that is 80% one evening's raid is a fact about that raid.
    # Disclosed with a number rather than left for the reader to assume equal weighting.
    per_map_runs = defaultdict(lambda: defaultdict(int))
    per_run = {}
    grand = []

    for nd, csvp in pairs:
        spans = in_raid_windows(nd)
        if not spans:
            print("skip %s: no in-raid windows" % os.path.basename(nd))
            continue
        lo = min(s["lo"] for s in spans)
        hi = max(s["hi"] for s in spans)
        ordered = sorted(spans, key=lambda s: s["lo"])

        got = []
        with open(csvp, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                try:
                    q = int(row["CPUStartQPC"])
                except (ValueError, TypeError, KeyError):
                    continue
                if q < lo or q > hi:
                    continue
                for s in ordered:
                    if s["lo"] < q <= s["hi"]:
                        try:
                            got.append((s["map"], float(row["FrameTime"])))
                        except (ValueError, TypeError, KeyError):
                            pass
                        break

        if not got:
            print("skip %s: 0 frames joined" % os.path.basename(nd))
            continue
        per_run[os.path.basename(nd)] = [v for _m, v in got]
        for m, v in got:
            per_map[m].append(v)
            per_map_runs[m][os.path.basename(nd)] += 1
            grand.append(v)

    if not grand:
        print("REFUSED: 0 frames joined across %d pair(s)" % len(pairs))
        return 2

    def report(label, vals):
        v = sorted(vals)
        p50, p75, p95, p99 = pct(v, 0.50), pct(v, 0.75), pct(v, 0.95), pct(v, 0.99)
        print("  %-34s %8d  %6.2f %6.2f %6.2f %6.2f   %6.1f %6.1f %6.1f %6.1f"
              % (label, len(v), p50, p75, p95, p99,
                 1000.0 / p50, 1000.0 / p75, 1000.0 / p95, 1000.0 / p99))

    hdr = ("  %-34s %8s  %6s %6s %6s %6s   %6s %6s %6s %6s"
           % ("", "frames", "p50", "p75", "p95", "p99", "p50", "p75", "p95", "p99"))
    print("IN-RAID FRAMES ONLY. Left block is frame time in ms, right block is the fps that")
    print("corresponds to it. Both are percentiles OF FRAME TIME, so p75 means 'the frame")
    print("time 75% of frames come in under' - i.e. 75% of frames are at least that fast.")
    print()
    print(hdr)
    print("  " + "-" * 100)
    for name in sorted(per_run):
        report(name.replace("framesaver-", "").replace(".ndjson", ""), per_run[name])
    print()
    print("  by map")
    for m in sorted(per_map):
        report(m, per_map[m])
    print()
    print("  MAP ROWS ARE FRAME-WEIGHTED, not leg-weighted. Each map's percentile pools raw")
    print("  frames, so a longer leg counts more. Where one leg dominates, that map's gate")
    print("  number is a fact about that leg:")
    for m in sorted(per_map):
        runs = per_map_runs[m]
        tot = sum(runs.values())
        top, topn = max(runs.items(), key=lambda kv: kv[1])
        flag = "  <- SINGLE LEG" if len(runs) == 1 else ("  <- DOMINATED" if topn > 0.6 * tot else "")
        print("    %-22s %2d leg(s), largest %3.0f%% of %7d frames (%s)%s"
              % (m, len(runs), 100.0 * topn / tot, tot,
                 top.replace("framesaver-", "").replace(".ndjson", "")[:34], flag))
    print()
    print("  " + "-" * 100)
    report("ALL IN-RAID FRAMES", grand)

    print()
    print("THE OTHER READING, stated so nobody has to guess which was quoted: the numbers")
    print("above are percentiles of FRAME TIME. Because fps is 1/time, the p75 frame time is")
    print("the 25th percentile of the FPS distribution. If someone means 'p75 of fps' as in")
    print("a number 75% of frames FAIL to reach, that is the p25 frame time:")
    v = sorted(grand)
    print("    p25 frame time %.2f ms  =  %.1f fps  (only 25%% of frames are faster)"
          % (pct(v, 0.25), 1000.0 / pct(v, 0.25)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
