"""Uninstaller dialogs (ecosystem-control#129, GUEST7C): uninstall-smoke.ps1 -Dialogs runs the real uninstaller WITHOUT /S and reads the
message box it shows through Win32 calls. The pure parts (what counts as a message box, when a button is pressed, which text is expected,
which verdict follows) run here against fake window lists; whether the real windows look like that is what the guest run measures."""
import re
import unittest
from pathlib import Path

from tests.guest_pwsh import requires_pwsh, run_functions

ROOT = Path(__file__).resolve().parent.parent
GUEST = ROOT / "installer" / "guest"
DRIVER = (GUEST / "uninstall-smoke.ps1").read_text(encoding="ascii")
NSH = ROOT / "installer" / "nsis" / "uninstall.nsh"

U2_TEXT = ("Uninstall stopped: C:\\ProgramData\\EcosystemRunner is a link (a junction or a symbolic link), not a folder, so nothing was deleted; "
           "the uninstall entry was kept and so was uninstall.exe. Remove the link by hand and run the uninstall again.")
KEPT_TEXT = ("Uninstall stopped: the folder could not be removed (a file may still be in use); the uninstall entry was kept and so was "
             "uninstall.exe. Run the uninstall again.")

FAKES = r"""
$log = Join-Path $base 'x.log'
[IO.File]::WriteAllText($log, '')
function W($h, $top, $cls, $id, $text, $vis = $true, $en = $true, $owner = 0) {
    [pscustomobject]@{ Hwnd = [long]$h; Top = [long]$top; Owner = [long]$owner; Id = [int]$id; Visible = $vis; Enabled = $en; Class = $cls; Text = $text }
}
$wiz = @((W 100 100 '#32770' 0 'Uninstall'), (W 101 100 'Button' 1 'Uninstall'), (W 102 100 'Button' 2 'Cancel'), (W 103 100 'Button' 3 '< Back' $true $false),
        (W 104 100 'Static' -1 'Nullsoft Install System'), (W 105 100 '#32770' 1018 ''), (W 106 105 'Static' 1006 'Press Uninstall'), (W 107 105 'Edit' 1019 'C:\x'))
$wizOff = @((W 100 100 '#32770' 0 'Uninstall' $true $false), (W 101 100 'Button' 1 'Uninstall' $true $false), (W 102 100 'Button' 2 'Cancel'),
            (W 105 100 '#32770' 1018 ''), (W 106 105 'Static' 1006 'Press Uninstall'))
$box = @((W 200 200 '#32770' 0 'Uninstall' $true $true 100), (W 201 200 'Static' 20 ''), (W 202 200 'Static' 65535 'Uninstall stopped: X'), (W 203 200 'Button' 2 '&OK'))
$two = @((W 300 300 '#32770' 0 'Q'), (W 301 300 'Static' 65535 'Sure?'), (W 302 300 'Button' 6 'Yes'), (W 303 300 'Button' 7 'No'))
$noBtn = @((W 400 400 '#32770' 0 'T'), (W 401 400 'Static' 65535 'x'))
"""

STATE_SCENARIO = FAKES + r"""
$s = Get-DialogState $wiz
"wizard-only box_null=$($null -eq $s.Box) confirm=$($s.Confirm) sigs=$(@($s.Sigs).Count)"
$s = Get-DialogState ($wizOff + $box)
"wizard-and-box title=[$($s.Box.Title)] text=[$($s.Box.Text)] buttons=[$($s.Box.Buttons)] ok=$($s.Box.Ok) confirm_null=$($null -eq $s.Confirm) sigs=$(@($s.Sigs).Count)"
$s = Get-DialogState $box
"box-only ok=$($s.Box.Ok) confirm_null=$($null -eq $s.Confirm)"
$s = Get-DialogState $two
"yes-no box_buttons=[$($s.Box.Buttons)] ok_null=$($null -eq $s.Box.Ok) confirm_null=$($null -eq $s.Confirm)"
$s = Get-DialogState $noBtn
"no-button box_null=$($null -eq $s.Box)"
$s = Get-DialogState @()
"empty box_null=$($null -eq $s.Box) confirm_null=$($null -eq $s.Confirm) sigs=$(@($s.Sigs).Count)"
$s = Get-DialogState $null
"null box_null=$($null -eq $s.Box) confirm_null=$($null -eq $s.Confirm)"
"""

