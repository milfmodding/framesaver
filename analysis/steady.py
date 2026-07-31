#!/usr/bin/env python3
"""The steady-state window definition, stated ONCE so readers cannot drift.

WHY THIS FILE EXISTS. Alpha and I quoted the LateUpdate remainder as 0.679 and
0.726 ms from the same two logs -- a 7% gap on a 0.7 ms number, caused entirely
by "steady state" never having been written down. That is the population error
in its mildest form, and it was mild only by luck: the same undefined term sits
under every rate, share and contrast any of us has published.

Worse, my OWN readers disagreed with each other. Measured over the 520 sample
lines in the corpus on 2026-07-30:

    raid + elapsed>=120 + not final                 363 windows
    the same + bots.total > 0  (read-marathon)      347 windows   -4.4%
    elapsed>=120 + not final   (read-updatemanual)  363 windows
    raid + not final, no warm-up cut                401 windows

The third agreed with the first by ACCIDENT. `read-updatemanual` never tested
`state == 'raid'` at all; it was saved only because no non-raid sample in this
corpus carries `raidElapsed >= 120` -- zero of 520. That is the same
excluded-as-a-side-effect defect that reader's own docstring already names about
`final`, sitting one line above it. A future build that carried `raidElapsed`
across the post-raid screen would silently admit menu windows, and nothing would
look wrong.

So this is code rather than a paragraph in CORPUS.md. A prose definition drifts
from the readers that are supposed to obey it, and then the doc is a claim about
the code rather than a description of it -- which is the same failure as a
docstring promising behaviour no branch implements.

THE CLAUSES, each with the reason it is there rather than the effect it has:

  state == 'raid'   Menus render a static screen at hundreds of fps and loading
                    windows carry stalls measured in seconds. Both destroy any
                    rate they are pooled into, in opposite directions.

  not final         The last window of a raid is truncated by the raid ending,
                    so every per-second quantity in it has a denominator that
                    does not mean what the others mean.

  raidElapsed >=    Warm-up. Shaders compile, the world streams in and the bot
  WARMUP_S          roster is still filling, so early windows measure the
                    machine settling rather than the game running.

  bots.total > 0    OPTIONAL and off by default. It is a stricter population,
                    not a truer one: it additionally drops in-raid windows whose
                    roster census came back empty. Correct when the quantity is
                    per-bot, wrong when the quantity is per-frame -- a window
                    with no bots is a legitimate observation of a frame cost.
                    read-marathon.py wants it; read-updatemanual.py does not.

WARMUP_S is 120 because that is what every reader already used. It is inherited,
not derived, and nobody has tested the corpus's sensitivity to it -- which is
worth knowing before anyone treats it as a measured boundary.

AND IT IS NOT WINDOW-LENGTH NEUTRAL, WHICH MATTERS THE MOMENT WINDOWS CHANGE.
`raidElapsed` is stamped at the window boundary, so on 60 s windows it only ever
takes values near 60/61, 120/121, 180/181 -- measured across the corpus: 36
windows at 60-61, 36 at 120-121, 32 at 180-181, and nothing in between. A
threshold of 120 therefore discards exactly the window covering 0-61 s.

On 30 s windows the same threshold discards the windows closing at 31, 61 AND
91, so the discard grows from ~61 s of raid to ~91 s. The steady-state
population is not the same on either side of a window-length change, and nobody
has to edit this constant for that to happen.

read-marathon.py states the intent plainly -- skip each leg's raid-init window,
which has a 704 ms median worst frame. That intent is "one window"; this
implementation is "120 seconds"; the two coincide only at 60 s. Expressed as
windows the discard would be stable, and expressed as seconds it is not.

Flagged rather than changed: altering a shared population definition is not
something to do between a decision to halve the window and the raid that uses
it. Whoever compares a 30 s run against the 60 s corpus needs to know the
warm-up discard differs by 30 s before they read the difference as an effect.
"""

WARMUP_S = 120.0

