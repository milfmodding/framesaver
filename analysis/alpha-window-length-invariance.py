"""Does halving the window improve the per-map p75, or is it a wash?

Gamma: p75 per-window noise rises 3.2% -> 4.5%, "but you gain twice as many windows, so a per-map
median tightens by sqrt(2) = 1.41x. Net win."

Both halves are right and they cancel. Total frames in a raid is FIXED, so:

    frames per window       N = T / n
    per-window p75 noise    s_w  proportional to 1/sqrt(N) = sqrt(n/T)
    noise of the aggregate  s_w / sqrt(n)  proportional to sqrt(n/T)/sqrt(n) = 1/sqrt(T)

The window count cancels exactly. Precision of a per-map percentile is set by TOTAL FRAMES, not by
how they are chopped up - and Gamma counted the sqrt(2) gain without propagating the sqrt(2) loss
that produced it. Same family as everything else today: a benefit computed over one population and
a cost over another.

Confirmed numerically below by direct simulation rather than by algebra alone, since the algebra is
what is in dispute.
"""
import random

random.seed(20260730)  # fixed, since Math.random-style variation would make this unrepeatable

TOTAL = 4021 * 10          # ten 60 s windows' worth of frames, one "raid"
TRIALS = 400


def p75(v):
    s = sorted(v)
    i = 0.75 * (len(s) - 1)
    lo = int(i)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def draw():
    """A frame-time-ish distribution: lognormal-ish body with a heavy right tail."""
    return [random.lognormvariate(2.6, 0.22) for _ in range(TOTAL)]


for n_windows, label in ((10, "60 s windows"), (20, "30 s windows"), (40, "15 s windows")):
    per_window_spread, aggregates = [], []
    for _ in range(TRIALS):
        frames = draw()
        per = TOTAL // n_windows
        wins = [p75(frames[i * per:(i + 1) * per]) for i in range(n_windows)]
        per_window_spread.append((max(wins) - min(wins)))
        aggregates.append(median(wins))
    m = sum(aggregates) / len(aggregates)
    sd = (sum((a - m) ** 2 for a in aggregates) / (len(aggregates) - 1)) ** 0.5
    print("%-14s %2d windows of %4d frames   median-of-window-p75 = %.4f  SD across trials %.5f"
          % (label, n_windows, TOTAL // n_windows, m, sd))

print()
print("If the SD column is flat, window length does not change the precision of the per-map")
print("figure - the total frame count does, and that is fixed by how long the raid is.")
