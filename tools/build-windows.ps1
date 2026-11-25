<#
Builds the installer test kit on this Windows PC (installer/BUILD-WINDOWS.md, #243). The VS Code task "Installer: build test kit" runs it.

It uses a separate clean clone, <Work>\src, so edits in the folder you have open in VS Code never block the build. It checks out
origin/<Branch>, writes the stand-in payload, then runs installer.build check, vmkit build and vmkit verify. If the kit for that
commit already exists and is not empty, it verifies that kit again instead of rebuilding it. It installs nothing and never starts
installer.exe. It lives outside installer/ because everything under installer/ is installer source (build file list, footprint scan).

It stops at the first failing step and exits with that step's exit code. A refusal of its own is one line and exit code 2.
#>
param(
    [string]$Branch = 'develop',
    [string]$Work = '',
    [int]$Request = 0
)
# Exit codes decide; Git and Python write progress to stderr, which must not stop Windows PowerShell 5.1.
$ErrorActionPreference = 'Continue'
Set-StrictMode -Version Latest

$Repo = 'svelderrainruiz/ecosystem-control'
$PayloadText = 'Stand-in runner payload for a UI test build.'

function Stop-Build([string]$Line, [int]$Code) {
    Write-Host $Line
    exit $Code
}

function Invoke-Step([string]$Name, [scriptblock]$Run, [string]$Hint = 'Fix what the line above names and run the task again.') {
    Write-Host "== $Name"
    $global:LASTEXITCODE = 0
    & $Run
    if ($LASTEXITCODE -ne 0) { Stop-Build "STOPPED at $Name (exit $LASTEXITCODE). $Hint" $LASTEXITCODE }
}

if ($Branch -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$' -or $Branch -match '\.\.') {
    Stop-Build "Refused: branch name '$Branch' is not a plain branch name." 2
}
if (-not $Work) {
    if (-not $env:USERPROFILE) { Stop-Build 'Refused: USERPROFILE is not set; pass -Work.' 2 }
    $Work = Join-Path $env:USERPROFILE 'installer-test'
}
$src = Join-Path $Work 'src'
$payload = Join-Path $Work 'stand-in-payload.txt'
$tools = @('git', 'python')
if (-not (Test-Path -LiteralPath $src)) { $tools += 'gh' }
foreach ($tool in $tools) {
    if (-not (Get-Command $tool -CommandType Application -ErrorAction SilentlyContinue)) { Stop-Build "Refused: $tool is not on PATH." 2 }
}
New-Item -ItemType Directory -Force -Path $Work -ErrorAction Stop | Out-Null

if (-not (Test-Path -LiteralPath $src)) {
    Invoke-Step "clone $Repo into $src" { gh repo clone $Repo $src }
}
Invoke-Step 'fetch origin' { git -C $src fetch --prune origin }
Invoke-Step "check out origin/$Branch" { git -C $src checkout --detach "origin/$Branch" }
$head = (git -C $src rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or "$head" -notmatch '^[0-9a-f]{40}$') { Stop-Build 'Refused: could not read the commit of the checkout.' 2 }
$c = "$head".Substring(0, 12)
$kit = Join-Path (Join-Path $Work 'kit') $c

Set-Content -LiteralPath $payload -Value $PayloadText -Encoding ascii -ErrorAction Stop
$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location -LiteralPath $src -ErrorAction Stop
try {
    Invoke-Step 'installer.build check' { python -m installer.build check }
    $earlier = (Test-Path -LiteralPath $kit) -and @(Get-ChildItem -LiteralPath $kit -Force -ErrorAction Stop).Count -gt 0
    if ($earlier) {
        Write-Host "Kit $c already exists; verifying it again. Delete $kit to rebuild it."
        Invoke-Step 'vmkit verify' { python -m installer.guest.vmkit verify $kit } "The kit folder is left from an earlier run that did not finish: delete $kit and run the task again."
    }
    else {
        Invoke-Step 'vmkit build' { python -m installer.guest.vmkit build --out $kit --payload $payload }
        Invoke-Step 'vmkit verify' { python -m installer.guest.vmkit verify $kit }
    }
}
finally {
    Pop-Location
}

$sums = Join-Path $kit 'SHA256SUMS'
$mentions = @(Get-Content -LiteralPath $sums -ErrorAction Stop | Where-Object { $_ -match 'installer\.exe' })
$line = @($mentions -match 'installer\.exe$')
Write-Host "KIT OK $kit"
Write-Host "Commit: $head (origin/$Branch)"
if ($line.Count -eq 1) {
    Write-Host "installer.exe line of SHA256SUMS: $($line[0])"
    if ($mentions.Count -eq 1 -and $line[0] -cmatch '^([0-9a-f]{64})  installer\.exe$') {
        $hash = $Matches[1]
        $repoPath = ($Repo.Split('/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/'
        $url = "https://github.com/$repoPath/issues/new?template=$([uri]::EscapeDataString('installer-test-run.yml'))"
        $url += "&built-from=$([uri]::EscapeDataString($c))&installer-sha256=$([uri]::EscapeDataString($hash))"
        if ($Request -gt 0) { $url += "&request=$([uri]::EscapeDataString("#$Request"))" }
        Write-Host "Report your run: $url"
    }
}
Write-Host 'Nothing was installed and installer.exe was not started.'
exit 0
