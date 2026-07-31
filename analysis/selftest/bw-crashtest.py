"""Crash-test read-botwindow.py. Paths only; the slopes here are constructed.

  A  flat cost, many spans          -> sign test reads as a coin
  B  rising cost, many spans        -> one-sided
  C  rows do not sum to awakeMs-deadMs -> reconcile gate fails
  D  one bot, two spans (a re-wake) -> split into 2 POSITIVE slopes, not 1 negative
  E  too few spans                  -> underpowered gate, no median reported
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
READER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "read-botwindow.py")

CALLS = 200


def build(nbots, nwin, slope, base=0.02, break_at=None, corrupt=False,
          span_start=None):
    """Rows plus the sample lines they must reconcile against."""
    lines = []
    for w in range(nwin):
        rows = []
        for b in range(nbots):
            # break_at restarts the age, which is what a re-wake looks like.
            age = (w % break_at if break_at else w) * 60.0 + 30.0
            per_call = base + slope * age
            row = {"type": "botWindow", "window": w, "id": "bot%d" % b,
                   "role": "assault", "awakeS": round(age, 2),
                   "ms": round(per_call * CALLS, 4), "n": CALLS}
            if span_start is not None:
                sv = (w // break_at) * 1000.0 if break_at else span_start
                row["spanS"] = round(sv, 2)
            rows.append(row)
        total = sum(r["ms"] for r in rows)
        dead_ms = 1.0
        um = {"awakeMs": round(total + dead_ms, 4), "awakeCalls": nbots * CALLS + 500,
              "pausedMs": 5.0, "pausedCalls": 40000, "unstampedCalls": 0,
              "deadCalls": 500, "deadMs": dead_ms}
        if corrupt:
            um["awakeMs"] = round(total * 1.5 + dead_ms, 4)
        lines.append({"type": "sample", "state": "raid", "window": w,
                      "raidElapsed": 200.0 + 60 * w, "frames": 3000,
                      "cfg": {"standBy": True}, "bots": {"awake": nbots},
                      "updateManual": um})
        lines.extend(rows)
    return lines


def run(name, lines, keys):
    path = os.path.join(HERE, "bw-%s.ndjson" % name)
    with open(path, "w", encoding="utf-8") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")
    print("=" * 70)
    print("CASE %s" % name)
    print("=" * 70)
    r = subprocess.run([sys.executable, READER, path], capture_output=True, text=True)
    for ln in r.stdout.splitlines():
        if any(k in ln for k in keys):
            print(ln)
    if r.stderr.strip():
        print("STDERR:\n" + r.stderr)
    print("rc=%d\n" % r.returncode)


KEYS = ["reconcile", "spans", "bots ", "median slope", "positive", "sign test",
        "design bound", "GATE", "!", "coin", "one-sided", "windows with rows"]

run("flat", build(12, 6, 0.0), KEYS)
run("rising", build(12, 6, 0.00005), KEYS)
run("corrupt", build(12, 6, 0.00005, corrupt=True), KEYS)
run("rewake", build(12, 8, 0.00005, break_at=4), KEYS)
run("thin", build(2, 4, 0.00005), KEYS)


# F: Beta's hole at OUR DEFAULT 60 s window. Span A ends at age 40; the bot
#    sleeps and re-wakes 5 s later, so span B's first recorded age is 53.
#    40 -> 53 is an INCREASE across a genuine reset, invisible to the age rule.
#    12 bots so the power gate is cleared and the slope section is reached.
def hole_rows(with_span):
    out = []
    ages_a, ages_b = [20.0, 30.0, 40.0], [53.0, 113.0, 173.0]
    for w, age in enumerate(ages_a + ages_b):
        rows = []
        for b in range(12):
            r = {"type": "botWindow", "window": w, "id": "bot%d" % b,
                 "role": "assault", "awakeS": age,
                 "ms": round(0.02 * CALLS, 4), "n": CALLS}
            if with_span:
                r["spanS"] = 0.0 if w < 3 else 45.0
            rows.append(r)
        total = sum(r["ms"] for r in rows)
        out.append({"type": "sample", "state": "raid", "window": w,
                    "raidElapsed": 200.0 + 60 * w, "frames": 3000,
                    "cfg": {"standBy": True}, "bots": {"awake": 12},
                    "updateManual": {"awakeMs": round(total + 1.0, 4),
                                     "awakeCalls": 12 * CALLS + 500,
                                     "pausedMs": 5.0, "pausedCalls": 40000,
                                     "unstampedCalls": 0, "deadCalls": 500,
                                     "deadMs": 1.0}})
        out.extend(rows)
    return out


run("hole_spanS", hole_rows(True), KEYS + ["disagree", "spanS"])
run("hole_ageonly", hole_rows(False), KEYS + ["disagree", "spanS"])
