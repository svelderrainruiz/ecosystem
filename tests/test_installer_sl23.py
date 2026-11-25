"""SL-23 (ecosystem-control#115, part 1: uninstall.nsh): the uninstaller never follows a junction or a symbolic link.
Measured on real Windows 11 (probe P1): NSIS RMDir with the recursive switch FOLLOWS a directory junction and deletes the files it points to, and the
uninstaller runs elevated. So no recursive RMDir is left in installer/nsis; every tree goes through Tree_Remove (tree.nsh, un.Tree_Remove here),
which reads the reparse flag of every entry and never enters a link.
The NSIS text cannot run on this host, so it runs on the interpreter of tests/test_installer_uninst.py (class Nsis on a scripted Windows, class World).
World models links as a real Windows guest answered (MEASURED, GUEST7A, winev-run-afbbd3e1): the recursive RMDir follows a directory link and empties its
target; the plain RMDir and the Win32 RemoveDirectoryW (no trailing backslash) remove a directory link and never its target; Delete removes a file link;
"." and ".." are resolved as Windows does, so a walk that does not skip them loops or climbs. GUEST7B (winev-run-3f6fe4f2) ran the real uninstaller of commit 032f54a on a guest; GUEST7C ran it again on develop 3bea02c (winev-run-d3710e18),
and tree.nsh changed between the two (SL23F). No network."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer import footprint
from installer.guest import pack
from tests.test_installer_uninst import (ENTRY, FOLDER, NSIS, README, ROOT, UNINSTALL, Escaped, Nsis, Runaway, World, body, code, files,
                                         tree_text)

OUT = r"C:\Outside\data"
OTHER = r"C:\Outside\other"
SECRET = OUT + r"\secret.txt"
KEEP = OTHER + r"\keep.txt"
REAL = OUT + r"\real.db"


def junction(target=OUT):
    return ("dir", target)


def remove(world, rel, **registers):
    """Runs un.Tree_Remove on one path below the product folder; the result is in $2."""
    n = Nsis(UNINSTALL, world)
    n.v.update(registers)
    n.stack.append(rel)
    n.start("un.Tree_Remove")
    return n


def clear(world):
    n = Nsis(UNINSTALL, world)
    n.start("un.Uninstall_ClearFolder")
    return n


def chain(depth):
    return "\\".join(f"d{i}" for i in range(1, depth + 1))


class LinksAreNeverEntered(unittest.TestCase):
    def test_a_junction_to_an_outside_folder_goes_as_a_link_and_the_outside_file_stays_sl23(self):
        w = World(files={"config.toml"}, links={"data": junction()}, outside={SECRET})
        n = clear(w)
        self.assertEqual((n.v["2"], w.links, w.files, w.outside), ("0", {}, set(), {SECRET}))
        self.assertEqual(n.ops, ["delete config.toml", "removedirectory data"])
        self.assertNotIn("data", w.listed)

    def test_a_junction_three_levels_deep_goes_as_a_link_and_the_outside_file_stays_sl23(self):
        deep = "program\\a\\b\\link"
        w = World(files={"program\\a\\b\\x.txt"}, links={deep: junction()}, outside={SECRET})
        n = remove(w, "program")
        self.assertEqual((n.v["2"], w.links, w.files, w.dirs, w.outside), ("0", {}, set(), set(), {SECRET}))
        self.assertEqual(n.ops, [f"removedirectory {deep}", "delete program\\a\\b\\x.txt", "rmdir program\\a\\b", "rmdir program\\a", "rmdir program"])
        self.assertNotIn(deep, w.listed)

    def test_a_file_symlink_is_deleted_as_a_link_and_its_target_stays_sl23(self):
        w = World(files={"state\\keep.txt"}, links={"state\\db.lnk": ("file", REAL)}, outside={REAL})
        n = remove(w, "state")
        self.assertEqual((n.v["2"], w.links, w.files, w.outside), ("0", {}, set(), {REAL}))
        self.assertEqual(n.ops, ["delete state\\db.lnk", "delete state\\keep.txt", "rmdir state"])

    def test_a_dangling_junction_goes_as_a_link_sl23(self):
        w = World(links={"old": ("dir", None)})
        n = remove(w, "old")
        self.assertEqual((n.v["2"], w.links, n.ops), ("0", {}, ["removedirectory old"]))

    def test_a_junction_named_like_a_real_subfolder_is_a_link_not_a_folder_sl23(self):
        w = World(files={"state\\db.json"}, links={"program": junction()}, outside={SECRET})
        n = clear(w)
        self.assertEqual((n.v["2"], w.links, w.files, w.outside), ("0", {}, set(), {SECRET}))
        self.assertEqual(n.ops, ["removedirectory program", "delete state\\db.json", "rmdir state"])
        self.assertNotIn("program", w.listed)

    def test_the_whole_guest_probe_tree_all_four_kinds_at_once_sl23(self):
        """The four kinds of link the guest probe builds: a junction to an outside folder with a file, a nested junction, a file symlink, a dangling junction."""
        w = World(files={"program\\runner.exe", "config.toml"},
                  links={"data": junction(), "program\\nested": junction(OTHER), "db.lnk": ("file", REAL), "dangling": ("dir", None)},
                  outside={SECRET, KEEP, REAL})
        n = clear(w)
        self.assertEqual((n.v["2"], w.links, w.files, w.dirs, w.outside), ("0", {}, set(), set(), {SECRET, KEEP, REAL}))
        self.assertFalse([op for op in n.ops if op.startswith("rmdir /r")])
        self.assertEqual(set(w.listed) - {"", "program"}, set())

    def test_started_in_place_a_junction_goes_as_a_link_and_the_running_uninstaller_stays_sl23(self):
        w = World(files={"uninstall.exe"}, locked={"uninstall.exe"}, links={"data": junction()}, outside={SECRET},
                  exedir=FOLDER, exefile="uninstall.exe")
        n, quit_ = files(w)
        self.assertEqual((quit_, n.errorlevel, n.keys, w.links, w.outside, w.files), (False, 0, [ENTRY], {}, {SECRET}, {"uninstall.exe"}))

    def test_a_locked_file_beside_a_junction_keeps_uninstall_exe_and_the_entry_but_the_link_goes_sl23(self):
        w = World(files={"uninstall.exe", "program\\runner.exe"}, locked={"program\\runner.exe"}, links={"data": junction()}, outside={SECRET})
        n, quit_ = files(w)
        self.assertTrue(quit_)
        self.assertEqual((n.errorlevel, n.keys, n.sleeps, w.links, w.outside), (40, [], [1000] * 5, {}, {SECRET}))
        self.assertEqual(w.files, {"uninstall.exe", "program\\runner.exe"})


class TheFolderItself(unittest.TestCase):
    def test_a_product_folder_that_is_a_junction_stops_the_run_with_40_and_touches_nothing_sl23(self):
        w = World(links={"": junction()}, outside={SECRET, OUT + r"\more.txt"}, silent=False)
        n, quit_ = files(w)
        self.assertTrue(quit_)
        self.assertEqual((n.errorlevel, n.ops, n.keys, n.sleeps, w.listed), (40, [], [], [], []))
        self.assertEqual(w.outside, {SECRET, OUT + r"\more.txt"})
        self.assertIn(FOLDER, n.boxes[-1])
        self.assertIn("link", n.boxes[-1])
        self.assertIn("run the uninstall again", n.boxes[-1])

    def test_the_whole_uninstall_removes_the_service_then_stops_at_a_junction_folder_keeping_the_entry_sl23(self):
        w = World(links={"": junction()}, outside={SECRET})
        n = Nsis(UNINSTALL, w)
        self.assertTrue(n.start("section"))
        self.assertEqual((n.log, n.errorlevel, n.keys, n.ops, w.outside), (["stop", "query", "delete"], 40, [], [], {SECRET}))

    def test_a_dangling_junction_as_the_product_folder_is_a_link_too_sl23(self):
        w = World(links={"": ("dir", None)})
        n, quit_ = files(w)
        self.assertEqual((quit_, n.errorlevel, n.ops, n.keys), (True, 40, [], []))

    def test_a_product_folder_whose_flag_cannot_be_read_stops_the_run_with_40_and_touches_nothing_sl23(self):
        w = World(files={"program\\runner.exe", "uninstall.exe"}, attr_errors={""}, silent=False)
        n, quit_ = files(w)
        self.assertEqual((quit_, n.errorlevel, n.ops, n.keys, w.files), (True, 40, [], [], {"program\\runner.exe", "uninstall.exe"}))
        self.assertIn("could not be checked", n.boxes[-1])

    def test_an_absent_product_folder_is_not_a_link_and_the_run_finishes_sl23(self):
        w = World()
        w.folder = False
        n, quit_ = files(w)
        self.assertEqual((quit_, n.errorlevel, n.keys), (False, 0, [ENTRY]))

    def test_an_absent_product_folder_has_nothing_to_clear_while_an_existing_unlistable_one_is_a_leftover_sl23(self):
        absent = World()
        absent.folder = False
        self.assertEqual(clear(absent).v["2"], "0")
        self.assertEqual(clear(World(files={"a.txt"}, list_errors={""})).v["2"], "1")


class DepthCap(unittest.TestCase):
    def test_a_chain_of_24_folders_is_removed_sl23(self):
        w = World(files={chain(24) + "\\f.txt"})
        n = remove(w, "d1")
        self.assertEqual((n.v["2"], w.files, w.dirs), ("0", set(), set()))

    def test_a_chain_of_25_folders_is_left_over_and_the_25th_is_not_entered_sl23(self):
        w = World(files={chain(25) + "\\f.txt"})
        n = remove(w, "d1")
        self.assertEqual((n.v["2"], w.files), ("1", {chain(25) + "\\f.txt"}))
        self.assertIn(chain(24), w.listed)
        self.assertNotIn(chain(25), w.listed)

    def test_a_tree_deeper_than_the_cap_stops_the_uninstall_with_40_and_keeps_uninstall_exe_and_the_entry_sl23(self):
        deep = chain(25) + "\\f.txt"
        w = World(files={"uninstall.exe", deep})
        n, quit_ = files(w)
        self.assertTrue(quit_)
        self.assertEqual((n.errorlevel, n.keys, n.sleeps, w.files), (40, [], [1000] * 5, {"uninstall.exe", deep}))

    def test_siblings_do_not_use_up_the_cap_so_a_subfolder_listed_after_many_files_is_removed_sl23(self):
        """The counter goes up for a call and down after it (tree.nsh, IntOp ... - 1). Without the decrement, 25 or more siblings used the cap up and
        the subfolder listed after them was left over: a false exit code 40."""
        names = {"program\\f%02d.txt" % i for i in range(30)} | {"program\\zz\\last.txt"}
        w = World(files=names)
        n = remove(w, "program")
        self.assertEqual((n.v["2"], w.files, w.dirs), ("0", set(), set()))
        self.assertIn("program\\zz", w.listed)
        n, quit_ = files(World(files=names | {"uninstall.exe"}))
        self.assertEqual((quit_, n.errorlevel, n.keys), (False, 0, [ENTRY]))


class UnreadableFlags(unittest.TestCase):
    def test_an_entry_whose_flag_cannot_be_read_is_left_over_and_untouched_sl23(self):
        w = World(files={"program\\runner.exe"}, attr_errors={"program"})
        n = remove(w, "program")
        self.assertEqual((n.v["2"], n.ops, w.files), ("1", [], {"program\\runner.exe"}))

    def test_an_entry_below_a_folder_whose_flag_cannot_be_read_is_left_over_the_rest_goes_sl23(self):
        w = World(files={"program\\a.dll", "program\\b.dll"}, attr_errors={"program\\a.dll"})
        n = remove(w, "program")
        self.assertEqual((n.v["2"], n.ops, w.files), ("1", ["delete program\\b.dll", "rmdir program"], {"program\\a.dll"}))
        self.assertEqual(w.dirs, {"program"})  # the plain RMDir was refused: the folder still holds a.dll

    def test_an_empty_answer_without_the_error_flag_is_a_leftover_too_sl23(self):
        """Each failure signal is distrusted on its own: an empty answer is not 'no link' even when the flag is clear."""
        w = World(files={"program\\runner.exe"}, attr_blank={"program"})
        n = remove(w, "program")
        self.assertEqual((n.v["2"], n.ops, w.files), ("1", [], {"program\\runner.exe"}))

    def test_a_set_error_flag_beside_a_usable_looking_answer_is_a_leftover_too_sl23(self):
        w = World(files={"program\\runner.exe"}, attr_flagged={"program"})
        n = remove(w, "program")
        self.assertEqual((n.v["2"], n.ops, w.files), ("1", [], {"program\\runner.exe"}))

    def test_a_product_folder_with_an_empty_answer_or_a_set_flag_stops_the_run_with_40_sl23(self):
        for kw in ({"attr_blank": {""}}, {"attr_flagged": {""}}):
            with self.subTest(kw=kw):
                w = World(files={"program\\runner.exe", "uninstall.exe"}, silent=False, **kw)
                n, quit_ = files(w)
                self.assertEqual((quit_, n.errorlevel, n.ops, n.keys, w.files), (True, 40, [], [], {"program\\runner.exe", "uninstall.exe"}))
                self.assertIn("could not be checked", n.boxes[-1])

    def test_one_unreadable_entry_does_not_poison_the_next_ones_sl23(self):
        """The error flag of the first entry must not make the next one look unreadable: ClearErrors comes right before each read."""
        w = World(files={"a.txt", "b.txt", "c.txt"}, attr_errors={"a.txt"})
        n = clear(w)
        self.assertEqual((n.v["2"], n.ops, w.files), ("1", ["delete b.txt", "delete c.txt"], {"a.txt"}))

    def test_an_unreadable_entry_stops_the_uninstall_with_40_and_keeps_uninstall_exe_and_the_entry_sl23(self):
        w = World(files={"uninstall.exe", "program\\runner.exe"}, attr_errors={"program"})
        n, quit_ = files(w)
        self.assertTrue(quit_)
        self.assertEqual((n.errorlevel, n.keys, n.sleeps, w.files), (40, [], [1000] * 5, {"uninstall.exe", "program\\runner.exe"}))


class Registers(unittest.TestCase):
    TREE = {"program\\a\\x.txt", "program\\b\\y.txt", "program\\c.txt"}
    SENTINELS = {name: "keep-" + name for name in ("0", "1", "3", "4", "5", "6", "7", "8", "9", "R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9",
                                                   "tree_depth")}

    def test_sibling_folders_are_all_removed_because_the_registers_are_saved_around_the_recursion_sl23(self):
        w = World(files=self.TREE)
        n = remove(w, "program")
        self.assertEqual((n.v["2"], w.files, w.dirs), ("0", set(), set()))
        self.assertEqual(n.ops, ["delete program\\a\\x.txt", "rmdir program\\a", "delete program\\b\\y.txt", "rmdir program\\b",
                                 "delete program\\c.txt", "rmdir program"])

    def test_every_register_outside_the_documented_set_survives_a_whole_walk_sl23(self):
        w = World(files=self.TREE, links={"program\\a\\ln": junction()}, outside={SECRET})
        n = remove(w, "program", **self.SENTINELS)
        self.assertEqual({name: n.v[name] for name in self.SENTINELS}, self.SENTINELS)
        self.assertEqual((n.v["2"], w.files, w.outside), ("0", set(), {SECRET}))
        self.assertEqual(n.stack, [])

    def test_the_depth_counter_is_back_to_where_it_was_after_a_walk_sl23(self):
        w = World(files=self.TREE)
        n = remove(w, "program", tree_depth="7")
        self.assertEqual(n.v["tree_depth"], "7")


class NormalTree(unittest.TestCase):
    TREE = {"uninstall.exe", "program\\runner.exe", "program\\lib\\a.dll", "config.toml", "state\\db.json"}

    def test_a_normal_tree_goes_with_uninstall_exe_last_and_the_entry_after_it_sl23(self):
        w = World(files=self.TREE)
        n = Nsis(UNINSTALL, w)
        self.assertFalse(n.start("section"))
        self.assertEqual((w.files, w.dirs, w.folder, n.keys, n.errorlevel, n.sleeps), (set(), set(), False, [ENTRY], 0, []))
        self.assertEqual(n.ops, ["delete config.toml", "delete program\\lib\\a.dll", "rmdir program\\lib", "delete program\\runner.exe",
                                 "rmdir program", "delete state\\db.json", "rmdir state", "delete uninstall.exe", "rmdir ."])
        self.assertFalse([op for op in n.ops if op.startswith("rmdir /r")])

    def test_no_find_handle_is_left_open_by_a_whole_uninstall_sl23(self):
        in_place = {"locked": {"uninstall.exe"}, "exedir": FOLDER, "exefile": "uninstall.exe"}  # also runs the self-left check, which lists the folder
        for kw in ({}, {"locked": {"program\\lib\\a.dll"}}, in_place):
            with self.subTest(kw=kw):
                n, _ = files(World(files=self.TREE, **kw))
                self.assertGreater(n.handles, 0)
                self.assertEqual(n.open_handles, 0)

    def test_a_folder_left_by_a_locked_file_is_a_leftover_and_the_run_retries_five_times_sl23(self):
        w = World(files=self.TREE, locked={"program\\lib\\a.dll"})
        n, quit_ = files(w)
        self.assertTrue(quit_)
        self.assertEqual((n.errorlevel, n.keys, n.sleeps), (40, [], [1000] * 5))
        self.assertEqual(w.files, {"uninstall.exe", "program\\lib\\a.dll"})


def nsis_instructions(text):
    """(line number, words) of every instruction, read the way makensis reads a script: block comments and backslash continuations are gone,
    `;` and `#` start a comment only at the start of a word, a leading `label:` is dropped, '...' "..." and `...` quote a word and the quotes
    go, and !define words are expanded in place (textually, as makensis does)."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"\\[ \t]*\r?\n", " ", text)
    defines, found = {}, []
    for number, line in enumerate(text.splitlines(), 1):
        for _ in range(5):
            for name, value in defines.items():
                line = line.replace("${%s}" % name, value)
        words, i = [], 0
        while i < len(line):
            ch = line[i]
            if ch in " \t":
                i += 1
            elif ch in ";#":
                break
            elif ch in "\"'`":
                end = line.find(ch, i + 1)
                end = len(line) if end < 0 else end
                words.append(line[i + 1:end])
                i = end + 1
            else:
                end = i
                while end < len(line) and line[end] not in " \t":
                    end += 1
                words.append(line[i:end])
                i = end
        if words and re.fullmatch(r"[A-Za-z_.][\w.]*:", words[0]):
            words = words[1:]
        if words and words[0].lower() == "!define" and len(words) >= 3:
            defines[words[1]] = " ".join(words[2:])
        if words:
            found.append((number, words))
    return found


