#!/usr/bin/env python3
"""Is an anim-cull run readable at all? A GATE, not an estimator.

WRITTEN BEFORE A SINGLE `animCulledEngine` ROW EXISTS. The field shipped in
86a13bb and no log carries one. Every threshold below was fixed without knowing
the answer, same as read-botarm.py and read-botwindow.py.

THIS FILE DOES NOT FIT ANYTHING. The contrast is
`phases.DirectorUpdateAnimationBegin` against `bots.awake`, and that lives in
alpha-animator-slope.py. What is missing is anything that says the run was
INTERPRETABLE before that fit runs, and the animator cull is the one lever where
the guard field returned its own success value: `animCulled` is
`CulledLastFrame`, `Plugin.CullSleepingBotAnimators.Value ? Sleeping.Count : 0`,
so it reports what we ASKED for and drops to 0 the instant the flag flips
whether or not the engine let go.

WHAT `animCulledEngine` ADDS, AND THE PART THAT IS EASY TO OVERSTATE. It walks
the same `Sleeping` set as its two neighbours -- same population, same
denominator -- but is not gated on the config flag, so its zero does not follow
from the feature being off. That buys three different things depending on the
arm, and only two of them are available in `protocol-anim-cull.ini`:

  ARM DELIVERY   cull on  -> engine count tracks `bots.asleep`
                 cull off -> engine count near 0
                 Says the arm reached the ENGINE and not merely the config.

  WRITE LANDING  cull on  -> engine count tracks `animCulled`
                 A gap is the write failing to land. The known cause is
                 FastAnimatorProcessorClass, whose `cullingMode` is
                 `{ get; set; }` with no reader in the class: the write does
                 nothing AND round-trips, so a plain read-back would report
                 100% success for a feature doing literally nothing. Hence the
                 type test in CulledEngine, and hence this check.

  LATCH          cull off, skipLate ON -> engine count STAYS high
                 Player.VisualPass is the only writer of cullingMode and its
                 only call site is Player.LateUpdate, so the LateUpdate skip
                 suppresses the thing that would undo the cull, and a bot asleep
                 at an arm boundary stays culled into the next arm.

AND THE THIRD IS DESIGNED OUT OF THE SHIPPED PROTOCOL, WHICH IS THE POINT OF
SECTION 4. `protocol-anim-cull.ini` pins `Skip sleeping bot LateUpdate = false`
in every arm, deliberately and for the right reason -- a latched arm B bleeding
into arm A makes the experiment unmeasurable. But that means a latch CANNOT
OCCUR there, so an engine count near 0 on a control arm is not evidence a latch
was ruled out. It was removed. A check that cannot fail reports a pass, and this
one would report it on the most important lever in the mod, so section 4 prints
DESIGNED OUT rather than a verdict whenever `cfg.skipLate` is false throughout.

The distinction is not pedantic: the day someone runs a protocol that moves the
skip, section 4 starts testing something, and nothing about the output format
will tell them it changed unless it says so on both sides.

THE THRESHOLDS ARE GUESSES AND ARE REGISTERED AS SUCH. 0.90 and 0.10 below are
the numbers most likely to be wrong here. Slack is needed on both sides --
CulledEngine swallows a mid-teardown body rather than misclassifying it, so it
undercounts, and a control arm can carry a bot Unity culled for its own reasons.
Neither has ever been measured. If they turn out to need moving, say so in the
output: a threshold revised after seeing the data ends the pre-registration, and
a run scored under a moved threshold is not the run that was registered.

Usage:  python read-animcull.py <log.ndjson> [more.ndjson ...]

Exit 1 means DO NOT FIT -- the field is missing, or the run failed a gate.
Exit 1 on a corpus log is the CORRECT answer and not a defect: no log before
86a13bb carries the field, and refusing is the whole point of writing this now.
"""

import collections
import json
import os
import sys

import steady

# Cull arms: the engine must honour at least this fraction of the marking.
# Undercount is expected (mid-teardown bodies are swallowed), overcount is not.
DELIVERY_MIN = 0.90

# Control arms: the engine count must be at most this fraction of `asleep`.
# Not 0. A bot Unity culled for its own reasons is not our cull returning.
CONTROL_MAX = 0.10

# `bots.awake` must match across arms within this fraction of the pooled mean.
# The cull changes how a sleeping bot is DRAWN, not who sleeps -- so if the
# awake count moves with the arm then something other than the cull moved, and
# whatever slope comes out is not the cull's. Protocol check 2.
AWAKE_TOLERANCE = 0.15

# Below this an arm is reported but not scored. Two windows cannot show a
# spread, and a gate that passes on one window is a gate on one number.
MIN_WINDOWS = 3


