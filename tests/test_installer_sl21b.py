"""SL-21b (ecosystem-control#117, part of #97 and #64): the answers typed before the Windows administrator prompt reach the elevated copy.
INST-REQ-028, 029, 073. Before this slice the first window asked everything, then started a second copy that asked everything again: only the program's own words crossed.
Now Elevate_Raise builds ONE parameter string (/NCRC and /SIGNER= when the first window had them, /ELEVATED, then every non-secret answer that is not blank, in schema order:
Carry_Answers in the generated screens.nsh) and the elevated copy reads it like a silent run (Carried_Detect, then ParseSilentKeys), skips every page those answers are for and
shows only the secrets page (secrets never cross; they are SL-17a, #105).
No Windows, no network: the NSIS functions run in the small interpreter (tests/nsis_interp.py) over the real script text. The one NSIS routine the string meets before any script
runs, the scan of the command line in the installer stub (Source/exehead/Main.c, NSIS 3.10), is ported here (stub_scan) and checked against what is handed over.
Every check_* takes an optional program, so the mutants at the end of the file run the same check over a changed script text."""
import re
import unittest
from pathlib import Path

from installer import schema as S
from tests.nsis_interp import NSIS, Program, Service, UpdateWorld, source_text
from tests.test_installer_sl16b import pinned_schema
from tests.test_installer_sl16e import StrictWorld
from tests.test_installer_sl19 import KEPT, RUNNER, STATE, state_line

README = (Path(__file__).resolve().parent.parent / "installer" / "README.md").read_text(encoding="utf-8")
SCHEMA = S.load_schema()
IDS = [i["id"] for i in S.public_inputs(SCHEMA)]
SECRETS = [i["id"] for i in S.secret_inputs(SCHEMA)]
PAGES = [s["page"] for s in S.screen_list(SCHEMA) if s["page"] != "secrets"]
EXE = "C:\\Program Files\\Ecosystem Installer\\setup.exe"
QEXE = '"%s"' % EXE
CANARY = "CANARY-SECRET-7731"
BASE = {"mode": "local", "install_dir": "C:\\x"}
ANSWERS = {
    "mode": "github", "install_dir": "C:\\Program Files\\Ecosystem Runner", "work_dir": "D:\\Work Folder\\Runner",
    "github_url": "https://github.example/acme", "gitlab_url": "https://gitlab.example/acme", "partner_id": "Acme Partner 01",
    "allow_list": "a.example,b.example", "http_proxy": "http://proxy.example:3128", "dns_servers": "1.1.1.1,9.9.9.9",
    "labview_version": "2024 Q3", "image_variant": "linux", "image_year": "2026q1", "ni_licence_held": "yes", "engine_licence_accepted": "yes",
}
EXPECTED = ('/ELEVATED /MODE=github /INSTALL_DIR="C:\\Program Files\\Ecosystem Runner" /WORK_DIR="D:\\Work Folder\\Runner" /GITHUB_URL=https://github.example/acme '
            '/GITLAB_URL=https://gitlab.example/acme /PARTNER_ID="Acme Partner 01" /ALLOW_LIST=a.example,b.example /HTTP_PROXY=http://proxy.example:3128 '
            '/DNS_SERVERS=1.1.1.1,9.9.9.9 /LABVIEW_VERSION="2024 Q3" /IMAGE_VARIANT=linux /IMAGE_YEAR=2026q1 /NI_LICENCE_HELD=yes /ENGINE_LICENCE_ACCEPTED=yes')
# Typed values that cross and read back as typed (a tab cannot be typed on a page: Val_Line refuses it).
CORPUS = ["Acme", "Acme Partner 01", "a/b", "a=b=c", "x=", "  leading", "a  b", "it's", "a`b", "/S", "/S b", "/NCRC x", "-", "/", "a-b", "ünï 名前",
          "cost $5 $PROFILE $$x", "a b/c", "a,b", "D:\\Work Folder\\", "a\\", "a b\\"]
# Values the NSIS stub would read as a switch if they crossed in these positions, or that would desynchronise its quote pairing.
SWITCHY = ["/S x", "/NCRC x", "/S", "/NCRC", "/D=C:\\x y", "-"]
TRAILING = ["a ", " ", "a  "]
# Tails of values that are NOT carried (Rule R: a double quote, a blank before / or -, a blank at the end).
REFUSED = [" /b", " -b", " - b", " -", '"b', " /S y", " /D=C:\\y", " /NCRC", " /GITHUB_TOKEN=1", " ", "  "]
LABELS = {"partner_id": "Partner or organisation ID", "work_dir": "Work folder"}
RUNNING = "/ELEVATED /MODE=local /INSTALL_DIR=C:\\x"
EXPERIMENTAL_BOX = ("MB_OK|MB_ICONEXCLAMATION This is an EXPERIMENTAL installer (test build). It is not for production use: run it only where you can undo the changes."
                    " /SD IDOK")


