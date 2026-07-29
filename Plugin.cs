using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using Framesaver.Patches;

namespace Framesaver
{
    [BepInPlugin("framesaver.ai.perf", "Framesaver", "0.1.0")]
    public class Plugin : BaseUnityPlugin
    {
        public static ManualLogSource LogSource;

        // ---- 0. Compatibility ---------------------------------------------------------------
        public static ConfigEntry<bool> DeferToOtherAiMods;
        public static ConfigEntry<bool> ReclaimStandBy;

        // ---- 1. Bot stand-by (BotStandBy) --------------------------------------------------
        public static ConfigEntry<bool> StandByEnabled;
        public static ConfigEntry<float> SleepDistance;
        public static ConfigEntry<float> WakeDistance;
        public static ConfigEntry<float> CheckInterval;
        public static ConfigEntry<bool> ForceStandByForAllRoles;
        public static ConfigEntry<bool> SleepImmediately;
        public static ConfigEntry<bool> KeepFightingBotsAwake;
        public static ConfigEntry<bool> IncludeAllHumanPlayers;
        public static ConfigEntry<int> KeepNearestSnipersAwake;

        // ---- 2. AI brain scheduler (AICoreControllerClass) ----------------------------------
        public static ConfigEntry<bool> FixAgentLeak;
        public static ConfigEntry<float> BrainUpdatePeriod;
        public static ConfigEntry<int> MinBrainsPerFrame;

        // ---- 3. Experimental ----------------------------------------------------------------
        public static ConfigEntry<bool> ForceFastBodyAnimator;
        public static ConfigEntry<bool> CullSleepingBotAnimators;
        public static ConfigEntry<float> MaxDeltaTime;
        public static ConfigEntry<bool> DeactivateSleepingBotState;
        public static ConfigEntry<bool> SkipSleepingLateUpdate;
        public static ConfigEntry<bool> SkipSleepingWorldTick;
        public static ConfigEntry<float> JobSchedulerBudgetMs;
        public static ConfigEntry<int> JobSchedulerSlowFrames;
        public static ConfigEntry<float> AsyncDrainBudgetMs;
        public static ConfigEntry<bool> AsyncDrainDiagnostics;
        public static ConfigEntry<bool> SuspendGcDuringCallbacks;
        public static ConfigEntry<bool> DrainInUpdateOnly;
        public static ConfigEntry<float> GcTimeSliceMs;
        public static ConfigEntry<float> GcDriveMs;

        // ---- 4. Telemetry -------------------------------------------------------------------
        public static ConfigEntry<bool> TelemetryEnabled;
        public static ConfigEntry<string> RunTag;
        public static ConfigEntry<BepInEx.Configuration.KeyboardShortcut> ProtocolKey;
        public static ConfigEntry<BepInEx.Configuration.KeyboardShortcut> MarkKey;
        public static ConfigEntry<float> TelemetryWindow;
        public static ConfigEntry<float> SpikeEventMs;
        public static ConfigEntry<bool> ProfilePlayerLoop;
        public static ConfigEntry<string> ExpandPhase;
        public static ConfigEntry<bool> GpuTelemetryEnabled;