SHELL_TREE_DELETE = re.compile(r"(?i)\b(?:rd|rmdir|del|erase)\b.*\s/s\b|-recurse\b|\bremove-item\b|\bshfileoperation|\brobocopy\b.*\s/(?:mir|purge)\b")


DISPLAY_ONLY = ("detailprint", "messagebox", "!echo", "!warning", "!error")


def unsafe_instructions(text):
    """The numbers of the lines that could delete a tree: any RMDir that is not exactly `RMDir <one path>` (a switch in any spelling, a second
    word, a path that is only a define or macro parameter) and any other instruction that carries a recursive shell delete in its words (a
    command string for Exec, nsExec, a StrCpy that builds one, ...); only instructions that merely display text are read as text. Nothing else
    is exempt: no file, no line."""
    bad = []
    for number, words in nsis_instructions(text):
        if words[0].lower() == "rmdir":
            args = words[1:]
            if len(args) != 1 or args[0].startswith("/") or re.fullmatch(r"\$\{[^}]*\}", args[0]):
                bad.append(number)
        elif words[0].lower() not in DISPLAY_ONLY and SHELL_TREE_DELETE.search(" ".join(words)):
            bad.append(number)
    return bad


class NoRecursiveRmdir(unittest.TestCase):
    FLAGGED = ("RMDir /r x", 'rmdir  /R  "$x"', "\tRMDir /REBOOTOK /r x", "RMDir /r", "  RMDIR\t/R x ; why", 'RMDir "/r" x', "RMDir '/R' x", "RMDir `/r` x",
               'RMDir "/r"', "RMDir '/r'", "RMDir `/R`",
               "RMDir /r /REBOOTOK x", "RMDir \\\n  /r x", "RMDir /* c */ /r x", "/* a */ RMDir /r x", "lbl: RMDir /r x", "!define SW /r\nRMDir ${SW} x",
               "!define RM RMDir\n${RM} /r x", '!macro Rm SW P\n  RMDir ${SW} "${P}"\n!macroend', "RMDir ${UNKNOWN}", "RMDir /REBOOTOK x",
               "nsExec::Exec 'cmd /c rd /s /q \"x\"'", "nsExec::Exec 'cmd /c RMDIR /S /Q x'", "ExecWait 'powershell -Command \"Remove-Item -Recurse x\"'",
               'nsExec::Exec "robocopy a b /MIR"', "System::Call 'shell32::SHFileOperationW(i r1)'")
    SAFE = ("; RMDir /r x", "# RMDir /r x", "RMDir x", "RMDir /* c */ x", 'RMDir "$APPDATA\\r"', "RMDir x ; was RMDir /r", "/* RMDir /r x */",
            'RMDir "${TREE_ROOT}\\$R0"', "Delete /r x", "lbl: RMDir x", 'DetailPrint "rd /s is not used"')

    def test_the_guard_flags_every_accepted_spelling_of_a_recursive_delete_and_ignores_comments_sl23(self):
        for text in self.FLAGGED:
            with self.subTest(flagged=text):
                self.assertTrue(unsafe_instructions(text), text)
        for text in self.SAFE:
            with self.subTest(safe=text):
                self.assertEqual(unsafe_instructions(text), [], text)

    def test_no_recursive_rmdir_is_left_in_any_nsh_or_nsi_of_the_installer_sl23(self):
        sources = [*sorted(NSIS.glob("*.nsh")), *sorted(NSIS.glob("*.nsi"))]
        self.assertIn("tree.nsh", [s.name for s in sources])
        self.assertIn("main.nsi", [s.name for s in sources])
        offenders = {s.name: unsafe_instructions(s.read_text()) for s in sources}
        self.assertEqual({name: lines for name, lines in offenders.items() if lines}, {})

    def test_the_two_places_that_used_the_switch_use_tree_remove_and_the_plain_rmdir_sl23(self):
        clear_body, files_body = code(body(UNINSTALL, "un.Uninstall_ClearFolder")), code(body(UNINSTALL, "un.Uninstall_RemoveFiles"))
        self.assertRegex(clear_body, r'Push "\$4"\s+Call un\.Tree_Remove')
        self.assertEqual(files_body.count('RMDir "$APPDATA\\EcosystemRunner"'), 1)
        self.assertEqual(files_body.count("${un.GetFileAttributes}"), 1)


