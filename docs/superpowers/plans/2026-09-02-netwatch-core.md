# NetWatch Core Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A root daemon that enforces a domain blocklist through `/etc/hosts` and a locked Zen DoH policy, repairs package-upgrade drift silently, and records hand tampering as a breach.

**Architecture:** A single-file-per-responsibility Python package driven by a systemd service. All mutation goes through a unix socket so the daemon is the sole writer of the blocklist — that is what makes "adding is instant, removing is slow" a property of the system rather than a convention. A pacman hook pair marks sanctioned transaction windows so upgrades are never mistaken for tampering.

**Tech Stack:** Python 3.14 stdlib only, systemd 261, pacman hooks, unittest.

**Spec:** `docs/superpowers/specs/2026-09-02-netwatch.md`

## Global Constraints

- Branch is `netwatch`. Never commit to `master`.
- **The blocklist is never committed.** `/var/lib/blackwall/` is outside the repo; add `netwatch/**/blocklist*` to `.gitignore` anyway as a second guard.
- Python 3 stdlib only. No pip, no new packages.
- Every module takes explicit paths as arguments. No module hardcodes `/etc/hosts` or any real system path at import time — tests must run against a tmpdir without root.
- Tests are `unittest`, run with `python3 -m unittest discover -s netwatch/tests -t netwatch`.
- No file in this phase punishes the operator. Breaches are recorded only.
- No README section, comment, or docstring explains how to disable NetWatch.
- Domain normalisation is defined once, in `blocklist.normalize`. Nothing else lowercases or strips.
- **No step runs bare `sudo`.** There is no passwordless sudo on this machine
  (`sudo -n true` fails), so an agent has nowhere to type a password. Scripts
  self-elevate with the `require_root` pattern below — `sudo` when a terminal is
  attached, `pkexec` otherwise. Steps marked **[operator]** must be run by the
  user in their own terminal with a `!` prefix; an agent must stop and hand them
  over rather than attempt them.
- The privilege pattern is copied from Omarchy's own
  `/usr/bin/omarchy-theme-set-browser-policy`. Root-phase scripts pin
  `PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin` so a dev
  link cannot resolve a helper out of a user-writable checkout.

---

### Task 1: Blocklist parsing and normalisation

**Files:**
- Create: `netwatch/blackwall_netwatch/__init__.py` (empty)
- Create: `netwatch/blackwall_netwatch/blocklist.py`
- Test: `netwatch/tests/test_blocklist.py`

**Interfaces:**
- Consumes: nothing
- Produces: `normalize(raw: str) -> str` (raises `InvalidDomain`), `parse(text: str) -> list[str]` (sorted, deduped), `InvalidDomain(ValueError)`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from blackwall_netwatch.blocklist import normalize, parse, InvalidDomain


class TestNormalize(unittest.TestCase):
    def test_strips_scheme_path_query_and_case(self):
        self.assertEqual(normalize("https://WWW.Example.COM/a/b?q=1"), "example.com")

    def test_strips_port_userinfo_and_trailing_dot(self):
        self.assertEqual(normalize("user@Example.com.:8443"), "example.com")

    def test_keeps_non_www_subdomains(self):
        self.assertEqual(normalize("cdn.example.com"), "cdn.example.com")

    def test_rejects_bare_label(self):
        with self.assertRaises(InvalidDomain):
            normalize("localhost")

    def test_rejects_empty(self):
        with self.assertRaises(InvalidDomain):
            normalize("   ")

    def test_rejects_bad_characters(self):
        with self.assertRaises(InvalidDomain):
            normalize("exa_mple.com")