STEP_SCENARIO = FAKES + r"""
$script:cur = @()
$script:pressed = @()
function Get-Windows([int]$procId) { $script:cur }
function Press-Button($hwnd) { $script:pressed += [long]$hwnd }
function Fake-State { $st = New-DialogState 'U5'; $st.Clock = [pscustomobject]@{ Elapsed = [pscustomobject]@{ TotalSeconds = 0.0 } }; $st }
function Poll($st, [double]$t) { $st.Clock.Elapsed.TotalSeconds = $t; Step-Dialog 1234 $st }
function Wins { @(Get-Content -LiteralPath $log | Where-Object { $_ -like 'WIN U5 *' }).Count }

$st = Fake-State
$script:cur = $wiz
Poll $st 0.1; Poll $st 0.3; Poll $st 1.8; Poll $st 3.0
"confirm presses=$($st.Confirms) pressed=$($script:pressed -join ',') boxes=$($st.Boxes.Count)"
$script:cur = $wizOff + $box
Poll $st 3.1
"first sight clicks=$($st.Clicks) boxes=$($st.Boxes.Count) pressed=$($script:pressed -join ',')"
Poll $st 3.3; Poll $st 3.5; Poll $st 6.6; Poll $st 9.9; Poll $st 13.0
"after clicks=$($st.Clicks) boxes=$($st.Boxes.Count) text=[$($st.Boxes[0].Text)] buttons=[$($st.Boxes[0].Buttons)] pressed=$($script:pressed -join ',')"
"signatures=$(Wins)"

$script:pressed = @()
$st = Fake-State
$script:cur = $wiz + $box
Poll $st 0.1
"enabled wizard while a box is up: confirm presses=$($st.Confirms) boxes=$($st.Boxes.Count)"
Poll $st 0.2
"second poll: confirm presses=$($st.Confirms) boxes=$($st.Boxes.Count) pressed=$($script:pressed -join ',')"

$script:pressed = @()
$st = Fake-State
$script:cur = $box; Poll $st 0.1
$script:cur = $wiz; Poll $st 0.2
$script:cur = $box; Poll $st 0.3
"flicker boxes=$($st.Boxes.Count)"
Poll $st 0.4
"steady boxes=$($st.Boxes.Count) pressed=$($script:pressed -join ',')"

$script:cur = @()
$st = Fake-State
$script:pressed = @()
Poll $st 0.1; Poll $st 0.2
"nothing there boxes=$($st.Boxes.Count) pressed=$($script:pressed.Count) confirms=$($st.Confirms)"
$script:cur = $two
$st = Fake-State
Poll $st 0.1; Poll $st 0.2; Poll $st 3.5; Poll $st 7.0
"yes-no box boxes=$($st.Boxes.Count) buttons=[$($st.Boxes[0].Buttons)] clicks=$($st.Clicks) pressed=$($script:pressed.Count)"
"""

REPORT_SETUP = FAKES + r"""
$script:dialogs = $true
$script:expect = @{ 'U5' = 'Uninstall stopped: X'; 'U2' = 'Uninstall stopped: Y' }
function St([string[]]$texts, [string]$buttons = 'OK') {
    $st = New-DialogState 'U5'
    $n = 0
    foreach ($t in $texts) { $n++; $st.Boxes.Add([pscustomobject]@{ Hwnd = $n; Title = 'Uninstall'; Text = $t; Buttons = $buttons; At = 1.5 }) }
    $st
}
function Rep([string]$name, [string]$rc, $st) {
    Report-Dialogs $name $rc $st
    $l = @(Get-Content -LiteralPath $log | Where-Object { $_ -like "VERDICT $name-dialog:*" })[-1]
    ($l -split ' ')[0..2] -join ' '
}
"""

# PowerShell's -ne ignores case, -cne does not: a box whose text or button label differs from the expected one in case only must not pass.
CASE_SCENARIO = REPORT_SETUP + r"""
"same text and button: $(Rep 'U5' '40' (St @('Uninstall stopped: X')))"
"text in lower case: $(Rep 'U5' '40' (St @('uninstall stopped: x')))"
"text in upper case: $(Rep 'U5' '40' (St @('UNINSTALL STOPPED: X')))"
"button in lower case: $(Rep 'U5' '40' (St @('Uninstall stopped: X') 'ok'))"
"""

