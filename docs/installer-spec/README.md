# Installer framework specification

Private until the operator publishes it.

## Purpose

This folder specifies the installer framework of issue #36 so completely that an agent given only `docs/installer-spec/` can reproduce the installer's intended behaviour without asking anyone. Contributors and partners build an NSIS installer from source and run it interactively or silently, giving the inputs it needs, against a curated design in the shape of the repo-standards-review packet. A sentence that cannot be written precisely is a design gap and is recorded as an open question, never guessed.

## Status

Specification only (issue #48). No installer code, no build script and no extension change exist in this slice. Discovery rounds 1 to 5 are recorded in #36, #39 and #40.

## Document map

| File | Content |
|------|---------|
| [decisions.md](./decisions.md) | Decision register `D-R<round>-<n>`, with the changes between rounds flagged. |
| [srs.md](./srs.md) | Requirements `INST-REQ-NNN`: one testable sentence, rationale, priority, method, test case. |
| [architecture.md](./architecture.md) | Context, building blocks, install flow with the elevation moment, trust chain, data boundary, update, rollback, repair and uninstall flows, the extension's role. |
| [test-plan.md](./test-plan.md) | Levels, what each environment can and cannot prove, test cases `INST-TC-NNN`. |
| [rtm.md](./rtm.md) | Traceability: requirement to decision, architecture element and test case; decision to requirement. |
| [slice-plan.md](./slice-plan.md) | Plan of the installer code: slices SL-1 to SL-8 with requirements, dependencies, proof needs and first tests; checked by `tests/test_installer_slice_plan.py`. |
| [risks-and-open-questions.md](./risks-and-open-questions.md) | Accepted risks, UNVERIFIED claims, and the open questions with their three choices, recommendation and the operator's answer. |

## How to read it

Start with decisions, then requirements, then architecture. Evidence tags: OBSERVED (seen in a named source), INFERRED (reasoning), UNVERIFIED (not checked). A requirement marked INFERRED rests on a reviewer's reasoning, not on a decision. The standards named (ISO/IEC/IEEE 29148, 29119-2, 29119-3, 42010) come from the repo-standards-review standards map; no clause number is cited.

## Definition of done for the specification

1. Every requirement has a decision, an architecture element and at least one test case (rtm.md).
2. Every decision maps to a requirement or says why not.
3. Every gap is an open question with three choices, or an accepted risk with a decision.
4. `python3 -m unittest tests.test_installer_spec` passes: traceability, links, forbidden content, titles.
5. An independent review finds no unrecorded gap, and the operator has answered or deferred each open question.

Item 5: the operator has answered all thirteen open questions (OQ-001 to OQ-013, answered 2026-11-21): 13 resolved, 0 open. The independent review of the finished set is not recorded in this folder.

## Shape (repo-standards-review)

Governed requirement row format in srs.md: `Id | Requirement | Decision | Prio | Method | Test`. The Decision cell holds decision ids, or INFERRED when no decision exists. Singular rule: every row has exactly one `shall`, one behaviour per row (ISO/IEC/IEEE 29148 singular and no and/or splitting). Ids need not be in numeric order: ids 067 and up are rows split out for the singular rule, or added later by the operator's answers, and sit at the end of their section.

Checker: `python3 ~/work/rsr-m2b/scripts/requirements_quality_check.py <repo> --spec-path docs/installer-spec/srs.md --json`. Result: `ok: true`, 101 requirement rows checked, 0 findings. The in-repo test `tests/test_installer_spec.py` enforces the one-`shall` rule with a negative control, because CI cannot run the external checker.

Not done: (1) the skill's preflight and the docs workbench, which need the governed GitLab setup; (2) clause numbers, which were not checked in the skill's references, so none are cited.

## Before publishing

1. Replace issue links by decision ids.
2. Remove account names.
3. Review every verbatim quote in decisions.md.

## Publication rules

Private until the operator publishes it. The folder holds no secrets, hosts, customer names, personal details, money amounts or personal-PC names; the machine check enforces part of this. Short verbatim quotes appear only in decisions.md.

## Change log

| Date | Change |
|------|--------|
| 2026-11-21 | Operator answers folded in (third slice): OQ-002, 006, 007, 008, 009, 010, 011, 012 resolved as D-R6-6 to D-R6-13; 101 requirements, 57 test cases, 49 decisions, 13 open questions resolved and 0 open; repository rules row 101 with INST-TC-057; OQ-010 single-reviewer exposure recorded as AR-3. |
| 2026-11-21 | Operator answers folded in (second slice): OQ-001, 003, 004, 005, 013 resolved as D-R6-1 to D-R6-5; 100 requirements, 56 test cases, 41 decisions, 8 open questions; GitLab mode rows 091 to 096 tied to INST-REQ-036. |
| 2026-11-21 | Singular-shall rewrite: 97 requirements, 54 test cases, shape section, publishing checklist. |
| 2026-11-21 | First version written from discovery rounds 1 to 5 (issue #48). |
