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

import importlib.util
import json
import math
import os
import statistics as st
import sys

STEADY_S = 120.0        # same warm-up discard as the marathon reader
MIN_PER_ARM = 3         # below this the drift bracket stops existing
Z_A, Z_B = 1.96, 0.8416   # two-sided 0.05, 80% power
CONTROL, TREAT = 'B1', 'B2'
# CONTAINS the AI tick; it is not identical to it, and the name gets shortened
# to "AI frames" by the second person who reads it. Measured on tonight's log,
# largest event per map, phase against that window's aiTotal.max:
#
#     Woods       SRBU 128.7   aiTotal.max 124.0   AI is 96% of it
#     Lighthouse  SRBU 101.6   aiTotal.max  10.0   AI is 10% of it
#
# So the proxy is excellent on Woods' spikes and BAD on Lighthouse's one large
# event, which is mostly other MonoBehaviours. It will be looser still at 10 ms,
# where a small number is more easily dominated by non-AI work. Section 6 prints
# the check per arm rather than asserting the proxy holds.
AI_PHASE = 'Update/ScriptRunBehaviourUpdate'
# LARGE-AI-FRAME THRESHOLD, and it was chosen for power before the leg ran.
# Measured on tonight's Lighthouse leg (19 steady windows), events per window and
# what k they give at the planned 3 windows/arm:
#
#     >=5 ms  6.26/win  k=38  detects 2.75x   - no longer "large"; avg covers it
#     >=10 ms 3.26/win  k=20  detects 4.0x    <- registered
#     >=15 ms 2.11/win  k=13  detects 7.35x
#     >=30 ms 1.05/win  k=6   detects >20x    - cannot fail, same defect as max
#
# 10 MS IS A POWER CHOICE AND NOTHING ELSE. An earlier version of this comment
# called it "the smallest threshold that still means a frame you could notice",
# which is false and would have been defended on grounds it never had: her
# demonstrated perception bound is <=90.6 ms for a WHOLE FRAME, so a 10 ms AI
# component inside a 14.5 ms frame is an ordinary frame. Alpha caught it. 10 ms
# is where k stops being unfalsifiable, full stop.
#
# I proposed 30 and it would have been unfalsifiable at this leg length - one
# message after arguing Alpha out of exactly that on aiTotal.max.
#
# THE GAP THIS LEAVES IS A FACTOR OF TWENTY AND IT MUST NOT BE CROSSED SILENTLY.
# Lighthouse has ONE >=100 ms AI-phase frame in 19 steady windows (0.05/win), so
# leg 4's ~6 protocol windows expect 0.3 of them. A NULL AT >=10 MS SAYS NOTHING
# ABOUT >=100 MS FRAMES, and the transfer between the two is an assumption, not
# a result. Woods runs 7x Lighthouse's rate at >=100 ms (0.35/win) and is where
# that question belongs.
#
# 4x IS A BIG EFFECT AND THE NULL MUST BE READ AS SUCH. Slicing cuts ticks 5.8x,
# so a pile-up mechanism should move the count by something near that; but a true
# ratio of 2x reads null here. See the fourth branch in section 6.
AI_MS = 10.0

# IMPORTED, NOT RESTATED. Both functions exist in read-slicing-raid.py and
# copying them is how this file acquired a stale docstring three hours ago.
# Every ad-hoc reimplementation tonight carried a defect the readers do not
# have, across two agents - a fresh implementation of the same rules is not
# independent of anything useful, it is correlated with every mistake a first
# implementation makes. importlib because the filename is hyphenated.
_spec = importlib.util.spec_from_file_location(
    'read_slicing_raid', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'read-slicing-raid.py'))
_rsr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rsr)
binom_two_sided = _rsr.binom_two_sided
detectable_ratio = _rsr.detectable_ratio


def load(paths):
    """Sample windows and spike lines, in file order.

    Spikes are kept because the arm contrast that can actually fail is a COUNT
    of large AI frames, and those live on spike lines. Keyed to arms through the
    sample window they fall in - see `ai_events`.
    """
    out, spikes = [], []
    for path in paths:
        for line in open(path, 'r', encoding='utf-8', errors='replace'):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            d['_log'] = os.path.basename(path)
            if d.get('type') == 'sample':
                out.append(d)
            elif d.get('type') == 'spike':
                spikes.append(d)
    return out, spikes


def ai_events(spikes, windows, threshold=AI_MS):
    """Spike lines inside `windows` whose AI phase clears `threshold`.

    Keyed on (log, window) because window counters restart per file exactly as
    `raid` does - 64 eligible windows in the marathon corpus shared only 46
    distinct ids, so keying on the number alone silently merges legs.
    """
    keys = set((w.get('_log'), w.get('window')) for w in windows)
    return [s for s in spikes
            if (s.get('_log'), s.get('window')) in keys
            and (s.get('phases') or {}).get(AI_PHASE, 0.0) >= threshold]


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


