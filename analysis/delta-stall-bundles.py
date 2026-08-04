"""Adjudicate Alpha's co-occurrence claim: post-warmup frames > 250 ms and bundle loads.

CLAIM (Alpha, 2026-08-03): post-warm-up, across the corpus, 13 of 13 frames over 250 ms
fall in windows that also carry a bundle load; therefore goal-2 violations look like asset
streaming, not AI. Stated as co-occurrence at 30 s window resolution; handed to me for
frame-resolution confirmation or death.

Three things a co-occurrence needs before it may become an attribution:

  1. THE POPULATION. "13 of 13" is only impressive against the base rate of bundle-loaded
     windows. If most kept windows carry a load, 13/13 is expected under independence.
     Both operationalisations of "frame > 250 ms" are computed - window frame.max (likely
     Alpha's) and spike events (paired per delta-stall-events, so boundary double-counts
     collapse).
  2. MAGNITUDE MATCHING, frame resolution. The window aggregate `bundleLoad.syncMsMax` is
     the largest single synchronous load in the window. If syncMsMax is commensurate with
     the stall (same order as mag), streaming can own the frame; if the window's whole
     syncMsTotal is milliseconds against a 300 ms stall, co-occurrence is an alibi, not a
     cause.
  3. PHASE SHAPE. Each spike carries its own phase breakdown. A synchronous bundle load
     stalls outside the scripted top-level phases or inside EarlyUpdate preloading; an AI
     stall shows up under Update. delta-stall-families' rule: attribute by TOP-LEVEL
     phase first.

Known weaknesses:
  - `bundleLoad` counters are window aggregates; a window can carry both a bundle load and
    an unrelated stall. Magnitude matching (2) is the guard, but a big load and a big
    unrelated stall in one window would still fool it.
  - worstCallbacks is a top-N list; a sync load outside the top N is invisible there
    (the window aggregate still sees it).
  - Warm-up (60 s) and teardown (last window per segment) follow the corpus convention -
    itself a hand-me-down from the 60 s-window era (see DELTA-STATE.md).
"""
import collections
import glob
import json
import os

LOGDIR = r"F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs"
WARMUP = 60
CUT = 250.0
HZ = 10_000_000
ADJ_MS, MAG_TOL = 100.0, 0.10
TOP = ("TimeUpdate", "Initialization", "EarlyUpdate", "FixedUpdate",
       "PreUpdate", "Update", "PreLateUpdate", "PostLateUpdate")


def mag(o):
    return max(o.get("frame") or 0.0, o.get("period") or 0.0)


