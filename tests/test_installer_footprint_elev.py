"""FOOTPRINT-ELEV (#203): Elevate_Raise may execute its one exact relaunch line and nothing else (INST-REQ-029, 030).

Every test changes a copy of the REAL installer sources in memory and runs the footprint scanner over all of them.
"""
import re
import unittest

from installer import footprint as fpm

RAISE = 'ExecShell "runas" "$EXEPATH" "$carry_args"'


def real_sources():
    return fpm.collect_sources()


def insert_after(sources, name, anchor, line):
    """A copy of `sources` whose file `name` holds `line` right after its one `anchor` line, and that line's number."""
    lines = sources[name].splitlines(keepends=True)
    hits = [i for i, raw in enumerate(lines) if raw.rstrip("\r\n") == anchor]
    assert len(hits) == 1, (name, anchor, hits)
    lines.insert(hits[0] + 1, "  " + line + "\n")
    return {**sources, name: "".join(lines)}, hits[0] + 2


def replace_line(sources, name, old, new):
    """A copy of `sources` whose file `name` has its one line `old` (stripped) rewritten as `new`, and its number."""
    lines = sources[name].splitlines(keepends=True)
    hits = [i for i, raw in enumerate(lines) if raw.strip() == old]
    assert len(hits) == 1, (name, old, hits)
    lines[hits[0]] = lines[hits[0]].replace(old, new)
    return {**sources, name: "".join(lines)}, hits[0] + 1


class ElevateRaiseExecIsExact(unittest.TestCase):
    def exec_findings(self, sources, name, number):
        return [b for b in fpm.check_source(sources)
                if re.fullmatch(rf"{re.escape(name)}:{number}: command execution .+ is outside the footprint", b)]

    def assertOnlyExecFinding(self, sources, number):
        """The one violation is the command execution at elevate.nsh:number, a line inside Elevate_Raise."""
        found = [f for f in fpm.scan_nsis(sources["elevate.nsh"]) if f["line"] == number and f["kind"] == "exec"]
        self.assertEqual([f["function"] for f in found], ["Elevate_Raise"])
        bad = fpm.check_source(sources)
        self.assertEqual(len(bad), 1, bad)
        self.assertEqual(self.exec_findings(sources, "elevate.nsh", number), bad)

    def test_real_sources_pass_with_the_one_exact_exec(self):
        """POSITIVE: the unmodified sources pass, and the only exec in elevate.nsh is the listed line in Elevate_Raise."""
        sources = real_sources()
        self.assertEqual(fpm.check_source(sources), [])
        self.assertEqual(fpm.ELEVATE_RAISE_OPERATIONS, frozenset((RAISE,)))
        lines = sources["elevate.nsh"].splitlines()
        execs = [f for f in fpm.scan_nsis(sources["elevate.nsh"]) if f["kind"] == "exec"]
        self.assertEqual([(f["function"], lines[f["line"] - 1].strip()) for f in execs], [("Elevate_Raise", RAISE)])

    def test_secure_create_instruction_in_elevate_raise_is_reported(self):
        """NEGATIVE (REV191 D5): the create instructions exempt only in winsys.nsh Winsys_FolderCreate are reported here."""
        for line in sorted(fpm.SECURE_CREATE_OPERATIONS):
            with self.subTest(line=line):
                sources, number = insert_after(real_sources(), "elevate.nsh", "Function Elevate_Raise", line)
                self.assertOnlyExecFinding(sources, number)

    def test_other_commands_in_elevate_raise_are_reported(self):
        """NEGATIVE: an extra ExecShell, nsExec, ExecWait or Exec line next to the relaunch is reported."""
        for line in ('ExecShell "open" "$EXEPATH"', "nsExec::Exec 'cmd'", "ExecWait 'cmd'", 'Exec "$EXEPATH"'):
            with self.subTest(line=line):
                sources, number = insert_after(real_sources(), "elevate.nsh", "Function Elevate_Raise", line)
                self.assertOnlyExecFinding(sources, number)

    def test_relaunch_with_other_arguments_is_reported(self):
        """NEGATIVE: the runas line itself with other arguments, another program or another opcode is reported."""
        for line in ('ExecShell "runas" "$EXEPATH" "$carry_args /X"', 'ExecShell "runas" "$EXEPATH"',
                     'ExecShell "runas" "$SYSDIR\\cmd.exe" "$carry_args"', 'ExecShellWait "runas" "$EXEPATH" "$carry_args"'):
            with self.subTest(line=line):
                sources, number = replace_line(real_sources(), "elevate.nsh", RAISE, line)
                self.assertOnlyExecFinding(sources, number)

    def test_exact_relaunch_line_is_exempt_only_in_elevate_raise_of_elevate_nsh(self):
        """The literal is scoped: the same line in another function, or in Elevate_Raise of another file, is reported."""
        sources, number = insert_after(real_sources(), "elevate.nsh", "Function Carry_Begin", RAISE)
        self.assertEqual(len(self.exec_findings(sources, "elevate.nsh", number)), 1)
        sources = {**real_sources(), "other.nsh": f"Function Elevate_Raise\n  {RAISE}\nFunctionEnd\n"}
        self.assertEqual(self.exec_findings(sources, "other.nsh", 2), fpm.check_source(sources))
        self.assertEqual(len(fpm.check_source(sources)), 1)


if __name__ == "__main__":
    unittest.main()
