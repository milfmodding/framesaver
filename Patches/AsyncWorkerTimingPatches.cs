using System.Diagnostics;
using System.Reflection;
using Diz.Utils;
using HarmonyLib;
using SPT.Reflection.Patching;

namespace Framesaver.Patches
{
    /// <summary>
    /// Times AsyncWorker's completion drain, split by which phase it ran in, AND (on the
    /// FixedUpdate side) implements the shipping "Drain completions in Update only" lever.
    ///
    /// RESTORED HERE (2026-08-19, same session, minutes after being deleted): the wiring-gap
    /// fix's first pass treated this whole file as measurement-only and deleted it once
    /// Ranger's copy was wired up - but EXTRACTION-PLAN.md had already ruled (Sophia,
    /// 2026-08-17 05:13Z) that this is a MIXED file: AsyncWorkerFixedUpdatePatch's Prefix
    /// does two jobs in one method, reading Plugin.DrainInUpdateOnly and skipping the
    /// original call when it is set - that skip IS the shipping lever, not a measurement.
    /// Deleting the file silently dropped it: Plugin.DrainInUpdateOnly stayed bound and
    /// visible in the BepInEx config, but nothing read it anymore, so toggling it would do
    /// nothing with no error. Caught by re-reading EXTRACTION-PLAN.md's own split ruling
    /// before trusting a deletion tests/unwrap has no coverage for (this is a live
    /// game-method skip, not a value the suite can assert on without a running game).
    ///
    /// RATHER THAN SPLITTING THE HARMONY PATCH ITSELF (which the extraction plan proposed
    /// but this restoration does not attempt): two separate ModulePatch classes, in two
    /// separate assemblies, both patching AsyncWorker.FixedUpdate has no established
    /// ordering guarantee in this codebase and was judged too large a change to get right
    /// under this session's time pressure - same reasoning AsyncDrainPatch's still-open
    /// class-split was left alone for. Both timing AND suppression stay together, in ONE
    /// patch, here in Framesaver, exactly as they always were. What DOES change: the two
    /// timing fields (UpdateDrainMs/FixedDrainMs) and the skip counter (FixedSkips) are
    /// written directly into RANGER's AsyncWorkerTiming via RangerBridge - Ranger's
    /// Telemetry.cs already reads that class (same-assembly, unqualified), and Ranger's OWN
    /// AsyncWorkerUpdatePatch/AsyncWorkerFixedUpdatePatch (the timing-only copies from the
    /// earlier batch move) are correspondingly left UNENABLED in Ranger's Plugin.cs, so
    /// there is still only ONE Harmony patch on each of these two methods - just this one,
    /// writing into a bridge-fed static in the other assembly instead of a local one.
    ///
    /// GClass1516.CheckForFinishedTasks empties the entire completion queue in one unbounded loop, and each
    /// callback is a TaskCompletionSource.SetResult that synchronously resumes whatever awaited it. AsyncWorker
    /// calls it from both Update and FixedUpdate, so a batch of background work finishing at the wrong moment
    /// lands its whole continuation inside a physics step.
    ///
    /// That is the shape of the unexplained spikes: ~800-1800ms frames spent almost entirely in FixedUpdate,
    /// with no change in bot count and allocation jumping from under 1.5MB/s to 123MB/s. Every RunOnBackgroundThread
    /// call site is resource-key or item work, which allocates heavily on completion.
    /// </summary>
    internal class AsyncWorkerUpdatePatch : ModulePatch
    {
        private static long _start;

        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(AsyncWorker), nameof(AsyncWorker.Update));
        }

        [PatchPrefix]
        private static void Prefix()
        {
            _start = Stopwatch.GetTimestamp();
        }

        [PatchPostfix]
        private static void Postfix()
        {
            // Present-gated at the call site (2026-08-20 fix, live Ranger-absent raid test) -
            // see BotStandByInitPointsPatch.cs's comment for the full story. This patch is
            // currently dead code (never .Enable()'d in Plugin.cs), so this fix has no live
            // effect today, but it needs to be correct before this class is ever wired up.
            if (RangerBridge.Present)
            {
                RangerBridge.AddAsyncWorkerUpdateDrainMs(TickMath.ToMs(Stopwatch.GetTimestamp() - _start));
            }
        }
    }

    /// <summary>
    /// Times the FixedUpdate drain, and optionally suppresses it.
    ///
    /// Both Update and FixedUpdate call CheckForFinishedTasks, and Unity runs the FixedUpdate phase before
    /// Update - so on any frame that owes a physics step the queue is drained inside physics, and otherwise
    /// in Update. That is the entire reason the same stall shows up as an fuFPS spike sometimes and a
    /// gameUpdate spike other times.
    ///
    /// Suppressing this call makes completions drain once per frame in Update instead, which takes a
    /// multi-hundred-millisecond callback out of the physics step and stops it feeding Unity's catch-up
    /// logic. It does not make the stall smaller - the same work runs either way, one phase later.
    /// </summary>
    internal class AsyncWorkerFixedUpdatePatch : ModulePatch
    {
        private static long _start;
        private static bool _skipped;

        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(AsyncWorker), nameof(AsyncWorker.FixedUpdate));
        }

        [PatchPrefix]
        private static bool Prefix()
        {
            _skipped = Plugin.DrainInUpdateOnly.Value;
            if (_skipped)
            {
                // Present-gated at the call site - see AsyncWorkerUpdatePatch.Postfix's
                // comment above for why.
                if (RangerBridge.Present)
                {
                    RangerBridge.IncrementAsyncWorkerFixedSkips();
                }

                return false;
            }

            _start = Stopwatch.GetTimestamp();
            return true;
        }

        [PatchPostfix]
        private static void Postfix()
        {
            // Postfixes still run when a prefix skips the original, so the timer must not be read then.
            if (_skipped)
            {
                return;
            }

            // Present-gated at the call site - see AsyncWorkerUpdatePatch.Postfix's comment
            // above for why.
            if (RangerBridge.Present)
            {
                RangerBridge.AddAsyncWorkerFixedDrainMs(TickMath.ToMs(Stopwatch.GetTimestamp() - _start));
            }
        }
    }
}
