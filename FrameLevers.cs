using System;
using Comfort.Common;
using Diz.Jobs;
using EFT;
using UnityEngine;

namespace Framesaver
{
    /// <summary>
    /// The per-frame behavioral levers that used to run inline inside Telemetry.cs's own
    /// Update() loop, before the capstone extraction moved the sampler to Ranger. These are
    /// NOT measurement - they are real Framesaver perf fixes (Time.maximumDeltaTime cap,
    /// JobScheduler tuning, the player-loop profiler's periodic re-arm check) that happen to
    /// have been driven from the same per-frame call site the sampler used, because that was
    /// the only per-frame hook the mod had before Ranger existed.
    ///
    /// Capstone finding (2026-08-18): unlike the 27+ config fields already folded into the
    /// window callback's cfg dump (StandByEnabled, SleepDistance, etc. - read once per ~30s
    /// window) and unlike ForceStandByForAllRoles (a bare per-BOT-EVENT value read), these
    /// three are ACTIVE PER-FRAME LOGIC - applying a cap, tuning a scheduler, checking a
    /// re-arm deadline - so they cannot be a passive reader or a window-cadence fragment.
    /// They need to keep running every frame, which is exactly what Ranger's existing
    /// per-frame callback slot (TelemetryBus.RegisterPerFrameCallback) already provides -
    /// same mechanism GcControl.ApplyConfig()/.Drive()/.Track() already use. Registered via
    /// RangerBridge (see RangerBridge.RegisterPerFrameLevers) so Framesaver's Awake stays
    /// JIT-safe with Ranger absent.
    /// </summary>
    internal static class FrameLevers
    {
        private static bool _vanillaMaxDeltaTimeCaptured;
        private static float _vanillaMaxDeltaTime;

        private static float _nextLoopCheck;

        /// <summary>
        /// Called once per frame (via the per-frame callback). Runs all three levers in the
        /// same order Telemetry.cs's Update() ran them inline, so behavior is unchanged.
        /// </summary>
        internal static void PerFrame()
        {
            ApplyMaxDeltaTime();
            ApplyJobSchedulerOverrides();
            ReArmPlayerLoopProfilerIfDue();
        }

        /// <summary>
        /// Live-applied so it can be toggled mid-raid like the other experimental flags.
        /// Moved verbatim from Telemetry.cs's Update() - see that file's git history for the
        /// original comment this is copied from.
        /// </summary>
        private static void ApplyMaxDeltaTime()
        {
            if (!_vanillaMaxDeltaTimeCaptured)
            {
                _vanillaMaxDeltaTime = Time.maximumDeltaTime;
                _vanillaMaxDeltaTimeCaptured = true;
            }

            float wanted = Plugin.MaxDeltaTime.Value > 0f ? Plugin.MaxDeltaTime.Value : _vanillaMaxDeltaTime;
            if (!Mathf.Approximately(Time.maximumDeltaTime, wanted))
            {
                Time.maximumDeltaTime = wanted;
            }
        }

        /// <summary>
        /// Applied live rather than at load, since JobScheduler is recreated per session and the game
        /// rewrites FrameTicks whenever graphics settings change. Moved verbatim from Telemetry.cs.
        /// </summary>
        private static void ApplyJobSchedulerOverrides()
        {
            if (!Singleton<JobScheduler>.Instantiated)
            {
                return;
            }

            JobScheduler js = Singleton<JobScheduler>.Instance;

            float budget = Plugin.JobSchedulerBudgetMs.Value;
            if (budget > 0f)
            {
                long ticks = (long)(budget * TimeSpan.TicksPerMillisecond);
                if (js.FrameTicks != ticks)
                {
                    js.FrameTicks = ticks;
                }
            }

            int slow = Plugin.JobSchedulerSlowFrames.Value;
            if (slow >= 0 && js.SlowFrames != (byte)slow)
            {
                js.SlowFrames = (byte)slow;
            }
        }

        /// <summary>
        /// The game rewrites the player loop during raid load; re-arm if our markers were
        /// dropped. Moved verbatim from Telemetry.cs's Update() (the 5-second-interval check),
        /// using Time.realtimeSinceStartup the same way the original did.
        ///
        /// Capstone cutover (2026-08-19): PlayerLoopProfiler.cs moves to Ranger together with
        /// Telemetry.cs (the seam-5 lesson - profiler and sampler cannot change owners
        /// independently). This class stays in Framesaver, so the actual re-arm call is now
        /// routed through RangerBridge rather than a direct PlayerLoopProfiler.MarkersPresent/
        /// .Install call - see RangerBridge.ReArmPlayerLoopProfilerIfNeeded's own doc comment
        /// for how this gap was found. The Plugin.ProfilePlayerLoop.Value gate stays here
        /// (config lookup, no cross-assembly reach), only the profiler touch moved.
        /// </summary>
        private static void ReArmPlayerLoopProfilerIfDue()
        {
            if (Time.realtimeSinceStartup < _nextLoopCheck)
            {
                return;
            }

            _nextLoopCheck = Time.realtimeSinceStartup + 5f;
            if (Plugin.ProfilePlayerLoop.Value)
            {
                Framesaver.Patches.RangerBridge.ReArmPlayerLoopProfilerIfNeeded();
            }
        }
    }
}