class TreeSource(unittest.TestCase):
    def test_one_macro_is_the_only_source_of_both_copies_sl23(self):
        text = (NSIS / "tree.nsh").read_text()
        self.assertEqual(text.count("!macro Tree_Define P"), 1)
        self.assertEqual(sorted(re.findall(r'^!insertmacro Tree_Define "(.*)"$', text, re.M)), ["", "un."])
        self.assertEqual(re.findall(r"^Function (\S+)$", text, re.M), ["${P}Tree_Remove", "${P}Tree_Walk"])
        self.assertIn('!include "tree.nsh"', UNINSTALL)

    def test_the_reparse_flag_is_read_from_the_entry_itself_and_never_the_recursive_switch_sl23(self):
        walk = code((NSIS / "tree.nsh").read_text())
        self.assertIn('"REPARSE_POINT"', walk)
        self.assertEqual(len(re.findall(r"\$\{\$\{P\}GetFileAttributes\}", walk)), 2)  # the reparse flag, then the directory flag of a link
        self.assertNotRegex(walk, r"(?i)rmdir\s+/r")

    def test_the_footprint_check_passes_with_tree_nsh_sl23(self):
        self.assertEqual(footprint.check_source(footprint.collect_sources()), [])


class TheModel(unittest.TestCase):
    """The test interpreter must behave like Windows where the uninstaller depends on it, or the tests above prove nothing."""

    PROBE = """Function probe
  ClearErrors
  ${un.GetFileAttributes} "$APPDATA\\EcosystemRunner\\$R0" "REPARSE_POINT" $R4
  ${un.GetFileAttributes} "$APPDATA\\EcosystemRunner\\$R0" "DIRECTORY" $R5
FunctionEnd"""

    def answers(self, world, name):
        n = Nsis(self.PROBE, world)
        n.v["R0"] = name
        n.start("probe")
        return n.v["R4"], n.v["R5"], n.errors

    def test_the_attribute_model_answers_one_zero_or_empty_with_the_error_flag_sl23(self):
        w = World(files={"f.txt", "d\\g.txt"}, links={"j": junction(), "s": ("file", REAL), "gone": ("dir", None)}, outside={SECRET},
                  attr_errors={"bad.txt"})
        self.assertEqual(self.answers(w, "f.txt"), ("0", "0", False))
        self.assertEqual(self.answers(w, "d"), ("0", "1", False))
        self.assertEqual(self.answers(w, "j"), ("1", "1", False))
        self.assertEqual(self.answers(w, "s"), ("1", "0", False))
        self.assertEqual(self.answers(w, "gone"), ("1", "1", False))
        self.assertEqual(self.answers(w, "missing"), ("", "", True))
        self.assertEqual(self.answers(w, "bad.txt"), ("", "", True))

    def test_the_recursive_rmdir_follows_a_link_as_the_real_one_does_sl23(self):
        for kind, target in (("dir", OUT), ("dir", None)):
            w = World(files={"a.txt"}, links={"j": (kind, target)}, outside={SECRET})
            w.rmdir(FOLDER + "\\j", True)
            self.assertEqual((w.links, w.outside), ({}, set() if target else {SECRET}))
        w = World(files={"a.txt"}, links={"j": junction()}, outside={SECRET})
        w.rmdir(FOLDER, True)
        self.assertEqual((w.links, w.files, w.outside), ({}, set(), set()))

    def test_the_plain_rmdir_and_the_win32_call_remove_a_directory_link_never_its_target_and_delete_removes_a_file_link_sl23(self):
        """MEASURED (GUEST7A, winev-run-afbbd3e1): a directory link goes with the plain RMDir or with RemoveDirectoryW and its target stays (full,
        empty or gone); Delete does nothing to a directory link and removes a file link; RMDir and RemoveDirectoryW leave a file link."""
        w = World(links={"j": junction(), "d": junction(), "s": ("file", REAL), "gone": ("dir", None)}, outside={SECRET, REAL})
        w.delete(FOLDER + "\\j")
        w.rmdir(FOLDER + "\\s", False)
        self.assertEqual(sorted(w.links), ["d", "gone", "j", "s"])
        w.rmdir(FOLDER + "\\j", False)
        w.rmdir(FOLDER + "\\gone", False)
        self.assertEqual((sorted(w.links), w.outside), (["d", "s"], {SECRET, REAL}))
        self.assertEqual(w.remove_directory(FOLDER + "\\s"), 0)  # a file link is not a directory
        self.assertEqual(w.remove_directory(FOLDER + "\\d"), 1)
        w.delete(FOLDER + "\\s")
        self.assertEqual((w.links, w.outside), ({}, {SECRET, REAL}))

    def test_a_link_held_by_an_open_handle_resists_the_plain_rmdir_and_the_win32_call_alike_sl23(self):
        w = World(links={"j": junction()}, outside={SECRET}, stuck_links={"j"})
        w.rmdir(FOLDER + "\\j", False)
        self.assertEqual((w.remove_directory(FOLDER + "\\j"), sorted(w.links), w.outside), (0, ["j"], {SECRET}))

    def test_the_win32_model_refuses_a_trailing_backslash_a_full_folder_and_a_stuck_link_sl23(self):
        w = World(files={"d\\f.txt"}, links={"j": junction()}, outside={SECRET}, stuck_links={"j"})
        with self.assertRaises(AssertionError):
            w.remove_directory(FOLDER + "\\j\\")
        self.assertEqual((w.remove_directory(FOLDER + "\\j"), w.remove_directory(FOLDER + "\\d"), w.remove_directory(FOLDER + "\\none")), (0, 0, 0))
        self.assertEqual((sorted(w.links), w.files, w.outside), (["j"], {"d\\f.txt"}, {SECRET}))

    def test_a_listing_below_a_link_shows_the_target_so_entering_one_is_visible_sl23(self):
        w = World(links={"j": junction()}, outside={SECRET})
        self.assertEqual(w.listing(FOLDER + "\\j\\*.*"), [".", "..", "secret.txt"])
        w.delete(FOLDER + "\\j\\secret.txt")
        self.assertEqual(w.outside, set())


