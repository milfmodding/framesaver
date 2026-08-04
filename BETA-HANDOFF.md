# Beta handoff — for a cold reboot

Written 2026-08-03 for a Beta who has never seen this repo. `COORDINATION.md` at `66fa723`
already records what shipped. This file is the other half: **why things were ruled out, which
code I would not touch without a raid, and what I believe but could not prove.**

A conclusion can be re-derived. A ruling-out cannot — nothing in the tree records the four
hours that produced it, so the next person re-runs those hours or, worse, re-proposes the idea.

---

## 0. The one live constraint, before anything else

**`bin/Release` currently contains the decoupled-cull flag.** The coupled A/B
(`protocol-anim-cull.ini`) needs its data **before** anything is deployed for the reload test.
Its registered prediction is only valid against a coupled build. Deploy first and you have
destroyed the A/B build and will run the protocol twice.

This is the first thing a reboot will break, because deploying is the obvious first move and
nothing in the build system stops it.

---

## 1. Method — the part I would keep if I could keep only one thing

**I was looking hard at all three of my own defects and found none of them.** Gamma found the
`windowSec` flag, Alpha's build-recovery request exposed the extractor, Gamma read the entry
above the one I sent them to. Not a claim about care — a structural one, and the same argument
as reviewer-separate-from-builder arriving from a different direction.

Three practices, in the order they earned their keep:

1. **Ask a tool a question whose answer comes from the far side of the join it exists to make.**
   Three extractor defects survived crash tests, code review and my own re-reading, and all
   three died within minutes to one such question. Not "a task with a known answer" — the
   answer has to arrive from the *other* side, or you are testing the model against itself.

2. **Falsify every check.** Break something so it fires; watch the message. Today's instance:
   `attribute-log.py` has four outcomes and I exercised all four, and the *ambiguous* fixture
   is what revealed that the whole attribution rests on a single config key (§4).

3. **Disclose defects precisely enough that the next person can check the neighbourhood.**
   Cheapest producer of catches all day. "Fixed a bug in the extractor" produces nothing;
   naming the file and the field sends a reader past the thing next to it.

And the failure mode those exist against: **a check built from your own model tests the model,
not the world.** My test suites were green through every one of the defects above.

---

## 2. Rulings — things that are settled, and will be re-proposed if this section is lost

Each of these cost real time. None is recoverable from the code.

**`EFTHardSettings.AnimatorCullDistance` is not an alternative lever.**
`AnimatorCullingMode.CullCompletely` appears **nowhere in Assembly-CSharp**. Vanilla writes only
`AlwaysAnimate` or `CullUpdateTransforms` (`Player.cs:1526`), and the setting has exactly two
readers. It cannot produce `CullCompletely` at any value. Turning it up is not a cheaper version
of what we do — it is a different thing.

**`Force fast body animator` is deleted, not disabled.** Sophia: *"enabling it was a first draft
we did at the very beginning, and it completely breaks the game."* I had proposed an interlock —
"turn the cull off if you want the fast animator" — which was wrong on its premise: an interlock
offers a route to a broken client. When the answer is "this breaks the game", the design question
is not how to sequence it.

**`Base` is closed.** Older SPT version. Not a control, never pooled. My "no-AI-mods control"
framing was a confound and I withdrew it: the two installs differ in SPT version, mod stack
*and* Framesaver build, so any difference has three candidate causes.

**Cross-raid A/B cannot resolve anything here.** Score alternating arms inside one raid.

**Factoring a sparse rate into two parts does not remove the sparsity.** `>=250` as
(arrival rate of `>=150`) x (fraction exceeding 250) looks like a decomposition into
better-estimated parts. The severity fraction is 3 of 20 — *the same three events*. Recorded in
`COORDINATION.md` because it will be proposed again; it looks clever every time.

**Attenuation, not contradiction.** The 0.091 vs 0.211 ms/bot disagreement is an
instantaneously-sampled regressor against a window-aggregate outcome. It is a bracket. Do not
"fix" either estimator; the paired protocol design removes the question instead.

---

## 3. Fragility — what I would not touch without a raid to verify

