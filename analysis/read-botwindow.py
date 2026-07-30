#!/usr/bin/env python3
"""Does an awake bot get more expensive as it stays awake? WITHIN bot, not pooled.

WRITTEN BEFORE A SINGLE `botWindow` ROW EXISTS. The field is in the deployed
build (cb47968) and no log in the 24-log corpus carries one. Every gate, every
threshold and the registered prediction below were fixed without knowing the
answer, same as read-marathon.py, read-aitotal-aba.py and read-updatemanual.py.

THE HYPOTHESIS, which is Beta's and Alpha's rather than mine: per-bot cost may
be a function of AWAKE AGE. If it is, every pooled per-bot figure we have ever
quoted is a function of the population's age distribution, and two runs with the
same bot count can disagree for a reason nothing in the pooled numbers records.

WHY WITHIN-BOT. Pooling bots of different ages confounds a trajectory with a
composition: the arms wake different populations, so an age-vs-cost curve drawn
across bots would move when the mix moved even if no individual bot ever changed.
A slope computed inside one bot's own span cannot do that. It costs statistical
power and buys the only interpretation worth having.

SURVIVORSHIP IS THE THREAT AND IT IS NOT FULLY SOLVED HERE. Within-bot removes
selection BETWEEN bots; it does not remove a bot LEAVING the sample. If expensive
bots die or sleep sooner, the old-age rows belong to cheap bots and even honest
within-bot slopes are drawn from a thinning, non-random survivor set. Section 2
prints the attrition curve so the reader can see how much of the age range rests
on how few bots, rather than being told the slope and trusting it.

A RE-WAKE IS NOT A CONTINUATION. `Ended()` closes a span on death or sleep and
`Woke()` starts a new one, so a bot's rows across a raid can hold several spans
and `awakeS` RESETS between them. Regressing a bot's rows without splitting on
that reset injects a large negative step wherever a bot slept and woke again --
which is exactly the population the stand-by work moves, so the artefact would
correlate with the treatment.

Spans are identified by `spanS`, the span's start timestamp, so the identity is
exact: same `id` AND same `spanS` is one continuous awake period. This file
originally split on a DECREASE in `awakeS`, which Beta showed fails in one
direction -- a bot that sleeps and re-wakes early in a window ends that window
older than the previous row, so the age rises across a genuine reset and the
break is invisible. Reachable at our default 60 s window and not only at long
ones. The decrease rule is retained as an independent cross-check and any
disagreement between the two is reported rather than silently resolved.

CORPSES ARE ALREADY OUT. `Ended()` drops a bot on death and the age is excluded
outright rather than counted, so these rows are corpse-free by construction --
unlike `updateManual.awakeMs`, which needs `deadMs` subtracted. That is what
makes section 1's identity meaningful: the rows must sum to `awakeMs - deadMs`,
not to `awakeMs`.

Usage:  python read-botwindow.py <log.ndjson> [more.ndjson ...]

Exit 0 when the rows are readable and reconcile, 1 when a gate fails, 2 on bad
input.
"""

import collections
import json
import math
import statistics as st
import sys

import steady

MIN_ROWS_PER_SPAN = 3   # two points are a difference, not a slope
MIN_CALLS = 30          # a per-window mean over fewer calls is mostly noise
MIN_SPANS = 8           # below this the sign test has no power worth reporting
RECONCILE_TOL = 0.02    # 2% between the rows and the pooled field


def load(paths):
    """Sample windows and botWindow rows, keyed by (log, window)."""
    samples, rows = {}, collections.defaultdict(list)
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
                if kind == 'sample':
                    samples[(path, obj.get('window'))] = obj
                elif kind == 'botWindow':
                    rows[(path, obj.get('window'))].append(obj)
    return samples, rows


def spans(bot_rows):
    """Split one bot's rows into continuous-awake spans.

    Returns (spans, disagreements) where `disagreements` counts adjacent pairs
    on which the two rules below reach different verdicts.

    `spanS` (ebae1e6) is the span's START timestamp, so identity is EXACT:
    same id AND same spanS is the same continuous awake period, and no
    inference is involved.

    The age-decrease rule this file shipped with was nearly right and failed in
    one direction, which Beta found. A bot that sleeps and re-wakes EARLY in a
    window can end that window OLDER than the previous row, so `awakeS` RISES
    across a genuine reset and the break is invisible. Reachable at our default
    60 s window, not only at long ones: a bot at age 40 that sleeps and wakes
    5 s later reads ~53 at the next window close, and 53 > 40 looks continuous.
    A bot that sleeps and re-wakes inside a window IS the treated population,
    so the artefact would correlate with the treatment rather than falling
    randomly -- the exact failure the split exists to prevent, arriving by the
    one route the old rule did not cover.

    The decrease rule is KEPT as a cross-check rather than deleted. It is free,
    it is independent, and a disagreement between two rules for one quantity
    means one of them is wrong -- which is worth surfacing rather than
    resolving silently in favour of the newer one.
    """
    out, cur, disagree = [], [], 0
    for r in bot_rows:
        if cur:
            prev = cur[-1]
            by_start = (r.get('spanS') is not None
                        and prev.get('spanS') is not None
                        and r['spanS'] != prev['spanS'])
            by_age = r['awakeS'] <= prev['awakeS']
            has_start = r.get('spanS') is not None and prev.get('spanS') is not None
            if has_start and by_start != by_age:
                disagree += 1
            # spanS decides where it exists; the age rule is the fallback for
            # rows predating the field, never an override of an exact identity.
            if by_start if has_start else by_age:
                out.append(cur)
                cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    return out, disagree


