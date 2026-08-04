#!/usr/bin/env python3
"""Which binary wrote this log?

For any log written after 2026-07-28 the answer is in the header's `commit`
field and this script is unnecessary. It exists for the 7 artifacts and 52 of
55 logs from before that field shipped, where the header names no binary at
all and the deploy record is the only link - and where that record is missing,
nothing joins the log to the code that produced it.

`build-provenance.py` answers the neighbouring question and cannot answer this
one: it reads a commit out of a BINARY. Given a LOG with no commit in it,
there is nothing to read, so the identification has to be reconstructed from
what the log demonstrably contains.

THE THREE LEGS, in the order they eliminate the most:

  1. The header's `commit` key, present or absent. A binary that emits the
     field cannot have written a header lacking it. This is a hard structural
     constraint in the SAFE direction - it argues from something the log HAS
     (or provably has not, since the header is one object we read whole).
  2. Field superset. Every key the log contains must exist as a string in the
     binary's image. A binary missing even one is eliminated. Absence from the
     image is NOT proof a build cannot emit a name (see beta-build-fields.py's
     `semantics` - it is measurably wrong 46 times for the one binary we can
     check), so this leg can over-eliminate, which is why leg 1 goes first and
     why a zero-candidate result is reported as a contradiction rather than as
     an answer.
  3. Build time before log time. Listed last because it is the WEAKEST leg and
     the one most likely to mislead: `mtime` in build-fields.json is the
     artifact FILE's last-write time in UTC, not the PE TimeDateStamp, so for
     a copied artifact it is an upper bound on the build. It also compares
     against a header timestamp carrying a local -07:00 offset. Both are handled
     here, and the leg is reported separately so a reader can discard it.

On `20260728-225956-marathon`, leg 1 alone leaves 21 of 25 candidates and leg 2
alone leaves 4; together they leave exactly one, and leg 3 eliminates nothing.
That is worth knowing before trusting a future run: the identification rests on
the two legs that argue from content, and the timestamp is corroboration.

WHAT IS ACTUALLY DOING THE WORK, because "field superset" oversells it. Run the
header line ALONE and the answer is still unique - 30 keys, one candidate - and
inside those 30, `deferToAiMods` eliminates 20 of the 21 by itself. So this is
not a broad statistical match. It is a two-sided bracket on shipping dates:

    leg 1 bounds from ABOVE   no `commit` in the header -> built before the
                              commit field shipped
    deferToAiMods bounds BELOW  the key is in the log -> built after that
                              config flag shipped

and the answer is unique because those two dates happen to be adjacent. That is
a real identification and a THIN one. A build in that window emitting the same
config set would be indistinguishable, and nothing here would say so - it would
simply report AMBIGUOUS, which is the correct behaviour and the reason the
ambiguous branch prints every survivor rather than picking one.

The corollary for anyone extending this: the discriminating power lives in the
CONFIG BLOCK, whose key names track ConfigEntry names one-for-one and therefore
change whenever a flag is added or removed. Removing a flag is what makes two
builds distinguishable. It is also, separately, what makes an old log's config
block unreadable, so the two properties are the same fact seen twice.

WHAT THE LOG'S KEYS ARE NOT. Two classes are dropped before the join, and both
would otherwise eliminate every candidate:

  - Phase paths (`EarlyUpdate/ARCoreUpdate`) are Unity PlayerLoop marker names
    discovered at runtime and used as dictionary keys. No binary contains them.
    137 of the marathon's 431 keys.
  - Single-character keys (n, t, x, y, z). Real emitted fields that the
    extractor's two-character minimum cannot see. 5 more.

Both were found by running this join and reading the eliminations instead of
the verdict. A candidate list that empties is the tool describing itself.

  attribute-log.py <log.ndjson> [<log.ndjson> ...]

Exit 0 when every log is uniquely attributed, 2 when any is ambiguous, and
1 when any has NO candidate - which is a contradiction between the log and the
field data, never a finding about the log.
"""

import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
FIELDS = os.path.join(HERE, "build-fields.json")


def keys_in(path):
    """Every key in the log, split into the ones that can join and the two
    classes that cannot. Returns (usable, phase_paths, single_char)."""
    found = set()

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                found.add(k)
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    header = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue          # a truncated tail line is normal after a crash
            if header is None and isinstance(obj, dict) and obj.get("type") == "header":
                header = obj
            walk(obj)

    paths = set(k for k in found if "/" in k)
    short = set(k for k in found if len(k) < 2)
    return header, found - paths - short, paths, short


def attribute(path, records):
    header, usable, paths, short = keys_in(path)
    print(os.path.basename(path))
    if header is None:
        print("  CANNOT TELL: no header record")
        return 2

    print("  %d keys = %d joinable + %d phase paths + %d single-char (%s)"
          % (len(usable) + len(paths) + len(short), len(usable), len(paths),
             len(short), ",".join(sorted(short)) or "none"))

    # The easy case, and the one every future log falls into.
    if header.get("commit"):
        print("  header names commit %s - no reconstruction needed"
              % header["commit"][:7])
        return 0

    emits = not (header.get("commit") is None and "commit" not in header)
    leg1 = [r for r in records if bool(r.get("emitsCommitField")) == emits]
    leg2 = [r for r in leg1 if not (usable - set(r.get("fields", [])))]
    print("  leg 1  emitsCommitField == %-5s  %2d of %2d survive"
          % (emits, len(leg1), len(records)))
    print("  leg 2  image contains every key   %2d survive" % len(leg2))

    started = header.get("started")
    if started:
        when = datetime.fromisoformat(started)
        early = [r for r in leg2 if datetime.fromisoformat(r["mtime"]) < when]
        print("  leg 3  file mtime precedes start  %2d survive  (weak - see docstring)"
              % len(early))
    else:
        early = leg2
        print("  leg 3  skipped: header has no `started`")

    if not leg2:
        # The failure that found three extractor defects. Say what it means.
        print("  NO CANDIDATE. The log contains keys no binary image does, so the")
        print("  field data or the archive is incomplete - this is not a finding")
        print("  about the log. Keys with no home:")
        anywhere = set()
        for r in records:
            anywhere |= set(r.get("fields", []))
        for name in sorted(usable - anywhere)[:12]:
            print("      %s" % name)
        return 1

    winners = early or leg2
    if len(winners) > 1:
        print("  AMBIGUOUS between %d:" % len(winners))
        for r in winners:
            print("      %-9s %s" % ((r.get("commit") or "-")[:7], os.path.basename(r["dll"])))
        return 2

    r = winners[0]
    print("  %s  commit %s" % (r["md5"], (r.get("commit") or "unstamped")[:7]))
    print("  %s" % r["dll"])
    if not early:
        print("  NOTE: leg 3 eliminated it. Content says yes, timestamp says no -")
        print("  check whether the artifact was copied after it was built.")
    return 0


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__.strip())
        return 2
    try:
        with open(FIELDS, encoding="utf-8") as fh:
            records = json.load(fh)["records"]
    except (OSError, ValueError, KeyError) as exc:
        print("CANNOT TELL: %s unreadable (%s). Regenerate with "
              "beta-build-fields.py." % (FIELDS, exc))
        return 2

    rc = 0
    for path in argv:
        try:
            got = attribute(path, records)
        except OSError as exc:
            print("%s\n  CANNOT TELL: %s" % (path, exc))
            got = 2
        rc = max(rc, got) if got != 1 else 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
