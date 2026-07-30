"""Sabotage control for harness/check-fields.py: make every failure path fire on purpose.

WHY THIS EXISTS, and it is not symmetry with the reconciler's self-test.

`check-fields.py` gates every run AUTOMATICALLY from post-flight. The reconciler is run by
hand during analysis. So the tool whose success path nobody re-derives is the one that had
no sabotage control - the wrong way round, and Echo on the DRIP port named the shape from
the other side of the building: a repack that "succeeded" twice, once having done nothing
and once having half-worked, both with a clean exit code.

Two of these branches had never executed against any input, real or synthetic:
the frame-cap refusal and the dead-spawn-hook refusal. A branch that has never run is a
branch whose message, exit code and predicate are all unverified - and the frame-cap one
guards the PRIMARY success criterion, where a false pass arrives in the number we are
least likely to interrogate because it agrees with us.

HOW IT WORKS. One synthetic baseline log that must PASS, then one mutation per failure
path, each asserting BOTH the exit code and a distinctive fragment of the message. The
exit code alone is too weak: 1 means "some check failed", and a mutation that trips a
DIFFERENT check than the one intended would still read as a pass here.

THE LIMITATION, stated rather than buried: the baseline is synthetic, because the fields
it exercises shipped in 646c45d and no raid has run since. Its key names were taken from
the emitters (Telemetry.AppendDisplay/AppendPlatform/AppendSystem,
UpdateManualTimingPatches.Append, BossSpawnGate.Append), not from my memory of them, and
tests/unwrap covers the C# side. So this validates the CHECKER against the emitters'
contract. It cannot catch a checker and an emitter that are wrong in the same direction -
that is what --real does, running the newest real log through both modes.

THE CONTROL ON THE CONTROL: --neuter replaces fail() with a no-op inside a COPY of
check-fields.py and reruns. Every mutation case must then stop failing. If a case still
"passes" with fail() neutered, that case was passing for a reason other than the one it
claims, which is the defect this whole file is about.

    python analysis/alpha-check-fields-sabotage.py
    python analysis/alpha-check-fields-sabotage.py --real
    python analysis/alpha-check-fields-sabotage.py --neuter

Exit 0 all cases behaved, 1 at least one did not, 2 refused to report.
"""
import copy
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CHECKER = os.path.join(REPO, "harness", "check-fields.py")
LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"

NEUTER = "--neuter" in sys.argv
REAL = "--real" in sys.argv


# ------------------------------------------------------------------ baseline ----
# Key names from the emitters, not from memory. A baseline that does not PASS makes
# every mutation below unattributable, so case 1 is load-bearing rather than padding.

def header():
    return {
        "type": "header",
        "commit": "646c45dd4934",
        "runTag": "sabotage",
        "platform": {"sptAssembly": "4.0.13", "game": "0.16.8.1.42217", "unity": "2019.4.39f1"},
        "display": {"vSyncCount": 0, "targetFrameRate": -1, "refreshHz": 164.917,
                    "width": 2560, "height": 1440, "fullScreenMode": "ExclusiveFullScreen"},
        "system": {"cpu": "AMD Ryzen 7 5800X3D", "cores": 16, "cpuMhz": 3400,
                   "ramMb": 32677, "os": "Windows 11 (10.0.26200) 64bit"},
    }


def window(n):
    return {
        "type": "sample", "state": "raid", "window": n, "qpc": 1000000 + n * 10000,
        "framePct": {"p50": 14.8, "p95": 22.1, "p99": 31.0, "p999": 58.2},
        "bots": {"awake": 12, "asleep": 17, "total": 29, "animCulled": 17,
                 "animCulledOffScreen": 11, "exempt": 0, "roleUnknown": 0},
        "updateManual": {"awakeMs": 1.21, "awakeCalls": 900, "pausedMs": 0.18,
                         "pausedCalls": 1200, "unstampedCalls": 0},
        "spawnGate": {"sawWaves": True, "sawSettings": True, "entries": 140,
                      "pveOffline": True, "botAmountWaves": "AsOnline",
                      "forcedButExcluded": []},
        "agents": {"mods": ["BigBrain", "SAIN"], "slicing": False, "suppressSlicing": False},
    }