# Alpha measured how long warm-up actually lasts, rather than inheriting a
# threshold: each early window against its own leg's later baseline, over ALL
# in-raid windows including the ones warm-up would exclude - because the
# excluded population is the subject and cannot be filtered by the thing under
# test. The damage is one window and it is entirely in the tail.
#
# Figures are Alpha's SECOND run, after the positional teardown exclusion below
# was applied to their late baseline - their first dropped only `final`, which
# marks 17 of 33, leaving 16 truncated windows in the baseline the ratio divides
# by. Both populations, because a corrected number that cannot be compared to
# the one it replaced is not obviously a correction:
#
#     dropping `final` only    window 1  mean 1.008   worst 4.38x
#     dropping teardown, all   window 1  mean 0.985   worst 4.53x
#
# It survives and strengthens. And window 1's MEAN ratio is BELOW baseline and
# the lowest of the four, because early raid has fewer bots awake - so a
# mean-based warm-up check would have concluded there is no warm-up at all.
# A mean can look settled while the tail has not.
WARMUP_DURATION_S = 60.0


def window_length(w):
    """Seconds this window covers, or None if it cannot be resolved.

    None is a REFUSAL, never a zero. Treating an unknown length as 0 would make
    every window look like it began at its own stamp and keep everything - the
    absent-is-not-zero trap arriving in a length rather than a count.

    `windowSec` is absent rather than present-as-zero on much of the corpus, so
    the header fallback is doing real work rather than covering an edge case:
    measured 2026-07-31, 384 of SPT4.0.13's 594 in-raid windows carry it and
    **0 of Base's 301 do**. Callers that strip headers must stamp
    `_windowSeconds` onto each row, as read-updatemanual's load() does -- and
    must read it from the header's TOP LEVEL, not from `header.config`, which
    is where read-animcull.py got it wrong and lost every window in a log.

    (This said "210 of the 418 in-raid windows in the corpus". Both numbers
    were right when written and neither corpus has 418 windows now. A count
    quoted without its date and its directory goes stale silently.)
    """
    v = w.get('windowSec')
    if v:
        return float(v)
    v = (w.get('cfg') or {}).get('windowSeconds')
    if v:
        return float(v)
    v = w.get('_windowSeconds')
    return float(v) if v else None


def past_warmup(w, warmup_s=WARMUP_S, by_start=False):
    """Whether this window is past warm-up, by either rule.

    `by_start` is Alpha's: keep a window only if it BEGINS after warm-up ends.
    A window stamped `e` of length `l` covers [e-l, e], so the test is
    `e - l >= WARMUP_DURATION_S`.

    NO LONGER EQUIVALENT, AND THE CLAIM THAT IT WAS HAS EXPIRED. This said
    "PROVEN EQUIVALENT ON THE EXISTING CORPUS: 418 of 418 in-raid windows
    agree, zero disagreements." That was measured, and it is now false --
    re-run 2026-07-31:

        SPT4.0.13   594 in-raid windows   584 agree   10 DISAGREE
        Base        301 in-raid windows   268 agree   33 DISAGREE

    Every disagreement is a window this rule KEEPS and the legacy one drops,
    all of them at `raidElapsed` ~90 with a 30 s length (and ~75-105 at 15 s in
    Base). Which is precisely what the paragraph below always said would
    happen: at 60 s `e - 60 >= 60` IS `e >= 120`, at 30 s it becomes `e >= 90`.

    The equivalence was never a property of the rule. It was a property of a
    corpus that only had 60 s windows, and the corpus stopped having that.
    Nothing here changed; the world did. That is the same shape as a docstring
    outliving its code, arriving as a number in prose rather than as behaviour
    - so it is not caught by any check we have, only by re-running it.

    The consequence is live, not theoretical: readers on `by_start=True`
    (read-updatemanual, read-animcull) now hold 10 windows that a legacy-rule
    reader drops. by_start is still the BETTER rule for the reason below. It is
    just no longer the SAME rule, so two readers quoting the same field over
    "steady state" can now differ, and the number above is how much.

    Off by default only because it needs a resolvable window length, and a
    reader that strips headers without stamping `_windowSeconds` would have its
    windows refused rather than measured. Opt in once the loader carries it.
    """
    e = w.get('raidElapsed') or 0.0
    if not by_start:
        return e >= warmup_s
    length = window_length(w)
    if length is None:
        return False
    return (e - length) >= WARMUP_DURATION_S



