# CTR-6 (ecosystem-control#227): the ten SL-6c rows that installer\guest\CHECKLIST.md classifies container-provable, measured against the REAL
# installer.exe (the VM kit's, copied by the container case to the tree root). Ported from guest-proof.ps1:403-539 with the same steps and pass
# conditions; guest-proof.ps1 itself stays laptop-refused (it creates a directory link). This driver creates no link, uses no network, needs no
# standard user and no desktop. One Python step of guest-proof.ps1 is ported to PowerShell because the container has no Python: the stub
# service install (service_proof.py install -> winsys.install_service). Runs elevated from the tree root (C:\w), Windows
# PowerShell 5.1, ASCII only. Writes out\uninstall-edge.txt (one ROW line per row, one [verdict] line) and out\sl6c.txt (the
# evidence notes). Output rule #210 KITOUT-1: SIDs only, never an account name; no path but names inside the product folder. Exit 0 whenever
# the verdict line is written; the case script judges that line.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$tree = (Get-Location).Path
$work = 'C:\X\ctr6'
$out = Join-Path $tree 'out'
New-Item -ItemType Directory -Force -Path $work, $out | Out-Null
$report = Join-Path $out 'uninstall-edge.txt'
$notes = Join-Path $out 'sl6c.txt'
[IO.File]::WriteAllText($report, '')
[IO.File]::WriteAllText($notes, '')
function Log([string]$line) { Add-Content -LiteralPath $report -Value $line -Encoding ascii }
function Note([string]$line) { Add-Content -LiteralPath $notes -Value $line -Encoding ascii }

$rows = @('SL-6c-leftover-default-launch', 'SL-6c-leftover-keeps-uninstaller', 'SL-6c-run-twice-after-release', 'SL-6c-readonly-file-removed',
    'SL-6c-leftover-exit-40', 'SL-6c-in-place-after-release', 'SL-6c-clean-in-place', 'SL-6c-clean-default', 'SL-6c-empty-folder-edge',
    'SL-6c-service-running-uninstall')
$script:rowState = @{}
# guest-proof.ps1 writes PASS, FAIL or UNPROVEN; here UNPROVEN prints as FAIL (it is not a pass) with the reason kept.
function Res6c($id, $state, $detail) {
    if ($script:rowState.ContainsKey($id)) { return }
    $script:rowState[$id] = $state
    if ($state -eq 'PASS') { Log "ROW $id PASS $detail" }
    elseif ($state -eq 'FAIL') { Log "ROW $id FAIL $detail" }
    else { Log "ROW $id FAIL unproven: $detail" }
}
function Ok6c($cond, $id, $okText, $badText) { if ($cond) { Res6c $id 'PASS' $okText } else { Res6c $id 'FAIL' $badText } }
function Write-Verdict {
    foreach ($id in $rows) { if (-not $script:rowState.ContainsKey($id)) { Res6c $id 'UNPROVEN' 'no result: the driver stopped before this row (see sl6c.txt)' } }
    $failed = @($rows | Where-Object { $script:rowState[$_] -ne 'PASS' })
    if ($failed.Count -eq 0) { Log '[verdict] c-uninstall-edge PASS' }
    else { Log ('[verdict] c-uninstall-edge FAIL ' + ($failed -join ',')) }
}

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# guest-proof.ps1 Run-Exe without the standard-user credential; a start failure reports the exception type only (its message can hold a path).
function Run-Exe($exe, $argText) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = [string]$argText
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $work
    try {
        $p = [Diagnostics.Process]::Start($psi)
        if (-not $p.WaitForExit(120000)) { $p.Kill(); return 'timeout' }
        return $p.ExitCode
    } catch { return ('error: ' + $_.Exception.GetType().Name) }
}

# A system tool with a fixed argument text; its output is read and dropped (sc.exe qc and icacls print account names), only the exit code is kept.
function Tool-Rc([string]$name, [string]$argText) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = Join-Path $env:windir ('System32\' + $name)
    $psi.Arguments = $argText
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    try {
        $p = [Diagnostics.Process]::Start($psi)
        [void]$p.StandardOutput.ReadToEnd()
        [void]$p.StandardError.ReadToEnd()
        if (-not $p.WaitForExit(120000)) { $p.Kill(); return 'timeout' }
        return $p.ExitCode
    } catch { return ('error: ' + $_.Exception.GetType().Name) }
}

