using System.Reflection;
using HarmonyLib;
using SPT.Reflection.Patching;

namespace Framesaver.Patches
{
    /// <summary>
    /// BotOwner activation calls BotStandBy.InitPoints(zone.Modifier.DistToActivate, zone.Modifier.DistToSleep),
    /// which seeds DIST_TO_ACTIVATE / DIST_TO_SLEEP from BotLocationModifier (220 / 240 by default) and decides
    /// whether this bot may stand by at all.
    ///
    /// Overwriting the distances here rather than in the Update prefix keeps them visible to the game's own
    /// debug readouts (BotStandBy.DistancesInfo) and to anything else that reads the fields.
    /// </summary>
    internal class BotStandByInitPointsPatch : ModulePatch
    {
        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(BotStandBy), nameof(BotStandBy.InitPoints));
        }

        [PatchPostfix]
        private static void Postfix(BotStandBy __instance)
        {
            if (!ApplyDistances(__instance))
            {
                // Still logged. Standing down is a decision about this bot,
                // and an unlogged one is indistinguishable from a bot that
                // never activated.
                //
                // Capstone (2026-08-18): BotLog moved to Ranger with the rest of
                // Telemetry.cs's unit. Fully qualified rather than a bare `BotLog` -
                // this class stays in Framesaver, so the type is now cross-assembly.
                global::Ranger.Patches.BotLog.StandByAssigned(__instance, __instance._owner);
                return;
            }

            // InitPoints clears CanDoStandBy when the role's Mind.CAN_STAND_BY
            // is false, or when either distance is under 5m. Re-enabling it
            // here is what lets those roles sleep - roughly half of them, and
            // every PMC among them, not just the bosses and guards this used
            // to say.
            //
            // Not re-applied per check the way the distances are: reclaiming a
            // cleared flag is TryReclaimStandBy's job, and it refuses for roles
            // the database exempts. Forcing it from here every interval would
            // override BotsPatrolGeneratorGameEvent with no way to opt out.
            if (Plugin.ForceStandByForAllRoles.Value)
            {
                __instance.CanDoStandBy = true;
            }

            // Last, so the line records what this bot was actually granted
            // rather than what it was about to be. The grant never changes
            // afterwards - it is decided here, once, for the bot's whole life.
            global::Ranger.Patches.BotLog.StandByAssigned(__instance, __instance._owner);
        }

        /// <summary>
        /// Writes our sleep and wake distances onto a bot. Returns false when
        /// the stand-by system is standing down, so the caller can bail too.
        ///
        /// **Called per check interval as well as at activation, and that is
        /// the point.** `InitPoints` runs exactly once per bot, so a distance
        /// edited mid-raid used to reach only bots that activated afterwards -
        /// leaving a mixed population while `cfg.sleepDistance` and
        /// `cfg.roleSleepDist` both reported one uniform number. Those keys
        /// describe the SETTING; nothing describes what the bots on the field
        /// carry, and the two silently disagreed for the rest of the raid.
        /// Re-applying converges the population within one interval, which is
        /// a better answer than a caveat, and makes the distances armable from
        /// a protocol instead of quietly inert.
        ///
        /// Still written onto the fields rather than compared against config
        /// at the point of use, so the game's own debug readout
        /// (BotStandBy.DistancesInfo) and anything else reading them stay
        /// truthful.
        /// </summary>
        internal static bool ApplyDistances(BotStandBy standBy)
        {
            // Also stand down when another mod owns pausing. These two fields are what vanilla's own
            // BotStandBy.Update measures against, so leaving our 150/130 in place while not running our
            // Update replacement would have vanilla sleeping bots at our distances using its bot-to-bot
            // measure - the exact combination this mod exists to avoid.
            if (!Plugin.StandByEnabled.Value || ModCompat.SuppressStandBy)
            {
                return false;
            }

            standBy.DIST_TO_SLEEP = Plugin.SleepDistance.Value;
            standBy.DIST_TO_ACTIVATE = Plugin.WakeDistance.Value;

            // Roles that engage from a fixed post sleep through their own
            // fight at the global distance. Widening it here rather than
            // exempting the role is what keeps the cost bounded - a bot past
            // the wider distance still sleeps. See RoleSleepDistance.
            float roleSleep = RoleSleepDistance.For(standBy._owner);
            if (roleSleep > 0f)
            {
                standBy.DIST_TO_SLEEP = roleSleep;
                standBy.DIST_TO_ACTIVATE = RoleSleepDistance.WakeFor(roleSleep);
            }

            return true;
        }
    }
}
