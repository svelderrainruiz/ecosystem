"""SL-15 (ecosystem-control#98, part of #97 and #64): the NSIS installer selects the runner mode and reads the silent keys.
INST-REQ-020 (modes), 023 (no secret on the command line, in a file or on standard input), 025, 026 (typed exits), 034 to 036 (runner modes), 066.
The NSIS functions run in a small interpreter (tests/nsis_interp.py) over the real script text; no Windows, no network."""
import copy
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer import footprint, runners, schema as S
from tests.nsis_interp import World, Program, NSIS
from tests.test_installer_sl13 import func

ROOT = Path(__file__).resolve().parent.parent
MAIN = (NSIS / "main.nsi").read_text(encoding="utf-8")
SCREENS = (NSIS / "screens.nsh").read_text(encoding="utf-8")
INSTALL = (NSIS / "install.nsh").read_text(encoding="utf-8")
SCHEMA = S.load_schema()
MODE_ERRORS = SCHEMA["exit_codes"]
STATE = "C:\\ProgramData\\EcosystemRunner\\"


def init(cmdline, silent=True, admin=True):
    w = World(cmdline=cmdline, silent=silent, admin=admin)
    return w, w.run(".onInit")


class SchemaMode(unittest.TestCase):
    def test_mode_is_the_first_page_and_a_choice_of_three_020_034_035_036(self):
        self.assertEqual(SCHEMA["pages"][0]["id"], "mode")
        spec = [i for i in SCHEMA["inputs"] if i["id"] == "mode"][0]
        self.assertEqual((spec["kind"], spec["choices"], spec["page"]), ("choice", ["local", "github", "gitlab"], "mode"))
        self.assertEqual(S.screen_list(SCHEMA)[0], {"page": "mode", "title": "What this PC does", "inputs": ["mode"]})
        self.assertEqual(S.silent_keys(SCHEMA)["/MODE"], "mode")

    def test_the_schema_stays_valid_and_the_generated_include_has_no_drift(self):
        S.validate_schema(SCHEMA)
        self.assertTrue(S.check_drift(SCHEMA))

    def test_reference_validation_knows_the_three_values_and_refuses_others_026(self):
        for v in ("local", "github", "gitlab"):
            S.validate_values(SCHEMA, {"mode": v, "install_dir": "x"})
        with self.assertRaises(S.BadValue):
            S.validate_values(SCHEMA, {"mode": "nonsense", "install_dir": "x"})
        self.assertEqual(S.parse_silent(SCHEMA, ["/S", "/MODE=github"]), {"mode": "github"})

    def test_a_setter_needs_a_choice_alone_on_an_unconditional_page(self):
        bad = copy.deepcopy(SCHEMA)
        [i for i in bad["inputs"] if i["id"] == "mode"][0]["kind"] = "text"
        with self.assertRaises(S.SchemaError):
            S.validate_schema(bad)
        bad = copy.deepcopy(SCHEMA)
        bad["inputs"].append({"id": "extra", "label": "x", "kind": "text", "page": "mode"})
        with self.assertRaises(S.SchemaError):
            S.validate_schema(bad)

    def test_typed_value_and_control_handles_are_separate_variables(self):
        self.assertIn("Var in_mode\n", SCREENS)
        for c in ("local", "github", "gitlab"):
            self.assertIn("Var ctl_mode_%s\n" % c, SCREENS)
        page = func(SCREENS, "Page_mode")
        self.assertNotIn("Pop $in_mode", page)
        self.assertEqual(page.count("Pop $ctl_mode_"), 3)
        self.assertEqual(page.count("NSD_CreateFirstRadioButton"), 1)
        self.assertEqual(page.count("NSD_CreateAdditionalRadioButton"), 2)
        self.assertNotIn("NSD_Check", page)


