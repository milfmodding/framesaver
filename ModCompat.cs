using System;
using System.Reflection;
using BepInEx.Bootstrap;

namespace Framesaver
{
    /// <summary>
    /// Detects the other mods Framesaver shares a raid with, and answers the three questions where their
    /// presence changes what we should do.
    ///
    /// Detection is deferred rather than done in Awake. BepInEx 5 fills Chainloader.PluginInfos as each
    /// plugin is instantiated, so a plugin loading before us is visible and one loading after us is not -
    /// an Awake-time check is a coin flip on load order. Every caller here sits on an in-raid path, by which
    /// point the chainloader has long finished, so resolving lazily on first use is both correct and free
    /// after the first call. (SAIN solves the same problem by waiting 5 seconds; same reasoning.)
    /// </summary>
    internal static class ModCompat
    {
        private const string AILimitGuid = "com.dvize.ailimit";
        private const string OrbitGuid = "com.chazut.orbit";
        private const string BigBrainGuid = "xyz.drakia.bigbrain";
        private const string FikaGuid = "com.fika.core";
        private const string FikaHeadlessGuid = "com.fika.headless";
        private const string SainGuid = "me.sol.sain";
        private const string QuestingBotsGuid = "com.danw.questingbots";
        private const string LootingBotsGuid = "me.skwizzy.lootingbots";

        private static bool _detected;

        public static bool AILimit { get; private set; }
        public static bool Orbit { get; private set; }
        public static bool BigBrain { get; private set; }
        public static bool Fika { get; private set; }
        public static bool FikaHeadlessPlugin { get; private set; }
        public static bool Sain { get; private set; }
        public static bool QuestingBots { get; private set; }
        public static bool LootingBots { get; private set; }

        /// <summary>
        /// FikaBackendUtils.IsHeadless, resolved reflectively so Framesaver never hard-references Fika.
        /// Null when Fika is absent or the type has moved.
        /// </summary>
        private static PropertyInfo _isHeadlessProperty;

        /// <summary>
        /// True when THIS instance is the headless host. Read live rather than cached: it is set per raid,
        /// not at load. Callers are on the stand-by check path (once per bot per check interval), so a
        /// reflected property read is not worth optimising away.
        /// </summary>
        public static bool IsFikaHeadlessHost
        {
            get
            {
                EnsureDetected();

                if (_isHeadlessProperty == null)
                {
                    return false;
                }

                try
                {
                    return (bool)_isHeadlessProperty.GetValue(null);
                }
                catch (Exception)
                {
                    // A Fika update that changes the property shape must not take the stand-by system with
                    // it. Failing closed means "not headless", which is the single-player behaviour.
                    _isHeadlessProperty = null;
                    return false;
                }
            }
        }

        /// <summary>
        /// AILimit drives the same BotStandBy objects we do, from its own MonoBehaviour, and its hammer is
        /// strictly bigger than ours: it calls gameObject.SetActive(false), which stops per-bot MonoBehaviours
        /// (LootingBots' brain among them) and Unity's animation evaluation, where our pause only skips the
        /// subsystem ticks in BotOwner.UpdateManual. Running both means two distance systems with different
        /// radii (its map defaults are 400m, ours is 150) and different cadences (300 frames vs 5s) fighting
        /// over one state object. It wins that fight on merit, so we step aside.
        /// </summary>
        public static bool SuppressStandBy
        {
            get
            {
                EnsureDetected();
                return Plugin.DeferToOtherAiMods.Value && AILimit;
            }
        }

        /// <summary>
        /// Round-robin brain slicing makes an agent think every Nth frame instead of every frame. ORBIT
        /// postfixes AICoreControllerClass.Update and dispatches every frame regardless, so it would act on
        /// layer state up to N frames stale; BigBrain's entire purpose is custom brain layers, which slicing
        /// throttles directly. Neither breaks - our replacement is behaviourally identical to vanilla with
        /// slicing off - but the interaction is the kind that produces "the AI feels wrong" reports with no
        /// obvious cause.
        /// </summary>
        public static bool SuppressSlicing
        {
            get
            {
                EnsureDetected();
                return Plugin.DeferToOtherAiMods.Value && (Orbit || BigBrain);
            }
        }

        /// <summary>
        /// Mods that clear BotOwner.StandBy.CanDoStandBy, which switches Framesaver's stand-by system - and
        /// therefore the animator cull, both sleeping-bot skips and the sniper exemption, all of which key
        /// off the paused state - off entirely.
        ///
        /// QuestingBots does it to every bot on brain activate; ORBIT does it in its brain layer's
        /// constructor ("BSG would otherwise deactivate the bot when far from the player"). Both are
        /// substituting their own handling for vanilla's check, and both take ours down as collateral.
        /// </summary>
        public static bool ClearsStandByFlag
        {
            get
            {
                EnsureDetected();
                return QuestingBots || Orbit;
            }
        }

