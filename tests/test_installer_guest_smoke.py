"""Uninstaller smoke (ecosystem-control#64, GUEST7B): uninstall-smoke.ps1 builds one fixture per case inside a disposable clone, runs the real
uninstall.exe in place (/S _?=<product folder>) and records exit code, wall time, what survives outside and what is left inside.
Static checks only; the guest run is the proof."""
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.guest_pwsh import requires_pwsh, run_functions

ROOT = Path(__file__).resolve().parent.parent
GUEST = ROOT / "installer" / "guest"
DRIVER = (GUEST / "uninstall-smoke.ps1").read_text(encoding="ascii")
UNINSTALL = (ROOT / "installer" / "nsis" / "uninstall.nsh").read_text(encoding="utf-8")


def body(name):
    """Text of one top-level function of the driver."""
    return DRIVER.split("function " + name, 1)[1].split("\n}\n", 1)[0]


class DriverMatchesTheUninstaller(unittest.TestCase):
    def test_product_folder_is_the_common_app_data_one_the_uninstaller_works_on(self):
        self.assertIn("SetShellVarContext all", UNINSTALL)
        self.assertIn("$prod = 'C:\\ProgramData\\EcosystemRunner'", DRIVER)
        self.assertIn("StrCmp $EXEDIR \"$APPDATA\\EcosystemRunner\"", UNINSTALL)

    def test_registry_entry_is_the_one_the_uninstaller_deletes_in_the_64_bit_view(self):
        self.assertIn("SetRegView 64", UNINSTALL)
        self.assertIn("DeleteRegKey HKLM \"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\EcosystemRunner\"", UNINSTALL)
        self.assertIn("$keyPath = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\EcosystemRunner'", DRIVER)
        self.assertIn("[Microsoft.Win32.RegistryView]::Registry64", DRIVER)

    def test_it_runs_the_uninstaller_in_place_and_silently_unless_dialogs_are_asked_for(self):
        self.assertIn('function Unrun { if ($script:dialogs) { "_?=$prod" } else { "/S _?=$prod" } }', DRIVER)
        self.assertIn("$script:dialogs = [bool]$Dialogs", DRIVER)
        self.assertIn("param([switch]$Dialogs)", DRIVER)
        self.assertIn('"/S _?=$root\\u7"', DRIVER)
        self.assertIn("uninstall-harness.exe.b64", DRIVER)
        self.assertIn("uninstall-guest.exe", DRIVER)

    def test_the_harness_writes_the_uninstaller_beside_itself(self):
        self.assertIn('WriteUninstaller "$EXEDIR\\uninstall-guest.exe"', (GUEST / "uninstall-harness.nsi").read_text(encoding="utf-8"))
        self.assertIn("Join-Path $bin 'uninstall-guest.exe'", DRIVER)


