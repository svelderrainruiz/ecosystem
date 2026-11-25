#!/usr/bin/env python3
"""Container lane (ecosystem-control#184 step 4): a kit that runs the guest drivers in throwaway Windows containers.

  python3 -m installer.guest.container PACKDIR OUTDIR --order L<n> [--case NAME ...] [--vm-kit DIR] [--image ltsc2025|ltsc2022] [--parallel N] [--sha SHA]

PACKDIR is the output of `python3 -m installer.guest.pack PACKDIR`. OUTDIR receives `kit-<12 hex>/` (the files the chosen drivers need,
with line endings normalized and optional update-case pruning, one `c-<case>.ps1` per case and `SHA256SUMS`) and `l<n>-ctr.ps1`, the host wrapper (PowerShell 7) that checks the
kit against its embedded hash table and starts every container under the gates of #184. `--vm-kit DIR` supplies the VM kit for `fresh-install`
and the `uninstall-edge`, `gate-edge` and `install-edge` cases; its `installer.exe`, `VM-TEST.md` and `vm-state.ps1` must match that directory's `SHA256SUMS`, and the ones a
selected case lists are copied byte for byte. Every other shipped
file is ASCII with CRLF line ends. Standard library only; nothing here starts a container or touches Docker.
"""
import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

REPO = "mcr.microsoft.com/windows/servercore"
# The only two images of #184 gate 2, pinned by digest.
IMAGES = {
    "ltsc2025": "sha256:a43c2d41a3d6e940dec865731e2f5db5c3e03f705f5300ef0b5817d3e01ecfb1",
    "ltsc2022": "sha256:f1a914079973258061ddbc95a9af579eab2ee252a6fddb254b1be5d769761acd",
}
# #184 gate 4: list only this lane's containers; inspect the selected digest directly.
LIST_CONTAINERS = "ps -a --filter label=ecosystem.proof=1 --format '{{.ID}} {{.Status}}'"
WORK = r"ecosystem-work"
PARALLEL_TIMEOUT_SECONDS = 3600

# A case runs one driver from C:\w (the tree root, as `winev run` does). Files: (path in the tree, "pack" or "repo").
CASES = {
    "link-probes": {
        "driver": "link-probes.ps1",
        "args": "",
        "files": (("installer/guest/payload/probe-p6.exe.b64", "pack"),),
    },
    "log-escape": {
        "driver": "log-escape.ps1",
        "args": "",
        "files": (("installer/guest/payload/log-harness.exe.b64", "pack"),
                  ("installer/guest/payload/installer.exe.b64", "pack")),
    },
    "uninstall-smoke": {
        "driver": "uninstall-smoke.ps1",
        "args": "",
        "files": (("installer/guest/payload/uninstall-harness.exe.b64", "pack"),),
    },
    "update-smoke": {
        "driver": "update-smoke.ps1",
        "args": "",
        "files": (("installer/guest/payload/installer-update.exe.b64", "pack"),
                  ("installer/guest/payload/update-payload.bin.b64", "pack"),
                  ("installer/guest/stub-service.cs", "repo"),
                  ("installer/nsis/winsys.nsh", "repo")),
    },
    "fresh-install": {
        "driver": "fresh-install",
        "args": "",
        "files": (),
        "generated": True,
        "vm_kit": True,
    },
    # CTR-6 (#227): the ten container-provable SL-6c rows against the VM kit's real installer.exe (copied byte for byte to C:\w\installer.exe).
    "uninstall-edge": {
        "driver": "uninstall-edge.ps1",
        "args": "",
        "files": (("installer.exe", "vm-kit"),
                  ("installer/guest/stub-service.cs", "repo")),
        "vm_kit": True,
    },
    "gate-edge": {
        "driver": "gate-edge.ps1",
        "args": "",
        "files": (("installer.exe", "vm-kit"),
                  ("installer/guest/payload/probe-p3.exe.b64", "pack"),
                  ("installer/guest/payload/probe-p4.exe.b64", "pack"),
                  ("installer/guest/payload/probe-p5.exe.b64", "pack")),
        "vm_kit": True,
    },
    "install-edge": {
        "driver": "install-edge.ps1",
        "args": "",
        "files": (("installer.exe", "vm-kit"),
                  ("installer/guest/stub-service.cs", "repo"),
                  ("installer/guest/payload/log-harness.exe.b64", "pack")),
        "vm_kit": True,
    },
}


