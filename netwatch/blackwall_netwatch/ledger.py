"""What happened, in order. Kinds and counts, never content.

One JSON object per line so a partial write costs one entry rather than the
file. Opened O_APPEND every time: the daemon may be restarted mid-write and two
writers appending is safer than one writer holding a handle across a restart.
"""

import json
import os
import time


def record(path, kind, **fields):
    entry = {"at": time.time(), "kind": kind}
    entry.update(fields)
    line = json.dumps(entry, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return entry


def read(path):
    entries = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return entries
