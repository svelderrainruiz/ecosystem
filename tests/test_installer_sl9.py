"""SL-9 tests: guest-run bug fixes 1-7 (ecosystem-control#64). Fakes only; makensis (host) is used when present."""
import re
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from tests.zone_database import requires_zone_database

from installer import build, footprint, log

ROOT = Path(__file__).resolve().parent.parent
NSIS = ROOT / "installer" / "nsis"
PINS = build.load_pins()


def exe_only_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("nsis-3.10/makensis.exe", b"MZ")


def pins_for(zip_path):
    import copy
    p = copy.deepcopy(PINS)
    p["nsis"]["sha256"] = build.sha256_file(zip_path)
    return p


class Bug1HostMakensis(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.zip = self.tmp / "ref.zip"
        exe_only_zip(self.zip)
        self.pins = pins_for(self.zip)

    def dl(self, url, dest):
        shutil.copy(self.zip, dest)

    def test_linux_uses_host_makensis_when_pinned_exe_cannot_run(self):
        got = build.fetch_nsis(self.pins, self.tmp / "c", self.dl, which=lambda n: "/usr/bin/makensis", platform="linux")
        self.assertEqual(got, "/usr/bin/makensis")

    def test_pin_check_still_runs_before_the_host_binary_is_used(self):
        bad = dict(self.pins, nsis=dict(self.pins["nsis"], sha256="0" * 64))
        with self.assertRaises(build.HashMismatch):
            build.fetch_nsis(bad, self.tmp / "c", self.dl, which=lambda n: "/usr/bin/makensis", platform="linux")

    def test_linux_without_host_makensis_is_a_typed_error(self):
        with self.assertRaises(build.BuildError) as cm:
            build.fetch_nsis(self.pins, self.tmp / "c", self.dl, which=lambda n: None, platform="linux")
        self.assertIn("makensis", str(cm.exception))

    def test_a_runnable_pinned_binary_wins_over_the_host_one(self):
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr("nsis-3.10/Bin/makensis", b"x")
        pins = pins_for(self.zip)
        got = build.fetch_nsis(pins, self.tmp / "c", self.dl, which=lambda n: "/usr/bin/makensis", platform="linux")
        self.assertTrue(got.endswith("Bin/makensis"))

    def test_windows_keeps_the_pinned_exe(self):
        got = build.fetch_nsis(self.pins, self.tmp / "c", self.dl, which=lambda n: "/x/makensis", platform="win32")
        self.assertTrue(got.endswith("makensis.exe"))


@unittest.skipUnless(shutil.which("makensis"), "makensis absent")
class Bug2Outfile(unittest.TestCase):
    def test_outfile_define_decides_where_the_exe_lands(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(NSIS, Path(d) / "nsis")
            out = Path(d) / "elsewhere" / "x.exe"
            out.parent.mkdir()
            r = subprocess.run(["makensis", "-WX", "-V1", f"-DOUTFILE={out}", str(Path(d) / "nsis" / "main.nsi")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(out.is_file())
            self.assertFalse((Path(d) / "nsis" / "installer.exe").exists())

    def test_build_end_to_end_with_real_makensis(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "src"
            shutil.copytree(ROOT / "installer", src / "installer", ignore=shutil.ignore_patterns("__pycache__"))
            out = Path(d) / "out" / "i.exe"
            out.parent.mkdir()
            digest = build.build(src, out, PINS, shutil.which("makensis"), Path(d) / "w", build.default_run)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertFalse((src / "installer" / "nsis" / "installer.exe").exists())

    def test_main_nsi_has_a_default_name_only_without_the_define(self):
        main = (NSIS / "main.nsi").read_text()
        self.assertRegex(main, r"!ifdef OUTFILE\s+OutFile \"\$\{OUTFILE\}\"\s+!else\s+OutFile \"installer.exe\"\s+!endif")


def install_text():
    return (NSIS / "install.nsh").read_text()


def func(text, name):
    return text.split(f"Function {name}")[1].split("FunctionEnd")[0]


class Bug3InstallSection(unittest.TestCase):
    def test_section_calls_the_footprint_function(self):
        main = (NSIS / "main.nsi").read_text()
        self.assertIn('!include "install.nsh"', main)
        self.assertRegex(main, r"Section\s*\n\s*Call Update_Route\s*\nSectionEnd")

    def test_install_creates_exactly_the_footprint_items(self):
        body = func(install_text(), "Install_Footprint")
        fp = footprint.load_footprint()
        self.assertIn("SetShellVarContext all", body)
        self.assertIn("SetRegView 64", body)
        self.assertIn("    Call Winsys_FolderCreate\n", body)
        create = func((NSIS / "winsys.nsh").read_text(), "Winsys_FolderCreate")
        self.assertIn(f"""System::Call 'kernel32::CreateDirectoryW(w "{fp["folder"]["path"]}", p r2) i .r0'""", create)
        self.assertIn("installer-state.json", body)
        self.assertIn(f'WriteUninstaller "{fp["folder"]["path"]}\\uninstall.exe"', body)
        key = fp["uninstall_entry"]["key"].replace("HKLM\\", "", 1)
        for value in ("DisplayName", "UninstallString"):
            self.assertRegex(body, rf'WriteRegStr HKLM "{re.escape(key)}" "{value}"')
        self.assertNotIn("sc.exe", body)

    def test_state_file_matches_the_state_schema_shape(self):
        body = func(install_text(), "Install_Footprint")
        self.assertIn('"schema_version": 1', body)
        self.assertIn('"installer_version"', body)

    def test_install_is_within_the_footprint_scan(self):
        self.assertEqual(footprint.check_source(footprint.collect_sources()), [])

    def test_install_nsh_is_an_elevated_file(self):
        self.assertNotIn("install.nsh", footprint.UNELEVATED_FILES)


class Bug4and5Uninstall(unittest.TestCase):
    def text(self):
        return (NSIS / "uninstall.nsh").read_text()

    def test_service_is_stopped_then_deleted_before_files(self):
        t = self.text()
        svc = func(t, "un.Uninstall_RemoveService")
        stop, delete = (f'"$SYSDIR\\sc.exe" {c} EcosystemRunner' for c in ("stop", "delete"))
        self.assertLess(svc.index(stop), svc.index(delete))
        sec = t.split('Section "Uninstall"')[1]
        self.assertLess(sec.index("Call un.Uninstall_RemoveService"), sec.index("Call un.Uninstall_RemoveFiles"))

    def test_registry_view_is_64_before_any_registry_call(self):
        body = func(self.text(), "un.Uninstall_RemoveFiles")
        self.assertLess(body.index("SetRegView 64"), body.index("DeleteRegKey"))

    def test_uninstall_exec_is_allowed_only_for_the_two_service_commands(self):
        fp = footprint.load_footprint()
        srcs = footprint.collect_sources()
        self.assertEqual(footprint.check_source(srcs, fp), [])
        bad = dict(srcs)
        bad["uninstall.nsh"] = srcs["uninstall.nsh"].replace("sc.exe\" delete EcosystemRunner", "sc.exe\" delete Other")
        self.assertTrue(footprint.check_source(bad, fp))
        bad["uninstall.nsh"] = srcs["uninstall.nsh"].replace("Function un.Uninstall_ForgeNote",
                                                            "Function un.Uninstall_ForgeNote\n  nsExec::Exec '\"$SYSDIR\\sc.exe\" stop EcosystemRunner'")
        self.assertTrue(footprint.check_source(bad, fp))
        bad["uninstall.nsh"] = srcs["uninstall.nsh"].replace('\'"$SYSDIR\\sc.exe" stop', "'sc.exe stop")
        self.assertTrue(footprint.check_source(bad, fp), "the bare form must be refused")

    @unittest.skipUnless(shutil.which("makensis"), "makensis absent")
    def test_script_compiles_with_warnings_as_errors(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(NSIS, Path(d) / "nsis")
            r = subprocess.run(["makensis", "-WX", "-V1", f"-DOUTFILE={d}/o.exe", str(Path(d) / "nsis" / "main.nsi")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Bug6NoTzdata(unittest.TestCase):
    def no_zoneinfo(self):
        return unittest.mock.patch.object(log, "ZoneInfo", side_effect=ZoneInfoNotFoundError("x"))

    def own(self, key):
        return unittest.mock.patch.object(log, "_registry_zone_key", return_value=key)

    def test_pinned_zone_converts_with_bias_without_zoneinfo(self):
        with self.no_zoneinfo(), self.own("W. Europe Standard Time"):
            self.assertEqual(log.display_hhmm("2026-07-01T12:05:00+00:00", "Europe/Amsterdam", active_time_bias=-120), "14:05")
            self.assertEqual(log.display_hhmm("2026-01-01T12:05:00+00:00", "Europe/Amsterdam", active_time_bias=-60), "13:05")

    def test_registry_bias_is_the_default_source(self):
        with self.no_zoneinfo(), self.own("Eastern Standard Time"), unittest.mock.patch.object(log, "_registry_bias", return_value=300):
            self.assertEqual(log.display_hhmm("2026-07-01T12:05:00+00:00", "America/New_York"), "07:05")

    def test_zone_other_than_the_pcs_own_is_refused(self):
        for own in ("Eastern Standard Time", None):
            with self.no_zoneinfo(), self.own(own):
                with self.assertRaises(log.UnknownZone):
                    log.display_hhmm("2026-07-01T12:05:00+00:00", "Europe/Amsterdam", active_time_bias=-120)

    def test_both_bias_signs(self):
        with self.no_zoneinfo(), self.own("Eastern Standard Time"):
            self.assertEqual(log.display_hhmm("2026-07-01T12:05:00+00:00", "America/New_York", active_time_bias=240), "08:05")
            self.assertEqual(log.display_hhmm("2026-07-01T00:30:00+00:00", "America/New_York", active_time_bias=300), "19:30")
        with self.no_zoneinfo(), self.own("W. Europe Standard Time"):
            self.assertEqual(log.display_hhmm("2026-07-01T23:30:00+00:00", "Europe/Amsterdam", active_time_bias=-120), "01:30")

    def test_unknown_zone_is_still_refused_without_zoneinfo(self):
        with self.no_zoneinfo():
            with self.assertRaises(log.UnknownZone):
                log.display_hhmm("2026-07-01T12:05:00+00:00", "Mars/Base", active_time_bias=0)

    def test_pinned_zone_without_any_bias_is_a_typed_error(self):
        with self.no_zoneinfo(), self.own("W. Europe Standard Time"), unittest.mock.patch.object(log, "_registry_bias", return_value=None):
            with self.assertRaises(log.UnknownZone):
                log.display_hhmm("2026-07-01T12:05:00+00:00", "Europe/Amsterdam")

    def test_naive_time_still_refused_in_fallback(self):
        with self.no_zoneinfo():
            with self.assertRaises(log.LogError):
                log.display_hhmm("2026-07-01T12:05:00", "Europe/Amsterdam", active_time_bias=0)

    @requires_zone_database("Europe/Amsterdam")
    def test_zoneinfo_is_used_when_available(self):
        self.assertEqual(log.display_hhmm("2026-07-01T12:05:00+00:00", "Europe/Amsterdam", active_time_bias=999), "14:05")


class Nits(unittest.TestCase):
    def test_state_file_failure_is_reported_not_skipped(self):
        body = func(install_text(), "Install_Footprint")
        failed = body.split("state_failed:")[1].split("state_done:")[0]
        for needle in ('Push "write installer-state.json"', "Call Install_StateFailed"):
            self.assertIn(needle, failed)
        self.assertIn("IfErrors state_failed", body)

    def test_install_refuses_without_elevation_before_any_write(self):
        body = func(install_text(), "Install_Footprint")
        gate = body[:body.index("    Call Winsys_FolderCreate\n")]
        self.assertIn("Call Elevate_IsAdmin", gate)
        self.assertIn("$elev_isadmin == 0", gate)
        self.assertIn("SetErrorLevel 38", gate)
        self.assertIn("Abort", gate)
        self.assertLess(body.index("Abort"), body.index("WriteRegStr"))


class Bug7LogZone(unittest.TestCase):
    def test_log_nsh_reads_and_writes_the_zone_name(self):
        nsh = (NSIS / "log.nsh").read_text()
        self.assertIn("TimeZoneInformation", nsh)
        self.assertIn("TimeZoneKeyName", nsh)
        self.assertRegex(nsh, r'"zone": "\$LogZone"')
        self.assertIn('ReadRegStr $LogZone HKLM "SYSTEM\\CurrentControlSet\\Control\\TimeZoneInformation" "TimeZoneKeyName"',
                      func(nsh, "LogStep"))
        self.assertIn("TimeZoneInformation\\TimeZoneKeyName", (ROOT / "installer" / "allowlist-read.txt").read_text())

    def test_zone_is_read_in_the_64_bit_view_free_of_plugins(self):
        nsh = (NSIS / "log.nsh").read_text()
        self.assertNotIn("System::", nsh)
        self.assertNotIn("nsExec", nsh)


if __name__ == "__main__":
    unittest.main()