def remove_in(world, rel, side, **registers):
    """remove(), on either copy of tree.nsh: side "un." is the uninstaller's copy, "" the plain-name copy for the install side."""
    n = Nsis(tree_text(side), world)
    n.v.update(registers)
    n.stack.append(rel)
    n.start(side + "Tree_Remove")
    return n


MINE = {"R0": "k0", "R1": "k1", "R2": "k2", "R4": "k4", "tree_depth": "7"}


class BothCopies:
    """What must hold in the uninstaller's copy (un.Tree_Remove) and in the plain-name copy (Tree_Remove) alike."""

    SIDE = ""

    def run_on(self, world, rel, **registers):
        return remove_in(world, rel, self.SIDE, **registers)

    def test_a_path_that_is_not_there_is_gone_and_nothing_is_deleted_or_changed_sl23f(self):
        """READ in FileFunc.nsh (GetFileAttributes sets the error flag for a missing path), not measured on Windows: missing means gone, 0."""
        for files in ({"program\\runner.exe"}, set()):
            w = World(files=files)
            n = self.run_on(w, "backup", **MINE)
            with self.subTest(files=files):
                self.assertEqual((n.v["2"], n.ops, w.files), ("0", [], files))
                self.assertEqual({k: n.v[k] for k in MINE}, MINE)

    def test_an_entry_that_exists_but_whose_flag_cannot_be_read_stays_a_leftover_sl23f(self):
        cases = ({"files": {"backup\\a.txt"}, "rel": "backup\\a.txt"}, {"files": {"backup\\a.txt"}, "rel": "backup"},
                 {"files": set(), "dirs": {"backup"}, "rel": "backup"})
        for c in cases:
            w = World(files=c["files"], dirs=c.get("dirs", ()), attr_errors={c["rel"]})
            n = self.run_on(w, c["rel"])
            with self.subTest(case=c):
                self.assertEqual((n.v["2"], n.ops), ("1", []))

    def test_a_directory_link_goes_by_the_win32_call_without_a_trailing_backslash_never_by_rmdir_sl23(self):
        w = World(files={"program\\x.txt"}, links={"program\\data": junction()}, outside={SECRET})
        n = self.run_on(w, "program")
        self.assertEqual((n.v["2"], w.links, w.files, w.outside), ("0", {}, set(), {SECRET}))
        self.assertEqual(n.ops, ["removedirectory program\\data", "delete program\\x.txt", "rmdir program"])
        self.assertNotIn("program\\data", w.listed)

    def test_a_link_that_cannot_be_removed_stays_a_leftover_and_is_never_entered_sl23(self):
        w = World(files={"program\\x.txt"}, links={"program\\data": junction()}, outside={SECRET}, stuck_links={"program\\data"})
        n = self.run_on(w, "program")
        self.assertEqual((n.v["2"], sorted(w.links), w.files, w.outside), ("1", ["program\\data"], set(), {SECRET}))
        self.assertEqual(n.ops[0], "removedirectory program\\data")
        self.assertNotIn("rmdir program\\data", n.ops)
        self.assertNotIn("program\\data", w.listed)

    def test_an_empty_path_and_a_path_ending_in_a_backslash_are_refused_and_touch_nothing_sl23(self):
        for rel in ("", "data\\", "program\\"):
            with self.subTest(rel=rel):
                w = World(files={"a.txt", "program\\x.txt"}, links={"data": junction()}, outside={SECRET})
                n = self.run_on(w, rel, **MINE)
                self.assertEqual((n.v["2"], n.ops, w.listed, w.files, sorted(w.links), w.outside),
                                 ("1", [], [], {"a.txt", "program\\x.txt"}, ["data"], {SECRET}))
                self.assertEqual({name: n.v[name] for name in MINE}, MINE)
                self.assertEqual(n.stack, [])

    def test_the_registers_r0_r1_r2_r4_and_the_depth_come_back_after_a_whole_walk_sl23(self):
        w = World(files=Registers.TREE, links={"program\\a\\ln": junction()}, outside={SECRET})
        n = self.run_on(w, "program", **MINE)
        self.assertEqual({name: n.v[name] for name in MINE}, MINE)
        self.assertEqual((n.v["2"], w.files, w.outside, n.stack), ("0", set(), {SECRET}, []))

    def test_a_subfolder_that_cannot_be_listed_is_a_leftover_and_nothing_below_it_is_touched_sl23(self):
        w = World(files={"program\\a\\x.txt", "program\\b.txt"}, list_errors={"program\\a"})
        n = self.run_on(w, "program")
        self.assertEqual((n.v["2"], w.files), ("1", {"program\\a\\x.txt"}))
        self.assertEqual(w.listed, ["program", "program\\a"])
        self.assertNotIn("delete program\\a\\x.txt", n.ops)

    def test_an_empty_real_folder_still_lists_its_dot_entries_and_is_removed_sl23(self):
        w = World(dirs={"program"})
        n = self.run_on(w, "program")
        self.assertEqual((n.v["2"], w.dirs, n.ops), ("0", set(), ["rmdir program"]))

    def test_the_walk_never_asks_about_a_dot_or_dotdot_entry_sl23(self):
        w = World(files=Registers.TREE, links={"program\\a\\ln": junction()}, outside={SECRET})
        n = self.run_on(w, "program")
        self.assertEqual((n.v["2"], w.files), ("0", set()))
        self.assertEqual([p for p in w.asked if {".", ".."} & set(p.split("\\"))], [])

    def test_an_entry_whose_flag_cannot_be_read_is_a_leftover_and_untouched_sl23(self):
        w = World(files={"program\\x.txt", "program\\y.txt"}, attr_errors={"program\\x.txt"})
        n = self.run_on(w, "program")
        self.assertEqual((n.v["2"], w.files), ("1", {"program\\x.txt"}))

    def test_every_failure_of_the_second_read_of_a_link_leaves_the_link_alone_and_unentered_sl23(self):
        """A link is read twice: REPARSE_POINT, then DIRECTORY, which picks RemoveDirectoryW or Delete. Each failure of the second read, on its own
        (an error, an empty answer, the true answer with the error flag set), is a leftover: nothing is asked to remove the link."""
        for label, link in (("directory link", ("dir", OUT)), ("file link", ("file", REAL))):
            for failure in ("attr_errors", "attr_blank", "attr_flagged"):
                with self.subTest(link=label, failure=failure):
                    w = World(links={"ln": link}, outside={SECRET, REAL}, **{failure: {("ln", "DIRECTORY")}})
                    n = self.run_on(w, "ln")
                    self.assertEqual((n.v["2"], n.ops, sorted(w.links), w.outside, w.listed), ("1", [], ["ln"], {SECRET, REAL}, []))

    def test_a_failing_directory_read_changes_nothing_for_a_real_folder_which_is_never_asked_for_it_sl23(self):
        w = World(files={"program\\x.txt"}, attr_errors={("program", "DIRECTORY")}, attr_flagged={("program\\x.txt", "DIRECTORY")})
        n = self.run_on(w, "program")
        self.assertEqual((n.v["2"], w.files), ("0", set()))

    def test_every_find_handle_is_closed_after_a_walk_sl23(self):
        w = World(files=Registers.TREE | {"program\\deep\\er\\f.txt"}, dirs={"program\\empty"}, links={"program\\a\\ln": junction()},
                  outside={SECRET})
        n = self.run_on(w, "program")
        self.assertEqual((n.v["2"], w.files, w.dirs), ("0", set(), set()))
        self.assertEqual(n.handles, 6)  # program, a, b, deep, er and empty were listed: the check below is not empty by accident
        self.assertEqual(n.open_handles, 0)


