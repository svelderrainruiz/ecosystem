"""CTR-8: source parity and fail-closed container wiring, not a Windows measurement."""
import re
import unittest
from pathlib import Path

from installer.guest import container
from tests.guest_pwsh import requires_pwsh, run_functions

ROOT = Path(__file__).resolve().parent.parent
GUEST = ROOT / "installer" / "guest"
SCRIPT = GUEST / "install-edge.ps1"
DRIVER = SCRIPT.read_text(encoding="ascii")
SOURCE = (GUEST / "guest-proof.ps1").read_text(encoding="ascii")
PROBES = (GUEST / "probes.ps1").read_text(encoding="ascii")
CHECKLIST = (GUEST / "CHECKLIST.md").read_text(encoding="utf-8")
PASS_LINE = "[verdict] c-install-edge PASS"
PORTED = ("GUEST6B-first-silent-start", "SL-13-upgrade-run", "SL-13-uninstall-removes-whole-folder",
          "SL-7a-steplog-path-utc", "SL-7b-zone-name-in-log")
PROBE_ROWS = ("A-M0-residue", "B-registered-strings", "B2-uninstall-no-underscore", "B2-uninstall-with-underscore")
ROWS = (PORTED[0], "SL-3", *PORTED[1:], *PROBE_ROWS)
DECISIONS = {
    "GUEST6B-first-silent-start": [
        """if ($ff.Done -and $ff.Rc -is [int]) { Res 'GUEST6B-first-silent-start' 'PASS' "rc=$($ff.Rc) seconds=$($ff.Sec) limit=40" }""",
        """elseif ($ff.Done) { Res 'GUEST6B-first-silent-start' 'FAIL' 'no integer exit'; $skipProduct = $true }""",
        """Res 'GUEST6B-first-silent-start' 'FAIL' "timeout=True seconds=$($ff.Sec) cpu_seconds_over_10=$cpu" """.strip(),
    ],
    "SL-13-upgrade-run": [
        """Res 'SL-13-upgrade-run' $(if ($upRan -and "$upRc" -eq '0') { 'PASS' } else { 'FAIL' }) "rc=$upRc expected=0; numeric exit only, not ACL evidence" """.strip(),
    ],
    "SL-13-uninstall-removes-whole-folder": [
        """if (-not $svcMade -or -not $hadUninstaller) { Res 'SL-13-uninstall-removes-whole-folder' 'FAIL' "precondition not met; $facts" }""",
        """elseif ((Test-Path $programDir) -eq $false -and $folderGone) { Res 'SL-13-uninstall-removes-whole-folder' 'PASS' $facts }""",
        """else { Res 'SL-13-uninstall-removes-whole-folder' 'FAIL' $facts }""",
    ],
    "SL-7a-steplog-path-utc": [
        """if ($zoneA -and $zoneB -and $zoneC) { Res 'SL-7a-steplog-path-utc' 'PASS' $facts }""",
        """else { Res 'SL-7a-steplog-path-utc' 'FAIL' $facts }""",
    ],
    "SL-7b-zone-name-in-log": [
        """if ($script:zoneMiss -eq 0 -and $script:zoneRuns -eq 3) { Res 'SL-7b-zone-name-in-log' 'PASS' $facts }""",
        """else { Res 'SL-7b-zone-name-in-log' 'FAIL' $facts }""",
    ],
}


def check_pass_line(text):
    written = re.findall(r"Log '(\[verdict\] c-install-edge [^']*)'", text)
    assert written == [PASS_LINE], written
    marker, passing = container.VERDICT_RULES["install-edge.ps1"]
    assert re.match(marker, written[0]) and re.fullmatch(passing, written[0])
    assert container.judge("install-edge.ps1", written) == (True, "one passing verdict line")
    assert "Log ('[verdict] c-install-edge FAIL ' + ($failed -join ','))" in text


