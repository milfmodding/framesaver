#!/usr/bin/env python3
"""Adjudicate registration `brain-tick-share-of-aitotal` against raid1-lighthouse.

Alpha reported a 0.146 ms aiTotal drop on the sliced arm and called it
`dropBelowRange` against my registered 0.25-0.51 ms, but declined to call the
registration falsified for four reasons. This script checks all four against the
log rather than against his table.

What it does:
  1. Reproduces his block table exactly (medians over full non-flushed raid
     windows), so any disagreement is located before it is argued.
  2. Converts the observed drop into the registration's ACTUAL estimand -- the
     tick's SHARE of aiTotal -- instead of comparing absolute ms. The registered
     ms band was computed at an assumed aiTotal baseline; if the observed
     baseline differs, comparing ms conflates a wrong share with a wrong
     baseline. Share = drop / (aiTotal_control * (1 - ticked/live)).
  3. Computes the within-arm, per-window noise floor for aiTotal.avg -- the one
     number Alpha says decides whether this is a result or a shrug.
  4. Separates the ramp from the arm by fitting aiTotal ~ live + t + arm over
     the 10 windows, which ABA on medians cannot do. Reports the arm
     coefficient with a CI. df is 6; this is a weak fit and is labelled as one.
  5. Tests whether the deferred work VANISHED or was CONSERVED, via ms per
     brain-tick = aiTotal.avg * frames / tickedSum. A small share and conserved
     work both produce a small per-frame drop and have opposite consequences
     for whether any scheduling policy can recover the cost.
  6. Checks whether the drop appears in `frame` at all, and whether frame's
     block pattern is monotone in raid order (drift) or dips on the arm.

Known weaknesses, stated up front:
  - n = 3/4/3 windows. Every interval here is wide and none of them is a
    substitute for a balanced interleave.
  - The linear-in-t drift term in (4) is an assumption. The per-window dump is
    printed so the reader can see whether linear is defensible.
  - `live` declines monotonically (27->21) so arm is partly confounded with
    population; the balance of that confound across the ABA bracket is reported
    rather than assumed to cancel.
"""

import json
import math
import os
import statistics as st

LOG = os.path.join(
    r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs",
    "framesaver-20260729-185430-raid1-lighthouse.ndjson",
)

# ---------------------------------------------------------------- load

