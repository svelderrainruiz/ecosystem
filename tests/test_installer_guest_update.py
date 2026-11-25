"""Update-mode smoke (ecosystem-control#129, GUEST7D): update-smoke.ps1 seeds one product folder per case inside a disposable clone, runs the REAL
installer-update.exe (update mode, built by installer.guest.pack with a stand-in program file) over it and records the exit code, the wall time,
what survives outside and what the update leaves inside. The static tests tie the driver to the NSIS sources it was written from; the pwsh tests
run its real functions against a temp folder with the installer and the Windows tools mocked; the guest run is the proof (installer/README.md)."""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer.guest import pack
from tests.guest_pwsh import PWSH, requires_pwsh, run_functions
from tests.test_installer_guest_smoke import REMOVE_SCENARIO

ROOT = Path(__file__).resolve().parent.parent
GUEST = ROOT / "installer" / "guest"
NSIS = ROOT / "installer" / "nsis"
SCRIPT = GUEST / "update-smoke.ps1"
DRIVER = SCRIPT.read_text(encoding="ascii")
SEVEN_B = (GUEST / "uninstall-smoke.ps1").read_text(encoding="ascii")
UPDATE = (NSIS / "update.nsh").read_text(encoding="utf-8")
WINSYS = (NSIS / "winsys.nsh").read_text(encoding="utf-8")
TRUST = (NSIS / "trust.nsh").read_text(encoding="utf-8")
INSTALL = (NSIS / "install.nsh").read_text(encoding="utf-8")
LOG = (NSIS / "log.nsh").read_text(encoding="utf-8")
FOOTPRINT = json.loads((ROOT / "installer" / "footprint.json").read_text(encoding="utf-8"))
SIG = "ab" * 32


def functions(text):
    """Top-level functions of a driver, name -> text: a one-liner has balanced braces, any other ends at a line that is just `}`."""
    lines = text.split("\n")
    found, i = {}, 0
    while i < len(lines):
        m = re.match(r"function ([A-Za-z][\w-]*)", lines[i])
        if m:
            j = i
            if lines[i].count("{") != lines[i].count("}"):
                j = i + lines[i:].index("}")
            found[m.group(1)] = "\n".join(lines[i:j + 1])
            i = j
        i += 1
    return found


FUNCS = functions(DRIVER)


def between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


class DriverMatchesTheInstaller(unittest.TestCase):
    def test_seed_applies_the_installer_descriptor(self):
        sddl = "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        self.assertIn(sddl, between(WINSYS, "Function Winsys_FolderCreate", "FunctionEnd"))
        self.assertIn("$security.SetSecurityDescriptorSddlForm('%s', 'Owner, Access')" % sddl, FUNCS["Mark-Prod"])
        self.assertIn("Set-Acl -LiteralPath $prod -AclObject $security", FUNCS["Mark-Prod"])

    def test_only_mark_prod_creates_the_product_root(self):
        create = r'(?i)(?:\bMkdirs\s+(?:@\((?:[^)\n]*,)?\s*)?|::CreateDirectory\(\s*)"?\$prod"?(?=[\s,);]|$)'
        self.assertRegex(FUNCS["Mark-Prod"], create)
        self.assertNotRegex(DRIVER.replace(FUNCS["Mark-Prod"], ""), create)

    def test_the_exit_codes_the_cases_expect_are_the_ones_the_footprint_and_the_nsis_sources_give(self):
        codes = FOOTPRINT["exit_codes"]
        self.assertEqual((codes["folder-not-ours"], codes["update-not-applied"]), (39, 43))
        self.assertIn("SetErrorLevel 39", between(WINSYS, "Function Winsys_FolderRefuse", "FunctionEnd"))
        self.assertIn("StrCpy $upd_code 43", between(UPDATE, "Function Update_NotApplied", "FunctionEnd"))
        self.assertIn("($r.Rc -eq '39')", FUNCS["Link-Case"])
        self.assertIn("($r1.Rc -eq '43')", FUNCS["Case-UB3"])
        self.assertIn("($r.Rc -eq '0')", FUNCS["Updated-Ok"])

    def test_the_seed_is_an_older_version_of_the_same_major_than_the_installer_under_test(self):
        default = re.search(r'!define INSTALLER_VERSION "(\d+)\.(\d+)\.(\d+)"', INSTALL)
        seed = re.search(r'"installer_version": "(\d+)\.(\d+)\.(\d+)"', FUNCS["Seed-Base"])
        self.assertTrue(default and seed)
        newer, older = tuple(map(int, default.groups())), tuple(map(int, seed.groups()))
        self.assertEqual(older[0], newer[0])
        self.assertLess(older, newer)
        self.assertEqual(newer, (0, 1, 0))
        self.assertIn("($s.Version -eq '0.1.0')", FUNCS["Updated-Ok"])
        self.assertIn("($s.KeyVer -ceq '0.1.0')", FUNCS["Updated-Ok"])
        self.assertIn("($s.Version -eq '0.0.1')", FUNCS["Link-Case"])
        self.assertIn("($s1.Version -eq '0.0.1')", FUNCS["Case-UB3"])

    def test_the_seeded_state_line_is_one_the_installer_accepts_and_has_the_shape_it_writes(self):
        self.assertIn("""StrCpy $upd_needle '"schema_version": 1'""", UPDATE)
        self.assertIn("""StrCpy $upd_needle '"installer_version": "'""", UPDATE)
        self.assertIn(r"""FileWrite $InstallHandle '{"schema_version": 1, "installer_version": "${INSTALLER_VERSION}"}$\r$\n'""", INSTALL)
        self.assertIn("""('{"schema_version": 1, "installer_version": "0.0.1"}' + "`r`n")""", FUNCS["Seed-Base"])

    def test_the_step_names_the_driver_counts_are_the_ones_update_nsh_logs_in_the_format_log_nsh_writes(self):
        for name in ("update-backup-cleanup", "update-backup", "update-swap"):
            self.assertIn('Push "%s"' % name, UPDATE)
        ub3 = FUNCS["Case-UB3"]
        self.assertIn("$_ -eq 'update-backup-cleanup'", ub3)
        self.assertIn("$_ -eq 'update-backup'", ub3)
        self.assertIn("@('update-backup', 'update-backup-cleanup', 'update-swap')", FUNCS["Update-Case"])
        self.assertIn('FileWrite $LogHandle \'{"step": "\'\n  !insertmacro LogWriteField $LogStepName', LOG)
        self.assertIn("""'"step": "([^"]*)"'""", FUNCS["Step-Names"])

    def test_a_silent_run_needs_the_stored_signer_and_the_driver_writes_exactly_that_file_and_runs_the_installer_with_it(self):
        self.assertIn(r'StrCpy $TrustStoreFile "$LOCALAPPDATA\EcosystemInstaller\signer.sha256"', TRUST)
        self.assertIn("Silent runs never confirm", TRUST)
        self.assertIn("$signerDir = Join-Path $env:LOCALAPPDATA 'EcosystemInstaller'", DRIVER)
        self.assertIn("$signerFile = Join-Path $signerDir 'signer.sha256'", DRIVER)
        self.assertIn("$sig = ('ab' * 32)", DRIVER)
        self.assertIn('$signerText = $sig + "`n"', DRIVER)
        self.assertIn('Push "/SIGNER="', TRUST)
        measure = FUNCS["Measure-Inst"]
        self.assertIn("""Run-Inst (Join-Path $bin 'installer-update.exe') "/S /SIGNER=$sig" $left""", measure)

    def test_the_program_file_the_update_writes_is_ascii_and_none_of_the_texts_the_driver_seeds(self):
        payload = pack.UPDATE_PAYLOAD.decode("ascii")
        for seeded in ("OLD-RUNNER-g7d", "DECOY-RUNNER-g7d", "STALE-RUNNER-g7d"):
            self.assertIn("'%s'" % seeded, DRIVER)
            self.assertNotIn(seeded, payload)
        self.assertIn("installer-update.exe.b64", DRIVER)
        self.assertIn("update-payload.bin.b64", DRIVER)
        self.assertIn("$script:payloadText = [Text.Encoding]::ASCII.GetString([Convert]::FromBase64String((Get-Content -LiteralPath "
                      "(Join-Path $payloadDir 'update-payload.bin.b64') -Raw)))", DRIVER)

    def test_the_driver_reads_the_audit_command_from_winsys_nsh_and_nothing_else_of_the_nsis_sources(self):
        code = "\n".join(line for line in DRIVER.splitlines() if not line.lstrip().startswith("#"))
        self.assertEqual(sorted(set(re.findall(r"installer\\nsis\\([\w.]+)", code))), ["winsys.nsh"])
        self.assertIn("installer\\guest\\stub-service.cs", DRIVER)
        self.assertTrue((GUEST / "stub-service.cs").is_file())


