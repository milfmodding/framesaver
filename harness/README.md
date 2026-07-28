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

## Run `-CaptureArgs` once, and here is the honest reason

```
harness\run-raid.bat -CaptureArgs
```

This starts the server and the **launcher**, waits for the game to appear, and
records the client's real command line to `launch-args.json`. Press Start in the
launcher as usual. After that, `run-raid.bat` starts the client directly and the
launcher is never needed again.

**Why not just pass the arguments SPT documents?** Because I could not verify
what the launcher actually passes. `SPT.Launcher.exe` is a 29.5 MB single-file
bundle, so searching it for argument strings returns almost nothing — and that
is an instrument seeing nothing, not evidence the arguments are absent. No EFT
or BepInEx log on disk records a command line either.

What *is* verified, from SPT's own source rather than from memory:
`SPT.Common.Http.RequestHandler` reads `-token=<profileId>` and
`-config={"BackendUrl":...}` and nothing else, by plain string replacement.

So the minimum is known and sufficient for SPT to function. What is unknown is
whether the launcher passes anything **more** — a graphics flag, a Unity switch —
and if it does, a harness that omits it is launching a different program than
every log in the corpus was recorded under. That would be a silent comparability
break, which is the expensive kind.

Until `launch-args.json` exists the harness uses the known minimum and **warns
loudly on every run**. Capture replaces a guess with a measurement, and it costs
one launch you were going to do anyway.

On replay the token and backend URL are substituted from the current profile and
`http.json`; every other captured argument is passed through untouched.

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
