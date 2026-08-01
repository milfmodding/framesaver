"""THE FEASIBILITY QUESTION: is Framesaver chasing lost milliseconds, and what is reachable?

Asked by Sophia 2026-08-01. Answered against the gate AS SHE REVISED IT on 2026-07-28 -
p50 floor of 60 fps on every map, 100 aspirational - NOT the p75 bar that had crept back
into ALPHA-STATE.md. Both are printed, because the verdict differs and the difference is the
kind of thing that gets quoted wrong.

THIS FILE CARRIES A DISCONFIRMED FIRST ATTEMPT ON PURPOSE. My first instrument priced the
mechanism's ceiling as the phases it directly occupies - animation + Unity AI + the stand-by
scheduling pool - and concluded TarkovStreets was UNREACHABLE by arithmetic: a 12.24 ms p75
deficit against a 6.70 ms pool, 55% cover, no implementation could close it. That conclusion
was WRONG, and the corpus already contained its refutation:

    Streets, matched at 21.5 vs 22.0 median bots, mod-on p50 14.48 ms vs mod-off 26.11 ms.
    An 11.63 ms improvement from a pool that only differs by 4.09 ms.

The mechanism has DOWNSTREAM LEVERAGE. A bot whose animator is culled stops evaluating its
state machine - that is the phase saving - and also stops writing bones, which stops skinning,
cloth, transform-hierarchy propagation and the script work that rides on them. Those live in
phases I had excluded as "not ours to claim". Across six maps the frame saving is consistently
2-3x the pool saving, so a ceiling built from the mechanism's own phases UNDERSTATES it by
roughly that factor. Pricing a mechanism at the phase it occupies is the mistake; it is the
same error as pricing stand-by by aiTotal, one level out.

WHAT IS AND IS NOT ESTABLISHED HERE. Every mod-on/mod-off pair below is BETWEEN-MARATHON:
different day, different build, different route. That design has already failed on this
project for small effects, and the honest statement of its status is that it is admissible
here only because these effects are large - 3.6 to 11.6 ms, against a residual that spanned
zero at fractions of a millisecond. It is evidence of MAGNITUDE and ORDERING, not of per-map
attribution, and the within-raid A/B is what converts it. Nothing here licenses a per-map
"+N fps" claim; those were withdrawn once already.

Confounds, named rather than caveated away:
  - Route and spawn composition differ per leg. Bot totals happen to match closely (within
    1-3 on six of nine maps), which is why the comparison is worth printing at all, but a
    matched COUNT is not a matched fight, a matched position, or a matched loot route.
  - Build differs: mod-on legs are 2026-07-28/29, mod-off is 2026-07-31.
  - The AI mod stack is constant across every log read here - all of them post-date the
    SPT4.0.13 install created 2026-07-26 15:28:36, so BigBrain/Waypoints/SAIN/LootingBots
    are present on both sides. This was the confound most likely to invalidate the whole
    table and it does not apply.
  - updateManual is ABSENT from the 07-28 logs entirely; the field was added later. Absent
    is printed as n/a, never as zero.
"""
import collections
import glob
import json
import os
import statistics as S
import sys

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
WARMUP = 60.0
GATE_P50 = 1000.0 / 60.0          # Sophia's revised gate, 2026-07-28
ASPIRATION = 1000.0 / 100.0

# Phases the mechanism DIRECTLY occupies. Kept as its own quantity so the leverage ratio
# below is visible rather than assumed.
DIRECT = (
    "PreLateUpdate/DirectorUpdateAnimationBegin",
    "PreLateUpdate/DirectorUpdateAnimationEnd",
    "PreLateUpdate/LegacyAnimationUpdate",
    "PreUpdate/AIUpdate",
    "PreLateUpdate/AIUpdatePostScript",
)


def read_log(path):
    hdr, samples = None, []
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") == "header" and hdr is None:
            hdr = o
        elif o.get("type") == "sample" and o.get("state") == "raid":
            samples.append(o)
    return hdr, samples


