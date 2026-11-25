"""SL-16e (ecosystem-control#114, part of #97 and #64): ONE command-line reader, installer/nsis/cmdline.nsh.
It serves the secret refusal, the silent-key check, the 14 keys, every choice's silent selection and the trust signer.
Rules: the text is $CMDLINE without the program name, which Cmdline_Begin skips itself (a name that starts with a double quote ends at the next one, any other at
the first blank or tab; it replaced ${GetParameters}, #136); a double quote toggles a quote state and is dropped; a blank or
a tab outside quotes ends a token; apostrophe, backtick and backslash are ordinary; an unclosed quote runs to the end; a key is the token text up
to its first "=", compared without case; the first token with a key wins. The old ${GetOptions} ended an unquoted value at the next "/" (an unquoted
URL was refused with exit 30) and kept a quote state for ' and ` (a lone apostrophe hid every later key). The NSIS reader runs in the shared
interpreter; schema.parse_silent must give the same answers (differential test). ${Errors} is IfErrors and clears the flag it tests, so the tests
run in StrictWorld.
SL16F (REV119): an unclosed double quote hid every later key, a secret key included. The secret refusal now also walks the RAW words (a second pass of
the same reader with the quote toggle off: Cmdline_BeginRaw, split_command_line(raw=True)), and a command line that ends inside a quote is exit 30, the
first check of the names pass (after 32 and 33, before 31)."""
import re
import unittest
from pathlib import Path

from installer import schema as S
from tests.nsis_interp import PROGRAM_PATH, Program, World, source_text

SCHEMA = S.load_schema()
IDS = [i["id"] for i in S.public_inputs(SCHEMA)]
URL = "https://github.com/owner/repo"
OBRIEN_EXE = "C:\\Users\\O'Brien\\setup.exe"
README = (Path(__file__).resolve().parent.parent / "installer" / "README.md").read_text(encoding="utf-8")
PASSES = "  !insertmacro RefuseLongCommandLine\n  !insertmacro RefuseSecretOptions\n  !insertmacro ParseSilentKeys\n  !insertmacro ValidateSilentKeys"
EACH = ('  Call Cmdline_Begin\n  ${Do}\n    Call Cmdline_Next\n    ${If} ${Errors}\n      ${ExitDo}\n    ${EndIf}\n'
        '    DetailPrint "$cl_name$\\n$cl_eq$\\n$cl_val"\n  ${Loop}')
EACH_RAW = EACH.replace("Call Cmdline_Begin\n", "Call Cmdline_BeginRaw\n")


class StrictWorld(World):
    """${Errors} is IfErrors, and IfErrors clears the flag it tests (NSIS script.cpp TOK_IFERRORS with mask 0, exec.c EW_IFFLAG). The shared World
    keeps the flag, which hid a reader that relied on it (the REV116 note in #117, item 4; the shared model itself is #109)."""

    def cond(self, t):
        if t == ["${Errors}"]:
            flag, self.errors = self.errors, False
            return flag
        return super().cond(t)


def program(body):
    files = source_text()
    files["probe.nsh"] = "Function Probe\n%s\nFunctionEnd\n" % body
    return Program(files)


def run(body, cmdline="", **kw):
    w = StrictWorld(cmdline=cmdline, program=program(body), **kw)
    return w, w.run("Probe")


def get(cmdline, key, **kw):
    """(value, key absent) from the real Cmdline_Get on a command line that follows the program path."""
    w, _ = run('  Push "%s"\n  Call Cmdline_Get\n  Pop $0' % key, cmdline, **kw)
    return w.var["0"], w.errors


def nsis_tokens(cmdline, raw=False, **kw):
    w, _ = run(EACH_RAW if raw else EACH, cmdline, **kw)
    return [(n, eq == "1", v) for n, eq, v in (d.split("\n", 2) for d in w.details)]


def py_tokens(cmdline, raw=False):
    return [(n, bool(sep), v) for n, sep, v in (t.partition("=") for t in S.split_command_line(cmdline, raw))]


def nsis_ends_in_quote(cmdline):
    w, _ = run("  Call Cmdline_EndsInQuote\n  Pop $0", cmdline)
    return w.var["0"] == "1"


def boot(cmdline, **kw):
    w = StrictWorld(cmdline=cmdline, silent=True, **kw)
    return w, w.run(".onInit")


def nsis_outcome(text):
    w = StrictWorld(cmdline=text, silent=True, program=program(PASSES))
    code = w.run("Probe")
    return code or 0, {i: w.var.get("in_" + i, "") for i in IDS}


def py_outcome(text, command_line_length=None):
    try:
        return 0, S.parse_silent(SCHEMA, text, command_line_length=command_line_length)
    except S.SchemaError as e:
        return S.exit_code(SCHEMA, e), None


def padded(total, head="/S /MODE=local /PARTNER_ID=", tail=""):
    """The text after the program name that makes the WHOLE command line (the interpreter's program path, a blank, this text) `total` characters long."""
    text = head + "x" * (total - len(PROGRAM_PATH) - 1 - len(head) - len(tail)) + tail
    assert len(PROGRAM_PATH + " " + text) == total
    return text