class DriverStaysInTheFixture(unittest.TestCase):
    def test_driver_is_ascii_and_names_no_secret_or_url(self):
        DRIVER.encode("ascii")
        self.assertNotRegex(DRIVER, r"https?://")
        self.assertNotRegex(DRIVER, r"(?i)password|credential|\.config")

    def test_every_path_it_names_is_under_the_fixture_or_the_product_folder(self):
        self.assertIn("$root = 'C:\\X\\g7d'", DRIVER)
        self.assertIn("$prod = 'C:\\ProgramData\\EcosystemRunner'", DRIVER)
        self.assertIn("refusing to remove outside the fixture", DRIVER)
        for drive in re.findall(r"[A-Za-z]:\\[^\s'\"]*", DRIVER):
            self.assertTrue(drive.startswith(("C:\\X\\g7d", "C:\\ProgramData\\EcosystemRunner")), drive)

    def test_no_recursive_delete_can_follow_a_link(self):
        self.assertNotRegex(DRIVER, r"(?i)-Recurse")
        self.assertNotRegex(DRIVER, r"(?i)\brd\s+/s|rmdir\s+/s|\bdel\s+/s")
        self.assertNotRegex(DRIVER, r"""(?i)['"]/s['"]""")
        self.assertNotRegex(DRIVER, r"(?i)[.:]Delete\([^)]*\$true")
        remover = FUNCS["Remove-Entry"]
        self.assertLess(remover.index("-band 0x400"), remover.index("GetFileSystemEntries"))
        self.assertIn("'rmdir'", remover)
        self.assertIn("'del'", remover)

    def test_the_snapshot_never_enters_a_link(self):
        walk = FUNCS["Snap-Walk"]
        self.assertLess(walk.index("-band 0x400"), walk.index("Snap-Walk $e"))
        self.assertIn("SHA256", DRIVER)

    def test_whatever_deletes_or_makes_a_service_or_writes_the_signer_file_starts_with_the_gate(self):
        for name, what in (("Reset-All", "nothing is deleted"), ("Ensure-Stub", "no service is made"), ("Seed-Signer", "no signer file is written"),
                           ("Remove-Signer", "nothing is deleted")):
            first = FUNCS[name].split("{", 1)[1].lstrip().splitlines()[0]
            self.assertEqual(first, "if (-not $script:gateOk) { throw 'the ownership gate has not passed: %s' }" % what, name)
        self.assertEqual(FUNCS["Remove-Stub"].split("{", 1)[1].lstrip().splitlines()[0], "if (-not $script:svcMade) { return }")
        self.assertLess(DRIVER.index("$script:gateOk = $false"), DRIVER.index("function Log"))

    def test_the_main_flow_gates_runs_the_six_cases_in_order_cleans_up_and_only_then_reports(self):
        main = DRIVER.split("$summary = ''", 1)[1]
        order = ["Test-Gate", "if ($script:gateOk) {", "Try-Case 'U-B1'", "Try-Case 'U-B2'", "Try-Case 'U-B3' ", "Try-Case 'U-B3b'", "Try-Case 'U-B4'",
                 "Try-Case 'U-B5'", "Log 'DONE'", "finally {", "try { Reset-All }", "try { Remove-Stub }", "try { Remove-Signer }", "AFTER-CLEANUP",
                 "Write-Summary", "Copy-Item -LiteralPath $log"]
        at = [main.index(x) for x in order]
        self.assertEqual(at, sorted(at))
        self.assertIn("    if ($script:gateOk) {\n        try { Reset-All }", main)
        self.assertEqual(DRIVER.rstrip().splitlines()[-1], "exit 0")
        self.assertEqual(DRIVER.count("Copy-Item -LiteralPath $log -Destination (Join-Path $out $logName)"), 3)

    def test_a_missing_payload_or_stub_stops_the_run_before_the_gate_and_before_anything_is_made(self):
        flow = DRIVER.split("$summary = ''", 1)[0].split("# ---- environment, the installer under test and the stub service", 1)[1]
        self.assertEqual((flow.count("exit 2"), flow.count("exit 3")), (1, 1))
        self.assertLess(flow.index("exit 2"), flow.index("exit 3"))
        for call in ("Test-Gate", "Reset-All", "Seed-Signer", "Ensure-Stub", "Seed-Base"):
            self.assertNotIn(call, flow)

    def test_the_lock_holder_keeps_one_file_open_with_the_share_mode_it_is_given_and_is_always_stopped(self):
        holder = FUNCS["Start-Holder"]
        self.assertIn("[IO.File]::Open($path, ''Open'', ''Read'', $share)", holder)
        self.assertIn("'100'", holder)
        self.assertIn("-WindowStyle Hidden", holder)
        self.assertIn("finally { Stop-Holder }", FUNCS["Case-UB3"])
        self.assertIn("Stop-Holder", FUNCS["Reset-All"])
        self.assertIn("$script:holder.Kill()", FUNCS["Stop-Holder"])

    def test_the_owner_and_the_audit_probe_are_evidence_only_never_part_of_a_verdict(self):
        self.assertEqual(DRIVER.count("Probe-Audit"), 2)
        self.assertEqual(DRIVER.count("Get-Owner"), 2)
        self.assertIn("owner=[$(Get-Owner)] audit=[$(Probe-Audit)]", FUNCS["Measure-Inst"])
        for name in ("Verdict", "Unproven", "Updated-Ok", "Link-Case", "Case-UB3", "Update-Case"):
            self.assertNotIn("Probe-Audit", FUNCS[name])
            self.assertNotIn("Get-Owner", FUNCS[name])


class DriverCoversTheCases(unittest.TestCase):
    def test_the_six_cases_run_in_the_order_of_the_pull_request_each_one_wrapped_so_one_error_cannot_stop_the_rest(self):
        lines = [x.strip() for x in DRIVER.splitlines() if x.strip().startswith("Try-Case 'U-B")]
        self.assertEqual(lines, ["Try-Case 'U-B1' { Case-UB1 }", "Try-Case 'U-B2' { Case-UB2 }", "Try-Case 'U-B3' { Case-UB3 'U-B3' 'None' }",
                                 "Try-Case 'U-B3b' { Case-UB3 'U-B3b' 'ReadWrite' }", "Try-Case 'U-B4' { Case-UB4 }", "Try-Case 'U-B5' { Case-UB5 }"])
        self.assertIn("function Case-UB1 { Link-Case 'U-B1' 'backup' 'OLD' }", DRIVER)
        self.assertIn("function Case-UB2 { Link-Case 'U-B2' 'program' 'DECOY' }", DRIVER)
        self.assertIn("function Case-UB4 { Update-Case 'U-B4' $true }", DRIVER)
        self.assertIn("function Case-UB5 { Update-Case 'U-B5' $false }", DRIVER)
        self.assertIn("$caseLimit = 120", DRIVER)

    def test_each_case_says_unproven_when_the_run_hit_the_limit_or_the_fixture_is_not_what_it_claims(self):
        self.assertEqual(FUNCS["Link-Case"].count("$r.TimedOut"), 1)
        self.assertEqual(FUNCS["Update-Case"].count("$r.TimedOut"), 1)
        self.assertEqual((FUNCS["Case-UB3"].count("$r1.TimedOut"), FUNCS["Case-UB3"].count("$r2.TimedOut")), (1, 1))
        self.assertIn("Unproven $name 'fixture could not be built'", FUNCS["Link-Case"])
        self.assertIn("Unproven $name 'the background process did not take the lock'", FUNCS["Case-UB3"])
        self.assertIn("Unproven $name 'run 2 hit the case limit and was killed'", FUNCS["Case-UB3"])
        self.assertIn("$rc = 'timeout'", FUNCS["Run-Inst"])
        self.assertIn("taskkill", FUNCS["Run-Inst"])

    def test_the_two_link_cases_use_junctions_at_backup_and_at_program_with_a_decoy_outside_the_product_folder(self):
        link = FUNCS["Link-Case"]
        self.assertIn("Cmd 'mklink' '/J' \"$prod\\$linkRel\" $o", link)
        self.assertIn("$o = \"$outs\\$name\\decoy\"", link)
        self.assertIn("Seed-Base ($linkRel -ne 'program')", link)
        self.assertIn('Write-Ascii "$o\\complete" \'\'', link)

    def test_the_stale_backup_has_no_complete_marker_and_the_locked_file_is_the_third_thing_in_it(self):
        stale = FUNCS["Seed-Stale"]
        self.assertNotIn("complete", stale)
        for name in ("backup\\program\\runner.exe", "backup\\service.json", "backup\\z-dir\\y.txt"):
            self.assertIn(name, stale)
        self.assertIn('Write-Ascii "$prod\\backup\\locked.txt" \'L\'', FUNCS["Case-UB3"])

    def test_the_readme_tells_the_signer_file_precondition_and_lists_the_six_cases(self):
        readme = (ROOT / "installer" / "README.md").read_text(encoding="utf-8")
        self.assertIn("update-smoke.ps1", readme)
        for case in ("U-B1", "U-B2", "U-B3", "U-B3b", "U-B4", "U-B5"):
            self.assertIn(case, readme)
        self.assertIn("signer.sha256", readme)


COPIED = ("Cmd", "Diff-Snap", "Exists", "Get-Attr", "Get-KeyName", "Get-Listing", "Get-Snapshot", "Log", "Mkdirs", "Note",
          "Open-Hklm64", "Prod-Text", "Read-Ascii", "Remove-Entry", "Remove-Key", "Set-Key", "Snap-Walk", "Test-Elevated", "Test-Gate", "Test-Key",
          "Unproven", "Write-Ascii", "Yn")


class CopiedHelpersMatchTheUninstallDriver(unittest.TestCase):
    def test_the_helpers_that_delete_or_measure_are_the_text_of_the_uninstall_smoke_driver(self):
        seven_b = functions(SEVEN_B)
        for name in COPIED:
            self.assertIn(name, FUNCS, name)
            self.assertIn(name, seven_b, name)
            self.assertEqual(FUNCS[name], seven_b[name], name)

    def test_the_functions_that_are_its_own_are_not_in_that_list(self):
        for name in ("Get-Foreign", "Mark-Prod", "Reset-All", "Verdict", "Write-Summary", "Try-Case"):
            self.assertNotIn(name, COPIED)
            self.assertIn(name, FUNCS)


