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

**THE HAZARD, and it is worse than the spawn fixture's.** Leica can mutate a `LocationBase`
safely because `GenerateLocationAndLoot` hands back a **clone** — there is nothing to write
back to. **Profiles are persisted.** A profile fixture that writes back is not a bad test
artifact, it is data loss on a character Sophia actually plays. So: apply to the in-memory
profile for the raid only, never through a save path, and verify that by reading the profile
off disk after a run rather than by trusting the code. If the clone property cannot be
established, this idea does not get built.

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
