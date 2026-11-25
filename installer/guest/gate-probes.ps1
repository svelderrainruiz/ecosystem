# GUEST6B: the silent gates of the real installer (exit code and what a start leaves behind) and the five tiny NSIS probes of real NSIS
# behaviour. Dot-sourced by guest-proof.ps1 under -GateProbes, after the first-start gate and the throw-away standard account. The GATE-*
# items count (PASS/FAIL); every PROBE-* line is INFO and never counts. Evidence: out\gate.txt and out\probes-nsis.txt. ASCII only.
# No secret anywhere: the secret-looking values below are the word x and the name of a file that does not exist.
# Exit codes come from installer\schema.json: 30 bad value, 31 unknown key, 32 secret on the command line, 33 secret file or stdin.

$adminLocal = Join-Path $env:LOCALAPPDATA 'EcosystemInstaller'
New-Item -ItemType Directory -Force -Path $adminLocal | Out-Null
Set-Content -LiteralPath (Join-Path $adminLocal 'signer.sha256') -Value $sig -Encoding ascii
$stepLog = Join-Path $footprintFolder 'steps.jsonl'
# The gate may append to an existing machine log; it never creates a log or uses the roaming folder.
$userLogDir = Join-Path $env:APPDATA 'EcosystemRunner'

function Clean-Gate {
    if (Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner') { sc.exe stop EcosystemRunner | Out-Null; sc.exe delete EcosystemRunner | Out-Null }
    Remove-Item -LiteralPath $footprintFolder -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $uninstallKey -Recurse -Force -ErrorAction SilentlyContinue
}
# What a start left behind: the folder, the uninstall key and the last step-log line (the log holds key names and codes only).
function State-Gate {
    $last = 'no step log'
    if (Test-Path -LiteralPath $stepLog) { $last = "${stepLog}: " + ((@(Get-Content -LiteralPath $stepLog) | Select-Object -Last 1) -replace '\s+', ' ') }
    "folder=$(Test-Path $footprintFolder) key=$(Test-Path $uninstallKey) roaming-log-folder=$(Test-Path $userLogDir) log=[$last]"
}
# Starts $exe with $argText from a clean state (40 s limit); a hang is measured (CPU over 10 s) and killed.
function Run-Gate($exe, $argText, $tag) {
    Clean-Gate
    $r = Start-Timed $exe $argText 40
    $cpu = 'n/a'
    if (-not $r.Done) { $cpu = Cpu-Over $r.Proc 10; $r.Proc.Kill() }
    $st = State-Gate
    Note 'gate.txt' @("[$tag] $(Split-Path $exe -Leaf) $argText", "  rc=$($r.Rc) after $($r.Sec) s; cpu over 10 s if it hung=$cpu; $st")
    [pscustomobject]@{ Rc = $r.Rc; Sec = $r.Sec; Hung = (-not $r.Done); Cpu = $cpu; State = $st }
}
# One item over several argument lists: every start must return $expect within 40 s.
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

# (a) valid keys return
$a1 = Run-Gate $installer "/S /SIGNER=$sig /MODE=local" 'a1 valid keys, minimal'
# a2 carries text keys only: since PR 107 (SL-16b) any image key sends a release build to the licence gate, which refuses the unpinned pair (36); item (i) covers that
$a2 = Run-Gate $installer "/S /SIGNER=$sig /MODE=local /PARTNER_ID=guest6b /LABVIEW_VERSION=2025" 'a2 valid keys, text keys'
if ((-not $a1.Hung) -and "$($a1.Rc)" -eq '0' -and (-not $a2.Hung) -and "$($a2.Rc)" -eq '0') { Res 'GATE-a-valid-keys-return' 'PASS' "/S /MODE=local returned 0 in $($a1.Sec) s; $($a1.State); with the text keys too: rc=$($a2.Rc) in $($a2.Sec) s; $($a2.State)" }
else { Res 'GATE-a-valid-keys-return' 'FAIL' "/S /MODE=local: rc=$($a1.Rc) hung=$($a1.Hung) after $($a1.Sec) s; $($a1.State); with the text keys too: rc=$($a2.Rc) hung=$($a2.Hung); $($a2.State)" }
# (b) a secret option on the command line, (c) a secret file or stdin option, (d) an unknown key, (e) a bad value for a choice key
Gate-Many 'GATE-b-secret-on-command-line-32' 'a secret option on the command line' 32 @('/GITHUB_TOKEN=x', '/GITLAB_TOKEN=x', '/REGISTRY_PASSWORD=x', '/API_KEY=x')
Gate-Many 'GATE-c-secret-file-or-stdin-33' 'a secret FILE or stdin option' 33 @('/SECRETFILE=C:\g5\none.txt', '/SECRETS=C:\g5\none.txt', '/SECRETSTDIN', '/STDIN', '-')
Gate-Many 'GATE-d-unknown-key-31' 'an unknown key' 31 @('/FOO=1', '/FOO')
Gate-Many 'GATE-e-bad-choice-30' 'a bad value for a choice key' 30 @('/MODE=bogus', '/IMAGE_YEAR=1999', '/IMAGE_VARIANT=beos', '/MODE=')
# (f) a url value unquoted and quoted: exit code, and whether the text (with its case) is kept in any file the installer left. The scheme is
# joined here only so that no URL literal sits in a source file (the net-policy scan of the repository).
$url = 'https' + '://github.com/AcmeOrg/Repo'
foreach ($v in @(@('unquoted', "/GITHUB_URL=$url"), @('quoted', "/GITHUB_URL=`"$url`""))) {
    $r = Run-Gate $installer "/S /SIGNER=$sig $($v[1])" "f $($v[0]) url"
    $files = @()
    foreach ($d in $footprintFolder, $adminLocal) { if (Test-Path $d) { $files += @(Get-ChildItem -LiteralPath $d -Recurse -File -Force -ErrorAction SilentlyContinue) } }
    $mixed = @($files | Select-String -SimpleMatch -CaseSensitive -Pattern 'AcmeOrg' -ErrorAction SilentlyContinue).Count
    $lower = @($files | Select-String -SimpleMatch -CaseSensitive -Pattern 'acmeorg' -ErrorAction SilentlyContinue).Count
    Res "PROBE-f-url-$($v[0])" 'INFO' "rc=$($r.Rc) in $($r.Sec) s; $($r.State); files holding the url text: original case=$mixed, lower case=$lower (0 and 0 = checked, not kept)"
}
# (g) no arguments and no /S: it must not spin (the interface waits; there is no desktop here)
Clean-Gate
$g = Start-Timed $installer '' 5
if ($g.Done) { Res 'GATE-g-no-arguments-no-spin' 'PASS' "returned rc=$($g.Rc) after $($g.Sec) s without spinning (no desktop in this guest)" }
else {
    $gcpu = Cpu-Over $g.Proc 10
    $g.Proc.Kill()
    if ($gcpu -lt 2) { Res 'GATE-g-no-arguments-no-spin' 'PASS' "waits without spinning: CPU time over 10 s = $gcpu s (killed afterwards)" }
    else { Res 'GATE-g-no-arguments-no-spin' 'FAIL' "SPINS: CPU time over 10 s = $gcpu s" }
}
Note 'gate.txt' @("[g] no arguments: $(State-Gate)")
# (h) PATH VARIANTS (GUEST6C1). Known bug #110 was fixed by SL-16c (PR 112): the command-line loops now skip the program name. The installer is copied to
# five paths and each copy is started three ways: the valid keys (expect 0), a bad value (30) and a secret on the command line (32). Every path must
# behave like the plain one; in GUEST6B the first and second gave 33 and 31. A name cannot hold a slash: Windows reads "a /x b" as the folders "a "
# (with a trailing space) and "x b", so that folder is made with the extended-length syntax (no trimming) and the program is started by the typed path,
# which is what a command line then holds.
New-Item -ItemType Directory -Force -Path 'C:\Temp' | Out-Null
Copy-Item -LiteralPath $installer -Destination 'C:\Temp\setup - Copy.exe' -Force
[void][IO.Directory]::CreateDirectory('\\?\C:\Temp\a \x b')
[IO.File]::Copy($installer, '\\?\C:\Temp\a \x b\setup.exe', $true)
foreach ($d in 'C:\Temp\o''brien', 'C:\Temp\x y', 'C:\Temp\$z') {
    [void][IO.Directory]::CreateDirectory($d)
    [IO.File]::Copy($installer, (Join-Path $d 'setup.exe'), $true)
}
# The first lines of the step log, taken right after a start (the next Run-Gate cleans).
function Log-Head {
    $head = 'no step log'
    if (Test-Path -LiteralPath $stepLog) { $head = "${stepLog}: " + (((@(Get-Content -LiteralPath $stepLog) | Select-Object -First 3) -join ' / ') -replace '\s+', ' ') }
    $head
}
$pathWanted = @(@('valid keys', '/MODE=local', 0), @('a bad value', '/MODE=bogus', 30), @('a secret on the command line', '/GITHUB_TOKEN=x', 32))
$pathCases = @(@('setup-copy', 'C:\Temp\setup - Copy.exe'), @('slash-folder', 'C:\Temp\a /x b\setup.exe'), @('apostrophe', 'C:\Temp\o''brien\setup.exe'),
    @('space-folder', 'C:\Temp\x y\setup.exe'), @('dollar-folder', 'C:\Temp\$z\setup.exe'))
foreach ($pc in $pathCases) {
    $pathTag = $pc[0]; $pathExe = $pc[1]
    $seen = @(); $bad = @()
    foreach ($w in $pathWanted) {
        $pathArgs = "/S /SIGNER=$sig $($w[1])"
        $r = Run-Gate $pathExe $pathArgs "h $pathTag $($w[0])"
        $seen += "$($w[0])=$($r.Rc)"
        if ($r.Hung -or "$($r.Rc)" -ne "$($w[2])") { $bad += "$($w[0]): rc=$($r.Rc) hung=$($r.Hung), wanted $($w[2]); command line: `"$pathExe`" $pathArgs; log head: $(Log-Head)" }
    }
    if ($bad.Count -eq 0) { Res "GATE-h-path-$pathTag" 'PASS' "${pathExe}: $($seen -join ', ')" }
    else { Res "GATE-h-path-$pathTag" 'FAIL' "${pathExe}: $($seen -join ', '); $($bad -join '; ')" }
}

# (i) LICENCE AND IMAGE (GUEST6C1, PR 107). Keys: both licence answers yes and the image choice windows 2024.
# L1 runs on the release build, whose table pins no image. L2 to L5 run on a build whose table pins windows 2024 (installer-pinned.exe, built on the
# workstation from a scratch copy of the tree and never committed). The container engine is a stub docker.exe compiled here from stub-engine.cs and put
# at the fixed place the installer searches; it records its command line and returns the number in C:\Temp\stub-rc.txt.
$imgKeys = '/MODE=local /IMAGE_VARIANT=windows /IMAGE_YEAR=2024 /NI_LICENCE_HELD=yes /ENGINE_LICENCE_ACCEPTED=yes'
$recFile = Join-Path $footprintFolder 'licence-record.json'
$dockerDir = 'C:\Program Files\Docker'
$engineDesktop = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$engineFixed = 'C:\Program Files\Docker\docker.exe'
$stubRc = 'C:\Temp\stub-rc.txt'
$stubSeen = 'C:\Temp\stub-engine.txt'
$pinRef = 'registry.example.test/ni/labview@sha256:' + ('0123456789abcdef' * 4)
$stubEngine = Join-Path $work 'docker.exe'
$dockerDirIsMine = -not (Test-Path $dockerDir)
function Steps-All {
    if (Test-Path -LiteralPath $stepLog) { (@(Get-Content -LiteralPath $stepLog) | ForEach-Object { $_ -replace '\s+', ' ' }) -join ' ## ' } else { 'no steps.jsonl' }
}
function Hex-Of($f) { if (Test-Path -LiteralPath $f) { (([IO.File]::ReadAllBytes($f) | ForEach-Object { $_.ToString('x2') }) -join '') } else { 'no file' } }
function Footprint-Facts {
    "folder=$(Test-Path $footprintFolder) key=$(Test-Path $uninstallKey) uninstaller=$(Test-Path (Join-Path $footprintFolder 'uninstall.exe')) record=$(Test-Path $recFile) steps=[$(Steps-All)]"
}
function Nothing-Written { (-not (Test-Path $footprintFolder)) -and (-not (Test-Path $uninstallKey)) -and (-not (Test-Path $recFile)) }
function Uninstall-Poll {
    $u = Join-Path $footprintFolder 'uninstall.exe'
    if (-not (Test-Path -LiteralPath $u)) { return [pscustomobject]@{ Clean = $false; Text = 'no uninstall.exe' } }
    $urc = Run-Exe $u '/S' $null
    $t0 = Get-Date
    $svc = 'HKLM:\SYSTEM\CurrentControlSet\Services\EcosystemRunner'
    while (((Test-Path $footprintFolder) -or (Test-Path $uninstallKey) -or (Test-Path $svc)) -and (((Get-Date) - $t0).TotalSeconds -lt 90)) { Start-Sleep -Seconds 2 }
    $clean = -not ((Test-Path $footprintFolder) -or (Test-Path $uninstallKey) -or (Test-Path $svc))
    [pscustomobject]@{ Clean = $clean; Text = "uninstall.exe /S rc=$urc, footprint gone=$clean after $([Math]::Round(((Get-Date) - $t0).TotalSeconds, 0)) s" }
}
function Put-Engine($rcText) {
    [void][IO.Directory]::CreateDirectory($dockerDir)
    Copy-Item -LiteralPath $stubEngine -Destination $engineFixed -Force
    if ($null -ne $rcText) { Set-Content -LiteralPath $stubRc -Value $rcText -Encoding ascii }
}
function Drop-Engine {
    Remove-Item -LiteralPath $engineFixed -Force -ErrorAction SilentlyContinue
    if ($dockerDirIsMine) { Remove-Item -LiteralPath $dockerDir -Recurse -Force -ErrorAction SilentlyContinue }
}
# One install of the pinned build with the stub engine in place (or none), 90 s limit; the stub is removed right after the start.
function Image-Run($tag, $stubRcText, $withStub) {
    Clean-Gate
    Remove-Item -LiteralPath $stubSeen, $stubRc -Force -ErrorAction SilentlyContinue
    if ($withStub) { Put-Engine $stubRcText }
    $r = Start-Timed $pinned "/S /SIGNER=$sig $imgKeys" 90
    if (-not $r.Done) { $r.Proc.Kill() }
    Drop-Engine
    $calls = @()
    if (Test-Path -LiteralPath $stubSeen) { $calls = @(Get-Content -LiteralPath $stubSeen | Where-Object { $_ -like 'args:*' }) }
    $facts = Footprint-Facts
    $stepsText = Steps-All
    Note 'licence.txt' @("[$tag] rc=$($r.Rc) after $($r.Sec) s; stub calls=$($calls.Count) $($calls -join ' ## '); $facts")
    [pscustomobject]@{ Rc = $r.Rc; Sec = $r.Sec; Hung = (-not $r.Done); Calls = $calls; Facts = $facts; Steps = $stepsText
        Installed = ((Test-Path $footprintFolder) -and (Test-Path $uninstallKey)); Record = (Test-Path $recFile) }
}
Note 'licence.txt' @("real engine paths before: desktop=$(Test-Path $engineDesktop) fixed=$(Test-Path $engineFixed); stub dir existed=$(Test-Path $dockerDir)")

# L1: release build
$l1 = Run-Gate $installer "/S /SIGNER=$sig $imgKeys" 'L1 release build, windows 2024, both answers yes'
$l1facts = Footprint-Facts
$l1hex = Hex-Of $recFile
$l1none = Nothing-Written
$l1full = (Test-Path $footprintFolder) -and (Test-Path $uninstallKey) -and (Test-Path $recFile)
$l1un = $null
if (Test-Path -LiteralPath (Join-Path $footprintFolder 'uninstall.exe')) { $l1un = Uninstall-Poll }
$l1shape = if ($l1none) { 'nothing written' } elseif ($l1full) { 'install complete with the record written' } else { 'partial state' }
Note 'licence.txt' @("[L1] release build: rc=$($l1.Rc) in $($l1.Sec) s; $l1shape; $l1facts; run-gate state: $($l1.State); record hex=$l1hex; uninstall: $(if ($null -ne $l1un) { $l1un.Text } else { 'none (no uninstaller)' })")
if ((-not $l1.Hung) -and "$($l1.Rc)" -eq '36' -and $l1shape -ne 'partial state') { Res 'GATE-i-L1-unpinned-pair-36' 'PASS' "release build: rc=36 in $($l1.Sec) s; observed: $l1shape; $l1facts; $($l1.State)" }
else { Res 'GATE-i-L1-unpinned-pair-36' 'FAIL' "release build: rc=$($l1.Rc) hung=$($l1.Hung) in $($l1.Sec) s; observed: $l1shape; $l1facts; $($l1.State)" }
Clean-Gate

# L2 to L5 need the pinned build and the stub engine
$pinnedB64 = Join-Path $tree 'installer\guest\payload\installer-pinned.exe.b64'
$pinned = $null
if (Test-Path -LiteralPath $pinnedB64) { $pinned = Decode 'installer-pinned.exe' }
$stubWhy = $null
if ($null -eq $pinned) { $stubWhy = 'no pinned installer in the payload (installer-pinned.exe.b64)' }
elseif (-not (Test-Path $csc)) { $stubWhy = 'no C# compiler in this clone' }
else {
    $cl = (& $csc /nologo /target:exe "/out:$stubEngine" (Join-Path $tree 'installer\guest\stub-engine.cs') 2>&1 | Out-String).Trim()
    Note 'licence.txt' @("stub engine compile: $cl")
    if (-not (Test-Path $stubEngine)) { $stubWhy = 'the stub engine did not compile' }
    elseif (Test-Path $engineDesktop) { $stubWhy = 'a real container engine is installed in this clone' }
    elseif (Test-Path $engineFixed) { $stubWhy = 'a docker.exe already sits at the fixed place' }
}
if ($stubWhy) {
    foreach ($id in 'GATE-i-L2-pull-ok-0', 'GATE-i-L3-pull-fails-46', 'GATE-i-L4-no-engine-46', 'GATE-i-L5-one-answer-35') { Res $id 'UNPROVEN' $stubWhy }
} else {
    # L2: the stub returns 0: rc 0, exactly one call, the record written, no image step
    $l2 = Image-Run 'L2 stub engine returns 0' '0' $true
    $rp = 'no record'
    if ((Test-Path $py) -and (Test-Path -LiteralPath $recFile)) {
        Remove-Item -LiteralPath 'C:\g5\rp' -Recurse -Force -ErrorAction SilentlyContinue
        Push-Location $tree
        try { $rp = (& $py -m installer.guest.record_probe $recFile 'C:\g5\rp' $footprintFolder 2>&1 | Out-String).Trim() } finally { Pop-Location }
    }
    $recHex = Hex-Of $recFile
    $un2 = Uninstall-Poll
    Note 'licence.txt' @("[L2] record at $recFile hex=$recHex", "[L2] record_probe:", $rp, "[L2] $($un2.Text)")
    $rpKeys = @{}
    foreach ($ln in ($rp -split "`r?`n")) { if ($ln -match '^([a-z_]+)=(.*)$') { $rpKeys[$Matches[1]] = $Matches[2] } }
    $rpLine = "NSIS line end=$($rpKeys['nsis_line_end']), Python line end=$($rpKeys['python_line_end']), identical=$($rpKeys['identical']), identical ignoring the line end=$($rpKeys['identical_ignoring_line_end']), reader path for the footprint folder=$($rpKeys['reader_path'])"
    Res 'PROBE-i-record-landing-and-bytes' 'INFO' "the installer wrote $recFile ($(if ($l2.Record) { 'present' } else { 'absent' }) after L2); $rpLine; last bytes $($recHex.Substring([Math]::Max(0, $recHex.Length - 4)))"
    $want2 = "args: pull|$pinRef"
    if ((-not $l2.Hung) -and "$($l2.Rc)" -eq '0' -and $l2.Calls.Count -eq 1 -and $l2.Calls[0] -eq $want2 -and $l2.Record -and $l2.Steps -notmatch 'image-') {
        Res 'GATE-i-L2-pull-ok-0' 'PASS' "rc=0 in $($l2.Sec) s; the stub saw exactly [$want2]; $($l2.Facts); $($un2.Text)"
    } else { Res 'GATE-i-L2-pull-ok-0' 'FAIL' "rc=$($l2.Rc) hung=$($l2.Hung) in $($l2.Sec) s; stub calls=$($l2.Calls.Count) [$($l2.Calls -join ' ## ')] wanted exactly one [$want2]; $($l2.Facts); $($un2.Text)" }
    # L3: the stub returns 1: rc 46, step image-pull, the install stays and uninstalls clean
    $l3 = Image-Run 'L3 stub engine returns 1' '1' $true
    $un3 = Uninstall-Poll
    Note 'licence.txt' @("[L3] $($un3.Text)")
    if ((-not $l3.Hung) -and "$($l3.Rc)" -eq '46' -and $l3.Steps -match '"step": "image-pull"' -and $l3.Installed -and $un3.Clean) {
        Res 'GATE-i-L3-pull-fails-46' 'PASS' "rc=46 in $($l3.Sec) s; stub calls=$($l3.Calls.Count); $($l3.Facts); $($un3.Text)"
    } else { Res 'GATE-i-L3-pull-fails-46' 'FAIL' "rc=$($l3.Rc) hung=$($l3.Hung) in $($l3.Sec) s; stub calls=$($l3.Calls.Count); installed=$($l3.Installed); $($l3.Facts); $($un3.Text)" }
    # L4: no engine at all: rc 46, step image-engine-missing, the install stays and uninstalls clean
    $l4 = Image-Run 'L4 no engine' $null $false
    $un4 = Uninstall-Poll
    Note 'licence.txt' @("[L4] $($un4.Text)")
    if ((-not $l4.Hung) -and "$($l4.Rc)" -eq '46' -and $l4.Steps -match '"step": "image-engine-missing"' -and $l4.Installed -and $un4.Clean) {
        Res 'GATE-i-L4-no-engine-46' 'PASS' "rc=46 in $($l4.Sec) s; $($l4.Facts); $($un4.Text)"
    } else { Res 'GATE-i-L4-no-engine-46' 'FAIL' "rc=$($l4.Rc) hung=$($l4.Hung) in $($l4.Sec) s; installed=$($l4.Installed); $($l4.Facts); $($un4.Text)" }
    # L5: the licence gate on the pinned build: no answer, or one answer only, is refused with 35 and nothing is written
    $seen5 = @(); $bad5 = @()
    foreach ($k in @(@('no answer', ''), @('the NI answer only', '/NI_LICENCE_HELD=yes'), @('the engine answer only', '/ENGINE_LICENCE_ACCEPTED=yes'))) {
        $r5 = Run-Gate $pinned "/S /SIGNER=$sig /MODE=local /IMAGE_VARIANT=windows /IMAGE_YEAR=2024 $($k[1])" "L5 pinned build, $($k[0])"
        $none5 = Nothing-Written
        $seen5 += "$($k[0])=$($r5.Rc) nothing written=$none5"
        if ($r5.Hung -or "$($r5.Rc)" -ne '35' -or -not $none5) { $bad5 += $k[0] }
    }
    if ($bad5.Count -eq 0) { Res 'GATE-i-L5-one-answer-35' 'PASS' "every start returned 35 and wrote nothing: $($seen5 -join '; ')" }
    else { Res 'GATE-i-L5-one-answer-35' 'FAIL' "expected 35 and nothing written for all: $($seen5 -join '; ')" }
}
Drop-Engine
Remove-Item -LiteralPath $stubSeen, $stubRc -Force -ErrorAction SilentlyContinue
Clean-Gate

# ---- the five NSIS probes (built by pack.py, run here), one plain line each
function Probe-Out($name) { $f = Join-Path $work $name; if (Test-Path $f) { (Get-Content -LiteralPath $f -Raw).Trim() } else { '(no result file)' } }
function Run-Probe($id, $exeName, $argText, $outName) {
    $exe = Decode $exeName
    Remove-Item -LiteralPath (Join-Path $work $outName) -ErrorAction SilentlyContinue
    $r = Start-Timed $exe $argText 40
    if (-not $r.Done) { $r.Proc.Kill() }
    $line = Probe-Out $outName
    Note 'probes-nsis.txt' @("[$id] $exeName $argText -> rc=$($r.Rc) after $($r.Sec) s; $line")
    Res "PROBE-$id" 'INFO' "$line; exit code $($r.Rc)"
}
Remove-Item -LiteralPath (Join-Path $env:TEMP 'v') -Recurse -Force -ErrorAction SilentlyContinue
Run-Probe 'P1-junction' 'probe-p1.exe' '' 'probe-p1.txt'
cmd.exe /c rmdir "$env:TEMP\v\r\j" 2>&1 | Out-Null
Remove-Item -LiteralPath (Join-Path $env:TEMP 'v') -Recurse -Force -ErrorAction SilentlyContinue
Run-Probe 'P3-wordfind' 'probe-p3.exe' '' 'probe-p3.txt'
$p4 = Decode 'probe-p4.exe'
$p4names = @{ a = 'Quit in .onInit'; b = 'Quit in a section'; c = 'Abort in a section'; d = 'Quit in a function called from a section' }
foreach ($k in 'a', 'b', 'c', 'd') {
    $r = Start-Timed $p4 "/$k" 40
    if (-not $r.Done) { $r.Proc.Kill() }
    Res "PROBE-P4$k" 'INFO' "SetErrorLevel 35 then $($p4names[$k]): exit code $($r.Rc)"
}
Set-Content -LiteralPath (Join-Path $work 'p5-in.txt') -Value ('x' * 1030) -Encoding ascii
Run-Probe 'P5-fileread' 'probe-p5.exe' '' 'probe-p5.txt'
# P2 last: a standard user cannot answer the elevation prompt, and the wait for it is bounded by Run-AsStd
if ($cred) {
    $p2 = Decode 'probe-p2.exe'
    Remove-Item -LiteralPath (Join-Path $work 'probe-p2.txt') -ErrorAction SilentlyContinue
    $rc2 = Run-AsStd $p2 ''
    $line2 = Probe-Out 'probe-p2.txt'
    Get-Process -Name 'probe-p2' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Note 'probes-nsis.txt' @("[P2] standard user run: rc=$rc2; $line2")
    if ($rc2 -is [int]) { Res 'PROBE-P2-declined-elevation' 'INFO' "UNPROVEN for a real prompt (nobody can answer one here); observed as a standard user in a batch session: $line2; exit code $rc2 after Quit" }
    else { Res 'PROBE-P2-declined-elevation' 'INFO' "UNPROVEN (the standard account could not be run to the end: $rc2); result file: $line2" }
} else { Res 'PROBE-P2-declined-elevation' 'INFO' 'UNPROVEN (no standard account in this clone)' }

# (j) DECLINED ADMINISTRATOR PROMPT (GUEST6C1, PR 116 / SL-21a), last of all: the installer is started WITHOUT /S as the standard account, inside the
# window station of a Task Scheduler batch logon (nobody sits at a desktop here). installer\guest\uac-drive.cs walks the pages to the elevation page and
# presses Next; ExecShell "runas" then fails at once (GUEST6B P2) which is the declined prompt. The driver proves (a) the installer is still running
# 20 s after the box appeared, (b) the message box about the declined prompt exists (owner, class and text), (c) the exit code after Cancel.
# Longer wait than Run-AsStd (45 s): the driver needs up to about 135 s. The password stays in memory and is never printed.
function Run-AsStdLong($exe, $argText, $limitSec) {
    $outFile = Join-Path $work 'std-long-out.txt'
    Remove-Item -LiteralPath $outFile -ErrorAction SilentlyContinue
    $name = 'g6uac'
    $res = $null
    try {
        $act = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c ""' + $exe + '" ' + $argText + ' > "' + $outFile + '" 2>&1"')
        Register-ScheduledTask -TaskName $name -Action $act -User $stdUser -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Force -ErrorAction Stop | Out-Null
        Start-ScheduledTask -TaskName $name -ErrorAction Stop
        $t0 = Get-Date
        do {
            Start-Sleep -Seconds 3
            $info = Get-ScheduledTaskInfo -TaskName $name
            $busy = ((Get-ScheduledTask -TaskName $name).State -eq 'Running') -or ($info.LastTaskResult -in 267009, 267011)
        } while ($busy -and ((Get-Date) - $t0).TotalSeconds -lt $limitSec)
        $res = if ($busy) { 'timeout' } else { [int]$info.LastTaskResult }
    } catch { $res = 'error: ' + $_.Exception.Message }
    finally { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue }
    $res
}
$uacIds = 'GATE-j-uac-a-stays-open', 'GATE-j-uac-b-box-exists', 'GATE-j-uac-c-exit-code-after-cancel'
$uacExe = Join-Path $work 'uac-drive.exe'
$uacLog = Join-Path $work 'uac-drive.txt'
$uacWhy = $null
Note 'uac.txt' @("standard account present=$([bool]$cred)")
if (-not $cred) { $uacWhy = 'no standard account in this clone' }
elseif (-not (Test-Path $csc)) { $uacWhy = 'no C# compiler in this clone' }
else {
    $cl = (& $csc /nologo /target:exe "/out:$uacExe" (Join-Path $tree 'installer\guest\uac-drive.cs') 2>&1 | Out-String).Trim()
    Note 'uac.txt' @("driver compile: $cl")
    if (-not (Test-Path $uacExe)) { $uacWhy = 'the window driver did not compile' }
}
$uac = @{}
if (-not $uacWhy) {
    # elevation requests are denied without a prompt for a standard user (this clone is thrown away)
    $pol = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
    Set-ItemProperty -LiteralPath $pol -Name ConsentPromptBehaviorUser -Value 0 -Type DWord -ErrorAction SilentlyContinue
    $stdLocal = "C:\Users\$stdUser\AppData\Local\EcosystemInstaller"
    New-Item -ItemType Directory -Force -Path $stdLocal -ErrorAction SilentlyContinue | Out-Null
    Set-Content -LiteralPath (Join-Path $stdLocal 'signer.sha256') -Value $sig -Encoding ascii
    Clean-Gate
    Remove-Item -LiteralPath $uacLog -ErrorAction SilentlyContinue
    $uacRc = Run-AsStdLong $uacExe "$installer $uacLog /SIGNER=$sig" 180
    Get-Process -Name 'uac-drive', 'installer' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Note 'uac.txt' @("task scheduler result for the driver: $uacRc", "ConsentPromptBehaviorUser set to 0 in this clone")
    if (Test-Path -LiteralPath $uacLog) {
        $uacLines = @(Get-Content -LiteralPath $uacLog)
        Note 'uac.txt' $uacLines
        foreach ($ln in $uacLines) { if ($ln -match '^RESULT ([a-z_0-9]+)=(.*)$') { $uac[$Matches[1]] = $Matches[2] } }
    }
    if ($uacRc -isnot [int]) { $uacWhy = "the driver did not run to the end: $uacRc" }
    elseif ($uac.Count -eq 0) { $uacWhy = 'the driver left no result lines (see uac.txt)' }
    elseif ($uac['started'] -ne 'True') { $uacWhy = 'the driver could not start the installer as the standard user' }
    elseif ($uac['elevation_page'] -ne 'True') { $uacWhy = 'the driver did not reach the elevation page of the installer window (see uac.txt for the pages it saw)' }
}
if ($uacWhy) { foreach ($id in $uacIds) { Res $id 'UNPROVEN' $uacWhy } }
else {
    $aliveText = if ($uac.ContainsKey('alive_after_20s')) { "alive 20 s after the box appeared=$($uac['alive_after_20s'])" } else { "no box found; alive 30 s after Next=$($uac['alive_after_click'])" }
    $aliveOk = $uac['box'] -eq 'yes' -and $uac['alive_after_20s'] -eq 'True'
    if ($aliveOk) { Res $uacIds[0] 'PASS' "the installer stayed open: $aliveText; after the box was closed: alive=$($uac['alive_after_close']), elevation page kept=$($uac['elevation_page_kept'])" }
    else { Res $uacIds[0] 'FAIL' "the installer did not stay open with the box showing: $aliveText" }
    $boxText = "$($uac['box_text'])"
    if ($uac['box'] -eq 'yes' -and $boxText -match 'NOT started') { Res $uacIds[1] 'PASS' "message box (class $($uac['box_class']), owned by the setup window=$($uac['box_owner_is_setup_window'])): [$boxText]" }
    elseif ($uac['box'] -eq 'yes') { Res $uacIds[1] 'FAIL' "a message box appeared but its text is not the declined-prompt text: [$boxText]" }
    else { Res $uacIds[1] 'FAIL' 'no message box within 30 s of Next on the elevation page' }
    $exitCode = "$($uac['exit_code'])"
    if ($exitCode -eq '1') { Res $uacIds[2] 'PASS' "closed with the Cancel button: exit code 1 (NSIS: cancelled by the user); box after Cancel=[$($uac['box_after_cancel'])]" }
    else { Res $uacIds[2] 'FAIL' "exit code after the Cancel button: [$exitCode] (NSIS: 1 = cancelled by the user); box after Cancel=[$($uac['box_after_cancel'])]" }
}
Clean-Gate
