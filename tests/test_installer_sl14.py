"""SL-14 (ecosystem-control#93, part of #64): the NSIS installer delivers the runner payload and creates the service.
INST-REQ-005 (no payload in Git), 007 (pinned digest), 008, 034 to 036 (runner modes), 070, 091 to 096 (service). Fakes only, no process, no network."""
import contextlib
import copy
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from installer import build, footprint
from tests.test_installer_build import FakeRun, Base as BuildBase, fake_download_factory
from tests.test_installer_sl13 import FOLDER, func, nsis_of

ROOT = Path(__file__).resolve().parent.parent
NSIS = ROOT / "installer" / "nsis"
INSTALL = (NSIS / "install.nsh").read_text(encoding="utf-8")
WINSYS = (NSIS / "winsys.nsh").read_text(encoding="utf-8")
MAIN = (NSIS / "main.nsi").read_text(encoding="utf-8")
PAYLOAD_PATH = "$APPDATA\\EcosystemRunner\\program\\runner.exe"
STUB = b"stub-runner"
STUB_SHA = hashlib.sha256(STUB).hexdigest()


def order(text, tokens):
    at, out = -1, []
    for t in tokens:
        at = text.index(t, at + 1)
        out.append(at)
    return out


class NsisStepOrder(unittest.TestCase):
    def test_service_modes_run_lock_state_payload_service_entry_in_that_order_093(self):
        body = func(INSTALL, "Install_Footprint")
        self.assertTrue(order(body, ["Call Winsys_FolderLock", "FileOpen", "Call Install_Payload", "Call Winsys_CreateService", "WriteUninstaller", "WriteRegStr"]))

    def test_the_uninstall_entry_is_the_last_step_091(self):
        body = func(INSTALL, "Install_Footprint")
        self.assertGreater(body.index("WriteUninstaller"), body.index("Call Winsys_CreateService"))
        self.assertGreater(body.index("WriteRegStr"), body.index("Call Winsys_CreateService"))
        lines = body.rstrip().splitlines()
        self.assertEqual(lines[-1].strip(), "Call Image_Pull")
        self.assertEqual(lines[-2].strip().split()[0], "WriteRegStr")

    def test_service_step_is_guarded_by_the_runner_mode_035(self):
        body = func(INSTALL, "Install_Footprint")
        guard = body[body.index('$runner_mode == "github"'):body.index("Call Install_Payload")]
        self.assertIn('${OrIf} $runner_mode == "gitlab"', guard)
        tail = body[body.index("Call Install_Payload"):body.index("WriteUninstaller")]
        self.assertIn("${EndIf}", tail)
        self.assertEqual(body.count("Call Install_Payload"), 1)
        self.assertEqual(body.count("Call Winsys_CreateService"), 1)

    def test_local_only_and_unknown_modes_have_no_payload_and_no_service_034(self):
        body = func(INSTALL, "Install_Footprint")
        self.assertNotIn('"local"', body)
        guard = body[body.index("${If}", body.index("FileOpen")):body.index("Call Install_Payload")]
        self.assertEqual(re.findall(r'\$runner_mode == "(\w*)"', guard), ["github", "gitlab"])
        self.assertNotIn("${Else}", body[body.index("Call Install_Payload"):body.index("WriteUninstaller")])

    def test_the_service_internal_order_is_kept_from_90_092(self):
        body = func(WINSYS, "Winsys_CreateService")
        order(body, ["sc.exe\" create", "sc.exe\" sidtype", "icacls.exe", "sc.exe\" start"])

    def test_the_runner_variable_is_declared_before_install_uses_it(self):
        self.assertLess(MAIN.index('"runner-github.nsh"'), MAIN.index('"install.nsh"'))

    def test_runner_includes_come_before_install(self):
        for n in ("runner-local.nsh", "runner-gitlab.nsh"):
            self.assertLess(MAIN.index(n), MAIN.index('"install.nsh"'))