class Reader(unittest.TestCase):
    def test_an_unquoted_url_with_slashes_is_read_whole(self):
        self.assertEqual(get("/S /GITHUB_URL=" + URL + " /MODE=local", "/GITHUB_URL="), (URL, False))

    def test_the_same_url_in_double_quotes_is_read_whole_without_the_quotes(self):
        self.assertEqual(get('/S /GITHUB_URL="%s"' % URL, "/GITHUB_URL="), (URL, False))

    def test_a_blank_inside_double_quotes_stays_in_the_value_and_the_next_key_is_found(self):
        line = '/S /INSTALL_DIR="C:\\Program Files\\x" /MODE=local'
        self.assertEqual(get(line, "/INSTALL_DIR="), ("C:\\Program Files\\x", False))
        self.assertEqual(get(line, "/MODE="), ("local", False))

    def test_a_whole_quoted_token_gives_its_key_and_value(self):
        self.assertEqual(get('/S "/INSTALL_DIR=C:\\Program Files\\x"', "/INSTALL_DIR="), ("C:\\Program Files\\x", False))

    def test_an_apostrophe_or_a_backtick_in_a_value_is_ordinary_and_hides_no_later_key(self):
        for mark in ("'", "`"):
            with self.subTest(mark=mark):
                line = "/S /INSTALL_DIR=C:\\Users\\O%sBrien /MODE=local" % mark
                self.assertEqual(get(line, "/INSTALL_DIR="), ("C:\\Users\\O%sBrien" % mark, False))
                self.assertEqual(get(line, "/MODE="), ("local", False))

    def test_an_apostrophe_in_the_unquoted_program_path_hides_no_key(self):
        self.assertEqual(get("/S /MODE=local", "/MODE=", exe=OBRIEN_EXE), ("local", False))

    def test_a_key_inside_a_quoted_program_path_is_not_a_key(self):
        exe = '"C:\\Tools /MODE=github\\setup.exe"'
        self.assertEqual(get("/S", "/MODE=", exe=exe), ("", True))
        self.assertEqual(get("/S /MODE=local", "/MODE=", exe=exe), ("local", False))

    def test_a_key_inside_a_quoted_value_is_not_a_key(self):
        self.assertEqual(get('/S /INSTALL_DIR="a /MODE=github b"', "/MODE="), ("", True))

    def test_a_blank_and_a_slash_in_the_quoted_program_path_do_not_matter(self):
        for exe in ('"C:\\Temp\\setup - Copy.exe"', '"C:\\Temp\\a /x b\\setup.exe"'):
            with self.subTest(exe=exe):
                self.assertEqual(get("/S /MODE=local", "/MODE=", exe=exe), ("local", False))

    def test_an_empty_value_is_found_and_is_empty(self):
        self.assertEqual(get("/S /INSTALL_DIR= /MODE=local", "/INSTALL_DIR="), ("", False))
        self.assertEqual(get('/S /INSTALL_DIR="" /MODE=local', "/INSTALL_DIR="), ("", False))

    def test_a_key_without_an_equals_sign_is_absent(self):
        self.assertEqual(get("/S /MODE", "/MODE="), ("", True))

    def test_a_key_that_is_a_prefix_or_an_extension_of_another_never_matches(self):
        self.assertEqual(get("/S /MODEX=a", "/MODE="), ("", True))
        self.assertEqual(get("/S /MOD=a", "/MODE="), ("", True))
        self.assertEqual(get("/S /MODE=a", "/MODEX="), ("", True))

    def test_the_first_occurrence_of_a_key_wins(self):
        self.assertEqual(get("/S /MODE=local /MODE=github", "/MODE="), ("local", False))

    def test_the_key_is_matched_without_case_and_the_value_keeps_its_case(self):
        self.assertEqual(get("/S /mode=GitHub", "/MODE="), ("GitHub", False))
        self.assertEqual(get("/S /MODE=GitHub", "/mode="), ("GitHub", False))

    def test_the_value_runs_to_the_next_blank_and_keeps_later_equals_signs(self):
        self.assertEqual(get("/S /ALLOW_LIST=a=b,c /MODE=local", "/ALLOW_LIST="), ("a=b,c", False))

    def test_a_tab_ends_a_token_and_a_tab_inside_quotes_does_not(self):
        self.assertEqual(get("/S\t/MODE=local\t/PARTNER_ID=p", "/MODE="), ("local", False))
        self.assertEqual(get("/S\t/MODE=local\t/PARTNER_ID=p", "/PARTNER_ID="), ("p", False))
        self.assertEqual(get('/PARTNER_ID="a\tb" /MODE=local', "/PARTNER_ID="), ("a\tb", False))

    def test_an_unclosed_quote_runs_to_the_end_and_hides_what_follows(self):
        self.assertEqual(get('/S /INSTALL_DIR="C:\\Program Files\\x', "/INSTALL_DIR="), ("C:\\Program Files\\x", False))
        self.assertEqual(get('/S /INSTALL_DIR="a /MODE=local', "/MODE="), ("", True))

    def test_a_backslash_before_a_quote_is_not_an_escape(self):
        line = '/S /INSTALL_DIR="C:\\dir\\" /MODE=local'
        self.assertEqual(get(line, "/INSTALL_DIR="), ("C:\\dir\\", False))
        self.assertEqual(get(line, "/MODE="), ("local", False))

    def test_an_absent_key_sets_the_error_flag_and_a_found_key_clears_it(self):
        w, _ = run('  ClearErrors\n  Push "/NOPE="\n  Call Cmdline_Get\n  Pop $0', "/S /MODE=local")
        self.assertEqual((w.errors, w.var["0"]), (True, ""))
        w, _ = run('  SetErrors\n  Push "/MODE="\n  Call Cmdline_Get\n  Pop $0', "/S /MODE=local")
        self.assertEqual((w.errors, w.var["0"]), (False, "local"))

    def test_a_caller_that_tests_the_flag_after_the_reader_sees_absent_although_errors_clears_it(self):
        test = '  Pop $0\n  ${If} ${Errors}\n    StrCpy $1 absent\n  ${Else}\n    StrCpy $1 found\n  ${EndIf}'
        w, _ = run('  Push "/NOPE="\n  Call Cmdline_Get\n' + test, "/S /MODE=local")
        self.assertEqual((w.var["1"], w.var["0"]), ("absent", ""))
        w, _ = run('  Push "/MODE="\n  Call Cmdline_Get\n' + test, "/S /MODE=local")
        self.assertEqual((w.var["1"], w.var["0"]), ("found", "local"))

    def test_the_reader_leaves_the_stack_as_it_found_it(self):
        w, _ = run('  Push "keep"\n  Push "/MODE="\n  Call Cmdline_Get\n  Pop $0\n  Push "/NOPE="\n  Call Cmdline_Get\n  Pop $1', "/S /MODE=local")
        self.assertEqual(w.stack, ["keep"])


class Tokens(unittest.TestCase):
    CASES = [
        ("", []), ("   ", []), ("a", ["a"]), ("a  b", ["a", "b"]), ('a "b c" d', ["a", "b c", "d"]), ('"a b"c', ["a bc"]),
        ("a\tb", ["a", "b"]), ('"a\tb"', ["a\tb"]), ('""', [""]), ('a "" b', ["a", "", "b"]), ("it's `x`", ["it's", "`x`"]),
        ('"unclosed a b', ["unclosed a b"]), ('C:\\dir\\" x', ["C:\\dir\\ x"]), ('/K="a b"c d', ["/K=a bc", "d"]),
        ('"', [""]), ('a"b c"d e', ["ab cd", "e"]), ("/A=b=c", ["/A=b=c"]),
        ("a \t b", ["a", "b"]), ("a\t\tb", ["a", "b"]), ("\ta", ["a"]), ("\t \t", []), ("a\t ", ["a"]),
    ]

    def test_the_nsis_iterator_gives_these_tokens(self):
        for text, tokens in self.CASES:
            with self.subTest(text=text):
                got = [n + ("=" + v if eq else "") for n, eq, v in nsis_tokens(text)]
                self.assertEqual(got, tokens)

    def test_the_python_splitter_gives_the_same_tokens(self):
        for text, tokens in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(S.split_command_line(text), tokens)

    def test_a_token_splits_at_its_first_equals_sign_only(self):
        self.assertEqual(nsis_tokens("/A=b=c /D =x -"), [("/A", True, "b=c"), ("/D", False, ""), ("", True, "x"), ("-", False, "")])

    def test_the_iterator_keeps_reporting_the_end_once_it_is_reached(self):
        w, _ = run("  Call Cmdline_Begin\n  Call Cmdline_Next\n  Call Cmdline_Next\n  Call Cmdline_Next\n  StrCpy $0 $cl_name", "/S")
        self.assertTrue(w.errors)

    RAW = [
        ("", []), ("   ", []), ('a "b c" d', ["a", "b", "c", "d"]), ('"a b"c', ["a", "bc"]), ('"unclosed a b', ["unclosed", "a", "b"]), ('"', [""]), ('""', [""]),
        ('a "" b', ["a", "", "b"]), ('/K="a b"c d', ["/K=a", "bc", "d"]), ('/PARTNER_ID="abc /GITHUB_TOKEN=x', ["/PARTNER_ID=abc", "/GITHUB_TOKEN=x"]),
        ('"a\tb"', ["a", "b"]), ('C:\\dir\\" x', ["C:\\dir\\", "x"]), ("it's `x`", ["it's", "`x`"]), ("a\t \tb", ["a", "b"]), ('/PARTNER_ID="abc  -', ["/PARTNER_ID=abc", "-"]),
    ]

    def test_the_raw_mode_of_the_nsis_iterator_drops_a_quote_and_never_groups(self):
        for text, tokens in self.RAW:
            with self.subTest(text=text):
                self.assertEqual([n + ("=" + v if eq else "") for n, eq, v in nsis_tokens(text, raw=True)], tokens)

    def test_the_python_splitter_in_raw_mode_gives_the_same_tokens(self):
        for text, tokens in self.RAW:
            with self.subTest(text=text):
                self.assertEqual(S.split_command_line(text, raw=True), tokens)

    def test_both_modes_agree_between_the_nsis_iterator_and_the_python_splitter(self):
        for text, _ in self.CASES + self.RAW:
            for raw in (False, True):
                with self.subTest(text=text, raw=raw):
                    self.assertEqual(nsis_tokens(text, raw=raw), py_tokens(text, raw=raw))

    OPEN = [("", False), ("a", False), ('"', True), ('""', False), ('a "b', True), ('a "b"', False), ('a"b', True), ('"a" "b', True), ('"""', True), ('"a b" c', False),
            ("it's `x`", False), ('a "b c', True), ('/S /MODE=github "', True), ('/PARTNER_ID="abc /GITHUB_TOKEN=x', True), ("\t", False), ('"\t', True)]

    def test_the_nsis_reader_and_the_python_scan_report_the_same_open_quote(self):
        for text, want in self.OPEN:
            with self.subTest(text=text):
                self.assertEqual((nsis_ends_in_quote(text), S.scan_command_line(text)[1]), (want, want))
                self.assertEqual(S.scan_command_line(text)[0], S.split_command_line(text))

    def test_the_raw_mode_never_reports_an_open_quote(self):
        walk = "  Call Cmdline_BeginRaw\n  ${Do}\n    Call Cmdline_Next\n    ${If} ${Errors}\n      ${ExitDo}\n    ${EndIf}\n  ${Loop}\n  StrCpy $0 $cl_q"
        for text, _ in self.OPEN:
            with self.subTest(text=text):
                self.assertEqual(run(walk, text)[0].var["0"], "0")
                self.assertFalse(S.scan_command_line(text, raw=True)[1])

    def test_begin_resets_the_quote_flag_and_the_mode(self):
        w, _ = run("  StrCpy $cl_q 1\n  Call Cmdline_EndsInQuote\n  Pop $0", "")
        self.assertEqual(w.var["0"], "0")
        w, _ = run("  Call Cmdline_BeginRaw\n  Call Cmdline_Begin\n  Call Cmdline_Next\n  StrCpy $0 $cl_tok\n  StrCpy $1 $cl_raw", '"a b"')
        self.assertEqual((w.var["0"], w.var["1"]), ("a b", "0"))

    def test_the_text_is_trimmed_at_the_end_like_getparameters_does(self):
        # an unclosed quote used to keep the blanks ${GetParameters} had cut off
        for text, tokens in (('/PARTNER_ID="abc ', ["/PARTNER_ID=abc"]), ('/PARTNER_ID="abc   ', ["/PARTNER_ID=abc"]), ('a "b\t', ["a", "b\t"])):
            with self.subTest(text=text):
                self.assertEqual(S.split_command_line(text), tokens)
                self.assertEqual([n + ("=" + v if eq else "") for n, eq, v in nsis_tokens(text)], tokens)


