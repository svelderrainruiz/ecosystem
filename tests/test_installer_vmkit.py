"""KIT-1 (#197): byte-identical, generator-only VM kits."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from installer.guest import vmkit
from tests.test_installer_build import make_zip, pins_for


ROOT = Path(__file__).resolve().parent.parent
FILES = ("installer.exe", "VM-TEST.md", "vm-state.ps1")


class VmKitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        (self.repo / "installer" / "guest").mkdir(parents=True)
        (self.repo / "installer" / "VM-TEST.md").write_bytes(b"# VM test\r\ncheck\n")
        (self.repo / "installer" / "guest" / "vm-state.ps1").write_bytes(b"report\r\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Kit Test", "-c", "user.email=kit@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.out = self.base / self.head[:12]
        self.payload = self.base / "payload.txt"
        self.payload.write_bytes(b"stand-in\n")
        self.builder = Mock(side_effect=lambda repo, out, payload: out.write_bytes(b"MZfake\n"))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout

    def build(self):
        return vmkit.make_kit(self.out, self.payload, self.repo, builder=self.builder)

    def sums(self):
        return "".join(f"{hashlib.sha256((self.out / name).read_bytes()).hexdigest()}  {name}\n"
                       for name in FILES).encode("ascii")

    def resign(self):
        (self.out / "SHA256SUMS").write_bytes(self.sums())

    def test_throwaway_commit_build_matches_recipe_and_verifies(self):
        self.build()
        self.builder.assert_called_once_with(self.repo, self.out / "installer.exe", self.payload)
        self.assertEqual((self.out / "VM-TEST.md").read_bytes(),
                         b"# VM test\r\ncheck\n" + f"built from: {self.head}\n".encode("ascii"))
        self.assertEqual((self.out / "vm-state.ps1").read_bytes(), b"report\r\n")
        self.assertEqual((self.out / "SHA256SUMS").read_bytes(), self.sums())
        self.assertEqual({p.name for p in self.out.iterdir()}, {*FILES, "SHA256SUMS"})
        vmkit.verify(self.out)

    def test_changed_byte_is_refused(self):
        self.build()
        (self.out / "installer.exe").write_bytes(b"NZfake\n")
        with self.assertRaises(vmkit.KitError):
            vmkit.verify(self.out)

    def test_extra_file_is_refused(self):
        self.build()
        (self.out / "extra").touch()
        with self.assertRaises(vmkit.KitError):
            vmkit.verify(self.out)

    def test_wrong_built_from_is_refused_even_with_matching_hashes(self):
        self.build()
        wrong = ("0" if self.head[0] != "0" else "1") + self.head[1:]
        (self.out / "VM-TEST.md").write_text(f"built from: {wrong}\n", encoding="ascii")
        self.resign()
        with self.assertRaises(vmkit.KitError):
            vmkit.verify(self.out)

    def test_dirty_checkout_is_refused(self):
        for name in ("untracked", "installer/VM-TEST.md"):
            with self.subTest(name=name):
                path = self.repo / name
                original = path.read_bytes() if path.exists() else None
                path.write_bytes(b"dirty\n")
                with self.assertRaises(vmkit.KitError):
                    self.build()
                self.builder.assert_not_called()
                self.assertFalse(self.out.exists())
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)
        (self.repo / "staged").touch()
        self.git("add", "staged")
        with self.assertRaises(vmkit.KitError):
            self.build()

    def test_hidden_untracked_files_are_refused_by_cli_without_output(self):
        self.git("config", "status.showUntrackedFiles", "no")
        (self.repo / "installer" / "untracked").write_bytes(b"untracked\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(vmkit.main(["build", "--out", str(self.out),
                                         "--payload", str(self.payload), "--repo", str(self.repo)]), 2)
        self.assertEqual(error.getvalue(), "KitError: checkout is dirty\n")
        self.assertFalse(self.out.exists())

    def test_nonempty_output_is_refused_without_changes(self):
        self.out.mkdir()
        sentinel = self.out / "keep"
        sentinel.write_bytes(b"keep")
        with self.assertRaises(vmkit.KitError):
            self.build()
        self.builder.assert_not_called()
        self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_wrong_folder_name_checks_all_twelve_digits(self):
        digit = "0" if self.head[11] != "0" else "1"
        self.out = self.base / (self.head[:11] + digit)
        with self.assertRaises(vmkit.KitError):
            self.build()
        self.builder.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_existing_empty_output_is_allowed(self):
        self.out.mkdir()
        self.build()
        vmkit.verify(self.out)

    def test_missing_files_are_refused(self):
        self.build()
        for name in (*FILES, "SHA256SUMS"):
            with self.subTest(name=name):
                path = self.out / name
                data = path.read_bytes()
                path.unlink()
                with self.assertRaises(vmkit.KitError):
                    vmkit.verify(self.out)
                path.write_bytes(data)

    def test_manifest_must_list_exactly_the_three_files(self):
        self.build()
        lines = self.sums().splitlines(keepends=True)
        for content in (b"".join(lines[:2]), self.sums() + lines[0],
                        self.sums().replace(b"installer.exe", b"../installer.exe"),
                        self.sums().replace(b"  ", b" ")):
            with self.subTest(content=content):
                (self.out / "SHA256SUMS").write_bytes(content)
                with self.assertRaises(vmkit.KitError):
                    vmkit.verify(self.out)

    def test_provenance_requires_last_line_and_forty_hex_digits(self):
        self.build()
        for content in ("", f"built from: {self.head[:12]}\n",
                        f"built from: {self.head[:12]}{'g' * 28}\n",
                        f"built from: {self.head}\nnot last\n"):
            with self.subTest(content=content):
                (self.out / "VM-TEST.md").write_text(content, encoding="ascii")
                self.resign()
                with self.assertRaises(vmkit.KitError):
                    vmkit.verify(self.out)

    def test_verify_checks_folder_name(self):
        self.build()
        wrong = self.base / (self.head[:11] + ("0" if self.head[11] != "0" else "1"))
        self.out.rename(wrong)
        with self.assertRaises(vmkit.KitError):
            vmkit.verify(wrong)

    def test_symlink_member_is_refused(self):
        self.build()
        path = self.out / "installer.exe"
        target = self.base / "external.exe"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaises(vmkit.KitError):
            vmkit.verify(self.out)

    def test_default_builder_invokes_test_build_in_selected_repo(self):
        with patch.object(vmkit.subprocess, "run", return_value=Mock(returncode=0)) as run:
            vmkit.build_installer(self.repo, self.out / "installer.exe", self.payload)
        args, kwargs = run.call_args
        self.assertEqual(args[0][1:], ["-m", "installer.build", "build", ".",
                         str(self.out / "installer.exe"), "--runner-payload",
                         str(self.payload), "--test-build"])
        self.assertEqual(kwargs["cwd"], self.repo)
        self.assertEqual(kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertFalse(Path(kwargs["env"]["XDG_CACHE_HOME"]).exists())

    def prepare_cache_build(self):
        for source, target in (("build.py", "compiler.py"), ("trust.py", "trust.py"),
                               ("guest/vmkit.py", "guest/vmkit.py")):
            shutil.copyfile(ROOT / "installer" / source, self.repo / "installer" / target)
        (self.repo / "installer" / "nsis").mkdir()
        (self.repo / "installer" / "nsis" / "main.nsi").write_text("stub", encoding="ascii")
        self.archive = self.base / "verified.zip"
        make_zip(self.archive, b"MZverified\n")
        (self.repo / "installer" / "pins.json").write_text(
            json.dumps(pins_for(self.archive)), encoding="ascii")
        # Exercise the real builder CLI, replacing only download and tool execution.
        (self.repo / "installer" / "build.py").write_text(
            "import os, shutil\n"
            "from pathlib import Path\n"
            "from installer import compiler\n"
            "def download(url, dest):\n"
            "    tree = Path(dest).parent / 'nsis-3.10' / 'Bin'\n"
            "    tree.mkdir(parents=True, exist_ok=True)\n"
            "    (tree / 'makensis').write_bytes(b'tampered compiler')\n"
            "    (tree / 'stale').touch()\n"
            "    shutil.copyfile(os.environ['KIT_TEST_ZIP'], dest)\n"
            "def run(cmd):\n"
            "    out = next((a.split('=', 1)[1] for a in cmd if a.startswith('-DOUTFILE=')), None)\n"
            "    if out is None:\n"
            "        return 0, 'tool version 1'\n"
            "    exe = Path(cmd[0])\n"
            "    if (exe.parent / 'stale').exists():\n"
            "        return 1, 'stale extracted tree reused'\n"
            "    Path(out).write_bytes(exe.read_bytes())\n"
            "    return 0, ''\n"
            "raise SystemExit(compiler.main(download=download, run=run, which=lambda n: n, euid=1000))\n",
            encoding="ascii")
        self.git("add", ".")
        self.git("-c", "user.name=Kit Test", "-c", "user.email=kit@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "cache fixture")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.out = self.base / self.head[:12]
        home, scratch = self.base / "home", self.base / "temp"
        home.mkdir()
        scratch.mkdir()
        self.env = dict(os.environ, HOME=str(home), XDG_CACHE_HOME="",
                        TMPDIR=str(scratch), TEMP=str(scratch), TMP=str(scratch),
                        PYTHONDONTWRITEBYTECODE="1", KIT_TEST_ZIP=str(self.archive))

    def outside_kit_listing(self):
        return sorted(str(p.relative_to(self.base)) for p in self.base.rglob("*")
                      if p != self.out and self.out not in p.parents)

    def cache_build_cli(self):
        return subprocess.run(
            [sys.executable, "-B", "-m", "installer.guest.vmkit", "build",
             "--out", str(self.out), "--payload", str(self.payload)],
            cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=120)

    def test_cli_cache_is_isolated_verified_and_removed(self):
        self.prepare_cache_build()
        for use_xdg in (False, True):
            with self.subTest(use_xdg=use_xdg):
                cache_root = self.base / ("xdg-cache" if use_xdg else "home/.cache")
                self.env["XDG_CACHE_HOME"] = str(cache_root) if use_xdg else ""
                cache = cache_root / "ecosystem-installer"
                exe = cache / "nsis-3.10" / "Bin" / "makensis"
                exe.parent.mkdir(parents=True)
                exe.write_bytes(b"tampered user compiler")
                archive = cache / "nsis-3.10.zip"
                archive.write_bytes(b"tampered user zip")
                before = self.outside_kit_listing()
                result = self.cache_build_cli()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                vmkit.verify(self.out)
                self.assertEqual((self.out / "installer.exe").read_bytes(), b"MZverified\n")
                self.assertEqual(self.outside_kit_listing(), before)
                self.assertEqual(exe.read_bytes(), b"tampered user compiler")
                self.assertEqual(archive.read_bytes(), b"tampered user zip")
                shutil.rmtree(self.out)

    def test_cli_bad_zip_is_refused_and_temp_cache_removed(self):
        self.prepare_cache_build()
        make_zip(self.archive, b"MZtampered\n")
        before = self.outside_kit_listing()
        result = self.cache_build_cli()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("HashMismatch: REFUSED NSIS zip", result.stderr)
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertFalse((self.out / "installer.exe").exists())
        self.assertEqual(self.outside_kit_listing(), before)

    def test_builder_failure_is_reported_on_one_line(self):
        result = Mock(returncode=2, stdout="build\nfailed", stderr="reason\nhere\n")
        with patch.object(vmkit.subprocess, "run", return_value=result):
            with self.assertRaises(vmkit.KitError) as raised:
                vmkit.build_installer(self.repo, self.out / "installer.exe", self.payload)
        self.assertNotIn("\n", str(raised.exception))

    def test_cli_build_and_verify(self):
        with patch.object(vmkit, "make_kit") as build, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(vmkit.main(["build", "--out", str(self.out),
                                        "--payload", str(self.payload), "--repo", str(self.repo)]), 0)
            build.assert_called_once_with(self.out, self.payload, self.repo)
        with patch.object(vmkit, "make_kit") as build, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(vmkit.main(["build", "--out", str(self.out),
                                        "--payload", str(self.payload)]), 0)
            build.assert_called_once_with(self.out, self.payload, Path("."))
        self.build()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(vmkit.main(["verify", str(self.out)]), 0)
        self.assertIn("OK", output.getvalue())
        (self.out / "extra").touch()
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertNotEqual(vmkit.main(["verify", str(self.out)]), 0)
        self.assertEqual(len(error.getvalue().splitlines()), 1)
        self.assertNotIn("Traceback", error.getvalue())

    def test_missing_input_has_one_line_cli_error(self):
        with patch.object(vmkit, "make_kit", side_effect=FileNotFoundError("missing\ninput")):
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                self.assertNotEqual(vmkit.main(["build", "--out", str(self.out),
                                               "--payload", str(self.payload)]), 0)
        self.assertEqual(len(error.getvalue().splitlines()), 1)

    @unittest.skipUnless(shutil.which("makensis"), "makensis not installed")
    def test_one_real_offline_installer_build(self):
        from installer import build

        def real_builder(repo, out, payload):
            build.build(ROOT, out, build.load_pins(), shutil.which("makensis"),
                        self.base / "compile", payload=payload, test_build=True)

        vmkit.make_kit(self.out, self.payload, self.repo, builder=real_builder)
        self.assertTrue((self.out / "installer.exe").read_bytes().startswith(b"MZ"))
        vmkit.verify(self.out)
