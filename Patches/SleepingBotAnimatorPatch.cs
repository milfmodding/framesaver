using System.Collections.Generic;
using System.Reflection;
using EFT;
using HarmonyLib;
using SPT.Reflection.Patching;
using UnityEngine;

namespace Framesaver.Patches
{
    /// <summary>
    /// Fully culls the animator of bots that are asleep.
    ///
    /// EFTHardSettings.AnimatorCullDistance is 10m, so Player.VisualPass puts essentially every bot into
    /// AnimatorCullingMode.CullUpdateTransforms - which skips retarget, IK and transform writes while the
    /// renderers are off screen, but still evaluates the state machine every frame. CullCompletely skips
    /// evaluation entirely.
    ///
    /// Restricting this to BotStandByType.paused is what makes it safe: those bots have already had
    /// SetPose(0f) and are not moving, so there is no root motion to lose while culled. Applying it to awake
    /// bots would risk freezing anything that depends on animation progressing off screen.
    ///
    /// Measured target: Unity's animation pass is ~3.19ms of a ~12.9ms frame with 20 bots. This recovers only
    /// the state-machine evaluation, and only for bots that are asleep AND off screen, so expect noticeably
    /// less than that.
    /// </summary>
    internal class SleepingBotAnimatorPatch : ModulePatch
    {
        // Keyed by Player so VisualPass can answer "is this a sleeping bot" in O(1). Players are pooled and
        // recycled, so membership alone is not enough - see the ownership re-check in Postfix.
        private static readonly Dictionary<Player, BotStandBy> Sleeping = new Dictionary<Player, BotStandBy>();

        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(Player), nameof(Player.VisualPass));
        }

        [PatchPostfix]
        private static void Postfix(Player __instance)
        {
            ApplyIfSleeping(__instance);
        }

        /// <summary>
        /// True when this Player is a bot currently in BotStandByType.paused. Also applies the animator cull
        /// as a side effect when enabled.
        ///
        /// Both callers matter: VisualPass covers the normal path, and the LateUpdate skip below calls it too.
        /// Without that, skipping LateUpdate would also skip VisualPass - and therefore the cull - so the two
        /// features would quietly cancel each other out.
        /// </summary>
        internal static bool ApplyIfSleeping(Player player)
        {
            if (Sleeping.Count == 0 || player == null)
            {
                return false;
            }

            BotStandBy standBy;
            if (!Sleeping.TryGetValue(player, out standBy) || standBy == null)
            {
                return false;
            }

            // Guard against a pooled Player having been recycled onto a different bot since we recorded it.
            BotOwner owner = standBy.BotOwner_0;
            if (owner == null || owner.GetPlayer != player || standBy.StandByType_1 != BotStandByType.paused)
            {
                Sleeping.Remove(player);
                return false;
            }

            if (Plugin.CullSleepingBotAnimators.Value)
            {
                IAnimator body = player.BodyAnimatorCommon;
                if (body != null)
                {
                    body.cullingMode = AnimatorCullingMode.CullCompletely;
                }
            }

            return true;
        }

        /// <summary>
        /// Called from the stand-by state-change hook below. VisualPass rewrites cullingMode every frame, so
        /// simply dropping a bot from this set restores vanilla behaviour on the next frame - no need to undo
        /// anything, including when the config toggle is switched off mid-raid.
        /// </summary>
        internal static void SetSleeping(BotStandBy standBy, bool sleeping)
        {
            BotOwner owner = standBy != null ? standBy.BotOwner_0 : null;
            Player player = owner != null ? owner.GetPlayer : null;
            if (player == null)
            {
                return;
            }

            if (sleeping)
            {
                Sleeping[player] = standBy;
            }
            else
            {
                Sleeping.Remove(player);
            }
        }

        /// <summary>
        /// Bots whose animators are being culled. Counting invocations instead double-counted once the
        /// LateUpdate and world-tick skips began calling ApplyIfSleeping alongside VisualPass.
        /// </summary>
        public static int CulledLastFrame
        {
            get { return Plugin.CullSleepingBotAnimators.Value ? Sleeping.Count : 0; }
        }

        public static void ReadAndReset()
        {
        }

        /// <summary>
        /// Drops every tracked bot. Called once per raid start.
        ///
        /// Entries only leave <see cref="Sleeping"/> when a bot transitions out of paused, and nothing
        /// resets StandByType at raid teardown - BotOwner.Dispose tears down 25 subsystems and never
        /// touches StandBy. So a bot pooled while asleep keeps its entry for the rest of the session.
        ///
        /// Measured before this fix: animCulled equalled asleep in every window of raid 1, then
        /// asleep + 15 in every window of raid 2 - the offset being raid 1's final sleeping count,
        /// carried over and never drained. Each raid adds its own, so it accumulates.
        ///
        /// The entry also retains the Player, the BotStandBy, and through BotStandBy.BotOwner_0 the
        /// whole disposed bot graph - the same leak shape as AICoreControllerClass.HashSet_1, which
        /// this mod exists to fix.
        /// </summary>
        internal static void ResetForRaid()
        {
            Sleeping.Clear();
        }
    }

    /// <summary>
    /// Tracks every stand-by state transition, whatever caused it - our own Update replacement, BotLeaveData,
    /// BotsPatrolGeneratorGameEvent, or a hit waking the bot up.
    /// </summary>
    internal class BotStandByStateChangePatch : ModulePatch
    {
        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.PropertySetter(typeof(BotStandBy), nameof(BotStandBy.StandByType));
        }

        [PatchPostfix]
        private static void Postfix(BotStandBy __instance, BotStandByType value)
        {
            SleepingBotAnimatorPatch.SetSleeping(__instance, value == BotStandByType.paused);
        }
    }

    /// <summary>
    /// Skips Player.LateUpdate entirely for sleeping bots.
    ///
    /// LateUpdate drives MovementContext.AnimatorStatesLateUpdate, Physical.LateUpdate, VisualPass and the
    /// beacon/tripwire placers. A paused bot is stationary and posed, so none of it should be observable -
    /// but this is the riskiest of the three changes, hence its own flag. If bots come back from sleep in a
    /// wrong pose or with stale visuals, this is the one to turn off first.
    /// </summary>
    internal class SkipSleepingPlayerLateUpdatePatch : ModulePatch
    {
        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(Player), nameof(Player.LateUpdate));
        }

        [PatchPrefix]
        private static bool Prefix(Player __instance)
        {
            if (!Plugin.SkipSleepingLateUpdate.Value)
            {
                return true;
            }

            // Applies the animator cull before bailing, since VisualPass will not get a chance to.
            return !SleepingBotAnimatorPatch.ApplyIfSleeping(__instance);
        }
    }

    /// <summary>
    /// Skips the per-Player world tick (Player.UpdateTick / FixedUpdateTick) for sleeping bots.
    ///
    /// GameWorld.PlayerTick walks every Player through this every frame and measured 0.78-0.99ms with 34-36
    /// bots. Separate flag from the LateUpdate skip because the failure modes differ: this one could stall
    /// health effects or leave movement state stale across a sleep, rather than affecting visuals.
    /// </summary>
    internal class SkipSleepingWorldTickPatch : ModulePatch
    {
        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(GameWorld), "smethod_2");
        }

        [PatchPrefix]
        private static bool Prefix(Player player)
        {
            if (!Plugin.SkipSleepingWorldTick.Value)
            {
                return true;
            }

            return !SleepingBotAnimatorPatch.ApplyIfSleeping(player);
        }
    }
}
