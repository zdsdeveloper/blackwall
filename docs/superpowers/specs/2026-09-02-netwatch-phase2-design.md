# NetWatch Phase 2 — Design

**Branch:** `netwatch`. `master` remains v1 and is the only branch submitted to the
Omarchy marketplace. Phase 2 changes the QML plugin as well as the daemon, and
none of it goes to `master`.

**Builds on:** `docs/superpowers/specs/2026-09-02-netwatch.md` (Phase 1, shipped
and armed), and the rulings in `.superpowers/sdd/2026-09-02-netwatch-core/progress.md`.

## What Phase 2 adds

Phase 1 records tampering. Phase 2 responds to it, and opens a way out of the
blocklist that costs time rather than resolve.

Two subsystems:

1. **The escalation ladder** — a breach draws a challenge, then a lock.
2. **Delayed removal** — a blocked domain can be released, after a wait that
   doubles each time the same domain is released again.

## Decisions

| Decision | Value | Chosen because |
|---|---|---|
| What counts as a breach | **Only a weakened wall** | An unrelated `/etc/hosts` line was a breach in Phase 1. In Phase 2 that is a lockout for adding a dev host. |
| Ladder at launch | **Full, live immediately** | Operator declined a shadow period. The narrowed breach definition is what makes that defensible. |
| Breach during a pending removal | **Cancels the request** | The wait already served is lost. Harshest of the three options offered. |
| Removal delay | **24h, doubling per domain** | Cheap for a mistake, compounding for a habit. |
| Repeat window | 6 hours | Default, not asked. |
| Lock duration | 20 minutes | Default, not asked. |
| Challenge phrase | Operator-set in config | Not mine to choose. |

The challenge phrase lives in the existing plugin config,
`~/.config/omarchy/zds.blackwall.json`, under `challengePhrase`. It is read by
the plugin, never by the daemon — the daemon says only *that* a challenge is
due, never what it should say. If unset, the plugin falls back to a built-in
default so a missing config can never mean a challenge that cannot be answered.

## The bridge, and why it is not a bridge

The daemon runs as root, outside the Wayland session; the plugin's IPC socket
lives inside it. This looked like it needed a privilege bridge — a root-written
penalty file the plugin watches, or a user-level relay service.

It does not. Root bypasses DAC, so it can reach the session's socket directly.
**Verified 2026-09-02** on this machine: as root, with `XDG_RUNTIME_DIR` set,
both `qs ipc --pid <pid> call blackwall status` and the explicit
`WAYLAND_DISPLAY` form returned the live status JSON.

So the daemon calls the `engage()` the plugin already has:

1. Find the Quickshell process (`/usr/share/omarchy/shell`).
2. Read `XDG_RUNTIME_DIR` from `/proc/<pid>/environ`.
3. `qs ipc --pid <pid> call blackwall <method> <args>`.

`--pid` rather than display matching: the daemon discovers its target instead of
being configured with it, so a different uid, a restarted shell or a changed
display does not break it. When no session exists the call fails harmlessly and
the breach simply stays unacknowledged — which is exactly what rung 3 consumes.

No penalty file. No relaxation of `bin/blackwall-file-guard`, which refuses
files it does not own and should keep refusing them. No third component whose
death would quietly take the ladder down with it.

## Breach means the wall got weaker

Phase 1 escalated when the managed files' **text** changed. That is why an
unrelated `/etc/hosts` entry produced a breach: `splice` rebuilds the file with
the managed region last, so an appended line moves and the text differs.

Phase 2 asks a different question, before repairing anything:

- **hosts** — is every expected sink line present? Four per domain: `0.0.0.0`
  and `::`, for the apex and the `www.` form.
- **zen policy** — is `DNSOverHTTPS` still `{"Enabled": false, "Locked": true}`?
- **unit** — does `/etc/systemd/system/blackwall-netwatch.service` exist, is it a
  regular file rather than a symlink to `/dev/null` (masked), and does it match
  the installed copy?

Any of those failing is a weakening, and only a weakening escalates. Everything
else is repaired in silence, exactly as Phase 1 repairs drift.

`splice()` additionally stops relocating the managed region, so an unrelated
edit no longer rewrites the file at all. That removes the churn at its source
rather than only declining to punish it.

