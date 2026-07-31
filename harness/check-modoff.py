"""Verify from the LOG that a mod-off baseline really had every lever off.

WHY THIS EXISTS. Sophia proposed a marathon with `Enabled = false` to establish what Framesaver
buys. Two problems, both silent:

  1. **There are TWO settings named `Enabled`.** `[1. Bot stand-by] Enabled` and
     `[3. Telemetry] Enabled`. Turning off the wrong one produces a raid with no telemetry at all.

  2. **`[1. Bot stand-by] Enabled = false` is not "mod off". It is "stand-by off."** It gates only
     `BotStandByInitPointsPatch:81` and `BotStandByUpdatePatch:96`. Five further levers stay live
     and four of them are engine-level:

         leakFix            true   dead-agent removal, changes the agent population
         maxDelta           0.1    caps Time.maximumDeltaTime; Unity's own value is 0.333, and
                                   0 is the setting that leaves it untouched
         asyncBudgetMs      4      caps AsyncWorker's completion drain; 0 is unbounded/vanilla
         suspendGc          true   suspends GC during completion callbacks
         drainInUpdateOnly  true   suppresses AsyncWorker's FixedUpdate drain

     A baseline with those active UNDERSTATES what the mod buys, in the direction that flatters us.

So the baseline needs ~10 hand edits, four of whose "off" values are not the obvious ones - and a
baseline that quietly kept a lever on is worse than no baseline, because it becomes the number we
quote to testers. This reads the `cfg` block written by the run itself and refuses if any lever was
active. Not the config file: the config file is what was intended, the log is what ran.

Moot-but-checked: `cullSleeping`, `skipLate`, `skipTick`, `deactivateSleeping` and `reclaimStandBy`
only act on sleeping bots, and with stand-by off nothing sleeps. They are still reported, because
"moot" is a conclusion from another field being right, and the point of this file is not to chain
conclusions.

`maxDelta` IS NOT A SETTING IN THE LOG. `cfg.maxDelta` is `Time.maximumDeltaTime` - the live engine
value, i.e. the OUTCOME. With the setting at 0 the mod writes nothing and the field reads back the
game's own value (Unity ships 0.333), so an expected-value check against 0 fails a CORRECT baseline.
The whole 520-window corpus reads 0.1 because the cap was applied in all of it, which means the
untouched value has never been observed and this file must not invent one. See OUTCOME_KEYS.

UNRULED KEYS ARE NAMED, NOT SKIPPED. A cfg key this table does not mention used to be ignored in
silence, so a lever added after this file was written would ship and still read "clean" - which is
how `forceAllRoles`, `roleSleepDist`, `roleWakeDist` and `bossGroupWake` came to be uncovered here.
Coverage is now stated in the verdict, so a pass can never be read as wider than it is.

EXIT 0 clean baseline, 1 a lever was ACTIVE, 2 REFUSED (cannot tell).
"""
import json
import os
import sys

# key -> (off value, whether it still acts with stand-by off, one-line reason)
LEVERS = {
    "standBy":           (False, True,  "the stand-by subsystem itself"),
    "leakFix":           (False, True,  "dead-agent removal changes the agent population"),
    "brainPeriod":       (0,     True,  "brain slicing; 0 is off"),
    "fastAnim":          (False, True,  "forces a cheaper body animator"),
    "maxDelta":          (0,     True,  "caps Time.maximumDeltaTime; 0 leaves Unity's 0.333 alone"),
    "asyncBudgetMs":     (0,     True,  "caps the async completion drain; 0 is unbounded/vanilla"),
    "suspendGc":         (False, True,  "suspends GC during completion callbacks"),
    "drainInUpdateOnly": (False, True,  "suppresses AsyncWorker's FixedUpdate drain"),
    "jobBudgetMs":       (0,     True,  "job scheduler budget; 0 is off"),
    "jobSlowFrames":     (-1,    True,  "job scheduler pump; -1 leaves it alone"),
    "gcTimeSliceMs":     (0,     True,  "incremental GC slice; 0 is off"),
    # The OUTCOME of gcTimeSliceMs rather than a second setting - GcControl sets it only when the
    # slice was really applied. Kept as a lever with off False because it is the one field here
    # that can contradict its own setting, which is the shape worth checking rather than trusting.
    "gcSliceApplied":    (False, True,  "whether the GC slice was actually applied; false is off"),
    "gcDriveMs":         (0,     True,  "drives incremental GC; 0 is off"),
    "cullSleeping":      (False, False, "animator culling - only acts on sleeping bots"),
    "skipLate":          (False, False, "skips sleeping bots' LateUpdate"),
    "skipTick":          (False, False, "skips sleeping bots' world tick"),
    "deactivateSleeping": (False, False, "BotState=NonActive while paused"),
    "reclaimStandBy":    (False, False, "re-grants CanDoStandBy after another mod clears it"),
    # All five read only INSIDE a stand-by patch, past its `if (!StandByEnabled) return` - verified
    # in source, not assumed: BotStandByInitPointsPatch:81 gates the read of forceAllRoles at :40's
    # role set and of RoleSleepDistance.For at :93, and BotStandByUpdatePatch:96 gates
    # BossGroupWake.HoldsAwake at :149. Listed as moot rather than omitted, because a key this file
    # does not name is a key it cannot clear.
    "forceAllRoles":     (False, False, "decides which ROLES may stand by at all - the largest of "
                                        "these; raid 1.5 slept 26 of 27 under it"),
    "keepFighting":      (False, False, "holds bots in combat awake - only acts on sleeping bots"),
    "bossGroupWake":     (False, False, "keeps a boss's followers awake with it"),
    "roleSleepDist":     (0,     False, "widened sleep radius for posted roles; 0 is the rule off"),
    "roleWakeDist":      (0,     False, "the wake half of the posted-role radius; 0 is off"),
}

