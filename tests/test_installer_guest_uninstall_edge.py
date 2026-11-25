"""CTR-6 (ecosystem-control#227): the uninstall-edge container case. uninstall-edge.ps1 ports the ten SL-6c rows that CHECKLIST.md classifies
container-provable from guest-proof.ps1 (same steps, same pass conditions) and runs them against the VM kit's real installer.exe. The static
tests tie the port to its source and to the container lane; the pwsh tests run its real verdict and SID functions; the container run is
the proof."""
import hashlib
import re
import tempfile
import unittest
from pathlib import Path

from installer import winsys
from installer.guest import container
from tests.guest_pwsh import requires_pwsh, run_functions

ROOT = Path(__file__).resolve().parent.parent
GUEST = ROOT / "installer" / "guest"
SCRIPT = GUEST / "uninstall-edge.ps1"
DRIVER = SCRIPT.read_text(encoding="ascii")
SOURCE = (GUEST / "guest-proof.ps1").read_text(encoding="ascii")
CHECKLIST = (GUEST / "CHECKLIST.md").read_text(encoding="utf-8")
PASS_LINE = "[verdict] c-uninstall-edge PASS"
ROWS = re.findall(r"^\| (SL-6c-[a-z0-9-]+) \| container-provable \|", CHECKLIST, re.M)
ROWS_IN_ORDER = re.findall(r"'([^']+)'", re.search(r"^\$rows = @\((.*?)\)$", DRIVER, re.M | re.S).group(1))
# both drivers: the row blocks start here, after the helper definitions
LEFTOVER = "# leftover: a file held open inside the folder (contract of PR 96 round UNINSTC: uninstall.exe goes last)"


def source_block():
    start = SOURCE.index(LEFTOVER)
    block = SOURCE[start:SOURCE.index("# ---- SL-13 pre-created folder", start)]
    # The standard-user gate is desktop-only: it is not ported, so it is cut from the comparison.
    gate = block.index("    if ($cred) {")
    gate_end = block.index("    } else { Res6c 'SL-6c-standard-user-gate' 'UNPROVEN' 'no standard account in this clone' }\n")
    return block[:gate] + block[gate_end + len("    } else { Res6c 'SL-6c-standard-user-gate' 'UNPROVEN' 'no standard account in this clone' }\n"):]


def driver_block(text):
    start = text.index(LEFTOVER)
    return text[start:text.index("$phase = 'done'", start)]


def normalize(line):
    """One statement as both drivers would run it: guest-proof's Run-Exe third argument ($null: no credential) and its Note file name dropped."""
    line = line.strip()
    line = re.sub(r"""(Run-Exe \$\w+ (?:'[^']*'|"[^"]*")) \$null""", r"\1", line)
    return re.sub(r"""Note 'sl6c\.txt' @\((".*")\)$""", r"Note \1", line)


def judging_lines(block, row):
    return [normalize(line) for line in block.splitlines()
            if f"'{row}'" in line and ("Ok6c" in line or f"'{row}' 'PASS'" in line or f"'{row}' 'FAIL'" in line)]


def steps(block):
    """The ordered actions of the SL-6c rows: installs, cleanups, uninstaller runs, waits, sleeps, holds and read-only marks."""
    pattern = re.compile(r"^(if \(Install-6c\) \{|Clean-6c|\$\w+ = (Run-Exe|Wait-6c) .*|Start-Sleep -Seconds \d+|\$fs = \[IO\.File\]::Open.*|"
                         r"Set-ItemProperty .*|Set-Content .*|\$runBefore = Svc-Running|\$\w+ = (State-6c|Exe-Kept|Names-6c))$")
    return [n for n in (normalize(line) for line in block.splitlines()) if pattern.match(n)]


def check_pass_line(text):
    """The driver's only PASS verdict is written verbatim and is the line VERDICT_RULES passes."""
    marker, passing = container.VERDICT_RULES["uninstall-edge.ps1"]
    written = re.findall(r"Log '(\[verdict\] c-uninstall-edge [^']*)'", text)
    assert written == [PASS_LINE], written
    assert re.match(marker, PASS_LINE) and re.fullmatch(passing, PASS_LINE), (marker, passing)
    assert container.judge("uninstall-edge.ps1", [PASS_LINE + "\r\n"]) == (True, "one passing verdict line")
    assert "Log ('[verdict] c-uninstall-edge FAIL ' + ($failed -join ','))" in text


