"""Reconcile the bot ledger against the bot census. Two instruments, one population.

`bots.total` is a CENSUS - how many bots exist right now, counted by walking them.
Spawns minus deaths is a LEDGER - how many should exist, accumulated from events.
They are built from different code paths that read nothing from each other, so they are
independent, and independence is the whole point: where they disagree the residual is
the DESPAWN COUNT, which no instrument we have can currently see at all
(ZonesLeaveController removes bots without killing them).

THE SIGN IS THE DIAGNOSIS, and this is the part worth getting right:

    ledger > census    bots left without dying. That is the despawn count - a
                       measurement we did not have, not a defect.
    ledger < census     the census sees bots the ledger never recorded spawning.
                       THAT is a defect: a missed spawn hook.

So a positive residual is reported and a negative one fails. A check that failed on
both would be unable to tell us the thing it exists to discover.

CONTRACT, from Beta (af3a3e0). Written against their names, not mine:
  botSpawn  qpc window state raidElapsed id role isAI pos canStandBy
  death     qpc window state raidElapsed id role isAI pos damageType bodyPart
            killerState{named|none|unread} killer{id,role,isAI}|null

TWO CONTRACT TRAPS, both from Beta and both load-bearing:

  1. The type is `death`, NOT `botDeath`, because Player.OnDead fires for Sophia too.
     PAIR ON id WHERE isAI - her death has no matching botSpawn by construction, and an
     unfiltered pairing reports the missed-hook signature every single raid. A false
     positive baked into the contract.
  2. Players are POOLED, so an id may legitimately recur across raids in one session -
     the Marathon case. Everything here is scoped by the sample stream's `raid` ordinal
     rather than by file, and cross-raid id reuse is reported rather than treated as a
     duplicate.

UNTESTED AGAINST REAL DATA. No deployed build emits these lines yet, so this is written
against a contract and exercised against a synthetic that deliberately contains the
awkward cases (a non-AI death, a death with no spawn, a duplicate id, an event outside
any window, id reuse across raids). A synthetic shares the assumptions of whoever built
it - the first real run is the real test, and this file should be re-read after it.

EXIT 0 pass, 1 failed, 2 refused to report.
"""
import json
import sys
from collections import defaultdict

PATHS = [a for a in sys.argv[1:] if not a.startswith("--")]
fails, notes, refusals = [], [], []


def fail(m):
    fails.append(m)


def note(m):
    notes.append(m)


def load(path):
    """Samples, spawn events and death events. Returns None if the file is unusable."""
    try:
        lines = open(path, encoding="utf-8-sig", errors="replace").read().splitlines()
    except OSError as e:
        refusals.append("cannot read %s: %s" % (path, e))
        return None
    samples, spawns, deaths, other = [], [], [], 0
    for ln in lines:
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        t = o.get("type")
        if t == "sample":
            samples.append(o)
        elif t == "botSpawn":
            spawns.append(o)
        elif t == "death":
            deaths.append(o)
        else:
            other += 1
    return samples, spawns, deaths, other


