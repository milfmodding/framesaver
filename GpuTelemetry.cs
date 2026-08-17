using System;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using Comfort.Common;
using UnityEngine;

namespace Framesaver
{
    /// <summary>
    /// Wall clock and graphics context. Everything else in this mod measures the main thread; this
    /// file carries the two instruments that are not measurement at all:
    ///
    ///   qpc           the wall-clock stamp on every telemetry line - P/Invoked QueryPerformanceCounter,
    ///                 so the ndjson joins against an external capture such as PresentMon. See Qpc's own
    ///                 doc for why Stopwatch cannot do this under Mono.
    ///   gfx blocks    graphics CONFIG, not GPU timing - render resolution vs screen (the pair that
    ///                 keeps a GPU-bound conclusion from being made for a CPU-bound config), plus
    ///                 vSync/targetFps/mipLimit/Reflex/DLSS/FSR per window and the device identity on
    ///                 the header.
    ///
    /// The GPU instruments (vram DXGI query, FrameTimingManager, render counters) lived here until
    /// 2026-08-17, when Sophia's ruling archived them: SPT's problems are CPU-bound, none of the
    /// three ever paid off, and the build lacked the flags two of them wanted anyway. Preserved in
    /// git history for Ranger's "if ever" mode; resurrectable as one file. The graphics blocks STAY
    /// deliberately - they are the evidence behind the CPU-bound conclusion itself, not a casualty
    /// of it.
    /// </summary>
    internal static class GpuTelemetry
    {
        // ---- wall clock ---------------------------------------------------------------------

