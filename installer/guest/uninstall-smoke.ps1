# GUEST7B (ecosystem-control#64, issue #122 part B): the REAL uninstaller of PR #118 (installer\nsis\uninstall.nsh and tree.nsh, built into
# uninstall-guest.exe by uninstall-harness.exe) run in place on real Windows, one fresh fixture per case. Runs INSIDE a disposable no-NIC clone
# through `winev run`, elevated. The product folder is C:\ProgramData\EcosystemRunner (the uninstaller calls SetShellVarContext all, so
# $APPDATA is the common application data folder, not the roaming profile); every outside folder lives under C:\X\g7b\outside. Links are
# made with mklink and removed only by rmdir / del (never a recursive delete). Before and after each case a name+hash listing of every outside
# folder and file is compared. The uninstaller writes no log of its own: its signals are the exit code and the state it leaves.
# Cases: U1 links and real content, U2 / U2b the product folder is a junction / a directory symlink, U4 depth 26 and 20, U3 unlistable folder,
# U5 locked file, U7 absent folder, U8 a directory link whose removal is blocked. Writes out\u-smoke.txt and out\g7b-env.txt. ASCII only; no secret.
# `-Dialogs` (GUEST7C, issue #129) runs only U2, U4-26, U3 and U5, WITHOUT /S: it reads the stop dialog of each one (title, text, buttons) through
# Win32 calls, presses its OK, and writes out\u-dialogs.txt instead of out\u-smoke.txt.
# OWNERSHIP GATE: before anything is deleted the run stops with one line `REFUSED: ...` (the path and the key name only) when the product folder
# exists without the marker file this harness writes into it, or the uninstall key exists with a DisplayName this harness did not write; Reset-All
# cannot run before the gate has passed. The verdict is in the log lines (VERDICT / REFUSED / SUMMARY), not in the exit code (installer/README.md).
[CmdletBinding()]
param([switch]$Dialogs)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$tree = (Get-Location).Path
$out = Join-Path $tree 'out'
$root = 'C:\X\g7b'
$prod = 'C:\ProgramData\EcosystemRunner'
$outs = Join-Path $root 'outside'
$bin = Join-Path $root 'bin'
$log = Join-Path $root 'u-smoke.log'
$keyPath = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner'
$decoyDir = if ($env:APPDATA) { Join-Path $env:APPDATA 'EcosystemRunner' } else { $null }
$markerName = '.g7b-marker'
$markerText = 'written-by-uninstall-smoke-g7b'
$keyName = 'EcosystemRunner g7b'
$script:gateOk = $false
$script:dialogs = [bool]$Dialogs
$script:dlg = $null
$script:expect = @{}
$logName = if ($script:dialogs) { 'u-dialogs.txt' } else { 'u-smoke.txt' }
New-Item -ItemType Directory -Force -Path $out, $root, $bin | Out-Null
[IO.File]::WriteAllText($log, '', [Text.Encoding]::ASCII)

function Log([string]$line) { Add-Content -LiteralPath $log -Value $line -Encoding ascii }
function Note([string]$file, $lines) { Add-Content -LiteralPath (Join-Path $out $file) -Value $lines -Encoding ascii }
function Cmd { $o = (& cmd.exe /c $args 2>&1 | Out-String); $o.Trim() }
function Write-Ascii([string]$p, [string]$text) { [IO.File]::WriteAllBytes($p, [Text.Encoding]::ASCII.GetBytes($text)) }
function Read-Ascii([string]$p) { try { [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($p)) } catch { $null } }
function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Get-Attr([string]$p) { try { [int][IO.File]::GetAttributes($p) } catch { $null } }
function Exists([string]$p) { $null -ne (Get-Attr $p) }
function Yn($b) { if ($b) { 'Y' } else { 'N' } }
function Mkdirs([string[]]$dirs) { foreach ($d in $dirs) { [void][IO.Directory]::CreateDirectory($d) } }

# Removes one entry WITHOUT following a link: rmdir removes a junction or a directory symbolic link (the link only), del a file symbolic link;
# a real folder is emptied entry by entry (each entry is checked again) and removed. The path is made absolute first and the removal acts on
# that absolute form; anything that is neither the product folder itself nor strictly inside it or inside C:\X\g7b is refused (a `..` that
# climbs out, a sibling such as C:\X\g7b-evil, a UNC path, a drive root, the empty string).
function Remove-Entry([string]$p) {
    $sep = [IO.Path]::DirectorySeparatorChar
    $full = $null
    if (-not [string]::IsNullOrWhiteSpace($p)) { try { $full = [IO.Path]::GetFullPath($p).TrimEnd($sep) } catch { $full = $null } }
    $pr = $prod.TrimEnd($sep)
    $inside = ($null -ne $full) -and (($full -ceq $pr) -or $full.StartsWith($pr + $sep, [StringComparison]::Ordinal) -or $full.StartsWith($root.TrimEnd($sep) + $sep, [StringComparison]::Ordinal))
    if (-not $inside) { throw "refusing to remove outside the fixture: $p" }
    $p = $full
    $a = Get-Attr $p
    if ($null -eq $a) { return }
    if ($a -band 0x400) {
        if ($a -band 0x10) {
            [void](Cmd 'rmdir' $p)
            if (Exists $p) { try { [IO.Directory]::Delete($p) } catch { } }
        } else {
            [void](Cmd 'del' '/f' '/q' $p)
            if (Exists $p) { try { [IO.File]::Delete($p) } catch { } }
        }
        if (Exists $p) { Log "FIXTURE-STUCK: could not remove the link $p" }
    } elseif ($a -band 0x10) {
        foreach ($e in [IO.Directory]::GetFileSystemEntries($p)) { Remove-Entry $e }
        try { [IO.Directory]::Delete($p) } catch { Log "FIXTURE-STUCK: could not remove the folder ${p}: $($_.Exception.Message)" }
    } else {
        try { [IO.File]::SetAttributes($p, [IO.FileAttributes]::Normal); [IO.File]::Delete($p) } catch { Log "FIXTURE-STUCK: could not delete the file ${p}: $($_.Exception.Message)" }
    }
}

# The uninstall entry of the product, in the 64-bit registry view (the uninstaller does SetRegView 64).
function Open-Hklm64 { [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64) }
function Set-Key { $b = Open-Hklm64; $k = $b.CreateSubKey($keyPath); $k.SetValue('DisplayName', $keyName); $k.Close(); $b.Close() }
function Test-Key { $b = Open-Hklm64; $k = $b.OpenSubKey($keyPath); $r = ($null -ne $k); if ($r) { $k.Close() }; $b.Close(); $r }
function Remove-Key { $b = Open-Hklm64; $b.DeleteSubKey($keyPath, $false); $b.Close() }
function Get-KeyName { $b = Open-Hklm64; $k = $b.OpenSubKey($keyPath); $r = $null; if ($null -ne $k) { $r = $k.GetValue('DisplayName'); $k.Close() }; $b.Close(); $r }

