"""#335 (measured on Windows 11): Settings > Apps starts uninstall.exe with the user's filtered token, and the folder ACL alone (SYSTEM and
Administrators) made Windows refuse to open the file before the uninstaller ran. Every path that writes uninstall.exe now gives the file alone an
explicit Users read-and-execute entry, after the write, and a reset of the children (Winsys_FolderLock on a folder that is ours) puts it back.
The folder ACL is unchanged. The real winsys.nsh, install.nsh and update.nsh run in the test interpreter; icacls is modelled there."""
import re
import unittest
from pathlib import Path

from installer import footprint
from tests.nsis_interp import NSIS, ROOT, Service, UpdateWorld
from tests.test_installer_sl19 import KEPT, RUNNER, STATE, state_line

UNINSTALLER = ROOT + "\\uninstall.exe"
USERS_RX = {"*S-1-5-32-545": "(RX)"}
GRANT = '"$SYSDIR\\icacls.exe" "$APPDATA\\EcosystemRunner\\uninstall.exe" /grant:r *S-1-5-32-545:(RX)'
LOCK = ('"$SYSDIR\\icacls.exe" "$APPDATA\\EcosystemRunner" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F /grant:r *S-1-5-32-544:(OI)(CI)F')
TEXT = {p.name: p.read_text(encoding="utf-8") for p in NSIS.glob("*.ns[hi]")}


def func(text, name):
    return text.split("Function " + name + "\n")[1].split("FunctionEnd")[0]


class AclWorld(UpdateWorld):
    """The real Install_Footprint and Winsys_FolderLock (probe, lock, audit, setowner, reset, audit), not the routing stubs."""
    native_Install_Footprint = None
    native_Winsys_FolderLock = None


def installed(**kw):
    """An older install: its uninstall.exe has only the folder's entries, as every install before #335 left it."""
    w = AclWorld(files={RUNNER: "old-runner", STATE: state_line("0.1.0"), **KEPT}, service=Service(), **kw)
    w.folder_status = "ours"
    return w


def check_written_then_granted(case, w):
    """uninstall.exe was written, the Users entry came after the last write, and no reset of the children came after the entry."""
    ops = w.acl_ops
    case.assertIn("write uninstall.exe", ops)
    last_write = len(ops) - 1 - ops[::-1].index("write uninstall.exe")
    last_grant = len(ops) - 1 - ops[::-1].index("grant uninstall.exe")
    case.assertGreater(last_grant, last_write, ops)
    case.assertNotIn("reset *", ops[last_grant:], ops)
    case.assertEqual(w.grants.get(UNINSTALLER), USERS_RX)
    case.assertEqual(set(w.grants), {UNINSTALLER}, "only uninstall.exe gets an explicit entry")


class EveryPathThatWritesTheUninstaller(unittest.TestCase):
    def test_fresh_install(self):
        w = AclWorld()
        self.assertEqual(w.start("Install_Footprint"), "done")
        check_written_then_granted(self, w)
        self.assertEqual(w.acl_ops[:3], ["status", "lock folder", "audit"])
        self.assertNotIn("reset *", w.acl_ops)
        self.assertEqual(len(w.regs), 4)

    def test_update(self):
        w = installed(installer_version="0.2.0")
        self.assertEqual(w.start("Update_Route"), "done")
        self.assertEqual(w.v["upd_mode"], "update")
        self.assertEqual(w.files[RUNNER], "new-runner")
        self.assertIn("reset *", w.acl_ops)  # the folder is ours: its children are reset before the new uninstaller is written
        check_written_then_granted(self, w)

    def test_repair(self):
        w = installed(installer_version="0.1.0")
        self.assertEqual(w.start("Update_Route"), "done")
        self.assertEqual(w.v["upd_mode"], "repair")
        self.assertIn("reset *", w.acl_ops)
        check_written_then_granted(self, w)


