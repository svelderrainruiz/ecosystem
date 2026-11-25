"""SL-1 tests: installer build script (INST-REQ-005..010, 013, 068..071). Fakes only: no network, no real makensis."""
import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path

from installer import build

ROOT = Path(__file__).resolve().parent.parent
PINS = json.loads((ROOT / "installer" / "pins.json").read_text())


def make_zip(path, payload=b"fake"):
    # A fixed timestamp keeps the digest independent of the wall clock (#200).
    info = zipfile.ZipInfo("nsis-3.10/Bin/makensis", date_time=(1980, 1, 1, 0, 0, 0))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(info, payload)


def pins_for(zip_bytes_path):
    p = copy.deepcopy(PINS)
    p["nsis"]["sha256"] = build.sha256_file(zip_bytes_path)
    return p


def fake_download_factory(payload=b"fake"):
    def dl(url, dest):
        make_zip(dest, payload)
    return dl


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        ref = self.tmp / "ref.zip"
        make_zip(ref)
        self.pins = pins_for(ref)


class FakeRun:
    def __init__(self, out_content=b"INSTALLER-A", rc=0):
        self.calls, self.out_content, self.rc = [], out_content, rc

    def __call__(self, cmd):
        self.calls.append(cmd)
        if any(a.startswith("-DOUTFILE=") for a in cmd):
            out = next(a for a in cmd if a.startswith("-DOUTFILE=")).split("=", 1)[1]
            if self.rc == 0:
                Path(out).write_bytes(self.out_content)
            return self.rc, "boom"
        return 0, f"{os.path.basename(cmd[0])} version 1.0\n"


class TestZip(Base):
    def test_genuine_zip_is_used(self):
        """INST-REQ-007: a zip equal to the pin is unpacked."""
        exe = build.fetch_nsis(self.pins, self.tmp / "c", fake_download_factory())
        self.assertTrue(os.path.isfile(exe))

    def test_second_fetch_replaces_tampered_zip_and_extracted_tree(self):
        cache = self.tmp / "c"
        exe = Path(build.fetch_nsis(self.pins, cache, fake_download_factory()))
        exe.write_bytes(b"tampered compiler")
        archive = cache / "nsis-3.10.zip"
        archive.write_bytes(b"tampered zip")
        stale = exe.parent / "stale"
        stale.touch()
        download = unittest.mock.Mock(side_effect=fake_download_factory())
        rebuilt = build.fetch_nsis(self.pins, cache, download)
        download.assert_called_once_with(self.pins["nsis"]["url"], str(archive))
        self.assertEqual(build.sha256_file(archive), self.pins["nsis"]["sha256"])
        self.assertEqual(Path(rebuilt).read_bytes(), b"fake")
        self.assertFalse(stale.exists())

    def test_zip_with_wrong_sha256_is_refused(self):
        """INST-REQ-007, 008, 070: a changed zip stops the build and names the mismatch."""
        with self.assertRaises(build.HashMismatch) as cm:
            build.fetch_nsis(self.pins, self.tmp / "c", fake_download_factory(b"tampered"))
        msg = str(cm.exception)
        self.assertIn("REFUSED", msg)
        self.assertIn(self.pins["nsis"]["sha256"], msg)
        self.assertFalse(list((self.tmp / "c").glob("*.zip")))
        self.assertFalse((self.tmp / "c" / "nsis-3.10").exists())

    def test_refusal_is_printed_to_user_without_traceback(self):
        """INST-REQ-070: the CLI tells the user and exits 2."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err), unittest.mock.patch.object(build, "load_pins", return_value=self.pins):
            rc = build.main(["fetch"], download=fake_download_factory(b"x"), env={"HOME": str(self.tmp)}, euid=1000)
        self.assertEqual(rc, 2)
        self.assertIn("HashMismatch: REFUSED", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_fixture_zip_digest_does_not_follow_the_clock(self):
        """#200: the pinned reference zip and the fake download must hash alike across a clock tick."""
        a, b = self.tmp / "a.zip", self.tmp / "b.zip"
        with unittest.mock.patch("time.time", return_value=1_000_000_000.0):
            make_zip(a)
        with unittest.mock.patch("time.time", return_value=1_000_172_800.0):
            make_zip(b)
        self.assertEqual(build.sha256_file(a), build.sha256_file(b))

    def test_zip_path_escape_is_refused(self):
        z = self.tmp / "evil.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("../evil", b"x")
        with self.assertRaises(build.HashMismatch):
            build._safe_extract(z, self.tmp / "d")


