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
draw call — a measured slope. ~~consistent with `graphicsMultiThreaded: false`~~ **withdrawn**: SPT's
launcher passes `-force-gfx-jobs native` on every raid, so the single-threading story is contested and the
slope stands without it.
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
| Plugin | `BepInEx\plugins\Framesaver.dll` (copied there only by `-p:Deploy=true`) |
| Config | `BepInEx\config\framesaver.ai.perf.cfg` — written on first launch, **not** the `F:\SPT\Base` path |
| Logs | `BepInEx\plugins\Framesaver-logs\framesaver-<timestamp>-<tag>.ndjson` |

One log file covers a whole game session, and every line carries `raid` and `map`, so a single launch can
cover several maps back to back. **Set `Run tag` to the stage** (`solo`, `ai-stack`, `ailimit`), not the map.

Confirm before the first raid: V-Sync **off**. `gameUpdate` excludes the frame-limiter sleep, but `frame`
does not, and a capped `frame` makes percentile comparisons meaningless.

### Before you raid: confirm the deployed binary is the approved one

```bash
python analysis/build-provenance.py "F:\SPT\SPT4.0.13\BepInEx\plugins\Framesaver.dll"
```

It prints the commit the binary was built from, read out of the assembly itself. **Compare it against the
commit named in the GO signal.** If they differ, the approval is stale and the raid would test something
nobody verified.

**Why this is your check and not the reviewer's.** On 2026-07-28 an approval went stale **five times**, and the
last one inside minutes: GO was signalled on `85db183d`, item 4 was built and deployed, and the deployed
binary became `8fe7f747` — a different build with a *different instrument in it*. Nobody broke a rule. Freeze
declarations are written before a deploy and read after one, so the writer and the reader are never looking at
the same moment. Opt-in deploy made deploying deliberate; it did not make it announced.

**A check that runs at the moment of use cannot go stale, and that is the only property that fixes this.**
The reviewer's verification is still worth having — it is what catches a binary missing a field it should
contain — but it is a claim about the past, and this one costs a raid when it is wrong.

Two minutes, and it is the only step here that protects every other number in the session.

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

**For a held-position run, two extra things, and both are things the log cannot record.**

- **Where you stood and what you aimed at**, in one sentence each. A protocol that cannot be repeated next
  month is a single measurement wearing a protocol's clothes, and nothing in the ndjson names the spot.
- **That the causal claim rests on the arm 1 ≈ arm 3 replication.** `drawCalls.max ÷ .avg` certifies that
  *a* view was held, not *which*. What rules out a scene change driving the draw calls instead of the view
  is that a spontaneous change does not revert exactly. **Whoever reads the result needs to know that is
  what carried it** — otherwise the claim gets restated later as though it had been measured directly, and
  nobody can tell which runs predate the instrument.
- **Whether `pos.look` was present, and whether it read plausibly.** The field ships from `52d398f` onward,
  so **the run in which it first appears is the boundary** any later reader needs in order to know which
  results rest on the replication and which on a measurement. Record it explicitly; the ndjson says the
  field exists, not that anyone trusted it yet.

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

1. md5 of **`plugins` and the artifact named in the freeze declaration** match each other

   > ~~md5 of `bin/Release` and `plugins` match each other.~~ **Retired 2026-07-28**, agreed by all three
   > agents. Since `524eb5d` made deploying opt-in (`-p:Deploy=true`), a verification build leaves
   > `bin/Release` holding a binary that was never deployed — so the two are **supposed** to diverge and
   > the check fires on the normal case. A check that fires on the normal case is a check nobody reads,
   > which is the same reason the `Assembly-CSharp` *mtime* clause was replaced by a hash.
   >
   > `bin/Release` is now out of the check entirely. Leave an abandoned build sitting there rather than
   > copying the approved binary over it: **a second location that looks authoritative is worse than an
   > obviously stale one.**

2. `TimeDateStamp` **high bit set** — check the bit, not the value; the value moves with content and that is determinism working
3. **The commit, read out of the binary** — `python analysis/build-provenance.py <path>`. The SDK stamps
   HEAD-at-build-time into `AssemblyInformationalVersion`, so provenance is *measured* rather than typed.
   Then `git diff <stamp>..HEAD -- '*.cs' '*.csproj'` must be **empty**.

   > **Empty is sufficient, not necessary.** A comment-only commit makes it non-empty while changing no
   > IL. When it is non-empty, read the diff — a comment-only hunk is verifiable from source, unlike the
   > byte-diff signature, which has at least three causes and does *not* mean "someone edited a comment".

4. **no build input newer than the deployed binary** — sources, `.csproj`, *and* `Assembly-CSharp.dll`. This is the only check that catches a stale binary

Then hash `Assembly-CSharp.dll` and record it. Hash it again after the launch.

