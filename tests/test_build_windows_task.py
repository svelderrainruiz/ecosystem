"""OPBUILD-2 (#243): the VS Code build task and tools/build-windows.ps1. The real script runs under pwsh with stub git, gh and
python on a PATH that holds only the stubs, so no real clone, build or network call happens. Script tests are skipped when pwsh is
absent; the tasks.json and guide checks always run."""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build-windows.ps1"
TASKS = ROOT / ".vscode" / "tasks.json"
GUIDE = ROOT / "installer" / "BUILD-WINDOWS.md"
PWSH = shutil.which("pwsh")
HEAD = "0123456789abcdef0123456789abcdef01234567"
PAYLOAD = "Stand-in runner payload for a UI test build."
SUMS_LINE = "abcd0123" * 8 + "  installer.exe"
REPORT_LINE = ("Report your run: https://github.com/svelderrainruiz/ecosystem-control/issues/new"
               f"?template=installer-test-run.yml&built-from={HEAD[:12]}&installer-sha256=" + "abcd0123" * 8)

STUB_HEAD = "#!/bin/sh\nPATH=/usr/bin:/bin; export PATH\nprintf '%s|%s|%s\\n' \"$(basename \"$0\")\" \"$PWD\" \"$*\" >> \"$STUB_LOG\"\n"
STUBS = {
    "gh": STUB_HEAD + 'mkdir -p "$4"\nexit "${STUB_GH_RC:-0}"\n',
    "git": STUB_HEAD + """case "$3" in
  fetch) echo "From github.com:svelderrainruiz/ecosystem-control" >&2; exit "${STUB_FETCH_RC:-0}" ;;
  checkout) exit "${STUB_CHECKOUT_RC:-0}" ;;
  rev-parse) echo "%s"; exit 0 ;;
esac
exit 9
""" % HEAD,
    "python": STUB_HEAD + """echo "PYTHONDONTWRITEBYTECODE=$PYTHONDONTWRITEBYTECODE" >> "$STUB_LOG"
case "$2 $3" in
  "installer.build check") exit "${STUB_CHECK_RC:-0}" ;;
  "installer.guest.vmkit build") mkdir -p "$5"; printf '%%s\\n' "%s" > "$5/SHA256SUMS"; cp "$7" "$STUB_LOG.payload"; echo OK
     exit "${STUB_BUILD_RC:-0}" ;;
  "installer.guest.vmkit verify") echo OK; exit "${STUB_VERIFY_RC:-0}" ;;
esac
exit 9
""" % SUMS_LINE,
}


