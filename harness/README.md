# Test harness — one command up, one command down

```
harness\run-raid.bat
```

Starts the SPT server, waits until it actually answers, starts the client against
it, and stops the server when the game closes. Runs the pre-raid and post-raid
checks around it.

`run-raid.bat -DryRun` runs both check phases and starts nothing. Safe any time,
including while the game is open — use it to answer "is the right build
deployed" without launching anything.

## Why it exists, which is not keystrokes

The checks around a run stop being things someone remembers:

| when | what |
|---|---|
| before | which commit the deployed plugin was built from, and whether it matches the approved one; what the config is set to; whether anything is already running |
| after | which log this run produced, and what the latch validator says about it |

**The commit is read out of the assembly**, not from a filename or a
written-down hash. On 2026-07-28 four artifacts were misnamed and an approval
went stale six times — every one of them true when it was sent. A check that
runs at the moment of use cannot go stale.

The expected commit lives in `harness/GO`. A mismatch **stops the run before
anything starts**, because at that point either the approval is stale or the
deploy is, and guessing which costs a raid. `-Force` overrides it and says so.

Nothing here modifies the plugin, the config, or a profile.

## The launch arguments, and why they are not a guess

The client is started with exactly what the launcher builds at
`SPT.Launcher.Base/Controllers/GameStarter.cs:140`:

```
-force-gfx-jobs native -token=<profileId>
-config={'BackendUrl':'<url>','MatchingVersion':'live','Version':'live'}
```

Single quotes are not a typo — `Json.SerializeSingleQuotes` sets Newtonsoft's
`QuoteChar` to `'`, so that is genuinely what goes on the command line.

**An earlier version of this script passed only `-token` and `-config` with just
`BackendUrl`, and that was wrong in a way worth recording.** SPT's own
`RequestHandler` reads only those two, so it would have *worked* — but:

- **`-force-gfx-jobs native` is a graphics-job threading flag.** Omitting it
  risks changing `render`, which is the quantity Protocol B exists to measure,
  against every log already in the corpus. `boot.config` also sets
  `gfx-enable-native-gfx-jobs=1`, so the two agree and omitting the flag may well
  be harmless — but "may well be" is not a basis for a measurement.
- **`ClientConfig` carries `Version` and `MatchingVersion` too.** SPT ignores
  them; BSG's `ApplicationConfigClass` does not.

The launcher binary could not answer this — it is a 29.5 MB single-file bundle
and searching it for argument strings returns almost nothing, which is an
instrument seeing nothing rather than evidence of absence. The launcher *source*
answered it in one line.

`-CaptureArgs` is therefore **optional now**, kept for the case where a future SPT
version changes the arguments:

```
harness\run-raid.bat -CaptureArgs
```

It starts the server and the launcher, waits for the game to appear, and records
the real command line to `launch-args.json`. Press Start in the launcher as
usual. On replay the token and backend URL are substituted from the current
profile and `http.json`; every other captured argument passes through untouched.

## What it does not do

- **It does not enter a raid.** Menu navigation is not automated, so the
  "consistent protocol" it enforces is setup and teardown, not the run itself.
  The protocols in [TESTING.md](../TESTING.md) are still executed by hand.
- **It does not pick a profile.** More than one profile in `user\profiles` is a
  hard stop rather than a choice made for you.
- **It never stops a process by name.** Only the server it started is stopped,
  by PID — a second server you started deliberately is left alone.
- **It does not verify the server is healthy**, only that it answers
  `/launcher/server/version`. A server that starts and then breaks looks fine here.

## Teardown

Server shutdown is in a `finally`, so Ctrl-C and an unexpected error both still
stop it. It is asked to close first and killed only if it refuses after 20 s, so
the server gets a chance to save.

A server left running headless after a crashed harness is the thing this is for.
If the harness itself is killed hard enough to skip `finally`, check for a stray
`SPT.Server` before the next run — the pre-flight check will also refuse to
start while one is up.

## The precondition gate

`harness/registrations.json` holds registered predictions whose stated
dependencies the harness checks. **A raid does not start while one is
unresolved.**

This exists because of one specific failure. A registration in FINDINGS.md said
of itself:

> *"If item 4 also latches `endToStart` at the boundary, the alignment changes
> and this needs re-deriving **before** the raid, not after. Beta owns that
> decision and has been asked."*

Item 4 shipped. The raid ran. It was not re-derived, and a 324 ms disagreement
arrived looking exactly like the refutation of a headline. **Nobody forgot** —
the precondition was written, assigned, and readable. It failed because nothing
in the path from registration to GO had to look at it.

**The default is the design, not the gate.** `precondition` is `unresolved`
unless someone says otherwise, and a *missing* field counts as unresolved too.
Silence blocks rather than passes. Any scheme that needs someone to declare a
dependency in a structured field fails the same way the rules that failed on
2026-07-28 did — staging by path, announcing the file, checking the diff — each
precise, each requiring an act nobody was forced to take.

Resolving is explicit and attributed: set `precondition` to `resolved` and fill
`resolvedBy`. **Resolved by nobody is not resolved** and blocks as well. A false
block costs a line of typing; a false pass costs a raid.

### What it does not cover, stated in its own output

Most registrations are prose in FINDINGS.md and this gate cannot see them. It
prints how many `Registered` mentions exist there against how many are
structured here, and warns that the difference is unchecked — because a check
that appears to cover more than it does is the failure family the whole gate
came out of.