Below what the comments say. This is the knowledge that comes from having broken them.

### `SleepingBotAnimatorPatch.cs` — the one that nearly deleted itself

`CullEveryBot` is called from `Postfix` and is deliberately **not** folded into `ApplyIfSleeping`.
That method's `bool` is what the LateUpdate and world-tick prefixes skip on. A decoupled cull
answering `true` for every bot would skip `Player.LateUpdate` for the whole roster — and
`LateUpdate` holds the **only call site of `VisualPass`**, which is the thing that applies the
cull. The two features would delete each other on the first frame, silently, and every
performance number would look *better*.

The general shape, which is what to carry: **a predicate reused as a control-flow signal is a
trap.** If a function's return value gates something else, adding a caller changes that gate.

### The seven suppressing prefixes

`AICoreControllerUpdatePatch`, `AsyncDrainPatch`, `AsyncWorkerFixedUpdatePatch`,
`BotStandByUpdatePatch`, `SkipSleepingPlayerLateUpdatePatch`, `SkipSleepingWorldTickPatch`,
`SleepingBotStandByPumpPatch`. A **bool-returning** Harmony prefix can suppress the original; a
void one cannot. Changing a prefix's return type is a one-character diff that changes control
flow for the whole game, and reads as a refactor.

There is a golden-list test. **I wrote that list from memory with five entries; there are seven,
and the check caught its own author inside a minute.** That is the check working, and it is also
the reason not to trust this paragraph over the test.

### Two patches gating on the same flag

`BotStandByUpdatePatch.Wake()` had an unconditional `BotState` restore that is **unreachable**
for NonActive+paused bots, because `SleepingBotStandByPumpPatch`'s prefix bails on the same flag.
The comment claimed otherwise until `6b9e880`.

Reflex: **when two patches gate on one flag, one of them has dead code and the comment will not
know.** Trace the other patch before believing a comment about reachability.

### `ModCompat` in `Awake`

`CORPUS` forbids reading `ModCompat` from anything running in `Awake` — load order is not
guaranteed and the answer you get is "no mods". Not enforced by the compiler.

---

## 4. The unattributed builds — now written down

**This was the item most at risk and it is fixed.** `analysis/attribute-log.py` runs the
derivation that identified `Framesaver-20260728-batch-e6cca83-4b839995.dll` (`e6cca83`) as the
binary that wrote `20260728-225956-marathon`. It reproduces, and its docstring carries the
reasoning rather than the answer.

Two things I did not know before writing it, both from exercising the branches:

- **The header line alone is enough**, and inside it `deferToAiMods` eliminates 20 of 21
  candidates by itself. The attribution is not a broad statistical match — it is a two-sided
  bracket on shipping dates (no `commit` key ⇒ built *before* that field shipped;
  `deferToAiMods` present ⇒ built *after* that flag shipped) that is unique only because the two
  dates are adjacent. Real, and thin. Say so when quoting it.
- **A fifth false-absence class in the extractor**: the two-character minimum means `n`, `t`,
  `x`, `y`, `z` are absent from every record while appearing in every log. Recorded in
  `beta-build-fields.py`'s `semantics`; callers must drop sub-two-character names from any join
  rather than reading them as structural.

Related and separate: `build-provenance.py` reads a commit **out of a binary**;
`attribute-log.py` identifies a binary **from a log**. Neither answers the other's question.

---

## 5. Deploy folklore — the steps whose reasons are not in the build file

- **Two playable installs. Only `F:\SPT\SPT4.0.13` is ever deployed to.** Name the install in
  every announcement. Never assume a log directory is *the* log directory.
- **Announce four things on every deploy:** md5 (`bin/Release` ↔ `plugins` must match),
  TimeDateStamp, source files changed, and **which install**.
- **`bin/Release` is normally AHEAD of the install, by design.** Compile-only builds happen
  constantly for the test suite; the install changes only on an explicit `-p:Deploy=true`. So
  divergence is the resting state and equality is the exception. The hazard is reading
  `bin/Release` as "what ran" — that cost four round-trips to a stale-read once. *An artifact
  does not have to be deployed to cause that confusion; it only has to exist and differ.*
