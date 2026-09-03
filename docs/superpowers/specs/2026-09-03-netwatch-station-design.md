# NetWatch Station — Design

**Branch:** `netwatch`. `master` stays v1 for the marketplace.

## What it is

A window, opened from the bar menu, that puts the operator at a NetWatch
station: the agency that maintains the Blackwall and watches what is on the
other side of it. Not a settings dialog with a theme — a post.

That framing decides everything else. Domains are not a list, they are contained
subjects. The ladder is not a preference, it is threat state. And purely
decorative telemetry is legitimate rather than filler, because a real operations
console carries readouts nobody acts on.

## Shape

A real `FloatingWindow` — movable, resizable, leaveable open beside other work.
The shell supports this for plugins declaring a `panel` entry point; the shipped
`omarchy.dev-gallery` plugin is the working reference. The host gives the plugin
a Loader and calls `open(payloadJson)`, `close()` and `requestClose()`.

```
┌─ NETWATCH ── BLACKWALL MONITOR ─────────────── STATION zds ── 04:17:22 ─┐
│ ╌╌╌ a pulse travels this trace, corner to corner ╌╌╌                    │
│   ▛▀▀▜ SUBJECT              CONTAINMENT ─────────────  TELEMETRY        │
│   ▌  ▐  the wall, breathing  ◉ gotanynudes.com   14h   RUNG  [█▁] 1/2   │
│   ▙▄▄▟                       ◉ example.net        2h   UNACK      0     │
│                              ◉ ...                    CYCLE   ▁▂▃▂▁▂    │
│   INTEGRITY   ● INTACT      > CONTAIN ______________  ○ DoH LOCKED      │
│   ENFORCED    ⟳ 30s         [▓▓▓▓▓▓░░░░] committing   ○ UNIT INTACT     │
│   LEDGER      ● ARMED                                 ○ LEDGER SEALED   │
├─────────────────────────────────────────────────────────────────────────┤
│ 04:17:02  applied   hosts          ← the ledger, tailing                │
└─────────────────────────────────────────────────────────────────────────┘
```

## Real versus decorative

Both, deliberately, and the difference is not hidden.

**Real** — every one of these is live daemon state:
- the wall (`BlackwallWall`, the same component the lock and the challenge use)
- a lamp per domain, lit only when that block is verified present in `/etc/hosts`
- the containment input, with a progress bar tracking the actual round-trip
- the three status lamps: DoH locked, unit intact, ledger sealed
- the rung gauge and unacknowledged count
- the ledger tail

**Decorative**, and honest about it:
- the perimeter trace pulse
- the cycle sparkline
- a slow-rotating sigil beside SUBJECT
- packet glyphs drifting through dead space

## Alive, and mechanical

Idle is never static. The wall breathes; the trace pulses; the sigil turns; the
sparkline advances. On top of that, two behaviours do the work of making the
station feel like a machine rather than a picture of one:

- **Power-on.** Opening the window runs a boot sequence: lamps light in order,
  the wall fades up, telemetry spins to life. Roughly 800ms. The station comes
  up rather than appearing.
- **Local reaction.** Hovering a domain row swells the static behind it. A
  failed action glitches hard instead of raising an error box. The surface
  reacts where it is touched.

## What the daemon has to add

`netwatchctl status` is line-based for humans. The panel needs structure:

- `netwatchctl status --json` — the whole state as one object
- `netwatchctl log [--limit N]` — recent ledger entries, newest last

Both read-only, both unprivileged, neither adding a way to weaken anything.

## Non-goals

- No removal path. There is none and there is never going to be one; the station
  shows what is contained, and containing more is the only verb it offers.
- No change to `master`.
