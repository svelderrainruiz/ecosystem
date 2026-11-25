"""SL-6 update, rollback, repair (ARCH-8) and the extension check (ARCH-13): INST-REQ-011, 037, 038, 039, 040, 041, 042, 081, 082, 083.
Temporary folders and fakes only, no network."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer import update

ROOT = Path(__file__).resolve().parent.parent
NSIS = ROOT / "installer" / "nsis"


class FakeSystem:
    def __init__(self, stays=True, online=True, fail=None):
        self.stays, self.online, self.fail = stays, online, fail
        self.calls = []
        self.service_present = True
        self.entry_present = True
        self.reachable = True
        self.unregister_result = True
        self.network = []
        self.restored = False
        self.restore_bad = False
        self.acl_calls = []
        self.lock_fail = False
        self.lock_fail_on = None

    def _do(self, name):
        self.calls.append(name)
        if self.fail == name:
            raise OSError("injected failure at " + name)

    def lock_folder(self):
        self.acl_calls.append(list(self.calls))
        if self.lock_fail or self.lock_fail_on == len(self.acl_calls):
            raise OSError("folder not ours")

    def service_definition(self):
        self._do("service_definition")
        return {"name": "EcosystemRunner", "version": "old"}

    def apply_service_definition(self, d):
        self._do("apply_service_definition")
        self.applied = d
        self.restored = True

    def stop_service(self):
        self._do("stop_service")

    def start_service(self):
        self._do("start_service")

    def stays_running(self, seconds):
        self.calls.append(("stays_running", seconds))
        return self.stays if not self.restored else not self.restore_bad

    def runner_online(self):
        self.calls.append("runner_online")
        return self.online if not self.restored else not self.restore_bad

    def service_exists(self):
        return self.service_present

    def install_service(self, name, account, folder, files=()):
        self.calls.append(("install_service", name))
        self.service_present = True

    def uninstall_entry_exists(self):
        return self.entry_present

    def write_uninstall_entry(self):
        self.calls.append("write_uninstall_entry")
        self.entry_present = True

    def remove_uninstall_entry(self):
        self._do("remove_uninstall_entry")
        self.entry_present = False

    def delete_service(self):
        self._do("delete_service")
        self.service_present = False

    def forge_reachable(self):
        return self.reachable

    def unregister_runner(self):
        self.calls.append("unregister_runner")
        return self.unregister_result


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "EcosystemRunner"
        (self.root / "program").mkdir(parents=True)
        (self.root / "program" / "runner.exe").write_text("old-binary")
        (self.root / "program" / "gone.txt").write_text("old-only")
        (self.root / "logs").mkdir()
        (self.root / "logs" / "step.log").write_text("log-line")
        (self.root / "keys").mkdir()
        (self.root / "keys" / "k.pem").write_text("key-material-stand-in")
        (self.root / "config.toml").write_text("registration")
        (self.root / "runner-forge.json").write_text('{"forge": "github"}')
        self.staged = self.tmp / "staged"
        self.staged.mkdir()
        (self.staged / "runner.exe").write_text("new-binary")

    def state(self, version="1.0.0", mode="local", address=None):
        update.write_state(self.root, version, mode, address)


class UpdateTests(Base):
    def test_update_replaces_program_files_only(self):
        """038, 039: configuration, logs, registration and keys stay; the state file gets the new version."""
        self.state()
        r = update.update(self.root, self.staged, "1.1.0", FakeSystem())
        self.assertEqual(r.status, "updated")
        self.assertEqual((self.root / "program" / "runner.exe").read_text(), "new-binary")
        self.assertFalse((self.root / "program" / "gone.txt").exists())
        for rel, text in (("logs/step.log", "log-line"), ("keys/k.pem", "key-material-stand-in"),
                          ("config.toml", "registration"), ("runner-forge.json", '{"forge": "github"}')):
            self.assertEqual((self.root / rel).read_text(), text)
        self.assertEqual(update.read_state(self.root)["installer_version"], "1.1.0")

    def test_failed_health_check_restores_backup(self):
        """040, 041: the screen says only the one promise."""
        self.state()
        s = FakeSystem(stays=False)
        r = update.update(self.root, self.staged, "1.1.0", s)
        self.assertEqual(r.status, "restored")
        self.assertEqual(r.message, "previous program files restored")
        self.assertEqual((self.root / "program" / "runner.exe").read_text(), "old-binary")
        self.assertEqual(s.applied, {"name": "EcosystemRunner", "version": "old"})
        self.assertIn("start_service", s.calls[-4:])
        self.assertTrue(s.restored)
        self.assertEqual(update.read_state(self.root)["installer_version"], "1.0.0")

    def test_health_check_waits_the_fixed_time(self):
        """040: fixed time."""
        self.state()
        s = FakeSystem()
        update.update(self.root, self.staged, "1.1.0", s)
        self.assertIn(("stays_running", update.HEALTH_SECONDS), s.calls)
        self.assertGreater(update.HEALTH_SECONDS, 0)

    def test_forge_mode_needs_runner_online(self):
        """040 (D-R6-10): forge modes also need the runner online; local mode does not ask."""
        self.state(mode="github", address="https://forge.example")
        r = update.update(self.root, self.staged, "1.1.0", FakeSystem(online=False))
        self.assertEqual(r.status, "restored")
        self.state(mode="github", address="https://forge.example")
        self.assertEqual(update.update(self.root, self.staged, "1.1.0", FakeSystem(online=True)).status, "updated")
        self.state(mode="local")
        s = FakeSystem(online=False)
        self.assertEqual(update.update(self.root, self.staged, "1.2.0", s).status, "updated")
        self.assertNotIn("runner_online", s.calls)

    def test_injected_failure_at_each_step_restores_or_changes_nothing(self):
        """040: backup, stop, swap, start, health: each failure leaves the old files, state and a started service."""
        for step in update.STEPS:
            with self.subTest(step=step):
                shutil.rmtree(self.root / "backup", ignore_errors=True)
                (self.root / "program").mkdir(exist_ok=True)
                (self.root / "program" / "runner.exe").write_text("old-binary")
                self.state()
                s = FakeSystem()

                def fault(name, step=step):
                    if name == step:
                        raise OSError("injected")
                if step == "backup":
                    with self.assertRaises(update.BackupFailed):
                        update.update(self.root, self.staged, "1.1.0", s, fault)
                    self.assertFalse((self.root / "backup").exists())
                else:
                    r = update.update(self.root, self.staged, "1.1.0", s, fault)
                    self.assertEqual(r.status, "restored")
                    self.assertIn("start_service", s.calls[-4:])
                    self.assertTrue(s.restored)
                self.assertEqual((self.root / "program" / "runner.exe").read_text(), "old-binary")
                self.assertEqual((self.root / "program" / "gone.txt").read_text(), "old-only")
                self.assertEqual(update.read_state(self.root)["installer_version"], "1.0.0")

    def test_swap_that_fails_halfway_is_restored(self):
        """040: a half-copied new folder is replaced by the backup."""
        self.state()
        (self.staged / "bad").mkdir()
        (self.staged / "bad" / "f").write_text("x")
        real = shutil.copytree

        def broken(src, dst, *a, **k):
            if Path(src) == self.staged:
                Path(dst).mkdir()
                (Path(dst) / "partial").write_text("p")
                raise OSError("disk full")
            return real(src, dst, *a, **k)
        orig = shutil.copytree
        shutil.copytree = broken
        try:
            r = update.update(self.root, self.staged, "1.1.0", FakeSystem())
        finally:
            shutil.copytree = orig
        self.assertEqual(r.status, "restored")
        self.assertFalse((self.root / "program" / "partial").exists())
        self.assertEqual((self.root / "program" / "runner.exe").read_text(), "old-binary")

    def test_restore_failure_is_typed_and_keeps_backup(self):
        """040, 041: no false promise when the restore itself fails."""
        self.state()
        s = FakeSystem(stays=False)
        orig = s.apply_service_definition

        def boom(d):
            raise OSError("x")
        s.apply_service_definition = boom
        with self.assertRaises(update.RestoreFailed) as c:
            update.update(self.root, self.staged, "1.1.0", s)
        self.assertNotIn("restored.", str(c.exception).replace("not be restored", ""))
        self.assertTrue((self.root / "backup" / "program" / "runner.exe").exists())

    def test_restore_that_is_not_healthy_is_typed(self):
        """040, 041: after the restore the same health check runs; unhealthy raises and keeps the backup."""
        self.state()
        s = FakeSystem(stays=False)
        s.restore_bad = True
        with self.assertRaises(update.RestoreFailed):
            update.update(self.root, self.staged, "1.1.0", s)
        self.assertTrue((self.root / "backup").exists())

    def test_backup_holds_program_and_service_definition(self):
        """040: the backup has both while the update runs (it is removed once the update succeeded)."""
        self.state()
        seen = {}

        def fault(step):
            if step == "stop":
                seen["program"] = (self.root / "backup" / "program" / "runner.exe").read_text()
                seen["service"] = json.loads((self.root / "backup" / "service.json").read_text())["version"]
        update.update(self.root, self.staged, "1.1.0", FakeSystem(), fault)
        self.assertEqual(seen, {"program": "old-binary", "service": "old"})
        self.assertFalse((self.root / "backup").exists())

    def test_a_backup_holding_a_program_is_restored_first_never_deleted(self):
        """B2: an earlier failed restore left the only good copy in the backup; the next update restores it before making a new backup."""
        self.state()
        (self.root / "backup" / "program").mkdir(parents=True)
        (self.root / "backup" / "program" / "runner.exe").write_text("good-old")
        (self.root / "backup" / "service.json").write_text(json.dumps({"version": "old"}))
        (self.root / "backup" / update.COMPLETE).write_text("")
        update.update(self.root, self.staged, "1.1.0", FakeSystem())
        self.assertEqual((self.root / "program" / "runner.exe").read_text(), (self.staged / "runner.exe").read_text())
        self.assertFalse((self.root / "backup").exists())

    def test_a_failed_restore_of_an_old_backup_stops_and_keeps_it_untouched(self):
        self.state()
        (self.root / "backup" / "program").mkdir(parents=True)
        (self.root / "backup" / "program" / "runner.exe").write_text("good-old")
        (self.root / "backup" / "service.json").write_text("not json")
        (self.root / "backup" / update.COMPLETE).write_text("")
        with self.assertRaises(update.RestoreFailed):
            update.update(self.root, self.staged, "1.1.0", FakeSystem())
        self.assertEqual((self.root / "backup" / "program" / "runner.exe").read_text(), "good-old")

    def test_update_order(self):
        """040: stop, start, then the health check."""
        self.state()
        s = FakeSystem()
        update.update(self.root, self.staged, "1.1.0", s)
        names = [c if isinstance(c, str) else c[0] for c in s.calls]
        self.assertLess(names.index("service_definition"), names.index("stop_service"))
        self.assertLess(names.index("stop_service"), names.index("start_service"))
        self.assertLess(names.index("start_service"), names.index("stays_running"))

    def test_different_major_version_is_refused(self):
        """039, 082: state file version versus caller; nothing changes."""
        self.state("1.4.2")
        s = FakeSystem()
        with self.assertRaises(update.MajorVersionMismatch):
            update.update(self.root, self.staged, "2.0.0", s)
        self.assertEqual(s.calls, [])
        self.assertEqual((self.root / "program" / "runner.exe").read_text(), "old-binary")
        with self.assertRaises(update.MajorVersionMismatch):
            update.extension_may_drive(self.root, "2.0.0")
        self.assertTrue(update.extension_may_drive(self.root, "1.9.0"))
        self.assertTrue(update.update_available("1.0.0", "1.2.0"))
        self.assertFalse(update.update_available("1.2.0", "1.2.0"))
        self.assertFalse(update.update_available("1.2.0", "1.1.9"))

    def test_check_major_is_pure_and_strict(self):
        """082"""
        update.check_major("1.0.0", "1.99.99")
        update.check_major("10.0.0", "10.1.0")
        for a, b in (("1.0.0", "2.0.0"), ("10.0.0", "1.0.0")):
            with self.assertRaises(update.MajorVersionMismatch):
                update.check_major(a, b)
        for bad in ("1.0", "v1.0.0", "01.0.0", "", None, "1.0.0-rc"):
            with self.assertRaises(update.BadVersion):
                update.parse_version(bad)

    def test_state_file_is_validated_and_typed(self):
        """039: missing, damaged, unknown key, wrong value."""
        with self.assertRaises(update.StateMissing):
            update.read_state(self.root)
        p = self.root / update.STATE_FILE
        for text in ("{", "[]", '{"schema_version": 1}', '{"schema_version": 1, "installer_version": "1.0.0", "x": 1}',
                     '{"schema_version": 2, "installer_version": "1.0.0"}', '{"schema_version": 1, "installer_version": "1.0.0", "mode": "both"}',
                     '{"schema_version": true, "installer_version": "1.0.0"}', '{"schema_version": 1, "installer_version": 3}'):
            p.write_text(text)
            with self.assertRaises(update.UpdateError, msg=text):
                update.read_state(self.root)
        with self.assertRaises(update.UpdateError):
            update.update(self.root, self.staged, "1.1.0", FakeSystem())

    def test_state_write_is_atomic_and_leaves_no_temp_file(self):
        """039"""
        self.state("1.0.0", "gitlab", "https://gl.example")
        self.assertEqual(update.read_state(self.root), {"schema_version": 1, "installer_version": "1.0.0", "mode": "gitlab",
                                                       "forge_address": "https://gl.example"})
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])

    def test_state_schema_file_matches_the_code(self):
        """039: the schema file is the only description."""
        schema = update.load_state_schema()
        self.assertEqual(schema["required"], ["schema_version", "installer_version"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["properties"]), {"schema_version", "installer_version", "mode", "forge_address"})

    def test_nothing_to_update_is_typed(self):
        """038"""
        self.state()
        with self.assertRaises(update.NothingToUpdate):
            update.update(self.root, self.tmp / "missing", "1.1.0", FakeSystem())


class RepairTests(Base):
    def test_repair_is_idempotent_and_never_creates_keys(self):
        """042, 083: restores a removed program file; second run changes nothing; no key, no registration."""
        self.state()
        (self.root / "program" / "runner.exe").unlink()
        shutil.rmtree(self.root / "keys")
        (self.root / "config.toml").unlink()
        s = FakeSystem()
        first = update.repair(self.root, self.staged, s)
        self.assertIn("program/runner.exe", first)
        self.assertEqual((self.root / "program" / "runner.exe").read_text(), "new-binary")
        snap = sorted((str(p.relative_to(self.root)), p.read_bytes() if p.is_file() else None) for p in self.root.rglob("*"))
        self.assertEqual(update.repair(self.root, self.staged, s), [])
        self.assertEqual(snap, sorted((str(p.relative_to(self.root)), p.read_bytes() if p.is_file() else None) for p in self.root.rglob("*")))
        self.assertFalse((self.root / "keys").exists())
        self.assertFalse((self.root / "config.toml").exists())
        self.assertFalse(any("regist" in str(c) or "key" in str(c) for c in s.calls))

    def test_repair_touches_only_its_own_things(self):
        """042: service and uninstall entry are re-created when missing, nothing else is called."""
        self.state()
        s = FakeSystem()
        s.service_present = False
        s.entry_present = False
        changed = update.repair(self.root, self.staged, s)
        self.assertEqual(sorted(changed), ["program/runner.exe", "service", "uninstall entry"])
        self.assertEqual(sorted(c if isinstance(c, str) else c[0] for c in s.calls), ["install_service", "write_uninstall_entry"])
        self.assertEqual((self.root / "logs" / "step.log").read_text(), "log-line")

    def test_repair_never_writes_through_a_link(self):
        """042: a link at a program file or folder is replaced or refused; nothing lands outside program/."""
        self.state()
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "target").write_text("keep")
        (self.root / "program" / "runner.exe").unlink()
        (self.root / "program" / "runner.exe").symlink_to(outside / "target")
        update.repair(self.root, self.staged, FakeSystem())
        self.assertEqual((outside / "target").read_text(), "keep")
        self.assertFalse((self.root / "program" / "runner.exe").is_symlink())
        self.assertEqual((self.root / "program" / "runner.exe").read_text(), "new-binary")
        (self.staged / "sub").mkdir()
        (self.staged / "sub" / "f.txt").write_text("n")
        (self.root / "program" / "sub").symlink_to(outside)
        with self.assertRaises(update.RepairRefused):
            update.repair(self.root, self.staged, FakeSystem())
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ["target"])

    def test_repair_without_state_is_refused(self):
        """042"""
        with self.assertRaises(update.StateMissing):
            update.repair(self.root, self.staged, FakeSystem())


class ContractTests(unittest.TestCase):
    def test_contract_file_states_the_limits(self):
        """011, 037, 081, 082: what the extension may and never may do."""
        text = (ROOT / "installer" / "extension-contract.md").read_text()
        for needle in ("INST-REQ-011", "may never", "fetch installer code", "open the build screen", "after the user confirmed", "major version"):
            self.assertIn(needle.lower(), text.lower())

    def test_messages_promise_only_previous_program_files_restored(self):
        """041: no other restore promise in code or NSIS text."""
        src = (ROOT / "installer" / "update.py").read_text() + (NSIS / "update.nsh").read_text()
        phrases = {m.lower() for m in re.findall(r"(?i)\b(?:restored|rolled back|recover\w*)\b", src)}
        self.assertEqual(update.RESTORED, "previous program files restored")
        self.assertNotRegex(src.lower(), r"jobs (that )?ran|registration (was )?(restored|kept)|recovered")
        self.assertLessEqual(phrases, {"restored", "rolled back"})

    def test_extension_code_never_in_this_module(self):
        """081: the module performs no download or code execution."""
        src = (ROOT / "installer" / "update.py").read_text()
        for bad in ("urllib", "socket", "subprocess", "exec(", "eval(", "http.client"):
            self.assertNotIn(bad, src)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh absent")
    def test_pwsh_parses_nothing_new(self):
        """No PowerShell file was added by SL-6; the shipped ones still parse."""
        for ps in (ROOT / "installer").glob("*.ps1"):
            cmd = "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e);exit $e.Count" % ps
            self.assertEqual(subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True).returncode, 0)

    def test_nsis_files_are_in_main_and_within_footprint(self):
        """038, 043: both new files are included and pass the footprint scan."""
        from installer import footprint
        main = (NSIS / "main.nsi").read_text()
        for f in ("update.nsh", "uninstall.nsh"):
            self.assertIn('!include "%s"' % f, main)
        self.assertEqual(footprint.check_source(footprint.collect_sources()), [])


if __name__ == "__main__":
    unittest.main()
