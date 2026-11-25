"""Guest proof, second run (ecosystem-control#64): the service proof module and the harmless test service."""
import contextlib
import io
import unittest
from pathlib import Path

from installer.guest import service_proof

GUEST = Path(__file__).resolve().parent.parent / "installer" / "guest"
ICACLS_OUT = (
    "C:\\ProgramData\\EcosystemRunnerG5\\config.toml NT SERVICE\\EcosystemRunnerG5:(R)\n"
    "                                               BUILTIN\\Administrators:(F)\n"
    "                                               NT AUTHORITY\\SYSTEM:(F)\n\nSuccessfully processed 1 files; Failed processing 0 files\n"
)


class ServiceProofTests(unittest.TestCase):
    def test_acl_parse_reads_each_account_and_right(self):
        self.assertEqual(service_proof.parse_aces(ICACLS_OUT), {
            "NT SERVICE\\EcosystemRunnerG5": "(R)", "BUILTIN\\Administrators": "(F)", "NT AUTHORITY\\SYSTEM": "(F)"})

    def test_inherited_entry_is_visible_to_the_check(self):
        text = ICACLS_OUT + "BUILTIN\\Users:(I)(RX)\n"
        self.assertIn("(I)", text)
        self.assertIn("BUILTIN\\Users", service_proof.parse_aces(text))

    def test_usage_error_for_unknown_action_or_wrong_argument_count(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(service_proof.main(["nothing"]), 2)
        self.assertIn("usage: see the module docstring", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(service_proof.main(["create5", "a"]), 2)
        self.assertIn("usage: see the module docstring", out.getvalue())

    def test_result_lines_are_one_line_with_three_fields(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            service_proof.result("SL-X", "PASS", "a\r\nb")
        self.assertEqual(buf.getvalue(), "SL-X|PASS|a b\n")

    def test_test_service_is_source_only_ascii_and_never_a_real_runner(self):
        text = (GUEST / "stub-service.cs").read_text("utf-8")
        text.encode("ascii")
        self.assertIn("crash.txt", text)
        self.assertNotIn("Http", text)
        self.assertNotIn("Socket", text)

    def test_service_proof_is_ascii_and_takes_no_secret(self):
        text = (GUEST / "service_proof.py").read_text("utf-8")
        text.encode("ascii")
        for word in ("password=", "token="):
            self.assertNotIn(word, text.lower())


class DriverFixTests(unittest.TestCase):
    def setUp(self):
        self.text = (GUEST / "guest-proof.ps1").read_text("utf-8")

    def test_denied_check_requires_an_integer_exit_code_and_an_exact_rc(self):
        self.assertNotIn("-match 'rc=1'", self.text)
        self.assertNotIn("-match '(?i)denied'", self.text)
        self.assertIn("read-config rc=(\\d+)", self.text)

    def test_programdata_finding_is_unproven_unless_the_attempt_ran(self):
        self.assertIn("$st = if (-not $ran) { 'UNPROVEN' }", self.text)
        self.assertIn("append=$appended", self.text)

    def test_local_mode_ignores_only_the_stub_probe_file(self):
        self.assertIn("EcosystemRunnerG5R\\probe.txt'", self.text)

    def test_standard_launch_has_a_second_method_and_work_dir_is_g5(self):
        self.assertIn("SeBatchLogonRight", self.text)
        self.assertIn("CreateProcessWithLogon", self.text)
        self.assertNotIn("g4", self.text)

    def test_service_proof_polls_instead_of_sleeping(self):
        text = (GUEST / "service_proof.py").read_text("utf-8")
        self.assertIn("wait_for(", text)
        self.assertNotIn("time.sleep(3)", text)


if __name__ == "__main__":
    unittest.main()
