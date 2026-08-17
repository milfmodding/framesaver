"""Positive controls for delta-check3-offscreen.py.

THIS EXISTS BECAUSE OF WHY CHECK 3 WAS NEVER WRITTEN.
`protocol-anim-cull.ini:176` declined to implement check 3 before the 2026-08-04
raid on the grounds that "ac-crashtest.py currently cannot fail, so adding a
check whose validating harness is incapable of failing would be the defect this
file exists to avoid." That was the right call and it was about ac-crashtest.py.

So this harness does not use ac-crashtest.py, and every case below asserts a
SPECIFIC exit code -- including cases that must FAIL. A harness that only ever
asserts success is the thing being avoided.

AND THE HARNESS ITSELF IS TESTED. `--prove` mutates the reader in memory and
asserts that this suite goes red. A suite that cannot go red is not evidence
that the reader works; run it before believing a green result.

Usage:  python delta-check3-selftest.py [--prove]
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
READER = os.path.join(HERE, '..', 'delta-check3-offscreen.py')

REFUSE, COMPUTE = 1, 0


def window(i, cull, culled, offscreen, drop_field=False, arm=None,
           drop_arm=False):
    """One sample window.

    `arm` is the protocol STEP NAME. It defaults to an A/B name matching the
    cull flag, because that is the ordinary case; pass `warmup`/`standdown` to
    build the non-scored steps, or `drop_arm=True` to simulate a log written
    before the field existed.
    """
    bots = {'awake': 8, 'asleep': 20, 'total': 28,
            'animCulled': culled, 'animCulledEngine': culled}
    if not drop_field:
        bots['animCulledOffScreen'] = offscreen
    w = {'type': 'sample', 'state': 'raid', 'window': i, 'raid': 1,
         'map': 'lighthouse', 'final': False, 'frames': 3000,
         'raidElapsed': 240.0 + 60 * i, 'flushedByProtocol': False,
         'cfg': {'cullSleeping': cull, 'skipLate': False,
                 'windowSeconds': 60.0},
         'bots': bots}
    if not drop_arm:
        w['protocol'] = {'name': 'test', 'arm': arm or ('B1' if cull else 'A1')}
    return w


def write(name, windows):
    path = os.path.join(HERE, name)
    with open(path, 'w') as fh:
        fh.write(json.dumps({'type': 'header', 'windowSeconds': 60.0,
                             'config': {'windowSeconds': 60.0}}) + '\n')
        for w in windows:
            fh.write(json.dumps(w) + '\n')
    return path


# ---- The cases. Each names what it proves. ---------------------------------
CASES = []

# Clean: every marked bot honoured. Must COMPUTE.
CASES.append(('clean', COMPUTE, [
    window(i, i % 2 == 1, 20, 20) for i in range(8)]))

# A genuinely low ratio is NOT a refusal -- it is the finding. Must COMPUTE.
# This is the case the protocol calls "the interesting failure", and an
# instrument that refuses it would destroy the signal it exists to report.
CASES.append(('lowratio', COMPUTE, [
    window(i, i % 2 == 1, 20, 6) for i in range(8)]))

# Field absent. Must REFUSE -- absent is not zero.
CASES.append(('nofield', REFUSE, [
    window(i, i % 2 == 1, 20, 20, drop_field=True) for i in range(8)]))

# Cull arm marked nothing: denominator zero. Must REFUSE, not report 0.000.
CASES.append(('zerodenom', REFUSE, [
    window(i, i % 2 == 1, 0, 0) for i in range(8)]))

# No cull arm at all -- control only. Must REFUSE: no ratio, not a low one.
CASES.append(('nocullarm', REFUSE, [
    window(i, False, 20, 20) for i in range(8)]))

# Too few windows on the cull arm to score. Must REFUSE.
CASES.append(('thin', REFUSE, [
    window(0, True, 20, 20)] + [window(i, False, 20, 20) for i in range(1, 8)]))

# Off-screen EXCEEDS the marking. Structurally impossible -- off-screen is a
# subset of the marking -- so it is two counters on different populations, not
# a high ratio. Must REFUSE. This case is the one that protects the ceiling
# the estimator argument rests on: if the ratio could exceed 1.0, `median of
# ratios` would not be censored and Gamma's granularity argument would not
# hold. The invariant is asserted rather than assumed.
CASES.append(('overunity', REFUSE, [
    window(i, i % 2 == 1, 10, 14) for i in range(8)]))

# No `protocol.arm` at all -- a log predating the field. Must REFUSE, NOT fall
# back to scoring every cull=true window. Absent is not "all of them", and a
# silent fallback would reinstate the warmup/standdown contamination in the one
# case nobody would think to audit.
CASES.append(('noarmname', REFUSE, [
    window(i, i % 2 == 1, 20, 20, drop_arm=True) for i in range(8)]))

# Non-scored steps are DROPPED, not scored. Here warmup and standdown carry a
# ratio of 1.0 and the real B arms carry 0.5: if the filter failed open, the
# pooled figure would be dragged upward and still print a confident number.
# Must COMPUTE, and the reported composition must show the drop.
CASES.append(('dropsnonscored', COMPUTE,
              [window(i, True, 20, 20, arm='warmup') for i in range(3)]
              + [window(3 + i, False, 20, 0, arm='A1') for i in range(3)]
              + [window(6 + i, True, 20, 10, arm='B1') for i in range(3)]
              + [window(9 + i, True, 20, 20, arm='standdown')
                 for i in range(3)]))

# ONLY non-scored steps. Nothing survives the filter. Must REFUSE rather than
# report a ratio over an empty scored population.
CASES.append(('allnonscored', REFUSE,
              [window(i, True, 20, 20, arm='standdown') for i in range(4)]
              + [window(4 + i, True, 20, 20, arm='warmup') for i in range(4)]))


def run(mutate=None):
    failures = []
    for name, want, windows in CASES:
        path = write('c3-%s.ndjson' % name, windows)
        env = dict(os.environ)
        if mutate:
            env['DELTA_C3_MUTATE'] = mutate
        proc = subprocess.run([sys.executable, READER, path],
                              capture_output=True, text=True, env=env)
        got = proc.returncode
        ok = (got == want)
        print('  %-10s want exit %d, got %d   %s'
              % (name, want, got, 'ok' if ok else 'MISMATCH'))
        if not ok:
            failures.append('%s: wanted %d got %d' % (name, want, got))
    return failures


def main(argv):
    prove = '--prove' in argv

    print('delta-check3-offscreen.py -- positive controls')
    print()
    failures = run()
    print()

    if failures:
        print('SUITE RED:')
        for f in failures:
            print('   - %s' % f)
        return 1

    print('SUITE GREEN. %d cases, %d of which assert a REFUSAL.'
          % (len(CASES), sum(1 for c in CASES if c[1] == REFUSE)))

    if prove:
        print()
        print('--prove: mutating the reader so the suite MUST go red.')
        print('  If any line below reads ok, this harness cannot detect a')
        print('  broken reader and a green result above means nothing.')
        print()
        red = run(mutate='always-zero')
        print()
        if red:
            print('HARNESS PROVEN. The mutant was caught by %d case(s).'
                  % len(red))
            return 0
        print('HARNESS USELESS. The mutant passed every case. Do not trust')
        print('the green result above -- this suite cannot fail.')
        return 1

    print('Run with --prove to verify this suite can go red at all.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
