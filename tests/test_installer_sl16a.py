"""SL-16a (ecosystem-control#102, part of #97 and #64): every typed value of the installer is checked, on the screens and in a silent run.
INST-REQ-021 (typed values), 023 (no secret on the command line), 026 (typed exits 30 bad value and 31 unknown key), 066 (https only), 076 (secrets).
The NSIS functions run in the small interpreter (tests/nsis_interp.py) over the real script text; no Windows, no network."""
import copy
import re
import unittest

from installer import schema as S
from tests.nsis_interp import World, Program, NSIS, source_text
from tests.test_installer_sl13 import func

MAIN = (NSIS / "main.nsi").read_text(encoding="utf-8")
SCREENS = (NSIS / "screens.nsh").read_text(encoding="utf-8")
SCHEMA = S.load_schema()
BY_ID = {i["id"]: i for i in SCHEMA["inputs"]}
BAD, UNKNOWN = SCHEMA["exit_codes"]["bad-value"], SCHEMA["exit_codes"]["unknown-key"]
CANARY = "CANARY-SECRET-7731"


def pinned_program():
    # an image pair is accepted only when it is pinned (digest and repository); the real table is still unpinned
    pinned = copy.deepcopy(SCHEMA)
    for n, e in enumerate(pinned["images"]["list"]):
        e["digest"], e["repository"] = "sha256:" + ("%02x" % (n + 1)) * 32, "registry.example/ni/" + e["variant"]
    files = source_text()
    files["screens.nsh"] = S.generate_nsh(pinned)
    return Program(files)


def init(cmdline, admin=True, silent=True):
    w = World(cmdline=cmdline, silent=silent, admin=admin, program=pinned_program())
    return w, w.run(".onInit")


def leave(page, texts=None, radios=None, preset=None):
    w = World(silent=False, texts={"ctl_" + k: v for k, v in (texts or {}).items()}, radios={"ctl_" + k: v for k, v in (radios or {}).items()}, program=pinned_program())
    w.var.update({"in_" + k: v for k, v in (preset or {}).items()})
    return w, w.run("Page_%s_Leave" % page)


def nothing_leaked(test, w, secret):
    for where, items in (("boxes", w.boxes), ("log", [str(x) for x in w.log]), ("details", w.details), ("files", list(w.files.values()))):
        test.assertFalse(any(secret in x for x in items), where)


# (input id, value, the value is good); the rule is written once and runs through validate_values and through the NSIS text.
TABLE = [
    ("install_dir", "C:\\Tools\\x", True), ("install_dir", 'C:\\a"b', False),
    ("work_dir", "D:\\work", True), ("work_dir", 'D:"w', False),
    ("github_url", "https://github.com", True), ("github_url", "HTTPS://GitHub.com", True), ("github_url", "https://h.example:8443/x?y#z", True),
    ("github_url", "http://github.com", False), ("github_url", "https://", False), ("github_url", "https:///x", False), ("github_url", "https://:80", False),
    ("github_url", "https://u@h.example", False), ("github_url", "https://h.example:abc", False), ("github_url", "https://h.example:123456", False),
    ("github_url", "https://h.example:", False), ("github_url", "https://[::1]", False), ("github_url", "ftp://h.example", False), ("github_url", "github.com", False),
    ("gitlab_url", "https://gitlab.example", True), ("gitlab_url", "http://gitlab.example", False), ("gitlab_url", "https://g.example:80", True),
    ("partner_id", "ACME-1", True), ("partner_id", 'AC"ME', False),
    ("partner_id", "   ", False), ("install_dir", " ", False), ("github_url", "   ", False), ("allow_list", "   ", False),
    ("allow_list", "a", True), ("allow_list", "a,b,c", True), ("allow_list", "a,,b", False), ("allow_list", ",a", False), ("allow_list", "a,", False),
    ("allow_list", "a, ,b", False), ("allow_list", "a, b", True),
    ("http_proxy", "http://p:3128", True), ("http_proxy", "https://p", True), ("http_proxy", "ftp://p", False), ("http_proxy", "http://", False), ("http_proxy", "http:///x", False),
    ("http_proxy", "HTTP://p", False), ("http_proxy", "proxy", False),
    ("dns_servers", "1.1.1.1,8.8.8.8", True), ("dns_servers", "1.1.1.1,", False), ("dns_servers", "1.1.1.1,,8.8.8.8", False),
    ("labview_version", "2024 Q3", True), ("labview_version", 'x"y', False),
    ("image_variant", "windows", True), ("image_variant", "WINDOWS", True), ("image_variant", "bsd", False),
    ("image_variant", "both", False),
    ("image_year", "2026q1", True), ("image_year", "1999", False),
    ("ni_licence_held", "yes", True), ("ni_licence_held", "No", True), ("ni_licence_held", "maybe", False),
    ("github_token", "ghs_abc123", True), ("github_token", "a b", False), ("github_token", 'a"b', False), ("github_token", "a'b", False), ("github_token", "a`b", False),
    ("github_token", "a\\b", False), ("github_token", "a\tb", False),
    ("gitlab_token", "glrt-xyz", True), ("gitlab_token", "x y", False), ("registry_password", "p@ss/word", True), ("registry_password", "p ass", False),
]
COMPANION = {"image_variant": ("image_year", "2026q1"), "image_year": ("image_variant", "windows")}
SHOWN = {e["year"]: e["label"] for e in SCHEMA["images"]["list"]}  # the version list shows the label of the version


