using System.Runtime.CompilerServices;
using BepInEx.Bootstrap;
using EFT;

namespace Framesaver.Patches
{
    /// <summary>
    /// The ONLY place in Framesaver that is allowed to touch a Ranger.* type, and the reason it
    /// exists rather than every publish site calling TelemetryBus directly.
    ///
    /// **Why a plain reference + `if (TelemetryBus.Enabled)` is NOT safe with Ranger absent.**
    /// The .NET JIT resolves every type referenced anywhere in a method's IL when that method is
    /// first compiled - not only the ones on the branch actually taken at runtime. So a call like
    ///
    ///     if (TelemetryBus.Enabled) { TelemetryBus.Event(...); }
    ///
    /// written inline inside, say, BossGroupWake.Counts(), does not protect that method: the JIT
    /// has to resolve Ranger.TelemetryBus to compile Counts() AT ALL, whether or not Enabled ends
    /// up true. With Ranger.dll missing from BepInEx/plugins, that throws (TypeLoadException /
    /// FileNotFoundException) from inside Counts() itself, the first time Flush() calls it - every
    /// raid, every window, not a clean plugin-load-time failure. Worse than an outright load
    /// failure, because it looks like intermittent runtime instability rather than a missing file.
    ///
    /// **The fix: isolate every Ranger-touching call into its own method, marked NoInlining, and
    /// gate the CALL to that method (not its internals) behind a presence check done once.** The
    /// JIT only has to resolve a method's referenced types when THAT METHOD is compiled, and
    /// NoInlining stops the JIT folding this wrapper's body into its caller (which would pull the
    /// Ranger reference back into a method that has to compile regardless of presence). A caller
    /// that never invokes the wrapper never triggers its compilation, so Ranger's absence never
    /// surfaces as an exception - it just means telemetry silently does not fire, which is
    /// correct: no-kit is documented as the DEFAULT case in Ranger's own design doc.
    /// </summary>
    internal static class RangerBridge
    {
        private const string RangerGuid = "ranger.telemetry.kit";

        // Checked once, cached. Chainloader.PluginInfos is stable once BepInEx has finished
        // loading plugins, and every call site here runs well after that point (raid-time, not
        // Awake-time), so re-checking per call would just be repeated dictionary lookups for an
        // answer that cannot change mid-session.
        private static bool? _present;

        internal static bool Present
        {
            get
            {
                if (_present == null)
                {
                    _present = Chainloader.PluginInfos.ContainsKey(RangerGuid);
                }

                return _present.Value;
            }
        }

        /// <summary>
        /// BossGroupWake's publish call, isolated. See the class doc comment for why this exists
        /// as its own NoInlining method rather than an inline TelemetryBus call at the caller.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PublishBossGroupWake(int linked, int held)
        {
            if (!global::Ranger.TelemetryBus.Enabled)
            {
                return;
            }

            global::Ranger.TelemetryBus.Event("bossGroupWake.linked", linked);
            global::Ranger.TelemetryBus.Event("bossGroupWake.held", held);
        }

        /// <summary>
        /// RoleSleepDistance's publish call, isolated. Same reasoning as above.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PublishRoleSleepDistance(float effective, float effectiveWake)
        {
            if (!global::Ranger.TelemetryBus.Enabled)
            {
                return;
            }

            global::Ranger.TelemetryBus.Event("roleSleepDistance.effective", effective);
            global::Ranger.TelemetryBus.Event("roleSleepDistance.effectiveWake", effectiveWake);
        }

        /// <summary>
        /// LongRangeExemption's publish call, isolated. Same reasoning as above.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PublishLongRangeExemption(int count)
        {
            if (!global::Ranger.TelemetryBus.Enabled)
            {
                return;
            }

            global::Ranger.TelemetryBus.Event("longRangeExemption.count", count);
        }

