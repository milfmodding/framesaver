"""Adjudicate claims C and D on the mod-off marathon: measure the gating ceiling, test the
age ramp with the new per-bot instrument, and re-verify the awakeCalls divisor.

CLAIM C (Alpha): stand-by's own gating saves ~0.011 ms per awake bot per frame, so sleeping
12 bots saves ~0.14 ms against Woods' measured 7.0 ms gap. Attacks it invites:
  - the divisor (one UpdateManual call per awake bot per frame) - re-proven here by the
    calls/frames identity, per window, on the new corpus. leakFix is OFF in this marathon,
    so the earlier corpse-population result (established with leakFix on) does NOT carry
    over; `deadCalls` now measures the contamination directly instead of by inference.
  - the awake-age ramp (raid 1: ms/call rose 0.034 -> 0.109 for permanently-awake bots).
    0.011 could be the FRESH rate; a mod-off raid holds bots awake permanently, so C's
    counterfactual might pay the ramped rate, up to ~10x higher.

THE CEILING ARGUMENT THAT MAKES THE RAMP MOOT FOR C. Mod-off, `awakeMs/frames` is the
ENTIRE per-frame pool the gating mechanism can ever draw from - integrated over the ages
the raid actually reached, ramp or no ramp. No per-bot rate, no extrapolation: if Woods'
mod-off awakeMs/frames is X, sleeping every bot on the map cannot save more than X minus
the paused replacement cost. The ramp question then only matters for per-bot PRICING
(role-aware 350 m, raid-2 design), not for whether C's ordering holds.

THE SAME MOVE BOUNDS THE CULL, one-sidedly. The mod-off animator phase
(PreLateUpdate/DirectorUpdateAnimationBegin) is everything the phase spends when nothing is
culled - player, doors and scenery included - so it is an UPPER bound on what culling bots
can save. If gating ceiling << animator phase on every map, the D-vs-C mechanism ORDERING
is settled without resolving the 0.091-vs-0.211 coefficient dispute.

THE AGE RAMP, tested two ways with the new instrument:
  - pooled: per-raid awakeAge buckets, ms/call by continuous-awake age.
  - within-bot: per (id, spanS) span, the SAME bot's ms/call young vs old. This is the
    raid-2 estimand shape, delivered early by the marathon: mod-off populations age
    without any interference from our stand-by, and full rosters stay awake on the maps
    where vanilla sleeps nobody.

INSTRUMENT SELF-CHECK BEFORE ANY OF IT IS BELIEVED (the botWindow rows are hours old):
the rows for a window must sum to awakeMs - deadMs (stated in AwakeAgeTiming.DrainRows).
A failure mode here produces a DIFFERENT value than a pass, so the check can fail.

Known weaknesses:
  - Age and raid-content are confounded within a raid (fights escalate as time passes).
    Within-bot pairing removes bot identity/role, not content. A flat result is clean
    evidence against the ramp; a positive result still carries the content alias.
  - The animator-phase ceiling includes non-bot animators, so it is generous to D. It
    cannot understate the ordering gap, only overstate it - direction stated, not hidden.
  - ms fields carry 3 decimals; a bot under 0.0005 ms/window reads 0. Affects cheap bots'
    per-call rates downward, uniformly across ages.
  - Warm-up sensitivity is checked by recomputing the headline medians at 180 s; windows
    are 30 s here and the 60 s rule's equivalence proof covered only the 60 s-window era.
"""
import collections
import json
import os
import statistics as S

LOG = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs\framesaver-20260731-112704-modoff-marathon.ndjson"
ANIM = "PreLateUpdate/DirectorUpdateAnimationBegin"


