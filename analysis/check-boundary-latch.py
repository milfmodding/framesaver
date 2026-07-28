#!/usr/bin/env python3
"""Validate the frame-boundary latch against a telemetry log.

The latch makes `accounted <= period` an identity rather than a measurement, so the
check is an assertion: any negative residual is an instrument defect. That is only
readable if a zero from the assertion holding can be told apart from a zero from the
counter never running, which is what clockResidualFrames exists for.

Usage:  python check-boundary-latch.py <log.ndjson> [more.ndjson ...]

Three exit states, not two:

  0  every essential check ran and passed
  1  an essential check failed
  2  an essential check could not run -- the log predates the latch, or the fields
     are absent for some other reason

The third state exists because the first version of this script returned 0 on a
pre-latch log: both latch checks skipped, the incidental nesting check ran and
passed, and the summary line read like a validated latch. A log with real data in
it passed while an empty file correctly failed, so the failure got EASIER to hit
the more data you had. "I could not look" must never render as "it is sound".
"""

import json
import sys


def load(path):
    """Yield window lines only. Spike lines carry a different schema."""
    with open(path, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                print(f"  ! {path}:{number} is not JSON, skipped")
                continue
            if "negResidualFrames" in row:
                yield number, row


# Checks 1 and 2 validate the latch and are the reason this script exists. Check 3
# would run against any log ever written, so it must not be able to carry a pass on
# its own.
ESSENTIAL = ("negative-residual assertion", "boundary tracks StartOfFrame")


def check(path):
    """Return (failures, ran, skipped_essential) for one log."""
    windows = list(load(path))
    if not windows:
        print("  SKIP  no window lines carrying negResidualFrames")
        return 0, 0, list(ESSENTIAL)

    failures = 0
    run = 0
    skipped = []

    # 1. The assertion itself. Zero by construction once the latch lands.
    eligible = sum(r.get("clockResidualFrames", 0) for _, r in windows)
    negatives = sum(r["negResidualFrames"] for _, r in windows)
    if any("clockResidualFrames" in r for _, r in windows):
        run += 1
        if eligible == 0:
            print("  FAIL  clockResidualFrames is 0 across every window: the residual test never "
                  "ran, so negResidualFrames == 0 proves nothing")
            failures += 1
        elif negatives:
            worst = max(r.get("negResidualWorstMs", 0) for _, r in windows)
            print(f"  FAIL  {negatives} negative-residual frames of {eligible} eligible, "
                  f"worst {worst} ms -- accounted <= period should be an identity")
            failures += 1
        else:
            print(f"  ok    negResidualFrames 0 of {eligible} eligible frames")
    else:
        print("  SKIP  clockResidualFrames absent (log predates the latch)")
        skipped.append(ESSENTIAL[0])

    # 2. The latch must sit on the frame boundary. SPT's StartOfFrame fires once per
    #    frame, so the two counts track each other; a divergence means the marker we
    #    latch on is not running once per frame.
    if any("boundaryFires" in r for _, r in windows):
        run += 1
        bad = [
            (n, r["boundaryFires"], r["startOfFrameFires"])
            for n, r in windows
            if r.get("startOfFrameFires", 0) > 0
            and abs(r["boundaryFires"] - r["startOfFrameFires"]) > 1
        ]
        if bad:
            n, b, s = bad[0]
            print(f"  FAIL  boundaryFires diverges from startOfFrameFires in {len(bad)} window(s), "
                  f"first at line {n}: {b} vs {s}")
            failures += 1
        else:
            print("  ok    boundaryFires tracks startOfFrameFires")
    else:
        print("  SKIP  boundaryFires absent (log predates the latch)")
        skipped.append(ESSENTIAL[1])

    # 3. Nesting detector. Install() strips prior markers so a reinstall cannot wrap
    #    its own output; if that ever regresses, our marker types show up as children
    #    in the phase names and every phase after the first is mislabelled.
    # Phase names are the keys of the per-window `phases` object -- NOT a header field.
    # The first version of this check looked for `phaseNames` on the header, which does
    # not exist, so it would have reported SKIP forever and never once failed. Verified
    # against a real log before trusting it, which is the only reason it works.
    names = []
    for _, row in windows:
        phases = row.get("phases")
        if isinstance(phases, dict) and phases:
            names = list(phases.keys())
            break
    if names:
        run += 1
        nested = [n for n in names if "BeginMarker" in n or "EndMarker" in n]
        if nested:
            print(f"  FAIL  {len(nested)} phase name(s) contain our own markers, e.g. {nested[0]!r} "
                  f"-- Install wrapped its own output")
            failures += 1
        else:
            print(f"  ok    no nested markers across {len(names)} phase names")
    else:
        print("  SKIP  no phases object on any window line")

    # 4. Boundary misses are expected at raid load, when the game rewrites the loop.
    #    Reported rather than failed: the number is the point, not a threshold.
    missed = sum(r.get("boundaryMissedFrames", 0) for _, r in windows)
    if any("boundaryMissedFrames" in r for _, r in windows):
        total = missed + eligible
        share = (100.0 * missed / total) if total else 0.0
        print(f"  info  {missed} boundary-missed frames ({share:.2f}% of {total})")

    # 5. Gamma's third population: frames sampled while the profiler was NOT installed.
    #    Counted in `frames`, absent from boundaryMissedFrames, excluded from
    #    clockResidualFrames -- so no field names it and it only comes out by
    #    subtraction. Non-zero mid-raid means that window's phase totals are partial,
    #    which nothing else on the line says. Reported, never failed: a raid load
    #    legitimately produces some.
    sampled = sum(r.get("frames", 0) for _, r in windows)
    if sampled and any("clockResidualFrames" in r for _, r in windows):
        uninstalled = sampled - missed - eligible
        # The first sampled frame of a session also lands here, dropped by the
        # periodMs > 0 guard, so 0 or 1 is the healthy reading and flagging on >0
        # would cry wolf on the opening window of every run.
        note = "  <- phase totals partial for these" if uninstalled > 1 else ""
        print(f"  info  {uninstalled} frame(s) sampled with the profiler uninstalled "
              f"(frames {sampled} - missed {missed} - eligible {eligible}){note}")

    return failures, run, skipped


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    total = 0
    ran = 0
    missing = []
    for path in argv[1:]:
        print(path)
        try:
            failures, run, skipped = check(path)
        except IOError as exc:
            print(f"  ! {exc}")
            return 2
        total += failures
        ran += run
        missing.extend(skipped)

    if total:
        print(f"\nFAILED: {total} failure(s) across {ran} check(s) run.")
        return 1

    # Before the pass. An essential check that did not run cannot be outvoted by
    # incidental ones that did - that inversion is the bug this script had.
    if missing:
        names = ", ".join(sorted(set(missing)))
        print(f"\nINCONCLUSIVE: the latch could not be validated - {names} did not run. "
              f"{ran} incidental check(s) passed, which says nothing about the latch.")
        return 2

    print(f"\nPASSED: {ran} check(s), including every essential one.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