def python_says(i, v):
    values = {i: v}
    if i in COMPANION:
        values[COMPANION[i][0]] = COMPANION[i][1]
    try:
        S.validate_values(SCHEMA, {**values, "install_dir": values.get("install_dir", "x")})
        return True
    except S.BadValue:
        return False


class OneRuleTwoWriters(unittest.TestCase):
    def test_validate_values_and_the_silent_script_agree_on_every_value_026(self):
        for i, v, good in TABLE:
            # a double quote never reaches a value from the command line (the one reader drops it); the screens test below still feeds it to the checks
            if BY_ID[i]["kind"] == "secret" or " " in v or "\t" in v or '"' in v:
                continue
            with self.subTest(i=i, v=v):
                self.assertEqual(python_says(i, v), good)
                cmd = "/S /%s=%s" % (i.upper(), '"%s"' % v if "/" in v else v)
                if i in COMPANION:
                    cmd += " /%s=%s" % (COMPANION[i][0].upper(), COMPANION[i][1])
                if i in COMPANION:
                    cmd += " /NI_LICENCE_HELD=yes /ENGINE_LICENCE_ACCEPTED=yes"
                w, code = init(cmd)
                self.assertEqual(code, None if good else BAD, (cmd, w.log))

    def test_validate_values_and_the_screens_agree_on_every_value_026(self):
        for i, v, good in TABLE:
            if BY_ID[i]["kind"] == "licence":
                continue
            with self.subTest(i=i, v=v):
                self.assertEqual(python_says(i, v), good)
                texts = {i: v}
                if i in COMPANION:
                    texts[COMPANION[i][0]] = COMPANION[i][1]
                if "image_year" in texts:
                    texts["image_year"] = SHOWN.get(texts["image_year"], texts["image_year"])
                w, code = leave(BY_ID[i]["page"], texts)
                self.assertEqual(code, None if good else "abort", (i, v, w.boxes))
                self.assertEqual(len(w.boxes), 0 if good else 1)

    def test_the_https_rule_is_written_for_the_forge_addresses_only_066(self):
        self.assertTrue(BY_ID["github_url"]["https_only"] and BY_ID["gitlab_url"]["https_only"])
        self.assertFalse(BY_ID["http_proxy"].get("https_only"))
        self.assertTrue(all(BY_ID[k].get("no_blank") for k in ("github_token", "gitlab_token", "registry_password")))

    def test_a_choice_is_compared_without_case_and_stored_in_lower_case(self):
        w, code = init("/S /IMAGE_VARIANT=WiNdOwS /IMAGE_YEAR=2026q1 /NI_LICENCE_HELD=yes /ENGINE_LICENCE_ACCEPTED=yes")
        self.assertEqual((code, w.var["in_image_variant"]), (None, "windows"))
        w, code = leave("image", {"image_variant": "LINUX", "image_year": "2026 Q1"})
        self.assertEqual((code, w.var["in_image_variant"]), (None, "linux"))

    def test_image_variant_and_year_come_together_on_both_paths(self):
        for cmd in ("/S /IMAGE_VARIANT=windows", "/S /IMAGE_YEAR=2025q3"):
            self.assertEqual(init(cmd)[1], BAD, cmd)
            with self.assertRaises(S.BadValue):
                S.validate_values(SCHEMA, {**S.parse_silent(SCHEMA, cmd.split()), "install_dir": "x"})
        for texts in ({"image_variant": "windows"}, {"image_variant": "windows", "image_year": "2025 Q3"}):
            w, code = leave("image", texts)
            self.assertEqual((code, len(w.boxes)), ("abort", 1), texts)
        w, code = leave("image", {"image_year": "2025 Q3"})  # (none): the version list is empty, nothing is read from it
        self.assertEqual((code, w.boxes, w.var["in_image_year"]), (None, [], ""))
        w, code = leave("image", {})
        self.assertEqual((code, w.boxes), (None, []))


