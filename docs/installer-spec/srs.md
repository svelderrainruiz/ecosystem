# Installer framework: software requirements specification

Private until the operator publishes it. Shape: requirements with an identifier, one testable sentence with exactly one `shall`, a rationale (decision id), a priority, a verification method and a test case, in the manner of ISO/IEC/IEEE 29148 (requirements quality and traceability), as listed in the repo-standards-review standards map. Ids are stable and need not be in numeric order: rows split out for the singular rule, or added later by the operator's answers, carry ids from 067 up and sit at the end of their section.

Priority: M = must, S = should. Method: T = test, I = inspection, D = demonstration, A = analysis. "The installer" means the NSIS installer that a contributor or partner builds from source. "The extension" means the VS Code extension. In the Decision column, "INFERRED" means no decision states it: the row rests on reviewer reasoning, and a gap behind it is recorded as an open question (OQ) or an accepted risk in [risks-and-open-questions.md](./risks-and-open-questions.md). Decisions are in [decisions.md](./decisions.md), tests in [test-plan.md](./test-plan.md), the mapping in [rtm.md](./rtm.md).

## 1. Trust anchor and first run

| Id | Requirement | Decision | Prio | Method | Test |
|----|-------------|----------|------|--------|------|
| INST-REQ-001 | The installer shall, on the first run on a PC, show the signer's fingerprint and require the user to confirm that it matches the fingerprints published in two independent places before any build step starts. | D-R4-1 | M | D | INST-TC-001 |
| INST-REQ-002 | The installer shall store the confirmed fingerprint locally. | D-R4-1 | M | T | INST-TC-002 |
| INST-REQ-003 | The installer shall, when the signer differs from the stored one, stop before any build step, show the old and the new fingerprint, and ask again. | D-R4-1 | M | T | INST-TC-003 |
| INST-REQ-004 | The installer shall show, on the confirmation screen before anything is built or started, exactly these items and no others: the version, who signed, whether a second builder got the same file (shown as "not yet checked" until two builders have matched), what changed since last time, which folder, Windows service and uninstall entry it touches, whether it needs administrator rights, and which internet addresses it contacts (closed list given by the commander from the Round 4 text). | D-R3-2, D-R5-4, D-R6-4, D-R6-7 | M | D | INST-TC-004 |
| INST-REQ-005 | The source repository shall contain no installer `.exe` and no signature file, because each release is identified by its SSH-signed Git tag. | D-R2-6, D-R1-2, D-R6-1 | M | I | INST-TC-005 |
| INST-REQ-006 | The build script shall compare the sha256 of the installer it built with the one published beside the SSH-signed release tag and report match or mismatch. | D-R1-2, D-R6-1 | M | T | INST-TC-006 |
| INST-REQ-067 | The installer shall not repeat the fingerprint pause while the signer is unchanged. | D-R4-1 | M | T | INST-TC-002 |
| INST-REQ-068 | Each signed release shall publish only the expected fingerprint (hash) of the installer. | D-R2-6, D-R1-2 | M | I | INST-TC-005 |

## 2. Build from source

| Id | Requirement | Decision | Prio | Method | Test |
|----|-------------|----------|------|--------|------|
| INST-REQ-007 | The build script shall use the downloaded NSIS 3.10 portable zip only after its sha256 equals the recorded fingerprint. | D-R4-5 | M | T | INST-TC-007 |
| INST-REQ-008 | The build script shall refuse to use an NSIS zip whose sha256 differs from the recorded one. | D-R4-5 | M | T | INST-TC-007 |
| INST-REQ-009 | The build script shall check that Git and the container engine are present and report their versions. | D-R4-5 | M | T | INST-TC-008 |
| INST-REQ-010 | The build script shall, when a required tool is missing, stop and name the tool the user must install himself. | D-R4-5 | M | T | INST-TC-008 |
| INST-REQ-011 | The extension shall offer one command that builds the installer from source and starts it only after the confirmation screen of INST-REQ-004. | D-R3-2 | M | D | INST-TC-009 |
| INST-REQ-012 | The extension shall not release the command of INST-REQ-011 before the hardening of issue #39 is done (workspace trust, machine-scoped settings, no plain-text password setting, confirmation screen, no silent elevation). | D-R3-6 | M | I | INST-TC-013 |
| INST-REQ-013 | The build shall fix its inputs: NSIS 3.10 files pinned by hash, `SetDateSave off`, a fixed compressor and dictionary size, a sorted file list, no build date or time macros, one Unicode setting, pinned plugin hashes, stock plugins only (the full list is INFERRED from reviewer r5). | D-R5-2, D-R1-2 | M | I | INST-TC-010 |
| INST-REQ-014 | The project shall not claim that builds match, or that the installer is reproducible, until two real builds on two machines produce the same hash. | D-R5-2, D-R2-5 | M | A | INST-TC-011 |
| INST-REQ-015 | Before each release an agent given only `docs/installer-spec/` shall rebuild the installer. | D-R2-5 | S | D | INST-TC-012 |
| INST-REQ-069 | The build script shall download the NSIS 3.10 portable zip per user. | D-R4-5 | M | T | INST-TC-007 |
| INST-REQ-070 | The build script shall tell the user when it refuses an NSIS zip. | D-R4-5 | M | T | INST-TC-007 |
| INST-REQ-071 | The build script and the installer shall never install or change Git or the container engine. | D-R4-5 | M | T | INST-TC-008 |
| INST-REQ-072 | The result of the agent's rebuild shall be compared with the release. | D-R2-5 | S | D | INST-TC-012 |

