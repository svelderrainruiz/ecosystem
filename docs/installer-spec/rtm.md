# Installer framework: requirements traceability matrix

Private until the operator publishes it. Every requirement has a decision (or the word INFERRED), an architecture element and at least one test case. Status "specified" means written down and reviewed as a document; no installer code exists in this slice, so nothing is "implemented" or "verified" yet. Rows are grouped by section of [srs.md](./srs.md); ids need not be in numeric order. Other sources: [decisions.md](./decisions.md), [architecture.md](./architecture.md), [test-plan.md](./test-plan.md).

## 1. Requirements to decisions, architecture and tests

| Requirement | Decision | Architecture | Test case | Status |
|-------------|----------|--------------|-----------|--------|
| INST-REQ-001 | D-R4-1 | ARCH-1 | INST-TC-001 | specified |
| INST-REQ-002 | D-R4-1 | ARCH-1 | INST-TC-002 | specified |
| INST-REQ-003 | D-R4-1 | ARCH-1 | INST-TC-003 | specified |
| INST-REQ-004 | D-R3-2, D-R5-4, D-R6-4, D-R6-7 | ARCH-1, ARCH-5 | INST-TC-004 | specified |
| INST-REQ-005 | D-R2-6, D-R1-2, D-R6-1 | ARCH-1, ARCH-2 | INST-TC-005 | specified |
| INST-REQ-006 | D-R1-2, D-R6-1 | ARCH-1, ARCH-2 | INST-TC-006 | specified |
| INST-REQ-067 | D-R4-1 | ARCH-1 | INST-TC-002 | specified |
| INST-REQ-068 | D-R2-6, D-R1-2 | ARCH-1 | INST-TC-005 | specified |
| INST-REQ-007 | D-R4-5 | ARCH-2 | INST-TC-007 | specified |
| INST-REQ-008 | D-R4-5 | ARCH-2 | INST-TC-007 | specified |
| INST-REQ-009 | D-R4-5 | ARCH-2 | INST-TC-008 | specified |
| INST-REQ-010 | D-R4-5 | ARCH-2 | INST-TC-008 | specified |
| INST-REQ-011 | D-R3-2 | ARCH-13 | INST-TC-009 | specified |
| INST-REQ-012 | D-R3-6 | ARCH-13 | INST-TC-013 | specified |
| INST-REQ-013 | D-R5-2, D-R1-2 | ARCH-2 | INST-TC-010 | specified |
| INST-REQ-014 | D-R5-2, D-R2-5 | ARCH-2, ARCH-14 | INST-TC-011 | specified |
| INST-REQ-015 | D-R2-5 | ARCH-14 | INST-TC-012 | specified |
| INST-REQ-069 | D-R4-5 | ARCH-2 | INST-TC-007 | specified |
| INST-REQ-070 | D-R4-5 | ARCH-2 | INST-TC-007 | specified |
| INST-REQ-071 | D-R4-5 | ARCH-2 | INST-TC-008 | specified |
| INST-REQ-072 | D-R2-5 | ARCH-14 | INST-TC-012 | specified |
| INST-REQ-016 | D-R4-2, D-R6-6 | ARCH-4 | INST-TC-014 | specified |
| INST-REQ-017 | D-R4-2, D-R6-6 | ARCH-4 | INST-TC-015 | specified |
| INST-REQ-018 | D-R4-2, D-R3-1, D-R6-5, D-R6-8 | ARCH-4 | INST-TC-016 | specified |
| INST-REQ-019 | D-R3-1, D-R2-4 | ARCH-4, ARCH-12 | INST-TC-017 | specified |
| INST-REQ-020 | D-R1-3 | ARCH-3 | INST-TC-018 | specified |
| INST-REQ-021 | D-R1-3, D-R6-5 | ARCH-3 | INST-TC-018 | specified |
| INST-REQ-022 | D-R1-3, D-R6-5 | ARCH-3 | INST-TC-021 | specified |
| INST-REQ-102 | D-R6-5 | ARCH-4, ARCH-12 | INST-TC-058 | specified |
| INST-REQ-023 | D-R1-3, D-R2-3, D-R6-2 | ARCH-3 | INST-TC-019 | specified |
| INST-REQ-024 | D-R2-3 | ARCH-3 | INST-TC-020 | specified |
| INST-REQ-025 | D-R1-4, D-R6-2 | ARCH-3 | INST-TC-022 | specified |
| INST-REQ-026 | D-R1-4, D-R6-2 | ARCH-3 | INST-TC-022 | specified |
| INST-REQ-073 | D-R4-2 | ARCH-4 | INST-TC-016 | specified |
| INST-REQ-074 | D-R3-1 | ARCH-4, ARCH-12 | INST-TC-017 | specified |
| INST-REQ-075 | D-R1-3, D-R2-3 | ARCH-3 | INST-TC-019 | specified |
| INST-REQ-076 | D-R2-3, D-R6-2 | ARCH-3 | INST-TC-020 | specified |
| INST-REQ-077 | D-R2-3 | ARCH-3 | INST-TC-020 | specified |
| INST-REQ-027 | D-R5-4 | ARCH-5 | INST-TC-023 | specified |
| INST-REQ-028 | D-R5-4, D-R6-4 | ARCH-5 | INST-TC-024 | specified |
| INST-REQ-029 | D-R5-4, D-R3-6 | ARCH-5 | INST-TC-024 | specified |
| INST-REQ-030 | D-R3-4, D-R6-4, D-R6-13 | ARCH-6 | INST-TC-025 | specified |
| INST-REQ-031 | D-R4-7, D-R3-4 | ARCH-6, ARCH-12 | INST-TC-026 | specified |
| INST-REQ-032 | D-R5-9 | ARCH-5, ARCH-7 | INST-TC-027 | specified |
| INST-REQ-033 | D-R2-1, D-R1-1 | ARCH-4, ARCH-7 | INST-TC-028 | specified |
| INST-REQ-034 | D-R3-3, D-R1-1, D-R6-12 | ARCH-7 | INST-TC-029 | specified |
| INST-REQ-035 | D-R5-4, D-R3-3 | ARCH-7 | INST-TC-030 | specified |
| INST-REQ-036 | D-R3-3, D-R6-12 | ARCH-7 | INST-TC-031 | specified |
| INST-REQ-066 | D-R2-2 | ARCH-7 | INST-TC-029 | specified |
| INST-REQ-078 | INFERRED | ARCH-5 | INST-TC-024 | specified |
| INST-REQ-079 | D-R5-9 | ARCH-5, ARCH-7 | INST-TC-027 | specified |
| INST-REQ-080 | INFERRED | ARCH-7, ARCH-12 | INST-TC-029 | specified |
| INST-REQ-091 | INFERRED | ARCH-5, ARCH-7 | INST-TC-031 | specified |
| INST-REQ-092 | D-R6-13 | ARCH-6, ARCH-7 | INST-TC-031 | specified |
| INST-REQ-093 | INFERRED | ARCH-7 | INST-TC-031 | specified |
| INST-REQ-094 | INFERRED | ARCH-7 | INST-TC-031 | specified |
| INST-REQ-095 | INFERRED | ARCH-9 | INST-TC-054 | specified |
| INST-REQ-096 | D-R5-1, D-R5-5 | ARCH-9 | INST-TC-054 | specified |
| INST-REQ-037 | D-R5-6 | ARCH-8, ARCH-13 | INST-TC-033 | specified |
| INST-REQ-038 | D-R5-6 | ARCH-8 | INST-TC-032 | specified |
| INST-REQ-039 | D-R5-6 | ARCH-8 | INST-TC-034 | specified |
| INST-REQ-040 | D-R5-3, D-R6-10 | ARCH-8 | INST-TC-035 | specified |
| INST-REQ-041 | D-R5-3 | ARCH-8 | INST-TC-036 | specified |
| INST-REQ-042 | D-R5-3 | ARCH-8 | INST-TC-037 | specified |
| INST-REQ-043 | D-R5-1, D-R5-5, D-R3-4, D-R6-4 | ARCH-9 | INST-TC-038 | specified |
| INST-REQ-044 | D-R5-1, D-R5-5 | ARCH-9 | INST-TC-039 | specified |
| INST-REQ-045 | D-R5-1 | ARCH-9 | INST-TC-039 | specified |
| INST-REQ-081 | D-R5-6 | ARCH-8, ARCH-13 | INST-TC-033 | specified |
| INST-REQ-082 | INFERRED | ARCH-8, ARCH-13 | INST-TC-034 | specified |
| INST-REQ-083 | D-R5-3 | ARCH-8 | INST-TC-037 | specified |
| INST-REQ-084 | D-R5-1, D-R5-5, D-R3-4, D-R6-4 | ARCH-9 | INST-TC-038 | specified |
| INST-REQ-046 | INFERRED | ARCH-10 | INST-TC-040 | specified |
| INST-REQ-047 | D-R4-6 | ARCH-10, ARCH-11 | INST-TC-040 | specified |
| INST-REQ-048 | D-R5-7, D-R6-11 | ARCH-10 | INST-TC-041 | specified |
| INST-REQ-049 | D-R5-7 | ARCH-10, ARCH-12 | INST-TC-041 | specified |
| INST-REQ-050 | D-R5-7 | ARCH-10, ARCH-12 | INST-TC-042 | specified |
| INST-REQ-051 | D-R4-6 | ARCH-11 | INST-TC-043 | specified |
| INST-REQ-052 | D-R4-6 | ARCH-11 | INST-TC-043 | specified |
| INST-REQ-053 | D-R4-6 | ARCH-11 | INST-TC-044 | specified |
| INST-REQ-054 | D-R4-6 | ARCH-11 | INST-TC-044 | specified |
| INST-REQ-055 | D-R4-6 | ARCH-11 | INST-TC-045 | specified |
| INST-REQ-085 | D-R5-7 | ARCH-10, ARCH-12 | INST-TC-042 | specified |
| INST-REQ-056 | D-R4-9, D-R6-3 | ARCH-1 | INST-TC-046 | specified |
| INST-REQ-057 | D-R6-3 | ARCH-1 | INST-TC-048 | specified |
| INST-REQ-058 | D-R5-8 | ARCH-1 | INST-TC-047 | specified |
| INST-REQ-059 | D-R4-9, D-R6-3, D-R6-7 | ARCH-1, ARCH-14 | INST-TC-048 | specified |
| INST-REQ-060 | D-R5-7, D-R4-7 | ARCH-12 | INST-TC-049 | specified |
| INST-REQ-061 | D-R4-3 | ARCH-14 | INST-TC-050 | specified |
| INST-REQ-062 | D-R4-7 | ARCH-14 | INST-TC-051 | specified |
| INST-REQ-063 | D-R4-3 | ARCH-14 | INST-TC-050 | specified |
| INST-REQ-064 | D-R1-5, D-R2-7 | ARCH-14, ARCH-15 | INST-TC-052 | specified |
| INST-REQ-065 | D-R1-5 | ARCH-15 | INST-TC-053 | specified |
| INST-REQ-086 | INFERRED | ARCH-1 | INST-TC-046 | specified |
| INST-REQ-087 | D-R6-5, D-R2-2 | ARCH-12 | INST-TC-049 | specified |
| INST-REQ-088 | D-R4-3 | ARCH-14 | INST-TC-050 | specified |
| INST-REQ-089 | D-R4-7, D-R3-4, D-R6-4 | ARCH-6, ARCH-14 | INST-TC-051 | specified |
| INST-REQ-090 | D-R2-7 | ARCH-15 | INST-TC-052 | specified |
| INST-REQ-097 | INFERRED | ARCH-14 | INST-TC-051 | specified |
| INST-REQ-098 | D-R6-2 | ARCH-3 | INST-TC-019 | specified |
| INST-REQ-099 | D-R6-5 | ARCH-4, ARCH-12 | INST-TC-055 | specified |
| INST-REQ-100 | D-R6-5, D-R3-1 | ARCH-4 | INST-TC-056 | specified |
| INST-REQ-101 | D-R6-9 | ARCH-14 | INST-TC-057 | specified |

