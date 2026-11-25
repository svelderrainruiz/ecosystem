# The harmless "will it work on this PC?" check (INST-REQ-033, ARCH-4): read-only, no administrator rights, no secrets, changes nothing.
# The edition comes from one replaceable source: -EditionFile (a one-line text file) or the live system.
# The accepted list below must equal installer/schema.json (a test compares them).
[CmdletBinding()]
param([string]$EditionFile = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$AcceptedExact = @('Windows 11 Pro', 'Windows 11 Enterprise')
$AcceptedPrefix = @('Windows Server 2022', 'Windows Server 2025')
$ExitRefused = 34

try {
    if ($EditionFile) {
        $caption = (Get-Content -LiteralPath $EditionFile -TotalCount 1)
    } else {
        $caption = (Get-CimInstance -ClassName Win32_OperatingSystem).Caption
    }
} catch {
    Write-Output 'no: the Windows edition could not be read on this PC'
    exit $ExitRefused
}
$name = (($caption -replace '^\s*(?i:microsoft)\s+', '') -replace '\s+', ' ').Trim()

$ok = $false
if ($name -notmatch '(?i)ltsc') {
    if ($AcceptedExact | Where-Object { $_ -ieq $name }) { $ok = $true }
    if ($AcceptedPrefix | Where-Object { $name -ieq $_ -or $name -like "$_ *" }) { $ok = $true }
}

if ($ok) {
    Write-Output "yes: $name is a supported edition"
    exit 0
}
Write-Output "no: $name is not supported; this installer runs only on $($AcceptedExact + $AcceptedPrefix -join ', ')"
exit $ExitRefused
