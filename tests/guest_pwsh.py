"""Run the REAL functions of a guest driver in a scratch pwsh (GUEST7 fix round). The driver is parsed with the PowerShell AST, the named
functions and top-level constants are taken from it verbatim, then a scenario runs against a temp folder; nothing outside that folder is
touched. Tests that use it are skipped when pwsh is absent."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PWSH = shutil.which("pwsh")
requires_pwsh = unittest.skipUnless(PWSH, "pwsh absent")

RUNNER = r"""
$ErrorActionPreference = 'Stop'
$errs = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:G7_SCRIPT, [ref]$null, [ref]$errs)
if ($errs -and $errs.Count) { throw 'parse errors' }
$defs = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)
foreach ($name in ($env:G7_FUNCS -split ',')) {
    $d = @($defs | Where-Object { $_.Name -eq $name })
    if ($d.Count -ne 1) { throw "function $name is defined $($d.Count) times" }
    . ([scriptblock]::Create($d[0].Extent.Text))
}
$asg = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] }, $false)
foreach ($name in ($env:G7_VARS -split ',')) {
    if (-not $name) { continue }
    $a = @($asg | Where-Object { $_.Left.Extent.Text -in @("`$$name", "`$script:$name") })
    if ($a.Count -ne 1) { throw "assignment of $name found $($a.Count) times" }
    Invoke-Expression $a[0].Extent.Text
}
Set-StrictMode -Version Latest
$base = $env:G7_TMP
. $env:G7_SCENARIO
"""


def run_functions(script, functions, scenario, variables=()):
    """Run the PowerShell text `scenario` with `functions` and `variables` of the driver `script` loaded; returns its output lines."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = os.path.realpath(tmp)
        work = Path(tmp, "work")
        work.mkdir()
        runner = Path(tmp, "runner.ps1")
        scen = Path(tmp, "scenario.ps1")
        runner.write_text(RUNNER, encoding="ascii")
        scen.write_text(scenario, encoding="ascii")
        env = {**os.environ, "G7_SCRIPT": str(script), "G7_FUNCS": ",".join(functions), "G7_VARS": ",".join(variables),
               "G7_TMP": str(work), "G7_SCENARIO": str(scen)}
        r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(runner)], capture_output=True, text=True, env=env,
                           cwd=tmp, timeout=120)
    if r.returncode != 0:
        raise AssertionError("pwsh failed (%d): %s%s" % (r.returncode, r.stdout, r.stderr))
    return r.stdout.splitlines()
