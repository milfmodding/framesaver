# Framesaver

BepInEx plugin investigating AI-driven frame stutter in SPT. Two patches plus a telemetry recorder.

Build with `dotnet build -c Release`; the post-build step copies `Framesaver.dll` into
`BepInEx/plugins/`. Config lives in `BepInEx/config/framesaver.ai.perf.cfg` after first launch.

Findings and methodology are in [FINDINGS.md](FINDINGS.md); behaviour alongside other AI and co-op mods is
in [COMPATIBILITY.md](COMPATIBILITY.md); the validation plan for SPT 4.0.13 is in [TESTING.md](TESTING.md).

## Compatibility guards

`0. Compatibility → Defer to other AI mods` (default on) stands Framesaver down from features another
installed mod already owns:

| Detected | Effect |
| --- | --- |
| AILimit | The stand-by patch disables itself — AILimit drives the same `BotStandBy` objects and pauses harder |
| ORBIT or BigBrain | Round-robin brain slicing is forced off — both drive bot brains and would see stale layer state |
| Fika headless host | The headless local player is excluded from the nearest-human distance, and the remote-player sweep is forced on |

Detection is deferred to the first stand-by check of a raid, not done at startup, because BepInEx populates
`Chainloader.PluginInfos` as plugins instantiate — an `Awake`-time check would depend on load order. The
result is logged when it resolves. Reasoning for each guard is in [COMPATIBILITY.md](COMPATIBILITY.md).

## Patches

**1. Bot stand-by** — `BotStandBy.Update` / `BotStandBy.InitPoints`

Vanilla measures distance to the nearest *enemy or neutral* and sleeps a bot past 240 m. In SPT that set is
mostly other bots, so a cluster of AI keeps itself awake with the player across the map, and the stand-by
system — the only gate on the 22 subsystem ticks in `BotOwner.UpdateManual` — effectively never fires. This
measures distance to human players instead.

Scope: pausing a bot skips `UpdateManual` and nothing else. `AICoreControllerClass` never consults stand-by
state, so brains (and therefore cover searches) keep running for sleeping bots. `BotOwner.FixedUpdate` also
ignores it, so the mover/navmesh raycast path is unaffected for bots on the FixedUpdate queue.

**2. AI brain scheduler** — `AICoreControllerClass.Update`

- *Leak fix* (default on). `HashSet_1` is the pending-removal set. Vanilla drains it into `HashSet_0.Remove`
  every frame but never clears it, and `method_0` clears `HashSet_0`/`HashSet_2` while skipping it. Every
  disposed agent is re-walked for the rest of the raid and stays strongly referenced, holding each dead bot's
  strategy, layers, node dictionary and GameObject alive.
- *Round-robin slicing* (default **off**). Spreads brain updates across frames, mirroring the shape of
  `AITaskManager.Class284.UpdateGroup` — the game's own load-adaptive scheduler, which stock EFT registers for
  exactly one task group (LookSensor). This is the setting that throttles the recursive cover search
  (`GClass381.GetCover` → `method_6`, up to 500 point checks and 100 raycasts per search, synchronous, main
  thread). It trades AI reaction time for frame time.

## Current telemetry fields

Deliberately narrow: a field survives only if it is still open, guards a confirmed fix against regression,
or is a headline number. Everything measured-and-settled has been removed along with its patch — the index
of what went and what it showed is in [FINDINGS.md](FINDINGS.md).

| field | why it is kept |
| --- | --- |
| `frame` / `gameUpdate` / `framePct` | headline; `gameUpdate` excludes the frame-limiter sleep |
| `phases` (+ `Expand phase` children) | the workhorse; subsumes the removed measurers |
| `spawn` | the root-cause finding — `creates` vs `botOwners` guards against regression |
| `profileBuild` | cost model: profiles built, total ms, and the inventory share (93%) |
| `asyncUpdateDrain` / `asyncFixedDrain` / `asyncDrained` / `worstCallbacks` | the stall diagnostic |
| `asyncFixedSkips` | confirms the FixedUpdate drain skip is firing, which zero drain time alone cannot |
| `playerLate` / `playerTick` | evidence fixes 2 and 3 still work |
| `bots` (awake/asleep/animCulled), `snipersAwake` | evidence fix 1 and the sniper exemption still work |
| `jobQueue` / `jobSchedulerLate` | continuation backlog; explained as bundle loading, still watched |
| `ambientLight` | **required on any non-Streets map** — it is inactive on Streets, not cheap |
| `botBackup` (fired/bailed) | open finding: 82% of backup flushes are refused by the in-flight guard |
| `bundleLoad` (calls/keys/inFlightMax) | drives the job queue; sync cost measured and refuted |
| `aiTotal`, `agents.pendingRemoval`, `gc`, `cfg` | cheap regression checks and A/B segmentation |