# winsys.service_sid: the SID of the service's virtual account, from the SHA-1 of the upper-case name (no name lookup).
function Service-Sid([string]$name) {
    $sha = [Security.Cryptography.SHA1]::Create()
    $d = $sha.ComputeHash([Text.Encoding]::Unicode.GetBytes($name.ToUpperInvariant()))
    'S-1-5-80-' + ((0..4 | ForEach-Object { [BitConverter]::ToUInt32($d, $_ * 4) }) -join '-')
}

$sig = ('ab' * 32)
$footprintFolder = 'C:\ProgramData\EcosystemRunner'
$uninstallKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner'
$uninstallExe = Join-Path $footprintFolder 'uninstall.exe'
$installer = Join-Path $tree 'installer.exe'
$stub = Join-Path $work 'stub\stub.exe'
$signerDir = Join-Path $env:LOCALAPPDATA 'EcosystemInstaller'
$signerFile = Join-Path $signerDir 'signer.sha256'
$script:gateOk = $false
$script:signerMade = $false
$script:signerDirMade = $false
$script:holder = $null

function Svc-Up { Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner' }
function Svc-Running { [bool]((& sc.exe query EcosystemRunner 2>&1 | Out-String) -match 'RUNNING') }
function State-6c { "folder=$(Test-Path $footprintFolder) service=$(Svc-Up) key=$(Test-Path $uninstallKey)" }
function Wait-6c($until) { for ($i = 0; $i -lt 90; $i++) { if (& $until) { return $true }; Start-Sleep -Seconds 1 }; return $false }
function Names-6c { if (Test-Path $footprintFolder) { (@(Get-ChildItem -LiteralPath $footprintFolder -Force -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }) -join ',') } else { '(no folder)' } }
function Exe-Kept { Test-Path $uninstallExe }

# service_proof.py install (prepare + winsys.install_service): the stub becomes program\runner.exe, the service runs it under its own virtual
# account, the service SID gets read and execute on the folder, then the service starts; a failed step removes the half-made service.
function Install-Stub {
    $prog = Join-Path $footprintFolder 'program'
    New-Item -ItemType Directory -Force -Path $prog | Out-Null
    Copy-Item -LiteralPath $stub -Destination (Join-Path $prog 'runner.exe') -Force
    $create = Tool-Rc 'sc.exe' ('create EcosystemRunner binPath= \"' + $footprintFolder + '\program\runner.exe\" obj= "NT SERVICE\EcosystemRunner" start= auto')
    if ("$create" -ne '0') { Note "stub service: sc create rc=$create"; return }
    $sidtype = Tool-Rc 'sc.exe' 'sidtype EcosystemRunner unrestricted'
    $grant = Tool-Rc 'icacls.exe' ('"' + $footprintFolder + '" /grant:r *' + (Service-Sid 'EcosystemRunner') + ':(OI)(CI)RX')
    $start = Tool-Rc 'sc.exe' 'start EcosystemRunner'
    $up = $false
    if (("$sidtype" -eq '0') -and ("$grant" -eq '0') -and ("$start" -in @('0', '1056'))) {
        for ($i = 0; $i -lt 30; $i++) { if (Svc-Running) { $up = $true; break }; Start-Sleep -Seconds 1 }
    }
    Note "stub service: create=$create sidtype=$sidtype grant=$grant start=$start running=$up"
    if (-not $up) { [void](Tool-Rc 'sc.exe' 'stop EcosystemRunner'); Start-Sleep -Seconds 2; [void](Tool-Rc 'sc.exe' 'delete EcosystemRunner') }
}
function Install-6c {
    $rc = Run-Exe $installer "/S /SIGNER=$sig"
    $made = $false
    if ($stubOk -and $rc -eq 0 -and (Test-Path $uninstallExe)) {
        Install-Stub
        $made = (Svc-Up) -and (Svc-Running)
    }
    Note "install: rc=$rc service running=$made $(State-6c)"
    return $made
}
function Clean-6c {
    if (Svc-Up) { & sc.exe stop EcosystemRunner 2>&1 | Out-Null; Start-Sleep -Seconds 3; & sc.exe delete EcosystemRunner 2>&1 | Out-Null }
    Remove-Item -LiteralPath $footprintFolder -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $uninstallKey -Recurse -Force -ErrorAction SilentlyContinue
}
# The SL-6c-empty-folder-edge holder: a headless process whose current directory is the product folder. guest-proof.ps1 uses cmd.exe with a
# ping loop as the timer; this uses powershell.exe Start-Sleep, so no network tool runs. The folder is held the same way: as a current directory.
function Start-Holder {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = Join-Path $env:windir 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $psi.Arguments = '-NoProfile -NonInteractive -Command Start-Sleep -Seconds 400'
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $footprintFolder
    try { $script:holder = [Diagnostics.Process]::Start($psi) } catch { $script:holder = $null }
}
function Stop-Holder {
    if ($null -ne $script:holder) {
        try { $script:holder.Kill() } catch { }
        try { [void]$script:holder.WaitForExit(5000) } catch { }
    }
    $script:holder = $null
}