class SilentNamesAndValues(unittest.TestCase):
    def test_an_unknown_key_exits_31_and_logs_the_name_only_026(self):
        w, code = init("/S /FOO=%s" % CANARY)
        self.assertEqual(code, UNKNOWN)
        self.assertEqual(w.log, [("unknown-key", "/FOO", str(UNKNOWN))])
        nothing_leaked(self, w, CANARY)

    def test_a_known_key_without_a_value_exits_30(self):
        for cmd in ("/S /PARTNER_ID", "/S /PARTNER_ID=", "/S /ALLOW_LIST", "/S /MODE"):
            w, code = init(cmd)
            self.assertEqual(code, BAD, cmd)

    def test_the_installer_own_switches_are_never_unknown(self):
        sig = "a" * 64
        for cmd in ("/S", "/S /D=C:\\Tools", "/S /NCRC", "/S /ELEVATED", "/S /SIGNER=%s" % sig, "/S /NCRC /SIGNER=%s /ELEVATED /D=C:\\x" % sig, "/s /signer=%s" % sig):
            w, code = init(cmd)
            self.assertIsNone(code, cmd)
            self.assertEqual(w.log, [], cmd)

    def test_keys_are_found_without_case_and_a_good_run_is_unchanged(self):
        w, code = init("/S /partner_id=ACME /allow_list=a,b")
        self.assertIsNone(code)
        self.assertEqual((w.var["in_partner_id"], w.var["in_allow_list"]), ("ACME", "a,b"))
        self.assertLess(w.trace.index("Check_partner_id"), w.trace.index("TrustCheck"))

    def test_no_key_at_all_leaves_the_run_as_it_was(self):
        w, code = init("/S")
        self.assertIsNone(code)
        self.assertEqual((w.log, w.boxes, w.files), ([], [], {}))
        self.assertIn("TrustCheck", w.trace)

    def test_names_are_checked_before_values_and_a_bad_value_exits_30(self):
        self.assertEqual(init('/S /PARTNER_ID="a\tb" /FOO=1')[1], UNKNOWN)
        self.assertEqual(init('/S /PARTNER_ID="a\tb"')[1], BAD)

    def test_a_bad_value_is_logged_by_key_name_and_writes_nothing(self):
        w, code = init('/S /PARTNER_ID="a\t%s"' % CANARY)
        self.assertEqual((code, w.log, w.files), (BAD, [("partner_id", "/PARTNER_ID", str(BAD))], {}))
        self.assertEqual(w.boxes, [])
        nothing_leaked(self, w, CANARY)

    def test_validation_runs_before_the_trust_check_and_before_the_elevation_gate(self):
        w, code = init('/S /PARTNER_ID="a\tb"', admin=False)
        self.assertEqual((code, w.trace.count("TrustCheck"), "Elevate_SilentGate" in w.trace), (BAD, 0, False))
        w, code = init("/S /PARTNER_ID=ok", admin=False)
        self.assertEqual(code, 38)
        self.assertLess(w.trace.index("TrustCheck"), w.trace.index("Elevate_SilentGate"))
        w, code = init("/S /FOO=1", admin=False)
        self.assertEqual((code, "TrustCheck" in w.trace), (UNKNOWN, False))

    def test_the_secret_refusals_still_come_first_032_033(self):
        self.assertEqual(init("/S /GITHUB_TOKEN=%s" % CANARY)[1], SCHEMA["exit_codes"]["secret-on-command-line"])
        self.assertEqual(init("/S /FOO=1 -")[1], SCHEMA["exit_codes"]["secret-from-file-or-stdin"])

    def test_a_quoted_value_with_a_blank_is_one_value(self):
        w, code = init('/S /INSTALL_DIR="C:\\Program Files\\x"')
        self.assertEqual((code, w.var["in_install_dir"]), (None, "C:\\Program Files\\x"))

    def test_a_blank_only_value_exits_30(self):
        self.assertEqual(init('/S /PARTNER_ID="   "')[1], BAD)

    def test_the_mode_choice_still_decides_first(self):
        self.assertEqual(init("/S /MODE=nonsense /FOO=1")[1], BAD)

    def test_required_is_not_enforced_for_the_install_folder(self):
        self.assertTrue(BY_ID["install_dir"]["required"])
        self.assertIsNone(init("/S /WORK_DIR=D:\\w")[1])


