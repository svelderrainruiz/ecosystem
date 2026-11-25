"""VM-1 (#137): the hand-test kit for the interactive installer.

installer/VM-TEST.md is the checklist the operator follows in a Windows VM; installer/guest/vm-state.ps1 is the read-only report it runs.
Nothing here starts the installer. These tests hold the document to the code it quotes, so a renamed page, a changed exit code, size or
function fails here and not in front of the operator. What nobody has seen on Windows stays tagged READ; only a guest case that passed is MEASURED.
"""
import getpass
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_installer_sl16e import PROBE, PROBE_P

ROOT = Path(__file__).resolve().parent.parent
INST = ROOT / "installer"
NSIS = INST / "nsis"
PS1_PATH = INST / "guest" / "vm-state.ps1"


def text_of(path):
    return Path(path).read_text(encoding="utf-8")


DOC = text_of(INST / "VM-TEST.md")
PS1 = text_of(PS1_PATH)
STEPS = [(int(n), body) for n, body in re.findall(r"^- \*\*T(\d+)\*\* (.*)$", DOC, re.M)]
PART_AB = DOC[DOC.index("## Part A"):DOC.index("\n---\n")]
BLOCK = next(b for b in re.findall(r"```powershell\n(.*?)```", DOC, re.S) if "$rows" in b)


def prose(text):
    """The document without its fenced blocks."""
    return re.sub(r"```.*?```", "", text, flags=re.S)


def prose_quotes(text):
    """The double-quoted strings of the prose; a backtick code span is a command or a typed value, not an on-screen text."""
    return re.findall(r'"([^"\n]+)"', re.sub(r"`[^`\n]*`", "", prose(text)))


def function_body(text, name):
    m = re.search(r"^Function %s\n(.*?)^FunctionEnd" % re.escape(name), text, re.M | re.S)
    return m.group(1) if m else ""


def defined(path, name):
    """A function or macro of an NSIS file, a key of a JSON file, or the name in any other file."""
    text = text_of(path)
    if path.suffix in (".nsh", ".nsi"):
        return re.search(r"^(Function|!macro) %s\b" % re.escape(name), text, re.M) is not None
    if path.suffix == ".json":
        return re.search(r'"%s"\s*:' % re.escape(name), text) is not None
    return name in text


def nsis_bytes(literal, version, mode="local"):
    """The bytes of a FileWrite literal: the version and mode filled in, $\\r$\\n as two bytes and $\\n as one."""
    text = literal.replace("${INSTALLER_VERSION}", version).replace("$runner_mode", mode)
    return len(text.replace("$\\r$\\n", "\r\n").replace("$\\n", "\n").encode("ascii"))


def pwsh_parse(path):
    cmd = "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e);if($e){$e|%%{$_.Message};exit 1}" % path
    return subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120)


INSTALL = text_of(NSIS / "install.nsh")
ELEVATE = text_of(NSIS / "elevate.nsh")
SCREENS = text_of(NSIS / "screens.nsh")
MAIN = text_of(NSIS / "main.nsi")
ALL_NSIS = "\n".join(text_of(p) for p in sorted(NSIS.glob("*.nsh")))
# A person sees only what installer/nsis holds: schema.json, the README and build.py are not on a screen.
NSIS_TEXT = ALL_NSIS + "\n" + MAIN
FUNCTIONS = dict(re.findall(r"^Function (\S+)\n(.*?)^FunctionEnd", NSIS_TEXT, re.M | re.S))
# A refusal box "<label>: $R9." and the Check_* function whose call left the reason in $R9.
COMPOSED = re.findall(r'Call (\w+)\s+\$\{If\} \$R9 != ""\s+MessageBox [^\n"]*"([^"\n]*?): \$R9\."', NSIS_TEXT)
# The carry_bad box has the label of the refused answer in place of the variable.
CARRY_LABELS = re.findall(r'Push "([^"]+)"\s+Push "/\w+="', function_body(SCREENS, "Carry_Answers"))
EXPANDED = "\n".join(NSIS_TEXT.replace("$carry_bad", label) for label in CARRY_LABELS)


def reasons(name, seen=()):
    """Every text that a function, or a function it calls, puts in $R9."""
    found = set(re.findall(r'StrCpy \$R9 "([^"]*)"', FUNCTIONS.get(name, "")))
    for callee in set(re.findall(r"Call (\w+)", FUNCTIONS.get(name, ""))) - set(seen) - {name}:
        found |= reasons(callee, seen + (name,))
    return found


HELP = {"Page_" + p["id"]: p["help"] for p in json.loads(text_of(INST / "schema.json"))["pages"] if "help" in p}
# The signer page (INST-REQ-103) is written in trust.nsh, not generated: its help text is its first label there.
HELP["Page_signer"] = re.search(r'^Function Page_signer\n.*?\$\{NSD_CreateLabel\} 0u 0u 100% 20u "([^"]+)"', text_of(NSIS / "trust.nsh"), re.M | re.S).group(1)


def first_field(page):
    """The text of the first control a page function creates after its help text (issue 329). A page has no heading, so this is what names it."""
    texts = re.findall(r'\$\{NSD_Create\w+\}[^\n"]*"([^"\n]*)"', FUNCTIONS[page])
    if page in HELP:
        assert texts[0] == HELP[page], page
        texts = texts[1:]
    return texts[0]


# What vm-state.ps1 uses, and so all it may use: it only reads. Anything outside these sets fails, aliases included (gc, ri, iex, ...).
ALLOWED = {
    "keywords": {"param", "function", "if", "elseif", "else", "foreach", "in", "switch", "default", "trap", "try", "catch", "exit",
                 "ValidatePattern", "SilentlyContinue", "Latest"},
    "commands": {"Set-StrictMode", "Write-Output", "Get-CimInstance", "Join-Path", "Get-Item", "Get-Acl", "ForEach-Object", "Sort-Object",
                 "Get-ChildItem", "Where-Object", "Get-Service"},
    "functions": {"Say", "YesNo", "Who"},
    "arguments": {"Win32_OperatingSystem"},
    "types": {"string", "Security.Principal.SecurityIdentifier", "Security.Principal.WindowsPrincipal", "Security.Principal.WindowsIdentity",
              "Security.Principal.WindowsBuiltInRole", "Microsoft.Win32.RegistryKey"},
    "statics": {"GetCurrent", "Administrator", "OpenBaseKey"},
    "methods": {"Translate", "IsInRole", "OpenSubKey", "GetValueNames", "GetValue", "Close", "ToString", "GetType"},
    "properties": {"Name", "Length", "Value", "Status", "PSIsContainer", "OSArchitecture", "Exception", "Count", "Caption", "BuildNumber", "Attributes",
                   "AreAccessRulesProtected", "Access", "IdentityReference"},
    "parameters": {"Version", "f", "LiteralPath", "Force", "ErrorAction", "ClassName", "Name", "Unique", "Regex", "match", "ceq", "notcontains", "join",
                   "not"},
}


def ps_code(text):
    """The code of a PowerShell script: comments dropped, every single-quoted string reduced to '' (a doubled quote stays inside it)."""
    out, i = [], 0
    while i < len(text):
        if text[i] == "'":
            i += 1
            while i < len(text) and not (text[i] == "'" and text[i + 1:i + 2] != "'"):
                i += 2 if text[i] == "'" else 1
            out.append("''")
            i += 1
        elif text[i] == "#":
            while i < len(text) and text[i] != "\n":
                i += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


# Every assignment operator: = += -= *= /= %= ??= (and not the comparison ==).
PS_ASSIGN = r"(?:[-+*/%]|\?\?)?=(?!=)"
# A qualifier that names a scope or the variable: drive; any other one ($env:, $c:, $temp:, ...) is a provider path.
PS_SCOPES = {"global", "local", "script", "private", "using", "variable"}


