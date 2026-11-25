"""SL-23b (ecosystem-control#124): update.nsh removes its trees with Tree_Remove (tree.nsh, PR 118), never the recursive RMDir, which follows a junction.
Fail closed where the next step would copy into a half-cleared folder (the old backup), best effort where the update already succeeded or failed,
and the restore retries its removal of program like a failed copy. The real commands are proven in the guest. Fakes only."""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from installer import update

from tests.nsis_interp import NSIS, ROOT as R, UpdateWorld
from tests.test_installer_sl19 import RUNNER, UPDATE, make, run

REPO = Path(__file__).resolve().parent.parent
BACKUP = R + "\\backup"
ELSEWHERE = "D:\\elsewhere"
OUTSIDE = {ELSEWHERE + "\\precious.txt": "keep"}
CLEANUP = "update-backup-cleanup"


def cleanups(w):
    return [x for x in w.log if x[0] == CLEANUP]


class Sites(unittest.TestCase):
    def test_f_no_recursive_rmdir_is_left_and_every_call_names_backup_or_program(self):
        for path in sorted(NSIS.glob("*.ns[hi]")):
            text = path.read_text(encoding="utf-8")
            code = "\n".join(re.sub(r";.*", "", l) for l in text.splitlines())
            with self.subTest(path.name):
                self.assertIsNone(re.search(r"(?i)rmdir\s+(/\w+\s+)*/r\b", code))
        code = "\n".join(re.sub(r";.*", "", l) for l in UPDATE.splitlines())
        calls = re.findall(r'Push "([^"]*)"\s*\n\s*Call Tree_Remove', code)
        self.assertEqual(calls, ["backup", "backup", "program", "backup", "backup"])

    def test_g_the_footprint_check_passes(self):
        r = subprocess.run([sys.executable, "-m", "installer.footprint", "check"], cwd=REPO, capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout + r.stderr), (0, ""))


class BackupSite(unittest.TestCase):
    def test_a_a_junction_at_backup_goes_as_a_link_and_the_update_goes_on(self):
        w = make(links={BACKUP: ELSEWHERE}, outside=OUTSIDE)
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("done", None))
        self.assertEqual(w.tree_args[0], "backup")
        self.assertIn("unlink backup", w.events)
        self.assertEqual(w.outside, set(OUTSIDE))
        self.assertEqual(w.files[RUNNER], "new-runner")

    def test_b_a_locked_entry_in_the_old_backup_fails_closed_and_changes_nothing_43(self):
        stuck = BACKUP + "\\notes.txt"
        w = make(files={stuck: "stale", BACKUP + "\\service.json": "old"}, stuck={stuck})
        before = dict(w.files)
        n, end = run(w, "Update_Route")
        self.assertEqual((end, w.errorlevel), ("quit", 43))
        self.assertIn("The backup could not be made; nothing was changed.", w.boxes + [n.v.get("upd_msg", "")])
        self.assertEqual(w.files[RUNNER], "old-runner")
        self.assertNotIn("backup-copy", w.events)
        self.assertNotIn("stop", w.events)
        self.assertEqual({k for k in w.files if not k.startswith(BACKUP)}, {k for k in before if not k.startswith(BACKUP)})


class RestoreSite(unittest.TestCase):
    def test_c_a_junction_at_program_goes_as_a_link_and_the_copy_back_follows(self):
        w = make(fail=("swap",), links={R + "\\program": ELSEWHERE}, outside=OUTSIDE)
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("quit", 42))
        self.assertIn("program", w.tree_args)
        self.assertEqual(w.outside, set(OUTSIDE))
        self.assertNotIn(R + "\\program", w.links)
        self.assertEqual(w.files[RUNNER], "old-runner")

    def test_d_a_removal_that_keeps_failing_retries_six_times_then_exits_44_and_keeps_the_backup(self):
        w = make(fail=("swap",), restore_failures=99)
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("quit", 44))
        self.assertEqual(len([x for x in w.log if x[0] == "update-restore-retry"]), 5)
        self.assertEqual(w.tree_args.count("program"), 6)
        self.assertEqual(w.files[BACKUP + "\\program\\runner.exe"], "old-runner")

    def test_d_a_removal_that_fails_twice_then_works_restores_42(self):
        w = make(fail=("swap",), restore_failures=2)
        n, end = run(w)
        self.assertEqual((end, w.errorlevel, w.files[RUNNER]), ("quit", 42, "old-runner"))