class UninstallerCopy(BothCopies, unittest.TestCase):
    SIDE = "un."


class InstallerCopy(BothCopies, unittest.TestCase):
    SIDE = ""


class FailClosedTopLevel(unittest.TestCase):
    """uninstall.nsh lists the product folder itself: an answer without a first name (not even "." or "..") is a failure, not an empty folder."""

    TREE = {"uninstall.exe", "program\\runner.exe", "config.toml"}

    def test_a_product_folder_that_cannot_be_listed_is_a_leftover_sl23(self):
        w = World(files=self.TREE, list_errors={""})
        n = clear(w)
        self.assertEqual((n.v["2"], w.files, n.ops), ("1", self.TREE, []))

    def test_the_whole_run_then_stops_with_40_after_five_retries_and_keeps_uninstall_exe_and_the_entry_sl23(self):
        w = World(files=self.TREE, list_errors={""})
        n, quit_ = files(w)
        self.assertEqual((quit_, n.errorlevel, n.keys, n.sleeps, w.files), (True, 40, [], [1000] * 5, self.TREE))

    def test_started_in_place_an_unlistable_folder_is_not_only_the_running_uninstaller_sl23(self):
        def world():
            return World(files=self.TREE, locked={"uninstall.exe"}, list_errors={""}, exedir=FOLDER, exefile="uninstall.exe")

        n = Nsis(UNINSTALL, world())
        n.start("un.Uninstall_OnlySelfLeft")
        self.assertEqual(n.v["2"], "0")
        n, quit_ = files(world())
        self.assertEqual((quit_, n.errorlevel, n.keys), (True, 40, []))