class ResetsThatEndBeforeTheUninstallerIsWrittenAgain(unittest.TestCase):
    """A run that locks a folder that is ours resets uninstall.exe and may end before Update_WriteEntry: the lock puts the entry back."""

    def check_kept(self, w):
        self.assertNotIn("write uninstall.exe", w.acl_ops)
        last_reset = len(w.acl_ops) - 1 - w.acl_ops[::-1].index("reset *")
        self.assertIn("grant uninstall.exe", w.acl_ops[last_reset:], w.acl_ops)
        self.assertEqual(w.grants, {UNINSTALLER: USERS_RX})

    def test_declined_update(self):
        w = installed(installer_version="0.2.0", silent=False, answer="IDNO")
        w.grants[UNINSTALLER] = dict(USERS_RX)
        self.assertEqual(w.start("Update_Route"), "quit")
        self.assertEqual(w.errorlevel, 43)
        self.check_kept(w)

    def test_restored_update_exit_42(self):
        w = installed(installer_version="0.2.0", fail=("swap",))
        w.grants[UNINSTALLER] = dict(USERS_RX)
        self.assertEqual(w.start("Update_Route"), "quit")
        self.assertEqual(w.errorlevel, 42)
        self.check_kept(w)

    def test_a_folder_without_uninstaller_is_locked_without_a_grant(self):
        w = installed()
        del w.files[UNINSTALLER]
        self.assertEqual(w.start("Winsys_FolderLock"), "done")
        self.assertNotIn("grant uninstall.exe", w.acl_ops)
        self.assertEqual(w.grants, {})


class GrantFailure(unittest.TestCase):
    def test_a_failed_grant_stops_with_exit_2_before_the_uninstall_entry(self):
        for entry in ("Install_Footprint", "Update_WriteEntry", "Winsys_FolderLock"):
            with self.subTest(entry=entry):
                w = installed() if entry == "Winsys_FolderLock" else AclWorld()
                w.icacls_fail.add("grant")
                self.assertEqual(w.start(entry), "abort")
                self.assertEqual(w.errorlevel, 2)
                self.assertEqual(w.regs, {})


class Text(unittest.TestCase):
    def test_the_grant_is_file_only_read_execute_for_users_and_listed(self):
        body = func(TEXT["winsys.nsh"], "Winsys_UninstallerGrant")
        self.assertEqual(re.findall(r"nsExec::Exec `([^`]*)`", body), [GRANT])
        self.assertNotIn("(OI)", GRANT)
        self.assertNotIn("(CI)", GRANT)
        self.assertNotRegex(GRANT.split("545:")[1], r"[FMWD]")
        entries = [e for e in footprint.load_footprint()["exec_allowed"] if e["function"] == "Winsys_UninstallerGrant"]
        self.assertEqual(entries, [{"file": "winsys.nsh", "function": "Winsys_UninstallerGrant", "commands": [GRANT]}])

    def test_the_folder_lock_line_is_unchanged(self):
        lock = func(TEXT["winsys.nsh"], "Winsys_FolderLock")
        self.assertEqual(re.findall(r"nsExec::Exec `([^`]*)`", lock), [LOCK])
        self.assertNotIn("S-1-5-32-545", lock.replace("Call Winsys_UninstallerGrant", ""))
        self.assertEqual(sum(t.count("S-1-5-32-545") for t in TEXT.values()), 1)

    def test_every_write_of_the_uninstaller_is_followed_by_the_grant(self):
        sites = [(name, f) for name, t in TEXT.items() for f in re.findall(r"Function (\S+)\n", t) if re.search(r"(?m)^\s*WriteUninstaller ", func(t, f))]
        self.assertEqual(sorted(sites), [("install.nsh", "Install_Footprint"), ("update.nsh", "Update_WriteEntry")])
        for name, f in sites:
            body = func(TEXT[name], f)
            self.assertIn("uninstaller_ready:\n  Call Winsys_UninstallerGrant\n  WriteRegStr", body)

    def test_the_only_reset_is_inside_the_lock_and_followed_by_the_grant(self):
        callers = [(name, f) for name, t in TEXT.items() for f in re.findall(r"Function (\S+)\n", t) if re.search(r"(?m)^\s*Call Winsys_FolderReset$", func(t, f))]
        self.assertEqual(callers, [("winsys.nsh", "Winsys_FolderLock")])
        lock = func(TEXT["winsys.nsh"], "Winsys_FolderLock")
        self.assertLess(lock.index("Call Winsys_FolderReset"), lock.index("Call Winsys_UninstallerGrant"))
        self.assertEqual(sum(t.count("/reset") for t in TEXT.values()), 1)


if __name__ == "__main__":
    unittest.main()
