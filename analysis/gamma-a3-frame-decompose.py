#!/usr/bin/env python3
"""Which component of the frame moved in control arm A3?

QUESTION THIS ANSWERS (indexed here so it is findable by the question rather
than by my name): reg-unc-2026-08-05T072828. The three control arms of the
2026-08-04 anim-cull A/B carry the SAME eight config values by construction,
yet A3's mean frame ran ~33.4 ms against A2's ~22.5 ms. The animation phase
also moved, but only in step with the roster; the frame moved ~1.8x that. So
something that is NOT the cull and NOT the roster moved during the raid.

WHAT IT DOES, and it is a decomposition rather than a search. `frame.avg` is
a per-frame mean and so is every `phases.<top>.avg`, so the top-level phases
SUM to the frame up to an unaccounted remainder. That identity turns "what
moved?" into arithmetic: difference the per-arm phase means and every
millisecond of the frame delta lands in a named bucket. No candidate list is
consulted and nothing is ranked by suspicion -- a mover cannot hide by not
being on a list of things I thought of.

THE IDENTITY IS CHECKED BEFORE IT IS USED, and the check can fail. If the
reconstructed frame does not match `frame.avg` within RECON_TOL_MS the script
REFUSES rather than reporting a decomposition of a quantity it cannot
reproduce. A decomposition whose parts do not sum to the whole is not a
decomposition, and the failure is silent unless something asserts it.

POPULATION comes from `steady.partition` and `arm_of`, the same rules
read-animcull.py uses. Not reimplemented: a second copy of a population rule
forks from the original silently.

WHAT IT DOES NOT DO. It says WHERE the time went, not WHY. Locating the delta
in a phase is not a cause, and the difference between those two is what my
predecessor's exit review records itself getting wrong twice in one hour.
"""

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import steady  # noqa: E402

# The frame must reconstruct from its phases to within this, or we refuse.
# Not a tuned value: the per-window residual `unaccounted` is reported by the
# plugin itself and runs in the hundredths, so a tolerance of 1 ms is loose
# by an order of magnitude and still catches a decomposition that is simply
# not additive.
RECON_TOL_MS = 1.0

# An arm below this is reported and not scored -- two windows cannot show a
# dispersion, the same floor read-animcull.py uses.
MIN_WINDOWS = 3

TOP_PHASES = ('TimeUpdate', 'Initialization', 'EarlyUpdate', 'FixedUpdate',
              'PreUpdate', 'Update', 'PreLateUpdate', 'PostLateUpdate')


def arm_of(w):
    """(cullSleeping, skipLate, cullAllBots), or None if unresolvable.

    Copied deliberately from read-animcull.py rather than imported: that file
    is a script and not a module, and importing it executes its main. The
    REFUSAL semantics are the load-bearing part -- an absent flag is not a
    false one, or the control arm silently fills with windows that never
    declared an arm.
    """
    cfg = w.get('cfg') or {}
    cull, skip = cfg.get('cullSleeping'), cfg.get('skipLate')
    if cull is None or skip is None:
        return None
    all_bots = cfg.get('cullAllBots')
    return (bool(cull), bool(skip),
            None if all_bots is None else bool(all_bots))