class InitOrder(unittest.TestCase):
    def test_on_init_order_is_pinned_as_text(self):
        body = func(MAIN, ".onInit")
        at = [body.index(t) for t in ("!insertmacro RefuseSecretOptions", "${If} ${Silent}", "!insertmacro ParseSilentKeys", "Call Mode_FromSilent",
                                      "${EndIf}", "Call TrustCheck", "Call Elevate_SilentGate", "Call Runner_GitlabInstallGate")]
        self.assertEqual(at, sorted(at))
        self.assertEqual(len(set(at)), len(at))
        for t in ("RefuseSecretOptions", "ParseSilentKeys", "Mode_FromSilent", "Runner_GitlabInstallGate"):
            self.assertEqual(body.count(t), 1, t)

    def test_the_refusal_comes_before_anything_else_in_on_init_023(self):
        first = [l.strip() for l in func(MAIN, ".onInit").splitlines() if l.strip() and not l.strip().startswith(";")][:2]
        # exit 50 (a command line NSIS cut, #136) is the one check in front of the secret refusal
        self.assertEqual(first, ["!insertmacro RefuseLongCommandLine", "!insertmacro RefuseSecretOptions"])

    def test_the_mode_page_is_the_first_page_and_has_its_leave_callback(self):
        pages = [l for l in MAIN.splitlines() if l.startswith("Page ")]
        self.assertEqual(pages[0], "Page custom Page_mode_Pre Page_mode_Leave")

    def test_every_message_box_added_is_silent_safe_034(self):
        for text in (func(SCREENS, "Page_mode_Leave"), *(p.read_text(encoding="utf-8") for p in NSIS.glob("runner-*.nsh"))):
            for line in text.splitlines():
                if "MessageBox" in line:
                    self.assertIn("/SD IDOK", line)


class SilentRuns(unittest.TestCase):
    def test_no_mode_keeps_footprint_only_behaviour_034(self):
        w, code = init("/S")
        self.assertIsNone(code)
        self.assertEqual(w.var.get("runner_mode", ""), "")
        self.assertEqual(w.log, [])
        self.assertIn("TrustCheck", w.trace)

    def test_each_valid_mode_sets_the_runner_mode_034_035_036(self):
        for mode in ("local", "github", "gitlab"):
            w, code = init("/S /MODE=" + mode)
            self.assertIsNone(code, mode)
            self.assertEqual(w.var["runner_mode"], mode)
            self.assertEqual(w.var["in_mode"], mode)

    def test_the_value_is_case_insensitive_like_a_choice_name(self):
        w, code = init("/S /MODE=GitHub")
        self.assertEqual((code, w.var["runner_mode"]), (None, "github"))

    def test_an_unknown_mode_exits_bad_value_with_one_log_step_and_sets_nothing_026(self):
        for bad in ("nonsense", "github2", "local,github"):
            w, code = init("/S /MODE=" + bad)
            self.assertEqual(code, MODE_ERRORS["bad-value"], bad)
            self.assertEqual(w.var.get("runner_mode", ""), "")
            self.assertEqual(w.log, [("mode", "/MODE", "30")])
            self.assertNotIn("TrustCheck", w.trace)
            self.assertEqual(w.files, {})

    def test_an_empty_mode_value_is_bad_value_like_the_reference_parser(self):
        w, code = init("/S /MODE=")
        self.assertEqual(code, MODE_ERRORS["bad-value"])
        with self.assertRaises(S.BadValue):
            S.validate_values(SCHEMA, {"mode": " ", "install_dir": "x"})

    def test_a_secret_file_option_exits_33_before_the_mode_is_read_023(self):
        for arg in ("/SECRETFILE=x", "/STDIN", "/SECRETSTDIN", "/SECRETS=x", "-"):
            w, code = init("/S /MODE=github " + arg)
            self.assertEqual(code, MODE_ERRORS["secret-from-file-or-stdin"], arg)
            self.assertEqual(w.var.get("runner_mode", ""), "", arg)
            self.assertNotIn("TrustCheck", w.trace)

    def test_a_secret_on_the_command_line_exits_32_023(self):
        for arg in ("/GITHUB_TOKEN=x", "/gitlab_token=x", "/REGISTRY_PASSWORD=x", "/DEPLOY_KEY=x", "/MY_CREDENTIAL=x"):
            w, code = init("/S /MODE=bad " + arg)
            self.assertEqual(code, MODE_ERRORS["secret-on-command-line"], arg)
            self.assertEqual(w.log, [], arg)

    def test_the_refusal_applies_to_an_interactive_run_too_023(self):
        w, code = init("/SECRETFILE=x", silent=False)
        self.assertEqual(code, 33)
        w, code = init("/GITHUB_TOKEN=x", silent=False)
        self.assertEqual(code, 32)

    def test_an_interactive_run_reads_no_silent_key(self):
        w, code = init("/MODE=github", silent=False)
        self.assertIsNone(code)
        self.assertEqual(w.var.get("runner_mode", ""), "")

    def test_gitlab_without_administrator_rights_exits_38_and_github_too_in_silent_mode(self):
        w, code = init("/S /MODE=gitlab", admin=False)
        self.assertEqual(code, 38)
        w, code = init("/S /MODE=github", admin=False)
        self.assertEqual(code, 38)

    def test_the_gitlab_gate_stands_on_its_own_when_the_silent_gate_is_passed(self):
        w = World(cmdline="", silent=False, admin=False)
        w.var["runner_mode"] = "gitlab"
        w.var["elev_isadmin"] = "0"
        self.assertEqual(w.run("Runner_GitlabInstallGate"), 38)
        w = World(admin=False)
        w.var["runner_mode"] = "github"
        w.var["elev_isadmin"] = "0"
        self.assertIsNone(w.run("Runner_GitlabInstallGate"))


