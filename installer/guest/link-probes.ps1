# GUEST7A (ecosystem-control#64, issue #122): what Windows and NSIS do with directory junctions, directory symbolic links and file symbolic links.
# Runs INSIDE a disposable no-NIC clone through `winev run`, elevated (the runner's account holds the full token). Everything lives under
# C:\X\g7a; every measurement starts from a rebuilt fixture, and the fixture is cleaned WITHOUT following any link (rmdir for a directory
# link, del for a file link). probe-p6.exe (built by pack.py) does the measured instruction; this script only builds the fixture, starts it
# and checks the link and the target afterwards. A last step (GUARD lines) checks that the probe refuses a recursive removal outside the fixture,
# against a decoy folder next to it (C:\X\g7a-guard, removed again by name; a folder that is already there is not ours and is left alone:
# GUARD-SKIPPED). The GUARD-VERDICT line is PASS only when both GUARD lines read refused=1 and decoy_intact=Y. Writes C:\X\g7a\p6.log,
# copied to out\p6.txt, and out\g7a-env.txt. ASCII only; no secret. The verdict is in the log lines, not in the exit code (installer/README.md).
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$tree = (Get-Location).Path
$out = Join-Path $tree 'out'
$root = 'C:\X\g7a'
$outside = Join-Path $root 'outside'
$case = Join-Path $root 'case'
$bin = Join-Path $root 'bin'
$log = Join-Path $root 'p6.log'
$nsout = Join-Path $root 'nsis-out.txt'
$p6 = Join-Path $bin 'probe-p6.exe'
New-Item -ItemType Directory -Force -Path $out, $root, $bin | Out-Null
[IO.File]::WriteAllText($log, '', [Text.Encoding]::ASCII)

$S = @{ keep = 'KEEP-g7a-3f9c1e'; deep = 'DEEP-g7a-77b2d0'; file = 'FILE-g7a-a41c9b'; rfile = 'RFILE-g7a-5d08e2' }

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

# Removes one entry WITHOUT following a link: rmdir removes a junction or a directory symbolic link (the link only), del a file symbolic link;
# a real folder is emptied entry by entry (each entry is checked again) and removed. The path is made absolute first and the removal acts on
# that absolute form; anything not strictly inside C:\X\g7a is refused (a `..` that climbs out, a sibling such as C:\X\g7a-evil, a UNC
# path, a drive root, the empty string).
function Remove-Entry([string]$p) {
    $sep = [IO.Path]::DirectorySeparatorChar
    $full = $null
    if (-not [string]::IsNullOrWhiteSpace($p)) { try { $full = [IO.Path]::GetFullPath($p).TrimEnd($sep) } catch { $full = $null } }
    if (($null -eq $full) -or -not $full.StartsWith($root.TrimEnd($sep) + $sep, [StringComparison]::Ordinal)) { throw "refusing to remove outside the fixture: $p" }
    $p = $full
    $a = Get-Attr $p
    if ($null -eq $a) { return }
    if ($a -band 0x400) {
        if ($a -band 0x10) {
            [void](Cmd 'rmdir' $p)
            if ($null -ne (Get-Attr $p)) { try { [IO.Directory]::Delete($p) } catch { } }
        } else {
            [void](Cmd 'del' '/f' '/q' $p)
            if ($null -ne (Get-Attr $p)) { try { [IO.File]::Delete($p) } catch { } }
        }
        if ($null -ne (Get-Attr $p)) { Log "FIXTURE-STUCK: could not remove the link $p" }
    } elseif ($a -band 0x10) {
        foreach ($e in [IO.Directory]::GetFileSystemEntries($p)) { Remove-Entry $e }
        try { [IO.Directory]::Delete($p) } catch { Log "FIXTURE-STUCK: could not remove the folder ${p}: $($_.Exception.Message)" }
    } else {
        try { [IO.File]::Delete($p) } catch { Log "FIXTURE-STUCK: could not delete the file ${p}: $($_.Exception.Message)" }
    }
}

$linkSpecs = @(
    @('/J', 'jFull', 'full'), @('/J', 'jEmpty', 'empty'), @('/J', 'jGone', 'gone'),
    @('/D', 'sFull', 'full'), @('/D', 'sEmpty', 'empty'), @('/D', 'sGone', 'gone'),
    @('', 'fLive', 'file.txt'), @('', 'fGone', 'gone.txt'))
