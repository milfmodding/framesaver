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

# Telemetry keys retired at a known build, and WHAT THEY ACTUALLY HELD before it.
#
# check-modoff.py has a RETIRED table and it is the right pattern - but it
# iterates against `cfgs`, so it matches CONFIG keys only. Putting `bots.*`
# telemetry in it prints "absent, as expected" on every log forever while
# matching nothing: a check that cannot fail, inside the guard added to
# record a retirement. Beta found that by trying to use it. Hence a second,
# telemetry-scoped table here rather than a shared one.
#
# RETIRED MEANS RENAMED, NOT VOID, and that is the load-bearing half. A
# future reader meeting a retired key must not discard the column: five days
# of `deadAwake` are the only measurements of stand-by-blocking anyone has,
# and the map-structure result rests on them. The failure this table exists
# to prevent is losing good data to tidiness.
RETIRED_BOTS = {
    "deadAwake": (
        "carried the !StandBy.CanDoStandBy count - stand-by-BLOCKED, never a death "
        "count. Transposed at the CountBots call site from 2026-07-30 (7e254c0, "
        "cb47968) until the rename. REAL, USABLE DATA UNDER A WRONG NAME: do not "
        "discard the column. Superseded by bots.standByRefused."),
    "standByBlocked": (
        "carried the TRUE dead-awake count, which is 0 in every window ever "
        "recorded because BotSpawner.BotDied removes a bot from the ticked roster "
        "in the same call that flags it dead. The name and the contents were "
        "swapped with deadAwake. Not superseded - the quantity is unreachable and "
        "updateManual.deadCalls is the tripwire for it."),
}

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

        header, raid, spawns, deaths, standby = None, [], 0, 0, 0
        # Every sample in file order, including `final` and non-raid, because segment position is
        # what identifies a teardown window and that cannot be computed from the filtered list.
        all_samples = []
        # Every `type` seen, counted. Beta found that this chain was an if/elif with no else, so an
        # unknown line type fell through in total silence - which is comfortable when a new build
        # adds one and dangerous when a build STOPS emitting one, because both look like nothing.
        # Counting every type turns "I do not recognise this" into a printed fact.
        seen_types = {}
        for ln in lines:
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            t = o.get("type")
            seen_types[t] = seen_types.get(t, 0) + 1
            if t == "header" and header is None:
                header = o
            elif t == "sample" and o.get("state") == "raid" and not o.get("final"):
                raid.append(o)
            elif t == "botSpawn":
                spawns += 1
            elif t == "death":
                deaths += 1
            elif t == "botStandBy":
                standby += 1
            if t == "sample":
                all_samples.append(o)

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
        # The types the FORMAT legitimately has, not the types this chain dispatches on. The first
        # version listed only the latter, so `census`, `mark` and `spike` reported as unrecognised
        # on every log in the corpus - a warning that fires on everything is a warning nobody reads,
        # and it would have trained the next person to skip the line that matters.
        known = {"header", "sample", "botSpawn", "death", "botStandBy",
                 "census", "mark", "spike"}
        extra = sorted(k for k in seen_types if k not in known)
        if extra:
            print("    line types this checker does not know: %s"
                  % ", ".join("%s x%d" % (k, seen_types[k]) for k in extra))
            notes.append("%s: unrecognised line type(s) %s - not an error, but a field nobody "
                         "registered is a field nobody checks" % (path, ", ".join(map(str, extra))))

        # ---- the census either ran or it did not, and zero cannot say which ------
        #
        # Beta found that `CountBots` has three early returns before its loop - not instantiated,
        # null controller, null bots - and every one leaves `awake` and `asleep` at 0. So
        # `bots.awake == 0` means either "nothing qualified" or "the census did not run", and the
        # field alone cannot discriminate. Absent-is-not-zero, in the oldest field we have.
        #
        # It needs no new telemetry to DETECT, which is why this is here rather than waiting on a
        # build: a bot must be either awake or paused, so `awake + asleep == 0` while `agents.live`
        # is non-zero is not a reachable state. `agents.live` comes from a different source
        # (AICoreControllerUpdatePatch.LiveAgents) that never touches Singleton<IBotGame>, so the
        # two fail independently - which is what makes the pair an instrument and either one alone
        # not.
        #
        # Those windows survived analysis only because a zero census makes a ratio NaN and an empty
        # paused bucket drops the row. Two accidents, neither a check.
        # SPLIT BY SEGMENT POSITION, because the first version of this check would have fired once
        # per map on every marathon log. Beta and Gamma traced the cause and I verified it: ALL 33
        # zero-census windows in the corpus are the LAST in-raid window of their segment, 33 of 33,
        # no exceptions. Raid teardown - Singleton<IBotGame> is gone when the census reads at window
        # close. So a teardown zero is expected and a MID-SEGMENT zero is a real defect, and firing
        # on both makes the check unreadable.
        #
        # `final` is NOT the flag for this and never was: it means "the session ended", so it marks
        # 17 of the 33. A reader keying on it misses 16. (That 16 is exactly what I counted before
        # knowing the cause - the non-final subset - which is how the three different counts we
        # traded, 16/23/33, reconcile.)
        #
        # Segment = consecutive in-raid samples sharing (raid, map). Last-in-segment means the next
        # sample is not an in-raid window of the same segment, or there is no next.
        last_ids = set()
        for i, o in enumerate(all_samples):
            if o.get("state") != "raid":
                continue
            key = (o.get("raid"), str(o.get("map")))
            nxt = all_samples[i + 1] if i + 1 < len(all_samples) else None
            if (nxt is None or nxt.get("state") != "raid"
                    or (nxt.get("raid"), str(nxt.get("map"))) != key):
                last_ids.add(id(o))

        def blind_p(w):
            b, a = w.get("bots") or {}, w.get("agents") or {}
            return (b.get("awake") == 0 and (b.get("asleep") or 0) == 0
                    and (a.get("live") or 0) > 0)

        teardown = [w for w in raid if blind_p(w) and id(w) in last_ids]
        midraid = [w for w in raid if blind_p(w) and id(w) not in last_ids]

        if midraid:
            ex = midraid[0]
            fails.append("%s: %d MID-SEGMENT window(s) have bots.awake+asleep == 0 while "
                         "agents.live > 0 - the roster census did not run and it is NOT teardown, "
                         "which is the only benign cause known. First: map=%s window=%s "
                         "elapsed=%ss live=%s"
                         % (path, len(midraid), ex.get("map"), ex.get("window"),
                            round(ex.get("raidElapsed") or 0),
                            (ex.get("agents") or {}).get("live")))
        if teardown:
            marked = sum(1 for w in teardown if w.get("final"))
            notes.append("%s: %d teardown window(s) - last of their segment, census did not run. "
                         "EXCLUDE bots.* and the instant-sampled fields (snipersAwake, animCulled) "
                         "from these; their FRAME data is fine. `final` marks only %d of %d, so do "
                         "not key on it. They are also truncated, so any per-second rate in them "
                         "has a denominator that means nothing."
                         % (path, len(teardown), marked, len(teardown)))
            print("    %d teardown window(s) identified by segment position (final marks %d)"
                  % (len(teardown), marked))
        if not midraid and not teardown:
            print("    roster census ran in all %d raid windows (awake+asleep vs agents.live)"
                  % len(raid))

        # ---- botStandBy: PRESENCE-ONLY, and paired with botSpawn -----------------
        #
        # Presence-only on Beta's recommendation and for their reason: `effective` being false on
        # every bot is the CORRECT reading under `forceAllRoles = false`, so a checker that treated
        # all-false as degenerate would fail the control arm of raid 2. The invariant is one line
        # per bot per raid, not any particular value in it.
        #
        # Paired with `botSpawn` because the two now come from opposite ends of one lifecycle -
        # `BotOwner.Create` and `BotStandBy.InitPoints`. Spawns without stand-by lines means bots
        # were created and never activated, which is a real failure mode nothing else detects.
        #
        # This is the field the bot-level contrast rests on: it carries the per-bot ARM. If the
        # emit is ever dropped in a refactor the reader finds no rows and reports a coverage gap,
        # which reads identically to a raid where nothing activated. Hence a gate rather than a
        # note.
        if spawns and not standby:
            fails.append("%s: %d botSpawn lines and ZERO botStandBy. Three causes look identical "
                         "here and only the third is benign: the emit is broken; no bot ever "
                         "activated; or the build predates bc90b76 and never had the field. This "
                         "checker tests the CURRENT build's fields, so a pre-bc90b76 log is "
                         "EXPECTED to fail this - check the header commit before treating it as a "
                         "defect. On a fresh run it means the per-bot arm label for raid 2 is "
                         "silently absent" % (path, spawns))
        elif standby:
            ratio = (100.0 * standby / spawns) if spawns else 0.0
            if spawns and standby < 0.5 * spawns:
                fails.append("%s: %d botStandBy against %d botSpawn (%.0f%%). One line per bot at "
                             "activation is the invariant; under half means the emit is dropping "
                             "bots, not that bots failed to activate" % (path, standby, spawns, ratio))
            else:
                print("    botStandBy %d line(s) against %d botSpawn (%.0f%%)"
                      % (standby, spawns, ratio))
        elif not spawns:
            print("    botStandBy and botSpawn both absent - pre-era build, not a failure")

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
        # `Force for all roles`, `standByRefused` reading 0 means the flag is working - so a
        # checker that treats 0 as degenerate would fail the run that worked. Same for
        # `bossGroups.linked`, which is legitimately 0 when no garrison spawned.
        #
        # The key here was `standByBlocked` until the rename. It is now
        # `standByRefused`, and the rule is unchanged because the QUANTITY is
        # unchanged - `!StandBy.CanDoStandBy` is what the old key was always
        # meant to hold. See RETIRED_BOTS below for what it actually held.
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
        for block, keys in (("bots", ("standByRefused",)),
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

        # ---- updateManual.deadCalls: THE MIRROR OF THE BLOCK ABOVE ---------------
        #
        # Here rather than beside the other updateManual checks, because it is the
        # OPPOSITE of the presence-only rules directly above and the next reader
        # should meet the pair together. Up there a 0 IS the value and demanding
        # non-zero would invent a failure. Here 0 is the value and any non-zero is
        # the alarm.
        #
        # WHY 0 IS CORRECT, and it is a property of the game rather than of us.
        # BotSpawner.BotDied sets `bot.IsDead = true` (:624) and calls
        # `Bots.Remove(bot)` (:634) inside one method, so a bot leaves the roster
        # in the same event that flags it dead - and UpdateByUnity ticks that same
        # HashSet_0. The postfix cannot meet a corpse. Read off the installed SPT
        # 4.0.13 assembly 2026-08-04; measured 0 in 205 of 205 windows.
        #
        # SO IT FIRES ONLY IF THE GAME CHANGED UNDER US. That is the point: the
        # consumers already swallow a non-zero in silence. Counted, not asserted -
        # `deadCalls` across analysis/ and harness/ is 4 files, of which THREE
        # read the value:
        #
        #     read-updatemanual.py:412            calls -= deadCalls
        #     alpha-animator-aggregate.py:105     (awakeCalls - deadCalls)/frames
        #     delta-modoff-gating-ceiling.py:125  deadCalls / frames
        #
        # The fourth (delta-corpse-roster-sweep.py:33) only names it in prose, and
        # harness/ asserts on it NOWHERE - which is what this check changes. All
        # three were calibrated over a history in which the field was structurally
        # zero, so a non-zero does not break them loudly. It shifts every per-bot
        # cost figure quietly.
        #
        # ABSENT IS NOT ZERO. `sum(... or 0)` would read a dropped emit as a clean
        # pass - the tripwire reporting that the tripwire is fine. So presence is
        # counted separately, a partial emission fails rather than averaging, and
        # absent follows this file's contract: a failure by default because the
        # deployed build is current by construction, a note under --tolerant where
        # the build may legitimately predate 86407a4.
        if not um:
            note("deadCalls unchecked - updateManual is absent (reported above). An "
                 "unchecked tripwire is not a passing one.")
        else:
            carrying = [u for u in um if u.get("deadCalls") is not None]
            if not carrying:
                (note if TOLERANT else fail)(
                    "updateManual.deadCalls ABSENT from all %d windows - the corpse tripwire is "
                    "not armed here. Builds before 86407a4 predate the field; a current build "
                    "reaching this line has dropped it." % len(um))
            elif len(carrying) < len(um):
                fail("updateManual.deadCalls absent from %d of %d windows - partial emission, so "
                     "a zero over the remainder would be over a subset rather than over the run"
                     % (len(um) - len(carrying), len(um)))
            else:
                hot = [u for u in carrying if (u.get("deadCalls") or 0) != 0]
                if hot:
                    worst = max((u.get("deadCalls") or 0) for u in hot)
                    fail("updateManual.deadCalls NON-ZERO in %d of %d windows (max %d) - EXPECTED "
                         "0 in every window. A corpse was ticked while flagged dead, so "
                         "BotSpawner.BotDied no longer removes from the roster as it sets IsDead. "
                         "awakeCalls is inflated by corpse ticks and every per-bot cost figure "
                         "from this log is biased low. Do not score it; re-check the assembly."
                         % (len(hot), len(carrying), worst))
                else:
                    note("updateManual.deadCalls 0 in all %d windows (TRIPWIRE ARMED: 0 is the "
                         "correct reading and any non-zero is an alarm - the mirror of the "
                         "presence-only fields above)" % len(carrying))

        # ---- retired bots.* keys: present means this build predates the rename ----
        #
        # Direction is the opposite of every other check here. Elsewhere ABSENT is
        # the failure because the deployed build is current by construction. For a
        # retired key, PRESENT is the failure for exactly the same reason - a
        # current build still emitting it means the removal regressed.
        #
        # Under --tolerant, present is expected and the note says what the key
        # actually held, because a reader opening an old log is the person most
        # likely to take the name at face value. That note is the whole point of
        # the table: the era is discriminable from the key set alone, with no
        # build sha and no date, BECAUSE both names were retired rather than one
        # being reused.
        bots_blocks = [w["bots"] for w in raid if isinstance(w.get("bots"), dict)]
        if not bots_blocks:
            note("no bots block in any raid window - retired-key check did not run, "
                 "which is not the same as passing")
        else:
            for key, meant in sorted(RETIRED_BOTS.items()):
                seen = sum(1 for b in bots_blocks if key in b)
                if not seen:
                    note("bots.%s absent from all %d windows, as expected after the rename"
                         % (key, len(bots_blocks)))
                elif TOLERANT:
                    note("bots.%s present in %d of %d windows - PRE-RENAME LOG. That key %s"
                         % (key, seen, len(bots_blocks), meant))
                else:
                    fail("bots.%s present in %d of %d windows - RETIRED, and this build should "
                         "not emit it. Either the removal regressed, or this is an older log "
                         "and wants --tolerant. That key %s"
                         % (key, seen, len(bots_blocks), meant))

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