GATE_SCENARIO = r"""
$root = Join-Path $base 'g7d'
$prod = Join-Path $base 'prod'
$outs = Join-Path $root 'outside'
$log = Join-Path $base 'x.log'
$signerParent = Join-Path $base 'appdata'
$signerDir = Join-Path $signerParent 'EcosystemInstaller'
$signerFile = Join-Path $signerDir 'signer.sha256'
$noService = '[SC] EnumQueryServicesStatus:OpenService FAILED 1060:' + "`r`n`r`n" + 'The specified service does not exist as an installed service.'
$script:svc = $noService
function Cmd { $script:svc }
$script:keyPresent = $false; $script:keyDisplay = $null; $script:keyRemoved = $false
function Test-Key { $script:keyPresent }
function Get-KeyName { $script:keyDisplay }
function Remove-Key { $script:keyRemoved = $true; $script:keyPresent = $false }
function Clean {
    foreach ($d in @($prod, $root, $signerParent)) { if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force } }
    Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
    $script:keyPresent = $false; $script:keyDisplay = $null; $script:keyRemoved = $false; $script:gateOk = $false; $script:svc = $noService
    $script:signerMade = $false; $script:signerDirMade = $false
}
function Refused-Lines { if (Test-Path -LiteralPath $log) { @(Get-Content -LiteralPath $log | Where-Object { $_ -like 'REFUSED:*' }) } else { @() } }
function Try-It([scriptblock]$sb) { try { & $sb; 'ran' } catch { 'threw' } }
function Mark([string]$text) { [void](New-Item -ItemType Directory -Force -Path $prod); [IO.File]::WriteAllText((Join-Path $prod $markerName), $text) }
function Signer-Text { if (Test-Path -LiteralPath $signerFile) { [IO.File]::ReadAllText($signerFile) } else { 'ABSENT' } }

Clean
[void](New-Item -ItemType Directory -Force -Path $prod); [IO.File]::WriteAllText((Join-Path $prod 'real.txt'), 'real')
Test-Gate
$r = @(Refused-Lines)
"1 foreign-folder gate=$script:gateOk refused=$($r.Count) names_path=$($r[0].Contains($prod)) reset=$(Try-It { Reset-All }) kept=$([IO.File]::Exists((Join-Path $prod 'real.txt')))"

Clean
Mark $markerText; [IO.File]::WriteAllText((Join-Path $prod 'ours.txt'), 'ours')
Test-Gate
"2 marked-folder gate=$script:gateOk refused=$(@(Refused-Lines).Count) reset=$(Try-It { Reset-All }) folder_gone=$(-not (Test-Path -LiteralPath $prod)) key_removed=$script:keyRemoved outside_made=$(Test-Path -LiteralPath $outs)"

Clean
$script:keyPresent = $true; $script:keyDisplay = 'Some Other Product'
Test-Gate
$r = @(Refused-Lines)
"3 foreign-key gate=$script:gateOk refused=$($r.Count) names_key=$($r[0].Contains($keyPath)) shows_content=$($r[0].Contains('Some Other Product')) reset=$(Try-It { Reset-All }) key_removed=$script:keyRemoved"

Clean
$script:keyPresent = $true; $script:keyDisplay = $keyName
Test-Gate
"4 own-key gate=$script:gateOk refused=$(@(Refused-Lines).Count)"

Clean
Test-Gate
"5 clean gate=$script:gateOk refused=$(@(Refused-Lines).Count)"

Clean
Mark 'not ours'
Test-Gate
"6 wrong-marker gate=$script:gateOk refused=$(@(Refused-Lines).Count)"

Clean
Mark $markerText
$script:keyPresent = $true; $script:keyDisplay = 'Some Other Product'
Test-Gate
"7 own-folder-foreign-key gate=$script:gateOk refused=$(@(Refused-Lines).Count)"

Clean
Mark $markerText
$script:svc = "SERVICE_NAME: EcosystemRunner`r`n        TYPE               : 10  WIN32_OWN_PROCESS`r`n        STATE              : 4  RUNNING"
Test-Gate
$r = @(Refused-Lines)
"8 foreign-service gate=$script:gateOk refused=$($r.Count) names_service=$($r[0].Contains('the service EcosystemRunner exists')) shows_state=$($r[0].Contains('RUNNING')) reset=$(Try-It { Reset-All }) folder_kept=$(Test-Path -LiteralPath $prod)"

Clean
$script:svc = '[SC] OpenSCManager FAILED 5:' + "`r`n`r`n" + 'Access is denied.'
Test-Gate
$r = @(Refused-Lines)
"9 unreadable-service gate=$script:gateOk refused=$($r.Count) says_not_queried=$($r[0].Contains('could not be queried'))"

Clean
$script:svc = ''
Test-Gate
"10 empty-answer gate=$script:gateOk refused=$(@(Refused-Lines).Count)"

Clean
Mkdirs @($signerDir); [IO.File]::WriteAllText($signerFile, 'something-else')
Test-Gate
$r = @(Refused-Lines)
"11 foreign-signer gate=$script:gateOk refused=$($r.Count) names_file=$($r[0].Contains('stored signer file')) shows_content=$($r[0].Contains('something-else')) seed=$(Try-It { Seed-Signer }) reset=$(Try-It { Reset-All }) kept=$(Signer-Text)"

Clean
Mkdirs @($signerDir); [IO.File]::WriteAllText($signerFile, $signerText)
Test-Gate
Seed-Signer
$made = $script:signerMade
Remove-Signer
"12 own-signer gate=$script:gateOk refused=$(@(Refused-Lines).Count) made=$made kept=$((Signer-Text) -ceq $signerText)"

Clean
Test-Gate
Seed-Signer
"13 seed-no-folder written=$((Signer-Text) -ceq $signerText) made=$script:signerMade dir_made=$script:signerDirMade"
Remove-Signer
"14 remove-made file_gone=$(-not (Test-Path -LiteralPath $signerFile)) dir_gone=$(-not (Test-Path -LiteralPath $signerDir)) made=$script:signerMade dir_made=$script:signerDirMade"

Clean
Mkdirs @($signerDir)
Test-Gate
Seed-Signer
"15 seed-with-folder written=$((Signer-Text) -ceq $signerText) made=$script:signerMade dir_made=$script:signerDirMade"
Remove-Signer
"16 remove-keeps-folder file_gone=$(-not (Test-Path -LiteralPath $signerFile)) dir_kept=$(Test-Path -LiteralPath $signerDir)"

Clean
Test-Gate
Seed-Signer
[IO.File]::WriteAllText((Join-Path $signerDir 'other.txt'), 'o')
Remove-Signer
$cl = @(Get-Content -LiteralPath $log | Where-Object { $_ -like 'CLEANUP:*' })
"17 folder-not-empty file_gone=$(-not (Test-Path -LiteralPath $signerFile)) other_kept=$(Test-Path -LiteralPath (Join-Path $signerDir 'other.txt')) cleanup_lines=$($cl.Count) dir_made=$script:signerDirMade"

Clean
Mkdirs @($signerDir); [IO.File]::WriteAllText($signerFile, 'keep-me')
$script:signerMade = $true
"18 before-gate seed=$(Try-It { Seed-Signer }) remove=$(Try-It { Remove-Signer }) kept=$(Signer-Text)"
"""

STUB_SCENARIO = r"""
$log = Join-Path $base 'x.log'
$stubExe = Join-Path $base 'stub.exe'
$gone = '[SC] EnumQueryServicesStatus:OpenService FAILED 1060:' + "`r`n`r`n" + 'The specified service does not exist as an installed service.'
$script:sc = 'absent'; $script:createWorks = $true; $script:startWorks = $true; $script:stopWorks = $true; $script:slept = 0
$script:calls = New-Object System.Collections.Generic.List[string]
function Start-Sleep { $script:slept++ }
function Cmd {
    $a = @($args)
    $script:calls.Add(($a -join ' '))
    $verb = if ($a.Count -gt 1) { [string]$a[1] } else { '' }
    switch ($verb) {
        'query' { if ($script:sc -eq 'absent') { $gone } else { 'SERVICE_NAME: EcosystemRunner' } }
        'queryex' {
            if ($script:sc -eq 'absent') { $gone }
            elseif ($script:sc -eq 'running') { "SERVICE_NAME: EcosystemRunner`r`n        TYPE               : 10  WIN32_OWN_PROCESS`r`n        STATE              : 4  RUNNING`r`n        PID                : 4242`r`n        FLAGS              :" }
            else { "SERVICE_NAME: EcosystemRunner`r`n        STATE              : 1  STOPPED`r`n        PID                : 0" }
        }
        'create' { if ($script:createWorks) { $script:sc = 'stopped'; '[SC] CreateService SUCCESS' } else { '[SC] OpenSCManager FAILED 5:' } }
        'start' { if (($script:sc -eq 'stopped') -and $script:startWorks) { $script:sc = 'running' }; '' }
        'stop' { if (($script:sc -eq 'running') -and $script:stopWorks) { $script:sc = 'stopped' }; '' }
        'delete' { $script:sc = 'absent'; '[SC] DeleteService SUCCESS' }
        default { '' }
    }
}
function Calls([string]$verb) { @($script:calls | Where-Object { $_ -like "sc $verb *" }).Count }

$script:gateOk = $false
"1 before-gate ensure=$(try { Ensure-Stub; 'ran' } catch { 'threw' }) calls=$($script:calls.Count) made=$script:svcMade"

$script:gateOk = $true
$r = Ensure-Stub
"2 create-and-start result=$r made=$script:svcMade created=$(Calls 'create') started=$(Calls 'start') sc=$script:sc"
"3 create_args=$((@($script:calls | Where-Object { $_ -like 'sc create *' }) -join '|') -replace [regex]::Escape($stubExe), 'STUB')"
"4 log=$(@(Get-Content -LiteralPath $log)[0])"

$script:calls.Clear()
$r = Ensure-Stub
"5 already-running result=$r created=$(Calls 'create') started=$(Calls 'start') made=$script:svcMade"

$script:calls.Clear()
Remove-Stub
"6 remove-made stopped=$(Calls 'stop') deleted=$(Calls 'delete') sc=$script:sc made=$script:svcMade"

$script:sc = 'running'; $script:svcMade = $false; $script:calls.Clear()
Remove-Stub
"7 remove-foreign calls=$($script:calls.Count) sc=$script:sc"

$script:sc = 'absent'; $script:createWorks = $false; $script:svcMade = $false; $script:calls.Clear()
$r = Ensure-Stub
$made = $script:svcMade
$script:calls.Clear()
Remove-Stub
"8 create-fails result=$r made=$made line=$(@(Get-Content -LiteralPath $log)[-1]) later_calls=$($script:calls.Count)"

$script:sc = 'absent'; $script:createWorks = $true; $script:startWorks = $false; $script:svcMade = $false; $script:slept = 0; $script:calls.Clear()
$r = Ensure-Stub
"9 never-starts result=$r slept=$($script:slept) started=$(Calls 'start')"

$script:sc = 'running'; $script:svcMade = $true; $script:stopWorks = $false; $script:slept = 0; $script:calls.Clear()
Remove-Stub
"10 never-stops slept=$($script:slept) stopped=$(Calls 'stop') deleted=$(Calls 'delete') sc=$script:sc made=$script:svcMade"
"""

