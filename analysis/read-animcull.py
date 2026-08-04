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
`CulledLastFrame`, which is `Marked().Count` -- the `Sleeping` set under
`CullSleepingBotAnimators`, the whole live roster under `CullAllBotAnimators`,
and empty otherwise. So it reports what we ASKED for and drops to 0 the instant
the flag flips whether or not the engine let go.

WHAT `animCulledEngine` ADDS, AND THE PART THAT IS EASY TO OVERSTATE.

**CORRECTED 2026-08-04. THIS PARAGRAPH ASSERTED A FALSE PREMISE FROM 383f6f0
UNTIL TODAY** -- that the field "walks the same `Sleeping` set as its two
neighbours, same population, same denominator." It does not, and has not since
`aeec0d4`, which widened it deliberately and said so at
`SleepingBotAnimatorPatch.cs:347`. `git log -S "AppendLiveBots(bots)"` names
that commit and no other. The reader was never updated; the emitter documented
the change; both are ancestors of HEAD. Found by Gamma, 2026-08-04.

`CulledEngine` walks the WHOLE LIVE AI ROSTER -- `AllAlivePlayersList` filtered
by `IsLiveBot` -- and never touches `Sleeping`. So the populations are
ARM-DEPENDENT, and the arm this protocol tests is the row where they differ:

  coupled cull (Sleeping)   animCulled = Sleeping subset, engine = live roster
  decoupled  (CullAll)      both = live roster
  both off                  animCulled = empty,           engine = live roster

They coincide in VALUE in the coupled arm only while nothing carries
`CullCompletely` that we did not mark -- which is exactly the latch. So the one
condition that separates the populations is the one the field exists to detect.

**AND SECTION 3 CANNOT SEE IT. MEASURED, NOT ARGUED, 2026-08-04.** Both cull-arm
tests are lower bounds (`>= DELIVERY_MIN`), so a ratio above 1 passes trivially;
`<= CONTROL_MAX` guards the CONTROL arm only. Fabricated coupled-arm windows
through this reader, with a positive control proving it can fail:

    engine = 0.0 x marked -> engine/animCulled 0.000  FAIL, exit 1   (control)
    engine = 1.0 x marked -> engine/animCulled 1.000  ok,   exit 0
    engine = 3.0 x marked -> engine/animCulled 3.000  ok,   exit 0

Three times the marked population still culled by the engine reads `ok` and
`Readable`. Section 4 then abstains, because the protocol pins `skipLate` off
and a latch "CANNOT occur" -- so the signal has two places to surface and
neither carries it. **A PASS HERE MEANS THE WRITE LANDED AT LEAST 90% OF WHAT WE
MARKED. IT DOES NOT MEAN THE CULL IS CLEAN.** Do not quote it as more.

An upper bound on `engine/asked` is deliberately NOT added in this commit: it is
a behaviour change to a pre-registered gate hours before it runs, and the last
guard added to a shipping file here refused every good case and was caught only
by a real run. It needs a negative control, which means an actual clean A/B.

That buys three different things depending on the arm, and only two of them are
available in `protocol-anim-cull.ini`:

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