def check(path):
    got = load(path)
    if got is None:
        return
    samples, spawns, deaths, _ = got

    if not samples:
        refusals.append("%s: no sample lines - refusing to report" % path)
        return
    if not spawns and not deaths:
        # Distinguish "this build does not emit the ledger" from "the ledger is empty",
        # because a reconciliation over zero events would otherwise print a clean pass.
        refusals.append("%s: no botSpawn and no death lines - either the build predates "
                        "the ledger or nothing was emitted. Refusing to report." % path)
        return

    # window -> the sample that closed it. `window` is monotone across a whole file and
    # never resets, so it is a global key; `raid` is the per-raid ordinal.
    byw = {}
    for s in samples:
        w = s.get("window")
        if w is not None:
            byw[w] = s
    ordered = sorted(byw)
    print("=== %s" % path)
    print("    %d samples over windows %s..%s, %d raids, %d botSpawn, %d death"
          % (len(samples), ordered[0], ordered[-1],
             len({s.get("raid") for s in samples}), len(spawns), len(deaths)))

    # ---- the contract's own filter, made visible rather than silent ---------------
    ai_deaths = [d for d in deaths if d.get("isAI") is True]
    human_deaths = [d for d in deaths if d.get("isAI") is not True]
    note("deaths: %d AI, %d non-AI (the non-AI are Sophia and are excluded from pairing)"
         % (len(ai_deaths), len(human_deaths)))
    if deaths and not ai_deaths:
        fail("every death line has isAI != true. Either no bot died, or isAI is not being "
             "set - and those are different facts this check cannot separate.")

    # ---- ordinal against containment, never ordinal alone ------------------------
    # Beta emits `window` and I check it rather than trust it. A sample's qpc is stamped
    # at window END, so an event belongs to the first window whose qpc is >= its own.
    ends = [(w, byw[w].get("qpc")) for w in ordered if byw[w].get("qpc") is not None]
    mismatch, unplaced = 0, 0
    for ev in spawns + deaths:
        w, q = ev.get("window"), ev.get("qpc")
        if w is None or w not in byw:
            unplaced += 1
            continue
        if q is None:
            continue
        expect = next((ww for ww, qq in ends if qq >= q), None)
        if expect is not None and expect != w:
            mismatch += 1
    if mismatch:
        fail("%d event(s) carry a `window` that disagrees with qpc containment. The "
             "ordinal is a claim and containment is the check; they must agree." % mismatch)
    else:
        note("every placed event's window ordinal agrees with qpc containment")
    if unplaced:
        # Beta emits these deliberately rather than dropping them. A spawn during loading
        # that vanished would later be inferred back as "did not spawn".
        note("%d event(s) name no window in this file - emitted and marked, not dropped"
             % unplaced)

    # ---- per raid ---------------------------------------------------------------
    raid_of_window = {w: byw[w].get("raid") for w in ordered}
    sp_by_raid, de_by_raid = defaultdict(list), defaultdict(list)
    for ev in spawns:
        sp_by_raid[raid_of_window.get(ev.get("window"))].append(ev)
    for ev in ai_deaths:
        de_by_raid[raid_of_window.get(ev.get("window"))].append(ev)

    ids_seen_in = defaultdict(set)
    for r, evs in sp_by_raid.items():
        for e in evs:
            ids_seen_in[e.get("id")].add(r)
    reused = {i: rs for i, rs in ids_seen_in.items() if len(rs) > 1}
    if reused:
        note("%d id(s) appear in more than one raid - expected, Players are pooled; "
             "scoping by raid is what makes that harmless" % len(reused))

    for r in sorted(x for x in sp_by_raid if x is not None):
        sp, de = sp_by_raid[r], de_by_raid.get(r, [])
        sp_ids = defaultdict(int)
        for e in sp:
            sp_ids[e.get("id")] += 1
        dupes = {i: n for i, n in sp_ids.items() if n > 1}
        orphan_deaths = [d for d in de if d.get("id") not in sp_ids]

        print("    raid %s: %d spawns (%d distinct ids), %d AI deaths"
              % (r, len(sp), len(sp_ids), len(de)))
        if dupes:
            fail("raid %s: %d id(s) spawned more than once within ONE raid - a double hook, "
                 "or a Player recycled mid-raid" % (r, len(dupes)))
        if orphan_deaths:
            fail("raid %s: %d AI death(s) with NO matching botSpawn - the missed-spawn-hook "
                 "signature. Roles: %s" % (r, len(orphan_deaths),
                                           sorted({d.get("role") for d in orphan_deaths})))
        else:
            note("raid %s: every AI death pairs with a spawn" % r)
        if sp and not de:
            # Beta could not rule this out from a read: Player.OnDead is virtual and an
            # override skipping the base would give a systematically empty death stream.
            fail("raid %s: %d spawns and ZERO AI deaths. Beta flagged this exact "
                 "possibility - Player.OnDead is virtual and an override skipping the base "
                 "would empty the stream. Check before trusting any death-based analysis."
                 % (r, len(sp)))

        # ---- census against ledger, per window ---------------------------------
        wins = [w for w in ordered if raid_of_window.get(w) == r]
        cum_s = cum_d = 0
        worst_neg, residuals = None, []
        si = sorted(sp, key=lambda e: (e.get("window") or -1))
        di = sorted(de, key=lambda e: (e.get("window") or -1))
        for w in wins:
            cum_s += sum(1 for e in si if e.get("window") == w)
            cum_d += sum(1 for e in di if e.get("window") == w)
            census = ((byw[w].get("bots") or {}).get("total"))
            if census is None:
                continue
            resid = (cum_s - cum_d) - census
            residuals.append(resid)
            if resid < 0 and (worst_neg is None or resid < worst_neg[1]):
                worst_neg = (w, resid)
        if not residuals:
            note("raid %s: no window carried bots.total - reconciliation unavailable" % r)
        elif worst_neg:
            fail("raid %s: ledger BELOW census by %d at window %d. The census sees bots the "
                 "ledger never recorded spawning - a missed spawn hook, not a despawn."
                 % (r, -worst_neg[1], worst_neg[0]))
        else:
            note("raid %s: ledger >= census in every window; residual %d..%d = the despawn "
                 "count, which nothing else measures" % (r, min(residuals), max(residuals)))

    # ---- killer states, since the whole feature turns on them -------------------
    if ai_deaths:
        st = defaultdict(int)
        for d in ai_deaths:
            st[str(d.get("killerState"))] += 1
        note("killerState: " + ", ".join("%s=%d" % kv for kv in sorted(st.items())))
        if st.get("None") or st.get("null"):
            fail("some AI deaths carry no killerState at all - the three states must be "
                 "exhaustive, or 'no aggressor' and 'not recorded' have merged")
        for d in ai_deaths:
            if d.get("killerState") == "none" and not d.get("damageType"):
                fail("a death with killerState=none carries no damageType - that is what "
                     "separates artillery from bleeding from a fall, and without it the "
                     "state is merely absent rather than informative")
                break
        named = [d for d in ai_deaths if d.get("killerState") == "named"]
        by_player = [d for d in named if d.get("killer") and d["killer"].get("isAI") is False]
        note("of %d named-killer deaths, %d were killed by a human (Sophia)"
             % (len(named), len(by_player)))

        # Beta carries `killer` (the game's judgement about attribution) AND `damageBy`
        # (the blow's own account) rather than choosing, because they can disagree and
        # the disagreement is the finding. Artillery is the known case: the game sets
        # LastAggressor to null AFTER a branch that may have named a player, so the blow
        # names someone the game deliberately un-named. Anyone attributing from
        # `damageBy` would overstate player involvement - which is the exact direction
        # this whole field exists to prevent, so it is counted rather than assumed rare.
        unnamed_by_game = [d for d in ai_deaths
                           if d.get("killer") is None and d.get("damageBy")]
        if unnamed_by_game:
            note("%d death(s) where the blow names a source but the game did NOT attribute "
                 "it (killer null, damageBy set) - artillery and its kin. Attribute from "
                 "`killer`, never `damageBy`, or these inflate player involvement."
                 % len(unnamed_by_game))
        disagree = [d for d in ai_deaths
                    if d.get("killer") and d.get("damageBy")
                    and d["killer"].get("id") != d["damageBy"].get("id")]
        if disagree:
            note("%d death(s) where killer and damageBy name DIFFERENT sources - visible "
                 "rather than settled by whichever field a reader happened to open"
                 % len(disagree))


def main():
    if not PATHS:
        print("usage: alpha-ledger-reconcile.py <log.ndjson> [...]")
        return 2
    for p in PATHS:
        check(p)
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
        print("\n%d FAILED check(s)." % len(fails))
        return 1
    print("\nledger and census reconcile (%d checks)" % len(notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
