# ecosystem

The Ecosystem Runner installer. This repository holds the installer as published test kits; the source and its
tests are still in `svelderrainruiz/ecosystem-control` (`installer/`) until they move here.

## Get the installer

Each test kit is a GitHub release named `installer-test-<12 hex digits>`, where the digits are the
ecosystem-control commit it was built from. A kit holds four files:

| File | What it is |
|---|---|
| `installer.exe` | The interactive installer (NSIS 3.10). **Test build**: its runner payload is a stand-in text file, not a pinned release payload. |
| `VM-TEST.md` | The step-by-step check (T1 to T17) for a throwaway Windows VM. |
| `vm-state.ps1` | Read-only state report the check runs after install, repair and uninstall. |
| `SHA256SUMS` | The sha256 of the three files above. |

Check the files before you run anything (PowerShell, in the kit folder):

```powershell
Get-Content .\SHA256SUMS | ForEach-Object { $h, $n = $_ -split '\s+\*?', 2; '{0} {1}' -f $n, ((Get-FileHash -LiteralPath $n).Hash -eq $h) }
```

Every line must end in `True`.

## Where to run it

Only in a Windows 11 Pro or Enterprise x64 VM you can throw away, with a checkpoint taken first. Never on a PC
that holds real work or customer data. The VM needs no internet. Start it as `VM-TEST.md` step T4 says: with
`/SIGNER=` and 64 hex digits; without it the installer stops at once (exit 3) and starts nothing.

## How a kit is built

From a clean checkout of ecosystem-control at the named commit:

```
python3 -m installer.build check
python3 -m installer.guest.vmkit build --out kit/<12 hex> --payload <stand-in payload file>
python3 -m installer.guest.vmkit verify kit/<12 hex>
```

A kit built on Linux compiles with the distribution's makensis 3.10; one built on Windows uses the pinned
NSIS 3.10 ZIP. So the same commit gives different hashes on the two systems; each release states where it
was built.
