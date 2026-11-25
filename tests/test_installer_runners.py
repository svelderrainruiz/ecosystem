"""SL-5 runner modes (ARCH-7): INST-REQ-034, 035, 036, 066, 091, 092, 093, 094, 099, 100. Fakes only, no network."""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer import footprint, image, runners
from installer.schema import ImageNotPinned, LicenceNotAccepted

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "glrt-SECRET-TOKEN-VALUE-123"
BOTH = {"ni_licence_held": True, "engine_licence_accepted": True}


class FakeForge:
    """Records every contact; the token is kept apart so tests can prove where it did not go."""

    def __init__(self):
        self.contacts = []

    def register(self, address, token):
        self.contacts.append(address)
        return {"runner_id": 7}


class FakeSystem:
    def __init__(self, logon_right=True, admin=True):
        self.logon_right = logon_right
        self.admin = admin
        self.calls = []
        self.acl_calls = []

    def prepare_folder(self):
        self.calls.append(("prepare_folder",))

    def restrict_acl(self, path, accounts):
        self.acl_calls.append((path, tuple(accounts), Path(path).read_text()))

    def is_elevated(self):
        return self.admin

    def has_logon_right(self, account):
        return self.logon_right

    def install_service(self, name, account, folder, files=()):
        self.calls.append(("install", name, account))


class FakeEngine:
    def __init__(self):
        self.pulls = []

    def pull(self, argv):
        self.pulls.append(argv)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.state = self.dir / "state"
        self.prog = self.dir / "progdata"


