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
| `20260728-100048-postlate-gc` | **live** | C | **30** | **all 8** | 1 | TarkovStreets | 0/4 | 1/6 |

**`state` matters and is a snapshot.** `empty` means zero sample and zero spike lines — an aborted launch,
nothing to find. `no in-raid` means the session never reached `state: raid`. **`live` means the file was still
being written when this table was generated**; a live log's counts are partial and its final window has not
closed. Regenerate the table rather than trusting a `live` row.

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
The high rates are all small-`n` logs; among the five with `n ≥ 30` the range is **0.0%–14.3%**, and the
era-C 30 ms logs sit inside it at 8.3%. **There is no build-related trend**, and the unfiltered rate
suggests one only because it is 1.9× inflated at the lower threshold.

> **The limit of that recovery, and it is the reason the defect matters at all.** Self-identification finds
> the **source** line and never the **destination**. The mechanism moves time from line N to line N+1: N is
> large and carries the marker, **N+1 is ordinary and carries nothing**. So filtering on `frame > period`
> leaves a reader holding a set of displaced-*from* lines and believing the corpus is clean, when the lines
> the time landed *on* are indistinguishable from ordinary frames.
>
> Worse, **no magnitude threshold can select the destination**, because the defect makes it ordinary by
> construction. That is why [nothing needing the frame after a spike is answerable](#what-this-corpus-cannot-answer)
> anywhere in this corpus, and why the fix is a sampling-boundary change rather than a filter.

**`gpu.vram` reads a string on the first window of each GPU-carrying log.** Initialisation, not failure.
*Wrong conclusion:* that the `overBudget` regression guard is absent. **Recovery: skip window 0** — the field
is live in 14 of 15 windows in the most recent log.

**`best p50` in the stage-1 table is a best-*window* figure.** *Wrong conclusion:* that it is a baseline.
Quoting it as one produced a phantom 40% disagreement with the user's own observation; the Streets median is
16.51 ms against that column's 11.51. **Recovery: read the median columns in
[TESTING.md](../TESTING.md).**

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
- **Absolute millisecond figures across maps.** Standing rule, and it now extends to attribution *ratios*:
  Streets attributes 10 of 11 collection frames to a phase, Customs 13 of 25.
- **Live set versus heap size.** `GC.GetTotalMemory(false)` reports heap-including-free-blocks, so every
  heap-scaling regression in the corpus used the wrong column. Nothing here measures the live set.
- **Per-collection pause cost inside a non-yielding span.** Three estimates have been withdrawn (895, 360,
  65 ms). The corpus does not contain the measurement.

---

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
