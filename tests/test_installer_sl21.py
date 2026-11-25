"""SL-21a (ecosystem-control#111, problems 1 and 3): declining the Windows administrator prompt keeps the installer open.
INST-REQ-028, 029. Elevate_Raise clears the error flag, raises the prompt once, and quits only when the hand-over worked; a decline
shows one message and Page_elevation_Leave aborts, so the user stays on the page. No Windows, no network: the test interpreter
runs the real text of elevate.nsh and ExecShell failure is scripted with World(shell_fails=True).
SL-21b (#117) changed the string that is handed over (the typed answers cross, the parent's own words do not: tests/test_installer_sl21b.py)
and dropped the dead decline variable and its check (REV116 NIT 3); IfNoErrors is not an NSIS instruction and is gone (NIT 2)."""
import unittest

from tests.nsis_interp import NSIS, World, Program, source_text

ELEVATE = (NSIS / "elevate.nsh").read_text()
CHILD = "/ELEVATED"
DECLINED_BOX = '  MessageBox MB_OK|MB_ICONEXCLAMATION "The installation needs administrator rights'


def program(old=None, new=None):
    files = source_text()
    if old is not None:
        assert files["elevate.nsh"].count(old) == 1, old
        files["elevate.nsh"] = files["elevate.nsh"].replace(old, new)
    return Program(files)


def leave(prog=None, **kw):
    w = World(admin=kw.pop("admin", False), program=prog, **kw)
    return w, w.run("Page_elevation_Leave")


def checks(prog=None, world=World):
    """Every behaviour the brief names; raises AssertionError on the first one that does not hold."""
    def mk(**kw):
        w = world(admin=kw.pop("admin", False), program=prog, **kw)
        return w

    w = mk(cmdline="/S /MODE=local", shell_fails=True)
    code = w.run("Page_elevation_Leave")
    assert code == "abort", "declined: Page_elevation_Leave must Abort, got %r" % (code,)
    assert len(w.boxes) == 1, "declined: exactly one message box, got %r" % (w.boxes,)
    assert "administrator" in w.boxes[0] and "NOT started" in w.boxes[0] and "Next" in w.boxes[0] and "Cancel" in w.boxes[0]
    assert len(w.shell) == 1 and w.exit_code == 0 and w.quit_code is None

    w = mk(cmdline="/S /MODE=local")
    code = w.run("Page_elevation_Leave")
    assert code == 0 and w.boxes == [] and len(w.shell) == 1, "succeeded: Quit, no box (%r, %r)" % (code, w.boxes)

    w = mk(cmdline="/S /MODE=local")
    w.errors = True
    code = w.run("Page_elevation_Leave")
    assert code == 0 and w.boxes == [], "a stale error flag must not make a successful hand-over look declined"

    w = mk(cmdline="/S /MODE=local", shell_fails=True)
    assert w.run("Page_elevation_Leave") == "abort"
    w.var["in_install_dir"] = "C:\\Program Files\\x"
    w.shell_fails = False
    code = w.run("Page_elevation_Leave")
    assert code == 0 and len(w.shell) == 2 and len(w.boxes) == 1, "Next again raises the prompt again, a success quits"
    assert w.shell[1][2] == CHILD + ' /INSTALL_DIR="C:\\Program Files\\x"', "the retry builds the string again, from nothing: %r" % (w.shell[1][2],)

    w = mk(cmdline="/S", admin=True)
    assert w.run("Page_elevation_Leave") is None and w.shell == [] and w.boxes == []

    w = mk(cmdline="/S /MODE=local")
    w.run("Elevate_Raise")
    (verb, file, text), = w.shell
    assert verb == "runas" and text == CHILD and "setup.exe" not in text
    w = mk(cmdline="/S /MODE=local", exe='"C:\\a b\\setup.exe"')
    w.run("Elevate_Raise")
    assert w.shell[0][2] == CHILD


