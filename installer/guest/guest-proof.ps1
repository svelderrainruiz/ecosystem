# Guest proof of the Windows installer (ecosystem-control#64, SL-3..SL-7). Runs INSIDE a disposable no-NIC clone through
# `winev run`; the tree holds the installer sources, installer\guest\payload\*.b64 holds the host-built binaries (never committed).
# Writes out\results.txt (ID|PASS/FAIL/UNPROVEN|detail) and evidence files under out\. ASCII only. Prints no secret: the one
# throw-away standard account gets a random password that lives in memory only.
[CmdletBinding()]
param([switch]$ProbesOnly, [int]$UpdateLoop = 0, [switch]$GateProbes)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$tree = (Get-Location).Path
$work = 'C:\g5'
$out = Join-Path $tree 'out'
New-Item -ItemType Directory -Force -Path $work, $out | Out-Null
$results = Join-Path $out 'results.txt'
Set-Content -LiteralPath $results -Value '' -Encoding ascii

function Res($id, $state, $detail) { Add-Content -LiteralPath $results -Value ("{0}|{1}|{2}" -f $id, $state, $detail) -Encoding ascii }
function Note($file, $lines) { Add-Content -LiteralPath (Join-Path $out $file) -Value $lines -Encoding ascii }

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Listing used for before/after: owned folders and files, per-user folder, uninstall keys, services.
function Get-Listing {
    $l = New-Object System.Collections.Generic.List[string]
    foreach ($p in 'C:\ProgramData', 'C:\Users') {
        Get-ChildItem -LiteralPath $p -Force -ErrorAction SilentlyContinue | ForEach-Object { $l.Add('dir ' + $_.FullName) }
    }
    foreach ($p in 'C:\ProgramData\EcosystemRunner*', 'C:\Users\*\AppData\Local\EcosystemInstaller*', 'C:\Users\*\AppData\Roaming\Ecosystem*') {
        Get-ChildItem -Path $p -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object { $l.Add('file ' + $_.FullName) }
    }
    foreach ($k in 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall', 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall') {
        Get-ChildItem -LiteralPath $k -ErrorAction SilentlyContinue | ForEach-Object { $l.Add('reg ' + $_.Name) }
    }
    Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Services' -ErrorAction SilentlyContinue | ForEach-Object { $l.Add('svc ' + $_.PSChildName) }
    $l | Sort-Object -Unique
}

function Get-Diff($before, $after) {
    $b = @{}; foreach ($x in $before) { $b[$x] = 1 }
    $a = @{}; foreach ($x in $after) { $a[$x] = 1 }
    $added = @($after | Where-Object { -not $b.ContainsKey($_) })
    $removed = @($before | Where-Object { -not $a.ContainsKey($_) })
    ,@($added, $removed)
}

function Decode($name) {
    $src = Join-Path $tree ('installer\guest\payload\' + $name + '.b64')
    $dst = Join-Path $work $name
    [IO.File]::WriteAllBytes($dst, [Convert]::FromBase64String((Get-Content -LiteralPath $src -Raw)))
    $dst
}

function Run-Exe($exe, $argText, $cred) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = [string]$argText
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $work
    if ($cred) { $psi.UserName = $cred.UserName; $psi.Password = $cred.Password; $psi.LoadUserProfile = $true }
    try {
        $p = [Diagnostics.Process]::Start($psi)
        if (-not $p.WaitForExit(120000)) { $p.Kill(); return 'timeout' }
        return $p.ExitCode
    } catch { return ('error: ' + $_.Exception.Message) }
}

# Adds an account to a user right (for example SeBatchLogonRight) in the local security policy of this disposable clone only.
function Grant-Right($user, $right) {
    $sid = (New-Object Security.Principal.NTAccount($user)).Translate([Security.Principal.SecurityIdentifier]).Value
    $inf = Join-Path $work 'sec.inf'; $db = Join-Path $work 'sec.sdb'
    Remove-Item -LiteralPath $inf, $db -ErrorAction SilentlyContinue
    secedit.exe /export /cfg $inf /areas USER_RIGHTS | Out-Null
    $lines = @(Get-Content -LiteralPath $inf)
    $hit = $false
    $lines = $lines | ForEach-Object { if ($_ -match ('^' + $right + '\s*=')) { $hit = $true; $_ + ',*' + $sid } else { $_ } }
    if (-not $hit) { $lines = $lines | ForEach-Object { $_; if ($_ -match '^\[Privilege Rights\]') { $right + ' = *' + $sid } } }
    Set-Content -LiteralPath $inf -Value $lines -Encoding Unicode
    secedit.exe /configure /db $db /cfg $inf /areas USER_RIGHTS | Out-Null
    Remove-Item -LiteralPath $inf, $db -ErrorAction SilentlyContinue
    $LASTEXITCODE
}

# Runs a program as the standard account and returns its integer exit code, or a string ('timeout', 'error: ...') when it never ran.
# Method 1: Task Scheduler batch logon (the account was given SeBatchLogonRight in this clone). Method 2: CreateProcessWithLogonW
# through Process.Start with the in-memory credential. The password is never on a command line or in a file.
function Run-AsStd($exe, $argText) {
    $outFile = Join-Path $work 'std-out.txt'
    Remove-Item -LiteralPath $outFile -ErrorAction SilentlyContinue
    $name = 'g5task'
    $r1 = $null
    try {
        $act = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c ""' + $exe + '" ' + $argText + ' > "' + $outFile + '" 2>&1"')
        Register-ScheduledTask -TaskName $name -Action $act -User $stdUser -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Force -ErrorAction Stop | Out-Null
        Start-ScheduledTask -TaskName $name -ErrorAction Stop
        $t0 = Get-Date
        do {
            Start-Sleep -Seconds 2
            $info = Get-ScheduledTaskInfo -TaskName $name
            $busy = ((Get-ScheduledTask -TaskName $name).State -eq 'Running') -or ($info.LastTaskResult -in 267009, 267011)
        } while ($busy -and ((Get-Date) - $t0).TotalSeconds -lt 45)
        $r1 = if ($busy) { 'timeout' } else { [int]$info.LastTaskResult }
    } catch { $r1 = 'error: ' + $_.Exception.Message }
    finally { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue }
    if ($r1 -is [int]) { Note 'sl4.txt' @("standard-user launch method: task scheduler rc=$r1"); return $r1 }
    Remove-Item -LiteralPath $outFile -ErrorAction SilentlyContinue
    $r2 = Run-Exe 'cmd.exe' ('/c ""' + $exe + '" ' + $argText + ' > "' + $outFile + '" 2>&1"') $cred
    Note 'sl4.txt' @("standard-user launch: task scheduler gave '$r1'; CreateProcessWithLogon gave '$r2'")
    return $r2
}

# Runs installer\guest\service_proof.py in the tree with the guest Python; keeps all output as evidence and adds its result lines.
$py = 'C:\Python311\python.exe'
function Invoke-Proof($file, $argList, $expect = @()) {
    if (-not (Test-Path $py)) { return $false }
    $o = & $py -m installer.guest.service_proof @argList 2>&1 | Out-String
    Note $file @(("args: " + ($argList -join ' ')), $o.Trim())
    $seen = @()
    foreach ($ln in ($o -split "`r?`n")) {
        if ($ln -match '^(SL-|ERROR-)[A-Za-z0-9-]*\|(PASS|FAIL|UNPROVEN)\|') { Add-Content -LiteralPath $results -Value $ln -Encoding ascii; $seen += ($ln -split '\|')[0] }
    }
    foreach ($id in $expect) { if ($seen -notcontains $id) { Res $id 'UNPROVEN' 'service_proof returned no result line for this item (it crashed or printed nothing)' } }
    $true
}