class NsisPayloadStep(unittest.TestCase):
    def test_payload_is_embedded_by_file_into_program_runner_exe_005(self):
        body = func(INSTALL, "Install_Payload")
        self.assertIn('File "/oname=%s" "${RUNNER_PAYLOAD}"' % PAYLOAD_PATH, body)
        self.assertIn('CreateDirectory "$APPDATA\\EcosystemRunner\\program"', body)
        self.assertEqual(len(re.findall(r"(?m)^\s*File ", INSTALL)), 1)

    def test_payload_exists_only_when_the_build_defines_it_005(self):
        self.assertIn("!ifdef RUNNER_PAYLOAD", INSTALL)
        self.assertIn("!else", INSTALL)
        head, tail = INSTALL.split("!ifdef RUNNER_PAYLOAD")
        self.assertFalse(re.search(r"(?m)^\s*File ", head))
        self.assertTrue(re.search(r"(?m)^\s*File ", tail.split("!else")[0]))

    def test_a_build_without_payload_refuses_in_the_service_modes_with_code_2(self):
        refuse = INSTALL.split("!else")[1].split("!endif")[0]
        self.assertIn("Goto payload_failed", refuse)
        self.assertFalse(re.search(r"(?m)^\s*File ", refuse))
        self.assertIn("SetErrorLevel 2", INSTALL.split("payload_failed:")[1])

    def test_write_failure_logs_one_step_deletes_the_partial_file_and_exits_2(self):
        body = func(INSTALL, "Install_Payload")
        self.assertIn("SetOverwrite try", body)
        self.assertIn("IfErrors", body)
        fail = body[body.index("payload_failed:"):]
        order(fail, ['Push "payload"', "Call LogStep", 'Delete "%s"' % PAYLOAD_PATH, "SetErrorLevel 2", "Abort"])
        self.assertEqual(fail.count("Call LogStep"), 1)

    def test_the_log_step_carries_no_secret_or_path_of_the_payload(self):
        body = func(INSTALL, "Install_Payload")
        pushes = re.findall(r'Push "([^"]*)"', body)
        self.assertEqual(pushes, ["payload", "File runner.exe", "1"])

    def test_exit_codes_stay_in_the_existing_set(self):
        used = set(re.findall(r"SetErrorLevel (\d+)", INSTALL + WINSYS))
        self.assertLessEqual(used, {"2", "3", "4", "38", "39", "48", "49"})

    def test_service_failures_log_one_step_each_before_they_quit_3_or_4(self):
        body = func(WINSYS, "Winsys_CreateService")
        self.assertEqual(body.count("Call LogStep"), body.count("SetErrorLevel"))
        for chunk in body.split("SetErrorLevel")[:-1]:
            self.assertIn("Call LogStep", chunk.rsplit("${If}", 1)[-1] if "${ElseIf}" not in chunk else chunk.rsplit("${ElseIf}", 1)[-1])
        self.assertEqual(re.findall(r'Push "([a-z-]+)"\n\s+Push "[^"\n]*"\n\s+Push \$0', body), ["service-create", "service-sidtype", "service-grant", "service-start", "service-start"])

    def test_cleanup_follows_each_failure_after_the_service_exists_092(self):
        body = func(WINSYS, "Winsys_CreateService")
        parts = body.split("nsExec::Exec")[1:]
        self.assertNotIn("Winsys_Cleanup", parts[0])
        for p in parts[1:]:
            self.assertIn("Winsys_Cleanup", p)


class FootprintPins(unittest.TestCase):
    def test_check_passes_with_the_payload_step(self):
        self.assertEqual(footprint.check_source(footprint.collect_sources()), [])

    def test_footprint_names_the_payload_path_and_define_exactly_005(self):
        fp = footprint.load_footprint()
        self.assertEqual(fp["payload"], {"path": PAYLOAD_PATH, "define": "RUNNER_PAYLOAD", "test_define": "RUNNER_TEST_BUILD"})
        self.assertTrue(PAYLOAD_PATH.startswith(fp["folder"]["path"]))

    def test_the_service_commands_listed_are_four_and_in_the_script_order_092(self):
        entry = [e for e in footprint.load_footprint()["exec_allowed"] if e["function"] == "Winsys_CreateService"][0]
        self.assertEqual(len(entry["commands"]), 4)
        for c, want in zip(entry["commands"], ("sc.exe\" create", "sc.exe\" sidtype", "icacls.exe", "sc.exe\" start")):
            self.assertIn(want, c)
        order(func(WINSYS, "Winsys_CreateService"), ["sc.exe\" create", "sc.exe\" sidtype", "icacls.exe", "sc.exe\" start"])

    def test_payload_file_outside_the_folder_is_a_violation(self):
        src = {"install.nsh": 'Function F\n  File "/oname=$TEMP\\runner.exe" "x"\nFunctionEnd\n'}
        self.assertTrue(footprint.check_source(src))
        src = {"install.nsh": 'Function F\n  File "/oname=%s" "x"\nFunctionEnd\n' % PAYLOAD_PATH}
        self.assertEqual(footprint.check_source(src), [])

    def test_payload_file_without_oname_is_still_judged_by_its_source_target(self):
        self.assertTrue(footprint.check_source({"install.nsh": 'Function F\n  File "x.exe"\nFunctionEnd\n'}))

    def test_service_binary_path_is_the_payload_path(self):
        self.assertIn('binPath= "%s"' % PAYLOAD_PATH, WINSYS)


