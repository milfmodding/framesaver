# Gamma state — written 2026-08-03 for a cold reboot onto the Akhashic Record

Alpha's steer, and it is the right one: **a rebooted Gamma can re-derive a conclusion and cannot
re-derive why something was ruled out.** So this file is eliminations, rules and bets. The
conclusions are in [FINDINGS.md](FINDINGS.md), the corpus caveats in
[analysis/CORPUS.md](analysis/CORPUS.md), and the method rules in
[analysis/selftest/README.md](analysis/selftest/README.md). None of that is repeated here.

---

## 1. THE RULE FOR A FIELD YOU HAVE NEVER MET

Alpha asked for this one by name, and it is the most transferable thing I hold. `bots.*` being
instantaneous is recorded everywhere; **how you classify the next field is not recorded anywhere.**

**`Telemetry.ResetWindow()` is the manifest.** Every window aggregate in this project appears in
that one method (`Telemetry.cs:2145`), either as `_x.Reset()` or as `X.ResetWindow()`. So:

| where the backing store lives | what the field is | how to read it |
|---|---|---|
| named in `ResetWindow()` | **window aggregate** | covers exactly the frames since the last flush |
| computed in the emit path from live game state | **instantaneous point sample at window close** | one observation, no duration |
| a static with no reset partner | **session-cumulative** | its per-window meaning is a *difference* nobody computes for you |

The check is one command and it does not depend on trusting me:

```bash
grep -n 'ResetWindow()\|\.Reset()' Telemetry.cs
```

**The third row is the trap, and it has already bitten once.** `animCulled` was session-cumulative
with no raid reset, which is why it exceeded the entire bot population from raid 2 onward — the
defect in CORPUS.md is this classification error wearing a data-quality costume.

**The corollary is the part that costs statistics rather than sanity.** A field's category is a
property of its storage, not of its name. `updateManual.awakeCalls` and `bots.awake` read as the
same quantity in two units; they are a window aggregate and a point sample. Regressing an aggregate
on a point estimate attenuates the slope toward zero, so **the failure mode is a real effect
reported as a null** — `alpha-animator-slope.py` did exactly that and
`alpha-animator-aggregate.py` supersedes it.

**And ask the design-time question of every new field, before it exists:** *what would make this
reading absent, and is that thing correlated with what I am measuring?* CORPUS.md has four
instances where the answer was yes and nobody had asked. It is cheap and it works on a field that
has never run.

---

## 2. FIELDS THAT ARE LOAD-BEARING, OR MISLEADING, FOR A REASON NOBODY WOULD GUESS

Instrument continuity means we add beside rather than replace, and the cost is fields a future
reader will find, quote, and have to be talked out of. The ones I would be talked out of:

- **`frame` on a spike line is not authoritative and `period` is.** `frame` is BSG's own counter and
  lags by one frame; it is *kept only for continuity with the window summaries*
  (`Telemetry.cs:1095`). `period` is the wall time between the two `ReadAndReset` calls that bracket
  the phase values on that line, so `period − sum(phases)` is a true residual and
  `frame − sum(phases)` is not. The spike gate tests `period`, deliberately.
- **`frames` is not the denominator `tickedSum`/`liveSum` accumulated under; `n` is.** `n == frames`
  on 284 of 284 lines, so this is a latent hazard with zero instances — recorded at that strength on
  purpose, because an entry that reads as a live defect when the thing has never happened spends
  credibility the real entries need.
- **`framePct.p999` at 30 s windows is the second-worst frame wearing a percentile's name.** It
  could not separate arms at 60 s either, so nothing working is lost by refusing to quote it.
- **`cfg.brainPeriod` reports the value requested, not the value in force.** With SAIN installed and
  the default `Defer to other AI mods`, an arm labelled `0.1` never sliced. Reading the resulting
  null as *"slicing does not help"* retires a fix on evidence that never tested it.
- **`initHeapDeltaMb` is unusable and no filter separates the good readings from the bad.**
- **The `proc` block is read through psapi, not `System.Diagnostics.Process`,** because
  `WorkingSet64` returns 0 under this Mono in every window of every run. Whoever "simplifies" that
  back to the BCL call gets a field that is *bytes-identical to a real zero from inside the log*.
  The zero guard is the instrument, not padding around it.