# The ownership gate: what sits at the product folder or under the uninstall key that this harness did not create. One reason per thing, naming
# the path or the key only (never what is in it); an empty answer means everything there is ours, or nothing is there.
function Get-Foreign {
    $why = @()
    if (Exists $prod) {
        if ((Read-Ascii (Join-Path $prod $markerName)) -cne $markerText) { $why += "the product folder $prod exists and holds no g7b marker" }
    }
    if (Test-Key) {
        if ((Get-KeyName) -cne $keyName) { $why += "the uninstall key HKLM\$keyPath is not the g7b one" }
    }
    # Every uninstall run stops and deletes the service EcosystemRunner: one that is already there is not ours, and one that cannot be queried is
    # not known to be absent (sc answers error 1060 when there is no such service).
    $svc = Cmd 'sc' 'query' 'EcosystemRunner'
    if ($svc -match 'SERVICE_NAME') { $why += 'the service EcosystemRunner exists' }
    elseif ($svc -notmatch '1060') { $why += 'the service EcosystemRunner could not be queried' }
    $why
}
function Test-Gate {
    $script:gateOk = $false
    $foreign = @(Get-Foreign)
    if ($foreign.Count -gt 0) { Log ('REFUSED: ' + ($foreign -join '; ') + '; nothing was deleted and no case was run'); return }
    $script:gateOk = $true
}
function Mark-Prod { Mkdirs @($prod); Write-Ascii (Join-Path $prod $markerName) $markerText }
function Write-Summary {
    $lines = @(Get-Content -LiteralPath $log)
    $n = @{ PASS = 0; FAIL = 0; UNPROVEN = 0 }
    foreach ($l in $lines) { if ($l -match '^VERDICT \S+: (PASS|FAIL|UNPROVEN)( |$)') { $n[$Matches[1]]++ } }
    $refused = @($lines | Where-Object { $_ -like 'REFUSED:*' }).Count
    # A case that died of a script error leaves no VERDICT line, so the counts alone would read as a clean run.
    $errored = @($lines | Where-Object { ($_ -match '^CASE \S+: SCRIPT-ERROR ') -or ($_ -like 'FATAL:*') -or ($_ -like 'CLEANUP:*') -or ($_ -like 'DIALOG-ERROR*') }).Count
    $s = "SUMMARY pass=$($n.PASS) fail=$($n.FAIL) unproven=$($n.UNPROVEN) refused=$refused error=$errored"
    Log $s
    $s
}

function Reset-All {
    if (-not $script:gateOk) { throw 'the ownership gate has not passed: nothing is deleted' }
    Remove-Entry $prod
    Remove-Entry $outs
    Remove-Key
    Mkdirs @($outs)
}

# Name + size + SHA-256 of everything under the outside area, never entering a link; sorted ordinally.
$script:sha = [Security.Cryptography.SHA256]::Create()
function Snap-Walk([string]$d, [int]$cut, $lines) {
    foreach ($e in @([IO.Directory]::GetFileSystemEntries($d))) {
        $a = Get-Attr $e
        if ($null -eq $a) { continue }
        $rel = $e.Substring($cut)
        if ($a -band 0x400) { [void]$lines.Add("LINK $rel"); continue }
        if ($a -band 0x10) { [void]$lines.Add("DIR $rel"); Snap-Walk $e $cut $lines; continue }
        try {
            $b = [IO.File]::ReadAllBytes($e)
            [void]$lines.Add(('FILE {0} {1} {2}' -f $rel, $b.Length, (([BitConverter]::ToString($script:sha.ComputeHash($b))) -replace '-', '')))
        } catch { [void]$lines.Add("FILE $rel UNREADABLE") }
    }
}
function Get-Snapshot {
    $lines = New-Object 'System.Collections.Generic.List[string]'
    if ([IO.Directory]::Exists($outs)) { Snap-Walk $outs ($outs.Length + 1) $lines }
    $arr = $lines.ToArray()
    [Array]::Sort($arr, [StringComparer]::Ordinal)
    $arr
}
function Diff-Snap($before, $after) {
    $b = @($before); $a = @($after)
    $miss = @($b | Where-Object { $a -notcontains $_ })
    $add = @($a | Where-Object { $b -notcontains $_ })
    [pscustomobject]@{ Same = (($miss.Count -eq 0) -and ($add.Count -eq 0)); Missing = $miss; Added = $add; Count = $b.Count }
}

