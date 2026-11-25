# Installer framework: risks, unverified claims and open questions

Private until the operator publishes it. Each open question has exactly three choices and a recommended pick, in plain words, so that one tap answers it. Until it is answered, the requirement that cites it stays as written and nobody guesses. Related: [srs.md](./srs.md), [decisions.md](./decisions.md).

## 1. Accepted risks (the operator's decision)

| Id | Risk | Decision | Consequence |
|----|------|----------|-------------|
| AR-1 | Nobody holds a recovery key. If the signing key or the marketplace account is lost, every partner reinstalls and compares fingerprints again. The reviewer and commander had recommended a sealed recovery key held by a second named person. | D-R5-8 | Releases stop until partners are told the new fingerprint through the two published places. |
| AR-2 | No written question to NI about the licence for partners and contributors. The installer shows NI's conditions and keeps a local "yes". Whether a partner without an NI development licence has any right is not settled (reviewer r2, INFERRED). | D-R3-1 | The legal position rests on each partner's own "yes". |
| AR-3 | Until a second person exists, the operator alone reviews every change to the diagnostics allow-list, so nobody else would catch a wrong entry (INFERRED), on a PC that may hold customer data. The user still reads the zip before sending it (D-R5-7). | D-R6-11 | The exposure stands until the trigger: a second person exists. From then a second reviewer must also approve every change to the list (option B of OQ-010). |

## 2. UNVERIFIED claims

| Id | Claim | What is known | How to settle it |
|----|-------|---------------|------------------|
| U-1 | `makensis` output is byte-identical across machines. | NSIS changelog items cover building NSIS itself (reviewer r5, OBSERVED); no statement found that installer output is identical; file times are stored by default. | Two real builds on two machines (INST-TC-011). Until then nobody claims reproducibility (D-R5-2). |
| U-2 | GitHub removes offline self-hosted runners automatically after a period. | Remembered by the reviewer, not re-checked. | Read the GitHub documentation before the uninstall text mentions it. The spec does not rely on it. |
| U-3 | The prerequisites of the Windows container engine and the NI Windows image on our hosts. | NI Windows tags exist for 2026 releases (OBSERVED, Docker Hub, reviewer r1); prerequisites for Windows-container runners were not checked. | A check on the clean Windows 11 base before the runner mode ships. |
| U-4 | Unicode CLDR `windowsZones` is the right source for the zone mapping. | Proposed, not checked by any reviewer. | Compare the table with Windows zone names on L1 and L2. |
| U-5 | NSIS can request user level or administrator level as the design needs. | Existing installers use user level (OBSERVED); admin-level behaviour is described in a skill note; docs not re-read. | Read the NSIS documentation for `RequestExecutionLevel` when the code slice starts. |
| U-6 | Our Windows 11 base cannot prove Server, Windows 10 or containers. | Reviewer r3 wrote this with a "(U)" tag. | Try each on the base once; update the test plan. |

Also tagged INFERRED where they appear: the diagnostics allow-list (its contents; its owner is decided, D-R6-11), the update and repair details, the version-skew rule and the key replacement rule (all from reviewer r5). "2025 has no Windows variant" is OBSERVED on 2026-11-21 (Docker Hub tags listed by reviewer r1) and can change; that is why the list is pinned at build time.

## 3. Open questions for the operator

All thirteen open questions were answered by the operator on 2026-11-21 (decisions D-R6-1 to D-R6-13); none is open. OQ-001, 003, 004, 005 and 013 came first (D-R6-1 to D-R6-5), the other eight after (D-R6-6 to D-R6-13).

### OQ-001 How is a release signed? RESOLVED 2026-11-21: A
Answer: a Git tag signed with an SSH key, fingerprint published (D-R6-1). Consequence: INST-REQ-005, 006 name the SSH-signed tag.
The record said "signed tag" and "fingerprint" but not with what.
- A. A Git tag signed with an SSH signing key, fingerprint published beside it.
- B. A Git tag signed with a GPG key.
- C. A separate signature file made with a small signing tool.
Recommended: A (nothing new to install for partners).

### OQ-002 Other Windows editions RESOLVED 2026-11-21: A
Answer: refuse every edition not on the list, with a plain reason (D-R6-6). Consequence: INST-REQ-016, 017; Windows 11 Education, Windows Server 2019 and Windows 11 Enterprise LTSC are refused.
Decision D-R4-2 lists four accepted editions. What about Windows 11 Education, Windows Server 2019 and Windows 11 Enterprise LTSC? It affects INST-REQ-016, 017.
- A. Refuse every edition not on the list, with a plain reason.
- B. Also accept Windows 11 Education.
- C. Accept every Windows 11 edition except Home.
Recommended: A (the list is what we can prove).

### OQ-003 Silent mode: secrets and exit codes RESOLVED 2026-11-21: A
Answer: silent mode never takes secrets; the add-secrets step is interactive (D-R6-2). Consequence: INST-REQ-023, 025, 026, 076, 098; exit code values are fixed in the code slice, one per failure class.
Secrets are never on a command line. How does silent mode get them, and which exit code means what?
- A. Silent mode never takes secrets; the separate "add secrets" step is always interactive.
- B. A one-time secrets file that the installer reads and then deletes.
- C. The user pipes them in on standard input.
Recommended: A; exit codes are then fixed in the code slice, one per failure class.

