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
        os.fchmod(fd, 0o644)
        written = 0
        while written < len(line):
            # A short write would leave a half-line for the next appender to
            # land on, turning one lost entry into two corrupt ones.
            written += os.write(fd, line[written:])
        os.fsync(fd)
    finally:
        os.close(fd)
    return entry


def read(path):
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
    return entries
