"""Self-test for alpha-ledger-reconcile.py: does every failure branch actually fire?

No deployed build emits botSpawn/death yet, so the reconciler is written against a
contract and has never seen its own failure paths execute. A checker whose failure
branches have never run is the defect this project keeps finding, so this exercises
them before the first real raid rather than after it.

REAL SAMPLES, SYNTHETIC EVENTS. The sample side is lifted verbatim from a real marathon
log - real `window`, `raid`, `qpc`, `bots.total`, real loading windows, real ordinals -
because a fully synthetic file shares every assumption of whoever wrote it, and this
project has already been bitten by a synthetic that was tidy in exactly the way the bug
was not. Only the event lines are constructed, and they are constructed UNTIDY on
purpose: each defect below exists because it is one the contract permits.

Run:  python alpha-ledger-reconcile-selftest.py [source.ndjson]
Exit 0 if every expectation held, 1 otherwise.

"9 OF 9 PASSED" IS WORTH NOTHING WITHOUT THE CONTROL, so here is the control and how to
re-run it. Neuter the reconciler's `fail()` so it records a note instead:

    def fail(m):
        notes.append(m)

and this self-test must drop to 3 of 9. The three survivors are the two
expected-to-pass cases and the no-events REFUSAL, none of which route through `fail()` -
so 3 is the right number, and anything higher means an expectation is being satisfied by
something other than the check it names. Verified on 2026-07-29: 9/9 sabotaged to 3/9,
restored to 9/9. A suite that passes against a checker which cannot fail is the defect
this whole file exists to rule out, and it is cheap to re-establish after any edit.
"""
import glob
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RECON = os.path.join(HERE, "alpha-ledger-reconcile.py")
OUT = os.path.join(os.environ.get("TEMP", "."), "framesaver-selftest")


def real_samples(src):
    out = []
    for ln in io.open(src, encoding="utf-8-sig", errors="replace"):
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("type") in ("header", "sample"):
            out.append(o)
    return out


def spawn(w, q, i, raid_tag, isai=True, role="exUsec", stand=True):
    return {"type": "botSpawn", "qpc": q, "window": w, "state": "raid", "raidElapsed": 60.0,
            "id": "p%s-%d" % (raid_tag, i), "role": role, "isAI": isai,
            "pos": [0, 0, 0], "canStandBy": stand}


def death(w, q, i, raid_tag, isai=True, state="named", dmg="Bullet", killer_ai=True):
    k = None
    if state == "named":
        k = {"id": "k1", "role": "pmcUSEC" if killer_ai else "Usec", "isAI": killer_ai}
    return {"type": "death", "qpc": q, "window": w, "state": "raid", "raidElapsed": 60.0,
            "id": "p%s-%d" % (raid_tag, i), "role": "exUsec", "isAI": isai,
            "pos": [0, 0, 0], "damageType": dmg, "bodyPart": "Chest",
            "killerState": state, "killer": k}


def write(name, samples, events):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with io.open(p, "w", encoding="utf-8") as f:
        for o in samples:
            f.write(json.dumps(o) + "\n")
        for o in events:
            f.write(json.dumps(o) + "\n")
    return p


