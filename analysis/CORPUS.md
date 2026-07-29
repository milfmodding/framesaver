# The Framesaver telemetry corpus

Provenance and known defects for the ndjson logs shipped with this project, so the numbers in
[FINDINGS.md](../FINDINGS.md) can be re-derived rather than taken.

**The headline is the ratio, not the list.** Almost every defect below is *recoverable* — each one has a
filter a reader can apply, and the rules are one line each. Only two are fatal: `initHeapDeltaMb`, and the
absence of player position. Everything else narrows what a log can answer without invalidating it.

Field definitions are in [README.md](../README.md). Methodology, including why several of these defects exist,
is in FINDINGS.md's methodology notes.

---

## Dating a log: read the `cfg` key count, not the filename

Every `sample` line carries a `cfg` block. **Its key count is monotonic across the project's history and
partitions the corpus into three eras**, which is the primary way to date a log:

| era | `cfg` keys | gained | window |
|---|---|---|---|
| **A** | 11 | — | 2026-07-26 → `20260727-005816` |
| **B** | 15 | `suspendGc`, `reclaimStandBy`, `deactivateSleeping`, `keepFighting` | `20260727-010740` → `20260727-201220` |
| **C** | 20 | the two GC knobs, `drainInUpdateOnly`, `drainDiagnostics`, `gcSliceApplied` | `20260727-232217` onward |

**Prefer this to timestamps.** In-data provenance survives files being copied, renamed, or re-dated by a
filesystem; a timestamp does not. It also resolves the `Expand phase` semantic inversion below without needing
a build date — **the inversion lands inside era C**, so era plus expanded-phase content is sufficient.

### The same rule applies to EFT's own logs, and there the names are in a different timezone

**EFT names its log directories in UTC while stamping the lines inside them in local time.** The session
this project calls the 10:00 raid lives in `Logs/log_2026.07.28_17-00-51_.../`, and its first line reads
`10:01:17 -07:00`. Exactly seven hours, so it is an offset and nothing more interesting.

It is worth a line here because the failure mode is **concluding a session is missing rather than
misnamed** — which cost one check already. `framesaver-20260728-100048-postlate-gc.ndjson` and that
directory are the same session. Same principle as reading the `cfg` key count: trust what is inside the
file over what is on it.

---

## Per-log provenance

`animCulled infl` counts in-raid windows where `animCulled` exceeds `asleep`. **`line-pairing slip` is
normalised to `period > 100 ms` *and* to a magnitude cut of 1 ms** — both are required, and applying one
without the other is how two agents each read a phantom regression into the era-C logs. It counts lines
with `frame > period + 1 ms` **or** `unaccounted < −1 ms`; the two co-occur by construction, so they are
one column rather than two.

