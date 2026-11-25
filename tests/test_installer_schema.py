"""SL-3 input schema, silent mode, licences and pinned image list (INST-REQ-018 to 026, 073 to 077, 098)."""
import datetime
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer import licences, schema as S

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime.datetime(2026, 11, 21, 12, 0, 0)
FAKE_TOKEN = "fake-token-0123456789abcdef"
GOOD = ["/S", "/INSTALL_DIR=C:\\ci", "/GITHUB_URL=https://github.example/org"]


class Base(unittest.TestCase):
    def setUp(self):
        self.schema = S.load_schema()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_silent(self, argv, caption="Microsoft Windows 11 Pro", **kw):
        log = []
        code = S.run_silent(self.schema, argv, caption, self.tmp, NOW, log=log, **kw)
        return code, log


class SchemaTests(Base):
    def test_schema_generates_screens_and_silent_keys(self):
        """INST-REQ-020, 025: one source, both outputs equal; every non-secret input has a screen field and a silent key."""
        S.validate_schema(self.schema)
        screen_ids = {i for s in S.screen_list(self.schema) for i in s["inputs"]}
        keys = S.silent_keys(self.schema)
        self.assertEqual(set(keys.values()), {i["id"] for i in S.public_inputs(self.schema)})
        self.assertTrue(set(keys.values()) <= screen_ids)
        nsh = S.generate_nsh(self.schema)
        for key in keys:
            self.assertIn('"%s="' % key, nsh)
        for i in self.schema["inputs"]:
            self.assertIn("Var in_%s\n" % i["id"], nsh)
        for p in self.schema["pages"]:
            self.assertIn("Function Page_%s\n" % p["id"], nsh)

    def test_validator_refuses_duplicate_codes_and_a_digest_input(self):
        """INST-REQ-021, 026: a broken schema is refused before it can generate anything."""
        bad = json.loads(json.dumps(self.schema))
        bad["exit_codes"]["bad-value"] = bad["exit_codes"]["unknown-key"]
        with self.assertRaises(S.SchemaError):
            S.validate_schema(bad)
        bad = json.loads(json.dumps(self.schema))
        bad["inputs"].append({"id": "image_digest", "label": "d", "kind": "text", "page": "image"})
        with self.assertRaises(S.SchemaError):
            S.validate_schema(bad)

    def test_committed_screens_include_has_no_drift(self):
        """INST-REQ-020: the generated NSIS include is committed and must equal the generator output."""
        self.assertTrue(S.check_drift(self.schema))
        self.assertEqual(S.main(["check"]), 0)

    def test_drift_is_detected(self):
        p = Path(self.tmp) / "screens.nsh"
        p.write_text(S.generate_nsh(self.schema) + "; edited\n", encoding="utf-8")
        self.assertFalse(S.check_drift(self.schema, p))
        self.assertFalse(S.check_drift(self.schema, Path(self.tmp) / "missing.nsh"))

    def test_asked_inputs_are_those_required_and_digest_is_never_asked(self):
        """INST-REQ-021, 022: the inputs cover the required kinds; no digest input."""
        kinds = {i["kind"] for i in self.schema["inputs"]}
        self.assertTrue({"url", "secret", "list", "path", "choice"} <= kinds)
        ids = {i["id"] for i in self.schema["inputs"]}
        for needed in ("http_proxy", "dns_servers", "partner_id", "labview_version", "image_variant", "image_year", "allow_list"):
            self.assertIn(needed, ids)
        self.assertFalse([i for i in ids if "digest" in i])
        self.assertNotIn("/IMAGE_DIGEST", S.silent_keys(self.schema))
        code, log = self.run_silent(["/S", "/IMAGE_DIGEST=sha256:abc"])
        self.assertEqual(code, self.schema["exit_codes"]["unknown-key"])

    def test_digest_comes_from_pinned_list(self):
        """INST-REQ-021, 022: 2025 Q3 has no Windows container type; an unpinned or half-recorded entry is a typed refusal."""
        lst = self.schema["images"]["list"]
        self.assertFalse([e for e in lst if e["year"].startswith("2025") and e["variant"] == "windows"])
        self.assertIn("2025q3", [e["year"] for e in lst])
        fake = json.loads(json.dumps(self.schema))
        first = fake["images"]["list"][0]
        first["digest"], first["repository"] = "sha256:" + "a" * 64, None
        with self.assertRaises(S.ImageNotPinned):
            S.pinned_digest(fake, first["variant"], first["year"])  # a digest alone is not pinned: the repository is needed too
        first["repository"] = "registry.example/ni/labview"
        self.assertEqual(S.pinned_digest(fake, first["variant"], first["year"]), "sha256:" + "a" * 64)
        with self.assertRaises(S.ImageNotPinned):
            S.pinned_digest(fake, "windows", "2025q3")
        self.assertEqual(S.pinned_digest(self.schema, "linux", "2025q3"),
                         "sha256:9938561c6460841674f9b1871d8562242f51fe9fb72a2c39c66608491edf429c")

    def test_secrets_have_a_screen_only_and_a_separate_repeatable_step(self):
        """INST-REQ-076, 077: secrets sit on one interactive, repeatable page; one key per PC, replaced on repeat."""
        secrets = S.secret_inputs(self.schema)
        self.assertTrue(secrets)
        page = [p for p in self.schema["pages"] if p["id"] == "secrets"][0]
        self.assertTrue(page["interactive_only"] and page["repeatable"])
        self.assertTrue(all(i["page"] == "secrets" for i in secrets))
        self.assertEqual({i["page"] for i in self.schema["inputs"] if i["kind"] != "secret"} & {"secrets"}, set())
        step = self.schema["secrets_step"]
        self.assertEqual((step["key_scope"], step["on_repeat"], step["interactive_only"]), ("per-pc", "replace", True))
        for i in secrets:
            self.assertNotIn(S.silent_key(i["id"]), S.silent_keys(self.schema))
        self.assertIn("${NSD_CreatePassword}", S.generate_nsh(self.schema))

    def test_no_secret_in_the_source(self):
        """INST-REQ-024: no token-looking or key-material string in the installer sources."""
        bad = re.compile(r"ghp_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}|" + FAKE_TOKEN)
        for path in (ROOT / "installer").rglob("*"):
            if path.is_file() and path.suffix in (".py", ".json", ".nsh", ".nsi", ".ps1", ".md"):
                self.assertIsNone(bad.search(path.read_text(encoding="utf-8")), str(path))


