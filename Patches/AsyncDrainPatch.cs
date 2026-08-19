using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Text;
using UnityEngine.Scripting;
using System.Reflection;
using System.Runtime.CompilerServices;
using Comfort.Common;
using EFT;
using HarmonyLib;
using SPT.Reflection.Patching;

namespace Framesaver.Patches
{
    /// <summary>
    /// Caps how long AsyncWorker's completion drain may run in a single call, deferring the rest to the next one.
    ///
    /// Diz.Utils.TaskWorker.CheckForFinishedTasks empties the whole completion queue in one unbounded loop. Each queued
    /// item is a TaskCompletionSource.SetResult, and TaskCompletionSource runs its continuations inline unless
    /// told otherwise - so the entire downstream async method body executes right there, on the main thread,
    /// inside whichever phase called the drain. AsyncWorker calls it from both Update and FixedUpdate.
    ///
    /// Measured on Streets: FixedUpdate max 2588.44ms against an asyncFixedDrain max of 2588.2ms in the same
    /// window, with fixedSteps never exceeding 6. The drain is not a symptom of a physics catch-up spiral -
    /// it IS the spike, and it is one call, not many steps.
    ///
    /// Budgeting it converts a single multi-second freeze into a run of slightly fat frames. Nothing is dropped;
    /// deferred callbacks are still at the head of the queue for the next drain, which is the same ordering they
    /// would have had anyway.
    ///
    /// The budget deliberately does not apply outside GameStatus.Started. Loading produced a 35-second drain in
    /// one run, and rationing that would stretch the loading screen out rather than help anything.
    /// </summary>
    public static class AsyncDrain
    {
        /// <summary>Callbacks executed this frame, across both the Update and FixedUpdate drains.</summary>
        public static int Drained;

        /// <summary>Queue depth left behind after the budget cut the drain short. 0 means it emptied.</summary>
        public static int Deferred;

        /// <summary>Number of drains this frame that hit the budget rather than running dry.</summary>
        public static int Truncated;

        /// <summary>
        /// Slowest callbacks since the last window flush. Kept as a small top-N rather than a single worst,
        /// because one /client/game/bot/generate stall will otherwise mask every other endpoint in the window -
        /// including the corpse resource loads that only ever cost tens of milliseconds.
        /// </summary>
        private const int TopCount = 3;

        private static readonly double[] TopMs = new double[TopCount];
        private static readonly string[] TopName = new string[TopCount];
        private static readonly long[] TopAlloc = new long[TopCount];

        /// <summary>Per-callback breakdown: what we can already attribute, and what is left over.</summary>
        private static readonly double[] TopProfileMs = new double[TopCount];
        private static readonly double[] TopBundleMs = new double[TopCount];
        private static readonly int[] TopGen0 = new int[TopCount];

        /// <summary>
        /// Raid initialisation that resumed inline inside this callback - see RaidInitPatches.
        ///
        /// Reported beside residualMs rather than folded into it. residualMs keeps its original definition
        /// (ms - profile - bundle) so the numbers stay comparable with logs already collected, and because
        /// the spawn scenarios inside raidInit create bots, which means profile and bundle time can legally
        /// appear inside this span too. Two overlapping measurements of the same interval subtract badly;
        /// two reported side by side do not.
        /// </summary>
        private static readonly double[] TopRaidInitMs = new double[TopCount];

        public static double WorstCallbackMs
        {
            get { return TopMs[0]; }
        }

        public static string WorstCallbackName
        {
            get { return TopName[0] ?? ""; }
        }

        public static void AppendTop(StringBuilder sb)
        {
            sb.Append('[');
            for (int i = 0; i < TopCount; i++)
            {
                if (TopName[i] == null)
                {
                    break;
                }

                if (i > 0)
                {
                    sb.Append(',');
                }

                double residual = TopMs[i] - TopProfileMs[i] - TopBundleMs[i];
                if (residual < 0d)
                {
                    residual = 0d;
                }

                sb.Append("{\"ms\":").Append(TopMs[i].ToString("0.###", CultureInfo.InvariantCulture))
                  .Append(",\"allocKb\":").Append(TopAlloc[i] / 1024L)
                  .Append(",\"profileMs\":").Append(TopProfileMs[i].ToString("0.###", CultureInfo.InvariantCulture))
                  .Append(",\"bundleSyncMs\":").Append(TopBundleMs[i].ToString("0.###", CultureInfo.InvariantCulture))
                  .Append(",\"residualMs\":").Append(residual.ToString("0.###", CultureInfo.InvariantCulture))
                  .Append(",\"raidInitMs\":").Append(TopRaidInitMs[i].ToString("0.###", CultureInfo.InvariantCulture))
                  .Append(",\"gen0\":").Append(TopGen0[i])
                  .Append(",\"name\":\"").Append(TopName[i].Replace("\\", "\\\\").Replace("\"", "\\\""))
                  .Append("\"}");
            }

            sb.Append(']');
        }