# The cases inside update-smoke.ps1, in the order it runs them; --update-case selects a subset (the driver's -Only).
UPDATE_CASES = ("U-B1", "U-B2", "U-B3", "U-B3b", "U-B4", "U-B5")


class ContainerKitError(Exception):
    """A refusal of the kit generator (exit 2)."""


class UnknownCase(ContainerKitError):
    pass


class MissingPackFile(ContainerKitError):
    pass


class KitExists(ContainerKitError):
    pass


class BadArgument(ContainerKitError):
    pass


def image_ref(image):
    return f"{REPO}@{IMAGES[image]}"


def case_files(case):
    """(name in the kit, path in the tree, source) for every file the case needs, the driver first. A "vm-kit" file comes from --vm-kit."""
    spec = CASES[case]
    if spec.get("generated"):
        if not spec.get("vm_kit"):
            return []
        return [
            ("installer.exe", "installer.exe", "vm-kit"),
            ("VM-TEST.md", "VM-TEST.md", "vm-kit"),
            ("vm-state.ps1", "vm-state.ps1", "vm-kit"),
            ("vm-kit-SHA256SUMS", "SHA256SUMS", "vm-kit"),
        ]
    rows = [(spec["driver"], f"installer/guest/{spec['driver']}", "repo")]
    rows += [(Path(p).name, p, src) for p, src in spec["files"]]
    return rows


def ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def win(path):
    return path.replace("/", "\\")


def write_crlf(path, text):
    text.encode("ascii")
    with open(path, "w", encoding="ascii", newline="\r\n") as f:
        f.write(text)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prune_update_smoke(text, cases):
    """Keep selected, non-nested case regions and advertise only the shipped cases."""
    selected = set(cases)
    if not selected <= set(UPDATE_CASES):
        raise BadArgument("unknown update-smoke case in pruning selection")
    region = None
    names = 0
    output = []
    for line in text.splitlines(keepends=True):
        marker = line.strip()
        if marker.startswith(("# >>>", "# <<<")):
            if marker.startswith("# >>> cases ") and region is None:
                region = set(marker[len("# >>> cases "):].split())
                if not region or not region <= set(UPDATE_CASES):
                    raise BadArgument(f"unknown or empty update-smoke case marker: {marker}")
            elif marker == "# <<< cases" and region is not None:
                region = None
            else:
                raise BadArgument(f"unbalanced, nested or malformed update-smoke case marker: {marker}")
            continue
        if re.match(r"\s*\$caseNames\s*=", line):
            match = re.fullmatch(r"\$caseNames = @\([^\r\n]*\)(\r?\n)?", line)
            if match is None or region is not None:
                raise BadArgument("invalid or region-local update-smoke $caseNames line")
            names += 1
            shipped = ", ".join(ps_quote(c) for c in UPDATE_CASES if c in selected)
            line = f"$caseNames = @({shipped})" + (match.group(1) or "")
        if region is None or region & selected:
            output.append(line)
    if region is not None:
        raise BadArgument("unclosed update-smoke case marker")
    if names != 1:
        raise BadArgument(f"expected one update-smoke $caseNames line, found {names}")
    return "".join(output)


SMOKE_RULE = (r"^SUMMARY\b", r"^SUMMARY pass=[1-9][0-9]* fail=0 unproven=0 refused=0 error=0$")
VERDICT_RULES = {
    "log-escape.ps1": (r"^\[verdict\] c-log-escape ", r"^\[verdict\] c-log-escape PASS$"),
    "uninstall-smoke.ps1": SMOKE_RULE,
    "update-smoke.ps1": SMOKE_RULE,
    "fresh-install": (r"^\[verdict\] c-fresh-install ", r"^\[verdict\] c-fresh-install PASS$"),
    # the exact pass line uninstall-edge.ps1 writes when all ten SL-6c rows pass (#227)
    "uninstall-edge.ps1": (r"^\[verdict\] c-uninstall-edge ", r"^\[verdict\] c-uninstall-edge PASS$"),
    "gate-edge.ps1": (r"^\[verdict\] c-gate-edge ", r"^\[verdict\] c-gate-edge PASS$"),
    "install-edge.ps1": (r"^\[verdict\] c-install-edge ", r"^\[verdict\] c-install-edge PASS$"),
    # the exact pass line of Test-GuardLines in link-probes.ps1 (#194: REPORT L9 judged that line FAIL against a bare "PASS")
    "link-probes.ps1": (r"^GUARD-VERDICT:", r"^GUARD-VERDICT: PASS both GUARD lines read refused=1 and decoy_intact=Y$"),
}