$kinds = @('jFull', 'jEmpty', 'jGone', 'sFull', 'sEmpty', 'sGone', 'fLive', 'fGone', 'rDir', 'rFile')

# The whole fixture, rebuilt from nothing: outside\full (keep.txt, sub\deep.txt), outside\empty, outside\gone and outside\gone.txt (created,
# linked, then removed so that the links dangle), outside\file.txt; case\ holds the eight links, a real empty folder rDir and a real file rFile.
$script:firstBuild = $true
function Reset-Fixture {
    Remove-Entry $case
    Remove-Entry $outside
    foreach ($d in "$outside\full\sub", "$outside\empty", "$outside\gone", $case, "$case\rDir") { [void][IO.Directory]::CreateDirectory($d) }
    Write-Ascii "$outside\full\keep.txt" $S.keep
    Write-Ascii "$outside\full\sub\deep.txt" $S.deep
    Write-Ascii "$outside\file.txt" $S.file
    Write-Ascii "$outside\gone.txt" 'GONE-g7a'
    Write-Ascii "$case\rFile" $S.rfile
    $msgs = @()
    foreach ($l in $linkSpecs) {
        $a = @('mklink')
        if ($l[0]) { $a += $l[0] }
        $a += "$case\$($l[1])", "$outside\$($l[2])"
        $msgs += (Cmd @a)
    }
    [IO.Directory]::Delete("$outside\gone")
    [IO.File]::Delete("$outside\gone.txt")
    if ($script:firstBuild) { $script:firstBuild = $false; Note 'g7a-env.txt' (@('first fixture build, mklink answers:') + $msgs) }
}

# name -> "<TYPE> name [target]" from `cmd /c dir /a`, the listing Windows itself prints (it shows a dangling link as well)
function Get-DirMap {
    $map = @{}
    $o = (& cmd.exe /c dir /a /-c $case 2>&1 | Out-String)
    foreach ($ln in ($o -split "`r?`n")) {
        if ($ln -match '<(JUNCTION|SYMLINKD|SYMLINK|DIR)>\s+(.+?)(?:\s+\[(.*)\])?\s*$') { $map[$Matches[2]] = ('<' + $Matches[1] + '> ' + $Matches[2] + $(if ($Matches[3]) { ' [' + $Matches[3] + ']' } else { '' })) }
        elseif ($ln -match '^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}\s+.*?\s[\d.,]+\s+(\S.*?)\s*$') { $map[$Matches[1]] = ('<FILE> ' + $Matches[1]) }
    }
    $map
}

function Test-Fixture {
    $want = @{ jFull = '<JUNCTION>'; jEmpty = '<JUNCTION>'; jGone = '<JUNCTION>'; sFull = '<SYMLINKD>'; sEmpty = '<SYMLINKD>'; sGone = '<SYMLINKD>'; fLive = '<SYMLINK>'; fGone = '<SYMLINK>'; rDir = '<DIR>'; rFile = '<FILE>' }
    $map = Get-DirMap
    $bad = @()
    foreach ($k in $kinds) {
        if (-not $map.ContainsKey($k) -or -not $map[$k].StartsWith($want[$k] + ' ')) { $bad += "$k=$(if ($map.ContainsKey($k)) { $map[$k] } else { 'missing' })" }
    }
    if ($bad.Count -eq 0) { 'ok' } else { 'BAD(' + ($bad -join '; ') + ')' }
}

# What is left of the outside objects, one token each, and the answer for the target of one kind (Y/N, or - when there is nothing to lose).
function Get-Outside {
    $emptyOk = [IO.Directory]::Exists("$outside\empty") -and ([IO.Directory]::GetFileSystemEntries("$outside\empty").Count -eq 0)
    $o = [ordered]@{
        full  = [IO.Directory]::Exists("$outside\full")
        sub   = [IO.Directory]::Exists("$outside\full\sub")
        keep  = ((Read-Ascii "$outside\full\keep.txt") -ceq $S.keep)
        deep  = ((Read-Ascii "$outside\full\sub\deep.txt") -ceq $S.deep)
        empty = $emptyOk
        file  = ((Read-Ascii "$outside\file.txt") -ceq $S.file)
    }
    $o
}
function Yn($b) { if ($b) { 'Y' } else { 'N' } }
function Target-Intact([string]$kind, $o) {
    switch -Regex ($kind) {
        '^[js]Full$' { return (Yn ($o.full -and $o.sub -and $o.keep -and $o.deep)) }
        '^[js]Empty$' { return (Yn $o.empty) }
        '^fLive$' { return (Yn $o.file) }
        default { return '-' }
    }
}
function Outside-Text($o) { (($o.Keys | ForEach-Object { "${_}:$(Yn $o[$_])" }) -join ',') }