def ols_slope(xs, ys):
    """Least-squares slope, or None when x has no spread."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / sxx


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    samples, rows = load(argv[1:])
    print('=' * 78)
    print('1. THE ROWS RECONCILE WITH THE POOLED FIELD')
    print('=' * 78)
    print('  sample windows      %d' % len(samples))
    print('  windows with rows   %d' % len(rows))
    if not rows:
        print('\n  No botWindow row in any input. The field is in the build (cb47968);')
        print('  a log without it predates that build. This is a coverage gap and not')
        print('  a null result - it clears as soon as one raid runs.')
        print('\nGATE FAILED - nothing to read.')
        return 1

    # The disaggregated rows must sum to the pooled field, or one of them is
    # wrong and there is no way to tell which from either alone. Corpses are
    # already out of the rows, so the pooled side needs deadMs subtracted --
    # comparing against awakeMs would fail for a reason that is not a defect.
    bad = []
    checked = 0
    for key, rs in sorted(rows.items()):
        w = samples.get(key)
        # Population from analysis/steady.py, but with the warm-up cut turned
        # OFF deliberately: a within-bot slope wants the whole span, and a bot
        # awake from the first minute would otherwise have its early rows
        # removed and its trajectory truncated at the young end - biasing the
        # very slope this file measures. In-raid and not-final still apply,
        # because a truncated final window's ms are not comparable.
        if not w or not steady.is_steady(w, warmup_s=0.0):
            continue
        if w.get('updateManual') is None:
            continue
        um = w['updateManual']
        if um.get('deadMs') is None:
            continue
        pooled = float(um.get('awakeMs') or 0.0) - float(um.get('deadMs') or 0.0)
        got = sum(float(r.get('ms') or 0.0) for r in rs)
        checked += 1
        denom = max(abs(pooled), 1e-9)
        if abs(got - pooled) / denom > RECONCILE_TOL:
            bad.append((key[1], got, pooled))
    print('  windows reconciled  %d' % checked)
    if not checked:
        print('  ! no window carries both the rows and deadMs - identity unchecked.')
        print('    Everything below is UNVERIFIED against the pooled number.')
    elif bad:
        print('  ! %d window(s) where rows do not sum to awakeMs - deadMs:' % len(bad))
        for wn, got, pooled in bad[:5]:
            print('      w%-4s rows %.4f ms  vs pooled %.4f ms' % (wn, got, pooled))
        print('\nGATE FAILED - the disaggregation disagrees with the field it came from.')
        return 1
    else:
        print('  all reconcile within %.0f%% - rows and pooled field agree' % (RECONCILE_TOL * 100))

    # Rows grouped per bot, ordered by window, then split into spans.
    by_bot = collections.defaultdict(list)
    for (path, wn), rs in rows.items():
        for r in rs:
            if r.get('id'):
                by_bot[(path, r['id'])].append((wn, r))
    all_spans = []
    disagreements = 0
    no_start = 0
    for key, wrs in by_bot.items():
        wrs.sort(key=lambda t: t[0])
        rs = [r for _, r in wrs]
        no_start += sum(1 for r in rs if r.get('spanS') is None)
        sps, dis = spans(rs)
        disagreements += dis
        for sp in sps:
            all_spans.append((key, sp))

    print()
    print('=' * 78)
    print('2. ATTRITION - how much of the age range rests on how few bots')
    print('=' * 78)
    print('  bots            %d' % len(by_bot))
    print('  spans           %d   (a re-wake starts a new one)' % len(all_spans))
    if no_start:
        print('  ! %d row(s) carry no spanS - split fell back to the age rule for those,' % no_start)
        print('    which cannot see a re-wake early in a window. Build predates ebae1e6.')
    if disagreements:
        print('  ! spanS and the age rule disagree on %d boundaries.' % disagreements)
        print('    spanS wins - it is an identity, not an inference - but a disagreement')
        print('    means one rule is wrong and the count is worth carrying to whoever')
        print('    owns the emitter. Expected shape: a re-wake early in a long window,')
        print('    invisible to the age rule because awakeS rose across the reset.')
    multi = [sp for _, sp in all_spans if len(sp) >= MIN_ROWS_PER_SPAN]
    print('  spans >= %d rows %d' % (MIN_ROWS_PER_SPAN, len(multi)))
    if all_spans:
        ages = sorted(max(r['awakeS'] for r in sp) for _, sp in all_spans)
        print()
        print('  %-12s %8s %10s' % ('age reached', 'spans', 'share'))
        for edge in (30, 60, 150, 300, 600, 1200):
            k = sum(1 for a in ages if a >= edge)
            print('  >= %-9d %8d %9.1f%%' % (edge, k, 100.0 * k / len(ages)))
        print()
        print('  A slope drawn across the whole range rests on the bottom row of this')
        print('  table. If expensive bots leave earlier, the old-age rows are the cheap')
        print('  survivors and the slope is biased DOWNWARD by selection.')

    print()
    print('=' * 78)
    print('3. WITHIN-BOT SLOPE   ms per call, per second of awake age')
    print('=' * 78)
    slopes = []
    for _key, sp in all_spans:
        usable = [r for r in sp if (r.get('n') or 0) >= MIN_CALLS]
        if len(usable) < MIN_ROWS_PER_SPAN:
            continue
        xs = [float(r['awakeS']) for r in usable]
        ys = [float(r['ms']) / r['n'] for r in usable]
        s = ols_slope(xs, ys)
        if s is not None:
            slopes.append(s)
    print('  spans with >= %d rows of >= %d calls   %d' % (MIN_ROWS_PER_SPAN, MIN_CALLS, len(slopes)))
    if len(slopes) < MIN_SPANS:
        print('  ! fewer than %d usable spans - no slope reported. Not a null result:' % MIN_SPANS)
        print('    the run is too short or the bots too short-lived to carry the test.')
        print('\nGATE FAILED - underpowered, and reporting a median here would invite')
        print('a conclusion the data cannot support.')
        return 1

    pos = sum(1 for s in slopes if s > 0)
    neg = sum(1 for s in slopes if s < 0)
    n = pos + neg
    print('  median slope    %+.6f ms/call per second awake' % st.median(slopes))
    print('  positive %d, negative %d, flat %d' % (pos, neg, len(slopes) - n))

    # Sign test rather than a t-test on the slopes: per-bot slopes are not
    # comparable in magnitude across bots with different call counts and
    # different age ranges, but their SIGN is. Distribution-free, and the
    # design bound is stated beside the achieved result because they
    # routinely disagree and both are true.
    if not n:
        # Every usable span came out exactly flat. That is the strongest null
        # this test can produce and it must not fall out of the bottom of the
        # sign test silently - a section that prints nothing reads as a section
        # that was not reached. Found by a synthetic built with slope 0.
        print('  every span is exactly flat. Not a coin and not an absence:')
        print('  cost does not move with age AT ALL in %d spans, which retires the' % len(slopes))
        print('  hypothesis more firmly than a balanced split would.')
    else:
        z = (pos - n / 2.0) / (0.5 * math.sqrt(n))
        print('  sign test       z = %+.2f over %d signed spans' % (z, n))
        det = 0.5 + 0.98 / math.sqrt(n)
        print('  design bound    this n resolves a sign split of %.0f/%.0f or wider'
              % (det * 100, (1 - det) * 100))
        if abs(z) < 1.96:
            print('  ! the sign split is NOT distinguishable from a coin. Age does not')
            print('    detectably move per-bot cost at this n, and pooled per-bot figures')
            print('    are not impeached by this run.')
        else:
            print('  the split is one-sided beyond chance: per-bot cost DOES move with age.')

    print()
    print('=' * 78)
    print('4. THE REGISTERED PREDICTION, written before the data')
    print('=' * 78)
    print('  read-updatemanual.py prints two routes to a per-frame number and on')
    print('  raid 1.5 they disagreed by 74% - contrast x MEDIAN awake count against a')
    print('  pooled figure. That was attributed to a skewed awake COUNT across windows.')
    print()
    print('  IF the sign test above is one-sided, the count is not the whole story and')
    print('  the same divergence is partly an AGE distribution effect. IF the sign test')
    print('  is a coin, the divergence is count skew alone and age is not a live')
    print('  confound in any pooled per-bot number we have quoted.')
    print()
    print('  These are different worlds and this run picks one. Neither outcome is a')
    print('  failure of the field: a flat slope retires a hypothesis, which is the')
    print('  cheaper result and the one nobody writes up.')

    print()
    print('=' * 78)
    print('5. WHAT THIS CANNOT ANSWER')
    print('=' * 78)
    print('  A slope is not a mechanism. A bot awake longer is also a bot that has been')
    print('  near her longer, has a longer path history and more accumulated state - so')
    print('  age here is a proxy for several things at once and this cannot separate')
    print('  them. It answers "does cost move with age", never "because of age".')
    print('  It is also silent on goal 2: these are window sums and counts, no maximum,')
    print('  so a flat mean is consistent with one 40 ms call.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