def post_warmup(samples):
    """Warm-up rule in one place. Absence is a third value: a window whose rule cannot be
    evaluated is counted as unreadable, never silently kept or dropped."""
    seg = collections.defaultdict(list)
    for o in samples:
        seg[(o.get("raid"), str(o.get("map")))].append(o)
    keep, unreadable, examined = collections.defaultdict(list), 0, 0
    for k in seg:
        for o in seg[k][:-1]:                     # drop each segment's teardown window
            examined += 1
            el, ws = o.get("raidElapsed"), o.get("windowSec")
            if el is None or ws is None:
                unreadable += 1
            elif el - ws >= WARMUP:
                keep[k[1]].append(o)
    return keep, unreadable, examined


def med(xs):
    xs = [x for x in xs if x is not None]
    return S.median(xs) if xs else None


def f(v, spec="%6.2f"):
    return (spec % v) if v is not None else " " * (len(spec % 0) - 3) + "n/a"


def direct_pool(w):
    tot = 0.0
    for nm in DIRECT:
        p = (w.get("phases") or {}).get(nm)
        if not isinstance(p, dict) or p.get("avg") is None:
            return None                            # absent phase invalidates the sum
        tot += p["avg"]
    return tot


def leg_stats(ws):
    return {
        "n": len(ws),
        "p50": med([(w.get("framePct") or {}).get("p50") for w in ws]),
        "p75": med([(w.get("framePct") or {}).get("p75") for w in ws]),
        "pool": med([direct_pool(w) for w in ws]),
        "bots": med([(w.get("bots") or {}).get("total") for w in ws]),
        "asleep": med([(w.get("bots") or {}).get("asleep") for w in ws]),
    }


def arm_of(cfg):
    sb, fa = cfg.get("standByEnabled"), cfg.get("forceAllRoles")
    if sb is False:
        return "modoff"
    if sb is True and fa is True:
        return "forceAll"
    if sb is True and fa is False:
        return "default"
    return "unknown"


