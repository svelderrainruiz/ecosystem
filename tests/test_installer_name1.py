"""NAME-1 (ecosystem-control#158, part of #64): it is the "NI docker image", and one installation has exactly one container type.
INST-REQ-021 (what is asked), INST-REQ-022 (exactly one container type: a Windows container or a Linux container, never both), INST-REQ-099 (the pull).
The wording is pinned at its source (schema.json, schema.py) and where it reaches the user (the generated screens.nsh and image.nsh).
The single choice and the single pull run in the small interpreter (tests/nsis_interp.py) over the real script text; the routes that
reach the pull are pinned in the source, because a whole install or update run is not modelled."""
import re
import unittest
from pathlib import Path

from installer import image
from installer import schema as S
from tests.nsis_interp import NSIS
from tests.test_installer_sl13 import func
from tests.test_installer_sl16b import BOTH, CODES, DESKTOP, RECORD, init, leave, pinned_schema, ready, with_engine, world

ROOT = Path(__file__).resolve().parent.parent
TITLE = "NI docker image"
TYPE_LABEL = "NI docker image container type"
YEAR_LABEL = "NI docker image version"
TOGETHER = "Choose both the NI docker image container type and version, or neither"
PIN = "This NI docker image container type and version are not in the pinned list"
PULLING = "Pulling the NI docker image. This can take a long time; Cancel waits until it ends."
FAILED = "The NI docker image could not be pulled. The installation stays: run the installer again to repair."
TYPES = ["windows", "linux"]
OLD = re.compile(r"(?i)\bNI image\b|container image|image variant")


def box(msg):
    return "MB_OK|MB_ICONEXCLAMATION %s /SD IDOK" % msg


