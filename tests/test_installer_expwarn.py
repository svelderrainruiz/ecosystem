"""Issue #329: the installer says on every page and in one first box that it is an EXPERIMENTAL installer.
The window caption and the branding line (bottom of every page, between Cancel and < Back) are fixed texts of main.nsi. The box is the first box of an interactive run, in front of
every trust box; a silent run and the elevated copy that its first window started ($carried 1) never show it, and no exit code changes.
The box sequence runs the real .onInit in the test interpreter (tests/nsis_interp.py); mutants of the script text check that the checks can fail.
The rehearsal asked for more ("Overlapping text, no help"): every generated page but the NI docker image page starts with a help text, and no two of its controls overlap."""
import copy
import re
import unittest
from unittest import mock

from installer import schema as S
from installer import trust
from tests.nsis_interp import NSIS, Program, source_text
from tests.test_installer_docfix import STORE, AuditWorld
from tests.test_installer_sl21b import EXPERIMENTAL_BOX, RUNNING, child, prog

MAIN = (NSIS / "main.nsi").read_text(encoding="utf-8")
SCREENS = (NSIS / "screens.nsh").read_text(encoding="utf-8")
HELP = {
    "mode": "Choose what this PC does: local only (no forge), a GitHub runner or a GitLab runner. Choose one, then select Next.",
    "folders": "Type an install folder and a work folder. Each typed folder is checked when you select Next; an empty box is skipped.",
    "forge": "The GitHub or GitLab address (https:// only), the partner or organisation ID and the allow-list. An empty box is skipped.",
    "network": "Only if this PC needs them: a proxy address (http:// or https://) and DNS servers, separated by commas. An empty box is skipped.",
    "labview": "Type the LabVIEW version this PC uses. An empty box is skipped.",
    "licences": "Shown because an NI docker image was chosen. Tick both licence boxes to continue.",
    "secrets": "Tokens and passwords are typed here only, never on the command line. Fill in only the ones you need; an empty box is skipped.",
}
WARNING = "This is an EXPERIMENTAL installer (test build). It is not for production use: run it only where you can undo the changes."
MISSING = ("The signer fingerprint is missing or malformed. Start the installer with /SIGNER= and the 64 hex digits of the published fingerprint."
           " Nothing was started.")
SIGNER = "0123456789abcdef" * 4
BLOCK = ('  ${IfNot} ${Silent}\n  ${AndIf} $carried != 1\n    MessageBox MB_OK|MB_ICONEXCLAMATION "%s" /SD IDOK\n  ${EndIf}\n' % WARNING)


def func(text, name):
    return re.search(r"^Function %s\n(.*?)^FunctionEnd" % re.escape(name), text, re.M | re.S).group(1)


def mutant(old, new):
    files = source_text()
    if files["main.nsi"].count(old) != 1:
        raise ValueError("the mutant anchor must match once: %r" % old)
    files["main.nsi"] = files["main.nsi"].replace(old, new)
    return files


def first_window(cmdline="", files=None, answer="IDYES"):
    """An interactive first window, standard account, nothing stored: the real TrustCheck runs."""
    w = AuditWorld(silent=False, admin=False, answer=answer)
    if files is not None:
        w.program = Program(files, defines={"RUNNER_PAYLOAD"}, version="0.2.0")
    w.native_TrustCheck = None
    if cmdline:
        w.var["CMDLINE"] += " " + cmdline
    w.code = w.run(".onInit")
    return w


def check_the_warning_comes_first_and_changes_no_exit_code(files=None):
    # T3: no signer. The warning, then the refusal, exit 3 as before.
    w = first_window(files=files)
    assert (w.code, w.errorlevel, w.boxes) == ("abort", 3, [WARNING, MISSING]), (w.code, w.errorlevel, w.boxes)
    # T4: a first run. The warning, then the signer box; Yes stores the signer and the run goes on to the pages.
    w = first_window("/SIGNER=" + SIGNER, files=files)
    assert (w.code, len(w.boxes), w.boxes[0]) == (None, 2, WARNING), (w.code, w.boxes)
    assert w.boxes[1].startswith("First run. The signer fingerprint is:") and w.files[STORE] == SIGNER + "\n", w.boxes
    # No on the signer box ends the run as before: no exit code set, nothing stored.
    w = first_window("/SIGNER=" + SIGNER, files=files, answer="IDNO")
    assert (w.code, w.errorlevel, len(w.boxes), w.boxes[0], STORE in w.files) == ("abort", None, 2, WARNING, False), (w.code, w.errorlevel, w.boxes)
    # A stored signer: the warning is the only box.
    w = AuditWorld(silent=False, admin=False, files={STORE: SIGNER + "\n"})
    if files is not None:
        w.program = Program(files, defines={"RUNNER_PAYLOAD"}, version="0.2.0")
    w.native_TrustCheck = None
    w.var["CMDLINE"] += " /SIGNER=" + SIGNER
    assert (w.run(".onInit"), w.boxes) == (None, [WARNING]), w.boxes


