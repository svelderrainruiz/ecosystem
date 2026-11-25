# CTR-8 (#234): source assertions from guest-proof.ps1, against the VM kit's real installer.exe.
# SL-3 is deferred to #238; SL-7 needs the pack's log harness, not a substitute installer.
# KITOUT-1 (#210): counts, booleans, exit codes and exception types only; no raw native output or log records.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$tree = (Get-Location).Path
$work = Join-Path $tree 'install-work'
$out = Join-Path $tree 'out'
$report = Join-Path $out 'install-edge.txt'
$rows = @('GUEST6B-first-silent-start', 'SL-3', 'SL-13-upgrade-run', 'SL-13-uninstall-removes-whole-folder',
    'SL-7a-steplog-path-utc', 'SL-7b-zone-name-in-log', 'A-M0-residue', 'B-registered-strings',
    'B2-uninstall-no-underscore', 'B2-uninstall-with-underscore')
$script:rowState = @{}
$script:unmeasured = 'not measured: driver stopped before this row'
$script:driverFailed = $false
function Log([string]$line) { Add-Content -LiteralPath $report -Value $line -Encoding ascii }
function Res($id, $state, $detail) {
    if ($script:rowState.ContainsKey($id)) { throw 'duplicate row' }
    $script:rowState[$id] = $state
    Log "ROW $id $state $detail"
}
function Write-Verdict {
    foreach ($id in $rows) {
        if (-not $script:rowState.ContainsKey($id)) { Res $id 'FAIL' $script:unmeasured }
    }
    $failed = @($rows | Where-Object { $script:rowState[$_] -ne 'PASS' })
    if ($script:driverFailed) { $failed += 'driver-or-cleanup' }
    if ($failed.Count -eq 0) { Log '[verdict] c-install-edge PASS' }
    else { Log ('[verdict] c-install-edge FAIL ' + ($failed -join ',')) }
}
function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Start-Timed($exe, $argText, $limitSec) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe; $psi.Arguments = [string]$argText
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true; $psi.WorkingDirectory = $work
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = [Diagnostics.Process]::Start($psi)
    # Drain both streams concurrently; neither stream is evidence safe to print.
    [void]$p.StandardOutput.ReadToEndAsync()
    [void]$p.StandardError.ReadToEndAsync()
    $done = $p.WaitForExit($limitSec * 1000)
    $rc = if ($done) { $p.ExitCode } else { 'timeout' }
    [pscustomobject]@{ Proc = $p; Done = $done; Rc = $rc; Sec = [Math]::Round($sw.Elapsed.TotalSeconds, 1) }
}
function Cpu-Over($p, $sec) {
    $a = $p.TotalProcessorTime.TotalSeconds
    Start-Sleep -Seconds $sec
    $p.Refresh()
    [Math]::Round($p.TotalProcessorTime.TotalSeconds - $a, 2)
}
function Run-Exe($exe, $argText) {
    $r = Start-Timed $exe $argText 120
    if (-not $r.Done) { $r.Proc.Kill(); $r.Proc.WaitForExit() }
    $r.Rc
}
function Tool-Rc($name, $argText) { Run-Exe (Join-Path $env:windir ('System32\' + $name)) $argText }
function Service-Sid([string]$name) {
    $sha = [Security.Cryptography.SHA1]::Create()
    try {
        $d = $sha.ComputeHash([Text.Encoding]::Unicode.GetBytes($name.ToUpperInvariant()))
        'S-1-5-80-' + ((0..4 | ForEach-Object { [BitConverter]::ToUInt32($d, $_ * 4) }) -join '-')
    } finally { $sha.Dispose() }
}

$sig = ('ab' * 32)
$installer = Join-Path $tree 'installer.exe'
$footprintFolder = 'C:\ProgramData\EcosystemRunner'
$programDir = Join-Path $footprintFolder 'program'
$uninstallExe = Join-Path $footprintFolder 'uninstall.exe'
$uninstallKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner'
$serviceKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner'
$signerDir = Join-Path $env:LOCALAPPDATA 'EcosystemInstaller'
$signerFile = Join-Path $signerDir 'signer.sha256'
$stub = Join-Path $work 'stub\stub.exe'

function Clean-Product {
    if (Test-Path $serviceKey) {
        $stop = Tool-Rc 'sc.exe' 'stop EcosystemRunner'
        if ("$stop" -notin @('0', '1062')) { throw 'service stop failed' }
        Start-Sleep -Seconds 3
        $delete = Tool-Rc 'sc.exe' 'delete EcosystemRunner'
        if ("$delete" -ne '0') { throw 'service delete failed' }
    }
    foreach ($p in $footprintFolder, $uninstallKey) {
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
    }
}
# Same service preparation as uninstall-edge.ps1, replacing guest-proof's Python install helper.
function Install-Stub {
    New-Item -ItemType Directory -Force -Path $programDir | Out-Null
    Copy-Item -LiteralPath $stub -Destination (Join-Path $programDir 'runner.exe') -Force
    $create = Tool-Rc 'sc.exe' ('create EcosystemRunner binPath= \"' + $footprintFolder + '\program\runner.exe\" obj= "NT SERVICE\EcosystemRunner" start= auto')
    if ("$create" -ne '0') { Log "stub create=$create"; return $false }
    $sidtype = Tool-Rc 'sc.exe' 'sidtype EcosystemRunner unrestricted'
    $grant = Tool-Rc 'icacls.exe' ('"' + $footprintFolder + '" /grant:r *' + (Service-Sid 'EcosystemRunner') + ':(OI)(CI)RX')
    $start = Tool-Rc 'sc.exe' 'start EcosystemRunner'
    $running = $false
    if ("$sidtype" -eq '0' -and "$grant" -eq '0' -and "$start" -in @('0', '1056')) {
        for ($i = 0; $i -lt 30; $i++) {
            $svc = Get-Service -Name EcosystemRunner
            if ($svc.Status -eq 'Running') { $running = $true; break }
            Start-Sleep -Seconds 1
        }
    }
    Log "stub create=$create sidtype=$sidtype grant=$grant start=$start running=$running"
    if (-not $running) {
        [void](Tool-Rc 'sc.exe' 'stop EcosystemRunner')
        Start-Sleep -Seconds 2
        $delete = Tool-Rc 'sc.exe' 'delete EcosystemRunner'
        if ("$delete" -ne '0') { throw 'stub cleanup failed' }
    }
    $running
}
function Set-Zone($name) {
    $rc = Tool-Rc 'tzutil.exe' ('/s "' + $name + '"')
    if ("$rc" -ne '0') { throw 'zone change failed' }
}
function Check-Log($tag) {
    $rc = Run-Exe $logh $null
    $file = Join-Path $footprintFolder 'steps.jsonl'
    if (-not (Test-Path $file)) {
        Log "$tag rc=$rc log_present=False"
        return $false
    }
    $lines = @(Get-Content -LiteralPath $file)
    $ok = $lines.Count -eq 3
    try {
        $records = @($lines | ForEach-Object { ConvertFrom-Json -InputObject $_ -ErrorAction Stop })
        $ok = $ok -and $records[2].step -ceq 'A"B' -and $records[2].command -ceq 'A\Q'
    } catch { Log "$tag json_error=$($_.Exception.GetType().Name)"; $ok = $false }
    $key = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\TimeZoneInformation').TimeZoneKeyName
    foreach ($ln in $lines) {
        if ($ln -notmatch ('"zone": "' + [regex]::Escape($key) + '"')) { $ok = $false; $script:zoneMiss += 1 }
    }
    foreach ($ln in $lines) {
        if ($ln -match '"started": "([0-9T:\-]+)\+00:00"') {
            $t = [DateTime]::ParseExact($Matches[1], 's', [Globalization.CultureInfo]::InvariantCulture)
            if ([Math]::Abs(([DateTime]::SpecifyKind($t, 'Utc') - [DateTime]::UtcNow).TotalSeconds) -gt 180) { $ok = $false }
        } else { $ok = $false }
    }
    if ($lines.Count -eq 3) { $script:zoneRuns += 1 }
    Log "$tag rc=$rc lines=$($lines.Count) valid=$ok zone_misses=$script:zoneMiss"
    Remove-Item -Recurse -Force $footprintFolder
    $ok
}

$gateOk = $false
$workMade = $false
$signerMade = $false
$signerDirMade = $false
$zoneChanged = $false
$originalZone = $null
$phase = 'gate'
try {
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    [IO.File]::WriteAllText($report, '')
    if ((Test-Path $footprintFolder) -or (Test-Path $uninstallKey) -or (Test-Path $serviceKey)) {
        $script:unmeasured = 'refused: product folder, uninstall key or service existed before the run; nothing touched'
        throw 'pre-existing product state'
    }
    if ((Test-Path $signerFile) -or (Test-Path $work)) {
        $script:unmeasured = 'refused: signer file or case work folder existed before the run; nothing touched'
        throw 'pre-existing fixture'
    }
    if (-not (Test-Elevated)) {
        $script:unmeasured = 'refused: elevation required; nothing touched'
        throw 'not elevated'
    }
    $gateOk = $true
    New-Item -ItemType Directory -Path $work | Out-Null
    $workMade = $true

    Res 'SL-3' 'NOT-PORTED' 'unproven in a container; see #238'
    # probes.ps1:1-5 defines every probe as INFO, even on unexpected state. No source pass rule may be invented here.
    Res 'A-M0-residue' 'NOT-PORTED' 'source is INFO only; boolean ACL residue after grants has no source PASS rule; no grant evidence claimed'
    Res 'B-registered-strings' 'NOT-PORTED' 'source is INFO only; registered-string observations have no source PASS rule'
    Res 'B2-uninstall-no-underscore' 'NOT-PORTED' 'source is INFO only; exit and 60 s folder observations have no source PASS rule'
    Res 'B2-uninstall-with-underscore' 'NOT-PORTED' 'source is INFO only; in-place exit and state observations have no source PASS rule'

    # guest-proof.ps1:170-183: the first launch has no stored signer.
    $phase = 'first-start'
    $skipProduct = $false
    $ff = Start-Timed $installer "/S /SIGNER=$sig" 40
    if ($ff.Done -and $ff.Rc -is [int]) { Res 'GUEST6B-first-silent-start' 'PASS' "rc=$($ff.Rc) seconds=$($ff.Sec) limit=40" }
    elseif ($ff.Done) { Res 'GUEST6B-first-silent-start' 'FAIL' 'no integer exit'; $skipProduct = $true }
    else {
        $cpu = Cpu-Over $ff.Proc 10
        $ff.Proc.Kill()
        $ff.Proc.WaitForExit()
        Res 'GUEST6B-first-silent-start' 'FAIL' "timeout=True seconds=$($ff.Sec) cpu_seconds_over_10=$cpu"
        $skipProduct = $true
    }
    if ($skipProduct) { $script:unmeasured = 'not measured: first silent start failed' }

    if (-not $skipProduct) {
        Clean-Product
        $phase = 'install'
        $signerDirMade = -not (Test-Path $signerDir)
        New-Item -ItemType Directory -Force -Path $signerDir | Out-Null
        $signerMade = $true
        Set-Content -LiteralPath $signerFile -Value $sig -Encoding ascii
        $irc = Run-Exe $installer "/S /SIGNER=$sig"
        Log "install rc=$irc uninstaller=$(Test-Path $uninstallExe)"
        if ("$irc" -ne '0' -or -not (Test-Path $uninstallExe)) { throw 'install precondition failed' }
        New-Item -ItemType Directory -Force -Path (Split-Path $stub), $programDir | Out-Null
        $csc = Join-Path $env:windir 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
        $cscRc = Run-Exe $csc ('/nologo /target:exe /out:"' + $stub + '" /r:System.ServiceProcess.dll "' + (Join-Path $tree 'installer\guest\stub-service.cs') + '"')
        if ("$cscRc" -ne '0' -or -not (Test-Path $stub)) { throw 'stub compile failed' }
        Copy-Item -LiteralPath $stub -Destination (Join-Path $programDir 'runner.exe') -Force

        # guest-proof.ps1:323-331: old inherited-folder setup, but only the numeric reinstall exit is asserted.
        $phase = 'upgrade'
        $reset = Tool-Rc 'icacls.exe' ('"' + $footprintFolder + '" /reset')
        if ("$reset" -ne '0') { throw 'upgrade fixture reset failed' }
        $upRc = Run-Exe $installer "/S /SIGNER=$sig"
        $upRan = "$upRc" -match '^-?\d+$'
        Res 'SL-13-upgrade-run' $(if ($upRan -and "$upRc" -eq '0') { 'PASS' } else { 'FAIL' }) "rc=$upRc expected=0; numeric exit only, not ACL evidence"

        # guest-proof.ps1:355-366,381-383: establish the service and executable before the default uninstall.
        $phase = 'whole-folder'
        $hadUninstaller = Test-Path $uninstallExe
        $svcMade = $false
        if ($hadUninstaller) { $svcMade = Install-Stub }
        $unRc = Run-Exe $uninstallExe '/S'
        for ($i = 0; $i -lt 90; $i++) {
            if (-not (Test-Path $footprintFolder) -and -not (Test-Path $uninstallKey) -and -not (Test-Path $serviceKey)) { break }
            Start-Sleep -Seconds 1
        }
        $folderGone = -not (Test-Path $footprintFolder)
        $facts = "rc=$unRc service_created=$svcMade uninstaller_present_before=$hadUninstaller folder_removed=$folderGone program_present=$(Test-Path $programDir)"
        if (-not $svcMade -or -not $hadUninstaller) { Res 'SL-13-uninstall-removes-whole-folder' 'FAIL' "precondition not met; $facts" }
        elseif ((Test-Path $programDir) -eq $false -and $folderGone) { Res 'SL-13-uninstall-removes-whole-folder' 'PASS' $facts }
        else { Res 'SL-13-uninstall-removes-whole-folder' 'FAIL' $facts }
        Clean-Product

        # guest-proof.ps1:590-617: pack's unchanged log.nsh harness, in three zones, with a 180 s UTC bound.
        $phase = 'logs'
        $logh = Join-Path $work 'log-harness.exe'
        $src = Join-Path $tree 'installer\guest\payload\log-harness.exe.b64'
        [IO.File]::WriteAllBytes($logh, [Convert]::FromBase64String((Get-Content -LiteralPath $src -Raw)))
        $originalZone = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\TimeZoneInformation').TimeZoneKeyName
        $script:zoneMiss = 0
        $script:zoneRuns = 0
        $zoneA = Check-Log 'zone-default'
        $zoneChanged = $true
        Set-Zone 'W. Europe Standard Time'
        $zoneB = Check-Log 'zone-weurope'
        Set-Zone 'Pacific Standard Time'
        $zoneC = Check-Log 'zone-pacific'
        $facts = "default=$zoneA weurope=$zoneB pacific=$zoneC utc_limit_seconds=180 log=steps.jsonl; log harness only"
        if ($zoneA -and $zoneB -and $zoneC) { Res 'SL-7a-steplog-path-utc' 'PASS' $facts }
        else { Res 'SL-7a-steplog-path-utc' 'FAIL' $facts }
        # A missing/empty log is not evidence that every zone field matched.
        $facts = "zone_misses=$script:zoneMiss measured_zones=$script:zoneRuns expected_zones=3; log harness only"
        if ($script:zoneMiss -eq 0 -and $script:zoneRuns -eq 3) { Res 'SL-7b-zone-name-in-log' 'PASS' $facts }
        else { Res 'SL-7b-zone-name-in-log' 'FAIL' $facts }
    }
} catch {
    Log "driver error phase=$phase type=$($_.Exception.GetType().Name)"
    $script:driverFailed = $true
} finally {
    foreach ($cleanup in @(
        { if ($zoneChanged) { Set-Zone $originalZone } },
        { if ($gateOk) { Clean-Product } },
        { if ($signerMade -and (Test-Path $signerFile)) { Remove-Item -LiteralPath $signerFile -Force } },
        { if ($signerDirMade -and (Test-Path $signerDir)) { Remove-Item -LiteralPath $signerDir -Force } },
        { if ($workMade) { Remove-Item -LiteralPath $work -Recurse -Force } }
    )) {
        try { & $cleanup }
        catch { Log "cleanup error type=$($_.Exception.GetType().Name)"; $script:driverFailed = $true }
    }
    Write-Verdict
}
if ($script:driverFailed) { exit 1 }
exit 0
