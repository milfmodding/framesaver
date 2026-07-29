#!/usr/bin/env python3
"""Read the brain-slicing raid against what was registered, in the registered order.

Written BEFORE the raid ran. That is the whole point: every choice in here --
which lines are excluded, which arm pools with which, what counts as the gate
failing -- was made without knowing the answer. Written afterwards, each of
those is a choice the outcome influenced.

Order matters. Checks 1-3 decide whether the primary is quotable at all, so the
primary is not printed until they pass. A number that survives a gate it never
faced is not a result.

Usage:  python read-slicing-raid.py <log.ndjson>

Run analysis/check-boundary-latch.py FIRST. Exit 2 there is not a pass.
"""

import json
import statistics
import sys
from math import comb

PRIMARY_MS = 100      # registered primary; near-Poisson (1.2x overdispersion)
DESCRIPTIVE_MS = 30   # registered DESCRIPTIVE ONLY -- no significance test
CONTROL_ARM = "B1"
TEST_ARM = "B2"


def load(path):
    """Sample windows and spike lines, split by the protocol arm stamped on them."""
    windows, spikes, cur = [], {}, None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "spike":
                cur = d.get("window", cur)
                spikes.setdefault(cur, []).append(d)
            elif d.get("type") == "sample":
                windows.append(d)
    return windows, spikes


def arm_of(w):
    p = w.get("protocol") or {}
    return p.get("arm")


def eligible(w):
    """In-raid, whole, and not the window a keypress cut short.

    flushedByProtocol lines are excluded for a reason stronger than being
    short: Advance() applies the step's config before the flush, so the
    labels name the arm about to START while the sums describe the arm that
    just ENDED. `slicing` is wrong on exactly those lines.
    """
    return (w.get("state") == "raid"
            and not w.get("flushedByProtocol")
            and not w.get("final"))


def count_at(spikes, window, threshold):
    return sum(1 for s in spikes.get(window, [])
               if (s.get("period") or 0) >= threshold)


def binom_two_sided(k, a):
    """Exact conditional binomial: P(|X - k/2| >= |a - k/2|) under p = 1/2."""
    if k == 0:
        return float("nan")
    d = abs(a - k / 2.0)
    tot = 2.0 ** k
    return sum(comb(k, x) for x in range(k + 1)
               if abs(x - k / 2.0) >= d - 1e-9) / tot


def _crit_c(k):
    """Largest c with two-sided P(X<=c) <= 0.05 under p = 1/2; -1 if none."""
    cum, c_ret = 0.0, -1
    for c in range(k + 1):
        cum += comb(k, c) / 2.0 ** k
        if 2 * cum <= 0.05:
            c_ret = c
        else:
            break
    return c_ret


