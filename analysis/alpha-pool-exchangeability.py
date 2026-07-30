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
    """(arm, sleepDistance) from the header, which carries BOTH in every log in the corpus.

    `sleepDistance` comes from the header rather than `cfg` because `cfg.sleepDistance` does not
    exist before era E and no log in the corpus has it - the first version of the geometry check
    read `cfg` and printed nothing at all, silently, for every map. Fourth time today that a field
    was in the header and not on the window, and the third time reaching for `cfg` first cost
    something.


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
        return ("unknown" if v is None else ("forceAll" if v else "default")), c.get("sleepDistance")
    return "unknown", None


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
    arm, hdr_sleep = header_arm(path)
    # Keyed by (map, raid index), NOT by map or by log. A SESSION log can hold several raids on
    # different maps, and `20260726-183701-ai-stack` does exactly that - raid 1 on factory4_day,
    # raid 2 on TarkovStreets. Keying a whole log to one map is how that leg got reported to me as
    # "the Streets leg" and back to me as "no, factory" when the truthful answer is both.
    by_map = defaultdict(list)
    for w in kept:
        b = dict(w.get("bots") or {})
        if b.get("total"):
            cfg = w.get("cfg") or {}
            b["_standBy"] = bool(cfg.get("standBy"))
            b["_sleepDist"] = cfg.get("sleepDistance")
            # Player positional extent, for the geometric capability check below.
            p = w.get("pos") or {}
            for ax in ("x", "y", "z"):
                v = p.get(ax)
                b["_" + ax] = tuple(v) if isinstance(v, list) and len(v) == 2 else None
            by_map[(str(w.get("map")), w.get("raid"))].append(b)
    name = os.path.basename(path).replace("framesaver-", "").replace(".ndjson", "")
    for (m, raid), bs in by_map.items():
        xs = [v for b in bs for v in (b.get("_x") or ())]
        zs = [v for b in bs for v in (b.get("_z") or ())]
        groups[m]["%s r%s [%s]" % (name[:30], raid, arm)] = {
            "n": len(bs),
            "standByAlwaysOn": all(b["_standBy"] for b in bs),
            "sleepDist": next((b["_sleepDist"] for b in bs if b.get("_sleepDist")), hdr_sleep),
            "extent": (max(max(xs) - min(xs), max(zs) - min(zs)) if xs and zs else None),
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
    # Gamma's rule, put HERE rather than in a second script, because a second home for a rule is a
    # second place for it to drift: `cfg.standBy` true in every window with median `asleep` 0 is a
    # config saying ON and an outcome saying nothing happened.
    #
    # WITH A POSITIVE CONTROL, because the first version of this rule fired on all three
    # factory4_day legs and I was ready to report a mod defect. Factory's player span is 46 m x
    # 72 m against `sleepDistance` 150 - **nothing on that map can ever be far enough away to
    # sleep**, so `asleep == 0` there is correct behaviour. A rule that cannot tell "the lever did
    # nothing" from "the lever had nothing to do" is not an instrument.
    #
    # The control is inside the corpus and needs no map geometry: has ANY leg on this map ever
    # recorded asleep > 0? If yes, sleeping demonstrably works here and a zero leg is anomalous. If
    # no, the map itself may be smaller than the threshold and the two explanations are not
    # separable from these logs - so it says that instead of picking one.
    # GEOMETRIC CAPABILITY, Beta's general form: the map has to be bigger than the sleep radius for
    # the feature to exist at all. Confirmed from the corpus - factory4_day is four raids and twenty
    # windows with not one sleeping bot, while every other map sleeps in 84-96% of windows.
    #
    # This matters BEFORE analysis, not after: a map that cannot sleep is a structural exclusion for
    # any stand-by comparison, and pooling its windows dilutes the effect with windows that could
    # never have shown one. It also kills an inference - "the phenomenon spans both maps in one
    # session, so the cause is session-level" does not survive, because factory's zero would read
    # zero in a perfectly healthy session. A constant read as a measurement, and persuasive because
    # it AGREED.
    #
    # Player positional extent is a LOWER bound on map size - the player need not visit the corners -
    # so extent >= sleepDistance proves capability while extent < sleepDistance only suggests the
    # opposite. Said that way round rather than asserted, and the corpus outcome is the arbiter.
    extents = [legs[leg]["extent"] for leg in legs if legs[leg]["extent"]]
    sleep_d = next((legs[leg]["sleepDist"] for leg in legs if legs[leg]["sleepDist"]), None)
    if extents and sleep_d:
        best = max(extents)
        verdict = ("CAN sleep - player alone spanned more than the radius" if best >= sleep_d
                   else "player never spanned the radius; combined with the outcome below this is"
                        " a geometric exclusion")
        print("      geometry: widest player extent %.0f m vs sleepDistance %g m -> %s"
              % (best, sleep_d, verdict))

    map_ever_slept = any(legs[leg]["asleep"] > 0 for leg in legs)
    zero = [leg for leg in sorted(legs)
            if legs[leg]["standByAlwaysOn"] and legs[leg]["asleep"] == 0]
    if zero and map_ever_slept:
        for leg in zero:
            print("      -> STAND-BY DID NOTHING: %s, cfg.standBy true in every" % leg)
            print("         window and median asleep 0 - on a map where OTHER legs do sleep, so")
            print("         the map is not the explanation. Not exchangeable with anything here.")
        flagged.append(m + " (stand-by inert)")
    elif zero:
        print("      -> every leg on this map reads asleep 0 with standBy on. NOT called a defect:")
        print("         no leg here has ever slept, so a map smaller than `sleepDistance` and a")
        print("         broken lever are indistinguishable from these logs. Factory is the known")
        print("         case - 46 m x 72 m of player span against a 150 m threshold.")
    if len(legs) == 1:
        if not zero:
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