def check_parity(text):
    """Every ported row is judged by the same condition text and reached by the same ordered steps as in guest-proof.ps1."""
    src, port = source_block(), driver_block(text)
    for row in ROWS:
        assert judging_lines(src, row) and judging_lines(port, row) == judging_lines(src, row), row
    edge = re.compile(r"^(\$holder = Start-Process .*|Start-Holder|Stop-Holder)$")
    assert [s for s in steps(port) if not edge.match(s)] == [s for s in steps(src) if not edge.match(s)]


def code(text):
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


FORBIDDEN = (
    r"\bmklink\b", r"-ItemType\s+['\"]?(Junction|SymbolicLink|HardLink)", r"Create(Symbolic|Hard)Link", r"\bfsutil\b",
    r"Invoke-WebRequest", r"Invoke-RestMethod", r"\b(iwr|irm|curl|wget|ping|nslookup|tracert)\b", r"Test-(Net)?Connection",
    r"Start-BitsTransfer", r"Net\.(WebClient|Http|Sockets|WebRequest)", r"https?://",
    r"\bwhoami\b", r"\$env:(USERNAME|USERDOMAIN|COMPUTERNAME)", r"NTAccount", r"\[Environment\]::(UserName|UserDomainName|MachineName)",
    r"GetCurrent\(\)\.Name", r"Get-Acl", r"\.Owner\b", r"\$_\.Exception\.Message",
)


def check_forbidden(text):
    hits = [p for p in FORBIDDEN if re.search(p, code(text), re.I)]
    assert not hits, hits


