"""SL-16c (ecosystem-control#110, part of #97 and #64): the command-line loops skip the program name.
INST-REQ-023, 075, 098 (a secret option is refused on every launch), 026 (exits 30 and 31 in a silent run), 029 (Elevate_Raise, the one raise),
021 (typed values keep their case). $CMDLINE always starts with the program path, quoted when it holds a blank; the loops read
${GetParameters} (FileFunc.nsh, NSIS 3.10) instead of $CMDLINE, and the test interpreter models that function. No Windows, no network."""
import unittest

from installer import schema as S
from tests.nsis_interp import World, PROGRAM_PATH, get_parameters

SCHEMA = S.load_schema()
CODES = SCHEMA["exit_codes"]
SECRET_CL, SECRET_FILE = CODES["secret-on-command-line"], CODES["secret-from-file-or-stdin"]
UNKNOWN = CODES["unknown-key"]
GENERATED = S.generate_nsh(SCHEMA)
COPY = '"C:\\Users\\Jo\\setup - Copy.exe"'
SLASH = '"C:\\Tools /v2\\setup.exe"'


def boot(cmdline, silent=True):
    """.onInit on exactly this $CMDLINE, program path included."""
    return World(cmdline=cmdline, silent=silent, exe=None).run(".onInit")


class GetParametersModel(unittest.TestCase):
    """Each expectation is traced by hand through FileFunc.nsh GetParameters_ (lines 1445-1496)."""

    def test_a_quoted_program_path_with_a_blank_is_removed(self):
        self.assertEqual(get_parameters('"C:\\a b\\setup.exe" /S'), "/S")

    def test_an_unquoted_program_is_removed_up_to_the_first_blank(self):
        self.assertEqual(get_parameters("setup.exe /S /MODE=x"), "/S /MODE=x")

    def test_a_quoted_path_alone_has_no_parameters(self):
        self.assertEqual(get_parameters('"C:\\a - b\\s.exe"'), "")

    def test_an_empty_command_line_and_a_bare_program_name_have_no_parameters(self):
        self.assertEqual(get_parameters(""), "")
        self.assertEqual(get_parameters("x.exe"), "")

    def test_blanks_are_trimmed_on_both_sides_and_kept_inside(self):
        self.assertEqual(get_parameters('"C:\\a b\\s.exe"   /S    /MODE=x   '), "/S    /MODE=x")
        self.assertEqual(get_parameters("setup.exe     /S"), "/S")
        self.assertEqual(get_parameters("setup.exe     "), "")

    def test_the_separator_is_a_quote_only_when_the_first_character_is_one(self):
        self.assertEqual(get_parameters('"C:\\a b\\s.exe" /S'), "/S")
        self.assertEqual(get_parameters('s"x.exe /S'), "/S")
        self.assertEqual(get_parameters('setup.exe /A="b c" /S'), '/A="b c" /S')

    def test_the_scan_starts_at_the_third_character(self):
        # A quirk of the real library: a one-character program name hides the blank at offset 1.
        self.assertEqual(get_parameters("a /S"), "")
        self.assertEqual(get_parameters('"a" /S'), "/S")

    def test_a_quote_that_is_never_closed_swallows_the_rest(self):
        self.assertEqual(get_parameters('"C:\\a b\\setup.exe /S'), "")


class TheInstruction(unittest.TestCase):
    def test_it_sets_only_its_target_and_leaves_registers_stack_and_error_flag_alone(self):
        for flag in (False, True):
            with self.subTest(flag=flag):
                w = World(cmdline="/S /MODE=x", exe='"C:\\a b\\setup.exe"')
                kept = {r: "keep-" + r for r in ["0", "1", "2", "3"] + ["R%d" % n for n in range(10) if n != 5]}
                w.var.update(kept)
                w.stack, w.errors = ["below"], flag
                w.step(["${GetParameters}", "$R5"], {})
                self.assertEqual(w.var["R5"], "/S /MODE=x")
                self.assertEqual({r: w.var[r] for r in kept}, kept)
                self.assertEqual((w.stack, w.errors), (["below"], flag))

    def test_the_world_puts_the_program_path_in_front_of_the_parameters(self):
        w = World(cmdline="/S")
        self.assertEqual(w.var["CMDLINE"], PROGRAM_PATH + " /S")
        self.assertEqual(w.var["EXEPATH"], PROGRAM_PATH.strip('"'))
        self.assertEqual(World(cmdline="/S", exe=None).var["CMDLINE"], "/S")
        self.assertEqual(World().var["CMDLINE"], PROGRAM_PATH)


