"""The release scoreboard, in the statistic the success criteria are written in.

    p50 >= 100 fps on every map except Streets
    p50 >= 60 fps on Streets
    no in-raid hitches

`framePct.p50` is the first of those directly and has been on every in-raid
window since the first log. Nothing here is new measurement; it is the corpus
read against the gate, plus the coverage that gate needs and does not have.

WHY A SCRIPT AND NOT A TABLE IN A DOCUMENT. The table in TESTING.md was correct
when written and is now 3.2 fps optimistic on Streets, because 51 windows
arrived after it and 28 of them are held-position protocol arms at 37 fps. A
scoreboard that is recomputed cannot go stale; one that is pasted goes stale
silently and in whichever direction the last raid happened to point.

THE POPULATION RULE DEFAULTS TO INCLUDING, WHICH IS THE OPPOSITE OF WHAT THIS
FILE FIRST DID. The first version keyed exclusion on `header.tag` and treated an
undeclared tag as not-counted, reasoning by analogy with the precondition gate in
harness/registrations.json: silence blocks rather than passes, because a false
block costs a line of typing and a false pass costs a raid.

**The analogy imports the wrong direction.** On a gating metric the two errors
are not symmetric the way they are on a gate: a wrongly *included* window makes
the number worse and the release more conservative, while a wrongly *excluded*
one makes the number prettier and the release riskier. Held windows are the hard
ones. Dropping them by default systematically flatters the scoreboard, so the
safe default here is to count everything and name the exceptions.

And the reason first given for excluding them was wrong on its own terms. *"A
held window measures a sightline, not play"* is false -- **a player holding an
angle in a firefight is playing, and it is the worst case the goal exists to
cover.** Players hold angles constantly and that is when they die, so a gate that
only holds while roaming is not a gate the community will experience.

What actually makes the 2026-07-28 protocol windows excludable is narrower:
**their sightline was chosen to maximise draw calls, so they are selected on the
dependent variable.** That is a property of one run, not a rule -- and the fields
that would turn it into a rule do not exist. `pos.dist` separates those windows
perfectly (0.0 m held against >= 76.1 m for every ordinary Streets window) but
appears on only 42 of 210 windows, 32 of them inside the very raid it would
exclude, so retroactively it classifies 168 windows as null and the handling of
nulls decides the answer outright. `header.tag` spans the corpus but names the
build under test rather than the runner's behaviour.

So the exclusion is a hand-written list of log names with a reason each, and it
is labelled as one. **A hand-picked exclusion that admits what it is beats a
mechanism that quietly rests on 168 nulls.** Excluded windows are still reported,
with their own numbers, so nothing hides.
"""
import glob
import json
import os
import statistics as st
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

LOGS = r'F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs'

# Streets was revised to 60+ as the target rather than the floor. Everything
# else is 100+. See TESTING.md, success criteria.
TARGET_FPS = {'tarkovstreets': 60.0}
DEFAULT_TARGET_FPS = 100.0

# Manual, per-log, with a reason each. Not a rule -- see the module docstring for
# why the fields that would make it one are not in the corpus. Everything not
# named here counts.
EXCLUDED = {
    '20260728-125209-latch':
        'sightline chosen to maximise draw calls, so these windows are selected '
        'on the dependent variable',
}

# A hitch is a stall a player would notice, not a threshold the log happened to
# be configured with. `Spike event ms` has been 100, 50 and 30 across the corpus
# and spike counts do not join across those, so both metrics below are
# threshold-free and retroactive over every raid we own.
#
# THEY MEASURE DIFFERENT THINGS AND GOAL 2 NEEDS THE SECOND ONE.
# `framePct.p999` at ~3,500 frames a window is the ~3.5th-worst frame, so a
# window holding ONE catastrophic frame reports a p999 set by the 4th-worst,
# which can be entirely ordinary: one Streets window carries a 338 ms hitch
# behind a p999 of 28.0 ms, better than the Streets median. 47 of 118 Streets
# windows carrying spike lines have a spike >= 150 ms whose p999 is under half of
# it. Sophia's framing of goal 2 is dying to a stutter in an early fight, and
# that is one frame -- an event criterion, not a density one.
#
# `frame.max` IS the worst frame, sits beside `avg`/`min` in every log of every
# era, and needs no threshold either. So: p999 for the sustained tail, max for
# the worst event. Proposing p999 alone would have retired the spike counter in
# favour of a metric blind to the family we spent two days localising.
HITCH_MS = 100.0


