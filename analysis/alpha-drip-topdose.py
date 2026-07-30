"""topDose: how many bots in a leg can actually put a DRIP top on screen.

FOR THE JOINT RIDE-ALONG, not for Framesaver's own gates. A DRIP dose has no bearing on
whether a Framesaver run is scoreable, so this is deliberately NOT wired into post-flight -
putting another project's metric in our gate would fail our runs for their reasons. Run it by
hand on a ride-along leg, and it becomes a post-flight note only if a ride-along protocol is
armed.

WHY IT EXISTS. Echo's mipmap differential contrasts a pinned arm (garment pool collapsed to
exactly one entry, so the denominator is exact by construction rather than modelled) against an
unpinned arm. A leg that failed to put enough distinct materials on screen produces the same
"neither moves" cell as a leg that put plenty on screen and cost nothing. **Undosed and negative
are not the same reading**, so the dose has to be counted rather than assumed.

THE THRESHOLD IS ECHO'S, DERIVED RATHER THAN PICKED. Expected distinct garments for N bots
against a pool of P is P(1 - ((P-1)/P)^N). Against real pool sizes - exusec 17 tops, pmcusec 23,
pmcbear 33 - that gives ~11 distinct at N=15 against the pinned arm's exact 1, a ~10x contrast.

    topDose >= 15   DOSED
    topDose 10-14   WEAK - report the number, let the reader judge
    topDose < 10    UNDOSED, and a null there is not evidence

Note the saturation: 15 to 30 bots moves distinct garments only 11 -> 17. **Dose saturates, so a
longer raid does not rescue a thin one** - but bot count itself accumulates on a wave schedule, so
a SHORT raid is genuinely undosed. Those are different statements and both are true.

THE MEMBERSHIP CORRECTION THAT MAKES THIS LIST SHORT, and it is the reason a naive count is wrong
by 2x. Echo first gave me `ClothedBotTypes`, 13 names - and that is the list DRIP ATTEMPTS to
clothe, not the list that can wear it. Of the 13: four return an empty top pool
(`assault`, `marksman`, `pmcbot`, and three of the Gluhar followers), and two - `usec` and `bear`,
which hold the two LARGEST pools in the table - have no wave, boss or escort entry on any map and
can never spawn at all. **"In the list" and "can wear DRIP" are different populations.**

Counting scavs in particular inflates a Lighthouse leg by 14 bots that cannot move the quantity
the pin manipulates, because none of DRIP's tops retexture a scav garment. And the Goons are not
in the list at all.

So TOPS - the five that can actually put a DRIP top on screen:

    exusec  pmcusec  pmcbear  followerbully  followerkojaniy

BOTTOMS is a different set and is NOT the one to pair with a top pin, recorded only so nobody
reconstructs it wrongly later:

    assault  marksman  pmcusec  pmcbear  followergluharsecurity  followerkojaniy

    python analysis/alpha-drip-topdose.py <log.ndjson> [...]
"""
import json
import os
import sys

TOPS = {"exusec", "pmcusec", "pmcbear", "followerbully", "followerkojaniy"}
BOTTOMS = {"assault", "marksman", "pmcusec", "pmcbear", "followergluharsecurity",
           "followerkojaniy"}
# In ClothedBotTypes but unable to contribute a top, with the reason. Reported so a reader can
# see what was excluded and why, rather than trusting the set above.
EXCLUDED = {
    "assault": "0 DRIP tops - no scav-origin top in the set",
    "marksman": "0 DRIP tops",
    "pmcbot": "empty pool, tops and bottoms",
    "followergluharassault": "empty pool",
    "followergluharscout": "empty pool",
    "followergluharsecurity": "bottoms only",
    "usec": "largest pool in the table but NEVER spawns - no wave/boss/escort entry",
    "bear": "same - superseded by pmcbear",
}

PATHS = [a for a in sys.argv[1:] if not a.startswith("--")]


def main():
    if not PATHS:
        print(__doc__.strip().splitlines()[-1])
        return 2
    worst = 0
    for path in PATHS:
        roles, maps = {}, set()
        try:
            lines = open(path, encoding="utf-8-sig", errors="replace").read().splitlines()
        except OSError as e:
            print("REFUSED cannot read %s: %s" % (path, e))
            worst = max(worst, 2)
            continue
        for ln in lines:
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            if o.get("type") == "botSpawn" and o.get("role"):
                r = str(o["role"]).lower()
                roles[r] = roles.get(r, 0) + 1
            elif o.get("type") == "sample" and o.get("map"):
                maps.add(str(o["map"]))

        if not roles:
            print("=== %s\n    REFUSED no botSpawn lines - no dose to count"
                  % os.path.basename(path))
            worst = max(worst, 2)
            continue

        top = sum(n for r, n in roles.items() if r in TOPS)
        bot = sum(n for r, n in roles.items() if r in BOTTOMS)
        verdict = "DOSED" if top >= 15 else ("WEAK" if top >= 10 else "UNDOSED")

        print("=== %s   map %s" % (os.path.basename(path), ", ".join(sorted(maps)) or "?"))
        print("    topDose %d   -> %s   (>=15 dosed, 10-14 weak, <10 undosed)" % (top, verdict))
        print("      %s" % ", ".join("%s=%d" % (r, roles[r]) for r in sorted(TOPS) if r in roles))
        print("    bottomDose %d  - NOT the figure that pairs with a top pin" % bot)
        present_excluded = [(r, roles[r], why) for r, why in EXCLUDED.items() if r in roles]
        if present_excluded:
            print("    excluded despite being in ClothedBotTypes:")
            for r, n, why in sorted(present_excluded, key=lambda t: -t[1]):
                print("      %-24s %3d spawns   %s" % (r, n, why))
        if verdict == "UNDOSED":
            print("    A NULL ON THIS LEG IS NOT EVIDENCE. Undosed and negative are different")
            print("    readings, and this is the undosed one.")
            worst = max(worst, 1)
        elif verdict == "WEAK":
            print("    Report the number rather than the verdict. The threshold does not get to")
            print("    decide silently at this count.")
        print()
    return worst


if __name__ == "__main__":
    sys.exit(main())