def binom_weighted(k, a, p):
    """Exact two-sided binomial at an arbitrary null share, not 1/2.

    THE ABA HAS UNEQUAL ARMS BY CONSTRUCTION AND p=1/2 IS WRONG FOR IT.
    Three presses give B1/B2/B1 - two control blocks against one treatment
    block - so the control arm carries twice the exposure. Under the null the
    expected control share is 2/3, not 1/2, and the imported `binom_two_sided`
    hardcodes 1/2 (`2.0 ** k`), which is correct for the balanced 7-step
    protocol it was written for and silently wrong here.

    Found by building the test log out of the REAL block structure instead of a
    balanced synthetic: 18 control events against 5 treatment came back p=0.011
    at p=1/2, which is a "significant" reading of data whose control arm simply
    ran twice as long. A balanced synthetic would never have shown it.

    So the exposure has to enter the null, not the estimate. p is the control
    arm's share of eligible windows.
    """
    if k == 0 or not 0.0 < p < 1.0:
        return float('nan')
    pmf = [math.comb(k, x) * p ** x * (1 - p) ** (k - x) for x in range(k + 1)]
    obs = pmf[a]
    return sum(v for v in pmf if v <= obs * (1 + 1e-9))


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
    samples, spikes = load(argv[1:])
    rows = [w for w in samples if arm_of(w) is not None]
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

    # ---- 2. the drift bracket, on BOTH arms ------------------------------
    #
    # Repeated blocks of one arm, separated by everything the other arm did. If
    # they disagree by more than the effect we are looking for, position and
    # session age move aiTotal more than the knob does and no arm contrast on
    # this leg is readable. That is what the repeated blocks buy: without them a
    # two-block design cannot tell a treatment effect from a trend.
    #
    # THE DESIGN IS NOW FOUR PRESSES, B1/B2/B1/B2, AND THE REASON IS THE NULL.
    # Three presses give B1/B2/B1 - two control blocks against one treatment -
    # so the control arm carries twice the exposure and H0 expects 2/3 of the
    # events there, not 1/2. Beta warned Alpha about exactly this formula when
    # the protocol was designed; Alpha agreed the balance mattered and then
    # specified three presses. Four is balanced 2:2, so the plain binomial is
    # correct by construction rather than by correction - and it gives a drift
    # bracket on the treatment side too, which three never did.
    blocks = {}
    for w in keep:
        blocks.setdefault((step_of(w), arm_of(w)), []).append(w['aiTotal']['avg'])
    ctrl_blocks = sorted((s, v) for (s, a), v in blocks.items() if a == CONTROL)
    treat_blocks = sorted((s, v) for (s, a), v in blocks.items() if a == TREAT)
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

    # The treatment side, reported and not gated. Two treatment blocks is new
    # with the fourth press and there is no history to set a threshold from, so
    # printing it beats inventing a bound - and a bound invented tonight would
    # be a threshold chosen after seeing what it excludes.
    if len(treat_blocks) > 1:
        tmeans = [st.mean(v) for _, v in treat_blocks]
        print('   treatment blocks    %s   gap %.3f ms (reported, not gated)'
              % ('  '.join('step %s n=%d mean %.3f' % (s2, len(v), st.mean(v))
                           for s2, v in treat_blocks),
                 max(tmeans) - min(tmeans)))

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

    # ---- 6. RELOCATED OR REMOVED - the contrast that can actually fail ----
    #
    # THE QUESTION: round-robin slicing changes WHICH brains tick on a frame; it
    # does not make any one brain's work cheaper. Her Woods mark is the reason to
    # care - a 139.8 ms frame she pressed on, 128.7 ms of it in this phase, with
    # `awake` = 2. Two awake bots and a 124 ms AI frame is ONE expensive
    # operation, not 25 brains at 5 ms each. Slicing cannot make that operation
    # cheaper, so it can only move it - unless the spikes are pile-ups of many
    # brains coinciding, in which case slicing genuinely prevents them.
    #
    # A COUNT, NOT A MAXIMUM, and that choice is the whole section. Alpha
    # registered `aiTotal.max` for this and withdrew it: max has cv 1.29-1.36 on
    # tonight's own legs against 0.12-0.13 for avg, so at n=3 it resolves ~300%
    # of the mean and "max does not fall" was guaranteed whatever the truth -
    # while being the expected branch. A count is near-Poisson and carries the
    # conditional binomial already registered for the spike primary.
    #
    # An estimator's sensitivity profile has to match the question. A median is
    # blind where a max is hypersensitive, and neither is a virtue on its own -
    # same defect as the `worst ms` column, arrived at from the opposite end.
    ce = ai_events(spikes, [w for w in keep if arm_of(w) == CONTROL])
    te = ai_events(spikes, [w for w in keep if arm_of(w) == TREAT])
    a, b = len(ce), len(te)
    k = a + b
    print('\n6. RELOCATED OR REMOVED   %s >= %.0f ms, per arm' % (AI_PHASE, AI_MS))
    print('   %s %d events / %d windows      %s %d events / %d windows'
          % (CONTROL, a, len(ctrl), TREAT, b, len(treat)))
    if k:
        # EXPOSURE-WEIGHTED NULL, FROM REALISED WINDOWS AND NEVER THE STEP COUNT.
        # The design is balanced 2:2, so this should come out at 50% - but the
        # design is not what happened, it is what was intended. She may die after
        # three presses, or press five times, or lose a block to the warm-up cut.
        # Weighting by the windows actually present makes a 2:1 outcome read as
        # 2:1 instead of as the plan. The share is printed for the same reason.
        #
        # detectable_ratio assumes p=1/2, so it is exact under the balanced
        # design and optimistic if the realised split is not - labelled as the
        # balanced-design bound rather than silently reported as this leg's.
        share = len(ctrl) / float(len(ctrl) + len(treat))
        dr = detectable_ratio(k)
        print('   k=%d, control holds %d of %d windows so H0 expects a %.0f%% share'
              % (k, len(ctrl), len(ctrl) + len(treat), 100 * share))
        print('   observed control share %.0f%%, exact two-sided p = %.4f'
              % (100.0 * a / k, binom_weighted(k, a, share)))
        print('   (balanced-design bound: %s x at k=%d - optimistic for unequal '
              'arms)' % (dr if dr else '>20', k))
    # BRANCHES STATED WHATEVER THE NUMBERS DID, so the reading is not chosen
    # after seeing them. The third is the one neither of us would have named:
    # a mean that falls while the count RISES is relocation plus concentration,
    # which is worse than either alone.
    print('   count HOLDS while avg falls  -> RELOCATED. Slicing moves the '
          'expensive operation;')
    print('                                   it does not remove it, and the '
          'frames she feels remain.')
    print('   count FALLS with avg         -> REMOVED. The spikes were pile-ups '
          'of coinciding')
    print('                                   brains, and slicing prevents them. '
          'Best case.')
    print('   count RISES while avg falls  -> RELOCATED AND CONCENTRATED. Worse '
          'than either.')
    # PROXY CHECK, printed rather than assumed. The phase CONTAINS the AI tick
    # and is not it: on tonight's Woods spike AI was 96% of the phase, on
    # Lighthouse's one large event it was 10%. If the ratio here is low, this
    # section is counting MonoBehaviour frames and the AI reading does not
    # follow - which is a fact about the metric, not about slicing.
    for label, evs in ((CONTROL, ce), (TREAT, te)):
        if not evs:
            continue
        big = max(evs, key=lambda s2: (s2.get('phases') or {}).get(AI_PHASE, 0.0))
        span = (big.get('phases') or {}).get(AI_PHASE, 0.0)
        host = [w for w in keep if w.get('window') == big.get('window')
                and w.get('_log') == big.get('_log')]
        amax = (host[0].get('aiTotal') or {}).get('max') if host else None
        if amax and span:
            print('   proxy check %s: largest phase %.1f ms, window aiTotal.max '
                  '%.1f ms (%.0f%% AI)' % (label, span, amax, 100.0 * amax / span))
    # THE FOURTH LINE, which the three-branch table invites you to forget: at
    # k~20 a null excludes changes above ~4x and nothing smaller. Slicing cuts
    # ticks 5.8x, so a pile-up mechanism should clear that - but a true 2x
    # reduction reads here as "count holds" and would be filed as RELOCATED.
    if k:
        dr2 = detectable_ratio(k)
        print('   NULL MEANS: no change larger than %s x. It does NOT mean the '
              'count held.' % (dr2 if dr2 else '>20'))
    if k and detectable_ratio(k) is None:
        print('   ! k is too small to call any of the three. Report the counts '
              'and stop.')

    # ---- 7. the tail, printed and NOT tested -----------------------------
    cm = [w['aiTotal'].get('max') for w in keep
          if arm_of(w) == CONTROL and w['aiTotal'].get('max') is not None]
    tm = [w['aiTotal'].get('max') for w in keep
          if arm_of(w) == TREAT and w['aiTotal'].get('max') is not None]
    if cm and tm:
        cv = st.stdev(cm) / st.mean(cm) if len(cm) > 1 and st.mean(cm) else float('nan')
        print('\n7. NOT TESTED  aiTotal.max   %s median %.2f   %s median %.2f'
              % (CONTROL, st.median(cm), TREAT, st.median(tm)))
        print('   control cv %.2f. At n=%d that resolves ~%.0f%% of the mean, so '
              'a null here' % (cv, len(cm), 100 * detectable(st.stdev(cm), len(cm))
                               / st.mean(cm) if len(cm) > 1 and st.mean(cm) else
                               float('nan')))
        print('   means nothing at all. Section 6 is the tail question that can '
              'fail.')

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
