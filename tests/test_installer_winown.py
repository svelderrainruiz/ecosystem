"""WINOWN-1 (#191): no default owner or check/create race on the first install."""
import contextlib
import ctypes
import io
import os
import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from installer import footprint, schema, winsys
from tests.nsis_interp import NSIS, ROOT, Program
from tests.test_installer_docfix_ef import InstallWorld


class SecureFolder(unittest.TestCase):
    def test_descriptor_failure_exit_contract(self):
        code = schema.load_schema()["exit_codes"]["folder-descriptor-failed"]
        self.assertEqual(code, 2)
        self.assertEqual(winsys.exit_code(winsys.FolderDescriptorError()), code)
        w = InstallWorld()
        w.folder_create = "descriptor-fails"
        self.assertEqual(w.start("Install_Footprint"), "abort")
        self.assertEqual(w.errorlevel, code)

    def test_atomic_create_records_security_and_refuses_replacement(self):
        w = InstallWorld()
        self.assertEqual(w.folder_status, "abse")
        self.assertFalse(w.exists(ROOT))
        self.assertEqual(w.start("Winsys_FolderCreate"), "done")
        self.assertTrue(w.exists(ROOT))
        self.assertEqual(w.folder_status, "fres")
        self.assertEqual(w.folder_security, {"owner": "S-1-5-32-544", "protected": True,
                                            "dacl": ("A;OICI;FA;;;SY", "A;OICI;FA;;;BA")})
        # The probe still says absent, but a directory appeared before CreateDirectoryW.
        w = InstallWorld(files={ROOT + "\\.dir": ""})
        self.assertEqual(w.start("Install_Footprint"), "abort")
        self.assertEqual(w.errorlevel, 39)
        self.assertIsNone(w.folder_security)
        self.assertNotIn("lock", w.events)

    def test_no_plain_install_root_create(self):
        program = Program()
        for tokens in program.lines(program.functions["Install_Footprint"]):
            if tokens[0].casefold() == "createdirectory":
                self.assertNotEqual(tokens[1].rstrip("\\").casefold(), r"$appdata\ecosystemrunner")

    def test_footprint_requires_exact_secure_create(self):
        call = r"""System::Call 'kernel32::CreateDirectoryW(w "$APPDATA\EcosystemRunner", p r2) i .r0'"""
        site = "Function Winsys_FolderCreate\n  %s\nFunctionEnd"
        self.assertEqual(footprint.check_source({"winsys.nsh": site % call}), [])
        for file, source in (("winsys.nsh", site % call.replace("p r2", "p 0")),
                             ("winsys.nsh", site.replace("FolderCreate", "Other") % call),
                             ("other.nsh", site % call)):
            with self.subTest(file=file, source=source):
                self.assertTrue(footprint.check_source({file: source}))

    def test_same_explicit_descriptor(self):
        self.assertEqual(winsys.FOLDER_SDDL, "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)")
        source = (NSIS / "winsys.nsh").read_text()
        self.assertEqual(re.findall(r'ConvertStringSecurityDescriptorToSecurityDescriptorW\(w "([^"]+)", i 1, \*p \.r1, p 0\)', source),
                         [winsys.FOLDER_SDDL])

    def test_install_outcomes_and_cleanup(self):
        for outcome, code in [("ok", 0), ("create-fails", 39), ("descriptor-fails", 2)]:
            with self.subTest(outcome=outcome):
                w = InstallWorld()
                w.folder_create = outcome
                self.assertEqual(w.start("Install_Footprint"), "abort" if code else "done")
                self.assertEqual(w.errorlevel or 0, code)
                self.assertEqual(w.events.count("folder-create"), 1)
                for event in ("free-attributes", "free-descriptor"):
                    self.assertEqual(w.events.count(event), int(code != 2))
                if code:
                    self.assertNotIn("lock", w.events)
                    self.assertEqual((w.regs, w.files), ({}, {}))
                else:
                    self.assertLess(w.events.index("folder-create"), w.events.index("lock"))
                    self.assertIn(ROOT + "\\installer-state.json", w.files)

    def test_existing_folders_are_locked_without_creation(self):
        for status in ("fres", "ours"):
            with self.subTest(status=status):
                w = InstallWorld()
                w.folder_status, w.folder_create = status, "create-fails"
                self.assertEqual(w.start("Install_Footprint"), "done")
                self.assertNotIn("folder-create", w.events)
                self.assertIn("lock", w.events)

    def test_ctypes_passes_native_attributes_and_releases_every_owned_descriptor(self):
        for descriptor_ok, create_ok, code in [(False, False, 2), (True, False, 39), (True, True, 0)]:
            with self.subTest(code=code):
                advapi, kernel = Mock(), Mock()
                pointer = 0x12345678 if ctypes.sizeof(ctypes.c_void_p) == 4 else 0x123456789

                def convert(sddl, revision, output, size):
                    self.assertEqual((sddl, revision, size), (winsys.FOLDER_SDDL, 1, None))
                    if descriptor_ok:
                        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = pointer
                    return descriptor_ok

                def create(path, attributes):
                    sa = ctypes.cast(attributes, kernel.CreateDirectoryW.argtypes[1]).contents
                    self.assertEqual((path, sa.descriptor, sa.inherit_handle), (ROOT, pointer, 0))
                    self.assertEqual(sa.length, 3 * ctypes.sizeof(ctypes.c_void_p))
                    return create_ok

                advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.side_effect = convert
                kernel.CreateDirectoryW.side_effect = create
                system = winsys.WinSystem(ROOT)
                with (patch.object(winsys, "os", SimpleNamespace(name="nt")),
                      patch.object(ctypes, "WinDLL", side_effect=[advapi, kernel], create=True),
                      patch.object(ctypes, "get_last_error", return_value=5, create=True),
                      patch.object(ctypes, "WinError", return_value=PermissionError("access denied"), create=True),
                      patch.object(system, "folder_status", return_value="absent"),
                      patch.object(system, "lock_folder") as lock,
                      contextlib.redirect_stderr(io.StringIO())):
                    self.assertEqual(winsys.main(["prepare-folder", ROOT], system), code)
                self.assertEqual(lock.call_count, int(not code))
                self.assertEqual(kernel.CreateDirectoryW.call_count, int(descriptor_ok))
                self.assertEqual(kernel.LocalFree.call_count, int(descriptor_ok))
                if descriptor_ok:
                    self.assertEqual(kernel.LocalFree.call_args.args[0].value, pointer)

    @unittest.skipIf(os.name == "nt", "off-Windows contract")
    def test_default_does_not_create_an_unprotected_folder_off_windows(self):
        with self.assertRaisesRegex(winsys.FolderDescriptorError, "requires Windows"):
            winsys.create_secure_folder(ROOT)