class TheDotEntries(unittest.TestCase):
    def test_the_model_resolves_dot_segments_and_refuses_to_climb_above_the_product_folder_sl23(self):
        w = World(files={"a\\x.txt"})
        self.assertEqual(w.rel(FOLDER + "\\a\\.\\..\\a"), "a")
        self.assertEqual(w.rel(FOLDER + "\\."), "")
        with self.assertRaises(Escaped):
            w.rel(FOLDER + "\\..")
        self.assertEqual(w.asked[-1], "..")

    def test_a_walk_that_never_ends_is_stopped_by_the_model_instead_of_hanging_the_suite_sl23(self):
        w = World()
        with self.assertRaises(Runaway):
            for _ in range(6000):
                w.rel(FOLDER + "\\.")

    def test_a_product_folder_walk_never_asks_about_a_dot_or_dotdot_entry_sl23(self):
        w = World(files={"uninstall.exe", "program\\runner.exe", "config.toml"}, links={"data": junction()}, outside={SECRET})
        n = clear(w)
        self.assertEqual((n.v["2"], w.files), ("0", {"uninstall.exe"}))
        self.assertEqual([p for p in w.asked if {".", ".."} & set(p.split("\\"))], [])


class Scanner(unittest.TestCase):
    def test_the_win32_directory_removal_is_a_path_write_and_any_other_system_call_is_an_exec_sl23(self):
        found = footprint.scan_nsis("System::Call 'kernel32::RemoveDirectoryW(w \"$APPDATA\\EcosystemRunner\\$R0\") i .s'")
        self.assertEqual([(f["kind"], f["target"]) for f in found], [("write", "$APPDATA\\EcosystemRunner\\$R0")])
        for call in ('kernel32::DeleteFileW(w "x") i .s', 'kernel32::RemoveDirectoryW(w "x") i .r1', 'kernel32::RemoveDirectoryW(w "x") i .r0',
                     'kernel32::RemoveDirectoryW(w "x") i .s ?e', 'kernel32::RemoveDirectoryW(w "x", i 1) i .s',
                     'user32::MessageBoxW(i 0, w "x", w "y", i 0)'):
            with self.subTest(call=call):
                self.assertEqual([f["kind"] for f in footprint.scan_nsis("System::Call '%s'" % call)], ["exec"])

    def test_tree_nsh_removes_a_link_only_through_that_one_call_sl23(self):
        walk = code((NSIS / "tree.nsh").read_text())
        self.assertEqual(len(re.findall(r"System::Call", walk)), 1)
        self.assertIn('kernel32::RemoveDirectoryW(w "${TREE_ROOT}\\$R0") i .s', walk)
        link_part = walk[walk.index("walk_link_dir:"):walk.index("walk_dir:")]
        self.assertNotRegex(link_part, r"(?i)\brmdir\b")