def check_parity(text):
    assert set(DECISIONS) == set(PORTED)
    for row in PORTED:
        decisions = [line.strip() for line in text.splitlines() if f"Res '{row}'" in line]
        assert decisions == DECISIONS[row], (row, decisions)
    for expression in (
        '$ff = Start-Timed $installer "/S /SIGNER=$sig" 40',
        '$cpu = Cpu-Over $ff.Proc 10',
        '$upRan = "$upRc" -match \'^-?\\d+$\'',
        """$(if ($upRan -and "$upRc" -eq '0') { 'PASS' } else { 'FAIL' })""",
        'for ($i = 0; $i -lt 90; $i++)',
        'if (-not $svcMade -or -not $hadUninstaller)',
        'elseif ((Test-Path $programDir) -eq $false -and $folderGone)',
        '$ok = $lines.Count -eq 3',
        """$ok = $ok -and $records[2].step -ceq 'A"B' -and $records[2].command -ceq 'A\\Q'""",
        """if ($ln -notmatch ('"zone": "' + [regex]::Escape($key) + '"'))""",
        """if ($ln -match '"started": "([0-9T:\\-]+)\\+00:00"')""",
        """if ([Math]::Abs(([DateTime]::SpecifyKind($t, 'Utc') - [DateTime]::UtcNow).TotalSeconds) -gt 180)""",
        "$zoneA = Check-Log 'zone-default'", "$zoneB = Check-Log 'zone-weurope'",
        "$zoneC = Check-Log 'zone-pacific'", 'if ($zoneA -and $zoneB -and $zoneC)',
    ):
        assert expression in SOURCE, expression
        assert expression in text, expression
    assert re.search(r'^\s*\$ff = Start-Timed \$installer "/S /SIGNER=\$sig" 40\s*$', text, re.M)
    for expression in ('$upRc = Run-Exe $installer "/S /SIGNER=$sig"', '$unRc = Run-Exe $uninstallExe \'/S\'',
                       '$r = Start-Timed $exe $argText 120', "Set-Zone 'W. Europe Standard Time'",
                       "Set-Zone 'Pacific Standard Time'", "if ($zoneChanged) { Set-Zone $originalZone }"):
        assert expression in text, expression


def first_start_block(text):
    return text[text.index("    $phase = 'first-start'"):text.index("    if (-not $skipProduct) {")]


FORBIDDEN = (
    r"\bmklink\b", r"-ItemType\s+['\"]?(Junction|SymbolicLink|HardLink)", r"Create(Symbolic|Hard)Link", r"\bfsutil\b",
    r"probe-p[12]", r"Invoke-WebRequest", r"Invoke-RestMethod", r"\b(iwr|irm|curl|wget|ping|nslookup|tracert)\b",
    r"Test-(Net)?Connection", r"Start-BitsTransfer", r"Net\.(WebClient|Http|Sockets|WebRequest)", r"https?://",
    r"\bwhoami\b", r"\$env:(USERNAME|USERDOMAIN|COMPUTERNAME)", r"NTAccount", r"GetCurrent\(\)\.Name",
    r"\[Environment\]::(UserName|UserDomainName|MachineName)", r"Get-Acl", r"\.Owner\b", r"\$_\.Exception\.Message",
    r"\[end\]", r"installer-pinned", r"stub-engine", r"New-LocalUser", r"PSCredential", r"Run-AsStd",
    r"Register-ScheduledTask", r"-Verb\s+RunAs", r"Windows\.Forms",
)


def check_forbidden(text):
    hits = [p for p in FORBIDDEN if re.search(p, text, re.I)]
    assert not hits, hits
    for raw in ('$lines', '$live', '$o', '$key', '$originalZone', '$signerFile', '$footprintFolder'):
        assert not re.search(r"^\s*Log\s+" + re.escape(raw) + r"\b", text, re.M), raw