class TheLoopsSkipTheProgramName(unittest.TestCase):
    def test_a_dash_in_a_quoted_program_path_is_not_a_secret_from_standard_input(self):
        for silent in (True, False):
            for cmd in (COPY, COPY + " /S"):
                with self.subTest(silent=silent, cmd=cmd):
                    self.assertIsNone(boot(cmd, silent))

    def test_a_secret_word_in_a_quoted_program_path_is_not_a_secret_option(self):
        for silent in (True, False):
            with self.subTest(silent=silent):
                self.assertIsNone(boot('"C:\\Tools /secret\\setup.exe" /S', silent))

    def test_a_real_secret_option_after_such_a_path_is_still_refused(self):
        cases = ((COPY + " /S /SECRETS", SECRET_FILE), (COPY + " /S /SECRETFILE=x", SECRET_FILE),
                 (COPY + " /S /GITHUB_TOKEN=x", SECRET_CL), (COPY + " /TOKEN", SECRET_CL))
        for silent in (True, False):
            for cmd, want in cases:
                with self.subTest(silent=silent, cmd=cmd):
                    self.assertEqual(boot(cmd, silent), want)

    def test_a_real_lone_dash_argument_still_exits_33(self):
        for silent in (True, False):
            for cmd in ('"C:\\Program Files\\x\\setup.exe" -', COPY + " -", COPY + " /S -", "setup.exe -"):
                with self.subTest(silent=silent, cmd=cmd):
                    self.assertEqual(boot(cmd, silent), SECRET_FILE)

    def test_a_slash_inside_the_quoted_program_path_is_not_an_unknown_key(self):
        self.assertIsNone(boot(SLASH + " /S"))
        self.assertEqual(boot(SLASH + " /S /FOO"), UNKNOWN)

    def test_an_unquoted_program_a_quoted_path_without_parameters_and_an_empty_command_line(self):
        self.assertIsNone(boot("setup.exe /S"))
        self.assertEqual(boot("setup.exe /S /FOO"), UNKNOWN)
        self.assertEqual(boot("setup.exe /TOKEN", False), SECRET_CL)
        for silent in (True, False):
            with self.subTest(silent=silent):
                self.assertIsNone(boot('"C:\\a b\\setup.exe"', silent))
                self.assertIsNone(boot("", silent))

    def test_each_loop_starts_the_one_reader_before_it_and_never_reads_the_command_line(self):
        # SL-16e: the reader (cmdline.nsh) is the one place that calls ${GetParameters}; each loop only starts it and takes its tokens
        # SL-16f: the refusal loop is Function Refuse_Pass; its macro starts the reader before each of the two passes (quote-aware, then raw)
        def code(text):
            return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(";"))

        refuse = code(GENERATED.split("!macro RefuseSecretOptions\n")[1].split("!macroend")[0])
        self.assertEqual([l.strip() for l in refuse.splitlines()], ["Call Cmdline_Begin", "Call Refuse_Pass", "Call Cmdline_BeginRaw", "Call Refuse_Pass"])
        refuse_pass = code(GENERATED.split("Function Refuse_Pass\n")[1].split("FunctionEnd")[0])
        self.assertNotIn("Call Cmdline_Begin", refuse_pass)
        self.assertIn("Call Cmdline_Next\n", refuse_pass.split("${Do}")[1])
        validate = code(GENERATED.split("!macro ValidateSilentKeys\n")[1].split("!macroend")[0])
        self.assertEqual(validate.count("Call Cmdline_Begin"), 1)
        self.assertIn("Call Cmdline_Begin\n", validate.split("${Do}")[0])
        self.assertIn("Call Cmdline_Next\n", validate.split("${Do}")[1])
        for body in (refuse, refuse_pass, validate):
            self.assertNotIn("$CMDLINE", body)
            self.assertNotIn("${GetParameters}", body)


class ElevateRaise(unittest.TestCase):
    """SL-21b: the string that Elevate_Raise hands over is /NCRC and /SIGNER= of the parent, /ELEVATED, then the typed answers; the program path is never in it."""

    @staticmethod
    def raised(exe, params, **answers):
        w = World(cmdline=params, exe=exe, admin=False)
        w.var.update(answers)
        w.run("Elevate_Raise")
        return w.shell

    def test_the_program_path_is_the_file_and_never_part_of_the_parameters(self):
        for exe in (COPY, SLASH, PROGRAM_PATH, "setup.exe"):
            for params, want in (("/S /MODE=local", "/ELEVATED"), ("/NCRC /SIGNER=ab12", "/NCRC /SIGNER=ab12 /ELEVATED"), ("", "/ELEVATED")):
                with self.subTest(exe=exe, params=params):
                    (verb, file, text), = self.raised(exe, params)
                    self.assertEqual((verb, file), ("runas", exe.strip('"')))
                    self.assertEqual(text.count(exe.strip('"')), 0)
                    self.assertEqual(text, want)

    def test_the_answers_keep_their_quotes_and_the_one_elevated_marker_comes_before_them(self):
        (_, _, text), = self.raised(COPY, "", in_install_dir="C:\\Program Files\\x")
        self.assertEqual(text, '/ELEVATED /INSTALL_DIR="C:\\Program Files\\x"')

    def test_the_command_line_of_the_elevated_child_passes_both_loops(self):
        (_, file, text), = self.raised(COPY, "", in_mode="local", in_install_dir="C:\\Program Files\\x")
        self.assertIsNone(boot('"%s" %s' % (file, text), silent=False))


class ValuesKeepTheirCase(unittest.TestCase):
    """Only the licence answers and the choices are lower-cased; every other value, a secret included, keeps its case."""
    KEEP = {"install_dir": "C:\\Program Files\\X", "work_dir": "D:\\Work Dir\\Big", "github_url": "https://GitHub.Example.com/Org",
            "gitlab_url": "https://GitLab.Example.com/Group/Project", "http_proxy": "http://Proxy.Example.com:3128",
            "partner_id": "Acme-Partner-01", "labview_version": "2024 Q3", "allow_list": "Alpha.Example.com,Beta.Example.com",
            "dns_servers": "Dns.Example.com,Other.Example.com", "github_token": "ghs_AbCd1234"}
    LOWER = {"mode": "GitHub", "ni_licence_held": "YES", "engine_licence_accepted": "Yes", "image_variant": "LINUX", "image_year": "2025q3"}

    def test_text_path_url_list_and_secret_values_keep_their_case_and_licence_and_choice_values_do_not(self):
        values = dict(self.KEEP, **self.LOWER)
        S.validate_values(SCHEMA, values)
        for key, value in self.KEEP.items():
            self.assertEqual(values[key], value, key)
        for key, value in self.LOWER.items():
            self.assertEqual(values[key], value.lower(), key)


if __name__ == "__main__":
    unittest.main()
