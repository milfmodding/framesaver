"""How much of the frame is AI? That bounds what brain slicing can possibly buy.

Brain slicing cuts brain TICKS. Its ceiling is the share of the frame spent in
AI, times the fraction of ticks removed. If AI is 2% of the frame, a 3x tick cut
saves at most ~1.3% and the arm is underpowered by construction - no number of
windows fixes that.

Reports per map, in-raid windows only, from whatever logs are passed.
"""
import json
import glob
import sys
from collections import defaultdict

LOGS = sys.argv[1:] or sorted(glob.glob(r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/"
                        r"framesaver-*.ndjson"))

acc = defaultdict(lambda: defaultdict(list))
for path in LOGS:
    for ln in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "sample" or o.get("state") != "raid":
            continue
        m = str(o.get("map") or "?")
        frame = (o.get("frame") or {}).get("avg")
        ai = (o.get("aiTotal") or {}).get("avg")
        aimax = (o.get("aiTotal") or {}).get("max")
        live = (o.get("agents") or {}).get("live")
        awake = (o.get("bots") or {}).get("awake")
        p50 = (o.get("framePct") or {}).get("p50")
        if frame is None or ai is None:
            continue
        a = acc[m]
        a["frame"].append(frame)
        a["ai"].append(ai)
        if aimax is not None:
            a["aimax"].append(aimax)
        if live is not None:
            a["live"].append(live)
        if awake is not None:
            a["awake"].append(awake)
        if p50 is not None:
            a["p50"].append(p50)

if not acc:
    print("NO RAID WINDOWS WITH aiTotal -- check field names")
    sys.exit(2)


def mean(xs):
    return sum(xs) / float(len(xs)) if xs else float("nan")


print("in-raid windows, all logs. 'AI share' is aiTotal.avg / frame.avg.\n")
print("%-18s %4s %7s %7s %7s   %6s %6s   %8s" %
      ("map", "n", "frame", "aiTotal", "AI share", "live", "awake", "ceiling"))
print("-" * 82)

rows = []
for m in sorted(acc, key=lambda k: -mean(acc[k]["ai"]) / max(1e-9, mean(acc[k]["frame"]))):
    a = acc[m]
    f, ai = mean(a["frame"]), mean(a["ai"])
    share = ai / f if f else 0.0
    live = mean(a["live"]) if a["live"] else float("nan")
    # A floor-bound arm ticks 4 of `live`. Ceiling on the saving is the AI time
    # removed, assuming cost is linear in ticks and nothing else changes.
    cut = (1.0 - 4.0 / live) if live and live > 4 else 0.0
    ceiling = ai * cut
    rows.append((m, len(a["frame"]), f, ai, share, live, mean(a["awake"]), ceiling))
    print("%-18s %4d %7.2f %7.3f %6.1f%%   %6.1f %6.1f   %6.2f ms" %
          (m, len(a["frame"]), f, ai, share * 100.0, live,
           mean(a["awake"]) if a["awake"] else float("nan"), ceiling))

print("\n'ceiling' = aiTotal.avg x (1 - 4/live): the whole AI saving if a")
print("floor-bound sliced arm removed every tick it does not perform, cost were")
print("linear in ticks, and nothing else moved. It is an upper bound and every")
print("one of those assumptions makes the real effect smaller.")
