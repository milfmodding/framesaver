"""Read a transit-marathon log: per-map scoreboard, with its own confound checked.

Usage:  python read-marathon.py <log.ndjson> [more.ndjson ...]

MORE THAN ONE LOG, BECAUSE A MARATHON NEED NOT BE ONE. The 2026-07-28 sweep was
split across two binaries and two files: legs 1-4 (Ground Zero, Streets, Interchange,
Customs) under `e337bea4`, and everything after under the build that added the
perception mark. Reading one file at a time would have made the sweep look half its
size and would have reported five maps as never launched while they sat in the
adjacent log. Logs are read in the order given, so pass them chronologically - leg
ordering is what the session-age control rests on.

WRITTEN BEFORE THE RUN, deliberately, same as read-slicing-raid.py. Every choice
here — which windows are eligible, what the session-age control is, what counts as
the run being unreadable — was made without knowing the answer. The same script
written afterwards is a set of choices the outcome influenced.

WHAT A MARATHON IS FOR. Goal 1 is a per-map claim and six maps have never been
launched: Woods, Shoreline, Reserve, Labs, Lighthouse, Ground Zero. Worse than the
count, Interchange and Factory rest on the 2026-07-26 baseline logs, the only ones
with `keepFightingBotsAwake: true` — a config we no longer ship. So the marathon
does two things at once: it covers the missing maps, and it measures every map on
ONE frozen config in ONE session, which no existing comparison does.

ITS OWN CONFOUND, AND WHY THE BACKTRACK IS THE CONTROL. Nine legs in one process
means map identity is confounded with session age: heap and working set grow, and
the route puts Lighthouse and Reserve — the two maps most likely to fail goal 1 —
last. The Shoreline route requires returning to Lighthouse, so **Lighthouse is
measured twice at two different session ages**, which turns the confound into a
measurement. If the two Lighthouse legs agree, every leg stands. If they disagree,
the size and direction are known and late legs are quoted with it.

THE OTHER THING ONLY THIS RUN CAN SHOW. Gluhar and Zryachiy carry
`Mind.CAN_STAND_BY = false` in BSG's own settings, so they never sleep and our
stand-by system deliberately respects that. Zryachiy spawns on Lighthouse
unconditionally. So on Lighthouse and Reserve `bots.awake` should floor ABOVE zero
however far the player walks, and that floor is the exemption's cost with nothing
else in it. No log in the corpus has it, on any map. It is also the baseline for
`Force stand-by for all roles`, a shipped knob that is false in all 18 logs and can
only matter on these two maps.

WHAT THE LOG CANNOT SEE, so it is asked for rather than inferred: which bosses were
present. `role` is recorded only for the single bot a census line samples, never as
a roster — so a Reserve leg with Gluhar and one without are indistinguishable here,
and they are not the same measurement. The runner's notes are load-bearing.
"""
import json
import os
import statistics as st
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

STEADY_S = 120.0        # skip each leg's raid-init window: 704 ms median worst frame
MIN_WINDOWS = 3         # below this a leg gets a number but not a verdict
TARGET_FPS = {'tarkovstreets': 60.0}
DEFAULT_TARGET = 100.0
HITCH_MS = 100.0
EXEMPT_MAPS = ('lighthouse', 'rezervbase')   # Zryachiy, Gluhar
# Several maps have more than one LocationId and the variants are not aliases of
# convenience -- they are different scenes. Ground Zero ships `sandbox` and
# `sandbox_high` (the level-20+ variant) and Factory ships day and night.
#
# The first version of this table had `sandbox` only, and the very first leg of the
# first marathon came back as `sandbox_high`. Ground Zero would have printed under
# its raw id, been missing from the coverage delta, AND been listed as "still never
# launched" in the same report that measured it. Caught by checking the live log at
# leg 1 rather than waiting for the whole sweep -- the cheapest possible moment, and
# the only reason it is a comment instead of a wrong conclusion.
KNOWN = {
    'tarkovstreets': 'Streets', 'bigmap': 'Customs',
    'factory4_day': 'Factory (day)', 'factory4_night': 'Factory (night)',
    'interchange': 'Interchange', 'woods': 'Woods', 'shoreline': 'Shoreline',
    'rezervbase': 'Reserve', 'laboratory': 'Labs', 'lighthouse': 'Lighthouse',
    'sandbox': 'Ground Zero', 'sandbox_high': 'Ground Zero (high)',
}
# Coverage is about the PLACE, so variants collapse here and only here.
FAMILY = {
    'sandbox_high': 'sandbox', 'factory4_night': 'factory4_day',
}
ALREADY_MEASURED = ('tarkovstreets', 'bigmap', 'factory4_day', 'interchange')