## 3. Accepted PCs, licences and inputs

| Id | Requirement | Decision | Prio | Method | Test |
|----|-------------|----------|------|--------|------|
| INST-REQ-016 | The installer shall refuse every Windows edition that INST-REQ-017 does not accept, among them Windows 10, Windows Home, Windows 11 Education, Windows Server 2019 and Windows 11 Enterprise LTSC, giving the edition and a plain-words reason. | D-R4-2, D-R6-6 | M | T | INST-TC-014 |
| INST-REQ-017 | The installer shall accept exactly these editions: Windows 11 Pro, Windows 11 Enterprise, Windows Server 2022 and Windows Server 2025. | D-R4-2, D-R6-6 | M | T | INST-TC-015 |
| INST-REQ-018 | The installer shall show the NI licence conditions and the container engine's licence conditions as two separate, initially unticked "yes" boxes, only when a container image is chosen and before any image is pulled. | D-R4-2, D-R3-1, D-R6-5, D-R6-8 | M | D | INST-TC-016 |
| INST-REQ-019 | The installer shall keep a local record, with a UTC date, of the "yes, we hold a development licence" answer. | D-R3-1, D-R2-4 | M | T | INST-TC-017 |
| INST-REQ-020 | One schema shall generate both the interactive screens and the silent-mode keys, so that every input has both. | D-R1-3 | M | T | INST-TC-018 |
| INST-REQ-021 | The installer shall ask for: URLs, keys or tokens, allow-lists, folder paths, proxy or DNS settings, partner or organisation ID, the LabVIEW version, the NI docker image with its container type and version, each chosen from a drop-down list (the digest is never asked: it comes from the pinned list). | D-R1-3, D-R6-5 | M | T | INST-TC-018 |
| INST-REQ-022 | The container type, version and image digest choices shall come from a list pinned at build time (the version list offers only the versions pinned for the chosen container type); exactly one container type per installation: a Windows container or a Linux container, never both. | D-R1-3, D-R6-5 | M | I | INST-TC-021 |
| INST-REQ-102 | The installer shall use a successful engine probe to refuse a mismatched container type with a message box and exit 46, while allowing the pull after a failed probe. | D-R6-5 | M | T | INST-TC-058 |
| INST-REQ-023 | The installer shall never accept a secret on its command line. | D-R1-3, D-R2-3, D-R6-2 | M | T | INST-TC-019 |
| INST-REQ-024 | The installer shall contain no secret. | D-R2-3 | M | T | INST-TC-020 |
| INST-REQ-025 | The installer shall offer a silent mode, driven by the same schema, for automated tests and for IT teams deploying to many PCs. | D-R1-4, D-R6-2 | M | T | INST-TC-022 |
| INST-REQ-026 | In silent mode the installer shall exit 0 only on success and otherwise with a distinct non-zero code per failure class and a written reason in the log (INFERRED; the code values are fixed in the code slice, one per failure class, D-R6-2). | D-R1-4, D-R6-2 | M | T | INST-TC-022 |
| INST-REQ-073 | The installer shall continue past the licence boxes only when both are ticked. | D-R4-2 | M | D | INST-TC-016 |
| INST-REQ-074 | The installer shall not send the local licence record anywhere. | D-R3-1 | M | T | INST-TC-017 |
| INST-REQ-075 | Silent mode shall exit with a typed code when a secret is given on the command line. | D-R1-3, D-R2-3 | M | T | INST-TC-019 |
| INST-REQ-076 | Secrets shall be entered in a separate, repeatable, interactive "add secrets" step. | D-R2-3, D-R6-2 | M | T | INST-TC-020 |
| INST-REQ-098 | Silent mode shall accept no secret from the command line, a file or standard input. | D-R6-2 | M | T | INST-TC-019 |
| INST-REQ-077 | The installer shall hold one key per PC. | D-R2-3 | M | T | INST-TC-020 |

