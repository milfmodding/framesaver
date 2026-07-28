"""Where the out-of-loop gap went after the boundary latch.

Delta, 2026-07-28.

FINDINGS attributes the 165-402 ms in-raid spike family to time outside
`PlayerLoop()`, on `endToStart ~ unaccounted` -- 12 of 12 to within 0.72 ms,
measured in the 0923 log. The 1252 log reads `endToStart` ~ 0.2 ms on every one
of its 47 comparable spikes, which looked like the attribution failing by 324 ms.

It is not. The field is alive -- 35 lines over 10 ms, max 453.65 -- and the gap
moved one line earlier relative to the spike:

    offset   endToStart within 5 ms of that spike's unaccounted
      i-2      0 / 47
      i-1     22 / 47        <- post-latch
      i+0      0 / 47        <- pre-latch: 12 / 15 in the 0923 log
      i+1      0 / 47

The 25 that miss are not failures, which is what this script exists to show.
Matched pairs sit 27-47 ms apart (median 33.6) -- the immediately preceding
frame. Unmatched pairs sit 383-11,096 ms apart (median 1,469): there is no
adjacent line, because that frame was never emitted as a spike. The two
populations are perfectly disjoint. It is 22 of 22 among cases where the test
could succeed.

What the pair looks like -- one stall, two lines, two clocks:

    i-1   frame 386.4   period  34.1   unaccounted   0.0   endToStart 352.4
    i+0   frame  30.5   period 382.8   unaccounted 352.4   endToStart   0.15

`endToStart` travels with `frame`; `unaccounted` travels with `period`. Before
the latch they landed on one line; after it, `period`'s anchor moved by one
boundary and they separated. Two consequences worth carrying: `frame > period`
on these events is the i-1 half of this pair rather than an independent anomaly,
and one stall emits TWO spike lines -- so any rate counted per spike line
over-counts this family by up to 2x.

Which anchor is *correct* is not decided here. Only that they used to agree.
"""

import json, statistics
p = 'F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-20260728-125209-latch.ndjson'
S = [json.loads(l) for l in open(p, encoding='utf-8', errors='replace') if '"spike"' in l]
S = [o for o in S if o.get('type') == 'spike']
hz = None
for l in open(p, encoding='utf-8', errors='replace'):
    o = json.loads(l)
    if o.get('type') == 'header': hz = o.get('qpcFrequency'); break
print('qpcFrequency', hz)
big = [(i, o) for i, o in enumerate(S) if o.get('state') == 'raid' and (o.get('unaccounted') or 0) >= 100]
print(f"{'i':>6s} {'unacc':>8s} {'e2s[i]':>8s} {'e2s[i-1]':>9s} {'gap i-1->i (ms)':>16s} {'match':>6s}")
gaps, hits = [], 0
for i, o in big:
    prev = S[i-1]
    dqpc = (o['qpc'] - prev['qpc']) / hz * 1000.0
    m = abs((prev.get('endToStart') or -1e9) - o['unaccounted']) <= 5.0
    hits += m
    gaps.append((dqpc, m))
    print(f"{i:>6d} {o['unaccounted']:>8.1f} {(o.get('endToStart') or 0):>8.2f} "
          f"{(prev.get('endToStart') if prev.get('endToStart') is not None else float('nan')):>9.2f} "
          f"{dqpc:>16.2f} {'YES' if m else '':>6s}")
mg = [g for g, m in gaps if m]
ng = [g for g, m in gaps if not m]
print()
print(f"matched pairs:   n={len(mg)} median inter-line gap {statistics.median(mg):.2f} ms  max {max(mg):.2f}")
if ng: print(f"unmatched pairs: n={len(ng)} median inter-line gap {statistics.median(ng):.2f} ms  max {max(ng):.2f}")
