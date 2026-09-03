"""Was that change the package manager, or was it a pair of hands?

The operator updates through the Omarchy bar updater, which shells out to pacman
and yay. A package replacing a file we protect is routine and must be repaired in
silence. A hand edit is not. Getting this backwards -- punishing someone for
running a system update -- is the failure most likely to make this tool resented,
so both an explicit hook marker and pacman's own lock are consulted.
"""

import os
import time

STALE_AFTER_SECONDS = 30 * 60

PROC_DIR = "/proc"

# pacman holds the lock directly; paru drives libalpm itself and never spawns a
# pacman child, so it has to be named here in its own right.
PACKAGE_MANAGERS = ("pacman", "paru", "yay")


def _age(path, now):
    """Seconds since `path` was last written, or None if it is not there.

    ValueError is caught alongside OSError because a path containing an embedded
    NUL raises the former, and nothing this daemon reads is allowed to raise.
    """
    try:
        return now - os.stat(path).st_mtime
    except (OSError, ValueError):
        return None


def transaction_alive(proc_dir=PROC_DIR):
    """Is a package manager actually running right now?

    Public because the daemon asks it too, when deciding whether a transaction
    window left lying around belongs to a transaction that still exists.

    pacman's lock file carries no pid, so a lock left behind by a killed
    transaction is indistinguishable from a live one by inspecting the file. On
    Arch a stale db.lck is an ordinary condition, and without this check a single
    `touch` of that path would put the daemon into permanent drift and every hand
    edit after it would go unrecorded.
    """
    try:
        entries = os.listdir(proc_dir)
    except (OSError, ValueError):
        return False
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_dir, entry, "comm")) as f:
                if f.read().strip() in PACKAGE_MANAGERS:
                    return True
        except (OSError, ValueError):
            continue
    return False


def transaction_in_progress(pacman_lock, now=None, proc_dir=PROC_DIR):
    """Is a package transaction actually under way?

    One definition, used by both the classifier and the window reaper. They had
    two, and the reaper's was the looser: it took the mere existence of db.lck
    as proof, so a lock left behind by a killed pacman kept the sanctioned
    window refreshed for ever and every hand edit after it read as drift.

    The lock is what makes a transaction, not the process. A live pacman with no
    lock is someone running `pacman -Q` -- an unprivileged query anyone can hold
    open in a loop -- and treating that as a transaction would hand out drift
    for free. The process check exists only to tell a stale lock from a slow one.
    """
    age = _age(pacman_lock, now if now is not None else time.time())
    if age is None:
        return False
    return age <= STALE_AFTER_SECONDS or transaction_alive(proc_dir)


def classify(window_marker, pacman_lock, now=None, proc_dir=PROC_DIR):
    now = time.time() if now is None else now
    if transaction_in_progress(pacman_lock, now, proc_dir):
        return "drift"
    marker_age = _age(window_marker, now)
    if marker_age is not None and marker_age <= STALE_AFTER_SECONDS:
        return "drift"
    return "breach"
