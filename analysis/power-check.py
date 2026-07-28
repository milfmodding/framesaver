#!/usr/bin/env python3
"""Statistical power for the line-pairing-slip rate comparison in CORPUS.md.

Answers one question: given the number of qualifying spike lines a log
actually contains, what change in the slip rate could that log have
detected?

The rate itself is reportable. Comparing rates across builds is not, and
the reason is n rather than any defect in the data -- so this lives beside
the corpus rather than inside the defect list.

Dependency-free by the same rule as the other scripts here: a reader
should be able to run it against the published logs without installing
anything. Counts are taken from CORPUS.md's provenance table, which
corpus-table.py regenerates from the logs themselves.
"""

from math import comb, sqrt

# Counts of qualifying lines, from the provenance table in CORPUS.md.
# Both normalisations are already applied: period > 100 ms and a 1 ms
# magnitude cut. Applying one without the other is how two agents each
# read a phantom regression into the era-C logs.
CONTROL = ("20260727-232217-control", 8, 76)

# Both 2026-07-28 logs, pooled. They are the same build, same map and the
# same threshold, so pooling them is the one cross-log pooling this corpus
# permits. The second shipped in CORPUS.md as a `live` row at 1/6 and
# finished at 2/13 -- partial rows do not stay partial, and quoting one is
# how a number goes stale without changing.
TODAY = ("20260728 era-C pooled", 2 + 2, 24 + 13)
TODAY_PARTS = [
    ("20260728-092354-postlate-gc", 2, 24),
    ("20260728-100048-postlate-gc", 2, 13),
]

# The five logs with n >= 30, which bound the run-to-run range.
LARGE_N = [
    ("20260726-170412-baseline", 1, 34),
    ("20260726-183701-ai-stack", 4, 50),
    ("20260726-205307-ai-stack", 5, 35),
    ("20260727-201220-ai-stack", 3, 33),
    ("20260727-232217-control", 8, 76),
]

Z95 = 1.959963985


def wilson(k, n, z=Z95):
    """Wilson score interval. Chosen over the normal approximation because
    these are small n with proportions near zero, where the normal
    interval goes below zero and stops meaning anything."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    halfwidth = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((centre - halfwidth) / denom, (centre + halfwidth) / denom)


def fisher_exact_two_sided(a, b, c, d):
    """Two-sided Fisher exact test on [[a, b], [c, d]].

    Exact rather than chi-square: the expected cell counts here are well
    under 5, which is precisely where chi-square stops being valid."""
    n = a + b + c + d
    row1, row2, col1 = a + b, c + d, a + c

    def prob(x):
        return comb(row1, x) * comb(row2, col1 - x) / comb(n, col1)

    observed = prob(a)
    total = 0.0
    for x in range(max(0, col1 - row2), min(row1, col1) + 1):
        # The 1e-9 slack keeps floating-point ties from being dropped;
        # without it a table exactly as likely as the observed one can
        # fall out of the sum and deflate p.
        if prob(x) <= observed * (1 + 1e-9):
            total += prob(x)
    return min(total, 1.0)


def detectable_change(n, baseline_rate):
    """Smallest and largest counts at this n whose interval excludes the
    baseline. Returns (low_k, high_k), either possibly None."""
    low = high = None
    for k in range(n + 1):
        lo, hi = wilson(k, n)
        if hi < baseline_rate and low is None:
            low = k
        if lo > baseline_rate and high is None:
            high = k
    return low, high


def report(label, k, n):
    lo, hi = wilson(k, n)
    print(f"  {label:32s} {k:3d}/{n:<3d} = {k / n * 100:5.1f}%"
          f"   95% CI [{lo * 100:5.1f}%, {hi * 100:5.1f}%]")


def main():
    print("Line-pairing slip rate, logs with n >= 30")
    print("-" * 78)
    for label, k, n in LARGE_N:
        report(label, k, n)

    print()
    print("The comparison CORPUS.md used to call 'no build-related trend'")
    print("-" * 78)
    report(CONTROL[0], CONTROL[1], CONTROL[2])
    for label, k, n in TODAY_PARTS:
        report("  " + label, k, n)
    report(TODAY[0], TODAY[1], TODAY[2])

    p = fisher_exact_two_sided(TODAY[1], TODAY[2] - TODAY[1],
                               CONTROL[1], CONTROL[2] - CONTROL[1])
    print()
    print(f"  Fisher exact, two-sided: p = {p:.3f}")

    n = TODAY[2]
    baseline = CONTROL[1] / CONTROL[2]
    low_k, high_k = detectable_change(n, baseline)

    print()
    print(f"What n = {n} could have detected against a {baseline * 100:.1f}% baseline")
    print("-" * 78)
    if high_k is None:
        print("  no count at this n has an interval above the baseline")
    else:
        ratio = (high_k / n) / baseline
        print(f"  regression: {high_k}/{n} = {high_k / n * 100:.1f}%"
              f"  ({ratio:.1f}x the baseline) is the first count that separates")
    if low_k is None:
        print("  improvement: NO count separates -- not even 0 of "
              f"{n}, a perfect result")
    else:
        print(f"  improvement: {low_k}/{n} = {low_k / n * 100:.1f}%"
              f" is the only count below the baseline that separates")

    # The indistinguishable band is open at both ends: low_k and high_k
    # each separate, so the band runs strictly between them. Printing
    # "0 through high_k - 1" is wrong whenever low_k is 0, and it read as
    # a contradiction against the line above it.
    band_lo = 0 if low_k is None else low_k + 1
    band_hi = n if high_k is None else high_k - 1
    print()
    print(f"So every outcome from {band_lo} through {band_hi} reads"
          f" identically at this n.")
    print("The rate is reportable. A comparison of rates across builds is not.")


if __name__ == "__main__":
    main()
