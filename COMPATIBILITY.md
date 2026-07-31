# Compatibility

How Framesaver behaves alongside the mods it is most likely to share a raid with, and what it does about it.
Reviewed against source: SAIN 4.4.3, Fika, ORBIT 1.2.1, AILimit 1.9.0, BigBrain 1.4.0, LootingBots,
QuestingBots, and SPT's own client modules.

## Summary

The surprise is where the conflicts *aren't*. Framesaver's most invasive patches — the ones that prefix a
method and return `false` — turned out to be almost entirely uncontested:

| Our patch | Anyone else on it? |
| --- | --- |
| `BotStandBy.Update` | **No.** AILimit manipulates the object but does not patch the method |
| `Player.LateUpdate` | **No** |
| `GameWorld.smethod_2` (player tick) | **No** |
| `AsyncWorker.FixedUpdate` / `CheckForFinishedTasks` | **No** |
| `AICoreControllerClass.Update` | **Yes** — ORBIT postfixes it |

Exactly one Harmony overlap, and it is benign. **The interactions that actually matter run through shared
*state* — the `BotStandBy` object and `BotOwner.BotState` — not through shared patch targets.** That was
written as an observation and proved to be the whole story: the only serious conflict found so far,
QuestingBots clearing `CanDoStandBy`, patches a method we never touch.

Three guards are implemented, all gated on **`0. Compatibility → Defer to other AI mods`** (default on).
Detection uses `Chainloader.PluginInfos` and is deferred to first in-raid use, because BepInEx 5 populates
that dictionary as plugins instantiate — an `Awake`-time check is a coin flip on load order. It is logged at
the first stand-by check of a raid.

## AILimit — we stand down

`com.dvize.ailimit`. **Guard: the stand-by patch disables itself.**

AILimit does not patch `BotStandBy.Update`. It is a `MonoBehaviour` that reaches into the same `BotStandBy`
objects we do, calling `Activate()` and `method_1()` and setting `NextCheckTime = Time.time + 1000f` to lock
vanilla out.

We honour `NextCheckTime`, so AILimit's lockout already suppressed us by accident. That is not something to
rely on, and it is one-directional.

The substantive reason to stand down is that **AILimit's hammer is strictly bigger than ours.** It calls
`player.gameObject.SetActive(false)`, which stops per-bot `MonoBehaviour`s (LootingBots' `LootingBrain` among
them) and Unity's animation evaluation. Our pause only skips the 22 subsystem ticks in
`BotOwner.UpdateManual`. Running both means two distance systems with different radii (its map defaults are
400 m, ours is 150) and different cadences (300 frames vs 5 s) fighting over one state object, for no gain.

`BotStandByInitPointsPatch` stands down too. It writes `DIST_TO_SLEEP` / `DIST_TO_ACTIVATE`, which is what
*vanilla's* `BotStandBy.Update` measures against — leaving our 150/130 in place while not running our own
`Update` replacement would have vanilla sleeping bots at our distances using its bot-to-bot measure. That is
precisely the failure this mod exists to fix.

### What survives the guard, and what does not

**The animator cull survives, and was never gated on the stand-by patch.** `BotStandByStateChangePatch`
postfixes the `BotStandBy.StandByType` *property setter*, so it records every transition to `paused` whatever
caused it, and AILimit's pauses do reach it — `BotStandBy.method_1()` writes the property
([BotStandBy.cs:219](../../Src/Assembly-CSharp/Assembly-CSharp/BotStandBy.cs:219)), and AILimit sets
`Mind.CAN_STAND_BY = true` immediately beforehand so `method_1`'s guard passes.

In practice it becomes moot rather than useful, because AILimit follows `method_1()` with
`player.gameObject.SetActive(false)`. An inactive `GameObject` does not evaluate its Animator at all —
strictly better than `CullCompletely` — and never receives `VisualPass`, so the cull is not applied and is not
needed. The same call subsumes the `Player.LateUpdate` skip and the world-tick skip. **All three confirmed
sleeping-bot fixes are covered by AILimit's one call.** No regression versus AILimit alone; the two simply do
not stack.

