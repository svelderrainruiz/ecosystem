"""DOC-1 regressions: execute the installer text with scripted Windows results."""
import json
import tempfile
import unittest
from pathlib import Path

from installer import diagnostics, log, trust
from tests.nsis_interp import ROOT, UpdateWorld, source_text


ROAMING = r"C:\Users\test\AppData\Roaming"
LOCAL = r"C:\Users\test\AppData\Local"
STORE = LOCAL + r"\EcosystemInstaller\signer.sha256"
LOG = ROOT + r"\steps.jsonl"


class AuditWorld(UpdateWorld):
    native_Install_Footprint = None
    native_LogStep = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.var.update(APPDATA=ROAMING, LOCALAPPDATA=LOCAL)
        self.labels = []

    def native_LogUtcNow(self):
        pass  # clock arithmetic is exercised in test_installer_logs

    def step(self, t, labels):
        op = t[0].lower()
        if op == "setshellvarcontext":
            machine = t[1] == "all"
            self.var.update(APPDATA=r"C:\ProgramData" if machine else ROAMING,
                            LOCALAPPDATA=r"C:\ProgramData" if machine else LOCAL)
        elif op == "readregstr":
            self.set(t[1], "UTC")
        elif op == "fileopen" and t[3] == "a":
            path = self.expand(t[2])
            if not self.exists(path.rsplit("\\", 1)[0]):
                self.errors = True
            else:
                self.fileopen(t[1], path, "w")
                self.fh[self.expand(t[1])]["buf"].append(self.files.get(path, ""))
        elif op == "fileseek":
            assert t[2:] == ["0", "END"]
        else:
            if op == "${nsd_createlabel}":
                self.labels.append(self.expand(t[-1]))
            return super().step(t, labels)


class DocFix(unittest.TestCase):
    def test_a_elevation_names_the_actual_install_folder(self):
        w = AuditWorld(admin=False, silent=False)
        w.call(".onInit")
        w.call("Page_elevation")
        w.admin = True
        w.call("Install_Footprint")
        [target] = [p.rsplit("\\", 1)[0] for p in w.files if p.endswith("\\uninstall.exe")]
        [label] = [s for s in w.labels if s.startswith("Folder: ")]
        self.assertEqual(label.split(" (")[0], "Folder: " + target)

    def test_b_refusal_never_creates_and_appends_only_to_existing_machine_log(self):
        user_log = ROAMING + r"\EcosystemRunner\steps.jsonl"
        for cmd, rc in (("/MODE=bad", 30), ("/BOGUS", 31), ("/IMAGE_VARIANT=windows /IMAGE_YEAR=2024", 35),
                        ("/IMAGE_VARIANT=windows /IMAGE_YEAR=2024", 36)):
            for existing in ({}, {ROOT + r"\.dir": ""}, {LOG: '{"old":1}\n'}):
                with self.subTest(rc=rc, existing=list(existing)):
                    w = AuditWorld(files={user_log: "untouched", **existing}, admin=False)
                    if rc == 35:  # supply the image lookup of a pinned build
                        w.native_Image_Known = lambda: w.set("$R9", "")
                    before = dict(w.files)
                    w.var["CMDLINE"] += " " + cmd
                    self.assertEqual(w.run(".onInit"), rc)
                    if LOG in existing:
                        self.assertEqual([json.loads(s)["exit_code"] for s in w.files[LOG].splitlines()[1:]], [rc])
                        self.assertTrue(w.files[LOG].startswith(existing[LOG]))
                        before[LOG] = w.files[LOG]
                    self.assertEqual(w.files, before)

    def test_b_footprint_rejects_redirected_alias(self):
        from installer import footprint
        for filename, old, new in (
                ("log.nsh", "SetShellVarContext all", "SetShellVarContext current"),
                ("log.nsh", r"$MachineFolder\steps.jsonl", r"$TEMP\steps.jsonl"),
                ("main.nsi", "  Call TrustCheck", "  Pop $LogPath\n  Call TrustCheck")):
            with self.subTest(filename=filename, new=new):
                src = source_text()
                self.assertEqual(src[filename].count(old), 1)
                src[filename] = src[filename].replace(old, new)
                self.assertTrue(footprint.check_source(src))

    def test_c_exec_results_round_trip_through_both_writers_and_diagnostics(self):
        w = AuditWorld(files={LOG: ""}, admin=False, silent=False)
        w.call(".onInit")
        w.var["APPDATA"] = r"C:\ProgramData"  # isolate serialization from the context regression
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steps.jsonl"
            model = log.StepLog(path)
            for code in ("error", "timeout", "7", "0", "-1"):
                w.stack.extend(["test", "command", code])
                w.call("LogStep")
                entry = json.loads(w.files[LOG].splitlines()[-1])
                projected = {k: entry[k] for k in ("exit_code", "exec_error") if k in entry}
                expected = ({"exit_code": None, "exec_error": code} if code in ("timeout", "error")
                            else {"exit_code": int(code)})
                self.assertEqual(projected, expected)
                model.record("test", "command", code)
                recorded = json.loads(path.read_text().splitlines()[-1])
                self.assertEqual({k: recorded[k] for k in expected}, expected)
                summary = diagnostics.collect(tmp)
                self.assertEqual(summary["exit_codes"], {"test": expected["exit_code"]})
                if "exec_error" in expected:
                    self.assertEqual(summary["error_codes"], {"test": code})
            path.write_text(w.files[LOG])  # NSIS records have no duration_ms
            self.assertEqual(diagnostics.collect(tmp)["exit_codes"], {"test": -1})

    def test_d_first_run_stores_canonical_and_legacy_uppercase_still_matches(self):
        signer = "0123456789ABCDEF" * 4
        for stored, silent in ((None, False), (signer, True), (signer.lower(), True)):
            w = AuditWorld(silent=silent, admin=False, files={STORE: stored + "\n"} if stored else {})
            w.native_TrustCheck = None
            w.var["CMDLINE"] += " /SIGNER=" + (signer.lower() if stored == signer else signer)
            self.assertEqual(w.run(".onInit"), 38 if silent else None)
            self.assertEqual(w.var["TrustSigner"], trust.parse_fingerprint(signer))
            self.assertEqual(w.files[STORE], (stored or signer.lower()) + "\n")
            self.assertEqual(len(w.boxes), 0 if stored else 1)

    def test_signer_with_an_extra_hex_digit_is_not_a_valid_first_run(self):
        w = AuditWorld(silent=False, admin=False)
        w.native_TrustCheck = None
        w.var["CMDLINE"] += " /SIGNER=" + "0123456789ABCDEF" * 4 + "a"
        self.assertEqual(w.run(".onInit"), "abort")
        self.assertEqual(w.errorlevel, 3)
        self.assertNotIn(STORE, w.files)
