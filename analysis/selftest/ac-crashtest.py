"""Crash-test read-animcull.py. Paths only; every count here is constructed.

  A  no animCulledEngine at all        -> REFUSED, rc=1 (the corpus state)
  B  clean ABAB, skipLate off          -> readable, rc=0, latch DESIGNED OUT
  C  cull arm, engine 0                -> delivery FAIL, rc=1
  D  cull arm, engine == asleep but    -> write-landing FAIL, rc=1
     animCulled far above it
  E  control arm with skipLate ON,     -> LATCHED, rc=1
     engine still high
  F  control arm with skipLate ON,     -> no latch, and it says the check was
     engine near 0                        LIVE rather than DESIGNED OUT
  G  bots.awake moves with the arm     -> confound FAIL, rc=1
  H  field on some windows only        -> PARTIAL warned, still scored
  I  an arm with no sleeping bots      -> UNSCORABLE, not a clean pass
  J  two windows per arm               -> below MIN_WINDOWS, refused

F IS THE ONE THAT MATTERS AND IT IS THE BORING ONE. E and F differ only in the
engine count; if section 4 printed DESIGNED OUT for both, the reader would be
reporting "a latch cannot happen here" about a run where it demonstrably could,
and E's pass would be luck. A case that cannot fail for the reason it was
written reports a pass -- see the README.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
READER = os.path.join(HERE, "..", "read-animcull.py")

WINDOW = 60.0


def win(idx, cull, skip, asleep, awake, engine, asked=None, field=True):
    """One steady sample line in a stated arm."""
    bots = {"awake": awake, "asleep": asleep, "total": awake + asleep,
            "animCulled": asleep if asked is None else asked,
            "animCulledOffScreen": max(0, asleep - 2)}
    if field:
        bots["animCulledEngine"] = engine
    return {"type": "sample", "state": "raid", "window": idx,
            "raid": 1, "map": "lighthouse", "final": False,
            "frames": 3000, "raidElapsed": 240.0 + WINDOW * idx,
            "flushedByProtocol": False,
            "cfg": {"cullSleeping": cull, "skipLate": skip,
                    "windowSeconds": WINDOW},
            "bots": bots}


def abab(cull_engine, ctrl_engine, skip=False, asked=None, field=True,
         awake_on=8, awake_off=8, per_arm=4, asleep=20, ctrl_asleep=None):
    """Header plus an ABAB run, four windows per arm by default.

    A trailing non-raid line so the last in-raid window of the segment is not
    the teardown one -- otherwise steady.partition() drops a scored window and
    the case silently tests one arm short.
    """
    lines = [{"type": "header", "windowSeconds": WINDOW,
              "config": {"windowSeconds": WINDOW}}]
    idx = 0
    for _ in range(per_arm):
        lines.append(win(idx, False, skip,
                         asleep if ctrl_asleep is None else ctrl_asleep,
                         awake_off, ctrl_engine, asked, field))
        idx += 1
        lines.append(win(idx, True, False, asleep, awake_on, cull_engine,
                         asked, field))
        idx += 1
    lines.append({"type": "sample", "state": "menu", "window": idx,
                  "raidElapsed": 0.0, "final": True})
    return lines


def run(name, lines, extra=()):
    path = os.path.join(HERE, "ac-%s.ndjson" % name)
    with open(path, "w", encoding="utf-8") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")
    print("=" * 70)
    print("CASE %s" % name)
    print("=" * 70)
    r = subprocess.run([sys.executable, READER, path],
                       capture_output=True, text=True)
    keys = list(KEYS) + list(extra)
    for ln in r.stdout.splitlines():
        if any(k in ln for k in keys):
            print(ln)
    if r.stderr.strip():
        print("STDERR:\n" + r.stderr)
    print("rc=%d\n" % r.returncode)


KEYS = ["REFUSED", "PARTIAL", "FAIL", "ok", "kept", "present in",
        "DESIGNED OUT", "LATCHED", "was live", "UNSCORABLE", "unscorable",
        "window(s)", "spread", "engine", "Readable", "NOT TESTED",
        "nothing to"]

# A. Every log before 86a13bb. The refusal must fire with windows PRESENT --
#    "0 of 0" would refuse for the wrong reason and prove nothing.
run("absent", abab(20, 0, field=False))

# B. The shipped protocol, working.
run("clean", abab(20, 0))

# C. Cull arm never reached the engine.
run("nodelivery", abab(0, 0))

# D. We marked 20, the engine honoured 6: the inert-animator shape. BOTH
#    ratios fail here and that is correct -- asleep and animCulled are equal,
#    so there is no way for them to disagree. Which is why D2 exists.
run("noland", abab(6, 0, asked=20))

# D2. THE CASE THAT SEPARATES THE TWO FAILURES, and D alone did not. Here we
#     marked only 6 of 20 sleeping bots and the engine honoured all 6: the
#     write is landing perfectly and the MARKING is short. Delivery must FAIL
#     and landing must pass, or the two lines are one check printed twice.
run("undermarked", abab(6, 0, asked=6))

# E. Latch: control arm runs with skipLate on and is still culling.
run("latched", abab(20, 18, skip=True))

# F. Same configuration, no latch. Must say the check was LIVE.
run("latchable_clean", abab(20, 0, skip=True))

# G. The arm moved something other than the cull.
run("awake_moved", abab(20, 0, awake_on=4, awake_off=12))

# H. Field appeared mid-run. Built by hand: abab() cannot express it.
#    per_arm=6 on purpose. The first version used the 4-window default, and
#    stripping 3 windows left every arm under MIN_WINDOWS -- so it exited on
#    the window-count refusal and never reached the PARTIAL scoring it was
#    written to test. It failed, for the wrong reason, and read as a pass.
mixed = abab(20, 0, per_arm=6)
for o in mixed:
    if o.get("type") == "sample" and (o.get("window") or 0) < 3:
        (o.get("bots") or {}).pop("animCulledEngine", None)
run("partial", mixed)

# I. A control arm with nobody asleep. engine/asleep is 0/0, and the tempting
#    reading is "0 <= 0.10, clean". It is a division by zero wearing a pass.
run("noasleep", abab(20, 0, ctrl_asleep=0))

# J. Two windows per arm.
run("thin", abab(20, 0, per_arm=2))