REPORT_SCENARIO = REPORT_SETUP + r"""
"match: $(Rep 'U5' '40' (St @('Uninstall stopped: X')))"
"other text: $(Rep 'U5' '40' (St @('Uninstall stopped: Z')))"
"exit code 0: $(Rep 'U5' '0' (St @('Uninstall stopped: X')))"
"no box: $(Rep 'U5' '40' (St @()))"
"timeout: $(Rep 'U5' 'timeout' (St @('Uninstall stopped: X')))"
"timeout without box: $(Rep 'U5' 'timeout' (St @()))"
"two boxes: $(Rep 'U5' '40' (St @('Uninstall stopped: X', 'Uninstall stopped: X')))"
"two buttons: $(Rep 'U5' '40' (St @('Uninstall stopped: X') 'OK,Cancel'))"
"unknown case: $(Rep 'U3' '40' (St @('Uninstall stopped: X')))"
$script:expect = $null
$script:expect = @{}
"expect empty: $(Rep 'U5' '40' (St @('Uninstall stopped: X')))"
$dl = @(Get-Content -LiteralPath $log | Where-Object { $_ -like 'DIALOG *' })
"dialog lines=$($dl.Count) first=[$($dl[0])]"
$script:dialogs = $true
Verdict 'U5' $false 'rc=timeout sec=60'
Verdict 'U5' $false 'rc=0 sec=1'
Verdict 'U5' $true 'rc=40'
$script:dialogs = $false
Verdict 'U5' $false 'rc=timeout sec=90'
Get-Content -LiteralPath $log | Where-Object { $_ -like 'VERDICT U5: *' } | ForEach-Object { ($_ -split ' ')[0..2] -join ' ' }
"killed lines=$(@(Get-Content -LiteralPath $log | Where-Object { $_ -like 'VERDICT U5-dialog: UNPROVEN*killed after the time limit' }).Count)"
"""

EXPECTED_SCENARIO = r"""
$log = Join-Path $base 'x.log'
$e = Get-DialogExpected '@NSH@' 'C:\ProgramData\EcosystemRunner'
foreach ($k in @('U2', 'U3', 'U4-26', 'U5')) { "$k=$($e[$k])" }
"keys=$($e.Keys.Count)"
$none = Get-DialogExpected (Join-Path $base 'absent.nsh') 'C:\ProgramData\EcosystemRunner'
"absent file null=$($null -eq $none)"
[IO.File]::WriteAllText((Join-Path $base 'half.nsh'), 'MessageBox MB_OK|MB_ICONSTOP "Uninstall stopped: $9" /SD IDOK' + "`n")
$half = Get-DialogExpected (Join-Path $base 'half.nsh') 'C:\ProgramData\EcosystemRunner'
"missing anchors null=$($null -eq $half)"
"""

COMPILE_SCENARIO = r"""
Add-Type -TypeDefinition $script:g7Cs -Language CSharp
$m = @([G7Win].GetMethods() | Where-Object { $_.DeclaringType -eq [G7Win] } | ForEach-Object { $_.Name } | Sort-Object -Unique)
"methods=$($m -join ',')"
$f = @([G7Item].GetFields() | ForEach-Object { $_.Name } | Sort-Object)
"fields=$($f -join ',')"
"""