# What is in the product folder, one token each, never entering a link: name, name\ for a folder, name[link-dir] / name[link-file].
function Get-Listing([string]$d, [string]$rel, $acc) {
    try { $entries = @([IO.Directory]::GetFileSystemEntries($d)) } catch { [void]$acc.Add($rel + '[unlistable]'); return }
    foreach ($e in ($entries | Sort-Object)) {
        $a = Get-Attr $e
        $name = $e.Substring($d.Length + 1)
        $r = if ($rel) { $rel + '\' + $name } else { $name }
        if ($null -eq $a) { [void]$acc.Add($r + '[?]'); continue }
        if ($a -band 0x400) { [void]$acc.Add($r + $(if ($a -band 0x10) { '[link-dir]' } else { '[link-file]' })); continue }
        if ($a -band 0x10) { [void]$acc.Add($r + '\'); Get-Listing $e $r $acc } else { [void]$acc.Add($r) }
    }
}
function Prod-Text {
    if (-not (Exists $prod)) { return 'ABSENT' }
    $acc = New-Object 'System.Collections.Generic.List[string]'
    Get-Listing $prod '' $acc
    $shown = @($acc | Select-Object -First 60)
    $more = if ($acc.Count -gt 60) { ' ...(+' + ($acc.Count - 60) + ' more)' } else { '' }
    '[' + ($shown -join ' ; ') + $more + '] (' + $acc.Count + ' entries)'
}
function Only-Self {
    $acc = New-Object 'System.Collections.Generic.List[string]'
    if (Exists $prod) { Get-Listing $prod '' $acc }
    @($acc | Where-Object { $_ -ne 'uninstall.exe' })
}

# ---- -Dialogs (GUEST7C, issue #129): the uninstaller runs WITHOUT /S. Win32 calls (compiled by Add-Type, in this mode only) list the windows of
# the uninstaller process on this desktop, read their class, id and text, and press a button with BM_CLICK. Nothing outside that process is read.
$script:g7Cs = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public class G7Item {
    public long Hwnd, Top, Owner;
    public int Id;
    public bool Visible, Enabled;
    public string Class, Text;
}

public static class G7Win {
    delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc p, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr h, EnumProc p, IntPtr l);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr h, uint cmd);
    [DllImport("user32.dll")] static extern int GetDlgCtrlID(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsWindowEnabled(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr SendMessageTimeoutW(IntPtr h, uint msg, IntPtr w, StringBuilder l, uint flags, uint ms, out IntPtr res);
    [DllImport("user32.dll")] static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] static extern IntPtr GetProcessWindowStation();
    [DllImport("user32.dll")] static extern IntPtr GetThreadDesktop(uint tid);
    [DllImport("user32.dll", EntryPoint = "GetUserObjectInformationW", CharSet = CharSet.Unicode)] static extern bool GetObjName(IntPtr h, int idx, StringBuilder b, int n, out int need);
    [DllImport("user32.dll", EntryPoint = "GetUserObjectInformationW")] static extern bool GetObjFlags(IntPtr h, int idx, byte[] b, int n, out int need);
    [DllImport("kernel32.dll")] static extern uint GetCurrentProcessId();
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("kernel32.dll")] static extern bool ProcessIdToSessionId(uint pid, out uint sid);

    static G7Item Make(IntPtr h, IntPtr top) {
        G7Item i = new G7Item();
        i.Hwnd = h.ToInt64();
        i.Top = top.ToInt64();
        i.Owner = GetWindow(h, 4).ToInt64();
        i.Id = GetDlgCtrlID(h);
        i.Visible = IsWindowVisible(h);
        i.Enabled = IsWindowEnabled(h);
        StringBuilder c = new StringBuilder(256);
        GetClassNameW(h, c, 256);
        i.Class = c.ToString();
        StringBuilder t = new StringBuilder(4096);
        IntPtr res;
        SendMessageTimeoutW(h, 0x000D, new IntPtr(4096), t, 2, 1000, out res);
        i.Text = t.ToString();
        return i;
    }

    public static List<G7Item> Windows(uint pid) {
        List<G7Item> list = new List<G7Item>();
        EnumProc top = delegate(IntPtr h, IntPtr l) {
            uint p;
            GetWindowThreadProcessId(h, out p);
            if (p == pid) {
                list.Add(Make(h, h));
                EnumChildWindows(h, delegate(IntPtr c, IntPtr l2) { list.Add(Make(c, h)); return true; }, IntPtr.Zero);
            }
            return true;
        };
        EnumWindows(top, IntPtr.Zero);
        return list;
    }

    public static bool Click(long hwnd) { return PostMessageW(new IntPtr(hwnd), 0x00F5, IntPtr.Zero, IntPtr.Zero); }

    public static string Where() {
        uint sid = 0;
        ProcessIdToSessionId(GetCurrentProcessId(), out sid);
        IntPtr ws = GetProcessWindowStation();
        IntPtr dk = GetThreadDesktop(GetCurrentThreadId());
        StringBuilder wn = new StringBuilder(256);
        StringBuilder dn = new StringBuilder(256);
        int need;
        GetObjName(ws, 2, wn, 512, out need);
        GetObjName(dk, 2, dn, 512, out need);
        byte[] fl = new byte[12];
        bool vis = false;
        if (GetObjFlags(ws, 1, fl, 12, out need)) { vis = (BitConverter.ToInt32(fl, 8) & 1) != 0; }
        return "session=" + sid + " window_station=" + wn + " interactive_station=" + (vis ? "Y" : "N") + " desktop=" + dn;
    }
}
'@

function Get-Windows([int]$procId) { @([G7Win]::Windows([uint32]$procId)) }
function Press-Button($hwnd) { [void][G7Win]::Click([long]$hwnd) }
function Flat([string]$s) { $s -replace '\r?\n', ' / ' }

function New-DialogState([string]$name) {
    @{ Name = $name; Clock = [Diagnostics.Stopwatch]::StartNew(); Seen = (New-Object 'System.Collections.Generic.List[string]'); Boxes = (New-Object 'System.Collections.Generic.List[object]');
       Cand = ''; Confirms = 0; LastConfirm = -10.0; LastClick = -10.0; Clicks = 0; Errors = 0 }
}

# What the windows of the uninstaller process show. A message box is a top-level #32770 window whose controls are only Static and Button (the
# wizard has a page dialog, a list or a progress bar among its controls); its OK is the one Button labelled OK, whatever its id (winev-run-9b3a7928
# showed Button:2 for the one button of a MB_OK box). The confirm button is the enabled, visible Button of id 1 of a window that is not a message box.
function Get-DialogState($items) {
    $items = @($items | Where-Object { $null -ne $_ })
    $box = $null
    $confirm = $null
    $sigs = @()
    foreach ($t in @($items | Where-Object { $_.Hwnd -eq $_.Top })) {
        $kids = @($items | Where-Object { ($_.Top -eq $t.Hwnd) -and ($_.Hwnd -ne $t.Hwnd) })
        $buttons = @($kids | Where-Object { $_.Class -ceq 'Button' })
        $others = @($kids | Where-Object { ($_.Class -cne 'Button') -and ($_.Class -cne 'Static') })
        $ok = @($buttons | Where-Object { $_.Id -eq 1 })
        $ctl = (@($kids | ForEach-Object { $_.Class + ':' + $_.Id }) -join ',')
        $sigs += ('top=' + $t.Class + ' owner=' + $t.Owner + ' visible=' + (Yn $t.Visible) + ' enabled=' + (Yn $t.Enabled) + ' title=[' + (Flat $t.Text) + '] controls=' + $ctl)
        if (($t.Class -ceq '#32770') -and ($others.Count -eq 0) -and ($buttons.Count -ge 1)) {
            if ($null -eq $box) {
                $texts = @($kids | Where-Object { ($_.Class -ceq 'Static') -and ($_.Text -ne '') } | ForEach-Object { $_.Text })
                $labels = @($buttons | ForEach-Object { $_.Text -replace '&', '' })
                $okb = @($buttons | Where-Object { ($_.Text -replace '&', '') -ceq 'OK' })
                $okHwnd = $null
                if ($okb.Count -eq 1) { $okHwnd = $okb[0].Hwnd }
                $box = [pscustomobject]@{ Hwnd = $t.Hwnd; Title = $t.Text; Text = ($texts -join ' '); Buttons = ($labels -join ','); Ok = $okHwnd }
            }
        } else {
            $c = @($ok | Where-Object { $_.Enabled -and $_.Visible })
            if (($c.Count -gt 0) -and ($null -eq $confirm)) { $confirm = $c[0].Hwnd }
        }
    }
    [pscustomobject]@{ Box = $box; Confirm = $confirm; Sigs = $sigs }
}

# One poll: log each new window signature (at most 60 per run); press the wizard's confirm button (at most 5 times, 1.5 s apart, never while a
# message box is up); a message box is recorded once, after two identical polls in a row, and its OK is pressed (again after 3 s, at most 3 times).
function Step-Dialog([int]$procId, $st) {
    $t = [Math]::Round($st.Clock.Elapsed.TotalSeconds, 1)
    $s = Get-DialogState (Get-Windows $procId)
    foreach ($g in $s.Sigs) {
        if (($st.Seen.Count -lt 60) -and (-not $st.Seen.Contains($g))) { $st.Seen.Add($g); Log "WIN $($st.Name) t=$t $g" }
    }
    if ($null -ne $s.Box) {
        $b = $s.Box
        $key = "$($b.Hwnd)|$($b.Title)|$($b.Text)|$($b.Buttons)"
        $known = (@($st.Boxes | Where-Object { $_.Hwnd -eq $b.Hwnd }).Count -gt 0)
        if (-not $known) {
            if ($st.Cand -ceq $key) {
                $st.Boxes.Add([pscustomobject]@{ Hwnd = $b.Hwnd; Title = $b.Title; Text = $b.Text; Buttons = $b.Buttons; At = $t })
                if ($null -ne $b.Ok) { Press-Button $b.Ok; $st.Clicks = 1; $st.LastClick = $t }
            } else { $st.Cand = $key }
        } elseif (($null -ne $b.Ok) -and ($st.Clicks -lt 3) -and (($t - $st.LastClick) -ge 3)) {
            Press-Button $b.Ok
            $st.Clicks++
            $st.LastClick = $t
        }
        return
    }
    $st.Cand = ''
    if (($null -ne $s.Confirm) -and ($st.Confirms -lt 5) -and (($t - $st.LastConfirm) -ge 1.5)) {
        Press-Button $s.Confirm
        $st.Confirms++
        $st.LastConfirm = $t
    }
}

# The texts the message boxes must show, read from uninstall.nsh at run time: the prefix of un.Uninstall_Stopped plus the pushed message. The
# link message names $APPDATA\EcosystemRunner, which the uninstaller expands to the product folder ($APPDATA is the common application data
# folder there). Null when an anchor is missing.
function Get-DialogExpected([string]$nshPath, [string]$prodPath) {
    $t = Read-Ascii $nshPath
    if ($null -eq $t) { return $null }
    $pre = [regex]::Match($t, 'MessageBox MB_OK\|MB_ICONSTOP "([^"$]*)\$9"')
    $lnk = [regex]::Match($t, 'Push "(\$APPDATA\\EcosystemRunner is a link[^"]*)"')
    $kept = [regex]::Match($t, 'Push "(the folder could not be removed \(a file[^"]*)"')
    if (-not ($pre.Success -and $lnk.Success -and $kept.Success)) { return $null }
    $left = $pre.Groups[1].Value + $kept.Groups[1].Value
    @{ 'U2' = ($pre.Groups[1].Value + $lnk.Groups[1].Value.Replace('$APPDATA\EcosystemRunner', $prodPath)); 'U3' = $left; 'U4-26' = $left; 'U5' = $left }
}

# One DIALOG line per message box that was read, then one verdict. PASS: exit code 40, exactly one box, its text equal to the expected one, OK
# as its only button. A box that was never seen proves nothing (NOT OBSERVED); a killed process proves nothing either.
function Report-Dialogs([string]$name, [string]$rc, $st) {
    $boxes = $st.Boxes.ToArray()
    $i = 0
    foreach ($b in $boxes) {
        $i++
        Log "DIALOG $name ${i}/$($boxes.Count): at=$($b.At)s title=[$(Flat $b.Title)] text=[$(Flat $b.Text)] buttons=[$(Flat $b.Buttons)]"
    }
    $v = "$name-dialog"
    $facts = "rc=$rc boxes=$($boxes.Count) confirm_presses=$($st.Confirms) ok_clicks=$($st.Clicks) window_signatures=$($st.Seen.Count)"
    $want = if ($script:expect.ContainsKey($name)) { $script:expect[$name] } else { $null }
    if ($rc -eq 'timeout') { Unproven $v "$facts; the process was killed after the time limit"; return }
    if ($null -eq $want) { Unproven $v "$facts; the expected text could not be read from uninstall.nsh"; return }
    if ($boxes.Count -eq 0) { Unproven $v "NOT OBSERVED: $facts; no message box was seen"; return }
    $problems = @()
    if ($rc -ne '40') { $problems += 'the exit code is not 40' }
    if ($boxes.Count -ne 1) { $problems += 'the number of message boxes is not 1' }
    if ($boxes[0].Text -cne $want) { $problems += 'the text differs from uninstall.nsh' }
    if ($boxes[0].Buttons -cne 'OK') { $problems += 'the buttons are not exactly OK' }
    if ($problems.Count -gt 0) { Verdict $v $false ($facts + '; ' + ($problems -join '; ')); return }
    Verdict $v $true "$facts; the text equals the one in uninstall.nsh; the only button is OK"
}

function Initialize-Dialogs {
    try { Add-Type -TypeDefinition $script:g7Cs -Language CSharp -ErrorAction Stop } catch { Log ('FATAL: the Win32 helper did not compile: ' + $_.Exception.Message); return $false }
    $where = try { [G7Win]::Where() } catch { 'where=unavailable: ' + $_.Exception.Message }
    $script:expect = Get-DialogExpected (Join-Path $tree 'installer\nsis\uninstall.nsh') $prod
    if ($null -eq $script:expect) { Log 'FATAL: the expected dialog texts could not be read from installer\nsis\uninstall.nsh'; return $false }
    Log "ENV dialogs $where"
    Note 'g7b-env.txt' "dialog_helper=compiled $where"
    foreach ($k in @('U2', 'U3', 'U4-26', 'U5')) { Log "EXPECT ${k}: [$($script:expect[$k])]" }
    $true
}

function Run-Un([string]$exe, [string]$argText) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = $argText
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $root
    $rc = 'not started'
    $windows = 0
    $limit = if ($null -ne $script:dlg) { 60 } else { 90 }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $p = [Diagnostics.Process]::Start($psi)
        while (-not $p.WaitForExit(100)) {
            try { $p.Refresh(); if ($p.MainWindowHandle -ne [IntPtr]::Zero) { $windows++ } } catch { }
            if (($null -ne $script:dlg) -and ($script:dlg.Errors -lt 3)) {
                try { Step-Dialog $p.Id $script:dlg } catch { $script:dlg.Errors++; Log "DIALOG-ERROR $($script:dlg.Name): $($_.Exception.Message)" }
            }
            if ($sw.Elapsed.TotalSeconds -gt $limit) { $p.Kill(); $rc = 'timeout'; break }
        }
        if ($rc -ne 'timeout') { $rc = $p.ExitCode }
    } catch { $rc = 'error: ' + $_.Exception.Message }
    [pscustomobject]@{ Rc = $rc; Sec = [Math]::Round($sw.Elapsed.TotalSeconds, 1); Windows = $windows }
}

