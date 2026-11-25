# Installer framework: test plan

Private until the operator publishes it. Test plan and cases in the manner of ISO/IEC/IEEE 29119-2 and 29119-3 (test process and test documentation), as listed in the repo-standards-review standards map; no clause number is cited. Requirements: [srs.md](./srs.md). Mapping: [rtm.md](./rtm.md).

## 1. Levels

| Level | Where | Who runs it |
|-------|-------|-------------|
| L0 | Linux CI and a reader: file checks, inspection, schema and string checks, `tests/test_installer_spec.py` | Anyone, on every change |
| L1 | A GitHub-hosted Windows job (decided: D-R4-3) | CI, on every change |
| L2 | Our clean Windows 11 base from the VM programme (D-R4-3), restored to its snapshot before each case | The operator's agents, before each release |
| L3 | The operator's own PC (D-R4-7) | The operator, personally |
| L4 | An agent given only `docs/installer-spec/` (D-R2-5) | An agent, before each release |

## 2. What each environment can and cannot prove

Source: reviewer r3 verdict 4 (OBSERVED in GitHub's hosted-runner documentation as it cites; the rest INFERRED or UNVERIFIED as tagged).

| Environment | Can prove | Cannot prove |
|-------------|-----------|--------------|
| L1 hosted Windows (Server 2022 or 2025 image, administrator, UAC off) | Build, fingerprint checks, silent install, service create and remove, footprint, Server editions accepted (INFERRED) | UAC prompts, non-administrator behaviour, client editions, the NI container |
| L2 clean Windows 11 Pro base | Client edition, UAC and the elevation moment, snapshots and restore, time-zone variants, offline behaviour | Windows Server, Windows 10, containers (UNVERIFIED), real partner networks |
| L3 operator's own PC | Real security software, real proxy, the real forge registration, the data-boundary behaviour on a PC with customer data | Anything repeatable by others; it is a demonstration, not a regression test |
| L4 agent from the spec | That the spec is complete enough to rebuild the behaviour | That the behaviour is correct |
| L0 | Document and source consistency | Any runtime behaviour |

Windows 10, Windows Home and the other refused editions (Windows 11 Education, Windows Server 2019, Windows 11 Enterprise LTSC) cannot be run in any environment above (INFERRED); INST-TC-014 therefore tests the edition gate with recorded edition values and not with a real PC (INFERRED design; the gate must read the edition from one replaceable source).

## 3. Common preconditions

- L1 and L2 start from a clean state: no previous installer folder, service or state file. L2 restores the snapshot.
- The test builds the installer from the commit under test with the pinned NSIS 3.10 zip. No secret appears in any test input; fake tokens are random strings made by the test.
- Network is blocked at L2 where a case says "offline".

## 4. Test cases

| Id | Level | Requirements | Precondition | Steps | Expected result |
|----|-------|--------------|--------------|-------|-----------------|
| INST-TC-001 | L2 | 001 | Clean PC, no stored signer | Run the installer interactively | A pause shows the fingerprint and the two places to compare; nothing is built until the user confirms |
| INST-TC-002 | L2 | 002 | TC-001 done | Run again | No pause; the stored fingerprint is used |
| INST-TC-003 | L2, L1 | 003 | Stored signer A | Run an installer signed by B (L1: silent) | Stops before any build step, shows both fingerprints, asks again (L1: non-zero exit) |
| INST-TC-004 | L2 | 004 | Clean PC | Start through the extension command | Screen shows exactly the closed list of INST-REQ-004 (version, who signed, second builder, what changed, folder and service, administrator rights, internet addresses) and nothing else; the second-builder item reads "not yet checked" while no two builders have matched |
| INST-TC-005 | L0 | 005 | Repository checkout | List tracked files; read the release notes template | No installer `.exe` tracked; the release publishes only the expected fingerprint |
| INST-TC-006 | L1 | 006 | Release fingerprint known | Build; then build with a changed source file | First build reports match, second reports mismatch; the published fingerprint comes with an SSH-signed tag |
| INST-TC-007 | L1 | 007, 008 | No NSIS present | Download zip; then tamper one byte | Genuine zip is used; tampered zip is refused with a message |
| INST-TC-008 | L1 | 009, 010 | PATH without Git, then without the container engine | Run the build and the check | Tool named as missing; nothing installed; present tools only reported |
| INST-TC-009 | L2 | 011 | Extension installed | Run the one command | Build runs, then the confirmation screen, then the installer starts only after confirm |
| INST-TC-010 | L0 | 013 | Source checkout | Inspect the `.nsi` and build script | Each fixed input of INST-REQ-013 is present; no date or time macro |
| INST-TC-011 | L1, L2 | 014 | Same commit | Build on two machines | Equal hash is required before any claim; unequal hash blocks the claim and is recorded as a finding |
| INST-TC-012 | L4 | 015 | Only `docs/installer-spec/` given | Agent rebuilds the behaviour | Differences from the release are listed; each one is a spec gap |
| INST-TC-013 | L0 | 012 | Extension source | Inspect manifest and settings | Workspace trust declared, machine-scoped settings, no plain password setting, confirmation before launch |
| INST-TC-014 | L1 | 016 | Recorded edition values for Windows 10, Windows Home, Windows 11 Education, Windows Server 2019 and Windows 11 Enterprise LTSC | Run the check with each value | Each refused with its edition and a plain reason |
| INST-TC-015 | L1, L2 | 017 | Hosted Server image; L2 Windows 11 Pro | Run the check | Accepted on both; every other edition is refused (INST-TC-014, D-R6-6) |
| INST-TC-016 | L2 | 018 | Container mode with an image chosen; the harmless check with no image | Leave a box unticked, then tick both; run the harmless check | Continue disabled until both separate boxes are ticked; the harmless check shows no licence box |
| INST-TC-017 | L1 | 019 | Silent run with the licence key | Run; read the state | Local record with UTC date exists; no network request carries it |
| INST-TC-018 | L0, L1 | 020, 021 | Schema file | Generate screens and silent keys; list both | Same set of inputs; every input has a screen field and a silent key |
| INST-TC-019 | L1 | 023, 075, 098 | Fake token | Pass it as a command-line argument, in a file and on standard input, in silent mode | Each refused with a typed exit code; token not written to any log |
| INST-TC-020 | L1 | 024 | Installer built | Search it for the fake token; run add-secrets twice | Installer holds no secret; second run replaces the key; one key per PC |
| INST-TC-021 | L0 | 022 | Pinned list and shared validation table | Check the pinned types by year; validate Windows, Linux and `both` as container type choices | 2025 has no Windows container; exactly one container type is accepted per installation (Windows or Linux); `both` is refused |
| INST-TC-058 | L1, L2 | 102 | Stub engine and real Docker Desktop with reachable pinned images for both container types | In Windows and Linux container modes, run the matching and mismatched choices; make the stub probe fail once | Each matching choice pulls; each mismatch shows the refusal box and exits 46 without pulling; a failed probe still attempts the pull |
| INST-TC-059 | L0, L2 | 103 | Clean PC, no stored signer, a standard account; L0: `tests/test_installer_signerpage.py` | Double-click the installer; type a malformed value, then the published fingerprint; answer No once (new run), then Yes; go on to the administrator prompt and accept it | The signer fingerprint page is the first page; a malformed value shows a box naming the problem and keeps the page; No ends with exit code 3 and stores nothing; Yes stores the fingerprint; the elevated copy asks nothing again; a given malformed fingerprint, a silent run and the elevated copy without one still exit 3 |
| INST-TC-022 | L1 | 025, 026 | Silent run, good and bad inputs | Check exit codes and log | 0 only on success; each failure class has its own code and a written reason |
| INST-TC-023 | L2 | 027 | Standard user session | Run check, build, choices, secrets entry | All succeed without an administrator prompt |
| INST-TC-024 | L2, L1 | 028, 029 | Standard user at L2 | Reach the runner step; L1 silent run un-elevated | Screen lists service, folder, uninstall entry and rights before the prompt; no rights raised without it; L1 fails with its own exit code |
| INST-TC-025 | L1, L2 | 030 | Snapshot of folders, services, registry | Install, diff | Only one folder, one service and one uninstall registry entry differ; the folder is under the machine's program-data location and the service runs under a dedicated virtual service account |
| INST-TC-026 | L3, L0 | 031 | The operator's own PC; the source | Watch file access during a run; read the source | No read outside the install folder and given inputs; inspection agrees |
| INST-TC-027 | L2 | 032 | Standard user | Choose a runner mode | Only per-user "Local only (no forge)" is offered, with the administrator note |
| INST-TC-028 | L2 | 033 | Standard user, no secrets | Run the harmless check | Reports yes or no with reasons; changes nothing (before and after snapshot equal) |
| INST-TC-029 | L1, L3 | 034, 066 | L1: fake registrar, also a PC that already has a GitLab runner; L3: the operator's own forge | Register with a typed address; repeat on the PC with the GitLab runner | Service created at L1; L3 shows the real registration; no address other than the typed one is contacted; with a GitLab runner present the GitHub mode is refused with a plain reason and nothing changes |
| INST-TC-030 | L2 | 035 | Network blocked | Run local-only commands | Check, build, SBOM, tests run; no service; no forge contact |
| INST-TC-031 | L2 | 036, 091 to 094 | After local-only is released; a standard user and an account without the service log-on right; a PC with a GitHub runner installed | Run the GitLab mode with a fake authentication token; run it again on the PC with the GitHub runner | Install step runs only after the administrator prompt; service runs under the dedicated virtual service account (D-R6-13); missing log-on right gives a typed error; the token is only in the runner's configuration file in the install folder; on the PC with the GitHub runner the mode is refused with a plain reason and nothing changes |
| INST-TC-032 | L1 | 038 | Version 1 installed with config, log, key | Install version 2 | Program files changed; configuration, logs, registration and keys unchanged |
| INST-TC-033 | L0, L2 | 037 | Extension source; two builds | Inspect; publish a newer version | Only a notice and the build screen; no download or run of installer code |
| INST-TC-034 | L0 | 039 | State file with major 1 | Extension asked to drive major 2 | Refuses |
| INST-TC-035 | L1 | 040 | Update with an injected failing health check: the service leaves the running state within the fixed time; in a forge mode, a fake forge that shows the runner offline | Run the update in each case, then once healthy | Backup made, swap done, check fails in each failing case, backup restored, service running; the healthy update passes (in a forge mode only when the runner also shows online) |
| INST-TC-036 | L0 | 041 | Installer strings | Search messages | Only "previous program files restored"; no other restore promise |
| INST-TC-037 | L1 | 042 | Installed; remove a program file | Run repair twice | File restored; second run changes nothing; no new key; no registration |
| INST-TC-038 | L2 | 043 | Installed; network blocked | Uninstall | Service, folder, uninstall entry and keys removed |
| INST-TC-039 | L1 | 044, 045 | Installed with a fake registration | Uninstall offline | Prints the forge to-do list with the exact place; text "registration removed" absent |
| INST-TC-040 | L1 | 046, 047 | Any run | Read the log | Each step has command, exit code, timing; machine timestamps are UTC ISO 8601 |
| INST-TC-041 | L1, L0 | 048, 049 | Planted fake secret, user name, host name, token URL | Make the zip; read the allow-list file and the review rule for it | Only allow-listed fields; none of the planted values present; the allow-list is a file in the source and every change to it needs the operator's review |
| INST-TC-042 | L2 | 050 | Network blocked | Make the zip | Zip written locally; location shown; no network attempt |
| INST-TC-043 | L2 | 051, 052 | PC zone set to a non-UTC zone | Open the zone screen; change; silent key | Pre-selected from the PC with country; only the name stored; absent key means PC zone |
| INST-TC-044 | L1 | 053, 054 | Zone with daylight saving | Show times; read stored values | Plain HH:MM, no "Z" or "UTC"; stored values UTC |
| INST-TC-045 | L0 | 055 | Mapping file | Read it | Pinned, with its source and hash |
| INST-TC-046 | L1 | 056 | Instance trusting key A | Offer key B signed by A, then unsigned B | First accepted, second refused |
| INST-TC-047 | L2 | 058 | Signer replaced by an unrelated key | Run the new installer | Pause shows a new fingerprint; the partner can reinstall; no recovery path exists |
| INST-TC-048 | L0 | 057, 059 | Release procedure | Inspect | Signer rule written (operator alone until a partner asks for a second signer); the three prerequisites listed with owner and status; the screen text "not yet checked" is kept until two builders have matched |
| INST-TC-049 | L2, L3 | 060 | Network capture | Run all modes | Only the three allowed destinations contacted |
| INST-TC-050 | L0 | 061, 063 | CI config; repository settings | Inspect | Hosted Windows job on every change; clean-base proof listed in the release checklist; repository public |
| INST-TC-051 | L3 | 062 | The operator's own PC | The operator runs the installer himself | Footprint is one folder, one service and one uninstall entry; the operator reports the result |
| INST-TC-052 | L0 | 064 | Release checklist | Inspect | A repo-standards-review run and an independent review are recorded |
| INST-TC-053 | L0 | 065 | This folder | Run `python3 -m unittest tests.test_installer_spec` | Traceability, links, forbidden content and titles all pass |
| INST-TC-054 | L2 | 095, 096 | GitLab mode installed with a fake registration | Uninstall once with the forge reachable (fake), once offline | Reachable: unregister is attempted; offline: the runner is listed for deletion at the forge with the exact place |
| INST-TC-055 | L2 | 099 | Container mode with both boxes unticked, then ticked; a fake registry | Run the installer; watch the engine's pull log | No pull before both boxes are ticked; then one pull by the pinned digest, on the test PC |
| INST-TC-056 | L0 | 100 | Built installer | List its contents and the release files | No image layers or image archive in the installer or the release |
| INST-TC-057 | L0 | 101 | Repository settings, workflow files and code-owners list (INFERRED design) | Inspect | Changes reach the default branch only by pull request; no job that a pull request from a fork can start names a self-hosted runner; the code-owners list names only the operator |

Test case count: 58. Requirement numbers from 067 up are rows split out for the singular rule or added later by operator answers; their test cases are the ones named in [srs.md](./srs.md).
