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

THE POPULATION RULE, AND IT DEFAULTS TO EXCLUDING. A held-position protocol
window measures a chosen worst-case sightline, not play, so it cannot inform a
criterion about playing. But "held" is not the discriminator -- standing still
while looting or sniping is play, and cutting on `pos.dist` would define the
population by what is convenient. The discriminator is the *run's intent*, which
lives in `header.tag` and nowhere in the data.

So intent is declared per tag below, and an undeclared tag is NOT counted. That
is the same default as the precondition gate in harness/registrations.json and
for the same reason: a false exclusion costs a line of typing here, while a false
inclusion corrupts the release number. The difference from the declaration
schemes that failed on 2026-07-28 is that this one fails LOUDLY -- unclassified
windows are printed with their tag and their count, so the missing population
announces itself instead of quietly not being there.
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

# Declared intent per `header.tag`. `play` windows count toward the scoreboard;
# `protocol` windows are held-position arms measuring something else. An
# undeclared tag counts as neither and is reported.
INTENT = {
    'baseline': 'play',
    'ai-stack': 'play',
    'control': 'play',
    'postlate-gc': 'play',
    'latch': 'protocol',        # 2026-07-28: Protocol A and B, held sightline
    'endtolatch': 'protocol',   # queued as the same shape
}

# A hitch is a stall a player would notice, not a threshold the log happened to
# be configured with. `Spike event ms` has been 100, 50 and 30 across the corpus
# and spike counts do not join across those; a percentile does.
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
                'frames': d.get('frames') or 0,
                'cfg0': cfg0,
            })
    return tag, cfg0, rows


def collect():
    play, other, knobs = [], {}, {}
    for path in sorted(glob.glob(os.path.join(LOGS, 'framesaver-*.ndjson'))):
        tag, cfg0, rows = read_log(path)
        if not rows:
            continue
        for k, v in cfg0.items():
            knobs.setdefault(k, {}).setdefault(repr(v), 0)
            knobs[k][repr(v)] += 1
        intent = INTENT.get(tag)
        for r in rows:
            r['tag'] = tag
            r['log'] = os.path.basename(path)[11:-7]
        if intent == 'play':
            play.extend(rows)
        else:
            other.setdefault(tag or '(no tag)', []).extend(rows)
    return play, other, knobs


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
    print('\n=== GOAL 2 -- in-raid hitches, threshold-free ===\n')
    print('A window\'s p999 is roughly its 3rd-worst frame out of ~3,700. It is '
          'an order\nstatistic in a small tail; treat a single window\'s value '
          'as indicative and the\nshare of windows as the measurement.\n')
    print('%-15s %5s %9s %9s %9s   %s'
          % ('map', 'n', 'p99 med', 'p999 med', 'p999 max',
             'windows with a >%.0f ms frame' % HITCH_MS))
    for m, v in sorted(by_map(play).items(), key=lambda kv: -len(kv[1])):
        p999 = [r['p999'] for r in v]
        bad = sum(1 for x in p999 if x > HITCH_MS)
        print('%-15s %5d %9.1f %9.1f %9.1f   %3d of %-4d (%3.0f%%)'
              % (m, len(v), st.median([r['p99'] for r in v]), st.median(p999),
                 max(p999), bad, len(v), 100.0 * bad / len(v)))


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


def unclassified(other):
    if not other:
        return
    print('\n=== NOT COUNTED -- declare the tag in INTENT to include ===\n')
    for tag, v in sorted(other.items()):
        maps = ', '.join(sorted(set(r['map'] for r in v)))
        f = fps(v)
        print('  %-14s %4d windows  %-22s p50 fps median %5.1f  [%s]'
              % (tag, len(v), maps, st.median(f),
                 INTENT.get(tag, 'UNDECLARED')))
    print('\nProtocol windows are excluded on purpose: they measure a chosen')
    print('sightline, not play. Pooling them moved Streets 60.6 -> 57.4 fps.')


def main():
    play, other, knobs = collect()
    if not play:
        print('No play windows. Every tag is undeclared or protocol.')
        unclassified(other)
        return
    print('%d play windows across %d logs; %d not counted'
          % (len(play), len(set(r['log'] for r in play)),
             sum(len(v) for v in other.values())))
    goal_one(play)
    goal_two(play)
    coverage(play)
    knob_variation(knobs)
    unclassified(other)


main()
