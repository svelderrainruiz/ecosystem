"""SL-16b (ecosystem-control#104, part of #97 and #64): the licence gate, the local licence record and the pull of the pinned NI docker image.
INST-REQ-018 (licence screen), 021/022 (variant and year, digest from the pinned list), 073 (answers kept), 074 (local only, no network).
The NSIS functions run in the small interpreter (tests/nsis_interp.py) over the real script text; no Windows, no engine, no network."""
import copy
import datetime
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer import build, footprint, image, licences, update
from installer import schema as S
from tests.nsis_interp import World, Program, NSIS, source_text
from tests.test_installer_sl13 import func
from tests.test_installer_update import Base, FakeSystem

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = S.load_schema()
CODES = SCHEMA["exit_codes"]
DIGEST = "sha256:" + "ab" * 32
REPO = "registry.example/ni/labview"
RECORD = "C:\\ProgramData\\EcosystemRunner\\licence-record.json"
DESKTOP = "C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe"
ENGINE = "C:\\Program Files\\Docker\\docker.exe"
CANARY = "CANARY-SECRET-7731"
BOTH = " /NI_LICENCE_HELD=yes /ENGINE_LICENCE_ACCEPTED=yes"


def pinned_schema():
    s = copy.deepcopy(SCHEMA)
    for n, e in enumerate(s["images"]["list"]):
        e["digest"], e["repository"] = "sha256:" + ("%02x" % (n + 1)) * 32, REPO + "/" + e["variant"]
    return s


def program(schema=None):
    files = source_text()
    if schema:
        files["screens.nsh"] = S.generate_nsh(schema)
    return Program(files)


class W(World):
    def native_LogUtcNow(self):
        self.var.update({"LogY": "2026", "LogMo": "11", "LogD": "22", "LogH": "07", "LogMi": "05", "LogS": "09"})
        self.errors = True  # a real LogUtcNow can leave the error flag set


def world(cmdline="", silent=True, schema=None, **k):
    return W(cmdline=cmdline, silent=silent, program=program(schema), **k)


def init(cmd, schema=None):
    w = world(cmd, schema=schema)
    return w, w.run(".onInit")


def ready(w, variant="linux", year="2024", held="yes", accepted="yes"):
    w.var.update({"in_image_variant": variant, "in_image_year": year, "in_ni_licence_held": held, "in_engine_licence_accepted": accepted})
    return w


def leave(page, texts=None, radios=None, preset=None, schema=None):
    w = world(silent=False, schema=schema, texts={"ctl_" + k: v for k, v in (texts or {}).items()}, radios={"ctl_" + k: v for k, v in (radios or {}).items()})
    w.var.update({"in_" + k: v for k, v in (preset or {}).items()})
    return w, w.run("Page_%s_Leave" % page)


def with_engine(w, path=DESKTOP):
    w.files[path] = "x"
    return w


def leaked(test, w, secret):
    for where, items in (("boxes", w.boxes), ("log", [str(x) for x in w.log]), ("details", w.details), ("files", list(w.files.values())), ("execs", [" ".join(x) for x in w.execs])):
        test.assertFalse(any(secret in x for x in items), where)


