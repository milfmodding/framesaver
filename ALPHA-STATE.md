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

**⚠ THE CONSTRAINT THAT USED TO BE HERE WAS BACKWARDS. Beta found it 2026-08-01; I had relayed it four
times including to Sophia, and it survived into a handoff as the item most likely to break.**

It read: *`bin/Release` contains the decoupled-cull flag, so the moment Beta deploys the A/B build is
gone — A/B needs its data first or we deploy twice.* **The truth is the reverse: the A/B needs a deploy
to be readable at all.**

`protocol-anim-cull.ini`'s check #1 reads **`animCulledEngine`**, the field that certifies *arm delivery*
— that the cull arm reached the engine rather than only the config. **It does not exist in the installed
build.** Verified three independent ways, each with a positive control:

- UTF-16 literal **absent** from the installed DLL (`bc90b76`), **present** in `bin/Release` (`aeec0d4`).
  Control: `animCulled` and `animCulledOffScreen` present in both, so the encoding and the probe work.
- **0 of 594 in-raid windows across 25 logs carry it.** Control: `animCulled` in 594 of 594.
- Introduced in `86a13bb`, after the gate — as was the protocol itself (`919204c`).

Check #3 (`animCulledOffScreen`) *is* installed and check #2 (`bots.awake`) is fine, so it is one of
three — but it is the one that distinguishes **"the cull worked"** from **"the config flipped and nothing
happened."** Without it the A/B falls back on `animCulled`, which is *our intent*, which is the
instrument-reads-intent flaw `animCulledEngine` was written to fix. **Running the A/B on the installed
build yields a clean-looking, uninterpretable result.** Deploying twice was never the risk.

**SECOND HAZARD ON THE SAME BUILD.** The installed build still carries the user-facing setting
**`Force fast body animator`** — removal is `299fd86`, also after the gate. Verified at descriptor
resolution: the string is present in the installed DLL and absent from `bin/Release`. The protocol's
reasoning explicitly assumes it is gone. Live config has it `false`, so it is **not armed**, but on this
binary a stray flip silently voids the cull *and* the inert-detection guard that would catch it
(`aeec0d4`) is also undeployed. **Two guards for that failure, neither in the running binary.**

**THE ORDER, RESTATED.** Build a candidate off `aeec0d4`; **Delta reviews the coupled-path diff before it
ships** (`SleepingBotAnimatorPatch.cs` is +304 lines between the gate and `aeec0d4`). Then the A/B, then
the reload test. Cost of doing it right: one review, no raid. Cost of not: the A/B runs and its
arm-delivery check has no instrument.

**Beta will not certify behavioural equivalence on the coupled path and has not claimed it.** The
decoupled flag defaults off and the fast-animator removal deletes a path Sophia says breaks the game, so
equivalence is *plausible* — a review conclusion, not a deploy announcement. `f218743` registered that
the prediction holds only for a **coupled** build; **whether that registration survives a new binary is
Sophia's call.**

**THE FIX IS A COMMAND, NOT A RESOLUTION. Run this before arming any protocol:**

    python analysis/probe-symbols.py --key <installed dll> <every field the readability checks name>

Exits **1** if any field is missing, 0 if all present — verified both branches. **It already existed,
written 2026-07-28 for exactly this class of question, four days before it was needed.** Neither Beta nor
I thought to point it at a protocol. No new code was ever required.

