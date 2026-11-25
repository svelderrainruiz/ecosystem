"""SL-4 tests: elevation moment and footprint (INST-REQ-027..032, 078, 079, 089)."""
import contextlib
import io
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from installer import footprint as fpm

ROOT = Path(__file__).resolve().parent.parent
NSIS = ROOT / "installer" / "nsis"
ELEVATE = (NSIS / "elevate.nsh").read_text()
FP = fpm.load_footprint()
ALLOW = fpm.load_allowlist()


def function_body(text, name):
    m = re.search(rf"^Function {re.escape(name)}\b(.*?)^FunctionEnd", text, re.S | re.M)
    assert m, name
    return m.group(1)


def code_lines(text):
    return [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith(";")]


def check(**sources):
    return fpm.check_source({k.replace("_", "."): v for k, v in sources.items()}, FP, ALLOW)


class TestElevationMoment(unittest.TestCase):
    def test_everything_before_the_screen_is_unelevated(self):
        """INST-REQ-027: the unelevated files hold no admin action; the level line stays `user`."""
        main = (NSIS / "main.nsi").read_text()
        self.assertRegex(main, r"(?m)^RequestExecutionLevel user$")
        self.assertIn('!include "elevate.nsh"', main)
        for name in fpm.UNELEVATED_FILES:
            text = (NSIS / name).read_text()
            for marker in FP["elevated_markers"]:
                self.assertNotIn(marker.lower(), "\n".join(code_lines(text)).lower(), f"{name}: {marker}")
        self.assertEqual(fpm.check_source(fpm.collect_sources()), [])

    def test_no_rights_raise_without_the_list_screen(self):
        """INST-REQ-028, 029: the one raise sits in Elevate_Raise, reached only from the screen's leave function."""
        code = "\n".join(code_lines(ELEVATE))
        self.assertEqual(len(re.findall(r"(?i)\brunas\b", code)), 1)
        self.assertIn("runas", function_body(ELEVATE, "Elevate_Raise"))
        self.assertEqual(len(re.findall(r"Call Elevate_Raise", code)), 1)
        self.assertIn("Call Elevate_Raise", function_body(ELEVATE, "Page_elevation_Leave"))
        for name in fpm.UNELEVATED_FILES:
            self.assertNotIn("Elevate_Raise", (NSIS / name).read_text())

    def test_pages_skip_themselves_when_already_admin(self):
        """INST-REQ-032: an administrator never sees the no-administrator page, nor is prompted again."""
        for name in ("Page_noadmin", "Page_elevation"):
            body = function_body(ELEVATE, name)
            self.assertRegex(body, r"\$elev_isadmin == 1\s+Abort")

    def test_screen_lists_what_will_change(self):
        """INST-REQ-028: the screen names the service, account, folder, uninstall entry and rights."""
        body = function_body(ELEVATE, "Page_elevation")
        self.assertIn(FP["service"]["name"], body)
        self.assertIn(FP["service"]["account"], body)
        self.assertIn("Folder: $MachineFolder", body)
        init = function_body((NSIS / "log.nsh").read_text(), "Log_InitPaths")
        self.assertIn(f'StrCpy $MachineFolder "{FP["folder"]["path"]}"', init)
        self.assertRegex(body, r"(?i)uninstall entry")
        self.assertRegex(body, r"(?i)\bRights\b")

    def test_no_admin_offers_only_local_only_mode(self):
        """INST-REQ-032, 079: one radio button, the per-user mode, and the plain administrator statement."""
        body = function_body(ELEVATE, "Page_noadmin")
        self.assertEqual(body.count("CreateRadioButton"), 1)
        self.assertIn("Local only (no forge)", body)
        self.assertIn("The runner needs administrator rights", body)

    def test_silent_mode_not_elevated_has_own_exit_code(self):
        """INST-REQ-078: silent and not admin: SetErrorLevel with a code no other class uses, then Quit."""
        code = FP["exit_codes"]["not-elevated"]
        schema_codes = json.loads((ROOT / "installer" / "schema.json").read_text())["exit_codes"].values()
        trust_codes = {int(c) for c in re.findall(r"SetErrorLevel (\d+)", (NSIS / "trust.nsh").read_text())}
        self.assertNotIn(code, list(schema_codes) + list(trust_codes))
        body = function_body(ELEVATE, "Elevate_SilentGate")
        self.assertIn("${Silent}", body)
        self.assertIn("$elev_isadmin == 0", body)
        self.assertRegex(body, rf"SetErrorLevel {code}\s+Quit")
        self.assertNotIn("Elevate_Raise", body)