        /// <summary>
        /// JObject-shaped sibling of AppendTop, for the capstone window callback body (Ranger's
        /// TelemetryBus.RegisterWindowCallback expects Action&lt;JObject&gt;, not
        /// Action&lt;StringBuilder&gt; - Sophia's 2026-08-18 ruling, same reasoning as every other
        /// JObject sibling in this codebase, e.g. GcControl.AppendWindowTo). Same fields, same
        /// values, same TopCount/skip-null-name loop, just written as an object graph instead of
        /// appended as characters. AppendTop itself is UNCHANGED and stays in use nowhere once the
        /// capstone lands (Framesaver's own Telemetry.cs is deleted at cutover), kept only so this
        /// stays additive rather than rewriting a working method.
        /// </summary>
        public static void AppendTopTo(Newtonsoft.Json.Linq.JArray array)
        {
            for (int i = 0; i < TopCount; i++)
            {
                if (TopName[i] == null)
                {
                    break;
                }

                double residual = TopMs[i] - TopProfileMs[i] - TopBundleMs[i];
                if (residual < 0d)
                {
                    residual = 0d;
                }

                var entry = new Newtonsoft.Json.Linq.JObject();
                entry["ms"] = TopMs[i];
                entry["allocKb"] = TopAlloc[i] / 1024L;
                entry["profileMs"] = TopProfileMs[i];
                entry["bundleSyncMs"] = TopBundleMs[i];
                entry["residualMs"] = residual;
                entry["raidInitMs"] = TopRaidInitMs[i];
                entry["gen0"] = TopGen0[i];
                entry["name"] = TopName[i];
                array.Add(entry);
            }
        }

        /// <summary>Callbacks run with collection suspended, so the effect is visible in telemetry.</summary>
        public static int GcSuspended;

        /// <summary>
        /// Runs one completion callback, optionally with garbage collection suspended.
        ///
        /// Unity's incremental collector is enabled here but slices only between frames, so a callback that
        /// runs for seconds without returning to the player loop gives it no opportunity - every collection
        /// forced inside such a callback runs to completion and blocks. Suspending collection for the
        /// duration converts those pauses into heap growth the incremental collector reclaims afterwards.
        ///
        /// try/finally is load-bearing: leaving GC disabled after an exception would leak for the rest of
        /// the session.
        /// </summary>
        internal static void RunCallback(Action action)
        {
            if (!Plugin.SuspendGcDuringCallbacks.Value)
            {
                action();
                return;
            }

            GarbageCollector.Mode previous = GarbageCollector.GCMode;
            try
            {
                GarbageCollector.GCMode = GarbageCollector.Mode.Disabled;
                GcSuspended++;
                action();
            }
            finally
            {
                GarbageCollector.GCMode = previous;
            }
        }

        internal static void Record(double ms, Action action, long allocBytes,
            double profileMs, double bundleMs, int gen0, double raidInitMs)
        {
            if (ms <= TopMs[TopCount - 1])
            {
                return;
            }

            string name = Describe(action);

            // Same call site twice in a window is not two findings - keep the slower and stop.
            for (int i = 0; i < TopCount; i++)
            {
                if (TopName[i] == name)
                {
                    if (ms <= TopMs[i])
                    {
                        return;
                    }

                    TopMs[i] = ms;
                    TopAlloc[i] = allocBytes;
                    TopProfileMs[i] = profileMs;
                    TopBundleMs[i] = bundleMs;
                    TopGen0[i] = gen0;
                    TopRaidInitMs[i] = raidInitMs;
                    Sort();
                    return;
                }
            }

            TopMs[TopCount - 1] = ms;
            TopName[TopCount - 1] = name;
            TopAlloc[TopCount - 1] = allocBytes;
            TopProfileMs[TopCount - 1] = profileMs;
            TopBundleMs[TopCount - 1] = bundleMs;
            TopGen0[TopCount - 1] = gen0;
            TopRaidInitMs[TopCount - 1] = raidInitMs;
            Sort();
        }