def ps_inventory(text):
    """The words, types, members and parameters in the code of a script, and the constructs no allow-list could cover."""
    code = ps_code(text)
    problems = [what for what, hit in (
        ("block comment", "<#" in text), ("here-string", "@'" in text or '@"' in text), ("double-quoted string", '"' in code),
        ("backtick", "`" in code), ("call operator", "&" in code), ("redirection", ">" in code),
        ("alias symbol % or ?", re.search(r"[%?]", code) is not None),
        ("dot-source", re.search(r"(?m)(?:^|[;{(|])\s*\.\s", code) is not None),
        ("dynamic member", re.search(r"(?:\.|::)\s*['$(]", code) is not None),
        ("write to a member", re.search(r"(?:\.|::)\s*\w+\s*%s" % PS_ASSIGN, code) is not None),
        ("increment or decrement", re.search(r"\+\+|--", code) is not None),
        ("braced variable name", "${" in code),
        ("write to a drive variable", any(drive.lower() not in PS_SCOPES for drive in re.findall(r"\$(\w+):[\w:]*\s*%s" % PS_ASSIGN, code))),
        ("ForEach-Object or Where-Object without a script block", re.search(r"(?i)\b(?:ForEach-Object|Where-Object)\b(?!\s*\{)", code) is not None),
        ("foreach or where as a pipeline command", re.search(r"(?i)\|\s*(?:foreach|where)(?![\w-])", code) is not None)) if hit]
    types = set(re.findall(r"\[([A-Za-z][\w.]*)\]", code))
    rest = re.sub(r"\[([A-Za-z][\w.]*)\]", " ", code)
    statics = set(re.findall(r"::(\w+)", rest))
    methods = set(re.findall(r"\.(\w+)\s*\(", rest))
    properties = set(re.findall(r"\.(\w+)(?!\w)(?!\s*\()", rest))
    rest = re.sub(r"\$\{?[\w:]+\}?", " ", re.sub(r"::\w+|\.\w+", " ", rest))
    parameters = set(re.findall(r"(?<![\w$])-([A-Za-z]+)\b", rest))
    rest = re.sub(r"(?<![\w$])-[A-Za-z]+\b", " ", rest)
    return {"problems": problems, "types": types, "statics": statics, "methods": methods, "properties": properties, "parameters": parameters,
            "words": set(re.findall(r"[A-Za-z_][\w-]*", rest))}


def ps_outside(text):
    """What a script uses beyond the allow-list; empty when it is inside."""
    found = ps_inventory(text)
    outside = list(found["problems"])
    for kind, allowed in (("words", ALLOWED["keywords"] | ALLOWED["commands"] | ALLOWED["functions"] | ALLOWED["arguments"]), ("types", ALLOWED["types"]),
                          ("statics", ALLOWED["statics"]), ("methods", ALLOWED["methods"]), ("properties", ALLOWED["properties"]),
                          ("parameters", ALLOWED["parameters"])):
        outside += ["%s: %s" % (kind, name) for name in sorted(found[kind] - allowed)]
    return outside


# What the parser sees, whatever the spelling: a member is a constant name or it is dynamic, and a pipeline block is one script block.
AST_DUMP = """
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:AST_FILE, [ref]$null, [ref]$null)
$members = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.MemberExpressionAst] }, $true) | ForEach-Object {
    $constant = $_.Member -is [System.Management.Automation.Language.StringConstantExpressionAst]
    [pscustomobject]@{ invoke = ($_ -is [System.Management.Automation.Language.InvokeMemberExpressionAst]); static = [bool]$_.Static
                       constant = $constant; name = $(if ($constant) { $_.Member.Value } else { $_.Member.Extent.Text }) } })
$blocks = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -in 'ForEach-Object', 'Where-Object' }, $true) |
    ForEach-Object { [pscustomobject]@{ name = $_.GetCommandName(); args = @($_.CommandElements | Select-Object -Skip 1 | ForEach-Object { $_.GetType().Name }) } })
$writes = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -or
        ($n -is [System.Management.Automation.Language.UnaryExpressionAst] -and $n.TokenKind -in 'PlusPlus', 'MinusMinus', 'PostfixPlusPlus', 'PostfixMinusMinus') }, $true) |
    ForEach-Object {
        $target = $(if ($_ -is [System.Management.Automation.Language.AssignmentStatementAst]) { $_.Left } else { $_.Child })
        while ($target -is [System.Management.Automation.Language.AttributedExpressionAst]) { $target = $target.Child }
        $isVariable = $target -is [System.Management.Automation.Language.VariableExpressionAst]
        [pscustomobject]@{ text = $_.Extent.Text; target = $target.GetType().Name; drive = $(if ($isVariable) { $target.VariablePath.DriveName } else { $null }) } })
[pscustomobject]@{ members = $members; blocks = $blocks; writes = $writes } | ConvertTo-Json -Depth 5 -Compress
"""


def ast_found(path):
    r = subprocess.run(["pwsh", "-NoProfile", "-Command", AST_DUMP], capture_output=True, text=True, timeout=120, env=dict(os.environ, AST_FILE=str(path)))
    if r.returncode:
        raise RuntimeError(r.stdout + r.stderr)
    return json.loads(r.stdout)


def ast_outside(found):
    """What the AST of a script shows beyond the allow-list; empty when it is inside."""
    outside = []
    for m in found["members"]:
        allowed = ALLOWED["statics"] if m["static"] else ALLOWED["methods"] if m["invoke"] else ALLOWED["properties"]
        if not m["constant"] or m["name"] not in allowed:
            outside.append("member: %s" % m["name"])
    # A write may only set a plain variable: a member target of any shape, an index, a list or a provider path ($env:X, ${c:x}) is refused.
    for w in found["writes"]:
        if w["target"] != "VariableExpressionAst":
            outside.append("write to a %s: %s" % (w["target"], w["text"]))
        elif (w["drive"] or "variable").lower() != "variable":
            outside.append("write to the drive %s: %s" % (w["drive"], w["text"]))
    return outside + ["%s without exactly one script block" % b["name"] for b in found["blocks"] if b["args"] != ["ScriptBlockExpressionAst"]]


class StepTests(unittest.TestCase):
    def test_step_ids_are_unique_and_ascending_from_one(self):
        ids = [n for n, _ in STEPS]
        self.assertGreaterEqual(len(ids), 20)
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_parts_a_and_b_are_one_line_per_step_and_at_most_90_lines(self):
        lines = [l for l in PART_AB.splitlines() if l.strip()]
        for line in lines:
            self.assertTrue(line.startswith("- **T") or line.startswith("## "), line[:60])
        self.assertLessEqual(len(lines), 90)

    def test_every_step_is_tagged_read_or_measured(self):
        for n, body in STEPS:
            self.assertRegex(body, r"\b(READ|MEASURED)\b", "T%d" % n)

    def test_a_measured_tag_names_a_guest_case_that_passed(self):
        """Only a guest case that ended PASS makes a step MEASURED; everything else stays READ."""
        proof = text_of(INST / "guest" / "guest-proof.ps1")
        cited = 0
        for n, body in STEPS:
            cases = re.findall(r"guest case ([A-Za-z0-9-]+)", body)
            if "MEASURED" in body:
                self.assertTrue(cases, "T%d is MEASURED without a guest case" % n)
            for case in cases:
                cited += 1
                self.assertIn("Res '%s' 'PASS'" % case, proof, case)
        self.assertGreaterEqual(cited, 3)

    def test_a_vm_state_call_uses_the_id_of_its_own_step(self):
        pattern = re.search(r"ValidatePattern\('([^']+)'\)", PS1).group(1)
        calls = 0
        for n, body in STEPS:
            for label in re.findall(r"vm-state\.ps1 -Step (\S+?)[`\s.,;]", body + " "):
                calls += 1
                self.assertEqual(label, "T%d" % n)
                self.assertRegex(label, pattern)
        self.assertGreaterEqual(calls, 6)