def check_the_elevated_copy_and_a_silent_run_show_no_warning(files=None):
    program = Program(files) if files is not None else prog()
    c = child(RUNNING, program)
    assert (c.code, c.var["carried"], c.boxes) == (None, "1", []), (c.code, c.boxes)
    s = child("/S /MODE=local /INSTALL_DIR=C:\\x", program, silent=True)
    assert (s.code, s.boxes) == (None, []), (s.code, s.boxes)
    w = AuditWorld(silent=True, admin=True, files={STORE: SIGNER + "\n"})
    if files is not None:
        w.program = Program(files, defines={"RUNNER_PAYLOAD"}, version="0.2.0")
    w.native_TrustCheck = None
    w.var["CMDLINE"] += " /S /MODE=local /SIGNER=" + SIGNER
    assert (w.run(".onInit"), w.boxes) == (None, []), w.boxes
    # an ordinary interactive run of the same program shows it once
    c = child("/MODE=local", program)
    assert (c.code, c.var["carried"], c.boxes) == (None, "0", [EXPERIMENTAL_BOX]), (c.code, c.boxes)


class Texts(unittest.TestCase):
    def test_the_caption_and_the_branding_line_say_experimental_and_the_product_name_is_unchanged(self):
        attrs = re.findall(r"^(Name|Caption|UninstallCaption|BrandingText) (.*)$", MAIN, re.M)
        self.assertEqual(attrs, [("Caption", '"Ecosystem Runner Setup (EXPERIMENTAL)"'), ("UninstallCaption", '"Ecosystem Runner Uninstall (EXPERIMENTAL)"'),
                                 ("BrandingText", '"EXPERIMENTAL (test build)"')])
        # The branding control is one line of 108 dialog units: the 59 characters first asked for showed as "EXPERIMENTAL installer (test".
        self.assertLessEqual(len(attrs[-1][1].strip('"')), 25)
        for name in ("install.nsh", "update.nsh"):
            self.assertIn('"DisplayName" "Ecosystem Runner"\n', (NSIS / name).read_text(encoding="utf-8"))

    def test_the_box_is_written_once_answers_itself_when_silent_and_sits_before_the_trust_check(self):
        every = "\n".join(p.read_text(encoding="utf-8") for p in sorted(NSIS.glob("*.ns[hi]")))
        self.assertEqual(every.count(WARNING), 1)
        body = func(MAIN, ".onInit")
        self.assertIn(BLOCK, body)
        at = [body.index(t) for t in ("!insertmacro RefuseSecretOptions", "Call Carried_Detect", "!insertmacro ParseSilentKeys", BLOCK, "Call TrustCheck")]
        self.assertEqual(at, sorted(at))


class Sequence(unittest.TestCase):
    def test_the_warning_comes_first_and_changes_no_exit_code(self):
        check_the_warning_comes_first_and_changes_no_exit_code()

    def test_the_elevated_copy_and_a_silent_run_show_no_warning(self):
        check_the_elevated_copy_and_a_silent_run_show_no_warning()

    def test_the_trust_module_reads_the_same_signer(self):
        self.assertEqual(trust.parse_fingerprint(SIGNER.upper()), SIGNER)


