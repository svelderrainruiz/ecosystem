"""SL-6 uninstall (ARCH-9): INST-REQ-043, 044, 045, 084, 095, 096. Network forbidden, fakes only."""
import shutil
import socket
from pathlib import Path
import unittest

from installer import update
from tests.test_installer_update import Base, FakeSystem


class UninstallTests(Base):
    def setUp(self):
        super().setUp()
        real = socket.socket

        def forbidden(*a, **k):
            raise AssertionError("network used")
        socket.socket = forbidden
        self.addCleanup(setattr, socket, "socket", real)

    def test_uninstall_works_without_network(self):
        """043, 084: service, folder, entry and keys go; forge unreachable."""
        self.state()
        s = FakeSystem()
        s.reachable = False
        rep = update.uninstall(self.root, s)
        self.assertFalse(self.root.exists())
        self.assertFalse(s.service_present)
        self.assertFalse(s.entry_present)
        self.assertEqual(rep.removed, ["service", "folder", "keys", "uninstall entry"])
        self.assertNotIn("unregister_runner", s.calls)

    def test_state_folder_other_than_the_install_folder_is_refused(self):
        """043: the state folder must be the footprint's folder; the other one is never deleted."""
        self.state()
        sd = self.tmp / "state"
        sd.mkdir()
        with self.assertRaises(update.UnsafeFolder):
            update.uninstall(self.root, FakeSystem(), state_dir=sd)
        self.assertTrue(sd.exists())
        self.assertTrue(self.root.exists())
        update.uninstall(self.root, FakeSystem(), state_dir=self.root)

    def test_bad_roots_are_refused_and_nothing_is_called(self):
        """043: home, a parent, a folder of the wrong name, one without state file or program folder."""
        self.state()
        keep = self.tmp / "sibling.txt"
        keep.write_text("keep")
        other = self.tmp / "Other"
        shutil.copytree(self.root, other)
        bare = self.tmp / "EcosystemRunner2"
        bare.mkdir()
        nostate = self.tmp / "x" / "EcosystemRunner"
        (nostate / "program").mkdir(parents=True)
        for bad in (self.tmp, Path.home(), Path("/"), other, bare, nostate, self.root.parent):
            s = FakeSystem()
            with self.assertRaises(update.UnsafeFolder, msg=str(bad)):
                update.uninstall(bad, s)
            self.assertEqual(s.calls, [])
        self.assertEqual(keep.read_text(), "keep")
        self.assertTrue((self.root / "program").exists())

    def test_symlinked_root_or_parent_is_refused(self):
        """043"""
        self.state()
        link = self.tmp / "link"
        link.symlink_to(self.tmp)
        for bad in (link / "EcosystemRunner",):
            with self.assertRaises(update.UnsafeFolder):
                update.uninstall(bad, FakeSystem())
        alias = self.tmp / "alias"
        alias.mkdir()
        (alias / "EcosystemRunner").symlink_to(self.root)
        with self.assertRaises(update.UnsafeFolder):
            update.uninstall(alias / "EcosystemRunner", FakeSystem())
        self.assertTrue((self.root / "program").exists())

    def test_sibling_and_foreign_files_survive(self):
        """043: only the installer's own files go; a foreign file keeps the folder; a link inside is unlinked, not followed."""
        self.state()
        sib = self.tmp / "sibling.txt"
        sib.write_text("keep")
        (self.root / "notes.txt").write_text("mine")
        out = self.tmp / "out"
        out.mkdir()
        (out / "f").write_text("keep")
        shutil.rmtree(self.root / "keys")
        (self.root / "keys").symlink_to(out)
        rep = update.uninstall(self.root, FakeSystem())
        self.assertEqual(sib.read_text(), "keep")
        self.assertEqual((self.root / "notes.txt").read_text(), "mine")
        self.assertEqual((out / "f").read_text(), "keep")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["notes.txt"])
        self.assertIn("other files kept", rep.text())

    def test_footprint_covers_everything_uninstall_removes(self):
        """084: the folder is the footprint's one folder and every owned item is a plain name inside it."""
        from installer import footprint
        self.assertTrue(footprint.load_footprint()["folder"]["path"].endswith("\\" + self.root.name))
        for name in update.OWNED:
            self.assertEqual(Path(name).name, name)
        for name in ("config.toml", "logs", "keys", "program", "backup", update.STATE_FILE):
            self.assertIn(name, update.OWNED)

    def test_forge_address_is_redacted_in_the_report(self):
        """044: a user name or password in the address never reaches the text."""
        self.state(mode="gitlab", address="https://bob:hunter2@gl.example")
        s = FakeSystem()
        s.reachable = False
        text = update.uninstall(self.root, s).text()
        self.assertNotIn("hunter2", text)
        self.assertIn("gl.example", text)

    def test_uninstall_works_with_damaged_state(self):
        """043: a lost or damaged state file does not block removal."""
        (self.root / update.STATE_FILE).write_text("{")
        s = FakeSystem()
        update.uninstall(self.root, s)
        self.assertFalse(self.root.exists())

    def test_uninstall_lists_forge_leftovers_and_never_claims_removal(self):
        """044, 045, 096: offline, the exact place is listed and no removal is claimed."""
        for mode, place in (("github", "https://git.example/org/settings/actions/runners"), ("gitlab", "https://gl.example/admin/runners")):
            with self.subTest(mode=mode):
                self.setUp()
                self.state(mode=mode, address="https://git.example/org" if mode == "github" else "https://gl.example/")
                s = FakeSystem()
                s.reachable = False
                rep = update.uninstall(self.root, s)
                self.assertEqual(rep.leftovers, [{"forge": mode, "place": place}])
                text = rep.text()
                self.assertIn(place, text)
                self.assertNotIn("registration removed", text.lower())
                self.assertNotIn("confirmed", text)
                self.assertFalse(rep.unregistered)

    def test_unregister_attempted_only_when_forge_reachable(self):
        """095, 096, 045: reachable and confirmed: no leftover; reachable but refused or raising: still listed."""
        for result, expect_left in ((True, 0), (False, 1), (None, 1), ("yes", 1)):
            with self.subTest(result=result):
                self.setUp()
                self.state(mode="gitlab", address="https://gl.example")
                s = FakeSystem()
                s.unregister_result = result
                rep = update.uninstall(self.root, s)
                self.assertIn("unregister_runner", s.calls)
                self.assertEqual(len(rep.leftovers), expect_left)
                self.assertEqual(rep.unregistered, expect_left == 0)
                self.assertEqual("confirmed" in rep.text(), expect_left == 0)

    def test_unregister_error_is_listed_not_raised(self):
        """095, 045"""
        self.state(mode="github", address="https://git.example")
        s = FakeSystem()

        def boom():
            raise OSError("down")
        s.unregister_runner = boom
        rep = update.uninstall(self.root, s)
        self.assertEqual(len(rep.leftovers), 1)
        self.assertFalse(self.root.exists())

    def test_local_mode_has_nothing_at_the_forge(self):
        """044"""
        self.state(mode="local", address="https://stale.example")
        s = FakeSystem()
        rep = update.uninstall(self.root, s)
        self.assertEqual(rep.leftovers, [])
        self.assertNotIn("unregister_runner", s.calls)

    def test_failed_step_is_typed_and_nothing_later_runs(self):
        """084: injected failure at each destructive step; nothing later runs: the folder stays until the service is gone and the
        uninstall entry stays until the folder is gone."""
        for step, service_gone, folder_gone in (("service", False, False), ("folder", True, False), ("uninstall entry", True, True)):
            with self.subTest(step=step):
                self.setUp()
                self.state()
                s = FakeSystem()

                def fault(name, step=step):
                    if name == step:
                        raise OSError("injected")
                with self.assertRaises(update.UninstallStopped):
                    update.uninstall(self.root, s, fault=fault)
                self.assertEqual(not s.service_present, service_gone)
                self.assertEqual(not self.root.exists(), folder_gone)
                self.assertEqual((self.root / "program").exists(), not folder_gone)
                self.assertTrue(s.entry_present)

    def test_failed_service_removal_keeps_folder(self):
        """084"""
        self.state()
        with self.assertRaises(update.UninstallStopped):
            update.uninstall(self.root, FakeSystem(fail="delete_service"))
        self.assertTrue(self.root.exists())

    def test_rerun_after_a_stop_completes(self):
        """084: uninstall is re-runnable."""
        self.state()
        with self.assertRaises(update.UninstallStopped):
            update.uninstall(self.root, FakeSystem(fail="remove_uninstall_entry"))
        update.uninstall(self.root, FakeSystem())
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
