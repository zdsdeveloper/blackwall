"""Was that change the package manager, or was it a pair of hands?

The operator updates through the Omarchy bar updater, which shells out to pacman
and yay. A package replacing a file we protect is routine and must be repaired in
silence. A hand edit is not. Getting this backwards -- punishing someone for
running a system update -- is the failure most likely to make this tool resented,
so both an explicit hook marker and pacman's own lock are consulted.
"""

import os
import time

# A transaction longer than this has crashed or been killed. Trusting the marker
# forever would leave breach detection silently disabled.
STALE_AFTER_SECONDS = 30 * 60


def classify(window_marker, pacman_lock, now=None):
    if os.path.exists(pacman_lock):
        return "drift"
    try:
        age = (now if now is not None else time.time()) - os.stat(window_marker).st_mtime
    except OSError:
        return "breach"
    return "drift" if age <= STALE_AFTER_SECONDS else "breach"