# SL16F (REV119). An unclosed quote hid every later key, so the secret refusal also reads the raw words; a text that ends inside a quote is exit 30, after the
# refusals (32, 33) and before 31. A quoted value is not refused for what it holds, except a raw word that looks like a secret option (the over-refusal main had).
RAW_REFUSED = {
    '/S /MODE=github /PARTNER_ID="abc /GITHUB_TOKEN=x': 32, '/PARTNER_ID="abc  -': 33, '"/GITHUB_TOKEN=x"': 32, '/PARTNER_ID="abc /SECRETFILE=x': 33,
    '/INSTALL_DIR="C:\\a /KEYS"': 32, '/INSTALL_DIR="C:\\My - Folder"': 33,
    # SL16H (REV119B, M10): the refused word is the FIRST raw word, and the quote-aware pass sees one word (`/stdin b`, `- b`) that is not refused.
    '/stdin" b': 33, '-" b': 33,
}
# SL16H (REV119B item 4). An empty QUOTED value is an empty value once the quotes are dropped: the same bad value as `/MODE=`, exit 30, and it comes before an
# unknown key that follows it (never 31). `main` accepted it (0, or 31 for the unknown key). Pinned as exits, not only as agreement of the two readers.
EMPTY_QUOTED = {'/S /INSTALL_DIR=""': 30, '/S /PARTNER_ID=""': 30, '/S /PARTNER_ID="" /FOO': 30}
OPEN_QUOTE = ['/PARTNER_ID=a"b', '/MODE="', '/S /MODE=github "', '/S /MODE=github /FOO /PARTNER_ID="abc', '/S /MODE=github /INSTALL_DIR= /PARTNER_ID="abc',
              '/S /MODE=github /INSTALL_DIR /PARTNER_ID="abc', '/S "/MODE=local', '/S /MODE=github "a b']
NOT_REFUSED = ['/INSTALL_DIR="C:\\a b" /MODE=github', '/INSTALL_DIR="C:\\Program Files\\KeyTool"', '/S /MODE=github /INSTALL_DIR="C:\\Program Files\\KeyTool" /PARTNER_ID=p1']
# Cmdline_Begin trims the blanks at the end (as ${GetParameters} did); the Python reader kept them inside an unclosed quote. Every line here ends inside a quote.
UNCLOSED = [
    '/S /PARTNER_ID="abc ', '/S /PARTNER_ID="abc  ', '/PARTNER_ID="abc ', '/MODE=" ', '/S /MODE=github " ', '/S /INSTALL_DIR="C:\\Program Files\\x ', '" ', '"   ',
    '/S "a b ', '/S /MODE=github /PARTNER_ID="a\t', '/S "/MODE=local ', '/S /ALLOW_LIST="a, b ', '/S /WORK_DIR="C:\\w /MODE=local ', '/S /INSTALL_DIR="C:\\dir\\ ',
    '/S /MODE=github /GITHUB_URL="https://github.com/o/r ',
]
# Every case holds only valid values: the NSIS value checks run after the token loop and are not what is compared here.
CORPUS = [
    "", "   ", "/S", "/s", "/S /MODE=local", "/S /mode=GitHub",
    "/S /MODE=github /GITHUB_URL=" + URL,
    '/S /MODE=github /GITHUB_URL="%s"' % URL,
    '/S "/GITHUB_URL=%s"' % URL,
    "/S /INSTALL_DIR=C:\\Users\\O'Brien /MODE=local",
    "/S /WORK_DIR=C:\\a`b /MODE=local",
    '/S /INSTALL_DIR="C:\\Program Files\\x" /MODE=local',
    '/S "/INSTALL_DIR=C:\\Program Files\\x" /MODE=local',
    '/S /INSTALL_DIR="C:\\Program Files\\x',
    '/S /INSTALL_DIR="C:\\dir\\" /MODE=local',
    "/S\t/MODE=local\t/PARTNER_ID=p1",
    "/S /MODE=local /MODE=github",
    "/S /partner_id=Mixed /PARTNER_ID=other",
    "/S /ALLOW_LIST=a.example,b.example /LABVIEW_VERSION=2024",
    "/S /PARTNER_ID=a=b",
    "/S /D=C:\\x /NCRC /ELEVATED /SIGNER=" + "a" * 64 + " /S=1",
    "/S foo a=b TOKEN=x -x -=x",
    '/S ""',
    "/S /MODE= /PARTNER_ID=p1",
    '/S /PARTNER_ID="" /MODE=local',
    "/S /MODE",
    "/S /INSTALL_DIR=x /WORK_DIR",
    "/S /MODEX=local",
    "/S /MOD=local",
    "/S /FOO",
    "/S /FOO=1",
    "/S /",
    "/S /=x",
    "/S /FOO /GITHUB_TOKEN=x",
    "/S /GITHUB_TOKEN=x",
    "/S /gitlab_token=x",
    "/S /MYPASSWORD=x",
    "/S /SECRETFILE=x",
    "/S /stdin",
    "/S -",
    '/S "-"',
    "/S /MODE=local - /FOO",
    "/S /FOO=1 /SECRETS=x",
    "/S /INSTALL_DIR=O'Brien /GITHUB_TOKEN=x",
    '/S "/GITHUB_TOKEN=x"',
] + list(RAW_REFUSED) + list(EMPTY_QUOTED) + OPEN_QUOTE + NOT_REFUSED + UNCLOSED
# Read correctly, but the NSIS value check (not what is compared above) refuses a tab in a text value.
TOKEN_ONLY = ['/S /PARTNER_ID="a\tb" /MODE=local']