**The sniper exemption is lost, and cannot be restored cleanly.** AILimit's `UpdateBots` sorts purely by
distance and keeps the nearest `BotLimit` bots, with no role awareness anywhere. A marksman placed to engage
from beyond any sensible radius — the Customs smokestack case — gets `SetActive(false)` and goes silent,
which is the exact failure the exemption exists to fix. Restoring it would mean re-enabling a `GameObject`
AILimit disabled on every one of its sweeps, which is the thrash this guard avoids.

Practical advice is to tune AILimit rather than layer Framesaver on top: its map distances default to 400 m,
so bringing them toward our 150 m gets the same policy through the stronger mechanism. It does not give the
sniper case back.

*Why not just let both run?* For a bot AILimit wants active but that is beyond our sleep distance: we pause
it, AILimit's next sweep (~300 frames) sees `StandByType == paused` and calls `Activate()` +
`SetActive(true)` + `NextCheckTime = Time.time + 10f`, locking us out for 10 s, after which we pause it
again. A ~12.5 s freeze/unfreeze oscillation, visible in play.

Two notes for later. AILimit already does multi-human distance (`getMinDistanceToBot` iterates every non-AI
player), which is independent precedent for our `Consider all human players` option. And its
`Player.ComplexUpdate` prefix is doing the same job as our `Skip sleeping bot world tick` by a different
route — both exist because `GameWorld` ticks players from its own list, so a deactivated `GameObject` still
gets `ComplexUpdate` called on it.

## ORBIT and BigBrain — slicing stands down, and ORBIT also clears the stand-by flag

`com.chazut.orbit`, `xyz.drakia.bigbrain`. **Guards: brain slicing forced off; stand-by flag reclaimed.**

### ORBIT clears `CanDoStandBy` too

`OrbitBrainLayer`'s constructor, with the comment *"BSG would otherwise deactivate the bot when far from
the player"*:

```csharp
botOwner.StandBy.CanDoStandBy = false;
botOwner.StandBy.Activate();
```

Identical effect to QuestingBots — it switches Framesaver's stand-by system off, and with it the animator
cull, both sleeping-bot skips and the sniper exemption. ORBIT is narrower (its brain layer only, and it
skips excluded roles) but the consequence for us is the same, so the same reclaim covers it.

Found by auditing every mod for **writes to state we read** rather than by reading what each mod does —
see the note under QuestingBots. ORBIT was not installed when the QuestingBots case was measured, so this
one was caught before it could cost a raid.

ORBIT postfixes `AICoreControllerClass.Update`; we prefix it with `return false`. Harmony runs postfixes even
when a prefix skips the original, so ORBIT's tick fires normally. Nothing breaks.

ORBIT's own comment warns that "running a prefix or replacing the method nulls the in-flight `ActualPath`",
but reading the code that is about *ORBIT's* logic deactivating a brain layer mid-tick, not a general
prohibition — our replacement preserves BSG's semantics exactly when slicing is off.

BigBrain patches `AICoreLogicAgentClass.Update`, one level below: the per-agent `Update` our replacement loop
invokes. We call it normally, so BigBrain's patch fires. Compatible.

The real risk in both cases is **slicing on**. It makes an agent think every Nth frame instead of every
frame, so ORBIT dispatches against layer state up to N frames stale, and BigBrain's custom layers — its
entire purpose — get throttled. Neither is a crash; both are the kind of thing that produces "the AI feels
wrong" with no obvious cause. Slicing is default-off anyway, so this guard mostly protects against turning it
on later and chasing a ghost.

## SAIN — cooperates for free

`me.sol.sain`. **No guard needed.**

SAIN drives its bots from its own chain — `GameWorldComponent.Update` → `SAINBotController` →
`BotManagerComponent` → `BotComponent.ManualUpdate` — entirely independent of `BotOwner.UpdateManual`. So our
pause does not stop it directly.

But `SAINActivationClass.CheckStandBy()` reads `BotOwner.IsBotActive()`, which reads `StandBy.StandByType`.
When we pause a bot, SAIN sets `BotInStandBy` and skips both `_tickWhenNoSleepClasses` and its combat
classes. We get most of the saving without doing anything, and SAIN patches neither `BotStandBy` nor
`AICoreControllerClass`.

