using System;
using System.Diagnostics;
using System.Globalization;
using System.Text;
using Framesaver.Patches;
using UnityEngine.Scripting;

namespace Framesaver
{
    /// <summary>
    /// Knobs and counters for the in-raid collection pause.
    ///
    /// Established 2026-07-27 on Streets: every `TimeUpdate`-dominant in-raid spike carries exactly one gen0
    /// collection (14 of 14, against a base rate of one collection per 3,628 frames), and PresentMon shows the
    /// GPU idle throughout. So `TimeUpdate` is a stop-the-world pause, not a presentation wait, and it costs
    /// 80-120 ms scaling with heap size.
    ///
    /// What is not yet known is *why* it is stop-the-world at all. `gcRuntime` reports `isIncremental: true`
    /// with a 3 ms slice, and these frames have perfectly ordinary boundaries either side, so the collector
    /// had every opportunity to spread the work and did not. Two candidates:
    ///
    ///   1. The collection is being **forced to completion** - an allocation that cannot wait for the
    ///      incremental collector to finish. If so the slice size is irrelevant and driving the collector
    ///      harder ahead of time should help.
    ///   2. Only **marking** is incremental and the sweep is unconditionally stop-the-world. If so nothing
    ///      here can help and the only remaining lever is allocation volume and heap size.
    ///
    /// `Time slice ms` and `Drive incremental ms` discriminate between them, and 2 is the outcome where they
    /// both do nothing. That is a real result rather than a failed experiment - it would close off the
    /// scheduling approach entirely and send the work back to `presetBatch` and the profile churn.
    /// </summary>
    internal static class GcControl
    {
        private static bool _sliceApplied;
        private static ulong _vanillaSliceNs;
        private static bool _vanillaSliceCaptured;

        private static int _driveCalls;
        private static int _drivePending;
        private static double _driveMsTotal;
        private static double _driveMsMax;

        // Suspension-to-collection tracking. The PMC session's hypothesis (COORDINATION.md, 2026-07-27) is
        // that `Suspend GC during completion callbacks` is itself candidate 1 - GCMode goes Disabled across a
        // callback allocating 120-190 MB, and the deferred work then lands as one expensive pause once it is
        // re-enabled. That would be a stall this mod manufactures.
        //
        // Window-level `gcSuspended` cannot test it: a suspension anywhere in a 60 s window says nothing
        // about whether it preceded the collection. What the mechanism actually predicts is that the *first
        // collection after a suspended span* is disproportionately expensive, so the pairing has to be
        // per-collection.
        private static int _prevSuspendCount;
        private static int _prevGcCount;
        private static int _suspendsSinceGc;
        private static long _lastSuspendTicks;

        private static int _suspendsBeforeLastGc = -1;
        private static double _msSinceSuspendAtLastGc = -1d;

        /// <summary>
        /// Applied live rather than once at load, so it can be toggled mid-raid like the other experimental
        /// flags and segmented on afterwards. Setting it to 0 restores whatever the runtime shipped with,
        /// which is what makes an A/B inside a single raid possible.
        /// </summary>
        internal static void ApplyConfig()
        {
            if (!GarbageCollector.isIncremental)
            {
                return;
            }

            try
            {
                if (!_vanillaSliceCaptured)
                {
                    _vanillaSliceNs = GarbageCollector.incrementalTimeSliceNanoseconds;
                    _vanillaSliceCaptured = true;
                }

                float wantedMs = Plugin.GcTimeSliceMs.Value;
                ulong wanted = wantedMs > 0f
                    ? (ulong)(wantedMs * 1000000f)
                    : _vanillaSliceNs;

                if (GarbageCollector.incrementalTimeSliceNanoseconds != wanted)
                {
                    GarbageCollector.incrementalTimeSliceNanoseconds = wanted;
                    _sliceApplied = wantedMs > 0f;
                }
            }
            catch (Exception e)
            {
                Plugin.LogSource.LogWarning("Framesaver GC: time slice override failed - " + e.Message);
                Plugin.GcTimeSliceMs.Value = 0f;
            }
        }