### GPU-side and GC-attribution fields (added 2026-07-27/28)

Added to close the GPU blind spot, which is how `TimeUpdate` was identified as garbage collection rather than
a presentation wait. See [FINDINGS.md](FINDINGS.md), "GPU-side telemetry — stage 3" and "Control run — stage 4".

| field | where | why it is kept |
| --- | --- | --- |
| `gcPhase` | spike | **the field the GC finding rests on** — which top-level player-loop phase a collection *completed in*, not merely which frame it landed on. Reads `TimeUpdate` on 22 of 23 in-raid collection frames across two maps. Only emitted when `gcGen0 > 0`. |
| `heapDeltaMb` | spike | signed heap change across the frame. Sharply negative confirms a pause was a collection rather than something correlated with one. Also emitted only when `gcGen0 > 0`. |
| `gcSuspendsBefore` / `gcMsSinceSuspend` | spike | GC suspensions since the previous collection, and how long before it the last one ended. Built to test whether `suspendGc` manufactures pauses. **Known limitation: no resolution inside a non-yielding callback** — latched at the post-callback sample, so during loading it carries no ordering information. Do not read a null here as evidence. |
| `qpc` / `qpcFrequency` | spike, sample / header | true `QueryPerformanceCounter`, for joining against an external capture. **Not** `Stopwatch.GetTimestamp()`, which under Mono is process-relative and will not join. `qpc` is stamped at frame *end*; PresentMon's `CPUStartQPC` is frame *start*, so subtract `period`. |
| `gpu.vram` | sample | DXGI budget vs usage via BSG's own `CameraClass.GetVRamUsage`. **`overBudget` is the field to watch** — non-zero means the driver is evicting, which no other instrument here can see. Measured 0 everywhere so far; kept as a cheap regression guard (`queryMsMax` 0.001–0.03 ms). |
| `gpu.render` | sample | `ProfilerRecorder` draw calls / SetPass / triangles. This build ships with the profiler enabled. Draw calls track awake bots (r = +0.74) but **not** frame time (r = +0.06), so submission cost is not a lever here. |
| `gpu.frameTiming` | sample | `FrameTimingManager`. **Reports unavailable on this build** — Frame Timing Stats is a baked player setting. Left in place so a build that has it is detected automatically. |
| `gfx` | sample | live graphics state per line: render vs screen resolution, reflex, vSync, targetFps, mipLimit, lodBias, DLSS/FSR/AA. Exists because `Graphics.ini` **disagreed with the runtime** on three settings and sent an investigation after a VRAM problem that did not exist. Read this, not the ini. |
| `gpuDevice` / `gfxSettings` | header / first sample | one-shot device and full graphics dump. `gfxSettings` is emitted on the first window line that can resolve the settings singleton, not in the header — the singleton does not exist at plugin load. |
| `gcDrive` | sample | counters for `Drive incremental GC ms`. `pending` is the diagnostic: how often `CollectIncremental` still had work outstanding. **Never yet exercised — both GC knobs have only ever run at 0.** |
| `cfg.gcTimeSliceMs` / `gcDriveMs` / `gcSliceApplied` | sample | the two GC experiment knobs, per the rule that any option changing behaviour belongs in `cfg`. |

