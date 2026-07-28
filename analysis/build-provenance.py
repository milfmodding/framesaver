#!/usr/bin/env python3
"""Which commit is this Framesaver.dll built from?

The freeze protocol identifies binaries by md5, and on 2026-07-28 that
produced three hashes from source with no .cs difference. The cause is
not nondeterminism: the SDK stamps the current git commit into
AssemblyInformationalVersion, so the assembly embeds "0.1.0+<sha>" in
both the metadata blob heap and the Win32 version resource. Any commit
by anyone -- a docs commit, a coordination note -- changes the binary's
hash without changing a byte of IL.

That makes md5 the wrong identity check for "same behaviour" and makes
the filename the wrong place to record provenance. The binary already
knows which commit it came from. Ask it.

  build-provenance.py <dll> [<dll> ...]   report each one's commit
  build-provenance.py --compare <a> <b>   same source or not

Exit 0 if all inputs are readable and, under --compare, from the same
commit. Exit 1 on a real difference, 2 when it cannot tell -- an
unparseable input is an error, never a verdict, because "cannot tell"
and "differs" have opposite consequences for a freeze.

WHAT THE STAMP DOES NOT TELL YOU, and it is the whole reason a freeze
still needs discipline: the SDK records HEAD at build time, not the
content of the working tree. A build from a dirty tree carries the same
stamp as a build from a clean one. The 403b1aeb artifact reports commit
3bf008f and its Telemetry.cs matched no commit -- one agent had saved
into the file between the build and the commit.

So the stamp answers "which commit was checked out" and never "was this
tree clean". It is necessary and not sufficient. The sufficient version
is ordering: commit, then build, then record -- which makes the binary
correspond to a commit by construction instead of by timing.
"""

import re
import subprocess
import sys

# 0.1.0+<40 hex>. Anchored on the AssemblyVersion the csproj sets, so a
# stray hex run elsewhere in the image cannot match.
STAMP = re.compile(rb'\d+\.\d+\.\d+\+[0-9a-f]{40}')


def stamps(data):
    """Every version stamp in the image, from both encodings.

    The blob heap holds it as UTF-8 and the Win32 version resource as
    UTF-16LE. Reading only one would work today and break the day a
    build stops emitting that one, which is the failure mode of every
    single-source check in this project so far."""
    found = set(m.decode('ascii') for m in STAMP.findall(data))
    # Drop every other byte to read UTF-16LE as if it were ASCII. Cheaper
    # than a real decode and cannot raise on the non-text parts.
    for m in STAMP.findall(data[0::2]):
        found.add(m.decode('ascii'))
    for m in STAMP.findall(data[1::2]):
        found.add(m.decode('ascii'))
    return sorted(found)


def describe(sha, repo):
    """Resolve a sha against the repo, if we are in one."""
    try:
        out = subprocess.run(['git', '-C', repo, 'log', '--oneline', '-1', sha],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
        return 'NOT A COMMIT IN THIS REPO'
    except (OSError, subprocess.SubprocessError):
        return 'git unavailable'


def read(path):
    with open(path, 'rb') as fh:
        return fh.read()


def report(paths, repo):
    rc = 0
    for path in paths:
        try:
            found = stamps(read(path))
        except OSError as exc:
            print('%s\n  CANNOT TELL: %s' % (path, exc))
            rc = 2
            continue
        print(path)
        if not found:
            # Not a failure of the binary: a build with no SourceRevisionId
            # simply has nothing to report, and saying so beats inventing it.
            print('  no version stamp found -- not built with a commit id')
            rc = max(rc, 2)
            continue
        if len(found) > 1:
            print('  MULTIPLE stamps, which should be impossible: %s'
                  % ', '.join(found))
            rc = 1
            continue
        version, sha = found[0].split('+')
        print('  version %s  commit %s' % (version, sha[:12]))
        print('  %s' % describe(sha, repo))
    return rc


def compare(a, b, repo):
    try:
        da, db = read(a), read(b)
    except OSError as exc:
        print('CANNOT TELL: %s' % exc)
        return 2

    sa, sb = stamps(da), stamps(db)
    if len(sa) != 1 or len(sb) != 1:
        print('CANNOT TELL: expected one version stamp each, got %d and %d'
              % (len(sa), len(sb)))
        return 2

    if sa[0] != sb[0]:
        print('DIFFERENT COMMITS')
        for path, stamp in ((a, sa[0]), (b, sb[0])):
            sha = stamp.split('+')[1]
            print('  %-52s %s' % (path, sha[:12]))
            print('  %-52s %s' % ('', describe(sha, repo)))
        print('\nmd5 would also differ, and would not tell you why.')
        return 1

    sha = sa[0].split('+')[1]
    print('SAME COMMIT %s' % sha[:12])
    print('  %s' % describe(sha, repo))

    if da == db:
        print('  and byte-identical.')
        return 0

    # Same commit, different bytes. Report it rather than ruling on it:
    # the remaining volatile fields are the timestamp, MVID and debug
    # directory, and enumerating them was tried and abandoned -- a
    # blocklist of what does not matter can only omit.
    n = sum(1 for x, y in zip(da, db) if x != y) + abs(len(da) - len(db))
    print('  but %d bytes differ at sizes %d and %d.' % (n, len(da), len(db)))
    print('  Expected for two builds of one commit: timestamp, MVID and')
    print('  debug directory move. Not a behaviour difference by itself.')
    return 0


def main():
    argv = sys.argv[1:]
    repo = '.'
    if argv and argv[0] == '--repo':
        repo = argv[1]
        argv = argv[2:]
    if argv and argv[0] == '--compare':
        if len(argv) != 3:
            print('usage: build-provenance.py [--repo D] --compare <a> <b>')
            return 2
        return compare(argv[1], argv[2], repo)
    if not argv:
        print(__doc__.strip())
        return 2
    return report(argv, repo)


if __name__ == '__main__':
    sys.exit(main())
