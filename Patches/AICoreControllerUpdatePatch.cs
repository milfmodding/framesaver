using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using HarmonyLib;
using SPT.Reflection.Patching;
using UnityEngine;

namespace Framesaver.Patches
{
    /// <summary>
    /// Replaces AICoreController.Update, which drives every bot brain from BotsController.method_0 (itself
    /// subscribed to BaseLocalGame's per-frame UpdateByUnity event).
    ///
    /// Two problems with the original:
    ///
    /// 1. Leak. _listToDel is the pending-removal set. Update drains it into _listAgents.Remove every frame but
    ///    never clears it, and Clear() clears _listAgents and _listOfErrors while skipping it. (4.1 IL
    ///    re-verified 2026-08-16: identical shape.) Every disposed agent
    ///    is therefore re-walked for the rest of the raid, and - the bigger cost - stays strongly referenced,
    ///    keeping each dead bot's strategy, layers, node dictionary and GameObject alive.
    ///
    /// 2. No budget. Every agent thinks every frame, with no round-robin and no cap. That is the path to the
    ///    recursive cover search (GClass381.GetCover -> method_6, up to MAX_POINS_CHECK_TOTAL=500 point checks
    ///    and MAX_POINS_CHECK_RAY=100 raycasts per search, synchronously, main thread).
    ///
    /// The slicing here mirrors the shape of AITaskManager.Class284.UpdateGroup, which is the game's own
    /// load-adaptive round-robin - registered, in stock EFT, for exactly one task group (LookSensor).
    /// </summary>
    internal class AICoreControllerUpdatePatch : ModulePatch
    {
        // Reused across frames; snapshotting also avoids the collection-modified exception vanilla is exposed
        // to when an agent disposes itself mid-iteration.
        private static readonly List<AICoreAgentBase> Snapshot = new List<AICoreAgentBase>(256);
        private static int _cursor;

        /// <summary>Agents in _listAgents as of the last tick.</summary>
        public static int LiveAgents;

        /// <summary>
        /// Size of _listToDel as observed this tick. With the leak fix off this climbs monotonically for the
        /// whole raid, which is the leak measured directly.
        /// </summary>
        public static int PendingRemoval;

        /// <summary>Cumulative agents drained out of _listToDel since load.</summary>
        public static int RemovedTotal;

        /// <summary>Brains actually ticked on the last frame - confirms slicing is doing what it claims.</summary>
        public static int LastBrainsTicked;

        /// <summary>
        /// Ranger extraction (2026-08-16/17): publish-side addition, ADDITIVE, does not change any
        /// of the four counters above. Routed through RangerBridge rather than calling
        /// Ranger.TelemetryBus directly - see RangerBridge.cs and RoleSleepDistance.PublishTelemetry()
        /// for why. Called once per window from Telemetry.cs's Flush(), matching the existing
        /// once-per-window reads of these same four fields there.
        /// </summary>
        internal static void PublishTelemetry()
        {
            if (!RangerBridge.Present)
            {
                return;
            }

            RangerBridge.PublishAICoreController(LiveAgents, PendingRemoval, RemovedTotal, LastBrainsTicked);
        }

        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(AICoreController), nameof(AICoreController.Update));
        }

        [PatchPrefix]
        private static bool Prefix(AICoreController __instance)
        {
            return Run(__instance);
        }

        private static bool Run(AICoreController __instance)
        {
            bool slice = Plugin.BrainUpdatePeriod.Value > 0f && !ModCompat.SuppressSlicing;

            // With every option off this replacement is behaviourally identical to vanilla, so it is still
            // worth running when telemetry is on: it is the only way to observe _listToDel growing during a
            // baseline capture. Only bow out entirely when nothing at all wants us here.
            if (!Plugin.FixAgentLeak.Value && !slice && !Plugin.TelemetryEnabled.Value)
            {
                return true;
            }

            if (!__instance._enable)
            {
                return false; // controller stopped, same as vanilla
            }

            PendingRemoval = __instance._listToDel.Count;

            if (PendingRemoval > 0)
            {
                foreach (AICoreAgentBase removed in __instance._listToDel)
                {
                    __instance._listAgents.Remove(removed);
                }

                if (Plugin.FixAgentLeak.Value)
                {
                    RemovedTotal += PendingRemoval;
                    __instance._listToDel.Clear();
                }
            }

            LiveAgents = __instance._listAgents.Count;

            if (!slice)
            {
                foreach (AICoreAgentBase agent in __instance._listAgents)
                {
                    SafeUpdate(agent, __instance);
                }

                LastBrainsTicked = LiveAgents;
                return false;
            }

            Snapshot.Clear();
            Snapshot.AddRange(__instance._listAgents);

            int count = Snapshot.Count;
            if (count == 0)
            {
                _cursor = 0;
                LastBrainsTicked = 0;
                return false;
            }

            int perFrame = count;
            float delta = Time.deltaTime;
            if (delta > 0f)
            {
                float framesPerPass = Plugin.BrainUpdatePeriod.Value / delta;
                if (framesPerPass > 1f)
                {
                    perFrame = Mathf.CeilToInt(count / framesPerPass);
                }
            }

            perFrame = Mathf.Clamp(perFrame, Mathf.Min(Plugin.MinBrainsPerFrame.Value, count), count);

            for (int i = 0; i < perFrame; i++)
            {
                if (_cursor >= count)
                {
                    _cursor = 0;
                }

                SafeUpdate(Snapshot[_cursor], __instance);
                _cursor++;
            }

            LastBrainsTicked = perFrame;
            Snapshot.Clear(); // don't hold agent references between frames
            return false;
        }

        /// <summary>
        /// Mirrors vanilla's per-agent swallow, including its cap of 10 distinct offenders, but logs the first
        /// few instead of discarding them silently.
        /// </summary>
        private static void SafeUpdate(AICoreAgentBase agent, AICoreController controller)
        {
            try
            {
                agent.Update();
            }
            catch (Exception e)
            {
                if (!controller._listOfErrors.Contains(agent) && controller._errorsPrinted < 10)
                {
                    controller._listOfErrors.Add(agent);
                    controller._errorsPrinted++;
                    Plugin.LogSource.LogError("Framesaver: bot brain update threw - " + e);
                }
            }
        }
    }
}
