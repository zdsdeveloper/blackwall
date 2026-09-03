# NetWatch Phase 2a — Escalation Ladder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A breach — meaning the wall was actually made weaker — draws a typed-phrase challenge, and a second one within the window locks the screen.

**Architecture:** Breach detection moves from "the file text changed" to "an expected protection is missing", computed before any repair. A new `integrity` module answers that question, a `ladder` module picks the rung, and a `session` module reaches the user's Quickshell over the IPC it already exposes. The daemon injects the notifier the way it already injects the resolver flusher, so the ladder is testable without a running shell.

**Tech Stack:** Python 3.14 stdlib only, QML/Quickshell, systemd, unittest.

**Spec:** `docs/superpowers/specs/2026-09-02-netwatch-phase2-design.md`

## Global Constraints

- Branch is `netwatch`. Never commit to `master` — it is the marketplace v1 and Phase 2 must not reach it.
- Python 3 stdlib only. No pip, no new packages.
- Every module takes explicit paths and injected callables. Nothing hardcodes a real system path at import time except a documented default; tests run against a tmpdir without root.
- Tests run with `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v` from the repo root. The `-t netwatch` form fails on Python 3.14. No `__init__.py` in `netwatch/tests/` or `netwatch/`.
- **No file the daemon reads may raise out of the read.** Malformed, missing or unreadable input is treated as absent input. Six defects in Phase 1 came from violating this.
- **Tests must not touch real system state, run real subprocesses, or open real sockets.** The suite must finish in under two seconds. A Phase 1 task shipped tests that shelled out and took 32 seconds.
- No README section, comment, docstring or help text explains how to stop, disable, mask or bypass NetWatch.
- The ladder fires **only on a newly recorded breach**, never on a standing one, and never on the daemon's first enforcement after start.
- Verdicts `init`, `applied`, `drift` and `repair` never escalate. Only `breach`.
- The current suite is **130 tests**. Every one must still pass unless a task deliberately changes behaviour, in which case say so.

---

### Task 1: Expected sink lines, and a region that stays put

**Files:**
- Modify: `netwatch/blackwall_netwatch/hosts.py`
- Test: `netwatch/tests/test_hosts.py`

**Interfaces:**
- Consumes: nothing
- Produces: `expected_lines(domains: list[str]) -> list[str]`, `region_lines(current: str) -> list[str]`, and a `splice(current, block)` that keeps the managed region where it already is

Why the position matters: `splice` currently rebuilds the file with the region at the end, so an unrelated appended line moves and the text differs. That churn is what made an ordinary `/etc/hosts` edit look like tampering.

- [ ] **Step 1: Write the failing test**

```python
class TestExpectedLines(unittest.TestCase):
    def test_four_lines_per_domain_in_render_order(self):
        self.assertEqual(hosts.expected_lines(["a.com"]), [
            "0.0.0.0 a.com", ":: a.com",
            "0.0.0.0 www.a.com", ":: www.a.com",
        ])

    def test_render_contains_exactly_the_expected_lines(self):
        rendered = hosts.render(["a.com", "b.com"])
        for line in hosts.expected_lines(["a.com", "b.com"]):
            self.assertIn(line, rendered)


class TestRegionLines(unittest.TestCase):
    def test_returns_only_what_is_inside_the_markers(self):
        text = hosts.splice(STOCK, hosts.render(["a.com"]))
        inside = hosts.region_lines(text)
        self.assertIn("0.0.0.0 a.com", inside)
        self.assertNotIn("127.0.0.1 localhost", inside)

    def test_absent_region_is_empty_not_an_error(self):
        self.assertEqual(hosts.region_lines(STOCK), [])


class TestSpliceKeepsPosition(unittest.TestCase):
    def test_an_entry_added_after_the_region_stays_after_it(self):
        once = hosts.splice(STOCK, hosts.render(["a.com"]))
        edited = once + "10.0.0.9 later\n"
        out = hosts.splice(edited, hosts.render(["a.com"]))
        self.assertLess(out.index(hosts.END), out.index("10.0.0.9 later"))

    def test_an_unrelated_edit_after_the_region_changes_nothing_else(self):
        once = hosts.splice(STOCK, hosts.render(["a.com"]))
        edited = once + "10.0.0.9 later\n"
        self.assertEqual(hosts.splice(edited, hosts.render(["a.com"])), edited)

    def test_still_idempotent(self):
        once = hosts.splice(STOCK, hosts.render(["a.com"]))
        self.assertEqual(hosts.splice(once, hosts.render(["a.com"])), once)

    def test_appends_when_absent(self):
        out = hosts.splice(STOCK, hosts.render(["a.com"]))
        self.assertIn("127.0.0.1 localhost", out)
        self.assertIn("0.0.0.0 a.com", out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: FAIL with `AttributeError: module 'blackwall_netwatch.hosts' has no attribute 'expected_lines'`

- [ ] **Step 3: Write minimal implementation**

Replace `render` and `splice`, and add the two new functions:

```python
def expected_lines(domains):
    """Every line the managed region must contain, in render order.

    The single definition of what "blocked" looks like on disk. The renderer
    writes these and the integrity check looks for them; if the two ever
    disagreed, the wall would report itself intact while missing entries.
    """
    lines = []
    for d in domains:
        for host in (d, "www." + d):
            lines.append("%s %s" % (SINK4, host))
            lines.append("%s %s" % (SINK6, host))
    return lines


def render(domains):
    return "\n".join([BEGIN] + expected_lines(domains) + [END])


