# Framesaver — investigation findings

Record of what was measured, what was fixed, what was refuted, and what is still open.
All numbers are from the game's own frame measurers (`GClass1357`) plus injected player-loop timers,
sampled per frame and summarised per window. See [README.md](README.md) for the field reference.

Map is Streets of Tarkov unless stated. V-Sync off, 120 fps cap, unmagnified optic.

Sections up to "Validation on SPT 4.0.13" were measured on **SPT 3.x**. Those numbers describe mechanisms
that still hold, but do not compare them directly against 4.0.13 figures — see that section for the current
platform's results.

---

## Summary

Investigation ran 2026-07-25 to 2026-07-26, Streets of Tarkov then Customs. V-Sync off, 120 fps cap.

**The dominant cause of in-raid stutter was not in BSG's engine code at all.** `NonWavesSpawnScenario`
fires one full spawn request per missing bot every check period, so when the bot cap exceeds what the map
can actually host — Horde mode — the deficit never closes and it re-issues the same ~90 requests forever.
Each carries a profile generation (~4 ms) and a bundle load. Measured at **70.8 creation attempts per bot
that actually exists**.

| Streets, 44 bots | Horde on | Horde off |
|---|---|---|
| spawn attempts | 2,478 | **23** |
| attempts per real bot | 70.8 | **1.1** |
| p99 | 39.45 ms | **16.17 ms** |
| drain stall per minute | 852 ms | **0 ms** |

Everything else optimised — `presetBatch`, the `Profile` constructor, the backup-flush bail, the bundle
backlog, `AsyncWorker`'s drain phase — is downstream of that.

