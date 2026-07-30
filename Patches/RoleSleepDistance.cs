using System.Collections.Generic;
using EFT;

namespace Framesaver.Patches
{
    /// <summary>
    /// A longer sleep distance for roles that engage from where they stand.
    ///
    /// Distance to the player is a good proxy for "can this bot affect the
    /// player" for almost every role. It is wrong for a garrison. Zryachiy's
    /// men on the Lighthouse island, the Rogues at Water Treatment and the
    /// Boar snipers on Streets are placed to cover ground from a fixed post,
    /// so a 150m rule has them asleep through the engagement they exist to
    /// fight. Killa is listed for the mirror-image reason: what makes him a
    /// threat is arriving before you knew he was coming.
    ///
    /// **A distance, not an exemption, and that is the whole design.**
    /// LongRangeExemption keeps the N nearest marksmen awake at any range - a
    /// rank, so the cost is exactly N bots however many the map holds.
    /// Exempting a role has no such bound: every Rogue on Lighthouse would be
    /// awake for the whole raid, which is what the role is already doing today
    /// via CAN_STAND_BY. A wider distance keeps the bound, because a bot past
    /// it still sleeps, while giving the garrison the range it was placed for.
    ///
    /// marksman is deliberately absent. Rank already covers it, and giving it
    /// a distance too would change an arm the corpus has already measured.
    /// </summary>
    internal static class RoleSleepDistance
    {
        /// <summary>
        /// Verified against WildSpawnType, and against what the 4.0.13
        /// database actually spawns.
        ///
        /// followerGluharSnipe is in the enum and matches ten base.json files,
        /// but every match is inside
        /// BotLocationModifier.AdditionalHostilitySettings.AlwaysEnemies - a
        /// hostility target, never a spawn entry. It can never spawn, so it is
        /// not listed. A plain grep does not tell those two cases apart.
        /// </summary>
        private static readonly HashSet<WildSpawnType> Posted = new HashSet<WildSpawnType>
        {
            WildSpawnType.exUsec,
            WildSpawnType.bossZryachiy,
            WildSpawnType.followerZryachiy,
            WildSpawnType.bossBoarSniper,
            WildSpawnType.bossKojaniy,
            WildSpawnType.followerKojaniy,
            WildSpawnType.bossKilla,
            WildSpawnType.bossKillaAgro,
            WildSpawnType.sectantPriest,
            WildSpawnType.sectantWarrior,
            WildSpawnType.sectantOni,
            WildSpawnType.sectantPredvestnik,
            WildSpawnType.sectantPrizrak,
        };

        /// <summary>
        /// The sleep distance for this bot, or 0 when the normal one applies.
        ///
        /// **Only ever widens.** A configured value at or below the global
        /// sleep distance disables the rule rather than inverting it -
        /// otherwise setting it low would make exactly the roles that most
        /// need range sleep closer than everything else, which is the failure
        /// nobody would think to look for.
        /// </summary>
        internal static float For(BotOwner bot)
        {
            float distance = Effective;
            if (bot == null || distance <= 0f)
            {
                return 0f;
            }

            return Applies(RoleOf(bot)) ? distance : 0f;
        }

        /// <summary>
        /// The distance actually in force, or 0 when the rule is off.
        ///
        /// The guard lives here alone so the telemetry and the bots cannot
        /// disagree: a header or cfg block that read the raw config value
        /// would report 350m for a run where nothing applied it.
        /// </summary>
        internal static float Effective
        {
            get { return EffectiveFrom(Plugin.PostedRoleSleepDistance.Value, Plugin.SleepDistance.Value); }
        }

        /// <summary>
        /// The widen-only policy, split from the config read so it can be
        /// tested: the ConfigEntry statics do not exist outside BepInEx, and
        /// this is the half worth checking.
        /// </summary>
        internal static float EffectiveFrom(float configured, float globalSleep)
        {
            return configured > globalSleep ? configured : 0f;
        }

        /// <summary>
        /// Wake distance for the posted roles, preserving the configured
        /// hysteresis band so they thrash no more than any other bot. 0 when
        /// the rule is off, rather than a negative band offset.
        /// </summary>
        internal static float EffectiveWake
        {
            get
            {
                float distance = Effective;
                return distance > 0f ? WakeFor(distance) : 0f;
            }
        }

        internal static float WakeFor(float sleepDistance)
        {
            return WakeFrom(sleepDistance, Plugin.SleepDistance.Value, Plugin.WakeDistance.Value);
        }

        /// <summary>Band-preserving arithmetic, split for the same
        /// reason.</summary>
        internal static float WakeFrom(float roleSleep, float globalSleep, float globalWake)
        {
            return roleSleep - (globalSleep - globalWake);
        }

        /// <summary>Exposed for the header block and for the tests.</summary>
        internal static bool Applies(WildSpawnType role)
        {
            return Posted.Contains(role);
        }

        /// <summary>
        /// Role names in force, sorted so the header is stable across runs and
        /// two logs diff cleanly.
        /// </summary>
        internal static List<string> RoleNames()
        {
            List<string> names = new List<string>(Posted.Count);
            foreach (WildSpawnType role in Posted)
            {
                names.Add(role.ToString());
            }

            names.Sort(System.StringComparer.Ordinal);
            return names;
        }

        private static WildSpawnType RoleOf(BotOwner bot)
        {
            return bot.Profile != null && bot.Profile.Info != null
                ? bot.Profile.Info.Settings.Role
                : WildSpawnType.assault;
        }
    }
}