        private static void Sort()
        {
            for (int i = 1; i < TopCount; i++)
            {
                for (int j = i; j > 0 && TopMs[j] > TopMs[j - 1]; j--)
                {
                    double m = TopMs[j]; TopMs[j] = TopMs[j - 1]; TopMs[j - 1] = m;
                    string n = TopName[j]; TopName[j] = TopName[j - 1]; TopName[j - 1] = n;
                    long a = TopAlloc[j]; TopAlloc[j] = TopAlloc[j - 1]; TopAlloc[j - 1] = a;
                    double p = TopProfileMs[j]; TopProfileMs[j] = TopProfileMs[j - 1]; TopProfileMs[j - 1] = p;
                    double b = TopBundleMs[j]; TopBundleMs[j] = TopBundleMs[j - 1]; TopBundleMs[j - 1] = b;
                    int g = TopGen0[j]; TopGen0[j] = TopGen0[j - 1]; TopGen0[j - 1] = g;
                    double r = TopRaidInitMs[j]; TopRaidInitMs[j] = TopRaidInitMs[j - 1]; TopRaidInitMs[j - 1] = r;
                }
            }
        }

        public static void ResetFrame()
        {
            Drained = 0;
            Deferred = 0;
            Truncated = 0;
        }

        /// <summary>
        /// Publishes Drained (this frame's count) then resets it, isolated as its own per-frame
        /// step. Capstone finding (2026-08-19): Ranger's already-committed Telemetry.cs (see its
        /// _lastDrained assignment, capstone comment there) reads this back every frame via
        /// TelemetryBus.TryGetEvent("asyncDrain.drainedThisFrame", ...) - that publish call did
        /// not exist anywhere in Framesaver yet when this was found, a real gap between what
        /// Ranger's side already assumes and what Framesaver's side actually does. PUBLISH THEN
        /// RESET, in that order and both here: Ranger's read happens once per frame from its own
        /// per-frame call site, same cadence as this method needs to run at, so this is the
        /// single place both steps can happen atomically without a window where a second reader
        /// could see a value already zeroed or a reset that raced the publish. Event (not Sum),
        /// because Drained is inherently a THIS-FRAME snapshot, not an accumulating quantity -
        /// same semantic Deferred/Truncated have, which is exactly why those two stay unpublished
        /// per RangerBridge.PublishAsyncDrain's own doc comment (a window-boundary read of a
        /// per-frame-reset field would silently be wrong; a per-FRAME read via this method is the
        /// only safe cadence for exactly that reason).
        /// </summary>
        internal static void PublishAndResetFrame()
        {
            if (RangerBridge.Present)
            {
                global::Ranger.TelemetryBus.Event("asyncDrain.drainedThisFrame", Drained);
            }

            ResetFrame();
        }

        public static void ResetWindow()
        {
            for (int i = 0; i < TopCount; i++)
            {
                TopMs[i] = 0d;
                TopName[i] = null;
                TopAlloc[i] = 0L;
                TopProfileMs[i] = 0d;
                TopBundleMs[i] = 0d;
                TopGen0[i] = 0;
                TopRaidInitMs[i] = 0d;
            }

            GcSuspended = 0;
        }

        /// <summary>
        /// Ranger extraction (2026-08-16/17): publish-side addition, ADDITIVE. Publishes GcSuspended
        /// and the top-1 worst callback (WorstCallbackMs/WorstCallbackName) - the fields that are
        /// actually window-scoped, reset by ResetWindow above. Deliberately does NOT publish Drained/
        /// Deferred/Truncated, which reset per-FRAME (ResetFrame, called every Sample()) - see
        /// RangerBridge.PublishAsyncDrain's doc comment for why a window-boundary read of those three
        /// would be silently wrong. Called once per window from Telemetry.cs's Flush(), beside the
        /// existing gcSuspended/worstCallbacks NDJSON fields.
        /// </summary>
        internal static void PublishTelemetry()
        {
            if (!RangerBridge.Present)
            {
                return;
            }

            RangerBridge.PublishAsyncDrain(GcSuspended, WorstCallbackMs, WorstCallbackName);
        }

        /// <summary>
        /// The queued Action is almost always a compiler-generated closure - AsyncWorker.Class1009&lt;T&gt;.method_0
        /// for the result path, Class1011.method_1 for the void path - whose name says nothing about the caller.
        /// The useful identity is the Func/Action the closure was built around, one field in. Walking that field
        /// is the difference between "Class1009`1.method_0" and the actual call site.
        /// </summary>
        internal static string Describe(Action action)
        {
            try
            {
                object target = action.Target;
                if (target == null)
                {
                    return Name(action.Method);
                }

                Delegate inner = FindInnerDelegate(target, 0);
                if (inner != null)
                {
                    // Everything in DataHandlerClass funnels through the same two closures, so the method name
                    // alone says "a backend request" and nothing more. The endpoint is on the BackendRequestParams the
                    // closure captured.
                    return Name(inner.Method) + DescribeRequest(inner.Target);
                }

                return target.GetType().Name + "." + action.Method.Name;
            }
            catch
            {
                return "<unknown>";
            }
        }

