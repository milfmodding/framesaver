using System;
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
            // Decoupled cull first, and deliberately NOT folded into
            // ApplyIfSleeping. That method's bool is what the LateUpdate and
            // world-tick prefixes skip on, so answering true for every bot
            // would skip Player.LateUpdate for the whole roster - suppressing
            // the VisualPass this cull rides on, for everyone, permanently.
            // The two features would annihilate each other on the first frame.
            if (CullEveryBot(__instance))
            {
                return;
            }

            ApplyIfSleeping(__instance);
        }

        /// <summary>
        /// The decoupled cull: every live AI player is eligible, and Unity culls
        /// whichever of them are invisible.
        ///
        /// **There is no distance check here and there should not be.**
        /// AnimatorCullingMode keys on RENDERER VISIBILITY, not distance, so our
        /// marking only decides eligibility and the engine decides the rest -
        /// per bot, per frame, for free. That deletes the whole apparatus the
        /// coupled version needs: no `Sleeping` set, no distance measure of our
        /// own, and no role exemption. A sniper engaging from 200m is either on
        /// screen and not culled, or off it - and vanilla already froze his
        /// transforms at 10m via CullUpdateTransforms, so nothing is lost that
        /// the base game had.
        ///
        /// Writes unconditionally rather than checking visibility ourselves.
        /// Setting CullCompletely on a VISIBLE bot changes nothing - culling
        /// modes only act while renderers are invisible - so the check would be
        /// a second, worse copy of one the engine already does.
        ///
        /// **The risk this carries, and it is not measurable from any log:**
        /// CullCompletely stops state-machine evaluation, so animation events
        /// stop being ENQUEUED. Free for a paused bot, which is not reloading.
        /// Unknown for an awake bot that leaves the screen mid-reload. See
        /// harness/RELOAD-OBSERVATION-TEST.md - that is why this ships off.
        /// </summary>
        internal static bool CullEveryBot(Player player)
        {
            if (!Plugin.CullAllBotAnimators.Value || Inert || !IsLiveBot(player))
            {
                return false;
            }

            IAnimator body = player.BodyAnimatorCommon;
            if (body != null)
            {
                body.cullingMode = AnimatorCullingMode.CullCompletely;
            }

            return true;
        }

        /// <summary>
        /// A bot that is alive. `IsAI` keeps human players out, including Fika
        /// remotes; the health check is not optional, because
        /// GameWorld.AllAlivePlayersList never removes the dead - UnregisterPlayer
        /// is reached only from Player.Dispose() at raid teardown - so the list
        /// its name promises is not the list it holds.
        /// </summary>
        internal static bool IsLiveBot(Player player)
        {
            return player != null
                   && player.IsAI
                   && player.HealthController != null
                   && player.HealthController.IsAlive;
        }

        /// <summary>
        /// The bots we asked the engine to cull this frame - `Sleeping` when the
        /// cull is coupled to stand-by, the live AI roster when it is not.
        ///
        /// Empty when neither cull is switched on, which is what keeps
        /// `animCulled` meaning exactly what it meant in all 25 existing logs.
        /// </summary>
        private static List<Player> Marked()
        {
            List<Player> marked = new List<Player>();

            if (Plugin.CullAllBotAnimators.Value)
            {
                AppendLiveBots(marked);
                return marked;
            }

            if (Plugin.CullSleepingBotAnimators.Value)
            {
                foreach (KeyValuePair<Player, BotStandBy> entry in Sleeping)
                {
                    marked.Add(entry.Key);
                }
            }

            return marked;
        }

        /// <summary>Every live AI player, or nothing outside a raid.</summary>
        private static void AppendLiveBots(List<Player> into)
        {
            GameWorld world = Singleton<GameWorld>.Instance;
            List<Player> alive = world != null ? world.AllAlivePlayersList : null;
            if (alive == null)
            {
                return;
            }

            for (int i = 0; i < alive.Count; i++)
            {
                if (IsLiveBot(alive[i]))
                {
                    into.Add(alive[i]);
                }
            }
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
            BotOwner owner = standBy._owner;
            if (owner == null || owner.GetPlayer != player || standBy.standByType != BotStandByType.paused)
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
        /// Called from the stand-by state-change hook below. Dropping a bot
        /// from this set restores vanilla behaviour on the next frame without
        /// undoing anything, because VisualPass rewrites cullingMode - **but
        /// only while Player.LateUpdate is still running for that bot.**
        ///
        /// This used to add "including when the config toggle is switched off
        /// mid-raid", flatly, as a reason not to worry. That was true when
        /// written and `Skip sleeping bot LateUpdate` later falsified it:
        /// LateUpdate holds the ONLY call site of VisualPass (Player.cs:1565),
        /// so with the skip on nothing rewrites cullingMode and a bot asleep at
        /// a config change stays culled until it next wakes. Same shape as the
        /// claim Wake() used to make about BotState - a comment that promises a
        /// recovery which, in one arm, nothing performs.
        ///
        /// Not gated on any flag, deliberately: CulledEngine's whole value rests
        /// on this set being populated whether or not the cull is switched on.
        /// Gate this for cost and that field silently reads 0 on a latched arm,
        /// which is the exact reading it exists to prevent.
        /// </summary>
        internal static void SetSleeping(BotStandBy standBy, bool sleeping)
        {
            BotOwner owner = standBy != null ? standBy._owner : null;
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
            get { return Marked().Count; }
        }

        /// <summary>
        /// Of the bots we marked, how many are OFF SCREEN - which is a fact
        /// about the camera, not about the engine. `CulledLastFrame` counts
        /// what we asked for; this counts how many of those Unity was in a
        /// position to honour, and it is an UPPER BOUND on the saving rather
        /// than a measurement of it. **Read them as a pair**: the ratio is the
        /// fraction of the marking that could have paid off, and if it is small
        /// then the saving is smaller than every number we have quoted.
        ///
        /// **This does NOT count what the engine honoured**, and the docstring
        /// said it did until 2026-08-04. What the engine honoured is
        /// `cullingMode == CullCompletely`, which is `CulledEngine` below and a
        /// different field over a different population. The distinction is the
        /// whole reason `CulledEngine` was written: off-screen is a precondition
        /// for the cull paying off, not evidence that the write landed.
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
                int offScreen = 0;
                foreach (Player player in Marked())
                {
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
        /// **Walks the whole live AI roster, not the marked set**, and that is a
        /// deliberate widening from the first version. A latch is a bot the
        /// engine is still culling after we stopped asking - so scanning only
        /// what we currently mark is scanning the one population guaranteed not
        /// to contain the evidence. It also makes the field work with stand-by
        /// switched off entirely, where `Sleeping` is empty by construction and
        /// the old version read 0 no matter what the engine was doing. That is
        /// exactly the configuration the reload observation test runs in.
        ///
        /// Read as a triple with the two above, IN EMIT ORDER, which is not the
        /// order this comment used to give:
        ///
        ///     animCulled           asked         CulledLastFrame
        ///     animCulledOffScreen  off screen    CulledOffScreen
        ///     animCulledEngine     reached the engine   (this)
        ///
        /// The old wording was "asked / honoured / off screen", which lands
        /// `animCulledEngine` on "off screen" - the opposite of what it is, and
        /// exactly backwards for anyone mapping the prose onto the log.
        ///
        /// **And the three are NOT over one population.** `CulledLastFrame` and
        /// `CulledOffScreen` walk `Marked()`, which is `Sleeping` in the coupled
        /// arm; this walks the whole live AI roster. They coincide in the
        /// decoupled arm and diverge in the coupled one, so a ratio between them
        /// is only a ratio when the arm makes it one.
        /// </summary>
        public static int CulledEngine
        {
            get
            {
                List<Player> bots = new List<Player>();
                AppendLiveBots(bots);

                int culled = 0;
                foreach (Player player in bots)
                {
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
            return animator != null && !typeof(FastAnimatorSystem.FastAnimatorProcessor).IsAssignableFrom(animator);
        }

        public static void ReadAndReset()
        {
        }

        /// <summary>
        /// Ranger extraction (2026-08-16/17): publish-side addition, ADDITIVE. Takes the three values
        /// as parameters rather than re-reading CulledLastFrame/CulledOffScreen/CulledEngine itself -
        /// each is a COMPUTED PROPERTY that walks a bot roster on every read, so a second independent
        /// read here would double that cost every window for no reason. The caller (Telemetry.Flush)
        /// already reads all three once for the NDJSON "bots" block; this reuses those same values.
        /// Routed through RangerBridge rather than calling Ranger.TelemetryBus directly - see
        /// RangerBridge.cs for why a plain reference is not safe with Ranger absent.
        /// </summary>
        internal static void PublishTelemetry(int animCulled, int animCulledOffScreen, int animCulledEngine)
        {
            if (!RangerBridge.Present)
            {
                return;
            }

            RangerBridge.PublishAnimatorCull(animCulled, animCulledOffScreen, animCulledEngine);
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
            Inert = false;

            try
            {
                ApplicationConfig config = AppEnvironment.Config;
                Inert = config != null && config.UseBodyFastAnimator;
            }
            catch (Exception)
            {
                // Cannot read it, so do not claim it. Leaving Inert false keeps
                // the cull running; CulledEngine reads the engine and will
                // disagree with animCulled if the write is landing nowhere.
            }

            // EVERY raid it is true, not the raid it becomes true. `Inert` is
            // static and survives a raid, so a rising edge fires once per
            // SESSION - and a log is a session (832498f). Someone reading back
            // raid 7 of a marathon would find a clean log for a raid in which
            // the cull was dead throughout. Reads as log spam and is not: the
            // line is absent from every raid that was fine.
            if (Inert)
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
            BotOwner owner = __instance != null ? __instance._owner : null;

            // Present-gated at the call site (2026-08-20 fix, live Ranger-absent raid test):
            // NotifyAwakeAgeEnded/NotifyAwakeAgeWoke's own internal Present check is not
            // enough to keep this Postfix (unconditionally enabled, fires on every stand-by
            // transition) safe with Ranger absent - the first CALL to either bridge method
            // still triggers Mono JIT-compiling it, which throws TypeLoadException regardless
            // of whether the internal check would have short-circuited. See
            // BotStandByInitPointsPatch.cs's own comment for the fuller story (same shape of
            // bug, found live via AsyncDrainPatch.cs's identical crash).
            if (RangerBridge.Present)
            {
                if (paused)
                {
                    RangerBridge.NotifyAwakeAgeEnded(owner);
                }
                else
                {
                    RangerBridge.NotifyAwakeAgeWoke(owner);
                }
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
    ///
    /// **WHAT THIS FLAG BREAKS ELSEWHERE, recorded here because this is where
    /// someone turning it on is standing.** Player.LateUpdate holds the ONLY
    /// call site of Player.VisualPass (Player.cs:1565), and VisualPass is the
    /// only thing that rewrites cullingMode. So with this on:
    ///
    ///   - the animator cull stops being reversible. Dropping a bot from
    ///     `Sleeping`, or switching the cull off mid-raid, no longer restores
    ///     vanilla - a bot asleep at that moment stays CullCompletely until it
    ///     next wakes. SetSleeping's docstring asserted the opposite for weeks.
    ///   - `animCulledEngine` is what tells a returned arm from a latched one,
    ///     and any protocol that MOVES this flag needs it read. A protocol that
    ///     pins this off has designed the latch out rather than measured it away.
    ///
    /// The rule this is an instance of: a bool prefix can suppress the method it
    /// wraps, so anything documented as "M always runs" becomes conditional the
    /// day one is added. tests/unwrap enumerates every such prefix against a
    /// reviewed list, which is what makes that day loud.
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
            // 4.1: was "smethod_2"; the closure GameWorld.PlayerTick invokes now carries the
            // CG_PlayerTick name. Mapped by call site (PlayerTick -> smethod_2 on 4.0.13,
            // PlayerTick -> CG_PlayerTick on 4.1), not by name - three same-shaped closures
            // made name-shape matching impossible.
            return AccessTools.Method(typeof(GameWorld), "CG_PlayerTick");
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
