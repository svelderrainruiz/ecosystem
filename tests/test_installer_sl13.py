"""SL-13 install folder lock (ecosystem-control#82): INST-REQ-030 (one folder, nothing else), 038 and 040 (update and rollback keep working),
043 (uninstall removes everything), 091 and 092 (service under its virtual account). Fake process runner and fake system, no process, no network."""
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from installer import footprint, update, winsys
from installer.winsys import FolderNotOurs, Result, WinSystem
from tests.test_installer_update import Base, FakeSystem

ROOT = Path(__file__).resolve().parent.parent
NSH = (ROOT / "installer" / "nsis" / "winsys.nsh").read_text(encoding="utf-8")
INSTALL = (ROOT / "installer" / "nsis" / "install.nsh").read_text(encoding="utf-8")
FOLDER = "C:\\ProgramData\\EcosystemRunner"
SERVICE_SID = "S-1-5-80-1994812370-2417282942-4224635210-1542273099-3328997366"
RESET_ARGVS = [["C:\\Windows\\System32\\icacls.exe", FOLDER, "/setowner", "*S-1-5-32-544", "/T", "/L"],
               ["C:\\Windows\\System32\\icacls.exe", FOLDER + "\\*", "/reset", "/T", "/L"]]
LOCK_ARGV = ["C:\\Windows\\System32\\icacls.exe", FOLDER, "/inheritance:r",
             "/grant:r", "*S-1-5-18:(OI)(CI)F", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "/grant:r", "*%s:(OI)(CI)RX" % SERVICE_SID]
BASE_LOCK_ARGV = LOCK_ARGV[:-2]  # the first-install form: Windows cannot resolve the service SID before the service exists


def func(text, name):
    return text.split("Function " + name)[1].split("FunctionEnd")[0]


def nsis_of(argv):
    """The NSIS spelling of an adapter argument list: tool under $SYSDIR, the folder as $APPDATA, $ doubled inside the script."""
    parts = []
    for a in argv:
        a = a.replace("C:\\Windows\\System32\\", "$SYSDIR\\").replace(FOLDER, "$APPDATA\\EcosystemRunner")
        if " " in a or "\n" in a:
            a = '"%s"' % a.replace("$", "$$").replace("$$APPDATA", "$APPDATA").replace("$$SYSDIR", "$SYSDIR")
        elif a.startswith("$SYSDIR") or a.startswith("$APPDATA"):
            a = '"%s"' % a
        parts.append(a)
    return " ".join(parts)


class Runner:
    """Fake process runner: answers the folder probe from `status`, records every argument list."""

    def __init__(self, status="absent", icacls=0, probe_rc=0, after_create=None, audits=None, icacls_fail_at=None, service=None,
                 start_rc=0):
        self.log = []  # every call in order, sc.exe included; `calls` leaves sc.exe out
        self.start_rc, self.sc_fail = start_rc, {}
        self.service = (after_create or status) == "ours" if service is None else service
        self.calls, self.status, self.icacls, self.probe_rc, self.after_create, self.mkdirs = [], status, icacls, probe_rc, after_create, []
        self.icacls_fail_at, self.n_icacls = icacls_fail_at, 0
        base = after_create or status
        self.audits = list(audits) if audits is not None else (["empty"] if base == "fresh" else ["clean", "clean"])

    def __call__(self, argv):
        assert isinstance(argv, list)
        self.log.append(argv)
        if argv[0].endswith("sc.exe"):
            verb = argv[1]
            if verb in self.sc_fail:
                return Result(self.sc_fail[verb])
            if verb == "query":
                return Result(0, "STATE : 4 RUNNING\r\n") if self.service else Result(1060)
            if verb == "create":
                self.service = True
            if verb == "delete":
                self.service = False
            if verb == "start":
                return Result(self.start_rc, "STATE : 4 RUNNING\r\n")
            return Result(0, "STATE : 4 RUNNING\r\n")
        self.calls.append(argv)
        if argv[0].endswith("icacls.exe"):
            self.n_icacls += 1
            if any(SERVICE_SID in a or "NT SERVICE" in a.upper() for a in argv) and not self.service:  # by SID or by name
                return Result(1332, "Successfully processed 0 files; Failed processing 1 files\r\n")  # ERROR_NONE_MAPPED
            return Result(5 if self.n_icacls == self.icacls_fail_at else self.icacls)
        if argv[0].endswith("powershell.exe") and "Queue" in argv[-1]:
            return Result(0 if self.audits and self.audits[0] != "error" else 1, (self.audits.pop(0) if self.audits else "clean") + "\r\n")
        if argv[0].endswith("powershell.exe"):
            word = self.status
            if self.mkdirs and self.after_create:
                word = self.after_create
            return Result(self.probe_rc, word + "\r\n")
        raise AssertionError(argv)

    def mkdir(self, path):
        self.mkdirs.append(path)


def adapter(runner):
    return WinSystem(FOLDER, run=runner, sleep=lambda s: None, mkdir=runner.mkdir)


