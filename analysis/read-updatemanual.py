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

A THIRD DEFLATOR, AND THIS ONE SUBTRACTS EXACTLY. Corpses tick UpdateManual and
read as awake: `BotsClass.UpdateByUnity` has no liveness test and the guard is
inside the method, past the postfix. `deadCalls`/`deadMs` (26fb3d6, Beta) are a
SUBSET of `awakeCalls`/`awakeMs`, not a fourth bucket, so live-awake is a
subtraction rather than a model -- and it replaces the estimate for the part of
the dilution it covers. Corpses sit in `bots.awake` as well, so the section 3
ratio had them above AND below the line, partly cancelling and UNDERSTATING the
idle dilution among live bots. Both sides are corpse-free now.

Written against a field that had not shipped when this file was, revised when
`deadMs` landed and still before the first raid carrying either. Absent is not
zero: a log predating the field says so and falls back, rather than reporting a
corpse-free number it cannot support.

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


def has_dead(w):
    """Whether this window's build emitted the corpse subset at all.

    `deadCalls` absent means the field predates the build; `deadCalls` at 0
    means it looked and found no corpses. Treating the first as the second
    would report a corpse-free contrast off a log that never measured one.
    """
    return um(w).get('deadCalls') is not None


def census_corpses(w):
    """(corpses inside bots.awake, route) for this window.

    `bots.deadAwake` (cb47968) is the census counting corpses in its own awake
    branch, a subset of `bots.awake` exactly as deadCalls is of awakeCalls.
    Before it existed the only route was deadCalls/frames -- the window-MEAN
    corpse count implied by the call rate, held against an INSTANTANEOUS census
    taken at window close. They answer the same question two ways and neither
    is a substitute for the other's provenance, so the direct one leads and the
    derived one both backs it up and checks it.

    None means no route at all: the build predates both, and the caller must
    not silently treat that as zero corpses.
    """
    bots = w.get('bots') or {}
    if bots.get('deadAwake') is not None:
        return float(bots['deadAwake']), 'census'
    if has_dead(w) and w.get('frames'):
        return (um(w).get('deadCalls') or 0) / float(w['frames']), 'derived'
    return None, 'none'


