using Framesaver.Patches;
using Newtonsoft.Json.Linq;

namespace Framesaver
{
    /// <summary>
    /// The Framesaver-side bodies for Ranger's registered header/window callbacks
    /// (TelemetryBus.RegisterHeaderCallback/RegisterWindowCallback), per Sophia's
    /// registered-callback design (room, 2026-08-17 ~15:39Z-19:23Z) and Tau's header-
    /// callback refinement (~18:33Z).
    ///
    /// WHY THIS FILE EXISTS RATHER THAN THE FRAGMENTS LIVING INLINE IN Plugin.cs: each
    /// callback body reaches into several Framesaver-only shipping classes
    /// (BossGroupWake, SleepingBotAnimatorPatch, LongRangeExemption, ModCompat,
    /// RoleSleepDistance, AICoreControllerUpdatePatch, GcControl) that Ranger's assembly
    /// has no reference to and must never need one for - the callback's BODY is compiled
    /// HERE, inside Framesaver's own assembly, where those types are ordinary in-assembly
    /// references. Ranger holds and invokes the delegate as an opaque Action&lt;JObject&gt;
    /// and never resolves any of these types itself. This is the whole point of the
    /// registered-callback design: type erasure through the delegate gets the same
    /// JIT-safety property RangerBridge's NoInlining isolation gets by the opposite route.
    ///
    /// CONTENT IS A DIRECT PORT of what Telemetry.cs's WriteHeader()/Flush() used to build
    /// inline before the capstone extraction removed it (verified against the pre-capstone
    /// commit cb6321c's Telemetry.cs, the last commit before these NDJSON blocks were
    /// pulled out pending this callback body being written) - same fields, same values,
    /// same nesting, just written into a JObject instead of appended to a shared
    /// StringBuilder (Sophia's JObject ruling, room 2026-08-18 06:33Z, supersedes the
    /// original Action&lt;StringBuilder&gt; callback shape the design session settled on
    /// the day before - the REGISTRATION mechanism is unchanged, only what the delegate
    /// builds).
    /// </summary>
    internal static class CapstoneCallbacks
    {
        /// <summary>
        /// Registered once at Framesaver's Awake via RangerBridge.RegisterCapstoneCallbacks
        /// (NoInlining-isolated, same pattern as every other Ranger-touching registration).
        /// Builds the ~10 header-only config facts that used to live in Telemetry.cs's
        /// WriteHeader() "config":{...} block plus AppendRoleSleep's "roleSleep":{...} -
        /// both written ONCE per session (WriteHeader's only call site), which is exactly
        /// this callback's cadence.
        /// </summary>
        internal static void BuildHeader(JObject obj)
        {
            JObject config = new JObject();
            config["standByEnabled"] = Plugin.StandByEnabled.Value;
            config["sleepDistance"] = Plugin.SleepDistance.Value;
            config["wakeDistance"] = Plugin.WakeDistance.Value;
            config["checkInterval"] = Plugin.CheckInterval.Value;
            config["keepFightingBotsAwake"] = Plugin.KeepFightingBotsAwake.Value;
            config["sleepImmediately"] = Plugin.SleepImmediately.Value;
            config["forceAllRoles"] = Plugin.ForceStandByForAllRoles.Value;
            config["fixAgentLeak"] = Plugin.FixAgentLeak.Value;
            config["brainUpdatePeriod"] = Plugin.BrainUpdatePeriod.Value;
            config["minBrainsPerFrame"] = Plugin.MinBrainsPerFrame.Value;
            obj["config"] = config;

            // Named deferToAiMods rather than defer because the drain budget already
            // emits a `defer` counter under a different key - see Telemetry.cs's
            // original WriteHeader comment for the full reasoning (unchanged, this is
            // a verbatim port).
            obj["deferToAiMods"] = Plugin.DeferToOtherAiMods.Value;

            // roleSleep.roles: a static table, not live config - written once because it
            // cannot change at runtime. EnsureDetected-adjacent classes are read here
            // exactly once per session, same cadence RoleSleepDistance.PublishTelemetry
            // already assumes (see that method's own doc comment).
            JArray roleNames = new JArray();
            foreach (string role in Patches.RoleSleepDistance.RoleNames())
            {
                roleNames.Add(role);
            }

            JObject roleSleep = new JObject();
            roleSleep["roles"] = roleNames;
            obj["roleSleep"] = roleSleep;

            Patches.RoleSleepDistance.PublishTelemetry();
        }