        /// <summary>
        /// Hands the incremental collector extra time on frames that can afford it, ahead of the point where
        /// something forces a full collection.
        ///
        /// `CollectIncremental` returns true when there is still work outstanding, which is the diagnostic
        /// half: a `pending` count that stays high means the collector is permanently behind, and that is the
        /// signature of candidate 1 above. It costs whatever budget it is given, so the budget is reported
        /// back as `msMax` - an instrument that overruns its own budget is worse than no instrument.
        /// </summary>
        internal static void Drive()
        {
            float budgetMs = Plugin.GcDriveMs.Value;
            if (budgetMs <= 0f || !GarbageCollector.isIncremental)
            {
                return;
            }

            // Never drive a collector that something else has deliberately disabled - AsyncDrain suspends
            // collection around completion callbacks, and forcing work inside that window would undo it.
            if (GarbageCollector.GCMode == GarbageCollector.Mode.Disabled)
            {
                return;
            }

            try
            {
                long start = Stopwatch.GetTimestamp();
                bool pending = GarbageCollector.CollectIncremental((ulong)(budgetMs * 1000000f));
                double ms = (Stopwatch.GetTimestamp() - start) * 1000d / Stopwatch.Frequency;

                _driveCalls++;
                if (pending)
                {
                    _drivePending++;
                }

                _driveMsTotal += ms;
                if (ms > _driveMsMax)
                {
                    _driveMsMax = ms;
                }
            }
            catch (Exception e)
            {
                Plugin.LogSource.LogWarning("Framesaver GC: CollectIncremental failed, disabling - " + e.Message);
                Plugin.GcDriveMs.Value = 0f;
            }
        }

        /// <summary>
        /// Called once per sampled frame, before the spike line for that frame is written. Cheap: two counter
        /// reads and some arithmetic.
        /// </summary>
        internal static void Track()
        {
            // AsyncDrain zeroes GcSuspended per window, so a decrease is a window boundary rather than
            // negative suspensions. Treat the new value as the count since that reset.
            int suspendNow = AsyncDrain.GcSuspended;
            int suspendDelta = suspendNow >= _prevSuspendCount ? suspendNow - _prevSuspendCount : suspendNow;
            _prevSuspendCount = suspendNow;

            if (suspendDelta > 0)
            {
                _suspendsSinceGc += suspendDelta;
                _lastSuspendTicks = Stopwatch.GetTimestamp();
            }

            int gcNow = GC.CollectionCount(0);
            if (gcNow != _prevGcCount)
            {
                // Latch what the run-up to this collection looked like, then start counting again. The spike
                // line for this frame reads these, so they describe the collection that just completed.
                _suspendsBeforeLastGc = _suspendsSinceGc;
                _msSinceSuspendAtLastGc = _lastSuspendTicks == 0L
                    ? -1d
                    : (Stopwatch.GetTimestamp() - _lastSuspendTicks) * 1000d / Stopwatch.Frequency;

                _suspendsSinceGc = 0;
                _prevGcCount = gcNow;
            }
        }

        /// <summary>
        /// Emitted only on spike lines that carry a collection. `suspendsBefore` is how many GC suspensions
        /// happened between the previous collection and this one; `msSinceSuspend` is how long before it the
        /// last one ended, or -1 if there has never been one. If suspension manufactures pauses, expensive
        /// collections cluster at low `msSinceSuspend` and high `suspendsBefore`.
        /// </summary>
        internal static void AppendSpike(StringBuilder sb)
        {
            if (_suspendsBeforeLastGc < 0)
            {
                return;
            }

            sb.Append(",\"gcSuspendsBefore\":").Append(_suspendsBeforeLastGc)
              .Append(",\"gcMsSinceSuspend\":").Append(Fmt(_msSinceSuspendAtLastGc));
        }

        internal static void AppendWindow(StringBuilder sb)
        {
            sb.Append(",\"gcDrive\":{\"calls\":").Append(_driveCalls)
              // Fraction of calls that still had work outstanding. High and sustained means the collector
              // never catches up, which is what candidate 1 predicts.
              .Append(",\"pending\":").Append(_drivePending)
              .Append(",\"msTotal\":").Append(Fmt(_driveMsTotal))
              .Append(",\"msMax\":").Append(Fmt(_driveMsMax))
              .Append(",\"sliceNs\":").Append(SliceNs())
              .Append('}');
        }

        internal static void AppendCfg(StringBuilder sb)
        {
            sb.Append(",\"gcTimeSliceMs\":").Append(Fmt(Plugin.GcTimeSliceMs.Value))
              .Append(",\"gcDriveMs\":").Append(Fmt(Plugin.GcDriveMs.Value))
              .Append(",\"gcSliceApplied\":").Append(_sliceApplied ? "true" : "false");
        }

        private static ulong SliceNs()
        {
            try
            {
                return GarbageCollector.incrementalTimeSliceNanoseconds;
            }
            catch (Exception)
            {
                return 0UL;
            }
        }

        internal static void ResetWindow()
        {
            _driveCalls = 0;
            _drivePending = 0;
            _driveMsTotal = 0d;
            _driveMsMax = 0d;
        }

        private static string Fmt(double value)
        {
            if (double.IsNaN(value) || double.IsInfinity(value))
            {
                return "null";
            }

            return value.ToString("0.###", CultureInfo.InvariantCulture);
        }
    }
}