$sig = ('ab' * 32)
$footprintFolder = 'C:\ProgramData\EcosystemRunner'
$uninstallKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner'

# ---- environment
$os = Get-CimInstance -ClassName Win32_OperatingSystem
Note 'env.txt' @("caption=$($os.Caption)", "build=$($os.BuildNumber)", "elevated=$(Test-Elevated)", "user=$env:USERNAME",
    "tz=$(tzutil /g)", "utc_now=$([DateTime]::UtcNow.ToString('s'))", "python=$((Get-Command python -ErrorAction SilentlyContinue | ForEach-Object { $_.Source }) -join ',')")
$installer = Decode 'installer.exe'
$logh = Decode 'log-harness.exe'
$unh = Decode 'uninstall-harness.exe'
$localh = Decode 'local-harness.exe'

# harmless test service, compiled here from installer\guest\stub-service.cs (no binary is committed)
$stub = Join-Path $work 'stub\stub.exe'
New-Item -ItemType Directory -Force -Path (Split-Path $stub) | Out-Null
$csc = Join-Path $env:windir 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (Test-Path $csc) { Note 'stub.txt' @((& $csc /nologo /target:exe "/out:$stub" /r:System.ServiceProcess.dll (Join-Path $tree 'installer\guest\stub-service.cs') 2>&1 | Out-String)) }
$stubOk = Test-Path $stub
Note 'env.txt' @("csc=$(Test-Path $csc) stub=$stubOk")

# Starts a program and waits at most $limitSec; returns the process, whether it ended, its exit code ('timeout' when it did not) and seconds.
function Start-Timed($exe, $argText, $limitSec) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe; $psi.Arguments = [string]$argText
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true; $psi.WorkingDirectory = $work
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try { $p = [Diagnostics.Process]::Start($psi) }
    catch { return [pscustomobject]@{ Proc = $null; Done = $true; Rc = ('not started: ' + $_.Exception.Message); Sec = 0 } }
    $done = $p.WaitForExit($limitSec * 1000)
    $rc = if ($done) { $p.ExitCode } else { 'timeout' }
    [pscustomobject]@{ Proc = $p; Done = $done; Rc = $rc; Sec = [Math]::Round($sw.Elapsed.TotalSeconds, 1) }
}
# CPU seconds a running process uses over $sec seconds (a spinning one uses about $sec).
function Cpu-Over($p, $sec) {
    $a = $p.TotalProcessorTime.TotalSeconds
    Start-Sleep -Seconds $sec
    $p.Refresh()
    [Math]::Round($p.TotalProcessorTime.TotalSeconds - $a, 2)
}

# ---- FAIL FAST (GUEST6B): the first silent start must return an exit code within 40 s; the build of main d49ca5d spun in .onInit (#108)
if ($GateProbes -or (-not $ProbesOnly -and $UpdateLoop -eq 0)) {
    $ff = Start-Timed $installer "/S /SIGNER=$sig" 40
    Note 'first-start.txt' @("first silent start (elevated, no stored signer): rc=$($ff.Rc) after $($ff.Sec) s")
    if ($ff.Done) {
        if ($ff.Rc -isnot [int]) { Res 'GUEST6B-first-silent-start' 'FAIL' "the installer could not be started: $($ff.Rc)"; exit 0 }
        Res 'GUEST6B-first-silent-start' 'PASS' "returned rc=$($ff.Rc) after $($ff.Sec) s (limit 40 s)"
        if (Test-Path $footprintFolder) { Note 'first-start.txt' @('the first start left a footprint folder; removed so that the later items start clean'); Remove-Item -Recurse -Force $footprintFolder -ErrorAction SilentlyContinue }
    } else {
        $cpu = Cpu-Over $ff.Proc 10
        $ff.Proc.Kill()
        Res 'GUEST6B-first-silent-start' 'FAIL' "HANG: no exit code after $($ff.Sec) s; CPU time used over the next 10 s = $cpu s; process killed"
        Note 'first-start.txt' @("HANG: cpu seconds over 10 s = $cpu")
        exit 0
    }
}

# ---- SL-3: host check, live edition and the decision on three fixed editions
if (-not $ProbesOnly -and -not $GateProbes) {
$hc = Join-Path $tree 'installer\hostcheck.ps1'
$live = & powershell -NoProfile -ExecutionPolicy Bypass -File $hc 2>&1 | Out-String
$liveRc = $LASTEXITCODE
Note 'sl3-hostcheck.txt' @("live rc=$liveRc", $live.Trim())
$cases = @{ 'Microsoft Windows 11 Pro' = 0; 'Microsoft Windows 11 Home' = 34; 'Microsoft Windows 11 Enterprise LTSC' = 34 }
$bad = @()
foreach ($c in $cases.Keys) {
    $f = Join-Path $work 'edition.txt'
    Set-Content -LiteralPath $f -Value $c -Encoding ascii
    $o = & powershell -NoProfile -ExecutionPolicy Bypass -File $hc -EditionFile $f 2>&1 | Out-String
    Note 'sl3-hostcheck.txt' @("file '$c' rc=$LASTEXITCODE", $o.Trim())
    if ($LASTEXITCODE -ne $cases[$c]) { $bad += $c }
}
$expected = if ($os.Caption -match '(?i)ltsc') { 34 } elseif ($os.Caption -match 'Windows 11 (Pro|Enterprise)\b') { 0 } else { 34 }
if ($bad.Count -eq 0 -and $liveRc -eq $expected) { Res 'SL-3' 'PASS' "live edition '$($os.Caption)' rc=$liveRc; fixed editions decided as specified" }
else { Res 'SL-3' 'FAIL' "live rc=$liveRc expected $expected; wrong cases: $($bad -join ',')" }

}

