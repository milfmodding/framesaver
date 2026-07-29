"""Does bots.total plateau, or is our steady-state cut sampling a spawn ramp?

BotStart from the location database: Streets 122 s and Ground Zero 120 s, against
10-20 s everywhere else. Our steady-state filter is raidElapsed >= 120 - which on
Streets is the moment spawning BEGINS. If population ramps, every Streets number we
have is a ramp average rather than a plateau, and Streets is next on the map list.

Printing ALL windows including pre-120 s, so the ramp is visible rather than cut off.
"""
import json, glob, os
from collections import defaultdict

BOTMAX = {"Lighthouse": 29, "TarkovStreets": 48, "Woods": 30, "RezervBase": 28,
          "factory4_day": 0, "Shoreline": 31, "bigmap": 19, "Interchange": 30,
          "Sandbox_high": 24}
rows = defaultdict(list)
for path in sorted(glob.glob(r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson")):
    stem = os.path.basename(path).split("-marathon")[0].replace("framesaver-", "")
    leg, prev = 0, None
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        try: o = json.loads(ln)
        except ValueError: continue
        if o.get("type") != "sample" or o.get("state") != "raid": continue
        m = str(o.get("map") or "?")
        if m != prev: prev, leg = m, leg + 1
        if o.get("final"): continue
        rows["%s %s L%d" % (stem, m, leg)].append(
            ((o.get("raidElapsed") or 0.0) / 60.0, (o.get("bots") or {}).get("total") or 0, m))

for k in sorted(rows):
    v = sorted(rows[k])
    m = v[0][2]
    cap = BOTMAX.get(m)
    print("\n%s   BotMax=%s   n=%d" % (k, cap, len(v)))
    line = "  ".join("%.0fm:%d" % (t, n) for t, n, _ in v)
    print("   " + line)
    early = [n for t, n, _ in v if t < 5.0]
    late = [n for t, n, _ in v if t >= 5.0]
    if early and late:
        e, l = sum(early) / len(early), sum(late) / len(late)
        flag = "  <== RAMP" if l - e >= 2.0 else ""
        print("   first 5 min mean %.1f | after 5 min mean %.1f | delta %+.1f%s" % (e, l, l - e, flag))
    peak = max(n for _, n, _ in v)
    if cap is not None and peak > cap:
        print("   PEAK %d EXCEEDS BotMax %d by %d - the database cap is not the ceiling" % (peak, cap, peak - cap))