class TestWiring(unittest.TestCase):
    def test_elevate_pages_and_gate_are_wired_in_order(self):
        """INST-REQ-028, 029, 078: main.nsi calls the gate after the trust check and shows the pages after secrets."""
        main = "\n".join(code_lines((NSIS / "main.nsi").read_text()))
        order = ["Page custom Page_secrets", "Page custom Page_noadmin", "Page custom Page_elevation Page_elevation_Leave",
                 "Page instfiles"]
        pos = [main.index(o) for o in order]
        self.assertEqual(pos, sorted(pos))
        init = function_body(main + "\n", ".onInit") if False else main[main.index("Function .onInit"):]
        self.assertLess(init.index("Call TrustCheck"), init.index("Call Elevate_SilentGate"))
        self.assertEqual(main.count("Call Elevate_SilentGate"), 1)

    @unittest.skipUnless(shutil.which("makensis"), "makensis absent")
    def test_main_nsi_compiles_with_warnings_as_errors(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(NSIS, Path(d) / "nsis")
            r = subprocess.run(["makensis", "-WX", "-V1", str(Path(d) / "nsis" / "main.nsi")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestFootprint(unittest.TestCase):
    def test_footprint_is_one_folder_one_service_one_entry(self):
        """INST-REQ-030, 089: the file names one of each, under program data, with a virtual service account."""
        self.assertEqual(sorted(k for k in FP if k in ("folder", "service", "uninstall_entry")),
                         ["folder", "service", "uninstall_entry"])
        self.assertTrue(FP["folder"]["path"].startswith("$APPDATA\\"))
        self.assertEqual(FP["service"]["account"], "NT SERVICE\\" + FP["service"]["name"])
        self.assertTrue(FP["uninstall_entry"]["key"].startswith("HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"))
        self.assertEqual(len(FP["per_user_exceptions"]), 2)

    def test_writes_inside_the_footprint_pass(self):
        ok = (
            'Function Install\n'
            '  CreateDirectory "$APPDATA\\EcosystemRunner\\logs"\n'
            '  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\EcosystemRunner" "DisplayName" "x"\n'
            'FunctionEnd\n')
        self.assertEqual(check(other_nsh=ok), [])

    def test_writes_outside_the_footprint_fail(self):
        """INST-REQ-030: any other folder, registry key or run key is refused."""
        for line in ('CreateDirectory "$PROGRAMFILES\\Other"',
                     'WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Run" "x" "y"',
                     'WriteRegStr HKCU "Software\\Foo" "x" "y"',
                     'FileOpen $0 "$TEMP\\x.txt" w',
                     'FileOpen $0 "$EXEDIR\\x.txt" w',
                     'SetOutPath "$APPDATA\\EcosystemRunnerOther"',
                     'CopyFiles "$EXEDIR\\a" "$DESKTOP\\a"',
                     'Delete "$APPDATA\\Other\\a"'):
            self.assertTrue(check(other_nsh=f"Function F\n  {line}\nFunctionEnd\n"), line)

    def test_services_and_commands_outside_the_footprint_fail(self):
        for line in ('nsExec::Exec "sc.exe create Other"', 'ExecWait "cmd /c whoami"', 'Exec "x.exe"'):
            self.assertTrue(check(other_nsh=f"Function F\n  {line}\nFunctionEnd\n"), line)

    def test_admin_markers_fail_in_unelevated_files(self):
        """INST-REQ-027: HKLM, all-users context or runas in main/trust/screens is refused."""
        for name in ("trust_nsh", "screens_nsh", "main_nsi"):
            for line in ('SetShellVarContext all', 'WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\EcosystemRunner" a b',
                         'ExecShell "runas" "$EXEPATH"'):
                self.assertTrue(check(**{name: f"Function F\n  {line}\nFunctionEnd\n"}), (name, line))

    def test_runas_outside_elevate_raise_fails(self):
        raise_line = 'ExecShell "runas" "$EXEPATH" "$carry_args"'
        self.assertIn(raise_line, ELEVATE)
        moved = ELEVATE.replace(raise_line, "Nop")
        moved = moved.replace("Function Page_noadmin\n", 'Function Page_noadmin\n  ExecShell "runas" "$EXEPATH"\n')
        self.assertTrue(check(elevate_nsh=moved))
        self.assertEqual(check(elevate_nsh=ELEVATE), [])

    def test_reads_only_allow_listed_paths(self):
        """INST-REQ-031: the allow-list is a file in the source; a read outside it is refused."""
        self.assertTrue((ROOT / "installer" / "allowlist-read.txt").is_file())
        ok = 'Function F\n  IfFileExists "$LOCALAPPDATA\\EcosystemInstaller\\signer.sha256" a b\nFunctionEnd\n'
        self.assertEqual(check(other_nsh=ok), [])
        for line in ('IfFileExists "$PROFILE\\.ssh\\id_x" a b', 'FileOpen $0 "$DOCUMENTS\\x" r',
                     'ReadRegStr $0 HKLM "Software\\Other" "x"', 'ReadEnvStr $0 "USERPASSWORD"',
                     'FindFirst $0 $1 "$PROFILE\\*.*"'):
            self.assertTrue(check(other_nsh=f"Function F\n  {line}\nFunctionEnd\n"), line)

    def test_allowlist_prefix_is_on_a_path_boundary(self):
        self.assertFalse(fpm.read_allowed("$INSTDIRX\\a", ["$INSTDIR"]))
        self.assertTrue(fpm.read_allowed("$instdir\\a", ["$INSTDIR"]))

    def test_comments_do_not_count_but_code_does(self):
        self.assertEqual(check(other_nsh='; WriteRegStr HKLM "x" "y" "z"\n'), [])
        self.assertTrue(check(other_nsh='WriteRegStr HKLM "x" "y" "z"\n'))

    def test_powershell_scan(self):
        """INST-REQ-089: no write cmdlet or service command in PowerShell; literal reads need the allow-list."""
        self.assertEqual(check(hostcheck_ps1=(ROOT / "installer" / "hostcheck.ps1").read_text()), [])
        for line in ("Set-Content -Path x -Value y", "New-Service -Name a", "sc.exe create a", "reg add HKLM\\x",
                     "Remove-Item $x", "[IO.File]::WriteAllText($a,$b)"):
            self.assertTrue(check(x_ps1=line), line)
        self.assertTrue(check(x_ps1="Get-Content 'C:\\Users\\other\\secret.txt'"))
        self.assertEqual(check(x_ps1="Test-Path 'HKLM\\Software\\Microsoft\\Windows NT\\CurrentVersion\\EditionID'"), [])
        self.assertEqual(check(x_ps1="# Set-Content x"), [])

    def test_nsis_flags_are_skipped_before_the_target(self):
        """Review 2: /SILENT and /REBOOTOK do not hide the destination."""
        for line in ('CopyFiles /SILENT "$EXEDIR\\a" "$DESKTOP\\a"', 'Rename /REBOOTOK "$EXEDIR\\a" "$DESKTOP\\a"',
                     'File /oname=$DESKTOP\\a "$EXEDIR\\a"', 'Delete /REBOOTOK "$DESKTOP\\a"'):
            self.assertTrue(check(other_nsh=f"Function F\n  {line}\nFunctionEnd\n"), line)
        self.assertEqual(check(other_nsh='Function F\n  Delete /REBOOTOK "$APPDATA\\EcosystemRunner\\a"\nFunctionEnd\n'), [])
        ok = 'Function F\n  CopyFiles /SILENT "$EXEDIR\\a" "$APPDATA\\EcosystemRunner\\a"\nFunctionEnd\n'
        self.assertEqual(check(other_nsh=ok), [])

    def test_more_nsis_writers_and_plugins_fail_closed(self):
        for line in ('WriteINIStr "$DESKTOP\\a.ini" s k v', 'DeleteINISec "$DESKTOP\\a.ini" s',
                     'System::Call "kernel32::DeleteFile(t 1)"', 'ExecDos::exec "cmd" "" ""',
                     '!system "x"', 'inetc::get "http://x" "y"'):
            self.assertTrue(check(other_nsh=f"Function F\n  {line}\nFunctionEnd\n"), line)

    def test_marker_match_ignores_whitespace_tricks(self):
        """Review 3: two spaces or a tab do not hide an admin marker."""
        for line in ("SetShellVarContext  all", "SetShellVarContext\tall", "  SETSHELLVARCONTEXT   ALL"):
            self.assertTrue(check(main_nsi=f"Function F\n{line}\nFunctionEnd\n"), line)

    def test_powershell_bypasses(self):
        """Review 4, 5: redirection, more cmdlets, aliases, backticks, non-literal reads."""
        for line in ("'x' > out.txt", "'x' >> out.txt", "$a | Tee-Object f", "$a | Export-Csv f", "Set-Acl a b",
                     "Expand-Archive a b", "Invoke-WebRequest u -OutFile f", "ni f", "del f", "rm f", "mkdir f", "cp a b",
                     "mv a b", "x; rm f", "Set`-Content f", "Remove`Item f", "Get-Content $other", "Test-Path $x",
                     "Get-ChildItem", "Get-Content ($a + 'b')"):
            self.assertTrue(check(x_ps1=line), line)
        self.assertEqual(check(x_ps1="Get-Content -LiteralPath $EditionFile -TotalCount 1"), [])
        self.assertEqual(check(x_ps1="cmd 2>&1"), [])
        self.assertEqual(check(x_ps1="$a = 'ni f > g'"), [])

    def test_trust_store_variable_is_pinned(self):
        """Review nit: $TrustStoreFile may only be set under the per-user installer folder."""
        self.assertEqual(check(other_nsh='StrCpy $TrustStoreFile "$LOCALAPPDATA\\EcosystemInstaller\\s.sha256"\n'), [])
        self.assertTrue(check(other_nsh='StrCpy $TrustStoreFile "$PROFILE\\x"\n'))
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "f.json"
            bad.write_text(json.dumps({**FP, "per_user_exceptions": [{"path": "$PROFILE\\x", "reason": "r"}]}))
            with self.assertRaises(fpm.FootprintError):
                fpm.load_footprint(bad)

    def test_damaged_files_are_typed_errors(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "f.json"
            bad.write_text("{")
            with self.assertRaises(fpm.FootprintError):
                fpm.load_footprint(bad)
            bad.write_text(json.dumps({**FP, "exit_codes": {}}))
            with self.assertRaises(fpm.FootprintError):
                fpm.load_footprint(bad)
            bad.write_text("# only a comment\n")
            with self.assertRaises(fpm.FootprintError):
                fpm.load_allowlist(bad)
            with self.assertRaises(fpm.FootprintError):
                fpm.load_allowlist(Path(d) / "missing")

    def test_cli(self):
        self.assertEqual(fpm.main(["check"]), 0)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(fpm.main([]), 2)
        self.assertIn("usage: python -m installer.footprint check", err.getvalue())

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh absent")
    def test_pwsh_parses_hostcheck(self):
        """Parse-only check of the PowerShell source."""
        path = ROOT / "installer" / "hostcheck.ps1"
        cmd = ("$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("
               f"'{path}',[ref]$null,[ref]$e);if($e.Count){{exit 1}}")
        self.assertEqual(subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