class InteractivePages(unittest.TestCase):
    def test_the_licence_page_is_skipped_without_an_image(self):
        w = world(silent=False)
        w.var["in_image_variant"] = ""
        self.assertEqual(w.run("Page_licences"), "abort")
        self.assertEqual((w.boxes, w.log), ([], []))

    def test_the_licence_page_is_shown_with_an_image(self):
        w = world(silent=False)
        w.var["in_image_variant"] = "linux"
        self.assertIsNone(w.run("Page_licences"))
        self.assertIn("nsDialogs::Create", w.trace)

    def test_the_licence_page_skip_comes_before_anything_is_created(self):
        body = func((NSIS / "screens.nsh").read_text(encoding="utf-8"), "Page_licences")
        self.assertLess(body.index("Abort"), body.index("!insertmacro Dialog_Create"))

    def test_one_box_is_not_enough(self):
        for radios in ({"ni_licence_held": True}, {"engine_licence_accepted": True}, {}):
            w, code = leave("licences", radios=radios)
            self.assertEqual(code, "abort", radios)
            self.assertEqual(len(w.boxes), 1)
            self.assertIn("/SD IDOK", w.boxes[0])

    def test_both_boxes_pass_with_no_message(self):
        w, code = leave("licences", radios={"ni_licence_held": True, "engine_licence_accepted": True})
        self.assertEqual((code, w.boxes), (None, []))

    def test_a_pair_that_is_not_pinned_is_refused_with_one_plain_message(self):
        w, code = leave("image", {"image_variant": "windows", "image_year": "2025"})
        self.assertEqual(code, "abort")
        self.assertEqual(len(w.boxes), 1)
        self.assertIn("/SD IDOK", w.boxes[0])

    def test_every_pinned_pair_is_accepted(self):
        for e in SCHEMA["images"]["list"]:
            w, code = leave("image", {"image_variant": e["variant"], "image_year": e["year"]}, schema=pinned_schema())
            self.assertEqual((code, w.boxes), (None, []), e)

    def test_no_image_leaves_the_image_page_as_before(self):
        w, code = leave("image", {})
        self.assertEqual((code, w.boxes), (None, []))


class SilentGate(unittest.TestCase):
    def test_both_yes_passes(self):
        w, code = init("/S /IMAGE_VARIANT=linux /IMAGE_YEAR=2024" + BOTH, pinned_schema())
        self.assertEqual((code, w.log), (None, []))

    def test_the_answers_are_case_insensitive(self):
        w, code = init("/S /IMAGE_VARIANT=linux /IMAGE_YEAR=2024 /NI_LICENCE_HELD=YES /ENGINE_LICENCE_ACCEPTED=Yes", pinned_schema())
        self.assertEqual(code, None)

    def test_one_no_one_missing_or_both_missing_exit_35(self):
        base = "/S /IMAGE_VARIANT=linux /IMAGE_YEAR=2024"
        for extra in (" /NI_LICENCE_HELD=yes /ENGINE_LICENCE_ACCEPTED=no", " /NI_LICENCE_HELD=no /ENGINE_LICENCE_ACCEPTED=yes",
                      " /NI_LICENCE_HELD=yes", " /ENGINE_LICENCE_ACCEPTED=yes", ""):
            w, code = init(base + extra, pinned_schema())
            self.assertEqual(code, CODES["licence-not-accepted"], extra)
            self.assertEqual(w.log, [("licence-not-accepted", "licences", "35")])
            self.assertEqual((w.files, w.execs), ({}, []))

    def test_an_unpinned_pair_exits_36_and_is_checked_before_the_licence(self):
        w, code = init("/S /IMAGE_VARIANT=windows /IMAGE_YEAR=2025")
        self.assertEqual(code, CODES["image-not-pinned"])
        self.assertEqual(w.log, [("image-not-pinned", "image", "36")])
        w, code = init("/S /IMAGE_VARIANT=windows /IMAGE_YEAR=2025" + BOTH)
        self.assertEqual(code, 36)

    def test_no_image_keys_changes_nothing(self):
        for cmd in ("/S", "/S /NI_LICENCE_HELD=no", "/S /MODE=local"):
            w, code = init(cmd)
            self.assertEqual((code, w.log, w.files, w.execs), (None, [], {}, []), cmd)

    def test_the_codes_come_from_the_schema(self):
        self.assertEqual((CODES["licence-not-accepted"], CODES["image-not-pinned"], CODES["image-pull-failed"]), (35, 36, 46))
        gate = func((NSIS / "licence.nsh").read_text(encoding="utf-8"), "Licence_SilentGate")
        self.assertEqual(re.findall(r"SetErrorLevel (\d+)", gate), ["36", "35"])

    def test_the_gate_runs_after_the_key_check_and_before_the_trust_check(self):
        body = func((NSIS / "main.nsi").read_text(encoding="utf-8"), ".onInit")
        self.assertLess(body.index("ValidateSilentKeys"), body.index("Call Licence_SilentGate"))
        self.assertLess(body.index("Call Licence_SilentGate"), body.index("Call TrustCheck"))
        self.assertEqual(body.count("Licence_SilentGate"), 1)


