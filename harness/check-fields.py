"""Post-flight field census: refuse a run whose new telemetry is present-but-degenerate.

Six builds landed on 2026-07-29 and every one of them can fail in the way this project
keeps cataloguing - a field that emits, reads plausible, and carries nothing. This is the
check Sophia asked for when she said pre-flight can catch us. It runs on the log the
harness just produced, so ABSENT IS A FAILURE by default: the deployed build is current
by construction. Pass --tolerant to read an older log, where absent means the build
predates the field rather than the field breaking.

Deliberately Python rather than PowerShell: our ndjson carries a UTF-8 BOM and
ConvertFrom-Json chokes on it, while utf-8-sig reads it without comment. That is a
recorded trap in this project, not a preference.

THREE VERDICTS, NEVER TWO. `absent` (the build did not record it), `empty` (it looked and
could not tell), and `bad` (it recorded something wrong) are different facts and get
different exit paths. Collapsing them is how a missing instrument comes to read as a
healthy one.

EXIT CODES
    0  every check passed
    1  at least one check FAILED - do not trust this run
    2  REFUSED to report - could not read the file, or read zero raid windows

2 is separate from 1 on purpose. A check that reports a pass over zero rows is the
defect this project has hit most often, so reading nothing must be its own outcome and
must never be silent.
"""
import json
import sys

TOLERANT = "--tolerant" in sys.argv
PATHS = [a for a in sys.argv[1:] if not a.startswith("--")]

# Vsync and a frame cap are not merely unrecorded context - they can PIN p50 at the
# gate's own budget and produce a pass that is insensitive to anything the mod does.
# A false pass on the primary success criterion is worse than a null, so these two are
# hard failures rather than notes.
VSYNC_KEYS = ("vSyncCount", "targetFrameRate")

fails, notes, refusals = [], [], []
_blocks_reported = set()


def fail(msg):
    fails.append(msg)


def note(msg):
    notes.append(msg)


def block_absent(name):
    """Report a missing block ONCE, not once per key inside it.

    Found by running this against a real pre-field log: `platform` reported three
    times and `system` four, turning six distinct problems into twelve failures.
    An inflated count is not a cosmetic defect - it overstates severity and makes
    triage read the wrong way round.
    """
    if name in _blocks_reported:
        return
    _blocks_reported.add(name)
    if TOLERANT:
        note("%s: whole block absent (tolerant: build may predate it)" % name)
    else:
        fail("%s: whole block ABSENT - this build should emit it" % name)


def probe(block, name, key, *, require_truthy=True, allow_zero=False):
    """One field. Returns the value, or None having already recorded the verdict."""
    if block is None:
        block_absent(name)
        return None
    if key not in block:
        if TOLERANT:
            note("%s.%s absent (tolerant: build may predate it)" % (name, key))
        else:
            fail("%s.%s ABSENT - this build should emit it" % (name, key))
        return None
    v = block[key]
    if v is None:
        fail("%s.%s is null - could not compute, which is not the same as empty" % (name, key))
        return None
    if require_truthy and v == "":
        fail("%s.%s is empty - it looked and could not tell" % (name, key))
        return v
    if require_truthy and v == 0 and not allow_zero:
        fail("%s.%s is 0 - reads as measured-and-zero rather than unmeasured" % (name, key))
    return v