class TestForgeRegistration(Base):
    def test_register_only_at_typed_forge_address(self):
        """INST-REQ-066, 034: no default address; only the typed one is contacted."""
        forge = FakeForge()
        with self.assertRaises(runners.ForgeAddressMissing):
            runners.register_github(self.state, self.prog, "", TOKEN, forge)
        with self.assertRaises(runners.ForgeAddressMissing):
            runners.register_github(self.state, self.prog, "http://plain.example", TOKEN, forge)
        self.assertIsNone(runners.recorded_forge(self.state, self.prog))
        self.assertEqual(forge.contacts, [])
        runners.register_github(self.state, self.prog, "https://git.example.org/me/repo", TOKEN, forge)
        self.assertEqual(forge.contacts, ["https://git.example.org/me/repo"])
        self.assertEqual(runners.read_mode(self.state), "github")

    def test_second_forge_on_a_pc_is_refused(self):
        """INST-REQ-034, 036: GitHub then GitLab and the reverse; nothing changes."""
        forge, system = FakeForge(), FakeSystem()
        runners.register_github(self.state, self.prog, "https://git.example.org/a", TOKEN, forge)
        with self.assertRaises(runners.SecondForgeRefused):
            runners.install_gitlab(self.state, self.dir / "prog", "https://lab.example.org", TOKEN, system)
        self.assertEqual(system.calls, [])
        self.assertEqual(runners.read_mode(self.state), "github")
        other = self.dir / "other"
        runners.install_gitlab(other, self.dir / "prog", "https://lab.example.org", TOKEN, system)
        with self.assertRaises(runners.SecondForgeRefused):
            runners.register_github(other, self.dir / "prog", "https://git.example.org/a", TOKEN, forge)
        self.assertEqual(forge.contacts, ["https://git.example.org/a"])
        self.assertEqual(runners.read_mode(other), "gitlab")

    def test_same_forge_twice_and_local_are_not_refused(self):
        runners.set_mode(self.state, "local")
        runners.set_mode(self.state, "github")
        runners.set_mode(self.state, "github")
        with self.assertRaises(runners.BadMode):
            runners.set_mode(self.state, "svn")

    def test_forge_never_cleared_by_local_mode(self):
        """Blocker 1: github -> local -> gitlab is refused."""
        runners.set_mode(self.state, "github")
        runners.set_mode(self.state, "local")
        with self.assertRaises(runners.SecondForgeRefused):
            runners.set_mode(self.state, "gitlab")
        with self.assertRaises(runners.SecondForgeRefused):
            runners.install_gitlab(self.state, self.prog, "https://lab.example.org", TOKEN, FakeSystem())
        runners.set_mode(self.state, "github")

    def test_lost_state_dir_does_not_free_the_pc(self):
        """Blocker 2: the marker is also kept beside the program data."""
        runners.register_github(self.state, self.prog, "https://git.example.org/a", TOKEN, FakeForge())
        shutil.rmtree(self.state)
        with self.assertRaises(runners.SecondForgeRefused):
            runners.install_gitlab(self.state, self.prog, "https://lab.example.org", TOKEN, FakeSystem())

    def test_gitlab_config_alone_counts_as_gitlab(self):
        self.prog.mkdir()
        (self.prog / runners.GITLAB_CONFIG).write_text("x")
        with self.assertRaises(runners.SecondForgeRefused):
            runners.register_github(self.state, self.prog, "https://git.example.org/a", TOKEN, FakeForge())

    def test_corrupt_state_is_typed_refusal(self):
        for name, body in ((runners.MODE_FILE, "{not json"), (runners.MODE_FILE, "[]"), (runners.MODE_FILE, '{"mode": "x"}'),
                           (runners.FORGE_FILE, "{}"), (runners.FORGE_FILE, "\x00")):
            shutil.rmtree(self.state, True)
            self.state.mkdir()
            (self.state / name).write_text(body)
            forge = FakeForge()
            with self.assertRaises(runners.StateCorrupt):
                runners.register_github(self.state, self.prog, "https://git.example.org/a", TOKEN, forge)
            self.assertEqual(forge.contacts, [])
        shutil.rmtree(self.state)
        self.state.mkdir()
        (self.state / runners.FORGE_FILE).write_text('{"forge": "github"}')
        self.prog.mkdir()
        (self.prog / runners.FORGE_FILE).write_text('{"forge": "gitlab"}')
        with self.assertRaises(runners.StateCorrupt):
            runners.recorded_forge(self.state, self.prog)

    def test_marker_written_before_registration_and_survives_failure(self):
        """Blocker 2: a failing registration still counts."""
        class Failing(FakeForge):
            def register(self, address, token):
                assert runners.recorded_forge(self_.state, self_.prog) == "github"
                raise OSError("down")
        self_ = self
        with self.assertRaises(OSError):
            runners.register_github(self.state, self.prog, "https://git.example.org/a", TOKEN, Failing())
        with self.assertRaises(runners.SecondForgeRefused):
            runners.install_gitlab(self.state, self.prog, "https://lab.example.org", TOKEN, FakeSystem())

    def test_address_strictly_parsed(self):
        """Blocker 3."""
        for bad in ("https://user:pw@git.example.org/", "https://@git.example.org", "https:///x", "https://", "HTTP://git.example.org",
                    "https://git.example.org/a b", "https://git.example.org/\n", "https://git.example.org/\"x", "https://git.example.org/'x",
                    "https://git.example.org/\\x", "https://git.example.org:notaport/", "https://git.example.org/\x00", None, 5, "https://git.example.org/`x"):
            with self.assertRaises(runners.ForgeAddressMissing, msg=repr(bad)):
                runners.register_github(self.state, self.prog, bad, TOKEN, FakeForge())
        forge = FakeForge()
        runners.register_github(self.state, self.prog, "HTTPS://Git.Example.org:8443/a", TOKEN, forge)
        self.assertEqual(len(forge.contacts), 1)

    def test_pinned_host_enforced(self):
        with self.assertRaises(runners.ForgeAddressMissing):
            runners.register_github(self.state, self.prog, "https://evil.example.org/a", TOKEN, FakeForge(), expected_host="git.example.org")
        runners.register_github(self.state, self.prog, "https://GIT.example.org/a", TOKEN, FakeForge(), expected_host="git.example.org")

    def test_mode_file_alone_counts_as_recorded_forge(self):
        self.state.mkdir()
        (self.state / runners.MODE_FILE).write_text('{"mode": "github"}')
        with self.assertRaises(runners.SecondForgeRefused):
            runners.set_mode(self.state, "gitlab")

    def test_local_mode_refuses_damaged_state(self):
        self.state.mkdir()
        (self.state / runners.FORGE_FILE).write_text("{bad")
        with self.assertRaises(runners.StateCorrupt):
            runners.set_mode(self.state, "local")

    def test_set_mode_itself_refuses_second_forge(self):
        runners.set_mode(self.state, "gitlab")
        with self.assertRaises(runners.SecondForgeRefused):
            runners.set_mode(self.state, "github")
        self.assertEqual(runners.read_mode(self.state), "gitlab")

    def test_github_token_never_stored(self):
        runners.register_github(self.state, self.prog, "https://git.example.org/a", TOKEN, FakeForge())
        for p in self.state.rglob("*"):
            if p.is_file():
                self.assertNotIn(TOKEN, p.read_text())