def judge_fresh_install(lines):
    """Judge fresh-install measurements without trusting a case's verdict line."""
    lines = [line.rstrip("\r\n") for line in lines]
    pre_folder = next((line for line in lines if re.match(r"^pre-folder: ", line)), None)
    if pre_folder == "pre-folder: present":
        return False, 'error: "pre-folder: present"'

    failures = []

    def one(pattern, label):
        found = [line for line in lines if re.match(pattern, line)]
        if len(found) != 1:
            failures.append(f'"{label}: expected one line, found {len(found)}"')
            return None
        return found[0]

    if pre_folder != "pre-folder: absent":
        failures.append(f'"{pre_folder or "pre-folder: absent (missing)"}"')
    install = one(r"^\[T4\] install exit=-?[0-9]+$", "[T4] install exit")
    if install and install != "[T4] install exit=0":
        failures.append(f'"{install}"')
    t13 = one(r"^\[T13\] vm-state exit=-?[0-9]+$", "[T13] vm-state exit")
    if t13 and t13 != "[T13] vm-state exit=0":
        failures.append(f'"{t13}"')
    access = one(r"^\[T13\] folder access: .*$", "[T13] folder access")
    if access and access != "[T13] folder access: Administrators, SYSTEM; inheritance removed: yes":
        failures.append(f'"{access}"')
    owner = one(r"^owner-sid: .*$", "owner-sid")
    if owner and owner != "owner-sid: S-1-5-32-544":
        failures.append(f'"{owner}"')
    sddl = one(r"^sddl: .*$", "sddl")
    dacl = re.search(r"D:([A-Z]*)(.*)$", sddl) if sddl else None
    expected_aces = "(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)"
    dacl_ok = False
    if dacl:
        flags, body = dacl.groups()
        aces = re.findall(r"\([^)]*\)", body)
        dacl_ok = "P" in flags and len(aces) == 2 and "".join(aces) == body and "".join(sorted(aces)) == expected_aces
    if not dacl_ok:
        failures.append(f'"{sddl or "sddl: (missing or invalid DACL)"}"')
    uninstall = one(r"^\[T20\] uninstall exit=-?[0-9]+$", "[T20] uninstall exit")
    if uninstall and uninstall != "[T20] uninstall exit=0":
        failures.append(f'"{uninstall}"')
    if failures:
        return False, "; ".join(failures)
    return True, "all fresh-install measurements passed"


def judge(driver, lines):
    """Judge raw log lines, without conflating a measured failure with a driver exit."""
    if driver == "fresh-install":
        return judge_fresh_install(lines)
    marker, passing = VERDICT_RULES[driver]
    verdicts = [line.rstrip("\r\n") for line in lines if re.match(marker, line)]
    if len(verdicts) != 1:
        return False, f"expected one verdict line, found {len(verdicts)}"
    if not re.match(passing, verdicts[0]):
        return False, "verdict line did not pass"
    return True, "one passing verdict line"


