"""GUEST6C1 (ecosystem-control#64): the harness blocks that prove main 775e4d0 on Windows: five program paths (PR 112), the licence record and
the image pull with a stub engine (PR 107), the declined administrator prompt (PR 116) and the record comparison. Static checks and the
host-side parts only; the guest run is the proof."""
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from installer.guest import record_probe

ROOT = Path(__file__).resolve().parent.parent
GUEST = ROOT / "installer" / "guest"
NSIS = ROOT / "installer" / "nsis"
GATE = (GUEST / "gate-probes.ps1").read_text(encoding="ascii")
STUB = (GUEST / "stub-engine.cs").read_text(encoding="ascii")
UAC = (GUEST / "uac-drive.cs").read_text(encoding="ascii")
PROBE = (GUEST / "record_probe.py").read_text(encoding="ascii")
CODES = json.loads((ROOT / "installer" / "schema.json").read_text(encoding="utf-8"))["exit_codes"]


def part(start, end):
    return GATE.split(start, 1)[1].split(end, 1)[0]


class PathVariants(unittest.TestCase):
    def test_five_paths_each_started_three_ways_with_the_codes_of_the_schema(self):
        block = part("# (h) PATH VARIANTS", "# (i) LICENCE AND IMAGE")
        paths = re.findall(r"@\('([a-z\-]+)', '(C:\\Temp\\[^']*(?:''[^']*)*\.exe)'\)", block)
        self.assertEqual([p[1] for p in paths], [
            "C:\\Temp\\setup - Copy.exe", "C:\\Temp\\a /x b\\setup.exe", "C:\\Temp\\o''brien\\setup.exe",
            "C:\\Temp\\x y\\setup.exe", "C:\\Temp\\$z\\setup.exe"])
        wanted = re.search(r"\$pathWanted = @\((.*)\)", block).group(1)
        self.assertEqual(re.findall(r"'(/[A-Z_]+=[a-z]+)', (\d+)\)", wanted),
                         [("/MODE=local", "0"), ("/MODE=bogus", "30"), ("/GITHUB_TOKEN=x", "32")])
        self.assertEqual(CODES["ok"], 0)
        self.assertEqual(CODES["bad-value"], 30)
        self.assertEqual(CODES["secret-on-command-line"], 32)

    def test_a_failing_path_records_the_command_line_and_the_head_of_the_log(self):
        block = part("# (h) PATH VARIANTS", "# (i) LICENCE AND IMAGE")
        self.assertIn("command line: `\"$pathExe`\" $pathArgs; log head: $(Log-Head)", block)
        self.assertIn("Select-Object -First 3", block)
        self.assertIn('Res "GATE-h-path-$pathTag" \'FAIL\'', block)

    def test_the_apostrophe_and_dollar_folders_are_made_without_expansion(self):
        block = part("# (h) PATH VARIANTS", "# (i) LICENCE AND IMAGE")
        self.assertIn("foreach ($d in 'C:\\Temp\\o''brien', 'C:\\Temp\\x y', 'C:\\Temp\\$z') {", block)
        self.assertIn("[IO.File]::Copy($installer, (Join-Path $d 'setup.exe'), $true)", block)

    def test_a2_carries_text_keys_only_because_any_image_key_reaches_the_licence_gate(self):
        a2 = [ln for ln in GATE.splitlines() if ln.startswith("$a2 = ")]
        self.assertEqual(len(a2), 1)
        self.assertNotIn("IMAGE_", a2[0])
        self.assertIn("/PARTNER_ID=guest6b /LABVIEW_VERSION=2025", a2[0])


