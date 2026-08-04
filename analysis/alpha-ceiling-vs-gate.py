"""SUPERSEDED 2026-08-01 by `alpha-feasibility.py`, AND ITS HEADLINE CONCLUSION IS WRONG.
Kept for the reasoning, never for the verdict. Do not quote this file's output.

It concluded TarkovStreets was unreachable by arithmetic - 12.24 ms p75 deficit against a
6.70 ms pool, 55% cover. The error is in the premise, not the arithmetic: it prices the
mechanism at the phases it OCCUPIES, and the mechanism's effect propagates into phases it
never appears in (bone writes, skinning, cloth, transform propagation). Measured leverage is
a median 2.8x, so this file understates the ceiling by roughly that factor. The corpus already
held the refutation - Streets matched at 21.5 vs 22.0 bots runs 11.63 ms faster mod-on from
pools differing by 4.10 ms.

The gate it uses is also wrong: p75 is correct, but this file was written believing p50 was
the bar. See ALPHA-STATE.md for why that flipped twice in one day.

Original docstring follows.

THE FEASIBILITY QUESTION, as arithmetic: can Framesaver's mechanism reach 60 fps on
each map even in the limit of a PERFECT implementation?

Asked by Sophia 2026-08-01: "given everything you've seen, what is possible? Are we stuck
on a snipe hunt chasing after these lost milliseconds?"

The shape of the answer does not need a coefficient, an A/B, or a working build. It needs
two directly measured quantities per map and a subtraction:

  DEFICIT     = mod-off frame time - 16.67 ms      (what must be removed to reach 60 fps)
  ADDRESSABLE = every pool our mechanism could ever touch, summed, priced at 100% removal

If ADDRESSABLE < DEFICIT the map cannot reach 60 fps through this mod at ANY quality of
implementation. That is arithmetic over measurements we already hold, not a prediction, and
no further raid can change it. If ADDRESSABLE > DEFICIT the map is reachable in principle
and the question becomes what fraction we actually capture - which IS an empirical question
and is what the A/B is for.

ADDRESSABLE IS DELIBERATELY GENEROUS - it is a ceiling, not an estimate. It credits us with:
  - the entire AI scheduling pool (updateManual.awakeMs/frames) driven to zero, though
    stand-by only pauses non-player bots and the observed paused cost is not zero;
  - the entire animator pool, though the PLAYER and every non-bot animated object lives in
    those same phases and no cull of ours will ever touch them;
  - the entire Unity AI/NavMesh pool, though pathfinding for the player's own colliders and
    for scenery lives there too.
A generous ceiling is the right instrument for an infeasibility question: if even the
inflated pool cannot cover the deficit, the honest ceiling certainly cannot, and the
conclusion is robust to every objection about attribution. It is the WRONG instrument for a
promise - nothing here is a claim about what the mod delivers.

POSITIVE CONTROL, and this script REFUSES rather than reporting if it fails: the whole
argument assumes phases[].avg is per-frame milliseconds. If it is instead a per-window sum,
or per-call, every subtraction below is meaningless while still printing plausible numbers -
the house failure. So we check that the eight top-level PlayerLoop phases sum to the
measured frame time. They partition the frame by construction, so agreement is evidence the
unit is what we think; disagreement means stop.

Known limits, stated because a ceiling argument is only as good as its population:
  - One leg per map, from the one clean mod-off marathon (166 post-warmup windows).
    Bot composition and route vary per run; the ORDERING is stable across the corpus but a
    single map's deficit carries that run's spawns.
  - Mod-off is the right baseline for "what must be removed" and says nothing about what a
    mod-on build achieves.
  - Frame time here is the p75 of window medians, matching the gate instrument. p50 is
    reported alongside because the two answer different questions and mixing them is how
    the withdrawn per-map figures got withdrawn.
"""
import collections
import glob
import json
import os
import statistics as S
import sys

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
MARATHON = os.path.join(LOGDIR, "framesaver-20260731-112704-modoff-marathon.ndjson")
WARMUP = 60.0
GATE_MS = 1000.0 / 60.0