        /// <summary>
        /// AICoreControllerUpdatePatch's publish call, isolated. Same reasoning as above. All 4
        /// values are already-computed snapshot counters (LiveAgents/PendingRemoval/RemovedTotal/
        /// LastBrainsTicked, all updated every frame in the Harmony prefix), so Event (last-write-
        /// wins) not Count.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PublishAICoreController(int liveAgents, int pendingRemoval, int removedTotal, int lastBrainsTicked)
        {
            if (!global::Ranger.TelemetryBus.Enabled)
            {
                return;
            }

            global::Ranger.TelemetryBus.Event("aiCoreController.liveAgents", liveAgents);
            global::Ranger.TelemetryBus.Event("aiCoreController.pendingRemoval", pendingRemoval);
            global::Ranger.TelemetryBus.Event("aiCoreController.removedTotal", removedTotal);
            global::Ranger.TelemetryBus.Event("aiCoreController.lastBrainsTicked", lastBrainsTicked);
        }

        /// <summary>
        /// AICoreControllerUpdatePatch's PER-FRAME accumulation, isolated. Capstone finding
        /// (2026-08-17/18): Telemetry.cs's own tickedSum/liveSum fields summed these two values
        /// directly every frame - a different relationship than the snapshot above (Event,
        /// last-write-wins). Sum accumulates, matching seam-2's StandByTransitions shape. Called
        /// once per frame from AICoreControllerUpdatePatch's own Prefix, not once per window like
        /// every other publish site here - deliberately, since the quantity being preserved IS a
        /// per-frame accumulation.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PublishAICoreControllerSums(int lastBrainsTicked, int liveAgents)
        {
            if (!global::Ranger.TelemetryBus.Enabled)
            {
                return;
            }

            global::Ranger.TelemetryBus.Sum("aiCoreController.tickedSum", lastBrainsTicked);
            global::Ranger.TelemetryBus.Sum("aiCoreController.liveSum", liveAgents);
        }

        /// <summary>
        /// BotStandByUpdatePatch's aggregate counts, isolated. Same reasoning as above, but note the
        /// shape difference from the other four publish sites: these five values are not static
        /// fields owned by the patch class itself - they are locals computed once per window inside
        /// Telemetry.CountBots(), which calls BotStandByUpdatePatch.RoleStandByKnown/RoleAllowsStandBy
        /// as per-bot predicates rather than accumulating its own counters. So this publish call is
        /// made from Telemetry.cs directly, at the point those locals already exist and are about to
        /// be serialized to NDJSON - matching where the data actually lives rather than inventing a
        /// PublishTelemetry() on a class that owns no state to publish.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PublishBotStandByCounts(int awake, int asleep, int exempt, int roleUnknown, int standByRefused)
        {
            if (!global::Ranger.TelemetryBus.Enabled)
            {
                return;
            }

            global::Ranger.TelemetryBus.Event("botStandBy.awake", awake);
            global::Ranger.TelemetryBus.Event("botStandBy.asleep", asleep);
            global::Ranger.TelemetryBus.Event("botStandBy.exempt", exempt);
            global::Ranger.TelemetryBus.Event("botStandBy.roleUnknown", roleUnknown);
            global::Ranger.TelemetryBus.Event("botStandBy.standByRefused", standByRefused);
        }

        /// <summary>
        /// ModCompat's publish call, isolated. Same reasoning as above. Publishes tags rather than
        /// events - each argument is either empty (no guard active) or names the mod responsible for
        /// that guard, so Tag (last-write-wins string) is the right shape, not Event (numeric).
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PublishModCompat(string suppressingStandBy, string suppressingSlicing, string clearingStandByFlag)
        {
            if (!global::Ranger.TelemetryBus.Enabled)
            {
                return;
            }

            global::Ranger.TelemetryBus.Tag("modCompat.suppressingStandBy", suppressingStandBy);
            global::Ranger.TelemetryBus.Tag("modCompat.suppressingSlicing", suppressingSlicing);
            global::Ranger.TelemetryBus.Tag("modCompat.clearingStandByFlag", clearingStandByFlag);
        }

