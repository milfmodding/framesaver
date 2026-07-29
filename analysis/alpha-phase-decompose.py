"""Decompose the Lighthouse gap by the Unity player loop, parents and leaves kept apart.

My first pass summed all 145 phase keys and got 198% of the frame, because the telemetry
emits BOTH the top-level player-loop groups AND their children. Summing them
double-counts. Recorded because a completeness check that reports -98% unaccounted is not
a finding, it is a broken check - and it is the same wrong-population error I keep making,
this time between a parent and its own child.
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
        rows.append((("%s %s L%d" % (stem, m, leg)), o))

by = defaultdict(list)
for k, o in rows: by[k].append(o)
lh = [k for k in sorted(by) if "Lighthouse" in k and len(by[k]) >= 5]
a, b = lh

def med(k, path):
    v = [(o.get("phases") or {}).get(path, {}).get("avg") for o in by[k]]
    v = [x for x in v if x is not None]
    return st.median(v) if v else None

keys = set()
for k in lh:
    for o in by[k]: keys |= set((o.get("phases") or {}).keys())
parents = sorted(x for x in keys if "/" not in x)
frame_a = st.median([o.get("frame", {}).get("avg") for o in by[a]])
frame_b = st.median([o.get("frame", {}).get("avg") for o in by[b]])

print("PARENTS ONLY - do the player-loop groups account for the frame?\n")
print("  %-18s %8s %8s %8s" % ("group", "L1", "L4", "delta"))
pa = pb = 0.0
for p in sorted(parents, key=lambda p: -(med(b, p) or 0)):
    x, y = med(a, p) or 0.0, med(b, p) or 0.0
    pa += x; pb += y
    print("  %-18s %8.3f %8.3f %+8.3f" % (p, x, y, y - x))
print("  %-18s %8.3f %8.3f %+8.3f" % ("SUM OF GROUPS", pa, pb, pb - pa))
print("  %-18s %8.3f %8.3f %+8.3f" % ("frame.avg", frame_a, frame_b, frame_b - frame_a))
print("  %-18s %8.3f %8.3f %+8.3f  <- outside every group" %
      ("unaccounted", frame_a - pa, frame_b - pb, (frame_b - pb) - (frame_a - pa)))

print("\nINSIDE EACH GROUP: named leaves against the remainder\n")
tot_named = 0.0
for p in sorted(parents, key=lambda p: -((med(b, p) or 0) - (med(a, p) or 0))):
    kids = sorted(x for x in keys if x.startswith(p + "/"))
    if not kids: continue
    pd = (med(b, p) or 0) - (med(a, p) or 0)
    if abs(pd) < 0.02: continue
    print("  %s   group delta %+.3f" % (p, pd))
    ksum = 0.0
    for kk in sorted(kids, key=lambda kk: -abs((med(b, kk) or 0) - (med(a, kk) or 0))):
        d = (med(b, kk) or 0) - (med(a, kk) or 0)
        ksum += d
        if abs(d) >= 0.03:
            print("      %-46s %+.3f" % (kk.split("/", 1)[1][:46], d))
    print("      %-46s %+.3f" % ("(leaves below 0.03, summed)", ksum - sum(
        d for d in ((med(b, kk) or 0) - (med(a, kk) or 0) for kk in kids) if abs(d) >= 0.03)))
    print("      %-46s %+.3f  <- inside the group, no leaf" % ("REMAINDER", pd - ksum))
    tot_named += ksum

print("\nFAMILIES, since attribution should group what shares a mechanism\n")
fam = {
    "animation (Begin + End)": ["PreLateUpdate/DirectorUpdateAnimationBegin",
                                "PreLateUpdate/DirectorUpdateAnimationEnd"],
    "rendering (FinishFrameRendering)": ["PostLateUpdate/FinishFrameRendering"],
    "script Update (bots + AI)": ["Update/ScriptRunBehaviourUpdate"],
    "script LateUpdate (playerLate lives here)": ["PreLateUpdate/ScriptRunBehaviourLateUpdate"],
    "particles": ["PreLateUpdate/ParticleSystemBeginUpdateAll"],
    "delayed / dynamic frame rate": ["Update/ScriptRunDelayedDynamicFrameRate",
                                     "PostLateUpdate/ScriptRunDelayedDynamicFrameRate"],
    "present wait (negative = less waiting)": ["TimeUpdate/WaitForLastPresentationAndUpdateTime"],
}
for name, ps in sorted(fam.items(), key=lambda t: -sum(((med(b, p) or 0) - (med(a, p) or 0)) for p in t[1])):
    d = sum(((med(b, p) or 0) - (med(a, p) or 0)) for p in ps)
    lv = sum((med(b, p) or 0) for p in ps)
    print("  %-44s level %6.3f   delta %+.3f" % (name, lv, d))
