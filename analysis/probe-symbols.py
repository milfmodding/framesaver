#!/usr/bin/env python3
"""Check whether a built assembly actually contains the fields you think it does.

Usage:  python probe-symbols.py <assembly.dll> <name> [name ...]
        python probe-symbols.py --key <assembly.dll> <key> [key ...]

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

**--key EXISTS BECAUSE THE FIX ABOVE LEFT A HOLE THE SAME SHAPE.** Presence in
either heap answers "is this string in the binary", which is NOT the question a
deploy declaration asks. It asks "will this key appear on a line". A member named
`_brainsTickedSum` puts `brainsTicked` in #Strings, so the default mode answers
`ok` for a key that is emitted nowhere — a false PASS this time, where the grep it replaced
gave false FAILs. Found by Gamma on 2026-07-28, one level up from the failure this
file was written for, and inside the same tool.

**An emitted JSON key must appear in #US/utf16**, because that is where the string
literal written to the line lives. A #Strings-only match is a member name and
proves nothing about the output. So `--key` passes only on a #US/utf16 match and
says explicitly when it is refusing a member-name-only match.

Use `--key` for anything you expect to read back out of an ndjson. Use the default
mode for methods, types and members — `ResetForRaid` is correctly #Strings-only.
"""

import sys

# The refusal line carries an em-dash and a default Windows console is cp1252,
# which turns it into a replacement byte. A verification tool whose failure output
# is mojibake is harder to read at exactly the moment it matters.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def probe(data, name):
    """Return the heaps the name appears in."""
    found = []
    if name.encode("utf-8") in data:
        found.append("#Strings/utf8")
    if name.encode("utf-16-le") in data:
        found.append("#US/utf16")
    return found


def main(argv):
    args = argv[1:]
    key_mode = False
    if args and args[0] == "--key":
        key_mode = True
        args = args[1:]

    if len(args) < 2:
        print(__doc__)
        return 2

    path = args[0]
    names = args[1:]
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except IOError as exc:
        print(f"  ! {exc}")
        return 2

    print(f"{path}  ({len(data)} bytes)"
          f"{'   [--key: literal required]' if key_mode else ''}")
    missing = 0
    for name in names:
        heaps = probe(data, name)
        literal = "#US/utf16" in heaps
        if key_mode and not literal:
            if heaps:
                # The distinction that matters, stated rather than implied: this
                # is not absence, it is a member name being mistaken for output.
                print(f"  NOT A KEY {name:20s} {', '.join(heaps)} only — a "
                      f"member name, not an emitted literal")
            else:
                print(f"  MISSING {name:22s} in neither heap")
            missing += 1
        elif heaps:
            print(f"  ok    {name:24s} {', '.join(heaps)}")
        else:
            print(f"  MISSING {name:22s} in neither heap")
            missing += 1

    print()
    if missing:
        what = "key(s) not emitted" if key_mode else "name(s) MISSING"
        print(f"{missing} {what} — do not declare these as present.")
        return 1

    print(f"all {len(names)} {'key(s)' if key_mode else 'name(s)'} present.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
