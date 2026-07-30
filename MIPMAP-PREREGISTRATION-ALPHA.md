# Mipmap differential — Framesaver's half, written before reading DRIP's

**Author:** Alpha (Framesaver). **Date:** 2026-07-30, before opening
`F:/SPT/Mods/DRIP/docs/MIPMAP-PREREGISTRATION.md`, which I have not read.

**Why this exists.** DRIP's rebuild branch and Sophia's content branch are *different owners*.
GPUBusy-alone means Echo regenerates mip chains, which is scheduled anyway. Both moving means
material variety, which is a content decision Sophia would have to make and would hate. A
prediction whose outcomes assign work to different people is exactly the kind that gets talked into
the convenient branch, so the mapping is fixed while neither of us knows the answer.

Echo proposed independent drafts rather than one of us drafting and the other attacking, on the
grounds that convergence-in-conversation produces one prediction with two signatures instead of two
predictions. They are right, and it means **provenance has to be marked, because some of theirs has
already reached me in conversation.** Marked below as `[TRANSFERRED]`. Everything unmarked is
derived from Framesaver's own corpus.

---

## What I am predicting from

- **We are CPU-bound and it is not close.** 368,697 PresentMon frames: CPUBusy 14.809 ms of a
  14.875 ms frame, GPUBusy 6.646, GPU 44.7% busy, **2.24x GPU headroom**. Every gate this project
  has is a CPU gate.
- **The Lighthouse frame decomposes, and three leaves own 73% of it** — 54 windows, median frame
  15.747 ms:

      DirectorUpdateAnimationBegin   3.949 ms   25.1%   Unity evaluating animators
      FinishFrameRendering           3.837 ms   24.4%   render submission
      ScriptRunBehaviourUpdate       3.786 ms   24.0%   every MonoBehaviour.Update

- **`DirectorUpdateAnimationBegin` never once leads a spike, in any stratum** (Delta). So the
  animator is exonerated for the tail independently of anything DRIP does.
- **Between-leg noise floor 0.68–0.74 ms** on a rendering component, n=2 maps with repeat legs.
- `[TRANSFERRED]` DRIP is retexture-only: renderer and skinned-mesh count per bot unchanged, same
  prefab shape. **286 of 333 diffuse maps ship with no mip chain** against vanilla's 12 levels.

## The prediction

**Primary: GPUBusy rises, CPUBusy does not move beyond the noise floor.**

Reasoning: a missing mip chain costs sampling bandwidth and texture-cache pressure at distance.
That is GPU-side work. With 2.24x GPU headroom it should be absorbable, so I expect it visible in
GPUBusy and **invisible in the frame**.

**Falsifiable floor, and it is the assumption-free part:** if the mechanism is sampling, then
CPUBusy must not move by more than 0.74 ms — the measured between-leg floor. A CPUBusy rise past
that is not a small effect of my mechanism; it is a different mechanism.

## The four cells

`[TRANSFERRED]` Echo told me their draft commits to a CPUBusy x GPUBusy table and names the
neither-moves case *unresolved, insufficient to attribute*. So the table's existence is not
independent. What follows is my reading of each cell.

| CPUBusy | GPUBusy | reading | owner |
|---|---|---|---|
| flat | **up** | sampling bandwidth / cache pressure. **My primary.** | Echo's rebuild — already scheduled |
| **up** | up | draw-call setup from unique material count, *plus* sampling | **Sophia's content decision** |
| **up** | flat | material variety alone; the mip chains are not the cost | Sophia's, and Echo's rebuild does not help |
| flat | flat | **unresolved, insufficient to attribute** — not a null | nobody; the raid failed to dose |

**The neither-moves cell is not evidence of absence** and I want that fixed now rather than
argued later. Lighthouse spawns 5–6 Rogues of a declared 18–22, and the clothed population is
chance-gated, so a raid can simply fail to put enough distinct materials on screen. The dose is
checkable: **unique clothed bots observed, from our own `botSpawn` ledger.** Below some count the
run is undosed rather than null, and I would rather set that threshold from Echo's pin than guess
it here.

## What makes the CPU branch specific, and it is mine to offer

If material variety costs CPU, the mechanism is SetPass calls and batch-break bookkeeping — render-phase
main-thread work. **So it must land in `FinishFrameRendering` and not in
`DirectorUpdateAnimationBegin` or `ScriptRunBehaviourUpdate`.**

**Diffuse CPU movement across all three leaves means something other than material variety**, and I
should not claim variety on it. That is sharper than "CPUBusy moves" and it is the discrimination
the leaf tree buys.

*(Echo has told me they are adding this same refinement to their half, marked as transferred from
this decomposition. So on this point we will not have converged independently — we will have
agreed, which is worth less, and the record should say so.)*

## What would make me abandon my own preferred branch

My preferred outcome is GPUBusy-alone, because it costs Sophia nothing and Echo's rebuild is
scheduled regardless. So the threshold is fixed before the data: **CPUBusy rising more than 0.74 ms
means I do not get to call it sampling.** No re-deriving the floor afterwards, and no arguing that
this leg's floor is different.

And I do not get to argue the bots were unrepresentative unless `exempt` differs materially between
arms — a number we log per window, so it is checkable rather than assertable.

## Scope limits

`[TRANSFERRED]` Echo's caveat, which I would not have had: **Lighthouse's high exempt fraction makes
it the worst case, not the typical one.** A result there is an upper bound and must be reported as
one. Nine of ten awake bots on Lighthouse are awake by role, and those never sleep and never get
animator-culled, so their materials stay resident all raid — which is why the map is right for the
test and wrong for extrapolation.

**Raid ages must be matched or recorded.** Raid 1 died at 11 minutes and raid 1.5 ran 36, and every
raid-wide comparison between them turned out to be a raid-age comparison — it inverted a p75 result
from +1.88 ms to −0.55. Pinned and unpinned arms need matched length, or enough recorded to cut on
age afterwards. Echo has already made this a required field on their side.

**And per-bot cost is a function of awake-age**, provisionally: the corpus 0.37 ms/bot and raid 1.5's
0.22–0.25 were both correct, measured on populations of different ages. So any per-bot figure quoted
from a DRIP leg carries the age distribution of that leg with it.

## What this raid cannot answer

It cannot separate *material count* from *texture resolution* — DRIP changes both at once. Only the
pinned arm collapses variety while holding resolution, so **the pinned/unpinned pair is what makes
the differential a differential**, and a DRIP-present-versus-absent comparison alone would confound
them.

It also cannot speak to bots we never render. The whole mechanism is visibility-gated, so a leg
spent away from the clothed population is undosed by construction — same failure as the
neither-moves cell above, and the same fix: count the dose.

— Alpha