        /// <summary>
        /// Registered once at Framesaver's Awake via RangerBridge.RegisterCapstoneCallbacks.
        /// Builds every per-window fact that used to be read directly out of the 9 shipping
        /// classes staying in Framesaver (bossGroups, bots.animCulled*, agents.*, mods,
        /// snipersAwake, the ~25-field cfg block, GcControl's window+cfg fragments) -
        /// everything Telemetry.cs's Flush() used to build inline for these fields before
        /// the capstone extraction removed the reads pending this callback existing.
        ///
        /// tickedSum/liveSum read via TryGetSum, NOT a direct field read - see
        /// AICoreControllerUpdatePatch.PublishPerFrameSums's own doc comment for why this
        /// pair needed TelemetryBus.Sum (accumulating) rather than the Event (last-write-
        /// wins) shape the other four AICoreController fields use.
        /// </summary>
        internal static void BuildWindow(JObject obj)
        {
            // snipersAwake: LongRangeExemption.Count, read fresh here (mirrors the
            // pre-capstone call site exactly - PublishTelemetry() already runs from
            // LongRangeExemption's own code elsewhere, additive, unchanged).
            obj["snipersAwake"] = Patches.LongRangeExemption.Count;

            // bossGroups: two counts from one call, matching BossGroupWake.Counts's
            // own out-parameter shape.
            int groupLinked;
            int groupHeld;
            Patches.BossGroupWake.Counts(out groupLinked, out groupHeld);
            JObject bossGroups = new JObject();
            bossGroups["linked"] = groupLinked;
            bossGroups["heldAwake"] = groupHeld;
            obj["bossGroups"] = bossGroups;

            // bots.animCulled*: three COMPUTED PROPERTIES, each a bot-roster walk - read
            // once each into locals and reused for both this fragment and the existing
            // additive PublishTelemetry call below, exactly as the pre-capstone code did
            // (see SleepingBotAnimatorPatch.PublishTelemetry's own doc comment for why a
            // second read would double the walk cost every window for nothing).
            int animCulled = Patches.SleepingBotAnimatorPatch.CulledLastFrame;
            int animCulledOffScreen = Patches.SleepingBotAnimatorPatch.CulledOffScreen;
            int animCulledEngine = Patches.SleepingBotAnimatorPatch.CulledEngine;

            // NOTE: awake/asleep/exempt/roleUnknown/standByRefused/animCulled* used to
            // share ONE "bots":{...} object with Ranger's own CountBots() output
            // (awake/asleep/total/exempt/standByRefused/roleUnknown, computed Ranger-
            // side via TelemetryBus.TryAskBotStandBy). Those two halves are built in
            // DIFFERENT assemblies now and this callback nests under its own modGuid key
            // regardless (Sophia's no-legacy-flat-path ruling, 19:14Z) - so there is no
            // way to merge them back into one flat "bots" object without exactly the
            // code-level special-casing that ruling rejected. Emitted here as
            // "bots.animCulled"/"animCulledOffScreen"/"animCulledEngine" under this
            // callback's own nested key; the field-mapping doc (still to be written)
            // must record that the OLD single flat "bots" object is now SPLIT across
            // Ranger's own top-level fields and this nested block.
            JObject botsAnim = new JObject();
            botsAnim["animCulled"] = animCulled;
            botsAnim["animCulledOffScreen"] = animCulledOffScreen;
            botsAnim["animCulledEngine"] = animCulledEngine;
            obj["botsAnim"] = botsAnim;

            Patches.RangerBridge.PublishAnimatorCull(animCulled, animCulledOffScreen, animCulledEngine);

            // agents.*: slicing is the EFFECTIVE state (same expression
            // AICoreControllerUpdatePatch.cs:64 branches on), not the requested one - see
            // that class's own doc comment for why the two can disagree silently
            // (BigBrain arriving as a SAIN dependency being the concrete case that bit
            // us). tickedSum/liveSum via TryGetSum: Ranger's window-close reads these
            // through the bus now, not a Telemetry-owned private field.
            bool slicing = Plugin.BrainUpdatePeriod.Value > 0f && !ModCompat.SuppressSlicing;
            // RunIfPresent-family refactor (2026-08-20): routed through RangerBridge.
            // ReadAICoreControllerSums instead of a bare TelemetryBus.TryGetSum call - see that
            // method's own doc comment for why (mechanical audit enforces no bare Ranger.*
            // reference outside RangerBridge.cs, no exceptions for call sites that happen to be
            // safe for other reasons).
            double tickedSum;
            double liveSum;
            Patches.RangerBridge.ReadAICoreControllerSums(out tickedSum, out liveSum);

            JObject agents = new JObject();
            agents["live"] = Patches.AICoreControllerUpdatePatch.LiveAgents;
            agents["pendingRemoval"] = Patches.AICoreControllerUpdatePatch.PendingRemoval;
            agents["removedTotal"] = Patches.AICoreControllerUpdatePatch.RemovedTotal;
            agents["slicing"] = slicing;
            agents["suppressSlicing"] = ModCompat.SuppressSlicing;
            agents["tickedSum"] = tickedSum;
            agents["liveSum"] = liveSum;
            obj["agents"] = agents;

            Patches.AICoreControllerUpdatePatch.PublishTelemetry();

            // mods: which AI/co-op mods are detected. AppendDetected forces detection as
            // a side effect (same call site pre-capstone relied on - see ModCompat's own
            // doc comment for why detection is deliberately forced from exactly this
            // site and not the header, which runs too early in Awake).
            JArray modsArray = new JArray();
            foreach (string name in ModCompat.DetectedNames())
            {
                modsArray.Add(name);
            }

            obj["mods"] = modsArray;
            ModCompat.PublishTelemetry();

            // The ~25-field cfg block: every shipping-config value a run needs to be
            // told apart from the one before it (see the pre-capstone code's own comment
            // for why each of these earned its place - the suspend-GC flag cost a whole
            // raid's worth of confusion once, for exactly this reason). Verbatim port of
            // the field set and field names.
            JObject cfg = new JObject();
            cfg["windowSeconds"] = Plugin.TelemetryWindow.Value;
            cfg["standBy"] = Plugin.StandByEnabled.Value;
            cfg["leakFix"] = Plugin.FixAgentLeak.Value;
            cfg["brainPeriod"] = Plugin.BrainUpdatePeriod.Value;
            cfg["cullSleeping"] = Plugin.CullSleepingBotAnimators.Value;
            cfg["cullAllBots"] = Plugin.CullAllBotAnimators.Value;
            cfg["maxDelta"] = UnityEngine.Time.maximumDeltaTime;
            cfg["skipLate"] = Plugin.SkipSleepingLateUpdate.Value;
            cfg["skipTick"] = Plugin.SkipSleepingWorldTick.Value;
            cfg["jobBudgetMs"] = Plugin.JobSchedulerBudgetMs.Value;
            cfg["jobSlowFrames"] = Plugin.JobSchedulerSlowFrames.Value;
            cfg["asyncBudgetMs"] = Plugin.AsyncDrainBudgetMs.Value;
            cfg["suspendGc"] = Plugin.SuspendGcDuringCallbacks.Value;
            cfg["reclaimStandBy"] = Plugin.ReclaimStandBy.Value;
            cfg["deactivateSleeping"] = Plugin.DeactivateSleepingBotState.Value;
            cfg["keepFighting"] = Plugin.KeepFightingBotsAwake.Value;
            cfg["drainInUpdateOnly"] = Plugin.DrainInUpdateOnly.Value;
            cfg["drainDiagnostics"] = Plugin.AsyncDrainDiagnostics.Value;
            cfg["sleepDistance"] = Plugin.SleepDistance.Value;
            cfg["wakeDistance"] = Plugin.WakeDistance.Value;
            cfg["roleSleepDist"] = Patches.RoleSleepDistance.Effective;
            cfg["roleWakeDist"] = Patches.RoleSleepDistance.EffectiveWake;
            cfg["bossGroupWake"] = Plugin.KeepBossGroupsAwake.Value;
            cfg["forceAllRoles"] = Plugin.ForceStandByForAllRoles.Value;
            cfg["checkInterval"] = Plugin.CheckInterval.Value;
            cfg["sleepImmediately"] = Plugin.SleepImmediately.Value;
            cfg["minBrainsPerFrame"] = Plugin.MinBrainsPerFrame.Value;
            GcControl.AppendCfgTo(cfg);
            obj["cfg"] = cfg;

            GcControl.AppendWindowTo(obj);

            // gcSuspended/worstCallbacks: both read AsyncDrain directly, same bucket as every
            // other shipping-class read in this method. Found missing here during the capstone
            // cutover session (2026-08-19) - Ranger's Telemetry.cs (already committed) has a
            // comment claiming these "moved into Framesaver's registered window callback" but
            // this method never actually contained them until now. AsyncDrain.PublishTelemetry()
            // (the separate, additive bus-publish half - GcSuspended/WorstCallbackMs/
            // WorstCallbackName as Events) is unaffected and keeps running from AsyncDrain's own
            // code; this is the OTHER relationship, Telemetry reading AsyncDrain's state directly
            // for its own NDJSON fields, same distinction the rest of this method's doc comments
            // draw for the other 8 shipping classes.
            obj["gcSuspended"] = Patches.AsyncDrain.GcSuspended;
            JArray worstCallbacks = new JArray();
            Patches.AsyncDrain.AppendTopTo(worstCallbacks);
            obj["worstCallbacks"] = worstCallbacks;
        }

        /// <summary>
        /// Registered once at Framesaver's Awake via RangerBridge.RegisterCapstoneCallbacks.
        /// Builds the per-collection GC-suspend diagnostic (gcSuspendsBefore/gcMsSinceSuspend),
        /// emitted only on spike lines that carry a completed collection - see GcControl's own
        /// doc comment on AppendSpike for the full reasoning.
        /// </summary>
        internal static void BuildSpike(JObject obj)
        {
            GcControl.AppendSpikeTo(obj);
        }

        /// <summary>
        /// Registered once at Framesaver's Awake via RangerBridge.RegisterCapstoneCallbacks.
        /// Zeroes GcControl's window-scoped drive counters (calls/pending/msTotal/msMax) at
        /// the same boundary Telemetry.cs zeroes its own - without this they carry over and
        /// every window's gcDrive block after the first double-counts.
        /// </summary>
        internal static void ResetWindow()
        {
            GcControl.ResetWindow();
        }
    }
}