# One measured run: snapshot, registry entry, start `uninstall.exe /S _?=<folder>`, snapshot again, one CASE line.
function Measure-Run([string]$name, [string]$exe, [string]$argText) {
    $before = @(Get-Snapshot)
    $listBefore = Prod-Text
    Set-Key
    $nsBefore = @(Get-ChildItem -LiteralPath $env:TEMP -Directory -Filter 'ns*.tmp' -ErrorAction SilentlyContinue).Count
    if ($script:dialogs) { $script:dlg = New-DialogState $name }
    $r = Run-Un $exe $argText
    $after = @(Get-Snapshot)
    $d = Diff-Snap $before $after
    $nsAfter = @(Get-ChildItem -LiteralPath $env:TEMP -Directory -Filter 'ns*.tmp' -ErrorAction SilentlyContinue).Count
    $outside = if ($d.Same) { 'SAME(' + $d.Count + ' names)' } else { 'CHANGED missing=[' + (@($d.Missing | Select-Object -First 12) -join ' ; ') + '] added=[' + (@($d.Added | Select-Object -First 12) -join ' ; ') + ']' }
    $keyKept = Test-Key
    Log "CASE ${name}: rc=$($r.Rc) sec=$($r.Sec) windows_seen=$($r.Windows) outside=$outside key=$(if ($keyKept) { 'kept' } else { 'removed' }) plugin_dirs_before_after=$nsBefore/$nsAfter"
    Log "CASE ${name} product folder before: $listBefore"
    Log "CASE ${name} product folder after:  $(Prod-Text)"
    if ($script:dialogs) { Report-Dialogs $name "$($r.Rc)" $script:dlg; $script:dlg = $null }
    [pscustomobject]@{ Rc = "$($r.Rc)"; Sec = $r.Sec; Same = $d.Same; KeyKept = $keyKept }
}
# A case whose uninstaller had to be killed after the time limit proves nothing: with -Dialogs that is UNPROVEN, never a FAIL.
function Verdict([string]$name, [bool]$ok, [string]$why) {
    if ($script:dialogs -and (-not $ok) -and ($why -match 'rc=timeout')) { Unproven $name ($why + ' (a dialog may have stayed open; the process was killed)'); return }
    Log ('VERDICT ' + $name + ': ' + $(if ($ok) { 'PASS' } else { 'FAIL' }) + ' ' + $why)
}
function Unproven([string]$name, [string]$why) { Log ('VERDICT ' + $name + ': UNPROVEN ' + $why) }
function Put-Uninstaller([string]$to) { Copy-Item -LiteralPath (Join-Path $bin 'uninstall-guest.exe') -Destination $to -Force }
function Unrun { if ($script:dialogs) { "_?=$prod" } else { "/S _?=$prod" } }
function Bad-Links([string[]]$paths) { @($paths | Where-Object { $a = Get-Attr $_; ($null -eq $a) -or (($a -band 0x400) -eq 0) }) }