def stub_scan(line):
    """What the NSIS stub does with the command line before any script runs (Source/exehead/Main.c of NSIS 3.10, the loop over `cmdline`):
    (silent, no CRC check, line cut at /D=). Blank-separated words; a word that starts with a quote runs to the next quote."""
    i, seek = (1, '"') if line[:1] == '"' else (0, " ")
    j = line.find(seek, i)
    i = len(line) if j < 0 else j + 1
    silent = no_crc = cut = False
    while i < len(line):
        while line[i:i + 1] == " ":
            i += 1
        seek = " "
        if line[i:i + 1] == '"':
            i, seek = i + 1, '"'
        if line[i:i + 1] == "/":
            i += 1
            rest = line[i:]
            silent = silent or (rest[:1] == "S" and rest[1:2] in ("", " "))
            no_crc = no_crc or (rest[:4] == "NCRC" and rest[4:5] in ("", " "))
            if line[i - 2:i + 2] == " /D=":
                cut = True
                break
        j = line.find(seek, i)
        i = len(line) if j < 0 else j
        if line[i:i + 1] == '"':
            i += 1
    return silent, no_crc, cut


def prog(*edits, pinned=True):
    """The real script text (screens.nsh from the generator over a schema whose images are pinned), with (file, old, new) edits that each match once."""
    files = source_text()
    if pinned:
        files["screens.nsh"] = S.generate_nsh(pinned_schema())
    for name, old, new in edits:
        if files[name].count(old) != 1:
            raise ValueError("the mutant anchor must match once: %r in %s" % (old, name))
        files[name] = files[name].replace(old, new)
    return Program(files)


def parent(answers, program, cmdline="", shell_fails=False):
    """The first window: not administrator, interactive, the answers as the pages left them, Next on the elevation page."""
    w = StrictWorld(cmdline=cmdline, admin=False, silent=False, program=program, exe=QEXE)
    w.var.update({"in_" + k: v for k, v in answers.items()})
    w.shell_fails = shell_fails
    w.code = w.run("Page_elevation_Leave")
    return w


def child(params, program, admin=True, silent=False):
    w = StrictWorld(cmdline=params, admin=admin, silent=silent, program=program, exe=QEXE)
    w.code = w.run(".onInit")
    return w


def handed(w):
    assert w.code == 0 and w.boxes == [] and len(w.shell) == 1 and w.shell[0][:2] == ("runas", EXE), "nothing was handed over: %r %r" % (w.code, w.boxes)
    return w.shell[0][2]


def refused(w, label):
    assert w.code == "abort" and w.shell == [], "an answer that cannot cross keeps the page and raises no prompt: %r %r" % (w.code, w.shell)
    assert len(w.boxes) == 1 and "NOT started" in w.boxes[0] and label in w.boxes[0], w.boxes


def check_every_answer_crosses_in_schema_order(program=None):
    program = program or prog()
    assert list(ANSWERS) == IDS, "the fixture follows the schema order"
    assert handed(parent(ANSWERS, program)) == EXPECTED


def check_no_secret_crosses_or_is_written_anywhere(program=None):
    program = program or prog()
    marks = {k: "%s-%s" % (CANARY, k) for k in SECRETS}
    w = parent(dict(ANSWERS, **marks), program)
    text = handed(w)
    assert CANARY not in repr([w.shell, w.boxes, w.log, w.files, w.execs]), "a secret reached the string, a box, the log, a file or a command"
    assert not [k for k in SECRETS if "/" + k.upper() in text.upper()]


def check_the_order_is_ncrc_signer_elevated_then_the_answers_and_the_parents_own_words_are_dropped(program=None):
    program = program or prog()
    own = "/NCRC /FOO=bar /SIGNER=ab12 /MODE=gitlab /D=C:\\y /INSTALL_DIR=D:\\z"
    assert handed(parent(dict(BASE, work_dir=""), program, own)) == "/NCRC /SIGNER=ab12 /ELEVATED /MODE=local /INSTALL_DIR=C:\\x"
    assert handed(parent(BASE, program, '/SIGNER="ab 12"')) == '/SIGNER="ab 12" /ELEVATED /MODE=local /INSTALL_DIR=C:\\x'
    assert handed(parent(BASE, program, "/NCRC")) == "/NCRC /ELEVATED /MODE=local /INSTALL_DIR=C:\\x"
    assert handed(parent(BASE, program, "/FOO=bar")) == "/ELEVATED /MODE=local /INSTALL_DIR=C:\\x"
    assert handed(parent(BASE, program, "/NCRCX /SIGNER")) == "/ELEVATED /MODE=local /INSTALL_DIR=C:\\x", "only the whole word /NCRC, and a /SIGNER= with a value"


