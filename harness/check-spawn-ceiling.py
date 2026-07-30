"""Post-flight refusal: did any role spawn more times than the database can declare?

WHY THIS EXISTS, and it is a near-miss rather than a theory. Beta audited what our
`DeactivateSleepingBotState` makes us drive and found that `BotOwner.BotState`'s setter fires
`OnBotStateChange`, which vanilla raises a handful of times per bot per raid and we now raise on
EVERY sleep and EVERY wake. One of its five subscribers is
`BossSpawnerClass.Class334.method_0`, which **spawns the boss's followers**. It unsubscribes
itself on the same edge, so we are fine. Had it not, every wake of a sleeping boss would have
spawned another escort group.

One line of BSG's code stands between this mod and garrison multiplication, and the failure
would have been SILENT: the bot ledger would have recorded every extra escort, because
`botSpawn` hooks `BotOwner.Create` - but nothing CHECKED it. The reconciler treats
ledger-above-census as a despawn count and reports it. `alpha-role-exemption-cost.py` compares
observed against expectation but only when run by hand, during analysis, days later.

Seen but not checked is the shape this project keeps finding. So: checked.

WHAT IT COMPARES. Observed `botSpawn` lines per role against the CEILING the map's `base.json`
can produce - every declared amount summed with chance ignored, which is the largest number the
database permits. Exceeding it means bots appeared that no declaration accounts for.

WHERE IT IS TIGHT AND WHERE IT IS NOT, stated because a check whose sensitivity varies by role
must not be read as uniform. It is TIGHT for unique named bots - the Goons declare one each, so
a second `followerBigPipe` is unambiguous, and those are exactly the followers that
`Class334.method_0` would have duplicated. It is LOOSE for numerous roles: Lighthouse declares
up to 22 `exUsec` against 5-6 observed, so multiplication would have to add fifteen before this
notices. A tight bound on the case that would fail, a weak bound elsewhere, and no pretence of
being uniform.

EXIT 0 pass, 1 a role exceeded its ceiling, 2 refused to report.
"""
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

DB = r"F:\SPT\SPT4.0.13\SPT\SPT_Data\database\locations"

# Telemetry `map` -> database directory. An unknown map REFUSES rather than guessing: a wrong
# directory yields a confident ceiling belonging to somewhere else.
MAP_DIRS = {
    "lighthouse": "lighthouse", "bigmap": "bigmap", "customs": "bigmap",
    "factory4_day": "factory4_day", "factory4_night": "factory4_night",
    "interchange": "interchange", "laboratory": "laboratory", "labs": "laboratory",
    "rezervbase": "rezervbase", "reserve": "rezervbase", "shoreline": "shoreline",
    "tarkovstreets": "tarkovstreets", "streets": "tarkovstreets", "woods": "woods",
    "sandbox": "sandbox", "sandbox_high": "sandbox_high", "labyrinth": "labyrinth",
}

PATHS = [a for a in sys.argv[1:] if not a.startswith("--")]


def rng_max(s):
    n = [int(x) for x in re.findall(r"\d+", str(s or ""))]
    return max(n) if n else 0


def ceilings(map_dir):
    path = os.path.join(DB, map_dir, "base.json")
    if not os.path.isfile(path):
        return None
    d = json.load(open(path, encoding="utf-8-sig"))
    cap = defaultdict(int)
    for b in d.get("BossLocationSpawn") or []:
        nm = str(b.get("BossName") or "")
        if nm:
            cap[nm.lower()] += 1
        es = str(b.get("BossEscortType") or "")
        if es:
            cap[es.lower()] += rng_max(b.get("BossEscortAmount"))
        for s in b.get("Supports") or []:
            st = str(s.get("BossEscortType") or "")
            if st:
                cap[st.lower()] += rng_max(s.get("BossEscortAmount"))
    for w in d.get("waves") or []:
        wt = str(w.get("WildSpawnType") or "")
        if wt:
            cap[wt.lower()] += (w.get("slots_max") or 0)
    return cap


def main():
    if not PATHS:
        print("usage: check-spawn-ceiling.py <log.ndjson>")
        return 2

    worst = 0
    for path in PATHS:
        print("=== %s" % os.path.basename(path))
        obs, maps = Counter(), set()
        try:
            lines = open(path, encoding="utf-8-sig", errors="replace").read().splitlines()
        except OSError as e:
            print("    REFUSED cannot read: %s" % e)
            worst = max(worst, 2)
            continue
        for ln in lines:
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            if o.get("type") == "botSpawn" and o.get("role"):
                obs[str(o["role"]).lower()] += 1
            elif o.get("type") == "sample" and o.get("map"):
                maps.add(str(o["map"]).lower())

        if not obs:
            print("    REFUSED no botSpawn lines - nothing to bound")
            worst = max(worst, 2)
            continue
        if len(maps) != 1:
            print("    REFUSED %d map values (%s) - one log, one map, or the ceiling is a blend"
                  % (len(maps), ", ".join(sorted(maps)) or "none"))
            worst = max(worst, 2)
            continue
        m = maps.pop()
        if m not in MAP_DIRS:
            print("    REFUSED map %r has no database directory in my table - add it "
                  "deliberately rather than guessing" % m)
            worst = max(worst, 2)
            continue
        cap = ceilings(MAP_DIRS[m])
        if cap is None:
            print("    REFUSED no base.json for %s" % MAP_DIRS[m])
            worst = max(worst, 2)
            continue

        over = [(r, n, cap.get(r, 0)) for r, n in obs.items() if n > cap.get(r, 0)]
        print("    %s: %d botSpawn lines across %d role(s), ceiling from %s/base.json"
              % (m, sum(obs.values()), len(obs), MAP_DIRS[m]))
        if over:
            for r, n, c in sorted(over, key=lambda t: -(t[1] - t[2])):
                print("    FAIL  %s spawned %d times against a declared ceiling of %d"
                      % (r, n, c))
            print("    A role exceeding what the database can declare means bots appeared that")
            print("    no declaration accounts for. The known mechanism is a boss-follower")
            print("    spawn re-firing on a wake edge - see the class doc. Do not score this run")
            print("    until the extra spawns are explained.")
            worst = max(worst, 1)
        else:
            tight = sorted(r for r, n in obs.items() if cap.get(r, 0) <= 2)
            print("    ok    every role within its declared ceiling")
            print("    ok    %d role(s) bounded TIGHTLY (ceiling <= 2): %s"
                  % (len(tight), ", ".join(tight) if tight else "none"))
            print("    note  numerous roles are bounded weakly - this passing is strong evidence")
            print("          about unique named bots and weak evidence about scav-count roles.")

    return worst


if __name__ == "__main__":
    sys.exit(main())
