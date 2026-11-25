"""Link-semantics probes (ecosystem-control#64, GUEST7A): probe-p6.nsi measures the instructions of installer/nsis/tree.nsh on directory
junctions, directory symbolic links and file symbolic links, and link-probes.ps1 builds the fixture and drives it inside a disposable clone.
Static checks only; the guest run is the proof."""
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from installer.guest import pack
from tests.guest_pwsh import requires_pwsh, run_functions

ROOT = Path(__file__).resolve().parent.parent
GUEST = ROOT / "installer" / "guest"
P6 = (GUEST / "probe-p6.nsi").read_text(encoding="ascii")
DRIVER = (GUEST / "link-probes.ps1").read_text(encoding="ascii")


class LinkProbePacked(unittest.TestCase):
    def test_p6_is_packed_beside_the_five_gate_probes(self):
        self.assertEqual(pack.LINK_PROBES, ("p6",))
        self.assertEqual(pack.PROBES, ("p1", "p2", "p3", "p4", "p5"))
        self.assertTrue((GUEST / "probe-p6.nsi").is_file())
        self.assertIn("probe-p6.exe.b64", DRIVER)

    def test_the_probe_and_its_driver_share_one_fixture_root(self):
        root = re.search(r"^\$root = '([^']+)'$", DRIVER, re.M).group(1)
        self.assertEqual(root, "C:\\X\\g7a")
        self.assertIn("$nsout = Join-Path $root 'nsis-out.txt'", DRIVER)
        prefix = root + "\\"
        self.assertEqual(P6.count('FileOpen $9 "%snsis-out.txt" w' % prefix), 1)
        self.assertIn('${If} $3 == "%s"' % prefix, P6)
        self.assertIn("StrCpy $3 $2 %d\n" % len(prefix), P6)
        self.assertIn("${AndIf} $5 > %d\n" % len(prefix), P6)
        self.assertNotRegex(P6, r"(?i)C:\\Temp")

    def test_p6_runs_elevated_silent_unicode_and_names_no_url(self):
        for text in ("Unicode true", "RequestExecutionLevel admin", "SilentInstall silent", '!include "FileFunc.nsh"'):
            self.assertIn(text, P6)
        self.assertNotRegex(P6, r"https?://")
        P6.encode("ascii")


class ProbeUsesTheUninstallersInstructions(unittest.TestCase):
    def test_reads_use_the_file_func_macro_ifFileExists_raw_win32_and_findfirst(self):
        self.assertIn("!insertmacro GetFileAttributes", P6)
        for attr in ("REPARSE_POINT", "DIRECTORY"):
            self.assertRegex(P6, r"!insertmacro Attr \w+ " + attr)
        self.assertIn('${FileExists} "${PATH}"', P6)
        self.assertIn('"$R1\\*.*"', P6)
        self.assertIn("kernel32::GetFileAttributesW(w r4)i .r0 ?e", P6)
        self.assertIn('StrCpy $4 "$R1\\"', P6)
        self.assertIn('FindFirst $6 $7 "$R2\\*.*"', P6)

    def test_removals_use_nsis_instructions_and_raw_win32_with_and_without_the_trailing_backslash(self):
        self.assertIn('RMDir "$R1"', P6)
        self.assertIn('Delete "$R1"', P6)
        self.assertIn('RMDir /r "$2"', P6)
        self.assertIn("kernel32::${FUNC}(w r4)i .r0 ?e", P6)
        self.assertIn("!insertmacro Win32Call RemoveDirectoryW", P6)
        self.assertIn("!insertmacro Win32Call DeleteFileW", P6)
        plain = P6.split('"A2c"', 1)[1].split('"A2d"', 1)[0]
        slash = P6.split('"A2d"', 1)[1].split('"A2e"', 1)[0]
        self.assertIn('StrCpy $4 "$R1"\n', plain)
        self.assertIn('StrCpy $4 "$R1\\"', slash)

    def test_every_measurement_clears_the_error_flag_first_and_writes_one_result_line(self):
        for op in ("A2a", "A2b"):
            body = P6.split('"%s"' % op, 1)[1].split("${ElseIf}", 1)[0]
            self.assertTrue(body.lstrip().startswith("ClearErrors"), op)
        self.assertRegex(P6.split('"A3r"', 1)[1], r'ClearErrors\s+RMDir /r "\$2"')
        self.assertEqual(P6.count('FileOpen $9 "C:\\X\\g7a\\nsis-out.txt" w'), 1)

    def test_operation_codes_are_three_characters_so_the_path_starts_at_offset_four(self):
        self.assertIn("StrCpy $R0 $R9 3", P6)
        self.assertIn('StrCpy $R1 $R9 "" 4', P6)
        for op in re.findall(r'\$R0 == "(\w+)"', P6):
            self.assertEqual(len(op), 3, op)
            self.assertIn("'%s'" % op, DRIVER)


