"""The window-length-neutral warm-up rule, tested for equivalence properly this time.

My first proposal was `raidElapsed > 60`. It is WRONG and would have done the opposite of the
intent: window 1 is stamped 60.2, not 60.0, so `> 60` KEEPS it - the one window measured as carrying
a 4.38x worst-frame spike. I assumed the stamp was at or below the nominal boundary without checking,
and the check took thirty seconds.

The principled form is: **keep a window only if it BEGINS after warm-up ends.** A window stamped `e`
with length `w` covers [e-w, e], so the test is `e - w >= WARMUP_S` with WARMUP_S = 60 - the measured
figure, one window at 60 s.

    60 s windows:  e - 60 >= 60  ->  e >= 120   identical to today's `>= 120`
    30 s windows:  e - 30 >= 60  ->  e >=  90   drops the 30 s and 60 s windows, keeps from 90

Window length is needed and it is NOT always on the sample line: era A/B/C logs carry `windowSec: 0`.
Falls back to cfg.windowSeconds, then the header, and REFUSES to guess - a rule that silently treats
an unknown length as zero would keep everything.
"""
import glob
import json
import os

LOG = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
WARMUP_S = 60.0

n = same = 0
differ, unknown_w = [], 0
for path in sorted(glob.glob(os.path.join(LOG, "framesaver-*.ndjson"))):
    hdr_w = None
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") == "header":
            hdr_w = o.get("windowSeconds")
            continue
        if o.get("type") != "sample" or o.get("state") != "raid":
            continue
        e = o.get("raidElapsed")
        if e is None:
            continue
        w = o.get("windowSec") or (o.get("cfg") or {}).get("windowSeconds") or hdr_w
        if not w:
            unknown_w += 1
            continue
        n += 1
        old = e >= 120.0
        new = (e - w) >= WARMUP_S
        if old == new:
            same += 1
        else:
            differ.append((os.path.basename(path)[:38], o.get("map"), round(e, 1), w, old, new))

print("in-raid windows with a resolvable window length: %d" % n)
print("windows with NO resolvable length (would have to refuse): %d" % unknown_w)
print("agree with today's `>= 120`: %d of %d" % (same, n))
print("disagree: %d" % len(differ))
for d in differ[:12]:
    print("    %-38s map=%s e=%ss w=%s  old_keeps=%s new_keeps=%s" % d)
print()
if not differ:
    print("-> IDENTICAL on every existing log. Adopting `raidElapsed - windowSec >= 60` is not an")
    print("   era change: 60 s legs keep exactly what they keep today, and 30 s legs will exclude")
    print("   the first 60 s rather than the first 90 s - matching the 60 s legs instead of")
    print("   diverging from them by 30 s.")
else:
    print("-> Not identical; it would move the existing corpus and is an era change after all.")