# Keys the LOG reports as an OUTCOME rather than as the setting, so an equality test against the
# off value is wrong by construction. `must_not_be` is what the field reads when the mod DID act.
#
# The off value cannot be asserted positively: the mod hands the field back to the engine, so the
# clean reading is "whatever the game chose", which nothing in the corpus has ever recorded. The
# check is therefore one-sided plus a constancy requirement - it can catch the lever being on and
# it cannot certify a specific number. Pin OUTCOME_KEYS["maxDelta"]["vanilla"] once a clean
# marathon log has established the value, and this becomes a two-sided check.
OUTCOME_KEYS = {
    "maxDelta": {
        "must_not_be": [0.1],
        "vanilla": None,
        "why": "cfg.maxDelta is Time.maximumDeltaTime, not the setting. 0.1 was our cap in all "
               "520 corpus windows; Unity's own default is 0.333",
    },
}

# Emitted in the cfg block, and deliberately not levers: measurement, or a bare distance rather
# than an on/off. Named so they do not show up as unruled - the list is the ruling.
NON_LEVERS = {
    "windowSeconds":     "the telemetry window length, not a behaviour",
    "drainDiagnostics":  "measurement; on in both arms so a difference cancels it",
    "sleepDistance":     "a distance, moot with stand-by off",
    "wakeDistance":      "a distance, moot with stand-by off",
    "checkInterval":     "stand-by re-check cadence, moot with stand-by off",
    "sleepImmediately":  "stand-by grace period, moot with stand-by off",
    "minBrainsPerFrame": "brain-slicing floor, moot with brainPeriod 0",
}


# cfg key -> the section and setting name as they appear in the cfg file and the F12 panel. Here
# rather than in a separate checklist, because a checklist is a second copy of this table and would
# drift from it - the same reason the steady-state definition went into code.
UI = {
    "standBy":            ("1. Bot stand-by", "Enabled"),
    "reclaimStandBy":     ("1. Bot stand-by", "(reclaim, no direct key)"),
    "leakFix":            ("2. AI brain scheduler", "Fix dead-agent leak"),
    "brainPeriod":        ("2. AI brain scheduler", "Brain update period"),
    "fastAnim":           ("4. Experimental", "Force fast body animator"),
    "cullSleeping":       ("4. Experimental", "Cull sleeping bot animators"),
    "maxDelta":           ("4. Experimental", "Max delta time"),
    "deactivateSleeping": ("4. Experimental", "Set sleeping bots to NonActive"),
    "skipLate":           ("4. Experimental", "Skip sleeping bot LateUpdate"),
    "skipTick":           ("4. Experimental", "Skip sleeping bot world tick"),
    "jobBudgetMs":        ("4. Experimental", "Job scheduler budget ms"),
    "jobSlowFrames":      ("4. Experimental", "Job scheduler slow frames"),
    "asyncBudgetMs":      ("4. Experimental", "Async drain budget ms"),
    "suspendGc":          ("4. Experimental", "Suspend GC during completion callbacks"),
    "gcSliceApplied":     ("4. Experimental", "(outcome of GC time slice ms, no direct key)"),
    "gcTimeSliceMs":      ("4. Experimental", "GC time slice ms"),
    "gcDriveMs":          ("4. Experimental", "Drive incremental GC ms"),
    "drainInUpdateOnly":  ("4. Experimental", "Drain completions in Update only"),
    "forceAllRoles":      ("1. Bot stand-by", "Force for all roles"),
    "keepFighting":       ("1. Bot stand-by", "Keep fighting bots awake"),
    "bossGroupWake":      ("1. Bot stand-by", "Keep boss groups together"),
    "roleSleepDist":      ("1. Bot stand-by", "Posted role sleep distance"),
    "roleWakeDist":       ("1. Bot stand-by", "(derived from the above, no direct key)"),
}


