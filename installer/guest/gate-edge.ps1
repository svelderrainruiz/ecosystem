# CTR-7 (#231): container-provable rows ported from gate-probes.ps1, against the VM kit's real installer.exe and pack.py's probes.
# Windows PowerShell 5.1, ASCII only. The wrapper prints out\*.txt; this driver writes one ROW per measurement and one verdict.
# KITOUT-1 (#210): state/log diagnostics are counts and booleans, not raw log or exception text that can contain profile paths.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$tree = (Get-Location).Path
$work = Join-Path $tree 'gate-work'
$out = Join-Path $tree 'out'
$report = Join-Path $out 'gate-edge.txt'
$rows = @('GATE-a-valid-keys-return', 'GATE-b-secret-on-command-line-32', 'GATE-d-unknown-key-31',
    'GATE-e-bad-choice-30', 'GATE-g-no-arguments-no-spin', 'GATE-i-L1-unpinned-pair-36')
$infoRows = @('PROBE-f-url-unquoted', 'PROBE-f-url-quoted', 'PROBE-P3-wordfind', 'PROBE-P4a', 'PROBE-P4b', 'PROBE-P4c',
    'PROBE-P4d', 'PROBE-P5-fileread')
$script:rowState = @{}
function Log([string]$line) { Add-Content -LiteralPath $report -Value $line -Encoding ascii }
function Note($file, $lines) { Add-Content -LiteralPath (Join-Path $out $file) -Value $lines -Encoding ascii }
function Res($id, $state, $detail) {
    if ($script:rowState.ContainsKey($id)) { throw 'duplicate row' }
    $script:rowState[$id] = $state
    Log "ROW $id $state $detail"
}
function Write-Verdict {
    foreach ($id in $rows) {
        if (-not $script:rowState.ContainsKey($id)) { Res $id 'FAIL' 'not measured: driver stopped before this row' }
    }
    foreach ($id in $infoRows) {
        if (-not $script:rowState.ContainsKey($id)) { Res $id 'INFO' 'not measured: driver stopped before this row' }
    }
    $failed = @($rows | Where-Object { $script:rowState[$_] -ne 'PASS' })
    if ($failed.Count -eq 0) { Log '[verdict] c-gate-edge PASS' }
    else { Log ('[verdict] c-gate-edge FAIL ' + ($failed -join ',')) }
}
function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Decode($name) {
    $src = Join-Path $tree ('installer\guest\payload\' + $name + '.b64')
    $dst = Join-Path $work $name
    [IO.File]::WriteAllBytes($dst, [Convert]::FromBase64String((Get-Content -LiteralPath $src -Raw)))
    $dst
}
function Start-Timed($exe, $argText, $limitSec) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe; $psi.Arguments = [string]$argText
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true; $psi.WorkingDirectory = $work
    $sw = [Diagnostics.Stopwatch]::StartNew()
    # A launch error stops the driver and is reported by type, never mistaken for a completed no-spin start.
    $p = [Diagnostics.Process]::Start($psi)
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

$sig = ('ab' * 32)
$installer = Join-Path $tree 'installer.exe'
$footprintFolder = 'C:\ProgramData\EcosystemRunner'
$uninstallKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner'
$serviceKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner'
$adminLocal = Join-Path $env:LOCALAPPDATA 'EcosystemInstaller'
$signerFile = Join-Path $adminLocal 'signer.sha256'
$userLogDir = Join-Path $env:APPDATA 'EcosystemRunner'
$stepLog = Join-Path $footprintFolder 'steps.jsonl'
$recFile = Join-Path $footprintFolder 'licence-record.json'
$imgKeys = '/MODE=local /IMAGE_VARIANT=windows /IMAGE_YEAR=2024 /NI_LICENCE_HELD=yes /ENGINE_LICENCE_ACCEPTED=yes'

function Clean-Gate {
    if (Test-Path $serviceKey) {
        sc.exe stop EcosystemRunner 2>&1 | Out-Null
        if ($LASTEXITCODE -notin @(0, 1062)) { throw 'service stop failed' }
        sc.exe delete EcosystemRunner 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'service delete failed' }
    }
    foreach ($p in $footprintFolder, $uninstallKey) {
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
    }
}
function Steps-All {
    if (Test-Path -LiteralPath $stepLog) { "steps.jsonl lines=$(@(Get-Content -LiteralPath $stepLog).Count)" } else { 'no steps.jsonl' }
}
function State-Gate {
    "folder=$(Test-Path $footprintFolder) key=$(Test-Path $uninstallKey) roaming-log-folder=$(Test-Path $userLogDir) log=[$(Steps-All)]"
}
function Run-Gate($exe, $argText, $tag) {
    Clean-Gate
    $r = Start-Timed $exe $argText 40
    $cpu = 'n/a'
    if (-not $r.Done) { $cpu = Cpu-Over $r.Proc 10; $r.Proc.Kill(); $r.Proc.WaitForExit() }
    $st = State-Gate
    Note 'gate.txt' @("[$tag] $(Split-Path $exe -Leaf) $argText", "  rc=$($r.Rc) after $($r.Sec) s; cpu over 10 s if it hung=$cpu; $st")
    [pscustomobject]@{ Rc = $r.Rc; Sec = $r.Sec; Hung = (-not $r.Done); Cpu = $cpu; State = $st }
}
function Gate-Many($id, $what, $expect, $argLists) {
    $seen = @(); $bad = @()
    foreach ($a in $argLists) {
        $r = Run-Gate $installer "/S /SIGNER=$sig $a" "$id $a"
        $seen += "[$a]=$($r.Rc)"
        if ($r.Hung -or "$($r.Rc)" -ne "$expect") { $bad += $a }
    }
    if ($bad.Count -eq 0) { Res $id 'PASS' "${what}: every start returned $expect $($seen -join ' ')" }
    else { Res $id 'FAIL' "${what}: expected $expect for all, got $($seen -join ' ')" }
}
function Footprint-Facts {
    "folder=$(Test-Path $footprintFolder) key=$(Test-Path $uninstallKey) uninstaller=$(Test-Path (Join-Path $footprintFolder 'uninstall.exe')) record=$(Test-Path $recFile) steps=[$(Steps-All)]"
}
function Nothing-Written { (-not (Test-Path $footprintFolder)) -and (-not (Test-Path $uninstallKey)) -and (-not (Test-Path $recFile)) }
function Uninstall-Poll {
    $u = Join-Path $footprintFolder 'uninstall.exe'
    if (-not (Test-Path -LiteralPath $u)) { return [pscustomobject]@{ Clean = $false; Text = 'no uninstall.exe' } }
    $urc = Run-Exe $u '/S'
    $t0 = Get-Date
    $svc = 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner'
    while (((Test-Path $footprintFolder) -or (Test-Path $uninstallKey) -or (Test-Path $svc)) -and (((Get-Date) - $t0).TotalSeconds -lt 90)) { Start-Sleep -Seconds 2 }
    $clean = -not ((Test-Path $footprintFolder) -or (Test-Path $uninstallKey) -or (Test-Path $svc))
    [pscustomobject]@{ Clean = $clean; Text = "uninstall.exe /S rc=$urc, footprint gone=$clean after $([Math]::Round(((Get-Date) - $t0).TotalSeconds, 0)) s" }
}
function Probe-Out($name) {
    $f = Join-Path $work $name
    if (-not (Test-Path $f)) { return '(no result file)' }
    $line = (Get-Content -LiteralPath $f -Raw).Trim()
    # Only the compiled probes' numeric measurements may leave the container.
    if ($line -notmatch '^(with E the loop ended at R8=\d+; without E the flag was (never|set at \d+) \(cap 50\)|characters read: \d+ of 1030)$') {
        return '(unrecognized probe result; withheld)'
    }
    $line
}
function Run-Probe($id, $exeName, $argText, $outName) {
    $exe = Decode $exeName
    $result = Join-Path $work $outName
    if (Test-Path -LiteralPath $result) { Remove-Item -LiteralPath $result }
    $r = Start-Timed $exe $argText 40
    if (-not $r.Done) { $r.Proc.Kill(); $r.Proc.WaitForExit() }
    $line = Probe-Out $outName
    Note 'probes-nsis.txt' @("[$id] $exeName $argText -> rc=$($r.Rc) after $($r.Sec) s; $line")
    Res "PROBE-$id" 'INFO' "$line; exit code $($r.Rc)"
}

