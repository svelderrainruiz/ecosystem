"""CTR-7: source parity and container wiring, not a Windows measurement."""
import re
import unittest
from pathlib import Path

from installer.guest import container
from tests.guest_pwsh import requires_pwsh, run_functions

GUEST = Path(__file__).resolve().parent.parent / "installer" / "guest"
SCRIPT = GUEST / "gate-edge.ps1"
DRIVER = SCRIPT.read_text(encoding="ascii")
SOURCE = (GUEST / "gate-probes.ps1").read_text(encoding="ascii")
CHECKLIST = (GUEST / "CHECKLIST.md").read_text(encoding="utf-8")
PASS_LINE = "[verdict] c-gate-edge PASS"
PASS_ROWS = ("GATE-a-valid-keys-return", "GATE-b-secret-on-command-line-32", "GATE-d-unknown-key-31",
             "GATE-e-bad-choice-30", "GATE-g-no-arguments-no-spin", "GATE-i-L1-unpinned-pair-36")
INFO_ROWS = ("PROBE-f-url-unquoted", "PROBE-f-url-quoted", "PROBE-P3-wordfind", "PROBE-P4a", "PROBE-P4b",
             "PROBE-P4c", "PROBE-P4d", "PROBE-P5-fileread")


def check_pass_line(text):
    written = re.findall(r"Log '(\[verdict\] c-gate-edge [^']*)'", text)
    assert written == [PASS_LINE], written
    marker, passing = container.VERDICT_RULES["gate-edge.ps1"]
    assert re.match(marker, written[0]) and re.fullmatch(passing, written[0])
    assert container.judge("gate-edge.ps1", written) == (True, "one passing verdict line")
    assert "Log ('[verdict] c-gate-edge FAIL ' + ($failed -join ','))" in text


def check_parity(text):
    # The judging expressions, argument lists and measurements are copied, not reinterpreted.
    port = {line.strip() for line in text.splitlines()}
    selected = []
    for line in SOURCE.splitlines():
        line = line.strip()
        if (any(f"'{row}'" in line for row in PASS_ROWS)
                or line.startswith(("$a1 =", "$a2 =", "$g =", "$gcpu =", "$l1 =", "$l1none =", "$l1full =", "$l1shape =",
                                    "$imgKeys =", "$p4 =", "$p4names =", "foreach ($k in 'a', 'b', 'c', 'd')", 'Res "PROBE-P4',
                                    "Run-Probe 'P3", "Run-Probe 'P5", "Set-Content -LiteralPath (Join-Path $work 'p5-in.txt')",
                                    "$url =", "foreach ($v in", 'Res "PROBE-f', '$r = Start-Timed $p4',
                                    '$r = Run-Gate $installer "/S /SIGNER=$sig $($v[1])"'))):
            selected.append(line)
    assert len(selected) >= 25, selected
    for line in selected:
        assert line in port, line
    for expression in ('if ($r.Hung -or "$($r.Rc)" -ne "$expect") { $bad += $a }',
                       '$r = Start-Timed $exe $argText 40', '$cpu = Cpu-Over $r.Proc 10',
                       'function Nothing-Written { (-not (Test-Path $footprintFolder)) -and (-not (Test-Path $uninstallKey)) -and (-not (Test-Path $recFile)) }',
                       "TotalSeconds -lt 90)) { Start-Sleep -Seconds 2 }",
                       "if (Test-Path -LiteralPath (Join-Path $footprintFolder 'uninstall.exe')) { $l1un = Uninstall-Poll }"):
        assert expression in text, expression
    for variable in ("mixed", "lower"):
        original = next(line.strip() for line in SOURCE.splitlines() if line.strip().startswith(f"${variable} ="))
        assert original.replace(" -ErrorAction SilentlyContinue", "") in port


FORBIDDEN = (
    r"\bmklink\b", r"-ItemType\s+['\"]?(Junction|SymbolicLink|HardLink)", r"Create(Symbolic|Hard)Link", r"\bfsutil\b",
    r"probe-p[12]", r"Invoke-WebRequest", r"Invoke-RestMethod", r"\b(iwr|irm|curl|wget|ping|nslookup|tracert)\b",
    r"Test-(Net)?Connection", r"Start-BitsTransfer", r"Net\.(WebClient|Http|Sockets|WebRequest)", r"https?://",
    r"\bwhoami\b", r"\$env:(USERNAME|USERDOMAIN|COMPUTERNAME)", r"NTAccount", r"GetCurrent\(\)\.Name",
    r"\[Environment\]::(UserName|UserDomainName|MachineName)", r"Get-Acl", r"\.Owner\b", r"\$_\.Exception\.Message",
    r"\[end\]", r"installer-pinned", r"stub-engine",
)


def check_forbidden(text):
    hits = [p for p in FORBIDDEN if re.search(p, text, re.I)]
    assert not hits, hits


