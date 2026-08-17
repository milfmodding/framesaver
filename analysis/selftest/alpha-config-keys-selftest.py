#!/usr/bin/env python3
"""Selftest for alpha-config-keys.py — proves it can FAIL, and proves it can PASS.

WHY THIS EXISTS, AND WHY IT SHIPPED WITH THE CHECK RATHER THAN AFTER IT
----------------------------------------------------------------------
`ac-crashtest.py` in this same directory CANNOT FAIL, and has been known-broken for days.
protocol-anim-cull.ini declined to add a check for exactly that reason: "adding a check whose
validating harness is incapable of failing would be the defect this file exists to avoid."

So a detector that has only ever been run against a file that trips it has not been shown to detect
anything - it has been shown to print. Case 6 is the one that matters most: a clean file must exit
0. Without it, a checker hardwired to `return 1` passes every other case here.

Mutants are built from the REAL Plugin.cs, so a rename that breaks the check's anchors breaks these
cases too, loudly, instead of leaving the suite green against a fixture nobody updated.

Run:  python analysis/selftest/alpha-config-keys-selftest.py
Exit: 0 all cases discriminate, 1 otherwise.
"""

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
CHECK = os.path.join(ROOT, 'analysis', 'alpha-config-keys.py')
PLUGIN = os.path.join(ROOT, 'Plugin.cs')


def run(text=None):
    """Run the check over Plugin.cs, or over a mutant of it. Returns (exit, stdout)."""
    if text is None:
        path, tmp = PLUGIN, None
    else:
        tmp = tempfile.NamedTemporaryFile('w', suffix='.cs', delete=False, encoding='utf-8')
        tmp.write(text)
        tmp.close()
        path = tmp.name
    try:
        r = subprocess.run([sys.executable, CHECK, path], capture_output=True, text=True)
        return r.returncode, r.stdout
    finally:
        if tmp:
            os.unlink(tmp.name)


def main():
    if not os.path.isfile(PLUGIN):
        print('REFUSED: cannot find Plugin.cs at ' + PLUGIN)
        return 1
    if not os.path.isfile(CHECK):
        print('REFUSED: cannot find the check at ' + CHECK)
        return 1

    with open(PLUGIN, encoding='utf-8', errors='replace') as fh:
        src = fh.read()

    cases = []

    # 1. The real file. Known pre-existing `Enabled` pair, and all three anchors must agree.
    rc, out = run()
    cases.append((
        'REAL Plugin.cs -> reports the known Enabled pair, anchors agree',
        rc == 1 and 'COLLISION  "Enabled"' in out and 'ANCHORS AGREE                : True' in out,
        rc))

    # 2. A NEW collision. This is the case the check exists for.
    mutant = src.replace('"Auto-start protocol at raid start"', '"Run tag"', 1)
    rc, out = run(mutant)
    cases.append((
        'NEW collision injected (Run tag x2) -> CAUGHT',
        rc == 1 and '"Run tag"' in out,
        rc))

    # 3. THE HOLE GAMMA FOUND. A comment between `Config.Bind(` and its section argument, exactly as
    #    at Plugin.cs:130-133. A whitespace-only regex silently drops that entry and reports a clean
    #    count one short. The recovered-pair count must not move.
    mutant = src.replace(
        'ProtocolAutoStart = Config.Bind(\n                "3. Telemetry"',
        'ProtocolAutoStart = Config.Bind(\n                // interposed comment, as at line 130\n                "3. Telemetry"',
        1)
    rc, out = run(mutant)
    m = re.search(r'pairs recovered\s*:\s*(\d+)', out)
    base = re.search(r'pairs recovered\s*:\s*(\d+)', run()[1])
    cases.append((
        'comment between Bind( and section -> entry NOT lost, count unchanged',
        bool(m) and bool(base) and m.group(1) == base.group(1) and 'AGREE                : True' in out,
        rc))

    # 4. A field declared but never bound. BuildEntryMap would find it and read null.
    mutant = src.replace('            ProtocolAutoStart = Config.Bind(',
                         '            if(false) ProtocolAutoStart = NOPE(', 1)
    rc, out = run(mutant)
    cases.append((
        'declared-but-unbound field -> ANCHOR DISAGREEMENT, not a clean report',
        rc == 1 and 'ANCHOR DISAGREEMENT' in out,
        rc))

    # 5. Pointed at the wrong file. Must refuse - "no collisions found" over an empty scan is the
    #    failure mode that reads as success.
    rc, out = run('class X { }')
    cases.append((
        'file with no binds -> REFUSES rather than reporting clean',
        rc == 1 and 'REFUSED' in out,
        rc))

    # 6. THE CONTROL, AND THE LOAD-BEARING CASE. Remove the collision and it must PASS. Without
    #    this, a check hardwired to fail satisfies every case above.
    mutant = src.replace('"1. Bot stand-by", "Enabled"', '"1. Bot stand-by", "Stand-by enabled"', 1)
    rc, out = run(mutant)
    cases.append((
        'CONTROL: collision removed -> exit 0 and says so',
        rc == 0 and 'No bare-name collisions' in out,
        rc))

    ok = True
    for name, passed, rc in cases:
        print(('  PASS  ' if passed else '  FAIL  ') + name + '   (exit %s)' % rc)
        ok &= bool(passed)

    print('')
    if ok:
        print('DISCRIMINATES: it detects a new collision, survives the comment hole, refuses an')
        print('empty scan, and PASSES a clean file. Exit 0 from the check means something.')
        return 0

    print('DOES NOT DISCRIMINATE - do not trust alpha-config-keys.py until these pass.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