function Run-P6([string]$op, [string]$path) {
    Remove-Item -LiteralPath $nsout -Force -ErrorAction SilentlyContinue
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $p6
    $psi.Arguments = "$op $path"
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $root
    $rc = 'not started'
    try {
        $p = [Diagnostics.Process]::Start($psi)
        if ($p.WaitForExit(30000)) { $rc = $p.ExitCode } else { $p.Kill(); $rc = 'timeout' }
    } catch { $rc = 'error: ' + $_.Exception.Message }
    $line = '(no output)'
    if (Test-Path -LiteralPath $nsout) { $line = (Get-Content -LiteralPath $nsout -Raw).Trim() }
    [pscustomobject]@{ Rc = $rc; Line = $line }
}
function Field([string]$line, [string]$key) { if ($line -match ('(?:^|\s)' + [regex]::Escape($key) + '=(\S*)')) { $Matches[1] } else { '?' } }

# The GUARD step: the probe must refuse a recursive removal through a `..` and next to the fixture (same name prefix). Only a decoy folder
# that this run creates is used and removed; whatever already sits at that path is not ours and is left alone.
function Run-Guard {
    if ($null -ne (Get-Attr $decoy)) { Log "GUARD-SKIPPED: $decoy already exists, so it is not ours; it was neither used nor touched"; return }
    $made = $false
    try {
        [void][IO.Directory]::CreateDirectory($decoy)
        $made = $true
        Write-Ascii "$decoy\keep.txt" $S.keep
        foreach ($g in @(@('dotdot', "$root\..\g7a-guard"), @('sibling', $decoy))) {
            $r = Run-P6 'A3r' $g[1]
            $kept = ((Read-Ascii "$decoy\keep.txt") -ceq $S.keep)
            Log "GUARD $($g[0]) A3r $($g[1]): refused=$(Field $r.Line 'refused') decoy_intact=$(Yn $kept) rc=$($r.Rc) raw=[$($r.Line)]"
        }
    } finally {
        if ($made) { try { [IO.File]::Delete("$decoy\keep.txt"); [IO.Directory]::Delete($decoy) } catch { Log "FIXTURE-STUCK: could not remove the decoy $decoy" } }
    }
}
# The verdict of the GUARD step: exactly two GUARD lines, each with refused=1 and decoy_intact=Y; a skipped step proves nothing.
function Test-GuardLines($lines) {
    $lines = @($lines)
    if (@($lines | Where-Object { $_ -like 'GUARD-SKIPPED:*' }).Count -gt 0) { return 'UNPROVEN the decoy folder was not ours, so the guard step did not run' }
    $g = @($lines | Where-Object { $_ -like 'GUARD *' })
    if ($g.Count -ne 2) { return "FAIL expected 2 GUARD lines, found $($g.Count)" }
    foreach ($l in $g) {
        if ((Field $l 'refused') -cne '1') { return "FAIL a GUARD line does not read refused=1: $l" }
        if ((Field $l 'decoy_intact') -cne 'Y') { return "FAIL a GUARD line does not read decoy_intact=Y: $l" }
    }
    'PASS both GUARD lines read refused=1 and decoy_intact=Y'
}

# ---- environment
$os = Get-CimInstance -ClassName Win32_OperatingSystem
$fs = (Get-Volume -DriveLetter C -ErrorAction SilentlyContinue | ForEach-Object { $_.FileSystem })
$symPriv = ((& whoami.exe /priv 2>&1 | Out-String) -split "`r?`n" | Where-Object { $_ -match 'SeCreateSymbolicLinkPrivilege' } | ForEach-Object { ($_ -replace '\s+', ' ').Trim() }) -join ';'
Note 'g7a-env.txt' @("caption=$($os.Caption)", "build=$($os.BuildNumber)", "elevated=$(Test-Elevated)", "user_sid=$([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)", "c_filesystem=$fs",
    "symlink_privilege=$symPriv", "utc_now=$([DateTime]::UtcNow.ToString('s'))")
Log "ENV caption=$($os.Caption) build=$($os.BuildNumber) elevated=$(Test-Elevated) fs=$fs"

