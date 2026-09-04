"""What happened, in order. Kinds and counts, never content.

One JSON object per line, so a partial write costs one entry rather than the
file. Opened O_APPEND on every call: for a line this size on a local filesystem
the append lands whole, and not holding a handle across a daemon restart is
worth more than the stronger guarantee a held handle would give.
"""

import json
import os
import time


def record(path, kind, **fields):
    entry = {"at": time.time(), "kind": kind}
    entry.update(fields)
    line = (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        # os.open's mode is masked by the ambient umask, so on its own it
        # promises nothing. Set the mode we actually want on the descriptor.
        #
        # Tolerated failure, and the reason is not hypothetical: once this file
        # is made append-only the kernel refuses a mode change on it, and an
        # unguarded fchmod here would turn arming the wall into breaking it --
        # every add failing, at exactly the moment the operator has made the
        # problem hard to undo. The mode is already right by then anyway.
        try:
            os.fchmod(fd, 0o644)
        except OSError:
            pass
        written = 0
        while written < len(line):
            # A short write would leave a half-line for the next appender to
            # land on, turning one lost entry into two corrupt ones.
            written += os.write(fd, line[written:])
        os.fsync(fd)
    finally:
        os.close(fd)
    return entry


# The last read of each ledger, keyed by what the file looked like when it was
# taken: {path: (size, mtime_ns, entries)}.
#
# The ledger only grows -- that is the whole point of it -- and `read` is called
# from nine places, including status, which a panel polls every two seconds. At
# 2660 entries a status call already spends 58ms re-parsing a history that has
# not changed, and nothing about that gets better: the file is append-only by
# design, so the cost rises for ever.
#
# Keyed on size AND mtime, so any write invalidates it. A modification that
# changed neither would have to be deliberate, in place, and made as root on a
# file the kernel has been told to refuse in-place writes to.
_CACHE = {}


def forget(path=None):
    """Drop the cache, for one path or all of it. Tests use this."""
    if path is None:
        _CACHE.clear()
    else:
        _CACHE.pop(path, None)


def read(path):
    try:
        st = os.stat(path)
        key = (st.st_size, st.st_mtime_ns)
        hit = _CACHE.get(path)
        if hit is not None and hit[0] == key:
            # A copy: callers filter and slice what they get back, and handing
            # out the cached list itself would let one of them mutate what
            # every later reader sees.
            return list(hit[1])
    except OSError:
        # No file, or it cannot be stated. Fall through to the read, which
        # answers the same way it always has.
        key = None

    entries = []
    try:
        # errors="replace" rather than strict: a process killed mid-write can
        # truncate a multi-byte sequence at EOF, and a decode error there would
        # take down the whole call instead of costing the one entry it damaged.
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                # Valid JSON that is not an object is corruption too: letting it
                # through would hand the caller something it cannot key into.
                if isinstance(entry, dict):
                    entries.append(entry)
    except (OSError, ValueError):
        return entries
    if key is not None:
        _CACHE[path] = (key, list(entries))
    return entries