## 4. Elevation, footprint and runner modes

| Id | Requirement | Decision | Prio | Method | Test |
|----|-------------|----------|------|--------|------|
| INST-REQ-027 | The check, the fingerprint comparison, the build, the choices and the secrets entry shall run without administrator rights. | D-R5-4 | M | T | INST-TC-023 |
| INST-REQ-028 | The installer shall show, before the administrator prompt, a screen that lists exactly what will change (the service, the folder, the uninstall entry, the rights). | D-R5-4, D-R6-4 | M | D | INST-TC-024 |
| INST-REQ-029 | The installer shall never raise its rights without that screen. | D-R5-4, D-R3-6 | M | T | INST-TC-024 |
| INST-REQ-030 | The installer shall change one folder under the machine's program-data location, one Windows service running under a dedicated virtual service account, and one Windows uninstall entry, and nothing else. | D-R3-4, D-R6-4, D-R6-13 | M | T | INST-TC-025 |
| INST-REQ-031 | The installer shall read only the paths listed in an enumerated allow-list file kept in the source (INFERRED mechanism; the intent is D-R4-7 and D-R3-4). | D-R4-7, D-R3-4 | M | A | INST-TC-026 |
| INST-REQ-032 | On a PC without administrator rights the installer shall offer only the per-user "Local only (no forge)" mode. | D-R5-9 | M | T | INST-TC-027 |
| INST-REQ-033 | The first installer delivered shall be the harmless check ("will it work on this PC?"), which needs no administrator rights, handles no secrets and changes nothing. | D-R2-1, D-R1-1 | M | T | INST-TC-028 |
| INST-REQ-034 | The second delivery shall be the GitHub runner mode, registered at the user's own repository with a registration token the user types, and refused on a PC that already has a GitLab runner. | D-R3-3, D-R1-1, D-R6-12 | M | T | INST-TC-029 |
| INST-REQ-035 | The "Local only (no forge)" mode shall run the check, build, SBOM and tests by command, with no runner service and no forge contact (the activity list is INFERRED from reviewer r5). | D-R5-4, D-R3-3 | M | T | INST-TC-030 |
| INST-REQ-036 | The GitLab runner mode shall be delivered after the local-only mode, with its elevation, service account, token storage and unregister behaviour given by rows INST-REQ-091 to 096, and refused on a PC that already has a GitHub runner. | D-R3-3, D-R6-12 | S | I | INST-TC-031 |
| INST-REQ-066 | The installer shall register runners only at a forge address the user types. | D-R2-2 | M | T | INST-TC-029 |
| INST-REQ-078 | Silent mode shall fail with its own exit code when the installer is not already elevated (INFERRED). | INFERRED | M | T | INST-TC-024 |
| INST-REQ-079 | On a PC without administrator rights the installer shall state that the runner needs administrator rights. | D-R5-9 | M | T | INST-TC-027 |
| INST-REQ-080 | The installer shall never contact a forge owned by us (INFERRED from D-R2-2). | INFERRED | M | T | INST-TC-029 |
| INST-REQ-091 | The installer shall run the GitLab runner install step only in the elevated phase (reviewer r5: elevated prompt, OBSERVED). | INFERRED | M | T | INST-TC-031 |
| INST-REQ-092 | The installer shall install the GitLab runner service under the dedicated virtual service account. | D-R6-13 | M | T | INST-TC-031 |
| INST-REQ-093 | The installer shall report a missing service log-on right as a typed error (reviewer r5: "logon failure", OBSERVED). | INFERRED | M | T | INST-TC-031 |
| INST-REQ-094 | The installer shall keep the GitLab authentication token only in the runner's local configuration file under the install folder (reviewer r2, OBSERVED: saved in `config.toml`). | INFERRED | M | T | INST-TC-031 |
| INST-REQ-095 | At uninstall the installer shall run the runner's unregister command only when the forge is reachable (reviewer r5, OBSERVED). | INFERRED | M | T | INST-TC-054 |
| INST-REQ-096 | At uninstall the installer shall list the GitLab runner for deletion at the forge when unregistering is not possible. | D-R5-1, D-R5-5 | M | T | INST-TC-054 |