SVC_SCENARIO = r"""
$script:answer = ''
function Cmd { $script:answer }
$script:answer = "SERVICE_NAME: EcosystemRunner `r`n        TYPE               : 10  WIN32_OWN_PROCESS  `r`n        STATE              : 4  RUNNING `r`n                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)`r`n        WIN32_EXIT_CODE    : 0  (0x0)`r`n        SERVICE_EXIT_CODE  : 0  (0x0)`r`n        CHECKPOINT         : 0x0`r`n        WAIT_HINT          : 0x0`r`n        PID                : 4176`r`n        FLAGS              : "
"running: $(Get-Svc)"
$script:answer = "SERVICE_NAME: EcosystemRunner `r`n        TYPE               : 10  WIN32_OWN_PROCESS  `r`n        STATE              : 1  STOPPED `r`n        WIN32_EXIT_CODE    : 0  (0x0)`r`n        PID                : 0`r`n        FLAGS              : "
"stopped: $(Get-Svc)"
$script:answer = "SERVICE_NAME: EcosystemRunner `r`n        STATE              : 2  START_PENDING `r`n        PID                : 1234"
"pending: $(Get-Svc)"
$script:answer = '[SC] EnumQueryServicesStatus:OpenService FAILED 1060:' + "`r`n`r`n" + 'The specified service does not exist as an installed service.'
"gone: $(Get-Svc)"
$script:answer = '[SC] OpenSCManager FAILED 5:' + "`r`n`r`n" + 'Access is denied.'
"denied: $(Get-Svc)"
$script:answer = ''
"empty: $(Get-Svc)"
"""

READERS_SCENARIO = r"""
$prod = Join-Path $base 'prod'
$script:payloadText = 'PAYLOAD-TEXT'
$script:kv = @{ DisplayName = 'Ecosystem Runner'; DisplayVersion = '0.1.0' }
function Get-Svc { 'RUNNING/77' }
function Get-KeyVal([string]$name) { $script:kv[$name] }
Mkdirs @($prod, (Join-Path $prod 'program'))
$prog = Join-Path $prod 'program\runner.exe'
$stateFile = Join-Path $prod 'installer-state.json'
$stepsFile = Join-Path $prod 'steps.jsonl'
function Dump { $s = Get-State; 'runner={0} version={1} backup={2} exe={3} key=[{4} {5}] svc={6} steps=[{7}]' -f $s.Runner, $s.Version, $s.Backup, $s.Exe, $s.KeyName, $s.KeyVer, $s.Svc, ($s.Steps -join ',') }
"1 nothing: $(Dump)"
foreach ($t in @($oldText, $decoyText, $staleText, 'PAYLOAD-TEXT', 'old-runner-g7d', '', 'PAYLOAD-TEXT ')) { Write-Ascii $prog $t; "runner for [$t]: $(Runner-Class)" }
foreach ($t in @(('{"schema_version": 1, "installer_version": "0.0.1"}' + "`r`n"), '{"schema_version": 1, "installer_version": "0.1.0"}', 'not json')) { Write-Ascii $stateFile $t; "version for [$($t.Trim())]: $(State-Version)" }
Write-Ascii $stepsFile ('{"step": "update-backup-cleanup", "command": "c", "exit_code": 1, "started": "t"}' + "`r`n" + '{"step": "update-backup", "command": "c", "exit_code": 1, "started": "t"}' + "`r`n")
"steps: $((Step-Names) -join ',') count=$(@(Step-Names).Count)"
Remove-Item -LiteralPath $stepsFile
"no steps file: count=$(@(Step-Names).Count)"
Write-Ascii $prog 'PAYLOAD-TEXT'
Write-Ascii $stateFile '{"schema_version": 1, "installer_version": "0.1.0"}'
Write-Ascii $stepsFile '{"step": "update-swap", "command": "c"}'
Write-Ascii "$prod\uninstall.exe" 'x'
"2 updated: $(Dump)"
[void][IO.Directory]::CreateDirectory("$prod\backup")
"3 backup dir: $(Dump)"
[IO.Directory]::Delete("$prod\backup")
[void][IO.File]::CreateSymbolicLink("$prod\backup", $base)
"4 backup link: $(Dump)"
[IO.Directory]::Delete("$prod\backup")
"""

AUDIT_SCENARIO = r"""
$nsh = Read-Ascii '%WINSYS%'
$c = Get-AuditCommand $nsh
$errs = $null; $tok = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($c, [ref]$tok, [ref]$errs)
"ERRORS $($errs.Count)"
"CMD $c"
"MISSING $($null -eq (Get-AuditCommand 'nothing of the kind'))"
"""

SUMMARY_SCENARIO = r"""
$log = Join-Path $base 'x.log'
function Fresh { [IO.File]::WriteAllText($log, '') }
Fresh
Try-Case 'U-B1' { Log 'VERDICT U-B1: PASS rc=39' }
Try-Case 'U-B2' { throw 'boom' }
Try-Case 'U-B3' { Verdict 'U-B3' $false 'x'; Unproven 'U-B3b' 'y' }
Log 'REFUSED: z'
Write-Summary
(Get-Content -LiteralPath $log) -join '|'

[IO.File]::WriteAllText($log, "VERDICT U-B1: PASS rc=39`nVERDICT U-B2: FAIL rc=0`nVERDICT U-B3: UNPROVEN why`nVERDICT U-B3b: PASS rc1=43 rc2=0`nREFUSED: x`nCASE U-B4: SCRIPT-ERROR boom at line 4`nFATAL: y`nCLEANUP: z`nCASE U-B5: rc=0 note SCRIPT-ERROR in the middle`n")
Write-Summary
"last=$(@(Get-Content -LiteralPath $log)[-1])"

$six = @('U-B1', 'U-B2', 'U-B3', 'U-B3b', 'U-B4', 'U-B5') | ForEach-Object { "VERDICT ${_}: PASS rc=0" }
[IO.File]::WriteAllText($log, ($six -join "`n") + "`n")
Write-Summary

[IO.File]::WriteAllText($log, ((($six | Select-Object -First 5) + 'CASE U-B5: SCRIPT-ERROR died at line 7') -join "`n") + "`n")
Write-Summary
"""

SELECT_SCENARIO = r"""
$log = Join-Path $base 'x.log'
[IO.File]::WriteAllText($log, '')
$selected = @('U-B3', 'U-B4')
foreach ($n in 'U-B1', 'U-B2', 'U-B3', 'U-B3b', 'u-b4', 'U-B4') { Try-Case $n { Log ('RAN ' + $n) } }
(Get-Content -LiteralPath $log) -join '|'
[IO.File]::WriteAllText($log, '')
$selected = @()
foreach ($n in 'U-B1', 'U-B2') { Try-Case $n { Log ('RAN ' + $n) } }
(Get-Content -LiteralPath $log) -join '|'
"""

OK_SCENARIO = r"""
function Run-Obj {
    param([string]$Rc = '0', [bool]$Same = $true, [string]$Runner = 'PAYLOAD', [string]$Backup = 'absent', [string]$Version = '0.1.0', [bool]$Exe = $true,
          [string]$KeyName = 'Ecosystem Runner', [string]$KeyVer = '0.1.0', [string]$Svc = 'RUNNING/200', [string]$SvcBefore = 'RUNNING/100')
    [pscustomobject]@{ Rc = $Rc; Same = $Same; SvcBefore = $SvcBefore
        State = [pscustomobject]@{ Runner = $Runner; Version = $Version; Backup = $Backup; Exe = $Exe; KeyName = $KeyName; KeyVer = $KeyVer; Svc = $Svc } }
}
$variants = [ordered]@{
    good = @{}
    rc1 = @{ Rc = '1' }
    rc43 = @{ Rc = '43' }
    outside_changed = @{ Same = $false }
    backup_dir = @{ Backup = 'dir' }
    backup_link = @{ Backup = 'link' }
    runner_old = @{ Runner = 'OLD' }
    runner_stale = @{ Runner = 'STALE' }
    state_old = @{ Version = '0.0.1' }
    no_uninstall_exe = @{ Exe = $false }
    key_name_case = @{ KeyName = 'ecosystem runner' }
    key_name_seed = @{ KeyName = 'EcosystemRunner g7d' }
    key_version_old = @{ KeyVer = '0.0.1' }
    service_stopped = @{ Svc = 'STOPPED/0' }
    service_same_process = @{ Svc = 'RUNNING/100' }
}
foreach ($k in $variants.Keys) { $v = $variants[$k]; $r = Run-Obj @v; "${k}: $(Updated-Ok $r)" }
"""

