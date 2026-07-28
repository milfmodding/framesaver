"""Detectable effect for the arm comparisons, and the discrete fact it turns on.

Three of us derived this independently and disagreed by up to 2.3x, which is too
large to be a convention. So this file leads with the **critical region** — the
integer the exact test actually turns on — because that can be checked by hand and
settles the disagreement without anyone trusting anyone's code.

    Alpha  6.43x for 2min x6      Beta  5.74x      Gamma  2.5x

**Gamma's figure is not attainable and the critical region shows why in one line.**
At 2min x6 the control arm expects 13.2 events and the total expects 18; a
two-sided exact test of p=0.5 at 18 trials rejects only at k >= 14. So at R = 2.5
the *expected* outcome does not reject — power is below 50%, and 80% is therefore
impossible at that ratio. Alpha's and Beta's figures agree within 10% and put the
80% point near 5.7x-6.4x, which is consistent with the expected count clearing the
bar around R = 3.5 (roughly the 50% point).

The general reading, worth more than any single number here: **rejecting at the
expected outcome is about 50% power, not 80%.** A design whose expected counts
merely clear the critical value is a coin flip, not a test.

TWO REAL ERRORS FOUND WHILE RECONCILING, both worth keeping:

  * **The ABA design is not balanced.** Control is B1+B3, twice the treatment
    exposure. Alpha's table averaged it to 7-versus-7 and overstated it; the true
    allocation is 10 control windows against 5.
  * **An unbalanced allocation must be tested against p0 = W1/(W1+W2), not 0.5.**
    Beta's first pass returned 1.69x for the unbalanced ABA — better than any
    balanced design, which is impossible on its face and is how they caught it.
    Same denominator family as everything else today: the null has to describe the
    design, not the ideal.

RESOLVED. Gamma found their own bug: the simulation generated the treatment arm as
`lambda * r` instead of `lambda / r` — inflated rather than depleted. Slicing is
meant to *reduce* stutter, so under H1 the treatment arm is the depleted one and
`T` shrinks; crediting it with events the hypothesis does not produce is the same
error as holding `T` at its null value, reached from the other side. Corrected,
their figures land on this file's exactly at 9 and 12 windows per arm.

Their note on how it went wrong is the part worth keeping: they had a hypothesis
that explained the 1.4x gap — halved sample gives sqrt(2) — and the arithmetic was
consistent with it, so they stopped. **A consistent explanation is not a confirmed
one.** Reproducing the other figure would have taken a minute and would have shown
the diagnosis was wrong before it was sent.

TWO FIGURES, BOTH CORRECT, DIFFERENT QUANTITIES. Do not quote one as the other:

  * **Design figures** — what this file prints — average over a random `T` that H1
    itself shrinks. 6 windows/arm gives 6.43x. **Use this to choose an arm length
    before the raid.**
  * **Post-hoc figures** condition on the realized total. At an observed `T = 18`
    that reads about 4.7x. **Use this for "what could this raid have seen",** and
    it is what `read-slicing-raid.py` prints beside the critical count.

Quoting the post-hoc number as the design requirement understates what the design
needed, which is the direction that turns an underpowered null into a finding.

SELF-CHECK, and it needs no second implementation: at the reported ratio, if
`E[control] < k_crit` then the figure is wrong, because the expected outcome not
rejecting caps power below 50%. Asserted below on every row. It would have caught
Gamma's bug and it would have caught mine had it gone the other way.
"""
import sys
from math import comb, exp, lgamma, log

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

RATE = 2.2          # period >= 100 ms events per 60 s held window, Streets
ALPHA = 0.05


def binom_pmf(k, n, p):
    return comb(n, k) * p ** k * (1.0 - p) ** (n - k)


def reject(k, n, p0):
    """Exact two-sided test of p == p0, by likelihood ordering."""
    if n == 0:
        return False
    obs = binom_pmf(k, n, p0)
    tail = sum(binom_pmf(i, n, p0) for i in range(n + 1)
               if binom_pmf(i, n, p0) <= obs * (1.0 + 1e-9))
    return tail <= ALPHA


def critical(n, p0=0.5):
    """Smallest control count at or above which the test rejects."""
    for k in range(int(n * p0) + 1, n + 1):
        if reject(k, n, p0):
            return k
    return None


