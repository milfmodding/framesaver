using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;

class P {
    const string Managed = @"F:\SPT\SPT4.0.13\EscapeFromTarkov_Data\Managed";
    const string Core    = @"F:\SPT\SPT4.0.13\BepInEx\core";
    const string Sptdir  = @"F:\SPT\SPT4.0.13\BepInEx\plugins\spt";

    static Assembly Resolve(object s, ResolveEventArgs e) {
        string n = new AssemblyName(e.Name).Name + ".dll";
        foreach (var d in new[] { Managed, Core, Sptdir }) {
            var c = Path.Combine(d, n);
            if (File.Exists(c)) { try { return Assembly.LoadFrom(c); } catch { } }
        }
        return null;
    }

    static int bad = 0;
    static void Check(string what, object got, object expect) {
        bool ok = Equals(got, expect);
        if (!ok) bad++;
        Console.WriteLine($"  {(ok ? "ok  " : "FAIL")}  {what,-46} got {got}  expect {expect}");
    }

    static int Main() {
        AppDomain.CurrentDomain.AssemblyResolve += Resolve;
        var asm = Assembly.LoadFrom(@"F:\SPT\Mods\Framesaver\bin\Release\Framesaver.dll");

        var tel = asm.GetType("Framesaver.Telemetry");
        var unwrap = tel.GetMethod("Unwrap", BindingFlags.NonPublic | BindingFlags.Static);
        Console.WriteLine("Telemetry.Unwrap");
        var cases = new (double from, double to, double expect, string why)[] {
            (359.9,   0.1,   0.2, "wrap forward across 0/360"),
            (  0.1, 359.9,  -0.2, "wrap backward across 0/360"),
            (170.0,-170.0,  20.0, "wrap across the -180/180 convention"),
            ( 10.0,  10.0,   0.0, "held view - the case this certifies"),
            (  0.0,-180.0, 180.0, "-180 folds to +180"),
            (  0.0, 720.1,   0.1, "multiple wraps"),
        };
        foreach (var c in cases) {
            double got = (double)unwrap.Invoke(null, new object[] { c.to - c.from });
            bool ok = Math.Abs(got - c.expect) < 1e-9;
            if (!ok) bad++;
            Console.WriteLine($"  {(ok ? "ok  " : "FAIL")}  {c.why,-46} {c.from} -> {c.to} = {got}");
        }

        var pr = asm.GetType("Framesaver.ProtocolRunner");
        var strip = pr.GetMethod("StripComment", BindingFlags.NonPublic | BindingFlags.Static);
        var parse = pr.GetMethod("TryParse",    BindingFlags.NonPublic | BindingFlags.Static);

        Console.WriteLine("\nProtocolRunner.StripComment");
        Check("hash comment",      strip.Invoke(null, new object[]{ "a = 1 # note" }), "a = 1 ");
        Check("semicolon comment", strip.Invoke(null, new object[]{ "a = 1 ; note" }), "a = 1 ");
        Check("earliest of both",  strip.Invoke(null, new object[]{ "a # b ; c" }),    "a ");
        Check("no comment",        strip.Invoke(null, new object[]{ "[A1]" }),         "[A1]");
        Check("whole-line comment",strip.Invoke(null, new object[]{ "# all of it" }),  "");

        Console.WriteLine("\nProtocolRunner.TryParse");
        object v;
        object[] a;
        a = new object[]{ "6",     typeof(float), null }; parse.Invoke(null, a);
        Check("float 6",       a[2], 6f);
        a = new object[]{ "0.5",   typeof(float), null }; parse.Invoke(null, a);
        Check("float 0.5 invariant", a[2], 0.5f);
        a = new object[]{ "true",  typeof(bool),  null }; parse.Invoke(null, a);
        Check("bool true",     a[2], true);
        a = new object[]{ "12",    typeof(int),   null }; parse.Invoke(null, a);
        Check("int 12",        a[2], 12);
        a = new object[]{ "abc",   typeof(float), null };
        Check("float rejects text", parse.Invoke(null, a), false);
        a = new object[]{ "6",     typeof(int),   null };
        Check("int accepts 6",  parse.Invoke(null, a), true);
        a = new object[]{ "6.5",   typeof(int),   null };
        Check("int rejects 6.5", parse.Invoke(null, a), false);
        // Can the mark key be bound to a mouse button from the .cfg alone?
        // Sophia proposed a thumb button; "it needs no code" rests on two
        // things neither of us wrote, so both are checked against the shipped
        // BepInEx and Unity assemblies rather than assumed.
        Console.WriteLine("\nKeyboardShortcut accepts a mouse button from config text");
        var keyCode = Type.GetType("UnityEngine.KeyCode, UnityEngine.CoreModule");
        Check("KeyCode.Mouse3 exists", Enum.IsDefined(keyCode, "Mouse3"), true);
        Check("KeyCode.Mouse4 exists", Enum.IsDefined(keyCode, "Mouse4"), true);

        var ks = Type.GetType("BepInEx.Configuration.KeyboardShortcut, BepInEx");
        var deser = ks.GetMethod("Deserialize", BindingFlags.Public | BindingFlags.Static);
        var shortcut = deser.Invoke(null, new object[] { "Mouse3" });
        Check("Deserialize(Mouse3).MainKey",
              ks.GetProperty("MainKey").GetValue(shortcut).ToString(), "Mouse3");
        Check("round-trips back to text",
              ks.GetMethod("Serialize").Invoke(shortcut, null), "Mouse3");


        // The log header derives `version` and `commit` from AssemblyInformationalVersion.
        // Nothing in the build fails if the SDK stops stamping it: Plugin's split just
        // yields commit:"" and every header goes back to being unattributable, which is
        // the state this replaced. That is a silent regression, so it gets a loud test.
        //
        // The SHAPE is what is checked, not the value. Asserting the sha equals HEAD would
        // fail on any build older than the newest commit - normal, constant, and the fast
        // way to teach everyone to ignore a red line.
        Console.WriteLine("\nBuild stamp the log header reads");
        string dll = FindUp("bin/Release/Framesaver.dll");
        Check("bin/Release/Framesaver.dll found", dll != null, true);
        if (dll != null) {
            // Same string Plugin's static constructor reads: the SDK writes
            // AssemblyInformationalVersion into the Win32 ProductVersion too.
            string informational = FileVersionInfo.GetVersionInfo(dll).ProductVersion ?? "";
            int plus = informational.IndexOf('+');
            Check("informational version has a '+'", plus > 0, true);
            string version = plus < 0 ? informational : informational.Substring(0, plus);
            string commit  = plus < 0 ? "" : informational.Substring(plus + 1);
            Check("version before '+' is non-empty", version.Length > 0, true);
            Check("commit after '+' is a 40-hex sha", commit.Length == 40
                  && commit.All(Uri.IsHexDigit), true);
        }

        Console.WriteLine(bad == 0 ? "\nall cases pass (against shipped IL)" : $"\n{bad} FAILURES");
        return bad == 0 ? 0 : 1;
    }

    /// <summary>
    /// Nearest ancestor of the test binary containing <paramref name="relative"/>, or null.
    /// Searched rather than counted in "../.." because the test output path has moved once
    /// already and a wrong count fails as "file not found", which reads like a missing build.
    /// </summary>
    static string FindUp(string relative) {
        for (var d = new DirectoryInfo(AppContext.BaseDirectory); d != null; d = d.Parent) {
            string c = Path.Combine(d.FullName, relative);
            if (File.Exists(c)) return c;
        }
        return null;
    }
}