class UninstallEdgeDriver(unittest.TestCase):
    def test_checklist_lists_exactly_the_ten_ported_rows(self):
        self.assertEqual(len(ROWS), 10, ROWS)
        self.assertNotIn("SL-6c-standard-user-gate", ROWS)
        listed = re.search(r"^\$rows = @\((.*?)\)$", DRIVER, re.M | re.S).group(1)
        self.assertCountEqual(re.findall(r"'([^']+)'", listed), ROWS)
        for row in ROWS:
            self.assertRegex(DRIVER, r"(Res6c|Ok6c [^\n]*) '%s'" % re.escape(row))
            line = next(line for line in CHECKLIST.splitlines() if line.startswith(f"| {row} |"))
            self.assertRegex(line, r"`uninstall-edge\.ps1:[0-9]")
        self.assertNotIn("standard-user-gate", code(DRIVER))

    def test_the_pass_line_is_the_one_the_container_case_accepts(self):
        check_pass_line(DRIVER)
        self.assertNotIn("[end] c-uninstall-edge END", DRIVER)
        self.assertEqual(container.judge("uninstall-edge.ps1", ["[verdict] c-uninstall-edge FAIL SL-6c-clean-default"]),
                         (False, "verdict line did not pass"))
        self.assertEqual(container.judge("uninstall-edge.ps1", [PASS_LINE, PASS_LINE]), (False, "expected one verdict line, found 2"))

    def test_rows_keep_guest_proof_steps_and_pass_conditions(self):
        check_parity(DRIVER)
        for helper in ("Svc-Up", "Svc-Running", "State-6c", "Wait-6c", "Names-6c", "Exe-Kept", "Ok6c"):
            line = re.search(r"^function %s\b.*$" % helper, SOURCE, re.M).group(0)
            self.assertIn(line, DRIVER.splitlines(), helper)

    def test_install_is_guest_proof_install_with_the_python_service_step_ported(self):
        src = re.search(r"^function Install-6c \{\n(.*?)\n\}", SOURCE, re.M | re.S).group(1).splitlines()
        port = re.search(r"^function Install-6c \{\n(.*?)\n\}", DRIVER, re.M | re.S).group(1).splitlines()
        src = [normalize(line).replace("[void](Invoke-Proof 'sl6c.txt' @('install', 'EcosystemRunner', $footprintFolder, $stub))",
                                       "Install-Stub") for line in src]
        self.assertEqual([normalize(line) for line in port], src)
        stub = re.search(r"^function Install-Stub \{\n(.*?)\n\}", DRIVER, re.M | re.S).group(1)
        # winsys.create_argv, then install_service's sidtype, service_grant_argv and start, in that order
        order = ["'create EcosystemRunner binPath= \\\"' + $footprintFolder + '\\program\\runner.exe\\\" obj= \"NT SERVICE\\EcosystemRunner\" start= auto'",
                 "'sidtype EcosystemRunner unrestricted'", "/grant:r *' + (Service-Sid 'EcosystemRunner') + ':" + winsys.FOLDER_RIGHTS_SERVICE + "'",
                 "'start EcosystemRunner'"]
        self.assertEqual([stub.index(o) for o in order], sorted(stub.index(o) for o in order))
        self.assertEqual(winsys.create_argv("EcosystemRunner", "NT SERVICE\\EcosystemRunner", "C:\\ProgramData\\EcosystemRunner")[1:],
                         ["create", "EcosystemRunner", "binPath=", '"C:\\ProgramData\\EcosystemRunner\\program\\runner.exe"', "obj=",
                          "NT SERVICE\\EcosystemRunner", "start=", "auto"])

    def test_no_link_no_network_no_account_name(self):
        check_forbidden(DRIVER)
        self.assertNotIn("Start-Process", code(DRIVER))
        self.assertIn("Tool-Rc 'sc.exe'", DRIVER)
        self.assertIn("$psi.RedirectStandardOutput = $true", DRIVER)

    def test_refuses_product_state_it_did_not_make_and_cleans_only_after_the_gate(self):
        gate = "if ((Test-Path $footprintFolder) -or (Test-Path $uninstallKey) -or (Svc-Up)) {"
        self.assertIn(gate, DRIVER)
        self.assertLess(DRIVER.index(gate), DRIVER.index("Clean-6c\n        if (Install-6c)"))
        self.assertRegex(DRIVER, r"finally \{\n    Stop-Holder\n    if \(\$script:gateOk\) \{\n        Clean-6c\n")
        self.assertIn("if ($script:signerMade) { Remove-Item -LiteralPath $signerFile", DRIVER)

    def test_mutants_are_caught(self):
        mutants = {
            "pass line renamed": (check_pass_line, DRIVER.replace(f"Log '{PASS_LINE}'", "Log '[verdict] c-uninstall-edge PASSED'")),
            "exit 40 weakened": (check_parity, DRIVER.replace("(($rc2 -eq 40) -and $exe2", "(($rc2 -eq 0) -and $exe2")),
            "30 s wait dropped": (check_parity, DRIVER.replace("                Start-Sleep -Seconds 30\n", "", 1)),
            "a link added": (check_forbidden, DRIVER.replace("function Clean-6c {", "function Clean-6c {\n    cmd.exe /c mklink /J a b")),
            "account name logged": (check_forbidden, DRIVER.replace("user_sid=$(", "user=$env:USERNAME user_sid=$(")),
        }
        for name, (check, text) in mutants.items():
            with self.subTest(name):
                self.assertNotEqual(text, DRIVER)
                with self.assertRaises(AssertionError):
                    check(text)


