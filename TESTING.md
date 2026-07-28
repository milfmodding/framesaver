# Testing protocol

Validation of Framesaver on a clean SPT 4.0.13 install, in three stages of increasing mod load.

**Nothing in [FINDINGS.md](FINDINGS.md) carries over.** Every number there was measured on SPT 3.x. If
comparing across maps is unsafe — and it is, that is the first methodology rule — then comparing across SPT
versions is worse. Treat 4.0.13 as an unmeasured platform.

## Success criteria

Set by Sophia 2026-07-28. Everything else — mod compatibility, telemetry pruning, shipping cleanup — is
subordinate until both are met.

**1. Consistent 100+ fps on every map except Streets. Streets at 60+.**

Streets was originally set at "60+ acceptable, more is better", and **revised the same day to 60+ as the
target rather than the floor.** Sophia's call: *"there's windmills worth chasing, and then there's just
running into a brick wall"*, and 60 consistent is better than Streets has been reported to run.

**The revision stands. The argument originally given for it does not, and both halves were corrected on
2026-07-28 — read this rather than the version relayed at the time.**

~~*100 fps on Streets is arithmetically unreachable: the regression intercept is 13.25 ms, i.e. 75 fps with
every bot asleep.*~~ **Withdrawn.** A regression intercept is a conditional mean, not a floor, and **nine of
99 Streets windows sit below 13.25 ms** — the low-awake windows, not high-awake outliers. The best is
**9.47 ms = 106 fps, observed, on Streets, at 7 awake bots.** The intercept is also **not identified**:
`corr(awake, asleep) = −0.954` over a near-constant total of 16–27, so it moves to 10.78 ms with +0.114 ms
per sleeping bot in a model carrying both, R² gains 0.004, and **the two models imply opposite strategies**
about whether further sleeping-bot work has headroom. Nothing in the data arbitrates. The "replicates to 2%"
claim was worthless too: the single-raid `13.5 + 0.507` fit matches the one-variable model's *intercept* and
the two-variable model's *slope*.

**Do not invert this.** 9.47 ms is a best-of window and is **not** evidence Streets can hold 100 — requoting
it that way is the same error as the `best p50` misquote below, one day later.

**What survives is the render bound**, which needs no model and no intercept:

| Streets `render`, 99 windows | min | median | max |
|---|---|---|---|
| | **4.85** | 6.53 | 8.21 |

`corr(awake, render) = +0.187`, so it barely tracks bot count — which is the property that makes it a floor
and the intercept never had.

~~*A 10 ms budget therefore leaves under 5.2 ms for the entire update side, against a current `gameUpdate` of
6.5–24.5 ms.*~~ **Withdrawn 2026-07-28 — this reproduced the defect it replaced, and so did the other
candidate replacement.** Both subtract or sum **window averages** (`render` min 4.85, `gameUpdate` min 6.50)
and apply the result to a **percentile** target. The distribution is right-skewed — median `avg − p50` gap is
0.58 ms — so any floor built that way is violated by observed p50s: **3 of 99 Streets windows sit below
11.35 ms**, and the minimum is 9.47 ms. A floor that observed data goes below is not a floor, which is exactly
why the intercept was struck. *Two* proposed replacements had the same shape, arriving inside the correction
for it.

**The criterion needs no arithmetic and nothing can violate it: 1 window in 99 reaches 100 fps on Streets.**
Stated in one statistic, on the population the criterion is about. *Consistent* 100+ is therefore not
reachable — which is what the criterion said. "Impossible" was too strong and licensed a different decision.

The render composition below still stands on its own terms — it is a statement about what `render` is made of,
not a bound on the frame — but **do not recombine component minima into a frame-level floor.** If a bound is
wanted, build it from the same statistic on the same population, or quote the population directly.

~~*render is largely outside what a Harmony mod reaches.*~~ **Also wrong, and it was never tested before
being written.** `render` is *by construction* the `PostLateUpdate` phase on the main thread —
`GameUpdateMeasurer` is defined as `frame − RenderMeasurer` (`GClass1357.cs:87`), and BSG injects
`StartOfPostLateUpdate` and `EndOfFrame` as the first and last subsystems of that phase. PresentMon puts
`CPUWait` at **0.053 ms p50** over 182,845 rows, so it contains no meaningful GPU sync: it is reachable
main-thread CPU work.

**But the reachable *portion* is small.** `render = 5.27 + 0.000467 × drawCalls` on Streets — 0.47 µs per
draw call, a normal single-threaded D3D11 submission cost, consistent with `graphicsMultiThreaded: false`.
Draw calls span 4.1× across 38 windows (1,141–4,648) while render spans only 5.63–7.81 ms, so **79% of
Streets render is a constant that draw calls do not reach.** Eliminating submission entirely — impossible —
buys ~1.4 ms of 6.6. Real, worth having, not a route to 100 fps.

