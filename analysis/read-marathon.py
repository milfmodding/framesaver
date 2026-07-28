"""Read a transit-marathon log: per-map scoreboard, with its own confound checked.

Usage:  python read-marathon.py <log.ndjson>

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


def load(path):
    hdr, rows = {}, []
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
                hdr = d
            elif d.get('type') == 'sample' and d.get('state') == 'raid':
                rows.append(d)
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


def fps(ws):
    return sorted(1000.0 / d['framePct']['p50'] for d in ws)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = argv[1]
    hdr, rows = load(path)
    if not rows:
        print('no in-raid sample lines - nothing to read')
        return 1

    print('%s\ntag %r, window %ss, spike %sms\n'
          % (os.path.basename(path), hdr.get('tag'),
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
    if periods - {0, 0.0}:
        fails.append('brainPeriod was not 0 on every window - slicing was applied, '
                     'probably inherited from a previous protocol run')
    print('3. protocol            %s'
          % ('null throughout' if protos == {None} else sorted(protos)))
    if protos != {None}:
        fails.append('a protocol was installed - this is not a clean sweep')

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
        cut = max(1, len(ls) // 3)
        exposed_from = cut + 1 if cut + 1 <= len(ls) else None
        print('NONE - no map was played twice')
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
    else:
        drift_measured = True
        for m, idx in repeats.items():
            vals = []
            for i in idx:
                e = eligible(ls[i])
                vals.append((i + 1, len(e), st.median(fps(e)) if e else None))
            got = [v for v in vals if v[2] is not None]
            print('%s played %d times: %s'
                  % (KNOWN.get(m, m), len(idx),
                     '  '.join('leg %d n=%d p50 %.1f fps' % v for v in got)))
            if len(got) > 1:
                lo, hi = min(v[2] for v in got), max(v[2] for v in got)
                drift = hi / lo
                print('   spread %.2fx across the session' % drift)
                if drift > 1.15:
                    fails.append('%s drifted %.2fx between visits - map and '
                                 'session age are not separable in this run'
                                 % (KNOWN.get(m, m), drift))
            print('                       ', end='')
        print()

    # ---- 3. the scoreboard ----------------------------------------------
    print('\n5. per leg, steady state only (>= %.0f s into the leg)\n' % STEADY_S)
    print('%-4s %-19s %-5s %-9s %-8s %-11s %-9s %s'
          % ('leg', 'map', 'n', 'p50 fps', 'target', 'verdict', 'worst ms',
             'awake min/med'))
    for i, l in enumerate(ls):
        e = eligible(l)
        name = KNOWN.get(l['map'], l['map'])
        if not e:
            print('%-4d %-19s %-5d %s' % (i + 1, name, 0, 'no steady-state windows'))
            continue
        f = fps(e)
        med = st.median(f)
        target = TARGET_FPS.get(l['map'], DEFAULT_TARGET)
        mx = [d['frame']['max'] for d in e if (d.get('frame') or {}).get('max')]
        awake = [(d.get('bots') or {}).get('awake', 0) for d in e]
        verdict = ('MEETS' if med >= target else 'under') + ' %.0f' % target
        if len(e) < MIN_WINDOWS:
            verdict = 'n<%d, no call' % MIN_WINDOWS
        mark = ''
        if exposed_from is not None and (i + 1) >= exposed_from:
            mark = '  *session-age untested'
        print('%-4d %-19s %-5d %-9.1f %-8.0f %-11s %-9.1f %d / %.0f%s'
              % (i + 1, name, len(e), med, target, verdict,
                 st.median(mx) if mx else float('nan'),
                 min(awake), st.median(awake), mark))

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
    print('%-19s %-11s %-13s %s'
          % ('map', 'min awake', 'snipersAwake', 'excess over snipers'))
    excess = {}
    for i, l in enumerate(ls):
        e = eligible(l)
        if not e:
            continue
        lo = min((d.get('bots') or {}).get('awake', 0) for d in e)
        sn = st.median([d.get('snipersAwake') or 0 for d in e])
        ex = lo - sn
        excess.setdefault(l['map'] in EXEMPT_MAPS, []).append((l['map'], ex))
        print('%-19s %-11d %-13.0f %+.0f%s'
              % (KNOWN.get(l['map'], l['map']), lo, sn, ex,
                 '   <- exempt boss expected' if l['map'] in EXEMPT_MAPS else ''))
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
    played = set(FAMILY.get(l['map'], l['map']) for l in ls)
    new = sorted(played - set(ALREADY_MEASURED))
    still = sorted(set(KNOWN[k] for k in KNOWN
                       if FAMILY.get(k, k) not in played | set(ALREADY_MEASURED)))
    print('\n7. coverage            newly measured: %s'
          % (', '.join(KNOWN.get(m, m) for m in new) or 'none'))
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