### OQ-004 Who can sign, and how a key is replaced RESOLVED 2026-11-21: C
Answer: no second signer until the first partner asks (D-R6-3). Consequence: INST-REQ-056, 057, 059; the operator's key is the only signing key, and AR-1 stands unsoftened.
D-R3-5 added a second signer with the first partner; D-R5-8 says nobody holds a recovery key; D-R4-9 requires "key replacement" with no owner or date.
- A. The second signer has their own key; either may sign, and either can sign a replacement for the other.
- B. The second signer only approves; the operator's key still signs.
- C. No second signer until the first partner asks for one.
Recommended: A (it softens AR-1 without a recovery key).

### OQ-005 Does the Windows "installed programs" entry count? RESOLVED 2026-11-21: A
Answer: one uninstall entry, named on the pre-administrator screen (D-R6-4). Consequence: INST-REQ-004, 028, 030, 043, 084, 089 name it; the promise is one folder, one service and one uninstall entry.
"One folder and one service and nothing else" would have forbidden the uninstall entry, which is a registry entry.
- A. Allow one uninstall entry and name it in the pre-administrator screen.
- B. No entry; uninstall is the same installer run again in uninstall mode.
- C. A per-user entry only.
Recommended: B (it keeps the promise literally true).

### OQ-006 Where does "second builder got the same file" come from? RESOLVED 2026-11-21: A
Answer: show "not yet checked" until two builders have matched (D-R6-7). Consequence: INST-REQ-004, 059; the row is always shown (options B and C not taken).
The confirmation screen list is now closed (INST-REQ-004). One row needs a source: before two real builds exist, the installer cannot know whether a second builder produced the same file. It affects INST-REQ-004 and INST-REQ-059.
- A. Show "not yet checked" until two builders have matched.
- B. Hide that row until two builders have matched.
- C. Block the first release until the row can be shown.
Recommended: A.

### OQ-007 When do the two licence boxes appear? RESOLVED 2026-11-21: A
Answer: only when a container image is chosen (D-R6-8). Consequence: INST-REQ-018; the harmless check stays free of licence screens.
It affects INST-REQ-018.
- A. Only when a container image is chosen.
- B. Always, at the start.
- C. Only in the runner modes.
Recommended: A (the harmless check stays free of licence screens).

### OQ-008 How partners suggest changes RESOLVED 2026-11-21: A
Answer: pull requests only; fork pull requests never run on any self-hosted runner; the operator is the only code owner (D-R6-9). Consequence: new INST-REQ-101, test INST-TC-057. The source licence, also named in the question, was not part of the answer; no requirement depends on it.
The vision wants partners to suggest changes. Not decided: fork pull requests on self-hosted runners, code owners, the source licence. It affects the repository rules, not a requirement yet.
- A. Pull requests only; fork pull requests never run on any self-hosted runner; the operator is the only code owner.
- B. As A, plus partners listed as owners of their own sub-folders.
- C. Issues only; the operator makes every change.
Recommended: A.

### OQ-009 What is the health check after an update? RESOLVED 2026-11-21: B
Answer: the service stays in the running state for a fixed time after start and, in forge modes only, the runner also shows online at the forge (D-R6-10). Consequence: INST-REQ-040.
It affects INST-REQ-040.
- A. The service stays in the running state for a fixed time after start.
- B. A, plus the runner shows as online at the forge.
- C. A self-test command shipped in the installer exits 0.
Recommended: A for local checks (works offline); B added where a forge is used.

### OQ-010 Who owns the diagnostics allow-list? RESOLVED 2026-11-21: A
Answer: a file in the source; the operator reviews every change; a second reviewer is added once a second person exists (D-R6-11). Not the recommended option (B): with OQ-004 C nobody else could approve. Consequence: INST-REQ-048; the exposure is ACCEPTED RISK AR-3, trigger: a second person exists.
It affects INST-REQ-048.
- A. A file in the source; the operator reviews every change.
- B. A file in the source; a second reviewer must also approve.
- C. Generated from the schema, no separate file.
Recommended: B (a mistake on a PC with customer data is costly).

### OQ-011 GitHub and GitLab runners on one PC RESOLVED 2026-11-21: A
Answer: refuse a second forge on a PC (D-R6-12). Consequence: INST-REQ-034, 036.
They share one container engine and distort each other's timings (INFERRED). It affects INST-REQ-034, 036.
- A. Refuse a second forge on a PC.
- B. Allow it with a plain warning about timings.
- C. Allow it only when the container engine is not used.
Recommended: A.

### OQ-012 Service identity and folder RESOLVED 2026-11-21: A
Answer: a dedicated virtual service account; the folder under the machine's program-data location (D-R6-13). Consequence: INST-REQ-030, 092.
Which account runs the service and where is the folder? It affects INST-REQ-030.
- A. A dedicated virtual service account; folder under the machine's program-data location.
- B. The built-in System account; same folder.
- C. A named local account the user types.
Recommended: A (least rights; a runner can read its own key anyway, reviewer r1 A3).

### OQ-013 Does the installer pull the NI docker image? RESOLVED 2026-11-21: B
Answer: after both boxes the installer pulls the pinned digest on the user's machine from the vendor registry (D-R6-5). It still never ships or mirrors the image. Consequence: INST-REQ-018, 021, 022, 087, 099, 100.
It never ships or mirrors it (the NI text bars giving containers to others, OBSERVED, reviewer r2).
- A. The installer never pulls; the user pulls by the exact digest we publish.
- B. After both boxes, the installer pulls the pinned digest.
- C. The installer pulls whatever digest the user types.
Recommended: A.

Counts: 3 accepted risks, 6 UNVERIFIED claims, 13 open questions (13 resolved, 0 open).