def region_lines(current):
    """The lines inside the markers, or empty if there is no complete region."""
    lines = current.splitlines()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == BEGIN:
            start = i
        elif stripped == END and start is not None:
            return lines[start + 1:i]
    return []


def splice(current, block):
    """Replace the managed region in place, leaving everything else where it is.

    In place matters: rebuilding the file with the region at the end moved any
    line written after it, so an ordinary edit to /etc/hosts produced a diff and
    read as tampering.
    """
    lines = current.splitlines()
    doomed = _doomed_lines(lines)
    kept = [line for i, line in enumerate(lines) if i not in doomed]
    if doomed:
        at = min(doomed)
        insert = sum(1 for i in range(at) if i not in doomed)
    else:
        insert = len(kept)
    head = "\n".join(kept[:insert]).rstrip("\n")
    tail = "\n".join(kept[insert:]).strip("\n")
    parts = [p for p in (head, block, tail) if p]
    return "\n\n".join(parts) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: PASS. Report the total; every pre-existing hosts test must still pass.

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/hosts.py netwatch/tests/test_hosts.py
git commit -m "netwatch: expected sink lines, and a managed region that stays put"
```

---

### Task 2: Integrity — is the wall weaker than it should be?

**Files:**
- Create: `netwatch/blackwall_netwatch/integrity.py`
- Test: `netwatch/tests/test_integrity.py`

**Interfaces:**
- Consumes: `hosts.expected_lines`
- Produces: `missing_sinks(hosts_path, domains) -> list[str]`, `doh_locked(policy_path) -> bool`, `unit_intact(unit_path, source_path) -> bool`, `weakened(hosts_path, domains, policy_path, unit_path, unit_source) -> list[str]` (reasons; empty means intact)

- [ ] **Step 1: Write the failing test**

```python
import json
import os
import tempfile
import unittest
from blackwall_netwatch import hosts, integrity