def load(paths):
    """Concatenate the logs in argument order, keeping the first header.

    Each log's `raid` counter restarts at 1, so legs from different files would
    collide on (raid, map) and merge. Offset each file's raid index past the last
    one seen - otherwise Lighthouse in file 1 and Lighthouse in file 2 look like one
    leg, which is exactly the pair the session-age control depends on telling apart.
    """
    hdr, rows, offset = {}, [], 0
    for path in paths:
        seen, first = set(), True
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get('type') == 'header':
                    if first:
                        hdr = hdr or d
                        first = False
                    continue
                if d.get('type') != 'sample' or d.get('state') != 'raid':
                    continue
                r = d.get('raid')
                if r is not None:
                    seen.add(r)
                    d['raid'] = r + offset
                d['_log'] = os.path.basename(path)[20:-7]
                rows.append(d)
        offset += max(seen) if seen else 0
    return hdr, rows


def legs(rows):
    """One entry per (raid index, map), in the order they were played.

    Keyed on the raid counter rather than the map, because the marathon revisits
    Lighthouse and the two visits must not merge - that pair IS the control.
    """
    out = []
    for d in rows:
        key = (d.get('raid'), (d.get('map') or '').lower())
        if not out or out[-1]['key'] != key:
            out.append({'key': key, 'raid': key[0], 'map': key[1], 'w': []})
        out[-1]['w'].append(d)
    return out


def eligible(leg):
    return [d for d in leg['w']
            if (d.get('raidElapsed') or 0) >= STEADY_S
            and (d.get('bots') or {}).get('total', 0) > 0
            and (d.get('framePct') or {}).get('p50')]


def sliced(w):
    """Was slicing applied on this window? `agents.slicing` when it is emitted,
    falling back to the config value.

    The config alone is not enough: `ModCompat.SuppressSlicing` can hold slicing
    off while `brainPeriod` reads non-zero, so a config-only test reports an arm
    that was never applied. Preferring the observed field over the requested one
    is the same rule as reading the backend URL out of Player.log.
    """
    obs = (w.get('agents') or {}).get('slicing')
    if obs is not None:
        return bool(obs)
    return bool((w.get('cfg') or {}).get('brainPeriod'))


def control_windows(leg):
    """Steady-state windows with slicing OFF.

    On a clean leg this is every eligible window and the call is free. On a leg
    carrying an A/B it is the control arm only, which is the ONLY thing on that
    leg comparable to a clean leg elsewhere in the session. Pooling both arms
    into a drift comparison would read a real slicing effect as session-age
    drift - in whichever direction slicing happens to work, which is the reading
    that would be believed.
    """
    return [w for w in eligible(leg) if not sliced(w)]


def armed(w):
    """Has a protocol STEP been entered on this window?

    NOT `protocol is None`. `ProtocolRunner.ResetForRaid()` calls `Load()`, so
    `Loaded` is true on every raid from the moment the ini is on disk, and
    Telemetry emits the `protocol` object whenever `Loaded`. Every window of
    every leg therefore carries `protocol: {step: 0, steps: 7, arm: null}` -
    including legs that never pressed the key. Testing for the object's presence
    marks the entire run as protocol legs and scores nothing.

    `arm` is null until the first press applies a step, so it is the field that
    actually distinguishes "an arm was applied here" from "the file was on
    disk". Delta found the chain; the substitution is theirs.

    Same family as the BoxedValue leak rotated ninety degrees: that one leaks
    forward through a value into later legs, this one leaks sideways through a
    load flag into legs that never used the file. Both are "installing a thing
    changes runs that do not use the thing."
    """
    return (w.get('protocol') or {}).get('arm') is not None