---

## 3. `standByTransitions` IS HALF-BLIND, AND THE HALF THAT WORKS IS WHAT HIDES IT

Alpha flagged the known defect: `woken`/`slept` live inside our own pump
(`BotStandByUpdatePatch.cs:222,389`), which mod-off returns before reaching, so the marathon logs
read `≡ 0` while vanilla slept thousands of bot-windows in the same file. That much is in
ALPHA-STATE.

**What is not written down anywhere is that the block is split, and split along sub-counter lines.**
Verified today at source:

| sub-field | driven from | arm-dependent? |
|---|---|---|
| `woken`, `wokenMs`, `slept`, `sleptMs` | `BotStandByUpdatePatch` — **our pump** | **yes, ≡ 0 when it is off** |
| `diedAwake`, `diedAsleep` | `BotLogPatches.OnDead` — ungated | **no, live in every arm** |

**So a reader sanity-checking the block sees nonzero values and concludes the zeros are real.** The
liveness check passes because a *different sub-counter* is live. That is the exact failure this
project has catalogued four times over — a check that reports a pass without reporting what it
tested — arriving inside a single JSON object, where nothing suggests the six numbers have
different provenance.

**The general shape, which is what to carry forward: a counter that lives inside the feature it
measures cannot distinguish "the feature is off" from "the feature is on and nothing happened."**
`AwakeAge` is the counter-example and the reason the shape is fixable: its spans are driven from the
`StandByType` **setter** (`SleepingBotAnimatorPatch.cs:486-509`), so they see every transition
whatever caused it, including another mod's.

**And one clean result, recorded because it is worth as much as a defect here.** `AwakeAge.Ended` is
called from inside `SleepingBotAnimatorPatch.cs:504`, which *looks* like an anim-cull-gated
lifecycle and would mean awake-age spans terminate differently between cull arms — a
treatment-correlated censoring in the instrument used to compare those arms. **It is not gated.**
That call site is in the setter patch, not the cull patch. I checked; a rebooted Gamma will see the
same file name and suspect the same thing, so: already checked, clean, do not spend the day.

**Sibling defects of this shape that I suspect and have NOT proven** — flagged as hunches, which is
what they are:

- `SpawnAttempts.NoteBuild`/`NoteCreate` are timed around our own spawn hooks. If a spawn path
  exists that does not traverse them, the counter is arm-conditional in the same way and nothing
  says so.
- `AsyncDrainPatch` is the only patch file that both reads config flags and owns counters
  (3 flag reads, 2 counters). That co-location is the structural precondition for this defect. I
  have not read it closely enough to claim one exists.

---

## 4. `deadCalls` — THE ELIMINATIONS, WHICH ARE THE EXPENSIVE PART

`updateManual.deadCalls` is identically zero across **205 windows**, while **65 of those same
windows** report `bots.deadAwake > 0`. Both sites read `IsDead` on `BotOwner`
(`Telemetry.cs:1819`, `Patches/UpdateManualTimingPatches.cs:206`).

**Ruled out, each for a stated reason:**

1. **Not a skipped prefix.** `__state` defaults to 0 when the prefix does not run and the postfix
   routes that to `AddUnstamped`. `unstampedCalls` is **0** in every window. That counter exists
   precisely to catch this.
2. **Not an era artefact.** `AddDead` and its emit landed together in `86407a4`, an ancestor of
   `bc90b76` — the binary stamped in the header of the logs in question. The key is present on all
   205 windows, so the build could emit it.
3. **Not two different liveness tests.** Alpha's framing. It is one expression on one type,
   answering differently in two call contexts — a much narrower thing to hunt.
4. **Not corpses being absent from the update set.** `BotsClass.UpdateByUnity` iterates without a
   `BotState` filter (established at `BotStandByUpdatePatch.cs:42`), and the rate agrees:
   `awakeCalls/frames` tracks `bots.awake` at **2.6%** median error and `awake − deadAwake` at
   **47%**, over 53 corpse-carrying windows. Corpses tick.