class LicenceAndImage(unittest.TestCase):
    def test_exit_codes_match_the_schema(self):
        self.assertEqual(CODES["image-not-pinned"], 36)
        self.assertEqual(CODES["licence-not-accepted"], 35)
        self.assertEqual(CODES["image-pull-failed"], 46)
        for ident, code in (("GATE-i-L1-unpinned-pair-36", 36), ("GATE-i-L3-pull-fails-46", 46), ("GATE-i-L4-no-engine-46", 46),
                            ("GATE-i-L5-one-answer-35", 35)):
            self.assertIn("'%s'" % ident, GATE)
            self.assertTrue(ident.endswith(str(code)), ident)
        self.assertIn("\"$($l1.Rc)\" -eq '36'", GATE)
        self.assertEqual(GATE.count("-eq '46'"), 2)
        self.assertIn("-ne '35'", GATE)

    def test_the_stub_sits_where_image_nsh_searches_and_uses_the_files_of_the_harness(self):
        image = (NSIS / "image.nsh").read_text(encoding="utf-8")
        self.assertIn('IfFileExists "$PROGRAMFILES64\\Docker\\Docker\\resources\\bin\\docker.exe" desktop', image)
        self.assertIn('IfFileExists "$PROGRAMFILES64\\Docker\\docker.exe" engine', image)
        self.assertIn("$engineDesktop = 'C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe'", GATE)
        self.assertIn("$engineFixed = 'C:\\Program Files\\Docker\\docker.exe'", GATE)
        for name in ("stub-engine.txt", "stub-rc.txt"):
            self.assertIn("C:\\Temp\\" + name, STUB)
            self.assertIn("'C:\\Temp\\" + name + "'", GATE)

    def test_the_stub_engine_only_records_and_returns(self):
        self.assertIn("File.AppendAllText(log, Environment.CommandLine", STUB)
        self.assertIn("string.Join(\"|\", args)", STUB)
        self.assertIn("int.Parse(File.ReadAllText(rcFile).Trim())", STUB)
        for word in ("Process", "Socket", "WebClient", "HttpClient", "http"):
            self.assertNotIn(word, STUB)

    def test_the_pull_reference_is_the_pinned_repository_at_the_digest(self):
        self.assertIn("$pinRef = 'registry.example.test/ni/labview@sha256:' + ('0123456789abcdef' * 4)", GATE)
        self.assertIn("$want2 = \"args: pull|$pinRef\"", GATE)
        self.assertIn("$l2.Calls.Count -eq 1 -and $l2.Calls[0] -eq $want2", GATE)
        pull = (NSIS / "image.nsh").read_text(encoding="utf-8")
        self.assertIn("nsExec::Exec '\"$ImgEngine\" pull $ImgRef'", pull)

    def test_the_stub_is_removed_after_every_case_and_the_guest_is_left_clean(self):
        run = part("function Image-Run", "# L1: release build")
        self.assertLess(run.index("$r = Start-Timed $pinned"), run.index("Drop-Engine"))
        self.assertIn("Remove-Item -LiteralPath $engineFixed -Force", part("function Drop-Engine", "# One install of the pinned build"))
        self.assertTrue(part("# (i) LICENCE AND IMAGE", "# ---- the five NSIS probes").rstrip().endswith("Clean-Gate"))

    def test_without_a_pinned_build_or_a_compiler_l2_to_l5_are_unproven_with_the_reason(self):
        self.assertIn("no pinned installer in the payload (installer-pinned.exe.b64)", GATE)
        self.assertIn("foreach ($id in 'GATE-i-L2-pull-ok-0', 'GATE-i-L3-pull-fails-46', 'GATE-i-L4-no-engine-46', 'GATE-i-L5-one-answer-35') { Res $id 'UNPROVEN' $stubWhy }", GATE)
        for reason in ("a real container engine is installed in this clone", "the stub engine did not compile"):
            self.assertIn(reason, GATE)

    def test_the_pinned_installer_is_never_a_committed_file(self):
        self.assertIn("installer/guest/payload/", (ROOT / ".gitignore").read_text(encoding="utf-8"))
        self.assertIn("Decode 'installer-pinned.exe'", GATE)

    def test_l1_is_judged_on_the_exit_code_and_both_observed_shapes_are_named(self):
        block = part("# L1: release build", "# L2 to L5 need")
        self.assertIn("'nothing written'", block)
        self.assertIn("'install complete with the record written'", block)
        self.assertIn("'partial state'", block)
        self.assertIn("Uninstall-Poll", block)

    def test_only_the_values_x_and_yes_are_ever_given_to_a_licence_key(self):
        for name, value in re.findall(r"/((?:NI_LICENCE_HELD|ENGINE_LICENCE_ACCEPTED))=([^'\s\"]+)", GATE):
            self.assertEqual(value, "yes", name)


