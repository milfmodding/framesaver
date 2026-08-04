# Alpha state — written 2026-07-31 EOD to survive a context reset

Supersedes `ALPHA-STATE-MODOFF-MARATHON.md`, which is now history: the marathon ran. **Method and
decisions, not conclusions** — a handoff amplifies whatever it emphasises and cannot re-derive what it
carries, so everything below points at a script that can be re-run or a ruling that can be checked.

## THE STOPPING RULE, FIRST

> **Between runs, produce only what changes what happens in the next run.** Not "is it true", not "is it
> interesting". When there is nothing to measure, the correct output is silence.

Today was raid-driven and teammate-driven throughout, which is what that rule permits. The urge that
needs resisting is sweeping a reader or re-checking a population with no new data on disk.

## TOMORROW, AND ONE HARD CONSTRAINT

**1. The coupled cull A/B first.** `protocol-anim-cull.ini`. ABABAB, 120 s boxes, both sleep-skips pinned
false in every arm.

**THIS IS A CONSTRAINT, NOT A PRIORITY.** `bin/Release` now contains the decoupled-cull flag, so the
moment Beta deploys for the reload test **the A/B build is gone**. A/B needs its data first or we deploy
twice. If there is time for only one thing, it is the A/B — it answers the release question; decoupling
improves a mechanism we have not yet sized.

**2. The decoupled reload test.** `harness/RELOAD-OBSERVATION-TEST.md`. Procedure written before the build
existed and corrected three times by Beta. Non-negotiable parts: **turn away, never use cover** (frustum
visibility, so cover risks the cull never engaging and every attempt passing vacuously); **Step 0b proves
`animCulledEngine` rises before any real attempt**; **`Window seconds = 5`**, because that field samples
once at window close and a 6 s look-away would usually be missed at 30 s.

**3. Raid 2** needs QuestingBots installed (both halves). Still unmeetable until then.

## WHAT IS DEFENSIBLE AND WHAT IS NOT (Delta's adjudication, 2026-07-31)

**Defensible:**

- **The cull is the mechanism; stand-by only picks its targets — AS AN ORDERING, NOT AS A CAP.** Read off
  two directly measured POOLS per map — `updateManual.awakeMs / frames` is 0.056–0.298 ms/frame, the
  animator phase is 1.14–6.25 ms/frame. **13× to 64× on every one of nine maps.** No regression, no lever
  arm, no attenuation.

  **BOTH POOLS ARE OCCUPANCY-PRICED AND THE CORRECTION IS SYMMETRIC (Delta, 2026-08-01).** I found on
  2026-08-01 that pricing the *cull* at the phases it occupies understates it by a median 2.8×, because
  its effect propagates into phases it never appears in. Delta pointed out the same cut lands on the
  *gate* side: a suppressed brain tick also suppresses pathfinding and targeting that never appear in
  `UpdateManual`'s phase. So:
  - **The ORDERING survives** — trivially under a symmetric 2.8×, and under an asymmetric 5× on most maps.
  - **"Sleeping every bot buys under 0.3 ms" IS DEAD as an absolute cap**, and it is the same
    sentence-shape as the ceiling claim I retracted the same morning. Quote the ratio; do not quote
    either pool as a bound on what its mechanism can buy.
- **The mod adds sleepers nearly everywhere vanilla does not** — Customs 3→19, Lighthouse 2→17, Woods
  12→21, Reserve 2→10. The game *grants* `CanDoStandBy` on Ground Zero and Factory (100%) and Streets
  (62%); vanilla's trigger simply never fires.
- **Factory is structurally inert** — 85 m max spread against a 150 m rule, zero sleep in either arm.
- The mod-off baseline itself: 9 maps, 166 windows, `check-modoff.py` clean throughout, 0 unruled keys.

**NOT defensible:**