# The pools our mechanism could conceivably touch. Named individually so a reader can
# strike one and re-run rather than having to trust the grouping.
ANIMATOR = (
    "PreLateUpdate/DirectorUpdateAnimationBegin",
    "PreLateUpdate/DirectorUpdateAnimationEnd",
    "PreLateUpdate/LegacyAnimationUpdate",
)
UNITY_AI = (
    "PreUpdate/AIUpdate",
    "PreLateUpdate/AIUpdatePostScript",
)
TOPLEVEL = (
    "TimeUpdate", "Initialization", "EarlyUpdate", "FixedUpdate",
    "PreUpdate", "Update", "PreLateUpdate", "PostLateUpdate",
)


def read_log(path):
    header, samples = None, []
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") == "header" and header is None:
            header = o
        elif o.get("type") == "sample" and o.get("state") == "raid":
            samples.append(o)
    return header, samples


def post_warmup(samples):
    """Warm-up rule in ONE place, and absence is a third value: a window whose rule cannot
    be evaluated is dropped as UNREADABLE and counted, never silently kept or excluded."""
    seg = collections.defaultdict(list)
    for o in samples:
        seg[(o.get("raid"), str(o.get("map")))].append(o)
    keep, unreadable, teardown, warm = [], 0, 0, 0
    for k in sorted(seg, key=lambda x: (x[0] is None, x[0])):
        windows = seg[k]
        teardown += 1 if windows else 0
        for o in windows[:-1]:          # last in-raid window of a segment is teardown
            el, ws = o.get("raidElapsed"), o.get("windowSec")
            if el is None or ws is None:
                unreadable += 1
                continue
            if el - ws >= WARMUP:
                keep.append(o)
            else:
                warm += 1
    return keep, unreadable, teardown, warm


def ph(o, name):
    """Phase avg, or None if the phase is absent. Absent is not zero."""
    p = (o.get("phases") or {}).get(name)
    if not isinstance(p, dict):
        return None
    return p.get("avg")


def pool(o, names):
    """Sum of named phases. Returns (total, n_missing) so missing is visible, not folded."""
    tot, missing = 0.0, 0
    for nm in names:
        v = ph(o, nm)
        if v is None:
            missing += 1
        else:
            tot += v
    return tot, missing


def ai_sched_ms(o):
    """updateManual.awakeMs is a per-window SUM over calls; per frame it is /frames.
    Returns None when either side is absent."""
    um, fr = o.get("updateManual"), o.get("frames")
    if not isinstance(um, dict) or not fr:
        return None
    aw = um.get("awakeMs")
    return None if aw is None else aw / fr


def p75(xs):
    """75th percentile, nearest-rank. Frame time p75 = the SLOW tail, which is the gate."""
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.75 * (len(s) - 1))))]