# ---- throw-away standard account (random password in memory only)
$stdUser = 'g5std'
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = New-Object byte[] 24; $rng.GetBytes($bytes)
$plain = 'Aa1!' + ([Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', 'x')
$secure = ConvertTo-SecureString $plain -AsPlainText -Force
$plain = $null
$cred = $null
try {
    New-LocalUser -Name $stdUser -Password $secure -AccountNeverExpires -PasswordNeverExpires | Out-Null
    $cred = New-Object Management.Automation.PSCredential($stdUser, $secure)
    $grc = Grant-Right $stdUser 'SeBatchLogonRight'
    icacls $work /grant "${stdUser}:(OI)(CI)M" | Out-Null
    Note 'sl4.txt' @("batch logon right granted to the throw-away account in this clone: secedit rc=$grc")
} catch { Note 'sl4.txt' @("standard account not created: $($_.Exception.Message)") }

# ---- -UpdateLoop N: SL-6b diagnosis only. N good updates in one run; INFO lines go to sl6b-loop.txt and never into results.txt
if ($UpdateLoop -gt 0) {
    if ($stubOk) { [void](Invoke-Proof 'sl6b-loop.txt' @('updateloop', 'EcosystemRunnerG5R', 'C:\ProgramData\EcosystemRunnerG5R', $stub, "$UpdateLoop")) }
    else { Note 'sl6b-loop.txt' @('stub not compiled') }
    exit 0
}

# ---- -ProbesOnly: the diagnostic probes of installer\guest\probes.ps1 (PROBE-*|INFO lines, never a checklist item), then stop
if ($ProbesOnly) {
    . (Join-Path $tree 'installer\guest\probes.ps1')
    exit 0
}

# ---- -GateProbes (GUEST6B): the silent gates of the real installer and the five NSIS probes of installer\guest\gate-probes.ps1, then stop
if ($GateProbes) {
    . (Join-Path $tree 'installer\guest\gate-probes.ps1')
    exit 0
}

# ---- SL-4: unelevated start, gates, footprint
$before = Get-Listing
Note 'sl4.txt' @("elevated now=$(Test-Elevated)")
if ($cred) {
    $firstRc = Run-AsStd $installer "/S /SIGNER=$sig"
    $stdLocal = "C:\Users\$stdUser\AppData\Local\EcosystemInstaller"
    New-Item -ItemType Directory -Force -Path $stdLocal -ErrorAction SilentlyContinue | Out-Null
    Set-Content -LiteralPath (Join-Path $stdLocal 'signer.sha256') -Value $sig -Encoding ascii
    icacls $stdLocal /grant "${stdUser}:(OI)(CI)F" /T 2>&1 | Out-Null
    $stdRc = Run-AsStd $installer "/S /SIGNER=$sig"
    Note 'sl4.txt' @("standard user, no stored signer, silent: rc=$firstRc (spec: 3)", "standard user, stored signer, silent: rc=$stdRc (spec: 38)")
    if ("$stdRc" -eq '38') { Res 'SL-4a-unelevated-gate' 'PASS' 'unelevated silent run ends with exit code 38' }
    elseif ("$stdRc" -match '^(error|timeout)') { Res 'SL-4a-unelevated-gate' 'UNPROVEN' "the standard account could not be started through Task Scheduler: $stdRc" }
    else { Res 'SL-4a-unelevated-gate' 'FAIL' "unelevated silent run rc=$stdRc (expected 38); no-signer first run rc=$firstRc (expected 3)" }
} else { Res 'SL-4a-unelevated-gate' 'UNPROVEN' 'no standard account could be created, the image has only an elevated Administrator' }

$adminLocal = Join-Path $env:LOCALAPPDATA 'EcosystemInstaller'
$before = Get-Listing
$adminRcNoSeed = Run-Exe $installer "/S /SIGNER=$sig" $null
New-Item -ItemType Directory -Force -Path $adminLocal | Out-Null
Set-Content -LiteralPath (Join-Path $adminLocal 'signer.sha256') -Value $sig -Encoding ascii
$adminRc = Run-Exe $installer "/S /SIGNER=$sig" $null
$after = Get-Listing
$d = Get-Diff $before $after
Note 'sl4.txt' @("elevated, no stored signer, silent: rc=$adminRcNoSeed (spec: 3)", "elevated, stored signer, silent: rc=$adminRc",
    'ADDED:', $d[0], 'REMOVED:', $d[1])
$expectedAdded = @('^dir C:\\ProgramData\\EcosystemRunner$', '^file C:\\ProgramData\\EcosystemRunner(\\installer-state\.json|\\uninstall\.exe)?$',
    '^reg HKEY_LOCAL_MACHINE\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\EcosystemRunner$',
    '^file C:\\Users\\[^\\]+\\AppData\\Local\\EcosystemInstaller(\\signer\.sha256)?$')
$unexpected = @($d[0] | Where-Object { $line = $_; -not ($expectedAdded | Where-Object { $line -match $_ }) })
$needed = @('dir C:\ProgramData\EcosystemRunner', 'file C:\ProgramData\EcosystemRunner\installer-state.json', 'file C:\ProgramData\EcosystemRunner\uninstall.exe')
$missing = @($needed | Where-Object { $d[0] -notcontains $_ })
$entry = Get-ItemProperty -LiteralPath $uninstallKey -ErrorAction SilentlyContinue
$values = if ($entry) { "DisplayName=$($entry.DisplayName) DisplayVersion=$($entry.DisplayVersion) UninstallString=$($entry.UninstallString) QuietUninstallString=$($entry.QuietUninstallString)" } else { 'no uninstall entry' }
Note 'sl4.txt' @("uninstall entry: $values", "unexpected added: $($unexpected -join '; ')", "missing: $($missing -join '; ')", "removed: $(@($d[1]).Count)")
if ($unexpected.Count -eq 0 -and $missing.Count -eq 0 -and $entry -and $entry.DisplayName -and @($d[1]).Count -eq 0) {
    Res 'SL-4b-footprint' 'PASS' "exactly the footprint items were added (folder, installer-state.json, uninstall.exe, uninstall entry with 4 values) plus the per-user signer file; no service, nothing removed"
} else { Res 'SL-4b-footprint' 'FAIL' "unexpected added: $($unexpected -join '; '); missing: $($missing -join '; '); entry: $values" }
Res 'SL-4c-pages-and-elevation-step' 'UNPROVEN' 'pages and the runas prompt need an interactive desktop; winev run is non-interactive guest control (no UI driver); silent gate covered in SL-4a'

# ---- Extra: permissions of the folder the install created under ProgramData (SetShellVarContext all)
# SL-13: the installer creates only the folder; program\runner.exe is made here, as an administrator, after the lock (the update flow does the same)
$programDir = Join-Path $footprintFolder 'program'
New-Item -ItemType Directory -Force -Path $programDir | Out-Null
if ($stubOk) { Copy-Item -LiteralPath $stub -Destination (Join-Path $programDir 'runner.exe') -Force } else { Set-Content -LiteralPath (Join-Path $programDir 'runner.exe') -Value 'x' -Encoding ascii }
if (Test-Path $py) { [void](Invoke-Proof 'sl13.txt' @('aclcheck', 'EcosystemRunner', $footprintFolder, 'SL-13-acl-as-installed') @('SL-13-acl-as-installed')) }
else { Res 'SL-13-acl-as-installed' 'UNPROVEN' 'no Python in the image' }
$acl = icacls $footprintFolder 2>&1 | Out-String
$aclState = icacls (Join-Path $footprintFolder 'installer-state.json') 2>&1 | Out-String
Note 'acl-programdata.txt' @('icacls C:\ProgramData\EcosystemRunner:', $acl.Trim(), 'icacls installer-state.json:', $aclState.Trim())
if ($cred) {
    $stateLen = (Get-Content -LiteralPath (Join-Path $footprintFolder 'installer-state.json') -Raw).Length
    $script = Join-Path $work 'stdwrite.cmd'
    Set-Content -LiteralPath $script -Encoding ascii -Value @(
        '@echo off',
        'echo whoami=%USERNAME%',
        "echo x> `"$footprintFolder\std-new.txt`"",
        'echo create-new-file rc=%errorlevel%',
        "echo x>> `"$footprintFolder\installer-state.json`"",
        'echo append-existing-file rc=%errorlevel%',
        "mkdir `"$footprintFolder\std-dir`"",
        'echo create-folder rc=%errorlevel%',
        "echo x> `"$programDir\std-new.txt`"",
        'echo create-new-file-in-program rc=%errorlevel%',
        "mkdir `"$programDir\std-dir`"",
        'echo create-folder-in-program rc=%errorlevel%')
    $wrc = Run-AsStd $script ''
    $wout = if (Test-Path (Join-Path $work 'std-out.txt')) { Get-Content -LiteralPath (Join-Path $work 'std-out.txt') -Raw } else { '' }
    $newFile = Test-Path (Join-Path $footprintFolder 'std-new.txt')
    $dirMade = (Test-Path (Join-Path $footprintFolder 'std-dir')) -or (Test-Path (Join-Path $programDir 'std-new.txt')) -or (Test-Path (Join-Path $programDir 'std-dir'))
    $stateAfter = (Get-Content -LiteralPath (Join-Path $footprintFolder 'installer-state.json') -Raw)
    $appended = $stateAfter.Length -ne $stateLen
    $ran = ($wrc -is [int]) -and ($wout -match 'create-folder-in-program rc=')
    $st = if (-not $ran) { 'UNPROVEN' } elseif ($newFile -or $dirMade -or $appended) { 'FAIL' } else { 'PASS' }
    Note 'acl-programdata.txt' @("standard-user write attempts (task rc=$wrc):", $wout.Trim(), "new file created=$newFile folder created=$dirMade")
    Res 'FINDING-programdata-folder-writable-by-standard-user' $st "standard user: create file=$newFile create folder=$dirMade append=$appended (rc=$wrc); ACL in acl-programdata.txt"
    Remove-Item -LiteralPath (Join-Path $footprintFolder 'std-new.txt'), (Join-Path $footprintFolder 'std-dir'), (Join-Path $programDir 'std-new.txt'), (Join-Path $programDir 'std-dir') -Recurse -Force -ErrorAction SilentlyContinue
} else { Res 'FINDING-programdata-folder-writable-by-standard-user' 'UNPROVEN' 'no standard account' }

# SL-13 upgrade: put back the old state (Users entry inherited into every child), then run the real installer again over its own folder
if (Test-Path $programDir) {
    # an older install had its folder inheriting from ProgramData (Users inherited into every child), not an explicit Users entry
    icacls $footprintFolder /reset | Out-Null
    $preUsers = (icacls (Join-Path $programDir 'runner.exe') | Out-String) -match 'BUILTIN\\Users'
    Note 'sl13.txt' @("before the upgrade: runner.exe has a Users entry = $preUsers", (icacls (Join-Path $programDir 'runner.exe') | Out-String))
    $upRc = Run-Exe $installer "/S /SIGNER=$sig" $null
    Note 'sl13.txt' @("upgrade: installer over its own folder, elevated, silent: rc=$upRc")
    $upRan = "$upRc" -match '^-?\d+$'
    Res 'SL-13-upgrade-run' $(if ($upRan -and "$upRc" -eq '0') { 'PASS' } else { 'FAIL' }) "installer over its own folder, elevated, silent: rc=$upRc (expected 0)"
    if (-not $upRan) {
        Res 'SL-13-acl-after-upgrade' 'UNPROVEN' "the upgrade did not finish (rc=$upRc)"
        Res 'SL-13-upgrade-children-lose-inherited-users' 'UNPROVEN' "the upgrade did not finish (rc=$upRc)"
    } else {
        if (Test-Path $py) { [void](Invoke-Proof 'sl13.txt' @('aclcheck', 'EcosystemRunner', $footprintFolder, 'SL-13-acl-after-upgrade') @('SL-13-acl-after-upgrade')) } else { Res 'SL-13-acl-after-upgrade' 'UNPROVEN' 'no Python in the image' }
        $runnerExe = Join-Path $programDir 'runner.exe'
        if (-not $preUsers) { Res 'SL-13-upgrade-children-lose-inherited-users' 'UNPROVEN' 'the setup did not put a Users entry on runner.exe' }
        elseif (-not (Test-Path $runnerExe)) { Res 'SL-13-upgrade-children-lose-inherited-users' 'UNPROVEN' "runner.exe is gone after the upgrade (rc=$upRc), so its ACL cannot be read" }
        else {
            $postUsers = (icacls $runnerExe | Out-String) -match '(?im)\bBUILTIN\\Users:|\bEveryone:|Authenticated Users:'
            Res 'SL-13-upgrade-children-lose-inherited-users' $(if ($postUsers -or "$upRc" -ne '0') { 'FAIL' } else { 'PASS' }) "installer rc=$upRc; runner.exe still has a Users, Authenticated Users or Everyone entry after the re-apply=$postUsers"
        }
    }
}

$zoneMiss = ''
# ---- SL-6a: the REAL installed uninstaller removes only owned items (runs on the install made by SL-4b)
$wowKey = 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner'
New-Item -Force -Path $wowKey | Out-Null
New-Item -ItemType Directory -Force -Path 'C:\ProgramData\EcosystemRunnerOther', 'C:\ProgramData\OtherApp' | Out-Null
Set-Content -LiteralPath 'C:\ProgramData\EcosystemRunnerOther\a.txt' -Value 'a' -Encoding ascii
Set-Content -LiteralPath 'C:\ProgramData\OtherApp\b.txt' -Value 'b' -Encoding ascii
New-Item -Force -Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OtherApp' | Out-Null
$svcMade = $false
$hadUninstaller = Test-Path (Join-Path $footprintFolder 'uninstall.exe')
if ($stubOk -and (Test-Path (Join-Path $footprintFolder 'uninstall.exe'))) {
    [void](Invoke-Proof 'sl6-service.txt' @('install', 'EcosystemRunner', $footprintFolder, $stub))
    $svcMade = Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner'
}
$pre = Get-Listing
$unRc = Run-Exe (Join-Path $footprintFolder 'uninstall.exe') '/S' $null
for ($i = 0; $i -lt 90; $i++) {
    if (-not (Test-Path $footprintFolder) -and -not (Test-Path $uninstallKey) -and -not (Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner')) { break }
    Start-Sleep -Seconds 1
}
$post = Get-Listing
$d = Get-Diff $pre $post
Note 'sl6.txt' @("real uninstall.exe /S rc=$unRc service_created=$svcMade", 'ADDED:', $d[0], 'REMOVED:', $d[1])
$folderGone = -not (Test-Path $footprintFolder)
$keyGone = -not (Test-Path $uninstallKey)
$wowKept = Test-Path $wowKey
$decoysKept = (Test-Path 'C:\ProgramData\EcosystemRunnerOther\a.txt') -and (Test-Path 'C:\ProgramData\OtherApp\b.txt') -and (Test-Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OtherApp')
$svcGone = -not (Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner')
$signerKept = Test-Path (Join-Path $adminLocal 'signer.sha256')
$unexpectedRemoved = @($d[1] | Where-Object { $_ -notmatch 'EcosystemRunner' -or $_ -match 'EcosystemRunnerOther' })
Note 'sl6.txt' @("folder_removed=$folderGone key64_removed=$keyGone service_created=$svcMade service_removed=$svcGone wow_lookalike_kept=$wowKept decoys_kept=$decoysKept signer_file_kept=$signerKept unexpected_removed=$($unexpectedRemoved -join ';')")
if ($svcMade -and $folderGone -and $keyGone -and $svcGone -and $wowKept -and $decoysKept -and $signerKept -and $unexpectedRemoved.Count -eq 0) {
    Res 'SL-6a-offline-uninstall' 'PASS' 'real uninstall.exe /S: folder, 64-bit key and running service removed; 32-bit look-alike key, look-alike folders and the signer file kept'
} else { Res 'SL-6a-offline-uninstall' 'FAIL' "service_created=$svcMade folder_removed=$folderGone key64_removed=$keyGone service_removed=$svcGone wow_kept=$wowKept decoys_kept=$decoysKept signer_kept=$signerKept (see sl6.txt)" }
if (-not $svcMade -or -not $hadUninstaller) { Res 'SL-13-uninstall-removes-whole-folder' 'UNPROVEN' "precondition not met: service_created=$svcMade uninstall.exe_present=$hadUninstaller" }
elseif ((Test-Path $programDir) -eq $false -and $folderGone) { Res 'SL-13-uninstall-removes-whole-folder' 'PASS' 'elevated uninstall removed the folder with program\ and the planted runner.exe' }
else { Res 'SL-13-uninstall-removes-whole-folder' 'FAIL' "folder_removed=$folderGone program_dir_present=$(Test-Path $programDir)" }

# ---- SL-6c: the uninstall contract of issue #91 (admin gate, running service, a leftover keeps the key and exits 40, run twice, read-only files)
# A default start (no _?=) copies the uninstaller to TEMP and the first process returns 0 at once, so those cases are judged by state: service, folder, key.
$uninstallExe = Join-Path $footprintFolder 'uninstall.exe'
function Svc-Up { Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner' }
function Svc-Running { [bool]((& sc.exe query EcosystemRunner 2>&1 | Out-String) -match 'RUNNING') }
function State-6c { "folder=$(Test-Path $footprintFolder) service=$(Svc-Up) key=$(Test-Path $uninstallKey)" }
function Wait-6c($until) { for ($i = 0; $i -lt 90; $i++) { if (& $until) { return $true }; Start-Sleep -Seconds 1 }; return $false }
function Install-6c {
    $rc = Run-Exe $installer "/S /SIGNER=$sig" $null
    $made = $false
    if ($stubOk -and $rc -eq 0 -and (Test-Path $uninstallExe)) {
        [void](Invoke-Proof 'sl6c.txt' @('install', 'EcosystemRunner', $footprintFolder, $stub))
        $made = (Svc-Up) -and (Svc-Running)
    }
    Note 'sl6c.txt' @("install: rc=$rc service running=$made $(State-6c)")
    return $made
}
function Clean-6c {
    if (Svc-Up) { & sc.exe stop EcosystemRunner 2>&1 | Out-Null; Start-Sleep -Seconds 3; & sc.exe delete EcosystemRunner 2>&1 | Out-Null }
    cmd.exe /c rmdir "$footprintFolder\link" 2>&1 | Out-Null
    $leftover = $footprintFolder
    Remove-Item -LiteralPath $leftover -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $uninstallKey -Recurse -Force -ErrorAction SilentlyContinue
}
$sl6cIds = @('SL-6c-leftover-default-launch', 'SL-6c-leftover-exit-40', 'SL-6c-run-twice-after-release', 'SL-6c-readonly-file-removed', 'SL-6c-standard-user-gate', 'SL-6c-service-running-uninstall', 'SL-6c-in-place-after-release', 'SL-6c-clean-in-place', 'SL-6c-clean-default', 'SL-6c-empty-folder-edge', 'SL-6c-leftover-keeps-uninstaller')
$sl6cDone = @()
function Res6c($id, $state, $detail) { $script:sl6cDone += $id; Res $id $state $detail }

# leftover: a file held open inside the folder (contract of PR 96 round UNINSTC: uninstall.exe goes last)
function Names-6c { if (Test-Path $footprintFolder) { (@(Get-ChildItem -LiteralPath $footprintFolder -Force -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }) -join ',') } else { '(no folder)' } }
function Exe-Kept { Test-Path $uninstallExe }
function Ok6c($cond, $id, $okText, $badText) { if ($cond) { Res6c $id 'PASS' $okText } else { Res6c $id 'FAIL' $badText } }
Clean-6c
if (Install-6c) {
    $held = Join-Path $footprintFolder 'held.txt'
    $ro = Join-Path $footprintFolder 'readonly.txt'
    Set-Content -LiteralPath $ro -Value 'ro' -Encoding ascii
    Set-ItemProperty -LiteralPath $ro -Name IsReadOnly -Value $true
    $fs = [IO.File]::Open($held, 'OpenOrCreate', 'ReadWrite', 'None')
    try {
        $rc1 = Run-Exe $uninstallExe '/S' $null
        $svcGone1 = Wait-6c { -not (Svc-Up) }
        Start-Sleep -Seconds 30
        $s1 = State-6c
        $exe1 = Exe-Kept
        Note 'sl6c.txt' @("1 leftover, default launch: process rc=$rc1 service gone=$svcGone1; 30 s later: $s1 uninstall.exe present=$exe1 files=$(Names-6c)")
        if ($rc1 -isnot [int]) { Res6c 'SL-6c-leftover-default-launch' 'UNPROVEN' "the uninstaller did not run: $rc1" }
        else { Ok6c ($svcGone1 -and $s1 -eq 'folder=True service=False key=True') 'SL-6c-leftover-default-launch' "held file: service removed, folder and uninstall key kept ($s1)" "held file: expected folder=True service=False key=True, got $s1 (service gone=$svcGone1)" }
        Ok6c $exe1 'SL-6c-leftover-keeps-uninstaller' 'after a leftover uninstall.exe is still in the folder and the key is kept' "after a leftover uninstall.exe is gone from the folder ($s1), so the key points at nothing"
    } finally { $fs.Dispose() }
    if (Test-Path $uninstallExe) {
        $rc3 = Run-Exe $uninstallExe '/S' $null
        $gone3 = Wait-6c { -not (Test-Path $footprintFolder) -and -not (Test-Path $uninstallKey) -and -not (Svc-Up) }
        $s3 = State-6c
        Note 'sl6c.txt' @("1 after releasing the file, default launch again: process rc=$rc3 everything gone=$gone3 $s3 files=$(Names-6c)")
        if ($rc3 -isnot [int]) { Res6c 'SL-6c-run-twice-after-release' 'UNPROVEN' "the second run did not start: $rc3" }
        else { Ok6c $gone3 'SL-6c-run-twice-after-release' "second default run after releasing the file removed folder, uninstall.exe, key and service ($s3)" "second run rc=$rc3 left $s3 files=$(Names-6c)" }
        Ok6c $gone3 'SL-6c-readonly-file-removed' 'the folder with a read-only file inside was removed completely' "read-only file present=$(Test-Path $ro) $s3"
    } else {
        Res6c 'SL-6c-run-twice-after-release' 'UNPROVEN' 'uninstall.exe was not available for the second run'
        Res6c 'SL-6c-readonly-file-removed' 'UNPROVEN' 'no second run, so the read-only file was not judged'
    }
} else {
    foreach ($id in 'SL-6c-leftover-default-launch', 'SL-6c-leftover-keeps-uninstaller', 'SL-6c-run-twice-after-release', 'SL-6c-readonly-file-removed') { Res6c $id 'UNPROVEN' 'precondition not met: installer or running test service (see sl6c.txt)' }
}
Clean-6c

# in place with a leftover, then released
if (Install-6c) {
    $held = Join-Path $footprintFolder 'held.txt'
    $fs = [IO.File]::Open($held, 'OpenOrCreate', 'ReadWrite', 'None')
    try {
        $rc2 = Run-Exe $uninstallExe "/S _?=$footprintFolder" $null
        $s2 = State-6c
        $exe2 = Exe-Kept
        Note 'sl6c.txt' @("2 leftover, in place (_?=): process rc=$rc2 $s2 uninstall.exe present=$exe2")
        if ($rc2 -isnot [int]) { Res6c 'SL-6c-leftover-exit-40' 'UNPROVEN' "the uninstaller did not run: $rc2" }
        else { Ok6c (($rc2 -eq 40) -and $exe2 -and $s2 -eq 'folder=True service=False key=True') 'SL-6c-leftover-exit-40' "in place with a held file: exit 40, uninstall.exe, folder and key kept ($s2)" "expected exit 40, uninstall.exe present and folder=True service=False key=True, got rc=$rc2 exe=$exe2 $s2" }
    } finally { $fs.Dispose() }
    if (Test-Path $uninstallExe) {
        $rc2b = Run-Exe $uninstallExe "/S _?=$footprintFolder" $null
        Start-Sleep -Seconds 3
        $names = Names-6c
        $s2b = State-6c
        Note 'sl6c.txt' @("2 released, in place again: process rc=$rc2b $s2b files=$names")
        if ($rc2b -isnot [int]) { Res6c 'SL-6c-in-place-after-release' 'UNPROVEN' "the second in-place run did not start: $rc2b" }
        else { Ok6c (($rc2b -eq 0) -and ($names -eq 'uninstall.exe') -and -not (Test-Path $uninstallKey) -and -not (Svc-Up)) 'SL-6c-in-place-after-release' 'in place after releasing the file: exit 0, key removed, uninstall.exe alone left (a running file cannot delete itself)' "expected rc 0, key gone and only uninstall.exe left, got rc=$rc2b $s2b files=$names" }
    } else { Res6c 'SL-6c-in-place-after-release' 'UNPROVEN' 'uninstall.exe was not available for the second in-place run' }
} else { foreach ($id in 'SL-6c-leftover-exit-40', 'SL-6c-in-place-after-release') { Res6c $id 'UNPROVEN' 'precondition not met' } }
Clean-6c

# no leftover: in place, then default, on clean installs
if (Install-6c) {
    $rcA = Run-Exe $uninstallExe "/S _?=$footprintFolder" $null
    Start-Sleep -Seconds 3
    $namesA = Names-6c
    Note 'sl6c.txt' @("3 clean, in place: process rc=$rcA $(State-6c) files=$namesA")
    if ($rcA -isnot [int]) { Res6c 'SL-6c-clean-in-place' 'UNPROVEN' "the uninstaller did not run: $rcA" }
    else { Ok6c (($rcA -eq 0) -and ($namesA -eq 'uninstall.exe') -and -not (Test-Path $uninstallKey) -and -not (Svc-Up)) 'SL-6c-clean-in-place' 'clean install, in place: exit 0, key and service gone, uninstall.exe alone left' "expected rc 0 and only uninstall.exe left, got rc=$rcA $(State-6c) files=$namesA" }
} else { Res6c 'SL-6c-clean-in-place' 'UNPROVEN' 'precondition not met' }
Clean-6c
if (Install-6c) {
    $rcB = Run-Exe $uninstallExe '/S' $null
    $goneB = Wait-6c { -not (Test-Path $footprintFolder) -and -not (Test-Path $uninstallKey) -and -not (Svc-Up) }
    Note 'sl6c.txt' @("3 clean, default: process rc=$rcB $(State-6c)")
    if ($rcB -isnot [int]) { Res6c 'SL-6c-clean-default' 'UNPROVEN' "the uninstaller did not run: $rcB" }
    else { Ok6c $goneB 'SL-6c-clean-default' 'clean install, default start: folder, uninstall.exe, key and service gone' "expected everything gone, got $(State-6c) files=$(Names-6c)" }
} else { Res6c 'SL-6c-clean-default' 'UNPROVEN' 'precondition not met' }
Clean-6c

# the edge: an otherwise EMPTY folder held as a process's current directory
if (Install-6c) {
    $holder = Start-Process -FilePath cmd.exe -ArgumentList '/c', "cd /d $footprintFolder & ping -n 400 127.0.0.1 > nul" -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 3
    $rcE = Run-Exe $uninstallExe '/S' $null
    $keyE = Wait-6c { -not (Test-Path $uninstallKey) -and -not (Svc-Up) }
    Start-Sleep -Seconds 20
    $sE = State-6c
    $namesE = Names-6c
    Note 'sl6c.txt' @("4 edge, folder held as current directory: process rc=$rcE key and service gone=$keyE $sE files=$namesE")
    if ($rcE -isnot [int]) { Res6c 'SL-6c-empty-folder-edge' 'UNPROVEN' "the uninstaller did not run: $rcE" }
    else { Ok6c ($keyE -and (Test-Path $footprintFolder) -and $namesE -eq '') 'SL-6c-empty-folder-edge' 'held empty folder: entry and service removed, uninstall.exe gone, folder left empty' "expected key removed, folder present and empty, got $sE files=$namesE" }
    Get-CimInstance Win32_Process -Filter "Name='PING.EXE'" -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $holder.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
} else { Res6c 'SL-6c-empty-folder-edge' 'UNPROVEN' 'precondition not met' }
Clean-6c

# admin gate, then an elevated uninstall with the service running
if (Install-6c) {
    if ($cred) {
        $copyDir = Join-Path $work 'stdcopy'
        New-Item -ItemType Directory -Force -Path $copyDir | Out-Null
        Copy-Item -LiteralPath $uninstallExe -Destination (Join-Path $copyDir 'uninstall.exe') -Force
        $b4 = State-6c
        $stdCopyRc = Run-AsStd (Join-Path $copyDir 'uninstall.exe') "/S _?=$footprintFolder"
        $stdDirectRc = Run-AsStd $uninstallExe '/S'
        Start-Sleep -Seconds 5
        $af = State-6c
        Note 'sl6c.txt' @("standard user: copy with _?= rc=$stdCopyRc; direct start rc=$stdDirectRc; before [$b4] after [$af]")
        if (($stdCopyRc -isnot [int]) -or ($stdDirectRc -isnot [int])) { Res6c 'SL-6c-standard-user-gate' 'UNPROVEN' "the standard-user launch did not run: copy=$stdCopyRc direct=$stdDirectRc" }
        elseif ($stdCopyRc -eq 38 -and ($stdDirectRc -in 1, 5, 38) -and $b4 -eq $af) { Res6c 'SL-6c-standard-user-gate' 'PASS' "standard user: copy\uninstall.exe /S _?=folder exit 38, direct start exit $stdDirectRc, nothing changed ($af)" }
        else { Res6c 'SL-6c-standard-user-gate' 'FAIL' "copy rc=$stdCopyRc (expected 38) direct rc=$stdDirectRc (expected 1, 5 or 38: cmd says path not found or access denied) before [$b4] after [$af]" }
    } else { Res6c 'SL-6c-standard-user-gate' 'UNPROVEN' 'no standard account in this clone' }
    $runBefore = Svc-Running
    $rc4 = Run-Exe $uninstallExe '/S' $null
    $gone4 = Wait-6c { -not (Test-Path $footprintFolder) -and -not (Test-Path $uninstallKey) -and -not (Svc-Up) }
    $s4 = State-6c
    Note 'sl6c.txt' @("service running at start=$runBefore; elevated default launch rc=$rc4 everything gone within 60 s=$gone4 $s4")
    if (-not $runBefore -or ($rc4 -isnot [int])) { Res6c 'SL-6c-service-running-uninstall' 'UNPROVEN' "service running=$runBefore, uninstaller rc=$rc4" }
    elseif ($gone4) { Res6c 'SL-6c-service-running-uninstall' 'PASS' "stub service running with runner.exe open: service, folder and key all removed ($s4)" }
    else { Res6c 'SL-6c-service-running-uninstall' 'FAIL' "left $s4" }
} else {
    Res6c 'SL-6c-standard-user-gate' 'UNPROVEN' 'precondition not met: installer or running test service (see sl6c.txt)'
    Res6c 'SL-6c-service-running-uninstall' 'UNPROVEN' 'precondition not met'
}
Clean-6c

# ---- SL-13 pre-created folder (clean state: the installer is uninstalled and the signer is stored): a standard user makes the folder first
function Remove-Case($tgt) {
    $link = "$footprintFolder\link"
    if (Test-Path $link) {
        cmd.exe /c rmdir "$link" | Out-Null
        if (Test-Path $link) { return $false }
    }
    Remove-Item -LiteralPath $footprintFolder -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $tgt -Recurse -Force -ErrorAction SilentlyContinue
    return $true
}
function Test-Precreated($variant) {
    $id = "SL-13-precreated-folder-$variant"
    $tgt = Join-Path $work 'jt-target'
    Remove-Item -LiteralPath $tgt -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $tgt | Out-Null
    if (-not (Remove-Case $tgt)) { Res $id 'UNPROVEN' 'the junction left by an earlier step could not be removed with rmdir; nothing was deleted recursively'; return }
    if (Test-Path $footprintFolder) { Res $id 'UNPROVEN' 'the folder left by an earlier step could not be removed, so there is no clean state to start from'; return }
    $l = @('@echo off', "mkdir `"$footprintFolder`"")
    if ($variant -eq 'junction') { $l += "mklink /J `"$footprintFolder\link`" `"$tgt`"" }
    if ($variant -eq 'file') { $l += "echo planted> `"$footprintFolder\planted.txt`"" }
    $l += 'echo planted-ok'
    $sc = Join-Path $work 'precreate.cmd'
    Set-Content -LiteralPath $sc -Encoding ascii -Value $l
    $prc = Run-AsStd $sc ''
    $owner = if (Test-Path $footprintFolder) { (Get-Acl -LiteralPath $footprintFolder).Owner } else { '' }
    if (-not ($prc -is [int]) -or -not (Test-Path $footprintFolder) -or ($owner -notlike "*\$stdUser") -or ($variant -eq 'junction' -and -not (Test-Path "$footprintFolder\link")) -or ($variant -eq 'file' -and -not (Test-Path "$footprintFolder\planted.txt"))) {
        Res $id 'UNPROVEN' "the standard user could not plant the case (rc=$prc, folder present=$(Test-Path $footprintFolder), owner=$owner)"
    } else {
        $names0 = @(Get-ChildItem -LiteralPath $footprintFolder -Force | ForEach-Object { $_.Name } | Sort-Object)
        $irc = Run-Exe $installer "/S /SIGNER=$sig" $null
        $names1 = @(Get-ChildItem -LiteralPath $footprintFolder -Force -ErrorAction SilentlyContinue | ForEach-Object { $_.Name } | Sort-Object)
        $targetCount = @(Get-ChildItem -LiteralPath $tgt -Force -ErrorAction SilentlyContinue).Count
        $wrote = (Test-Path (Join-Path $footprintFolder 'installer-state.json')) -or (Test-Path (Join-Path $footprintFolder 'uninstall.exe')) -or (Test-Path $uninstallKey)
        Note 'sl13.txt' @("${variant}: pre-created contents [$($names0 -join ',')] after the elevated install [$($names1 -join ',')] rc=$irc target_entries=$targetCount wrote=$wrote")
        $ok = ("$irc" -eq '39') -and (($names0 -join '|') -eq ($names1 -join '|')) -and ($targetCount -eq 0) -and -not $wrote
        Res $id $(if ($ok) { 'PASS' } else { 'FAIL' }) "elevated silent install rc=$irc (expected 39); folder unchanged=$((($names0 -join '|') -eq ($names1 -join '|'))); junction target entries=$targetCount; installer wrote state or uninstall entry=$wrote; the refusal text itself is a MessageBox that /S suppresses (checked by the unit tests of the installer)"
    }
    if (-not (Remove-Case $tgt)) { Note 'sl13.txt' @("${variant}: rmdir of the junction failed; the folder was left in place, not deleted recursively") }
}
foreach ($v in 'empty', 'junction', 'file') {
    if ($cred) { Test-Precreated $v } else { Res "SL-13-precreated-folder-$v" 'UNPROVEN' 'no standard account' }
}
Remove-Item -Recurse -Force 'C:\ProgramData\EcosystemRunnerOther', 'C:\ProgramData\OtherApp', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OtherApp', $wowKey -ErrorAction SilentlyContinue

# ---- SL-7: step log from the real log.nsh, under two zones
if (Test-Path $footprintFolder) { Remove-Item -Recurse -Force $footprintFolder }
function Check-Log($tag) {
    $rc = Run-Exe $logh $null $null
    $file = Join-Path $footprintFolder 'steps.jsonl'
    if (-not (Test-Path $file)) { Note 'sl7.txt' @("$tag rc=$rc no steps.jsonl at $file"); return $false }
    $lines = @(Get-Content -LiteralPath $file)
    $ok = $lines.Count -eq 3
    try {
        $records = @($lines | ForEach-Object { ConvertFrom-Json -InputObject $_ -ErrorAction Stop })
        $ok = $ok -and $records[2].step -ceq 'A"B' -and $records[2].command -ceq 'A\Q'
    } catch { $ok = $false }
    Note 'sl7.txt' @("$tag rc=$rc lines=$($lines.Count) json_roundtrip=$ok tz=$(tzutil /g) bias=$((Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\TimeZoneInformation').ActiveTimeBias) utc_now=$([DateTime]::UtcNow.ToString('s'))") + $lines
    $key = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\TimeZoneInformation').TimeZoneKeyName
    foreach ($ln in $lines) { if ($ln -notmatch ('"zone": "' + [regex]::Escape($key) + '"')) { $ok = $false; $script:zoneMiss += "$tag expected zone '$key'; " } }
    foreach ($ln in $lines) {
        if ($ln -match '"started": "([0-9T:\-]+)\+00:00"') {
            $t = [DateTime]::ParseExact($Matches[1], 's', [Globalization.CultureInfo]::InvariantCulture)
            if ([Math]::Abs(([DateTime]::SpecifyKind($t, 'Utc') - [DateTime]::UtcNow).TotalSeconds) -gt 180) { $ok = $false }
        } else { $ok = $false }
    }
    Remove-Item -Recurse -Force $footprintFolder
    $ok
}
$zoneA = Check-Log 'zone-default'
tzutil /s 'W. Europe Standard Time'
$zoneB = Check-Log 'zone-weurope'
tzutil /s 'Pacific Standard Time'
$zoneC = Check-Log 'zone-pacific'
if ($zoneA -and $zoneB -and $zoneC) {
    Res 'SL-7a-steplog-path-utc' 'PASS' 'steps.jsonl at ProgramData\EcosystemRunner, UTC time within 180 s of Windows UTC under three zones'
} else { Res 'SL-7a-steplog-path-utc' 'FAIL' "default=$zoneA weurope=$zoneB pacific=$zoneC (see sl7.txt)" }
if ($zoneMiss -eq '') { Res 'SL-7b-zone-name-in-log' 'PASS' 'every step-log line of log.nsh names the PC zone (TimeZoneKeyName) under three zones' }
else { Res 'SL-7b-zone-name-in-log' 'FAIL' "log lines lack the zone name: $zoneMiss" }
$py = 'C:\Python311\python.exe'
if (Test-Path $py) {
    tzutil /s 'W. Europe Standard Time'
    $t = & $py -m unittest tests.test_installer_logs 2>&1 | Out-String
    $trc = $LASTEXITCODE
    Note 'sl7.txt' @("python tests.test_installer_logs (zone W. Europe) rc=$trc", ($t.Trim() -split "`n" | Select-Object -Last 40))
    $failed = @([regex]::Matches($t, '(?m)^(?:ERROR|FAIL): (\w+)') | ForEach-Object { $_.Groups[1].Value })
    $zoneFailed = @($failed | Where-Object { $_ -match 'display|hhmm' })
    $other = @($failed | Where-Object { $_ -notmatch 'display|hhmm' })
    if ($other.Count -eq 0) { Res 'SL-7c-secret-redaction' 'PASS' "log.py redaction tests pass under Windows Python 3.11 (display tests failing: $($zoneFailed -join ',')); log.nsh itself writes installer constants and never redacts" }
    else { Res 'SL-7c-secret-redaction' 'FAIL' "failing under Windows Python: $($other -join ',')" }
    # display time without tzdata: the PC's own zone converts, any other zone is refused
    function Get-Display { $o = & $py -m installer.guest.service_proof display 'Europe/Amsterdam' 2>&1 | Out-String; Note 'sl7.txt' @($o.Trim()); $o }
    $before = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'W. Europe Standard Time').ToString('HH:mm')
    $own = Get-Display
    $afterT = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'W. Europe Standard Time').ToString('HH:mm')
    tzutil /s 'Pacific Standard Time'
    $foreign = Get-Display
    $ownOk = ($own -match 'hhmm=(\d\d:\d\d)') -and (@($before, $afterT) -contains $Matches[1])
    $noData = $own -match 'zoneinfo=missing'
    $foreignRefused = $foreign -match 'error=UnknownZone'
    if ($ownOk -and (-not $noData -or $foreignRefused)) { Res 'SL-7d-display-time-zone' 'PASS' "own zone Europe/Amsterdam shown as the Windows local time ($before/$afterT); zoneinfo data present=$(-not $noData); other zone refused=$foreignRefused; display tests failing: $($zoneFailed -join ',')" }
    else { Res 'SL-7d-display-time-zone' 'FAIL' "own ok=$ownOk (expected $before/$afterT) zoneinfo missing=$noData foreign refused=$foreignRefused; display tests failing: $($zoneFailed -join ',')" }
} else { Res 'SL-7c-secret-redaction' 'UNPROVEN' 'no Python in the image to run log.py'; Res 'SL-7d-display-time-zone' 'UNPROVEN' 'no Python in the image' }
tzutil /s 'W. Europe Standard Time'


# Diagnostic (not a checklist item): the adapter's lock on a fresh folder before its service exists, with the raw icacls output
if (Test-Path $py) { [void](Invoke-Proof 'sl13.txt' @('lockdiag', 'EcosystemRunner', 'C:\ProgramData\EcosystemRunnerDiag')) }

# ---- SL-6b: rollback after an injected failed health check, with the real adapter and update.py
if ($stubOk) { [void](Invoke-Proof 'sl6b.txt' @('rollback', 'EcosystemRunnerG5R', 'C:\ProgramData\EcosystemRunnerG5R', $stub)) }
else { Res 'SL-6b-rollback-after-failed-health-check' 'UNPROVEN' 'the test service could not be compiled in the guest (csc.exe or .NET Framework missing, see stub.txt)' }

# ---- SL-5: local mode creates no service and no forge state
if (Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner') { sc.exe delete EcosystemRunner | Out-Null }
$pre = Get-Listing
$lrc = Run-Exe $localh $null $null
$post = Get-Listing
$d = Get-Diff $pre $post
$extra = @($d[0] | Where-Object { $_ -ne 'file C:\ProgramData\EcosystemRunnerG5R\probe.txt' })
$mode = ''
$modeFile = Join-Path $work 'local-mode.txt'
if (Test-Path $modeFile) { $mode = (Get-Content -LiteralPath $modeFile -Raw).Trim() }
Note 'sl5.txt' @("local harness rc=$lrc mode='$mode'", 'ADDED:', $d[0], 'REMOVED:', $d[1])
$svc = Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner'
$state = Test-Path $footprintFolder
if ($mode -eq 'local' -and -not $svc -and -not $state -and @($extra).Count -eq 0) { Res 'SL-5a-local-mode' 'PASS' 'mode local; no service, no EcosystemRunner folder or forge state added' }
else { Res 'SL-5a-local-mode' 'FAIL' "mode='$mode' service=$svc folder=$state other-added=$(@($extra) -join ';')" }
# ---- SL-5b/5c: the real adapter creates a test service under its virtual account; config.toml ACL; logon failure
$svcName = 'EcosystemRunnerG5'
$svcFolder = 'C:\ProgramData\EcosystemRunnerG5'
if ($stubOk) {
    [void](Invoke-Proof 'sl5b.txt' @('create5', $svcName, $svcFolder, $stub))
    if ($cred) {
        $cfg = Join-Path $svcFolder 'config.toml'
        $readScript = Join-Path $work 'stdread.cmd'
        Set-Content -LiteralPath $readScript -Encoding ascii -Value @('@echo off', "type `"$cfg`" > nul", 'echo read-config rc=%errorlevel%')
        $rrc = Run-AsStd $readScript ''
        $rout = if (Test-Path (Join-Path $work 'std-out.txt')) { Get-Content -LiteralPath (Join-Path $work 'std-out.txt') -Raw } else { '' }
        Note 'sl5b.txt' @("standard user reads config.toml (task rc=$rrc):", $rout.Trim())
        $rcm = [regex]::Match([string]$rout, 'read-config rc=(\d+)')
        $readRc = if ($rcm.Success) { [int]$rcm.Groups[1].Value } else { $null }
        if (($rrc -is [int]) -and ($null -ne $readRc) -and $readRc -ne 0) { Res 'SL-5b-config-denied-to-standard-user' 'PASS' 'a standard user cannot read config.toml' }
        elseif (($rrc -is [int]) -and ($readRc -eq 0)) { Res 'SL-5b-config-denied-to-standard-user' 'FAIL' 'a standard user can read config.toml' }
        else { Res 'SL-5b-config-denied-to-standard-user' 'UNPROVEN' "standard user could not be run (task rc=$rrc)" }
    }
    [void](Invoke-Proof 'sl5b.txt' @('cleanup5', $svcName, $svcFolder))
    $noLogon = 'g5nologon'
    $pw = ConvertTo-SecureString ('Aa1!' + [Guid]::NewGuid().ToString('N')) -AsPlainText -Force
    try {
        New-LocalUser -Name $noLogon -Password $pw -AccountNeverExpires | Out-Null
        [void](Invoke-Proof 'sl5c.txt' @('logon5', 'EcosystemRunnerG5L', 'C:\ProgramData\EcosystemRunnerG5L', $stub, $noLogon))
    } catch { Res 'SL-5c-logon-failure-error' 'UNPROVEN' "throw-away local account could not be created: $($_.Exception.Message)" }
    Remove-LocalUser -Name $noLogon -ErrorAction SilentlyContinue
} else {
    Res 'SL-5b-service-under-virtual-account' 'UNPROVEN' 'the test service could not be compiled in the guest (csc.exe or .NET Framework missing, see stub.txt)'
    Res 'SL-5c-logon-failure-error' 'UNPROVEN' 'depends on the test service'
}

Remove-LocalUser -Name $stdUser -ErrorAction SilentlyContinue
Write-Output (Get-Content -LiteralPath $results -Raw)
