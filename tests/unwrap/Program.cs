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
    static int ran = 0;
    static void Check(string what, object got, object expect) {
        bool ok = Equals(got, expect);
        ran++;
        if (!ok) bad++;
        Console.WriteLine($"  {(ok ? "ok  " : "FAIL")}  {what,-46} got {got}  expect {expect}");
    }

    static int Main(string[] args) {
        AppDomain.CurrentDomain.AssemblyResolve += Resolve;

        // ONE resolution of the assembly under test. It was two - a hardcoded
        // absolute path here, and a FindUp below feeding the version-stamp and
        // raw-image sections - so the suite could reflect over one binary while
        // reading bytes from another and nothing would say so.
        //
        // The optional argument exists because running this suite USED to
        // require a build into bin/Release, and bin/Release is SHARED STATE: on
        // 2026-08-04 one seat's compile-check overwrote another seat's binary,
        // which was the only copy of a build being reasoned about. Build to a
        // private -p:OutputPath and point this at it instead.
        //
        // Refusing on absence rather than skipping: the floor check at the
        // bottom of this file complains that half these sections sit behind an
        // `if` - "a null dll" is the first example it names - so a missing
        // binary quietly cost its checks and the run still printed green.
        string dll = args.Length > 0 ? args[0] : FindUp("bin/Release/Framesaver.dll");
        if (dll == null) {
            Console.WriteLine("REFUSED: no Framesaver.dll found. Pass its path as the first "
                              + "argument, or build bin/Release/Framesaver.dll first.");
            return 86;
        }
        Console.WriteLine($"assembly under test: {dll}");
        var asm = Assembly.LoadFrom(dll);

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
            // Through Check rather than its own tally, so these six count toward
            // the floor at the bottom. The comparison stays a tolerance one; only
            // the bookkeeping is shared.
            Check($"{c.why} ({c.from} -> {c.to})", Math.Abs(got - c.expect) < 1e-9, true);
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
        // The "dll found" assertion that used to sit here is gone, not lost: it
        // could no longer fail, because Main now refuses on a null dll before
        // any section runs. A tautological assertion is worse than none - it
        // reports coverage it does not have. The `if` is kept so this section
        // reads the same as the others; it is simply always taken now.
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

        // The awake/paused split is the whole instrument: the number Alpha wants is a
        // DIFFERENCE of two per-call means, so a bucket landing in the wrong total is not a
        // small error, it is a sign error. Driven through the same statics the patch uses.
        Console.WriteLine("\nUpdateManualTiming buckets and emitted shape");
        var umt = asm.GetType("Framesaver.Patches.UpdateManualTiming");
        var add = umt.GetMethod("Add", BindingFlags.NonPublic | BindingFlags.Static);
        var unstamped = umt.GetMethod("AddUnstamped", BindingFlags.NonPublic | BindingFlags.Static);
        var append = umt.GetMethod("Append", BindingFlags.Public | BindingFlags.Static);
        var reset = umt.GetMethod("ResetWindow", BindingFlags.Public | BindingFlags.Static);

        reset.Invoke(null, null);
        long freq = Stopwatch.Frequency;
        add.Invoke(null, new object[] { freq / 1000, false });      // 1.0 ms awake
        add.Invoke(null, new object[] { freq / 1000, false });      // 1.0 ms awake
        add.Invoke(null, new object[] { freq / 4000, true  });      // 0.25 ms paused
        unstamped.Invoke(null, null);

        var sb = new System.Text.StringBuilder();
        append.Invoke(null, new object[] { sb });
        string json = sb.ToString();
        Check("awake ticks land in awakeMs", json.Contains("\"awakeMs\":2"), true);
        Check("awake calls counted",         json.Contains("\"awakeCalls\":2"), true);
        Check("paused ticks do NOT land in awakeMs", json.Contains("\"pausedMs\":0.25"), true);
        Check("paused calls counted",        json.Contains("\"pausedCalls\":1"), true);
        Check("skipped prefix is counted, not silently dropped",
              json.Contains("\"unstampedCalls\":1"), true);

        // Corpses tick UpdateManual and read as AWAKE:
        // BotsClass.UpdateByUnity has no liveness test and the guard is
        // INSIDE the method, after our postfix. Counted as a subset rather
        // than removed, so no existing log changes meaning. Subtract it
        // before quoting a per-bot cost - a long raid with many deaths is
        // not cheaper per live bot, it has more corpses in the denominator.
        var addDead = umt.GetMethod("AddDead", BindingFlags.NonPublic | BindingFlags.Static);
        addDead.Invoke(null, new object[] { freq / 8000 });   // 0.125 ms
        addDead.Invoke(null, new object[] { freq / 8000 });
        var deadSb = new System.Text.StringBuilder();
        append.Invoke(null, new object[] { deadSb });
        string deadJson = deadSb.ToString();
        Check("dead calls counted", deadJson.Contains("\"deadCalls\":2"), true);
        Check("and NOT subtracted from awakeCalls", deadJson.Contains("\"awakeCalls\":2"), true);
        // deadMs as well as deadCalls, or the reconciliation cannot close:
        // the per-bot rows sum to awakeMs MINUS deadMs, and without the ms
        // term a reader can see that corpses were counted but not subtract
        // them.
        Check("dead ms recorded too", deadJson.Contains("\"deadMs\":0.25"), true);

        // A window boundary has to zero every field, or the first window after a busy one
        // reports the busy one's totals against its own call counts - the hold-last-value
        // shape that cost us 40 loading windows on aiTotal.
        reset.Invoke(null, null);
        var sb2 = new System.Text.StringBuilder();
        append.Invoke(null, new object[] { sb2 });
        // WHOLE-STRING, not Contains, and that is load-bearing: it is the only
        // assertion here that fires when a field is ADDED. Gamma's two worst-call
        // fields (db6c04c) landed after this literal was written and it failed on
        // the next run - which is the check doing its job, and is also the
        // evidence that their window reset covers them. Both read 0 after the
        // reset; if either had missed ResetWindow it would be a session
        // high-water mark, and this line is what would say so.
        Check("ResetWindow zeroes every field",
              sb2.ToString(), "{\"awakeMs\":0,\"awakeCalls\":0,\"pausedMs\":0,"
                              + "\"pausedCalls\":0,\"unstampedCalls\":0,"
                              + "\"deadCalls\":0,\"deadMs\":0,"
                              + "\"awakeWorstCallMs\":0,\"pausedWorstCallMs\":0}");

        // The point of this block is one field: forcedButExcluded must be null when either
        // half was not observed, and [] only when both were and the answer really is empty.
        // An empty list IS the all-clear, so "could not compute" must never be able to
        // impersonate one - that is the exact shape that has cost us four tests already.
        Console.WriteLine("\nBossSpawnGate intersection, and its absent-vs-empty distinction");
        var gate = asm.GetType("Framesaver.Patches.BossSpawnGate");
        var recW = gate.GetMethod("RecordWaves", BindingFlags.NonPublic | BindingFlags.Static);
        var recS = gate.GetMethod("RecordSettings", BindingFlags.NonPublic | BindingFlags.Static);
        var gAppend = gate.GetMethod("Append", BindingFlags.Public | BindingFlags.Static);

        var blsType = recW.GetParameters()[0].ParameterType.GetElementType();
        var botAmount = recW.GetParameters()[2].ParameterType;
        var ctrlType = recS.GetParameters()[0].ParameterType;

        Func<string, bool, float, object> wave = (name, force, chance) => {
            object w = Activator.CreateInstance(blsType);
            blsType.GetField("BossName").SetValue(w, name);
            blsType.GetField("ForceSpawn").SetValue(w, force);
            blsType.GetField("BossChance").SetValue(w, chance);
            // BossType directly rather than via ParseMainTypesTypes, which also parses
            // escort type and both difficulty strings. What is under test is the
            // intersection, not BSG's parser.
            var bossType = blsType.GetProperty("BossType");
            bossType.SetValue(w, Enum.Parse(bossType.PropertyType, name));
            return w;
        };

        Func<string> emit = () => {
            var b = new System.Text.StringBuilder();
            gAppend.Invoke(null, new object[] { b });
            return b.ToString();
        };

        Func<string[], object> settings = names => {
            object s = Activator.CreateInstance(ctrlType);
            ctrlType.GetField("ExcludedBosses").SetValue(s, names);
            ctrlType.GetField("BotAmount").SetValue(s, Enum.Parse(botAmount, "AsOnline"));
            return s;
        };

        var waves = Array.CreateInstance(blsType, 2);
        waves.SetValue(wave("exUsec", true, 100f), 0);
        waves.SetValue(wave("bossBoar", true, 100f), 1);

        // Waves only: settings never observed, so the answer is unknown, not clear.
        recW.Invoke(null, new object[] { waves, true, Enum.Parse(botAmount, "AsOnline") });
        Check("waves alone -> forcedButExcluded is null, NOT []",
              emit().Contains("\"forcedButExcluded\":null"), true);

        // Both halves, nothing excluded: this is the real all-clear.
        recS.Invoke(null, new object[] { settings(new string[0]) });
        Check("both halves, none excluded -> []",
              emit().Contains("\"forcedButExcluded\":[]"), true);

        // Both halves, a forced role excluded: the failure announces itself.
        recW.Invoke(null, new object[] { waves, true, Enum.Parse(botAmount, "AsOnline") });
        recS.Invoke(null, new object[] { settings(new[] { "bossBoar" }) });
        Check("forced role excluded -> named in forcedButExcluded",
              emit().Contains("\"forcedButExcluded\":[\"bossBoar\"]"), true);

        // An unparseable exclusion blocks nothing, because SetBlockedRoles uses TryParse.
        // It must show in excludedRaw and NOT in the intersection.
        recW.Invoke(null, new object[] { waves, true, Enum.Parse(botAmount, "AsOnline") });
        recS.Invoke(null, new object[] { settings(new[] { "BossBoar" }) });
        string typo = emit();
        Check("typo'd exclusion is visible in excludedRaw", typo.Contains("\"BossBoar\""), true);
        Check("typo'd exclusion excludes nothing, matching TryParse",
              typo.Contains("\"forcedButExcluded\":[]"), true);

        // A new raid whose vmethod_1 never fired must not inherit the last raid's answer.
        recW.Invoke(null, new object[] { waves, true, Enum.Parse(botAmount, "AsOnline") });
        string restaged = emit();
        Check("RecordWaves clears the settings half", restaged.Contains("\"sawSettings\":false"), true);
        Check("...so a stale intersection cannot survive into a new raid",
              restaged.Contains("\"forcedButExcluded\":null"), true);

        // The header must carry the SPT version, because the criterion that excludes the
        // Base corpus lives outside the data and would otherwise stay there. Reflection
        // rather than a literal, so a version bump cannot leave the field stale - which
        // is the same failure the build-commit stamp above exists to prevent.
        Console.WriteLine("\nHeader records what the numbers were measured against");
        // AppendPlatform itself cannot run here - Application.version and unityVersion are
        // engine ECalls that throw outside the Unity runtime. SptVersion is split out for
        // exactly that reason, and it is the field that actually needs checking.
        var sptVersion = tel.GetMethod("SptVersion", BindingFlags.NonPublic | BindingFlags.Static);
        Check("Telemetry.SptVersion exists", sptVersion != null, true);
        Check("Telemetry.AppendPlatform exists",
              tel.GetMethod("AppendPlatform", BindingFlags.NonPublic | BindingFlags.Static) != null, true);
        if (sptVersion != null) {
            string got = (string)sptVersion.Invoke(null, null);
            // Must come from the loaded assembly, never a literal someone forgets to bump -
            // the same failure the build-commit stamp above exists to prevent.
            string want = Assembly.LoadFrom(Path.Combine(Sptdir, "spt-reflection.dll"))
                          .GetName().Version.ToString();
            Check("sptAssembly is read from the assembly, not written down", got, want);
            Check("sptAssembly is non-empty", got.Length > 0, true);
        }

        // The three provenance blocks an outside tester cannot certify. Existence only:
        // every value inside them is a Unity ECall that throws outside the runtime, so
        // what is checkable here is that the emitters exist and are wired in - which is
        // exactly the failure a rename or a dropped call would cause.
        foreach (var m in new[] { "AppendDisplay", "AppendSystem" })
            Check($"Telemetry.{m} exists",
                  tel.GetMethod(m, BindingFlags.NonPublic | BindingFlags.Static) != null, true);
        Check("ModCompat.AppendDetected exists (mod list, per-window not header)",
              asm.GetType("Framesaver.ModCompat")
                 .GetMethod("AppendDetected", BindingFlags.NonPublic | BindingFlags.Static) != null, true);

        // The bot ledger. The hooks and the emitted values need a live game, so what is
        // checkable here is the contract Alpha's reconciliation is written against: the
        // type names, the pairing key, and that the three killer states are all reachable
        // and distinct. A collapse from three to two is the failure that would overstate
        // Sophia in the one field the segmentation depends on.
        Console.WriteLine("\nBot ledger contract");
        var botLog = asm.GetType("Framesaver.Patches.BotLog");
        Check("BotLog exists", botLog != null, true);
        foreach (var m in new[] { "Spawn", "Drain", "ResetForRaid", "Subscribe" })
            Check($"BotLog.{m} exists",
                  botLog.GetMethod(m, BindingFlags.NonPublic | BindingFlags.Public
                                      | BindingFlags.Static) != null, true);

        // Read the emitted literals out of the shipped IL, so a rename that silently
        // breaks the reconciliation fails here rather than in an analysis three weeks on.
        //
        // Byte search, not File.ReadAllText(Encoding.Unicode): #US literals are UTF-16 but
        // not guaranteed 2-byte aligned to the file start, so a decode from offset 0 misses
        // any literal at an odd offset. That is a check whose failure looks like a missing
        // field - which is the shape this whole file exists to catch.
        byte[] image = File.ReadAllBytes(dll);
        Func<string, bool> inUs = lit => {
            byte[] pat = System.Text.Encoding.Unicode.GetBytes(lit);
            for (int i = 0; i + pat.Length <= image.Length; i++) {
                int j = 0;
                while (j < pat.Length && image[i + j] == pat[j]) j++;
                if (j == pat.Length) return true;
            }
            return false;
        };

        // botStandBy carries the EFFECTIVE grant beside the role property.
        // botSpawn.canStandBy cannot answer it: Create is a static factory at
        // BotOwner.cs:1033 and InitPoints runs at :1772 on the activation
        // path, so at spawn-write time the grant has not been decided. The
        // pair is the measurement - under forceAllRoles a bot reads false on
        // roleAllows while holding a true grant.
        foreach (var lit in new[] { "{\"type\":\"botStandBy\"", ",\"effective\":",
                                    ",\"roleAllows\":", ",\"forced\":" })
            Check($"emits {lit}", inUs(lit), true);

        foreach (var lit in new[] { "{\"type\":\"botSpawn\"", "{\"type\":\"death\"",
                                    "\"killerState\":\"named\"", "\"killerState\":\"none\"",
                                    "\"killerState\":\"unread\"", ",\"canStandBy\":",
                                    ",\"raidElapsed\":null" })
            Check($"emits {lit}", inUs(lit), true);

        // A literal the code does NOT emit must not be found, or the search above proves
        // nothing - every check so far would pass against a matcher that returns true.
        Check("the search can fail (control)", inUs("{\"type\":\"botDeath\""), false);

        // ---- Posted-role sleep distance --------------------------------
        //
        // The table is read out of the shipped IL and compared against enum
        // VALUES derived independently from EFT/WildSpawnType.cs, not against
        // the names it was written from. A name that still compiles after the
        // enum shifts between game versions is exactly the failure a name-only
        // check cannot see, and it would silently give the wider distance to
        // whichever role now holds that number.
        Console.WriteLine("\nRoleSleepDistance table");
        var rsd = asm.GetType("Framesaver.Patches.RoleSleepDistance");
        var postedField = rsd.GetField("Posted", BindingFlags.NonPublic | BindingFlags.Static);
        var wst = postedField.FieldType.GetGenericArguments()[0];
        var haveRoles = new System.Collections.Generic.SortedDictionary<string, int>(StringComparer.Ordinal);
        foreach (var role in (System.Collections.IEnumerable)postedField.GetValue(null))
            haveRoles[role.ToString()] = Convert.ToInt32(role);

        var wantRoles = new System.Collections.Generic.SortedDictionary<string, int>(StringComparer.Ordinal) {
            { "bossKilla", 6 }, { "bossKojaniy", 7 }, { "followerKojaniy", 8 },
            { "sectantWarrior", 20 }, { "sectantPriest", 21 }, { "exUsec", 24 },
            { "bossZryachiy", 29 }, { "followerZryachiy", 30 }, { "bossBoarSniper", 36 },
            { "sectantPredvestnik", 57 }, { "sectantPrizrak", 58 }, { "sectantOni", 59 },
            { "bossKillaAgro", 66 },
        };
        Check("table size", haveRoles.Count, wantRoles.Count);
        foreach (var kv in wantRoles)
            Check($"{kv.Key} is still {kv.Value}", haveRoles.TryGetValue(kv.Key, out int found) ? found : -1, kv.Value);

        var applies = rsd.GetMethod("Applies", BindingFlags.NonPublic | BindingFlags.Static);
        Func<string, bool> covers = n => (bool)applies.Invoke(null, new[] { Enum.Parse(wst, n) });
        // marksman is absent ON PURPOSE - LongRangeExemption already ranks
        // it, and giving it a distance too would change an arm the corpus has
        // measured. Asserted so a future reader cannot "fix" the omission
        // without a test telling them it was a decision.
        Check("marksman deliberately NOT covered", covers("marksman"), false);
        Check("assault not covered (control)", covers("assault"), false);
        Check("exUsec covered", covers("exUsec"), true);

        // The widen-only guard. A value at or below the global sleep
        // distance disables the rule; it must never make the posted roles
        // sleep CLOSER than everything else, which is the inversion nobody
        // would think to look for.
        var effFrom = rsd.GetMethod("EffectiveFrom", BindingFlags.NonPublic | BindingFlags.Static);
        var wakeFrom = rsd.GetMethod("WakeFrom", BindingFlags.NonPublic | BindingFlags.Static);
        Check("350 over a 150 global widens", effFrom.Invoke(null, new object[] { 350f, 150f }), 350f);
        Check("equal to global disables",      effFrom.Invoke(null, new object[] { 150f, 150f }), 0f);
        Check("below global disables",         effFrom.Invoke(null, new object[] { 100f, 150f }), 0f);
        Check("wake keeps the 20m band", wakeFrom.Invoke(null, new object[] { 350f, 150f, 130f }), 330f);
        Check("wake with no band",       wakeFrom.Invoke(null, new object[] { 350f, 150f, 150f }), 350f);

        // ---- Boss group wake -------------------------------------------
        //
        // HoldsAwake needs a live BotOwner, so what is checkable here is the
        // property the telemetry depends on: with no game instantiated the
        // counts are 0 and nothing throws. Same shape as
        // DistanceToNearestHuman returning 0 rather than mass-sleeping an
        // uninitialised world.
        Console.WriteLine("\nBossGroupWake");
        var bgw = asm.GetType("Framesaver.Patches.BossGroupWake");
        Check("BossGroupWake exists", bgw != null, true);
        var counts = bgw.GetMethod("Counts", BindingFlags.NonPublic | BindingFlags.Static);
        var countArgs = new object[] { 0, 0 };
        counts.Invoke(null, countArgs);
        Check("no world -> linked 0", countArgs[0], 0);
        Check("no world -> heldAwake 0", countArgs[1], 0);

        // The fields the analysis is written against, read out of the
        // shipped IL for the same reason as the ledger's above.
        foreach (var lit in new[] { ",\"bossGroups\":{\"linked\":", ",\"heldAwake\":",
                                    ",\"roleSleep\":{\"roles\":[", ",\"roleSleepDist\":",
                                    ",\"roleWakeDist\":", ",\"bossGroupWake\":" })
            Check($"emits {lit}", inUs(lit), true);

        // Named for what it is not: the count that would have conflated
        // "rule off" with "linkage broken" was never emitted, and must not
        // quietly appear later.
        Check("no bare groupHeldAwake field (control)", inUs(",\"groupHeldAwake\":"), false);

        // ---- Stand-by transition timing ------------------------------------
        //
        // Driven through the same statics the two choke points use. What is
        // NOT covered here: that Wake() declines to count a call which found
        // the bot already awake. That discrimination needs a live BotOwner,
        // and it is the number's whole meaning - without it the count is the
        // exempt population times the check rate. Stated rather than faked.
        Console.WriteLine("\nStandByTransitions");
        var sbt = asm.GetType("Framesaver.Patches.StandByTransitions");
        var woken = sbt.GetMethod("Woken", BindingFlags.NonPublic | BindingFlags.Static);
        var slept = sbt.GetMethod("Slept", BindingFlags.NonPublic | BindingFlags.Static);
        var sbtAppend = sbt.GetMethod("Append", BindingFlags.Public | BindingFlags.Static);
        var sbtReset = sbt.GetMethod("ResetWindow", BindingFlags.Public | BindingFlags.Static);

        sbtReset.Invoke(null, null);
        woken.Invoke(null, new object[] { freq / 1000 });   // 1.0 ms
        woken.Invoke(null, new object[] { freq / 1000 });   // 1.0 ms
        slept.Invoke(null, new object[] { freq / 4000 });   // 0.25 ms
        var sbt1 = new System.Text.StringBuilder();
        sbtAppend.Invoke(null, new object[] { sbt1 });
        string tj = sbt1.ToString();
        Check("wake count", tj.Contains("\"woken\":2"), true);
        Check("wake ms", tj.Contains("\"wokenMs\":2"), true);
        Check("sleep count", tj.Contains("\"slept\":1"), true);
        Check("sleep ms does not land in wokenMs", tj.Contains("\"sleptMs\":0.25"), true);

        // A death is neither a wake nor a sleep, and the proxy this replaces
        // could not tell it from either - which is what put deaths, and the
        // fights that contain them, inside the churn correlation.
        var died = sbt.GetMethod("Died", BindingFlags.NonPublic | BindingFlags.Static);
        died.Invoke(null, new object[] { true });
        died.Invoke(null, new object[] { false });
        died.Invoke(null, new object[] { true });
        var sbt3 = new System.Text.StringBuilder();
        sbtAppend.Invoke(null, new object[] { sbt3 });
        string dj = sbt3.ToString();
        Check("deaths while awake counted", dj.Contains("\"diedAwake\":2"), true);
        Check("deaths while asleep kept separate", dj.Contains("\"diedAsleep\":1"), true);
        Check("a death is not a wake", dj.Contains("\"woken\":2"), true);
        Check("a death is not a sleep", dj.Contains("\"slept\":1"), true);

        sbtReset.Invoke(null, null);
        var sbt2 = new System.Text.StringBuilder();
        sbtAppend.Invoke(null, new object[] { sbt2 });
        Check("ResetWindow zeroes every field",
              sbt2.ToString(),
              "{\"woken\":0,\"wokenMs\":0,\"slept\":0,\"sleptMs\":0,\"diedAwake\":0,\"diedAsleep\":0}");

        // A comma-decimal locale turns "wokenMs":2.5 into "wokenMs":2,5 and
        // every window in the file stops parsing. Both timers pass
        // InvariantCulture explicitly; this is what fails if someone removes
        // it. It bit us once already on updateManual, caught before deploy by
        // reading rather than by a test - so the test exists now, and covers
        // the older timer too.
        var prev = System.Threading.Thread.CurrentThread.CurrentCulture;
        try {
            System.Threading.Thread.CurrentThread.CurrentCulture =
                new System.Globalization.CultureInfo("de-DE");
            sbtReset.Invoke(null, null);
            slept.Invoke(null, new object[] { freq / 4000 });
            var deSb = new System.Text.StringBuilder();
            sbtAppend.Invoke(null, new object[] { deSb });
            Check("transitions: decimal point survives de-DE",
                  deSb.ToString().Contains("\"sleptMs\":0.25"), true);

            reset.Invoke(null, null);
            add.Invoke(null, new object[] { freq / 4000, true });
            var deSb2 = new System.Text.StringBuilder();
            append.Invoke(null, new object[] { deSb2 });
            Check("updateManual: decimal point survives de-DE",
                  deSb2.ToString().Contains("\"pausedMs\":0.25"), true);
        } finally {
            System.Threading.Thread.CurrentThread.CurrentCulture = prev;
        }

        foreach (var lit in new[] { ",\"standByTransitions\":", "{\"woken\":", ",\"sleptMs\":" })
            Check($"emits {lit}", inUs(lit), true);

        // ---- Protocol @directives -------------------------------------------
        //
        // Load() needs BepInEx's config to resolve setting names and Due reads
        // a Unity clock, so neither runs here. Directive() is the half that can
        // and the half that carries the parsing hazards.
        Console.WriteLine("\nProtocolRunner @directives");
        var prType = asm.GetType("Framesaver.ProtocolRunner");
        var stepType = prType.GetNestedType("Step");
        var directive = prType.GetMethod("Directive", BindingFlags.NonPublic | BindingFlags.Static);
        var defSecs = prType.GetField("_defaultSeconds", BindingFlags.NonPublic | BindingFlags.Static);
        var secsField = stepType.GetField("Seconds");

        object step = Activator.CreateInstance(stepType);
        Check("@seconds on a step",
              directive.Invoke(null, new object[] { "seconds", "120", step, 1 }), true);
        Check("step box parsed", secsField.GetValue(step), 120f);

        Check("@seconds before any step is the file default",
              directive.Invoke(null, new object[] { "seconds", "90", null, 1 }), true);
        Check("file default parsed", defSecs.GetValue(null), 90f);

        Check("@name still works as a directive",
              directive.Invoke(null, new object[] { "name", "someone-elses-experiment", null, 1 }), true);
        Check("name captured", prType.GetProperty("Name").GetValue(null), "someone-elses-experiment");

        // The decimal separator again, in the one place a foreign operator is
        // most likely to hit it. Parsed with the current culture, "0.5" reads
        // as 5 under de-DE - a box eight times too long, silently, in someone
        // else's experiment rather than ours.
        var prev2 = System.Threading.Thread.CurrentThread.CurrentCulture;
        try {
            System.Threading.Thread.CurrentThread.CurrentCulture =
                new System.Globalization.CultureInfo("de-DE");
            object step2 = Activator.CreateInstance(stepType);
            directive.Invoke(null, new object[] { "seconds", "0.5", step2, 1 });
            Check("@seconds survives de-DE", secsField.GetValue(step2), 0.5f);
        } finally {
            System.Threading.Thread.CurrentThread.CurrentCulture = prev2;
        }

        foreach (var lit in new[] { ",\"stepSeconds\":", "unknown directive '@" })
            Check($"emits {lit}", inUs(lit), true);

        // ---- Awake-age bucketing -------------------------------------
        //
        // Record() needs a live BotOwner, so the seam tested here is the one
        // that decides everything downstream: which bucket an age falls in.
        // An off-by-one at a boundary would move a whole population between
        // buckets and invent, or erase, exactly the ramp under test.
        Console.WriteLine("\nAwakeAge buckets");
        var aa = asm.GetType("Framesaver.Patches.AwakeAge");
        var bucket = aa.GetMethod("Bucket", BindingFlags.NonPublic | BindingFlags.Static);
        foreach (var c in new (float age, int want)[] {
            (0f, 0), (59.9f, 0), (60f, 1), (149.9f, 1), (150f, 2),
            (299.9f, 2), (300f, 3), (599.9f, 3), (600f, 4), (1199.9f, 4),
            (1200f, 5), (100000f, 5),
        })
            Check($"age {c.age}s -> bucket {c.want}", bucket.Invoke(null, new object[] { c.age }), c.want);

        // Drive the sums through the private arrays rather than adding a seam
        // to production for the test's benefit. readonly is on the reference,
        // not the contents.
        var ticksF = aa.GetField("Ticks", BindingFlags.NonPublic | BindingFlags.Static);
        var callsF = aa.GetField("Calls", BindingFlags.NonPublic | BindingFlags.Static);
        var aaAppend = aa.GetMethod("Append", BindingFlags.Public | BindingFlags.Static);
        var aaReset = aa.GetMethod("ResetWindow", BindingFlags.Public | BindingFlags.Static);

        aaReset.Invoke(null, null);
        ((long[])ticksF.GetValue(null))[0] = freq / 1000;   // 1.0 ms in the youngest
        ((int[])callsF.GetValue(null))[0] = 4;
        ((long[])ticksF.GetValue(null))[5] = freq / 250;    // 4.0 ms in the tail
        ((int[])callsF.GetValue(null))[5] = 2;
        var aaSb = new System.Text.StringBuilder();
        aaAppend.Invoke(null, new object[] { aaSb });
        string aj = aaSb.ToString();
        Check("youngest bucket edge is 60", aj.Contains("{\"toS\":60,\"ms\":1,\"n\":4}"), true);
        Check("tail edge is null, not 0", aj.Contains("{\"toS\":null,\"ms\":4,\"n\":2}"), true);
        Check("six buckets emitted", aj.Split(new[] { "{\"toS\":" }, StringSplitOptions.None).Length - 1, 6);

        aaReset.Invoke(null, null);
        var aaSb2 = new System.Text.StringBuilder();
        aaAppend.Invoke(null, new object[] { aaSb2 });
        Check("ResetWindow zeroes the sums", aaSb2.ToString().Contains("\"ms\":0,\"n\":0}"), true);

        // ---- Awake-age SPAN state machine ------------------------------
        //
        // The gating check, and the alias it closes is the expensive one. The
        // raid's registered prediction has a branch reading "the second block
        // opens at the first block's END value" - which means sleep FROZE the
        // accumulator rather than resetting it. **A counter that silently
        // froze would produce that same signature**, so the instrument error
        // and the finding would be indistinguishable after the fact.
        //
        // The clock is injected for exactly this: Time.realtimeSinceStartup is
        // a Unity ECall and would have made the one stateful thing here the
        // one thing no bench could drive.
        Console.WriteLine("\nAwakeAge span reset (raid gate)");
        var wokeAt = aa.GetMethod("WokeAt", BindingFlags.NonPublic | BindingFlags.Static);
        var endedM = aa.GetMethod("Ended", BindingFlags.NonPublic | BindingFlags.Static);
        var recordAt = aa.GetMethod("RecordAt", BindingFlags.NonPublic | BindingFlags.Static);
        var resetRaid = aa.GetMethod("ResetForRaid", BindingFlags.NonPublic | BindingFlags.Static);
        var botType = Type.GetType("EFT.BotOwner, Assembly-CSharp");
        object bot1 = System.Runtime.Serialization.FormatterServices
                          .GetUninitializedObject(botType);

        resetRaid.Invoke(null, null);
        wokeAt.Invoke(null, new object[] { bot1, 100f });
        recordAt.Invoke(null, new object[] { bot1, freq / 1000, 130f });   // age 30 -> b0
        endedM.Invoke(null, new object[] { bot1 });
        wokeAt.Invoke(null, new object[] { bot1, 500f });
        recordAt.Invoke(null, new object[] { bot1, freq / 1000, 530f });   // age 30 -> b0

        var tk = (long[])ticksF.GetValue(null);
        var cl = (int[])callsF.GetValue(null);
        Check("both calls land in the YOUNG bucket after a sleep", cl[0], 2);
        Check("a frozen accumulator would have put one at age 430", cl[3], 0);

        // Ended must actually remove, or the re-stamp above never happens.
        // ReferenceEquals is load-bearing here: BotOwner is a MonoBehaviour,
        // so `== null` is Unity's overload and answers TRUE for an object with
        // no native peer - which is every destroyed bot, and this test object.
        var sinceF = aa.GetField("Since", BindingFlags.NonPublic | BindingFlags.Static);
        endedM.Invoke(null, new object[] { bot1 });
        Check("Ended removes a bot with no native peer",
              ((System.Collections.ICollection)sinceF.GetValue(null)).Count, 0);

        // A second wake on a RUNNING span must not reset it - active to
        // goToSave and back are both un-paused and neither is a wake.
        resetRaid.Invoke(null, null);
        wokeAt.Invoke(null, new object[] { bot1, 100f });
        wokeAt.Invoke(null, new object[] { bot1, 200f });
        recordAt.Invoke(null, new object[] { bot1, freq / 1000, 230f });   // age 130 -> b1
        cl = (int[])callsF.GetValue(null);
        Check("add-if-absent: span survives a redundant wake", cl[1], 1);
        Check("and did not restart at the second one", cl[0], 0);

        // (b) the reconciliation: per-bot rows must sum to the buckets, which
        // are in turn awakeMs - deadMs. Two instruments over one set of calls,
        // so a disagreement is a bug rather than a finding.
        var drain = aa.GetMethod("DrainRows", BindingFlags.NonPublic | BindingFlags.Static);
        object bot2 = System.Runtime.Serialization.FormatterServices
                          .GetUninitializedObject(botType);
        resetRaid.Invoke(null, null);
        wokeAt.Invoke(null, new object[] { bot1, 0f });
        wokeAt.Invoke(null, new object[] { bot2, 0f });
        recordAt.Invoke(null, new object[] { bot1, freq / 1000, 10f });
        recordAt.Invoke(null, new object[] { bot1, freq / 1000, 20f });
        recordAt.Invoke(null, new object[] { bot2, freq / 2000, 30f });

        var rows = new System.Collections.Generic.List<string>();
        Action<string> collect = rows.Add;
        drain.Invoke(null, new object[] { collect, 7 });
        Check("one row per bot, not per call", rows.Count, 2);
        Check("rows carry the window", rows.TrueForAll(r => r.Contains("\"window\":7")), true);
        Check("rows carry the span start", rows.TrueForAll(r => r.Contains("\"spanS\":0")), true);


        double rowMs = 0d;
        foreach (var r in rows) {
            int i = r.IndexOf("\"ms\":") + 5;
            rowMs += double.Parse(r.Substring(i, r.IndexOf(',', i) - i),
                                  System.Globalization.CultureInfo.InvariantCulture);
        }
        tk = (long[])ticksF.GetValue(null);
        double bucketMs = 0d;
        foreach (var t in tk) bucketMs += t * 1000d / freq;
        Check("per-bot rows sum to the buckets", Math.Abs(rowMs - bucketMs) < 0.01d, true);
        Check("draining clears the rows",
              ((System.Collections.ICollection)aa.GetField("Live",
                  BindingFlags.NonPublic | BindingFlags.Static).GetValue(null)).Count, 0);

        // A re-wake is not a continuation, and a reader cannot always see the
        // break from awakeS alone: a bot that sleeps and wakes EARLY in a
        // window ends it OLDER than the previous row, so the reset is
        // invisible and two spans would be regressed as one. spanS makes the
        // identity exact - same id AND same spanS is the same span.
        //
        // Numbers chosen to be reachable at the DEFAULT 60 s window, per
        // Gamma. An earlier version used a 155 s span, which needs a
        // reconfigured window and could have been dismissed as unreachable at
        // the setting we actually run - a true test of a case that cannot
        // happen tonight.
        resetRaid.Invoke(null, null);
        wokeAt.Invoke(null, new object[] { bot1, 0f });
        recordAt.Invoke(null, new object[] { bot1, freq / 1000, 40f });   // awakeS 40
        var w1 = new System.Collections.Generic.List<string>();
        drain.Invoke(null, new object[] { (Action<string>)w1.Add, 1 });

        endedM.Invoke(null, new object[] { bot1 });                       // slept
        wokeAt.Invoke(null, new object[] { bot1, 45f });                  // and woke
        recordAt.Invoke(null, new object[] { bot1, freq / 1000, 100f });  // awakeS 55
        var w2 = new System.Collections.Generic.List<string>();
        drain.Invoke(null, new object[] { (Action<string>)w2.Add, 2 });

        Check("awakeS ROSE across the re-wake, hiding the break",
              w1[0].Contains("\"awakeS\":40") && w2[0].Contains("\"awakeS\":55"), true);
        Check("but spanS changed, so the break is detectable",
              w1[0].Contains("\"spanS\":0") && w2[0].Contains("\"spanS\":45"), true);

        // ---- Trigger-subscriber count --------------------------------
        //
        // The whole value of this number is telling unbounded from bounded, so
        // "cannot tell" must never read as 0. Outside a game it returns -1; the
        // separate check is that the event's backing field still exists in THIS
        // build of the game, because a rename would also return -1 and the two
        // would be indistinguishable from the log alone.
        Console.WriteLine("\nTriggerSubscribers");
        var ts = asm.GetType("Framesaver.Patches.TriggerSubscribers");
        var tsMax = ts.GetMethod("Max", BindingFlags.Public | BindingFlags.Static);
        Check("no game reads -1, not 0", tsMax.Invoke(null, null), -1);
        var backing = ts.GetField("_backing", BindingFlags.NonPublic | BindingFlags.Static);
        Check("ShootData.OnTriggerPressed backing field still exists",
              backing.GetValue(null) != null, true);

        // bots.deadAwake needs a live roster to count, so what is checkable
        // here is that the field ships. It is the term that makes `awake`
        // subtractable - corpses keep StandByType_1 == active and stay on the
        // roster, so they have been inside `awake` in all 24 logs.
        foreach (var lit in new[] { ",\"awakeAge\":", "{\"toS\":", ",\"triggerSubsMax\":",
                                    ",\"deadAwake\":" })
            Check($"emits {lit}", inUs(lit), true);

        // ---- Animator cull: the instrument guarding the main mechanism ----
        //
        // The cull measures ~0.22ms per awake bot across two maps and five legs -
        // twenty times what stand-by's own gating saves - so this is where nearly
        // all of the mod's frame time comes from, and `animCulled` alone cannot
        // tell a working cull from a dead one. Everything below certifies the
        // instrument that can.
        Console.WriteLine("\nAnimator cull instrument");
        var sba = asm.GetType("Framesaver.Patches.SleepingBotAnimatorPatch");
        var reaches = sba.GetMethod("WriteReachesUnity",
                                    BindingFlags.NonPublic | BindingFlags.Static);
        Check("WriteReachesUnity exists", reaches != null, true);

        // Both real types, resolved out of the game assembly. Neither can be
        // constructed without Unity and assets, which is why the method takes a
        // Type - the alternative was testing a hand-rolled fake, i.e. testing the
        // fake.
        var fastAnim = Type.GetType("FastAnimatorProcessorClass, Assembly-CSharp");
        var unityAnim = Type.GetType("GClass1446, Assembly-CSharp");
        Check("FastAnimatorProcessorClass still exists", fastAnim != null, true);
        Check("the Unity animator wrapper still exists", unityAnim != null, true);
        if (reaches != null && fastAnim != null && unityAnim != null) {
            Check("write does NOT reach Unity on the fast animator",
                  reaches.Invoke(null, new object[] { fastAnim }), false);
            Check("write DOES reach Unity on the real wrapper (control)",
                  reaches.Invoke(null, new object[] { unityAnim }), true);
            Check("null type is not counted as reachable",
                  reaches.Invoke(null, new object[] { null }), false);
        }

        // The fact the whole design rests on, and it is a fact about the GAME,
        // not about us: the fast animator's cullingMode is an auto-property, so a
        // write to it round-trips while doing nothing. That is why CulledEngine
        // type-tests instead of simply reading the value back - a read-back would
        // have reported 100% success for a feature doing literally nothing, which
        // is the most flattering false answer available.
        //
        // If BSG ever gives it a real implementation this fails, and it should:
        // both the type test and the interlock would need revisiting.
        //
        // Asserted from behaviour, not from the name `<cullingMode>k__BackingField`
        // - the decompiled assembly carries renamed backing fields, so a name check
        // fails for the wrong reason and looks like the property was fixed.
        const int All = (int)(BindingFlags.Public | BindingFlags.NonPublic
                              | BindingFlags.Instance | BindingFlags.Static
                              | BindingFlags.DeclaredOnly);
        // The field a getter of the form `return this.X;` returns, else null.
        Func<MethodInfo, FieldInfo> plainReadBack = m => {
            byte[] il = m?.GetMethodBody()?.GetILAsByteArray();
            if (il == null || il.Length != 7) return null;          // ldarg.0/ldfld/ret
            if (il[0] != 0x02 || il[1] != 0x7B || il[6] != 0x2A) return null;
            try { return m.Module.ResolveField(BitConverter.ToInt32(il, 2)); } catch { return null; }
        };
        Func<Type, FieldInfo, int> readersOf = (t, f) => t.GetMethods((BindingFlags)All).Count(m => {
            byte[] il = m.GetMethodBody()?.GetILAsByteArray();
            if (il == null) return false;
            for (int i = 0; i + 5 <= il.Length; i++) {
                if (il[i] != 0x7B) continue;
                try { if (Equals(m.Module.ResolveField(BitConverter.ToInt32(il, i + 1)), f)) return true; }
                catch { }
            }
            return false;
        });
        if (fastAnim != null && unityAnim != null) {
            var slot = plainReadBack(fastAnim.GetProperty("cullingMode").GetGetMethod());
            Check("fast animator's cullingMode just reads a field back", slot != null, true);
            // The inert half, and the reason a read-back would have lied: the
            // value it stores is consulted by NOTHING. One reader, the getter.
            if (slot != null)
                Check("...that nothing else in the class ever reads",
                      readersOf(fastAnim, slot), 1);
            // A count of 1 is only meaningful if the scan can reach 2. Without
            // this, a scanner that only ever finds the method it started from
            // passes the line above and proves nothing.
            Check("the reader scan can count past one (control)",
                  readersOf(fastAnim, fastAnim.GetField("FastAnimatorController",
                                                        (BindingFlags)All)) > 1, true);
            Check("the real wrapper forwards instead (control)",
                  plainReadBack(unityAnim.GetProperty("cullingMode").GetGetMethod()) == null, true);
        }

        // CulledEngine must NOT be gated on the config flag and CulledLastFrame
        // must be - that asymmetry IS the instrument. Both directions are checked
        // because a scanner that finds nothing and a scanner that finds
        // everything each pass one of these and fail the other.
        Func<MethodInfo, string, bool> readsField = (m, field) => {
            var body = m?.GetMethodBody();
            byte[] il = body?.GetILAsByteArray();
            if (il == null) return false;
            var mod = m.Module;
            for (int i = 0; i + 5 <= il.Length; i++) {
                if (il[i] != 0x7E && il[i] != 0x7B) continue;   // ldsfld / ldfld
                try {
                    if (mod.ResolveField(BitConverter.ToInt32(il, i + 1)).Name == field)
                        return true;
                } catch { }
            }
            return false;
        };
        // The intent/engine split now sits one level down: `Marked()` picks the
        // population and reads the flags, CulledLastFrame just counts it.
        var marked = sba.GetMethod("Marked", BindingFlags.NonPublic | BindingFlags.Static);
        var engineGet = sba.GetProperty("CulledEngine")?.GetGetMethod();
        Check("CulledEngine ships", engineGet != null, true);
        Check("the marked set IS gated on the cull flag (control)",
              readsField(marked, "CullSleepingBotAnimators"), true);
        Check("...and on the decoupled flag too (control)",
              readsField(marked, "CullAllBotAnimators"), true);
        Check("CulledEngine is NOT gated on either flag",
              readsField(engineGet, "CullSleepingBotAnimators")
              || readsField(engineGet, "CullAllBotAnimators"), false);

        // ---- The decoupled cull ------------------------------------------
        //
        // Ships OFF. The one risk no log can see is that CullCompletely stops
        // animation events being queued, so a bot leaving the screen mid-reload
        // may never finish it - harness/RELOAD-OBSERVATION-TEST.md.
        Console.WriteLine("\nDecoupled animator cull");
        var pluginT = asm.GetType("Framesaver.Plugin");
        Check("the flag ships", pluginT.GetField("CullAllBotAnimators") != null, true);
        Check("and the cfg block records it", inUs(",\"cullAllBots\":"), true);
        var cullAll = sba.GetMethod("CullEveryBot",
                                    BindingFlags.NonPublic | BindingFlags.Static);
        Check("CullEveryBot ships", cullAll != null, true);
        Check("it is gated on the decoupled flag",
              readsField(cullAll, "CullAllBotAnimators"), true);
        Check("and yields to the inert-animator guard",
              readsField(cullAll, "Inert"), true);

        // The safety property worth a test rather than a comment: the decoupled
        // write must NOT go through ApplyIfSleeping, whose bool is what the
        // LateUpdate and world-tick prefixes skip on. Answering true for every
        // bot would skip Player.LateUpdate for the whole roster and suppress the
        // VisualPass this cull rides on - the two features annihilating each
        // other on the first frame. Checked by IL: the skip prefixes must not
        // reach the decoupled flag at all.
        foreach (var skip in new[] { "SkipSleepingPlayerLateUpdatePatch",
                                     "SkipSleepingWorldTickPatch" })
            Check($"{skip} cannot see the decoupled flag",
                  readsField(asm.GetType("Framesaver.Patches." + skip)
                                .GetMethod("Prefix", BindingFlags.NonPublic | BindingFlags.Static),
                             "CullAllBotAnimators"), false);

        // ---- 'Force fast body animator' is REMOVED, not interlocked -------
        //
        // Sophia: it breaks the game, and always did - it was a first-draft
        // experiment. An interlock still leaves the user a route to a broken
        // client, so the whole write path is gone. These assert the removal:
        // a setting that quietly came back would be a broken client shipped by
        // us, and nobody goes looking for a knob they were told was deleted.
        Console.WriteLine("\nFast body animator is removed, guard remains");
        Check("the forcing patch is gone",
              asm.GetType("Framesaver.Patches.FastBodyAnimatorPatch") == null, true);
        Check("the setting is gone from Plugin",
              asm.GetType("Framesaver.Plugin").GetField("ForceFastBodyAnimator") == null, true);
        Check("and the cfg block no longer emits it", inUs(",\"fastAnim\":"), false);
        // Control for the three above: the search does find a cfg key that IS
        // still emitted, so "not found" means removed rather than broken.
        Check("...while a surviving cfg key is still found (control)",
              inUs(",\"cullSleeping\":"), true);

        // What remains is the READ-ONLY half. UseBodyFastAnimator still exists
        // and another mod can set it, and under it the cull is inert while
        // animCulled still reports full success - so detect it and switch the
        // cull off rather than burning a write per bot per frame for nothing.
        var detect = sba.GetMethod("DetectInertAnimator",
                                   BindingFlags.NonPublic | BindingFlags.Static);
        Check("the inert-animator detector ships", detect != null, true);
        Check("it reads the game's own flag",
              readsField(detect, "UseBodyFastAnimator"), true);
        Check("the cull consults what it found",
              readsField(sba.GetMethod("ApplyIfSleeping",
                                       BindingFlags.NonPublic | BindingFlags.Static), "Inert"), true);
        Check("and says so in the log of the raid it spoiled",
              inUs("UseBodyFastAnimator is ON"), true);

        // The line above asserts the string is in the assembly. It passed while
        // the guard fired on a RISING EDGE - `if (Inert && !wasInert)` - which,
        // because Inert is static and a log is a session (832498f), logged in
        // raid 1 and was silent in raids 2..n. Delta found that by reading the
        // code, not by running this suite: the assertion could not fail either
        // way, which is worse than no assertion because it reports coverage.
        //
        // WHAT THIS PROVES, precisely: the rising-edge form has to read `Inert`
        // TWICE - once to save the previous value, once to test it - and the
        // correct form reads it once. It is a proxy for "does not compare
        // against a saved previous value", not a direct test of it. If a future
        // change legitimately needs two reads, do not just bump the number:
        // check that neither read is a carried-over previous value.
        Func<MethodInfo, string, int> countsReadsOf = (m, field) => {
            byte[] il = m?.GetMethodBody()?.GetILAsByteArray();
            if (il == null) return -1;
            var mod = m.Module;
            int n = 0;
            for (int i = 0; i + 5 <= il.Length; i++) {
                if (il[i] != 0x7E && il[i] != 0x7B) continue;   // ldsfld / ldfld
                try {
                    if (mod.ResolveField(BitConverter.ToInt32(il, i + 1)).Name == field) n++;
                } catch { }
            }
            return n;
        };
        Check("the inert guard fires on the STATE, not the edge",
              countsReadsOf(detect, "Inert"), 1);
        // A count of 1 means nothing from a scanner that cannot reach 2.
        // ApplyIfSleeping reads Sleeping three times, by inspection.
        Check("...and the read counter can count past one (control)",
              countsReadsOf(sba.GetMethod("ApplyIfSleeping",
                                          BindingFlags.NonPublic | BindingFlags.Static),
                            "Sleeping") >= 2, true);
        // The other direction: a scanner that matched everything would pass
        // both lines above. This is a field that method provably never reads.
        Check("...and does not match a field that is not there (control)",
              countsReadsOf(detect, "Sleeping"), 0);

        // ---- Every protocol file on disk, against the shipped settings ----
        //
        // An unknown key refuses the WHOLE protocol at raid start, so a typo
        // costs a raid - and the raids are the scarce thing. The runner needs a
        // BepInEx host to resolve keys, but the keys themselves are Config.Bind
        // literals in the same assembly, so they are checkable from here.
        //
        // Every protocol-*.ini, not a named list: a file added later is exactly
        // the one nobody thought to check.
        Console.WriteLine("\nProtocol files resolve against the shipped settings");
        // The REPO root, found from a marker, not walked back from the assembly
        // under test. It used to be `dirname(dll)/../..`, which silently found
        // nothing the moment the dll lived outside the tree - as it now can,
        // since the path is overridable. That cost the whole protocol section
        // and the floor check is what caught it, exactly as advertised.
        string csproj = FindUp("Framesaver.csproj");
        string root = csproj == null ? "." : Path.GetDirectoryName(csproj);
        var inis = Directory.GetFiles(root, "protocol-*.ini");
        Check("protocol files found", inis.Length > 0, true);
        foreach (var ini in inis) {
            var unknown = new System.Collections.Generic.List<string>();
            foreach (var raw in File.ReadAllLines(ini)) {
                var line = raw.Split('#', ';')[0].Trim();
                int eq = line.IndexOf('=');
                if (line.StartsWith("[") || eq < 1) continue;
                string key = line.Substring(0, eq).Trim();
                if (key.StartsWith("@")) {
                    string d = key.Substring(1).ToLowerInvariant();
                    if (d != "name" && d != "seconds") unknown.Add(key);
                } else if (key.ToLowerInvariant() != "name" && !inUs(key)) {
                    unknown.Add(key);
                }
            }
            Check(Path.GetFileName(ini), string.Join("/", unknown), "");
        }
        // Same reason as the #US control above: without this, a matcher that
        // said yes to everything would pass every line in the loop.
        Check("an invented setting name would be caught (control)",
              inUs("Cull sleeping bot animatorz"), false);

        // Protocol prose also names TELEMETRY fields, and those were unchecked
        // until one shipped misspelled - `animCullEngine` for `animCulledEngine`.
        // A reader keyed on the protocol's spelling gets None, and None is
        // absent-not-zero, which reads as a clean control arm. The misspelling
        // survived a green suite because the check above validates settings
        // keys, and these are not settings.
        //
        // Backticked, starts lowercase, and camelCase or dotted - which is JSON
        // field convention here and excludes the PascalCase code identifiers
        // this prose is also full of. Dotted paths are checked on their last
        // segment, since that is the key actually emitted.
        Console.WriteLine("\nTelemetry fields named in protocol prose");
        var fieldRe = new System.Text.RegularExpressions.Regex(
            @"`([a-z][A-Za-z0-9]*(?:\.[a-zA-Z][A-Za-z0-9]*)*)`");
        foreach (var ini in inis) {
            var missing = new System.Collections.Generic.List<string>();
            foreach (System.Text.RegularExpressions.Match m
                     in fieldRe.Matches(File.ReadAllText(ini))) {
                string tok = m.Groups[1].Value;
                if (tok.IndexOf('.') < 0 && tok.ToLowerInvariant() == tok) continue;
                // Quoted, but NOT `"leaf":` - `botStandBy` and `botWindow` are
                // emitted as VALUES of the type key, so a key-shaped pattern
                // reported three real fields as missing. Weaker and still
                // sufficient: a misspelling appears nowhere in the image at all.
                string leaf = tok.Substring(tok.LastIndexOf('.') + 1);
                if (!inUs("\"" + leaf + "\"")) missing.Add(tok);
            }
            Check(Path.GetFileName(ini) + " fields", string.Join("/", missing), "");
        }
        Check("a misspelt field would be caught (control)",
              inUs("\"animCullEngine\""), false);

        // ---- Which of our patches can SUPPRESS the method they wrap --------
        //
        // Twice now a docstring has asserted "method M always runs" - VisualPass
        // rewrites cullingMode every frame; UpdateManual keeps driving
        // StandBy.Update - and been falsified later by OUR OWN mod gaining the
        // ability to skip M. Both comments were true when written, sat on the
        // BENEFICIARY rather than the suppressor, and nothing failed when the
        // flag that broke them was added.
        //
        // That set is exactly computable: a Harmony prefix returning bool can
        // skip the original; a void one cannot. Type-level, deliberately -
        // Gamma's first pass grepped bodies for `return false;`, found four, and
        // MISSED BOTH SKIP PATCHES, which return `!ApplyIfSleeping(...)` with no
        // literal false anywhere. The two it missed are the two that caused both
        // incidents, and it reported a confident small number while doing it.
        //
        // Compared against a literal list rather than a registry of which
        // invariants depend on what. A registry is a second artefact that rots
        // unwatched; this fails the moment a suppressing patch is added, and the
        // diff line IS the prompt - what asserted that this method always runs?
        //
        // LIMIT, so nobody over-trusts it: this catches invariants broken by
        // SUPPRESSION only. A flag that changes a distance, a period or a
        // threshold breaks a comment just as thoroughly and is invisible here.
        Console.WriteLine("\nPrefixes that can skip the method they patch");
        var suppressors = asm.GetTypes()
            .SelectMany(t => t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic
                                          | BindingFlags.Static | BindingFlags.Instance
                                          | BindingFlags.DeclaredOnly))
            .Where(m => m.ReturnType == typeof(bool)
                        && m.GetCustomAttributes(true)
                            .Any(a => a.GetType().Name == "PatchPrefixAttribute"))
            .Select(m => m.DeclaringType.Name + "." + m.Name)
            .OrderBy(s => s, StringComparer.Ordinal)
            .ToArray();
        // Golden list. Adding a line here is the moment to ask what documented
        // invariant assumed the patched method always runs - and to write the
        // consequence at the SUPPRESSOR, where whoever adds the flag is
        // standing, not at whatever benefits from it.
        // Seven. I wrote this list from memory first and it had five - I had
        // forgotten the brain and the async worker, which is the whole argument
        // for reflecting the set rather than keeping one by hand.
        var known = new[] {
            "AICoreControllerUpdatePatch.Prefix",        // AICoreControllerClass.Update
            "AsyncDrainPatch.Prefix",                    // the async drain
            "AsyncWorkerFixedUpdatePatch.Prefix",        // AsyncWorker.FixedUpdate
            "BotStandByUpdatePatch.Prefix",              // BotStandBy.Update
            "SkipSleepingPlayerLateUpdatePatch.Prefix",  // Player.LateUpdate -> VisualPass
            "SkipSleepingWorldTickPatch.Prefix",         // GameWorld.smethod_2
            "SleepingBotStandByPumpPatch.Prefix",        // BotOwner.UpdateManual
        };
        // Two controls. Non-empty, so a broken reflection query cannot pass by
        // matching nothing; and strictly fewer than ALL prefixes, so the bool
        // filter is actually discriminating rather than waving everything
        // through. Without the second, a filter that ignored return type would
        // pass the moment someone pasted the full list into `known`.
        int allPrefixes = asm.GetTypes()
            .SelectMany(t => t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic
                                          | BindingFlags.Static | BindingFlags.Instance
                                          | BindingFlags.DeclaredOnly))
            .Count(m => m.GetCustomAttributes(true)
                         .Any(a => a.GetType().Name == "PatchPrefixAttribute"));
        Check("the reflected set is non-empty (control)", suppressors.Length > 0, true);
        Check("...and the bool filter excludes void prefixes (control)",
              allPrefixes > suppressors.Length, true);
        Check("suppressing prefixes match the reviewed list",
              string.Join(" ", suppressors), string.Join(" ", known));

        // `bad == 0` is an ABSENCE, and this file argues elsewhere that an
        // absence of complaint is not a verification. Half the sections here sit
        // behind an `if` - a null dll, a type that vanished from the game
        // assembly - so one going quiet costs its checks and nothing says so.
        // Gamma shipped 8 crash-test cases that had been bailing before their
        // first assertion since the day they were committed, signed off on "0
        // tracebacks".
        //
        // A floor, not an exact count: adding checks never touches it, and the
        // only event it fails on is the count FALLING, which is the event.
        //
        // The floor is one below the printed total, because this check's own
        // condition is evaluated before Check increments the counter. Setting it
        // to the number at the bottom of a green run fails by one, which is a
        // confusing way to learn that.
        Check("the suite still runs every section it used to", ran >= 204, true);

        Console.WriteLine(bad == 0
            ? $"\nall {ran} cases pass (against shipped IL)"
            : $"\n{bad} FAILURES of {ran}");
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
