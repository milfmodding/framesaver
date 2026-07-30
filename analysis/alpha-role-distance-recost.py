"""Recost role-aware sleep distance against the mechanism we would ACTUALLY ship.

BETA'S CORRECTION, and it is a mechanism error not an arithmetic one. My 4.72 ms priced every
exempt-role bot on Lighthouse as permanently awake, because that is what the EXEMPTION path does:
`LongRangeExemption` short-circuits with `Wake()` before the distance check, so an exempt bot is
awake at any range, forever. That is rank-bounded on purpose - "keeping the N nearest awake costs
exactly N bots no matter how many exist."

But the thing Sophia asked for is not an exemption. It is a longer SLEEP DISTANCE for certain
roles: a Rogue with 350 m still sleeps at 500 m. The exemption mechanism cannot express that
because it has no upper bound. And the distance version is the smaller change -
`BotStandByInitPointsPatch` already writes DIST_TO_SLEEP and DIST_TO_ACTIVATE in its postfix.

So the honest cost is not "all exempt-role bots" but "exempt-role bots INSIDE the role distance",
which depends on where the player is, so it has to be computed per window against real positions.

METHOD, AND ITS ONE REAL WEAKNESS. Sample lines carry the player's `pos` per window; botSpawn lines
carry each bot's spawn `pos`. Distance is measured player-to-spawn-position, which is a good proxy
ONLY for statically posted bots. Lighthouse's Rogues post at the water treatment plant and stay
there, so it holds for them. It would NOT hold for a patrolling role, and any such role in the
output should be read as unreliable rather than as a measurement.

Horizontal distance, because Unity's y is vertical and a rooftop gunner 30 m up is not further away
in any sense the sleep check cares about - DIST_TO_SLEEP is compared against a 3D distance in
vanilla, but the difference is second-order next to the proxy weakness above.

SECOND WEAKNESS, found by reading the field instead of assuming it. The sample `pos` is not a
coordinate - it is a summary: `x`/`y`/`z` are RANGES over the window, plus `end` (position at window
close), `dist` (distance travelled) and a look-sweep. So there is no single player position per
window. `end` is used, and `dist` is reported beside it, because the player covered up to ~150 m
inside a single window - which is first-order for the 150 m radius and second-order for 350 m. A
window with large travel makes its own row unreliable and the median travel is printed so that is
visible rather than buried.
"""
import glob
import json
import math
import os
import statistics
import sys

LOGS = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
DISTANCES = [150, 250, 350, 450]
# Roles proposed for a longer sleep distance, and posted rather than patrolling on Lighthouse.
ROLES = {"exusec", "bosszryachiy", "followerzryachiy", "bossboarsniper", "marksman",
         "bosskojaniy", "followerkojaniy"}
MS_PER_BOT_ANIMATOR = 0.244   # measured raid 1.5, counted change over measured level


def horiz(a, b):
    return math.hypot(b[0] - a[0], b[2] - a[2])


def main():
    paths = [p for p in sorted(glob.glob(os.path.join(LOGS, "*.ndjson")))]
    any_out = False
    for path in paths:
        spawns, windows = [], []
        for ln in open(path, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln.endswith("}"):
                continue
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            t = o.get("type")
            if t == "botSpawn" and str(o.get("role", "")).lower() in ROLES:
                p = o.get("pos")
                if isinstance(p, list) and len(p) == 3:
                    spawns.append((str(o["role"]), p))
            elif t == "sample" and o.get("state") == "raid" and not o.get("final"):
                # `pos` is a summary object, not a triple. `end` is the position at window close.
                pb = o.get("pos")
                p = pb.get("end") if isinstance(pb, dict) else None
                if isinstance(p, list) and len(p) == 3:
                    windows.append((o.get("window"), str(o.get("map")), p,
                                    (o.get("bots") or {}).get("awake"),
                                    (pb.get("dist") if isinstance(pb, dict) else None)))
        if not spawns or not windows:
            continue
        any_out = True
        print("=== %s" % os.path.basename(path))
        print("    %d posted-role spawns, %d in-raid windows with a player position"
              % (len(spawns), len(windows)))

        print("    %-8s %10s %10s %10s   %s"
              % ("role dist", "median in", "max in", "min in", "animator ms at median"))
        for d in DISTANCES:
            counts = [sum(1 for _r, sp in spawns if horiz(p, sp) <= d)
                      for _w, _m, p, _a, _dist in windows]
            med = statistics.median(counts)
            print("    %6d m %10.0f %10d %10d   %6.2f ms"
                  % (d, med, max(counts), min(counts), med * MS_PER_BOT_ANIMATOR))

        print("    for comparison, the EXEMPTION mechanism keeps all %d awake at any range"
              % len(spawns))
        print("      -> %.2f ms of animator, which is the figure I gave Sophia"
              % (len(spawns) * MS_PER_BOT_ANIMATOR))
        travel = [t for _w, _m, _p, _a, t in windows if t]
        if travel:
            print("    median player travel per window %.0f m, max %.0f - a row is only as good"
                  % (statistics.median(travel), max(travel)))
            print("      as its travel is small next to the radius being tested")
        obs = [a for _w, _m, _p, a, _t in windows if a is not None]
        if obs:
            print("    observed bots.awake in this leg: median %.0f (treatment had ALL roles "
                  "sleepable)" % statistics.median(obs))
        print()

    if not any_out:
        print("REFUSED: no log carries both posted-role spawn positions and player positions.")
        return 2
    print("READ IT AS: the distance mechanism costs what is INSIDE the radius, and only the")
    print("exemption mechanism costs the whole set. The gap between those two columns is Beta's")
    print("correction, and it is a mechanism difference rather than an arithmetic one.")
    print()
    print("PROXY WEAKNESS, restated because it bounds every number above: bot position is taken")
    print("from the SPAWN record, so this is only valid for roles that post and stay. It holds")
    print("for Lighthouse Rogues and would not hold for a patrolling role.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
