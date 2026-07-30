"""Before pooling legs into one number, check the legs are exchangeable on the population fields.

WHY THIS EXISTS. The per-map p75 table pooled raid 1 (default) with raid 1.5 (`Force for all roles`
ON) and reported the average as a Lighthouse baseline. Beta and Gamma both concluded the
contamination was undetectable - "no per-window quantity existed that could have disagreed with the
pooling", and therefore "the only failure mode in the set that cannot be caught by cross-checking
the data against itself".

That is false, and the distinction decides whether we keep building cheap checks or write them off:

    leg                   windows   awake   asleep   total   asleep%
    raid 1   (default)         11      11       13      23      52%
    marathon (default)         37      10       17      29      65%
    raid 1.5 (forceAll)        33       1       26      27      96%

The two default legs agree on awake to within one bot. The treatment leg reads awake 1 against 10-11
- a tenfold difference in a field on every sample line. **The contamination was undetected, not
undetectable**, and it was reachable two independent ways: `header.config.forceAllRoles` names the
cause, and `bots.awake` shows the consequence. Writing it off as impossible is how the cheap check
never gets built, so here is the cheap check.

WHAT IT DOES. For each pooling group (map), compare every contributing leg on the fields a treatment
would move, and flag the group when they diverge beyond a stated tolerance. It does not know which
leg is "right" - divergence means the pooled number describes a mixture, and that is all it claims.

WHAT IT DOES NOT DO. It cannot detect a treatment with no per-window consequence. That failure mode
is real and IS undetectable this way - which is the precise version of the claim above, and the
reason `forceAllRoles` belongs in `cfg` regardless of this script existing.

TOLERANCE IS SET BEFORE LOOKING, not fitted to what the corpus happens to show: a leg whose median
awake differs from the group median by more than 3 bots OR by more than 50% is flagged. Three bots
because the animator margin is ~0.13 ms/bot and 3 bots is ~0.4 ms, which is larger than the
between-leg rendering floor we cannot resolve anyway; 50% because a small-roster map would pass a
fixed-3 rule while being a completely different population.
"""
import glob
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import steady  # noqa: E402

LOG = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
ABS_TOL_BOTS = 3.0
REL_TOL = 0.50
FIELDS = ("awake", "asleep", "total")


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def header_arm(path):
    """Whole-leg arm from the header, which carries it in every log in the corpus.

    Read here as well as in the percentile reader because a pooling guard that cannot name the
    likely CAUSE of a divergence gets ignored - "these legs differ" prompts a shrug, "these legs
    differ and one ran the treatment" prompts a fix.
    """
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "header":
            continue
        c = o.get("config") or {}
        v = c.get("forceAllRoles")
        return "unknown" if v is None else ("forceAll" if v else "default")
    return "unknown"


groups = defaultdict(dict)  # map -> leg -> {field: median}
for path in sorted(glob.glob(os.path.join(LOG, "framesaver-*.ndjson"))):
    raw = []
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if ln.endswith("}"):
            try:
                raw.append(json.loads(ln))
            except ValueError:
                pass
    kept, _ = steady.partition(raw)
    arm = header_arm(path)
    by_map = defaultdict(list)
    for w in kept:
        b = w.get("bots") or {}
        if b.get("total"):
            by_map[str(w.get("map"))].append(b)
    name = os.path.basename(path).replace("framesaver-", "").replace(".ndjson", "")
    for m, bs in by_map.items():
        groups[m]["%s [%s]" % (name[:34], arm)] = {
            "n": len(bs),
            **{f: median([b.get(f) or 0 for b in bs]) for f in FIELDS}}

print("POOLING GUARD: are the legs behind each map's number the same population?")
print("Tolerance fixed before looking: %.0f bots absolute OR %.0f%% relative on any field.\n"
      % (ABS_TOL_BOTS, 100 * REL_TOL))

flagged = []
for m in sorted(groups):
    legs = groups[m]
    print("  %s  (%d leg%s)" % (m, len(legs), "" if len(legs) == 1 else "s"))
    print("      %-40s %5s %7s %7s %7s" % ("leg", "wins", *FIELDS))
    for leg in sorted(legs):
        d = legs[leg]
        print("      %-40s %5d %7g %7g %7g" % (leg, d["n"], *(d[f] for f in FIELDS)))
    if len(legs) == 1:
        print("      -> single leg: nothing to disagree, and nothing averaging out either")
        print()
        continue
    bad = []
    for f in FIELDS:
        vals = [legs[leg][f] for leg in legs]
        gm = median(vals)
        for leg in sorted(legs):
            v = legs[leg][f]
            if abs(v - gm) > ABS_TOL_BOTS or (gm and abs(v - gm) / gm > REL_TOL):
                bad.append((f, leg, v, gm))
    if bad:
        flagged.append(m)
        print("      -> MIXTURE. The pooled %s number describes no single population:" % m)
        for f, leg, v, gm in bad:
            print("         %-8s %-40s %g vs group median %g" % (f, leg, v, gm))
    else:
        print("      -> legs are exchangeable within tolerance on every field")
    print()

print("-" * 78)
if flagged:
    print("FLAGGED: %s. Do not quote a pooled percentile for these maps - split by arm." % ", ".join(flagged))
else:
    print("No map pools legs that disagree beyond tolerance.")
print()
print("This guard cannot see a treatment with no per-window consequence. That case is genuinely")
print("undetectable from sample lines alone, and is why the arm flag belongs in `cfg` whether or")
print("not this script exists. What it refutes is the broader claim that the Lighthouse mixture")
print("could not have been caught: two fields on every sample line disagreed by tenfold.")