def load(paths):
    """Sample rows, header cfg stamped onto each, per file."""
    rows = []
    for path in paths:
        try:
            fh = open(path, 'r', encoding='utf-8', errors='replace')
        except OSError as exc:
            print('cannot open %s: %s' % (path, exc))
            sys.exit(2)
        header = {}
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
                    header = obj
                elif obj.get('type') == 'sample':
                    obj['_log'] = path
                    # TOP LEVEL on the header, not inside `config` -- the first
                    # version of this line read header.config.windowSeconds,
                    # got None on every log, and steady.partition() charged all
                    # 58 windows of a 58-window log to "warm-up". A field-scope
                    # error reading as ordinary attrition, which is why that
                    # bucket is now split. read-updatemanual.py:110 had it
                    # right and this did not copy it.
                    obj['_windowSeconds'] = (header.get('windowSeconds')
                                             or (header.get('config') or {})
                                             .get('windowSeconds'))
                    rows.append(obj)
    return rows


def arm_of(w):
    """(cullSleeping, skipLate) for this window, or None if unresolvable.

    None is a REFUSAL. A window whose arm cannot be established is not a
    control window; treating an absent flag as false would silently fill the
    control arm with windows that never declared one.
    """
    cfg = w.get('cfg') or {}
    cull, skip = cfg.get('cullSleeping'), cfg.get('skipLate')
    if cull is None or skip is None:
        return None
    return (bool(cull), bool(skip))


def median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    mid = len(xs) // 2
    if len(xs) % 2:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2.0