class TestLocalOnly(Base):
    def test_local_only_runs_check_build_sbom_tests_without_service(self):
        """INST-REQ-035: four steps by command, no service, no forge contact."""
        ran = []
        sys_ = FakeSystem()
        forge = FakeForge()
        out = runners.run_local(self.dir, lambda argv: ran.append(argv) or 0)
        self.assertEqual([s["step"] for s in out], ["check", "build", "sbom", "tests"])
        self.assertEqual(len(ran), 3)  # the SBOM is written in process by the stdlib generator
        self.assertEqual(sys_.calls, [])
        self.assertEqual(forge.contacts, [])
        self.assertTrue((self.dir / runners.SBOM_NAME).exists())

    def test_local_only_stops_at_first_failing_step(self):
        with self.assertRaises(runners.LocalStepFailed) as cm:
            runners.run_local(self.dir, lambda argv: 1)
        self.assertIn("check", str(cm.exception))

    def test_sbom_skips_config_and_symlinks(self):
        (self.dir / "a.txt").write_text("x")
        (self.dir / runners.GITLAB_CONFIG).write_text(TOKEN)
        os.symlink("/etc/hostname", self.dir / "link")
        text = runners.write_sbom(self.dir).read_text()
        self.assertNotIn(runners.GITLAB_CONFIG, text)
        self.assertNotIn("link", text)
        self.assertNotIn(TOKEN, text)

    def test_sbom_lists_files_with_digest(self):
        (self.dir / "a.txt").write_text("x")
        doc = json.loads(runners.write_sbom(self.dir).read_text())
        self.assertEqual(doc["bomFormat"], "CycloneDX")
        self.assertEqual(doc["components"][0]["name"], "a.txt")
        self.assertEqual(len(doc["components"][0]["hashes"][0]["content"]), 64)


