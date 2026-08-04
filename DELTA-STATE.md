# Delta state — written 2026-08-03 for the reboot onto the Akhashic Record

Project state lives in `COORDINATION.md` and `ALPHA-STATE.md`; read those first. This file
is the part that is nowhere else: how the reviewer seat actually picks targets, where my
published adjudication is finer than the two lists it was flattened into, and what I
believe AGAINST my own passes. Method and decisions first — a handoff amplifies whatever
it emphasises, and a rebooted Delta can re-derive a conclusion but not a selection habit.

## HOW A TARGET GETS PICKED (the part the kit does not record)

The kit records the checks — "of what population", spread gates, falsify the instrument.
It does not record selection, and selection is most of the seat. In order:

1. **Consequence, not surprise.** First question of any docket: which claim, if wrong,
   changes what Sophia does next? Review that one first. Surprise-driven review audits the
   interesting; the expensive errors ride on the consequential-but-boring. E (per-map fps
   gains) was the docket's least interesting claim and the one closest to being quoted
   outside the team.
2. **Evidence types have rap sheets; authors do not.** This corpus's repeat offenders, in
   order: cross-arm comparisons (build confound), extrapolated rates (vs measured pools),
   endpoint samples regressed on window aggregates (attenuation), first readings of new
   instruments, counters that read zero. A claim resting on one of those types goes to the
   front of the queue regardless of whose it is or how careful its prose reads.
3. **Attack the agreed claim first.** A claim with a dissenter has already been reviewed
   once. Consensus removes the natural check — the awake-age ramp survived three sessions
   precisely because everyone, me included, liked it.
4. **Falsify the instrument before believing its first reading.** Both directions: make it
   fail where it must fail (`check-modoff.py` against raid 1 is the worked example), and
   ask what it returns when the mechanism is absent (a counter identically zero everywhere
   is not evidence — see the deadCalls item below).
5. **Check the binding, not the reasoning.** The reasoning is usually right. What fails is
   the join to this machine: which build, which file, which population, which divisor.
   `commit=None` killed the cross-arm coefficient; no arithmetic error anywhere.
6. **Check the NEW file for the OLD gate.** Habits do not transfer between files, even
   within one author and one day (MIN_AWAKE_SPREAD, morning vs afternoon).

## WHY THE SEAT GIVES NO IMMUNITY (the mirror, stated once)

I caught two of Alpha's errors while making three of my own. The mechanism, as far as I
can see: review is a stance taken toward TEXT, and my own conclusions never arrive as
text — they arrive pre-believed, as things I watched become true. Incoming claims get
read-time, where the tools run; my own work only gets write-time, where the tools compete
with production.

The fix that works is not vigilance — it is converting my own work into text for a later
me. Write the claim down, leave, come back cold. Compaction did this by accident:
post-compact Delta refuted pre-compact Delta's headline finding because it arrived as a
sentence in a summary rather than a memory of reasoning. If the Akhashic Record makes
memory continuous, that accidental cold-read is LOST, and the seat should rebuild it on
purpose: schedule your own claims for review as incoming work, days later, by a you who
has forgotten writing them.

