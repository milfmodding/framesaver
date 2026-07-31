"""Animator cost per animating bot, fitted WITHIN an arm on FRAME-WEIGHTED regressors.

SUPERSEDES the fit in `alpha-animator-slope.py`, which regressed on `bots.awake` - an instantaneous
sample read once at the window boundary (`CountBots`, one call site, Telemetry.cs:1314) - against a
window aggregate. That pairing attenuates the slope toward zero, and the attenuation is what
produced this file. Read that one for the history; use this one for the number.

WHAT GAMMA POINTED OUT, and it needed no new telemetry: `BotsClass.UpdateByUnity` iterates every bot
without filtering on BotState, so `UpdateManual` runs once per bot per frame. That makes

    (awakeCalls - deadCalls) / frames            frame-weighted mean LIVE NON-PAUSED bots
    (awakeCalls + pausedCalls - deadCalls) / frames   frame-weighted mean ALL LIVE bots

genuine window aggregates over exactly the frames `phases[].avg` covers - the two reset blocks are
eight lines apart. `deadCalls` is a SUBSET of `awakeCalls`, not a fourth bucket, so it subtracts.

VERIFIED, not assumed. Gamma refused to guess the denominator and specified a calibration instead:
on windows with zero within-window stand-by transitions AND an endpoint `awake` matching the previous
window, `(awakeCalls - deadCalls) / D == bots.awake` must hold; solve for D. Run on the mod-off
marathon, 44 qualifying windows: **D / frames has median 1.000**, and `frames == n` in every row. So
the once-per-frame assumption holds and the denominator is `frames`. The spread, 0.718 to 1.043, is
roster churn within a window - and it is also a direct measurement of how far the endpoint sample
strays from the true mean, i.e. of the attenuation itself.

WHICH REGRESSOR IS RIGHT DEPENDS ON THE ARM, and that is the whole finding:

  * cull OFF - nothing is culled, so every LIVE bot animates      -> ALL LIVE
  * cull ON  - sleeping bots carry CullCompletely and do not      -> NON-PAUSED

That was pre-registered as a prediction on 2026-07-31 and appeared to FAIL: slopes against
`awake + asleep` came back ~0 with |r| < 0.4 on seven of nine maps. It failed on the endpoint
sample. On aggregates the predicted pattern appears, and it appears most strongly exactly where it
should - Interchange, where 15 of 21 bots are asleep-but-animating, goes from -0.064 (r -0.60) to
**+0.314 (r 0.91)**. Factory, where nothing ever sleeps, returns IDENTICAL columns, which is the
internal control: with no paused bots the two regressors are arithmetically the same quantity.
"""
import collections
import glob
import json
import os
import statistics as S

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
ANIM = "PreLateUpdate/DirectorUpdateAnimationBegin"
WARMUP_SEC = 60
MIN_WINDOWS = 5
STRONG_R = 0.8


def arm_of(cfg):
    standby, force = cfg.get("standByEnabled"), cfg.get("forceAllRoles")
    if standby is None or force is None:
        return "unknown"
    return "modOff" if not standby else ("forceAll" if force else "modOn")


def load():
    out = collections.defaultdict(list)
    for path in sorted(glob.glob(os.path.join(LOGDIR, "*.ndjson"))):
        arm, rows = None, []
        for ln in open(path, encoding="utf-8-sig", errors="replace"):
            ln = ln.strip()
            if not ln.endswith("}"):
                continue
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            if o.get("type") == "header":
                arm = arm_of(o.get("config") or {})
                continue
            if o.get("type") != "sample" or o.get("state") != "raid":
                continue
            el, ws = o.get("raidElapsed"), o.get("windowSec")
            if el is None or ws is None or el - ws < WARMUP_SEC:
                continue
            rows.append(o)
        segs = collections.defaultdict(list)
        for o in rows:
            segs[(o.get("raid"), str(o.get("map")))].append(o)
        for (_r, mp), ws in segs.items():
            for o in ws[:-1]:  # teardown window: census reads after the game object is gone
                ph = (o.get("phases") or {}).get(ANIM)
                um = o.get("updateManual") or {}
                fr = o.get("frames")
                ac, dc, pc = um.get("awakeCalls"), um.get("deadCalls"), um.get("pausedCalls")
                if not isinstance(ph, dict) or ph.get("avg") is None or not fr:
                    continue
                if ac is None or dc is None or pc is None:
                    continue
                out[(mp, arm)].append({"nonPaused": (ac - dc) / fr,
                                       "allLive": (ac + pc - dc) / fr,
                                       "anim": ph["avg"]})
    return out


def fit(pts, key):
    xs = [p[key] for p in pts]
    ys = [p["anim"] for p in pts]
    n = len(xs)
    if n < MIN_WINDOWS or len(set(xs)) < 3:
        return None, None
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if den == 0 or sy == 0:
        return None, None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / den, cov / (den ** 0.5 * sy)


def main():
    data = load()
    if not data:
        print("REFUSED: no windows carry both %s and updateManual" % ANIM)
        return 2

    print("ANIMATOR MS vs FRAME-WEIGHTED BOT COUNT, within one arm - build, day and route fixed.")
    print("The correct regressor differs by arm: ALL LIVE when the cull is off, NON-PAUSED when on.")
    print()
    print("  %-14s %-9s %4s   %-16s   %-16s  %s"
          % ("map", "arm", "n", "vs non-paused", "vs ALL LIVE", "expected regressor"))
    print("  " + "-" * 86)

    picked = collections.defaultdict(list)
    for (mp, arm) in sorted(data):
        pts = data[(mp, arm)]
        a, ra = fit(pts, "nonPaused")
        b, rb = fit(pts, "allLive")
        if a is None or b is None:
            continue
        want = "ALL LIVE" if arm == "modOff" else "non-paused"
        slope, r = (b, rb) if want == "ALL LIVE" else (a, ra)
        mark = "  <- strong" if abs(r) >= STRONG_R else ""
        print("  %-14s %-9s %4d   %8.3f %6.2f      %8.3f %6.2f  %s%s"
              % (mp, arm, len(pts), a, ra, b, rb, want, mark))
        if abs(r) >= STRONG_R:
            picked[arm].append((mp, slope))

    print()
    for arm in sorted(picked):
        vals = [s for _, s in picked[arm]]
        print("  %s, maps with |r| >= %.1f on the expected regressor:" % (arm, STRONG_R))
        print("    %s" % ", ".join("%s %.3f" % (m, s) for m, s in picked[arm]))
        print("    median %.3f ms of animator cost per animating bot, over %d map(s)."
              % (S.median(vals), len(vals)))
    print()
    print("  Against ~0.011 ms per awake bot for what stand-by's own UpdateManual gating saves")
    print("  (updateManual.awakeMs / awakeCalls, paused 0.0002-0.0005). The cull is the larger")
    print("  mechanism by more than an order of magnitude; stand-by only selects its targets.")
    print()
    print("  STILL NOT A PER-ARM EFFECT SIZE. These are slopes within an arm, so they say what an")
    print("  animating bot costs - not what the cull saves, which needs the population it moves")
    print("  and a paired difference across arms. protocol-anim-cull.ini is that design, and its")
    print("  prediction is registered as a LEVEL shift of 0.5-2.5 ms before any data exists.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