def plan():
    """Print the edits a mod-off baseline needs, by the names Sophia will actually see.

    `--plan` exists so the list can be read BEFORE the raid. Everything else here checks after.
    """
    print("MOD-OFF BASELINE: the settings to change, and the four whose off value is not obvious.")
    print()
    print("LEAVE `3. Telemetry / Enabled` = true. It is a DIFFERENT setting from")
    print("`1. Bot stand-by / Enabled`, and turning off the wrong one yields no data at all.")
    print()
    print("  %-24s %-40s %s" % ("section", "setting", "set to"))
    print("  " + "-" * 76)
    for key, (off, acts, _why) in sorted(LEVERS.items(), key=lambda kv: UI.get(kv[0], ("", ""))):
        sec, name = UI.get(key, ("?", key))
        mark = "" if acts else "   (moot with stand-by off, set anyway)"
        print("  %-24s %-40s %s%s" % (sec, name, off, mark))
    print()
    print("The four that are ON in the current config and whose off value is counter-intuitive:")
    print("  Max delta time                     -> 0      (0 leaves Unity's 0.333 alone; 0.1 caps it)")
    print("  Async drain budget ms              -> 0      (0 is UNBOUNDED, i.e. vanilla)")
    print("  Suspend GC during completion cbs   -> false")
    print("  Drain completions in Update only   -> false")
    print("  and `Fix dead-agent leak` -> false, which defaults true and is easy to read as a")
    print("  bug fix rather than a behaviour change. It changes the agent population.")
    print()
    print("Then run this file against the log to verify it from what RAN, not what was intended.")
    return 0