class TestPins(Base):
    def test_pins_file_is_the_only_hash_source(self):
        """INST-REQ-007: the real pins file is complete; hashes are valid hex; build.py holds no 64-hex literal."""
        pins = build.load_pins()
        self.assertEqual(pins["nsis"]["version"], "3.10")
        self.assertTrue(pins["nsis"]["url"].startswith("https://"))
        import re
        self.assertIsNone(re.search(r"[0-9a-f]{64}", (ROOT / "installer" / "build.py").read_text()))

    def test_bad_pins_are_typed_errors(self):
        p = self.tmp / "p.json"
        for text in ("{", "{}", json.dumps({"nsis": {"url": "u", "version": "v", "root": "r", "sha256": "zz"},
                                            "compile": {"defines": {}}})):
            p.write_text(text)
            with self.assertRaises(build.PinsError):
                build.load_pins(p)
        with self.assertRaises(build.PinsError):
            build.load_pins(self.tmp / "missing.json")

    def test_http_download_is_refused(self):
        with self.assertRaises(build.PinsError):
            build.default_download("http://example.invalid/x.zip", str(self.tmp / "x"))


class TestTools(unittest.TestCase):
    def which_without(self, *missing):
        return lambda n: None if n in missing else "/usr/bin/" + n

    def test_missing_git_or_engine_names_the_tool(self):
        """INST-REQ-009, 010, 071: stop naming the tool, never install it."""
        run = FakeRun()
        with self.assertRaises(build.MissingTool) as cm:
            build.check_tools(self.which_without("git"), run)
        self.assertIn("Git", str(cm.exception))
        with self.assertRaises(build.MissingTool) as cm:
            build.check_tools(self.which_without("docker", "podman"), run)
        self.assertIn("docker or podman", str(cm.exception))
        for cmd in run.calls:
            self.assertEqual(cmd[1:], ["--version"])
        self.assertIn("never installs", str(cm.exception))

    def test_present_tools_are_reported_with_versions(self):
        """INST-REQ-009."""
        found = build.check_tools(self.which_without("docker"), FakeRun())
        self.assertEqual(set(found), {"git", "podman"})
        self.assertIn("version 1.0", found["git"])

    def test_source_never_installs_anything(self):
        """INST-REQ-071: no installer command in the script."""
        text = (ROOT / "installer" / "build.py").read_text()
        for word in ("apt", "winget", "choco", "sudo", "pip install", "brew"):
            self.assertNotRegex(text, rf"[\"' ]{word}[\"' ]")


class TestCompile(Base):
    def test_compile_inputs_are_fixed(self):
        """INST-REQ-013: fixed defines, pinned script commands, sorted file list, no date macro."""
        src = self.tmp / "src"
        for n in ("installer/nsis/b.nsh", "installer/a.txt", "installer/nsis/main.nsi", "installer/Z.txt"):
            (src / n).parent.mkdir(parents=True, exist_ok=True)
            (src / n).write_text("x")
        (src / ".git").mkdir()
        (src / "installer" / ".git").mkdir()
        (src / "installer" / ".git" / "h").write_text("x")
        self.assertEqual(build.collect_files(src / "installer"),
                         sorted(["Z.txt", "a.txt", "nsis/b.nsh", "nsis/main.nsi"]))
        run = FakeRun()
        out = self.tmp / "out.exe"
        build.build(src, out, self.pins, "/x/makensis", self.tmp / "w", run)
        cmd = run.calls[0]
        for fixed in ("-XSetDateSave off", "-XUnicode true", "-XSetCompressor /SOLID lzma", "-XSetCompressorDictSize 8",
                      "-DINSTALLER_UNICODE=1", "-INPUTCHARSET", "UTF8"):
            self.assertIn(fixed, cmd)
        self.assertEqual((self.tmp / "w" / "filelist.txt").read_text().split(), ["Z.txt", "a.txt", "nsis/b.nsh", "nsis/main.nsi"])
        self.assertFalse(any("__DATE__" in a or "__TIME__" in a for a in cmd))
        self.assertEqual(cmd[-1], str(src / "installer" / "nsis" / "main.nsi"))
        defs = [a for a in cmd if a.startswith("-D")]
        self.assertEqual(defs, sorted(defs[:1]) + defs[1:])

    def test_date_macro_in_pins_is_refused(self):
        p = copy.deepcopy(self.pins)
        p["compile"]["script_commands"].append("!define D ${__DATE__}")
        with self.assertRaises(build.PinsError):
            build.compile_command("m", p, "a.nsi", "o", "f")

    def test_compile_failure_and_missing_script_are_typed(self):
        src = self.tmp / "src"
        with self.assertRaises(build.CompileError):
            build.build(src, self.tmp / "o", self.pins, "m", self.tmp / "w", FakeRun())
        (src / "installer" / "nsis").mkdir(parents=True)
        (src / "installer" / "nsis" / "main.nsi").write_text("x")
        with self.assertRaises(build.CompileError) as cm:
            build.build(src, self.tmp / "o", self.pins, "m", self.tmp / "w", FakeRun(rc=1))
        self.assertIn("exit 1", str(cm.exception))