def is_steady(w, warmup_s=WARMUP_S, require_population=False,
              by_start=False):
    """True when this sample window is in-raid, whole, and past warm-up.

    `w` is a parsed `type == 'sample'` line. Callers still apply their own
    field-presence gates -- this answers "is this window comparable", never
    "does this window carry my field".
    """
    if w.get('state') != 'raid':
        return False
    if w.get('final'):
        return False
    if not past_warmup(w, warmup_s, by_start):
        return False
    if require_population and not ((w.get('bots') or {}).get('total') or 0):
        return False
    return True


def describe(warmup_s=WARMUP_S, require_population=False,
             drop_teardown=False, by_start=False):
    """One line naming the population, for a reader to print above its results.

    Printed rather than assumed, because two readers quoting the same field over
    different populations is exactly what this file exists to stop, and the only
    way a human catches it is seeing both definitions side by side.
    """
    if by_start:
        base = ('in-raid, not final, window begins >= %.0fs into the raid'
                % WARMUP_DURATION_S)
    else:
        base = 'in-raid, not final, raidElapsed >= %.0fs' % warmup_s
    if require_population:
        base += ', bots.total > 0'
    if drop_teardown:
        base += ', excluding each teardown window'
    return base


def sources(paths):
    """One line naming WHICH corpus was read, for a reader to print.

    WHY A READER MUST SAY THIS. There are two log directories on this machine
    -- F:\\SPT\\Base\\... (which CORPUS.md documents) and F:\\SPT\\SPT4.0.13\\...
    (where the marathon landed). Base carries zero windows with `updateManual`;
    SPT4.0.13 carries 258. I read Base all day and told the team a field was
    absent everywhere, and every reader I ran printed a population line that
    described the FILTER in detail and never once said which files it had
    opened.

    A population is (definition, input), and stating half of it precisely is
    what makes the other half invisible. Same error as keying one map per log,
    one level up.
    """
    import os
    dirs = {}
    for p in paths:
        d = os.path.dirname(os.path.abspath(p)) or '.'
        dirs[d] = dirs.get(d, 0) + 1
    if len(dirs) == 1:
        d, n = list(dirs.items())[0]
        return '%d file(s) from %s' % (n, d)
    # More than one directory is worth shouting about: it is either deliberate
    # pooling or the two-corpus mistake, and the reader cannot tell which.
    return 'MIXED SOURCES - ' + '; '.join(
        '%d from %s' % (n, d) for d, n in sorted(dirs.items()))


def resolve_inputs(args):
    """(paths, source_line, refusal) -- refuse a pooled corpus by default.

    `refusal` is a message string, or None when the run may proceed. Readers
    print `source_line`, then exit 2 on a refusal.

    WHY REFUSE RATHER THAN WARN. Beta established that the two directories are
    not two builds of one thing, they are two playable installs with different
    AI mod stacks -- Base has no SAIN/BigBrain/Waypoints/LootingBots, and
    ModCompat's stand-downs key on detected plugins, so `agents.slicing` and
    the stand-by guards can differ for reasons that are not our configuration.

    Pooling them averages two mod environments into one plausible number, and
    **that failure has no signature**: no field goes out of range, no ratio
    looks wrong, nothing fails. A warning printed above a result that looks
    fine is read as noise. This is the case where a refusal is proportionate.

    And it cannot be detected from inside the files. `mods` is present in 3 of
    25 SPT4.0.13 logs and 0 of 30 Base logs, so its absence means "old build"
    and covers both populations. **Directory is the only attribution available
    for 52 of the 55 logs**, which is exactly why it has to be on the line.

    `--pool` is the explicit opt-in. It takes an argument list rather than
    paths so the flag never reaches a glob as a filename.
    """
    import os
    paths = [a for a in args if not a.startswith('--')]
    pool = '--pool' in args
    line = sources(paths)
    if len(set(os.path.dirname(os.path.abspath(p)) or '.'
               for p in paths)) <= 1 or pool:
        return paths, line + (' [POOLED, explicitly]' if pool else ''), None
    return paths, line, (
        'REFUSED: inputs span more than one install, and the installs carry\n'
        'different AI mod stacks. Pooling them averages two environments into\n'
        'one plausible number and nothing downstream would look wrong. Re-run\n'
        'against one directory, or pass --pool if that is genuinely intended.')


