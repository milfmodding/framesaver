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
    /// Replaces AICoreControllerClass.Update, which drives every bot brain from BotsController.method_0 (itself
    /// subscribed to BaseLocalGame's per-frame UpdateByUnity event).
    ///
    /// Two problems with the original:
    ///
    /// 1. Leak. HashSet_1 is the pending-removal set. Update drains it into HashSet_0.Remove every frame but
    ///    never clears it, and method_0 clears HashSet_0 and HashSet_2 while skipping it. Every disposed agent
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
        private static readonly List<GClass32> Snapshot = new List<GClass32>(256);
        private static int _cursor;

        /// <summary>Agents in HashSet_0 as of the last tick.</summary>
        public static int LiveAgents;

        /// <summary>
        /// Size of HashSet_1 as observed this tick. With the leak fix off this climbs monotonically for the
        /// whole raid, which is the leak measured directly.
        /// </summary>
        public static int PendingRemoval;

        /// <summary>Cumulative agents drained out of HashSet_1 since load.</summary>
        public static int RemovedTotal;

        /// <summary>Brains actually ticked on the last frame - confirms slicing is doing what it claims.</summary>
        public static int LastBrainsTicked;

        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(AICoreControllerClass), nameof(AICoreControllerClass.Update));
        }

        [PatchPrefix]
        private static bool Prefix(AICoreControllerClass __instance)
        {
            return Run(__instance);
        }

        private static bool Run(AICoreControllerClass __instance)
        {
            bool slice = Plugin.BrainUpdatePeriod.Value > 0f && !ModCompat.SuppressSlicing;

            // With every option off this replacement is behaviourally identical to vanilla, so it is still
            // worth running when telemetry is on: it is the only way to observe HashSet_1 growing during a
            // baseline capture. Only bow out entirely when nothing at all wants us here.
            if (!Plugin.FixAgentLeak.Value && !slice && !Plugin.TelemetryEnabled.Value)
            {
                return true;
            }

            if (!__instance.Bool_0)
            {
                return false; // controller stopped, same as vanilla
            }

            PendingRemoval = __instance.HashSet_1.Count;

            if (PendingRemoval > 0)
            {
                foreach (GClass32 removed in __instance.HashSet_1)
                {
                    __instance.HashSet_0.Remove(removed);
                }

                if (Plugin.FixAgentLeak.Value)
                {
                    RemovedTotal += PendingRemoval;
                    __instance.HashSet_1.Clear();
                }
            }

            LiveAgents = __instance.HashSet_0.Count;

            if (!slice)
            {
                foreach (GClass32 agent in __instance.HashSet_0)
                {
                    SafeUpdate(agent, __instance);
                }

                LastBrainsTicked = LiveAgents;
                return false;
            }

            Snapshot.Clear();
            Snapshot.AddRange(__instance.HashSet_0);

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
        private static void SafeUpdate(GClass32 agent, AICoreControllerClass controller)
        {
            try
            {
                agent.Update();
            }
            catch (Exception e)
            {
                if (!controller.HashSet_2.Contains(agent) && controller.Int_0 < 10)
                {
                    controller.HashSet_2.Add(agent);
                    controller.Int_0++;
                    Plugin.LogSource.LogError("Framesaver: bot brain update threw - " + e);
                }
            }
        }
    }
}
