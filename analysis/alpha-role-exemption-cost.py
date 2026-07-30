"""Chance-weighted cost of the proposed exemptions, validated against the ledger.

The declared-entry count overstates the population badly: Lighthouse declares 18 exUsec entries
but raids observed 5 and 6, because BossChance gates each entry (0, 20, 30, 50, 80 there). So the
honest cost is the CHANCE-WEIGHTED expectation, and the declared range is an upper bound nobody
should quote.

Reports three numbers per map, because they answer different questions:

  expected   sum(chance x amount) - what an average raid costs, the number for a default
  ceiling    sum(amount) ignoring chance - the worst raid, the number for a cost bound
  observed   from our own botSpawn ledger where we have one, as a check on the method

Escort amounts stay preset-dependent: AsOnline draws inside the declared range, so the midpoint
is used for the expectation and the max for the ceiling, and that is stated rather than hidden.
"""
import glob
import json
import os
import re
from collections import defaultdict

DB = r"F:\SPT\SPT4.0.13\SPT\SPT_Data\database\locations"
LOGS = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
MS_PER_BOT = 0.35

GROUPS = [
    ("long-range", ["marksman", "exUsec", "bossZryachiy", "followerZryachiy", "bossBoarSniper",
                    "bossKojaniy", "followerKojaniy", "followerGluharSnipe"]),
    ("goons", ["bossKnight", "followerBirdEye", "followerBigPipe"]),
    ("prowl", ["bossKilla", "bossKillaAgro", "sectantPriest", "sectantWarrior", "sectantOni",
               "sectantPredvestnik", "sectantPrizrak"]),
]
WANT = {r.lower(): r for _g, rs in GROUPS for r in rs}
GROUP_OF = {r: g for g, rs in GROUPS for r in rs}


def rng(s):
    n = [int(x) for x in re.findall(r"\d+", str(s or ""))]
    return (min(n), max(n)) if n else (0, 0)


exp = defaultdict(lambda: defaultdict(float))
ceil = defaultdict(lambda: defaultdict(float))

for path in sorted(glob.glob(os.path.join(DB, "*", "base.json"))):
    m = os.path.basename(os.path.dirname(path))
    try:
        d = json.load(open(path, encoding="utf-8-sig"))
    except Exception:
        continue

    def add(role, lo, hi, chance):
        p = (chance if chance is not None else 100.0) / 100.0
        mid = (lo + hi) / 2.0
        exp[m][role] += p * mid
        ceil[m][role] += hi

    for b in d.get("BossLocationSpawn") or []:
        c = b.get("BossChance")
        nm = str(b.get("BossName") or "").lower()
        if nm in WANT:
            add(WANT[nm], 1, 1, c)
        es = str(b.get("BossEscortType") or "").lower()
        if es in WANT:
            lo, hi = rng(b.get("BossEscortAmount"))
            add(WANT[es], lo, hi, c)
        for s in b.get("Supports") or []:
            st = str(s.get("BossEscortType") or "").lower()
            if st in WANT:
                lo, hi = rng(s.get("BossEscortAmount"))
                add(WANT[st], lo, hi, c)
    for w in d.get("waves") or []:
        wt = str(w.get("WildSpawnType") or "").lower()
        if wt in WANT:
            add(WANT[wt], w.get("slots_min") or 0, w.get("slots_max") or 0, None)

# observed, from our own ledger. PER RAID, not pooled - the expectation is a per-raid
# quantity and the first version of this check compared a pooled count against it, which is
# the same wrong-denominator error this whole file is about.
obs = defaultdict(lambda: defaultdict(int))
nraids = defaultdict(int)
for p in glob.glob(os.path.join(LOGS, "*.ndjson")):
    mp = None
    lines = []
    for ln in open(p, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        lines.append(o)
        if o.get("type") == "sample" and o.get("map"):
            mp = str(o["map"])
    if not mp:
        continue
    if not any(o.get("type") == "botSpawn" for o in lines):
        continue  # build predates the ledger; counting it as a raid would dilute
    nraids[mp.lower()] += 1
    for o in lines:
        if o.get("type") == "botSpawn" and o.get("role") in WANT.values():
            obs[mp.lower()][o["role"]] += 1

print("CHANCE-WEIGHTED cost of exempting the proposed roles, per map.\n")
print("  %-16s %10s %10s   %s" % ("map", "expected", "ceiling", "ms/frame at 0.35/bot exp..ceil"))
print("  " + "-" * 78)
for m in sorted(exp):
    e = sum(exp[m].values())
    c = sum(ceil[m].values())
    if c <= 0:
        continue
    print("  %-16s %10.1f %10.0f   %.2f .. %.2f ms" % (m, e, c, MS_PER_BOT * e, MS_PER_BOT * c))

print("\n  by group, Lighthouse and Streets - the two maps that matter most:")
for m in ("lighthouse", "tarkovstreets"):
    if m not in exp:
        continue
    print("    %s" % m)
    for g, _rs in GROUPS:
        ge = sum(v for r, v in exp[m].items() if GROUP_OF[r] == g)
        gc = sum(v for r, v in ceil[m].items() if GROUP_OF[r] == g)
        if gc:
            print("      %-12s expected %5.1f  ceiling %3.0f   %.2f .. %.2f ms"
                  % (g, ge, gc, MS_PER_BOT * ge, MS_PER_BOT * gc))

print("\n  METHOD CHECK against our own ledger, PER RAID:")
for m in sorted(obs):
    k = nraids[m]
    tot = sum(obs[m].values()) / k
    e = sum(exp.get(m, {}).values())
    c = sum(ceil.get(m, {}).values())
    print("    %-14s %d raid(s):  observed/raid %.1f   expected %.1f   ceiling %.0f"
          % (m, k, tot, e, c))
    print("        -> %s" % ("expectation is the better predictor"
                             if abs(tot - e) < abs(tot - c) else "ceiling closer - model suspect"))
    for r, n in sorted(obs[m].items(), key=lambda kv: -kv[1]):
        ex = exp.get(m, {}).get(r, 0.0)
        print("        %-20s observed/raid %4.1f   expected %5.2f   %s"
              % (r, n / k, ex,
                 "exact" if abs(n / k - ex) < 0.05
                 else "over %.1fx" % (ex / (n / k)) if n and ex > n / k
                 else "under"))
    print("        cost at %.2f ms/bot: observed %.2f ms/frame, expected %.2f"
          % (MS_PER_BOT, MS_PER_BOT * tot, MS_PER_BOT * e))