class DriverStaysInTheFixture(unittest.TestCase):
    def test_driver_is_ascii_and_names_no_secret_or_url(self):
        DRIVER.encode("ascii")
        self.assertNotRegex(DRIVER, r"https?://")
        self.assertNotRegex(DRIVER, r"(?i)password|credential|\.config")

    def test_every_path_it_writes_is_under_the_fixture_or_out(self):
        self.assertIn("$root = 'C:\\X\\g7a'", DRIVER)
        self.assertIn("refusing to remove outside the fixture", DRIVER)
        self.assertIn("StartsWith($root.TrimEnd($sep) + $sep, [StringComparison]::Ordinal)", DRIVER)
        for drive in re.findall(r"[A-Za-z]:\\[^\s'\"]*", DRIVER):
            self.assertTrue(drive.startswith("C:\\X\\g7a"), drive)

    def test_no_recursive_delete_can_follow_a_link(self):
        self.assertNotRegex(DRIVER, r"(?i)-Recurse")
        self.assertNotRegex(DRIVER, r"(?i)\brd\s+/s|rmdir\s+/s|\bdel\s+/s")
        remover = DRIVER.split("function Remove-Entry", 1)[1].split("\n}\n", 1)[0]
        self.assertLess(remover.index("-band 0x400"), remover.index("GetFileSystemEntries"))
        self.assertIn("'rmdir'", remover)
        self.assertIn("'del'", remover)

    def test_the_fixture_has_the_ten_kinds_of_the_brief(self):
        for kind in ("jFull", "jEmpty", "jGone", "sFull", "sEmpty", "sGone", "fLive", "fGone", "rDir", "rFile"):
            self.assertIn("'%s'" % kind, DRIVER)
        for folder in ("outside\\full\\sub", "outside\\empty", "outside\\gone", "outside\\file.txt", "outside\\gone.txt"):
            self.assertIn(folder, DRIVER)
        self.assertIn("mklink", DRIVER)
        self.assertIn("'/J'", DRIVER)
        self.assertIn("'/D'", DRIVER)
        self.assertIn("[IO.Directory]::Delete(\"$outside\\gone\")", DRIVER)
        self.assertIn("[IO.File]::Delete(\"$outside\\gone.txt\")", DRIVER)

    def test_it_runs_the_reads_the_five_removals_and_the_recursive_removal_each_on_a_rebuilt_fixture(self):
        for code in ("A1r", "A2a", "A2b", "A2c", "A2d", "A2e", "A3r"):
            self.assertIn("'%s'" % code, DRIVER)
        a3 = next(ln for ln in DRIVER.splitlines() if "'A3r'" in ln and "foreach" in ln)
        for kind in ("jEmpty", "jGone", "sEmpty", "sGone"):
            self.assertIn("'%s'" % kind, a3)
        self.assertGreaterEqual(DRIVER.count("Reset-Fixture"), 3)
        loop = DRIVER.split("# A2 removals and A3", 1)[1]
        self.assertLess(loop.index("Reset-Fixture"), loop.index("Run-P6"))
        self.assertIn("p6.log", DRIVER)
        self.assertIn("'p6.txt'", DRIVER)

    def test_each_case_line_carries_the_fields_of_the_brief(self):
        case = DRIVER.split('$line = "CASE ', 1)[1].split("\n", 1)[0]
        for field in ("ret=", "err=", "lasterr=", "linkGone=", "targetIntact="):
            self.assertIn(field, case)
        self.assertIn("cmd.exe /c dir /a", DRIVER)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh absent")
    def test_driver_parses(self):
        cmd = ('$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile($env:G7_SCRIPT,[ref]$null,[ref]$e);'
               'exit $e.Count')
        r = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                           env={**os.environ, "G7_SCRIPT": str(GUEST / "link-probes.ps1")})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


