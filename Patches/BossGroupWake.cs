using System.Collections.Generic;
using Comfort.Common;
using EFT;

namespace Framesaver.Patches
{
    /// <summary>
    /// Keeps a boss's followers awake while the boss is awake.
    ///
    /// A garrison is one unit and the sleep rule treats it as N independent
    /// bots. Birdeye engages at about 130m, which is precisely our wake
    /// boundary, while Knight and BigPipe stand further out and stay asleep -
    /// so the Goons arrive one at a time. Extending one role's range would
    /// only move the seam; keying on the boss/follower relationship fixes
    /// cohesion for every garrison the game declares - Shturman's, Gluhar's,
    /// Kolontay's - without naming any of them.
    ///
    /// Asymmetric on purpose. A boss wakes its followers; a follower never
    /// wakes its boss. The boss is where the decision belongs, and the reverse
    /// would let one straggler hold an entire garrison awake.
    ///
    /// It needs no cap of its own. The group is declared by the game and small
    /// - Kaban's is the largest at roughly a dozen - and a boss is only awake
    /// when it is near the player or fighting, which is exactly when its
    /// followers should be as well.
    /// </summary>
    internal static class BossGroupWake
    {
        /// <summary>
        /// True when this bot follows a boss that is not asleep.
        /// </summary>
        internal static bool HoldsAwake(BotOwner bot)
        {
            if (!Plugin.KeepBossGroupsAwake.Value)
            {
                return false;
            }

            BotOwner boss = BossOf(bot);
            return boss != null
                   && !boss.IsDead
                   && boss.StandBy != null
                   && boss.StandBy.standByType != BotStandByType.paused;
        }

        /// <summary>
        /// Two counts, because one of them cannot tell two very different
        /// zeroes apart.
        ///
        /// `linked` is followers that resolved a boss at all.
        /// BotFollower.TryFindBoss runs exactly once, from BotOwner.Activate,
        /// and only when the bot IsFollower - so if the boss has not activated
        /// yet when its follower does, the link may simply never form. There
        /// is no retry. That failure would leave this rule doing nothing at
        /// all while every other number in the log looked healthy: a shipped
        /// feature that is silently inert.
        ///
        /// `held` is the subset the rule is actually buying something for -
        /// linked, boss awake, and past the distance at which this bot would
        /// otherwise have been put to sleep.
        ///
        /// So `linked == 0` on a Goons raid is a linkage failure, while
        /// `linked > 0, held == 0` is a live rule that is not currently
        /// binding. Same reason animCulled needed animCulledOffScreen beside
        /// it: ship the number that says whether the feature is real, in the
        /// change that ships the feature.
        ///
        /// `linked` deliberately ignores the config flag. Gating it would make
        /// the feature switched off look identical to the linkage broken.
        /// </summary>
        internal static void Counts(out int linked, out int held)
        {
            linked = 0;
            held = 0;

            if (!Singleton<IBotGame>.Instantiated)
            {
                return;
            }

            BotsController controller = Singleton<IBotGame>.Instance.BotsController;
            if (controller == null || controller.Bots == null)
            {
                return;
            }

            IEnumerable<BotOwner> bots = controller.Bots.BotOwners;
            if (bots == null)
            {
                return;
            }

            foreach (BotOwner bot in bots)
            {
                if (bot == null || bot.IsDead || BossOf(bot) == null)
                {
                    continue;
                }

                linked++;

                // Past DIST_TO_SLEEP rather than DIST_TO_ACTIVATE: between the
                // two a bot keeps whatever state it already had, so only
                // beyond the far edge is "would certainly be asleep".
                if (bot.StandBy != null
                    && HoldsAwake(bot)
                    && BotStandByUpdatePatch.DistanceToNearestHumanPublic(bot.Position)
                       > bot.StandBy.DIST_TO_SLEEP)
                {
                    held++;
                }
            }
        }

        /// <summary>
        /// The BotOwner behind this bot's boss, or null.
        ///
        /// Read from the follower, which is O(1). BotBoss.Followers gives the
        /// other direction, but the stand-by check runs per bot, so walking
        /// every boss's list to answer for one follower is the same question
        /// asked the expensive way.
        ///
        /// The cast is what reaches the boss's own stand-by state:
        /// IBossToFollow exposes Player(), Position and Followers but not the
        /// BotOwner behind them, and BotBoss.Owner does. A foreign
        /// implementation of the interface therefore yields null here and the
        /// rule does not fire - it degrades to today's behaviour rather than
        /// throwing.
        /// </summary>
        private static BotOwner BossOf(BotOwner bot)
        {
            if (bot == null)
            {
                return null;
            }

            BotFollower follower = bot.BotFollower;
            if (follower == null || !follower.HaveBoss)
            {
                return null;
            }

            BotBoss boss = follower.BossToFollow as BotBoss;
            return boss != null ? boss.Owner : null;
        }
    }
}