## 5. Update, rollback, repair, uninstall

| Id | Requirement | Decision | Prio | Method | Test |
|----|-------------|----------|------|--------|------|
| INST-REQ-037 | The extension shall only tell the user that a newer version exists and open the build screen. | D-R5-6 | M | I | INST-TC-033 |
| INST-REQ-038 | An update shall replace the program files only and keep configuration, logs, registration and keys (INFERRED from reviewer r5). | D-R5-6 | M | T | INST-TC-032 |
| INST-REQ-039 | The installer shall write its version to a state file (INFERRED). | D-R5-6 | S | T | INST-TC-034 |
| INST-REQ-040 | Before an update the installer shall copy the program folder and the service definition to a backup folder, stop the service, swap the files, start the service, run a health check and restore the backup if the check fails (health check: the service stays in the running state for a fixed time after start, the length fixed in the code slice, and, in the forge modes only, the runner also shows online at the forge). | D-R5-3, D-R6-10 | M | T | INST-TC-035 |
| INST-REQ-041 | Rollback screens and logs shall promise only "previous program files restored", not jobs that ran, forge registration changes or recovery after the backup is lost. | D-R5-3 | M | I | INST-TC-036 |
| INST-REQ-042 | Repair shall be the same installer in repair mode, idempotent and touching only its folder, its service, its uninstall entry and its state file. | D-R5-3 | M | T | INST-TC-037 |
| INST-REQ-043 | Uninstall shall work with no network, including the removal of its own uninstall entry. | D-R5-1, D-R5-5, D-R3-4, D-R6-4 | M | T | INST-TC-038 |
| INST-REQ-044 | Uninstall shall print a list of what remains to be deleted at the forge, with the exact place. | D-R5-1, D-R5-5 | M | T | INST-TC-039 |
| INST-REQ-045 | Uninstall shall never state that a registration was removed unless the forge confirmed it. | D-R5-1 | M | T | INST-TC-039 |
| INST-REQ-081 | The extension shall never fetch or run installer code. | D-R5-6 | M | I | INST-TC-033 |
| INST-REQ-082 | The extension shall refuse to drive an installer of a different major version (INFERRED). | INFERRED | S | T | INST-TC-034 |
| INST-REQ-083 | Repair shall never create keys or register silently. | D-R5-3 | M | T | INST-TC-037 |
| INST-REQ-084 | Uninstall shall remove the service, the folder, the uninstall entry and the keys on the PC. | D-R5-1, D-R5-5, D-R3-4, D-R6-4 | M | T | INST-TC-038 |

## 6. Logs, diagnostics, time zone

| Id | Requirement | Decision | Prio | Method | Test |
|----|-------------|----------|------|--------|------|
| INST-REQ-046 | The installer shall write every step to a persistent log with the command, its exit code and its timing (INFERRED; existing pattern `winev/bake-installer.nsi`, OBSERVED). | INFERRED | M | T | INST-TC-040 |
| INST-REQ-047 | Machine-readable logs and stored evidence shall use UTC in ISO 8601. | D-R4-6 | M | T | INST-TC-040 |
| INST-REQ-048 | On request the installer shall write a diagnostics zip locally that contains only allow-listed fields: version, Windows edition, service state, exit codes, timings, error codes, and folder names with sizes (list INFERRED from reviewer r5; the list is a file in the source and the operator reviews every change to it). | D-R5-7, D-R6-11 | M | T | INST-TC-041 |
| INST-REQ-049 | The diagnostics zip shall contain no file contents, user names, host names, paths outside the install folder, URLs with tokens or environment variables. | D-R5-7 | M | T | INST-TC-041 |
| INST-REQ-050 | The installer shall not upload the diagnostics zip. | D-R5-7 | M | T | INST-TC-042 |
| INST-REQ-051 | The installer shall offer a "Time zone" screen pre-selected from the PC (with country), changeable from a list pinned at build time, with a matching silent-mode key; absent means the PC's zone. | D-R4-6 | M | T | INST-TC-043 |
| INST-REQ-052 | The installer shall store the zone name only; daylight-saving rules come from the OS at run time (INFERRED). | D-R4-6 | M | T | INST-TC-043 |
| INST-REQ-053 | Every time shown to a person shall be plain HH:MM in that person's zone, never a bare "Z" or "UTC". | D-R4-6 | M | T | INST-TC-044 |
| INST-REQ-054 | Stored evidence and machine-readable logs shall stay in UTC; only the display converts. | D-R4-6 | M | T | INST-TC-044 |
| INST-REQ-055 | The Windows-to-IANA zone mapping shall be a pinned build input (source: Unicode CLDR `windowsZones`, generated by `installer/zones_gen.py` from a recorded release). | D-R4-6 | S | I | INST-TC-045 |
| INST-REQ-085 | The installer shall show where the diagnostics zip is so that the user reads and sends it himself. | D-R5-7 | M | T | INST-TC-042 |