- **Any per-map fps gain.** The +28.6 / +11.3 / −10.4 figures are **withdrawn, not caveated.**
- **Any single per-bot cull coefficient.** 0.09–0.34 depending on estimator and lever arm; intercepts run
  negative on four of six maps (Lighthouse −5.96), which is proof the linear form is wrong outside the
  fitted range. `alpha-animator-slope.py` is superseded by `alpha-animator-aggregate.py`; both carry their
  own disconfirmations in the docstring rather than only the flattering fit.

Both wait on within-raid contrasts on identified builds.

## THE THREE NUMBERS MOST LIKELY TO BE QUOTED WRONG

1. **`aiTotal` IS NOT WHAT STAND-BY GATES.** It is `BotsController.method_0` and does not contain
   `BotOwner.UpdateManual` (`Telemetry.cs:1337` says so). Every "AI is N% of frame time" figure taken from
   it describes a slice stand-by does not touch. The right field is `updateManual.awakeMs / awakeCalls`
   ≈ **0.011 ms per awake bot**, against paused at 0.0002–0.0005.
2. **`bots.*` are INSTANTANEOUS samples** at window close (`CountBots`, one call site, `Telemetry.cs:1314`).
   Regressing a window aggregate on them attenuates the slope. The frame-weighted aggregates already exist
   and needed no new telemetry: `(awakeCalls − deadCalls) / frames` for live non-paused,
   `(awakeCalls + pausedCalls − deadCalls) / frames` for all live. Denominator verified: `D / frames`
   median 1.000 over 44 quiet windows, `frames == n` throughout.
3. **Lighthouse `[default]` is 17.40 ms / 57.5 fps at p75 and FAILS the 60 fps gate.** The pooled figure
   mixes arms. `alpha-fps-percentiles.py` splits three arms — `default`, `forceAll`, `standbyOff` —
   because it previously knew only about `forceAllRoles` and pooled the mod-off marathon into `default`.

   **THE GATE IS p75 WITH A p99 GUARD. This entry was flipped to p50 on 2026-08-01 and flipped back the
   same day; do not flip it a third time without reading this paragraph.** The p50 claim came from a
   memory file dated 2026-07-29 recording Sophia's 2026-07-28 revision to a p50 floor. That revision was
   real *and was later superseded by her move to p75*, which is recorded in two contemporaneous places —
   `harness/check-fields.py:409` ("Sophia moved the gate to p75 with a p99 guard") and
   `analysis/alpha-fps-percentiles.py:3` ("SOPHIA ASKED FOR p75 AND IT IS NOT IN THE TELEMETRY"). The
   ordering is datable from the corpus rather than recalled: **`framePct.p75` appears in exactly one of
   25 logs**, the 2026-07-31 marathon, and in none of the 22 before it — so the field was added for that
   request between 2026-07-29 21:56 and 2026-07-31 11:27, after the p50 revision.

   The lesson is the one this file exists to carry: **a memory file has no *as-of* marker and the code
   does.** Prefer the dated artefact over the undated sentence, including when the undated sentence is
   your own and reads like an instruction.

## SETTLED BY SOPHIA

- **`Base` is a CLOSED corpus.** Older SPT version, upgraded away from. Boundary is a filesystem fact:
  `SPT4.0.13` created **2026-07-26 15:28:36**; anything in `Base` after that is noise, which disposes of
  the four `20260729-*-control` orphans she cannot account for. Available for a historical question, never
  pooled, **not a control** — the two installs differ in SPT version *and* AI mod stack *and* Framesaver
  build. Recorded in `analysis/CORPUS.md`.
- **`Force fast body animator` is REMOVED** (`299fd86`), her call: a first draft that completely breaks the
  game. `check-modoff.py` has a `RETIRED` table so absent-is-not-off does not fire on the build carrying
  the fix. An inverted guard now disables the cull if anything else sets `UseBodyFastAnimator`.
- **Decoupling is authorised to be explored.** Built at `aeec0d4`, flag off by default, not the release
  default until the reload test passes.
- **"Demo" means early-tester DLLs, not a release.** Her words: the churn is getting lower so she can start
  prep work and give a DLL to folks who want very early tests. She is deliberately not writing docs for
  things that will change again.

