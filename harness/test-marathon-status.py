"""Controls for marathon-status.py - the instrument I have been reading every raid through.

Each case states what MUST appear. The point is not that it passes; it is that a broken version
would print something different.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = r"F:\SPT\Mods\Framesaver\harness\marathon-status.py"


def w(raid, mp, elapsed, winsec=30.0, p75=20.0, agents=10, asleep=0, linked=5, extra=None):
    o = {"type": "sample", "state": "raid", "raid": raid, "map": mp,
         "raidElapsed": elapsed, "windowSec": winsec,
         "framePct": {"p75": p75}, "agents": {"live": agents},
         "bots": {"asleep": asleep}, "bossGroups": {"linked": linked}}
    if winsec is None:
        del o["windowSec"]
    if extra:
        o.update(extra)
    return o


def run(rows, name="s.ndjson"):
    p = os.path.join(HERE, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "header", "commit": "deadbeef"}) + "\n")
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    r = subprocess.run([sys.executable, TOOL, p], capture_output=True, text=True)
    return r.returncode, r.stdout


def case(label, rows, want_exit, must=(), must_not=()):
    code, out = run(rows)
    ok = code == want_exit
    for m in must:
        if m not in out:
            ok = False
    for m in must_not:
        if m in out:
            ok = False
    print("%-4s %-56s exit %d (want %d)" % ("ok" if ok else "FAIL", label, code, want_exit))
    if not ok:
        print(out)
    return ok


res = []

# 1. A 10-window raid: 2 lost to warm-up, 1 to teardown, 7 body. Hand-checked.
rows = [w(1, "woods", 30 * i) for i in range(1, 11)]
res.append(case("10 windows -> keep 8, body 7", rows, 0, must=("   10     8     7",)))

# 2. THE WARM-UP BOUNDARY. elapsed 90 winsec 30 begins at 60 and MUST be kept; elapsed 60
#    begins at 30 and must not. A tool using `elapsed >= 60` would keep one window too many.
rows = [w(1, "woods", 60.0), w(1, "woods", 90.0), w(1, "woods", 120.0), w(1, "woods", 150.0)]
# body is 2 here, so THIN correctly fires and the exit is 1. The table is what this case is
# testing; the earlier version of this control asserted exit 0 and failed on the TOOL being right.
res.append(case("warm-up boundary is elapsed-windowSec, not elapsed", rows, 1,
                must=("    4     3     2",)))

# 3. Teardown is the LAST window of a segment, identified by position not by `final`. Two raids
#    on the SAME map must not merge - if they did, only one teardown would be removed.
rows = ([w(1, "woods", 30 * i) for i in range(1, 7)]
        + [w(2, "woods", 30 * i) for i in range(1, 7)])
res.append(case("same map twice -> two segments, two teardowns", rows, 0,
                must=("1    woods", "2    woods")))

# 4. THIN must fire and set exit 1. Never tested until now.
rows = [w(1, "factory4_day", 30 * i) for i in range(1, 6)]
res.append(case("5 windows -> body 2 -> THIN, exit 1", rows, 1,
                must=("THIN", "factory4_day")))

# 5. A `final` flag in the WRONG place must not move the teardown. `final` marks only 17 of 33
#    real teardown windows in the corpus, so trusting it would be wrong.
rows = [w(1, "woods", 30 * i, extra={"final": True} if i == 3 else None) for i in range(1, 11)]
res.append(case("a misplaced `final` does not move the teardown", rows, 0,
                must=("   10     8     7",)))

# 6. THE COLLAPSED DENOMINATOR. windowSec is absent on 210 of 418 corpus windows. A tool that
#    silently drops them reports keep 0, which is indistinguishable from a short raid.
rows = [w(1, "woods", 30 * i, winsec=None) for i in range(1, 11)]
# The first version of this control asserted the string "windowSec", which appears in the
# warm-up header line of EVERY run - so it passed without testing anything. A vacuous control is
# worse than no control: it reports coverage it does not have.
res.append(case("windowSec absent -> UNREADABLE, not THIN", rows, 2,
                must=("UNREADABLE", "no windowSec"), must_not=("THIN",)))

# 7. Zero in-raid windows must refuse, not print an empty table.
res.append(case("no raid windows -> REFUSED", [], 2, must=("REFUSED",)))

# 8. A p75 that is null on some windows must not be silently averaged into a range.
rows = [w(1, "woods", 30 * i, p75=None if i == 5 else 20.0) for i in range(1, 11)]
res.append(case("null p75 in one window does not crash the range", rows, 0, must=("20",)))

print()
print("%d/%d controls behaved as specified" % (sum(res), len(res)))
sys.exit(0 if all(res) else 1)
