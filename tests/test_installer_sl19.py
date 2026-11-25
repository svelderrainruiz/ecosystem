"""SL-19 (ecosystem-control#100, part of #97 and #64): the NSIS installer detects an existing install, updates it with backup and rollback, and repairs it.
INST-REQ-038 (program files only), 039 (state file, major version), 040 (backup, stop, swap, start, health, restore), 041 (rollback text),
042 (repair). The NSIS control flow runs against the shared interpreter of tests/nsis_interp.py (UpdateWorld, a scripted Windows); the real commands are
proven in the guest. Fakes only, no process, no network."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer import footprint, image
from installer import schema as S
from tests.nsis_interp import NSIS, Program, ROOT as R, Service, UpdateWorld as World, source_text
from tests.test_installer_sl16b import DESKTOP, RECORD, pinned_schema, ready

REPO = Path(__file__).resolve().parent.parent
UPDATE = (NSIS / "update.nsh").read_text(encoding="utf-8")
WINSYS = (NSIS / "winsys.nsh").read_text(encoding="utf-8")
MAIN = (NSIS / "main.nsi").read_text(encoding="utf-8")
README = (REPO / "installer" / "README.md").read_text(encoding="utf-8")
RUNNER = R + "\\program\\runner.exe"
STATE = R + "\\installer-state.json"
KEPT = {R + "\\config.toml": "cfg", R + "\\logs\\steps.jsonl": "log", R + "\\keys\\placeholder.txt": "key-placeholder",
        R + "\\runner-mode.json": '{"mode": "github"}\r\n', R + "\\runner-forge.json": '{"address": "forge.example"}', R + "\\uninstall.exe": "uninstaller"}


def state_line(version="0.1.0"):
    return '{"forge_address": "forge.example", "installer_version": "%s", "mode": "github", "schema_version": 1}\r\n' % version


def rewritten(version):
    """What the engine writes back: the same fields, the line ending of update.py write_state."""
    return state_line(version).replace("\r\n", "\n")


def make(installed="0.1.0", service=None, **kw):
    files = {RUNNER: "old-runner", STATE: state_line(installed), **KEPT}
    files.update(kw.pop("files", {}))
    return World(files=files, service=service or Service(), **kw)


def run(world, entry="Update_Route"):
    return world, world.start(entry)


def steps(world, *verbs):
    return [e for e in world.events if e in verbs]


class Detection(unittest.TestCase):
    def test_no_state_file_runs_the_first_install_unchanged_039(self):
        """INST-REQ-039: no state file means a first install; nothing is read or changed by the update code."""
        w = World(files={})
        n, end = run(w)
        self.assertEqual((end, w.events), ("done", ["install-footprint"]))
        self.assertEqual(n.v["upd_mode"], "fresh")

    def test_not_elevated_stays_fresh_and_reads_nothing_039(self):
        w = make(admin=False)
        n, end = run(w, "Update_Detect")
        self.assertEqual((n.v["upd_mode"], w.events), ("fresh", []))

    def test_versions_choose_the_mode_039_040_042(self):
        """INST-REQ-040, 042: an older installed version is an update, the same version a repair; a newer one or another major version is refused (exit 41)."""
        for installed, mode, level in (("0.1.0", "update", None), ("0.2.0", "repair", None), ("0.1.9", "update", None), ("0.0.9", "update", None),
                                       ("0.3.0", None, 41), ("0.2.1", None, 41), ("1.0.0", None, 41), ("0.10.0", None, 41)):
            w = make(installed)
            n, end = run(w, "Update_Detect")
            with self.subTest(installed=installed):
                if mode:
                    self.assertEqual((end, n.v["upd_mode"], w.errorlevel), ("done", mode, None))
                else:
                    self.assertEqual((end, w.errorlevel), ("quit", level))
                    self.assertEqual(w.events, [])
                    self.assertEqual(w.files[STATE], state_line(installed))

    def test_a_damaged_state_file_is_refused_and_nothing_changes_039(self):
        """INST-REQ-039: unreadable, no schema_version 1, no version, or a version that is not three plain numbers: exit 45, nothing touched."""
        bad = ["", "garbage", '{"installer_version": "0.1.0"}\r\n', '{"schema_version": 1}\r\n', '{"schema_version": 1, "installer_version": "0.1"}\r\n',
               '{"schema_version": 1, "installer_version": "01.2.3"}\r\n', '{"schema_version": 1, "installer_version": "1.2.3.4"}\r\n',
               '{"schema_version": 1, "installer_version": "1.-2.3"}\r\n', '{"schema_version": 1, "installer_version": "a.b.c"}\r\n',
               '{"schema_version": 1, "installer_version": "1..3"}\r\n', '{"schema_version": 1, "installer_version": "0.1.0}\r\n']
        for text in bad:
            w = make(files={STATE: text})
            before = dict(w.files)
            n, end = run(w)
            with self.subTest(text=text):
                self.assertEqual((end, w.errorlevel, w.events), ("quit", 45, []))
                self.assertEqual(w.files, before)
                self.assertEqual(w.boxes, [])

    def test_the_refusal_text_is_the_one_of_the_python_model_039(self):
        w = make(files={STATE: "garbage"}, silent=False)
        run(w)
        self.assertEqual(w.boxes, ["The installer state file is damaged; nothing was changed."])
        w = make("1.0.0", silent=False)
        run(w)
        self.assertIn("different major versions; nothing was changed", w.boxes[0])


class Update(unittest.TestCase):
    def test_the_order_is_lock_backup_stop_swap_lock_start_health_state_040(self):
        """INST-REQ-040: backup, stop, swap, start, health check, and the state file last."""
        w = make()
        n, end = run(w)
        order = [e for e in w.events if e in ("lock", "backup-copy", "stop", "swap", "start", "write installer-state.json", "entry")]
        self.assertEqual(order, ["lock", "backup-copy", "stop", "swap", "lock", "start", "write installer-state.json", "entry"])
        self.assertEqual(end, "done")
        self.assertEqual(w.files[RUNNER], "new-runner")
        self.assertFalse(any(f.startswith(R + "\\backup") for f in w.files), "the backup folder is removed after a successful update")

    def test_the_health_check_polls_thirty_times_one_second_apart_040(self):
        """INST-REQ-040: the service stays running for 30 seconds, polled once a second."""
        w = make()
        run(w)
        self.assertEqual(w.sleeps.count(1000), 1 + 29)
        self.assertEqual(w.service.state, "RUNNING")

    def test_the_stop_is_confirmed_before_the_swap_and_a_pending_stop_is_waited_for_040(self):
        w = make(service=Service(stop_script=("STOP_PENDING", "STOP_PENDING", "STOPPED")))
        run(w)
        queries_before_swap = w.events[:w.events.index("swap")].count("query")
        self.assertGreaterEqual(queries_before_swap, 3)
        self.assertEqual(w.files[RUNNER], "new-runner")

    def test_a_stop_answered_1061_is_retried_with_backoff_040(self):
        w = make(service=Service(stop_codes=(1061, 1061, 0)))
        run(w)
        self.assertEqual(w.sleeps[:2], [1000, 2000])
        self.assertEqual(w.files[RUNNER], "new-runner")

    def test_a_stop_that_is_never_confirmed_changes_nothing_and_exits_43_040(self):
        """INST-REQ-040: a service not confirmed stopped never gets its files swapped; exit 43, no backup left, the old file kept."""
        for service in (Service(stop_script=("STOP_PENDING",)), Service(stop_codes=(1061,)), Service(stop_codes=(5,))):
            w = make(service=service)
            before = {k: v for k, v in w.files.items()}
            n, end = run(w)
            with self.subTest(service=service.stop_codes):
                self.assertEqual((end, w.errorlevel), ("quit", 43))
                self.assertEqual(w.files, before)
                self.assertNotIn("swap", w.events)
                self.assertNotIn("swap-failed", w.events)
                self.assertFalse(any(f.startswith(R + "\\backup") for f in w.files))

    def test_a_failed_backup_changes_nothing_and_exits_43_040(self):
        w = make(fail=("backup",))
        before = dict(w.files)
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("quit", 43))
        self.assertNotIn("stop", w.events)
        self.assertEqual(w.files, before)

    def test_swap_start_and_health_failures_restore_the_old_files_and_exit_42_040_041(self):
        """INST-REQ-040, 041: a failed swap, start or health check puts the previous program files back; exit 42, the version in the state file is unchanged."""
        cases = {"swap": make(fail=("swap",)), "start": make(service=Service(start_codes=(1053, 0))),
                 "pending": make(service=Service(start_scripts=(("RUNNING",) * 3 + ("START_PENDING",), ("RUNNING",)))),
                 "health": make(service=Service(start_scripts=(("RUNNING",) * 4 + ("STOPPED",), ("RUNNING",))))}
        for name, w in cases.items():
            n, end = run(w)
            with self.subTest(name):
                self.assertEqual((end, w.errorlevel), ("quit", 42))
                self.assertEqual(w.files[RUNNER], "old-runner")
                self.assertEqual(w.files[STATE], state_line("0.1.0"))
                self.assertEqual(w.service.state, "RUNNING")
                self.assertEqual(w.events[w.events.index("swap"):].count("stop") if "swap" in w.events else 1, 1)
                self.assertTrue(any(f.startswith(R + "\\backup") for f in w.files))
                self.assertIn(("update-restore", "restore program files", "0"), w.log)

    def test_the_only_rollback_text_is_previous_program_files_restored_041(self):
        """INST-REQ-041: the box says only that sentence; no promise about jobs, registration or the backup."""
        w = make(fail=("swap",), silent=False)
        run(w)
        self.assertEqual(w.boxes[1:], ["previous program files restored"])
        for words in ("job", "regist", "backup", "recover", "forge"):
            self.assertNotIn(words, w.boxes[1].lower())
        texts = re.findall(r'StrCpy \$upd_msg "([^"]*)"', UPDATE)
        self.assertEqual([t for t in texts if "restored" in t and "could not" not in t], ["previous program files restored"])

    def test_a_failed_restore_keeps_the_backup_and_exits_44_040_041(self):
        """INST-REQ-040: restore copy failing, or the restored service not healthy: exit 44, the backup folder is kept."""
        cases = {"copy": make(fail=("swap", "restore")),
                 "unhealthy": make(service=Service(start_scripts=(("STOPPED",), ("STOPPED",)))),
                 "stop": make(service=Service(stop_codes=(0, 0, 5), stop_script=("STOP_PENDING", "STOPPED"), start_scripts=(("RUNNING",) * 3 + ("STOPPED",),)))}
        for name, w in cases.items():
            n, end = run(w)
            with self.subTest(name):
                self.assertEqual((end, w.errorlevel), ("quit", 44))
                self.assertEqual(w.files[R + "\\backup\\program\\runner.exe"], "old-runner")
                self.assertEqual(w.files[R + "\\backup\\service.json"].count("EcosystemRunner") > 0, True)
                self.assertFalse(any(e.startswith("rmdir backup") for e in w.events[w.events.index("backup-copy"):]))

    def test_a_failed_restore_says_the_backup_was_kept_and_not_the_promised_sentence_041(self):
        w = make(fail=("swap", "restore"), silent=False)
        run(w)
        self.assertEqual(len(w.boxes), 2)
        self.assertIn("could not be restored", w.boxes[1])
        self.assertIn("was kept", w.boxes[1])

    def test_configuration_logs_keys_registration_and_state_survive_an_update_038(self):
        """INST-REQ-038: only program files are replaced; configuration, logs, keys and the registration files are byte-identical."""
        w = make()
        run(w)
        for path, text in KEPT.items():
            self.assertEqual(w.files[path], text, path)
        written = [e for e in w.events if e.startswith("write ")]
        self.assertEqual(written, ["write backup\\service.json", "write backup\\complete", "write installer-state.json"])

    def test_the_state_file_keeps_mode_and_forge_address_and_is_written_last_039(self):
        """INST-REQ-039: the new version replaces the old one in the same line; mode and forge address stay."""
        w = make()
        run(w)
        self.assertEqual(w.files[STATE], rewritten("0.2.0"))
        data = json.loads(w.files[STATE])
        self.assertEqual((data["mode"], data["forge_address"], data["schema_version"]), ("github", "forge.example", 1))
        self.assertEqual(w.regs[(r"Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner", "DisplayVersion")], "0.2.0")
        self.assertLess(w.events.index("write installer-state.json"), w.events.index("entry"))

    def test_the_state_file_is_not_written_when_the_update_is_restored_039(self):
        for w in (make(fail=("swap",)), make(service=Service(start_scripts=(("RUNNING",) * 4 + ("STOPPED",), ("RUNNING",))))):
            run(w)
            self.assertNotIn("write installer-state.json", w.events)

    def test_a_missing_service_is_created_before_the_start_040(self):
        w = make(service=Service(exists=False, state="STOPPED"))
        n, end = run(w)
        self.assertEqual(w.created, 1)
        self.assertEqual((end, w.files[RUNNER]), ("done", "new-runner"))

    def test_a_local_install_has_no_service_to_stop_and_only_its_state_is_updated_034(self):
        w = make(service=Service(exists=False), files={R + "\\runner-mode.json": '{"mode": "local"}\r\n'})
        del w.files[RUNNER]
        n, end = run(w)
        self.assertEqual(steps(w, "stop", "start", "query", "backup-copy", "swap"), [])
        self.assertEqual(w.files[STATE], rewritten("0.2.0"))

    def test_an_interactive_update_asks_once_and_declining_changes_nothing_040(self):
        w = make(silent=False)
        run(w)
        self.assertEqual(len(w.boxes), 1)
        self.assertIn("0.1.0", w.boxes[0])
        w = make(silent=False, answer="IDNO")
        before = dict(w.files)
        n, end = run(w)
        self.assertEqual((end, w.errorlevel, w.files), ("quit", 43, before))
        self.assertNotIn("stop", w.events)

    def test_the_confirmation_is_a_yes_no_box_that_answers_yes_when_silent_040(self):
        self.assertRegex(UPDATE, r"MessageBox MB_YESNO[^\n]*/SD IDYES")

    def test_a_silent_update_never_asks_040(self):
        w = make(silent=True, answer="IDNO")
        run(w)
        self.assertEqual((w.boxes, w.files[RUNNER]), ([], "new-runner"))


class Repair(unittest.TestCase):
    def test_a_repair_with_nothing_wrong_ends_in_the_same_state_when_run_twice_042(self):
        """INST-REQ-042: idempotent. The program file is always rewritten (SetOverwrite try), the end state does not change."""
        w = make("0.2.0", files={RUNNER: "new-runner"})
        n, end = run(w)
        self.assertEqual(end, "done")
        w2 = make("0.2.0", files={RUNNER: "new-runner"})
        run(w2)
        self.assertEqual(w.files, w2.files)
        self.assertEqual(w.files[RUNNER], "new-runner")

    def test_a_repair_rewrites_a_damaged_or_missing_program_file_042(self):
        for files in ({RUNNER: "tampered"}, {}):
            w = make("0.2.0", files=files)
            if not files:
                del w.files[RUNNER]
                w.files[R + "\\runner-mode.json"] = '{"mode": "github"}\r\n'
            run(w)
            self.assertEqual(w.files[RUNNER], "new-runner")
            self.assertEqual(steps(w, "stop", "swap", "start")[:3], ["stop", "swap", "start"])

    def test_a_repair_recreates_a_missing_service_and_the_uninstall_entry_042(self):
        w = make("0.2.0", service=Service(exists=False, state="STOPPED"), files={RUNNER: "new-runner"})
        del w.files[R + "\\uninstall.exe"]
        n, end = run(w)
        self.assertEqual((end, w.created), ("done", 1))
        self.assertEqual(w.files[R + "\\uninstall.exe"], "uninstaller")
        self.assertIn((r"Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner", "UninstallString"), w.regs)

    def test_a_repair_never_creates_a_key_and_never_registers_083(self):
        """INST-REQ-042: a missing key or registration stays missing; the repair writes only its own files."""
        w = make("0.2.0", files={RUNNER: "tampered"})
        before = dict(w.files)
        run(w)
        changed = {k for k in set(w.files) | set(before) if w.files.get(k) != before.get(k) and not k.endswith("\\.dir")}
        self.assertEqual(changed - {STATE}, {RUNNER, R + "\\uninstall.exe"} - ({R + "\\uninstall.exe"} if before[R + "\\uninstall.exe"] == "uninstaller" else set()))
        self.assertFalse([f for f in w.files if "\\keys\\" in f and f != R + "\\keys\\placeholder.txt"])
        self.assertNotIn("Runner_SetGithub", UPDATE)
        self.assertNotIn("Runner_SetGitlab", UPDATE)

    def test_a_repair_rewrites_the_state_file_unchanged_and_shows_no_box_042(self):
        w = make("0.2.0", files={RUNNER: "new-runner"}, silent=False)
        run(w)
        self.assertEqual(w.files[STATE], rewritten("0.2.0"))
        self.assertEqual(w.boxes, [])

    def test_a_repair_with_a_service_that_will_not_stop_changes_nothing_43_042(self):
        w = make("0.2.0", service=Service(stop_script=("STOP_PENDING",)), files={RUNNER: "tampered"})
        n, end = run(w)
        self.assertEqual((end, w.errorlevel, w.files[RUNNER]), ("quit", 43, "tampered"))

    def test_a_service_that_does_not_run_after_a_repair_exits_43_042(self):
        w = make("0.2.0", service=Service(start_scripts=(("STOPPED",),)), files={RUNNER: "tampered"})
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("quit", 43))
        self.assertIn("repair-health", [s[0] for s in w.steps])


class PhaseTwo(unittest.TestCase):
    """The REV101 fix round: B1 SetOverwrite try, B2 backup retention, B3 state file, B4 no bare Abort, the mode page."""

    def test_the_swap_uses_setoverwrite_try_and_never_on_or_ifdiff_b1(self):
        swap = UPDATE[UPDATE.index("Function Update_Swap"):]
        swap = swap[:swap.index("FunctionEnd")]
        self.assertIn("SetOverwrite try", swap)
        self.assertNotRegex(UPDATE, r"SetOverwrite\s+(on|ifdiff)")

    def test_a_failed_program_write_restores_and_exits_42_without_the_abort_box_b1(self):
        w = make(fail=("swap",))
        run(w)
        self.assertNotIn("abort-box", w.events)
        self.assertEqual((w.errorlevel, w.files[RUNNER]), (42, "old-runner"))
        w = make("0.2.0", files={RUNNER: "tampered"}, fail=("swap",))
        n, end = run(w)
        self.assertNotIn("abort-box", w.events)
        self.assertEqual((end, w.errorlevel), ("quit", 43))

    def test_the_interpreter_models_the_silent_abort_of_on_and_ifdiff_b1(self):
        from tests.nsis_interp import Program, source_text
        for mode in ("on", "ifdiff"):
            files = source_text()
            files["update.nsh"] = files["update.nsh"].replace("SetOverwrite try", "SetOverwrite " + mode)
            w = make(fail=("swap",))
            w.program = Program(files=files, defines={"RUNNER_PAYLOAD"}, version="0.2.0")
            run(w)
            with self.subTest(mode=mode):
                self.assertIn("abort-box", w.events)
                self.assertEqual(w.errorlevel, 2)

    def test_the_backup_is_removed_after_a_successful_update_and_kept_after_a_failed_restore_b2(self):
        w = make()
        run(w)
        self.assertFalse(any(f.startswith(R + "\\backup") for f in w.files))
        w = make(fail=("swap", "restore"))
        run(w)
        self.assertTrue(any(f.startswith(R + "\\backup\\program") for f in w.files))

    def test_a_backup_holding_a_program_is_restored_first_and_never_deleted_b2(self):
        old = {R + "\\backup\\program\\runner.exe": "good-old", R + "\\backup\\service.json": '{"name": "EcosystemRunner"}',
               R + "\\backup\\complete": ""}  # SL-23b part B: only a finished backup (marker) is restored
        w = make(files=old)
        n, end = run(w)
        self.assertEqual((end, w.files[RUNNER]), ("done", "new-runner"))
        self.assertLess(w.events.index("restore-copy"), w.events.index("backup-copy"))
        self.assertFalse(any(f.startswith(R + "\\backup") for f in w.files))
        w = make(files=old, fail=("restore",))
        before = {k: v for k, v in w.files.items() if k.startswith(R + "\\backup")}
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("quit", 44))
        self.assertEqual({k: v for k, v in w.files.items() if k.startswith(R + "\\backup")}, before)
        self.assertNotIn("backup-copy", w.events)

    def test_a_backup_without_a_program_is_deleted_as_before_b2(self):
        w = make(files={R + "\\backup\\service.json": "{}", R + "\\backup\\stray.txt": "x"})
        n, end = run(w)
        self.assertEqual(end, "done")
        self.assertFalse(any(f.startswith(R + "\\backup") for f in w.files))

    def test_the_schema_needle_must_end_at_a_comma_or_a_brace_b3(self):
        for text in ('{"schema_version": 12, "installer_version": "0.1.0"}\r\n', '{"schema_version": 1x}\r\n'):
            w = make(files={STATE: text})
            n, end = run(w)
            with self.subTest(text=text):
                self.assertEqual((end, w.errorlevel), ("quit", 45))
        for text in ('{"installer_version": "0.1.0", "schema_version": 1}\r\n', '{"schema_version": 1, "installer_version": "0.1.0"}\r\n'):
            w = make(files={STATE: text})
            n, end = run(w, "Update_Detect")
            self.assertEqual((end, n.v["upd_mode"]), ("done", "update"))

    def test_a_first_line_of_1023_characters_or_more_is_refused_and_left_unchanged_b3(self):
        head = '{"schema_version": 1, "installer_version": "0.1.0", "forge_address": "'
        for size in (1023, 1500):
            text = head + "x" * (size - len(head) - 3) + '"}'
            self.assertGreaterEqual(len(text), 1023 - 1)
            w = make(files={STATE: text + "\r\n"})
            before = dict(w.files)
            n, end = run(w)
            with self.subTest(size=size):
                self.assertEqual((end, w.errorlevel, w.files), ("quit", 45, before))

    def test_a_long_but_complete_line_is_written_back_whole_never_truncated_b3(self):
        addr = "forge.example/" + "a" * 900
        text = '{"forge_address": "%s", "installer_version": "0.1.0", "mode": "github", "schema_version": 1}\r\n' % addr
        self.assertLess(len(text), 1023)
        w = make(files={STATE: text})
        run(w)
        self.assertEqual(json.loads(w.files[STATE])["forge_address"], addr)
        self.assertEqual(json.loads(w.files[STATE])["installer_version"], "0.2.0")

    def test_the_state_file_content_equals_what_the_python_model_writes_b3(self):
        from installer import update
        for fields in (("github", "forge.example"), ("local", None), (None, None)):
            parts = ['"installer_version": "0.1.0"', '"schema_version": 1']
            if fields[0]:
                parts.insert(1, '"mode": "%s"' % fields[0])
            if fields[1]:
                parts.insert(0, '"forge_address": "%s"' % fields[1])
            w = make(files={STATE: "{" + ", ".join(parts) + "}\r\n"})
            run(w)
            with tempfile.TemporaryDirectory() as d:
                update.write_state(d, "0.2.0", *fields)
                expected = (Path(d) / update.STATE_FILE).read_text(encoding="utf-8")
            with self.subTest(fields=fields):
                self.assertEqual(w.files[STATE], expected)

    def test_a_state_open_failure_exits_49_with_a_logged_step_b4(self):
        w = make(fail=("state",))
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("quit", 49))
        self.assertIn("state-file", [s[0] for s in w.steps])

    def test_there_is_no_bare_abort_in_update_nsh_b4(self):
        self.assertNotRegex(re.sub(r"Function Page_mode_Pre.*?FunctionEnd", "", UPDATE, flags=re.S), r"(?m)^\s*Abort\b")

    def test_the_interactive_failure_boxes_answer_themselves_b4(self):
        w = make(fail=("state",), silent=False)
        run(w)
        self.assertEqual(len(w.boxes), 2)
        self.assertIn("state file could not be written", w.boxes[1])

    def test_an_update_or_repair_skips_the_mode_page_and_a_fresh_install_shows_it(self):
        for mode, end, events in (("update", "abort", []), ("repair", "abort", []), ("fresh", "done", ["mode-page"]), ("newer", "done", ["mode-page"])):
            w = make(silent=False)
            w.var["upd_mode"] = mode
            n, got = run(w, "Page_mode_Pre")
            with self.subTest(mode=mode):
                self.assertEqual((got, w.events), (end, events))

    def test_main_uses_the_pre_wrapper_for_the_first_page_and_includes_update_before_the_pages_b4(self):
        self.assertIn("Page custom Page_mode_Pre Page_mode_Leave", MAIN)
        self.assertLess(MAIN.index('!include "update.nsh"'), MAIN.index("Page custom Page_mode_Pre"))


class StateEscapes(unittest.TestCase):
    """#228: Update_WriteState copies forge_address and mode back verbatim. A value that would not be valid JSON there is refused at detection
    (exit 45, nothing changed); every valid escape is kept, and for what json.dumps writes the new line equals update.write_state."""

    # JSON text (between the quotes) of a damaged file, which a verbatim copy keeps invalid: a lone backslash before the closing quote, unknown
    # or short escapes, raw control characters. The valid escaped quote of row 1 is quote_line.
    BAD = ["a\\", "a\\\\\\", "a\\qb", "a\\Bb", "a\\u12", "a\\u12zz", "a\\x", "a\tb", "a\x01b", "a\x1fb"]

    def state(self, field, raw, installed="0.1.0"):
        """The line update.write_state writes, with the JSON text of `field` replaced by `raw` (json.dumps cannot write the damaged ones)."""
        data = {"schema_version": 1, "installer_version": installed, "mode": "github", "forge_address": "forge.example"}
        data[field] = "@@"
        return json.dumps(data, sort_keys=True).replace('"@@"', '"forge.example/%s"' % raw) + "\n"

    def check_refused(self, line, entry="Update_Route", program=None):
        w = make(files={STATE: line}, silent=False)
        if program is not None:
            w.program = program
        before = dict(w.files)
        n, end = run(w, entry)
        self.assertEqual((end, w.errorlevel, w.events), ("quit", 45, []))
        self.assertEqual(w.files, before)
        self.assertEqual(w.boxes, ["The installer state file is damaged; nothing was changed."])

    def quote_line(self, field, slashes=0, installed="0.1.0"):
        """Row 1 of #228: the Python value forge.example/a"b (with 0, 1 or 2 backslashes before the quote), written as update.write_state does."""
        data = {"schema_version": 1, "installer_version": installed, "mode": "github", "forge_address": "forge.example"}
        data[field] = "forge.example/a" + "\\" * slashes + '"b'
        return json.dumps(data, sort_keys=True) + "\n"

    def test_quote_row_is_refused_before_any_change_228(self):
        for field in ("forge_address", "mode"):
            for slashes in (0, 1, 2):
                for installed in ("0.1.0", "0.2.0"):
                    for entry in ("Update_Detect", "Update_Route"):
                        with self.subTest(field=field, slashes=slashes, installed=installed, entry=entry):
                            self.check_refused(self.quote_line(field, slashes, installed), entry)

    def test_values_that_would_copy_into_invalid_json_are_refused_before_any_change_228(self):
        for field in ("forge_address", "mode"):
            for raw in self.BAD:
                for entry in ("Update_Detect", "Update_Route"):
                    with self.subTest(field=field, raw=raw, entry=entry):
                        line = self.state(field, raw)
                        with self.assertRaises(ValueError):
                            json.loads(line)
                        self.check_refused(line, entry)

    def test_valid_escapes_are_copied_back_unchanged_228(self):
        for field in ("forge_address", "mode"):
            for raw in ("\\\\", "\\/", "\\b\\f\\n\\r\\t", "\\u00e9\\u00E9\\uD83D\\ude00", "a\\\\\\u0041", ""):
                with self.subTest(field=field, raw=raw):
                    line = self.state(field, raw)
                    w = make(files={STATE: line})
                    n, end = run(w)
                    self.assertEqual((end, w.errorlevel), ("done", None))
                    self.assertEqual(w.files[STATE], line.replace('"0.1.0"', '"0.2.0"'))
                    self.assertEqual(json.loads(w.files[STATE])[field], json.loads(line)[field])

    def test_other_rows_equal_the_python_state_writer_228(self):
        """Rows 2 and 3 of #228, and more values json.dumps writes with escapes: the NSIS line is byte for byte update.write_state."""
        from installer import update
        for address in ("forge.example\\x", "forge.example/\u00e9", "forge.example\\", "forge.example\\\\", "a\tb\x01", "/\U0001f600", ""):
            for installed in ("0.1.0", "0.2.0"):
                with self.subTest(address=address, installed=installed):
                    data = {"schema_version": 1, "installer_version": installed, "mode": "github", "forge_address": address}
                    w = make(files={STATE: json.dumps(data, sort_keys=True) + "\n"})
                    n, end = run(w)
                    self.assertEqual((end, w.errorlevel), ("done", None))
                    self.assertEqual(json.loads(w.files[STATE])["forge_address"], address)
                    with tempfile.TemporaryDirectory() as d:
                        update.write_state(d, "0.2.0", "github", address)
                        expected = (Path(d) / update.STATE_FILE).read_bytes()
                    self.assertEqual(w.files[STATE].encode("utf-8"), expected)

    def test_mutant_without_the_refusals_fails_the_refusal_tests_228(self):
        """Mutant: drop the two new refusals in Update_ReadState. The quote row and every BAD value then fail check_refused, because the
        update runs and writes a state file that json.loads rejects."""
        files = source_text()
        check = '  StrCmp $upd_ok "0" state_bad\n'
        self.assertEqual(files["update.nsh"].count(check), 2)
        files["update.nsh"] = files["update.nsh"].replace(check, "")
        program = Program(files=files, defines={"RUNNER_PAYLOAD"}, version="0.2.0")
        lines = [self.quote_line(f) for f in ("forge_address", "mode")] + [self.state(f, r) for f in ("forge_address", "mode") for r in self.BAD]
        for line in lines:
            with self.subTest(line=line):
                with self.assertRaises(AssertionError):
                    self.check_refused(line, program=program)
                w = make(files={STATE: line})
                w.program = program
                n, end = run(w)
                self.assertEqual(end, "done")
                with self.assertRaises(ValueError):
                    json.loads(w.files[STATE])

    def test_mutant_that_accepts_any_escape_fails_the_escape_rows_228(self):
        """Mutant: Update_OneOf never refuses (a check of the last backslashes only). Unknown escapes, short \\u escapes and a lone backslash
        before the closing quote then pass detection and are copied into invalid JSON."""
        files = source_text()
        refusal = "  oneof_bad:\n  StrCpy $upd_ok 0\n"
        self.assertEqual(files["update.nsh"].count(refusal), 1)
        files["update.nsh"] = files["update.nsh"].replace(refusal, "  oneof_bad:\n")
        program = Program(files=files, defines={"RUNNER_PAYLOAD"}, version="0.2.0")
        for raw in ("a\\qb", "a\\Bb", "a\\u12zz", "a\\"):
            with self.subTest(raw=raw):
                with self.assertRaises(AssertionError):
                    self.check_refused(self.state("forge_address", raw), program=program)