@unittest.skipUnless(shutil.which("makensis"), "makensis not installed: it is what expands includes, defines and macros")
class Preprocessed(unittest.TestCase):
    """The text the guard reads can hide a switch behind a define or a macro; makensis -PPO prints what it will really compile."""

    PROBE = """OutFile "probe.exe"
!macro Rm SW P
  RMDir ${SW} "${P}"
!macroend
!define SW /r
!define RM RMDir
Section
  RMDir /r "$TEMP\\a"
  rmdir  /R  "$TEMP\\b"
  RMDir /REBOOTOK /r "$TEMP\\c"
  RMDIR "/r" "$TEMP\\e"
  RMDir '/R' "$TEMP\\f"
  RMDir `/r` "$TEMP\\g"
  RMDir /* c */ /r "$TEMP\\i"
  /* a */ RMDir /r "$TEMP\\j"
  RMDir ${SW} "$TEMP\\l"
  ${RM} /r "$TEMP\\m"
  !insertmacro Rm /r "$TEMP\\n"
  nsExec::Exec 'cmd /c rd /s /q "$TEMP\\o"'
  ExecWait 'powershell -Command "Remove-Item -Recurse $TEMP\\p"'
SectionEnd
"""

    def expanded(self, cmd, cwd=None):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stdout[-400:] + r.stderr[-400:])
        return r.stdout

    def test_makensis_accepts_the_probe_spellings_and_the_guard_flags_each_one_after_expansion_sl23(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "probe.nsi").write_text(self.PROBE)
            text = self.expanded(["makensis", "-PPO", "probe.nsi"], cwd=d)
        flagged = unsafe_instructions(text)
        self.assertGreaterEqual(len(flagged), 13, text)

    def test_the_expanded_installer_and_the_expanded_guest_harness_have_nothing_unsafe_sl23(self):
        pins = json.loads((ROOT / "installer" / "pins.json").read_text())
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(NSIS, Path(d) / "nsis")
            main = self.expanded(["makensis", "-PPO", f"-DOUTFILE={d}/o.exe", str(Path(d) / "nsis" / "main.nsi")])
            cmd = pack.harness_command("makensis", pins, ROOT / "installer" / "guest" / "uninstall-harness.nsi", Path(d) / "h.exe")
            cmd.insert(1, "-PPO")
            harness = self.expanded(cmd)
        for name, text in (("main.nsi", main), ("uninstall-harness.nsi", harness)):
            with self.subTest(name):
                self.assertIn("RemoveDirectoryW", text)
                self.assertEqual(unsafe_instructions(text), [])


