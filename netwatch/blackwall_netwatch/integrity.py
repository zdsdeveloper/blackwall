"""Is the wall weaker than it should be?

Phase 1 escalated whenever a managed file's text changed, which meant an
unrelated line in /etc/hosts read as tampering. The question that actually
matters is narrower: is a protection we put in place now missing? Everything
else is repaired in silence.
"""

import json
import os

from . import blocklist, hosts


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, ValueError):
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
    doh = policies.get("DNSOverHTTPS")
    if not isinstance(doh, dict):
        return False
    # The two fields we care about, not the whole object. A future Zen adding a
    # third key inside DNSOverHTTPS would fail an equality check even with DoH
    # still locked off -- and that is a screen lock for a browser update.
    return doh.get("Enabled") is False and doh.get("Locked") is True


def _has_dropins(unit_path):
    """Is there a drop-in beside this unit?

    A file in <unit>.d/ overrides directives without the unit itself changing by
    a single byte, which makes it the quiet way to repoint a service. We install
    none, so any that exists is one we did not put there.
    """
    try:
        names = os.listdir(unit_path + ".d")
    except (OSError, ValueError):
        return False
    return any(name.endswith(".conf") for name in names)


def unit_intact(unit_path, source_path):
    """Is the installed unit present, unmasked, unmodified and unoverridden?

    Masking is the quiet way to stop the daemon: the unit becomes a symlink to
    /dev/null and systemd never starts it again.
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
    # Trailing newlines only. A re-save or `systemctl edit` can add or drop the
    # final newline without changing a directive, and locking someone out over
    # that would be the tool punishing a no-op. Nothing can hide in it.
    if text.rstrip("\n") != source.rstrip("\n"):
        return False
    return not _has_dropins(unit_path)


def promised_domains(entries):
    """Every domain the ledger says was added.

    The blocklist is the daemon's working copy; this is the record. Nothing
    removes a domain because there is no removal, so a domain that was added and
    is no longer in the blocklist did not leave by any route the daemon offers.
    """
    promised = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("kind") != "added":
            continue
        domain = entry.get("domain")
        if not isinstance(domain, str) or not domain:
            continue
        # Normalised on the way out rather than trusted as written. An entry
        # recorded under an older normalisation can be a domain this one would
        # never produce, and a promise that cannot be satisfied is a breach
        # filed every cycle for ever -- a lock inside the first minute.
        try:
            promised.add(blocklist.normalize(domain))
        except blocklist.InvalidDomain:
            continue
    return promised


def unblocked_domains(entries, domains):
    """Promised domains that are no longer in the blocklist."""
    return sorted(promised_domains(entries) - set(domains))


def weakened(hosts_path, domains, policy_path, unit_path, unit_source,
             ledger_entries=()):
    """Reasons the wall is weaker than it should be. Empty means intact."""
    reasons = []
    removed = unblocked_domains(ledger_entries, domains)
    if removed:
        reasons.append("blocklist: %d domain(s) removed (%s)" % (
            len(removed), removed[0]))
    missing = missing_sinks(hosts_path, domains)
    if missing:
        reasons.append("hosts: %d of %d sink lines missing (%s)" % (
            len(missing), len(hosts.expected_lines(domains)), missing[0]))
    if not doh_locked(policy_path):
        reasons.append("zen policy: DNS-over-HTTPS is not locked off")
    if not unit_intact(unit_path, unit_source):
        reasons.append("unit: missing, masked or altered")
    return reasons