        /// <summary>
        /// Pulls the endpoint and payload size off a captured BackendRequestParams backend request, if there is one.
        /// Also reports any large captured string, which for the DataHandlerClass parse closures is the raw
        /// response body - the number that says whether this was a big response or merely a slow one.
        /// </summary>
        private static string DescribeRequest(object closure)
        {
            if (closure == null)
            {
                return "";
            }

            try
            {
                FieldInfo[] fields = FieldsOf(closure.GetType());
                string endpoint = null;
                int bodyChars = -1;
                BackendRequestParams backRequest = null;

                for (int i = 0; i < fields.Length; i++)
                {
                    object value = fields[i].GetValue(closure);

                    BackendRequestParams request = value as BackendRequestParams;
                    if (request != null && endpoint == null)
                    {
                        backRequest = request;
                        endpoint = !string.IsNullOrEmpty(request.BackendMethod)
                            ? request.BackendMethod
                            : request.MainURLNamePath;
                        continue;
                    }

                    string text = value as string;
                    if (text != null && text.Length > bodyChars)
                    {
                        bodyChars = text.Length;
                    }
                }

                if (endpoint == null && bodyChars < 0)
                {
                    return "";
                }

                return " [" + (endpoint ?? "?") + DescribeWaves(backRequest)
                       + (bodyChars >= 0 ? ", " + bodyChars + " chars" : "") + "]";
            }
            catch
            {
                return "";
            }
        }

        /// <summary>
        /// The roles this request asked for, dug out of BackendRequestParams.Params.
        ///
        /// Response size turned out to be a poor predictor of cost: 113 KB took 566 ms in one window and 64 ms
        /// in another, a 9x spread at identical size, with no GC and no heap growth to explain it. The obvious
        /// suspect is what the bytes describe - a PMC with a fully modded weapon builds a far deeper item graph
        /// per character than a scav with a pistol - and the role is the way to test that.
        /// </summary>
        private static string DescribeWaves(BackendRequestParams request)
        {
            try
            {
                object p = request != null ? request.Params : null;
                if (p == null)
                {
                    return "";
                }

                // The single-field params wrapper around the wave list (element was WaveInfoClass, 4.1: CountTypeBotWave).
                FieldInfo[] fields = FieldsOf(p.GetType());
                for (int i = 0; i < fields.Length; i++)
                {
                    IEnumerable<CountTypeBotWave> waves = fields[i].GetValue(p) as IEnumerable<CountTypeBotWave>;
                    if (waves == null)
                    {
                        continue;
                    }

                    StringBuilder sb = new StringBuilder();
                    foreach (CountTypeBotWave w in waves)
                    {
                        if (sb.Length > 0)
                        {
                            sb.Append('+');
                        }

                        sb.Append(w.Role).Append('x').Append(w.Limit);
                        if (sb.Length > 120)
                        {
                            sb.Append("...");
                            break;
                        }
                    }

                    return sb.Length > 0 ? ", " + sb : "";
                }
            }
            catch
            {
            }

            return "";
        }

        private static Delegate FindInnerDelegate(object target, int depth)
        {
            if (target == null || depth > 3)
            {
                return null;
            }

            FieldInfo[] fields = FieldsOf(target.GetType());

            // A delegate on this object wins outright.
            for (int i = 0; i < fields.Length; i++)
            {
                Delegate d = fields[i].GetValue(target) as Delegate;
                if (d != null)
                {
                    return d;
                }
            }

            // Otherwise follow the captured-closure chain (Class1009 -> class1008_0 -> function). Compiler-
            // generated fields are walked first: Class1009 also holds the operation's *result*, and descending
            // into that would happily report some delegate hanging off the response object instead of the
            // caller we are trying to name.
            for (int pass = 0; pass < 2; pass++)
            {
                for (int i = 0; i < fields.Length; i++)
                {
                    Type ft = fields[i].FieldType;
                    if (ft.IsPrimitive || ft == typeof(string))
                    {
                        continue;
                    }

                    bool generated = ft.IsDefined(typeof(CompilerGeneratedAttribute), false);
                    if (generated != (pass == 0))
                    {
                        continue;
                    }

                    Delegate d = FindInnerDelegate(fields[i].GetValue(target), depth + 1);
                    if (d != null)
                    {
                        return d;
                    }
                }
            }

            return null;
        }

