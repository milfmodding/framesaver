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

    absent from `fields`  ->  STRUCTURAL. No raid, no config and no map could
                              have produced it from this binary. The strong
                              direction, and the only one to read.
    present in `fields`   ->  the string exists in the image. Deliberately
                              OVER-collected, so not proof it is a field.
    present in `fieldsAsJsonKeys` -> definitely emitted as a JSON key. Precise,
                              but INCOMPLETE - never read ITS absence.

**The first version of this file got that backwards and shipped.** It matched
`"name":` only, which misses every block emitted through Telemetry's `Block()`
helper, where the literal is the bare word. `aiTotal`, `ambientLight` and
`asyncDrained` are emitted by the CURRENT build and were reported absent from
it. A file built to make "absent means structural" trustworthy was
manufacturing false absences - the exact failure, inside the fix for it.

Caught by trying to identify which artifact wrote a known log: the answer came
back "no candidate", including the binary that certainly could have. A tool
that cannot find a right answer it has been handed is saying something about
itself. Same argument as probe-symbols.py's docstring - a false zero is the
strongest possible wrong claim about a build.

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
import urllib.request
from datetime import datetime, timezone

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Log directories whose binary is known 1:1, so keys observed there are GROUND
# TRUTH for what that binary emits. Only Base qualifies: it carried one binary
# throughout. SPT4.0.13's installed binary did not write most of its logs.
GROUND_TRUTH_LOGS = {
    "Base": r"F:\SPT\Base\BepInEx\plugins\Framesaver-logs\*.ndjson",
}
INSTALLS = {
    "Base": r"F:\SPT\Base\BepInEx\plugins\Framesaver.dll",
    "SPT4.0.13": r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver.dll",
}

# A JSON key as this codebase emits them: lowercase initial, then word chars.
# Matched against `"name":` because that is the literal shape in the #US heap.
KEY = re.compile(r'"([a-z][A-Za-z0-9]{1,40})":')
# Two characters minimum, not three. The first cut required three and so
# reported `aa`, `at`, `gc` and `ms` absent from every binary - four real
# emitted fields, four more false absences, found the same way as the last
# batch: by asking the tool a question whose answer was nearly known.
TOKEN = re.compile(r'[A-Za-z][A-Za-z0-9]{1,40}')


def _decodes(blob):
    """Byte-level UTF-16 decode from BOTH parities. #US literals are UTF-16 but
    carry no alignment guarantee relative to the file start, so decoding only
    from offset 0 silently misses every literal at an odd offset."""
    return (blob.decode("utf-16-le", "ignore"),
            blob[1:].decode("utf-16-le", "ignore"))


def field_names(blob):
    """Every identifier-shaped string in the image. The CONSERVATIVE set, and
    it must stay conservative, because absence is the only direction anyone
    reads.

    **The first version of this matched `"name":` only, and was wrong in the
    dangerous direction.** Telemetry emits most blocks through a helper -
    `Block(sb, "aiTotal", _aiTotal)` - so the literal in the assembly is the
    bare word and the quotes are added at runtime. `aiTotal`, `ambientLight`
    and `asyncDrained` are emitted by the CURRENT build and the quoted-only
    scan reported all three absent from it. A file whose entire purpose is
    "absent means structural" was manufacturing false absences.

    Over-collecting is the safe error and is now deliberate: a string in the
    image that is not a field weakens `present`, which was already only an
    upper bound. `mods` is a known instance - it appears in the Base image and
    in none of Base's 30 logs. Use `fieldsAsJsonKeys` when you need the strong
    form of presence.
    """
    names = set()
    for text in _decodes(blob):
        names |= set(TOKEN.findall(text))
    return names


def json_key_names(blob):
    """Names appearing as a complete `"name":` literal - definitely emitted as
    a JSON key. Precise but INCOMPLETE for the helper-emitted blocks above, so
    never use its absence for anything."""
    names = set()
    for text in _decodes(blob):
        names |= set(KEY.findall(text))
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