CASES_SCENARIO = r"""
$prod = Join-Path $base 'prod'
$outs = Join-Path $base 'outside'
Mkdirs @($prod, $outs)
$script:lines = New-Object System.Collections.Generic.List[string]
$script:events = New-Object System.Collections.Generic.List[string]
$script:queue = New-Object System.Collections.Queue
$script:holderOk = $true; $script:mklinkWorks = $true
function Log([string]$line) { $script:lines.Add($line) }
function Seed-Base([bool]$program) { $script:events.Add("seed-base:$program") }
function Seed-Stale { $script:events.Add('seed-stale') }
function Start-Holder([string]$path, [string]$share) { $script:events.Add("holder:$share"); $script:holderOk }
function Stop-Holder { $script:events.Add('stop-holder') }
function Measure-Inst([string]$name, [string]$tag) {
    $script:events.Add("measure:$name$tag")
    $item = $script:queue.Dequeue()
    if ($item -is [scriptblock]) { & $item } else { $item }
}
function Cmd {
    $a = @($args)
    $script:events.Add('cmd:' + $a[0])
    if ($a[0] -ne 'mklink') { return '' }
    $lnk = [string]$a[2]
    if (Exists $lnk) { try { [IO.Directory]::Delete($lnk) } catch { } }
    if (-not $script:mklinkWorks) { return 'Access is denied.' }
    [void][IO.File]::CreateSymbolicLink($lnk, $base)
    'Junction created'
}
function Run-Obj {
    param([string]$Rc = '0', [bool]$Same = $true, [string]$Runner = 'PAYLOAD', [string]$Backup = 'absent', [string]$Version = '0.1.0', [bool]$Exe = $true,
          [string]$KeyName = 'Ecosystem Runner', [string]$KeyVer = '0.1.0', [string]$Svc = 'RUNNING/200', [string]$SvcBefore = 'RUNNING/100', $Steps = @(), [bool]$TimedOut = $false)
    [pscustomobject]@{ Rc = $Rc; Sec = 1.5; Same = $Same; SvcBefore = $SvcBefore; TimedOut = $TimedOut
        State = [pscustomobject]@{ Runner = $Runner; Version = $Version; Backup = $Backup; Exe = $Exe; KeyName = $KeyName; KeyVer = $KeyVer; Svc = $Svc; Steps = @($Steps) } }
}
function Merge([hashtable]$base, [hashtable]$over) { $h = $base.Clone(); foreach ($k in $over.Keys) { $h[$k] = $over[$k] }; $h }
$steps2 = @('update-backup-cleanup', 'update-backup')
$linkGood = @{ Rc = '39'; Runner = 'OLD'; Version = '0.0.1'; Svc = 'RUNNING/100'; Backup = 'link' }
$run1Good = @{ Rc = '43'; Runner = 'OLD'; Version = '0.0.1'; Svc = 'RUNNING/100'; Backup = 'dir'; Steps = $steps2 }
$run2Good = @{ Steps = $steps2 }
$updGood = @{}
function Link-R([hashtable]$over = @{}) { $h = Merge $linkGood $over; Run-Obj @h }
function Run1([hashtable]$over = @{}) { $h = Merge $run1Good $over; Run-Obj @h }
function Run2([hashtable]$over = @{}) { $h = Merge $run2Good $over; Run-Obj @h }
function Upd([hashtable]$over = @{}) { $h = Merge $updGood $over; Run-Obj @h }
function Run-Case([string]$label, [scriptblock]$call, $results) {
    $script:lines.Clear(); $script:events.Clear(); $script:queue.Clear()
    $script:holderOk = $true; $script:mklinkWorks = $true
    foreach ($x in @($results)) { $script:queue.Enqueue($x) }
    $how = 'ran'
    try { & $call } catch { $how = 'threw ' + $_.Exception.Message }
    $verdict = @($script:lines | Where-Object { $_ -like 'VERDICT *' }) -join ' / '
    "$label | $how | $verdict | $($script:events -join ',')"
}

Run-Case 'L1' { Link-Case 'U-B1' 'backup' 'OLD' } @((Link-R))
Run-Case 'L2' { Link-Case 'U-B2' 'program' 'DECOY' } @((Link-R @{ Runner = 'DECOY' }))
Run-Case 'L3' { Link-Case 'U-B1' 'backup' 'OLD' } @((Link-R @{ Rc = '0' }))
Run-Case 'L4' { Link-Case 'U-B1' 'backup' 'OLD' } @((Link-R @{ Same = $false }))
Run-Case 'L5' { Link-Case 'U-B1' 'backup' 'OLD' } @((Link-R @{ Runner = 'DECOY' }))
Run-Case 'L6' { Link-Case 'U-B1' 'backup' 'OLD' } @((Link-R @{ Version = '0.1.0' }))
Run-Case 'L7' { Link-Case 'U-B1' 'backup' 'OLD' } @((Link-R @{ Svc = 'RUNNING/200' }))
Run-Case 'L8' { Link-Case 'U-B1' 'backup' 'OLD' } @((Link-R @{ Svc = 'STOPPED/0'; SvcBefore = 'STOPPED/0' }))
Run-Case 'L9' { Link-Case 'U-B1' 'backup' 'OLD' } @({ [IO.Directory]::Delete("$prod\backup"); Link-R })
Run-Case 'L10' { Link-Case 'U-B1' 'backup' 'OLD' } @((Link-R @{ TimedOut = $true }))
$script:mklinkWorks = $false
$script:lines.Clear(); $script:events.Clear(); $script:queue.Clear()
Link-Case 'U-B1' 'backup' 'OLD'
"L11 | ran | $(@($script:lines | Where-Object { $_ -like 'VERDICT *' }) -join ' / ') | $($script:events -join ',')"

Run-Case 'B1' { Case-UB3 'U-B3' 'None' } @((Run1), (Run2))
Run-Case 'B2' { Case-UB3 'U-B3b' 'ReadWrite' } @((Run1), (Run2))
Run-Case 'B3' { Case-UB3 'U-B3' 'None' } @((Run1 @{ Rc = '0' }), (Run2))
Run-Case 'B4' { Case-UB3 'U-B3' 'None' } @((Run1 @{ Same = $false }), (Run2))
Run-Case 'B5' { Case-UB3 'U-B3' 'None' } @({ [IO.File]::Delete("$prod\backup\locked.txt"); Run1 }, (Run2))
Run-Case 'B6' { Case-UB3 'U-B3' 'None' } @((Run1 @{ Svc = 'RUNNING/200' }), (Run2))
Run-Case 'B7' { Case-UB3 'U-B3' 'None' } @((Run1 @{ Runner = 'PAYLOAD' }), (Run2))
Run-Case 'B8' { Case-UB3 'U-B3' 'None' } @((Run1 @{ Version = '0.1.0' }), (Run2))
Run-Case 'B9' { Case-UB3 'U-B3' 'None' } @((Run1 @{ Steps = @('update-backup') }), (Run2))
Run-Case 'B10' { Case-UB3 'U-B3' 'None' } @((Run1 @{ Steps = @('update-backup-cleanup', 'update-backup-cleanup', 'update-backup') }), (Run2))
Run-Case 'B11' { Case-UB3 'U-B3' 'None' } @((Run1 @{ Steps = @('update-backup-cleanup') }), (Run2))
Run-Case 'B12' { Case-UB3 'U-B3' 'None' } @((Run1), (Run2 @{ Rc = '43' }))
Run-Case 'B13' { Case-UB3 'U-B3' 'None' } @((Run1), (Run2 @{ Steps = @('update-backup-cleanup', 'update-backup', 'update-swap') }))
Run-Case 'B14' { Case-UB3 'U-B3' 'None' } @((Run1 @{ TimedOut = $true }), (Run2))
Run-Case 'B15' { Case-UB3 'U-B3' 'None' } @((Run1), (Run2 @{ TimedOut = $true }))
$script:lines.Clear(); $script:events.Clear(); $script:queue.Clear()
$script:holderOk = $false
Case-UB3 'U-B3' 'None'
"B16 | ran | $(@($script:lines | Where-Object { $_ -like 'VERDICT *' }) -join ' / ') | $($script:events -join ',')"
Run-Case 'B17' { Case-UB3 'U-B3' 'None' } @({ throw 'boom' })
Run-Case 'B18' { Case-UB3 'U-B3' 'None' } @((Run1 @{ Svc = 'STOPPED/0'; SvcBefore = 'STOPPED/0' }), (Run2))

Run-Case 'P1' { Update-Case 'U-B5' $false } @((Upd))
Run-Case 'P2' { Update-Case 'U-B4' $true } @((Upd))
Run-Case 'P3' { Update-Case 'U-B5' $false } @((Upd @{ Rc = '1' }))
Run-Case 'P4' { Update-Case 'U-B5' $false } @((Upd @{ Same = $false }))
Run-Case 'P5' { Update-Case 'U-B5' $false } @((Upd @{ Backup = 'dir' }))
Run-Case 'P6' { Update-Case 'U-B5' $false } @((Upd @{ Runner = 'OLD' }))
Run-Case 'P7' { Update-Case 'U-B5' $false } @((Upd @{ Version = '0.0.1' }))
Run-Case 'P8' { Update-Case 'U-B5' $false } @((Upd @{ Exe = $false }))
Run-Case 'P9' { Update-Case 'U-B5' $false } @((Upd @{ KeyName = 'ecosystem runner' }))
Run-Case 'P10' { Update-Case 'U-B5' $false } @((Upd @{ KeyVer = '0.0.1' }))
Run-Case 'P11' { Update-Case 'U-B5' $false } @((Upd @{ Svc = 'STOPPED/0' }))
Run-Case 'P12' { Update-Case 'U-B5' $false } @((Upd @{ Svc = 'RUNNING/100' }))
Run-Case 'P13' { Update-Case 'U-B5' $false } @((Upd @{ Steps = @('update-swap') }))
Run-Case 'P14' { Update-Case 'U-B4' $true } @((Upd @{ Steps = @('update-backup-cleanup') }))
Run-Case 'P15' { Update-Case 'U-B5' $false } @((Upd @{ TimedOut = $true }))
"""

MEASURE_SCENARIO = r"""
$bin = Join-Path $base 'bin'
$script:lines = New-Object System.Collections.Generic.List[string]
$script:snaps = New-Object System.Collections.Queue
$script:runCalls = New-Object System.Collections.Generic.List[string]
$script:rc = '0'
function Log([string]$line) { $script:lines.Add($line) }
function Get-Snapshot { $script:snaps.Dequeue() }
function Prod-Text { 'LISTING' }
function Get-Svc { 'RUNNING/100' }
function Get-Owner { 'OWNER' }
function Probe-Audit { 'exit=0 answer=[clean]' }
function Run-Inst([string]$exe, [string]$argText, [double]$limit) { $script:runCalls.Add("$(Split-Path -Leaf $exe)|$argText|$limit"); [pscustomobject]@{ Rc = $script:rc; Sec = 2.5 } }
function Get-State { [pscustomobject]@{ Runner = 'PAYLOAD'; Version = '0.1.0'; Backup = 'absent'; Exe = $true; KeyName = 'Ecosystem Runner'; KeyVer = '0.1.0'; Svc = 'RUNNING/200'; Steps = @('a', 'b') } }
function Elapsed([double]$s) { $script:caseSw = [pscustomobject]@{ Elapsed = [pscustomobject]@{ TotalSeconds = $s } } }

Elapsed 30.0
$script:snaps.Enqueue(@('FILE a 1 AB')); $script:snaps.Enqueue(@('FILE a 1 AB'))
$r = Measure-Inst 'U-B9' ' run1'
$script:lines
"RESULT rc=$($r.Rc) sec=$($r.Sec) same=$($r.Same) timed_out=$($r.TimedOut) svc_before=$($r.SvcBefore)"
"CALL $($script:runCalls[-1])"

$script:lines.Clear()
Elapsed 118.0; $script:rc = 'timeout'
$script:snaps.Enqueue(@('FILE a 1 AB')); $script:snaps.Enqueue(@('FILE a 2 CD', 'FILE b 1 EF'))
$r = Measure-Inst 'U-B9' ''
$script:lines[1]
"RESULT rc=$($r.Rc) same=$($r.Same) timed_out=$($r.TimedOut)"
"CALL $($script:runCalls[-1])"

$script:rc = '0'
$limits = @()
foreach ($e in @(0.0, 30.0, 59.9, 109.0, 110.0, 118.0)) {
    Elapsed $e
    $script:snaps.Enqueue(@()); $script:snaps.Enqueue(@())
    [void](Measure-Inst 'U-B9' '')
    $limits += "$e=$($script:runCalls[-1].Split('|')[2])"
}
"LIMITS $($limits -join ' ')"
"""

