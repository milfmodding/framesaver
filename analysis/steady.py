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
"""

WARMUP_S = 120.0


def is_steady(w, warmup_s=WARMUP_S, require_population=False):
    """True when this sample window is in-raid, whole, and past warm-up.

    `w` is a parsed `type == 'sample'` line. Callers still apply their own
    field-presence gates -- this answers "is this window comparable", never
    "does this window carry my field".
    """
    if w.get('state') != 'raid':
        return False
    if w.get('final'):
        return False
    if (w.get('raidElapsed') or 0.0) < warmup_s:
        return False
    if require_population and not ((w.get('bots') or {}).get('total') or 0):
        return False
    return True


def describe(warmup_s=WARMUP_S, require_population=False):
    """One line naming the population, for a reader to print above its results.

    Printed rather than assumed, because two readers quoting the same field over
    different populations is exactly what this file exists to stop, and the only
    way a human catches it is seeing both definitions side by side.
    """
    base = 'in-raid, not final, raidElapsed >= %.0fs' % warmup_s
    return base + (', bots.total > 0' if require_population else '')


def partition(rows, warmup_s=WARMUP_S, require_population=False):
    """(kept, dropped_by_clause) so a reader can show its own attrition.

    A count of what a filter removed is worth more than the filter passing
    silently: it is the difference between "33 windows" and "33 of 37, four lost
    to warm-up", and only the second lets anyone tell an underpowered run from a
    badly filtered one.
    """
    kept = []
    dropped = {'not sample': 0, 'not raid': 0, 'final': 0,
               'warm-up': 0, 'empty roster': 0}
    for w in rows:
        if w.get('type') != 'sample':
            dropped['not sample'] += 1
        elif w.get('state') != 'raid':
            dropped['not raid'] += 1
        elif w.get('final'):
            dropped['final'] += 1
        elif (w.get('raidElapsed') or 0.0) < warmup_s:
            dropped['warm-up'] += 1
        elif require_population and not ((w.get('bots') or {}).get('total') or 0):
            dropped['empty roster'] += 1
        else:
            kept.append(w)
    return kept, dropped