@requires_pwsh
class DialogLogicRunsForReal(unittest.TestCase):
    def run_driver(self, funcs, scenario, variables=()):
        return run_functions(GUEST / "uninstall-smoke.ps1", funcs, scenario, variables)

    def test_a_message_box_is_a_top_level_dialog_of_static_and_button_controls_and_its_ok_is_found_by_its_label(self):
        lines = self.run_driver(("Get-DialogState", "Flat", "Yn"), STATE_SCENARIO)
        self.assertEqual(lines, [
            "wizard-only box_null=True confirm=101 sigs=1",
            "wizard-and-box title=[Uninstall] text=[Uninstall stopped: X] buttons=[OK] ok=203 confirm_null=True sigs=2",
            "box-only ok=203 confirm_null=True",
            "yes-no box_buttons=[Yes,No] ok_null=True confirm_null=True",
            "no-button box_null=True",
            "empty box_null=True confirm_null=True sigs=0",
            "null box_null=True confirm_null=True"], lines)

    def test_the_confirm_button_is_pressed_at_most_five_times_and_never_while_a_box_is_up_and_the_box_after_two_identical_polls(self):
        lines = self.run_driver(("Step-Dialog", "Get-DialogState", "New-DialogState", "Log", "Flat", "Yn"), STEP_SCENARIO)
        self.assertEqual(lines, [
            "confirm presses=2 pressed=101,101 boxes=0",
            "first sight clicks=0 boxes=0 pressed=101,101",
            "after clicks=3 boxes=1 text=[Uninstall stopped: X] buttons=[OK] pressed=101,101,203,203,203",
            "signatures=3",
            "enabled wizard while a box is up: confirm presses=0 boxes=0",
            "second poll: confirm presses=0 boxes=1 pressed=203",
            "flicker boxes=0",
            "steady boxes=1 pressed=101,203",
            "nothing there boxes=0 pressed=0 confirms=0",
            "yes-no box boxes=1 buttons=[Yes,No] clicks=0 pressed=0"], lines)

    def test_the_confirm_press_limit_is_five(self):
        scenario = FAKES + r"""
$script:cur = $wiz
$script:pressed = 0
function Get-Windows([int]$procId) { $script:cur }
function Press-Button($hwnd) { $script:pressed++ }
$st = New-DialogState 'U5'
$st.Clock = [pscustomobject]@{ Elapsed = [pscustomobject]@{ TotalSeconds = 0.0 } }
foreach ($i in 1..40) { $st.Clock.Elapsed.TotalSeconds = $i * 2.0; Step-Dialog 1 $st }
"pressed=$script:pressed confirms=$($st.Confirms)"
"""
        lines = self.run_driver(("Step-Dialog", "Get-DialogState", "New-DialogState", "Log", "Flat", "Yn"), scenario)
        self.assertEqual(lines, ["pressed=5 confirms=5"], lines)

    def test_the_verdict_follows_exit_code_box_count_text_and_buttons_and_a_box_never_seen_is_not_observed(self):
        lines = self.run_driver(("Report-Dialogs", "New-DialogState", "Verdict", "Unproven", "Log", "Flat", "Yn"), REPORT_SCENARIO)
        self.assertEqual(lines[:10], [
            "match: VERDICT U5-dialog: PASS",
            "other text: VERDICT U5-dialog: FAIL",
            "exit code 0: VERDICT U5-dialog: FAIL",
            "no box: VERDICT U5-dialog: UNPROVEN",
            "timeout: VERDICT U5-dialog: UNPROVEN",
            "timeout without box: VERDICT U5-dialog: UNPROVEN",
            "two boxes: VERDICT U5-dialog: FAIL",
            "two buttons: VERDICT U5-dialog: FAIL",
            "unknown case: VERDICT U3-dialog: UNPROVEN",
            "expect empty: VERDICT U5-dialog: UNPROVEN"], lines)
        self.assertRegex(lines[10], r"^dialog lines=\d+ first=\[DIALOG U5 1/1: at=1\.5s title=\[Uninstall\] text=\[Uninstall stopped: X\] buttons=\[OK\]\]$")
        self.assertEqual(lines[11:], ["VERDICT U5: UNPROVEN", "VERDICT U5: FAIL", "VERDICT U5: PASS", "VERDICT U5: FAIL", "killed lines=2"], lines)

    def test_the_text_and_the_button_label_are_compared_case_sensitively(self):
        lines = self.run_driver(("Report-Dialogs", "New-DialogState", "Verdict", "Unproven", "Log", "Flat", "Yn"), CASE_SCENARIO)
        self.assertEqual(lines, [
            "same text and button: VERDICT U5-dialog: PASS",
            "text in lower case: VERDICT U5-dialog: FAIL",
            "text in upper case: VERDICT U5-dialog: FAIL",
            "button in lower case: VERDICT U5-dialog: FAIL"], lines)

    def test_the_expected_texts_are_read_from_the_uninstaller_source(self):
        scenario = EXPECTED_SCENARIO.replace("@NSH@", str(NSH))
        lines = self.run_driver(("Get-DialogExpected", "Read-Ascii"), scenario)
        self.assertEqual(lines, ["U2=" + U2_TEXT, "U3=" + KEPT_TEXT, "U4-26=" + KEPT_TEXT, "U5=" + KEPT_TEXT, "keys=4",
                                 "absent file null=True", "missing anchors null=True"], lines)

    def test_the_win32_helper_compiles_and_offers_what_the_driver_calls(self):
        lines = self.run_driver(("Flat",), COMPILE_SCENARIO, ("g7Cs",))
        self.assertEqual(lines, ["methods=Click,Where,Windows", "fields=Class,Enabled,Hwnd,Id,Owner,Text,Top,Visible"], lines)