Caveats on that composition: n = 38, observational, and **location is not held on the map where location
dominates everything**. `drawCalls` also indexes everything view-dependent — culling, shadow passes,
batching — so the partial correlation cannot separate submission from any other on-screen cost. Settling it
needs a within-raid A/B from a fixed position that moves draw calls without moving what is drawn.

**2. No in-raid hitches.** Loading hitches are wanted eventually and are explicitly secondary — the reason is
concrete: dying to a stutter in an early fight, once testing stops running with invincibility.

### Measured against those criteria, neither is met yet

Pooled across every in-raid window in all 15 logs, teardown windows excluded per the `bots.total > 0`
filter. **Read the medians, not the `best p50` column in the stage-1 table** — that column is a best-window
figure and was misquoted as a baseline, which is what produced a phantom 40% disagreement with the user's own
observation:

| map | n | best | median | p75 | median fps | windows at 100+ |
|---|---|---|---|---|---|---|
| `tarkovstreets` | 99 | 9.47 | **16.51** | 18.69 | 61 | 1 of 99 |
| `bigmap` | 25 | 8.34 | **10.03** | 10.88 | 100 | 12 of 25 |
| `interchange` | 7 | 7.63 | **9.84** | 11.97 | 102 | 4 of 7 |
| `factory4_day` | 9 | 5.70 | **8.33** | 8.33 | 120 | 9 of 9 |

Streets sits at 61 fps median — goal met at the median, but **47 of 99 windows are at or below 60 fps**,
which is why it feels marginal. (Below the 60 fps criterion, not below the median.) Customs and Interchange sit *at* 100 as a median, so roughly half their windows are under.
**Factory is not evidence**: median and p75 are both exactly 8.33 ms = 120.0 fps with `gameUpdate` averaging
5.42 ms, which is a frame-cap signature rather than a measurement. So **no map yet demonstrates a consistent
100+**.

Caveats that must travel with the table: `n` is 7 and 9 for Interchange and Factory and those medians are
near-anecdotal; the pooling crosses mod stacks, dates and builds, so the spread overstates
achievable-versus-not; and the no-cap confirmation rests on the 50 windows carrying a `gfx` block. That
confirmation is what makes these performance rather than pacing figures — `targetFps: -1, vSync: 0` is
unanimous across every in-raid window that reports it, so there is no limiter sleep inside `render`.

**What goal 1 now needs is the part of the frame nothing has attributed**, not the per-bot slope. Every fix
shipped so far attacks the 0.402 ms per awake bot. What is left is a ~4.85 ms render floor that draw calls
reach only ~1.4 ms of, plus **2.5–3.5 ms of `ScriptRunBehaviourUpdate` that remains entirely unattributed** —
whose leading suspect, per-bot weapon audio, was eliminated at 0.002–0.005 ms across 43–49 instances, so the
block is *more* mysterious than it was. `ScriptRunBehaviourUpdate` is a player-loop **leaf** with no internal
structure a marker can bracket, so the component census is not merely the best path to it, it is the only
one.

**Goal 2 has two in-raid families, not one, and they are similar in size.** With the drain eliminated by the
spawn fix:

| family | n (control run) | median period | signature |
|---|---|---|---|
| stop-the-world collections | 35 | 128.4 ms | `gcGen0 > 0`; `frame ≪ period` on the residual half |
| **unnamed, no collection** | **12** | **201.9 ms** | no `gcGen0`, no drain, `TimeUpdate` absent, `frame ≈ period` |

The second is **larger per event**, is CPU-side by PresentMon, and has never had a name or a cause. It had
been absorbed into the GC finding by a bucket boundary until 2026-07-28. **Eliminating in-raid hitches
requires both.**

**Scoped across all 15 logs it is bigger than the control run showed: 36 frames, 20 on Streets and 16 on
Customs, across 7 logs, period to 402 ms (median 334).** Only 58% fall inside the first 120 s and the latest
is at 742 s, so stage 1's *"confined to the first minute or two"* must be widened rather than reused. Three
hypotheses are dead — not a present/GPU wait (`CPUWait` median 0.077 ms against `CPUBusy` of 203 ms), not
ALT-Tab or focus loss (`PresentMode` is `Hardware: Independent Flip` on every one and either side; the whole
182,845-row capture holds 10 `Composed: Flip` rows, none nearby), and not shader compilation, which happens
at draw time inside `PostLateUpdate` — and that phase reads an ordinary 3.8–15.3 ms on all of them.