def main():
    print("SOURCE   %s" % MARATHON)
    if not os.path.exists(MARATHON):
        print("REFUSED: marathon log not found at that path")
        return 2
    header, samples = read_log(MARATHON)
    cfg = (header or {}).get("config") or {}
    keep, unreadable, segs, warm = post_warmup(samples)
    print("WINDOWS  %d in-raid, %d kept post-warmup, %d in warm-up, %d teardown, "
          "%d UNREADABLE" % (len(samples), len(keep), warm, segs, unreadable))
    print("ARM      standByEnabled=%r forceAllRoles=%r  (mod-off baseline)"
          % (cfg.get("standByEnabled"), cfg.get("forceAllRoles")))
    if unreadable:
        print("REFUSED: %d windows could not be evaluated against the warm-up rule" % unreadable)
        return 2
    if not keep:
        print("REFUSED: no post-warmup windows")
        return 2

    # ---- POSITIVE CONTROL: is phases[].avg per-frame ms? --------------------------------
    print()
    print("POSITIVE CONTROL - phases[].avg must be per-frame ms, else every number below is")
    print("meaningless. The 8 top-level PlayerLoop phases partition the frame, so their sum")
    print("must track the measured frame time.")
    resid = []
    for o in keep:
        tot, missing = pool(o, TOPLEVEL)
        fr = (o.get("frame") or {}).get("avg")
        if missing or not fr:
            continue
        resid.append(tot / fr)
    if not resid:
        print("  REFUSED: could not evaluate the control on any window")
        return 2
    med = S.median(resid)
    print("  sum(top-level phases) / frame :  median %.3f   min %.3f   max %.3f   (n=%d)"
          % (med, min(resid), max(resid), len(resid)))
    if not 0.90 <= med <= 1.10:
        print("  REFUSED: ratio %.3f is not ~1.0, so avg is NOT per-frame ms. Stop here."
              % med)
        return 2
    print("  PASS - within 10%% of unity, the unit is per-frame ms as assumed.")

    # ---- the table ----------------------------------------------------------------------
    by_map = collections.defaultdict(list)
    for o in keep:
        by_map[str(o.get("map"))].append(o)

    print()
    print("CEILING vs GATE, per map. All ms/frame. 'addressable' credits 100%% removal of")
    print("every pool the mechanism could touch and is therefore an UPPER BOUND, not a")
    print("forecast. cover = addressable / deficit.")
    print()
    print("  %-14s %5s %7s %7s %8s %7s %7s %8s %8s  %s"
          % ("map", "n", "p50ms", "p75ms", "p75fps", "deficit", "anim", "unityAI",
             "aiSched", "cover"))

    rows = []
    def sortkey(m):
        v = [(w.get("framePct") or {}).get("p75") for w in by_map[m]]
        v = [x for x in v if x is not None]
        return -(S.median(v) if v else 0)

    for mp in sorted(by_map, key=sortkey):
        ws = by_map[mp]
        # The gate is a PER-FRAME p75, which the log carries directly in framePct. Taking a
        # percentile of window means would answer a different and easier question.
        f75s = [(w.get("framePct") or {}).get("p75") for w in ws]
        f50s = [(w.get("framePct") or {}).get("p50") for w in ws]
        if any(v is None for v in f75s) or any(v is None for v in f50s):
            print("  %-14s REFUSED: framePct.p50/p75 absent in some windows" % mp)
            return 2
        f75, f50 = S.median(f75s), S.median(f50s)
        anim = [pool(w, ANIMATOR) for w in ws]
        uai = [pool(w, UNITY_AI) for w in ws]
        if any(m for _, m in anim) or any(m for _, m in uai):
            print("  %-14s REFUSED: a named phase is absent in some windows" % mp)
            return 2
        a_med = S.median([t for t, _ in anim])
        u_med = S.median([t for t, _ in uai])
        sched = [ai_sched_ms(w) for w in ws]
        if any(s is None for s in sched):
            print("  %-14s REFUSED: updateManual or frames absent in some windows" % mp)
            return 2
        s_med = S.median(sched)
        deficit = f75 - GATE_MS
        addressable = a_med + u_med + s_med
        cover = (addressable / deficit) if deficit > 0 else None
        rows.append((mp, f75, deficit, addressable, cover))
        print("  %-14s %5d %7.2f %7.2f %8.1f %7.2f %7.2f %8.2f %8.3f  %s"
              % (mp, len(ws), f50, f75, 1000.0 / f75, deficit, a_med, u_med, s_med,
                 "PASSES ALREADY" if deficit <= 0
                 else ("%.0f%%" % (100.0 * cover)) + ("  REACHABLE" if cover >= 1
                                                      else "  UNREACHABLE")))

    print()
    print("VERDICT PER MAP - 'unreachable' means no implementation of THIS mechanism gets")
    print("the map to 60 fps p75, because the pools it can touch are smaller than the gap.")
    already = [r[0] for r in rows if r[2] <= 0]
    reach = [r[0] for r in rows if r[2] > 0 and r[4] is not None and r[4] >= 1]
    unreach = [r[0] for r in rows if r[2] > 0 and r[4] is not None and r[4] < 1]
    print("  passes mod-off already : %s" % (", ".join(already) or "none"))
    print("  reachable in principle : %s" % (", ".join(reach) or "none"))
    print("  UNREACHABLE by arithmetic: %s" % (", ".join(unreach) or "none"))
    print()
    print("  %d of %d maps pass or are reachable; %d cannot be reached at any implementation"
          % (len(already) + len(reach), len(rows), len(unreach)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