class InstallEdgeDriver(unittest.TestCase):
    def test_pass_line_is_read_from_driver_and_judged_exactly(self):
        check_pass_line(DRIVER)
        for lines in ([], ["PASS"], [PASS_LINE, PASS_LINE], ["[verdict] c-install-edge FAIL SL-3"]):
            self.assertFalse(container.judge("install-edge.ps1", lines)[0])

    def test_every_requested_row_is_registered_and_has_output(self):
        registered = re.findall(r"'([^']+)'", re.search(r"^\$rows = @\((.*?)\)$", DRIVER, re.M | re.S).group(1))
        self.assertEqual(registered, list(ROWS))
        self.assertIn('Log "ROW $id $state $detail"', DRIVER)
        for row in ROWS:
            self.assertIn(f"Res '{row}'", DRIVER)
        for row in PORTED:
            entry = next(line for line in CHECKLIST.splitlines() if line.startswith(f"| {row} |"))
            self.assertIn("| container-provable |", entry)
            self.assertIn("case `install-edge`", entry)
            self.assertIn("case added, not measured", entry)
            line = int(re.search(r"`install-edge\.ps1:(\d+)", entry).group(1))
            self.assertIn(f"Res '{row}'", DRIVER.splitlines()[line - 1])

    def test_info_only_probes_are_not_invented_passes(self):
        self.assertIn('Res "PROBE-$id" \'INFO\'', PROBES)
        for row in PROBE_ROWS:
            self.assertRegex(DRIVER, rf"Res '{row}' 'NOT-PORTED' '[^'\n]*no source PASS rule")
            self.assertIn(f"Probe '{row}'", PROBES)
            self.assertNotIn(f"Res '{row}' 'PASS'", DRIVER)
        self.assertIn("$script:rowState[$_] -ne 'PASS'", DRIVER)

    def test_sl3_is_not_ported_until_the_container_rule_is_decided(self):
        self.assertIn("Res 'SL-3' 'NOT-PORTED' 'unproven in a container; see #238'", DRIVER)
        self.assertNotIn("Res 'SL-3' 'PASS'", DRIVER)
        self.assertNotIn("hostcheck.ps1", DRIVER)
        entry = next(line for line in CHECKLIST.splitlines() if line.startswith("| SL-3 |"))
        self.assertIn("NOT-PORTED", entry)
        self.assertIn("#238", entry)
        self.assertNotIn("Core can prove its own rejection", entry)

    def test_first_start_product_failures_do_not_throw_and_skip_dependent_rows(self):
        block = first_start_block(DRIVER)
        self.assertNotIn("throw", block)
        self.assertEqual(block.count("$skipProduct = $true"), 2)
        self.assertIn("if ($skipProduct) { $script:unmeasured = 'not measured: first silent start failed' }", block)
        self.assertIn("if (-not $skipProduct) {\n        Clean-Product\n        $phase = 'install'", DRIVER)

    def test_source_arguments_timeouts_and_assertions_are_preserved(self):
        check_parity(DRIVER)

    def test_no_forbidden_constructs_raw_logs_or_end_line(self):
        check_forbidden(DRIVER)
        DRIVER.encode("ascii")
        self.assertIn('$psi.RedirectStandardOutput = $true', DRIVER)
        self.assertIn('$psi.RedirectStandardError = $true', DRIVER)

    def test_gate_precedes_mutation_and_cleanup_is_owned_and_fail_closed(self):
        gate = 'if ((Test-Path $footprintFolder) -or (Test-Path $uninstallKey) -or (Test-Path $serviceKey))'
        self.assertLess(DRIVER.index(gate), DRIVER.index('$gateOk = $true'))
        self.assertLess(DRIVER.index('$gateOk = $true'), DRIVER.index('$ff = Start-Timed'))
        self.assertLess(DRIVER.index('$ff = Start-Timed'), DRIVER.index('Set-Content -LiteralPath $signerFile'))
        self.assertIn('if ($gateOk) { Clean-Product }', DRIVER)
        self.assertIn('if ($workMade) { Remove-Item -LiteralPath $work', DRIVER)
        self.assertIn('Log "cleanup error type=$($_.Exception.GetType().Name)"; $script:driverFailed = $true', DRIVER)
        self.assertIn("if ($script:driverFailed) { $failed += 'driver-or-cleanup' }", DRIVER)

    def test_mutants_are_caught(self):
        for name, check, mutant in (
            ("pass line renamed", check_pass_line, DRIVER.replace(f"Log '{PASS_LINE}'", "Log '[verdict] c-install-edge PASSED'")),
            ("UTC bound weakened", check_parity, DRIVER.replace("-gt 180)", "-gt 181)")),
            ("first start limit weakened", check_parity, DRIVER.replace('"/S /SIGNER=$sig" 40', '"/S /SIGNER=$sig" 400')),
            ("whole-folder precondition dropped", check_parity, DRIVER.replace("if (-not $svcMade -or -not $hadUninstaller)", "if (-not $hadUninstaller)")),
            ("missing zones accepted", check_parity, DRIVER.replace(" -and $script:zoneRuns -eq 3", "")),
            ("whole-folder decisions swapped", check_parity,
             DRIVER.replace("'SL-13-uninstall-removes-whole-folder' 'PASS' $facts", "'SL-13-uninstall-removes-whole-folder' 'FAIL' $facts")
             .replace("else { Res 'SL-13-uninstall-removes-whole-folder' 'FAIL' $facts }", "else { Res 'SL-13-uninstall-removes-whole-folder' 'PASS' $facts }")),
            ("first-start decisions swapped", check_parity,
             DRIVER.replace("Res 'GUEST6B-first-silent-start' 'PASS' \"rc=", "Res 'GUEST6B-first-silent-start' 'FAIL' \"rc=")
             .replace("Res 'GUEST6B-first-silent-start' 'FAIL' 'no integer exit'", "Res 'GUEST6B-first-silent-start' 'PASS' 'no integer exit'")),
            ("link added", check_forbidden, DRIVER + "\ncmd.exe /c mklink /J a b\n"),
            ("raw log emitted", check_forbidden, DRIVER + "\nLog $lines\n"),
        ):
            with self.subTest(name):
                self.assertNotEqual(mutant, DRIVER)
                with self.assertRaises(AssertionError):
                    check(mutant)


