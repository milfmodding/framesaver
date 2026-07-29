#!/usr/bin/env python3
"""Read the three-press aiTotal ABA on the closing Lighthouse leg.

WRITTEN BEFORE THE RAID, same as read-marathon.py and read-slicing-raid.py.
Every choice here -- which windows are excluded, what the drift bracket has to
show, what counts as the leg being unreadable -- was made without knowing the
answer.

WHY THIS FILE EXISTS SEPARATELY. read-slicing-raid.py scores spike counts under
a 7-step B1/B2 protocol. The design changed: the p50 A/B needed 34 windows per
arm in the most favourable case in the whole corpus against a longest-ever leg
of 19, so it was replaced by three presses scored on `aiTotal.avg`, whose
window-to-window sd is 0.042-0.106 ms against means of 0.13-0.70. Different
metric, different arm structure, different gate. Editing the pre-registered
spike reader to cover this would have left neither file describing a design we
were actually running.

WHAT THIS MEASURES, AND THE SENTENCE A WRITE-UP WILL GET WRONG:

    aiTotal.avg IS A MEAN AND STUTTER IS A TAIL.

`aiTotal.max` runs an order of magnitude above `aiTotal.avg` on every window we
have. This leg answers "does slicing reduce MEAN AI cost, and by how much" --
which is the brain tick's share of aiTotal, a number nobody has and which the
frame-cost ceiling currently has to assume. It does NOT answer "does slicing
reduce stutter". The design became powerable partly by changing what it
measures. That is a fair trade and it has to be said out loud, every time.

Usage:  python read-aitotal-aba.py <log.ndjson> [more.ndjson ...]

Exit 0 when the leg is readable, 1 when a gate fails, 2 on bad input.
"""

import json
import math
import os
import statistics as st
import sys

STEADY_S = 120.0        # same warm-up discard as the marathon reader
MIN_PER_ARM = 3         # below this the drift bracket stops existing
Z_A, Z_B = 1.96, 0.8416   # two-sided 0.05, 80% power
CONTROL, TREAT = 'B1', 'B2'


def load(paths):
    """Sample windows carrying a protocol, in file order."""
    out = []
    for path in paths:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get('type') == 'sample':
                    d['_log'] = os.path.basename(path)
                    out.append(d)
    return out


def arm_of(w):
    return (w.get('protocol') or {}).get('arm')


def step_of(w):
    return (w.get('protocol') or {}).get('step')


def eligible(w):
    """In-raid, past warm-up, whole, and not the window a keypress cut short.

    `flushedByProtocol` is excluded because THE WINDOW IS SHORT - it was cut
    mid-window by the press, so its per-window statistics are drawn from fewer
    frames than every other row.

    I FIRST WROTE THE STRONGER REASON HERE AND IT WAS FALSE, copied from
    read-slicing-raid.py, which predates the fix. That text said `Advance()`
    applies the step's config before the flush, so the labels name the incoming
    arm while the sums describe the outgoing one. That WAS true, and `ada1824`
    reversed it: Telemetry.cs flushes and only then calls `Advance()`, so a
    flushed line's labels correctly describe the arm that just ended. Verified
    by reading both call sites, not by trusting either comment.

    So a brand-new file acquired a stale comment by copying, on the same evening
    two other stale comments were found. Copying is how a comment outlives the
    code it describes even in a file with no history - and the reason to write
    the weaker justification down is that the weaker one is the one that is
    still true.
    """
    return (w.get('state') == 'raid'
            and not w.get('flushedByProtocol')
            and not w.get('final')
            and (w.get('raidElapsed') or 0) >= STEADY_S
            and (w.get('aiTotal') or {}).get('avg') is not None)


def welch(a, b):
    """Welch t and two-sided p, normal approximation on the tail.

    Normal rather than exact-t on purpose: at 3 windows an arm the df estimate
    is doing more work than the data supports, and a p-value quoted to three
    places off 4 df reads as more precision than exists. The detectable effect
    printed above the p-value is the honest summary; this is a sanity number.
    """
    if len(a) < 2 or len(b) < 2:
        return None, None
    va, vb = st.variance(a) / len(a), st.variance(b) / len(b)
    if va + vb <= 0:
        return None, None
    t = (st.mean(a) - st.mean(b)) / math.sqrt(va + vb)
    p = math.erfc(abs(t) / math.sqrt(2.0))
    return t, p