# Prose that records deploys. COORDINATION.md is append-only, so an md5 in it
# is evidence a build shipped. Absence is NOT evidence it did not: 7 artifacts
# exist without one, and artifacts are taken AT deploy time - so the record is
# incomplete and `deployed` has three values for that reason and not for
# tidiness.
#
# THESE ARE READ FROM THE AKHASHIC RECORD, NOT FROM DISK (Sophia, 2026-08-04:
# the Record is canonical, the filesystem is a cache). The previous version
# read them from MOD and SKIPPED any that were missing, silently - which turned
# "the documents moved" into `deployed: null` on builds that had certainly
# shipped, wearing the message "no record found, and the record is known to be
# incomplete". A wrong answer that arrives pre-excused by its own tool is worse
# than a crash, so a document that cannot be fetched is now a REFUSAL.
DEPLOY_RECORD = ["COORDINATION.md", "FINDINGS.md", "TESTING.md",
                 "COMPATIBILITY.md", "README.md"]
DEPLOY_RECORD_PREFIX = "framesaver/shared/docs/"


def refuse(reason):
    """First line names it, exit code carries it. Neither half suffices alone:
    18 exit-2 sites in this tree print no distinctive token, and errno text
    from a real refusal is indistinguishable from CPython failing to find the
    script at all. 86 sits in the unclaimed band and nothing wraps to it.
    """
    print("REFUSED: %s" % reason, file=sys.stderr)
    sys.exit(86)


