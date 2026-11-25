"""Guest proof for the install folder lock (SL-13, ecosystem-control#64): the offline assertion code of service_proof and the driver wiring."""
import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

from installer.guest import service_proof as sp

GUEST = Path(__file__).resolve().parent.parent / "installer" / "guest"
NAME = "EcosystemRunner"
SID = sp.service_sid(NAME)
GOOD = ("C:\\ProgramData\\EcosystemRunner NT AUTHORITY\\SYSTEM:(OI)(CI)(F)\n"
        "                               BUILTIN\\Administrators:(OI)(CI)(F)\n"
        "                               %s:(OI)(CI)(RX)\n\nSuccessfully processed 1 files; Failed processing 0 files\n")
CHILD = ("C:\\ProgramData\\EcosystemRunner\\program NT AUTHORITY\\SYSTEM:(I)(OI)(CI)(F)\n"
         "                               BUILTIN\\Administrators:(I)(OI)(CI)(F)\n"
         "                               NT SERVICE\\EcosystemRunner:(I)(OI)(CI)(RX)\n")


class AclProblems(unittest.TestCase):
    def test_service_sid_is_the_known_value(self):
        self.assertEqual(SID, "S-1-5-80-1994812370-2417282942-4224635210-1542273099-3328997366")

    def test_expected_folder_acl_with_a_raw_sid_or_the_resolved_name_is_clean(self):
        self.assertEqual(sp.acl_problems(GOOD % SID, NAME, True), [])
        self.assertEqual(sp.acl_problems(GOOD % "NT SERVICE\\EcosystemRunner", NAME, True), [])

    def test_users_entry_or_inherited_entry_on_the_folder_is_a_problem(self):
        text = (GOOD % SID) + "BUILTIN\\Users:(I)(OI)(CI)(RX)\nBUILTIN\\Users:(I)(CI)(WD,AD,WEA,WA)\n"
        found = " ".join(sp.acl_problems(text, NAME, True))
        self.assertIn("unexpected principal BUILTIN\\Users", found)
        self.assertIn("inherited", found)

    def test_missing_service_entry_or_wrong_rights_is_a_problem(self):
        no_service = "\n".join(GOOD.splitlines()[:2]) + "\n"
        self.assertTrue(any("SVC expected" in p for p in sp.acl_problems(no_service, NAME, True)))
        writable = GOOD % ("NT SERVICE\\EcosystemRunner").replace("(RX)", "(M)")
        self.assertTrue(sp.acl_problems(GOOD.replace("(RX)", "(M)") % SID, NAME, True))
        self.assertTrue(writable)

    def test_children_may_inherit_the_three_principals_but_nothing_else(self):
        self.assertEqual(sp.acl_problems(CHILD, NAME, False), [])
        bad = CHILD + "NT AUTHORITY\\Authenticated Users:(I)(M)\nEveryone:(I)(R)\nCREATOR OWNER:(I)(F)\n"
        problems = sp.acl_problems(bad, NAME, False)
        self.assertEqual(len(problems), 3)

    def test_children_service_account_must_stay_read_only(self):
        self.assertTrue(sp.acl_problems(CHILD.replace("(RX)", "(F)"), NAME, False))

    def test_empty_output_is_not_a_pass(self):
        self.assertEqual(sp.acl_problems("Successfully processed 0 files", NAME, True), ["no entries parsed"])

    def test_aclcheck_reports_missing_paths_and_takes_three_arguments(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sp.aclcheck(NAME, "Z:\\does-not-exist", "SL-13-x")
            code = sp.main(["aclcheck", "a"])
        self.assertIn("SL-13-x|UNPROVEN|precondition not met, nothing to check: folder missing; program missing; runner.exe missing", buf.getvalue())
        self.assertEqual(code, 2)


class AclCheckVerdicts(unittest.TestCase):
    def run_check(self, problems, present):
        buf = io.StringIO()
        with mock.patch.object(sp, "acl_report", return_value=(problems, [])), mock.patch.object(sp, "service_present", return_value=present), \
                contextlib.redirect_stdout(buf):
            sp.aclcheck(NAME, "C:\\x", "SL-13-y")
        return buf.getvalue().strip()

    def test_missing_path_is_unproven(self):
        self.assertIn("SL-13-y|UNPROVEN|", self.run_check(["runner.exe missing"], True))

    def test_only_a_missing_service_entry_without_the_service_is_unproven(self):
        out = self.run_check(["folder: SVC expected ['CI', 'OI', 'RX'] got []"], False)
        self.assertIn("SL-13-y|UNPROVEN|", out)

    def test_missing_service_entry_with_the_service_present_is_a_fail(self):
        self.assertIn("SL-13-y|FAIL|", self.run_check(["folder: SVC expected ['CI', 'OI', 'RX'] got []"], True))

    def test_a_users_entry_is_a_fail_even_without_the_service(self):
        out = self.run_check(["folder: SVC expected [] got []", "folder: unexpected principal BUILTIN\\Users ['RX']"], False)
        self.assertIn("SL-13-y|FAIL|", out)

    def test_clean_acl_passes(self):
        self.assertIn("SL-13-y|PASS|", self.run_check([], False))


class DriverWiring(unittest.TestCase):
    def setUp(self):
        self.text = (GUEST / "guest-proof.ps1").read_text("ascii")

    def test_every_sl13_result_is_reported(self):
        for item in ("SL-13-acl-as-installed", "SL-13-acl-after-upgrade", "SL-13-upgrade-children-lose-inherited-users",
                     "SL-13-uninstall-removes-whole-folder", "SL-13-precreated-folder-$variant"):
            self.assertIn(item, self.text)
        for variant in ("empty", "junction", "file"):
            self.assertIn("'%s'" % variant, self.text)
        text = (GUEST / "service_proof.py").read_text("ascii")
        for item in ("SL-13-acl-after-update", "SL-13-acl-after-failed-update", "SL-13-acl-identical-after-update-and-failed-update",
                     "SL-13-children-lose-inherited-users"):
            self.assertIn(item, text)

    def test_precreated_case_requires_exit_39_and_an_untouched_folder(self):
        self.assertIn("-eq '39'", self.text)
        self.assertIn("junction target entries", self.text)

    def test_standard_user_write_test_covers_program_folder(self):
        self.assertIn("create-folder-in-program", self.text)

    def test_proof_without_result_line_is_unproven(self):
        self.assertIn("$seen -notcontains $id", self.text)
        self.assertIn("returned no result line", self.text)
        self.assertIn("@('SL-13-acl-as-installed')", self.text)
        self.assertIn("@('SL-13-acl-after-upgrade')", self.text)

    def test_upgrade_results_need_a_finished_upgrade_and_runner_exe(self):
        self.assertIn("-not (Test-Path $runnerExe)", self.text)
        self.assertIn("if (-not $upRan) {", self.text)
        self.assertIn("the upgrade did not finish", self.text)
        self.assertIn("SL-13-upgrade-run", self.text)

    def test_postusers_pattern_matches_authenticated_users_and_says_so(self):
        self.assertIn("Authenticated Users:", self.text)
        self.assertNotIn("'(?i)Users:|Everyone'", self.text)

    def test_precreated_checks_owner_and_clean_start_and_never_recurses_past_a_failed_rmdir(self):
        self.assertIn('-or ($owner -notlike "*\\$stdUser") -or', self.text)
        self.assertIn("function Remove-Case", self.text)
        self.assertIn("if (Test-Path $link) { return $false }", self.text)
        self.assertEqual(self.text.count("Remove-Item -LiteralPath $footprintFolder -Recurse"), 1)

    def test_uninstall_result_is_unproven_without_service_or_uninstaller(self):
        self.assertIn("-not $svcMade -or -not $hadUninstaller", self.text)


if __name__ == "__main__":
    unittest.main()


class UpgradeSetup(unittest.TestCase):
    def test_old_state_inherits_users_from_programdata_instead_of_an_explicit_entry(self):
        driver = (GUEST / "guest-proof.ps1").read_text(encoding="ascii")
        self.assertIn("icacls $footprintFolder /reset | Out-Null", driver)
        self.assertNotIn("/grant '*S-1-5-32-545", driver)
