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

import collections
import json
import math
import os
import statistics as st
import sys

import steady

STEADY_S = steady.WARMUP_S   # the shared definition; see analysis/steady.py
MIN_WINDOWS = 3         # below this the spread has no meaning to report
# Dilution tolerance on `awakeCalls/frames` vs `bots.awake`. Not a tuned number:
# `bots.awake` is an instantaneous census at window close and the call rate is a
# window mean, so they cannot be expected to match exactly even with no idle
# bots at all. 15% is the band inside which the two disagree for that reason
# alone; outside it, the excess is idle awake calls and section 3 corrects.
DILUTION_TOL = 0.15


def load(paths):
    """Sample windows, tagged with their source file AND that log's header arm.

    The header's `config.forceAllRoles` is present in every log we hold - 24 of
    24 - so a log predating the per-window `cfg` key can still say which arm the
    LEG ran. Discarding it and printing UNKNOWN throws away a field that exists,
    which is what this reader did until Alpha caught it. `_legFar` carries it so
    stratum() can fall back rather than give up.
    """
    rows = []
    for path in paths:
        try:
            fh = open(path, 'r', encoding='utf-8', errors='replace')
        except OSError as exc:
            print('cannot open %s: %s' % (path, exc))
            sys.exit(2)
        leg_far = None
        leg_win = None
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get('type') == 'header':
                    leg_far = ((obj.get('config') or {}).get('forceAllRoles'))
                    # `windowSec` is absent on half the corpus, so the header is
                    # the only resolution for those rows. Stamped here because
                    # this loader drops headers and steady.window_length() would
                    # otherwise have to refuse them.
                    leg_win = obj.get('windowSeconds')
                    continue
                if obj.get('type') != 'sample':
                    continue
                obj['_log'] = path
                obj['_legFar'] = leg_far
                obj['_windowSeconds'] = leg_win
                rows.append(obj)
    return rows


def eligible(rows):
    """Steady-state per analysis/steady.py, carrying the field and its denominators.

    The population test is IMPORTED rather than restated. This function used to
    spell it out and got it wrong in a way nothing could see: it never tested
    `state == 'raid'`, and was saved only because no non-raid sample in this
    corpus carries `raidElapsed >= 120` -- zero of 520. Excluded as a side
    effect, which is the defect the docstring one line above already named about
    `final`. Alpha and I then quoted the same remainder as 0.679 and 0.726 ms
    because our definitions differed by clauses neither of us had written down.

    `require_population` stays FALSE here. bots.total > 0 is right for
    read-marathon's per-bot quantities and wrong for this file's per-frame ones,
    where a window with no bots is a legitimate observation rather than a gap.
    """
    # drop_teardown=TRUE here. Every quantity this file reports divides by a
    # bot count, and a teardown window's census is dead or stale, so the
    # denominator is wrong rather than noisy.
    #
    # A per-FRAME reader should leave it False: the frame data in those windows
    # is good, 2772-7019 frames, and excluding them would throw away real
    # observations. Same shape as require_population - correct for one quantity
    # and wrong for another, so steady.py offers it rather than deciding it.
    kept, dropped = steady.partition(rows, drop_teardown=True, by_start=True)
    out = []
    for w in kept:
        if w.get('updateManual') is None:
            continue
        if not w.get('frames'):
            continue
        if (w.get('bots') or {}).get('awake') is None:
            continue
        out.append(w)
    return out, dropped


def um(w):
    return w['updateManual']


def leg_key(w):
    """The raid a window belongs to: (log, raid counter, map).

    NOT the log. Six of the 24 logs hold more than one map and three revisit a
    map, so a file is a SESSION and can contain several raids. Keying a
    composition report on the filename merges them.

    The rule is read-marathon.py's `legs()` and is referenced rather than
    restated: it keys on the raid counter precisely because the marathon
    revisits Lighthouse and those two visits must not merge - that pair is its
    control. A second statement of a rule is a second place for it to drift.

    I learned this by getting it wrong in public. I told Beta the zero-asleep
    leg was on factory4_day and not Streets, from a query that took the first
    `map` in each file and labelled the whole file with it. That session is two
    raids: raid 1 on factory with 4 zero-asleep windows, raid 2 on Streets with
    15. Beta's original attribution was closer than my correction, and my
    "no Streets leg has it" was computed with the same broken key - internally
    consistent and wrong.
    """
    return (w.get('_log', '?'), w.get('raid'), w.get('map'))