        [DllImport("kernel32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool QueryPerformanceCounter(out long value);

        [DllImport("kernel32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool QueryPerformanceFrequency(out long value);

        private static bool _qpcChecked;
        private static bool _qpcUsable;

        /// <summary>
        /// True QPC, for joining against an external capture such as PresentMon.
        ///
        /// Stopwatch.GetTimestamp() is NOT this under Mono. On .NET it returns the raw QueryPerformanceCounter
        /// value; Mono returns 100ns ticks measured from *process start*. Both report Stopwatch.Frequency as
        /// 10,000,000, so the tick rate matches and durations are correct either way - but the epoch does not,
        /// and the two series simply do not overlap. Measured on the 2026-07-27 Streets run: PresentMon
        /// timestamps sat at 5.19e12 while Stopwatch reported 1.07e9 to 1.00e10, and the join had to be
        /// recovered afterwards by matching a 37-second stall in both files by hand.
        ///
        /// P/Invoking QueryPerformanceCounter gives the value PresentMon actually writes. Durations elsewhere
        /// in this mod stay on Stopwatch, which is correct for deltas and cheaper.
        /// </summary>
        internal static long Qpc()
        {
            if (!_qpcChecked)
            {
                _qpcChecked = true;
                try
                {
                    long probe;
                    _qpcUsable = QueryPerformanceCounter(out probe);
                }
                catch (Exception)
                {
                    _qpcUsable = false;
                }

                if (!_qpcUsable)
                {
                    Plugin.LogSource.LogWarning(
                        "Framesaver GPU: QueryPerformanceCounter unavailable; qpc falls back to Stopwatch, "
                        + "which under Mono is process-relative and will not join against an external capture.");
                }
            }

            if (_qpcUsable)
            {
                long now;
                if (QueryPerformanceCounter(out now))
                {
                    return now;
                }
            }

            return Stopwatch.GetTimestamp();
        }

        /// <summary>Ticks per second for <see cref="Qpc"/>, so the stamps convert to seconds.</summary>
        internal static long QpcFrequency()
        {
            try
            {
                long freq;
                if (QueryPerformanceFrequency(out freq) && freq > 0L)
                {
                    return freq;
                }
            }
            catch (Exception)
            {
                // fall through
            }

            return Stopwatch.Frequency;
        }

        // CONSTRAINT ON EVERY FIELD BELOW: no field in this class may be typed with a game type
        // (`CameraClass`, `GraphicsSettingsClass`, `SharedGameSettingsClass`, any `GClass*`). Those names are
        // obfuscated and move between SPT versions, and a static field of one moves the resolution failure
        // into this class's *type initialiser* - which no guard inside the class can catch, and which then
        // poisons every member, including `Qpc()` that `Telemetry` calls without a guard. Game types belong
        // in method bodies reached through `Guarded`, where the JIT-time failure lands inside a try.
        //
        // See FINDINGS.md methodology notes, "a try inside a method does not protect against a
        // type-resolution failure in that method".

        /// <summary>
        /// Set if anything in this file throws in a way its own guards could not catch, after which none of it
        /// runs again.
        ///
        /// The per-block try/catch below is not sufficient on its own. A missing or renamed type - a game
        /// type referenced by the graphics-config readers - fails when the *method referencing it is
        /// JIT-compiled*, before its body executes, so the `try` inside that method never gets the chance to
        /// catch it. The exception surfaces at the call site instead, which is inside Telemetry's window
        /// builder, and it would take out every other instrument on that line along with this one.
        /// </summary>
        private static bool _fatal;
        private static void Fatal(Exception e, string where)
        {
            _fatal = true;
            try
            {
                Plugin.LogSource.LogError(
                    "Framesaver GPU: disabled after an unrecoverable error in " + where + " - " + e);
            }
            catch (Exception)
            {
                // Never take the game down over telemetry, including over failing to log about telemetry.
            }
        }

        /// <summary>
        /// Rolls the StringBuilder back to where it was if the body throws. A half-written field would make
        /// the whole line invalid JSON and cost the window that contains it, which is a worse outcome than
        /// losing this block.
        /// </summary>
        private static void Guarded(StringBuilder sb, Action<StringBuilder> body, string where)
        {
            if (_fatal)
            {
                return;
            }

            int mark = sb.Length;
            try
            {
                body(sb);
            }
            catch (Exception e)
            {
                sb.Length = mark;
                Fatal(e, where);
            }
        }

        private static readonly Action<StringBuilder> WindowBody = AppendWindowCore;
        private static readonly Action<StringBuilder> GraphicsBody = AppendGraphicsConfigCore;
        private static readonly Action<StringBuilder> HeaderBody = AppendHeaderCore;

        internal static void AppendWindow(StringBuilder sb)
        {
            Guarded(sb, WindowBody, "AppendWindow");
        }

        private static void AppendWindowCore(StringBuilder sb)
        {
            // The per-window GPU block (`gpu:{...}`) is archived with the instruments. The one thing this
            // block still owns is the once-per-session graphics settings dump, which lands on the first
            // window line that can resolve the settings singleton.
            AppendSettingsDumpOnce(sb);
        }

        /// <summary>
        /// Graphics state on every window line. These are not our config, but they change what every other
        /// number in the file means, and EFT's settings are editable mid-session from the graphics tab - so a
        /// header written at load can lie about them for exactly the same reason the BepInEx block can.
        /// Reflex in particular rewrites targetFrameRate and vSyncCount when it is switched on.
        /// </summary>
        internal static void AppendGraphicsConfig(StringBuilder sb)
        {
            Guarded(sb, GraphicsBody, "AppendGraphicsConfig");
        }

        private static void AppendGraphicsConfigCore(StringBuilder sb)
        {
            sb.Append(",\"gfx\":{");
            sb.Append("\"screen\":\"").Append(Screen.width).Append('x').Append(Screen.height).Append('"');

            // Internal render resolution, which is what the GPU actually shades. With FSR3 Balanced this is
            // 0.588x per axis, so it is roughly a third of the pixels the screen resolution implies - and
            // reading frame times against the wrong one of those two is how a GPU-bound conclusion gets made
            // for a config that is nowhere near GPU-bound.
            try
            {
                Camera cam = EFT.CameraControl.CameraManager.Exist ? EFT.CameraControl.CameraManager.Instance.Camera : null;
                if (cam != null)
                {
                    sb.Append(",\"render\":\"").Append(cam.pixelWidth).Append('x').Append(cam.pixelHeight).Append('"');
                }
            }
            catch (Exception)
            {
                // Camera rig not up yet; the screen resolution above is still worth having.
            }

            sb.Append(",\"vSyncCount\":").Append(QualitySettings.vSyncCount);
            sb.Append(",\"targetFps\":").Append(Application.targetFrameRate);
            sb.Append(",\"mipLimit\":").Append(QualitySettings.globalTextureMipmapLimit);
            sb.Append(",\"lodBias\":").Append(Fmt(QualitySettings.lodBias));

            try
            {
                EFT.Settings.Graphics.GraphicsSettingsGroup g = GraphicsSettings();
                if (g != null)
                {
                    sb.Append(",\"reflex\":\"").Append(g.NVidiaReflex.Value).Append('"');
                    sb.Append(",\"textureQuality\":").Append(g.TextureQuality.Value);
                    sb.Append(",\"mipStreaming\":").Append(g.MipStreaming.Value ? "true" : "false");
                    sb.Append(",\"dlss\":\"").Append(g.DLSSMode.Value).Append('"');
                    sb.Append(",\"fsr2\":\"").Append(g.FSR2Mode.Value).Append('"');
                    sb.Append(",\"fsr3\":\"").Append(g.FSR3Mode.Value).Append('"');
                    sb.Append(",\"aa\":\"").Append(g.AntiAliasing.Value).Append('"');
                }
            }
            catch (Exception)
            {
                // Settings singleton not up yet. The QualitySettings values above are read straight from Unity
                // and are always valid, so a partial block beats no block.
            }

            sb.Append('}');
        }

        /// <summary>
        /// Full graphics dump, written once. Everything here is either immutable for the session or too
        /// verbose to repeat per line; the mutable subset lives in AppendGraphicsConfig.
        /// </summary>
        internal static void AppendHeader(StringBuilder sb)
        {
            Guarded(sb, HeaderBody, "AppendHeader");
        }

        private static void AppendHeaderCore(StringBuilder sb)
        {
            sb.Append(",\"gpuDevice\":{");
            sb.Append("\"name\":\"").Append(Escape(SystemInfo.graphicsDeviceName)).Append('"');
            sb.Append(",\"api\":\"").Append(Escape(SystemInfo.graphicsDeviceType.ToString())).Append('"');
            sb.Append(",\"driver\":\"").Append(Escape(SystemInfo.graphicsDeviceVersion)).Append('"');
            sb.Append(",\"vramMb\":").Append(SystemInfo.graphicsMemorySize);
            sb.Append(",\"multiThreaded\":").Append(SystemInfo.graphicsMultiThreaded ? "true" : "false");
            sb.Append('}');

            // Deliberately not the graphics settings: the settings singleton does not exist yet at plugin load,
            // so a dump written here says only "not instantiated". AppendSettingsDumpOnce puts it on the first
            // window line that can actually resolve it.
        }

        private static bool _settingsDumped;

        /// <summary>
        /// The full graphics dump, emitted once on the first window line where the settings singleton exists.
        /// Everything here is either immutable for the session or too verbose to repeat per line; the mutable
        /// subset that matters lives in AppendGraphicsConfig and goes on every line.
        /// </summary>
        private static void AppendSettingsDumpOnce(StringBuilder sb)
        {
            if (_settingsDumped)
            {
                return;
            }

            EFT.Settings.Graphics.GraphicsSettingsGroup probe = null;
            try
            {
                probe = GraphicsSettings();
            }
            catch (Exception)
            {
                // Retry on the next window.
            }

            if (probe == null)
            {
                return;
            }

            _settingsDumped = true;

            sb.Append(",\"gfxSettings\":{");
            try
            {
                EFT.Settings.Graphics.GraphicsSettingsGroup g = probe;
                {
                    sb.Append("\"textureQuality\":").Append(g.TextureQuality.Value);
                    sb.Append(",\"mipStreaming\":").Append(g.MipStreaming.Value ? "true" : "false");
                    sb.Append(",\"mipStreamingBufferSize\":").Append(g.MipStreamingBufferSize.Value);
                    sb.Append(",\"shadowsQuality\":").Append(g.ShadowsQuality.Value);
                    // ShadowDistance and SuperSamplingFactor are plain derived properties on the settings
                    // object, not GameSetting<T> bindables like the rest.
                    sb.Append(",\"shadowDistance\":").Append(Fmt(g.ShadowDistance));
                    sb.Append(",\"overallVisibility\":").Append(Fmt(g.OverallVisibility.Value));
                    sb.Append(",\"lodBias\":").Append(Fmt(g.LodBias.Value));
                    sb.Append(",\"superSamplingFactor\":").Append(Fmt(g.SuperSamplingFactor));
                    sb.Append(",\"vSync\":").Append(g.VSync.Value ? "true" : "false");
                    sb.Append(",\"gameFramerate\":").Append(g.GameFramerate.Value);
                    sb.Append(",\"reflex\":\"").Append(g.NVidiaReflex.Value).Append('"');
                }
            }
            catch (Exception e)
            {
                sb.Append("\"error\":\"").Append(Escape(e.GetType().Name + ": " + e.Message)).Append('"');
            }

            sb.Append('}');
        }

        // Deliberately not probed: GClass3692.IsReflexAvailable(). It looks like a free capability query and is
        // not one - it latches a static Bool_0 on any error or NvReflex_ERROR status, and GClass3692 short
        // circuits to "unavailable" forever once that is set (only Dispose, on camera teardown, clears it).
        // Probing it early enough to put in the header would mean a failed probe silently preventing Reflex
        // from ever initialising - disabling the feature we want to measure, in the file that measures it.
        // The `reflex` setting value plus whether frame reports ever appear answers the same question safely.

        private static EFT.Settings.Graphics.GraphicsSettingsGroup GraphicsSettings()
        {
            // 4.1: SharedGameSettingsClass survives as EFT.Settings.SettingsManager; Graphics is a
            // SettingsWithController<GraphicsSettingsGroup, ...> whose inherited `.Settings` field is
            // the group this returns. Reached through Singleton - if SettingsManager does not register
            // itself there, Instantiated stays false and this yields null, which the callers already treat
            // as "no settings yet" rather than an error.
            if (!Singleton<EFT.Settings.SettingsManager>.Instantiated)
            {
                return null;
            }

            EFT.Settings.SettingsManager shared = Singleton<EFT.Settings.SettingsManager>.Instance;
            return shared != null && shared.Graphics != null ? shared.Graphics.Settings : null;
        }

        private static string Fmt(double value)
        {
            if (double.IsNaN(value) || double.IsInfinity(value))
            {
                return "null";
            }

            return value.ToString("0.###", CultureInfo.InvariantCulture);
        }

        private static string Escape(string value)
        {
            return string.IsNullOrEmpty(value) ? "" : value.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }
    }
}