# ---- U1: links and real content together
function Case-U1 {
    Reset-All
    Mark-Prod
    $o = "$outs\u1"
    Mkdirs @("$o\full\sub", "$o\empty", "$o\gone", "$o\symfull\sub", "$o\symgone", "$o\fullB\sub", "$prod\m-real\inner", "$prod\z-dir")
    Write-Ascii "$o\full\keep.txt" 'KEEP-full'; Write-Ascii "$o\full\sub\deep.txt" 'DEEP-full'
    Write-Ascii "$o\symfull\keep.txt" 'KEEP-sym'; Write-Ascii "$o\symfull\sub\deep.txt" 'DEEP-sym'
    Write-Ascii "$o\fullB\keep-b.txt" 'KEEP-b'; Write-Ascii "$o\fullB\sub\deep-b.txt" 'DEEP-b'
    Write-Ascii "$o\file.txt" 'FILE-target'
    $msgs = @()
    $msgs += Cmd 'mklink' '/J' "$prod\a1-linkFull" "$o\full"
    $msgs += Cmd 'mklink' '/J' "$prod\a2-linkEmpty" "$o\empty"
    $msgs += Cmd 'mklink' '/J' "$prod\a3-linkGone" "$o\gone"
    $msgs += Cmd 'mklink' '/D' "$prod\a4-symFull" "$o\symfull"
    $msgs += Cmd 'mklink' '/D' "$prod\a5-symGone" "$o\symgone"
    $msgs += Cmd 'mklink' "$prod\a6-fileLink.txt" "$o\file.txt"
    $msgs += Cmd 'mklink' '/J' "$prod\m-real\inner\linkB" "$o\fullB"
    [IO.Directory]::Delete("$o\gone"); [IO.Directory]::Delete("$o\symgone")
    Write-Ascii "$prod\m-real\inner\ro.txt" 'RO'; [IO.File]::SetAttributes("$prod\m-real\inner\ro.txt", [IO.FileAttributes]::ReadOnly)
    Write-Ascii "$prod\m-real\inner\hid.txt" 'HID'; [IO.File]::SetAttributes("$prod\m-real\inner\hid.txt", [IO.FileAttributes]::Hidden)
    Write-Ascii "$prod\z-file.txt" 'Z'; Write-Ascii "$prod\z-dir\x.txt" 'X'
    $links = @("$prod\a1-linkFull", "$prod\a2-linkEmpty", "$prod\a3-linkGone", "$prod\a4-symFull", "$prod\a5-symGone", "$prod\a6-fileLink.txt", "$prod\m-real\inner\linkB")
    $bad = @(Bad-Links $links)
    if ($bad.Count -gt 0) { Log "FIXTURE-BAD U1: not links: $($bad -join ',') mklink=[$($msgs -join ' | ')]"; Unproven 'U1' 'fixture could not be built'; return }
    $decoyMade = $false
    if ($decoyDir -and -not (Exists $decoyDir)) { Mkdirs @($decoyDir); Write-Ascii "$decoyDir\decoy.txt" 'ROAMING-DECOY'; $decoyMade = $true }
    Put-Uninstaller "$prod\uninstall.exe"
    $t0 = Get-Date
    $r = Measure-Run 'U1' "$prod\uninstall.exe" (Unrun)
    $names = @('a1-linkFull', 'a2-linkEmpty', 'a3-linkGone', 'a4-symFull', 'a5-symGone', 'a6-fileLink.txt', 'm-real', 'z-file.txt', 'z-dir')
    $left = @($names | Where-Object { Exists "$prod\$_" })
    $decoyKept = if ($decoyMade) { Test-Path -LiteralPath "$decoyDir\decoy.txt" } else { $false }
    $ev = @(Get-WinEvent -FilterHashtable @{ LogName = 'Application'; StartTime = $t0; Level = 1, 2, 3 } -ErrorAction SilentlyContinue)
    Log "CHECK U1 mklink=[$($msgs -join ' | ')]"
    Log "CHECK U1 entries_still_there=[$($left -join ',')] other_than_uninstall.exe=[$((Only-Self) -join ',')] roaming_decoy_kept=$(Yn $decoyKept) application_log_errors_and_warnings=$($ev.Count) $(@($ev | Select-Object -First 3 | ForEach-Object { $_.ProviderName + ':' + $_.Id }) -join ',')"
    Verdict 'U1' (($r.Rc -eq '0') -and $r.Same -and ($left.Count -eq 0) -and (@(Only-Self).Count -eq 0) -and (-not $r.KeyKept) -and $decoyKept) "rc=$($r.Rc) outside_same=$($r.Same) key_removed=$(Yn (-not $r.KeyKept))"
    if ($decoyMade) { try { [IO.File]::Delete("$decoyDir\decoy.txt"); [IO.Directory]::Delete($decoyDir) } catch { } }
}