def leg_name(key):
    log, raid, mp = key
    return '%s raid %s %s' % (os.path.basename(log)[-24:], raid, mp)


def stratum(w):
    """The config flags that decide which bots land in which bucket.

    `deactivateSleeping` routes a NonActive paused bot through the pump patch
    instead of the vanilla body, so it changes what `pausedMs` is measuring.
    `standBy` decides whether the paused bucket is populated at all.

    `forceAllRoles` decides which ROLES may sleep, so it moves bots between the
    two buckets wholesale -- raid 1.5 ran it on and slept 26 of 27. It is the
    largest composition lever we have and it was missing from this tuple until
    2026-07-30.

    TWO SOURCES, DIFFERENT GRANULARITIES, AND THE FALLBACK IS NOT A CONCESSION.
    The per-window `cfg` key arrived in 1806101. The HEADER has carried
    `config.forceAllRoles` all along -- 24 of 24 logs, 23 False and raid 1.5
    True -- so a pre-1806101 leg can still say which arm it ran. I first had
    this print UNKNOWN for those legs, which discarded a field that exists;
    Alpha caught it, and it had already cost a gate verdict, because the
    Lighthouse figure that read as a passing baseline was a pooling of a failing
    default arm with a passing treatment one.

    So: window value first, leg value second, `None` only when neither exists.
    `None` still means UNKNOWN rather than False, because a future build
    dropping the key must never read as the default arm -- but UNKNOWN is now
    spent only on logs that genuinely cannot answer.

    "Absent" and "absent at the granularity I need" diverge exactly when a
    cheaper route exists, and here the cheaper route was free and a day old.
    """
    cfg = w.get('cfg') or {}
    far = cfg.get('forceAllRoles')
    if far is None:
        far = w.get('_legFar')
    return (bool(cfg.get('standBy')), bool(cfg.get('deactivateSleeping')), far)


def far_source(w):
    """Where this window's forceAllRoles came from: window, leg, or nowhere.

    A LEG value is the header's, written once at session start. It labels the
    whole leg correctly and cannot see a mid-session flip - which is exactly
    what the per-window key was added to catch. So it is good enough to gate a
    whole-leg contrast and NOT good enough to gate a within-leg one, and the
    difference has to be visible rather than assumed.
    """
    if (w.get('cfg') or {}).get('forceAllRoles') is not None:
        return 'window'
    if w.get('_legFar') is not None:
        return 'leg'
    return 'none'


def stratum_label(key):
    """Human-readable stratum, with UNKNOWN distinguished from False.

    `forceAllRoles` is None on any log predating its arrival in `cfg`. That is
    not the same as off, and printing it as `False` would assert the arm of a
    run nobody recorded - the absent-is-not-zero rule applied to a label.
    """
    sb, ds, far = key
    return ('standBy=%-5s deactivateSleeping=%-5s forceAllRoles=%s'
            % (sb, ds, 'UNKNOWN' if far is None else far))


def stratum_sort(key):
    """Sortable form: None cannot be ordered against bool in Python 3."""
    sb, ds, far = key
    return (bool(sb), bool(ds), -1 if far is None else int(bool(far)))


# Mods that clear CanDoStandBy on every bot, per ModCompat.ClearsStandByFlag.
# Only with one of these present does `forceAllRoles` become REVOCABLE.
CLEARING_MODS = ('QuestingBots', 'ORBIT')


