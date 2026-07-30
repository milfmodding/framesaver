"""Does wake churn track the tail? A within-raid probe on data already on disk.

WHY A PROBE AND NOT A MEASUREMENT. Delta could not exclude wake-churn as the driver of raid
1.5's worse tail - more sleepers means more wake TRANSITIONS per encounter, and every quantity
this project measures is per-frame, not per-transition. Sophia wants it measured. A proper
measurement needs a transition counter that does not exist yet. This is what can be asked of
the logs we already have, and its answer is suggestive at best.

THE PROXY AND ITS WEAKNESS, which is the whole reason this is a probe. Nothing counts
transitions, so churn is approximated by |awake[i] - awake[i-1]| between consecutive windows.
That is the NET change and transitions are GROSS: a bot waking while another sleeps inside one
window cancels to zero. So the proxy is a strict LOWER BOUND on churn, and it understates most
in exactly the busy windows where churn should matter most.

WHAT THAT MEANS FOR EACH OUTCOME, decided before looking:
  correlation present  -> churn is worth the counter, and the true effect is larger than shown
  correlation absent   -> INCONCLUSIVE, not negative. A lower-bound proxy that understates
                          worst where the signal should be strongest cannot clear the
                          hypothesis. Say inconclusive; do not say no.

Spikes are counted per window by qpc containment against the window boundaries - the same
containment rule as the PresentMon join, not nearest.
"""
import glob
import json
import math
import os
import statistics
import sys

LOGS = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"


def spearman(x, y):
    """Rank correlation - the tail is heavy and Pearson would be led by one window."""
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(x), rank(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


def main():
    for path in sorted(glob.glob(os.path.join(LOGS, "*raid1*.ndjson"))):
        wins, spikes, prevqpc = [], [], None
        for ln in open(path, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln.endswith("}"):
                continue
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            t = o.get("type")
            if t == "spike" and o.get("qpc"):
                spikes.append(o["qpc"])
            elif t == "sample":
                q = o.get("qpc")
                if (o.get("state") == "raid" and not o.get("final") and q and prevqpc
                        and (o.get("bots") or {}).get("total")):
                    wins.append({"w": o.get("window"), "lo": prevqpc, "hi": q,
                                 "awake": (o.get("bots") or {}).get("awake"),
                                 "asleep": (o.get("bots") or {}).get("asleep"),
                                 "p99": (o.get("framePct") or {}).get("p99"),
                                 "max": (o.get("frame") or {}).get("max")})
                if q:
                    prevqpc = q
        if len(wins) < 6:
            continue

        for w in wins:
            w["spikes"] = sum(1 for q in spikes if w["lo"] < q <= w["hi"])
        for i, w in enumerate(wins):
            w["churn"] = (abs(w["awake"] - wins[i - 1]["awake"])
                          if i and w["awake"] is not None and wins[i - 1]["awake"] is not None
                          else None)

        rows = [w for w in wins if w["churn"] is not None and w["p99"] and w["max"]]
        if len(rows) < 6:
            continue

        print("=== %s" % os.path.basename(path))
        print("    %d windows with a churn proxy, %d spike lines in raid" % (len(rows), len(spikes)))
        print("    %-4s %6s %7s %7s %8s %8s" % ("win", "awake", "churn", "spikes", "p99 ms", "max ms"))
        for w in rows:
            print("    %-4s %6s %7s %7s %8.2f %8.2f"
                  % (w["w"], w["awake"], w["churn"], w["spikes"], w["p99"], w["max"]))

        ch = [w["churn"] for w in rows]
        print("\n    churn proxy: median %.0f, max %d, zero in %d of %d windows"
              % (statistics.median(ch), max(ch), sum(1 for c in ch if c == 0), len(ch)))
        for name, key in (("p99", "p99"), ("frame.max", "max"), ("spike count", "spikes")):
            r = spearman(ch, [w[key] for w in rows])
            print("    spearman(churn, %-11s) = %+.3f" % (name, r))
        print()

    print("READ IT AS A PROBE. The proxy is a lower bound on churn and understates worst in the")
    print("busy windows where churn should matter most, so a NULL here is inconclusive rather")
    print("than negative. Only a real transition counter can clear the hypothesis - one")
    print("increment in Wake() and one in the sleep path, both single choke points.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