def read_log(path):
    """Header tag and config, plus every in-raid window carrying framePct.

    `bots.total > 0` drops teardown windows, per the corpus rule -- a window
    after the last bot despawns is not a measurement of the game under load.

    Knob values come from `header.config` and NOT from `cfg` on the sample line.
    `cfg` gained keys across three eras, so `cfg.keepFighting` is absent in era
    A -- and the first version of this script read it there, found `None`, and
    printed no provenance note at all for the two maps whose entire evidence
    comes from a `keepFightingBotsAwake: true` config. An absent field read as
    "nothing to report" is the exact failure this file exists to prevent, and it
    happened inside the tool written to prevent it. `header.config` carries all
    ten knobs on every log in the corpus.
    """
    tag, cfg0, rows = None, {}, []
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
                tag = d.get('tag')
                cfg0 = d.get('config') or {}
                continue
            if d.get('type') != 'sample' or d.get('state') != 'raid':
                continue
            if (d.get('bots') or {}).get('total', 0) <= 0:
                continue
            pct = d.get('framePct')
            if not pct or not pct.get('p50'):
                continue
            rows.append({
                'map': (d.get('map') or '').lower(),
                'raid': d.get('raid'),
                'p50': pct['p50'],
                'p99': pct['p99'],
                'p999': pct['p999'],
                'max': (d.get('frame') or {}).get('max'),
                'elapsed': d.get('raidElapsed') or 0.0,
                'frames': d.get('frames') or 0,
                'cfg0': cfg0,
            })
    return tag, cfg0, rows


def collect():
    counted, excluded, knobs = [], {}, {}
    for path in sorted(glob.glob(os.path.join(LOGS, 'framesaver-*.ndjson'))):
        tag, cfg0, rows = read_log(path)
        if not rows:
            continue
        for k, v in cfg0.items():
            knobs.setdefault(k, {}).setdefault(repr(v), 0)
            knobs[k][repr(v)] += 1
        log = os.path.basename(path)[11:-7]
        for r in rows:
            r['tag'] = tag
            r['log'] = log
        if log in EXCLUDED:
            excluded[log] = rows
        else:
            counted.extend(rows)
    return counted, excluded, knobs


def knob_variation(knobs):
    """Which of our own settings has any raid ever varied?

    This is the finding that reordered the plan on 2026-07-28, so it is computed
    rather than asserted. A knob with one distinct value across the whole corpus
    has never been tested -- the mod ships it, and no measurement covers it.
    """
    print('\n=== WHAT WE HAVE ACTUALLY VARIED ===\n')
    print('%-24s %6s   %s' % ('knob', 'values', 'across the corpus'))
    for k, v in sorted(knobs.items(), key=lambda kv: (len(kv[1]), kv[0])):
        seen = ', '.join('%s x%d' % (val, n)
                         for val, n in sorted(v.items(), key=lambda x: -x[1]))
        flag = '  <-- NEVER VARIED' if len(v) == 1 else ''
        print('%-24s %6d   %s%s' % (k, len(v), seen, flag))
    never = [k for k, v in knobs.items() if len(v) == 1]
    print('\n%d of %d knobs have never moved. Every arm run so far varied'
          % (len(never), len(knobs)))
    print('telemetry design or GC settings, so the mod\'s own patches have')
    print('never been A/B\'d against framePct.p50 on any map.')


def fps(rows):
    return sorted(1000.0 / r['p50'] for r in rows)


def by_map(rows):
    out = {}
    for r in rows:
        out.setdefault(r['map'], []).append(r)
    return out