## THE GATES SHE ASKED TO BE HELD TO

- **All public-facing prose is HERS** — READMEs, the forge description, anything a user reads. Review and
  suggest; do not draft.
- **Before the forge she reviews the code herself** and demonstrates she can update it unaided.
  `DECOUPLED-CULL.md` is Beta's walkthrough written for that purpose.
- Internal docs and coordination prose by agents are fine.
- **No GitHub push.** Commits authorised; she squashes and humanises before open-sourcing.
- Line lengths: 120 code, 80 comments.

## OPEN, NOT MINE

- **Beta**: whether the remaining unattributed builds are recoverable. `20260728-225956-marathon` came out
  as `e6cca83` — the *only surviving candidate*, not proven, since 7 artifacts have no deploy record.
- **Gamma**: `updateManual.deadCalls` is identically 0 across 205 windows while `bots.deadAwake` is > 0 in
  65 of them — twelve corpses on the Streets roster for six consecutive windows. Both call sites read the
  same `bot.IsDead` on `BotOwner`, so it is one expression answering differently in two contexts, not two
  theories of death. Until it works, **quote a bracket** bounded by `awakeCalls/frames` (over-counts) and
  `(awakeCalls − deadAwake)/frames` (over-corrects); corpses cost roughly half a live bot, suggestive only.
- **Also Gamma's**: `standByTransitions` counters live inside the disabled pump, so mod-off logs read
  `slept ≡ woken ≡ 0` structurally. That was one of my two supports for the Factory conclusion and it was
  vacuous; Factory stands on `bots.asleep = 0` from the census, which is valid.
- **UNOWNED AND POSSIBLY SHIP-BLOCKING — raised by Delta 2026-08-01, assign this before the A/B.** Delta's
  real line on the raid-1 UpdateManual ramp is not the ramp: it is that on `646c45dd` the **LEVEL started
  3× high as well**, which content does not explain. **If raid 2 reproduces that on the current build it is
  ship-blocker material and nobody owns it.** Raid 2 also needs QuestingBots installed, so the two are one
  errand. Also flagged by Delta as read only on that anomalous build: the honoured-fraction 1.00.
- **Delta retracts limb 2 of their own claim C.** `deadCalls ≡ 0` was read as "corpses never reach
  `UpdateManual`"; given Gamma's discrepancy that reading is **exactly tied** with "the counter cannot
  count", because one `IsDead` expression answers differently in two contexts. C survives on limbs 1 and 3;
  **treat the limb-2 sentence as unproven until Gamma's item closes.** Delta's note on their own miss is
  the general rule: they had "distrust an instrument that returns its success value when the mechanism is
  absent" two entries up, and did not apply it to the counter that was agreeing with them.
- **Warm-up insensitivity is proven FOR MEDIANS ONLY** (Delta) and will not transfer to the p99 guard.
- **Unowned**: 8 of 13 posted roles have never appeared in 25 logs — `bossKojaniy`/`followerKojaniy`
  (Shturman, and Woods was its one chance), `bossKillaAgro`, and all five Cultist roles. Spawn-chance
  gated, so replaying the marathon does not fix it.

## HOUSEKEEPING THAT BIT TWICE TODAY

The repo tree is shared and mid-round. `git add <dir>` swept Delta's in-flight scripts into my commit, and
Beta's commit swept my tells entry into his. Nothing lost either time. **Check `git status` and commit
explicit paths.** Commit messages with quotes or apostrophes break the shell — write the message to a file
in the scratchpad and use `git commit -F`.

## VERIFIED STATE AT WRITING

    harness/GO                bc90b76
    install md5               9c14f132254aac9b79aa3ca074a8923e   (unchanged)
    bin/Release               stamps aeec0d4, ahead of the install BY DESIGN
    deployed                  NOTHING new
    trees                     clean
    corpus                    F:\SPT\SPT4.0.13\...\Framesaver-logs  — 25 logs, 594 in-raid windows
