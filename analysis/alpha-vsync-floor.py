"""Is OUR corpus vsync-capped? Beta raised this for external testers; it applies here too.

A vsync cap at refresh R pins frame time at or above 1000/R ms and no window can sit
below it. So the check is the mirror of the bot-cap censoring test: look for a FLOOR.
Any window below a candidate budget excludes that refresh rate outright.

    60 Hz  -> 16.67 ms      120 Hz -> 8.33 ms
    75 Hz  -> 13.33 ms      144 Hz -> 6.94 ms
    90 Hz  -> 11.11 ms      165 Hz -> 6.06 ms
                            240 Hz -> 4.17 ms

Using framePct.p50 (the gate's estimator) and frame.min (the strongest floor test -
a single fast frame below a budget excludes that cap, where a median need not).
"""
import json, glob
CAND = [(60, 1000/60), (75, 1000/75), (90, 1000/90), (120, 1000/120),
        (144, 1000/144), (165, 1000/165), (240, 1000/240)]
p50s, mins = [], []
for path in sorted(glob.glob(r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*.ndjson")):
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        try: o = json.loads(ln)
        except ValueError: continue
        if o.get("type") != "sample" or o.get("state") != "raid" or o.get("final"): continue
        p = (o.get("framePct") or {}).get("p50")
        if p is not None: p50s.append(p)
        f = (o.get("frame") or {}).get("min")
        if f: mins.append(f)

if not p50s:
    print("NO WINDOWS - refusing to report"); raise SystemExit(2)
print("raid windows: %d with p50, %d with frame.min" % (len(p50s), len(mins)))
print("lowest p50      %.3f ms  (%.1f fps)" % (min(p50s), 1000/min(p50s)))
if mins:
    print("lowest frame.min %.3f ms  (%.1f fps)" % (min(mins), 1000/min(mins)))
print("\nrefresh  budget   verdict")
for hz, budget in CAND:
    below50 = sum(1 for v in p50s if v < budget - 0.05)
    belowmin = sum(1 for v in mins if v < budget - 0.05)
    if belowmin or below50:
        print("  %3d Hz  %6.2f   EXCLUDED - %d p50 and %d frame.min windows sit below it"
              % (hz, budget, below50, belowmin))
    else:
        print("  %3d Hz  %6.2f   not excluded by this test" % (hz, budget))
print("\nA cap can only be excluded, never confirmed, by a floor test: nothing below the")
print("budget proves a cap, it may just be a slow machine. Exclusion is the usable half.")