def goal_one(play):
    print('\n=== GOAL 1 -- p50 frame rate, play windows only ===\n')
    print('%-15s %5s %5s %8s %8s %8s   %s'
          % ('map', 'raids', 'n', 'p50 fps', 'p25', 'p75', 'verdict'))
    for m, v in sorted(by_map(play).items(), key=lambda kv: -len(kv[1])):
        f = fps(v)
        target = TARGET_FPS.get(m, DEFAULT_TARGET_FPS)
        med = st.median(f)
        met = sum(1 for x in f if x >= target)
        raids = len(set((r['log'], r['raid']) for r in v))
        verdict = 'MEETS %.0f' % target if med >= target else 'under %.0f' % target
        print('%-15s %5d %5d %8.1f %8.1f %8.1f   %-9s (%d of %d windows)'
              % (m, raids, len(v), med, f[int(0.25 * (len(f) - 1))],
                 f[int(0.75 * (len(f) - 1))], verdict, met, len(v)))


def goal_two(play):
    print('\n=== GOAL 2 -- in-raid hitches ===\n')
    print('frame.max is the worst frame in the window and is the criterion: '
          'goal 2 is an\nevent, not a density. p999 sits beside it for the '
          'sustained tail -- it CANNOT see\na lone catastrophic frame, which is '
          'above p999 at these window sizes.\n')
    print('%-15s %5s %9s %9s   %-24s %s'
          % ('map', 'n', 'p999 med', 'max med', 'worst frame seen',
             'windows with a >%.0f ms frame' % HITCH_MS))
    for m, v in sorted(by_map(play).items(), key=lambda kv: -len(kv[1])):
        mx = [r['max'] for r in v if r['max'] is not None]
        if not mx:
            continue
        bad = sum(1 for x in mx if x > HITCH_MS)
        print('%-15s %5d %9.1f %9.1f   %-24.1f %3d of %-4d (%3.0f%%)'
              % (m, len(v), st.median([r['p999'] for r in v]), st.median(mx),
                 max(mx), bad, len(mx), 100.0 * bad / len(mx)))
    # The first in-raid window is the raid-init and spawn family, which is a
    # known and separately-attacked problem, and it would otherwise inflate every
    # figure above. Splitting it out is what makes the rest a steady-state
    # reading -- and the answer survives the split, which is the point of taking
    # it: the share does not decay with time, it rises.
    print('\nBy how far into the raid the window sits, all maps:')
    print('%-18s %5s %14s   %s'
          % ('', 'n', 'median worst', 'windows with a >%.0f ms frame'
             % HITCH_MS))
    bands = [('under 120 s', 0.0, 120.0), ('120-300 s', 120.0, 300.0),
             ('beyond 300 s', 300.0, float('inf'))]
    for lbl, lo, hi in bands:
        mx = [r['max'] for r in play
              if r['max'] is not None and lo <= r['elapsed'] < hi]
        if not mx:
            continue
        print('  %-16s %5d %14.1f   %3d of %-4d (%3.0f%%)'
              % (lbl, len(mx), st.median(mx),
                 sum(1 for x in mx if x > HITCH_MS), len(mx),
                 100.0 * sum(1 for x in mx if x > HITCH_MS) / len(mx)))
    print('\nSteady state only (>= 120 s), which is the number goal 2 is about:')
    for m, v in sorted(by_map([r for r in play if r['elapsed'] >= 120.0]).items(),
                       key=lambda kv: -len(kv[1])):
        mx = [r['max'] for r in v if r['max'] is not None]
        if not mx:
            continue
        print('  %-16s %5d %14.1f   %3d of %-4d (%3.0f%%)'
              % (m, len(mx), st.median(mx),
                 sum(1 for x in mx if x > HITCH_MS), len(mx),
                 100.0 * sum(1 for x in mx if x > HITCH_MS) / len(mx)))

    # The gap between the two metrics, stated as a number rather than argued,
    # because the whole point is that one of them is blind.
    blind = [r for r in play
             if r['max'] is not None and r['max'] >= 150.0
             and r['p999'] < r['max'] / 2.0]
    if blind:
        worst = max(blind, key=lambda r: r['max'] - r['p999'])
        print('\n%d windows carry a frame >= 150 ms whose p999 is under half of '
              'it.' % len(blind))
        print('Worst gap: %s carries a %.1f ms frame behind a p999 of %.1f ms.'
              % (worst['log'], worst['max'], worst['p999']))


