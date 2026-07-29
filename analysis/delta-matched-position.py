"""Compare two visits to the same map at MATCHED POSITION rather than whole-leg p50.

`read-marathon.py` fails its drift gate when a map's two visits differ by more
than 1.15x, on the grounds that map and session age are not separable. That is
only true when the visits covered different ground. When the runner repeats a
route - which she did on Customs - the visits overlap in position and the
comparison can be made at fixed position from data already on disk.

`pos.x` / `pos.z` are [min, max] bounding ranges over a window, not points, so
two windows are treated as matched when their x-intervals overlap. That is
COARSE: it ignores z, and overlapping wide and narrow intervals are not the
same ground. It is a screening test - it decides whether a finer comparison is
worth building, and its output is not quotable on its own.

Chronology comes from file order then leg order, never from sorting the labels.
An earlier draft of this sorted by label and inverted the two visits, which
reverses the sign of every drift conclusion drawn from it.

Usage:  python analysis/delta-matched-position.py <map-id> <log.ndjson>...
        map-id is the internal name, e.g. bigmap for Customs, Lighthouse.
"""
import json
import os
import sys
from collections import defaultdict


def visits_for(map_id, paths):
    """Every raid window on `map_id`, grouped into visits in chronological order."""
    out = []
    for path in paths:
        stamp = os.path.basename(path).split("-")[1:3]
        leg, prev = 0, None
        for ln in open(path, encoding="utf-8"):
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            if o.get("type") != "sample":
                continue
            m = str(o.get("map") or "").lower()
            if m != prev:
                leg += 1
                prev = m
            if m != map_id.lower() or o.get("state") != "raid":
                continue
            pos = o.get("pos") or {}
            x = pos.get("x")
            if not (isinstance(x, list) and len(x) == 2):
                continue
            fp = o.get("framePct") or {}
            bots = o.get("bots") or {}
            out.append({
                "key": (paths.index(path), leg),
                "label": "%s leg%d" % ("-".join(stamp), leg),
                "win": o.get("window"), "x0": x[0], "x1": x[1],
                "p50": fp.get("p50"), "awake": bots.get("awake"),
                "slicing": (o.get("agents") or {}).get("slicing"),
                "brainPeriod": (o.get("cfg") or {}).get("brainPeriod"),
            })

    grouped = defaultdict(list)
    for r in out:
        grouped[r["key"]].append(r)
    return [grouped[k] for k in sorted(grouped)]


def median(xs):
    s = sorted(xs)
    return s[len(s) // 2] if s else None


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2

    map_id, paths = argv[1], argv[2:]
    visits = visits_for(map_id, paths)
    if not visits:
        print("NO RAID WINDOWS for map '%s' -- check the map id before "
              "concluding anything" % map_id)
        return 2

    print("visits to '%s', in chronological order\n" % map_id)
    for v in visits:
        p50 = median([r["p50"] for r in v if r["p50"]])
        aw = [r["awake"] for r in v if r["awake"] is not None]
        print("  %-22s n=%-3d x %7.0f..%-7.0f  p50 %5.2f ms (%5.1f fps)  awake %d..%d"
              % (v[0]["label"], len(v), min(r["x0"] for r in v),
                 max(r["x1"] for r in v), p50, 1000.0 / p50,
                 min(aw) if aw else -1, max(aw) if aw else -1))

    if len(visits) < 2:
        print("\nonly one visit -- nothing to match")
        return 0

    a, b = visits[0], visits[-1]
    pairs = [(ra, rb) for ra in a for rb in b
             if ra["x0"] <= rb["x1"] and rb["x0"] <= ra["x1"] and ra["p50"] and rb["p50"]]

    print("\nmatched-position pairs (x-intervals overlap): %d\n" % len(pairs))
    if not pairs:
        print("  NONE -- the visits covered disjoint ground. Position and session")
        print("  age are genuinely inseparable in this run, and the gate is right.")
        return 0

    for ra, rb in pairs:
        print("  w%-4d x[%5.0f,%5.0f]  vs  w%-4d x[%5.0f,%5.0f]  %6.2f / %-6.2f = %.2fx"
              "   awake %s vs %s"
              % (ra["win"], ra["x0"], ra["x1"], rb["win"], rb["x0"], rb["x1"],
                 rb["p50"], ra["p50"], rb["p50"] / ra["p50"], ra["awake"], rb["awake"]))

    ratios = [rb["p50"] / ra["p50"] for ra, rb in pairs]
    whole = median([r["p50"] for r in b if r["p50"]]) / median([r["p50"] for r in a if r["p50"]])
    print("\n  whole-visit ratio (what the gate computes) : %.2fx" % whole)
    print("  matched-position median ratio              : %.2fx  (range %.2f-%.2f)"
          % (median(ratios), min(ratios), max(ratios)))
    print("\n  The difference is what position explains. What is left is not")
    print("  session age by default -- check `awake` above before naming it.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
