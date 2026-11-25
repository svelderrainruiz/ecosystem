#!/usr/bin/env python3
"""Proof and release gate (ARCH-14): one command runs the host checks and writes a UTC-stamped evidence file.

  python3 -m installer.proof gate --out DIR --release FILE --rebuilt FILE --vm NAME [--guest-result FILE]
  python3 -m installer.proof compare RELEASE REBUILT

Checks: hosted Windows workflow (INST-REQ-061), agent rebuild equals release (INST-REQ-072), clean Windows 11 base
before the proof (INST-REQ-088), repository rules (INST-REQ-101). The guest proof itself is run by the operator's
tooling and handed in as a result file; without it the gate says pending-guest, never pass. Every expected refusal is a
ProofError printed as one line (exit 2). Evidence holds file names and sha256 hashes only.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from installer import build, log

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RULES_PATH = HERE / "repo-rules.json"
WORKFLOW_PATH = HERE / "ci-windows.yml"
BASE_SNAPSHOT = re.compile(r"^baked-[0-9A-Za-z._-]+$")
FORK_GUARD = "head.repo.full_name == github.repository"
UNTRUSTED_TRIGGER = re.compile(r"\b(pull_request(_target)?|workflow_run|issue_comment)\b")


EXIT = {"pass": 0, "fail": 1, "pending-guest": 3}


class ProofError(Exception):
    """Base of every expected refusal."""


class RebuildError(ProofError):
    pass


class WorkflowError(ProofError):
    pass


class RulesError(ProofError):
    pass


class DirtyBase(ProofError):
    pass


def compare_rebuild(release, rebuilt):
    """INST-REQ-072: (match, release sha256, rebuilt sha256). The same file twice proves nothing."""
    release, rebuilt = Path(release), Path(rebuilt)
    for p in (release, rebuilt):
        if not p.is_file():
            raise RebuildError(f"not a file: {p.name}")
    if release.stat().st_size == 0 or rebuilt.stat().st_size == 0:
        raise RebuildError("an empty file proves nothing")
    if release.resolve() == rebuilt.resolve():
        raise RebuildError("release and rebuild are the same file")
    a, b = build.sha256_file(release), build.sha256_file(rebuilt)
    return a == b, a, b


def compare_main(argv):
    if len(argv) != 2:
        print("usage: rebuild-compare.py RELEASE REBUILT")
        return 2
    try:
        match, a, b = compare_rebuild(*argv)
    except ProofError as e:
        print(f"REFUSED: {e}")
        return 2
    print(f"MATCH {a}" if match else f"DIFFER release {a} rebuilt {b}")
    return 0 if match else 1


def _section(text, key):
    """Lines of the top-level `key:` block of a workflow file (no YAML library: the files are simple)."""
    out, inside = [], False
    for line in text.splitlines():
        if re.match(r"^\S", line):
            inside = line.startswith(key + ":")
            if inside:
                out.append(line)
        elif inside:
            out.append(line)
    return out


def runs_on_values(text):
    """Every runs-on value of the file: inline scalar, inline list, or a block list on the following lines."""
    out, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)runs-on:\s*(.*?)\s*(#.*)?$", line)
        if not m:
            continue
        value = m.group(2)
        if value:
            out += [v.strip().strip("'\"") for v in value.strip("[]").split(",") if v.strip()]
            continue
        for nxt in lines[i + 1:]:
            b = re.match(r"^\s*-\s*(.*?)\s*(#.*)?$", nxt)
            if not b:
                if nxt.strip() and not nxt.lstrip().startswith("#"):
                    break
                continue
            out.append(b.group(1).strip("'\""))
    return out


def check_workflow(text):
    """INST-REQ-061: runs on Windows for every push and pull request, with no filter and no job condition."""
    on = "\n".join(_section(text, "on"))
    for trigger in ("push", "pull_request"):
        if not re.search(rf"^\s+{trigger}:\s*$", on, re.M):
            raise WorkflowError(f"trigger missing or filtered: {trigger}")
    if re.search(r"\b(branches|branches-ignore|paths|paths-ignore|tags|types):", on):
        raise WorkflowError("a trigger filter means not every change")
    labels = runs_on_values(text)
    if not labels or not all(l.startswith("windows-") for l in labels):
        raise WorkflowError("every job must run on hosted Windows")
    if re.search(r"^\s+if:", text, re.M):
        raise WorkflowError("a job condition means not every change")
    return True


def check_base_clean(info_text):
    """INST-REQ-088: the base is powered off and its current snapshot is the only baked one (no state after the bake)."""
    fields = {}
    for line in info_text.splitlines():
        k, sep, v = line.partition("=")
        if sep:
            fields.setdefault(k.strip(), []).append(v.strip().strip('"'))
    if fields.get("VMState", [None])[0] != "poweroff":
        raise DirtyBase("the base is not powered off")
    current = fields.get("CurrentSnapshotName", [None])[0]
    if not current or not BASE_SNAPSHOT.match(current):
        raise DirtyBase("the base is not at its baked snapshot")
    snaps = [v[0] for k, v in fields.items() if k.startswith("SnapshotName")]
    if snaps != [current]:
        raise DirtyBase("the base holds snapshots other than the baked one")
    return True


def default_gh(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RulesError(f"gh unavailable: {type(e).__name__}") from None
    return r.returncode, r.stdout


def _owners(text):
    rules = [l.split() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    return rules, {t for r in rules for t in r[1:]}


def check_repo_rules(rules, gh, workflows):
    """INST-REQ-101: pull requests only, operator the only code owner, no fork pull request on a self-hosted runner."""
    repo, branch = rules["repository"], rules["branch"]
    code, out = gh(["gh", "api", f"repos/{repo}/branches/{branch}/protection"])
    if code:
        raise RulesError("branch protection could not be read")
    try:
        prot = json.loads(out)
    except ValueError:
        raise RulesError("branch protection answer is not JSON") from None
    if not isinstance(prot, dict):
        raise RulesError("branch protection answer has the wrong shape")
    review = prot.get("required_pull_request_reviews")
    if rules["pull_request_required"] and not isinstance(review, dict):
        raise RulesError("the default branch does not require pull requests")
    review = review if isinstance(review, dict) else {}
    if rules["code_owner_review_required"] and review.get("require_code_owner_reviews") is not True:
        raise RulesError("code owner review is not required")
    count = review.get("required_approving_review_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise RulesError("at least one approving review is required")
    admins = prot.get("enforce_admins")
    if not isinstance(admins, dict) or admins.get("enabled") is not True:
        raise RulesError("the rules do not apply to administrators")
    force = prot.get("allow_force_pushes")
    if not isinstance(force, dict) or force.get("enabled") is not False:
        raise RulesError("force pushes are not refused")
    code, out = gh(["gh", "api", f"repos/{repo}/contents/.github/CODEOWNERS", "-H", "Accept: application/vnd.github.raw"])
    if code:
        raise RulesError("CODEOWNERS could not be read")
    entries, owners = _owners(out)
    if not entries or owners != {"@" + rules["code_owner"]}:
        raise RulesError("the operator is not the only code owner")
    for name, text in workflows:
        guarded = any(re.match(r"^\s*(-\s*)?if:.*" + re.escape(FORK_GUARD), l) for l in text.splitlines())
        if (not rules["fork_pull_request_on_self_hosted_runner"] and UNTRUSTED_TRIGGER.search("\n".join(_section(text, "on")))
                and any("self-hosted" in v for v in runs_on_values(text)) and not guarded):
            raise RulesError(f"{name}: a pull request from a fork could reach a self-hosted runner")
    return {"ok": True}


def gate(out_dir, vm_info, guest, rules, gh, workflows, workflow_text, release, rebuilt, now=None):
    """Run every check, write release-gate-<UTC>.json, return its path. A dirty base refuses before anything is written."""
    moment = now() if now else datetime.now(timezone.utc)
    check_base_clean(vm_info())
    checks = {}

    def record(name, fn):
        try:
            checks[name] = {"ok": True, **(fn() or {})}
        except ProofError as e:
            checks[name] = {"ok": False, "error": str(e)}

    record("workflow", lambda: {"ok": check_workflow(workflow_text)})
    record("repo_rules", lambda: check_repo_rules(rules, gh, workflows))
    checks["base_clean"] = {"ok": True}

    def rebuild():
        match, a, b = compare_rebuild(release, rebuilt)
        return {"ok": match, "release_sha256": a, "rebuilt_sha256": b}

    record("rebuild", rebuild)
    checks["guest_proof"] = guest_check(guest() if guest else None, release)
    host_ok = all(c["ok"] for k, c in checks.items() if k != "guest_proof")
    guest_state = checks["guest_proof"]["result"]
    result = "fail" if not host_ok or guest_state == "fail" else "pass" if guest_state == "pass" else "pending-guest"
    stamp = moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = Path(out_dir) / f"release-gate-{stamp}.json"
    tmp = Path(out_dir) / f".release-gate-{os.getpid()}.tmp"
    tmp.write_text(json.dumps({"utc": log.utc_iso(moment), "result": result, "checks": checks}, indent=1) + "\n")
    try:
        os.link(tmp, path)
    except FileExistsError:
        raise ProofError(f"evidence file exists: {path.name}") from None
    finally:
        tmp.unlink()
    return path


def guest_check(text, release):
    """INST-REQ-088: the guest result must be `pass <sha256 of the release installer>`; a bare pass or another hash fails."""
    if text is None:
        return {"ok": False, "result": "pending-guest"}
    parts = text.split()
    try:
        want = build.sha256_file(release)
    except (OSError, TypeError):
        want = None
    if parts[:1] == ["pass"] and len(parts) == 2 and parts[1] == want:
        return {"ok": True, "result": "pass"}
    return {"ok": False, "result": "fail", "error": "guest result is not `pass <release sha256>`"}


def main(argv=None, gh=default_gh, run=subprocess.run):
    ap = argparse.ArgumentParser(prog="installer.proof")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate")
    g.add_argument("--out", required=True)
    g.add_argument("--release", required=True)
    g.add_argument("--rebuilt", required=True)
    g.add_argument("--vm", required=True)
    g.add_argument("--guest-result")
    c = sub.add_parser("compare")
    c.add_argument("release")
    c.add_argument("rebuilt")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if a.cmd == "compare":
        return compare_main([a.release, a.rebuilt])
    rules = json.loads(RULES_PATH.read_text())
    wf = [(p.name, p.read_text()) for p in sorted((ROOT / ".github" / "workflows").glob("*.yml"))]

    def vm_info():
        try:
            r = run(["VBoxManage", "showvminfo", "--machinereadable", "--", a.vm], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise DirtyBase("the base could not be inspected") from None
        if r.returncode:
            raise DirtyBase("the base could not be inspected")
        return r.stdout

    guest = (lambda: Path(a.guest_result).read_text().strip()) if a.guest_result else None
    try:
        path = gate(a.out, vm_info, guest, rules, gh, wf, WORKFLOW_PATH.read_text(), a.release, a.rebuilt)
    except (ProofError, OSError) as e:
        print(f"REFUSED: {e}")
        return 2
    result = json.loads(path.read_text())["result"]
    print(f"evidence: {path.name} {result}")
    return EXIT[result]


if __name__ == "__main__":
    sys.exit(main())
