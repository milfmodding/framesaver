using System;
using System.IO;
using System.Linq;
using System.Reflection;

class P {
    const string Managed = @"F:\SPT\SPT4.0.13\EscapeFromTarkov_Data\Managed";
    const string Core    = @"F:\SPT\SPT4.0.13\BepInEx\core";
    const string Sptdir  = @"F:\SPT\SPT4.0.13\BepInEx\plugins\spt";

    static Assembly Resolve(object sender, ResolveEventArgs e) {
        string name = new AssemblyName(e.Name).Name + ".dll";
        foreach (var dir in new[] { Managed, Core, Sptdir }) {
            var c = Path.Combine(dir, name);
            if (File.Exists(c)) { try { return Assembly.LoadFrom(c); } catch { } }
        }
        return null;
    }

    static int Main() {
        AppDomain.CurrentDomain.AssemblyResolve += Resolve;
        var asm = Assembly.LoadFrom(@"F:\SPT\Mods\Framesaver\bin\Release\Framesaver.dll");
        Type t = null;
        try { t = asm.GetType("Framesaver.Telemetry"); }
        catch (Exception ex) { Console.WriteLine("GetType threw: " + ex.GetType().Name); }
        if (t == null) { Console.WriteLine("FAIL: Telemetry type not found"); return 2; }
        var m = t.GetMethod("Unwrap", BindingFlags.NonPublic | BindingFlags.Static);
        if (m == null) { Console.WriteLine("FAIL: Unwrap not found"); return 2; }

        var cases = new (double from, double to, double expect, string why)[] {
            (359.9,   0.1,   0.2, "wrap forward across 0/360"),
            (  0.1, 359.9,  -0.2, "wrap backward across 0/360"),
            (170.0,-170.0,  20.0, "wrap across the -180/180 convention"),
            (-170.0, 170.0, -20.0, "wrap back"),
            ( 10.0,  10.0,   0.0, "held view - the case this exists to certify"),
            (  0.0, 180.0, 180.0, "exactly at the fold boundary"),
            (  0.0,-180.0, 180.0, "-180 folds to +180"),
            (  0.0,  90.0,  90.0, "ordinary"),
            (  0.0, 720.1,   0.1, "multiple wraps"),
        };
        int bad = 0;
        foreach (var c in cases) {
            double got = (double)m.Invoke(null, new object[] { c.to - c.from });
            bool ok = Math.Abs(got - c.expect) < 1e-9;
            if (!ok) bad++;
            Console.WriteLine($"  {c.from,7} -> {c.to,7}  expect {c.expect,7}  got {got,7}  {(ok ? "ok" : "FAIL")}   {c.why}");
        }
        Console.WriteLine(bad == 0 ? "\nall unwrap cases pass (against shipped IL)" : "\n" + bad + " FAILURES");
        return bad == 0 ? 0 : 1;
    }
}