$b64 = Join-Path $tree 'installer\guest\payload\probe-p6.exe.b64'
if (-not (Test-Path -LiteralPath $b64)) { Log 'FATAL: installer\guest\payload\probe-p6.exe.b64 is missing'; Copy-Item -LiteralPath $log -Destination (Join-Path $out 'p6.txt') -Force; exit 2 }
[IO.File]::WriteAllBytes($p6, [Convert]::FromBase64String((Get-Content -LiteralPath $b64 -Raw)))

try {
    Reset-Fixture
    $fx = Test-Fixture
    Log "FIXTURE first build: $fx"
    Log ('FIXTURE listing: ' + (((Get-DirMap).Values | Sort-Object) -join ' ; '))
    if ($fx -ne 'ok') { Log 'FATAL: the fixture could not be built (see out\g7a-env.txt for the mklink answers); no measurement was made'; exit 3 }

    # A1 reads, one process per entry
    foreach ($k in $kinds) {
        Reset-Fixture
        $fx = Test-Fixture
        $r = Run-P6 'A1r' "$case\$k"
        $map = Get-DirMap
        Log "READ $k`: $($r.Line) | dir=[$(if ($map.ContainsKey($k)) { $map[$k] } else { '-' })] fixture=$fx rc=$($r.Rc)"
    }

    # A2 removals and A3 recursive removal, each from a fresh fixture
    $ops = @(@('A2a', 'RMDir'), @('A2b', 'Delete'), @('A2c', 'RemoveDirectoryW'), @('A2d', 'RemoveDirectoryW-bslash'), @('A2e', 'DeleteFileW'))
    $jobs = @()
    foreach ($k in $kinds) { foreach ($o in $ops) { $jobs += , @($k, $o[0], $o[1]) } }
    foreach ($k in 'jFull', 'sFull', 'jEmpty', 'sEmpty', 'jGone', 'sGone', 'rDir') { $jobs += , @($k, 'A3r', 'RMDir-r') }
    $n = 0
    foreach ($j in $jobs) {
        $k = $j[0]; $code = $j[1]; $name = $j[2]
        Reset-Fixture
        $fx = Test-Fixture
        $r = Run-P6 $code "$case\$k"
        $map = Get-DirMap
        $dirLine = if ($map.ContainsKey($k)) { $map[$k] } else { '-' }
        $attr = Get-Attr "$case\$k"
        $attrText = if ($null -eq $attr) { 'absent' } else { '0x{0:X8}' -f $attr }
        $goneDir = Yn (-not $map.ContainsKey($k))
        $o = Get-Outside
        $line = "CASE $k $code-${name}: ret=$(Field $r.Line 'ret') err=$(Field $r.Line 'err') lasterr=$(Field $r.Line 'lasterr') linkGone=$goneDir targetIntact=$(Target-Intact $k $o)"
        $line += " | iffe=$(Field $r.Line 'iffe') attr=$attrText dir=[$dirLine] outside=$(Outside-Text $o) fixture=$fx rc=$($r.Rc)"
        if ($r.Line -notmatch 'ret=') { $line += " raw=[$($r.Line)]" }
        Log $line
        $n++
    }
    Log "DONE: $n removal measurements"

    # The probe's own guard: RMDir /r must refuse an entry outside C:\X\g7a, through a `..` and next to the fixture (same name prefix).
    $decoy = 'C:\X\g7a-guard'
    Run-Guard
    Log ('GUARD-VERDICT: ' + (Test-GuardLines @(Get-Content -LiteralPath $log)))
} catch {
    Log ('FATAL: ' + $_.Exception.Message)
} finally {
    Copy-Item -LiteralPath $log -Destination (Join-Path $out 'p6.txt') -Force
}
$guardVerdict = @(Get-Content -LiteralPath $log | Where-Object { $_ -like 'GUARD-VERDICT: *' })
Write-Output "link-probes done: $(@(Get-Content -LiteralPath $log | Where-Object { $_ -like 'CASE *' }).Count) CASE lines, $(@(Get-Content -LiteralPath $log | Where-Object { $_ -like 'READ *' }).Count) READ lines, $(@(Get-Content -LiteralPath $log | Where-Object { $_ -like 'GUARD *' }).Count) GUARD lines, $(if ($guardVerdict.Count -gt 0) { $guardVerdict[-1] } else { 'GUARD-VERDICT: none' })"
exit 0
