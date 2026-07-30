# Galaxy-brain ideas

Deferred, not forgotten. Named by Sophia, 2026-07-29, as a joke that turned out to have a
point: every idea we decide not to build right now currently goes into `COORDINATION.md`,
which is append-only and roughly half a megabyte, so **a deferred idea and a forgotten idea
look identical.** Same failure as exclusion-by-accident versus exclusion-by-decision, one
level up.

**What belongs here:** an idea with no owner and no date, that we would want back if it
became cheap or if the thing blocking it moved.

**What does not:** queued work (that has an owner), release tasks (those have a checklist),
and anything already declined *by decision* — a declined idea goes in `COORDINATION.md`
with its reason, and resurrecting it should cost re-reading that reason.

Each entry says what it is, why it is not now, what it would need, and **the hazard**,
because the hazard is the part that gets lost first.

---

## Leica: force player profile data for a run

**Sophia's, 2026-07-29.** A fixture supplies profile data for the run — gear, keys, quest
state — and **falls back to the real SPT profile when no fixture is present.** Two payoffs:
no gearing-up time before a test, and any run can guarantee the items a test needs. It came
out of Labs: that raid needs a keycard, so a Labs measurement is currently gated on
inventory rather than on anything we want to measure.

**Why not now:** nothing measured is blocked on it. Labs can be done in isolation or at the
head of a marathon run.

**What it needs:** the server-side profile load hook — profiles live under `user/profiles/`,
so this is Leica's territory rather than Framesaver's. Plus the same fixture discipline as
the spawn fixture: env-var path from the harness, hash logged by both sides, default off,
**absence positively recorded.** Her fallback-to-real-profile behaviour *is* the
absent-means-inert rule, already stated correctly.

**THE HAZARD, and Sophia's clarification makes it worse rather than better.** Leica can mutate
a `LocationBase` safely because `GenerateLocationAndLoot` hands back a **clone** — there is
nothing to write back to. **Profiles are persisted.**

Her testing install is fully separate from anything she plays with a persistent profile, so
**the hazard is not ours at all — it is entirely other people's.** That is the dangerous
shape, not the safe one: **a defect that cannot bite the developer is a defect that ships.**
It would never appear in our testing, because our install cannot produce it. Same structure as
the off-screen animator problem — any defect it causes exists only where we cannot observe it.

**And the mechanism is subtler than "do not call a save path."** The danger is not a write
*Leica* performs. It is a write **SPT** performs on data Leica changed: mutate the in-memory
profile at load, and the ordinary post-raid save persists the fixture's gear as though the
player had earned it. So declining to save is insufficient. The safe design needs a defined
revert point — snapshot before, restore after, or intercept the save — and that has to be
established **by reading the save path**, because it cannot be established by testing on an
isolated install.

**Sophia's model is better than the snapshot-and-revert above, and supersedes it.** The fixture
**wholesale replaces** the profile at every game launch, to that exact snapshot each time. No
persistence by default, and *"I don't expect these raids to get me any loot so like, whatever."*

Why it is better: **there is no revert step to get wrong.** The profile becomes a function of
the fixture, re-derived every launch, so it is idempotent by construction — the same shape as
the location fixture, where the base is regenerated per raid rather than mutated and restored.
It also makes the post-raid save harmless rather than something to intercept: SPT can persist
whatever it likes, because the next launch discards it.

**It trades a subtle hazard for a loud one, which is the right trade.** Snapshot-and-revert
fails as a *quietly contaminated* profile — hard to notice, hard to attribute. Wholesale
replacement fails as a *profile that is obviously gone*, on first use, doing exactly what the
tool says it does. **Loud destruction beats quiet corruption when both are possible.**

**So the control it needs is not a revert path, it is a ONE-TIME BACKUP** of whatever profile it
is about to replace. One file copy, and it converts *irreversible* into *recoverable* — which
is the whole difference for the person who ran it without reading the README. The README then
explains a backup rather than warning about a default.

