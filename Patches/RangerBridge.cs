using System.Runtime.CompilerServices;
using BepInEx.Bootstrap;

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
    }
}