What still runs is `_alwaysTickClasses` and `_tickWhenActiveClasses`, gated on
`BotOwner.BotState == EBotState.Active` — see below.

## `BotState` — the flag every other mod gates on

Pausing a bot skips `BotOwner.UpdateManual` and nothing else. **No other mod consults stand-by state.** All
three of the AI stack gate their per-bot work on `BotOwner.BotState` instead:

| Mod | Gate |
| --- | --- |
| SAIN | `_tickWhenActiveClasses` via `SAINActivationClass.CheckBotActive()` |
| LootingBots | `LootingBrain.Update` → `if (BotOwner.BotState == EBotState.Active)` |
| QuestingBots | layer and logic checks throughout |

So a bot we have paused still costs SAIN, LootingBots and QuestingBots their full per-bot work. Measured on
Streets stage 2: at matched awake/asleep counts `aiTotal` was ~5× stage 1 (0.706 vs 0.143 ms).

`4. Experimental → Set sleeping bots to NonActive` (default **off**) closes it, which is exactly what
AILimit does. It is off by default because `BotState` is read in roughly 30 places in BSG's own code —
follower assignment, boss spawning, group ally checks, `AITaskManager` and `MovementContext` among them —
making it a broader change than the pause itself.

**Bosses and followers are never deactivated**, whatever the setting. `BotFollower` requires a boss to be
`Active` before a follower will attach, and `BossSpawnerClass` checks it while placing groups; a sleeping
Reshala losing his guards would be a worse bug than the frame time is worth. `BotOwner.PostActivate` also
promotes `NonActive` back to `PreActive`, so the game can pull a bot out of this state by itself — the wake
path restores `Active` unconditionally so nothing gets stranded, including when the option is switched off
mid-raid.

**Open item:** SAIN ships its own `SAINAILimit` per-bot class. Not yet reviewed for double-throttling against
our pause.

## Fika — one real bug, now fixed

`com.fika.core` / `com.fika.headless`. **Guard: the headless host's local player is excluded from the
nearest-human calculation.**

Co-op distance already worked. `GameWorld.AllAlivePlayersList` on the host includes `ObservedPlayer` for
remote humans; `Player.IsAI` resolves through `AIData.IsAI`, and Fika sets `IsAI = true` only on `FikaBot`.
So `Consider all human players` (default on) already covers remote players correctly, with no changes.

The bug was headless. `CoopGame.CreateLocalPlayer` runs unconditionally on a headless host — it only prefixes
the profile nickname with `headless_` — so a headless instance still has a real `LocalPlayer` with
`IsAI == false`, and it becomes `MainPlayer`. Counting it meant a permanent awake bubble of bots around a
spawn point nobody was standing on, for the whole raid.

`ModCompat.IsFikaHeadlessHost` reads `FikaBackendUtils.IsHeadless` reflectively (no hard reference to Fika,
and it fails closed to "not headless" if the property moves). When set, `MainPlayer` is excluded and the
remote-player sweep is forced on regardless of the config, since it is then the only source of humans. With
no humans at all the function still returns 0, meaning nothing sleeps — safe.

On a Fika **client**, bots are `ObservedPlayer`s with no `BotOwner`, so every bot patch is inert by
construction. Only telemetry runs.

### Fika's `OnDead` transpiler discards more than it means to

