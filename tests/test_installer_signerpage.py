"""INST-REQ-103 (ecosystem-control#331 item 10): a window started without /SIGNER= (a double click) asks for the signer fingerprint on the first page.
The real .onInit, Page_signer, Page_signer_Leave and Elevate_Raise run in the test interpreter (tests/nsis_interp.py) over the real script text.
Only a missing or empty /SIGNER= opens the page; a malformed one, a silent run and the elevated copy are refused in .onInit as before (exit 3)."""
import re
import unittest

from installer import trust
from tests.nsis_interp import NSIS, Program, source_text
from tests.test_installer_docfix import LOCAL, ROAMING, STORE, AuditWorld

TRUST = (NSIS / "trust.nsh").read_text(encoding="utf-8")
MAIN = (NSIS / "main.nsi").read_text(encoding="utf-8")
SIGNER = "0123456789abcdef" * 4
OTHER = "fedcba9876543210" * 4
WARNING = "This is an EXPERIMENTAL installer (test build). It is not for production use: run it only where you can undo the changes."
MISSING = ("The signer fingerprint is missing or malformed. Start the installer with /SIGNER= and the 64 hex digits of the published fingerprint."
           " Nothing was started.")
HELP = "Type the signer fingerprint: the 64 hex digits published in the two independent places. Then select Next."
FIELD = "Signer fingerprint (64 hex digits)"
EMPTY = "No signer fingerprint was typed. Type the 64 hex digits of the published fingerprint, then select Next."
LENGTH = "The signer fingerprint has %d characters, not 64. Type the 64 hex digits (0 to 9, a to f) again, then select Next."
NOT_HEX = "The signer fingerprint holds a character that is not a hex digit (0 to 9, a to f). Type it again, then select Next."
FIRST = "First run. The signer fingerprint is:"
CHANGED = "The signer changed."
DAMAGED = "The stored signer file is damaged, so the stored signer cannot be read. Nothing was started."
PAGE_HEIGHT = 130


def func(text, name):
    return re.search(r"^Function %s\n(.*?)^FunctionEnd" % re.escape(name), text, re.M | re.S).group(1)


def program(*edits):
    files = source_text()
    for name, old, new in edits:
        if files[name].count(old) != 1:
            raise ValueError("the mutant anchor must match once: %r in %s" % (old, name))
        files[name] = files[name].replace(old, new)
    return Program(files, defines={"RUNNER_PAYLOAD"}, version="0.2.0")


def window(cmdline="", silent=False, admin=False, stored=None, answer="IDYES", prog=None):
    """A window of the installer, nothing installed, the real TrustCheck; .onInit has run (w.code)."""
    w = AuditWorld(silent=silent, admin=admin, answer=answer, files={STORE: stored} if stored is not None else {})
    if prog is not None:
        w.program = prog
    w.native_TrustCheck = None
    if cmdline:
        w.var["CMDLINE"] += " " + cmdline
    w.code = w.run(".onInit")
    return w


def page(w, typed):
    """The signer page is shown, the fingerprint typed, Next selected: (what the page function did, what its Leave function did)."""
    shown = w.run("Page_signer")
    w.texts["TrustText"] = typed
    return shown, w.run("Page_signer_Leave")


def check_the_typed_signer_reaches_the_elevated_copy(prog=None):
    w = window(prog=prog)
    assert page(w, SIGNER.upper()) == (None, None) and w.files[STORE] == SIGNER + "\n", (w.boxes, w.files)
    w.var.update(in_mode="local", in_install_dir="C:\\x")
    assert w.run("Page_elevation_Leave") == 0 and len(w.shell) == 1, (w.boxes, w.shell)
    handed = w.shell[0][2]
    assert handed == "/SIGNER=%s /ELEVATED /MODE=local /INSTALL_DIR=C:\\x" % SIGNER, handed
    # The elevated copy: the same user, the signer stored by the first window. No box, no exit, the same signer.
    c = window(handed, admin=True, stored=SIGNER + "\n", prog=prog)
    assert (c.code, c.boxes, c.var["carried"], c.var["TrustSigner"], c.var["TrustAsk"]) == (None, [], "1", SIGNER, "0"), (c.code, c.boxes)
    assert c.files[STORE] == SIGNER + "\n"