class TestPublished(Base):
    def _built(self, published_text):
        src = self.tmp / "src"
        (src / "installer" / "nsis").mkdir(parents=True, exist_ok=True)
        (src / "installer" / "nsis" / "main.nsi").write_text("x")
        h = self.tmp / "pub.txt"
        h.write_text(published_text)
        return src, h

    def test_built_hash_is_compared_with_published(self):
        """INST-REQ-006, 068: equal passes, different stops."""
        digest = hashlib.sha256(b"INSTALLER-A").hexdigest()
        src, h = self._built(digest.upper() + "  installer.exe\n")
        out = self.tmp / "o.exe"
        got = build.build(src, out, self.pins, "m", self.tmp / "w", FakeRun(), build.read_published(h))
        self.assertEqual(got, digest)
        with self.assertRaises(build.PublishedMismatch) as cm:
            build.build(src, out, self.pins, "m", self.tmp / "w", FakeRun(b"CHANGED"), build.read_published(h))
        self.assertIn("MISMATCH", str(cm.exception))
        self.assertIn(digest, str(cm.exception))

    def test_published_file_errors_are_typed(self):
        with self.assertRaises(build.PublishedMismatch):
            build.read_published(self.tmp / "none")
        (self.tmp / "e.txt").write_text("no hash here")
        with self.assertRaises(build.PublishedMismatch):
            build.read_published(self.tmp / "e.txt")

    def test_verify_cli_match_and_mismatch(self):
        out = self.tmp / "o.exe"
        out.write_bytes(b"A")
        h = self.tmp / "h"
        h.write_text(hashlib.sha256(b"A").hexdigest())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), unittest.mock.patch.object(build, "load_pins", return_value=self.pins):
            self.assertEqual(build.main(["verify", str(out), str(h)], env={"HOME": str(self.tmp)}, euid=1000), 0)
        self.assertIn("MATCH", buf.getvalue())
        out.write_bytes(b"B")
        with contextlib.redirect_stderr(io.StringIO()), unittest.mock.patch.object(build, "load_pins", return_value=self.pins):
            self.assertEqual(build.main(["verify", str(out), str(h)], env={"HOME": str(self.tmp)}, euid=1000), 2)

    def test_build_end_to_end_against_fakes(self):
        """Definition of done: check, fetch, compile and compare in one run."""
        src, h = self._built(hashlib.sha256(b"INSTALLER-A").hexdigest())
        out = self.tmp / "o.exe"
        run = FakeRun()
        buf = io.StringIO()
        payload = self.tmp / "runner.exe"
        payload.write_bytes(b"stub")
        self.pins["runner_payload"] = {"sha256": build.sha256_file(payload)}
        with contextlib.redirect_stdout(buf), unittest.mock.patch.object(build, "load_pins", return_value=self.pins):
            rc = build.main(["build", str(src), str(out), "--runner-payload", str(payload), "--published", str(h)], download=fake_download_factory(),
                            run=run, which=lambda n: "/usr/bin/" + n, env={"HOME": str(self.tmp)}, euid=1000)
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertIn("MATCH", buf.getvalue())


class TestLocation(unittest.TestCase):
    def test_download_goes_to_the_user_folder(self):
        """INST-REQ-069: per user, no elevation."""
        self.assertEqual(build.download_dir({"HOME": "/home/u"}, 1000), Path("/home/u/.cache/ecosystem-installer"))
        self.assertEqual(build.download_dir({"HOME": "/h", "XDG_CACHE_HOME": "/c"}, 1000), Path("/c/ecosystem-installer"))
        with self.assertRaises(build.ElevationRefused):
            build.download_dir({"HOME": "/root"}, 0)


class TestRepoHygiene(unittest.TestCase):
    def test_repo_holds_no_exe_or_signature(self):
        """INST-REQ-005, 068: no installer binary, signature, zip or disk image tracked or present in the tree."""
        banned = (".exe", ".sig", ".sshsig", ".asc", ".gpg", ".zip", ".vdi", ".vmdk", ".iso")
        try:
            files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
        except (OSError, subprocess.CalledProcessError):
            files = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if ".git" not in p.parts]
        bad = [f for f in files if f.lower().endswith(banned)]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
