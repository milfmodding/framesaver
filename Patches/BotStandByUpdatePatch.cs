using System.Collections.Generic;
using System.Reflection;
using Comfort.Common;
using EFT;
using HarmonyLib;
using SPT.Reflection.Patching;
using UnityEngine;

namespace Framesaver.Patches
{
    /// <summary>
    /// Replaces BotStandBy.Update.
    ///
    /// Vanilla walks EnemiesController.EnemyInfos and BotsGroup.Neutrals every 10s and takes the nearest
    /// distance. In SPT that set is mostly other bots, so a cluster of AI keeps itself awake indefinitely even
    /// with the player on the far side of the map, and the 240m threshold covers most of a map anyway. The
    /// result is that the stand-by system - the only gate on the 22 subsystem ticks in BotOwner.UpdateManual -
    /// effectively never fires.
    ///
    /// This measures distance to human players only.
    ///
    /// Scope note: pausing a bot skips the ManualUpdate block, and nothing else. The brain
    /// (AICoreControllerClass -> AICoreAgentClass.Update -> cover search) does not consult stand-by state at
    /// all, so it keeps running for sleeping bots. See AICoreControllerUpdatePatch for that half.
    /// </summary>
    /// <summary>
    /// Keeps the stand-by check alive for bots dropped to EBotState.NonActive.
    ///
    /// BotOwner.UpdateManual puts StandBy.Update() *inside* its `BotState == Active` guard:
    ///
    ///     if (BotState == EBotState.Active &amp;&amp; GetPlayer.HealthController.IsAlive) {
    ///         StandBy.Update();                                  // the wake check
    ///         if (StandBy.StandByType != paused) { ...22 ticks... }
    ///     }
    ///
    /// So setting a paused bot NonActive stops its own wake check from ever running again - sleep becomes a
    /// one-way door. The bot cannot wake by distance, and cannot wake from being shot either, because
    /// BotStandBy.GetHit only sets a timer that Update would have read. It stands frozen for the rest of
    /// the raid.
    ///
    /// BotsClass.UpdateByUnity iterates every bot without filtering on BotState, so this prefix still runs
    /// and can drive the check by hand. Vanilla's body does nothing at all for a NonActive bot, so skipping
    /// it costs nothing beyond the call we add back.
    ///
    /// AILimit sets the same flag without hitting this, because it drives wake-ups from its own
    /// MonoBehaviour sweep rather than relying on the game to keep ticking stand-by. Copying the flag
    /// without also owning the wake path is what broke.
    /// </summary>
    internal class SleepingBotStandByPumpPatch : ModulePatch
    {
        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(BotOwner), nameof(BotOwner.UpdateManual));
        }

        [PatchPrefix]
        private static bool Prefix(BotOwner __instance)
        {
            if (!Plugin.DeactivateSleepingBotState.Value || ModCompat.SuppressStandBy)
            {
                return true;
            }

            // NonActive *and* paused is our own signature. A bot NonActive for any other reason - the
            // game's own activation flow, or another mod - is left entirely alone.
            if (__instance.BotState != EBotState.NonActive
                || __instance.StandBy == null
                || __instance.StandBy.StandByType_1 != BotStandByType.paused)
            {
                return true;
            }

            Player player = __instance.GetPlayer;
            if (player == null || player.HealthController == null || !player.HealthController.IsAlive)
            {
                return true;
            }

            // Our replacement, which restores BotState via Wake() when the bot should no longer be asleep.
            __instance.StandBy.Update();
            return false;
        }
    }

    internal class BotStandByUpdatePatch : ModulePatch
    {
        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(BotStandBy), nameof(BotStandBy.Update));
        }

        [PatchPrefix]
        private static bool Prefix(BotStandBy __instance)
        {
            if (!Plugin.StandByEnabled.Value || ModCompat.SuppressStandBy)
            {
                return true; // fall through to vanilla
            }

            // Same field the game uses, so BotStandBy.GetHit's 30s post-damage grace period still applies.
            if (Time.time < __instance.NextCheckTime)
            {
                return false;
            }

            __instance.NextCheckTime = Time.time + Plugin.CheckInterval.Value;

            BotOwner bot = __instance.BotOwner_0;
            if (bot == null)
            {
                return false;
            }

            // Normally respects BotsPatrolGeneratorGameEvent, which toggles this at runtime for scripted
            // events - but QuestingBots also clears it on every bot, which switches this whole system off.
            if (!__instance.CanDoStandBy && !TryReclaimStandBy(__instance, bot))
            {
                return false;
            }

            if (Plugin.KeepFightingBotsAwake.Value && bot.Memory != null && bot.Memory.GoalEnemy != null)
            {
                Wake(__instance, bot);
                return false;
            }

            // Long-range roles are the one case where distance is the wrong proxy for "can this bot affect
            // the player". A sniper scav is placed specifically to engage from beyond any sensible sleep
            // distance, so a pure distance rule guarantees it never fires a shot. Keeping the nearest few
            // awake regardless of range restores them at a bounded cost.
            if (LongRangeExemption.IsExempt(bot))
            {
                Wake(__instance, bot);
                return false;
            }

            float distance = DistanceToNearestHuman(bot.Position);

            if (__instance.StandByType_1 == BotStandByType.active)
            {
                if (distance > __instance.DIST_TO_SLEEP)
                {
                    GoToSleep(__instance, bot);
                }
            }
            else if (distance < __instance.DIST_TO_ACTIVATE)
            {
                // Covers none / paused / goToSave, matching vanilla's enum arithmetic.
                Wake(__instance, bot);
            }

            return false;
        }

        /// <summary>
        /// Single wake path, so restoring BotState cannot be forgotten at one of the three call sites.
        ///
        /// BotState is restored unconditionally rather than behind the config flag: turning the option off
        /// mid-raid must let already-deactivated bots recover as they wake, instead of stranding them.
        /// </summary>
        private static void Wake(BotStandBy standBy, BotOwner bot)
        {
            if (standBy.StandByType_1 != BotStandByType.active)
            {
                standBy.Activate();
            }

            if (bot.BotState == EBotState.NonActive)
            {
                bot.BotState = EBotState.Active;
            }
        }

        /// <summary>
        /// Takes back the CanDoStandBy flag that QuestingBots clears on every bot as it activates
        /// (BotOwnerBrainActivatePatch, "Fix for bots getting stuck in Standby when enemy PMC's are near").
        ///
        /// That workaround targets a flaw in *vanilla's* check, which measures distance to the nearest enemy
        /// or neutral - mostly other bots in SPT, which is why a bot could end up parked. This replacement
        /// measures distance to humans only and refuses to sleep a bot holding a goal enemy, so the stuck
        /// state it defends against cannot arise here. Left alone, its flag costs the entire stand-by
        /// system: measured on Streets as 20-27 bots awake for a full raid and p50 roughly doubled.
        ///
        /// Only reclaims for roles the bot's own settings already permit, so the 30 roles of 57 whose
        /// Mind.CAN_STAND_BY is false stay exempt exactly as InitPoints intended. That set is far wider
        /// than the bosses it is easy to picture - every PMC is in it - so "exempt" is a large fraction
        /// of a live roster rather than a handful of scripted characters.
        ///
        /// Caveat: this cannot tell QuestingBots' flag apart from one cleared by BotsPatrolGeneratorGameEvent
        /// for a scripted patrol, so with this on such an event would be overridden within one check
        /// interval. Rare enough to accept against a doubling of frame time, and the toggle exists for
        /// anyone who hits it.
        /// </summary>
        private static bool TryReclaimStandBy(BotStandBy standBy, BotOwner bot)
        {
            if (!Plugin.ReclaimStandBy.Value || !ModCompat.ClearsStandByFlag)
            {
                return false;
            }

            if (!Plugin.ForceStandByForAllRoles.Value && !RoleAllowsStandBy(bot))
            {
                return false;
            }

            standBy.CanDoStandBy = true;
            return true;
        }

        /// <summary>The role's own setting, which is what InitPoints consults before clearing the flag.</summary>
        private static bool RoleAllowsStandBy(BotOwner bot)
        {
            return bot.Settings != null
                   && bot.Settings.FileSettings != null
                   && bot.Settings.FileSettings.Mind != null
                   && bot.Settings.FileSettings.Mind.CAN_STAND_BY;
        }

        /// <summary>Exposed for LongRangeExemption, which ranks snipers by the same measure.</summary>
        internal static float DistanceToNearestHumanPublic(Vector3 botPosition)
        {
            return DistanceToNearestHuman(botPosition);
        }

        /// <summary>
        /// Returns 0 when no live human reference point exists, so an uninitialised or post-death world never
        /// mass-sleeps the bots.
        /// </summary>
        private static float DistanceToNearestHuman(Vector3 botPosition)
        {
            GameWorld world = Singleton<GameWorld>.Instance;
            if (world == null)
            {
                return 0f;
            }

            // A Fika headless host still constructs a real LocalPlayer - CoopGame.CreateLocalPlayer runs
            // unconditionally and only renames the profile to "headless_*" - so MainPlayer is a body parked
            // at a spawn point for the whole raid with IsAI false. Counting it would hold a permanent awake
            // bubble around that spawn while the actual players are elsewhere on the map.
            bool headless = ModCompat.IsFikaHeadlessHost;

            float nearest = float.MaxValue;
            Player main = world.MainPlayer;

            if (!headless && IsLiveHuman(main))
            {
                nearest = Vector3.Distance(main.Position, botPosition);
            }

            // On a headless host the remote sweep is the only source of humans, so it cannot be optional.
            if (Plugin.IncludeAllHumanPlayers.Value || headless)
            {
                List<Player> alive = world.AllAlivePlayersList;
                if (alive != null)
                {
                    for (int i = 0; i < alive.Count; i++)
                    {
                        Player player = alive[i];

                        // main is already accounted for above, or deliberately excluded when headless.
                        if (player == main || !IsLiveHuman(player))
                        {
                            continue;
                        }

                        float distance = Vector3.Distance(player.Position, botPosition);
                        if (distance < nearest)
                        {
                            nearest = distance;
                        }
                    }
                }
            }

            return nearest == float.MaxValue ? 0f : nearest;
        }

        private static bool IsLiveHuman(Player player)
        {
            return player != null
                   && !player.IsAI
                   && player.HealthController != null
                   && player.HealthController.IsAlive;
        }

        private static void GoToSleep(BotStandBy standBy, BotOwner bot)
        {
            if (!Plugin.SleepImmediately.Value)
            {
                // Vanilla route: enter goToSave, pathfind to the nearest cover point, sleep on arrival.
                standBy.method_0();
                return;
            }

            if (standBy.StandByType_1 == BotStandByType.paused)
            {
                return;
            }

            // Vanilla's method_0/method_1 both refuse to sleep a bot that still needs first aid. Keep that.
            if (bot.Medecine != null && bot.Medecine.FirstAid != null && bot.Medecine.FirstAid.Have2Do)
            {
                return;
            }

            // Deliberately not calling method_1(): it re-checks Mind.CAN_STAND_BY, which would undo the
            // "Force for all roles" option. CanDoStandBy was already validated by the caller.
            standBy.CurPoint = null;
            standBy.StandByType = BotStandByType.paused;

            if (bot.Mover != null)
            {
                bot.Mover.SetPose(0f);
            }

            // Player.Sleep is a virtual no-op in this build, but call it anyway so the state stays consistent
            // if BSG ever gives it a body.
            Player player = bot.GetPlayer;
            if (player != null)
            {
                player.Sleep(true);
            }

            Deactivate(bot);
        }

        /// <summary>
        /// Drops the bot to EBotState.NonActive, which is the flag SAIN, LootingBots and QuestingBots all
        /// gate their per-bot work on - none of them consult stand-by state, so without this they keep
        /// working on a bot we have paused. AILimit does the same thing for the same reason.
        ///
        /// Deliberately narrower than the pause itself. BotState is read in roughly 30 places in BSG's code,
        /// and two of them matter here: BotFollower requires a boss to be Active before a follower will
        /// attach to it, and BossSpawnerClass checks it while placing boss groups. Bosses and followers are
        /// therefore left Active whatever the setting says - a sleeping Reshala losing his guards would be a
        /// far worse bug than the frame time is worth.
        ///
        /// Note BotOwner.PostActivate promotes NonActive back to PreActive, so the game can pull a bot out
        /// of this state on its own. That is a reason to keep the option off by default rather than a
        /// correctness problem: the wake path restores Active regardless.
        /// </summary>
        private static void Deactivate(BotOwner bot)
        {
            if (!Plugin.DeactivateSleepingBotState.Value)
            {
                return;
            }

            if (bot.Profile == null || bot.Profile.Info == null || bot.Profile.Info.Settings == null)
            {
                return;
            }

            if (bot.Profile.Info.Settings.Role.IsBossOrFollower())
            {
                return;
            }

            if (bot.BotState == EBotState.Active)
            {
                bot.BotState = EBotState.NonActive;
            }
        }
    }
}