REMOVE_SCENARIO = r"""
$root = Join-Path $base 'g7a'
$log = Join-Path $base 'x.log'
$sep = [IO.Path]::DirectorySeparatorChar
$script:cmdCalls = @()
function Cmd { $script:cmdCalls += ,@($args); '' }
$evil = $root + '-evil'
$outside = Join-Path $base 'x'
[void](New-Item -ItemType Directory -Force -Path (Join-Path $root 'in/sub'), $evil, $outside)
[IO.File]::WriteAllText((Join-Path $root 'in/sub/f.txt'), 'f')
[IO.File]::WriteAllText((Join-Path $evil 'keep.txt'), 'k')
[IO.File]::WriteAllText((Join-Path $outside 'keep.txt'), 'k')
$bad = @(($root + $sep + '..' + $sep + 'x'), ($root + $sep + 'in' + $sep + '..' + $sep + '..' + $sep + 'x'), ($evil + $sep + 'keep.txt'), $evil, $root, '\\server\share\x', $sep, '', '   ')
foreach ($b in $bad) {
    try { Remove-Entry $b; "NOT-REFUSED [$b]" } catch { if ($_.Exception.Message -like 'refusing to remove outside the fixture*') { 'refused' } else { "OTHER [$b] $($_.Exception.Message)" } }
}
"kept: evil=$([IO.File]::Exists((Join-Path $evil 'keep.txt'))) outside=$([IO.File]::Exists((Join-Path $outside 'keep.txt')))"
Remove-Entry (Join-Path $root 'in')
"inside removed: $(-not (Test-Path -LiteralPath (Join-Path $root 'in')))"
$lnk = Join-Path $root 'lnk'
[void](New-Item -ItemType SymbolicLink -Path $lnk -Target $outside)
Remove-Entry $lnk
"link removed: $(-not (Test-Path -LiteralPath $lnk)) target kept: $([IO.File]::Exists((Join-Path $outside 'keep.txt')))"
$flnk = Join-Path $root 'flnk'
[void](New-Item -ItemType SymbolicLink -Path $flnk -Target (Join-Path $outside 'keep.txt'))
Remove-Entry $flnk
"file link removed: $(-not (Test-Path -LiteralPath $flnk)) target kept: $([IO.File]::Exists((Join-Path $outside 'keep.txt')))"
$verbs = @($script:cmdCalls | ForEach-Object { $_[0] } | Sort-Object -Unique)
$slash = @($script:cmdCalls | Where-Object { @($_ | Where-Object { [string]$_ -ieq '/s' }).Count -gt 0 })
"cmd verbs=$($verbs -join ',') slash_s=$($slash.Count)"
"""

GUARD_SCENARIO = r"""
$root = Join-Path $base 'g7a'
$decoy = Join-Path $base 'g7a-guard'
$log = Join-Path $base 'x.log'
$S = @{ keep = 'KEEP-x' }
$script:p6calls = 0
function Run-P6([string]$op, [string]$path) { $script:p6calls++; [pscustomobject]@{ Line = 'refused=1 ret=- lasterr=-'; Rc = 0 } }
function Reset-Log { [IO.File]::WriteAllText($log, ''); $script:p6calls = 0 }
function Clean-Decoy { [IO.File]::Delete("$decoy\keep.txt"); if (Test-Path -LiteralPath $decoy) { Remove-Item -LiteralPath $decoy -Recurse -Force } }
function Show([string]$tag) {
    $l = @(Get-Content -LiteralPath $log)
    $v = (Test-GuardLines $l).Split(' ')[0]
    $n = @($l | Where-Object { $_ -like 'GUARD *' }).Count
    $k = @($l | Where-Object { $_ -like 'GUARD-SKIPPED:*' }).Count
    "$tag guard_lines=$n skipped=$k p6_calls=$script:p6calls verdict=$v decoy_dir=$([IO.Directory]::Exists($decoy)) decoy_file=$([IO.File]::Exists($decoy))"
}

Reset-Log; Run-Guard; Show '1 absent'

[void](New-Item -ItemType Directory -Force -Path $decoy)
[IO.File]::WriteAllText("$decoy\keep.txt", 'FOREIGN')
Reset-Log; Run-Guard; Show '2 foreign-folder'
$same = ([IO.File]::ReadAllText("$decoy\keep.txt") -ceq 'FOREIGN')
"foreign file intact: $same"
Clean-Decoy

[IO.File]::WriteAllText($decoy, 'A FILE')
Reset-Log; Run-Guard; Show '3 foreign-file'
$same = ([IO.File]::ReadAllText($decoy) -ceq 'A FILE')
"foreign file intact: $same"
Remove-Item -LiteralPath $decoy -Force

function Run-P6([string]$op, [string]$path) { $script:p6calls++; [IO.File]::Delete("$decoy\keep.txt"); [pscustomobject]@{ Line = 'refused=0 ret=1'; Rc = 0 } }
Reset-Log; Run-Guard; Show '4 probe-that-deletes'

$g1 = 'GUARD dotdot A3r p: refused=1 decoy_intact=Y rc=0 raw=[x]'
$g2 = 'GUARD sibling A3r p: refused=1 decoy_intact=Y rc=0 raw=[x]'
function V($lines) { (Test-GuardLines $lines).Split(' ')[0] }
"good=$(V @($g1, $g2)) one=$(V @($g1)) none=$(V @()) three=$(V @($g1, $g2, $g2))"
"refused0=$(V @($g1, ($g2 -replace 'refused=1', 'refused=0'))) intactN=$(V @($g1, ($g2 -replace 'decoy_intact=Y', 'decoy_intact=N')))"
"no-refused=$(V @($g1, ($g2 -replace 'refused=1 ', ''))) no-intact=$(V @($g1, ($g2 -replace 'decoy_intact=Y ', '')))"
"skipped=$(V @('GUARD-SKIPPED: x exists', $g1, $g2)) skipped-alone=$(V @('GUARD-SKIPPED: x exists')) noise=$(V @('CASE a: refused=0', $g1, $g2))"
"""