def force_all_roles_arm_took_effect(groups):
    """Did flipping `forceAllRoles` actually move the population? OBSERVED.

    Returns (verdict, detail) where verdict is True (the arm moved bots), False
    (it did not - the flag changed and the population did not), or None (no
    observed counterpart, so the question is unanswerable from this input).

    THIS REPLACED A MOD-LIST INFERENCE, AND THE REPLACEMENT IS THE POINT. The
    first version concluded "latched" from the ABSENCE of QuestingBots or ORBIT,
    on the reasoning that only a clearing mod makes the flag revocable. Beta
    then found that QuestingBots clears `CanDoStandBy` once per bot at
    activation rather than continuously, so the flag is one-way WITH a clearing
    mod as well as without - which would have made the old check go silent on
    raid 2 precisely when the latch was real.

    I cannot verify that frequency here: QuestingBots is not installed on this
    machine, so Beta's premise is unverifiable from my side and the conclusion
    is only as good as it. What I can verify is our half - TryReclaimStandBy is
    gated on `!CanDoStandBy` at BotStandByUpdatePatch:125, so once the grant is
    in place nothing we run revisits it.

    So stop inferring from which mod is installed and read the outcome instead.
    `bots.standByBlocked` counts the bots the pump actually refused. If the flag
    varies across windows and that count does not follow it, the arm did not
    take effect - true regardless of which mods are present, and it does not
    depend on anyone's reading of a third party's source.
    """
    per_arm = {}
    for key, ws in groups.items():
        far = key[2]
        if far is None:
            continue
        vals = [(w.get('bots') or {}).get('standByBlocked') for w in ws]
        vals = [v for v in vals if v is not None]
        if vals:
            per_arm.setdefault(bool(far), []).extend(vals)
    if len(per_arm) < 2:
        return None, per_arm
    on = st.median(per_arm[True])
    off = st.median(per_arm[False])
    # `forceAllRoles` on should drive standByBlocked toward zero; off should let
    # it rise to the exempt-role population. Indistinguishable medians mean the
    # flip did not reach the bots.
    return (abs(on - off) > 0.5), {'on': on, 'off': off}


