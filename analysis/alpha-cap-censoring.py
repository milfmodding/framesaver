"""Does MaxBotsAliveOnMap = 36 actually bind on bots.total?

Alpha told Sophia "no cap blocks raising population", inferring it from three
BotMax violations. Beta then found MaxBotsAliveOnMap = 36 used for PVE_OFFLINE
regardless of BotAmount, with observed maxima sitting right against it. Those
cannot both be right, so: look for CENSORING.

A binding cap leaves a signature the median cannot show - a pile-up of windows
just below the ceiling and a hard edge above it. An unbinding cap leaves a
distribution that simply tails off. Printing the top of the distribution for both
log sets, because the second set reaching 49 would disprove a 36 ceiling outright.
"""
import json, glob, os
from collections import Counter

SETS = {
    "documented (SPT4.0.13)": r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*.ndjson",
    "undocumented (Base)":    r"F:/SPT/Base/BepInEx/plugins/Framesaver-logs/framesaver-*.ndjson",
}
for label, pat in SETS.items():
    files = sorted(glob.glob(pat))
    hist, permap = Counter(), {}
    for path in files:
        for ln in open(path, encoding="utf-8-sig", errors="replace"):
            try: o = json.loads(ln)
            except ValueError: continue
            if o.get("type") != "sample" or o.get("state") != "raid" or o.get("final"): continue
            t = (o.get("bots") or {}).get("total")
            if t is None: continue
            hist[t] += 1
            m = str(o.get("map") or "?")
            permap[m] = max(permap.get(m, 0), t)
    n = sum(hist.values())
    print("\n=== %s : %d files, %d raid windows" % (label, len(files), n))
    if not n:
        print("    NO WINDOWS - refusing to report"); continue
    top = max(hist)
    print("    max bots.total = %d" % top)
    print("    top of distribution (count per value):")
    for v in range(max(0, top - 14), top + 1):
        c = hist.get(v, 0)
        bar = "#" * min(c, 60)
        mark = ""
        if v == 36: mark = "   <-- MaxBotsAliveOnMap"
        print("      %3d  %4d  %s%s" % (v, c, bar, mark))
    at_or_below = sum(c for v, c in hist.items() if v <= 36)
    above = n - at_or_below
    print("    windows <=36: %d (%.1f%%)   >36: %d (%.1f%%)" % (at_or_below, 100.0*at_or_below/n, above, 100.0*above/n))
    print("    per-map maxima: " + ", ".join("%s=%d" % kv for kv in sorted(permap.items(), key=lambda x: -x[1])))
