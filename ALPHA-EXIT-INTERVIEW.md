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