class OnInit(unittest.TestCase):
    def test_a_double_click_refuses_nothing_and_leaves_the_fingerprint_to_the_page(self):
        for cmdline in ("", "/SIGNER=", '/SIGNER=""'):
            with self.subTest(cmdline=cmdline):
                w = window(cmdline)
                self.assertEqual((w.code, w.errorlevel, w.boxes, w.var["TrustAsk"]), (None, None, [WARNING], "1"))
                self.assertNotIn(STORE, w.files)
                self.assertEqual(w.run("Page_signer"), None)
                self.assertIn("${NSD_CreateText}", w.trace)
                self.assertEqual(w.labels, [HELP, FIELD])

    def test_a_given_valid_signer_skips_the_page_and_is_checked_in_on_init_as_before(self):
        for typed in (SIGNER, SIGNER.upper()):
            w = window("/SIGNER=" + typed)
            self.assertEqual((w.code, len(w.boxes), w.boxes[0], w.var["TrustAsk"]), (None, 2, WARNING, "0"))
            self.assertTrue(w.boxes[1].startswith(FIRST), w.boxes)
            self.assertEqual(w.files[STORE], SIGNER + "\n")
            self.assertEqual(w.run("Page_signer"), "abort")
            self.assertFalse(any(op.startswith(("nsDialogs::", "${NSD_Create")) for op in w.trace), w.trace)
        # No on the box in .onInit ends the run as before: Abort, no exit code set, nothing stored.
        w = window("/SIGNER=" + SIGNER, answer="IDNO")
        self.assertEqual((w.code, w.errorlevel, STORE in w.files), ("abort", None, False))
        # a stored signer: no box but the warning
        w = window("/SIGNER=" + SIGNER, stored=SIGNER + "\n")
        self.assertEqual((w.code, w.boxes), (None, [WARNING]))

    def test_a_given_malformed_signer_is_refused_exactly_as_before(self):
        for typed in ("abc", SIGNER + "a", SIGNER[:-1] + "g"):
            with self.subTest(typed=typed):
                w = window("/SIGNER=" + typed)
                self.assertEqual((w.code, w.errorlevel, w.boxes, w.var["TrustAsk"]), ("abort", 3, [WARNING, MISSING], "0"))
                self.assertNotIn(STORE, w.files)

    def test_a_silent_run_without_a_signer_still_exits_3(self):
        for cmdline in ("/S /MODE=local", "/S /MODE=local /SIGNER="):
            with self.subTest(cmdline=cmdline):
                w = window(cmdline, silent=True, admin=True)
                self.assertEqual((w.code, w.errorlevel, w.boxes, w.var["TrustAsk"]), ("abort", 3, [], "0"))
                self.assertNotIn(STORE, w.files)

    def test_the_elevated_copy_without_a_signer_still_exits_3(self):
        w = window("/ELEVATED /MODE=local /INSTALL_DIR=C:\\x", admin=True)
        self.assertEqual((w.code, w.errorlevel, w.boxes, w.var["carried"], w.var["TrustAsk"]), ("abort", 3, [MISSING], "1", "0"))
        self.assertNotIn(STORE, w.files)
        self.assertEqual(w.run("Page_signer"), "abort")