class DocumentTests(unittest.TestCase):
    def test_every_source_cite_names_a_file_and_a_function_or_key_that_exist(self):
        cites = re.findall(r"\bsrc: ([\w.\-]+) ([\w.\-]+)", DOC)
        self.assertGreaterEqual(len(cites), 15)
        for name, place in cites:
            found = [p for p in INST.rglob(name) if p.is_file()]
            self.assertEqual(len(found), 1, name)
            self.assertTrue(defined(found[0], place), "%s %s" % (name, place))

    def test_every_quoted_on_screen_text_is_in_installer_nsis_and_a_composed_one_has_its_box_and_its_reason(self):
        """A composed quote, label then reason, is the box <label>: $R9. after a Check_* call, with a reason that this Check_* or a Val_* it calls puts in $R9."""
        quotes = prose_quotes(DOC)
        self.assertGreaterEqual(len(quotes), 30)
        composed = 0
        for quote in quotes:
            quote = quote.rstrip(".")
            if quote in NSIS_TEXT or quote in EXPANDED:
                continue
            if ": " in quote:
                label, reason = quote.split(": ", 1)
                checks = [check for check, text in COMPOSED if text == label]
                self.assertTrue(any(reason in reasons(check) for check in checks), quote)
                composed += 1
            else:
                for part in quote.split(". "):
                    self.assertIn(part, NSIS_TEXT, quote)
        self.assertGreaterEqual(composed, 5)

    def test_a_composed_message_is_quoted_after_the_field_the_step_typed_into(self):
        """The GitHub and the GitLab address boxes give one reason: only the label, tied to the field typed into, tells them apart."""
        labels = {label for _, label in COMPOSED}
        tied = 0
        for n, body in STEPS:
            text = re.sub(r"`[^`\n]*`", "", body)
            field = None
            for m in re.finditer(r'"([^"\n]+)"', text):
                label = m.group(1).split(": ", 1)[0]
                if text[:m.start()].endswith(" in "):
                    field = m.group(1)
                elif ": " in m.group(1) and label in labels:
                    self.assertEqual(label, field, "T%d: %s" % (n, m.group(1)))
                    tied += 1
        self.assertGreaterEqual(tied, 5)

    def test_every_exit_code_named_in_the_prose_exists_and_t3_names_the_one_trust_sets(self):
        """Codes 3 and 38 are in footprint.json and the .nsh files, not in schema.json, so all three are read."""
        known = {0}
        known |= set(json.loads(text_of(INST / "schema.json"))["exit_codes"].values())
        known |= set(json.loads(text_of(INST / "footprint.json"))["exit_codes"].values())
        for path in list(NSIS.glob("*.nsh")) + [NSIS / "main.nsi"]:
            known |= {int(x) for x in re.findall(r"SetErrorLevel (\d+)", text_of(path))}
        named = {int(x) for x in re.findall(r"\bexits? (?:code )?(\d+)\b", prose(DOC))}
        self.assertIn(3, named)
        self.assertLessEqual(named, known)
        refuse = re.findall(r"SetErrorLevel (\d+)", function_body(text_of(NSIS / "trust.nsh"), "TrustRefuse"))
        self.assertEqual(re.findall(r"\bexit (\d+)\b", dict(STEPS)[3]), refuse)

    def test_the_sizes_follow_from_the_literals_the_installer_writes(self):
        install = text_of(NSIS / "install.nsh")
        version = re.search(r'!define INSTALLER_VERSION "([^"]+)"', install).group(1)
        first = re.search(r"FileWrite \$InstallHandle '(\{\"schema_version\".*?)'$", install, re.M).group(1)
        mode = re.search(r"FileWrite \$InstallHandle '(\{\"mode\".*?)'$", install, re.M).group(1)
        write_state = function_body(text_of(NSIS / "update.nsh"), "Update_WriteState")
        self.assertIn('FileWrite $upd_h "$upd_json$\\n"', write_state)
        self.assertIn('StrCpy $upd_json "{"', write_state)
        unconditional = re.sub(r"\$\{If\}.*?\$\{EndIf\}", "", write_state, flags=re.S)
        repaired = "{" + "".join(re.findall(r"StrCpy \$upd_json '\$upd_json(.*)'", unconditional))
        self.assertEqual(json.loads(repaired.replace("${INSTALLER_VERSION}", version)), {"installer_version": version, "schema_version": 1})
        self.assertIn('FileWrite $0 "$TrustSigner$\\n"', text_of(NSIS / "trust.nsh"))
        self.assertIn("[0-9a-f]{64}", text_of(INST / "trust.py"))
        sizes = {
            "installer-state.json: present, %d bytes" % nsis_bytes(first, version): 53,
            "runner-mode.json: present, %d bytes" % nsis_bytes(mode, version): 19,
            "installer-state.json: present, %d bytes" % nsis_bytes(repaired + "$\\n", version): 52,
            "present, %d bytes" % (64 + 1): 65,
        }
        for text, expected in sizes.items():
            self.assertIn(text, DOC)
            self.assertIn("%d bytes" % expected, text)
        self.assertIn("DisplayVersion: %s" % version, DOC)

    def test_the_report_lines_the_document_expects_are_the_ones_the_script_prints(self):
        spans = []
        for _, body in STEPS:
            if "vm-state.ps1" in body:
                spans += [s for s in re.findall(r"`([A-Za-z][^`]*: [^`]*)`", body) if not s.startswith("Folder line is the machine folder: ")]
        self.assertGreaterEqual(len(spans), 8)
        for span in spans:
            label, value = span.split(": ", 1)
            self.assertIn(label, PS1, span)
            if re.fullmatch(r"present, \d+ bytes", value):
                self.assertIn("present, {0} bytes", PS1, span)

    def test_the_rebuild_command_is_the_vmkit_cli_and_lists_the_complete_kit(self):
        from unittest.mock import patch
        from installer.guest import vmkit

        section = DOC.split("## Rebuild the kit\n", 1)[1]
        commands = re.findall(r"```bash\n(.*?)```", section, re.S)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].count("\n"), 1)
        command = commands[0].strip()
        self.assertEqual(command, 'python3 -m installer.guest.vmkit build --out '
                         '~/work/vm-kit/$(git rev-parse HEAD | cut -c1-12) '
                         '--payload ~/work/vm-kit/stand-in-payload.txt')
        argv = shlex.split(command.replace("$(git rev-parse HEAD | cut -c1-12)", "0123456789ab"))
        with patch.object(vmkit, "make_kit") as make_kit, patch("builtins.print"):
            self.assertEqual(vmkit.main(argv[3:]), 0)
        self.assertEqual(make_kit.call_args.args, (Path("~/work/vm-kit/0123456789ab"),
                         Path("~/work/vm-kit/stand-in-payload.txt"), Path(".")))
        self.assertEqual(vmkit.KIT_FILES, ("installer.exe", "VM-TEST.md", "vm-state.ps1"))
        for name in (*vmkit.KIT_FILES, "SHA256SUMS"):
            self.assertIn(name, section)
        self.assertIn("python3 -m installer.guest.vmkit verify <dir>", section)
        self.assertIn("--test-build", text_of(INST / "guest" / "vmkit.py"))
        self.assertIn('"--test-build"', text_of(INST / "build.py"))

    def test_no_secret_money_host_or_user_name_and_only_ascii(self):
        self.assertTrue(DOC.isascii())
        for pattern in (r"ghp_", r"glpat-", r"BEGIN [A-Z ]*KEY", r"AKIA[0-9A-Z]{8}", r"[0-9a-fA-F]{32,}", r"\$\s*\d", r"US\$", r"\bUSD\b", r"\bEUR\b",
                        r"\b\d{1,3}(\.\d{1,3}){3}\b"):
            self.assertIsNone(re.search(pattern, DOC), pattern)
        left = DOC
        for ok in ("https://github.com/o/r", "https://", "http://", "ftp://"):
            left = left.replace(ok, "")
        self.assertNotIn("://", left)
        names = {socket.gethostname().split(".")[0], getpass.getuser(), Path.home().name} - {"runner", "root", "user", "ubuntu", "github"}
        for name in names:
            if len(name) >= 5:
                self.assertIsNone(re.search(r"\b%s\b" % re.escape(name), DOC, re.I), "a host or user name is in the document")

    def test_the_readme_has_one_line_linking_the_document(self):
        readme = text_of(INST / "README.md")
        self.assertEqual(len([l for l in readme.splitlines() if "VM-TEST.md" in l]), 1)


