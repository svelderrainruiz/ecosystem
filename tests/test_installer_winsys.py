"""SL-10 Windows system adapter: INST-REQ-036, 038, 040, 041, 043, 091, 092, 093, 094. Fake process runner, exact argv, no process, no network."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer import footprint, runners, update, winsys
from installer.winsys import WinSystem, Result
from tests.test_installer_update import Base

FOLDER = "C:\\ProgramData\\EcosystemRunner"
QC = ("SERVICE_NAME: EcosystemRunner\n        START_TYPE         : 2   AUTO_START\n"
      "        BINARY_PATH_NAME   : \"C:\\ProgramData\\EcosystemRunner\\program\\runner.exe\"\n"
      "        SERVICE_START_NAME : NT SERVICE\\EcosystemRunner\n")
RUNNING = "STATE              : 4  RUNNING"


class Fake:
    def __init__(self, results=None, default=0):
        self.calls, self.full, self.results, self.default = [], [], results or {}, default
        self.state = "STOPPED"

    def __call__(self, argv):
        assert isinstance(argv, list)
        self.full.append(argv)
        argv = [argv[0].rsplit("\\", 1)[-1]] + argv[1:]
        self.calls.append(argv)
        key = " ".join(argv[:2])
        if key in ("sc.exe start", "sc.exe stop"):
            self.state = "RUNNING" if key.endswith("start") else "STOPPED"
        if key == "sc.exe query" and key not in self.results:
            return Result(0, "STATE              : %d  %s" % (4 if self.state == "RUNNING" else 1, self.state))
        r = self.results.get(key, self.default)
        if isinstance(r, list):
            r = r.pop(0) if len(r) > 1 else r[0]
        return r if isinstance(r, Result) else Result(r)


def make(fake, **kw):
    sleeps = []
    return WinSystem(FOLDER, run=fake, sleep=sleeps.append, **kw), sleeps


class ServiceTests(unittest.TestCase):
    def test_install_service_exact_argv_091_092(self):
        f = Fake()
        s, _ = make(f)
        s.install_service("EcosystemRunner", "NT SERVICE\\EcosystemRunner", FOLDER)
        self.assertEqual(f.calls, [
            ["sc.exe", "create", "EcosystemRunner", "binPath=", '"C:\\ProgramData\\EcosystemRunner\\program\\runner.exe"',
             "obj=", "NT SERVICE\\EcosystemRunner", "start=", "auto"],
            ["sc.exe", "sidtype", "EcosystemRunner", "unrestricted"],
            ["icacls.exe", FOLDER, "/grant:r", "*S-1-5-80-1994812370-2417282942-4224635210-1542273099-3328997366:(OI)(CI)RX"],
            ["sc.exe", "start", "EcosystemRunner"],
            ["sc.exe", "query", "EcosystemRunner"]])

    def test_logon_failure_is_typed_093(self):
        s, _ = make(Fake({"sc.exe start": 1069}))
        with self.assertRaises(runners.LogonRightMissing) as cm:
            s.install_service("EcosystemRunner", "NT SERVICE\\EcosystemRunner", FOLDER)
        self.assertIsInstance(cm.exception, winsys.LogonFailure)
        self.assertIn("logon failure", str(cm.exception))

    def test_other_failure_is_typed(self):
        s, _ = make(Fake({"sc.exe create": 5}))
        with self.assertRaises(winsys.ServiceCommandFailed):
            s.install_service("EcosystemRunner", "NT SERVICE\\EcosystemRunner", FOLDER)

    def test_virtual_account_has_logon_right_only_for_own_name(self):
        s, _ = make(Fake())
        self.assertTrue(s.has_logon_right("NT SERVICE\\EcosystemRunner"))
        self.assertFalse(s.has_logon_right("NT SERVICE\\Other"))
        self.assertFalse(s.has_logon_right("DOMAIN\\user"))

    def test_delete_service_stops_then_deletes_043(self):
        f = Fake()
        s, _ = make(f)
        s.delete_service()
        self.assertEqual(f.calls, [["sc.exe", "stop", "EcosystemRunner"], ["sc.exe", "query", "EcosystemRunner"],
                                   ["sc.exe", "delete", "EcosystemRunner"]])

    def test_delete_is_idempotent(self):
        s, _ = make(Fake({"sc.exe stop": 1062, "sc.exe delete": 1060}))
        s.delete_service()
        s, _ = make(Fake({"sc.exe stop": 1060, "sc.exe delete": 1072}))
        s.delete_service()

    def test_delete_failure_is_typed(self):
        s, _ = make(Fake({"sc.exe delete": 5}))
        with self.assertRaises(winsys.ServiceCommandFailed):
            s.delete_service()

    def test_service_exists(self):
        self.assertTrue(make(Fake())[0].service_exists())
        self.assertFalse(make(Fake({"sc.exe query": 1060}))[0].service_exists())
        with self.assertRaises(winsys.ServiceCommandFailed):
            make(Fake({"sc.exe query": 5}))[0].service_exists()

    def test_start_when_already_running_is_fine(self):
        make(Fake({"sc.exe start": 1056}))[0].start_service()

    def test_stop_missing_or_stopped_is_fine(self):
        make(Fake({"sc.exe stop": 1062}))[0].stop_service()
        make(Fake({"sc.exe stop": 1060}))[0].stop_service()


class AclTests(unittest.TestCase):
    def test_acl_argv_094(self):
        f = Fake()
        s, _ = make(f)
        s.restrict_acl(FOLDER + "\\config.toml", runners.ACL_ACCOUNTS + ("NT SERVICE\\EcosystemRunner",))
        self.assertEqual(f.calls, [["icacls.exe", FOLDER + "\\config.toml", "/inheritance:r",
                                    "/grant:r", "NT AUTHORITY\\SYSTEM:(F)", "/grant:r", "BUILTIN\\Administrators:(F)",
                                    "/grant:r", "NT SERVICE\\EcosystemRunner:(R)"]])

    def test_acl_failure_is_typed(self):
        with self.assertRaises(winsys.ServiceCommandFailed):
            make(Fake(default=5))[0].restrict_acl("C:\\x", ("BUILTIN\\Administrators",))

    def test_install_gitlab_end_to_end_no_token_on_any_command_line(self):
        import tempfile
        from pathlib import Path
        f = Fake({"powershell.exe -NoProfile": Result(0, "True\n")})
        plain = f.__call__

        def run(argv):
            if argv[0].endswith("powershell.exe") and "Test-Path" in argv[-1]:
                f.calls.append(["powershell.exe", "probe"])
                return Result(0, "ours\n")
            if argv[0].endswith("powershell.exe") and "Queue" in argv[-1]:
                f.calls.append(["powershell.exe", "audit"])
                return Result(0, "clean\n")
            return plain(argv)

        s, _ = make(run)
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        state, prog = tmp / "state", tmp / "prog"
        state.mkdir()
        prog.mkdir()
        token = "glrt-SECRETSECRET123456"
        real = winsys._DRIVE_PATH
        winsys._DRIVE_PATH = __import__("re").compile(r"^([A-Za-z]:[\\/]|/)")  # the temp folder here is a POSIX path
        self.addCleanup(setattr, winsys, "_DRIVE_PATH", real)
        runners.install_gitlab(state, prog, "https://gitlab.example.org", token, s)
        self.assertNotIn(token, repr(f.calls))
        names = [c[0] + (" " + c[1] if c[1] in ("probe", "audit") else "") for c in f.calls]
        self.assertEqual(names[1:7], ["powershell.exe probe", "powershell.exe probe", "sc.exe", "icacls.exe", "powershell.exe audit", "icacls.exe"])  # the folder is locked before the config is written
        self.assertEqual([c[1] for c in f.calls if c[0] == "sc.exe"], ["query", "create", "sidtype", "start", "query"])


class ElevationTests(unittest.TestCase):
    def test_is_elevated_argv_and_answer_091(self):
        f = Fake({"powershell.exe -NoProfile": Result(0, "True\r\n")})
        s, _ = make(f)
        self.assertTrue(s.is_elevated())
        self.assertEqual(f.calls[0][:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"])
        self.assertFalse(make(Fake({"powershell.exe -NoProfile": Result(0, "False")}))[0].is_elevated())
        self.assertFalse(make(Fake({"powershell.exe -NoProfile": Result(1, "True")}))[0].is_elevated())


class DefinitionTests(unittest.TestCase):
    def test_service_definition_parsed_041(self):
        s, _ = make(Fake({"sc.exe qc": Result(0, QC)}))
        self.assertEqual(s.service_definition(), {
            "name": "EcosystemRunner", "binary": '"C:\\ProgramData\\EcosystemRunner\\program\\runner.exe"',
            "account": "NT SERVICE\\EcosystemRunner", "start": "auto"})

    def test_apply_definition_argv(self):
        f = Fake()
        s, _ = make(f)
        s.apply_service_definition({"name": "EcosystemRunner", "binary": '"C:\\a b\\runner.exe"',
                                    "account": "NT SERVICE\\EcosystemRunner", "start": "auto"})
        self.assertEqual(f.calls, [["sc.exe", "config", "EcosystemRunner", "binPath=", '"C:\\a b\\runner.exe"',
                                    "obj=", "NT SERVICE\\EcosystemRunner", "start=", "auto"]])

    def test_apply_definition_for_other_service_refused(self):
        with self.assertRaises(winsys.UnsafeValue):
            make(Fake())[0].apply_service_definition({"name": "Other"})

    def test_unsafe_values_refused(self):
        for bad in ('C:\\x" & calc', "C:\\x\nfoo", "C:\\x|y"):
            with self.assertRaises(winsys.UnsafeValue):
                winsys.create_argv("EcosystemRunner", "NT SERVICE\\EcosystemRunner", bad)
        with self.assertRaises(winsys.UnsafeValue):
            winsys.create_argv("bad name", "NT SERVICE\\x", FOLDER)


class HealthTests(unittest.TestCase):
    def test_stays_running_polls_each_second_040(self):
        f = Fake({"sc.exe query": Result(0, RUNNING)})
        s, sleeps = make(f)
        self.assertTrue(s.stays_running(3))
        self.assertEqual(sleeps, [1, 1, 1])
        self.assertEqual(len(f.calls), 4)

    def test_dies_midway_is_unhealthy(self):
        f = Fake({"sc.exe query": [Result(0, RUNNING), Result(0, "STATE : 1  STOPPED")]})
        s, _ = make(f)
        self.assertFalse(s.stays_running(5))

    def test_stopped_is_unhealthy_and_missing_is_unhealthy(self):
        self.assertFalse(make(Fake({"sc.exe query": Result(0, "STATE : 1  STOPPED")}))[0].stays_running(2))
        self.assertFalse(make(Fake({"sc.exe query": 1060}))[0].stays_running(2))

    def test_runner_online_uses_forge_when_given(self):
        class Forge:
            def runner_online(self): return False
        f = Fake({"sc.exe query": Result(0, RUNNING)})
        self.assertFalse(make(f, forge=Forge())[0].runner_online())
        self.assertTrue(make(f)[0].runner_online())

    def test_no_forge_means_unreachable_and_unregistered(self):
        s, _ = make(Fake())
        self.assertFalse(s.forge_reachable())
        self.assertFalse(s.unregister_runner())


class EntryTests(unittest.TestCase):
    KEY = "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\EcosystemRunner"

    def test_entry_uses_64_bit_view_and_footprint_key_043(self):
        f = Fake()
        s, _ = make(f, version="1.2.3")
        s.write_uninstall_entry()
        s.remove_uninstall_entry()
        self.assertTrue(s.uninstall_entry_exists())
        for c in f.calls:
            self.assertEqual(c[0], "reg.exe")
            self.assertEqual(c[-1], "/reg:64")
            self.assertEqual(c[2], self.KEY)
        self.assertEqual(f.calls[0], ["reg.exe", "add", self.KEY, "/v", "DisplayName", "/t", "REG_SZ", "/d", "Ecosystem Runner", "/f", "/reg:64"])
        self.assertEqual(f.calls[-2], ["reg.exe", "delete", self.KEY, "/f", "/reg:64"])

    def test_entry_missing_and_delete_missing(self):
        s, _ = make(Fake({"reg.exe query": 1, "reg.exe delete": 1}))
        self.assertFalse(s.uninstall_entry_exists())
        s.remove_uninstall_entry()


class ProtocolTests(unittest.TestCase):
    def test_every_method_the_callers_use_exists(self):
        used = {"is_elevated", "has_logon_right", "restrict_acl", "install_service", "service_exists", "stop_service", "start_service",
                "stays_running", "runner_online", "service_definition", "apply_service_definition", "uninstall_entry_exists",
                "write_uninstall_entry", "remove_uninstall_entry", "delete_service", "forge_reachable", "unregister_runner", "lock_folder"}
        for m in used:
            self.assertTrue(callable(getattr(WinSystem, m, None)), m)


class AdapterUninstallTests(Base):
    def test_uninstall_through_adapter_043(self):
        self.state()
        f = Fake()
        s, _ = make(f)
        update.uninstall(self.root, s, state_dir=self.root)
        self.assertEqual([c[:2] for c in f.calls][:3], [["sc.exe", "stop"], ["sc.exe", "query"], ["sc.exe", "delete"]])
        self.assertEqual(f.calls[3][:2], ["reg.exe", "delete"])


class GlueTests(unittest.TestCase):
    NSH = Path(__file__).resolve().parent.parent / "installer" / "nsis" / "winsys.nsh"

    def test_glue_runs_only_after_the_gate_and_stays_in_footprint_091(self):
        text = self.NSH.read_text(encoding="utf-8")
        self.assertEqual(footprint.check_source({"winsys.nsh": text}), [])
        body = text.split("Function Winsys_CreateService")[1].split("FunctionEnd")[0]
        self.assertLess(body.index("Call Winsys_Gate"), body.index("nsExec::Exec"))
        self.assertNotIn("sc.exe\" delete", body)
        self.assertIn("SetErrorLevel 38", text)

    def test_exec_elsewhere_is_still_a_violation(self):
        bad = text = "Function Other_Thing\n  ExecWait 'sc.exe delete x'\nFunctionEnd\n"
        self.assertTrue(footprint.check_source({"winsys.nsh": bad}))
        self.assertTrue(footprint.check_source({"runner-gitlab.nsh": text.replace("Other_Thing", "Winsys_X")}))

    def test_glue_commands_match_the_adapter_argv(self):
        text = self.NSH.read_text(encoding="utf-8")
        argv = winsys.create_argv("EcosystemRunner", "NT SERVICE\\EcosystemRunner", "$APPDATA\\EcosystemRunner")
        self.assertIn("sc.exe\" create EcosystemRunner binPath= \"$APPDATA\\EcosystemRunner\\program\\runner.exe\" "
                      "obj= \"NT SERVICE\\EcosystemRunner\" start= auto", text)
        self.assertEqual(argv[1:4], ["create", "EcosystemRunner", "binPath="])
        self.assertIn("SetRegView 64", text)

    @unittest.skipUnless(shutil.which("makensis"), "makensis absent")
    def test_main_nsi_compiles_with_glue(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(self.NSH.parent, d + "/nsis")
            r = subprocess.run(["makensis", "-WX", "-V1", "main.nsi"], cwd=d + "/nsis", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class ReviewFixTests(unittest.TestCase):
    NSH = GlueTests.NSH

    def test_account_must_be_the_virtual_account_of_the_name(self):
        with self.assertRaises(winsys.UnsafeValue):
            winsys.create_argv("EcosystemRunner", "NT AUTHORITY\\SYSTEM", FOLDER)
        with self.assertRaises(winsys.UnsafeValue):
            winsys.create_argv("EcosystemRunner", "NT SERVICE\\Other", FOLDER)
        f = Fake()
        with self.assertRaises(winsys.UnsafeValue):
            make(f)[0].apply_service_definition({"name": "EcosystemRunner", "account": "NT AUTHORITY\\SYSTEM"})
        self.assertEqual(f.calls, [])
        with self.assertRaises(winsys.UnsafeValue):
            make(f)[0].install_service("EcosystemRunner", "LocalSystem", FOLDER)
        self.assertEqual(f.calls, [])

    def test_failed_sidtype_or_start_cleans_up_then_raises(self):
        for key, code, exc in (("sc.exe sidtype", 5, winsys.ServiceCommandFailed), ("sc.exe start", 1069, winsys.LogonFailure),
                               ("sc.exe start", 5, winsys.ServiceCommandFailed)):
            f = Fake({key: code})
            with self.assertRaises(exc):
                make(f)[0].install_service("EcosystemRunner", "NT SERVICE\\EcosystemRunner", FOLDER)
            self.assertEqual([c[1] for c in f.calls if c[1] != "query"][-2:], ["stop", "delete"])

    def test_cleanup_failure_does_not_hide_the_error(self):
        def run(argv):
            if argv[1] in ("stop", "delete"):
                raise OSError("boom")
            return Result(1069 if argv[1] == "start" else 0)
        s = WinSystem(FOLDER, run=run, sleep=lambda x: None)
        with self.assertRaises(winsys.LogonFailure):
            s.install_service("EcosystemRunner", "NT SERVICE\\EcosystemRunner", FOLDER)

    def test_timeout_is_typed_and_output_capped(self):
        real = subprocess.run

        def slow(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 1)
        subprocess.run = slow
        try:
            with self.assertRaises(winsys.ServiceCommandFailed):
                winsys.subprocess_runner(["sc.exe", "query"])
            subprocess.run = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "x" * 200000, "")
            self.assertEqual(len(winsys.subprocess_runner(["sc.exe"]).stdout), winsys.MAX_OUTPUT)
        finally:
            subprocess.run = real

    def test_name_and_dotdot_rules(self):
        for bad in ("-x", ".x", "_x"):
            with self.assertRaises(winsys.UnsafeValue):
                winsys.create_argv(bad, "NT SERVICE\\" + bad, FOLDER)
        with self.assertRaises(winsys.UnsafeValue):
            winsys.create_argv("EcosystemRunner", "NT SERVICE\\EcosystemRunner", "C:\\a\\..\\b")
        with self.assertRaises(winsys.UnsafeValue):
            winsys.acl_argv("C:\\a\\..\\config.toml", ("BUILTIN\\Administrators",))

    def test_saved_binary_with_arguments_is_restored_unchanged(self):
        f = Fake()
        binary = '"C:\\a b\\runner.exe" run --config "C:\\a b\\config.toml"'
        make(f)[0].apply_service_definition({"name": "EcosystemRunner", "binary": binary})
        self.assertEqual(f.calls, [["sc.exe", "config", "EcosystemRunner", "binPath=", binary]])
        with self.assertRaises(winsys.UnsafeValue):
            make(f)[0].apply_service_definition({"name": "EcosystemRunner", "binary": '"C:\\a b\\runner.exe'})

    def test_gate_checks_admin_itself_and_fails_closed(self):
        text = self.NSH.read_text(encoding="utf-8")
        body = text.split("Function Winsys_Gate")[1].split("FunctionEnd")[0]
        self.assertIn("Call Elevate_IsAdmin", body)
        self.assertIn("$elev_isadmin != 1", body)
        for fn in ("Winsys_CreateService", "Winsys_DeleteService"):
            self.assertIn("sidtype", text)
        create = text.split("Function Winsys_CreateService")[1].split("FunctionEnd")[0]
        self.assertLess(create.index("sidtype"), create.index("start EcosystemRunner"))
        self.assertGreaterEqual(create.count("Call Winsys_Cleanup"), 3)

    def test_exec_must_be_an_exact_listed_command_in_its_function(self):
        def src(cmd, fn):
            return {"winsys.nsh": "Function %s\n  %s\nFunctionEnd\n" % (fn, cmd)}
        ok = "nsExec::Exec '\"$SYSDIR\\sc.exe\" start EcosystemRunner'"
        self.assertEqual(footprint.check_source(src(ok, "Winsys_CreateService")), [])
        self.assertTrue(footprint.check_source(src(ok, "Winsys_Other")))
        self.assertTrue(footprint.check_source(src(ok.replace("start", "delete"), "Winsys_CreateService")))
        self.assertTrue(footprint.check_source(src(ok.replace("EcosystemRunner", "Other"), "Winsys_CreateService")))
        for cmd in ("nsExec::Exec 'cmd.exe /c calc'", "nsExec::Exec '\"$SYSDIR\\icacls.exe\" x'", "Exec 'powershell.exe x'"):
            self.assertTrue(footprint.check_source(src(cmd, "Winsys_CreateService")), cmd)

    def test_footprint_commands_match_the_adapter_and_service_is_deleted_once(self):
        fp = footprint.load_footprint()
        entries = [e for e in fp["exec_allowed"] if e["file"] == "winsys.nsh"]
        self.assertEqual({e["function"] for e in entries}, {"Winsys_CreateService", "Winsys_Cleanup", "Winsys_FolderStatus", "Winsys_FolderAudit", "Winsys_FolderReset", "Winsys_FolderLock", "Winsys_UninstallerGrant", "Winsys_QueryState", "Winsys_StopAndWait", "Winsys_StartAndWait"})
        text = self.NSH.read_text(encoding="utf-8")
        self.assertNotIn("Function Winsys_DeleteService", text)
        for e in entries:
            for c in e["commands"]:
                self.assertTrue("'" + c + "'" in text or "`" + c + "`" in text, c)

    def test_scanner_sees_label_and_define_hidden_execs(self):
        for text in ("Function Winsys_X\n  lbl: ExecWait 'cmd.exe /c calc'\nFunctionEnd\n",
                     "!define E ExecWait\nFunction Winsys_X\n  ${E} 'cmd.exe /c calc'\nFunctionEnd\n",
                     "Function Other\nlbl: ExecWait 'x'\nFunctionEnd\n"):
            self.assertTrue(footprint.check_source({"winsys.nsh": text}), text)
        kinds = [f["kind"] for f in footprint.scan_nsis("Function F\nl1: WriteRegStr HKLM a b c\nFunctionEnd\n")]
        self.assertEqual(kinds, ["write"])


class ReviewTwoTests(unittest.TestCase):
    def test_tools_are_absolute_system32_paths(self):
        f = Fake({"powershell.exe -NoProfile": Result(0, "True")})
        s, _ = make(f)
        s.install_service("EcosystemRunner", "NT SERVICE\\EcosystemRunner", FOLDER)
        s.restrict_acl("C:\\x\\config.toml", ("BUILTIN\\Administrators",))
        s.is_elevated()
        s.write_uninstall_entry()
        s.stop_service()
        self.assertEqual({a[0] for a in f.full}, {
            "C:\\Windows\\System32\\sc.exe", "C:\\Windows\\System32\\icacls.exe", "C:\\Windows\\System32\\reg.exe",
            "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"})

    def test_system_root_validated_from_environment(self):
        self.assertEqual(winsys.system_root({"SystemRoot": "D:\\WINNT\\"}), "D:\\WINNT")
        for bad in ("", "relative", "C:\\Win;calc", "C:\\a\\..\\b", "\\\\host\\share"):
            self.assertEqual(winsys.system_root({"SystemRoot": bad}), "C:\\Windows")
        self.assertEqual(winsys.system_root({}), "C:\\Windows")

    def test_acl_path_and_accounts_are_pinned(self):
        for path in ("/grant", "config.toml", "\\\\host\\share\\c", "-x"):
            with self.assertRaises(winsys.UnsafeValue):
                winsys.acl_argv(path, ("BUILTIN\\Administrators",))
        for acct in ("Everyone:(F) Users", "Everyone", "BUILTIN\\Users", "NT SERVICE\\-x", "NT SERVICE\\a:(F)"):
            with self.assertRaises(winsys.UnsafeValue):
                winsys.acl_argv("C:\\x\\config.toml", (acct,))
        winsys.acl_argv("C:/x/config.toml", ("NT SERVICE\\EcosystemRunner", "NT AUTHORITY\\SYSTEM"))

    def test_leading_dash_refused(self):
        with self.assertRaises(winsys.UnsafeValue):
            winsys.create_argv("EcosystemRunner", "NT SERVICE\\EcosystemRunner", "-x")
        with self.assertRaises(winsys.UnsafeValue):
            make(Fake())[0].apply_service_definition({"name": "EcosystemRunner", "binary": "-x run"})
        with self.assertRaises(winsys.UnsafeValue):
            make(Fake())[0].apply_service_definition({"name": "EcosystemRunner", "binary": '"-x" run'})


class RunnerTests(unittest.TestCase):
    def test_real_runner_uses_a_list_and_no_shell(self):
        seen = {}

        def fake(argv, **kw):
            seen.update(kw, argv=argv)
            return subprocess.CompletedProcess(argv, 0, "out", "")
        real, subprocess.run = subprocess.run, fake
        try:
            r = winsys.subprocess_runner(["sc.exe", "query", "x"])
        finally:
            subprocess.run = real
        self.assertIs(seen["shell"], False)
        self.assertEqual(seen["argv"], ["sc.exe", "query", "x"])
        self.assertEqual((r.returncode, r.stdout), (0, "out"))


if __name__ == "__main__":
    unittest.main()
