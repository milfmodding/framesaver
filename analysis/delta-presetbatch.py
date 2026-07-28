"""Re-derivation of the presetBatch / per-profile-size claims queued for the SPT PR.

Delta, 2026-07-28. Dependency-free, second implementation.

Source of truth is `worstCallbacks[].name`, which carries the request's role mix
(one `rolexLimit` clause per `GenerateCondition`) and the response length in
chars. The server rule under test is `BotController.cs:356`:

    BotCountToGenerate = Math.Max(GetBotPresetGenerationLimit(role), condition.Limit)

so a single-clause request of `roleXn` yields `max(presetBatch[role], n)` profiles.

Three things this script deliberately does NOT do:

  * It does not hard-code which bot.json era a log ran under. That would make
    the test circular -- the era is what the Max rule is being used to explain.
    Instead each log's era is *fitted* from three candidates (stock / cap 10 /
    cap 5), choosing whichever assignment makes per-profile size most consistent
    across the whole corpus. If the Max rule is wrong, no assignment fits.
  * It does not pool roles. The claim under test is that per-profile size is
    flat at 10.1-12.2 KB for every single-clause observation; pooling roles
    would hide exactly the failure mode being looked for.
  * It does not use multi-clause requests. `Max` applies per clause, so their
    size is a sum over per-role splits and cannot pin a per-profile figure.
"""

import glob
import itertools
import json
import os
import re
import statistics

LOG_GLOBS = [
    "F:/SPT/Base/BepInEx/plugins/Framesaver-logs/*.ndjson",
    "F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/*.ndjson",
]

# Stock presetBatch, from Libraries/SPTarkov.Server.Assets/SPT_Data/configs/bot.json.
STOCK_BATCH = {
    "assault": 45, "marksman": 30, "pmcBEAR": 15, "pmcUSEC": 15,
    "shooterBTR": 1, "followerBoar": 15, "followerBoarClose1": 10,
    "followerBoarClose2": 10, "cursedAssault": 50, "pmcBot": 40,
}

# A cap edit lowers every key to the cap; keys already below it are unchanged.
# Sophia ran stock, then a cap of 10, then the cap of 5 that is live now.
ERAS = ("stock", "cap10", "cap5")

STATED_BAND = (10.1, 12.2)  # the FINDINGS claim under test

NAME_RE = re.compile(r"bot/generate, ([^\]]*?), (\d+) chars")
CLAUSE_RE = re.compile(r"^([A-Za-z0-9]+)x(\d+)$")


def batch_for(role, era):
    stock = STOCK_BATCH.get(role)
    if stock is None:
        return None
    if era == "stock":
        return stock
    return min(stock, 10 if era == "cap10" else 5)


def observations():
    """Yield (log_tag, role, asked, chars) for every single-clause request.

    Truncated mixes (the emitter elides long ones with '...') are dropped: the
    clause list is incomplete, so neither the role set nor the count is known.
    """
    for pattern in LOG_GLOBS:
        for path in sorted(glob.glob(pattern)):
            tag = os.path.basename(path)[11:24]
            for line in open(path, encoding="utf-8", errors="replace"):
                if "bot/generate" not in line:
                    continue
                for cb in json.loads(line).get("worstCallbacks") or []:
                    m = NAME_RE.search(cb.get("name", ""))
                    if not m:
                        continue
                    mix, chars = m.group(1), int(m.group(2))
                    if mix.endswith("...") or "+" in mix:
                        continue
                    c = CLAUSE_RE.match(mix)
                    if c and c.group(1) in STOCK_BATCH:
                        yield tag, c.group(1), int(c.group(2)), chars


def kb_per_profile(rows, era_of):
    """chars / max(batch, asked) / 1024, grouped by role."""
    by_role = {}
    for tag, role, asked, chars in rows:
        generated = max(batch_for(role, era_of[tag]), asked)
        by_role.setdefault(role, []).append(chars / generated / 1024)
    return by_role


def cost(rows, era_of):
    """Total *relative* dispersion of KB/profile within each role.

    Relative, not absolute: an absolute (max - min) objective is dominated by
    whichever role has the largest profiles and will happily wreck a role with
    small ones. Weighted by n so a role seen 171 times outvotes one seen twice.
    """
    total = 0.0
    for sizes in kb_per_profile(rows, era_of).values():
        if len(sizes) > 1:
            med = statistics.median(sizes)
            total += len(sizes) * statistics.pstdev(sizes) / med
    return total


def fit_eras(rows, logs):
    """Pick one era per log, minimising within-role dispersion of KB/profile.

    Coordinate descent, restarted from each uniform assignment so a bad local
    optimum from one starting point cannot decide the answer. If the Max rule
    holds, one assignment collapses the dispersion; if it does not, every
    assignment leaves it wide -- which is the failure this is built to show.
    """
    best = None
    for start in ERAS:
        era_of = {t: start for t in logs}
        improved = True
        while improved:
            improved = False
            for tag in logs:
                pick = min(ERAS, key=lambda e: cost(rows, {**era_of, tag: e}))
                if pick != era_of[tag]:
                    era_of[tag] = pick
                    improved = True
        c = cost(rows, era_of)
        if best is None or c < best[1]:
            best = (era_of, c)
    return best