class DriverStaysInTheFixture(unittest.TestCase):
    def test_driver_is_ascii_and_names_no_secret_or_url(self):
        DRIVER.encode("ascii")
        self.assertNotRegex(DRIVER, r"https?://")
        self.assertNotRegex(DRIVER, r"(?i)password|credential|\.config")

    def test_every_path_it_names_is_under_the_fixture_or_the_product_folder(self):
        self.assertIn("$root = 'C:\\X\\g7b'", DRIVER)
        self.assertIn("refusing to remove outside the fixture", DRIVER)
        self.assertIn("$full.StartsWith($pr + $sep, [StringComparison]::Ordinal)", DRIVER)
        self.assertIn("$full.StartsWith($root.TrimEnd($sep) + $sep, [StringComparison]::Ordinal)", DRIVER)
        for drive in re.findall(r"[A-Za-z]:\\[^\s'\"]*", DRIVER):
            self.assertTrue(drive.startswith(("C:\\X\\g7b", "C:\\ProgramData\\EcosystemRunner")), drive)

    def test_no_recursive_delete_can_follow_a_link(self):
        self.assertNotRegex(DRIVER, r"(?i)-Recurse")
        self.assertNotRegex(DRIVER, r"(?i)\brd\s+/s|rmdir\s+/s|\bdel\s+/s")
        remover = body("Remove-Entry")
        self.assertLess(remover.index("-band 0x400"), remover.index("GetFileSystemEntries"))
        self.assertIn("'rmdir'", remover)
        self.assertIn("'del'", remover)

    def test_the_snapshot_never_enters_a_link(self):
        walk = body("Snap-Walk")
        self.assertLess(walk.index("-band 0x400"), walk.index("Snap-Walk $e"))
        self.assertIn("SHA256", DRIVER)

    def test_the_acl_is_reset_and_the_lock_released_whatever_happens(self):
        self.assertIn("icacls.exe \"$prod\\b-locked\" /reset", DRIVER)
        self.assertIn("$h.Close()", DRIVER)
        self.assertIn("$hp.Kill()", DRIVER)
        self.assertIn("$logName = if ($script:dialogs) { 'u-dialogs.txt' } else { 'u-smoke.txt' }", DRIVER)
        self.assertIn("Copy-Item -LiteralPath $log -Destination (Join-Path $out $logName)", DRIVER)
        self.assertEqual(DRIVER.count("Copy-Item -LiteralPath $log -Destination (Join-Path $out $logName)"), 3)
        self.assertNotIn("(Join-Path $out 'u-smoke.txt')", DRIVER)


class DriverCoversTheCases(unittest.TestCase):
    def test_every_case_is_run_and_wrapped_so_one_error_cannot_stop_the_rest(self):
        for case in ("'U1'", "'U2'", "'U2b'", "'U4-26'", "'U4-20'", "'U3'", "'U5'", "'U7'", "'U8'", "'U9'"):
            self.assertIn("Try-Case %s" % case, DRIVER)
        self.assertIn("VERDICT ", DRIVER)
        for state in ("PASS", "FAIL", "UNPROVEN"):
            self.assertIn(state, DRIVER)

    def test_u1_has_the_seven_links_real_content_and_the_decoy(self):
        u1 = body("Case-U1")
        for name in ("a1-linkFull", "a2-linkEmpty", "a3-linkGone", "a4-symFull", "a5-symGone", "a6-fileLink.txt", "m-real\\inner\\linkB"):
            self.assertIn(name, u1)
        for flag in ("'/J'", "'/D'"):
            self.assertIn(flag, u1)
        self.assertIn("[IO.Directory]::Delete(\"$o\\gone\")", u1)
        self.assertIn("[IO.Directory]::Delete(\"$o\\symgone\")", u1)
        self.assertIn("ReadOnly", u1)
        self.assertIn("Hidden", u1)
        self.assertIn("decoy.txt", u1)
        self.assertIn("Get-WinEvent", u1)

    def test_u2_makes_the_product_folder_itself_a_link_and_expects_40_with_nothing_removed(self):
        u2 = body("Case-U2([string]$flag, [string]$label)")
        self.assertIn("Cmd 'mklink' $flag $prod $p2", u2)
        self.assertIn("-eq '40'", u2)
        self.assertIn("keep-p2.txt", u2)
        self.assertIn("Case-U2 '/J' 'U2'", DRIVER)
        self.assertIn("Case-U2 '/D' 'U2b'", DRIVER)

    def test_u4_builds_the_chain_and_reports_what_is_left_at_26_and_20_levels(self):
        u4 = body("Case-U4([int]$n)")
        for text in ("f$i.txt", "bottom.txt", "folder_levels_left", "files_left"):
            self.assertIn(text, u4)
        self.assertIn("Case-U4 26", DRIVER)
        self.assertIn("Case-U4 20", DRIVER)

    def test_u3_u5_u7_u8_each_state_what_makes_them_unproven(self):
        for name, why in (("Case-U3", "did not make the folder unlistable"), ("Case-U5", "did not take the lock"),
                          ("Case-U8", "did not block the removal of the link")):
            self.assertIn(why, body(name))
        u3 = body("Case-U3")
        self.assertIn("/deny '*S-1-1-0:(RD)'", u3)
        self.assertIn("-eq '40'", u3)
        u5 = body("Case-U5")
        self.assertIn("[IO.File]::Open($path, ''Open'', ''Read'', ''None'')", u5)
        self.assertIn("rerun_after_release", u5)
        u7 = body("Case-U7")
        self.assertIn("-eq '0'", u7)
        u8 = body("Case-U8")
        self.assertIn("CreateFileW", u8)
        self.assertIn("0x02200000", u8)
        self.assertIn("CreateFileW(path, 0x81, 3,", u8)

    def test_u9_junctions_to_the_product_folder_itself_must_be_removed_as_links(self):
        u9 = body("Case-U9")
        self.assertIn("Cmd 'mklink' '/J' \"$prod\\a-loop\" $prod", u9)
        self.assertIn("Cmd 'mklink' '/J' \"$prod\\sub\\up\" $prod", u9)
        self.assertIn("-eq '0'", u9)

    def test_each_run_line_carries_the_fields_of_the_brief(self):
        run = body("Measure-Run([string]$name, [string]$exe, [string]$argText)")
        for field in ("rc=", "sec=", "outside=", "key=", "plugin_dirs_before_after=", "product folder before", "product folder after"):
            self.assertIn(field, run)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh absent")
    def test_driver_parses(self):
        cmd = ('$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile($env:G7_SCRIPT,[ref]$null,[ref]$e);'
               'exit $e.Count')
        r = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                           env={**os.environ, "G7_SCRIPT": str(GUEST / "uninstall-smoke.ps1")})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


