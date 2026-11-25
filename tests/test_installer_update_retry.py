"""SL-19 fix round C: a transient access denied while the program folder is replaced is retried (1, 2, 4, 8 s); nothing else is."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from installer import update


class Retry(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.src, self.dst = tmp / "src", tmp / "dst"
        self.src.mkdir()
        (self.src / "runner.exe").write_text("new")
        self.dst.mkdir()
        (self.dst / "runner.exe").write_text("old")
        self.waits = []
        p = mock.patch.object(update, "_sleep", self.waits.append)
        p.start()
        self.addCleanup(p.stop)

    def run_with(self, failures, error=PermissionError):
        real, calls = shutil.rmtree, []

        def fake(path, *a, **k):
            calls.append(path)
            if len(calls) <= failures:
                raise error(13, "denied")
            return real(path, *a, **k)
        with mock.patch.object(update.shutil, "rmtree", fake):
            update._replace_tree(self.src, self.dst)
        return calls

    def test_the_wait_list_is_pinned(self):
        self.assertEqual(update._REPLACE_RETRY_SECONDS, (1, 2, 4, 8))

    def test_no_failure_no_wait(self):
        self.run_with(0)
        self.assertEqual(self.waits, [])
        self.assertEqual((self.dst / "runner.exe").read_text(), "new")

    def test_transient_failures_wait_one_two_four_eight(self):
        for n, waits in ((1, [1]), (3, [1, 2, 4]), (4, [1, 2, 4, 8])):
            self.waits.clear()
            self.dst.mkdir(exist_ok=True)
            (self.dst / "runner.exe").write_text("old")
            calls = self.run_with(n)
            with self.subTest(n=n):
                self.assertEqual(self.waits, waits)
                self.assertEqual(len(calls), n + 1)
                self.assertEqual((self.dst / "runner.exe").read_text(), "new")

    def test_a_permanent_failure_raises_the_original_error_after_the_last_wait(self):
        err = PermissionError(13, "denied")
        with mock.patch.object(update.shutil, "rmtree", side_effect=err) as m:
            with self.assertRaises(PermissionError) as c:
                update._replace_tree(self.src, self.dst)
        self.assertIs(c.exception, err)
        self.assertEqual((self.waits, m.call_count), ([1, 2, 4, 8], 5))

    def test_any_other_error_is_not_retried(self):
        with mock.patch.object(update.shutil, "rmtree", side_effect=OSError(5, "io")) as m:
            with self.assertRaises(OSError):
                update._replace_tree(self.src, self.dst)
        self.assertEqual((self.waits, m.call_count), ([], 1))

    def test_the_sleep_is_injectable_and_a_test_never_really_waits(self):
        self.assertEqual(update._sleep, self.waits.append)
        self.assertIn("_sleep = time.sleep", Path(update.__file__).read_text(encoding="utf-8"))
        self.assertNotIn("time.sleep(", Path(update.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
