"""Check 3: `animCulledOffScreen / animCulled` -- the fraction of the marking
Unity could honour.

WHY THIS IS A NEW FILE AND NOT AN EDIT TO read-animcull.py.
`protocol-anim-cull.ini` is a PRE-REGISTERED gate. Its own docstring records
that the last guard added to a shipping file here refused every good case and
was caught only by a real run. Adding a section to that reader hours before a
raid depends on it is the mistake the file exists to prevent. A new file cannot
change what the gate says about tonight, because nothing depends on this one.

WHY IT WAS NOT WRITTEN BEFORE, AND WHY THAT REASON NO LONGER BLOCKS IT.
`protocol-anim-cull.ini:174` (Delta, 2026-08-04): check 3 is emitted and unread,
"deliberately not fixed before the raid: ac-crashtest.py currently cannot fail,
so adding a check whose validating harness is incapable of failing would be the
defect this file exists to avoid."

That reasoning was right and it was about ac-crashtest.py, not about check 3.
This file does not use ac-crashtest.py. It ships its own positive controls in
delta-check3-selftest.py, each of which is asserted to FAIL. The blocker was a
property of the validating harness, so a check that brings its own harness is
not blocked by it.

WHAT IT REPORTS, AND WHAT IT DELIBERATELY DOES NOT.
It reports the ratio. It does NOT pass or fail on the VALUE, because no
threshold has ever been registered for it and inventing one after seeing the
data is what ends a pre-registration. `protocol-anim-cull.ini` says only that
"a low ratio on an open map is the interesting failure" -- that is a direction,
not a number. Anyone who registers a threshold should do it before the run it
scores, and say so here.

It DOES refuse -- exit 1 -- when it cannot compute the ratio honestly: the field
absent, no cull arm with enough windows, or a zero denominator. An instrument
that prints a number whether or not it measured one cannot be evidence.

TWO ESTIMATORS, ON PURPOSE.
`median(offscreen)/median(culled)` and `median(offscreen/culled per window)` are
different quantities and this project has already been bitten once by a
ratio-vs-slope conflation. Both are printed. They should agree closely; if they
do not, the marking is moving within the arm and neither number is a summary.
Disagreement is reported, not reconciled.

POPULATION IS IMPORTED, NOT REIMPLEMENTED.
The window filter, arm resolution and MIN_WINDOWS come from read-animcull.py by
import. A second COPY of a population rule forks silently; the whole point here
is to score the same windows the gate scored, so sharing the code is correct and
duplicating it would be the defect.

Usage:  python delta-check3-offscreen.py <log.ndjson> [more.ndjson ...]
Exit 1 means the ratio could not be computed. That is an answer, not a crash.
"""

import importlib.util
import random
import os
import sys

# read-animcull.py is not a legal module name (hyphen), so it is loaded by path
# rather than imported by name. Same file the gate runs, no copy.
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'read_animcull', os.path.join(_HERE, 'read-animcull.py'))
ac = importlib.util.module_from_spec(_spec)
sys.path.insert(0, _HERE)
_spec.loader.exec_module(ac)

FIELD = 'animCulledOffScreen'
MARK = 'animCulled'

# ---- Population: SCORED ARMS ONLY ------------------------------------------
# Bound by Framesaver/Beta at reg-unc-2026-08-07T062917, BEFORE any Streets
# ratio was computed by anyone. Until then this file scored every window with
# `cullSleeping = true`, which silently included `warmup` and `standdown`.
#
# Why that was wrong, and it is not a matter of taste. `standdown` is
# `@seconds = 0` -- it runs until the PLAYER LEAVES THE RAID. So its window
# count is set by extraction timing, not by the experiment. A baseline that
# moves with when somebody quits cannot be compared across raids, and
# cross-raid comparison is the whole purpose of this number.
#
# Measured on Lighthouse: 7 of 16 cull=true windows (44%) were in no pair, and
# the contamination is DIRECTIONAL rather than noise -- warmup and standdown
# read ~0.95 against the B arms' 0.87-0.93. It moved the pooled ratio 0.9291 ->
# 0.9054, which is a quarter of the registered 0.10 gate.
#
# EXCLUDED BY NAME, and absence is a REFUSAL rather than a fallback: a log with
# no `protocol.arm` cannot have its population established, and quietly scoring
# every cull=true window would reinstate exactly this defect in the one case
# nobody would look at.
NON_SCORED_ARMS = ('warmup', 'standdown')


def arm_name(w):
    """The protocol step name, or None if this log predates the field."""
    p = w.get('protocol') or {}
    n = p.get('arm')
    return n if isinstance(n, str) and n else None

# The two estimators must agree within this, or neither is a summary of the arm.
ESTIMATOR_TOLERANCE = 0.05

