#!/usr/bin/env python3
"""The per-BOT forceAllRoles contrast: cost split by the arm each bot was assigned.

WRITTEN BEFORE A SINGLE `botStandBy` ROW EXISTS. The field shipped in bc90b76 and
no log carries one. Every gate, threshold and registered prediction below was
fixed without knowing the answer, same as read-botwindow.py and
read-updatemanual.py.

WHY THE UNIT IS THE BOT AND NOT THE WINDOW. `forceAllRoles` is granted once, at
bot activation, and nothing revokes it -- QuestingBots would be the only thing
that could, and it is not installed. So a window-level ABAB does not alternate:
every window in the second A block is populated by bots still holding their B
grant. `read-updatemanual` detects that and refuses to difference across those
strata, which is correct and is not a result.

The latch is only fatal to the WINDOW design. Per bot it is an asset: assignment
happens once and holds for life, which a per-interval revocable flag would not
give. `botStandBy.forced` records the arm on the bot's own line, so the mixture
stops being a confound and becomes the design.

THE CONFOUND, STATED BEFORE ANY NUMBER. Assignment is by ACTIVATION TIME,
which is not random. Bots assigned to different arms ACTIVATED at different
points in the raid, so they differ in raid phase, player position, roster size
and what was happening around them. This is a natural experiment, not a
randomised one, and section 3 prints the activation-time overlap, because a
contrast between two non-overlapping stretches of raid time is a comparison of
raid phases wearing an arm label.

ACTIVATION, NOT CREATION, AND THE DIFFERENCE IS NOT COSMETIC. `method_10` fires
only when the bot is PreActive, its weapon manager is ready, and a NavMesh
sample succeeds -- retrying on a one-second timer when it does not. So a bot
created during arm A can activate during arm B and carries B's grant. Beta found
this; the code here already read the `botStandBy` stamp, which is the activation
one, but every label in this file said "spawn" until they did.

AND A REGISTERED INTERACTION WITH read-botwindow.py, WHICH IS THE POINT OF
WRITING THIS NOW. That reader tests whether per-bot cost varies with awake AGE.
If it finds a non-zero slope, then bots that activated earlier are older
and therefore cost differently FOR A REASON THAT IS NOT THE ARM -- and since
assignment here is by activation time, the age effect maps directly onto the
arm split. So:

    age slope indistinguishable from zero  ->  this contrast is interpretable
    age slope one-sided                    ->  this contrast is CONFOUNDED by
                                               activation-time composition and
                                               two readers must be read together

Neither outcome is known. Both are registered here, before either has run, so
nobody gets to pick the reading that suits the result.

Usage:  python read-botarm.py <log.ndjson> [more.ndjson ...]

Exit 0 when the contrast is readable, 1 when a gate fails, 2 on bad input.
"""

import collections
import json
import math
import statistics as st
import sys

MIN_BOTS_PER_ARM = 8    # below this the split has no power worth reporting
MIN_CALLS = 30          # a per-bot mean over fewer calls is mostly noise
OVERLAP_MIN = 0.30      # below this overlap the arms are raid phases, not arms
LATENCY_WARN = 5.0      # activation lag above this and the arm label is shaky


