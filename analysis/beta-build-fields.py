#!/usr/bin/env python3
"""Emit one record per Framesaver binary we can reach: identity, and the set of
telemetry field names its emit code contains.

WHY THIS EXISTS. A log header carries `version` and `commit`, and `commit` is
blank on 52 of 55 logs across the two installs - for two distinct reasons that
no log distinguishes (the assembly was never stamped, or it was stamped and the
header had no field to put it in; both landed 2026-07-28, hours apart). So a
log cannot name the binary that wrote it, and a reader asking "is this field
absent because the raid produced nothing, or because this build could not emit
it?" has nothing to join on.

This replaces that inference with a measurement.

WHAT A NAME IN THE OUTPUT MEANS, because the asymmetry is the whole value:

    present  ->  the EMIT CODE EXISTS in that binary. NOT that it ever fired.
                 An upper bound, and a weak one.
    absent   ->  STRUCTURAL. No raid, no config and no map could have produced
                 that field from this binary.

Absence is the strong direction, which is precisely the direction the
absent-versus-zero question needs. Same argument as probe-symbols.py's
docstring: a false zero is the strongest possible wrong claim about a build.

THE JOIN, AND ITS LIMIT. Records are keyed by md5 and tagged with the install
directory when the binary is currently installed in one, so a reader can go
directory -> binary -> field set. That join is SOUND FOR `Base`, which appears
to have carried one binary throughout. It is NOT sound for `SPT4.0.13`: the
binary installed there today is not the one that wrote most of its logs. For
those, the `artifacts/` records bracket the answer - a log from 2026-07-28 was
written by one of them - and `intersection` in the summary is the set every one
of them could emit.

Deliberately does NOT assume the field sets are nested, and they are NOT:
`findingNestedFieldSets` is false, with the breaks named in `nestingBreaks`.
I claimed "strict subset, nothing has ever been removed" from two binaries an
hour before writing this; it was already false, because I had removed
cfg.fastAnim myself that afternoon. A file resting on that premise would have
been wrong on its first run while still answering confidently.

Usage:  python beta-build-fields.py > build-fields.json
"""

import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALLS = {
    "Base": r"F:\SPT\Base\BepInEx\plugins\Framesaver.dll",
    "SPT4.0.13": r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver.dll",
}

# A JSON key as this codebase emits them: lowercase initial, then word chars.
# Matched against `"name":` because that is the literal shape in the #US heap.
KEY = re.compile(r'"([a-z][A-Za-z0-9]{1,40})":')


def field_names(blob):
    """Field names in a .NET #US heap.

    Byte-level UTF-16 decode from BOTH parities. #US literals are UTF-16 but
    carry no alignment guarantee relative to the file start, so decoding only
    from offset 0 silently misses every literal at an odd offset - a failure
    that looks exactly like a missing field, which is the reading this whole
    file exists to make impossible.
    """
    names = set()
    for start in (0, 1):
        names |= set(KEY.findall(blob[start:].decode("utf-16-le", "ignore")))
    return names


def product_version(path):
    """Win32 ProductVersion, which is where the SDK writes
    AssemblyInformationalVersion - so `0.1.0` means unstamped and
    `0.1.0+<sha>` means SourceLink produced a revision id at build time."""
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-Item '%s').VersionInfo.ProductVersion" % path],
            capture_output=True, text=True, timeout=60)
        return out.stdout.strip() or None
    except Exception:
        return None


def record(path, install=None):
    blob = open(path, "rb").read()
    ver = product_version(path)
    return {
        "dll": path,
        "install": install,
        "md5": hashlib.md5(blob).hexdigest(),
        "bytes": len(blob),
        "mtime": datetime.fromtimestamp(
            os.path.getmtime(path), timezone.utc).isoformat(),
        "productVersion": ver,
        "commit": ver.split("+", 1)[1] if ver and "+" in ver else None,
        # Distinct from `commit`: whether the binary can PUT a commit in a log
        # header at all. The two blank-commit causes differ exactly here.
        "emitsCommitField": '"commit":' in blob.decode("utf-16-le", "ignore")
                            or '"commit":' in blob[1:].decode("utf-16-le", "ignore"),
        "fields": sorted(field_names(blob)),
    }


def main():
    records = []
    for name, path in sorted(INSTALLS.items()):
        if os.path.exists(path):
            records.append(record(path, install=name))
        else:
            print("missing install binary: %s" % path, file=sys.stderr)

    for path in sorted(glob.glob(os.path.join(MOD, "artifacts", "*.dll"))):
        records.append(record(path))

    built = os.path.join(MOD, "bin", "Release", "Framesaver.dll")
    if os.path.exists(built):
        records.append(record(built))

    if not records:
        print("no binaries reachable - refusing to emit an empty corpus",
              file=sys.stderr)
        return 2

    sets = [frozenset(r["fields"]) for r in records]
    union = set().union(*sets)
    inter = set(sets[0]).intersection(*sets)

    # Reported, never assumed - and it reads FALSE, which is why it is reported.
    # I claimed "strict subset, nothing has ever been removed" from two binaries
    # an hour before writing this, and it was already untrue: I had removed
    # cfg.fastAnim myself the same afternoon. The breaks are named rather than
    # summarised, because "not nested" is useless and "role vanished between two
    # same-size 28 July artifacts" is a fact about how those builds were made.
    ordered = sorted(records, key=lambda r: len(r["fields"]))
    breaks = []
    for i in range(len(ordered) - 1):
        smaller = set(ordered[i]["fields"])
        larger = set(ordered[i + 1]["fields"])
        lost = sorted(smaller - larger)
        if lost:
            breaks.append({
                "from": os.path.basename(ordered[i]["dll"]),
                "fromMd5": ordered[i]["md5"],
                "to": os.path.basename(ordered[i + 1]["dll"]),
                "toMd5": ordered[i + 1]["md5"],
                "dropped": lost,
            })

    json.dump({
        "generatedBy": "analysis/beta-build-fields.py",
        "semantics": {
            "present": "the emit code exists in this binary; NOT that it fired",
            "absent": "structural - no raid or config could produce it here",
            "join": "directory -> binary is sound for Base (one binary "
                    "throughout) and NOT for SPT4.0.13, whose installed binary "
                    "is not the one that wrote most of its logs",
        },
        "binaries": len(records),
        "fieldsUnion": sorted(union),
        "fieldsInEveryBinary": sorted(inter),
        "findingNestedFieldSets": not breaks,
        "nestingBreaks": breaks,
        "records": records,
    }, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
