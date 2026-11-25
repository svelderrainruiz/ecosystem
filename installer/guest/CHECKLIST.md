# Guest checklist: what can move to Server Core? (#94, #199)

**No whole driver qualifies.** The unit of transfer is the unchanged driver **and** the payloads it executes, not a switch, one result line, or one compiled probe. `guest-proof.ps1` and `gate-probes.ps1` are `laptop-refused` (link creation); `probes.ps1` is `output-rule` (raw accounts and paths). None emits a single complete pass line for the whole driver. An item-level `PASS`, diagnostic `INFO`, or process exit 0 is not a substitute.

The tables classify the observation in each item, not the rest of its caller. `container-provable` means a headless local observation as ContainerAdministrator on ltsc2025 with no network, **not measured** unless the row explicitly records a measurement and REPORT. `desktop-only` means keep the unchanged check on the VM: some need a second token or UI; others need a VM-only prerequisite, identified below. `source-read` is a claim made from source, not a Windows result. `output-rule` includes evidence files: the case script prints `out\*.txt` (`container.py:131-134`). Reading an ACL is not itself a violation; emitting a named account or an out-of-scope path is. Line references are relative to `installer/guest/` unless noted.

### `guest-proof.ps1`

The SL-6 uninstall rows distinguish the **assertion** from its shared setup. File handles, registry views and service state can be measured without a desktop. The unchanged driver still needs the clone's Python adapter and compiled stub to supply a running service (`guest-proof.ps1:115-121,142-149,355-359,391-401`); the helper logs the stub's disallowed work path. None of these rows independently supplies a case from the unchanged driver. The ten `container-provable` SL-6c rows are instead ported, with the same steps and pass conditions, to the separate driver `uninstall-edge.ps1` (case `uninstall-edge`, #227). That driver runs them against the VM kit's real `installer.exe`, installs the stub service itself in PowerShell, and creates no link; `guest-proof.ps1` itself stays `laptop-refused`.

| Item | Class | Reason and source |
|---|---|---|
| Environment | output-rule | `guest-proof.ps1:133-136` writes the user name and resolved Python path to `env.txt` before running the checks. |
| GUEST6B-first-silent-start | container-provable | `guest-proof.ps1:170-183` times the elevated silent process; it needs an exit code, not a visible window. Ported to case `install-edge` (`install-edge.ps1:191`, #234): **case added, not measured**. |
| SL-3 | container-provable | `guest-proof.ps1:187-204` checks the live edition's expected decision and three supplied captions. Windows containers report Server captions accepted by the current host check, so the source's rejection expectation is not applicable. **NOT-PORTED** in case `install-edge` (`install-edge.ps1:180`): unproven in a container pending the decision in #238; no live Windows 11 Pro install is claimed. |
| SL-4a-unelevated-gate | desktop-only | `guest-proof.ps1:246-257` requires an actual unelevated launch; an elevated exit code cannot establish refusal. |
| SL-4b-footprint | output-rule | `guest-proof.ps1:26-35,260-280` writes full added/removed paths, including the per-user signer under the profile. Checking registry values does not require the Apps & Features UI. |
| SL-4c-pages-and-elevation-step | desktop-only | `guest-proof.ps1:281` explicitly leaves page navigation and the prompt unproven without an interactive desktop. |
| SL-13-acl-as-installed | output-rule | `guest-proof.ps1:283-292` plants the child, calls the Python ACL helper and writes raw named ACLs. This is not the #94 measurement of a child delivered by the installer. |
| FINDING-programdata-folder-writable-by-standard-user | desktop-only | `guest-proof.ps1:293-320` tries creation and append with a second token; its batch script also echoes the account. |
| SL-13-upgrade-run | container-provable | `guest-proof.ps1:328-331` checks the numeric exit of an elevated silent reinstall; the adjacent **ACL** evidence is not safe to transfer. Ported to case `install-edge` (`install-edge.ps1:224`, #234): **case added, not measured** (numeric exit only). |
| SL-13-acl-after-upgrade | output-rule | `guest-proof.ps1:332-336` calls `aclcheck`; `service_proof.py:110-136` prints the raw descriptors with resolved names. |
| SL-13-upgrade-children-lose-inherited-users | output-rule | `guest-proof.ps1:325-327,337-342` logs the named before-ACL used to qualify the child, even though the final comparison is a boolean. |
| SL-6a-offline-uninstall | output-rule | `guest-proof.ps1:348-379` compares local state but writes the full listing diff, which can include non-product registry paths and profile or decoy paths (also on failure). |
| SL-13-uninstall-removes-whole-folder | container-provable | `guest-proof.ps1:355-359,381-383` checks program and folder absence after establishing the service and uninstaller were present. Ported to case `install-edge` (`install-edge.ps1:239`, #234): **case added, not measured**. |
| SL-6c-leftover-default-launch | container-provable | `guest-proof.ps1:416-432` holds a file open, starts the silent uninstaller and checks service, key and folder state. Ported to case `uninstall-edge` (`uninstall-edge.ps1:197-211`, #227): **measured PASS** on Windows (L22, [REPORT](https://github.com/svelderrainruiz/ecosystem-control/issues/221#issuecomment-7090455033)). |
| SL-6c-leftover-keeps-uninstaller | container-provable | `guest-proof.ps1:416-433` checks that the executable still exists after the locked-file uninstall. Ported to case `uninstall-edge` (`uninstall-edge.ps1:197-212`, #227): **measured PASS** on Windows (L22, [REPORT](https://github.com/svelderrainruiz/ecosystem-control/issues/221#issuecomment-7090455033)). |
| SL-6c-run-twice-after-release | container-provable | `guest-proof.ps1:434-441` retries after the handle closes and polls for removal. Ported to case `uninstall-edge` (`uninstall-edge.ps1:214-220`, #227): **measured PASS** on Windows (L22, [REPORT](https://github.com/svelderrainruiz/ecosystem-control/issues/221#issuecomment-7090455033)). |
| SL-6c-readonly-file-removed | container-provable | `guest-proof.ps1:418-421,435-446` checks the folder containing the read-only file disappears on the second run. Ported to case `uninstall-edge` (`uninstall-edge.ps1:199-201,214-225`, #227): **measured PASS** on Windows (L22, [REPORT](https://github.com/svelderrainruiz/ecosystem-control/issues/221#issuecomment-7090455033)). |
| SL-6c-leftover-exit-40 | container-provable | `guest-proof.ps1:452-464` observes the in-place exit, retained executable, and key with a held file. Ported to case `uninstall-edge` (`uninstall-edge.ps1:233-243`, #227): **measured PASS** on Windows (L22, [REPORT](https://github.com/svelderrainruiz/ecosystem-control/issues/221#issuecomment-7090455033)). |
| SL-6c-in-place-after-release | container-provable | `guest-proof.ps1:465-473` retries the in-place uninstall after release and checks which file remains. Ported to case `uninstall-edge` (`uninstall-edge.ps1:244-253`, #227): **measured PASS** on Windows (L22, [REPORT](https://github.com/svelderrainruiz/ecosystem-control/issues/221#issuecomment-7090455033)). |
| SL-6c-clean-in-place | container-provable | `guest-proof.ps1:476-484` checks exit 0 and the still-running executable on a clean install. Ported to case `uninstall-edge` (`uninstall-edge.ps1:258-265`, #227): **measured PASS** on Windows (L22, [REPORT](https://github.com/svelderrainruiz/ecosystem-control/issues/221#issuecomment-7090455033)). |
| SL-6c-clean-default | container-provable | `guest-proof.ps1:485-493` polls for complete removal after the default launch on a clean install. Ported to case `uninstall-edge` (`uninstall-edge.ps1:267-273`, #227): **measured PASS** on Windows (L22, [REPORT](https://github.com/svelderrainruiz/ecosystem-control/issues/221#issuecomment-7090455033)). |
| SL-6c-empty-folder-edge | container-provable | `guest-proof.ps1:495-510` uses a headless process to hold the directory and checks that it is empty after removal of the key and service. Ported to case `uninstall-edge` (`uninstall-edge.ps1:278-294`, #227): **measured PASS** on Windows (L22, [REPORT](https://github.com/svelderrainruiz/ecosystem-control/issues/221#issuecomment-7090455033)). |
| SL-6c-standard-user-gate | desktop-only | `guest-proof.ps1:513-529` compares direct and copied uninstaller launches by a standard user, including exit 38 and unchanged state. |
| SL-6c-service-running-uninstall | container-provable | `guest-proof.ps1:530-539` checks that the service is running before the elevated silent uninstall, then polls for complete removal. Ported to case `uninstall-edge` (`uninstall-edge.ps1:299-308`, #227): **measured PASS** on Windows (L22, [REPORT](https://github.com/svelderrainruiz/ecosystem-control/issues/221#issuecomment-7090455033)). |
| SL-13-precreated-folder-empty / -file | desktop-only | `guest-proof.ps1:561-570,583-584` requires each fixture to be owned by the standard user; the failure detail can also print the owner by name. |
| SL-13-precreated-folder-junction | laptop-refused | `guest-proof.ps1:554-567` contains the link-creation fixture. Skipping the variant does not remove its code from a staged driver. |
| SL-13 refusal message wording | source-read | `guest-proof.ps1:578-579` explicitly attributes the wording to installer unit tests: silent mode suppresses the message. This is not an observed dialog. |
| SL-7a-steplog-path-utc | container-provable | `guest-proof.ps1:590-614` reads the local step log and compares UTC timestamps under the selected Windows zones. Ported to case `install-edge` (`install-edge.ps1:258`, #234): **case added, not measured** (unchanged log harness). |
| SL-7b-zone-name-in-log | container-provable | `guest-proof.ps1:595-598,608-617` compares log fields with the OS zone key; no user session is needed. Ported to case `install-edge` (`install-edge.ps1:262`, #234): **case added, not measured** (unchanged log harness; missing or empty logs cannot pass). |
| SL-7c-secret-redaction | desktop-only | `guest-proof.ps1:618-628,641` runs the clone's Windows Python 3.11 test suite; neither Python nor the test tree is a pack output. The separate claim about constant NSIS log messages is a source read. |
| SL-7d-display-time-zone | desktop-only | `guest-proof.ps1:629-641` compares Python's actual zone-data behavior with Windows time; explicitly unproven without that interpreter. |
| SL-6b-rollback-after-failed-health-check | output-rule | `guest-proof.ps1:117-121,648-650` logs helper arguments under a sibling ProgramData folder and the clone's work path before recording the rollback. |
| SL-13-acl-after-update / -acl-after-failed-update | output-rule | `service_proof.py:110-115,275-285` dumps named ACLs after the good update and again after restore. |
| SL-13-children-lose-inherited-users | output-rule | `service_proof.py:260-262,275-280` records the original named child ACL to establish the update precondition. |
| SL-13-acl-identical-after-update-and-failed-update | output-rule | `service_proof.py:275-287` obtains both signatures from those ACL reports; a mismatch also prints the differing signatures. |
| SL-5a-local-mode | output-rule | `guest-proof.ps1:654-666` emits the raw listing diff, **including** the sibling-folder probe path exempted from the assertion. A correct local-mode flag alone cannot make that transcript safe. |
| SL-5b-service-under-virtual-account | output-rule | `service_proof.py:191-205` records the stub's actual identity by name, not SID (`stub-service.cs:29-30`). |
| SL-5b-config-acl | output-rule | `service_proof.py:182-188` emits the config file's raw ACL and the named access entries. |
| SL-5b-config-denied-to-standard-user | desktop-only | `guest-proof.ps1:672-683` requires a failed read using a standard-user token. |
| SL-5b-delete | output-rule | `guest-proof.ps1:117-121,668-671,685` logs the cleanup helper's folder argument outside the product root, even though `service_proof.py:210-217` tests local service absence. |
| SL-5c-logon-failure-error | desktop-only | `guest-proof.ps1:686-695` creates a separate account lacking the service logon right; `service_proof.py:220-235` checks the real logon failure. |
| Optional update loop / fresh-lock diagnostic | output-rule | `guest-proof.ps1:117-121,224-229,645-646` logs sibling ProgramData paths for both; `service_proof.py:305-323` also records raw ACLs. Neither diagnostic is a release verdict. |

For #94, the pack's stand-in payload is for **updates** (`pack.py:25-27,55-60`). The full proof still plants `runner.exe` and creates its own service (`guest-proof.ps1:283-289,355-359`). Reading that setup is not proof of the installer's service or the requested before/after ACL on its delivered binary. Neither a container result nor this classification signs off the fresh-clone release hash.

### `probes.ps1`: service ACL and uninstall diagnostics

Every result is `INFO` (`probes.ps1:1-5`). `Raw` saves the tool's absolute path, arguments and unfiltered output, not just its exit code (`probes.ps1:7-13,16-24`). M0/M1/M2/M3 repeat the same grants before service creation, after creation, after SID configuration and with the service started, respectively (`probes.ps1:94-113`).

| Item | Class | Reason and source |
|---|---|---|
| A-M0..M3: 1-folder-by-name / 2-folder-by-sid / folder-acl-after | output-rule | `probes.ps1:53-60` records the account, fixture path or raw folder ACL; using a SID for one grant does not sanitize the transcript. |
| A-M0..M3: 3-file-by-name / 4-file-by-sid / both file-acl-after results | output-rule | `probes.ps1:61-72` repeats the same disclosures for the config file. |
| A-M0-residue | container-provable | `probes.ps1:93-98` compares ACL snapshots and checks service absence; the residue observation reports booleans, unlike the grant evidence. |
| A-M1-sc-create / A-M2-sc-sidtype | output-rule | `probes.ps1:100-109` records the raw creation command with its service account and the system tool path for both invocations. |
| A-M3 service-read: baseline, after grant 3, after grant 4 | output-rule | `probes.ps1:40-50,66-72,111` re-emits the service identity written by `stub-service.cs:39-42` at all three restarts. |
| A-cleanup | output-rule | `probes.ps1:75-82` records the system tool path while stopping/deleting the fixture before reporting its absence. |
| B-setup | output-rule | `probes.ps1:118-126,144-145` logs the service preparation command, including its account and binary path. |
| B-folder-acl | output-rule | `probes.ps1:146-147` emits the raw named ACL. |
| B-registered-strings | container-provable | `probes.ps1:149-152` reads the installed product's uninstall strings from the registry; it does not exercise Apps & Features. |
| B1-standard-user | desktop-only | `probes.ps1:154-165` launches as the second account and also copies the account-identification command's output into evidence. |
| B2-uninstall-no-underscore / -with-underscore | container-provable | `probes.ps1:167-183` measures the elevated silent process and local state, polling for the default launch and waiting for the in-place one. |
| B-cleanup | output-rule | `probes.ps1:128-134,184-185` logs the native tool path during cleanup, before emitting final state. |

`A-skipped` and `B-skipped` (`probes.ps1:86,148`) only report missing fixtures. They prove no behavior.

CTR-8 (#234) explicitly reports `A-M0-residue`, `B-registered-strings`, `B2-uninstall-no-underscore` and
`B2-uninstall-with-underscore` as `NOT-PORTED` in `install-edge.ps1:182-185`: the source gives observations
only, with no PASS/FAIL condition. Promoting successful observation to a product PASS would invent a rule.
These rows remain unmeasured and prevent a passing case verdict until source pass rules are agreed.

### `gate-probes.ps1`: silent gates, NSIS P1-P5 and UAC

The parent dot-sources the two different drivers at `guest-proof.ps1:231-241`. **P1-P5 run here, not in `probes.ps1`.** `pack.py:23-25,61-69` compiles them to `probe-p1.exe.b64` through `probe-p5.exe.b64`; it does not supply `installer-pinned.exe.b64`. Compiling P1 does not remove its link-creation behavior. The gates report per-item results, and the NSIS probes report only `INFO` (`gate-probes.ps1:1-3,253-262`).

The container-provable rows below are ported to the separate case `gate-edge` (#231), using the VM kit's real `installer.exe` and only
the compiled P3/P4/P5 probes. Arguments, timeouts and pass conditions are retained; diagnostics use counts and booleans instead of raw
step logs, record bytes or exception messages (KITOUT-1). Its six GATE rows determine the verdict; its eight PROBE rows remain INFO.
The original driver stays `laptop-refused`. The new case is added, not measured; no Windows result is claimed.

| Item | Class | Reason and source |
|---|---|---|
| GATE-a-valid-keys-return | container-provable | `gate-probes.ps1:47-52` times two silent elevated starts with local/text arguments. Ported to case `gate-edge` (`gate-edge.ps1:173`, #231): case added, not measured. |
| GATE-b-secret-on-command-line-32 | container-provable | `gate-probes.ps1:36-44,54` checks exit 32 using dummy values, no credentials or network. Ported to case `gate-edge` (`gate-edge.ps1:179`, #231): case added, not measured. |
| GATE-c-secret-file-or-stdin-33 | output-rule | `gate-probes.ps1:39-44,55` includes the disallowed absolute dummy file path in the evidence and result, even on pass. |
| GATE-d-unknown-key-31 | container-provable | `gate-probes.ps1:36-44,56` checks unknown options by exit code only. Ported to case `gate-edge` (`gate-edge.ps1:180`, #231): case added, not measured. |
| GATE-e-bad-choice-30 | container-provable | `gate-probes.ps1:36-44,57` checks invalid choices by exit code only. Ported to case `gate-edge` (`gate-edge.ps1:181`, #231): case added, not measured. |
| PROBE-f-url-unquoted / -quoted | container-provable | `gate-probes.ps1:58-68` tests local option parsing and counts matches in local files; it does not contact the URL. Ported to case `gate-edge` (`gate-edge.ps1:185`, #231): case added, not measured. |
| GATE-g-no-arguments-no-spin | container-provable | `gate-probes.ps1:69-79` checks exit or bounded CPU time, not whether a usable wizard appears. Ported to case `gate-edge` (`gate-edge.ps1:197`, #231): case added, not measured. |
| GATE-h-path-{setup-copy, slash-folder, apostrophe, space-folder, dollar-folder} | output-rule | `gate-probes.ps1:99-112` prints the full executable path under the temp root for each variant on both pass and fail. |
| GATE-i-L1-unpinned-pair-36 | container-provable | `gate-probes.ps1:174-186` observes release-build refusal and local footprint; no image is fetched. Ported to case `gate-edge` (`gate-edge.ps1:211`, #231): case added, not measured. |
| GATE-i-L2-pull-ok-0 | desktop-only | `gate-probes.ps1:188-206,220-223` requires a separately built pinned installer and compiled engine stub to observe one successful simulated call. |
| GATE-i-L3-pull-fails-46 | desktop-only | `gate-probes.ps1:188-204,224-230` requires the same missing fixture to return a failure and test uninstall afterward. |
| GATE-i-L4-no-engine-46 | desktop-only | `gate-probes.ps1:188-204,231-237` also skips without the pinned fixture, even though this start tests engine absence. |
| GATE-i-L5-one-answer-35 | desktop-only | `gate-probes.ps1:188-204,238-247` requires the pinned build to distinguish a missing licence answer from an unpinned image. |
| PROBE-i-record-landing-and-bytes | desktop-only | `gate-probes.ps1:205-219` compares a successful L2 record with the VM's Windows Python writer/reader; mere file presence is not a byte comparison. |
| PROBE-P1-junction | laptop-refused | `gate-probes.ps1:264-267` runs the executable built from `probe-p1.nsi:9`, which creates a directory link. |
| PROBE-P2-declined-elevation | desktop-only | `gate-probes.ps1:278-288` needs the standard-user token; even its batch result explicitly does not prove a real prompt. |
| PROBE-P3-wordfind | container-provable | `gate-probes.ps1:268`, `probe-p3.nsi:12-33`: bounded in-process string parsing; reports loop counters and the error flag. Ported to case `gate-edge` (`gate-edge.ps1:225`, #231): case added, not measured. |
| PROBE-P4a / P4b / P4c / P4d | container-provable | `gate-probes.ps1:269-275`, `probe-p4.nsi:8-29`: observes exit codes for Quit in initialization, Quit in a section, Abort in a section, and Quit in a called function. Ported to case `gate-edge` (`gate-edge.ps1:226`, #231): case added, not measured. |
| PROBE-P5-fileread | container-provable | `gate-probes.ps1:276-277`, `probe-p5.nsi:7-14`: reads a local 1030-character fixture and reports the character count. Ported to case `gate-edge` (`gate-edge.ps1:233`, #231): case added, not measured. |
| GATE-j-uac-a-stays-open | desktop-only | `gate-probes.ps1:290-293,350-355` needs the standard user's installer window and samples its lifetime after the elevation refusal. |
| GATE-j-uac-b-box-exists | desktop-only | `gate-probes.ps1:315-325,356-359` uses the compiled UI driver to inspect the actual message box and text. |
| GATE-j-uac-c-exit-code-after-cancel | desktop-only | `gate-probes.ps1:290-293,360-362` checks exit 1 **after pressing Cancel**, not an unrelated silent exit 1. |
