"""Spawn-to-death displacement, filtered to AI kills. The DanW payload, per arm.

WHAT THIS IS FOR. If Framesaver's brain slicing broke QuestingBots' bots, the symptom
would be bots that do not go anywhere. So the deliverable to DanW is a DISTRIBUTION of how
far bots travelled between spawning and dying, split by arm, not an impression that his
bots looked fine. An overclaim here puts the cost on him.

WHY AI KILLS ONLY. A bot Sophia killed died where SOPHIA was. That measures the player's
position, not the bot's travel, and it is the majority of deaths in a normal raid - 8 of 10
in raid 1. Filtering to deaths whose killer was itself AI removes the player from the
numerator. It also shrinks n hard, which is why this refuses rather than plots when n is
too small to carry a distribution.

THE CENSORING, STATED RATHER THAN BURIED. Displacement-at-death only exists for bots that
DIED. Survivors contribute nothing, and survivors are plausibly the bots that quested
furthest - they were never near enough to anything to be shot. So the absolute distribution
is biased toward bots that came to the fight, and it must never be reported as "how far
QuestingBots bots travel". The per-ARM COMPARISON survives that, because the same censoring
applies to both arms - but only if the arms have comparable kill counts, so this reports
them side by side and says so when they are lopsided.

HORIZONTAL AND 3D SEPARATELY. Unity's y is vertical. On Reserve or Lighthouse a bot can
gain 30 m of elevation without covering ground, so 3D distance flatters a stationary bot on
a stairwell. Horizontal is the travel measure; 3D is reported beside it, never instead.

DURATION IS NOT OPTIONAL. Displacement without time-alive is uninterpretable: a bot that
died 20 seconds after spawning cannot have gone far, and an arm that kills bots faster will
show shorter displacement for reasons that have nothing to do with slicing. So metres per
second alive is reported as the arm-comparable quantity.

AND MOST SPAWNS HAVE NO SPAWN TIME. In raid 1, 24 of 31 bots spawned while the state was
`loading`, before the raid clock existed, so their `raidElapsed` is legitimately null - the
clock had not started, which is a fact about the raid rather than a gap in the ledger. For
those bots the death's own raidElapsed is a LOWER bound on time alive, making metres per
second an UPPER bound. Exact and bounded rows are reported separately and never pooled: an
upper bound averaged in with a measurement produces a number that is neither, and with 77%
of the population on the bounded side it would be the bound wearing a measurement's label.
It is probably a tight bound, because a bot spawned during loading has little reason to move
before the raid starts - but "probably tight" is an assumption, and it is written here rather
than absorbed into the arithmetic.

THE LEDGER MUST RECONCILE FIRST. This runs alpha-ledger-reconcile.py and REFUSES if it does
not exit 0, rather than restating its pairing rules. A second statement of a rule is a
second place for it to be wrong, and displacement over an unreconciled ledger is a
distribution over pairs that may not be pairs. --no-reconcile exists for iterating on this
file and says loudly that the gate was skipped.

    python analysis/alpha-spawn-death-displacement.py <log.ndjson> [--no-reconcile]

Exit 0 reported, 1 something failed, 2 refused to report.
"""
import importlib.util
import math
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RECON = os.path.join(HERE, "alpha-ledger-reconcile.py")

# Below this many AI kills in an arm, a distribution is theatre. Five is not a defensible
# statistical threshold and is not offered as one - it is the point below which quartiles
# stop being distinguishable from the individual observations they are computed from.
MIN_PER_ARM = 5

PATHS = [a for a in sys.argv[1:] if not a.startswith("--")]
NO_RECONCILE = "--no-reconcile" in sys.argv


def import_reconciler():
    """Reuse the reconciler's own parser, hyphenated filename and all."""
    spec = importlib.util.spec_from_file_location("recon", RECON)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def horiz(a, b):
    return math.hypot(b[0] - a[0], b[2] - a[2])


def dist3(a, b):
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2)


def quantiles(xs):
    xs = sorted(xs)
    n = len(xs)

    def q(p):
        if n == 1:
            return xs[0]
        i = p * (n - 1)
        lo = int(math.floor(i))
        hi = min(lo + 1, n - 1)
        return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)

    return q(0.0), q(0.25), q(0.5), q(0.75), q(0.9), q(1.0)


