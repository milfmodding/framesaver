"""
Framesaver/Ranger ndjson -> Argos importer.

DESIGN, decided against real sample lines (header/spike/sample/botSpawn/
botStandBy/botActive/botWindow/mark/death) pulled from a real split-verify
raid log:

  - Ranger's ndjson has no native trace.id/span concept yet (no explicit
    span ids anywhere in the file). Building a synthetic span tree (e.g.
    window-as-span, bot-lines-as-children) would be an invention layered
    on top of data that doesn't carry it, and Argos's own operator (Eris)
    said flatter is fine: "everything still lands, you just get less tree
    structure and more flat rows, which is still fine for historical/
    cross-session SQL analysis." So v1 deliberately does NOT try to fake
    spans.

  - One ndjson line -> one Argos event row, event.name = the line's own
    "type" field (header/spike/sample/botSpawn/...). Simple, correct,
    directly queryable via event_name = 'sample' etc.

  - meta.timestamp: derived, not native. Most lines carry qpc (a raw
    perf-counter tick, meaningless without qpcFrequency) and/or `t`
    (seconds since the file's own sampling start), not a wall-clock
    string. The header's own "started" field IS an absolute ISO
    timestamp - so timestamp = started + t seconds, computed per line.
    Lines with no `t` (rare) fall back to the header's `started` value
    itself rather than being dropped.

  - Everything else (the entire original line) goes into `attrs` as one
    JSON blob - nothing is discarded, nothing is renamed. This costs
    nothing per Argos's own contract (unknown keys become typed columns
    or land in attrs, still queryable via attrs->>'your_key').

  - **DO NOT wrap the extra fields in your own "attrs": {...} key.**
    Argos already promotes every unknown top-level key into its own attrs
    column automatically. Sending a literal "attrs" key double-nests it
    (confirmed against a real ingested row: query came back
    attrs->'attrs'->>'x' instead of attrs->>'x'). This script sends every
    field flat at the top level and lets Argos do the wrapping.

  - Every imported row also gets source_file / source_tag / source_commit
    (from the ndjson filename + its own header line) so a query can filter
    to one Framesaver run without cross-referencing anything else.

Requires ARGOS_URL and ARGOS_TOKEN in the environment (never hardcode the
token - it is a live shared operator credential, expected to cycle).

Verified 2026-08-19: dry-run, then a real small batch, round-tripped via a
query against the flat attrs path, confirmed correct field values, test
rows cleaned up afterward. Full-file/backfill runs should follow the same
dry-run-first discipline before ever pointing this at the whole corpus of
raid logs on disk.
"""
import argparse
import datetime
import json
import os
import sys
import urllib.request
import urllib.error

BASE = os.environ.get("ARGOS_URL", "http://argos.tfw.internal/").rstrip("/") + "/"
TOKEN = os.environ.get("ARGOS_TOKEN")
BATCH_SIZE = 2000  # one POST per this many lines, so a full raid log is several
                   # requests rather than one multi-MB body


def iso_from_header_started(started_str):
    # BepInEx/Framesaver writes "started" as .NET's "o" round-trip format,
    # e.g. "2026-08-17T00:49:24.8494822-07:00" - Python's fromisoformat
    # chokes on 7-digit fractional seconds (only accepts up to 6), so
    # truncate to microseconds before parsing.
    s = started_str
    if "." in s:
        head, rest = s.split(".", 1)
        # rest is fractional seconds + optional timezone offset
        for i, c in enumerate(rest):
            if c in "+-Z":
                frac, tz = rest[:i], rest[i:]
                break
        else:
            frac, tz = rest, ""
        frac = (frac + "000000")[:6]
        s = head + "." + frac + tz
    return datetime.datetime.fromisoformat(s)


def convert_file(path, run_tag_override=None):
    """Yields one Argos event dict per ndjson line."""
    started = None
    source_commit = None
    fname = os.path.basename(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception as e:
                print(f"  SKIP line {lineno}: parse error {e}", file=sys.stderr)
                continue

            if obj.get("type") == "header":
                started = iso_from_header_started(obj.get("started", ""))
                source_commit = obj.get("commit", "")

            t = obj.get("t")
            if started is not None and isinstance(t, (int, float)):
                ts = started + datetime.timedelta(seconds=t)
            elif started is not None:
                ts = started
            else:
                # No header seen yet (shouldn't happen - header is always
                # line 1) and no usable clock. Skip rather than guess.
                print(f"  SKIP line {lineno}: no timestamp basis yet", file=sys.stderr)
                continue

            # See the module docstring: fields go flat at the top level,
            # never wrapped in a literal "attrs" key - Argos does that
            # wrapping itself for unknown keys.
            row = dict(obj)
            row["source_file"] = fname
            row["source_tag"] = run_tag_override or obj.get("tag") or ""
            row["source_commit"] = source_commit or ""
            row["meta.timestamp"] = ts.isoformat()
            row["event.name"] = obj.get("type", "unknown")

            yield row


def post_batch(rows):
    if not TOKEN:
        raise SystemExit("ARGOS_TOKEN not set in environment")
    payload = "\n".join(json.dumps(r) for r in rows) + "\n"
    req = urllib.request.Request(
        BASE + "v1/events",
        data=payload.encode("utf-8"),
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/x-ndjson",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read().decode()


def post_all(rows):
    """POSTs in BATCH_SIZE chunks, reporting each. Stops and raises on the
    first failed batch rather than silently skipping ahead - a partial
    import that looks complete is worse than one that visibly stopped."""
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]
        status, body = post_batch(chunk)
        print(f"  batch {i}-{i + len(chunk)}: status={status} body={body.strip()}")
        if status != 202:
            raise SystemExit(f"batch starting at line {i} failed, stopping")
        total += len(chunk)
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="ndjson file to import")
    ap.add_argument("--limit", type=int, default=0, help="max lines to import, 0=all")
    ap.add_argument("--dry-run", action="store_true", help="print rows, do not POST")
    args = ap.parse_args()

    rows = []
    for i, row in enumerate(convert_file(args.path)):
        if args.limit and i >= args.limit:
            break
        rows.append(row)

    print(f"Converted {len(rows)} rows from {args.path}")
    if args.dry_run:
        for r in rows[:5]:
            print(json.dumps(r)[:400])
        if len(rows) > 5:
            print(f"... and {len(rows) - 5} more (dry-run, nothing sent)")
        return

    total = post_all(rows)
    print(f"Imported {total} rows total")


if __name__ == "__main__":
    main()