        /// <summary>
        /// BotBackup's publish call, isolated. Same reasoning as above. All five values are
        /// already-computed per-window counters (static fields BotBackup owns, reset each window by
        /// its own ResetWindow), so Event not Count.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PublishBotBackup(int added, int fired, int bailed, int pendingMax, int largestRequest)
        {
            if (!global::Ranger.TelemetryBus.Enabled)
            {
                return;
            }

            global::Ranger.TelemetryBus.Event("botBackup.added", added);
            global::Ranger.TelemetryBus.Event("botBackup.fired", fired);
            global::Ranger.TelemetryBus.Event("botBackup.bailed", bailed);
            global::Ranger.TelemetryBus.Event("botBackup.pendingMax", pendingMax);
            global::Ranger.TelemetryBus.Event("botBackup.largestRequest", largestRequest);
        }

        /// <summary>
        /// AsyncDrain's publish call, isolated. Same reasoning as above.
        ///
        /// Deliberately publishes only GcSuspended and the top-1 worst-callback pair
        /// (WorstCallbackMs/WorstCallbackName), NOT Drained/Deferred/Truncated. Those three reset
        /// per-FRAME (AsyncDrain.ResetFrame, called from Telemetry.Sample every frame) rather than
        /// per-window (ResetWindow) - GcSuspended and the Top-N arrays are the only fields on this
        /// class that actually survive to the once-per-window call site this is published from. A
        /// window-boundary read of Drained/Deferred/Truncated would silently report only the LAST
        /// frame's counts rather than the window's, which is worse than not publishing them - the
        /// NDJSON side does not make this mistake either: asyncUpdateDrain/asyncFixedDrain are Stat
        /// blocks accumulated frame-by-frame into _asyncUpdate/_asyncFixed, not a single end-of-window
        /// read of the static fields.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PublishAsyncDrain(int gcSuspended, double worstMs, string worstName)
        {
            if (!global::Ranger.TelemetryBus.Enabled)
            {
                return;
            }

            global::Ranger.TelemetryBus.Event("asyncDrain.gcSuspended", gcSuspended);
            global::Ranger.TelemetryBus.Event("asyncDrain.worstMs", (float)worstMs);
            global::Ranger.TelemetryBus.Tag("asyncDrain.worstName", worstName);
        }

        /// <summary>
        /// SleepingBotAnimatorPatch's publish call, isolated. Same reasoning as above. All three
        /// values are passed in by the caller rather than read here - see
        /// SleepingBotAnimatorPatch.PublishTelemetry's own doc comment for why (each is a computed
        /// property that walks a bot roster per read, and the caller already paid for one read each
        /// to build the NDJSON "bots" block).
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PublishAnimatorCull(int animCulled, int animCulledOffScreen, int animCulledEngine)
        {
            if (!global::Ranger.TelemetryBus.Enabled)
            {
                return;
            }

            global::Ranger.TelemetryBus.Event("animatorCull.culled", animCulled);
            global::Ranger.TelemetryBus.Event("animatorCull.culledOffScreen", animCulledOffScreen);
            global::Ranger.TelemetryBus.Event("animatorCull.culledEngine", animCulledEngine);
        }

        /// <summary>
        /// StandByTransitions seam (extraction phase 2): a counted wake/sleep transition with
        /// its path duration, published from BotStandByUpdatePatch where the transition is
        /// observed. Count + Sum deliberately, NOT Event: Event is last-write-wins per window
        /// and would silently report only the final transition's length, while the semantic
        /// being preserved is `wokenMs / woken` = cost of ONE wake - both halves of that ratio
        /// must accumulate. Key names mirror the class's own NDJSON block ("standByTransitions":
        /// woken/wokenMs/slept/sleptMs). Called alongside the direct StandByTransitions call
        /// until that class moves to Ranger; additive, changes no NDJSON output.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void PublishStandByTransition(bool woken, double ms)
        {
            if (!global::Ranger.TelemetryBus.Enabled)
            {
                return;
            }

            global::Ranger.TelemetryBus.Count(woken ? "standBy.woken" : "standBy.slept", 1);
            global::Ranger.TelemetryBus.Sum(woken ? "standBy.wokenMs" : "standBy.sleptMs", ms);
        }