class BestEffortSites(unittest.TestCase):
    STUCK = {BACKUP + "\\.dir"}

    def test_e_site_two_a_failed_backup_whose_folder_stays_leaves_one_log_line_and_exits_43(self):
        w = make(fail=("backup",), stuck=self.STUCK)
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("quit", 43))
        self.assertEqual(len(cleanups(w)), 1)

    def test_e_site_four_an_unconfirmed_stop_with_a_stuck_backup_still_exits_43(self):
        from tests.nsis_interp import Service
        w = make(service=Service(stop_codes=(5,)), stuck=self.STUCK)
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("quit", 43))
        self.assertEqual(len(cleanups(w)), 1)

    def test_e_site_five_a_successful_update_stays_successful_and_logs_one_line(self):
        w = make(stuck=self.STUCK)
        n, end = run(w)
        self.assertEqual((end, w.errorlevel, w.files[RUNNER]), ("done", None, "new-runner"))
        self.assertEqual(len(cleanups(w)), 1)
        self.assertEqual(cleanups(w)[0][2], "0")

    def test_e_a_removal_that_works_logs_nothing(self):
        for kw in ({}, {"fail": ("backup",)}):
            w = make(**kw)
            run(w)
            with self.subTest(kw=kw):
                self.assertEqual(cleanups(w), [])


STALE = {BACKUP + "\\program\\runner.exe": "stale-old", BACKUP + "\\service.json": '{"name": "EcosystemRunner"}'}
MARKER = BACKUP + "\\complete"


class StaleBackup(unittest.TestCase):
    """#135, part B: a backup is a restore point only when the marker is there; the marker is written last and removed first."""

    def test_a_stale_backup_without_the_marker_is_not_restored_and_the_update_succeeds(self):
        w = make(files=dict(STALE))
        n, end = run(w)
        self.assertEqual((end, w.errorlevel, w.files[RUNNER]), ("done", None, "new-runner"))
        self.assertNotIn("restore-copy", w.events)
        self.assertEqual(w.tree_args[0], "backup")

    def test_an_interrupted_update_with_the_marker_is_restored_as_before_exit_42_unchanged(self):
        w = make(files={**STALE, MARKER: ""}, fail=("swap",))
        n, end = run(w)
        self.assertIn("restore-copy", w.events)
        self.assertLess(w.events.index("restore-copy"), w.events.index("backup-copy"))
        self.assertEqual((end, w.errorlevel), ("quit", 42))

    def check_post_swap_failure(self, fault, code):
        w = make(fail=(fault,))
        self.assertEqual(w.start("Update_Route"), "quit")
        self.assertEqual(w.errorlevel, code)
        self.assertEqual(w.files[RUNNER], "new-runner")
        self.assertEqual(w.files[BACKUP + "\\program\\runner.exe"], "old-runner")
        self.assertNotIn(MARKER, w.files)

        # A newer version takes the update path even if the first run recorded its version.
        retry = UpdateWorld(files=w.files, service=w.service, installer_version="0.3.0", payload="next-runner")
        self.assertEqual(retry.start("Update_Route"), "done")
        self.assertIn("Update_Backup", retry.trace)
        self.assertNotIn("Update_RestoreFiles", retry.trace)
        self.assertEqual(retry.files[RUNNER], "next-runner")

    def test_state_open_failure_after_swap_does_not_arm_the_next_restore(self):
        self.check_post_swap_failure("state", 49)

    def test_uninstaller_failure_after_swap_does_not_arm_the_next_restore(self):
        self.check_post_swap_failure("uninstaller", 48)

    def test_the_marker_is_written_after_the_copy_and_the_service_file_and_before_the_swap(self):
        w = make()
        run(w)
        self.assertLess(w.events.index("write backup\\service.json"), w.events.index("write backup\\complete"))
        self.assertLess(w.events.index("backup-copy"), w.events.index("write backup\\complete"))
        self.assertLess(w.events.index("write backup\\complete"), w.events.index("swap"))

    def test_a_backup_that_failed_before_the_marker_is_never_a_restore_point(self):
        w = make(fail=("backup",), files={BACKUP + "\\program\\runner.exe": "half"})
        run(w)
        self.assertNotIn(MARKER, w.files)

    def test_the_marker_is_removed_before_the_backup_folder_on_success(self):
        w = make(stuck={BACKUP + "\\program\\runner.exe"})
        seen, real = [], w.native_Tree_Remove

        def spy():
            seen.append((w.stack[-1], MARKER in w.files))
            real()
        w.native_Tree_Remove = spy
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("done", None))
        self.assertEqual(seen[-1], ("backup", False))  # the marker was already gone when the last removal of backup ran
        self.assertNotIn(MARKER, w.files)
        self.assertIn(BACKUP + "\\program\\runner.exe", w.files)  # a stuck backup stays, but stale: the next update removes it
        n2 = make(files={k: v for k, v in w.files.items()}, installed="0.1.0")
        w2 = n2
        w2.stuck = set()
        run(w2)
        self.assertNotIn("restore-copy", w2.events)
        self.assertEqual(w2.files[RUNNER], "new-runner")

    def test_a_failed_restore_keeps_the_marker_so_the_backup_stays_a_restore_point(self):
        w = make(fail=("swap", "restore"))
        run(w)
        self.assertIn(MARKER, w.files)