def main():
    rows = list(observations())
    logs = sorted({r[0] for r in rows})
    print(f"{len(rows)} single-clause observations across {len(logs)} logs\n")

    baseline = min((cost(rows, {t: e for t in logs}), e) for e in ERAS)
    era_of, fitted = fit_eras(rows, logs)
    print("Step 1 - fit one presetBatch era per log")
    print(f"  best single era forced on all logs : dispersion {baseline[0]:.1f} "
          f"({baseline[1]})")
    print(f"  best per-log assignment            : dispersion {fitted:.1f}")
    for tag in logs:
        print(f"    {tag}  {era_of[tag]}")
    print()

    by_role = kb_per_profile(rows, era_of)

    print("Step 2 - per-profile size by role, under the fitted eras")
    print(f"  {'role':20s} {'n':>4s} {'median KB':>10s} {'min':>7s} {'max':>7s}")
    for role in sorted(by_role, key=lambda r: -statistics.median(by_role[r])):
        s = by_role[role]
        print(f"  {role:20s} {len(s):>4d} {statistics.median(s):>10.1f} "
              f"{min(s):>7.1f} {max(s):>7.1f}")

    print(f"\nStep 3 - the FINDINGS claim under test:")
    print('  "Every single-clause observation in the log set lands at')
    print(f'   {STATED_BAND[0]}-{STATED_BAND[1]} KB per profile"\n')
    meds = {r: statistics.median(s) for r, s in by_role.items()}
    print(f"  observed role medians span {min(meds.values()):.1f} - "
          f"{max(meds.values()):.1f} KB ({max(meds.values())/min(meds.values()):.1f}x)")
    outside = {r: v for r, v in meds.items() if not STATED_BAND[0] <= v <= STATED_BAND[1]}
    print(f"  roles whose median falls OUTSIDE the stated band: "
          f"{len(outside)} of {len(meds)}")
    for role, v in sorted(outside.items(), key=lambda kv: -kv[1]):
        n = len(by_role[role])
        print(f"    {role:20s} {v:>6.1f} KB   (n={n})")
    n_out = sum(1 for r, s in by_role.items() for v in s
                if not STATED_BAND[0] <= v <= STATED_BAND[1])
    print(f"  individual observations outside the band: {n_out} of {len(rows)} "
          f"({n_out/len(rows)*100:.0f}%)")

    print("\nStep 4 - does the Max actually bind? (Alpha's 'is it inert' question)")
    print("  Broken out by era, because the number the PR needs is what the")
    print("  SHIPPED default costs -- not what Sophia's already-capped config does.\n")
    print(f"  {'era':8s} {'n':>4s} {'binds':>6s} {'median waste':>13s} {'max':>6s}")
    for era in ERAS:
        sub = [(role, asked, max(batch_for(role, era), asked) / asked)
               for tag, role, asked, _ in rows if era_of[tag] == era]
        if not sub:
            continue
        w = [s[2] for s in sub if s[2] > 1.0]
        print(f"  {era:8s} {len(sub):>4d} {len(w)/len(sub)*100:>5.0f}% "
              f"{statistics.median(w) if w else 1:>12.1f}x {max(w) if w else 1:>5.1f}x")
    print("\n  Same request, the two ends of the config edit -- assaultx3:")
    for era in ("stock", "cap5"):
        sz = [chars for tag, role, asked, chars in rows
              if role == "assault" and asked == 3 and era_of[tag] == era]
        if sz:
            print(f"    {era:6s} n={len(sz):>3d}  median {statistics.median(sz):>9,.0f} chars")

    print("\nStep 4b - Alpha's three marksman observations, located and checked")
    for tag, role, asked, chars in sorted(rows):
        if chars in (310696, 309609, 329627):
            gen = max(batch_for(role, era_of[tag]), asked)
            print(f"    {tag} {role}x{asked:<3d} {chars:>9,} chars -> "
                  f"Max({batch_for(role, era_of[tag])},{asked})={gen} profiles "
                  f"= {chars/gen/1024:.2f} KB each")

    print("\nStep 5 - the built-in control")
    print("  shooterBTR has presetBatch 1 in stock AND in the capped config, so")
    print("  Max(1, asked) == asked always and its size must NOT move with the")
    print("  config edits that moved every other role.\n")
    btr = sorted((tag, chars) for tag, role, asked, chars in rows
                 if role == "shooterBTR" and asked == 3)
    eras_spanned = sorted({era_of[t] for t, _ in btr})
    sizes = [c for _, c in btr]
    print(f"  n={len(sizes)} shooterBTRx3 observations spanning {eras_spanned}")
    print(f"  min={min(sizes):,}  max={max(sizes):,}  "
          f"spread={max(sizes)/min(sizes):.2f}x")
    mk = [chars for tag, role, asked, chars in rows
          if role == "marksman" and asked == 3]
    print(f"  for contrast, marksmanx3 over the same edits: "
          f"min={min(mk):,} max={max(mk):,} spread={max(mk)/min(mk):.2f}x")


if __name__ == "__main__":
    main()