| log | state | era | spike ms | expanded | raids | maps | animCulled infl | line-pairing slip |
|---|---|---|---|---|---|---|---|---|
| `20260726-170412-baseline` | complete | A | 100 | PreLateUpdate | 5 | Interchange, TarkovStreets, bigmap, factory4_day | 20/30 | 1/34 |
| `20260726-183701-ai-stack` | complete | A | 100 | PreLateUpdate | 2 | TarkovStreets, factory4_day | 0/17 | 4/50 |
| `20260726-191139-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/6 | 1/12 |
| `20260726-205307-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/9 | 5/35 |
| `20260726-212828-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/3 | 2/7 |
| `20260726-231556-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/6 | 0/3 |
| `20260726-234729-ai-stack` | no in-raid | A | 100 | PreLateUpdate | 1 | — | — | — |
| `20260726-235721-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/7 | 2/13 |
| `20260727-002111-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/8 | 2/7 |
| `20260727-004848-ai-stack` | **empty** | — | 100 | — | 0 | — | — | — |
| `20260727-005816-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/2 | 0/5 |
| `20260727-010740-ai-stack` | complete | B | 100 | PreLateUpdate | 1 | TarkovStreets | 0/2 | 2/6 |
| `20260727-201220-ai-stack` | complete | B | 100 | PreLateUpdate | 2 | TarkovStreets | 10/22 | 3/33 |
| `20260727-232106-ai-stack` | **empty** | — | 100 | — | 0 | — | — | — |
| `20260727-232217-control` | complete | C | 100 | PreLateUpdate | 2 | TarkovStreets, bigmap | 12/28 | 8/76 |
| `20260728-092354-postlate-gc` | complete | C | **30** | **all 8** | 1 | TarkovStreets | 0/11 | 2/24 |
| `20260728-100048-postlate-gc` | complete | C | **30** | **all 8** | 1 | TarkovStreets | 0/9 | 2/13 |

**`state` matters and is a snapshot.** `empty` means zero sample and zero spike lines — an aborted launch,
nothing to find. `no in-raid` means the session never reached `state: raid`. **`live` means the file was still
being written when this table was generated**; a live log's counts are partial and its final window has not
closed. Regenerate the table rather than trusting a `live` row.

> **That instruction has already been needed once, which is the argument for it.** The row for
> `20260728-100048` shipped as `live` at `0/4` and `1/6`. The session then ended, and regenerating gave
> `complete` at **`0/9` and `2/13`** — the slip count doubled and the `animCulled` count more than doubled.
> Nothing was wrong with the original row; it was simply a measurement of a file that was not finished. **A
> partial row does not announce itself as partial once the numbers are quoted somewhere else**, which is why
> the `state` column exists at all.

> **A `live` log will also make an analysis disagree with itself, silently.** `delta-rederive.py` reported
> dropping **717 lines in one section and 719 in the next**, from the same corpus in the same run — the live
> file grew between the two reads. Small enough to look like rounding, large enough to be wrong, and **nothing
> in the output says a re-read happened.** Any script that touches the corpus more than once in a pass must
> **snapshot the file list and contents once**, not re-glob per section. Both tools here now do.

---

## Defects, stated as what a reader would wrongly conclude

### Recoverable

**`animCulled` exceeds the bot population from raid 2 onward.** `SleepingBotAnimatorPatch.Sleeping` is never
cleared at raid teardown, so every bot asleep when a raid ends stays counted for the rest of the session.
*Wrong conclusion:* any per-bot animator-culling rate computed from a multi-raid log is inflated by a constant.
**Recovery: use raid 1 of any log.** The table shows the mechanism confirming itself — inflation is confined
entirely to the three multi-raid logs and is **zero in every single-raid log**. The offset equals the prior
raid's final `asleep` count and accumulates across raids (0 → 18 → 41 → 62 → 76 in the five-raid log).

> **Fixed in the build deployed on 2026-07-28, so the recovery rule above applies to the logs listed here and
> must not be carried forward.** `SleepingBotAnimatorPatch.ResetForRaid()` now runs on each raid transition,
> alongside `Census.ResetForRaid()` and `ProtocolRunner.ResetForRaid()`. Confirmed present in
> `e6abe58c2e2199e143b279f3f29b1b7a` with `analysis/probe-symbols.py`, not grep.
>
> **This matters most for the run that needs it most.** *"Use raid 1 of any log"* would discard eight legs of a
> nine-leg transit marathon — the single cheapest way to cover the six maps this corpus has never launched. A
> stale recovery rule costs more than the defect did, because the defect only inflated one field while the rule
> throws away whole raids. **When a defect is fixed, date the fix in the same entry rather than deleting it**:
> the older logs still need the rule, and a reader cannot tell which side of the fix a log falls on without it.

**Spike counts do not join across logs.** `Spike event ms` has been 100, 50 and 30.
*Wrong conclusion:* that a log with more spike lines had more stalls. **Recovery: segment on the header's
`spikeEventMs`, and normalise to a common `period` cut before comparing rates.** The last two columns above do
this at `period > 100`. Without it the era-C 30 ms logs show a residual-defect rate **1.9× inflated** purely
because a lower threshold admits small frames, which are proportionally likelier to flip a fixed-size error.

**`Expand phase` inverted meaning on 2026-07-28.** It was an allowlist naming one phase to decompose; it became
a blocklist. *Wrong conclusion:* that a log lacking a phase's children had that phase suppressed, when in the
earlier semantics it simply was not selected. **Recovery: era, plus the `expanded` column.** Era A and B are
allowlist; the inversion is inside era C, where the current logs expand all 8.

**A phase missing from `phases` means `< 0.5 ms`, not zero.** Sub-threshold phases are dropped from the JSON
while still counting toward `accounted`. *Wrong conclusion:* that an absent `TimeUpdate` means no time was
spent there. **Recovery: read absence as "below threshold".** Note the asymmetry — `TimeUpdate` absent is the
*normal* in-raid case, so its **presence** is the signal.

**`state` reads `loading` at the menu.** `CurrentState()` gated `Menu` on `GameWorld` being absent, and the
world persists after a raid. *Wrong conclusion:* that menu-idle lines of 545,800 ms and 1,149,837 ms are
loading stalls. **Recovery: filter `period > 60000`**, or exclude by inspection — there are two in the corpus
and both are unmistakable.

**`unaccounted` is unreliable on a minority of in-raid spike lines**, sometimes going negative, with `frame`
exceeding `period` on the same lines. *Wrong conclusion:* that residual-dominant frames are a single
phenomenon, or that a negative residual is meaningful. **Recovery: the affected lines identify themselves —
`frame > period` is on the line.** Use a magnitude cut of **`< −1 ms`**: the mechanism's signature is −56 to
−200 ms, and pooling sub-millisecond jitter with it changes the headline by ~4×.

**Rate varies 0%–33% across logs at identical threshold, so this is a property of the *run*, not of the
instrument** — it tracks how often the `Update`-phase stall occurs, which moves with mod stack and map.
The high rates are all small-`n` logs; among the five with `n ≥ 30` the range is **2.9%–14.3%**
(~~0.0%–14.3%~~ — no `n ≥ 30` log reads zero; the zeroes are all in logs of 3 and 5 lines), and the era-C
30 ms logs sit inside it. ~~**There is no build-related trend**~~ — **the corpus cannot support that claim;
see below** — and the unfiltered rate suggests one only because it is 1.9× inflated at the lower threshold.

> **Unresolved, not resolved, and the distinction is load-bearing.** Two agents each read a phantom
> regression into the era-C logs and each corrected the other, which makes "no trend" feel like the
> hard-won answer. It is not. It is the absence of one. Pooling both 2026-07-28 logs — same build, same
> map, same threshold, which is the one cross-log pooling this corpus permits — gives **4 of 37, 10.8%**
> against the control's **8 of 76, 10.5%**. Fisher exact **p = 1.000**; Wilson 95% CI **[4.3%, 24.7%]**
> against **[5.4%, 19.4%]**.
>
> **The design is nearly blind in both directions.** At n = 37 the observation would have to reach **8 of
> 37 — a 2.1× regression — before its interval excludes the control**, and below the baseline **only 0 of
> 37 separates at all**. So every outcome from 1 through 7 reads identically, and nothing short of total
> elimination registers as a fix. Quoting 10.8% as evidence of no regression and quoting it as evidence of
> improvement are the same error in opposite directions.
>
> **If this is reopened, what it needs is more in-raid spike lines, not more analysis of these 37.** Every
> derivation anyone has run against them is already in this corpus, and
> [power-check.py](power-check.py) prints the interval arithmetic above.

> **The limit of that recovery, and it is the reason the defect matters at all.** Self-identification finds
> the **source** line and never the **destination**. The mechanism moves time from line N to line N+1: N is
> large and carries the marker, **N+1 is ordinary and carries nothing**. So filtering on `frame > period`
> leaves a reader holding a set of displaced-*from* lines and believing the corpus is clean, when the lines
> the time landed *on* are indistinguishable from ordinary frames.
>
> Worse, **no magnitude threshold can select the destination**, because the defect makes it ordinary by
> construction. That is why [nothing needing the frame after a spike is answerable](#what-this-corpus-cannot-answer)
> anywhere in this corpus, and why the fix is a sampling-boundary change rather than a filter.

**A clobbered phase and a fast phase look identical — but no log in this corpus shows one.** README's rule
is that an absent phase means `< 0.5 ms`. `PlayerLoopProfiler.MarkersPresent()` returns `true` as soon as
**any one** top-level phase still carries its `BeginMarker`, so a mod or a loop rewrite that drops seven of
eight triggers no reinstall and those seven silently emit nothing. *Wrong conclusion:* that a phase which
vanished was cheap.

**Checked rather than assumed, because this one is testable retroactively.** Across all 14 logs with in-raid
phase data, **no top-level phase is absent for a whole log, and none disappears mid-log** (present through
window *k*, absent for every window after). Both scans returned zero. So this is a latent weakness in the
guard, not a defect in the data — every log here is clean of it.

**Recovery for future logs:** a clobbered phase contributes nothing to `accounted`, so its duration lands in
`unaccounted` instead. The signature is therefore a *sustained* absence of the **same** phase across
consecutive windows **together with an inflated `unaccounted`** — not the per-window absence that
`TimeUpdate` shows normally. One phase blinking out for one window is the 0.5 ms threshold; the same phase
gone for the rest of the session while the residual grows is the guard failing.

**Window length is on the header and nowhere else, against a setting that is live-editable.** Every
per-window rate in this project divides by it — `frames ÷ windowSeconds` is how fps per window is computed
— and no `sample` line carries it. `cfg` is repeated per line precisely because BepInEx config can change
mid-session; `Window seconds` is the one setting that governs the line's own denominator and is *not* in
`cfg`. *Wrong conclusion:* that a rate computed from `frames` is comparable across a session in which the
setting was touched. **Recovery: read `windowSeconds` from the header, and treat any log where it may have
been edited live as having no reliable per-window rates after the edit** — nothing in the data would say.
No log in this corpus is known to have been edited that way, and none could show it if it had been.

**`drawCalls.max ÷ .avg` rises with window frame count** — `corr(frames, ratio) = +0.484` over 76 in-raid
windows, median **1.48** in the lowest third by frame count against **1.81** in the highest. A `max` has
more chances to be extreme when there are more samples, and frame counts across this corpus span **659 to
6,299**, nearly 10×. *Wrong conclusion:* that the ratio is comparable between a low-fps window and a
high-fps one, or that the ≤ 1.15 held-view threshold means the same thing in both. **Recovery: compare the
ratio only across windows of similar `frames`.** The threshold survives its intended use — a genuinely
held view drives the ratio to ~1.0 by having no view change at all, not by sampling less — but it is
calibrated on ~60 s windows and **must not be transported to a partial one.**

**`unaccounted` cannot be recomputed from the emitted `phases`, and the discrepancy is worst where someone
would go to check the instrument.** All eight top-level phases are accumulated; only those ≥ 0.5 ms are
*emitted*. In `EmitSpikeEvent`, `accounted += phase[i]` runs **before** the `< 0.5d` `continue`, in the same
loop — so **`unaccounted` on the line is correct** while a spike line typically shows 3 to 6 phases, not 8.
*(Cited by structure rather than line number: both sites have already moved once today, and a stale line
reference is the same failure this file exists to catalogue.)*

Across 14,790 in-raid spike lines:

| | median |
|---|---|
| hidden sub-0.5 ms phases | **0.417 ms** |
| naive `period − Σ(emitted phases)` | **0.473 ms** |
| **true `unaccounted`** | **0.017 ms** |

*Wrong conclusion:* that the residual is ~0.5 ms on ordinary frames, or that `unaccounted` is broken. **A
28× overstatement on ordinary lines and 0.1% on the 71 large ones** — so the error is negligible exactly
where the findings live and severe exactly where a sceptic would sanity-check. Someone recomputing by hand
gets 0.473 against a true 0.017 and concludes the instrument is defective.

**Recovery: use the emitted `unaccounted`; never re-derive it from `phases`.** And the general form, because
this is the more dangerous shape of the two: **a hazard that makes a healthy instrument look defective to
the person checking it is worse than one that corrupts a result** — a corrupted result is wrong about one
thing, while a discredited instrument takes every other number in the file with it.

**`gpu.vram` reads a string on the first window of each GPU-carrying log.** Initialisation, not failure.
*Wrong conclusion:* that the `overBudget` regression guard is absent. **Recovery: skip window 0** — the field
is live in 14 of 15 windows in the most recent log.

**`best p50` in the stage-1 table is a best-*window* figure.** *Wrong conclusion:* that it is a baseline.
Quoting it as one produced a phantom 40% disagreement with the user's own observation; the Streets median is
16.51 ms against that column's 11.51. **Recovery: read the median columns in
[TESTING.md](../TESTING.md).**

**On a `flushedByProtocol` line the labels and the measurements describe different arms.**
`ProtocolRunner.Advance()` applies the step's assignments and increments `StepIndex` *before* returning true,
and the caller flushes after — so `protocol.arm`, `protocol.step`, `cfg.brainPeriod` and `agents.slicing` name
the arm **about to start**, while `tickedSum`, `liveSum` and every timing figure describe the arm that just
**ended**. *Wrong conclusion:* that the arm labelled on that line is the arm measured on it — and this is worse
than the usual mislabel, because `agents.slicing` is precisely the field a reader takes as ground truth for
whether the manipulation was live. **Recovery: drop `flushedByProtocol` lines.** They were already excluded for
being partial windows; that is the weaker reason. Whole windows inside an arm are self-consistent.

**`frames` is not the denominator `tickedSum` and `liveSum` were accumulated under** — but the divergence has
**never once occurred**, and the safe denominator was already on the line. `frames` is `_periodSamples`,
incremented unconditionally, while the two sums accumulate behind `if (m != null)`; `n` is emitted behind that
same gate, and **`n == frames` on 284 of 284 sample lines across all 18 logs.** So this is a latent hazard with
zero instances rather than a defect, and it is recorded at that strength deliberately: an entry that reads as a
live defect when the thing has never happened costs this document the credibility its recoverable entries
depend on. **Use `n` or `liveSum`, not `frames`, and expect no difference.**

`tickedSum ÷ liveSum` remains the ratio to read, for a different reason than the denominator: it is the field
that says **which regime bound in a window**. With
`Minimum brains per frame` at 4 and a Streets roster of 14–29 agents, slicing binds at the top of that range
and the floor binds at the bottom, so a single arm at `brainUpdatePeriod = 0.1` contains both.

**`bots.awake` conflates two populations, and one of them our mechanism cannot touch.** A bot is awake either
because a human is near it *or* because its role is exempt from stand-by entirely — `CAN_STAND_BY: false` in
BSG's own per-role settings, which `RoleAllowsStandBy` reads at runtime. *Wrong conclusion:* that a high
`awake` count means the stand-by system is underperforming.

**Recovery: none from the line as it stands.** No field separates them, which is why this is filed here rather
than as a caveat. Requested from Gamma as a `bots.exempt` count.

> **AND THE PROJECT'S OWN STATEMENT OF WHICH ROLES THESE ARE WAS WRONG, IN THE DIRECTION THAT MATTERS MOST.**
> Counted out of `SPT_Data/database/bots/types/*.json` on 2026-07-28, twice and independently: **30 roles
> `false`, 27 `true`, 0 missing the key.** The `false` set is `pmcusec`, `pmcbear`, `pmcbot`, `exusec`, every
> boss and follower, all four `sectant*`, `arenafighterevent`, `gifter`, `infectedpmc`, `spiritspring`,
> `spiritwinter`.
>
> Against that, **four** places in this project said it was two: `Plugin.cs`'s stand-by description
> *"bosses that must never sleep (Gluhar, Zryachiy)"*, the same file's `Force for all roles` text
> *"typically bosses and their guards"*, `BotStandByUpdatePatch`'s copy of the first, and
> `BotStandByInitPointsPatch`'s *"lets bosses and their guards sleep"*. FINDINGS repeated it as
> *"the two roles that cannot stand by at all"*.
>
> **So every PMC in every raid is exempt from the central mechanism this mod is built on.** Other maps floor at
> 0–2 awake only because their PMCs are dead by mid-raid; Lighthouse floors at **14 of 29** because the `exusec`
> Rogue garrison at Water Treatment does not die. Measured: median excess over `snipersAwake` is **+13 on
> Lighthouse against +0 on every other map in the same sweep.**
>
> The two-role claim was never checked against the data files — it is the shape of thing that reads as settled
> because it is specific, and it survived because nothing in the pipeline had to look at it. Same family as the
> stale scoreboard and the stale line citation: **a confident sentence nobody re-derives.**

### Recoverable, but only from outside the ndjson

**`cfg.brainPeriod` is the value *requested*, not the value in force.** It reads `BrainUpdatePeriod.Value`, so
it reports what the config asks for whether or not slicing actually engages. `ModCompat.SuppressSlicing` is
`DeferToOtherAiMods && (Orbit || BigBrain)`, and `DrakiaXYZ-BigBrain.dll` ships as a SAIN dependency — so on
any install with SAIN and the **default** `Defer to other AI mods = true`, `AICoreControllerUpdatePatch` takes
the vanilla path while the log still reads `brainPeriod: 0.1`.

*Wrong conclusion:* that an arm labelled 0.1 was sliced. **The natural reading of a null is then "slicing does
not help", drawn from an arm that never ran** — the most expensive shape of wrong answer available, because it
retires a fix on evidence that never tested it.

**Recovery: `Player.log`.** With `DeferToOtherAiMods` false and BigBrain present, `ModCompat.LogSummary()`
takes the `!defer` branch unconditionally and writes positive confirmation there. Nothing in the ndjson
carries it: `SuppressSlicing` is not emitted, and `AICoreControllerUpdatePatch.LastBrainsTicked` — whose own
doc comment says it *"confirms slicing is doing what it claims"* — reaches no line. Requested from Gamma as
two fields; until they land, **an ndjson alone cannot establish that slicing was active**, and any
brain-slicing arm needs its `Player.log` kept alongside.

Three separate facts had to agree to see this: the plugin list, the guard's boolean, and *which* value the
telemetry field reports. Beta found it before the raid rather than after, which is the only reason it is a
note here instead of a withdrawn finding. Note the family — it is the same one as `animCulled` and
`state: loading`-at-menu: **a field that reports an intent rather than a state reads as healthy in exactly the
case it needs to warn about.**

### Fatal

**`initHeapDeltaMb` is unusable.** It read 6,900.8 MB inside a 116.6 MB container on one raid and a consistent
126.4 MB on another. Same code path; no filter separates the good readings from the bad. Do not use it.

**Player position is in no log.** Every cross-window comparison in this corpus therefore carries an unmeasured
location confound — and FINDINGS' first methodology rule is that **location dominates everything on Streets**.
This cannot be recovered by any filter, and it is the single most-cited caveat in the project.

---

## What this corpus can answer

Stated positively, because a document that is all caveats gets read as "unusable" and this corpus is not.

- **Within-run phase attribution.** The eight top-level phases tile the frame and `sum(phases)` reconciles
  against `frame` to 0.087 ms mean when clean. Era-C logs with all eight expanded also resolve *inside* a
  phase.
- **Where a spike's time went, when it went outside the player loop.** `endToStart` accounts for the
  165–402 ms family to **±0.72 ms on 12 of 12** — but era C onward only, and only `20260728-*` in practice.
- **GC coincidence in the forward direction.** `TimeUpdate`-dominant ⇒ a collection is **38 of 38 across four
  runs**, and it touches neither `unaccounted` nor `frame`, so none of the clock defects reach it.
- **Relative A/B within one log at fixed threshold and fixed position** — which is what every confirmed fix
  in FINDINGS rests on.
- **Bot population.** `awake + asleep` agrees with `agents.live` on **136 of 156** in-raid windows, the
  disagreements being the teardown artifact and four registration lags. Filter `bots.total > 0`.
- **`animCulled`, in raid 1 of any log.** Inflation is zero in every single-raid log and confined to raids 2+.

## What this corpus cannot answer

- **Anything requiring the frame *after* a spike.** Structural, not a sampling problem — see the limit note
  above. Demonstrated: a check for a negative-residual line following each of the thirteen stage-4
  residual+collection frames returned **0 of 13, because none of the thirteen has a consecutive line at all** —
  the nearest is 2.9 to 31 seconds away. Reading that as a negative result is the error; the discriminating
  line was below threshold and never written.
- **Whether any cross-window comparison is location-confounded.** Position is in no log before `20260728-*`.
  This is the largest single limitation and it invalidates nothing outright — it means every cross-window
  number carries an unmeasured term rather than a wrong one.
- **Rate comparisons across a threshold change.** `spikeEventMs` is 100 for every log except `20260728-*` at
  30. Spike *counts* and *rates* do not join across that boundary; normalise to `period ≥ 100` first. This
  caught two agents in one day.
- **Whether any build changed the line-pairing slip rate.** Not a defect in the data — a power limit. The
  two era-C 30 ms logs carry **37** qualifying lines pooled, and at that n a **2.1× regression** is the
  first thing separable from the control while only *total elimination* separates below it. The rate is
  reportable; a *comparison* of rates across builds is not, and no filter fixes that.
- **Absolute millisecond figures across maps.** Standing rule, and it now extends to attribution *ratios*:
  Streets attributes 10 of 11 collection frames to a phase, Customs 13 of 25.
- **Live set versus heap size.** `GC.GetTotalMemory(false)` reports heap-including-free-blocks, so every
  heap-scaling regression in the corpus used the wrong column. Nothing here measures the live set.
- **Per-collection pause cost inside a non-yielding span.** Three estimates have been withdrawn (895, 360,
  65 ms). The corpus does not contain the measurement.

---

## The one rule behind most of the entries above

**A check that reports a pass must also report what it tested**, because otherwise *"nothing failed"* and
*"nothing was examined"* are the same output — and the second is indistinguishable from the strongest possible
confirmation.

Four instances on 2026-07-28 alone, and the shape is identical every time:

| the check | what it said | what was true |
|---|---|---|
| `negResidualFrames == 0` | latch holds | also what a run produces if the test never ran — hence `clockResidualFrames` as the denominator and the `3 ÷ N` bound |
| `probe-symbols.py` on `brainsTicked` | `ok` | a *member* was named `_brainsTickedSum`; the key is emitted nowhere |
| `grep -c … \|\| echo 0` | no candidates | `grep -c` exits 1 on zero, so the fallback fired on the normal case; three existed |
| `slicing matches arm` on a pre-protocol log | `OK` | zero windows carried an arm label, so every comparison was skipped |

**Two of the four were inside verification tools**, which is where it does the most damage: a tool built to
catch someone else's error reports a pass, and the pass is trusted precisely because the tool exists.

The countermeasure is mechanical rather than a matter of care. **Print the population beside the verdict, and
make an empty population a failure rather than a pass** — `UNTESTED`, not `OK`. Then the output cannot claim
more than it looked at. `analysis/read-slicing-raid.py` does this on every check and refuses to print its
primary comparison until each one names a non-empty population it examined; the `3 ÷ N` bound in
`check-boundary-latch.py` is the same rule expressed as a number.

Gamma stated the general form after finding the fourth instance in their own gate. It generalises past this
project: it is the reason a green test suite that runs no tests is worse than a red one.

## The other rule: ask whether the loss is correlated with the signal

**When an observation goes missing, ask whether it goes missing more often when it would have been
interesting.** Missing-at-random costs precision. Missing-when-interesting produces a confident wrong answer,
and it is the same output as a clean measurement.

Four instances on 2026-07-28, and none of them looked like this from the front:

| the instrument | what went missing | and it correlated with |
|---|---|---|
| `LastBrainsTicked` sampled once at flush | the per-frame value | **a slow frame ticks more brains**, so the sample tracked the quantity the A/B was measuring |
| `framePct.p999` | a lone catastrophic frame | at ~3,500 frames it sits *above* p999, so the metric was blindest to the largest events |
| the mark lookback | frames before a window boundary | a boundary is where a flush happens, and a flush is where stalls cluster |
| `KeyboardShortcut.IsDown()` for the mark key | presses made while any other key was held | **movement and combat**, which is where the hitches we are hunting live |

The last one is the clearest. `IsDown()` requires that *no* other key is down — BepInEx's type summary says so
outright, while the summary on `IsDown` itself mentions only the configured modifiers, so the permissive
documentation is the one attached to the method you look up. In Tarkov, moving holds `W`. So marks registered
only while the runner stood still: **five presses, five marks, and every one of them made stationary.** A
perception threshold estimated from that population is a threshold *while stationary*, and nothing suggests it
transfers to the case the release is gated on.

**So the pre-fix mark set is a pilot that proved the instrument, not data.** Four observations from one
condition, three of them loading screens. Treated as evidence it would have been worse than nothing, because
the missing half was the informative half — and the bracket built on it was withdrawn twice before that was
clear.

**How to apply it:** the question is cheap and it works before the data exists. Ask it of every new field at
design time — *what would make this reading absent, and is that thing correlated with what I am measuring?*
`tickedSum`/`liveSum` over the window instead of a sample at flush, and `frame.max` instead of a percentile,
both came from asking it. It also explains why `boundaryMissedFrames` and `clockResidualFrames` are emitted at
all: an instrument that can go dark must say how often it did.

## Verifying a field is in a build: probe the key, not the name

`analysis/probe-symbols.py` replaced an ASCII `grep` that could not see UTF-16 string literals. **It then had a
hole the same shape, one level up, and it was live in deploy declarations.** Presence in *either* heap answers
*"is this string in the binary"*, which is not what a declaration asks — it asks *"will this key appear on a
line"*. A member named `_brainsTickedSum` puts `brainsTicked` in `#Strings`, so the tool answered **ok** for a
key emitted nowhere. A false **pass**, where the `grep` it replaced gave false failures.

**An emitted JSON key must appear in `#US/utf16`.** That is where the literal written to the line lives; a
`#Strings/utf8`-only match is a member name and proves nothing about the output.

```
python analysis/probe-symbols.py --key <dll> slicing tickedSum liveSum   # keys: literal required
python analysis/probe-symbols.py       <dll> ResetForRaid                # members: #Strings is correct
```

`--key` refuses a `#Strings`-only match and prints `NOT A KEY` rather than `MISSING`, because those are
different facts and collapsing them is how the hole opened. Found by Gamma, 2026-07-28 — the second failure
inside this verification tool, and the argument for fixing the tool rather than noting the hazard: a rule about
how to read output depends on someone remembering to read it that way.

### And `--key` did not close the class, so here is the third level

`--key defer` against the deployed binary returns **ok, `#US/utf16`** — a genuine emitted literal, exactly what
the flag demands. It is the **drain budget's** `defer` counter. Different field, same name.

So **`--key` proves a literal exists; it does not prove which field owns it.** That is not fixable without
parsing the metadata tables properly, so it is a usage rule rather than a tool change: **a `--key` pass on a
name that could plausibly belong to another field is not evidence about your field.**

Three levels of one failure, and the progression is the lesson:

| instrument | matched | and was wrong because |
|---|---|---|
| `grep` | the UTF-8 heap | the literal lives in UTF-16 |
| `probe-symbols` | either heap | a *member* name is not an emitted key |
| `probe-symbols --key` | a UTF-16 literal | a *different field* has the same name |

**An instrument that matches on a name can only ever tell you that a name matched.** The fix is never a better
matcher — it is asking what else could have produced this match. Applied forward rather than only recorded:
new fields get names that cannot collide, which is why the AI-mod defer setting will ship as `deferToAiMods`
and not as `defer`.

## Two provenance fields are absent, and the obvious way to add them is dangerous

`Defer to other AI mods` appears **nowhere in any log** — not in the header, not in `cfg`. It gates
`ModCompat.SuppressSlicing` (`defer && (Orbit || BigBrain)`), and BigBrain ships as a SAIN dependency, so **two
runs with byte-identical `cfg` blocks can have opposite slicing behaviour with no field distinguishing them.**
Worse than `cfg.brainPeriod` being a request rather than a state: there is no field to misread.

**Do not close it by reading `ModCompat` from the header.** `EnsureDetected()` sets `_detected = true` *before*
its `Has(...)` probes, so the first caller latches the result permanently — and `WriteHeader()` runs inside
`Telemetry.Awake()`, when `Chainloader.PluginInfos` need not yet contain plugins that load after Framesaver.
BigBrain would read absent, the latch would stick, and **`SuppressSlicing` would return false for the whole
session: the compatibility guard silently off, from a change that only meant to log something.** Gamma caught
this before building it; verified here against the `_detected = true` assignment preceding the `Has(...)` probes
in `EnsureDetected`, and the `WriteHeader()` call inside `Telemetry.Awake()`.

> **Cite the predicate, not the line.** Gamma shifted the spike gate sixteen lines by adding fields to the same
> file and invalidated their own citation of it — `Telemetry.cs:966` is now 981, and nothing warned anyone. **A
> line number is invalidated by any edit above it, including your own.** These files point into a codebase three
> agents edit in parallel, so where a citation is load-bearing — and the spike gate is, since the
> `period`-not-`frame` rule rests on it — quote the text: `if (periodMs >= Plugin.SpikeEventMs.Value && …)`
> survives the edits that the number does not. Same reasoning as dating a log by its `cfg` key count rather than
> its filename: prefer the identifier that travels with the thing.

The safe shape is split by *when the value is knowable*: **`deferToAiMods` in the header**, a pure config read
that triggers no detection, and **`suppressSlicing` in the per-window `agents` block**, by which point the
patch has caused detection naturally. Recorded here rather than only in a queue because the gap is visible in
every existing log and the tempting repair is the harmful one.

## Re-deriving the numbers

`analysis/delta-rederive.py` is a dependency-free second implementation of the derivations behind the headline
findings, written independently of the analysis it checks — the concrete answer to *"how do you check a number
you cannot re-derive by hand"*. Every figure it prints has two implementations behind it.

**What it assumes, stated so a wrong reading is loud rather than plausible.** It hard-codes the **60 s
artifact cut** (`ARTIFACT_MS`) and the **0.5 ms phase-emit floor** (`PHASE_EMIT_FLOOR`), both era-C facts.

~~It takes **no threshold parameter at all** — it pools every log it finds, which is correct for the era-A/B
corpus at a uniform 100 ms and wrong the moment a 30 ms log is in the directory.~~ **Fixed 2026-07-28.** It now
reads `spikeEventMs` from **each log's own header** and normalises pooled statistics to `period ≥ 100 ms`,
printing the drop count and the thresholds present. Deliberately *not* a parameter: a caller who must remember
to state the era is a caller who will forget, which is the same reasoning as renaming a config key when its
meaning inverts rather than documenting the hazard.

**Two things it will not do, both found by running it rather than reading it.** It **snapshots the corpus once
per process** — a log being written by a live game grows between calls, and two sections of one report read
different corpora and disagreed by two lines, small enough to look like rounding and large enough to be wrong.
And it does **not** re-read a `live` log, so its numbers age exactly as the provenance table's do.

`analysis/ticker-manifest.json` lists the 759 `Assembly-CSharp` types that receive a per-frame Unity message,
transitively closed over base types — 585 declaring one directly and 174 inheriting without overriding.

`analysis/corpus-table.py` regenerates the provenance table above. Dependency-free; prints markdown to stdout.
It applies **both** normalisations together because either alone is misleading, snapshots the corpus once so a
live log cannot make it disagree with itself, and prints a warning naming any log that may still be growing.
**Re-run it after any session ends** — a `live` row's counts are partial by definition.

> **It forces UTF-8 on stdout, and it did not always.** Reading was UTF-8 from the start; writing was left to
> the platform, and a default Windows console is cp1252. So the documented workflow — run it, paste the
> output over the table body — replaced every em-dash in the `empty` and `no in-raid` rows with a mojibake
> byte. **Following the instructions corrupted the file the instructions were for**, and only in the rows
> with no data to draw the eye.

`analysis/power-check.py` answers what a rate comparison in this corpus could have detected, given the number
of qualifying lines a log actually contains. It exists because "no build-related trend" was asserted here from
data that cannot separate a 2× change, and a power figure is the difference between *no effect* and
*no measurement*.
