# vm-state.ps1 (VM-1, ecosystem-control#137): a READ-ONLY report of what the installer leaves on this PC, for installer\VM-TEST.md.
# It prints names, sizes and yes/no only: never a file's content, never steps.jsonl, no secret, no user or host name, no network, no write.
# Run it from an elevated PowerShell (the program-data folder is locked to administrators; Windows 11 blocks an unsigned script by default, hence Bypass for this one run):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\vm-state.ps1 -Step T13
# The label after -Step starts every line, so a line can be copied into a report as it is. ASCII only.
# Status: 0 when every read worked, 1 when a read failed (the last line says which; see How to report in VM-TEST.md).
param([ValidatePattern('^[A-Za-z0-9._-]{0,16}$')][string]$Step = '-')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$failed = $false

function Say($text) { Write-Output ('[{0}] {1}' -f $Step, $text) }
function YesNo($flag) { if ($flag) { 'yes' } else { 'no' } }

# The principal of an access rule by its well-known SID, so no account name is ever printed and the words do not depend on the Windows language.
function Who($ref) {
    $sid = ''
    try { $sid = $ref.Translate([Security.Principal.SecurityIdentifier]).Value } catch { $sid = '' }
    switch -Regex ($sid) {
        '^S-1-5-18$'      { 'SYSTEM' }
        '^S-1-5-32-544$'  { 'Administrators' }
        '^S-1-5-80-'      { 'a service account' }
        default           { '<other principal>' }
    }
}

# An unexpected error ends the report with status 1. Only the kind of error is printed: its text can hold a path.
trap { Say ('a read failed: {0}' -f $_.Exception.GetType().Name); Say 'end of report: a read failed, status 1'; exit 1 }

$os = Get-CimInstance -ClassName Win32_OperatingSystem
Say ('windows: {0}, build {1}, {2}' -f $os.Caption, $os.BuildNumber, $os.OSArchitecture)
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$admin = $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Say ('elevated: {0}' -f (YesNo $admin))
if (-not $admin) { Say 'WARNING: not elevated. The folder is locked to administrators, so a file below it may read as absent only because it cannot be seen.' }

$dir = Join-Path $env:ProgramData 'EcosystemRunner'
$folder = Get-Item -LiteralPath $dir -Force -ErrorAction SilentlyContinue
if (-not $folder) {
    Say 'folder C:\ProgramData\EcosystemRunner: absent'
} else {
    Say ('folder C:\ProgramData\EcosystemRunner: present, is a link: {0}' -f (YesNo ($folder.Attributes.ToString() -match 'ReparsePoint')))
    $acl = Get-Acl -LiteralPath $dir -ErrorAction SilentlyContinue
    if ($acl) {
        $who = @($acl.Access | ForEach-Object { Who $_.IdentityReference } | Sort-Object -Unique) -join ', '
        Say ('folder access: {0}; inheritance removed: {1}' -f $who, (YesNo $acl.AreAccessRulesProtected))
    } else {
        Say 'folder access: cannot be read from this session'
        $failed = $true
    }
    $known = 'installer-state.json', 'runner-mode.json', 'runner-forge.json', 'licence-record.json', 'steps.jsonl', 'uninstall.exe', 'program', 'backup'
    foreach ($name in $known) {
        $f = Get-Item -LiteralPath (Join-Path $dir $name) -Force -ErrorAction SilentlyContinue
        if (-not $f) { $what = 'absent' } elseif ($f.PSIsContainer) { $what = 'present (folder)' } else { $what = 'present, {0} bytes' -f $f.Length }
        Say ('  {0}: {1}' -f $name, $what)
    }
    $other = @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | Where-Object { $known -notcontains $_.Name }).Count
    Say ('  other entries in the folder: {0}' -f $other)
}

$signer = Get-Item -LiteralPath (Join-Path $env:LOCALAPPDATA 'EcosystemInstaller\signer.sha256') -Force -ErrorAction SilentlyContinue
if ($signer) { $what = 'present, {0} bytes' -f $signer.Length } else { $what = 'absent' }
Say ('per-user file %LOCALAPPDATA%\EcosystemInstaller\signer.sha256: {0}' -f $what)

$service = Get-Service -Name 'EcosystemRunner' -ErrorAction SilentlyContinue
if ($service) { $what = 'present, status {0}' -f $service.Status } else { $what = 'absent' }
Say ('service EcosystemRunner: {0}' -f $what)

$uninstall = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner'
$exe = Join-Path $dir 'uninstall.exe'
foreach ($view in 'Registry64', 'Registry32') {
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey('LocalMachine', $view)
    $key = $base.OpenSubKey($uninstall)
    if (-not $key) {
        Say ('uninstall key EcosystemRunner, {0} view: absent' -f $view)
    } else {
        Say ('uninstall key EcosystemRunner, {0} view: present, values: {1}' -f $view, (($key.GetValueNames() | Sort-Object) -join ', '))
        Say ('  DisplayName: {0}' -f $key.GetValue('DisplayName'))
        Say ('  DisplayVersion: {0}' -f $key.GetValue('DisplayVersion'))
        Say ('  UninstallString is the quoted uninstall.exe of the folder: {0}' -f (YesNo ($key.GetValue('UninstallString') -ceq ('"' + $exe + '"'))))
        Say ('  QuietUninstallString is the same with /S: {0}' -f (YesNo ($key.GetValue('QuietUninstallString') -ceq ('"' + $exe + '" /S'))))
        $key.Close()
    }
    $base.Close()
}
if ($failed) { Say 'end of report: a read failed, status 1'; exit 1 }
Say 'end of report: every read worked, status 0'
exit 0
