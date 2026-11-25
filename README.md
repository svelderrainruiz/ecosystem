# ecosystem

The Ecosystem Runner installer: its source, its tests and the published test kits.

The installer source and tests now live here. They were imported as one snapshot from
`svelderrainruiz/ecosystem-control` (private) at commit `4d71a8a09e983d91b8c547410be67d362a6be78c` (develop), without
that repository's history. The paths are the same as there: `installer/`, `tests/`, `tools/build-windows.ps1` and
`.vscode/tasks.json`. The installer specification (`docs/installer-spec/` in ecosystem-control) is not here yet.

## Get the installer

Each test kit is a GitHub release named `installer-test-<12 hex digits>`, where the digits are the
ecosystem-control commit it was built from. A kit holds four files:

| File | What it is |
|---|---|
| `installer.exe` | The interactive installer (NSIS 3.10). **Test build**: its runner payload is a stand-in text file, not a pinned release payload. |
| `VM-TEST.md` | The step-by-step check (T1 to T24) for a throwaway Windows VM. |
| `vm-state.ps1` | Read-only state report the check runs after install, repair and uninstall. |
| `SHA256SUMS` | The sha256 of the three files above. |

Check the files before you run anything (PowerShell, in the kit folder):

```powershell
Get-Content .\SHA256SUMS | ForEach-Object { $h, $n = $_ -split '\s+\*?', 2; '{0} {1}' -f $n, ((Get-FileHash -LiteralPath $n).Hash -eq $h) }
```

Every line must end in `True`.

## Where to run it

This is an experimental installer. Run it only where you can undo the changes: a throwaway VM with a checkpoint is
the safest place. The kit's check (`VM-TEST.md`) is written for a Windows 11 Pro or Enterprise x64 VM. In "Local only
(no forge)" mode it starts no service and uses no network; it writes `C:\ProgramData\EcosystemRunner`, the uninstall
entry and `%LOCALAPPDATA%\EcosystemInstaller\signer.sha256`. To undo it, run
`C:\ProgramData\EcosystemRunner\uninstall.exe` from an administrator PowerShell, then delete
`%LOCALAPPDATA%\EcosystemInstaller` (the uninstaller keeps the signer file on purpose):

```powershell
& 'C:\ProgramData\EcosystemRunner\uninstall.exe'
Test-Path -LiteralPath 'C:\ProgramData\EcosystemRunner'
Remove-Item -LiteralPath "$env:LOCALAPPDATA\EcosystemInstaller" -Recurse
```

The uninstaller returns after about a second, before its work is done: run the `Test-Path` line again until it prints
`False`. At the end it shows the box "Still to do at the forge: delete this runner by hand at the place listed in the
uninstall report." even in "Local only (no forge)" mode; select OK (`VM-TEST.md` T18 and T19).

It needs no internet. Start it as `VM-TEST.md` step T4 says: with `/SIGNER=` and 64 hex digits; without it the
installer stops at once (exit 3) and starts nothing.

## Run the tests

The tests use the Python standard library only, on the CPython version in `.python-version` (3.14.4). From the top of
a checkout:

```
python3 -m unittest discover -s tests -t . -v
```

The tests under `tests/test_installer_guest_*.py` and `tests/test_build_windows_task.py` run PowerShell scripts and
are skipped when `pwsh` is not on `PATH`. The 19 tests that run `makensis` are skipped when it is not on
`PATH`.

CI (`.github/workflows/ci.yml`, check `unit tests`) runs the same command on a runner without `makensis`, so those 19
are skipped there. It then runs `python3 -m installer.footprint check`, `python3 -m installer.schema check` and
`python3 -m installer.build check`, installs `makensis` (Ubuntu package `nsis`) and compiles
`installer/nsis/main.nsi` with warnings as errors, once as is and once with the test-only engine override.

## How a kit is built

On Linux, from a clean checkout of this repository, with Git, a container engine (`docker` or `podman`), `makensis`
3.10 and internet access (the build downloads the pinned NSIS 3.10 ZIP and uses it only when its sha256 equals
`installer/pins.json`):

```
export PYTHONDONTWRITEBYTECODE=1
python3 -m installer.build check
c=$(git rev-parse HEAD | cut -c1-12)
python3 -m installer.guest.vmkit build --out ~/vm-kit/$c --payload ~/vm-kit/stand-in-payload.txt
python3 -m installer.guest.vmkit verify ~/vm-kit/$c
```

The payload is any stand-in file outside the checkout; the build refuses a dirty checkout and a kit folder whose name
is not the first 12 hex digits of `HEAD`. `PYTHONDONTWRITEBYTECODE=1` keeps Python cache files out of `installer/`, whose
file list is a build input. `installer/README.md` has the details.

A kit built on Linux compiles with the distribution's makensis 3.10; one built on Windows uses the pinned
NSIS 3.10 ZIP. So the same commit gives different hashes on the two systems; each release states where it
was built. The Windows build (`installer/BUILD-WINDOWS.md`, `tools/build-windows.ps1`) is imported unchanged and still
clones and builds `svelderrainruiz/ecosystem-control`.

## Licence

BSD Zero Clause License (0BSD), the same as ecosystem-control: see [LICENSE](LICENSE).
