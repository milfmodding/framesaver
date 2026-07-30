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

"N OF N PASSED" IS WORTH NOTHING WITHOUT THE CONTROL, so pass `--neuter`: it copies the
reconciler with `fail()` blanked and re-runs every case. Each case expecting exit 1 must
then STOP failing. The survivors are the cases that never route through `fail()` - the
expected-to-pass ones and the REFUSALS - and the run tells you the count instead of you
remembering it.

It used to say "must drop to 3 of 9" and I had to hand-edit the reconciler to check. Two
problems with that: a documented ritual gets skipped, and the number goes stale the moment
a case is added - which it did, and a stale control number is worse than none, because the
next person sees a different figure and concludes something broke.

THE CONTROL IS NOT DECORATION - IT IS WHY THE COUNT MEANS ANYTHING. Nine of nine passed
here for a day while the reconciler's two `damageBy` branches had never executed on any
input, because no case supplied the field. The reconciler then crashed on the first real
log. A count is only evidence over the branches the cases actually reach.
"""
import glob
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RECON = os.path.join(HERE, "alpha-ledger-reconcile.py")
OUT = os.path.join(os.environ.get("TEMP", "."), "framesaver-selftest")
NEUTER = "--neuter" in sys.argv


def neutered_copy():
    """A copy of the reconciler whose fail() records nothing.

    Refuses rather than proceeding if the pattern does not match: a neutered run that
    silently neutered nothing would report the suite as healthy on the strength of a
    substitution that never happened."""
    src = io.open(RECON, encoding="utf-8").read()
    out = re.sub(r"def fail\(m\):\n    fails\.append\(m\)",
                 "def fail(m):\n    pass  # NEUTERED", src, count=1)
    if out == src:
        print("REFUSED: could not neuter fail() - pattern did not match, so a")
        print("         'suite collapsed' result would mean nothing.")
        sys.exit(2)
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, "reconcile-neutered.py")
    io.open(dst, "w", encoding="utf-8").write(out)
    return dst


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


def death(w, q, i, raid_tag, isai=True, state="named", dmg="Bullet", killer_ai=True,
          damage_by="MISSING"):
    """`damage_by` defaults to matching the killer id, which is the ordinary case.

    It used to be omitted entirely, which meant the reconciler's two damageBy branches -
    artillery attribution and killer/damageBy disagreement - never executed on any input,
    synthetic or real. The reconciler then crashed on the first real log, because
    damageBy is a bare profile-id STRING and I had compared it as an object. Nine of nine
    passing said nothing about a field no case supplied."""
    k = None
    if state == "named":
        k = {"id": "k1", "role": "pmcUSEC" if killer_ai else "Usec", "isAI": killer_ai}
    if damage_by == "MISSING":
        damage_by = k["id"] if k else None
    return {"type": "death", "qpc": q, "window": w, "state": "raid", "raidElapsed": 60.0,
            "id": "p%s-%d" % (raid_tag, i), "role": "exUsec", "isAI": isai,
            "pos": [0, 0, 0], "damageType": dmg, "bodyPart": "Chest",
            "killerState": state, "killer": k, "damageBy": damage_by}


def write(name, samples, events):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with io.open(p, "w", encoding="utf-8") as f:
        for o in samples:
            f.write(json.dumps(o) + "\n")
        for o in events:
            f.write(json.dumps(o) + "\n")
    return p


def run(path, recon):
    r = subprocess.run([sys.executable, recon, path], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def main():
    # Flags filtered out of the positionals, or --neuter gets read as the source path.
    src = ([a for a in sys.argv[1:] if not a.startswith("--")] or sorted(glob.glob(
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

    # 10-12. THE damageBy BRANCHES, which no case above ever reached. All three exist
    #        because the reconciler crashed on real data where nine synthetic cases had
    #        passed - the field was absent from every one of them.

    # 10. Killer and damageBy name DIFFERENT sources. Must be reported, not silently
    #     resolved by whichever field a reader opens first.
    ev = [spawn(w0, q0, i, "h") for i in range(peak + 5)]
    ev += [death(ws[-1]["window"], ws[-1]["qpc"] - 1000, 0, "h", damage_by="someone-else")]
    cases.append(("damageby-disagree.ndjson", ev, 0, ["DIFFERENT sources"]))

    # 11. ARTILLERY: the game declines to attribute, the blow names a source. Attributing
    #     from damageBy here would overstate player involvement, which is the whole reason
    #     both fields are carried.
    ev = [spawn(w0, q0, i, "i") for i in range(peak + 5)]
    ev += [death(ws[-1]["window"], ws[-1]["qpc"] - 1000, 0, "i", state="none",
                 damage_by="a-player-id")]
    cases.append(("artillery.ndjson", ev, 0, ["did NOT attribute"]))

    # 12. WRONG TYPE. damageBy as an object is the exact mistake the reader made, so the
    #     reader must REFUSE rather than compare a dict against a string and report every
    #     death as a disagreement - a fabricated finding in the direction we most want to
    #     avoid. This case is the reason the guard exists.
    ev = [spawn(w0, q0, i, "j") for i in range(peak + 5)]
    ev += [death(ws[-1]["window"], ws[-1]["qpc"] - 1000, 0, "j",
                 damage_by={"id": "k1"})]
    cases.append(("damageby-wrong-type.ndjson", ev, 2, ["not a string or null"]))

    recon = neutered_copy() if NEUTER else RECON
    if NEUTER:
        print("NEUTERED RUN: fail() records nothing, so every case expecting exit 1 must")
        print("now collapse. Cases expecting 0 or 2 must NOT - they do not route through")
        print("fail(), and that independence is the point of a separate refusal path.\n")

    bad, collapsed, survived = 0, 0, 0
    for name, events, want_code, want_text in cases:
        p = write(name, samples, events)
        code, out = run(p, recon)
        ok = code == want_code and all(t in out for t in want_text)

        if NEUTER and want_code == 1:
            # The expectation inverts: a fail-path case must no longer be satisfied.
            if ok:
                survived += 1
                bad += 1
                verdict = "**SURVIVED NEUTERING**"
            else:
                collapsed += 1
                verdict = "collapsed"
            print("%-26s exit %d  %s" % (name, code, verdict))
            continue

        print("%-26s exit %d (want %d)  %s"
              % (name, code, want_code, "PASS" if ok else "**MISMATCH**"))
        if not ok:
            bad += 1
            missing = [t for t in want_text if t not in out]
            if missing:
                print("    expected text not found: %r" % missing)
            print("    ---- output ----")
            for l in out.splitlines():
                print("    " + l)

    if NEUTER:
        print("\n%d of %d fail-path cases collapsed, %d survived."
              % (collapsed, collapsed + survived, survived))
        if survived:
            print("A survivor was passing for a reason other than the check it names.")
        else:
            print("Every fail-path case depends on fail(), so the counts above mean "
                  "what they say.")
    else:
        print("\n%d of %d expectations held" % (len(cases) - bad, len(cases)))
        print("Re-run with --neuter to confirm the count is load-bearing.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