class UninstallEdgeKit(unittest.TestCase):
    def test_kit_ships_the_driver_the_stub_source_and_only_the_vm_installer(self):
        self.assertEqual(container.case_files("uninstall-edge"), [
            ("uninstall-edge.ps1", "installer/guest/uninstall-edge.ps1", "repo"),
            ("installer.exe", "installer.exe", "vm-kit"),
            ("stub-service.cs", "installer/guest/stub-service.cs", "repo"),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pack").mkdir()
            vm_kit = root / "vm-kit"
            vm_kit.mkdir()
            files = {"installer.exe": b"\x00real installer\xff", "VM-TEST.md": b"VM test kit\n", "vm-state.ps1": b"Write-Output 'state'\n"}
            for name, data in files.items():
                (vm_kit / name).write_bytes(data)
            (vm_kit / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in files.items()), encoding="ascii")
            kit, wrapper, _ = container.make_kit(root / "pack", root / "out", "L30", ["uninstall-edge"], sha="b" * 40, vm_kit=vm_kit)
            self.assertEqual(sorted(p.name for p in kit.iterdir()),
                             ["SHA256SUMS", "c-uninstall-edge.ps1", "installer.exe", "stub-service.cs", "uninstall-edge.ps1"])
            self.assertEqual((kit / "installer.exe").read_bytes(), files["installer.exe"])
            case = (kit / "c-uninstall-edge.ps1").read_text(encoding="ascii")
            self.assertIn("'installer.exe' = 'installer.exe'", case)
            self.assertIn("'stub-service.cs' = 'installer\\guest\\stub-service.cs'", case)
            self.assertIn("-File (Join-Path $w 'installer\\guest\\uninstall-edge.ps1')", case)
            self.assertIn("-cnotmatch '^\\[verdict\\] c-uninstall-edge PASS$'", case)
            both, _, _ = container.make_kit(root / "pack", root / "out2", "L30", ["fresh-install", "uninstall-edge"], sha="b" * 40, vm_kit=vm_kit)
            self.assertTrue({"installer.exe", "VM-TEST.md", "vm-state.ps1", "vm-kit-SHA256SUMS"} <= {p.name for p in both.iterdir()})
            with self.assertRaisesRegex(container.BadArgument, r"^--case uninstall-edge requires --vm-kit DIR$"):
                container.make_kit(root / "pack", root / "out3", "L30", ["uninstall-edge"], sha="b" * 40)


VERDICT_SCENARIO = r"""
$report = Join-Path $base 'r.txt'
foreach ($mode in 'all-pass', 'mixed') {
    [IO.File]::WriteAllText($report, '')
    $script:rowState = @{}
    if ($mode -eq 'all-pass') { foreach ($id in $rows) { Ok6c $true $id 'ok' 'bad' } }
    else {
        Ok6c $true 'SL-6c-leftover-default-launch' 'ok' 'bad'
        Ok6c $false 'SL-6c-leftover-default-launch' 'ok' 'second result ignored'
        Ok6c $false 'SL-6c-clean-default' 'ok' 'left folder=True'
        Res6c 'SL-6c-empty-folder-edge' 'UNPROVEN' 'the holder process was not running before the uninstall'
        foreach ($id in $rows[1..6]) { Res6c $id 'PASS' 'ok' }
    }
    Write-Verdict
    Get-Content -LiteralPath $report | ForEach-Object { "$mode|$_" }
}
"""


@requires_pwsh
class UninstallEdgeFunctions(unittest.TestCase):
    def test_verdict_passes_only_when_all_ten_rows_pass_and_unproven_is_a_failure(self):
        lines = run_functions(SCRIPT, ("Log", "Res6c", "Ok6c", "Write-Verdict"), VERDICT_SCENARIO, ("rows", "rowState"))
        by_mode = {m: [line.split("|", 1)[1] for line in lines if line.startswith(m + "|")] for m in ("all-pass", "mixed")}
        self.assertEqual(by_mode["all-pass"], [f"ROW {r} PASS ok" for r in ROWS_IN_ORDER] + [PASS_LINE])
        mixed = by_mode["mixed"]
        self.assertEqual(mixed[:3], ["ROW SL-6c-leftover-default-launch PASS ok", "ROW SL-6c-clean-default FAIL left folder=True",
                                     "ROW SL-6c-empty-folder-edge FAIL unproven: the holder process was not running before the uninstall"])
        self.assertIn("ROW SL-6c-service-running-uninstall FAIL unproven: no result: the driver stopped before this row (see sl6c.txt)", mixed)
        self.assertEqual(mixed[-1], "[verdict] c-uninstall-edge FAIL SL-6c-clean-default,SL-6c-empty-folder-edge,SL-6c-service-running-uninstall")
        self.assertEqual(container.judge("uninstall-edge.ps1", by_mode["all-pass"]), (True, "one passing verdict line"))
        self.assertEqual(container.judge("uninstall-edge.ps1", mixed), (False, "verdict line did not pass"))

    def test_driver_output_never_emits_the_case_end_marker(self):
        lines = run_functions(SCRIPT, ("Log", "Res6c", "Ok6c", "Write-Verdict"), VERDICT_SCENARIO, ("rows", "rowState"))
        self.assertEqual({line.split("|", 1)[0] for line in lines}, {"all-pass", "mixed"})
        for line in lines:
            mode, output = line.split("|", 1)
            with self.subTest(mode=mode, output=output):
                self.assertNotRegex(output, r"^\[end\] c-uninstall-edge END$")

    def test_service_sid_matches_winsys(self):
        lines = run_functions(SCRIPT, ("Service-Sid",), "Service-Sid 'EcosystemRunner'\nService-Sid 'ecosystemrunner'\n")
        self.assertEqual(lines, [winsys.service_sid("EcosystemRunner")] * 2)



if __name__ == "__main__":
    unittest.main()