class FolderAclArgv(unittest.TestCase):
    def test_exact_argument_list_030(self):
        """INST-REQ-030: inheritance removed, SYSTEM and Administrators full with (OI)(CI), the service read and execute, no Users entry."""
        self.assertEqual(winsys.folder_acl_argv(FOLDER, "EcosystemRunner"), LOCK_ARGV)

    def test_no_entry_for_users_or_authenticated_users_030(self):
        text = " ".join(LOCK_ARGV)
        for sid in ("S-1-5-32-545", "S-1-5-11", "S-1-1-0", "Users", "Everyone"):
            self.assertNotIn(sid, text)
        self.assertNotIn("/inheritance:e", text)
        self.assertNotIn("/T", LOCK_ARGV)

    def test_service_sid_is_the_real_virtual_account_sid_092(self):
        self.assertEqual(winsys.service_sid("EcosystemRunner"), SERVICE_SID)
        self.assertEqual(winsys.service_sid("ecosystemrunner"), SERVICE_SID)
        self.assertEqual(winsys.service_sid(footprint.load_footprint()["service"]["name"]), SERVICE_SID)

    def test_unsafe_values_are_refused_030(self):
        for bad in ("relative\\dir", "C:\\a'b", "C:\\a\\..\\b", "-C:\\x", "C:\\a\"b"):
            with self.assertRaises(winsys.UnsafeValue):
                winsys.folder_acl_argv(bad, "EcosystemRunner")
            with self.assertRaises(winsys.UnsafeValue):
                winsys.folder_probe_argv(bad)
        with self.assertRaises(winsys.UnsafeValue):
            winsys.folder_acl_argv(FOLDER, "bad name")

    def test_probe_argv_is_one_fixed_powershell_command_030(self):
        argv = winsys.folder_probe_argv(FOLDER)
        self.assertEqual(argv[:4], ["C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe", "-NoProfile", "-NonInteractive", "-Command"])
        self.assertEqual(len(argv), 5)
        self.assertIn("$p='%s'" % FOLDER, argv[4])
        self.assertNotIn('"', argv[4])
        self.assertNotIn("`", argv[4])
        for needle in ("S-1-5-18", "S-1-5-32-544", "1024", "GetOwner", "installer-state.json", "schema_version"):
            self.assertIn(needle, argv[4])


class ProbeSyntax(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is absent")
    def test_probe_script_parses_030(self):
        code = "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseInput($env:PROBE,[ref]$null,[ref]$e);$e.Count"
        out = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", code],
                             capture_output=True, text=True, timeout=60, env={**os.environ, "PROBE": winsys.folder_probe_argv(FOLDER)[4]})
        self.assertEqual(out.stdout.strip(), "0", out.stdout + out.stderr)