class Differential(unittest.TestCase):
    def test_the_nsis_reader_and_parse_silent_agree_on_every_case(self):
        for text in CORPUS:
            with self.subTest(text=text):
                n_code, n_values = nsis_outcome(text)
                p_code, p_values = py_outcome(text)
                self.assertEqual(n_code, p_code)
                if p_code == 0:
                    self.assertEqual(n_values, {i: p_values.get(i, "") for i in IDS})

    def test_the_nsis_iterator_and_the_python_splitter_agree_on_every_case(self):
        for text in CORPUS + TOKEN_ONLY:
            with self.subTest(text=text):
                self.assertEqual(nsis_tokens(text), py_tokens(text))

    def test_the_corpus_reaches_every_token_level_exit_and_both_answers_are_pinned(self):
        self.assertEqual({py_outcome(t)[0] for t in CORPUS}, {0, 30, 31, 32, 33})
        pinned = {
            "/S /MODE=github /GITHUB_URL=" + URL: 0,
            "/S /INSTALL_DIR=C:\\Users\\O'Brien /MODE=local": 0,
            "/S /MODE=local /MODE=github": 0,
            "/S /MODE": 30, "/S /MODE=": 30, "/S /FOO": 31, "/S /MODEX=local": 31,
            "/S /FOO /GITHUB_TOKEN=x": 32, "/S /INSTALL_DIR=O'Brien /GITHUB_TOKEN=x": 32,
            "/S -": 33, '/S "-"': 33, "/S /SECRETFILE=x": 33,
            '/S /INSTALL_DIR="C:\\Program Files\\x': 30,
            **RAW_REFUSED, **EMPTY_QUOTED, **{t: 30 for t in OPEN_QUOTE + UNCLOSED}, **{t: 0 for t in NOT_REFUSED},
        }
        for text, code in pinned.items():
            with self.subTest(text=text):
                self.assertEqual((nsis_outcome(text)[0], py_outcome(text)[0]), (code, code))

    def test_an_empty_quoted_value_is_exit_30_in_both_readers_and_in_oninit_and_the_key_is_named_before_an_unknown_key(self):
        for text, code in EMPTY_QUOTED.items():
            with self.subTest(text=text):
                self.assertEqual((nsis_outcome(text)[0], py_outcome(text)[0], boot(text)[1] or 0), (code, code, code))
        self.assertEqual(boot('/S /PARTNER_ID="" /FOO')[0].log, [("bad-value", "/PARTNER_ID", "30")])
        self.assertEqual(boot('/S /INSTALL_DIR=""')[0].log, [("bad-value", "/INSTALL_DIR", "30")])
        with self.assertRaises(S.BadValue) as cm:
            S.parse_silent(SCHEMA, '/S /PARTNER_ID="" /FOO')
        self.assertIn("needs a value", str(cm.exception))
        # the order inside the names pass is the order of the words: an unknown key BEFORE the empty value is still 31
        self.assertEqual((boot('/S /FOO /PARTNER_ID=""')[1], py_outcome('/S /FOO /PARTNER_ID=""')[0]), (31, 31))

    def test_the_first_occurrence_wins_in_both(self):
        self.assertEqual(py_outcome("/S /MODE=local /MODE=github")[1], {"mode": "local"})
        self.assertEqual(nsis_outcome("/S /MODE=local /MODE=github")[1]["mode"], "local")

    def test_parse_silent_still_takes_an_already_split_list(self):
        self.assertEqual(S.parse_silent(SCHEMA, ["/S", "/INSTALL_DIR=C:\\Program Files\\x"]), {"install_dir": "C:\\Program Files\\x"})


class OpenQuote(unittest.TestCase):
    """SL16F (REV119 BLOCKER): the same answers from the NSIS passes, from parse_silent and from the whole .onInit."""

    def test_each_case_gives_its_exit_in_the_nsis_passes_in_parse_silent_and_in_oninit(self):
        cases = {**RAW_REFUSED, **{t: 30 for t in OPEN_QUOTE + UNCLOSED}, **{t: 0 for t in NOT_REFUSED}}
        for text, code in cases.items():
            with self.subTest(text=text):
                self.assertEqual((nsis_outcome(text)[0], py_outcome(text)[0], boot(text)[1] or 0), (code, code, code))

    def test_the_accepted_lines_keep_their_values(self):
        w, code = boot('/S /MODE=github /INSTALL_DIR="C:\\Program Files\\KeyTool" /PARTNER_ID=p1')
        self.assertEqual((code, w.var["in_install_dir"], w.var["in_mode"]), (None, "C:\\Program Files\\KeyTool", "github"))
        self.assertEqual(py_outcome('/S /MODE=github /INSTALL_DIR="C:\\Program Files\\KeyTool" /PARTNER_ID=p1')[1],
                         {"mode": "github", "install_dir": "C:\\Program Files\\KeyTool", "partner_id": "p1"})

    def test_the_refusal_wins_over_the_open_quote(self):
        for text in ('/S /MODE=github /PARTNER_ID="abc /GITHUB_TOKEN=x', '/PARTNER_ID="abc  -', '/PARTNER_ID="abc /SECRETFILE=x'):
            with self.subTest(text=text):
                self.assertEqual((boot(text)[1], py_outcome(text)[0]), (RAW_REFUSED[text],) * 2)

    def test_the_open_quote_is_the_first_check_of_the_names_pass(self):
        # before 31 (an unknown key) and before the missing-value check, so the one log line names the command line and not a key
        for text in ('/S /MODE=github /FOO /PARTNER_ID="abc', '/S /MODE=github /INSTALL_DIR= /PARTNER_ID="abc', '/S /MODE=github /INSTALL_DIR /PARTNER_ID="abc'):
            with self.subTest(text=text):
                w, code = boot(text)
                self.assertEqual((code, w.log), (30, [("bad-value", "command-line", "30")]))
                with self.assertRaises(S.BadValue) as cm:
                    S.parse_silent(SCHEMA, text)
                self.assertIn("ends inside a double quote", str(cm.exception))
        self.assertEqual(boot("/S /MODE=github /FOO /PARTNER_ID=abc")[1], 31)
        w, code = boot("/S /MODE=github /INSTALL_DIR= /PARTNER_ID=abc")
        self.assertEqual((code, w.log), (30, [("bad-value", "/INSTALL_DIR", "30")]))

    def test_the_open_quote_is_logged_with_fixed_words_and_never_with_the_swallowed_text(self):
        text = '/S /MODE=github /PARTNER_ID="swallowed-value more'
        w, code = boot(text)
        self.assertEqual((code, w.log), (30, [("bad-value", "command-line", "30")]))
        self.assertNotIn("swallowed", repr(w.log) + repr(w.stack))
        with self.assertRaises(S.BadValue) as cm:
            S.parse_silent(SCHEMA, text)
        self.assertNotIn("swallowed", str(cm.exception))

    def test_an_interactive_launch_does_not_check_the_quote_but_still_refuses_the_raw_words(self):
        w = StrictWorld(cmdline='/PARTNER_ID="abc', silent=False)
        self.assertIsNone(w.run(".onInit"))
        for text, code in (('/PARTNER_ID="abc /GITHUB_TOKEN=x', 32), ('/PARTNER_ID="abc  -', 33)):
            with self.subTest(text=text):
                self.assertEqual(StrictWorld(cmdline=text, silent=False).run(".onInit"), code)

    def test_the_unclosed_lines_agree_between_the_nsis_iterator_and_the_python_splitter(self):
        for text in UNCLOSED:
            with self.subTest(text=text):
                self.assertTrue(S.scan_command_line(text)[1] and nsis_ends_in_quote(text))
                self.assertEqual(nsis_tokens(text), py_tokens(text))

    def test_a_token_list_has_neither_the_raw_pass_nor_the_open_quote_check(self):
        self.assertEqual(S.parse_silent(SCHEMA, ["/S", "/INSTALL_DIR=C:\\a /KEYS"]), {"install_dir": "C:\\a /KEYS"})

    def test_the_stdin_refusal_still_comes_first(self):
        with self.assertRaises(S.SecretFromFileOrStdin):
            S.parse_silent(SCHEMA, '/S /PARTNER_ID="abc', stdin_is_secret=True)


