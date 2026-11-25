"""SL-4c pin: the page order and the texts the operator sees on the elevation and no-admin pages. Offline; a change must be deliberate."""
import re
import unittest
from pathlib import Path

NSIS = Path(__file__).resolve().parent.parent / "installer" / "nsis"

PAGES = [("Page_mode_Pre", "Page_mode_Leave"), ("Page_folders", "Page_folders_Leave"), ("Page_forge", "Page_forge_Leave"), ("Page_network", "Page_network_Leave"), ("Page_labview", "Page_labview_Leave"), ("Page_image", "Page_image_Leave"),
         ("Page_licences", "Page_licences_Leave"), ("Page_secrets", "Page_secrets_Leave"), ("Page_noadmin", None), ("Page_elevation", "Page_elevation_Leave")]

ELEVATION_TEXTS = [
    ("Label", "The next step needs administrator rights. It changes exactly these things and nothing else:"),
    ("Label", "Service: EcosystemRunner, running under the virtual service account NT SERVICE\\EcosystemRunner"),
    ("Label", "Folder: $MachineFolder (the machine's program-data location)"),
    ("Label", "Uninstall entry: one entry named EcosystemRunner"),
    ("Label", "Rights: create and start the service, write the folder, write the uninstall entry. Choose Next to see the Windows administrator prompt."),
]
NOADMIN_TEXTS = [
    ("Label", "The runner needs administrator rights, and this PC session does not have them. Only the per-user mode is offered."),
    ("RadioButton", "Local only (no forge)"),
]


def nsh_text():
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(NSIS.glob("*.nsh")))


def body(name):
    m = re.search(r"^Function %s\n(.*?)^FunctionEnd" % re.escape(name), nsh_text(), re.S | re.M)
    assert m, name
    return m.group(1)


def texts(name):
    return re.findall(r'\$\{NSD_Create(\w+)\}\s+\S+\s+\S+\s+\S+\s+\S+\s+"([^"]*)"', body(name))


class PagesTest(unittest.TestCase):
    def test_page_order_is_pinned(self):
        lines = [l.strip() for l in (NSIS / "main.nsi").read_text(encoding="utf-8").splitlines() if l.startswith("Page ")]
        want = ["Page custom " + a + (" " + b if b else "") for a, b in PAGES] + ["Page instfiles"]
        self.assertEqual(lines, want)

    def test_every_page_and_leave_function_exists(self):
        text = nsh_text()
        for show, leave in PAGES:
            for fn in (show, leave):
                if fn:
                    self.assertRegex(text, r"(?m)^Function %s\s*$" % fn)

    def test_elevation_page_texts_are_pinned(self):
        self.assertEqual(texts("Page_elevation"), ELEVATION_TEXTS)

    def test_noadmin_page_texts_are_pinned(self):
        self.assertEqual(texts("Page_noadmin"), NOADMIN_TEXTS)

    def test_no_other_control_text_is_set_on_these_pages(self):
        for fn in ("Page_elevation", "Page_noadmin"):
            self.assertNotRegex(body(fn), r"GetDlgItem|SendMessage|NSD_SetText|NSD_CreateButton|NSD_CreateLink", fn)


if __name__ == "__main__":
    unittest.main()