class TestParse(unittest.TestCase):
    def test_ignores_comments_and_blanks_dedupes_and_sorts(self):
        text = "\n".join([
            "# a comment",
            "",
            "https://www.B.com/",
            "a.com   # trailing comment",
            "b.com",
        ])
        self.assertEqual(parse(text), ["a.com", "b.com"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'blackwall_netwatch'`

- [ ] **Step 3: Write minimal implementation**

```python
"""The blocklist.

Normalisation matters more than it looks. The operator will paste whole URLs,
mixed case, and trailing dots, and a domain that does not normalise to the same
string every time is a hole in the wall. This is the only place in NetWatch that
is allowed to transform a domain.
"""

import re

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class InvalidDomain(ValueError):
    pass


def normalize(raw):
    d = raw.strip().lower()
    if "://" in d:
        d = d.split("://", 1)[1]
    d = d.split("/", 1)[0]
    d = d.split("?", 1)[0]
    if "@" in d:
        d = d.split("@", 1)[1]
    d = d.split(":", 1)[0]
    d = d.rstrip(".")
    # Stored apex-only; hosts rendering puts the www back. Keeping both forms in
    # the list would mean two entries to remove and one of them forgotten.
    if d.startswith("www."):
        d = d[4:]
    if not d or len(d) > 253:
        raise InvalidDomain(raw)
    labels = d.split(".")
    if len(labels) < 2:
        raise InvalidDomain(raw)
    for label in labels:
        if not _LABEL.match(label):
            raise InvalidDomain(raw)
    return d


def parse(text):
    out = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        out.add(normalize(line))
    return sorted(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/__init__.py netwatch/blackwall_netwatch/blocklist.py netwatch/tests/test_blocklist.py
git commit -m "netwatch: parse and normalise blocklist domains"
```

---

### Task 2: Hosts file managed region

**Files:**
- Create: `netwatch/blackwall_netwatch/hosts.py`
- Test: `netwatch/tests/test_hosts.py`

**Interfaces:**
- Consumes: nothing
- Produces: `BEGIN: str`, `END: str`, `render(domains: list[str]) -> str`, `splice(current: str, block: str) -> str`, `apply(path: str, domains: list[str]) -> bool` (True if the file changed)

- [ ] **Step 1: Write the failing test**

```python
import os
import tempfile
import unittest
from blackwall_netwatch import hosts

STOCK = "# Static table lookup for hostnames.\n127.0.0.1 localhost\n::1 localhost\n"


class TestRender(unittest.TestCase):
    def test_renders_apex_and_www_between_markers(self):
        out = hosts.render(["a.com"])
        self.assertTrue(out.startswith(hosts.BEGIN))
        self.assertTrue(out.rstrip().endswith(hosts.END))
        self.assertIn("0.0.0.0 a.com", out)
        self.assertIn("0.0.0.0 www.a.com", out)

    def test_empty_list_still_renders_markers(self):
        out = hosts.render([])
        self.assertIn(hosts.BEGIN, out)
        self.assertIn(hosts.END, out)


class TestSplice(unittest.TestCase):
    def test_appends_when_absent_and_preserves_existing(self):
        out = hosts.splice(STOCK, hosts.render(["a.com"]))
        self.assertIn("127.0.0.1 localhost", out)
        self.assertIn("0.0.0.0 a.com", out)

    def test_is_idempotent(self):
        once = hosts.splice(STOCK, hosts.render(["a.com"]))
        twice = hosts.splice(once, hosts.render(["a.com"]))
        self.assertEqual(once, twice)

    def test_replaces_region_without_touching_surroundings(self):
        once = hosts.splice(STOCK, hosts.render(["a.com"]))
        updated = hosts.splice(once, hosts.render(["b.com"]))
        self.assertNotIn("a.com", updated)
        self.assertIn("0.0.0.0 b.com", updated)
        self.assertIn("127.0.0.1 localhost", updated)

    def test_preserves_trailing_content_after_region(self):
        with_tail = hosts.splice(STOCK, hosts.render(["a.com"])) + "10.0.0.1 later\n"
        updated = hosts.splice(with_tail, hosts.render(["b.com"]))
        self.assertIn("10.0.0.1 later", updated)


class TestApply(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "hosts")
        with open(self.path, "w") as f:
            f.write(STOCK)

    def test_writes_and_reports_change_then_reports_no_change(self):
        self.assertTrue(hosts.apply(self.path, ["a.com"]))
        self.assertFalse(hosts.apply(self.path, ["a.com"]))
        with open(self.path) as f:
            self.assertIn("0.0.0.0 a.com", f.read())

    def test_preserves_mode(self):
        os.chmod(self.path, 0o644)
        hosts.apply(self.path, ["a.com"])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o644)

    def test_leaves_no_temp_files_behind(self):
        hosts.apply(self.path, ["a.com"])
        self.assertEqual(os.listdir(self.dir), ["hosts"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: FAIL with `ImportError: cannot import name 'hosts'`

- [ ] **Step 3: Write minimal implementation**

```python
"""The managed region of /etc/hosts.

Everything between the markers belongs to NetWatch and is rewritten wholesale.
Everything outside them is the operator's and is never touched -- /etc/hosts is
a file other things legitimately edit.
"""

import os
import tempfile

BEGIN = "# >>> blackwall-netwatch (managed) >>>"
END = "# <<< blackwall-netwatch (managed) <<<"

# 0.0.0.0 rather than 127.0.0.1: nothing is listening, so the connection fails
# immediately instead of hitting whatever happens to be on the loopback.
SINK = "0.0.0.0"


def render(domains):
    lines = [BEGIN]
    for d in domains:
        lines.append("%s %s" % (SINK, d))
        lines.append("%s www.%s" % (SINK, d))
    lines.append(END)
    return "\n".join(lines)


def splice(current, block):
    if BEGIN in current and END in current:
        head = current.split(BEGIN, 1)[0]
        tail = current.split(END, 1)[1]
        return head.rstrip("\n") + "\n\n" + block + "\n" + tail.lstrip("\n")
    return current.rstrip("\n") + "\n\n" + block + "\n"


def apply(path, domains):
    with open(path) as f:
        current = f.read()
    desired = splice(current, render(domains))
    if desired == current:
        return False
    directory = os.path.dirname(path) or "."
    mode = os.stat(path).st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".netwatch-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(desired)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.rename(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: PASS, 16 tests total

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/hosts.py netwatch/tests/test_hosts.py
git commit -m "netwatch: render and atomically apply the managed hosts region"
```

---

### Task 3: Zen policy rendering

**Files:**
- Create: `netwatch/blackwall_netwatch/zenpolicy.py`
- Test: `netwatch/tests/test_zenpolicy.py`

**Interfaces:**
- Consumes: nothing
- Produces: `read_package_policies(path: str) -> dict`, `render(package_policies: dict) -> str`, `apply(path: str, package_policies: dict) -> bool`

**Why this task is not just "write a JSON file":** Zen's
`_getLocalConfigurationFile()` returns the system policy file and **returns
early** — it never reads the package's `distribution/policies.json` once ours
exists. The package currently sets `DisableAppUpdate` and
`DefaultSerialGuardSetting`. If we do not carry those across, writing our file
silently turns them off.

- [ ] **Step 1: Write the failing test**

```python
import json
import os
import tempfile
import unittest
from blackwall_netwatch import zenpolicy

PACKAGE = {"DisableAppUpdate": True, "DefaultSerialGuardSetting": 3}


class TestReadPackagePolicies(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "policies.json")

    def test_reads_policies_key(self):
        with open(self.path, "w") as f:
            json.dump({"policies": PACKAGE}, f)
        self.assertEqual(zenpolicy.read_package_policies(self.path), PACKAGE)

    def test_missing_file_is_empty_not_an_error(self):
        self.assertEqual(zenpolicy.read_package_policies(self.path), {})

    def test_malformed_file_is_empty_not_an_error(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual(zenpolicy.read_package_policies(self.path), {})


class TestRender(unittest.TestCase):
    def test_locks_doh_off(self):
        got = json.loads(zenpolicy.render({}))["policies"]["DNSOverHTTPS"]
        self.assertEqual(got, {"Enabled": False, "Locked": True})

    def test_carries_forward_package_policies(self):
        got = json.loads(zenpolicy.render(PACKAGE))["policies"]
        self.assertTrue(got["DisableAppUpdate"])
        self.assertEqual(got["DefaultSerialGuardSetting"], 3)

    def test_our_policy_wins_over_a_conflicting_package_value(self):
        hostile = {"DNSOverHTTPS": {"Enabled": True, "Locked": False}}
        got = json.loads(zenpolicy.render(hostile))["policies"]["DNSOverHTTPS"]
        self.assertEqual(got, {"Enabled": False, "Locked": True})


class TestApply(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "policies.json")

    def test_creates_then_reports_no_further_change(self):
        self.assertTrue(zenpolicy.apply(self.path, PACKAGE))
        self.assertFalse(zenpolicy.apply(self.path, PACKAGE))

    def test_creates_parent_directories(self):
        nested = os.path.join(self.dir, "zen", "policies", "policies.json")
        self.assertTrue(zenpolicy.apply(nested, {}))
        self.assertTrue(os.path.exists(nested))

    def test_repairs_a_tampered_file(self):
        zenpolicy.apply(self.path, PACKAGE)
        with open(self.path, "w") as f:
            f.write('{"policies": {}}')
        self.assertTrue(zenpolicy.apply(self.path, PACKAGE))
        got = json.loads(open(self.path).read())["policies"]["DNSOverHTTPS"]
        self.assertEqual(got, {"Enabled": False, "Locked": True})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: FAIL with `ImportError: cannot import name 'zenpolicy'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: PASS, 25 tests total

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/zenpolicy.py netwatch/tests/test_zenpolicy.py
git commit -m "netwatch: render the Zen policy with DoH locked off"
```

---

### Task 4: Verify the Zen system policy path empirically

**Files:**
- Modify: `docs/superpowers/specs/2026-09-02-netwatch.md` (record the confirmed path)

The spec expects `/etc/zen/policies/policies.json` because `application.ini` has
`RemotingName=zen`, but `SysConfD` is built from `MOZ_APP_NAME` and no literal
`/etc/zen` string appears in the binary. Everything downstream depends on this
path being right, and a wrong path fails silently — the wall would look armed
and DoH would still be on. So it gets confirmed by observation, not inference.

- [ ] **Step 1: Write a probe policy to the expected path** — **[operator]**

```bash
sudo mkdir -p /etc/zen/policies
printf '%s\n' '{"policies":{"DNSOverHTTPS":{"Enabled":false,"Locked":true}}}' \
  | sudo tee /etc/zen/policies/policies.json >/dev/null
```

- [ ] **Step 2: Restart Zen fully and check that the policy is live** — **[operator]**

Fully quit Zen (not just the window), relaunch, and open `about:policies`.
Expected: an **Active** tab listing `DNSOverHTTPS` with `Enabled: false`.
Then open `about:preferences#privacy` and confirm the DNS-over-HTTPS control is
greyed out and cannot be changed.

- [ ] **Step 3: If the Active tab is empty, find the real path**

```bash
# about:support -> "Enterprise Policies" row shows the path actually consulted.
# Fallback candidates, in order:
sudo mkdir -p /etc/zen-browser/policies
sudo cp /etc/zen/policies/policies.json /etc/zen-browser/policies/policies.json
```
Restart Zen and re-check `about:policies`. Record whichever path shows Active.

- [ ] **Step 4: Record the confirmed path in the spec**

Replace the "**Not yet verified empirically**" sentence in the Environment
section with the confirmed path and the date it was confirmed.

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add docs/superpowers/specs/2026-09-02-netwatch.md
git commit -m "netwatch: confirm the Zen system policy path"
```

---

### Task 5: Provenance classification

**Files:**
- Create: `netwatch/blackwall_netwatch/provenance.py`
- Test: `netwatch/tests/test_provenance.py`

**Interfaces:**
- Consumes: nothing
- Produces: `classify(window_marker: str, pacman_lock: str, now: float | None = None) -> str` returning `"drift"` or `"breach"`; `STALE_AFTER_SECONDS: int`

- [ ] **Step 1: Write the failing test**

```python
import os
import tempfile
import time
import unittest
from blackwall_netwatch import provenance


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.marker = os.path.join(self.dir, "pacman-window")
        self.lock = os.path.join(self.dir, "db.lck")

    def touch(self, path, age=0):
        with open(path, "w") as f:
            f.write("")
        if age:
            past = time.time() - age
            os.utime(path, (past, past))

    def test_no_signals_is_breach(self):
        self.assertEqual(provenance.classify(self.marker, self.lock), "breach")

    def test_hook_marker_is_drift(self):
        self.touch(self.marker)
        self.assertEqual(provenance.classify(self.marker, self.lock), "drift")

    def test_pacman_lock_alone_is_drift(self):
        self.touch(self.lock)
        self.assertEqual(provenance.classify(self.marker, self.lock), "drift")

    def test_stale_marker_is_ignored(self):
        # A transaction that crashed between PreTransaction and PostTransaction
        # would otherwise leave the marker in place and disable breach detection
        # permanently -- the quietest possible way for this tool to stop working.
        self.touch(self.marker, age=provenance.STALE_AFTER_SECONDS + 60)
        self.assertEqual(provenance.classify(self.marker, self.lock), "breach")

    def test_stale_marker_still_yields_to_a_live_lock(self):
        self.touch(self.marker, age=provenance.STALE_AFTER_SECONDS + 60)
        self.touch(self.lock)
        self.assertEqual(provenance.classify(self.marker, self.lock), "drift")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: FAIL with `ImportError: cannot import name 'provenance'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: PASS, 30 tests total

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/provenance.py netwatch/tests/test_provenance.py
git commit -m "netwatch: tell package drift apart from hand tampering"
```

---

### Task 6: Append-only event ledger

**Files:**
- Create: `netwatch/blackwall_netwatch/ledger.py`
- Test: `netwatch/tests/test_ledger.py`

**Interfaces:**
- Consumes: nothing
- Produces: `record(path: str, kind: str, **fields) -> dict` (the written record), `read(path: str) -> list[dict]`

Records counts and kinds, never URLs visited or content. The ledger exists so
that a pattern is visible later; it is not a browsing log.

- [ ] **Step 1: Write the failing test**

```python
import os
import tempfile
import unittest
from blackwall_netwatch import ledger


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "ledger.jsonl")

    def test_record_returns_entry_with_kind_and_timestamp(self):
        entry = ledger.record(self.path, "added", domain="a.com")
        self.assertEqual(entry["kind"], "added")
        self.assertEqual(entry["domain"], "a.com")
        self.assertIn("at", entry)

    def test_records_append_and_read_back_in_order(self):
        ledger.record(self.path, "added", domain="a.com")
        ledger.record(self.path, "breach", target="hosts")
        entries = ledger.read(self.path)
        self.assertEqual([e["kind"] for e in entries], ["added", "breach"])

    def test_read_missing_file_is_empty(self):
        self.assertEqual(ledger.read(self.path), [])

    def test_read_skips_a_corrupt_line_without_losing_the_rest(self):
        ledger.record(self.path, "added", domain="a.com")
        with open(self.path, "a") as f:
            f.write("{ truncated\n")
        ledger.record(self.path, "added", domain="b.com")
        self.assertEqual(len(ledger.read(self.path)), 2)

    def test_file_is_created_root_readable_only_for_write(self):
        ledger.record(self.path, "added", domain="a.com")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o644)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: FAIL with `ImportError: cannot import name 'ledger'`

- [ ] **Step 3: Write minimal implementation**

```python
"""What happened, in order. Kinds and counts, never content.

One JSON object per line so a partial write costs one entry rather than the
file. Opened O_APPEND every time: the daemon may be restarted mid-write and two
writers appending is safer than one writer holding a handle across a restart.
"""

import json
import os
import time


def record(path, kind, **fields):
    entry = {"at": time.time(), "kind": kind}
    entry.update(fields)
    line = json.dumps(entry, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return entry


def read(path):
    entries = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: PASS, 35 tests total

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/ledger.py netwatch/tests/test_ledger.py
git commit -m "netwatch: append-only event ledger"
```

---

### Task 7: Daemon state and enforcement cycle

**Files:**
- Create: `netwatch/blackwall_netwatch/daemon.py`
- Test: `netwatch/tests/test_daemon.py`

**Interfaces:**
- Consumes: `blocklist.parse`, `blocklist.normalize`, `blocklist.InvalidDomain`, `hosts.apply`, `zenpolicy.apply`, `zenpolicy.read_package_policies`, `provenance.classify`, `ledger.record`
- Produces: `Paths` dataclass with fields `blocklist, ledger, hosts, zen_policy, zen_package_policy, window_marker, pacman_lock, socket`; `NetWatch(paths)` with `domains() -> list[str]`, `add(raw: str) -> str`, `enforce() -> dict`, `status() -> dict`

`enforce()` returns `{"changed": bool, "verdict": "init"|"drift"|"breach"|None, "targets": list[str]}`.
`verdict` is `None` when nothing changed, and `"init"` for the first enforcement on a machine that has
never been enforced before — writing the region for the first time is installation, not tampering.
Whether the machine has been enforced before is read from the ledger, which is append-only and root-owned.

- [ ] **Step 1: Write the failing test**

```python
import json
import os
import tempfile
import unittest
from blackwall_netwatch import ledger
from blackwall_netwatch.daemon import NetWatch, Paths

STOCK = "127.0.0.1 localhost\n"


def paths_in(d):
    return Paths(
        blocklist=os.path.join(d, "blocklist"),
        ledger=os.path.join(d, "ledger.jsonl"),
        hosts=os.path.join(d, "hosts"),
        zen_policy=os.path.join(d, "zen", "policies", "policies.json"),
        zen_package_policy=os.path.join(d, "distribution", "policies.json"),
        window_marker=os.path.join(d, "pacman-window"),
        pacman_lock=os.path.join(d, "db.lck"),
        socket=os.path.join(d, "netwatch.sock"),
    )


class TestNetWatch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = paths_in(self.dir)
        with open(self.paths.hosts, "w") as f:
            f.write(STOCK)
        os.makedirs(os.path.dirname(self.paths.zen_package_policy))
        with open(self.paths.zen_package_policy, "w") as f:
            json.dump({"policies": {"DisableAppUpdate": True}}, f)
        self.nw = NetWatch(self.paths)

    def test_starts_empty(self):
        self.assertEqual(self.nw.domains(), [])

    def test_add_normalises_and_persists(self):
        self.assertEqual(self.nw.add("https://WWW.Example.com/x"), "example.com")
        self.assertEqual(self.nw.domains(), ["example.com"])
        self.assertEqual(NetWatch(self.paths).domains(), ["example.com"])

    def test_add_is_idempotent(self):
        self.nw.add("a.com")
        self.nw.add("www.a.com")
        self.assertEqual(self.nw.domains(), ["a.com"])

    def test_add_rejects_garbage_without_writing(self):
        from blackwall_netwatch.blocklist import InvalidDomain
        with self.assertRaises(InvalidDomain):
            self.nw.add("localhost")
        self.assertEqual(self.nw.domains(), [])

    def test_add_is_recorded(self):
        self.nw.add("a.com")
        kinds = [e["kind"] for e in ledger.read(self.paths.ledger)]
        self.assertIn("added", kinds)

    def test_enforce_writes_hosts_and_zen_policy(self):
        self.nw.add("a.com")
        result = self.nw.enforce()
        self.assertTrue(result["changed"])
        self.assertIn("0.0.0.0 a.com", open(self.paths.hosts).read())
        policy = json.load(open(self.paths.zen_policy))["policies"]
        self.assertEqual(policy["DNSOverHTTPS"], {"Enabled": False, "Locked": True})
        self.assertTrue(policy["DisableAppUpdate"])

    def test_enforce_is_quiet_when_nothing_changed(self):
        self.nw.add("a.com")
        self.nw.enforce()
        result = self.nw.enforce()
        self.assertFalse(result["changed"])
        self.assertIsNone(result["verdict"])

    def test_hand_edit_of_hosts_is_a_breach(self):
        self.nw.add("a.com")
        self.nw.enforce()
        with open(self.paths.hosts, "w") as f:
            f.write(STOCK)
        result = self.nw.enforce()
        self.assertEqual(result["verdict"], "breach")
        self.assertIn("hosts", result["targets"])
        self.assertIn("0.0.0.0 a.com", open(self.paths.hosts).read())

    def test_edit_during_a_pacman_window_is_drift_not_breach(self):
        self.nw.add("a.com")
        self.nw.enforce()
        os.unlink(self.paths.zen_policy)
        with open(self.paths.window_marker, "w") as f:
            f.write("")
        result = self.nw.enforce()
        self.assertEqual(result["verdict"], "drift")
        self.assertTrue(os.path.exists(self.paths.zen_policy))

    def test_first_enforce_is_initialisation_not_breach(self):
        # Writing the managed region onto a machine that never had one is an
        # install. Calling it tampering would mean every fresh setup starts with
        # a breach on the record.
        self.nw.add("a.com")
        self.assertEqual(self.nw.enforce()["verdict"], "init")

    def test_second_enforce_after_a_hand_edit_is_a_breach(self):
        self.nw.add("a.com")
        self.nw.enforce()
        os.unlink(self.paths.zen_policy)
        self.assertEqual(self.nw.enforce()["verdict"], "breach")

    def test_breach_is_recorded_with_its_target(self):
        self.nw.add("a.com")
        self.nw.enforce()
        os.unlink(self.paths.zen_policy)
        self.nw.enforce()
        breaches = [e for e in ledger.read(self.paths.ledger) if e["kind"] == "breach"]
        self.assertEqual(len(breaches), 1)
        self.assertIn("zen_policy", breaches[0]["targets"])

    def test_status_reports_counts_not_domains(self):
        self.nw.add("a.com")
        s = self.nw.status()
        self.assertEqual(s["domains"], 1)
        self.assertEqual(s["breaches"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'blackwall_netwatch.daemon'`

- [ ] **Step 3: Write minimal implementation**

```python
"""The wall itself.

Enforcement is a repair loop, not an event handler: whatever the file says, make
it say the right thing again. That means a change made while the daemon was
stopped is caught the moment it starts, and it means there is no edit-detection
race to lose.
"""

import dataclasses
import os

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


class NetWatch:
    def __init__(self, paths):
        self.paths = paths

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: PASS, 48 tests total

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/blackwall_netwatch/daemon.py netwatch/tests/test_daemon.py
git commit -m "netwatch: enforcement cycle with drift and breach verdicts"
```

---

### Task 8: Socket server and `netwatchctl`

**Files:**
- Create: `netwatch/blackwall_netwatch/server.py`
- Create: `netwatch/bin/blackwall-netwatch`
- Create: `netwatch/bin/netwatchctl`
- Test: `netwatch/tests/test_server.py`

**Interfaces:**
- Consumes: `NetWatch`, `Paths`
- Produces: `handle(nw: NetWatch, request: dict) -> dict`; `serve(nw: NetWatch, interval: int) -> None`

Protocol is one JSON object per connection, newline-terminated, reply likewise.
Commands: `{"cmd": "add", "domain": str}`, `{"cmd": "list"}`, `{"cmd": "status"}`,
`{"cmd": "enforce"}`.
**There is no remove command.** Removal arrives in Phase 2 behind a delay.

`enforce` exists so the pacman hook can force the repair *while its window is
still open*. Without it the hook would have to remove the marker and wait for the
next poll, and that poll would find changed files with no window and call a
routine system upgrade a breach.

- [ ] **Step 1: Write the failing test**

```python
import json
import os
import tempfile
import unittest
from blackwall_netwatch.daemon import NetWatch, Paths
from blackwall_netwatch.server import handle


def paths_in(d):
    return Paths(
        blocklist=os.path.join(d, "blocklist"),
        ledger=os.path.join(d, "ledger.jsonl"),
        hosts=os.path.join(d, "hosts"),
        zen_policy=os.path.join(d, "zen", "policies", "policies.json"),
        zen_package_policy=os.path.join(d, "dist.json"),
        window_marker=os.path.join(d, "pacman-window"),
        pacman_lock=os.path.join(d, "db.lck"),
        socket=os.path.join(d, "netwatch.sock"),
    )


class TestHandle(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "hosts"), "w") as f:
            f.write("127.0.0.1 localhost\n")
        self.nw = NetWatch(paths_in(self.dir))

    def test_add_returns_the_normalised_domain(self):
        reply = handle(self.nw, {"cmd": "add", "domain": "https://WWW.A.com/"})
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["domain"], "a.com")

    def test_add_rejects_garbage_with_a_message(self):
        reply = handle(self.nw, {"cmd": "add", "domain": "localhost"})
        self.assertFalse(reply["ok"])
        self.assertIn("localhost", reply["error"])

    def test_list_returns_domains(self):
        handle(self.nw, {"cmd": "add", "domain": "a.com"})
        self.assertEqual(handle(self.nw, {"cmd": "list"})["domains"], ["a.com"])

    def test_status_reports_counts(self):
        self.assertEqual(handle(self.nw, {"cmd": "status"})["domains"], 0)

    def test_enforce_repairs_and_reports(self):
        # The pacman hook calls this inside its window; without it the repair
        # would land after the window closed and read as tampering.
        handle(self.nw, {"cmd": "add", "domain": "a.com"})
        reply = handle(self.nw, {"cmd": "enforce"})
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["result"]["changed"])

    def test_remove_is_not_a_command(self):
        reply = handle(self.nw, {"cmd": "remove", "domain": "a.com"})
        self.assertFalse(reply["ok"])

    def test_unknown_command_is_refused_not_crashing(self):
        reply = handle(self.nw, {"cmd": "nonsense"})
        self.assertFalse(reply["ok"])

    def test_malformed_request_is_refused(self):
        self.assertFalse(handle(self.nw, {})["ok"])
        self.assertFalse(handle(self.nw, {"cmd": "add"})["ok"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'blackwall_netwatch.server'`

- [ ] **Step 3: Write minimal implementation**

`netwatch/blackwall_netwatch/server.py`:

```python
"""The only way in.

The blocklist is root-owned and append-only, so the operator cannot edit it
directly -- every change comes through here. That is the whole point: it lets the
daemon enforce "adding is instant, removing is slow" as a property of the system
rather than a convention someone has to keep.
"""

import json
import os
import socket
import time

from .blocklist import InvalidDomain


def handle(nw, request):
    cmd = request.get("cmd")
    if cmd == "add":
        raw = request.get("domain")
        if not isinstance(raw, str) or not raw.strip():
            return {"ok": False, "error": "add requires a domain"}
        try:
            return {"ok": True, "domain": nw.add(raw)}
        except InvalidDomain as exc:
            return {"ok": False, "error": "not a domain: %s" % exc}
    if cmd == "list":
        return {"ok": True, "domains": nw.domains()}
    if cmd == "status":
        reply = {"ok": True}
        reply.update(nw.status())
        return reply
    if cmd == "enforce":
        return {"ok": True, "result": nw.enforce()}
    return {"ok": False, "error": "unknown command: %r" % (cmd,)}


def serve(nw, interval=30):
    path = nw.paths.socket
    os.makedirs(os.path.dirname(path) or "/", mode=0o755, exist_ok=True)
    if os.path.exists(path):
        os.unlink(path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    # Anyone on this machine may add a domain. Nobody, including this user, may
    # take one away.
    os.chmod(path, 0o666)
    server.listen(8)
    server.settimeout(interval)
    nw.enforce()
    last = time.monotonic()
    while True:
        try:
            conn, _ = server.accept()
        except socket.timeout:
            conn = None
        if conn is not None:
            with conn:
                conn.settimeout(5)
                try:
                    data = conn.recv(65536).decode("utf-8")
                    reply = handle(nw, json.loads(data))
                except (ValueError, UnicodeDecodeError):
                    reply = {"ok": False, "error": "malformed request"}
                except socket.timeout:
                    reply = None
                if reply is not None:
                    conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
            nw.enforce()
            last = time.monotonic()
        elif time.monotonic() - last >= interval:
            nw.enforce()
            last = time.monotonic()
```

`netwatch/bin/blackwall-netwatch`:

```python
#!/usr/bin/env python3
"""NetWatch daemon entry point."""

import sys

sys.path.insert(0, "/usr/local/lib/blackwall-netwatch")

from blackwall_netwatch.daemon import NetWatch, Paths
from blackwall_netwatch.server import serve

PATHS = Paths(
    blocklist="/var/lib/blackwall/blocklist",
    ledger="/var/lib/blackwall/ledger.jsonl",
    hosts="/etc/hosts",
    zen_policy="/etc/zen/policies/policies.json",
    zen_package_policy="/opt/zen-browser-bin/distribution/policies.json",
    window_marker="/run/blackwall/pacman-window",
    pacman_lock="/var/lib/pacman/db.lck",
    socket="/run/blackwall/netwatch.sock",
)

if __name__ == "__main__":
    serve(NetWatch(PATHS))
```

`netwatch/bin/netwatchctl`:

```python
#!/usr/bin/env python3
"""Talk to NetWatch."""

import argparse
import json
import socket
import sys

SOCKET = "/run/blackwall/netwatch.sock"


def call(request):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect(SOCKET)
    except OSError as exc:
        sys.exit("netwatch is not running (%s)" % exc)
    with s:
        s.sendall((json.dumps(request) + "\n").encode("utf-8"))
        return json.loads(s.recv(65536).decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(prog="netwatchctl")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="block a domain, permanently")
    add.add_argument("domain")
    sub.add_parser("list", help="show blocked domains")
    sub.add_parser("status", help="show counts")
    sub.add_parser("enforce", help="repair the managed files now")
    args = parser.parse_args()

    if args.command == "add":
        reply = call({"cmd": "add", "domain": args.domain})
        if not reply["ok"]:
            sys.exit(reply["error"])
        print("blocked: %s" % reply["domain"])
    elif args.command == "list":
        for domain in call({"cmd": "list"})["domains"]:
            print(domain)
    elif args.command == "enforce":
        result = call({"cmd": "enforce"})["result"]
        print("changed: %s" % result["changed"])
    else:
        reply = call({"cmd": "status"})
        print("domains  %d" % reply["domains"])
        print("breaches %d" % reply["breaches"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.config/omarchy/plugins/zds.blackwall && python3 -m unittest discover -s netwatch/tests -t netwatch -v`
Expected: PASS, 56 tests total

- [ ] **Step 5: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
chmod +x netwatch/bin/blackwall-netwatch netwatch/bin/netwatchctl
git add netwatch/blackwall_netwatch/server.py netwatch/bin netwatch/tests/test_server.py
git commit -m "netwatch: socket server and netwatchctl"
```

---

### Task 9: systemd unit, pacman hooks, installer

**Files:**
- Create: `netwatch/units/blackwall-netwatch.service`
- Create: `netwatch/hooks/50-blackwall-netwatch-begin.hook`
- Create: `netwatch/hooks/99-blackwall-netwatch-end.hook`
- Create: `netwatch/bin/netwatch-hook`
- Create: `netwatch/install.sh`
- Modify: `.gitignore`

The unit is deliberately **not** hardened in this task — no `RefuseManualStop`,
no append-only blocklist. Development needs `systemctl restart` to work. Task 10
arms it.

- [ ] **Step 1: Write the unit and hooks**

`netwatch/units/blackwall-netwatch.service`:

```ini
[Unit]
Description=NetWatch - Blackwall integrity daemon
After=local-fs.target

[Service]
Type=simple
ExecStart=/usr/local/bin/blackwall-netwatch
Restart=always
RestartSec=2
RuntimeDirectory=blackwall
RuntimeDirectoryMode=0755
StateDirectory=blackwall
StateDirectoryMode=0755

[Install]
WantedBy=multi-user.target
```

`netwatch/hooks/50-blackwall-netwatch-begin.hook`:

```ini
[Trigger]
Operation = Install
Operation = Upgrade
Operation = Remove
Type = Package
Target = *

[Action]
Description = NetWatch: opening sanctioned transaction window
When = PreTransaction
Exec = /usr/local/bin/netwatch-hook begin
```

`netwatch/hooks/99-blackwall-netwatch-end.hook`: identical, but
`When = PostTransaction`, `Exec = /usr/local/bin/netwatch-hook end`, and
`Description = NetWatch: closing sanctioned transaction window`.

`netwatch/bin/netwatch-hook`:

```bash
#!/bin/bash
# Marks the window in which a file NetWatch protects may legitimately change.
# Without this a routine system update looks exactly like tampering.
set -euo pipefail

marker=/run/blackwall/pacman-window
mkdir -p /run/blackwall

case "${1:-}" in
  begin) : > "$marker" ;;
  end)
    # Repair anything the transaction replaced BEFORE dropping the marker --
    # the daemon has to see the window still open or it reads its own repair as
    # tampering. Deliberately not a systemctl restart: once the unit is armed
    # with RefuseManualStop, restart is refused and the repair would never run.
    /usr/local/bin/netwatchctl enforce >/dev/null 2>&1 || true
    rm -f "$marker"
    ;;
  *) echo "usage: netwatch-hook begin|end" >&2; exit 2 ;;
esac
```

- [ ] **Step 2: Write the installer**

`netwatch/install.sh`:

```bash
#!/bin/bash
# Install NetWatch. From the repo root: ./netwatch/install.sh
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.sh"

# Omarchy's own privileged helpers use this shape -- see
# /usr/bin/omarchy-theme-set-browser-policy. sudo when a terminal is attached to
# take the password, pkexec when one is not: an agent or a graphical launcher
# has nowhere to type it.
require_root() {
  if (( EUID == 0 )); then
    return
  elif [[ -t 0 ]]; then
    exec sudo "$SELF" "$@"
  else
    exec pkexec "$SELF" "$@"
  fi
}
require_root "$@"

# Root phase: a dev link can prepend a user-writable bin/ to secure_path, so
# pin PATH before calling install, cp or systemctl by bare name.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

install -d -m 0755 /usr/local/lib/blackwall-netwatch
cp -r "$here/blackwall_netwatch" /usr/local/lib/blackwall-netwatch/
install -m 0755 "$here/bin/blackwall-netwatch" /usr/local/bin/blackwall-netwatch
install -m 0755 "$here/bin/netwatchctl"        /usr/local/bin/netwatchctl
install -m 0755 "$here/bin/netwatch-hook"      /usr/local/bin/netwatch-hook

install -d -m 0755 /etc/pacman.d/hooks
install -m 0644 "$here/hooks/"*.hook /etc/pacman.d/hooks/
install -m 0644 "$here/units/blackwall-netwatch.service" /etc/systemd/system/

install -d -m 0755 /var/lib/blackwall
touch /var/lib/blackwall/blocklist
chmod 0644 /var/lib/blackwall/blocklist

systemctl daemon-reload
systemctl enable --now blackwall-netwatch.service
systemctl --no-pager --lines=5 status blackwall-netwatch.service
```

- [ ] **Step 3: Guard the blocklist against ever being committed**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
cat >> .gitignore <<'EOF'

# The blocklist is personal and this repo is public. It lives in
# /var/lib/blackwall and must never appear here.
netwatch/**/blocklist
netwatch/**/blocklist.*
netwatch/**/ledger.jsonl
EOF
```

- [ ] **Step 4: Install and verify end to end** — **[operator]**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
chmod +x netwatch/install.sh netwatch/bin/netwatch-hook
./netwatch/install.sh
netwatchctl status
netwatchctl add example.com
grep -A3 'blackwall-netwatch' /etc/hosts
getent hosts example.com
```

Expected: `status` prints counts; `add` prints `blocked: example.com`; the hosts
region contains `0.0.0.0 example.com` and `0.0.0.0 www.example.com`;
`getent hosts example.com` resolves to `0.0.0.0`.

- [ ] **Step 5: Verify a package transaction does not register as a breach** — **[operator]**

```bash
netwatchctl status                       # note the breach count
sudo pacman -S --noconfirm --needed tree # any trivial package
netwatchctl status                       # breach count must be unchanged
journalctl -u blackwall-netwatch -n 20 --no-pager
```

Expected: breach count identical before and after.

- [ ] **Step 6: Commit**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/units netwatch/hooks netwatch/bin/netwatch-hook netwatch/install.sh .gitignore
git commit -m "netwatch: systemd unit, pacman hooks, installer"
```

---

### Task 10: Review, document, and arm

**Files:**
- Create: `netwatch/README.md`
- Modify: `netwatch/units/blackwall-netwatch.service`

- [ ] **Step 1: Get a second model onto the root-side code**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
agy -p --effort high "Review this for correctness and for ways a same-user \
process could defeat or wedge it. It is a root daemon that enforces a hosts \
blocklist and a browser policy file. Focus on: atomic write correctness, the \
socket protocol, and whether the drift-vs-breach classification can be spoofed \
by a non-root user. $(cat netwatch/blackwall_netwatch/*.py)" | tee /tmp/agy-netwatch-review.txt
```

Read the review, judge each point on its merits rather than implementing it
wholesale, and fix what is genuinely wrong. Note in the commit message which
findings were acted on and which were rejected and why.

- [ ] **Step 2: Write `netwatch/README.md`**

Cover: what NetWatch is, the commitment-device framing, the scope boundary
(it watches only its own artifacts), how to add a domain, that there is no
removal in this phase, and that the blocklist lives in `/var/lib/blackwall` and
is never committed. **Do not document how to stop, disable, or uninstall it.**

- [ ] **Step 3: Arm the unit** — **[operator]** for the shell commands

Add to the `[Unit]` section of `netwatch/units/blackwall-netwatch.service`:

```ini
RefuseManualStop=yes
```

Then make the blocklist append-only so it cannot be edited by hand even with
sudo, and reinstall:

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
./netwatch/install.sh
sudo chattr +a /var/lib/blackwall/blocklist
sudo chattr +a /var/lib/blackwall/ledger.jsonl
lsattr /var/lib/blackwall/
```

Expected: both files show the `a` attribute.

- [ ] **Step 4: Verify arming took** — **[operator]**

```bash
sudo systemctl stop blackwall-netwatch.service    # must be refused
systemctl is-active blackwall-netwatch.service    # must print "active"
netwatchctl add example.org                       # must still work
```

Expected: the stop is refused by systemd, the service stays active, and adding
still works through the socket.

- [ ] **Step 5: Commit and push the branch**

```bash
cd ~/.config/omarchy/plugins/zds.blackwall
git add netwatch/README.md netwatch/units/blackwall-netwatch.service
git commit -m "netwatch: document and arm"
git push -u origin netwatch
```

---

## What Phase 1 deliberately does not do

- **No removal.** Nothing added can be taken away yet. Phase 2 adds the 24h
  delay path. Until then the daemon is stoppable by someone who knows how, which
  is the intended pressure release while the delay machine is being built.
- **No punishment.** Breaches are counted, not acted on. Phase 2 adds the ladder.
- **No UI.** `netwatchctl` only. Phase 3 adds the bar widget and window.