**The time sits between the last `PostLateUpdate` subsystem of frame N and the first `TimeUpdate` subsystem of
frame N+1 — outside `PlayerLoop()` entirely.** Realistically the Win32 message pump. The instrument is
correspondingly cheap: SPT already brackets that interval, inserting `EndOfFrame` last in `PostLateUpdate` and
`StartOfFrame` first in `EarlyUpdate` (`CustomPlayerLoopSystemsInjector.cs:15–16`). A `Stopwatch` across those
two events captures native gap + `TimeUpdate` + `Initialization`; the latter two are already measured, so
subtraction yields the gap. **Two event subscriptions, one spike-line field, no Harmony patch and no
obfuscated types** — so none of the JIT-resolution exposure. **This is sequenced above work-queue item 1**: it
costs a fraction of the off-thread sampler and closes the last unexplained in-raid family, which is goal 2,
where the sampler serves loading.

### Work-queue item 6 is promoted — the collector demonstrably slices

Item 6 (`GC time slice ms`, `Drive incremental GC ms`) sat last on the argument that if the extra cost is
Boehm's *sweep* then no scheduling knob can touch it. **That premise is now wrong.** `TimeUpdate` on in-raid
spike frames is trimodal across all logs — **< 0.5 ms on 136 frames, 2.9–3.2 ms on 69, > 10 ms on 73**, and
three others. Baseline `TimeUpdate` is 0.094 ms and the header reports `timeSliceNs: 3000000`. **The middle
mode is the 3 ms incremental slice, observed 69 times**, and the thirteen residual-plus-collection frames read
3.01–3.27 ms with twelve of them within 0.06 ms of each other.

So candidate 2 as usually stated — *"only marking is incremental, nothing schedulable is happening"* — is
refuted: slicing is visible in the data. That gives the knob a **falsifiable prediction rather than an
open-ended trial: raise the slice and the middle mode must move.** If it moves, the knob is live and the
instrument is confirmed at once. If the mode does not move at all, that is a far sharper negative than "the
knob did nothing", which is the outcome item 6 was demoted for producing.

It also reopens the reading of those thirteen frames: they carry a **normal** 3.02 ms slice *and* 80–218 ms of
residual, so "the collection *is* the residual" is no longer the only interpretation. Independence is refuted
either way — expected coincidence 0.01 against 13 observed — but the direction is open.

## Status

| Stage | State |
| --- | --- |
| 1 — Framesaver alone | **Done** 2026-07-26: Factory, Streets, Customs, Interchange. All pass. Results in [FINDINGS.md](FINDINGS.md) |
| 1b — config completion | **Required before stage 2** — see below |
| 2 — SAIN + LootingBots + QuestingBots | **Done** 2026-07-26: Factory, Streets ×4. Parity with the no-mods baseline reached after three fixes — see FINDINGS |
| 2b — QuestingBots removed | In progress: isolating whether the 19 s loading generation is QuestingBots' |
| 3 — AILimit | Not started |

Woods, Reserve, Shoreline and Lighthouse were dropped from stage 1 by decision — four maps gave consistent
enough results to move on. Reserve and Lighthouse remain the only untested boss-scripting cases (Gluhar and
Zryachiy, the two roles that cannot stand by at all).

### Stage 1b — one raid, then freeze

Stage 1 ran with `skipLate: false`, `skipTick: false`, `asyncBudgetMs: 0`, so two confirmed fixes were
disabled and the drain was unbudgeted. Enable them, run **one** validation raid on Customs (which now has a
clean 4.0.13 baseline), then change nothing else for stages 2 and 3.

| Setting | To |
| --- | --- |
| `4. Experimental → Skip sleeping bot LateUpdate` | `true` |
| `4. Experimental → Skip sleeping bot world tick` | `true` |
| `4. Experimental → Async drain budget ms` | `4` |

Watch for bots returning from sleep in a wrong pose — that is `skipLate`'s failure mode and the reason it
ships off. Expect little visible change from the drain budget on large maps: Streets, Customs and
Interchange had almost no in-raid drain stalls to slice. It is insurance for Factory-shaped cases, and it
does **not** affect the loading freeze — those are single monster callbacks a per-call budget cannot
interrupt, and their real cause is GC. See FINDINGS.

To actually quantify the two skips, run the off→on→off reversal from a fixed position. Simply enabling
them and playing a normal route does not isolate the effect — awake/asleep counts and location both move.

**Then freeze the config.** Stage 2 must change exactly one thing: the mods.

### Settings that stage 2 proved matter

Learned the hard way; carry these into any run with an AI overhaul installed.

| Setting | Value | Why |
| --- | --- | --- |
| `Keep fighting bots awake` | **false** | With SAIN + QuestingBots this alone held 50–58% of bots awake regardless of distance |
| `Reclaim stand-by from QuestingBots` | true | Without it QuestingBots disables the stand-by system completely |
| `Set sleeping bots to NonActive` | true | The only thing SAIN, LootingBots and QuestingBots actually gate on |
| `Skip sleeping bot LateUpdate` | true | Confirmed ~2.3 ms; ships off, so it must be set explicitly |
| `Skip sleeping bot world tick` | true | Confirmed ~0.45 ms; same |
| `Suspend GC during completion callbacks` | true | Removes ~80% of collections during loading; small win, no downside measured |