**WHY IT WENT UNCHECKED, in Beta's framing, which is better than the one this file used to carry.** The
constraint was a **join**: a claim about a protocol document (mine) welded to a claim about binary
contents (Beta's). Each of us verified our own half, correctly. **Nobody owned the join, and clean
ownership is what made it invisible — the crisper the split, the more natural it is for each side to
treat the other's half as settled.** That is a property of how the work was divided, not of relaying or
of believing, and it will recur with different domains and the same shape.

**AND THE JOIN IS THE ADJUTANT'S BEAT.** *Arbitrate across boundaries* is duty three of the role, so a
join nobody owns is mine by definition. Beta is right that the artefact should carry the mechanism rather
than the apportioning — *a rebooted pair reading "the adjutant failed to check" will resolve to be more
careful, which does not work.* But a mechanism with no owner is how the join went missing in the first
place. **Both: run the probe, and the adjutant owns every claim that spans two domains.**

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

## THE ODDS, BECAUSE THE TABLE ABOVE IS A BINARY AND THE BINARY IS LOSSY

**Added at Gamma's instruction, 2026-08-01, and they were right that this was the one thing missing:**
*a rebooted Alpha will read defensible/not-defensible as the resolution rather than as the current line
— and unlike a conclusion, a betting line has no re-derivation path.* Evidence can be recomputed from
the corpus. Odds cannot. So these are the odds, and they are the most perishable thing in this file.

| claim | my line | note |
| --- | --- | --- |
| The cull is the mechanism, as an **ordering** | near-certain | Two routes agree. Delta stakes their seat on the divisor identity and ~90% on the ordering itself. |
| The 2.8× leverage is a property of **the transition measured**, not a rate | high | Extrapolating it onto the residual overshoots; the residual includes player animation, never cullable. **Most misusable number we hold.** |
| 100 fps on Streets by this mechanism | won't happen | Sophia has accepted this. |
| The within-raid A/B comes in **smaller** than the between-marathon figures | likely, unsized | Every gain figure compares different days, routes and builds. **The optimism in this file is not discounted for it.** |
| Reserve's regression is real, not artefact | I'd bet on it | Sign replicates across two instruments over different populations. **No mechanism, therefore no finding.** |
| The decoupled cull passes the reload test | **~45/55, moved down** | See the disagreement below. Was 60/40 in favour. |
| `deadCalls` is a property of `IsDead`, not of our code | Gamma's 70/30 | Six code-side explanations dead, zero property-side touched. |
| `p999`/`p99` ever separate an arm at 30 s | Gamma bets against | Kept for continuity, not expected use. |

**THE ONE PLACE THE TEAM'S TWO CLOSEST READERS DISAGREE, REGISTERED BEFORE THE TEST:**

> **Beta is ~60/40 AGAINST the reload test resolving benign. I was ~60/40 FOR.**

Beta's reason is better than mine and I have moved to **~45/55**, i.e. roughly a coin flip leaning
against. The argument: the vanilla precedent everyone reaches for is `CullUpdateTransforms`, which
freezes transforms for invisible bots and **does not stop state-machine evaluation** — and
`CullCompletely` does. Animation events are enqueued by state callbacks and drained separately, so the
precedent does not cover our case. Plus the cheapest signal available: **BSG never used
`CullCompletely` anywhere in Assembly-CSharp**, and "they never noticed" is the optimistic reading of
that.

**Do not let this resolve into one number before the raid.** Two independent lines in opposite
directions is the honest state, and per Delta: *a model the whole team shares is invisible to every
reviewer, so registered predictions outrank review.* This is the registration.

**Beta's second bet, checkable and consequential if true:** the cull's saving tracks **off-screen
fraction**, not roster size, because Unity decides eligibility per renderer per frame. If that holds,
Lighthouse is not an incidental gate — an open map with long sightlines is the **worst case** and the
right thing to gate on.

## WHERE A FRESH ALPHA GOES WRONG FIRST — ranked, and falsifiable

**Beta's format, and it is better than the inventory the exit interview asked for:** *four predictions
is a test; four inventories is a filing cabinet.* If a rebooted Alpha avoids these, the handoff worked.
If they hit one, the gap is in this file and not in them.

1. **Quotes a per-map fps gain.** The withdrawn figures are arithmetically recoverable from the corpus
   and read as findings. They are between-marathon, single-leg against single-leg. **Withdrawn, not
   caveated.**
2. **Reconciles the estimator disagreement into one coefficient.** 0.09–0.34 is a bracket with signable
   biases. Resolving it feels like synthesis and is the signature failure of this seat.
3. **Trusts an undated sentence over a dated artefact** — including their own memory files. This one
   already happened, twice in one day, once while I was describing it to Sophia as a hazard.
4. **Retracts an instance and leaves the pattern standing.** I fixed occupancy-pricing on the cull side
   and left it on the gate side, same document, four hours apart. Delta caught it. **After any
   retraction, grep for the sentence-shape, not the sentence.**

## THE THREE NUMBERS MOST LIKELY TO BE QUOTED WRONG

1. **`aiTotal` IS NOT WHAT STAND-BY GATES.** It is `BotsController.method_0` and does not contain
   `BotOwner.UpdateManual` (`Telemetry.cs:1337` says so). Every "AI is N% of frame time" figure taken from
   it describes a slice stand-by does not touch. The right field is `updateManual.awakeMs / awakeCalls`
   ≈ **0.011 ms per awake bot**, against paused at 0.0002–0.0005.
2. **`bots.*` are INSTANTANEOUS samples** at window close (`CountBots`, one call site, `Telemetry.cs:1314`).

   **THE GENERAL RULE, from Gamma 2026-08-01 — this supersedes memorising individual fields.**
   `Telemetry.ResetWindow()` (`Telemetry.cs:2145`) **is the manifest.** Three categories, not
   interchangeable, and checkable in one command that does not require trusting anybody:
   `grep -n 'ResetWindow()\|\.Reset()' Telemetry.cs`
   - named in the reset block → **window aggregate**, covering the frames since the last flush
   - computed in the emit path from live game state → **instantaneous point sample at window close**
   - **a static with no reset partner → session-cumulative**, whose per-window meaning is a *difference*
     nobody computes for you

   **The third row is the trap and it has already bitten.** `animCulled` was session-cumulative with no
   raid reset, which is the whole reason it exceeded the bot population from raid 2 on. `CORPUS.md`
   records that as a data defect; it is **a classification error wearing a data defect's clothes.**
   And the corollary that costs statistics rather than sanity: **category is a property of storage, not
   of name.** `awakeCalls` and `bots.awake` read as one quantity in two units and are an aggregate and a
   point sample — regressing one on the other attenuates toward zero, so **the failure mode is a real
   effect reported as a null.** That is exactly `alpha-animator-slope.py`.
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

- **Beta — CLOSED, and the attribution is THINNER than this file used to say.** `analysis/attribute-log.py`
  (`3e46ffb`) now reproduces the identification of `e6cca83` for `20260728-225956-marathon`, exits non-zero
  on ambiguity, and carries the reasoning rather than the answer. **Writing it down changed what Beta
  believed about it**, which is the argument for asking: it is *not* a broad statistical match. The header
  line alone suffices, and within it **`deferToAiMods` eliminates 20 of 21 candidates by itself.** The
  identification is a **two-sided bracket on shipping dates** — no `commit` key means built before that
  field shipped, `deferToAiMods` present means built after that flag shipped — and it is unique only
  because those two dates happen to be adjacent. **Real identification, and thin. Anyone quoting it says
  so.** Build time eliminates nothing and is the weakest leg: `mtime` is the artifact file's last-write
  time, not the PE TimeDateStamp, so for a copied artifact it is an upper bound.
- **Also Beta's, affecting anyone reading `build-fields.json`:** a **fifth false-absence class** — the
  extractor's two-character minimum means `n`, `t`, `x`, `y`, `z` are absent from every record while
  appearing in every log. Named in `semantics.fields` and the JSON regenerated, output diffed on disk
  rather than trusted.
- **Gamma**: `updateManual.deadCalls` is identically 0 across 205 windows while `bots.deadAwake` is > 0 in
  65 of them — twelve corpses on the Streets roster for six consecutive windows. Both call sites read the
  same `bot.IsDead` on `BotOwner`, so it is one expression answering differently in two contexts, not two
  theories of death. Until it works, **quote a bracket** bounded by `awakeCalls/frames` (over-counts) and
  `(awakeCalls − deadAwake)/frames` (over-corrects); corpses cost roughly half a live bot, suggestive only.
- **Also Gamma's**: `standByTransitions` counters live inside the disabled pump, so mod-off logs read
  `slept ≡ woken ≡ 0` structurally. That was one of my two supports for the Factory conclusion and it was
  vacuous; Factory stands on `bots.asleep = 0` from the census, which is valid.

  **AND THE DEFECT IS WORSE THAN THAT — THE BLOCK IS SPLIT ALONG SUB-COUNTER LINES** (Gamma, verified at
  source 2026-08-01). `woken`/`wokenMs`/`slept`/`sleptMs` are **our pump**
  (`BotStandByUpdatePatch.cs:222,389`) and are identically zero when it is off; `diedAwake`/`diedAsleep`
  are **ungated** (`BotLogPatches.OnDead:242`) and live in every arm. **So a reader sanity-checking the
  block sees nonzero numbers and concludes the zeros are real — the liveness check passes on a different
  sub-counter, inside one JSON object where nothing marks the six numbers as having different
  provenance.** My vacuous support was the visible cost; this is the mechanism that produces the next one.
  General form: **a counter living inside the feature it measures cannot distinguish "feature off" from
  "feature on, nothing happened."** `AwakeAge` is the counter-example and the reason it is fixable — its
  spans are driven from the `StandByType` *setter*, so they see every transition whatever caused it.
- **`deadCalls`: THE NEXT MOVE IS NOT ANOTHER LOG QUERY** (Gamma). Six mechanisms are eliminated,
  including Gamma's own leading hypothesis (Unity fake-null on a destroyed `BotOwner`, killed because the
  census applies the same null guard at `Telemetry.cs:1801` and would be blind too, so `deadAwake > 0`
  refutes it). What remains is a property of `BotOwner.IsDead` itself. **Every instinct says query harder
  and the corpus has said everything it can** — decompile `BotOwner.IsDead` in the 4.0.13 assembly, or
  add a second death predicate *beside* `deadCalls`, never instead.
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
- **THE TAIL: WITHDRAWN AND REPLACED (Delta, `3e24631`, `analysis/delta-stall-bundles.py`).** My
  *"13 of 13 stalls co-occur with a bundle load"* was a vacuous filter — `bundleLoad` is a non-empty dict
  on every line, base rate **594/594**. **Do not let "the tail is streaming, not AI" reach testers; it is
  unsupported, and so is "our mechanism cannot fix it."** At frame resolution: **zero of twenty** spike
  events magnitude-matched to a load. What the tail actually is, by dominant child phase:
  1. **`Update/ScriptRunBehaviourUpdate` bursts, 225–471 ms, eight events, mostly mod-off.** Main-thread
     script — **which is exactly where bot AI lives**, so "not AI" is not merely unsupported: the dominant
     family sits in AI's own phase and is **undecidable at current instrument depth.**
  2. The known Streets out-of-loop family — four events plus one Lighthouse, sync counters ~0.
  3. **NEW: `TimeUpdate/WaitForLastPresentationAndUpdateTime`, 223–359 ms, three events**, Shoreline and
     Reserve mod-off. Present-wait, GPU/swapchain-shaped, and **no CPU mechanism of ours addresses it.**
  4. One `ScriptRunDelayedTasks` event on Reserve, 228 ms, in the single window that also carries loads —
     the only place a streaming story has any purchase, and it is one event.
