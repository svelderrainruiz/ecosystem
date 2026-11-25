# Run from the kit's disposable container. case_script reads the verdict from out\*.txt.
$ErrorActionPreference = 'Stop'
$out = New-Item -ItemType Directory -Force -Path 'out'
$report = Join-Path $out.FullName 'log-escape.txt'
[IO.File]::WriteAllText($report, '')
function Log([string]$line) { Add-Content -LiteralPath $report -Value $line -Encoding ascii }

function Expand-Payload([string]$name) {
    $exe = Join-Path $PSScriptRoot $name
    $encoded = Join-Path $PSScriptRoot "payload\$name.b64"
    [IO.File]::WriteAllBytes($exe, [Convert]::FromBase64String([IO.File]::ReadAllText($encoded)))
    return $exe
}

function Run-Exe([string]$exe, [string]$arguments) {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $exe
    $start.Arguments = $arguments
    $start.UseShellExecute = $false
    $process = [Diagnostics.Process]::Start($start)
    try {
        $process.WaitForExit()
        return $process.ExitCode
    } finally { $process.Dispose() }
}

function Read-StepLog {
    foreach ($line in [IO.File]::ReadAllLines($steps)) {
        # ConvertFrom-Json can return nothing for a blank line. Count physical records, not pipeline output.
        if (-not $line.TrimStart().StartsWith('{')) { throw 'not a step object' }
        ConvertFrom-Json -InputObject $line -ErrorAction Stop
    }
}

function Test-Step($record, [string]$step, [string]$command, [int]$code) {
    return ($record.step -is [string] -and $record.step -ceq $step -and
            $record.command -is [string] -and $record.command -ceq $command -and
            ($record.exit_code -is [int] -or $record.exit_code -is [long]) -and $record.exit_code -eq $code)
}

try {
    $phase = 'LE1 setup'
    $steps = Join-Path $env:ProgramData 'EcosystemRunner\steps.jsonl'
    if (Test-Path -LiteralPath $steps) { throw 'pre-existing log' }
    $phase = 'LE1 harness'
    if ((Run-Exe (Expand-Payload 'log-harness.exe') '') -ne 0) { throw 'harness exit' }
    $phase = 'LE1 JSON'
    $rows = @(Read-StepLog)
    $phase = 'LE1 records'
    if ($rows.Count -ne 3 -or -not (Test-Step $rows[2] 'A"B' 'A\Q' 31)) { throw 'harness records' }
    Log ('[LE1] lines={0} json_ok={0} step={1} command={2} exit={3}' -f $rows.Count, $rows[2].step, $rows[2].command, $rows[2].exit_code)

    $phase = 'LE2 payload'
    $installer = Expand-Payload 'installer.exe'
    # NSIS reads the raw Windows command line, not CRT argv. Cmdline_Next drops quotes;
    # ValidateSilentKeys refuses an unclosed quote BEFORE unknown keys. Other key names retain their slash.
    $cases = @(
        @{ args = '/S /A"B=1'; step = 'bad-value';   command = 'command-line'; code = 30 }
        @{ args = '/S /A\Q=1'; step = 'unknown-key'; command = '/A\Q';         code = 31 }
        @{ args = '/S /FOO=1'; step = 'unknown-key'; command = '/FOO';         code = 31 }
    )
    $n = 0
    foreach ($case in $cases) {
        $n++
        $phase = "LE2 arg=$n reset"
        # .onInit sets LogExistingOnly: early refusals append only if the file already exists.
        Remove-Item -LiteralPath $steps
        [IO.File]::WriteAllText($steps, '')
        $phase = "LE2 arg=$n process"
        $rc = Run-Exe $installer $case.args
        $phase = "LE2 arg=$n exit=$rc"
        if ($rc -ne $case.code) { throw 'installer exit' }
        $phase = "LE2 arg=$n JSON"
        $rows = @(Read-StepLog)
        $phase = "LE2 arg=$n one record"
        # The log was emptied above, so the refusal must be its only record.
        if ($rows.Count -ne 1 -or -not (Test-Step $rows[0] $case.step $case.command $rc)) { throw 'installer record' }
        Log ('[LE2] arg={0} exit={1} lines={2} json_ok={2} step={3} command={4}' -f $n, $rc, $rows.Count, $rows[0].step, $rows[0].command)
    }
    Log '[verdict] c-log-escape PASS'
} catch {
    # Native/JSON exception messages can contain paths or unvalidated input. Report only the fixed check.
    Log "[verdict] c-log-escape FAIL $phase"
}
