# Windows probes for the SL-13 and uninstaller fixes (ecosystem-control#64). Dot-sourced by guest-proof.ps1 when -ProbesOnly is given,
# after the stub is compiled and the standard account exists. Diagnostic only: every result line is PROBE-<id>|INFO|<detail>, which
# the gate never counts; raw outputs go to out\probe-a.txt and out\probe-b.txt. ASCII only.

function Probe($id, $detail) { Res "PROBE-$id" 'INFO' (($detail -replace '\s+', ' ').Trim()) }

# Runs a native tool, records the raw command, rc and stdout (stderr merged) in the evidence file, returns @(rc, text).
function Raw($file, $exe, $argList) {
    $o = (& $exe @argList 2>&1 | Out-String)
    $rc = $LASTEXITCODE
    Note $file @("> $exe $($argList -join ' ')", "rc=$rc", $o.Trim(), '')
    ,@($rc, $o)
}

# ---------------------------------------------------------------- PROBE A: when can a grant name the service?
$pName = 'EcosystemRunnerG5P'
$pF = 'C:\g5\probe-f'
$pCfg = Join-Path $pF 'config.toml'
$pProg = Join-Path $pF 'program'
$pOut = 'C:\g5\probe-out'
$sc = Join-Path $env:windir 'System32\sc.exe'
$icacls = Join-Path $env:windir 'System32\icacls.exe'
$pSid = if (Test-Path $py) { (& $py -c "from installer import winsys; print(winsys.service_sid('$pName'))" 2>&1 | Out-String).Trim() } else { '' }
Note 'probe-a.txt' @("service name=$pName folder=$pF service SID (winsys.service_sid)=$pSid", 'The file the stub reads is named config.toml (the stub reads <folder>\config.toml); it plays the role of c.toml.', '')