@unittest.skipUnless(PWSH, "pwsh absent")
class BuildScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.work = self.tmp / "work"
        self.log = self.tmp / "calls.log"
        self.src = self.work / "src"
        self.kit = self.work / "kit" / HEAD[:12]

    def run_script(self, branch="develop", stubs=("gh", "git", "python"), request=None, **rcs):
        for old in self.bin.iterdir():
            old.unlink()
        for name in stubs:
            path = self.bin / name
            path.write_text(STUBS[name], encoding="ascii")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        env = {**os.environ, "PATH": str(self.bin), "STUB_LOG": str(self.log)}
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        env.update({k: str(v) for k, v in rcs.items()})
        args = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT), "-Branch", branch, "-Work", str(self.work)]
        if request is not None:
            args += ["-Request", str(request)]
        r = subprocess.run(args, capture_output=True, text=True, env=env, cwd=self.tmp, timeout=120)
        return r.returncode, r.stdout + r.stderr

    def calls(self):
        if not self.log.exists():
            return []
        return [line.split("|") for line in self.log.read_text().splitlines() if "|" in line]

    def commands(self):
        return [f"{name} {args}" for name, _, args in self.calls()]

    def test_fresh_build_clones_builds_and_verifies(self):
        rc, out = self.run_script()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.commands(), [
            f"gh repo clone svelderrainruiz/ecosystem-control {self.src}",
            f"git -C {self.src} fetch --prune origin",
            f"git -C {self.src} checkout --detach origin/develop",
            f"git -C {self.src} rev-parse HEAD",
            "python -m installer.build check",
            f"python -m installer.guest.vmkit build --out {self.kit} --payload {self.work / 'stand-in-payload.txt'}",
            f"python -m installer.guest.vmkit verify {self.kit}",
        ])
        self.assertEqual({cwd for name, cwd, _ in self.calls() if name == "python"}, {str(self.src)})
        self.assertNotIn("PYTHONDONTWRITEBYTECODE=\n", self.log.read_text())
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", self.log.read_text())
        self.assertEqual(Path(str(self.log) + ".payload").read_text().strip(), PAYLOAD)
        self.assertIn(f"KIT OK {self.kit}", out)
        self.assertIn(f"Commit: {HEAD} (origin/develop)", out)
        lines = out.splitlines()
        self.assertEqual(lines[lines.index(f"installer.exe line of SHA256SUMS: {SUMS_LINE}") + 1], REPORT_LINE)
        self.assertEqual(out.count("Report your run:"), 1)
        self.assertIn("installer.exe was not started", out)

    def test_report_link_encodes_request_issue(self):
        rc, out = self.run_script(request=261)
        self.assertEqual(rc, 0, out)
        self.assertIn(REPORT_LINE + "&request=%23261", out.splitlines())

    def test_no_report_link_without_one_valid_installer_checksum(self):
        self.kit.mkdir(parents=True)
        for case, sums in [
            ("no installer", "f" * 64 + "  VM-TEST.md"),
            ("two installers", SUMS_LINE + "\n" + SUMS_LINE),
            ("non-hex hash", "g" * 64 + "  installer.exe"),
            ("short hash", "a" * 63 + "  installer.exe"),
            ("uppercase hash", "A" * 64 + "  installer.exe"),
            ("binary marker", "f" * 64 + " *installer.exe"),
            ("extra field", "f" * 64 + "  extra  installer.exe"),
            ("prefixed name", "f" * 64 + "  old-installer.exe"),
            ("backup name", "f" * 64 + "  installer.exe.bak"),
            ("subdirectory", "f" * 64 + "  sub/installer.exe"),
            ("valid plus backup", SUMS_LINE + "\n" + "f" * 64 + "  installer.exe.bak"),
        ]:
            with self.subTest(case=case):
                (self.kit / "SHA256SUMS").write_text(sums + "\n")
                rc, out = self.run_script()
                self.assertEqual(rc, 0, out)
                self.assertIn(f"KIT OK {self.kit}", out)
                self.assertNotIn("Report your run:", out)

    def test_existing_clone_needs_no_gh_and_builds_the_named_branch(self):
        self.src.mkdir(parents=True)
        rc, out = self.run_script(branch="feature/ui1-239", stubs=("git", "python"))
        self.assertEqual(rc, 0, out)
        cmds = self.commands()
        self.assertFalse([c for c in cmds if c.startswith("gh ")])
        self.assertIn(f"git -C {self.src} checkout --detach origin/feature/ui1-239", cmds)
        self.assertIn("(origin/feature/ui1-239)", out)

    def test_existing_kit_is_verified_not_rebuilt(self):
        self.src.mkdir(parents=True)
        self.kit.mkdir(parents=True)
        (self.kit / "SHA256SUMS").write_text(SUMS_LINE + "\n")
        rc, out = self.run_script()
        self.assertEqual(rc, 0, out)
        cmds = self.commands()
        self.assertFalse([c for c in cmds if "vmkit build" in c])
        self.assertEqual(cmds[-1], f"python -m installer.guest.vmkit verify {self.kit}")
        self.assertIn("already exists; verifying it again", out)

    def test_empty_kit_folder_from_a_failed_run_is_built(self):
        self.src.mkdir(parents=True)
        self.kit.mkdir(parents=True)
        rc, out = self.run_script()
        self.assertEqual(rc, 0, out)
        self.assertIn(f"python -m installer.guest.vmkit build --out {self.kit} --payload {self.work / 'stand-in-payload.txt'}", self.commands())
        self.assertNotIn("already exists", out)
        self.assertIn(f"KIT OK {self.kit}", out)

    def test_partial_kit_that_fails_verify_says_to_delete_it(self):
        self.src.mkdir(parents=True)
        self.kit.mkdir(parents=True)
        (self.kit / "nsis-3.10.zip.part").write_text("x")
        rc, out = self.run_script(STUB_VERIFY_RC=2)
        self.assertEqual(rc, 2, out)
        self.assertFalse([c for c in self.commands() if "vmkit build" in c])
        self.assertIn("STOPPED at vmkit verify (exit 2)", out)
        self.assertIn(f"delete {self.kit} and run the task again", out)
        self.assertNotIn("KIT OK", out)

    def test_fetch_progress_on_stderr_does_not_stop_the_build(self):
        rc, out = self.run_script()
        self.assertEqual(rc, 0, out)
        self.assertIn("From github.com:svelderrainruiz/ecosystem-control", out)
        self.assertNotIn("STOPPED", out)

    def test_each_failing_step_stops_the_build_with_its_exit_code(self):
        cases = [("STUB_FETCH_RC", 128, "fetch origin", "checkout"),
                 ("STUB_CHECKOUT_RC", 1, "check out origin/develop", "rev-parse"),
                 ("STUB_CHECK_RC", 2, "installer.build check", "vmkit"),
                 ("STUB_BUILD_RC", 2, "vmkit build", "verify"),
                 ("STUB_VERIFY_RC", 2, "vmkit verify", None)]
        for var, code, step, never in cases:
            with self.subTest(step=step):
                shutil.rmtree(self.work, ignore_errors=True)
                self.log.unlink(missing_ok=True)
                rc, out = self.run_script(**{var: code})
                self.assertEqual(rc, code, out)
                self.assertIn(f"STOPPED at {step} (exit {code})", out)
                self.assertNotIn("KIT OK", out)
                if never:
                    self.assertFalse([c for c in self.commands() if never in c], self.commands())

    def test_bad_branch_is_refused_before_any_command(self):
        for branch in ("x;rm", "a..b", "a b", "/x", "x$y"):
            with self.subTest(branch=branch):
                rc, out = self.run_script(branch=branch)
                self.assertEqual(rc, 2, out)
                self.assertIn("Refused: branch name", out)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.work.exists())

    def test_missing_tool_is_refused_before_any_command(self):
        rc, out = self.run_script(stubs=("gh", "git"))
        self.assertEqual(rc, 2, out)
        self.assertIn("Refused: python is not on PATH.", out)
        self.assertEqual(self.calls(), [])
        rc, out = self.run_script(stubs=("git", "python"))
        self.assertEqual(rc, 2, out)
        self.assertIn("Refused: gh is not on PATH.", out)
        self.assertEqual(self.calls(), [])