**Config hygiene, learned by losing a raid to each:**

- A new entry does not exist in the `.cfg` until the plugin has run once with the new build. Launch, quit,
  *then* set it.
- Editing the `.cfg` while the game is running is silently overwritten on exit. Edit with the game closed,
  or use the in-game F12 manager.
- Every behaviour flag is now recorded in the `cfg` block on each sample line — check it in the first
  window rather than trusting the file.

Server-side, `presetBatch` capped at 5 cut the worst in-raid callback from 1,242 ms to 150 ms. That is a
`SPT_Data/configs/bot.json` edit (backup at `bot.json.framesaver-backup`) and needs a **server** restart,
not just a game restart. Shipping it means a server mod overriding `botConfig.presetBatch` in `postDBLoad`.

## Setup

| | |
| --- | --- |
| Install | `F:\SPT\SPT4.0.13` |
| Plugin | `BepInEx\plugins\Framesaver.dll` (post-build step copies it there) |
| Config | `BepInEx\config\framesaver.ai.perf.cfg` — written on first launch, **not** the `F:\SPT\Base` path |
| Logs | `BepInEx\plugins\Framesaver-logs\framesaver-<timestamp>-<tag>.ndjson` |

One log file covers a whole game session, and every line carries `raid` and `map`, so a single launch can
cover several maps back to back. **Set `Run tag` to the stage** (`solo`, `ai-stack`, `ailimit`), not the map.

Confirm before the first raid: V-Sync **off**. `gameUpdate` excludes the frame-limiter sleep, but `frame`
does not, and a capped `frame` makes percentile comparisons meaningless.

## Method: A/B inside one raid

Do not run separate baseline raids. Location dominates frame time, so a between-raids comparison mostly
measures where you walked.

From a fixed position, run **off → on → off**. The reversal is what separates a real effect from having
wandered somewhere lighter. Config is live-editable and recorded on every sample line as `cfg`, so
segmenting on it afterwards is how every A/B in FINDINGS was resolved.

For stage 1 the toggle is `1. Bot stand-by → Enabled` plus the two experimental skips. Give each segment at
least two full windows (120 s at the default) so percentiles mean something.

## Stage 1 — Framesaver alone

No other mods. Establishes that the methods replicate on 4.0.13 and break nothing map-specific.

| Order | Map | `map` value | Why |
| --- | --- | --- | --- |
| 1 | Factory *(optional)* | `factory4_day` | 3-minute smoke test — dense bots, fast load. Surfaces a crash or mass T-pose before committing to a 40-minute raid |
| 2 | Streets | `tarkovstreets` | Stress test; the map every existing number came from |
| 3 | Customs | `bigmap` | Sniper exemption — you know all four marksman positions |
| 4 | Woods | `woods` | Open sightlines, long distances |
| 5 | Reserve | `rezervbase` | Boss scripting (Glukhar), heavy verticality |
| 6 | Shoreline | `shoreline` | Large, mixed |
| 7 | Interchange | `interchange` | Dense interior geometry |
| 8 | Lighthouse | `lighthouse` | Boss scripting (Zryachiy) — see below |

### Pass criteria

Per raid, from the log:

- `spawn.creates` ≈ `spawn.botOwners` (ratio near 1.0, not 70)
- `bots.asleep` > 0 once you are away from the spawn cluster — the stand-by system is firing
- `ambientLight` avg **non-zero** on every map except Streets, where the component is inactive rather than cheap
- `asyncDrained` spike frames at or near 0 during raid
- `agents.pendingRemoval` not climbing monotonically across windows
- No `final:false` gap where sampling stopped unexpectedly

In play: no T-posing, no bots frozen mid-animation on wake, no missing gear, bosses behave normally.

## Stage 2 — the AI stack

Add SAIN, LootingBots, QuestingBots together. Same map order. Bisect only if something breaks.

**QuestingBots changes our headline metric.** Its scav limiter blocks spawns at
`BotSpawner.TrySpawnFreeAndDelay`, so `spawn.creates` will move for reasons that are not us. A drop there is
QB working. Do not read stage 2 spawn numbers against stage 1.

Expect SAIN to cooperate without configuration: it gates its own per-bot work on `BotOwner.IsBotActive()`,
which reads the stand-by state we set. See [COMPATIBILITY.md](COMPATIBILITY.md).

## Stage 3 — AILimit

**Two maps only** — one small, one large (Factory or Customs, plus Streets). The guard is binary and
map-independent: either it fires or it does not.

What to confirm:

- The startup log line reports AILimit detected and the stand-by patch standing down
- `bots.asleep` and `snipersAwake` go to 0 or become meaningless — expected, we are not driving pausing
- Frame times are no worse than AILimit alone
- The parts that do *not* stand down still work: `asyncDrained`, animator culling, spawn counters

Known and accepted: the sniper exemption is lost under AILimit, which has no role awareness. Reasoning in
COMPATIBILITY.md.

## Which metrics carry across stages

| Metric | Stage 1 | Stage 2 | Stage 3 |
| --- | --- | --- | --- |
| `frame` / `gameUpdate` percentiles | yes | yes | yes *(within a map)* |
| `asyncDrained` / `worstCallbacks` | yes | yes | yes |
| `ambientLight` | yes | yes | yes |
| `agents.pendingRemoval` | yes | yes | yes |
| `bots` awake/asleep, `snipersAwake` | yes | yes | **no** — we stand down |
| `spawn.creates` vs `botOwners` | yes | **no** — QB changes it | **no** |

## Testing the sniper exemption

Only `WildSpawnType.marksman` is covered. Confirmed from the 4.0.13 bot database:

| role | `Mind.CAN_STAND_BY` | covered by exemption |
| --- | --- | --- |
| `marksman` | True | **yes** |
| `assault` | True | no — normal distance rules |
| `bossZryachiy` | False | no |
| `followerZryachiy` | False | no |

**Zryachiy is not a test of this.** He and his tower followers are separate `WildSpawnType`s, and both have
`CAN_STAND_BY = False`, so `InitPoints` clears `CanDoStandBy` and our `Update` prefix returns immediately.
They never sleep with or without Framesaver — the test would pass regardless of whether the exemption works.
Lighthouse is still worth running, as a check that boss scripting is *unbroken*.

**Do not provoke with a hit.** `BotStandBy.GetHit` grants a 30 s wake grace after damage
(`MIN_TIME_AFTER_HIT`), and `Keep fighting bots awake` then holds the bot awake while it has a goal enemy.
Landing a shot wakes a sleeping sniper regardless of the exemption, which invalidates the test.

Valid tests, best first:

1. **Read `snipersAwake` in the log.** Direct evidence. Should be between 1 and `Keep nearest snipers awake`
   (default 2) whenever live marksmen are on the map. 0 with snipers alive means the exemption is not firing.
2. **Get shot at first.** Stand in a known marksman's sightline beyond the 150 m sleep distance, unprovoked.
   Him engaging you can only happen if something kept him awake.
3. **Miss deliberately.** If you must provoke, do not land the shot. A reaction implies awake; no reaction is
   ambiguous, since a paused bot skips the sensor ticks that would notice a near-miss.

Customs is the right map: four known marksman positions, including the inaccessible smokestack — the case a
pure distance rule can never satisfy.

## Reporting back

Per raid, the useful summary is: map, run tag, what was toggled and when, anything odd seen in play. The log
carries the rest. `raidClock` matches the O-key readout exactly, so "it stuttered around 22 minutes left"
locates a line without arithmetic.

---

## PresentMon: GPU-side capture and the QPC join

Added 2026-07-28. This is the only way to measure GPU-side cost — `FrameTimingManager` is unavailable on this
build and NVIDIA Reflex frame reports were never needed once PresentMon worked. It is what established that
`TimeUpdate` spikes are not GPU waits.

**Binary.** Intel PresentMon 2.5.1, console build. Not on PATH, and not named `presentmon-cli`:

```
C:\Program Files\Intel\PresentMon\PresentMonConsoleApplication\PresentMon-2.5.1-x64.exe
```

`PresentMonSharedService` must be running for the vendor telemetry columns (GPU power, temperature, throttle
reasons, memory) to populate. It ships as an automatic service.

**Invocation.** Write the CSV next to the ndjson so the pair travels together, and name it after the run tag:

```
PresentMon-2.5.1-x64.exe --process_name EscapeFromTarkov.exe ^
  --output_file "F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver-logs\presentmon-<tag>.csv" ^
  --qpc_time --v2_metrics --stop_existing_session --restart_as_admin
```

- `--qpc_time` is not optional — it emits `CPUStartQPC`, which is what the join needs.
- `--restart_as_admin` handles the elevation ETW requires.
- Leave console stats on; it is how you confirm it attached rather than finding an empty CSV afterwards.
- **Start PresentMon before launching the game.** The loading phase holds the largest unexplained costs and
  you only get it if capture is already running.
- One continuous capture can span several raids; segment the ndjson on `raid`. The CSV is held under an
  **exclusive lock while capture runs**, so it cannot be read until PresentMon exits. That is expected.
- `--terminate_on_proc_exit` was left off: it is unverified whether it exits immediately when the target
  process does not exist yet.

**Columns worth keeping.** `CPUStartQPC`, `FrameTime`, `CPUBusy`, `CPUWait`, `GPULatency`, **`GPUBusy`**,
`GPUWait`, `DisplayLatency`, `Dropped`. `GPUBusy` is per-frame GPU execution and the reason the tool is here.