def live(w, use_dead):
    """(ms, calls) for awake bots that are actually alive.

    deadCalls/deadMs are a SUBSET of awakeCalls/awakeMs - the postfix adds a
    corpse to the awake bucket and then again to the dead one - so this is a
    subtraction, not a fourth bucket.

    `use_dead` is the STRATUM's verdict, not this window's, and the caller must
    pass it rather than let this function check has_dead() itself. A stratum
    spanning both builds would otherwise subtract on the windows that carry the
    field and not on the ones that do not, pooling corrected totals with
    uncorrected ones against a census adjusted for neither. Found by a synthetic
    of mixed windows: it reported a ratio of 0.833 and a contrast 20% high,
    while section 1 printed a promise to treat mixed as absent that nothing
    implemented.
    """
    ms = float(um(w).get('awakeMs') or 0.0)
    calls = um(w).get('awakeCalls') or 0
    if use_dead and has_dead(w):
        ms -= float(um(w).get('deadMs') or 0.0)
        calls -= um(w).get('deadCalls') or 0
    return max(ms, 0.0), max(calls, 0)


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

    # Absent, mixed and present are three outcomes, not two. A run that pools
    # corpse-corrected windows with uncorrected ones produces a contrast that is
    # neither, and the per-window subtraction hides it - so mixed is
    # reported and then treated as absent for the whole stratum rather
    # than per window.
    n_dead = sum(1 for w in wins if has_dead(w))
    total_ac = sum(um(w).get('awakeCalls') or 0 for w in wins)
    if n_dead == 0:
        print('  deadCalls                ABSENT - build predates it. Corpses stay in the')
        print('                           awake bucket below and cannot be subtracted.')
    elif n_dead < len(wins):
        print('  deadCalls                MIXED - %d of %d windows carry it' % (n_dead, len(wins)))
        print('                           Any stratum spanning both is treated as absent.')
    else:
        total_dc = sum(um(w).get('deadCalls') or 0 for w in wins)
        share = (100.0 * total_dc / total_ac) if total_ac else 0.0
        print('  deadCalls (subset of awake)  %d of %d calls   %.2f%% of the awake bucket'
              % (total_dc, total_ac, share))
        if total_dc == 0:
            print('    zero corpses measured - a real finding here, not a missing field,')
            print('    because the field is present in every window.')

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
        # Corpse-free on BOTH sides or neither. Corpses tick once a frame
        # and the census counts them awake as well, so leaving them above
        # and below the line cancels part of the very dilution this ratio
        # exists to measure. deadCalls/frames is the mean corpse count per
        # frame, which is what comes off the census.
        dead_known = all(has_dead(w) for w in ws)
        census_known = all(census_corpses(w)[0] is not None for w in ws)

        # Where both routes exist they are two instruments for one quantity, so
        # print the gap rather than picking the direct one and moving on. A
        # window-mean call rate and an instantaneous census cannot be expected
        # to match exactly; a LARGE gap means corpses are entering or leaving
        # the roster fast enough that neither describes the window.
        both = [(float((w.get('bots') or {}).get('deadAwake')),
                 (um(w).get('deadCalls') or 0) / float(w['frames']))
                for w in ws
                if (w.get('bots') or {}).get('deadAwake') is not None
                and has_dead(w) and w.get('frames')]
        if both:
            gaps = [abs(c - d) for c, d in both]
            scale = st.median([max(c, d) for c, d in both])
            print('  corpse count, two routes: census median %.2f, call-rate median %.2f'
                  % (st.median([c for c, _ in both]), st.median([d for _, d in both])))
            if scale > 0 and st.median(gaps) / scale > DILUTION_TOL:
                print('  ! the two corpse routes differ by more than %.0f%% - the roster is'
                      % (DILUTION_TOL * 100.0))
                print('    turning over inside the window and neither count describes it.')

        ratios = []
        for w in ws:
            l_ms, l_calls = live(w, dead_known)
            rate = l_calls / float(w['frames'])
            census = float((w.get('bots') or {}).get('awake') or 0)
            corpses, _route = census_corpses(w)
            if census_known and corpses is not None:
                census -= corpses
            ratio = (rate / census) if census > 0 else float('nan')
            if not math.isnan(ratio):
                ratios.append(ratio)
        med = None
        if not ratios:
            print('  no window has a positive live awake census - dilution not assessable')
        else:
            med = st.median(ratios)
            print('  median liveAwakeCalls/frames / live bots.awake   %.3f%s'
                  % (med, '' if dead_known else '   (corpses NOT removed)'))
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
        aw_ms, aw_n = 0.0, 0
        for w in ws:
            l_ms, l_calls = live(w, dead_known)
            aw_ms += l_ms
            aw_n += l_calls
        pa_ms = sum(float(um(w).get('pausedMs') or 0.0) for w in ws)
        pa_n = sum(um(w).get('pausedCalls') or 0 for w in ws)
        aw = mean_or_none(aw_ms, aw_n)
        pa = mean_or_none(pa_ms, pa_n)
        label = 'awake (live)' if dead_known else 'awake (corpses in)'
        print('  %-18s %10.4f ms over %8d calls   mean %s'
              % (label, aw_ms, aw_n, '%.5f' % aw if aw else 'n/a'))
        print('  %-18s %10.4f ms over %8d calls   mean %s'
              % ('paused', pa_ms, pa_n, '%.5f' % pa if pa else 'n/a'))

        # Newly reachable once corpses are subtracted: a stratum whose every
        # awake call was a corpse leaves no live bucket at all. The window
        # filter above only guarantees awakeCalls > 0, which corpses satisfy.
        if aw is None or pa is None:
            print('  ! no live awake calls remain after subtracting corpses - no contrast.')
            failed.append('standBy=%s deactivateSleeping=%s is all-corpse after subtraction'
                          % (sb, ds))
            continue

        print('  contrast (awake - paused)   %.5f ms/call' % (aw - pa))
        if dead_known:
            raw_ms = sum(float(um(w).get('awakeMs') or 0.0) for w in ws)
            raw_n = sum(um(w).get('awakeCalls') or 0 for w in ws)
            raw = mean_or_none(raw_ms, raw_n)
            if raw:
                print('    corpse subtraction moved the awake mean %+.1f%%  (%.5f -> %.5f)'
                      % (100.0 * (aw - raw) / raw, raw, aw))

        # The correction section 3 promises. The excess calls cost ~0, so
        # dividing by the census-implied call count rather than the actual one
        # recovers a per-TICKING-bot mean. Printed only when the dilution is
        # outside the census band, because below that the two divisors agree and
        # a second number would just look like a second measurement.
        best = aw - pa
        if med is not None and med > 1.0 + DILUTION_TOL:
            census_calls = 0.0
            for w in ws:
                c = float((w.get('bots') or {}).get('awake') or 0)
                corpses, _route = census_corpses(w)
                if census_known and corpses is not None:
                    c -= corpses
                census_calls += w['frames'] * max(c, 0.0)
            aw_corr = mean_or_none(aw_ms, census_calls)
            if aw_corr is not None:
                best = aw_corr - pa
                print('  corrected for dilution     %.5f ms/call awake, contrast %.5f'
                      % (aw_corr, best))
                print('    (awakeMs / (frames x bots.awake) - the divisor the census implies)')

        # Per-window contrasts, so the spread is between windows rather than
        # between calls. A call-level sd would be dominated by which bots were
        # in the window, which is the confound, not the noise.
        #
        # Corpse-subtracted like the pooled figure above. It was not, at first,
        # and the synthetic caught it: the pooled contrast read 0.01981 while
        # the per-window median under it read 0.01318 off raw awake means. Two
        # numbers on adjacent lines, differing by 50%, both labelled contrast.
        per = []
        for w in ws:
            l_ms, l_calls = live(w, dead_known)
            a = mean_or_none(l_ms, l_calls)
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
        live_census = []
        for w in ws:
            c = float((w.get('bots') or {}).get('awake') or 0)
            corpses, _route = census_corpses(w)
            if census_known and corpses is not None:
                c -= corpses
            live_census.append(max(c, 0.0))
        med_awake = st.median(live_census)
        print('  x median %.1f %s awake bots  =  %.4f ms/frame'
              % (med_awake, 'live' if census_known else 'census (corpses in)',
                 best * med_awake))

        # Second route to a frame-level number, needing no bot count at all.
        # It answers a DIFFERENT question from the line above - what awake bots
        # cost, not what stand-by buys - and is exact where that one is a
        # product of two estimates. Printed together because when they are
        # wildly inconsistent it is the bot count that is wrong, and there is
        # otherwise nothing to catch that.
        tot_frames = sum(w['frames'] for w in ws)
        if tot_frames:
            direct = aw_ms / tot_frames
            print('  direct: live awake ms / frame  =  %.4f ms/frame   (no bot count;'
                  % direct)
            print('    this is what awake bots COST, not what stand-by BUYS)')

            # Two ms/frame numbers on adjacent lines will get reconciled by
            # whoever reads them, so say what a gap MEANS before someone
            # invents a reason. The line above pools every window; the one
            # before it multiplies by a MEDIAN. They diverge when the awake
            # population is skewed across windows - a few crowded windows
            # carrying most of the calls - which is a fact about the raid,
            # not a defect in either number. It is also the only signal here
            # that a single median bot count does not describe the run.
            ref = best * med_awake
            if ref and direct and abs(direct - ref) / max(abs(ref), 1e-9) > 0.25:
                mean_awake = sum(live_census) / len(live_census)
                print('  ! the two disagree by %.0f%%. Not an error: the first uses the MEDIAN'
                      % (100.0 * abs(direct - ref) / abs(ref)))
                print('    awake count (%.1f) and the second pools all frames; mean awake is'
                      % med_awake)
                print('    %.1f. A skewed awake population across windows is the cause, and'
                      % mean_awake)
                print('    no single per-frame figure describes this run. Quote neither alone.')
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
