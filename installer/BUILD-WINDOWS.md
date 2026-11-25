# Build and hand-test the installer on your own Windows PC

You build a test installer from `develop` on your own Windows PC: the real system, not a VM. One VS Code task does the whole build (#243). Running the installer is a separate, optional step in Windows Sandbox, a throwaway desktop that Windows wipes when you close it. In the sandbox you walk the pages with [VM-TEST.md](VM-TEST.md) and report each UI bug as an issue (#235).

The build installs nothing and never starts `installer.exe`. The installer never runs on your real system.

## What you need

- Windows 11 x64.
- Python 3 (`python --version`), Git, and the GitHub CLI `gh`, signed in.
- Visual Studio Code, for the build task.
- Docker Desktop running. The build only checks that `docker` (or `podman`) answers `--version`; it starts no container.
- Internet during the build. It downloads the pinned NSIS 3.10 ZIP from SourceForge and refuses it unless its sha256 equals `installer/pins.json`.

## Build from VS Code

1. Clone the repository, or update the clone you have, and open that folder in a new VS Code window. Trust the folder when VS Code asks, because VS Code runs no task in Restricted Mode.

   ```powershell
   $r = "$env:USERPROFILE\ecosystem-control"
   if (-not (Test-Path "$r\.git")) { gh repo clone svelderrainruiz/ecosystem-control $r }
   git -C $r switch develop; if ($LASTEXITCODE -eq 0) { git -C $r pull --ff-only }
   if ($LASTEXITCODE -eq 0) { code -n $r } else { 'Stopped: fix the git error above first.' }
   ```

   VS Code reads the task from `.vscode\tasks.json` at the top of the folder the window has open. If Ctrl+Shift+B says **No build task to run found**, that window has another folder open. That folder may hold the clone one level down, or it may be a clone made before the task existed. Run the lines above and press Ctrl+Shift+B in the new window. If `git` prints an error (for example, edits in that clone block the switch), the lines stop and open no window. Commit or undo those edits, or delete the folder to clone it fresh, then run the lines again.

2. Choose **Terminal**, **Run Build Task** (Ctrl+Shift+B). It runs the task **Installer: build test kit**.
3. Type the branch to build and press Enter. Enter alone builds `develop`. The task builds the branch as it is on GitHub (`origin/<branch>`), not the folder you opened.
4. The build is done when the task panel shows `KIT OK` and the kit folder. Below it, the panel shows the commit and the `installer.exe` line of `SHA256SUMS`, which the bug form asks for.

The task runs [tools/build-windows.ps1](../tools/build-windows.ps1) with Windows PowerShell. It passes `-ExecutionPolicy Bypass` for that one run only, because Windows blocks script files by default. The script does the steps of the next section in a separate clean clone, `%USERPROFILE%\installer-test\src`, so your edits in the folder you opened never block the build. It differs from the steps by hand in three ways:

- **A kit that already exists** for that commit is verified again, not rebuilt. Delete its folder to rebuild it. A build that failed or was stopped can leave a partial kit folder; the verify step then fails and says to delete that folder and run the task again.
- **A failing step stops the build.** The panel shows `STOPPED at <step> (exit <code>)`, and the task ends with that exit code.
- **Its own refusals** are one line and exit code 2: a branch name that does not start with a letter or digit, holds a character other than letters, digits, `.`, `_`, `/` and `-`, or holds `..`; or `git`, `python` or `gh` missing from `PATH`.

Run `git pull` in the folder you opened now and then: that updates the task itself. The build always fetches the branch fresh.

## Build by hand in PowerShell (same steps, not as administrator)

```powershell
$w = "$env:USERPROFILE\installer-test"
if (-not (Test-Path "$w\src")) { gh repo clone svelderrainruiz/ecosystem-control "$w\src" }
git -C "$w\src" fetch origin
git -C "$w\src" checkout --detach origin/develop
$c = (git -C "$w\src" rev-parse HEAD).Substring(0, 12)
Set-Content -Path "$w\stand-in-payload.txt" -Value 'Stand-in runner payload for a UI test build.' -Encoding ascii
Set-Location "$w\src"; $env:PYTHONDONTWRITEBYTECODE = '1'
python -m installer.build check
python -m installer.guest.vmkit build --out "$w\kit\$c" --payload "$w\stand-in-payload.txt"
python -m installer.guest.vmkit verify "$w\kit\$c"
```

If the build works, you see three things:

- `check` prints the Git version and the container engine version.
- `build` prints `OK`.
- `verify` prints `OK`.

The build leaves a kit folder, `kit\<12 hex digits>`. The folder name is the commit you built. It holds exactly four files: `installer.exe`, `VM-TEST.md`, `vm-state.ps1` and `SHA256SUMS`.

The installer is a test build. Its runner payload is the stand-in text file, not a pinned release payload.

Some rules for rebuilding:

- **A refusal is one line and exit code 2**, for example `MissingTool: no container engine found ...` or `KitError: checkout is dirty`. Fix what the line names and run the task or the commands again.
- **Do not edit files in `src`.** The kit build refuses a checkout with any change.
- **To rebuild the same commit**, delete `kit\<12 hex digits>` first. The kit build refuses a folder that is not empty.
- **To build a branch other than `develop`**, for example a pull request's branch, use `origin/<branch>` in the `checkout` line.
- **Your hashes are your own.** A kit built on Windows compiles with the pinned ZIP's own `makensis.exe`, and its text files get CRLF line endings when Git's `autocrlf` is on. So all three hashes differ from a kit built on Linux from the same commit. Copy the `installer.exe` line from your own `SHA256SUMS` into the form.

## Optional: run it in Windows Sandbox

Windows Sandbox needs Windows 11 Pro or Enterprise, and it must be turned on. Turning it on is a one-time step that needs administrator rights and a restart. It is your choice; no agent turns it on.

- Open Settings, System, Optional features, More Windows features.
- Tick "Windows Sandbox", then restart.
- Check: `Test-Path "$env:windir\System32\WindowsSandbox.exe"` prints `True` once Sandbox is on. On a Windows 11 test PC without it, it printed `False`. If it still prints `False` after the restart, report that on #235.

After a build by hand, run this in the same PowerShell window. After the VS Code task, open PowerShell and first set `$w = "$env:USERPROFILE\installer-test"; $c = '<kit folder name>'`, with the 12 hex digits from the `KIT OK` line.

```powershell
@"
<Configuration>
  <Networking>Disable</Networking>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$w\kit\$c</HostFolder>
      <SandboxFolder>C:\kit-ro</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
  </MappedFolders>
</Configuration>
"@ | Set-Content -Path "$w\ui-test.wsb" -Encoding utf8
Start-Process "$w\ui-test.wsb"
```

The sandbox has no network and sees the kit read-only. Inside the sandbox:

1. Open Windows PowerShell as administrator.
2. Run `Copy-Item C:\kit-ro C:\kit -Recurse; Set-Location C:\kit`.
3. Follow [VM-TEST.md](VM-TEST.md) from **T1**, but skip its snapshot and its copy: run only its `vm-state.ps1 -Step T1` command, then go on with T2. Skip T23 too. The sandbox replaces the VM snapshot: closing the sandbox throws everything away. Start a new sandbox for a fresh run.

Do not double-click `installer.exe`, and never start it on your real system. A start without `/SIGNER=` and 64 hex digits shows "The signer fingerprint is missing or malformed." and "Nothing was started.", then exits with code 3 (VM-TEST T3). In the sandbox, start it with the VM-TEST T4 command, which passes a made-up placeholder signer.

Only one sandbox can run at a time.

## Report a test run

When you finish a run, open a new issue with the **Installer test run** form (<https://github.com/svelderrainruiz/ecosystem-control/issues/new?template=installer-test-run.yml>), whether every step passed or not. Use one issue per run.

The form asks for:

- the kit folder name and the `installer.exe` SHA-256. After `KIT OK`, the build task prints a `Report your run:` link. Open it to see both fields already filled in, then fill in the rest;
- the test request you ran, if any;
- where it ran, and the Windows edition and build;
- the parts of VM-TEST you ran;
- one line per step, as in VM-TEST "How to report": `T4 ok`, or `T7 saw: <up to 80 characters>`;
- the number of frames you marked, if you recorded the run with the Frame Correlator (#251);
- the result, your bug issues, and the minutes you spent.

A maintainer answers on the run's issue: they record the result on the test request, link each bug fix, and close the run. When the test request is for a release candidate and a maintainer filed the run, the run is the UI half of that release's install gate (#247). It passes that half only if all four of these hold:

- it ran in Windows Sandbox;
- both the Part A and the Part B boxes are ticked (T1 to T19);
- "Built from" is the first 12 digits of the candidate's commit;
- the result is "Every step I ran matched VM-TEST.md".

A run with a step that differs holds the release until the bug is fixed and a new run passes.

Builds that need testers are open issues with the label `test-request` (<https://github.com/svelderrainruiz/ecosystem-control/issues?q=is%3Aissue+is%3Aopen+label%3Atest-request>). Maintainers post them with the **Installer test request** form.

## Report a UI bug

Open a new issue with the **Installer UI bug** form (<https://github.com/svelderrainruiz/ecosystem-control/issues/new?template=installer-ui-bug.yml>). Use one issue per bug.

The form asks for:

- the kit folder name;
- the `installer.exe` line of `SHA256SUMS`;
- the VM-TEST step;
- the page's first field;
- what you did, what you saw and what you expected.

You can attach a screenshot. Show only the installer window: nothing from your real desktop, no user names and no customer data.