@requires_pwsh
class RemoveEntryIsReallyGuarded(unittest.TestCase):
    def test_the_real_function_refuses_every_path_outside_the_fixture_and_removes_inside_ones(self):
        lines = run_functions(GUEST / "link-probes.ps1", ("Remove-Entry", "Get-Attr", "Log"), REMOVE_SCENARIO)
        self.assertEqual(lines, ["refused"] * 9 + ["kept: evil=True outside=True", "inside removed: True",
                                                   "link removed: True target kept: True", "file link removed: True target kept: True",
                                                   "cmd verbs=del,rmdir slash_s=0"], lines)

    def test_the_guard_step_uses_only_a_decoy_it_made_and_says_what_it_proved(self):
        funcs = ("Run-Guard", "Test-GuardLines", "Field", "Get-Attr", "Log", "Write-Ascii", "Read-Ascii", "Yn")
        lines = run_functions(GUEST / "link-probes.ps1", funcs, GUARD_SCENARIO)
        self.assertEqual(lines, [
            "1 absent guard_lines=2 skipped=0 p6_calls=2 verdict=PASS decoy_dir=False decoy_file=False",
            "2 foreign-folder guard_lines=0 skipped=1 p6_calls=0 verdict=UNPROVEN decoy_dir=True decoy_file=False",
            "foreign file intact: True",
            "3 foreign-file guard_lines=0 skipped=1 p6_calls=0 verdict=UNPROVEN decoy_dir=False decoy_file=True",
            "foreign file intact: True",
            "4 probe-that-deletes guard_lines=2 skipped=0 p6_calls=2 verdict=FAIL decoy_dir=False decoy_file=False",
            "good=PASS one=FAIL none=FAIL three=FAIL",
            "refused0=FAIL intactN=FAIL",
            "no-refused=FAIL no-intact=FAIL",
            "skipped=UNPROVEN skipped-alone=UNPROVEN noise=PASS"], lines)