class TestGitlab(Base):
    def test_gitlab_install_step_only_in_elevated_phase(self):
        """INST-REQ-091: not elevated means no install step and a typed error."""
        system = FakeSystem(admin=False)
        with self.assertRaises(runners.NotElevated):
            runners.install_gitlab(self.state, self.dir / "prog", "https://lab.example.org", TOKEN, system)
        self.assertEqual(system.calls, [])
        self.assertIsNone(runners.read_mode(self.state))

    def test_service_under_virtual_account(self):
        """INST-REQ-092."""
        system = FakeSystem()
        runners.install_gitlab(self.state, self.dir / "prog", "https://lab.example.org", TOKEN, system)
        fp = footprint.load_footprint()
        self.assertEqual(system.calls, [("prepare_folder",), ("install", fp["service"]["name"], fp["service"]["account"])])
        self.assertTrue(fp["service"]["account"].startswith("NT SERVICE\\"))

    def test_gitlab_token_only_in_runner_config(self):
        """INST-REQ-094: the token is in config.toml (0600), nowhere else, not in the error text or the state file."""
        prog = self.dir / "prog"
        runners.install_gitlab(self.state, prog, "https://lab.example.org", TOKEN, FakeSystem())
        cfg = prog / runners.GITLAB_CONFIG
        self.assertIn(TOKEN, cfg.read_text())
        self.assertEqual(stat.S_IMODE(os.stat(cfg).st_mode), 0o600)
        for p in list(self.state.rglob("*")) + [prog / "x"]:
            if p.is_file():
                self.assertNotIn(TOKEN, p.read_text())
        self.assertEqual(len([p for p in self.dir.rglob("*") if p.is_file() and TOKEN in p.read_text()]), 1)
        try:
            runners.install_gitlab(self.dir / "s2", self.dir / "p2", "https://lab.example.org", TOKEN, FakeSystem(logon_right=False))
        except runners.LogonRightMissing as e:
            self.assertNotIn(TOKEN, str(e))
        self.assertFalse((self.dir / "p2" / runners.GITLAB_CONFIG).exists())

    def test_missing_logon_right_is_typed_error(self):
        """INST-REQ-093."""
        system = FakeSystem(logon_right=False)
        with self.assertRaises(runners.LogonRightMissing) as cm:
            runners.install_gitlab(self.state, self.dir / "prog", "https://lab.example.org", TOKEN, system)
        self.assertIn("logon", str(cm.exception).lower())
        self.assertEqual(system.calls, [])
        self.assertIsNone(runners.read_mode(self.state))

    def test_failed_service_install_leaves_no_token_file(self):
        class Boom(FakeSystem):
            def install_service(self, *a, **k):
                raise OSError("denied")
        prog = self.dir / "prog"
        with self.assertRaises(OSError):
            runners.install_gitlab(self.state, prog, "https://lab.example.org", TOKEN, Boom())
        self.assertFalse((prog / runners.GITLAB_CONFIG).exists())
        self.assertIsNone(runners.read_mode(self.state))

    def test_toml_injection_refused(self):
        """Blocker 4: quote, backslash, newline in address or token never reach config.toml."""
        for addr, tok in (('https://lab.example.org/"\nx = 1', TOKEN), ("https://lab.example.org", 'a"\nrunner = 1'),
                          ("https://lab.example.org", "a\\b"), ("https://lab.example.org", "a b"), ("https://lab.example.org", ""),
                          ("https://lab.example.org", "a\rb"), ("https://lab.example.org", "a'b")):
            with self.assertRaises((runners.ForgeAddressMissing, runners.BadSecret)):
                runners.install_gitlab(self.state, self.prog, addr, tok, FakeSystem())
            self.assertFalse((self.prog / runners.GITLAB_CONFIG).exists())
        with self.assertRaises(runners.BadSecret):
            runners.register_github(self.state, self.prog, "https://git.example.org/a", "bad token", FakeForge())

    def test_config_created_0600_excl_nofollow_acl_before_token(self):
        """Blocker 5: mode and flags AT creation; ACL applied while the file is still empty; stale file or link replaced."""
        seen = []
        real = os.open

        def spy(path, flags, mode=0o777, **kw):
            if str(path).endswith(runners.GITLAB_CONFIG):
                seen.append((flags, mode))
            return real(path, flags, mode, **kw)
        self.prog.mkdir()
        victim = self.dir / "victim"
        victim.write_text("keep")
        os.symlink(victim, self.prog / runners.GITLAB_CONFIG)
        system = FakeSystem()
        orig, os.open = os.open, spy
        try:
            runners.install_gitlab(self.state, self.prog, "https://lab.example.org", TOKEN, system)
        finally:
            os.open = orig
        flags, mode = seen[0]
        self.assertEqual(mode, 0o600)
        self.assertTrue(flags & os.O_EXCL and flags & os.O_CREAT)
        if hasattr(os, "O_NOFOLLOW"):
            self.assertTrue(flags & os.O_NOFOLLOW)
        self.assertEqual(victim.read_text(), "keep")
        path, accounts, content_at_acl = system.acl_calls[0]
        self.assertEqual(content_at_acl, "")
        self.assertNotIn("NT SERVICE\\EcosystemRunner", accounts)  # the SID resolves only once the service exists: it is granted in install_service
        self.assertIn("NT AUTHORITY\\SYSTEM", accounts)
        self.assertIn("BUILTIN\\Administrators", accounts)

    def test_config_removed_on_write_failure_and_unlink_error_does_not_mask(self):
        class AclBoom(FakeSystem):
            def restrict_acl(self, path, accounts):
                raise OSError("acl")
        with self.assertRaises(OSError) as cm:
            runners.install_gitlab(self.state, self.prog, "https://lab.example.org", TOKEN, AclBoom())
        self.assertEqual(str(cm.exception), "acl")
        self.assertFalse((self.prog / runners.GITLAB_CONFIG).exists())
        real = Path.unlink

        def bad_unlink(self_, *a, **k):
            raise PermissionError("unlink")

        class Boom(FakeSystem):
            def install_service(self, *a, **k):
                raise OSError("install")
        Path.unlink = bad_unlink
        try:
            with self.assertRaises(OSError) as cm:
                runners.install_gitlab(self.dir / "s3", self.dir / "p3", "https://lab.example.org", TOKEN, Boom())
        finally:
            Path.unlink = real
        self.assertEqual(str(cm.exception), "install")

    def test_gitlab_needs_typed_address(self):
        with self.assertRaises(runners.ForgeAddressMissing):
            runners.install_gitlab(self.state, self.dir / "prog", "", TOKEN, FakeSystem())