def force_all_roles_is_latched(ws):
    """True when `cfg.forceAllRoles` records a wish the population may not obey.

    `forceAllRoles` has two write paths and only one of them can ever take the
    grant back:

      BotStandByInitPointsPatch   once per bot at activation. GRANTS ONLY.
      TryReclaimStandBy           per check interval, but it returns early
                                  unless ReclaimStandBy AND one of the clearing
                                  mods is present.

    So without QuestingBots or ORBIT the flag is a ONE-WAY LATCH: turning it off
    mid-raid leaves every already-active bot holding its grant, and only bots
    activating afterwards see the change. `cfg.forceAllRoles == False` on such a
    window does NOT mean the bots in it were exempt.

    Detected from `agents.mods` rather than assumed, and it is not hypothetical:
    every log in the corpus as of 2026-07-30 reads ["BigBrain", "SAIN",
    "LootingBots"] -- no clearing mod -- so the flag has been one-way in every
    run we hold. Raid 2 is the QuestingBots protocol, where it becomes genuinely
    revocable, which is why the within-raid arm exists there and nowhere else.

    This is the properties-versus-outcomes rule landing on a field I added
    tonight: `cfg.forceAllRoles` is what was ASKED FOR. `bots.standByBlocked` is
    the observed consequence, and it is the field to check against it.
    """
    mods = set()
    for w in ws:
        for m in (w.get('agents') or {}).get('mods') or []:
            mods.add(m)
    if not mods:
        return None, mods          # no mod list: cannot tell, so do not claim
    return not (mods & set(CLEARING_MODS)), mods


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

    `deadCalls/frames` LEADS. It is the window-MEAN corpse count, integrated
    over every call, and the ratio it feeds is a window-mean call rate -- so it
    is the term that matches its denominator.

    `bots.deadAwake` is a ONE-SHOT roster sample at window close and is the
    cross-check, not the primary. This file briefly had that the other way
    round (c28fcff), on the premise that corpses persist on the roster. Delta
    refuted the premise from the corpus (3926246) and Beta retracted it:
    `bots.total` declines after its peak in 17 of the 18 logs with enough
    windows, and in the two logs carrying deaths the drop tracks the death
    count. Corpses are transient, so an instantaneous sample UNDERSTATES a
    window mean and preferring it was a correction in the wrong direction.

    **A `deadAwake` of 0 is its PREDICTED value and confirms nothing.** For a
    sub-window transient the sample reads nonzero only if it happens to land
    inside a corpse's residency. Treating 0 as "no contamination" would be a
    check that cannot fail -- so a nonzero reading is news and a zero is not
    evidence, in either direction.

    None means no route at all: the build predates both, and the caller must
    not silently treat that as zero corpses.
    """
    bots = w.get('bots') or {}
    if has_dead(w) and w.get('frames'):
        return (um(w).get('deadCalls') or 0) / float(w['frames']), 'derived'
    if bots.get('deadAwake') is not None:
        return float(bots['deadAwake']), 'census'
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


def denominator_calibration(wins):
    """Does `awakeCalls / frames` really mean "mean awake bots this window"?

    THE REASON THIS EXISTS. Alpha needs a per-window AGGREGATE awake count:
    `bots.awake` is one instantaneous sample at the window boundary
    (`CountBots` has a single call site, immediately before the sample line is
    built) while `phases[...].avg` is a mean over every frame, so regressing
    one on the other attenuates the slope by an unknown factor. Their two fits
    disagreed 0.091 within-arm against 0.211 cross-arm, and attenuation
    predicts that direction and roughly that size.

    No new field is needed. `BotsClass.UpdateByUnity` iterates every bot with
    no BotState filter, so UpdateManual runs once per bot per frame and
    `awakeCalls / frames` IS the frame-weighted mean. Better still,
    `UpdateManualTiming.ResetWindow()` and `_phases[i].Reset()` sit in the same
    reset block, so it covers exactly the frames `phases[...].avg` covers.

    BUT THE DENOMINATOR IS NOT SETTLED, AND I WILL NOT GUESS IT. `frames` is
    `_periodSamples`; `n` is `_frame.Count`; nothing guarantees they agree, and
    `Block()` emits avg/min/max with no `n` of its own so the phase means carry
    no denominator at all. Picking one and being wrong scales every per-bot
    coefficient by a constant that would never show up as an error.

    So: solve for it. On a window where NOTHING MOVED -- no transitions, no
    deaths, and the same awake and total counts as the window before it -- the
    awake count was constant across the whole window, so

        awakeCalls / D == bots.awake

    and D is the true frame count. Compare it against both candidates. One
    check settles the denominator, the once-per-frame assumption, and any duty
    cycle at once; a D matching neither means UpdateManual is throttled and the
    aggregate needs a scale factor before anyone quotes a slope from it.

    Corpses are deliberately NOT subtracted here. `deadCalls` is a subset of
    `awakeCalls` and `bots.awake` counts corpses too, so the raw ratio compares
    like with like. Subtracting one side only would manufacture a duty cycle
    out of the corpse count.

    Prints and returns nothing on no candidates, which is the honest outcome
    and not a pass -- a corpus with no quiet window cannot calibrate anything.
    """
    prev = {}
    cands = []
    for w in wins:
        key = leg_key(w)
        before = prev.get(key)
        prev[key] = w
        tr = w.get('standByTransitions') or {}
        if before is None or not tr:
            continue
        moved = ((tr.get('woken') or 0) + (tr.get('slept') or 0)
                 + (tr.get('diedAwake') or 0) + (tr.get('diedAsleep') or 0))
        b, pb = w.get('bots') or {}, before.get('bots') or {}
        if moved or b.get('awake') != pb.get('awake'):
            continue
        if b.get('total') != pb.get('total') or not b.get('awake'):
            continue
        calls = um(w).get('awakeCalls')
        if not calls:
            continue
        cands.append((w, calls / float(b['awake'])))

    print('  denominator calibration  %d quiet window(s)' % len(cands))
    if not cands:
        print('    no window had zero transitions AND an unchanged roster, so')
        print('    awakeCalls/frames is UNCALIBRATED. Do not quote a per-bot')
        print('    slope from it yet - this is a missing check, not a pass.')
        return

    hits = {'frames': 0, 'n': 0, 'neither': 0}
    for w, implied in cands:
        for name in ('frames', 'n'):
            got = w.get(name)
            # 2% covers a frame landing either side of the boundary; a real
            # duty cycle would be a ratio like 0.5, not a rounding difference.
            if got and abs(implied - got) / float(got) <= 0.02:
                hits[name] += 1
                break
        else:
            hits['neither'] += 1
    print('    implied frame count matches: frames %d, n %d, neither %d'
          % (hits['frames'], hits['n'], hits['neither']))

    # A DOMINANT MATCH IS THE RESULT; STRAGGLERS ARE STRAGGLERS. The first
    # version escalated on any non-match at all, so its first contact with real
    # data turned 33 of 34 agreeing on `frames` into "UpdateManual is NOT once
    # per bot per frame" -- a systemic verdict read off one window. The same
    # branch also compared a median implied count across windows against ONE
    # arbitrary window's `frames`, which is a different quantity: implied
    # counts vary because the windows do.
    best = max(('frames', 'n'), key=lambda k: hits[k])
    share = hits[best] / float(len(cands))
    if share >= 0.9:
        print('    -> denominator is `%s` (%.0f%% of quiet windows), and'
              % (best, 100 * share))
        print('       UpdateManual IS once per bot per frame.')
        if hits['neither']:
            worst = max(cands, key=lambda c: abs(c[1] - (c[0].get(best) or 0)))
            print('       %d outlier(s), worst implied %.0f against %s=%s in'
                  % (hits['neither'], worst[1], best, worst[0].get(best)))
            print('       that window - a straggler, not a scale factor.')
    else:
        print('    ! NO denominator dominates (%s leads at %.0f%%), so either'
              % (best, 100 * share))
        print('      UpdateManual is not once per bot per frame or the window')
        print('      is misaligned. Every per-bot slope from awakeCalls needs a')
        print('      scale factor before it is quoted.')


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    rows = load(argv[1:])
    if not rows:
        print('no sample windows found')
        return 2

    wins, dropped = eligible(rows)
    print('=' * 78)
    print('1. FIELD PRESENT AND DENOMINATORS INTACT')
    print('=' * 78)
    print('  read                     %s' % steady.sources(argv[1:]))
    print('  sample windows           %d' % len(rows))
    print('  carrying updateManual    %d' % sum(1 for w in rows if w.get('updateManual') is not None))
    print('  population               %s'
          % steady.describe(drop_teardown=True, by_start=True))
    lost = ', '.join('%s %d' % (k, v) for k, v in dropped.items() if v)
    print('  eligible                 %d%s'
          % (len(wins), ('   (dropped: %s)' % lost) if lost else ''))
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

    denominator_calibration(wins)

    # THE CENSUS AND THE CALL RATE COUNT DIFFERENT POPULATIONS, and section 3
    # divides one by the other. `updateManual` counts every bot whose
    # UpdateManual runs; `CountBots` skips any bot with a null StandBy. That
    # skip is documented in Telemetry.cs, which says agents.live is reported
    # alongside precisely so the two can be cross-checked rather than assumed
    # equal - and this reader never did the cross-check.
    #
    # It is not theoretical. 23 of 401 in-raid windows disagree, 20 of them
    # past the warm-up cut, and the severe ones read awake=0 asleep=0 against
    # agents.live of 20-25.
    #
    # DIAGNOSED, and my first guess and Beta's were both wrong. Not corpses,
    # and not "every bot held a null StandBy" - BotOwner.StandBy is assigned
    # inside BotOwner.Create, so that state is unreachable. The census did not
    # RUN: all 33 such windows in the corpus are the LAST in-raid window of
    # their raid segment, 33 of 33, so the raid ended at the window boundary
    # and Singleton<IBotGame> was gone when the census read at window close.
    #
    # `final` marks only 17 of the 33; the other 16 reach every reader.
    #
    # I CLAIMED THOSE 16 WERE FULL-LENGTH AND THEY ARE NOT. That claim came
    # from their absence in a short-window list they could not appear in -
    # they predate `windowSec` entirely, so the query that found short windows
    # never saw them. Absence of evidence read as evidence of absence.
    #
    # Reconstructed as frames x frame.avg, those 16 run a median of 25.0 s
    # against a configured 60, with 15 of 16 under 54 s - while the other 385
    # in-raid windows sit at a median of 60.0 s. They ARE truncated, which is
    # what `final` exists to exclude and does not.
    #
    # Not fixed here. A population change reaching every reader, minutes before
    # a raid, over 16 of 418 windows already excluded by two accidents, is the
    # same trade Beta declined on censusRead. Recorded, proposed, deferred - and
    # the FRAME data in them is still good, so the exclusion belongs to per-bot
    # quantities rather than to everything.
    # Those windows were excluded from the ratio only because a zero census
    # makes it NaN, and from the contrast only because an empty paused bucket
    # drops them - incidental safety twice over, which is the pattern this file
    # keeps finding elsewhere.
    # `n_live`, not `live` - that name is the module-level function this file
    # uses to subtract corpses, and shadowing it here crashed every log that
    # carries agents.live. I missed it by checking the first fourteen lines of
    # output instead of the exit code, one message after telling Alpha the fix
    # is something that must be found or a code that must be zero.
    mismatch = []
    for w in wins:
        b = w.get('bots') or {}
        n_live = (w.get('agents') or {}).get('live')
        aw, asl = b.get('awake'), b.get('asleep')
        if n_live is None or aw is None or asl is None:
            continue
        if abs(n_live - (aw + asl)) > 1:
            mismatch.append((w, n_live, aw + asl))
    if mismatch:
        print('  ! %d window(s) where agents.live disagrees with awake+asleep by >1.'
              % len(mismatch))
        print('    The census did not run, so its zero is "could not look" and not')
        print('    "looked and found none". The denominator in section 3 is wrong')
        print('    for those windows rather than noisy. Worst: live %d, census %d.'
              % max(mismatch, key=lambda t: t[1] - t[2])[1:])
        print('    Frame data in those windows is unaffected - this invalidates the')
        print('    bots.* fields only.')

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
            print('    because the field is present in every window. Note the asymmetry')
            print('    with bots.deadAwake: deadCalls integrates over every call, so its')
            print('    zero means no corpse ticked. deadAwake is one roster sample and')
            print('    its zero is the predicted value for a transient - it means nothing.')

    print()
    print('=' * 78)
    print('2. STRATIFICATION - the comparison is gated, not pooled')
    print('=' * 78)
    groups = {}
    for w in wins:
        groups.setdefault(stratum(w), []).append(w)
    for key, ws in sorted(groups.items(), key=lambda kv: stratum_sort(kv[0])):
        print('  %s  %d windows' % (stratum_label(key), len(ws)))
    # Where the arm label came from, always printed. A leg-level value labels a
    # whole leg correctly and CANNOT see a mid-session flip, which is the exact
    # thing the per-window key was added to catch - so it gates a between-leg
    # contrast and not a within-leg one. Silent provenance is how a leg-level
    # label gets read as a window-level fact.
    srcs = collections.Counter(far_source(w) for w in wins)
    print('  forceAllRoles source       %s'
          % ', '.join('%s %d' % (k, v) for k, v in sorted(srcs.items())))
    if srcs.get('leg') and not srcs.get('window'):
        print('    LEG-level only: the header is written once, so this labels the whole')
        print('    leg and cannot see a mid-session flip. Fine for a between-leg')
        print('    contrast; not sufficient to gate a within-leg one.')
    elif srcs.get('leg') and srcs.get('window'):
        print('    MIXED provenance across inputs - some legs window-attributed, some')
        print('    leg-attributed. Do not treat these strata as uniformly window-level.')

    # A stratification is only as good as the flag it strata on. Warn when the
    # flag records a wish rather than a state, and check it against the observed
    # counterpart instead of trusting either alone.
    far_vals = set(k[2] for k in groups)
    if len(far_vals - {None}) > 1:
        took, detail = force_all_roles_arm_took_effect(groups)
        _latched, mods = force_all_roles_is_latched(wins)
        print()
        if took is None:
            print('  ! forceAllRoles varies but bots.standByBlocked is absent, so whether')
            print('    the flip reached the bots CANNOT be determined. The strata are')
            print('    labelled arms, not demonstrated ones.')
        elif not took:
            print('  ! forceAllRoles varies and bots.standByBlocked DOES NOT FOLLOW IT')
            print('    (median %.1f on, %.1f off). The flag changed and the population'
                  % (detail['on'], detail['off']))
            print('    did not: the grant is applied once per bot at activation and')
            print('    nothing revokes it, so a later window inherits the earlier arm.')
            print('    THESE ARE NOT ALTERNATING ARMS. Do not difference across them.')
        else:
            print('  forceAllRoles arm took effect: standByBlocked median %.1f on,'
                  % detail['on'])
            print('    %.1f off - the flip reached the population.' % detail['off'])
        if mods:
            print('    mods present: %s (context only - the verdict above is from the'
                  % ', '.join(sorted(mods)))
            print('    observed counterpart, not from which mods are installed)')

    if len(groups) > 1:
        print()
        print('  Reported per stratum below and NEVER differenced across them.')
        print('  deactivateSleeping changes which paused path a bot takes, so it changes')
        print('  what pausedMs measures; standBy decides whether paused is populated at all.')

    failed = []
    for key, all_ws in sorted(groups.items(), key=lambda kv: stratum_sort(kv[0])):
        # A window with either bucket empty is dropped from the POOLED sums too,
        # not just from the per-window spread. Keeping it contributes awake ms
        # with no paused counterpart, which biases the contrast upward by
        # exactly the awake total of the dropped window. Found by a synthetic
        # that put one such window in the stratum: it changed the pooled mean
        # and printed no warning, because the pooled paused count was non-zero
        # from the OTHER windows.
        ws = [w for w in all_ws
              if (um(w).get('awakeCalls') or 0) and (um(w).get('pausedCalls') or 0)]
        dropped = len(all_ws) - len(ws)

        print()
        print('=' * 78)
        print('3. DILUTION CHECK   %s   (%d windows)' % (stratum_label(key), len(ws)))
        print('=' * 78)
        if dropped:
            print('  %d window(s) dropped: one bucket empty. Excluded from the pooled sums as' % dropped)
            print('    well as the spread - an unpaired awake total inflates the contrast.')
            # Name the maps, because "3 windows dropped" and "3 windows dropped,
            # all factory4_day, where stand-by CANNOT fire by geometry" are
            # different facts. factory's player span is ~46x72 m against a
            # sleepDistance of 150, so nothing there is ever far enough to
            # sleep: 19 in-raid windows across 4 raids, 0% with any bot asleep,
            # against 86-100% on every other map. Those windows are a STRUCTURAL
            # exclusion rather than a bad sample, and an anonymous drop count
            # hides which. No factory window carries updateManual yet, so this
            # path is unexercised on real data and will first matter the next
            # time factory is run.
            gone = collections.Counter((w.get('map') or '?')
                                       for w in all_ws if w not in ws)
            print('    by map: %s'
                  % ', '.join('%s %d' % (m, n) for m, n in gone.most_common()))

        # WHICH LEGS THIS STRATUM POOLS. `_log` has been carried since this file
        # was written and never printed, so every contrast it has produced was a
        # pooling of unnamed legs. A stratification that does not disclose its
        # composition just moves the assumption one level down - Alpha's phrase,
        # after their per-map split turned out to be 75% one leg.
        #
        # Not theoretical: factory4_day pools a leg with `asleep` 0 across 19
        # windows at 21.91 ms p50 beside two healthy legs at 9.34 and 8.44, on
        # identical standBy/cullSleeping/skipLate/skipTick. No config splits it.
        # The empty-bucket filter above catches a leg where NOTHING slept, since
        # pausedCalls goes to zero - but a partly-broken leg passes, and then
        # only the leg list shows it.
        if ws:
            legs = collections.Counter(leg_key(w) for w in ws)
            if len(legs) > 1:
                print('  pooled from %d legs:' % len(legs))
                for lg, n in legs.most_common():
                    print('    %-46s %3d windows  %4.0f%%'
                          % (leg_name(lg), n, 100.0 * n / len(ws)))
                top = legs.most_common(1)[0][1] / float(len(ws))
                if top > 0.5:
                    print('    ! one leg is %.0f%% of this stratum - it is not a pooled' % (top * 100))
                    print('      estimate so much as that leg with company.')
            else:
                print('  single leg: %s' % leg_name(list(legs)[0]))
        if not ws:
            print('  ! no window in this stratum has both buckets populated - no contrast.')
            failed.append('%s has no two-bucket window' % stratum_label(key))
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
            med_census = st.median([c for c, _ in both])
            med_rate = st.median([d for _, d in both])
            print('  corpse count, two routes: call-rate median %.2f (used), roster'
                  % med_rate)
            print('    sample median %.2f (cross-check)' % med_census)
            # Asymmetric on purpose, for two independent reasons. Corpses are
            # transient, so the one-shot roster sample reading 0 is its
            # PREDICTED value and refutes nothing - only a NONZERO reading
            # carries information, because it means the sample landed inside a
            # residency. A symmetric disagreement test would fire on every
            # honest window and then be ignored, which is how a check stops
            # being read.
            #
            # And separately: agreement between two routes is weak evidence in
            # general. Alpha and I quoted one remainder as 0.679 and 0.726 ms
            # from an aggregation-order error that produced a 0.001 ms gap on
            # the other leg - two methods agreeing to three decimals while one
            # was wrong. Do not add a line saying the routes concur.
            if med_census > 0 and med_rate > 0:
                gap = abs(med_census - med_rate) / max(med_census, med_rate)
                if gap > DILUTION_TOL:
                    print('  ! both routes are nonzero and differ by %.0f%% - the roster is'
                          % (gap * 100.0))
                    print('    turning over inside the window and neither count describes it.')
            elif med_census == 0 and med_rate > 0:
                print('    roster sample at 0 against a nonzero call rate is EXPECTED for a')
                print('    sub-window transient. It is not confirmation of anything.')

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
        print('4. THE CONTRAST   %s' % stratum_label(key))
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
            failed.append('%s is all-corpse after subtraction' % stratum_label(key))
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
        # PAIRED PER-WINDOW, not a product of aggregates. This line used to be
        # `pooled contrast x median awake bots`: two aggregates multiplied,
        # which is the same defect class as a difference of medians and needs
        # no window to have produced the value. On raid 1.5 it read 0.0131
        # against 0.0137 here, 4.6% low.
        #
        # Found because Alpha swept their own readers by SHAPE and found four
        # instances, one reporting a negative unaccounted time. My own audit
        # grepped for the literal `median(a) - median(b)` and missed this,
        # because a product does not match that pattern. Their caveat was the
        # useful part: finding none is consistent with having none AND with
        # one's instances sitting in the small cells. Mine was in a small cell.
        #
        # The dilution correction is a pooled quantity and does NOT propagate
        # into this route, so it is labelled uncorrected rather than silently
        # carrying `best`.
        per_frame, live_census = [], []
        for w in ws:
            c = float((w.get('bots') or {}).get('awake') or 0)
            corpses, _route = census_corpses(w)
            if census_known and corpses is not None:
                c -= corpses
            c = max(c, 0.0)
            live_census.append(c)
            l_ms, l_calls = live(w, dead_known)
            a = mean_or_none(l_ms, l_calls)
            p = mean_or_none(float(um(w).get('pausedMs') or 0.0),
                             um(w).get('pausedCalls') or 0)
            if a is not None and p is not None:
                per_frame.append((a - p) * c)
        med_awake = st.median(live_census)
        med_pf = st.median(per_frame) if per_frame else None
        if med_pf is not None:
            print('  median per-window contrast x that window\'s %s awake bots'
                  % ('live' if census_known else 'census (corpses in)'))
            print('    =  %.4f ms/frame   (median awake %.1f; uncorrected for dilution)'
                  % (med_pf, med_awake))

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
            ref = med_pf
            if ref and direct and abs(direct - ref) / max(abs(ref), 1e-9) > 0.25:
                mean_awake = sum(live_census) / len(live_census)
                print('  ! the two disagree by %.0f%%. Not an error: the first takes a'
                      % (100.0 * abs(direct - ref) / abs(ref)))
                print('    MEDIAN over windows, the second pools every frame. Median awake')
                print('    %.1f against mean awake %.1f - a skewed awake population across'
                      % (med_awake, mean_awake))
                print('    windows is the cause, so no single per-frame figure describes')
                print('    this run and neither number should be quoted alone.')
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