REMOVE_SCENARIO = r"""
$root = Join-Path $base 'g7b'
$prod = Join-Path $base 'prod'
$log = Join-Path $base 'x.log'
$sep = [IO.Path]::DirectorySeparatorChar
$script:cmdCalls = @()
function Cmd { $script:cmdCalls += ,@($args); '' }
$evil = $prod + '-evil'
$outside = Join-Path $base 'x'
[void](New-Item -ItemType Directory -Force -Path (Join-Path $prod 'sub'), (Join-Path $root 'in'), $evil, $outside)
[IO.File]::WriteAllText((Join-Path $prod 'sub/f.txt'), 'f')
[IO.File]::WriteAllText((Join-Path $evil 'keep.txt'), 'k')
[IO.File]::WriteAllText((Join-Path $outside 'keep.txt'), 'k')
$bad = @(($root + $sep + '..' + $sep + 'x'), ($prod + $sep + '..' + $sep + 'x'), ($evil + $sep + 'keep.txt'), $evil, $root, (Split-Path $prod), '\\server\share\x', $sep, '', '   ')
foreach ($b in $bad) {
    try { Remove-Entry $b; "NOT-REFUSED [$b]" } catch { if ($_.Exception.Message -like 'refusing to remove outside the fixture*') { 'refused' } else { "OTHER [$b] $($_.Exception.Message)" } }
}
"kept: evil=$([IO.File]::Exists((Join-Path $evil 'keep.txt'))) outside=$([IO.File]::Exists((Join-Path $outside 'keep.txt')))"
Remove-Entry (Join-Path $root 'in')
"fixture folder removed: $(-not (Test-Path -LiteralPath (Join-Path $root 'in')))"
$lnk = Join-Path $prod 'lnk'
[void](New-Item -ItemType SymbolicLink -Path $lnk -Target $outside)
[void](New-Item -ItemType SymbolicLink -Path (Join-Path $prod 'flnk') -Target (Join-Path $outside 'keep.txt'))
Remove-Entry $prod
"product folder removed: $(-not (Test-Path -LiteralPath $prod)) target kept: $([IO.File]::Exists((Join-Path $outside 'keep.txt'))) sibling kept: $([IO.File]::Exists((Join-Path $evil 'keep.txt')))"
$verbs = @($script:cmdCalls | ForEach-Object { $_[0] } | Sort-Object -Unique)
$slash = @($script:cmdCalls | Where-Object { @($_ | Where-Object { [string]$_ -ieq '/s' }).Count -gt 0 })
"cmd verbs=$($verbs -join ',') slash_s=$($slash.Count)"
"""