**Separately, much of the freezing *during loading* is garbage collection**, not scheduling: 174
stop-the-world collections in a single loading window, driven by 150–340 MB allocated per bot-generation
response on a heap that grows 1.1 → 6.4 GB across a session. That one is not fixable from the client — see
[the 4.0.13 section](#the-loading-freeze-is-garbage-collection).

**But the two largest loading stalls are not GC and not bot work.** `/client/match/local/start` (34–39 s)
and the "PMC bot-generation" callback (8–17 s) are both **raid initialisation resumed inline inside a drain
callback** — the second is `BotsController.Init` and the `vmethod_1` tail, billed to whichever
`bot/generate` completes last. Solved 2026-07-27; see
[that section](#the-167-s-pmc-bot-generation-callback--solved-it-is-raid-initialisation-not-bot-generation).

**And 70% of that is a one-time-per-launch cost.** `GClass620.SetSettings` inside `BotsController.Init`
costs **9,868 ms on the first raid after client launch and 6.5 ms on every raid after, on any map** — so the
largest single remaining item is not a per-raid cost to optimise but a startup cost to relocate off the
loading path. It also makes the community habit of **restarting SPT every few raids actively harmful**: a
restart re-pays ten seconds the running client had already amortised.

**The remaining in-raid spike family is also garbage collection.** With the drain gone, every
`TimeUpdate`-dominant spike measured on 2026-07-27 carried exactly one collection — 14 of 14, against a
base rate of one per 3,628 frames — and PresentMon confirmed the GPU idle throughout. That phase had been
written off as an unreachable GPU wait. It is an 80–120 ms stop-the-world pause that grows with heap size,
and the same run established there is **no GPU-side problem at all** on this hardware: the GPU is idle 62%
of every frame. See [GPU-side telemetry](#gpu-side-telemetry--stage-3-2026-07-27).

Alongside it, four independent client-side fixes exploit the fact that **SPT bots are full `LocalPlayer`
MonoBehaviours** where live EFT uses the far lighter `ObservedPlayerView`. Those are fixes 1–4 below and
are worth ~5 ms/frame at high bot counts on their own.

**Customs, everything applied:** p50 **8.41 ms (119 fps)**, p99 **12.01 ms**, zero drain-attributed spike
frames in 43,021 frames. For comparison, the first Streets measurement was p50 ~21 ms (48 fps).

### What each layer contributed

| | effect |
|---|---|
| Spawn churn (bot cap ≤ map capacity) | eliminates the drain entirely; p99 39.5 → 16.2 ms |
| Cull sleeping bot animators | ~3.3 ms at 24 asleep |
| Skip `Player.LateUpdate` for sleeping bots | ~2.3 ms at 24 asleep |
| Skip `GameWorld` per-player tick | ~0.45 ms |
| Cap `Time.maximumDeltaTime` | worst spawn spiral 439 → 92 ms |
| `presetBatch` 45 → 5 | stall size linear in it; 1,866 → ~40 ms per response |
| Drain out of `FixedUpdate` | moves stalls off the physics clock; does not shrink them |

### Superseded early figures

The original headline compared two Streets locations before the spawn cause was known, and read
"~21 ms → 10.3 ms". Directionally right, but the location differed and Horde was on throughout, so treat
the Customs numbers above as the real result.

---

## Validation on SPT 4.0.13 — stage 1, 2026-07-26

Everything above was measured on SPT 3.x. This is the first data from a clean 4.0.13 install: stock server
config (`presetBatch` 45/30/15, unmodified — the earlier 45 → 5 edit was deliberately not carried over),
no other mods, Horde off. Protocol in [TESTING.md](TESTING.md).

Framesaver built against 4.0.13 with **zero code changes**. The five obfuscated types it depends on
(`GClass32`, `AICoreControllerClass`, `Class312`, `GClass1516`, `GClass684`) kept their names.

| | Factory | Streets | Customs | Interchange |
|---|---|---|---|---|
| `creates` : `botOwners` | 10 : 14 | **21 : 21** | 27 : 29 | 21 : 30 |
| `asleep` / `awake` | 0 / 0–6 | 15–20 / 3–7 | 17–22 / 2–7 | 14–21 / 1–7 |
| `agents.pendingRemoval` | 0 | 0 | 0 | 0 |
| `ambientLight` | runs | inactive | runs | runs |
| in-raid drain stalls | 572, 441 ms | none | one, 97 ms | none |
| best p50 | 8.33 *(capped)* | 11.51 | 8.02 | 6.52 |

**`best p50` means what it says, and it has been read as the baseline ever since.** The row above is the
*best window* of each run, not the run. Quoting Streets at 11.51 ms (87 fps) against a user reporting ~55 fps
looked like a 40% instrument-versus-experience discrepancy worth investigating. **There is no discrepancy.**
Pooling every in-raid Streets window across all 15 logs — 99 windows, 13 raids, teardown windows excluded:

| Streets `frame` p50 | ms | fps |
|---|---|---|
| best window *(the quoted figure's kind)* | 9.47 | 106 |
| p25 | 14.95 | 67 |
| **median window** | **16.51** | **61** |
| p75 | 18.69 | 53 |
| worst window | 31.51 | 32 |

**47 of 99 windows are at or below 60 fps.** A reported ~55 fps is 18.2 ms, sitting between the median and
p75 — squarely inside the distribution. The telemetry has agreed with the person playing all along; the
*quoted number* did not, because a best-of statistic was carried forward as a typical one.

Report the median window, or the distribution. A best-of figure is only meaningful against another best-of.

#### The per-awake-bot model replicates, and it bounds what is reachable

Regressing p50 on awake bots over those same 99 windows, pooled across 13 raids and several mod stacks:

**p50 = 13.25 + 0.402 × awake, r = 0.737** — against `13.5 + 0.507 × awake` from a single 33-window raid.
**The intercept replicates to 2%**, which is the load-bearing half.

- ~~**The intercept is 13.25 ms — 75 fps with every bot asleep.** Every sleeping-bot fix attacks the *slope*.
  Nothing built so far touches the intercept.~~
- **60 fps on Streets needs awake ≤ 8.5 bots**, and the median window runs 8 awake. That is exactly why it
  sits on the edge: the fixes have brought it to the boundary and it wobbles across.
- ~~**100 fps needs 10 ms total, which is below the intercept alone.** Reaching it at 8 awake bots would need
  the intercept down to 6.8 ms.~~

~~So Streets is an **intercept problem**, and no amount of further sleeping-bot work reaches it.~~

##### Corrected 2026-07-28, Delta — the intercept is not identified, and it is not a floor

The regression reproduces exactly (n=99, `13.25 + 0.402 × awake`, r = 0.737). **Both things built on it do not.**

**1. `awake` and `asleep` are 95% collinear, so the intercept depends on which one is in the model.**
`corr(awake, asleep) = −0.954`, because `total` barely moves (16–27). They are near enough one variable with
a sign flip:

| model | R² | intercept | awake | asleep |
|---|---|---|---|---|
| `p50 ~ awake` | 0.543 | **13.25** | +0.402 | — |
| `p50 ~ asleep` | 0.468 | 21.79 | — | −0.376 |
| `p50 ~ awake + asleep` | 0.547 | **10.78** | +0.510 | **+0.114** |

**The two readings imply opposite strategies.** "Intercept 13.25 and nothing touches it" says further
sleeping-bot work is pointless; "10.78 plus 0.114 ms per sleeping bot" says there is ~1.7 ms of headroom at
the median 15 asleep. **The data cannot arbitrate** — R² gains 0.004, and at r = −0.954 the decomposition is
unstable. Neither model is preferred by fit.

**And "the intercept replicates to 2%" was doing work it cannot do.** The single-raid fit `13.5 + 0.507`
matches the one-variable model's *intercept* **and** the two-variable model's *slope*. Both halves
"replicate", to different models, so replication does not break the tie either.

**2. A regression intercept is a conditional mean, not a floor — and nine windows beat it.** Nine of 99 sit
below 13.25 ms, and they are the *low-awake* windows rather than outliers — awake counts 2, 2, 2, 3, 3, 3,
7, 7, 7. The best is **9.47 ms = 106 fps, on Streets, at 7 awake bots**.

So *"100 fps on Streets is arithmetically out of reach"* is **false**. What survives is
**"a *consistent* 100+ is not reachable"** — 1 window of 99 — which is what the criterion
[elsewhere in this document](#the-same-column-produced-every-other-maps-headline-and-the-medians-disagree-there-too)
already says. "Impossible" and "not consistently achievable" license different decisions.

> **Do not requote 9.47 ms as reachable.** It is a best-of window and it is a counterexample to an
> impossibility claim, nothing more. Reading it as a typical figure is precisely the `best p50` error this
> section exists to correct — one day later, in the paragraph correcting it.

**3. Location is why no amount of extra windows can rescue it.** This document's first methodology rule is
that [location dominates everything on Streets](#methodology-notes) and cross-window comparison is
near-meaningless unless position is held. This regression *is* cross-window comparison on Streets, pooled
over 99 windows, 13 raids and several mod stacks. It bundles location cost into a constant and then reads the
constant as physical. That is a structural limit, not a sample-size one.

##### What replaces it: Streets is bounded by `render`, and that bound is real

Same 99 windows, `render` = `frame.avg − gameUpdate.avg`:

| | min | p25 | median | p75 | max |
|---|---|---|---|---|---|
| Streets `render` | **4.85** | 6.02 | 6.53 | 7.01 | 8.21 |

**99 of 99 windows above 4.85 ms, and `corr(awake, render) = +0.187`** — so it barely tracks bot count, which
is the property that makes it a floor and the one the intercept never had. A 10 ms budget leaves **under 5 ms
for the entire update side**, against a current `gameUpdate` of 6.5–24.5 ms.

The strategic conclusion is unchanged — further sleeping-bot work has limited headroom and a consistent
100 fps on Streets is not reachable client-side. It now rests on 99 of 99 observations of a quantity that
does not move with bot count, instead of on an unidentified coefficient with nine counterexamples in the same
table. **`render` is not, however, unreachable — see
[the `render` correction](#render-is-the-postlateupdate-phase-and-the-write-off-was-wrong).**

#### The same column produced every other map's headline, and the medians disagree there too

`best p50` is the row for all four maps, so the correction is not a Streets one. Same pooling, same
`bots.total > 0` filter:

| map | n | best | **median** | p75 | median fps | windows at 100+ fps |
|---|---|---|---|---|---|---|
| `tarkovstreets` | 99 | 9.47 | **16.51** | 18.69 | 61 | **1 of 99 (1%)** |
| `bigmap` | 25 | 8.34 | **10.03** | 10.88 | 100 | 12 of 25 (48%) |
| `interchange` | 7 | 7.63 | **9.84** | 11.97 | 102 | 4 of 7 (57%) |
| `factory4_day` | 9 | 5.70 | **8.33** | 8.33 | 120 | 9 of 9 (100%) |

**Customs and Interchange sit *at* 100 fps as a median, which means roughly half of all windows fall below
it.** Against a criterion of a *consistent* 100+, no map is passing — and Factory is not evidence that one is,
because its median and p75 are **identical at 8.33 ms = exactly 120.0 fps**, the signature of a cap rather
than a measurement. `gameUpdate` there averages 5.42 ms, so the CPU had 2.9 ms of headroom it was never
allowed to use. Factory says only "≥120".

**These are performance numbers, not pacing numbers — checked rather than assumed.** `render` includes the
frame-limiter and V-Sync sleep, so a capped run would inflate `frame` while `gameUpdate` stayed honest. Every
in-raid window carrying a `gfx` block reports **`targetFps: -1, vSync: 0`** — no cap and no V-Sync in raid,
per `DisableGameFramerateLimit`. So there is nothing to sleep for, and `render` is real CPU-side render cost:

| map | `frame` avg | `gameUpdate` avg | `render` | render share |
|---|---|---|---|---|
| `tarkovstreets` | 17.00 | 10.21 | **6.78** | 40% |
| `bigmap` | 10.55 | 6.16 | 4.40 | 42% |
| `interchange` | 10.71 | 7.25 | 3.46 | 32% |
| `factory4_day` | 8.42 | 5.42 | 3.00 | 36% |

**This sharpens the Streets bound considerably.** 100 fps is a 10 ms budget and `render` alone is 6.78 ms,
leaving 3.2 ms for the entire update side against a current `gameUpdate` of 10.21 ms — a 69% cut, with render
held exactly where it is and ~~largely outside what a Harmony mod reaches~~ **— see below; the write-off was
wrong, though what replaces it is worth about a millisecond.**

##### `render` **is** the `PostLateUpdate` phase, and the write-off was wrong

**Established from source, not correlation.** `gameUpdate` is *defined* as `frame − render`
([GClass1357.cs:85](../../Src/Assembly-CSharp/Assembly-CSharp/GClass1357.cs:85)):

```csharp
this.GameUpdateMeasurer.MeasureStatistics.AddMeasurement(new GStruct132
{
    Value = currentFrameTime - this.RenderMeasurer.MeasureStatistics.LastValue
});
```

so `render = frame − gameUpdate` recovers `RenderMeasurer` algebraically. And `RenderMeasurer` runs from
`StartOfPostLateUpdate` to `EndOfFrame`, which
[CustomPlayerLoopSystemsInjector.cs:16,26](../../Src/Assembly-CSharp/Assembly-CSharp/CustomPlayerLoopSystem/CustomPlayerLoopSystemsInjector.cs:16)
inserts as the **first and last subsystems of `PostLateUpdate`**.

**So `render` is the wall-clock duration of the `PostLateUpdate` root player-loop system, on the main
thread — by construction.** It is CPU work, not a GPU sync. PresentMon agrees independently: `CPUWait` p50
**0.053 ms** over 182,845 rows, `GPUWait` p50 9.547 ms. The GPU idles for the CPU.

**A measured `r = 1.00000` between `render` and our `PostLateUpdate` marker is *not* evidence for this** — it
is two brackets around one interval, and the 0.0024 ms residual is the width of BSG's two injected
subsystems, i.e. our own instrument overhead. The lesson is worth more than the number:
**a separate field is not an independent measurement.** The first check — confirming `gameUpdate` is read
from its own `GameUpdateMeasurer` rather than derived — was true and insufficient; it verified a separate
*field*, not an independently *computed* one, and the answer was forty lines into the class already being
cited.

**What it buys is about a millisecond, and correlation is not share.** Over 38 Streets in-raid windows
carrying a `gpu.render` block, `corr(render, drawCalls) = +0.717`; the bot-count confound is genuinely
absent (partial `+0.683` for draw calls, `+0.116` for awake bots). But:

```
render_ms = 5.264 + 0.000467 × drawCalls          (0.47 µs per draw call)
```

**79% of Streets `render` is a constant that does not move with draw calls.** Model-free, needing no
extrapolation: `drawCalls` spans **1,141–4,648** across those windows — 4× — while `render` spans only
**5.63–7.81 ms**. Eliminating submission entirely, which is impossible, buys **~1.4 ms of 6.6**.

0.47 µs per draw call is a normal single-threaded D3D11 submission cost and `graphicsMultiThreaded` is
false, so the mechanism is real and correctly sized. It is a fifth of the block, not the block.

**Two numbers to stop quoting until recomputed on a stated population.**
[The draw-call note below](#gpu-side-telemetry--stage-3-2026-07-27) gives
`corr(drawCalls, p50) = +0.06` and `corr(awakeBots, drawCalls) = +0.74`. **Neither reproduces on any window
set either of two agents could construct** — roughly a dozen variants between them, nearest approaches
`+0.004` and `+0.623`. Its conclusion — *"draw-call submission is not a cost here"* — is also wrong as
stated: submission **is** a cost, ~1.4 ms of `render`; it simply does not show against total frame time.

**Still open, and it is the reading that would change what is worth doing.** `PostLateUpdate` is a composite —
culling, renderer updates, frame completion, **and the canvas/UI subsystems** — so part of the 6.5 ms may be
EFT's in-raid UI rather than scene rendering, which would be reachable in a way scene rendering is not and is
invisible to any draw-call theory. **No log can answer this:** `Expand phase` is `PreLateUpdate` in all
thirteen logs, so no `PostLateUpdate` child has ever been emitted. Setting it to `PostLateUpdate` is a config
change, no build, and it also separates render work from present/sync directly — closing the one gap left by
`TimeUpdate ≈ 0`, which rules out a wait *in `TimeUpdate`* but not one inside a `PostLateUpdate` subsystem.

**And "CPU work" is not the same as "reachable."** This is Unity's render pipeline, not game script. The
write-off may still be operationally right for the wrong stated reason, and the phase expansion is exactly
the result that will tempt someone to slide from one to the other.

**Three caveats, because this changes what gets worked on.** Interchange (n=7) and Factory (n=9) are close to
anecdotal and only Streets has real sample size. The pooling crosses mod stacks, dates and builds, so the
spread is wider than any single configuration would produce and should not be read as achievable-versus-not.
And the older logs carry no `gfx` block, so the no-cap confirmation rests on the runs that do — 50 windows
across Streets and Customs, unanimous.

**The sniper exemption is confirmed twice.** `snipersAwake` held at the configured cap in every Streets,
Customs and Interchange raid window, and behaviourally the Customs marksman near Fortress was seen moving
and engaging the player from well beyond 150 m — the case a pure distance rule can never satisfy.

### Caveat: two confirmed fixes were disabled throughout

The `cfg` block records `skipLate: false`, `skipTick: false`, `asyncBudgetMs: 0`. Stage 1 therefore
validated a **partially disabled** Framesaver — the `Player.LateUpdate` and world-tick skips (~2.75 ms
combined at high asleep counts) contributed nothing to these numbers, and Factory's 572/441 ms drains went
unsliced. Read the table as a floor, not the product's ceiling.

### ~~`TimeUpdate` — a spike family that is not ours~~ — WRONG, it is garbage collection

Recurring in-raid spikes of 130–350 ms initially landed entirely in `unaccounted`. On Interchange three of
five in-raid spikes resolved into **`TimeUpdate`** (180.2 / 134.5 / 142.3 ms, `unaccounted` ≈ 1 ms,
`drained: 0`) — that is Unity's `WaitForLastPresentationAndUpdateTime`, where the CPU blocks on
presentation.

The conclusion drawn from that — *"GPU-side, not reachable by patching"* — **was wrong, and it closed off
the largest remaining in-raid spike family for a day.** `TimeUpdate` is where a stop-the-world collection
lands, not where the GPU is waited on. Measured directly with PresentMon on 2026-07-27: see
[GPU-side telemetry](#gpu-side-telemetry--stage-3-2026-07-27).

**The reasoning error is worth keeping.** `WaitForLastPresentationAndUpdateTime` really is the phase that
blocks on presentation, so naming it looked like an explanation. But "this phase's job is to wait" does not
establish that a given long sample *was* that wait — the phase is simply the first one in the frame, so
anything that blocks the main thread at a frame boundary lands there. Identifying a mechanism that *could*
explain an observation is not the same as measuring that it did.

A second, distinct family remains open: 150–350 ms spikes confined to the first minute or two of a raid,
with `TimeUpdate` at zero. All eight top-level Unity phases are instrumented, so this is genuinely time
outside the player loop rather than a missing marker.

### `/client/match/local/start` — further corroboration it is not a stall

Measured at 40,130 ms (Streets), 19,681 ms (Customs) and **716.9 ms** (Interchange) in a single session.
A 56× spread across three raids is what a loading screen does, not what a main-thread stall does. This
matches the earlier conclusion, which had been wrong three times before being checked.

### The loading freeze is garbage collection

With in-raid stalls largely gone, loading is what is left — but the problem is not its *duration*. Per the
user, a long load is acceptable; what is not acceptable is the main game loop freezing partway through it.
That reframing matters, because the two have different fixes.

GC collections cluster almost entirely in loading windows:

| Raid | loading windows (gen0) | in-raid windows (gen0) |
|---|---|---|
| 1 Factory | **174**, 0 | 0–4 |
| 2 Streets | **25**, 1, 5 | 0 |
| 3 Customs | **18**, 4 | 0–1 |
| 4 Interchange | **27** | 0–2 |
| 5 Customs | **22**, 4 | 0–3 |

Allocation rate tracks it: **14–55 MB/s during loading against 0.2–9 MB/s in raid**. Each
`/client/game/bot/generate` completion allocates 150–340 MB on its own.

**Mechanism.** Mono's Boehm GC is non-generational and non-compacting, so every collection is a
stop-the-world pause and they lengthen as the heap grows. 174 collections inside one loading window is the
main loop being interrupted 174 times — which is exactly what "the game freezes at points during the load"
describes. It also explains the 8.7 s Streets callback reporting a *negative* `allocKb`: a collection ran
inside it and the heap ended smaller than it started.

**The heap climbs relentlessly across a session: 1.1 GB → 6.4 GB over five raids.**

### Why a drain budget cannot fix the loading freeze

`Async drain budget ms` caps how long a drain *call* may spend before deferring the rest. That only helps
when the time is spread across many callbacks. During loading it is not:

| | drain time | callbacks drained | worst single callback |
|---|---|---|---|
| raid2 w11 | 8,702 ms | **3** | 8,699 ms |
| raid3 w19 | 3,068 ms | **1** | 3,068 ms |
| raid5 w35 | 18,221 ms | 221 | 18,221 ms |
| raid4 w25 | 7,412 ms | 366 | 2,939 ms |

Three of four are a single monster callback. A per-call budget stops the drain *starting* another callback
once spent; it cannot interrupt one already running. Only `raid4 w25` was ever sliceable.

The budget was originally gated to raid-only on the reasoning that rationing the loading queue would just
lengthen the loading screen. Given the reframing above that objection no longer applies — but the fix would
not have worked anyway, so the gate stays. **The budget remains worthwhile for in-raid stalls only.**

### The lever is allocation, not scheduling

Fewer profiles per response → less allocated → fewer and shorter stop-the-world pauses. That is
`presetBatch`, and it needs a **server-side** mod overriding `botConfig.presetBatch` in `postDBLoad`. This
is a considerably stronger case for building it than "loading is slow" was: it is not about duration, it is
about how many times the main loop is stopped.

**Testable prediction:** loading should get measurably worse the longer a client session runs, because
collections on a 6 GB heap cost more than on a 1 GB one. That matches the community habit of restarting SPT
every few raids. Confirming it needs several consecutive raids with `gc.heapMb` and loading stall duration
compared across them — the data is already collected per window, it just needs a long enough session.

---

## Validation on SPT 4.0.13 — stage 2 (SAIN + LootingBots + QuestingBots), 2026-07-26

**Result: parity with the no-mods baseline while running the full AI stack.**

| Streets | Stage 1 (no mods) | Stage 2 (full stack, `presetBatch` 5) |
|---|---|---|
| p50 | 16.6 → 11.5 ms | 11.0 → 15.6 ms |
| `gameUpdate` avg | 8.5 → 6.6 ms | 6.7 → 9.4 ms |
| awake / asleep | 3–7 / 15–20 | 2–7 / 14–19 |
| in-raid spike frames | 4 | 7 |
| worst in-raid callback | — | 149.9 ms |

Getting there took three fixes and cost two invalid raids. Each is worth recording separately.

### 1. QuestingBots switched the stand-by system off entirely

`BotOwnerBrainActivatePatch` sets `StandBy.CanDoStandBy = false` on every bot. Our `Update` prefix bails on
exactly that flag, so **nothing slept for a whole raid**: `asleep: 0` in every window, 20–27 bots awake,
p50 19.5–31.5 ms against stage 1's 11.5–16.6. Every stand-by-derived saving went with it, since the
animator cull, both skips and the sniper exemption all key off the paused state.

Fixed by reclaiming the flag for roles whose own `Mind.CAN_STAND_BY` is true. Full reasoning, including why
this is not merely bulldozing another mod, in [COMPATIBILITY.md](COMPATIBILITY.md). ORBIT does the same
thing in its brain layer and is covered by the same guard.

### 2. `Keep fighting bots awake` is a major lever once SAIN is installed

Default on, and near-free in vanilla SPT. With SAIN's much better detection and QuestingBots pushing bots
to roam and fight, a large fraction of the map holds a goal enemy at any moment — so the flag kept
**50–58% of bots awake** against stage 1's 26–30%, regardless of distance.

Turning it off brought the awake fraction *below* the no-mods baseline. This is the single highest-value
setting when running an AI overhaul, and it does not appear to cost anything observable: a bot-vs-bot
fight beyond the sleep distance freezes, but wake distance is 130 m, so it resumes before the player can
reach it.

### 3. `BotState = NonActive` — the fix that needs its own wake path

Pausing a bot only skips `BotOwner.UpdateManual`. No other mod consults stand-by state; SAIN, LootingBots
and QuestingBots all gate on `BotOwner.BotState`, so they keep working on bots we have paused. At matched
awake/asleep counts `aiTotal` was ~5× stage 1 (0.706 vs 0.143 ms).

Setting `NonActive` closes that — but naively it is a **serious bug**, and the first attempt shipped it:

```csharp
// BotOwner.UpdateManual
if (this.BotState == EBotState.Active && this.GetPlayer.HealthController.IsAlive) {
    this.StandBy.Update();                                   // the wake check
    if (this.StandBy.StandByType != paused) { ...22 ticks... }
}
```

`StandBy.Update()` is *inside* the `Active` guard, so a deactivated bot can never wake again — not by
distance, and not by being shot, since `GetHit` only sets a timer `Update` would have read. Sleep became a
one-way door and bots stood frozen for the rest of the raid. The tell was `snipersAwake: 0` for a whole
raid on a map where marksmen had demonstrably been generated: `IsExempt` was never called, so the exemption
never rebuilt.

AILimit sets the same flag without hitting this because it drives wake-ups from its own MonoBehaviour
sweep. Copying the flag without also owning the wake path is what broke. Fixed with a prefix on
`UpdateManual` that pumps `StandBy.Update()` by hand for the NonActive+paused signature —
`BotsClass.UpdateByUnity` iterates every bot without filtering on `BotState`, so it still runs.

**The raid measured with that bug is not usable data:** asleep counts were inflated by frozen bots.

### `presetBatch` — the linear relationship confirmed on 4.0.13

Capping all 31 `presetBatch` keys above 5 down to 5 (45 → 5 for `assault`, 30 → 5 for `marksman`):

| | before | after |
|---|---|---|
| worst in-raid callback | 1,242.2 ms | **149.9 ms** |
| next two | 638.3 / 636.2 ms | 79.7 / 71.1 ms |
| in-raid spike frames | ~28 | **7** |

An ~8× reduction against a 9× batch reduction. Stall size is linear in `presetBatch`, now confirmed on two
SPT versions.

### In-raid and loading have different bottlenecks

The same change barely touched loading: the pre-raid generation callback went **21.0 s → 19.1 s, a 9%
improvement from a 9× batch reduction**. So profile construction was never the loading bottleneck.

That fits the GC finding above — 139 MB allocated in that one callback, `gen0 = 146` in the window. Loading
is allocation-and-collection bound; in-raid stalls are profile-count bound. Two problems that shared a
symptom and needed separating.

---

## GPU-side telemetry — stage 3, 2026-07-27

Two consecutive Streets raids in one client session, Reflex off then on, with
[Intel PresentMon 2.5.1](https://github.com/GameTechDev/PresentMon) capturing per-frame GPU execution
alongside the usual telemetry. The GPU was the one part of the frame nothing here could measure, and three
instruments were added to close it: BSG's own DXGI VRAM query, Unity's `FrameTimingManager`, and
`ProfilerRecorder` render counters.

**The result was not the one being looked for.** There is no GPU-side problem on this hardware at these
settings — and finding that out is what identified the cause of the largest remaining in-raid spike family.

### `TimeUpdate` is garbage collection — 14 of 14

| in-raid spikes, both raids | n | carrying a gen0 collection |
|---|---|---|
| **`TimeUpdate`-dominant** | **14** | **14** |
| everything else | 19 | 2 |

The in-raid base rate is **one collection per 3,628 frames** — 22 collections across 79,820 frames — so the
expected coincidence across 14 spikes is 0.004. Every one of the 14 also has `drained: 0` and
`asyncUpdate: 0.0`, so this is not the bot/generate drain under another name.

Turned around: **16 of the 22 in-raid collections produced a spike frame over 100 ms — 73%.** In-raid
collection is now rare and individually catastrophic, which is the opposite of the loading regime.

Confirmed independently by PresentMon: `GPUBusy` on those same frames is **6.5–9.4 ms** against a session
p50 of 6.24 ms. The GPU did an entirely ordinary amount of work through every stall. Two instruments, two
mechanisms, same answer.

**This does not contradict [the earlier GC refutation](#refuted--do-not-re-tread).** That measured 30 of
4,249 spike frames coinciding with a collection — 0.7% — when the drain generated the overwhelming majority
of spikes. With the drain gone, the population is different: what is left is mostly GC. The old number was
right about its population and says nothing about this one.

### Pause cost scales with heap — measured in raid

Same map, same build, consecutive raids in one session:

| | heap | `TimeUpdate` pause | n |
|---|---|---|---|
| raid 1 | ~2.6 GB | **82.9 ms** mean | 6 |
| raid 2 | ~3.1 GB | **111.3 ms** mean | 8 |

+19% heap for +34% pause, in the direction
[the session-degradation prediction](#does-loading-degrade-over-a-session--heap-growth-says-it-should)
requires. **Treat it as suggestive and badly confounded, not as evidence.** The rest of this subsection is
why, because the number is more tempting than it deserves.

**Pooling the individual collections looks far stronger than it is.** Regressing all 14 in-raid `TimeUpdate`
pauses against their window's heap, same map, continuous 2,533–3,232 MB range, gives 51.8 ms per GB with
**r = 0.909, r² = 0.83**. That looks like a clean result and is not one. Decomposed:

| | n | heap range | r | slope |
|---|---|---|---|---|
| within raid 1 | 6 | 2,533–2,673 MB | +0.216 | +18.8 ms/GB |
| within raid 2 | 8 | 3,030–3,232 MB | **−0.021** | **−1.4 ms/GB** |
| pooled | 14 | 2,533–3,232 MB | +0.909 | +51.8 ms/GB |

The correlation is **entirely between the two clusters**. Within either raid there is none. So the fourteen
points are the same two-point comparison wearing a larger n, and the pooled r² is an artifact of two tight
groups far apart. The within-raid nulls are uninformative rather than contradictory — a 140–200 MB spread
cannot resolve this effect against ~10 ms of scatter — but they add no independent support either.

**And the two clusters differ by more than heap.** Raid 1 ran Reflex **off**, raid 2 Reflex **on**; raid 2
also carried more awake bots (7–14 against 2–12) and sat later in the session. Nothing about Reflex plausibly
touches collection cost, but a two-point comparison cannot separate any of these from heap. The Reflex
comparison's bot-count confound was noted at the time; that the *same pair* confounds the heap comparison
was not, and it should have been.

**What would actually establish it:** several consecutive same-map raids in one client session with no other
variable moving, giving heap a range wide enough to regress within a single arm. That is a run nobody has
done. Until then this is a hypothesis with a plausible mechanism and a suggestive pair, which is roughly
where it stood before the measurement.

**Superseded 2026-07-28 — the linear model is refuted and the independent variable was wrong.** The control
run extrapolated it to 4.9 GB and it failed by 73%. Worse, `heapMb` turns out not to measure the quantity a
collection's cost depends on. See
[the control run](#control-run--stage-4-2026-07-28-reflex-on-both-arms).

**Keep any such comparison within a map.** Pause cost is an absolute millisecond figure, and
[absolute figures do not transfer between maps](#cross-map-validation--required-before-this-is-shippable) —
a different map changes object-graph shape and heap fragmentation, not just heap size. A later raid on
another map is a consistency check, not a confirmation, and if its direction disagrees the map is the first
suspect, not the claim.

### Collections are frequent-and-cheap loading, rare-and-catastrophic in raid

The same spike lines, split by regime. Expected coincidences are computed from each window's own collection
rate, so the two regimes are compared against their own base rates rather than each other's:

| regime | spike lines | expected to carry a collection | observed |
|---|---|---|---|
| loading | 67 | 1.43 | **7** |
| in raid | 33 | 0.01 | **16** |

Loading is enriched about 5×; in-raid is enriched by three orders of magnitude. That is not one phenomenon
seen twice — during loading, collections are constant (144 in a single window) and mostly too cheap to
produce a 100 ms frame at all, while in raid they are rare and almost always catastrophic.

Heap is the obvious candidate for what separates them — loading windows run at **1.2–2.9 GB**, in-raid at
**2.5–3.2 GB**, and the window with 144 collections had the smallest heap in the session (1,207 MB) and a
p99 of 68.5 ms. But those ranges **overlap at 2.5–2.9 GB**, so "separates cleanly" would be too strong.

The overlap is the interesting part, because it is where loading and in-raid collections could be compared
at matched heap: if a loading collection at 2.7 GB is much cheaper than an in-raid one at 2.7 GB, heap is
not the whole story and something else differs between regimes — live-set composition, fragmentation, or
reachable fraction.

**Not answerable with the data in hand, for a reason worth recording.** Loading frames carrying a collection
are dominated by something else: of the seven, five are 1.2–17.9 second callbacks that happen to contain a
collection, not frames the collection made slow. Only two are small enough to be collection-dominated
(130.8 and 129.3 ms) and both sit *below* the overlap, at 1,207 and 2,125 MB. In raid the pause is the frame;
during loading it is a rounding error inside a callback. Isolating it needs `gcPhase` plus a sharply negative
`heapDeltaMb` to identify collection-dominated loading frames, and even then most loading collections occur
inside long callbacks where no frame-level instrument can separate them.

This sharpens rather than contradicts
[the loading-freeze finding](#the-loading-freeze-is-garbage-collection): "174 collections in a loading
window" is still the count of times the main loop was interrupted, but the cost of each interruption is a
function of heap size, and early-session loading is where the heap is smallest.

### The machine is comprehensively CPU-bound

| | p50 | p95 | p99 | max |
|---|---|---|---|---|
| `FrameTime` | 16.54 | 22.24 | 37.94 | 37,260 |
| **`GPUBusy`** | **6.31** | 8.25 | 9.90 | 319.7 |
| `CPUBusy` | 16.49 | 22.17 | 37.83 | 37,260 |

The GPU is idle roughly **62% of every frame**, and `GPUBusy` exceeded the frame budget on **83 of 55,326
frames — 0.15%**. The two loading megastalls say it louder still: the 37.26 s frame ran **12.22 ms** of GPU
work, the 17.96 s frame 147.79 ms.

Every millisecond this investigation has chased is on the correct side of the CPU/GPU line. That was
assumed throughout and had never been checked.

### Reflex changes nothing, which is the expected result

| p50 / p99 | Reflex Off | Reflex On |
|---|---|---|
| `FrameTime` | 16.54 / 37.94 | 16.65 / 32.68 |
| `GPUBusy` | 6.31 / 9.90 | 6.24 / 9.92 |
| `GPULatency` | 3.20 / 13.61 | 3.56 / **8.56** |
| `DisplayLatency` | 19.67 / 49.23 | 21.05 / **41.77** |

Medians unchanged or fractionally worse, tails modestly better. Reflex exists to stop the CPU running ahead
of a *saturated* GPU; this GPU has 62% headroom, so there is nothing for it to do. `vSyncCount` and
`targetFps` were unchanged too, so it did not even perturb the pacing regime.

**The tail improvements are not established** — raid 2 ran 7–14 awake bots against raid 1's 2–12, so the
two are not matched. What the run does establish is compatibility: Reflex on is harmless, and the GC
finding replicates cleanly under it.

### VRAM is not a factor, and the settings file lied

3.5–5.6 GB used against an 11,228 MB budget, `overBudget: 0` in all 32 windows. Not close, and the DXGI
query costs 0.001–0.03 ms so it is worth keeping as a cheap regression guard.

The hypothesis that motivated it — maximum texture residency crowding a 12 GB card — was built on
`%APPDATA%/Battlestate Games/Escape from Tarkov/Settings/Graphics.ini`, which claimed `TextureQuality: 3`,
`MipStreaming: false` and `FSR3Mode: Balanced`. **The runtime disagreed with all three:** `textureQuality: 1`,
`mipLimit: 1`, `fsr3: Off`.

**Read graphics state from the live objects, not from the ini.** The `gfx` block now does this on every
window line, for the same reason the `cfg` block exists — and it caught a second discrepancy immediately:
`targetFps` is **−1 in raid**, because `DisableGameFramerateLimit` is on. There is no frame cap in raid,
which the ini also denied. This matters beyond bookkeeping: `render` includes the frame-limiter sleep, so
whether a cap is active changes how that field must be read.

### What each instrument was worth

| source | verdict |
|---|---|
| **`ProfilerRecorder` render counters** | **Live** — this build ships with the profiler enabled. Draw calls 1,849–4,648 avg (max 7,065), SetPass 1,144–3,191, triangles 1.4–2.1M. |
| **DXGI VRAM** (`CameraClass.GetVRamUsage`) | **Live and free.** Answered its question: not a factor. Keep as a regression guard. |
| **`FrameTimingManager`** | **Unavailable.** Frame Timing Stats is a baked player setting and this build lacks it. The vendor-neutral path is closed; PresentMon is the route. |

### ~~Draw-call submission is not a cost here~~ — corrected 2026-07-28: it is, and the figures did not reproduce

The original entry read: *"`corr(drawCalls, p50) = +0.06`. Awake bots do drive submission —
`corr(awakeBots, drawCalls) = +0.74` — it simply costs nothing measurable."*

**Neither figure reproduces on any population anyone can construct.** Swept across draw calls avg/max and
`setPass`, against `p50`/`frame`/`gameUpdate`, in-raid and all-states, pooled and GPU-session-only, by two
sessions independently. Nearest approaches to `+0.06` are `+0.004` and `+0.129`; nearest to `+0.74` is
`+0.623`. **The population was never stated, which is the whole defect** — the entry compares two numbers
whose denominators are unknown.

**Stated population for the replacement: Streets, in-raid, windows carrying a `gpu.render` block, all logs,
n = 38.** The GPU-session subset (n = 22) is given where it differs.

| | n = 38 | n = 22 |
|---|---|---|
| `corr(drawCalls, p50)` | **+0.351** | +0.262 |
| `corr(awakeBots, drawCalls)` | **+0.338** | +0.493 |
| `corr(render, drawCalls)` | **+0.717** | +0.615 |
| …partialling out `awakeBots` | **+0.683** | +0.501 |
| `corr(render, awakeBots)` partialling out draw calls | **+0.116** | +0.236 |

**Submission is a real cost, correctly sized, and it is not bot count in disguise.** Once draw calls are in
the model, bot count adds almost nothing. The regression is

> `render = 5.266 + 0.000467 × drawCalls` — **0.47 µs per draw call**, a normal single-threaded D3D11
> submission cost, consistent with `graphicsMultiThreaded: false`.

**But correlation is not share, and only share decides whether it is a lever.** Draw calls span **4.1×**
across those windows (1,141–4,648) while `render` spans only **5.63–7.81 ms**. So **79% of Streets render is a
constant draw calls do not reach**, and the proportional part is **1.4 ms of 6.6**. Eliminating submission
entirely — impossible — buys ~1.4 ms. Real, worth having, not a route to 100 fps.

The old conclusion was directionally wrong and the old reason was right: draw calls are a poor predictor of
*frame time*, because render is 40% of the frame and bot-driven variance dominates the rest. **Predicting
frame time and predicting render are different questions, and the entry answered the first while being read
as answering the second.**

Caveats that must travel with this: n = 38, observational, and **location is not held on the one map where
[location dominates everything](#methodology-notes)**. `drawCalls` also indexes everything view-dependent —
culling, shadow passes, batching — so a partial correlation cannot separate submission from any other
on-screen cost, and the 0.47 µs agreement with a known submission figure is suggestive rather than decisive.
**More observational windows cannot strengthen this**; it needs the `PostLateUpdate` expansion or a
fixed-position A/B that moves draw calls without moving what is drawn.

### Open: why is it stop-the-world at all?

`gcRuntime` reports `isIncremental: true` with a 3 ms slice, and these frames have ordinary boundaries
either side, so the collector had every opportunity to spread the work and did not. Two candidates:

1. **The collection is forced to completion** by an allocation that cannot wait. Slice size is then
   irrelevant, but driving the collector harder in advance should help.
2. **Only marking is incremental** and the sweep is unconditionally stop-the-world. Nothing schedulable can
   help, and the only lever left is allocation volume and heap size — back to `presetBatch` and the profile
   churn.

`GC time slice ms` and `Drive incremental GC ms` discriminate between them, and **both doing nothing is
candidate 2** — a real result, not a failed experiment. `gcPhase` on spike lines now names the phase a
collection completed in rather than merely the frame, and `heapDeltaMb` gives what it reclaimed.

---

## Control run — stage 4, 2026-07-28 (Reflex on, both arms)

Two arms in one client session with no restart between them: **Streets** then **Customs**, both GC knobs at 0,
`suspendGc` true, `drainInUpdateOnly` true, and — unplanned — **Reflex on throughout**, carried over from the
previous session. The carry-over turned out to be useful rather than harmful; see below.

### ~~`TimeUpdate` is garbage collection — now attributed to the phase, on two maps~~ — the denominator was wrong

**Corrected 2026-07-28 by re-analysis of the same log** (`framesaver-20260727-232217-control.ndjson`); no new
measurement, and re-derived independently from the raw file by a second session. The original text is kept
below because the error is in the *selection*, not the arithmetic, and it is the more instructive half.

> ~~The stage-3 claim rested on "a collection happened on this frame and the frame was slow". `gcPhase` counts~~
> ~~collections *per player-loop phase*, which upgrades that to "the collection completed inside this phase":~~
>
> | ~~arm~~ | ~~map~~ | ~~in-raid collection frames~~ | ~~`gcPhase` = `TimeUpdate`~~ |
> |---|---|---|---|
> | ~~1~~ | ~~Streets~~ | ~~10~~ | ~~**9**~~ |
> | ~~2~~ | ~~Customs~~ | ~~13~~ | ~~**13**~~ |
>
> ~~**22 of 23**, and in every case `gcPhase` equals the frame's dominant phase.~~

**The denominator was the set of frames on which the instrument produced an answer, not the set of frames
carrying a collection.** `PlayerLoopProfiler.GcPhase()` returns `""` when no top-level phase's counter moved,
and `Telemetry` omits the field entirely when it is empty — so filtering on `gcPhase` silently selected the
successes. There are **36** in-raid collection frames, not 23:

| arm | map | in-raid collection frames | `gcPhase` = `TimeUpdate` | other phase | **no `gcPhase`** |
|---|---|---|---|---|---|
| 1 | Streets | **11** | 9 | 1 (`Update`) | **1** |
| 2 | Customs | **25** | 13 | 0 | **12** |
| | | **36** | **22** | 1 | **13** |

**State the implication in both directions, because only one of them survives.**

- **`TimeUpdate`-dominant in-raid spike ⇒ a collection: 22 of 22, both maps.** Untouched, and it is the
  direction the mechanism argument needs.
- **A collection ⇒ `TimeUpdate`-dominant: 22 of 36, and only 13 of 25 on Customs.** The published headline
  asserts this direction and it is not supported.

#### The 13 are not an instrument failure — the pause lands outside every bracketed phase

All eight top-level phases *are* bracketed (`TimeUpdate`, `Initialization`, `EarlyUpdate`, `FixedUpdate`,
`PreUpdate`, `Update`, `PreLateUpdate`, `PostLateUpdate`), so a collection completing in any of them would be
named. On these 13 the counter moved in none, and `GcPhase()` correctly returned nothing.

**Where the time actually goes, per frame:** `unaccounted` is **80.7–218.8 ms, a remarkably tight 0.86–0.90 of
the period** on all twelve Customs frames, while `PostLateUpdate` sits at **3.8–15.3 ms** — *lower* than an
ordinary in-raid frame's 9.3–11.8 ms. So these frames are **residual-dominant**. Reading them as
`PostLateUpdate`-dominant is an artifact of taking a maximum over the named phases while ignoring the residual,
and it would point at the wrong mechanism.

~~The separation is total. `unaccounted / period` is **0.78–0.90** on the thirteen and **−0.02–0.03** on the
twenty-two attributed frames — bimodal with no overlap — while `PostLateUpdate` sits in the same 3.8–15.3 ms
range on both. It is not elevated on the thirteen at all.~~

**Superseded 2026-07-28, Delta — the ratio is not a mechanism, and it points the wrong way.** With phase work
roughly constant at ~11 ms, `unaccounted / period` is a monotone function of pause length, so "0.78–0.90, tight
across thirteen frames" restates that those frames are similar *lengths* while reading as a signature. It is
also actively misleading: the twelve non-GC frames found below sit at a **higher** ratio (0.91–0.95), so
anyone using it as a GC signature mis-assigns exactly the population it fails on.

**Two fields already on every spike line separate the populations perfectly, and both are positive assertions
rather than descriptions:**

| in-raid, residual-dominant | `frame` median | `frame < period / 2` | `TimeUpdate` ≥ 0.5 ms |
|---|---|---|---|
| **13 with a collection** | 15.0 ms | **13 of 13** | **13 of 13** |
| **12 with no collection** | 201.5 ms *(≈ its own period)* | **0 of 12** | **0 of 12** |

**Read the second column as `≥ 0.5 ms`, not as "present".** `Telemetry.cs` drops any phase below 0.5 ms from
the JSON while still counting it toward `accounted`, so the residual stays correct but the field *vanishes*
rather than reading zero. Same shape as the `gcPhase` omission that caused the error this section corrects —
an absent field is not a zero, and here it is a threshold.

`frame` is BSG's own `GClass1357` measurer and `period` is our wall clock between `ReadAndReset` calls — two
clocks sharing no code. **On the thirteen, BSG's measurer reports an ordinary 12.6–27.5 ms frame while the
period is 104–246 ms.**

`PostLateUpdate` is 3.8–15.3 ms on both and separates nothing. It was never the discriminator.

##### Corrected 2026-07-28, Delta — the separation is real, the mechanism I attached to it is not

I wrote that the block *"sits outside the interval the game measures and inside ours"*, and called it the
boundary mechanism. **Withdrawn. Two problems, and the second is the one that bites.**

**1. The alignment does not support it.** `GameFrameMeasurer` stops and restarts inside `method_0`
([GClass1357.cs:83,96](../../Src/Assembly-CSharp/Assembly-CSharp/GClass1357.cs:83)), which is subscribed to
`StartOfFrame` — inserted as the **first subsystem of `EarlyUpdate`**. So its window runs
`StartOfFrame` → `StartOfFrame` and is a **complete tiling of wall time**: it contains the native inter-frame
gap and the next frame's `TimeUpdate`. There is no interval that `period` covers and `frame` structurally does
not. So "outside the interval the game measures" cannot be the explanation, and what actually produces
`frame ≪ period` is an **alignment or lag effect between two differently-anchored clocks** that has not been
worked out. `frame` is a lagged counter — the off-by-one it caused once already is
[in the methodology notes](#methodology-notes).

**2. It does not generalise as a GC classifier.** Within the control run's residual-dominant set the split is
perfect, and that is a fact. Across all logs it is not: **29 in-raid spike frames have `frame < period / 2`,
28 of them residual-dominant, and only 14 carry a collection.** So roughly half the population showing this
property has no collection at all, and using it to *identify* collections would repeat the error one field
over — again.

**What survives, and it is narrower than what it replaced.** Inside the control run's 25 residual-dominant
in-raid frames, `frame < period / 2` and `TimeUpdate ≥ 0.5 ms` each separate the 13 from the 12 without
error. That is a **classifier on that population**, useful for reading those lines, and it is *not* a
mechanism and *not* a general GC test. The `unaccounted / period` ratio it replaced was worse — it pointed
the wrong way — so this is still an improvement, but it was over-claimed within a day of being written.

**`endToStart` settles it and needs no argument.** If the block is in the native inter-frame gap it will show
there on both populations; if the thirteen's time is somewhere else, it will not. That is the measurement,
and it is already built.

##### Registered prediction — written 2026-07-28 by Delta, before `endToStart` has ever run

Recorded before the data exists so it cannot be fitted afterwards, on the precedent of
[the `zoneLeaveCtor` map-independence call](#registered-prediction-before-arm-2-is-run). **A merge is the
more interesting outcome, which is exactly why the criteria go in first.**

`endToStart` spans `EndOfFrame` → `StartOfFrame`, so it **contains `TimeUpdate` and `Initialization`** as well
as the native gap. **The quantity to read is `endToStart − TimeUpdate − Initialization`**, never the raw
field. Call it `gap`.

| population | `gap` under **merge** | `gap` under **coincidence** |
|---|---|---|
| ordinary in-raid frames | ~0–2 ms | ~0–2 ms |
| the 22 `TimeUpdate`-dominant | ~0–2 ms *(their pause is inside `TimeUpdate`, which is subtracted out)* | same |
| **the 12 non-GC** | **≈ `unaccounted`, 160–246 ms** | **≈ `unaccounted`** |
| **the 13 residual + collection** | **≈ `unaccounted`, 80–218 ms** | **small, ≪ `unaccounted`** |

- **Merge** — the thirteen's residual is in the same native gap as the twelve, so GC *rides along* on a block
  it does not cause. The residual half of the GC attribution is then wrong, though
  [the forward direction](#amended-2026-07-28-delta--36-of-36-is-true-and-it-invites-an-inverse-that-is-a-coin-flip)
  — `TimeUpdate`-dominant ⇒ a collection, 38 of 38 — is untouched either way.
- **Coincidence** — the thirteen's time is somewhere neither the eight phases nor the gap reach, and the
  boundary story needs a different home.
- **Common cause**, Gamma's variant, sits between them and is distinguishable by *size* rather than presence:
  the twelve at ~200 ms and the thirteen at ~125 ms with a 3 ms slice inside. Predicted by the existing data.

**Falsification of the merge is either of the last two rows failing**, and one further outcome would be the
most useful of all: **if the twelve also read a small `gap`, the residual is in none of the eight phases *and*
none of the inter-frame interval** — which would make it an artifact of how the residual is computed rather
than a real family. That is an instrumentation defect, and it is a better result than a named cause.

**The run is void, not negative, if `gap` is large on ordinary frames too.** That is the pairing-drift failure
mode below, and it produces exactly the signature being hunted.

**A third outcome, added before the run once the pairing guard shipped.** `endToStart` emits `null` when the
`EndOfFrame`/`StartOfFrame` pairing is not 1:1 on a frame, so an anomalous loop iteration reads as *no answer*
rather than as a number:

| `endToStart` on the block family | reading |
|---|---|
| large `gap` | the block is in the native inter-frame interval |
| small `gap` | it is in neither the phases nor the gap — the residual is an artifact |
| **mostly `null`** | **the pairing is not 1:1 during the block — a loop-iteration anomaly, not merely a stall** |

**Nulls concentrated on the family and absent on ordinary frames is a positive result**, and a different one
from either registered outcome. Recorded now so it cannot be rationalised into one of them afterwards, and so
a column of nulls is not read as a broken instrument.

**Read the BepInEx log before any number.** `FrameGapArmed` is emitted nowhere — not on the line, not in
`cfg`, not in the header — so `null` covers *both* "never armed" and "pairing invalid this frame", and only
the absence of the `inter-frame gap not armed` warning separates them. That is the
[log-not-data failure](#open) work-queue item 4 exists for, occurring in the field built so that a `null` and
a zero could not be confused. One `cfg` line fixes it, after the run.

**Two things about the coming logs that are the instrument, not the game.** `Expand phase` became the
blocklist `Do not expand phases`, blank by default, so **all eight top-level phases expand** where the
previous fifteen logs expanded `PreLateUpdate` only. Child-level series therefore **do not join across that
boundary**; top-level phases and `unaccounted` still do, since `accounted` sums only non-child slots. And
every child adds a Begin/End pair — roughly 140–200 extra QPC reads per frame, **3.5–5 µs landing inside the
top-level totals**. Against a 200–330 ms family that is nothing, and against `render` at 6.5 ms it is
0.05–0.08% — but it is not zero, and it is in the direction that reads as a regression. Do not report a few
microseconds of `render` growth across this boundary as one.

##### The axis is not GC and not raid phase — it is whether BSG's measurer registered the block

Added 2026-07-28, Delta, after auditing a grouping I had drawn myself. All 64 in-raid residual-dominant spike
frames across every log, split **before** looking at collections:

| | n | period, median | carrying a collection | `TimeUpdate` ≥ 0.5 ms |
|---|---|---|---|---|
| **A** — `frame < period / 2` | 28 | **130.5 ms** | **14 of 28** | 21 of 28 |
| **B** — `frame ≥ period / 2` | 36 | **333.9 ms** | **0 of 36** | **0 of 36** |

**Within A, collection status makes no difference to period at all** — 128.5 ms with, 140.5 ms without. So the
axis is A versus B, and it is neither of the two divisions anyone had been using: not early-versus-late raid,
and not GC-versus-not.

**This retires a test that looked like evidence.** A comparison of period between collection and
non-collection frames gave "with-collection is 77 ms *shorter*", read as ruling out an additive merge. It does
not: the effect is the A/B split wearing a GC label, and it largely disappears on conditioning. **"Does not
bear on the merge" would be slightly too strong** (Gamma, and the correction is theirs): within A the additive
model still predicts with-collection *longer*, and it is −12.0 ms on medians and −52.6 on means, n = 14 per
arm. That is a **low-powered null leaning against additive** — untested rather than unrelated, since the sign
is at least not the one the merge needs. **The tightened
version of that test was worse** — the tightening criterion is met by 0 of 14 collection frames, so applying
it to one arm only deleted the 14 non-collection frames nearest the other arm (median 140.5 ms) and widened
the gap from 77 to 205 ms. **An asymmetric filter anti-correlated with the outcome always widens the gap**,
and "tightening made the effect larger, so the filter was not doing the work" inverts the check.

~~**What survives is a presence statement rather than a distribution shift**, which is why it is worth more:
collections occur in A only, 14 of 28, and in B **never**, 0 of 36.~~ The entanglement flagged here was real
and **the presence statement does not survive it.** Gamma proposed the deciding query — *A holds 7 frames with
`TimeUpdate < 0.5 ms`; if none carries a collection then `TimeUpdate` is the predictor and A/B adds nothing
for GC.* Run: **0 of 7.** Full cross-tab:

| | collections | none | n | period median |
|---|---|---|---|---|
| A, `TimeUpdate ≥ 0.5` | **14** | 7 | 21 | 129.6 |
| A, `TimeUpdate < 0.5` | **0** | 7 | 7 | 138.9 |
| B, `TimeUpdate ≥ 0.5` | — | — | **0** | — |
| B, `TimeUpdate < 0.5` | **0** | 36 | 36 | **333.9** |

**Collections require `TimeUpdate ≥ 0.5 ms` — 14 of 14 — and B never has one.** So *"no collections in B"* is
"no slice in B" restated, and it is **one fact, not two**, exactly as suspected. A collection completes during
a slice, so this is close to definitional and is not independent evidence about the A/B axis.

**What does survive, and it is now better tested than before.** Holding `TimeUpdate < 0.5` — comparing like
with like — the frame criterion still tracks event size, independent of GC:

| | n | min | median | max | distinct logs |
|---|---|---|---|---|---|
| A, `frame < period/2` | 7 | 104.6 | **138.9** | 231.1 | 5 |
| B, `frame ≥ period/2` | 36 | 165.2 | **333.9** | 401.7 | 7 |

~~the frame criterion still **separates** event size~~ — **too strong** (Gamma, and the correction is theirs).
**B is stochastically larger — Mann-Whitney AUC 0.901 — with substantially overlapping ranges.** The overlap
band is 165.2–231.1 ms: **15 of 36 B frames sit inside A's range and 3 of 7 A frames inside B's.** So this is
**a split in event size, not a partition** — written as a partition it will be read as two classes, and the
next person to find a 200 ms frame will not be able to say which family it belongs to.

**The check that mattered at n = 7 passes:** A spans **5** distinct logs and B **7**, so neither is one
session's artifact — which was the live risk at that sample size and is not present.

**The B / `TimeUpdate ≥ 0.5` cell is empty**, so the two criteria are nearly nested and cannot be fully
separated with this data. Stated because it bounds everything above: the A/B axis is established as a split on
event size and **not** established as independent of the slice.

**So the merge question reduces to whether the A/B criterion means anything**, and
[the mechanism behind it is withdrawn](#corrected-2026-07-28-delta--the-separation-is-real-the-mechanism-i-attached-to-it-is-not).
`endToStart` is the instrument for exactly that: **if A and B read the same `gap`, the criterion is an
artifact and they are one family.** Register the prediction on this axis rather than on GC status — B ~330 ms,
A ~130 ms with a 3.02 ms slice inside the half that collects.

#### The corrected finding is stronger than the one it replaces

This is not a retreat. The published claim was about a **phase** — "collections land in `TimeUpdate`" — and
the selection error cut it to 22 of 36. The corrected claim is about a **mechanism**:

> **Collections land at the frame boundary, and the `TimeUpdate` marker bisects them: 22 just inside, 13 just
> outside. 36 of 36.**

FINDINGS already supplied the reason, before any of this was measured: *"the phase is simply the first one in
the frame, so anything that blocks the main thread at a frame boundary lands there."* The residual is the gap
immediately *before* that first phase, so both populations are the same event landing either side of one
marker — and the instrument is honest about the side it cannot name, emitting nothing rather than guessing.

So the finding survived the correction, **generalised from 23 frames to 36, gained a mechanism, and stopped
depending on which phase happens to be bracketed.** It was arrived at by chasing an error rather than by
looking for a result, which is the only reason it was found at all.

#### Amended 2026-07-28, Delta — "36 of 36" is true, and it invites an inverse that is a coin flip

The claim above is **correct**: every one of the 36 collections does land at a frame boundary, and the
`frame ≪ period` test confirms it on 13 of 13 of the outside half. Nothing there is withdrawn. What is wrong
is the completeness the phrasing implies, and it is wrong in a direction a reader will predictably take.

**The residual-dominant bucket is not GC-pure. It holds 25 in-raid spike frames, not 13** — and the twelve
without a collection are the *larger* group:

| in-raid, residual-dominant | n | period, median | `unaccounted`, median |
|---|---|---|---|
| with a collection | 13 | 128.4 ms | 113.8 ms |
| **no collection at all** | **12** | **201.9 ms** | **186.8 ms** |

So state both directions here too, because again only one survives:

- **`TimeUpdate`-dominant ⇒ a collection: 22 of 22.** Untouched.
- **Residual-dominant ⇒ a collection: 13 of 25.** A coin flip. Residual-dominance is *not* diagnostic of GC.

The thirteen are still collections — raid 2 runs one collection per 2,629 frames, so thirteen hits on
twenty-five frames is enriched by three orders of magnitude. **The defect is not correctness, it is that
"36 of 36" reads as "the residual bucket is accounted for", and half of it is not.**

**The twelve are the open second family, not a new one.** Nine of twelve sit at `raidElapsed` 1.1–82.7 s with
`TimeUpdate` absent on all twelve — which is [stage 1's description](#timeupdate--a-spike-family-that-is-not-ours--wrong-it-is-garbage-collection)
of it verbatim: *"150–350 ms spikes confined to the first minute or two of a raid, with `TimeUpdate` at zero."*
Two independent signatures identifying the same population four days apart. **The remaining three sit at 430.1,
431.0 and 721.7 s and that framing does not cover them** — call it out rather than round it off.

PresentMon says they are real and CPU-side, joined by containment: `CPUBusy` median **203.2 ms**, `GPUBusy`
median 6.50 against a capture p50 of 6.19, `asyncUpdate` 0.001 and `drained` 0 on every one. So the largest
unexplained in-raid family left is **the same size as the GC one and has never had a name**.

**`heapDeltaMb` cannot be cited as corroboration, and the reason is structural.** `Telemetry.cs` emits it
inside a block gated on `_gcThisFrame > 0`, so it is present on 13 of 13 of the collection frames and **0 of
12** of the others. The comment at the gate claims a negative delta *"confirms the pause was a collection
rather than something correlated with one"* — it cannot. It confirms a collection **completed**; the twelve
counterexamples are invisible to it by construction. ~~Use `frame ≪ period` instead, which is emitted
unconditionally.~~ **`frame ≪ period` is a classifier on this population and not a general GC test — see the
correction above.** `endToStart` is the field that answers it.

**This is the seventh instance of [a population defined by the instrument's success](#methodology-notes), and
it is inside the correction written to fix the sixth.** The class of defect is not retired by fixing an
instance — the same thing the `MonoBehaviour` → `Behaviour` → `Component` chain already says, three
consecutive widenings each returning clean. Worth the entry saying it about itself: this section corrected a
population defined by `gcPhase` being present, and immediately defined a new one by `gcGen0 > 0`.

**It was also known and not carried in.** The mixed composition of the residual bucket was reported the night
before this section was written — *"on Customs 24 spike frames residual-dominant, only 12 carry a
collection"* — and the section was then built around "36 of 36" anyway. **Knowing and not folding it in is a
worse failure than not knowing**, and it is the one the methodology note exists to catch.

#### Phase attribution is map-dependent, which weakens the two-map claim

Twelve of the thirteen unattributed frames are Customs. Streets attributes 10 of 11; Customs attributes 13 of
25. **The two maps do not behave the same**, so ~~"confirmed on two maps, by two independent instruments, with
phase-level attribution"~~ is carrying less weight than the sentence implies. Consistent with the standing rule
that absolute figures and now attribution ratios do not transfer between maps.

#### What is unaffected — read this before revising anything downstream

**The heap-scaling refutation stands, on the corrected population.** Recomputing mean pause over *all* 36
collection frames — dominant-phase ms, so `unaccounted` for the residual-dominant ones:

| | heap | mean pause, published (n) | mean pause, all frames (n) |
|---|---|---|---|
| arm 1, Streets | 2,714 MB | 90.2 ms (9) | **92.2 ms (11)** |
| arm 2, Customs | 4,877 MB | 115.5 ms (13) | **120.1 ms (25)** |

**+30% pause for +80% heap**, against the +28% published. The 52 ms/GB linear model is still refuted, by very
nearly the same margin, and everything resting on it — that `heapMb` is the wrong variable, that reclaim per
collection *fell* while the heap nearly doubled, that "restart every N raids" loses most of its force —
is unchanged.

**The PresentMon corroboration is unaffected**, and it never depended on phase attribution: `GPUBusy` on the
Customs collection frames runs **5.59–6.33 ms** against a whole-capture p50 of **6.19 ms**. The GPU does an
ordinary frame's work through every one, whichever phase the pause is named for — or none.

`heapDeltaMb` is negative on almost all 36: −37 to −463 MB on Streets, −2 to −361 MB on Customs, and −1 to
−1,003 MB on the thirteen unattributed frames. That the residual-dominant frames reclaim on the same scale is
the second reason to read them as collections rather than as something else that happens to coincide.

#### The lesson, which is the one this document already has and did not apply

A filter was validated against what it was meant to *keep* rather than against what it would *remove* — the
same failure recorded twice in the methodology notes, once for a `period > 10 s` cut and once for
`asyncUpdate / period`. **The tell was available without any new data: 23 attributed frames against 36
carrying `gcGen0 > 0` is a discrepancy visible by counting one field against another on the same lines.**
An absent field is a silent exclusion, and a population defined by "the field is present" is a population
defined by the instrument's success.

### The heap-scaling claim is refuted, and it was measuring the wrong thing

Extrapolating stage 3's 52 ms/GB from Streets to Customs:

| | heap | mean pause | |
|---|---|---|---|
| arm 1, Streets | 2,714 MB | **90.2 ms** | n=9 |
| arm 2, Customs | 4,877 MB | **115.5 ms** | n=13 |
| *predicted at 4,877 MB* | | *200 ms* | **+73% error** |

Heap rose **80%**; pause rose **28%**. The implied cross-map slope is **12.0 ms/GB** against 52.2 ms/GB from
the Streets pair. So cost rises with heap far less than linearly, and the 52 ms/GB figure does not extrapolate
at all. The map changed too, so this cannot separate "sublinear" from "map-dependent" — but either way the
linear model is gone, and with it most of the force behind a "restart every N raids" recommendation: going
2.7 → 4.9 GB cost 25 ms per collection, not 110.

**And `heapMb` is not the variable that matters.** Window `heapMb.min` sits at 4,791 MB against an average of
4,877 — the heap essentially never dips. On Boehm, `GC.GetTotalMemory(false)` reports **heap size including
free blocks**, not live set, so a heap that grew to 4.9 GB may hold no more reachable data than one at 2.7 GB.
Mark cost scales with the **live set**. Nothing in this telemetry measures the live set, which is a sufficient
explanation for why pause cost does not track `heapMb` and means the whole heap-scaling framing has been
regressing against the wrong column.

Corroborating: reclaim per collection **fell** from 200 MB (Streets) to 109 MB (Customs) while the heap nearly
doubled. More heap, not more garbage.

### Reflex, unplanned, closed a confound by measurement

Stage 3's heap comparison was confounded with Reflex (raid 1 off, raid 2 on). Both control arms ran Reflex
**on**, which makes arm 1 directly comparable to stage 3's raid 2. The PMC session's `controllerInitMs`
replicates across Reflex states to **1.3%** (13,804.7 ms off, 13,986.6 ms on, both cold Streets), so Reflex
has no measurable effect on raid initialisation. A matched-Reflex run would have left that untested.

### The QPC join works

145 of 145 spike lines fell inside the capture range with **no landmark offset**, 107 matched to a PresentMon
frame at 8.39 ms median alignment. Mono's process-relative `Stopwatch` epoch is fixed; joins are now direct.

### The cross-instrument invariant was run, and it passes

Two sessions instrument the same frame by different routes — collections per player-loop phase, and
collections per raid-init segment — and agreed an invariant to catch a defect in either. It appears never to
have been executed. Run against the control log 2026-07-28:

| | arm 1, Streets | arm 2, Customs |
|---|---|---|
| `sum(SegGen0)` | 0 | 0 |
| `Update` phase `gen0` on the raid-init frame | 4 | 5 |
| `cfg.drainInUpdateOnly` | true | true |

`sum(SegGen0) <= Update gen0 + FixedUpdate gen0` holds, and so does the tight form. The sharper prediction
holds too: **`gcPhase` reads `Update` on the 18,251 ms raid-init callback frame**, which is what it must read
if raid-init collections are nested inside the drain rather than being something else. Had it read
`TimeUpdate` while a segment claimed a collection, that would have been a contradiction rather than a
difference in granularity.

Worth recording as executed rather than merely specified. An agreed check that nobody runs is indistinguishable
from no check, and this one confirms both instruments against each other on the run every stage-4 conclusion
rests on.

### The four forced collections reproduce a measurement from days earlier

The PMC callback in arm 1 carries **exactly 4 collections** with `suspendGc` true, and `GCMode` is `Disabled`
for the whole callback (`AsyncDrain.RunCallback` restores in a `finally` around the entire queued action). So
those four ran *while collection was disabled*.

That number is not new. The original suspend-GC experiment measured
[collections 20 → 4](#the-167-s-pmc-bot-generation-callback--solved-it-is-raid-initialisation-not-bot-generation)
for the same callback. **The same irreducible 4, reproduced independently.** `GCMode.Disabled` prevents 16 and cannot
prevent 4, which is direct evidence for forced collections — allocation that cannot wait — rather than the
inferred version.

### ~~The 20 → 4 experiment bounds collection cost at ~65 ms~~ — WITHDRAWN, the effect is the noise floor

Briefly recorded here as "1,046 ms for 16 fewer collections, ~65 ms each". It does not survive provenance
checking, and the reason is the config-hygiene failure this document already records twice.

**The control arm does not record the treatment variable.** The 0058 run's `cfg` block has 11 keys —
`standBy, leakFix, brainPeriod, fastAnim, cullSleeping, maxDelta, skipLate, skipTick, jobBudgetMs,
jobSlowFrames, asyncBudgetMs` — and **no `suspendGc`**, because that field did not exist in that build. The
0107 treatment arm has 15 keys including `suspendGc: true`. So the two arms are different *builds* and the
control's actual suspend state is unrecorded. Verified directly against both logs.

**Decisive: the claimed effect is smaller than the same-treatment spread.** Two runs with identical treatment —
both cold Streets, both `suspendGc: true`, both `gen0: 4` on the callback:

| | callback |
|---|---|
| 0107 | 16,759.1 ms |
| control arm 1 | 17,710.8 ms |
| **spread, same treatment** | **951.7 ms** |
| claimed GC saving | 1,046 ms |

An effect of 1,046 ms against a 952 ms replicate spread establishes nothing. Payloads also differed
(`pmcUSECx4+pmcBEARx13` / 465 KB against `pmcBEARx10` / 230 KB).

**So the cost of a collection inside a suspended non-yielding span is unmeasured.** Not 895 ms, not 360 ms,
not 65 ms. Three estimates, three different methods, no measurement. The 4 forced collections are also present
in both arms of that experiment and cancel in its difference, so it could not have bounded them even had the
arms been matched.

**A mechanistic reason the forced collections could be far costlier than the preventable ones.** In Boehm,
mark cost scales with the **live set** but sweep cost scales with the **heap size**, because sweep walks the
whole heap's block structure. Combined with `GC.GetTotalMemory(false)` reporting heap-including-free-blocks:
an unsuspended arm collects continuously and never lets the heap expand far, so each collection sweeps a small
heap; a suspended arm lets it expand without bound between forced collections — `initHeapDeltaMb` reports
+6.9 GB on the one raid where `zoneLeaveCtor` ran long — so a forced collection sweeps a far larger heap at
roughly constant live set.

That predicts the asymmetry without requiring the forced collections to reclaim more live data, and it maps
onto the two open candidates: **if the extra cost is sweep, it is the non-incremental phase and no scheduling
knob can touch it.** Mark and sweep are separable in a heap trace — mark is a plateau, sweep is the drop — so
the off-thread sampler can distinguish them, which neither the slice nor the drive experiment can.

### Artifact to filter

The Customs arm opens with a spike line of **545,800 ms** carrying 20 collections and `TimeUpdate` at
437,918 ms — the client sitting at the menu, not a stall. Stage 3 had the same thing at 1,149,837 ms. It is
`TimeUpdate`-dominant with `gcGen0: 20`, so it pollutes exactly the statistic the GC finding rests on and must
be excluded from any pooled figure.

**Threshold: ~60 s. Not 10 s.** An earlier revision of this section said 10 s and justified it as "safely
above every real stall measured (the largest is the 36 s `/client/match/local/start`)" — a sentence containing
its own refutation, since 10 s is *below* 36 s. Every spike line above 10 s in the control run:

| period | state | gen0 | dominant | `asyncUpdate` | |
|---|---|---|---|---|---|
| 545,800.0 | loading | 20 | `TimeUpdate` 437,918 | 5,623 | **menu idle** |
| 36,917.7 | loading | 0 | `Update` 36,210 | 36,171 | real — `/client/match/local/start` |
| 20,990.2 | loading | 0 | `Update` 20,934 | 20,887 | real |
| 18,251.1 | loading | **4** | `Update` 18,097 | 17,713 | **real — the raid-init callback** |

A 10 s cut deletes three real stalls including the frame carrying the four forced collections, the 3,584 ms
gap and the 6.9 GB anomaly. Largest real stall is 36,917.7 ms, smallest artifact 545,800 ms — a **15× gap**,
so anything in 50,000–400,000 ms works and 60 s has margin on both sides.

**Rejected discriminator: `asyncUpdate / period`.** Proposed here as "better than a threshold" on the grounds
that real stalls are drain callbacks running ~99% while the artifact is 1%. It is a **drain detector, not an
artifact detector**, and the ratio runs the wrong way:

| population | ratio |
|---|---|
| drain stalls (`local/start`, raid-init) | 0.98, 0.97 |
| **menu artifact** | **0.0103** |
| **all 36 in-raid collection frames** | **0.0000** |

The artifact's ratio is *higher* than every GC frame's, because a GC pause has no drain in it at all. So any
cut that removes the artifact necessarily removes all 36 collection frames — the exact population the
`TimeUpdate` attribution rests on — and any cut that keeps them keeps the artifact. The metric is
anti-correlated with the thing it was proposed to detect. It would also delete real non-drain loading stalls
(5,633 ms / `PreLateUpdate` / `gcGen0: 5`, and others).

**Use `period > 60000`.** Threshold-dependence is a real weakness, but a wrong discriminator is worse than a
crude one.

**The durable fix is the mislabel.** Gate `CurrentState()` on the game object rather than on `GameWorld`'s
existence — `Menu` when `Singleton<AbstractGame>` is absent or its `Status` is terminal. Then `state == 'menu'`
excludes the artifact exactly, with no threshold and no ratio, and sampling stops at the menu as originally
intended.

**`state` will not do the job, and the reason is a mislabel worth knowing.** The menu-idle line reads
`state: loading`, not `menu`. `CurrentState()` returns `Loading` whenever `GameWorld` is instantiated and
`GameStatus != Started`, which is true sitting at the menu with a world still resident — and sampling
continues, because the `Menu` early-return needs `GameWorld` to be *gone*. Only `loading` and `raid` ever
appear on spike lines.

*The stage-4 in-raid figures above are unaffected* — every one filters `state == 'raid'`, and both artifacts
are `loading`. The hazard is to pooled or loading-regime statistics.

---

## Confirmed fixes

### 1. Cull sleeping bot animators — ~3.3 ms

`EFTHardSettings.AnimatorCullDistance` is 10 m, so `Player.VisualPass` puts nearly every bot into
`AnimatorCullingMode.CullUpdateTransforms`, which skips transform writes off-screen but **still
evaluates the state machine every frame**. `CullCompletely` skips evaluation outright. Safe for
`BotStandByType.paused` bots specifically: they are already posed and stationary, so no root motion
is lost.

36 bots, 24 asleep, one position:

| windows | culling | animation | frame | fps |
|---|---|---|---|---|
| 16–18 | off | 6.94 ms | 19.83 ms | 50.4 |
| 22–24 | **on** | **3.66 ms** | **16.35 ms** | **61.2** |
| 26–29 | off | 6.78 ms | 20.42 ms | 49.0 |

Per-bot: uncelled ~0.193 ms, culled ~0.056 ms — a 71% cut. Saving scales with how many bots are
asleep *and* off-screen, and does nothing below ~11 asleep.

### 2. Skip `Player.LateUpdate` for sleeping bots — ~2.3 ms

28 bots, 24 asleep, one position:

| windows | skip | frame | fps | `playerLate` | `scripts` |
|---|---|---|---|---|---|
| 11–14 | off | 12.60 ms | 79.4 | 0.969 ms | 2.81 ms |
| 15–19 | **on** | **10.33 ms** | **96.8** | **0.275 ms** | 1.64 ms |
| 40–42 | off | — | — | 0.74–1.18 ms | — |

`Player.LateUpdate` fell 72% and returned when switched off.

**Interaction to preserve:** `VisualPass()` is called *from* `Player.LateUpdate`, and the animator
cull is a postfix on `VisualPass`. Skipping `LateUpdate` naively also skips the cull, so the two
features cancel out and the skip appears to do nothing. Both paths go through
`SleepingBotAnimatorPatch.ApplyIfSleeping`, which culls before bailing.

### 3. Skip `GameWorld` per-player tick for sleeping bots — ~0.45 ms

`playerTick` 0.594 → 0.147 ms (−75%). Small but clean and reversible.

**Safety, established from code rather than observation:** `GameWorld.smethod_2` → `Player.UpdateTick`
→ `ComplexUpdate(Update, dt)` drives only `ManualUpdate` (movement), `ArmsUpdate`, `Physical.Update`
(stamina), and `UpdateEvent`. That event has exactly three subscribers assembly-wide —
`ObstacleCollisionFacade.Tick`, `CurrentManagedState.Vaulting()`, `_vaultingComponent.DoVaultingTick`.
No health controller, no effects. **Bleeding is not ticked through this path**, so sleeping bots
still bleed out normally.

### 4. Cap `Time.maximumDeltaTime` — spawn spiral 79% smaller

Unity's default 0.333 s lets one slow frame schedule a flood of catch-up physics steps, each making
the next frame slower. Worst observed `fixedUpdate` fell from **439.3 ms to 92.5 ms** at 0.1.

Spawn-in is still expensive on its own (191 ms frame, `scripts` 51.8 ms as 26 bots arrive) — the
spiral no longer compounds it.

---

## Refuted — do not re-tread

1. **Bot AI CPU cost.** The entire AI tick (`BotsController.method_0` — every brain, every
   `BotOwner.UpdateManual`) is **0.13–0.55 ms**, about 1–2% of the frame, and does not change between
   Customs and Streets. The stand-by and dead-agent-leak patches work exactly as designed and save
   roughly 0.1 ms. Cover search (`GClass381.GetCover` → `method_6`) is a fraction of that.

2. **GC pressure.** Across 4,249 spike frames, **30 coincided with a collection — 0.7%**. Steady state
   runs 0–6 collections/minute against a 2.7–3.1 GB heap. Note Unity's Mono uses Boehm, which is
   non-generational: `GC.CollectionCount(n)` returns the same value for all n, so the gen split is
   meaningless. Loading *is* allocation-heavy (144 collections/min at 23 MB/s) but that is separate.

   **Scope this to its population.** It was measured when the drain produced the overwhelming majority of
   spikes, so it says GC was not *the* in-raid stutter — which remains true. It does not say collections
   are cheap. With the drain gone, 14 of 14 remaining `TimeUpdate` spikes are collections, each 80–120 ms:
   [stage 3](#gpu-side-telemetry--stage-3-2026-07-27). A coincidence rate is a statement about the
   denominator as much as the numerator, and the denominator changed.

3. **The recurring ~350 ms hitch was ALT-Tab.** It appeared in 11 of 15 windows in one run and
   vanished entirely in a run with no tabbing out. Confirmed by reconciliation: `sum(phases)` matches
   `frame` to within 0.087 ms mean when clean, and drifts 0.4–1.5 ms per window when tabbing occurred.
   Window-focus stalls happen in the OS message pump, outside every player-loop phase.

4. **`UseBodyFastAnimator`.** Ships disabled and is unreachable normally (`client.config.json` does not
   exist, the field has no initialiser, `PatchConfig` only copies `BackendUrl`/`MatchingVersion`).
   Forcing it on makes the game unplayable — missing weapon textures, no ADS, broken movement input.
   It also would not have helped: `_bodyUpdateMode` becomes `Manual`, relocating cost into
   `ScriptRunBehaviourLateUpdate` at roughly 10× Unity's per-bot price.

5. **`AmbientLight` — refuted on Streets only, and that distinction matters.** Its `LateUpdate` measured
   exactly 0 there because the component is *inactive on that map*, not because it is cheap. On **Customs
   it does run**: avg 0.107 ms, max 4.63 ms. So the 2023 report of 5 ms/frame is half right — the peak
   matches, the average does not, meaning it spikes occasionally rather than costing every frame. At ~1.3%
   of frame it is not a priority, but it must stay instrumented on every non-Streets map.

6. **Texture streaming.** `Mip Streaming` off sets `QualitySettings.streamingMipmapsActive = false`.
   "Streets Lower Texture Resolution Mode" (`SDModeController`) is a one-time
   `globalTextureMipmapLimit` bump at `Awake`, applying only when Mip Streaming is off. Neither does
   per-frame work.

7. **Animators on dead bots.** Refuted from source 2026-07-28, without a build or a raid.
   `Player.OnDead` zeroes `EnabledAnimators` and disables both animators outright
   ([Player.cs:7452](../../Src/Assembly-CSharp/EFT/Player.cs:7452)):

   ```csharp
   this.EnabledAnimators = (Player.EAnimatorMask)0;
   this.BodyAnimatorCommon.enabled = false;
   if (BackendConfigAbstractClass.Config.UseBodyFastAnimator) { this.PlayerBones.PlayableAnimator.Stop(); }
   this.ArmsAnimatorCommon.enabled = false;
   ```

   `OnDead` is `virtual`, so the override chain decides whether bots get this. Only two overrides exist —
   `ClientPlayer` and `LocalPlayer` — and `LocalPlayer.OnDead`
   ([LocalPlayer.cs:215](../../Src/Assembly-CSharp/EFT/LocalPlayer.cs:215)) is the AI path and calls
   `base.OnDead(damageType)` after its AI-only branch. A disabled `Animator` does not evaluate at all, so
   the `CullUpdateTransforms`-still-runs-the-state-machine mechanism that [fix 1](#1-cull-sleeping-bot-animators--33-ms)
   exploits never arises for a corpse. There is no culling mode to ask about.

   **The follow-on is also negative, and it is the more useful half.** A corpse keeps the `Player`
   MonoBehaviour — `Corpse.CreateCorpse` does `AddComponent` on the *same* GameObject — so
   `Player.LateUpdate` runs for every corpse for the rest of the raid. But
   [Player.cs:1562](../../Src/Assembly-CSharp/EFT/Player.cs:1562) guards `Physical.LateUpdate()`,
   `VisualPass()` and the beacon raycast behind `HealthController.IsAlive`. Outside that guard sit
   `MovementContext.AnimatorStatesLateUpdate()`, two bool writes, and — the one an earlier revision of this
   entry missed — `ComplexLateUpdate(EUpdateQueue.Update, DeltaTime)` at
   [Player.cs:1604](../../Src/Assembly-CSharp/EFT/Player.cs:1604), where line 1603 closes the `IsAlive`
   block. `AnimatorStatesLateUpdate` ([MovementContext.cs:1110](../../Src/Assembly-CSharp/EFT/MovementContext.cs:1110))
   is a single `if (ScheduleDirectApplyMotion)`, false on a corpse. `ComplexLateUpdate` resolves to
   `MovementContext.LateFixedUpdate()` — a guarded no-op once the character controller is off, plus
   `PlayerAnimator.EventsDispatcher.EmitEvents()` — and `AIData.LateUpdate()`, whose body is empty
   (`GClass591.cs:555`). **Three calls deep rather than two bool writes, and still not a lever**, though
   `EmitEvents()` is asserted cheap from the animator being disabled rather than read.

   So corpse accumulation cannot explain in-raid degradation over a long raid, and the "it gets worse the
   longer I play" complaint does not get to be about corpses. That hypothesis had the right shape — per-frame
   work for a bot nobody can see, accumulating monotonically, in the one population
   [the animator cull cannot reach](#1-cull-sleeping-bot-animators--33-ms) because it keys off
   `BotStandByType.paused` and a corpse never enters that state. It is simply not what the code does.

   **A near-miss worth recording, because reading only `Corpse.cs` gives the right answer for the wrong
   reason.** `Corpse.CreateStillCorpse` walks every child `Animator`, calls `Update(0f)` to settle the pose,
   then disables it ([Corpse.cs:102](../../Src/Assembly-CSharp/EFT/Interactive/Corpse.cs:102)) — but that is
   the JSON path for corpses already present at load. In-raid deaths go through `CreateCorpse` at line 72,
   which does not touch animators, because `OnDead` already has. Same conclusion, different code path, and
   believing the wrong one would mislead the moment the distinction mattered.

   `GClass921.cs:195` disables `BodyAnimator` on the `ObservedPlayerView` death path too. Not the path SPT
   takes, but it establishes that BSG does this deliberately in both character representations rather than
   by accident in one.

   **The override-chain dependency is now closed, including the case that could have inverted it.** All of
   `F:\SPT\Community` was grepped, not only `modules-master`: no SPT module patches `OnDead`, and SAIN,
   QuestingBots, LootingBots, AILimit and BigBrain are clean. ORBIT's apparent hit subscribes to the
   `OnPlayerDead` *event* rather than patching the method. **Fika does patch it**, and survives anyway:
   `Player_OnDead_Patch` is a transpiler replacing the whole body of `LocalPlayer.OnDead` with
   `call Player.OnDead; ret`, so the AI-only branch is discarded but `Player.OnDead` still runs and the
   animator disable holds.

   That last one is a Fika behaviour change worth a COMPATIBILITY.md line on its own account: **under Fika,
   AI bots silently lose `DisableCullingOnDead()` and their dogtag info**, because the transpiler throws away
   the entire branch rather than only the dogtag call it was presumably aimed at. Exactly the kind of thing
   this mod could have been blamed for.

   **`WeaponSoundPlayer` survives death and then quiesces on its own** — the residual this question was
   really reaching for, and it is also negative. The component lives on `_controllerObject`, the weapon
   prefab, not the player root ([Player.cs:14661](../../Src/Assembly-CSharp/EFT/Player.cs:14661)). Base
   `HandsController.OnPlayerDead()` is empty and `FirearmController`'s override only fast-forwards the
   operation and drops the ballistic calculator, so nothing disables or pools the weapon object until
   `HandsController.Destroy()` at raid teardown. But `Update` releases its audio queue once
   `dspTime > _releaseTime` and nulls `_queue`, after which it early-returns; `_queue` is only re-borrowed on
   firing, which a corpse never does. Steady-state corpse cost is a null check and a bool test. The existing
   measurement of **0.002–0.005 ms across 43–49 instances** was taken against 37 bots, so it already
   included corpses and is an upper bound rather than a live-only figure.

   **Ragdoll physics is handled by BSG too.** `RagdollClass` walks `PlayerRigidbodySleepHierarchy.TryPutToSleep()`
   and sets `isKinematic = true` once `CheckCorpseIsStill` passes; sleep is on unless `forceStill` or
   `DEBUG_CORPSE_PHYSICS`.

   **What is narrowed rather than answered.** Four subsystems were checked by name — animators, `Player.LateUpdate`,
   weapon audio, ragdoll — and all four are disabled, gated, empty or self-quiescing. Nobody has enumerated
   every component on a bot GameObject, and reading source one suspect at a time can only ever produce more
   negatives. The way to close the class rather than the instances is a one-shot component census, spec in
   [COORDINATION.md](COORDINATION.md) — `GetComponentsInChildren<Component>()` on one bot across a prefix and
   postfix pair on `Player.OnDead`, logging the diff of what is still `enabled`.

   ~~Dump `GetComponents<MonoBehaviour>()` on a bot at spawn and again on a corpse.~~ **That sketch — written
   here before the spec was reviewed — contained two of the four defects the review then caught, and is left
   struck through rather than deleted because it is the best available illustration of them.** `MonoBehaviour`
   cannot see `Animator`, which derives from `Behaviour`; widening to `Behaviour` still cannot see the ragdoll
   or any renderer, since `Renderer`, `Collider`, `Rigidbody`, `Cloth` and `ParticleSystem` derive from
   `Component` directly. And sampling "at spawn and again on a corpse" compares two different bots minutes
   apart, confounding death with role, loadout and raid phase; the prefix/postfix pair reads one object across
   one method instead. Full accounting of all four defects is in the methodology note on
   [a correct rule applied where it does not bite](#methodology-notes).

---

## The architectural cause

Offline/SPT bots are **full `LocalPlayer` MonoBehaviours** — `Player.Create<LocalPlayer>(...)` with
`aiControl` ([LocalPlayer.cs:25](../../Src/Assembly-CSharp/Assembly-CSharp/EFT/LocalPlayer.cs)) —
carrying the complete stack: inventory, health controller, physical, movement context, procedural
weapon animation, hit colliders. Identical machinery to the local player, ×N.

Online, remote characters are `ObservedPlayerView` / `ObservedPlayerController`, a far lighter
representation with its own `LateUpdate` and animator handling.

Measured local-only surplus at 34–36 bots: `playerLate` 1.15–2.70 ms (55–60% of all
`ScriptRunBehaviourLateUpdate`) plus `playerTick` 0.78–0.99 ms (~25% of the whole `Update` phase) —
**2–3.6 ms, 10–18% of frame time.** This is why offline has always been worse than live despite
rendering comparable character counts, and it is what fixes 2 and 3 above exploit.

---

### 5. Budget the `AsyncWorker` completion drain — the FixedUpdate freezes

**Cause confirmed, attribution total.** The 800–2600 ms FixedUpdate freezes are
`GClass1516.CheckForFinishedTasks` and nothing else. Five independent occurrences in one Streets raid:

| window | `FixedUpdate` max | `asyncFixedDrain` max | `fixedSteps` max |
|---|---|---|---|
| 10 | 717.7 ms | 717.2 ms | 6 |
| 11 | 1499.8 ms | 1499.5 ms | 6 |
| 14 | 2588.4 ms | 2588.2 ms | 6 |
| 31 | 1103.8 ms | 1103.6 ms | 6 |
| 32 | 155.6 ms | 155.5 ms | 6 |

The drain accounts for the spike to within 0.3 ms every time, and `fixedSteps` never exceeds 6 with
`maxDeltaTime` at 0.1. **This kills the catch-up-spiral theory outright** — it is one physics step
containing one enormous call, not many steps.

Two loading-time occurrences are far larger still: 15,135 ms and **35,280 ms**, both matching their
frame to within 5 ms.

Mechanism: the queue holds `Action`s that are just `TaskCompletionSource.SetResult`. `SetResult` runs
its continuations **inline**, so the whole downstream `async` method body executes on the main thread
inside the drain. `AsyncWorker` calls the drain from both `Update` and `FixedUpdate`, unbounded.

`AsyncDrainPatch` replaces it with a time-budgeted drain that always executes at least one callback and
defers the remainder to the next call. Nothing is dropped and ordering is unchanged. It deliberately
does not apply outside `GameStatus.Started`, since rationing the 35 s loading drain would only stretch
the loading screen.

**Identified: it is SPT's `/client/game/bot/generate`, and the cost is linear in response size.**

Every single stall in the 2026-07-26 09:43 raid resolved to the same endpoint. Nothing else appeared:

| response | stall | µs per 1000 chars |
|---|---|---|
| 35 KB | 13.5 ms | 0.38 |
| 308 KB | 86.3 ms | 0.28 |
| 315 KB | 106.8 ms | 0.34 |
| 495 KB | 263.0 ms | 0.53 |
| 527 KB | 166.9 ms | 0.32 |
| 1.34 MB | 452.7 ms | 0.34 |
| 1.61 MB | 550.4 ms | 0.34 |
| **1.84 MB** | **1866.6 ms** | **1.01** |

Flat at ~0.34 µs/char up to ~1.6 MB, then 3× worse — the largest response costs three times what its size predicts, so there is a threshold effect (almost certainly allocation) on top of the linear parse.

**Why a batch of 45 when a wave is nowhere near that big.** The client does not ask for 45. Tracing it:

- `BotsPresets.CreateProfile` first tries `GetNewProfile(data)` against the local pool `List_0`.
- On a miss it builds **`new WaveInfoClass(3, role, difficulty)`** — a request for **three** bots —
  and calls `ISession.LoadBots(...)` → `POST /client/game/bot/generate`.
- The response comes back and **all of it** goes into the pool: `this.List_0.AddRange(result)`.
  One profile is taken; the rest stay cached for later spawns.

So the surplus is not discarded — it is *prepayment*, and later spawns of that role are free until the
pool drains. That is what `presetBatch` is for: amortising HTTP round trips.

The trade is simply mis-sized for SPT. Batching 45 responses into one makes sense against a remote
backend where a round trip costs 50–200 ms. SPT's server is on loopback, where a round trip is nearly
free — so the client pays a **1.9-second main-thread stall to avoid roughly fifteen cheap local
requests**. It also explains the observed clustering: a burst of stalls as pools fill for each role,
then quiet.

This also sets the floor. Since the client asks for 3 at a time, a batch of 10 still gives about three
spawns of headroom per request.

**This is not a BSG problem, it is an SPT one, and it is fixable in config.**
`SPT_Data/configs/bot.json` → `presetBatch` sets how many bots the server generates per request:
`assault: 45`, `cursedAssault: 50`, `pmcBot: 40`, `marksman: 30`. ~~At ~41 KB per generated bot~~ — **the
41 KB figure is wrong by ~4×; see below.** Lowering the batch does not reduce total work — it splits the same
work into pieces small enough to fit in a frame.

#### Per-profile size is ~10.5 KB, and the generation rule is confirmed

**Measured 2026-07-28 from `worstCallbacks`, which carries the role mix and response size per callback.** The
server generates `Math.Max(presetBatch[role], requested)` per role clause
([`BotController.cs:356`](../../SPT4.0.13/Src/Server), fallback 10 for a missing role) — so **dividing a
response by the number of bots *requested* over-states per-profile size by exactly the inflation factor.**
That is where 41 KB came from.

Divide by the number *generated* instead and it is flat. Three single-clause marksman requests, **same log,
same raid, stock batch 30**:

| request | generated under `Max` | chars | **KB per profile** |
|---|---|---|---|
| `marksmanx3` | 30 | 310,696 | **10.1** |
| `marksmanx17` | 30 | 309,609 | **10.1** |
| `marksmanx32` | 32 | 329,627 | **10.1** |

**An 11× range in requested count, identical per-profile size to three significant figures.** The rule
predicts the response size, not merely fits it.

It holds across roles and across the batch change. `assaultx3` and `assaultx8` on stock batch 45 give 11.0 and
10.7 KB per profile; the same requests after `bot.json` was capped to 5 give 10.2–12.2. **Every single-clause
observation in the log set lands at 10.1–12.2 KB per profile, spanning batch 45 → 5 and requests of 1 → 32.**

**This dissolves the 42–137 KB puzzle.** At batch 5 a small request generates 5 profiles ≈ **55 KB**, and
multi-clause requests give more — so the post-fix range is exactly what the rule predicts, and there was never
a discrepancy to explain. The predictions above should read **batch 10 ≈ 105 KB and ~40 ms; batch 5 ≈ 55 KB and
~20 ms**, at the measured 4.04 ms per profile.

**And the inflation is worst exactly where the small on-demand path fires.** `Max(45, 3)` is **15× waste** on a
3-bot request; `Max(45, 44)` is none on a full wave. The small path is **not** rare post-fix — `assaultx4`,
`marksmanx4` and `shooterBTRx3` requests appear in every post-fix log including the control run. So capping
`presetBatch` is worth upstreaming: at stock config each of those costs 45 profiles ≈ 180 ms of main-thread
construction to deliver 3 bots, and at batch 5 it costs 5 ≈ 20 ms.

**Corollary for anyone reading response size as a proxy: do not.** Response bytes tell you `Max(batch, asked)`,
not how many bots the raid wanted. `profileBuild.profiles` counts profiles built per window directly.

Note the client-side budget is useless here for the same reason it was useless generally: one response is
one callback.

**Result of the batch change (raid 10:15 vs 09:43):**

| | batch 45 | batch 10 |
|---|---|---|
| largest response | 1,844,747 chars | **607,109** |
| slowest single callback | 1866.6 ms | **566.3 ms** |
| typical response | 300 KB – 1.8 MB | 100–350 KB |
| in-raid p50 | 16.23 ms | 14.70 ms |
| in-raid p99 | 57.5 ms | 52.7 ms |

Worked, and the superlinear penalty at 1.8 MB is gone with it — everything now sits at the flat
~0.3 µs/1k rate. p50/p99 moved less than the stall numbers because those are dominated by bot count
(6.8 vs 11.5 awake on average), not by these events.

**But size stopped predicting cost.** Windows 30–31 ran 1.3–5.0 µs/1k against the usual 0.28–0.55 —
**566 ms for 113 KB where another window did 113 KB in 64 ms**, a 9× spread at identical size. Not GC
(0–1 collections), not allocation rate (8.5 MB/s, below the 63 MB/s window that was fast), not heap size.

**Role is not the answer.** With roles now reported, four `assaultx3` requests of near-identical size:

| window | request | size | cost | µs/1k |
|---|---|---|---|---|
| 28 | `assaultx3` | 109,899 | 44.3 ms | 0.40 |
| 9 | `assaultx3` | 114,999 | 45.6 ms | 0.40 |
| 23 | `assaultx3` | 111,390 | 75.7 ms | 0.68 |
| 33 | `assaultx3` | 116,694 | **209.8 ms** | **1.80** |

Same role, same size, 5× spread. Also ruled out: GC count (0–2 either way), allocation rate (the *fast*
windows include the 63 MB/s one; the slow ones ran at 12 MB/s), heap size (4234 MB slow vs 4242 MB fast),
and awake bot count (the slowest windows had the fewest awake bots).

**SOLVED — it is GC landing inside the callback.** `allocKb` goes **negative** on exactly the slow ones,
and a negative net heap delta across a callback means a collection ran during it:

| response | cost | `allocKb` |
|---|---|---|
| `assaultx3`, 54,197 chars | **138 ms** | **−321,360** |
| `marksmanx3`, 52,148 chars | **88 ms** | **−391,908** |
| `assaultx3`, 52,070 chars | 82 ms | +9,856 |
| `marksmanx3`, 52,282 chars | 23 ms | +3,420 |

Where the delta is positive, cost tracks allocation sensibly. The outliers are 320–390 MB collections
happening mid-callback. Not role, not graph shape, not response size — the callback is simply unlucky
about when the collector runs. Note the earlier per-window GC counters said "not GC"; they were too coarse,
because a collection *inside one callback* does not move a window-level collection count much.

Superseded reasoning, kept for the record: `allocKb` per callback is a much better proxy for item-graph size
than response bytes. If the slow ones allocate proportionally more, the graph is bigger than the byte
count suggests; if they allocate the same and merely take longer, the allocator is the problem rather
than the work.

**`presetBatch` is not the only lever.** The largest request this raid was
`assaultx44+marksmanx11+assaultx6+marksmanx1` — 834 KB, 62 profiles — so something bypasses the batch
setting and asks for whole waves at once (`BotsPresets` has a `PrepareToLoadBackend` path alongside the
`WaveInfoClass(3, ...)` on-demand one). Notably it ran at the *normal* 0.29 µs/1k and cost 243 ms for 62
profiles, about 3.9 ms each — **cheaper per profile than the small on-demand requests**, which run
5–23 ms per profile. Bulk preloading is efficient; it is the trickle of small requests during play that
costs disproportionately.

**Applied 2026-07-26** as a test: 16 bulk-spawn roles set to 10 (`assault` 45, `cursedAssault` 50,
`pmcBot` 40, `marksman`/`infected*`/`test` 30, the 15s). Bosses and followers left alone — already ≤10
and rare. Backup at `SPT_Data/configs/bot.json.framesaver-backup`; restoring it returns the install to
stock.

Shipping this properly means a **server** mod overriding `botConfig.presetBatch` in `postDBLoad`, not a
client one — the response size is the server's decision and Harmony cannot reach it. A pure-client
alternative would be moving the `CompleteProfileDescriptorClass` → `Profile` conversion in
`ProfileEndpointFactoryAbstractClass.LoadBots` (`.Select(...).ToArray()`, which runs in the continuation)
into the background job that already parses the JSON. Untested, and depends on that conversion being
thread-safe.

---

### Telemetry pruned 2026-07-26

Fields that answered their question were removed rather than left to accumulate. Each is recorded above
with what it showed; this is the index so nothing gets silently re-added:

`render` / `update` / `fixedUpdate` (duplicated by the player-loop phases) · `gameUpdatePct` (redundant
with `framePct`) · `spikes` / `spikesWithGc` (fixed ms threshold does not transfer between maps;
percentiles replaced it, and GC coincidence was 0.7%) · `gc.gen1` / `gc.gen2` (Boehm is non-generational,
always identical to gen0) · `aiBrains` / `aiBotOwners` / `brainsTicked` (AI refuted at 1–2% of frame;
`aiTotal` kept as a cheap regression check) · `playerVisual` · `worldLate` · `ambientLight` (inactive on
Streets; re-add if another map is tested) · `cameras` (existed only as an `AmbientLight` multiplier) ·
`fixedSteps` (the spiral discriminator; settled, never exceeded 6) · `asyncDeferred` / `asyncTruncated`
(the drain budget cannot help against a single callback) · `forceExec` / `forceExecCalls` (measured 0) ·
`shells` / `worldUpdate` · `weaponAudio` / `weaponAudioCalls` · `bundleGraph`.

Their patches were deleted too, which matters for more than tidiness: `WeaponSoundPlayerUpdatePatch` was
running a `Stopwatch` pair on 49 instances per frame, and `BundleGraphVisitPatch` fired on every node
visit — both pure overhead once their question was answered.

### ~~Proposed: hollow out `Profile` construction for bots~~ — MEASURED, NOT WORTH DOING

2,460 profiles over one Streets raid:

| section | time | share |
|---|---|---|
| **`Inventory.ToInventory()`** | **9,245 ms** | **92.9%** |
| `SkillManager` | 566 ms | 5.7% |
| `TraderInfo` × 29,520 | 71 ms | 0.7% |
| everything else | 65 ms | 0.7% |
| **total** | **9,947 ms** | 4.04 ms/profile |

**The dead-weight column has a ceiling of ~1.4%.** The trader loop — the most obviously wasteful thing in
the constructor, building **12 `TraderInfo` per bot, 29,520 across the raid** — costs 2.4 µs each and
0.7% of the total. The earlier assessment was right that a scav can never use a trader-standing table and
wrong about it mattering. Wishlists, notes, hideout, ragfair and quest counters are all in that same 0.7%.

The item graph is the entire cost, and it is the one part a bot genuinely needs. Do not build the
thread-static-flag design.

#### Correction: per-profile cost is uniform, and `presetBatch` does scale stall size

An earlier entry claimed bulk requests were cheaper per profile (3.1–3.7 ms in bulk vs 13–19 ms for the
`assaultx3` trickle). That was an artifact of assuming an `assaultx3` request yields 3 profiles — the
server returns `presetBatch` regardless of what was asked for. At 10 per response, those 40–56 ms
callbacks are 10 profiles at ~4 ms each, which matches the measured 4.04 ms exactly.

Cost is therefore **uniform ~4 ms per profile**, and stall size is linear in profiles per response. Lowering
`presetBatch` further does keep working — more requests, same total work, smaller individual stalls.

#### The real waste: 2,460 profiles for a 36-bot raid

**~68 profiles constructed per bot that exists**, costing 9.9 seconds of main-thread time across the raid.
One window built 612. This is a far larger lever than making the constructor cheaper: the work is not
badly implemented, there is just an enormous amount of it that nothing ever uses.

**Measured: the pool is not thrashing.** 2,160 lookups, 1,893 hits — an **87.6% hit rate**, ~7.5 profiles
built per miss, which is `presetBatch` plus multi-wave bundling. Generation and consumption balance
(2,012 built vs 1,893 consumed). The matching logic is fine and there is no fix there.

**What the data shows instead is a constant poll.** `GetNewProfile` is called **~96 times per 15-second
window, every window — about 6.4 per second, sustained** — in a raid whose bot population sits stable at
44. And the pool is not a small cache: it holds **200–650 profiles** at all times.

That rate is not spawn-driven; something asks continuously. The likely candidate is the backup-profile
system: `CreateProfile` calls `Gclass684_0.AddProfileForBackup(data)`, and `FillBackupProfilesData`
exposes `LoadsProcess`, `TotalBackups` and `PeriodsForBackups` — a periodic top-up. Instrumenting that is
the next step; it is where ~2,000 profiles per raid actually come from.

#### Loading stalls are a different problem

Window 6 of the same raid: a **12,919 ms** callback for `marksmanx1+bossBoarx1+follower…`, while profile
construction across that entire window was **998 ms**. So ~92% of the loading stall is *not* profile
construction — consistent with the allocation-rate evidence pointing at Unity-side asset and bundle work.
In-raid stalls and loading stalls have different causes and need separate fixes.

### Original proposal (kept for the reasoning, not the plan)

`.Select(...)` in `LoadBots` is `new Profile(descriptor)` per bot, ~41 ms each. The LINQ itself is
irrelevant at 45 elements — the cost is the constructor, [Profile.cs:19](../../Src/Assembly-CSharp/Assembly-CSharp/EFT/Profile.cs:19).

Bots are built through the same `Profile` type as the human player, so every scav gets the full player
apparatus. Sorted by whether a bot could possibly use it:

| needed | plausibly needed | **dead weight for a bot** |
|---|---|---|
| `Inventory.ToInventory()` — the item graph | `SkillManager` (bot handling/recoil may read skills) | `TradersInfo` — a `Profile.TraderInfo` **per trader**, plus a `Class1413` closure each |
| `Info`, `Health`, `Customization` | `GClass789` stats (kill/death attribution at raid end?) | `WishlistManager`, `NotesManagerClass`, `Hideout`, `RagfairInfo`, `UnlockedRecipeInfo` |
| | `BonusController` (`Skills.Init` may require non-null) | `QuestsData`, `AchievementsData`, `TaskConditionCounters.ToDictionary(...)`, `PrestigeData.Select().ToList()`, `InsuredItems`, `TransferLimitData`, `Encyclopedia` |

**Measure the split before cutting any of it.** Most of the right-hand column is field assignment of
already-deserialised data and therefore nearly free; the trader loop is the only entry there that
allocates per-item. If `ToInventory()` turns out to be 35 of the 41 ms, hollowing out the rest buys
almost nothing in time — though it would still cut allocation, which matters given the 123 MB/s spikes.
Time the constructor in sections first.

**How a patch could know it is building a bot:** the wasteful sub-objects have no idea who they belong
to. Set a thread-static flag around the `.Select(...)` in `ProfileEndpointFactoryAbstractClass.LoadBots`
— everything constructed inside it is a bot profile by definition — then have targeted prefixes on the
dead-weight constructors no-op while it is set. That is far less brittle than transpiling the `Profile`
constructor or reimplementing it in a prefix, and it fails safe: if the flag is never set, vanilla
behaviour.

Same architectural theme as the `LocalPlayer` / `ObservedPlayerView` split one layer down: bots are
modelled as full players, and the cost is paying for the whole player.

---

It is *one* callback, not many:

| window | `asyncFixedDrain` max | worst single callback | callbacks drained |
|---|---|---|---|
| 9 | 389.1 ms | **389.0 ms** | 2 |
| 13 | 154.3 ms | **154.3 ms** | 1 |
| 33 | 653.7 ms | **653.7 ms** | 1 |
| 29 | 1705.5 ms | 566.4 ms | 25 |
| 17 | 1615.9 ms | 1071.9 ms | 33 |

One callback routinely *is* the whole drain. Capping the loop cannot help when a single item takes
650 ms, which is exactly the failure mode flagged when the budget was written.

`worstCallback` names it every time: **`DataHandlerClass.Class318<T>.method_2`**, i.e.
`method_7<T>(backRequest, responseText)` — the completion of a **backend HTTP request**. The JSON parse
itself runs on the worker thread; what stalls is the continuation that resumes inline when
`TaskCompletionSource.SetResult` fires. `Class316<T>.method_2` (`SetupDataBlock`) shows up for the small
ones, 1.7–3.5 ms.

Next: `Class312.BackendMethod` is now reported alongside the name, so the next run says *which endpoint*.
`forceExec` tests the other candidate mechanism — `JobScheduler.ForceExecuteContinuations` pumps with no
budget until the job it waits on completes, which would burn seconds on the main thread while computing
nothing.

---

## Open

### Work queue as of 2026-07-28, in priority order

Agreed between both sessions at the end of the control run. The ordering is the argument, not the list.

1. **Off-thread heap/pause sampler — scope reduced 2026-07-28, ranking now open.** Ranked first for answering
   four questions at once. **Two of the four are not reachable by a gap-based sampler:**

   - **Sliced versus forced (candidate 1 vs 2) has a resolution floor.** The pause is read from the gap in the
     sampler's own timestamp series, so a slice shorter than the sample interval plus scheduler jitter cannot
     be told from a missed wakeup. At 1 kHz that floor is roughly 10 ms; Boehm's configured slice is **3 ms**.
     A null therefore reads as "slices below the floor not excluded", never as candidate 2 — which was the
     whole point of running it.
   - **Live set versus heap size is not reachable at all.** The only heap instrument is
     `GC.GetTotalMemory(false)`, already established here as heap-including-free-blocks — the wrong column.
     Sampling the wrong column faster does not make it the right one. The nearest proxy is a heap read taken
     *immediately after* a collection completes, whose lower envelope approximates live + fragmentation, and
     that needs an event-driven read rather than a timer.

   What remains is still worth building: **per-collection pause cost inside a non-yielding span**, genuinely
   unmeasured after three withdrawn estimates (895 ms, 360 ms, 65 ms), plus evidence on the 6.9 GB
   `initHeapDeltaMb` anomaly. Two questions, not four.

   Two hazards, both biased toward confirming the hypothesis, so both are gates rather than caveats:

   - **The instrument's own gap distribution is uncharacterised.** Timeslice expiry, core contention on a
     machine that is comprehensively CPU-bound, and Windows timer granularity all produce gaps before a single
     collection happens. A gap-based instrument with no measured noise floor has no floor. This is the failure
     that killed the 20 → 4 experiment one level down: the spread check was specified for the instrument's
     effect on the *game* and omitted for its effect on *itself*.
   - **Both edges of the gap are soft and every error term is non-negative.** `GC.CollectionCount(0)`
     increments when a collection *completes*, so a changed count across a gap establishes only that one
     finished inside it. Measured gap = true pause + up to two sample intervals + any overlapping preemption.

   Revised design and both validation runs in [COORDINATION.md](COORDINATION.md), 2026-07-28 Gamma entry.
   **Ranking is deliberately left open rather than silently reshuffled:** items 3 and 5 reach the same
   non-yielding span far more cheaply, and item 5 targets `initHeapDeltaMb` directly. Argument in that entry.
2. **`CurrentState()` menu gating.** Gate `Menu` on `Singleton<AbstractGame>` being absent or terminal rather
   than on `GameWorld`'s existence. Fixes the `state: loading`-at-menu mislabel, removes the need for a
   threshold filter, and stops sampling that should never have been running.
3. **Segment tiling past `Init`.** The 3,584 ms gap in the raid-init callback holds the second-largest
   unexplained span *and* all four forced collections, and no instrument on either side reaches inside it.
4. **`failedPatches` + `"gpu":"failed"`, as one change.** A run needs a single answer to "was anything
   degraded", not two fields in different shapes. Both currently fail *silently*: a Harmony patch that cannot
   resolve throws out of `Awake` and drops every later registration, and a latched `_fatal` makes the `gpu`
   block vanish indistinguishably from being switched off. Neither can fire until a future SPT rename, which is
   why they sit here rather than higher.
5. **`GCMode`-boundary heap sampling test.** Sample the heap at `Init`'s boundaries *and* immediately after
   `GCMode` is restored, in one run. The only structural difference left between the consistent and the absurd
   `initHeapDeltaMb` readings is which GC state the sample was taken in.
6. **`GC time slice ms` and `Drive incremental GC ms` experiments — last.** Both knobs exist, are wired into
   `cfg`, and have **never run at anything but 0**. Demoted because if the forced collections' extra cost is
   Boehm's *sweep* — which scales with heap size rather than live set — then it is the non-incremental phase and
   no scheduling knob can touch it. These test the phase that probably is not the problem.

Deliberately not on the list: NVML/ADL interop, since PresentMon 2.5 already exposes throttle reasons, power,
temperature and GPU memory; and NVIDIA Reflex frame reports, since `NvReflex_Plugin_GetLatency` would give a
full per-frame CPU→GPU→present breakdown but PresentMon answered the question without requiring Reflex to be
enabled at all.

### ~~The 16.7 s PMC bot-generation callback~~ — SOLVED: it is raid initialisation, not bot generation

**Confirmed 2026-07-27 by direct measurement, across a cold/warm raid pair on Streets.**

The callback is not doing bot work at all. [LocalGame.cs:102](../../Src/Assembly-CSharp/Assembly-CSharp/EFT/LocalGame.cs:102):

```csharp
await botsPresets.TryLoadBotsProfilesOnStart(list);   // the bot/generate requests
BotCreatorClass botCreatorClass = new BotCreatorClass(...);
BotZone[] array = LocationScene.GetAllObjects<BotZone>(false).ToArray();
this.botsController_0.Init(...);                      // the whole AI system
await this.wavesSpawnScenario_0.Run(BeforeGameStarted);
this.nonWavesSpawnScenario_0.Run();
this.bossSpawnScenario_0.Run(...);
```

`TaskCompletionSource.SetResult` resumes continuations **inline**, so everything after that await runs on
the main thread inside whichever bot/generate callback completes the *last* preset batch. Intermediate
batches are cheap because `BotsPresets.method_1` opens with `await Task.Delay(500)` and yields immediately;
only the final batch falls out of the loop in `TryLoadBotsProfilesOnStart` and returns into `vmethod_1`.

**The discriminator is decisive.** Two callbacks, same endpoint, same window, same raid:

| | payload | ms | `profileMs` | `residualMs` | `raidInitMs` |
|---|---|---|---|---|---|
| `assaultx22+assaultx30+…` | 2,076 KB | 589.1 | 587.1 | 2.0 | **0** |
| `pmcUSECx2+pmcBEARx16` | 489 KB | 17,450.7 | 139.3 | 17,310.2 | **13,815.9** |

Four times the payload, zero raid-init time. PMCs are simply what SPT loads last — the role is a
coincidence of ordering, which is why every role-based and size-based theory failed.

This is the same trap already documented for `/client/match/local/start`, one layer down: **a drain
callback's measured duration includes the whole synchronously resumed continuation chain.** The timeline
confirms the two are halves of one loading sequence — `local/start` at 37.1 s, then the PMC callback at
17.5 s, split at the profile await.

#### The session warm-up is inside `BotsController.Init`, and not where it looked

Raid 1 (cold client) vs raid 2 (same process, no restart), Streets both times:

| | cold | warm | Δ |
|---|---|---|---|
| PMC callback | 17,450.7 ms | 8,577.5 ms | −50.8% |
| `controllerInitMs` | 13,804.7 | 4,059.0 | −70.6% |
| **uninstrumented remainder** | **12,569.9** | **2,784.7** | **−77.8%** |
| `coversRestoreMs` | 802.9 | 809.4 | **+0.8%** |
| `doorsMs` | 341.7 | 351.3 | +2.8% |
| zones / loot clusters | 21 / 200 | 21 / 200 | identical |

`controllerInitMs` fell 9,745.7 ms; the unmeasured remainder fell 9,785.2 ms. **All of the warm-up lives in
the part that was not instrumented**, and every named suspect is flat, constant work. The cover database —
the strongest prior candidate — is 803 ms cold and 809 ms warm.

Also refuted at this stage: the loot-cluster scan is 8.5 ms across 200 clusters, zone init 3.4 ms across 21
zones, the patrol map 0.31 ms. `CutController.Init` **is** called twice (`cutCalls: 2`, confirmed at
runtime) and is worth 0.055 ms — a real bug and a worthless fix.

**Method note worth keeping:** picking seven plausible methods to time left 91% in `other`, and the
cold/warm pair then proved the answer was entirely in that 91%. Pass 2 replaces sampling with a complete
partition — 17 checkpoints tiling `Init` so the segments sum to `controllerInitMs` by construction and
there is nowhere for the time to hide.

#### The warm-up is not garbage collection — the heap runs the other way

Worth stating explicitly now that [`TimeUpdate` has turned out to be GC](#timeupdate-is-garbage-collection--14-of-14)
and [pause cost is known to scale with heap](#pause-cost-scales-with-heap--measured-in-raid). Segment times
are wall clock, so a stop-the-world collection inside `Init` would be billed to whichever section was
running — the same mechanism that made identically-sized bot/generate callbacks differ 5×.

It is not what happened here, and the primary evidence is the **collection count**: `gen0` was 4 and 5 for
the entire 60-second window in the two raids, with `suspendGc: true` suppressing collections inside the
callback. Four collections cannot be 12.6 seconds at any plausible pause cost — the largest in-raid pauses
measured anywhere in this investigation are ~110 ms.

Heap direction is a secondary and now weaker support: across the pair the heap at the raid-init window went
**2,355 → 2,875 MB (+22%) while `controllerInitMs` fell 13,804.7 → 4,059.0 ms (−71%)**.

**Correction 2026-07-27:** an earlier version of this paragraph leaned on "+19% heap measured as +34% pause"
as though pause-versus-heap scaling were established. The GPU session has since decomposed that regression
and [downgraded it](#pause-cost-scales-with-heap--measured-in-raid) — pooled r = 0.909 across 14 in-raid
pauses, but r = +0.216 and −0.021 *within* each raid, so it was entirely between-cluster, and the two
clusters differ in Reflex state and bot count as well as heap. The argument here does not need it: it needs
only that four collections cannot account for 12.6 seconds, which holds whether pause cost rises with heap,
falls with it, or is flat.

Corroborated from the GPU side: the 17.96 s loading frame ran **147.79 ms of GPU work — 0.8% of the frame**,
so it is CPU-side managed work by an instrument that knows nothing about these patches.

**Two caveats on the absolute numbers.** Both raids ran with `suspendGc: true`, so `controllerInitMs` is raid
init *without* GC interference — a stock client takes those collections, and on the earlier 20 → 4
measurement that is likely 1–1.5 s more than these figures show. And `gen0` is now recorded per segment
precisely so this argument does not have to be re-derived by hand each run: a fat segment carrying
collections must be re-measured before anyone acts on it.

**Unmeasured tension worth testing.** `Suspend GC during completion callbacks` converts loading pauses into
heap growth, and in-raid collections are now known to be rare but individually catastrophic (73% produce a
>100 ms spike) and to worsen with heap. The setting may therefore be trading a smaller loading freeze for
worse in-raid spikes later in a session. It ships enabled on the strength of the loading measurement alone.

#### Pass 2 result — `zoneLeaveCtor` is 70.6% of `Init`, and by elimination it is `GClass620.SetSettings`

Control arm 1, Streets, cold client, 2026-07-27. **The partition is exact: the 17 segments sum to
13,986.595 ms against a measured `controllerInitMs` of 13,986.589 — 0.006 ms of drift over 14 seconds.** The
segments are a decomposition, not a sample, so the ranking below can be read directly.

| segment | ms | share |
|---|---|---|
| **`zoneLeaveCtor`** | **9,868.0** | **70.6%** |
| `coversCreate` | 1,561.3 | 11.2% |
| `coversData` | 923.4 | 6.6% |
| `coverBounds` | 541.7 | 3.9% |
| `doorsAndFinds` | 511.0 | 3.7% |
| `entry` | 380.4 | 2.7% |
| `method2` | 169.8 | 1.2% |
| the other ten | < 10 each | — |

`zoneLeaveCtor` covers [BotsController.cs:181–189](../../Src/Assembly-CSharp/Assembly-CSharp/EFT/BotsController.cs:181),
which is five statements. Four are trivial on inspection:

- `new ZoneLeaveControllerClass(...)` — a `HashSet` per zone (21), two date calls, two event subscriptions
- `new GClass1874(this)` + `Activate()` — two field assignments, three event subscriptions
- `Singleton<GClass620>.Create(new GClass620())` — an empty object
- `new GClass3597(online)` — two property assignments

That leaves **`Singleton<GClass620>.Instance.SetSettings(BotPresets, BotScatterings, botLocationModifier, IsPvE)`**
holding essentially all 9.87 s. Its structure:

```
for role in BotsController.AllTypes          // Enum.GetValues(WildSpawnType) = 64
  for difficulty in BotDifficulty            // 4
      botPresets.FirstOrDefault(...)                       // linear scan, closure alloc per iteration
      BotCurvSettings.Instance.Copy()                       // = UnityEngine.Object.Instantiate<ScriptableObject>
      new GClass612(botScatterings[j], preset) per scattering
      new BotDifficultySettingsClass(...); ApplyPreset(); ApplyPresetLocation()
```

**256 iterations, each performing a native `Object.Instantiate` of a `ScriptableObject` carrying 7
`AnimationCurve` fields** — 38.5 ms per iteration at the measured total. Per-iteration attribution needs a
pass-3 split; what is established is that the 70.6% is inside this one method.

Also newly measured: `AICoversData.CreateOrFind` is **1,561.3 ms**, nearly double the `RestoreData` that
pass 1 measured beside it (843 ms) and missed entirely. A good illustration of why partitioning beat
sampling — pass 1 timed the neighbour of the second-largest cost.

**`preInitMs` is 3.2 ms, refuting my own earlier attribution.** The ~3,494 ms pre-`Init` gap was blamed on
`LocationScene.GetAllObjects<BotZone>(false).ToArray()`. The scene scan is free. The gap is real but sits
earlier, in the `LoadBots` continuation before `vmethod_1` resumes — see below.

**GC is excluded outright, not merely bounded.** `initGen0: 0` and every one of the 17 `SegGen0` entries is
0: **zero collections across the entire 13,986 ms**. The GPU session's frame-level counter reads `gcGen0: 4`,
`gcPhase: Update` on the same frame, so the cross-check `sum(SegGen0) <= 4` holds and all four collections
are outside `Init`.

##### Registered prediction, before arm 2 is run

`GClass620.SetSettings` is **map-independent**: `AllTypes` is `Enum.GetValues`, the difficulties are a fixed
enum, and `BotPresets`/`BotScatterings` come from `iSession.BackEndConfig`, not from the loaded scene. Only
`ApplyPresetLocation(BotLocationModifier)` touches map state. So for this segment the Streets→Customs map
confound can be reasoned about rather than merely conceded:

- **If `zoneLeaveCtor` is low on Customs**, the drop cannot be a map effect, because the dominant work is
  identical on every map. That isolates it as genuine session warm-up.
- **If `zoneLeaveCtor` is high on Customs**, it is per-raid work rather than warm-up, and the explanation
  must move to something map-dependent inside the span — which on inspection there is very little of.

Recorded before the data exists so it cannot be fitted afterwards.

##### Prediction confirmed — arm 2, Customs, warm client, 2026-07-27

**`zoneLeaveCtor`: 9,868.0 ms → 6.5 ms. A factor of 1,518.**

| segment | Streets cold | Customs warm | |
|---|---|---|---|
| **`zoneLeaveCtor`** | **9,868.0** | **6.5** | **−99.93%** |
| `coversCreate` | 1,561.3 | 1,182.3 | −24% |
| `coversData` | 923.4 | 685.1 | −26% |
| `coverBounds` | 541.7 | 392.1 | −28% |
| `doorsAndFinds` | 511.0 | 390.8 | −24% |
| `entry` | 380.4 | 242.2 | −36% |
| `method2` | 169.8 | 135.0 | −20% |
| **`controllerInitMs`** | **13,986.6** | **3,036.8** | **−78%** |

Partition exact on both arms — 0.006 ms drift cold, 0.002 ms warm.

**`zoneLeaveCtor` alone is 9,861.5 ms of the 10,949.8 ms reduction: 90%.** Because the dominant work in that
span is map-independent by construction, the prediction registered above resolves it: this is **session
warm-up, not a map effect**. Every other segment fell 20–36%, which is what changing from Streets to the
smaller Customs would produce anyway and cannot be separated from warm-up — those remain confounded, and
deliberately so.

**This is a one-time-per-client-session cost, and that changes the fix.** At 6.5 ms warm there is nothing to
optimise about `GClass620.SetSettings` per raid; the 256-iteration loop is nearly free once the client has
run it. The 9.87 s is paid once, on the first raid load after launch, on whichever map that happens to be.
The intervention is therefore to **move it off the first raid's critical path** — touching
`BotCurvSettings.Instance` and running the loop during menu idle would relocate ~9.9 s out of the loading
freeze entirely — rather than to make the loop cheaper.

It also explains the community habit the investigation started from in reverse: restarting SPT every few
raids *reintroduces* this cost, because it is a launch cost, not a leak.

##### The 6.9 GB anomaly is not a lone artifact

`initHeapDeltaMb` read 6,900.8 MB on Streets against a 119,356 KB container, which was flagged unusable. On
Customs the same field reads **126.4 MB inside a 213,504 KB container — consistent**. Same code path, same
sampling under `GCMode.Disabled`.

Four quantities co-occur with the expensive segment and vanish together with it:

| | Streets cold | Customs warm |
|---|---|---|
| `zoneLeaveCtor` | 9,868.0 ms | 6.5 ms |
| `initHeapDeltaMb` | 6,900.8 MB | 126.4 MB |
| callback `gen0` | 4 | 0 |
| gap (`residualMs − raidInitMs`) | 3,584 ms | 420 ms |

That does not establish the transient, but any "measurement artifact" explanation now has to say why the
artifact only fires when one segment is 1,518× slower. Settling it needs an off-thread heap sampler — no
per-frame instrument has sample points inside a 17.7 s non-yielding callback. `GCMode` is `Disabled` for the
**whole** callback (`AsyncDrain.RunCallback` restores in a `finally` at callback end), so those four
collections were forced while collection was disabled.

#### Still open

- ~~**Which segment of `BotsController.Init` holds the ~12.6 s.**~~ Answered by pass 2 above:
  `zoneLeaveCtor`, 70.6%, and by elimination `GClass620.SetSettings`. What remains is the per-iteration
  split of its 256-iteration loop — pass 3 should checkpoint `BotCurvSettings.Copy`,
  `BotDifficultySettingsClass`'s constructor, and `ApplyPreset`/`ApplyPresetLocation` separately.
- **The 3,584 ms gap inside the PMC callback but outside `Init`, which neither instrument reaches.**
  `preInitMs` is 3.2 ms, so it is *not* the `BotZone` scene scan as previously assumed. **Whether it sits
  before or after `raidInit` is unestablished** — an earlier claim that it precedes `raidInit` was asserted
  without evidence and is withdrawn. Structurally, "after" is more likely: `vmethod_1` is `async Task`, so
  when its tail completes it resumes *its* awaiter — the remainder of the raid-load chain — inline in the
  same callback, whereas only trivial code sits before it. The gap also contains **all four** of the
  callback's collections (`initGen0: 0` localises them outside `Init`), and `GCMode` is `Disabled` for the
  **whole** callback (`AsyncDrain.RunCallback` restores in a `finally` at callback end), so those four were
  forced while collection was disabled — candidate 1 observed rather than inferred. Segment tiling should be
  extended across it; frame-level counters cannot see inside a non-yielding callback, which is the same
  argument that made per-segment counting right for `Init`. How much of the gap is collection is
  [not measured](#the-20--4-experiment-bounds-collection-cost-at-65-ms--withdrawn-the-effect-is-the-noise-floor).
  On Customs the same gap is **420 ms** with **zero** collections.
- ~~**Is the warm-up process-wide or per-map?**~~ **Answered by arm 2.** Process-wide, for the segment that
  matters: `zoneLeaveCtor` fell to 6.5 ms on a *different* map, and its dominant work is map-independent by
  construction. The other segments fell 20–36%, which is confounded with Customs being smaller and is not
  separated.
- **The cost is not per-iteration, which changes what pass 3 should measure.** 9,868 ms cold against 6.5 ms
  warm across the *same* 256 iterations means the loop body is not intrinsically expensive — something on
  the **first** call through it is. Pass 3 should therefore record `BotCurvSettings.Copy` cumulatively **with
  a call count**, and time the first iteration separately from the remainder. If iteration 1 is ~9.8 s and
  the other 255 are ~25 µs each, the target is a first-touch cost (asset load, native init, JIT) and the fix
  is to trigger it earlier — not to make the loop cheaper.
- `/client/match/local/start` did **not** improve raid-over-raid (37,094.8 → 39,282.2 ms). The whole
  session gain was in the bot-generate half; total loading stall 54.5 s → 47.9 s.

#### Next: the changes this points to

Written to be implementable without the conversation that produced it. Ordered by value, not by effort.

**Source data:** `BepInEx/plugins/Framesaver-logs/framesaver-20260727-232217-control.ndjson`, tag `control`.
Arm 1 = `raid 1`, Streets, window 1. Arm 2 = `raid 2`, Customs (`bigmap`), window 22. Both Reflex on,
`suspendGc: true`, both GC knobs 0. Build 99,840 bytes / 2026-07-27 21:44:16.

**1. Pre-warm the first-touch cost off the loading path — the actual product fix, ~9.9 s.**
`GClass620.SetSettings` costs 9,868 ms on the first raid after client launch and 6.5 ms on every raid after,
on any map. Since the loop body is identical both times, the cost is a first-call effect inside it (see the
pass-3 note above), and the cheapest candidate is `BotCurvSettings.Instance` — a static-cached
`GClass861.Load<BotCurvSettings>("botCurvSettings")` whose first access happens inside this loop, followed by
256 `UnityEngine.Object.Instantiate` clones of that `ScriptableObject`.

Sequence: **measure before building.** Confirm with pass-3 counters that iteration 1 dominates; then the fix
is to touch `BotCurvSettings.Instance` (and probably one `.Copy()`) during menu idle, which is cheap and
low-risk. Only if the cost is genuinely spread across all 256 iterations does anything larger become
necessary. Do not cache `Gclass624_0` across raids as a first move — `ApplyPresetLocation(BotLocationModifier)`
is map-specific and the settings object is handed to live bot AI.

**2. Fix the `CurrentState()` menu mislabel.** `Telemetry.CurrentState()` returns `Menu` only when
`Singleton<GameWorld>` is *not* instantiated, but the world persists at the menu after a raid — so menu idle
reports `state: "loading"` and keeps sampling, producing 545,800 ms and 1,149,837 ms spike lines that pollute
loading-regime and pooled statistics. Gate on `Singleton<AbstractGame>` being absent or its `Status` terminal
instead. Then `state == "menu"` filters the artifact exactly, with no threshold and no ratio. Until it ships,
filter `period > 60000`. **Do not** filter on `asyncUpdate / period` — see the artifact section; it is
anti-correlated with the population it appears to select.

**3. Extend segment tiling past `Init`** across the 3,584 ms gap, per the open item above.

**4. `failedPatches` on the telemetry header, and guard the confirmed fixes too.** `Plugin.TryEnable`
currently guards diagnostic patches only; confirmed fixes use bare `Enable()` so they "fail loudly", but in
`Awake` that means throwing and silently dropping every registration after it — including telemetry and the
GPU instruments. The danger is not silence but *undetectable* silence. Guard everything and emit the list of
patches that failed to resolve, so a degraded run is identifiable from the data rather than only from the
BepInEx log. Same reasoning as the `cfg` block. Design together with the GPU session's `"gpu":"failed"`
marker — a run needs one answer to "was anything degraded", not two fields in different shapes.

**5. Resolve `initHeapDeltaMb`.** Flagged unusable: it read 6,900.8 MB inside a 116.6 MB container on arm 1,
but **126.4 MB inside a 208.5 MB container on arm 2** — consistent, same code path. So the field is not
simply broken, and the anomaly appears only when `zoneLeaveCtor` runs long. The one structural difference is
that `RaidInit` samples the heap *inside* the `GCMode.Disabled` span while `AsyncDrain` and the GPU session's
`heapDeltaMb` both sample outside it. Test by sampling at Init's boundaries *and* immediately after `GCMode`
is restored, in the same run. Note the likely reading is not "6.9 GB of objects were allocated" but "Boehm
expanded the heap by 6.9 GB while forbidden to collect", since `GC.GetTotalMemory(false)` reports heap size
including free blocks.

**Noise floor for any future A/B on this callback** — established from two same-treatment replicates, and the
thing whose absence invalidated the 20 → 4 experiment: **951.7 ms on callback duration**, and 1.3% on
`controllerInitMs` (13,804.7 vs 13,986.6 across two cold Streets runs). An effect smaller than these is not
an effect.

#### The original measurements, kept for the record

Four mechanisms were excluded before the cause was found. All four were testing the *response handler*,
and the time was never in the response:

| callback | ms | profileMs | bundleMs | residual | gen0 | alloc | payload |
|---|---|---|---|---|---|---|---|
| scav wave | 599.9 | **598.0** | 0.0 | 1.9 | 0 | 180 MB | 1,977 KB |
| **PMC** | 16,759.1 | 66.2 | 0.0 | **16,691.8** | 4 | 120 MB | 502 KB |

The scav callback is 99.7% profile construction. The PMC callback is 0.4%, and **nothing accounts for the
rest**. Excluded by direct measurement, in order:

1. **Profile construction** — 66–135 ms of a 16,700 ms callback. Also refuted by `presetBatch` 45 → 5,
   which cut profiles built 495 → 145 while the callback moved only 21.0 s → 19.1 s.
2. **Bundle-load prologue** — `syncMsMax` measured **272 ms** against one call carrying 4,817 keys.
   Predicted ~16,000 ms; it is 1.7%. The earlier "keys per call" theory was built on per-window
   correlation and was wrong.
3. **Payload size** — a **502 KB** payload took 16.3 s while a **1,977 KB** payload in the same raid took
   688 ms. Normalised: 33 ms/KB versus 0.36 ms/KB, a ~100× difference in per-byte cost.
4. **Garbage collection** — suspending GC for the callback cut collections **20 → 4** and the duration only
   **17,805 → 16,759 ms (6%)**. Collections were costing ~60 ms each, not the ~800 ms the theory needed.

Superseded reasoning, kept because it was wrong in an instructive way: the allocation/collection mismatch
(scav 180 MB with **zero** collections, PMC 120 MB with **twenty**) was read as evidence about *survival* —
PMC descriptors being retained in the preset cache so each collection frees nothing. That inference was
built on the assumption that the callback was processing the response. It was not. The twenty collections
are what sixteen seconds of raid initialisation looks like from the outside, and the low allocation rate
(7 MB/s, against 300–400 MB/s for genuine response handling) was the clue that should have been followed —
it is the same Unity-side signature `/client/match/local/start` shows at 1.8–2.2 MB/s.

The "instrument within the callback" step was right; the mistake was assuming what was in there.

*Separately:* `/client/match/local/start` runs 34–39 s in the same loading phase with `gen0` of **0–1**, so
it is definitively not GC, and it is more than twice the size of the PMC callback. Its "loading screen, not
a stall" reading now looks **more** secure, not less, since the PMC callback turned out to be the second
half of the same resumed chain — but it is still the largest single number in the investigation and has
never been broken down.

### Unity's incremental GC is enabled — and structurally defeated

`gcRuntime` on the header line reads `isIncremental: true, mode: Enabled, timeSliceNs: 3000000`. So the
collector is incremental with a 3 ms per-frame slice, which raises the question of how 20 stop-the-world
collections happened inside one callback.

**Because incremental GC slices between frames.** A callback that runs 16 seconds without returning to the
player loop offers no frame boundary, so any collection forced inside it must run to completion and block.
The collector is correctly configured and cannot help. Raising `timeSliceNs` would change nothing.

`Suspend GC during completion callbacks` exploits this: disabling collection for the callback's duration
converts those pauses into heap growth the incremental collector reclaims afterwards. It works as designed
(20 → 4 collections, heap flat at 2,503 → 2,398 MB across the raid) and is worth keeping on. It is simply
not the loading fix, because GC was not the dominant cost.

### Spawn-in: `BotOwner.Create` refuted, `method_2` measured, spike still unexplained

The ~700 ms `Update` spike in the first seconds of a raid is not bot construction:

| | measured |
|---|---|
| `BotOwner.Create` | **0.1–0.3 ms** per bot, ≤4 per frame — a leaf, irrelevant |
| `BotCreatorClass.method_2` (the real build) | 12–21 ms per bot, 2–4 per frame → ~43 ms/frame worst case |
| Total bot construction in the spike's window | **200 ms**, against a 727 ms single frame |

`drained: 0`, `gcGen0: 0` on those frames, so it is neither the drain nor collection. Still open.

Two smaller notes from the same pass. The recurring ~330 ms `unaccounted` spikes are **not** GC —
`gcGen0` is 0 on every one. And spikes dominated by `ScriptRunBehaviourLateUpdate` **predate the AI stack**:
the stage 1 baseline (Framesaver only, four maps) already contained one at 135 ms, so LootingBots is not
the cause.

### Config hygiene — two process failures worth not repeating

**A new BepInEx config entry does not exist until the plugin has run once with the new build.** A raid was
spent testing a fix whose flag was still at its default, because the entry was created by that very launch.

**Editing the `.cfg` while the game is running gets clobbered on exit** — BepInEx writes its in-memory
values back on unload. Edit with the game closed, or use the in-game F12 manager.

Both were invisible in the telemetry because the `cfg` block recorded only the older options. It now
carries `suspendGc`, `reclaimStandBy`, `deactivateSleeping` and `keepFighting` as well. **Any option that
changes behaviour belongs in `cfg`, or a run cannot be told apart from the one before it.**

### Does loading degrade over a session? — heap growth says it should

The Mono heap grew 1.1 → 6.4 GB across five consecutive raids, and Boehm collections lengthen with heap
size. If that drives the loading freeze, load stalls should worsen raid-over-raid within one client
session. Needs a long session with `gc.heapMb` and loading stall duration compared across raids; the
telemetry already records both. Confirming it would justify a "restart every N raids" recommendation, or
argue for attacking allocation harder. See
[the loading freeze section](#the-loading-freeze-is-garbage-collection).

### Mod compatibility — reviewed on paper, unverified in play

Source review of SAIN, Fika, ORBIT, AILimit, BigBrain, LootingBots, QuestingBots and SPT's client modules
is written up in [COMPATIBILITY.md](COMPATIBILITY.md), and three guards are implemented. Every measured
result in this document, however, comes from a clean install with no other AI mods loaded. Nothing here has
been observed in a raid alongside them.

Two items are deferred rather than resolved: SAIN's own `SAINAILimit` per-bot class has not been checked for
double-throttling against our pause, and LootingBots' `LootingBrain` runs as a per-bot `MonoBehaviour` that
our stand-by pause cannot reach (it self-limits by distance, so this is a possible saving, not a conflict).

### JobScheduler backlog — knobs tested, needs a smaller slice

`jobQueue` averaged 9–27 with peaks near 100. `SetTargetFrameRate(120)` gives `FrameTicks = 8 ms` and
`LoopTicks = 4 ms`, but frames take 10–13 ms, so `Boolean_0`'s budget check never passes and the pump
falls into its every-4th-frame starvation burst.

`budget = 20 ms`, `slowFrames = 0` was tested mid-raid. `SlowFrames = 0` makes `int_1 > SlowFrames` true
on every frame, which disables the budget gate entirely and leaves `LoopTicks` (= budget/2 = **10 ms**)
as the only limit — a 10 ms per-frame drain allowance.

Result, comparing like for like (w15–17 vs w19–20, both ~30 bots, 0–4 awake):

| | `jobQueue` avg | frame avg | p95 | p99 |
|---|---|---|---|---|
| budget 0 (vanilla) | 19–25 | 14.5–15.1 ms | 18.0–18.3 ms | 19.6–21.0 ms |
| budget 20 / slow 0 | 3–4 | 14.6–15.2 ms | 25.1–26.3 ms | 27.8–28.7 ms |

**The backlog is fixed and the tail is worse.** Median is unchanged; the queue now drains in fat bursts
instead of persisting. Matches the reported "smoother overall, but semi-frequent `GameUpdate` spikes".

Next: `budget = 4`, `slowFrames = 0` — keeps the gate disabled (which is what un-sticks the pump) but
cuts the per-frame slice to 2 ms.

### A recurring ~80 ms cost in the `Update` phase

Present in every window of both Streets runs — 77–99 ms, at most once per 15 s window, entirely inside
the `Update` player-loop phase. Not the AI tick (`aiTotal` max 0.3–5 ms), not the world tick, not GC
(`spikesWithGc` is 0 in almost every window), not the telemetry writer (see methodology below), and
independent of bot count: 92 ms with 0 bots awake, 86 ms with 17.

**Localised to `Update/ScriptRunBehaviourUpdate`** — so it is a MonoBehaviour's `Update()`, not a coroutine
and not a posted continuation. `ScriptRunDelayedDynamicFrameRate` (coroutines) maxed at 2–3 ms and
`ScriptRunDelayedTasks` (the `SynchronizationContext` pump) at 0.2 ms in the same windows.

Extremely regular: 94.7, 95.0, 95.1, 95.3, 97.1, 97.4, 99.1, 99.1, 100.3, 100.6 ms across consecutive
windows, once per window, occasionally 300 ms. Not the AI tick, not GC, unaffected by bot count.

Next: per-frame spike lines give the exact cadence. A constant interval points at a timer, which can then
be searched for in the decompile.

### ~~Frames spent in no phase at all~~ — resolved, it was instrumentation

The "1.8 s outside every player-loop phase" was the off-by-one described in the methodology notes, not a
real phenomenon. With the residual measured against the correct interval, **6 of 111 spike frames are
residual-dominant, 4 of them in-raid, totalling 720 ms across an eleven-minute raid.** Everything else
accounts to within about a millisecond. The ALT-Tab explanation was never needed.

### The drain is 81% of in-raid stutter

With the drain moved to `Update` (2026-07-26), 197 in-raid spike frames split cleanly:

| | frames | total |
|---|---|---|
| **drain** (`asyncUpdate` > 1 ms) | 162 | **11,840 ms — 81%** |
| everything else | 35 | 2,822 ms |

The remainder is `TimeUpdate` (100–126 ms — described here as presentation waits, but
[since measured as GC pauses](#gpu-side-telemetry--stage-3-2026-07-27)), two unexplained
`ScriptRunBehaviourUpdate` frames at 81–93 ms, one `Initialization` at 74.8 ms, and one `PreLateUpdate`.

**This is the number that says where to go next.** Every remaining avenue — audio, shells, bundle graph,
AI, GC — has now been measured and found to be noise. The bot/generate completion is the in-raid stutter,
and its cost is the `Profile` constructor.

### The FixedUpdate move worked exactly as designed, and no more

`asyncFixedDrain` is **0.0 in every window**, `asyncFixedSkips` ~900 per 15 s window (once per frame), and
the drain time reappears in `Update` / `ScriptRunBehaviourUpdate`. In-raid spike attribution flipped from
`FixedUpdate`-dominant (47 of 64 frames) to `Update`-dominant (185 of 197).

The stall did not shrink, which is what was predicted. `fuFPS` spikes should now be gone entirely.

**Not comparable between those two runs:** `Spike event ms` changed from 100 to 50 at the same time, so
spike *counts* and *totals* across the two runs measure different populations. Only the per-phase split
within a run is meaningful.

### Where in-raid spike time actually goes

64 spike frames, t > 160 s (excluding the two loading megastalls):

| dominant phase | frames | total | worst |
|---|---|---|---|
| `FixedUpdate` | 47 | 11,575 ms | 715.7 ms |
| `TimeUpdate` | 5 | 1,071 ms | 460.7 ms |
| `Update` | 7 | 1,024 ms | 247.7 ms |
| residual | 4 | 720 ms | 276.1 ms |
| `Initialization` | 1 | 122 ms | 121.8 ms |

`FixedUpdate` is the bot/generate drain and still owns ~85% of in-raid spike time. ~~`TimeUpdate` is Unity
waiting on presentation — GPU-side, outside what a Harmony mod can reach.~~ **Superseded:** `TimeUpdate` is
garbage collection, and it is reachable — see
[GPU-side telemetry](#gpu-side-telemetry--stage-3-2026-07-27).

### The "recurring ~95 ms MonoBehaviour" was several different things

Per-frame data dissolves it. In the 90–160 ms band in-raid the dominant phase is variously `FixedUpdate`,
`TimeUpdate` (119.1, 130.0, 120.9 ms), `ScriptRunBehaviourUpdate` (48.1, 68.8, 107.8, 112.1 ms) and
`Initialization` (102.6 ms), with gaps ranging from 0.1 s to 131 s. There is no fixed cadence.

The apparent regularity was an artifact of reading **window maxima**: several unrelated mechanisms each
produce roughly-100 ms spikes, so any 15-second window catches one and its maximum lands near 100 ms
every time. Tightly clustered window maxima are not evidence of a single cause.

Some of the `ScriptRunBehaviourUpdate` spikes are the same drain, running Update-side: at t=562.68,
`ScriptRunBehaviourUpdate` = 206.8 ms against `asyncUpdate` = 202.8 ms. Others are not — t=561.91 has
112.1 ms with `asyncUpdate` at zero.

### Awake bots cost ~0.5 ms each

Regressing p50 against awake count over 33 clean windows of the 2026-07-26 raid:

**0.507 ms per awake bot, intercept 13.5 ms.**

This is the whole explanation for that run feeling inconsistent versus the previous one. Stand-by was
back at 150/130 m, so 17–26 bots were awake where the previous raid had 0–10, and p50 tracked it: 10.8 ms
at 10 awake, 29.1 ms at 26 awake. It also puts a number on the ceiling — the sleep-based fixes are worth
about half a millisecond per bot they can put to sleep, and nothing for bots that must stay awake.

### Modernising `Diz` — what is worth doing, after measurement

`AsyncWorker` and `JobScheduler` are a hand-rolled `SynchronizationContext` and `TaskScheduler` from
before Unity had the TPL (.NET 4.x became Unity's default only in 2018.3), with a `TaskCompletionSource`
façade bolted on later. Every pathology lives on that seam. But the measurements narrow what is worth
changing:

- **Worth doing: skip the drain in `AsyncWorker.FixedUpdate`.** Both `Update` and `FixedUpdate` call
  `CheckForFinishedTasks`, and Unity runs the FixedUpdate phase first — so whichever frame happens to owe
  a physics step drains inside physics. That is the whole explanation for the same stall appearing as
  `fuFPS` sometimes and `gameUpdate` other times. Skipping the FixedUpdate call makes it drain once per
  frame in `Update` and removes the interaction with physics catch-up. Three lines; completions arriving
  one `Update` later is immaterial for HTTP responses.
- **Not worth doing: `RunContinuationsAsynchronously` on the TCS.** It buys the *same* normalisation —
  relocating the continuation to `ScriptRunDelayedTasks` — at far higher risk, because any `await` that
  did not capture a `SynchronizationContext` would resume arbitrary game code on a thread-pool thread.
  The cheap option above gets the benefit without that failure mode.
- **Not worth doing yet: thread pool in place of the two worker threads.** The stall is a main-thread
  continuation, not background parse throughput. No evidence the two threads are a bottleneck.
- **Separate concern: the `JobScheduler` headroom budget.** Its budget is derived from the *target* frame
  rate via `1000 / frameRate`, so for anyone not hitting their cap the check never passes and the pump
  falls into its starvation burst. Budgeting from measured headroom instead fixes that. Raised in value by
  `EasyAssets` pushing one continuation per bundle through the pump at startup.

**Neither of the first two shrinks the stall — they only move it.** Stall size lives in the `Profile`
constructor and in whatever `/client/match/local/start` does.

### Bundle loading — `EasyAssets` / `DependencyGraphClass`

Read from source, **not yet measured**. Ranked by how wrong they look:

**MEASURED 2026-07-26 — the O(n²) is real but irrelevant. Do not write the HashSet fix.**

| | |
|---|---|
| total bundles in graph | 6,816 |
| **largest closure observed** | **54 nodes** |
| average scan depth per visit | 12.8 – 21.4 |
| worst window's total comparisons | 53,499 |
| worst window's `retainMs` | **1.08 ms — for the whole 15-second window** |

n²/2 at n = 54 is about 1,500 comparisons. The linear-scan visited check is harmless because closures are
tiny relative to the graph. This was worth measuring precisely because it *looked* obviously wrong.

Caveat: `smethod_1`, the async variant, is still not counted. But `Retain` runs during loading too
(3–113 calls per window) with equally small closures, so there is no sign of a hidden large-closure path.

The remaining `EasyAssets` items below are unmeasured and now lower priority.

1. **`DependencyGraphClass.smethod_0` is O(n²).** The recursive dependency-closure walk uses
   `if (!nodes.Contains(node))` on a `List<T>` — a linear scan — as its visited check, so building a
   closure of *n* nodes costs ~n²/2 reference comparisons. `Retain` calls it once per key with the list
   carried across keys; `RetainSeparate` clears and re-walks per key, making it O(k·n²). A `HashSet`
   seeded from the incoming list fixes it exactly, and the method is static and self-contained, so a
   prefix replacing it with an iterative DFS preserves pre-order and the cross-key dedup semantics.
   **Measure first** — the win is entirely a function of closure size, which is unknown.

2. **`smethod_1`** (the async variant) has the same linear-scan visited check, plus a `Task.Yield()`
   every `Int_0` iterations — so it also emits continuations in proportion to node count.

3. **`EasyAssets.method_0` yields to `JobScheduler` once per bundle.** The construction loop does
   `await JobScheduler.Yield(EJobPriority.General)` inside `for (i < allAssetBundles.Length)`. EFT ships
   thousands of bundles, so startup pushes thousands of continuations through the pump — which is
   probably why `jobQueue` behaves the way it does during load, and it raises the value of fixing the
   scheduler's budget logic.

4. Same method reads the manifest with `File.ReadAllText` and deserialises it with `JsonConvert` plus a
   LINQ `ToDictionary`, synchronously.

5. `EasyAssets.Update()` → `DependencyGraphClass.Update()` is a plain MonoBehaviour `Update`, so it lands
   in `ScriptRunBehaviourUpdate` — a candidate for the spikes seen there that were not the drain.

6. **Unverified:** `List_2.AddRange(list)` accumulates on every `Retain`/`RetainSeparate`. Whether it is
   ever cleared was not checked; if not, it is a leak of the same shape as `AICoreControllerClass.HashSet_1`.

This is consistent with the loading stalls being Unity-side rather than managed: `/client/match/local/start`
allocated only 64 MB across 35.7 s (1.8 MB/s, against 300–400 MB/s for in-raid callbacks), so most of that
time is not managed allocation.

### Triage of earlier community findings (2023 thread, re-checked 2026-07-26)

| claim | verdict |
|---|---|
| `GetCover` up to 55 ms/frame, huge GC churn | **Refuted.** Whole AI tick is 0.13–0.55 ms. The 55 ms was a deep-profiler artifact — see methodology. |
| `AmbientLight` 5 ms/frame | **Refuted on Streets** (component inactive there, measured 0). Unverified on other maps. |
| Diz bundle loading + HTTP causes the stutters, worst on bot loads and deaths | **Confirmed, with receipts.** `/client/game/bot/generate` on loads; `Corpse.cs:134` resource keys on deaths, which matches "only the first couple of bodies". |
| X3D / L3 cache helps EFT | **Consistent, unproven.** Fits what we found — `Profile` construction pointer-chases a 4–6 GB heap, which is cache-hostile. Validating it needs hardware counters (VTune/uProf), not reachable from a mod. |
| `EFTPhysicsClass` queues physics manually, up to 55 ms/frame | **Unexamined.** Not yet looked at. |
| Spatial audio / `MetaXrAudioSource` updated needlessly per frame | **Unexamined, and now the most promising lead** — see below. |
| `GameWorld.Update` iterates every bullet shell in the world | **Confirmed in source.** |

#### Both measured 2026-07-26 — **both refuted**

| | measured | verdict |
|---|---|---|
| `WeaponSoundPlayer.Update` | **0.002–0.005 ms/frame** across 43–49 instances (~0.1 µs each) | The 2 ms was deep-profiler per-call overhead, not work. Instance count *does* track bot count (37 → 49), so the scaling intuition was right — the cost simply is not there. |
| `GameWorld.Update` shell sweep | **0.000–0.001 ms/frame**, `list_0` max **1** entry all raid | The list never accumulates. Even if it did, the per-item cost is so small it would take ~100k shells to reach a millisecond. |

Same root cause as `GetCover`: a component with many instances, each individually trivial, that the deep
profiler inflates by instrumenting every call. Three separate 2023 findings have now died this way.

Caveat on the shell number: it depends on shooting having happened during the raid. The per-item cost
bound holds regardless.

#### For the record: what the code actually does

```csharp
for (int i = this.list_0.Count - 1; i >= 0; i--)
    if (this.list_0[i].ShouldBeDestroyed) { remove; ReturnToPool(); }
```

`list_0` is fed by `SpawnShellInTheWorld` and only shrinks when a shell flags itself destroyed, so it
tracks every live casing. `ShouldBeDestroyed` is a plain auto-property, so each iteration is cheap — this
is O(shells) with a trivial body, not an expensive check. Whether it matters is purely a question of how
large `list_0` gets with 40 bots firing, which nobody has measured. Cheap to instrument: record
`list_0.Count` per window. Note each active shell is also its own MonoBehaviour with an `Update`.

#### Most promising: per-bot weapon audio

`WeaponSoundPlayer.Update` and its base `BaseSoundPlayer.Update` are both individually tiny. The 2 ms/frame
in the old capture is the profiler **summing across instances** — and there is one per weapon, on every
bot, because SPT bots are full players. `Update` calls `_queue.Pose(WeaponPosition)` every frame, which
moves audio sources, and `UpdateMixerGroup` goes through `MonoBehaviourSingleton<SpatialAudioSystem>`.

This fits the largest remaining unattributed cost: `Update/ScriptRunBehaviourUpdate` averages 2.5–3.5 ms
in-raid and almost none of it is accounted for. It is also the same shape as the fixes that already
worked — a per-bot component doing per-frame work for a bot nobody can see — so disabling audio
components on sleeping bots is the obvious experiment, directly analogous to the `LateUpdate` skip.

Note the existing sleep skips do **not** cover this: `WeaponSoundPlayer` is a separate MonoBehaviour with
its own `Update`, untouched by skipping `Player.LateUpdate` or the world tick.

### ~~`/client/match/local/start`~~ — resolved: it is the loading screen, not a stall

**37,469 ms in one callback** was the single largest number in this investigation. It is not a cost to
fix; it is where raid loading is *attached*.

`Class308.LocalRaidStarted` posts to the endpoint and its own continuation is two field assignments. But
its awaiter, [TarkovApplication.cs:1984](../../Src/Assembly-CSharp/Assembly-CSharp/EFT/TarkovApplication.cs),
is the entire raid initialisation:

```csharp
LocalSettings localSettings = await Session.LocalRaidStarted(localRaidSettings_0);
...
@class.localGame = LocalGame.smethod_6(...);      // build the game
Singleton<AbstractGame>.Create(@class.localGame);
await @class.localGame.method_4(BotSettings, backendUrl, null);   // the whole raid load
DestroyImmediate(MenuUI); gameWorld.OnGameStarted();
```

`TaskCompletionSource.SetResult` resumes that chain **inline**, so everything raid loading does
synchronously is billed to the drain callback that started it. The 37 seconds is the loading screen.

Corroborating: allocation was only 82 MB across those 37 s (2.2 MB/s, against 300–400 MB/s for in-raid
callbacks), which is what Unity-side asset work looks like rather than managed allocation.

**Lesson for the instrumentation:** a drain callback's measured duration includes the whole synchronously
resumed continuation chain, not just the callback body. That was harmless for `bot/generate`, where the
chain really is the work, and completely misleading here. Load-time improvement would mean going after
`LocalGame.method_4` directly — a separate and much larger investigation.

### Suspected: the backup-profile flush is self-reinforcing

`GClass684` accumulates wave requests in `List_1` and flushes them as one `/client/game/bot/generate`:

- `AddProfileForBackup(data)` appends `data.PrepareToLoadBackend(1)` and fires `method_1()` once the
  pending total exceeds **10**
- `method_1()` does `if (Int_3 <= 1) { take List_1, clear it, request the lot }`

The trigger is >10, yet **75-bot requests** (`assaultx54+assaultx17+marksmanx4`) were observed mid-raid.
The `Int_3 <= 1` guard would explain the gap: with two backup requests already in flight, `method_1`
returns **without clearing `List_1`**, so the pending list keeps growing while each new
`AddProfileForBackup` re-fires a call that immediately bails. When a slot frees, the whole accumulation
goes out at once — and a larger request means a longer stall, which keeps the slots busy longer.

`method_1` also sets `Float_2` (the last-flush timestamp) *before* the `Int_3` check, so a bailed call
still resets the 50-second timer in `Update`.

**CONFIRMED 2026-07-26.** Across one raid: **20 flushes fired, 94 bailed — 82% of attempts refused by the
guard.** Pending totals reached 57, 40 and 24 against a trigger of 10, and the largest single request was
58 bots. The clustering is visible too: the windows with the most bails (47, 30, 14) are exactly the
windows that built the most profiles (371, 286, 249).

The fix is small and local: make `method_1` leave `Float_2` alone when it bails, and either queue a retry
or raise the in-flight limit. Do not simply raise the limit without thought — more concurrent backup
requests means more concurrent 4 ms/profile continuations.

### The real driver: ~7.5 bot-creation attempts per second, regardless of bot count

`GetNewProfile` is called **112–115 times per 15-second window, in every window**, and each one is
followed by a `LoadBundlesAndCreatePools` call — the two counts track to within a couple of calls.

The rate does not depend on the bot population:

| raid | bots | pool lookups / window |
|---|---|---|
| 12:35 | 44 | ~96 |
| 12:57 | **26** | **~112** |

Fewer bots, *more* lookups. So this is not spawning; something attempts bot creation ~7.5 times a second
throughout, and the population sits flat at 26 the whole time. Each attempt takes a profile from the pool
and kicks off a bundle load.

Over one raid that is **2,118 profiles built and 112,629 resource keys requested across 2,239
`LoadBundlesAndCreatePools` calls** — for a raid holding 26 bots.

First pass measured `syncMs` at 1,339 ms total (0.6 ms per call). That covers more than it appears —
`method_1` is async, so its whole prologue runs synchronously on the caller — but it stops at the first
await and therefore misses pool creation entirely. Expanded to `totalMs` (wall clock to task completion),
`poolFillMs` (`InitAndFillPools`, which instantiates the pooled GameObjects) and `inFlightMax`.

#### Three quadratic scans in the synchronous prologue

`PoolManagerClass.method_1`, before its first await:

| | cost |
|---|---|
| `pools.PoolsDictionary.Keys.All(...)` per candidate pool | O(candidates × existing pools) |
| `Dictionary_4.ContainsValue(path)` per resource — `ContainsValue` is a linear scan | O(resources × loaded resources) |
| `list2.Contains(path)` per resource | O(resources²) |

**Measured — the degradation does not happen.** `syncMs` per call was **0.69 ms in the first half of the
raid and 0.59 ms in the second**: slightly *better*, not worse. `Dictionary_4` growth produces no
measurable effect at these sizes. `poolFillMs` is likewise negligible at 0.1–1.4 ms per 15-second window.

So the synchronous side of bundle loading is not a cost worth pursuing. What the run found instead is
below.

#### The JobScheduler backlog is bundle loading — long-standing open item closed

Bundle loads accumulate and never drain. `inFlightMax` climbs from 2 early in the raid to **149**, then
settles at 100–108 for the rest of it, and individual loads take **44–82 seconds** to complete.

`inFlight` and `jobQueue` track each other tightly:

| raid clock | inFlight | `jobQueue` avg | `jobQueue` max | `jobSchedulerLate` avg |
|---|---|---|---|---|
| 49:44 | 2 | 0.5 | 10 | 0.08 ms |
| 49:14 | 149 | 22.4 | 84 | 0.80 ms |
| 47:14 | 100 | 20.0 | 76 | 1.14 ms |
| 46:29 | 106 | 39.8 | 98 | **1.27 ms** |

That answers a question open since the first Streets raid. The continuation backlog is not mysterious and
is not the scheduler misbehaving — it is ~100 outstanding bundle loads, each yielding through
`JobScheduler.Yield`, queued behind one another.

**But the main-thread cost is modest.** `jobSchedulerLate` grows from 0.08 to 1.27 ms/frame as the backlog
builds — about 7% of a 19 ms frame at its worst. Real, worth having, not a stutter source.

Caveat, and it matters here: **`totalMs` and `longestMs` are elapsed time, not main-thread time.** The
44–82 second figures are queue latency, not CPU. A load waiting 80 seconds for its turn costs nothing
while it waits. What those numbers do say is that a bot's bundles may not be ready until a minute or more
after its profile was built, which is a correctness/behaviour question rather than a frame-time one.

#### ANSWERED: `NonWavesSpawnScenario` re-fires the entire bot deficit every check period

One raid, measured end to end:

| | count |
|---|---|
| `BotCreationDataClass.Create` | 2,478 |
| ↳ via `ActivateBotsWithoutWave` | **2,457 (99.4%)** |
| ↳ via `ActivateBotsByWave` | 13 |
| ↳ via `SpawnBotByTypeForce` | 1 |
| `TryToSpawnInZoneInner` | **14,874** |
| profiles built | 2,521 |
| `LoadBundlesAndCreatePools` calls | 2,636 |
| **`BotOwner.Create` — bots that actually exist** | **35** |

**70.8 creation attempts per bot that results.** The chain reading was right: `creates` (2,478) tracks
`botPool.calls` (2,637) and `bundleLoad.calls` (2,636) almost exactly, so one attempt really does cost one
pool lookup and one bundle-load call.

The driver is `NonWavesSpawnScenario`:

```csharp
if (abstractGame_0.PastTime - float_0 < float_2) return;   // check period, >= 10s
float_0 = abstractGame_0.PastTime;
int num = this.BotMax - botsController_0.AliveLoadingDelayedBotsCount;   // the deficit
...
num = gclass1876_0.TrySpawn(num, botsController_0, gclass1881_0);
for (int i = 0; i < num; i++)
    botsController_0.ActivateBotsWithoutWave(1, botProfileDataClass);    // one call per missing bot
```

It computes `BotMax − alive` and fires **one full spawn request per missing bot, every check period** —
each carrying a pool lookup, possibly a profile generation, and a bundle load. Measured at ~90–96 calls
per 15-second window against a standing population of 41–49, which is consistent with a `BotMax` around
140 and a deficit that never closes.

**CONFIRMED by A/B.** Same map, same settings, Horde on vs off:

| | Horde (44 bots) | Normal (19 bots) |
|---|---|---|
| `Create` calls | 2,478 | **23** |
| via `ActivateBotsWithoutWave` | 2,457 | **14** |
| `TryToSpawnInZoneInner` | 14,874 | **33** |
| profiles built | 2,521 | **153** (all during load) |
| bundle-load calls | 2,636 | **26** |
| **creates per actual bot** | **70.8** | **1.1** |

**108× fewer creation attempts, 451× fewer zone attempts, and zero in-raid profile construction.** With a
reachable cap the deficit closes and the scenario stops re-firing; 1.1 attempts per bot is essentially
optimal. The churn is not merely reduced, it is absent in steady state — most windows record nothing at all.

Frame-time effect, in-raid:

| | Horde (44 bots) | Normal (19 bots) |
|---|---|---|
| p50 | 17.70 ms | 11.24 ms |
| p99 | 39.45 ms | **16.17 ms** |
| spike frames ≥50 ms | 168 | **31** |
| of which the drain | 92 | **0** |
| drain stall per minute | **852 ms** | **0 ms** |

**The bot/generate stall — 81% of in-raid spike time across this entire investigation — disappears
completely.** Not smaller: zero drain-attributed spike frames in 47,293 frames.

*Attribution caveat:* bot count also halved, so p50's improvement is partly just fewer bots (~0.5 ms per
awake bot, established earlier). What is *not* explainable by bot count is the drain going to exactly
zero and p99 collapsing from 39.5 ms to 16.2 ms — p99 is dominated by stalls, not by steady load.

`TryToSpawnInZoneInner` at 14,874 calls — ~550 per window, 36/second — is a second, separate retry loop
sitting underneath this, and it spins in windows with zero `creates`.

**This is the largest lever found in the whole investigation**, and it is upstream of everything else:
`presetBatch`, the `Profile` constructor, the backup-flush bail and the bundle backlog are all downstream
consequences of asking for ~70× more bots than the game will ever create.

#### The amplifier: SPT makes every cached profile single-use

Found 2026-07-26 while reviewing SPT's client modules, and it closes the "constant poll" question left open
above — the backup system was the wrong suspect.

`RemoveUsedBotProfilePatch` forces `withDelete = true` on `BotsPresets.GetNewProfile`
([RemoveUsedBotProfilePatch.cs:22](../../Community/modules-master/project/SPT.SinglePlayer/Patches/RaidFix/RemoveUsedBotProfilePatch.cs:22)).
Every profile handed out is removed from the cache. That is correct in isolation — it stops duplicate bots.

Combined with the spawn churn it is the multiplier that turns a retry loop into a stall generator:
**a rejected spawn attempt still pulls a profile from the cache and still deletes it.** The cache therefore
drains at the rate of *attempts*, not *spawns*, and the next `presetBatch`-sized generate request fires that
much sooner.

That is why the 87.6% pool hit rate measured earlier was not the reassurance it looked like. The pool was
matching fine; it was being strip-mined and refilled continuously underneath. It also explains why
`presetBatch` 45 → 5 helped as much as it did without changing the attempt rate at all — it shrank each
wasted refill.

Order matters for anyone fixing this: `BotCreationDataClass.Create` fires `/client/game/bot/generate` and
builds the `Profile`s *before* the spawn is validated. Any mitigation placed at or after
`BotSpawner.TrySpawnFreeAndDelay` — which is where QuestingBots puts its scav limiter — reduces the bots
that end up alive but not the work already paid for. A Framesaver fix has to sit upstream, at generation.
See [COMPATIBILITY.md](COMPATIBILITY.md).

### Customs, 2026-07-26 — first non-Streets run

| | |
|---|---|
| p50 | **8.41 ms (119 fps)** |
| p99 | **12.01 ms** |
| worst frame | 190 ms |
| spike frames >= 50 ms | 20 in 43,021 frames |
| **of which the drain** | **0** |
| bots | 4 awake / 18.5 asleep, ~~all 18.5 animator-culled~~ *(see below)* |
| spawn | 30 creates -> 29 `BotOwner.Create` = **1.0 per bot** |

The spawn finding holds on a second map: 1.0 attempts per bot against 70.8 under Horde on Streets. The
three sleeping-bot fixes also work harder here than expected - 18.5 of 22.5 bots asleep, because Customs
is long and thin enough that 150 m still excludes most of it.

**Correction 2026-07-28 — "all 18.5 animator-culled" was an inference, not a reading, and this is the
[`Sleeping` leak's](#methodology-notes) first identified victim in this document.** `animCulled` averaged
**37.3** across those windows, against an `asleep` of 19.3 and a `total` of 22.5 — the field claimed more
culled animators than the map held bots. This was raid 3 of that session, so it was carrying 18 stale entries
from the two raids before it. The conclusion is probably still true, since raid 1 of any session reads
correctly and reads `animCulled = asleep` exactly; but it was never read off this field, and the field would
not have supported it.

A p99 of 12.01 ms against a p50 of 8.41 is the tightest distribution measured anywhere in this
investigation. Streets under Horde was 17.70 / 39.45.

**`ambientLight` does run on Customs** - avg 0.107 ms, max 4.63 ms. So the component being inactive was a
Streets fact, not a general one, and re-adding the instrument before this run was necessary. The 2023
report of 5 ms/frame is half right: the *peak* matches at 4.63 ms, but the average does not - at 0.107 ms
it is ~1.3% of frame, so it spikes occasionally rather than costing every frame. Not a priority, but keep
it instrumented on every non-Streets map.

### Sniper scavs need rank, not radius

Distance to player is a good proxy for "can this bot affect the player" for every role except marksman.
Sniper scavs are placed at overwatch positions specifically to engage from beyond any sensible sleep
radius, so a 150 m rule guarantees one sitting at 200 m sleeps permanently and never takes a shot. That is
a behaviour regression, not a saving. Vanilla has the same flaw at its own 240 m, just further out.

`LongRangeExemption` keeps the **N nearest marksmen awake regardless of distance** (default 2). Ranking
rather than exempting the role is what bounds the cost: exempting outright would keep every sniper on the
map awake forever, fine with two and not fine with a dozen, whereas nearest-N costs exactly N whatever the
map holds. Re-ranked on the stand-by check interval, so a moving player promotes and demotes snipers as
they pass each other. Reported as `snipersAwake`.

### Cross-map validation — required before this is shippable

**Everything in this document was measured on Streets.** Several conclusions are explicitly map-specific
and must be re-checked before trusting them anywhere else:

- **`ambientLight` must be re-added to the telemetry.** It was dropped in the 2026-07-26 prune because it
  measured exactly 0 on Streets — but that is because the component is *inactive on that map*, not because
  it is cheap. The 2023 report of 5 ms/frame may well hold on maps where it runs. Re-add
  `AmbientLightLateUpdatePatch` and the `ambientLight` field before testing any other map; without it a
  regression there would be invisible.
- **Percentile baselines do not transfer.** p50/p95/p99 are map-dependent, as is any absolute ms figure.
  Comparisons must stay within a map.
- **The stand-by distances (150/130) are tuned for Streets' scale.** Factory and Labs are small enough
  that nearly every bot stays awake, so the three sleeping-bot fixes will save proportionally less; on
  larger maps they should save more.
- **Boss behaviour is untested.** `Force for all roles` is off, so bosses never sleep, but no map with an
  active boss has been run with the skips enabled.
- **The `presetBatch` change is global**, so its effect applies everywhere — but the wave sizes and role
  mix differ per map, and the per-profile cost may not.

### Others

- **Spawn-in**: 191 ms frames with `scripts` at 51.8 ms while bots arrive. `Player.Init`, pool
  instantiation, bundle work. Pool sizes are backend config (`ApplicationConfigClass.Pools`) and
  tunable without code.
- **Render**: 4.67 ms, still 45% of the frame and the largest single block. Largely outside what a
  Harmony mod reaches.
- **`ScriptRunBehaviourLateUpdate`**: 1.64 ms with `playerLate` now only 0.275 of it — ~1.36 ms of
  other MonoBehaviour `LateUpdate` remains unattributed.
- A magnified optic costs **~6.2 ms** (48 → 37 fps), ~94% of it render. Inherent to rendering a second
  view, not a bug.

---

## Methodology notes

Worth keeping — several of these cost real time to learn.

- **Unity's deep profiler systematically misleads here.** It instruments every managed call, inflating
  managed-call-heavy code (a recursive graph search) while Unity-native work (animation, culling,
  rendering) registers as one sample regardless of internal cost. This is why cover search looked like
  the top hotspot for years when the entire AI system is ~1% of the frame. Sampling the shipped game's
  own wall-clock timers has no per-call overhead and no such bias.
- **`render` includes the frame-limiter/V-Sync sleep.** It is measured through to `EndOfFrame`, so a
  capped-and-hitting-it player shows inflated `render`. Not a GPU number. Turn V-Sync off before
  trusting it. `gameUpdate` (= `frame − render`) is clean either way, which is why it was the reliable
  metric throughout.
- **Fixed spike thresholds do not transfer between maps.** 16 ms is 1.7× the mean on Customs but 1.3×
  on Streets, where it degenerated into "slightly above average" (43% of frames in one window). Use
  percentiles; p99/p50 is scale-free.
- **Location dominates everything on Streets.** Cross-window comparison is near-meaningless unless the
  position is held. A/B within one raid, standing still, with a reversal phase — the reversal is what
  separates a real effect from having wandered somewhere lighter.
- **BepInEx config is live-editable, so a header written at load can lie.** Config is recorded on every
  sample line for this reason; segmenting on `cfg.*` is how every A/B in this document was resolved.
- **Watch for instrumentation that cancels the thing it measures** (the `VisualPass` interaction above),
  and for counters that measure intent rather than effect (`animCulled` initially mirrored `asleep`
  regardless of whether culling was on).

  **The same field failed again on 2026-07-28, the same way, and this time it survived four months of
  analysis.** `SleepingBotAnimatorPatch.Sleeping` is a static `Dictionary<Player, BotStandBy>` whose entries
  are removed only when a bot's `StandByType` transitions away from `paused`. Nothing resets `StandByType` at
  raid teardown — `BotOwner.Dispose()` disposes 25 subsystems and never touches `StandBy` — so paused bots are
  pooled with their entry still live and **the dictionary never drains across raids.**

  The two-raid control run shows the offset appear (`animCulled = asleep` throughout raid 1, `asleep + 15`
  throughout raid 2). **The five-raid session of 2026-07-26 shows it compound**, which two raids cannot —
  `framesaver-20260726-170412-baseline.ndjson`, in-raid windows only:

  | raid | map | standing `animCulled − asleep` | left behind at teardown |
  |---|---|---|---|
  | 1 | Factory | **0** | 0 |
  | 2 | Streets | **0** | 18 |
  | 3 | Customs | **18** | 41 |
  | 4 | Interchange | **41** | 62 |
  | 5 | Customs | **62** | 76 |

  **0 → 18 → 41 → 62 → 76**, monotonic, never released, and the offset is constant to the unit within every
  raid. Two independent checks that the mechanism is exactly as described: Factory contributes **nothing**,
  because it is smaller than the 150 m sleep radius and nothing ever slept there; and each raid's increment
  (18, 23, 21, 14) tracks *that raid's own final `asleep` count* rather than any property of the next one.

  Flat *within* a raid is the other half of the mechanism — bots dying mid-raid **are** released, via the
  ownership re-check in `ApplyIfSleeping`. Only the teardown case leaks, because a torn-down bot never gets
  another `VisualPass` and never transitions out of `paused`.

  **The tell was visible the whole time and nobody read it: `animCulled` of 31–33 against a `total` of 20–22.**
  The field claimed more culled animators than there were bots, in every window of raid 2, in a document that
  reconciles `sum(phases)` against `frame` to 0.087 ms and checks `sum(SegGen0)` against per-phase counters.
  A counter exceeding its own population is a free consistency check that was never written down, which is the
  transferable lesson: **state the invariant a counter cannot violate, or nobody notices when it does.**

  Scope of the damage, because "a field is broken" invites over-correction. `animCulled` is listed in
  [README.md](README.md) as the evidence that [fix 1](#1-cull-sleeping-bot-animators--33-ms) still works, and
  for **raid 2 onward in any session it is not that evidence.** Raid 1 of any session is clean. Fix 1's
  measured effect size is unaffected — it came from `animation` and `frame` timings across a culling
  off/on/off reversal, not from this counter — and no conclusion in the stage-4 control run rests on it
  either. What is contaminated is any pooled or cross-raid use of the field.

  Behaviourally the leak is close to harmless: a stale entry makes `ApplyIfSleeping` skip `LateUpdate` and the
  world tick for a corpse, both near-empty for a dead player, and set `cullingMode` on an animator that
  `Player.OnDead` has already disabled. Pooled-and-recycled players self-heal on first touch via the ownership
  re-check. **The count is what is broken, not the game.**

  It is also a retention leak of precisely the shape this mod exists to fix — the entry holds a `Player` and a
  `BotStandBy`, and through `BotStandBy.BotOwner_0` the disposed bot's entire graph, which is the same shape as
  `AICoreControllerClass.HashSet_1` in confirmed fix 2. At 76 bots after five raids it is far too small to
  explain the 1.1 → 6.4 GB heap growth and should not be offered as a candidate for it, but it is our own
  version of the bug we shipped a fix for.

  Fix is small: clear `Sleeping` on the raid transition `Telemetry` already detects.
  `SleepingBotAnimatorPatch.ReadAndReset()` is an empty stub already sitting there for it.
- **~~The live DLL can be shown to be the build the control run was measured on~~ — WITHDRAWN, and the
  reasoning was wrong twice.** Recorded rather than deleted, because a withdrawn check is more useful than a
  missing one.

  The claim was that `obj/Release/Framesaver.csproj.CoreCompileInputs.cache` dating to 21:15 proves no
  compilation happened at 00:27, so the 00:27 file timestamp is a copy. **That does not follow.** MSBuild
  writes that cache with `WriteOnlyWhenDifferent`, so its mtime dates the last change to the *input set*, not
  the last compile. Against the claim: `Framesaver.csproj.AssemblyReference.cache` is 00:27:12,
  `obj/Release/Framesaver.dll` is 00:27:13 — and `obj` is the compiler's own output path, which a skipped
  `CoreCompile` does not rewrite. **`EscapeFromTarkov_Data/Managed/Assembly-CSharp.dll` is 23:22:09**, so a
  reference genuinely did move between the two builds and would have invalidated the up-to-date check. A
  recompile at 00:27 is the better-supported reading.

  **What makes it moot, and is the durable part:** the PE `TimeDateStamp` is `0xa07049d3`, high bit set — a
  content hash, not a time. **This is a deterministic build**, so identical source plus identical reference
  metadata yields byte-identical output including the MVID. Identity to the 21:44 binary is nonetheless
  **unverifiable by comparison, because that binary no longer exists.**

  **A comment-only edit changes the binary. Demonstrated, not argued.** A build at 01:54 on 2026-07-28 whose
  only source change was four comment lines produced `163ceaea…` where the previous build produced
  `94e2da31…` — **at exactly 99,840 bytes both times.** The mechanism is in the artifact: the debug data
  directory holds a `CODEVIEW` entry (type 2) and a `REPRO` entry (type 16), and under determinism the
  CodeView PDB GUID is content-derived, so changing a comment changes the PDB, which changes the GUID, which
  changes the DLL — with zero IL change. The 21:43:59 / 21:44:16 pair in COORDINATION addendum 7, identical in
  size and described as a comment-only rebuild, is the same thing seen once before and misread as identity.

  Three lessons, the last of which generalises furthest:

  1. **Size match is not identity, and neither is a timestamp.** Under a deterministic build the *hash* is
     identity, which makes hashing every deployed binary nearly free and the only check that works.
  2. **A build artifact's mtime answers "when was this written", never "what was compiled into it".** Every
     inference in this thread failed by treating one as the other.
  3. **A changed hash does not imply changed behaviour, and an unchanged hash does not imply an unchanged
     tree.** Hash plus determinism check cannot tell a comment from a behavioural change. Only the list of
     files that changed can, so a deploy record needs all three.
- **A per-frame residual is only as good as its two clocks agreeing.** The first spike-line implementation
  paired `GameFrameMeasurer.LastValue` with the current frame's phase snapshot — but that counter reports
  the **previous** frame. The `unaccounted` column was therefore off by a frame, which showed up as
  residuals that exactly equalled the *previous* line's `FixedUpdate` value, and as **negative**
  unaccounted (−226 ms in one case). Negative residuals are the tell; a residual that can go below zero is
  measuring two different intervals. Now measured as wall time between consecutive `ReadAndReset` calls,
  which is by construction the same interval the phase accumulators cover.
- **Beware a plausible artifact story that fits.** The recurring ~90 ms `Update` spike (below) looked
  exactly like the telemetry writer: `File.AppendAllText` from `Update`, one open/write/close per line,
  once per window, invariant across every config toggle. The writer was moved to a background thread —
  and **the spike did not move**, 77–86 ms in every window afterwards. Invariance across config
  narrowed it to "not one of our knobs"; it did not identify the cause, and treating it as confirmation
  was wrong. The background writer is worth keeping regardless, but it fixed nothing measurable.
- **An off-thread sampler is not free of observer effect, and the direction of its bias flatters the
  hypothesis.** `GC.GetTotalMemory(false)` reaches Boehm's `GC_get_heap_size()`, which takes the collector
  lock rather than reading a word. Polling it at 200 Hz against a main thread allocating hundreds of MB/s
  inside a GC-disabled span contends for exactly that lock — and the effect would be to *lengthen* the span
  being measured, which reads as confirmation. Sample each quantity at the rate its **shortest event** demands
  rather than picking one rate for the instrument, keep the high-rate path off any locking API, and **A/B the
  sampler itself** against the known replicate spread before trusting a trace.

  **Generalised 2026-07-28 on a second instance, which is what makes it a rule rather than a story about a
  sampler.** Expanding every player-loop phase charges the profiler's own timer reads **inside the top-level
  phase totals they report** — so `render` gains across the expansion boundary, a real and reproducible
  increase that is entirely the instrument. Different instrument, same property: the sampler's cost would have
  *lengthened the span it measured*; the profiler's lands *inside the number it produces*. Both biased toward
  the effect being hunted.

  **The first version of this paragraph understated that cost by 3×, in the direction the paragraph warns
  about.** It said "~140–200 reads, 3.5–5 µs", extrapolated from one expanded phase. The `Install()` line then
  reported **145 slots**, and each slot's Begin and End each read `Stopwatch.GetTimestamp()` *and*
  `GC.CollectionCount(0)` — so **580 reads per frame, ~14.5 µs, 0.088% of a 16.5 ms frame.** Still negligible,
  and three times what was written into a note about instruments understating themselves. **Estimating an
  instrument's cost is subject to the same bias as the measurement it perturbs**; the `Install()` count was
  available for free and neither estimate waited for it.

  > Before trusting an instrument, ask **where its own cost is charged.** If the answer is "inside the number
  > it produces", the bias has a direction — and the direction is usually toward the effect being looked for.

  Neither case is large enough to matter here (0.05–0.08% of a frame). The point is that the sign is knowable
  in advance and is not random, so it can be stated before the data rather than argued about after it.
- **A stop-the-world pause cannot be observed from inside the process it stops.** Boehm suspends every managed
  thread, so a background sampler is suspended too and can see nothing *within* a collection. What it can see
  is the **gap in its own timestamp series**, which is the pause. That inverts the design: the pause duration
  is measured by the absence of samples, not by their content, so the high-rate path needs only a QPC read and
  a counter — no heap read at all. It also kills the idea of separating mark from sweep by watching a plateau
  then a drop: for a monolithic collection there is nothing to watch. The gap *pattern* still discriminates,
  though — many small gaps mean the collector sliced, one large gap means it was forced to run whole, which is
  the open candidate-1-versus-2 question directly.
- **Validate a filter against the population it is about to remove, not against the thing it is meant to
  remove.** Both sessions proposed a self-defeating artifact filter within an hour on 2026-07-28, and each was
  caught only by running it against the data. A `period > 10 s` cut, justified as "safely above every real
  stall (the largest is 36 s)" — a sentence containing its own counterexample — would have deleted three real
  drain stalls including the raid-init callback. Its replacement, `asyncUpdate / period`, was worse: the ratio
  is *higher* for the artifact (0.0103) than for all 36 in-raid collection frames (0.0000), because a GC pause
  contains no drain, so it would have deleted the entire population the central finding rests on while
  keeping the artifact. Reasoning about what a filter should catch is not a check. Print what it drops.

  **And read the drop rate — it is diagnostic of the check, not of the corpus.** A hit rate near 100% or near
  0% is evidence about the instrument at least as much as about the data, and it is readable off the output
  without inspecting a line of the code. A table-syntax check written on 2026-07-28 flagged **~100% of tables
  across three documents**, including tables that predate the investigation and render correctly; the absurd
  rate identified the bug — a blank line satisfying its "is this a separator row" test — in a single command.
  The near-0% direction is the same tell and the more dangerous one, because a filter that removes nothing may
  simply not be matching, which is a [silent omission](#methodology-notes) wearing a filter's costume.
  **Before believing either extreme, run the check against one case you know is good and one you know is bad.**
- **A phase named for waiting is not evidence that a long sample was a wait.**
  `WaitForLastPresentationAndUpdateTime` genuinely is where the CPU blocks on presentation, which made
  "`TimeUpdate` is a GPU wait" feel like an explanation rather than a guess. It is the *first* phase of the
  frame, so anything blocking the main thread at a frame boundary lands there — and what was actually
  landing there was a stop-the-world collection. Naming a mechanism that could produce an observation is
  not measuring that it did.
- **`Stopwatch.GetTimestamp()` is not QueryPerformanceCounter under Mono.** On .NET it returns the raw QPC
  value; Mono returns 100ns ticks measured from **process start**. Both report `Stopwatch.Frequency` as
  10,000,000, so durations are correct either way and nothing looks wrong — but the epoch differs, so
  timestamps will not join against anything external. The first PresentMon capture had to be aligned
  afterwards by matching a 37-second stall present in both files by hand. `GpuTelemetry.Qpc()` now
  P/Invokes `QueryPerformanceCounter`. Durations elsewhere stay on `Stopwatch`, which is correct for deltas.
- **When joining against an external capture, know which end of the frame each side stamps.** Framesaver
  writes `qpc` at frame *end* (it samples from `Update`); PresentMon's `CPUStartQPC` is the frame *start*.
  Subtract `period` before matching, or every row lands one frame late.
- **A `try` inside a method does not protect against a type-resolution failure in that method.** The types a
  method references resolve when it is **JIT-compiled**, which happens before its body runs — so a renamed
  obfuscated type throws at the *call site*, one frame out, where the `try` isn't. This mod depends on 20+
  obfuscated names, and the failure compiles cleanly and smoke-tests clean on the current SPT: it only fires
  when a future version renames one, and then it presents as "telemetry mysteriously stopped" with no
  obvious link to the rename. Worse, an unguarded call site propagates the failure to everything downstream
  of it — one renamed graphics type would have taken out the drain and spawn instruments too.

  Game types appear in three places and each resolves differently, so **audit by position, not by method**.
  A grep grouped by enclosing method cannot tell them apart, and both sessions initially made that mistake:

  1. **Method bodies** — resolve at JIT of that method, so a guard at the *call site* covers them.
     `TryEnable` for Harmony registration (`GetTargetMethod()` is JIT'd inside its try) and an outer `try`
     latching a kill-switch for reporting paths.
  2. **Field declarations** — resolve in the class's **type initialiser**, which no guard inside the class
     can catch and which then poisons every member, including ones touching no game types at all. Strictly
     worse than 1. Never declare a field of an obfuscated type.
  3. **Method signatures** — parameter and return types. Usually covered like 1, *unless something outside
     your own code resolves the member.*

  Case 3 is where the rule needs its second half. `Prefix(GClass1516 __instance)` is not resolved at any call
  site we control: **Harmony reflects over the patch method during `Enable()`**. So the real question is not
  only "where does this type appear" but **"does anything other than my own code resolve this member?"** —
  reflection, serialisation and Unity's own message dispatch all qualify, and all bypass call-site guarding.
  A signature-typed member with no external resolver is safe; the same signature on a Harmony patch is not.

  Audited all three ways across `GpuTelemetry.cs`, `GcControl.cs`, `AsyncDrainPatch.cs` and
  `RaidInitPatches.cs` on 2026-07-27.
- **Sentinel values escape into the output when a window has no samples.** A `min`/`max` accumulator seeded
  with `double.MaxValue`/`MinValue` serialises as a 309-digit number if nothing was ever recorded, which
  breaks strict JSON consumers. Only bites accumulators sampled on a timer rather than per frame, since a
  window shortened by a state transition can legitimately contain nothing. Report a `samples` count
  alongside, so "no data" and "genuinely zero" stay distinguishable.
- **A threshold that surfaces a symptom can suppress its own evidence.** Distinct from the omission and
  inversion entries below, and worth its own line because the countermeasures for those do not touch it.

  The `unaccounted` slip moves time from frame N to frame N+1: a stall inside the `Update` phase lands in
  `period` on the line it happens and in the phase totals on the next. **So N is large and N+1 is ordinary —
  by construction.** Spike lines are emitted on magnitude, so N is always emitted and **N+1 never is**. The
  check for the defect was *"does a large-residual frame have a negative-residual line after it"*, and it
  returned **0 of 13** — not because the follow-up lines were clean, but because **none of the 13 had a
  following line at all**, the nearest being 2.9 to 31 seconds away at the run's 100 ms threshold.

  > A defect that displaces evidence by one sample is invisible to any filter that selects samples by
  > magnitude, because the displaced half is *normal* — that is what displacement means.

  **The tell is not the value, it is the absence of an adjacent sample.** Before concluding from a
  neighbour-comparison, check that the neighbours exist; a zero result over an empty population is
  indistinguishable from a zero result over a full one, and only one of them is a finding.

  **Countermeasure: count on every sample, not on the ones the trigger selects.** `negResidualFrames` and
  `frameOverPeriodFrames` are per-window counts over all frames for exactly this reason — two comparisons
  each, against a defect that spike-line analysis had put at 6.5% and whole-population counting was needed to
  show at 23.9%. *Found by Delta running Beta's proposed check and reporting that it could not run, rather
  than reporting its result.*

- **A clean result is not evidence when the failure mode is a silent omission.** The single most common defect
  in this project is an instrument that omits something, returns well-formed output shorter than reality, and
  agrees with what the author already believed. There is no local symptom: the output is valid, plausible, and
  wrong. **Six instances in two days, in three different kinds of artifact**, all caught by review rather than
  by anything in the output:

  | | the omission | what it would have produced |
  |---|---|---|
  | instrument | `GetComponentsInChildren<MonoBehaviour>` | no `Animator` — it derives from `Behaviour` — in a census built to examine animators |
  | instrument | `GetComponentsInChildren<Behaviour>` | no `Rigidbody`, `Collider`, `Cloth` or `Renderer`; the ragdoll claim it was meant to check is unreachable |
  | instrument | intersecting against types declaring managed `Update` | no native per-frame cost at all, `Animator` included — a clean managed list reading as a clean bill of health |
  | instrument | triggering `dead0` off the `OnPlayerDead` event | a sample ~46 lines before the animators are disabled, reporting `Animator.enabled: true` on a "corpse" — **inverting** the conclusion |
  | validation | `animCulled == asleep` in raid 1 | a pass, whether or not the `Sleeping` fix works, because raid 1 was always clean |
  | acceptance | "a `census` line at the first AI death" | a pass when one of four samples fires and three silently do not |

  Note the third row is where they compound: each layer was a correct widening of the one before, and each
  still omitted something, so **three consecutive fixes all returned clean.** The stage-4 `gcPhase` selection
  error is the same family reached from the analysis side.

  **The countermeasure that worked every time was a positive assertion naming a specific thing that must be
  present**, not a plausibility check on the output. `WeaponSoundPlayer` in the component list proves the
  enumeration recursed into `PlayerBones.WeaponRoot`; a `Rigidbody` row with `enabled: null` proves both that
  the `Component` widening took and that "no such property" did not collapse into "switched off";
  `aliveControl` proves the pre-death sample was uncontaminated. Each is one grep, and each converts a defect
  we caught by argument into one the run catches by measurement — which matters because **the argument is not
  present at runtime.**

  **Design bias that follows: prefer an instrument whose failure is implausible output over one whose failure
  is plausible output.** A table-syntax check written the same night flagged ~100% of tables in three
  documents; the absurd hit rate announced the bug immediately and it cost one command. A check that passes
  wrongly announces nothing and costs a run. Loud failure is a feature worth paying for.

- **A stale reference smells stale. An inverted one does not — and five failures on 2026-07-28 were all
  checks that ran and returned a pass.** The entry above is about instruments that could not see something.
  These are different and in some ways worse: **the safeguard was present, executed, and confidently wrong.**
  Collected in one pass because the shared property is the only thing that makes them recognisable — the
  countermeasures do not generalise and are listed per case.

  **Lead case, because it is the nastiest shape found so far.** `Expand phase` was an allowlist naming one
  player-loop phase to decompose. It became a **blocklist** the same day, keeping its key. Every existing
  reference silently reversed: the run-sheet line *"set `Expand phase` to `PostLateUpdate`"* — correct when
  written — became an instruction to **block the one phase the run existed to decompose**, producing a
  clean-looking run with no render breakdown and no error. An existing `.cfg` carrying `PreLateUpdate` from
  the allowlist era likewise flipped from expanding it to suppressing it.

  > **A setting that keeps its key while reversing its meaning converts every existing reference into a
  > confidently wrong instruction, and nothing in the text looks stale.**

  **Countermeasure: rename the key, do not just re-document it.** BepInEx orphans an unknown key and creates
  the new one at its default, so a stale value becomes **inert** rather than **inverted** — the only fix that
  does not depend on a reader noticing something that looks correct. Fail-safe beats fail-noticed. Three
  documentation mitigations were written first and all three required someone to read them.

  *Specimen: Gamma, who wrote the run-sheet line and specified the inversion that reversed it, two hours
  apart, without connecting them.*

  **The countermeasure generalises past config, and that is the durable half.** Renaming the key, emitting
  `null` rather than `0` where a type has no `enabled`, and making an unsure frame report nothing rather than
  a number are the same move: **change the artifact so the wrong state cannot be reached, instead of relying
  on a reader to notice.** The alternative in each case was a note someone had to read at the moment they
  were most confident they already understood — which is the moment the advice fails. *Delta's framing, on
  the observation that "apply the rule you just derived to the correction itself" is advice, and advice does
  not survive believing you have just understood the error.*

  The other four, with what each actually needed:

  | | the failure | countermeasure |
  |---|---|---|
  | **A separate field is not an independent measurement** | `render = frame − gameUpdate` was defended as two independent instruments because `gameUpdate` is read from its own BSG measurer. It is — and that measurer is *defined* as `frame − render` forty lines into the class already being cited. The check verified a separate **field**, not an independently **computed** one. | Follow the field to its definition. A verification that stops at "different object, different field" has stopped where checking *feels* complete, one level above the answer. The tell was that agreement was 0.0024 ms rather than merely close — that is one interval measured twice, not two instruments agreeing. |
  | **A truncated search is a silent omission with a byline** | *"`presetBatch` appears in no `.cs` file"*, concluded from a `head -20` grep whose output was flooded by locale JSON. | Count before reading. A search that was cut reports absence indistinguishably from a search that found nothing. |
  | **Match the statistic to the question** | A near-miss: blocking `Initialization` and `PreUpdate` from expansion on medians of 0.005 and 0.028 ms — while FINDINGS already recorded *one `Initialization` at 74.8 ms* among in-raid spike frames. | **A spike instrument must be configured on tail behaviour, never on averages.** A phase with a negligible mean can carry a rare large spike, so selecting on the mean reintroduces exactly the omission the change was meant to prevent. Distinct from the others: the instrument was fine, the *aiming statistic* answered a different question. |
  | **A filter's failure direction is a property of its purpose, not of the filter** | `git add -A` swept another agent's in-flight source and a build artifact into a commit described as documentation-only. | Commit by explicit path. Failing toward *taking too much* is the correct direction for an instrument — it is the whole argument for the expansion blocklist — and the wrong one for a commit. The same default is safe in one context and unsafe in the other, so "which way does this fail" must be re-asked per use rather than settled once. |

  *Specimens: Alpha for rows 1–2, Gamma for rows 3–4.*

  **What none of them were: carelessness.** Every one came from a step performed *because* it was the careful
  thing to do — verifying a suspected tautology, grepping before asserting, choosing a threshold from measured
  data, staging work before committing. **The check is not a safe place to stop thinking**, and the practical
  consequence is the one the day already demonstrated repeatedly: these were caught by a second person
  re-deriving from source or raw logs, never by the author re-reading their own work.

  **The asymmetry is in the role, not the reasoner** (Delta, 2026-07-28). A reviewer arrives already knowing
  what the work concluded, which is the cheapest possible position from which to check it — so a run of
  catches says nothing about who is more careful, and reading it that way would make the next reviewer
  reluctant to look foolish. Every agent on this project was both specimen and catcher within the same day,
  several times inside corrections they had written for earlier errors.

  **So the thing worth keeping is not any individual catch: it is that nobody defended a number once it was
  checked.** That is what made a day with this many defects cost zero runs, and it is the only part of the
  practice that has to survive contact with being wrong in public.

  **Addendum, 2026-07-28: a name match is not a code-path match, and the counterexample was in this
  document's own opening.** Fixing the census's missing weapon took three source reads and all three were
  wrong. Beta merged two lines that each contained the words being looked for. Then Gamma proposed rooting the
  census on `HandsControllerClass`, citing line 718 where `BaseSoundPlayer` is fetched from the controller's
  own `gameObject` — true of that class, which **our bots never instantiate.** `HandsControllerClass` is the
  `ObservedPlayerView` path; SPT bots are `LocalPlayer` and use `Player.AbstractHandsController`.

  **The verification and the citation were about different classes with similar names.** Checking
  *"is `AbstractHandsController` a `MonoBehaviour`?"* — yes — and then quoting a line from
  `HandsControllerClass` felt like one check because the names blur. The proposed root was also
  `player.gameObject` by another route, since the controller is `AddComponent`'d onto the player, so it would
  have enumerated the subtree already covered, grown the census by the controller's own components, and
  **looked like a fix.**

  **[The architectural cause](#the-architectural-cause) section states the distinction that would have caught
  it** — bots are `LocalPlayer` where live EFT uses `ObservedPlayerView`. It is arguably this investigation's
  most load-bearing structural fact, and it did not fire when the two representations' class names appeared
  side by side. **A document knowing something is not the same as it being applied**, which is the same
  distance as a label knowing a qualifier and a reader dropping it.

  **And the honest reason it was cheap is the corpus, not the care** (Delta, 2026-07-28). Every catch above
  landed on data already on disk — fifteen ndjson logs and three PresentMon captures, re-derived as many times
  as anyone wanted for free. The same defect rate against a workflow where each check costs a raid would have
  been a different day entirely. **The transferable lesson is not "we caught a lot", it is "being wrong was
  cheap because the corpus was rich enough to be re-queried"** — which is an argument for the telemetry
  investment rather than for anyone's diligence.

  The corollary sets the price of the next step: a measurement that no existing log can reproduce loses this
  protection entirely. That is why the `endToStart` bracket's prediction was registered **before** the
  instrument had ever produced a number — a pre-registration is the substitute for cheap re-derivation, and it
  is only a substitute.
- **A label is not a caveat. A qualifier that lives anywhere except the number will be dropped by the first
  person who quotes it.** Two figures in this document were misread this way four days apart, and **neither
  was a measurement fault** — both numbers were correct, and in both cases the qualification was sitting in
  plain sight somewhere other than the value.

  | | the figure | where the qualifier lived | what it became |
  |---|---|---|---|
  | 2026-07-26 | `best p50` = 11.51 ms, Streets | **in the column name** | quoted to the user as the Streets baseline, manufacturing a 40% instrument-versus-experience discrepancy against a real median of 16.51 ms |
  | 2026-07-28 | 22 of 23 collections in `TimeUpdate` | **in a field's absence** | a population of 36 reduced to 23, by filtering on the frames where `gcPhase` existed |

  So the two need different checks, and only the first is a matter of wording:

  - **Labelled qualifier — requote with the qualifier or not at all.** `best`, `capped`, `max`, `p99` are part
    of the figure. A best-of number is only meaningful against another best-of number, and the moment it is
    compared against a typical experience it has been converted into a different claim.
  - **Absent field — count the population you think you have against a field that is always present.** The
    `gcPhase` discrepancy needed no new data to spot: 23 attributed frames against 36 carrying `gcGen0 > 0` is
    two fields on the same lines disagreeing. **A population defined by "the field is present" is a population
    defined by the instrument's success**, and an absent field is a silent exclusion with no local symptom.

  Both were caught by re-deriving from the raw logs, neither by re-reading the prose — which is the practical
  lesson. Prose preserves a number and drops its qualifier; the log still has both.

- **A spike threshold must never change silently, and must sometimes change.** `Spike event ms` went 100 → 50
  once before, and spike *counts* either side of it measure different populations — the existing caveat on the
  FixedUpdate-move run. That is an argument for announcing the change, not for freezing the value: at a 100 ms
  threshold a working incremental GC slice is **invisible**, because one 110 ms pause becoming four 30 ms
  pauses removes every spike line while leaving window `gcGen0` unmoved, so success and no-effect produce
  identical output. When the threshold is the thing that decides whether an effect can be seen, change it and
  carry the change in the run tag and the header — and record which prior runs the counts no longer join to.
- **A window flushed *by* a state transition is not a window *of* that state.** A state change forces a flush
  first, so the last `state: raid` window of every raid is written at teardown, when
  `BotsController.Bots.BotOwners` is already empty. It reports `bots.total: 0` against an `agents.live` of
  18–25 carried from the previous AI tick. Sixteen of the nineteen raids in the log set contain exactly one
  such window. **`final` does not mark them — 0 of 16** — because `final` belongs to the line written when
  `GameWorld` goes away, one state later. **Filter bot populations on `bots.total > 0`.** This is an
  analysis-side defect rather than an instrument one, which is why it survived so long: averaging
  `awake`/`asleep` across a raid's windows quietly pulls a zero into every per-bot effect size quoted here.
- **`awake + asleep` is the live bot population — measured, not guaranteed.** `CountBots` walks
  `Bots.BotOwners` and silently skips any bot whose `StandBy` is null, so the field counts
  bots-with-stand-by rather than bots. Cross-checked against `agents.live`
  (`AICoreControllerClass.HashSet_0.Count`, an independent source applying no such filter): **136 of 156
  in-raid windows agree exactly.** The only disagreements are the teardown artifact above and four windows
  at +1/+2, each of which created a bot in that same window — registration lag, not exclusion. Corpses do
  leave the accounted population, but they leave *both* counts together, which is why two independent
  instruments agree; the denominator is consistently live bots and is not silently shrinking.

  **The bound comes from `agents.live` agreeing, not from the exclusion being unreachable.** A mod that
  leaves `StandBy` null on a live bot makes the two counters diverge with no other symptom. That is the
  difference between measured-harmless and harmless-by-construction. Worth a comment at the skip rather than
  a fix — and worth re-running the cross-check whenever the mod stack changes.
- **A correct general rule, applied where it does not bite, reads as diligence.** The component census was
  specced to take its post-death sample from the `Player.OnPlayerDead` *event* rather than a Harmony postfix,
  to avoid the JIT type-resolution hazard above — a rule this document already carries and which has already
  saved a subsystem. But `Player.OnDead(EDamageType)` references no obfuscated type, so the rule bought
  nothing here, while the event fires at
  [Player.cs:7411](../../Src/Assembly-CSharp/Assembly-CSharp/EFT/Player.cs:7411) and the animators are not
  disabled until 7454, with `CreateCorpse` at 7521. The census would have reported `Animator.enabled = true`
  on its subject and read as **"corpses keep their animators"** — inverting the finding it exists to test, on
  a line that looks clean.

  A wrong rule is easy to catch: it produces visibly wrong results. A right rule in the wrong place produces
  a defensible-looking choice with no local symptom, and the citation makes it *harder* to question rather
  than easier. **After invoking a rule, say what it costs here and what it buys here.** If what it buys is
  "nothing, the hazard is not present", then the rule is not an argument for the choice and the choice needs
  its own.

  **Four near-misses on this one instrument, all in the same direction.** `MonoBehaviour` instead of
  `Behaviour` cannot see `Animator`; `Behaviour` instead of `Component` cannot see the ragdoll or any
  renderer; the event trigger samples before the teardown it is measuring; and a spawn-versus-corpse baseline
  confounds death with role, loadout and raid phase. Each would have returned a *clean* result agreeing with
  the conclusion already held — and nothing prompts a re-check when the answer is the expected one. This is
  the [`animCulled`](#refuted--do-not-re-tread) failure generalised: an instrument structurally unable to see
  the thing it is looking for is worse than a missing instrument, because it produces evidence. **Ask what an
  instrument cannot see before asking what it found.**

  **A truncated search is a silent omission with a byline.** A `grep` for `presetBatch` across SPT's server
  was piped through `head -20`, the output was flooded by twenty-odd locale JSON files, and the `.cs` hits
  were pushed off the end — from which it was concluded that the C# rewrite had dropped the code path
  entirely. The path is at `BotController.cs:356`. The instrument could not show everything, what it did show
  agreed with an interesting hypothesis, and nothing about the output looked wrong. **When a search result is
  dominated by one file type, exclude it and re-run rather than reading the first twenty lines** — the count
  of matches is the tell, exactly as an extreme hit rate is for a filter.

  **Two of the four were sitting in this document, in the proposal that raised the question.** The original
  sketch specified `GetComponents<MonoBehaviour>()` on a bot at spawn and again on a corpse — the narrowest
  possible type filter and the confounded baseline both — written into the same entry that now records the
  pattern. It is the only one of the four that reached a written artifact rather than being caught in review,
  and that is the sharpest form of the rule: **review caught every defect that was still a proposal and
  caught none of the one already written down as settled.** Text that has been accepted stops being read as a
  claim. Re-audit a specification when the thing it specifies changes, not only when someone questions it.