def eligible(rows):
    """Steady windows that also carry an arm and are not protocol-truncated."""
    kept, dropped = steady.partition(rows, drop_teardown=True, by_start=True)
    out, no_arm, partial = [], 0, 0
    for w in kept:
        if w.get('flushedByProtocol'):
            partial += 1
        elif arm_of(w) is None:
            no_arm += 1
        else:
            out.append(w)
    dropped['flushed by protocol'] = partial
    dropped['arm unresolvable'] = no_arm
    return out, dropped


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    rows = load(argv[1:])
    windows, dropped = eligible(rows)

    print('population: %s' % steady.describe(drop_teardown=True, by_start=True))
    print('            + arm resolvable, + not flushedByProtocol')
    print('kept %d window(s); dropped %s'
          % (len(windows),
             ', '.join('%s %d' % (k, v) for k, v in sorted(dropped.items())
                       if v) or 'nothing'))
    print()

    # ---- 1. Presence. Absent is not zero, and this is where that bites -----
    #
    # Every field this reader needs would read as a clean, passing control arm
    # if absence were scored as 0: no engine culling on a cull arm is a
    # DELIVERY FAILURE, and it looks identical to a build that predates the
    # field. Refuse rather than score.
    have = [w for w in windows
            if (w.get('bots') or {}).get('animCulledEngine') is not None]
    print('1. FIELD PRESENCE')
    print('   animCulledEngine present in %d of %d window(s)'
          % (len(have), len(windows)))
    if not have:
        print('   REFUSED. No window carries the field, which is absent and')
        print('   NOT zero. Every log before 86a13bb is in this state and')
        print('   exit 1 here is the correct answer, not a defect.')
        return 1
    if len(have) < len(windows):
        print('   PARTIAL. The field appeared mid-corpus, so any comparison')
        print('   spanning both sides is a comparison of two builds. Split on')
        print('   the boundary before reading anything below.')
    print()

    by_arm = collections.defaultdict(list)
    for w in have:
        by_arm[arm_of(w)].append(w)

    print('2. ARMS, counted before any verdict')
    for arm in sorted(by_arm):
        cull, skip = arm
        print('   cull=%-5s skipLate=%-5s  %3d window(s)%s'
              % (str(cull).lower(), str(skip).lower(), len(by_arm[arm]),
                 '' if len(by_arm[arm]) >= MIN_WINDOWS else '   (not scored)'))
    scored = {a: ws for a, ws in by_arm.items() if len(ws) >= MIN_WINDOWS}
    if not scored:
        print('   REFUSED. No arm reaches %d windows.' % MIN_WINDOWS)
        return 1
    print()

    failed = []

    # ---- 3. Delivery and write-landing, per arm ---------------------------
    print('3. DELIVERY (did the arm reach the engine?)')
    for arm in sorted(scored):
        cull, _ = arm
        ws = scored[arm]
        asleep = median([float((w.get('bots') or {}).get('asleep') or 0)
                         for w in ws])
        engine = median([float((w['bots'])['animCulledEngine']) for w in ws])
        asked = median([float((w.get('bots') or {}).get('animCulled') or 0)
                        for w in ws])
        print('   cull=%-5s  asleep %6.1f   animCulled %6.1f   engine %6.1f'
              % (str(cull).lower(), asleep, asked, engine))
        if not asleep:
            print('             no sleeping bots in this arm, so nothing to')
            print('             deliver -- the arm is UNSCORABLE, not clean.')
            failed.append('cull=%s has no sleeping bots' % str(cull).lower())
            continue
        if cull:
            ratio = engine / asleep
            ok = ratio >= DELIVERY_MIN
            print('             engine/asleep %.3f  (need >= %.2f)  %s'
                  % (ratio, DELIVERY_MIN, 'ok' if ok else 'FAIL'))
            if not ok:
                failed.append('cull arm delivered %.3f of its marking' % ratio)
            # Write landing. Separate from delivery because they fail for
            # different reasons and the fix differs: a low engine/asleep with
            # engine == animCulled means we marked fewer bots than are asleep,
            # a low engine/animCulled means the write is not landing.
            if asked:
                land = engine / asked
                ok = land >= DELIVERY_MIN
                print('             engine/animCulled %.3f  (need >= %.2f)  %s'
                      % (land, DELIVERY_MIN, 'ok' if ok else 'FAIL'))
                if not ok:
                    failed.append('write not landing: engine is %.3f of the '
                                  'marking (inert animator?)' % land)
        else:
            ratio = engine / asleep
            ok = ratio <= CONTROL_MAX
            print('             engine/asleep %.3f  (need <= %.2f)  %s'
                  % (ratio, CONTROL_MAX, 'ok' if ok else 'FAIL'))
            if not ok:
                failed.append('control arm still culling %.3f of asleep'
                              % ratio)
    print()

    # ---- 4. Latch, and whether this run can even test for one -------------
    print('4. LATCH')
    controls = [a for a in scored if not a[0]]
    latchable = [a for a in controls if a[1]]
    if not controls:
        print('   NOT TESTED. No control arm in this run.')
    elif not latchable:
        print('   DESIGNED OUT, not ruled out. Every control arm here runs')
        print('   with skipLate=false, so Player.VisualPass rewrites')
        print('   cullingMode every frame and a latch CANNOT occur. The near-')
        print('   zero engine count above is the expected reading either way,')
        print('   so it is not evidence about latching.')
        print('   protocol-anim-cull.ini pins the skip off in every arm on')
        print('   purpose -- this is the protocol working, not a gap. Section')
        print('   3 is what that protocol can prove.')
    else:
        for arm in sorted(latchable):
            ws = scored[arm]
            engine = median([float((w['bots'])['animCulledEngine'])
                             for w in ws])
            asleep = median([float((w.get('bots') or {}).get('asleep') or 0)
                             for w in ws])
            ratio = (engine / asleep) if asleep else 0.0
            print('   cull=false skipLate=true  engine/asleep %.3f' % ratio)
            if ratio > CONTROL_MAX:
                print('             LATCHED. This control arm inherited the')
                print('             cull from the arm before it, so its frame')
                print('             time is not a control. Do not fit.')
                failed.append('control arm latched at %.3f' % ratio)
            else:
                print('             no latch detected, and this run COULD')
                print('             have shown one -- the check was live.')
    print()

    # ---- 5. Did anything but the cull move? -------------------------------
    #
    # Protocol check 2. The cull changes how a sleeping bot is drawn, not who
    # sleeps, so `bots.awake` moving with the arm means the arm is confounded
    # and the slope belongs to something else.
    print('5. AWAKE COUNT ACROSS ARMS (the cull must not move it)')
    awake = {a: median([float((w.get('bots') or {}).get('awake') or 0)
                        for w in ws]) for a, ws in scored.items()}
    for arm in sorted(awake):
        print('   cull=%-5s skipLate=%-5s  awake %6.2f'
              % (str(arm[0]).lower(), str(arm[1]).lower(), awake[arm]))
    vals = [v for v in awake.values() if v is not None]
    if len(vals) < 2:
        print('   one arm only, so nothing to compare.')
    else:
        pooled = sum(vals) / len(vals)
        spread = (max(vals) - min(vals)) / pooled if pooled else 0.0
        ok = spread <= AWAKE_TOLERANCE
        print('   spread %.3f of the pooled mean (need <= %.2f)  %s'
              % (spread, AWAKE_TOLERANCE, 'ok' if ok else 'FAIL'))
        if not ok:
            failed.append('bots.awake moved %.3f across arms' % spread)
    print()

    print('VERDICT')
    if failed:
        for f in failed:
            print('   FAIL  %s' % f)
        print('   Do not fit the animator slope on this run.')
        return 1
    print('   Readable. The arms reached the engine and the write landed;')
    print('   fit DirectorUpdateAnimationBegin against bots.awake in')
    print('   alpha-animator-slope.py. This says the instrument worked, not')
    print('   that the cull bought anything.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
