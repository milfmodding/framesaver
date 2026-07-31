"""Per-raid state of a multi-raid session log, with the warm-up rule in ONE place.

WHY THIS EXISTS. The marathon appends every raid to a single ndjson, and after each one the
question is the same: how many usable windows did that raid produce, and does anything look wrong.
Answering it with an ad-hoc query per raid is how the warm-up rule drifts - `raidElapsed > 60` on
one raid and `raidElapsed - windowSec >= 60` on the next, which is a population difference invented
by the reader rather than found in the data. Five aggregation-order and population errors this week
came from exactly that. So the rule lives here, once.

WHAT THIS DELIBERATELY DOES NOT DO. It does not estimate a per-raid percentile. `framePct.p75` is a
per-window nearest-rank figure over BSG's measurer; the gate instrument is a linear-interpolated
percentile over pooled PresentMon frames. Reducing the window values to one number here would be a
THIRD estimator that agrees with neither, and it would get quoted. The p75 column is therefore
labelled as a RANGE OF WINDOW VALUES and nothing else.

Teardown: the last in-raid window of each segment reads its census after the game object is gone,
so `bots.*` and the instant-sampled fields are unusable there. Frame data in it is fine. `final`
marks only some of them, so segment position is what identifies them.
"""
import json
import os
import sys

WARMUP_SEC = 60
MIN_WINDOWS = 3


def load(path):
    """Windows in file order, plus a teardown flag set by SEGMENT POSITION, not by `final`."""
    rows = []
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") == "sample" and o.get("state") == "raid":
            rows.append(o)

    for i, o in enumerate(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        key = (o.get("raid"), str(o.get("map")))
        o["_teardown"] = (nxt is None
                          or (nxt.get("raid"), str(nxt.get("map"))) != key)
    return rows


def kept(o):
    """A window is usable if it BEGINS after warm-up ends.

    `raidElapsed` is stamped at window CLOSE, so a bare `raidElapsed >= 60` keeps a window that
    started at 30 s - and at 30 s windows it would keep one that started at 0. Subtracting the
    window's own length is what makes the rule window-length neutral, which matters because this
    corpus has both 60 s and 30 s eras.

    Returns None - NOT False - when the rule cannot be evaluated. `windowSec` is absent on 210 of
    the 418 pre-marathon windows, and folding that into False made an unreadable raid print as a
    THIN one: same table, same exit code, completely different cause. A caller pointed at the old
    corpus would have read "too few windows" and gone looking for a longer raid.
    """
    el, ws = o.get("raidElapsed"), o.get("windowSec")
    if el is None or ws is None:
        return None
    return el - ws >= WARMUP_SEC


def rng(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    lo, hi = min(vals), max(vals)
    return "%g" % lo if lo == hi else "%g-%g" % (lo, hi)


def main():
    if len(sys.argv) < 2:
        print("usage: marathon-status.py <log.ndjson>")
        return 2
    path = sys.argv[1]
    if not os.path.isfile(path):
        print("REFUSED: no such log: %s" % path)
        return 2

    rows = load(path)
    if not rows:
        print("REFUSED: 0 in-raid windows - a report over zero rows is not a report")
        return 2

    segs = []
    for o in rows:
        key = (o.get("raid"), str(o.get("map")))
        if not segs or segs[-1][0] != key:
            segs.append((key, []))
        segs[-1][1].append(o)

    print("%s" % os.path.basename(path))
    print("warm-up rule: keep a window only if raidElapsed - windowSec >= %d" % WARMUP_SEC)
    print()
    print("  %-4s %-15s %5s %5s %5s  %-9s %-7s %-9s %s"
          % ("raid", "map", "win", "keep", "body", "agents", "asleep", "linked", "p75 window range (ms)"))
    print("  " + "-" * 96)

    thin, unreadable = [], []
    for (raid, mp), ws in segs:
        blind = [o for o in ws if kept(o) is None]
        k = [o for o in ws if kept(o) is True]
        body = [o for o in k if not o["_teardown"]]
        if blind:
            unreadable.append("%s (raid %s): %d of %d window(s) have no windowSec, so the "
                              "warm-up rule cannot be evaluated on them"
                              % (mp, raid, len(blind), len(ws)))
        p75 = [(o.get("framePct") or {}).get("p75") for o in body]
        ag = [(o.get("agents") or {}).get("live") for o in body]
        sl = [(o.get("bots") or {}).get("asleep") for o in body]
        li = [(o.get("bossGroups") or {}).get("linked") for o in body]
        print("  %-4s %-15s %5d %5d %5d  %-9s %-7s %-9s %s"
              % (raid, mp, len(ws), len(k), len(body), rng(ag), rng(sl), rng(li), rng(p75)))
        if len(body) < MIN_WINDOWS:
            thin.append("%s (raid %s): %d body window(s)" % (mp, raid, len(body)))

    print()
    print("win  = in-raid windows.  keep = past warm-up.  body = keep minus the teardown window,")
    print("       which is the population for bots.* and every instant-sampled field.")
    print("p75  = the RANGE of per-window framePct.p75, not an estimate of the raid's p75. The")
    print("       gate figure comes from pooled PresentMon frames and is not computed here.")

    # Unreadable is reported BEFORE thin and returns a different code, because the two look
    # identical in the table above and mean opposite things: thin says play longer, unreadable
    # says this tool cannot read this log.
    if unreadable:
        print()
        print("UNREADABLE - not the same as thin. A short raid and a missing field print the")
        print("same row, and the fix for one is not the fix for the other:")
        for u in unreadable:
            print("  %s" % u)
        return 2

    if thin:
        print()
        print("THIN, under %d body windows - too few for a per-map figure:" % MIN_WINDOWS)
        for t in thin:
            print("  %s" % t)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
