# State: the mod-off marathon is armed and waiting on Sophia

Written 2026-07-30 to survive a context reset. **Method and state, not conclusions** — a handoff amplifies
whatever it emphasises and cannot re-derive what it carries, so everything below points at a script that can be
re-run rather than at a number to be trusted.

## THE STOPPING RULE, FIRST, BECAUSE A FRESH CONTEXT WILL WANT TO GENERATE

**Nothing further from Alpha until the marathon runs.** Today produced 102 team commits, 12 touching shipping
code, and **zero raids**. The corpus is large enough that there is always another defensible thing to check, so
the gate has to be named rather than felt:

> **Between runs, produce only what changes what happens in the next run.** Not "is it true", not "is it
> interesting". When there is nothing to measure, the correct output is silence.

If you are reading this with no context and feel the urge to sweep a reader or re-check a population: that urge
is correct on the merits and wrong on the timing. Wait for the logs.

## WHAT IS ARMED

    harness/GO                bc90b76      (approved; install md5 9c14f132..., stamp bc90b76)
    compiled source vs HEAD   no .cs differs from the deployed build
    config                    F:\SPT\SPT4.0.13\BepInEx\config\framesaver.ai.perf.cfg
    config backup             same path + .pre-modoff-bak
    protocol                  NONE - parked as framesaver.protocol.ini.brain-slice-parked

Config state, applied and verified 2026-07-30 19:xx: every lever at its off value, `[1. Bot stand-by] Enabled =
false`, `[3. Telemetry] Enabled = true`, `Run tag = modoff-marathon`, `Window seconds = 30`.

**The protocol was deliberately removed, not forgotten.** `ProtocolRunner.Load()` does not apply the first block
— it arms and waits for a keypress — and "no file is not a failure" is designed for. A baseline has nothing to
alternate, and a protocol that duplicates config values is a second source that can disagree with the first.

## THE RUN

Nine raids, one session, ~10 minutes each: Ground Zero → Streets → Interchange → Customs → Factory → Woods →
Reserve → Lighthouse → Shoreline. **Labs separately**, because Labs has never launched successfully and
isolating it means a Labs failure does not cost the other eight.

## AFTER EACH RAID — the two commands that carry the reasoning so nobody has to remember it

    python harness/check-modoff.py <log.ndjson>     # were the levers actually off?
    python harness/check-fields.py <log.ndjson>     # did the telemetry record what it should?

`check-modoff.py --plan` prints the settings by their F12 names. Both refuse rather than pass when they cannot
tell, and `check-modoff` states on every run what a clean result still does **not** mean.

## FOUR THINGS ABOUT THIS RUN THAT ARE NOT OBVIOUS FROM THE LOGS

1. **`Enabled = false` is not "mod off".** It gates two patch sites. Five further levers keep acting, four of
   them engine-level, and four off-values are counter-intuitive (`Max delta time = 0` and `Async drain budget
   ms = 0` both mean *hand it back to Unity*, not *disabled*). This is why the verification reads the `cfg` block
   the run wrote rather than the config file: the file is intent, the log is what ran.

2. **The baseline is not vanilla, structurally.** Our replacement of `AICoreControllerClass.Update` runs whenever
   telemetry is on, and telemetry must be on. It mirrors vanilla except that it logs the first few agent
   exceptions (cap 10). Same for the player-loop profiler, which stays on because the mod-on corpus has it on.
   **Both are in both arms, so a mod-on minus mod-off difference cancels them** — they bound what the baseline
   can be *called*, not what it can be compared to.

3. **Factory is a geometric control, not a wasted raid.** 46 × 72 m of player span against a 150 m sleep
   threshold: nothing there can ever be far enough away to sleep, so stand-by cannot fire. Its mod-on-versus-off
   delta is therefore a read on the four engine-level levers alone. A large Factory gap is informative, not
   anomalous.

4. **The last window of every raid is unusable for `bots.*` and the instant-sampled fields.** All 33 such
   windows in the corpus are the last of their segment — raid teardown, the census reads after the game object
   is gone. Frame data in them is fine. **`final` marks only 17 of 33 and is not the flag for this**; segment
   position identifies them exactly. `check-fields.py` reports them.

