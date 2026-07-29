"""Turn perception marks into a bound on the hitch threshold.

Usage:  python read-marks.py <log.ndjson> [more.ndjson ...]

WRITTEN BEFORE A SINGLE MARK EXISTS. That matters more here than anywhere else in
this directory, because the quantity being estimated is a threshold and almost every
choice below could be tuned to tighten it after the fact. Fixed in advance:

  * the event a mark refers to is the worst frame in the EMITTED lookback, whole.
    No sub-window search. A search would find the reading that flatters the bracket.
  * the delta statistic is the largest frame-to-frame change in the same lookback.
  * a "watched" raid is declared by the runner, never inferred from the marks in it.

WHY THERE IS NO TOLERANCE PARAMETER, which is the design's best property. Every
previous join in this project needed a window - plus or minus so many milliseconds
or seconds - and one of them inflated a coincidence baseline until the rate and its
null matched unconditionally. Here the mark CARRIES its own lookback, so the join is
the payload. There is nothing to widen and therefore nothing to widen until it
agrees.

WHAT IT ESTIMATES. Perception is bracketed from both sides:

  * every mark gives an UPPER bound - she perceived something no larger than the
    worst frame in its lookback, so the threshold is at or below that.
  * every large frame in a watched raid with NO mark covering it gives a LOWER
    bound - she was watching and did not react, so the threshold is above it.

The tightest bracket is (largest unmarked event, smallest marked event).

**AND THE PRE-REGISTERED PREDICTION IS THAT THIS CAN FAIL.** If the smallest marked
event is BELOW the largest unmarked one, the bracket inverts, and perception is not
a threshold on `frame.max` at all. That would be a real finding rather than a
disappointment: it points at the frame-to-frame delta, which is what stutter
physically is and which no metric in this project has ever measured. Reported as an
inversion rather than quietly collapsed into a single number.

JOIN MARKS TO SPIKE LINES ON `qpc`, NEVER ON TIME AND MAGNITUDE. The first attempt
matched a mark's worst lookback frame against nearby spike lines by `t` and size, and
it failed on all three real marks -- returning a 30.6 ms line for a 122.5 ms event,
because `frame` travels one line ahead of `period` so neither field matches what the
lookback recorded. Both line types carry `qpc`, and `header.qpcFrequency` converts the
lookback span to ticks, so the join is exact and needs no tolerance. It found all
three immediately.

`frameMs` is emitted NEWEST FIRST - the writer walks the ring backwards. Reversed on
read, because a delta series computed in the wrong direction is sign-flipped and
still looks plausible.
"""
import json
import os
import statistics as st
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Logs the runner has confirmed she was watching for hitches. Absence of marks is
# evidence ONLY in these. A log not listed contributes its positives and no
# negatives, because a raid where nobody was watching cannot testify to silence.
WATCHED = (
    # 'framesaver-20260728-XXXXXX-tag',
)
BAND_LO = 146.0     # largest frame she has been observed not to react to
BAND_HI = 300.0     # smallest family she has spontaneously reported


def load(paths):
    marks, samples, spikes, freq = [], [], [], None
    for path in paths:
        # Stem is YYYYMMDD-HHMMSS-tag; the date is constant within a run
        # and the time+tag is what distinguishes logs in a table.
        name = os.path.basename(path)[20:-7]
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            d['_log'] = name
            if d.get('type') == 'header':
                freq = freq or d.get('qpcFrequency')
            if d.get('type') == 'mark':
                marks.append(d)
            elif d.get('type') == 'sample' and d.get('state') == 'raid':
                samples.append(d)
            elif d.get('type') == 'spike':
                spikes.append(d)
    return marks, samples, spikes, freq


def series(mark):
    """Lookback frames, oldest first."""
    return list(reversed(mark.get('frameMs') or []))