def half_pinned(**keep):
    s = pinned_schema()
    for e in s["images"]["list"]:
        for k in ("digest", "repository"):
            if k not in keep:
                e[k] = None
    return s


class RefuseEarly(unittest.TestCase):
    PAIR = "/S /IMAGE_VARIANT=linux /IMAGE_YEAR=2024" + BOTH

    def test_with_the_real_unpinned_table_a_silent_run_exits_36_and_writes_nothing(self):
        for e in SCHEMA["images"]["list"]:
            w, code = init("/S /IMAGE_VARIANT=%s /IMAGE_YEAR=%s%s" % (e["variant"], e["year"], BOTH))
            self.assertEqual(code, 36, e)
            self.assertEqual(w.log, [("image-not-pinned", "image", "36")])
            self.assertEqual((w.files, w.execs, w.boxes), ({}, [], []))

    def test_with_a_fully_pinned_table_the_same_command_line_passes_the_gate_and_pulls(self):
        s = pinned_schema()
        w, code = init(self.PAIR, s)
        self.assertEqual((code, w.log), (None, []))
        w = with_engine(ready(world(schema=s)))
        w.files[RECORD] = "{}"
        self.assertIsNone(w.run("Image_Pull"))
        self.assertEqual(len(w.execs), 1)

    def test_a_half_pinned_entry_is_refused_by_the_gate_and_has_no_reference(self):
        for keep in ({"digest": 1}, {"repository": 1}, {}):
            s = half_pinned(**keep)
            w, code = init(self.PAIR, s)
            self.assertEqual(code, 36, keep)
            w = ready(world(schema=s))
            w.run("Image_Ref")
            self.assertEqual(w.var["R8"], "", keep)

    def test_the_interactive_page_refuses_an_unpinned_pair_with_the_pinned_list_message(self):
        for s in (None, half_pinned(digest=1), half_pinned(repository=1)):
            w, code = leave("image", {"image_variant": "linux", "image_year": "2024"}, schema=s)
            self.assertEqual(code, "abort")
            self.assertEqual(len(w.boxes), 1)
            self.assertIn("not in the pinned list", w.boxes[0])
            self.assertIn("/SD IDOK", w.boxes[0])


class OrderParity(unittest.TestCase):
    """The NSIS gate and schema.run_silent agree on the order: unpinned (36) is checked before the licence (35)."""

    def python_exit(self, schema, args):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            return S.run_silent(schema, ["/S"] + args, "Microsoft Windows 11 Pro", d, datetime.datetime(2026, 11, 22, 7, 5, 9), log=[])

    def test_a_command_line_with_both_errors_exits_36_in_nsis_and_in_python(self):
        args = ["/INSTALL_DIR=C:\\ci", "/IMAGE_VARIANT=linux", "/IMAGE_YEAR=2024", "/NI_LICENCE_HELD=no"]
        self.assertEqual(init(" ".join(["/S"] + args))[1], 36)
        self.assertEqual(self.python_exit(SCHEMA, args), 36)

    def test_with_a_pinned_pair_the_licence_error_is_35_in_both(self):
        args = ["/INSTALL_DIR=C:\\ci", "/IMAGE_VARIANT=linux", "/IMAGE_YEAR=2024", "/NI_LICENCE_HELD=no"]
        self.assertEqual(init(" ".join(["/S"] + args), pinned_schema())[1], 35)
        self.assertEqual(self.python_exit(pinned_schema(), args), 35)