def case_script(case, order, update_cases=()):
    spec = CASES[case]
    if case == "fresh-install":
        return fresh_install_script(order)
    marker, passing = VERDICT_RULES[spec["driver"]]
    files = "\n".join(f"  {ps_quote(n)} = {ps_quote(win(p))}" for n, p, _ in case_files(case))
    driver = win(f"installer/guest/{spec['driver']}")
    words = [spec["args"]] if spec["args"] else []
    if case == "update-smoke" and update_cases:
        passing = rf"^SUMMARY pass={len(update_cases)} fail=0 unproven=0 refused=0 error=0$"
        # One quoted string: unquoted, the calling PowerShell would pass the comma list as separate words.
        words.append("-Only " + ps_quote(",".join(update_cases)))
    args = "".join(" " + w for w in words)
    return f"""# c-{case}.ps1 - {order} (#184 step 4), generated by installer.guest.container. Runs INSIDE a throwaway Windows container,
# Windows PowerShell 5.1. The kit is mounted read-only at C:\\kit: this copies the files the driver needs to C:\\w in the repository
# layout, runs {driver}{args} unchanged from C:\\w (as `winev run` does from the tree root), then prints the driver's
# out\\*.txt between BEGIN and END. The container has no network. Metadata only, ASCII.
$ErrorActionPreference = 'Continue'
$k = 'C:\\kit'; $w = 'C:\\w'
$files = [ordered]@{{
{files}
}}
foreach ($n in $files.Keys) {{
  $dest = Join-Path $w $files[$n]
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
  Copy-Item -LiteralPath (Join-Path $k $n) -Destination $dest
}}
$cv = Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion'
$adm = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Output ('[env] image_build={{0}}.{{1}} admin={{2}} ps={{3}} user_sid={{4}}' -f $cv.CurrentBuild, $cv.UBR, $adm, $PSVersionTable.PSVersion, [Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
Set-Location -LiteralPath $w
$t = [Diagnostics.Stopwatch]::StartNew()
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $w '{driver}'){args} 2>&1 | ForEach-Object {{ '[console] ' + "$_".TrimEnd() }}
$rc = if ($null -eq $LASTEXITCODE) {{ -1 }} else {{ [int]$LASTEXITCODE }}
Write-Output ('[driver] {spec['driver']} exit={{0}} seconds={{1}}' -f $rc, [int]$t.Elapsed.TotalSeconds)
Write-Output 'BEGIN {case}'
$verdictLines = @()
$readOk = $true
try {{
  Get-ChildItem -LiteralPath (Join-Path $w 'out') -Filter '*.txt' -File -ErrorAction Stop | Sort-Object Name | ForEach-Object {{
    Write-Output ('--- out\\' + $_.Name)
    Get-Content -LiteralPath $_.FullName -ErrorAction Stop | ForEach-Object {{
      if ($_ -cmatch {ps_quote(marker)}) {{ $verdictLines += $_ }}
      Write-Output $_
    }}
  }}
}} catch {{ $readOk = $false }}
Write-Output 'END {case}'
$status = 'FAIL'
if ($rc -ne 0) {{ $reason = "driver exit $rc" }}
elseif (-not $readOk) {{ $reason = 'could not read driver logs' }}
elseif ($verdictLines.Count -ne 1) {{ $reason = 'expected one verdict line, found ' + $verdictLines.Count }}
elseif ($verdictLines[0] -cnotmatch {ps_quote(passing)}) {{ $reason = 'verdict line did not pass' }}
else {{ $status = 'PASS'; $reason = 'one passing verdict line' }}
if ($rc -eq 0 -and $status -eq 'FAIL') {{ $rc = 6 }}
Write-Output ('[verdict] c-{case} {{0}} {{1}}' -f $status, $reason)
Write-Output '[end] c-{case} END'
exit $rc
"""