- **Commit, then build, then record.** SourceLink stamps HEAD *at build time*, so a build from a
  dirty tree carries the same stamp as a clean one — the `403b1aeb` artifact reports `3bf008f`
  and its `Telemetry.cs` matched no commit. Ordering makes the correspondence structural instead
  of a matter of timing.
- **Beta does not move `harness/GO`.** The deployer records what shipped; the reviewer records
  what was approved. Read `GO` from disk, never quote it from memory.
- **Never leave the install disagreeing with the gate.** Restore from `artifacts/` — never
  rebuild. A rebuild produces a different md5 for the same source and destroys the evidence.
- **Never `git add -A`.** Three other agents have uncommitted files in this tree. Name paths.
- **`COORDINATION.md` is append-only.** Corrections are strikethrough in place, so the wrong
  version stays visible next to the right one.

**And the one that generalises past this repo:** the deploy gate I added refused *every* deploy,
including legitimate ones, because it needed `DependsOnTargets="InitializeSourceControlInformation"`.
**The falsification passed and so did the control** — I found it only by running a real deploy.
When you add a gate, the negative control (a deploy that *should* succeed) is the test that
matters; the positive one tells you almost nothing.

---

## 6. Hunches — believed, not proven, and therefore nowhere else

Flagged as such because they are the highest-value thing here and the easiest to mistake for
findings.

- **I would bet against the reload question resolving benign — maybe 60/40.** The vanilla
  precedent does *not* cover us: `CullUpdateTransforms` already freezes transforms for invisible
  bots, but it does **not** stop state-machine evaluation, and `CullCompletely` does. Animation
  events are *enqueued* by state callbacks and drained separately, so a frozen state machine
  means the drain finds nothing. The cheapest reason to suspect it: **BSG never once used
  `CullCompletely`**, anywhere. That is not evidence of a defect, but a mode this useful going
  unused by the people who wrote the game wants an explanation, and "they never noticed" is the
  optimistic one.

- **The cull's saving is a function of what fraction of bots is off-screen, not of bot count.**
  Unity decides eligibility per renderer, per frame. If that is right, the Lighthouse gate is
  not incidental — an open map with long sightlines is the *worst* case for us and the correct
  one to gate on. Untested, and it predicts something checkable: the saving should track
  off-screen fraction better than it tracks roster size.

- **`bots.animCulledEngine` cannot detect a latch in the current protocol run.** Designed out,
  not measured away — with stand-by off the marked set is empty by construction. Recorded in
  `protocol-anim-cull.ini`, repeated here because it is exactly the kind of caveat that gets
  dropped when a number is quoted.

- **Low confidence, worth one hour if someone has it:** the decoupled cull may make the
  posted-role exemptions and most of `COMPATIBILITY.md`'s guards unnecessary rather than merely
  unused, since every one of them is about stand-by. If that holds, the mod gets smaller — which
  is the direction Sophia wants — but it is an argument I have not tried to break.

---

## 7. Where the reboot will actually fail — a prediction, not a summary

The exit question was *"what did you know that will not survive?"*, and the honest structural
answer is that **the outgoing agent is the worst-placed party to answer it.** Tacit knowledge is
invisible from the inside; that is what makes it tacit. Everything above is what I could *see*
that I knew, which is a biased sample of what I know, in exactly the direction that matters.

So the more useful thing I can leave is a prediction of where a fresh Beta goes wrong first:

1. **Deploys before the coupled A/B has its data.** §0. Most likely failure, and it costs a raid.
2. **Reads `bin/Release` as "what ran".** §5. Second most likely, and it wastes an evening
   rather than a raid.
3. **Quotes a number without its population.** Every measurement error we had was a population
   error — *"of what?"* before checking arithmetic. Arithmetic review caught none of them.
4. **Trusts this file over the tests.** I got the golden list wrong from memory in the same
   session I wrote the test that caught it. Where this file and a check disagree, the check wins.

Test the prediction rather than the summary: if a fresh Beta avoids those four, the handoff
worked, and if they do not, the gap is here and not in them.
