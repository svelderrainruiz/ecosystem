"""Guest proof harness (ecosystem-control#64): pack.py command shape and the driver's static properties."""
import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer import build
from installer.guest import pack

ROOT = Path(__file__).resolve().parent.parent
GUEST = ROOT / "installer" / "guest"
PINS = build.load_pins()


class PackTests(unittest.TestCase):
    def test_harness_command_uses_pinned_flags_and_outfile(self):
        cmd = pack.harness_command("makensis", PINS, "a.nsi", "/o/x.exe")
        self.assertEqual(cmd[0], "makensis")
        self.assertIn("-XSetDateSave off", cmd)
        self.assertIn("-XOutFile /o/x.exe", cmd)
        self.assertEqual(cmd[-1], "a.nsi")

    def test_harness_command_puts_the_defines_before_the_script_commands_and_none_by_default(self):
        plain = pack.harness_command("makensis", PINS, "a.nsi", "/o/x.exe")
        self.assertFalse([c for c in plain if c.startswith("-D")])
        cmd = pack.harness_command("makensis", PINS, "a.nsi", "/o/x.exe", ("RUNNER_PAYLOAD=/p/r.bin", "OUTFILE=/o/x.exe"))
        defines = [i for i, c in enumerate(cmd) if c.startswith("-D")]
        script = [i for i, c in enumerate(cmd) if c.startswith("-X")]
        self.assertEqual([cmd[i] for i in defines], ["-DRUNNER_PAYLOAD=/p/r.bin", "-DOUTFILE=/o/x.exe"])
        self.assertLess(max(defines), min(script))
        self.assertEqual(cmd[:1] + cmd[1:1 + len(PINS["compile"]["flags"])], ["makensis", *PINS["compile"]["flags"]])
        self.assertEqual(cmd[-2:], ["-XOutFile /o/x.exe", "a.nsi"])

    def test_pack_writes_base64_text_only(self):
        def fake_run(cmd):
            out = [c[len("-XOutFile "):] for c in cmd if c.startswith("-XOutFile ")]
            target = Path(out[0]) if out else Path(cmd[-1]).parent / "installer.exe"
            target.write_bytes(b"MZ" + cmd[-1].encode())
            return 0, ""
        with tempfile.TemporaryDirectory() as d:
            digests = pack.pack(d, "makensis", fake_run)
            self.assertEqual(sorted(digests), ["installer", "installer-update", "local-harness", "log-harness", "probe-p1", "probe-p2", "probe-p3", "probe-p4", "probe-p5", "probe-p6", "uninstall-harness", "update-payload"])
            for f in Path(d).iterdir():
                self.assertTrue(f.name.endswith(".b64"))
                base64.b64decode(f.read_text("ascii").strip(), validate=True)

    def test_the_update_installer_is_the_main_script_built_with_a_stand_in_program_file_and_its_own_output_name(self):
        calls = []

        def fake_run(cmd):
            calls.append(cmd)
            out = [c[len("-XOutFile "):] for c in cmd if c.startswith("-XOutFile ")]
            Path(out[0]).write_bytes(b"MZ" + cmd[-1].encode())
            return 0, ""
        with tempfile.TemporaryDirectory() as d:
            digests = pack.pack(d, "makensis", fake_run)
            payload = base64.b64decode((Path(d) / "update-payload.bin.b64").read_text("ascii").strip(), validate=True)
            self.assertEqual(payload, pack.UPDATE_PAYLOAD)
            self.assertEqual(digests["update-payload"], hashlib.sha256(pack.UPDATE_PAYLOAD).hexdigest())
            self.assertTrue((Path(d) / "installer-update.exe.b64").is_file())
        plain, update = [c for c in calls if Path(c[-1]).name == "main.nsi"]
        self.assertFalse([x for x in plain if x.startswith("-D")])
        defs = {x[2:].split("=", 1)[0]: x[2:].split("=", 1)[1] for x in update if x.startswith("-D")}
        self.assertEqual(sorted(defs), ["OUTFILE", "RUNNER_PAYLOAD"])
        self.assertTrue(defs["OUTFILE"].endswith("installer-update.exe"))
        self.assertTrue(defs["RUNNER_PAYLOAD"].endswith("update-payload.bin"))
        self.assertIn("-XOutFile " + defs["OUTFILE"], update)
        self.assertEqual(len(calls), 11)
        self.assertEqual(pack.UPDATE_PAYLOAD.decode("ascii").count("\n"), 1)
        for stale in (b"OLD-RUNNER-g7d", b"DECOY-RUNNER-g7d", b"STALE-RUNNER-g7d"):
            self.assertNotIn(stale, pack.UPDATE_PAYLOAD)

    def test_main_refuses_without_makensis(self):
        self.assertEqual(pack.main(["x", "--makensis", ""]), 2)

    def test_compile_failure_is_typed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(build.CompileError):
                pack.pack(d, "makensis", lambda cmd: (1, "boom"))


class DriverTests(unittest.TestCase):
    def test_every_harness_has_a_source_and_no_binary_is_tracked(self):
        for name in pack.HARNESSES:
            self.assertTrue((GUEST / f"{name}-harness.nsi").is_file())
        for name in pack.PROBES:
            self.assertTrue((GUEST / f"probe-{name}.nsi").is_file())
        tracked = subprocess.run(["git", "ls-files", "installer/guest"], cwd=ROOT, capture_output=True, text=True).stdout
        self.assertNotIn(".exe", tracked)
        self.assertNotIn(".b64", tracked)

    def test_driver_is_ascii_and_prints_no_secret(self):
        text = (GUEST / "guest-proof.ps1").read_text("utf-8")
        text.encode("ascii")
        self.assertNotIn("Write-Output $plain", text)
        self.assertNotIn("Write-Host $plain", text)

    def test_driver_reports_every_checklist_item(self):
        text = (GUEST / "guest-proof.ps1").read_text("utf-8")
        for item in ("SL-3", "SL-4a", "SL-4b", "SL-4c", "SL-5a", "SL-5b", "SL-5c", "SL-6a", "SL-6b", "SL-7a", "SL-7b", "SL-7c", "SL-7d"):
            self.assertIn(f"'{item}", text)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh absent")
    def test_driver_parses(self):
        cmd = ('$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile($env:G4_SCRIPT,[ref]$null,[ref]$e);'
               'exit $e.Count')
        r = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                           env={**os.environ, "G4_SCRIPT": str(GUEST / "guest-proof.ps1")})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