def payload_file(tmp, data=STUB):
    p = Path(tmp) / "runner.exe"
    p.write_bytes(data)
    return p


class BuildPayload(BuildBase):
    def _src(self):
        src = self.tmp / "src"
        (src / "installer" / "nsis").mkdir(parents=True)
        (src / "installer" / "nsis" / "main.nsi").write_text("x")
        return src

    def _main(self, *extra, pins=None):
        out, err = io.StringIO(), io.StringIO()
        run = FakeRun()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                unittest.mock.patch.object(build, "load_pins", return_value=pins or self.pins):
            rc = build.main(["build", str(self._src()), str(self.tmp / "o.exe"), *extra], download=fake_download_factory(),
                            run=run, which=lambda n: "/usr/bin/" + n, env={"HOME": str(self.tmp)}, euid=1000)
        return rc, out.getvalue(), err.getvalue(), run

    def _pinned(self, digest=STUB_SHA):
        p = copy.deepcopy(self.pins)
        p["runner_payload"] = {"sha256": digest}
        return p

    def test_the_repository_pin_is_present_and_unset_for_now_007(self):
        pins = json.loads((ROOT / "installer" / "pins.json").read_text())
        self.assertIn("sha256", pins["runner_payload"])
        self.assertIsNone(pins["runner_payload"]["sha256"])

    def test_release_build_with_an_unset_pin_is_refused_with_a_typed_error_007(self):
        rc, out, err, run = self._main("--runner-payload", str(payload_file(self.tmp)))
        self.assertEqual(rc, 2)
        self.assertIn("PayloadError", err)
        self.assertIn("runner_payload.sha256", err)
        self.assertIn("not set", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual([c for c in run.calls if any(a.startswith("-DOUTFILE=") for a in c)], [])

    def test_release_build_without_a_payload_is_refused_005(self):
        rc, out, err, run = self._main(pins=self._pinned())
        self.assertEqual(rc, 2)
        self.assertIn("PayloadError", err)
        self.assertIn("--runner-payload", err)

    def test_release_build_with_the_wrong_digest_is_refused_and_names_both_hashes_007(self):
        rc, out, err, run = self._main("--runner-payload", str(payload_file(self.tmp, b"other")), pins=self._pinned())
        self.assertEqual(rc, 2)
        self.assertIn("PayloadMismatch", err)
        self.assertIn(hashlib.sha256(b"other").hexdigest(), err)
        self.assertIn(STUB_SHA, err)
        self.assertEqual([c for c in run.calls if any(a.startswith("-DOUTFILE=") for a in c)], [])

    def test_release_build_with_the_right_digest_passes_and_defines_only_the_payload_008(self):
        p = payload_file(self.tmp)
        rc, out, err, run = self._main("--runner-payload", str(p), pins=self._pinned())
        self.assertEqual(rc, 0, err)
        cmd = [c for c in run.calls if any(a.startswith("-DOUTFILE=") for a in c)][0]
        self.assertIn("-DRUNNER_PAYLOAD=%s" % p, cmd)
        self.assertFalse([a for a in cmd if a.startswith("-DRUNNER_TEST_BUILD")])
        self.assertIn("runner payload sha256 %s (pinned)" % STUB_SHA, out)
        self.assertNotIn("TEST BUILD", out)

    def test_a_test_build_needs_the_explicit_flag_and_is_marked_everywhere(self):
        p = payload_file(self.tmp)
        rc, out, err, run = self._main("--runner-payload", str(p), "--test-build")
        self.assertEqual(rc, 0, err)
        cmd = [c for c in run.calls if any(a.startswith("-DOUTFILE=") for a in c)][0]
        self.assertIn("-DRUNNER_TEST_BUILD=1", cmd)
        self.assertIn("-DRUNNER_PAYLOAD=%s" % p, cmd)
        self.assertIn("TEST BUILD: the runner payload is not pinned; this installer is not a release", out)
        self.assertEqual(out.count("TEST BUILD"), 1)

    def test_a_test_build_without_a_payload_is_refused(self):
        rc, out, err, run = self._main("--test-build")
        self.assertEqual(rc, 2)
        self.assertIn("PayloadError", err)

    def test_a_test_build_skips_the_digest_check_and_says_so_007(self):
        rc, out, err, run = self._main("--runner-payload", str(payload_file(self.tmp, b"other")), "--test-build", pins=self._pinned())
        self.assertEqual(rc, 0, err)
        self.assertIn("TEST BUILD", out)

    def test_a_payload_that_is_not_a_file_is_a_typed_refusal(self):
        rc, out, err, run = self._main("--runner-payload", str(self.tmp / "missing.exe"), "--test-build")
        self.assertEqual(rc, 2)
        self.assertIn("PayloadError", err)
        self.assertNotIn("Traceback", err)

    def test_a_bad_pin_value_is_a_pins_error(self):
        for bad in ("abc", 5, "A" * 64):
            pins = json.loads((ROOT / "installer" / "pins.json").read_text())
            pins["runner_payload"] = {"sha256": bad}
            f = self.tmp / "pins.json"
            f.write_text(json.dumps(pins))
            with self.assertRaises(build.PinsError):
                build.load_pins(f)

    def test_the_pin_may_be_null_or_a_lowercase_digest(self):
        pins = json.loads((ROOT / "installer" / "pins.json").read_text())
        f = self.tmp / "pins.json"
        for ok in (None, STUB_SHA):
            pins["runner_payload"] = {"sha256": ok}
            f.write_text(json.dumps(pins))
            self.assertEqual(build.load_pins(f)["runner_payload"]["sha256"], ok)

    def test_the_payload_is_a_compile_input_and_never_in_the_file_list_005(self):
        src = self._src()
        (src / "installer" / "runner.exe").write_bytes(b"x")
        self.assertIn("runner.exe", build.collect_files(src / "installer"))
        self.assertFalse(subprocess.run(["git", "-C", str(ROOT), "ls-files", "*runner.exe"], capture_output=True, text=True).stdout.strip())

    def test_compile_command_adds_the_defines_only_when_asked(self):
        base = build.compile_command("/m", self.pins, "main.nsi", "o.exe", "f.txt")
        self.assertFalse([a for a in base if "RUNNER" in a])
        cmd = build.compile_command("/m", self.pins, "main.nsi", "o.exe", "f.txt", payload="/p/runner.exe", test_build=True)
        self.assertIn("-DRUNNER_PAYLOAD=/p/runner.exe", cmd)
        self.assertIn("-DRUNNER_TEST_BUILD=1", cmd)
        self.assertEqual(cmd[-1], "main.nsi")


@unittest.skipUnless(shutil.which("makensis"), "makensis not installed")
class RealCompile(unittest.TestCase):
    def _compile(self, *defines):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        r = subprocess.run(["makensis", "-V1", "-INPUTCHARSET", "UTF8", *defines, "-DOUTFILE=%s" % (tmp / "o.exe"), str(NSIS / "main.nsi")],
                           capture_output=True, text=True, cwd=ROOT)
        return r, tmp

    def test_the_script_compiles_without_and_with_a_payload_093(self):
        r, _ = self._compile()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        pay = payload_file(tmp)
        r, out = self._compile("-DRUNNER_PAYLOAD=%s" % pay, "-DRUNNER_TEST_BUILD=1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertGreater((out / "o.exe").stat().st_size, 0)


class MessageBoxesAreSilentSafe(unittest.TestCase):
    # Pre-existing boxes outside this slice (interactive screens, the trust prompts, update): listed, not changed here.
    ALLOWED = {("trust.nsh", "$0 Nothing was started."), ("trust.nsh", "The signer changed."), ("trust.nsh", "First run.")}

    def test_every_messagebox_carries_sd_or_is_listed_093(self):
        bad = []
        for f in sorted(NSIS.glob("*.nsh")) + [NSIS / "main.nsi"]:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if line.strip().startswith("MessageBox") and "/SD" not in line:
                    if not any(f.name == a and q in line for a, q in self.ALLOWED):
                        bad.append("%s:%d" % (f.name, n))
        self.assertEqual(bad, [])

    def test_the_logon_failure_box_answers_itself_under_silent_mode(self):
        self.assertRegex(func(WINSYS, "Winsys_CreateService"), r'logon failure[^\n]*" /SD IDOK')