        /// <summary>
        /// Registers Framesaver's WHOLE per-frame surface (FrameLevers.PerFrame - MaxDeltaTime
        /// cap, JobScheduler tuning, player-loop profiler re-arm check - AND GcControl's
        /// ApplyConfig/Drive/Track) as ONE per-frame callback, isolated.
        ///
        /// REAL BUG FOUND AND FIXED HERE (2026-08-19, capstone cutover session): this used to
        /// be TWO separate methods (RegisterPerFrameLevers, RegisterGcControlPerFrame), each
        /// calling TelemetryBus.RegisterPerFrameCallback(FramesaverGuid, ...) with the SAME key.
        /// TelemetryBus's registration dictionary is `_perFrameCallbacks[modGuid] = callback` -
        /// last write wins, not additive - so Plugin.Awake() calling both in sequence silently
        /// dropped FrameLevers.PerFrame the moment GcControlPerFrame's registration ran second.
        /// Dormant only because nothing yet calls TelemetryBus.InvokePerFrameCallbacks() (that
        /// starts once the capstone's namespace switch lands and Ranger's Telemetry.cs starts
        /// driving the per-window/per-frame calls) - so this would have silently disabled the
        /// MaxDeltaTime cap, JobScheduler tuning and the profiler re-arm check the FIRST raid
        /// after cutover, with nothing in a build log or a review diff pointing at it. Caught by
        /// re-reading TelemetryBus's actual dictionary semantics rather than assuming two
        /// registration calls compose. Fixed by merging into one registration, one delegate,
        /// matching the one-modGuid-one-slot shape the dictionary actually has.
        ///
        /// The JIT resolves TelemetryBus/RegisterPerFrameCallback's signature the moment THIS
        /// method compiles, so it must never be called inline at Plugin.Awake() with Ranger
        /// possibly absent. Called once from Plugin.Awake(), gated on Present, same as the
        /// checkpoint patches.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void RegisterPerFrameLevers()
        {
            global::Ranger.TelemetryBus.RegisterPerFrameCallback(FramesaverGuid, PerFrame);
        }

        private static void PerFrame()
        {
            FrameLevers.PerFrame();
            GcControl.ApplyConfig();
            GcControl.Drive();
            GcControl.Track();
            // Capstone finding (2026-08-19): Ranger's Telemetry.cs reads asyncDrain.drainedThisFrame
            // back every frame - see AsyncDrainPatch.PublishAndResetFrame's own doc comment for why
            // publish-then-reset has to happen together, here, at this per-frame cadence.
            AsyncDrain.PublishAndResetFrame();
        }

        /// <summary>
        /// Registers the live reader for Plugin.ForceStandByForAllRoles.Value, isolated. See
        /// TelemetryBus.RegisterForceStandByForAllRolesReader's own doc comment for why this
        /// exists as a separate one-slot reader rather than folding into the window callback's
        /// cfg dump - it is read per bot-event (BotLogPatches.cs), not per window.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void RegisterForceStandByForAllRolesReader()
        {
            global::Ranger.TelemetryBus.RegisterForceStandByForAllRolesReader(ReadForceStandByForAllRoles);
        }

        private static bool ReadForceStandByForAllRoles()
        {
            return Plugin.ForceStandByForAllRoles.Value;
        }

        /// <summary>
        /// Registers the single stand-by-role predicate BotLogPatches.cs/CountBots ask per bot,
        /// isolated. See TelemetryBus.RegisterBotStandByPredicate's own doc comment for the
        /// one-slot shape and why. The delegate body reaches into
        /// Framesaver.Patches.BotStandByUpdatePatch, which is exactly the reason this whole
        /// registration call has to be isolated here rather than made inline anywhere the JIT
        /// might compile it with Ranger absent.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void RegisterBotStandByPredicate()
        {
            global::Ranger.TelemetryBus.RegisterBotStandByPredicate(FramesaverGuid, AskBotStandBy);
        }