RUN_SCENARIO = r"""
$root = $base
$script:cmds = New-Object System.Collections.Generic.List[string]
function Cmd { $script:cmds.Add(($args -join ' ')); '' }
$a = Run-Inst '/bin/sh' '-c "exit 3"' 30
"exit3: rc=$($a.Rc) sec_ok=$($a.Sec -lt 30) cmds=$($script:cmds.Count)"
$a = Run-Inst '/bin/sh' '-c "exit 0"' 30
"exit0: rc=$($a.Rc) cmds=$($script:cmds.Count)"
$a = Run-Inst '/bin/sh' '-c "exec sleep 60"' 1
"timeout: rc=$($a.Rc) sec_ok=$(($a.Sec -ge 1) -and ($a.Sec -lt 30)) taskkill=$(@($script:cmds | Where-Object { $_ -like 'taskkill /T /F /PID *' }).Count)"
$a = Run-Inst (Join-Path $base 'no-such-file') '' 5
"missing: $($a.Rc.StartsWith('error: ')) cmds=$($script:cmds.Count)"
$cwdFile = Join-Path $base 'cwd.txt'
[void](Run-Inst '/bin/sh' ('-c "pwd -P > ' + $cwdFile + '"') 30)
"cwd: ran_in_root=$([IO.Path]::GetFileName(@(Get-Content -LiteralPath $cwdFile)[0]) -eq [IO.Path]::GetFileName($root))"
"""

SEED_SCENARIO = r"""
$prod = Join-Path $base 'prod'
$script:events = New-Object System.Collections.Generic.List[string]
function Reset-All { $script:events.Add('reset') }
function Seed-Signer { $script:events.Add('signer') }
function Mark-Prod { $script:events.Add('mark'); Mkdirs @($prod) }
function Set-Key { $script:events.Add('key') }
function Ensure-Stub { $script:events.Add('stub'); 'RUNNING/1' }
function Vis($t) { if ($null -eq $t) { return 'null' }; ($t -replace "`r", '<CR>') -replace "`n", '<LF>' }
Seed-Base $true
"with-program events=$($script:events -join ',') state=$(Vis (Read-Ascii (Join-Path $prod 'installer-state.json'))) runner=$(Vis (Read-Ascii "$prod\program\runner.exe"))"
$script:events.Clear()
$prod = Join-Path $base 'prod2'
Seed-Base $false
"without-program events=$($script:events -join ',') state=$(Vis (Read-Ascii (Join-Path $prod 'installer-state.json'))) runner=$(Vis (Read-Ascii "$prod\program\runner.exe"))"
Seed-Stale
"stale runner=$(Vis (Read-Ascii "$prod\backup\program\runner.exe")) service=$(Vis (Read-Ascii "$prod\backup\service.json")) y=$(Vis (Read-Ascii "$prod\backup\z-dir\y.txt")) complete=$(Exists "$prod\backup\complete")"
"""

SEED_ACL_SCENARIO = r"""
$ErrorActionPreference = 'Continue'  # same as the driver outside Mark-Prod
$log = Join-Path $base 'seed.log'
$descriptor = [pscustomobject]@{}
$descriptor | Add-Member ScriptMethod SetSecurityDescriptorSddlForm { param($sddl, $sections) $script:requested = $sddl }
function New-Object([string]$typeName) {
    if ($typeName -ne 'System.Security.AccessControl.DirectorySecurity') { throw "unexpected type $typeName" }
    $descriptor
}
function Set-Acl($LiteralPath, $AclObject) {
    if ($mode -eq 'set-error') { Write-Error 'cannot set ACL' }
    if ($LiteralPath -ne $prod -or $AclObject -ne $descriptor) { throw 'wrong Set-Acl arguments' }
    $script:applied = $requested
}
function Get-Acl($LiteralPath) {
    if ($mode -eq 'get-error') { Write-Error 'cannot read ACL' }
    if ($LiteralPath -ne $prod -or -not $applied) { throw 'ACL not applied to product folder' }
    $acl = [pscustomobject]@{ AreAccessRulesProtected = $mode -ne 'unprotected' }
    $acl | Add-Member ScriptMethod GetOwner { param($type)
        if ($type -ne [Security.Principal.SecurityIdentifier]) { throw 'expected SID' }
        @{ Value = $(if ($mode -eq 'owner') { 'S-1-5-18' } else { 'S-1-5-32-544' }) }
    }
    $acl | Add-Member ScriptMethod GetSecurityDescriptorSddlForm { param($sections)
        if ($sections -ne 'Access') { throw 'expected DACL only' }
        $applied.Substring($applied.IndexOf('D:'))
    }
    $acl | Add-Member ScriptMethod GetAccessRules { param($explicit, $inherited, $type)
        if (-not ($explicit -and $inherited) -or $type -ne [Security.Principal.SecurityIdentifier]) { throw 'expected all rules as SIDs' }
        foreach ($sid in 'S-1-5-18', 'S-1-5-32-544') {
            @{ IdentityReference = @{ Value = $(if ($mode -eq 'duplicate') { 'S-1-5-18' } else { $sid }) }
               IsInherited = $mode -eq 'inherited'; AccessControlType = $(if ($mode -eq 'deny') { 'Deny' } else { 'Allow' })
               FileSystemRights = $(if ($mode -eq 'rights') { 'Read' } else { 'FullControl' })
               InheritanceFlags = $(if ($mode -eq 'flags') { 'ContainerInherit' } else { 'ContainerInherit, ObjectInherit' })
               PropagationFlags = $(if ($mode -eq 'propagation') { 'InheritOnly' } else { 'None' }) }
        }
        if ($mode -eq 'extra') {
            @{ IdentityReference = @{ Value = 'S-1-5-32-545' }; IsInherited = $false; AccessControlType = 'Allow'
               FileSystemRights = 'FullControl'; InheritanceFlags = 'ContainerInherit, ObjectInherit'; PropagationFlags = 'None' }
        }
    }
    $acl
}
foreach ($mode in 'good', 'set-error', 'get-error', 'owner', 'unprotected', 'duplicate', 'rights', 'extra', 'flags', 'inherited',
               'deny', 'propagation') {
    $prod = Join-Path $base $mode
    $script:applied = $null
    [IO.File]::WriteAllText($log, '')
    Try-Case $mode { Mark-Prod; Verdict $mode $true 'seeded' }
    "$mode marker=$(Test-Path -LiteralPath (Join-Path $prod $markerName)) $(Write-Summary)"
    if ($mode -eq 'good') { Get-Content -LiteralPath $log | Where-Object { $_ -like 'SEED *' } }
}
"""