---

## Spawn source on the bot ledger

Which of the three spawn systems produced each bot — boss spawner, wave scenario, or the
continuous trickle. Would make the structure we untangled on 2026-07-29 visible in data
instead of inferable, and a forced garrison would appear as boss-sourced, which is the
empirical half of the fixture provenance question.

**Why not now:** Beta scoped it and found **nine** `BotCreationDataClass` construction sites,
not three — the boss path alone builds three. With no way to prove the list complete,
`unknown` becomes the majority rather than the edge case, and a field that is right for a boss
and silently wrong for its escorts is worse than no field.

**What it needs:** all nine reach the funnel `BotCreationDataClass.Create`, which is already
patched. Each of the nine needs checking for an intervening `await` between its entry and its
`Create` call. Bounded work.

**Hazard:** the identity table is keyed by an object, and a table keyed by an object is a leak
unless something removes from it — the defect this mod exists to fix. Removal on consume in a
`finally`, cleared at raid start, and an orphan count emitted.

---

## Realised customisation IDs on the spawn line

**Delta's.** Log which garments each bot actually drew, not just which bot types were present.
Composition buys a **confounded** 9x variety contrast (type determines behaviour as well as
variety); realised IDs buy a clean instrument, because the draw is random given the type.

**Why not now:** the thing it would measure is deferred below, and the bot ledger shipped
hours before the idea arrived. Widening a log the day it lands is what we spent an evening
guarding against.

**What it needs:** the `botSpawn` line already fires per bot and already carries role, so this
is a field rather than a hook.

---

## Garment-variety manipulation: collapse an appearance pool

**Echo's (DRIP), 2026-07-29.** Clear a bot type's appearance pool and write exactly one
garment, then compare against a normal run. Composition, behaviour, aggro, group size and
stand-by eligibility all held fixed, so **only variety differs** — realised distinct garments
go from ~7.84 to 1, a **~7.8x manipulation** where natural variation offers 15%. Needs no
DRIP: the write path is the bot template post-DB-load, the same class of mutation Leica
already performs, and vanilla PMC pools are 18/16.

**Why not now:** priority, not plausibility. The outcome's between-leg noise floor is
**0.680-0.740 ms** against a **0.549 ms** gap, so ~28 raids would be needed for a between-raid
design — and the rendering component it targets does not survive standardisation anyway. It is
recorded as *testable, cheap, and not next.*

**Control that comes with it:** pinning changes *which* garment as well as how many, so repeat
with three or four different pins. A stable delta means variety; a delta that tracks the
garment means it was that texture, and the hypothesis is wrong informatively.

---

## Stepped animator instead of culled

`animator.enabled = false` plus a manual `animator.Update(accumulatedDt)` every Nth frame,
rather than `CullCompletely`. Converts the correctness failure into a **latency** cost: the
state machine still advances, so transitions complete, events fire, and a mid-vault bot
finishes its vault late instead of never.

**Why not now:** ceiling is ~0.2 ms, and gated on off-screen it reaches the same population
`CullCompletely` already reaches — so it buys correctness rather than size. It only becomes
worth anything if something creates a large awake-and-far population.

**Hazard:** `MovementContext` consumes `PlayerAnimatorDeltaPosition` as displacement, so a
manual step could double-apply or drop displacement. A silent displacement drift is the
expensive failure, and the intervention only acts off-screen, so play-testing has near-zero
power against it by construction.

---

## Step in for QuestingBots' performance profile

**Sophia's, 2026-07-29.** We already take back the `CanDoStandBy` flag QuestingBots clears. If
the deferral default goes away, the same reasoning might extend further — QuestingBots' stated
reason for clearing it is a defect in *vanilla's* stand-by check, which our replacement does
not have.

**Why not now:** downstream of the deferral decision, which is downstream of a behavioural
test that has not run.

---

## Leica capability 2: reproducible population