def check_licence_tokens_cross_as_typed_and_the_childs_gate_refuses_them(program=None):
    program = program or prog()
    text = handed(parent(dict(ANSWERS, engine_licence_accepted="no"), program))
    assert text.endswith(" /NI_LICENCE_HELD=yes /ENGINE_LICENCE_ACCEPTED=no"), text
    c = child(text, program)
    s = child("/S " + text.replace("/ELEVATED ", ""), program, silent=True)
    assert (c.code, c.log) == (35, [("licence-not-accepted", "licences", "35")]) and (s.code, s.log, s.boxes) == (35, c.log, [])
    assert len(c.boxes) == 1 and "licences" in c.boxes[0]


def check_a_typed_value_reaches_the_child_as_typed(program=None):
    program = program or prog()
    for key in ("partner_id", "work_dir"):
        for v in CORPUS:
            text = handed(parent(dict(BASE, **{key: v}), program))
            c = child(text, program)
            assert (c.code, c.boxes) == (None, []), (key, v, c.code, c.boxes)
            assert c.var["in_" + key] == v, (key, v, c.var["in_" + key])
            assert S.parse_silent(SCHEMA, text)[key] == v, (key, v)


def check_the_nsis_stub_sees_no_switch_in_what_is_handed_over(program=None):
    program = program or prog()
    for v in CORPUS:
        for w in SWITCHY:
            answers = dict(BASE, partner_id=v, labview_version=w)
            assert stub_scan(QEXE + " " + handed(parent(answers, program, "/NCRC"))) == (False, True, False), (v, w)
            assert stub_scan(QEXE + " " + handed(parent(answers, program))) == (False, False, False), (v, w)
    for v in TRAILING:
        p = parent(dict(BASE, partner_id=v, labview_version="/S x"), program)
        assert not p.shell or stub_scan(QEXE + " " + p.shell[0][2]) == (False, False, False), "a blank at the end of a value desynchronises the stub: %r" % (v,)


def check_rule_r_refuses_what_the_elevated_copy_could_not_read_back(program=None):
    program = program or prog()
    for tail in REFUSED:
        for key, label in LABELS.items():
            w = parent(dict(BASE, **{key: CANARY + tail}), program)
            refused(w, label)
            assert CANARY not in repr([w.boxes, w.log, w.files, w.execs]), "the value must not be shown or written"
        if '"' not in tail:
            w = parent(BASE, program, '/SIGNER="%s"' % (CANARY + tail))
            refused(w, "The signer fingerprint")
            assert CANARY not in repr(w.boxes)
    refused(parent(dict(BASE, partner_id=" "), program), LABELS["partner_id"])
    refused(parent(dict(BASE, work_dir="a /b", partner_id="c -d"), program), "Work folder, Partner or organisation ID")
    assert handed(parent(dict(BASE, work_dir="a-b", partner_id="a/b"), program)).endswith(" /WORK_DIR=a-b /PARTNER_ID=a/b")


def check_the_length_limit_is_exact(program=None):
    program = program or prog()
    head = QEXE + " " + RUNNING + " /WORK_DIR="
    folder = "w" * (1022 - len(head))
    text = handed(parent(dict(BASE, work_dir=folder), program))
    assert len(QEXE + " " + text) == 1022
    w = parent(dict(BASE, work_dir=folder + "w"), program)
    refused(w, "Work folder")
    assert w.var["carry_bad"] == "Work folder"
    assert "wwwww" not in repr(w.boxes)
    w = parent(dict(BASE, work_dir=folder[:-20], labview_version="2024"), program)
    refused(w, "LabVIEW version")
    c = child(text, program)
    assert (c.code, c.var["carried"], c.var["in_work_dir"]) == (None, "1", folder)