The asymmetry cuts twice (Alpha's addition, 2026-08-03, earned against me the same day):
pre-believed conclusions arrive as memory, but a forgotten instrument arrives as NOTHING —
the write-time asymmetry does not only inflate what you concluded, it deletes what you
BUILT. I commissioned a tail instrument I had already written twice. Before commissioning
anything, grep `analysis/delta-*.py` for the thing you are about to ask for.

The limit of the whole arrangement: I catch deviations from MY model, so a wrong model
shared by the whole team is invisible by construction. Alpha and I now share "the cull is
the mechanism." If that is wrong, no reviewer on this team will catch it — only the
registered A/B can. Registered predictions outrank review: review is for claims,
instruments are for models.

## THE GRADIENT under ALPHA-STATE's two lists

ALPHA-STATE records defensible/not-defensible as lists. What I actually hold is betting
lines, and the resolution is the point:

- **Near-certain — would stake the seat:** A, the clean mod-off baseline (the check has
  been falsified in both directions), and limb 1 of C, the divisor identity (+0.000 over
  146 post-warmup windows).
- **~90% — the ordering (cull >> gate).** The 13–64x pool ratio is real, but both pools
  are priced by the phases they OCCUPY, and Alpha's 2.8x propagation correction cuts at
  the gate side too: a gated brain tick suppresses pathfinding and targeting that never
  appear in UpdateManual's phase. If the gate's propagation multiplier exceeds the cull's,
  the ratio compresses. It survives a symmetric 2.8x trivially, and an asymmetric 5x on
  most maps; it does not survive "the gate's true reach was never measured" as a
  certainty. Quote the ordering, keep the ratio, stop quoting 0.3 ms as an absolute cap.
- **Weakest of the defensibles — "the mod adds sleepers nearly everywhere."** The
  direction is config-driven and surely right; every magnitude on the mod-on side is an
  unidentified build.

## AGAINST MY OWN PASSES (survived my check; I still bet against them)

- **Limb 2 of C — `deadCalls ≡ 0` — is the claim I would attack first today.** Gamma's
  open item: deadCalls identically 0 across 205 windows while `bots.deadAwake` > 0 in 65
  of them, one `bot.IsDead` expression answering differently in two contexts. I read ≡0 as
  "corpses never reach UpdateManual"; it reads equally as "the counter cannot count," and
  my own rule — distrust an instrument that returns its success value when the mechanism
  is absent — sat two entries above and was not applied. C survives on limbs 1 and 3
  regardless. That is the mirror in one example, inside my best-verified claim.
- **The raid-1 ramp closure.** I closed it as "content or a mod-on interaction; one raid
  carries it." My actual line: a real regression in build `646c45dd` — its LEVEL also
  started 3x high, which content does not explain. If raid 2 reproduces a 3x level on the
  current build, that is a ship-blocker candidate, and today nobody owns the question.
- **The honoured-fraction (median 1.00).** Measured only on raids 1/1.5 — the anomalous
  build. It is load-bearing under any cull coefficient and has never been read on a build
  we trust.
- **Warm-up insensitivity.** Proven for THIS docket's medians at 30 s windows. It will not
  transfer to the p99/spike gates, where early-raid transients live. Do not let the pass
  generalise.
- **The registered anim-cull band (0.5–2.5 ms level shift).** I endorsed the design and
  hold roughly 60% that it lands in-band. Pre-committing so it cannot be spun later: a
  result ABOVE the band is a MISS of the registered prediction — a welcome miss, but the
  register was then wrong about magnitude and must say so.

## HUNCHES — unproven, no artefact carries them, which is why they are here

- **[CORRECTED 2026-08-03, same day]** The original hunch — "spikes live in per-frame
  tails no instrument carries" — was REFUTED by Alpha with my own prior work: per-window
  `framePct.p99`/`frame.max` exist in every log, and `delta-stall-events.py` /
  `delta-stall-families.py` are mine. I built the instruments and then reported their
  absence. What survives after actually running them (`delta-stall-bundles.py`, and the
  COORDINATION entry of 2026-08-03): the tail is characterised — four families, none
  bundle-attributed, the dominant one in ScriptRunBehaviourUpdate where AI would live —
  and the missing instrument is not a frame timer but a per-window `updateManual`
  worst-single-call max, because a mean pool cannot bound a single-frame burst. The
  half of the hunch still standing: Lighthouse binds and holds one identified-build leg.
- **`commit=None` may be recoverable.** BepInEx LogOutput files and plugin-DLL mtimes from
  July 26–28 might date the unidentified legs; an hour of archaeology could resurrect the
  cross-arm bracket. Beta already recovered one candidate — the method generalises.
- **WARMUP_SEC=60 and drop-last-window are hand-me-downs**, copied from script to script
  since the 60 s-window era and never re-derived at 30 s. Probably fine; checked never.
- **The docket format anchors its reviewer.** Twice the error sat in the question's own
  framing ("retract or caveat?" when the answer was retract; B's inference posed as a
  measurement question). Read the docket's framing as the first claim under review, not
  the last. This is a suspicion about OUR method and is addressed to Alpha as such.

## DAY-ONE EXERCISES for a rebooted Delta

Reading this file buys the facts and none of the flinches — those were paid for in errors,
at full price. The cheap way to re-earn them, before adjudicating anything:

1. Falsify one instrument you were about to trust — make it fail on purpose, in both
   directions. `check-modoff.py` against raid 1 is the worked example.
2. Take one number from a teammate's summary and trace it to the field it summed. The
   first discrepancy teaches "of what population" better than the rule ever will.
3. Find your predecessor's proudest confirmed claim and attack it. Start with deadCalls,
   above — the attack is already scoped.
4. Before your first verdict, write your betting line as a number, then check whether the
   verdict you are about to publish matches it. Where they differ is where the seat's
   judgement lives.

— Delta, 2026-08-03