class Declined(unittest.TestCase):
    def test_the_page_stays_with_one_message_and_no_quit(self):
        w, code = leave(cmdline="/S /MODE=local", shell_fails=True)
        self.assertEqual(code, "abort")
        self.assertEqual(len(w.boxes), 1)
        self.assertIn("needs administrator rights and has NOT started", w.boxes[0])
        self.assertIn("Next", w.boxes[0])
        self.assertIn("Cancel", w.boxes[0])
        self.assertTrue(w.boxes[0].isascii())
        self.assertEqual(len(w.shell), 1)
        self.assertEqual((w.exit_code, w.quit_code), (0, None))

    def test_next_again_raises_the_prompt_again(self):
        w = World(admin=False, cmdline="/S", shell_fails=True)
        self.assertEqual(w.run("Page_elevation_Leave"), "abort")
        self.assertEqual(w.run("Page_elevation_Leave"), "abort")
        self.assertEqual(len(w.shell), 2)
        w.shell_fails = False
        self.assertEqual(w.run("Page_elevation_Leave"), 0)
        self.assertEqual(len(w.shell), 3)
        self.assertEqual(len(w.boxes), 2)

    def test_a_retry_after_a_decline_hands_over_the_same_string_once(self):
        w = World(admin=False, cmdline="/S", shell_fails=True)
        w.var["in_work_dir"] = "D:\\Work"
        w.run("Page_elevation_Leave")
        w.shell_fails = False
        w.run("Elevate_Raise")
        self.assertEqual(w.shell[0], w.shell[1])
        self.assertEqual(w.shell[1][2], '/ELEVATED /WORK_DIR=D:\\Work')

    def test_the_dead_decline_variable_and_its_check_are_gone(self):
        self.assertNotIn("elev_declined", ELEVATE)


class Succeeded(unittest.TestCase):
    def test_a_successful_hand_over_quits_without_a_message(self):
        w, code = leave(cmdline="/S")
        self.assertEqual(code, 0)
        self.assertEqual(w.boxes, [])
        self.assertEqual(len(w.shell), 1)

    def test_a_stale_error_flag_does_not_look_like_a_decline(self):
        w = World(admin=False, cmdline="/S")
        w.errors = True
        self.assertEqual(w.run("Page_elevation_Leave"), 0)
        self.assertEqual(w.boxes, [])

    def test_already_administrator_aborts_as_before_with_no_prompt(self):
        w, code = leave(admin=True, cmdline="/S")
        self.assertIsNone(code)
        self.assertEqual((w.shell, w.boxes), ([], []))


class ChildParameters(unittest.TestCase):
    def test_the_child_gets_the_elevation_flag_and_never_the_program_path_or_the_parents_own_words(self):
        for exe in ('"C:\\Program Files\\Ecosystem Installer\\setup.exe"', "setup.exe"):
            w = World(admin=False, cmdline="/S /MODE=local /FOO=bar", exe=exe)
            w.run("Elevate_Raise")
            (verb, file, text), = w.shell
            self.assertEqual((verb, file, text), ("runas", exe.strip('"'), CHILD))


class InterpreterFlag(unittest.TestCase):
    def test_execshell_sets_the_flag_only_when_told_to_fail_and_never_clears_it(self):
        p = Program({"x.nsh": 'Function F\n  ExecShell "runas" "x.exe" "/X"\nFunctionEnd\n'})
        w = World(program=p, shell_fails=True)
        w.run("F")
        self.assertTrue(w.errors)
        w = World(program=p)
        w.errors = True
        w.run("F")
        self.assertTrue(w.errors)
        w = World(program=p)
        w.run("F")
        self.assertFalse(w.errors)

    def test_iferrors_clears_the_flag_and_clearerrors_clears_it(self):
        p = Program({"x.nsh": "Function F\n  IfErrors a\n  a:\n  StrCpy $1 x\nFunctionEnd\n"})
        w = World(program=p)
        w.errors = True
        w.run("F")
        self.assertFalse(w.errors)


