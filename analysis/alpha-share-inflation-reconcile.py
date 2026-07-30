"""Reconcile the contrast share (12.6%) with the min-channel bound (37.2%).

DELTA ESTABLISHED TWO THINGS THAT DO NOT SIT TOGETHER UNTIL ONE MORE STEP IS TAKEN.

  1. Routes 1-3 are all the contrast, and it returns a share of 12.6%.
  2. aiTotal.min bounds the fixed component one-way, giving share >= 37.2%.
  3. Per-tick cost inflates >= 3x for EVERY admissible F, so constant per-tick cost is
     rejected without needing to know F. About half the deferred work comes back.

Delta says 12.6% and 37.2% "are honest and not in conflict". That is right, and the reason
is worth making explicit, because it is the same fact as (3):

    THE CONTRAST ESTIMATOR ASSUMES CONSTANT PER-TICK COST, WHICH (3) REJECTS.

Route 1 is s = (ai_c - ai_s) / (ai_c * (1 - r)). That denominator is the fraction of tick
work removed, and it is only 1 - r if each surviving tick costs what it used to. If the
surviving ticks inflate by k, the work removed is 1 - r*k, not 1 - r, so

    s = drop / (B * (1 - r*k))

and every contrast-based share is biased LOW by exactly the factor (1 - r*k)/(1 - r).

So the three contrast routes and the min channel are not two answers to one question. They
are one biased answer and one bound, and (3) supplies the correction factor that maps
between them. This script applies it and reports whether the corrected contrast reaches the
min channel's floor.

CONSEQUENCE I HAVE TO ACT ON RATHER THAN NOTE: the share <= 47% upper bound I derived from
the contrast's upper CI - and wrote into protocol-brain-slice-lighthouse-v2.ini as an
established result - inherits the same bias. It is not an upper bound on the share once
constant per-tick cost is rejected. The v2 header has to be corrected.
"""

B = 1.391          # control aiTotal.avg, ms/frame (Delta, block medians)
AI_S = 1.245       # sliced aiTotal.avg
R = 0.1692         # ticked/live on the sliced arm
DROP = B - AI_S
CI_HI = 0.541      # upper 95% bound on the drop
MIN_FLOOR = 0.372  # Delta route 4, one-way lower bound on the share

# Delta's inflation table: per-tick cost ratio after subtracting a candidate F.
INFLATION = [(0.000, 4.76), (0.500, 4.27), (0.876, 3.29)]

print("contrast share, as computed by routes 1-3 (constant per-tick cost assumed)")
s_naive = DROP / (B * (1 - R))
print("  drop %.3f ms  ->  share %.1f%%" % (DROP, 100 * s_naive))
print("  same estimator on the upper CI %.3f  ->  %.1f%%" % (CI_HI, 100 * CI_HI / (B * (1 - R))))
print()

print("corrected for inflation: work removed is 1 - r*k, not 1 - r")
print("     k     1-r*k    share from drop   share from upper CI   reaches %.1f%% floor?"
      % (100 * MIN_FLOOR))
for f, k in INFLATION:
    removed = 1 - R * k
    if removed <= 0:
        print("  %5.2f   %+.3f   -- r*k >= 1: the model says MORE work after slicing than "
              "before, which is not admissible" % (k, removed))
        continue
    s = DROP / (B * removed)
    s_hi = CI_HI / (B * removed)
    print("  %5.2f   %.3f    %11.1f%%      %14.1f%%          %s"
          % (k, removed, 100 * s, 100 * s_hi,
             "yes" if s_hi >= MIN_FLOOR else "only via the CI" if s_hi >= MIN_FLOOR else "no"))
print()

# What inflation would be needed for the corrected point estimate to MEET the floor?
# s = drop/(B(1-rk)) = floor  ->  1-rk = drop/(B*floor)  ->  k = (1 - drop/(B*floor))/r
k_needed = (1 - DROP / (B * MIN_FLOOR)) / R
print("inflation needed for the contrast POINT estimate to meet the %.1f%% floor: k = %.2f"
      % (100 * MIN_FLOOR, k_needed))
print("  Delta's admissible range is k = 3.29 to 4.76, so the required value is %s that range"
      % ("inside" if 3.29 <= k_needed <= 4.76 else "outside"))
print()

print("THE UPPER BOUND I HAVE TO WITHDRAW")
print("  share <= 47%% came from CI_HI / (B * (1 - r)) = %.1f%%, which assumes constant"
      % (100 * CI_HI / (B * (1 - R))))
print("  per-tick cost. At k = 3.29 the same CI gives %.1f%%, and at k = 4.27 it gives"
      % (100 * CI_HI / (B * (1 - R * 3.29))))
print("  %.1f%%. So it is not an upper bound on the share at all - it is an upper bound"
      % (100 * CI_HI / (B * (1 - R * 4.27))))
print("  on the SAVING, which is the quantity that was robust all along.")
print()
print("WHAT SURVIVES UNCHANGED: the saving. drop %.3f ms, upper 95%% %.3f ms, CI contains"
      % (DROP, CI_HI))
print("zero. Rule 3's budget is a budget on the SAVING, so it does not move.")