def check_the_child_reads_every_answer_and_shows_only_the_secrets_page(program=None):
    program = program or prog()
    c = child(handed(parent(ANSWERS, program)), program)
    assert (c.code, c.boxes, c.log, c.var["carried"]) == (None, [], [], "1")
    assert [k for k, v in ANSWERS.items() if c.var.get("in_" + k) != v] == []
    assert [k for k in SECRETS if c.var.get("in_" + k, "")] == []
    assert len(PAGES) == 7
    for page in PAGES:
        assert c.run("Page_" + page) == "abort", page
    assert c.windows == {}
    assert c.run("Page_secrets") is None and c.windows == {"parent/3": 0}, "the secrets page shows, with the Back button off"
    n = child("", program)
    assert n.var["carried"] == "0" and n.run("Page_secrets") is None and n.windows == {}, "an ordinary run leaves Back alone"


def check_elevated_alone_is_the_wizard_and_a_silent_run_is_unchanged(program=None):
    program = program or prog()
    for params in ("/ELEVATED", "/ELEVATED /INSTALL_DIR=C:\\x", "/MODE=local /INSTALL_DIR=C:\\x", "/ELEVATEDX /MODE=local", "/ELEVATED=1 /MODE=local"):
        c = child(params, program)
        # an ordinary interactive run: its one box is the experimental warning every wizard starts with (issue 329)
        assert (c.code, c.boxes, c.var["carried"], c.var.get("in_install_dir", "")) == (None, [EXPERIMENTAL_BOX], "0", ""), params
    s = child("/S /ELEVATED /MODE=local /INSTALL_DIR=C:\\x", program, admin=False, silent=True)
    assert (s.code, s.boxes, s.var["carried"]) == (38, [], "0")
    s = child("/S /ELEVATED /MODE=local /FOO=x", program, silent=True)
    assert (s.code, s.boxes) == (31, [])


UNPINNED = RUNNING + " /IMAGE_VARIANT=windows /IMAGE_YEAR=2025q3 /NI_LICENCE_HELD=yes /ENGINE_LICENCE_ACCEPTED=yes"
BAD = [(RUNNING + " /WORK_DIR=", 30, "/WORK_DIR"), ("/ELEVATED /MODE=nope", 30, "/MODE"), (RUNNING + " /GITHUB_URL=http://" + CANARY, 30, "/GITHUB_URL"),
       (RUNNING + " /FOO=x", 31, "/FOO"), (UNPINNED.replace("windows", "linux").replace("2025q3", "2026q1").replace("ACCEPTED=yes", "ACCEPTED=no"), 35, "licences"),
       (UNPINNED, 36, "image")]


def check_a_token_the_child_does_not_accept_ends_it_with_the_silent_exit_code_and_one_box(program=None):
    program = program or prog()
    for params, code, key in BAD:
        c = child(params, program)
        s = child("/S " + params.replace("/ELEVATED ", ""), program, silent=True)
        assert (c.code, c.log) == (code, s.log) and s.code == code and s.boxes == [], (params, c.code, c.log, s.code, s.log)
        assert len(c.boxes) == 1 and key in c.boxes[0] and "Nothing was started" in c.boxes[0] and CANARY not in c.boxes[0], (params, c.boxes)


def check_a_declined_prompt_keeps_the_answers_and_the_next_try_hands_over_the_same_string(program=None):
    program = program or prog()
    w = parent(ANSWERS, program, "/NCRC", shell_fails=True)
    assert w.code == "abort" and len(w.boxes) == 1 and "NOT started" in w.boxes[0] and len(w.shell) == 1
    first = w.shell[0][2]
    assert first == "/NCRC " + EXPECTED
    assert [k for k, v in ANSWERS.items() if w.var["in_" + k] != v] == []
    w.shell_fails = False
    assert w.run("Page_elevation_Leave") == 0 and len(w.shell) == 2 and w.shell[1][2] == first and len(w.boxes) == 1


def check_a_copy_that_is_still_not_administrator_hands_the_same_string_on(program=None):
    program = program or prog()
    text = handed(parent(ANSWERS, program, "/NCRC"))
    c = child(text, program, admin=False)
    assert (c.code, c.boxes, c.var["carried"]) == (None, [], "1")
    assert c.run("Page_elevation_Leave") == 0 and len(c.shell) == 1 and c.shell[0][2] == text


class StrictUpdate(UpdateWorld):
    """The update world with IfErrors clearing the flag it tests, as real NSIS does (the shared model keeps it: #109)."""

    def cond(self, t):
        if t == ["${Errors}"]:
            flag, self.errors = self.errors, False
            return flag
        return super().cond(t)


