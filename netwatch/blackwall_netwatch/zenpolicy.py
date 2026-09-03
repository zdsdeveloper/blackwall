"""Zen's enterprise policy file.

Zen is Firefox-based and its build sets MOZ_SYSTEM_POLICIES, so it reads
/etc/<app>/policies/policies.json in preference to the one shipped in the
install directory. Preference, not merge: whatever the package set is lost the
moment our file exists, so we carry it across.

Locking DoH off matters more than it sounds. With DNS-over-HTTPS active the
browser resolves through its own resolver and never consults /etc/hosts at all
-- the wall would look present and do nothing.
"""

import json
import os
import tempfile

OURS = {"DNSOverHTTPS": {"Enabled": False, "Locked": True}}


def read_package_policies(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    # A file that parses but is not an object is malformed input, not an error
    # to raise on: anything that escapes here takes down the enforcement loop,
    # and a daemon that will not start is a wall that is not up.
    if not isinstance(data, dict):
        return {}
    policies = data.get("policies")
    return policies if isinstance(policies, dict) else {}


def render(package_policies):
    policies = dict(package_policies)
    policies.update(OURS)
    return json.dumps({"policies": policies}, indent=2, sort_keys=True) + "\n"


def apply(path, package_policies):
    desired = render(package_policies)
    try:
        # errors="replace" and ValueError alongside OSError for the same reason
        # read_package_policies guards both: a file we are about to rewrite
        # anyway must never be able to abort the enforcement loop by being
        # unreadable. Anything that is not exactly `desired` gets rewritten.
        with open(path, encoding="utf-8", errors="replace") as f:
            if f.read() == desired:
                return False
    except (OSError, ValueError):
        pass
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, mode=0o755, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".netwatch-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(desired)
            # On the descriptor we already hold, not on the path: a path-based
            # chmod is a second lookup that a symlink planted in between could
            # redirect. Before the fsync, so the mode is durable with the data.
            os.fchmod(f.fileno(), 0o644)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, path)
        # O_DIRECTORY: without it this would silently fsync a regular file if
        # `directory` ever turned out not to be one, and the rename would not
        # actually be on disk.
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        # Guarded in its own right: an unlink that raises here would replace the
        # real failure with a stray OSError about a temp file nobody asked
        # about, and the reason enforcement broke would be lost.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True