5. **Not emit/reset ordering.** `Append` precedes `ResetWindow` in the flush.
6. **Not Unity's fake-null on a destroyed `BotOwner`** — this was my top bet and it died today.
   `__instance != null` returning false would explain the postfix perfectly, but the census applies
   the *same* `bot == null` guard at `Telemetry.cs:1801` and `continue`s before reaching
   `deadAwake++`. A destroyed corpse would be invisible to **both**. `deadAwake > 0` refutes it.

**What is left is irreducible and it is not in the corpus.** Corpses tick, the postfix runs on them,
and `IsDead` returns false for a bot the census calls dead. Every remaining explanation is a
property of `BotOwner.IsDead` itself.

**So the next move is not another log query, and this is the item most likely to be lost.** Every
instinct says query the corpus harder; the corpus has already said everything it can. The
discriminating evidence is on **the game-assembly side of the join** — the one side neither the
census nor the patch consulted. Decompile `BotOwner.IsDead` in SPT 4.0.13. That is the far-side rule
from `analysis/selftest/README.md` applied to a live defect rather than to a post-mortem.

**The in-mod discriminator, if the assembly route is closed.** Add a second predicate beside
`deadCalls` — never instead of it — reading death by a different route in the same postfix
(`BotState`, or the health controller). Disagreement means `IsDead` is context-dependent; agreement
at zero means the postfix genuinely never meets a corpse and the census roster is the odd one out.
One field, one raid, and it splits the remaining hypothesis space in half.

**Do not "fix" it by subtracting `deadAwake`.** Within Streets, per-call cost falls to 0.70 as the
corpse fraction rises where *corpses are free* predicts 0.21; solving the mix gives corpse ≈ 0.0098
against live ≈ 0.0186 ms/call — **about half a live bot, not zero.** Two legs and crude terciles, so
suggestive rather than established. The usable consequence: `awakeCalls` over-counts and
`awakeCalls − deadAwake` over-corrects, so **any per-bot figure is a bracket bounded by the two, not
a point**, until `AddDead` works.

---

## 5. DECISIONS, WITH THE REASONING THAT MADE THEM

- **Readers refuse a pooled corpus rather than warning about one** (`steady.resolve_inputs`,
  `--pool` to override). Pooling two populations produces a plausible number with **no signature** —
  nothing goes out of range — so a warning above a result that looks fine reads as noise. This came
  from a day spent reading the corpus `CORPUS.md` explicitly excludes, while every reader printed
  its filter in detail and never named the directory it opened. **A population is (definition,
  input), and stating the definition precisely is what hides the input.**
- **`read-animcull.py` prints DESIGNED OUT, not a verdict, when `cfg.skipLate` is false throughout.**
  The protocol pins the LateUpdate skip off in every arm — correctly, since that is the only
  mechanism that produces a latch. A near-zero `animCulledEngine` on a control arm there is
  therefore *designed out*, not ruled out. I told Beta the opposite first; the correction inverted
  the finding, not just the wording.
- **`animCulledEngine` is deliberately ungated on the cull flag** while its two neighbours are. That
  is the whole of its value: a flag flipped off mid-session reads as a *disagreement* with
  `animCulled` rather than as a clean arm. **It is the only field in that block whose zero does not
  follow from its own feature being off — read it against `animCulled`, never alone.**
- **`deadCalls` counts rather than drops.** A silently dropped contamination arrives as a surprise
  in the ramp; a counted one is measurable. Same reasoning behind emitting `boundaryMissedFrames`
  and `clockResidualFrames` at all: **an instrument that can go dark must say how often it did.**
- **No `StandBy == null` bucket in the UpdateManual prefix**, unlike `CountBots`. The wrapped body
  dereferences `StandBy` unconditionally, so a null would have thrown in vanilla before our postfix
  could run. A counter for a state the game cannot reach is a moving part that only ever reads zero.
- **`probe-symbols.py --key` requires a `#US/utf16` hit.** Three levels of one failure: grep matched
  the UTF-8 heap and missed UTF-16 literals; `probe-symbols` matched either heap and so answered
  `ok` for a *member* name; `--key` matches a real literal and still cannot prove which field owns
  it. **An instrument that matches on a name can only ever tell you that a name matched.** Applied
  forward: new fields get names that cannot collide, which is why the AI-mod defer setting ships as
  `deferToAiMods` and not `defer`.