def pois_pmf(k, lam):
    if lam <= 0.0:
        return 1.0 if k == 0 else 0.0
    return exp(k * log(lam) - lam - lgamma(k + 1))


def power(w_ctrl, w_trt, ratio):
    """Averaged over the joint Poisson variation in both arms, not evaluated at
    the mean -- at these totals the difference is not negligible."""
    lam_c = RATE * w_ctrl
    lam_t = RATE * w_trt / ratio
    p0 = float(w_ctrl) / (w_ctrl + w_trt)
    total = 0.0
    for nc in range(0, int(lam_c * 4.0) + 30):
        pc = pois_pmf(nc, lam_c)
        if pc < 1e-13:
            continue
        for nt in range(0, int(lam_t * 4.0) + 30):
            pr = pc * pois_pmf(nt, lam_t)
            if pr < 1e-13:
                continue
            if reject(nc, nc + nt, p0):
                total += pr
    return total


def detectable(w_ctrl, w_trt, target=0.80):
    lo, hi = 1.01, 14.0
    for _ in range(44):
        mid = (lo + hi) / 2.0
        if power(w_ctrl, w_trt, mid) >= target:
            hi = mid
        else:
            lo = mid
    return hi


def main():
    print('period >= 100 ms at %.1f events per held window, exact two-sided '
          'test, alpha %.2f\n' % (RATE, ALPHA))

    print('THE CRITICAL REGION -- check this by hand before believing any figure '
          'below.')
    print('%-8s %-16s %s' % ('total T', 'reject if k >=', 'share that needs'))
    for t in (12, 16, 18, 20, 24, 28, 30, 40):
        k = critical(t)
        print('%-8d %-16d %.1f%%' % (t, k, 100.0 * k / t))

    print('\nDESIGNS. w_ctrl/w_trt are windows per condition.\n')
    print('%-32s %-6s %-6s %-9s %-9s   %s'
          % ('design', 'ctrl', 'trt', 'ev/ctrl', 'null p0', 'detectable at 80%'))
    designs = [
        ('interleave 2 min x6', 6, 6),
        ('interleave 3 min x6 [INSTALLED]', 9, 9),
        ('interleave 4 min x6', 12, 12),
        ('interleave 2 min x8', 8, 8),
        ('old ABA 5 min x3, real 10v5', 10, 5),
    ]
    failures = []
    for label, wc, wt in designs:
        p0 = float(wc) / (wc + wt)
        r = detectable(wc, wt)
        # The self-check, on every row. At the reported ratio the expected control
        # count must reach the critical value, or the expected outcome does not
        # reject and power is capped below 50% -- so the figure cannot be an 80%
        # detectable effect. This is cheap and it catches the whole family of
        # H1-direction errors without a second implementation to disagree with.
        ec = RATE * wc
        t = int(round(ec + RATE * wt / r))
        k = critical(t, p0)
        flag = ''
        if k is None or ec < k:
            flag = '   <-- SELF-CHECK FAILED (E[ctrl] %.1f < k %s)' % (ec, k)
            failures.append(label)
        print('%-32s %-6d %-6d %-9.1f %-9.3f   %.2fx%s'
              % (label, wc, wt, ec, p0, r, flag))
    if failures:
        print('\n%d row(s) failed the self-check and must not be quoted: %s'
              % (len(failures), ', '.join(failures)))
    else:
        print('\nself-check passed on every row: at each reported ratio the '
              'expected control count reaches the critical value.')

    print('\nWhat "rejecting at the expected outcome" buys, which is about 50% '
          'and not 80%:')
    print('%-26s %-8s %-8s %-8s %s'
          % ('design at R', 'E[ctrl]', 'E[T]', 'k >=', 'expected outcome rejects?'))
    for label, wc, wt in designs[:3]:
        for r in (2.0, 2.5, 3.5, 5.0):
            ec = RATE * wc
            et = RATE * wt / r
            t = int(round(ec + et))
            k = critical(t, float(wc) / (wc + wt))
            print('%-26s %-8.1f %-8d %-8d %s'
                  % ('%s R=%.1f' % (label.split(' [')[0], r), ec, t, k,
                     'yes' if ec >= k else 'NO'))
        print()


main()
