# GUEST7D (ecosystem-control#129, GUEST7C part B): the REAL installer in update mode (installer\nsis\update.nsh, built by installer.guest.pack as
# installer-update.exe with a stand-in program file) run on real Windows over a seeded product folder, one fresh fixture per case. Runs INSIDE a
# disposable no-NIC clone through `winev run`, elevated. The product folder is C:\ProgramData\EcosystemRunner (the installer calls SetShellVarContext
# all); every outside folder lives under C:\X\g7d\outside. A harmless stub service (installer\guest\stub-service.cs, compiled here) is registered as
# EcosystemRunner OUTSIDE the product folder, so stop, start and the health check work and the stand-in program file is never run.
# >>> cases U-B1 U-B2
# Links are made with mklink and removed only by rmdir / del (never a recursive delete).
# <<< cases
# Before and after each run a name + size + SHA-256 listing of every outside folder and file is compared: the outside fixture must be unchanged.
# Cases (the expectations are READ from update.nsh and written in the PR body before the run; a verdict that differs is a FINDING, not an edit):
# >>> cases U-B1
# U-B1 a junction at backup (refused with 39).
# <<< cases
# >>> cases U-B2
# U-B2 a junction at program (refused with 39).
# <<< cases
# >>> cases U-B3 U-B3b
# U-B3 / U-B3b a locked file in a stale backup, held with FileShare None / ReadWrite (run 1 exits 43, run 2 after the release exits 0).
# <<< cases
# >>> cases U-B4
# U-B4 a stale backup before an update (0).
# <<< cases
# >>> cases U-B5
# U-B5 the FIRST update, no backup (0).
# <<< cases
# Hard limit of 120 seconds per case: the installer is killed with its children and the case is UNPROVEN, never waited for.
# OWNERSHIP GATE: before anything is deleted or any service is made the run stops with one line `REFUSED: ...` (the path, the key and the service name
# only) when the product folder exists without the marker file this harness writes into it, the uninstall key exists with a DisplayName this harness
# did not write, a service EcosystemRunner exists, or a stored-signer file exists with other content; Reset-All, Ensure-Stub and Seed-Signer cannot run before the
# gate has passed (a silent run exits 3 until the signer has been confirmed once, so the harness writes that one file and removes it again). The verdict is in the log lines
# (VERDICT / REFUSED / SUMMARY), not in the exit code (installer/README.md). Writes out\update-smoke.txt and out\g7d-env.txt. ASCII only; no secret.
[CmdletBinding()]
param([string]$Only = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

# -Only 'U-B3,U-B4' runs just those cases (one comma-separated string: powershell -File passes it unsplit); every other case logs NOT-SELECTED and
# runs nothing. An unknown name is refused here, before anything is touched. Without -Only all shipped cases run.
$caseNames = @('U-B1', 'U-B2', 'U-B3', 'U-B3b', 'U-B4', 'U-B5')
$selected = @($Only -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
foreach ($c in $selected) {
    if ($caseNames -cnotcontains $c) { Write-Output ('REFUSED-ARG: -Only [' + ($selected -join ',') + '] names unknown case ' + $c + '; known: ' + ($caseNames -join ',')); exit 2 }
}

$tree = (Get-Location).Path
$out = Join-Path $tree 'out'
$root = 'C:\X\g7d'
$prod = 'C:\ProgramData\EcosystemRunner'
$outs = Join-Path $root 'outside'
$bin = Join-Path $root 'bin'
$stubExe = Join-Path $root 'stub\stub.exe'
$log = Join-Path $root 'u-update.log'
$keyPath = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner'
$markerName = '.g7d-marker'
$markerText = 'written-by-update-smoke-g7d'
$keyName = 'EcosystemRunner g7d'
$sig = ('ab' * 32)
$caseLimit = 120
$signerDir = Join-Path $env:LOCALAPPDATA 'EcosystemInstaller'
$signerFile = Join-Path $signerDir 'signer.sha256'
$signerText = $sig + "`n"
$oldText = 'OLD-RUNNER-g7d'
$decoyText = 'DECOY-RUNNER-g7d'
$staleText = 'STALE-RUNNER-g7d'
$script:gateOk = $false
$script:svcMade = $false
$script:signerMade = $false
$script:signerDirMade = $false
$script:holder = $null
$script:caseSw = $null
$script:payloadText = $null
$logName = 'update-smoke.txt'
New-Item -ItemType Directory -Force -Path $out, $root, $bin, (Split-Path $stubExe) | Out-Null
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

# Removes one entry WITHOUT following a link: rmdir removes a directory link (the link only), del a file symbolic link;
# a real folder is emptied entry by entry (each entry is checked again) and removed. The path is made absolute first and the removal acts on
# that absolute form; anything that is neither the product folder itself nor strictly inside it or inside C:\X\g7d is refused (a `..` that
# climbs out, a sibling such as C:\X\g7d-evil, a UNC path, a drive root, the empty string).
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

# The uninstall entry of the product, in the 64-bit registry view (the installer does SetRegView 64).
function Open-Hklm64 { [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64) }
function Set-Key { $b = Open-Hklm64; $k = $b.CreateSubKey($keyPath); $k.SetValue('DisplayName', $keyName); $k.Close(); $b.Close() }
function Test-Key { $b = Open-Hklm64; $k = $b.OpenSubKey($keyPath); $r = ($null -ne $k); if ($r) { $k.Close() }; $b.Close(); $r }
function Remove-Key { $b = Open-Hklm64; $b.DeleteSubKey($keyPath, $false); $b.Close() }
function Get-KeyName { $b = Open-Hklm64; $k = $b.OpenSubKey($keyPath); $r = $null; if ($null -ne $k) { $r = $k.GetValue('DisplayName'); $k.Close() }; $b.Close(); $r }
function Get-KeyVal([string]$name) { $b = Open-Hklm64; $k = $b.OpenSubKey($keyPath); $r = $null; if ($null -ne $k) { $r = $k.GetValue($name); $k.Close() }; $b.Close(); $r }

# The ownership gate: what sits at the product folder, under the uninstall key or as the service EcosystemRunner that this harness did not create. One
# reason per thing, naming the path, the key or the service only (never what is in it); an empty answer means everything there is ours, or nothing is there.
# The stub service is made by Ensure-Stub only after the gate has passed, so one met here is not ours.
function Get-Foreign {
    $why = @()
    if (Exists $prod) {
        if ((Read-Ascii (Join-Path $prod $markerName)) -cne $markerText) { $why += "the product folder $prod exists and holds no g7d marker" }
    }
    if (Test-Key) {
        if ((Get-KeyName) -cne $keyName) { $why += "the uninstall key HKLM\$keyPath is not the g7d one" }
    }
    if (Exists $signerFile) {
        if ((Read-Ascii $signerFile) -cne $signerText) { $why += 'the stored signer file under the local application data folder exists and is not the one this harness writes' }
    }
    # sc answers error 1060 when there is no such service; one that cannot be queried is not known to be absent.
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
function Mark-Prod {
    $ErrorActionPreference = 'Stop'
    Mkdirs @($prod)
    $security = New-Object System.Security.AccessControl.DirectorySecurity
    $security.SetSecurityDescriptorSddlForm('O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)', 'Owner, Access')
    Set-Acl -LiteralPath $prod -AclObject $security

    $acl = Get-Acl -LiteralPath $prod
    $sidType = [Security.Principal.SecurityIdentifier]
    $owner = $acl.GetOwner($sidType).Value
    $dacl = $acl.GetSecurityDescriptorSddlForm('Access')
    Log "SEED owner=$owner dacl=$dacl"
    $rules = @($acl.GetAccessRules($true, $true, $sidType))
    $trustees = @($rules | ForEach-Object { $_.IdentityReference.Value })
    if ($owner -ne 'S-1-5-32-544' -or -not $acl.AreAccessRulesProtected -or $rules.Count -ne 2 -or
        $trustees -notcontains 'S-1-5-18' -or $trustees -notcontains 'S-1-5-32-544') {
        throw "Unexpected seed owner or DACL on $prod"
    }
    foreach ($rule in $rules) {
        if ($rule.IsInherited -or $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne 'FullControl' -or
            $rule.InheritanceFlags -ne 'ContainerInherit, ObjectInherit' -or $rule.PropagationFlags -ne 'None') {
            throw "Unexpected seed access rule on $prod"
        }
    }
    Write-Ascii (Join-Path $prod $markerName) $markerText
}
function Write-Summary {
    $lines = @(Get-Content -LiteralPath $log)
    $n = @{ PASS = 0; FAIL = 0; UNPROVEN = 0 }
    foreach ($l in $lines) { if ($l -match '^VERDICT \S+: (PASS|FAIL|UNPROVEN)( |$)') { $n[$Matches[1]]++ } }
    $refused = @($lines | Where-Object { $_ -like 'REFUSED:*' }).Count
    # A case that died of a script error leaves no VERDICT line, so the counts alone would read as a clean run.
    $errored = @($lines | Where-Object { ($_ -match '^CASE \S+: SCRIPT-ERROR ') -or ($_ -like 'FATAL:*') -or ($_ -like 'CLEANUP:*') }).Count
    $s = "SUMMARY pass=$($n.PASS) fail=$($n.FAIL) unproven=$($n.UNPROVEN) refused=$refused error=$errored"
    Log $s
    $s
}

# ---- the stub service and the lock holder
function Get-Svc {
    $t = Cmd 'sc' 'queryex' 'EcosystemRunner'
    $state = 'UNKNOWN'
    if ($t -match 'STATE\s*:\s*\d+\s+(\w+)') { $state = $Matches[1] } elseif ($t -match '1060') { $state = 'GONE' }
    $procId = '0'
    if ($t -match 'PID\s*:\s*(\d+)') { $procId = $Matches[1] }
    "$state/$procId"
}
function Ensure-Stub {
    if (-not $script:gateOk) { throw 'the ownership gate has not passed: no service is made' }
    if ((Cmd 'sc' 'query' 'EcosystemRunner') -notmatch 'SERVICE_NAME') {
        $c = Cmd 'sc' 'create' 'EcosystemRunner' 'binPath=' $stubExe 'start=' 'demand'
        if ((Cmd 'sc' 'query' 'EcosystemRunner') -match 'SERVICE_NAME') { $script:svcMade = $true }
        Log "STUB create: made=$(Yn $script:svcMade) answer=[$($c -replace '\s+', ' ')]"
    }
    if ((Get-Svc) -notmatch '^RUNNING/') {
        [void](Cmd 'sc' 'start' 'EcosystemRunner')
        $n = 0; while (($n -lt 30) -and ((Get-Svc) -notmatch '^RUNNING/')) { Start-Sleep -Seconds 1; $n++ }
    }
    Get-Svc
}
function Remove-Stub {
    if (-not $script:svcMade) { return }
    [void](Cmd 'sc' 'stop' 'EcosystemRunner')
    $n = 0; while (($n -lt 20) -and ((Get-Svc) -notmatch '^(STOPPED|GONE)/')) { Start-Sleep -Seconds 1; $n++ }
    [void](Cmd 'sc' 'delete' 'EcosystemRunner')
    $script:svcMade = $false
}
function Stop-Holder {
    if ($null -ne $script:holder) {
        try { $script:holder.Kill() } catch { }
        try { [void]$script:holder.WaitForExit(5000) } catch { }
    }
    $script:holder = $null
}
# A background process that opens one file and keeps it open (FileShare None blocks every other open, ReadWrite only the delete) until it is killed.
function Start-Holder([string]$path, [string]$share) {
    $hold = Join-Path $root 'hold.ps1'; $flag = Join-Path $root 'held.flag'
    Remove-Item -LiteralPath $flag -Force -ErrorAction SilentlyContinue
    $src = @('param([string]$path, [string]$flag, [string]$share, [int]$sec)', '$fs = [IO.File]::Open($path, ''Open'', ''Read'', $share)',
        '[IO.File]::WriteAllText($flag, ''held'')', 'Start-Sleep -Seconds $sec', '$fs.Close()') -join "`r`n"
    Write-Ascii $hold $src
    $script:holder = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $hold, $path, $flag, $share, '100') -PassThru -WindowStyle Hidden
    $n = 0; while (-not (Test-Path -LiteralPath $flag) -and $n -lt 100) { Start-Sleep -Milliseconds 200; $n++ }
    Test-Path -LiteralPath $flag
}

# A silent run stops with exit 3 until the signer has been confirmed once (trust.nsh), so the stored-signer file a confirmed first run leaves is written here, only
# when it is absent and only after the gate; Remove-Signer removes just that file, and the folder only if this run made it and it is empty.
function Seed-Signer {
    if (-not $script:gateOk) { throw 'the ownership gate has not passed: no signer file is written' }
    if (Exists $signerFile) { return }
    if (-not (Exists $signerDir)) { Mkdirs @($signerDir); $script:signerDirMade = $true }
    Write-Ascii $signerFile $signerText
    $script:signerMade = $true
}
function Remove-Signer {
    if (-not $script:gateOk) { throw 'the ownership gate has not passed: nothing is deleted' }
    if ($script:signerMade) {
        try { [IO.File]::Delete($signerFile) } catch { Log "CLEANUP: the signer file could not be removed: $($_.Exception.Message)" }
        $script:signerMade = $false
    }
    if ($script:signerDirMade) {
        try { [IO.Directory]::Delete($signerDir) } catch { Log "CLEANUP: the signer folder could not be removed: $($_.Exception.Message)" }
        $script:signerDirMade = $false
    }
}
function Reset-All {
    if (-not $script:gateOk) { throw 'the ownership gate has not passed: nothing is deleted' }
    Stop-Holder
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

# ---- what the update leaves behind, read one fact at a time
# The stand-in program file written by the update is the one from update-payload.bin.b64; the other three texts are the ones this harness seeds.
function Runner-Class {
    $t = Read-Ascii (Join-Path $prod 'program\runner.exe')
    if ($null -eq $t) { return 'ABSENT' }
    if ($t -ceq $oldText) { return 'OLD' }
    if ($t -ceq $decoyText) { return 'DECOY' }
    if ($t -ceq $staleText) { return 'STALE' }
    if ($t -ceq $script:payloadText) { return 'PAYLOAD' }
    'OTHER(' + $t.Length + ' bytes)'
}
function State-Version {
    $t = Read-Ascii (Join-Path $prod 'installer-state.json')
    if ($null -eq $t) { return 'ABSENT' }
    if ($t -match '"installer_version": "([^"]*)"') { return $Matches[1] }
    'UNPARSED'
}
function Step-Names {
    $t = Read-Ascii (Join-Path $prod 'steps.jsonl')
    if ($null -eq $t) { return @() }
    @([regex]::Matches($t, '"step": "([^"]*)"') | ForEach-Object { $_.Groups[1].Value })
}
function Get-Owner { try { ((Get-Acl -LiteralPath $prod).GetOwner([Security.Principal.SecurityIdentifier])).Value } catch { 'unreadable' } }
function Get-State {
    $a = Get-Attr "$prod\backup"
    [pscustomobject]@{
        Runner = (Runner-Class)
        Version = (State-Version)
        Backup = $(if ($null -eq $a) { 'absent' } elseif ($a -band 0x400) { 'link' } else { 'dir' })
        Exe = (Exists "$prod\uninstall.exe")
        KeyName = "$(Get-KeyVal 'DisplayName')"
        KeyVer = "$(Get-KeyVal 'DisplayVersion')"
        Svc = (Get-Svc)
        Steps = @(Step-Names)
    }
}

# Evidence only, never part of a verdict: the PowerShell command Winsys_FolderAudit runs, taken from the shipped winsys.nsh, run on the fixture before
# the installer is; its one word says why an update was or was not refused (clean, links, owners, empty), nothing at all means the probe itself failed.
function Get-AuditCommand([string]$nsh) {
    $m = [regex]::Match($nsh, '(?s)Function Winsys_FolderAudit.*?-Command "([^"]*)"')
    if (-not $m.Success) { return $null }
    $m.Groups[1].Value.Replace('$$', '$').Replace('''$APPDATA\EcosystemRunner''', "[IO.Path]::Combine([Environment]::GetFolderPath('CommonApplicationData'), 'EcosystemRunner')")
}
function Probe-Audit {
    $nsh = Read-Ascii (Join-Path $tree 'installer\nsis\winsys.nsh')
    if ($null -eq $nsh) { return 'no-source' }
    $c = Get-AuditCommand $nsh
    if ($null -eq $c) { return 'no-command' }
    try {
        $o = (& (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -NoProfile -NonInteractive -Command $c 2>&1 | Out-String).Trim()
        "exit=$LASTEXITCODE answer=[$($o -replace '\s+', ' ')]"
    } catch { 'probe-error ' + $_.Exception.Message }
}

# ---- one run of the installer under test: /S /SIGNER=<64 hex>, an update because installer-state.json says 0.0.1. Killed with its children at the limit.
function Run-Inst([string]$exe, [string]$argText, [double]$limit) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = $argText
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $root
    $rc = 'not started'
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $p = [Diagnostics.Process]::Start($psi)
        if ($p.WaitForExit([int]($limit * 1000))) {
            $rc = $p.ExitCode
        } else {
            [void](Cmd 'taskkill' '/T' '/F' '/PID' "$($p.Id)")
            try { $p.Kill() } catch { }
            [void]$p.WaitForExit(5000)
            $rc = 'timeout'
        }
    } catch { $rc = 'error: ' + $_.Exception.Message }
    [pscustomobject]@{ Rc = "$rc"; Sec = [Math]::Round($sw.Elapsed.TotalSeconds, 1) }
}

# One measured run: snapshot, owner and audit probe, start the installer, snapshot again, state, CASE lines. The run gets what is left of the case limit.
function Measure-Inst([string]$name, [string]$tag) {
    $before = @(Get-Snapshot)
    $listBefore = Prod-Text
    $svcBefore = Get-Svc
    Log "PROBE ${name}${tag} before the run: owner=[$(Get-Owner)] audit=[$(Probe-Audit)]"
    $left = [Math]::Max(5, [Math]::Floor($caseLimit - 5 - $script:caseSw.Elapsed.TotalSeconds))
    $r = Run-Inst (Join-Path $bin 'installer-update.exe') "/S /SIGNER=$sig" $left
    $after = @(Get-Snapshot)
    $d = Diff-Snap $before $after
    $st = Get-State
    $outside = if ($d.Same) { 'SAME(' + $d.Count + ' names)' } else { 'CHANGED missing=[' + (@($d.Missing | Select-Object -First 12) -join ' ; ') + '] added=[' + (@($d.Added | Select-Object -First 12) -join ' ; ') + ']' }
    Log "CASE ${name}${tag}: rc=$($r.Rc) sec=$($r.Sec) outside=$outside service=${svcBefore} to $($st.Svc) runner=$($st.Runner) state_version=$($st.Version) backup=$($st.Backup) uninstall.exe=$(Yn $st.Exe) key=[$($st.KeyName) $($st.KeyVer)] steps=[$($st.Steps -join ',')]"
    Log "CASE ${name}${tag} product folder before: $listBefore"
    Log "CASE ${name}${tag} product folder after:  $(Prod-Text)"
    [pscustomobject]@{ Rc = $r.Rc; Sec = $r.Sec; Same = $d.Same; State = $st; SvcBefore = $svcBefore; TimedOut = ($r.Rc -eq 'timeout') }
}
function Verdict([string]$name, [bool]$ok, [string]$why) { Log ('VERDICT ' + $name + ': ' + $(if ($ok) { 'PASS' } else { 'FAIL' }) + ' ' + $why) }
function Unproven([string]$name, [string]$why) { Log ('VERDICT ' + $name + ': UNPROVEN ' + $why) }

# A finished update leaves no backup folder, the stand-in program file, state 0.1.0, uninstall.exe and the uninstall entry of the installer under test,
# and the service RUNNING under a new process (it was stopped and started).
function Updated-Ok($r) {
    $s = $r.State
    ($r.Rc -eq '0') -and $r.Same -and ($s.Backup -eq 'absent') -and ($s.Runner -eq 'PAYLOAD') -and ($s.Version -eq '0.1.0') -and $s.Exe -and ($s.KeyName -ceq 'Ecosystem Runner') -and ($s.KeyVer -ceq '0.1.0') -and ($s.Svc -match '^RUNNING/') -and ($s.Svc -ne $r.SvcBefore)
}

# The common seed: the product folder as an elevated administrator made it, the state of an install of 0.0.1 (the format install.nsh writes), the old program
# file (so the update sees a service install), the uninstall entry, the stub service RUNNING.
function Seed-Base([bool]$program) {
    Reset-All
    Seed-Signer
    Mark-Prod
    Write-Ascii (Join-Path $prod 'installer-state.json') ('{"schema_version": 1, "installer_version": "0.0.1"}' + "`r`n")
    if ($program) { Mkdirs @("$prod\program"); Write-Ascii "$prod\program\runner.exe" $oldText }
    Set-Key
    [void](Ensure-Stub)
}
function Seed-Stale {
    Mkdirs @("$prod\backup\program", "$prod\backup\z-dir")
    Write-Ascii "$prod\backup\program\runner.exe" $staleText
    Write-Ascii "$prod\backup\service.json" '{"name": "EcosystemRunner"}'
    Write-Ascii "$prod\backup\z-dir\y.txt" 'Y'
}

# >>> cases U-B1 U-B2
# ---- U-B1 / U-B2: a junction inside the product folder (at backup, at program), the target a decoy folder outside it. The folder audit finds the reparse
# point and the update is refused with 39 before anything is changed or followed; the decoy must come out identical by name, size and SHA-256.
function Link-Case([string]$name, [string]$linkRel, [string]$wantRunner) {
    Seed-Base ($linkRel -ne 'program')
    $o = "$outs\$name\decoy"
    Mkdirs @("$o\nested")
    Write-Ascii "$o\keep.txt" 'KEEP-decoy'; Write-Ascii "$o\nested\deep.txt" 'DEEP-decoy'
    if ($linkRel -eq 'backup') { Write-Ascii "$o\complete" ''; Mkdirs @("$o\program"); Write-Ascii "$o\program\runner.exe" $decoyText } else { Write-Ascii "$o\runner.exe" $decoyText }
    $m = Cmd 'mklink' '/J' "$prod\$linkRel" $o
    $a = Get-Attr "$prod\$linkRel"
    if (($null -eq $a) -or (($a -band 0x400) -eq 0)) { Log "FIXTURE-BAD ${name}: mklink=[$m]"; Unproven $name 'fixture could not be built'; return }
    $r = Measure-Inst $name ''
    if ($r.TimedOut) { Unproven $name 'the run hit the case limit and was killed'; return }
    $a2 = Get-Attr "$prod\$linkRel"
    $linkThere = ($null -ne $a2) -and (($a2 -band 0x400) -ne 0)
    $s = $r.State
    $sameSvc = ($s.Svc -eq $r.SvcBefore) -and ($s.Svc -match '^RUNNING/')
    Log "CHECK $name mklink=[$m] link_still_there=$(Yn $linkThere) service_untouched=$(Yn $sameSvc) uninstall.exe_there=$(Yn $s.Exe)"
    Verdict $name (($r.Rc -eq '39') -and $linkThere -and $r.Same -and $sameSvc -and ($s.Runner -eq $wantRunner) -and ($s.Version -eq '0.0.1')) "rc=$($r.Rc) outside_same=$(Yn $r.Same) runner=$($s.Runner) state_version=$($s.Version)"
}
# <<< cases
# >>> cases U-B1
function Case-UB1 { Link-Case 'U-B1' 'backup' 'OLD' }
# <<< cases
# >>> cases U-B2
function Case-UB2 { Link-Case 'U-B2' 'program' 'DECOY' }
# <<< cases

# >>> cases U-B3 U-B3b
# ---- U-B3 / U-B3b: a stale backup (no complete marker) holding a file that a background process keeps open (share mode None / ReadWrite). Run 1 with the
# lock held: the old backup cannot be cleared, so the update stops with 43 before the service is stopped. Then the lock is released and run 2 finishes the update.
function Case-UB3([string]$name, [string]$share) {
    Seed-Base $true
    Seed-Stale
    Write-Ascii "$prod\backup\locked.txt" 'L'
    if (-not (Start-Holder "$prod\backup\locked.txt" $share)) { Stop-Holder; Unproven $name 'the background process did not take the lock'; return }
    $r1 = $null
    try { $r1 = Measure-Inst $name ' run1' } finally { Stop-Holder }
    if ($r1.TimedOut) { Unproven $name 'run 1 hit the case limit and was killed'; return }
    $s1 = $r1.State
    $locked = Exists "$prod\backup\locked.txt"
    $cleanup = @($s1.Steps | Where-Object { $_ -eq 'update-backup-cleanup' }).Count
    $failed = @($s1.Steps | Where-Object { $_ -eq 'update-backup' }).Count
    $sameSvc = ($s1.Svc -eq $r1.SvcBefore) -and ($s1.Svc -match '^RUNNING/')
    $ok1 = ($r1.Rc -eq '43') -and $r1.Same -and $locked -and $sameSvc -and ($s1.Runner -eq 'OLD') -and ($s1.Version -eq '0.0.1') -and ($cleanup -eq 1) -and ($failed -eq 1)
    Log "CHECK $name run1: locked.txt_left=$(Yn $locked) service_untouched=$(Yn $sameSvc) update-backup-cleanup_lines=$cleanup update-backup_lines=$failed run1_as_expected=$(Yn $ok1)"
    $r2 = Measure-Inst $name ' run2'
    if ($r2.TimedOut) { Unproven $name 'run 2 hit the case limit and was killed'; return }
    # Run 2 clears the old backup without a second failure: no step line is added to the ones run 1 left.
    $new = @($r2.State.Steps).Count - @($s1.Steps).Count
    $ok2 = (Updated-Ok $r2) -and ($new -eq 0)
    Verdict $name ($ok1 -and $ok2) "rc1=$($r1.Rc) rc2=$($r2.Rc) run1_as_expected=$(Yn $ok1) run2_as_expected=$(Yn $ok2) new_steps_in_run2=$new"
}
# <<< cases

# >>> cases U-B4 U-B5
# ---- U-B4 / U-B5: a stale backup (no marker, no lock) before the update, and the first update with no backup folder at all: both finish with 0.
function Update-Case([string]$name, [bool]$stale) {
    Seed-Base $true
    if ($stale) { Seed-Stale }
    $r = Measure-Inst $name ''
    if ($r.TimedOut) { Unproven $name 'the run hit the case limit and was killed'; return }
    $s = $r.State
    $bad = @($s.Steps | Where-Object { $_ -in @('update-backup', 'update-backup-cleanup', 'update-swap') })
    Log "CHECK $name stale_backup_seeded=$(Yn $stale) failure_steps=[$($bad -join ',')]"
    Verdict $name ((Updated-Ok $r) -and ($bad.Count -eq 0)) "rc=$($r.Rc) runner=$($s.Runner) state_version=$($s.Version) backup=$($s.Backup)"
}
# <<< cases
# >>> cases U-B4
function Case-UB4 { Update-Case 'U-B4' $true }
# <<< cases
# >>> cases U-B5
function Case-UB5 { Update-Case 'U-B5' $false }
# <<< cases

function Try-Case([string]$name, [scriptblock]$sb) {
    if (($script:selected.Count -gt 0) -and ($script:selected -cnotcontains $name)) { Log ('CASE ' + $name + ': NOT-SELECTED'); return }
    $script:caseSw = [Diagnostics.Stopwatch]::StartNew()
    try { & $sb } catch { Log ('CASE ' + $name + ': SCRIPT-ERROR ' + $_.Exception.Message + ' at line ' + $_.InvocationInfo.ScriptLineNumber) }
}

# ---- environment, the installer under test and the stub service
$os = Get-CimInstance -ClassName Win32_OperatingSystem
$csc = Join-Path $env:windir 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
Note 'g7d-env.txt' @("caption=$($os.Caption)", "build=$($os.BuildNumber)", "elevated=$(Test-Elevated)", "user_sid=$([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)", "ps_version=$($PSVersionTable.PSVersion)",
    "ps_64bit=$([Environment]::Is64BitProcess)", "product_folder_existed_at_start=$(Exists $prod)", "signer_file_existed_at_start=$(Exists $signerFile)", "csc=$(Test-Path -LiteralPath $csc)",
    "service_query=$((Cmd 'sc' 'query' 'EcosystemRunner') -split '\r?\n' | Select-Object -First 1)", "utc_now=$([DateTime]::UtcNow.ToString('s'))")
$payloadDir = Join-Path $tree 'installer\guest\payload'
foreach ($f in 'installer-update.exe.b64', 'update-payload.bin.b64') {
    if (-not (Test-Path -LiteralPath (Join-Path $payloadDir $f))) { Log "FATAL: installer\guest\payload\$f is missing"; Copy-Item -LiteralPath $log -Destination (Join-Path $out $logName) -Force; exit 2 }
}
[IO.File]::WriteAllBytes((Join-Path $bin 'installer-update.exe'), [Convert]::FromBase64String((Get-Content -LiteralPath (Join-Path $payloadDir 'installer-update.exe.b64') -Raw)))
$script:payloadText = [Text.Encoding]::ASCII.GetString([Convert]::FromBase64String((Get-Content -LiteralPath (Join-Path $payloadDir 'update-payload.bin.b64') -Raw)))
if (Test-Path -LiteralPath $csc) {
    Note 'g7d-env.txt' @((& $csc /nologo /target:exe "/out:$stubExe" /r:System.ServiceProcess.dll (Join-Path $tree 'installer\guest\stub-service.cs') 2>&1 | Out-String))
}
if (-not (Test-Path -LiteralPath $stubExe)) { Log 'FATAL: the stub service was not compiled'; Copy-Item -LiteralPath $log -Destination (Join-Path $out $logName) -Force; exit 3 }
foreach ($fp in (Join-Path $bin 'installer-update.exe'), $stubExe) {
    Note 'g7d-env.txt' "$(Split-Path -Leaf $fp) size=$((Get-Item -LiteralPath $fp).Length) sha256=$((Get-FileHash -LiteralPath $fp -Algorithm SHA256).Hash)"
}
Log "ENV caption=$($os.Caption) build=$($os.BuildNumber) elevated=$(Test-Elevated) ps_64bit=$([Environment]::Is64BitProcess) payload_bytes=$($script:payloadText.Length)"

$summary = ''
try {
    Test-Gate
    if ($script:gateOk) {
        # >>> cases U-B1
        Try-Case 'U-B1' { Case-UB1 }
        # <<< cases
        # >>> cases U-B2
        Try-Case 'U-B2' { Case-UB2 }
        # <<< cases
        # >>> cases U-B3
        Try-Case 'U-B3' { Case-UB3 'U-B3' 'None' }
        # <<< cases
        # >>> cases U-B3b
        Try-Case 'U-B3b' { Case-UB3 'U-B3b' 'ReadWrite' }
        # <<< cases
        # >>> cases U-B4
        Try-Case 'U-B4' { Case-UB4 }
        # <<< cases
        # >>> cases U-B5
        Try-Case 'U-B5' { Case-UB5 }
        # <<< cases
        Log 'DONE'
    }
} catch {
    Log ('FATAL: ' + $_.Exception.Message)
} finally {
    if ($script:gateOk) {
        try { Reset-All } catch { Log ('CLEANUP: ' + $_.Exception.Message) }
        try { Remove-Stub } catch { Log ('CLEANUP: ' + $_.Exception.Message) }
        try { Remove-Signer } catch { Log ('CLEANUP: ' + $_.Exception.Message) }
        try { Log "AFTER-CLEANUP product_folder=$(Yn (Exists $prod)) uninstall_key=$(Yn (Test-Key)) service=$(Get-Svc) signer_file=$(Yn (Exists $signerFile))" } catch { Log ('CLEANUP: ' + $_.Exception.Message) }
    }
    $summary = Write-Summary
    Copy-Item -LiteralPath $log -Destination (Join-Path $out $logName) -Force
}
Write-Output "update-smoke done: $summary"
exit 0
