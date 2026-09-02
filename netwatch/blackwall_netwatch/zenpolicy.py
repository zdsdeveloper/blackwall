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
    policies = data.get("policies")
    return policies if isinstance(policies, dict) else {}


def render(package_policies):
    policies = dict(package_policies)
    policies.update(OURS)
    return json.dumps({"policies": policies}, indent=2, sort_keys=True) + "\n"


def apply(path, package_policies):
    desired = render(package_policies)
    try:
        with open(path) as f:
            if f.read() == desired:
                return False
    except OSError:
        pass
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, mode=0o755, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".netwatch-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(desired)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.rename(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return True