def clean_windows(leg):
    """Steady-state windows with no arm applied and slicing off.

    PER WINDOW, NOT PER LEG, and the difference is the whole Lighthouse verdict.
    Route 2 presses three times in the last ten minutes of a forty-minute leg,
    so a leg-level test throws away thirty clean minutes of the map we reordered
    the route to measure. The contaminated part of a leg is the part after the
    first press; the rest is an ordinary clean leg and scores like one.

    Granularity has now been wrong in both directions in one evening - per run
    when it wanted per leg, then per leg when it wanted per window. The question
    to ask of any exclusion is what the smallest unit carrying the defect is,
    and it is almost never the unit that is convenient to loop over.
    """
    return [w for w in eligible(leg) if not armed(w) and not sliced(w)]


def leg_is_clean(leg):
    """True when no window of the leg had an arm applied or slicing on."""
    return all(not armed(w) and not sliced(w) for w in leg['w'])


def fps(ws):
    return sorted(1000.0 / d['framePct']['p50'] for d in ws)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    paths = argv[1:]
    hdr, rows = load(paths)
    if not rows:
        print('no in-raid sample lines - nothing to read')
        return 1

    print('%s\ntag %r, window %ss, spike %sms\n'
          % (' + '.join(os.path.basename(p) for p in paths), hdr.get('tag'),
             hdr.get('windowSeconds'), hdr.get('spikeEventMs')))

    ls = legs(rows)
    fails = []

    # ---- 1. was this actually a clean sweep? ------------------------------
    periods = set()
    protos = set()
    for d in rows:
        periods.add((d.get('cfg') or {}).get('brainPeriod'))
        p = d.get('protocol')
        protos.add(None if p is None else json.dumps(p, sort_keys=True))
    print('1. legs                %d   maps %s'
          % (len(ls), ', '.join(KNOWN.get(l['map'], l['map']) for l in ls)))
    print('2. brainPeriod         %s' % (sorted(str(p) for p in periods),))
    # UNEXPLAINED SLICING STILL FAILS THE RUN; EXPLAINED SLICING EXCLUDES A LEG.
    # The original gate failed on any non-zero brainPeriod, and its own message
    # says what it was written to catch: slicing "probably inherited from a
    # previous protocol run" - a leftover nobody asked for, which silently makes
    # every map figure a slicing figure. That hazard is unchanged and still fails
    # here. What is new is a leg that carries an ini ON PURPOSE, where the
    # non-zero period is announced by the protocol beside it. Those are different
    # facts and the single test conflated them, so a deliberate A/B leg made
    # three clean legs unquotable.
    #
    # Split by whether the window can explain itself: slicing with a protocol is
    # an arm, slicing without one is contamination.
    # `not armed(w)`, NOT `protocol is None` - and this is the site where the
    # difference disables a check rather than merely mislabelling one. Once the
    # ini is on disk `protocol` is never None, so the `is None` form makes this
    # branch unreachable and the inherited-slicing detector goes silent at
    # exactly the moment a protocol run makes inheritance possible. The hazard
    # it exists for - a 0.1 left over from a previous run - is unreachable
    # precisely when it is most likely.
    unexplained = [w for w in rows if sliced(w) and not armed(w)]
    if unexplained:
        fails.append('%d window(s) have slicing on with no protocol to explain it '
                     '- probably inherited from a previous run, and every map '
                     'figure on those legs is a slicing figure' % len(unexplained))
    # sorted(key=str): a mixed run holds both None and JSON strings, and sorting
    # those raw raises TypeError. Unreachable while any protocol failed the whole
    # run, which is why it survived - the crash was one line below a gate that
    # always fired first, so widening the gate uncovered a second defect rather
    # than causing one. Found by feeding the reader a synthesised protocol leg
    # before the raid, which is the only place that combination existed.
    print('3. protocol            %s'
          % ('null throughout' if protos == {None}
             else sorted((str(p) for p in protos), key=str)))
    dirty = [(i + 1, sum(1 for w in l['w'] if armed(w) or sliced(w)), len(l['w']))
             for i, l in enumerate(ls) if not leg_is_clean(l)]
    if dirty:
        print('                       %s'
              % '; '.join('leg %d: %d of %d windows armed or sliced' % d
                          for d in dirty))
        print('                       Those WINDOWS are dropped from goal-1 '
              'scoring, not the whole leg -')
        print('                       the clean part of a leg scores normally. '
              'Slicing-off windows,')
        print('                       armed or not, still serve the session-age '
              'comparison.')

    # ---- 2. the session-age control --------------------------------------
    seen = {}
    for i, l in enumerate(ls):
        seen.setdefault(l['map'], []).append(i)
    repeats = {m: idx for m, idx in seen.items() if len(idx) > 1}
    # A missing repeat is NOT a blanket gate failure, and this was decided before
    # any marathon log existed -- loosening a gate after seeing the result is the
    # thing pre-registration exists to prevent, so it had to be settled blind.
    #
    # The reasoning: without a repeat the session-age term is unmeasured, but it is
    # unmeasured *unevenly*. Leg 1 carries almost none of it and the last leg
    # carries all of it, so refusing every per-map verdict would discard the early
    # legs to protect against a confound that barely touches them. The honest form
    # is to name which legs are exposed rather than to fail the whole run.
    # TWO INDEPENDENT FACTS, TWO VARIABLES, and they were one variable for three
    # revisions of this file. `exposed_from is None` was made to mean both "a repeated
    # map measured the drift" and "too few legs for late-leg exposure to matter", so
    # the summary line reported drift MEASURED on a one-leg log that had measured
    # nothing. Third appearance of the vacuous-pass shape in this one file, and each
    # time it came back through a patch that fixed the symptom.
    exposed_from = None      # first leg carrying an unquantified session-age term
    drift_measured = False   # a map was played twice, so the term is bounded
    print('\n4. session-age control ', end='')
    if not repeats:
        print('NONE - no map was played twice')
    else:
        # A REPEAT IS NOT A COMPARISON. This used to set drift_measured here, on
        # the strength of the map appearing twice, while the ratio below needs
        # `len(got) > 1`. A run whose only repeat has one unusable leg therefore
        # printed "session-age drift MEASURED via the repeated map" having
        # measured nothing. Fourth appearance of the vacuous pass in this file,
        # and the first three are named in the comments above - a shape that
        # comes back this often wants the rule stated, not another patch: THE
        # FLAG THAT SAYS A THING WAS MEASURED IS SET WHERE THE MEASUREMENT
        # SUCCEEDS, NEVER WHERE ITS PRECONDITION IS SPOTTED.
        for m, idx in repeats.items():
            vals = []
            for i in idx:
                # CONTROL-ARM WINDOWS ONLY, so a repeat leg that carries an A/B is
                # still comparable to the clean leg it is being read against. On a
                # clean leg this is every eligible window and nothing changes.
                e = control_windows(ls[i])
                vals.append((i + 1, len(e), st.median(fps(e)) if e else None))
            got = [v for v in vals if v[2] is not None]
            print('%s played %d times: %s'
                  % (KNOWN.get(m, m), len(idx),
                     '  '.join('leg %d n=%d p50 %.1f fps' % v for v in got)))
            if len(got) < 2:
                print('   only %d of %d visits produced a steady-state window, '
                      'so this repeat measures nothing' % (len(got), len(idx)))
            if len(got) > 1:
                drift_measured = True
                lo, hi = min(v[2] for v in got), max(v[2] for v in got)
                drift = hi / lo
                print('   spread %.2fx across the session' % drift)
                if drift > 1.15:
                    fails.append('%s drifted %.2fx between visits - map and '
                                 'session age are not separable in this run'
                                 % (KNOWN.get(m, m), drift))
            print('                       ', end='')
        print()

    # EXPOSURE IS MARKED WHENEVER DRIFT WENT UNMEASURED, which is not the same as
    # "no map repeated" - and treating them as the same is how the repeat-with-one-
    # usable-leg case escaped both arms: it took the `repeats` branch, so it never
    # reached the exposure marking, and it failed the ratio test, so it produced no
    # drift figure either. The run then read as neither measured nor caveated.
    # Keyed on the OUTCOME rather than on the shape of the route, for the same
    # reason drift_measured now is.
    if not drift_measured:
        cut = max(1, len(ls) // 3)
        exposed_from = cut + 1 if cut + 1 <= len(ls) else None
        if exposed_from is None:
            print('                       only %d leg(s), so there is no late-leg '
                  'exposure to mark - but' % len(ls))
            print('                       session-age drift is still UNTESTED '
                  'rather than absent.')
        else:
            print('                       session-age drift is UNTESTED, not '
                  'absent. Legs 1-%d carry little of' % cut)
            print('                       it; legs %d-%d carry an unquantified '
                  'term and are marked below.' % (exposed_from, len(ls)))
            print('                       This is a caveat, not a gate failure - '
                  'the exposure is uneven.')

    # ---- 3. the scoreboard ----------------------------------------------
    print('\n5. per leg, steady state only (>= %.0f s into the leg)\n' % STEADY_S)
    print('%-4s %-19s %-5s %-9s %-8s %-11s %-9s %-14s %s'
          % ('leg', 'map', 'n', 'p50 fps', 'target', 'verdict', 'worst ms',
             'awake min/med', 'dropped'))
    # Which maps the scoreboard actually CALLED, so section 7 cannot report a map
    # as covered that section 5 refused a verdict. Lighthouse did exactly that on
    # 2026-07-28: 121 s of raid, one steady-state window, "n<3, no call" in the
    # scoreboard and "newly measured" in coverage. Two sections disagreeing about
    # what `measured` means is the same vacuous pass wearing different words.
    verdicted = set()
    for i, l in enumerate(ls):
        e = eligible(l)
        name = KNOWN.get(l['map'], l['map'])
        if not e:
            print('%-4d %-19s %-5d %s' % (i + 1, name, 0, 'no steady-state windows'))
            continue
        # SCORE THE CLEAN WINDOWS ONLY. The armed and sliced ones are dropped
        # rather than pooled: a p50 mixing both arms of an A/B is this map's
        # frame rate under no config, and "printed with a caveat" is how the
        # Lighthouse 65.8 reached three documents. If nothing clean survives,
        # the leg gets no number at all rather than a qualified one.
        e = clean_windows(l)
        dropped = len(eligible(l)) - len(e)
        if not e:
            print('%-4d %-19s %-5d %-9s %-8s %s'
                  % (i + 1, name, 0, '--', '--',
                     'no clean windows (%d armed or sliced)' % dropped))
            continue
        f = fps(e)
        med = st.median(f)
        target = TARGET_FPS.get(l['map'], DEFAULT_TARGET)
        mx = [d['frame']['max'] for d in e if (d.get('frame') or {}).get('max')]
        awake = [(d.get('bots') or {}).get('awake', 0) for d in e]
        verdict = ('MEETS' if med >= target else 'under') + ' %.0f' % target
        if len(e) < MIN_WINDOWS:
            verdict = 'n<%d, no call' % MIN_WINDOWS
        else:
            verdicted.add(FAMILY.get(l['map'], l['map']))
        mark = ''
        if exposed_from is not None and (i + 1) >= exposed_from:
            mark = '  *session-age untested'
        # The dropped count is printed on every row, not only on rows where it is
        # non-zero. A column that appears when there is something to hide teaches
        # the reader to skim it; a zero in every clean row is what makes the one
        # non-zero legible.
        print('%-4d %-19s %-5d %-9.1f %-8.0f %-11s %-9.1f %-14s %-8s%s'
              % (i + 1, name, len(e), med, target, verdict,
                 st.median(mx) if mx else float('nan'),
                 '%d / %.0f' % (min(awake), st.median(awake)),
                 '%d armed' % dropped if dropped else '-', mark))

    # ---- 4. the exemption floor, read RELATIVELY --------------------------
    #
    # The first version of this section printed min(awake) and called any non-zero
    # value on a non-exempt map "worth a look". Dry-running it against the control
    # log flagged Streets at 6 and Customs at 2 - and neither is an anomaly:
    # `Keep nearest snipers awake` is 2 by config, so LongRangeExemption alone
    # guarantees a floor of ~2 on any map with sniper scavs, and the rest is
    # ordinary bots inside wakeDistance because a player is never far from
    # everything. An absolute floor is not the exemption's cost.
    #
    # So this reads the floor relatively: the excess over `snipersAwake`, compared
    # against the same quantity on the non-exempt maps of the SAME session. That
    # controls the config and the session but not the player's distance, which
    # nothing in the log can - stated rather than papered over.
    print('\n6. the CAN_STAND_BY floor - Gluhar and Zryachiy never sleep\n')
    print('Read relatively. An absolute floor is not the exemption: '
          '`Keep nearest snipers awake`\nis 2, so ~2 is expected everywhere, and '
          'a player is never far from every bot.\n')
    print('%-19s %-11s %-13s %-21s %-9s %s'
          % ('map', 'min awake', 'snipersAwake', 'excess over snipers',
             'last win', 'awake vs exempt'))
    excess = {}
    direct_seen = False
    for i, l in enumerate(ls):
        e = eligible(l)
        if not e:
            continue
        lo = min((d.get('bots') or {}).get('awake', 0) for d in e)
        sn = st.median([d.get('snipersAwake') or 0 for d in e])
        ex = lo - sn
        excess.setdefault(l['map'] in EXEMPT_MAPS, []).append((l['map'], ex))
        # THE DIRECT READ, AND IT IS THE LAST FULL WINDOW AND NEVER A POOLED MEAN.
        # `exempt` counts every role-exempt bot and every PMC is one, so early in a
        # raid it is large on every map and discriminates nothing. What separates
        # Lighthouse from Customs is the FLOOR - whether the bots still awake when
        # the map has settled are awake because their role forbids stand-by. Pooling
        # mixes the PMCs-alive phase into that floor, the same aggregation error as
        # the per-bot slope. Registered as `reserve-exempt-floor`.
        last = (e[-1].get('bots') or {})
        aw, exm, unk = last.get('awake'), last.get('exempt'), last.get('roleUnknown')
        if exm is None:
            direct = 'not emitted'
        else:
            direct_seen = True
            direct = '%d awake / %d exempt' % (aw, exm)
            if unk:
                direct += '  (%d roleUnknown)' % unk
        print('%-19s %-11d %-13.0f %+-21.0f %-9s %s%s'
              % (KNOWN.get(l['map'], l['map']), lo, sn, ex,
                 'w%s' % e[-1].get('window'), direct,
                 '   <- exempt boss expected' if l['map'] in EXEMPT_MAPS else ''))
    # KEEP THE PROXY UNTIL THE DIRECT READ IS PROVEN, not until it ships - the rule
    # endToLatch earned. `exempt` has never emitted a value in any log, so on its
    # first run it is the unproven instrument and the sniper subtraction is its
    # control. Retire the proxy on the first log where both columns agree, and if
    # they disagree that is a finding rather than a reason to trust the newer one.
    if not direct_seen:
        print('\n`bots.exempt` is absent from every leg, so only the proxy is '
              'readable here.\nThat is expected on any log written before e6cca83.')
    if True in excess and False in excess:
        e_ex = st.median([x[1] for x in excess[True]])
        n_ex = st.median([x[1] for x in excess[False]])
        print('\nmedian excess: exempt maps %+.1f, other maps %+.1f, '
              'difference %+.1f' % (e_ex, n_ex, e_ex - n_ex))
        print('That difference is the exemption cost, to the extent distance was '
              'comparable -\nwhich the log cannot verify. Treat it as an estimate '
              'wanting a held-position run.')
    else:
        print('\nOnly one class of map present, so there is no within-session '
              'comparison and\nthe floor above says nothing about the exemption.')

    # ---- 5. coverage delta ----------------------------------------------
    #
    # COVERAGE COUNTS WHAT THE SCOREBOARD CALLED, not what was loaded. `played`
    # used to be every map with a leg, which reported Lighthouse as newly measured
    # off a 121 s visit the scoreboard had just refused with "n<3, no call". A map
    # that was launched and not measured is worse than one never launched, because
    # it stops looking like a gap.
    played = set(FAMILY.get(l['map'], l['map']) for l in ls)
    # A protocol leg is not a short leg and must not be reported as one - the fix
    # is not "more raid time", it is a clean leg. Named separately so the reader
    # is told which thing to do about it.
    proto_only = sorted(set(FAMILY.get(l['map'], l['map']) for l in ls
                            if not leg_is_clean(l)) - verdicted)
    launched_only = sorted(played - verdicted - set(proto_only))
    new = sorted(verdicted - set(ALREADY_MEASURED))
    still = sorted(set(KNOWN[k] for k in KNOWN
                       if FAMILY.get(k, k) not in played | set(ALREADY_MEASURED)))
    win_s = float(hdr.get('windowSeconds') or 60)
    print('\n7. coverage            newly measured: %s'
          % (', '.join(KNOWN.get(m, m) for m in new) or 'none'))
    if launched_only:
        print('                       LAUNCHED BUT NOT MEASURED (n<%d): %s'
              % (MIN_WINDOWS,
                 ', '.join(KNOWN.get(m, m) for m in launched_only)))
        print('                       A leg needs %.0f s of raid to earn a verdict: '
              '%.0f s discarded as' % (STEADY_S + MIN_WINDOWS * win_s, STEADY_S))
        print('                       warm-up, then %d windows of %.0f s. These '
              'are still gaps.' % (MIN_WINDOWS, win_s))
    if proto_only:
        print('                       MEASURED ONLY UNDER A PROTOCOL: %s'
              % ', '.join(KNOWN.get(m, m) for m in proto_only))
        print('                       goal 1 is a claim about the shipped config, '
              'so an A/B leg does not')
        print('                       cover it however long it ran. Still a gap, '
              'and more raid time will')
        print('                       not close this one - a clean leg will.')
    print('                       still never launched: %s'
          % (', '.join(still) or 'none - all ten maps measured'))

    print('\n8. NOT IN THIS LOG     which bosses were present. `role` is recorded')
    print('                       only for the bot a census line samples, never as')
    print('                       a roster. A Reserve leg with Gluhar and one')
    print('                       without are indistinguishable here. Attach the')
    print('                       runner\'s notes before quoting any per-map number.')

    if fails:
        print('\nGATE FAILED - per-map verdicts above are NOT quotable:')
        for f in fails:
            print('  ! %s' % f)
        return 1
    # The pass line has to say what actually held. Its first version read
    # "session-age drift measured rather than assumed" unconditionally, which is
    # false on a run with no repeated map -- a vacuous pass in the summary of a
    # gate written to prevent vacuous passes, found by reading its own output.
    # Fifth instance of that rule today and the second inside a tool that states
    # it.
    if drift_measured:
        print('\nGate passed: clean sweep, one config, and session-age drift '
              'MEASURED via the repeated map.')
    elif exposed_from is None:
        print('\nGate passed on config and cleanliness only. Session-age drift is '
              'UNTESTED\nrather than absent - there are simply too few legs yet '
              'for it to bite.')
    else:
        print('\nGate passed on config and cleanliness only. Session-age drift is '
              'UNTESTED:\nlegs %d-%d carry an unquantified term. Not a failure, '
              'not a clean bill either.' % (exposed_from, len(ls)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
