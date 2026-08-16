"""Refuse a run whose protocol depends on a mod that is not on disk.

WHY THIS EXISTS. Raid 2's release-blocking primary is an EVENT criterion: `bots.asleep` above 0
**with QuestingBots present in `agents.mods`**. QuestingBots is not installed. It has never been
installed in the life of this corpus - `agents.mods` reads `["BigBrain","SAIN","LootingBots"]` in
all 24 logs - and the whole raid was designed around it across eight hours of reasoning from source
in `Community\\`, by three of us, without anyone running `ls plugins`.

The failure mode is the one this project keeps building instruments against: **it is silent and it
looks like success.** `cfg.forceAllRoles` would have flipped cleanly in every window. The arms would
have been near no-ops on the garrison, because without a clearing mod `ModCompat.ClearsStandByFlag`
is false, `TryReclaimStandBy` returns on its first line, and the only writer of the grant is the
`InitPoints` postfix - once per bot, at activation. So arm assignment would have been SPAWN-time,
not arm-time, and on Lighthouse the garrison is fixed during warm-up.

A protocol that names a mod is stating a precondition. This turns that statement into a gate.

WHAT IT CHECKS, and it deliberately checks the DISK rather than the source tree: a mod whose source
sits in `Community\\` is not installed, and every correct reading of that source is irrelevant to the
machine. Both halves are required - an SPT mod is a BepInEx client plugin AND (usually) a server mod,
and half an install fails in a way that is harder to see than none of it.

EXIT 0 all preconditions met, 1 a declared mod is MISSING, 2 REFUSED (could not tell).
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 2026-08-16: repointed at the SPT-4.1 install with the port campaign. Note the
# server subfolder is SPT_Runtime here - 4.0.13 called it SPT.
INSTALL = r"F:\SPT\SPT-4.1"
PLUGINS = os.path.join(INSTALL, "BepInEx", "plugins")
SERVERMODS = os.path.join(INSTALL, "SPT_Runtime", "user", "mods")

# name -> (client dll/dir fragments, server mod dir fragments). Fragments are matched
# case-insensitively as substrings, because mod authors capitalise inconsistently and a folder
# named `DrakiaXYZ-Waypoints` must match a declaration of `waypoints`.
KNOWN = {
    "questingbots": (("questingbots", "danw.questingbots"), ("questingbots",)),
    "bigbrain": (("bigbrain",), ()),
    "waypoints": (("waypoints",), ()),
    "sain": (("sain",), ("sain",)),
    "lootingbots": (("lootingbots",), ("lootingbots",)),
    "orbit": (("orbit",), ()),
}


def listing(path):
    try:
        return [e.lower() for e in os.listdir(path)]
    except OSError:
        return None


def present(entries, fragments):
    return any(f.lower() in e for e in entries for f in fragments)


def declared(protocol):
    """Mod names a protocol declares via `@requires`, one per line, comma separated."""
    out = []
    with open(protocol, encoding="utf-8-sig", errors="replace") as f:
        for ln in f:
            m = re.match(r"\s*@requires\s+(.+?)\s*$", ln)
            if m:
                out += [x.strip().lower() for x in m.group(1).split(",") if x.strip()]
    return out


def main():
    proto = (sys.argv[1] if len(sys.argv) > 1
             else os.path.join(INSTALL, "BepInEx", "config", "framesaver.protocol.ini"))
    if not os.path.isfile(proto):
        print("REFUSED: no protocol at %s - cannot tell what it requires" % proto)
        return 2

    plug, srv = listing(PLUGINS), listing(SERVERMODS)
    if plug is None:
        print("REFUSED: cannot read %s. Refusing rather than reporting 'no mods found',"
              % PLUGINS)
        print("         because an unreadable directory and an empty one are not the same thing.")
        return 2
    if srv is None:
        print("NOTE: cannot read %s - server-mod halves reported as UNKNOWN, not absent."
              % SERVERMODS)
        srv = []
        srv_known = False
    else:
        srv_known = True

    want = declared(proto)
    print("protocol: %s" % os.path.basename(proto))
    if not want:
        print("  declares no @requires. That is not the same as requiring nothing - if this")
        print("  protocol depends on a mod, say so with @requires so this gate can hold it.")
        return 0

    bad = []
    for name in want:
        if name not in KNOWN:
            print("  %-16s REFUSED - not in KNOWN, so this gate cannot look for it. Add the"
                  % name)
            print("  %-16s          folder fragments rather than letting it pass unchecked."
                  % "")
            return 2
        cfrag, sfrag = KNOWN[name]
        c = present(plug, cfrag)
        s = present(srv, sfrag) if sfrag else None
        if sfrag and not srv_known:
            s_txt = "UNKNOWN"
        elif not sfrag:
            s_txt = "n/a"
        else:
            s_txt = "yes" if s else "NO"
        print("  %-16s client %-3s   server %s" % (name, "yes" if c else "NO", s_txt))
        if not c or (sfrag and srv_known and not s):
            bad.append(name)

    print()
    if bad:
        for name in bad:
            print("  MISSING: %s" % name)
        print()
        print("Do not run. A protocol that arms a setting behind this mod would flip the config")
        print("cleanly and change nothing measurable - the config line is not evidence the lever")
        print("moved. Checked against the DISK, not against source in Community\\: a correct")
        print("reading of uninstalled source is a correct reading of nothing.")
        return 1
    print("All declared mods present in the install.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
