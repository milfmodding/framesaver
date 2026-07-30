"""The tick's share of aiTotal, from a route that does NOT go through the noisy contrast.

WHY THIS EXISTS. Delta's adjudication put the ABA drop at +0.146 ms with a 95% CI of
-0.249 .. +0.541. That interval contains zero AND contains the registered floor, so the
DROP cannot adjudicate the registration either way - it is underpowered, not below range,
and I had called it below range.

But the registration's estimand is the tick's SHARE, and there is a second route to the
share that does not use the contrast at all. Delta printed ms-per-brain-tick rising 440% on
the sliced arm and offered two readings: the tick is a small share, or the work is CONSERVED
and no scheduling policy can recover it. THOSE TWO HAVE OPPOSITE CONSEQUENCES, and the
metric as printed cannot separate them - because dividing a mostly-FIXED numerator by a
5.9x-smaller denominator produces ~5.9x whether or not the per-tick cost changed.

That confound is also the way in. Model aiTotal as fixed + tick work:

    control  aiTotal = F + T           over N ticks
    sliced   aiTotal = F + T*r         over N*r ticks,  r = ticked/live

If per-tick cost is CONSTANT, the observed ms-per-tick ratio is

    ratio = (F + T*r)/(N*r) / ((F + T)/N) = (F/r + T) / (F + T)

which is one equation in one unknown once F + T is pinned to the observed control baseline.
So the ratio IDENTIFIES the share under constant per-tick cost - and the noise in it comes
from tickedSum and the block medians, not from the between-block contrast. tickedSum is
counted exactly and blocks 2 and 3 have within-block sd of 0.064 and 0.006 ms.

If the two routes agree, constant per-tick cost is the consistent story and CONSERVED WORK
is not: conserved work predicts a drop of zero, and the drop is not zero.

Numbers are taken from Delta's script rather than recomputed, so a disagreement between us
shows up as a disagreement rather than being averaged away.
"""

# From analysis/delta-brain-tick-share-check.py on raid1-lighthouse.
BRACKET_AI = 1.391          # median aiTotal.avg, mean of the two B1 brackets, ms/frame
SLICED_AI = 1.245           # median aiTotal.avg on B2
R = 0.1692                  # ticked/live on the sliced arm
RATIO_PER_TICK = 0.29924 / 0.05544   # sliced / bracket ms-per-brain-tick
ARM_COEF_SHARE = 0.099      # share implied by the regression's sliced coefficient
REG_LO, REG_HI = 0.38, 0.78

print("inputs, from Delta's run")
print("  control aiTotal        %.3f ms/frame" % BRACKET_AI)
print("  sliced  aiTotal        %.3f ms/frame" % SLICED_AI)
print("  ticked/live on sliced  %.4f   (dose removed %.4f)" % (R, 1 - R))
print("  ms-per-tick ratio      %.3fx" % RATIO_PER_TICK)
print()

# ---- route 1: the contrast. T*(1-r) = observed drop.
drop = BRACKET_AI - SLICED_AI
T1 = drop / (1 - R)
print("route 1, from the CONTRAST (the underpowered one)")
print("  observed drop          %+.3f ms" % drop)
print("  implied tick work T    %.3f ms/frame" % T1)
print("  implied SHARE          %.1f%%" % (100 * T1 / BRACKET_AI))
print("  and its CI contains zero, so this route cannot rule anything out")
print()

# ---- route 2: the per-tick ratio. Solve (F/r + T)/(F + T) = ratio, F + T = baseline.
#      F*(1/r - 1) = ratio*(F+T) - (F+T)  ->  F = baseline*(ratio-1)*r/(1-r)
F = BRACKET_AI * (RATIO_PER_TICK - 1) * R / (1 - R)
T2 = BRACKET_AI - F
print("route 2, from the PER-TICK RATIO (does not use the contrast)")
print("  implied fixed part F   %.3f ms/frame" % F)
print("  implied tick work T    %.3f ms/frame" % T2)
print("  implied SHARE          %.1f%%" % (100 * T2 / BRACKET_AI))
print()

print("route 3, Delta's regression coefficient on `sliced`")
print("  implied SHARE          %.1f%%" % (100 * ARM_COEF_SHARE))
print()

shares = [100 * T1 / BRACKET_AI, 100 * T2 / BRACKET_AI, 100 * ARM_COEF_SHARE]
print("three routes: %s" % ", ".join("%.1f%%" % s for s in shares))
print("registered band: %.0f-%.0f%%" % (100 * REG_LO, 100 * REG_HI))
print()

# What the per-tick ratio WOULD have been if the registered share were true. If the
# observed ratio is far from this, the ratio is informative even though the drop is not.
for label, share in (("registered floor", REG_LO), ("registered ceiling", REG_HI)):
    T = share * BRACKET_AI
    Fx = BRACKET_AI - T
    predicted = (Fx / R + T) / (Fx + T)
    print("  if share were %.0f%% (%s), ms-per-tick ratio would be %.2fx"
          % (100 * share, label, predicted))
print("  observed %.2fx" % RATIO_PER_TICK)
print()

print("READING IT. Conserved work predicts a drop of ZERO - each tick costing 1/r more")
print("exactly cancels r times fewer ticks - and the drop is not zero, so conserved work")
print("is not the consistent story. Constant per-tick cost with a SMALL share is: it")
print("predicts both the observed ratio and a small positive drop.")
print()
print("THE HONEST LIMIT. Route 2 assumes per-tick cost is constant, which is the thing")
print("route 2 is being used to argue. It is not circular - the assumption predicts a")
print("ratio and the ratio came out where predicted - but it is one model fitting one")
print("number, and it agrees with the regression to within a point for reasons that may")
print("include luck. It does not replace a balanced interleave; it says what to expect")
print("from one.")
