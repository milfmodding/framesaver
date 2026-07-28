"""Coincidence baseline for the endToStart/unaccounted pairing.

Delta, 2026-07-28, on Alpha's method. The adjacency split alone shows the two
populations are disjoint; a shuffled null shows the match rate is not reachable
by chance, which is the stronger argument and was Alpha's addition.

The null draws each `endToStart` at random from the whole log's pool and asks how
often it lands within the same 5 ms of the spike's `unaccounted`. Two conditions
matter and both are cheap to get wrong:

  * pairs must be temporally adjacent (<= 100 ms apart) -- a spike line's
    predecessor can be tens of seconds earlier;
  * the population must be cut at `unaccounted >= 100`.

Without the second cut the test is meaningless, and it fails loudly enough to be
worth reproducing:

    all in-raid spikes, 1252:   i-1  99.3%  vs baseline 99.0%
                                i+0  98.9%  vs baseline 98.8%
    unaccounted >= 100, 1252:   i-1 100.0%  vs baseline  0.0%
                                i+0   0.0%  vs baseline  0.0%

Almost every ordinary spike has both quantities near zero, where +-5 ms matches
everything. A baseline that moves from 0.4% to 99% between populations of the
same phenomenon is not evidence the logs differ -- it is evidence the cut is
wrong, and it is the cheapest signal available for that.
"""

import json, random, statistics
random.seed(20260728)
P = {'0923': 'F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-20260728-092354-postlate-gc.ndjson',
     '1252': 'F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-20260728-125209-latch.ndjson'}
TOL, ADJ = 5.0, 100.0

def run(tag, path, cut):
    S = [o for o in (json.loads(l) for l in open(path, encoding='utf-8', errors='replace')
                     if '"spike"' in l) if o.get('type') == 'spike']
    hz = 10_000_000
    big = [(i, o) for i, o in enumerate(S)
           if o.get('state') == 'raid' and (o.get('unaccounted') or 0) >= cut]
    pool = [o['endToStart'] for o in S if o.get('endToStart') is not None]
    out = {}
    for off in (-1, 0):
        elig = [(i, o) for i, o in big if 0 <= i+off < len(S)
                and abs(S[i+off]['qpc'] - o['qpc'])/hz*1000 <= ADJ]
        hit = sum(1 for i, o in elig
                  if S[i+off].get('endToStart') is not None
                  and abs(S[i+off]['endToStart'] - o['unaccounted']) <= TOL)
        # null: same eligible pairs, endToStart drawn at random from the whole log
        trials = [sum(1 for _ in elig if abs(random.choice(pool) - _[1]['unaccounted']) <= TOL)
                  for _ in range(2000)] if elig else [0]
        null = statistics.mean(trials)/len(elig)*100 if elig else float('nan')
        out[off] = (hit, len(elig), null)
    return big, out

for tag, path in P.items():
    for cut, label in ((100.0, 'unaccounted >= 100'), (0.0, 'all in-raid spikes')):
        big, out = run(tag, path, cut)
        print(f"{tag}  {label:22s}  n={len(big)}")
        for off in (-1, 0):
            h, n, nul = out[off]
            pct = h/n*100 if n else float('nan')
            print(f"    i{off:+d}: {h:>4d}/{n:<4d} = {pct:>5.1f}%   coincidence baseline {nul:>5.1f}%")
        print()