def main():
    if not PATHS:
        print("usage: check-fields.py <log.ndjson> [--tolerant]")
        return 2

    for path in PATHS:
        print("=== %s" % path)
        try:
            lines = open(path, encoding="utf-8-sig", errors="replace").read().splitlines()
        except OSError as e:
            refusals.append("cannot read %s: %s" % (path, e))
            continue

        header, raid, spawns, deaths = None, [], 0, 0
        for ln in lines:
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            t = o.get("type")
            if t == "header" and header is None:
                header = o
            elif t == "sample" and o.get("state") == "raid" and not o.get("final"):
                raid.append(o)
            elif t == "botSpawn":
                spawns += 1
            elif t == "death":
                deaths += 1

        if header is None:
            refusals.append("%s: no header line - refusing to report" % path)
            continue
        if not raid:
            # A dry run or a launch that never entered a raid. Reporting a pass over
            # zero windows is the exact defect this file exists to catch, so it is a
            # refusal rather than a pass, and it says so.
            refusals.append("%s: 0 non-final raid windows - refusing to report" % path)
            continue

        print("    header commit %s, %d raid windows" % (str(header.get("commit"))[:12], len(raid)))

        # ---- header blocks: once per file --------------------------------------
        plat = header.get("platform")
        probe(plat, "platform", "sptAssembly")
        probe(plat, "platform", "game")
        probe(plat, "platform", "unity")

        sysb = header.get("system")
        probe(sysb, "system", "cpu")
        probe(sysb, "system", "cores")
        probe(sysb, "system", "ramMb")
        probe(sysb, "system", "os")

        disp = header.get("display")
        if disp is None:
            block_absent("display")
        else:
            for k in VSYNC_KEYS:
                if k not in disp:
                    (note if TOLERANT else fail)("display.%s absent" % k)
                    continue
                v = disp[k]
                # vSyncCount 0 and targetFrameRate -1 both mean "uncapped". Any other
                # value can pin p50 at a refresh budget and pass the gate for free.
                if (k == "vSyncCount" and v not in (0,)) or (k == "targetFrameRate" and v not in (-1, 0)):
                    fail("display.%s = %r - a frame cap can PIN p50 and pass the "
                         "60 fps gate insensitively. Do not score this run." % (k, v))
                else:
                    note("display.%s = %r (uncapped)" % (k, v))
            if disp.get("refreshHz"):
                note("display.refreshHz = %r" % disp["refreshHz"])

        probe(header, "header", "commit")

        # ---- per-window blocks: checked over raid windows only ------------------
        um = [w["updateManual"] for w in raid if isinstance(w.get("updateManual"), dict)]
        if not um:
            (note if TOLERANT else fail)("updateManual absent from all %d raid windows" % len(raid))
        else:
            unstamped = sum(w.get("unstampedCalls") or 0 for w in um)
            if unstamped:
                fail("updateManual.unstampedCalls = %d over %d windows - the awake/paused "
                     "split is INCOMPLETE and the difference is over a partial roster"
                     % (unstamped, len(um)))
            else:
                note("updateManual.unstampedCalls = 0 across %d windows" % len(um))
            aw = sum(w.get("awakeCalls") or 0 for w in um)
            pa = sum(w.get("pausedCalls") or 0 for w in um)
            if not aw or not pa:
                fail("updateManual awake=%d paused=%d - the paired measurement needs BOTH "
                     "arms; a zero side makes the difference unavailable, not zero" % (aw, pa))
            else:
                note("updateManual awake=%d paused=%d calls" % (aw, pa))

        sg = [w["spawnGate"] for w in raid if isinstance(w.get("spawnGate"), dict)]
        if not sg:
            (note if TOLERANT else fail)("spawnGate absent from all %d raid windows" % len(raid))
        else:
            nulls = sum(1 for w in sg if w.get("forcedButExcluded", "MISSING") is None)
            if nulls:
                fail("spawnGate.forcedButExcluded is null in %d of %d windows - could not "
                     "compute. Null must not be read as an all-clear." % (nulls, len(sg)))
            hits = [w for w in sg if w.get("forcedButExcluded")]
            if hits:
                fail("spawnGate.forcedButExcluded is NON-EMPTY (%r) - a forced role is "
                     "blocked by a client setting. This run is void."
                     % (hits[0].get("forcedButExcluded"),))
            elif not nulls:
                # NAME THE POPULATION, because an all-clear that cannot fail over a
                # population it never sees is the exact defect this field was built to
                # prevent, one level up. BossSpawnGate intersects forced roles from the
                # DATABASE wave array against ExcludedBosses. BotSpawner.method_2
                # constructs a fresh BossLocationSpawn that never came from base.json -
                # BossChance 100, IgnoreMaxBots = forcedSpawn - and calls BossSpawner.Spawn
                # directly, so such a spawn can never appear in the intersection. It is a
                # public method taking (side, zone, profileType, difficulty, forcedSpawn),
                # which is the shape a spawn-control mod reaches for. Found by Echo on the
                # DRIP port. Use analysis/alpha-declared-vs-observed-roles.py for the
                # population this cannot see.
                note("spawnGate.forcedButExcluded empty in all %d windows - covers "
                     "DATABASE-declared spawns only, not BotSpawner.method_2 spawns"
                     % len(sg))

            amounts = set(str(w.get("botAmountWaves")) for w in sg)
            note("spawnGate.botAmountWaves = %s" % ", ".join(sorted(amounts)))
            if amounts - {"AsOnline"}:
                # Committed in c5c4d2b before either the answer or the patch existed, so
                # this is a calibration of the field rather than a test of the corpus.
                fail("botAmountWaves is not AsOnline. Sophia certified AsOnline, so either "
                     "the setting changed deliberately or THE PATCH IS WRONG - the registered "
                     "prediction now tests the field, not the corpus.")
            if len(amounts) > 1:
                fail("botAmountWaves varies WITHIN one log (%s) - population regime changed "
                     "mid-run and no analysis may pool these windows" % ", ".join(sorted(amounts)))

        # ---- ledger LIVENESS, and only liveness ---------------------------------
        # Beta's exception to the split, and it follows from why a census exists at all:
        # this file gates the run automatically, the reconciler is run by hand during
        # analysis. So a ledger that silently stops emitting - a patch that fails to
        # resolve after an SPT update, or the Player.OnDead override Beta could not rule
        # out - is found by the reconciler AFTER the session, and the fix costs raids.
        # Here it is found at the end of the raid that produced it.
        #
        # Presence is a well-formedness property; agreement is an analysis property. So
        # this checks liveness and nothing else: no pairing, no counting, no residual.
        #
        # The predicate is CROSS-INSTRUMENT rather than a bare count, so it cannot fire
        # on a genuinely empty raid: if the census ever saw a bot and the ledger never
        # saw a spawn, the hook is dead.
        saw_bots = max((w.get("bots") or {}).get("total") or 0 for w in raid)
        if not spawns:
            if TOLERANT:
                note("no botSpawn lines (tolerant: build may predate the ledger)")
            elif saw_bots:
                fail("ZERO botSpawn lines while the census counted up to %d bots. The "
                     "spawn hook is dead - and the reconciler would only find this after "
                     "the session, when the fix is re-running raids." % saw_bots)
            else:
                note("no botSpawn lines, and the census never saw a bot either")
        else:
            note("ledger live: %d botSpawn, %d death lines" % (spawns, deaths))
            if not deaths:
                # Cannot be a failure - a raid with no deaths is possible, if unlikely.
                # The reconciler fails on it per raid, where it has the context to.
                note("zero death lines. Possible, but Player.OnDead is virtual and Beta "
                     "could not rule out an override - check before trusting death data.")

        # ---- fields that shipped for raid 2 --------------------------------------
        #
        # PRESENCE-ONLY WHERE A ZERO IS THE SUCCESS CASE, and that distinction is the whole
        # reason these are separated from the probes above. Gamma's warning: under
        # `Force for all roles`, `standByBlocked` reading 0 means the flag is working - so a
        # checker that treats 0 as degenerate would fail the run that worked. Same for
        # `bossGroups.linked`, which is legitimately 0 when no garrison spawned.
        #
        # This is the mirror of the defect this file exists to catch. Elsewhere a 0 that
        # should have been a value reads as measured-and-zero; here a 0 IS the value, and
        # demanding non-zero would invent a failure.
        pct = [w["framePct"] for w in raid if isinstance(w.get("framePct"), dict)]
        if not pct:
            (note if TOLERANT else fail)("framePct absent from all %d raid windows" % len(raid))
        else:
            missing75 = sum(1 for p in pct if p.get("p75") is None)
            if missing75 == len(pct):
                (note if TOLERANT else fail)(
                    "framePct.p75 absent from all %d windows - the GATE metric. Sophia moved "
                    "the gate to p75 with a p99 guard, and without this field it exists only "
                    "on maps carrying a PresentMon capture." % len(pct))
            elif missing75:
                fail("framePct.p75 absent from %d of %d windows - partial, so any p75 quoted "
                     "would silently be over a subset" % (missing75, len(pct)))
            else:
                note("framePct.p75 present in all %d windows (the gate metric)" % len(pct))

        # Grouped by block, and `continue` rather than `break` - the first version broke out
        # of the whole loop when a block was absent, so a missing `bossGroups` silently
        # skipped `standByTransitions` entirely. One absent block hid two more. That is the
        # mirror of the defect already fixed in this file, where a missing block reported
        # once per key and turned 6 problems into 12: same failure to separate the block
        # from its contents, inverted.
        for block, keys in (("bots", ("standByBlocked",)),
                            ("bossGroups", ("linked", "heldAwake")),
                            ("standByTransitions", ("woken", "slept", "diedAwake"))):
            have = [w[block] for w in raid if isinstance(w.get(block), dict)]
            if not have:
                (note if TOLERANT else fail)("%s absent from all %d raid windows - so its %d "
                                             "field(s) are unchecked, not passing"
                                             % (block, len(raid), len(keys)))
                continue
            for key in keys:
                absent = sum(1 for h in have if key not in h)
                if absent == len(have):
                    (note if TOLERANT else fail)(
                        "%s.%s ABSENT - presence-only field, this build should emit it"
                        % (block, key))
                elif absent:
                    fail("%s.%s absent from %d of %d windows - partial emission"
                         % (block, key, absent, len(have)))
                else:
                    note("%s.%s present in all %d windows (PRESENCE-ONLY: 0 may be the "
                         "success case, so its value is deliberately not judged here)"
                         % (block, key, len(have)))

        cfgs = [w["cfg"] for w in raid if isinstance(w.get("cfg"), dict)]
        if not cfgs:
            (note if TOLERANT else fail)("cfg absent from all %d raid windows" % len(raid))
        else:
            for k in ("sleepDistance", "wakeDistance"):
                vals = {c.get(k) for c in cfgs}
                if vals == {None}:
                    (note if TOLERANT else fail)("cfg.%s ABSENT - a log that cannot say what "
                                                 "distances were in force cannot be compared "
                                                 "to one that can" % k)
                elif len(vals) > 1:
                    fail("cfg.%s VARIES within one log (%s) - a distance changed mid-run and "
                         "no analysis may pool these windows"
                         % (k, ", ".join(str(v) for v in sorted(vals, key=str))))
                else:
                    note("cfg.%s = %s" % (k, vals.pop()))

        hdr_role = header.get("roleSleep")
        if hdr_role is None:
            (note if TOLERANT else fail)("header.roleSleep ABSENT - the role-distance table in "
                                         "force is not recorded, so configuration would have to "
                                         "be inferred from behaviour later")
        else:
            note("header.roleSleep present: %s" % json.dumps(hdr_role)[:110])

        mods = [w.get("agents", {}).get("mods") for w in raid]
        present = [m for m in mods if m is not None]
        if not present:
            (note if TOLERANT else fail)("agents.mods absent from all %d raid windows" % len(raid))
        else:
            seen = sorted({m for lst in present for m in lst})
            note("agents.mods = %s (in %d of %d windows)" % (seen or "[]", len(present), len(raid)))

    # ---- report ---------------------------------------------------------------
    for m in notes:
        print("    ok    %s" % m)
    for m in fails:
        print("    FAIL  %s" % m)
    for m in refusals:
        print("    REFUSED %s" % m)

    if refusals:
        print("\nREFUSED - read nothing usable. This is NOT a pass.")
        return 2
    if fails:
        print("\n%d FAILED check(s). Do not trust this run until each is understood." % len(fails))
        return 1
    print("\nall field checks passed (%d)" % len(notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
