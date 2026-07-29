"""What does one more bot cost, and how much of that cost is AI?

The bucketing proposal's surviving justification is headroom to RAISE population.
That justification has never been sized. The AI ceiling is known (1.6-4.9% of the
frame); the cost of A BOT is not, and they are different numbers. If the marginal
bot costs mostly animation, physics and rendering, then an AI scheduler does not
buy population headroom no matter how good the scheduler is.

Within-map, within-leg OLS of per-window mean cost on bots.awake. Steady state
only (raidElapsed >= 120 s), non-final windows.

OBSERVATIONAL AND CONFOUNDED, stated up front: awake count rises when the player
is near a bot cluster, which is also when rendering, physics and audio load rise.
The total-frame slope is therefore an OVER-estimate of a bot's causal cost, and
the aiTotal slope is comparatively clean because aiTotal times only the bot tick.
That asymmetry biases the AI SHARE downward - i.e. against my own argument - so a
small share here is a conservative reading, not a flattering one.
"""
import json
import glob
import sys
from collections import defaultdict

LOGS = sys.argv[1:] or sorted(glob.glob(
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson"))
STEADY = 120.0
ANIM = "PreLateUpdate/DirectorUpdateAnimationBegin"

rows = []
for path in LOGS:
    leg, prev = 0, None
    for ln in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "sample" or o.get("state") != "raid":
            continue
        m = str(o.get("map") or "?")
        if m != prev:
            prev, leg = m, leg + 1
        if o.get("final") or (o.get("raidElapsed") or 0) < STEADY:
            continue
        b = o.get("bots") or {}
        ph = o.get("phases") or {}
        rows.append({
            "leg": "%s L%d" % (m, leg),
            "awake": b.get("awake") or 0,
            "total": b.get("total") or 0,
            "frame": (o.get("frame") or {}).get("avg") or 0.0,
            "ai": (o.get("aiTotal") or {}).get("avg") or 0.0,
            "anim": (ph.get(ANIM) or {}).get("avg") or 0.0,
            "late": (o.get("playerLate") or {}).get("avg") or 0.0,
            "tick": (o.get("playerTick") or {}).get("avg") or 0.0,
        })


def ols(xs, ys):
    """Slope, and its 95% interval via the standard error. Returns None if x is constant."""
    n = len(xs)
    if n < 4:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-9:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    resid = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    if n <= 2:
        return None
    se = (resid / (n - 2) / sxx) ** 0.5
    return b, 1.96 * se, n, min(xs), max(xs)


by = defaultdict(list)
for r in rows:
    by[r["leg"]].append(r)

print("marginal cost per +1 AWAKE bot, within leg, steady state only\n")
print("%-18s %4s %9s %22s %22s %22s" %
      ("leg", "n", "awake rng", "frame ms/bot", "aiTotal ms/bot", "animBegin ms/bot"))
print("-" * 104)

tot_ai, tot_frame = [], []
for leg in sorted(by):
    v = by[leg]
    xs = [r["awake"] for r in v]
    out = []
    for f in ("frame", "ai", "anim"):
        res = ols(xs, [r[f] for r in v])
        out.append(res)
    if out[0] is None:
        print("%-18s %4d   (awake constant or n too small)" % (leg, len(v)))
        continue
    rng = "%d-%d" % (out[0][3], out[0][4])
    cells = []
    for res in out:
        cells.append("%8.4f +/- %-8.4f" % (res[0], res[1]) if res else "%-19s" % "--")
    print("%-18s %4d %9s %22s %22s %22s" % (leg, len(v), rng, cells[0], cells[1], cells[2]))
    if out[0] and out[1] and out[0][0] > 0:
        tot_frame.append(out[0][0])
        tot_ai.append(out[1][0])

print("\nAI share of the marginal awake bot, per leg where the frame slope is positive")
if tot_frame:
    for f, a in zip(tot_frame, tot_ai):
        print("  frame %7.4f ms/bot   ai %7.4f ms/bot   AI share %5.1f%%" % (f, a, 100.0 * a / f))
    print("\n  median frame slope %.4f ms/bot, median ai slope %.4f ms/bot"
          % (sorted(tot_frame)[len(tot_frame) // 2], sorted(tot_ai)[len(tot_ai) // 2]))
else:
    print("  none - no leg gave a positive frame slope")

print("\nlevels for scale (median over all steady-state windows)")
for f in ("frame", "ai", "anim", "late", "tick"):
    s = sorted(r[f] for r in rows)
    print("  %-6s %8.3f ms" % (f, s[len(s) // 2] if s else 0.0))
print("  n windows %d" % len(rows))