class Record(unittest.TestCase):
    def test_nothing_is_written_without_an_image_or_without_both_yes(self):
        for kw in ({"variant": ""}, {"held": "no"}, {"accepted": "no"}, {"held": ""}, {"accepted": ""}):
            w = ready(world(), **kw)
            self.assertIsNone(w.run("Licence_WriteRecord"), kw)
            self.assertEqual(w.files, {}, kw)

    def test_the_record_equals_the_python_record_byte_for_byte(self):
        w = ready(world())
        self.assertIsNone(w.run("Licence_WriteRecord"))
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = licences.write_record(d, datetime.datetime(2026, 11, 22, 7, 5, 9))
            expected = p.read_bytes().decode("utf-8")
        self.assertEqual(w.files[RECORD], expected)
        self.assertEqual(json.loads(w.files[RECORD]), {"ni_development_licence_held": "yes", "utc": "2026-11-22T07:05:09Z"})

    def test_the_record_name_is_the_python_name_and_is_in_the_footprint(self):
        self.assertTrue(RECORD.endswith("\\" + licences.RECORD_NAME))
        self.assertEqual(footprint.load_footprint()["licence_record"]["file"], RECORD.replace("C:\\ProgramData", "$APPDATA"))

    def test_a_record_that_cannot_be_written_stops_with_37_and_logs_the_name_only(self):
        w = ready(world())
        w.files[RECORD] = None
        self.assertEqual(w.run("Licence_WriteRecord"), "abort")
        self.assertEqual(w.log, [("licence-record", "FileOpen licence-record.json", "37")])

    def test_a_failed_write_exits_37_logs_filewrite_leaves_no_record_and_no_pull(self):
        w = ready(world())
        w.write_fails.add(RECORD)
        self.assertEqual(w.run("Licence_WriteRecord"), "abort")
        self.assertEqual(w.exit_code, 37)
        self.assertEqual(w.log, [("licence-record", "FileWrite licence-record.json", "37")])
        self.assertNotIn(RECORD, w.files)
        self.assertEqual(w.open_handles, set())
        with_engine(w)
        self.assertIsNone(w.run("Image_Pull"))
        self.assertEqual(w.execs, [])

    def test_a_write_on_a_closed_handle_fails_in_the_interpreter(self):
        p = Program({"x.nsh": 'Function F\n  FileOpen $9 "C:\\a" w\n  FileClose $9\n  ClearErrors\n  FileWrite $9 "x"\nFunctionEnd\n'})
        w = World(program=p)
        w.run("F")
        self.assertEqual((w.errors, w.files["C:\\a"]), (True, ""))

    def test_a_written_record_leaves_no_open_handle(self):
        w = ready(world())
        w.run("Licence_WriteRecord")
        self.assertEqual(w.open_handles, set())

    def test_an_unopenable_record_exits_37_and_nothing_after_it_runs(self):
        w = ready(world())
        w.files[RECORD] = None
        self.assertEqual(w.run("Licence_WriteRecord"), "abort")
        self.assertEqual(w.exit_code, 37)
        self.assertEqual(w.files, {RECORD: None})
        self.assertEqual((w.open_handles, w.execs, len(w.boxes)), (set(), [], 0))

    def test_the_whole_install_path_stops_at_a_record_failure_before_the_pull(self):
        body = func((NSIS / "licence.nsh").read_text(encoding="utf-8"), "Licence_WriteRecord")
        self.assertRegex(body, r"IfErrors record_failed")
        self.assertRegex(body, r"SetErrorLevel 37\s+Abort")

    def test_the_record_is_written_after_the_state_file_and_before_the_pull(self):
        body = func((NSIS / "install.nsh").read_text(encoding="utf-8"), "Install_Footprint")
        i = {k: body.index(k) for k in ("installer-state.json", "Call Licence_WriteRecord", "WriteUninstaller", "Call Image_Pull")}
        self.assertLess(i["installer-state.json"], i["Call Licence_WriteRecord"])
        self.assertLess(i["Call Licence_WriteRecord"], i["WriteUninstaller"])
        self.assertLess(i["WriteUninstaller"], i["Call Image_Pull"])
        self.assertEqual(body.count("Call Licence_WriteRecord"), 1)
        self.assertEqual(body.count("Call Image_Pull"), 1)


