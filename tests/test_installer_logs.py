"""SL-7 tests: step log, diagnostics zip, data boundary (INST-REQ-046..050, 060, 080, 085, 087)."""
import json
import re
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from installer import diagnostics, log
from tests.zone_database import requires_zone_database

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "installer"
URL = re.compile(r"https?://([A-Za-z0-9.\-$_]+)")
NET_IMPORT = re.compile(r"^\s*(?:import|from)\s+(urllib(?!\.parse)|socket|http|ftplib|smtplib|requests|ssl|xmlrpc)\b", re.M)
SECRET_TOKEN = "s3cr3t-T0KEN-value"
PLANTED = {
    "user": "alice_the_user",
    "host": "DESKTOP-HOSTNAME1",
    "tokenurl": "https://example.invalid/x?token=" + SECRET_TOKEN,
    "path": "C:\\Users\\alice_the_user\\Documents",
    "env": "%USERPROFILE%",
}


class FakeRun:
    def __init__(self, code, out, err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


class StepLogTests(unittest.TestCase):
    def test_step_log_has_command_exit_code_output(self):
        """INST-REQ-046: each step has command, exit code, output and timing."""
        with tempfile.TemporaryDirectory() as d:
            ticks = iter([10.0, 10.25])
            sl = log.StepLog(Path(d) / "steps.jsonl", now=lambda: datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc),
                             clock=lambda: next(ticks))
            sl.run("probe", ["tool", "--x"], runner=lambda *a, **k: FakeRun(3, "out", "err"))
            (e,) = sl.read()
        self.assertEqual((e["step"], e["command"], e["exit_code"], e["output"], e["duration_ms"]),
                         ("probe", "tool --x", 3, "outerr", 250))

    @requires_zone_database("Europe/Amsterdam")
    def test_machine_logs_are_utc_iso8601_and_display_is_hhmm(self):
        """INST-REQ-047, 053, 054: machine time UTC ISO 8601; display plain HH:MM, never Z or UTC."""
        with tempfile.TemporaryDirectory() as d:
            sl = log.StepLog(Path(d) / "s.jsonl", now=lambda: datetime(2026, 7, 1, 10, 5, tzinfo=timezone.utc))
            e = sl.record("a", "c", 0)
        self.assertEqual(e["started"], "2026-07-01T10:05:00+00:00")
        shown = log.display_hhmm(e["started"], "Europe/Amsterdam")
        self.assertEqual(shown, "12:05")
        self.assertRegex(shown, r"^\d\d:\d\d$")
        self.assertNotRegex(shown, "[A-Za-z]")
        with self.assertRaises(log.LogError):
            log.utc_iso(datetime(2026, 1, 1))
        with self.assertRaises(log.LogError):
            log.display_hhmm("2026-07-01T10:05:00", "Europe/Amsterdam")

    def test_redaction_probes(self):
        """Reviewer probes: every secret shape is gone from command and output."""
        probes = [
            ("Authorization: Bearer abc123SECRET", "abc123SECRET"),
            ("--password hunter2", "hunter2"),
            ("secret: 'a b' next", "b'"),
            ("API_KEY=zzzval", "zzzval"),
            ("licence ABCD-1234-EFGH-5678 end", "ABCD-1234"),
            ("PASSWORD%3Dxpassval", "xpassval"),
            ("db_password=pw1 and x-api-key: k2", "pw1"),
            ("Authorization: Basic dXNlcjpwdw==", "dXNlcjpwdw"),
            ('token="two words"', "words"),
            ("pass%77ord=zq9", "zq9"),
            ("pwd=abc9x", "abc9x"),
            ("key AB12-CD34-EF56 end", "AB12-CD34"),
        ]
        for text, secret in probes:
            self.assertNotIn(secret, log.redact(text), text)
        self.assertIn("[redacted]", log.redact("--password hunter2"))
        self.assertEqual(log.redact("plain step ok"), "plain step ok")

    def test_non_utc_input_is_stored_as_utc(self):
        """INST-REQ-047/054: an aware time in another zone is written in UTC."""
        from datetime import timedelta
        local = datetime(2026, 7, 1, 12, 5, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(log.utc_iso(local), "2026-07-01T10:05:00+00:00")

    def test_utc_from_local_bias_arithmetic(self):
        """INST-REQ-047: the integer arithmetic of log.nsh (local + ActiveTimeBias) equals datetime, with rollovers."""
        from datetime import timedelta
        cases = [
            ((2026, 7, 1, 12, 5, 9), -120),    # CEST: negative bias (UTC = local - 2h)
            ((2026, 1, 15, 8, 30, 0), -60),    # CET winter
            ((2026, 3, 29, 3, 0, 0), -120),    # just after the spring change
            ((2026, 10, 25, 2, 30, 0), -60),   # after the autumn change
            ((2026, 7, 1, 20, 0, 0), 420),     # US Mountain daylight: positive bias, day rollover
            ((2026, 12, 31, 20, 0, 0), 300),   # year rollover
            ((2028, 2, 28, 22, 0, 0), 180),    # leap day
            ((2026, 3, 1, 0, 30, 0), -60),     # back across the month end into February
            ((2026, 1, 1, 0, 10, 0), -60),     # back across the year end
            ((2026, 2, 28, 23, 59, 59), 1),
        ]
        for (y, mo, d, h, mi, s), bias in cases:
            want = (datetime(y, mo, d, h, mi, s) + timedelta(minutes=bias)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            self.assertEqual(log.utc_from_local(y, mo, d, h, mi, s, bias), want, (y, mo, d, h, mi, bias))

    def run_logutcnow(self, local, bias):
        """Executes the real LogUtcNow body of log.nsh in a tiny interpreter of the NSIS subset it uses."""
        body = (INSTALLER / "nsis" / "log.nsh").read_text().split("Function LogUtcNow")[1].split("FunctionEnd")[0]
        lines = [l.strip() for l in body.splitlines() if l.strip() and not l.strip().startswith(";")]
        labels = {l[:-1]: i for i, l in enumerate(lines) if re.fullmatch(r"\w+:", l)}
        v = {}
        def ref(t):
            if not t.startswith("$"):
                return int(t)
            if isinstance(v[t[1:]], str) and len(v[t[1:]]) > 1 and v[t[1:]].startswith("0"):
                self.fail("NSIS would read a zero-padded number as octal: " + t)
            return int(v[t[1:]])
        i = 0
        while i < len(lines):
            t = lines[i].split()
            i += 1
            if not t or t[0].endswith(":"):
                continue
            if t[0] == "${GetTime}":
                for name, val in zip(t[3:], local):
                    v[name[1:]] = val
            elif t[0] == "!insertmacro":
                var = t[2][1:]
                v[var] = v[var][1:] if v[var][0] == "0" else v[var]
            elif t[0] == "ReadRegDWORD":
                v[t[1][1:]] = bias
            elif t[0] == "StrCpy":
                v[t[1][1:]] = v[t[2][1:]]
            elif t[0] == "IntOp":
                a, b = ref(t[2]), ref(t[4])
                r = {"+": a + b, "-": a - b, "*": a * b, "/": int(a / b) if t[3] == "/" else 0,
                     "%": a % b if t[3] == "%" else 0}[t[3]]
                v[t[1][1:]] = r
            elif t[0] == "IntCmp":
                a, b = ref(t[1]), ref(t[2])
                i = labels[t[3] if a == b else t[4] if a < b else t[5]]
            elif t[0] == "Goto":
                i = labels[t[1]]
            elif t[0] == "IntFmt":
                v[t[1][1:]] = "%02d" % int(v[t[3][1:]])
            else:
                self.fail("unsupported NSIS line: " + lines[i - 1])
        return f"{int(v['LogY']):04d}-{v['LogMo']}-{v['LogD']}T{v['LogH']}:{v['LogMi']}:{v['LogS']}+00:00"

    def test_nsis_arithmetic_matches_the_model(self):
        """INST-REQ-047: the NSIS LogUtcNow body, executed, equals utc_from_local (leading-zero values like 08 included)."""
        cases = [((2026, 7, 1, 12, 5, 9), -120), ((2026, 1, 8, 8, 9, 8), -60), ((2026, 12, 31, 20, 0, 0), 300),
                 ((2028, 2, 29, 22, 0, 0), 180), ((2026, 3, 1, 0, 30, 0), -60), ((2026, 1, 1, 0, 10, 0), -60),
                 ((2026, 2, 28, 23, 59, 59), 1), ((2026, 10, 25, 2, 30, 0), -60), ((2026, 9, 5, 9, 0, 7), 420),
                 ((2100, 3, 1, 0, 30, 0), -60), ((2100, 2, 28, 23, 0, 0), 120)]
        for (y, mo, d, h, mi, s), bias in cases:
            local = ("%02d" % d, "%02d" % mo, str(y), "1", "%02d" % h, "%02d" % mi, "%02d" % s)
            self.assertEqual(self.run_logutcnow(local, bias), log.utc_from_local(y, mo, d, h, mi, s, bias), (y, mo, d, bias))

    def test_nsis_log_reads_only_the_allow_listed_bias_and_no_plugin(self):
        """The bias read is the one allow-list line added for SL-7; log.nsh uses no plugin or exec; the log is inside the footprint."""
        nsh = (INSTALLER / "nsis" / "log.nsh").read_text()
        self.assertIn("ActiveTimeBias", nsh)
        self.assertNotIn("System::", nsh)
        self.assertNotIn("nsExec", nsh)
        self.assertIn('StrCpy $MachineFolder "$APPDATA\\EcosystemRunner"', nsh)
        self.assertIn('StrCpy $LogPath "$MachineFolder\\steps.jsonl"', nsh)
        self.assertIn("TimeZoneInformation\\ActiveTimeBias", (INSTALLER / "allowlist-read.txt").read_text())

    @requires_zone_database("Europe/Amsterdam")
    def test_display_converts_across_daylight_saving(self):
        """INST-REQ-053/054: same UTC hour shows +1h before and +2h after the change; stored stays UTC."""
        before = log.display_hhmm("2026-03-28T12:00:00+00:00", "Europe/Amsterdam")
        after = log.display_hhmm("2026-03-29T12:00:00+00:00", "Europe/Amsterdam")
        self.assertEqual((before, after), ("13:00", "14:00"))

    def test_secrets_never_logged(self):
        """No secret in the log (brief rule)."""
        with tempfile.TemporaryDirectory() as d:
            sl = log.StepLog(Path(d) / "s.jsonl")
            sl.record("a", "tool --password=hunter2 https://u:pw@h/x", 0, "token: abc123 ok")
            raw = (Path(d) / "s.jsonl").read_text()
        for bad in ("hunter2", "pw@", "abc123"):
            self.assertNotIn(bad, raw)

    def test_nsis_log_include_and_unicode_free_format(self):
        """INST-REQ-046/047: log.nsh exists, is included once, writes an UTC +00:00 time."""
        self.assertEqual((INSTALLER / "nsis" / "main.nsi").read_text().count('!include "log.nsh"'), 1)
        nsh = (INSTALLER / "nsis" / "log.nsh").read_text()
        self.assertIn("GetTime", nsh)
        self.assertIn("+00:00", nsh)
        self.assertIn("exit_code", nsh)


class DiagnosticsTests(unittest.TestCase):
    def make_install(self, d):
        root = Path(d) / "install"
        (root / "data").mkdir(parents=True)
        (root / "data" / "blob.bin").write_bytes(b"x" * 100)
        (root / "data" / "secret.txt").write_text("FILE-CONTENT-" + SECRET_TOKEN)
        (root / PLANTED["user"]).mkdir()
        (root / "state.json").write_text(json.dumps({
            "version": "1.2.3", "windows_edition": "Windows 11 Pro", "service_state": "running",
            "user_name": PLANTED["user"], "host_name": PLANTED["host"], "token_url": PLANTED["tokenurl"],
            "path": PLANTED["path"], "environment": {"X": PLANTED["env"]}}))
        sl = log.StepLog(root / "steps.jsonl")
        sl.record("install", "tool " + PLANTED["tokenurl"], 0, "OUT " + PLANTED["path"], duration_ms=40)
        entries = [json.loads(l) for l in (root / "steps.jsonl").read_text().splitlines()]
        entries[0]["error_code"] = "E-" + PLANTED["env"]
        (root / "steps.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        return root

    def test_diagnostics_zip_contains_only_allow_listed_items(self):
        """INST-REQ-048, 049, 085: only allow-listed fields; every planted class absent; location shown."""
        with tempfile.TemporaryDirectory() as d:
            root = self.make_install(d)
            out = diagnostics.write_zip(root, stamp="t1", deny=[PLANTED["user"], PLANTED["host"]])
            with zipfile.ZipFile(out) as z:
                self.assertEqual(z.namelist(), ["diagnostics.json"])
                raw = z.read("diagnostics.json").decode()
            data = json.loads(raw)
            msg = diagnostics.location_message(out)
        self.assertTrue(set(data) <= set(diagnostics.load_allowlist()))
        self.assertEqual(data["version"], "1.2.3")
        self.assertEqual(data["folder_sizes"]["data"], 100 + len("FILE-CONTENT-" + SECRET_TOKEN))
        self.assertEqual(data["exit_codes"], {"install": 0})
        for planted in list(PLANTED.values()) + [SECRET_TOKEN, "FILE-CONTENT", "OUT ", str(root), "Documents"]:
            self.assertNotIn(planted, raw)
        self.assertIn(str(out), msg)
        self.assertEqual(data["error_codes"], {"install": "[redacted]"})

    def test_symlinked_folder_is_not_followed(self):
        """INST-REQ-049: a link out of the install folder adds neither name nor size."""
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            root = self.make_install(d)
            (Path(outside) / "big.bin").write_bytes(b"y" * 500)
            try:
                (root / "linked").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("no symlinks")
            self.assertNotIn("linked", diagnostics.collect(root)["folder_sizes"])

    def test_allowlist_is_the_single_source(self):
        """INST-REQ-048: a field removed from the file disappears from the zip; the file names the review rule."""
        with tempfile.TemporaryDirectory() as d:
            root = self.make_install(d)
            data = diagnostics.collect(root, allowlist=["version"])
        self.assertEqual(list(data), ["version"])
        self.assertIn("operator", (INSTALLER / "diag-allowlist.txt").read_text())
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.txt").write_text("# only comments\n")
            with self.assertRaises(diagnostics.AllowlistError):
                diagnostics.load_allowlist(Path(d) / "a.txt")

    def test_malformed_step_log_is_typed(self):
        """A step without its keys or with a bad exit code is a typed refusal, not a traceback."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "steps.jsonl").write_text('{"step": "a", "exit_code": "x", "duration_ms": 1}\n')
            with self.assertRaises(diagnostics.DiagnosticsError):
                diagnostics.collect(d)
            (Path(d) / "steps.jsonl").write_text('{"step": "a"}\n')
            with self.assertRaises(diagnostics.DiagnosticsError):
                diagnostics.collect(d)
            (Path(d) / "steps.jsonl").write_text('not json\n')
            with self.assertRaises(diagnostics.DiagnosticsError):
                diagnostics.collect(d)

    def test_missing_install_folder_is_typed(self):
        with self.assertRaises(diagnostics.DiagnosticsError):
            diagnostics.collect("/nonexistent-install-folder-x")


class DataBoundaryTests(unittest.TestCase):
    def policy(self):
        return json.loads((INSTALLER / "netpolicy.json").read_text())

    def sources(self):
        for p in sorted(INSTALLER.rglob("*")):
            if p.is_file() and p.suffix in {".py", ".nsh", ".nsi", ".ps1", ".json"} and p.name != "netpolicy.json":
                yield p

    def test_only_pinned_network_destinations_and_no_upload(self):
        """INST-REQ-050, 060, 080, 087: URLs only to policy hosts; no forge of ours; no network code outside build.py."""
        pol = self.policy()
        self.assertIs(pol["upload"], False)
        self.assertEqual({a["id"] for a in pol["allowed"]}, {"nsis-source", "user-forge", "vendor-registry"})
        allowed = {a["host"] for a in pol["allowed"]}
        for p in self.sources():
            text = p.read_text(encoding="utf-8")
            for host in URL.findall(text):
                self.assertIn(host, allowed, f"{p.name}: destination not in the policy: {host}")
                for bad in pol["forbidden_forge_names"]:
                    self.assertFalse(host.lower().endswith(bad.lower()), f"{p.name}: forge of ours: {host}")
            if p.suffix == ".py" and p.name != "build.py":
                self.assertIsNone(NET_IMPORT.search(text), f"{p.name}: network module imported")

    def test_diagnostics_module_has_no_network_code(self):
        """INST-REQ-050: diagnostics.py and log.py import nothing that can reach a network."""
        for name in ("diagnostics.py", "log.py"):
            self.assertIsNone(NET_IMPORT.search((INSTALLER / name).read_text()), name)
        self.assertNotIn("subprocess", (INSTALLER / "diagnostics.py").read_text())

    def test_policy_rejects_a_planted_forge_destination(self):
        """The scan itself works: a forge URL is not in the allowed hosts."""
        allowed = {a["host"] for a in self.policy()["allowed"]}
        self.assertNotIn("github.com", allowed)
        self.assertTrue(any("github.com".endswith(b) for b in self.policy()["forbidden_forge_names"]))


if __name__ == "__main__":
    unittest.main()
