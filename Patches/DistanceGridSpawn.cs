using System;
using System.Collections.Generic;
using System.Globalization;
using Comfort.Common;
using EFT;
using UnityEngine;
using UnityEngine.AI;

namespace Framesaver.Patches
{
    /// <summary>
    /// Built 2026-08-08, on Sophia's request: spawn a known, controlled bot population at fixed
    /// distances from the player instead of hoping a map/route happens to land the awake count
    /// where a raid needs it. Triggered by GridSpawnKey (see Telemetry.Update, which also writes
    /// the "gridSpawnPressed" marker BEFORE calling Trigger - that call is synchronous where this
    /// one is not, so the marker is the only reliable record of when the key was actually pressed).
    ///
    /// BUILT ON THE FUNNEL TRACED 2026-08-08, NOT A NEW MECHANISM. ActivateBotsWithoutWave,
    /// ActivateBotsByWave, SpawnBotByTypeForce and BossSpawner all converge on
    /// BotCreatorClass.ActivateBot -> BotOwner.PreActivate -> (per-frame) BotOwner.method_10, and
    /// that last step is unconditional - every bot that reaches Active gets it regardless of which
    /// spawn method created it. So a bot spawned here goes through the exact same stand-by/InitPoints
    /// treatment as a wave-spawned bot. Traced and confirmed against the live Assembly-CSharp.dll,
    /// not inferred - see the framesaver room log for 2026-08-08 for the decompiled call chain.
    ///
    /// THE ONE THING NOT COVERED BY THAT FUNNEL: position. None of the four vanilla spawn methods
    /// take a position argument - they all resolve one through SpawnSystem.SelectAISpawnPoints
    /// against a zone's predefined markers. BotCreationDataClass.AddPosition/GetPosition is the real
    /// mechanism (confirmed already in use by the normal wave path, not just DebugSpawnAnyway's
    /// debug plumbing) and it is used BLIND - method_2 hands the raw Vector3 straight to player
    /// creation with no NavMesh check. That check is done HERE, before AddPosition, rather than
    /// left to the game's own PreActive fallback - which does not reject a bad position, it silently
    /// teleports the bot to a random zone spawn point about a second later. See BotLog.ActivationCanary
    /// for the line that would catch it if this check were ever wrong or bypassed.
    /// </summary>
    internal static class DistanceGridSpawn
    {
        /// <summary>
        /// Public so Telemetry can size the "gridSpawnPressed" marker (ring count, requested bot
        /// count) from the SAME parse Trigger will use a moment later, rather than duplicating the
        /// CSV-splitting logic in two places that could drift.
        /// </summary>
        internal static float[] ParseDistances()
        {
            string raw = Plugin.GridSpawnDistances.Value ?? "";
            string[] parts = raw.Split(',');
            List<float> result = new List<float>(parts.Length);

            foreach (string part in parts)
            {
                string trimmed = part.Trim();
                if (trimmed.Length == 0)
                {
                    continue;
                }

                float value;
                if (float.TryParse(trimmed, NumberStyles.Float, CultureInfo.InvariantCulture, out value) && value > 0f)
                {
                    result.Add(value);
                }
                else
                {
                    Plugin.LogSource.LogWarning(
                        "Framesaver grid spawn: could not parse distance '" + trimmed + "' from config, skipping it.");
                }
            }

            return result.ToArray();
        }