def run(path):
    r = subprocess.run([sys.executable, RECON, path], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def main():
    src = (sys.argv[1:] or sorted(glob.glob(
        r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson")))[-1]
    samples = real_samples(src)
    raids = {}
    for s in samples:
        if s.get("type") != "sample" or s.get("window") is None:
            continue
        raids.setdefault(s.get("raid"), []).append(s)
    # The raid with the most windows carrying a census, so the ledger has something to
    # disagree with. Picking by window count instead would find a loading-heavy raid.
    target = max((r for r in raids if r is not None),
                 key=lambda r: sum(1 for s in raids[r] if (s.get("bots") or {}).get("total")))
    ws = [s for s in raids[target] if (s.get("bots") or {}).get("total")]
    first, peak = ws[0], max((s.get("bots") or {}).get("total") for s in ws)
    w0, q0 = first["window"], first["qpc"] - 1000
    other = next((r for r in raids if r is not None and r != target), None)

    print("source %s" % os.path.basename(src))
    print("raid %s, %d censused windows, peak bots.total %d, first window %d\n"
          % (target, len(ws), peak, w0))

    cases = []

    # 1. CLEAN. Ledger above census everywhere, every death pairs, one human death
    #    present so the isAI filter has something to exclude.
    ev = [spawn(w0, q0, i, "a") for i in range(peak + 5)]
    ev += [death(ws[-1]["window"], ws[-1]["qpc"] - 1000, 0, "a")]
    ev += [death(ws[-1]["window"], ws[-1]["qpc"] - 1000, 99, "a", isai=False)]
    cases.append(("clean.ndjson", ev, 0, ["every AI death pairs", "non-AI"]))

    # 2. MISSED SPAWN HOOK: a death whose id never spawned.
    ev = [spawn(w0, q0, i, "b") for i in range(peak + 5)]
    ev += [death(ws[-1]["window"], ws[-1]["qpc"] - 1000, 4242, "b")]
    cases.append(("orphan-death.ndjson", ev, 1, ["NO matching botSpawn"]))

    # 3. DUPLICATE id inside one raid.
    ev = [spawn(w0, q0, i, "c") for i in range(peak + 5)] + [spawn(w0, q0, 0, "c")]
    ev += [death(ws[-1]["window"], ws[-1]["qpc"] - 1000, 1, "c")]
    cases.append(("dupe-id.ndjson", ev, 1, ["more than once within ONE raid"]))

    # 4. LEDGER BELOW CENSUS: too few spawns for the population the census counts.
    ev = [spawn(w0, q0, i, "d") for i in range(2)]
    ev += [death(ws[-1]["window"], ws[-1]["qpc"] - 1000, 0, "d")]
    cases.append(("ledger-low.ndjson", ev, 1, ["ledger BELOW census"]))

    # 5. ZERO AI DEATHS with spawns present - Beta's virtual-OnDead risk.
    ev = [spawn(w0, q0, i, "e") for i in range(peak + 5)]
    ev += [death(ws[-1]["window"], ws[-1]["qpc"] - 1000, 7, "e", isai=False)]
    cases.append(("no-ai-deaths.ndjson", ev, 1, ["ZERO AI deaths"]))

    # 6. WINDOW ORDINAL LYING: correct-looking ordinal, qpc from another window.
    ev = [spawn(w0, q0, i, "f") for i in range(peak + 5)]
    ev += [death(w0, ws[-1]["qpc"] - 1000, 0, "f")]
    cases.append(("window-lie.ndjson", ev, 1, ["disagrees with qpc containment"]))

    # 7. killerState=none WITHOUT damageType - artillery reading as nothing.
    ev = [spawn(w0, q0, i, "g") for i in range(peak + 5)]
    d = death(ws[-1]["window"], ws[-1]["qpc"] - 1000, 0, "g", state="none")
    d["damageType"] = ""
    ev += [d]
    cases.append(("none-no-dmg.ndjson", ev, 1, ["carries no damageType"]))

    # 8. NO EVENTS AT ALL - must REFUSE, not pass. The failure this whole file guards.
    cases.append(("no-events.ndjson", [], 2, ["Refusing to report"]))

    # 9. ID REUSE ACROSS RAIDS - legitimate, Players are pooled. Must NOT fail.
    if other is not None:
        ows = [s for s in raids[other] if (s.get("bots") or {}).get("total")]
        if ows:
            opeak = max((s.get("bots") or {}).get("total") for s in ows)
            ev = [spawn(w0, q0, i, "a") for i in range(peak + 5)]
            ev += [spawn(ows[0]["window"], ows[0]["qpc"] - 1000, i, "a")
                   for i in range(opeak + 5)]
            ev += [death(ws[-1]["window"], ws[-1]["qpc"] - 1000, 0, "a"),
                   death(ows[-1]["window"], ows[-1]["qpc"] - 1000, 1, "a")]
            cases.append(("id-reuse.ndjson", ev, 0, ["more than one raid"]))

    bad = 0
    for name, events, want_code, want_text in cases:
        p = write(name, samples, events)
        code, out = run(p)
        ok = code == want_code and all(t in out for t in want_text)
        print("%-22s exit %d (want %d)  %s" % (name, code, want_code, "PASS" if ok else "**MISMATCH**"))
        if not ok:
            bad += 1
            missing = [t for t in want_text if t not in out]
            if missing:
                print("    expected text not found: %r" % missing)
            print("    ---- output ----")
            for l in out.splitlines():
                print("    " + l)

    print("\n%d of %d expectations held" % (len(cases) - bad, len(cases)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