# ---- Interval on the pooled ratio ------------------------------------------
# REGISTERED BEFORE ANY SECOND-MAP DATA EXISTS. Written 2026-08-07 ~02:00Z, for
# Framesaver/Beta's cross-map row, whose fallback is "pooled ratios differ by
# >= 0.10 absolute" and which retires in favour of NON-OVERLAP if an interval
# exists. Beta said "not before a Streets log"; that is backwards and it is the
# same trap they just avoided on the estimator. An interval METHOD chosen after
# seeing the second map is chosen knowing which way it decides the bet. So the
# method is fixed here, now, while nobody can know what Streets returns.
#
# TWO RESAMPLES, DELIBERATELY, BECAUSE THE HONEST ANSWER IS A BRACKET:
#   BLOCK = 1  treats windows as independent. Known to be WRONG -- the ratio is
#              autocorrelated within a raid -- and it therefore gives the
#              NARROWEST interval the data can support. It is a FLOOR on width.
#   BLOCK = 4  moving-block resample, which preserves local correlation. The
#              block length is a GUESS and is stated as one; it is not tuned and
#              nothing was fitted to pick it.
#
# WHICH TO USE FOR A NON-OVERLAP TEST: THE WIDER ONE, WHICHEVER IT IS.
#
# This rule replaces "use BLOCK=4", which was written here on the reasoning that
# correlation only ever widens an interval. THAT REASONING WAS WRONG ON THIS
# DATA and the measurement caught it within a minute of being written:
#
#     Lighthouse, 16 windows:  block=1  0.880-0.969  width 0.089
#                              block=4  0.894-0.962  width 0.068   <- NARROWER
#
# The sub-1.0 windows are scattered through the raid rather than clustered, so
# every contiguous block of 4 contains a mix, block means resemble each other
# more than random draws do, and the interval TIGHTENS. Positive autocorrelation
# would have widened it; this series does not have the shape I assumed.
#
# So do not trust the direction -- read both and take the wider. That is robust
# to being wrong about the correlation structure, which I demonstrably was, and
# it costs nothing. If the two disagree about OVERLAP against another map, that
# disagreement IS the result and neither is the answer.
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 20260807      # fixed, so the interval is reproducible
BOOTSTRAP_BLOCKS = (1, 4)
INTERVAL_PCT = (2.5, 97.5)     # a 95% percentile interval


