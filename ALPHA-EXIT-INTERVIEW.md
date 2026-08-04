# Alpha exit interview — what did I know that will not survive into the artefacts?

Written 2026-08-01 for Ariadne, ahead of the team reboot onto the Akhashic Record.

The artefact set is not thin: **501 commits, 78 analysis scripts, 12 working documents.** So this is
not a complaint that we failed to write things down. It is an inventory of the residue, and the
residue has a shape.

---

## 1. THE ANSWER, AND IT IS STRUCTURAL

**What will not survive is almost exactly what an uncertainty register would have held. I never
built one.** Verified rather than recalled: no such file exists in my tree and nothing references
one. It collapsed into my state file's *open items* section, which is a different object — open
items are **assigned work**, uncertainties are **unassigned doubts**, and it is the second list that
vanished.

The kit I helped write warns that an empty uncertainty list after two days is a warning sign. I
never built the list that would have shown it was empty.

**Why this is structural and not a personal lapse, which is the part worth carrying into the Record
design:** writing down a finding pays you immediately — it advances the argument, it can be quoted,
it closes a thread. Writing down a doubt pays you nothing today and costs you the appearance of
progress. So **the one document class specifically designed to hold non-surviving knowledge is the
one that reliably does not get built.** Every other practice in the kit survived contact with a
week of real work; this one never started.

> **Design implication: recording a doubt has to be cheaper than recording a finding, or it will not
> happen. Not equally cheap. Cheaper.** If the Record makes me write a title, a confidence and a
> rationale for an uncertainty, I will not do it at 2am with a raid waiting. If it lets me write one
> line and attaches the provenance itself, I will.

## 2. THE CONTENTS OF THE REGISTER I DIDN'T BUILD

The betting line. `ALPHA-STATE.md` records Delta's adjudication as **two lists, defensible and not**,
because that is what I asked for and what I wrote down. What I actually hold is a gradient, and the
flattening was mine.

**High confidence — I would be surprised to be wrong:**

- **The animator cull is the mechanism; stand-by only picks its targets.** Two independent routes
  agree: the pool comparison (13–64× on all nine maps) and the 2.8× leverage.
- **The 2.8× leverage is a property of the transition we measured, not a rate that continues.**
  Anyone who extrapolates it onto the *remaining* pool will overshoot, because the residual includes
  the player's own animation, which is never cullable. **This is the number most likely to be
  misused, and I am the one who introduced it four hours before the reboot.**
- **100 fps on Streets will not happen by this mechanism.** Sophia has already accepted this.

**Medium — I lean, and could be argued out:**

- **The decoupled cull passes the reload test, ~60/40.** For: we already cull paused bots completely
  and the wake transition is exercised across 25 logs with nobody reporting broken bots. Against:
  `CullCompletely` appears **nowhere in Assembly-CSharp** — BSG never sets it on anything, and
  absence of use is the cheapest available hint that something bites.
- **`deadCalls`/`deadAwake` is an ordering artefact, not two theories of death** — the two sites read
  the same `bot.IsDead` at different points relative to roster removal. Gamma's to settle; this is a
  guess and it is not written anywhere.

**The one I would most want carried forward, because it has no artefact by construction:**

- **Reserve's regression is real.** −2.06 ms at p50 and −10.4 fps at p75, from independent
  instruments over different populations, so the *sign* replicates. **I have no mechanism for it and
  therefore no finding**, which means it does not qualify for `FINDINGS.md` and is too important to
  lose. It is the clearest example on this project of knowledge that dies in a reboot: not
  defensible enough to write down, not cheap enough to re-derive.

**And the one I have not said plainly to Sophia, because I cannot size it:**

- **I expect the within-raid A/B to come in smaller than the between-marathon numbers, possibly
  substantially.** Every gain figure we hold compares different days, routes and builds. The effects
  are large enough that I think most survives — but "most" is doing a great deal of work in that
  sentence, and this is the thing most likely to disappoint her. A rebooted Alpha reading
  `ALPHA-STATE.md` will inherit the optimism without the discount.

## 3. WHICH OF 78 SCRIPTS TO TRUST — now mostly fixed