class DialogModeIsWrittenDownToo(unittest.TestCase):
    def helper(self):
        return DRIVER.split("$script:g7Cs = @'\n", 1)[1].split("\n'@", 1)[0]

    def test_the_win32_helper_is_c_sharp_5_ascii_and_reads_only_the_windows_of_one_process(self):
        cs = self.helper()
        cs.encode("ascii")
        for modern in ('$"', "?.", "=>", "nameof(", "out var", "?["):
            self.assertNotIn(modern, cs)
        for call in ("EnumWindows", "EnumChildWindows", "GetWindowThreadProcessId", "SendMessageTimeoutW", "PostMessageW", "GetClassNameW"):
            self.assertIn(call, cs)
        self.assertIn("if (p == pid)", cs)
        self.assertIn("0x00F5", cs)
        self.assertIn("0x000D", cs)
        self.assertNotRegex(cs, r"(?i)terminate|kill|SendInput|keybd_event|SetForeground")

    def test_the_helper_is_compiled_in_dialog_mode_only_and_only_four_cases_run(self):
        self.assertEqual(DRIVER.count("Add-Type -TypeDefinition $script:g7Cs"), 1)
        self.assertIn("function Initialize-Dialogs {\n    try { Add-Type -TypeDefinition $script:g7Cs", DRIVER)
        main = DRIVER.split("$summary = ''", 1)[1]
        dialogs = main.split("if ($script:gateOk -and $script:dialogs) {", 1)[1].split("} elseif ($script:gateOk) {", 1)[0]
        self.assertIn("if (Initialize-Dialogs) {", dialogs)
        cases = re.findall(r"Try-Case '([^']+)'", dialogs)
        self.assertEqual(cases, ["U2", "U4-26", "U3", "U5"])
        silent = main.split("} elseif ($script:gateOk) {", 1)[1]
        self.assertEqual(re.findall(r"Try-Case '([^']+)'", silent), ["U1", "U2", "U2b", "U4-26", "U4-20", "U3", "U5", "U7", "U8", "U9"])

    def test_the_run_steps_the_dialog_state_and_kills_after_sixty_seconds_in_dialog_mode(self):
        run = DRIVER.split("function Run-Un", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("$limit = if ($null -ne $script:dlg) { 60 } else { 90 }", run)
        self.assertIn("Step-Dialog $p.Id $script:dlg", run)
        self.assertIn("if ($sw.Elapsed.TotalSeconds -gt $limit) { $p.Kill(); $rc = 'timeout'; break }", run)
        measure = DRIVER.split("function Measure-Run", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("if ($script:dialogs) { $script:dlg = New-DialogState $name }", measure)
        self.assertIn('if ($script:dialogs) { Report-Dialogs $name "$($r.Rc)" $script:dlg; $script:dlg = $null }', measure)

    def test_the_second_u5_run_is_skipped_in_dialog_mode_and_the_dialog_log_has_its_own_name(self):
        u5 = DRIVER.split("function Case-U5", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("if (-not $script:dialogs) {\n            $r2 = Run-Un", u5)
        self.assertIn("'u-dialogs.txt'", DRIVER)

    def test_the_ok_button_is_found_by_its_label_without_the_accelerator_ampersand_and_in_exact_case(self):
        self.assertIn("$okb = @($buttons | Where-Object { ($_.Text -replace '&', '') -ceq 'OK' })", DRIVER)

    def test_the_stop_message_is_pressed_not_waited_for_and_the_texts_are_not_typed_into_the_driver(self):
        self.assertNotIn("Uninstall stopped", DRIVER.replace("Uninstall stopped: X", ""))
        self.assertNotIn("could not be removed (a file", DRIVER.replace("the folder could not be removed \\(a file", ""))


if __name__ == "__main__":
    unittest.main()
