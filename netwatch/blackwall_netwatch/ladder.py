"""Which rung a breach lands on.

Pure arithmetic over ledger entries, deliberately: the decision to lock someone
out of their own machine should be inspectable without a daemon, a socket or a
session anywhere near it.
"""

import time

CHALLENGE = "challenge"
LOCK = "lock"

WINDOW_SECONDS = 6 * 60 * 60
LOCK_SECONDS = 20 * 60


def unacknowledged(entries, now=None, window=WINDOW_SECONDS):
    """Breaches recorded in the window that nothing has acknowledged.

    Entries are taken in list order, which for an append-only ledger written by
    a single process is chronological order. Nothing here re-sorts them: the
    file is the sequence.

    An acknowledgement clears everything before it. Dismissing a challenge is
    not an acknowledgement -- the breach stands, so the next one is the second
    in the window and lands on the lock.
    """
    now = time.time() if now is None else now
    count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if kind == "ack":
            count = 0
            continue
        if kind != "breach":
            continue
        at = entry.get("at")
        # bool is an int in Python, and a True here would read as an ancient
        # timestamp rather than the malformed entry it is.
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            continue
        age = now - at
        # Both ends. A future-dated entry gives a negative age, which an upper
        # bound alone would accept for ever -- holding the ladder at
        # lock-eligible until the clock caught up.
        if 0 <= age <= window:
            count += 1
    return count


def rung(entries, now=None, window=WINDOW_SECONDS):
    """CHALLENGE for the first unacknowledged breach in the window, LOCK after."""
    return CHALLENGE if unacknowledged(entries, now, window) <= 1 else LOCK