def fresh_install_script(order):
    return f"""# c-fresh-install.ps1 - {order}, generated by installer.guest.container. Metadata only.
$ErrorActionPreference = 'Stop'
$pd = 'C:\\ProgramData\\EcosystemRunner'
if (Test-Path -LiteralPath $pd) {{
  Write-Output 'pre-folder: present'
  Write-Output '[verdict] c-fresh-install error "pre-folder: present"'
  Write-Output '[end] c-fresh-install END'
  exit 6
}}
Write-Output 'pre-folder: absent'
try {{
  # The signer store and the install line are L16's (payload/L16/c-proof-l16.ps1), byte for byte; only $w is C:\\X here.
  $k = 'C:\\kit'; $w = 'C:\\X'
  New-Item -ItemType Directory -Force -Path $w | Out-Null
  Copy-Item -LiteralPath "$k\\installer.exe", "$k\\vm-state.ps1" -Destination $w
  $sig = 'ab' * 32
  $sd = Join-Path $env:LOCALAPPDATA 'EcosystemInstaller'
  New-Item -ItemType Directory -Force -Path $sd | Out-Null
  [IO.File]::WriteAllText((Join-Path $sd 'signer.sha256'), ($sig + "`n"), [Text.Encoding]::ASCII)
  $p = Start-Process -FilePath "$w\\installer.exe" -ArgumentList "/S /MODE=local /SIGNER=$sig" -Wait -PassThru
  $installRc = $p.ExitCode
  Write-Output ('[T4] install exit={{0}}' -f $installRc)
  $t13 = @(& powershell -NoProfile -ExecutionPolicy Bypass -File "$w\\vm-state.ps1" -Step T13 2>&1 | ForEach-Object {{ $_.ToString().TrimEnd() }})
  $t13rc = $LASTEXITCODE
  Write-Output ('[T13] vm-state exit={{0}}' -f $t13rc)
  $access = @($t13 | Where-Object {{ $_ -match '^\\[T13\\] folder access:' }})
  foreach ($line in $access) {{ Write-Output $line }}
  $acl = $null
  $owner = 'none'
  $sddl = 'none'
  if (Test-Path -LiteralPath $pd) {{
    $acl = Get-Acl -LiteralPath $pd -ErrorAction SilentlyContinue
    if ($acl) {{
      $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
      $sddl = $acl.Sddl
    }}
  }}
  Write-Output ('owner-sid: {{0}}' -f $owner)
  Write-Output ('sddl: {{0}}' -f $sddl)
  # In place, as uninstall-smoke.ps1 runs it ("/S _?=<folder>"): the started process is the uninstaller, so its exit code is real.
  # The running uninstall.exe cannot delete itself, so after a clean run it alone is left (uninstall.nsh, SL-6c-clean-in-place).
  $u = Join-Path $pd 'uninstall.exe'
  if (Test-Path -LiteralPath $u) {{
    $un = Start-Process -FilePath $u -ArgumentList "/S _?=$pd" -Wait -PassThru
    $uninstallRc = $un.ExitCode
  }} else {{
    $uninstallRc = -1
  }}
  Write-Output ('[T20] uninstall exit={{0}}' -f $uninstallRc)
  $gone = -not (Test-Path -LiteralPath $pd)
  Write-Output ('[T20] folder_absent={{0}}' -f $gone)
}} catch {{
  $kind = $_.Exception.GetType().Name
  Write-Output ('[case] error-type: {{0}}' -f $kind)
  Write-Output ('[verdict] c-fresh-install FAIL "error-type: {{0}}"' -f $kind)
  Write-Output '[end] c-fresh-install END'
  exit 6
}}
$verdict, $reason = 'PASS', ''
if ($installRc -ne 0) {{ $reason += ('"[T4] install exit={{0}}"; ' -f $installRc) }}
if ($t13rc -ne 0) {{ $reason += ('"[T13] vm-state exit={{0}}"; ' -f $t13rc) }}
if ($access.Count -ne 1 -or $access[0] -cne '[T13] folder access: Administrators, SYSTEM; inheritance removed: yes') {{
  $evidence = if ($access.Count) {{ $access -join ' | ' }} else {{ '[T13] folder access: (missing)' }}
  $reason += ('"{{0}}"; ' -f $evidence)
}}
if ($owner -cne 'S-1-5-32-544') {{ $reason += ('"owner-sid: {{0}}"; ' -f $owner) }}
$dacl = [regex]::Match($sddl, 'D:([A-Z]*)(.*)$')
$daclAces = @([regex]::Matches($dacl.Groups[2].Value, '\\([^)]*\\)') | ForEach-Object {{ $_.Value }})
$aces = @($daclAces | Sort-Object)
$daclOk = $dacl.Success -and $dacl.Groups[1].Value.Contains('P') -and $aces.Count -eq 2 -and
  (($aces -join '') -ceq '(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)') -and
  ($dacl.Groups[2].Value -ceq ($daclAces -join ''))
if (-not $daclOk) {{ $reason += ('"sddl: {{0}}"; ' -f $sddl) }}
if ($uninstallRc -ne 0) {{ $reason += ('"[T20] uninstall exit={{0}}"; ' -f $uninstallRc) }}
if ($reason) {{
  $verdict = 'FAIL'
  $reason = $reason.TrimEnd('; ')
  Write-Output ('[verdict] c-fresh-install {{0}} {{1}}' -f $verdict, $reason)
  Write-Output '[end] c-fresh-install END'
  exit 6
}}
Write-Output '[verdict] c-fresh-install PASS'
Write-Output '[end] c-fresh-install END'
exit 0
"""


def docker_run_args(case_expr):
    """The one `docker run` argument list of the wrapper (#184 gate 3), as a PowerShell array literal."""
    return ("@('run') + $p + @('--pull=never', '--rm', '--network', 'none', '--label', 'ecosystem.proof=1', '--isolation=hyperv', "
            "'--mount', \"type=bind,source=$kit,target=C:\\kit,readonly\", $ref, "
            f"'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', \"C:\\kit\\c-{case_expr}.ps1\")")