def main():
    paths = sorted(glob.glob(os.path.join(LOGDIR, "*.ndjson")))
    print("SOURCE   %s" % LOGDIR)
    print("LOGS     %d found" % len(paths))
    if not paths:
        print("REFUSED: no logs")
        return 2

    arms = collections.defaultdict(lambda: collections.defaultdict(list))
    unread_tot, used, preschema = 0, 0, []
    for p in paths:
        hdr, samples = read_log(p)
        keep, unread, examined = post_warmup(samples)
        # `windowSec` was added to the sample schema on 2026-07-28 midday. Logs older than
        # that cannot be evaluated against the warm-up rule at all, so they are OUT OF
        # POPULATION by name and count - not relaxed into it, and not silently dropped.
        if examined and unread == examined:
            preschema.append((os.path.basename(p), examined))
            continue
        unread_tot += unread
        if not keep:
            continue
        arm = arm_of((hdr or {}).get("config") or {})
        if arm == "unknown":
            print("  SKIP (unknown arm): %s" % os.path.basename(p))
            continue
        used += 1
        for mp, ws in keep.items():
            arms[arm][mp].extend(ws)
    print("WINDOWS  %d logs contributed post-warmup windows, %d unreadable" % (used, unread_tot))
    print("EXCLUDED %d logs pre-date the windowSec field (%d in-raid windows), so the warm-up"
          % (len(preschema), sum(n for _, n in preschema)))
    print("         rule cannot be evaluated on them at all: %s"
          % ", ".join(b[10:-7] for b, _ in preschema[:4]) + (" ..." if len(preschema) > 4 else ""))
    if unread_tot:
        print("REFUSED: %d windows in post-schema logs are unreadable" % unread_tot)
        return 2

    off, on = arms.get("modoff", {}), arms.get("default", {})
    if not off or not on:
        print("REFUSED: need both a mod-off and a default-arm population")
        return 2

    # ---- 1. the gate, mod-off ------------------------------------------------------------
    print()
    print("1. MOD-OFF BASELINE against the gate (p50 >= 60 fps; 100 aspirational).")
    print("   %-14s %4s %8s %7s %8s %7s %6s" % ("map", "n", "p50 ms", "p50 fps",
                                                "gate", "p75 fps", "bots"))
    for mp in sorted(off, key=lambda m: -(leg_stats(off[m])["p50"] or 0)):
        s = leg_stats(off[mp])
        print("   %-14s %4d %8s %7s %8s %7s %6s"
              % (mp, s["n"], f(s["p50"]), f(1000 / s["p50"], "%5.1f") if s["p50"] else "n/a",
                 "PASS" if s["p50"] and s["p50"] <= GATE_P50 else "FAIL",
                 f(1000 / s["p75"], "%5.1f") if s["p75"] else "n/a", f(s["bots"], "%4.1f")))

    # ---- 2. matched mod-on vs mod-off ----------------------------------------------------
    print()
    print("2. DEFAULT ARM vs MOD-OFF, same map. BETWEEN-marathon - evidence of magnitude and")
    print("   ordering, not per-map attribution. 'lev' = frame gain / pool gain: how far past")
    print("   its own phases the mechanism reaches.")
    print()
    print("   %-14s %11s %11s %8s %9s %8s %5s %11s"
          % ("map", "off p50", "on p50", "gain ms", "on fps", "pool gain", "lev", "bots off/on"))
    levs = []
    for mp in sorted(set(off) & set(on), key=lambda m: -(leg_stats(off[m])["p50"] or 0)):
        a, b = leg_stats(off[mp]), leg_stats(on[mp])
        if a["p50"] is None or b["p50"] is None:
            continue
        gain = a["p50"] - b["p50"]
        pg = (a["pool"] - b["pool"]) if (a["pool"] is not None and b["pool"] is not None) else None
        lev = (gain / pg) if (pg and pg > 0.05) else None
        if lev is not None:
            levs.append(lev)
        print("   %-14s %6s(n=%2d) %6s(n=%2d) %8s %9s %8s %5s   %4.1f/%4.1f"
              % (mp, f(a["p50"]), a["n"], f(b["p50"]), b["n"], f(gain, "%+6.2f"),
                 f(1000 / b["p50"], "%6.1f"), f(pg, "%+6.2f"),
                 f(lev, "%4.1fx") if lev else " n/a", a["bots"] or 0, b["bots"] or 0))
    if levs:
        print()
        print("   leverage across %d maps: median %.1fx  range %.1f-%.1fx"
              % (len(levs), S.median(levs), min(levs), max(levs)))
        print("   A ceiling built from the mechanism's own phases understates it by that much.")

    # ---- 3. the gate under the mod --------------------------------------------------------
    print()
    print("3. WHERE THE GATE STANDS on the default arm, and what is left.")
    fails, asp = [], []
    for mp in sorted(on):
        s = leg_stats(on[mp])
        if s["p50"] is None:
            continue
        if s["p50"] > GATE_P50:
            fails.append((mp, 1000 / s["p50"], s["n"]))
        elif s["p50"] > ASPIRATION:
            asp.append((mp, 1000 / s["p50"], s["n"]))
    print("   below the 60 gate : %s"
          % (", ".join("%s %.1f (n=%d)" % t for t in fails) or "NONE"))
    print("   past 60, below 100: %s"
          % (", ".join("%s %.1f (n=%d)" % t for t in asp) or "none"))
    fa = arms.get("forceAll", {})
    if fa:
        print()
        print("   forceAllRoles legs, the largest lever we hold and do not ship by default:")
        for mp in sorted(fa):
            s, d = leg_stats(fa[mp]), leg_stats(on.get(mp, []))
            if s["p50"] and d.get("p50"):
                print("     %-14s %5.1f fps vs %5.1f default  (asleep %s vs %s of %s)"
                      % (mp, 1000 / s["p50"], 1000 / d["p50"], f(s["asleep"], "%4.1f"),
                         f(d["asleep"], "%4.1f"), f(s["bots"], "%4.1f")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