## 7. Keys, data boundary, proof, governance

| Id | Requirement | Decision | Prio | Method | Test |
|----|-------------|----------|------|--------|------|
| INST-REQ-056 | A replacement signing key shall be signed by the old key, which is the operator's only signing key (INFERRED mechanism). | D-R4-9, D-R6-3 | M | T | INST-TC-046 |
| INST-REQ-057 | The operator alone shall sign releases until the first partner asks for a second signer. | D-R6-3 | M | I | INST-TC-048 |
| INST-REQ-058 | The project shall hold no recovery key; if the signing key or marketplace account is lost, partners reinstall and compare fingerprints again (ACCEPTED RISK AR-1). | D-R5-8 | M | D | INST-TC-047 |
| INST-REQ-059 | Before the first partner, key replacement, marketplace account security and two matching builds shall be in place, with no second signer required (until two builders have matched, the confirmation screen shows "not yet checked", INST-REQ-004). | D-R4-9, D-R6-3, D-R6-7 | M | I | INST-TC-048 |
| INST-REQ-060 | Only redacted metadata shall leave a PC that may hold customer data. | D-R5-7, D-R4-7 | M | T | INST-TC-049 |
| INST-REQ-061 | A hosted Windows check shall run on every change. | D-R4-3 | M | I | INST-TC-050 |
| INST-REQ-062 | The operator shall test the installer on his own PC himself. | D-R4-7 | M | D | INST-TC-051 |
| INST-REQ-063 | The installer source shall live in a public repository. | D-R4-3 | M | I | INST-TC-050 |
| INST-REQ-064 | A release shall pass a repo-standards-review run and an independent reviewer. | D-R1-5, D-R2-7 | M | I | INST-TC-052 |
| INST-REQ-065 | The specification folder shall be machine-checked for traceability, links, forbidden content, titles and the singular rule per requirement. | D-R1-5 | M | T | INST-TC-053 |
| INST-REQ-086 | Installed instances shall accept a replacement signing key only when it is signed by the old key (INFERRED). | INFERRED | M | T | INST-TC-046 |
| INST-REQ-087 | The installer shall make no network request except to the pinned NSIS source, the user's own forge and the vendor registry that holds the pinned image digest. | D-R6-5, D-R2-2 | M | T | INST-TC-049 |
| INST-REQ-088 | A clean Windows 11 machine shall run the proof before each release. | D-R4-3 | M | I | INST-TC-050 |
| INST-REQ-089 | On the operator's own PC the installer shall touch only its folder, its service and its uninstall entry. | D-R4-7, D-R3-4, D-R6-4 | M | D | INST-TC-051 |
| INST-REQ-090 | The specification set shall stay complete: every requirement, decision and test case traced. | D-R2-7 | M | T | INST-TC-052 |
| INST-REQ-099 | The installer shall pull the NI docker image on the user's machine, by the pinned digest, only after both licence boxes are ticked. | D-R6-5 | M | T | INST-TC-055 |
| INST-REQ-100 | The installer shall never ship or mirror the NI docker image. | D-R6-5, D-R3-1 | M | I | INST-TC-056 |
| INST-REQ-097 | The operator's own-PC test shall be completed before the first partner joins (INFERRED). | INFERRED | S | I | INST-TC-051 |
| INST-REQ-101 | The source repository's rules shall accept changes by pull request only, never run a pull request from a fork on any self-hosted runner, and name the operator as the only code owner. | D-R6-9 | M | I | INST-TC-057 |

Requirement count: 101.
