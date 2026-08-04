# Analysis manifest — routing, and which files lie to you

Written 2026-08-01 for the team reboot. **78 scripts, and the hazard is not that any of them is
wrong — it is that several answer questions adjacent to the one you are asking, with docstrings
that read authoritatively.** A rebooted reader with a question will pick by filename and get a
confident answer to a different question.

Organised **by question**, because that is the failure mode. Filenames are the index at the
bottom of your own `ls`, not here.

**Status vocabulary.** `CURRENT` — I would quote its output today. `SUPERSEDED` — kept for the
reasoning, never the verdict. `NOT MINE` — Delta's or Gamma's; I can describe what it does and I
have no standing to certify it, so ask its owner. `UNREVIEWED` — nobody has said either way, which
is a third value and not a synonym for fine.

---

## The question you are most likely to ask

**"What does the mod actually buy, and where does the gate stand?"**

- `alpha-feasibility.py` — **CURRENT.** Mod-off baseline against the gate, matched mod-on
  comparison, and the leverage ratio. The one to run first.
- `scoreboard.py` — **CURRENT.** The release scoreboard in the statistic the success criteria are
  actually written in. Run it before quoting anything to Sophia.
- `alpha-fps-percentiles.py` — **CURRENT.** Percentiles from PresentMon frames, split by the three
  treatment arms. Prints `SINGLE LEG` / `DOMINATED` per map, which is the single most useful line
  in the whole directory — see *what transferred* below.
- `alpha-ceiling-vs-gate.py` — **SUPERSEDED, AND ITS HEADLINE IS WRONG.** Concluded Streets was
  unreachable by arithmetic. It prices the mechanism at the phases it *occupies*; the effect
  propagates into phases it never appears in, by a measured median 2.8×. Kept because the error is
  instructive and because the corpus already held its refutation. **Do not quote its output.**
- `delta-gate-status.py` — **NOT MINE.** Marathon legs against the three gates as Delta framed them.
- `alpha-map-gate-and-gaps.py` — **UNREVIEWED**, and note it hard-codes p75/p99, which is right for
  the current gate and was written before that was settled. Check its percentile before trusting it.

**Three files whose names promise headroom and answer something else.** This is the trap:

- `alpha-headroom.py` — *population* headroom. How many more bots a map can take, bracketed across
  three slopes. Not fps headroom.
- `delta-modoff-headroom.py` — **NOT MINE**, and it is a *vanilla stand-by census per map* plus an
  argument about what "headroom" means under two mechanisms. It is not a headroom number.
- `delta-ai-ceiling.py` — **NOT MINE.** Bounds what *brain slicing* can buy. Slicing is not the
  mod's shipping mechanism, so this ceiling is not the mod's ceiling.

## Per-bot cost, and why there is no single number

- `alpha-animator-aggregate.py` — **CURRENT.** Within-arm fit on frame-weighted regressors.
- `alpha-animator-slope.py` — **SUPERSEDED.** Retains its apparently-failed prediction unedited,
  deliberately.
- `alpha-headroom.py`, `delta-bot-cost-bracket.py`, `delta-bot-marginal-cost.py` — the bracket.
  **The disagreement between these is the finding, not a problem to resolve.** When two estimators
  disagree and you can sign each one's bias, report the interval and say which end is which.

**Do not synthesise these into one coefficient.** Intercepts run negative on four of six maps,
which is proof the linear form is wrong outside the fitted range.

## Reading a specific raid or field

`read-*.py` are all single-purpose readers and all **CURRENT**: `read-marathon.py` (per-map
scoreboard with its own confound checked), `read-updatemanual.py`, `read-animcull.py` (a **gate**,
not an estimator — it answers *is this run readable at all*), `read-marks.py` (perception marks →
hitch-threshold bound), `read-botarm.py`, `read-botwindow.py`, `read-aitotal-aba.py`,
`read-slicing-raid.py`.

`steady.py` states the steady-state window definition **once** so readers cannot drift. Import it
rather than re-deriving; a re-derived warm-up rule is how the 198-vs-10 disagreement happened.

## Self-tests and sabotage controls — run these when you doubt an instrument

`alpha-check-fields-sabotage.py`, `alpha-ledger-reconcile-selftest.py`, `probe-symbols.py`,
`percentile-discriminability.py`, `power-check.py`, `power-binomial.py`,
`alpha-pool-exchangeability.py`, `alpha-warmup-rule-equivalence.py`.

**`probe-symbols.py` earned its place the hard way.** A binary search for four telemetry strings
returned all four absent — and so did a fabricated control, which is what a *working* search
returns. Wrong text encoding. **Never run a presence check without something that must be present.**

## Provenance — read this before quoting any number from any log

`build-provenance.py`, `beta-build-fields.py`, `corpus-table.py`, and `CORPUS.md`.

**22 of 25 logs cannot be tied to a binary, and this is retroactively unfixable.** The strongest
mod-on figures we hold come from a build we cannot identify. `framePct.p75` exists in exactly one
of 25 logs, which is what dates the gate change. Provenance questions are answerable *only* from
these files; do not infer a build from a date.

---

## What transferred, and how — the one generalisable lesson here

The most useful piece of tacit knowledge I held was **where the corpus is thin** — that Sandbox is
n=8, that Lighthouse is 75% one leg, that six maps are single-leg for p75. A rebooted reader
computes correctly and *trusts* wrongly, and no prose warning survives contact with a hurry.

That knowledge did transfer, and not as a document: `alpha-fps-percentiles.py` prints
`<- SINGLE LEG` and `<- DOMINATED` beside every map, every run. **The transferable form of a reflex
is a print statement, not a paragraph.** If you find yourself writing a caveat into a doc, check
first whether the instrument can print it instead.

## Known gaps, stated so they are absences by decision rather than by accident

- `alpha-playerlate-recheck.py` has **no docstring**. Nobody can route to it. Unowned.
- Nothing in this directory records which scripts have ever been *re-run since the telemetry
  changed*. A script that was correct against a 30 s window may be silently wrong at 5 s.
- `NOT MINE` entries are uncertified by design. That is honest, and it is also a standing hole:
  four of Delta's files bear on the release argument and only their owner can status them.