def detectable_ratio(k):
    """Smallest true ratio this k can call at 80% power, two-sided a=0.05."""
    if k < 4:
        return None
    cum, crit = 0.0, -1
    for c in range(k + 1):
        cum += comb(k, c) / 2.0 ** k
        if 2 * cum > 0.05:
            crit = c - 1
            break
    if crit < 0:
        return None
    for step in range(21, 401):
        r = step / 20.0
        p = 1.0 / (1.0 + r)
        power = sum(comb(k, x) * p ** x * (1 - p) ** (k - x)
                    for x in list(range(crit + 1)) + list(range(k - crit, k + 1)))
        if power >= 0.80:
            return r
    return None


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    windows, spikes = load(argv[1])
    keep = [w for w in windows if eligible(w)]
    print(f"{argv[1]}\n{len(windows)} sample windows, {len(keep)} eligible "
          f"(in-raid, whole, not protocol-flushed)\n")

    fail = []

    # 1. Did the protocol parse the file that was actually on disk?
    steps = {(w.get("protocol") or {}).get("steps") for w in keep}
    steps.discard(None)
    print(f"1. protocol.steps      {steps or 'ABSENT'}  (expect {{7}})")
    if steps != {7}:
        fail.append("protocol did not parse as 7 steps -- arms are not what was registered")

    # 2. Did the lever engage? This is the check the whole raid rests on: with
    #    BigBrain present and deferral on, the arm reads as applied and the
    #    behaviour is vanilla, and the null reads as "the lever does nothing".
    bad = []
    for w in keep:
        arm, sl = arm_of(w), (w.get("agents") or {}).get("slicing")
        if arm == TEST_ARM and sl is not True:
            bad.append((w.get("window"), arm, sl))
        if arm == CONTROL_ARM and sl is not False:
            bad.append((w.get("window"), arm, sl))
    # An empty `bad` is only a pass if something was actually tested. On a log
    # with no arm labels every branch above is skipped and this reported OK --
    # a check that cannot fail is not a check, and it read as the strongest
    # possible confirmation of the thing the raid rests on.
    tested = sum(1 for w in keep if arm_of(w) in (CONTROL_ARM, TEST_ARM))
    verdict = "OK" if not bad else f"{len(bad)} MISMATCHED {bad[:4]}"
    print(f"2. slicing matches arm {verdict}  ({tested} windows tested)")
    if not tested:
        fail.append("no window carries a B1/B2 arm label -- check 2 tested nothing")
    if bad:
        fail.append("agents.slicing disagrees with the arm label -- the lever did not do what the label says")

    # 3. Drift gate. The control blocks are separated in time by everything
    #    the test arm did; if they disagree with each other, time is a larger
    #    effect than the knob and no arm comparison in this raid is readable.
    ctrl = [w for w in keep if arm_of(w) == CONTROL_ARM]
    test = [w for w in keep if arm_of(w) == TEST_ARM]
    blocks = []
    for w in ctrl:
        step = (w.get("protocol") or {}).get("step")
        blocks.append((step, count_at(spikes, w.get("window"), PRIMARY_MS)))
    by_block = {}
    for step, c in blocks:
        by_block.setdefault(step, []).append(c)
    sums = {s: sum(v) for s, v in sorted(by_block.items())}
    print(f"3. control blocks      {sums}")
    if len(sums) < 2:
        fail.append(f"fewer than 2 control blocks ({len(sums)}) -- drift is untested, "
                    "not absent")
    else:
        lo, hi = min(sums.values()), max(sums.values())
        spread = hi / lo if lo else float("inf")
        print(f"   spread {spread:.2f}x across control blocks")
        if spread > 2.0:
            fail.append(f"control blocks differ by {spread:.2f}x -- drift dominates, raid unreadable")

    if fail:
        print("\nGATE FAILED -- the primary is NOT quotable:")
        for f in fail:
            print(f"  ! {f}")
        print("\nRefusing to print the primary comparison.")
        return 1

    # 4. Primary. Stated detectable effect BEFORE the p-value, so a null is
    #    read as "this raid could not have seen it" rather than "no effect".
    a = sum(count_at(spikes, w.get("window"), PRIMARY_MS) for w in ctrl)
    b = sum(count_at(spikes, w.get("window"), PRIMARY_MS) for w in test)
    k = a + b
    det = detectable_ratio(k)
    print(f"\n4. PRIMARY  period >= {PRIMARY_MS} ms, pooled per arm")
    print(f"   {CONTROL_ARM} {a} events / {len(ctrl)} windows      "
          f"{TEST_ARM} {b} events / {len(test)} windows")
    # Print the critical region next to the effect, because a power figure with
    # no critical count cannot be sanity-checked by the person reading it.
    #
    # Alpha's self-check, earned the hard way: REJECTING AT THE EXPECTED OUTCOME
    # IS ABOUT 50% POWER, NOT 80%. If the expected control count under the
    # reported ratio does not clear `k_crit`, the figure is wrong. My own
    # simulation reported 2.5x where the expected outcome could not reject,
    # because it generated the treatment arm inflated rather than depleted --
    # slicing is meant to REDUCE stutter, so under H1 the total shrinks, and
    # holding it at its null value credits the design with events H1 never
    # produces.
    crit_k = k - _crit_c(k)
    print(f"   rejects only at {CONTROL_ARM} >= {crit_k} of {k} "
          f"({100.0 * crit_k / k:.1f}% share)" if k else "")
    print(f"   this raid can detect {det if det else '>20'}x at 80% power")
    if det:
        exp_ctrl = k * (det / (1.0 + det))
        if exp_ctrl < crit_k:
            print(f"   ! SELF-CHECK FAILED: expected {CONTROL_ARM} {exp_ctrl:.1f} "
                  f"< critical {crit_k} -- the power figure above is wrong")
    print(f"   exact conditional binomial p = {binom_two_sided(k, a):.4f}")
    if det and det > 2.0:
        print(f"   NOTE: underpowered. A null here excludes only changes above {det:.1f}x.")

    # 5. Descriptive only. Overdispersed 454x with rho=+0.71 against window
    #    order -- it drifts within a raid at constant config, so it gets no test.
    da = sum(count_at(spikes, w.get("window"), DESCRIPTIVE_MS) for w in ctrl)
    db = sum(count_at(spikes, w.get("window"), DESCRIPTIVE_MS) for w in test)
    print(f"\n5. DESCRIPTIVE  period >= {DESCRIPTIVE_MS} ms  "
          f"{CONTROL_ARM} {da}   {TEST_ARM} {db}   -- no test, by registration")

    # 6. Arm 2 is not one condition: at ~23 agents the computed per-frame count
    #    equals the floor of 4, so the roster moving 14-29 puts some windows
    #    floor-bound and some slicing-bound. Registered split, not a post-hoc cut.
    print(f"\n6. {TEST_ARM} stratification by tickedSum/liveSum")
    for w in test:
        ag = w.get("agents") or {}
        ts, ls = ag.get("tickedSum"), ag.get("liveSum")
        if ts is None or ls is None or not ls:
            continue
        frac = ts / ls
        n = w.get("n") or 1
        print(f"   window {w.get('window'):>3}  ticked/live {frac:5.3f}  "
              f"per-frame {ts / n:5.2f}  "
              f"{'FLOOR-BOUND' if ts / n <= 4.05 else 'slicing-bound'}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