def read_log(path):
    samples, spikes = [], []
    for ln in open(path, encoding="utf-8-sig", errors="replace"):
        ln = ln.strip()
        if not ln.endswith("}"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("state") != "raid":
            continue
        if o.get("type") == "sample":
            samples.append(o)
        elif o.get("type") == "spike":
            spikes.append(o)
    return samples, spikes


def kept_windows(samples):
    """Post-warmup, teardown dropped, per (raid, map) segment. Returns {window: sample}."""
    seg = collections.defaultdict(list)
    for o in samples:
        seg[(o.get("raid"), str(o.get("map")))].append(o)
    out = {}
    for k in sorted(seg):
        for o in seg[k][:-1]:
            el, ws = o.get("raidElapsed"), o.get("windowSec")
            if el is not None and ws is not None and el - ws >= WARMUP:
                out[o["window"]] = o
    return out


def events(spikes):
    out = []
    for o in spikes:
        if out:
            prev = out[-1][-1]
            q0, q1 = prev.get("qpc"), o.get("qpc")
            dt = (q1 - q0) / HZ * 1000.0 if q0 is not None and q1 is not None else None
            m0, m1 = mag(prev), mag(o)
            if dt is not None and dt <= ADJ_MS and m0 > 0 and abs(m1 - m0) / m0 <= MAG_TOL:
                out[-1].append(o)
                continue
        out.append([o])
    return out


def main():
    all_kept = 0
    loaded_kept = 0
    hot_windows = []   # (log, sample) with frame.max > CUT
    hot_events = []    # (log, event, sample) spike events with mag >= CUT in kept windows

    for path in sorted(glob.glob(os.path.join(LOGDIR, "framesaver-*.ndjson"))):
        name = os.path.basename(path)
        samples, spikes = read_log(path)
        keep = kept_windows(samples)
        all_kept += len(keep)
        for w, s in keep.items():
            bl = s.get("bundleLoad") or {}
            if (bl.get("calls") or 0) > 0:
                loaded_kept += 1
            fr = s.get("frame") or {}
            if (fr.get("max") or 0.0) > CUT:
                hot_windows.append((name, s))
        for ev in events(spikes):
            m = max(mag(o) for o in ev)
            w = ev[0].get("window")
            if m >= CUT and w in keep:
                hot_events.append((name, ev, keep[w]))

    base = loaded_kept / all_kept if all_kept else 0.0
    print("POPULATION: %d kept windows (post-warmup, teardown dropped, in-raid), of which"
          % all_kept)
    print("%d (%.0f%%) carry a bundle load (bundleLoad.calls > 0)." % (loaded_kept, 100 * base))
    nhw = len(hot_windows)
    nhl = sum(1 for _, s in hot_windows if ((s.get("bundleLoad") or {}).get("calls") or 0) > 0)
    print("\nA. WINDOW OPERATIONALISATION (frame.max > %.0f ms): %d windows, %d loaded."
          % (CUT, nhw, nhl))
    if nhw:
        print("   P(all %d loaded | independence at base rate) = %.2g"
              % (nhw, base ** nhw if base > 0 else 0.0))

    print("\nB. FRAME RESOLUTION: %d spike events with mag >= %.0f ms in kept windows."
          % (len(hot_events), CUT))
    print("   For each: stall size, its own phase shape, and the window's bundle numbers.")
    print("   %-34s %-12s %7s %9s %7s  %-24s %8s %8s %5s"
          % ("log", "map", "mag", "unacc", "topSum", "dominant top phase", "syncMax",
             "syncTot", "calls"))
    for name, ev, s in sorted(hot_events, key=lambda t: -max(mag(o) for o in t[1])):
        o = max(ev, key=mag)
        allph = {k: v for k, v in (o.get("phases") or {}).items()
                 if isinstance(v, (int, float))}
        ph = {k: v for k, v in allph.items() if k in TOP}
        dom = max(ph, key=ph.get) if ph else None
        kids = {k: v for k, v in allph.items() if dom and k.startswith(dom + "/")}
        kid = max(kids, key=kids.get) if kids else None
        bl = s.get("bundleLoad") or {}
        wc = s.get("worstCallbacks") or []
        wcb = max((c.get("bundleSyncMs") or 0.0) for c in wc) if wc else 0.0
        print("   %-34s %-12s %7.1f %9.1f %7.1f  %-24s %8.1f %8.1f %5d"
              % (name.replace("framesaver-", "")[:34], str(s.get("map"))[:12],
                 max(mag(x) for x in ev), o.get("unaccounted") or 0.0, sum(ph.values()),
                 "%s %.0f" % (dom, ph[dom]) if dom else "-",
                 bl.get("syncMsMax") or 0.0, bl.get("syncMsTotal") or 0.0,
                 bl.get("calls") or 0))
        if kid:
            print("     child: %s %.1f ms" % (kid.split("/", 1)[1], kids[kid]))
        if wcb:
            worst = max(wc, key=lambda c: c.get("bundleSyncMs") or 0.0)
            print("     worstCallback with bundle sync: %s" % json.dumps(worst))

    print("\nVERDICT MATERIAL: a stall is bundle-ATTRIBUTED only if syncMsMax is the same")
    print("order as the stall; loaded-but-tiny syncMsTotal is co-occurrence, not cause.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