class Checks(unittest.TestCase):
    def test_every_non_secret_answer_crosses_in_schema_order_as_one_string(self):
        check_every_answer_crosses_in_schema_order()

    def test_no_secret_crosses_and_none_is_written_to_a_box_the_log_a_file_or_a_command(self):
        check_no_secret_crosses_or_is_written_anywhere()

    def test_the_order_is_ncrc_signer_elevated_then_the_answers_and_the_parents_own_words_are_dropped(self):
        check_the_order_is_ncrc_signer_elevated_then_the_answers_and_the_parents_own_words_are_dropped()

    def test_licence_tokens_cross_as_typed_and_the_childs_gate_refuses_them_with_exit_35(self):
        check_licence_tokens_cross_as_typed_and_the_childs_gate_refuses_them()

    def test_a_typed_value_reaches_the_child_as_typed_and_the_python_reference_agrees(self):
        check_a_typed_value_reaches_the_child_as_typed()

    def test_the_nsis_stub_sees_no_switch_no_cut_and_no_crc_only_when_it_was_carried(self):
        check_the_nsis_stub_sees_no_switch_in_what_is_handed_over()

    def test_rule_r_refuses_what_the_elevated_copy_could_not_read_back(self):
        check_rule_r_refuses_what_the_elevated_copy_could_not_read_back()

    def test_the_child_reads_1022_and_the_parent_refuses_1023_before_elevation(self):
        check_the_length_limit_is_exact()

    def test_the_child_reads_every_answer_skips_seven_pages_and_shows_only_the_secrets_page_with_back_off(self):
        check_the_child_reads_every_answer_and_shows_only_the_secrets_page()

    def test_elevated_alone_is_the_wizard_and_a_silent_run_is_unchanged(self):
        check_elevated_alone_is_the_wizard_and_a_silent_run_is_unchanged()

    def test_a_token_the_child_does_not_accept_ends_it_with_the_silent_exit_code_and_one_box(self):
        check_a_token_the_child_does_not_accept_ends_it_with_the_silent_exit_code_and_one_box()

    def test_a_declined_prompt_keeps_the_answers_and_the_next_try_hands_over_the_same_string(self):
        check_a_declined_prompt_keeps_the_answers_and_the_next_try_hands_over_the_same_string()

    def test_a_copy_that_is_still_not_administrator_hands_the_same_string_on(self):
        check_a_copy_that_is_still_not_administrator_hands_the_same_string_on()

    def test_the_elevated_copy_still_takes_the_update_path_and_reads_the_answers_first(self):
        text = '/ELEVATED /MODE=local /INSTALL_DIR="C:\\Program Files\\x" /WORK_DIR=D:\\w'
        for installed, mode, code in (("0.1.0", "update", None), ("0.2.0", "repair", None), ("0.3.0", "newer", 41)):
            w = StrictUpdate(files={RUNNER: "old-runner", STATE: state_line(installed), **KEPT}, service=Service(), silent=False)
            w.var.update({"CMDLINE": QEXE + " " + text, "EXEPATH": EXE})
            end = w.start(".onInit")
            self.assertEqual((end, w.v["upd_mode"], w.errorlevel, w.v["carried"]), ("quit" if code else "done", mode, code, "1"), installed)
            self.assertEqual((w.v["in_install_dir"], w.v["in_work_dir"]), ("C:\\Program Files\\x", "D:\\w"))


class StubPort(unittest.TestCase):
    """The port of the stub scan is checked against what the C code does, so the checks that use it are not empty."""

    def test_it_sees_a_switch_in_a_quoted_value_a_cut_and_a_no_crc_option(self):
        self.assertEqual(stub_scan(QEXE + ' /PARTNER_ID="x /S y"'), (True, False, False))
        self.assertEqual(stub_scan(QEXE + " /A=1 /D=C:\\x"), (False, False, True))
        self.assertEqual(stub_scan(QEXE + " /A /NCRC"), (False, True, False))
        self.assertEqual(stub_scan(QEXE + " /A /NCRCX /SY"), (False, False, False))

    def test_a_value_that_ends_in_a_blank_swaps_the_quote_pairing_of_every_later_value(self):
        self.assertEqual(stub_scan(QEXE + ' /PARTNER_ID="a " /LABVIEW_VERSION="/S x"'), (True, False, False))
        self.assertEqual(stub_scan(QEXE + ' /PARTNER_ID="a b" /LABVIEW_VERSION="/S x"'), (False, False, False))

    def test_the_words_rule_r_keeps_out_would_have_been_read_as_a_switch_or_a_secret(self):
        for tail, seen in ((" /S y", (True, False, False)), (" /NCRC y", (False, True, False)), (" /D=C:\\y", (False, False, True))):
            self.assertEqual(stub_scan(QEXE + ' /PARTNER_ID="%s%s"' % (CANARY, tail)), seen)
        for tail in (" -", " /GITHUB_TOKEN=1"):
            with self.assertRaises(S.SchemaError):
                S.parse_silent(SCHEMA, '/PARTNER_ID="%s%s"' % (CANARY, tail))


