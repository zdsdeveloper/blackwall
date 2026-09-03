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

    An acknowledgement clears everything before it. Dismissing a challenge is
    not an acknowledgement -- the breach stands, so the next one is the second
    in the window and lands on the lock.
    """
    now = time.time() if now is None else now
    count = 0
    for entry in entries:
        at = entry.get("at")
        if not isinstance(at, (int, float)):
            continue
        kind = entry.get("kind")
        if kind == "ack":
            count = 0
        elif kind == "breach" and now - at <= window:
            count += 1
    return count


def rung(entries, now=None, window=WINDOW_SECONDS):
    """CHALLENGE for the first unacknowledged breach in the window, LOCK after."""
    return CHALLENGE if unacknowledged(entries, now, window) <= 1 else LOCK