        /// <summary>
        /// Registers CapstoneCallbacks.BuildHeader/BuildWindow as Ranger's header/window
        /// callbacks, isolated. Same reasoning as every other bridge method - the JIT
        /// resolves TelemetryBus.RegisterHeaderCallback/RegisterWindowCallback's JObject-
        /// typed signature (Newtonsoft.Json.Linq.JObject) the moment THIS method compiles,
        /// so it must never be called inline anywhere the JIT might compile with Ranger
        /// absent. Called once from Plugin.Awake(), gated on Present, same as every other
        /// registration site.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void RegisterCapstoneCallbacks()
        {
            global::Ranger.TelemetryBus.RegisterHeaderCallback(FramesaverGuid, CapstoneCallbacks.BuildHeader);
            global::Ranger.TelemetryBus.RegisterWindowCallback(FramesaverGuid, CapstoneCallbacks.BuildWindow);
            global::Ranger.TelemetryBus.RegisterSpikeCallback(FramesaverGuid, CapstoneCallbacks.BuildSpike);
            global::Ranger.TelemetryBus.RegisterWindowResetCallback(FramesaverGuid, CapstoneCallbacks.ResetWindow);

            // Gap found and fixed during the capstone cutover session (2026-08-19): Ranger's
            // already-committed Telemetry.cs has a comment on its ResetForRaid path claiming
            // SleepingBotAnimatorPatch.ResetForRaid() "moved to Framesaver's registered raid-start
            // callback" - but no such registration existed anywhere in Framesaver until this line.
            // Without it, per-raid stale-dictionary state in SleepingBotAnimatorPatch (see that
            // class's own ResetForRaid doc comment for what leaks otherwise) would never actually
            // clear once Ranger's Telemetry.cs becomes the live sampler and starts calling
            // InvokeRaidStartCallbacks() instead of the direct call Framesaver's original
            // Telemetry.cs makes today.
            global::Ranger.TelemetryBus.RegisterRaidStartCallback(FramesaverGuid, SleepingBotAnimatorPatch.ResetForRaid);
        }

        /// <summary>
        /// AwakeAge's per-bot wake notification, isolated. SleepingBotAnimatorPatch's
        /// BotStandByStateChangePatch calls this on every un-pause edge (see that class's
        /// own doc comment for why the hook lives there rather than in Wake()/GoToSleep()).
        /// BotOwner is a shared EFT type both assemblies reference directly - only the
        /// delegate body, which reaches into global::Ranger.AwakeAge, needs isolating.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void NotifyAwakeAgeWoke(BotOwner bot)
        {
            if (!Present)
            {
                return;
            }

            global::Ranger.AwakeAge.Woke(bot);
        }

        /// <summary>
        /// AwakeAge's per-bot sleep/end notification, isolated. Same reasoning as
        /// <see cref="NotifyAwakeAgeWoke"/>.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void NotifyAwakeAgeEnded(BotOwner bot)
        {
            if (!Present)
            {
                return;
            }

            global::Ranger.AwakeAge.Ended(bot);
        }

        /// <summary>
        /// AwakeAge's per-bot-call timing record, isolated. Gap found and fixed during the
        /// capstone cutover session (2026-08-19): UpdateManualTimingPatches.cs stays in
        /// Framesaver (it is a per-bot shipping-adjacent timing instrument, not one of the
        /// files that moves with Telemetry.cs/AwakeAgeTiming.cs) but calls AwakeAge.Record
        /// directly - a bare, unqualified reference that resolves to Framesaver's OWN copy of
        /// AwakeAge today. Once AwakeAgeTiming.cs is deleted from Framesaver at cutover, that
        /// call would not compile at all - caught by an exhaustive coupling sweep before
        /// deleting anything, not discovered as a build failure after. Same reasoning as every
        /// other bridge method: BotOwner is a shared EFT type, only the delegate body (which
        /// reaches into global::Ranger.AwakeAge) needs isolating.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void NotifyAwakeAgeRecord(BotOwner bot, long ticks)
        {
            if (!Present)
            {
                return;
            }

            global::Ranger.AwakeAge.Record(bot, ticks);
        }