class ModelAgrees(unittest.TestCase):
    """installer/update.py follows the same marker rule."""

    def setUp(self):
        import tempfile, shutil
        from tests.test_installer_update import FakeSystem
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "program").mkdir()
        (self.root / "program" / "runner.exe").write_text("current")
        self.staged = self.root / "staged"
        self.staged.mkdir()
        (self.staged / "runner.exe").write_text("new")
        update.write_state(self.root, "1.0.0", None, None)
        self.system = FakeSystem()
        (self.root / "backup" / "program").mkdir(parents=True)
        (self.root / "backup" / "program" / "runner.exe").write_text("stale")

    def test_no_marker_no_restore(self):
        with mock.patch.object(update, "_restore") as restore:
            update.update(self.root, self.staged, "1.1.0", self.system)
        restore.assert_not_called()
        self.assertEqual((self.root / "program" / "runner.exe").read_text(), "new")
        self.assertFalse((self.root / "backup").exists())

    def test_the_marker_is_removed_first_so_a_backup_that_stays_is_stale(self):
        shutil.rmtree(self.root / "backup")
        real = shutil.rmtree
        keep = lambda path, *a, **k: None if Path(path).name == "backup" else real(path, *a, **k)
        with mock.patch.object(update.shutil, "rmtree", keep):
            update.update(self.root, self.staged, "1.1.0", self.system)
        self.assertTrue((self.root / "backup" / "program").exists())
        self.assertFalse((self.root / "backup" / update.COMPLETE).exists())

    def test_the_marker_is_written_when_the_backup_is_done(self):
        with mock.patch.object(update, "_healthy", return_value=False), mock.patch.object(update, "_restore") as restore:
            update.update(self.root, self.staged, "1.1.0", self.system)
        self.assertEqual(restore.call_count, 1)
        self.assertTrue((self.root / "backup" / update.COMPLETE).exists())

    def spy(self, seen):
        real = shutil.rmtree

        def rmtree(path, *a, **k):
            if Path(path).name == "backup":
                seen.append((self.root / "backup" / update.COMPLETE).exists())
                return None
            return real(path, *a, **k)
        return mock.patch.object(update.shutil, "rmtree", rmtree)

    def test_order_the_marker_is_gone_before_the_backup_folder_is_removed(self):
        shutil.rmtree(self.root / "backup")
        seen = []
        with self.spy(seen):
            r = update.update(self.root, self.staged, "1.1.0", self.system)
        self.assertEqual((r.status, seen), ("updated", [False]))

    def test_order_a_copy_that_raises_leaves_no_marker(self):
        shutil.rmtree(self.root / "backup")
        seen = []
        with self.spy(seen), mock.patch.object(update.shutil, "copytree", side_effect=OSError("disk")):
            with self.assertRaises(update.BackupFailed):
                update.update(self.root, self.staged, "1.1.0", self.system)
        self.assertFalse((self.root / "backup" / update.COMPLETE).exists())

    def test_a_marker_that_cannot_be_deleted_does_not_fail_a_good_update(self):
        shutil.rmtree(self.root / "backup")
        real = Path.unlink

        def unlink(p, *a, **k):
            if p.name == update.COMPLETE:
                raise PermissionError(13, "locked")
            return real(p, *a, **k)
        with mock.patch.object(Path, "unlink", unlink):
            r = update.update(self.root, self.staged, "1.1.0", self.system)
        self.assertEqual(r.status, "updated")
        self.assertEqual((self.root / "program" / "runner.exe").read_text(), "new")
        self.assertIn("1.1.0", (self.root / "installer-state.json").read_text())

    def test_the_marker_means_restore(self):
        (self.root / "backup" / update.COMPLETE).write_text("")
        with mock.patch.object(update, "_restore") as restore:
            update.update(self.root, self.staged, "1.1.0", self.system)
        self.assertEqual(restore.call_count, 1)