**The join.**

```
trueQPC_frameStart  =  <ndjson qpc>  -  period_ms * 10_000
```

`qpc` is stamped at frame *end* (sampling happens in `Update`); `CPUStartQPC` is frame *start*. Convert with
`qpcFrequency` from the header (10 MHz here). Match on nearest `CPUStartQPC`, then confirm by
`|FrameTime − period|`. Achieved 145 of 145 spike lines inside range with **no offset**, 107 matched at 8.39 ms
median alignment.

**If a log predates the QPC fix** its `qpc` is Mono's process-relative clock and will not overlap. Recover by
matching one unmistakable stall present in both files — a multi-second frame — to derive a constant offset,
then validate against a second landmark. Two landmarks agreed to 4.7 ms when this was needed.

## Protocol that worked: the two-arm control run

Reusable shape, from 2026-07-27/28. Serves a cold/warm comparison and a GC baseline in one session.

1. **Game closed.** Set `Run tag`. BepInEx clobbers `.cfg` edits made while running, and a new config entry
   does not exist until the plugin has run once with the new build — so default new options to the value the
   control arm needs.
2. Confirm the invariants explicitly, including any option neither party thought to name. **Reflex carried
   over unnoticed between sessions**; it happened to help, but only by luck.
3. Start PresentMon, then launch.
4. **Arm 1**, 10 min+ of raid time. In-raid collections arrive at roughly one per minute, so shorter arms
   yield single-digit event counts.
5. Menu, then **arm 2 on a different map, without closing the client.**

**Absolute millisecond figures do not transfer between arms 1 and 2** — different map. Arm 2 is a consistency
check, not a confirmation. This is how a heap-scaling claim survived one session and died the next.

## Validating an instrument before trusting it

Any new instrument that could perturb what it measures needs an A/B against a **known replicate spread**,
before its output is used. Established spreads for identical treatment:

| quantity | same-treatment spread |
|---|---|
| PMC bot/generate callback | **~950 ms** (16,759.1 vs 17,710.8 ms) |
| `controllerInitMs`, cold Streets | **1.3%** (13,804.7 vs 13,986.6 ms) |

An effect smaller than these establishes nothing. A claimed 1,046 ms GC saving was withdrawn on exactly this
basis. The pending off-thread heap sampler must clear it before any trace is read.

---

## Build 1 run sheet — 2026-07-28

One launch, **two Streets raids, no restart between them.** The knob A/B below runs inside raid 1.

### What is in the build

| change | what it fixes |
|---|---|
| `Sleeping` cross-raid leak | `animCulled` currently over-reports by a growing constant from raid 2 onward |
| `CurrentState()` menu gating | `state` reports `loading` at the post-raid menu, polluting loading-regime statistics |
| Component census | new instrument; enumerates what a bot carries alive vs dead. Registered via `TryEnable` |

### Before launch — four deploy checks

1. md5 of `bin/Release` and `plugins` **match each other**
2. `TimeDateStamp` **high bit set** — check the bit, not the value; the value moves with content and that is determinism working
3. **changed-file list** announced — a hash change alone cannot distinguish a comment from a behaviour change
4. **no build input newer than the deployed binary** — sources, `.csproj`, *and* `Assembly-CSharp.dll`. This is the only check that catches a stale binary

Then hash `Assembly-CSharp.dll` and record it. Hash it again after the launch.

### Settings

| | |
|---|---|
| Run tag | include the threshold, e.g. `build1-spike30` |
| `Spike event ms` | **30**, deliberately. A working GC slice turns one 110 ms pause into several ~30 ms ones, so the small pauses *are* the success signal — at 100 ms success and no-effect look identical. **Spike counts from this run do not join to 2026-07-27** |
| Both GC knobs | **0** for the first two windows |
| `Expand phase` | **blank.** See the inversion warning below — this is now a blocklist, and blank expands everything including `PostLateUpdate` |
| V-Sync | off |

> ### `Expand phase` inverted 2026-07-28 — read this before setting it
>
> It is now a **blocklist**: entries name the phases *not* to expand, and **blank expands everything**.
>
> **Setting it to `PostLateUpdate` now BLOCKS `PostLateUpdate`** — the exact opposite of what this run needs,
> and it would look like a successful run producing no render decomposition. Leave it **blank**.
>
> **An existing `.cfg` carries `PreLateUpdate` from the allowlist era.** Under the new meaning that blocks
> `PreLateUpdate` rather than selecting it, so the animation-pass breakdown disappears unless the value is
> cleared. **Clear it.**
>
> The old note below — "costs `PreLateUpdate`'s children for this run" — no longer applies: a blocklist
> expands every phase at once, so nothing is traded away.

