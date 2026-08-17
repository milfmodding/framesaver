using System.Diagnostics;

namespace Framesaver.Patches
{
    /// <summary>
    /// Local copy of AiTiming.ToMs (ticks * 1000d / Stopwatch.Frequency).
    ///
    /// Exists because AiTickTimingPatches/AiTiming is measurement-only and moves to Ranger in the
    /// extraction, while the drain budget lever here in AsyncDrainPatch is a shipping feature that
    /// stays. Ruled 2026-08-16 23:13Z (option 1): duplicate the one-liner rather than build
    /// soft-dependency machinery for a stateless unit conversion. If this and AiTiming.ToMs ever
    /// disagree, Stopwatch.Frequency changed on this platform - there is no second tuning constant.
    /// </summary>
    internal static class TickMath
    {
        internal static double ToMs(long ticks)
        {
            return ticks * 1000d / Stopwatch.Frequency;
        }
    }
}
