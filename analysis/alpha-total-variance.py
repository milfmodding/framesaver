"""Is the 28-vs-31 between-leg total-bot difference large or small, measured in the
SAME quantity on both sides?

Beta priced spawn-side PMC variance (E=24.97, sd=3.99 PMCs spawned per raid) and
correctly flagged that bots.total is CONCURRENT live bots in a 60 s window - a
different quantity, so that sd cannot be compared to a 3-bot median difference.

The comparison that has no unit mismatch: within-leg sd of bots.total against the
between-leg difference in bots.total medians. Both are concurrent counts from the
same field.
"""
import json, glob, os, statistics as st
from collections import defaultdict

rows = []
for path in sorted(glob.glob(r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson")):
    stem = os.path.basename(path).split("-marathon")[0].replace("framesaver-", "")
    leg, prev = 0, None
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        try: o = json.loads(ln)
        except ValueError: continue
        if o.get("type") != "sample" or o.get("state") != "raid": continue
        m = str(o.get("map") or "?")
        if m != prev: prev, leg = m, leg + 1
        if o.get("final") or (o.get("raidElapsed") or 0) < 120: continue
        rows.append(("%s %s L%d" % (stem, m, leg), (o.get("bots") or {}).get("total") or 0))

by = defaultdict(list)
for k, v in rows: by[k].append(v)

print("bots.total WITHIN each leg (concurrent count, steady state)\n")
print("%-30s %3s %7s %7s %8s %9s" % ("leg", "n", "median", "sd", "min-max", "range"))
print("-" * 70)
sds = []
for k in sorted(by):
    v = by[k]
    if len(v) < 4: 
        print("%-30s %3d   (n too small)" % (k, len(v))); continue
    sd = st.stdev(v)
    sds.append(sd)
    print("%-30s %3d %7.1f %7.2f %8s %9d"
          % (k, len(v), st.median(v), sd, "%d-%d" % (min(v), max(v)), max(v) - min(v)))

lh = {k: by[k] for k in by if "Lighthouse" in k and len(by[k]) >= 4}
print("\nmedian within-leg sd across legs: %.2f bots" % st.median(sds))
if len(lh) == 2:
    (ka, va), (kb, vb) = sorted(lh.items())
    d = abs(st.median(va) - st.median(vb))
    pooled = ((st.stdev(va) ** 2 + st.stdev(vb) ** 2) / 2) ** 0.5
    print("\nthe two Lighthouse legs, same field, same units")
    print("  %-30s median %4.1f  sd %4.2f  range %d-%d" % (ka, st.median(va), st.stdev(va), min(va), max(va)))
    print("  %-30s median %4.1f  sd %4.2f  range %d-%d" % (kb, st.median(vb), st.stdev(vb), min(vb), max(vb)))
    print("  between-leg median difference %.1f bots" % d)
    print("  pooled within-leg sd           %.2f bots" % pooled)
    print("  difference as a multiple of within-leg sd: %.2f" % (d / pooled))
    print("\n  READING: a between-leg shift smaller than ~1 within-leg sd is inside the")
    print("  variation a single leg already shows, and needs no separate mechanism.")