- **COMMISSIONED, does not exist (Delta grepped first): a worst-single-call max inside `updateManual`,
  beside the existing sum.** Delta's own ceiling caveat is why — **mean pools cannot bound single-frame
  tails.** A 470 ms `UpdateManual` burst moves a 30 s window's `awakeMs/frames` by ~0.016 ms, i.e. is
  invisible. **The ceiling argument and the goal-2 tail are independent questions and nothing in any
  docket bounds AI's contribution to spikes.** With that one field, family 1 becomes decidable in one
  marathon.
- **FOR BETA — POSSIBLY OURS, AND UP TO 708 ms.** Outside the gate population, **nine further stalls
  ≥ 250 ms sit at exactly each map's first window boundary** — spike `t` equals the previous window's
  close, once per map, never at later boundaries. Warm-up excludes them so no gate number moves, but the
  alignment pattern-matches **our own first-window-close path (census + flush)**. One falsification
  settles it: **log the flush duration.**
- **GOAL 2 NEEDS RE-PHRASING AND THAT IS SOPHIA'S CALL.** The tail exists **mod-off**: twelve of twenty
  kept events are in the mod-off marathon (Woods, Reserve, Shoreline, Streets), so **vanilla violates an
  absolute 250 ms gate on at least four maps** and the criterion is unmeetable as stated. It needs a
  **vanilla-relative** phrasing. Lighthouse, which binds, carries four mod-on events — three on the
  unidentified `225956` build, one on `646c45dd`. **Whether our mechanism threatens or helps the tail is
  established in neither direction.**