        internal static void EnsureDetected()
        {
            if (_detected)
            {
                return;
            }

            AILimit = Has(AILimitGuid);
            Orbit = Has(OrbitGuid);
            BigBrain = Has(BigBrainGuid);
            Fika = Has(FikaGuid);
            FikaHeadlessPlugin = Has(FikaHeadlessGuid);
            Sain = Has(SainGuid);
            QuestingBots = Has(QuestingBotsGuid);
            LootingBots = Has(LootingBotsGuid);

            // Latch AFTER the probes and BEFORE the logging, and both halves matter.
            //
            // It used to latch first. A caller running before Chainloader.PluginInfos
            // was populated would then cache "nothing installed" for the whole session
            // - SuppressSlicing false forever, the compatibility guard silently off,
            // and no trace but the AI behaving differently. Never fired, because the
            // first caller today is a bot-brain frame long after load. Gamma nearly
            // became the first early caller by adding a detected-mod field to the log
            // header, which runs in Awake: a LOGGING change would have disabled a
            // behavioural guard.
            //
            // Before moving it, checked that the early latch was not an uncommented
            // recursion guard - an obvious bug and a load-bearing one look identical
            // in a diff. It is not: Has touches only Chainloader, ResolveFikaHeadless
            // only AppDomain, and LogSummary reads the backing fields rather than the
            // properties, so nothing re-enters here. Had LogSummary used the
            // properties, moving this would have traded a silent wrong answer for a
            // stack overflow on load.
            //
            // Before the logging because LogSummary is the only thing here that can
            // throw uncaught, and a throw after latching costs one log line, while a
            // throw before it would re-run detection and re-log on every later call.
            _detected = true;

            if (Fika)
            {
                ResolveFikaHeadless();
            }

            LogSummary();
        }

        /// <summary>
        /// Case-insensitive on purpose. Mods change their GUID casing between releases, and
        /// Chainloader.PluginInfos is an ordinal dictionary, so an exact-match lookup reports "not
        /// installed" for a mod sitting right there in the BepInEx log - silently, with no error to notice.
        ///
        /// Found the hard way: QuestingBots ships "com.danw.questingbots", while the constant published in
        /// SAIN's own AssemblyInfoClass - which is where this list came from - still reads
        /// "com.DanW.QuestingBots". Matching loosely costs one string compare per plugin, once per session.
        /// </summary>
        private static bool Has(string guid)
        {
            try
            {
                foreach (string key in Chainloader.PluginInfos.Keys)
                {
                    if (string.Equals(key, guid, StringComparison.OrdinalIgnoreCase))
                    {
                        return true;
                    }
                }
            }
            catch (Exception)
            {
                // Fall through - a detection failure must never take the raid with it.
            }

            return false;
        }

        private static void ResolveFikaHeadless()
        {
            try
            {
                foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
                {
                    if (assembly.GetName().Name != "Fika.Core")
                    {
                        continue;
                    }

                    Type backendUtils = assembly.GetType("Fika.Core.Main.Utils.FikaBackendUtils");
                    if (backendUtils == null)
                    {
                        break;
                    }

                    _isHeadlessProperty = backendUtils.GetProperty(
                        "IsHeadless", BindingFlags.Public | BindingFlags.Static);
                    break;
                }
            }
            catch (Exception e)
            {
                Plugin.LogSource.LogWarning("Framesaver: Fika detected but IsHeadless could not be resolved - "
                    + "treating this instance as non-headless. " + e.Message);
            }
        }

        private static void LogSummary()
        {
            string found = string.Join(", ", DetectedNames());

            Plugin.LogSource.LogInfo(found.Length == 0
                ? "Framesaver: no known AI or co-op mods detected."
                : "Framesaver: detected " + found + ".");

            if (!Plugin.DeferToOtherAiMods.Value)
            {
                if (AILimit || Orbit || BigBrain)
                {
                    Plugin.LogSource.LogWarning(
                        "Framesaver: 'Defer to other AI mods' is off, so no compatibility guards will be "
                        + "applied. Expect the interactions described in COMPATIBILITY.md.");
                }

                return;
            }

            if (AILimit)
            {
                Plugin.LogSource.LogInfo(
                    "Framesaver: AILimit is present and does the same job more aggressively, so the stand-by "
                    + "patch is standing down. Distance-based pausing is AILimit's from here.");
            }

            if (Orbit || BigBrain)
            {
                if (Plugin.BrainUpdatePeriod.Value > 0f)
                {
                    Plugin.LogSource.LogWarning(
                        "Framesaver: brain slicing is configured but suppressed - "
                        + (Orbit ? "ORBIT" : "BigBrain")
                        + " drives bot brains and slicing would make it act on stale layer state.");
                }
            }
        }

        private static string[] DetectedNames()
        {
            var names = new System.Collections.Generic.List<string>(8);

            if (AILimit) names.Add("AILimit");
            if (Orbit) names.Add("ORBIT");
            if (BigBrain) names.Add("BigBrain");
            if (Sain) names.Add("SAIN");
            if (QuestingBots) names.Add("QuestingBots");
            if (LootingBots) names.Add("LootingBots");
            if (Fika) names.Add(FikaHeadlessPlugin ? "Fika (+headless)" : "Fika");

            return names.ToArray();
        }
    }
}