class TaskAndGuideTests(unittest.TestCase):
    def test_task_runs_the_script_as_the_default_build_task(self):
        data = json.loads(TASKS.read_text(encoding="utf-8"))
        tasks = [t for t in data["tasks"] if t["label"] == "Installer: build test kit"]
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task["group"], {"kind": "build", "isDefault": True})
        self.assertEqual(task["type"], "process")
        self.assertEqual(task["command"], "powershell.exe")
        args = task["args"]
        self.assertEqual(args[args.index("-File") + 1], "${workspaceFolder}\\tools\\build-windows.ps1")
        self.assertEqual(args[args.index("-Branch") + 1], "${input:installerBranch}")
        inputs = {i["id"]: i for i in data["inputs"]}
        self.assertEqual(inputs["installerBranch"]["default"], "develop")
        self.assertTrue(SCRIPT.is_file())
        self.assertTrue(SCRIPT.read_bytes().isascii())

    def test_guide_names_the_task_and_matches_the_script(self):
        guide = GUIDE.read_text(encoding="utf-8")
        self.assertIn("Installer: build test kit", guide)
        self.assertIn("build-windows.ps1", guide)
        self.assertIn("No build task to run found", guide)
        self.assertIn("{ code -n $r } else", guide)
        self.assertIn(f"-Value '{PAYLOAD}'", guide)
        self.assertIn(f"$PayloadText = '{PAYLOAD}'", SCRIPT.read_text(encoding="ascii"))


if __name__ == "__main__":
    unittest.main()
