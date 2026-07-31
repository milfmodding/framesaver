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


def win(i, dead=True, corpses=CORPSES, live_bots=LIVE_BOTS, census_dead=None,
        transitions=None, duty=1.0):
    live_calls = int(live_bots * FRAMES * duty)
    dead_calls = int(corpses * FRAMES * duty)
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
    out = {"type": "sample", "state": "raid", "window": i, "raidElapsed": 200.0 + 60 * i,
           "frames": FRAMES, "n": FRAMES,
           "cfg": {"standBy": True, "deactivateSleeping": False},
           "bots": bots, "updateManual": um}
    # Omitted entirely unless asked for, so every case written before the
    # denominator calibration existed keeps the inputs it was verified on.
    if transitions is not None:
        out["standByTransitions"] = transitions
    return out


def run(name, windows, grep):
    path = os.path.join(HERE, "um-%s.ndjson" % name)
    with open(path, "w", encoding="utf-8") as fh:
        # THE HEADER IS LOAD-BEARING AND ITS ABSENCE KILLED THIS WHOLE FILE.
        # read-updatemanual partitions with by_start=True, which needs a
        # resolvable window length; these synthetics carried none, so every
        # window was refused and all 8 cases had been exiting on "GATE FAILED
        # - no eligible window carries updateManual" since the day the harness
        # was committed. They ran, printed, and tested NOTHING. It survived
        # because the check applied to it was "no traceback" -- an absence, on
        # the one file whose README says a case that cannot fail reports a
        # pass. windowSeconds is TOP LEVEL on the header, not under `config`.
        fh.write(json.dumps({"type": "header", "windowSeconds": 60.0}) + "\n")
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


# ---- Denominator calibration -------------------------------------------
#
# Does awakeCalls/frames really mean "mean awake bots"? These decide whether
# Alpha can quote a per-bot slope off it or only a bracket.
CAL = KEYS + ["calibration", "quiet", "implied", "UNCALIBRATED", "scale factor"]
QUIET = {"woken": 0, "slept": 0, "diedAwake": 0, "diedAsleep": 0}

# I: once per bot per frame, nothing moving -> implied count IS `frames`.
run("cal_clean", [win(i, transitions=QUIET) for i in range(6)], CAL)

# J: UpdateManual throttled to every other frame. The counts stay internally
#    consistent and every other section still reads fine -- which is the point:
#    without this check a duty cycle is invisible and halves every slope.
run("cal_duty", [win(i, transitions=QUIET, duty=0.5) for i in range(6)], CAL)

# K: transitions present but the roster is churning, so NO window is quiet.
#    Must say UNCALIBRATED rather than fall through to a pass.
run("cal_busy", [win(i, transitions={"woken": 3, "slept": 2, "diedAwake": 0,
                                     "diedAsleep": 0}) for i in range(6)], CAL)

# L: the block is absent entirely -- every log before it shipped. Absent is not
#    quiet, and must not be scored as a calibration.
run("cal_absent", [win(i) for i in range(6)], CAL)