class NsisParity(unittest.TestCase):
    def test_lock_command_matches_the_adapter_and_is_listed_exactly_030(self):
        want = nsis_of(BASE_LOCK_ARGV)
        self.assertIn("nsExec::Exec `%s`" % want, func(NSH, "Winsys_FolderLock"))
        entries = [e for e in footprint.load_footprint()["exec_allowed"] if e["function"] == "Winsys_FolderLock"]
        self.assertEqual(entries, [{"file": "winsys.nsh", "function": "Winsys_FolderLock", "commands": [want]}])

    def test_probe_command_matches_the_adapter_and_is_listed_exactly_030(self):
        want = nsis_of(winsys.folder_probe_argv(FOLDER)[:4] + ['"x"'])
        want = want[:want.index('"x"')] + '"%s"' % winsys.FOLDER_PROBE.replace("@P@", "$APPDATA\\EcosystemRunner").replace("$", "$$").replace("$$APPDATA", "$APPDATA")
        self.assertIn("nsExec::ExecToStack `%s`" % want, func(NSH, "Winsys_FolderStatus"))
        entries = [e for e in footprint.load_footprint()["exec_allowed"] if e["function"] == "Winsys_FolderStatus"]
        self.assertEqual(entries, [{"file": "winsys.nsh", "function": "Winsys_FolderStatus", "commands": [want]}])

    def test_probe_and_lock_do_not_fit_any_other_function_030(self):
        fp = footprint.load_footprint()
        lock = [e for e in fp["exec_allowed"] if e["function"] == "Winsys_FolderLock"][0]["commands"][0]
        src = {"winsys.nsh": "Function Winsys_Cleanup\n  nsExec::Exec `%s`\nFunctionEnd\n" % lock}
        self.assertTrue(footprint.check_source(src))
        src = {"winsys.nsh": "Function Winsys_FolderLock\n  nsExec::Exec `%s /grant:r *S-1-5-32-545:(OI)(CI)F`\nFunctionEnd\n" % lock}
        self.assertTrue(footprint.check_source(src))

    def test_footprint_check_passes_and_names_the_new_exit_code(self):
        self.assertEqual(footprint.check_source(footprint.collect_sources()), [])
        self.assertEqual(footprint.load_footprint()["exit_codes"]["folder-not-ours"], 39)
        self.assertIn("SetErrorLevel 39", func(NSH, "Winsys_FolderRefuse"))

    def test_service_sid_in_the_nsis_text_is_the_computed_one(self):
        self.assertEqual(set(re.findall(r"\*(S-1-5-80-[0-9-]+):", NSH)), {winsys.service_sid(footprint.load_footprint()["service"]["name"])})

    def test_ordering_check_create_lock_before_any_write_030(self):
        body = func(INSTALL, "Install_Footprint")
        order = [body.index(t) for t in ("Call Winsys_FolderCheck", "Call Winsys_FolderCreate", "Call Winsys_FolderLock", "FileOpen", "WriteUninstaller", "WriteRegStr")]
        self.assertEqual(order, sorted(order))
        self.assertLess(body.index("SetShellVarContext all"), body.index("Call Winsys_FolderCheck"))

    def test_nsis_refuses_every_status_except_the_three_good_ones(self):
        check, lock = func(NSH, "Winsys_FolderCheck"), func(NSH, "Winsys_FolderLock")
        for word in ('"abse"', '"fres"', '"ours"'):
            self.assertIn("$1 != %s" % word, check)
        for word in ('"fres"', '"ours"'):
            self.assertIn("$1 != %s" % word, lock)
        self.assertNotIn('"abse"', lock)
        self.assertEqual(check.count("$1 !="), 3)
        self.assertEqual(re.findall(r'\$1 != "(\w+)"', lock), ["fres", "ours", "empt", "clea", "owne", "clea"])
        self.assertNotIn('!= "fore"', check + lock)
        self.assertIn('StrCpy $1 "fore"', func(NSH, "Winsys_FolderStatus"))
        self.assertLess(lock.index("Call Winsys_FolderRefuse"), lock.index("icacls.exe"))
        order = ["Winsys_FolderStatus", "icacls.exe", "Winsys_FolderAudit", '"empt"', "Winsys_FolderReset", "Winsys_FolderAudit"]
        at = -1
        for token in order:
            at = lock.index(token, at + 1)  # the same order as the adapter: probe, lock, audit, reset, audit
        self.assertIn("Winsys_Gate", check)
        self.assertIn("Winsys_Gate", lock)


def kinds(r):
    out = []
    for c in r.calls:
        if c[0].endswith("icacls.exe"):
            out.append({"/inheritance:r": "lock", "/setowner": "setowner", "/reset": "reset", "/grant:r": "grant"}[c[2]])
        elif "Queue" in c[-1]:
            out.append("audit")
        else:
            out.append("probe")
    return out


class AdapterLock(unittest.TestCase):
    def test_fresh_install_probe_create_probe_lock_audit_in_that_order_030(self):
        r = Runner(status="absent", after_create="fresh")
        adapter(r).prepare_folder()
        self.assertEqual(kinds(r), ["probe", "probe", "lock", "audit"])
        self.assertEqual(r.mkdirs, [FOLDER])
        self.assertEqual(r.calls[2], BASE_LOCK_ARGV)

    def test_empty_folder_of_an_administrator_is_locked_without_creating_030(self):
        r = Runner(status="fresh")
        adapter(r).prepare_folder()
        self.assertEqual(r.mkdirs, [])
        self.assertEqual(kinds(r), ["probe", "probe", "lock", "audit"])

    def test_folder_that_is_ours_gets_acl_then_audit_then_reset_then_audit_030(self):
        r = Runner(status="ours", audits=["owners", "clean"])
        adapter(r).prepare_folder()
        self.assertEqual(r.mkdirs, [])
        self.assertEqual(kinds(r), ["probe", "probe", "lock", "audit", "setowner", "reset", "audit"])
        self.assertEqual(r.calls[2], LOCK_ARGV)
        self.assertEqual(r.calls[4:6], RESET_ARGVS)

    def test_precreated_foreign_folder_is_refused_typed_and_nothing_is_written_030(self):
        for word in ("foreign", "garbage", ""):
            r = Runner(status=word)
            with self.assertRaises(FolderNotOurs) as cm:
                adapter(r).prepare_folder()
            self.assertEqual(cm.exception.kind, "folder-not-ours")
            self.assertIn("administrator must remove", str(cm.exception))
            self.assertEqual(r.mkdirs, [])
            self.assertFalse([c for c in r.calls if c[0].endswith("icacls.exe")])

    def test_failed_probe_fails_closed_030(self):
        r = Runner(status="ours", probe_rc=1)
        with self.assertRaises(FolderNotOurs):
            adapter(r).prepare_folder()
        self.assertFalse([c for c in r.calls if c[0].endswith("icacls.exe")])

    def test_folder_planted_between_the_check_and_the_create_is_refused_030(self):
        r = Runner(status="absent", after_create="foreign")
        with self.assertRaises(FolderNotOurs):
            adapter(r).prepare_folder()
        self.assertFalse([c for c in r.calls if c[0].endswith("icacls.exe")])

    def test_a_race_where_a_fresh_folder_appears_on_mkdir_is_refused_030(self):
        r = Runner(status="absent", after_create="fresh")

        def mkdir(path):
            r.mkdirs.append(path)
            raise FileExistsError(path)
        with self.assertRaises(FolderNotOurs):
            WinSystem(FOLDER, run=r, sleep=lambda s: None, mkdir=mkdir).prepare_folder()
        self.assertEqual(r.mkdirs, [FOLDER])
        self.assertEqual(len(r.calls), 1)  # initial probe only; no repair of the raced folder

    def test_lock_failure_is_typed_030(self):
        with self.assertRaises(winsys.ServiceCommandFailed):
            adapter(Runner(status="ours", icacls=5)).lock_folder()

    def test_lock_folder_refuses_absent_and_foreign_but_not_ours_or_fresh_040(self):
        for word in ("absent", "foreign"):
            with self.assertRaises(FolderNotOurs):
                adapter(Runner(status=word)).lock_folder()
        for word in ("ours", "fresh"):
            adapter(Runner(status=word)).lock_folder()