        /// <summary>
        /// The player-loop profiler's periodic re-arm check, isolated. Gap found and fixed
        /// during the capstone cutover session (2026-08-19): FrameLevers.cs (staying in
        /// Framesaver - it is the per-frame shipping-lever surface, not a file that moves)
        /// called PlayerLoopProfiler.MarkersPresent()/.Install() directly, a bare reference
        /// that resolves to Framesaver's OWN copy of PlayerLoopProfiler.cs today. That file
        /// moves to Ranger AT THIS CUTOVER, together with Telemetry.cs (the seam-5 lesson,
        /// documented at length in EXTRACTION-PLAN.md: the profiler and the sampler that reads
        /// its Snapshot are statically coupled within one assembly and cannot change owners
        /// independently) - so once PlayerLoopProfiler.cs is deleted from Framesaver, this
        /// direct call would not compile. Caught by the same exhaustive coupling sweep that
        /// found the AwakeAge.Record gap, before deleting anything.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void ReArmPlayerLoopProfilerIfNeeded()
        {
            if (!Present)
            {
                return;
            }

            if (!global::Ranger.PlayerLoopProfiler.MarkersPresent())
            {
                global::Ranger.PlayerLoopProfiler.Install();
            }
        }

        /// <summary>
        /// Reads Ranger's current ProfileBuild.TotalMs/BundleLoad.SyncMsTotal/RaidInit.TotalMs in
        /// one call, isolated. Added 2026-08-19 (wiring-gap fix session) alongside deleting
        /// Framesaver's OWN copies of ProfileBuild/BundleLoad/RaidInit (RaidInitPatches.cs,
        /// ProfileBuildPatches.cs, BundleLoadPatches.cs, and their ~26 sibling patch classes) -
        /// those source files already moved to Ranger in the earlier extraction batches and
        /// Ranger's Plugin.cs now enables their patches, so Framesaver's copies were dead weight
        /// that had also drifted out of sync (Telemetry.cs, the only reader, stopped reading them
        /// at the capstone). AsyncDrainPatch's diagnostics block is the ONE remaining Framesaver
        /// call site that needs these three values - EXTRACTION-PLAN.md flagged a diagnostics/
        /// suppression class-split for AsyncDrainPatch.cs itself as still-needed follow-on work;
        /// this bridge method is a smaller, immediate fix that keeps AsyncDrainPatch's existing
        /// attribution (raidInitMs/profileMs/bundleSyncMs in its worstCallbacks NDJSON block)
        /// correct against the values that actually change now (Ranger's, not a frozen zero)
        /// without doing that larger split under time pressure. Absent-Ranger default (0,0,0) is
        /// the same shape AsyncDrainPatch's delta math already tolerates - a delta against a
        /// constant 0 baseline just reports 0 rather than a wrong number, same posture as every
        /// other RangerBridge call this session's caller can no-op through.
        /// </summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static void ReadDrainAttribution(out double profileMs, out double bundleMs, out double raidInitMs)
        {
            if (!Present)
            {
                profileMs = 0d;
                bundleMs = 0d;
                raidInitMs = 0d;
                return;
            }

            profileMs = global::Ranger.ProfileBuild.TotalMs;
            bundleMs = global::Ranger.BundleLoad.SyncMsTotal;
            raidInitMs = global::Ranger.RaidInit.TotalMs;
        }

        private static bool? AskBotStandBy(BotOwner bot)
        {
            if (!BotStandByUpdatePatch.RoleStandByKnown(bot))
            {
                return null;
            }

            return BotStandByUpdatePatch.RoleAllowsStandBy(bot);
        }

        // The guid every registration above stamps as its owner, matching Plugin.cs's
        // [BepInPlugin] attribute. Not RangerGuid (that names RANGER's own plugin id, checked
        // by Present) - this is FRAMESAVER's own id, the one TelemetryBus nests fields under.
        private const string FramesaverGuid = "framesaver.ai.perf";
    }
}
