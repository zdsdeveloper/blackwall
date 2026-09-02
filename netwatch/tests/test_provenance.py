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
