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

    def make_proc(self, name, comm):
        proc = os.path.join(self.dir, name)
        os.makedirs(os.path.join(proc, "4242"), exist_ok=True)
        with open(os.path.join(proc, "4242", "comm"), "w") as f:
            f.write(comm + "\n")
        return proc

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

    def test_stale_lock_with_no_package_manager_running_is_breach(self):
        # A killed pacman leaves db.lck behind as a matter of course. Without
        # this, one touch of that path would buy permanent drift and every hand
        # edit after it would go unrecorded.
        self.touch(self.lock, age=provenance.STALE_AFTER_SECONDS + 60)
        idle = self.make_proc("idle-proc", "bash")
        self.assertEqual(
            provenance.classify(self.marker, self.lock, proc_dir=idle), "breach")

    def test_stale_lock_during_a_long_transaction_is_still_drift(self):
        # A big -Syu can outrun the staleness bound. Bounding on age alone would
        # call a real system update tampering.
        self.touch(self.lock, age=provenance.STALE_AFTER_SECONDS + 60)
        busy = self.make_proc("busy-proc", "pacman")
        self.assertEqual(
            provenance.classify(self.marker, self.lock, proc_dir=busy), "drift")

    def test_fresh_lock_is_trusted_without_a_process_scan(self):
        self.touch(self.lock)
        idle = self.make_proc("idle-proc2", "bash")
        self.assertEqual(
            provenance.classify(self.marker, self.lock, proc_dir=idle), "drift")

    def test_a_live_package_manager_with_no_lock_is_not_a_transaction(self):
        # `pacman -Q` lists installed packages. It is unprivileged, it takes no
        # lock, and it runs a process named pacman -- so if a live process were
        # enough on its own, `while true; do pacman -Q; done` would force
        # permanent drift for any user on the machine and the wall would detect
        # nothing. A transaction is made by db.lck; the process scan exists only
        # to tell a stale lock from a slow one. Do not widen this.
        busy = self.make_proc("querying-proc", "pacman")
        self.assertEqual(
            provenance.classify(self.marker, self.lock, proc_dir=busy), "breach")

    def test_a_fresh_marker_is_still_drift_with_a_live_pacman_and_no_lock(self):
        # The other half: narrowing the lock rule left the hook marker's own
        # path exactly as it was.
        self.touch(self.marker)
        busy = self.make_proc("querying-proc2", "pacman")
        self.assertEqual(
            provenance.classify(self.marker, self.lock, proc_dir=busy), "drift")

    def test_a_stale_lock_with_a_live_pacman_is_still_drift(self):
        # The case the process scan is for: a big -Syu outruns the staleness
        # bound while genuinely holding the lock.
        self.touch(self.lock, age=provenance.STALE_AFTER_SECONDS + 60)
        busy = self.make_proc("syu-proc", "pacman")
        self.assertEqual(
            provenance.classify(self.marker, self.lock, proc_dir=busy), "drift")

    def test_unreadable_proc_is_treated_as_no_transaction(self):
        self.touch(self.lock, age=provenance.STALE_AFTER_SECONDS + 60)
        missing = os.path.join(self.dir, "no-such-proc")
        self.assertEqual(
            provenance.classify(self.marker, self.lock, proc_dir=missing), "breach")


if __name__ == "__main__":
    unittest.main()