def baseline():
    lines = [header()]
    for n in range(1, 7):
        lines.append(window(n))
        lines.append({"type": "botSpawn", "id": "bot%02d" % n, "role": "assault",
                      "isAI": True, "canStandBy": True, "window": n})
    lines.append({"type": "death", "id": "bot01", "role": "assault", "isAI": True})
    # A final window exists in every real log and check-fields excludes it. Present so
    # the exclusion is exercised rather than assumed.
    fin = window(7)
    fin["final"] = True
    lines.append(fin)
    return lines


# ------------------------------------------------------------------ mutations ----
# Each returns a mutated copy. The name is what the case asserts, so a mutation that
# trips a different check than its name is a failure of this file, not of the checker.

def m_vsync(ls):
    ls[0]["display"]["vSyncCount"] = 1
    return ls


def m_targetfps(ls):
    ls[0]["display"]["targetFrameRate"] = 60
    return ls


def m_display_gone(ls):
    del ls[0]["display"]
    return ls


def m_platform_empty(ls):
    ls[0]["platform"]["sptAssembly"] = ""
    return ls


def m_no_header(ls):
    return [l for l in ls if l.get("type") != "header"]


def m_no_raid(ls):
    return [l for l in ls if not (l.get("type") == "sample" and not l.get("final"))]


def m_unstamped(ls):
    for l in ls:
        if l.get("type") == "sample" and not l.get("final"):
            l["updateManual"]["unstampedCalls"] = 7
            break
    return ls


def m_paused_zero(ls):
    for l in ls:
        if l.get("type") == "sample":
            l["updateManual"]["pausedCalls"] = 0
    return ls


def m_forced_null(ls):
    for l in ls:
        if l.get("type") == "sample" and not l.get("final"):
            l["spawnGate"]["forcedButExcluded"] = None
    return ls


def m_forced_hit(ls):
    for l in ls:
        if l.get("type") == "sample" and not l.get("final"):
            l["spawnGate"]["forcedButExcluded"] = ["bossBoar"]
            break
    return ls


def m_preset_wrong(ls):
    for l in ls:
        if l.get("type") == "sample":
            l["spawnGate"]["botAmountWaves"] = "Medium"
    return ls


def m_preset_varies(ls):
    hits = [l for l in ls if l.get("type") == "sample" and not l.get("final")]
    hits[-1]["spawnGate"]["botAmountWaves"] = "Horde"
    return ls


def m_ledger_dead(ls):
    return [l for l in ls if l.get("type") != "botSpawn"]


def m_mods_gone(ls):
    for l in ls:
        if l.get("type") == "sample":
            l["agents"].pop("mods", None)
    return ls


def m_um_gone(ls):
    for l in ls:
        if l.get("type") == "sample":
            l.pop("updateManual", None)
    return ls


# (name, mutation or None, expected exit, expected message fragment, extra argv)
CASES = [
    ("baseline must PASS",                 None,             0, "all field checks passed", []),
    ("vsync cap",                          m_vsync,          1, "can PIN p50", []),
    ("targetFrameRate cap",                m_targetfps,      1, "can PIN p50", []),
    ("display block absent",               m_display_gone,   1, "whole block ABSENT", []),
    ("platform field empty",               m_platform_empty, 1, "is empty", []),
    ("no header -> REFUSE",                m_no_header,      2, "no header line", []),
    ("no raid windows -> REFUSE",          m_no_raid,        2, "0 non-final raid windows", []),
    ("unstampedCalls non-zero",            m_unstamped,      1, "INCOMPLETE", []),
    ("paused side zero",                   m_paused_zero,    1, "needs BOTH", []),
    ("forcedButExcluded null",             m_forced_null,    1, "must not be read as an all-clear", []),
    ("forcedButExcluded non-empty",        m_forced_hit,     1, "This run is void", []),
    ("preset not AsOnline",                m_preset_wrong,   1, "not AsOnline", []),
    ("preset varies within a log",         m_preset_varies,  1, "varies WITHIN", []),
    ("spawn hook dead",                    m_ledger_dead,    1, "spawn hook is dead", []),
    ("agents.mods absent",                 m_mods_gone,      1, "agents.mods absent", []),
    ("updateManual absent",                m_um_gone,        1, "updateManual absent", []),
    # Tolerant must TOLERATE, and it must not tolerate a cap - a cap is wrong whatever
    # the build is, so --tolerant is not a way to score a capped run.
    ("tolerant: absent blocks pass",       m_um_gone,        0, "tolerant", ["--tolerant"]),
    ("tolerant: cap still FAILS",          m_vsync,          1, "can PIN p50", ["--tolerant"]),
]