- **MINE, BECAUSE IT SPANS EVERY DIRECTORY — the exit-2 collision.** 86 exit-2 sites across `analysis/`
  and `harness/`; 26 files print a `REFUSED` marker; **18 return 2 without a literal `REFUSED` token**,
  spanning every owner. **STATE THE POPULATION EXACTLY: that is "lacks a distinctive token", NOT "prints
  nothing".** I wrote the stronger version first and Beta caught it — `probe-symbols.py` prints on both
  its exit-2 paths, so *"prints nothing"* is unmeasured.

  **The real defect is that output does not separate them either.** `probe-symbols.py` refusing to read a
  DLL prints `! [Errno 2] No such file or directory: 'F:/SPT/nope.dll'`; CPython failing to find the
  script prints `can't open file '...': [Errno 2] No such file or directory`. **Same code, same errno
  text, opposite meanings** — one is a real refusal, the other is the script never running. A caller
  asserting on output is fooled as thoroughly as one asserting on the code.

  **FIX, decided and registered by Delta (`9c62ac0`): a refusal is ALWAYS BOTH HALVES — first output line
  `REFUSED: <reason>`, then `sys.exit(86)`.** Each half alone has a measured collision (the tokenless 18;
  the errno twins above) and neither can collide alone. 86 sits in the unclaimed 79–125 band, nothing
  wraps to it, and *"eighty-sixed"* means refused service — which is the tiebreak that matters, because my
  own census proved **a rule that must be remembered fails on its own author within the hour.**

  **BUT 86 DOES NOT FIX THE TRAP BETA AND I FELL INTO, AND THEY ARE TWO DEFECTS, NOT ONE.** Measured here
  tonight in PowerShell 5.1:

      python r86.py                            -> 86
      python r86.py | Select-Object -First 1   -> -1     EARLY-TERMINATING
      python r86.py | Select-Object -Last 1    -> 86
      python r86.py | Out-String               -> 86
      python r86.py | ForEach-Object {$_}      -> 86
      python r86.py | Where-Object {$true}     -> 86
      Git Bash:  $? through a pipe -> 0 (tail's);  ${PIPESTATUS[0]} -> 86

  **Delta and Beta are both right about different pipes.** 86 survives ordinary pipes verbatim, so Delta's
  end-to-end claim holds; Beta's −1 came specifically from `Select-Object -First 2`, which **stops the
  upstream process**, and **no exit code of any value survives that.** So:
  - **Defect 1** — refusal indistinguishable from failure-to-run. **Fixed by 86 + the token.**
  - **Defect 2** — an exit code destroyed by the *reader*. **Not fixed by any code.** Rule: **capture the
    status before any pipe**, or use `${PIPESTATUS[0]}` / `$LASTEXITCODE` with no early-terminating cmdlet
    in between. Never `-First`.

  Third time today that *"of what?"* was the whole answer, this time about a **shell behaviour** rather
  than a data population.

  **Migration recorded, not executed** (Delta's order): the tokenless 18 first, one owner per commit;
  `check-modoff.py`'s documented exit-2 contract moves only with its callers in the same commit; new
  scripts born conforming. **Prose hazard:** the census found *86 exit-2 sites* and the new code is *86*.
  Unrelated. Never write those two numbers in one sentence.
- **BEFORE ARMING ANY PROTOCOL** — `probe-symbols.py --key <installed dll> <every field its readability
  checks name>`. This is in the procedure rather than in anyone's memory on purpose; see the A/B section.
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
