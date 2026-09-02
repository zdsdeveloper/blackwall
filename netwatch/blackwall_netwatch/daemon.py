"""The wall itself.

Enforcement is a repair loop, not an event handler: whatever the file says, make
it say the right thing again. That means a change made while the daemon was
stopped is caught the moment it starts, and it means there is no edit-detection
race to lose.
"""

import dataclasses
import os
import subprocess

from . import blocklist, hosts, ledger, provenance, zenpolicy


@dataclasses.dataclass(frozen=True)
class Paths:
    blocklist: str
    ledger: str
    hosts: str
    zen_policy: str
    zen_package_policy: str
    window_marker: str
    pacman_lock: str
    socket: str


def flush_resolver_cache():
    """systemd-resolved answers from cache, so a name blocked a moment ago can
    keep resolving until its TTL runs out -- exactly when the block is wanted.

    Best effort by design: on a machine not running resolved this is a no-op,
    and a failure here must never be louder than the enforcement it follows.
    """
    try:
        subprocess.run(
            ["resolvectl", "flush-caches"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


class NetWatch:
    def __init__(self, paths, flusher=flush_resolver_cache):
        self.paths = paths
        self.flusher = flusher

    def domains(self):
        try:
            with open(self.paths.blocklist) as f:
                return blocklist.parse(f.read())
        except OSError:
            return []

    def add(self, raw):
        domain = blocklist.normalize(raw)
        if domain not in self.domains():
            fd = os.open(
                self.paths.blocklist,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
                0o644,
            )
            try:
                os.write(fd, (domain + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            ledger.record(self.paths.ledger, "added", domain=domain)
        return domain

    def enforce(self):
        domains = self.domains()
        targets = []
        if hosts.apply(self.paths.hosts, domains):
            targets.append("hosts")
            self.flusher()
        package = zenpolicy.read_package_policies(self.paths.zen_package_policy)
        if zenpolicy.apply(self.paths.zen_policy, package):
            targets.append("zen_policy")
        if not targets:
            return {"changed": False, "verdict": None, "targets": []}
        if self._enforced_before():
            verdict = provenance.classify(
                self.paths.window_marker, self.paths.pacman_lock
            )
        else:
            verdict = "init"
        ledger.record(self.paths.ledger, verdict, targets=targets)
        return {"changed": True, "verdict": verdict, "targets": targets}

    def _enforced_before(self):
        # The ledger is the record of whether this machine has ever been in a
        # good state. It is append-only and root-owned, so answering this
        # question dishonestly costs more than the answer is worth.
        return any(
            e.get("kind") in ("init", "drift", "breach")
            for e in ledger.read(self.paths.ledger)
        )

    def status(self):
        entries = ledger.read(self.paths.ledger)
        return {
            "domains": len(self.domains()),
            "breaches": len([e for e in entries if e["kind"] == "breach"]),
            "armed": os.path.exists(self.paths.blocklist),
        }
