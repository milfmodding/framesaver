# The reload observation test, and why it needs a person

The decoupled animator cull is the one change on this project that **no metric we own can validate.**
Everything else has been settled by reading a log. This cannot be, because the failure mode is
"bots go quietly passive when unobserved", and every performance number would look *better* if it
happened.

So this is a gameplay observation with a protocol, not a measurement. Written before the build exists
so the procedure is not improvised around whatever tomorrow happens to show.

## The mechanism at risk, stated so the observation is aimed at it

`AnimatorCullingMode.CullCompletely` stops **state-machine evaluation**. Animation events are
*enqueued* by `AnimationEventsStateBehaviour.OnStateEnter/OnStateExit`; `EmitEvents()` drains that
queue. With the state machine frozen the drain still runs and finds nothing.

For a **paused** bot that costs nothing — it is not reloading. The open question is the awake one:

> **Does a bot that goes off-screen mid-reload ever finish the reload?**

If animation-driven weapon operations stall, a decoupled cull neuters every bot the moment it leaves
your screen. That is worse than anything stand-by has ever done, and it is invisible to the entire
corpus.

**One piece of weak evidence in favour before starting:** we already cull paused bots completely and
the wake transition is exercised constantly across 25 logs with nobody reporting broken bots. That
covers coming *out* of the cull. It does not cover being culled *during* an operation.

**One piece of weak evidence against, worth holding:** `CullCompletely` appears **nowhere in
Assembly-CSharp**. BSG never sets that mode on anything. Absence of use is not evidence of a defect,
but it is the cheapest available hint that something bites, and it is the hypothesis this test exists
to check rather than to dismiss.

## Config for the test

    [1. Bot stand-by] Enabled        = false      <- stand-by OFF, so the cull is the only actor
    decoupled cull                   = true       <- every AI player cull-eligible
    Skip sleeping bot LateUpdate     = false      <- it suppresses the VisualPass the cull rides on
    [3. Telemetry] Enabled           = true
    [3. Telemetry] Window seconds    = 5          <- NOT OPTIONAL, see below

Stand-by off matters: with it on, a bot far enough away to be culled is probably also paused, and a
paused bot that fails to reload proves nothing. **The subject has to be awake, fighting, and culled.**

**`Window seconds = 5` is load-bearing, not tidiness (Beta).** `animCulledEngine` is sampled ONCE at
window close, like every `bots.*` field. At a 30 s window a 6-second look-away has roughly a 1-in-5
chance of being the moment sampled, so most windows would read 0 on a *working* cull and the objective
half below degenerates into noise. At 5 s every look-away spans at least one close.

## Procedure

**Step 0a — the positive control, and do not skip it.** Fight a bot at 30-60 m and keep it on screen
continuously through a reload. Watch it stop firing, reload, and resume. **If you cannot reliably see
a reload complete while watching, the test cannot detect one failing to complete**, and everything
below returns "seemed fine" whatever the truth is. Do this until you know what the resume looks like.

**Step 0b — PROVE THE CULL ENGAGES, before any real attempt.** Turn away from a live bot and confirm
`bots.animCulledEngine` **rises**. If it does not, the cull is not firing and every attempt below
would pass vacuously — a clean PASS from a test that never ran, which is the worst available outcome
and the exact failure this document was written to avoid. This is a precondition, not a post-hoc
validity check.

**Step 1 — the test. TURN AWAY. Do not use cover.** Same engagement. The moment the bot starts
reloading, **turn so the bot leaves your view frustum entirely.** Hold for **5-8 seconds**, well past
a normal reload. Then look back.

**Why not cover (Beta).** The mechanism is `SkinnedMeshRenderer.isVisible` — Unity's *renderer*
visibility, which is frustum-based. A bot standing behind a wall can remain "visible" to Unity while
being invisible to you; whether occlusion culling removes it is a property of the scene, not something
this procedure can assume. Cover therefore risks the cull never engaging while the test appears to run
normally. **Turning away is reliable: out of frustum, invisible, culled.** The earlier version of this
file offered "full cover, or turn away" as equivalent. They are not.

**Step 2 — the discriminating observation.** This is the whole test, and it is not "is the bot
alright":

- **PASS** — the bot is *already* firing, or fires within a beat of you re-acquiring it. The reload
  completed while it was culled.
- **FAIL** — the bot is idle when you look back and then starts reloading or firing *after* a moment
  on screen. **The reload completed only once un-culled**, which means it was stalled the whole time
  you were not looking.

The tell is the ordering, not the outcome. A bot that resumes *after* being observed is the failure,
even though it looks fine a second later.

**Step 3 — repeat 5+ times**, and include one where you stay away 15+ seconds. A stall that resolves
in 6 seconds and one that never resolves are different bugs and only the long hold separates them.

**Step 4 — the negative control.** Same sequence with the decoupled cull **off**. Every repetition
must pass. If any fails, the test is measuring something other than the cull and its results are void.

## The objective half

The log cannot see the bug, but it can confirm the subject was actually culled — otherwise a clean
result may mean the cull never fired:

- **`bots.animCulledEngine` must be non-zero** during the windows you were looking away, since it
  counts bots the engine actually culled rather than what we asked for.

  **It would have read 0 through this entire test as originally built (Beta, caught before the raid).**
  It walked the *marked* set, and with stand-by off `Sleeping` is empty by construction — so a
  perfectly working cull would have logged zero on every window and this test would have voided a good
  run on its own objective half. It now walks the live AI roster, which is also strictly better for its
  original job: a latch is a bot the engine still culls after we stopped asking, and scanning only what
  we currently mark scans the one population guaranteed not to contain the evidence.
- **`bots.awake` must stay high.** If it drops, stand-by got involved and the subject was paused
  rather than culled, which invalidates the run.
- Mark each look-away with the **mouse-button mark key**. The mark carries the preceding 5 s of frame
  times plus your position and look-sweep, so each attempt is locatable in the log afterwards without
  reconstructing it from the clock.

## What each result means, registered before the data

- **All pass, positive and negative controls both behave** — decoupling is viable and the mod's
  0.25-0.30 ms/bot mechanism can ship without stand-by's compatibility surface. Still behind a flag
  until a longer play session agrees.
- **Any clean FAIL** — decoupling is dead in this form. The animator cull stays coupled to stand-by,
  and `COMPATIBILITY.md` gets the reason recorded, which is worth having regardless: right now
  nothing says the coupling is anything but incidental.
- **Ambiguous, i.e. bots look sluggish but nothing is clearly stalled** — treat as FAIL for release
  purposes. A behavioural regression that a careful operator cannot confidently rule out in five
  attempts is not one a player will tolerate for a hundred raids.

## Why this is not negotiable before release

Every other gate on this project is a number. This one is a person watching, and it is the only
defence against a class of bug the performance corpus is **structurally unable to detect** — the same
asymmetry as the operator being the only party who can observe a failure and the least able to
diagnose it. If the cull ships decoupled without this, the first report will come from a player, in
prose, about bots that "feel wrong", and there will be no measurement to connect it to.
