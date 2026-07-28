# `BotController.GenerateBotWaves` never materialises its parallel query

Delta, 2026-07-28. Against `Community/server-csharp-main` at `Build.props` → `SptVersion 4.0.13`, matching the
`SPT 4.0.13` watermark of the running server.

**This is a mechanism report with no measurement attached, deliberately.** The effect is server-side and every
instrument this investigation owns is inside the game client. What follows is what the code does and what
that implies; what it *costs* is not established here and should not be inferred from the fact that a report
exists. Anyone with a server-side profiler can settle it in minutes, which is the main reason to write it down.

## The code

[`BotController.cs:231-273`](../../Community/server-csharp-main/Libraries/SPTarkov.Server.Core/Controllers/BotController.cs:231):

```csharp
var generatedBots = Enumerable
    .Range(0, botGenerationDetails.BotCountToGenerate)
    .AsParallel()                                       // Parallelize above range of values so they can each generate a bot
    .Select(i => TryGenerateSingleBot(sessionId, botGenerationDetails, i))
    .Where(bot =>
        bot is not null
    ) // Skip failed bots
; // Materialise parallel query into data

return generatedBots;
```

The trailing comment says *"Materialise parallel query into data"*. Nothing materialises it. There is no
`ToList()`, no `ToArray()`, no enumeration of any kind — the statement it is attached to is the empty one
created by the stray semicolon on the line above.

The laziness then survives every subsequent hop.
[`GenerateBotWaves`](../../Community/server-csharp-main/Libraries/SPTarkov.Server.Core/Controllers/BotController.cs:182)
wraps each wave in `Task.Run`, awaits them with `Task.WhenAll`, and flattens with
`results.SelectMany(botList => botList)` — itself lazy. `Generate` returns that. The first enumeration is
`httpResponseUtil.GetBody(...)` at
[`BotCallbacks.cs:54`](../../Community/server-csharp-main/Libraries/SPTarkov.Server.Core/Callbacks/BotCallbacks.cs:54),
during JSON serialisation of the response.

## Three consequences, in decreasing order of confidence

**1. The debug timing is measuring nothing, and this one is certain.**
[`BotController.cs:189-218`](../../Community/server-csharp-main/Libraries/SPTarkov.Server.Core/Controllers/BotController.cs:189)
starts a `Stopwatch`, awaits `Task.WhenAll`, stops it, and logs
`"Took {stopwatch.ElapsedMilliseconds}ms to GenerateMultipleBotsAndCache()"`. Since `Task.WhenAll` completes
as soon as each `Task.Run` has *constructed* its query, that elapsed time excludes all bot generation. **Any
SPT profiling work that has ever quoted this number was quoting query construction.** That is the cheapest
thing here for a maintainer to confirm and the most immediately useful, because it may have shaped decisions.

**2. Cross-wave parallelism is defeated; within-wave parallelism is not.** The `Task.Run` per wave was
intended to overlap waves. Because each task returns immediately, the waves do not overlap — they enumerate
one after another inside a single serialisation pass. The `AsParallel()` *inside* each wave still works when
that wave is finally enumerated, so this is a loss of one level of concurrency, not all of it. A request
carrying one condition loses nothing. A multi-clause request loses the overlap between clauses, and
multi-clause requests are the large ones: the biggest observed in our corpus is a 2.6 MB response spanning
eight-plus role clauses.

**3. Generation runs during serialisation, holding whatever the response pipeline holds.** Work that was
written to happen inside a `Task.Run` happens inside `GetBody` instead. Whether that matters depends on the
server's response pipeline, which is not examined here.

## Why no number

The client cannot see it. Framesaver measures the callback that *parses* the response — that is the
~0.34 µs/char figure — which begins after the server has finished. The gap between request and response would
include generation, but it also includes queueing, serialisation and transport, and nothing on the client can
separate them. The server's own timing log is, per consequence 1, the wrong number.

Two ways to settle it, neither needing us:

- **Add one `.ToList()`** after the `Where` and re-read the existing debug log. If the reported figure jumps
  from near-zero to something substantial, consequence 1 is confirmed by the same instrument that was wrong.
- **Time `GetBody`** at `BotCallbacks.cs:54` against the `GenerateMultipleBotsAndCache` figure. The
  difference is the generation that the stopwatch missed.

## Standing

Unverified as to impact. The mechanism is plain from the source and the misleading comment makes intent clear
enough that this is very likely a bug rather than a design choice — but "very likely a bug" and "costs
anything" are different claims, and only the first is supported. **If this is raised upstream it should be
raised as consequence 1 only** — a timing log that does not measure what it says — which is checkable, small,
and does not require anyone to accept a performance claim we have not made.