class SourcePins(unittest.TestCase):
    def test_one_runas_one_caller_and_the_flag_is_cleared_first(self):
        self.assertEqual(ELEVATE.count('ExecShell "runas"'), 1)
        body = ELEVATE.split("Function Elevate_Raise")[1].split("FunctionEnd")[0]
        self.assertLess(body.index("ClearErrors"), body.index("ExecShell"))
        self.assertLess(body.index("ExecShell"), body.index("IfErrors"))
        boxes = [ln for ln in body.splitlines() if "MessageBox" in ln]
        self.assertEqual(len(boxes), 2)
        self.assertTrue(all("/SD IDOK" in ln for ln in boxes), boxes)

    def test_the_declined_box_has_an_icon_and_the_page_aborts_whatever_came_back(self):
        # REV116 NIT 3: MB_OK alone had no icon; Elevate_Raise returns only when nothing was handed over, so the Abort needs no condition
        self.assertEqual(ELEVATE.count(DECLINED_BOX), 1)
        leave = ELEVATE.split("Function Page_elevation_Leave")[1].split("FunctionEnd")[0]
        self.assertIn("    Call Elevate_Raise\n    Abort\n", leave)

    def test_the_silent_gate_is_untouched(self):
        body = ELEVATE.split("Function Elevate_SilentGate")[1].split("FunctionEnd")[0]
        self.assertIn("SetErrorLevel 38", body)
        self.assertNotIn("Elevate_Raise", body)


class Mutants(unittest.TestCase):
    """Each mutant of elevate.nsh (or of the interpreter's ExecShell) must fail at least one behaviour check."""

    def killed(self, old, new):
        with self.assertRaises(AssertionError):
            checks(program(old, new))

    def test_the_real_text_passes_every_check(self):
        checks(program())

    def test_m01_clearerrors_removed(self):
        self.killed("  ClearErrors\n  ExecShell", "  ExecShell")

    def test_m02_iferrors_removed_always_quits(self):
        self.killed("  IfErrors declined\n", "")

    def test_m03_the_decline_path_still_quits(self):
        self.killed("  declined:\n  MessageBox MB_OK", "  declined:\n  Quit\n  MessageBox MB_OK")

    def test_m04_abort_missing_in_page_elevation_leave(self):
        self.killed("    Call Elevate_Raise\n    Abort\n", "    Call Elevate_Raise\n")

    def test_m05_abort_on_the_success_path(self):
        self.killed("  IfErrors declined\n  Quit\n", "  IfErrors declined\n  Abort\n")

    def test_m07_message_box_without_sd(self):
        with self.assertRaises(AssertionError):
            checks_sd(program("Cancel to leave.\" /SD IDOK", "Cancel to leave.\""))
        checks_sd(program())

    def test_m08_message_box_missing(self):
        start = ELEVATE.index(DECLINED_BOX)
        end = ELEVATE.index("\n", start) + 1
        self.killed(ELEVATE[start:end], "")

    def test_m09_the_program_path_is_copied_into_the_parameters(self):
        self.killed('  StrCpy $carry_args ""\n', '  StrCpy $carry_args "$EXEPATH"\n')

    def test_m10_elevated_dropped(self):
        self.killed('  Push "The elevation flag"\n  Push "/ELEVATED"\n  Call Carry_Token\n', "")

    def test_m11_the_admin_test_inverted_in_page_elevation_leave(self):
        self.killed("  ${If} $elev_isadmin == 0\n    Call Elevate_Raise", "  ${If} $elev_isadmin == 1\n    Call Elevate_Raise")

    def test_m12_the_string_is_not_started_again_at_each_raise(self):
        self.killed('  StrCpy $carry_args ""\n', "")

    def test_m13_the_interpreter_execshell_never_sets_the_flag(self):
        class Blind(World):
            def step(self, t, labels):
                r = super().step(t, labels)
                if t[0].lower() == "execshell":
                    self.errors = False
                return r

        with self.assertRaises(AssertionError):
            checks(world=Blind)


def checks_sd(prog):
    """The message box carries /SD IDOK in the source (the silent-safe rule of MessageBoxesAreSilentSafe)."""
    body = [ln for ln in prog.functions["Elevate_Raise"].splitlines() if "MessageBox" in ln]
    assert body and all("/SD IDOK" in ln for ln in body), "a message box without /SD"


if __name__ == "__main__":
    unittest.main()
