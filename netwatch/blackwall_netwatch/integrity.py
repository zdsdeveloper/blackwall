"""Is the wall weaker than it should be?

Phase 1 escalated whenever a managed file's text changed, which meant an
unrelated line in /etc/hosts read as tampering. The question that actually
matters is narrower: is a protection we put in place now missing? Everything
else is repaired in silence.
"""

import json
import os

from . import hosts


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def missing_sinks(hosts_path, domains):
    """Expected sink lines that are not present anywhere in the file.

    The whole file, not just our managed region. What matters is whether the
    block is in effect, and a sink line works wherever it sits -- so a line the
    operator wrote themselves counts, and a duplicate region carrying the right
    lines is a redundant copy rather than a decoy. Asking only about our own
    region would mean a reader that has to agree with the writer about where
    the region is, and that agreement is one more thing to get wrong.
    """
    text = _read(hosts_path)
    if text is None:
        return list(hosts.expected_lines(domains))
    present = set(line.strip() for line in text.splitlines())
    return [line for line in hosts.expected_lines(domains) if line not in present]


def doh_locked(policy_path):
    text = _read(policy_path)
    if text is None:
        return False
    try:
        data = json.loads(text)
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    policies = data.get("policies")
    if not isinstance(policies, dict):
        return False
    return policies.get("DNSOverHTTPS") == {"Enabled": False, "Locked": True}


def unit_intact(unit_path, source_path):
    """Is the installed unit present, unmasked, and what we installed?

    Masking is the quiet way to take the daemon down: the unit becomes a symlink
    to /dev/null and systemd simply never starts it again.
    """
    source = _read(source_path)
    if source is None:
        # Nothing to compare against is not evidence of tampering.
        return True
    if os.path.islink(unit_path):
        return False
    text = _read(unit_path)
    if text is None:
        return False
    return text == source


def weakened(hosts_path, domains, policy_path, unit_path, unit_source):
    """Reasons the wall is weaker than it should be. Empty means intact."""
    reasons = []
    missing = missing_sinks(hosts_path, domains)
    if missing:
        reasons.append("hosts: %d of %d sink lines missing (%s)" % (
            len(missing), len(hosts.expected_lines(domains)), missing[0]))
    if not doh_locked(policy_path):
        reasons.append("zen policy: DNS-over-HTTPS is not locked off")
    if not unit_intact(unit_path, unit_source):
        reasons.append("unit: missing, masked or altered")
    return reasons
