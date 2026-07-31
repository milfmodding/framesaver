"""Positive and negative controls for check-modoff.py after the maxDelta/unruled fix.

Every case states the exit code it MUST produce. A case that passes for the wrong reason is
caught by the FAIL cases: if the checker returned 0 for everything, five of these break.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = r"F:\SPT\Mods\Framesaver\harness\check-modoff.py"

# A cfg block for a CORRECT mod-off baseline under the bc90b76 build.
CLEAN = {
    "windowSeconds": 30, "standBy": False, "leakFix": False, "brainPeriod": 0,
    "fastAnim": False, "cullSleeping": False, "maxDelta": 0.083, "skipLate": False,
    "skipTick": False, "jobBudgetMs": 0, "jobSlowFrames": -1, "asyncBudgetMs": 0,
    "suspendGc": False, "reclaimStandBy": False, "deactivateSleeping": False,
    "keepFighting": False, "drainInUpdateOnly": False, "drainDiagnostics": True,
    "sleepDistance": 150, "wakeDistance": 130, "roleSleepDist": 0, "roleWakeDist": 0,
    "bossGroupWake": False, "forceAllRoles": False, "checkInterval": 5,
    "sleepImmediately": True, "minBrainsPerFrame": 4, "gcTimeSliceMs": 0, "gcDriveMs": 0, "gcSliceApplied": False,
}


def write_log(name, cfgs):
    path = os.path.join(HERE, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "header", "commit": "bc90b76deadbeef",
                             "config": {"standByEnabled": False}}) + "\n")
        for i, cfg in enumerate(cfgs):
            fh.write(json.dumps({"type": "sample", "state": "raid", "raid": 1, "map": "woods",
                                 "raidElapsed": 120 + 30 * i, "windowSec": 30, "cfg": cfg}) + "\n")
    return path


def run(path):
    p = subprocess.run([sys.executable, CHECK, path], capture_output=True, text=True)
    return p.returncode, p.stdout


def case(label, cfgs, want_exit, want_text=None, absent_text=None):
    path = write_log("t.ndjson", cfgs)
    code, out = run(path)
    ok = code == want_exit
    if ok and want_text:
        ok = want_text in out
    if ok and absent_text:
        ok = absent_text not in out
    print("%-4s %-52s exit %d (want %d)" % ("ok" if ok else "FAIL", label, code, want_exit))
    if not ok:
        print("---- output ----")
        print(out)
    return ok


def variant(**kw):
    c = dict(CLEAN)
    c.update(kw)
    return c


results = []

# 1. THE REGRESSION. maxDelta reads Unity's value because the setting is 0 and the mod wrote
#    nothing. Before the fix this returned 1 and would have failed all nine marathon logs.
#    0.083 is EFT own value, measured on Ground Zero 2026-07-31 - NOT Unity 0.333.
results.append(case("clean baseline, maxDelta = the game 0.083",
                    [variant(), variant()], 0, want_text="Clean mod-off baseline"))

# 2. NEGATIVE CONTROL for the same field: the cap still applied. Must be caught.
results.append(case("maxDelta = 0.1, the value the mod imposes",
                    [variant(maxDelta=0.1), variant(maxDelta=0.1)], 1,
                    want_text="the value the mod IMPOSES"))

# 2b. A third value is a NOTE about the game, not a dirty baseline - must still pass.
results.append(case("maxDelta = 0.05, neither vanilla nor our cap -> note",
                    [variant(maxDelta=0.05)], 0, want_text="NOTE, not a failure"))

# 3. A mid-raid edit leaves the windows disagreeing. A single-value report would hide it.
results.append(case("maxDelta not constant across windows",
                    [variant(maxDelta=0.083), variant(maxDelta=0.1)], 1,
                    want_text="NOT CONSTANT"))

# 4. An acting lever left on must still fail, i.e. the fix did not blunt the original check.
results.append(case("asyncBudgetMs = 4 still caught",
                    [variant(asyncBudgetMs=4)], 1, want_text="ACTIVE"))
results.append(case("leakFix = true still caught",
                    [variant(leakFix=True)], 1, want_text="ACTIVE"))

# 5. A lever added to the mod after this checker was written. Must be NAMED, not ignored.
results.append(case("unknown key is reported as UNRULED",
                    [variant(someNewLever=True)], 0, want_text="UNRULED someNewLever"))

# 6. The four newly-ruled keys are moot with stand-by off, so ON is reported and not fatal.
results.append(case("bossGroupWake/roleSleepDist on -> moot, exit 0",
                    [variant(bossGroupWake=True, roleSleepDist=350, roleWakeDist=330)], 0,
                    want_text="moot"))

# 7. forceAllRoles was previously invisible to this file. It is stand-by gated, so moot - but it
#    must now appear rather than vanish.
results.append(case("forceAllRoles on -> named as moot",
                    [variant(forceAllRoles=True)], 0, want_text="forceAllRoles"))

# 7b. RETIRED settings. Absent must be FINE (a post-removal build must not refuse), present-and-off
#     must be a note, and present-and-on must FAIL. Without the third case the retirement is just a
#     deletion and an old build running the setting would pass silently.
noanim = dict(CLEAN)
del noanim["fastAnim"]
results.append(case("fastAnim absent -> fine, post-removal build", [noanim], 0,
                    want_text="absent, as expected"))
results.append(case("fastAnim present but off -> note, not a failure",
                    [variant(fastAnim=False)], 0, want_text="present but off"))
results.append(case("fastAnim present and ON -> must FAIL",
                    [variant(fastAnim=True)], 1, want_text="was REMOVED"))

# 8. A key this build cannot report is still a refusal, unchanged.
missing = dict(CLEAN)
del missing["suspendGc"]
results.append(case("suspendGc unreportable -> REFUSED", [missing], 2,
                    want_text="not emitted by this build"))

# 9. Header-only log: zero windows must refuse, not pass.
results.append(case("zero raid windows -> REFUSED", [], 2, want_text="REFUSED"))

print()
print("%d/%d controls behaved as specified" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
