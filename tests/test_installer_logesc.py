"""LOGESC-1 (#222): every steps.jsonl line written by log.nsh is valid JSON, whatever the step and command text.

The escape helper is run from the real log.nsh text by a small interpreter of the NSIS instructions it uses, so the
mutants below are edits of that text, not of a Python copy.
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NSIS = ROOT / "installer" / "nsis"
LOG = (NSIS / "log.nsh").read_text()
HARNESS = (ROOT / "installer" / "guest" / "log-harness.nsi").read_text()
GUEST_PROOF = (ROOT / "installer" / "guest" / "guest-proof.ps1").read_text()
NSIS_MAX_STRLEN = 1024
REGISTERS = [f"${i}" for i in range(10)] + [f"$R{i}" for i in range(10)]
SAMPLES = ['A"B', "A\\Q", 'A\\"B', "tab\there", "cr\rlf\n", "", "plain-step", "caf\u00e9 \u20ac soft\u00adhyphen zero\u200bwidth",
           "".join(chr(c) for c in range(1, 32)), '/A"B=1', "C:\\X\\g7a\\steps.jsonl"]


def section(text, start, end):
    s = text.index(start)
    return text[s:text.index(end, s) + len(end)]


def tokens(line):
    out, cur, quote, started = [], "", None, False
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur += ch
        elif ch in "'\"`":
            quote, started = ch, True
        elif ch in ";#" and not started and not cur:
            break
        elif ch.isspace():
            if started or cur:
                out.append(cur)
            cur, started = "", False
        else:
            cur += ch
    if started or cur:
        out.append(cur)
    return out


class Machine:
    """The NSIS instructions LogJsonEscape uses, with NSIS v3 semantics (docs/Commands/*.md)."""

    def __init__(self, function_text):
        self.code, self.labels = [], {}
        for raw in function_text.splitlines()[1:-1]:
            t = tokens(raw.strip())
            if not t:
                continue
            if len(t) == 1 and t[0].endswith(":"):
                self.labels[t[0][:-1]] = len(self.code)
            else:
                self.code.append(t)
        self.regs = {r: "" for r in REGISTERS}
        self.stack = []

    def value(self, word):
        word = re.sub(r"\$\\([trn])", lambda m: {"t": "\t", "r": "\r", "n": "\n"}[m.group(1)], word)
        return re.sub(r"\$(R?[0-9])", lambda m: self.regs["$" + m.group(1)], word)

    def jump(self, pc, target):
        if target in ("", "0"):
            return pc + 1
        if target[0] in "+-":
            return pc + int(target)
        return self.labels[target]

    def call(self, arg):
        self.stack.append(arg)
        pc, steps = 0, 0
        while pc < len(self.code):
            steps += 1
            if steps > 200000:
                raise AssertionError("LogJsonEscape does not terminate")
            op, *a = self.code[pc]
            a += [""] * (5 - len(a))
            nxt = pc + 1
            if op == "Exch":
                self.stack[-1], self.regs[a[0]] = self.regs[a[0]], self.stack[-1]
            elif op == "Push":
                self.stack.append(self.value(a[0]))
            elif op == "Pop":
                self.regs[a[0]] = self.stack.pop()
            elif op == "StrCpy":
                s = self.value(a[1])
                if a[3]:
                    off = int(self.value(a[3]))
                    s = s[off:] if off >= 0 else s[len(s) + off:]
                if a[2]:
                    n = int(self.value(a[2]))
                    s = s[:n] if n >= 0 else s[:len(s) + n]
                self.regs[a[0]] = s
            elif op == "StrLen":
                self.regs[a[0]] = str(len(self.value(a[1])))
            elif op == "IntOp":
                x, y = int(self.value(a[1])), int(self.value(a[3]))
                self.regs[a[0]] = str({"+": x + y, "-": x - y, "*": x * y}[a[2]])
            elif op == "IntCmp":
                x, y = int(self.value(a[0])), int(self.value(a[1]))
                nxt = self.jump(pc, a[2] if x == y else a[3] if x < y else a[4])
            elif op in ("StrCmp", "StrCmpS"):
                x, y = self.value(a[0]), self.value(a[1])
                same = x == y if op == "StrCmpS" else x.lower() == y.lower()
                nxt = self.jump(pc, a[2] if same else a[3])
            elif op == "IntFmt":
                self.regs[a[0]] = self.value(a[1]) % int(self.value(a[2]))
            elif op == "Goto":
                nxt = self.jump(pc, a[0])
            else:
                raise AssertionError(f"instruction not modelled: {op}")
            pc = nxt
        return self.stack.pop()


def escaper(log_text):
    machine = Machine(section(log_text, "Function LogJsonEscape", "FunctionEnd"))
    return machine.call, machine


def chunk_sizes(log_text):
    macro = section(log_text, "!macro LogWriteField", "!macroend")
    take = re.search(r"StrCpy \$LogT1 \$\{var\} (\d+)", macro)
    drop = re.search(r'StrCpy \$\{var\} \$\{var\} "" (\d+)', macro)
    return int(take.group(1)), int(drop.group(1))


def step_line(log_text, step, command):
    """The line LogStep writes, built from its write_line instructions; each LogWriteField runs the real helper."""
    esc, _ = escaper(log_text)
    take, drop = chunk_sizes(log_text)
    fields = {"$LogStepName": step, "$LogCommand": command}
    sample = {"$LogExit": "31", "$LogY": "2026", "$LogMo": "11", "$LogD": "23", "$LogH": "01", "$LogMi": "02",
              "$LogS": "03", "$LogZone": "W. Europe Standard Time"}
    body = log_text[log_text.index("  write_line:", log_text.index("Function LogStep")):]
    body = body[:body.index("FileClose $LogHandle")]
    out = ""
    for raw in body.splitlines()[1:]:
        t = tokens(raw.strip())
        if t[:2] == ["!insertmacro", "LogWriteField"]:
            rest = fields[t[2]]
            while True:
                out += esc(rest[:take])
                rest = rest[drop:]
                if not rest:
                    break
        elif t[:2] == ["FileWrite", "$LogHandle"]:
            text = t[2].replace("$\\r$\\n", "\r\n")
            for name in sorted({**sample, **fields}, key=len, reverse=True):
                text = text.replace(name, {**sample, **fields}[name])
            out += text
    return out


class EscapeHelper(unittest.TestCase):
    def test_every_sample_round_trips_through_json(self):
        esc, _ = escaper(LOG)
        for s in SAMPLES:
            with self.subTest(s=s):
                out = esc(s)
                self.assertEqual(json.loads('"' + out + '"'), s)
                self.assertTrue(all(ord(c) >= 32 for c in out))

    def test_text_without_specials_is_written_unchanged(self):
        esc, _ = escaper(LOG)
        for s in ("plain-step", "sc.exe create", "caf\u00e9 \u20ac", "FileWrite licence-record.json", ""):
            self.assertEqual(esc(s), s)

    def test_specials_use_the_short_json_escapes_and_other_controls_use_u00XX(self):
        esc, _ = escaper(LOG)
        self.assertEqual(esc('\\"\t\r\n'), '\\\\\\"\\t\\r\\n')
        self.assertEqual(esc("\x01\x1f"), "\\u0001\\u001F")

    def test_the_helper_restores_every_register_it_uses(self):
        esc, machine = escaper(LOG)
        for i, r in enumerate(REGISTERS):
            machine.regs[r] = f"keep{i}"
        before = dict(machine.regs)
        esc('A"B\x01')
        self.assertEqual(machine.regs, before)
        self.assertEqual(machine.stack, [])

    def test_the_helper_compares_exactly(self):
        """StrCmp is case-insensitive (lstrcmpi); only StrCmpS compares code units."""
        helper = section(LOG, "Function LogJsonEscape", "FunctionEnd")
        self.assertNotRegex(helper, r"\bStrCmp\b")
        self.assertIn("StrCmpS", helper)


class StepLine(unittest.TestCase):
    def test_both_fields_go_through_the_helper_and_the_line_is_json(self):
        for step in SAMPLES:
            for command in ("A\\Q", 'q"q', "plain"):
                with self.subTest(step=step, command=command):
                    line = step_line(LOG, step, command)
                    self.assertTrue(line.endswith("\r\n"))
                    record = json.loads(line)
                    self.assertEqual((record["step"], record["command"], record["exit_code"]), (step, command, 31))

    def test_a_long_field_is_written_in_chunks_that_fit_the_nsis_string_buffer(self):
        take, drop = chunk_sizes(LOG)
        self.assertEqual(take, drop)
        self.assertLess(take * len("\\u001F"), NSIS_MAX_STRLEN)
        long = ('x"\\\x01' * 200)[:777]
        self.assertEqual(json.loads(step_line(LOG, long, long))["command"], long)

    def test_no_write_carries_a_raw_field(self):
        body = section(LOG, "Function LogStep", "FunctionEnd")
        for line in body.splitlines():
            if "FileWrite" in line:
                self.assertNotIn("$LogStepName", line)
                self.assertNotIn("$LogCommand", line)

    def test_every_constant_caller_writes_the_same_bytes_as_before(self):
        esc, _ = escaper(LOG)
        sources = sorted(NSIS.glob("*.nsh")) + [ROOT / "installer" / "guest" / "log-harness.nsi"]
        calls = 0
        for path in sources:
            lines = path.read_text().splitlines()
            for i, line in enumerate(lines):
                if line.strip() != "Call LogStep":
                    continue
                calls += 1
                for push in lines[max(0, i - 3):i - 1]:
                    t = tokens(push.strip())
                    if t[:1] == ["Push"] and "$" not in t[1]:
                        with self.subTest(path=path.name, line=i + 1, value=t[1]):
                            self.assertEqual(esc(t[1]), t[1])
        self.assertGreaterEqual(calls, 25)

    def test_the_unknown_key_block_still_logs_the_key_as_typed_and_the_line_is_json(self):
        screens = (NSIS / "screens.nsh").read_text()
        self.assertEqual(screens.count('Push "unknown-key"\n        Push "$vs_name"\n        Push "31"\n        Call LogStep\n'), 1)
        for key in ('A"B', "A\\Q", "FOO", 'A\\"\tB'):
            with self.subTest(key=key):
                record = json.loads(step_line(LOG, "unknown-key", key))
                self.assertEqual((record["step"], record["command"], record["exit_code"]), ("unknown-key", key, 31))

    def test_the_shared_interpreter_runs_the_real_logstep_to_the_same_json(self):
        """Cross-check with tests/nsis_interp.py, which runs the whole LogStep (open, seek, write, close) independently."""
        from tests.test_installer_docfix import LOG as MACHINE_LOG, AuditWorld
        w = AuditWorld(files={MACHINE_LOG: ""}, admin=False, silent=False)
        w.call(".onInit")
        w.var["APPDATA"] = r"C:\ProgramData"
        cases = [('A"B', "A\\Q"), ("unknown-key", 'A\\"\tB\x01'), ("plain", "")]
        for step, command in cases:
            w.stack.extend([step, command, "31"])
            w.call("LogStep")
        records = [json.loads(s) for s in w.files[MACHINE_LOG].splitlines()[-len(cases):]]
        self.assertEqual([(r["step"], r["command"], r["exit_code"]) for r in records], [(s, c, 31) for s, c in cases])

    def test_the_harness_line_and_the_guest_check_agree(self):
        self.assertIn("StrCpy $0 'A\"B'", HARNESS)
        self.assertIn("StrCpy $1 'A\\Q'", HARNESS)
        self.assertIn("$records[2].step -ceq 'A\"B' -and $records[2].command -ceq 'A\\Q'", GUEST_PROOF)
        self.assertIn("$lines.Count -eq 3", GUEST_PROOF)


class Mutants(unittest.TestCase):
    """Each edit of log.nsh must make at least one check fail."""

    def killed(self, old, new):
        self.assertEqual(LOG.count(old), 1, old)
        text = LOG.replace(old, new)
        failures = 0
        try:
            esc, machine = escaper(text)
            for s in SAMPLES:
                try:
                    out = esc(s)
                    if json.loads('"' + out + '"') != s or machine.stack:
                        failures += 1
                except (ValueError, AssertionError, IndexError, KeyError):
                    failures += 1
            esc, machine = escaper(text)
            machine.regs["$R0"] = "keep"
            esc("x")
            failures += machine.regs["$R0"] != "keep"
            for s in SAMPLES:
                try:
                    failures += json.loads(step_line(text, s, s))["command"] != s
                except (ValueError, AssertionError, IndexError, KeyError):
                    failures += 1
            take, drop = chunk_sizes(text)
            failures += take != drop
            failures += bool(re.search(r"\bStrCmp\b", section(text, "Function LogJsonEscape", "FunctionEnd")))
        except (ValueError, AssertionError, IndexError, KeyError):
            failures += 1
        self.assertGreater(failures, 0, f"mutant survived: {old!r} -> {new!r}")

    def test_backslash_not_doubled(self):
        self.killed("StrCpy $4 '\\\\'", "StrCpy $4 '\\'")

    def test_quote_not_escaped(self):
        self.killed("StrCpy $4 '\\\"'", "StrCpy $4 '\"'")

    def test_tab_written_raw(self):
        self.killed("StrCpy $4 '\\t'", 'StrCpy $4 "$\\t"')

    def test_other_controls_written_raw(self):
        self.killed("IntCmp $5 32 append control", "Goto append")

    def test_register_not_restored(self):
        self.killed("  Pop $R0\n", "")

    def test_case_insensitive_compare(self):
        self.killed("StrCmpS $4 '\"'", "StrCmp $4 '\"'")

    def test_command_written_raw(self):
        self.killed("!insertmacro LogWriteField $LogCommand", "FileWrite $LogHandle $LogCommand")

    def test_step_written_raw(self):
        self.killed("!insertmacro LogWriteField $LogStepName", "FileWrite $LogHandle $LogStepName")

    def test_chunk_drop_differs_from_chunk_take(self):
        self.killed('StrCpy ${var} ${var} "" 128', 'StrCpy ${var} ${var} "" 127')



class HarnessBuild(unittest.TestCase):
    @unittest.skipUnless(shutil.which("makensis"), "makensis absent")
    def test_the_log_harness_compiles_with_the_pinned_flags(self):
        """log.nsh uses LogicLib in LogWriteField, so it must include LogicLib itself for log-harness.nsi."""
        from installer.guest import pack
        pins = json.loads((ROOT / "installer" / "pins.json").read_text())
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "log-harness.exe"
            cmd = pack.harness_command("makensis", pins, ROOT / "installer" / "guest" / "log-harness.nsi", out)
            r = subprocess.run(cmd, cwd=d, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
