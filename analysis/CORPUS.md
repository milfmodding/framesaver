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

`animCulled infl` counts in-raid windows where `animCulled` exceeds `asleep`. The last two columns are
**normalised to `period > 100 ms`** so that logs at different spike thresholds are comparable — see the
threshold defect below, which is why the raw rates must not be compared directly.

| log | state | era | spike ms | expanded | raids | maps | animCulled infl | `frame>period` | `unacc < -1ms` |
|---|---|---|---|---|---|---|---|---|---|
| `20260726-170412-baseline` | complete | A | 100 | PreLateUpdate | 5 | Interchange, TarkovStreets, bigmap, factory4_day | 20/30 | 2/34 | 1/34 |
| `20260726-183701-ai-stack` | complete | A | 100 | PreLateUpdate | 2 | TarkovStreets, factory4_day | 0/17 | 6/50 | 4/50 |
| `20260726-191139-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/6 | 1/12 | 1/12 |
| `20260726-205307-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/9 | **11/35** | 5/35 |
| `20260726-212828-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/3 | 2/7 | 2/7 |
| `20260726-231556-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/6 | 0/3 | 0/3 |
| `20260726-234729-ai-stack` | no in-raid | A | 100 | PreLateUpdate | 1 | — | 0/0 | — | — |
| `20260726-235721-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/7 | 3/13 | 2/13 |
| `20260727-002111-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/8 | 2/7 | 1/7 |
| `20260727-004848-ai-stack` | **empty** | — | 100 | — | 0 | — | — | — | — |
| `20260727-005816-ai-stack` | complete | A | 100 | PreLateUpdate | 1 | TarkovStreets | 0/2 | 0/5 | 0/5 |
| `20260727-010740-ai-stack` | complete | B | 100 | PreLateUpdate | 1 | TarkovStreets | 0/2 | 3/6 | 2/6 |
| `20260727-201220-ai-stack` | complete | B | 100 | PreLateUpdate | 2 | TarkovStreets | 10/22 | 5/33 | 3/33 |
| `20260727-232106-ai-stack` | **empty** | — | 100 | — | 0 | — | — | — | — |
| `20260727-232217-control` | complete | C | 100 | PreLateUpdate | 2 | TarkovStreets, bigmap | 12/28 | 12/76 | 8/76 |
| `20260728-092354-postlate-gc` | complete | C | **30** | **all 8** | 1 | TarkovStreets | 0/11 | 7/24 | 2/24 |
| `20260728-100048-postlate-gc` | **live** | C | **30** | **all 8** | 1 | TarkovStreets | 0/2 | 1/4 | 1/4 |

**`state` matters and is a snapshot.** `empty` means zero sample and zero spike lines — an aborted launch,
nothing to find. `no in-raid` means the session never reached `state: raid`. **`live` means the file was still
being written when this table was generated**; a live log's counts are partial and its final window has not
closed. Regenerate the table rather than trusting a `live` row.

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

**Rate varies 0%–31% across logs at identical threshold**, so this is a property of the *run*, not of the
instrument — it tracks how often the `Update`-phase stall occurs, which moves with mod stack and map. The
worst log in the corpus is `20260726-205307-ai-stack` at 11/35, era A, threshold 100.

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

## Re-deriving the numbers

`analysis/delta-rederive.py` is a dependency-free second implementation of the derivations behind the headline
findings, written independently of the analysis it checks. It encodes **era-C, 100 ms-threshold** assumptions;
pass the threshold explicitly before running it against a 30 ms log.

`analysis/ticker-manifest.json` lists the 759 `Assembly-CSharp` types that receive a per-frame Unity message,
transitively closed over base types — 585 declaring one directly and 174 inheriting without overriding.