def call_record(tool, args):
    """One JSON-RPC call to the Record. Raises on anything unexpected.

    The token is per-agent and comes from the environment; it is deliberately
    not in this file, so the script is the same for every seat that runs it.
    """
    token = os.environ.get("RECORD_TOKEN")
    url = os.environ.get("RECORD_URL")
    if not token or not url:
        # NOT a fallback to .mcp.json. A fallback here would reintroduce the
        # exact defect this function was written to remove: a run that quietly
        # sources different bytes than the operator believes it did.
        refuse("RECORD_TOKEN and RECORD_URL must both be set in the "
               "environment; refusing to guess where the Record is")

    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    with urllib.request.urlopen(req, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    if "error" in body:
        raise RuntimeError(json.dumps(body["error"])[:300])
    return json.loads(body["result"]["content"][0]["text"])


def fetch_document(path):
    doc = call_record("read_document", {"path": path})
    text = doc.get("body")
    if text is None:
        # `found: false` and FORBIDDEN are different answers and the Record
        # says which. Either way this script has no business continuing.
        raise RuntimeError("no body at %s: %s" % (path, json.dumps(doc)[:200]))
    return text


def fetch_deploys():
    """Deploys recorded on purpose, as register rows. Returns {id: haystack}.

    THE CONVENTION, and it is the whole interface: a deploy is a DECISION row
    whose summary carries the binary's full 32-character md5. A decision is the
    right kind because a deploy already has to answer what the register demands
    of one - why it shipped, and the command that puts the old binary back - and
    those are written BEFORE the deploy rather than reconstructed after it.

    Why this beats grepping prose, which is what it supersedes: the register is
    append-only and scoped, so a row cannot be quietly edited or tidied away,
    and `at`/`by` come from the store rather than from whoever remembered to
    type them. The prose search stays for everything deployed before this
    existed - history cannot be backfilled honestly, so it is not.
    """
    rows = call_record("read_register", {"kind": "decision"}).get("entries")
    if rows is None:
        raise RuntimeError("read_register returned no entries list")
    # `why` and `undo` are searched too: a row naming the md5 only in its undo
    # command ("copy <md5>.dll back") is still a deploy somebody recorded, and
    # refusing to see it would be pedantry that costs a true positive.
    return {r["id"]: " ".join(str(r.get(f) or "")
                              for f in ("summary", "why", "undo", "artefact"))
            for r in rows}


def deploy_status(path, md5, install, docs, deploys):
    """Was this binary ever in an install, and how do we know.

    Gamma asked for `wroteLogs`. This says `deployed`, because that is what is
    measurable - whether anyone then PLAYED a raid on it is recorded nowhere,
    so `wroteLogs` would be an inference wearing a measurement's name.

    THREE SOURCES, IN DESCENDING ORDER OF WHAT THEY PROVE. The install is the
    binary itself. The register is a row somebody wrote ON PURPOSE at deploy
    time. The prose is an md5 that happens to appear in a document, which is
    why it was always evidence rather than proof.
    """
    if install:
        return True, "currently installed in %s" % install
    registered = [rid for rid, row in deploys.items() if md5 in row]
    if registered:
        # Full md5 only. The prose search below also accepts the 8-character
        # prefix because that is how humans wrote it in running text; a
        # register row is written by procedure and has no excuse for a short
        # form, and 8 hex characters would collide across a long enough corpus.
        return True, "registered deploy " + ", ".join(sorted(registered))
    named = [d for d in docs if md5[:8] in docs[d] or md5 in docs[d]]
    if named:
        return True, "md5 named in " + ", ".join(sorted(named))
    if os.path.basename(os.path.dirname(path)).lower() == "release":
        # The only case callable false. It is stamped with the current HEAD,
        # its md5 matches neither install, and no announcement names it - and
        # byte-identical .NET builds do not recur, since the MVID differs per
        # compile. This is also the case that produces the slack Gamma found:
        # animCulledEngine exists ONLY here, so leaving it "unknown" keeps a
        # field in the bracket that no log-writing binary could ever emit.
        return False, "build output; matches no install and no record names it"
    return None, "no record found, and the record is known to be incomplete"


def observed_keys(pattern):
    """JSON keys actually present in logs. The only complete source there is."""
    keys = set()
    for path in glob.glob(pattern):
        with open(path, encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                keys |= set(KEY.findall(line))
    return keys


def record(path, install=None, docs=None, deploys=None):
    blob = open(path, "rb").read()
    ver = product_version(path)
    deployed, why = deploy_status(path, hashlib.md5(blob).hexdigest(),
                                  install, docs or {}, deploys or {})
    return {
        "dll": path,
        "install": install,
        "deployed": deployed,
        "deployedEvidence": why,
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
        # Ground truth where the binary-to-logs join is 1:1. PROVES emission,
        # unlike anything read out of the image - and measures how badly the
        # image under-reports: 49 of these are absent from `fields`.
        "fieldsObservedInLogs": sorted(
            observed_keys(GROUND_TRUTH_LOGS[install])) if install in GROUND_TRUTH_LOGS else None,
        "fieldsAsJsonKeys": sorted(json_key_names(blob)),
    }


def main():
    docs = {}
    for name in DEPLOY_RECORD:
        path = DEPLOY_RECORD_PREFIX + name.lower()
        try:
            docs[name] = fetch_document(path).lower()
        except Exception as exc:
            # EVERY name in DEPLOY_RECORD is load-bearing: an md5 found in any
            # one of them is what makes `deployed` true. Continuing without one
            # produces a clean, well-formed, wrong corpus, so this stops.
            refuse("cannot read %s from the Record: %s" % (path, exc))

    try:
        deploys = fetch_deploys()
    except Exception as exc:
        # Same rule as the documents. An unreachable register is not an empty
        # one, and treating it as empty would silently demote every deploy
        # recorded since the procedure changed - the identical defect this
        # script was just repaired for, one source along.
        refuse("cannot read the register from the Record: %s" % exc)

    records = []
    for name, path in sorted(INSTALLS.items()):
        if os.path.exists(path):
            records.append(record(path, install=name, docs=docs, deploys=deploys))
        else:
            print("missing install binary: %s" % path, file=sys.stderr)

    for path in sorted(glob.glob(os.path.join(MOD, "artifacts", "*.dll"))):
        records.append(record(path, docs=docs, deploys=deploys))

    built = os.path.join(MOD, "bin", "Release", "Framesaver.dll")
    if os.path.exists(built):
        records.append(record(built, docs=docs, deploys=deploys))

    if not records:
        print("no binaries reachable - refusing to emit an empty corpus",
              file=sys.stderr)
        return 2

    sets = [frozenset(r["fields"]) for r in records]
    keysets = [frozenset(r["fieldsAsJsonKeys"]) for r in records]
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
            "fields": "identifier-shaped strings in the image. ABSENT MEANS "
                      "'NOT FOUND IN THE IMAGE', WHICH IS NOT 'STRUCTURAL'. "
                      "This entry claimed structural until it was checked "
                      "against Base's 30 logs, where 46 keys that binary "
                      "demonstrably emitted are absent from its image "
                      "(brainsTicked, poolSize, worldUpdate, spikes, "
                      "worstCallback...). Some names are never string literals "
                      "at all - an exact #US heap parse misses them too - so no "
                      "static scan can be complete. PRESENT means the string "
                      "exists, not that it is a field. See fieldsObservedInLogs "
                      "on each record for the only source that proves emission. "
                      "A SECOND known-false-absence class, found 2026-08-03 by "
                      "attribute-log.py: TOKEN requires two characters, so the "
                      "single-char keys n, t, x, y and z are absent from every "
                      "record while appearing in the logs. Widening the regex "
                      "would admit every stray letter in the image and buy "
                      "nothing, since absence is already not proof - so callers "
                      "exclude names shorter than two characters from any join "
                      "rather than reading them as structural.",
            "fieldsAsJsonKeys": "complete \"name\": literals - definitely "
                                "emitted as a key, but INCOMPLETE, so never "
                                "read its absence for anything",
            "whichSetToUse": "POSITIVE ('this build emits it'): "
                             "jsonKeysInEveryBinary, or fieldsObservedInLogs "
                             "where present - both prove emission. NEGATIVE: "
                             "there is NO set here that proves a field is "
                             "impossible. Absence from fieldsUnion is evidence, "
                             "not proof, and is measurably wrong 46 times for "
                             "the one binary we can check. State it as 'not "
                             "found in any image' and let the reader decide.",
            "join": "directory -> binary is sound for Base (one binary "
                    "throughout) and NOT for SPT4.0.13, whose installed binary "
                    "is not the one that wrote most of its logs",
        },
        "binaries": len(records),
        "fieldsUnion": sorted(union),
        # The bracket Gamma's middle state should use. fieldsUnion spans every
        # binary reachable on disk INCLUDING ones that never shipped, so a field
        # existing only in bin/Release lands in it and "unknown" then reads as
        # "possibly present" for something no log-writing binary could emit.
        # This drops only records proven never deployed; `deployed: null` stays
        # in, because the deploy record is incomplete and unknown must not be
        # silently treated as no.
        "fieldsUnionDeployed": sorted(set().union(*[
            set(r["fields"]) for r in records if r["deployed"] is not False])),
        # DO NOT use fieldsInEveryBinary as a "definitely emitted" test. Since
        # `fields` was widened to kill the false absences, it holds every
        # identifier-shaped string in the image - class names, log-message
        # words, hex - so a short field name can match a method rather than an
        # emit. Gamma found this by wiring a True branch to it.
        "fieldsInEveryBinary": sorted(inter),
        # Use THESE for a positive test. Intersection of the strong sets: a
        # name here appears as a complete `"name":` literal in every binary, so
        # every candidate can emit it as a key. Absence proves nothing.
        "jsonKeysUnion": sorted(set().union(*keysets)),
        "jsonKeysInEveryBinary": sorted(set(keysets[0]).intersection(*keysets)),
        "findingNestedFieldSets": not breaks,
        "nestingBreaks": breaks,
        "records": records,
    }, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