GATE_SCENARIO = r"""
$root = Join-Path $base 'g7b'
$prod = Join-Path $base 'prod'
$outs = Join-Path $root 'outside'
$log = Join-Path $base 'x.log'
$noService = '[SC] EnumQueryServicesStatus:OpenService FAILED 1060:' + "`r`n`r`n" + 'The specified service does not exist as an installed service.'
$script:svc = $noService
function Cmd { $script:svc }
$script:keyPresent = $false; $script:keyDisplay = $null; $script:keyRemoved = $false
function Test-Key { $script:keyPresent }
function Get-KeyName { $script:keyDisplay }
function Remove-Key { $script:keyRemoved = $true; $script:keyPresent = $false }
function Clean {
    foreach ($d in @($prod, $root)) { if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force } }
    Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
    $script:keyPresent = $false; $script:keyDisplay = $null; $script:keyRemoved = $false; $script:gateOk = $false; $script:svc = $noService
}
function Refused-Lines { if (Test-Path -LiteralPath $log) { @(Get-Content -LiteralPath $log | Where-Object { $_ -like 'REFUSED:*' }) } else { @() } }
function Try-Reset { try { Reset-All; 'ran' } catch { 'threw' } }
function Mark([string]$text) { [void](New-Item -ItemType Directory -Force -Path $prod); [IO.File]::WriteAllText((Join-Path $prod $markerName), $text) }

Clean
[void](New-Item -ItemType Directory -Force -Path $prod); [IO.File]::WriteAllText((Join-Path $prod 'real.txt'), 'real')
Test-Gate
$r = @(Refused-Lines)
"1 foreign-folder gate=$script:gateOk refused=$($r.Count) names_path=$($r[0].Contains($prod)) reset=$(Try-Reset) kept=$([IO.File]::Exists((Join-Path $prod 'real.txt')))"

Clean
Mark $markerText; [IO.File]::WriteAllText((Join-Path $prod 'ours.txt'), 'ours')
Test-Gate
"2 marked-folder gate=$script:gateOk refused=$(@(Refused-Lines).Count) reset=$(Try-Reset) folder_gone=$(-not (Test-Path -LiteralPath $prod)) key_removed=$script:keyRemoved"

Clean
$script:keyPresent = $true; $script:keyDisplay = 'Some Other Product'
Test-Gate
$r = @(Refused-Lines)
"3 foreign-key gate=$script:gateOk refused=$($r.Count) names_key=$($r[0].Contains($keyPath)) shows_content=$($r[0].Contains('Some Other Product')) reset=$(Try-Reset) key_removed=$script:keyRemoved"

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
"8 foreign-service gate=$script:gateOk refused=$($r.Count) names_service=$($r[0].Contains('the service EcosystemRunner exists')) shows_state=$($r[0].Contains('RUNNING')) reset=$(Try-Reset) folder_kept=$(Test-Path -LiteralPath $prod)"

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
[IO.File]::WriteAllText($log, "VERDICT U1: PASS rc=0`nVERDICT U2: FAIL rc=1`nVERDICT U8: UNPROVEN x`nREFUSED: y`nCASE a: rc=0`n")
Write-Summary
"last=$(@(Get-Content -LiteralPath $log)[-1])"

Clean
[IO.File]::WriteAllText($log, "VERDICT U1: PASS rc=0`nCASE U2: SCRIPT-ERROR boom at line 4`nCASE U4-26: SCRIPT-ERROR again at line 9`nFATAL: x`nCLEANUP: y`nDIALOG-ERROR U2: z`nCASE U3: rc=0 note SCRIPT-ERROR in the middle`n")
Write-Summary

Clean
$nine = @(1..9 | ForEach-Object { "VERDICT U${_}: PASS rc=0" })
[IO.File]::WriteAllText($log, (($nine + 'CASE U10: SCRIPT-ERROR died at line 7') -join "`n") + "`n")
Write-Summary

Clean
$ten = @(1..10 | ForEach-Object { "VERDICT U${_}: PASS rc=0" })
[IO.File]::WriteAllText($log, ($ten -join "`n") + "`n")
Write-Summary
"""