class Pull(unittest.TestCase):
    def run_pull(self, schema=None, record=True, **kw):
        engine = kw.pop("engine", DESKTOP)
        w = ready(world(schema=schema, exec_codes=kw.pop("exec_codes", None)), **kw)
        if engine:
            with_engine(w, engine)
        if record:
            w.files[RECORD] = "{}"
        return w, w.run("Image_Pull")

    def test_the_argument_list_is_the_engine_pull_and_the_reference_of_the_pinned_digest_for_every_pair(self):
        s = pinned_schema()
        for e in s["images"]["list"]:
            w, code = self.run_pull(s, variant=e["variant"], year=e["year"])
            self.assertIsNone(code)
            self.assertEqual(w.execs, [[DESKTOP, "pull", image.reference(e["repository"], e["digest"])]], e)

    def test_the_engine_override_is_a_build_define_for_tests_and_is_empty_by_default(self):
        text = (NSIS / "image.nsh").read_text(encoding="utf-8")
        self.assertIn('!ifdef ENGINE_EXE\n  !ifndef RUNNER_TEST_BUILD\n    !error "ENGINE_EXE is a test-only define: add -DRUNNER_TEST_BUILD=1 (a release build never defines it)"\n'
                      '  !endif\n!else\n  !define ENGINE_EXE ""\n!endif', text)
        self.assertIn("ONLY for tests", text)

    def test_with_digests_still_null_nothing_is_pulled_and_the_run_exits_36(self):
        w, code = self.run_pull()
        self.assertEqual((code, w.execs), (36, []))
        self.assertEqual(w.log, [("image-not-pinned", "image", "36")])

    def test_no_pull_without_an_image_without_both_yes_or_without_the_record(self):
        s = pinned_schema()
        for kw in ({"variant": ""}, {"held": "no"}, {"accepted": ""}, {"record": False}):
            w, code = self.run_pull(s, **kw)
            self.assertEqual((code, w.execs), (None, []), kw)

    def test_every_non_zero_or_non_numeric_engine_answer_is_a_failed_pull(self):
        for answer in ("error", "timeout", "125", "1", "-1", "255"):
            w, code = self.run_pull(pinned_schema(), exec_codes=[answer])
            self.assertEqual(code, CODES["image-pull-failed"], answer)
            self.assertEqual(w.log, [("image-pull", "pull", "46")], answer)

    def test_only_a_zero_answer_is_a_pulled_image(self):
        w, code = self.run_pull(pinned_schema(), exec_codes=["0"])
        self.assertEqual((code, w.log, w.boxes), (None, [], []))

    def test_a_failed_pull_exits_46_with_one_step_and_one_plain_message(self):
        w, code = self.run_pull(pinned_schema(), exec_codes=[1])
        self.assertEqual(code, CODES["image-pull-failed"])
        self.assertEqual(w.log, [("image-pull", "pull", "46")])
        self.assertEqual(len(w.boxes), 1)
        self.assertIn("/SD IDOK", w.boxes[0])
        self.assertIn("run the installer again to repair", w.boxes[0])

    def test_the_uninstall_entry_exists_before_the_pull_so_a_failed_pull_leaves_a_removable_install(self):
        body = func((NSIS / "install.nsh").read_text(encoding="utf-8"), "Install_Footprint")
        self.assertEqual(body.rstrip().splitlines()[-1].strip(), "Call Image_Pull")
        self.assertLess(body.index('"QuietUninstallString"'), body.index("Call Image_Pull"))

    def test_the_verbs_are_the_mode_probe_and_the_pull_only(self):
        text = (NSIS / "image.nsh").read_text(encoding="utf-8") + (NSIS / "licence.nsh").read_text(encoding="utf-8")
        calls = re.findall(r"nsExec::(\w+)[ \t]+([^\r\n]*)", text, re.I)
        self.assertEqual(calls, [("ExecToStack", "'\"$ImgEngine\" info --format {{.OSType}}'"), ("Exec", "'\"$ImgEngine\" pull $ImgRef'")])
        self.assertNotRegex(text, r"(?im)^[^;\n]*\"[ \t]+(save|export|push|login)\b")
        body = func((NSIS / "image.nsh").read_text(encoding="utf-8"), "Image_Pull")
        self.assertNotRegex(body, r"(?i)\bGoto\b|\$\{(Do|While|For|ForEach|Loop)")

    def test_the_reference_comes_from_the_generated_table_not_from_text(self):
        body = func((NSIS / "image.nsh").read_text(encoding="utf-8"), "Image_Pull")
        self.assertIn("Call Image_Ref", body)
        self.assertNotIn("$in_", body)
        table = func(S.generate_nsh(pinned_schema()), "Image_Ref")
        self.assertEqual(len(re.findall(r"StrCpy \$R8 ", table)), 1 + len(SCHEMA["images"]["list"]))

    def test_a_pair_listed_twice_with_a_tag_is_refused_by_the_schema(self):
        s = pinned_schema()
        s["images"]["list"][0]["digest"] = "latest"
        with self.assertRaises(S.SchemaError):
            S.validate_schema(s)