class EndToEnd(unittest.TestCase):
    def test_an_unquoted_url_is_accepted_and_was_refused_before(self):
        w, code = boot("/S /MODE=github /GITHUB_URL=" + URL)
        self.assertEqual((code, w.var["in_github_url"]), (None, URL))

    def test_the_same_url_in_double_quotes_is_accepted(self):
        w, code = boot('/S /MODE=github /GITHUB_URL="%s"' % URL)
        self.assertEqual((code, w.var["in_github_url"]), (None, URL))

    def test_a_key_after_an_apostrophe_value_is_still_read(self):
        w, code = boot("/S /INSTALL_DIR=C:\\Users\\O'Brien /MODE=github")
        self.assertEqual((code, w.var["in_mode"], w.var["in_install_dir"]), (None, "github", "C:\\Users\\O'Brien"))

    def test_a_secret_after_an_apostrophe_value_is_still_refused_with_32(self):
        w, code = boot("/S /INSTALL_DIR=O'Brien /MODE=github /GITHUB_TOKEN=x")
        self.assertEqual(code, 32)

    def test_a_program_path_with_an_apostrophe_gives_the_same_run_as_a_plain_path(self):
        plain, c1 = boot("/S /MODE=github")
        quirky, c2 = boot("/S /MODE=github", exe=OBRIEN_EXE)
        self.assertEqual((c1, c2, quirky.var["in_mode"]), (None, None, plain.var["in_mode"]))
        self.assertEqual(boot("/S /MODE=github /GITHUB_TOKEN=x", exe=OBRIEN_EXE)[1], 32)

    def test_the_program_paths_of_pr_112_are_still_fine(self):
        for exe in ('"C:\\Temp\\setup - Copy.exe"', '"C:\\Temp\\a /x b\\setup.exe"'):
            with self.subTest(exe=exe):
                w, code = boot("/S /MODE=github", exe=exe)
                self.assertEqual((code, w.var["in_mode"]), (None, "github"))

    def test_a_secret_word_or_a_dash_in_a_quoted_program_path_is_not_an_option(self):
        w, code = boot("/S /MODE=github", exe='"C:\\Tools - x\\secret-token\\setup.exe"')
        self.assertEqual(code, None)

    def test_an_empty_mode_is_a_bad_mode_logged_by_the_mode_step(self):
        w, code = boot("/S /MODE=")
        self.assertEqual((code, w.log), (30, [("mode", "/MODE", "30")]))

    def test_a_key_without_an_equals_sign_is_a_missing_value_of_the_names_pass_and_never_an_empty_mode(self):
        # Cmdline_Get must give "absent" for the token /MODE: the mode step then leaves the mode alone and ValidateSilentKeys reports the missing value
        w, code = boot("/S /MODE")
        self.assertEqual((code, w.log, w.var["in_mode"]), (30, [("bad-value", "/MODE", "30")], ""))
        w, code = boot("/S /MODE /PARTNER_ID=p1")
        self.assertEqual((code, w.log), (30, [("bad-value", "/MODE", "30")]))

    def test_the_mode_is_read_by_the_one_reader_with_a_quoted_value(self):
        w, code = boot('/S "/MODE=local"')
        self.assertEqual((code, w.var["in_mode"]), (None, "local"))

    def test_a_secret_in_a_quoted_whole_token_is_refused(self):
        self.assertEqual(boot('/S /MODE=github "/GITHUB_TOKEN=x"')[1], 32)
        self.assertEqual(boot('/S /MODE=github "-"')[1], 33)

    def test_the_trust_step_reads_the_signer_with_the_one_reader(self):
        body = Program().functions["TrustCheck"].split("  Call TrustCanonicalHex64")[0] + "  Pop $TrustSigner"
        signer = "ab" * 32
        w, _ = run(body, "/S /INSTALL_DIR=O'Brien /SIGNER=" + signer, exe=OBRIEN_EXE)
        self.assertEqual(w.var["TrustSigner"], signer)
        w, _ = run(body, "/S", exe='"C:\\Tools /SIGNER=%s\\setup.exe"' % signer)
        self.assertEqual(w.var["TrustSigner"], "")


class SilentMode(unittest.TestCase):
    """Mode_FromSilent tests ${Errors} right after Cmdline_Get: no /MODE= key leaves the mode alone, in a World whose ${Errors} clears the flag."""

    def mode(self, cmdline):
        w = StrictWorld(cmdline=cmdline, silent=True)
        return w.run("Mode_FromSilent"), w.var.get("in_mode", "")

    def test_a_silent_run_without_the_mode_key_leaves_the_mode_alone(self):
        for line in ("/S", "/S /INSTALL_DIR=C:\\x", '/S /INSTALL_DIR="C:\\Program Files\\x"', "/S /MODEX=local", "/S /MODE", "/S /MODE /INSTALL_DIR=C:\\x"):
            self.assertEqual(self.mode(line), (None, ""), line)

    def test_each_valid_mode_is_selected_and_any_other_value_ends_with_30(self):
        self.assertEqual(self.mode("/S /MODE=local"), (None, "local"))
        self.assertEqual(self.mode("/S /mode=GitHub"), (None, "github"))
        self.assertEqual(self.mode("/S /MODE=gitlab"), (None, "gitlab"))
        self.assertEqual(self.mode("/S /MODE=bogus")[0], 30)


class Quote(unittest.TestCase):
    CASES = [("plain", "plain"), ("C:\\Program Files\\x", '"C:\\Program Files\\x"'), ("a\tb", '"a\tb"'), ("O'Brien Ltd", '"O\'Brien Ltd"'),
             (URL, URL), ("", "")]

    def test_a_value_with_a_blank_or_a_tab_is_wrapped_in_double_quotes_and_reads_back(self):
        for value, quoted in self.CASES:
            with self.subTest(value=value):
                w, _ = run('  Push "%s"\n  Call Cmdline_Quote\n  Pop $1' % value.replace("\t", "$\\t"), "")
                self.assertEqual(w.var["1"], quoted)
                if value:
                    self.assertEqual(get("/INSTALL_DIR=" + w.var["1"] + " /MODE=local", "/INSTALL_DIR="), (value, False))
                    self.assertEqual(get("/INSTALL_DIR=" + w.var["1"] + " /MODE=local", "/MODE="), ("local", False))


class ProgramName(unittest.TestCase):
    """#136, REPORT L3: Cmdline_Begin skips the program name itself, so a one-letter name and a tab after the name are no longer special."""

    def test_a_program_named_s_without_an_extension_keeps_its_first_parameter(self):
        # CreateProcess hands over `s /FOO /S`; through cmd.exe the text had two blanks (REPORT L3)
        for text in ("/FOO /S", " /FOO /S"):
            with self.subTest(text=text):
                self.assertEqual(boot(text, exe="s")[1], 31)
                self.assertEqual(py_outcome(text)[0], 31)

    def test_a_quoted_name_ends_at_the_next_quote_and_an_unclosed_one_leaves_no_parameters(self):
        self.assertEqual(boot("/FOO /S", exe='"C:\\p q\\s.exe"')[1], 31)
        self.assertIsNone(boot("", exe='"C:\\p q\\s.exe /FOO /S')[1])

    def test_a_tab_after_the_name_ends_it_like_a_blank(self):
        self.assertEqual(boot("s\t/FOO /S", exe=None)[1], 31)
        self.assertEqual(boot('"C:\\p q\\s.exe"\t/FOO /S', exe=None)[1], 31)
        self.assertEqual(py_outcome("\t/FOO /S")[0], 31)


