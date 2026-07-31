using System;
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

            if (Plugin.CullSleepingBotAnimators.Value && !Inert)
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
        /// True when the game is running BSG's fast body animator, under which
        /// writing cullingMode is a no-op - so the cull is switched off rather
        /// than left to burn a write per sleeping bot per frame for nothing.
        ///
        /// This is the READ-ONLY half of a setting that used to force that
        /// animator on. The write path is gone: it breaks the game. But
        /// UseBodyFastAnimator still exists and another mod or a hand-edited
        /// client.config.json can set it, and if that ever happens the cull -
        /// this mod's largest single saving - is silently inert while
        /// `animCulled` still reports full success. A deleted footgun where a
        /// compatibility hole remains is worth a guard.
        /// </summary>
        internal static bool Inert;

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

        /// <summary>
        /// Of the bots we marked, how many Unity is ACTUALLY culling - the
        /// ones off screen. `CulledLastFrame` counts what we asked for; this
        /// counts what the engine honoured, and nobody has measured the
        /// difference. **Read them as a pair**: the ratio is the fraction of
        /// the feature that is real, and if it is small then the saving is
        /// smaller than every number we have quoted for it.
        ///
        /// **`Player.OnScreen` is the right predicate. `IsVisibleToCamera`
        /// would have been a disaster.** OnScreen resolves through
        /// PlayerBody.IsVisible() and LoddedSkin.IsVisible() to
        /// `SkinnedMeshRenderer.isVisible` over the body LODs - Unity's own
        /// renderer visibility flag, which is the state
        /// AnimatorCullingMode.CullCompletely keys off. Same flag, so the
        /// predicate matches the mechanism; and the worry about a shadow cast
        /// into frustum counting as visible applies to both sides equally, so
        /// it cancels rather than biasing.
        ///
        /// `IsVisibleToCamera` is `{ get; set; } = true` on Player with **no
        /// assignment anywhere in Assembly-CSharp**, and a getter-only
        /// constant `= true` on BotOwner and GamePerson. It is a networking
        /// hook. Reading it would have made this equal CulledLastFrame in
        /// every window - "the engine honours 100% of our marking", the most
        /// flattering false answer available about a shipped feature.
        ///
        /// Computed here rather than counted in ApplyIfSleeping, which runs
        /// from VisualPass, the LateUpdate skip and the world-tick skip -
        /// counting invocations there double-counted once already. One pass
        /// per read, two LOD walks per sleeping bot, once a window.
        /// </summary>
        public static int CulledOffScreen
        {
            get
            {
                if (!Plugin.CullSleepingBotAnimators.Value)
                {
                    return 0;
                }

                int offScreen = 0;
                foreach (KeyValuePair<Player, BotStandBy> entry in Sleeping)
                {
                    Player player = entry.Key;
                    if (player == null)
                    {
                        continue;
                    }

                    try
                    {
                        if (!player.OnScreen)
                        {
                            offScreen++;
                        }
                    }
                    catch (Exception)
                    {
                        // A body mid-teardown must not take the window's
                        // telemetry with it. Undercounts rather than
                        // misclassifies - same as CountBots dropping a null
                        // StandBy.
                    }
                }

                return offScreen;
            }
        }

        /// <summary>
        /// Of the bots we marked, how many carry CullCompletely on an animator
        /// that can actually honour it.
        ///
        /// **Deliberately not gated on the config flag, unlike the two above.**
        /// That asymmetry is the whole point. `CulledLastFrame` reports what we
        /// asked for, so switching the cull off drops it to 0 on the very next
        /// window - while the engine keeps culling every bot that was already
        /// asleep, because our own LateUpdate skip suppresses Player.VisualPass
        /// (its ONLY call site, Player.cs:1565) and VisualPass is the thing
        /// that would have rewritten cullingMode. A latched arm and a clean arm
        /// are otherwise byte-identical in the log, which is the worst possible
        /// property for the instrument guarding the mod's main mechanism.
        ///
        /// **A plain read-back of cullingMode would NOT have been enough**, and
        /// this is the trap worth spelling out. On BSG's
        /// FastAnimatorProcessorClass `cullingMode` is `{ get; set; }` with no
        /// reader anywhere in the class - so the write does nothing AND the
        /// value round-trips, and a read-back would report full success for a
        /// feature doing literally nothing. Hence the type test: ask whether
        /// the write can land before believing what it reads back.
        ///
        /// Read as a triple with the two above: asked / honoured / off screen.
        /// </summary>
        public static int CulledEngine
        {
            get
            {
                int culled = 0;
                foreach (KeyValuePair<Player, BotStandBy> entry in Sleeping)
                {
                    Player player = entry.Key;
                    if (player == null)
                    {
                        continue;
                    }

                    try
                    {
                        IAnimator body = player.BodyAnimatorCommon;
                        if (body != null && WriteReachesUnity(body.GetType())
                            && body.cullingMode == AnimatorCullingMode.CullCompletely)
                        {
                            culled++;
                        }
                    }
                    catch (Exception)
                    {
                        // Same rule as CulledOffScreen: a body mid-teardown
                        // undercounts rather than misclassifies.
                    }
                }

                return culled;
            }
        }

        /// <summary>
        /// Whether writing cullingMode on this animator reaches Unity at all.
        ///
        /// False only for FastAnimatorProcessorClass, which
        /// Player.CreateBodyAnimator substitutes for Unity's Animator when
        /// UseBodyFastAnimator is set (Player.cs:4661). It is not a Unity
        /// Animator and its cullingMode is inert, so the whole animator cull
        /// becomes a no-op under it. Framesaver no longer offers to turn that
        /// flag on - it breaks the game - so this is purely about detecting
        /// something else having done so. See DetectInertAnimator.
        ///
        /// Takes a Type rather than the instance so it can be tested against
        /// both real types without a Unity host to construct one in.
        /// </summary>
        internal static bool WriteReachesUnity(Type animator)
        {
            return animator != null && !typeof(FastAnimatorProcessorClass).IsAssignableFrom(animator);
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
            DetectInertAnimator();
        }

        /// <summary>
        /// Sets <see cref="Inert"/> from the game's own config, once per raid.
        ///
        /// Here rather than in a patch of its own, because a per-raid reset
        /// already runs here and the config is certainly loaded by now - so the
        /// check costs no hook at all. Once per raid also puts the error in the
        /// log of the raid it spoiled, which is where someone reading back will
        /// look for it.
        /// </summary>
        private static void DetectInertAnimator()
        {
            bool wasInert = Inert;
            Inert = false;

            try
            {
                ApplicationConfigClass config = BackendConfigAbstractClass.Config;
                Inert = config != null && config.UseBodyFastAnimator;
            }
            catch (Exception)
            {
                // Cannot read it, so do not claim it. Leaving Inert false keeps
                // the cull running; CulledEngine reads the engine and will
                // disagree with animCulled if the write is landing nowhere.
            }

            if (Inert && !wasInert)
            {
                Plugin.LogSource.LogError(
                    "Framesaver: UseBodyFastAnimator is ON, so animator culling cannot work - "
                    + "cullingMode is inert on BSG's fast animator. The sleeping-bot cull is "
                    + "DISABLED for this raid. Something other than Framesaver set that flag.");
            }
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
            bool paused = value == BotStandByType.paused;
            SleepingBotAnimatorPatch.SetSleeping(__instance, paused);

            // Awake-age spans are driven from HERE rather than from our own
            // Wake/GoToSleep, because this hook sees every transition whatever
            // caused it. A bot paused or woken by BotsPatrolGeneratorGameEvent,
            // by BotLeaveData or by another mod would otherwise keep a stale
            // stamp and report an age spanning a sleep it did take - which is
            // precisely the frozen-accumulator reading the raid's registered
            // second branch would be mistaken for.
            //
            // AwakeAge.Woke is add-if-absent, so the un-paused values that are
            // not wakes - active to goToSave and back - leave a running span
            // alone.
            BotOwner owner = __instance != null ? __instance.BotOwner_0 : null;
            if (paused)
            {
                AwakeAge.Ended(owner);
            }
            else
            {
                AwakeAge.Woke(owner);
            }
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