def wrapper_script(order, kit_name, image, cases, parallel, sha, table):
    n = order.lower()
    want = "\n".join(f"  {ps_quote(name)} = '{h.upper()}'" for name, h in table)
    case_list = ", ".join(ps_quote(c) for c in cases)
    choices = ", ".join(ps_quote(k) for k in IMAGES)
    digests = "\n".join(f"  {k} = {ps_quote(v)}" for k, v in IMAGES.items())
    return f"""#Requires -Version 7.0
# {n}-ctr.ps1 - ORDER {order} (#184 step 4), generated by installer.guest.container from develop {sha}. PowerShell 7 on the host.
# Runs the guest drivers {', '.join(cases)} unchanged, each in its own throwaway Windows container (-Image, default {image};
# -Platform adds --platform windows/amd64 after run; Hyper-V isolation),
# up to {parallel} at a time, under #178 rule 4 (container lane) with the gates of #184. The host stays untouched: this checks every kit
# hash against the table below (exit 3 on a mismatch), checks that the host has no C:\\ProgramData\\EcosystemRunner before (exit 4) and
# after, inspects the selected digest, lists only labelled containers, and writes only $Out. Each case requires driver exit 0 AND
# a passing log verdict. Results are READ until a REPORT measures them.
param([ValidateSet({choices})][string]$Image = '{image}', [switch]$Platform)
$ErrorActionPreference = 'Continue'
$Kit = Join-Path $env:USERPROFILE '{WORK}\\{kit_name}'
$Out = Join-Path $env:USERPROFILE '{WORK}\\{n}-run.txt'
$d = Join-Path $env:ProgramFiles 'Docker\\Docker\\resources\\bin\\docker.exe'
$digests = @{{
{digests}
}}
$digest = $digests[$Image]
$ref = '{REPO}@' + $digest
$pf = @(); if ($Platform) {{ $pf = @('--platform', 'windows/amd64') }}
$cases = @({case_list})
$want = [ordered]@{{
{want}
}}
if (Test-Path -LiteralPath $Out) {{ Remove-Item -LiteralPath $Out }}
function W([string]$s) {{ Add-Content -LiteralPath $Out -Value $s -Encoding ascii; Write-Host $s }}
function Stop-Order([int]$code, [string]$why) {{ W ('{order} refusal: {{0}}' -f $why); W '{order} RESULT failed'; W '{order} END'; exit $code }}

W ('{order} develop={sha} image={{0}} platform={{1}} parallel={parallel} cases={{2}}' -f $Image, [bool]$Platform, ($cases -join ','))
$bad = $false
foreach ($name in $want.Keys) {{
  $f = Join-Path $Kit $name
  $h = if (Test-Path -LiteralPath $f -PathType Leaf) {{ (Get-FileHash -Algorithm SHA256 -LiteralPath $f).Hash }} else {{ 'absent' }}
  $ok = $h -eq $want[$name]
  if (-not $ok) {{ $bad = $true }}
  W ('{order} kit {{0}} {{1}} {{2}}' -f $name, $h, $(if ($ok) {{ 'ok' }} else {{ 'MISMATCH' }}))
}}
if ($bad) {{ Stop-Order 3 'kit hash' }}
$hostPd = 'C:\\ProgramData\\EcosystemRunner'
$before = -not (Test-Path -LiteralPath $hostPd)
W ('{order} host_before EcosystemRunner_absent={{0}}' -f $before)
if (-not $before) {{ Stop-Order 4 'the host has C:\\ProgramData\\EcosystemRunner' }}
if (-not (Test-Path -LiteralPath $d -PathType Leaf)) {{ Stop-Order 5 'docker.exe absent' }}
& $d image inspect $ref *> $null
$present = $LASTEXITCODE -eq 0
W ('{order} image {{0}} {{1}} present={{2}}' -f $Image, $digest, $present)
if (-not $present) {{ Stop-Order 5 'the pinned image is not present; no pull is ordered' }}
$c0 = @(& $d {LIST_CONTAINERS} 2>&1 | ForEach-Object {{ "$_".Trim() }} | Where-Object {{ $_ }})
W ('{order} containers_before={{0}}' -f $c0.Count)

$t = [Diagnostics.Stopwatch]::StartNew()
$res = @($cases | ForEach-Object -ThrottleLimit {parallel} -TimeoutSeconds {PARALLEL_TIMEOUT_SECONDS} -Parallel {{
  $c = $_
  $kit = $using:Kit
  $ref = $using:ref
  $docker = $using:d
  $p = @($using:pf)
  $a = {docker_run_args('$c')}
  $s = [Diagnostics.Stopwatch]::StartNew()
  $o = & $docker @a 2>&1
  [pscustomobject]@{{ Case = $c; Exit = $LASTEXITCODE; Seconds = [int]$s.Elapsed.TotalSeconds; Lines = @($o | ForEach-Object {{ "$_".TrimEnd() }} | Where-Object {{ $_ }}) }}
}})
$ok = $true
foreach ($c in $cases) {{
  $r = @($res | Where-Object {{ $_.Case -eq $c }}) | Select-Object -First 1
  if ($null -eq $r) {{ W ('{{0}} no_result (stopped at {PARALLEL_TIMEOUT_SECONDS} seconds)' -f $c); $ok = $false; continue }}
  foreach ($line in $r.Lines) {{ W ($c + ' ' + $line) }}
  $end = $r.Lines -contains ('[end] c-' + $c + ' END')
  W ('{{0}} docker_exit={{1}} seconds={{2}} end_marker={{3}}' -f $c, $r.Exit, $r.Seconds, $end)
  if ($r.Exit -ne 0 -or -not $end) {{ $ok = $false }}
}}
W ('{order} wall_seconds={{0}}' -f [int]$t.Elapsed.TotalSeconds)
$c1 = @(& $d {LIST_CONTAINERS} 2>&1 | ForEach-Object {{ "$_".Trim() }} | Where-Object {{ $_ }})
W ('{order} leftover_containers={{0}}' -f $c1.Count)
if ($c1.Count -gt $c0.Count) {{ $ok = $false }}
$after = -not (Test-Path -LiteralPath $hostPd)
W ('{order} host_after EcosystemRunner_absent={{0}}' -f $after)
if (-not $after) {{ $ok = $false }}
W ('{order} RESULT {{0}}' -f $(if ($ok) {{ 'ok' }} else {{ 'failed' }}))
W '{order} END'
if ($ok) {{ exit 0 }} else {{ exit 1 }}
"""