class AuditAfterTheLock(unittest.TestCase):
    """SL-13 fix round items 1 and 2: the children are audited after the lock and before any write, without following a link."""

    def test_a_new_folder_with_any_child_at_all_is_refused_and_says_delete_it_030(self):
        for found in ("clean", "owners", "links", "error"):
            r = Runner(status="absent", after_create="fresh", audits=[found])
            with self.assertRaises(FolderNotOurs) as cm:
                adapter(r).prepare_folder()
            self.assertIn("delete the folder", str(cm.exception), found)
            self.assertEqual(kinds(r), ["probe", "probe", "lock", "audit"], found)  # no reset, nothing after the audit

    def test_a_failing_audit_that_still_prints_a_good_word_is_an_error_030(self):
        class Bad(Runner):
            def __call__(self, argv):
                if argv[0].endswith("powershell.exe") and "Queue" in argv[-1]:
                    return Result(1, "empty\r\n")
                return Runner.__call__(self, argv)

        self.assertEqual(adapter(Bad(status="fresh")).folder_audit(), "error")
        with self.assertRaises(FolderNotOurs):
            adapter(Bad(status="fresh")).lock_folder()

    def test_an_empty_audit_of_a_new_folder_passes_030(self):
        adapter(Runner(status="fresh", audits=["empty"])).lock_folder()

    def test_an_old_folder_with_a_link_or_hard_link_or_failed_audit_is_refused_untouched_040(self):
        for found in ("links", "error", "empty"):
            r = Runner(status="ours", audits=[found])
            with self.assertRaises(FolderNotOurs, msg=found):
                adapter(r).lock_folder()
            self.assertEqual(kinds(r), ["probe", "lock", "audit"], found)  # no setowner, no reset: nothing is changed or followed

    def test_an_old_folder_with_foreign_owners_is_handed_to_administrators_and_reset_040(self):
        r = Runner(status="ours", audits=["owners", "clean"])
        adapter(r).lock_folder()
        self.assertEqual(kinds(r), ["probe", "lock", "audit", "setowner", "reset", "audit"])
        self.assertEqual(r.calls[3:5], RESET_ARGVS)

    def test_a_clean_old_folder_is_still_reset_so_inherited_users_entries_go_040(self):
        r = Runner(status="ours", audits=["clean", "clean"])
        adapter(r).lock_folder()
        self.assertEqual(kinds(r)[-3:], ["setowner", "reset", "audit"])

    def test_still_not_clean_after_the_reset_is_refused_040(self):
        r = Runner(status="ours", audits=["owners", "owners"])
        with self.assertRaises(FolderNotOurs):
            adapter(r).lock_folder()

    def test_a_failed_reset_is_typed_040(self):
        for at in (2, 3):
            r = Runner(status="ours", audits=["owners", "clean"], icacls_fail_at=at)
            with self.assertRaises(winsys.ServiceCommandFailed):
                adapter(r).lock_folder()

    def test_reset_never_names_the_folder_itself_and_never_follows_links_040(self):
        for argv in winsys.folder_reset_argvs(FOLDER):
            self.assertIn("/L", argv)
            self.assertIn("/T", argv)
        self.assertNotEqual(winsys.folder_reset_argvs(FOLDER)[1][1], FOLDER)
        self.assertEqual(winsys.folder_reset_argvs(FOLDER)[1][1], FOLDER + "\\*")

    def test_no_c_flag_is_left_in_any_folder_reset_command_040(self):
        root = Path(winsys.__file__).parent
        for argv in winsys.folder_reset_argvs(FOLDER):
            self.assertNotIn("/C", argv)
        lines = [l for l in (root / "nsis" / "winsys.nsh").read_text().splitlines()
                 if "icacls.exe" in l and ("/reset" in l or "/setowner" in l)]
        lines += [l for l in (root / "footprint.json").read_text().splitlines() if "icacls.exe" in l and ("/reset" in l or "/setowner" in l)]
        self.assertEqual(len(lines), 4)
        for l in lines:
            self.assertNotRegex(l, r"\s/C\b")

    def test_audit_script_is_one_line_walks_without_following_links_and_parses_030(self):
        script = winsys.FOLDER_AUDIT
        self.assertNotIn("\n", script)
        self.assertNotIn('"', script)
        self.assertNotIn("`", script)
        self.assertIn("-band 1024", script)  # a reparse point is flagged, never entered (continue)
        self.assertIn("continue", script)
        self.assertIn("HardLink", script)
        self.assertNotIn("-Recurse", script)
        if shutil.which("pwsh"):
            code = "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseInput($env:PROBE,[ref]$null,[ref]$e);$e.Count"
            out = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", code], capture_output=True, text=True, timeout=60,
                                 env={**os.environ, "PROBE": winsys.folder_audit_argv(FOLDER)[4]})
            self.assertEqual(out.stdout.strip(), "0", out.stdout + out.stderr)