# ---- U2 / U2b: the product folder ITSELF is a junction (/J) or a directory symbolic link (/D) to an outside folder with files
function Case-U2([string]$flag, [string]$label) {
    Reset-All
    $p2 = "$outs\$label\p2"
    Mkdirs @("$p2\sub")
    Write-Ascii "$p2\keep-p2.txt" 'KEEP-p2'; Write-Ascii "$p2\sub\deep-p2.txt" 'DEEP-p2'; Write-Ascii "$p2\$markerName" $markerText
    $m = Cmd 'mklink' $flag $prod $p2
    if (-not (Exists $prod) -or -not ((Get-Attr $prod) -band 0x400)) { Log "FIXTURE-BAD ${label}: mklink=[$m]"; Unproven $label 'fixture could not be built'; return }
    Put-Uninstaller "$prod\uninstall.exe"
    $r = Measure-Run $label "$prod\uninstall.exe" (Unrun)
    $a = Get-Attr $prod
    $linkThere = ($null -ne $a) -and (($a -band 0x400) -ne 0)
    $kept = Test-Path -LiteralPath "$p2\keep-p2.txt"
    $exeKept = Test-Path -LiteralPath "$p2\uninstall.exe"
    Log "CHECK $label mklink=[$m] product_link_still_there=$(Yn $linkThere) keep-p2.txt_kept=$(Yn $kept) uninstall.exe_kept=$(Yn $exeKept)"
    Verdict $label (($r.Rc -eq '40') -and $r.Same -and $linkThere -and $kept -and $exeKept -and $r.KeyKept) "rc=$($r.Rc) outside_same=$($r.Same) key_kept=$(Yn $r.KeyKept)"
}

# ---- U4: a chain of $n real folders d1\d2\...\dn, a file f<i>.txt in every folder and bottom.txt in the last
function Case-U4([int]$n) {
    Reset-All
    Mark-Prod
    $p = $prod
    for ($i = 1; $i -le $n; $i++) { $p = "$p\d$i"; Mkdirs @($p); Write-Ascii "$p\f$i.txt" "F$i" }
    Write-Ascii "$p\bottom.txt" 'BOTTOM'
    Put-Uninstaller "$prod\uninstall.exe"
    $r = Measure-Run "U4-$n" "$prod\uninstall.exe" (Unrun)
    $q = $prod; $levels = 0; $files = @()
    for ($i = 1; $i -le $n; $i++) {
        $q = "$q\d$i"
        if (-not [IO.Directory]::Exists($q)) { break }
        $levels = $i
        if ([IO.File]::Exists("$q\f$i.txt")) { $files += "f$i" }
    }
    $bottom = ($levels -eq $n) -and [IO.File]::Exists("$q\bottom.txt")
    Log "CHECK U4-$n folder_levels_left=$levels of $n files_left=[$($files -join ',')] bottom.txt_left=$(Yn $bottom) uninstall.exe_kept=$(Yn (Exists "$prod\uninstall.exe"))"
    if ($n -gt 24) { Verdict "U4-$n" (($r.Rc -eq '40') -and ($levels -gt 0) -and $r.KeyKept -and (Exists "$prod\uninstall.exe")) "rc=$($r.Rc) levels_left=$levels" }
    else { Verdict "U4-$n" (($r.Rc -eq '0') -and (@(Only-Self).Count -eq 0) -and (-not $r.KeyKept)) "rc=$($r.Rc) levels_left=$levels" }
}

# ---- U3: a subfolder that cannot be listed (deny list-folder for Everyone); the ACL is reset in the end
function Case-U3 {
    Reset-All
    Mark-Prod
    Mkdirs @("$prod\b-locked\deeper", "$prod\c-dir")
    Write-Ascii "$prod\a-file.txt" 'A'; Write-Ascii "$prod\b-locked\inner.txt" 'I'; Write-Ascii "$prod\b-locked\deeper\x.txt" 'X'
    Write-Ascii "$prod\c-dir\y.txt" 'Y'; Write-Ascii "$prod\z-file.txt" 'Z'
    try {
        $ic = (& icacls.exe "$prod\b-locked" /deny '*S-1-1-0:(RD)' 2>&1 | Out-String).Trim() -replace '\s+', ' '
        $unlistable = $false; $why = ''
        try { [void][IO.Directory]::GetFileSystemEntries("$prod\b-locked") } catch { $unlistable = $true; $why = $_.Exception.GetType().Name }
        $gci = $false
        try { [void](Get-ChildItem -LiteralPath "$prod\b-locked" -Force -ErrorAction Stop) } catch { $gci = $true }
        Log "CHECK U3 icacls=[$ic] unlistable_dotnet=$(Yn $unlistable) ($why) unlistable_get-childitem=$(Yn $gci)"
        if (-not $unlistable) { Unproven 'U3' 'the deny entry did not make the folder unlistable for this elevated account'; return }
        Put-Uninstaller "$prod\uninstall.exe"
        $r = Measure-Run 'U3' "$prod\uninstall.exe" (Unrun)
        $others = @('a-file.txt', 'c-dir', 'z-file.txt') | Where-Object { Exists "$prod\$_" }
        Log "CHECK U3 b-locked_left=$(Yn (Exists "$prod\b-locked")) other_entries_still_there=[$(@($others) -join ',')] uninstall.exe_kept=$(Yn (Exists "$prod\uninstall.exe"))"
        Verdict 'U3' (($r.Rc -eq '40') -and $r.KeyKept -and (Exists "$prod\b-locked") -and (Exists "$prod\uninstall.exe")) "rc=$($r.Rc) key_kept=$(Yn $r.KeyKept)"
    } finally {
        [void](& icacls.exe "$prod\b-locked" /reset 2>&1)
    }
}

