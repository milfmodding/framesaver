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


def leg_arm(ndjson):
    """The treatment arm of a whole leg, read from the header `config` block.

    Returns 'standbyOff' / 'forceAll' / 'default' / 'unknown'.

    `standbyOff` WAS MISSING AND THAT WAS A CONTAMINATION BUG. This split originally knew only
    about `forceAllRoles`, because that was the only arm in the corpus when it was written. The
    mod-off marathon of 2026-07-31 then arrived with `standByEnabled = False`, got labelled
    `default`, and was pooled with 23 mod-ON legs - so `Woods [default]` was 64% mod-on and 36%
    mod-off, and `Lighthouse [default]` was 90% mod-on. Those rows were being read as gate
    figures. This file exists to stop exactly that, and it did it to itself the moment a new arm
    appeared: **an arm split only separates the arms it was told about.**

    `standbyOff` is NOT a certified mod-off baseline. It reports one setting. Five further levers
    keep acting with stand-by off, four of them engine-level - `harness/check-modoff.py` is what
    certifies a leg from the full `cfg` block, and it should be run before any leg is quoted as a
    baseline. The label here says which legs must not be pooled; it does not say what they are.

    `unknown` means the header genuinely lacks the key - which no log in the present corpus does -
    and is kept distinct from False so a future build that drops a key can never be read as having
    run the default arm.
    """
    for ln in open(ndjson, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "header":
            continue
        cfg = o.get("config") or {}
        standby = cfg.get("standByEnabled")
        force = cfg.get("forceAllRoles")
        if standby is None or force is None:
            return "unknown"
        # Stand-by off dominates the label: with the subsystem off, forceAllRoles cannot act
        # (BotStandByInitPointsPatch returns before reading it), so a mod-off leg is one arm and
        # not two.
        if not standby:
            return "standbyOff"
        return "forceAll" if force else "default"
    return "unknown"


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
    # Frames split by map AND by the treatment arm the LEG ran in. Added 2026-07-30 after the
    # weighting disclosure showed 48% of Lighthouse's frames came from raid 1.5 - which ran
    # `Force for all roles` ON, so a number reading as a Lighthouse baseline was half treatment.
    #
    # `cfg.forceAllRoles` is null on every sample line in all 24 logs, and Gamma read that as the
    # discriminator being absent from the data. It is absent PER WINDOW. The HEADER carries it in
    # 24 of 24 - 23 False and raid 1.5 True - so a whole-leg attribution, which is all a per-map
    # percentile needs, is available today and does not wait on a build. Only a within-raid ABAB
    # contrast needs the per-window key. UNKNOWN is therefore the wrong label for these legs: the
    # answer is knowable and printing UNKNOWN would discard it.
    per_map_arm = defaultdict(list)
    # Arm rows need the SAME weighting disclosure as map rows, or the fix recreates the defect one
    # level down: Lighthouse [default] is itself mostly one leg, and its two legs disagree by 8 fps
    # at p75. Splitting by arm without disclosing composition would just move the assumption.
    per_map_arm_runs = defaultdict(lambda: defaultdict(int))
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
        arm = leg_arm(nd)
        for m, v in got:
            per_map[m].append(v)
            per_map_runs[m][os.path.basename(nd)] += 1
            per_map_arm[(m, arm)].append(v)
            per_map_arm_runs[(m, arm)][os.path.basename(nd)] += 1
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
    # Split by arm so a map row that mixes treatment into a baseline cannot be quoted as a gate.
    # The arm comes from the header, which carries it for every log in the corpus - so this needed
    # no new telemetry, only reading a field that was already there.
    print("  BY MAP AND TREATMENT ARM. Three arms, and they are three different questions:")
    print("    default     stand-by ON, Force for all roles off - what a user of the mod gets")
    print("    forceAll    Force for all roles ON - a treatment leg, NOT a baseline")
    print("    standbyOff  stand-by OFF - the mod-off baseline arm. `check-modoff.py` is what")
    print("                certifies one; this label only keeps it out of the other pools.")
    print("  The mod's effect on a map is default MINUS standbyOff, both rows read below. Neither")
    print("  row alone is 'the gate figure' now that two arms exist.")
    print(hdr)
    print("  " + "-" * 100)
    for (m, arm) in sorted(per_map_arm):
        report("%s [%s]" % (m, arm), per_map_arm[(m, arm)])
        runs = per_map_arm_runs[(m, arm)]
        tot = sum(runs.values())
        top, topn = max(runs.items(), key=lambda kv: kv[1])
        note = "SINGLE LEG" if len(runs) == 1 else ("largest %.0f%%" % (100.0 * topn / tot))
        print("      from %d leg(s), %s: %s" % (len(runs), note, ", ".join(
            "%s %.0f%%" % (r.replace("framesaver-", "").replace(".ndjson", "")[:30],
                           100.0 * c / tot) for r, c in sorted(runs.items(), key=lambda kv: -kv[1]))))
    mixed = sorted({m for (m, _a) in per_map_arm}
                   & {m for (m, a) in per_map_arm if a == "forceAll"}
                   & {m for (m, a) in per_map_arm if a == "default"})
    if mixed:
        print("  -> %s mix both arms, so the pooled row above is NOT a baseline for %s"
              % (", ".join(mixed), "it" if len(mixed) == 1 else "them"))
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