def build_can_emit(field, paths):
    """(verdict, note) for whether the BINARY behind these logs could emit it.

    True / False / None, where None is "the join does not reach an answer" and
    must never be collapsed into either.

    FALSE IS EVIDENCE, NOT PROOF, AND AN EARLIER VERSION OF THIS FILE CLAIMED
    OTHERWISE. It printed "structural, not a fact about any raid - no config,
    map or arm could have produced a value here", inheriting a premise Beta
    then withdrew and measured: for the one binary whose logs can be joined 1:1
    (Base, 30 logs, one image), ~46 keys are demonstrably emitted and absent
    from the image. `brainsTicked`, `poolSize`, `worldUpdate`, `spikes` among
    them. Some names are built at runtime and some are Unity's own PlayerLoop
    system names that were never ours to emit, so **no static extraction can be
    complete** and impossibility was never available from it.

    What survives is a joint claim from two independent directions: the field
    appears in no image that could have written a log, AND no window in this
    run carries it. The second is ground truth for this population rather than
    inference. That is worth printing and is not the same sentence.

    Read straight out of Beta's `build-fields.json` rather than inferred from a
    commit. `read-animcull` used to assert "every log before 86a13bb is in this
    state", which was a claim about an ancestry I had reasoned about and never
    measured.

    THE JOIN IS SOUND FOR ONE DIRECTORY AND NOT THE OTHER, and that asymmetry
    is Beta's, stated in the file's own `semantics.join`:

      Base        one binary wrote all 30 logs (md5 b6bd3927), so directory ->
                  binary resolves and the answer is exact.
      SPT4.0.13   the INSTALLED binary is not the one that wrote most of its
                  logs, so directory -> binary does not resolve. All that is
                  available is a bracket: `fieldsInEveryBinary` (every
                  candidate could emit it) and `fieldsUnion` (none could).
                  Between the two the honest answer is None.

    `present` is an upper bound -- the emit code exists, not that it fired --
    so a True here never licenses "this field should have had a value".

    THE BRACKET IS NARROWED WITH `deployed`, AND NEITHER PRECOMPUTED UNION IS
    THE RIGHT ONE. Beta added a deploy status per binary after I flagged that
    `fieldsUnion` spans builds that never wrote a log. But:

      fieldsUnion          includes `deployed: false` - a build output that
                           demonstrably wrote nothing. Too wide.
      fieldsUnionDeployed  drops ONLY the proven-false and keeps every
                           `deployed: null`, which is the correct reading of a
                           record its own evidence line calls incomplete.

    I asserted in an earlier version of this docstring that
    `fieldsUnionDeployed` excluded the unknown-deploy binaries and was
    therefore too narrow. **That was wrong** -- a claim about someone else's
    artefact written without opening it. Verified since: it is set-identical to
    the union computed below, on every record.

    The set is still computed here rather than read, for one reason: this
    reader's False branch says "no raid could have produced this", and it
    should not depend on a consumer and a producer agreeing about what
    `deployed: null` means. The rule is stated where it is used - unknown
    counts as could-have - and if the file's convention ever changes, this
    keeps giving the safe answer instead of silently inheriting a new one.
    Beta's proof of why unknown must stay in is the `Base` binary itself: it is
    installed right now and named in no document, so "no record" meaning "never
    shipped" would have excluded the binary that wrote 30 of the 55 logs.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'build-fields.json')
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None, 'build-fields.json unreadable; no build-side answer'

    installs = set()
    for p in paths:
        low = os.path.abspath(p).lower()
        for name in ('base', 'spt4.0.13'):
            if (os.sep + name + os.sep) in low:
                installs.add(name)
    if len(installs) != 1:
        return None, 'cannot tell which install these logs came from'
    install = installs.pop()

    if install == 'base':
        for rec in data.get('records') or []:
            if (rec.get('install') or '').lower() == 'base':
                # GROUND TRUTH FIRST. Base is the one install whose logs join
                # 1:1 to a single image, so `fieldsObservedInLogs` is not
                # inference -- the key appeared, therefore the binary emits it.
                #
                # This branch used to answer from `fields` alone, which is the
                # wide identifier set, and that was wrong in BOTH directions:
                # a positive could match a class name or a log message, and a
                # negative was flatly false for the ~46 keys this binary
                # demonstrably emits without their names appearing in its
                # image. `brainsTicked` is the live example - observed in the
                # logs, absent from the image, and this returned False for it.
                obs = rec.get('fieldsObservedInLogs')
                md5 = (rec.get('md5') or '?')[:8]
                if obs and field in obs:
                    return True, ('observed in Base\'s own logs, which join 1:1 '
                                  'to image %s' % md5)
                if field in (rec.get('fields') or []):
                    return None, ('the string is in image %s but no Base log '
                                  'carries the key - the wide set cannot tell '
                                  'an emit from a class name' % md5)
                return False, ('not found in image %s, and not among the %d '
                               'keys its 30 logs ever carried'
                               % (md5, len(obs or [])))
        return None, 'no Base record in build-fields.json'

    # POSITIVE branch takes the NARROW set, per the file's own whichSetToUse:
    # `fieldsInEveryBinary` is every identifier-shaped string in the image and
    # runs to 750 entries including AICoreControllerClass, AI and Additionally,
    # so a short field name can match a class name or a log message rather than
    # an emit. `jsonKeysInEveryBinary` is a complete `"name":` literal present
    # in every binary, so its PRESENCE is strong.
    #
    # Its absence is not, and that asymmetry is why the two branches must use
    # different sets. The strong set still misses every name emitted through a
    # helper -- `frame`, `aiTotal`, `ambientLight` and `windowSec` all read
    # absent from it while being present and working. A false absence here
    # yields None, which is the safe direction; the same set on the negative
    # branch would call a live field structural.
    if field in (data.get('jsonKeysInEveryBinary') or []):
        return True, 'a complete emit literal in every candidate binary'
    could = set()
    for rec in data.get('records') or []:
        if rec.get('deployed') is not False:
            could |= set(rec.get('fields') or [])
    if field not in could:
        return False, 'not found in any image that could have written a log'
    return None, ('SPT4.0.13: the installed binary did not write most of these '
                  'logs, and this field is in some candidate binaries and not '
                  'others - the join does not reach an answer')


def arm_of(w):
    """(cullSleeping, skipLate, cullAllBots) or None if unresolvable.

    None is a REFUSAL. A window whose arm cannot be established is not a
    control window; treating an absent flag as false would silently fill the
    control arm with windows that never declared one.

    `cullAllBots` is the THIRD dimension and it is deliberately tri-state.
    Beta's decoupled cull (aeec0d4) culls a population that is not `Sleeping`,
    so a decoupled arm and an ordinary cull arm are different experiments that
    would otherwise share a key and be differenced against each other.

    Absent stays None rather than collapsing to False. Every log written before
    that commit lacks the key, and the two are not the same thing: False is a
    build that has the mode and declined it, None is a build that could not
    have had it. They happen to behave alike because the flag defaults off --
    which is an inference about a default, and inferring a default is how a
    field's absence gets read as a measurement. Kept distinct and shown as `-`
    so a run mixing them is visible rather than silently pooled.
    """
    cfg = w.get('cfg') or {}
    cull, skip = cfg.get('cullSleeping'), cfg.get('skipLate')
    if cull is None or skip is None:
        return None
    all_bots = cfg.get('cullAllBots')
    return (bool(cull), bool(skip),
            None if all_bots is None else bool(all_bots))


def arm_sort(arm):
    """Sortable key. `sorted()` on the raw tuples raises once cullAllBots is
    tri-state, because None and bool are not orderable in Python 3 -- a crash
    that would arrive on the first decoupled log rather than in any test."""
    return tuple(-1 if v is None else int(v) for v in arm)


def arm_label(arm):
    """`-` for a build that predates cullAllBots, never `false`."""
    cull, skip, all_bots = arm
    return ('cull=%-5s skipLate=%-5s cullAll=%-5s'
            % (str(cull).lower(), str(skip).lower(),
               '-' if all_bots is None else str(all_bots).lower()))


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

    paths, src, refusal = steady.resolve_inputs(argv[1:])
    print('read:       %s' % src)
    if refusal:
        print(refusal)
        return 2

    rows = load(paths)
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
        emit, note = build_can_emit('animCulledEngine', paths)
        print('   REFUSED. No window carries the field, which is absent and')
        print('   NOT zero.')
        if emit is False:
            print('   AND %s.' % note)
            print('   Two independent sources agree - never seen in these')
            print('   windows, and not in any image. NEITHER PROVES the field')
            print('   was impossible: a static scan is measurably incomplete')
            print('   (Beta found ~46 fields demonstrably emitted by the one')
            print('   binary we can check against its own logs, yet absent')
            print('   from its image - names built at runtime, or the engine\'s')
            print('   own). Read this as "no evidence it could appear here",')
            print('   not as "no raid could have produced it".')
        elif emit is True:
            print('   BUT THE BUILD COULD EMIT IT (%s),' % note)
            print('   so the absence IS about these raids and is worth')
            print('   explaining rather than filtering away.')
        else:
            print('   Build-side answer UNAVAILABLE: %s.' % note)
            print('   Do not read this absence as either structural or real.')
        print('   exit 1 either way; refusing is the correct answer here.')
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
    for arm in sorted(by_arm, key=arm_sort):
        print('   %s  %3d window(s)%s'
              % (arm_label(arm), len(by_arm[arm]),
                 '' if len(by_arm[arm]) >= MIN_WINDOWS else '   (not scored)'))
    scored = {a: ws for a, ws in by_arm.items() if len(ws) >= MIN_WINDOWS}
    if not scored:
        print('   REFUSED. No arm reaches %d windows.' % MIN_WINDOWS)
        return 1
    print()

    failed = []

    # ---- 3. Delivery and write-landing, per arm ---------------------------
    print('3. DELIVERY (did the arm reach the engine?)')
    for arm in sorted(scored, key=arm_sort):
        cull = arm[0]
        ws = scored[arm]
        asleep = median([float((w.get('bots') or {}).get('asleep') or 0)
                         for w in ws])
        engine = median([float((w['bots'])['animCulledEngine']) for w in ws])
        asked = median([float((w.get('bots') or {}).get('animCulled') or 0)
                        for w in ws])
        print('   %s' % arm_label(arm))
        print('     asleep %6.1f   animCulled %6.1f   engine %6.1f'
              % (asleep, asked, engine))
        if not asleep:
            print('             no sleeping bots in this arm, so nothing to')
            print('             deliver -- the arm is UNSCORABLE, not clean.')
            failed.append('%s has no sleeping bots' % arm_label(arm))
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
        for arm in sorted(latchable, key=arm_sort):
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
    for arm in sorted(awake, key=arm_sort):
        print('   %s  awake %6.2f' % (arm_label(arm), awake[arm]))
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