**A phase missing from `phases` means `< 0.5 ms`, not zero.** `Telemetry` adds every top-level phase to
`accounted` and *then* drops it from the JSON if it is under 0.5 ms, so the residual arithmetic is correct
while the field silently disappears. Read an absent phase as "below threshold", never as "did not run" — and
note the asymmetry that makes it easy to misread: `TimeUpdate` absent is the normal case in raid (median
0.065 ms), so its *presence* is the signal. Same shape as `gcPhase`, which is also omitted rather than
emitted empty.

**Two fields are known-defective and must not be used:** `initHeapDeltaMb` (reads 6,900 MB inside a 208 MB
container on one raid; internally consistent on another, so flagged rather than removed), and `state`, which
reports `loading` at the menu because `CurrentState()` gates `Menu` on `GameWorld` being absent and the world
persists after a raid. Filter menu-idle artifacts on `period > 60000` until that is fixed.

## Telemetry

Writes newline-delimited JSON to `BepInEx/plugins/Framesaver-logs/framesaver-<timestamp>-<tag>.ndjson`.
One header line, then one `sample` line per window (default 60 s), plus one `spike` line per frame slower
than `Spike event ms`.

### Session state and the raid clock

Every `sample` and `spike` line carries `state`:

| state | meaning |
| --- | --- |
| `loading` | `GameWorld` exists but the match is not `GameStatus.Started` — map load and spawn-in |
| `raid` | match running |

Sampling starts when `GameWorld` appears and closes with a `final` line when it goes away, so the menu and
hideout are never logged. A window never straddles two states — a state change forces a flush first.

One log file covers the whole game session, so every line also carries which raid it came from:

| field | meaning |
| --- | --- |
| `raid` | 1-based counter of raids since launch — `window` and `t` both restart each raid, so this is what segments the file |
| `map` | `GameWorld.LocationId`, e.g. `bigmap` (Customs), `tarkovstreets`, `Woods`, `RezervBase` |

That means a single launch can cover several maps back to back and still be analysed per-raid. Set **Run
tag** to the mod stack under test (`solo`, `ai-stack`, `ailimit`) rather than the map, since the map is now
a field.

This matters because loading produces the largest stalls in the entire session (34.5 s and 13.8 s in one
raid), and until now they were timed but never attributed: the drain diagnostics were gated on the raid
having started. The drain *budget* is still raid-only, since rationing the loading queue would only
lengthen the loading screen.

Lines inside a running raid also carry the clock the O key shows:

| field | meaning |
| --- | --- |
| `raidElapsed` | seconds since the raid timer started |
| `raidLeft` | seconds remaining |
| `raidClock` | `raidLeft` as `HH:MM:SS` — exactly what O displays |

So "it stuttered at about 22 minutes left" maps onto `raidClock` without arithmetic.

Note `t` is seconds since *sampling* began, which now includes loading — that is why the raid clock is
reported separately. `frames` counts every sampled frame; `n` counts only those with the game's frame
measurers available, so `n` is 0 in early loading windows while `frames` is not.

`frame` and `gameUpdate` come from `GClass1357`, the same source as the `fps 3` console readout.
`gameUpdate` is `frame - render`, and since `render` is measured through to `EndOfFrame` it contains the
frame-limiter and V-Sync sleep — so `gameUpdate` is the one to trust, and V-Sync should be off regardless.

Every `Stat` block carries `avg` / `min` / `max` over the window. Percentiles are on `framePct` only
(p50/p95/p99/p999); a fixed millisecond spike threshold was tried and abandoned because it does not
transfer between maps.

## Run protocol

Change **Run tag** between runs so the files are self-identifying; each file's header line records the full
config that produced it. Change one variable at a time:

Two rules learned the hard way, both in FINDINGS.md:

- **Never compare across maps.** Percentile baselines, `ambientLight` activity and the sleep-distance
  hit rate are all map-specific. Compare within a run, or between runs on the same map.
- **A/B within a single raid, from a fixed position, with an off→on→off reversal.** Location dominates
  frame time on large maps; the reversal is what separates a real effect from having walked somewhere
  lighter. Config is live-editable and recorded on every sample line as `cfg`, so segmenting on it is how
  every A/B in FINDINGS.md was resolved.

The `raidClock` field matches the O-key readout exactly, so "it stuttered around 22 minutes left" maps
onto a line without arithmetic.