$gateOk = $false
$signerMade = $false
$signerDirMade = $false
$driverFailed = $false
$phase = 'setup'
try {
    New-Item -ItemType Directory -Force -Path $work, $out | Out-Null
    foreach ($name in 'gate-edge.txt', 'gate.txt', 'licence.txt', 'probes-nsis.txt') {
        [IO.File]::WriteAllText((Join-Path $out $name), '')
    }
    if (-not (Test-Elevated)) { throw 'elevation required' }
    if ((Test-Path $footprintFolder) -or (Test-Path $uninstallKey) -or (Test-Path $serviceKey) -or (Test-Path $signerFile)) {
        throw 'pre-existing fixture refused'
    }
    $gateOk = $true
    $signerDirMade = -not (Test-Path $adminLocal)
    New-Item -ItemType Directory -Force -Path $adminLocal | Out-Null
    $signerMade = $true
    Set-Content -LiteralPath $signerFile -Value $sig -Encoding ascii

    # gate-probes.ps1:47-57 (a, b, d, e).
    $phase = 'a'
    $a1 = Run-Gate $installer "/S /SIGNER=$sig /MODE=local" 'a1 valid keys, minimal'
    $a2 = Run-Gate $installer "/S /SIGNER=$sig /MODE=local /PARTNER_ID=guest6b /LABVIEW_VERSION=2025" 'a2 valid keys, text keys'
    if ((-not $a1.Hung) -and "$($a1.Rc)" -eq '0' -and (-not $a2.Hung) -and "$($a2.Rc)" -eq '0') { Res 'GATE-a-valid-keys-return' 'PASS' "/S /MODE=local returned 0 in $($a1.Sec) s; $($a1.State); with the text keys too: rc=$($a2.Rc) in $($a2.Sec) s; $($a2.State)" }
    else { Res 'GATE-a-valid-keys-return' 'FAIL' "/S /MODE=local: rc=$($a1.Rc) hung=$($a1.Hung) after $($a1.Sec) s; $($a1.State); with the text keys too: rc=$($a2.Rc) hung=$($a2.Hung); $($a2.State)" }
    $phase = 'b-d-e'
    Gate-Many 'GATE-b-secret-on-command-line-32' 'a secret option on the command line' 32 @('/GITHUB_TOKEN=x', '/GITLAB_TOKEN=x', '/REGISTRY_PASSWORD=x', '/API_KEY=x')
    Gate-Many 'GATE-d-unknown-key-31' 'an unknown key' 31 @('/FOO=1', '/FOO')
    Gate-Many 'GATE-e-bad-choice-30' 'a bad value for a choice key' 30 @('/MODE=bogus', '/IMAGE_YEAR=1999', '/IMAGE_VARIANT=beos', '/MODE=')

    # gate-probes.ps1:58-68 (f).
    $phase = 'f'
    $url = 'https' + '://github.com/AcmeOrg/Repo'
    foreach ($v in @(@('unquoted', "/GITHUB_URL=$url"), @('quoted', "/GITHUB_URL=`"$url`""))) {
        $r = Run-Gate $installer "/S /SIGNER=$sig $($v[1])" "f $($v[0]) url"
        $files = @()
        foreach ($d in $footprintFolder, $adminLocal) { if (Test-Path $d) { $files += @(Get-ChildItem -LiteralPath $d -Recurse -File -Force) } }
        $mixed = @($files | Select-String -SimpleMatch -CaseSensitive -Pattern 'AcmeOrg').Count
        $lower = @($files | Select-String -SimpleMatch -CaseSensitive -Pattern 'acmeorg').Count
        Res "PROBE-f-url-$($v[0])" 'INFO' "rc=$($r.Rc) in $($r.Sec) s; $($r.State); files holding the url text: original case=$mixed, lower case=$lower (0 and 0 = checked, not kept)"
    }

    # gate-probes.ps1:69-79 (g).
    $phase = 'g'
    Clean-Gate
    $g = Start-Timed $installer '' 5
    if ($g.Done) { Res 'GATE-g-no-arguments-no-spin' 'PASS' "returned rc=$($g.Rc) after $($g.Sec) s without spinning (no desktop in this guest)" }
    else {
        $gcpu = Cpu-Over $g.Proc 10
        $g.Proc.Kill()
        $g.Proc.WaitForExit()
        if ($gcpu -lt 2) { Res 'GATE-g-no-arguments-no-spin' 'PASS' "waits without spinning: CPU time over 10 s = $gcpu s (killed afterwards)" }
        else { Res 'GATE-g-no-arguments-no-spin' 'FAIL' "SPINS: CPU time over 10 s = $gcpu s" }
    }
    Note 'gate.txt' @("[g] no arguments: $(State-Gate)")

    # gate-probes.ps1:174-186 (L1); record contents are not needed to judge the footprint shape.
    $phase = 'L1'
    $l1 = Run-Gate $installer "/S /SIGNER=$sig $imgKeys" 'L1 release build, windows 2024, both answers yes'
    $l1facts = Footprint-Facts
    $l1none = Nothing-Written
    $l1full = (Test-Path $footprintFolder) -and (Test-Path $uninstallKey) -and (Test-Path $recFile)
    $l1un = $null
    if (Test-Path -LiteralPath (Join-Path $footprintFolder 'uninstall.exe')) { $l1un = Uninstall-Poll }
    $l1shape = if ($l1none) { 'nothing written' } elseif ($l1full) { 'install complete with the record written' } else { 'partial state' }
    Note 'licence.txt' @("[L1] release build: rc=$($l1.Rc) in $($l1.Sec) s; $l1shape; $l1facts; run-gate state: $($l1.State); uninstall: $(if ($null -ne $l1un) { $l1un.Text } else { 'none (no uninstaller)' })")
    if ((-not $l1.Hung) -and "$($l1.Rc)" -eq '36' -and $l1shape -ne 'partial state') { Res 'GATE-i-L1-unpinned-pair-36' 'PASS' "release build: rc=36 in $($l1.Sec) s; observed: $l1shape; $l1facts; $($l1.State)" }
    else { Res 'GATE-i-L1-unpinned-pair-36' 'FAIL' "release build: rc=$($l1.Rc) hung=$($l1.Hung) in $($l1.Sec) s; observed: $l1shape; $l1facts; $($l1.State)" }
    Clean-Gate

    # gate-probes.ps1:268-277.
    $phase = 'probes'
    Run-Probe 'P3-wordfind' 'probe-p3.exe' '' 'probe-p3.txt'
    $p4 = Decode 'probe-p4.exe'
    $p4names = @{ a = 'Quit in .onInit'; b = 'Quit in a section'; c = 'Abort in a section'; d = 'Quit in a function called from a section' }
    foreach ($k in 'a', 'b', 'c', 'd') {
        $r = Start-Timed $p4 "/$k" 40
        if (-not $r.Done) { $r.Proc.Kill(); $r.Proc.WaitForExit() }
        Res "PROBE-P4$k" 'INFO' "SetErrorLevel 35 then $($p4names[$k]): exit code $($r.Rc)"
    }
    Set-Content -LiteralPath (Join-Path $work 'p5-in.txt') -Value ('x' * 1030) -Encoding ascii
    Run-Probe 'P5-fileread' 'probe-p5.exe' '' 'probe-p5.txt'
} catch {
    Note 'gate.txt' @("driver error phase=$phase type=$($_.Exception.GetType().Name)")
    $driverFailed = $true
} finally {
    try {
        if ($gateOk) { Clean-Gate }
        if ($signerMade -and (Test-Path $signerFile)) { Remove-Item -LiteralPath $signerFile -Force }
        if ($signerDirMade) { Remove-Item -LiteralPath $adminLocal -Force }
    } catch {
        Note 'gate.txt' @("cleanup error type=$($_.Exception.GetType().Name)")
        $driverFailed = $true
    }
    Write-Verdict
}
if ($driverFailed) { exit 1 }
exit 0