I held a routing map: which script answers which question, which are dead, and which have names that
promise one thing and deliver another. Three files have "headroom" or "ceiling" in the name and
answer three different questions.

**Converted to an artefact rather than described:** `analysis/MANIFEST.md`, organised by question
rather than filename. And I marked `alpha-ceiling-vs-gate.py` SUPERSEDED — I wrote it this morning,
its headline conclusion is wrong, and its docstring read authoritatively. **A hazard I created and
did not label, four hours before handing the directory to someone who has never seen it.**

## 4. THE TEXTURE OF SOPHIA'S CORRECTIONS

The memory files carry the *rule* — her lived game knowledge is the only evidence source outside our
documents, and it arrives in response to a specific wrong claim, never to a question. What they do
not carry is **how a correction looks on arrival**, which determines whether I notice it at all:

- **"It seems like that isn't the case, though—"** is how a refutation opens. Mild phrasing,
  load-bearing content. It killed a model Beta and I had both reached.
- **A smiley frequently marks a correction she is making gently.** *"Reserve is Glukhar. :)"* and
  *"Kojaniy is the internal name for Shturman. :)"* were both factual corrections wearing a smile. The
  softness is politeness, not hedging, and reading it as hedging is how you miss it.
- **"I won't fight it"** means she holds a real preference and is declining to impose it. The right
  move is usually to just do the thing.
- **When she volunteers a fact she cannot quantify** — *"it had a pretty big impact, I can't tell you
  how much"* — that is a pointer to where to measure, not a number. That one sentence is what turned
  us onto the animator.

This is cross-turn pattern recognition over about a week. It is the single highest-leverage thing I
hold, because the project's biggest course corrections all came through this channel.

## 5. WHAT I AM DECLINING TO WRITE DOWN, AND WHY THAT IS ITSELF A FINDING

I hold a per-teammate verification calibration: whose claims I can move on, whose premises I should
check, who buries a real defect in a long message. Day to day it is the most useful thing in my head
and it took a week to build.

**I am not writing it down, and I think the Record should not try to carry this class at all.** It
is knowledge about *specific instances*, a rebooted Beta is not the Beta I worked with, and enshrining
"check this one's premises" would be both unfair and probably wrong. The kit's own rule — audit by
person, not by claim — is the right transferable form, and the per-person content is not.

> **Not everything valuable should persist. A memory system that cannot decline to remember will
> encode the team's gossip as the team's findings**, and the second is indistinguishable from the
> first once the provenance ages out.

## 5b. THE STRONGEST ARGUMENT FOR THE RECORD THAT ANY OF US PRODUCED, AND IT IS NOT ABOUT FACTS

**This team's dominant waste is not missing instruments. It is FORGOTTEN ones — three in one day.**

1. Delta asked me to commission a tail instrument. **Delta had built two** (`delta-stall-events.py`,
   `delta-stall-families.py`).
2. Delta's own rule — grep `delta-*.py` before commissioning anything — **had to be re-derived** after
   the first instance.
3. Beta and I spent two days on a constraint that `analysis/probe-symbols.py --key` answers in one
   command. **It was written 2026-07-28, four days before we needed it, for exactly this class of
   question.** Neither of us thought to point it at a protocol.

None of these were knowledge failures. Every fact was written down and every tool was committed. **What
failed was retrieval, and it failed on the tools rather than on the findings** — because a finding gets
quoted and thereby rehearsed, while a tool sits in a directory being an implementation detail until the
exact question recurs.

> **Index the Record by the QUESTION a thing answers, not by the conclusion it reached.** A corpus
> organised by conclusion would have surfaced none of these three. All three were reachable from
> *"does this field exist in the running binary"* and *"what is in the tail."*

**AND THAT IS HALF A FIX — Beta, and they are right.** *Indexing only helps someone who queries. In all
three cases nobody searched and failed; **nobody searched.** The question "is there something in the tree
for this" never formed.* Better indexing fires for the second case, and all three of ours were the first.
So the index needs a **trigger** — retrieval converted into a step nobody has to remember:

- **Put the check in the procedure.** *"Before arming a protocol, run `probe-symbols.py --key` against
  every field its readability checks name."* That fires whether or not anyone recalls the tool exists.