class Page(unittest.TestCase):
    def test_a_malformed_fingerprint_keeps_the_page_with_a_box_that_names_the_problem(self):
        for typed, box in (("", EMPTY), ("abc", LENGTH % 3), (SIGNER + "0", LENGTH % 65), (" " + SIGNER, LENGTH % 65),
                           (SIGNER[:-1] + "g", NOT_HEX), (SIGNER[:-1] + " ", NOT_HEX)):
            with self.subTest(typed=typed):
                w = window()
                self.assertEqual(page(w, typed), (None, "abort"))
                self.assertEqual(w.boxes, [WARNING, box])
                self.assertEqual((w.errorlevel, STORE in w.files), (None, False))

    def test_a_first_run_asks_and_yes_stores_the_canonical_fingerprint(self):
        for typed in (SIGNER, SIGNER.upper(), "0123456789ABCdef" * 4):
            with self.subTest(typed=typed):
                w = window()
                self.assertEqual(page(w, typed), (None, None))
                self.assertEqual(len(w.boxes), 2)
                self.assertTrue(w.boxes[1].startswith(FIRST) and SIGNER in w.boxes[1], w.boxes)
                self.assertEqual((w.files[STORE], w.var["TrustSigner"], w.errorlevel), (SIGNER + "\n", SIGNER, None))
                self.assertEqual(trust.parse_fingerprint(typed), SIGNER)

    def test_no_on_the_first_run_box_ends_with_exit_3_and_stores_nothing(self):
        w = window(answer="IDNO")
        self.assertEqual(page(w, SIGNER), (None, 3))
        self.assertEqual((w.errorlevel, STORE in w.files, len(w.boxes)), (3, False, 2))
        self.assertTrue(w.boxes[1].startswith(FIRST))

    def test_the_same_stored_signer_asks_nothing(self):
        w = window(stored=SIGNER + "\n")
        self.assertEqual(page(w, SIGNER.upper()), (None, None))
        self.assertEqual((w.boxes, w.files[STORE]), ([WARNING], SIGNER + "\n"))

    def test_a_changed_signer_shows_both_and_yes_stores_the_new_one_and_no_ends_with_exit_3(self):
        w = window(stored=OTHER + "\n")
        self.assertEqual(page(w, SIGNER), (None, None))
        self.assertTrue(w.boxes[1].startswith(CHANGED) and OTHER in w.boxes[1] and SIGNER in w.boxes[1], w.boxes)
        self.assertEqual(w.files[STORE], SIGNER + "\n")
        w = window(stored=OTHER + "\n", answer="IDNO")
        self.assertEqual(page(w, SIGNER), (None, 3))
        self.assertEqual((w.errorlevel, w.files[STORE], len(w.boxes)), (3, OTHER + "\n", 2))
        self.assertTrue(w.boxes[1].startswith(CHANGED))

    def test_a_damaged_stored_file_is_refused_from_the_page_with_exit_3(self):
        w = window(stored="not a fingerprint\n")
        self.assertEqual(page(w, SIGNER), (None, 3))
        self.assertEqual((w.boxes, w.errorlevel, w.files[STORE]), ([WARNING, DAMAGED], 3, "not a fingerprint\n"))

    def test_back_and_next_with_the_same_fingerprint_asks_nothing_again(self):
        w = window()
        self.assertEqual(page(w, SIGNER), (None, None))
        self.assertEqual(page(w, SIGNER), (None, None))
        self.assertEqual((len(w.boxes), w.files[STORE]), (2, SIGNER + "\n"))

    def test_an_administrator_window_stores_the_user_s_signer_and_keeps_the_machine_folders_for_the_pages(self):
        w = window(admin=True)
        self.assertEqual((w.code, w.var["LOCALAPPDATA"]), (None, "C:\\ProgramData"))  # Update_Detect in .onInit
        self.assertEqual(page(w, SIGNER), (None, None))
        self.assertEqual(w.files[STORE], SIGNER + "\n")
        self.assertFalse(any(p.startswith("C:\\ProgramData\\EcosystemInstaller") for p in w.files), sorted(w.files))
        self.assertEqual((w.var["APPDATA"], w.var["LOCALAPPDATA"]), ("C:\\ProgramData", "C:\\ProgramData"))
        u = window(admin=False)
        self.assertEqual(page(u, SIGNER), (None, None))
        self.assertEqual((u.var["APPDATA"], u.var["LOCALAPPDATA"]), (ROAMING, LOCAL))