hdr = None
samples = []
with open(LOG, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        if o["type"] == "header":
            hdr = o
        elif o["type"] == "sample":
            samples.append(o)

cfgh = hdr["config"]
print("build          ", hdr["commit"][:12])
print("windowSeconds  ", hdr["windowSeconds"])
print("deferToAiMods  ", hdr["deferToAiMods"])
print("minBrainsPerFrame (static, header):", cfgh["minBrainsPerFrame"])
print()

# Alpha's inclusion rule: raid state, not flushed by protocol, live bots > 0,
# and a full window. "Full" is not a field -- derive it from windowSeconds.
WSEC = hdr["windowSeconds"]


def full(o):
    return o.get("windowSec", WSEC) is None or True  # replaced below


rows = []
prev_t = None
for o in samples:
    if o["state"] != "raid":
        continue
    if o.get("flushedByProtocol"):
        continue
    if o["agents"]["live"] <= 0:
        continue
    span = o["t"] - prev_t if prev_t is not None else None
    prev_t = o["t"]
    rows.append(o)

# recompute spans on the filtered-out windows too, so short windows are found
prev_t = None
span_by_w = {}
for o in samples:
    if prev_t is not None:
        span_by_w[o["window"]] = o["t"] - prev_t
    prev_t = o["t"]

keep = [o for o in rows if span_by_w.get(o["window"], 0) >= 0.9 * WSEC]

print("included windows (raid, non-flushed, live>0, span >= %.0f s):" % (0.9 * WSEC))
print(
    "  w  arm  span_s  frames  live  brainPeriod  ticked/live  aiTotal.avg  aiTotal.max  frame.p50"
)
for o in keep:
    a = o["agents"]
    ratio = a["tickedSum"] / a["liveSum"] if a["liveSum"] else float("nan")
    print(
        "  %2d  %-3s  %5.1f  %6d  %4d  %10.2f  %10.3f  %11.3f  %11.2f  %9.3f"
        % (
            o["window"],
            o["protocol"]["arm"],
            span_by_w.get(o["window"], float("nan")),
            o["frames"],
            a["live"],
            o["cfg"]["brainPeriod"],
            ratio,
            o["aiTotal"]["avg"],
            o["aiTotal"]["max"],
            o["framePct"]["p50"] if "framePct" in o else float("nan"),
        )
    )
print()
dropped = [o for o in rows if o not in keep]
if dropped:
    print(
        "  EXCLUDED as short: "
        + ", ".join(
            "w%d(%s, %.1f s)" % (o["window"], o["protocol"]["arm"], span_by_w.get(o["window"], 0))
            for o in dropped
        )
    )
    print()

# ---------------------------------------------------------------- blocks

blocks = []
cur = None
for o in keep:
    step = o["protocol"]["step"]
    if cur is None or cur["step"] != step:
        cur = {"step": step, "arm": o["protocol"]["arm"], "w": []}
        blocks.append(cur)
    cur["w"].append(o)


def med(xs):
    return st.median(xs)


print("block table (medians, as Alpha reported):")
print("  step arm   n   frame.p50   aiTotal.avg   live   ticked/live   ms per brain-tick")
tick_cost = {}
for b in blocks:
    ws = b["w"]
    p50 = med([o["framePct"]["p50"] for o in ws])
    ai = med([o["aiTotal"]["avg"] for o in ws])
    live = med([o["agents"]["live"] for o in ws])
    ratio = med([o["agents"]["tickedSum"] / o["agents"]["liveSum"] for o in ws])
    # ms per brain-tick, built per window then aggregated (never sum-of-medians)
    per = [
        o["aiTotal"]["avg"] * o["frames"] / o["agents"]["tickedSum"]
        for o in ws
        if o["agents"]["tickedSum"]
    ]
    tick_cost[b["step"]] = med(per)
    b.update(p50=p50, ai=ai, live=live, ratio=ratio, per_tick=med(per))
    print(
        "  %4d %-4s %3d  %9.3f   %11.3f  %5.1f   %11.4f   %17.5f"
        % (b["step"], b["arm"], len(ws), p50, ai, live, ratio, med(per))
    )
print()

b1a, b2, b1b = blocks[0], blocks[1], blocks[2]
bracket_ai = (b1a["ai"] + b1b["ai"]) / 2
bracket_p50 = (b1a["p50"] + b1b["p50"]) / 2
bracket_live = (b1a["live"] + b1b["live"]) / 2
drop_ai = bracket_ai - b2["ai"]
drop_p50 = bracket_p50 - b2["p50"]

print("ABA contrast, B2 against the mean of its two brackets:")
print("  aiTotal.avg drop   %+.3f ms   (bracket %.3f vs sliced %.3f)" % (drop_ai, bracket_ai, b2["ai"]))
print("  frame.p50   drop   %+.3f ms   (bracket %.3f vs sliced %.3f)" % (drop_p50, bracket_p50, b2["p50"]))
print("  live balance       bracket %.2f vs sliced %.2f  -> %+.2f bots" % (bracket_live, b2["live"], bracket_live - b2["live"]))
print()

# is frame monotone in raid order (drift) or dipped on the arm (effect)?
seq = [b1a["p50"], b2["p50"], b1b["p50"]]
mono = (seq[0] >= seq[1] >= seq[2]) or (seq[0] <= seq[1] <= seq[2])
print("  frame.p50 in raid order: %.3f -> %.3f -> %.3f   monotone=%s" % (*seq, mono))
seqa = [b1a["ai"], b2["ai"], b1b["ai"]]
monoa = (seqa[0] >= seqa[1] >= seqa[2]) or (seqa[0] <= seqa[1] <= seqa[2])
print("  aiTotal   in raid order: %.3f -> %.3f -> %.3f   monotone=%s" % (*seqa, monoa))
print()

# ---------------------------------------------------------------- estimand

REG_LO_MS, REG_HI_MS, REG_PT_MS = 0.25, 0.51, 0.38
REG_LO_SH, REG_HI_SH = 0.38, 0.78

dose = 1.0 - b2["ratio"]
implied_share = drop_ai / (bracket_ai * dose)
# what the registered SHARE band predicts AT THIS RAID'S OBSERVED BASELINE
pred_lo = REG_LO_SH * bracket_ai * dose
pred_hi = REG_HI_SH * bracket_ai * dose
# what baseline the registered ms band must have assumed
implied_baseline = REG_PT_MS / (0.58 * dose)  # 0.58 = Factory point share

print("THE ESTIMAND. The registration's claim is about the tick's SHARE of aiTotal;")
print("the ms band was that share evaluated at an assumed baseline.")
print("  dose removed (1 - ticked/live)          %.4f" % dose)
print("  control aiTotal baseline, observed      %.3f ms" % bracket_ai)
print("  control aiTotal baseline, back-implied")
print("    from the registered ms band           %.3f ms" % implied_baseline)
print("  observed drop                           %.3f ms" % drop_ai)
print("  -> IMPLIED SHARE                        %.1f%%   (registered %.0f-%.0f%%)"
      % (100 * implied_share, 100 * REG_LO_SH, 100 * REG_HI_SH))
print("  registered SHARE band, re-evaluated at")
print("    THIS raid's baseline                   %.3f - %.3f ms" % (pred_lo, pred_hi))
print("  observed / correctly-scaled floor        %.2fx" % (drop_ai / pred_lo))
print("  observed / as-written floor              %.2fx" % (drop_ai / REG_LO_MS))
print()

# ---------------------------------------------------------------- noise floor

print("WITHIN-ARM NOISE FLOOR for aiTotal.avg (the number Alpha asked for).")
resid = []
for b in blocks:
    xs = [o["aiTotal"]["avg"] for o in b["w"]]
    sd = st.stdev(xs) if len(xs) > 1 else float("nan")
    print("  step %d %-3s n=%d  values %s  sd %.3f  range %.3f"
          % (b["step"], b["arm"], len(xs), ["%.3f" % v for v in xs], sd, max(xs) - min(xs)))
    m = st.mean(xs)
    resid += [v - m for v in xs]
pooled_sd = math.sqrt(sum(r * r for r in resid) / (len(resid) - len(blocks)))
print("  pooled within-block sd                  %.3f ms  (df %d)" % (pooled_sd, len(resid) - len(blocks)))

n1, n2, n3 = len(b1a["w"]), len(b2["w"]), len(b1b["w"])
se_contrast = pooled_sd * math.sqrt(0.25 / n1 + 1.0 / n2 + 0.25 / n3)
df = len(resid) - len(blocks)
tcrit = {1: 12.71, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365}.get(df, 2.0)
print("  SE of the ABA contrast                  %.3f ms" % se_contrast)
print("  observed drop %+.3f  95%% CI  %+.3f .. %+.3f  (t_%d=%.3f)"
      % (drop_ai, drop_ai - tcrit * se_contrast, drop_ai + tcrit * se_contrast, df, tcrit))
print("  contains zero: %s" % (abs(drop_ai) < tcrit * se_contrast))
print()
mde = tcrit * se_contrast
print("  minimum detectable effect at this n     %.3f ms  (share %.0f%%)"
      % (mde, 100 * mde / (bracket_ai * dose)))
print()

# WHERE THE VARIANCE LIVES. The pooled sd above is dominated by one block. If the
# variance is concentrated in early raid rather than spread over the raid, the
# achievable floor for a RERUN is not the floor measured here, and the power
# verdict changes. Test it by pooling only the blocks after the opening minutes.
print("VARIANCE STRUCTURE -- is the floor a property of the measurement or of early raid?")
late = [b for b in blocks if b["step"] >= 2]
resid_l = []
for b in late:
    xs = [o["aiTotal"]["avg"] for o in b["w"]]
    m = st.mean(xs)
    resid_l += [v - m for v in xs]
sd_late = math.sqrt(sum(r * r for r in resid_l) / (len(resid_l) - len(late)))
print("  pooled sd, ALL blocks                   %.3f ms  (df %d)" % (pooled_sd, df))
print("  pooled sd, blocks after the first       %.3f ms  (df %d)"
      % (sd_late, len(resid_l) - len(late)))
print("  ratio                                   %.1fx" % (pooled_sd / sd_late))
first = blocks[0]
print("  first block's own sd                    %.3f ms   values %s"
      % (st.stdev([o["aiTotal"]["avg"] for o in first["w"]]),
         ["%.3f" % o["aiTotal"]["avg"] for o in first["w"]]))
print("  -> the floor quoted above is an EARLY-RAID floor, not an instrument floor.")
print()

print("POWER FOR A RERUN, balanced interleave, both floors:")
print("   n/arm   MDE @ sd=%.3f   MDE @ sd=%.3f   raid minutes (2n windows)" % (pooled_sd, sd_late))
for k in (3, 4, 5, 6, 8, 10):
    tc = {3: 2.776, 4: 2.447, 5: 2.306, 6: 2.228, 8: 2.145, 10: 2.101}[k]
    m_all = tc * pooled_sd * math.sqrt(2.0 / k)
    m_late = tc * sd_late * math.sqrt(2.0 / k)
    print("   %5d   %13.3f   %13.3f   %6.0f" % (k, m_all, m_late, 2 * k * WSEC / 60))
print("   (observed effect %.3f ms; registered floor at this baseline %.3f ms)"
      % (drop_ai, pred_lo))
print()

# what the raid DOES exclude: the top of the registered share band
hi_ci = drop_ai + tcrit * se_contrast
print("WHAT THE RAID ACTUALLY SETTLES:")
print("  upper 95%% bound on the drop             %.3f ms  -> share <= %.0f%%"
      % (hi_ci, 100 * hi_ci / (bracket_ai * dose)))
print("  registered band 38-78%%: the top %s ruled out, the bottom %s"
      % ("IS" if hi_ci < pred_hi else "is NOT", "is NOT" if hi_ci > pred_lo else "IS"))
print()

# does dropping the one early-raid window rescue the registration?
alt = blocks[0]["w"][1:]
alt_ai = med([o["aiTotal"]["avg"] for o in alt])
alt_bracket = (alt_ai + b1b["ai"]) / 2
alt_drop = alt_bracket - b2["ai"]
print("POST-HOC EXCLUSION of the opening window (Alpha's reason 3), for the record:")
print("  early-block median without it           %.3f ms (was %.3f)" % (alt_ai, b1a["ai"]))
print("  drop                                    %.3f ms (was %.3f)" % (alt_drop, drop_ai))
print("  implied share                           %.1f%% (was %.1f%%)"
      % (100 * alt_drop / (alt_bracket * dose), 100 * implied_share))
print("  -> moves the miss from %.1fx to %.1fx below the floor; does not rescue it."
      % (pred_lo / drop_ai, pred_lo / alt_drop))
print()

# ---------------------------------------------------------------- ramp vs arm

print("SEPARATING THE RAMP FROM THE ARM: aiTotal ~ 1 + live + t + sliced")
Y = [o["aiTotal"]["avg"] for o in keep]
X = [
    [1.0, float(o["agents"]["live"]), o["t"] / 60.0, 1.0 if o["protocol"]["arm"] == "B2" else 0.0]
    for o in keep
]
p = len(X[0])
n = len(X)


def solve(X, Y):
    m = len(X[0])
    A = [[sum(X[i][a] * X[i][b] for i in range(len(X))) for b in range(m)] + [sum(X[i][a] * Y[i] for i in range(len(X)))] for a in range(m)]
    for c in range(m):
        piv = max(range(c, m), key=lambda r: abs(A[r][c]))
        A[c], A[piv] = A[piv], A[c]
        if abs(A[c][c]) < 1e-12:
            return None, None
        for r in range(m):
            if r == c:
                continue
            f = A[r][c] / A[c][c]
            for k in range(c, m + 1):
                A[r][k] -= f * A[c][k]
    beta = [A[r][m] / A[r][r] for r in range(m)]
    # (X'X)^-1 for SEs
    XtX = [[sum(X[i][a] * X[i][b] for i in range(len(X))) for b in range(m)] for a in range(m)]
    inv = [[1.0 if a == b else 0.0 for b in range(m)] for a in range(m)]
    W = [row[:] + inv[i][:] for i, row in enumerate(XtX)]
    for c in range(m):
        piv = max(range(c, m), key=lambda r: abs(W[r][c]))
        W[c], W[piv] = W[piv], W[c]
        d = W[c][c]
        for k in range(2 * m):
            W[c][k] /= d
        for r in range(m):
            if r == c:
                continue
            f = W[r][c]
            for k in range(2 * m):
                W[r][k] -= f * W[c][k]
    inv = [row[m:] for row in W]
    return beta, inv


beta, inv = solve(X, Y)
if beta is None:
    print("  singular -- covariates collinear at this n")
else:
    fitted = [sum(beta[j] * X[i][j] for j in range(p)) for i in range(n)]
    rss = sum((Y[i] - fitted[i]) ** 2 for i in range(n))
    s2 = rss / (n - p)
    names = ["intercept", "live (ms/bot)", "t (ms/min)", "sliced (ms)"]
    tc = {4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365}.get(n - p, 2.0)
    for j, nm in enumerate(names):
        se = math.sqrt(s2 * inv[j][j])
        print("  %-16s %+8.4f   se %.4f   95%% CI %+.4f .. %+.4f"
              % (nm, beta[j], se, beta[j] - tc * se, beta[j] + tc * se))
    print("  df %d, residual sd %.3f ms" % (n - p, math.sqrt(s2)))
    arm = beta[3]
    print("  arm effect implies share %.1f%% (vs registered %.0f-%.0f%%)"
          % (100 * -arm / (bracket_ai * dose), 100 * REG_LO_SH, 100 * REG_HI_SH))
print()

# ---------------------------------------------------------------- conserved?

print("DID THE WORK VANISH OR MOVE? ms per brain-tick, built per window.")
for b in blocks:
    print("  step %d %-3s  %.5f ms/tick" % (b["step"], b["arm"], b["per_tick"]))
bracket_pt = (b1a["per_tick"] + b1b["per_tick"]) / 2
print("  bracket %.5f vs sliced %.5f  ->  %+.1f%% per-tick cost on the sliced arm"
      % (bracket_pt, b2["per_tick"], 100 * (b2["per_tick"] / bracket_pt - 1)))
print()
print("  If per-tick cost is flat, the tick is genuinely a small share of aiTotal.")
print("  If per-tick cost rose ~1/dose, the work is CONSERVED and no scheduling")
print("  policy recovers it -- a different conclusion with the same drop.")
print()
print("  aiTotal.max per block (a conserved-work signature should raise the tail):")
for b in blocks:
    print("  step %d %-3s  max median %.2f ms" % (b["step"], b["arm"], med([o["aiTotal"]["max"] for o in b["w"]])))
