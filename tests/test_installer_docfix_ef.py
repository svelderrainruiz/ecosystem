"""DOC-1E/F: run the shipped NSIS write and page functions, injecting native failures."""
import re
import unittest

from tests.nsis_interp import ROOT, UpdateWorld, World, source_text


class InstallWorld(UpdateWorld):
    native_Install_Footprint = None  # execute the fresh-install function, not the routing stub


class WriteFailures(unittest.TestCase):
    def test_failed_uninstaller_does_not_publish_registry_values(self):
        for entry in ("Install_Footprint", "Update_WriteEntry"):
            with self.subTest(entry=entry):
                w = InstallWorld(fail=("uninstaller",))
                self.assertEqual(w.start(entry), "quit")
                self.assertEqual(w.errorlevel, 48)
                self.assertEqual(w.regs, {})
                self.assertNotIn(ROOT + "\\uninstall.exe", w.files)
                self.assertIn(("uninstaller", "WriteUninstaller", "48"), w.log)

    def test_previous_error_does_not_block_a_successful_entry(self):
        w = InstallWorld()
        w.errors = True
        self.assertEqual(w.start("Update_WriteEntry"), "done")
        self.assertEqual(len(w.regs), 4)
        self.assertIn(ROOT + "\\uninstall.exe", w.files)

    def test_stale_install_error_does_not_report_uninstaller_failure(self):
        class StaleFlagWorld(InstallWorld):
            def native_Install_RunnerState(self):
                self.errors = True  # A previous call returned with the sticky flag set.

        w = StaleFlagWorld()
        self.assertEqual(w.start("Install_Footprint"), "done")
        self.assertNotEqual(w.errorlevel, 48)
        self.assertIn(ROOT + "\\uninstall.exe", w.files)
        self.assertEqual(len(w.regs), 4)

    def test_each_product_state_write_stops_before_publication(self):
        for entry, name in (("Install_Footprint", "installer-state.json"),
                            ("Install_Footprint", "runner-forge.json"),
                            ("Install_Footprint", "runner-mode.json"),
                            ("Update_WriteState", "installer-state.json")):
            with self.subTest(entry=entry, name=name):
                w = InstallWorld()
                w.var["runner_mode"] = "github"
                path = ROOT + "\\" + name
                w.write_fails.add(path)
                self.assertEqual(w.start(entry), "quit")
                self.assertEqual(w.errorlevel, 49)
                self.assertEqual(w.regs, {})
                self.assertEqual(w.files[path], "")
                self.assertFalse(w.fh)
                self.assertIn(("state-file", "write " + name, "49"), w.log)

    def test_failed_backup_metadata_is_not_a_restore_point(self):
        w = InstallWorld(files={ROOT + r"\program\runner.exe": "installed"})
        w.write_fails.add(ROOT + r"\backup\service.json")
        self.assertEqual(w.start("Update_Backup"), "quit")
        self.assertEqual(w.errorlevel, 49)
        self.assertIn(("state-file", r"write backup\service.json", "49"), w.log)
        self.assertNotIn(r"write backup\complete", w.events)
        self.assertFalse(w.under(ROOT + r"\backup"))

    def test_failed_backup_marker_open_uses_state_exit_and_existing_cleanup(self):
        marker = ROOT + r"\backup\complete"
        w = InstallWorld(files={ROOT + r"\program\runner.exe": "installed"}, fail=(marker,))
        self.assertEqual(w.start("Update_Backup"), "quit")
        self.assertEqual(w.errorlevel, 49)
        self.assertIn(("state-file", r"write backup\complete", "49"), w.log)
        self.assertFalse(w.under(ROOT + r"\backup"))


class DialogCreation(unittest.TestCase):
    def test_create_error_aborts_without_showing_controls(self):
        for page in ("Page_secrets", "Page_elevation"):
            with self.subTest(page=page):
                w = World(admin=False)
                w.dialog_result = "error"
                self.assertEqual(w.run(page), "abort")
                self.assertIn("nsDialogs::Create", w.trace)
                self.assertNotIn("nsDialogs::Show", w.trace)
                self.assertFalse(any("NSD_Create" in op for op in w.trace))
                self.assertEqual(w.stack, [])

    def test_only_dialog_create_macro_calls_the_plugin(self):
        sites = []
        for file, text in source_text().items():
            macro = None
            for line in text.splitlines():
                words = line.split(";", 1)[0].lower().split()
                if words[:1] == ["!macro"]:
                    macro = words[1]
                elif words[:1] == ["!macroend"]:
                    macro = None
                elif re.search(r"\bnsdialogs::create\b", " ".join(words)):
                    sites.append((file, macro))
        self.assertEqual(sites, [("dialog.nsh", "dialog_create")])