def load():
    samples, rows = [], collections.defaultdict(list)
    for ln in open(LOG, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        t = o.get("type")
        if t == "sample" and o.get("state") == "raid":
            samples.append(o)
        elif t == "botWindow":
            rows[o["window"]].append(o)
    return samples, rows


def kept_windows(samples, warmup):
    """Warm-up by window START (raidElapsed - windowSec >= warmup), teardown = last window
    of each (raid, map) segment - same rules as alpha-animator-slope, restated because the
    filter is under test here (weakness: two statements of a rule can drift)."""
    seg = collections.defaultdict(list)
    for o in samples:
        seg[(o.get("raid"), str(o.get("map")))].append(o)
    keep = []
    for k in sorted(seg):
        ws = seg[k]
        for o in ws[:-1]:
            el, wsec = o.get("raidElapsed"), o.get("windowSec")
            if el is None or wsec is None or el - wsec < warmup:
                continue
            keep.append(o)
    return keep


def main():
    samples, rows = load()
    keep = kept_windows(samples, 60)
    if not keep:
        print("REFUSED: no post-warmup in-raid windows")
        return 2

    # ---- 0. instrument self-check: botWindow rows must sum to awakeMs - deadMs -----------
    print("0. SELF-CHECK: sum(botWindow.ms) vs awakeMs - deadMs, per window. The stated")
    print("   contract of DrainRows. Worst offenders shown; a broken drain fails HERE.")
    gaps = []
    for o in keep:
        u = o["updateManual"]
        want = u["awakeMs"] - u.get("deadMs", 0)
        got = sum(r["ms"] for r in rows.get(o["window"], ()))
        gaps.append((abs(got - want), want, got, o))
    gaps.sort(reverse=True, key=lambda g: g[0])
    worst = gaps[0]
    print("   windows %d, worst |gap| %.3f ms (want %.3f got %.3f, raid %s %s w%d)"
          % (len(gaps), worst[0], worst[1], worst[2], worst[3]["raid"], worst[3]["map"],
             worst[3]["window"]))
    med = S.median([g[0] / g[1] if g[1] else 0.0 for g in gaps])
    print("   median relative gap %.4f  (rounding on 0.### rows predicts ~0.001-0.01)" % med)
    print()

    # ---- 1. the divisor identity, and deadCalls read directly ----------------------------
    print("1. IDENTITY: awakeCalls/frames - bots.awake per window (0 iff one call per awake")
    print("   bot per frame). leakFix=false here, so corpses COULD accumulate: deadCalls is")
    print("   the direct read. pausedCalls/frames - asleep is the control.")
    exA = [o["updateManual"]["awakeCalls"] / o["frames"] - o["bots"]["awake"] for o in keep]
    exP = [o["updateManual"]["pausedCalls"] / o["frames"] - o["bots"]["asleep"] for o in keep]
    dc = [o["updateManual"].get("deadCalls", 0) / o["frames"] for o in keep]
    un = [o["updateManual"].get("unstampedCalls", 0) for o in keep]
    print("   awake excess: med %+0.3f  p90 %+0.3f  max %+0.3f" %
          (S.median(exA), sorted(exA)[int(0.9 * len(exA))], max(exA)))
    print("   paused excess: med %+0.3f  max %+0.3f" % (S.median(exP), max(exP)))
    print("   deadCalls/frame: med %.3f  max %.3f   unstamped total %d"
          % (S.median(dc), max(dc), sum(un)))
    print()

    # ---- 2. per-map ceilings -------------------------------------------------------------
    print("2. CEILINGS per map, mod-off, post-warmup medians. gate = awakeMs/frames is ALL")
    print("   the gating mechanism can draw from (any ramp already integrated). anim = the")
    print("   whole animator phase, an over-generous ceiling for the cull (player+scenery")
    print("   included). frame = avg frame ms for scale.")
    print()
    print("   %-14s %4s %7s %8s %8s %8s %7s %7s" %
          ("map", "n", "awake", "gateMs", "pausedMs", "animMs", "frameMs", "ms/call"))
    by_map = collections.defaultdict(list)
    for o in keep:
        by_map[(o["raid"], str(o["map"]))].append(o)
    for (raid, mp) in sorted(by_map, key=lambda k: k[1]):
        ws = by_map[(raid, mp)]
        gate = S.median([w["updateManual"]["awakeMs"] / w["frames"] for w in ws])
        paus = S.median([w["updateManual"]["pausedMs"] / w["frames"] for w in ws])
        anim = [((w.get("phases") or {}).get(ANIM) or {}).get("avg") for w in ws]
        anim = [a for a in anim if a is not None]
        fr = S.median([(w.get("frame") or {}).get("avg") for w in ws])
        awake = S.median([w["bots"]["awake"] for w in ws])
        mpc = S.median([w["updateManual"]["awakeMs"] / w["updateManual"]["awakeCalls"]
                        for w in ws if w["updateManual"]["awakeCalls"]])
        print("   %-14s %4d %7.1f %8.3f %8.3f %8s %7.2f %7.4f" %
              (mp, len(ws), awake, gate, paus,
               "%.3f" % S.median(anim) if anim else "-", fr, mpc))
    print()

    # ---- 3. the age ramp, pooled buckets per raid ----------------------------------------
    print("3. AGE RAMP, pooled: ms/call by continuous-awake age bucket, per raid. Raid 1's")
    print("   ramp predicts the right-hand buckets read ~3x the left; flat kills the ramp")
    print("   as an AGE effect (mod-off bots age all raid on the no-sleep maps).")
    print()
    print("   %-14s " % "map" + " ".join("%9s" % b for b in
                                          ("<60s", "<150", "<300", "<600", "<1200", "1200+")))
    for (raid, mp) in sorted(by_map, key=lambda k: k[1]):
        ws = by_map[(raid, mp)]
        ms = [0.0] * 6
        n = [0] * 6
        for w in ws:
            for i, b in enumerate(w.get("awakeAge") or ()):
                ms[i] += b["ms"]
                n[i] += b["n"]
        cells = ["%9s" % ("%.4f" % (ms[i] / n[i]) if n[i] else "-") for i in range(6)]
        print("   %-14s %s   calls %s" % (mp, " ".join(cells),
                                          "/".join(str(x // 1000) + "k" if x >= 1000 else str(x)
                                                   for x in n)))
    print()

    # ---- 4. within-bot: same bot, young vs old -------------------------------------------
    print("4. WITHIN-BOT paired contrast: for each continuous span (id+spanS) with windows")
    print("   both young (age<150s) and old (age>600s), the SAME bot's ms/call in each.")
    print("   Composition cannot produce a paired effect; content still can.")
    win_of = {o["window"]: o for o in keep}
    spans = collections.defaultdict(list)
    for w, rs in rows.items():
        if w not in win_of:
            continue
        for r in rs:
            if r["n"] > 0:
                spans[(r["id"], r["spanS"], r["role"])].append((r["awakeS"], r["ms"] / r["n"]))
    diffs, roles = [], collections.Counter()
    for (bid, sp, role), pts in spans.items():
        young = [c for a, c in pts if a < 150]
        old = [c for a, c in pts if a > 600]
        if young and old:
            diffs.append(S.median(old) - S.median(young))
            roles[role] += 1
    if diffs:
        up = sum(1 for d in diffs if d > 0)
        print("   %d spans with both ends; paired old-minus-young ms/call:" % len(diffs))
        print("   med %+0.5f  mean %+0.5f  positive %d/%d  (raid-1-sized ramp predicts ~+0.07)"
              % (S.median(diffs), S.mean(diffs), up, len(diffs)))
        print("   roles: %s" % ", ".join("%s %d" % (r, c) for r, c in roles.most_common(6)))
    else:
        print("   no span reaches both ends - the maps with old bots have no young windows")
        print("   for the same bots; report what pooled buckets alone can say.")
    print()

    # ---- 5. warm-up sensitivity ----------------------------------------------------------
    print("5. WARM-UP SENSITIVITY: headline medians at warmup 60 vs 180 s. The 60 s rule's")
    print("   equivalence proof covered only 60 s windows; this leg is the first at 30 s.")
    for wu in (60, 180):
        ws = kept_windows(samples, wu)
        gate = S.median([w["updateManual"]["awakeMs"] / w["frames"] for w in ws])
        mpc = S.median([w["updateManual"]["awakeMs"] / w["updateManual"]["awakeCalls"]
                        for w in ws if w["updateManual"]["awakeCalls"]])
        fr = S.median([(w.get("frame") or {}).get("avg") for w in ws])
        print("   warmup %3ds: n %3d  gateMs %.3f  ms/call %.4f  frame avg %.2f"
              % (wu, len(ws), gate, mpc, fr))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
