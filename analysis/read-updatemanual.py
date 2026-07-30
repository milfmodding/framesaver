#!/usr/bin/env python3
"""Read the `updateManual` field: what an awake bot costs in BotOwner.UpdateManual.

WRITTEN BEFORE THE FIELD HAS EVER PRODUCED DATA. The field shipped in 4a51dd5
and the first raid to carry it has not been run. Every choice here -- what gates
the comparison, what the dilution correction is, what the number may be called
-- was made without knowing the answer, for the same reason as read-marathon.py
and read-aitotal-aba.py.

WHAT THIS MEASURES, AND THE SENTENCE A WRITE-UP WILL GET WRONG:

    awakeMs/awakeCalls - pausedMs/pausedCalls IS A CONTRAST, NOT A PRICE.

The field's own docstring calls it "the marginal cost of one awake bot, measured
on the same bots in the same frames". THE BUCKETS HOLD DISJOINT BOTS. A bot is
awake or paused, never both, and it is awake because it is near her. That makes
this a between-group difference with non-random assignment, biased in two
directions at once:

  * awake bots are near, engaged, questing -- part of their per-tick cost is WHY
    they are awake rather than THAT the 22 subsystem ticks exist. Inflates.
  * `awake` here means NOT PAUSED, not TICKING. A NonActive-but-unpaused bot
    runs the vanilla body, fails the `BotState == Active` guard, does nothing,
    and is still counted as an awake call at ~0 ms. Deflates.

Neither is bounded, so the sign of the net bias is unknown and section 4 prints
the contrast without a confidence claim attached to it as a cost.

Section 3 measures the second bias, which needs no new field: `awakeCalls/frames`
against `bots.awake`. The excess calls cost ~0, so dividing the window total by
the census-implied call count instead of the actual one recovers a per-TICKING-bot
mean. Both are printed. The first bias needs awake-population distance buckets,
which do not exist yet -- awake-and-far is the control group this contrast lacks.

WHAT IT CANNOT ANSWER. Sums and counts, no maximum. A window mean stays flat
while one call spikes to 40 ms, so `updateManual` IS SILENT ON GOAL 2. Nobody
should reach for this field when the subject is stutter.

Usage:  python read-updatemanual.py <log.ndjson> [more.ndjson ...]

Exit 0 when the field is readable, 1 when a gate fails, 2 on bad input.
"""

import json
import math
import statistics as st
import sys

STEADY_S = 120.0        # same warm-up discard as the marathon reader
MIN_WINDOWS = 3         # below this the spread has no meaning to report
# Dilution tolerance on `awakeCalls/frames` vs `bots.awake`. Not a tuned number:
# `bots.awake` is an instantaneous census at window close and the call rate is a
# window mean, so they cannot be expected to match exactly even with no idle
# bots at all. 15% is the band inside which the two disagree for that reason
# alone; outside it, the excess is idle awake calls and section 3 corrects.
DILUTION_TOL = 0.15


def load(paths):
    """Sample windows only, warm-up discarded, tagged with their source file."""
    rows = []
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
                if obj.get('type') != 'sample':
                    continue
                obj['_log'] = path
                rows.append(obj)
    return rows


def eligible(rows):
    """In-raid, past warm-up, carrying both the field and its denominators.

    `final` is excluded explicitly. It was excluded before only as a side effect
    of `bots.total > 0`, which nobody had noticed was doing the work.
    """
    out = []
    for w in rows:
        if w.get('final'):
            continue
        if (w.get('raidElapsed') or 0.0) < STEADY_S:
            continue
        if w.get('updateManual') is None:
            continue
        if not w.get('frames'):
            continue
        if (w.get('bots') or {}).get('awake') is None:
            continue
        out.append(w)
    return out


def um(w):
    return w['updateManual']


def stratum(w):
    """The two config flags that decide which bots land in which bucket.

    `deactivateSleeping` routes a NonActive paused bot through the pump patch
    instead of the vanilla body, so it changes what `pausedMs` is measuring.
    `standBy` decides whether the paused bucket is populated at all.
    """
    cfg = w.get('cfg') or {}
    return (bool(cfg.get('standBy')), bool(cfg.get('deactivateSleeping')))