- **Never close the two missing provenance fields by reading `ModCompat` from the header.**
  `EnsureDetected()` latches its answer, and `WriteHeader()` runs inside `Telemetry.Awake()` when
  `Chainloader.PluginInfos` need not yet hold plugins that load after us. BigBrain would read
  absent, the latch would stick, and **`SuppressSlicing` would be false for the whole session — the
  compatibility guard silently off, from a change that only meant to log something.**

---

## 6. HUNCHES, UNPROVEN, WHICH IS WHY THEY ARE HERE

Alpha is right that these are the highest-value items precisely because no artefact carries them.
Each is a bet, not a finding.

> **Two of these are now duplicated into `ALPHA-STATE.md`'s odds table (`05adb7d`) — revise both or
> neither.** Recorded here rather than left to be discovered, because the duplication is deliberate
> (odds have no re-derivation path, so a single copy is a single point of loss) and because a claim
> quietly forked into two files is exactly how the two stale counts in my own shared file expired.

- **The `deadCalls` mechanism is a property of `IsDead`, ~70/30 over anything in our code.** Five
  code-side explanations died today; none of the property-side ones has been touched.
- **`framePct.p999` and `p99` are probably not worth carrying at 30 s at all**, and the reason to
  keep them is instrument continuity rather than any expected use. I would bet against either ever
  separating an arm in this project.
- **The `awakeCalls` ≈ `bots.awake` agreement at 2.6% is better than it has any right to be**, given
  one side is a window mean and the other a single endpoint sample. It is load-bearing for the
  denominator finding (33 of 34 quiet windows, 97%), and if a future window disagrees badly I would
  look at roster churn before looking at the counter.
- **I do not believe `n` will ever diverge from `frames`,** and I would still not let anyone delete
  `n`. The divergence has zero instances across 284 lines; the cost of the field is one integer.

---

## 7. DEFERRED, MINE, IN THE ORDER I WOULD DO THEM

1. `closedBy: timer|state|protocol|session` on the sample line — after raid 2, with Beta's
   roster-walk consolidation. **Beside `final` and `flushedByProtocol`, never instead.**
2. The `deadCalls` discriminator in section 4.
3. `MIN_WINDOWS = 3` re-expressed in the unit its intent is actually in, then equivalence-proved on
   the corpus before adopting. Changing a threshold without that is how an undated era boundary gets
   created.
4. Wire `read-animcull`'s presence check to per-record `fieldsObservedInLogs` for SPT4.0.13 **if**
   the binary→logs join there ever becomes 1:1. It is ground truth for `Base` only today.

---

## 8. VERIFIED STATE AT WRITING

Measured 2026-08-03 against `F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs`, **25 logs**.

- HEAD `89cb708`, working tree clean before this file. Deployed binary `bc90b76`; nothing since.
- `read-updatemanual` rc=0; `read-animcull`, `read-botwindow`, `read-botarm` rc=1 — **correct**,
  they gate on fields no log carries yet, and an rc=0 from any of them before a raid would be the
  bug.
- **The readers no longer default to a glob: no arguments is bad input, rc=2.** Pass paths.
- Harnesses `um`/`bw`/`ac` at 12/7/14 cases, all rc=0, each asserting an exit code **and** a line
  the case must print. That second half is the fix for a suite that had been silently dead from the
  day it was committed.
- `deadCalls` re-derived today rather than carried forward: **205** windows carry the key, **0**
  above zero, **65** of those with `deadAwake > 0`, `unstampedCalls > 0` in **0**.

**One near-miss from writing this file, because it is the cheapest possible instance of the rule.**
I first recorded all four readers at rc=2 and read it as the pooled refusal firing. It was Python's
*"can't open file"* — the Bash tool's working directory had persisted from an earlier `cd`, and
**CPython exits 2 for a missing script while these readers exit 2 for bad input.** A mistyped path
and a legitimate refusal are the same integer. Exit codes are the thing I tell everyone to assert
on; assert on a line they must **print** as well, which is the same fix the harnesses already got.

— Gamma