        private void Awake()
        {
            LogSource = Logger;

            DeferToOtherAiMods = Config.Bind(
                "0. Compatibility", "Defer to other AI mods", true,
                "Stand down from features another installed mod already owns. AILimit drives the same "
                + "BotStandBy objects we do and pauses bots harder, so the stand-by patch turns itself off "
                + "when it is present; ORBIT and BigBrain drive bot brains, so round-robin brain slicing "
                + "turns itself off when either is present. Turn this off to force Framesaver's own "
                + "behaviour and accept the overlap - see COMPATIBILITY.md. Detection is logged at the "
                + "first stand-by check of a raid, not at startup.");

            ReclaimStandBy = Config.Bind(
                // Key deliberately unchanged mid-testing so an existing config keeps its value; it now also
                // covers ORBIT, so the name under-describes it.
                "0. Compatibility", "Reclaim stand-by from QuestingBots", true,
                "QuestingBots sets CanDoStandBy = false on every bot as it activates, and ORBIT does the same "
                + "in its brain layer. Either disables Framesaver's stand-by system completely - measured on "
                + "Streets as every bot awake for a whole raid and roughly double the frame time. "
                + "QuestingBots' stated reason is bots getting stuck in stand-by near enemy PMCs, which is a "
                + "property of *vanilla's* check - it measures distance to the nearest enemy or neutral, "
                + "measures distance to the nearest enemy or neutral (mostly other bots in SPT); our "
                + "replacement measures distance to humans and never sleeps a bot that has a goal enemy, so "
                + "it cannot get stuck that way. Turn off to let QuestingBots win and accept the frame cost. "
                + "Only ever applies to roles whose own Mind.CAN_STAND_BY is true, so bosses that must never "
                + "sleep (Gluhar, Zryachiy) stay exempt.");

            StandByEnabled = Config.Bind(
                "1. Bot stand-by", "Enabled", true,
                "Replaces the vanilla stand-by check. Vanilla measures distance to the nearest enemy OR neutral, " +
                "so in SPT bots keep each other awake and almost never sleep. This measures distance to human " +
                "players instead.");

            SleepDistance = Config.Bind(
                "1. Bot stand-by", "Sleep distance", 150f,
                new ConfigDescription(
                    "Bots further than this (metres) from a human player go to sleep. Vanilla effective value is 240.",
                    new AcceptableValueRange<float>(20f, 1000f)));

            WakeDistance = Config.Bind(
                "1. Bot stand-by", "Wake distance", 130f,
                new ConfigDescription(
                    "Sleeping bots closer than this (metres) wake up. Keep it below Sleep distance - the gap is " +
                    "hysteresis that stops bots thrashing between states. Vanilla effective value is 220.",
                    new AcceptableValueRange<float>(20f, 1000f)));

            CheckInterval = Config.Bind(
                "1. Bot stand-by", "Check interval", 5f,
                new ConfigDescription(
                    "Seconds between stand-by re-evaluations per bot. Vanilla is 10. Lower reacts faster to a " +
                    "moving player at a negligible cost.",
                    new AcceptableValueRange<float>(1f, 30f)));

            KeepFightingBotsAwake = Config.Bind(
                "1. Bot stand-by", "Keep fighting bots awake", true,
                "Never sleep a bot that currently has a goal enemy, whatever the distance. Stops a bot-vs-bot " +
                "fight freezing mid-way in case the player walks into it. Turn off for maximum savings.");

            SleepImmediately = Config.Bind(
                "1. Bot stand-by", "Sleep immediately", true,
                "Vanilla makes a bot pathfind to the nearest cover point and walk there before it actually sleeps " +
                "(the 'goToSave' state), costing a full navmesh path for a bot nobody can see. This puts it to " +
                "sleep where it stands.");

            ForceStandByForAllRoles = Config.Bind(
                "1. Bot stand-by", "Force for all roles", false,
                "Vanilla disables stand-by entirely for roles whose Mind.CAN_STAND_BY is false (typically bosses " +
                "and their guards). Enabling this lets those sleep too. Off by default - boss scripting is the " +
                "most likely thing to break.");

            IncludeAllHumanPlayers = Config.Bind(
                "1. Bot stand-by", "Consider all human players", true,
                "Also measure distance to other human players (co-op / Fika). Harmless in single-player.");

            KeepNearestSnipersAwake = Config.Bind(
                "1. Bot stand-by", "Keep nearest snipers awake", 2,
                new ConfigDescription(
                    "Keep this many marksman (sniper scav) bots awake regardless of distance, nearest first. "
                    + "Distance is the wrong proxy for snipers - they are placed to engage from beyond any "
                    + "sensible sleep radius, so a pure distance rule means they never take a shot. Ranking "
                    + "by nearest rather than exempting the role caps the cost at exactly this many bots no "
                    + "matter how many the map has. 0 disables.",
                    new AcceptableValueRange<int>(0, 8)));

            FixAgentLeak = Config.Bind(
                "2. AI brain scheduler", "Fix dead-agent leak", true,
                "AICoreControllerClass.Update drains its pending-removal set every frame but never clears it, so " +
                "every disposed bot brain is retained and re-walked for the rest of the raid. This clears it.");

            BrainUpdatePeriod = Config.Bind(
                "2. AI brain scheduler", "Brain update period", 0f,
                new ConfigDescription(
                    "Seconds one full pass over all bot brains should take, spread round-robin across frames. " +
                    "0 = vanilla (every brain, every frame). This is the setting that throttles the cover-search " +
                    "hotspot, and it genuinely trades AI reaction time for frame time - try 0.05-0.1 and measure.",
                    new AcceptableValueRange<float>(0f, 0.5f)));

            MinBrainsPerFrame = Config.Bind(
                "2. AI brain scheduler", "Minimum brains per frame", 4,
                new ConfigDescription(
                    "Floor on brains ticked per frame while slicing, so low bot counts stay responsive.",
                    new AcceptableValueRange<int>(1, 64)));

            TelemetryEnabled = Config.Bind(
                "3. Telemetry", "Enabled", true,
                "Write per-window frame-timing summaries as newline-delimited JSON to BepInEx/Framesaver/. " +
                "Sampling is a handful of double reads per frame; the cost is not measurable against the " +
                "numbers being recorded.");

            RunTag = Config.Bind(
                "3. Telemetry", "Run tag", "baseline",
                "Appended to the log filename so runs are self-identifying. Change this between A/B runs, " +
                "e.g. baseline / standby / sliced-50ms.");

            // Deliberately awkward. An accidental press advances the protocol and voids the arm in
            // progress, so this wants to be hard to hit by mistake and easy to hit on purpose. F12 is
            // ConfigurationManager and EFT binds most bare keys and single modifiers. Confirmed with
            // Sophia, who is the one who will hit it wrong at minute eleven.
            ProtocolKey = Config.Bind(
                "3. Telemetry", "Protocol step key",
                new BepInEx.Configuration.KeyboardShortcut(
                    UnityEngine.KeyCode.PageDown,
                    UnityEngine.KeyCode.LeftControl,
                    UnityEngine.KeyCode.LeftAlt),
                new ConfigDescription(
                    "Advances the measurement protocol one step: applies that step's config values, closes "
                    + "the current telemetry window immediately, and stamps the new arm onto every line "
                    + "after it. Replaces changing knobs through the F12 overlay, which moves the view, "
                    + "costs a large IMGUI draw, and lands the change mid-window. Does nothing and says so "
                    + "if no protocol is loaded - see framesaver.protocol.ini."));

            // Adjacent to the protocol key, but the failure modes are opposites and
            // that is what sets the default apart. A missed protocol press voids an
            // arm; a missed mark loses one observation out of many. So that key is
            // chosen to be hard to hit by accident, and this one to be reachable
            // WITHOUT LOOKING DOWN MID-FIGHT - because the marks we most want are
            // the ones she is least able to stop and aim for. End rather than Home:
            // further from PageDown, so a fumbled protocol press cannot land here.
            //
            // Provisional. Sophia knows what EFT leaves spare and picked the
            // protocol key. This is a KeyboardShortcut entry, so changing it is a
            // config edit and never a build.
            MarkKey = Config.Bind(
                "3. Telemetry", "Mark key",
                new BepInEx.Configuration.KeyboardShortcut(
                    UnityEngine.KeyCode.End,
                    UnityEngine.KeyCode.LeftControl,
                    UnityEngine.KeyCode.LeftAlt),
                new ConfigDescription(
                    "Writes a 'mark' line saying you noticed choppiness just now, with the frame times "
                    + "leading up to the press so the reading is a labelled sample rather than a "
                    + "timestamp. Unlike the protocol key this does NOT close the window - marks are "
                    + "frequent, and flushing on each one would put every statistic on a different "
                    + "denominator. Marks are numbered per raid and stamped with the map, so a written "
                    + "note only needs the ordinal: 'Factory mark 2, mid-fight'."));

            TelemetryWindow = Config.Bind(
                "3. Telemetry", "Window seconds", 60f,
                new ConfigDescription(
                    "How much wall time each summary line covers.",
                    new AcceptableValueRange<float>(10f, 300f)));

            SpikeEventMs = Config.Bind(
                "3. Telemetry", "Spike event ms", 100f,
                new ConfigDescription(
                    "Write a separate line for every frame at least this slow, carrying that frame's own phase "
                    + "breakdown and an 'unaccounted' residual. Window summaries cannot resolve a spike whose "
                    + "phase maxima came from different frames, and only per-frame lines give the exact cadence "
                    + "of a recurring one. 0 disables.",
                    new AcceptableValueRange<float>(0f, 2000f)));

            ProfilePlayerLoop = Config.Bind(
                "3. Telemetry", "Profile player loop", true,
                "Inject timing markers around every top-level Unity player-loop phase (Initialization, " +
                "EarlyUpdate, FixedUpdate, PreUpdate, Update, PreLateUpdate, PostLateUpdate). This is what " +
                "locates work that falls outside the game's own Update/FixedUpdate/render counters. Turn off " +
                "if you suspect the injection is causing trouble.");

            // Renamed from "Expand phase" when the meaning inverted from allowlist to blocklist. The
            // rename is the point: BepInEx orphans the old key and creates this one at its default, so
            // an existing "PreLateUpdate" goes inert rather than silently meaning the opposite. Every
            // alternative - warnings in the description, in the run sheet, a changed default - needs a
            // human to notice something that looks correct.
            ExpandPhase = Config.Bind(
                "3. Telemetry", "Do not expand phases", "",
                "Comma-separated player-loop phases NOT to break into their child systems. Blank - the "
                + "default - expands every phase, which is what you almost always want. This is a "
                + "blocklist: an allowlist could only time phases someone had thought to name, so a "
                + "phase carrying a rare large spike went unmeasured while the output looked complete. "
                + "A blocklist fails toward collecting too much instead. Deliberately no default "
                + "entries - Initialization averages 0.005 ms and looks like an obvious block, but one "
                + "in-raid Initialization spike of 74.8 ms is on record, and average cost is the wrong "
                + "criterion for a spike instrument. Read only inside Install(), so a change takes "
                + "effect on the NEXT raid load; setting it mid-raid does nothing. The phases actually "
                + "expanded are reported as `expandedPhases` on the telemetry header, and entries "
                + "matching no phase are logged - a blocklist typo expands something you meant to block "
                + "and otherwise looks exactly like success.");

            GpuTelemetryEnabled = Config.Bind(
                "3. Telemetry", "GPU telemetry", true,
                "Sample VRAM budget vs usage (BSG's own DXGI query, twice a second), Unity's FrameTimingManager " +
                "and the render-submission profiler counters. This is the only view into the GPU side, which is " +
                "where the TimeUpdate presentation-wait spikes live. Sources that this build does not support " +
                "report themselves as unavailable and then stop costing anything.");

            ForceFastBodyAnimator = Config.Bind(
                "4. Experimental", "Force fast body animator", false,
                "Turn on BSG's own FastAnimatorProcessorClass in place of Unity's Animator for character " +
                "bodies. Unity's animation pass is ~25% of the frame on Streets, so this targets the single " +
                "largest CPU-side game cost. The code path ships disabled, and the assets ship with it - but " +
                "it may be disabled because it is incomplete. Requires a restart. If characters T-pose, " +
                "animate wrongly, or fail to spawn, set this back to false and restart.");

            CullSleepingBotAnimators = Config.Bind(
                "4. Experimental", "Cull sleeping bot animators", true,
                "Set AnimatorCullingMode.CullCompletely on bots that are asleep, so their animator state " +
                "machines stop evaluating while off screen. Vanilla only reaches CullUpdateTransforms, which " +
                "skips transform writes but keeps evaluating. Safe for paused bots specifically because they " +
                "are already posed and stationary. Takes effect immediately - no restart needed.");

            MaxDeltaTime = Config.Bind(
                "4. Experimental", "Max delta time", 0.1f,
                new ConfigDescription(
                    "Caps Time.maximumDeltaTime. Unity's default of 0.333 lets one slow frame schedule a "
                    + "flood of catch-up FixedUpdate steps, which makes the next frame slower again - measured "
                    + "at 439ms of FixedUpdate during a bot spawn wave. Lowering it makes the engine drop time "
                    + "instead of spiralling. 0 leaves Unity's value untouched.",
                    new AcceptableValueRange<float>(0f, 0.34f)));

            DeactivateSleepingBotState = Config.Bind(
                "4. Experimental", "Set sleeping bots to NonActive", false,
                "Also set BotOwner.BotState = NonActive while a bot is paused, restoring Active on wake. "
                + "Pausing only skips BotOwner.UpdateManual, which other mods do not consult - SAIN, "
                + "LootingBots and QuestingBots all gate their per-bot work on BotState instead, so they "
                + "keep working on bots we have put to sleep. This closes that gap in one move, and is what "
                + "AILimit does. Off by default because BotState is read in roughly 30 places in BSG's own "
                + "code - follower assignment, boss spawning, group ally checks, the task manager and "
                + "movement among them - so it is a broader change than the pause itself. Bosses and their "
                + "followers are never deactivated regardless, since BotFollower requires a boss to be "
                + "Active to be followable.");

            SkipSleepingLateUpdate = Config.Bind(
                "4. Experimental", "Skip sleeping bot LateUpdate", false,
                "Skip Player.LateUpdate entirely for bots that are asleep. Riskiest of the three - if bots "
                + "return from sleep in a wrong pose or with stale visuals, turn this off first.");

            SkipSleepingWorldTick = Config.Bind(
                "4. Experimental", "Skip sleeping bot world tick", false,
                "Skip GameWorld's per-Player tick (UpdateTick / FixedUpdateTick) for bots that are asleep. "
                + "Separate flag from the LateUpdate skip because the failure modes differ - this one could "
                + "stall health effects or leave movement state stale across a sleep.");

            JobSchedulerBudgetMs = Config.Bind(
                "4. Experimental", "Job scheduler budget ms", 0f,
                new ConfigDescription(
                    "Overrides JobScheduler.FrameTicks. The game derives it from your FPS cap (120 -> 8ms), "
                    + "but frames take 10-11ms, so its budget check never passes and the continuation pump "
                    + "drops into a starvation burst every 4th frame with half this value to spend. Queue "
                    + "depth averaged 9-27 with peaks near 100 as a result. Try ~20. 0 leaves it alone.",
                    new AcceptableValueRange<float>(0f, 100f)));

            JobSchedulerSlowFrames = Config.Bind(
                "4. Experimental", "Job scheduler slow frames", -1,
                new ConfigDescription(
                    "Overrides JobScheduler.SlowFrames (vanilla 6), which sets how many starved frames pass "
                    + "before the pump ignores its budget. 0 makes it pump every frame, bounded by the budget "
                    + "above. -1 leaves it alone.",
                    new AcceptableValueRange<int>(-1, 12)));

            AsyncDrainBudgetMs = Config.Bind(
                "4. Experimental", "Async drain budget ms", 0f,
                new ConfigDescription(
                    "Caps how long AsyncWorker's completion drain may run per call, deferring the remainder to "
                    + "the next one. This is the confirmed cause of the multi-second FixedUpdate freezes: one "
                    + "unbounded drain measured 2588ms while physics never exceeded 6 steps, so it is the drain "
                    + "itself and not a catch-up spiral. Try 2-5. 0 leaves it unbounded. Only applies during an "
                    + "in-progress raid - loading needs to run its queue to completion.",
                    new AcceptableValueRange<float>(0f, 50f)));

            SuspendGcDuringCallbacks = Config.Bind(
                "4. Experimental", "Suspend GC during completion callbacks", false,
                "Disable garbage collection for the duration of each async completion callback, restoring it "
                + "immediately afterwards. Unity's incremental collector is enabled in this build (3 ms "
                + "slice) but slices only between frames - so a callback that runs 16 seconds without "
                + "returning to the player loop gives it no opportunity, and every collection forced inside "
                + "that callback must run to completion and block. One PMC bot-generation callback measured "
                + "21 such collections in 16.4 s. Suspending collection for the callback trades those "
                + "pauses for heap growth (~109 MB in that case), which the incremental collector then "
                + "reclaims in the background over following frames. Scope is one callback at a time, so "
                + "the exposure is bounded and GC is always restored, including on exception.");

            GcTimeSliceMs = Config.Bind(
                "4. Experimental", "GC time slice ms", 0f,
                new ConfigDescription(
                    "Override Unity's incremental GC slice (vanilla is 3 ms). Every in-raid TimeUpdate spike "
                    + "measured on 2026-07-27 carried exactly one gen0 collection - 14 of 14, against a base "
                    + "rate of one collection per 3,628 frames - and PresentMon showed the GPU idle through "
                    + "all of them, so those 80-120 ms stalls are stop-the-world pauses, not presentation "
                    + "waits. The collector is configured incremental and had ordinary frame boundaries "
                    + "either side, yet did not spread the work. Raising this tests whether it was simply not "
                    + "given enough time per frame. If pause size and count do not move, the sweep is "
                    + "unconditionally stop-the-world and no scheduling knob can help. 0 leaves it alone.",
                    new AcceptableValueRange<float>(0f, 50f)));

            GcDriveMs = Config.Bind(
                "4. Experimental", "Drive incremental GC ms", 0f,
                new ConfigDescription(
                    "Call GarbageCollector.CollectIncremental once per frame with this budget, handing the "
                    + "collector extra time before something forces a full collection. The companion test to "
                    + "'GC time slice ms': that one gives the collector longer slices, this one gives it more "
                    + "of them. Also a diagnostic - the reported `pending` count is how often the collector "
                    + "still had work outstanding after being driven, and a count that stays high means it is "
                    + "permanently behind rather than idle. Costs whatever budget it is given, every frame. "
                    + "0 disables.",
                    new AcceptableValueRange<float>(0f, 10f)));

            AsyncDrainDiagnostics = Config.Bind(
                "4. Experimental", "Async drain diagnostics", true,
                "Time each individual completion callback and report the slowest one per window, resolved back "
                + "to the call site that queued it. This is what identifies WHAT is stalling rather than just "
                + "where. Costs a timestamp pair per callback; turn off once the culprit is known.");

            DrainInUpdateOnly = Config.Bind(
                "4. Experimental", "Drain completions in Update only", true,
                "Suppress AsyncWorker's FixedUpdate drain so completions are picked up once per frame in "
                + "Update. Both phases call the same unbounded drain and Unity runs FixedUpdate first, so "
                + "whichever frame owes a physics step runs the callback inside physics - which is why the "
                + "same stall appears as an fuFPS spike sometimes and a gameUpdate spike other times. This "
                + "does NOT make the stall smaller; it moves it out of the physics step so it stops feeding "
                + "Unity's catch-up logic. Toggleable mid-raid.");

            new BotStandByUpdatePatch().Enable();
            new SleepingBotStandByPumpPatch().Enable();
            new BotStandByInitPointsPatch().Enable();
            new AICoreControllerUpdatePatch().Enable();
            new BotsControllerTickPatch().Enable();
            new FastBodyAnimatorPatch().Enable();
            new SleepingBotAnimatorPatch().Enable();
            new BotStandByStateChangePatch().Enable();
            new SkipSleepingPlayerLateUpdatePatch().Enable();
            new SkipSleepingWorldTickPatch().Enable();
            new AsyncWorkerUpdatePatch().Enable();
            new AsyncWorkerFixedUpdatePatch().Enable();
            new AsyncDrainPatch().Enable();
            new ProfileCtorPatch().Enable();
            new ProfileInventoryPatch().Enable();
            new BotBackupAddPatch().Enable();
            new BotBackupFlushPatch().Enable();
            new BundleLoadPatch().Enable();
            new SpawnCreateDataPatch().Enable();
            new SpawnByWavePatch().Enable();
            new SpawnWithoutWavePatch().Enable();
            new SpawnByTypeForcePatch().Enable();
            new SpawnZoneAttemptPatch().Enable();
            new BotOwnerCreatePatch().Enable();
            new BotCreateWorkPatch().Enable();

            // Raid initialisation, which resumes inline inside the last bot/generate completion callback and
            // is the unexplained 16.7s. One-shot per raid, so no per-frame cost.
            new BotsControllerInitPatch().Enable();
            new WavesSpawnRunPatch().Enable();
            new NonWavesSpawnRunPatch().Enable();
            new BossSpawnRunPatch().Enable();
            new CoversRestorePatch().Enable();
            new CoversCachePointsPatch().Enable();
            new BotDoorsRefreshPatch().Enable();
            new BotZoneInitPatch().Enable();
            new PatrolZoneMapPatch().Enable();
            new CutControllerInitPatch().Enable();
            new LootClusterScanPatch().Enable();

            // Pass 2: checkpoints that partition BotsController.Init, plus the vmethod_1 tail outside it.
            // Pass 1 left 91% of Init in `otherMs` and the cold/warm pair showed the entire warm-up lives
            // there, so these tile the method rather than sampling more of it.
            //
            // Registered through TryEnable rather than Enable: several target obfuscated types and one
            // resolves a method by string. A patch that fails to resolve throws out of Awake, which would
            // silently drop every registration after it - including the telemetry component - and cost a
            // raid to discover. A missing checkpoint only merges its segment into the previous one.
            TryEnable(new CoversCreateCheckpoint(), "CoversCreateCheckpoint");
            TryEnable(new CoverBoundsCheckpoint(), "CoverBoundsCheckpoint");
            TryEnable(new StationaryInitCheckpoint(), "StationaryInitCheckpoint");
            TryEnable(new ZoneLeaveCtorCheckpoint(), "ZoneLeaveCtorCheckpoint");
            TryEnable(new SettingsRepoCheckpoint(), "SettingsRepoCheckpoint");
            TryEnable(new EventsCtorCheckpoint(), "EventsCtorCheckpoint");
            TryEnable(new BotsControllerMethod2Checkpoint(), "BotsControllerMethod2Checkpoint");
            TryEnable(new GClass369InitCheckpoint(), "GClass369InitCheckpoint");
            TryEnable(new SpawnerCtorCheckpoint(), "SpawnerCtorCheckpoint");
            TryEnable(new CoreActivateCheckpoint(), "CoreActivateCheckpoint");
            TryEnable(new BotCreatorCtorPatch(), "BotCreatorCtorPatch");
            TryEnable(new SetSettingsPatch(), "SetSettingsPatch");
            TryEnable(new SpawnActionPatch(), "SpawnActionPatch");

            // Diagnostic, so it goes through TryEnable: a bare Enable() that fails to resolve throws out
            // of Awake and drops every registration after it, including telemetry - which would turn a
            // census defect into total data loss for the run.
            TryEnable(new PlayerOnDeadCensusPatch(), "PlayerOnDeadCensusPatch");


            new PlayerLateUpdateTimingPatch().Enable();
            new GameWorldPlayerTickPatch().Enable();
            new JobSchedulerLateUpdatePatch().Enable();
            new AmbientLightLateUpdatePatch().Enable();

            if (ProfilePlayerLoop.Value)
            {
                PlayerLoopProfiler.Install();
                PlayerLoopProfiler.ArmFrameGap();
            }

            if (TelemetryEnabled.Value)
            {
                gameObject.AddComponent<Telemetry>();
            }

            LogSource.LogInfo("Framesaver loaded.");
        }

        /// <summary>
        /// Enables a patch, logging rather than throwing if its target cannot be resolved.
        ///
        /// Only for diagnostic patches whose absence degrades a measurement instead of breaking a fix - an
        /// unresolved checkpoint just means its segment merges into the one before it. Confirmed fixes are
        /// still registered with a bare Enable(), because silently not applying one of those is worse than
        /// failing loudly.
        /// </summary>
        private static void TryEnable(SPT.Reflection.Patching.ModulePatch patch, string name)
        {
            try
            {
                patch.Enable();
            }
            catch (System.Exception ex)
            {
                LogSource.LogWarning("Framesaver: diagnostic patch " + name + " did not resolve - "
                                     + ex.Message + ". Its segment will merge into the previous one.");
            }
        }
    }
}
