"""Gate probes (ecosystem-control#64, GUEST6B): the silent gates of the real installer and five tiny NSIS probes run in the guest behind
-GateProbes. Static checks only; the guest run is the proof. Gate items count (GATE-*), every PROBE-* line is INFO."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from installer.guest import pack

ROOT = Path(__file__).resolve().parent.parent
GUEST = ROOT / "installer" / "guest"
DRIVER = (GUEST / "guest-proof.ps1").read_text(encoding="ascii")
GATE = (GUEST / "gate-probes.ps1").read_text(encoding="ascii")
CODES = json.loads((ROOT / "installer" / "schema.json").read_text(encoding="utf-8"))["exit_codes"]


class FailFastGate(unittest.TestCase):
    def test_first_silent_start_has_a_40_second_limit_and_runs_in_a_whole_run_too(self):
        self.assertIn("if ($GateProbes -or (-not $ProbesOnly -and $UpdateLoop -eq 0)) {", DRIVER)
        self.assertIn('Start-Timed $installer "/S /SIGNER=$sig" 40', DRIVER)
        self.assertIn("Res 'GUEST6B-first-silent-start' 'PASS'", DRIVER)

    def test_a_hang_is_measured_killed_and_ends_the_run(self):
        hang = DRIVER.split("'FAIL' \"HANG", 1)[1].split("}", 1)[0]
        self.assertIn("exit 0", hang)
        before = DRIVER.split("'FAIL' \"HANG", 1)[0]
        self.assertIn("Cpu-Over $ff.Proc 10", before.rsplit("if ($ff.Done)", 1)[1])
        self.assertIn(".Kill()", before.rsplit("if ($ff.Done)", 1)[1])

    def test_a_program_that_cannot_start_is_reported_not_mistaken_for_a_hang(self):
        self.assertIn("catch { return [pscustomobject]@{ Proc = $null; Done = $true; Rc = ('not started: '", DRIVER)
        self.assertIn("if ($ff.Rc -isnot [int]) { Res 'GUEST6B-first-silent-start' 'FAIL' \"the installer could not be started", DRIVER)

    def test_gate_probes_are_dot_sourced_only_behind_the_switch(self):
        self.assertRegex(DRIVER, r"if \(\$GateProbes\) \{\s+\. \(Join-Path \$tree 'installer\\guest\\gate-probes\.ps1'\)\s+exit 0")
        self.assertEqual(DRIVER.count("gate-probes.ps1'"), 1)
        self.assertIn("if (-not $ProbesOnly -and -not $GateProbes) {", DRIVER)


class GateItems(unittest.TestCase):
    def test_every_counted_item_is_a_gate_and_every_probe_line_is_info(self):
        found = re.findall(r"Res [\"']([^\"']+)[\"'] '(PASS|FAIL|UNPROVEN|INFO)'", GATE)
        self.assertTrue(found)
        for ident, state in found:
            if ident.startswith("PROBE-"):
                self.assertEqual(state, "INFO", ident)
            else:
                self.assertTrue(ident.startswith("GATE-") or ident == "$id", ident)
                self.assertIn(state, ("PASS", "FAIL"), ident)

    def test_items_a_to_g_exist_and_f_is_info_only(self):
        for letter in "abcdefg":
            if letter == "f":
                self.assertIn("PROBE-f-url-", GATE)
            else:
                self.assertRegex(GATE, r"GATE-%s-" % letter)
        self.assertNotIn("known bug #110, expected to fail", GATE)

    def test_expected_exit_codes_match_the_schema(self):
        wanted = {"b": "secret-on-command-line", "c": "secret-from-file-or-stdin", "d": "unknown-key", "e": "bad-value"}
        calls = re.findall(r"Gate-Many 'GATE-([a-z])-[a-z\-]+-(\d+)' '[^']+' (\d+) @\(", GATE)
        self.assertEqual(sorted(c[0] for c in calls), sorted(wanted))
        for letter, in_id, expect in calls:
            self.assertEqual(int(in_id), CODES[wanted[letter]], letter)
            self.assertEqual(int(expect), CODES[wanted[letter]], letter)
        self.assertEqual(CODES["ok"], 0)
        self.assertIn("\"$($a1.Rc)\" -eq '0'", GATE)

    def test_secret_values_are_never_real(self):
        pairs = re.findall(r"/([A-Z_]*(?:TOKEN|PASSWORD|KEY|SECRET)[A-Z_]*)=([^'\s,)]+)", GATE)
        self.assertTrue(pairs)
        for name, value in pairs:
            self.assertIn(value, ("x", "C:\\g5\\none.txt"), name)

    def test_no_url_literal_and_ascii_only(self):
        self.assertNotRegex(GATE, r"https?://")
        self.assertIn("'https' + '://github.com/AcmeOrg/Repo'", GATE)
        self.assertEqual(GATE, GATE.encode("ascii").decode("ascii"))

    def test_the_slash_folder_is_made_with_the_extended_syntax_and_started_by_the_typed_path(self):
        self.assertIn("[IO.Directory]::CreateDirectory('\\\\?\\C:\\Temp\\a \\x b')", GATE)
        self.assertIn("@('slash-folder', 'C:\\Temp\\a /x b\\setup.exe')", GATE)
        self.assertIn("@('setup-copy', 'C:\\Temp\\setup - Copy.exe')", GATE)
        self.assertIn("Run-Gate $pathExe $pathArgs", GATE)

    def test_the_log_is_looked_for_where_log_nsh_writes_it(self):
        self.assertIn("$stepLog = Join-Path $footprintFolder 'steps.jsonl'", GATE)
        self.assertIn("$userLogDir = Join-Path $env:APPDATA 'EcosystemRunner'", GATE)
        self.assertIn("roaming-log-folder=", GATE)

    def test_the_guest_is_left_clean(self):
        self.assertIn("sc.exe delete EcosystemRunner", GATE)
        self.assertTrue(GATE.split("# ---- the five NSIS probes")[0].rstrip().endswith("Clean-Gate"))

    def test_the_no_argument_start_is_killed_after_its_cpu_is_measured(self):
        spin = GATE.split("# (g)", 1)[1].split("# (h)", 1)[0]
        self.assertIn("Cpu-Over $g.Proc 10", spin)
        self.assertLess(spin.index("Cpu-Over"), spin.index(".Kill()"))


class NsisProbes(unittest.TestCase):
    def test_five_probe_sources_each_under_40_lines_and_packed(self):
        self.assertEqual(pack.PROBES, ("p1", "p2", "p3", "p4", "p5"))
        for name in pack.PROBES:
            text = (GUEST / ("probe-%s.nsi" % name)).read_text(encoding="ascii")
            self.assertLess(len(text.splitlines()), 40, name)
            self.assertIn("RequestExecutionLevel user", text)
            self.assertIn("SilentInstall silent", text)
            self.assertNotRegex(text, r"https?://")
            self.assertIn("probe-%s.exe" % name, GATE)

    def test_each_probe_asks_the_question_of_the_brief(self):
        read = lambda n: (GUEST / ("probe-%s.nsi" % n)).read_text(encoding="ascii")
        self.assertIn("mklink /J", read("p1"))
        self.assertIn("RMDir /r", read("p1"))
        self.assertLess(read("p1").index("\n  IfFileExists"), read("p1").index("\n  RMDir /r"))
        self.assertIn('ExecShell "runas" "$EXEPATH" "/X"', read("p2"))
        self.assertIn("IfErrors", read("p2"))
        p3 = read("p3")
        self.assertIn('"E+$R8"', p3)
        self.assertEqual(p3.count("IntCmp $R8 50"), 2)
        p4 = read("p4")
        self.assertIn("SetErrorLevel 35", p4)
        for word in ("Quit", "Abort", "Call QuitHere"):
            self.assertIn(word, p4)
        self.assertIn("FileRead", read("p5"))
        self.assertIn("('x' * 1030)", GATE)

    def test_p2_runs_last_as_the_standard_account_and_never_counts(self):
        self.assertGreater(GATE.index("Decode 'probe-p2.exe'"), GATE.index("Run-Probe 'P5-fileread'"))
        self.assertIn("Run-AsStd $p2 ''", GATE)
        self.assertIn("'PROBE-P2-declined-elevation' 'INFO'", GATE)


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell is not installed here")
class ParseTests(unittest.TestCase):
    def test_both_scripts_parse(self):
        for name in ("guest-proof.ps1", "gate-probes.ps1"):
            command = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e); "
                       "$e | ForEach-Object { $_.Message }; exit $e.Count" % (GUEST / name))
            done = subprocess.run(["pwsh", "-NoProfile", "-Command", command], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, name + ": " + done.stdout)


if __name__ == "__main__":
    unittest.main()