**None of these establish that what is on disk now is what was approved.** They are statements about an
artifact and stay true indefinitely; freshness is a statement about a moment and expires on the next
build. That is what [the pre-raid provenance read](#before-you-raid-confirm-the-deployed-binary-is-the-approved-one)
is for, and it is the only check here that cannot go stale, because it runs at the moment of use.

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

---

## The held-position A/B — the procedure, for the person standing there

Every cross-window comparison in the corpus carries position as an unmeasured confound. **No window in
either 2026-07-28 raid was positionally stable**: distance travelled runs **76–244 m per window**, and the
quietest window on record still covers 76 m. Holding position does not happen by accident, and
`corr(distanceTravelled, p50) = −0.306` at n=10 means distance is a **comparability filter, not a
predictor** — it says which windows may be compared, not what the frame rate will be. The negative sign is
the kind of number that gets quoted backwards; it does not mean moving makes the game faster.

Two protocols. **A** makes any intervention A/B readable. **B** is the one still owed on goal 1, and it is
the only experiment on the list that converts an observational correlation into an intervention.

Neither needs a build. Both need you to stand still, which is the expensive part.

### Choosing the spot — once, and then write it down

Not a specific location, because the spot has to survive being described to a future session:

- **A long sightline down a street with buildings in it.** This is where 60 fps fails, so it is where the
  measurement is worth taking. A courtyard or an interior gives a clean run of numbers about a case nobody
  is complaining about.
- **Somewhere you can hold for ten minutes** — a corner, doorway or rooftop with one approach. Not a spawn,
  not a hot extract.
- **Under two minutes from spawn**, so the raid timer is never the reason an arm was cut short.
- **A fixed aim point**: a sign, an antenna, a specific window — something you can re-acquire *exactly*
  after looking away. Protocol B depends on it and so does arm 3 of any later session.

Write the spot and the aim point into the run notes in one sentence each. A protocol that cannot be
repeated next month is a single measurement wearing a protocol's clothes.

### Protocol A — one position, one view, one knob

Sequence, for a knob with a baseline and a test value:

| step | what | duration |
|---|---|---|
| 1 | reach the spot, settle on the aim point, **stop moving** | — |
| 2 | **arm 1**, knob at baseline | **5 min** |
| 3 | open F12, change the knob, close it — **without moving the feet** | ~15 s |
| 4 | **arm 2**, knob at test value | **5 min** |
| 5 | revert the knob the same way | ~15 s |
| 6 | **arm 3**, back at baseline | **5 min** |

**Five minutes here where Protocol B has four, and the extra minute buys back the discard.** Windows are
60 s, so you **discard the first window of each arm** — and that discard is not a duplicate of the
containment arithmetic, it is how you *identify* the window containment excludes. `cfg` is stamped when
the line is written, so the straddling window is labelled with the **new** arm and nothing else
distinguishes it. Positional rule, because no field marks it.

Four-minute arms then leave **two** usable windows in the worst case — the near-aligned case, where there
is barely a straddler and the discard removes a nearly clean window — and two is what this document
already declares insufficient twenty lines below. **Five-minute arms guarantee three after the discard.**

Arm 1 has no preceding knob change and does not strictly need the extra minute. It gets it anyway:
**a procedure with per-arm durations is a procedure someone executes wrong at minute eleven.**

So Protocol A is **fifteen minutes** plus the two changes; Protocol B stays at twelve. Two reasons for the
discard, both silent if ignored:

- **A knob changed mid-window lands in a window that reports the new value on a line whose frames are
  mostly from the old arm.** `cfg` is stamped when the line is written. The contaminated window is
  labelled as the *new* arm, which is the worst possible place for it.
- **The F12 overlay is a large IMGUI draw**, so the window you open it in has extra render and UI cost that
  belongs to neither arm.

Arm 3 is not optional. It is the only thing that separates a knob effect from a drift over a quarter of an hour —
heat, a bot wave arriving, the collector's heap growing. If arm 3 does not return to arm 1, **the run
measured time, not the knob**, whatever arm 2 showed.

### Protocol B — one position, two views, no knob at all

The render decomposition rests on `render = 5.266 + 0.000467 × drawCalls` fitted across 38 windows in which
**both the position and the view were changing**. That is an observational slope and the caveat travels
with it. This replaces it with an intervention, at the same spot, in twelve minutes:

| step | what | duration |
|---|---|---|
| 1 | stand on the spot, aim at the **long sightline** | **4 min** |
| 2 | **turn on the spot** to face a near wall — feet do not move | **4 min** |
| 3 | turn back to the aim point | **4 min** |

Nothing is configured, nothing is toggled. The only variable is which way you are looking.

#### Registered prediction — written before Protocol B has ever run

**Registered as a slope, not a difference.** The difference form was the first version and it had a hole
Delta found: nothing in it verified that the two arms *differed in draw calls at all*. A near wall with
geometry behind it, or a sightline occluded by something you did not clock, passes every held-position
criterion, lands both arms at similar `drawCalls.avg`, and produces Δ`render` ≈ 0 — **which reads as the
outcome that retires the whole line of enquiry.** A failed manipulation and a real null were
indistinguishable, and the failure mode manufactured the most consequential reading on the table.

> **Δ`render` p50 ÷ Δ`drawCalls.avg` ≈ 0.000467 ms per call**, and `gameUpdate` unchanged.

Dividing by the swing you actually got, rather than the one you assumed, is what closes it: a weak
manipulation becomes a wide error bar instead of a null, and a *failed* manipulation announces itself.

**Manipulation check — a signal-to-noise ratio the run measures on itself, not an absolute number.**

The first version of this set an absolute floor of Δ`drawCalls.avg` ≥ 2,000. **That number came from the
wrong population.** Delta measured natural window-to-window movement in `drawCalls.avg` *while roaming* —
median 570 adjacent, **p90 1,583**, and at the two-window separation that step 1 and step 3 sit at, **median
962, p90 2,113, max 2,976**. A 2,000 "manipulation" is below the p90 of roaming noise.

Those are roaming windows, so they bound held-position drift from above rather than estimating it. **And
there is no better estimate anywhere in the corpus, because nobody has ever held position** — conditioning
on view stability leaves three adjacent pairs, one of which shows Δ = 2,284 with both windows view-stable,
which is a view *change between* windows rather than drift within one. n=3, confounded. No number.

So the floor is measured in the run itself — and **the arm 1 ↔ arm 3 comparison is the gate**, not the
within-arm one:

> Arm 1 and arm 3 are **the same position and the same view**, separated by an entire arm. So their Δ is a
> same-view measurement at a *longer* separation than any within-arm pair. **Require the between-arm Δ to
> be at least 2× the arm 1 ↔ arm 3 Δ.**

| | |
|---|---|
| between-arm Δ ≥ **2×** the arm 1 ↔ arm 3 Δ | the run is readable |
| between-arm Δ < that | **void, not negative.** Do not compute the ratio, do not report a null — find a wall with less behind it, or a longer sightline, and run it again |

**Why not the within-arm Δ, which was the first version of this.** Within-arm Δ is measured between
*adjacent* windows while the comparison it gates spans a whole arm. If drift grows with separation at all,
the within-arm figure understates the noise in the comparison, and **the bias runs toward passing a run
that should have been voided** — the direction this document spends most of its length closing off. Arm 1 ↔
arm 3 sits at a *longer* separation than the between-arm comparison, so it is conservative-or-equal under
any noise process that does not *decrease* with separation. That covers both plausible cases: independent
noise is flat, slow drift increases. **The gate needs no model of how drift scales**, which is the property
that matters, since the only scaling data available is from the wrong population.

Being conservative in a known direction is what buys the drop from 3× to 2×. A 3× gate against an inflated
floor is where a genuinely good run gets thrown away.

> **The roaming drift-vs-separation numbers must not be used to calibrate this, in either direction.**
> Measured across the corpus, median Δ`drawCalls.avg` by window separation runs **570 / 969 / 1,169 /
> 1,077 / 796 / 782** at gaps 1–6. It rises to gap 3 and then **falls** — because a roaming player returns
> to similar ground and the long-gap sample is only long raids. That shape is a property of how someone
> walks around Streets, which is exactly what holding position removes. It bounds nothing about a held run
> and the non-monotonicity means it cannot even be extrapolated.

**Three windows per arm rather than two, and it is no longer optional.** The gate now needs arm 1 and arm 3
each to have a stable mean, and Δ`render` still has to be read against a within-arm spread. Two windows per
arm gives one Δ per arm — a noise estimate with no spread of its own.

**Which makes the arms four minutes, not three — the window boundary is not aligned to the arm boundary.**
`ResetWindow()` fires at the raid transition and then runs on a fixed 60 s cadence; nothing re-aligns it to
when you start standing still. So an arm beginning at an arbitrary offset into a window yields:

| arm length | fully-contained windows, worst case | best case |
|---|---|---|
| 2 min | **1** | 2 |
| 3 min | **2** | 3 |
| **4 min** | **3** | 4 |

Three minutes was written as "three windows per arm" and guarantees only two. **Four minutes guarantees
three**, which is what the gate and the spread both assume, so **Protocol B is twelve minutes**.

**Protocol A needs five-minute arms rather than four**, because it discards the first window of each arm to
remove the one the knob change straddles — and four minutes minus that discard is two again. Fifteen
minutes plus the changes. The reasoning is with its own step table above.

**The straddling windows are not a loss that needs managing — they are self-excluding.** A window spanning
the turn contains *both* views, so its `drawCalls.max ÷ .avg` blows past 1.15 and the view-held criterion
drops it. **That is also the only thing separating the arms**, since Protocol B changes no config and
nothing in the log marks where one arm ends.

**Note the double duty before it bites:** arm 1 ↔ arm 3 now gates the run *and* serves as the replication
check. That is safe — a run that drifted badly fails both, and both answers are "run it again" — but the
two failures have different causes, drift versus the runner not re-acquiring the aim point, **and nothing
in the log separates them.** Do not read a void as a null.

Then Δ`render` is read against the same within-arm spread rather than against zero. **If the arms overlap
inside their own scatter, the answer is "this swing was too small to resolve"** — a third thing, distinct
from both a confirmed slope and a null.

| outcome — slope in ms per call | reading |
|---|---|
| **≈ 0.0005**, within the arms' own scatter | the observational slope is causal. "79% of Streets render is a constant draw calls do not reach" stands, and the reachable ceiling really is ~1.4 ms |
| **0.0005 – 0.001** | real and larger than fitted; the observational fit was diluted by windows where position moved against the view. The lever is bigger than we have been saying, and the ~1.4 ms figure is an underestimate |
| **> 0.001** | draw calls proxy something well beyond submission — culling, shadow casters, overdraw. The decomposition needs redoing before the number is quoted again |
| **≈ 0** with Δ`drawCalls` above the floor | the observational slope was position and content, not submission. The draw-call lever does not exist and `render` is fixed cost |
| **`gameUpdate` moves too** | the view is driving more than rendering — visibility or LOD work on the CPU side — and neither the slope nor the split can be read until that is separated |

**The ≈ 0 row is a good result and should be reported as one.** It retires the draw-call line of enquiry
with a measurement instead of leaving it as a caveat on a regression, and it costs twelve minutes. The
temptation afterwards will be to describe it as a failed experiment; it is the opposite — **provided the
manipulation check passed**, which is the whole reason that check is now a gate rather than a footnote.

**A number this section used to carry, corrected.** It said draw calls span *"1,141–4,648 across the
corpus"*. The lower bound is right and the upper is not: in-raid `drawCalls.avg` reaches **5,880**, and
five windows exceed 4,648. 4,648 was the top of the **38-window subset the regression was fitted on**,
quoted as though it described the corpus — the same shape of error as reading a best-window figure as a
baseline, [which this project has already made once](../analysis/CORPUS.md). Under a slope prediction the
span does not enter the arithmetic at all, which is a second reason to prefer it: **the corpus span is an
upper bound on what one position can swing, not an expectation, because it aggregates positions.**

### Pass criteria — read from the log afterwards, never judged in the moment

| check | field | pass |
|---|---|---|
| **position held** | `pos` — largest of the three axis spans | **≤ 1 m** |
| **no pacing** | `pos.dist` | **≤ 5 m per window** |
| **view held** | `gpu.render.drawCalls.max ÷ .avg` | **≤ 1.15** |
| **arms comparable** | `bots.awake` | within **±2** across arms |
| **arm labelled right** | `cfg.*` | first window after every change discarded |
| **manipulation worked** *(B only)* | Δ`gpu.render.drawCalls.avg` between arms | **≥ 2,000**, else the run is **void, not negative** |
| **no drift across the run** | arm 3 vs arm 1, same measure as the result | agree within the arms' own scatter |

**Arm 3 is a replication, not a formality, and it is a stronger control than `bots.awake`.** Both protocols
already end by returning to the starting condition, so the comparison is free — and if arm 3 does not
reproduce arm 1, something drifted over the whole run whatever the bot count says. Heat, a wave
arriving, the heap growing. **A result that survives arm 1 vs arm 2 but fails arm 1 vs arm 3 measured
time, not the variable**, and no other criterion here can see that.

**In Protocol B it does more than that — it is what makes the protocol an intervention at all.** The
manipulation check certifies that draw calls *changed*; it cannot certify that the **view** changed them. A
fire starting, a vehicle moving, bots piling into frame — any of those gives a large Δ`drawCalls`, passes
the check, and yields a perfectly well-formed ratio, at which point Protocol B has quietly degraded back
into the observation it exists to escape, with nothing in the log recording the degradation.

**A spontaneous scene change does not revert exactly.** So arm 1 ≈ arm 3 with arm 2 apart is strong
evidence the view was the driver, because the alternative requires a confound to appear and disappear on
the same schedule as your feet not moving. That is the whole causal claim, and it rests on the replication
rather than on the manipulation check.

**The bounding box is the criterion, not `dist`.** `dist` sums a per-frame distance over ~3,000 frames a
window, so its floor grows with frame count and it will read non-zero standing perfectly still; the box
does not accumulate. `dist` is kept because it catches the one thing a box misses — pacing a small circle,
which returns a tidy box and a large path.

**These thresholds are bounds, not measurements.** Nobody has ever stood still with this instrument
running, so there is no measured noise floor and the first held window *is* the calibration: record what it
actually read and replace these numbers with those.

For `dist` and the box the placement is not delicate — the quietest roaming window on record is 76 m
against a 5 m bound, more than an order of magnitude of daylight. **For `drawCalls` it is delicate**, which
is why that one is expressed as a ratio the run measures on itself rather than as a number: the bound on
natural drift and the expected manipulation are the same order of magnitude. Record the within-arm
`drawCalls.avg` Δ from the first held run — **it is the first honest estimate of held drift anyone will
have**, and everything downstream of it currently rests on a bound taken from roaming windows.

**`bots.awake` is the combat check.** Standing still on Streets draws fire, and a bot shooting at you is a
different CPU workload from a bot patrolling. Consistent is fine; *different between arms* is not.

**`max ÷ avg` keys on a single frame, so bias it toward false failures deliberately.** One explosion or a
HUD element popping can fail an otherwise-clean arm. For a *validity* check that is the right direction —
a false fail costs a re-run, a false pass costs a wrong conclusion — so the threshold stays where it is. If
an arm fails it and looks clean on everything else, check whether `max` was a single frame before
discarding it.

### What the log cannot check, and what stands in for it

`pos` records position and never look direction — `SamplePosition` reads `player.Position` and nothing
else. **So no field verifies that you held the aim point**, which is precisely what Protocol B turns on.

`drawCalls.max ÷ .avg` is the stand-in, and it works: across 76 in-raid windows the ratio runs 1.01 to
3.21, median 1.63, with only 5 windows at or below 1.15. A fixed view genuinely does drive it to ~1.0, and
roaming genuinely does not — so ≤ 1.15 certifies a held view without certifying *which* view.

**Shipped, and deployed for this run** — `a38db8cc` / `52d398f`, verified on disk rather than from a
message. `pos.look = {samples, yaw:{range,swept}, pitch:{range,swept}}`, or `"look":null`.

**It does not yet carry the held-view condition, and tonight is not the run that lets it.** The field has
never produced a line, so its first reading validates the *instrument*, not the protocol. Tonight the
causal claim still rests on the arm 1 ≈ arm 3 replication; `look` runs alongside as a cross-check whose own
first output is under test.

> **Protocol B is its own positive control for the field, at no cost.** Step 2 is a deliberate large yaw
> change between two deliberately held views — so arms 1 and 3 must show **small `swept`** and the
> transitions **large**. That pattern is the field working. A large `swept` inside a held arm means either
> the field is wrong or the runner moved, and the other criteria say which.
>
> **If it reads that way, later runs can rest on `look` directly and drop the replication argument to a
> secondary check.** If it does not, nothing about tonight's result changes — the claim never depended on
> it. This is the cheapest possible way to bring a new field into service: put it in a run whose
> manipulation already exercises it, and let the run decide.

#### `drawCalls` stays the arm-boundary marker tonight, and `look` does not get that job

Protocol B changes no config, so **something has to delimit the arms**, and the temptation with `look`
newly live is to promote it — it is the more direct measurement of the thing that actually changes.

**Do not, and the reason is not caution.** If `look` both defines the arms *and* is the field under test,
there is no independent signal left to catch a defect in it: a mis-segmentation would silently regroup
every window before any other criterion is computed, and each arm would then look internally consistent
because `look` drew the boundaries. **That is the same circularity as a manipulation check doubling as the
arm label** — the instrument under test must not define the populations it is judged on.

`drawCalls.max ÷ .avg` keeps the job for a positive reason as well: a straddling window reads high because
it genuinely contains two views, which is the same physical fact Protocol B manipulates. It is not a proxy
standing in for `look`; it is a second consequence of the same cause.

> **So the two are compared, and the comparison is the validation.** The windows `drawCalls` flags as
> straddling should be the windows `look` flags as high-`swept`. **Agreement promotes `look` for future
> runs. Disagreement is a finding either way** — and the held-position criteria say which instrument to
> distrust, because a runner who drifted fails `pos`, while a runner who held fails nothing else.

> **The one thing to know about it before reading a `look` field**, because it nearly shipped inverted:
> **raw yaw min/max reports a perfectly held view as a full 360° sweep.** Yaw wraps, so a view held near
> the wrap point samples at 359.9 and 0.1 and a naive range spans the circle — healthy-looking, and the
> exact opposite of the truth on the single reading the field exists to certify. The shipped version
> accumulates an unwrapped angle relative to each window's first sample instead, with `swept` as the
> angular analogue of `dist`.

**Its priority changed once the drift was measured, and the argument is now quantitative rather than
convenience.** The expected manipulation is ~3,300–4,700 draw calls. The bound on natural window-to-window
drift is ~3,000. **Those are the same order of magnitude** — so the log cannot presently distinguish "the
view moved the draw calls" from "something in the scene did while the view was held", and the entire causal
claim rests on the arm 1 ≈ arm 3 replication argument above. Yaw and pitch would make it a direct reading.
Worth raising in the queue on that basis; still behind the boundary latch.

### If there is only time for one thing

**Protocol B.** Protocol A makes future comparisons valid; Protocol B answers an open question about goal 1
today, needs no config changes, and takes twelve minutes. It is also the cheaper failure: a botched
Protocol A wastes an intervention, while a botched Protocol B wastes twelve minutes of standing still.

---

## Brain-slicing A/B — Streets, held position. Run sheet, 2026-07-28

The first raid that varies a **Framesaver AI patch** rather than telemetry design or a GC knob. Across all
18 logs, nine of ten AI knobs have never moved and `brainUpdatePeriod` is **0 in every one of them**. The
config comment on it reads *"try 0.05-0.1 and measure"*; nobody has. So this raid tests the lever the mod
already ships, switched off.

**What it targets.** Slicing throttles `AICoreControllerClass.Update`, which drives every bot brain, which
is the path to the recursive cover search — up to 500 point checks and 100 raycasts, synchronously, on the
main thread. Brain updates live inside `ScriptRunBehaviourUpdate`: **3.80 ms, 20.7% of the median Streets
frame**, and the largest block on the update side still unattributed.

### Before you launch — two things, and the first one is the whole raid

**1. `Defer to other AI mods` must be `false`.** Already set in `framesaver.ai.perf.cfg`; this records why,
because re-enabling it silently voids the run.

`DrakiaXYZ-BigBrain.dll` is installed — SAIN depends on it — and `ModCompat.SuppressSlicing` suppresses
slicing whenever BigBrain or ORBIT is present *and* the defer setting is on. With the shipped default,
`Brain update period = 0.1` **changes nothing**, and `cfg.brainPeriod` still reports `0.1`, because it
reports the value requested rather than the value in force.

> **Arm 2 would be arm 1 wearing arm 2's label**, and the natural reading of the resulting null is *"slicing
> does not help"* — the exact conclusion the raid exists to draw, drawn from an arm that never ran.

The override is in the config file rather than a protocol step because `ModCompat` latches its detection on
the **first bot-brain frame of the raid**, long before you can press a key. Set before launch, BepInEx logs
`no compatibility guards will be applied`, and **`Player.log` carries the proof the arm was real.** That log
is currently the *only* record of it — see "what this run cannot tell you" below.

**2. Confirm the protocol parsed.** The line carries `protocol.steps`. The file defines **7** sections. If
the log says 7, the parse worked on the file in use. If `protocol` reads `null`, the ini is not installed
and every arm is arm 1.

`Run tag` is **`brainslice`**, so the log self-identifies. The `endToLatch` validation rides along and needs
no tag of its own.

### The arms

`BepInEx\config\framesaver.protocol.ini`, three steps, advanced with **Ctrl+Alt+PageDown**:

`BepInEx\config\framesaver.protocol.ini`, **seven steps**, advanced with **Ctrl+Alt+PageDown**:

| step | arm | `Brain update period` | |
|---|---|---|---|
| 1–6 | **B1 / B2 / B1 / B2 / B1 / B2** | `0` / `0.1`, alternating | held position, **~3 minutes each** |
| 7 | **KABAN** | `0.1` | leave position, go fight — see below |

Held position, one view, per [Protocol A](#protocol-a--one-position-one-view-one-knob).

**Why six alternating blocks and not a single ABA reversal.** Gamma measured spike counts rising **3.9×**
from the first half of a raid to the second **at constant config**, rho **+0.71** against window order.
Under a drift that size the late control sits above the early one whatever the knob does, and the treatment
arm in the middle lands between them either way — **ABA can detect that drift and cannot separate it from
the effect.** Interleaving gives three replications of the contrast, each spanning four minutes rather than
one spanning fifteen, and balances exposure 50/50 instead of ABA's 2:1 control-heavy split.

**Three minutes a block.** `Window seconds` is 60 and a keypress both flushes and resets the timer
(`Telemetry.cs:405–410` — `Flush(false)` then `_nextWrite = now + 60`), so a block that is a whole multiple
of 60 s spends nothing on partials: the press closes a *full* window rather than cutting one short. Three
minutes is three full windows a block — **18 usable windows against the ABA design's 15**, for three more
minutes of standing still. At 2.5 the press would cut a third window short and ~20% of held time would land
in partials that have to be excluded.

> **This file now contains two different window-arithmetic tables. They do not contradict each other.**
> [Protocol B's table](#the-held-position-ab--the-procedure-for-the-person-standing-there) says three
> minutes guarantees only **two** windows, and it is right *for Protocol B* — that protocol has no
> keypress, so nothing re-aligns the 60 s cadence to when the runner starts standing still and an arm
> begins at an arbitrary offset. **A protocol keypress re-aligns it by construction**, which is why the
> same three minutes buys three windows here and two there. If you ever run these blocks without the
> protocol, Protocol B's table is the one that applies.

~~Two minutes, because that is exactly two whole windows.~~ **Two is aligned but 3 is aligned too**, and
picking the shorter one optimised total held time, which is not the scarce resource here — usable windows
are. Precision is not critical either way; block identity comes from `protocol.step`, not from the clock.

**Arm labels repeat on purpose.** `arm` names the *condition*, so pooling the three B1 blocks is what the
label already does; `protocol.step` names the *block*.

> **The control blocks gate everything, and the check keys on `step`.** If the three B1 blocks disagree
> materially the raid is unreadable on every metric, and no arithmetic downstream fixes it. **Group by
> `protocol.step`, not `protocol.arm`** — the natural thing to write is "group by arm", and that pools the
> three control blocks into one, destroying exactly the signal the alternation was added to produce.

### 0.1 is the top of the useful range, not a midpoint — and the floor is what actually binds

Measured, from the 163 in-raid Streets sample lines in the corpus: **23 live agents** at the median,
**17.1 ms** median frame.

`perFrame = ceil(count ÷ (period ÷ delta))`, then clamped up to `Minimum brains per frame` (**4**). At the
median that is `ceil(23 ÷ 5.85) = 4` — **exactly the floor**. The floor binds for any period above ~0.098,
so `0.1`, `0.2` and `0.5` all tick the same four brains per frame.

Two consequences, and they point in opposite directions:

- **A null at 0.1 kills the entire 0.098–0.5 range in one arm**, not just the value tested. That is a
  stronger result than picking a midpoint would have bought.
- **A positive result does not make 0.1 the ship value.** What the arm actually varies is *slicing engaged
  at a floor of 4* versus *not engaged*. The shippable question that follows is **what floor**, not what
  period, and it needs its own raid.

**`Minimum brains per frame` stays at 4.** Dropping it would buy a "purer" 0.1 and is the wrong trade: 4 of
23 is already an 83% cut in brain work, the AI-quality risk is the binding constraint in this arm rather
than the frame-time headroom, and 4 is the shipped default — so the arm tests a configuration someone could
actually run.

### Sophia's read is an instrument here, not colour commentary

The numbers measure frame time and hitches. They **cannot see whether bots still fight competently**, and
slicing is throttling SAIN's custom brain layers — which is precisely the interaction `ModCompat` calls
*"the kind that produces 'the AI feels wrong' reports with no obvious cause."* That guard has never been
measured; it is a prediction, and this raid is the first test of it.

**The held-position arms cannot answer it.** Standing still watching a street is the right way to measure
frame time and the wrong way to judge whether bots fight well — nothing is fighting. So the AI read moves
to its own phase, below, where it is actually answerable.

A frame-time win with a "they stopped flanking" note is not a win. The release criteria do not mention AI
quality; the people who install this will.

### Arm 4 — fight Kaban's crew at LexOs, slicing on. Last, and not negotiable

**Order.** A firefight would wreck the held-position measurement, so B1–B3 come first and this comes after
them. It needs the fourth protocol step — after three presses `Advance()` refuses and nothing changes.

This is two instruments at once, and the first one is the reason it is worth a phase of its own.

**1. The AI-quality arm, with a real baseline behind it.** Sophia stress-tests here already: LexOs is the
highest concentration of bots in one area on Streets, and she has run this fight **unsliced, repeatedly,
looking for failure, and found none — no deaths, no issues with the bots.** That converts the subjective
read from a vibe into a comparison against an established reference. It is also aimed squarely at
`ModCompat`'s prediction: the guard exists because we thought slicing would feel wrong under BigBrain, and
Kaban's crew at LexOs is where wrong would show.

**Pass criteria are her own named failure modes**, because she is the one who knows what this fight does
when it is working:

| | reference (unsliced, repeated) | this run |
|---|---|---|
| deaths | none | |
| did anything land a **grenade** | it can, and does | |
| did the **dealership launchers** engage | they can, and do | |
| did anyone **push** her | yes | |
| anything that felt *wrong* | nothing, across many runs | |

She has practical invincibility there **except** to grenades and the launchers — so those two are not
hazards to note in passing, they are the sharpest available signal that the crew is still playing properly.
**A noticeably passive crew is the finding.** So is a death, in the other direction.

**2. The best-case frame-time arm.** Highest awake-bot count in one place on the map, so if slicing helps
anywhere it helps most here. **Her observed 5–10 fps degrade in that area is the number to beat.** A null
in the held arms plus a win here is a real finding; a null in both is a much stronger negative than the
held arms could give alone.

**What arm 4 is not.** It is **not comparable to B1/B2/B3 on frame time** — different position, with a
firefight in it, and absolute ms do not transfer across either. Its control is historical: her own prior
unsliced runs of the same fight. That control **cannot be replicated in-raid**, because killing Kaban's
crew once leaves no second fight to reverse into. Treat the 5–10 fps figure as remembered rather than
logged, and say so in whatever it supports.

### What this run cannot tell you, stated before it produces numbers

- **Whether slicing engaged is not in the ndjson.** `AICoreControllerUpdatePatch.LastBrainsTicked` exists
  and is documented as *"confirms slicing is doing what it claims"* — and is **not emitted**. Verified
  against the deployed binary with `analysis/probe-symbols.py`: `brainsTicked` is in neither string heap.
  Nor is the effective `SuppressSlicing` state. So engagement is **inferred from `Player.log` plus a frame
  time that moved**, which is weaker than it should be, and the floor arithmetic above stays arithmetic
  rather than becoming a measurement.
- **This measures slicing *under SAIN*, not slicing under vanilla AI.** SAIN replaces much of the decision
  logic the cover-search hotspot sits in. A frame-time win is real and is what a real user would get, but it
  **cannot be attributed to the cover search** without a SAIN-absent raid to compare against. Do not write
  the mechanism into FINDINGS off this run alone.

### Riding along at no cost

The `endToLatch` validation and its `endToStart` control need this raid and no build. **Do not drop
`endToStart` yet.**

### Two fields land in this build, and both have a reading trap

Gamma's `287f35b` adds `agents.slicing`, `agents.tickedSum` and `agents.liveSum`. They close the "did
slicing engage" gap above — `slicing` is the same expression the patch branches on, and
`tickedSum == liveSum` on an arm-2 window means slicing did not engage, measured over every frame of the
window rather than the last one. Both traps below are about how to *read* them; neither is a data defect.

**1. Divide by `n`, not by `frames`.** Both are on the line. `n` is `_frame.Count`, accumulated behind the
same `if (m != null)` in the same method as the sums, so it is the accumulation denominator **by
construction**. `frames` is `_periodSamples`, incremented unconditionally one line later, so it can exceed
the count the sums were taken under.

> ~~The safe ratio is `tickedSum ÷ liveSum` because no matching frame count is emitted.~~
> **Corrected — `n` is emitted and is the matching count.** The hazard is real and has no instances:
> `n == frames` on **284 of 284** sample lines across all 18 logs, every state including loading. So
> `tickedSum ÷ frames` has never actually been wrong; it is simply the one that has no guarantee.

`tickedSum ÷ liveSum` remains the more useful ratio — fraction of the roster ticked per frame, which is
what predicts frame time — and `tickedSum == liveSum` remains the exact did-slicing-engage check, since
both sums share the one gate.

**2. On the `flushedByProtocol: true` line, the labels and the measurements describe different arms.**
`ProtocolRunner.Advance()` applies the new step's config values and *then* returns true to trigger the
flush, so that line carries:

| field | which arm |
|---|---|
| `cfg.brainPeriod`, `agents.slicing`, `protocol.arm` | the arm **about to start** |
| `agents.tickedSum`, `agents.liveSum`, every timing figure | the arm **just ended** |

That line is already marked partial and excluded from averages — but the stated reason for excluding it is
that it is *short*, and this is a second and worse reason. `slicing` is exactly the field a reader will
trust as ground truth, and on that one line it is ground truth about the next arm.

**Both are properties of the boundary line only.** Every whole window inside an arm is self-consistent.

---

## The transit marathon — and the one thing that does not travel with it

Ground Zero → Streets → Interchange → Customs → Factory → Woods → Lighthouse → Reserve, with a Lighthouse
backtrack to reach Shoreline. **Six of those maps have never been launched.** Alpha verified the
segmentation holds: `BaseLocalGame.method_15` sets `GameStatus.Stopped` on `ExitStatus.Transit`, so each
leg increments `_raid` and re-resolves `_map`, and `ResetForRaid` is in the deployed build.

Play normally. **Do not hold position** — that is a different run.

### Two things to do before launching it, and the second one is not obvious

**1. Remove `BepInEx\config\framesaver.protocol.ini`.** Separate runs, so `protocol` reads `null` and the
provenance is unambiguous. An armed protocol that nobody presses is inert, but a `null` reading is a
*statement* that no arm was applied, and this run wants that statement.

**2. Confirm `Brain update period = 0` in `framesaver.ai.perf.cfg`. Removing the ini does not do this.**

> **A protocol step rewrites the config file.** `ProtocolRunner` assigns through `ConfigEntryBase.BoxedValue`,
> which is BepInEx's ordinary setter — the same path `GcControl` uses to self-disable its knobs at
> `GcControl.cs:94` and `:143`. With `SaveOnConfigSet` at its default the new value is written to disk.
> **So whatever the last arm set is still set at the next launch.** End the slicing raid on arm 4 and the
> marathon starts with slicing quietly on, across six maps nobody has ever measured, with the ini deleted
> and `protocol` reporting `null` — every signal saying "no arm applied" while an arm is applied.

That is the cross-raid leak shape `ResetForRaid` exists to close, one level up: it rewinds the protocol's
*position* and cannot rewind the config the protocol wrote.

**It contaminates a re-run of the slicing raid too, not only the marathon.** Block 1 of a second run
inherits `0.1` from the first run's last arm until step 1 applies it away — so if the runner spawns in and
waits before the first keypress, **those windows are B2 wearing no label at all.** Every `[B1]` block
stating its own period is what saves this; that choice is load-bearing for a second reason now.

> **Hard stop, not a note: `agents.slicing` must read `false` on the first window.** If it reads `true`
> before the first keypress, a previous run's state is still applied. Reset the config and restart the
> raid — do not press through it, because the arm you are standing in has no label and cannot be given one
> afterwards.

### The primary metric — read this before computing anything

**Two thresholds, and they are not interchangeable.** Alpha registered `period >= 30 ms` as primary
(`registrations.json`, `85d05a1`) on a power argument; Gamma then measured it and sent a retraction. The
retraction is the one to act on, and the reason is not power:

| threshold | dispersion vs Poisson | drift within a raid at constant config | verdict |
|---|---|---|---|
| `period >= 30 ms` | **454×** overdispersed | **3.9×** across a raid, rho **+0.71** | **descriptive only** |
| `period >= 100 ms` | 1.2× — near-Poisson | — | **primary**, and underpowered |

> **Do not run a conditional binomial on `>= 30 ms`.** It assumes Poisson and the metric is not a
> rare-event count — it tracks the frame-time distribution, so it drifts hard within a raid. That test
> yields a confident number which is mostly drift, which is worse than no number.

**So: `>= 100 ms` is primary**, and its detectable effect belongs in the sheet *before* the raid rather
than as an excuse after it. At the measured ~2.2 events per window, exact conditional binomial, two-sided,
80% power:

| design | held | windows/condition | detectable ratio |
|---|---|---|---|
| old ABA, 5 min × 3 | 15 m | 10 control vs 5 treatment | **~4.7×** |
| interleaved 2 min × 6 | 12 m | 6 | **~5.7×** — *worse than the ABA it replaced* |
| **interleaved 3 min × 6 — installed** | 18 m | 9 | **~3.5×** |
| interleaved 4 min × 6 | 24 m | 12 | ~2.9× |

**The row that decides the block length is the second one.** Interleaving buys drift control and pays for
it in exposure; at two minutes the net was a design more valid and *less able to see anything* than the one
it replaced. Three minutes gets both, for six more minutes of standing still.

> **Three people have derived these and they disagree by up to ~1.4×** — Alpha 3.74× where this table says
> 3.5×, Gamma 4.5× for the ABA row. Most of the gap is that the **ABA design is not balanced** (control is
> B1+B3, twice the treatment exposure) and an unbalanced conditional test has null `p₀ = W₁/(W₁+W₂)`, not
> 0.5; the rest is small-`N` discreteness in the exact test. **The ranking is identical under all three,
> and the ranking is what the block-length decision turns on.** Quote the ordering, not the digits, until
> one derivation is agreed.

Report `>= 30 ms` alongside as description, never as a test. The interleaved blocks make the drift
survivable rather than fatal; they do not make `>= 30 ms` Poisson.

**Count `period`, not `frame`.** The emit gate at `Telemetry.cs:966` tests `periodMs` alone — `frameMs` is
passed in and never tested. Since `frame` travels one line ahead of `period`, a large frame can sit on a
line whose period is under threshold and emit nothing. Counting `frame >= T` off the spike stream
undercounts by about a third, and 8 of 16 windows have a percentile-derived lower bound above their
observed count.

### Stratify the B2 blocks — they are not one condition

Arm 2 straddles two regimes, and the raid crosses the boundary on its own. At 23 agents and 17.1 ms frames
the computed `perFrame` is 4 and `Minimum brains per frame` is 4 — **they coincide exactly.** Slicing binds
above ~30 agents; the floor binds below ~15; **Streets runs 14–29 within a single raid.**

**`tickedSum ÷ liveSum` is the arm's own covariate.** Split the B2 windows on it before pooling: a real
effect present only in the high-agent windows gets diluted by the windows where the floor meant nothing was
actually sliced. **Pre-register the split rather than discovering it in the analysis** — deciding where to
cut after seeing the outcome is how a null becomes a finding.

That also makes the Kaban phase sharper than "best case". It is the **highest-agent** phase of the raid, so
it is the one place slicing is guaranteed to bind rather than sit on the floor — which makes it the
cleaner test of the mechanism, not merely the most favourable.
