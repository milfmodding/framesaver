"""Regenerate the per-log provenance table in CORPUS.md.

Dependency-free. Prints markdown to stdout; paste over the table body.

Two normalisations are applied together and both are required — applying one
without the other is how two agents each read a phantom regression into the
era-C logs (see CORPUS.md, "line-pairing slip"):

  * period > 100 ms      - so logs at different spike thresholds are comparable
  * magnitude cut of 1 ms - so sub-millisecond clock jitter is not pooled with a
                            mechanism whose signature is -56 to -200 ms

The corpus is snapshotted once. A log being written by a live game grows between
reads, and a script that re-globs per section will disagree with itself by a
handful of lines with nothing in its output to say so.
"""
import json
import os
import glob
import sys
import datetime

# The table contains em-dashes, and a default Windows console is cp1252. Without
# this the documented workflow -- run it, paste the output over the table body --
# silently replaces every em-dash with a mojibake byte. Reading was already
# UTF-8; only writing was left to the platform.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

LOGS = r'F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs'

# cfg key count is the primary way to date a log: it is monotonic across the
# project's history and survives files being copied, renamed or re-dated.
ERA = {11: 'A', 15: 'B', 20: 'C'}

LIVE_SECONDS = 1200      # newer than this and the file may still be growing
PERIOD_FLOOR = 100.0     # ms
MAGNITUDE = 1.0          # ms


def snapshot(directory):
    """Read every log once. Returns [(name, header, samples, spikes)]."""
    out = []
    for path in sorted(glob.glob(os.path.join(directory, 'framesaver-*.ndjson'))):
        header, samples, spikes = None, [], []
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue           # partial final line of a live log
                kind = d.get('type')
                if kind == 'header':
                    header = d
                elif kind == 'sample':
                    samples.append(d)
                elif kind == 'spike':
                    spikes.append(d)
        out.append((path, header, samples, spikes))
    return out


def row(path, header, samples, spikes):
    name = os.path.basename(path).replace('framesaver-', '').replace('.ndjson', '')
    era = ERA.get(len((samples[0].get('cfg') or {})) if samples else 0, '—')

    expanded = sorted({k.split('/')[0] for s in samples
                       for k in (s.get('phases') or {}) if '/' in k})
    expanded = '**all 8**' if len(expanded) >= 8 else (','.join(expanded) or '—')

    raids = len({s.get('raid') for s in samples if s.get('raid')})
    maps = sorted({str(s.get('map')) for s in samples
                   if s.get('map') and s.get('map') != 'None'})

    in_raid = [s for s in samples
               if s.get('state') == 'raid' and (s.get('bots') or {}).get('total', 0)]
    inflated = sum(1 for s in in_raid
                   if s['bots']['animCulled'] > s['bots']['asleep'])

    norm = [x for x in spikes
            if x.get('state') == 'raid' and x.get('period', 0) > PERIOD_FLOOR]
    slip = sum(1 for x in norm
               if x['frame'] > x['period'] + MAGNITUDE
               or x.get('unaccounted', 0) < -MAGNITUDE)

    age = (datetime.datetime.now()
           - datetime.datetime.fromtimestamp(os.path.getmtime(path))).total_seconds()
    if not samples and not spikes:
        state = '**empty**'
    elif age < LIVE_SECONDS:
        state = '**live**'
    elif not in_raid:
        state = 'no in-raid'
    else:
        state = 'complete'

    threshold = header.get('spikeEventMs') if header else '—'
    return '| `%s` | %s | %s | %s | %s | %d | %s | %s | %s |' % (
        name, state, era,
        '**%s**' % threshold if threshold == 30 else threshold,
        expanded, raids, ', '.join(maps) or '—',
        '%d/%d' % (inflated, len(in_raid)) if in_raid else '—',
        '%d/%d' % (slip, len(norm)) if norm else '—')


if __name__ == '__main__':
    corpus = snapshot(LOGS)
    print('| log | state | era | spike ms | expanded | raids | maps | '
          'animCulled infl | line-pairing slip |')
    print('|---|---|---|---|---|---|---|---|---|')
    for entry in corpus:
        print(row(*entry))
    live = [os.path.basename(p) for p, _, _, sp in corpus
            if (datetime.datetime.now()
                - datetime.datetime.fromtimestamp(os.path.getmtime(p))).total_seconds() < LIVE_SECONDS]
    if live:
        print()
        print('NOTE: %d log(s) may still be growing: %s' % (len(live), ', '.join(live)))
        print('Their counts are partial. Regenerate once the session ends.')