The unit check lands here rather than later because rung 3 depends on it: a
masked unit is how the ladder would otherwise be defeated without ever tripping.

## The ladder

State is derived, not stored: a breach is **unacknowledged** until the plugin
acknowledges it. Rung selection counts unacknowledged breaches recorded in the
last 6 hours — a rolling window, not a window opened by the first breach.

**The ladder fires on a new breach, never on a standing one.** A breach that
stays unacknowledged does not re-challenge on every 30-second cycle; the rung is
chosen once, when the breach is recorded. The only other trigger is the plugin's
startup check. Without this an unanswered challenge would reappear every half
minute until the operator was driven to kill the shell, which is a way of
teaching them to kill the shell.

| Condition | Rung | Effect |
|---|---|---|
| 1 unacknowledged breach in the window | Challenge | Daemon calls `challenge()`; plugin shows a Blackwall overlay requiring a typed phrase, confirm disabled for 15s |
| 2 or more | Lock | Daemon calls `engage(1200)` |
| Any unacknowledged breach, no session | Deferred | Plugin asks at startup and engages before anything else |

The plugin sends `netwatchctl ack` once a challenge is completed or a lock has
engaged. Acknowledgement is the only thing that clears the count.

**Dismissing a challenge does not acknowledge it.** Closing the overlay, or
never answering it, leaves the breach standing — so the next weakening counts as
the second in the window and lands on the lock. Refusing to engage with rung 1
is a choice to take rung 2, which is the correct direction: the way out of the
ladder is answering it, never ignoring it.

### What must never escalate

Carried from Phase 1's ledger, and load-bearing:

- Verdicts `init`, `applied` and `drift`. Only `breach`.
- **The daemon's first enforcement after start.** A restart mid-transaction
  used to look like tampering; in Phase 2 that is a lockout for rebooting.
- Anything during a sanctioned pacman window, per Phase 1's provenance rules.

## Delayed removal

`netwatchctl request-removal <domain>` starts a countdown:

```
delay = 24h × 2 ^ (number of removals already APPLIED for that domain)
```

Applied removals, not requests — cancelling costs nothing and a mistyped request
must not raise the price for ever. Releasing the same domain repeatedly is the
pattern that compounds.

Cancelling is free and instant. **A breach voids every pending removal**, losing
whatever wait had been served.

### Append-only, including for us

The blocklist is `chattr +a`; nothing can be deleted from it. Removal therefore
appends a **tombstone** — a line `-example.com` — and `blocklist.parse` applies
lines in order, so a later re-add re-blocks. The file only ever grows, and the
current set is a replay.

Pending removals live in their own append-only journal,
`/var/lib/blackwall/removals.jsonl`, holding `requested`, `cancelled`, `applied`
and `voided` records, replayed at startup. No state file that must be rewritten,
so no exception carved into append-only for our own convenience.

## New interfaces

**Socket commands:** `ack`, `request-removal <domain>`, `cancel-removal <domain>`.
`status` gains `unacknowledged`, `pending_removals` (domain and seconds left),
and `weakened`.

**Plugin IPC (new methods on `blackwall`):** `challenge(reason)`. The plugin
gains a startup check that calls `netwatchctl status` and engages if anything is
unacknowledged.

**`netwatchctl`:** the three new subcommands, plus pending removals and their
countdowns in `status` output.

## Testing

Unit tests as in Phase 1: stdlib `unittest`, explicit paths, tmpdir, no root, no
real sockets or subprocesses, whole suite under two seconds. The IPC bridge is
injected as a callable so the ladder is testable without a running shell — the
same shape as Phase 1's `flusher`.

The scenarios that must be covered because they are the expensive failures:

- An unrelated `/etc/hosts` edit does **not** escalate.
- A missing sink line **does**.
- A masked unit does.
- The first enforcement after start never escalates.
- A breach voids pending removals.
- Doubling counts applied removals, not requests.
- A tombstoned domain is unblocked; re-adding re-blocks it.

## Non-goals

- Any change to `master`.
- Phase 3's bar widget and window. `netwatchctl` remains the interface.
- Any removal path that is faster than the delay, for any reason.