class SchemaValues(unittest.TestCase):
    def reject(self, **kw):
        s = pinned_schema()
        s["images"]["list"][0].update(kw)
        with self.assertRaises(S.SchemaError):
            S.validate_schema(s)

    def test_a_bad_digest_is_rejected(self):
        good = "sha256:" + "a" * 64
        for bad in (good.upper(), "sha256:" + "a" * 63, "sha256:" + "a" * 65, "a" * 64, "sha256:" + "g" * 64, good + "\n"):
            self.reject(digest=bad)

    def test_a_bad_repository_is_rejected(self):
        for bad in ("Ghcr.io/x/y", "/ghcr.io/x", "ghcr.io/x y", 'ghcr.io/x"y', "ghcr.io/x@y", "", "-x", "ghcr.io/x\n"):
            self.reject(repository=bad)

    def test_a_repository_is_at_most_255_characters(self):
        s = pinned_schema()
        s["images"]["list"][0]["repository"] = "a" * 255
        S.validate_schema(s)
        self.reject(repository="a" * 256)

    def test_a_good_pair_is_accepted(self):
        S.validate_schema(pinned_schema())


@unittest.skipUnless(shutil.which("makensis"), "makensis not installed")
class EngineDefineIsTestOnly(unittest.TestCase):
    def compile(self, *defines):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return subprocess.run(["makensis", "-V1", "-INPUTCHARSET", "UTF8", *defines, "-DOUTFILE=%s" % (tmp / "o.exe"), str(NSIS / "main.nsi")],
                              capture_output=True, text=True, cwd=ROOT)

    def test_the_override_without_a_test_build_fails_the_compile(self):
        r = self.compile("-DENGINE_EXE=C:\\fake\\docker.exe")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ENGINE_EXE is a test-only define", r.stdout + r.stderr)

    def test_the_override_with_a_test_build_compiles(self):
        r = self.compile("-DENGINE_EXE=C:\\fake\\docker.exe", "-DRUNNER_TEST_BUILD=1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class ReleaseBuildHasNoEngineDefine(unittest.TestCase):
    def test_the_release_compile_command_and_the_pinned_defines_hold_no_engine_define(self):
        pins = json.loads((ROOT / "installer" / "pins.json").read_text())
        self.assertNotIn("ENGINE_EXE", pins["compile"]["defines"])
        for test_build in (False, True):
            cmd = build.compile_command("makensis", pins, "main.nsi", "o.exe", "files.txt", payload="p.exe", test_build=test_build)
            self.assertFalse([c for c in cmd if "ENGINE_EXE" in c], cmd)
        self.assertNotIn("-DRUNNER_TEST_BUILD=1", build.compile_command("makensis", pins, "main.nsi", "o.exe", "files.txt", payload="p.exe"))


class DuplicatePair(unittest.TestCase):
    def test_a_variant_and_year_pair_listed_twice_is_rejected(self):
        s = pinned_schema()
        s["images"]["list"].append(dict(s["images"]["list"][0]))
        with self.assertRaisesRegex(S.SchemaError, "twice"):
            S.validate_schema(s)

    def test_the_committed_schema_has_no_duplicate_pair(self):
        S.validate_schema(SCHEMA)


class UpperCaseDigest(unittest.TestCase):
    def test_an_upper_case_digest_is_refused_by_the_schema_so_the_two_models_cannot_disagree(self):
        s = pinned_schema()
        s["images"]["list"][0]["digest"] = "sha256:" + "A" * 64
        with self.assertRaises(S.SchemaError):
            S.validate_schema(s)


class Engine(unittest.TestCase):
    def pull(self, *places, define=""):
        w = ready(world(schema=pinned_schema()))
        w.defines = {"ENGINE_EXE": define}
        for p in places:
            with_engine(w, p)
        w.files[RECORD] = "{}"
        return w, w.run("Image_Pull")

    def test_the_engine_found_in_the_first_place_runs_by_its_absolute_path(self):
        w, code = self.pull(DESKTOP)
        self.assertEqual((code, w.execs[0][0]), (None, DESKTOP))

    def test_the_engine_found_in_the_second_place_runs_by_its_absolute_path(self):
        w, code = self.pull(ENGINE)
        self.assertEqual((code, w.execs[0][0]), (None, ENGINE))

    def test_with_both_present_the_first_place_wins(self):
        w, code = self.pull(ENGINE, DESKTOP)
        self.assertEqual(w.execs[0][0], DESKTOP)

    def test_no_engine_exits_46_with_one_step_one_plain_message_and_no_command(self):
        w, code = self.pull()
        self.assertEqual(code, CODES["image-pull-failed"])
        self.assertEqual((w.execs, w.details), ([], []))
        self.assertEqual(w.log, [("image-engine-missing", "engine", "46")])
        self.assertEqual(len(w.boxes), 1)
        self.assertIn("/SD IDOK", w.boxes[0])
        self.assertIn("The container engine was not found. The installation stays: install Docker, then run the installer again to repair.", w.boxes[0])

    def test_a_file_named_docker_next_to_the_installer_is_never_run(self):
        w = ready(world(schema=pinned_schema()))
        w.files[RECORD] = "{}"
        w.var["EXEDIR"] = "C:\\Users\\x\\Downloads"
        w.files["C:\\Users\\x\\Downloads\\docker.exe"] = "planted"
        self.assertEqual(w.run("Image_Pull"), 46)
        self.assertEqual(w.execs, [])

    def test_the_override_wins_beside_a_real_engine_file(self):
        w, code = self.pull(DESKTOP, ENGINE, define="C:\\stub\\docker.exe")
        self.assertEqual((code, w.execs[0][0]), (None, "C:\\stub\\docker.exe"))

    def test_the_build_define_overrides_the_search_for_tests_only(self):
        w, code = self.pull(define="C:\\stub\\docker.exe")
        self.assertEqual((code, w.execs[0][0]), (None, "C:\\stub\\docker.exe"))

    def test_the_command_never_uses_a_bare_engine_name(self):
        text = re.sub(r"(?m)^;.*$", "", (NSIS / "image.nsh").read_text(encoding="utf-8"))
        text = re.sub(r"(?m)^\s*MessageBox .*$", "", text)  # box text, never a command: #159's box starts with "Docker is running"
        self.assertNotRegex(text, r"(?i)[\"']docker[\"' ]")
        self.assertEqual(re.findall(r"IfFileExists \"(\$PROGRAMFILES64[^\"]+)\"", text), ["$PROGRAMFILES64\\Docker\\Docker\\resources\\bin\\docker.exe", "$PROGRAMFILES64\\Docker\\docker.exe"])

    def test_the_two_places_are_the_only_new_reads_in_the_footprint_allow_list(self):
        allow = footprint.load_allowlist()
        self.assertIn("$PROGRAMFILES64\\Docker\\Docker\\resources\\bin\\docker.exe", allow)
        self.assertIn("$PROGRAMFILES64\\Docker\\docker.exe", allow)
        self.assertFalse([a for a in allow if "Docker" in a and a.lower().endswith("docker\\")])


class NoSilentHang(unittest.TestCase):
    TEXT = "Pulling the NI docker image. This can take a long time; Cancel waits until it ends."

    def test_one_constant_line_is_shown_before_the_pull(self):
        w = with_engine(ready(world(schema=pinned_schema())))
        w.files[RECORD] = "{}"
        w.run("Image_Pull")
        self.assertEqual(w.details, ["Checking which container type Docker runs.", self.TEXT])
        body = func((NSIS / "image.nsh").read_text(encoding="utf-8"), "Image_Pull")
        self.assertIn('DetailPrint "%s"\n  nsExec::Exec \'' % self.TEXT, body)
        for line in re.findall(r'DetailPrint "(.*)"', body):
            self.assertNotIn("$", line)

    def test_no_line_is_shown_when_nothing_is_pulled(self):
        w = ready(world(schema=pinned_schema()), held="no")
        w.files[RECORD] = "{}"
        w.run("Image_Pull")
        self.assertEqual((w.details, w.execs), ([], []))

    def test_there_is_deliberately_no_timeout_and_it_is_said_so(self):
        text = (NSIS / "image.nsh").read_text(encoding="utf-8")
        code = re.sub(r"(?m)^;.*$", "", text)
        self.assertNotRegex(code, r"(?i)timeout")
        self.assertEqual(re.findall(r"nsExec::ExecToStack (.*)", code), ["'\"$ImgEngine\" info --format {{.OSType}}'"])
        self.assertIn("NO timeout", text)
        self.assertIn("NO timeout", (NSIS.parent / "README.md").read_text(encoding="utf-8"))


class Hygiene(unittest.TestCase):
    def test_a_canary_secret_reaches_no_message_log_file_or_command(self):
        s = pinned_schema()
        w = world("/S /IMAGE_VARIANT=linux /IMAGE_YEAR=2024 /GITHUB_TOKEN=%s" % CANARY, schema=s)
        w.run(".onInit")
        leaked(self, w, CANARY)
        w = with_engine(ready(world(schema=s, exec_codes=[1]), variant="linux"))
        w.var["in_github_token"] = CANARY
        w.files[RECORD] = "{}"
        w.run("Licence_WriteRecord")
        w.run("Image_Pull")
        leaked(self, w, CANARY)

    def test_the_footprint_and_the_schema_agree_on_the_new_exit_code(self):
        self.assertEqual(footprint.load_footprint()["exit_codes"]["image-pull-failed"], 46)
        self.assertEqual(CODES["image-pull-failed"], 46)
        self.assertEqual(len(set(CODES.values())), len(CODES))

    def test_the_footprint_check_is_green_and_the_pull_is_the_only_new_exec(self):
        self.assertEqual(footprint.check_source({p.name: p.read_text(encoding="utf-8") for p in NSIS.glob("*.ns[hi]")}), [])
        fp = footprint.load_footprint()
        self.assertEqual([e["function"] for e in fp["exec_allowed"] if e["file"] == "image.nsh"], ["Image_Pull"])

    def test_the_generated_screens_are_not_drifted(self):
        self.assertTrue(S.check_drift(SCHEMA))

    def test_the_new_files_use_no_network_word(self):
        for n in ("licence.nsh", "image.nsh"):
            self.assertNotRegex((NSIS / n).read_text(encoding="utf-8"), r"(?i)https?://|inetc|NSISdl|nsExec::ExecToLog|ExecWait|ExecShell")


class InterpreterNotes(unittest.TestCase):
    def test_nsexec_records_the_arguments_and_answers_the_chosen_code(self):
        p = Program({"x.nsh": 'Function F\n  nsExec::Exec \'"C:\\x\\docker.exe" pull a@b\'\n  Pop $R0\nFunctionEnd\n'})
        w = World(program=p, exec_codes=[7])
        w.run("F")
        self.assertEqual((w.execs, w.var["R0"]), ([["C:\\x\\docker.exe", "pull", "a@b"]], "7"))



class RecordIsOwned(Base):
    def test_the_record_name_is_owned_and_uninstall_exe_stays_last(self):
        self.assertIn(licences.RECORD_NAME, update.OWNED)
        self.assertEqual(update.OWNED[-1], "uninstall.exe")
        self.assertEqual(update.OWNED[-2], licences.RECORD_NAME)

    def test_an_uninstall_removes_the_record_and_leaves_nothing_behind(self):
        self.state()
        (self.root / "uninstall.exe").write_text("nsis-uninstaller")
        (self.root / licences.RECORD_NAME).write_text('{"ni_development_licence_held": "yes"}')
        rep = update.uninstall(self.root, FakeSystem())
        self.assertFalse(self.root.exists())
        self.assertNotIn("other files kept", rep.text())


if __name__ == "__main__":
    unittest.main()
