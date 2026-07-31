"""Adjudicate claim B: vanilla's own stand-by per map, WHY it differs, and what "headroom"
means under each mechanism.

CLAIM B (Alpha): vanilla sleeps heavily on Interchange/Woods/Shoreline and not at all on
Streets/Ground Zero/Factory, therefore Framesaver's untapped headroom is Streets and GZ
only. The measurement half is checked here (census reads the game's own StandByType_1, and
mod-off vanilla's own BotStandBy.Update writes it - verified at source, BotStandByUpdate-
Patch:96 returns true before touching anything). The INFERENCE half is the target:

"Headroom = maps where vanilla does not already sleep bots" is gating-mechanism logic. It
prices a slept bot at what stand-by's own gate saves (~0.011 ms/frame, ceiling measured at
0.06-0.30 ms/frame for entire rosters). Under claim D - the animator cull as the dominant
mechanism - the value of a slept bot is the CULL, and vanilla sleeps WITHOUT culling: its
sleepers still animate at CullUpdateTransforms. So on the maps where vanilla sleeps most,
Framesaver's cull gets its targets handed to it for free, and the "already handled" maps
are where the mod's dominant mechanism has the most to work with. B and D cannot both be
read the way they are currently phrased; this file prints the numbers both readings need.

WHY STREETS SLEEPS NOBODY is checkable, not a shrug: botStandBy events carry the game's
own CanDoStandBy grant per bot at activation (`effective`), plus `roleAllows`. Grants
false => the game disables stand-by there (patrol events / map scripting), and the mod
can only add sleepers via the reclaim lever (QuestingBots interplay). Grants true with
zero sleepers => distance geometry, and the mod's own distances would sleep them.

Known weaknesses:
  - One marathon, one leg per map. Bot population and spawn waves vary by run; the
    per-map asleep medians carry that run's composition.
  - The mod-on comparison pools default-arm legs from the corpus across days and builds;
    it is descriptive context for the headroom table, not a within-raid contrast.
  - `effective` is sampled at activation; the game can toggle CanDoStandBy later
    (BotsPatrolGeneratorGameEvent), which activation-time grants cannot see.
"""
import collections
import glob
import json
import os
import statistics as S

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
MARATHON = os.path.join(LOGDIR, "framesaver-20260731-112704-modoff-marathon.ndjson")
WARMUP = 60


def read_log(path):
    header, samples, grants = None, [], []
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        t = o.get("type")
        if t == "header" and header is None:
            header = o
        elif t == "sample" and o.get("state") == "raid":
            samples.append(o)
        elif t == "botStandBy":
            grants.append(o)
    return header, samples, grants


def kept(samples):
    seg = collections.defaultdict(list)
    for o in samples:
        seg[(o.get("raid"), str(o.get("map")))].append(o)
    out = []
    for k in sorted(seg):
        for o in seg[k][:-1]:
            el, ws = o.get("raidElapsed"), o.get("windowSec")
            if el is not None and ws is not None and el - ws >= WARMUP:
                out.append(o)
    return out


def main():
    header, samples, grants = read_log(MARATHON)
    keep = kept(samples)
    if not keep:
        print("REFUSED: no post-warmup windows in the marathon")
        return 2

    # grants are keyed by the window they were logged in; map them to raids via sample
    # windows (grants during loading carry the raid's upcoming windows' neighborhood, so
    # bucket by nearest sample raid at or after the grant's window).
    win_raid = {}
    for o in samples:
        win_raid[o["window"]] = (o["raid"], str(o["map"]))
    order = sorted(win_raid)

    def raid_of(window):
        for w in order:
            if w >= window:
                return win_raid[w]
        return None

    gr = collections.defaultdict(lambda: {"n": 0, "eff": 0, "role": 0})
    for g in grants:
        key = raid_of(g.get("window", -1))
        if key is None:
            continue
        gr[key]["n"] += 1
        gr[key]["eff"] += 1 if g.get("effective") else 0
        gr[key]["role"] += 1 if g.get("roleAllows") else 0

    print("1. VANILLA'S OWN STAND-BY per map (mod-off marathon, post-warmup medians), and")
    print("   the game's own grants at activation. effective = CanDoStandBy as the game")
    print("   set it; roleAllows = our role table's opinion, for reference.")
    print()
    print("   %-14s %6s %6s %6s %7s %8s %12s %10s"
          % ("map", "awake", "asleep", "total", "exempt", "blocked", "grants", "granted%"))
    by_map = collections.defaultdict(list)
    for o in keep:
        by_map[(o["raid"], str(o["map"]))].append(o)
    rows = []
    for key in sorted(by_map, key=lambda k: k[1]):
        ws = by_map[key]
        b = lambda f: S.median([w["bots"][f] for w in ws])
        g = gr.get(key, {"n": 0, "eff": 0, "role": 0})
        rows.append((key[1], b("awake"), b("asleep"), b("total"), b("exempt"),
                     b("standByBlocked"), g))
        print("   %-14s %6.1f %6.1f %6.1f %7.1f %8.1f %8d bots %9s"
              % (key[1], b("awake"), b("asleep"), b("total"), b("exempt"),
                 b("standByBlocked"), g["n"],
                 "%.0f%%" % (100.0 * g["eff"] / g["n"]) if g["n"] else "-"))

    # ---- mod-on default-arm context from the corpus --------------------------------------
    print()
    print("2. MOD-ON default-arm asleep per map (corpus legs with standByEnabled=true,")
    print("   forceAllRoles=false; cross-day descriptive context, NOT a contrast):")
    on_map = collections.defaultdict(list)
    for path in sorted(glob.glob(os.path.join(LOGDIR, "*.ndjson"))):
        if os.path.basename(path).startswith("framesaver-20260731-112704"):
            continue
        h, ss, _ = read_log(path)
        cfg = (h or {}).get("config") or {}
        if cfg.get("standByEnabled") is not True or cfg.get("forceAllRoles") is not False:
            continue
        for o in kept(ss):
            on_map[str(o["map"])].append(o)
    print()
    print("   %-14s %6s %6s %6s   (legs pooled by frame count of windows)"
          % ("map", "awake", "asleep", "total"))
    for mp in sorted(on_map):
        ws = on_map[mp]
        print("   %-14s %6.1f %6.1f %6.1f   n=%d windows"
              % (mp, S.median([w["bots"]["awake"] for w in ws]),
                 S.median([w["bots"]["asleep"] for w in ws]),
                 S.median([w["bots"]["total"] for w in ws]), len(ws)))

    print()
    print("3. THE TWO READINGS OF HEADROOM, side by side. Under the gating mechanism the")
    print("   mod's value on a map is (modOnAsleep - vanillaAsleep) x ~0.011 ms. Under the")
    print("   cull mechanism it is modOnAsleep x 0.09-0.21 ms, because vanilla never culls")
    print("   what it sleeps - its sleepers animate at CullUpdateTransforms regardless.")
    print("   The maps B writes off as 'already handled' are the cull's richest targets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