def git_head(root=ROOT):
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def vm_kit_files(vm_kit):
    vm_kit = Path(vm_kit)
    expected = ("installer.exe", "VM-TEST.md", "vm-state.ps1")
    if not vm_kit.is_dir():
        raise BadArgument(f"--vm-kit is not a directory: {vm_kit}")
    manifest_path = vm_kit / "SHA256SUMS"
    if not manifest_path.is_file():
        raise BadArgument(f"--vm-kit is missing {manifest_path.name}")
    try:
        manifest = manifest_path.read_text(encoding="ascii")
    except UnicodeDecodeError as e:
        raise BadArgument("--vm-kit SHA256SUMS is not ASCII") from e
    entries = {}
    for line in manifest.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
        if not match or match.group(2) in entries:
            raise BadArgument("--vm-kit SHA256SUMS has an invalid or duplicate entry")
        entries[match.group(2)] = match.group(1).lower()
    if set(entries) != set(expected):
        raise BadArgument("--vm-kit SHA256SUMS must list installer.exe, VM-TEST.md and vm-state.ps1 exactly once")
    files = {}
    for name in expected:
        path = vm_kit / name
        if not path.is_file():
            raise BadArgument(f"--vm-kit is missing {name}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entries[name]:
            raise BadArgument(f"--vm-kit SHA256SUMS mismatch for {name}")
        files[name] = data
    files["vm-kit-SHA256SUMS"] = manifest_path.read_bytes()
    return files


def make_kit(packdir, outdir, order, cases, image="ltsc2025", parallel=2, sha=None, root=ROOT, update_cases=(), vm_kit=None):
    """Write OUTDIR/kit-<12 hex>/ and OUTDIR/l<n>-ctr.ps1; return (kit dir, wrapper path, [(name, sha256, bytes)])."""
    if not re.fullmatch(r"L[0-9]{1,4}", order or ""):
        raise BadArgument(f"--order must be L<n>, got {order!r}")
    if image not in IMAGES:
        raise BadArgument(f"--image must be one of {', '.join(IMAGES)}, got {image!r}")
    if not 1 <= parallel <= 8:
        raise BadArgument(f"--parallel must be 1 to 8, got {parallel}")
    sha = sha or git_head(root)
    if not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
        raise BadArgument(f"the develop sha must be 40 lowercase hex digits, got {sha!r}")
    cases = list(dict.fromkeys(cases or [c for c in CASES if not CASES[c].get("vm_kit")]))
    for c in cases:
        if c not in CASES:
            raise UnknownCase(f"unknown case {c!r}; known: {', '.join(CASES)}")
    for u in update_cases or ():
        if u not in UPDATE_CASES:
            raise BadArgument(f"--update-case must be one of {', '.join(UPDATE_CASES)}, got {u!r}")
    if update_cases and "update-smoke" not in cases:
        raise BadArgument("--update-case needs --case update-smoke")
    update_cases = tuple(u for u in UPDATE_CASES if u in (update_cases or ()))
    needs_vm_kit = any(CASES[c].get("vm_kit") for c in cases)
    if needs_vm_kit and vm_kit is None:
        raise BadArgument("--case " + ", ".join(c for c in cases if CASES[c].get("vm_kit")) + " requires --vm-kit DIR")
    if vm_kit is not None and not needs_vm_kit:
        raise BadArgument("--vm-kit is only used by --case " + " or ".join(c for c in CASES if CASES[c].get("vm_kit")))
    packdir, outdir, root = Path(packdir), Path(outdir), Path(root)
    kit = outdir / f"kit-{sha[:12]}"
    wrapper = outdir / f"{order.lower()}-ctr.ps1"
    if kit.exists() or wrapper.exists():
        raise KitExists(f"{kit if kit.exists() else wrapper} already exists; use an empty OUTDIR")
    sources = {}
    binary_sources = vm_kit_files(vm_kit) if needs_vm_kit else {}
    shipped_vm = {name for c in cases for name, _, src in case_files(c) if src == "vm-kit"}
    binary_sources = {name: data for name, data in binary_sources.items() if name in shipped_vm}
    for c in cases:
        for name, tree_path, src in case_files(c):
            if src == "vm-kit":
                continue
            p = (packdir / name) if src == "pack" else (root / tree_path)
            if not p.is_file():
                raise MissingPackFile(f"{c}: {p} is missing" + (" (run python3 -m installer.guest.pack PACKDIR)" if src == "pack" else ""))
            try:
                sources[name] = p.read_text(encoding="ascii")
            except UnicodeDecodeError as e:
                raise BadArgument(f"{p} is not ASCII") from e
    if update_cases:
        sources["update-smoke.ps1"] = prune_update_smoke(sources["update-smoke.ps1"], update_cases)
    kit.mkdir(parents=True)
    for name, text in sources.items():
        write_crlf(kit / name, text)
    for name, data in binary_sources.items():
        (kit / name).write_bytes(data)
    for c in cases:
        write_crlf(kit / f"c-{c}.ps1", case_script(c, order, update_cases))
    names = sorted(p.name for p in kit.iterdir())
    table = [(name, sha256(kit / name)) for name in names]
    write_crlf(kit / "SHA256SUMS", "".join(f"{h}  {name}\n" for name, h in table))
    table.append(("SHA256SUMS", sha256(kit / "SHA256SUMS")))
    write_crlf(wrapper, wrapper_script(order, kit.name, image, cases, parallel, sha, table))
    listing = [(p.relative_to(outdir).as_posix(), sha256(p), p.stat().st_size)
               for p in sorted([wrapper, *kit.iterdir()])]
    return kit, wrapper, listing


def main(argv=None):
    ap = argparse.ArgumentParser(prog="installer.guest.container", description=__doc__.splitlines()[0])
    ap.add_argument("packdir")
    ap.add_argument("outdir")
    ap.add_argument("--order", required=True)
    ap.add_argument("--case", action="append", dest="cases", default=[],
                    help="select a case (repeatable): " + ", ".join(CASES))
    ap.add_argument("--vm-kit", help="VM-TEST kit directory required by --case fresh-install, --case uninstall-edge and --case gate-edge")
    ap.add_argument("--image", default="ltsc2025")
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--sha", default=None, help="the develop commit the pack was built from (default: git HEAD)")
    ap.add_argument("--update-case", action="append", dest="update_cases", default=[],
                    help="run only this update-smoke case (repeatable; needs --case update-smoke; default: all six)")
    a = ap.parse_args(argv)
    try:
        kit, wrapper, listing = make_kit(a.packdir, a.outdir, a.order, a.cases, a.image, a.parallel, a.sha,
                                         update_cases=a.update_cases, vm_kit=a.vm_kit)
    except (ContainerKitError, UnicodeEncodeError) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    for name, h, size in listing:
        print(f"{name} {h} {size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