**`Expand phase` must be set at the menu before the raid loads. Setting it in-raid does nothing.**
`ShouldExpand` is read only inside `PlayerLoopProfiler.Install()`, which runs at `Awake` and thereafter only
from the 5-second re-arm when markers are *absent*. Markers are dropped when the game rewrites the player loop
at raid load — so a change made at the menu takes effect on **the next raid**, and a change made mid-raid does
not take effect until the raid after. Combined with BepInEx clobbering `.cfg` edits made while the game runs,
the only safe procedure is **F12 at the menu, then load**. This is the config-hygiene failure that has already
cost two raids, in a new location.

**Why `PostLateUpdate`, and why it is worth losing `PreLateUpdate`'s children.** `render` is not a separate
measurement — BSG *defines* `gameUpdate` as `frame − render` ([GClass1357.cs:87](../../Src/Assembly-CSharp/Assembly-CSharp/GClass1357.cs)),
and its `RenderMeasurer` brackets `PostLateUpdate` from its first injected subsystem to its last. So **`render`
*is* the `PostLateUpdate` phase**, 6.2 ms median in raid and the largest single block in the frame, and it has
never been decomposed. Expanding it answers three questions at once:

- **How much is EFT's in-raid UI/canvas** rather than scene rendering — reachable in a way scene rendering is not.
- **How much is submission**, against a regression saying draw calls explain only ~1.4 ms of it.
- **Whether any of it is a blocking `Present()`.** `TimeUpdate` reading ~0 rules out a presentation wait *there*;
  it cannot rule one out inside `PostLateUpdate`, where Unity's `FinishFrameRendering` and
  `PlayerSendFramePostPresent` both live. This is the only measurement that closes it.

Losing `PreLateUpdate`'s children costs nothing here: fix 2's evidence is `playerLate`, a separate field, and
nothing on the checklist below reads them. This run already fails to join to the prior thirteen logs on three
code changes and a threshold change, so continuity is not an argument.

### Raid 1 — smoke test, then baseline, then reversal

**Read the first two windows before touching a knob.** If any of these fail, quit and report rather than
continuing — a knob run on a broken build is worse than no run.

| check | pass | what it cannot tell you |
|---|---|---|
| `cfg` block present, `gcSliceApplied` among the keys | present | — |
| raid-init segments sum to `controllerInitMs` | tiles | — |
| **three** `census` lines at the first AI death — `alive`, `aliveControl`, `dead0` — and a fourth `dead10` ~10 s later | all four present, `dropped: 0` on each | whether the enumeration actually *reached* everything — see the two rows below |
| `WeaponSoundPlayer` appears in the `alive` line's components | present | proves `GetComponentsInChildren` recursed into `PlayerBones.WeaponRoot`. A non-recursive `GetComponents` returns a plausible, shorter list and nothing else flags it |
| at least one `Rigidbody` row, with `enabled: null` | present | proves the `Component` widening took. A `Behaviour` census cannot see `Rigidbody`, `Collider` or `Cloth` at all, and `null` rather than `false` proves "no such property" did not collapse into "switched off" |
| `awake + asleep` agrees with `agents.live` | agrees | — |
| `animCulled == asleep` | agrees | **nothing about whether the leak fix works.** Raid 1 was always clean; this only shows the fix did not break the clean case |
| BepInEx log | no errors at load | — |

Then, from a fixed position: **knobs off → on → off**, at least two full windows per segment. The reversal is
what separates a real effect from having walked somewhere lighter.

### Raid 2 — same map, no restart

This is the only raid that can test the `Sleeping` fix. **Pass is `animCulled == asleep` in every window.**
Before the fix, raid 2 ran at `asleep + 15` — raid 1's final sleeping count, carried over and never drained.

Also gives a second knob data point at a larger heap.

### Reading it — both goals, or the result is unreadable

| goal | read | pass |
|---|---|---|
| **2 — in-raid hitches** | in-raid spike frames and `gcPhase` on each | fewer; `gcPhase` no longer `TimeUpdate` |
| **1 — frame rate** | `framePct` p50, same segment | unchanged |

A run that halves the hitches and costs 8 fps is a real result. Which side of that trade to take is a
judgement call, not a measurement — but *"did the hitches go away"* alone cannot see the price.

### Two things in this run's output that are the instrument, not the game — read before any number

`Expand phase` became the blocklist `Do not expand phases`, blank by default, so **all eight top-level phases
expand** where the previous fifteen logs expanded `PreLateUpdate` only. Verified against the live
`framesaver.ai.perf.cfg`: line 118 `Do not expand phases = ` blank, and the orphaned `Expand phase =
PreLateUpdate` at line 125 binds to nothing, so the old allowlist value cannot reach the new blocklist
semantics.