def run(checker, path, extra):
    p = subprocess.run([sys.executable, checker, path] + extra,
                       capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def make_neutered(tmp):
    """A copy of the checker whose fail() records nothing.

    The point is that EVERY case below must stop failing. A case that survives this
    was passing for a reason other than the one it names.
    """
    src = open(CHECKER, encoding="utf-8").read()
    out = re.sub(r"def fail\(msg\):\n    fails\.append\(msg\)",
                 "def fail(msg):\n    pass  # NEUTERED", src, count=1)
    if out == src:
        print("REFUSED: could not neuter fail() - the pattern did not match, so a")
        print("         'suite collapsed' result would be meaningless.")
        sys.exit(2)
    dst = os.path.join(tmp, "check-fields-neutered.py")
    open(dst, "w", encoding="utf-8").write(out)
    return dst


def main():
    if not os.path.isfile(CHECKER):
        print("REFUSED: no checker at %s" % CHECKER)
        return 2

    tmp = tempfile.mkdtemp(prefix="fs-sabotage-")
    checker = make_neutered(tmp) if NEUTER else CHECKER
    if NEUTER:
        print("NEUTERED RUN: fail() records nothing, so every case that expects exit 1")
        print("MUST now collapse. The two pass cases and the two REFUSALS must not -")
        print("a refusal does not route through fail(), and that is the point of it.\n")

    passed, failed = 0, 0
    for name, mut, want_code, want_frag, extra in CASES:
        ls = baseline()
        if mut:
            ls = mut(copy.deepcopy(ls))
        path = os.path.join(tmp, re.sub(r"[^a-z0-9]+", "-", name.lower()) + ".ndjson")
        with open(path, "w", encoding="utf-8-sig") as fh:
            for l in ls:
                fh.write(json.dumps(l) + "\n")

        code, out = run(checker, path, extra)
        ok_code = code == want_code
        ok_frag = want_frag in out
        # Under --neuter the expectation inverts for the FAIL cases only. Exit 2 is a
        # refusal, and refusals go through refusals.append rather than fail() - so a
        # refusal surviving a neutered fail() is the checker being right, not wrong.
        # Asserting it here is worth a line: it says the two outcomes are genuinely
        # independent paths, which is the reason exit 2 exists at all.
        if NEUTER and want_code == 1:
            good = not (ok_code and ok_frag)
            verdict = "collapsed" if good else "SURVIVED NEUTERING"
        else:
            good = ok_code and ok_frag
            verdict = "ok" if good else "MISMATCH"

        if good:
            passed += 1
            print("  %-9s %s" % (verdict, name))
        else:
            failed += 1
            print("  %-9s %s" % (verdict, name))
            print("            wanted exit %d and %r" % (want_code, want_frag))
            print("            got    exit %d, fragment %s"
                  % (code, "present" if ok_frag else "ABSENT"))
            for ln in out.splitlines():
                if "FAIL" in ln or "REFUSED" in ln or "passed" in ln:
                    print("            | %s" % ln.strip())

    if REAL and not NEUTER:
        # The synthetic baseline cannot catch a checker and an emitter that are wrong
        # in the same direction. A real log can, and the newest one predates these
        # fields - so strict must FAIL on it and tolerant must not. Anything else
        # means absent-is-a-failure is not working.
        logs = sorted(glob.glob(os.path.join(LOGDIR, "*.ndjson")))
        if not logs:
            print("\n  REFUSED  --real asked for, no logs found in %s" % LOGDIR)
            failed += 1
        else:
            newest = logs[-1]
            print("\n  real-input control on %s" % os.path.basename(newest))
            sc, _ = run(CHECKER, newest, [])
            tc, tout = run(CHECKER, newest, ["--tolerant"])
            print("            strict exit %d (expect 1: predates the fields)" % sc)
            print("            tolerant exit %d" % tc)
            if sc == 0:
                print("            MISMATCH a pre-field log passed STRICT - "
                      "absent-is-a-failure is not working")
                failed += 1
            else:
                passed += 1
            if tc == 2:
                print("            note tolerant REFUSED - %s"
                      % next((l.strip() for l in tout.splitlines() if "REFUSED" in l), ""))

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d behaved, %d did not." % (passed, failed))
    if failed:
        print("A mismatch here means the gate on every run does not do what its "
              "message says. Fix before scoring a raid.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