class GateEdgeDriver(unittest.TestCase):
    def test_pass_line_is_read_from_driver_and_judged_exactly(self):
        check_pass_line(DRIVER)
        for lines in ([], ["PASS"], [PASS_LINE, PASS_LINE], ["[verdict] c-gate-edge FAIL GATE-a-valid-keys-return"]):
            self.assertFalse(container.judge("gate-edge.ps1", lines)[0])

    def test_all_container_rows_are_registered_and_checklist_keeps_classification(self):
        def registered(name):
            return re.findall(r"'([^']+)'", re.search(rf"^\${name} = @\((.*?)\)$", DRIVER, re.M | re.S).group(1))
        self.assertEqual(registered("rows"), list(PASS_ROWS))
        self.assertEqual(registered("infoRows"), list(INFO_ROWS))
        table = CHECKLIST[CHECKLIST.index("### `gate-probes.ps1`"):]
        entries = [line for line in table.splitlines() if "| container-provable |" in line]
        self.assertEqual(len(entries), 10)
        for entry in entries:
            self.assertIn("case `gate-edge`", entry)
            self.assertIn("case added, not measured", entry)
            self.assertRegex(entry, r"`gate-edge\.ps1:\d+")

    def test_port_keeps_arguments_timeouts_and_pass_conditions(self):
        check_parity(DRIVER)

    def test_driver_has_no_forbidden_constructs_or_end_marker(self):
        check_forbidden(DRIVER)
        DRIVER.encode("ascii")
        self.assertNotIn('$_.FullName)', DRIVER)
        self.assertIn('steps.jsonl lines=', DRIVER)

    def test_mutants_are_caught(self):
        for check, mutant in (
            (check_pass_line, DRIVER.replace(f"Log '{PASS_LINE}'", "Log '[verdict] c-gate-edge PASSED'")),
            (check_parity, DRIVER.replace("if ($gcpu -lt 2)", "if ($gcpu -lt 20)")),
            (check_parity, DRIVER.replace('"/S /SIGNER=$sig /MODE=local"', '"/S /MODE=local"')),
            (check_forbidden, DRIVER + "\ncmd.exe /c mklink /J a b\n"),
        ):
            with self.subTest(check=check.__name__):
                self.assertNotEqual(mutant, DRIVER)
                with self.assertRaises(AssertionError):
                    check(mutant)


class GateEdgeCase(unittest.TestCase):
    def test_files_are_real_installer_and_only_p3_p4_p5(self):
        self.assertEqual(container.case_files("gate-edge"), [
            ("gate-edge.ps1", "installer/guest/gate-edge.ps1", "repo"),
            ("installer.exe", "installer.exe", "vm-kit"),
            ("probe-p3.exe.b64", "installer/guest/payload/probe-p3.exe.b64", "pack"),
            ("probe-p4.exe.b64", "installer/guest/payload/probe-p4.exe.b64", "pack"),
            ("probe-p5.exe.b64", "installer/guest/payload/probe-p5.exe.b64", "pack"),
        ])
        self.assertTrue(container.CASES["gate-edge"]["vm_kit"])
        case = container.case_script("gate-edge", "L30")
        self.assertIn("-File (Join-Path $w 'installer\\guest\\gate-edge.ps1')", case)
        self.assertIn("-cnotmatch '^\\[verdict\\] c-gate-edge PASS$'", case)
        self.assertEqual(case.count("Write-Output '[end] c-gate-edge END'"), 1)
        for name, path, _ in container.case_files("gate-edge"):
            self.assertIn(f"'{name}' = '{container.win(path)}'", case)


@requires_pwsh
class GateEdgeFunctions(unittest.TestCase):
    def test_real_verdict_outputs_every_row_once_and_info_never_fails(self):
        lines = run_functions(SCRIPT, ("Log", "Res", "Write-Verdict"), r"""
$report = Join-Path $base 'rows.txt'
foreach ($mode in 'all-pass', 'mixed', 'missing-info') {
    [IO.File]::WriteAllText($report, '')
    $script:rowState = @{}
    foreach ($id in $rows) {
        if ($mode -eq 'mixed' -and $id -eq $rows[0]) { continue }
        Res $id 'PASS' 'ok'
    }
    if ($mode -ne 'missing-info') { foreach ($id in $infoRows) { Res $id 'INFO' 'exit code 35' } }
    Write-Verdict
    Get-Content -LiteralPath $report | ForEach-Object { "$mode|$_" }
}
""", ("rows", "infoRows", "rowState"))
        for mode in ("all-pass", "mixed", "missing-info"):
            output = [line.split("|", 1)[1] for line in lines if line.startswith(mode + "|")]
            self.assertEqual(len(output), 15)
            self.assertCountEqual([line.split()[1] for line in output[:-1]], PASS_ROWS + INFO_ROWS)
            self.assertEqual(container.judge("gate-edge.ps1", output)[0], mode != "mixed")
            self.assertFalse(any("[end]" in line for line in output))
        self.assertIn("mixed|ROW GATE-a-valid-keys-return FAIL not measured: driver stopped before this row", lines)

    def test_probe_measurements_are_kept_but_unexpected_text_is_withheld(self):
        lines = run_functions(SCRIPT, ("Probe-Out",), r"""
$work = $base
foreach ($value in 'with E the loop ended at R8=5; without E the flag was never (cap 50)',
    'with E the loop ended at R8=50; without E the flag was set at 3 (cap 50)',
    'characters read: 1022 of 1030', 'characters read: 1023 of 1030', 'unexpected path C:\outside') {
    Set-Content -LiteralPath (Join-Path $work 'probe.txt') -Value $value
    Probe-Out 'probe.txt'
}
Probe-Out 'missing.txt'
""")
        self.assertEqual(lines, [
            "with E the loop ended at R8=5; without E the flag was never (cap 50)",
            "with E the loop ended at R8=50; without E the flag was set at 3 (cap 50)",
            "characters read: 1022 of 1030", "characters read: 1023 of 1030",
            "(unrecognized probe result; withheld)", "(no result file)",
        ])


if __name__ == "__main__":
    unittest.main()