class GuardsAreWrittenDownToo(unittest.TestCase):
    def test_remove_entry_acts_on_the_absolute_form_and_only_after_the_guard(self):
        remover = DRIVER.split("function Remove-Entry", 1)[1].split("\n}\n", 1)[0]
        guard = ('if (($null -eq $full) -or -not $full.StartsWith($root.TrimEnd($sep) + $sep, [StringComparison]::Ordinal)) '
                 '{ throw "refusing to remove outside the fixture: $p" }')
        self.assertIn(guard, remover)
        self.assertIn("[IO.Path]::GetFullPath($p).TrimEnd($sep)", remover)
        self.assertLess(remover.index(guard), remover.index("$p = $full"))
        self.assertLess(remover.index("$p = $full"), remover.index("$a = Get-Attr $p"))

    def test_links_go_by_rmdir_and_del_and_nothing_is_ever_removed_recursively(self):
        remover = DRIVER.split("function Remove-Entry", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("[void](Cmd 'rmdir' $p)", remover)
        self.assertIn("[void](Cmd 'del' '/f' '/q' $p)", remover)
        self.assertNotRegex(DRIVER, r"""(?i)['"]/s['"]""")
        self.assertNotRegex(DRIVER, r"(?i)[.:]Delete\([^)]*\$true")

    def test_the_arguments_of_the_probe_keep_the_space_its_parser_counts_on(self):
        self.assertIn('$psi.Arguments = "$op $path"', DRIVER)

    def test_the_record_keys_the_driver_reads_are_the_ones_the_probe_writes(self):
        for key in ("ret", "err", "lasterr", "iffe"):
            self.assertIn("Field $r.Line '%s'" % key, DRIVER)
        win32 = P6.split("!macro Win32Call FUNC", 1)[1].split("!macroend", 1)[0]
        self.assertIn('StrCpy $8 "$8 ret=$0"', win32)
        self.assertIn("!insertmacro Flag err", win32)
        self.assertIn('StrCpy $8 "$8 lasterr=$1"', win32)
        self.assertIn("!insertmacro Exists iffe", P6)
        self.assertNotIn("lasterror", P6 + DRIVER)

    def test_the_recursive_removal_of_the_probe_refuses_anything_outside_the_fixture(self):
        prefix = "C:\\X\\g7a\\"
        self.assertEqual(len(prefix), 9)
        order = [P6.index("kernel32::GetFullPathNameW(w r4, i ${NSIS_MAX_STRLEN}, w .r2, i 0)i .r0"), P6.index("StrCpy $3 $2 9"),
                 P6.index('${If} $3 == "%s"' % prefix), P6.index("${AndIf} $5 > 9"), P6.index('RMDir /r "$2"'), P6.index("refused=1")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(len(re.findall(r"^\s*RMDir /r ", P6, re.M)), 1)
        self.assertNotIn('RMDir /r "$R1"', P6)

    def test_the_recursive_removal_of_the_probe_is_exactly_the_guarded_block_with_no_line_commented_out(self):
        block = P6.split('${ElseIf} $R0 == "A3r"', 1)[1].split('${Else}\n    StrCpy $8 "$8 unknown-op"', 1)[0]
        code = [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith(";")]
        self.assertEqual(code, [
            'StrCpy $4 "$R1"',
            "System::Call 'kernel32::GetFullPathNameW(w r4, i ${NSIS_MAX_STRLEN}, w .r2, i 0)i .r0'",
            "StrLen $5 $2",
            "StrCpy $3 $2 9",
            '${If} $3 == "C:\\X\\g7a\\"',
            "${AndIf} $5 > 9",
            "ClearErrors",
            'RMDir /r "$2"',
            'StrCpy $8 "$8 ret=- lasterr=-"',
            "!insertmacro Flag err",
            "${Else}",
            'StrCpy $8 "$8 ret=- lasterr=- refused=1"',
            "${EndIf}"], code)

    def test_the_guard_verdict_is_logged_and_ends_the_last_output_line(self):
        self.assertIn("Run-Guard\n    Log ('GUARD-VERDICT: ' + (Test-GuardLines @(Get-Content -LiteralPath $log)))", DRIVER)
        self.assertIn("GUARD-SKIPPED: $decoy already exists, so it is not ours", DRIVER)
        self.assertIn("if ($null -ne (Get-Attr $decoy))", DRIVER.split("function Run-Guard", 1)[1].split("\n}\n", 1)[0])
        self.assertIn("if ($made) {", DRIVER.split("function Run-Guard", 1)[1].split("\n}\n", 1)[0])
        out = [ln for ln in DRIVER.splitlines() if ln.startswith('Write-Output "link-probes done:')]
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].endswith("'GUARD-VERDICT: none' })\""), out[0])

    def test_the_guard_step_checks_the_probe_against_a_decoy_next_to_the_fixture(self):
        self.assertIn("$decoy = 'C:\\X\\g7a-guard'", DRIVER)
        self.assertIn("@('dotdot', \"$root\\..\\g7a-guard\")", DRIVER)
        self.assertIn("@('sibling', $decoy)", DRIVER)
        self.assertIn("Run-P6 'A3r' $g[1]", DRIVER)
        self.assertIn("refused=$(Field $r.Line 'refused') decoy_intact=$(Yn $kept)", DRIVER)
        self.assertIn('[IO.File]::Delete("$decoy\\keep.txt"); [IO.Directory]::Delete($decoy)', DRIVER)
        self.assertLess(DRIVER.index('Log "DONE: $n removal measurements"'), DRIVER.index("$decoy = "))

    def test_elevation_is_really_asked_and_the_verdict_is_not_the_exit_code(self):
        self.assertIn("IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)", DRIVER)
        self.assertEqual(DRIVER.rstrip().splitlines()[-1], "exit 0")
        readme = (ROOT / "installer" / "README.md").read_text(encoding="utf-8")
        self.assertIn("The verdict is in those lines, not in the exit code", readme)


if __name__ == "__main__":
    unittest.main()