class ScreensLeave(unittest.TestCase):
    def test_every_page_with_inputs_has_its_leave_wired_in_main_nsi(self):
        for p in SCHEMA["pages"]:
            if any(i["page"] == p["id"] for i in SCHEMA["inputs"]):
                show = "Page_mode_Pre" if p["id"] == "mode" else "Page_" + p["id"]  # SL-19: the mode page is skipped for an update or repair
                self.assertIn("\nPage custom %s Page_%s_Leave\n" % (show, p["id"]), MAIN, p["id"])
                self.assertIn("\nFunction Page_%s_Leave\n" % p["id"], SCREENS)

    def test_the_page_keeps_handles_apart_from_typed_values(self):
        for p in SCHEMA["pages"]:
            if p["id"] == "mode":
                continue
            body = func(SCREENS, "Page_" + p["id"])
            self.assertNotRegex(body, r"Pop \$in_")
            self.assertRegex(body, r"Pop \$ctl_")

    def test_a_bad_value_shows_one_silent_safe_message_naming_the_field_and_stays(self):
        w, code = leave("forge", {"github_url": "http://github.com", "gitlab_url": "http://also.bad"})
        self.assertEqual(code, "abort")
        self.assertEqual(len(w.boxes), 1)
        self.assertTrue(w.boxes[0].startswith("MB_OK|MB_ICONEXCLAMATION GitHub address: must start with https://."), w.boxes)
        self.assertTrue(w.boxes[0].endswith("/SD IDOK"))

    def test_every_message_box_added_by_the_leaves_is_silent_safe(self):
        for p in SCHEMA["pages"]:
            if p["id"] != "mode" and any(i["page"] == p["id"] for i in SCHEMA["inputs"]):
                for line in func(SCREENS, "Page_%s_Leave" % p["id"]).splitlines():
                    if "MessageBox" in line:
                        self.assertTrue(line.rstrip().endswith("/SD IDOK"), line)

    def test_an_empty_optional_field_passes_and_a_good_page_shows_nothing(self):
        for page in ("folders", "forge", "network", "labview", "image", "secrets"):
            w, code = leave(page, {})
            self.assertEqual((code, w.boxes), (None, []), page)
        w, code = leave("forge", {"github_url": "https://github.com", "allow_list": "a,b"})
        self.assertEqual((code, w.boxes), (None, []))
        self.assertEqual(w.var["in_github_url"], "https://github.com")

    def test_the_licence_boxes_are_stored_as_yes_or_no(self):
        w, code = leave("licences", {}, radios={"ni_licence_held": True})
        self.assertEqual((code, w.var["in_ni_licence_held"], w.var["in_engine_licence_accepted"]), ("abort", "yes", "no"))
        w, code = leave("licences", {}, radios={"ni_licence_held": True, "engine_licence_accepted": True})
        self.assertEqual((code, w.var["in_ni_licence_held"], w.var["in_engine_licence_accepted"]), (None, "yes", "yes"))

    def test_the_licence_page_is_still_skipped_without_an_image(self):
        w = World(silent=False)
        w.var["in_image_variant"] = ""
        self.assertEqual(w.run("Page_licences"), "abort")
        w, code = leave("image", {})
        self.assertEqual(w.var["in_image_variant"], "")
        w2 = World(silent=False)
        w2.var["in_image_variant"] = w.var["in_image_variant"]
        self.assertEqual(w2.run("Page_licences"), "abort")

    def test_secrets_leave_reads_the_masked_fields_and_names_the_field_never_the_value(self):
        w, code = leave("secrets", {"github_token": CANARY + " x", "gitlab_token": "fine"})
        self.assertEqual(code, "abort")
        self.assertEqual(len(w.boxes), 1)
        self.assertIn("GitHub registration token: must not hold a space, quote, backslash or control character.", w.boxes[0])
        nothing_leaked(self, w, CANARY)

    def test_a_good_secret_is_kept_in_memory_only(self):
        w, code = leave("secrets", {"github_token": CANARY, "gitlab_token": CANARY + "2", "registry_password": CANARY + "3"})
        self.assertIsNone(code)
        self.assertEqual((w.var["in_github_token"], w.var["in_gitlab_token"], w.var["in_registry_password"]), (CANARY, CANARY + "2", CANARY + "3"))
        nothing_leaked(self, w, CANARY)
        self.assertEqual(w.files, {})

    def test_the_folders_are_checked_and_kept_but_not_applied(self):
        w, code = leave("folders", {"install_dir": "C:\\Tools\\x", "work_dir": "D:\\w"})
        self.assertEqual((code, w.var["in_install_dir"], w.files), (None, "C:\\Tools\\x", {}))
        self.assertNotIn("$INSTDIR", MAIN + SCREENS)

    def test_the_secret_value_is_never_logged_shown_or_written_by_the_generated_text(self):
        for i in SCHEMA["inputs"]:
            if i["kind"] == "secret":
                for line in SCREENS.splitlines():
                    if re.search(r"(DetailPrint|LogStep|FileWrite|MessageBox|Push)", line):
                        self.assertNotIn("$in_" + i["id"], line)