class ModePage(unittest.TestCase):
    def leave(self, **radios):
        w = World(silent=False, radios=radios)
        return w, w.run("Page_mode_Leave")

    def test_no_choice_stays_on_the_page_with_a_plain_message_and_a_silent_default(self):
        w, code = self.leave()
        self.assertEqual(code, "abort")
        self.assertEqual(w.var.get("runner_mode", ""), "")
        self.assertEqual(len(w.boxes), 1)
        self.assertIn("Choose what this PC does", w.boxes[0])
        self.assertIn("/SD IDOK", w.boxes[0])

    def test_each_choice_calls_its_setter(self):
        for mode in ("local", "github", "gitlab"):
            w, code = self.leave(**{"ctl_mode_" + mode: True})
            self.assertIsNone(code, mode)
            self.assertEqual((w.var["in_mode"], w.var["runner_mode"]), (mode, mode))

    def test_going_back_and_choosing_the_other_forge_is_not_a_second_forge(self):
        w, _ = self.leave(ctl_mode_gitlab=True)
        w.radios = {"ctl_mode_github": True}
        self.assertIsNone(w.run("Page_mode_Leave"))
        self.assertEqual(w.var["runner_mode"], "github")
        self.assertEqual(w.boxes, [])

    def test_the_setters_still_refuse_a_second_forge_034_036(self):
        for have, want, fn in (("gitlab", "github", "Runner_SetGithub"), ("github", "gitlab", "Runner_SetGitlab")):
            w = World(silent=True)
            w.var["runner_mode"] = have
            self.assertEqual(w.run(fn), "abort")
            self.assertEqual(w.var["runner_mode"], have)