def mean_or_none(total, calls):
    return (total / calls) if calls else None


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    rows = load(argv[1:])
    if not rows:
        print('no sample windows found')
        return 2

    wins = eligible(rows)
    print('=' * 78)
    print('1. FIELD PRESENT AND DENOMINATORS INTACT')
    print('=' * 78)
    print('  sample windows           %d' % len(rows))
    print('  carrying updateManual    %d' % sum(1 for w in rows if w.get('updateManual') is not None))
    print('  eligible (past %.0fs)    %d' % (STEADY_S, len(wins)))
    if not wins:
        print('\nGATE FAILED - no eligible window carries updateManual.')
        return 1

    # A zero here is EXPECTED and proves nothing. The counter watches our prefix
    # being skipped by another prefix returning false, and HarmonyPriority.First
    # exists so that cannot happen. The interaction that does fire every frame -
    # the pump patch returning false AFTER we stamped - is invisible to it. Read
    # a non-zero as real news; do not read zero as confirmation.
    unstamped = sum(um(w).get('unstampedCalls') or 0 for w in wins)
    print('  unstampedCalls (total)   %d%s' % (unstamped, '' if unstamped else '   <- expected; not evidence'))
    if unstamped:
        print('    ! our prefix was skipped on %d calls - those samples were dropped, not' % unstamped)
        print('      mis-timed, but HarmonyPriority.First is no longer holding.')

    zero_calls = [w for w in wins if not um(w).get('awakeCalls')]
    if zero_calls:
        print('  windows with awakeCalls == 0   %d   <- no data, distinct from zero cost' % len(zero_calls))

    print()
    print('=' * 78)
    print('2. STRATIFICATION - the comparison is gated, not pooled')
    print('=' * 78)
    groups = {}
    for w in wins:
        groups.setdefault(stratum(w), []).append(w)
    for (sb, ds), ws in sorted(groups.items()):
        print('  standBy=%-5s deactivateSleeping=%-5s  %d windows' % (sb, ds, len(ws)))
    if len(groups) > 1:
        print()
        print('  Reported per stratum below and NEVER differenced across them.')
        print('  deactivateSleeping changes which paused path a bot takes, so it changes')
        print('  what pausedMs measures; standBy decides whether paused is populated at all.')

    failed = []
    for (sb, ds), all_ws in sorted(groups.items()):
        # A window with either bucket empty is dropped from the POOLED sums too,
        # not just from the per-window spread. Keeping it contributes awake ms
        # with no paused counterpart, which biases the contrast upward by exactly
        # the awake total of the dropped window. Found by a synthetic that put
        # one such window in the stratum: it changed the pooled mean and printed
        # no warning, because the pooled paused count was non-zero from the
        # OTHER windows.
        ws = [w for w in all_ws
              if (um(w).get('awakeCalls') or 0) and (um(w).get('pausedCalls') or 0)]
        dropped = len(all_ws) - len(ws)

        print()
        print('=' * 78)
        print('3. DILUTION CHECK   standBy=%s deactivateSleeping=%s   (%d windows)' % (sb, ds, len(ws)))
        print('=' * 78)
        if dropped:
            print('  %d window(s) dropped: one bucket empty. Excluded from the pooled sums as' % dropped)
            print('    well as the spread - an unpaired awake total inflates the contrast.')
        if not ws:
            print('  ! no window in this stratum has both buckets populated - no contrast.')
            failed.append('standBy=%s deactivateSleeping=%s has no two-bucket window' % (sb, ds))
            continue
        ratios = []
        for w in ws:
            rate = (um(w).get('awakeCalls') or 0) / float(w['frames'])
            census = (w.get('bots') or {}).get('awake') or 0
            ratio = (rate / census) if census else float('nan')
            if not math.isnan(ratio):
                ratios.append(ratio)
        med = None
        if not ratios:
            print('  no window has bots.awake > 0 - dilution not assessable')
        else:
            med = st.median(ratios)
            print('  median awakeCalls/frames / bots.awake   %.3f' % med)
            if med > 1.0 + DILUTION_TOL:
                print('  ! %.0f%% more awake CALLS than awake BOTS. The excess is NonActive-but-unpaused'
                      % ((med - 1.0) * 100.0))
                print('    bots running the vanilla body to a failed guard at ~0 ms. Corrected mean below.')
            elif med < 1.0 - DILUTION_TOL:
                print('  ! fewer awake calls than awake bots - UpdateManual is not being called for')
                print('    every awake bot every frame, so the per-call mean is not a per-bot cost.')
            else:
                print('  within +/-%.0f%% of the census - no material dilution' % (DILUTION_TOL * 100.0))

        print()
        print('=' * 78)
        print('4. THE CONTRAST   standBy=%s deactivateSleeping=%s' % (sb, ds))
        print('=' * 78)
        aw_ms = sum(float(um(w).get('awakeMs') or 0.0) for w in ws)
        aw_n = sum(um(w).get('awakeCalls') or 0 for w in ws)
        pa_ms = sum(float(um(w).get('pausedMs') or 0.0) for w in ws)
        pa_n = sum(um(w).get('pausedCalls') or 0 for w in ws)
        aw = mean_or_none(aw_ms, aw_n)
        pa = mean_or_none(pa_ms, pa_n)
        print('  awake    %10.4f ms over %8d calls   mean %s' % (aw_ms, aw_n, '%.5f' % aw if aw else 'n/a'))
        print('  paused   %10.4f ms over %8d calls   mean %s' % (pa_ms, pa_n, '%.5f' % pa if pa else 'n/a'))
        print('  contrast (awake - paused)   %.5f ms/call' % (aw - pa))

        # The correction section 3 promises. The excess calls cost ~0, so
        # dividing by the census-implied call count rather than the actual one
        # recovers a per-TICKING-bot mean. Printed only when the dilution is
        # outside the census band, because below that the two divisors agree and
        # a second number would just look like a second measurement.
        best = aw - pa
        if med is not None and med > 1.0 + DILUTION_TOL:
            census_calls = sum(w['frames'] * ((w.get('bots') or {}).get('awake') or 0) for w in ws)
            aw_corr = mean_or_none(aw_ms, census_calls)
            if aw_corr is not None:
                best = aw_corr - pa
                print('  corrected for dilution     %.5f ms/call awake, contrast %.5f'
                      % (aw_corr, best))
                print('    (awakeMs / (frames x bots.awake) - the divisor the census implies)')

        # Per-window contrasts, so the spread is between windows rather than
        # between calls. A call-level sd would be dominated by which bots were
        # in the window, which is the confound, not the noise.
        per = []
        for w in ws:
            a = mean_or_none(float(um(w).get('awakeMs') or 0.0), um(w).get('awakeCalls') or 0)
            p = mean_or_none(float(um(w).get('pausedMs') or 0.0), um(w).get('pausedCalls') or 0)
            if a is not None and p is not None:
                per.append(a - p)
        if len(per) >= MIN_WINDOWS:
            sd = st.stdev(per)
            print('  per-window contrast   median %.5f   sd %.5f   n %d' % (st.median(per), sd, len(per)))
            print('  detectable at 0.05/80%%, this n:   %.5f ms/call' % (2.8 * sd / math.sqrt(len(per))))
        else:
            print('  fewer than %d windows with both buckets - no spread reported' % MIN_WINDOWS)

        # Frame-level restatement, which is the only form anyone will actually
        # want, and the form most likely to be quoted past its warrant.
        # The corrected contrast when there was one, because this is the line
        # that gets quoted and the uncorrected version understates it.
        med_awake = st.median([(w.get('bots') or {}).get('awake') or 0 for w in ws])
        print('  x median %d awake bots  =  %.4f ms/frame' % (med_awake, best * med_awake))
        print()
        print('  THIS IS A CONTRAST, NOT A PRICE. Disjoint buckets, non-random assignment,')
        print('  biased both ways and neither bound. Quote it as an order of magnitude.')

    print()
    print('=' * 78)
    print('5. WHAT THIS FIELD CANNOT ANSWER')
    print('=' * 78)
    print('  No maximum is emitted, by design. A flat window mean is consistent with one')
    print('  40 ms call, so updateManual is SILENT ON GOAL 2 and cannot support or refute')
    print('  any claim about stutter. It answers "what does an awake bot cost on average".')
    print('  Cost-of-awake still needs awake-population distance buckets for its control')
    print('  group, and per-frame aiMs to separate removal from relocation.')

    if failed:
        print()
        print('GATE FAILED - the contrast above is NOT quotable:')
        for f in failed:
            print('  ! %s' % f)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
