#!/usr/bin/env python3
"""Check whether a built assembly actually contains the fields you think it does.

Usage:  python probe-symbols.py <assembly.dll> <name> [name ...]

Exit 0 if every name is present, 1 otherwise.

**Why this exists rather than `grep -c`.** A .NET assembly stores strings in two
heaps with different encodings:

  #Strings  UTF-8   type, member and field names
  #US       UTF-16  string literals

A telemetry field name like `windowSec` appears ONLY as a literal, so an ASCII
grep returns 0 while the field is present and working. A name like `endToLatch`
happens to match because a member is called `_endToLatchMs`, and `yawSwept`
matches for the same reason while never being a literal at all.

So the ASCII grep this replaces reported presence correctly **only for names that
happened to double as member names**, and reported a confident 0 for the rest. It
was used in deploy declarations, where a false 0 reads as "the feature is not in
the binary" — the strongest possible wrong claim about a build.

Caught when `windowSec` probed 0 in a declaration that had already been sent.
Fifth instrument-saw-nothing failure of 2026-07-28, and the first one inside a
verification tool rather than an analysis.
"""

import sys


def probe(data, name):
    """Return the heaps the name appears in."""
    found = []
    if name.encode("utf-8") in data:
        found.append("#Strings/utf8")
    if name.encode("utf-16-le") in data:
        found.append("#US/utf16")
    return found


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2

    path = argv[1]
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except IOError as exc:
        print(f"  ! {exc}")
        return 2

    print(f"{path}  ({len(data)} bytes)")
    missing = 0
    for name in argv[2:]:
        heaps = probe(data, name)
        if heaps:
            print(f"  ok    {name:24s} {', '.join(heaps)}")
        else:
            print(f"  MISSING {name:22s} in neither heap")
            missing += 1

    print()
    if missing:
        print(f"{missing} name(s) MISSING — the binary does not contain them.")
        return 1

    print(f"all {len(argv) - 2} name(s) present.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