class Wiring(unittest.TestCase):
    def test_main_calls_the_detection_once_after_the_silent_gate_and_routes_the_section(self):
        init = MAIN[MAIN.index("Function .onInit"):MAIN.index("FunctionEnd", MAIN.index("Function .onInit"))]
        calls = [l.strip() for l in init.splitlines() if l.strip().startswith("Call ")]
        self.assertEqual(calls, ["Call Log_InitPaths", "Call Carried_Detect", "Call Mode_FromSilent", "Call Licence_SilentGate", "Call TrustCheck", "Call Elevate_SilentGate", "Call Update_Detect", "Call Runner_GitlabInstallGate"])
        self.assertEqual(MAIN.count("Call Update_Detect"), 1)
        self.assertIn("Section\n  Call Update_Route\nSectionEnd", MAIN)
        self.assertNotIn("Install_Footprint", MAIN)

    def test_exit_codes_are_registered_unique_and_used_by_the_code_041(self):
        codes = footprint.load_footprint()["exit_codes"]
        self.assertEqual({k: codes[k] for k in ("major-version-mismatch", "update-restored", "update-not-applied", "restore-failed", "state-invalid")},
                         {"major-version-mismatch": 41, "update-restored": 42, "update-not-applied": 43, "restore-failed": 44, "state-invalid": 45})
        self.assertEqual(len(set(codes.values())), len(codes))
        used = {int(c) for c in re.findall(r"StrCpy \$upd_code (\d+)", UPDATE)}
        self.assertEqual(used, {41, 42, 43, 44, 45})

    def test_the_old_unused_functions_are_gone_and_the_header_is_corrected(self):
        self.assertNotIn("Update_CheckMajor", UPDATE)
        self.assertNotIn("the swap itself runs in that logic", UPDATE)
        self.assertIn("authoritative", UPDATE.splitlines()[0])

    def test_every_messagebox_answers_itself_under_silent_mode(self):
        for n, line in enumerate(UPDATE.splitlines() + WINSYS.splitlines()):
            if line.strip().startswith("MessageBox"):
                self.assertIn("/SD", line, line)

    def test_the_health_check_constants_match_the_python_model(self):
        from installer import update
        self.assertEqual(update.HEALTH_SECONDS, 30)
        self.assertEqual(update.RESTORED, "previous program files restored")
        self.assertIn("IntCmp" if False else "$1 < 30", WINSYS)
        for name in (update.PROGRAM, update.BACKUP, update.SERVICE_FILE, update.STATE_FILE):
            self.assertIn(name, UPDATE)

    def test_the_forge_online_check_is_a_documented_stub_040(self):
        body = UPDATE[UPDATE.index("Function Update_RunnerOnline"):]
        body = body[:body.index("FunctionEnd")]
        self.assertIn("not-checked", body)
        self.assertNotIn("nsExec", body)
        self.assertIn("Update_RunnerOnline", README)
        self.assertIn("INST-REQ-040", README[README.index("Update_RunnerOnline") - 600:README.index("Update_RunnerOnline") + 600])

    def test_the_footprint_scan_accepts_the_new_code(self):
        sources = footprint.collect_sources()
        self.assertEqual(footprint.check_source(sources), [])

    def test_the_footprint_command_check_passes(self):
        self.assertEqual(subprocess.run(["python3", "-m", "installer.footprint", "check"], cwd=REPO, capture_output=True).returncode, 0)