# ---- U5: a file held open without sharing by a background process during the run; released afterwards, then the uninstall is run again
function Case-U5 {
    Reset-All
    Mark-Prod
    Mkdirs @("$prod\z-dir")
    Write-Ascii "$prod\a-keep.txt" 'K'; Write-Ascii "$prod\locked.txt" 'L'; Write-Ascii "$prod\z-dir\y.txt" 'Y'
    Put-Uninstaller "$prod\uninstall.exe"
    $hold = Join-Path $root 'hold.ps1'; $flag = Join-Path $root 'held.flag'
    Remove-Item -LiteralPath $flag -Force -ErrorAction SilentlyContinue
    $src = @('param([string]$path, [string]$flag, [int]$sec)', '$fs = [IO.File]::Open($path, ''Open'', ''Read'', ''None'')',
        '[IO.File]::WriteAllText($flag, ''held'')', 'Start-Sleep -Seconds $sec', '$fs.Close()') -join "`r`n"
    Write-Ascii $hold $src
    $hp = $null
    try {
        $hp = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $hold, "$prod\locked.txt", $flag, '60') -PassThru -WindowStyle Hidden
        $n = 0; while (-not (Test-Path -LiteralPath $flag) -and $n -lt 100) { Start-Sleep -Milliseconds 200; $n++ }
        if (-not (Test-Path -LiteralPath $flag)) { Unproven 'U5' 'the background process did not take the lock'; return }
        $r = Measure-Run 'U5' "$prod\uninstall.exe" (Unrun)
        $others = @('a-keep.txt', 'z-dir') | Where-Object { Exists "$prod\$_" }
        Log "CHECK U5 locked.txt_left=$(Yn (Exists "$prod\locked.txt")) other_entries_still_there=[$(@($others) -join ',')] uninstall.exe_kept=$(Yn (Exists "$prod\uninstall.exe"))"
        Verdict 'U5' (($r.Rc -eq '40') -and $r.KeyKept -and (Exists "$prod\locked.txt") -and (@($others).Count -eq 0) -and (Exists "$prod\uninstall.exe")) "rc=$($r.Rc) key_kept=$(Yn $r.KeyKept)"
        try { $hp.Kill() } catch { }
        [void]$hp.WaitForExit(5000)
        # -Dialogs: the second run would show the wizard again and wait for a click; only the dialog of the first run is wanted.
        if (-not $script:dialogs) {
            $r2 = Run-Un "$prod\uninstall.exe" (Unrun)
            Log "CHECK U5 rerun_after_release: rc=$($r2.Rc) sec=$($r2.Sec) key=$(if (Test-Key) { 'kept' } else { 'removed' }) product folder: $(Prod-Text)"
        }
    } finally {
        if ($hp) { try { $hp.Kill() } catch { } }
    }
}

# ---- U7: the product folder is absent (nothing to clear); the uninstaller runs from another folder
function Case-U7 {
    Reset-All
    Mkdirs @("$root\u7")
    Put-Uninstaller "$root\u7\uninstall.exe"
    $r = Measure-Run 'U7' "$root\u7\uninstall.exe" "/S _?=$root\u7"
    Verdict 'U7' (($r.Rc -eq '0') -and (-not $r.KeyKept) -and (-not (Exists $prod))) "rc=$($r.Rc) key_removed=$(Yn (-not $r.KeyKept))"
}

# ---- U8 (extra): a directory link whose removal is blocked (another handle on the link itself without FILE_SHARE_DELETE; the access is list-folder
# plus read-attributes because a handle with attribute-only access is not part of the share check): the failure path of the System call. The
# target must never be entered, the entries after the link must still go (stack balanced), the run ends with 40.
function Case-U8 {
    $src = @('using System;', 'using System.Runtime.InteropServices;', 'using Microsoft.Win32.SafeHandles;', 'public static class G7Hold {',
        '  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]',
        '  static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr sa, uint disp, uint flags, IntPtr tmpl);',
        '  public static SafeFileHandle OpenNoDelete(string path) { return CreateFileW(path, 0x81, 3, IntPtr.Zero, 3, 0x02200000, IntPtr.Zero); }',
        '}') -join "`r`n"
    try { Add-Type -TypeDefinition $src -ErrorAction Stop } catch { Unproven 'U8' "the helper type did not compile: $($_.Exception.Message)"; return }
    Reset-All
    Mark-Prod
    $o = "$outs\u8"
    Mkdirs @("$o\full\sub", "$o\empty", "$prod\z-dir")
    Write-Ascii "$o\full\keep.txt" 'KEEP-full'; Write-Ascii "$o\full\sub\deep.txt" 'DEEP-full'
    $m1 = Cmd 'mklink' '/J' "$prod\a1-linkFull" "$o\full"
    $m2 = Cmd 'mklink' '/J' "$prod\a2-linkEmpty" "$o\empty"
    Write-Ascii "$prod\b-file.txt" 'B'; Write-Ascii "$prod\z-file.txt" 'Z'; Write-Ascii "$prod\z-dir\x.txt" 'X'
    if (@(Bad-Links @("$prod\a1-linkFull", "$prod\a2-linkEmpty")).Count -gt 0) { Log "FIXTURE-BAD U8: mklink=[$m1 | $m2]"; Unproven 'U8' 'fixture could not be built'; return }
    Put-Uninstaller "$prod\uninstall.exe"
    $h = [G7Hold]::OpenNoDelete("$prod\a1-linkFull")
    try {
        Log "CHECK U8 handle_on_the_link_invalid=$(Yn $h.IsInvalid)"
        if ($h.IsInvalid) { Unproven 'U8' 'the blocking handle could not be opened'; return }
        $r = Measure-Run 'U8' "$prod\uninstall.exe" (Unrun)
        $stuck = Exists "$prod\a1-linkFull"
        $later = @('a2-linkEmpty', 'b-file.txt', 'z-file.txt', 'z-dir') | Where-Object { Exists "$prod\$_" }
        Log "CHECK U8 blocked_link_still_there=$(Yn $stuck) entries_still_there=[$(@($later) -join ',')] uninstall.exe_kept=$(Yn (Exists "$prod\uninstall.exe"))"
        if (-not $stuck) { Unproven 'U8' 'the handle did not block the removal of the link, so the failure path was not exercised'; return }
        Verdict 'U8' (($r.Rc -eq '40') -and $r.Same -and $r.KeyKept -and (@($later).Count -eq 0)) "rc=$($r.Rc) outside_same=$($r.Same) key_kept=$(Yn $r.KeyKept)"
    } finally {
        $h.Close()
    }
}