def text(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def inputs():
    return {i["id"]: i for i in S.load_schema()["inputs"]}


class WordingAtTheSource(unittest.TestCase):
    def test_the_page_title_and_the_two_labels_inst_req_021(self):
        pages = {p["id"]: p["title"] for p in S.load_schema()["pages"]}
        self.assertEqual(pages["image"], TITLE)
        self.assertEqual((inputs()["image_variant"]["label"], inputs()["image_year"]["label"]), (TYPE_LABEL, YEAR_LABEL))

    def test_the_two_validation_messages(self):
        self.assertEqual((S.TOGETHER_TEXT, S.PIN_TEXT), (TOGETHER, PIN))

    def test_the_ids_values_and_keys_did_not_change(self):
        self.assertEqual((inputs()["image_variant"]["page"], inputs()["image_year"]["page"]), ("image", "image"))
        self.assertEqual(S.TOGETHER, ("image_variant", "image_year"))
        self.assertEqual(sorted({e["variant"] for e in S.load_schema()["images"]["list"]}), sorted(TYPES))


class WordingWhereTheUserSeesIt(unittest.TestCase):
    def test_the_generated_page_carries_the_new_labels_and_messages(self):
        nsh = text("installer/nsis/screens.nsh")
        self.assertEqual(nsh, S.generate_nsh(S.load_schema()))
        self.assertEqual(nsh.count('${NSD_CreateLabel} 0u 24u 100% 8u "' + TYPE_LABEL + '"'), 1)
        self.assertEqual(nsh.count('${NSD_CreateLabel} 0u 48u 100% 8u "' + YEAR_LABEL + '"'), 1)
        self.assertEqual(nsh.count('Push "%s"' % TYPE_LABEL), 1)
        self.assertEqual(nsh.count('Push "%s"' % YEAR_LABEL), 1)
        self.assertEqual(nsh.count('"%s: $R9."' % TYPE_LABEL), 1)
        self.assertEqual(nsh.count('"%s: $R9."' % YEAR_LABEL), 1)
        self.assertEqual(nsh.count('StrCpy $R9 "%s"' % TOGETHER), 2)
        self.assertEqual(nsh.count('StrCpy $R9 "%s"' % PIN), 1)

    def test_the_pull_texts_inst_req_099(self):
        nsh = text("installer/nsis/image.nsh")
        self.assertEqual(nsh.count('DetailPrint "%s"' % PULLING), 1)
        self.assertEqual(nsh.count('MessageBox MB_OK|MB_ICONEXCLAMATION "%s" /SD IDOK' % FAILED), 1)

    def test_no_old_wording_is_left_where_the_user_or_the_build_reads_it(self):
        for rel in ("installer/schema.json", "installer/schema.py", "installer/nsis/screens.nsh", "installer/nsis/image.nsh", "installer/image.py"):
            self.assertEqual(OLD.findall(text(rel)), [], rel)

    def test_no_ni_image_is_left_in_the_installer_or_its_spec(self):
        found = []
        for folder in (ROOT / "installer", ROOT / "docs" / "installer-spec"):
            for p in sorted(folder.rglob("*")):
                if p.is_file() and p.suffix in {".py", ".nsh", ".nsi", ".json", ".md", ".ps1"}:
                    found += ["%s:%d" % (p.relative_to(ROOT), n) for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                              if re.search(r"(?i)\bNI image\b", line)]
        self.assertEqual(found, [])

    def test_the_spec_rows_say_ni_docker_image_and_022_says_one_container_type(self):
        rows = {r.split("|")[1].strip(): r for r in text("docs/installer-spec/srs.md").splitlines() if r.startswith("| INST-REQ-")}
        for req in ("INST-REQ-021", "INST-REQ-099", "INST-REQ-100"):
            self.assertIn("NI docker image", rows[req], req)
        self.assertIn("exactly one container type per installation: a Windows container or a Linux container, never both.", rows["INST-REQ-022"])

    def test_the_user_reads_the_new_messages_on_the_page(self):
        w, code = leave("image", texts={"image_variant": "linux", "image_year": ""})
        self.assertEqual((code, w.boxes), ("abort", [box(TOGETHER + ".")]))
        w, code = leave("image", texts={"image_variant": "windows", "image_year": "2025 Q3"})  # not in the windows list: no version chosen
        self.assertEqual((code, w.boxes), ("abort", [box(TOGETHER + ".")]))
        w = ready(world(silent=False), variant="windows", year="2025q3")
        w.run("Image_Known")
        self.assertEqual(w.var["R9"], PIN)
        w, code = leave("image", texts={"image_variant": "both", "image_year": "2026 Q1"})
        self.assertEqual((code, w.boxes), ("abort", [box(TYPE_LABEL + ": must be one of windows, linux.")]))

    def test_the_user_reads_the_new_pull_texts(self):
        w = with_engine(ready(world(schema=pinned_schema(), exec_codes=["1"])))
        w.files[RECORD] = "{}"
        self.assertEqual(w.run("Image_Pull"), CODES["image-pull-failed"])
        self.assertEqual((w.details, w.boxes), (["Checking which container type Docker runs.", PULLING], [box(FAILED)]))


class OneContainerType(unittest.TestCase):
    def test_the_field_is_one_choice_of_exactly_windows_and_linux_inst_req_022(self):
        f = inputs()["image_variant"]
        self.assertEqual((f["kind"], f["choices"]), ("choice", TYPES))
        self.assertIn("INST-REQ-022", f["req"])
        pairs = [(e["variant"], e["year"]) for e in S.load_schema()["images"]["list"]]
        self.assertEqual(len(pairs), len(set(pairs)))
        self.assertTrue(all(v in TYPES for v, _ in pairs), pairs)

    def test_the_page_takes_one_type_and_refuses_both_or_a_third(self):
        for v in ("windows,linux", "windows linux", "linux;windows", "both", "windows+linux", "wsl", "macos"):
            w, code = leave("image", texts={"image_variant": v, "image_year": "2026 Q1"})
            self.assertEqual((code, w.boxes), ("abort", [box(TYPE_LABEL + ": must be one of windows, linux.")]), v)
        for v, kept in (("windows", "windows"), ("LINUX", "linux")):
            w, code = leave("image", texts={"image_variant": v, "image_year": "2026 Q1"}, schema=pinned_schema())
            self.assertEqual((code, w.boxes, w.var["in_image_variant"]), (None, [], kept), v)

    def test_a_silent_run_that_asks_for_both_exits_30_and_pulls_nothing(self):
        for v in ("windows,linux", "both"):
            w, code = init("/S /IMAGE_VARIANT=%s /IMAGE_YEAR=2026q1%s" % (v, BOTH), pinned_schema())
            self.assertEqual((code, w.execs, w.files), (CODES["bad-value"], [], {}), v)

    def test_one_run_pulls_at_most_one_reference_inst_req_099(self):
        s = pinned_schema()
        for e in s["images"]["list"]:
            w = with_engine(ready(world(schema=s), variant=e["variant"], year=e["year"]))
            w.files[RECORD] = "{}"
            self.assertIsNone(w.run("Image_Pull"))
            self.assertEqual(w.execs, [[DESKTOP, "pull", image.reference(e["repository"], e["digest"])]], e)
        w = with_engine(ready(world(schema=s), variant="", year=""))
        w.files[RECORD] = "{}"
        self.assertIsNone(w.run("Image_Pull"))
        self.assertEqual(w.execs, [])

    def test_the_pull_has_the_mode_probe_one_pull_and_no_loop(self):
        body = func(text("installer/nsis/image.nsh"), "Image_Pull")
        self.assertEqual(len(re.findall(r"nsExec::", body, re.I)), 2)
        self.assertEqual(re.findall(r"nsExec::.*", body, re.I), ["nsExec::ExecToStack '\"$ImgEngine\" info --format {{.OSType}}'", "nsExec::Exec '\"$ImgEngine\" pull $ImgRef'"])
        self.assertNotRegex(body, r"(?i)\bGoto\b|\$\{(Do|While|For|ForEach|Loop)")

    def test_each_route_ends_in_the_one_pull_and_a_run_takes_one_route(self):
        files = {p.name: p.read_text(encoding="utf-8") for p in sorted(NSIS.glob("*.ns[hi]"))}
        calls = sorted((name, n) for name, t in files.items() for n, line in enumerate(t.splitlines(), 1) if line.strip() == "Call Image_Pull")
        self.assertEqual(len(calls), 3, calls)
        for name, fn in (("install.nsh", "Install_Footprint"), ("update.nsh", "Update_Apply"), ("update.nsh", "Update_Repair")):
            body = [line.strip() for line in func(files[name], fn).splitlines() if line.strip() and not line.strip().startswith(";")]
            self.assertEqual(body[-1], "Call Image_Pull", fn)
            self.assertEqual(body.count("Call Image_Pull"), 1, fn)
        route = [line.strip() for line in func(files["update.nsh"], "Update_Route").splitlines() if line.strip()]
        self.assertEqual(route, ["Call Update_Detect", '${If} $upd_mode == "update"', "Call Update_Apply", '${ElseIf} $upd_mode == "repair"',
                                 "Call Update_Repair", "${Else}", "Call Install_Footprint", "${EndIf}"])
        self.assertEqual(sum(t.count("Call Update_Route") for t in files.values()), 1)
        self.assertEqual(sum(t.count(c) for t in files.values() for c in ("Call Update_Apply", "Call Update_Repair", "Call Install_Footprint")), 3)


if __name__ == "__main__":
    unittest.main()


WINDOWS_LABELS = ["2026 Q3", "2026 Q1 patch 2", "2026 Q1 patch 1", "2026 Q1"]
LINUX_LABELS = WINDOWS_LABELS + ["2025 Q3 patch 1", "2025 Q3"]
HELP = "Choose the container type, then the NI docker image version. The runner uses it; it is pulled at install time. (none) skips it."


def page(preset=None):
    w = world(silent=False)
    w.var.update({"in_image_variant": "", "in_image_year": ""})
    w.var.update(preset or {})
    return w, w.run("Page_image")


class DropDownPage(unittest.TestCase):
    """#329: the NI docker image page is two drop-down lists filled from the pinned table; nothing is typed."""

    def test_the_pinned_table_is_the_ten_docker_hub_tags_with_full_digests_and_no_latest(self):
        lst = S.load_schema()["images"]["list"]
        self.assertEqual([(e["variant"], e["label"]) for e in lst], [("windows", x) for x in WINDOWS_LABELS] + [("linux", x) for x in LINUX_LABELS])
        for e in lst:
            self.assertEqual((e["tag"], e["repository"]), ("%s-%s" % (e["year"], e["variant"]), "docker.io/nationalinstruments/labview"), e)
            self.assertRegex(e["digest"], r"^sha256:[0-9a-f]{64}$")
            self.assertNotIn("latest", e["tag"])

    def test_the_page_offers_none_windows_linux_and_an_empty_greyed_version_list(self):
        w, code = page()
        self.assertEqual(code, None)
        self.assertEqual((w.combos["ctl_image_variant"], w.texts["ctl_image_variant"]), (["(none)"] + TYPES, "(none)"))
        self.assertEqual((w.combos["ctl_image_year"], w.texts["ctl_image_year"]), ([], ""))
        self.assertEqual(w.callbacks, {"ctl_image_variant": "Image_TypeChanged"})

    def test_a_change_of_container_type_refills_the_version_list_with_its_pinned_versions_only(self):
        w, _ = page()
        for v, labels in (("windows", WINDOWS_LABELS), ("linux", LINUX_LABELS), ("(none)", [])):
            w.texts["ctl_image_variant"] = v
            w.stack.append("handle")  # nsDialogs hands the control over on the stack
            w.call(w.callbacks["ctl_image_variant"])
            self.assertEqual((w.combos["ctl_image_year"], w.texts["ctl_image_year"], w.windows["handle"]), (labels, "", 1 if labels else 0), v)

    def test_back_from_a_later_page_shows_the_held_answers_again(self):
        for v, y, label in (("windows", "2026q1patch2", "2026 Q1 patch 2"), ("linux", "2025q3patch1", "2025 Q3 patch 1"), ("linux", "2026q1", "2026 Q1")):
            w, _ = page({"in_image_variant": v, "in_image_year": y})
            self.assertEqual((w.texts["ctl_image_variant"], w.texts["ctl_image_year"]), (v, label))

    def test_none_is_no_image_and_the_licence_page_is_skipped(self):
        w, code = leave("image", texts={"image_variant": "(none)", "image_year": ""})
        self.assertEqual((code, w.boxes, w.var["in_image_variant"], w.var["in_image_year"]), (None, [], "", ""))
        self.assertEqual(w.run("Page_licences"), "abort")

    def test_each_shown_pair_gives_its_pinned_digest_reference(self):
        for e in S.load_schema()["images"]["list"]:
            w, code = leave("image", texts={"image_variant": e["variant"], "image_year": e["label"]})
            self.assertEqual((code, w.boxes), (None, []), e)
            w.run("Image_Ref")
            self.assertEqual(w.var["R8"], "docker.io/nationalinstruments/labview@" + e["digest"])
            self.assertEqual(w.var["R8"], image.reference(e["repository"], e["digest"]))

    def test_the_layout_has_the_help_on_top_and_no_overlap(self):
        body = func(text("installer/nsis/screens.nsh"), "Page_image")
        rows = re.findall(r"\$\{NSD_Create(\w+)\} 0u (\d+)u 100% (\d+)u \"([^\"]*)\"", body)
        self.assertEqual(rows, [("Label", "0", "20", HELP), ("Label", "24", "8", TYPE_LABEL), ("DropList", "33", "52", ""),
                                ("Label", "48", "8", YEAR_LABEL), ("DropList", "57", "70", "")])
        self.assertNotIn("NSD_CreateText", body)