class ProductionPathCallsPrepare(unittest.TestCase):
    """Item 3: the Python first-install path (runners.install_gitlab) prepares and locks the folder before its first write."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state, self.prog = self.tmp / "state", self.tmp / "prog"
        self.state.mkdir()
        self.prog.mkdir()

    def _system(self, refuse=False):
        from tests.test_installer_runners import FakeSystem as RunnerSystem
        seen = []
        outer = self

        class Spy(RunnerSystem):
            def prepare_folder(self):
                seen.append((sorted(p.name for p in outer.state.iterdir()), sorted(p.name for p in outer.prog.iterdir())))
                self.calls.append(("prepare_folder",))
                if refuse:
                    raise FolderNotOurs("not ours")
        return Spy(), seen

    def test_install_gitlab_calls_prepare_folder_first_and_before_any_file_exists_030(self):
        from installer import runners
        s, seen = self._system()
        runners.install_gitlab(self.state, self.prog, "https://lab.example.org", "glrt-TOKENTOKEN123456", s)
        self.assertEqual(seen, [([], [])])
        self.assertEqual(s.calls[0], ("prepare_folder",))

    def test_a_refused_folder_stops_install_gitlab_with_nothing_written_030(self):
        from installer import runners
        s, seen = self._system(refuse=True)
        with self.assertRaises(FolderNotOurs):
            runners.install_gitlab(self.state, self.prog, "https://lab.example.org", "glrt-TOKENTOKEN123456", s)
        self.assertEqual(list(self.state.iterdir()) + list(self.prog.iterdir()), [])
        self.assertEqual(s.calls, [("prepare_folder",)])


class ExitCode39(unittest.TestCase):
    """Item 5: FolderNotOurs maps to exit code 39 on the Python side, the same code the NSIS side sets."""

    def test_schema_and_footprint_agree_on_39_and_the_error_maps_to_it_030(self):
        from installer import schema
        self.assertEqual(schema.exit_code(schema.load_schema(), FolderNotOurs("x")), 39)
        self.assertEqual(winsys.exit_code(FolderNotOurs("x")), 39)
        self.assertEqual(footprint.load_footprint()["exit_codes"]["folder-not-ours"], 39)
        self.assertIn("SetErrorLevel 39", func(NSH, "Winsys_FolderRefuse"))

    def test_main_returns_39_for_a_foreign_folder_and_0_otherwise_030(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(winsys.main(["prepare-folder", FOLDER], system=adapter(Runner(status="foreign"))), 39)
        self.assertIn("folder-not-ours", err.getvalue())
        self.assertEqual(winsys.main(["prepare-folder", FOLDER], system=adapter(Runner(status="ours", audits=["clean", "clean"]))), 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(winsys.main(["nonsense"]), 2)

    @unittest.skipIf(os.name == "nt", "the probe would really run on Windows")
    def test_the_process_exits_39_when_the_folder_cannot_be_proved_ours_030(self):
        import sys
        p = subprocess.run([sys.executable, "-m", "installer.winsys", "prepare-folder", FOLDER], cwd=ROOT, capture_output=True, text=True,
                           timeout=60, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(p.returncode, 39, p.stderr)
        self.assertIn("folder-not-ours", p.stderr)


class UpdateKeepsTheLock(Base):
    def test_update_reapplies_the_acl_before_anything_changes_040(self):
        self.state()
        s = FakeSystem()
        res = update.update(self.root, self.staged, "1.1.0", s)
        self.assertEqual(res.status, "updated")
        self.assertEqual(s.acl_calls[0], [])  # before service_definition, stop, swap

    def test_foreign_folder_stops_the_update_with_nothing_touched_040(self):
        self.state()
        s = FakeSystem()
        s.lock_fail = True
        with self.assertRaises(OSError):
            update.update(self.root, self.staged, "1.1.0", s)
        self.assertEqual(s.calls, [])
        self.assertEqual((self.root / "program" / "runner.exe").read_text(), "old-binary")
        self.assertFalse((self.root / "backup").exists())

    def test_failed_update_restores_and_locks_again_before_the_service_comes_back_040(self):
        self.state()
        s = FakeSystem(stays=False)
        res = update.update(self.root, self.staged, "1.1.0", s)
        self.assertEqual(res.status, "restored")
        self.assertEqual(len(s.acl_calls), 3)  # before, after the swap, after the rollback swap
        self.assertIn("stop_service", s.acl_calls[2])
        self.assertNotIn("apply_service_definition", s.acl_calls[2])

    def test_update_locks_again_after_the_swap_before_the_service_starts_040(self):
        self.state()
        s = FakeSystem()
        update.update(self.root, self.staged, "1.1.0", s)
        self.assertEqual(len(s.acl_calls), 2)
        self.assertNotIn("start_service", s.acl_calls[1])
        self.assertIn("stop_service", s.acl_calls[1])

    def test_a_lock_failure_after_the_swap_rolls_back_and_locks_the_restored_files_040(self):
        self.state()
        s = FakeSystem()
        s.lock_fail_on = 2  # the second call: right after the swap
        res = update.update(self.root, self.staged, "1.1.0", s)
        self.assertEqual(res.status, "restored")
        self.assertEqual((self.root / "program" / "runner.exe").read_text(), "old-binary")
        self.assertEqual(len(s.acl_calls), 3)
        self.assertNotIn("start_service", s.acl_calls[1])

    def test_repair_reapplies_the_acl_first_040(self):
        self.state()
        s = FakeSystem()
        update.repair(self.root, self.staged, s)
        self.assertEqual(s.acl_calls, [[]])

    def test_acl_is_the_same_set_every_time_never_looser_040(self):
        runs = []
        for status in ("fresh", "ours", "ours"):
            r = Runner(status=status)
            adapter(r).lock_folder()
            runs.append([c for c in r.calls if c[0].endswith("icacls.exe") and c[2] == "/inheritance:r"][0])
        self.assertEqual(runs, [BASE_LOCK_ARGV, LOCK_ARGV, LOCK_ARGV])


def sc_verbs(r):
    return [c[1] for c in r.log if c[0].endswith("sc.exe")]


def position(r, pred):
    return [i for i, c in enumerate(r.log) if pred(c)]


def is_service_grant(c):
    return c[0].endswith("icacls.exe") and any(a.startswith("*" + SERVICE_SID) for a in c)


class ServiceSidOnlyAfterTheServiceExists(unittest.TestCase):
    """The Windows guest found rc 1332 (ERROR_NONE_MAPPED): the service SID cannot be granted before the service exists."""

    def _first_install(self, **kw):
        r = Runner(status="absent", after_create="fresh", **kw)
        s = adapter(r)
        s.prepare_folder()
        return r, s

    def test_the_fake_models_windows_and_refuses_the_full_lock_without_a_service_1332(self):
        r = Runner(status="fresh")
        self.assertEqual(r(LOCK_ARGV).returncode, 1332)
        r.service = True
        self.assertEqual(r(LOCK_ARGV).returncode, 0)

    def test_first_install_locks_a_fresh_folder_with_no_service_sid_and_succeeds_1332(self):
        r, _ = self._first_install()
        self.assertEqual(r.calls[2], BASE_LOCK_ARGV)
        self.assertFalse([c for c in r.log if is_service_grant(c)])
        self.assertEqual(kinds(r), ["probe", "probe", "lock", "audit"])

    def test_install_service_grants_the_sid_after_sidtype_and_before_start_1332(self):
        r, s = self._first_install()
        s.install_service("EcosystemRunner", "NT SERVICE\\EcosystemRunner", FOLDER)
        grant = position(r, is_service_grant)
        self.assertEqual(len(grant), 1)
        self.assertEqual(r.log[grant[0]], winsys.service_grant_argv(FOLDER, "EcosystemRunner"))
        self.assertEqual(r.log[grant[0]][2:], ["/grant:r", "*%s:(OI)(CI)RX" % SERVICE_SID])
        sc = [(i, c[1]) for i, c in enumerate(r.log) if c[0].endswith("sc.exe") and c[1] in ("create", "sidtype", "start")]
        self.assertEqual([v for _, v in sc], ["create", "sidtype", "start"])
        self.assertTrue(sc[1][0] < grant[0] < sc[2][0], (sc, grant))

    def test_a_config_file_gets_its_own_read_grant_before_start_1332(self):
        r, s = self._first_install()
        cfg = FOLDER + "\\program\\config.toml"
        s.install_service("EcosystemRunner", "NT SERVICE\\EcosystemRunner", FOLDER, files=(cfg,))
        grants = position(r, is_service_grant)
        self.assertEqual(r.log[grants[1]][1:], [cfg, "/grant:r", "*%s:(R)" % SERVICE_SID])
        self.assertLess(grants[1], position(r, lambda c: c[0].endswith("sc.exe") and c[1] == "start")[0])

    def test_a_refused_grant_removes_the_service_and_leaves_the_folder_locked_1332(self):
        r, s = self._first_install()
        r.icacls_fail_at = r.n_icacls + 1
        with self.assertRaises(winsys.ServiceCommandFailed):
            s.install_service("EcosystemRunner", "NT SERVICE\\EcosystemRunner", FOLDER)
        self.assertNotIn("start", sc_verbs(r))
        self.assertIn("delete", sc_verbs(r))
        self.assertFalse(r.service)
        self.assertEqual(r.calls[2], BASE_LOCK_ARGV)  # the lock stays: nothing reopens the folder

    def test_a_failed_start_still_cleans_up_after_the_grant_1332(self):
        r, s = self._first_install(start_rc=1069)
        with self.assertRaises(winsys.LogonFailure):
            s.install_service("EcosystemRunner", "NT SERVICE\\EcosystemRunner", FOLDER)
        self.assertFalse(r.service)

    def test_with_a_service_the_full_single_call_lock_is_kept_1332(self):
        for status in ("fresh", "ours"):
            r = Runner(status=status, service=True)
            adapter(r).lock_folder()
            self.assertEqual(r.calls[1], LOCK_ARGV, status)

    def test_repair_without_a_service_locks_the_base_form_then_install_service_adds_the_sid_1332(self):
        r = Runner(status="ours", service=False)
        s = adapter(r)
        s.lock_folder()
        self.assertEqual(r.calls[1], BASE_LOCK_ARGV)
        s.install_service("EcosystemRunner", "NT SERVICE\\EcosystemRunner", FOLDER)
        self.assertEqual(len(position(r, is_service_grant)), 1)

    def test_nsis_first_lock_has_no_service_sid_and_create_service_grants_it_between_sidtype_and_start_1332(self):
        lock = func(NSH, "Winsys_FolderLock")
        self.assertNotIn(SERVICE_SID, lock)
        create = func(NSH, "Winsys_CreateService")
        grant = "nsExec::Exec `%s`" % nsis_of(winsys.service_grant_argv(FOLDER, "EcosystemRunner"))
        self.assertIn(grant, create)
        self.assertTrue(create.index("sidtype") < create.index(grant) < create.index("sc.exe\" start"))
        after = create[create.index(grant):]
        self.assertIn("Call Winsys_Cleanup", after.split("sc.exe\" start")[0])  # a refused grant removes the service
        entries = [e for e in footprint.load_footprint()["exec_allowed"] if e["function"] == "Winsys_CreateService"]
        self.assertIn(grant[len("nsExec::Exec `"):-1], entries[0]["commands"])

    def test_the_fake_refuses_the_service_by_name_or_sid_without_a_service_1332(self):
        r = Runner(status="fresh")
        cfg = FOLDER + "\\program\\config.toml"
        self.assertEqual(r(winsys.acl_argv(cfg, ("NT AUTHORITY\\SYSTEM", "NT SERVICE\\EcosystemRunner"))).returncode, 1332)
        self.assertEqual(r(winsys.service_grant_argv(cfg, "EcosystemRunner", "(R)")).returncode, 1332)
        self.assertEqual(r(winsys.acl_argv(cfg, ("NT AUTHORITY\\SYSTEM", "BUILTIN\\Administrators"))).returncode, 0)

    def test_the_real_first_install_path_writes_config_admin_only_then_grants_the_service_before_start_1332(self):
        import tempfile
        from installer import runners
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        state, prog = tmp / "state", tmp / "prog"
        state.mkdir()
        prog.mkdir()
        real = winsys._DRIVE_PATH
        winsys._DRIVE_PATH = re.compile(r"^([A-Za-z]:[\\/]|/)")  # the temp folder is a POSIX path
        self.addCleanup(setattr, winsys, "_DRIVE_PATH", real)
        r = Runner(status="absent", after_create="fresh")

        class Sys(WinSystem):
            def is_elevated(self):
                return True

            def has_logon_right(self, account):
                return True
        s = Sys(FOLDER, run=r, sleep=lambda x: None, mkdir=r.mkdir)
        runners.install_gitlab(state, prog, "https://lab.example.org", "glrt-TOKENTOKEN123456", s)
        cfg = str(prog / runners.GITLAB_CONFIG)
        on_cfg = [c for c in r.log if c[0].endswith("icacls.exe") and c[1] == cfg]
        self.assertEqual(on_cfg[0][2:], ["/inheritance:r", "/grant:r", "NT AUTHORITY\\SYSTEM:(F)", "/grant:r", "BUILTIN\\Administrators:(F)"])
        self.assertEqual(on_cfg[1][2:], ["/grant:r", "*%s:(R)" % SERVICE_SID])
        i_create = position(r, lambda c: c[0].endswith("sc.exe") and c[1] == "create")[0]
        i_start = position(r, lambda c: c[0].endswith("sc.exe") and c[1] == "start")[0]
        i_cfg_admin, i_cfg_svc = (r.log.index(c) for c in on_cfg)
        self.assertLess(i_cfg_admin, i_create)
        self.assertTrue(i_create < i_cfg_svc < i_start)

    def test_a_refused_config_grant_cleans_up_removes_config_and_keeps_the_folder_locked_1332(self):
        import tempfile
        from installer import runners
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "state").mkdir()
        (tmp / "prog").mkdir()
        real = winsys._DRIVE_PATH
        winsys._DRIVE_PATH = re.compile(r"^([A-Za-z]:[\\/]|/)")
        self.addCleanup(setattr, winsys, "_DRIVE_PATH", real)
        r = Runner(status="absent", after_create="fresh")

        class Sys(WinSystem):
            def is_elevated(self):
                return True

            def has_logon_right(self, account):
                return True
        s = Sys(FOLDER, run=r, sleep=lambda x: None, mkdir=r.mkdir)
        # icacls calls in order: folder lock, config admin-only, folder service grant, config service grant (the 4th fails)
        r.icacls_fail_at = 4
        with self.assertRaises(winsys.ServiceCommandFailed):
            runners.install_gitlab(tmp / "state", tmp / "prog", "https://lab.example.org", "glrt-TOKENTOKEN123456", s)
        self.assertFalse((tmp / "prog" / runners.GITLAB_CONFIG).exists())
        self.assertFalse(r.service)
        self.assertNotIn("start", sc_verbs(r))
        self.assertEqual(r.calls[2], BASE_LOCK_ARGV)

    def test_install_gitlab_passes_the_config_to_install_service_and_not_the_sid_to_its_acl_1332(self):
        from installer import runners
        from tests.test_installer_runners import FakeSystem as RunnerSystem
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "state").mkdir()
        (tmp / "prog").mkdir()
        got = {}

        class Spy(RunnerSystem):
            def install_service(self, name, account, folder, files=()):
                got["files"] = files
                RunnerSystem.install_service(self, name, account, folder, files)
        s = Spy()
        runners.install_gitlab(tmp / "state", tmp / "prog", "https://lab.example.org", "glrt-TOKENTOKEN123456", s)
        self.assertEqual(got["files"], (str(tmp / "prog" / runners.GITLAB_CONFIG),))
        self.assertFalse([a for _, accounts, _ in s.acl_calls for a in accounts if "NT SERVICE" in a])


class UninstallStillWorks(Base):
    def test_uninstall_removes_everything_in_the_locked_folder_043(self):
        """The Administrators entry is full control with (OI)(CI), so an elevated uninstall can delete every file under it."""
        self.state()
        self.assertIn("*S-1-5-32-544:(OI)(CI)F", LOCK_ARGV)
        self.assertIn("*S-1-5-18:(OI)(CI)F", LOCK_ARGV)
        s = FakeSystem()
        rep = update.uninstall(self.root, s, state_dir=self.root)
        self.assertFalse(self.root.exists())
        self.assertIn("folder", rep.text())
        self.assertEqual(s.acl_calls, [])

    def test_uninstall_keeps_a_file_a_user_cannot_have_planted_but_reports_it_043(self):
        self.state()
        (self.root / "stranger.txt").write_text("not ours")
        update.uninstall(self.root, FakeSystem(), state_dir=self.root)
        self.assertTrue((self.root / "stranger.txt").exists())

    def test_nsis_uninstall_still_removes_the_whole_folder_043(self):
        # SL-23 (#115): a recursive RMDir follows a junction, so the folder is emptied by un.Tree_Remove and then removed with a plain RMDir.
        text = (ROOT / "installer" / "nsis" / "uninstall.nsh").read_text(encoding="utf-8")
        self.assertIn("Call un.Tree_Remove", text)
        self.assertIn('RMDir "$APPDATA\\EcosystemRunner"', text)
        self.assertNotIn("RMDir /r", text)
        self.assertNotIn("icacls", text)


class ConfigAclStaysSL5(unittest.TestCase):
    def test_config_file_acl_is_untouched_and_not_looser_than_the_folder_030(self):
        from installer import runners
        self.assertEqual(runners.ACL_ACCOUNTS, ("NT AUTHORITY\\SYSTEM", "BUILTIN\\Administrators"))
        argv = winsys.acl_argv(FOLDER + "\\program\\config.toml", runners.ACL_ACCOUNTS + ("NT SERVICE\\EcosystemRunner",))
        self.assertEqual(argv[2:], ["/inheritance:r", "/grant:r", "NT AUTHORITY\\SYSTEM:(F)", "/grant:r", "BUILTIN\\Administrators:(F)",
                                    "/grant:r", "NT SERVICE\\EcosystemRunner:(R)"])


if __name__ == "__main__":
    unittest.main()