# ---- U9 (extra): two junctions whose target is the product folder itself (a loop, one of them a level down): each must be removed as a link
# and never walked, so the run ends with 0 and only uninstall.exe is left.
function Case-U9 {
    Reset-All
    Mark-Prod
    Mkdirs @("$prod\sub")
    Write-Ascii "$prod\sub\keep9.txt" 'K9'; Write-Ascii "$prod\z-file.txt" 'Z'
    $m1 = Cmd 'mklink' '/J' "$prod\a-loop" $prod
    $m2 = Cmd 'mklink' '/J' "$prod\sub\up" $prod
    if (@(Bad-Links @("$prod\a-loop", "$prod\sub\up")).Count -gt 0) { Log "FIXTURE-BAD U9: mklink=[$m1 | $m2]"; Unproven 'U9' 'fixture could not be built'; return }
    Put-Uninstaller "$prod\uninstall.exe"
    $r = Measure-Run 'U9' "$prod\uninstall.exe" (Unrun)
    $rest = @(Only-Self)
    Log "CHECK U9 mklink=[$m1 | $m2] entries_other_than_uninstall.exe=[$($rest -join ',')]"
    Verdict 'U9' (($r.Rc -eq '0') -and ($rest.Count -eq 0) -and (-not $r.KeyKept)) "rc=$($r.Rc) key_removed=$(Yn (-not $r.KeyKept))"
}

function Try-Case([string]$name, [scriptblock]$sb) {
    try { & $sb } catch { Log ('CASE ' + $name + ': SCRIPT-ERROR ' + $_.Exception.Message + ' at line ' + $_.InvocationInfo.ScriptLineNumber) }
}

# ---- environment and the uninstaller under test
$os = Get-CimInstance -ClassName Win32_OperatingSystem
$csc = Test-Path (Join-Path $env:windir 'Microsoft.NET\Framework64\v4.0.30319\csc.exe')
Note 'g7b-env.txt' @("caption=$($os.Caption)", "build=$($os.BuildNumber)", "elevated=$(Test-Elevated)", "user_sid=$([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)", "ps_version=$($PSVersionTable.PSVersion)",
    "ps_64bit=$([Environment]::Is64BitProcess)", "product_folder_existed_at_start=$(Exists $prod)", "csc=$csc", "mode=$(if ($script:dialogs) { 'dialogs' } else { 'silent' })",
    "service_query=$((Cmd 'sc' 'query' 'EcosystemRunner') -split '\r?\n' | Select-Object -First 1)", "utc_now=$([DateTime]::UtcNow.ToString('s'))")
$b64 = Join-Path $tree 'installer\guest\payload\uninstall-harness.exe.b64'
if (-not (Test-Path -LiteralPath $b64)) { Log 'FATAL: installer\guest\payload\uninstall-harness.exe.b64 is missing'; Copy-Item -LiteralPath $log -Destination (Join-Path $out $logName) -Force; exit 2 }
[IO.File]::WriteAllBytes((Join-Path $bin 'uninstall-harness.exe'), [Convert]::FromBase64String((Get-Content -LiteralPath $b64 -Raw)))
$mk = Run-Un (Join-Path $bin 'uninstall-harness.exe') ''
$guestExe = Join-Path $bin 'uninstall-guest.exe'
if (-not (Test-Path -LiteralPath $guestExe)) { Log "FATAL: uninstall-harness.exe (rc=$($mk.Rc)) did not write uninstall-guest.exe"; Copy-Item -LiteralPath $log -Destination (Join-Path $out $logName) -Force; exit 3 }
foreach ($f in 'uninstall-harness.exe', 'uninstall-guest.exe') {
    $fp = Join-Path $bin $f
    Note 'g7b-env.txt' "$f size=$((Get-Item -LiteralPath $fp).Length) sha256=$((Get-FileHash -LiteralPath $fp -Algorithm SHA256).Hash)"
}
Log "ENV caption=$($os.Caption) build=$($os.BuildNumber) elevated=$(Test-Elevated) ps_64bit=$([Environment]::Is64BitProcess) harness_rc=$($mk.Rc)"

$summary = ''
try {
    Test-Gate
    if ($script:gateOk -and $script:dialogs) {
        if (Initialize-Dialogs) {
            Try-Case 'U2' { Case-U2 '/J' 'U2' }
            Try-Case 'U4-26' { Case-U4 26 }
            Try-Case 'U3' { Case-U3 }
            Try-Case 'U5' { Case-U5 }
            Log 'DONE'
        }
    } elseif ($script:gateOk) {
        Try-Case 'U1' { Case-U1 }
        Try-Case 'U2' { Case-U2 '/J' 'U2' }
        Try-Case 'U2b' { Case-U2 '/D' 'U2b' }
        Try-Case 'U4-26' { Case-U4 26 }
        Try-Case 'U4-20' { Case-U4 20 }
        Try-Case 'U3' { Case-U3 }
        Try-Case 'U5' { Case-U5 }
        Try-Case 'U7' { Case-U7 }
        Try-Case 'U8' { Case-U8 }
        Try-Case 'U9' { Case-U9 }
        Log 'DONE'
    }
} catch {
    Log ('FATAL: ' + $_.Exception.Message)
} finally {
    if ($script:gateOk) { try { Reset-All } catch { Log ('CLEANUP: ' + $_.Exception.Message) } }
    $summary = Write-Summary
    Copy-Item -LiteralPath $log -Destination (Join-Path $out $logName) -Force
}
Write-Output "uninstall-smoke done: $summary"
exit 0
