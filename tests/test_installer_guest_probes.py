"""Probe run (ecosystem-control#64): the diagnostic probes are wired behind -ProbesOnly and can never count as a checklist item."""
import re
import unittest
from pathlib import Path

GUEST = Path(__file__).resolve().parent.parent / "installer" / "guest"
DRIVER = (GUEST / "guest-proof.ps1").read_text(encoding="ascii")
PROBES = (GUEST / "probes.ps1").read_text(encoding="ascii")


class ProbeWiring(unittest.TestCase):
    def test_flag_exists_and_probes_run_only_behind_it(self):
        self.assertIn("param([switch]$ProbesOnly, [int]$UpdateLoop = 0, [switch]$GateProbes)", DRIVER)
        self.assertRegex(DRIVER, r"if \(\$ProbesOnly\) \{\s+\. \(Join-Path \$tree 'installer\\guest\\probes\.ps1'\)\s+exit 0")
        self.assertIn("if (-not $ProbesOnly -and -not $GateProbes) {", DRIVER)

    def test_every_probe_line_is_info(self):
        self.assertIn("Res \"PROBE-$id\" 'INFO'", PROBES)
        self.assertNotRegex(PROBES, r"Res '[A-Z]+-\d")
        self.assertNotRegex(PROBES, r"'(PASS|FAIL|UNPROVEN)'")

    def test_all_moments_and_four_grants_are_probed(self):
        for m in ("M0", "M1", "M2", "M3"):
            self.assertIn("Try-Grants '%s'" % m, PROBES)
        for g in ("1-folder-by-name", "2-folder-by-sid", "3-file-by-name", "4-file-by-sid"):
            self.assertIn(g, PROBES)
        self.assertIn("sidtype", PROBES)

    def test_probe_b_covers_standard_user_and_both_uninstall_styles(self):
        self.assertIn("B1-standard-user", PROBES)
        self.assertIn("B2-uninstall-no-underscore", PROBES)
        self.assertIn("B2-uninstall-with-underscore", PROBES)

    def test_no_secret_and_no_throwaway_name_collision(self):
        self.assertIsNone(re.search(r"(?i)password|token=", PROBES))
        self.assertIn("EcosystemRunnerG5P", PROBES)

    def test_stub_reports_what_the_service_could_read(self):
        stub = (GUEST / "stub-service.cs").read_text(encoding="ascii")
        self.assertIn("probe-out", stub)
        self.assertIn("config.toml", stub)


if __name__ == "__main__":
    unittest.main()
