# The decoupled animator cull — what it is, where it lives, how to switch it off

Written for review. This is new shipping behaviour, it is off by default, and it is the piece
of the mod that has had the least eyes on it.

## The one-paragraph version

Framesaver's biggest saving is **not** stopping bots thinking. It is stopping them being
animated. Those two have always been welded together — a bot only got its animator culled if
stand-by had put it to sleep — and nothing chose that; the cull was built on top of stand-by
because stand-by already kept a list of eligible bots.

    stand-by gating BotOwner.UpdateManual   the bot stops THINKING    ~0.011 ms per bot
    AnimatorCullingMode.CullCompletely      the bot stops being DRAWN ~0.25-0.30 ms per bot

The small one is the one that changes behaviour, argues with other AI mods, needs the
posted-role exemptions, and produced all three mid-raid latches in `COORDINATION.md`. This
flag takes the large mechanism without the small one.

## What the flag actually does

**`4. Experimental → Decouple cull from stand-by`**, default **off**.

On, every live bot becomes *eligible* for the cull. Off, only sleeping ones are — today's
behaviour, unchanged.

**Eligible is not culled.** Unity applies `CullCompletely` only while a character's renderers
are invisible. So the engine makes the per-bot decision, every frame, for free — and a bot you
can actually see is never culled, whatever we marked.

That is why there is no distance check and no role exemption in the decoupled path, and why
there should not be. A sniper engaging you from 200 m is either on your screen, in which case
he animates normally, or off it — and vanilla already stopped writing his bone transforms at
10 m, so nothing is lost that the base game had.

## The three places to look

1. **`Patches/SleepingBotAnimatorPatch.cs` → `CullEveryBot`** — the whole decoupled path. Four
   lines of logic: if the flag is on, the animator is real, and the player is a live bot, write
   `CullCompletely`.

2. **`Patches/SleepingBotAnimatorPatch.cs` → `Postfix`** — where it is called, and *why it is
   called there and not inside `ApplyIfSleeping`*. That method's `true`/`false` is what the
   LateUpdate and world-tick skips use to decide whether to skip a bot entirely. If the
   decoupled cull answered `true` for every bot, those skips would suppress
   `Player.LateUpdate` for the whole roster — and `LateUpdate` holds the only call site of
   `VisualPass`, which is the thing that applies the cull. The two features would delete each
   other on the first frame. There is a test asserting the skips cannot see this flag.

3. **`Patches/SleepingBotAnimatorPatch.cs` → `Marked`** — which population the telemetry counts.
   `animCulled` follows whichever cull is switched on, so the log never silently attributes a
   decoupled run's numbers to the coupled arm. `cfg.cullAllBots` records the mode.

## The failure mode, and it is the reason this ships off

`CullCompletely` stops the animator's **state machine** from evaluating. Animation events are
*queued* by state-machine callbacks and drained separately, so with the state machine frozen
the drain runs and finds nothing.

For a sleeping bot that costs nothing — it is not reloading. For an awake one:

> **Does a bot that goes off-screen mid-reload ever finish the reload?**

If animation-driven weapon operations stall, this makes bots go quietly passive the moment you
look away. **No number we collect can see that** — every performance metric would look *better*
if it happened. It needs a person watching, which is `harness/RELOAD-OBSERVATION-TEST.md`.

One hint worth holding: `AnimatorCullingMode.CullCompletely` appears **nowhere in the game's own
code**. BSG never set that mode on anything. That is not evidence of a defect, but it is the
cheapest available reason to suspect something bites.

## Turning it off

Set it back to false in `BepInEx/config/…framesaver.cfg`, or in the in-game config manager. It
takes effect immediately — no restart. `VisualPass` rewrites `cullingMode` every frame, so the
next frame restores vanilla with nothing to undo.

**One exception, and it is the only sharp edge:** if `Skip sleeping bot LateUpdate` is also on,
`VisualPass` is being suppressed for the bots it applies to, so nothing rewrites `cullingMode`
and a bot culled at that moment stays culled until it next wakes. Turn the LateUpdate skip off
first, or expect the change to take effect per bot rather than at once.

## What it does not change

- **Not stand-by.** Sleeping still works exactly as before, and the two can run together.
- **Not the compatibility surface.** Every guard in `COMPATIBILITY.md` is about stand-by, which
  this does not touch. The point of decoupling is to reach the saving without needing them.
- **Not visible bots.** Whatever we mark, Unity animates anything on screen.
- **Not the corpse path.** Dead bots have their animators disabled by the game and never reach
  `VisualPass` again, so they were already free.

## How to check it is doing anything

`bots.animCulledEngine` in the telemetry. It reads the engine rather than our intent — it counts
live bots whose animator actually carries `CullCompletely` on an animator that can honour it.
`bots.animCulled` is what we *asked* for. Read them as a pair:

    animCulled high, animCulledEngine 0   we are asking and nothing is landing
    both 0 with the flag on               nothing is eligible - check you are in a raid
    animCulledEngine tracking animCulled  working