def main():
    if len(sys.argv) < 2:
        print("usage: check-modoff.py <log.ndjson> | --plan")
        return 2
    if sys.argv[1] == "--plan":
        return plan()
    path = sys.argv[1]
    if not os.path.isfile(path):
        print("REFUSED: no such log: %s" % path)
        return 2

    header, cfgs, n_raid = None, [], 0
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") == "header" and header is None:
            header = o
        elif o.get("type") == "sample" and o.get("state") == "raid" and not o.get("final"):
            n_raid += 1
            if o.get("cfg"):
                cfgs.append(o["cfg"])

    if header is None:
        print("REFUSED: no header line")
        return 2
    if not n_raid:
        print("REFUSED: 0 non-final raid windows - a pass over zero windows is the defect this")
        print("         file exists to catch")
        return 2
    if not cfgs:
        print("REFUSED: %d raid windows and NONE carries a cfg block. This build cannot say what"
              % n_raid)
        print("         was in force, so the baseline is unverifiable rather than clean.")
        return 2

    print("%s" % os.path.basename(path))
    print("  header commit %s, %d raid windows, %d with cfg"
          % (str(header.get("commit"))[:12], n_raid, len(cfgs)))

    # Telemetry must have been ON or there would be no log - stated because it is the OTHER
    # setting called `Enabled`, and confusing the two is the first failure this file guards.
    print("  telemetry was on (this log exists), which is the OTHER setting named `Enabled`")

    active, absent, moot_on = [], [], []
    for key, (off, acts, why) in sorted(LEVERS.items()):
        if key in OUTCOME_KEYS:
            continue  # handled below - the log reports the outcome, not the setting
        vals = [c.get(key) for c in cfgs]
        if all(v is None for v in vals):
            absent.append(key)
            continue
        distinct = sorted(set(v for v in vals if v is not None), key=repr)
        bad = [v for v in distinct if v != off]
        if not bad:
            continue
        shown = ", ".join(repr(v) for v in distinct)
        if acts:
            active.append("%-18s = %s   (off is %r) - %s" % (key, shown, off, why))
        else:
            moot_on.append("%-18s = %s   %s" % (key, shown, why))

    # Outcome fields, one-sided. An equality test here would fail a correct baseline: see the
    # module docstring. Constancy is required as well, because a mid-raid edit would leave half the
    # windows capped and a single-value report would hide it.
    for key, spec in sorted(OUTCOME_KEYS.items()):
        vals = [c.get(key) for c in cfgs]
        if all(v is None for v in vals):
            absent.append(key)
            continue
        distinct = sorted(set(v for v in vals if v is not None), key=repr)
        if len(distinct) > 1:
            active.append("%-18s = %s   NOT CONSTANT across windows - %s"
                          % (key, ", ".join(repr(v) for v in distinct), spec["why"]))
        elif distinct[0] in spec["must_not_be"]:
            active.append("%-18s = %r   this is the value the mod IMPOSES - %s"
                          % (key, distinct[0], spec["why"]))
        elif spec["vanilla"] is not None and distinct[0] != spec["vanilla"]:
            active.append("%-18s = %r   expected the established vanilla %r - %s"
                          % (key, distinct[0], spec["vanilla"], spec["why"]))
        else:
            print("  outcome %-18s = %r   constant, and not the value the mod imposes."
                  % (key, distinct[0]))
            if spec["vanilla"] is None:
                print("           - the untouched value has never been recorded, so this run")
                print("             ESTABLISHES it. Pin it in OUTCOME_KEYS to make the check")
                print("             two-sided; until then a wrong-but-not-0.1 value would pass.")

    # Keys present in the log that this file has no ruling on. Reported loudly because the silent
    # version of this is how four levers came to be uncovered: a checker that ignores what it does
    # not recognise reports "clean" for a run it never examined.
    ruled = set(LEVERS) | set(NON_LEVERS)
    unruled = sorted(set(k for c in cfgs for k in c) - ruled)

    for line in active:
        print("  ACTIVE  %s" % line)
    for line in moot_on:
        print("  moot    %s" % line)
    if unruled:
        print("  UNRULED %s" % ", ".join(unruled))
        print("           - emitted by this build and not covered by this check. NOT cleared:")
        print("             each needs a ruling on whether it acts with stand-by off.")
    if absent:
        print("  not emitted by this build: %s" % ", ".join(absent))
        print("           - absent is NOT off. A lever this build cannot report is a lever this")
        print("             check cannot clear, which is why the next line is a refusal.")

    win = sorted(set(c.get("windowSeconds") for c in cfgs if c.get("windowSeconds") is not None))
    if win:
        print("  windowSeconds %s" % ", ".join(str(w) for w in win))
        print("           - a baseline compared against 60 s logs by MEDIAN OF WINDOWS must not")
        print("             pool the two lengths: a 30 s window covers half the time and gets")
        print("             equal weight. Per-FRAME percentiles from PresentMon are unaffected.")

    # WHAT A CLEAN RESULT HERE STILL DOES NOT MEAN. Stated on every run rather than in a doc,
    # because a checker that prints "clean" and nothing else invites the reading that the baseline
    # is vanilla. Beta's audit of the five acting levers, 2026-07-30:
    #
    #  * `leakFix = false` does NOT remove our replacement of `AICoreControllerClass.Update` - that
    #    runs whenever telemetry is on, and telemetry must be on for this raid to produce anything.
    #    It mirrors vanilla (same drain of HashSet_1 into HashSet_0.Remove, deliberately not
    #    clearing), with one known difference: our SafeUpdate LOGS the first few agent exceptions
    #    where vanilla swallows them silently, capped at ten distinct offenders. So the baseline is
    #    "our replacement behaving like vanilla", not vanilla. **Structural: it cannot be turned off
    #    without turning off the measurement.**
    #  * `Profile player loop` instruments the Unity player loop and stays on, because the mod-on
    #    corpus has it on and removing it would change the comparison rather than clean it.
    #
    # Both are present in BOTH arms, so a mod-on-minus-mod-off difference still cancels them. They
    # bound what the baseline can be called, not what it can be compared to.
    print("  A clean result below means every CONFIGURABLE lever was off. It does not mean vanilla:")
    print("    - our AICoreControllerClass.Update replacement runs whenever telemetry is on, and")
    print("      mirrors vanilla except that it logs the first few agent exceptions (cap 10).")
    print("    - the player-loop profiler stays on, as it is on in the mod-on corpus.")
    print("    Both are in BOTH arms, so a mod-on minus mod-off difference cancels them.")

    print()
    if absent:
        print("REFUSED: %d lever(s) unreportable by this build." % len(absent))
        return 2
    if active:
        print("%d LEVER(S) ACTIVE. This is not a mod-off baseline - it understates what the mod"
              % len(active))
        print("buys, in the direction that flatters us. Do not quote it to testers.")
        return 1
    print("Clean mod-off baseline: every lever this file rules on was at its off value, telemetry")
    print("on. Coverage: %d lever(s) ruled, %d outcome field(s), %d non-lever(s) named, %d UNRULED."
          % (len(LEVERS) - len(OUTCOME_KEYS), len(OUTCOME_KEYS), len(NON_LEVERS), len(unruled)))
    if unruled:
        print("The unruled keys above are not part of this clean result.")
    if moot_on:
        print("(%d sleeping-bot lever(s) left on, which cannot act with stand-by off - reported"
              % len(moot_on))
        print(" rather than excused, because 'moot' is a conclusion from another field.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