class InstallEdgeCase(unittest.TestCase):
    def test_files_and_wrapper_use_real_installer_and_only_required_helpers(self):
        self.assertEqual(container.case_files("install-edge"), [
            ("install-edge.ps1", "installer/guest/install-edge.ps1", "repo"),
            ("installer.exe", "installer.exe", "vm-kit"),
            ("stub-service.cs", "installer/guest/stub-service.cs", "repo"),
            ("log-harness.exe.b64", "installer/guest/payload/log-harness.exe.b64", "pack"),
        ])
        self.assertTrue(container.CASES["install-edge"]["vm_kit"])
        case = container.case_script("install-edge", "L30")
        self.assertIn("-File (Join-Path $w 'installer\\guest\\install-edge.ps1')", case)
        self.assertIn("-cnotmatch '^\\[verdict\\] c-install-edge PASS$'", case)
        self.assertEqual(case.count("Write-Output '[end] c-install-edge END'"), 1)
        for name, path, _ in container.case_files("install-edge"):
            self.assertIn(f"'{name}' = '{container.win(path)}'", case)


@requires_pwsh
class InstallEdgeFunctions(unittest.TestCase):
    def test_first_start_failures_keep_driver_success_and_a_failing_verdict(self):
        lines = run_functions(SCRIPT, ("Log", "Res", "Write-Verdict"), r"""
$report = Join-Path $base 'rows.txt'
$installer = 'unused'
$sig = 'ab' * 32
$proc = [pscustomobject]@{}
$proc | Add-Member ScriptMethod Kill { $script:killed += 1 }
$proc | Add-Member ScriptMethod WaitForExit {}
function Cpu-Over($p, $sec) { 0 }
function Start-Timed($exe, $argText, $limitSec) {
    $rc = if ($mode -eq 'integer') { 3 } else { 'timeout' }
    [pscustomobject]@{ Done = ($mode -ne 'timeout'); Rc = $rc; Proc = $proc; Sec = 40 }
}
foreach ($mode in 'integer', 'non-integer', 'timeout') {
    [IO.File]::WriteAllText($report, '')
    $script:rowState = @{}
    $script:driverFailed = $false
    $script:unmeasured = 'not measured fixture'
    $script:killed = 0
    try {
""" + first_start_block(DRIVER) + r"""
    } catch { $script:driverFailed = $true }
    Write-Verdict
    "$mode|skip=$skipProduct error=$script:driverFailed killed=$script:killed"
    Get-Content -LiteralPath $report | ForEach-Object { "$mode|$_" }
}
""" + DRIVER[DRIVER.index("if ($script:driverFailed) { exit 1 }"):], ("rows", "rowState"))
        for mode, skip, killed in (("integer", False, 0), ("non-integer", True, 0), ("timeout", True, 1)):
            output = [line.split("|", 1)[1] for line in lines if line.startswith(mode + "|")]
            self.assertEqual(output[0], f"skip={skip} error=False killed={killed}")
            self.assertTrue(output[1].startswith(f"ROW GUEST6B-first-silent-start {'FAIL' if skip else 'PASS'} "))
            self.assertFalse(container.judge("install-edge.ps1", output[1:])[0])
            self.assertNotIn("driver-or-cleanup", output[-1])

    def test_real_verdict_missing_not_ported_failed_and_cleanup_cannot_pass(self):
        lines = run_functions(SCRIPT, ("Log", "Res", "Write-Verdict"), r"""
$report = Join-Path $base 'rows.txt'
$script:unmeasured = 'not measured fixture'
foreach ($mode in 'all-pass', 'missing', 'not-ported', 'failed', 'cleanup') {
    [IO.File]::WriteAllText($report, '')
    $script:rowState = @{}
    $script:driverFailed = $mode -eq 'cleanup'
    foreach ($id in $rows) {
        if ($mode -eq 'missing' -and $id -eq $rows[0]) { continue }
        $state = if ($mode -eq 'not-ported' -and $id -eq 'A-M0-residue') { 'NOT-PORTED' }
                 elseif ($mode -eq 'failed' -and $id -eq 'SL-3') { 'FAIL' } else { 'PASS' }
        Res $id $state 'fixture'
    }
    Write-Verdict
    Get-Content -LiteralPath $report | ForEach-Object { "$mode|$_" }
}
""", ("rows", "rowState"))
        for mode in ("all-pass", "missing", "not-ported", "failed", "cleanup"):
            output = [line.split("|", 1)[1] for line in lines if line.startswith(mode + "|")]
            self.assertEqual(len(output), 11)
            self.assertCountEqual([line.split()[1] for line in output[:-1]], ROWS)
            self.assertEqual(container.judge("install-edge.ps1", output)[0], mode == "all-pass")

    def test_real_log_check_rejects_stale_invalid_missing_and_wrong_zone_records(self):
        lines = run_functions(SCRIPT, ("Log", "Check-Log"), r"""
$report = Join-Path $base 'notes.txt'
$footprintFolder = Join-Path $base 'product'
$logh = 'unused'
function Run-Exe($exe, $argText) { 0 }
function Get-ItemProperty($path) { [pscustomobject]@{ TimeZoneKeyName = 'Fixture Zone' } }
foreach ($mode in 'valid', 'stale', 'wrong-zone', 'bad-json', 'two-lines', 'missing') {
    New-Item -ItemType Directory -Path $footprintFolder -Force | Out-Null
    $script:zoneMiss = 0
    $script:zoneRuns = 0
    $t = [DateTime]::UtcNow
    if ($mode -eq 'stale') { $t = $t.AddSeconds(-240) }
    $line = '{"step": "one", "command": "two", "zone": "Fixture Zone", "started": "' + $t.ToString('s') + '+00:00"}'
    $last = $line.Replace('"one"', '"A\"B"').Replace('"two"', '"A\\Q"')
    $records = @($line, $line, $last)
    if ($mode -eq 'wrong-zone') { $records = $records.Replace('Fixture Zone', 'Other Zone') }
    if ($mode -eq 'bad-json') { $records[2] = 'not-json' }
    if ($mode -eq 'two-lines') { $records = @($line, $line) }
    if ($mode -ne 'missing') { Set-Content -LiteralPath (Join-Path $footprintFolder 'steps.jsonl') -Value $records }
    $ok = Check-Log $mode
    "$mode|$ok|$script:zoneMiss|$script:zoneRuns"
}
""")
        self.assertEqual(lines, ["valid|True|0|1", "stale|False|0|1", "wrong-zone|False|3|1",
                                 "bad-json|False|1|1", "two-lines|False|0|0", "missing|False|0|0"])


if __name__ == "__main__":
    unittest.main()