class ReporterTests(unittest.TestCase):
    CODE = "\n".join(l for l in PS1.splitlines() if not l.lstrip().startswith("#"))

    def test_the_script_is_short_ascii_and_has_no_network_or_url(self):
        self.assertLess(len(PS1.splitlines()), 120)
        self.assertTrue(PS1.isascii())
        self.assertIsNone(re.search(r"https?://|Net\.|WebClient|Invoke-", PS1))

    def test_the_script_only_reads(self):
        self.assertEqual(ps_outside(PS1), [])
        self.assertEqual(set(re.findall(r"Write-\w+", self.CODE)), {"Write-Output"})
        self.assertEqual(self.CODE.count("steps.jsonl"), 1)
        self.assertRegex(self.CODE, r"\$known = .*'steps\.jsonl'")

    def test_the_allow_list_holds_what_the_script_uses_and_nothing_more(self):
        found = ps_inventory(PS1)
        self.assertEqual(found["words"], ALLOWED["keywords"] | ALLOWED["commands"] | ALLOWED["functions"] | ALLOWED["arguments"])
        for kind in ("types", "statics", "methods", "properties", "parameters"):
            self.assertEqual(found[kind], ALLOWED[kind], kind)

    def test_the_guard_refuses_every_alias_and_every_write(self):
        aliases = ("gc", "cat", "type", "ri", "rm", "del", "rd", "sc", "ni", "iex", "saps")
        mutants = ["%s $dir" % alias for alias in aliases] + [
            "gc $dir\\steps.jsonl\nri -LiteralPath $dir -Recurse -Force", "Remove-Item -LiteralPath $dir", "Get-Content $exe", "Get-Item $exe -Raw",
            "[IO.File]::Delete($exe)", "[System.IO.File]::WriteAllText($exe, 'x')", "$folder.Delete()", "$folder.Attributes = 'Normal'",
            "$x = \"$(gci)\"", "& $exe", ". $exe", "Get-Item $exe > $dir", "$x = @'\nhere\n'@", "<# block #> Say 'x'", "`n",
            "$folder | ForEach-Object 'Delete'", "$m = 'Delete'; $folder.$m()", "$folder.'Delete'()", "$folder | % 'Delete'", "$folder | foreach 'Delete'",
            "$folder | Where-Object 'Name'", "$folder.psobject", "[IO.File]::$m($exe)"]
        for mutant in mutants:
            self.assertNotEqual(ps_outside(PS1 + "\n" + mutant + "\n"), [], mutant)
        self.assertEqual(ps_outside(PS1 + "\n# gc and ri in a comment\nSay 'ri -Recurse in a string'\n"), [])

    # A member write of any target shape and with any operator, and a write through a provider path (#163).
    MEMBER_WRITES = ["(Get-Item -LiteralPath $exe -Force).Attributes = 'Hidden'", "$(Get-Item -LiteralPath $exe).Attributes = 'Hidden'",
                     "$folder.Attributes += 2", "$folder.Attributes -= 1", "$folder.Attributes *= 2", "$folder.Attributes /= 2",
                     "$folder.Attributes %= 2", "$folder.Attributes ??= 2", "$folder.Attributes++", "--$folder.Attributes",
                     "[Microsoft.Win32.RegistryKey]::Name = 'x'", "$folder.Attributes=2"]
    DRIVE_WRITES = ["${c:probe} = ''", "${temp:probe142} = ''", "$env:Path = ''", "$env:Path += ';x'", "[string]$env:Path = ''", "$a, $env:Path = 1, 2",
                    "$c:probe = ''", "$env:Path++"]
    PLAIN = "\n$x = $env:ProgramData\n$x += $env:LOCALAPPDATA\n$script:y = 1\n$variable:z = 1\n[string]$w = $x\n"

    def test_the_regex_guard_refuses_a_member_write_of_any_target_and_operator_and_a_drive_variable_write(self):
        for mutant in self.MEMBER_WRITES + self.DRIVE_WRITES:
            self.assertNotEqual(ps_outside(PS1 + "\n" + mutant + "\n"), [], mutant)
        self.assertEqual(ps_outside(PS1 + self.PLAIN), [])

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
    def test_the_parser_finds_only_the_allowed_commands(self):
        cmd = ("$a=[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$null);"
               "$a.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst]},$true)|%%{$_.GetCommandName()}|Sort-Object -Unique") % PS1_PATH
        r = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120)
        self.assertEqual(set(r.stdout.split()), ALLOWED["commands"] | ALLOWED["functions"], r.stdout + r.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
    def test_every_member_in_the_ast_is_a_constant_name_in_the_allow_list_and_every_pipeline_block_is_one_script_block(self):
        found = ast_found(PS1_PATH)
        self.assertEqual(ast_outside(found), [])
        self.assertEqual({m["name"] for m in found["members"]}, ALLOWED["methods"] | ALLOWED["statics"] | ALLOWED["properties"])
        self.assertEqual(sorted(b["name"] for b in found["blocks"]), ["ForEach-Object", "Where-Object"])

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
    def test_the_ast_guard_refuses_the_member_name_form_a_dynamic_member_and_a_quoted_member(self):
        mutants = ("$folder | ForEach-Object 'Delete'", "$m = 'Delete'; $folder.$m()", "$folder.'Delete'()", "$folder | ForEach-Object -MemberName Delete",
                   "$folder | Where-Object -Property Name", "$folder.psobject")
        with tempfile.TemporaryDirectory() as tmp:
            for mutant in mutants:
                path = Path(tmp) / "mutant.ps1"
                path.write_text(PS1 + "\n" + mutant + "\n", encoding="utf-8")
                self.assertNotEqual(ast_outside(ast_found(path)), [], mutant)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
    def test_the_ast_guard_refuses_a_member_write_of_any_target_and_operator_and_a_drive_variable_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mutant.ps1"
            for mutant in self.MEMBER_WRITES + self.DRIVE_WRITES:
                path.write_text(PS1 + "\n" + mutant + "\n", encoding="utf-8")
                self.assertTrue([o for o in ast_outside(ast_found(path)) if o.startswith("write to ")], mutant)
            path.write_text(PS1 + self.PLAIN, encoding="utf-8")
            self.assertEqual(ast_outside(ast_found(path)), [])

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
    def test_every_write_in_the_script_sets_a_plain_variable(self):
        writes = ast_found(PS1_PATH)["writes"]
        self.assertGreaterEqual(len(writes), 10)
        self.assertEqual({(w["target"], w["drive"]) for w in writes}, {("VariableExpressionAst", None)})

    def test_the_script_is_strict_and_stops_on_an_error(self):
        lines = [l for l in self.CODE.splitlines() if l.strip()]
        self.assertIn("Set-StrictMode -Version Latest", lines)
        self.assertIn("$ErrorActionPreference = 'Stop'", lines)
        self.assertLess(lines.index("Set-StrictMode -Version Latest"), lines.index("$ErrorActionPreference = 'Stop'"))
        self.assertLess(lines.index("$ErrorActionPreference = 'Stop'"), min(i for i, l in enumerate(lines) if l.startswith("function ")))

    def test_the_status_is_explicit_and_documented_and_each_last_line_says_its_status(self):
        pairs = re.findall(r"Say 'end of report: [^']*status (\d)'(?:;\s*|\s+)exit (\d)", PS1)
        self.assertEqual(sorted(pairs), [("0", "0"), ("1", "1"), ("1", "1")])
        self.assertTrue(self.CODE.rstrip().endswith("exit 0"))
        for text in set(re.findall(r"Say '(end of report: [^']+)'", PS1)):
            self.assertIn("`%s`" % text, DOC)
        self.assertIn("`$LASTEXITCODE`", DOC)

    @unittest.skipUnless(shutil.which("pwsh") and os.name == "posix", "needs pwsh on a POSIX host")
    def test_a_failed_read_ends_with_status_1_and_names_only_the_kind_of_error(self):
        r = subprocess.run(["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1_PATH), "-Step", "T0"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[-1], "[T0] end of report: a read failed, status 1")
        self.assertRegex(lines[-2], r"^\[T0\] a read failed: \w+$")

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
    def test_the_script_parses(self):
        r = pwsh_parse(PS1_PATH)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class PartCTests(unittest.TestCase):
    def test_the_rows_are_the_ten_probe_rows_unchanged(self):
        rows = [(int(n), shown, int(code)) for n, shown, code in re.findall(r"@\((\d+),\s*'([^']*)',\s*(\d+)\)", BLOCK)]
        self.assertEqual(rows, [(n, shown, expected) for n, shown, expected, _ in PROBE])

    def test_the_step_log_line_names_the_file_log_nsh_appends_to_and_says_it_must_exist(self):
        init = function_body(ALL_NSIS, "Log_InitPaths")
        folder = re.search(r'SetShellVarContext all\s+StrCpy \$MachineFolder "\$APPDATA\\(\w+)"', init).group(1)
        leaf = re.search(r'StrCpy \$LogPath "\$MachineFolder\\([\w.]+)"', init).group(1)
        part_c = DOC[DOC.index("## Part C"):DOC.index("## How to report")]
        self.assertIn("may append one line to `C:\\ProgramData\\%s\\%s`, only if that file already exists" % (folder, leaf), part_c)
        for text in ("%APPDATA%", "Roaming", "%TEMP%", "that folder already exists"):
            self.assertNotIn(text, part_c)
        step = function_body(ALL_NSIS, "LogStep")
        self.assertRegex(step, r'StrCmp \$LogExistingOnly 1 0 log_ready\s+IfFileExists "\$LogPath" log_ready done')
        self.assertIn("Call LogStep", function_body(SCREENS, "Silent_Bad"))
        on_init = re.search(r"^Function \.onInit\n(.*?)^FunctionEnd", MAIN, re.M | re.S).group(1)
        self.assertRegex(on_init, r"(?s)Call Log_InitPaths\s+StrCpy \$LogExistingOnly 1\s+Call Carried_Detect.*ParseSilentKeys.*StrCpy \$LogExistingOnly 0")

    def test_t12_names_the_step_log_log_nsh_appends_to(self):
        init = function_body(ALL_NSIS, "Log_InitPaths")
        folder = re.search(r'SetShellVarContext all\s+StrCpy \$MachineFolder "\$APPDATA\\(\w+)"', init).group(1)
        leaf = re.search(r'StrCpy \$LogPath "\$MachineFolder\\([\w.]+)"', init).group(1)
        t12 = dict(STEPS)[12]
        self.assertIn("`C:\\ProgramData\\%s\\%s`" % (folder, leaf), t12)
        self.assertEqual(t12.count(leaf), 1)
        for text in ("%APPDATA%", "Roaming", "AppData", "%TEMP%"):
            self.assertNotIn(text, t12)

    def test_the_block_gives_no_signer_and_starts_each_row_without_a_shell_layer(self):
        self.assertNotIn("/SIGNER", BLOCK)
        self.assertNotIn("Start-Process", BLOCK)
        self.assertNotRegex(BLOCK, r"-ArgumentList|-File\b|-Command\b")
        self.assertIn("System.Diagnostics.ProcessStartInfo", BLOCK)
        self.assertIn("$i.UseShellExecute = $false", BLOCK)
        self.assertIn("$i.Arguments = '%s ' + $rest" % PROBE_P, BLOCK)
        self.assertIn(".Replace('<1000 x>', 'x' * 1000)", BLOCK)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
    def test_the_block_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "block.ps1"
            path.write_text(BLOCK, encoding="utf-8")
            r = pwsh_parse(path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    LAUNCHER = re.search(r"Add-Type -TypeDefinition @'\n(.*?)\n'@", BLOCK, re.S)
    # On a POSIX host there is no kernel32: the stand-in launcher logs what it was asked to start and starts it with the words of the line after the first.
    STUB = ('using System.Diagnostics; using System.IO;\npublic static class KitDirect {\n  public static int Run(string app, string line, string dir) {\n'
            '    File.WriteAllText(Path.Combine(dir, "direct.log"), app + "\\n" + line + "\\n" + dir);\n'
            '    var i = new ProcessStartInfo(app) { WorkingDirectory = dir, UseShellExecute = false };\n'
            '    var w = line.Split(\' \'); for (int n = 1; n < w.Length; n++) i.ArgumentList.Add(w[n]);\n'
            '    var p = Process.Start(i); p.WaitForExit(); return p.ExitCode;\n  }\n}')

    def test_c8d_starts_s_exe_directly_with_the_line_of_row_8_as_it_is(self):
        """#136, REV187: through cmd the line already gave 31 before the fix; only a direct start leaves one blank after the one-letter name."""
        launcher = self.LAUNCHER.group(1)
        self.assertIn("static extern bool CreateProcessW(string app, StringBuilder cmd,", launcher)
        self.assertIn("CreateProcessW(app, new StringBuilder(line), IntPtr.Zero, IntPtr.Zero, false, 0, IntPtr.Zero, dir, ref si, out pi)", launcher)
        self.assertIn("WaitForSingleObject(pi.hp, 0xFFFFFFFF); GetExitCodeProcess(pi.hp, out c);", launcher)
        after = BLOCK[BLOCK.index("'@\n"):]
        self.assertIn("$r = $rows[7]", after)
        self.assertIn("$rc = [KitDirect]::Run((Resolve-Path .\\s.exe).Path, $r[1], (Get-Location).Path)", after)
        self.assertLess(after.index("[KitDirect]::Run("), after.index("Remove-Item .\\s.exe"))
        # REV187B: 31 is expected, so counting 3 as 0 could never change C8d; it compares the exit as it is
        self.assertIn("if ($rc -eq $r[2]) { 'C8d ok' } else { 'C8d saw: {0}' -f $rc }", after)
        self.assertNotIn("$seen", after)
        self.assertEqual(PROBE[7][1], "s /FOO /S")

    def run_block(self, last_exit):
        """With stand-ins for installer.exe, cmd.exe and the direct launcher: (printed lines, the runs in order, what the launcher was asked)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "installer.exe").write_text(
                '#!/bin/sh\nd=$(dirname "$0")\nn=$(cat "$d/count" 2>/dev/null || echo 0)\nn=$((n + 1))\necho "$n" > "$d/count"\n'
                '{ basename "$0"; for a in "$@"; do printf "%s\\n" "$a"; done; echo "--"; } >> "$d/args.log"\nexit "$(echo "$KIT_EXITS" | cut -d, -f"$n")"\n',
                encoding="utf-8")
            (tmp / "comspec").write_text('#!/bin/sh\n[ "$1" = "/c" ] || exit 99\nshift\nprog=$1\nshift\nexec "./$prog.exe" "$@"\n', encoding="utf-8")
            block = BLOCK[:self.LAUNCHER.start(1)] + self.STUB + BLOCK[self.LAUNCHER.end(1):]
            (tmp / "block.ps1").write_text(block, encoding="utf-8")
            for name in ("installer.exe", "comspec"):
                (tmp / name).chmod(0o755)
            env = dict(os.environ, ComSpec=str(tmp / "comspec"), KIT_EXITS="3,32,31,33,3,32,30,31,3,50,%d" % last_exit)
            r = subprocess.run(["pwsh", "-NoProfile", "-File", str(tmp / "block.ps1")], cwd=tmp, env=env, capture_output=True, text=True, timeout=180)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertFalse((tmp / "s.exe").exists())
            runs = [rec.strip("\n").split("\n") for rec in (tmp / "args.log").read_text().split("--\n") if rec.strip()]
            app, line, cwd = (tmp / "direct.log").read_text().split("\n")
            self.assertEqual(Path(cwd).resolve(), tmp.resolve())
            self.assertEqual(Path(app).resolve(), (tmp / "s.exe").resolve())
            return [l for l in r.stdout.splitlines() if l.strip()], runs, line, r.stderr

    @unittest.skipUnless(shutil.which("pwsh") and os.name == "posix", "needs pwsh on a POSIX host")
    def test_the_block_runs_each_row_and_counts_exit_3_as_the_tables_0(self):
        """What the block starts, in which order, and what it prints; C8d's exit 3 is what the installer gave before #136 (REPORT L3)."""
        for last_exit, last_line in ((31, "C8d ok"), (3, "C8d saw: 3"), (0, "C8d saw: 0")):
            with self.subTest(c8d=last_exit):
                printed, runs, line, err = self.run_block(last_exit)
                self.assertEqual(printed, ["C%d ok" % n if n != 3 else "C3 saw: 31" for n in range(1, 11)] + [last_line], err)
                self.assertEqual(line, "s /FOO /S")
                self.assertEqual(len(runs), 11)
                self.assertEqual(runs[0], ["installer.exe", "/S", "/MODE=github", "/GITHUB_URL=https://github.com/o/r"])
                self.assertEqual(runs[7], ["s.exe", "/FOO", "/S"])
                self.assertEqual(runs[9][-2:], ["/PARTNER_ID=" + "x" * 1000, "/FOO"])
                self.assertEqual(runs[10], ["s.exe", "/FOO", "/S"])
                self.assertEqual([r[0] for r in runs].count("installer.exe"), 9)


class RunLineTests(unittest.TestCase):
    """Windows 11 blocks an unsigned script by default: the report is only ever started in the one form that runs."""
    FORM = re.compile(r"powershell -NoProfile -ExecutionPolicy Bypass -File \.\\vm-state\.ps1 -Step T(\d+)")

    def test_every_run_line_of_the_document_is_that_form_in_its_own_step(self):
        called, spans = set(), 0
        for n, body in STEPS:
            for span in re.findall(r"`([^`\n]*(?:\\vm-state\.ps1|-Step)[^`\n]*)`", body):
                found = self.FORM.fullmatch(span)
                self.assertIsNotNone(found, span)
                self.assertEqual(int(found.group(1)), n, span)
                called.add(n)
                spans += 1
        self.assertGreaterEqual(len(called), 7)
        self.assertEqual(sum(body.count("\\vm-state.ps1") for _, body in STEPS), spans)
        self.assertEqual(DOC.count("\\vm-state.ps1"), spans)

    def test_the_script_header_gives_the_same_form(self):
        self.assertEqual(PS1.count("\\vm-state.ps1"), 1)
        self.assertRegex(PS1, r"(?m)^#\s+powershell -NoProfile -ExecutionPolicy Bypass -File \.\\vm-state\.ps1 -Step T13$")

    def test_the_document_says_what_smartscreen_shows_and_what_to_click_in_one_line_before_part_a(self):
        line = next(l for l in DOC[:DOC.index("## Part A")].splitlines() if "Mark of the Web" in l)
        for text in ("`Windows protected your PC`", "`More info`", "`Run anyway`", "`Open File - Security Warning`", "`Run`", "Unblock-File",
                     "-ExecutionPolicy Bypass", "not installer code"):
            self.assertIn(text, line)


class CarryTests(unittest.TestCase):
    """T21 and T22 (SL-21b, #117): what the first window hands to the elevated copy, read from the installer source and not copied here."""
    T21 = dict(STEPS)[21]
    T22 = dict(STEPS)[22]

    @staticmethod
    def label(key):
        return re.search(r'Push "([^"]+)"\s+Push "%s"' % re.escape(key), function_body(SCREENS, "Carry_Answers")).group(1)

    def test_t21_quotes_the_refusal_for_the_label_of_the_install_folder_and_it_comes_before_the_prompt(self):
        raised = function_body(ELEVATE, "Elevate_Raise")
        template = re.search(r'MessageBox MB_OK\|MB_ICONEXCLAMATION "([^"]*\$carry_bad[^"]*)"', raised).group(1)
        self.assertIn('"%s"' % template.replace("$carry_bad", self.label("/INSTALL_DIR=")), self.T21)
        self.assertRegex(raised, r'\$carry_bad != ""\s+MessageBox[^\n]*\n\s+Return\s+\$\{EndIf\}\s+ClearErrors\s+ExecShell "runas"')
        self.assertRegex(function_body(ELEVATE, "Page_elevation_Leave"), r"Call Elevate_Raise\s+Abort")

    def test_t21_types_a_value_the_page_accepts_and_carry_one_refuses(self):
        typed = re.search(r'`([^`]+)` in "%s"' % self.label("/INSTALL_DIR="), self.T21).group(1)
        self.assertEqual(re.findall(r"Call (\w+)", function_body(SCREENS, "Check_install_dir")), ["Val_Line", "Val_NoQuote"])
        escapes = {"$\\t": "\t", "$\\r": "\r", "$\\n": "\n"}
        on_one_line = [escapes[c] for c in re.findall(r'\$R1 == "(\$\\[trn])"', function_body(SCREENS, "Val_Line"))]
        quote = re.search(r"StrCpy \$R5 '(.)'", function_body(SCREENS, "Val_NoQuote")).group(1)
        one = function_body(ELEVATE, "Carry_One")
        self.assertEqual(re.search(r"StrCpy \$carry_q '(.)'", one).group(1), quote)
        refused = re.findall(r'\$\{StrStr\} \$carry_t \$carry_v "([^"]+)"', one)
        self.assertEqual(len(on_one_line), 3)
        self.assertEqual(len(refused), 2)
        self.assertTrue(any(part in typed for part in refused), typed)
        self.assertEqual(typed, typed.strip())
        for char in on_one_line + [quote]:
            self.assertNotIn(char, typed)

    def test_t22_the_elevated_copy_opens_at_the_secrets_page_after_the_pages_it_skips(self):
        order = re.findall(r"^Page custom (\w+)", MAIN, re.M)

        def skips(name):
            body = function_body(ALL_NSIS, name)
            return re.search(r"\$\{If\} \$carried == 1\s+Abort", body) is not None or any(skips(c) for c in re.findall(r"Call (Page_\w+)", body))

        skipped = [p for p in order if skips(p)]
        self.assertEqual(skipped, order[:len(skipped)])
        self.assertEqual(order[len(skipped)], "Page_secrets")
        def named(name):
            return first_field(re.sub(r"_Pre$", "", name))

        first, last = re.search(r'from the page whose first field is "([^"]+)" to the page whose first field is "([^"]+)"', self.T22).groups()
        self.assertEqual(first, named(skipped[0]))
        self.assertIn(last, [named(p) for p in skipped[1:]])
        self.assertIn('opens at the page whose first field is "%s"' % named("Page_secrets"), self.T22)
        for name in ("Page_noadmin", "Page_elevation"):
            self.assertRegex(function_body(ELEVATE, name), r"\$\{If\} \$elev_isadmin == 1\s+Abort")
        self.assertRegex(function_body(SCREENS, "Page_secrets"), r"\$\{If\} \$carried == 1\s+GetDlgItem \$0 \$HWNDPARENT 3\s+EnableWindow \$0 0\s+\$\{EndIf\}")
        self.assertIn("Back button greyed out", self.T22)

    def test_t22_the_mode_and_the_answers_cross_and_no_secret_does(self):
        answers = function_body(SCREENS, "Carry_Answers")
        self.assertRegex(answers, r'^\s*\$\{If\} \$in_mode != ""\s+Push "[^"]+"\s+Push "/MODE="')
        secrets = re.findall(r"\$ctl_\w+ \$(in_\w+)", function_body(SCREENS, "Page_secrets_Leave"))
        self.assertEqual(len(secrets), 3)
        for var in secrets:
            self.assertNotIn("$" + var, answers)
        for key in ("/ELEVATED", "/MODE="):
            self.assertIn('Push "%s"' % key, function_body(ELEVATE, "Carried_Detect"))
        self.assertIn("no secret is ever handed over", self.T22)
        self.assertIn("`runner-mode.json: present, 19 bytes`", self.T22)

    def test_t22_declining_shows_the_code_s_box_and_the_folder_line_is_the_machine_folder(self):
        declined = re.search(r'declined:\s+MessageBox MB_OK\|MB_ICONEXCLAMATION "([^"]+)"', function_body(ELEVATE, "Elevate_Raise")).group(1)
        self.assertIn('"%s"' % declined, self.T22)
        elevation = function_body(ELEVATE, "Page_elevation")
        self.assertIn('"Folder: $MachineFolder (', elevation)
        self.assertNotIn("$APPDATA", elevation)
        leaf = re.search(r'SetShellVarContext all\s+StrCpy \$MachineFolder "\$APPDATA\\(\w+)"', function_body(ALL_NSIS, "Log_InitPaths")).group(1)
        self.assertIn("`C:\\ProgramData\\%s`, the machine folder" % leaf, self.T22)
        self.assertIn("Call Log_InitPaths", re.search(r"^Function \.onInit\n(.*?)^FunctionEnd", MAIN, re.M | re.S).group(1))
        self.assertIn("RequestExecutionLevel user", MAIN)

    def test_the_stale_t21_wording_is_gone(self):
        for text in ("KNOWN", "SL-24", "#117"):
            self.assertNotIn(text, self.T21)
        self.assertNotIn("SL-24", DOC)
        self.assertEqual(dict(STEPS)[23], "Restore the snapshot `before`. READ")


class PageNameTests(unittest.TestCase):
    """The pages have no heading (a bare nsDialogs::Create 1018): the document names each page by its first field, read from the source."""
    ORDER = re.findall(r"^Page custom (\w+)", MAIN, re.M)

    @staticmethod
    def phrase(page):
        return 'page whose first field is "%s"' % first_field(page)

    def test_each_page_step_names_the_page_it_cites_by_the_first_field_of_that_page(self):
        named = 0
        for n, body in STEPS:
            cited = re.search(r"src: screens\.nsh (Page_\w+?)_Leave\b", body)
            if cited:
                self.assertIn("he " + self.phrase(cited.group(1)), body, "T%d" % n)
                named += 1
        self.assertEqual(named, 7)

    def test_each_page_step_quotes_the_help_text_of_the_page_it_names(self):
        """Every page with a help text that a step names by its first field quotes that help text in the same step; the NI docker image page has one too."""
        self.assertIn("Page_image", HELP)
        quoted = set()
        for n, body in STEPS:
            for page, help_text in HELP.items():
                if re.search(r"[Tt]he " + re.escape(self.phrase(page)) + r" \(", body) and "src: screens.nsh %s_Leave" % page in body:
                    self.assertIn('help text "%s"' % help_text, body, "T%d" % n)
                    quoted.add(page)
        self.assertEqual(quoted, {"Page_folders", "Page_forge", "Page_network", "Page_labview", "Page_image", "Page_secrets", "Page_mode"})

    def test_t10_names_the_page_after_it_that_is_not_shown_and_t14_the_page_a_repair_skips(self):
        after = self.ORDER[self.ORDER.index("Page_image") + 1]
        self.assertEqual(after, "Page_licences")
        self.assertIn("The %s is not shown after it" % self.phrase(after), dict(STEPS)[10])
        self.assertEqual(self.ORDER[:2], ["Page_signer", "Page_mode_Pre"])
        self.assertIn("no %s" % self.phrase("Page_mode"), dict(STEPS)[14])

    def test_no_title_that_only_schema_json_holds_is_quoted_and_the_code_sets_no_heading(self):
        titles = [p["title"] for p in json.loads(text_of(INST / "schema.json"))["pages"]]
        self.assertGreaterEqual(len(titles), 8)
        for title in titles:
            self.assertNotIn('"%s"' % title, DOC)
        for text in ("MUI_HEADER_TEXT", "SubCaption"):
            self.assertNotIn(text, NSIS_TEXT)
        # The window caption is one text for the whole wizard (the experimental warning, issue 329), not a heading of a page.
        self.assertEqual(re.findall(r"^\s*(\w*Caption)\b(.*)$", NSIS_TEXT, re.M),
                         [("Caption", ' "Ecosystem Runner Setup (EXPERIMENTAL)"'), ("UninstallCaption", ' "Ecosystem Runner Uninstall (EXPERIMENTAL)"')])
        self.assertEqual([l for l in NSIS_TEXT.splitlines() if l.startswith("Page ") and '"' in l], [])
        self.assertIn("The code sets no heading on its pages, so each page is named by its first field.", DOC)


class InstallerFactsTests(unittest.TestCase):
    """What the report looks for is what the installer writes: both are read from their sources, so a second copy cannot drift."""
    WRITES = re.findall(r"""^\s*WriteRegStr HKLM "([^"]+)" "(\w+)" (?:"([^"]*)"|'(.*)')\s*$""", INSTALL, re.M)
    VALUES = {name: dq or sq for _, name, dq, sq in WRITES}
    EXE = re.search(r'WriteUninstaller "([^"]+)"', INSTALL).group(1)

    @staticmethod
    def template(expr):
        """A PowerShell concatenation of string literals and $exe, as text with <exe> for the path."""
        return "".join("<exe>" if p == "$exe" else p[1:-1].replace("''", "'") for p in (q.strip() for q in expr.split(" + ")))

    def test_the_uninstall_key_and_the_folder_are_the_ones_install_nsh_writes(self):
        self.assertEqual(len(self.WRITES), 4)
        self.assertEqual({key for key, *_ in self.WRITES}, {re.search(r"\$uninstall = '([^']+)'", PS1).group(1)})
        folder = re.search(r"\$dir = Join-Path \$env:ProgramData '([^']+)'", PS1).group(1)
        leaf = re.search(r"\$exe = Join-Path \$dir '([^']+)'", PS1).group(1)
        self.assertEqual(self.EXE, "$APPDATA\\%s\\%s" % (folder, leaf))
        footprint = function_body(INSTALL, "Install_Footprint")
        self.assertLess(footprint.index("SetShellVarContext all"), footprint.index("WriteUninstaller"))

    def test_the_two_uninstall_strings_the_script_compares_are_the_ones_install_nsh_writes(self):
        for name in ("UninstallString", "QuietUninstallString"):
            expr = re.search(r"GetValue\('%s'\) -ceq \((.+?)\)\)\)\)$" % name, PS1, re.M).group(1)
            self.assertEqual(self.template(expr), self.VALUES[name].replace(self.EXE, "<exe>"), name)

    def test_the_document_gives_the_name_version_and_value_names_install_nsh_writes(self):
        t13 = dict(STEPS)[13]
        version = re.search(r'!define INSTALLER_VERSION "([^"]+)"', INSTALL).group(1)
        self.assertEqual(self.VALUES["DisplayVersion"], "${INSTALLER_VERSION}")
        self.assertIn("`DisplayName: %s`" % self.VALUES["DisplayName"], t13)
        self.assertIn("`DisplayVersion: %s`" % version, t13)
        self.assertIn("values `%s`" % ", ".join(sorted(self.VALUES)), t13)
        self.assertIn('"%s" with version %s' % (self.VALUES["DisplayName"], version), dict(STEPS)[16])

    def test_the_two_write_failures_t12_names_are_the_boxes_and_exits_install_nsh_ends_a_run_with(self):
        exits = json.loads(text_of(INST / "footprint.json"))["exit_codes"]
        t12 = dict(STEPS)[12]
        for name, kind in (("Install_UninstallerFailed", "uninstaller-write-failed"), ("Install_StateFailed", "state-write-failed")):
            body = function_body(INSTALL, name)
            box = re.search(r'MessageBox MB_OK\|MB_ICONSTOP "([^"]+)"', body).group(1)
            code = int(re.search(r"SetErrorLevel (\d+)", body).group(1))
            self.assertEqual(code, exits[kind], name)
            self.assertIn('"%s" with exit %d' % (box, code), t12)
            self.assertIn("(src: install.nsh %s)" % name, t12)
        self.assertIn("as in T12", dict(STEPS)[15])
        for name in ("Update_WriteState", "Update_WriteEntry"):
            self.assertIn("(src: update.nsh %s)" % name, dict(STEPS)[15])
        self.assertIn("Call Install_StateFailed", FUNCTIONS["Update_WriteState"])
        self.assertIn("Call Install_UninstallerFailed", FUNCTIONS["Update_WriteEntry"])

    def test_the_signer_file_is_the_one_trust_nsh_names(self):
        var, relative = re.search(r'StrCpy \$TrustStoreFile "\$(\w+)\\([^"]+)"', text_of(NSIS / "trust.nsh")).groups()
        found = re.search(r"Join-Path \$env:%s '([^']+)'" % var, PS1)
        self.assertIsNotNone(found)
        self.assertEqual(found.group(1), relative)
        self.assertIn("per-user file %%%s%%\\%s: " % (var, relative), PS1)


class ExpectationTests(unittest.TestCase):
    def test_the_exit_code_the_document_expects_of_a_good_install_is_the_ok_code(self):
        ok = json.loads(text_of(INST / "schema.json"))["exit_codes"]["ok"]
        prints = re.findall(r"it prints (\d+)", DOC)
        self.assertGreaterEqual(len(prints), 2)
        self.assertEqual({int(n) for n in prints}, {ok})

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
    def test_t2_prints_true_for_a_file_that_matches_its_hash_and_false_for_one_that_does_not(self):
        t2 = dict(STEPS)[2]
        command = re.search(r"`(Get-Content \.\\SHA256SUMS[^`]*)`", t2).group(1)
        from installer.guest.vmkit import KIT_FILES
        names = list(KIT_FILES)
        self.assertEqual(names, ["installer.exe", "VM-TEST.md", "vm-state.ps1"])
        self.assertIn("after each of the three names", t2)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for name in names:
                (tmp / name).write_bytes(name.encode())
            sums = "".join("%s %s%s\n" % (hashlib.sha256(name.encode()).hexdigest(), mark, name) for name, mark in zip(names, (" ", "*", " ")))
            (tmp / "SHA256SUMS").write_text(sums)

            def answers():
                r = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=tmp, capture_output=True, text=True, timeout=120)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                return dict(line.rsplit(" ", 1) for line in r.stdout.splitlines() if line.strip())

            self.assertEqual(answers(), {name: "True" for name in names})
            (tmp / names[1]).write_bytes(b"changed")
            self.assertEqual(answers(), {names[0]: "True", names[1]: "False", names[2]: "True"})


class RebuildTests(unittest.TestCase):
    BLOCK = re.search(r"## Rebuild the kit\n.*?```bash\n(.*?)```", DOC, re.S).group(1)

    def test_the_block_builds_the_commit_into_a_folder_of_its_first_12_digits_and_lists_the_kit(self):
        lines = self.BLOCK.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].split()[:4], ["python3", "-m", "installer.guest.vmkit", "build"])
        self.assertIn("--out ~/work/vm-kit/$(git rev-parse HEAD | cut -c1-12)", lines[0])
        self.assertIn("--payload ~/work/vm-kit/stand-in-payload.txt", lines[0])
        for rel in ("installer/VM-TEST.md", "installer/guest/vm-state.ps1", "installer/guest/vmkit.py"):
            self.assertTrue((ROOT / rel).is_file(), rel)
        self.assertIn("built from: <the 40 hex digits>", DOC)

    @unittest.skipUnless(shutil.which("bash") and shutil.which("git") and shutil.which("sha256sum"), "needs bash, git and sha256sum")
    def test_the_block_runs_and_leaves_a_kit_that_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo, home = tmp / "repo", tmp / "home"
            for rel in ("installer/VM-TEST.md", "installer/guest/vm-state.ps1", "installer/guest/vmkit.py"):
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / rel, repo / rel)
            (home / "work" / "vm-kit").mkdir(parents=True)
            (home / "work" / "vm-kit" / "stand-in-payload.txt").write_bytes(b"stand-in\n")
            # Only the compiler is fake: execute the documented command and real generator.
            (repo / "installer" / "build.py").write_text(
                "import sys\nfrom pathlib import Path\n"
                "assert sys.argv[1:3] == ['build', '.']\n"
                "assert sys.argv[4] == '--runner-payload' and sys.argv[6:] == ['--test-build']\n"
                "assert not any(Path(sys.argv[3]).parent.iterdir()), 'kit must be empty before compilation'\n"
                "Path(sys.argv[3]).write_bytes(Path(sys.argv[5]).read_bytes())\n", encoding="ascii")
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
            for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "kit"]):
                subprocess.run(git + args, cwd=repo, check=True, capture_output=True)
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
            r = subprocess.run(["bash", "-e", "-c", self.BLOCK], cwd=repo,
                               env=dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE="1"),
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            kit = home / "work" / "vm-kit" / head[:12]
            self.assertEqual(sorted(p.name for p in kit.iterdir()), ["SHA256SUMS", "VM-TEST.md", "installer.exe", "vm-state.ps1"])
            self.assertEqual((kit / "VM-TEST.md").read_text(encoding="utf-8"), DOC + "built from: %s\n" % head)
            self.assertEqual((kit / "installer.exe").read_bytes(), b"stand-in\n")
            self.assertEqual((kit / "vm-state.ps1").read_bytes(), (ROOT / "installer/guest/vm-state.ps1").read_bytes())
            check = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=kit, capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)


if __name__ == "__main__":
    unittest.main()