class RunnerState(unittest.TestCase):
    def state(self, mode):
        w = World()
        w.var["runner_mode"] = mode
        code = w.run("Install_RunnerState")
        return w, code

    def test_forge_modes_write_the_forge_file_then_the_mode_file_like_the_adapter_034_036(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for mode in ("github", "gitlab"):
            w, code = self.state(mode)
            self.assertIsNone(code)
            self.assertEqual(list(w.files), [STATE + "runner-forge.json", STATE + "runner-mode.json"])
            runners.set_mode(tmp / mode, mode)
            self.assertEqual(w.files[STATE + "runner-mode.json"], (tmp / mode / runners.MODE_FILE).read_text().replace("\n", "\r\n"))
            self.assertEqual(json.loads(w.files[STATE + "runner-forge.json"]), {"forge": mode})
            self.assertEqual(json.loads(w.files[STATE + "runner-mode.json"]), {"mode": mode})

    def test_local_writes_the_mode_file_and_no_forge_file_035(self):
        w, code = self.state("local")
        self.assertEqual(list(w.files), [STATE + "runner-mode.json"])
        self.assertEqual(json.loads(w.files[STATE + "runner-mode.json"]), {"mode": "local"})

    def test_an_empty_mode_writes_nothing(self):
        w, code = self.state("")
        self.assertEqual(w.files, {})

    def test_the_file_names_are_the_adapters(self):
        self.assertIn(runners.MODE_FILE, INSTALL)
        self.assertIn(runners.FORGE_FILE, INSTALL)

    def test_no_address_and_no_secret_is_written(self):
        body = func(INSTALL, "Install_RunnerState")
        self.assertNotRegex(body, r"(?i)token|secret|password|\$in_|url")

    def test_a_write_failure_reports_the_failed_state_file_not_its_contents(self):
        body = func(INSTALL, "Install_RunnerState")
        self.assertIn("runner_state_failed:", body)
        tail = body.split("runner_state_failed:")[1]
        self.assertIn('Push "write runner-mode.json"', tail)
        self.assertIn("Call Install_StateFailed", tail)
        self.assertNotIn("$runner_mode", tail)

    def test_install_footprint_calls_it_after_the_state_file_and_before_the_payload_093(self):
        body = func(INSTALL, "Install_Footprint")
        at = [body.index(t) for t in ("Call Winsys_FolderLock", 'installer-state.json" w', "state_done:", "Call Install_RunnerState", "Call Install_Payload",
                                      "Call Winsys_CreateService", "WriteUninstaller")]
        self.assertEqual(at, sorted(at))
        self.assertEqual(body.count("Call Install_RunnerState"), 1)

    def test_the_payload_and_the_service_remain_github_and_gitlab_only_034_035(self):
        body = func(INSTALL, "Install_Footprint")
        guard = body[body.index('${If} $runner_mode == "github"'):body.index("Call Install_Payload")]
        self.assertIn('${OrIf} $runner_mode == "gitlab"', guard)
        self.assertNotIn('"local"', body)
        self.assertEqual(body.count("Call Install_Payload"), 1)
        self.assertEqual(body.count("Call Winsys_CreateService"), 1)


class FootprintParity(unittest.TestCase):
    def test_footprint_lists_the_two_new_paths_exactly(self):
        fp = footprint.load_footprint()
        folder = fp["folder"]["path"]
        self.assertEqual(fp["runner_state"], {"mode_file": folder + "\\" + runners.MODE_FILE, "forge_file": folder + "\\" + runners.FORGE_FILE})

    def test_the_install_writes_exactly_those_paths(self):
        fp = footprint.load_footprint()
        body = func(INSTALL, "Install_RunnerState")
        written = set(re.findall(r'FileOpen \$InstallHandle "([^"]+)" w', body))
        self.assertEqual(written, set(fp["runner_state"].values()))

    def test_the_check_is_green(self):
        self.assertEqual(footprint.check_source({p.name: p.read_text(encoding="utf-8") for p in NSIS.glob("*.ns[hi]")}), [])


@unittest.skipUnless(shutil.which("makensis"), "makensis not installed")
class RealCompile(unittest.TestCase):
    def _compile(self, *defines):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        r = subprocess.run(["makensis", "-V1", "-INPUTCHARSET", "UTF8", *defines, "-DOUTFILE=%s" % (tmp / "o.exe"), str(NSIS / "main.nsi")],
                           capture_output=True, text=True, cwd=ROOT)
        return r, tmp

    def test_the_final_script_compiles_without_and_with_a_test_build_payload(self):
        r, _ = self._compile()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        pay = tmp / "runner.exe"
        pay.write_bytes(b"stub")
        r, out = self._compile("-DRUNNER_PAYLOAD=%s" % pay, "-DRUNNER_TEST_BUILD=1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertGreater((out / "o.exe").stat().st_size, 0)


class InterpreterGuards(unittest.TestCase):
    def run_body(self, body, cmdline=""):
        w = World(cmdline=cmdline, program=Program({"x.nsh": "Function F\n%s\nFunctionEnd\n" % body}))
        w.run("F")
        return w

    def test_string_comparison_ignores_case_like_strcmp_and_s_equals_does_not(self):
        w = self.run_body('  StrCpy $0 "GitHub"\n  ${If} $0 == "github"\n    StrCpy $1 "eq"\n  ${EndIf}\n  ${If} $0 != "GITHUB"\n    StrCpy $2 "ne"\n  ${EndIf}\n'
                          '  ${If} $0 S== "github"\n    StrCpy $3 "seq"\n  ${EndIf}')
        self.assertEqual((w.var.get("1"), w.var.get("2"), w.var.get("3")), ("eq", None, None))

    def test_getoptions_honours_a_quoted_value_with_blanks_and_strips_the_quotes(self):
        w = self.run_body('  ${GetOptions} $CMDLINE "/INSTALL_DIR=" $0\n  ${GetOptions} $CMDLINE "/MODE=" $1',
                          cmdline='/S /INSTALL_DIR="C:\\Program Files\\x" /mode=local')
        self.assertEqual((w.var["0"], w.var["1"]), ("C:\\Program Files\\x", "local"))
        self.assertFalse(w.errors)

    def test_getoptions_does_not_find_an_option_inside_a_quoted_value(self):
        w = self.run_body('  ${GetOptions} $CMDLINE "/MODE=" $0', cmdline='"a /MODE=github b"')
        self.assertTrue(w.errors)
        self.assertEqual(w.var["0"], "")

    def test_an_unknown_instruction_raises_so_the_interpreter_is_extended_on_purpose(self):
        p = Program({"x.nsh": "Function F\n  Frobnicate 1\nFunctionEnd\n"})
        with self.assertRaises(ValueError):
            World(program=p).run("F")

    def test_the_interpreter_runs_the_real_files(self):
        self.assertIn(".onInit", Program().functions)
        self.assertIn("Mode_FromSilent", Program().functions)


if __name__ == "__main__":
    unittest.main()
