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
- The event ledger (`/var/lib/blackwall/ledger.jsonl`) records what happened
  — that a domain was added, that the wall was applied after you added one,
  that a change looked like drift or like a breach — as kinds and counts and
  timestamps only. It
  never records a URL, a domain you visited, or any browsing content. It's a
  record that the wall is doing its job, not a log of what's on the other
  side of it.

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
