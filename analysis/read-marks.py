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
    marks, samples = [], []
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
            if d.get('type') == 'mark':
                marks.append(d)
            elif d.get('type') == 'sample' and d.get('state') == 'raid':
                samples.append(d)
    return marks, samples


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
    marks, samples = load(argv[1:])
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

    # ---- level versus derivative ---------------------------------------
    print('\n--- level or derivative? ------------------------------------')
    both = [(max(series(m)), worst_delta(series(m))) for m in marks
            if len(series(m)) >= 2]
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