class Mutants(unittest.TestCase):
    def killed(self, check, files):
        with self.assertRaises(AssertionError):
            check(files)

    def test_m1_the_box_after_the_trust_check_misses_the_refusal(self):
        moved = mutant(BLOCK + "  Call TrustCheck\n", "  Call TrustCheck\n" + BLOCK)
        self.killed(check_the_warning_comes_first_and_changes_no_exit_code, moved)

    def test_m2_the_elevated_copy_shows_it_again(self):
        self.killed(check_the_elevated_copy_and_a_silent_run_show_no_warning, mutant("  ${AndIf} $carried != 1\n", ""))

    def test_m3_a_silent_run_reaches_the_box(self):
        self.killed(check_the_elevated_copy_and_a_silent_run_show_no_warning, mutant("  ${IfNot} ${Silent}\n  ${AndIf} $carried != 1\n", "  ${If} $carried != 1\n"))

    def test_m4_no_box(self):
        self.killed(check_the_warning_comes_first_and_changes_no_exit_code, mutant(BLOCK, ""))



# The custom pages (operator rehearsal, issue 329: "Overlapping text, no help"). A page of the classic UI is 266 x 130 dialog units.
PAGE_HEIGHT = 130
CONTROL = re.compile(r'^  \$\{NSD_Create(\w+)\} (\d+)u (\d+)u (\S+) (\d+)u "([^"]*)"$', re.M)


def controls(nsh, page):
    """(kind, y, height, text) of every control the page function creates, in order."""
    return [(kind, int(y), int(h), text) for kind, _x, y, _w, h, text in CONTROL.findall(func(nsh, "Page_" + page))]


def check_pages(schema, nsh):
    """Every page with a help text starts with it, and no two of its controls share a row of dialog units; all stay inside the page."""
    helped = [p for p in schema["pages"] if p.get("help")]
    assert [p["id"] for p in helped] == [p["id"] for p in schema["pages"] if p["id"] != "image"], "every page but the NI docker image page has help"
    for p in helped:
        made = controls(nsh, p["id"])
        assert made[0] == ("Label", 0, S.HELP_HEIGHT, p["help"]), p["id"]
        assert len(made) == 1 + sum(len(i["choices"]) if i.get("setter") else 1 if i["kind"] == "licence" else 2 for i in schema["inputs"] if i["page"] == p["id"]), p["id"]
        rows = sorted((y, y + h) for _k, y, h, _t in made)
        for (top, bottom), (next_top, _) in zip(rows, rows[1:]):
            assert bottom <= next_top, "%s: a control at %du..%du overlaps the next at %du" % (p["id"], top, bottom, next_top)
        assert rows[-1][1] <= PAGE_HEIGHT, p["id"]


class Pages(unittest.TestCase):
    def setUp(self):
        self.schema = S.load_schema()

    def test_every_page_but_the_image_page_has_help_and_nothing_overlaps(self):
        check_pages(self.schema, SCREENS)
        self.assertEqual(SCREENS, S.generate_nsh(self.schema))

    def test_the_help_texts_are_these_and_fit_in_two_lines(self):
        # Rendered under Wine, the longest (128 characters) took 1.6 of the 2.5 lines the 20u label holds.
        helps = {p["id"]: p["help"] for p in self.schema["pages"] if p.get("help")}
        self.assertEqual(helps, HELP)
        for text in helps.values():
            self.assertLessEqual(len(text), 130)
            self.assertNotRegex(text, r'["$`]|NI image')

    def test_the_image_page_keeps_its_controls_for_the_separate_change(self):
        self.assertEqual(controls(SCREENS, "image"), [("Label", 4, 8, "NI docker image container type"), ("Text", 12, 12, ""),
                                                      ("Label", 22, 8, "NI docker image year"), ("Text", 30, 12, "")])


class PageMutants(unittest.TestCase):
    def setUp(self):
        self.schema = S.load_schema()

    def test_m5_the_old_pitch_overlaps(self):
        with mock.patch.object(S, "FIELD_PITCH", 18):
            with self.assertRaises(AssertionError):
                check_pages(self.schema, S.generate_nsh(self.schema))

    def test_m6_a_first_field_moved_up_into_the_help_text(self):
        old = '${NSD_CreateLabel} 0u 24u 100% 8u "Install folder"'
        self.assertEqual(SCREENS.count(old), 1)
        with self.assertRaises(AssertionError):
            check_pages(self.schema, SCREENS.replace(old, old.replace(" 24u ", " 16u ")))

    def test_m7_a_page_without_help(self):
        bare = copy.deepcopy(self.schema)
        del [p for p in bare["pages"] if p["id"] == "network"][0]["help"]
        with self.assertRaises(AssertionError):
            check_pages(bare, S.generate_nsh(bare))


if __name__ == "__main__":
    unittest.main()