def detectable(sd, n):
    """Smallest mean shift n windows an arm can call at 80% power."""
    return sd * math.sqrt(2.0 * (Z_A + Z_B) ** 2 / n)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    # SELECT ON `arm`, NOT ON THE PRESENCE OF THE `protocol` OBJECT.
    # ProtocolRunner.ResetForRaid() calls Load(), so `Loaded` is true on every
    # raid once the ini is on disk, and Telemetry emits `protocol` whenever
    # `Loaded`. Every window of every leg carries {step: 0, steps: 7, arm: null}
    # including the three legs that never pressed the key - so selecting on the
    # object would pull the whole marathon into an ABA that only happened on one
    # leg, and the "no ABA here" branch below could never fire. `arm` is null
    # until a press applies a step. Delta found the chain.
    rows = [w for w in load(argv[1:]) if arm_of(w) is not None]
    if not rows:
        print('no window carries a protocol ARM - there is no ABA in these files.')
        print('That is not a null result; it is an absent one. Check in this order:')
        print('  1. was framesaver.protocol.ini on disk at launch (protocol object')
        print('     present at all, with arm null)? If absent entirely, the ini was')
        print('     not installed and no press could have done anything.')
        print('  2. did a press register? Advance() logs on every press, so the')
        print('     BepInEx log beside this ndjson answers it directly.')
        return 1

    keep = [w for w in rows if eligible(w)]
    print('%s\n%d protocol windows, %d eligible (in-raid, past %.0f s, whole, '
          'not flush-cut)\n' % (' + '.join(os.path.basename(p) for p in argv[1:]),
                                len(rows), len(keep), STEADY_S))

    fails = []

    # ---- 1. did the lever engage? ----------------------------------------
    #
    # THE CHECK THE WHOLE LEG RESTS ON. With BigBrain present and deferral on,
    # the arm label reads as applied while the behaviour is vanilla - and the
    # null then reads as "slicing does nothing" when slicing never happened.
    bad = [(w.get('window'), arm_of(w), (w.get('agents') or {}).get('slicing'))
           for w in keep
           if (arm_of(w) == TREAT and (w.get('agents') or {}).get('slicing') is not True)
           or (arm_of(w) == CONTROL and (w.get('agents') or {}).get('slicing') is not False)]
    tested = sum(1 for w in keep if arm_of(w) in (CONTROL, TREAT))
    # An empty `bad` is a pass only if something was tested. On a log with no arm
    # labels every comparison above is skipped and this reported OK - a check that
    # cannot fail is not a check, and it read as the strongest possible
    # confirmation of the one thing the leg depends on.
    print('1. slicing matches arm   %s  (%d windows tested)'
          % ('OK' if not bad else '%d MISMATCHED %s' % (len(bad), bad[:4]), tested))
    if not tested:
        fails.append('no window carries a B1/B2 arm label - check 1 tested nothing')
    if bad:
        fails.append('agents.slicing disagrees with the arm label - the lever did '
                     'not do what the label says')

    # ---- 2. the drift bracket, which is what the third press buys ---------
    #
    # Two control blocks separated by everything the treatment block did. If they
    # disagree by more than the effect we are looking for, position and session
    # age move aiTotal more than the knob does and no arm contrast on this leg is
    # readable. THIS IS THE ONLY REASON THERE IS A THIRD PRESS: without it a
    # two-block ABA cannot tell a treatment effect from a trend.
    blocks = {}
    for w in keep:
        blocks.setdefault((step_of(w), arm_of(w)), []).append(w['aiTotal']['avg'])
    ctrl_blocks = sorted((s, v) for (s, a), v in blocks.items() if a == CONTROL)
    print('2. control blocks        %s'
          % ('  '.join('step %s n=%d mean %.3f' % (s, len(v), st.mean(v))
                       for s, v in ctrl_blocks) or 'NONE'))
    if len(ctrl_blocks) < 2:
        fails.append('fewer than 2 control blocks (%d) - drift is UNTESTED, not '
                     'absent, and the third press is what was supposed to test it'
                     % len(ctrl_blocks))
    else:
        means = [st.mean(v) for _, v in ctrl_blocks]
        gap = max(means) - min(means)
        # AND THE GATE IS ENFORCED, not just described. The first draft of this
        # file printed the gap and stated in a comment that a large one made the
        # leg unreadable - with no test behind it. That is the exact defect this
        # reader's sibling was fixed for two hours earlier: a criterion stated in
        # prose reads as a check and is not one.
        #
        # Measured against WITHIN-BLOCK spread, never the pooled control sd. If
        # the two control blocks genuinely differ, that difference inflates the
        # pooled sd, which inflates the threshold, which hides the difference -
        # a gate that gets looser exactly when it should fire.
        within = []
        for _, v in ctrl_blocks:
            if len(v) > 1:
                within += [x - st.mean(v) for x in v]
        sd_w = st.stdev(within) if len(within) > 1 else float('nan')
        n_min = min(len(v) for _, v in ctrl_blocks)
        tol = detectable(sd_w, n_min) if sd_w == sd_w else float('nan')
        print('   control-to-control gap %.3f ms against a %.3f ms resolution '
              '(within-block sd %.3f, n=%d)' % (gap, tol, sd_w, n_min))
        if not (tol == tol):
            fails.append('control blocks have under 2 windows each - their '
                         'agreement is untestable, which is not agreement')
        elif gap > tol:
            fails.append('control blocks differ by %.3f ms, more than the %.3f ms '
                         'this leg can resolve - position or session age moves '
                         'aiTotal more than the knob does, and no arm contrast '
                         'here is readable' % (gap, tol))

    # ---- 3. arm sizes ----------------------------------------------------
    ctrl = [w['aiTotal']['avg'] for w in keep if arm_of(w) == CONTROL]
    treat = [w['aiTotal']['avg'] for w in keep if arm_of(w) == TREAT]
    print('3. windows per arm       %s %d, %s %d' % (CONTROL, len(ctrl), TREAT, len(treat)))
    if len(ctrl) < MIN_PER_ARM or len(treat) < MIN_PER_ARM:
        fails.append('under %d windows in an arm - the blocks were too short, and '
                     'a short block fails as a low count rather than as an absent '
                     'effect' % MIN_PER_ARM)

    if fails:
        print('\nGATE FAILED - the arm contrast is NOT quotable:')
        for f in fails:
            print('  ! %s' % f)
        print('\nRefusing to print the comparison.')
        return 1

    # ---- 4. detectable effect FIRST, then the result ---------------------
    #
    # Printed above the contrast so a null is read as "this leg could not have
    # seen it" rather than "there is no effect". The effect size was never known
    # in advance here: the tick's share of aiTotal is the thing being measured,
    # so pricing the design against an assumed share would make the power figure
    # and the finding the same number.
    sd = st.stdev(ctrl) if len(ctrl) > 1 else float('nan')
    base = st.mean(ctrl)
    n = min(len(ctrl), len(treat))
    det = detectable(sd, n)
    print('\n4. DETECTABLE BEFORE THE RESULT')
    print('   control sd %.3f ms over %d windows, control mean %.3f ms' % (sd, len(ctrl), base))
    print('   at n=%d this leg resolves a shift of %.3f ms (%.0f%% of aiTotal)'
          % (n, det, 100.0 * det / base if base else float('nan')))
    ratios = [(w.get('agents') or {}).get('tickedSum', 0) /
              ((w.get('agents') or {}).get('liveSum') or 1)
              for w in keep if arm_of(w) == TREAT]
    cut = (1.0 / st.mean(ratios)) if ratios and st.mean(ratios) > 0 else None
    if cut:
        removed = 1.0 - 1.0 / cut
        print('   realized tick cut %.1fx (ticked/live %.3f), so it removes %.0f%% '
              'of the tick' % (cut, st.mean(ratios), 100 * removed))
        print('   => a null here means the brain tick is under ~%.0f%% of aiTotal,'
              % (100.0 * det / base / removed if base and removed else float('nan')))
        print('      NOT that slicing is free and NOT that stutter is unchanged.')

    # ---- 5. the contrast -------------------------------------------------
    diff = base - st.mean(treat)
    t, p = welch(ctrl, treat)
    print('\n5. CONTRAST  aiTotal.avg')
    print('   %s %.3f ms (n=%d)   %s %.3f ms (n=%d)   difference %+.3f ms'
          % (CONTROL, base, len(ctrl), TREAT, st.mean(treat), len(treat), diff))
    if t is not None:
        print('   Welch t %.2f, two-sided p ~%.3f (normal tail)' % (t, p))
    if abs(diff) < det:
        print('   NOTE: the difference is smaller than this leg can resolve. '
              'Report the bound,\n         not the point estimate.')

    # ---- 6. the tail, descriptive only -----------------------------------
    #
    # No test, by design. aiTotal.max is one frame per window, so its window-to-
    # window spread is the spread of a maximum and nothing here is powered for
    # it. It is printed because it is the ONLY tail number this leg produces,
    # and because goals 2 and 3 live in the tail while section 5 does not.
    cm = [w['aiTotal'].get('max') for w in keep
          if arm_of(w) == CONTROL and w['aiTotal'].get('max') is not None]
    tm = [w['aiTotal'].get('max') for w in keep
          if arm_of(w) == TREAT and w['aiTotal'].get('max') is not None]
    if cm and tm:
        print('\n6. DESCRIPTIVE  aiTotal.max   %s median %.2f ms   %s median %.2f ms'
              % (CONTROL, st.median(cm), TREAT, st.median(tm)))
        print('   No test. This is a mean-shift design; the tail is not powered '
              'and\n   section 5 says nothing about stutter.')

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