class Carry(unittest.TestCase):
    def test_the_typed_signer_reaches_the_elevated_copy(self):
        check_the_typed_signer_reaches_the_elevated_copy()

    def test_a_given_signer_crosses_as_typed_as_before(self):
        w = window("/SIGNER=" + SIGNER.upper(), stored=SIGNER + "\n")
        w.var.update(in_mode="local")
        self.assertEqual(w.run("Page_elevation_Leave"), 0)
        self.assertEqual(w.shell[0][2], "/SIGNER=%s /ELEVATED /MODE=local" % SIGNER.upper())


class Source(unittest.TestCase):
    def test_the_page_is_first_and_its_controls_follow_the_layout_rule(self):
        pages = re.findall(r"^Page (.*)$", MAIN, re.M)
        self.assertEqual(pages[:2], ["custom Page_signer Page_signer_Leave", "custom Page_mode_Pre Page_mode_Leave"])
        made = [(k, int(y), int(h), t) for k, y, h, t in
                re.findall(r'^  \$\{NSD_Create(\w+)\} 0u (\d+)u 100% (\d+)u "([^"]*)"$', func(TRUST, "Page_signer"), re.M)]
        self.assertEqual(made, [("Label", 0, 20, HELP), ("Label", 24, 8, FIELD), ("Text", 33, 12, "$TrustSigner")])
        self.assertLessEqual(max(y + h for _k, y, h, _t in made), PAGE_HEIGHT)
        self.assertLessEqual(len(HELP), 130)
        self.assertNotRegex(HELP, r'["$`]')

    def test_every_box_of_the_page_answers_itself_and_the_trust_boxes_are_unchanged(self):
        for line in func(TRUST, "Page_signer_Leave").splitlines():
            if "MessageBox" in line:
                self.assertRegex(line, r'^\s+MessageBox MB_OK\|MB_ICONEXCLAMATION "[^"]+" /SD IDOK$')
        self.assertEqual(len(re.findall(r"MessageBox MB_YESNO\|MB_ICON\w+\|MB_DEFBUTTON2 ", TRUST)), 2)
        self.assertEqual(TRUST.count("Push \"/SIGNER=\"\n  Call Cmdline_Get"), 1)

    def test_a_stop_from_the_page_quits_with_exit_3_and_from_on_init_aborts(self):
        self.assertRegex(func(TRUST, "TrustStop"), r"StrCmp \$TrustAsk 1 0 TrustStopInit\s+SetErrorLevel 3\s+Quit\s+TrustStopInit:\s+Abort\s*$")


class Mutants(unittest.TestCase):
    def test_m1_the_typed_signer_not_carried(self):
        p = program(("elevate.nsh", "  ${If} $0 == \"\"\n    StrCpy $0 $TrustSigner\n  ${EndIf}\n", ""))
        with self.assertRaises(AssertionError):
            check_the_typed_signer_reaches_the_elevated_copy(p)

    def test_m2_the_page_for_a_carried_run(self):
        p = program(("trust.nsh", "  ${AndIf} $carried != 1\n  ${AndIf} $TrustSigner == \"\"\n", "  ${AndIf} $TrustSigner == \"\"\n"))
        w = window("/ELEVATED /MODE=local", admin=True, prog=p)
        self.assertNotEqual((w.code, w.errorlevel), ("abort", 3))

    def test_m3_abort_from_the_page_would_keep_it_after_a_no(self):
        p = program(("trust.nsh", "  SetErrorLevel 3\n  Quit\n  TrustStopInit:\n", "  TrustStopInit:\n"))
        w = window(answer="IDNO", prog=p)
        self.assertNotEqual(page(w, SIGNER), (None, 3))


if __name__ == "__main__":
    unittest.main()
