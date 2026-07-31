"""Crash-test the corpse paths in read-updatemanual.py.

Exercises code paths, and ONE arithmetic recovery. The recovery case is built so
the true per-live-call cost is known by construction (0.02 ms), so the corrected
mean can be checked against it -- that is a test of the subtraction, not of any
claim about raids.

  A  every window carries deadCalls, corpses present  -> subtracts, recovers 0.02
  B  no window carries it (old build)                 -> falls back, says so
  C  mixed builds                                     -> treated as absent
  D  every awake call is a corpse                     -> no live bucket, gated
  E  field present, zero corpses                      -> real zero, not absent
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
READER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "read-updatemanual.py")

FRAMES = 3000
LIVE_BOTS = 10
CORPSES = 5
LIVE_MS_PER_CALL = 0.02
DEAD_MS_PER_CALL = 0.0001
PAUSED_BOTS = 20
PAUSED_MS_PER_CALL = 0.000188


def win(i, dead=True, corpses=CORPSES, live_bots=LIVE_BOTS, census_dead=None):
    live_calls = live_bots * FRAMES
    dead_calls = corpses * FRAMES
    um = {
        "awakeMs": round(live_calls * LIVE_MS_PER_CALL
                         + dead_calls * DEAD_MS_PER_CALL, 4),
        "awakeCalls": live_calls + dead_calls,
        "pausedMs": round(PAUSED_BOTS * FRAMES * PAUSED_MS_PER_CALL, 4),
        "pausedCalls": PAUSED_BOTS * FRAMES,
        "unstampedCalls": 0,
    }
    if dead:
        um["deadCalls"] = dead_calls
        um["deadMs"] = round(dead_calls * DEAD_MS_PER_CALL, 4)
    bots = {"awake": live_bots + corpses, "total": 40}
    if census_dead is not None:
        bots["deadAwake"] = census_dead
    return {"type": "sample", "state": "raid", "window": i, "raidElapsed": 200.0 + 60 * i,
            "frames": FRAMES, "cfg": {"standBy": True, "deactivateSleeping": False},
            "bots": bots, "updateManual": um}


def run(name, windows, grep):
    path = os.path.join(HERE, "um-%s.ndjson" % name)
    with open(path, "w", encoding="utf-8") as fh:
        for w in windows:
            fh.write(json.dumps(w) + "\n")
    print("=" * 70)
    print("CASE %s" % name)
    print("=" * 70)
    r = subprocess.run([sys.executable, READER, path], capture_output=True, text=True)
    for ln in r.stdout.splitlines():
        if any(g in ln for g in grep):
            print(ln)
    if r.stderr.strip():
        print("STDERR:\n" + r.stderr)
    print("rc=%d" % r.returncode)
    print()


KEYS = ["deadCalls", "awake (", "paused ", "contrast", "corpse", "direct",
        "median live", "x median", "GATE", "!", "no live"]

print("by construction: live cost %.5f ms/call, direct %.4f ms/frame\n"
      % (LIVE_MS_PER_CALL, LIVE_BOTS * LIVE_MS_PER_CALL))

run("all", [win(i) for i in range(6)], KEYS)
run("oldbuild", [win(i, dead=False) for i in range(6)], KEYS)
run("mixed", [win(i, dead=(i % 2 == 0)) for i in range(6)], KEYS)
run("allcorpse", [win(i, live_bots=0) for i in range(6)], KEYS)
run("zerocorpse", [win(i, corpses=0) for i in range(6)], KEYS)

# F: bots.deadAwake present and agreeing with the call-rate route.
run("census", [win(i, census_dead=CORPSES) for i in range(6)], KEYS)

# G: census says 1 corpse, the call rate implies 5 - a roster turning over
#    inside the window. Both routes exist and neither describes it.
run("turnover", [win(i, census_dead=1) for i in range(6)], KEYS)

# H: the transient regime Delta established - corpses tick (call rate 5) but
#    the one-shot roster sample at window close catches none. deadAwake == 0
#    is the PREDICTED value and must not read as "no contamination".
run("transient", [win(i, census_dead=0) for i in range(6)], KEYS + ["EXPECTED", "roster"])
