# Installer framework: slice plan

Private until the operator publishes it. This file plans the installer code (issue #64, step 1); it changes no requirement and no decision. Each slice is one pull request by one worker. Requirements: [srs.md](./srs.md). Blocks: [architecture.md](./architecture.md). Proof levels: [test-plan.md](./test-plan.md). The shape of this file is checked by `tests/test_installer_slice_plan.py`: fixed field labels, one `Field: value` line per field, ids written in full.

## A. The slices

Proposed layout, following the repo pattern of one top-level package per tool (`winev/`, `fleet/`, `notify/`): a new package `installer/` with Python for the build script and for host-side models, NSIS and PowerShell for what runs on the target PC, and one `tests/test_installer_<topic>.py` per slice (standard library only, fakes in the style of `tests/fake_gh.py`). A slice that adds a directory adds its own short README, as the other packages do.

| Slice | Name | Size | Lines | Needs |
|-------|------|------|-------|-------|
| SL-1 | Build script and pinned inputs | M | 600 | nothing |
| SL-2 | Trust chain | M | 500 | SL-1 |
| SL-3 | Input schema, host check and licences | L | 900 | SL-1 |
| SL-4 | Elevation moment and footprint | M | 700 | SL-3 |
| SL-5 | Runner modes | L | 850 | SL-4 |
| SL-6 | Update, rollback, repair, uninstall, extension contract | L | 900 | SL-5 |
| SL-7 | Logs, time zone and data boundary | M | 650 | SL-3 |
| SL-8 | Proof and release gate | S | 350 | SL-6, SL-7 |

The commander's draft order was: trust chain and build script; input schema and host check; elevation and footprint; runner modes; update, rollback and uninstall; logs, time zone and data boundary; proof gate. Two changes. First, ARCH-1 and ARCH-2 are two slices (SL-1 build, SL-2 trust): together they hold 18 requirements and would pass the 900-line target, and the build script is the dependency of everything else while the trust chain is not. Second, logs, time zone and data boundary (SL-7) need only the input schema, so they move beside elevation and runners and run in parallel with them; the dependency is the schema (SL-3), not the update flow.

### SL-1 Build script and pinned inputs

- ARCH: ARCH-2
- Requirements: INST-REQ-005, INST-REQ-006, INST-REQ-007, INST-REQ-008, INST-REQ-009, INST-REQ-010, INST-REQ-013, INST-REQ-068, INST-REQ-069, INST-REQ-070, INST-REQ-071
- Depends-on: none
- Paths: installer/__init__.py, installer/build.py, installer/pins.json, installer/README.md, tests/test_installer_build.py
- Host verification: unit tests with a fake download and a fake `makensis`; pins file hash check; a test that the repo holds no installer binary and no signature file
- Guest proof: none. The build runs on the host; the real compile is proven once in SL-4's guest run.
- Independent review: no
- First tests:
  - test_zip_with_wrong_sha256_is_refused: a changed zip stops the build and names the mismatch (007, 008, 070).
  - test_missing_git_or_engine_names_the_tool: stop with the tool the user must install, never install it (009, 010, 071).
  - test_compile_inputs_are_fixed: the compile command carries the fixed defines, a sorted file list and no date macro (013).
  - test_built_hash_is_compared_with_published: equal passes, different stops (006, 068).
  - test_repo_holds_no_exe_or_signature: scan the tree (005).
  - test_download_goes_to_the_user_folder: per user, no elevation (069).
- Definition of done: the build script runs end to end against fakes, refuses every bad input with a typed error, the pins file is the only source of hashes, tests are green in CI.
- Size: M, about 600 lines. One script like `winev/bake.py` plus its tests.
- Risk: the NSIS 3.10 flags that make a build deterministic are INFERRED, so "fixed inputs" may still not give equal hashes (see INST-REQ-014 in section E).

### SL-2 Trust chain

- ARCH: ARCH-1
- Requirements: INST-REQ-001, INST-REQ-002, INST-REQ-003, INST-REQ-004, INST-REQ-056, INST-REQ-067, INST-REQ-086, INST-REQ-103
- Depends-on: SL-1
- Paths: installer/trust.py, installer/nsis/trust.nsh, installer/nsis/main.nsi, tests/test_installer_trust.py
- Host verification: Python reference model of the state machine (first run, same signer, different signer, key replacement) tested on the host; `pwsh` parse-only check of the PowerShell helper; `makensis` compile where available
- Guest proof: base. The confirmation and fingerprint screens are exercised in the SL-4 guest run; nothing earlier needs a guest.
- Independent review: yes (signing, trust and key replacement)
- First tests:
  - test_first_run_requires_two_place_confirmation: no build step before the user confirms (001, 004).
  - test_confirmed_fingerprint_is_stored: stored locally after confirmation (002).
  - test_same_signer_skips_the_pause: second run is one step (067).
  - test_different_signer_stops_and_shows_both: old and new shown, stop before any build step (003).
  - test_replacement_key_needs_old_key_signature: unsigned replacement is refused (056, 086).
- Definition of done: the state machine is covered, the stored fingerprint file has one defined format, the confirmation screen exists in `main.nsi`, review done.
- Size: M, about 500 lines.
- Risk: key replacement is INFERRED in the spec (D-R4-9 adopts it without defining it), so the signature format is a design choice made here.

### SL-3 Input schema, host check and licences

- ARCH: ARCH-3, ARCH-4
- Requirements: INST-REQ-016, INST-REQ-017, INST-REQ-018, INST-REQ-019, INST-REQ-020, INST-REQ-021, INST-REQ-022, INST-REQ-023, INST-REQ-024, INST-REQ-025, INST-REQ-026, INST-REQ-033, INST-REQ-073, INST-REQ-074, INST-REQ-075, INST-REQ-076, INST-REQ-077, INST-REQ-098
- Depends-on: SL-1
- Paths: installer/schema.json, installer/schema.py, installer/hostcheck.ps1, installer/nsis/screens.nsh, installer/licences.py, tests/test_installer_schema.py, tests/test_installer_hostcheck.py
- Host verification: the generator turns the schema into the screen list and the silent keys, and a test proves they match; edition table tests on fake system data; `pwsh` parse-only check of `hostcheck.ps1`
- Guest proof: base. The real edition read and the harmless check run once in the SL-4 guest run (the clean base is one Windows 11 edition only, so refusals of other editions stay host-side with fakes).
- Independent review: yes (secrets handling)
- First tests:
  - test_schema_generates_screens_and_silent_keys: one source, both outputs equal (020, 025).
  - test_unlisted_edition_is_refused_with_reason: Home, Education, LTSC, Server 2019 (016, 017).
  - test_secret_on_command_line_gives_typed_exit: also no secret from file or stdin (023, 075, 098).
  - test_silent_exit_zero_only_on_success: distinct non-zero codes (026).
  - test_licence_boxes_start_unticked_and_both_needed: shown only when an image is chosen (018, 073).
  - test_digest_comes_from_pinned_list: never asked (021, 022).
- Definition of done: schema is the only description of inputs, harmless check delivered first and changes nothing, the licence record has a UTC date and never leaves the PC, no secret in the source.
- Size: L, about 900 lines. This is the largest slice; if the worker passes 900 lines, move INST-REQ-073 and INST-REQ-074 with the licence screen to a follow-up and say so in the PR.
- Risk: the schema must serve interactive NSIS pages and silent keys; a generator in Python cannot run on the target, so its output (generated NSIS include) must be committed and checked for drift.

### SL-4 Elevation moment and footprint

- ARCH: ARCH-5, ARCH-6
- Requirements: INST-REQ-027, INST-REQ-028, INST-REQ-029, INST-REQ-030, INST-REQ-031, INST-REQ-032, INST-REQ-078, INST-REQ-079, INST-REQ-089
- Depends-on: SL-3
- Paths: installer/nsis/elevate.nsh, installer/footprint.json, installer/footprint.py, installer/allowlist-read.txt, tests/test_installer_footprint.py, winev/base-manifest.json
- Host verification: footprint allow-list tests (one folder, one service, one uninstall entry, nothing else); a static scan of the NSIS and PowerShell source for registry or file writes outside the list; `pwsh` parse-only checks
- Guest proof: base. First slice that needs the Windows guest: the service creation under the virtual service account, the administrator prompt and the screen before it. This is where the ONE planned base rebuild belongs (see section C).
- Independent review: yes (elevation and destructive footprint)
- First tests:
  - test_everything_before_the_screen_is_unelevated: steps up to the secrets entry list no admin action (027).
  - test_no_rights_raise_without_the_list_screen: elevation call only after the screen (028, 029).
  - test_footprint_is_one_folder_one_service_one_entry: and nothing else (030).
  - test_reads_only_allow_listed_paths: the allow-list is a file in the source (031).
  - test_no_admin_offers_only_local_only_mode: with the plain statement that the runner needs administrator rights (032, 079).
  - test_silent_mode_not_elevated_has_own_exit_code (078).
- Definition of done: elevation and footprint are enforced by a source scan in CI, the guest run on the rebuilt base is recorded, review done.
- Size: M, about 700 lines.
- Risk: whether NSIS can drive user level and administrator level as the flow needs is UNVERIFIED (architecture.md section 3); the guest run is the first real evidence and may force a redesign of the elevation step.

### SL-5 Runner modes

- ARCH: ARCH-7
- Requirements: INST-REQ-034, INST-REQ-035, INST-REQ-036, INST-REQ-066, INST-REQ-091, INST-REQ-092, INST-REQ-093, INST-REQ-094, INST-REQ-099, INST-REQ-100
- Depends-on: SL-4
- Paths: installer/runners.py, installer/nsis/runner-github.nsh, installer/nsis/runner-gitlab.nsh, installer/nsis/runner-local.nsh, installer/image.py, tests/test_installer_runners.py
- Host verification: fake forge (in the style of `tests/fake_gh.py`) for registration; mode exclusion tests (second forge refused); image pull planner tested with a fake engine; `pwsh` parse-only checks
- Guest proof: base. Service install under the virtual account and the "logon failure" typed error are proven in the guest; no real forge contact (the base has no NIC) so registration stays proven by fakes, and the first real registration happens on the operator's own PC.
- Independent review: yes (credential storage and service accounts)
- First tests:
  - test_register_only_at_typed_forge_address: no default address (066).
  - test_second_forge_on_a_pc_is_refused: GitHub then GitLab and the reverse (034, 036).
  - test_local_only_runs_check_build_sbom_tests_without_service (035).
  - test_gitlab_install_step_only_in_elevated_phase (091).
  - test_gitlab_token_only_in_runner_config: never in logs or state file (094).
  - test_missing_logon_right_is_typed_error (093).
  - test_image_pulled_by_digest_after_both_licences: never shipped or mirrored (099, 100).
- Definition of done: the three modes exist behind one mode switch, delivery order GitHub then local-only then GitLab is visible in the commit order, no secret reaches a log.
- Size: L, about 850 lines.
- Risk: the SBOM and test tooling for local-only mode is not named by the spec (INST-REQ-035 is INFERRED); the slice must pin a minimal choice.

### SL-6 Update, rollback, repair, uninstall, extension contract

- ARCH: ARCH-8, ARCH-9, ARCH-13
- Requirements: INST-REQ-011, INST-REQ-037, INST-REQ-038, INST-REQ-039, INST-REQ-040, INST-REQ-041, INST-REQ-042, INST-REQ-043, INST-REQ-044, INST-REQ-045, INST-REQ-081, INST-REQ-082, INST-REQ-083, INST-REQ-084, INST-REQ-095, INST-REQ-096
- Depends-on: SL-5
- Paths: installer/update.py, installer/nsis/update.nsh, installer/nsis/uninstall.nsh, installer/state.schema.json, installer/extension-contract.md, tests/test_installer_update.py, tests/test_installer_uninstall.py
- Host verification: backup, swap and restore tested on a temporary folder with injected failures at each step; uninstall tested with the network forbidden; the major-version check as a pure function; `pwsh` parse-only checks
- Guest proof: base. Rollback after a failed health check and offline uninstall are run in the guest from a snapshot; first real update on the operator's own PC.
- Independent review: yes (destructive: swap, restore, removal)
- First tests:
  - test_update_replaces_program_files_only: configuration, logs, registration and keys stay (038).
  - test_failed_health_check_restores_backup: and the screen says only "previous program files restored" (040, 041).
  - test_repair_is_idempotent_and_never_creates_keys (042, 083).
  - test_uninstall_works_without_network: removes service, folder, entry and keys (043, 084).
  - test_uninstall_lists_forge_leftovers_and_never_claims_removal (044, 045, 095, 096).
  - test_different_major_version_is_refused: state file version versus caller (039, 082).
- Definition of done: every destructive step has an injected-failure test, the state file schema is fixed, the contract file states what the extension may do (tell, open the build screen, command after confirmation, never fetch or run installer code).
- Size: L, about 900 lines.
- Risk: the extension is not in this repo (see decision O-1), so INST-REQ-011, INST-REQ-037 and INST-REQ-081 are met here only as a contract plus a host check, not as extension code.

### SL-7 Logs, time zone and data boundary

- ARCH: ARCH-10, ARCH-11, ARCH-12
- Requirements: INST-REQ-046, INST-REQ-047, INST-REQ-048, INST-REQ-049, INST-REQ-050, INST-REQ-051, INST-REQ-052, INST-REQ-053, INST-REQ-054, INST-REQ-055, INST-REQ-060, INST-REQ-080, INST-REQ-085, INST-REQ-087
- Depends-on: SL-3
- Paths: installer/log.py, installer/diagnostics.py, installer/diag-allowlist.txt, installer/zones.json, installer/netpolicy.json, installer/nsis/log.nsh, tests/test_installer_logs.py, tests/test_installer_zone.py
- Host verification: allow-list diagnostics zip tested on a fake install folder (every excluded class planted and proven absent); display conversion tested across a daylight-saving change; a source scan for network destinations against the policy file; `pwsh` parse-only checks
- Guest proof: base. The step log written by a real run and the zone read from Windows are checked in the SL-4 or later guest run; nothing else needs a guest.
- Independent review: yes (diagnostics are the data boundary)
- First tests:
  - test_step_log_has_command_exit_code_output (046).
  - test_machine_logs_are_utc_iso8601_and_display_is_hhmm: never a bare Z or UTC in display (047, 053, 054).
  - test_zone_stored_by_name_only (052).
  - test_zone_mapping_is_a_pinned_input: hash checked (055, 051).
  - test_diagnostics_zip_contains_only_allow_listed_items (048, 049).
  - test_only_pinned_network_destinations_and_no_upload: no forge of ours (050, 060, 080, 087).
- Definition of done: the allow-list file and the network policy file are the single sources, no upload code exists, the zip location is shown to the user.
- Size: M, about 650 lines.
- Risk: a wrong Windows-to-IANA table silently shows wrong times. SL-12 generates it from Unicode CLDR `windowsZones`; its fit to real Windows zone names is still open (U-4).

### SL-8 Proof and release gate

- ARCH: ARCH-14
- Requirements: INST-REQ-061, INST-REQ-072, INST-REQ-088, INST-REQ-101
- Depends-on: SL-6, SL-7
- Paths: installer/proof.py, installer/rebuild-compare.py, installer/repo-rules.json, installer/ci-windows.yml, tests/test_installer_proof.py
- Host verification: the rebuild comparison tested on two fake build outputs; the repository rules file checked against a fake `gh` response; the workflow file parsed and checked to run on every change
- Guest proof: base. The clean Windows 11 proof script runs on the base before each release; the first full run closes the plan.
- Independent review: yes (release and signing gate)
- First tests:
  - test_rebuild_result_is_compared_with_release: equal and different (072).
  - test_hosted_windows_check_runs_on_every_change: workflow trigger (061).
  - test_repo_rules_require_pr_and_no_fork_pr_on_self_hosted_runner (101).
  - test_proof_script_refuses_a_dirty_base: the clean-base precondition (088).
- Definition of done: one command runs the release gate and writes a UTC-stamped evidence file; the workflow file sits in the source but is enabled only once the repository is public.
- Size: S, about 350 lines.
- Risk: the hosted Windows check needs a public repository (INST-REQ-063, operator publication), so it cannot run in CI until then.

## B. Dependencies, critical path and order

```text
SL-1 --+--> SL-2
       |
       +--> SL-3 --+--> SL-4 --> SL-5 --> SL-6 --+--> SL-8
                   |                             |
                   +--> SL-7 --------------------+
```

- Critical path: SL-1, SL-3, SL-4, SL-5, SL-6, SL-8 (about 4300 lines, six pull requests in series).
- Parallel pairs (never more than two workers at once): SL-2 with SL-3; SL-7 with SL-4; SL-7 with SL-5 if SL-7 was late. SL-2 and SL-7 are off the critical path and can slip without delaying SL-8, except that SL-8 waits for SL-7.
- Recommended order: SL-1; then SL-2 and SL-3 together; then SL-4 and SL-7 together; then SL-5; then SL-6; then SL-8.
- Merge conflicts: SL-2, SL-3, SL-4 and SL-7 all touch `installer/nsis/main.nsi`. Each slice adds a `.nsh` include and one include line to `main.nsi`; a worker rebases and re-runs tests before the push.

## C. Guest-proof plan

| Slice | Where proven |
|-------|--------------|
| SL-1 | Host only: fakes. |
| SL-2 | Host only (reference model, `pwsh` parse-only); screens seen in the SL-4 guest run. |
| SL-3 | Host only (fakes, `pwsh` parse-only); real edition read in the SL-4 guest run. |
| SL-4 | Clean base (guest). First guest slice. |
| SL-5 | Host fakes for forges; clean base for service and log-on error; real registration on the operator's own PC. |
| SL-6 | Host fakes with injected failures; clean base from snapshot for rollback and offline uninstall; real update on the operator's own PC. |
| SL-7 | Host only; one log and zone read in a guest run. |
| SL-8 | Clean base for the release proof; the operator's own PC for INST-REQ-062 and INST-REQ-097 (section E). |

- Agents never touch the operator's own PC. They hand over a script and a checklist; the operator runs it and records the result.
- The ONE planned base rebuild belongs at SL-4, before its guest run. The base has no network card, so the pinned NSIS 3.10 zip must be baked in rather than downloaded, and the guest needs the Windows features the service test uses. Doing it once at SL-4 serves SL-2, SL-3, SL-4, SL-5 and SL-6 guest runs, which then use snapshots of that one base.
- Until SL-4 every slice is verified on the host, so SL-1 to SL-3 can merge before any guest time is spent.

## D. Open decisions for the operator

| Id | Question | Pick |
|----|----------|------|
| O-1 | Where does the extension code live? INST-REQ-011, INST-REQ-037 and INST-REQ-081 are extension behaviour. | The extension stays in its own repository; SL-6 delivers the installer-side contract and a host check only. |
| O-2 | In which language does installer logic run on the target PC? Python cannot be assumed there. | NSIS plus PowerShell on the target; Python only for the build script and host-side models (as `winev/bake.py` does). |
| O-3 | Where is the installer source built until the operator publishes it (INST-REQ-063)? | In this private repository under `installer/`; the operator exports it to a new public repository at publication, and the hosted Windows workflow is enabled then. |
| O-4 | Which SBOM and test tooling does local-only mode run (INST-REQ-035)? | The smallest pinned choice made in SL-5 and recorded as a new decision by the operator before SL-5 merges. |

## E. Requirements that are not code

| Id | Reason |
|----|--------|
| INST-REQ-012 | A release gate: the hardening of issue #39 is extension work done elsewhere; the check is the release checklist. |
| INST-REQ-014 | A claim rule: needs two real builds on two machines, one being the operator's; no code can make it true. |
| INST-REQ-015 | A release process step: an agent given only the spec rebuilds the installer; the comparison script is SL-8 (INST-REQ-072). |
| INST-REQ-057 | Custody process: the operator alone signs. |
| INST-REQ-058 | Custody process: no recovery key exists; an accepted risk (AR-1). |
| INST-REQ-059 | A pre-partner checklist: key replacement, marketplace account security and two matching builds. |
| INST-REQ-062 | Operator-only: the operator tests on his own PC himself. |
| INST-REQ-063 | Publication by the operator. |
| INST-REQ-064 | Review process: a repo-standards-review run and an independent reviewer before a release. |
| INST-REQ-065 | Already enforced by `tests/test_installer_spec.py`; no new code. |
| INST-REQ-090 | Already enforced by `tests/test_installer_spec.py` (traceability); no new code. |
| INST-REQ-097 | Operator-only: the own-PC test is completed before the first partner joins. |
| INST-REQ-102 | Documentation-only follow-up: the container-type probe was already implemented by ENGINE-1 (#175); this requirement records it without new code work. |

## F. Spec defects found while planning

- INST-REQ-033, INST-REQ-034 and INST-REQ-036 state a delivery order, which is a plan fact rather than testable behaviour; they are claimed by the slice that builds the mode.
- The base has no network card, yet INST-REQ-069 has the build script download NSIS: the guest run needs the zip baked in (section C).
- ARCH-13 lists INST-REQ-011, 012, 037 and 039 but not 081 and 082, which are extension rules too; they are placed in SL-6 with ARCH-13.
- INST-REQ-035 names SBOM and tests without a tool (decision O-4).