class RecordProbe(unittest.TestCase):
    NSIS_BYTES = b'{"ni_development_licence_held": "yes", "utc": "2026-11-22T09:20:00Z"}\n'

    def facts(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "nsis" / "licence-record.json"
            record.parent.mkdir()
            record.write_bytes(data)
            return dict(record_probe.compare(record, Path(tmp) / "python", record.parent))

    def test_the_python_writer_gives_the_same_json_for_the_same_utc_string(self):
        facts = self.facts(self.NSIS_BYTES)
        self.assertEqual(facts["utc_found"], "True")
        self.assertEqual(facts["identical_ignoring_line_end"], "True")
        self.assertEqual(facts["nsis_line_end"], "LF")

    def test_a_different_line_end_is_reported_and_is_the_only_difference_that_is_ignored(self):
        facts = self.facts(self.NSIS_BYTES.replace(b"\n", b"\r\n"))
        self.assertEqual(facts["nsis_line_end"], "CRLF")
        self.assertEqual(facts["identical_ignoring_line_end"], "True")
        changed = self.facts(self.NSIS_BYTES.replace(b'"yes"', b'"no"'))
        self.assertEqual(changed["identical_ignoring_line_end"], "False")

    def test_a_record_without_a_date_is_reported_not_guessed(self):
        facts = self.facts(b'{"ni_development_licence_held": "yes"}\n')
        self.assertEqual(facts["utc_found"], "False")
        self.assertNotIn("identical", facts)

    def test_the_reader_path_is_the_state_dir_plus_the_record_name(self):
        facts = self.facts(self.NSIS_BYTES)
        self.assertTrue(facts["reader_path"].endswith("licence-record.json"))
        self.assertIn("reader_path_is_the_nsis_file_when_state_dir_is_the_footprint_folder", " ".join(facts))
        self.assertEqual(facts["reader_path_is_the_nsis_file_when_state_dir_is_the_footprint_folder"], "True")

    def test_the_probe_opens_no_network_and_is_ascii(self):
        for word in ("socket", "urllib", "http", "subprocess", "requests"):
            self.assertNotIn(word, PROBE)
        self.assertEqual(PROBE, PROBE.encode("ascii").decode("ascii"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(record_probe.main(["record_probe"]), 2)


class DeclinedPrompt(unittest.TestCase):
    def test_the_harness_reads_only_result_keys_the_driver_writes(self):
        keys = set(re.findall(r"\$uac\['([a-z_0-9]+)'\]", GATE)) | set(re.findall(r"\$uac\.ContainsKey\('([a-z_0-9]+)'\)", GATE))
        self.assertTrue(keys)
        written = set(re.findall(r'Result\("([a-z_0-9]+)"', UAC))
        self.assertEqual(keys - written, set())

    def test_the_driver_texts_exist_in_the_installer_sources(self):
        elevate = (NSIS / "elevate.nsh").read_text(encoding="utf-8")
        self.assertIn("The next step needs administrator rights", UAC)
        self.assertIn("The next step needs administrator rights", elevate)
        self.assertIn("NOT started", GATE)
        self.assertIn("NOT started", elevate)
        self.assertIn('ExecShell "runas"', elevate)
        screens = (NSIS / "screens.nsh").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'FindButton\(main, "([^"]+)"\)', UAC), ["Local only (no forge)"])
        self.assertIn("Local only (no forge)", screens)

    def test_the_driver_clicks_next_and_cancel_only(self):
        self.assertEqual(sorted(set(re.findall(r"Click\([a-zA-Z]+, (ID[A-Z]+)\)", UAC))), ["IDCANCEL", "IDOK"])
        self.assertIn("IDOK = 1", UAC)
        self.assertIn("IDCANCEL = 2", UAC)
        self.assertNotIn("SendKeys", UAC)

    def test_it_runs_as_the_standard_account_without_a_slash_s_and_waits_at_most_180_seconds(self):
        block = GATE.split("# (j) DECLINED ADMINISTRATOR PROMPT", 1)[1]
        self.assertIn('Run-AsStdLong $uacExe "$installer $uacLog /SIGNER=$sig" 180', block)
        self.assertNotIn("/S ", block.split("Run-AsStdLong $uacExe", 1)[1].split("\n", 1)[0])
        self.assertIn("-RunLevel Limited", block)
        self.assertIn("ConsentPromptBehaviorUser -Value 0", block)

    def test_the_password_only_goes_to_the_task_registration_and_is_never_printed(self):
        self.assertEqual(GATE.count("GetNetworkCredential().Password"), 1)
        self.assertRegex(GATE, r"Register-ScheduledTask [^\n]*-Password \$cred\.GetNetworkCredential\(\)\.Password")
        for printer in ("Write-Host", "Write-Output", "Out-File"):
            self.assertNotIn(printer, GATE)

    def test_without_a_standard_account_or_a_page_the_three_items_are_unproven_with_a_reason(self):
        block = GATE.split("# (j) DECLINED ADMINISTRATOR PROMPT", 1)[1]
        self.assertIn("if ($uacWhy) { foreach ($id in $uacIds) { Res $id 'UNPROVEN' $uacWhy } }", block)
        self.assertIn("'no standard account in this clone'", block)
        self.assertIn("did not reach the elevation page", block)
        self.assertEqual(re.findall(r"'(GATE-j-uac-[a-z\-]+)'", block), ["GATE-j-uac-a-stays-open", "GATE-j-uac-b-box-exists", "GATE-j-uac-c-exit-code-after-cancel"])

    def test_the_new_sources_are_ascii_and_hold_no_url(self):
        for text in (STUB, UAC):
            self.assertEqual(text, text.encode("ascii").decode("ascii"))
            self.assertNotRegex(text, r"https?://")


if __name__ == "__main__":
    unittest.main()
