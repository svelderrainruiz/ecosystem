"""SL-16d: the command-line loops end (WordFind needs the E option), and the interpreter models the real WordFind and GetOptions."""
import copy
import re
import signal
import unittest

from installer import schema as S
from tests import nsis_interp
from tests.nsis_interp import World, word_find, get_options
from tests.test_installer_sl16a import init, BAD, UNKNOWN

SCHEMA = S.load_schema()
SECRET_CL = SCHEMA["exit_codes"]["secret-on-command-line"]
SECRET_FILE = SCHEMA["exit_codes"]["secret-from-file-or-stdin"]
GENERATED = S.generate_nsh(SCHEMA)


class WordFindModel(unittest.TestCase):
    def test_words_are_numbered_from_one(self):
        self.assertEqual(word_find("a b c", " ", "E+1"), ("a", False))
        self.assertEqual(word_find("a b c", " ", "E+3"), ("c", False))

    def test_a_double_blank_makes_no_empty_word(self):
        self.assertEqual(word_find("a  b", " ", "E+2"), ("b", False))

    def test_a_trailing_delimiter_makes_no_word(self):
        self.assertEqual(word_find("a b ", " ", "E+3"), ("2", True))
        self.assertEqual(word_find("a b ", " ", "E+2"), ("b", False))

    def test_a_string_without_the_delimiter_is_error_1_even_for_the_first_word(self):
        self.assertEqual(word_find("abc", " ", "E+1"), ("1", True))

    def test_a_number_beyond_the_count_is_error_2(self):
        self.assertEqual(word_find("a b", " ", "E+3"), ("2", True))

    def test_without_E_an_error_returns_the_input_and_sets_no_flag(self):
        self.assertEqual(word_find("abc", " ", "+1"), ("abc", False))
        self.assertEqual(word_find("a b", " ", "+3"), ("a b", False))

    def test_E_may_come_first_only_as_a_letter_and_other_forms_are_refused(self):
        with self.assertRaises(ValueError):
            word_find("a b", " ", "E/x")

    def test_the_inner_equals_call_without_E_gives_the_whole_word_when_there_is_no_equals_sign(self):
        self.assertEqual(word_find("/SECRETFILE", "=", "+1"), ("/SECRETFILE", False))
        self.assertEqual(word_find("/A=b", "=", "+1"), ("/A", False))

    def test_the_instruction_sets_the_flag_in_the_world(self):
        w = World(cmdline="a b", exe=None)
        w.step(["${WordFind}", "$CMDLINE", " ", "E+3", "$R1"], {})
        self.assertEqual((w.errors, w.var["R1"]), (True, "2"))
        w.step(["${WordFind}", "$CMDLINE", " ", "+3", "$R1"], {})
        self.assertEqual((w.errors, w.var["R1"]), (False, "a b"))


class GetOptionsModel(unittest.TestCase):
    def test_the_value_ends_at_the_next_slash_not_at_a_blank(self):
        self.assertEqual(get_options("/A=x y /B=z", "/A="), "x y")

    def test_a_quoted_value_keeps_its_slashes_and_loses_one_pair_of_quotes(self):
        self.assertEqual(get_options('/GITHUB_URL="https://x.example/p"', "/GITHUB_URL="), "https://x.example/p")

    def test_an_unquoted_url_is_cut_at_its_first_slash(self):
        self.assertEqual(get_options("/GITHUB_URL=https://x.example", "/GITHUB_URL="), "https:")

    def test_the_name_is_found_without_regard_to_case(self):
        self.assertEqual(get_options("/github_url=ab", "/GITHUB_URL="), "ab")

    def test_a_missing_option_gives_none(self):
        self.assertIsNone(get_options("/S /B=1", "/A="))
        self.assertIsNone(get_options("", "/A="))

    def test_a_slash_inside_quotes_does_not_start_an_option(self):
        self.assertIsNone(get_options('/B="/A=1"', "/A="))

    def test_single_quotes_and_backticks_are_stripped_too(self):
        self.assertEqual(get_options("/A='x y'", "/A="), "x y")
        self.assertEqual(get_options("/A=`x`", "/A="), "x")

    def test_unequal_quotes_are_kept(self):
        self.assertEqual(get_options('/A="x\'', "/A="), "\"x'")

    def test_the_value_is_trimmed_on_both_sides(self):
        self.assertEqual(get_options("/A=   x   /B=1", "/A="), "x")


