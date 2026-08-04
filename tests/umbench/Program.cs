using System;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;

// Bench for updateManual's worst-single-call fields.
//
// It drives the REAL accumulator inside the REAL built assembly by
// reflection - not a copy of the logic, which would test nothing. The
// only thing faked is the input, because no raid has run and the code
// path has therefore never executed.
//
// THE FAILURE IT EXISTS TO CATCH is a max that misses ResetWindow and
// silently becomes a session high-water mark. That defect emits a
// plausible number forever, so it cannot be caught by eyeballing output.
//
// ARM B IS THE POSITIVE CONTROL and the reason to trust ARM A: it runs
// the identical comparison with the reset omitted, which IS the defect.
// ARM B MUST FAIL. If both arms pass, the assertion is not testing
// anything and this program exits nonzero saying so.

internal static class Program
{
    private static MethodInfo _add;
    private static MethodInfo _append;
    private static MethodInfo _reset;

    private static int Main(string[] args)
    {
        if (args.Length != 1)
        {
            Console.WriteLine("REFUSED: expected exactly one argument, the path to Framesaver.dll");
            return 86;
        }

        string dll = args[0];
        if (!File.Exists(dll))
        {
            Console.WriteLine("REFUSED: no such file: " + dll);
            return 86;
        }

        Assembly asm = Assembly.LoadFrom(Path.GetFullPath(dll));
        Type t = asm.GetType("Framesaver.Patches.UpdateManualTiming");
        if (t == null)
        {
            Console.WriteLine("REFUSED: Framesaver.Patches.UpdateManualTiming not found in " + dll);
            return 86;
        }

        _add = t.GetMethod("Add", BindingFlags.NonPublic | BindingFlags.Static);
        _append = t.GetMethod("Append", BindingFlags.Public | BindingFlags.Static);
        _reset = t.GetMethod("ResetWindow", BindingFlags.Public | BindingFlags.Static);

        if (_add == null || _append == null || _reset == null)
        {
            Console.WriteLine("REFUSED: Add/Append/ResetWindow not all resolvable - the shape changed");
            return 86;
        }

        Console.WriteLine("dll        " + Path.GetFullPath(dll));
        Console.WriteLine("frequency  " + System.Diagnostics.Stopwatch.Frequency
                          + " ticks/s   (1000 ticks = "
                          + Ms(1000).ToString("0.####", CultureInfo.InvariantCulture) + " ms)");
        Console.WriteLine();

        bool armA = RunArm("A  reset between windows   (the correct behaviour)", true);
        Console.WriteLine();
        bool armB = RunArm("B  NO reset between windows (the defect, control)", false);
        Console.WriteLine();

        // Both halves asserted: the arm that must pass, and the arm that
        // must fail. An exit code alone cannot distinguish "the bench ran
        // and the field is sound" from "the bench never reached the
        // comparison", so each arm prints its verdict line as well.
        Console.WriteLine("EXPECT     A pass, B fail");
        Console.WriteLine("OBSERVED   A " + (armA ? "pass" : "fail") + ", B " + (armB ? "pass" : "fail"));

        if (armA && !armB)
        {
            Console.WriteLine("RESULT     OK - the window reset works and the comparison can detect its absence");
            return 0;
        }

        if (armA && armB)
        {
            Console.WriteLine("RESULT     BROKEN BENCH - arm B passed, so the comparison cannot see a frozen max;"
                              + " arm A's pass means nothing");
            return 1;
        }

        Console.WriteLine("RESULT     FIELD DEFECTIVE - arm A failed: the max does not reset per window");
        return 1;
    }

    // One window's worth of calls, then the flush. Returns the parsed
    // pair so the caller can compare windows.
    private static (double awake, double paused, string json) Window(params (long ticks, bool paused)[] calls)
    {
        foreach ((long ticks, bool paused) in calls)
        {
            _add.Invoke(null, new object[] { ticks, paused });
        }

        StringBuilder sb = new StringBuilder();
        _append.Invoke(null, new object[] { sb });
        string json = sb.ToString();
        return (Field(json, "awakeWorstCallMs"), Field(json, "pausedWorstCallMs"), json);
    }

    private static bool RunArm(string label, bool resetBetween)
    {
        Console.WriteLine(label);

        // Setup, not the thing under test: both arms must start from a
        // clean accumulator or arm B would inherit arm A's leftovers and
        // the control would be measuring the wrong thing.
        _reset.Invoke(null, null);

        // Window 1 carries the tail. 50000 ticks is the "burst"; the
        // paused sample is deliberately tiny, because a paused call runs
        // StandBy.Update() and stops.
        var w1 = Window((1000L, false), (50000L, false), (200L, true));
        Console.WriteLine("  w1  " + w1.json);

        if (resetBetween)
        {
            _reset.Invoke(null, null);
        }

        // Window 2 has NO burst. Its max must therefore be smaller - that
        // is the whole assertion, and a frozen accumulator cannot produce it.
        var w2 = Window((1000L, false));
        Console.WriteLine("  w2  " + w2.json);

        bool fell = w2.awake < w1.awake;
        bool split = w1.paused < w1.awake;
        bool quiet = w2.paused == 0d;

        Console.WriteLine("  awake max fell w1->w2      " + Yes(fell)
                          + "   (" + w1.awake.ToString("0.####", CultureInfo.InvariantCulture)
                          + " -> " + w2.awake.ToString("0.####", CultureInfo.InvariantCulture) + " ms)");
        Console.WriteLine("  paused max below awake     " + Yes(split));
        Console.WriteLine("  paused max 0 in a window with no paused calls  " + Yes(quiet));
        Console.WriteLine("  ARM " + (fell && split && quiet ? "PASS" : "FAIL"));
        return fell && split && quiet;
    }

    private static string Yes(bool b)
    {
        return b ? "yes" : "NO ";
    }

    private static double Ms(long ticks)
    {
        return ticks * 1000d / System.Diagnostics.Stopwatch.Frequency;
    }

    // Deliberately a dumb scan rather than a JSON parser: the thing under
    // test is the emitted text, so a parser that repaired a malformed
    // number would hide exactly the defect worth seeing.
    private static double Field(string json, string key)
    {
        string needle = "\"" + key + "\":";
        int i = json.IndexOf(needle, StringComparison.Ordinal);
        if (i < 0)
        {
            throw new InvalidOperationException("key absent from emitted JSON: " + key + "  in  " + json);
        }

        int start = i + needle.Length;
        int end = start;
        while (end < json.Length && (char.IsDigit(json[end]) || json[end] == '.' || json[end] == '-'))
        {
            end++;
        }

        return double.Parse(json.Substring(start, end - start), CultureInfo.InvariantCulture);
    }
}
