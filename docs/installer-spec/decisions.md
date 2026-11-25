# Installer framework: decision register

Private until the operator publishes it.

All decisions were taken on 2026-11-21 in the discovery rounds recorded in issue #36 (and #39, #40). "Decided" means the operator chose it. "Adopted" means a default that the operator did not object to when asked. Each id is `D-R<round>-<n>`. Round 6 holds the operator's answers of 2026-11-21 to all thirteen open questions, OQ-001 to OQ-013. The short quotes are the operator's own words (at most 25 words each). A line "Changed by" marks an earlier decision that a later round changed.

Links: R1 is the issue body [#36](https://github.com/svelderrainruiz/ecosystem-control/issues/36). R2 [comment](https://github.com/svelderrainruiz/ecosystem-control/issues/36#issuecomment-7060984678). R3 [comment](https://github.com/svelderrainruiz/ecosystem-control/issues/36#issuecomment-7061152058). Time zone [comment](https://github.com/svelderrainruiz/ecosystem-control/issues/36#issuecomment-7061266309). Own-PC test [comment](https://github.com/svelderrainruiz/ecosystem-control/issues/36#issuecomment-7061576050). R4 [comment](https://github.com/svelderrainruiz/ecosystem-control/issues/36#issuecomment-7061674107). Reviewer r5 report [comment](https://github.com/svelderrainruiz/ecosystem-control/issues/36#issuecomment-7064454011). R5 answers [comment](https://github.com/svelderrainruiz/ecosystem-control/issues/36#issuecomment-7064490132). R6 answers: the two answer comments of [#48](https://github.com/svelderrainruiz/ecosystem-control/issues/48) (the first for D-R6-1 to D-R6-5, the last for D-R6-6 to D-R6-13).

## Round 1 (issue body)

| Id | Decision | Who | Quote or note | Flag |
|----|----------|-----|---------------|------|
| D-R1-1 | One shared framework plus one small installer per use case. The laptop runner was first. | Decided, "as proposed" | | Changed by D-R2-1 (the harmless check now goes first). |
| D-R1-2 | Contributors and partners build the installer from source only; nobody receives a binary from us. NSIS 3.10 pinned, one build script, stock plugins only. | Decided | "build from source only, never a binary from us" | The "stock plugins only" part came with the proposal and was not objected to (adopted). Refined by D-R2-6 and D-R4-5. |
| D-R1-3 | One schema generates the screens and the silent mode. Secrets are never on a command line. Inputs: URLs, keys or tokens, allow-lists, folder paths, proxy or DNS settings, partner or organisation ID, the LabVIEW version, and the NI Docker image with its variant (Windows or Linux) and year. Licence data was not selected. | Decided | | Licence handling added by D-R3-1. "2025 has no Windows variant" was the operator's statement and was later observed to be true (see risks file). |
| D-R1-4 | Silent mode serves our own automated tests and IT teams deploying to many PCs. | Decided | | |
| D-R1-5 | The full document set, complete enough to rebuild the installer from it, gated by a repo-standards-review run and an independent reviewer. | Decided, "as proposed" | | |

## Round 2

| Id | Decision | Who | Quote or note | Flag |
|----|----------|-----|---------------|------|
| D-R2-1 | First installer: a harmless "will it work on this PC?" check (no administrator rights, no secrets). Then the laptop runner. | Decided | | Changes D-R1-1 order. |
| D-R2-2 | Each partner owns a private GitHub, GitLab, both, or neither. We ship the installer and one command in the extension (new major version of the extension) to trigger it. | Decided | "Each partner owns a private github, gitlab, both or neither(isolation)" | The "major version" wording was changed by D-R3-6 (minor version). |
| D-R2-3 | The installer contains no secrets. A separate, repeatable "add secrets" step exists. One key per PC. | Decided | | |
| D-R2-4 | LabVIEW source: the operator said NI needs no development licence for CI/CD use in containers. The reviewer read NI's text as needing an organisation development licence. | Decided (statement) | "NI requires no development license on docker windows or linux containers as long as" it is used for CI or CD | Settled in practice by D-R3-1 (screen plus local record). |
| D-R2-5 | Release gate: two independent builds must match, and an AI agent must rebuild the installer from the spec alone. | Decided | | Changed by D-R5-2 (no claim until two real builds match). |
| D-R2-6 | No `.exe` is committed to Git. Each signed release publishes only the expected fingerprint (hash). | Adopted | | |
| D-R2-7 | The full document set stays. | Adopted | | |

## Round 3

| Id | Decision | Who | Quote or note | Flag |
|----|----------|-----|---------------|------|
| D-R3-1 | The installer shows NI's licence conditions on a screen and keeps a local "yes, we hold a development licence". No written question to NI for now. | Decided | | Docker's licence added by D-R4-2. |
| D-R3-2 | The single extension command is ONE step: it builds from source and starts the installer after a clear confirmation screen. | Decided | "builds from source and starts the installer after a clear confirmation screen" | Prerequisite: extension hardening, issue #39. |
| D-R3-3 | Order: the harmless check, then the laptop runner (GitHub), then local-only mode, then GitLab. | Decided | | |
| D-R3-4 | The installer may touch one folder and one Windows service only. Uninstall removes the service, the registration and the keys. | Decided | | Changed by D-R5-1 (registration is only removed locally; the forge part is listed). |
| D-R3-5 | The operator alone signs for now. A second signer joins when the first partner joins. | Decided | | Changed by D-R6-3 (no second signer until a partner asks). |
| D-R3-6 | The new extension command is a minor version unless something breaks. The extension is hardened first (workspace trust, machine-only settings, no plain-text password setting, confirmation screen, no silent elevation). | Adopted | | Replaces the "major version" wording of D-R2-2. |

## Round 4

| Id | Decision | Who | Quote or note | Flag |
|----|----------|-----|---------------|------|
| D-R4-1 | First run on a PC: one pause to compare the signer's fingerprint with two published places. Later runs are one step and ask again only if the signer changes. | Decided | | |
| D-R4-2 | Accepted PCs: Windows 11 Pro and Enterprise, Windows Server 2022 and 2025. Windows 10 and Home are refused with a plain reason. NI and Docker licence conditions are two separate "yes" boxes. | Decided | | |
| D-R4-3 | Source is a public repository. A GitHub Windows check runs on every change, a clean Windows 11 machine before each release, and the operator tests on his own PC. | Decided | | |
| D-R4-4 | First-release VM panel in the extension: per launched VM the time until ready, CPU, memory, disk, plus Linux-container use only, with the experiment name and result. | Decided | | Extension feature, not an installer requirement. |
| D-R4-5 | Build tool: NSIS 3.10 portable zip downloaded per user after checking the recorded fingerprint. Git and the container engine are only checked, never installed. | Decided | | |
| D-R4-6 | Time zone is an installer input: pre-selected from the PC with country, the zone name is stored, evidence is stored in UTC. | Adopted | "Aim higher, include it on the NSIS installer as well, so that people can place their timezone there." | Proposed after R3, adopted in R4. |
| D-R4-7 | The first real PC is the operator's own PC, tested by him personally. | Decided | "I will test the installer locally at the laptop." | A PC may hold customer data. Update comment above. |
| D-R4-8 | Container statistics for experiments are in scope for the extension panel, Linux containers only. | Decided | "only for Linux containers since some features may not be available for windows containers" | Issue #40. Extension feature, not an installer requirement. |
| D-R4-9 | Before the first partner: key replacement, marketplace account security and two matching builds. | Adopted | | No owner or date was given. |

## Round 5

| Id | Decision | Who | Quote or note | Flag |
|----|----------|-----|---------------|------|
| D-R5-1 | Uninstall promises only what it can do offline: it removes the service, folder and keys on the PC, then prints what is left to delete at the forge. It never says "registration removed" unless the forge confirmed it. | Adopted | | Changes D-R3-4. |
| D-R5-2 | No claim "two builds match" until two real builds match (all inputs fixed, file dates not stored, pinned NSIS 3.10 files, fixed compressor settings). | Adopted | | Changes D-R2-5. |
| D-R5-3 | Rollback promises only "previous program files restored". Repair is the same installer in repair mode and never creates keys or registers silently. | Adopted | | |
| D-R5-4 | The screen before the administrator prompt lists exactly what will change; everything before it runs without administrator rights. Local-only mode is named "Local only (no forge)". | Adopted | | |
| D-R5-5 | Uninstall with no internet: remove everything on the PC and print what to delete at the forge. | Decided | "Remove everything on the PC and print what to delete at the forge (my pick)" | |
| D-R5-6 | Updates: the extension only tells the user; he builds and runs the new installer himself. | Decided | "The extension only tells the user; he builds and runs the new installer himself (my pick)" | |
| D-R5-7 | Problem reports: a zip made on the PC; the user reads it and sends it himself. | Decided | "A zip made on the PC; the user reads it and sends it himself (my pick)" | |
| D-R5-8 | Signer unavailable or key lost: nobody holds a recovery key; partners reinstall and compare fingerprints again. | Decided | "Nobody; partners reinstall if it is lost" | Not the reviewer's pick. ACCEPTED RISK (see risks file). |
| D-R5-9 | PCs without administrator rights: local-only per-user mode; the runner needs administrator rights. | Decided | "Local-only per-user mode; the runner needs administrator rights (my pick)" | |

## Round 6 (operator answers, 2026-11-21)

| Id | Decision | Who | Quote or note | Flag |
|----|----------|-----|---------------|------|
| D-R6-1 | A release is a Git tag signed with an SSH key; the signer's fingerprint is published. | Decided | "Git tag signed with an SSH key, fingerprint published (my pick)" | Answer to OQ-001. Refines D-R1-2. |
| D-R6-2 | Silent mode never takes secrets; the "add secrets" step is interactive. | Decided | "Silent mode never takes secrets; add-secrets step is interactive (my pick)" | Answer to OQ-003. Refines D-R1-3 and D-R2-3. |
| D-R6-3 | No second signer until the first partner asks for one. The operator signs alone. | Decided | "No second signer until the first partner asks" | Answer to OQ-004, not the recommended option. Changes D-R3-5. D-R5-8 stands (no recovery key). |
| D-R6-4 | The installer makes one uninstall entry and names it on the screen before the administrator prompt. | Decided | "One uninstall entry, named on the pre-admin screen" | Answer to OQ-005, not the recommended option. Refines D-R3-4 (one folder, one service and one uninstall entry). |
| D-R6-5 | After both licence boxes the installer pulls the pinned image digest on the user's machine from the vendor registry. It still never ships or mirrors the image. | Decided | "Installer pulls the pinned digest after both boxes" | Answer to OQ-013, not the recommended option. Refines D-R3-1. |
| D-R6-6 | The installer refuses every Windows edition that is not on the accepted list (D-R4-2) and gives a plain reason. | Decided | "Refuse editions not on the list, with a plain reason" | Answer to OQ-002. Refines D-R4-2. |
| D-R6-7 | The confirmation screen shows "not yet checked" for the second-builder item until two builders have matched. | Decided | "Show 'not yet checked' until two builders match" | Answer to OQ-006. Refines D-R3-2 and D-R5-2. |
| D-R6-8 | The two licence boxes appear only when a container image is chosen. | Decided | "Only when a container image is chosen" | Answer to OQ-007. Refines D-R4-2 and D-R3-1. |
| D-R6-9 | Changes to the source repository come by pull request only. A pull request from a fork never runs on any self-hosted runner. The operator is the only code owner. | Decided | "Pull requests only; fork requests never run on our runners; you are the only code owner" | Answer to OQ-008. Refines D-R4-3. The source licence, also named in the question, was not answered. |
| D-R6-10 | The health check after an update is: the service stays in the running state for a fixed time after start and, in forge modes only, the runner also shows online at the forge. | Decided | "A, plus runner shows online at the forge (forge modes only)" | Answer to OQ-009. Refines D-R5-3. |
| D-R6-11 | The diagnostics allow-list is a file in the source and the operator reviews every change to it. A second reviewer is added once a second person exists. | Decided | "File in source; you review every change (second reviewer later)" | Answer to OQ-010, not the recommended option (B). With D-R6-3 nobody else could approve, so A now and B once a second person exists; the operator accepted this. Refines D-R5-7. Exposure: ACCEPTED RISK AR-3. |
| D-R6-12 | The installer refuses to set up a runner for a second forge on a PC. | Decided | "Refuse a second forge on a PC" | Answer to OQ-011. Refines D-R2-2 (a partner may own both forges; a PC serves one). |
| D-R6-13 | The runner service runs under a dedicated virtual service account, and its folder is under the machine's program-data location. | Decided | "Dedicated virtual service account; folder in the machine's program-data location" | Answer to OQ-012. Refines D-R3-4. |

Count: 5 + 7 + 6 + 9 + 9 + 13 = 49 decisions.
