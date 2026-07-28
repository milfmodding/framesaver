# Reflection tests against the shipped assembly

`dotnet run -c Release` from this directory. Exit 0 passes.

**Why reflection rather than a normal test project.** Framesaver targets `netstandard2.1`
and its types derive from `MonoBehaviour`, so nothing here can be constructed without a
Unity host. But pure static helpers can be *invoked* — load `bin/Release/Framesaver.dll`,
resolve Unity's assemblies out of the game's `Managed` folder with an `AssemblyResolve`
handler, and call the method by reflection.

That matters because it tests the **compiled IL that ships**, not a reimplementation.
Testing a copy of an algorithm proves the copy is right and says nothing about the
binary — which is the same class of mistake as a validator that reports SKIP as a pass.

**What is covered.** `Telemetry.Unwrap`, which folds an angular difference into
(-180, 180]. It exists because yaw wraps: a view held near the wrap point samples at
359.9 and 0.1, and raw min/max over those spans the whole circle — a held view reported
as a full sweep, which is exactly the reading the `look` block exists to make
trustworthy. The cases cover both wrap directions, both angle conventions (0..360 and
-180..180), the fold boundary at ±180, multiple wraps, and a held view.

**Limits, stated because a green run here is narrower than it looks.** This exercises one
static method. It does not cover `SampleLook`'s accumulation, the per-window reset, or
the null-versus-zero emission — those need a player and a window boundary. A pass means
the arithmetic is right, not that the block is.
