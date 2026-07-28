using System.Reflection;
using HarmonyLib;
using SPT.Reflection.Patching;

namespace Framesaver.Patches
{
    /// <summary>
    /// Forces BackendConfigAbstractClass.Config.UseBodyFastAnimator on.
    ///
    /// Unity's animation pass (PreLateUpdate/DirectorUpdateAnimationBegin) measures ~3.2ms of a ~12.9ms frame
    /// on Streets with 20 bots - the largest CPU-side game cost after rendering, and 24x the entire bot AI
    /// tick. When this flag is set, Player.method_81 swaps Unity's Animator for BSG's own
    /// FastAnimatorProcessorClass and sets _bodyUpdateMode to Manual.
    ///
    /// The flag is unreachable through normal means on an SPT install: AbstractApplication seeds the config
    /// from a fresh ApplicationConfigClass because client.config.json does not exist, the field has no
    /// initialiser, and PatchConfig only copies BackendUrl and MatchingVersion. So it is always false.
    ///
    /// Patching LoadApplicationConfig rather than writing client.config.json keeps every other config value
    /// untouched - notably BackendUrl, which SPT needs pointed at the local server.
    ///
    /// Expectation worth checking rather than assuming: Manual update mode means the game ticks the animator
    /// itself, so cost may *move* from DirectorUpdateAnimationBegin into ScriptRunBehaviourLateUpdate rather
    /// than disappear. The phase telemetry will show which.
    /// </summary>
    internal class FastBodyAnimatorPatch : ModulePatch
    {
        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(BackendConfigAbstractClass),
                nameof(BackendConfigAbstractClass.LoadApplicationConfig));
        }

        [PatchPostfix]
        private static void Postfix()
        {
            if (!Plugin.ForceFastBodyAnimator.Value)
            {
                return;
            }

            ApplicationConfigClass config = BackendConfigAbstractClass.Config;
            if (config == null)
            {
                Plugin.LogSource.LogWarning("Framesaver: config was null after load; fast animator not applied.");
                return;
            }

            if (!config.UseBodyFastAnimator)
            {
                config.UseBodyFastAnimator = true;
                Plugin.LogSource.LogWarning("Framesaver: UseBodyFastAnimator forced ON (experimental).");
            }
        }
    }
}
