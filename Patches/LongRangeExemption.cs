using System.Collections.Generic;
using Comfort.Common;
using EFT;
using UnityEngine;

namespace Framesaver.Patches
{
    /// <summary>
    /// Keeps the nearest few long-range bots awake regardless of distance.
    ///
    /// Distance-to-player is a good proxy for "can this bot affect the player" for almost every role, but
    /// not for sniper scavs: they are placed at overwatch positions precisely to engage from beyond it. With
    /// a 150m sleep distance a marksman sitting at 200m sleeps permanently and never takes a shot, which is
    /// a behaviour regression rather than a saving. Vanilla has the same flaw at its own 240m, just further
    /// out.
    ///
    /// Rank rather than radius, because that is what bounds the cost. Exempting the role outright would mean
    /// every sniper on the map stays awake forever - fine on Customs with two, not fine on a map with a
    /// dozen. Keeping the N nearest awake costs exactly N bots no matter how many exist.
    ///
    /// The ranking is recomputed on the same cadence as the stand-by check itself, so a moving player
    /// promotes and demotes snipers as they cross each other, and the recompute cost is one pass over the
    /// bot list every few seconds.
    /// </summary>
    internal static class LongRangeExemption
    {
        private static readonly HashSet<BotOwner> Exempt = new HashSet<BotOwner>();
        private static readonly List<BotOwner> Candidates = new List<BotOwner>();
        private static float _nextRebuild;
        private static float _lastRebuild = float.NegativeInfinity;

        internal static bool IsExempt(BotOwner bot)
        {
            int keep = Plugin.KeepNearestSnipersAwake.Value;
            if (keep <= 0 || bot == null || !IsLongRange(bot))
            {
                return false;
            }

            Rebuild(keep);
            return Exempt.Contains(bot);
        }

        private static bool IsLongRange(BotOwner bot)
        {
            WildSpawnType role = bot.Profile != null && bot.Profile.Info != null
                ? bot.Profile.Info.Settings.Role
                : WildSpawnType.assault;

            return role == WildSpawnType.marksman;
        }

        private static void Rebuild(int keep)
        {
            if (Time.time < _nextRebuild)
            {
                return;
            }

            _nextRebuild = Time.time + Plugin.CheckInterval.Value;
            _lastRebuild = Time.time;
            Exempt.Clear();
            Candidates.Clear();

            if (!Singleton<IBotGame>.Instantiated)
            {
                return;
            }

            BotsController controller = Singleton<IBotGame>.Instance.BotsController;
            IEnumerable<BotOwner> bots = controller != null && controller.Bots != null
                ? controller.Bots.BotOwners
                : null;
            if (bots == null)
            {
                return;
            }

            foreach (BotOwner bot in bots)
            {
                if (bot != null && !bot.IsDead && IsLongRange(bot))
                {
                    Candidates.Add(bot);
                }
            }

            if (Candidates.Count <= keep)
            {
                // Fewer than the cap - all of them stay awake, no sorting needed.
                for (int i = 0; i < Candidates.Count; i++)
                {
                    Exempt.Add(Candidates[i]);
                }

                return;
            }

            // Partial selection rather than a full sort: keep is 1-2 in practice, so this is a couple of
            // passes over a short list.
            for (int picked = 0; picked < keep; picked++)
            {
                BotOwner best = null;
                float bestDistance = float.MaxValue;

                for (int i = 0; i < Candidates.Count; i++)
                {
                    BotOwner candidate = Candidates[i];
                    if (candidate == null || Exempt.Contains(candidate))
                    {
                        continue;
                    }

                    float d = BotStandByUpdatePatch.DistanceToNearestHumanPublic(candidate.Position);
                    if (d < bestDistance)
                    {
                        bestDistance = d;
                        best = candidate;
                    }
                }

                if (best == null)
                {
                    break;
                }

                Exempt.Add(best);
            }
        }

        /// <summary>
        /// Snipers currently held awake by rank - reported so the cost stays visible.
        ///
        /// The set is only rebuilt when a bot calls IsExempt from the stand-by check, so once bots stop
        /// ticking - raid over, everything dead, or a map with no marksman at all - it would otherwise keep
        /// reporting whatever the last raid left in it. That made the field ambiguous at every raid
        /// boundary: a 1 on a fresh map could be a real sniper or a leftover from the previous raid.
        ///
        /// Treat the set as stale if no rebuild has happened for a full extra check interval, and prune
        /// entries whose bot has since died, so the number always describes bots that exist right now.
        /// </summary>
        internal static int Count
        {
            get
            {
                if (Time.time > _lastRebuild + (Plugin.CheckInterval.Value * 2f))
                {
                    return 0;
                }

                int live = 0;
                foreach (BotOwner bot in Exempt)
                {
                    if (bot != null && !bot.IsDead)
                    {
                        live++;
                    }
                }

                return live;
            }
        }
    }
}