class TestWeakened(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.hosts = os.path.join(self.dir, "hosts")
        self.policy = os.path.join(self.dir, "policies.json")
        self.unit = os.path.join(self.dir, "unit.service")
        self.source = os.path.join(self.dir, "unit.source")
        with open(self.hosts, "w") as f:
            f.write(hosts.splice("127.0.0.1 localhost\n", hosts.render(["a.com"])))
        with open(self.policy, "w") as f:
            json.dump({"policies": {"DNSOverHTTPS": {"Enabled": False, "Locked": True}}}, f)
        for path in (self.unit, self.source):
            with open(path, "w") as f:
                f.write("[Service]\nExecStart=/usr/local/bin/blackwall-netwatch\n")

    def reasons(self):
        return integrity.weakened(self.hosts, ["a.com"], self.policy,
                                  self.unit, self.source)

    def test_an_intact_wall_has_no_reasons(self):
        self.assertEqual(self.reasons(), [])

    def test_an_unrelated_hosts_entry_is_not_a_weakening(self):
        # The whole point of the change: adding a dev host is not tampering.
        with open(self.hosts, "a") as f:
            f.write("10.0.0.9 my-dev-box.local\n")
        self.assertEqual(self.reasons(), [])

    def test_a_sink_line_the_operator_wrote_themselves_counts(self):
        # What matters is whether the block is in effect, not whose line it is.
        text = open(self.hosts).read().replace("0.0.0.0 a.com\n", "")
        with open(self.hosts, "w") as f:
            f.write("0.0.0.0 a.com\n" + text)
        self.assertEqual(self.reasons(), [])

    def test_a_missing_sink_line_is_a_weakening(self):
        text = open(self.hosts).read().replace("0.0.0.0 a.com\n", "")
        with open(self.hosts, "w") as f:
            f.write(text)
        self.assertTrue(any("a.com" in r for r in self.reasons()))

    def test_the_whole_region_gone_is_a_weakening(self):
        with open(self.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.assertTrue(self.reasons())

    def test_doh_unlocked_is_a_weakening(self):
        with open(self.policy, "w") as f:
            json.dump({"policies": {"DNSOverHTTPS": {"Enabled": True, "Locked": False}}}, f)
        self.assertTrue(any("DNS" in r or "DoH" in r for r in self.reasons()))

    def test_a_missing_policy_file_is_a_weakening(self):
        os.unlink(self.policy)
        self.assertTrue(self.reasons())

    def test_a_malformed_policy_file_is_a_weakening_not_a_crash(self):
        with open(self.policy, "w") as f:
            f.write("{ not json")
        self.assertTrue(self.reasons())

    def test_a_masked_unit_is_a_weakening(self):
        os.unlink(self.unit)
        os.symlink("/dev/null", self.unit)
        self.assertTrue(any("unit" in r for r in self.reasons()))

    def test_an_edited_unit_is_a_weakening(self):
        with open(self.unit, "a") as f:
            f.write("# tampered\n")
        self.assertTrue(any("unit" in r for r in self.reasons()))

    def test_a_missing_unit_is_a_weakening(self):
        os.unlink(self.unit)
        self.assertTrue(any("unit" in r for r in self.reasons()))

    def test_an_absent_source_copy_is_not_a_weakening(self):
        # Nothing to compare against is not evidence of tampering.
        os.unlink(self.source)
        self.assertEqual(self.reasons(), [])

    def test_no_domains_no_sink_reasons(self):
        self.assertEqual(
            integrity.weakened(self.hosts, [], self.policy, self.unit, self.source), [])

    def test_an_unreadable_hosts_file_is_a_weakening_not_a_crash(self):
        os.unlink(self.hosts)
        self.assertTrue(self.reasons())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: FAIL with `ImportError: cannot import name 'integrity'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: PASS, 13 new tests.

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/integrity.py netwatch/tests/test_integrity.py
git commit -m "netwatch: weakened-wall detection"
```

---

### Task 3: The session bridge

**Files:**
- Create: `netwatch/blackwall_netwatch/session.py`
- Test: `netwatch/tests/test_session.py`

**Interfaces:**
- Consumes: nothing
- Produces: `find_shell_pid(proc_dir=PROC_DIR) -> int | None`, `runtime_dir_of(pid, proc_dir=PROC_DIR) -> str | None`, `notify(method, args=(), proc_dir=PROC_DIR, runner=subprocess.run) -> bool`

Verified 2026-09-02: as root, `qs ipc --pid <pid> call blackwall status` with `XDG_RUNTIME_DIR` set returns the live status. `--pid` rather than display matching, so the daemon discovers its target rather than being configured with one.

- [ ] **Step 1: Write the failing test**

```python
import os
import tempfile
import unittest
from blackwall_netwatch import session


def fake_proc(entries):
    """entries: {pid: (comm, environ_bytes)}"""
    d = tempfile.mkdtemp()
    for pid, (comm, environ) in entries.items():
        p = os.path.join(d, str(pid))
        os.makedirs(p)
        with open(os.path.join(p, "comm"), "w") as f:
            f.write(comm + "\n")
        with open(os.path.join(p, "cmdline"), "wb") as f:
            f.write(b"quickshell\x00-p\x00/usr/share/omarchy/shell\x00")
        with open(os.path.join(p, "environ"), "wb") as f:
            f.write(environ)
    return d


ENV = b"HOME=/home/zds\x00XDG_RUNTIME_DIR=/run/user/1000\x00LANG=C\x00"


class TestFindShellPid(unittest.TestCase):
    def test_finds_the_quickshell_process(self):
        proc = fake_proc({1214: ("quickshell", ENV)})
        self.assertEqual(session.find_shell_pid(proc), 1214)

    def test_returns_none_when_no_shell_is_running(self):
        proc = fake_proc({7: ("bash", ENV)})
        self.assertIsNone(session.find_shell_pid(proc))

    def test_missing_proc_is_none_not_a_crash(self):
        self.assertIsNone(session.find_shell_pid("/nonexistent"))


class TestRuntimeDir(unittest.TestCase):
    def test_reads_it_out_of_environ(self):
        proc = fake_proc({1214: ("quickshell", ENV)})
        self.assertEqual(session.runtime_dir_of(1214, proc), "/run/user/1000")

    def test_absent_variable_is_none(self):
        proc = fake_proc({1214: ("quickshell", b"HOME=/home/zds\x00")})
        self.assertIsNone(session.runtime_dir_of(1214, proc))

    def test_unreadable_environ_is_none_not_a_crash(self):
        self.assertIsNone(session.runtime_dir_of(99999, "/nonexistent"))


class TestNotify(unittest.TestCase):
    def test_builds_the_expected_command(self):
        proc = fake_proc({1214: ("quickshell", ENV)})
        seen = {}

        def runner(argv, **kwargs):
            seen["argv"] = argv
            seen["env"] = kwargs.get("env")
            class R:
                returncode = 0
            return R()

        self.assertTrue(session.notify("engage", ["1200"], proc_dir=proc, runner=runner))
        self.assertEqual(seen["argv"][:5],
                         ["qs", "ipc", "--pid", "1214", "call"])
        self.assertEqual(seen["argv"][5:], ["blackwall", "engage", "1200"])
        self.assertEqual(seen["env"]["XDG_RUNTIME_DIR"], "/run/user/1000")

    def test_no_session_is_false_not_a_crash(self):
        # Logged out: there is nothing to lock, and the breach stays
        # unacknowledged so the plugin picks it up at next start.
        proc = fake_proc({7: ("bash", ENV)})
        self.assertFalse(session.notify("engage", ["1200"], proc_dir=proc,
                                        runner=lambda *a, **k: None))

    def test_a_failing_runner_is_false_not_a_crash(self):
        proc = fake_proc({1214: ("quickshell", ENV)})

        def runner(argv, **kwargs):
            raise OSError("qs not found")

        self.assertFalse(session.notify("engage", ["1200"], proc_dir=proc, runner=runner))

    def test_a_nonzero_exit_is_false(self):
        proc = fake_proc({1214: ("quickshell", ENV)})

        def runner(argv, **kwargs):
            class R:
                returncode = 1
            return R()

        self.assertFalse(session.notify("engage", ["1200"], proc_dir=proc, runner=runner))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: FAIL with `ImportError: cannot import name 'session'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Reaching the user's shell from a root daemon.

This looked like it needed a privilege bridge -- a root-written file the plugin
watches, or a relay service in the session. It does not: root bypasses the
permission bits on the session's runtime directory, so the daemon can speak the
IPC the plugin already exposes. Verified on this machine before it was designed
around.

The target is found by pid rather than by display, so a different uid, a
restarted shell or a changed display does not break it.
"""

import os
import subprocess

PROC_DIR = "/proc"

SHELL_MARKER = "/usr/share/omarchy/shell"
SHELL_COMMS = ("quickshell", "qs")

IPC_TARGET = "blackwall"

TIMEOUT_SECONDS = 5


def _read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def find_shell_pid(proc_dir=PROC_DIR):
    """The pid of the Quickshell process running the Omarchy shell, if any."""
    try:
        entries = os.listdir(proc_dir)
    except (OSError, ValueError):
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        comm = _read_bytes(os.path.join(proc_dir, entry, "comm"))
        if comm is None or comm.decode("utf-8", "replace").strip() not in SHELL_COMMS:
            continue
        cmdline = _read_bytes(os.path.join(proc_dir, entry, "cmdline")) or b""
        if SHELL_MARKER.encode("utf-8") in cmdline:
            return int(entry)
    return None


def runtime_dir_of(pid, proc_dir=PROC_DIR):
    """XDG_RUNTIME_DIR as that process sees it."""
    raw = _read_bytes(os.path.join(proc_dir, str(pid), "environ"))
    if raw is None:
        return None
    for item in raw.split(b"\x00"):
        if item.startswith(b"XDG_RUNTIME_DIR="):
            return item.split(b"=", 1)[1].decode("utf-8", "replace")
    return None


def notify(method, args=(), proc_dir=PROC_DIR, runner=subprocess.run):
    """Call a method on the plugin's IPC. True if it landed.

    False is an ordinary outcome, not an error: when nobody is logged in there
    is no screen to lock, and the breach simply stays unacknowledged until the
    plugin asks about it at next start.
    """
    pid = find_shell_pid(proc_dir)
    if pid is None:
        return False
    runtime = runtime_dir_of(pid, proc_dir)
    if runtime is None:
        return False
    argv = ["qs", "ipc", "--pid", str(pid), "call", IPC_TARGET, method]
    argv.extend(str(a) for a in args)
    env = dict(os.environ)
    env["XDG_RUNTIME_DIR"] = runtime
    try:
        result = runner(
            argv,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except Exception:
        return False
    return getattr(result, "returncode", 1) == 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: PASS, 9 new tests. No real subprocess runs — every test injects `runner`.

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/session.py netwatch/tests/test_session.py
git commit -m "netwatch: reach the session's IPC from the daemon"
```

---

### Task 4: The ladder

**Files:**
- Create: `netwatch/blackwall_netwatch/ladder.py`
- Test: `netwatch/tests/test_ladder.py`

**Interfaces:**
- Consumes: nothing (takes ledger entries as data)
- Produces: `CHALLENGE = "challenge"`, `LOCK = "lock"`, `WINDOW_SECONDS = 6 * 60 * 60`, `LOCK_SECONDS = 20 * 60`, `unacknowledged(entries, now=None, window=WINDOW_SECONDS) -> int`, `rung(entries, now=None, window=WINDOW_SECONDS) -> str`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from blackwall_netwatch import ladder

NOW = 1_000_000.0


def e(kind, at):
    return {"kind": kind, "at": at}


class TestUnacknowledged(unittest.TestCase):
    def test_none_when_empty(self):
        self.assertEqual(ladder.unacknowledged([], now=NOW), 0)

    def test_counts_breaches_in_the_window(self):
        entries = [e("breach", NOW - 60), e("breach", NOW - 30)]
        self.assertEqual(ladder.unacknowledged(entries, now=NOW), 2)

    def test_ignores_breaches_older_than_the_window(self):
        entries = [e("breach", NOW - ladder.WINDOW_SECONDS - 1), e("breach", NOW - 5)]
        self.assertEqual(ladder.unacknowledged(entries, now=NOW), 1)

    def test_an_ack_clears_everything_before_it(self):
        entries = [e("breach", NOW - 300), e("ack", NOW - 200), e("breach", NOW - 100)]
        self.assertEqual(ladder.unacknowledged(entries, now=NOW), 1)

    def test_other_kinds_do_not_count(self):
        entries = [e("drift", NOW - 10), e("applied", NOW - 9), e("repair", NOW - 8),
                   e("init", NOW - 7)]
        self.assertEqual(ladder.unacknowledged(entries, now=NOW), 0)

    def test_an_entry_without_a_timestamp_is_skipped_not_fatal(self):
        self.assertEqual(ladder.unacknowledged([{"kind": "breach"}], now=NOW), 0)


class TestRung(unittest.TestCase):
    def test_first_breach_challenges(self):
        self.assertEqual(ladder.rung([e("breach", NOW)], now=NOW), ladder.CHALLENGE)

    def test_second_breach_locks(self):
        entries = [e("breach", NOW - 60), e("breach", NOW)]
        self.assertEqual(ladder.rung(entries, now=NOW), ladder.LOCK)

    def test_third_also_locks(self):
        entries = [e("breach", NOW - 90), e("breach", NOW - 60), e("breach", NOW)]
        self.assertEqual(ladder.rung(entries, now=NOW), ladder.LOCK)

    def test_an_ack_between_them_drops_back_to_challenge(self):
        # Answering rung 1 is what clears it. Ignoring it is not.
        entries = [e("breach", NOW - 300), e("ack", NOW - 200), e("breach", NOW)]
        self.assertEqual(ladder.rung(entries, now=NOW), ladder.CHALLENGE)

    def test_a_breach_outside_the_window_does_not_stack(self):
        entries = [e("breach", NOW - ladder.WINDOW_SECONDS - 1), e("breach", NOW)]
        self.assertEqual(ladder.rung(entries, now=NOW), ladder.CHALLENGE)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: FAIL with `ImportError: cannot import name 'ladder'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: PASS, 11 new tests.

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/ladder.py netwatch/tests/test_ladder.py
git commit -m "netwatch: rung selection"
```

---

### Task 5: Wire the daemon to weakening and the ladder

**Files:**
- Modify: `netwatch/blackwall_netwatch/daemon.py`
- Modify: `netwatch/bin/blackwall-netwatch`
- Test: `netwatch/tests/test_daemon.py`

**Interfaces:**
- Consumes: `integrity.weakened`, `ladder.rung`, `ladder.CHALLENGE`, `ladder.LOCK`, `ladder.LOCK_SECONDS`, `session.notify`
- Produces: `Paths` gains `unit_file` and `unit_source`; `NetWatch(paths, flusher=..., proc_dir=..., notifier=session.notify)`; `enforce()` may now return verdict `"repair"`

The behaviour change: a change that does not weaken the wall records `repair` and never escalates. Only a weakening can become `breach`, and only a newly recorded `breach` fires the ladder — never a standing one, and never the first enforcement after start.

- [ ] **Step 1: Write the failing test**

Add to `test_daemon.py`. `paths_in` gains the two new fields; update the existing helper and add `unit`/`source` files in `setUp` so the wall starts intact.

```python
class TestWeakeningAndLadder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = paths_in(self.dir)
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        for path in (self.paths.unit_file, self.paths.unit_source):
            with open(path, "w") as f:
                f.write("[Service]\n")
        self.calls = []
        self.nw = NetWatch(self.paths, flusher=lambda: None,
                           proc_dir=self.empty_proc(),
                           notifier=lambda m, a=(): self.calls.append((m, list(a))) or True)

    def empty_proc(self):
        p = os.path.join(self.dir, "proc")
        os.makedirs(os.path.join(p, "1"), exist_ok=True)
        with open(os.path.join(p, "1", "comm"), "w") as f:
            f.write("bash\n")
        return p

    def settle(self):
        self.nw.add("a.com")
        self.nw.enforce()          # init
        self.nw.enforce()          # quiet
        self.calls.clear()

    def test_an_unrelated_hosts_edit_is_a_repair_not_a_breach(self):
        self.settle()
        with open(self.paths.hosts, "a") as f:
            f.write("10.0.0.9 my-dev-box.local\n")
        result = self.nw.enforce()
        self.assertIn(result["verdict"], (None, "repair"))
        self.assertEqual(self.calls, [])

    def test_a_removed_sink_line_is_a_breach_and_challenges(self):
        self.settle()
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        result = self.nw.enforce()
        self.assertEqual(result["verdict"], "breach")
        self.assertEqual(self.calls, [("challenge", [result["reasons"][0]])])

    def test_a_second_breach_locks(self):
        self.settle()
        for _ in range(2):
            with open(self.paths.hosts, "w") as f:
                f.write("127.0.0.1 localhost\n")
            self.nw.enforce()
        self.assertEqual(self.calls[-1][0], "engage")
        self.assertEqual(self.calls[-1][1], [str(ladder.LOCK_SECONDS)])

    def test_a_masked_unit_is_a_breach(self):
        self.settle()
        os.unlink(self.paths.unit_file)
        os.symlink("/dev/null", self.paths.unit_file)
        self.assertEqual(self.nw.enforce()["verdict"], "breach")

    def test_the_first_enforcement_after_start_never_escalates(self):
        # A restart mid-transaction used to look like tampering. In Phase 2 that
        # is a lockout for rebooting.
        self.settle()
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        fresh = NetWatch(self.paths, flusher=lambda: None, proc_dir=self.empty_proc(),
                         notifier=lambda m, a=(): self.calls.append((m, list(a))) or True)
        fresh.enforce()
        self.assertEqual(self.calls, [])

    def test_a_standing_breach_does_not_re_fire_the_ladder(self):
        # Otherwise an unanswered challenge reappears every cycle until the
        # operator kills the shell to stop it.
        self.settle()
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.nw.enforce()
        before = len(self.calls)
        self.nw.enforce()
        self.nw.enforce()
        self.assertEqual(len(self.calls), before)

    def test_drift_never_escalates(self):
        self.settle()
        with open(self.paths.window_marker, "w") as f:
            f.write("")
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.assertEqual(self.nw.enforce()["verdict"], "drift")
        self.assertEqual(self.calls, [])

    def test_a_notifier_that_fails_does_not_break_enforcement(self):
        self.settle()
        nw = NetWatch(self.paths, flusher=lambda: None, proc_dir=self.empty_proc(),
                      notifier=lambda m, a=(): (_ for _ in ()).throw(OSError("no session")))
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.assertEqual(nw.enforce()["verdict"], "breach")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: FAIL — `Paths` has no field `unit_file`.

- [ ] **Step 3: Write minimal implementation**

Add the two `Paths` fields after `pacman_lock`:

```python
    unit_file: str
    unit_source: str
```

Add to `__init__`: `notifier=session.notify` stored as `self.notifier`, and `self._first_enforcement = True`.

Replace the verdict half of `enforce()`:

```python
        reasons = integrity.weakened(
            self.paths.hosts, domains, self.paths.zen_policy,
            self.paths.unit_file, self.paths.unit_source)
```

placed **before** the two `apply` calls, and the tail of the method:

```python
        first = self._first_enforcement
        self._first_enforcement = False
        applied = self._applied_pending
        self._applied_pending = False
        if not self._enforced_before():
            verdict = "init"
        elif applied:
            verdict = "applied"
        elif not reasons:
            # Something changed but no protection was missing: an unrelated
            # edit, a reordering. Repaired, recorded, never punished.
            verdict = "repair"
        else:
            verdict = provenance.classify(
                self.paths.window_marker, self.paths.pacman_lock,
                proc_dir=self.proc_dir)
        ledger.record(self.paths.ledger, verdict, targets=targets, reasons=reasons)
        if verdict == "breach" and not first:
            self._escalate(reasons)
        return {"changed": True, "verdict": verdict, "targets": targets,
                "reasons": reasons}
```

And the escalation itself:

```python
    def _escalate(self, reasons):
        """Fire the ladder for a breach just recorded.

        Only for a NEW breach: a standing one must not re-fire every cycle, or
        an unanswered challenge reappears every thirty seconds until the
        operator kills the shell to stop it -- which teaches them that killing
        the shell is how you deal with the Blackwall.
        """
        entries = ledger.read(self.paths.ledger)
        step = ladder.rung(entries)
        try:
            if step == ladder.LOCK:
                self.notifier("engage", [str(ladder.LOCK_SECONDS)])
            else:
                self.notifier("challenge", [reasons[0] if reasons else "breach"])
        except Exception:
            # No session, no qs, no screen to lock. The breach stays
            # unacknowledged and the plugin picks it up when it next starts.
            pass
```

Import `integrity`, `ladder` and `session` at the top of `daemon.py`.

In `netwatch/bin/blackwall-netwatch`, add to the `Paths(...)` literal:

```python
    unit_file="/etc/systemd/system/blackwall-netwatch.service",
    unit_source="/usr/local/lib/blackwall-netwatch/blackwall-netwatch.service",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: PASS. Existing daemon tests that asserted `breach` for a text-only change now expect `repair` — update those and say which in your report.

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/daemon.py netwatch/bin/blackwall-netwatch netwatch/tests/test_daemon.py
git commit -m "netwatch: escalate only when the wall was actually weakened"
```

---

### Task 6: `ack`, and status that reports the ladder

**Files:**
- Modify: `netwatch/blackwall_netwatch/server.py`
- Modify: `netwatch/blackwall_netwatch/daemon.py` (`status`)
- Modify: `netwatch/bin/netwatchctl`
- Test: `netwatch/tests/test_server.py`

**Interfaces:**
- Consumes: `ladder.unacknowledged`, `integrity.weakened`
- Produces: socket command `{"cmd": "ack"}`; `status()` gains `unacknowledged: int` and `weakened: list[str]`; `netwatchctl ack`

- [ ] **Step 1: Write the failing test**

```python
class TestAck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = paths_in(self.dir)
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        for path in (self.paths.unit_file, self.paths.unit_source):
            with open(path, "w") as f:
                f.write("[Service]\n")
        self.nw = NetWatch(self.paths, flusher=lambda: None,
                           notifier=lambda m, a=(): True)

    def test_ack_records_an_entry(self):
        reply = handle(self.nw, {"cmd": "ack"})
        self.assertTrue(reply["ok"])
        self.assertIn("ack", [e["kind"] for e in ledger.read(self.paths.ledger)])

    def test_ack_clears_the_unacknowledged_count(self):
        ledger.record(self.paths.ledger, "breach", targets=["hosts"])
        self.assertEqual(handle(self.nw, {"cmd": "status"})["unacknowledged"], 1)
        handle(self.nw, {"cmd": "ack"})
        self.assertEqual(handle(self.nw, {"cmd": "status"})["unacknowledged"], 0)

    def test_ack_needs_no_root(self):
        # The plugin runs as the operator, not as root.
        self.assertTrue(handle(self.nw, {"cmd": "ack"}, peer_is_root=False)["ok"])

    def test_status_reports_weakening(self):
        self.nw.add("a.com")
        self.nw.enforce()
        with open(self.paths.hosts, "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.assertTrue(handle(self.nw, {"cmd": "status"})["weakened"])

    def test_status_reports_no_weakening_when_intact(self):
        self.nw.add("a.com")
        self.nw.enforce()
        self.assertEqual(handle(self.nw, {"cmd": "status"})["weakened"], [])

    def test_ack_is_not_a_mutating_command(self):
        # It changes the ladder, not the wall; it must not force an enforcement.
        conn = _FakeConn([b'{"cmd": "ack"}\n'])
        self.assertFalse(server.serve_connection(self.nw, conn))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: FAIL — `handle` returns `unknown command: 'ack'`.

- [ ] **Step 3: Write minimal implementation**

In `server.handle`, before the unknown-command fallback:

```python
    if cmd == "ack":
        # Deliberately unprivileged: the plugin runs as the operator. All this
        # can do is clear a count, which only ever makes the next breach
        # cheaper by one rung -- and the breach itself is already recorded.
        ledger.record(nw.paths.ledger, "ack")
        return {"ok": True}
```

In `NetWatch.status`, add:

```python
            "unacknowledged": ladder.unacknowledged(entries),
            "weakened": integrity.weakened(
                self.paths.hosts, self.domains(), self.paths.zen_policy,
                self.paths.unit_file, self.paths.unit_source),
```

In `netwatch/bin/netwatchctl`, add the subcommand and print the new fields:

```python
    sub.add_parser("ack", help="acknowledge outstanding breaches")
```

```python
    elif args.command == "ack":
        call({"cmd": "ack"})
        print("acknowledged")
```

and in the status branch, after `failures`:

```python
        print("unacked  %d" % reply.get("unacknowledged", 0))
        for reason in reply.get("weakened", []):
            print("WEAK     %s" % reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: PASS, 6 new tests.

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/server.py netwatch/blackwall_netwatch/daemon.py netwatch/bin/netwatchctl netwatch/tests/test_server.py
git commit -m "netwatch: ack, and a status that reports the ladder"
```

---

### Task 7: Install the unit source copy

**Files:**
- Modify: `netwatch/install.sh`

`integrity.unit_intact` compares the installed unit against a reference copy. Without that copy installed the check always passes, so this is the task that makes Task 2's unit detection real rather than decorative.

- [ ] **Step 1: Install the reference copy alongside the package**

In `install.sh`, after the unit is installed to `/etc/systemd/system/`, add:

```bash
# The reference the integrity check compares against. Kept beside the package
# rather than in /etc, so an edit to the live unit has something to differ from.
install -m 0644 "$here/units/blackwall-netwatch.service" \
  /usr/local/lib/blackwall-netwatch/blackwall-netwatch.service
```

- [ ] **Step 2: Verify the script still parses**

Run: `bash -n netwatch/install.sh`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/install.sh
git commit -m "netwatch: install the unit reference the integrity check needs"
```

---

### Task 6b: An ack that cannot be forged

**Files:**
- Modify: `netwatch/blackwall_netwatch/ladder.py`
- Modify: `netwatch/blackwall_netwatch/daemon.py`
- Modify: `netwatch/blackwall_netwatch/server.py`
- Modify: `netwatch/bin/netwatchctl`
- Test: `netwatch/tests/test_ladder.py`, `netwatch/tests/test_server.py`

**Interfaces:**
- Produces: `ladder.pending_token(entries) -> str | None`; `NetWatch.escalation_token()`; socket command `{"cmd": "ack", "token": str}`; `netwatchctl ack <token>`

**Why.** `ack` as shipped is a bare unauthenticated socket write, and the socket
is 0666. `while true; do netwatchctl ack; sleep 5; done` pins the unacknowledged
count at one, and the lock rung is never reached — the one hard consequence this
tool exists to deliver, suppressible with zero privilege and no proof the
operator ever answered anything. The threat model is their own future self, who
has unprivileged standing by definition.

**Why a token, and why it is not in `status`.** The token must reach the plugin
over a channel a spamming process cannot read. `status` is the wrong place:
anything the plugin can read from the socket, any local process can read too.
The daemon therefore passes it as an argument to the IPC call it makes into the
session — root to plugin, over the plugin's own socket — and the plugin holds it
in memory and hands it back.

- [ ] **Step 1: Write the failing test for `pending_token`**

```python
class TestPendingToken(unittest.TestCase):
    def test_none_when_no_breach(self):
        self.assertIsNone(ladder.pending_token([]))

    def test_the_token_of_the_latest_unacknowledged_breach(self):
        entries = [{"kind": "breach", "at": NOW - 10, "token": "aaa"},
                   {"kind": "breach", "at": NOW, "token": "bbb"}]
        self.assertEqual(ladder.pending_token(entries), "bbb")

    def test_none_once_acknowledged(self):
        entries = [{"kind": "breach", "at": NOW - 10, "token": "aaa"},
                   {"kind": "ack", "at": NOW, "token": "aaa"}]
        self.assertIsNone(ladder.pending_token(entries))

    def test_a_breach_after_an_ack_is_pending_again(self):
        entries = [{"kind": "breach", "at": NOW - 20, "token": "aaa"},
                   {"kind": "ack", "at": NOW - 10, "token": "aaa"},
                   {"kind": "breach", "at": NOW, "token": "ccc"}]
        self.assertEqual(ladder.pending_token(entries), "ccc")

    def test_a_breach_without_a_token_yields_none(self):
        # Breaches recorded before this task carry no token; they cannot be
        # acknowledged, and must not crash the lookup either.
        self.assertIsNone(ladder.pending_token([{"kind": "breach", "at": NOW}]))

    def test_a_non_dict_entry_is_skipped(self):
        self.assertIsNone(ladder.pending_token(["junk", 3, None]))
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH=netwatch python3 -m unittest discover -s netwatch/tests -t netwatch/tests -v`
Expected: FAIL, `module 'blackwall_netwatch.ladder' has no attribute 'pending_token'`

- [ ] **Step 3: Implement `pending_token`**

```python
def pending_token(entries):
    """The token of the most recent breach nothing has acknowledged.

    None means there is nothing to acknowledge, and an ack presenting any token
    at all must be refused. That is the whole point: without this an ack is a
    bare socket write on a world-writable socket, and a shell loop could hold
    the ladder below the lock rung for ever.
    """
    token = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if kind == "ack":
            token = None
        elif kind == "breach":
            candidate = entry.get("token")
            token = candidate if isinstance(candidate, str) and candidate else None
    return token
```

- [ ] **Step 4: Issue the token, and require it**

In `daemon.py`, import `secrets`, and generate the token where the breach is
recorded so it lands on the ledger entry:

```python
        token = secrets.token_hex(4) if verdict == "breach" else None
        fields = {"targets": targets, "reasons": reasons}
        if token:
            fields["token"] = token
        ledger.record(self.paths.ledger, verdict, **fields)
        if verdict == "breach" and not first:
            self._escalate(reasons, token)
```

and `_escalate` passes it on, calling the two token-carrying methods rather than
bare `engage`:

```python
    def _escalate(self, reasons, token):
        entries = ledger.read(self.paths.ledger)
        step = ladder.rung(entries)
        try:
            if step == ladder.LOCK:
                self.notifier("lock", [str(ladder.LOCK_SECONDS), token])
            else:
                self.notifier("challenge",
                              [reasons[0] if reasons else "breach", token])
        except Exception:
            pass
```

In `server.handle`, the `ack` branch requires a matching token:

```python
    if cmd == "ack":
        # Unprivileged by design -- the plugin runs as the operator -- but not
        # unauthenticated. The token was delivered to the plugin over the
        # session IPC, which a process spamming this socket cannot read.
        token = request.get("token")
        expected = ladder.pending_token(ledger.read(nw.paths.ledger))
        if not expected or token != expected:
            return {"ok": False, "error": "no acknowledgement is pending"}
        ledger.record(nw.paths.ledger, "ack", token=token)
        return {"ok": True}
```

In `netwatchctl`, `ack` takes the token as a positional argument:

```python
    ack = sub.add_parser("ack", help="acknowledge a breach you were shown")
    ack.add_argument("token")
```

- [ ] **Step 5: Test that the bypass is closed**

```python
    def test_ack_without_a_token_is_refused(self):
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        self.assertFalse(handle(self.nw, {"cmd": "ack"})["ok"])

    def test_ack_with_the_wrong_token_is_refused(self):
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        self.assertFalse(handle(self.nw, {"cmd": "ack", "token": "zzz"})["ok"])

    def test_ack_with_the_right_token_is_accepted(self):
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        self.assertTrue(handle(self.nw, {"cmd": "ack", "token": "aaa"})["ok"])

    def test_a_token_cannot_be_replayed(self):
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        handle(self.nw, {"cmd": "ack", "token": "aaa"})
        self.assertFalse(handle(self.nw, {"cmd": "ack", "token": "aaa"})["ok"])

    def test_spamming_ack_cannot_hold_the_ladder_down(self):
        # The bypass this task exists to close: a shell loop with no token.
        for _ in range(20):
            handle(self.nw, {"cmd": "ack"})
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="aaa")
        ledger.record(self.paths.ledger, "breach", targets=["hosts"], token="bbb")
        entries = ledger.read(self.paths.ledger)
        self.assertEqual(ladder.rung(entries), ladder.LOCK)
```

- [ ] **Step 6: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch netwatch/bin/netwatchctl netwatch/tests
git commit -m "netwatch: an ack has to prove it was answered"
```

---

### Task 8: The challenge overlay and the plugin's startup check

**Files:**
- Create: `ChallengeView.qml`
- Modify: `Service.qml`
- Modify: `netwatch/README.md`

**Interfaces:**
- Consumes: `netwatchctl status` (JSON on stdout), `netwatchctl ack`
- Produces: IPC method `challenge(reason: string): string` on target `blackwall`

This task has no unit tests — it is QML in a running shell, verified by the operator. Everything it depends on is already tested.

- [ ] **Step 1: Create `ChallengeView.qml`**

A `WlSessionLockSurface`-free overlay: a `PanelWindow` in the Blackwall visual language showing the breach reason, a `TextField` for the phrase, and a confirm button disabled for 15 seconds. Read `BlackwallLockView.qml` first and match its palette, font and glitch treatment — this is the same wall speaking, not a new dialog.

Properties: `reason` (string), `phrase` (string, the expected answer), `armSeconds` (int, 15). Signal: `answered()`.

The phrase comes from the existing plugin config, `~/.config/omarchy/zds.blackwall.json`, key `challengePhrase`, read through the config `GuardedFile` that `Service.qml` already owns. **The daemon never sees it** — it says only that a challenge is due. If the key is absent, fall back to a built-in default, so a missing or unreadable config can never produce a challenge that cannot be answered.

The confirm button is enabled only when the typed text equals `phrase` **and** `armSeconds` have elapsed. There is no cancel button; closing the window is possible and leaves the breach unacknowledged, which is the design.

- [ ] **Step 2: Add the IPC method and the startup check to `Service.qml`**

In the existing `IpcHandler`, alongside `engage`:

```qml
    function challenge(reason: string, token: string): string {
      root.showChallenge(reason, token)
      return "challenge shown"
    }

    function lock(seconds: string, token: string): string {
      root.engage(parseInt(seconds, 10))
      root.pendingToken = token
      return "locked"
    }
```

The token is held in memory and sent back with `netwatchctl ack <token>` — after
the challenge is answered, or after a served lock expires. It is never read from
`status`, because anything the plugin can read there a spamming process can read
too. A served lock clears the slate: without that, reaching rung 2 would leave
every later breach locking for the full six hours with no challenge ever offered.

Add a `Process` that runs `netwatchctl status`, parses the JSON, and on a non-zero `unacknowledged` calls `root.engage(1200)` — the deferred rung, for a breach that happened with no session to lock. Run it from `Component.onCompleted`.

Add a `Process` that runs `netwatchctl ack`, invoked when `ChallengeView` emits `answered()` and after a ladder-driven `engage` has locked.

Follow the existing `GuardedFile` process pattern for both: wait for `processId > 0` before writing, and never assume a synchronous result.

- [ ] **Step 3: Verify against the running shell** — **[operator]**

```
netwatchctl status
sudo env XDG_RUNTIME_DIR=/run/user/$(id -u) qs ipc --pid $(pgrep -f 'quickshell.*omarchy/shell' | head -1) call blackwall challenge "test reason"
```

Expected: the challenge overlay appears, the confirm button is dead for 15 seconds, typing the phrase enables it, and confirming makes `netwatchctl status` report `unacked 0`.

- [ ] **Step 4: Document it**

Add a section to `netwatch/README.md` covering what a breach is, what each rung does, and that dismissing a challenge leaves it standing so the next breach locks. **Do not document how to stop, disable, mask or bypass any of it.**

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add ChallengeView.qml Service.qml netwatch/README.md
git commit -m "netwatch: the challenge overlay and the deferred rung"
```

---

## What Phase 2a deliberately does not do

- **No delayed removal.** That is Phase 2b: tombstones, the removal journal, and the doubling delay.
- **No bar widget.** Phase 3.
- **No change to `master`.** The challenge overlay and the `Service.qml` changes live on `netwatch` only.