def leaf(w, path, default=None):
    """Fetch a dotted path. Absent returns `default` and NOT 0 -- absent,
    false and zero are three values and collapsing them is how a field that
    was never emitted reads as a measured nothing."""
    cur = w
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def phase_leaves(w):
    """Every `phases.<top>/<child>` avg present in this window."""
    out = {}
    for k, v in (w.get('phases') or {}).items():
        if isinstance(v, dict) and 'avg' in v:
            out[k] = v['avg']
    return out


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def stdev(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def load(paths):
    rows = []
    for p in paths:
        header = None
        with open(p, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get('type') == 'header':
                    header = o
                    continue
                if o.get('type') != 'sample':
                    continue
                # steady.window_length reads a per-window length that older
                # logs carry only on the header.
                o['_windowSeconds'] = (
                    (header or {}).get('windowSeconds')
                    or ((header or {}).get('config') or {}).get('windowSeconds'))
                o['_source'] = os.path.basename(p)
                rows.append(o)
    return rows


def eligible(rows):
    """Steady windows that carry an arm and were not protocol-truncated."""
    kept, dropped = steady.partition(rows, drop_teardown=True, by_start=True)
    out, no_arm, partial = [], 0, 0
    for w in kept:
        if w.get('flushedByProtocol'):
            partial += 1
        elif arm_of(w) is None:
            no_arm += 1
        else:
            out.append(w)
    dropped = dict(dropped)
    dropped['flushed by protocol'] = partial
    dropped['arm unresolvable'] = no_arm
    return out, dropped


def control_runs(windows):
    """Contiguous runs of CONTROL windows (cullSleeping false), in raid order.

    A run is an "arm" in the protocol's sense. Identified by contiguity in
    `protocol.step` rather than by counting, so a protocol that reorders its
    arms does not silently relabel A3.
    """
    runs, cur = [], []
    for w in sorted(windows, key=lambda x: (x.get('t') or 0)):
        is_control = (arm_of(w) or (None,))[0] is False
        step = leaf(w, 'protocol.step')
        if is_control and (not cur or step == cur[-1][1]):
            cur.append((w, step))
        else:
            if cur:
                runs.append([x[0] for x in cur])
            cur = [(w, step)] if is_control else []
    if cur:
        runs.append([x[0] for x in cur])
    return runs


def check_identity(windows, label):
    """POSITIVE CONTROL. Reconstruct frame.avg from the top-level phases.

    If this does not hold, every number below it is a decomposition of
    something that is not the frame, and the whole report is void. Returns
    (ok, worst_abs_residual_ms, n_checked).
    """
    worst, n = 0.0, 0
    for w in windows:
        f = leaf(w, 'frame.avg')
        if f is None:
            continue
        recon = 0.0
        for p in TOP_PHASES:
            v = leaf(w, 'phases.%s.avg' % p)
            if v is not None:
                recon += v
        worst = max(worst, abs(recon - f))
        n += 1
    return worst <= RECON_TOL_MS, worst, n


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('logs', nargs='+', help='ndjson log path(s)')
    ap.add_argument('--top', type=int, default=14,
                    help='how many leaf movers to print (default 14)')
    args = ap.parse_args()

    rows = load(args.logs)
    windows, dropped = eligible(rows)
    print('POPULATION')
    print('  samples read          %d' % len(rows))
    print('  eligible windows      %d' % len(windows))
    for k, v in sorted(dropped.items()):
        if v:
            print('    dropped: %-28s %d' % (k, v))
    if not windows:
        print('  REFUSED: no eligible windows.')
        return 2

    runs = control_runs(windows)
    print('  control runs found    %d  (sizes %s)'
          % (len(runs), ', '.join(str(len(r)) for r in runs)))
    scored = [r for r in runs if len(r) >= MIN_WINDOWS]
    if len(scored) < 2:
        print('  REFUSED: fewer than two control runs reach %d windows.'
              % MIN_WINDOWS)
        return 2

    # ---- positive control -------------------------------------------------
    print()
    print('IDENTITY CHECK  (frame.avg == sum of top-level phases?)')
    ok, worst, n = check_identity(windows, 'all')
    print('  windows checked       %d' % n)
    print('  worst residual        %.4f ms   tolerance %.2f ms' % (worst, RECON_TOL_MS))
    if not ok:
        print('  REFUSED. The frame does not reconstruct from its phases, so a')
        print('  per-phase decomposition of the A3 delta would be a')
        print('  decomposition of something else. Nothing below is printed.')
        return 3
    print('  OK -- the decomposition below is additive and exhausts the frame.')

    # ---- per-arm levels ---------------------------------------------------
    labels = ['A%d' % (i + 1) for i in range(len(scored))]
    print()
    print('CONTROL ARMS  (cullSleeping=false in all of them, by construction)')
    hdr = '  %-4s %5s %9s %9s %9s %9s %9s'
    print(hdr % ('arm', 'n', 'frame', 'sd', 'animPhase', 'awake', 'total'))
    for lab, run in zip(labels, scored):
        print('  %-4s %5d %9.3f %9.3f %9.3f %9.2f %9.2f'
              % (lab, len(run),
                 mean([leaf(w, 'frame.avg') for w in run]),
                 stdev([leaf(w, 'frame.avg') for w in run]) or float('nan'),
                 mean([leaf(w, 'phases.PreLateUpdate/DirectorUpdateAnimationBegin.avg')
                       for w in run]),
                 mean([leaf(w, 'bots.awake') for w in run]),
                 mean([leaf(w, 'bots.total') for w in run])))

    # ---- the decomposition, last arm against each earlier one -------------
    target = scored[-1]
    tlab = labels[-1]
    for lab, run in zip(labels[:-1], scored[:-1]):
        print()
        print('=' * 72)
        print('DECOMPOSITION  %s - %s   (every ms of the frame delta, by bucket)'
              % (tlab, lab))
        f_t = mean([leaf(w, 'frame.avg') for w in target])
        f_b = mean([leaf(w, 'frame.avg') for w in run])
        print('  frame  %.3f -> %.3f   delta %+.3f ms  (%+.1f%%)'
              % (f_b, f_t, f_t - f_b, 100.0 * (f_t - f_b) / f_b))
        print()
        print('  top-level phase          %8s %8s %9s %8s'
              % (lab, tlab, 'delta', 'share'))
        total_delta = 0.0
        rowsout = []
        for p in TOP_PHASES:
            a = mean([leaf(w, 'phases.%s.avg' % p) for w in run])
            b = mean([leaf(w, 'phases.%s.avg' % p) for w in target])
            if a is None or b is None:
                continue
            rowsout.append((b - a, p, a, b))
            total_delta += (b - a)
        for d, p, a, b in sorted(rowsout, key=lambda x: -abs(x[0])):
            share = 100.0 * d / total_delta if total_delta else float('nan')
            print('  %-24s %8.3f %8.3f %+9.3f %7.1f%%' % (p, a, b, d, share))
        print('  %-24s %8s %8s %+9.3f %7.1f%%'
              % ('SUM', '', '', total_delta, 100.0))
        print('  (frame delta %+.3f, phase-sum delta %+.3f, residual %+.3f)'
              % (f_t - f_b, total_delta, (f_t - f_b) - total_delta))

        # leaf level
        keys = set()
        for w in run + target:
            keys |= set(phase_leaves(w))
        movers = []
        for k in keys:
            a = mean([phase_leaves(w).get(k) for w in run])
            b = mean([phase_leaves(w).get(k) for w in target])
            if a is None or b is None:
                continue
            movers.append((b - a, k, a, b))
        print()
        print('  leaf movers (of %d leaves present in both arms)' % len(movers))
        print('  %-46s %7s %7s %8s' % ('leaf', lab, tlab, 'delta'))
        for d, k, a, b in sorted(movers, key=lambda x: -abs(x[0]))[:args.top]:
            print('  %-46s %7.3f %7.3f %+8.3f' % (k[:46], a, b, d))

    # ---- per-awake-bot normalisation --------------------------------------
    print()
    print('=' * 72)
    print('ROSTER NORMALISATION  (does the mover scale with awake bots?)')
    print('  %-4s %9s %9s %11s %11s'
          % ('arm', 'awake', 'frame', 'frame/awake', 'anim/awake'))
    for lab, run in zip(labels, scored):
        aw = mean([leaf(w, 'bots.awake') for w in run])
        fr = mean([leaf(w, 'frame.avg') for w in run])
        an = mean([leaf(w, 'phases.PreLateUpdate/DirectorUpdateAnimationBegin.avg')
                   for w in run])
        print('  %-4s %9.2f %9.3f %11.3f %11.3f'
              % (lab, aw, fr, fr / aw if aw else float('nan'),
                 an / aw if aw else float('nan')))
    print()
    print('  A per-awake-bot ratio is NOT a per-bot cost: it divides a total')
    print('  that contains a fixed part by a roster, so it moves when the')
    print('  roster moves even if nothing per-bot changed. Read it as a')
    print('  normalisation for comparing arms, never as a marginal cost.')

    association(windows)
    return 0


def corr(xs, ys):
    """Pearson r, plus n and the predictor's observed range.

    THE RANGE IS RETURNED BECAUSE IT IS THE PART THAT DECIDES WHETHER r MEANS
    ANYTHING. A predictor that never moved produces a correlation from noise,
    and this project has already published one such: a monotonic three-point
    trend over a predictor range of 0.009. Printing the range next to r is
    what stops the next reader repeating it.
    """
    pts = [(x, y) for x, y in zip(xs, ys)
           if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    n = len(pts)
    if n < 3:
        return None, n, None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    syy = sum((p[1] - my) ** 2 for p in pts)
    rng = (min(p[0] for p in pts), max(p[0] for p in pts))
    if sxx == 0 or syy == 0:
        return None, n, rng
    return sxy / (sxx * syy) ** 0.5, n, rng


# Candidates for what tracks the mover. Deliberately includes predictors
# expected to FAIL -- a candidate list containing only plausible entries
# cannot distinguish a real association from the fact that everything in a
# raid grows together.
CANDIDATES = [
    ('raidElapsed', 'raid elapsed s'),
    ('bots.total', 'bots total (awake+asleep)'),
    ('bots.awake', 'bots awake'),
    ('spawn.zoneAttempts', 'spawn zoneAttempts'),
    ('proc.wsMb', 'working set MB'),
    ('playerLate.avg', 'playerLate ms'),
    ('gc.heapMb.avg', 'GC heap MB'),
    ('gc.allocMbPerSec', 'alloc MB/s'),
    ('gpu.render.drawCalls.avg', 'draw calls'),
    ('gpu.render.triangles', 'triangles'),
]

RESPONSE = 'phases.Update/ScriptRunBehaviourUpdate.avg'


def association(windows):
    """What tracks the mover, and -- the load-bearing half -- what cannot be
    told apart from what.

    A ranked correlation table invites picking the winner. In a single raid
    almost everything is monotone in time, so the winner is usually just
    whichever collinear quantity has the least noise. The cross-correlation
    matrix below is printed FIRST-CLASS, not as a diagnostic, because it is
    the thing that decides whether the ranking may be read at all.
    """
    y = [leaf(w, RESPONSE) for w in windows]
    ys = [v for v in y if isinstance(v, (int, float))]
    print()
    print('=' * 72)
    print('ASSOCIATION  (n=%d eligible windows, BOTH arms -- needs variation,'
          % len(windows))
    print('              so this pools cull and control deliberately)')
    print()
    print('  response: %s' % RESPONSE)
    print('            range %.3f .. %.3f ms' % (min(ys), max(ys)))
    print()
    print('  %-28s %7s %6s %22s' % ('predictor', 'r', 'n', 'observed range'))
    got = []
    for path, lab in CANDIDATES:
        xs = [leaf(w, path) for w in windows]
        r, n, rng = corr(xs, y)
        if r is None:
            print('  %-28s %7s %6d   %s' % (lab, '--', n, 'no variation'))
            continue
        got.append((path, lab, r, xs))
        print('  %-28s %7.3f %6d %10.1f .. %-10.1f' % (lab, r, n, rng[0], rng[1]))

    print()
    print('  CROSS-CORRELATION between predictors -- which of these are the')
    print('  same variable wearing different names?')
    labs = [g[1] for g in got]
    print('  %-28s' % '' + ''.join('%9s' % l[:8] for l in labs))
    for path_a, lab_a, _, xs_a in got:
        cells = []
        for path_b, lab_b, _, xs_b in got:
            r, _, _ = corr(xs_a, xs_b)
            cells.append('%9s' % ('%.2f' % r if r is not None else '--'))
        print('  %-28s' % lab_a + ''.join(cells))
    print()
    print('  READ THE MATRIX BEFORE THE RANKING. Any block of predictors')
    print('  mutually above ~0.8 is one axis, and this design cannot say')
    print('  which member of it is the cause. A predictor that is ORTHOGONAL')
    print('  to that block and still fails to track the response is a real')
    print('  negative -- that is the only kind of conclusion available here.')


if __name__ == '__main__':
    sys.exit(main())