class InterpreterAdditions(unittest.TestCase):
    """The new instructions of the test interpreter, each with its own proof."""

    def run_text(self, body, **kw):
        prog = Program({"t.nsh": "Function T\n%s\nFunctionEnd\n" % body})
        w = World(program=prog, **kw)
        return w, w.run("T")

    def test_strlen_and_a_character_loop(self):
        w, _ = self.run_text('  StrCpy $R0 "abc"\n  StrLen $R2 $R0\n  StrCpy $R3 0\n  StrCpy $R5 ""\n  ${Do}\n    ${If} $R3 >= $R2\n      ${ExitDo}\n    ${EndIf}\n'
                             '    StrCpy $R1 $R0 1 $R3\n    StrCpy $R5 "$R1$R5"\n    IntOp $R3 $R3 + 1\n  ${Loop}')
        self.assertEqual((w.var["R2"], w.var["R5"]), ("3", "cba"))

    def test_gettext_reads_the_scripted_field_and_an_empty_one(self):
        w, _ = self.run_text("  ${NSD_GetText} $ctl_a $in_a\n  ${NSD_GetText} $ctl_b $in_b", texts={"ctl_a": "hi"})
        self.assertEqual((w.var["in_a"], w.var["in_b"]), ("hi", ""))

    def test_abort_inside_a_leave_is_reported_and_stops_the_function(self):
        w, code = self.run_text('  Abort\n  StrCpy $R0 "after"')
        self.assertEqual((code, w.var.get("R0")), ("abort", None))

    def test_else_and_numeric_comparisons(self):
        w, _ = self.run_text('  StrCpy $R0 7\n  ${If} $R0 > 9\n    StrCpy $R1 big\n  ${Else}\n    StrCpy $R1 small\n  ${EndIf}\n  ${If} $R0 <= 7\n    StrCpy $R2 le\n  ${EndIf}')
        self.assertEqual((w.var["R1"], w.var["R2"]), ("small", "le"))

    def test_a_message_box_text_is_expanded_and_detailprint_is_recorded(self):
        w, _ = self.run_text('  StrCpy $R9 "why"\n  MessageBox MB_OK "x: $R9." /SD IDOK\n  DetailPrint "d $R9"')
        self.assertEqual((w.boxes, w.details), (["MB_OK x: why. /SD IDOK"], ["d why"]))

    def test_strcpy_takes_a_length_and_an_offset_from_variables_and_an_empty_length(self):
        w, _ = self.run_text('  StrCpy $R0 "hello"\n  StrCpy $R3 1\n  StrCpy $R1 $R0 2 $R3\n  StrCpy $R2 $R0 "" 2')
        self.assertEqual((w.var["R1"], w.var["R2"]), ("el", "llo"))

    def test_tab_cr_and_lf_escapes(self):
        w, _ = self.run_text('  StrCpy $R0 "a$\\tb"')
        self.assertEqual(w.var["R0"], "a\tb")

    def test_an_unknown_instruction_still_raises(self):
        with self.assertRaises(ValueError):
            self.run_text("  Frobnicate $R0")


class SchemaAttributes(unittest.TestCase):
    def test_the_rule_attributes_are_only_on_their_own_kinds(self):
        for i in SCHEMA["inputs"]:
            if i.get("https_only"):
                self.assertEqual(i["kind"], "url")
            if i.get("no_blank"):
                self.assertEqual(i["kind"], "secret")

    def test_the_generated_include_has_no_drift_and_the_exit_codes_are_untouched(self):
        self.assertTrue(S.check_drift(SCHEMA))
        self.assertEqual({k: v for k, v in SCHEMA["exit_codes"].items() if v in (30, 31)}, {"bad-value": 30, "unknown-key": 31})

    def test_one_check_function_per_input_that_is_not_a_setter(self):
        for i in SCHEMA["inputs"]:
            self.assertEqual("\nFunction Check_%s\n" % i["id"] in SCREENS, not i.get("setter"), i["id"])


if __name__ == "__main__":
    unittest.main()