class TestImage(Base):
    schema = {"images": {"list": [{"variant": "linux", "year": "2025", "digest": "sha256:" + "a" * 64, "repository": "registry.example/ni/labview"},
                                  {"variant": "linux", "year": "2024", "digest": None}]}}

    def test_image_pulled_by_digest_after_both_licences(self):
        """INST-REQ-099: no pull before both boxes; then one pull by the pinned digest."""
        eng = FakeEngine()
        for ticks in ({}, {"ni_licence_held": True}, {"engine_licence_accepted": True}):
            with self.assertRaises(LicenceNotAccepted):
                image.pull_image(self.schema, "linux", "2025", ticks, "registry.example/ni/labview", eng)
        self.assertEqual(eng.pulls, [])
        ref = image.pull_image(self.schema, "linux", "2025", BOTH, "registry.example/ni/labview", eng)
        self.assertEqual(eng.pulls, [["pull", "--", ref]])
        self.assertEqual(ref, "registry.example/ni/labview@sha256:" + "a" * 64)

    def test_unpinned_image_is_not_pulled(self):
        eng = FakeEngine()
        with self.assertRaises(ImageNotPinned):
            image.pull_image(self.schema, "linux", "2024", BOTH, "registry.example/ni/labview", eng)
        self.assertEqual(eng.pulls, [])

    def test_digest_fullmatch_and_repository_validated(self):
        for d in ("sha256:" + "a" * 64 + "\n", "sha256:" + "A" * 64, "sha256:abc"):
            with self.assertRaises(ImageNotPinned):
                image.reference("registry.example/ni/labview", d)
        for r in ("-rf", "Reg/x", "reg/x\n", "", "reg x", "reg/x;y", "reg@sha256:x"):
            with self.assertRaises(ImageNotPinned):
                image.reference(r, "sha256:" + "a" * 64)

    def test_tag_reference_refused(self):
        with self.assertRaises(ImageNotPinned):
            image.reference("registry.example/ni/labview", "latest")

    def test_image_never_shipped_or_mirrored(self):
        """INST-REQ-100: no archive or layer file under installer/ and no push or save in the planner."""
        bad = [p.name for p in (ROOT / "installer").rglob("*") if p.suffix in (".tar", ".tgz", ".wim", ".vhd", ".vhdx", ".iso", ".exe")]
        self.assertEqual(bad, [])
        src = (ROOT / "installer" / "image.py").read_text()
        for word in ("push", "save", "export", "mirror"):
            self.assertNotIn("." + word + "(", src)


class TestNsisAndFootprint(unittest.TestCase):
    def test_footprint_scan_green(self):
        self.assertEqual(footprint.check_source(footprint.collect_sources()), [])

    def test_runner_files_exist_and_mode_switch_in_main(self):
        for n in ("runner-github.nsh", "runner-local.nsh", "runner-gitlab.nsh"):
            self.assertTrue((ROOT / "installer" / "nsis" / n).exists())
        main = (ROOT / "installer" / "nsis" / "main.nsi").read_text()
        for n in ("runner-github.nsh", "runner-local.nsh", "runner-gitlab.nsh"):
            self.assertIn('!include "%s"' % n, main)

    def test_gitlab_nsis_install_guarded_by_elevation(self):
        text = (ROOT / "installer" / "nsis" / "runner-gitlab.nsh").read_text()
        self.assertIn("$elev_isadmin", text)
        self.assertNotIn("Exec", text)
        self.assertIn("${AndIf} $elev_isadmin == 0", text)
        self.assertIn("SetErrorLevel 38", text)

    def test_mode_switch_matches_python_modes(self):
        text = "".join((ROOT / "installer" / "nsis" / n).read_text() for n in ("runner-github.nsh", "runner-local.nsh", "runner-gitlab.nsh"))
        for m in runners.MODES:
            self.assertIn('"%s"' % m, text)

    def test_nsh_has_no_token_variable_output(self):
        for n in ("runner-github.nsh", "runner-local.nsh", "runner-gitlab.nsh"):
            t = (ROOT / "installer" / "nsis" / n).read_text()
            self.assertNotIn("DetailPrint $gitlab_token", t)
            self.assertNotIn("DetailPrint $github_token", t)


@unittest.skipUnless(shutil.which("pwsh"), "pwsh absent")
class TestPwshParse(unittest.TestCase):
    def test_runner_scripts_parse(self):
        scripts = list((ROOT / "installer").glob("runner*.ps1"))
        for s in scripts:
            r = subprocess.run(["pwsh", "-NoProfile", "-Command",
                                "$e=$null;[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e)|Out-Null;if($e){exit 1}" % s],
                               capture_output=True)
            self.assertEqual(r.returncode, 0, s.name)


if __name__ == "__main__":
    unittest.main()
