# Simple APK — design record

Identity, techniques, and the filter each technique passed. Joshua's
design rules (`~/workspace/design-rules.md`) win on any conflict.

## Identity: the warm workbench

Simple APK looks like a workbench, not a dashboard. Warm near-charcoal
bench (`#2b2622`), off-white ink (`#f7f5f0`), one amber work-lamp accent
(`#e8a33d`) for the thing that matters most: the Build button and the
status light. Tight radii (cards 6 px, buttons 4 px), plain words,
system type with mono only for the build log.

Token inspiration came from the Warp design file in
`design-skills/awesome-design-md/design-md/` (warm canvas, off-white
ink, tight radii, Inter-like type, mono for technical text). It is
inspiration, not a clone: Warp has no chromatic accent at all, while
Simple APK's amber lamp is its own mark, and the voice is plain
words for a first-time user, not developer chrome.

The icon carries the same identity: a charcoal bench tile, an amber
lamp arc across the top, a white phone with an amber check. Source in,
finished app out.

## Techniques pulled (3, from the BNB UI Design Source File Library)

### 012 Progressive disclosure: the minimum now, the rest when asked

The main window shows three steps only: pick, build, done. The log,
setup, settings, and help each live in their own window behind the
menu bar. Nothing else is on screen.

### 003 Calm technology: the interface that knows when to shut up

One status light plus one status line at the bottom of the main
window. The build log stays in its own window. The app never pops up
to say it worked: step 3 quietly shows the finished app. The only
interruptions are things the user asked for (a failed build's plain
message, an update found) or chose (cancel, clear work files).

### 008 Delight, done right: personality in the small places

One moment only: when the APK is ready, a check fades in over 200 ms
on step 3. Nowhere else. No celebration on the main workflow, no
sound, no confetti.

## The filter (design-rules.md Part 3)

Each technique passed all four questions:

1. **Does it make it simpler?** Progressive disclosure leaves three
   choices on screen. Calm technology leaves one status line. Delight
   marks the one moment worth marking. All three reduce what the user
   has to think about.
2. **Does it survive the toy test?** A child can follow three numbered
   steps top to bottom: pick, build, done. Nothing needs explaining.
   The Build button is the biggest, brightest thing on screen when it
   is time to press it.
3. **Does it run on his PC?** 8 GB RAM, no GPU. All motion is one
   200 ms opacity fade; there is no blur, no layout animation, no
   shadow animation. The stylesheet is flat colours and hairlines.
4. **Does it make the app feel like itself?** The warm bench and amber
   lamp give it a look no other studio app has, and the lamp arc in
   the icon is its own mark. Decoration serves the identity; it never
   fights readability.

## What was deliberately not pulled

- **Honest loading (011)** as a named technique: its substance is
  already in the rules the app follows (U16 always show what it is
  doing, U26 progress plus cancel, U37 real measurements). The log
  streams real lines with a real elapsed time; there is no fake
  progress bar to dress up, so no skeleton screens were needed.
- **Bento grids (005):** three vertical steps read as a journey;
  tiles would have made them feel like a dashboard.
- **Spring physics (002):** nothing here is grabbed or flung; a
  spring would be decoration without a gesture to match.
- **Neo-skeuomorphism (006):** pressable controls matter for dials
  and mixers, not for three big buttons.

## Rules that shaped the build most

- U34 toy test: three steps, plain words, one primary button.
- U1 one function one window: log, setup, settings, help are separate
  windows, never crammed onto the main window.
- U35/U36 the backend configures itself: Gradle memory and worker
  count are sized from the machine's RAM and never appear as settings.
- U20 every field explains itself underneath: every settings field
  and every step carries its plain-words line.
- U32 never silently skip: unreadable zip entries are listed with
  reasons under step 1.
- U16 always show what it is doing: the status light and line never
  go quiet during a job.
