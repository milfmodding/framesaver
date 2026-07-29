"""Large stalls across the corpus, split by whether anything accounts for them.

Three buckets, not two, and the third is the one a two-way split hides:

  out-of-loop  unaccounted >= half the period. Already characterised.
  attributed   the eight top-level phases cover at least half the period.
  UNEXPLAINED  neither. The instrument saw the stall and nothing inside it.

Attribution uses the TOP-LEVEL phases and only then names a child inside the
dominant one. Preferring the deepest child is wrong: parents and children are
both emitted, so a 1448 ms period whose parent holds 1440 reports as a 6 ms
child and lands in the wrong bucket.
"""
import json
import glob
import sys
from collections import defaultdict

TOP = ("TimeUpdate", "Initialization", "EarlyUpdate", "FixedUpdate",
       "PreUpdate", "Update", "PreLateUpdate", "PostLateUpdate")
BIG = 150.0

LOGS = sys.argv[1:] or sorted(glob.glob(
    r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*.ndjson"))

rows = []
n_spikes = 0
for path in LOGS:
    for ln in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") != "spike":
            continue
        n_spikes += 1
        per = o.get("period") or 0.0
        if per < BIG:
            continue
        ph = {k: v for k, v in (o.get("phases") or {}).items()
              if isinstance(v, (int, float))}
        tops = {k: v for k, v in ph.items() if k in TOP}
        unacc = o.get("unaccounted") or 0.0
        covered = sum(tops.values())
        dom = max(tops, key=tops.get) if tops else None
        kids = {k: v for k, v in ph.items() if dom and k.startswith(dom + "/")}
        kid = max(kids, key=kids.get) if kids else None

        if unacc >= 0.5 * per:
            bucket = "out-of-loop"
        elif covered >= 0.5 * per:
            bucket = "attributed"
        else:
            bucket = "UNEXPLAINED"
        rows.append({
            "bucket": bucket, "state": o.get("state"), "map": o.get("map") or "?",
            "period": per, "unacc": unacc, "covered": covered,
            "dom": dom, "domMs": tops.get(dom) if dom else 0.0,
            "kid": kid, "kidMs": kids.get(kid) if kid else 0.0,
            "gcGen0": o.get("gcGen0"),
        })

print("%d spike lines, %d with period >= %.0f ms\n" % (n_spikes, len(rows), BIG))
by = defaultdict(list)
for r in rows:
    by[r["bucket"]].append(r)
for k in sorted(by):
    v = sorted(by[k], key=lambda r: -r["period"])
    raid = sum(1 for r in v if r["state"] == "raid")
    print("  %-12s n=%-4d (raid %-4d) max %9.1f  median %7.1f"
          % (k, len(v), raid, v[0]["period"], v[len(v) // 2]["period"]))

raid_rows = [r for r in rows if r["state"] == "raid"]
print("\nIN-RAID only: %d stalls >= %.0f ms\n" % (len(raid_rows), BIG))
sig = defaultdict(list)
for r in raid_rows:
    key = ("out-of-loop / no phase" if r["bucket"] == "out-of-loop"
           else "UNEXPLAINED" if r["bucket"] == "UNEXPLAINED"
           else "%s -> %s" % (r["dom"], (r["kid"] or "(parent only)")))
    sig[key].append(r)
for k in sorted(sig, key=lambda k: -len(sig[k])):
    v = sorted(sig[k], key=lambda r: -r["period"])
    print("  %-56s n=%-4d max %8.1f  median %7.1f"
          % (k[:56], len(v), v[0]["period"], v[len(v) // 2]["period"]))

print("\nworst in-raid ATTRIBUTED stalls (the ones with a named subsystem)\n")
att = [r for r in raid_rows if r["bucket"] == "attributed"]
for r in sorted(att, key=lambda r: -r["period"])[:12]:
    print("  %-14s period %8.1f  unacc %6.1f  covered %7.1f  gc %-4s  %s -> %s %.1f"
          % (r["map"], r["period"], r["unacc"], r["covered"], r["gcGen0"],
             r["dom"], r["kid"], r["kidMs"]))