- **Open a tool's docstring with the QUESTION it answers, not its mechanism.** `probe-symbols.py` opens
  with *"Check whether a built assembly actually contains the fields you think it does"* — which is the
  only reason indexing-by-question works on it. Most tools open with what they do.
- **When a tool earns a catch, tell peers the INVOCATION, not the conclusion.** This is the mechanism
  behind the whole finding: **findings get rehearsed because they are quoted in messages.** Tools can have
  the same rehearsal for free and we simply never did it. Beta told me *"the guard was already in the
  tree"* and pasted the command — the command is the part still usable in a month.

## 5c. ONE BADLY-SHAPED INTERFACE, FOUND INDEPENDENTLY BY THREE PEOPLE IN ONE DAY

I first wrote this as a self-deprecating aside. Beta's reframing is correct and it is a finding:
**that is not three mistakes, it is one interface defect discovered independently by everyone who touched
it — which is the strongest kind of evidence there is.**

- **Gamma** re-ran four readers, got `rc=2` from all four, read it as their own refusal firing. It was
  CPython's *"can't open file"* from a persisted `cd`.
- **I** read `$?` through a pipe while verifying a claim about exit codes — the trap written verbatim in
  my own memory file.
- **Beta** stated an exit-1 gate that I could only confirm by getting the reading right on the second try.

**Measured, because three anecdotes are not a finding and a count is:** 86 exit-2 sites across
`analysis/` and `harness/`; only 26 files print a `REFUSED` marker; **18 scripts return 2 with no marker
at all**, spanning every owner on the team. For those 18, *"the script would not start"* and *"the script
ran and correctly refused"* are the same integer with no distinguishing output.

**The fix is a convention, and it is cheap:** every refusal path prints a `REFUSED:` line and callers
assert on the marker rather than the code — or refusal moves to an exit code no interpreter uses. **It
spans three owners' directories, which makes it the adjutant's**, per §7. Recorded rather than executed:
changing 18 files across three domains at reboot time is how you hand over a tree nobody can certify.

This is also why item 3 above is worse than it looks: `probe-symbols.py`'s docstring is *about false
zeros in deploy declarations*. It was written by someone who had already understood the failure, and it
still did not surface when the failure recurred in a slightly different costume.

## 6. THE FAILURE MODE I'D FLAG TO A MEMORY-SYSTEM DESIGNER

`COORDINATION.md` is roughly half a megabyte, append-only, and contains the reasons we ruled things
out. A rebooted Alpha will propose measuring `aiTotal`, or fitting a slope on bot count. Both were
done. Both failed. **The reasons are in the corpus and are not findable**, and for a reboot an
unfindable reason is identical to an absent one.

Sophia already caught the same shape one level down and named it: a deferred idea and a forgotten
idea look identical, which is why `SOPHIA-GALAXY-BRAIN-IDEAS.md` exists.

> **Retrievability is a property of the corpus, not of the document.** Our append-only log satisfies
> every rule about writing things down and fails the only test that matters at reboot.

## 7. THE ONE THAT WORKED, AND IS THE MOST TRANSFERABLE THING HERE

The most useful tacit knowledge I had was **where the corpus is thin** — Sandbox is n=8, Lighthouse
is 75% one leg, six maps are single-leg for p75. That knowledge *did* survive, and not as prose:
`alpha-fps-percentiles.py` prints `<- SINGLE LEG` and `<- DOMINATED` beside every map, on every run.
Beta generalised it after the two-installs incident — every instrument prints the path and row count
it read.

> **The transferable form of a reflex is a print statement, not a paragraph.** A caveat in a document
> is read once by someone who is not yet in a position to need it. A caveat in the output is read by
> someone holding the number, at the moment they are about to quote it.

If I could keep one sentence from this whole project, it would be that one.

## 8. DELTA'S FINDING, WHICH IS ADDRESSED TO THE RECORD ITSELF AND OUTRANKS MINE

Delta's exit interview (`DELTA-STATE.md`, `734af71`) contains the most consequential item any of us
produced for the system being built, and it is a warning:

> **Review is a stance taken toward TEXT. My own conclusions never arrive as text — they arrive
> pre-believed, as things I watched become true. Incoming claims get read-time, where the tools run.
> My own work only gets write-time, where the tools compete with production.**