def worst_delta(xs):
    if len(xs) < 2:
        return None
    return max(abs(xs[i] - xs[i - 1]) for i in range(1, len(xs)))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    marks, samples, spikes, freq = load(argv[1:])
    if not marks:
        print('No mark lines in %d log(s).' % (len(argv) - 1))
        print('That is not the same as no hitches - it means either the key was '
              'unbound,\nthe runner did not press it, or the raid was clean. '
              'Which of those it was\nis not in the log; ask.')
        return 1

    print('%d mark(s) across %d log(s)\n'
          % (len(marks), len(set(m['_log'] for m in marks))))

    print('%-5s %-16s %-13s %-7s %-8s %-9s %-9s %s'
          % ('mark', 'log', 'map', 'frames', 'span ms', 'worst ms',
             'worst d', 'reading'))
    uppers = []
    for m in sorted(marks, key=lambda x: (x['_log'], x.get('mark', 0))):
        xs = series(m)
        if not xs:
            print('%-5s %-16s %-13s %-7d %-8s %s'
                  % (m.get('mark'), m['_log'], (m.get('map') or '?')[:13],
                     0, '-', 'EMPTY LOOKBACK - nothing to attribute'))
            continue
        mx = max(xs)
        wd = worst_delta(xs)
        if mx >= BAND_HI:
            reading = 'above the band - expected to be perceived'
        elif mx >= BAND_LO:
            reading = 'IN the undetermined band - this is the useful case'
        else:
            reading = 'below %g ms - stray press, or threshold lower than thought' % BAND_LO
        uppers.append((mx, m))
        print('%-5s %-16s %-13s %-7d %-8.0f %-9.1f %-9.1f %s'
              % (m.get('mark'), m['_log'], (m.get('map') or '?')[:13],
                 m.get('frames', len(xs)), m.get('spanMs') or 0, mx,
                 wd if wd is not None else 0, reading))

    # ---- ISOLATED HITCH OR SUSTAINED BAD STRETCH ------------------------
    #
    # THE MARKS ARE NO LONGER ONE POPULATION AND POOLING THEM IS UNSAFE.
    # Four of tonight's five are a single bad frame in an otherwise smooth five
    # seconds; the Reserve mark is five seconds that were bad throughout. Those
    # are different stimuli, and a threshold estimated from the mixture answers
    # neither question - she may have reacted to the worst frame in one case and
    # to the sustained badness in the other. The upper bound below only means
    # "she perceived something no larger than this" if the worst frame is what
    # she perceived.
    #
    # THE DISCRIMINATOR IS p99/p50 OF THE LOOKBACK AND IT HAS NO FREE PARAMETER,
    # which is why it beats counting frames above a chosen line: a count needs a
    # threshold invented after seeing the data. Tonight it separates completely:
    #
    #     Lighthouse 1  p99 20.6      Woods 1  p99 16.8
    #     Lighthouse 2  p99 24.9      Woods 2  p99 17.6
    #     Reserve 1     p99 86.7   <- 3.5x the largest of the others
    #
    # The count view agrees at every threshold from 40 to 75 ms - four marks
    # read 1 frame over, Reserve reads 3 - so the split is not an artifact of
    # the statistic. Reported and not gated: two populations with one member
    # each is a distinction, not a rate.
    print()
    print('--- isolated hitch, or a sustained bad stretch? -------------')
    print('%-5s %-13s %-8s %-8s %-8s %s'
          % ('mark', 'map', 'p50', 'p99', 'worst', 'reading'))
    sustained = []
    for m in sorted(marks, key=lambda x: (x['_log'], x.get('mark', 0))):
        xs = sorted(series(m))
        if not xs:
            continue
        p50 = xs[len(xs) // 2]
        p99 = xs[min(len(xs) - 1, int(0.99 * len(xs)))]
        # The RATIO, not the level: a p99 near the p50 means the lookback was
        # smooth apart from its worst frame, whatever the map's frame rate.
        ratio = p99 / p50 if p50 else float('inf')
        kind = ('SUSTAINED - the whole lookback was bad' if ratio >= 3.0
                else 'isolated hitch in a smooth stretch')
        if ratio >= 3.0:
            sustained.append(m)
        print('%-5s %-13s %-8.1f %-8.1f %-8.1f %s'
              % (m.get('mark'), (m.get('map') or '?')[:13], p50, p99, xs[-1], kind))
    if sustained and len(sustained) < len(marks):
        print()
        print('BOTH KINDS PRESENT. The bounds below pool them, and that is only')
        print('valid if she reacts to the same thing in both - which is exactly')
        print('what is not established. Read the bracket as the ISOLATED-HITCH')
        print('bound, and treat the sustained marks separately until there are')
        print('enough of them to bound on their own.')

    # ---- the two bounds -------------------------------------------------
    print('\n--- bounds -------------------------------------------------')
    lo_bound = None
    if not WATCHED:
        print('UPPER bound only. No log is declared watched, so no silence counts')
        print('as a negative - add logs to WATCHED once the runner confirms she was')
        print('marking in them. Until then the threshold has no lower bound here.')
    else:
        big = [s for s in samples
               if s['_log'] in WATCHED
               and (s.get('frame') or {}).get('max') is not None
               and s['frame']['max'] >= BAND_LO]
        covered = set()
        for mx, m in uppers:
            covered.add((m['_log'], m.get('window')))
        unmarked = [s for s in big if (s['_log'], s.get('window')) not in covered]
        if unmarked:
            lo_bound = max(s['frame']['max'] for s in unmarked)
            print('%d window(s) in watched logs carry a frame >= %g ms with no mark'
                  % (len(unmarked), BAND_LO))
            print('LOWER bound: threshold is above %.1f ms' % lo_bound)
        else:
            print('Every large frame in a watched log carries a mark - no lower '
                  'bound yet.')

    if uppers:
        # Keyed, because min() over (float, dict) tuples raises TypeError the
        # moment two marks share a worst frame - a tie is not exotic when the
        # same stall is marked twice.
        best = min(uppers, key=lambda u: u[0])
        up = best[0]
        print('UPPER bound: threshold is at or below %.1f ms (mark %s on %s)'
              % (up, best[1].get('mark'), best[1]['_log']))
        if lo_bound is not None:
            if up > lo_bound:
                print('\nBRACKET: %.1f - %.1f ms  (was %g - %g)'
                      % (lo_bound, up, BAND_LO, BAND_HI))
            else:
                # The pre-registered failure. Do not average it away.
                print('\n*** INVERTED: smallest marked event %.1f ms is BELOW the '
                      'largest\n    unmarked one %.1f ms. Perception is NOT a '
                      'threshold on frame.max.' % (up, lo_bound))
                print('    Look at the delta column: if marked lookbacks carry '
                      'larger frame-to-frame\n    changes than unmarked ones at '
                      'the same peak, the perceived quantity is the\n    '
                      'derivative and not the level. That is a finding, not a '
                      'measurement failure.')

    # ---- in-loop or out-of-loop? ---------------------------------------
    #
    # Exact join on qpc. A mark's lookback spans `spanMs`, so the spike lines that
    # describe the same interval are those whose qpc falls inside it. `unaccounted`
    # then says whether the stall she reacted to was inside PlayerLoop or in the
    # native gap between frames - the two families goal 2 has to cover, and there
    # is no reason to assume perception treats them alike.
    if freq and spikes:
        print('\n--- what kind of stall did she react to? --------------------')
        print('%-6s %-14s %-9s %-9s %-13s %s'
              % ('mark', 'map', 'period', 'frame', 'unaccounted', 'family'))
        for m in sorted(marks, key=lambda x: (x['_log'], x.get('mark', 0))):
            if m.get('state') != 'raid' or not m.get('qpc'):
                continue
            span = (m.get('spanMs') or 5000.0) / 1000.0
            q0, q1 = m['qpc'] - int(span * freq), m['qpc']
            ins = [d for d in spikes
                   if d.get('qpc') and q0 <= d['qpc'] <= q1
                   and d.get('_log') == m['_log']]
            if not ins:
                print('%-6s %-14s %s' % (m.get('mark'),
                                         (m.get('map') or '?')[:14],
                                         'no spike line inside the lookback'))
                continue
            d = max(ins, key=lambda x: x.get('period') or 0)
            pe = d.get('period') or 0.0
            un = d.get('unaccounted') or 0.0
            print('%-6s %-14s %-9.1f %-9.1f %-13.1f %s'
                  % (m.get('mark'), (m.get('map') or '?')[:14], pe,
                     d.get('frame') or 0, un,
                     'OUT-OF-LOOP' if un > 0.5 * pe else 'in-loop'))
        print('\nIf both families appear, stall TYPE does not explain what she '
              'notices, and the\ndiscriminator is elsewhere - do not quietly drop '
              'the one that does not fit.')

    # ---- level versus derivative ---------------------------------------
    print('\n--- level or derivative? ------------------------------------')
    # In-raid marks only. Pooling loading stalls in here put a 19,928 ms map load
    # beside a 122 ms in-play hitch and produced a median of 848 ms, which is a
    # number about nothing. Loading is a different regime with a different
    # threshold - goal 2's secondary target, measured separately or not at all.
    both = [(max(series(m)), worst_delta(series(m))) for m in marks
            if m.get('state') == 'raid' and len(series(m)) >= 2]
    if len(both) < 3:
        print('n=%d marks with a usable series - too few to compare the two.'
              % len(both))
    else:
        lv = [b[0] for b in both]
        dv = [b[1] for b in both]
        print('worst frame across marks: median %.1f  range %.1f - %.1f'
              % (st.median(lv), min(lv), max(lv)))
        print('worst delta across marks: median %.1f  range %.1f - %.1f'
              % (st.median(dv), min(dv), max(dv)))
        print('\nThe more consistent of the two is the better candidate for what '
              'she reacts to.\nSpread is the comparison, not the median - a '
              'threshold should be crossed at a\nsimilar value every time it '
              'fires.')
        for lbl, v in (('level', lv), ('delta', dv)):
            print('  %-6s coefficient of variation %.2f'
                  % (lbl, st.pstdev(v) / st.mean(v) if st.mean(v) else 0))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