class CutLine(unittest.TestCase):
    """#136, REPORT L2 and C10: NSIS cuts $CMDLINE at 1023 characters, so a line of 1023 or more is refused with exit 50, before every other command-line check."""

    def test_the_longest_whole_line_is_1022_characters_and_from_1023_on_the_exit_is_50_in_both_readers(self):
        for total, expected in ((1021, 0), (1022, 0), (1023, 50), (1024, 50), (1500, 50)):
            text = padded(total)
            with self.subTest(total=total):
                self.assertEqual(nsis_outcome(text)[0], expected)
                self.assertEqual(py_outcome(text, command_line_length=total)[0], expected)

    def test_on_init_runs_through_at_1022_and_at_1023_ends_at_once_with_one_log_step_and_nothing_written(self):
        w, code = boot(padded(1022))
        self.assertIsNone(code)
        self.assertIn("TrustCheck", w.trace)
        w, code = boot(padded(1023))
        self.assertEqual(code, 50)
        self.assertEqual(w.log, [("cmdline-too-long", "command-line", "50")])
        self.assertEqual((w.boxes, w.files), ([], StrictWorld(cmdline="", silent=True).files))
        for step in ("Carried_Detect", "Mode_FromSilent", "TrustCheck"):
            self.assertNotIn(step, w.trace)

    def test_an_interactive_run_is_refused_too(self):
        w = StrictWorld(cmdline=padded(1023), silent=False)
        self.assertEqual(w.run(".onInit"), 50)
        self.assertEqual(w.boxes, [])

    def test_the_50_check_comes_before_the_secret_and_value_checks(self):
        for tail, before in ((" /GITHUB_TOKEN=x", 32), (" /SECRETFILE=x", 33), (' /PARTNER_ID="abc', 30)):
            for total, expected in ((1022, before), (1023, 50)):
                text = padded(total, tail=tail)
                with self.subTest(tail=tail, total=total):
                    self.assertEqual(nsis_outcome(text)[0], expected)
                    self.assertEqual(py_outcome(text, command_line_length=total)[0], expected)
                    self.assertEqual(boot(text)[1], expected)

    def test_the_python_reader_checks_the_length_only_when_it_is_given_one(self):
        text = padded(1500)
        self.assertEqual(py_outcome(text)[0], 0)
        with self.assertRaises(S.CommandLineTooLong) as caught:
            S.parse_silent(SCHEMA, text, command_line_length=1023)
        self.assertEqual(S.exit_code(SCHEMA, caught.exception), 50)
        log = []
        self.assertEqual(S.run_silent(SCHEMA, text, "x", None, None, command_line_length=1023, log=log), 50)
        self.assertIn("cmdline-too-long: the command line is 1023 characters or more", log)


class OneReader(unittest.TestCase):
    CODE = {n: [l.strip() for l in t.splitlines() if l.strip() and not l.strip().startswith(";")] for n, t in source_text().items()}

    def test_no_installer_script_calls_getoptions_or_wordfind(self):
        for name, lines in self.CODE.items():
            for line in lines:
                with self.subTest(file=name, line=line):
                    self.assertNotRegex(line, r"(?i)GetOptions|WordFind|WordFunc")

    def test_only_the_reader_and_the_length_check_read_cmdline_and_no_script_calls_getparameters(self):
        # #136: Cmdline_Begin skips the program name itself, so it reads $CMDLINE; the one other reader is the generated exit-50 check, which only measures it
        for name, lines in self.CODE.items():
            for line in lines:
                with self.subTest(file=name, line=line):
                    self.assertNotIn("${GetParameters}", line)
                    if "$CMDLINE" in line:
                        self.assertTrue(name == "cmdline.nsh" or (name, line) == ("screens.nsh", "StrLen $vs_c $CMDLINE"))
        self.assertEqual([l for l in self.CODE["screens.nsh"] if "$CMDLINE" in l], ["StrLen $vs_c $CMDLINE"])

    def test_cmdline_nsh_has_the_reader_functions_and_skips_the_program_name_in_cmdline_begin_only(self):
        text = (Path(__file__).resolve().parent.parent / "installer" / "nsis" / "cmdline.nsh").read_text(encoding="utf-8")
        for fn in ("Cmdline_Begin", "Cmdline_BeginRaw", "Cmdline_Next", "Cmdline_EndsInQuote", "Cmdline_Get", "Cmdline_Quote"):
            self.assertRegex(text, r"(?m)^Function %s$" % fn)
        # REV187: the block each code line sits in, not whether the same text also appears in Cmdline_Begin
        owner, owners = None, []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith(";"):
                continue
            start = re.fullmatch(r"(Function|!macro) (\S+).*", line)
            if start:
                self.assertIsNone(owner, line)
                owner = start.group(1, 2)
            elif line in ("FunctionEnd", "!macroend"):
                owner = None
            elif "$CMDLINE" in line:
                owners.append(owner)
        self.assertGreaterEqual(len(owners), 1)
        # REV187B: by kind and name, so a !macro Cmdline_Begin is not taken for the function
        self.assertEqual(set(owners), {("Function", "Cmdline_Begin")})
        self.assertEqual(self.CODE["cmdline.nsh"].count('StrCpy $cl_text $CMDLINE "" $cl_pos'), 1)
        self.assertNotIn("${GetParameters}", "\n".join(self.CODE["cmdline.nsh"]))

    def test_every_silent_read_goes_through_cmdline_get(self):
        wired = [i for i in SCHEMA["inputs"] if i.get("setter")]
        screens = "\n".join(self.CODE["screens.nsh"])
        self.assertEqual(screens.count("Call Cmdline_Get"), len(S.public_inputs(SCHEMA)) + len(wired))
        self.assertIn('Push "/SIGNER="', self.CODE["trust.nsh"])
        self.assertEqual(self.CODE["trust.nsh"].count("Call Cmdline_Get"), 1)

    def test_both_loops_use_the_iterator(self):
        screens = source_text()["screens.nsh"]
        refuse = re.search(r"(?ms)^Function Refuse_Pass\n(.*?)^FunctionEnd", screens).group(1)
        validate = re.search(r"(?ms)^!macro ValidateSilentKeys\n(.*?)^!macroend", screens).group(1)
        self.assertIn("Call Cmdline_Next", refuse)
        self.assertIn("Call Cmdline_Begin\n", validate)
        self.assertIn("Call Cmdline_Next", validate)

    def test_the_refusal_runs_one_pass_of_the_quote_aware_reader_and_one_of_the_raw_mode_with_one_copy_of_the_rules(self):
        screens = source_text()["screens.nsh"]
        body = re.search(r"(?ms)^!macro RefuseSecretOptions\n(.*?)^!macroend", screens).group(1)
        calls = [l.strip() for l in body.splitlines() if l.strip() and not l.strip().startswith(";")]
        self.assertEqual(calls, ["Call Cmdline_Begin", "Call Refuse_Pass", "Call Cmdline_BeginRaw", "Call Refuse_Pass"])
        self.assertEqual(screens.count("Function Refuse_Pass\n"), 1)

    def test_the_raw_mode_is_a_mode_of_the_one_reader_and_the_generated_code_never_touches_its_state(self):
        screens = "\n".join(self.CODE["screens.nsh"])
        self.assertEqual(self.CODE["cmdline.nsh"].count("Function Cmdline_Next"), 1)
        for var in ("$cl_raw", "$cl_q", "$cl_pos", "$cl_text"):
            self.assertNotIn(var, screens)
        for name, lines in self.CODE.items():
            if name != "cmdline.nsh":
                self.assertFalse([l for l in lines if "$cl_raw" in l], name)

    def test_the_names_pass_checks_the_open_quote_before_it_starts_its_loop(self):
        body = re.search(r"(?ms)^!macro ValidateSilentKeys\n(.*?)^!macroend", source_text()["screens.nsh"]).group(1)
        first = body.split("Call Cmdline_Begin\n")[0]
        self.assertIn("Call Cmdline_EndsInQuote\n", first)
        self.assertIn('Push "bad-value"\n    Push "command-line"\n    Call Silent_Bad\n', first)

    def test_the_generated_screens_are_not_out_of_date(self):
        self.assertTrue(S.check_drift(SCHEMA))

    def test_main_includes_the_reader_once(self):
        self.assertEqual(self.CODE["main.nsi"].count('!include "cmdline.nsh"'), 1)

    def test_the_reader_hides_no_warning_both_makensis_wx_builds_pass_without_the_6010_pragma(self):
        self.assertEqual([l for l in self.CODE["cmdline.nsh"] if l.startswith("!pragma")], [])