def coverage(play):
    print('\n=== COVERAGE -- what the gate needs and does not have ===\n')
    print('Goal 1 is a per-map claim. These are the maps it has evidence on.\n')
    print('%-15s %5s %5s %9s   %s'
          % ('map', 'raids', 'n', 'frames', 'config provenance'))
    for m, v in sorted(by_map(play).items(), key=lambda kv: -len(kv[1])):
        kf = set(r['cfg0'].get('keepFightingBotsAwake') for r in v)
        bp = set(r['cfg0'].get('brainUpdatePeriod') for r in v)
        notes = []
        if kf == {True}:
            notes.append('ONLY keepFightingBotsAwake=true -- a config we no '
                         'longer ship')
        elif True in kf:
            notes.append('mixed keepFightingBotsAwake')
        if None in kf:
            notes.append('keepFightingBotsAwake UNREADABLE on some windows')
        if bp == {0}:
            notes.append('brainUpdatePeriod 0 throughout')
        elif bp:
            notes.append('brainUpdatePeriod varies: %s'
                         % sorted(x for x in bp if x is not None))
        raids = len(set((r['log'], r['raid']) for r in v))
        print('%-15s %5d %5d %9d   %s'
              % (m, raids, len(v), sum(r['frames'] for r in v),
                 '; '.join(notes) or '-'))

    # Named rather than counted: "six maps untested" is a number someone has to
    # trust, while a list is a thing they can act on.
    known = {
        'tarkovstreets': 'Streets', 'bigmap': 'Customs',
        'factory4_day': 'Factory', 'interchange': 'Interchange',
        'woods': 'Woods', 'shoreline': 'Shoreline', 'rezervbase': 'Reserve',
        'laboratory': 'Labs', 'lighthouse': 'Lighthouse',
        'sandbox': 'Ground Zero',
    }
    seen = set(by_map(play))
    missing = [n for k, n in known.items() if k not in seen]
    print('\nNever launched: %s' % ', '.join(missing))
    print('Reserve and Lighthouse are the boss-scripting cases -- Gluhar and')
    print('Zryachiy cannot stand by at all -- so they are the likeliest to fail')
    print('goal 1 and carry the least evidence.')


def excluded_report(excluded, counted):
    """Reported, not deleted. Stratified beside the headline, with the reason."""
    if not excluded:
        return
    print('\n=== EXCLUDED BY NAME -- one entry per log, reason stated ===\n')
    for log, v in sorted(excluded.items()):
        f = fps(v)
        mx = [r['max'] for r in v if r['max'] is not None]
        same = [r for r in counted
                if r['map'] in set(x['map'] for x in v)]
        print('  %s   %d windows on %s'
              % (log, len(v), ', '.join(sorted(set(r['map'] for r in v)))))
        print('    reason: %s' % EXCLUDED[log])
        print('    p50 fps median %.1f against %.1f for the counted windows on '
              'the same map' % (st.median(f), st.median(fps(same)) if same
                                else float('nan')))
        if mx:
            print('    worst frame %.1f ms; %d of %d windows over %.0f ms'
                  % (max(mx), sum(1 for x in mx if x > HITCH_MS), len(mx),
                     HITCH_MS))
    print('\nThese are harder windows, not invalid ones. They are held out '
          'because the\nsightline was picked to maximise draw calls -- selected '
          'on the dependent\nvariable -- and for no broader reason. Holding an '
          'angle is playing the game.')


def main():
    counted, excluded, knobs = collect()
    if not counted:
        print('Every log is on the exclusion list.')
        return
    print('%d windows counted across %d logs; %d held out by name'
          % (len(counted), len(set(r['log'] for r in counted)),
             sum(len(v) for v in excluded.values())))
    goal_one(counted)
    goal_two(counted)
    coverage(counted)
    knob_variation(knobs)
    excluded_report(excluded, counted)


main()