## THE 30 s CHANGE, AND THE ONE COMPARABILITY TRAP

`Window seconds` is 30 from this run onward. **This does not improve percentile precision** — per-window noise
rises by √2 and window count rises by √2, and they cancel; simulated in
`analysis/alpha-window-length-invariance.py`. The real gains are finer exclusion granularity and clearing
window-count floors.

**The trap:** `raidElapsed` is stamped at window *close*, so a seconds-based warm-up threshold is not
window-length neutral. `>= 120` discards the first 60 s at 60 s windows and the first **90 s** at 30 s windows.
A 30 s leg read against a 60 s leg under the old rule carries 30 s of extra warm-up exclusion, and since early
frames are slow the 30 s leg looks better for reasons unrelated to the mod.

Fixed: keep a window only if it **begins** after warm-up ends — `raidElapsed - windowSec >= 60`.

**THE EQUIVALENCE HAS SINCE BROKEN, AS DESIGNED. Corrected 2026-07-31.** This paragraph used to read
"identical on 418 of 418 existing windows, so no era boundary". Re-measured on `SPT4.0.13` after the marathon:
**384 evaluable windows, 374 agree, 10 disagree** — every disagreement a window `by_start` keeps and the legacy
rule drops, all at `raidElapsed` ~90 with a 30 s length. Which is what the rule was written to do: at 60 s
`e - 60 >= 60` *is* `e >= 120`; at 30 s it becomes `e >= 90`.

**The proof was correct and it was a property of a corpus that only had 60 s windows.** Nothing in the code
changed — Sophia halved the window and the two rules stopped coinciding. So `by_start` is still the right rule
and is no longer the *same* rule, and two people quoting "steady state" over the same field can now differ by
10 windows. Found by Gamma; the era boundary I said did not exist is the 30 s era.

Two things that make the re-measurement itself worth reading. **210 of the 594 in-raid windows carry no
`windowSec` at all** and are unevaluable rather than excluded — my first re-run folded them into False and
reported 198 disagreements, which is the same absent-is-not-zero defect I had fixed in `marathon-status.py`
that morning. And **no `Base` window carries `windowSec`**, so the rule cannot be evaluated on that corpus at
all: 0 of 301 evaluable. Warm-up is 60 s, measured: worst-frame ratio 4.53× in window 1, 0.97 by window 2, and the *mean* is at
baseline in window 1 — **a mean-based warm-up check finds no warm-up at all.**
`CORPUS.md` carries this as an era note.

## OPEN AND NOT MINE

- **QuestingBots is not installed** (verified: no client dll, no server mod, only a stale config). Raid 2's
  primary is an event criterion requiring it in `agents.mods`, so it is unmeetable until installed. Deferred by
  Sophia. `harness/check-mod-preconditions.py` gates on `@requires`.
- **`harness/release-manifest.json`** — Sophia's to write; `check-release.py` refuses until it exists.
- **The `CLAUDE.md` rule in her words** — writing it for her would break the rule it states.
- **Raid 2** is now `[A]` 900 s → `[B]` 900 s, not ABAB: `Force for all roles` is a one-way latch. Registered
  price, before any result: **it can confirm a benefit and cannot bound one**, because arm is perfectly
  confounded with raid age and drift runs against B.
- **Streets pools 16 raids, one of which slept nothing.** No treatment flag splits it; needs reading logs
  individually. Unowned.
- **Six maps still lack a p75.** The marathon is what closes that.

## THE NUMBER MOST LIKELY TO BE QUOTED WRONG

**Lighthouse default-config p75 is 17.40 ms / 57.5 fps — it FAILS the 60 fps gate.** The pooled 16.00 ms /
62.5 fps figure mixes in raid 1.5, which ran `Force for all roles` on. And `[default]` is itself 75 % one leg,
with the two legs 8 fps apart. **Do not quote the pooled number**, and do not read the 17 fps arm gap as what
`Force for all roles` buys — that is a between-leg contrast and the noise floor forbids it.
