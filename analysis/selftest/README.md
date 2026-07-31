# Reader self-tests

Synthetic-input harnesses for the pre-registered readers in `analysis/`. Run
them from this directory:

    python um-crashtest.py     # read-updatemanual.py, 8 cases
    python bw-crashtest.py     # read-botwindow.py, 7 cases

They exist because **every one of them found a defect in code written minutes
earlier**, and none of those defects would have produced an error. A list, so
the next person knows what these are for rather than assuming they are
regression tests:

- a promise printed in section 1 that no branch implemented
- a per-window median computed off raw means while the pooled figure above it
  used corrected ones — two numbers on adjacent lines, 50% apart, both labelled
  contrast
- a mixed-era stratum that subtracted corpses on some windows and not others
- an all-corpse stratum dividing by zero, newly reachable once the subtraction
  existed
- twelve exactly-flat slopes making a sign test's signed count zero, so the
  strongest possible null fell out of the bottom of the section in silence
- a warning that fired and then printed the contrast anyway
- a span-split rule blind to a re-wake early in a window

**What they are not.** They exercise code paths on data built for convenience.
A synthetic shares the assumption under test, so nothing here validates a
conclusion — only that a branch runs and says what it claims to say. The one
exception is stated in each file: `um-crashtest` builds a case whose true
per-live-call cost is 0.02 ms by construction, so the corpse subtraction can be
checked against a known answer. That tests arithmetic, not a claim about raids.

**Write the boring cases.** The slope-0 case felt too dull to bother with and is
the one that found the silent-null defect. A case that cannot fail for the
reason it was written is worse than no case, because it reports a pass — the
first version of the `spanS` hole test picked ages that happened to decrease, so
both rules agreed and it tested nothing.

Fixtures are written into this directory and gitignored.