# The ten command lines of the real-Windows run (#121): (row, as the README shows it, the exit expected on Windows, the exit of the model). P = `I /S /MODE=github`
# with I the installer; a row that starts with another word names the program (row 8: `s`). Row 9 is the ` /D=` limit of the NSIS stub, measured on Windows
# (REPORT L2, C9): the model keeps the text, so its answer differs from the expected exit on purpose. Row 10 is the cut line (C10), refused with exit 50 (#136).
PROBE_P = "/S /MODE=github"
PROBE = [
    (1, "P /GITHUB_URL=https://github.com/o/r", 0, 0),
    (2, 'P /PARTNER_ID="abc /GITHUB_TOKEN=x', 32, 32),
    (3, 'P /PARTNER_ID="abc', 30, 30),
    (4, 'P "-"', 33, 33),
    (5, 'P /INSTALL_DIR="C:\\a b"', 0, 0),
    (6, 'P /INSTALL_DIR="C:\\a /KEYS"', 32, 32),
    (7, 'P /PARTNER_ID=""', 30, 30),
    (8, "s /FOO /S", 31, 31),
    (9, "P /D=C:\\X /FOO", 0, 31),
    (10, "P /PARTNER_ID=<1000 x> /FOO", 50, 50),
]


def probe_run(shown):
    """(program, parameters) of a probe row as the model runs it."""
    first, _, rest = shown.partition(" ")
    if first == "P":
        return "setup.exe", (PROBE_P + " " + rest).replace("<1000 x>", "x" * 1000)
    return first, rest


class Readme(unittest.TestCase):
    BULLET = next(l for l in README.splitlines() if l.startswith("- **One command-line reader")).lower()
    SILENT = next(l for l in README.splitlines() if l.startswith("- **Silent run.**")).lower()
    OPEN = next(l for l in README.splitlines() if l.startswith("- **Open quote and the raw pass")).lower()
    NOT_VERIFIED = next(l for l in README.splitlines() if l.startswith("- **Not verified on Windows")).lower()

    def test_it_says_how_a_value_is_quoted(self):
        for phrase in ("double quote", "no escape", "apostrophe", "backtick", "unclosed", "first", "cmdline.nsh"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.BULLET)

    def test_it_shows_the_unquoted_url_as_valid(self):
        self.assertIn("/github_url=https://github.com/owner/repo", self.BULLET)
        self.assertNotIn("must be quoted", README.lower())
        self.assertNotIn("cut at its first", README.lower())

    def test_it_says_the_reader_skips_the_program_name_itself_and_the_limits_of_getparameters_are_gone(self):
        for phrase in ("skips the program name itself", "next double quote", "first blank or tab", "replaced `${getparameters}`", "#136", "report l3"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.BULLET)
        self.assertNotIn("is not a separator", self.BULLET)

    def test_the_one_letter_limit_is_gone_and_the_header_says_why(self):
        self.assertIn("one letter and no extension", self.BULLET)
        self.assertIn("`s /foo /s`", self.BULLET)
        self.assertNotRegex(README, r"(?<!\w)s\.exe /|Temp\\s\.exe", "the old probe: s.exe has five letters and does not show the limit")
        header = source_text()["cmdline.nsh"].split("!include", 1)[0]
        self.assertIn("it replaces ${GetParameters} (#136, REPORT L3)", header)
        self.assertIn("THIRD character", header)
        self.assertNotIn("ONE letter makes", header)

    def test_the_elevated_relaunch_goes_through_the_one_reader_since_sl21b(self):
        for text in (self.SILENT, self.BULLET):
            with self.subTest(text=text[:30]):
                for phrase in ("#117", "elevate_raise", "cmdline_has", "cmdline_quote"):
                    self.assertIn(phrase, text)
                for phrase in ("elevate.nsh:74", "raw `${getparameters}` text", "one exception", "except the elevated relaunch"):
                    self.assertNotIn(phrase, text)

    def test_the_two_nsis_limits_are_labelled_measured_and_the_cut_line_is_refused_with_50(self):
        for phrase in ("measured on windows 11 build 26300", "report l2", "c9", "c10", "main.c", "` /d=...`", "everything after it", "the elevated relaunch loses it",
                       "1023 characters", "1022 characters", "exit 50", "cmdline-too-long", "before every other", "command_line_length"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.BULLET)
        for phrase in ("source-read", "not measured on windows", "not yet measured"):
            with self.subTest(gone=phrase):
                self.assertNotIn(phrase, self.BULLET)

    def test_the_open_quote_and_raw_pass_bullet_names_the_pieces_and_the_documented_limits(self):
        for phrase in ("cmdline_beginraw", "$cl_raw", "split_command_line(text, raw=true)", "function refuse_pass", "refusesecretoptions", "twice",
                       "cmdline_endsinquote", "scan_command_line", "ends inside a double quote", "exits 30", "first check of the names pass",
                       "32 or 33, then 30, then 31", "bad-value", "command-line", "never the swallowed text", "neither adds an exit code",
                       '/install_dir="c:\\a /keys"` exits 32', '/install_dir="c:\\my - folder"` exits 33', "exactly as `main` did",
                       '/install_dir="c:\\program files\\keytool"` is accepted', "documented limits"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.OPEN)

    def test_the_silent_run_bullet_gives_the_order_of_the_exits_and_the_log_words(self):
        for phrase in ("32 or 33", "ends inside a double quote", "bad-value", "command-line", "never the swallowed text", "then the names", "cmdline-too-long"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.SILENT)
        self.assertLess(self.SILENT.index("order of the exits is: 50 ("), self.SILENT.index("32 or 33"))

    def test_the_windows_probe_list_has_the_new_cases(self):
        for phrase in ("unclosed double quote", "tab between two parameters", "named `s` without an extension", "1023 characters", "` /d=` parameter"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.NOT_VERIFIED)

    def test_the_windows_probe_lists_the_ten_rows_with_the_exit_expected_on_windows(self):
        self.assertIn("`p` = `i /s /mode=github`", self.NOT_VERIFIED)
        for row, shown, expected, _ in PROBE:
            with self.subTest(row=row):
                self.assertIn(("(%d) `%s` exits %d" % (row, shown, expected)).lower(), self.NOT_VERIFIED)
        self.assertEqual(len(re.findall(r"\(\d+\) `", self.NOT_VERIFIED)), len(PROBE))

    def test_the_windows_probe_names_what_is_new_in_rows_5_to_8(self):
        for phrase in ("an empty quoted value", "the documented over-refusal", "the raw pass sees the word `/keys\"`", 'start /wait ""', "createprocess",
                       "started by `start`", "window title", "0 would mean `/foo` was dropped", "the model says 31", "differ from the model on purpose"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.NOT_VERIFIED)
        self.assertEqual(self.NOT_VERIFIED.count("the model says 31"), 1)

    def test_the_probe_rows_give_the_model_exit_and_only_row_9_differs_from_the_expected_exit(self):
        for row, shown, expected, model in PROBE:
            program, parameters = probe_run(shown)
            with self.subTest(row=row):
                self.assertEqual(boot(parameters, exe=program)[1] or 0, model)
                self.assertEqual(model != expected, row == 9)
        self.assertEqual([py_outcome(probe_run(s)[1])[0] for r, s, e, m in PROBE if r in range(1, 8)], [m for r, s, e, m in PROBE if r in range(1, 8)])

    def test_no_guest6c_text_here_because_the_sl23_pin_on_develop_forbids_it_in_the_readme(self):
        flat = re.sub(r"\s*\n\s*", " ", README)
        self.assertNotIn("GUEST6C", flat)
        self.assertNotIn("is to prove them", flat)
        self.assertIsNone(re.search(r"resolves?\s+(?:a|the|any|every|each|all)\s+links?\b", flat))
        self.assertIn("(guest6, #121)", self.NOT_VERIFIED)


