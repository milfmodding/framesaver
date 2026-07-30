"""Does the LateUpdate remainder track AWAKE, or just track a busy frame that has more bots?

First pass gave rho(remainder, awake) = +0.443 in raid 1, which is not zero and not far off the
animator's +0.681. So "the remainder is not bot work" was not established. But awake also tracks
frame time (+0.518), and a busier moment has more of everything - so a raw correlation cannot
separate "the remainder is awake-bot work" from "awake and the remainder are both downstream of
a busy frame".

Two reads that can:

  1. rho(remainder SHARE of frame, awake). Dividing by frame time removes the common busyness
     term. If the remainder is genuinely awake-scaled, its SHARE rises as bots wake. If it is
     scene/UI/player work, the share is flat or falls while awake work crowds it out.
     The animator is the positive control: its share MUST rise with awake, or the test cannot
     detect scaling at all and a null here would mean nothing.

  2. The magnitude. A correlation says direction, not price. Split each leg at its median awake
     and difference the remainder. That is the number that decides whether anything is here, and
     a rank correlation cannot supply it.

Within-raid, because between-leg contrasts are not an instrument for effects this size - the
established floor is 0.259 ms pooled.

POPULATION, and why this file runs FOUR of them. The first version of this script invented its own
steady-state filter (in-raid, not final, roster non-empty) and applied NO warm-up cut, while
Gamma's readers cut at raidElapsed >= 120 s. That is how we came to quote the same remainder as
0.679 and 0.726 ms. Gamma has since put the definition in `steady.py` and made `bots.total > 0` an
explicit option rather than an unwritten habit - correct for per-bot quantities, wrong for
per-frame ones, and the remainder is per-frame.

Rather than pick the population that suits the conclusion, this runs the 2x2 (warm-up cut on/off
x roster gate on/off) and prints all four. If awake-invariance holds across all four, the flag
choice is irrelevant TO THIS CONCLUSION and saying so is worth more than defending one filter. If
it holds in only some, the conclusion was a population artefact and needs to be withdrawn.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import steady  # noqa: E402

LOG = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
LEGS = [("raid 1  ", "framesaver-20260729-185430-raid1-lighthouse"),
        ("raid 1.5", "framesaver-20260729-215652-raid15-forceallroles")]

LATE = "PreLateUpdate/ScriptRunBehaviourLateUpdate"
ANIM = "PreLateUpdate/DirectorUpdateAnimationBegin"


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return float("nan")
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def rank(xs):
    """Average ranks, so ties on the awake ladder do not invent an ordering."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = 0.5 * (i + j) + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(xs, ys):
    n = len(xs)
    if n < 4:
        return float("nan")
    a, b = rank(xs), rank(ys)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = sum((v - ma) ** 2 for v in a) ** 0.5
    db = sum((v - mb) ** 2 for v in b) ** 0.5
    return num / (da * db) if da and db else float("nan")


def read(tag):
    """Every sample line, unfiltered. steady.py owns the population, not this reader."""
    out = []
    for ln in open(os.path.join(LOG, tag + ".ndjson"), encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def measure(rows):
    """Field-presence gate only. Population was already decided upstream."""
    got = []
    for o in rows:
        ph = o.get("phases") or {}
        late = (ph.get(LATE) or {}).get("avg")
        anim = (ph.get(ANIM) or {}).get("avg")
        pl = (o.get("playerLate") or {}).get("avg")
        fr = (o.get("frame") or {}).get("avg")
        awake = (o.get("bots") or {}).get("awake")
        if None in (late, pl, fr, anim, awake) or not fr:
            continue
        got.append(dict(rem=late - pl, anim=anim, fr=fr, awake=awake, late=late, pl=pl,
                        remShare=(late - pl) / fr, animShare=anim / fr))
    return got


for label, tag in LEGS:
    if not os.path.isfile(os.path.join(LOG, tag + ".ndjson")):
        print("skip %s: no ndjson\n" % label)
        continue
    raw = read(tag)
    print("=" * 78)
    print("%s   %d lines in file" % (label, len(raw)))
    print("=" * 78)

    for warm in (steady.WARMUP_S, 0.0):
        for pop in (False, True):
            kept, dropped = steady.partition(raw, warmup_s=warm, require_population=pop)
            rows = measure(kept)
            head = "  [%s]" % steady.describe(warmup_s=warm, require_population=pop)
            if len(rows) < 4:
                print("%s\n      only %d windows carry the fields - cannot answer" % (head, len(rows)))
                continue
            aw = [r["awake"] for r in rows]
            med = median(aw)
            lo = [r for r in rows if r["awake"] <= med]
            hi = [r for r in rows if r["awake"] > med]
            print("%s" % head)
            print("      %d windows (dropped %s)"
                  % (len(rows), ", ".join("%s %d" % (k, v) for k, v in dropped.items() if v)))
            print("      LateUpdate %.3f  playerLate %.3f  REMAINDER %.3f  frame %.3f  anim %.3f"
                  % (median([r["late"] for r in rows]), median([r["pl"] for r in rows]),
                     median([r["rem"] for r in rows]), median([r["fr"] for r in rows]),
                     median([r["anim"] for r in rows])))
            print("      awake %d..%d (median %g)" % (min(aw), max(aw), med))
            print("      rho(remainder SHARE, awake) %+.3f    rho(animator SHARE, awake) %+.3f  <-ctl"
                  % (spearman([r["remShare"] for r in rows], aw),
                     spearman([r["animShare"] for r in rows], aw)))
            if not hi:
                print("      no window above median awake - this population cannot price it")
                continue
            d_aw = median([r["awake"] for r in hi]) - median([r["awake"] for r in lo])
            d_rem = median([r["rem"] for r in hi]) - median([r["rem"] for r in lo])
            d_anim = median([r["anim"] for r in hi]) - median([r["anim"] for r in lo])
            per_rem = d_rem / d_aw if d_aw else float("nan")
            per_anim = d_anim / d_aw if d_aw else float("nan")
            print("      split %d lo / %d hi, %g bots apart:"
                  " remainder %+.4f ms/bot   animator %+.4f ms/bot   ratio %.1f%%"
                  % (len(lo), len(hi), d_aw, per_rem, per_anim,
                     100.0 * per_rem / per_anim if per_anim else float("nan")))
    print()
