"""Guest proof of the uninstall contract (SL-6c, issue #91): the driver wiring, checked offline."""
import re
import unittest
from pathlib import Path

DRIVER = (Path(__file__).resolve().parent.parent / "installer" / "guest" / "guest-proof.ps1").read_text(encoding="ascii")
START = DRIVER.index("# ---- SL-6c")
BLOCK = DRIVER[START:DRIVER.index("# ---- SL-13 pre-created folder", START)]


class Sl6cDriver(unittest.TestCase):
    def test_every_item_is_reported(self):
        for item in ("leftover-default-launch", "leftover-exit-40", "run-twice-after-release", "readonly-file-removed",
                     "standard-user-gate", "service-running-uninstall"):
            self.assertIn("'SL-6c-%s'" % item, BLOCK)

    def test_default_launch_has_no_in_place_flag_and_the_exit_code_case_has_it(self):
        self.assertRegex(BLOCK, r"Run-Exe \$uninstallExe '/S' \$null")
        self.assertIn('"/S _?=$footprintFolder"', BLOCK)

    def test_exit_40_and_gate_38_are_required_and_5_is_the_only_other_direct_code(self):
        self.assertIn("($rc2 -eq 40) -and $exe2", BLOCK)
        self.assertIn("$stdCopyRc -eq 38", BLOCK)
        self.assertIn("-in 1, 5, 38", BLOCK)
        self.assertIn('SL-6c-leftover-keeps-uninstaller', BLOCK)
        self.assertIn("$rc2b", BLOCK)

    def test_leftover_means_service_gone_folder_and_key_kept(self):
        self.assertIn("'folder=True service=False key=True'", BLOCK)
        self.assertIn("[IO.File]::Open($held, 'OpenOrCreate', 'ReadWrite', 'None')", BLOCK)

    def test_a_process_that_never_ran_is_unproven_not_a_verdict(self):
        self.assertGreaterEqual(len(re.findall(r"-isnot \[int\]", BLOCK)), 4)
        self.assertIn("'UNPROVEN'", BLOCK)

    def test_service_must_be_running_before_the_running_service_case(self):
        self.assertIn("-not $runBefore", BLOCK)

    def test_block_leaves_a_clean_state_for_the_precreated_cases(self):
        self.assertGreaterEqual(BLOCK.count("Clean-6c\n"), 2)


if __name__ == "__main__":
    unittest.main()


class UninstCContract(unittest.TestCase):
    def test_new_items_and_the_edge_are_reported(self):
        for item in ("in-place-after-release", "clean-in-place", "clean-default", "empty-folder-edge"):
            self.assertIn("'SL-6c-%s'" % item, BLOCK)

    def test_in_place_leaves_only_uninstall_exe_with_exit_0(self):
        self.assertIn("($rc2b -eq 0) -and ($names -eq 'uninstall.exe')", BLOCK)
        self.assertIn("($rcA -eq 0) -and ($namesA -eq 'uninstall.exe')", BLOCK)

    def test_edge_holds_the_folder_as_a_current_directory_and_expects_it_left_empty(self):
        self.assertIn("cd /d $footprintFolder & ping", BLOCK)
        self.assertIn("$namesE -eq ''", BLOCK)

    def test_default_start_must_keep_uninstall_exe_after_a_leftover(self):
        self.assertIn("Ok6c $exe1 'SL-6c-leftover-keeps-uninstaller'", BLOCK)


class WaitsCoverTheProductWorstCase(unittest.TestCase):
    def test_polls_are_at_least_90s_and_wait_for_the_key(self):
        self.assertIn("function Wait-6c($until) { for ($i = 0; $i -lt 90;", DRIVER)
        sl6a = DRIVER[DRIVER.index("$unRc = Run-Exe"):DRIVER.index("$post = Get-Listing")]
        self.assertIn("$i -lt 90", sl6a)
        self.assertIn("-not (Test-Path $uninstallKey)", sl6a)
