"""Spike rates per stall EVENT rather than per spike line.

Delta, 2026-07-28.

A boundary stall emits two spike lines, not one -- the `frame` clock reports it
on the earlier line and the `period` clock on the later one (see the endToStart
alignment section in FINDINGS). So any rate counted per spike line over-counts
this family by up to 2x, and NOT by a constant factor: whether the earlier line
clears a given cut depends on its frame time, which differs by arm.

Two numbers depend on fixing that, and both were on hold:

  * the Protocol A slice trade (>100 ms and >300 ms rates across three arms);
  * the `frame > period` rate, quoted at 4.2% on the `period >= 100` population,
    which is the *later* half of every pair -- so the earlier halves, which are
    `frame > period` by construction, sit outside the denominator entirely.

Pairing rule, deliberately loose on magnitude and tight on time: two in-raid
spike lines are the same event if they are within one frame-time of each other
(<= 100 ms) and their stall magnitudes agree within 10%. Magnitude is
max(frame, period), which is the same physical quantity seen from either clock.
"""

import json
import statistics

LOG = 'F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-20260728-125209-latch.ndjson'
HZ = 10_000_000
ADJ_MS, MAG_TOL = 100.0, 0.10
# Protocol A arms: held windows with comparable draw calls, straddling the slice change.
ARMS = {'arm1 slice 0': range(13, 20), 'arm2 slice 6': range(23, 26), 'arm3 slice 0': range(27, 32)}


def load():
    spikes, windows, hdr = [], {}, None
    for line in open(LOG, encoding='utf-8', errors='replace'):
        o = json.loads(line)
        t = o.get('type')
        if t == 'header':
            hdr = o
        elif t == 'spike' and o.get('state') == 'raid':
            spikes.append(o)
        elif t == 'sample' and o.get('state') == 'raid':
            windows[o['window']] = o
    return spikes, windows, hdr


def mag(o):
    return max(o.get('frame') or 0.0, o.get('period') or 0.0)


def events(spikes):
    """Collapse adjacent same-magnitude lines into one event. Returns list of line-lists."""
    out = []
    for o in spikes:
        if out:
            prev = out[-1][-1]
            dt = (o['qpc'] - prev['qpc']) / HZ * 1000.0
            m0, m1 = mag(prev), mag(o)
            if dt <= ADJ_MS and m0 > 0 and abs(m1 - m0) / m0 <= MAG_TOL:
                out[-1].append(o)
                continue
        out.append([o])
    return out


def main():
    spikes, windows, hdr = load()
    ev = events(spikes)
    secs = hdr.get('windowSeconds')
    print(f"{len(spikes)} in-raid spike lines -> {len(ev)} events "
          f"({sum(1 for e in ev if len(e) > 1)} are multi-line)\n")

    print("Protocol A, rates per minute -- per line against per event")
    print(f"  {'arm':14s} {'win':>4s} {'min':>6s} "
          f"{'>100 line':>10s} {'>100 evt':>9s} {'>300 line':>10s} {'>300 evt':>9s}")
    res = {}
    for name, ws in ARMS.items():
        ws = [w for w in ws if w in windows]
        minutes = len(ws) * secs / 60.0
        lines = [o for o in spikes if o.get('window') in ws]
        evs = [e for e in ev if e[0].get('window') in ws]
        row = {}
        for cut in (100, 300):
            nl = sum(1 for o in lines if mag(o) >= cut)
            ne = sum(1 for e in evs if max(mag(o) for o in e) >= cut)
            row[cut] = (nl / minutes, ne / minutes, nl, ne)
        res[name] = row
        print(f"  {name:14s} {len(ws):>4d} {minutes:>6.1f} "
              f"{row[100][0]:>10.2f} {row[100][1]:>9.2f} "
              f"{row[300][0]:>10.2f} {row[300][1]:>9.2f}")

    print("\n  raw counts (events): "
          + ", ".join(f"{n}: {res[n][100][3]}@>100 {res[n][300][3]}@>300" for n in ARMS))

    a1, a2, a3 = (res[n] for n in ARMS)
    for cut in (100, 300):
        base = (a1[cut][1] + a3[cut][1]) / 2
        print(f"  >{cut} ms, arm2 vs mean of the two slice-0 arms, per event: "
              f"{a2[cut][1]:.2f} vs {base:.2f}  "
              f"({'below' if a2[cut][1] < base else 'above'}, "
              f"ratio {a2[cut][1]/base:.2f})" if base else "")

    # Is arm 2 low, or is it two Poisson draws? Exposure is windows x windowSeconds.
    print()
    for cut in (100, 300):
        k = res['arm2 slice 6'][cut][3]
        pooled = res['arm1 slice 0'][cut][3] + res['arm3 slice 0'][cut][3]
        lam = pooled / (12 * secs / 60.0) * (3 * secs / 60.0)
        print(f"  Poisson, arm2 low against the pooled slice-0 rate at >{cut} ms: "
              f"k={k}, lambda={lam:.2f}, one-sided p={poisson_p(k, lam):.3f}")

    print("\n`frame > period`: is it the earlier half of a pair, or unexplained?")
    fgp = [o for o in spikes if (o.get('frame') or 0) > (o.get('period') or 0)]
    paired = [o for o in fgp if any(len(e) > 1 and o in e for e in ev)]
    print(f"  in-raid lines with frame > period: {len(fgp)}")
    print(f"    of those, part of a multi-line event: {len(paired)} "
          f"({len(paired)/len(fgp)*100:.1f}%)")
    print(f"    unpaired -- the genuinely unexplained residue: {len(fgp)-len(paired)}")
    big = [o for o in fgp if mag(o) >= 100]
    bigp = [o for o in big if o in paired]
    print(f"  restricted to stalls >= 100 ms: {len(big)}, of which paired {len(bigp)}, "
          f"unpaired {len(big)-len(bigp)}")
    per = [o for o in spikes if (o.get('period') or 0) >= 100]
    print(f"\n  Alpha's denominator was `period >= 100` = {len(per)} lines, which is the LATER")
    print(f"  half of each pair. The earlier halves are frame > period by construction and")
    print(f"  sit outside it: {len(bigp)} such lines exist in this log.")


def poisson_p(k, lam):
    """One-sided P(X <= k) for a Poisson with mean lam -- 'is arm 2 low?'"""
    import math
    return sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k + 1))


if __name__ == '__main__':
    main()