class Parity(unittest.TestCase):
    """The update tests run a MODEL of Tree_Remove (UpdateWorld.native_Tree_Remove); this test keeps it in step with the real text of tree.nsh,
    run on the interpreter of tests/test_installer_uninst.py, on the same shapes: the same $2 and the same end state."""

    LINK = ("dir", ELSEWHERE)
    SHAPES = {
        "missing path": dict(path="backup", files={"program\\runner.exe"}),
        "a file": dict(path="backup", files={"backup"}),
        "an empty folder": dict(path="backup", dirs={"backup"}),
        "a tree with files": dict(path="backup", files={"backup\\a.txt", "backup\\p\\b.txt", "backup\\p\\q\\c.txt", "keep.txt"}),
        "a directory junction": dict(path="backup", links={"backup": ("dir", ELSEWHERE)}, outside={ELSEWHERE + "\\precious.txt"}),
        "a junction inside a tree": dict(path="backup", files={"backup\\a.txt"}, links={"backup\\j": ("dir", ELSEWHERE)},
                                         outside={ELSEWHERE + "\\precious.txt"}),
        "the empty path": dict(path="", files={"a.txt"}),
        "a path ending in a backslash": dict(path="backup\\", files={"backup\\a.txt"}),
    }

    def real(self, shape):
        from tests.test_installer_sl23 import remove
        from tests.test_installer_uninst import World as Real
        w = Real(files=shape.get("files", ()), dirs=shape.get("dirs", ()), links=shape.get("links"), outside=shape.get("outside", ()))
        n = remove(w, shape["path"])
        return n.v["2"], w.files, set(w.links), set(w.outside)

    def model(self, shape):
        from tests.nsis_interp import UpdateWorld
        files = {R + "\\" + f: "x" for f in shape.get("files", ())}
        files.update({R + "\\" + d + "\\.dir": "" for d in shape.get("dirs", ())})
        links = {R + "\\" + k: v[1] for k, v in shape.get("links", {}).items()}
        w = UpdateWorld(files=files, links=links, outside=shape.get("outside", ()))
        w.stack.append(shape["path"])
        w.native_Tree_Remove()
        left = {f[len(R) + 1:] for f in w.files if not f.endswith("\\.dir")}
        return w.var["2"], left, {k[len(R) + 1:] for k in w.links}, set(w.outside)

    def test_the_model_and_the_text_agree_on_every_shape(self):
        for name, shape in self.SHAPES.items():
            with self.subTest(name):
                self.assertEqual(self.model(shape), self.real(shape))

    def test_the_missing_path_answers_zero_on_both(self):
        self.assertEqual(self.real(self.SHAPES["missing path"])[0], "0")
        self.assertEqual(self.model(self.SHAPES["missing path"])[0], "0")


class FirstUpdate(unittest.TestCase):
    def test_d_the_first_update_with_no_backup_folder_makes_a_backup_and_the_marker(self):
        w = make()
        self.assertFalse(any(f.startswith(BACKUP) for f in w.files))
        n, end = run(w)
        self.assertEqual((end, w.errorlevel, w.files[RUNNER]), ("done", None, "new-runner"))
        self.assertIn("backup-copy", w.events)
        self.assertIn("write backup\\complete", w.events)
        self.assertEqual(cleanups(w), [])

    def test_d_a_failed_backup_with_no_folder_logs_no_cleanup_line(self):
        w = make(fail=("backup",))
        n, end = run(w)
        self.assertEqual((end, w.errorlevel, cleanups(w)), ("quit", 43, []))


class ReadmePins(unittest.TestCase):
    def test_the_readme_says_what_this_round_found(self):
        readme = (REPO / "installer" / "README.md").read_text(encoding="utf-8")
        for phrase in ("by a different route", "stale marker beside a good program", "does not trust it, it removes it and never restores it",
                       "A path that is not there is gone", "READ in FileFunc.nsh", "MODEL of `Tree_Remove`", "that test is what keeps the model in step",
                       "the FIRST update with no `backup\\` folder"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)


if __name__ == "__main__":
    unittest.main()