def report(path):
    if not NO_RECONCILE:
        r = subprocess.run([sys.executable, RECON, path], capture_output=True, text=True)
        if r.returncode != 0:
            print("REFUSED: the ledger does not reconcile (reconciler exit %d). Displacement "
                  "over an unreconciled ledger is a distribution over pairs that may not be "
                  "pairs." % r.returncode)
            for ln in r.stdout.splitlines():
                if "FAIL" in ln or "REFUSED" in ln:
                    print("    | %s" % ln.strip())
            return 2
        print("ok  ledger reconciles - pairing below uses the same id/isAI rule it checked")
    else:
        print("WARNING: --no-reconcile. The pairing gate was SKIPPED, so nothing below is "
              "gated on the ledger being complete.")

    recon = import_reconciler()
    got = recon.load(path)
    if got is None:
        print("REFUSED: %s" % "; ".join(recon.refusals))
        return 2
    samples, spawns, deaths, _ = got
    if not samples:
        print("REFUSED: no sample lines")
        return 2

    # window -> raid ordinal and window -> arm, from the samples that closed each window.
    raid_of, arm_of = {}, {}
    for s in samples:
        w = s.get("window")
        if w is None:
            continue
        raid_of[w] = s.get("raid")
        arm_of[w] = (s.get("protocol") or {}).get("arm")

    # Same filter as the reconciler: pair on id, AI only, within one raid.
    spawn_by = {}
    for sp in spawns:
        if sp.get("isAI") is True and sp.get("id"):
            spawn_by[(raid_of.get(sp.get("window")), sp["id"])] = sp

    rows, unpaired, no_pos, player_kills = [], 0, 0, 0
    for d in deaths:
        if d.get("isAI") is not True or not d.get("id"):
            continue
        k = d.get("killer")
        if not k or k.get("isAI") is not True:
            player_kills += 1
            continue
        sp = spawn_by.get((raid_of.get(d.get("window")), d["id"]))
        if sp is None:
            unpaired += 1
            continue
        p0, p1 = sp.get("pos"), d.get("pos")
        if not (isinstance(p0, list) and isinstance(p1, list) and len(p0) == 3 and len(p1) == 3):
            no_pos += 1
            continue
        t0, t1 = sp.get("raidElapsed"), d.get("raidElapsed")
        # Exact when the bot spawned after the raid clock started; a lower bound on time
        # alive when it spawned during loading, which is most of them.
        if t1 is None:
            alive, bounded = None, False
        elif t0 is None:
            alive, bounded = t1, True
        else:
            alive, bounded = t1 - t0, False
        rows.append({"arm": arm_of.get(d.get("window")), "role": d.get("role"),
                     "horiz": horiz(p0, p1), "d3": dist3(p0, p1),
                     "alive": alive, "bounded": bounded})

    print("\n%d AI death(s) killed by AI and paired to a spawn." % len(rows))
    print("excluded: %d killed by a human (the player's position, not the bot's travel), "
          "%d unpaired, %d without usable positions" % (player_kills, unpaired, no_pos))

    if not rows:
        print("\nREFUSED: no AI-on-AI kills with positions. Nothing to distribute.")
        return 2

    by_arm = {}
    for r in rows:
        by_arm.setdefault(r["arm"], []).append(r)

    print("\narm      n   horiz m: min   p25   p50   p75   p90   max   m/s exact  m/s <=bound")
    thin = []
    for arm in sorted(by_arm, key=lambda a: (a is None, a)):
        v = by_arm[arm]
        mn, q1, q2, q3, q9, mx = quantiles([r["horiz"] for r in v])
        ex = [r["horiz"] / r["alive"] for r in v
              if r["alive"] and r["alive"] > 0 and not r["bounded"]]
        bd = [r["horiz"] / r["alive"] for r in v
              if r["alive"] and r["alive"] > 0 and r["bounded"]]
        fx = ("%.3f (n%d)" % (statistics.median(ex), len(ex))) if ex else "-"
        fb = ("%.3f (n%d)" % (statistics.median(bd), len(bd))) if bd else "-"
        print("%-7s %3d          %5.1f %5.1f %5.1f %5.1f %5.1f %6.1f   %-11s %s"
              % (str(arm), len(v), mn, q1, q2, q3, q9, mx, fx, fb))
        if len(v) < MIN_PER_ARM:
            thin.append((arm, len(v)))
    nb = sum(1 for r in rows if r["bounded"])
    if nb:
        print("%d of %d rows spawned before the raid clock, so their m/s is an UPPER bound "
              "and sits in its own column." % (nb, len(rows)))

    if thin:
        print("\nREFUSED as a DanW deliverable: %s below %d AI kills."
              % (", ".join("arm %s has %d" % (a, n) for a, n in thin), MIN_PER_ARM))
        print("The numbers above are printed as a plumbing check on this reader, not as a")
        print("distribution. Quoting quartiles from n<%d would be exactly the overclaim"
              % MIN_PER_ARM)
        print("that puts the cost on him.")
        return 2

    counts = sorted(len(v) for v in by_arm.values())
    if len(counts) > 1 and counts[-1] > 3 * counts[0]:
        print("\nNOTE: arm kill counts are lopsided (%s). The censoring only cancels between"
              % ", ".join(str(c) for c in counts))
        print("arms when both arms lose comparable numbers of bots, so compare m/s alive")
        print("rather than raw displacement here.")

    print("\nREAD IT AS: a comparison between arms, never as how far QuestingBots bots")
    print("travel. Survivors are absent from every row and are plausibly the ones that")
    print("went furthest.")
    return 0


def main():
    if not PATHS:
        print(__doc__.strip().splitlines()[-3])
        return 2
    worst = 0
    for p in PATHS:
        print("=== %s" % p)
        worst = max(worst, report(p))
    return worst


if __name__ == "__main__":
    sys.exit(main())