$phase = 'setup'
try {
    $build = try { $cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'; "$($cv.CurrentBuild).$($cv.UBR)" } catch { 'unknown' }
    Note "env: build=$build elevated=$(Test-Elevated) user_sid=$([Security.Principal.WindowsIdentity]::GetCurrent().User.Value) installer_present=$(Test-Path $installer)"
    # Ownership gate: product state that this run did not make is never touched.
    $phase = 'gate'
    if ((Test-Path $footprintFolder) -or (Test-Path $uninstallKey) -or (Svc-Up)) {
        Note "gate: refused, product state existed before the run: $(State-6c); nothing was touched"
        foreach ($id in $rows) { Res6c $id 'UNPROVEN' 'refused: product folder, uninstall key or service existed before the run' }
    } else {
        $script:gateOk = $true
        # A silent run exits 3 until the signer has been confirmed once (trust.nsh); guest-proof.ps1 stores it during SL-4b, this run stores it here.
        $phase = 'signer'
        if (-not (Test-Path -LiteralPath $signerFile)) {
            if (-not (Test-Path -LiteralPath $signerDir)) { New-Item -ItemType Directory -Force -Path $signerDir | Out-Null; $script:signerDirMade = $true }
            [IO.File]::WriteAllText($signerFile, ($sig + "`n"), [Text.Encoding]::ASCII)
            $script:signerMade = $true
        }
        # harmless test service, compiled here from installer\guest\stub-service.cs (no binary is committed)
        $phase = 'stub'
        New-Item -ItemType Directory -Force -Path (Split-Path $stub) | Out-Null
        $csc = Join-Path $env:windir 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
        $cscRc = 'absent'
        if (Test-Path $csc) {
            & $csc /nologo /target:exe "/out:$stub" /r:System.ServiceProcess.dll (Join-Path $tree 'installer\guest\stub-service.cs') 2>&1 | Out-Null
            $cscRc = $LASTEXITCODE
        }
        $stubOk = Test-Path $stub
        Note "stub: csc=$cscRc stub=$stubOk"

        # ---- SL-6c (guest-proof.ps1:403-539): a default start (no _?=) copies the uninstaller to TEMP and the first process returns 0 at once,
        # so those rows are judged by state: service, folder, key.
        # leftover: a file held open inside the folder (contract of PR 96 round UNINSTC: uninstall.exe goes last)
        $phase = 'leftover'
        Clean-6c
        if (Install-6c) {
            $held = Join-Path $footprintFolder 'held.txt'
            $ro = Join-Path $footprintFolder 'readonly.txt'
            Set-Content -LiteralPath $ro -Value 'ro' -Encoding ascii
            Set-ItemProperty -LiteralPath $ro -Name IsReadOnly -Value $true
            $fs = [IO.File]::Open($held, 'OpenOrCreate', 'ReadWrite', 'None')
            try {
                $rc1 = Run-Exe $uninstallExe '/S'
                $svcGone1 = Wait-6c { -not (Svc-Up) }
                Start-Sleep -Seconds 30
                $s1 = State-6c
                $exe1 = Exe-Kept
                Note "1 leftover, default launch: process rc=$rc1 service gone=$svcGone1; 30 s later: $s1 uninstall.exe present=$exe1 files=$(Names-6c)"
                if ($rc1 -isnot [int]) { Res6c 'SL-6c-leftover-default-launch' 'UNPROVEN' "the uninstaller did not run: $rc1" }
                else { Ok6c ($svcGone1 -and $s1 -eq 'folder=True service=False key=True') 'SL-6c-leftover-default-launch' "held file: service removed, folder and uninstall key kept ($s1)" "held file: expected folder=True service=False key=True, got $s1 (service gone=$svcGone1)" }
                Ok6c $exe1 'SL-6c-leftover-keeps-uninstaller' 'after a leftover uninstall.exe is still in the folder and the key is kept' "after a leftover uninstall.exe is gone from the folder ($s1), so the key points at nothing"
            } finally { $fs.Dispose() }
            if (Test-Path $uninstallExe) {
                $rc3 = Run-Exe $uninstallExe '/S'
                $gone3 = Wait-6c { -not (Test-Path $footprintFolder) -and -not (Test-Path $uninstallKey) -and -not (Svc-Up) }
                $s3 = State-6c
                Note "1 after releasing the file, default launch again: process rc=$rc3 everything gone=$gone3 $s3 files=$(Names-6c)"
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
        $phase = 'in-place'
        if (Install-6c) {
            $held = Join-Path $footprintFolder 'held.txt'
            $fs = [IO.File]::Open($held, 'OpenOrCreate', 'ReadWrite', 'None')
            try {
                $rc2 = Run-Exe $uninstallExe "/S _?=$footprintFolder"
                $s2 = State-6c
                $exe2 = Exe-Kept
                Note "2 leftover, in place (_?=): process rc=$rc2 $s2 uninstall.exe present=$exe2"
                if ($rc2 -isnot [int]) { Res6c 'SL-6c-leftover-exit-40' 'UNPROVEN' "the uninstaller did not run: $rc2" }
                else { Ok6c (($rc2 -eq 40) -and $exe2 -and $s2 -eq 'folder=True service=False key=True') 'SL-6c-leftover-exit-40' "in place with a held file: exit 40, uninstall.exe, folder and key kept ($s2)" "expected exit 40, uninstall.exe present and folder=True service=False key=True, got rc=$rc2 exe=$exe2 $s2" }
            } finally { $fs.Dispose() }
            if (Test-Path $uninstallExe) {
                $rc2b = Run-Exe $uninstallExe "/S _?=$footprintFolder"
                Start-Sleep -Seconds 3
                $names = Names-6c
                $s2b = State-6c
                Note "2 released, in place again: process rc=$rc2b $s2b files=$names"
                if ($rc2b -isnot [int]) { Res6c 'SL-6c-in-place-after-release' 'UNPROVEN' "the second in-place run did not start: $rc2b" }
                else { Ok6c (($rc2b -eq 0) -and ($names -eq 'uninstall.exe') -and -not (Test-Path $uninstallKey) -and -not (Svc-Up)) 'SL-6c-in-place-after-release' 'in place after releasing the file: exit 0, key removed, uninstall.exe alone left (a running file cannot delete itself)' "expected rc 0, key gone and only uninstall.exe left, got rc=$rc2b $s2b files=$names" }
            } else { Res6c 'SL-6c-in-place-after-release' 'UNPROVEN' 'uninstall.exe was not available for the second in-place run' }
        } else { foreach ($id in 'SL-6c-leftover-exit-40', 'SL-6c-in-place-after-release') { Res6c $id 'UNPROVEN' 'precondition not met' } }
        Clean-6c

        # no leftover: in place, then default, on clean installs
        $phase = 'clean'
        if (Install-6c) {
            $rcA = Run-Exe $uninstallExe "/S _?=$footprintFolder"
            Start-Sleep -Seconds 3
            $namesA = Names-6c
            Note "3 clean, in place: process rc=$rcA $(State-6c) files=$namesA"
            if ($rcA -isnot [int]) { Res6c 'SL-6c-clean-in-place' 'UNPROVEN' "the uninstaller did not run: $rcA" }
            else { Ok6c (($rcA -eq 0) -and ($namesA -eq 'uninstall.exe') -and -not (Test-Path $uninstallKey) -and -not (Svc-Up)) 'SL-6c-clean-in-place' 'clean install, in place: exit 0, key and service gone, uninstall.exe alone left' "expected rc 0 and only uninstall.exe left, got rc=$rcA $(State-6c) files=$namesA" }
        } else { Res6c 'SL-6c-clean-in-place' 'UNPROVEN' 'precondition not met' }
        Clean-6c
        if (Install-6c) {
            $rcB = Run-Exe $uninstallExe '/S'
            $goneB = Wait-6c { -not (Test-Path $footprintFolder) -and -not (Test-Path $uninstallKey) -and -not (Svc-Up) }
            Note "3 clean, default: process rc=$rcB $(State-6c)"
            if ($rcB -isnot [int]) { Res6c 'SL-6c-clean-default' 'UNPROVEN' "the uninstaller did not run: $rcB" }
            else { Ok6c $goneB 'SL-6c-clean-default' 'clean install, default start: folder, uninstall.exe, key and service gone' "expected everything gone, got $(State-6c) files=$(Names-6c)" }
        } else { Res6c 'SL-6c-clean-default' 'UNPROVEN' 'precondition not met' }
        Clean-6c

        # the edge: an otherwise EMPTY folder held as a process's current directory
        $phase = 'edge'
        if (Install-6c) {
            Start-Holder
            Start-Sleep -Seconds 3
            if (($null -eq $script:holder) -or $script:holder.HasExited) { Res6c 'SL-6c-empty-folder-edge' 'UNPROVEN' 'the holder process was not running before the uninstall' }
            else {
                $rcE = Run-Exe $uninstallExe '/S'
                $keyE = Wait-6c { -not (Test-Path $uninstallKey) -and -not (Svc-Up) }
                Start-Sleep -Seconds 20
                $sE = State-6c
                $namesE = Names-6c
                Note "4 edge, folder held as current directory: process rc=$rcE key and service gone=$keyE $sE files=$namesE"
                if ($rcE -isnot [int]) { Res6c 'SL-6c-empty-folder-edge' 'UNPROVEN' "the uninstaller did not run: $rcE" }
                else { Ok6c ($keyE -and (Test-Path $footprintFolder) -and $namesE -eq '') 'SL-6c-empty-folder-edge' 'held empty folder: entry and service removed, uninstall.exe gone, folder left empty' "expected key removed, folder present and empty, got $sE files=$namesE" }
            }
            Stop-Holder
            Start-Sleep -Seconds 2
        } else { Res6c 'SL-6c-empty-folder-edge' 'UNPROVEN' 'precondition not met' }
        Clean-6c

        # an elevated uninstall with the service running (guest-proof.ps1 runs the desktop-only standard-user gate first on the same install)
        $phase = 'service-running'
        if (Install-6c) {
            $runBefore = Svc-Running
            $rc4 = Run-Exe $uninstallExe '/S'
            $gone4 = Wait-6c { -not (Test-Path $footprintFolder) -and -not (Test-Path $uninstallKey) -and -not (Svc-Up) }
            $s4 = State-6c
            Note "service running at start=$runBefore; elevated default launch rc=$rc4 everything gone within 60 s=$gone4 $s4"
            if (-not $runBefore -or ($rc4 -isnot [int])) { Res6c 'SL-6c-service-running-uninstall' 'UNPROVEN' "service running=$runBefore, uninstaller rc=$rc4" }
            elseif ($gone4) { Res6c 'SL-6c-service-running-uninstall' 'PASS' "stub service running with runner.exe open: service, folder and key all removed ($s4)" }
            else { Res6c 'SL-6c-service-running-uninstall' 'FAIL' "left $s4" }
        } else { Res6c 'SL-6c-service-running-uninstall' 'UNPROVEN' 'precondition not met' }
        Clean-6c
        $phase = 'done'
    }
} catch {
    # Exception messages can hold paths or names: report the phase and the exception type only.
    Note "script error in phase ${phase}: $($_.Exception.GetType().Name)"
} finally {
    Stop-Holder
    if ($script:gateOk) {
        Clean-6c
        if ($script:signerMade) { Remove-Item -LiteralPath $signerFile -Force -ErrorAction SilentlyContinue }
        if ($script:signerDirMade) { Remove-Item -LiteralPath $signerDir -Force -ErrorAction SilentlyContinue }
    }
    Write-Verdict
}
exit 0
