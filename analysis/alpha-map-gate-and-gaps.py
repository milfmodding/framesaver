"""Per-map gate table at p75/p99, and where the frame time actually goes.

TWO JOBS, and they need different instruments, which is the whole reason this file is careful
about which number came from where.

1. THE GATE TABLE. p75 needs per-frame data, so it exists only where a PresentMon capture
   exists. p99 exists BOTH ways - from PresentMon and from the telemetry's own framePct - so
   it is reported from both and any disagreement is visible rather than averaged. Maps with
   telemetry but no capture get p99 and no p75, and are listed as such: a coverage gap named
   is a gap somebody can close, a gap omitted reads as a map that does not exist.

2. WHERE THE FRAME GOES. Sums TOP-LEVEL player-loop phases only. `phases` carries parents and
   children keyed as "Update" and "Update/Something", and summing both reported 198% of the
   frame once on this project. Anything with a "/" is a child and is excluded from the sum.
   The named components (aiTotal, playerLate, playerTick, updateManual, asyncUpdateDrain) live
   INSIDE those phases, so they are reported as their own rows and never added to the total.

BUILT PER WINDOW, AGGREGATED LAST. A median of sums is not a sum of medians, and the eight
components do not peak in the same window. Every quantity here is computed per window first.

    python analysis/alpha-map-gate-and-gaps.py
"""
import csv
import glob
import json
import os
import statistics
from collections import defaultdict

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"


def pctile(vals, p):
    v = sorted(vals)
    n = len(v)
    if not n:
        return None
    if n == 1:
        return v[0]
    i = p * (n - 1)
    lo = int(i)
    hi = min(lo + 1, n - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def raid_windows(path):
    out, prevqpc = [], None
    for ln in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "sample":
            continue
        q = o.get("qpc")
        if o.get("state") == "raid" and not o.get("final"):
            o["_lo"], o["_hi"] = prevqpc, q
            out.append(o)
        if q:
            prevqpc = q
    return out


def main():
    tele = defaultdict(list)          # map -> [window dicts]
    pm_ft = defaultdict(list)         # map -> [frame times from PresentMon]

    for nd in sorted(glob.glob(os.path.join(LOGDIR, "*.ndjson"))):
        wins = raid_windows(nd)
        if not wins:
            continue
        for w in wins:
            tele[str(w.get("map"))].append(w)

        csvp = nd[: -len(".ndjson")] + ".presentmon.csv"
        if not os.path.isfile(csvp):
            continue
        spans = [w for w in wins if w.get("_lo") and w.get("_hi")]
        if not spans:
            continue
        lo = min(w["_lo"] for w in spans)
        hi = max(w["_hi"] for w in spans)
        ordered = sorted(spans, key=lambda w: w["_lo"])
        with open(csvp, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                try:
                    q = int(row["CPUStartQPC"])
                except (ValueError, TypeError, KeyError):
                    continue
                if q < lo or q > hi:
                    continue
                for w in ordered:
                    if w["_lo"] < q <= w["_hi"]:
                        try:
                            pm_ft[str(w.get("map"))].append(float(row["FrameTime"]))
                        except (ValueError, TypeError, KeyError):
                            pass
                        break

    if not tele:
        print("REFUSED: no in-raid windows anywhere")
        return 2

    # ---------------------------------------------------------------- gate table
    print("GATE TABLE. p75 requires per-frame data and exists only where a capture does.")
    print("p99 is available both ways, so both are shown and disagreement stays visible.\n")
    print("  %-16s %7s %8s   %8s %8s   %8s %8s   %s"
          % ("map", "windows", "frames", "p75 ms", "p75 fps", "p99 ms", "p99 fps", "p99 telem"))
    print("  " + "-" * 92)
    nocap = []
    for m in sorted(tele):
        wins = tele[m]
        # telemetry p99: median across windows of each window's own p99
        t99 = [w["framePct"]["p99"] for w in wins
               if isinstance(w.get("framePct"), dict) and w["framePct"].get("p99")]
        t99m = statistics.median(t99) if t99 else None
        ft = pm_ft.get(m)
        if ft:
            p75, p99 = pctile(ft, 0.75), pctile(ft, 0.99)
            print("  %-16s %7d %8d   %8.2f %8.1f   %8.2f %8.1f   %s"
                  % (m, len(wins), len(ft), p75, 1000.0 / p75, p99, 1000.0 / p99,
                     ("%.1f ms" % t99m) if t99m else "-"))
        else:
            nocap.append(m)
            print("  %-16s %7d %8s   %8s %8s   %8s %8s   %s"
                  % (m, len(wins), "-", "NO CAP", "-", "-", "-",
                     ("%.1f ms" % t99m) if t99m else "-"))

    if nocap:
        print("\n  NO p75 AVAILABLE for: %s" % ", ".join(nocap))
        print("  These maps have telemetry but no PresentMon capture. p75 cannot be")
        print("  reconstructed from framePct, which carries p50/p95/p99/p999 only. One")
        print("  captured raid per map closes it.")

    # ------------------------------------------------------- where the frame goes
    print("\n\nWHERE THE FRAME GOES, top-level player-loop phases only, median of per-window")
    print("values. Children (keys containing '/') are excluded - summing parents and children")
    print("reported 198%% of the frame once here.\n")

    for m in sorted(tele):
        wins = tele[m]
        rows, loop_sums, frames = defaultdict(list), [], []
        named = defaultdict(list)
        for w in wins:
            ph = w.get("phases") or {}
            tops = {k: v for k, v in ph.items() if "/" not in k and isinstance(v, dict)}
            if not tops:
                continue
            s = 0.0
            for k, v in tops.items():
                a = v.get("avg")
                if a is not None:
                    rows[k].append(a)
                    s += a
            loop_sums.append(s)
            fr = w.get("frame") or {}
            if fr.get("avg"):
                frames.append(fr["avg"])
            for key in ("aiTotal", "playerLate", "playerTick"):
                blk = w.get(key)
                if isinstance(blk, dict) and blk.get("avg") is not None:
                    named[key].append(blk["avg"])
            um = w.get("updateManual") or {}
            if um.get("awakeMs") and w.get("frames"):
                named["updateManual awake"].append(um["awakeMs"] / w["frames"])
            ad = w.get("asyncUpdateDrain")
            if isinstance(ad, dict) and ad.get("avg") is not None:
                named["asyncUpdateDrain"].append(ad["avg"])

        if not loop_sums:
            continue
        fm = statistics.median(frames) if frames else None
        lm = statistics.median(loop_sums)
        print("  %s  (%d windows)" % (m, len(wins)))
        print("    frame avg            %7.3f ms" % (fm or -1))
        print("    sum of top phases    %7.3f ms   %s of the frame"
              % (lm, ("%.0f%%" % (100 * lm / fm)) if fm else "-"))
        if fm:
            print("    outside the loop     %7.3f ms   %.0f%%" % (fm - lm, 100 * (fm - lm) / fm))
        for k in sorted(rows, key=lambda k: -statistics.median(rows[k])):
            med = statistics.median(rows[k])
            if med < 0.05:
                continue
            print("      %-28s %7.3f ms   %s of frame"
                  % (k, med, ("%5.1f%%" % (100 * med / fm)) if fm else "-"))
        if named:
            print("    named components (INSIDE the phases above, not additive with them):")
            for k in sorted(named, key=lambda k: -statistics.median(named[k])):
                print("      %-28s %7.3f ms" % (k, statistics.median(named[k])))
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