A blanket rule over a `BossName` rather than a per-entry match: *for every entry named
`pmcUSEC` or `pmcBEAR`, set chance 100 and escort amount n.* Deterministic, and immune to SPT
changing the wave count between versions — Lighthouse carries 14 injected PMC waves and Streets
12, several sharing a zone string, so they are **not** uniquely addressable by `(name, zone)`.

**Why not now:** Sophia asked for the forced garrison, which is capability 1. This one would
retire a measurement problem carried through four attempts, so it is the strongest candidate
here.

**What it needs:** no new mechanism — a match-all mode over the same list Leica already walks.

---

## Map edits for performance

Sophia, 2026-07-30: "a decent case to be made for seeing if we COULD do map edits to help with
performance issues."

**Why it is a real candidate rather than a whim.** `FinishFrameRendering` is **3.8 ms, 24.4% of
the Lighthouse frame**, and it is **not bot-scaled** - Spearman against awake bots is -0.111 and
+0.076 across two raids, against the animator's +0.681. So it does not respond to anything a
performance mod can do to AI, and its owners are scene content and material variety. That makes
geometry, renderer count and material count the only levers that reach it.

**Why not now:** it is a content project rather than a code one, it needs an asset pipeline this
project does not have, and shipping map edits is a different distribution and compatibility
problem than shipping a plugin. Also downstream of Echo's mipmap ride-along, which would say
whether variety costs CPU at all.

**What it needs first:** the ride-along result. If material variety moves CPUBusy, content is
implicated and this becomes worth costing. If only GPUBusy moves, we have 2.24x GPU headroom and
the whole avenue is uninteresting.

---

## Blanket-patch every MonoBehaviour LateUpdate for per-class timing

Sophia, 2026-07-30, from an experiment she ran years ago and cannot recall the outcome of: at boot
and on a cadence, Harmony-patch every active `MonoBehaviour::LateUpdate` and record class plus
timing. She flagged the risk herself - that it lands in the same pit as the Unity profiler,
inflating managed method time and obscuring real cost.

**It is a worse pit than the profiler's, and in a specific way.** The profiler inflates managed
relative to native - a LEVEL error, and it reports call counts so you can normalise. Harmony
overhead here is paid **per call**, so a type with 500 cheap instances absorbs 500x the overhead
while a type with 1 expensive instance absorbs 1x. **It distorts the RANKING, not the level - and
the ranking is the entire purpose.** It would systematically over-attribute to numerous-cheap
classes and under-attribute to few-expensive ones, which is backwards from what the exercise is
for.

**And the prize is smaller than the phase headline suggests.**

    ScriptRunBehaviourLateUpdate     1.500 ms (raid 1)   1.038 ms (raid 1.5)
    already attributed to playerLate 0.781      52%      0.444      43%
    UNATTRIBUTED remainder           0.719 ms            0.594 ms
    for scale, the animator          3.519 ms            1.809 ms

So the target is **0.6-0.7 ms**, in a phase already half-attributed, against an animator 2-3x
larger. Whether the instrument costs more than that depends entirely on calls per frame, which
**we do not know** - at 500 calls and 200 ns overhead it adds 0.10 ms, at 2000 it adds 0.40, at
5000 it adds 1.0 and costs more than it measures.

**The cheap step that comes first: COUNT, do not time.** An instance census by type touches no
call path and gives the denominator plus the candidate list. Then patch 5-10 types selectively
rather than hundreds.

**And the control that makes timing-by-patch usable at all: a NO-OP patch of identical shape on
the same types.** Diff the instrumented run against the no-op run and the overhead is measured
rather than assumed. That is make-it-fail-on-purpose applied to an instrument's own cost, and
without it the numbers cannot be corrected for the thing that produced them.

**Why not now:** the prize is under a millisecond, the animator and the script Update phase are
both larger and cheaper to reach, and re-patching on a cadence would generate its own hitches
inside the tail we are trying to measure.