@unittest.skipUnless(shutil.which("makensis"), "makensis not installed")
class RealCompile(unittest.TestCase):
    def _compile(self, *defines):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "p.bin").write_bytes(b"stub-runner")
        d = [x.replace("PAYLOAD_FILE", str(tmp / "p.bin")) for x in defines]
        return subprocess.run(["makensis", "-V2", "-WX", "-INPUTCHARSET", "UTF8", *d, "-DOUTFILE=%s" % (tmp / "o.exe"), str(NSIS / "main.nsi")],
                              capture_output=True, text=True, cwd=REPO)

    def test_the_final_script_compiles_without_warnings_with_and_without_a_payload_040(self):
        r = self._compile()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self._compile("-DRUNNER_PAYLOAD=PAYLOAD_FILE", "-DRUNNER_TEST_BUILD=1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Docs(unittest.TestCase):
    def test_the_readme_has_the_sl19_section_and_no_longer_says_a_rerun_fails_042(self):
        self.assertIn("SL-19", README)
        self.assertNotIn("a re-run while the service runs fails at the payload write", README)
        for token in ("41", "42", "43", "44", "45", "INST-TC-032", "INST-TC-037"):
            self.assertIn(token, README[README.index("SL-19"):])


class TransientLock(unittest.TestCase):
    """Fix round C: a just-stopped service can leave runner.exe mapped for a moment; the swap and the restore retry (1, 2, 4, 8, 8 s)."""

    def retries(self, w, name="update-swap-retry"):
        return [x for x in w.log if x[0] == name]

    def test_no_failure_no_wait(self):
        w = make()
        run(w)
        self.assertEqual((self.retries(w), w.errorlevel), ([], None))
        self.assertEqual(w.swap_waits, [])

    def test_transient_failures_wait_one_two_four_eight_eight(self):
        for n, waits in ((1, [1000]), (3, [1000, 2000, 4000]), (5, [1000, 2000, 4000, 8000, 8000])):
            w = make(swap_failures=n)
            run(w)
            with self.subTest(n=n):
                self.assertEqual(w.files[RUNNER], "new-runner")
                self.assertEqual(len(self.retries(w)), n)
                self.assertEqual(w.swap_waits, waits)
                self.assertIsNone(w.errorlevel)

    def test_six_failures_restore_and_exit_42_with_five_waits(self):
        w = make(swap_failures=6)
        run(w)
        self.assertEqual((w.errorlevel, w.files[RUNNER], len(self.retries(w))), (42, "old-runner", 5))
        self.assertEqual(w.swap_waits, [1000, 2000, 4000, 8000, 8000])

    def test_six_failures_in_repair_exit_43(self):
        w = make("0.2.0", files={RUNNER: "tampered"}, swap_failures=6)
        n, end = run(w)
        self.assertEqual((end, w.errorlevel, len(self.retries(w))), ("quit", 43, 5))

    def test_the_counter_starts_again_for_the_restore(self):
        w = make(swap_failures=6, restore_failures=2)
        run(w)
        self.assertEqual((w.errorlevel, w.files[RUNNER], len(self.retries(w, "update-restore-retry"))), (42, "old-runner", 2))

    def test_a_restore_that_keeps_failing_exits_44(self):
        for kw in ({"fail": ("swap", "restore")}, {"fail": ("swap",), "restore_failures": 9}):
            w = make(**kw)
            run(w)
            with self.subTest(kw=kw):
                self.assertEqual(w.errorlevel, 44)
                self.assertEqual(len(self.retries(w, "update-restore-retry")), 5)
                self.assertEqual(w.sleeps[-5:], [1000, 2000, 4000, 8000, 8000])

    def test_a_retry_is_logged_without_a_value(self):
        w = make(swap_failures=2)
        run(w)
        self.assertEqual(self.retries(w), [("update-swap-retry", "swap program file", "0")] * 2)
        self.assertNotIn("new-runner", repr(w.log))


class GapWorld(World):
    """The update world with the pinned image table, a licence that was accepted, an engine in its fixed place and a scripted record write."""
    def native_LogUtcNow(self):
        self.var.update({"LogY": "2026", "LogMo": "11", "LogD": "22", "LogH": "07", "LogMi": "05", "LogS": "09"})

    def step(self, t, labels):
        if t[0].lower() == "filewrite" and "write" in self.fail and self.fh[self.var[t[1].lstrip("$")]]["path"] == RECORD:
            self.errors = True
            return None
        return super().step(t, labels)

    def fileopen(self, var, path, mode):
        if path == RECORD and "record" in self.fail:
            self.errors = True
            return
        if path == RECORD:
            self.events.append("record")
        super().fileopen(var, path, mode)


def gap(installed="0.1.0", licence=True, record=True, **kw):
    """A real update or repair finds the record its first install wrote; record=False is an install made before the record existed."""
    files = {RUNNER: "old-runner", STATE: state_line(installed), DESKTOP: "engine", **KEPT}
    if record:
        files[RECORD] = "{}"
    files.update(kw.pop("files", {}))
    w = GapWorld(files=files, service=Service(), **kw)
    sources = source_text()
    sources["screens.nsh"] = S.generate_nsh(pinned_schema())
    w.program = Program(files=sources, defines={"RUNNER_PAYLOAD"}, version="0.2.0")
    if licence:
        ready(w)
    return w


class RepairGap(unittest.TestCase):
    """REV107 A4: an updated or repaired install gets the licence record and the pinned image, in the order of a first install, at the very end."""

    def order(self, w):
        return [e for e in w.events if e in ("swap", "start", "record", "pull", "restore-copy")]

    def test_update_writes_the_record_then_pulls_after_the_swap_and_not_before(self):
        w = gap()
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("done", None))
        self.assertEqual(self.order(w), ["swap", "start", "record", "pull"])
        self.assertEqual(w.events.count("record"), 1)
        self.assertEqual(len(w.pulls), 1)
        self.assertEqual(w.files[RUNNER], "new-runner")
        self.assertEqual(w.files[STATE], rewritten("0.2.0"))

    def test_repair_writes_the_record_then_pulls(self):
        w = gap("0.2.0", files={RUNNER: "tampered"})
        n, end = run(w)
        self.assertEqual((end, w.errorlevel), ("done", None))
        self.assertEqual(self.order(w), ["swap", "start", "record", "pull"])
        self.assertEqual(len(w.pulls), 1)

    def test_an_install_without_a_record_gets_it_written_and_then_pulls_on_both_routes(self):
        for installed, files in (("0.1.0", {}), ("0.2.0", {RUNNER: "tampered"})):
            w = gap(installed, files=files, record=False)
            n, end = run(w)
            with self.subTest(installed=installed):
                self.assertEqual((end, w.errorlevel), ("done", None))
                self.assertEqual(self.order(w), ["swap", "start", "record", "pull"])
                self.assertIn(RECORD, w.files)
                self.assertEqual(w.pulls, ['"%s" pull %s' % (DESKTOP, self.pinned_reference())])

    def pinned_reference(self, variant="linux", year="2024"):
        e = next(e for e in pinned_schema()["images"]["list"] if (e["variant"], e["year"]) == (variant, year))
        return image.reference(e["repository"], e["digest"])

    def test_a_restore_path_calls_neither(self):
        for kw in ({"fail": ("swap",)}, {"swap_failures": 6}):
            w = gap(**kw)
            n, end = run(w)
            with self.subTest(kw=kw):
                self.assertEqual(w.errorlevel, 42)
                self.assertEqual((w.pulls, w.events.count("record"), w.files[RECORD]), ([], 0, "{}"))

    def test_a_declined_or_stopped_run_calls_neither(self):
        w = gap(silent=False, answer="IDNO")
        run(w)
        self.assertEqual((w.errorlevel, w.pulls, w.events.count("record")), (43, [], 0))

    def test_a_pull_failure_exits_46_and_keeps_the_updated_program(self):
        for installed, files, expect in (("0.1.0", {}, "new-runner"), ("0.2.0", {RUNNER: "tampered"}, "new-runner")):
            w = gap(installed, files=files, pull_code=1)
            n, end = run(w)
            with self.subTest(installed=installed):
                self.assertEqual((end, w.errorlevel), ("quit", 46))
                self.assertEqual(w.files[RUNNER], expect)
                self.assertNotIn("restore-copy", w.events)
                self.assertEqual(w.events.count("record"), 1)
                self.assertEqual(w.files[STATE], rewritten("0.2.0"))
                self.assertIn(("image-pull", "pull", "46"), w.log)

    def test_a_record_failure_exits_37_and_pulls_nothing(self):
        for installed, files in (("0.1.0", {}), ("0.2.0", {RUNNER: "tampered"})):
            w = gap(installed, files=files, fail=("record",))
            n, end = run(w)
            with self.subTest(installed=installed):
                self.assertEqual((end, w.errorlevel, w.pulls), ("abort", 37, []))
                self.assertEqual(w.files[RUNNER], "new-runner")
                self.assertIn(("licence-record", "FileOpen licence-record.json", "37"), w.log)

    def test_a_record_write_failure_exits_37_not_46_and_pulls_nothing_on_both_routes(self):
        for installed, files in (("0.1.0", {}), ("0.2.0", {RUNNER: "tampered"})):
            for record in (True, False):
                w = gap(installed, files=files, fail=("write",), record=record)
                n, end = run(w)
                with self.subTest(installed=installed, record=record):
                    self.assertEqual((end, w.errorlevel, w.pulls), ("abort", 37, []))
                    self.assertIn(("licence-record", "FileWrite licence-record.json", "37"), w.log)
                    self.assertNotIn(RECORD, w.files)

    def test_without_an_accepted_licence_nothing_is_written_or_pulled(self):
        for installed, files in (("0.1.0", {}), ("0.2.0", {RUNNER: "tampered"})):
            w = gap(installed, files=files, licence=False)
            n, end = run(w)
            with self.subTest(installed=installed):
                self.assertEqual((end, w.errorlevel, w.pulls, w.events.count("record")), ("done", None, [], 0))

    def test_both_paths_end_with_the_two_calls_and_hold_no_register_the_calls_clobber(self):
        for name in ("Update_Apply", "Update_Repair"):
            body = UPDATE[UPDATE.index("Function " + name):]
            body = body[:body.index("FunctionEnd")]
            with self.subTest(name=name):
                self.assertTrue(body.rstrip().endswith("Call Licence_WriteRecord\n  Call Image_Pull"), name)
                self.assertEqual(body.count("Call Licence_WriteRecord"), 1)
                self.assertEqual(body.count("Call Image_Pull"), 1)
                self.assertNotRegex(body, r"\$(R[0-9]|ImgEngine|ImgRef)\b")

    def test_the_swap_and_restore_counters_are_finished_before_the_calls(self):
        for name in ("Update_Swap", "Update_RestoreFiles"):
            body = UPDATE[UPDATE.index("Function " + name):]
            body = body[:body.index("FunctionEnd")]
            self.assertNotIn("Image_Pull", body)
            self.assertNotIn("Licence_WriteRecord", body)

    def test_the_pull_and_record_run_once_per_update_even_after_swap_retries(self):
        w = gap(swap_failures=2)
        run(w)
        self.assertEqual((len(w.pulls), w.events.count("record"), w.errorlevel), (1, 1, None))


if __name__ == "__main__":
    unittest.main()
