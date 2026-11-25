"""ENGINE-1 (#159): before the pull, Image_Pull asks the engine which container mode it runs ("info --format {{.OSType}}", nsExec::ExecToStack)
and refuses the pull, with exit 46 and a box that names both modes, when that is not the chosen container type. A read that fails falls through."""
import re
import unittest

from tests.test_installer_sl16b import DESKTOP, NSIS, RECORD, func, pinned_schema, ready, with_engine, world

PROBE = [DESKTOP, "info", "--format", "{{.OSType}}"]
PROBE_TEXT = "Checking which container type Docker runs."
PULL_TEXT = "Pulling the NI docker image. This can take a long time; Cancel waits until it ends."


def box(found, wanted):
    return ("MB_OK|MB_ICONEXCLAMATION Docker is running %s containers, but the NI docker image needs %s containers. Switch Docker to %s containers"
            " and run the installer again to repair. /SD IDOK" % (found, wanted, wanted))


def pull(variant, *answers, codes=None):
    w = with_engine(ready(world(schema=pinned_schema(), stack_answers=list(answers), exec_codes=codes), variant=variant))
    w.files[RECORD] = "{}"
    return w, w.run("Image_Pull")


class Mode(unittest.TestCase):
    def assertPulled(self, w, code, why):
        self.assertEqual((code, w.stack_execs, [x[:2] for x in w.execs]), (None, [PROBE], [[DESKTOP, "pull"]]), why)
        self.assertEqual((w.boxes, w.log), ([], []), why)
        self.assertEqual(w.details, [PROBE_TEXT, PULL_TEXT], why)

    def test_a_mismatch_skips_the_pull_names_both_modes_logs_one_step_and_exits_46(self):
        for variant, other in (("linux", "windows"), ("windows", "linux")):
            w, code = pull(variant, (0, other + "\n"))
            self.assertEqual((code, w.stack_execs, w.execs, w.details), (46, [PROBE], [], [PROBE_TEXT]), variant)
            self.assertEqual(w.boxes, [box(other, variant)], variant)
            self.assertEqual(w.log, [("image-engine-mode", "engine", "46")], variant)

    def test_a_match_pulls(self):
        for variant, out in (("linux", "linux\n"), ("windows", "windows\r\n"), ("linux", "linux")):
            w, code = pull(variant, (0, out))
            self.assertPulled(w, code, (variant, out))

    def test_an_info_failure_falls_through_to_the_pull(self):
        """A non-zero exit, nsExec's "error" (also with nothing scripted) and "timeout" all keep today's behaviour, even when the text names the
        other mode; a pull that then fails still reports its own failure."""
        for answer in ((1, "windows\n"), ("1", "error during connect"), ("error", ""), ("timeout", "windows")):
            w, code = pull("linux", answer)
            self.assertPulled(w, code, answer)
        w, code = pull("linux")
        self.assertPulled(w, code, "nothing scripted")
        w, code = pull("linux", ("error", ""), codes=[1])
        self.assertEqual((code, w.log, w.stack_execs), (46, [("image-pull", "pull", "46")], [PROBE]))
        self.assertEqual(w.details, [PROBE_TEXT, PULL_TEXT])

    def test_blanks_cr_lf_and_upper_case_count_as_a_match(self):
        for variant, out in (("linux", "Linux\r\n"), ("windows", "  WINDOWS \r\n"), ("linux", "\r\nlinux \n\n")):
            w, code = pull(variant, (0, out))
            self.assertPulled(w, code, (variant, out))

    def test_the_found_word_in_the_box_is_trimmed_and_lower_case(self):
        w, code = pull("linux", (0, " Windows\r\n"))
        self.assertEqual((code, w.boxes), (46, [box("windows", "linux")]))

    def test_every_engine_call_has_a_constant_detail_line_directly_before_it(self):
        lines = func((NSIS / "image.nsh").read_text(encoding="utf-8"), "Image_Pull").splitlines()
        calls = [i for i, line in enumerate(lines) if re.match(r"\s*nsExec::", line, re.I)]
        self.assertEqual(len(calls), 2)
        for i, text in zip(calls, (PROBE_TEXT, PULL_TEXT)):
            self.assertGreater(i, 0)
            self.assertEqual(lines[i - 1].strip(), 'DetailPrint "%s"' % text)
            self.assertNotIn("$", lines[i - 1])


if __name__ == "__main__":
    unittest.main()
