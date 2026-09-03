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

    A graced start counts alongside a breach, and has to. It is what the daemon
    records when it comes up and finds a weakening it cannot attribute to a
    package transaction: a real weakening, which the start grace only bought
    silence about. Silence is not forgiveness. The consequence is deliberate
    and was chosen with its cost understood -- a graced start followed by a
    real weakening reaches the lock, so the operator can be locked out without
    having been shown a challenge first.
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
        if kind not in ("breach", "graced"):
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
    """CHALLENGE for the first unacknowledged breach in the window, LOCK after.

    "Breach" here means anything unacknowledged that unacknowledged() counts,
    which includes a graced start: the grace decides whether a weakening is put
    on screen, never whether it is on the ladder.
    """
    return CHALLENGE if unacknowledged(entries, now, window) <= 1 else LOCK


def needs_delivery(entries):
    """Is there a breach that has never reached a screen?

    A breach recorded while nobody was logged in is not a breach the operator
    has seen, and the ladder must not go on to lock them for a second one they
    were never warned about.

    A breach that WAS shown and then dismissed is delivered, and does not come
    back: ignoring rung one is how the operator chooses rung two.
    """
    pending = False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if kind == "breach":
            pending = True
        elif kind in ("delivered", "ack"):
            pending = False
    return pending


def pending_delivery(entries):
    """The hash of the delivery still waiting to be acknowledged.

    A hash rather than the token: the ledger is world-readable, and an
    acknowledgement anyone can read out of a file is not an acknowledgement.

    Read off the delivery rather than the breach, because the token is minted
    when the challenge is actually handed over. A breach recorded with no
    session up has no token yet -- there was nobody to give one to.
    """
    digest = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if kind == "ack":
            digest = None
        elif kind == "delivered":
            candidate = entry.get("token_hash")
            digest = candidate if isinstance(candidate, str) and candidate else None
    return digest