def _percentile(xs, pct):
    """Linear-interpolated percentile. No numpy on this host."""
    if not xs:
        return None
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def pooled_interval(offs, marks, block, rng):
    """Percentile interval on sum(offs)/sum(marks) by moving-block resample.

    Resamples WINDOWS, not bots: the window is the unit the protocol delivers
    and the unit the correlation lives in. Blocks wrap, so every window has
    equal weight -- otherwise the ends of the raid are systematically
    under-sampled and the interval quietly describes the middle of the raid.
    """
    n = len(offs)
    if n < 2:
        return None, None
    draws = []
    n_blocks = (n + block - 1) // block
    for _ in range(BOOTSTRAP_N):
        so = sm = 0.0
        taken = 0
        for _ in range(n_blocks):
            start = rng.randrange(n)
            for j in range(block):
                # TRUNCATE at exactly n. When n is not a multiple of `block`,
                # ceil(n/block) whole blocks cover MORE than n windows -- at
                # n=9, block=4 that is 12 resampled windows drawn from 9 real
                # ones, which inflates the effective sample and narrows the
                # interval. Measured: it reported width 0.051 against block=1's
                # 0.136 on the same data. A resample must be the size of the
                # data it resamples.
                if taken >= n:
                    break
                i = (start + j) % n
                so += offs[i]
                sm += marks[i]
                taken += 1
        if sm:
            draws.append(so / sm)
    if not draws:
        return None, None
    return (_percentile(draws, INTERVAL_PCT[0]),
            _percentile(draws, INTERVAL_PCT[1]))


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[-2])
        return 2

    paths, src, refusal = ac.steady.resolve_inputs(argv[1:])
    if refusal:
        print('REFUSED. %s' % refusal)
        return 1
    rows = ac.load(paths)
    kept, counts = ac.eligible(rows)

    print('check 3: %s / %s -- the fraction of the marking Unity honoured'
          % (FIELD, MARK))
    print('read:       %d file(s) from %s' % (len(paths), src))
    print('population: imported from read-animcull.py, identical to the gate')
    print('kept %d window(s)' % len(kept))
    print()

    if not kept:
        print('REFUSED. No eligible windows.')
        return 1

    # ---- Field presence, before any arithmetic -------------------------
    present = [w for w in kept if (w.get('bots') or {}).get(FIELD) is not None]
    print('1. FIELD PRESENCE')
    print('   %s present in %d of %d window(s)' % (FIELD, len(present),
                                                   len(kept)))
    if len(present) != len(kept):
        print()
        print('   REFUSED. The field is missing from %d window(s). Absent is'
              % (len(kept) - len(present)))
        print('   not zero -- a build that never emitted it and a run that')
        print('   honoured nothing are different facts and this cannot tell')
        print('   them apart. Check the build wrote the field.')
        return 1
    print()

    # ---- Population: drop non-scored steps, or refuse --------------------
    print('2a. POPULATION (scored arms only, bound reg-unc-2026-08-07T062917)')
    missing = [w for w in kept if arm_name(w) is None]
    if missing:
        print('   REFUSED. %d of %d window(s) carry no `protocol.arm`, so the'
              % (len(missing), len(kept)))
        print('   scored population cannot be established. This log predates')
        print('   the field. Scoring every cull=true window instead is the')
        print('   exact defect this filter exists to remove -- absent is not')
        print('   "all of them".')
        return 1
    comp = {}
    for w in kept:
        comp[arm_name(w)] = comp.get(arm_name(w), 0) + 1
    dropped = {k: v for k, v in comp.items() if k in NON_SCORED_ARMS}
    kept = [w for w in kept if arm_name(w) not in NON_SCORED_ARMS]
    print('   kept  %s' % {k: v for k, v in sorted(comp.items())
                           if k not in NON_SCORED_ARMS})
    print('   DROPPED %s -- in no pair; standdown is @seconds=0 and its count'
          % (dropped or '{}'))
    print('   is set by extraction timing rather than by the design.')
    if not kept:
        print('   REFUSED. Every window was a non-scored step.')
        return 1
    print()

    # ---- Arms ----------------------------------------------------------
    by_arm = {}
    for w in kept:
        by_arm.setdefault(ac.arm_of(w), []).append(w)

    print('2. ARMS, counted before any verdict')
    for arm in sorted(by_arm, key=ac.arm_sort):
        print('   %s %3d window(s)%s'
              % (ac.arm_label(arm), len(by_arm[arm]),
                 '' if len(by_arm[arm]) >= ac.MIN_WINDOWS else '   (not scored)'))
    scored = {a: ws for a, ws in by_arm.items() if len(ws) >= ac.MIN_WINDOWS}
    print()

    # Check 3 is only defined where a marking exists -- i.e. on cull arms.
    cull_arms = [a for a in scored if a[0]]
    if not cull_arms:
        print('REFUSED. No cull arm reaches %d windows, so nothing was marked'
              % ac.MIN_WINDOWS)
        print('and the ratio has no denominator. Not a low ratio -- no ratio.')
        return 1

    # ---- The ratio ------------------------------------------------------
    print('3. RATIO, per cull arm')
    failed = []
    for arm in sorted(cull_arms, key=ac.arm_sort):
        ws = scored[arm]
        offs = [float((w['bots'])[FIELD]) for w in ws]
        marks = [float((w.get('bots') or {}).get(MARK) or 0) for w in ws]

        med_off, med_mark = ac.median(offs), ac.median(marks)
        print('   %s' % ac.arm_label(arm))
        print('     %s %6.2f   %s %6.2f   (medians over %d windows)'
              % (MARK, med_mark, FIELD, med_off, len(ws)))

        # STRUCTURAL INVARIANT, asserted before any ratio is printed.
        # `animCulledOffScreen` counts marked bots that are also off-screen, so
        # it is a SUBSET of `animCulled` and the ratio cannot exceed 1.0. A
        # value above 1.0 is not a high ratio -- it is two counters walking
        # different populations, and every number on this arm is then void.
        # This is why the ratio is ceiling-censored, which is load-bearing for
        # choosing an estimator: `median of ratios` sits ON that ceiling.
        # Asserted rather than assumed -- the ceiling is the reason the
        # estimator argument works, so nothing may quietly violate it.
        over = [(o, m) for o, m in zip(offs, marks) if m and o > m]
        if over:
            print('             IMPOSSIBLE: %s EXCEEDS %s in %d window(s),'
                  % (FIELD, MARK, len(over)))
            print('             worst %g > %g. Off-screen is a SUBSET of the'
                  % (max(o for o, m in over),
                     max(m for o, m in over)))
            print('             marking, so this ratio cannot exceed 1.0. Two')
            print('             counters are walking different populations and')
            print('             every figure on this arm is void.')
            failed.append('%s: %s exceeds %s in %d window(s)'
                          % (ac.arm_label(arm), FIELD, MARK, len(over)))
            continue

        if not med_mark:
            print('             DENOMINATOR ZERO. Nothing was marked on a cull')
            print('             arm, so the ratio is undefined rather than low.')
            failed.append('%s marked nothing' % ac.arm_label(arm))
            continue

        ratio_of_medians = med_off / med_mark
        per_window = [o / m for o, m in zip(offs, marks) if m]
        median_of_ratios = ac.median(per_window)
        if median_of_ratios is None:
            print('             NO WINDOW CARRIES A MARKING. Undefined, not'
                  ' low.')
            failed.append('%s: no window carries a marking'
                          % ac.arm_label(arm))
            continue
        pooled = sum(offs) / sum(marks)

        print('             pooled  (sum/sum)  %.3f   <- honoured overall'
              % pooled)
        print('             ratio of medians   %.3f' % ratio_of_medians)
        print('             median of ratios   %.3f' % median_of_ratios)

        # The DISTRIBUTION, because a third estimator does not help if the
        # quantity is not a point. Reported always, not only on disagreement.
        below = [r for r in per_window if r < 1.0]
        print('             per-window range   %.3f - %.3f over %d windows'
              % (min(per_window), max(per_window), len(per_window)))
        print('             windows below 1.0  %d of %d'
              % (len(below), len(per_window)))

        # Interval on POOLED, which is the estimator Beta's row is bound to.
        rng = random.Random(BOOTSTRAP_SEED)
        widest = None
        for block in BOOTSTRAP_BLOCKS:
            lo, hi = pooled_interval(offs, marks, block, rng)
            if lo is None:
                print('             pooled 95%% CI  block=%d  -- too few windows'
                      % block)
                continue
            print('             pooled 95%% CI  block=%d   %.3f - %.3f  (w %.3f)'
                  % (block, lo, hi, hi - lo))
            if widest is None or (hi - lo) > (widest[1] - widest[0]):
                widest = (lo, hi, block)
        if widest:
            print('             USE THIS ONE   %.3f - %.3f  (block=%d, widest)'
                  % (widest[0], widest[1], widest[2]))
            print('             ^ the WIDER of the two, whichever it is. Not')
            print('               block=4 by rule: this file assumed')
            print('               correlation would widen the interval and the')
            print('               measurement contradicted it -- see the note')
            print('               at BOOTSTRAP_BLOCKS. Taking the wider is')
            print('               robust to that assumption being wrong.')
        print('             seed %d, %d resamples, reproducible.'
              % (BOOTSTRAP_SEED, BOOTSTRAP_N))

        gap = abs(ratio_of_medians - median_of_ratios)
        if gap > ESTIMATOR_TOLERANCE:
            # NOT a refusal. Two estimators that disagree are a bracket, and
            # this one is signal: the marking moves within the arm. Refusing
            # here would fail a clean run, which is the exact defect this
            # project has already paid for once -- and which this file did on
            # its first outing against real data, with a tolerance its author
            # had guessed. Report the interval; let the reader judge.
            print('             ESTIMATORS DISAGREE by %.3f -- REPORTED, NOT'
                  ' REFUSED.' % gap)
            print('             The ratio is not a point on this arm. Quote it')
            print('             as the interval %.3f - %.3f and say which'
                  % (min(ratio_of_medians, median_of_ratios),
                     max(ratio_of_medians, median_of_ratios)))
            print('             estimator you used. `pooled` is the one with a')
            print('             plain reading: the fraction of ALL marking that')
            print('             Unity honoured.')
        else:
            print('             estimators agree to %.3f' % gap)
    print()

    print('NO THRESHOLD IS REGISTERED FOR THIS RATIO.')
    print('   The number above is a measurement, not a verdict. The protocol')
    print('   says only that a low ratio on an open map is the interesting')
    print('   failure -- a direction, not a bound. Do not read a printed ratio')
    print('   as check 3 having PASSED; read it as check 3 having been RUN,')
    print('   which until today it never was.')
    print()

    if failed:
        print('REFUSED:')
        for f in failed:
            print('   - %s' % f)
        return 1

    print('COMPUTED. The ratio is available for every scored cull arm.')
    return 0


if __name__ == '__main__':
    code = main(sys.argv)
    # DELIBERATE MUTATION HOOK, for delta-check3-selftest.py --prove.
    # Set DELTA_C3_MUTATE=always-zero and this reader stops refusing --
    # the "instrument returns its own success value" failure, injected on
    # purpose. The selftest asserts that its refusal cases go MISMATCH when
    # this is set. A suite that stays green against this mutant cannot
    # detect a broken reader, and its green result means nothing.
    # It is read from the environment and never from a log, so no data file
    # can reach it.
    if os.environ.get('DELTA_C3_MUTATE') == 'always-zero':
        code = 0
    sys.exit(code)