class LoopsEnd(unittest.TestCase):
    CASES = [
        ("", None), ("/S", None), ("/S /MODE=github", None),
        ("/S /FOO", UNKNOWN), ("/FOO", UNKNOWN),
        ("/SECRETFILE", SECRET_FILE), ("/S /SECRETFILE", SECRET_FILE), ("/S  /SECRETFILE=x", SECRET_FILE),
        ("/TOKEN", SECRET_CL), ("/S /GITHUB_TOKEN=x", SECRET_CL), ("/S   /MODE=github  /TOKEN", SECRET_CL),
        ("/S /PARTNER_ID=ACME-1 ", None), ('/S /PARTNER_ID="a\tb"', BAD),
        (" ".join(["/S"] * 40), None), (" ".join(["/S"] * 40 + ["/TOKEN"]), SECRET_CL),
        ('/S /INSTALL_DIR="C:\\Program Files\\x"', None),
    ]

    def test_every_command_line_ends_with_the_right_exit_code_in_a_silent_run(self):
        for cmd, want in self.CASES:
            with self.subTest(cmd=cmd):
                self.assertEqual(init(cmd)[1], want)

    def test_an_interactive_launch_returns_too(self):
        for cmd, want in (("", None), ("/NCRC", None), ("/TOKEN", SECRET_CL), ("/SECRETFILE", SECRET_FILE)):
            with self.subTest(cmd=cmd):
                self.assertEqual(init(cmd, silent=False)[1], want)

    def test_both_loops_end_on_the_error_flag_the_one_reader_sets_at_the_end_and_no_wordfind_is_left(self):
        # SL-16e: Cmdline_Next sets the error flag at the end of the parameters; ${WordFind} (which needed the E option for that) is not used any more
        # SL-16f: the refusal loop is Function Refuse_Pass (run twice by its macro)
        loops = {"Refuse_Pass": GENERATED.split("Function Refuse_Pass\n")[1].split("FunctionEnd")[0],
                 "ValidateSilentKeys": GENERATED.split("!macro ValidateSilentKeys\n")[1].split("!macroend")[0]}
        for name, body in loops.items():
            with self.subTest(loop=name):
                self.assertIn("  ${Do}\n    Call Cmdline_Next\n    ${If} ${Errors}\n      ${ExitDo}\n    ${EndIf}\n", body)
        self.assertNotIn("WordFind", GENERATED)

    def test_a_loop_that_never_ends_is_stopped_by_the_cap(self):
        w = World()
        w.program.compile = lambda name: ([["jmp", None, 0]], {})

        def hang(*_):
            raise RuntimeError("the interpreter loops for ever: no cap")

        old = signal.signal(signal.SIGALRM, hang)
        signal.alarm(10)
        try:
            with self.assertRaisesRegex(AssertionError, "NSIS loop does not end"):
                w.call("anything")
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)

    def test_the_cap_does_not_stop_a_long_but_finite_command_line(self):
        # the longest whole line is 1022 characters, program path included; from 1023 on the run ends at once with exit 50 (#136)
        w, code = init(" ".join(["/S"] * ((1022 - len(nsis_interp.PROGRAM_PATH)) // 3)))
        self.assertGreater(len(w.var["CMDLINE"]), 1000)
        self.assertIsNone(code)
        self.assertEqual(init(" ".join(["/S"] * 1500))[1], 50)


class ValuesAreNormalised(unittest.TestCase):
    VALUES = {"install_dir": "C:\\x", "ni_licence_held": "YES", "engine_licence_accepted": "Yes", "image_variant": "LINUX", "image_year": "2026q1"}

    def test_the_two_licence_answers_and_the_choices_are_stored_in_lower_case(self):
        v = dict(self.VALUES)
        S.validate_values(SCHEMA, v)
        self.assertEqual((v["ni_licence_held"], v["engine_licence_accepted"], v["image_variant"]), ("yes", "yes", "linux"))

    def test_an_upper_case_answer_passes_the_licence_gate_and_finds_the_pinned_digest(self):
        from installer import licences
        v = dict(self.VALUES)
        S.validate_values(SCHEMA, v)
        licences.require_both(v)
        pinned = copy.deepcopy(SCHEMA)
        for e in pinned["images"]["list"]:
            e["digest"] = "sha256:" + "a" * 64
            e["repository"] = "registry.example/ni/labview"
        self.assertTrue(S.pinned_digest(pinned, v["image_variant"], v["image_year"]).startswith("sha256:"))

    def test_the_pinned_lookup_stays_case_sensitive(self):
        pinned = copy.deepcopy(SCHEMA)
        for e in pinned["images"]["list"]:
            e["digest"] = "sha256:" + "a" * 64
            e["repository"] = "registry.example/ni/labview"
        with self.assertRaises(S.ImageNotPinned):
            S.pinned_digest(pinned, "LINUX", "2026q1")


class EditControlsAreLimited(unittest.TestCase):
    def test_every_generated_edit_control_has_a_text_limit_of_1023(self):
        lines = [l.strip() for l in GENERATED.splitlines()]
        creates = [n for n, l in enumerate(lines) if l.startswith(("${NSD_CreateText}", "${NSD_CreatePassword}"))]
        self.assertTrue(creates)
        for n in creates:
            handle = lines[n + 1].split()[1]
            self.assertTrue(lines[n + 1].startswith("Pop $ctl_"), lines[n + 1])
            self.assertEqual(lines[n + 2], "SendMessage %s ${EM_LIMITTEXT} 1023 0" % handle)

    def test_no_other_control_gets_a_limit(self):
        self.assertEqual(GENERATED.count("${EM_LIMITTEXT}"), len(re.findall(r"\$\{NSD_Create(Text|Password)\}", GENERATED)))


if __name__ == "__main__":
    unittest.main()