class SilentTests(Base):
    def test_silent_exit_zero_only_on_success(self):
        """INST-REQ-025, 026: 0 on success; each failure class has its own non-zero code and a written reason."""
        self.assertEqual(self.run_silent(GOOD), (0, []))
        pinned = json.loads(json.dumps(self.schema))
        for e in pinned["images"]["list"]:
            e["digest"], e["repository"] = "sha256:" + "c" * 64, "registry.example/ni/labview"
        failures = {
            "unknown-key": self.run_silent(GOOD + ["/NOPE=1"]),
            "bad-value": self.run_silent(["/S", "/GITHUB_URL=not-a-url"]),
            "secret-on-command-line": self.run_silent(GOOD + ["/GITHUB_TOKEN=" + FAKE_TOKEN]),
            "secret-from-file-or-stdin": self.run_silent(GOOD + ["/SECRETFILE=x"]),
            "edition-refused": self.run_silent(GOOD, caption="Microsoft Windows 11 Home"),
            "licence-not-accepted": (S.run_silent(pinned, GOOD + ["/IMAGE_VARIANT=linux", "/IMAGE_YEAR=2025q3"], "Microsoft Windows 11 Pro", self.tmp, NOW, log=(plog := [])), plog),
            "image-not-pinned": self.run_silent(GOOD + ["/IMAGE_VARIANT=windows", "/IMAGE_YEAR=2025q3", "/NI_LICENCE_HELD=yes", "/ENGINE_LICENCE_ACCEPTED=yes"]),
        }
        codes = []
        for kind, (code, log) in failures.items():
            self.assertEqual(code, self.schema["exit_codes"][kind], kind)
            self.assertNotEqual(code, 0)
            self.assertTrue(log and log[0].startswith(kind + ":"), kind)
            codes.append(code)
        self.assertEqual(len(set(codes)), len(codes))
        self.assertEqual(len(set(self.schema["exit_codes"].values())), len(self.schema["exit_codes"]))

    def test_secret_on_command_line_gives_typed_exit(self):
        """INST-REQ-023, 075, 098: command line, file and stdin are each refused; the value is never logged."""
        for argv in (GOOD + ["/GITHUB_TOKEN=" + FAKE_TOKEN], GOOD + ["/MY_PASSWORD=" + FAKE_TOKEN],
                     GOOD + ["/REGISTRY_PASSWORD=" + FAKE_TOKEN], GOOD + ["/gitlab_token=" + FAKE_TOKEN]):
            code, log = self.run_silent(argv)
            self.assertEqual(code, self.schema["exit_codes"]["secret-on-command-line"], argv)
            self.assertNotIn(FAKE_TOKEN, " ".join(log))
        for argv in (GOOD + ["/SECRETFILE=" + FAKE_TOKEN], GOOD + ["-"], GOOD + ["/SECRETSTDIN"]):
            code, log = self.run_silent(argv)
            self.assertEqual(code, self.schema["exit_codes"]["secret-from-file-or-stdin"], argv)
            self.assertNotIn(FAKE_TOKEN, " ".join(log))
        code, log = self.run_silent(GOOD, stdin_is_secret=True)
        self.assertEqual(code, self.schema["exit_codes"]["secret-from-file-or-stdin"])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_unknown_key_with_a_secret_value_does_not_echo_it(self):
        code, log = self.run_silent(GOOD + ["/WHATEVER=" + FAKE_TOKEN])
        self.assertNotIn(FAKE_TOKEN, " ".join(log))
        self.assertEqual(code, self.schema["exit_codes"]["unknown-key"])

    def test_generated_include_refuses_secret_options(self):
        """INST-REQ-075, 098: the NSIS side refuses what parse_silent refuses: pattern words in any option name, file and stdin."""
        nsh = S.generate_nsh(self.schema)
        block = nsh.split("Function Refuse_Pass")[1].split("FunctionEnd")[0]
        self.assertEqual(nsh.split("!macro RefuseSecretOptions")[1].split("!macroend")[0].count("Call Refuse_Pass"), 2)
        sr = self.schema["secret_refusal"]
        for word in sr["name_pattern"].split("|"):
            self.assertIn('${StrStr} $R4 $R3 "%s"' % word, block)
        for o in sr["file_or_stdin_options"]:
            self.assertIn('$R3 == "/%s"' % o, block)
        self.assertIn('${If} $cl_tok == "-"', block)
        self.assertIn('${StrCase} $R3 $cl_name "U"', block)
        codes = self.schema["exit_codes"]
        self.assertEqual(block.count("SetErrorLevel %d" % codes["secret-on-command-line"]), len(sr["name_pattern"].split("|")))
        self.assertEqual(block.count("SetErrorLevel %d" % codes["secret-from-file-or-stdin"]), len(sr["file_or_stdin_options"]) + 1)
        self.assertEqual(block.count("Quit"), block.count("SetErrorLevel"))

    def test_pattern_words_refuse_unknown_names_like_the_generated_code(self):
        """INST-REQ-023: a never-seen *TOKEN* / *PASSW* option is a secret refusal, not an unknown key."""
        for name in ("/DEPLOY_TOKEN", "/ADMINPASSWD", "/API_KEY", "/x_secret"):
            code, log = self.run_silent(GOOD + [name + "=" + FAKE_TOKEN])
            self.assertEqual(code, self.schema["exit_codes"]["secret-on-command-line"], name)
            self.assertNotIn(FAKE_TOKEN, " ".join(log))

    @unittest.skipUnless(shutil.which("makensis"), "makensis not installed")
    def test_generated_include_compiles(self):
        nsi = Path(self.tmp) / "t.nsi"
        nsi.write_text('Unicode true\n!include "LogicLib.nsh"\n!include "%s"\n!include "%s"\n!include "%s"\nOutFile "%s"\nFunction Runner_Clear\nFunctionEnd\nFunction Runner_SetLocal\nFunctionEnd\nFunction Runner_SetGithub\nFunctionEnd\nFunction Runner_SetGitlab\nFunctionEnd\nFunction LogStep\nFunctionEnd\nFunction Carried_Box\nFunctionEnd\nFunction Carry_One\nFunctionEnd\nSection\n!insertmacro ParseSilentKeys\n'
                       '!insertmacro RefuseSecretOptions\nSectionEnd\n' % (S.SCREENS_PATH.with_name("cmdline.nsh"), S.SCREENS_PATH.with_name("dialog.nsh"),
                                                                        S.SCREENS_PATH, Path(self.tmp) / "t.exe"), encoding="utf-8")
        r = subprocess.run(["makensis", "-V1", str(nsi)], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_validator_refuses_secret_with_default_value_or_choices(self):
        """INST-REQ-024: a secret input carries no default, value or choices; secret-looking public keys are refused."""
        for field, val in (("default", "x"), ("value", "x"), ("choices", ["a"])):
            bad = json.loads(json.dumps(self.schema))
            [i for i in bad["inputs"] if i["kind"] == "secret"][0][field] = val
            with self.assertRaises(S.SchemaError, msg=field):
                S.validate_schema(bad)
        bad = json.loads(json.dumps(self.schema))
        bad["inputs"].append({"id": "my_token", "label": "t", "kind": "text", "page": "forge"})
        with self.assertRaises(S.SchemaError):
            S.validate_schema(bad)

    def test_values_are_validated_and_unknown_ids_are_typed(self):
        """INST-REQ-025, 026: no raw KeyError; required, text, list, path and image pairing are checked."""
        with self.assertRaises(S.UnknownKey):
            S.validate_values(self.schema, {"nope": "x"})
        for argv in (["/S"], ["/S", "/INSTALL_DIR= "], GOOD + ["/ALLOW_LIST=a,,b"], GOOD + ["/LABVIEW_VERSION="],
                     GOOD + ["/PARTNER_ID=a\x01b"], GOOD + ["/IMAGE_VARIANT=linux"], GOOD + ["/IMAGE_YEAR=2026q1"]):
            code, log = self.run_silent(argv)
            self.assertEqual(code, self.schema["exit_codes"]["bad-value"], argv)
            self.assertTrue(log)
        self.assertEqual(self.run_silent(GOOD + ["/ALLOW_LIST=a.example,b.example", "/LABVIEW_VERSION=2024"])[0], 0)

    def test_licence_record_written_only_after_the_image_is_pinned(self):
        """Licence answers are recorded only when the whole run is otherwise accepted."""
        code, _ = self.run_silent(GOOD + ["/IMAGE_VARIANT=windows", "/IMAGE_YEAR=2025q3", "/NI_LICENCE_HELD=yes", "/ENGINE_LICENCE_ACCEPTED=yes"])
        self.assertEqual(code, self.schema["exit_codes"]["image-not-pinned"])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_existing_licence_file_is_made_private(self):
        path = licences.record_path(self.tmp)
        path.write_text("old")
        os.chmod(path, 0o666)
        licences.write_record(self.tmp, NOW)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_silent_run_runs_unelevated_without_secrets_and_changes_nothing_without_image(self):
        """INST-REQ-033: no image chosen means no licence record and no state."""
        self.assertEqual(self.run_silent(GOOD)[0], 0)
        self.assertEqual(os.listdir(self.tmp), [])


class LicenceTests(Base):
    def test_licence_boxes_start_unticked_and_both_needed(self):
        """INST-REQ-018, 073: two separate boxes, shown only when an image is chosen, both needed."""
        self.assertEqual(licences.licence_boxes(False), [])
        boxes = licences.licence_boxes(True)
        self.assertEqual(len(boxes), 2)
        self.assertEqual({b["id"] for b in boxes}, set(licences.BOXES))
        self.assertFalse(any(b["ticked"] for b in boxes))
        self.assertFalse(licences.may_continue({}))
        self.assertFalse(licences.may_continue({"ni_licence_held": True}))
        self.assertFalse(licences.may_continue({"engine_licence_accepted": True}))
        self.assertFalse(licences.may_continue({"ni_licence_held": True, "engine_licence_accepted": False}))
        self.assertTrue(licences.may_continue({"ni_licence_held": True, "engine_licence_accepted": True}))
        page = [p for p in self.schema["pages"] if p["id"] == "licences"][0]
        self.assertEqual(page["only_when"], "image_chosen")
        self.assertIn('${If} $in_image_variant == ""', S.generate_nsh(self.schema))

    def test_silent_needs_both_licence_answers_when_image_chosen(self):
        fake = json.loads(json.dumps(self.schema))
        fake["images"]["list"][1]["digest"] = "sha256:" + "b" * 64
        fake["images"]["list"][1]["repository"] = "registry.example/ni/labview"
        img = ["/IMAGE_VARIANT=linux", "/IMAGE_YEAR=2026q1"]
        run = lambda extra: S.run_silent(fake, GOOD + img + extra, "Windows 11 Pro", self.tmp, NOW, log=[])
        self.assertEqual(run(["/NI_LICENCE_HELD=yes"]), 35)
        self.assertEqual(run(["/NI_LICENCE_HELD=yes", "/ENGINE_LICENCE_ACCEPTED=no"]), 35)
        self.assertEqual(os.listdir(self.tmp), [])
        self.assertEqual(run(["/NI_LICENCE_HELD=yes", "/ENGINE_LICENCE_ACCEPTED=yes"]), 0)

    def test_licence_record_has_utc_date_and_stays_local(self):
        """INST-REQ-019, 074: the record has a UTC date, is private, and nothing in the modules can reach the network."""
        path = licences.write_record(self.tmp, NOW)
        rec = json.loads(path.read_text())
        self.assertEqual(rec["utc"], "2026-11-21T12:00:00Z")
        self.assertEqual(rec["ni_development_licence_held"], "yes")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        for name in ("licences.py", "schema.py"):
            src = (ROOT / "installer" / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"^\s*(import|from)\s+(socket|urllib|http|ssl|smtplib|ftplib|requests)", src, re.M), name)

    def test_unwritable_state_is_a_typed_error(self):
        blocker = Path(self.tmp) / "file"
        blocker.write_text("x")
        with self.assertRaises(S.StateNotWritable):
            licences.write_record(blocker / "sub", NOW)


if __name__ == "__main__":
    unittest.main()
