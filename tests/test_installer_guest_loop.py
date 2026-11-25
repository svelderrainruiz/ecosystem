"""SL-6b diagnosis loop: wiring and failure detail, offline."""
import re
import unittest
from pathlib import Path

from installer.guest import service_proof

DRIVER = (Path(__file__).resolve().parent.parent / "installer" / "guest" / "guest-proof.ps1").read_text(encoding="ascii")


class LoopTests(unittest.TestCase):
    def test_failure_detail_names_class_winerror_paths_and_frames(self):
        try:
            e = PermissionError(13, "denied", "C:\\a\\runner.exe")
            e.winerror = 5
            raise e
        except PermissionError as err:
            text = service_proof.failure_detail(err)
        for part in ("PermissionError", "winerror=5", "filename=C:\\a\\runner.exe", "filename2=None", "test_installer_guest_loop.py:"):
            self.assertIn(part, text)

    def test_loop_is_dispatched_and_never_writes_to_results(self):
        self.assertIn("'updateloop'", DRIVER)
        self.assertIn("[int]$UpdateLoop", DRIVER)
        self.assertIn('"updateloop"', Path(service_proof.__file__).read_text(encoding="ascii"))
        # INFO lines do not match the result filter of Invoke-Proof
        self.assertIsNone(re.match(r"^(SL-|ERROR-)[A-Za-z0-9-]*\|(PASS|FAIL|UNPROVEN)\|", "SL-6b-loop-01|INFO|x"))

    def test_loop_records_the_step_of_each_failure(self):
        src = Path(service_proof.__file__).read_text(encoding="ascii")
        for step in ("lock", "stop", "start", "health", "swap"):
            self.assertIn('"%s"' % step, src)


if __name__ == "__main__":
    unittest.main()