        /// <summary>
        /// Called from Telemetry.Update on the keybind press, already gated on state == Raid there.
        /// Synchronous up to the point where positions are computed and validated; the actual spawn
        /// (BotCreationDataClass.Create awaits internally) runs in SpawnSlots, fire-and-forget from
        /// here the same way the game's own BotSpawner.method_7 does not await its own method_10 call.
        /// </summary>
        internal static void Trigger(float[] distances)
        {
            if (distances.Length == 0)
            {
                Plugin.LogSource.LogWarning("Framesaver grid spawn: no valid distances configured (see 'Distances'), nothing to spawn.");
                return;
            }

            GameWorld world = Singleton<GameWorld>.Instantiated ? Singleton<GameWorld>.Instance : null;
            if (world == null)
            {
                Plugin.LogSource.LogWarning("Framesaver grid spawn: no GameWorld, aborting.");
                return;
            }

            Player main = world.MainPlayer;
            if (main == null || main.HealthController == null || !main.HealthController.IsAlive)
            {
                Plugin.LogSource.LogWarning("Framesaver grid spawn: no live local player, aborting.");
                return;
            }

            IBotGame botGame = Singleton<IBotGame>.Instantiated ? Singleton<IBotGame>.Instance : null;
            BotsController controller = botGame != null ? botGame.BotsController : null;
            BotSpawner spawner = controller != null ? controller.BotSpawner : null;
            if (spawner == null)
            {
                Plugin.LogSource.LogWarning("Framesaver grid spawn: no BotSpawner available yet, aborting.");
                return;
            }

            Vector3 origin = main.Position;
            int perRing = Mathf.Max(1, Plugin.GridSpawnCountPerDistance.Value);
            float snapRadius = Plugin.GridSpawnNavMeshRadius.Value;

            List<RequestedSlot> slots = new List<RequestedSlot>(distances.Length * perRing);

            for (int ring = 0; ring < distances.Length; ring++)
            {
                float distance = distances[ring];

                // Ring-to-ring half-step offset so consecutive rings don't share bearings - makes
                // the rings visually distinct on a map overlay, nothing more than that.
                float baseAngleDeg = ring % 2 == 0 ? 0f : (360f / perRing) * 0.5f;

                for (int i = 0; i < perRing; i++)
                {
                    float angleDeg = baseAngleDeg + (360f / perRing) * i;
                    float angleRad = angleDeg * Mathf.Deg2Rad;
                    Vector3 candidate = origin + new Vector3(Mathf.Cos(angleRad), 0f, Mathf.Sin(angleRad)) * distance;

                    NavMeshHit hit;
                    if (NavMesh.SamplePosition(candidate, out hit, snapRadius, NavMesh.AllAreas))
                    {
                        slots.Add(new RequestedSlot(ring, distance, i, hit.position));
                    }
                    else
                    {
                        Plugin.LogSource.LogWarning(
                            "Framesaver grid spawn: ring " + ring + " (" + distance.ToString("0", CultureInfo.InvariantCulture)
                            + "m) slot " + i + " found no NavMesh within " + snapRadius.ToString("0.#", CultureInfo.InvariantCulture)
                            + "m - skipped rather than spawned off-mesh.");
                        BotLog.GridSpawnSkipped(ring, distance, i, candidate);
                    }
                }
            }

            if (slots.Count == 0)
            {
                Plugin.LogSource.LogWarning("Framesaver grid spawn: every position failed the NavMesh check, nothing spawned.");
                return;
            }

            SpawnSlots(spawner, slots);
        }

        private static async void SpawnSlots(BotSpawner spawner, List<RequestedSlot> slots)
        {
            try
            {
                GetProfileDataParams profileData = new GetProfileDataParams(
                    EPlayerSide.Savage, WildSpawnType.assault, BotDifficulty.normal, 0f);

                // Matches DebugSpawnAnyway's choice, not arbitrarily - assault/Savage is NOT one of
                // RoleSleepDistance's ~13 posted roles, so every spawned bot uses the plain 130/150m
                // wake/sleep band this feature exists to test, rather than a role-specific 350m one
                // that would make several rings meaningless. Confirmed 2026-08-08, see the room log.
                BotCreationData data = await BotCreationData.Create(
                    profileData, spawner._botCreator, slots.Count, spawner);

                // corePointId -1: guaranteed not to match a real AICorePoint.Id, which are
                // non-negative and generated per map. AICorePointHolder.GetCorePoint returns null
                // for an unmatched id - no exception - and BotCreatorClient.method_2 passes that
                // straight through as the bot's cover-point reference. Worst case is a bot with no
                // cover reference, not a crash. Confirmed 2026-08-08 against the live assembly.
                for (int i = 0; i < slots.Count; i++)
                {
                    data.AddPosition(slots[i].Position, -1);
                }

                BotZone zone = spawner.GetRandomBotZone(canBeSnipe: false);
                int nextSlot = 0;

                // ORDER ASSUMPTION, load-bearing, stated because it is one: BotCreatorClass.method_0
                // walks data.Profiles and calls data.GetPosition() once per profile, IN ORDER, and
                // GetPosition drains the list AddPosition built, first-not-yet-used first. Both lists
                // are fields on THIS data object - not the shared-static race Beta found for the
                // nine-site bot-ledger idea, which is a different feature entirely. So profile[i]
                // pairs with slots[i] reliably as long as the counts match, which they do here by
                // construction (one AddPosition per slot, slots.Count profiles requested).
                spawner.method_10(zone, data, delegate (BotOwner bot)
                {
                    if (nextSlot < slots.Count)
                    {
                        RequestedSlot slot = slots[nextSlot];
                        BotLog.GridSpawnResolved(bot, slot.Ring, slot.Distance, slot.Index, slot.Position);
                    }

                    nextSlot++;
                }, spawner.GetCancelToken());
            }
            catch (Exception ex)
            {
                Plugin.LogSource.LogError("Framesaver grid spawn failed: " + ex);
            }
        }

        private readonly struct RequestedSlot
        {
            internal readonly int Ring;
            internal readonly float Distance;
            internal readonly int Index;
            internal readonly Vector3 Position;

            internal RequestedSlot(int ring, float distance, int index, Vector3 position)
            {
                Ring = ring;
                Distance = distance;
                Index = index;
                Position = position;
            }
        }
    }
}