class Readme(unittest.TestCase):
    TREE = (NSIS / "tree.nsh").read_text()
    MODEL = (ROOT / "tests" / "test_installer_uninst.py").read_text()

    def test_the_readme_says_the_uninstaller_never_follows_a_link_and_what_a_leftover_link_means_sl23(self):
        for phrase in ("never follows a link", "junction", "symbolic link", "un.Tree_Remove", "exit code 40", "uninstall.exe", "by hand", "RemoveDirectoryW",
                       "trailing backslash", "MEASURED", "READ in the Microsoft documentation", "READ in the NSIS source",
                       "READ in the `System` plugin source", "proves nothing about links", "possible fallback only", "ASSUMED", "NOT observed"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, README)

    def test_no_text_says_a_trailing_backslash_makes_windows_resolve_a_link_or_that_the_guest_proof_is_still_to_come_sl23(self):
        """GUEST7A measured the opposite of the first claim (a trailing backslash changes nothing for RemoveDirectoryW); GUEST7A and GUEST7B proved the rest."""
        for name, text in (("README", README), ("tree.nsh", self.TREE), ("the model", self.MODEL)):
            flat = re.sub(r"\s*\n\s*(?:[;#]\s*)?", " ", text)
            with self.subTest(name):
                self.assertIsNone(re.search(r"resolves?\s+(?:a|the|any|every|each|all)\s+links?\b", flat))
                self.assertNotIn("is to prove them", flat)
                self.assertNotIn("GUEST6C", flat)

    def test_the_readme_table_of_guest_measurements_names_the_run_of_every_row_sl23(self):
        lines = README.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("Measured on a real Windows guest"))
        for word in ("Windows 11 Pro 26200", "NTFS", "NOT observed", "#129"):
            self.assertIn(word, lines[start])
        rows = []
        for line in lines[start + 1:]:
            if line.startswith("|"):
                rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
            elif rows:
                break
        self.assertEqual(rows[0], ["Label", "Run", "Case", "Result"])
        data = rows[2:]
        self.assertGreaterEqual(len(data), 12)
        runs = set()
        for row in data:
            with self.subTest(case=row[2][:50]):
                self.assertEqual(len(row), 4)
                self.assertEqual(row[0], "MEASURED")
                self.assertRegex(row[1], r"^`winev-run-[0-9a-f]{8}`$")
                runs.add(row[1].strip("`"))
        self.assertEqual(runs, {"winev-run-afbbd3e1", "winev-run-3f6fe4f2"})
        cases = " ".join(row[2] for row in data)
        for case in ("U1", "U2", "U2b", "U3", "U4", "U5", "U6", "U7", "U8", "U9"):
            self.assertRegex(cases, rf"\b{case}\b")


if __name__ == "__main__":
    unittest.main()
