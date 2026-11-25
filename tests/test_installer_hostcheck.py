"""SL-3 host check: edition gate on recorded edition values, hostcheck.ps1 parse-only and in sync (INST-REQ-016, 017, 033)."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from installer import schema as S

PS1 = Path(__file__).resolve().parent.parent / "installer" / "hostcheck.ps1"
REFUSED = ["Microsoft Windows 10 Pro", "Microsoft Windows 11 Home", "Microsoft Windows 11 Education", "Microsoft Windows Server 2019 Standard",
           "Microsoft Windows 11 Enterprise LTSC", "Microsoft Windows 11 Enterprise 2024 LTSC", "Microsoft Windows 10 Enterprise LTSC 2021",
           "Microsoft Windows 11 Pro for Workstations", "Microsoft Windows Server 2022 LTSC", "Microsoft Windows Server 2025 Datacenter LTSC", "Microsoft Windows Server 2016 Datacenter", "Microsoft Windows Server 20225", "", None]
ACCEPTED = ["Microsoft Windows 11 Pro", "Microsoft Windows 11 Enterprise", "Microsoft Windows Server 2022 Standard",
            "Microsoft Windows Server 2022 Datacenter", "Microsoft Windows Server 2025 Datacenter", "microsoft  windows 11 pro"]


class EditionTests(unittest.TestCase):
    def setUp(self):
        self.schema = S.load_schema()

    def test_unlisted_edition_is_refused_with_reason(self):
        """INST-REQ-016, 017: Home, Education, LTSC, Server 2019 and others are refused with the edition and a plain reason."""
        for caption in REFUSED:
            with self.assertRaises(S.EditionRefused, msg=caption) as cm:
                S.check_edition(self.schema, caption)
            text = str(cm.exception)
            self.assertIn("is not supported", text)
            self.assertIn("Windows 11 Pro", text)
            if caption:
                self.assertIn(re.sub(r"^Microsoft ", "", caption), text)

    def test_listed_editions_are_accepted(self):
        for caption in ACCEPTED:
            self.assertTrue(S.check_edition(self.schema, caption), caption)

    def test_accepted_list_is_exactly_the_four_editions(self):
        t = self.schema["editions"]
        self.assertEqual(t["accepted_exact"] + t["accepted_prefix"],
                         ["Windows 11 Pro", "Windows 11 Enterprise", "Windows Server 2022", "Windows Server 2025"])


class HostcheckScriptTests(unittest.TestCase):
    def setUp(self):
        self.src = PS1.read_text(encoding="utf-8")

    def test_script_lists_equal_the_schema(self):
        """INST-REQ-017: hostcheck.ps1 carries the same accepted list and exit code as schema.json."""
        t = S.load_schema()
        for var, key in (("AcceptedExact", "accepted_exact"), ("AcceptedPrefix", "accepted_prefix")):
            m = re.search(r"\$%s = @\((.*?)\)" % var, self.src)
            self.assertEqual(re.findall(r"'([^']+)'", m.group(1)), t["editions"][key])
        self.assertIn("$ExitRefused = %d" % t["exit_codes"]["edition-refused"], self.src)
        self.assertIn("ltsc", self.src.lower())
        self.assertRegex(self.src, r"catch \{[^}]*exit \$ExitRefused")  # a failed edition read is the typed refusal

    def test_check_changes_nothing_and_needs_no_rights_or_secrets(self):
        """INST-REQ-033: only reads; no write, registry, service, elevation or secret cmdlet."""
        banned = r"Set-(Content|Item|Service)|New-Item|Remove-|Out-File|Add-Content|Set-Content|Start-Process|RunAs|Invoke-WebRequest|Invoke-RestMethod|\breg\b|sc\.exe|token|password|secret"
        body = "\n".join(l for l in self.src.splitlines() if not l.lstrip().startswith("#"))
        self.assertIsNone(re.search(banned, body, re.I))
        self.assertIn("Get-CimInstance", body)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
    def test_script_parses(self):
        cmd = "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e);if($e){$e|%%{$_.Message};exit 1}" % PS1
        r = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
