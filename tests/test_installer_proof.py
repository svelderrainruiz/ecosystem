"""SL-8 tests: proof and release gate (INST-REQ-061, 072, 088, 101)."""
import contextlib
import hashlib
import importlib.util
import io
import os
import json
import re
import subprocess
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

from installer import proof

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "installer"
RULES = json.loads((INSTALLER / "repo-rules.json").read_text())
GOOD_PROTECTION = {"required_pull_request_reviews": {"require_code_owner_reviews": True, "required_approving_review_count": 1},
                   "enforce_admins": {"enabled": True}, "allow_force_pushes": {"enabled": False}}
GOOD_OWNERS = "# owners\n* @svelderrainruiz\n"
CLEAN_BASE = 'VMState="poweroff"\nCurrentSnapshotName="baked-2026-11-01"\nSnapshotName="baked-2026-11-01"\n'
HOSTED = (INSTALLER / "ci-windows.yml").read_text()
SAME_SHA = hashlib.sha256(b"same").hexdigest()
SELF_HOSTED_PR = "on:\n  pull_request:\njobs:\n  a:\n    runs-on: [self-hosted, linux]\n"


def load_script():
    spec = importlib.util.spec_from_file_location("rebuild_compare", INSTALLER / "rebuild-compare.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRun:
    def __init__(self, code, out):
        self.returncode, self.stdout = code, out


class FakeGh:
    """Stands in for `gh api`: answers the protection and CODEOWNERS calls."""

    def __init__(self, protection=GOOD_PROTECTION, owners=GOOD_OWNERS, code=0):
        self.protection, self.owners, self.code, self.calls = protection, owners, code, []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if self.code:
            return self.code, ""
        if any("protection" in c for c in cmd):
            return 0, json.dumps(self.protection)
        return 0, self.owners


class RebuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def write(self, name, data):
        p = self.d / name
        p.write_bytes(data)
        return p

    def test_rebuild_result_is_compared_with_release(self):
        """INST-REQ-072: equal and different outputs."""
        a, b, c = self.write("a", b"same"), self.write("b", b"same"), self.write("c", b"other")
        self.assertTrue(proof.compare_rebuild(a, b)[0])
        match, rel, reb = proof.compare_rebuild(a, c)
        self.assertFalse(match)
        self.assertNotEqual(rel, reb)

    def test_rebuild_refuses_missing_and_self_comparison(self):
        """INST-REQ-072: a missing file or the same file twice proves nothing."""
        a = self.write("a", b"x")
        with self.assertRaises(proof.RebuildError):
            proof.compare_rebuild(a, self.d / "none")
        with self.assertRaises(proof.RebuildError):
            proof.compare_rebuild(a, a)

    def test_rebuild_refuses_empty_inputs(self):
        """INST-REQ-072: two empty files must not read as a match."""
        a, b, c = self.write("a", b""), self.write("b", b""), self.write("c", b"x")
        for x, y in ((a, b), (a, c), (c, a)):
            with self.assertRaises(proof.RebuildError):
                proof.compare_rebuild(x, y)

    def test_rebuild_script_exit_codes(self):
        """INST-REQ-072: the script exits 0 on MATCH, 1 on DIFFER, 2 on refusal."""
        a, b, c = self.write("a", b"same"), self.write("b", b"same"), self.write("c", b"other")
        mod = load_script()
        self.assertEqual(proof.compare_main([str(a), str(b)]), 0)
        self.assertEqual(proof.compare_main([str(a), str(c)]), 1)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(proof.compare_main([str(a)]), 2)
        self.assertIn("usage: rebuild-compare.py RELEASE REBUILT", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(proof.compare_main([str(a), str(self.d / "none")]), 2)
        self.assertIn("not a file: none", out.getvalue())
        self.assertTrue(callable(mod.proof.compare_main))
        r = subprocess.run(["python3", str(INSTALLER / "rebuild-compare.py"), str(a), str(c)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("DIFFER", r.stdout)


class WorkflowTests(unittest.TestCase):
    def test_hosted_windows_check_runs_on_every_change(self):
        """INST-REQ-061: the workflow runs on Windows for every push and pull request."""
        proof.check_workflow(HOSTED)
        self.assertRegex(HOSTED, r"runs-on:\s*windows-")

    def test_workflow_with_filters_or_missing_trigger_is_refused(self):
        """INST-REQ-061: a filter or a missing trigger means not every change."""
        for bad in (HOSTED.replace("  push:\n", "  push:\n    branches: [main]\n"),
                    HOSTED.replace("  pull_request:\n", "  pull_request:\n    paths: ['x']\n"),
                    HOSTED.replace("  push:\n", ""),
                    HOSTED.replace("  pull_request:\n", ""),
                    HOSTED.replace("windows-2025", "ubuntu-24.04"),
                    HOSTED.replace("    steps:", "    if: false\n    steps:")):
            with self.assertRaises(proof.WorkflowError):
                proof.check_workflow(bad)

    def test_every_runs_on_value_must_be_hosted_windows(self):
        """INST-REQ-061: list forms, block lists and a second job cannot hide a non-Windows or self-hosted runner."""
        for bad in (HOSTED.replace("runs-on: windows-2025", "runs-on: [windows-2025, self-hosted]"),
                    HOSTED.replace("runs-on: windows-2025", "runs-on:\n      - windows-2025\n      - self-hosted"),
                    HOSTED + "  other:\n    runs-on: ubuntu-24.04\n    steps: []\n",
                    HOSTED.replace("    runs-on: windows-2025\n", "")):
            with self.assertRaises(proof.WorkflowError):
                proof.check_workflow(bad)
        proof.check_workflow(HOSTED.replace("runs-on: windows-2025", "runs-on:\n      - windows-2025  # hosted"))

    def test_workflow_is_not_enabled_before_the_repository_is_public(self):
        """INST-REQ-061/063: the file sits in installer/, not in .github/workflows."""
        self.assertFalse((ROOT / ".github" / "workflows" / "ci-windows.yml").exists())


class RulesTests(unittest.TestCase):
    def test_repo_rules_require_pr_and_no_fork_pr_on_self_hosted_runner(self):
        """INST-REQ-101: pull requests only, no fork pull request on a self-hosted runner, operator the only code owner."""
        gh = FakeGh()
        result = proof.check_repo_rules(RULES, gh, [("ci.yml", "on:\n  pull_request:\njobs:\n  a:\n    runs-on: ubuntu-24.04\n")])
        self.assertTrue(result["ok"])
        self.assertTrue(any("branches/main/protection" in " ".join(c) for c in gh.calls))

    def test_repo_rules_refuse_each_violation(self):
        """INST-REQ-101: each rule fails closed."""
        wf = [("ci.yml", "on:\n  pull_request:\n")]
        cases = [
            (FakeGh(protection={}), wf),
            (FakeGh(protection={"required_pull_request_reviews": {"require_code_owner_reviews": False}}), wf),
            (FakeGh(owners="* @svelderrainruiz @someone-else\n"), wf),
            (FakeGh(owners="# nothing\n"), wf),
            (FakeGh(code=1), wf),
            (FakeGh(), [("bad.yml", SELF_HOSTED_PR)]),
            (FakeGh(), [("bad.yml", "on: [pull_request_target]\njobs:\n  a:\n    runs-on: self-hosted\n")]),
        ]
        for gh, files in cases:
            with self.assertRaises(proof.RulesError):
                proof.check_repo_rules(RULES, gh, files)

    def test_self_hosted_job_is_allowed_with_a_fork_guard_or_no_pr_trigger(self):
        """INST-REQ-101: a self-hosted job off the pull request trigger, or guarded against forks, is fine."""
        push_only = "on:\n  push:\njobs:\n  a:\n    runs-on: self-hosted\n"
        guarded = SELF_HOSTED_PR + "    if: github.event.pull_request.head.repo.full_name == github.repository\n"
        proof.check_repo_rules(RULES, FakeGh(), [("a.yml", push_only), ("b.yml", guarded)])

    def test_protection_shape_and_strength_are_validated(self):
        """INST-REQ-101: wrong shapes are RulesError, and weak settings are refused."""
        def prot(**over):
            p = json.loads(json.dumps(GOOD_PROTECTION))
            p.update(over)
            return p
        weak = [prot(enforce_admins={"enabled": False}), prot(enforce_admins=None), prot(enforce_admins=True),
                prot(allow_force_pushes={"enabled": True}), prot(allow_force_pushes=None),
                prot(required_pull_request_reviews={"require_code_owner_reviews": True, "required_approving_review_count": 0}),
                prot(required_pull_request_reviews={"require_code_owner_reviews": True}),
                prot(required_pull_request_reviews="yes"), prot(required_pull_request_reviews=None), []]
        for p in weak:
            with self.assertRaises(proof.RulesError, msg=p):
                proof.check_repo_rules(RULES, FakeGh(protection=p), [])
        with self.assertRaises(proof.RulesError):
            proof.check_repo_rules(RULES, lambda cmd: (0, "not json"), [])

    def test_fork_guard_must_be_a_condition_and_other_triggers_count(self):
        """INST-REQ-101: a comment is no guard; workflow_run and issue_comment are untrusted triggers; block lists are read."""
        commented = SELF_HOSTED_PR + "    # head.repo.full_name == github.repository\n"
        block = "on:\n  pull_request:\njobs:\n  a:\n    runs-on:\n      - self-hosted\n"
        run = "on:\n  workflow_run:\njobs:\n  a:\n    runs-on: self-hosted\n"
        comment = "on: issue_comment\njobs:\n  a:\n    runs-on: [self-hosted]\n"
        for text in (commented, block, run, comment):
            with self.assertRaises(proof.RulesError, msg=text):
                proof.check_repo_rules(RULES, FakeGh(), [("w.yml", text)])

    def test_rules_file_names_only_the_operator(self):
        """INST-REQ-101: the rules file itself."""
        self.assertTrue(RULES["pull_request_required"] and RULES["code_owner_review_required"])
        self.assertFalse(RULES["fork_pull_request_on_self_hosted_runner"])
        self.assertEqual(RULES["code_owner"], "svelderrainruiz")

    def test_repository_workflows_pass_the_fork_rule(self):
        """INST-REQ-101: the real workflows of this tree obey the rule."""
        files = [(p.name, p.read_text()) for p in (ROOT / ".github" / "workflows").glob("*.yml")]
        proof.check_repo_rules(RULES, FakeGh(), files)


class BaseTests(unittest.TestCase):
    def test_proof_script_refuses_a_dirty_base(self):
        """INST-REQ-088: the clean-base precondition."""
        proof.check_base_clean(CLEAN_BASE)
        for bad in (CLEAN_BASE.replace("poweroff", "running"),
                    CLEAN_BASE.replace('CurrentSnapshotName="baked-2026-11-01"\n', ""),
                    CLEAN_BASE.replace('CurrentSnapshotName="baked-2026-11-01"', 'CurrentSnapshotName="scratch"'),
                    CLEAN_BASE + 'SnapshotName-1="after-proof"\nCurrentSnapshotName="after-proof"\n',
                    ""):
            with self.assertRaises(proof.DirtyBase):
                proof.check_base_clean(bad)

    def test_dirty_base_stops_the_gate_before_the_guest_proof(self):
        """INST-REQ-088: the guest proof is never called on a dirty base."""
        called = []
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(proof.DirtyBase):
                proof.gate(out_dir=d, vm_info=lambda: CLEAN_BASE.replace("poweroff", "saved"),
                           guest=lambda: called.append(1) or "pass", rules=RULES, gh=FakeGh(), workflows=[],
                           workflow_text=HOSTED, release=None, rebuilt=None)
            self.assertEqual(list(Path(d).iterdir()), [])
        self.assertEqual(called, [])


class GateTests(unittest.TestCase):
    def run_gate(self, d, **over):
        a = Path(d) / "rel.exe"
        a.write_bytes(b"same")
        b = Path(d) / "reb.exe"
        b.write_bytes(over.pop("rebuilt_bytes", b"same"))
        args = dict(out_dir=d, vm_info=lambda: CLEAN_BASE, guest=lambda: "pass " + SAME_SHA, rules=RULES, gh=FakeGh(), workflows=[],
                    workflow_text=HOSTED, release=a, rebuilt=b,
                    now=lambda: datetime(2026, 11, 21, 21, 0, 5, tzinfo=timezone.utc))
        args.update(over)
        return proof.gate(**args)

    def test_gate_writes_a_utc_stamped_evidence_file(self):
        """INST-REQ-061/072/088/101: one command, one UTC-stamped evidence file."""
        with tempfile.TemporaryDirectory() as d:
            path = self.run_gate(d)
            self.assertEqual(path.name, "release-gate-20261121T210005.000000Z.json")
            ev = json.loads(path.read_text())
        self.assertEqual(ev["result"], "pass")
        self.assertTrue(ev["utc"].endswith("+00:00"))
        self.assertEqual(set(ev["checks"]), {"workflow", "repo_rules", "base_clean", "rebuild", "guest_proof"})
        self.assertNotIn("/", json.dumps(ev["checks"]["rebuild"]))

    def test_gate_fails_on_rebuild_difference_or_guest_failure(self):
        """INST-REQ-072/088: any failed check fails the gate and the file says which."""
        with tempfile.TemporaryDirectory() as d:
            ev = json.loads(self.run_gate(d, rebuilt_bytes=b"other").read_text())
            self.assertEqual((ev["result"], ev["checks"]["rebuild"]["ok"]), ("fail", False))
        with tempfile.TemporaryDirectory() as d:
            ev = json.loads(self.run_gate(d, guest=lambda: "fail").read_text())
            self.assertEqual((ev["result"], ev["checks"]["guest_proof"]["ok"]), ("fail", False))

    def test_gate_without_guest_proof_is_pending_not_pass(self):
        """INST-REQ-088: the host side alone never reads as a pass."""
        with tempfile.TemporaryDirectory() as d:
            ev = json.loads(self.run_gate(d, guest=None).read_text())
        self.assertEqual(ev["result"], "pending-guest")

    def test_cli_runs_the_gate_with_fakes(self):
        """The command line runs the gate: exit 0 only for pass, 3 for pending-guest, 1 for fail, 2 for a refusal."""
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(proof.main(["gate"]), 2)
        self.assertIn("required: --out, --release, --rebuilt, --vm", err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(proof.main(["nonsense"]), 2)
        self.assertIn("invalid choice: 'nonsense'", err.getvalue())
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "rel").write_bytes(b"same")
            (d / "reb").write_bytes(b"same")
            (d / "guest").write_text("pass " + SAME_SHA)
            base = ["gate", "--out", str(d), "--release", str(d / "rel"), "--rebuilt", str(d / "reb"), "--vm", "base"]
            calls = []

            def run(cmd, **kw):
                calls.append(cmd)
                return FakeRun(0, CLEAN_BASE)

            def go(extra=(), fake=run, gh=None):
                for f in d.glob("release-gate-*"):
                    f.unlink()
                return proof.main(base + list(extra), gh=gh or FakeGh(), run=fake)

            self.assertEqual(go(["--guest-result", str(d / "guest")]), 0)
            self.assertEqual(calls[-1][-2:], ["--", "base"])
            self.assertEqual(go(), 3)
            (d / "guest").write_text("fail")
            self.assertEqual(go(["--guest-result", str(d / "guest")]), 1)
            self.assertEqual(go(["--guest-result", str(d / "guest")], gh=FakeGh(code=1)), 1)
            self.assertEqual(go(fake=lambda *a, **k: FakeRun(0, CLEAN_BASE.replace("poweroff", "running"))), 2)
            self.assertEqual(go(fake=mock.Mock(side_effect=subprocess.TimeoutExpired("x", 1))), 2)

    def test_each_failing_sub_check_fails_the_gate(self):
        """INST-REQ-061/101/072: workflow, repo rules (bad shape, bad rule) and rebuild each fail inside gate(); a dirty base refuses."""
        bad_wf = HOSTED.replace("windows-2025", "ubuntu-24.04")
        cases = [("workflow", dict(workflow_text=bad_wf)),
                 ("repo_rules", dict(gh=FakeGh(protection=[]))),
                 ("repo_rules", dict(gh=FakeGh(protection={"required_pull_request_reviews": 5}))),
                 ("repo_rules", dict(gh=FakeGh(owners="* @other\n"))),
                 ("repo_rules", dict(workflows=[("x.yml", SELF_HOSTED_PR)])),
                 ("rebuild", dict(rebuilt_bytes=b"other"))]
        for name, over in cases:
            with tempfile.TemporaryDirectory() as d:
                ev = json.loads(self.run_gate(d, **over).read_text())
            self.assertEqual((ev["result"], ev["checks"][name]["ok"]), ("fail", False), (name, over))
        with tempfile.TemporaryDirectory() as d, self.assertRaises(proof.DirtyBase):
            self.run_gate(d, vm_info=lambda: CLEAN_BASE.replace("poweroff", "running"))

    def test_guest_result_must_carry_the_release_hash(self):
        """INST-REQ-088: a bare pass, another hash, or extra words fail."""
        for text in ("pass", "pass " + "0" * 64, "pass " + SAME_SHA + " extra", "ok " + SAME_SHA, ""):
            with tempfile.TemporaryDirectory() as d:
                ev = json.loads(self.run_gate(d, guest=lambda t=text: t).read_text())
            self.assertEqual(ev["result"], "fail", text)

    def test_evidence_is_never_overwritten(self):
        """INST-REQ-088: a second gate in the same microsecond refuses; no temp file is left."""
        with tempfile.TemporaryDirectory() as d:
            first = self.run_gate(d)
            before = first.read_text()
            with self.assertRaises(proof.ProofError):
                self.run_gate(d)
            self.assertEqual(first.read_text(), before)
            self.assertEqual([p.name for p in Path(d).iterdir() if p.name.endswith(".tmp")], [])

    def test_no_secret_or_host_in_the_new_files(self):
        """No key material, host name or address in the SL-8 files."""
        for name in ("proof.py", "repo-rules.json", "ci-windows.yml", "rebuild-compare.py"):
            text = (INSTALLER / name).read_text()
            self.assertIsNone(re.search(r"\d+\.\d+\.\d+\.\d+|BEGIN [A-Z ]*PRIVATE|ghp_|password", text, re.I), name)


if __name__ == "__main__":
    unittest.main()