def load(paths):
    """botStandBy assignments, botWindow rows and botSpawn, by (log, bot id)."""
    arms, rows, born = {}, collections.defaultdict(list), {}
    for path in paths:
        try:
            fh = open(path, 'r', encoding='utf-8', errors='replace')
        except OSError as exc:
            print('cannot open %s: %s' % (path, exc))
            sys.exit(2)
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                kind = obj.get('type')
                if kind == 'botStandBy' and obj.get('id'):
                    # First assignment wins. A bot re-entering InitPoints would
                    # emit again, and the FIRST line is the one that decided the
                    # grant it has held since -- taking the last would silently
                    # relabel a bot with a later arm it never ran under.
                    arms.setdefault((path, obj['id']), obj)
                elif kind == 'botWindow' and obj.get('id'):
                    rows[(path, obj['id'])].append(obj)
                elif kind == 'botSpawn' and obj.get('id'):
                    born.setdefault((path, obj['id']), obj)
    return arms, rows, born


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    arms, rows, born = load(argv[1:])
    print('=' * 78)
    print('1. THE JOIN, AND WHAT IT LOSES')
    print('=' * 78)
    print('  botStandBy assignments   %d' % len(arms))
    print('  bots with cost rows      %d' % len(rows))
    if not arms or not rows:
        print('\n  No botStandBy row (bc90b76) or no botWindow row in any input.')
        print('  A log without them predates the build. Coverage gap, not a null')
        print('  result - it clears as soon as one raid runs.')
        print('\nGATE FAILED - nothing to read.')
        return 1

    matched = [k for k in rows if k in arms]
    orphan_cost = [k for k in rows if k not in arms]
    orphan_arm = [k for k in arms if k not in rows]
    print('  joined on id             %d' % len(matched))
    # An unmatched bot is not a rounding error: it has cost and no arm, so it
    # cannot enter the contrast, and if the unmatched set is arm-correlated the
    # exclusion is itself a treatment effect. Counted and reported, never
    # silently dropped.
    if orphan_cost:
        print('  ! %d bot(s) have cost rows and NO assignment - excluded, and if that'
              % len(orphan_cost))
        print('    set is arm-correlated the exclusion biases the contrast.')
    if orphan_arm:
        print('  %d bot(s) assigned but never billed a window - expected for bots that'
              % len(orphan_arm))
        print('    died or despawned before a window closed.')
    if not matched:
        print('\nGATE FAILED - no bot has both an arm and a cost.')
        return 1

    print()
    print('=' * 78)
    print('2. DID THE ARM ACTUALLY FIRE?   effective vs roleAllows')
    print('=' * 78)
    # The pairing that makes this readable at all. `forced` is what was asked
    # for; `effective` is the grant the bot got. The bots that DISCRIMINATE are
    # the ones whose role would normally refuse - roleAllows False. Under
    # forced=True those must come out effective=True, and if they do not, the
    # arm did not reach the population and nothing below means anything.
    disc = [arms[k] for k in matched if arms[k].get('roleAllows') is False]
    print('  bots whose role refuses stand-by (roleAllows False)   %d' % len(disc))
    if not disc:
        # A GATE, not a note. If no bot's role refuses stand-by then
        # forceAllRoles overrode nothing, so any contrast below is by definition
        # not the arm's effect - and printing it invites exactly that
        # attribution. My crash test caught this: the synthetic warned and then
        # produced +0.004 ms/call anyway, which is the caveat-with-no-teeth
        # shape I have been finding in other people's work all day.
        print('  ! no discriminating bot in this input: every bot\'s role already')
        print('    allowed stand-by, so forceAllRoles had nothing to override and')
        print('    the arm is unobservable here. Not evidence it works.')
        print('\nGATE FAILED - the treatment is a no-op on this population, so no')
        print('contrast can be attributed to it.')
        return 1
    else:
        by_arm = collections.Counter()
        for a in disc:
            by_arm[(bool(a.get('forced')), bool(a.get('effective')))] += 1
        for forced in (True, False):
            got = by_arm[(forced, True)]
            tot = got + by_arm[(forced, False)]
            if tot:
                print('    forced=%-5s -> effective True in %d of %d (%.0f%%)'
                      % (forced, got, tot, 100.0 * got / tot))
        bad = by_arm[(True, False)]
        if bad:
            print('  ! %d bot(s) were assigned forced=True and still refused the grant.'
                  % bad)
            print('    The arm did not reach them. The contrast below is not quotable.')
            print('\nGATE FAILED - treatment not delivered.')
            return 1

    print()
    print('=' * 78)
    print('3. ACTIVATION-TIME OVERLAP   the confound, before the contrast')
    print('=' * 78)
    act = collections.defaultdict(list)
    for k in matched:
        a = arms[k]
        el = a.get('raidElapsed')
        if el is not None:
            act[bool(a.get('forced'))].append(float(el))
    if len(act) < 2:
        print('  only one arm present - no contrast, and no overlap to report.')
        print('\nGATE FAILED - a one-arm input cannot answer this.')
        return 1
    lo_hi = {}
    for arm, xs in act.items():
        xs.sort()
        lo_hi[arm] = (xs[0], xs[-1])
        print('  forced=%-5s n=%-4d activated %.0f .. %.0f s (median %.0f)'
              % (arm, len(xs), xs[0], xs[-1], st.median(xs)))
    # Activation latency, which Beta pointed out is free once both lines are
    # loaded: botStandBy.raidElapsed - botSpawn.raidElapsed for the same id. A
    # bot with a long lag is one whose arm label is least trustworthy, because
    # it is the one most likely to have been created under the other arm.
    lags = []
    for k in matched:
        b = born.get(k)
        if not b:
            continue
        t0, t1 = b.get('raidElapsed'), arms[k].get('raidElapsed')
        if t0 is not None and t1 is not None:
            lags.append(float(t1) - float(t0))
    if lags:
        slow = sum(1 for x in lags if x > LATENCY_WARN)
        print('  activation lag  median %.1f s  max %.1f s  over %.0fs: %d of %d bots'
              % (st.median(lags), max(lags), LATENCY_WARN, slow, len(lags)))
        if slow:
            print('    those %d were created under one arm and may have activated under' % slow)
            print('    the other - their labels are the least trustworthy in the set.')
    else:
        print('  activation lag  not computable (no botSpawn line carries raidElapsed)')

    (a_lo, a_hi), (b_lo, b_hi) = lo_hi[True], lo_hi[False]
    inter = max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))
    union = max(a_hi, b_hi) - min(a_lo, b_lo)
    frac = (inter / union) if union > 0 else 0.0
    print('  overlap %.0f%% of the combined span' % (frac * 100))
    if frac < OVERLAP_MIN:
        print('  ! the arms occupy DIFFERENT stretches of raid time. This is a')
        print('    comparison of raid phases wearing an arm label, and no amount of')
        print('    per-bot precision fixes it.')

    print()
    print('=' * 78)
    print('4. THE CONTRAST   ms per call, by assigned arm')
    print('=' * 78)
    per_arm = collections.defaultdict(list)
    for k in matched:
        ms = sum(float(r.get('ms') or 0.0) for r in rows[k])
        n = sum(r.get('n') or 0 for r in rows[k])
        if n >= MIN_CALLS:
            per_arm[bool(arms[k].get('forced'))].append(ms / n)
    for arm in (True, False):
        xs = per_arm.get(arm) or []
        if len(xs) < MIN_BOTS_PER_ARM:
            print('  forced=%-5s only %d bot(s) over %d calls - too few to score'
                  % (arm, len(xs), MIN_CALLS))
        else:
            print('  forced=%-5s n=%-4d median %.5f ms/call  IQR %.5f'
                  % (arm, len(xs), st.median(xs),
                     st.quantiles(xs, n=4)[2] - st.quantiles(xs, n=4)[0]))
    if min(len(per_arm.get(True) or []), len(per_arm.get(False) or [])) < MIN_BOTS_PER_ARM:
        print('\nGATE FAILED - underpowered. Reporting a difference here would invite')
        print('a conclusion the data cannot carry.')
        return 1
    d = st.median(per_arm[True]) - st.median(per_arm[False])
    print('  contrast (forced - default)   %+.5f ms/call' % d)
    print()
    print('  A DIFFERENCE OF MEDIANS IS NOT A MEDIAN. These are disjoint bot sets')
    print('  so no pairing exists and the unpaired form is correct here - unlike a')
    print('  per-window remainder, where it was not.')

    print()
    print('=' * 78)
    print('5. WHAT THIS CANNOT ANSWER')
    print('=' * 78)
    print('  Assignment is by activation time, not at random, so this is a natural')
    print('  experiment. Quote it as a direction, never as a price.')
    print('  If read-botwindow finds a non-zero awake-age slope, this contrast is')
    print('  CONFOUNDED by activation-time composition and both must be read together.')
    print('  Registered before either ran, so the reading cannot be chosen after.')
    print('  And these are sums and counts with no maximum: silent on goal 2.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
