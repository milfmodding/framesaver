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
            // Also stand down when another mod owns pausing. These two fields are what vanilla's own
            // BotStandBy.Update measures against, so leaving our 150/130 in place while not running our
            // Update replacement would have vanilla sleeping bots at our distances using its bot-to-bot
            // measure - the exact combination this mod exists to avoid.
            if (!Plugin.StandByEnabled.Value || ModCompat.SuppressStandBy)
            {
                return;
            }

            __instance.DIST_TO_SLEEP = Plugin.SleepDistance.Value;
            __instance.DIST_TO_ACTIVATE = Plugin.WakeDistance.Value;

            // Roles that engage from a fixed post sleep through their own
            // fight at the global distance. Widening it here rather than
            // exempting the role is what keeps the cost bounded - a bot past
            // the wider distance still sleeps. See RoleSleepDistance.
            float roleSleep = RoleSleepDistance.For(__instance.BotOwner_0);
            if (roleSleep > 0f)
            {
                __instance.DIST_TO_SLEEP = roleSleep;
                __instance.DIST_TO_ACTIVATE = RoleSleepDistance.WakeFor(roleSleep);
            }

            // InitPoints clears CanDoStandBy when the role's Mind.CAN_STAND_BY is
            // false, or when either distance is under 5m. Re-enabling it here is
            // what lets those roles sleep - roughly half of them, and every PMC
            // among them, not just the bosses and guards this used to say.
            if (Plugin.ForceStandByForAllRoles.Value)
            {
                __instance.CanDoStandBy = true;
            }
        }
    }
}