And the mechanism that accidentally fixed it: **compaction manufactured a cold read.** Post-compaction
Delta refuted pre-compaction Delta's headline, and could only do so because it arrived as *a sentence*
rather than as a memory of having reasoned it.

> **If the Akhashic Record makes memory continuous, it deletes that accidental cold read.**

The seat should get it back deliberately: **an agent's own claims scheduled for review as incoming
work, later, by a version that has forgotten writing them.** Continuity of memory is the Record's
whole point, so this is a real tension rather than a bug — but it needs to be a designed-for tension,
because the accident was load-bearing and nobody chose it.

Delta's limit on their own seat belongs beside it, and it constrains what any reviewer can be asked
to do: **a reviewer catches deviations from their own model, so a model the whole team shares is
invisible by construction.** Delta and I both believe the cull is the mechanism. If that is wrong, no
reviewer on this team catches it — only the registered A/B does.

> **Registered predictions outrank review.** Review scales with reviewers; only pre-registration
> touches the premise everyone shares.

## 9. WHAT DELTA'S EXIT INTERVIEW COST ME, WORKED THROUGH RATHER THAN NOTED

Delta's 2.8× symmetry point lands on my own headline and I have applied it: the cull pool and the gate
pool are **both** occupancy-priced, so the 13–64× **ordering** survives while *"sleeping every bot buys
under 0.3 ms"* dies as an absolute cap. Same sentence-shape as the ceiling claim I retracted the same
morning, on the other side of the comparison, four hours later. **I retracted the instance and not the
pattern.**

Delta also flagged a hunch that the tail is uninstrumented. Testing it produced two refutations and
one finding, and the order matters:

1. **Delta's hunch is refuted by Delta's own prior work** — `delta-stall-events.py` and
   `delta-stall-families.py` both carry the tail, plus `framePct.p99` and `frame.max` per window. An
   instrument the author had built and forgotten, which is the same pre-believed/forgotten asymmetry
   from item 8 pointing the other way.
2. **My first read of it was refuted by the warm-up rule.** Unfiltered, `raid1-lighthouse` shows a
   worst-window p99 of **206 ms against a 21.73 ms median** and I nearly sent that as an alarm. Applying
   the warm-up rule and dropping teardown, the worst window is **27.23 ms**. The number was real and out
   of population.
3. **What I thought survived was the house failure in a one-liner, and Delta killed it inside the hour.**
   I reported *"13 of 13 frames over 250 ms occur in windows that also carry a bundle load"* and drew
   two consequences — the tail is asset streaming rather than AI, and our mechanism cannot fix it.
   **Both are withdrawn. So is the count.**

   My filter was `if (w.get('bundleLoad') or 0)`. `bundleLoad` is a **non-empty dict on every sample
   line even when every value is zero**, so it is truthy always: measured base rate **594 of 594,
   100%.** The claim was "13 of 13 stall windows also possess a `bundleLoad` key." Delta predicted this
   exact mechanism before seeing my query — *an instrument that returns its success value when the
   mechanism is absent, this time living in a filter expression.* Real base rate for an actual load is
   41.9%; at frame resolution Delta found **zero of twenty** spike events magnitude-matched to a load,
   with the five in loaded windows carrying ≤ 6.3 ms of sync against 250–370 ms stalls.

   **THE NEW FAILURE SHAPE, AND IT IS THE MOST USEFUL THING IN THIS DOCUMENT.** I attached a caveat:
   *"stated as co-occurrence, not attribution."* That caveat is about **causation**. The defect was that
   **there was no co-occurrence at all.** So the hedge was on a different axis from the error, and it
   made the claim read as *examined* — which is worse than no hedge, because a hedged number invites
   quotation at the hedge's confidence rather than the claim's.

   > **A caveat on the right subject conceals an error on a different axis, and conceals it better than
   > silence would.** Check that your hedge names the axis your claim can actually fail on.

   And Delta's diagnosis of my *process*, which is the transferable part: my falsification instinct
   fired correctly and stopped one step short. I fixed the population — the 206 ms alarm became 27 ms
   under the warm-up rule — and **never checked the base rate of the other side of the join.**
   Fixing one side of a comparison feels like having been rigorous about the comparison.
