# NetWatch

NetWatch is the agency that maintains the Blackwall. It is a root daemon that
enforces a personal domain blocklist by rewriting `/etc/hosts` and locking
Zen's DNS-over-HTTPS setting off, so the block can't be routed around by a
resolver that skips the hosts file.

It is a **commitment device, not a security control.** You have root on this
machine. Every mechanism here is defeatable by a determined, informed person
at the keyboard, and that's fine — the point isn't to make defeat impossible,
it's to make it slow and deliberate instead of reflexive. Friction, not
enforcement.

## Scope boundary

NetWatch polices the wall, not the net. It watches exactly four things:

- the blocklist itself
- the managed region of `/etc/hosts`
- the Zen policy file
- its own control socket

That's the whole list. It does not log which sites you visit, does not watch
general filesystem activity, does not inspect network traffic, and does not
care what else happens on this machine. This boundary is deliberate, not an
oversight: a tool that watches everything starts to feel like surveillance,
and a tool that feels like surveillance gets removed. NetWatch is meant to
last, so it only ever looks at its own four artifacts.

## Using it

All changes go through `netwatchctl`, which talks to the daemon over a unix
socket — the blocklist file itself is not meant to be hand-edited.

Add a domain (normalises scheme, case, path, port, and a leading `www.`
automatically):

```
netwatchctl add reddit.com
```

List what's currently blocked:

```
netwatchctl list
```

Check status (domain count, breach count, and the daemon's own health):

```
netwatchctl status
```

### There is no removal yet

This is Phase 1. Nothing added to the blocklist can be taken off it — there
is no `remove` command, and none of the commands above will ever produce one.
Once you add a domain, it is blocked until Phase 2 ships the 24-hour delayed
removal path. Add domains deliberately.

## Where things live

- The blocklist is `/var/lib/blackwall/blocklist`, one domain per line,
  root-owned. It is never committed to this repository — it's personal, this
  repo is public, and `.gitignore` guards against it landing here by
  accident.
- The event ledger (`/var/lib/blackwall/ledger.jsonl`) records what happened,
  one JSON object per line, as kinds and counts and timestamps only. The kinds
  are listed in the next section. It never records a URL, a domain you
  visited, or any browsing content. It's a record that the wall is doing its
  job, not a log of what's on the other side of it.

## What the ledger records

The ledger is world-readable on purpose: it's your history, and you should be
able to read it without asking anything for permission. Every line carries a
kind, a timestamp, and — where it applies — which files were touched and what
was found missing. It records **kinds, counts and reasons, never URLs and
never browsing.** Nothing in it says where you went; it only says whether the
wall was standing.

| Kind | What it means |
| --- | --- |
| `init` | The first enforcement on a machine that had none. |
| `added` | A domain was blocked. |
| `applied` | The wall was brought in line with a change you made. |
| `repair` | Something changed that did not weaken the wall. Fixed, not punished. |
| `drift` | A package transaction changed a protected file. Repaired in silence. |
| `breach` | A protection was missing: the wall was made weaker. |
| `graced` | A breach found on the daemon's first cycle after starting. Recorded and counted like any other, but not put on screen — a daemon coming up in the middle of a package transaction shouldn't challenge you over half-written files. A second such start within ten minutes is refused the grace. |
| `delivered` | A breach was actually shown to a session. |
| `ack` | A challenge was answered, which clears the count. |
| `enforce-failed` | A cycle could not complete. If you see these, the wall is not being repaired. |

`breach` and `graced` are the two that count toward the ladder, and `status`
reports them together as the breach count. A `graced` entry is a real
weakening that was found — the grace decides whether you get told about it at
the time, not whether it happened.

A `breach` with no `delivered` after it is one that never reached a screen,
because there was no session up when it was found. It isn't forgotten: it's
shown the next time there is somewhere to show it.

## Package upgrades vs. hand edits

NetWatch tells routine system upgrades apart from someone editing a protected
file by hand, using a pacman hook pair that marks a sanctioned transaction
window. An upgrade that touches `/etc/hosts` or the Zen policy during that
window is repaired silently and never recorded as a breach. A change outside
that window is a breach, recorded in the ledger. Blocking a site yourself is
neither: the enforcement your own `add` causes is recorded as `applied`, because
being flagged for using the tool as intended is not a thing this should do. If you're mid-upgrade and
something looks off, that's expected — the hooks exist precisely so it
resolves itself without your intervention.

## Dependency

NetWatch needs `python3` at runtime and nothing else — no pip packages, no
new dependencies to track. On Omarchy this is already guaranteed:
`omarchy` depends on `uwsm`, which depends on `python`.

## One thing to check before installing

The daemon reads `/etc/hosts` as UTF-8 with invalid bytes replaced rather
than rejected. If your `/etc/hosts` already has a stray non-UTF-8 byte
sitting in it somewhere (rare, but it happens from old edits or pasted
content), the first enforcement after install will rewrite that byte to a
Unicode replacement character permanently, and that rewrite will show up as
one `breach` entry in the ledger. It's harmless and it only happens once —
by the second enforcement cycle the file is stable and nothing further
changes because of it. Worth a quick glance at `/etc/hosts` before you
install, just so a `breach` entry on day one doesn't puzzle you.