@requires_pwsh
class DriverFunctionsRunForReal(unittest.TestCase):
    def test_remove_entry_refuses_every_path_outside_and_removes_the_product_folder_without_its_link_targets(self):
        lines = run_functions(GUEST / "uninstall-smoke.ps1", ("Remove-Entry", "Get-Attr", "Exists", "Log"), REMOVE_SCENARIO)
        self.assertEqual(lines, ["refused"] * 10 + ["kept: evil=True outside=True", "fixture folder removed: True",
                                                    "product folder removed: True target kept: True sibling kept: True",
                                                    "cmd verbs=del,rmdir slash_s=0"], lines)

    def test_the_gate_refuses_what_it_did_not_create_and_nothing_is_deleted(self):
        funcs = ("Test-Gate", "Get-Foreign", "Reset-All", "Remove-Entry", "Get-Attr", "Exists", "Read-Ascii", "Write-Ascii", "Mkdirs", "Log",
                 "Write-Summary")
        lines = run_functions(GUEST / "uninstall-smoke.ps1", funcs, GATE_SCENARIO, ("markerName", "markerText", "keyName", "keyPath", "gateOk"))
        self.assertEqual(lines, [
            "1 foreign-folder gate=False refused=1 names_path=True reset=threw kept=True",
            "2 marked-folder gate=True refused=0 reset=ran folder_gone=True key_removed=True",
            "3 foreign-key gate=False refused=1 names_key=True shows_content=False reset=threw key_removed=False",
            "4 own-key gate=True refused=0",
            "5 clean gate=True refused=0",
            "6 wrong-marker gate=False refused=1",
            "7 own-folder-foreign-key gate=False refused=1",
            "8 foreign-service gate=False refused=1 names_service=True shows_state=False reset=threw folder_kept=True",
            "9 unreadable-service gate=False refused=1 says_not_queried=True",
            "10 empty-answer gate=False refused=1",
            "SUMMARY pass=1 fail=1 unproven=1 refused=1 error=0",
            "last=SUMMARY pass=1 fail=1 unproven=1 refused=1 error=0",
            "SUMMARY pass=1 fail=0 unproven=0 refused=0 error=5",
            "SUMMARY pass=9 fail=0 unproven=0 refused=0 error=1",
            "SUMMARY pass=10 fail=0 unproven=0 refused=0 error=0"], lines)