function Reset-ProbeAcl {
    [void](Raw 'probe-a.txt' $icacls @($pF, '/reset', '/T', '/C'))
    [void](Raw 'probe-a.txt' $icacls @($pF, '/inheritance:r'))
    [void](Raw 'probe-a.txt' $icacls @($pF, '/grant:r', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'))
    [void](Reset-ProbeCfg)
    # the service binary must stay readable whatever the folder grants do: program\ is its own, closed to inheritance
    [void](Raw 'probe-a.txt' $icacls @($pProg, '/inheritance:r'))
    [void](Raw 'probe-a.txt' $icacls @($pProg, '/grant:r', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', '*S-1-1-0:(OI)(CI)RX'))
}
function Reset-ProbeCfg {
    [void](Raw 'probe-a.txt' $icacls @($pCfg, '/inheritance:r'))
    [void](Raw 'probe-a.txt' $icacls @($pCfg, '/grant:r', '*S-1-5-18:F', '*S-1-5-32-544:F'))
}

function Restart-Probe($tag) {
    Remove-Item -LiteralPath (Join-Path $pOut 'probe.txt') -ErrorAction SilentlyContinue
    [void](Raw 'probe-a.txt' $sc @('stop', $pName))
    for ($i = 0; $i -lt 15; $i++) { if ((& $sc query $pName 2>&1 | Out-String) -match 'STOPPED') { break }; Start-Sleep -Seconds 1 }
    $st = Raw 'probe-a.txt' $sc @('start', $pName)
    $run = $false
    for ($i = 0; $i -lt 20; $i++) { if ((& $sc query $pName 2>&1 | Out-String) -match 'RUNNING') { $run = $true; break }; Start-Sleep -Seconds 1 }
    Start-Sleep -Seconds 2
    $probe = if (Test-Path (Join-Path $pOut 'probe.txt')) { (Get-Content -LiteralPath (Join-Path $pOut 'probe.txt') -Raw) } else { 'no probe.txt written' }
    Note 'probe-a.txt' @("probe.txt after restart ($tag): running=$run start_rc=$($st[0])", $probe, '')
    Probe "A-$tag-service-read" "restart rc=$($st[0]) running=$run stub says: $probe"
}

function Try-Grants($m) {
    $byName = "NT SERVICE\${pName}"
    $g1 = Raw 'probe-a.txt' $icacls @($pF, '/grant:r', "${byName}:(OI)(CI)RX")
    Probe "A-$m-1-folder-by-name" "rc=$($g1[0]) cmd=icacls $pF /grant:r `"${byName}:(OI)(CI)RX`" out=$($g1[1])"
    $g2 = Raw 'probe-a.txt' $icacls @($pF, '/grant:r', "*${pSid}:(OI)(CI)RX")
    Probe "A-$m-2-folder-by-sid" "rc=$($g2[0]) cmd=icacls $pF /grant:r `"*${pSid}:(OI)(CI)RX`" out=$($g2[1])"
    $fAcl = Raw 'probe-a.txt' $icacls @($pF)
    Probe "A-$m-folder-acl-after" ($fAcl[1] -replace [regex]::Escape($pF), 'F')
    Reset-ProbeCfg
    $g3 = Raw 'probe-a.txt' $icacls @($pCfg, '/grant:r', "${byName}:(R)")
    Probe "A-$m-3-file-by-name" "rc=$($g3[0]) cmd=icacls $pCfg /grant:r `"${byName}:(R)`" out=$($g3[1])"
    $c3 = Raw 'probe-a.txt' $icacls @($pCfg)
    Probe "A-$m-3-file-acl-after" ($c3[1] -replace [regex]::Escape($pCfg), 'c.toml')
    if ($m -eq 'M3') { Restart-Probe 'M3-after-grant-3' }
    Reset-ProbeCfg
    $g4 = Raw 'probe-a.txt' $icacls @($pCfg, '/grant:r', "*${pSid}:(R)")
    Probe "A-$m-4-file-by-sid" "rc=$($g4[0]) cmd=icacls $pCfg /grant:r `"*${pSid}:(R)`" out=$($g4[1])"
    $c4 = Raw 'probe-a.txt' $icacls @($pCfg)
    Probe "A-$m-4-file-acl-after" ($c4[1] -replace [regex]::Escape($pCfg), 'c.toml')
    if ($m -eq 'M3') { Restart-Probe 'M3-after-grant-4' }
}

function Remove-ProbeA {
    [void](Raw 'probe-a.txt' $sc @('stop', $pName))
    Start-Sleep -Seconds 2
    [void](Raw 'probe-a.txt' $sc @('delete', $pName))
    Remove-Item -LiteralPath $pF, $pOut -Recurse -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    $left = (Test-Path "HKLM:\SYSTEM\CurrentControlSet\Services\$pName") -or (Test-Path $pF) -or (Test-Path $pOut)
    Probe 'A-cleanup' "service, folder and probe-out removed: $(-not $left)"
}

function Run-ProbeA {
    if (-not $stubOk) { Probe 'A-skipped' 'the stub could not be compiled (see stub.txt)'; return }
    Remove-ProbeA
    New-Item -ItemType Directory -Force -Path $pF, $pProg, $pOut | Out-Null
    [void](Raw 'probe-a.txt' $icacls @($pOut, '/grant', '*S-1-1-0:(OI)(CI)M'))
    Copy-Item -LiteralPath $stub -Destination (Join-Path $pProg 'runner.exe') -Force
    Set-Content -LiteralPath $pCfg -Value '# probe config, no secret' -Encoding ascii
    Reset-ProbeAcl
    $before = (icacls $pF | Out-String) + (icacls $pCfg | Out-String)

    Try-Grants 'M0'
    $after0 = (icacls $pF | Out-String) + (icacls $pCfg | Out-String)
    $m0svc = Test-Path "HKLM:\SYSTEM\CurrentControlSet\Services\$pName"
    Probe 'A-M0-residue' "folder and file ACL unchanged by the M0 grants (any success would show)=$($before.Trim() -eq $after0.Trim()); service created by a grant=$m0svc"

    Reset-ProbeAcl
    $cr = Raw 'probe-a.txt' $sc @('create', $pName, 'binPath=', "`"$pProg\runner.exe`"", 'obj=', "NT SERVICE\$pName", 'start=', 'demand')
    Probe 'A-M1-sc-create' "rc=$($cr[0]) out=$($cr[1])"
    Try-Grants 'M1'

    Reset-ProbeAcl
    $sd = Raw 'probe-a.txt' $sc @('sidtype', $pName, 'unrestricted')
    Probe 'A-M2-sc-sidtype' "rc=$($sd[0]) out=$($sd[1])"
    Try-Grants 'M2'

    Reset-ProbeAcl
    Restart-Probe 'M3-baseline-no-grant'
    Try-Grants 'M3'
    Remove-ProbeA
}

# ---------------------------------------------------------------- PROBE B: who can start the uninstaller?
$bName = 'EcosystemRunner'
function Setup-RealInstall {
    # The real installer, elevated. The service exists first so that a grant naming its SID resolves (the pre-run showed it does not before).
    if (-not (Test-Path "HKLM:\SYSTEM\CurrentControlSet\Services\$bName")) {
        [void](Raw 'probe-b.txt' $sc @('create', $bName, 'binPath=', "`"$stub`"", 'obj=', "NT SERVICE\$bName", 'start=', 'demand'))
        [void](Raw 'probe-b.txt' $sc @('sidtype', $bName, 'unrestricted'))
    }
    $rc = Run-Exe $installer "/S /SIGNER=$sig" $null
    Note 'probe-b.txt' @("real installer, elevated, silent, service pre-created: rc=$rc", "uninstall.exe present=$(Test-Path (Join-Path $footprintFolder 'uninstall.exe'))", '')
    $rc
}
function Remove-ProbeB {
    [void](Raw 'probe-b.txt' $sc @('stop', $bName))
    [void](Raw 'probe-b.txt' $sc @('delete', $bName))
    cmd.exe /c rmdir "$footprintFolder\link" 2>&1 | Out-Null
    Remove-Item -LiteralPath $footprintFolder -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $uninstallKey -Recurse -Force -ErrorAction SilentlyContinue
}
function State-B {
    "folder=$(Test-Path $footprintFolder) uninstall.exe=$(Test-Path (Join-Path $footprintFolder 'uninstall.exe')) service=$(Test-Path "HKLM:\SYSTEM\CurrentControlSet\Services\$bName") uninstall_key=$(Test-Path $uninstallKey)"
}

function Run-ProbeB {
    $adminLocal = Join-Path $env:LOCALAPPDATA 'EcosystemInstaller'
    New-Item -ItemType Directory -Force -Path $adminLocal | Out-Null
    Set-Content -LiteralPath (Join-Path $adminLocal 'signer.sha256') -Value $sig -Encoding ascii
    Remove-ProbeB
    $irc = Setup-RealInstall
    Probe 'B-setup' "installer rc=$irc; $(State-B)"
    $acl = (icacls $footprintFolder 2>&1 | Out-String)
    Probe 'B-folder-acl' $acl
    if (-not (Test-Path (Join-Path $footprintFolder 'uninstall.exe'))) { Probe 'B-skipped' 'the installer did not leave an uninstall.exe, so the standard user case has nothing to start'; Remove-ProbeB; return }
    $reg = Get-ItemProperty -LiteralPath $uninstallKey -ErrorAction SilentlyContinue
    $us = if ($reg -and $reg.UninstallString) { $reg.UninstallString } else { '(none)' }
    $qs = if ($reg -and $reg.QuietUninstallString) { $reg.QuietUninstallString } else { '(none)' }
    Probe 'B-registered-strings' "UninstallString=$us QuietUninstallString=$qs (install.nsh:39-40; neither has _?=)"

    if ($cred) {
        $before = State-B
        $sc1 = Join-Path $work 'probe-b-std.cmd'
        Set-Content -LiteralPath $sc1 -Encoding ascii -Value @('@echo off', 'whoami', "dir `"$footprintFolder`"", 'echo dir rc=%errorlevel%',
            "dir `"$footprintFolder\uninstall.exe`"", 'echo dir-uninstall rc=%errorlevel%', "`"$footprintFolder\uninstall.exe`" /S", 'echo start rc=%errorlevel%')
        $stdRc = Run-AsStd $sc1 ''
        $stdOut = if (Test-Path (Join-Path $work 'std-out.txt')) { Get-Content -LiteralPath (Join-Path $work 'std-out.txt') -Raw } else { '(no output file)' }
        Start-Sleep -Seconds 10
        $afterB = State-B
        Note 'probe-b.txt' @("standard user script rc=$stdRc", $stdOut, "state before: $before", "state 10 s after: $afterB", '')
        Probe 'B1-standard-user' "launcher rc=$stdRc; output: $stdOut; state before [$before] after [$afterB]"
    } else { Probe 'B1-standard-user' 'no standard account in this clone' }

    # B2 as SL-6a starts it: the real uninstaller, elevated, '/S' and no _?=, waiting for the process only
    $t0 = Get-Date
    $unRc = Run-Exe (Join-Path $footprintFolder 'uninstall.exe') '/S' $null
    $ms = [int]((Get-Date) - $t0).TotalMilliseconds
    $atReturn = State-B
    $gone = $false
    for ($i = 0; $i -lt 60; $i++) { if (-not (Test-Path $footprintFolder)) { $gone = $true; break }; Start-Sleep -Seconds 1 }
    Probe 'B2-uninstall-no-underscore' "SL-6a way: uninstall.exe /S (no _?=): process rc=$unRc after $ms ms; state when the process returned [$atReturn]; folder gone after polling=$gone (polled $i s); final [$(State-B)]"

    # the same with _?= (the uninstaller runs in place, so the parent process is the one that works)
    $irc2 = Setup-RealInstall
    if (Test-Path (Join-Path $footprintFolder 'uninstall.exe')) {
        $t0 = Get-Date
        $unRc2 = Run-Exe (Join-Path $footprintFolder 'uninstall.exe') "/S _?=$footprintFolder" $null
        $ms2 = [int]((Get-Date) - $t0).TotalMilliseconds
        Probe 'B2-uninstall-with-underscore' "uninstall.exe /S _?=${footprintFolder}: process rc=$unRc2 after $ms2 ms; state when the process returned [$(State-B)]"
    } else { Probe 'B2-uninstall-with-underscore' "second install did not produce uninstall.exe (rc=$irc2)" }
    Remove-ProbeB
    Probe 'B-cleanup' "after cleanup [$(State-B)]"
}

Run-ProbeB
Run-ProbeA