Found 2026-07-28 while establishing whether anything patches `Player.OnDead` — the override chain that
[the dead-bot animator refutation](FINDINGS.md#refuted--do-not-re-tread) depends on. Not a conflict with
Framesaver, and recorded because it is a frame-time-adjacent behaviour change that could easily be
attributed to us.

`Fika.Core/Main/Patches/PlayerPatches/Player_OnDead_Patch.cs` is a `[PatchTranspiler]` on
`LocalPlayer.OnDead` which replaces the **entire method body** with `ldarg_0; ldarg_1;
call Player.OnDead; ret`. Its own comment gives the intent as the dogtag handling, described there as
poorly executed.

`LocalPlayer.OnDead` ([LocalPlayer.cs:215-224](../../Src/Assembly-CSharp/EFT/LocalPlayer.cs:215)) is a
five-line method: an `if (base.IsAI)` branch calling `localPlayerCullingHandlerClass.DisableCullingOnDead()`
and `SetDogtagInfo(method_165())`, then `base.OnDead(damageType)` unconditionally. Replacing the whole body
therefore discards the branch, and with it **`DisableCullingOnDead()` for every AI bot** — not only the
dogtag call it was aimed at. `DisableCullingOnDead` puts the per-player culling handler into
`EMode.Disabled` and disposes its subscription (`GClass917.cs:103`), so under Fika that teardown never runs
on a bot corpse.

Two things this does *not* threaten, stated so nobody re-derives them:

- **The animator refutation survives.** `base.OnDead` still runs, and that is where
  `BodyAnimatorCommon.enabled = false` lives. Fika was the one case that could have inverted that finding
  and it does not.
- **It is not in any tested stack.** Fika is absent from stages 1–3, so no measurement in FINDINGS is
  affected.

**Unmeasured.** Read from source at the cited lines; nobody has run Fika or measured what a non-disposed
culling handler costs per corpse. The prediction is that it would present as a culling regression on
corpses under Fika specifically — which, if anyone reports one, is where to look first.

## LootingBots — out of reach, but self-limiting

`me.skwizzy.lootingbots`. **No guard needed.**

`LootingBrain` is a `MonoBehaviour` on the bot's `GameObject` with its own `Update()`, keyed on
`BotOwner.BotState == EBotState.Active` rather than stand-by state. Our pause does not reach it — this is one
of the places AILimit's `SetActive(false)` saves more than we do.

It is not a problem in practice because LootingBots already gates itself on distance and capacity via
`ActiveBotCache` / `IsCloseToPlayer`. Filed as a possible future saving, not a conflict.

## QuestingBots — disables our stand-by system outright

`com.danw.questingbots` (note the casing — see below). **Guard: we reclaim the stand-by flag.**

### The one that mattered

`BotOwnerBrainActivatePatch` postfixes `BotOwner.method_10` and runs this on **every** bot as it activates:

```csharp
// Fix for bots getting stuck in Standby when enemy PMC's are near them
__instance.StandBy.CanDoStandBy = false;
```

Unconditional, not config-gated. Our `Update` prefix bails on exactly that flag, so with QuestingBots
installed **Framesaver's stand-by system never executes at all**. Measured on Streets, stage 2: `asleep = 0`
in every window, 20–27 bots awake for the entire raid, p50 19.5–31.5 ms against 11.5–16.6 ms in stage 1.
Every stand-by-derived saving — the animator cull, both skips, the sniper exemption — goes with it, since
they all key off the paused state.

The workaround targets a flaw in **vanilla's** check, which measures distance to the nearest enemy *or
neutral* — mostly other bots in SPT, which is exactly why a bot could end up parked. Our replacement
measures distance to humans only and refuses to sleep a bot holding a goal enemy, so the stuck state it
defends against cannot arise here. `Reclaim stand-by from QuestingBots` (default on) takes the flag back.

It only reclaims for roles whose own `Mind.CAN_STAND_BY` is true, so Gluhar and Zryachiy stay exempt exactly
as `InitPoints` intended. Known limitation: it cannot distinguish QuestingBots' flag from one cleared by
`BotsPatrolGeneratorGameEvent` for a scripted patrol, so such an event would be overridden within one check
interval. Rare enough to accept against a doubling of frame time; the toggle exists for anyone who hits it.

**How this was missed:** the original review searched QuestingBots' spawning code, having framed it as a
spawn-system mod. Its bot-activation patches were never read. The lesson is that "what does this mod do"
is the wrong search — the right one is "what does this mod write that we read", which for the stand-by
system means `CanDoStandBy`, `StandByType` and `NextCheckTime`.

### QuestingBots has its own sleeping system

`BotLogic/Sleep/SleepingLayer.cs` is a BigBrain layer implementing distance-based sleeping: per-map human
distances, a `MinBotsToEnableSleeping` floor, a configurable sleepless-role list, and a rule against
sleeping near a questing bot. So clearing `CanDoStandBy` is not only a bug workaround — QuestingBots is
substituting its own system for vanilla's.

It did not compensate on Streets, and the reason is in its own gating: a bot that is questing or extracting
is exempt from sleeping unless `SleepingEnabledForQuestingBots` is on *and* the current map is in
`MapsToAllowSleepingForQuestingBots`. Making bots quest is the mod's entire purpose, so on Streets almost
every bot qualified for the exemption — while the system that would otherwise have slept them was switched
off. That is how the measurement ended at `asleep: 0` for a whole raid.

The two systems can coexist: ours pauses `UpdateManual` via `StandByType`, theirs occupies a brain layer.
Neither reads the other's state. If both are enabled the work is done twice but not incorrectly. Anyone
preferring QuestingBots' map-specific distances can turn `Reclaim stand-by from QuestingBots` off and its
`SleepingEnabled` on; Framesaver's version is the measured one and keeps the sniper exemption.

### Detection: GUID casing

QuestingBots ships `com.danw.questingbots`, all lowercase. The constant published in SAIN's
`AssemblyInfoClass` — the source this list was built from — reads `com.DanW.QuestingBots`, and
`Chainloader.PluginInfos` is an ordinal dictionary, so the lookup silently reported "not installed" for a
mod plainly visible in the BepInEx log. `ModCompat.Has` now matches case-insensitively so no GUID can do
this again. SAIN's own QuestingBots detection appears to have the same defect.

### The spawn side: still complementary

This is the most useful thing the review turned up. QB's `TrySpawnFreeAndDelayPatch` prefixes
`BotSpawner.TrySpawnFreeAndDelay`, blocks scav spawns on a max-alive limit and a rate limit, and sets
`NonWavesSpawnScenario.float_2` (the retry delay) when it blocks.

That targets exactly the mechanism in FINDINGS — but it sits **downstream of the cost**. By the time
`TrySpawnFreeAndDelay` runs, `data.Profiles` already exists, meaning `BotCreationDataClass.Create` has already
fired `/client/game/bot/generate` and already paid for the `Profile` constructors. QB reduces how many scavs
end up alive; it does not reduce the 70.8-creation-attempts-per-bot churn we measured. Damping the retry loop
via `float_2` helps, but only after a block has already occurred.

So the two are complementary, and it is a direct argument that a shippable Framesaver spawn fix belongs
**upstream, at generation**.

QB also offers two reusable hook points:

- `NonWavesSpawnScenarioCreatePatch` postfixes the scenario factory to capture the live instance.
- `ServerRequestPatch` prefixes `CreateFromLegacyParams` and filters on the `/client/game/bot/generate` URL —
  a far more stable place to count or throttle generation than BSG internals, and already proven in the wild.

## SPT client modules — why the batch is wasted

Not a compatibility question, but the review answered an open one from FINDINGS.

~~`RemoveUsedBotProfilePatch` forces `withDelete = true` on `BotsPresets.GetNewProfile`, making every cached
profile single-use. Sensible on its own — it stops duplicate bots.~~

**Corrected 2026-07-28, Delta: the patch is a no-op.** `withDelete` is already `true` at all three call sites
in BSG's own code, and the one that would have mattered is dead. Full derivation and citations in
[FINDINGS.md](FINDINGS.md), under "The amplifier is real; SPT does not cause it". The amplifier mechanism
below still holds — only its attribution was wrong.

Combined with the spawn churn it is the missing amplifier. **Each rejected spawn attempt still pulls a
profile from the cache and deletes it.** The cache therefore drains at the rate of *attempts*, not *spawns*,
and a fresh `presetBatch`-sized generate request fires that much sooner. 2,478 attempts against 35 real bots
means the profile cache was being strip-mined and refilled continuously — which is why dropping `presetBatch`
45 → 5 helped as much as it did. It shrank each wasted refill.

One more find, relevant to the sniper exemption: `SpawnPointAIPlayerBotLimitPatch` re-implements
`SpawnPoint.IsInPlayersIndividualLimits` and exempts `marksman` and bosses/followers outright — they bypass
the per-player spawn limit entirely. Snipers are already a special case upstream, which supports treating
them as one in the stand-by system.

## Why the animator cull is coupled to stand-by, and what decoupling it would cost

**The coupling is incidental, not deliberate.** Recording that because everyone who finds it will assume the
opposite, and the assumption is load-bearing: most of this document is about the compatibility surface of
stand-by, and the animator cull inherits every bit of it for no reason anyone chose.

The cull was built on top of stand-by because stand-by already maintained a per-bot eligibility set
(`SleepingBotAnimatorPatch.Sleeping`, filled from the `BotStandBy.StandByType` setter). Not because the cull
needs one.

What each mechanism is worth, measured:

| mechanism | what it changes | measured |
| --- | --- | --- |
| stand-by gating `BotOwner.UpdateManual` | the bot stops **thinking** | ~0.011 ms per bot |
| `AnimatorCullingMode.CullCompletely` | the bot stops being **animated** | ~0.3 ms per bot |

So the 0.011 ms mechanism is the one that fights QuestingBots, needs `keepFightingBotsAwake`, needs the
posted-role widening, and produced all three of the mid-raid latches documented in `COORDINATION.md`. The
0.3 ms mechanism only changes how a bot is drawn, and rides along behind all of it.

### What decoupling would look like, if anyone picks this up

Not a distance check. **Unity keys `CullCompletely` on renderer visibility, not distance** — our marking only
decides which bots are *eligible*, and the engine culls whichever of those are invisible. So the eligible set
can be "every AI player", which removes the `Sleeping` dictionary, any distance measure of ours, and the
role-exemption problem in one move: a sniper engaging you from 200 m is either on your screen and not culled,
or off it and already frozen by vanilla.

Two facts that make this less alarming than it sounds, both from the game's own source:

- `CullCompletely` appears **nowhere in Assembly-CSharp**. Vanilla only ever writes `AlwaysAnimate` or
  `CullUpdateTransforms` ([Player.cs:1526](../../Src/Assembly-CSharp/Assembly-CSharp/EFT/Player.cs:1526)), so
  `EFTHardSettings.AnimatorCullDistance` cannot produce it at any value and is not an alternative lever.
- `CullUpdateTransforms` **already stops transform writes for invisible bots**. Frozen hit boxes, weapon root
  and muzzle past 10 m are vanilla behaviour today, not something culling would introduce.

### The one risk that is genuinely new, and is not settled

`CullCompletely` stops state-machine evaluation, so animation events stop being **enqueued** —
`AnimationEventsStateBehaviour.OnStateEnter/OnStateExit` fills the queue that `EmitEvents()` drains, and the
drain then finds nothing. Harmless for a paused bot, which is not reloading. **Unknown for an awake bot that
leaves your screen mid-reload.** If animation-driven weapon operations stall, decoupled culling makes bots go
passive whenever you look away — a behavioural bug invisible to every performance metric we have, and obvious
to a player within one raid.

That question needs someone watching a raid, not a number. Until it is answered, the coupling stays.

## Source-dump version skew

The decompile at `F:\SPT\Src\Assembly-CSharp` is older than the SPT HEAD these mods build against. The drift
is in **SPT's deobfuscation mapping**, not the game: names still `GClassNNN` in our dump have since been given
real ones. Confirmed instance — BigBrain patches `AICoreLogicAgentClass.Update`; our dump calls that type
`GClass32`, and `AICoreControllerClass.HashSet_0` is a `HashSet<GClass32>` of exactly that abstract agent base.

Harmless for reading community source, which is plain C#. It matters for us because Framesaver references
`GClass32`, `GClass1516`, `GClass684` and `GClass680` by those names and will not compile against current SPT
until the dump is refreshed.

## Untested combinations

Everything above is a source review. None of it has been observed in a running raid — Framesaver's measured
results to date are from a clean install with no other AI mods loaded. The guards are written to fail safe
(stand down, don't slice), but "compatible on paper" is the claim being made here, not "verified in play".