# (class, the example as the README shows it with \t for a TAB, NSIS exit on main and now, Python exit on main and now). The main side is the answer of
# main (baf0434, the base of this branch) measured over 5299 command lines by a scratch run that is not in the repository (the three rows of the empty
# quoted value, SL16H, by the same run on those lines); the head side is run below. Class 15 (#136) is the answer of develop (a5a7ae7) against this branch.
DEVIATIONS = [
    (1, "\\t/GITHUB_TOKEN=x", (0, 32), (32, 32)), (1, "\\t/FOO", (0, 31), (31, 31)), (1, "/MODE=local\\t/KEYS", (30, 32), (32, 32)),
    (1, "/S\\t-x", (31, 0), (31, 0)),
    (2, "/MODE=local -x", (30, 0), (31, 0)), (2, "/MODE=github a=b", (30, 0), (31, 0)),
    (3, "/INSTALL_DIR=C:\\O'Brien /MODE=local", (0, 0), (0, 0)),
    (4, "/GITHUB_URL=https://github.com/o/r", (30, 0), (0, 0)),
    (5, '"/GITHUB_TOKEN=x"', (0, 32), (32, 32)), (5, '"-"', (0, 33), (31, 33)), (5, '"/MODE=local"', (0, 0), (31, 0)),
    (6, '/PARTNER_ID=a"b /PARTNER_ID=a"b', (30, 0), (0, 0)),
    (7, '"', (0, 30), (31, 30)), (7, '/ "', (31, 30), (31, 30)), (7, '/S /MODE=github /FOO /PARTNER_ID="abc', (31, 30), (31, 30)),
    (7, '/PARTNER_ID=a"b', (30, 30), (0, 30)), (7, '/MODE="', (30, 30), (0, 30)),
    (8, '"/GITHUB_TOKEN=x" -', (33, 32), (32, 32)), (8, '"-" /KEYS', (32, 33), (31, 33)), (8, '/INSTALL_DIR="C:\\a /KEYS" /stdin', (32, 33), (32, 33)),
    (9, "/NCRC", (0, 0), (31, 0)), (9, "/D=C:\\x", (0, 0), (31, 0)), (9, "/ELEVATED", (0, 0), (31, 0)),
    (10, "-x", (0, 0), (31, 0)), (10, "TOKEN=x", (0, 0), (32, 0)), (10, "foo", (0, 0), (31, 0)),
    (10, '/INSTALL_DIR="C:\\Program Files\\KeyTool"', (0, 0), (32, 0)),
    (11, "/MODE /KEYS", (32, 32), (30, 32)), (11, "/ /KEYS", (32, 32), (31, 32)), (11, "/ -", (33, 33), (31, 33)),
    (12, "/MODE=", (30, 30), (0, 30)),
    (12, '/INSTALL_DIR=""', (0, 30), (0, 30)), (12, '/PARTNER_ID=""', (0, 30), (0, 30)), (12, '/PARTNER_ID="" /FOO', (31, 30), (31, 30)),
    (13, "/MODE=github /MODE=local", (0, 0), (0, 0)),
    (14, '/INSTALL_DIR="C:\\a /KEYS"', (32, 32), (32, 32)), (14, '/INSTALL_DIR="C:\\My - Folder"', (33, 33), (33, 33)),
    (14, '/S /MODE=github /PARTNER_ID="abc /GITHUB_TOKEN=x', (32, 32), (32, 32)),
    (15, "/PARTNER_ID=<1000 x> /FOO", (31, 50), (31, 50)),
]


def arrow_cell(before, after):
    return "%d same" % after if before == after else "%d \u2192 %d" % (before, after)


class Deviations(unittest.TestCase):
    """The README table of the differences from main: each row is pinned to the answers of this branch, and no README row goes unpinned."""
    ROWS = [l.strip() for l in README.splitlines() if re.match(r"\s*\| \d+ \|", l)]

    def test_the_readme_table_and_this_list_hold_the_same_rows(self):
        self.assertEqual(len(self.ROWS), len(DEVIATIONS))
        self.assertEqual({c for c, *_ in DEVIATIONS}, set(range(1, 16)))
        for cls, example, n, p in DEVIATIONS:
            with self.subTest(example=example):
                pattern = r"^\| %d \|[^|]*\| `%s` \| %s \| %s \|$" % (cls, re.escape(example), arrow_cell(*n), arrow_cell(*p))
                self.assertEqual(sum(bool(re.match(pattern, r)) for r in self.ROWS), 1, pattern)

    def test_every_row_gives_the_answers_of_this_branch_in_both_readers(self):
        for cls, example, n, p in DEVIATIONS:
            text = example.replace("\\t", "\t").replace("<1000 x>", "x" * 1000)
            with self.subTest(example=example):
                length = len(PROGRAM_PATH) + 1 + len(text)
                self.assertEqual((boot(text)[1] or 0, py_outcome(text, command_line_length=length)[0]), (n[1], p[1]))

    def test_the_rows_that_keep_the_exit_pin_the_values_that_changed(self):
        w, _ = boot("/INSTALL_DIR=C:\\O'Brien /MODE=local")
        self.assertEqual((w.var["in_install_dir"], w.var["in_mode"]), ("C:\\O'Brien", "local"))
        self.assertEqual(py_outcome("/INSTALL_DIR=C:\\O'Brien /MODE=local")[1], {"install_dir": "C:\\O'Brien", "mode": "local"})
        w, _ = boot('"/MODE=local"')
        self.assertEqual(w.var["in_mode"], "local")
        self.assertEqual(py_outcome('"/MODE=local"')[1], {"mode": "local"})
        w, _ = boot('/PARTNER_ID=a"b /PARTNER_ID=a"b')
        self.assertEqual(w.var["in_partner_id"], "ab /PARTNER_ID=ab")
        self.assertEqual(py_outcome('/PARTNER_ID=a"b /PARTNER_ID=a"b')[1], {"partner_id": "ab /PARTNER_ID=ab"})
        self.assertEqual(py_outcome("/MODE=github /MODE=local")[1], {"mode": "github"})
        w, _ = boot("/MODE=github /MODE=local")
        self.assertEqual(w.var["in_mode"], "github")

    def test_the_python_pass_through_words_include_the_signer(self):
        self.assertEqual(py_outcome("/SIGNER=" + "ab" * 32), (0, {}))


if __name__ == "__main__":
    unittest.main()