def is_teardown(rows):
    """Set of ids of windows that are the LAST in-raid window of their segment.

    Those windows were closed by the raid ending rather than by their timer, and
    three things are wrong with them at once: the roster census reads 0 because
    the game object is gone, the instant-sampled fields (snipersAwake,
    animCulled, agents.live) carry stale values, and the window itself is
    truncated -- a measured median of 25.0 s against a configured 60.

    All 33 such windows in the corpus are last-of-segment, 33 of 33, and `final`
    marks only 17 of them: `final` means "the session ended", which is a
    different question, so no existing filter catches the other 16.

    NOT A PER-WINDOW PREDICATE, which is why this lives here and not in
    is_steady(): segment position cannot be seen from one window. Identity is
    (log, raid, map) per read-marathon.py's `legs()` -- keyed on the raid
    counter because a session can revisit a map and those visits must not merge.
    """
    last = {}
    for i, w in enumerate(rows):
        if w.get('type') != 'sample' or w.get('state') != 'raid':
            continue
        last[(w.get('_log'), w.get('raid'), w.get('map'))] = i
    return set(last.values())


def partition(rows, warmup_s=WARMUP_S, require_population=False,
              drop_teardown=False, by_start=False):
    """(kept, dropped_by_clause) so a reader can show its own attrition.

    A count of what a filter removed is worth more than the filter passing
    silently: it is the difference between "33 windows" and "33 of 37, four lost
    to warm-up", and only the second lets anyone tell an underpowered run from a
    badly filtered one.
    """
    kept = []
    dropped = {'not sample': 0, 'not raid': 0, 'final': 0,
               'warm-up': 0, 'length unresolvable': 0,
               'empty roster': 0, 'teardown': 0}
    tear = is_teardown(rows) if drop_teardown else set()
    for i, w in enumerate(rows):
        if w.get('type') != 'sample':
            dropped['not sample'] += 1
        elif w.get('state') != 'raid':
            dropped['not raid'] += 1
        elif w.get('final'):
            dropped['final'] += 1
        # A REFUSAL AND AN EXCLUSION ARE DIFFERENT EVENTS AND USED TO SHARE A
        # BUCKET. Under by_start an unresolvable window length makes
        # past_warmup() return False, so a loader that stamps `_windowSeconds`
        # from the wrong path has every window charged to "warm-up" -- which is
        # a plausible-looking number, not an error. read-animcull.py read
        # header.config.windowSeconds instead of header.windowSeconds and lost
        # all 58 windows of a 58-window log that way. Same windows dropped
        # either way; `kept` is unchanged by this split, only the label is.
        elif by_start and window_length(w) is None:
            dropped['length unresolvable'] += 1
        elif not past_warmup(w, warmup_s, by_start):
            dropped['warm-up'] += 1
        elif require_population and not ((w.get('bots') or {}).get('total') or 0):
            dropped['empty roster'] += 1
        elif i in tear:
            dropped['teardown'] += 1
        else:
            kept.append(w)
    return kept, dropped
