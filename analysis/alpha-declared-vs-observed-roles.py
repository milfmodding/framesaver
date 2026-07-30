"""Roles the ledger OBSERVED against roles the map DECLARED. Closes the forcedButExcluded gap.

WHY THIS EXISTS. `spawnGate.forcedButExcluded` intersects forced roles taken from the
DATABASE wave array against `ExcludedBosses`, so it is blind by construction to any spawn
that never came from `base.json`. `BotSpawner.method_2` is exactly that: it constructs a
fresh `BossLocationSpawn` - `BossChance = 100f`, `BossEscortAmount = "0"`,
`BossEscortType = followerBully` whatever the real role, `BossZone = ""`,
`IgnoreMaxBots = forcedSpawn` - and calls `BossSpawner.Spawn` directly. So a forced spawn
through that path both BYPASSES the concurrent cap and is invisible to any census of the
declared array. It is public and takes (side, zone, profileType, difficulty, forcedSpawn),
which is the shape a spawn-control mod reaches for.

Echo on the DRIP port found the site while checking a claim of mine; the narrowing that
makes it actionable is that the object is NEW rather than a mutated declared entry, so the
declared-entry census stays valid and what it misses is spawns OUTSIDE the declared set.
Their form of the rule is the one to keep: **the declared set was never the whole population.**

WHAT THIS DOES. Reads the ledger's `botSpawn` roles for the raid's map, reads that map's
declared roles from the server database, and reports observed roles with no declaration.
It is a POSITIVE test for the population `forcedButExcluded` cannot reach, rather than a
second statement of the same rule.

WHAT AN UNDECLARED ROLE MEANS, and there are three readings this cannot separate on its own:
a programmatic spawn (method_2 or similar), a mod that injected database entries at runtime
so the on-disk file no longer describes the raid, or a role-name mapping difference between
the client enum and the database string. It reports the candidates and refuses to pick.
Do not read a hit as "a mod forced a spawn".

DIRECTION MATTERS AND ONLY ONE SIDE IS INFORMATIVE. Declared-but-not-observed is expected
and boring: chance rolls fail, waves are scheduled past the end of a short raid, and raid 1
ended at 11 minutes. Observed-but-not-declared is the finding. Reporting both, with the
boring side clearly marked, so nobody quotes the wrong half.

    python analysis/alpha-declared-vs-observed-roles.py <log.ndjson>

Exit 0 nothing undeclared, 1 undeclared roles present, 2 refused to report.
"""
import glob
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RECON = os.path.join(HERE, "alpha-ledger-reconcile.py")
DB = r"F:\SPT\SPT4.0.13\SPT\SPT_Data\database\locations"

# Telemetry `map` values against database directory names. Only the mapping this project
# actually measures on; an unknown map REFUSES rather than guessing a directory, because a
# wrong directory yields a confident list of "undeclared" roles that are merely elsewhere.
MAP_DIRS = {
    "lighthouse": "lighthouse",
    "bigmap": "bigmap", "customs": "bigmap",
    "factory4_day": "factory4_day", "factory4_night": "factory4_night",
    "interchange": "interchange",
    "laboratory": "laboratory", "labs": "laboratory",
    "rezervbase": "rezervbase", "reserve": "rezervbase",
    "shoreline": "shoreline",
    "tarkovstreets": "tarkovstreets", "streets": "tarkovstreets",
    "woods": "woods",
    "sandbox": "sandbox", "sandbox_high": "sandbox_high",
    "labyrinth": "labyrinth",
}

PATHS = [a for a in sys.argv[1:] if not a.startswith("--")]


def load_reconciler():
    spec = importlib.util.spec_from_file_location("recon", RECON)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def declared_roles(map_dir):
    """Every role name the map's base.json can produce, boss and wave alike."""
    path = os.path.join(DB, map_dir, "base.json")
    if not os.path.isfile(path):
        return None, "no base.json at %s" % path
    d = json.load(open(path, encoding="utf-8-sig"))

    roles = set()
    for b in d.get("BossLocationSpawn") or []:
        for key in ("BossName", "BossEscortType"):
            v = b.get(key)
            if v:
                roles.add(str(v).lower())
        # Supports carry their own escort types and are easy to forget.
        for s in b.get("Supports") or []:
            v = s.get("BossEscortType")
            if v:
                roles.add(str(v).lower())
    for w in d.get("waves") or []:
        v = w.get("WildSpawnType")
        if v:
            roles.add(str(v).lower())
    return roles, None


def main():
    if not PATHS:
        print("usage: alpha-declared-vs-observed-roles.py <log.ndjson>")
        return 2

    worst = 0
    for path in PATHS:
        print("=== %s" % path)
        recon = load_reconciler()
        got = recon.load(path)
        if got is None:
            print("REFUSED: %s" % "; ".join(recon.refusals))
            worst = max(worst, 2)
            continue
        samples, spawns, _deaths, _ = got
        if not spawns:
            print("REFUSED: no botSpawn lines - nothing observed to compare")
            worst = max(worst, 2)
            continue

        maps = {s.get("map") for s in samples if s.get("map")}
        if len(maps) != 1:
            print("REFUSED: %d map values in this log (%s) - refusing to compare a "
                  "multi-map log against one database directory"
                  % (len(maps), ", ".join(sorted(str(m) for m in maps)) or "none"))
            worst = max(worst, 2)
            continue
        mapname = maps.pop()
        key = str(mapname).lower()
        if key not in MAP_DIRS:
            print("REFUSED: map %r has no database directory in my mapping. Add it "
                  "deliberately - guessing a directory produces a confident list of "
                  "undeclared roles that are merely somewhere else." % mapname)
            worst = max(worst, 2)
            continue

        decl, err = declared_roles(MAP_DIRS[key])
        if err:
            print("REFUSED: %s" % err)
            worst = max(worst, 2)
            continue

        observed = {}
        for sp in spawns:
            r = sp.get("role")
            if r:
                observed.setdefault(str(r).lower(), 0)
                observed[str(r).lower()] += 1

        print("    map %s -> database %s" % (mapname, MAP_DIRS[key]))
        print("    %d declared role name(s), %d distinct observed, %d botSpawn lines"
              % (len(decl), len(observed), len(spawns)))

        undeclared = sorted(k for k in observed if k not in decl)
        missing = sorted(k for k in decl if k not in observed)

        if undeclared:
            print("\n    UNDECLARED, observed but not in the map's base.json:")
            for r in undeclared:
                print("      %-24s %d spawn(s)" % (r, observed[r]))
            print("    Three readings this cannot separate: a programmatic spawn such as")
            print("    BotSpawner.method_2, a mod that injected database entries at runtime")
            print("    so the on-disk file no longer describes the raid, or a name-mapping")
            print("    difference between the client enum and the database string. Do NOT")
            print("    read this as 'a mod forced a spawn' without checking which.")
            worst = max(worst, 1)
        else:
            print("\n    no undeclared roles: every observed role is declared for this map.")
            print("    That is the population forcedButExcluded cannot see, checked directly.")

        # The boring direction, marked so nobody quotes it as a finding.
        if missing:
            print("\n    declared but not observed (EXPECTED, not a finding): %d role(s)"
                  % len(missing))
            print("      %s" % ", ".join(missing))
            print("    Chance rolls fail, and waves scheduled past a short raid never fire -")
            print("    raid 1 ended at 11 minutes. This side is uninformative by design.")

    return worst


if __name__ == "__main__":
    sys.exit(main())