class OwnershipGateIsWrittenDownToo(unittest.TestCase):
    def test_remove_entry_acts_on_the_absolute_form_and_allows_only_the_product_folder_and_the_fixture(self):
        remover = body("Remove-Entry")
        for text in ("[IO.Path]::GetFullPath($p).TrimEnd($sep)", "($full -ceq $pr)", "$full.StartsWith($pr + $sep, [StringComparison]::Ordinal)",
                     'if (-not $inside) { throw "refusing to remove outside the fixture: $p" }'):
            self.assertIn(text, remover)
        self.assertLess(remover.index("-not $inside"), remover.index("$p = $full"))
        self.assertLess(remover.index("$p = $full"), remover.index("$a = Get-Attr $p"))
        self.assertIn("[void](Cmd 'rmdir' $p)", remover)
        self.assertNotRegex(DRIVER, r"""(?i)['"]/s['"]""")
        self.assertNotRegex(DRIVER, r"(?i)[.:]Delete\([^)]*\$true")

    def test_nothing_is_deleted_before_the_gate_has_passed(self):
        self.assertTrue(body("Reset-All").split("{", 1)[1].lstrip().startswith("if (-not $script:gateOk) { throw"))
        self.assertLess(DRIVER.index("$script:gateOk = $false"), DRIVER.index("function Log"))
        main = DRIVER.split("$summary = ''", 1)[1]
        self.assertLess(main.index("Test-Gate"), main.index("Try-Case 'U1'"))
        self.assertIn("if ($script:gateOk) { try { Reset-All }", main)
        self.assertLess(main.index("Write-Summary"), main.index("Copy-Item -LiteralPath $log"))
        self.assertEqual(DRIVER.rstrip().splitlines()[-1], "exit 0")

    def test_the_refusal_is_one_line_that_names_the_path_and_the_key(self):
        self.assertIn("Log ('REFUSED: ' + ($foreign -join '; ')", body("Test-Gate"))
        foreign = body("Get-Foreign")
        self.assertIn("-cne $markerText", foreign)
        self.assertIn("-cne $keyName", foreign)
        self.assertIn("the product folder $prod exists and holds no g7b marker", foreign)
        self.assertIn("the uninstall key HKLM\\$keyPath is not the g7b one", foreign)
        self.assertIn("$k.SetValue('DisplayName', $keyName)", DRIVER)

    def test_every_case_that_builds_a_product_folder_writes_the_marker_and_the_absent_folder_case_does_not(self):
        for name in ("Case-U1", "Case-U3", "Case-U5", "Case-U8", "Case-U9", "Case-U4([int]$n)"):
            self.assertIn("Mark-Prod", body(name), name)
        self.assertIn('Write-Ascii "$p2\\$markerName" $markerText', body("Case-U2([string]$flag, [string]$label)"))
        self.assertNotIn("Mark-Prod", body("Case-U7"))

    def test_the_summary_counts_pass_fail_unproven_refused_and_errors(self):
        self.assertIn('"SUMMARY pass=$($n.PASS) fail=$($n.FAIL) unproven=$($n.UNPROVEN) refused=$refused error=$errored"', body("Write-Summary"))
        self.assertIn("-like 'REFUSED:*'", body("Write-Summary"))
        for text in ("'^CASE \\S+: SCRIPT-ERROR '", "-like 'FATAL:*'", "-like 'CLEANUP:*'", "-like 'DIALOG-ERROR*'"):
            self.assertIn(text, body("Write-Summary"))

    def test_the_u5_verdict_needs_exit_40_the_kept_entry_the_locked_file_the_other_entries_and_the_uninstaller(self):
        u5 = body("Case-U5")
        self.assertIn("Verdict 'U5' (($r.Rc -eq '40') -and $r.KeyKept -and (Exists \"$prod\\locked.txt\") -and (@($others).Count -eq 0) "
                      "-and (Exists \"$prod\\uninstall.exe\")) \"rc=$($r.Rc) key_kept=$(Yn $r.KeyKept)\"", u5)
        self.assertIn("rerun_after_release", u5)

    def test_the_service_is_part_of_the_ownership_gate(self):
        foreign = body("Get-Foreign")
        self.assertIn("$svc = Cmd 'sc' 'query' 'EcosystemRunner'", foreign)
        self.assertIn("if ($svc -match 'SERVICE_NAME') { $why += 'the service EcosystemRunner exists' }", foreign)
        self.assertIn("elseif ($svc -notmatch '1060') { $why += 'the service EcosystemRunner could not be queried' }", foreign)
        self.assertIn("service_query=", DRIVER)

    def test_u8_ends_with_40_and_elevation_is_really_asked(self):
        self.assertIn("Verdict 'U8' (($r.Rc -eq '40')", body("Case-U8"))
        self.assertIn("IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)", body("Test-Elevated"))
        self.assertGreaterEqual(DRIVER.count("elevated=$(Test-Elevated)"), 2)


if __name__ == "__main__":
    unittest.main()