class SourcePins(unittest.TestCase):
    def test_the_carried_box_names_the_key_and_never_a_value(self):
        body = prog().functions["Carried_Box"]
        self.assertEqual(sorted(set(re.findall(r"\$\w+", body))), ["$0", "$carried"], body)
        self.assertIn("MB_ICONSTOP", body)
        self.assertIn("/SD IDOK", body)

    def test_seven_generated_pages_skip_when_carried_and_the_secrets_page_does_not(self):
        files = source_text()
        screens = files["screens.nsh"]
        for page in PAGES:
            self.assertIn("Function Page_%s\n  ${If} $carried == 1\n    Abort\n  ${EndIf}\n" % page, screens, page)
        self.assertIn("Function Page_secrets\n  !insertmacro Dialog_Create\n", screens)

    def test_every_silent_exit_that_names_an_answer_shows_the_carried_box_first(self):
        files = source_text()
        screens = files["screens.nsh"]
        for anchor in ("  Push $R0\n  Call Carried_Box\n  Push $R1\n", '        Push "$vs_name"\n        Call Carried_Box\n        Push "unknown-key"\n',
                       '  Push "/MODE"\n  Call Carried_Box\n  Push "mode"\n'):
            self.assertEqual(screens.count(anchor), 1, anchor)
        for anchor in ('    Push "image"\n    Call Carried_Box\n    Push "image-not-pinned"\n', '    Push "licences"\n    Call Carried_Box\n    Push "licence-not-accepted"\n'):
            self.assertEqual(files["licence.nsh"].count(anchor), 1, anchor)

    def test_the_secrets_are_not_in_the_hand_over_and_the_generated_text_has_one_block_per_public_answer(self):
        body = prog().functions["Carry_Answers"]
        self.assertEqual(re.findall(r'Push "/([A-Z_]+)="', body), [i.upper() for i in IDS])
        self.assertEqual(body.count("Call Carry_One"), len(IDS))


class ReadmePins(unittest.TestCase):
    """REV116 NIT 1: the README names the real probe and says what Cancel does, and the SL-21b section agrees with the scripts."""

    SECTION = README.split("## Declining the administrator prompt", 1)[1]
    DECLINED, CARRIED = SECTION.split("## Handing the typed answers to the elevated copy", 1)

    def test_the_declined_prompt_text_names_the_real_probe_and_says_cancel_exits_with_nsis_code_1(self):
        probes = (Path(__file__).resolve().parent.parent / "installer" / "guest" / "gate-probes.ps1").read_text(encoding="utf-8")
        for name in ("GATE-j-uac-a-stays-open", "GATE-j-uac-b-box-exists", "GATE-j-uac-c-exit-code-after-cancel"):
            with self.subTest(name):
                self.assertIn(name, self.DECLINED)
                self.assertIn(name, probes, "the README must name a probe that exists")
        for phrase in ("installer/guest/gate-probes.ps1", "exit code 1", "not 0", "cancelled by the user"):
            self.assertIn(phrase, self.DECLINED)
        for gone in ("probe in the PR", "exit code untouched", "NOT yet handed", "restarts the wizard"):
            self.assertNotIn(gone, README)
        self.assertIn("never read after the `Quit`", self.DECLINED)

    def test_the_section_names_each_hazard_and_quotes_the_two_boxes_the_scripts_show(self):
        elevate = source_text()["elevate.nsh"]
        for phrase in ("The administrator step did not accept the answer", "Nothing was started",
                       "These answers cannot be handed to the administrator step, so it was NOT started"):
            with self.subTest(phrase):
                self.assertIn(phrase, self.CARRIED)
                self.assertIn(phrase, elevate)
        for phrase in ("Rule R", "`/NCRC`", "ends in a blank", "1022", "1023 or more before the administrator prompt", "Carried_Detect", "Carried_Box", "Update_Detect", "`Page_mode_Pre`",
                       "GetDlgItem", "EnableWindow", "SL-17a", "lower-case `/ncrc`", "not measured on Windows", "NOT start the elevated copy"):
            with self.subTest(phrase):
                self.assertIn(phrase, self.CARRIED)
        self.assertNotIn("://", self.CARRIED)