## 2. Decisions to requirements

| Decision | Requirements, or why none |
|----------|---------------------------|
| D-R1-1 | INST-REQ-033, INST-REQ-034 |
| D-R1-2 | INST-REQ-005, INST-REQ-006, INST-REQ-013, INST-REQ-068 |
| D-R1-3 | INST-REQ-020, INST-REQ-021, INST-REQ-022, INST-REQ-023, INST-REQ-075 |
| D-R1-4 | INST-REQ-025, INST-REQ-026 |
| D-R1-5 | INST-REQ-064, INST-REQ-065 |
| D-R2-1 | INST-REQ-033 |
| D-R2-2 | INST-REQ-066 |
| D-R2-3 | INST-REQ-023, INST-REQ-024, INST-REQ-075, INST-REQ-076, INST-REQ-077 |
| D-R2-4 | INST-REQ-019 |
| D-R2-5 | INST-REQ-014, INST-REQ-015, INST-REQ-072 |
| D-R2-6 | INST-REQ-005, INST-REQ-068 |
| D-R2-7 | INST-REQ-064, INST-REQ-090 |
| D-R3-1 | INST-REQ-018, INST-REQ-019, INST-REQ-074 |
| D-R3-2 | INST-REQ-004, INST-REQ-011 |
| D-R3-3 | INST-REQ-034, INST-REQ-035, INST-REQ-036 |
| D-R3-4 | INST-REQ-030, INST-REQ-031, INST-REQ-043, INST-REQ-084, INST-REQ-089 |
| D-R3-5 | Superseded by D-R6-3 (INST-REQ-057) |
| D-R3-6 | INST-REQ-012, INST-REQ-029 |
| D-R4-1 | INST-REQ-001, INST-REQ-002, INST-REQ-003, INST-REQ-067 |
| D-R4-2 | INST-REQ-016, INST-REQ-017, INST-REQ-018, INST-REQ-073 |
| D-R4-3 | INST-REQ-061, INST-REQ-063, INST-REQ-088 |
| D-R4-4 | Not a requirement: the VM panel is an extension feature outside the installer (see architecture, section 9). |
| D-R4-5 | INST-REQ-007, INST-REQ-008, INST-REQ-009, INST-REQ-010, INST-REQ-069, INST-REQ-070, INST-REQ-071 |
| D-R4-6 | INST-REQ-047, INST-REQ-051, INST-REQ-052, INST-REQ-053, INST-REQ-054, INST-REQ-055 |
| D-R4-7 | INST-REQ-031, INST-REQ-060, INST-REQ-062, INST-REQ-089 |
| D-R4-8 | Not a requirement: container statistics are an extension panel feature (issue #40), outside the installer. |
| D-R4-9 | INST-REQ-056, INST-REQ-059 |
| D-R5-1 | INST-REQ-043, INST-REQ-044, INST-REQ-045, INST-REQ-084, INST-REQ-096 |
| D-R5-2 | INST-REQ-013, INST-REQ-014 |
| D-R5-3 | INST-REQ-040, INST-REQ-041, INST-REQ-042, INST-REQ-083 |
| D-R5-4 | INST-REQ-027, INST-REQ-028, INST-REQ-029, INST-REQ-035 |
| D-R5-5 | INST-REQ-043, INST-REQ-044, INST-REQ-084, INST-REQ-096 |
| D-R5-6 | INST-REQ-037, INST-REQ-038, INST-REQ-039, INST-REQ-081 |
| D-R5-7 | INST-REQ-048, INST-REQ-049, INST-REQ-050, INST-REQ-060, INST-REQ-085 |
| D-R5-8 | INST-REQ-058 |
| D-R5-9 | INST-REQ-032, INST-REQ-079 |
| D-R6-1 | INST-REQ-005, INST-REQ-006 |
| D-R6-2 | INST-REQ-023, INST-REQ-025, INST-REQ-026, INST-REQ-076, INST-REQ-098 |
| D-R6-3 | INST-REQ-056, INST-REQ-057, INST-REQ-059 |
| D-R6-4 | INST-REQ-004, INST-REQ-028, INST-REQ-030, INST-REQ-043, INST-REQ-084, INST-REQ-089 |
| D-R6-5 | INST-REQ-018, INST-REQ-021, INST-REQ-022, INST-REQ-087, INST-REQ-099, INST-REQ-100, INST-REQ-102 |
| D-R6-6 | INST-REQ-016, INST-REQ-017 |
| D-R6-7 | INST-REQ-004, INST-REQ-059 |
| D-R6-8 | INST-REQ-018 |
| D-R6-9 | INST-REQ-101 |
| D-R6-10 | INST-REQ-040 |
| D-R6-11 | INST-REQ-048 |
| D-R6-12 | INST-REQ-034, INST-REQ-036 |
| D-R6-13 | INST-REQ-030, INST-REQ-092 |