@requires_pwsh
class DriverFunctionsRunForReal(unittest.TestCase):
    def test_bad_seed_is_an_error_not_a_verdict(self):
        funcs = ("Mark-Prod", "Mkdirs", "Write-Ascii", "Log", "Try-Case", "Verdict", "Write-Summary")
        lines = run_functions(SCRIPT, funcs, SEED_ACL_SCENARIO, ("markerName", "markerText"))
        self.assertEqual(lines, [
            "good marker=True SUMMARY pass=1 fail=0 unproven=0 refused=0 error=0",
            "SEED owner=S-1-5-32-544 dacl=D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)",
            *[f"{mode} marker=False SUMMARY pass=0 fail=0 unproven=0 refused=0 error=1"
              for mode in ("set-error", "get-error", "owner", "unprotected", "duplicate", "rights", "extra", "flags",
                           "inherited", "deny", "propagation")],
        ])

    def test_driver_parses(self):
        cmd = ('$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile($env:G7_SCRIPT,[ref]$null,[ref]$e);'
               'exit $e.Count')
        r = subprocess.run([PWSH, "-NoProfile", "-Command", cmd], capture_output=True, text=True, env={**os.environ, "G7_SCRIPT": str(SCRIPT)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_remove_entry_refuses_every_path_outside_and_removes_the_product_folder_without_its_link_targets(self):
        lines = run_functions(SCRIPT, ("Remove-Entry", "Get-Attr", "Exists", "Log"), REMOVE_SCENARIO)
        self.assertEqual(lines, ["refused"] * 10 + ["kept: evil=True outside=True", "fixture folder removed: True",
                                                    "product folder removed: True target kept: True sibling kept: True",
                                                    "cmd verbs=del,rmdir slash_s=0"], lines)

    def test_the_gate_refuses_what_it_did_not_create_and_this_run_writes_and_removes_only_its_own_signer_file(self):
        funcs = ("Test-Gate", "Get-Foreign", "Reset-All", "Seed-Signer", "Remove-Signer", "Remove-Entry", "Stop-Holder", "Get-Attr", "Exists", "Read-Ascii",
                 "Write-Ascii", "Mkdirs", "Log")
        variables = ("markerName", "markerText", "keyName", "keyPath", "sig", "signerText", "gateOk", "signerMade", "signerDirMade", "holder")
        lines = run_functions(SCRIPT, funcs, GATE_SCENARIO, variables)
        self.assertEqual(lines, [
            "1 foreign-folder gate=False refused=1 names_path=True reset=threw kept=True",
            "2 marked-folder gate=True refused=0 reset=ran folder_gone=True key_removed=True outside_made=True",
            "3 foreign-key gate=False refused=1 names_key=True shows_content=False reset=threw key_removed=False",
            "4 own-key gate=True refused=0",
            "5 clean gate=True refused=0",
            "6 wrong-marker gate=False refused=1",
            "7 own-folder-foreign-key gate=False refused=1",
            "8 foreign-service gate=False refused=1 names_service=True shows_state=False reset=threw folder_kept=True",
            "9 unreadable-service gate=False refused=1 says_not_queried=True",
            "10 empty-answer gate=False refused=1",
            "11 foreign-signer gate=False refused=1 names_file=True shows_content=False seed=threw reset=threw kept=something-else",
            "12 own-signer gate=True refused=0 made=False kept=True",
            "13 seed-no-folder written=True made=True dir_made=True",
            "14 remove-made file_gone=True dir_gone=True made=False dir_made=False",
            "15 seed-with-folder written=True made=True dir_made=False",
            "16 remove-keeps-folder file_gone=True dir_kept=True",
            "17 folder-not-empty file_gone=True other_kept=True cleanup_lines=1 dir_made=False",
            "18 before-gate seed=threw remove=threw kept=keep-me"], lines)

    def test_the_stub_service_is_made_after_the_gate_and_stopped_and_deleted_only_when_this_run_made_it(self):
        lines = run_functions(SCRIPT, ("Ensure-Stub", "Remove-Stub", "Get-Svc", "Log", "Yn"), STUB_SCENARIO, ("gateOk", "svcMade"))
        self.assertEqual(lines, [
            "1 before-gate ensure=threw calls=0 made=False",
            "2 create-and-start result=RUNNING/4242 made=True created=1 started=1 sc=running",
            "3 create_args=sc create EcosystemRunner binPath= STUB start= demand",
            "4 log=STUB create: made=Y answer=[[SC] CreateService SUCCESS]",
            "5 already-running result=RUNNING/4242 created=0 started=0 made=True",
            "6 remove-made stopped=1 deleted=1 sc=absent made=False",
            "7 remove-foreign calls=0 sc=running",
            "8 create-fails result=GONE/0 made=False line=STUB create: made=N answer=[[SC] OpenSCManager FAILED 5:] later_calls=0",
            "9 never-starts result=STOPPED/0 slept=30 started=1",
            "10 never-stops slept=20 stopped=1 deleted=1 sc=absent made=False"], lines)

    def test_get_svc_reads_state_and_process_id_from_what_sc_queryex_prints(self):
        lines = run_functions(SCRIPT, ("Get-Svc",), SVC_SCENARIO)
        self.assertEqual(lines, ["running: RUNNING/4176", "stopped: STOPPED/0", "pending: START_PENDING/1234", "gone: GONE/0", "denied: UNKNOWN/0",
                                 "empty: UNKNOWN/0"], lines)

    def test_the_readers_classify_the_program_file_read_the_state_version_the_steps_and_the_backup(self):
        funcs = ("Runner-Class", "State-Version", "Step-Names", "Get-State", "Get-Attr", "Exists", "Read-Ascii", "Write-Ascii", "Mkdirs")
        lines = run_functions(SCRIPT, funcs, READERS_SCENARIO, ("oldText", "decoyText", "staleText"))
        self.assertEqual(lines, [
            "1 nothing: runner=ABSENT version=ABSENT backup=absent exe=False key=[Ecosystem Runner 0.1.0] svc=RUNNING/77 steps=[]",
            "runner for [OLD-RUNNER-g7d]: OLD",
            "runner for [DECOY-RUNNER-g7d]: DECOY",
            "runner for [STALE-RUNNER-g7d]: STALE",
            "runner for [PAYLOAD-TEXT]: PAYLOAD",
            "runner for [old-runner-g7d]: OTHER(14 bytes)",
            "runner for []: OTHER(0 bytes)",
            "runner for [PAYLOAD-TEXT ]: OTHER(13 bytes)",
            'version for [{"schema_version": 1, "installer_version": "0.0.1"}]: 0.0.1',
            'version for [{"schema_version": 1, "installer_version": "0.1.0"}]: 0.1.0',
            "version for [not json]: UNPARSED",
            "steps: update-backup-cleanup,update-backup count=2",
            "no steps file: count=0",
            "2 updated: runner=PAYLOAD version=0.1.0 backup=absent exe=True key=[Ecosystem Runner 0.1.0] svc=RUNNING/77 steps=[update-swap]",
            "3 backup dir: runner=PAYLOAD version=0.1.0 backup=dir exe=True key=[Ecosystem Runner 0.1.0] svc=RUNNING/77 steps=[update-swap]",
            "4 backup link: runner=PAYLOAD version=0.1.0 backup=link exe=True key=[Ecosystem Runner 0.1.0] svc=RUNNING/77 steps=[update-swap]"], lines)

    def test_the_audit_probe_runs_the_command_winsys_nsh_ships_as_plain_powershell_over_the_product_folder(self):
        scenario = AUDIT_SCENARIO.replace("%WINSYS%", str(NSIS / "winsys.nsh"))
        lines = run_functions(SCRIPT, ("Get-AuditCommand", "Read-Ascii"), scenario)
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[0], "ERRORS 0")
        self.assertEqual(lines[2], "MISSING True")
        cmd = lines[1][len("CMD "):]
        product = "[IO.Path]::Combine([Environment]::GetFolderPath('CommonApplicationData'), 'EcosystemRunner')"
        self.assertTrue(cmd.startswith("$ErrorActionPreference='Stop';$p=" + product + ";"), cmd)
        for text in ("Get-ChildItem -LiteralPath $d -Force", "$c.Attributes -band 1024", "$c.LinkType -eq 'HardLink'", "Get-Acl -LiteralPath $c.FullName",
                     "'S-1-5-18'", "'S-1-5-32-544'", "{'links'}", "{'empty'}", "{'owners'}", "else{'clean'}"):
            self.assertIn(text, cmd)
        self.assertNotIn("$$", cmd)
        self.assertNotIn("$APPDATA", cmd)
        self.assertEqual(cmd, between(WINSYS, "Function Winsys_FolderAudit", 'FunctionEnd').split('-Command "', 1)[1].split('"`', 1)[0]
                         .replace("$$", "$").replace("'$APPDATA\\EcosystemRunner'", product))

    def test_the_summary_counts_pass_fail_unproven_refused_and_every_kind_of_error_and_try_case_logs_a_script_error(self):
        lines = run_functions(SCRIPT, ("Write-Summary", "Try-Case", "Log", "Verdict", "Unproven", "Yn"), SUMMARY_SCENARIO, ("selected",))
        self.assertEqual(len(lines), 6, lines)
        self.assertRegex(lines[0], r"^SUMMARY pass=1 fail=1 unproven=1 refused=1 error=1$")
        self.assertRegex(lines[1], r"^VERDICT U-B1: PASS rc=39\|CASE U-B2: SCRIPT-ERROR boom at line \d+\|VERDICT U-B3: FAIL x\|VERDICT U-B3b: UNPROVEN y\|"
                                  r"REFUSED: z\|SUMMARY pass=1 fail=1 unproven=1 refused=1 error=1$")
        self.assertEqual(lines[2:], ["SUMMARY pass=2 fail=1 unproven=1 refused=1 error=3", "last=SUMMARY pass=2 fail=1 unproven=1 refused=1 error=3",
                                     "SUMMARY pass=6 fail=0 unproven=0 refused=0 error=0", "SUMMARY pass=5 fail=0 unproven=0 refused=0 error=1"], lines)

    def test_only_runs_just_the_selected_cases_and_logs_the_others_as_not_selected(self):
        lines = run_functions(SCRIPT, ("Try-Case", "Log"), SELECT_SCENARIO)
        self.assertEqual(lines, ["CASE U-B1: NOT-SELECTED|CASE U-B2: NOT-SELECTED|RAN U-B3|CASE U-B3b: NOT-SELECTED|CASE u-b4: NOT-SELECTED|RAN U-B4",
                                 "RAN U-B1|RAN U-B2"], lines)

    def test_only_is_parsed_and_an_unknown_name_is_refused_before_anything_runs(self):
        head, sep, _ = DRIVER.partition("\n$tree = (Get-Location).Path")
        self.assertTrue(sep)
        self.assertNotIn("Log ", head)
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp, "head.ps1")
            script.write_text(head + "\n'SELECTED ' + ($selected -join '|') + ' count=' + $selected.Count\n", encoding="ascii")
            for only, rc, out in [
                (None, 0, "SELECTED  count=0"), ("", 0, "SELECTED  count=0"),
                (" U-B3 ,,U-B5", 0, "SELECTED U-B3|U-B5 count=2"), ("U-B3,U-B3b,U-B4,U-B5", 0, "SELECTED U-B3|U-B3b|U-B4|U-B5 count=4"),
                ("U-B3,u-b4", 2, "REFUSED-ARG: -Only [U-B3,u-b4] names unknown case u-b4; known: U-B1,U-B2,U-B3,U-B3b,U-B4,U-B5"),
                ("U-B9", 2, "REFUSED-ARG: -Only [U-B9] names unknown case U-B9; known: U-B1,U-B2,U-B3,U-B3b,U-B4,U-B5"),
            ]:
                with self.subTest(only=only):
                    argv = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(script)] + ([] if only is None else ["-Only", only])
                    r = subprocess.run(argv, capture_output=True, text=True, cwd=tmp, timeout=60)
                    self.assertEqual((r.returncode, r.stdout.splitlines()), (rc, [out]), r.stderr)
            self.assertEqual(sorted(os.listdir(tmp)), ["head.ps1"])

    def test_a_finished_update_needs_every_one_of_its_ten_facts(self):
        lines = run_functions(SCRIPT, ("Updated-Ok",), OK_SCENARIO)
        self.assertEqual(lines, ["good: True"] + ["%s: False" % k for k in (
            "rc1", "rc43", "outside_changed", "backup_dir", "backup_link", "runner_old", "runner_stale", "state_old", "no_uninstall_exe", "key_name_case",
            "key_name_seed", "key_version_old", "service_stopped", "service_same_process")], lines)

    def test_each_case_turns_what_was_measured_into_pass_fail_or_unproven_and_always_releases_the_lock(self):
        funcs = ("Link-Case", "Case-UB3", "Update-Case", "Updated-Ok", "Verdict", "Unproven", "Yn", "Get-Attr", "Exists", "Write-Ascii", "Mkdirs")
        lines = run_functions(SCRIPT, funcs, CASES_SCENARIO, ("oldText", "decoyText", "staleText"))
        link = "seed-base:True,cmd:mklink,measure:U-B1"
        fail39 = "VERDICT U-B1: FAIL rc=39 outside_same=Y runner=OLD state_version=0.0.1"
        b3 = "seed-base:True,seed-stale,holder:None,measure:U-B3 run1,stop-holder,measure:U-B3 run2"
        ok3 = "VERDICT U-B3: PASS rc1=43 rc2=0 run1_as_expected=Y run2_as_expected=Y new_steps_in_run2=0"
        p5 = "seed-base:True,measure:U-B5"
        self.assertEqual(lines, [
            "L1 | ran | VERDICT U-B1: PASS rc=39 outside_same=Y runner=OLD state_version=0.0.1 | " + link,
            "L2 | ran | VERDICT U-B2: PASS rc=39 outside_same=Y runner=DECOY state_version=0.0.1 | seed-base:False,cmd:mklink,measure:U-B2",
            "L3 | ran | VERDICT U-B1: FAIL rc=0 outside_same=Y runner=OLD state_version=0.0.1 | " + link,
            "L4 | ran | VERDICT U-B1: FAIL rc=39 outside_same=N runner=OLD state_version=0.0.1 | " + link,
            "L5 | ran | VERDICT U-B1: FAIL rc=39 outside_same=Y runner=DECOY state_version=0.0.1 | " + link,
            "L6 | ran | VERDICT U-B1: FAIL rc=39 outside_same=Y runner=OLD state_version=0.1.0 | " + link,
            "L7 | ran | " + fail39 + " | " + link,
            "L8 | ran | " + fail39 + " | " + link,
            "L9 | ran | " + fail39 + " | " + link,
            "L10 | ran | VERDICT U-B1: UNPROVEN the run hit the case limit and was killed | " + link,
            "L11 | ran | VERDICT U-B1: UNPROVEN fixture could not be built | seed-base:True,cmd:mklink",
            "B1 | ran | " + ok3 + " | " + b3,
            "B2 | ran | VERDICT U-B3b: PASS rc1=43 rc2=0 run1_as_expected=Y run2_as_expected=Y new_steps_in_run2=0 | "
            "seed-base:True,seed-stale,holder:ReadWrite,measure:U-B3b run1,stop-holder,measure:U-B3b run2",
            "B3 | ran | VERDICT U-B3: FAIL rc1=0 rc2=0 run1_as_expected=N run2_as_expected=Y new_steps_in_run2=0 | " + b3,
            "B4 | ran | VERDICT U-B3: FAIL rc1=43 rc2=0 run1_as_expected=N run2_as_expected=Y new_steps_in_run2=0 | " + b3,
            "B5 | ran | VERDICT U-B3: FAIL rc1=43 rc2=0 run1_as_expected=N run2_as_expected=Y new_steps_in_run2=0 | " + b3,
            "B6 | ran | VERDICT U-B3: FAIL rc1=43 rc2=0 run1_as_expected=N run2_as_expected=Y new_steps_in_run2=0 | " + b3,
            "B7 | ran | VERDICT U-B3: FAIL rc1=43 rc2=0 run1_as_expected=N run2_as_expected=Y new_steps_in_run2=0 | " + b3,
            "B8 | ran | VERDICT U-B3: FAIL rc1=43 rc2=0 run1_as_expected=N run2_as_expected=Y new_steps_in_run2=0 | " + b3,
            "B9 | ran | VERDICT U-B3: FAIL rc1=43 rc2=0 run1_as_expected=N run2_as_expected=N new_steps_in_run2=1 | " + b3,
            "B10 | ran | VERDICT U-B3: FAIL rc1=43 rc2=0 run1_as_expected=N run2_as_expected=N new_steps_in_run2=-1 | " + b3,
            "B11 | ran | VERDICT U-B3: FAIL rc1=43 rc2=0 run1_as_expected=N run2_as_expected=N new_steps_in_run2=1 | " + b3,
            "B12 | ran | VERDICT U-B3: FAIL rc1=43 rc2=43 run1_as_expected=Y run2_as_expected=N new_steps_in_run2=0 | " + b3,
            "B13 | ran | VERDICT U-B3: FAIL rc1=43 rc2=0 run1_as_expected=Y run2_as_expected=N new_steps_in_run2=1 | " + b3,
            "B14 | ran | VERDICT U-B3: UNPROVEN run 1 hit the case limit and was killed | seed-base:True,seed-stale,holder:None,measure:U-B3 run1,stop-holder",
            "B15 | ran | VERDICT U-B3: UNPROVEN run 2 hit the case limit and was killed | " + b3,
            "B16 | ran | VERDICT U-B3: UNPROVEN the background process did not take the lock | seed-base:True,seed-stale,holder:None,stop-holder",
            "B17 | threw boom |  | seed-base:True,seed-stale,holder:None,measure:U-B3 run1,stop-holder",
            "B18 | ran | VERDICT U-B3: FAIL rc1=43 rc2=0 run1_as_expected=N run2_as_expected=Y new_steps_in_run2=0 | " + b3,
            "P1 | ran | VERDICT U-B5: PASS rc=0 runner=PAYLOAD state_version=0.1.0 backup=absent | " + p5,
            "P2 | ran | VERDICT U-B4: PASS rc=0 runner=PAYLOAD state_version=0.1.0 backup=absent | seed-base:True,seed-stale,measure:U-B4",
            "P3 | ran | VERDICT U-B5: FAIL rc=1 runner=PAYLOAD state_version=0.1.0 backup=absent | " + p5,
            "P4 | ran | VERDICT U-B5: FAIL rc=0 runner=PAYLOAD state_version=0.1.0 backup=absent | " + p5,
            "P5 | ran | VERDICT U-B5: FAIL rc=0 runner=PAYLOAD state_version=0.1.0 backup=dir | " + p5,
            "P6 | ran | VERDICT U-B5: FAIL rc=0 runner=OLD state_version=0.1.0 backup=absent | " + p5,
            "P7 | ran | VERDICT U-B5: FAIL rc=0 runner=PAYLOAD state_version=0.0.1 backup=absent | " + p5,
            "P8 | ran | VERDICT U-B5: FAIL rc=0 runner=PAYLOAD state_version=0.1.0 backup=absent | " + p5,
            "P9 | ran | VERDICT U-B5: FAIL rc=0 runner=PAYLOAD state_version=0.1.0 backup=absent | " + p5,
            "P10 | ran | VERDICT U-B5: FAIL rc=0 runner=PAYLOAD state_version=0.1.0 backup=absent | " + p5,
            "P11 | ran | VERDICT U-B5: FAIL rc=0 runner=PAYLOAD state_version=0.1.0 backup=absent | " + p5,
            "P12 | ran | VERDICT U-B5: FAIL rc=0 runner=PAYLOAD state_version=0.1.0 backup=absent | " + p5,
            "P13 | ran | VERDICT U-B5: FAIL rc=0 runner=PAYLOAD state_version=0.1.0 backup=absent | " + p5,
            "P14 | ran | VERDICT U-B4: FAIL rc=0 runner=PAYLOAD state_version=0.1.0 backup=absent | seed-base:True,seed-stale,measure:U-B4",
            "P15 | ran | VERDICT U-B5: UNPROVEN the run hit the case limit and was killed | " + p5], lines)

    def test_a_measured_run_gets_what_is_left_of_the_case_limit_and_logs_the_probe_the_case_line_and_both_folder_listings(self):
        lines = run_functions(SCRIPT, ("Measure-Inst", "Diff-Snap", "Yn"), MEASURE_SCENARIO, ("caseLimit", "sig"))
        self.assertEqual(lines, [
            "PROBE U-B9 run1 before the run: owner=[OWNER] audit=[exit=0 answer=[clean]]",
            "CASE U-B9 run1: rc=0 sec=2.5 outside=SAME(1 names) service=RUNNING/100 to RUNNING/200 runner=PAYLOAD state_version=0.1.0 backup=absent "
            "uninstall.exe=Y key=[Ecosystem Runner 0.1.0] steps=[a,b]",
            "CASE U-B9 run1 product folder before: LISTING",
            "CASE U-B9 run1 product folder after:  LISTING",
            "RESULT rc=0 sec=2.5 same=True timed_out=False svc_before=RUNNING/100",
            "CALL installer-update.exe|/S /SIGNER=%s|85" % SIG,
            "CASE U-B9: rc=timeout sec=2.5 outside=CHANGED missing=[FILE a 1 AB] added=[FILE a 2 CD ; FILE b 1 EF] service=RUNNING/100 to RUNNING/200 "
            "runner=PAYLOAD state_version=0.1.0 backup=absent uninstall.exe=Y key=[Ecosystem Runner 0.1.0] steps=[a,b]",
            "RESULT rc=timeout same=False timed_out=True",
            "CALL installer-update.exe|/S /SIGNER=%s|5" % SIG,
            "LIMITS 0=115 30=85 59.9=55 109=6 110=5 118=5"], lines)

    @unittest.skipUnless(Path("/bin/sh").exists(), "no POSIX shell")
    def test_run_inst_returns_the_exit_code_kills_a_run_at_the_limit_and_reports_one_that_cannot_start(self):
        lines = run_functions(SCRIPT, ("Run-Inst",), RUN_SCENARIO)
        self.assertEqual(lines, ["exit3: rc=3 sec_ok=True cmds=0", "exit0: rc=0 cmds=0", "timeout: rc=timeout sec_ok=True taskkill=1",
                                 "missing: True cmds=1", "cwd: ran_in_root=True"], lines)

    def test_the_seeds_write_an_install_of_0_0_1_in_the_order_the_cases_need_and_a_stale_backup_without_the_complete_marker(self):
        funcs = ("Seed-Base", "Seed-Stale", "Write-Ascii", "Read-Ascii", "Mkdirs", "Exists", "Get-Attr")
        lines = run_functions(SCRIPT, funcs, SEED_SCENARIO, ("oldText", "staleText"))
        state = '{"schema_version": 1, "installer_version": "0.0.1"}<CR><LF>'
        self.assertEqual(lines, [
            "with-program events=reset,signer,mark,key,stub state=" + state + " runner=OLD-RUNNER-g7d",
            "without-program events=reset,signer,mark,key,stub state=" + state + " runner=null",
            'stale runner=STALE-RUNNER-g7d service={"name": "EcosystemRunner"} y=Y complete=False'], lines)


if __name__ == "__main__":
    unittest.main()