        private static FieldInfo[] FieldsOf(Type type)
        {
            FieldInfo[] fields;
            if (!FieldCache.TryGetValue(type, out fields))
            {
                fields = type.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
                FieldCache[type] = fields;
            }

            return fields;
        }

        private static string Name(MethodBase m)
        {
            Type t = m.DeclaringType;
            return (t != null ? t.Name : "?") + "." + m.Name;
        }

        private static readonly Dictionary<Type, FieldInfo[]> FieldCache = new Dictionary<Type, FieldInfo[]>();
    }

    internal class AsyncDrainPatch : ModulePatch
    {
        protected override MethodBase GetTargetMethod()
        {
            return AccessTools.Method(typeof(Diz.Utils.TaskWorker), nameof(Diz.Utils.TaskWorker.CheckForFinishedTasks));
        }

        [PatchPrefix]
        private static bool Prefix(Diz.Utils.TaskWorker __instance)
        {
            float budget = Plugin.AsyncDrainBudgetMs.Value;
            bool diagnose = Plugin.AsyncDrainDiagnostics.Value;

            if (budget <= 0f && !diagnose)
            {
                return true;
            }

            // The *budget* is confined to an in-progress raid: the loading path legitimately needs to run a
            // very long queue to completion, and rationing it there just moves the wait. Diagnostics are not
            // gated the same way - loading produces the largest stalls in the whole session (34.5s and 13.8s
            // in one raid) and those were being timed but never attributed.
            bool inRaid = Singleton<AbstractGame>.Instantiated
                          && Singleton<AbstractGame>.Instance.Status == GameStatus.Started;

            if (!diagnose && !inRaid)
            {
                return true;
            }

            long start = Stopwatch.GetTimestamp();
            double budgetMs = inRaid ? budget : 0d;
            Queue<Action> queue = __instance._finishedCallbacks;

            for (;;)
            {
                Action action;
                lock (queue)
                {
                    if (queue.Count <= 0)
                    {
                        break;
                    }

                    action = queue.Dequeue();
                }

                if (diagnose)
                {
                    // Allocation across the callback is a far better proxy for item-graph size than the
                    // response's character count, which has turned out not to predict cost at all: identical
                    // role and identical byte size have measured 44ms and 210ms in the same raid. If the slow
                    // ones allocate proportionally more, the graph is bigger than the bytes suggest; if they
                    // allocate the same and simply take longer, the allocator is the problem, not the work.
                    long heap0 = GC.GetTotalMemory(false);

                    // Snapshot the two things we already know how to attribute, so a slow callback can be
                    // split into "profile construction", "bundle prologue" and "everything else". A 16.3s
                    // callback carrying 830ms of profiles and 272ms of bundle prologue is a very different
                    // problem from one where those account for most of it - and so far neither does.
                    double profile0 = ProfileBuild.TotalMs;
                    double bundle0 = BundleLoad.SyncMsTotal;
                    int gen0 = GC.CollectionCount(0);

                    // The bot/generate callback that completes the last preset batch resumes the tail of
                    // LocalGame.vmethod_1 inline - BotsController.Init and the spawn scenarios. That is the
                    // 16.7s, and until now it landed entirely in `residual`.
                    double raidInit0 = RaidInit.TotalMs;

                    long t0 = Stopwatch.GetTimestamp();
                    AsyncDrain.RunCallback(action);
                    double ms = TickMath.ToMs(Stopwatch.GetTimestamp() - t0);

                    AsyncDrain.Record(ms, action, GC.GetTotalMemory(false) - heap0,
                        ProfileBuild.TotalMs - profile0,
                        BundleLoad.SyncMsTotal - bundle0,
                        GC.CollectionCount(0) - gen0,
                        RaidInit.TotalMs - raidInit0);
                }
                else
                {
                    AsyncDrain.RunCallback(action);
                }

                AsyncDrain.Drained++;

                // Checked after executing, so the drain always makes progress no matter how small the budget or
                // how slow a single callback is.
                if (budgetMs > 0d && TickMath.ToMs(Stopwatch.GetTimestamp() - start) >= budgetMs)
                {
                    lock (queue)
                    {
                        AsyncDrain.Deferred += queue.Count;
                    }

                    AsyncDrain.Truncated++;
                    break;
                }
            }

            return false;
        }
    }
}