1. **Child-level series do not join to the previous fifteen logs** — different child name set. Top-level
   phases and `unaccounted` still join, since `accounted` sums only non-child slots.
2. **Top-level phases will read a few µs higher, and it looks like a regression.** Every child adds a
   Begin/End pair — roughly 140–200 extra QPC reads per frame — landing **inside** the top-level totals.
   `render` gains **3.5–5 µs, 0.05–0.08%**. Nothing against a 200–330 ms family, but real, reproducible, and
   in the direction of the effect being looked for. **Do not report it as a regression, and do not compare
   `render` across the expansion boundary at µs resolution.**

**This is not a new class of artifact — it is [the observer-effect note](FINDINGS.md#methodology-notes) in a
second instrument.** That entry was written about the off-thread GC sampler: *an instrument is not free of
observer effect, and the direction of its bias flatters the hypothesis.* The sampler's cost would have
lengthened the span it measured; the profiler's cost lands inside the phase totals it reports. Same principle,
different instrument, and the second instance is what makes it a rule rather than a story about one sampler.

**The generalisation that follows:** before trusting any instrument, ask **where its own cost is charged.**
If the answer is "inside the number it produces", the bias has a direction and the direction is usually
toward the effect being hunted.

### After the launch — one rebuild, free answer

Rebuild from unchanged sources. **If the hash matches build 1's, whatever the launch rewrote in
`Assembly-CSharp.dll` touched nothing Framesaver binds to.** Assembly references carry name, version,
culture, public-key token and member refs — not the reference's MVID — so an internal rewrite that leaves our
bound signatures intact emits byte-identical output. That closes an item previously written off as
unknowable, for one rebuild.

---

## The GC knob A/B — ready to run, no build required

`GC time slice ms` and `Drive incremental GC ms` are existing config entries that have **never run at
anything but 0**. They target the in-raid hitches directly: with the drain gone, every `TimeUpdate`-dominant
spike measured is a stop-the-world collection, and 73% of in-raid collections produce a frame over 100 ms.

**No build is needed.** Both entries already exist in `framesaver.ai.perf.cfg`, and `GcControl` reads them
**per frame** — verified in source, not assumed — so they can be changed mid-raid from the F12 manager. That
makes the off → on → off reversal from a fixed position possible inside a single raid, which is the only
comparison Streets tolerates.

### This is a trade between the two goals, not a free win

**BSG chose 3 ms deliberately** — it is set in `EscapeFromTarkov_Data/boot.config` as `gc-max-time-slice=3`,
not left at a Unity default. Raising it is overriding a shipped decision, so expect a cost.

The mechanism cuts both ways. Incremental marking gets a per-frame budget; if allocation outruns marking,
Boehm abandons incrementality and takes the full stop-the-world pause. So a larger slice should mean **fewer
forced full collections** — the in-raid hitches — while adding **up to that many milliseconds of GC work to
every frame**, which is frame rate. On a 12 ms frame a 10 ms slice would be catastrophic. **3 → 5 or 6 is the
plausible window**; do not start at 10.

### Read both numbers, or the result is unreadable

A run that halves the hitches and costs 8 fps is a real result, and which side of that trade is worth taking
is a judgement call, not a measurement. "Did the hitches go away" alone cannot see the price.

| goal | read | pass looks like |
|---|---|---|
| **2 — kill in-raid hitches** | in-raid spike frames, and `gcPhase` on each | fewer spikes; `gcPhase` no longer `TimeUpdate` |
| **1 — frame rate** | `framePct` p50, same segment | unchanged |

Segment on `cfg.gcTimeSliceMs` / `cfg.gcDriveMs`, which are on every sample line — the same way every other
A/B in [FINDINGS.md](FINDINGS.md) was resolved.

### Two traps specific to these knobs

- **`gcSliceApplied` is what confirms the write took**, not `gcRuntime`. The header's `gcRuntime` block is
  stamped **once at plugin load** and will keep reporting 3 ms however the knob is set. Reading it as evidence
  the knob did nothing would be wrong.
- **Both knobs self-disable by writing their own entry back to 0** on exception. So a knob you set reading 0
  mid-raid means a caught failure, not a mis-set — check the BepInEx log rather than re-setting it.

### If the runtime write is ignored

`boot.config`'s `gc-max-time-slice` sets the slice authoritatively at startup and is the fallback. It costs a
**relaunch per arm**, so it cannot give a within-raid reversal — use it only if `gcSliceApplied` shows the
runtime write is not taking, and treat the resulting cross-raid comparison with the usual suspicion.

### What a null means

The two knobs are companions: one gives the collector **longer** slices, the other **more** of them. If
neither moves spike size or count, that is a real result and not a failed experiment — it means the extra cost
is Boehm's **sweep**, which is unconditionally stop-the-world and scales with heap size rather than live set.
No scheduling knob can touch that, and the only remaining lever is allocation volume.