class Mutants(unittest.TestCase):
    """Each mutant of the scripts must fail the check named for it."""

    def killed(self, check, *edits):
        with self.assertRaises(AssertionError):
            check(prog(*edits))

    def test_m01_a_secret_is_added_to_the_string(self):
        self.killed(check_no_secret_crosses_or_is_written_anywhere,
                    ("screens.nsh", "Function Carry_Answers\n", 'Function Carry_Answers\n  Push "x"\n  Push "/GITHUB_TOKEN="\n  Push $in_github_token\n  Call Carry_One\n'))

    def test_m02_the_work_folder_is_not_carried(self):
        self.killed(check_every_answer_crosses_in_schema_order,
                    ("screens.nsh", '  ${If} $in_work_dir != ""\n    Push "Work folder"\n    Push "/WORK_DIR="\n    Push $in_work_dir\n    Call Carry_One\n  ${EndIf}\n', ""))

    def test_m03_the_value_is_not_quoted(self):
        self.killed(check_a_typed_value_reaches_the_child_as_typed, ("elevate.nsh", "  Push $carry_v\n  Call Cmdline_Quote\n  Pop $carry_t\n", "  StrCpy $carry_t $carry_v\n"))

    def test_m04_the_child_reads_no_answers_when_it_is_not_silent(self):
        self.killed(check_the_child_reads_every_answer_and_shows_only_the_secrets_page, ("main.nsi", "  ${OrIf} $carried == 1\n", ""))

    def test_m05_a_page_is_not_skipped(self):
        self.killed(check_the_child_reads_every_answer_and_shows_only_the_secrets_page,
                    ("screens.nsh", "Function Page_forge\n  ${If} $carried == 1\n    Abort\n  ${EndIf}\n", "Function Page_forge\n"))

    def test_m06_the_secrets_page_is_skipped_too(self):
        self.killed(check_the_child_reads_every_answer_and_shows_only_the_secrets_page,
                    ("screens.nsh", "Function Page_secrets\n", "Function Page_secrets\n  ${If} $carried == 1\n    Abort\n  ${EndIf}\n"))

    def test_m07_the_length_check_is_gone(self):
        self.killed(check_the_length_limit_is_exact, ("elevate.nsh", "  ${If} $carry_n > $carry_room\n    Call Carry_Bad\n    Return\n  ${EndIf}\n", ""))

    def test_m08_a_token_that_exactly_fits_is_refused(self):
        self.killed(check_the_length_limit_is_exact, ("elevate.nsh", "${If} $carry_n > $carry_room", "${If} $carry_n >= $carry_room"))

    def test_m09_restoring_the_1023_limit_starts_the_elevated_copy(self):
        self.killed(check_the_length_limit_is_exact, ("elevate.nsh", "IntOp $carry_room 1022 - $carry_n", "IntOp $carry_room 1023 - $carry_n"))

    def test_m10_ncrc_and_signer_come_after_the_answers(self):
        self.killed(check_the_order_is_ncrc_signer_elevated_then_the_answers_and_the_parents_own_words_are_dropped,
                    ("elevate.nsh", '  Call Carry_Begin\n  Push "/NCRC"', '  Call Carry_Begin\n  Call Carry_Answers\n  Push "/NCRC"'),
                    ("elevate.nsh", "  Call Carry_Token\n  Call Carry_Answers\n  ${If} $carry_bad", "  Call Carry_Token\n  ${If} $carry_bad"))

    def test_m11_the_licence_token_is_forced_to_yes(self):
        self.killed(check_licence_tokens_cross_as_typed_and_the_childs_gate_refuses_them,
                    ("screens.nsh", "    Push $in_engine_licence_accepted\n    Call Carry_One", '    Push "yes"\n    Call Carry_One'))

    def test_m12_a_declined_prompt_clears_an_answer(self):
        self.killed(check_a_declined_prompt_keeps_the_answers_and_the_next_try_hands_over_the_same_string,
                    ("elevate.nsh", "  declined:\n  MessageBox", '  declined:\n  StrCpy $in_work_dir ""\n  MessageBox'))

    def test_m13_rule_r_is_gone(self):
        self.killed(check_rule_r_refuses_what_the_elevated_copy_could_not_read_back,
                    ("elevate.nsh", '  ${If} $carry_t != ""\n  ${OrIf} $carry_n == " "\n    Call Carry_Bad\n    Return\n  ${EndIf}\n', ""))

    def test_m14_a_value_that_ends_in_a_blank_is_carried(self):
        self.killed(check_the_nsis_stub_sees_no_switch_in_what_is_handed_over, ("elevate.nsh", '  ${OrIf} $carry_n == " "\n', ""))
        self.killed(check_rule_r_refuses_what_the_elevated_copy_could_not_read_back, ("elevate.nsh", '  ${OrIf} $carry_n == " "\n', ""))

    def test_m15_the_carried_box_is_not_shown(self):
        self.killed(check_a_token_the_child_does_not_accept_ends_it_with_the_silent_exit_code_and_one_box,
                    ("elevate.nsh", '    MessageBox MB_OK|MB_ICONSTOP "The administrator step did not accept the answer $0 that the first window handed over. Nothing was started." /SD IDOK\n', ""))

    def test_m16_the_signer_is_not_carried(self):
        self.killed(check_the_order_is_ncrc_signer_elevated_then_the_answers_and_the_parents_own_words_are_dropped,
                    ("elevate.nsh", '    Push "The signer fingerprint"\n    Push "/SIGNER="\n    Push $0\n    Call Carry_One\n', ""))

    def test_m17_ncrc_is_not_carried(self):
        self.killed(check_the_nsis_stub_sees_no_switch_in_what_is_handed_over,
                    ("elevate.nsh", '    Push "The no-integrity-check option"\n    Push "/NCRC"\n    Call Carry_Token\n', ""))

    def test_m18_the_child_is_recognised_without_a_mode(self):
        self.killed(check_elevated_alone_is_the_wizard_and_a_silent_run_is_unchanged,
                    ("elevate.nsh", '  Push "/MODE="\n  Call Cmdline_Get\n  Pop $0\n  ${If} ${Errors}\n    Return\n  ${EndIf}\n', ""))

    def test_m19_the_back_button_stays_on_the_first_page_of_the_child(self):
        self.killed(check_the_child_reads_every_answer_and_shows_only_the_secrets_page, ("screens.nsh", "    EnableWindow $0 0\n", ""))

    def test_m20_a_bad_value_ends_the_child_without_a_box(self):
        self.killed(check_a_token_the_child_does_not_accept_ends_it_with_the_silent_exit_code_and_one_box, ("screens.nsh", "  Push $R0\n  Call Carried_Box\n", ""))

    def test_m21_a_silent_run_is_treated_as_a_carried_one(self):
        self.killed(check_elevated_alone_is_the_wizard_and_a_silent_run_is_unchanged,
                    ("elevate.nsh", '  ${If} ${Silent}\n    Return\n  ${EndIf}\n  Push "/ELEVATED"', '  Push "/ELEVATED"'))

    def test_m22_the_string_is_not_started_again_at_each_hand_over(self):
        self.killed(check_a_declined_prompt_keeps_the_answers_and_the_next_try_hands_over_the_same_string,
                    ("elevate.nsh", '  StrCpy $carry_args ""\n  StrCpy $carry_bad ""\n', '  StrCpy $carry_bad ""\n'))

    def test_m23_a_second_refused_answer_hides_the_first(self):
        self.killed(check_rule_r_refuses_what_the_elevated_copy_could_not_read_back,
                    ("elevate.nsh", '    StrCpy $carry_bad "$carry_bad, $carry_l"', "    StrCpy $carry_bad $carry_l"))

    def test_m24_the_refused_value_is_shown_in_the_box(self):
        self.killed(check_rule_r_refuses_what_the_elevated_copy_could_not_read_back,
                    ("elevate.nsh", "    StrCpy $carry_bad $carry_l\n  ${Else}", '    StrCpy $carry_bad "$carry_l=$carry_v"\n  ${Else}'))

    def test_m25_the_prompt_is_raised_although_an_answer_was_refused(self):
        self.killed(check_rule_r_refuses_what_the_elevated_copy_could_not_read_back,
                    ("elevate.nsh", '/SD IDOK\n    Return\n  ${EndIf}\n  ClearErrors', "/SD IDOK\n  ${EndIf}\n  ClearErrors"))

    def test_m26_an_unknown_key_ends_the_child_without_a_box(self):
        self.killed(check_a_token_the_child_does_not_accept_ends_it_with_the_silent_exit_code_and_one_box,
                    ("screens.nsh", '        Push "$vs_name"\n        Call Carried_Box\n', ""))

    def test_m27_the_licence_gate_ends_the_child_without_a_box(self):
        self.killed(check_a_token_the_child_does_not_accept_ends_it_with_the_silent_exit_code_and_one_box,
                    ("licence.nsh", '    Push "licences"\n    Call Carried_Box\n', ""))

    def test_m28_a_child_that_is_not_administrator_hands_on_nothing_it_read(self):
        self.killed(check_a_copy_that_is_still_not_administrator_hands_the_same_string_on, ("main.nsi", "  ${OrIf} $carried == 1\n", ""))


if __name__ == "__main__":
    unittest.main()
