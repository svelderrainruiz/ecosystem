"""Guest proof of the Windows system adapter (ecosystem-control#64, SL-5b, SL-5c, SL-6b). Runs INSIDE a disposable no-NIC clone,
as Administrator, from the extracted tree: it drives the REAL installer/winsys.py (sc.exe, icacls.exe, powershell.exe) against
a harmless test service (installer/guest/stub-service.cs compiled in the guest); no real runner, no network, no forge call.

  python -m installer.guest.service_proof create5 NAME FOLDER STUB     # SL-5b: service under NT SERVICE\\NAME, config.toml ACL
  python -m installer.guest.service_proof cleanup5 NAME FOLDER         # delete it again
  python -m installer.guest.service_proof logon5 NAME FOLDER STUB USER # SL-5c: a start that fails to log on
  python -m installer.guest.service_proof rollback NAME FOLDER STUB    # SL-6b: update with a crashing new version, then restore
  python -m installer.guest.service_proof updateloop NAME FOLDER STUB N # SL-6b diagnosis: N good updates, every failure with winerror, path, step and frames
  python -m installer.guest.service_proof install NAME FOLDER STUB     # only the adapter's install_service (used before uninstall)
  python -m installer.guest.service_proof aclcheck NAME FOLDER ID     # SL-13: folder, program and program\\runner.exe ACLs
  python -m installer.guest.service_proof display ZONE                 # display_hhmm of the current time in an IANA zone

Prints evidence lines and result lines `ID|PASS/FAIL/UNPROVEN|detail`. Never prints or takes a secret. Standard library only."""
import hashlib
import re
import shutil
import struct
import traceback
import subprocess
import sys
import time
from pathlib import Path

from installer import update, winsys

SYSTEM, ADMINS = "NT AUTHORITY\\SYSTEM", "BUILTIN\\Administrators"
ACE = re.compile(r"((?:(?:NT SERVICE|NT AUTHORITY|BUILTIN|[A-Za-z0-9_-]+)\\[A-Za-z0-9_. -]+?)|S-1-[0-9]+(?:-[0-9]+)+|Everyone|CREATOR OWNER)"
                 r":((?:\([A-Z,]+\))+)")


def service_sid(name):
    """The well-known SID of a service's virtual account (SHA-1 of the upper-case name); computed here, not taken from the code under test."""
    digest = hashlib.sha1(name.upper().encode("utf-16-le")).digest()
    return "S-1-5-80-" + "-".join(str(n) for n in struct.unpack("<5I", digest))


def say(text):
    print(text, flush=True)


def result(item, state, detail):
    say("%s|%s|%s" % (item, state, " ".join(str(detail).split())))


def ps(command):
    p = subprocess.run([winsys.tool(winsys.POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", command],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
    return (p.stdout or "").strip()


def icacls_text(path):
    return winsys.subprocess_runner([winsys.tool(winsys.ICACLS), str(path)]).stdout


def parse_aces(text):
    aces = {}
    for who, rights in ACE.findall(text):
        aces[who] = rights
    return aces


def parse_entries(text):
    """Every ACE as (principal, set of rights tokens); a principal may appear more than once."""
    return [(who, set(re.findall(r"\(([A-Z,]+)\)", rights))) for who, rights in ACE.findall(text)]


def normalise(who, name):
    if who.upper() in ("NT SERVICE\\" + name.upper(), service_sid(name)):
        return "SVC"
    return {SYSTEM.upper(): "SYSTEM", ADMINS.upper(): "ADMINS"}.get(who.upper(), who)


def acl_problems(text, name, folder):
    """SL-13 expectations. The folder: SYSTEM and Administrators (OI)(CI)(F), the service (OI)(CI)(RX), nothing else, nothing inherited.
    A child inherits these from the locked folder, so (I) is expected there; but only those three principals may appear, and the
    service must stay read-only. A Users, Authenticated Users, Everyone or CREATOR OWNER entry anywhere is a problem."""
    entries = [(normalise(who, name), rights) for who, rights in parse_entries(text)]
    problems = []
    if not entries:
        return ["no entries parsed"]
    for who, rights in entries:
        if who not in ("SYSTEM", "ADMINS", "SVC"):
            problems.append("unexpected principal %s %s" % (who, sorted(rights)))
        elif who == "SVC" and rights & {"F", "M", "W", "WD", "AD"}:
            problems.append("service account is not read-only: %s" % sorted(rights))
        elif who in ("SYSTEM", "ADMINS") and "F" not in rights:
            problems.append("%s is not full control: %s" % (who, sorted(rights)))
    if folder:
        want = {"SYSTEM": {"OI", "CI", "F"}, "ADMINS": {"OI", "CI", "F"}, "SVC": {"OI", "CI", "RX"}}
        got = {}
        for who, rights in entries:
            got.setdefault(who, []).append(rights)
        for who, rights in want.items():
            if got.get(who) != [rights]:
                problems.append("%s expected %s got %s" % (who, sorted(rights), [sorted(r) for r in got.get(who, [])]))
        if any("I" in rights for _, rights in entries):
            problems.append("an inherited (I) entry on the folder")
    return problems


def acl_paths(folder):
    folder = Path(folder)
    return [("folder", folder), ("program", folder / "program"), ("runner.exe", folder / "program" / "runner.exe")]


def acl_report(name, folder):
    """(problems, signature) over the folder, program and program\\runner.exe."""
    problems, signature = [], []
    for label, path in acl_paths(folder):
        if not path.exists():
            problems.append("%s missing" % label)
            continue
        text = icacls_text(path)
        say("icacls %s:\n%s" % (path, text))
        problems += ["%s: %s" % (label, p) for p in acl_problems(text, name, label == "folder")]
        signature.append((label, sorted((normalise(a, name), sorted(b)) for a, b in parse_entries(text))))
    return problems, signature


def service_present(name):
    return winsys.WinSystem("C:\\ProgramData\\" + name, name=name).service_exists()


def aclcheck(name, folder, item):
    """FAIL only when the ACL text shows the product is wrong; UNPROVEN when a precondition did not hold (a path is missing, or the
    only difference is the service entry while the test service was never created)."""
    problems, _ = acl_report(name, folder)
    missing = [p for p in problems if p.endswith(" missing")]
    if missing:
        result(item, "UNPROVEN", "precondition not met, nothing to check: " + "; ".join(missing))
        return
    if problems and all("SVC expected" in p for p in problems) and not service_present(name):
        result(item, "UNPROVEN", "the service %s was never created, so its entry cannot be judged: %s" % (name, "; ".join(problems)))
        return
    result(item, "FAIL" if problems else "PASS", "; ".join(problems) or "SYSTEM and Administrators (OI)(CI)(F), the service (OI)(CI)(RX), no Users entry, no inherited entry on the folder")


def prepare(folder, stub, config=True):
    folder = Path(folder)
    (folder / "program").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(stub, folder / "program" / "runner.exe")
    if config:
        (folder / "config.toml").write_text("# guest proof test config, no secret\n", encoding="ascii")
    return folder


def sc_state(name):
    return winsys.subprocess_runner([winsys.tool(winsys.SC), "query", name]).stdout


def wait_for(predicate, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(1)
    return bool(predicate())


def create5(name, folder, stub):
    account = winsys.VIRTUAL_PREFIX + name
    folder = prepare(folder, stub)
    system = winsys.WinSystem(str(folder), name=name)
    try:
        system.install_service(name, account, str(folder))
    except winsys.WinSysError as e:
        result("SL-5b-service-under-virtual-account", "FAIL", "install_service raised %s: %s" % (type(e).__name__, e))
        return
    d = system.service_definition()
    say("definition: %r" % d)
    say(sc_state(name))
    if not wait_for(lambda: "RUNNING" in sc_state(name)):
        say("service never reached RUNNING within 30 s")
    running = system.stays_running(3)
    cfg = folder / "config.toml"
    try:
        system.restrict_acl(str(cfg), [SYSTEM, ADMINS, account])
        acl_error = None
    except winsys.WinSysError as e:
        acl_error = "%s: %s" % (type(e).__name__, e)
    text = icacls_text(cfg)
    say("icacls config.toml:\n" + text)
    aces = parse_aces(text)
    want = {SYSTEM: "(F)", ADMINS: "(F)", account: "(R)"}
    acl_ok = acl_error is None and aces == want and "(I)" not in text
    result("SL-5b-config-acl", "PASS" if acl_ok else "FAIL",
           "icacls after restrict_acl: %r (expected %r)%s" % (aces, want, "; error " + acl_error if acl_error else ""))
    winsys.subprocess_runner([winsys.tool(winsys.ICACLS), str(folder), "/grant", "%s:(OI)(CI)M" % account])
    system.stop_service()
    probe = folder / "probe.txt"
    probe.unlink(missing_ok=True)
    system.start_service()
    wait_for(lambda: probe.exists() and "read=" in probe.read_text(encoding="ascii", errors="replace"))
    probe_text = probe.read_text(encoding="ascii", errors="replace") if probe.exists() else ""
    say("probe.txt: %r" % probe_text)
    owner = ps("$s = Get-CimInstance Win32_Service -Filter \"Name='%s'\"; $o = Invoke-CimMethod -InputObject "
               "(Get-CimInstance Win32_Process -Filter \"ProcessId=$($s.ProcessId)\") -MethodName GetOwner; "
               "'startname=' + $s.StartName + ' state=' + $s.State + ' owner=' + $o.Domain + '\\' + $o.User" % name)
    say("cim: " + owner)
    identity_ok = probe_text.splitlines()[:1] == [account] and "read=ok" in probe_text
    ok = d.get("account") == account and d.get("start") == "auto" and running and identity_ok and ("startname=" + account) in owner
    result("SL-5b-service-under-virtual-account", "PASS" if ok else "FAIL",
           "qc=%r running=%s probe=%r cim=%r" % (d, running, probe_text.replace("\r\n", " / "), owner))


def cleanup5(name, folder):
    system = winsys.WinSystem(str(folder), name=name)
    system.delete_service()
    gone = False
    for _ in range(20):
        if not system.service_exists():
            gone = True
            break
        time.sleep(1)
    shutil.rmtree(folder, ignore_errors=True)
    result("SL-5b-delete", "PASS" if gone else "FAIL", "service %s removed after delete_service: %s" % (name, gone))


def logon5(name, folder, stub, user):
    folder = prepare(folder, stub, config=False)
    system = winsys.WinSystem(str(folder), name=name)
    binpath = '"%s\\%s"' % (str(folder).rstrip("\\"), winsys.PROGRAM_EXE)
    r = winsys.subprocess_runner([winsys.tool(winsys.SC), "create", name, "binPath=", binpath, "obj=", ".\\" + user, "start=", "demand"])
    say("sc create with a local account and no password: rc=%d\n%s" % (r.returncode, r.stdout))
    if r.returncode != 0:
        result("SL-5c-logon-failure-error", "UNPROVEN", "sc create with a local account failed (rc=%d), so no start could be tried" % r.returncode)
    else:
        try:
            system.start_service(name)
            result("SL-5c-logon-failure-error", "FAIL", "start_service did not raise although the account cannot log on")
        except winsys.LogonFailure as e:
            result("SL-5c-logon-failure-error", "PASS", "start_service raised LogonFailure (sc.exe start rc 1069): %s" % e)
        except winsys.WinSysError as e:
            result("SL-5c-logon-failure-error", "FAIL", "start_service raised %s instead of LogonFailure: %s" % (type(e).__name__, e))
    system.delete_service()
    shutil.rmtree(folder, ignore_errors=True)


def staged(tmp, stub, version, crash):
    d = Path(tmp)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    shutil.copyfile(stub, d / "runner.exe")
    (d / "version.txt").write_text(version, encoding="ascii")
    if crash:
        (d / "crash.txt").write_text("crash", encoding="ascii")
    return d


def rollback(name, folder, stub):
    account = winsys.VIRTUAL_PREFIX + name
    folder = prepare(folder, stub, config=False)
    (folder / "program" / "version.txt").write_text("1", encoding="ascii")
    update.write_state(folder, "0.1.0", "local")
    system = winsys.WinSystem(str(folder), name=name)
    system.install_service(name, account, str(folder))
    before = system.service_definition()
    pre_text = icacls_text(folder / "program" / "runner.exe")
    say("runner.exe before any update (made under ProgramData, so it inherits Users):\n" + pre_text)
    pre_users = any(normalise(w, name) == "BUILTIN\\Users" for w, _ in parse_entries(pre_text))
    tmp = folder.parent / (folder.name + "-staged")
    steps = []
    try:
        good = update.update(folder, staged(tmp, stub, "2", False), "0.2.0", system)
        steps.append("good update: %r cause=%r version.txt=%s" % (good, getattr(good, "cause", None), (folder / "program" / "version.txt").read_text()))
        if good.status != "updated":
            try:
                system.lock_folder()
                steps.append("lock_folder after the restore: ok")
            except Exception as e:
                steps.append("lock_folder after the restore raised %s: %s" % (type(e).__name__, e))
            steps.append("status=%s audit=%s" % (system.folder_status(), system.folder_audit()))
        good_problems, good_sig = acl_report(name, folder)
        result("SL-13-acl-after-update", "FAIL" if good_problems else "PASS", "; ".join(good_problems) or "ACL as expected, runner.exe has no Users entry")
        if pre_users:
            result("SL-13-children-lose-inherited-users", "FAIL" if good_problems else "PASS", "runner.exe carried a Users entry before the update; after it: " + ("; ".join(good_problems) or "none"))
        else:
            result("SL-13-children-lose-inherited-users", "UNPROVEN", "runner.exe had no Users entry before the update, so nothing to remove")
        t0 = time.time()
        bad = update.update(folder, staged(tmp, stub, "3", True), "0.3.0", system)
        steps.append("crashing update: %r cause=%r after %.0f s" % (bad, getattr(bad, "cause", None), time.time() - t0))
        bad_problems, bad_sig = acl_report(name, folder)
        result("SL-13-acl-after-failed-update", "FAIL" if bad_problems else "PASS", "; ".join(bad_problems) or "ACL as expected after the restore, runner.exe has no Users entry")
        result("SL-13-acl-identical-after-update-and-failed-update", "PASS" if good_sig == bad_sig else "FAIL",
               "folder, program and runner.exe ACLs %s" % ("identical" if good_sig == bad_sig else "differ: %r vs %r" % (good_sig, bad_sig)))
        v = (folder / "program" / "version.txt").read_text()
        crash_left = (folder / "program" / "crash.txt").exists()
        state = update.read_state(folder)
        running = system.stays_running(5)
        after = system.service_definition()
        steps.append("after: version.txt=%s crash.txt_present=%s state=%r running=%s definition=%r" % (v, crash_left, state, running, after))
        ok = good.status == "updated" and bad.status == "restored" and v == "2" and not crash_left and running \
            and state["installer_version"] == "0.2.0" and after == before
        result("SL-6b-rollback-after-failed-health-check", "PASS" if ok else "FAIL", "; ".join(steps))
    except Exception as e:
        result("SL-6b-rollback-after-failed-health-check", "FAIL", "; ".join(steps) + "; raised %s: %s" % (type(e).__name__, e))
    finally:
        system.delete_service()
        shutil.rmtree(folder, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def lockdiag(name, folder):
    """Diagnostic: the adapter's own lock steps on a fresh folder whose service does not exist yet, with the raw tool output."""
    folder = Path(folder)
    shutil.rmtree(folder, ignore_errors=True)
    system = winsys.WinSystem(str(folder), name=name)
    say("service exists: %s" % system.service_exists())
    say("status before: %s" % system.folder_status())
    folder.mkdir(parents=True)
    say("status after mkdir: %s" % system.folder_status())
    argv = winsys.folder_acl_argv(str(folder), name)
    r = winsys.subprocess_runner(argv)
    say("icacls lock argv: %r rc=%s stdout=%r stderr=%r" % (argv, r.returncode, r.stdout, getattr(r, "stderr", "")))
    say("audit: %s" % system.folder_audit())
    try:
        system.lock_folder()
        say("lock_folder: ok")
    except Exception as e:
        say("lock_folder raised %s: %s" % (type(e).__name__, e))
    say(icacls_text(folder))
    shutil.rmtree(folder, ignore_errors=True)


def failure_detail(e):
    """Class, winerror, both paths and the last traceback frames (file:line) of an exception, for the SL-6b diagnosis."""
    frames = ["%s:%s" % (Path(f.filename).name, f.lineno) for f in traceback.extract_tb(e.__traceback__)[-4:]]
    return "%s winerror=%s errno=%s filename=%s filename2=%s frames=%s" % (
        type(e).__name__, getattr(e, "winerror", None), getattr(e, "errno", None), getattr(e, "filename", None),
        getattr(e, "filename2", None), ">".join(frames))


def runner_processes():
    r = ps("Get-Process | Where-Object { $_.Path -like '*EcosystemRunner*' -or $_.ProcessName -like 'runner*' -or $_.ProcessName -like 'stub*' } "
           "| ForEach-Object { '{0}:{1}' -f $_.ProcessName, $_.Id }")
    return " ".join(r.split()) or "none"


def updateloop(name, folder, stub, count):
    """N good updates in a row against the real adapter and update.py; a failure records the step it happened in."""
    folder, passes, current = Path(folder), 0, ["none"]
    original = update._replace_tree
    for i in range(1, int(count) + 1):
        account = winsys.VIRTUAL_PREFIX + name
        prepare(folder, stub, config=False)
        (folder / "program" / "version.txt").write_text("1", encoding="ascii")
        update.write_state(folder, "0.1.0", "local")
        system = winsys.WinSystem(str(folder), name=name)
        tmp = folder.parent / (folder.name + "-staged")
        errors, swaps = [], []
        try:
            system.install_service(name, account, str(folder))

            def wrap(owner, attr, step):
                inner = getattr(owner, attr)

                def run(*a, **k):
                    current[0] = step
                    try:
                        return inner(*a, **k)
                    except Exception as e:
                        errors.append("%s: %s" % (step, failure_detail(e)))
                        raise
                setattr(owner, attr, run)
            for attr, step in (("lock_folder", "lock"), ("stop_service", "stop"), ("start_service", "start"), ("stays_running", "health")):
                wrap(system, attr, step)
            def swap(src, dst):
                swaps.append(1)
                current[0] = "swap" if len(swaps) == 1 else "restore"
                try:
                    return original(src, dst)
                except Exception as e:
                    errors.append("%s: %s processes=%s" % (current[0], failure_detail(e), runner_processes()))
                    raise
            update._replace_tree = swap
            res = update.update(folder, staged(tmp, stub, "2", False), "0.2.0", system, fault=lambda step: current.__setitem__(0, step))
            ok = res.status == "updated"
            if ok:
                passes += 1
            else:
                result("SL-6b-loop-%02d" % i, "INFO", "%r cause=%r errors=%s processes=%s service=%s" % (
                    res, res.cause, " | ".join(errors) or "none", runner_processes(), sc_state(name)))
        except Exception as e:
            result("SL-6b-loop-%02d" % i, "INFO", "raised at step %s: %s errors=%s processes=%s" % (
                current[0], failure_detail(e), " | ".join(errors) or "none", runner_processes()))
        finally:
            update._replace_tree = original
            try:
                system.delete_service()
            except Exception:
                pass
            shutil.rmtree(folder, ignore_errors=True)
            shutil.rmtree(tmp, ignore_errors=True)
    result("SL-6b-loop", "INFO", "%d of %s good updates passed" % (passes, count))


def install(name, folder, stub):
    folder = prepare(folder, stub, config=False)
    winsys.WinSystem(str(folder), name=name).install_service(name, winsys.VIRTUAL_PREFIX + name, str(folder))
    say("installed %s" % name)


def display(zone):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from installer import log
    try:
        ZoneInfo(zone)
        zi = "ok"
    except Exception:
        zi = "missing"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        shown, err = log.display_hhmm(now, zone), ""
    except Exception as e:
        shown, err = "", type(e).__name__
    say("DISPLAY|zoneinfo=%s|hhmm=%s|error=%s" % (zi, shown, err))


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    table = {"create5": (create5, 3), "cleanup5": (cleanup5, 2), "logon5": (logon5, 4), "rollback": (rollback, 3), "updateloop": (updateloop, 4), "install": (install, 3), "aclcheck": (aclcheck, 3), "lockdiag": (lockdiag, 2),
             "display": (display, 1)}
    if not a or a[0] not in table or len(a) != table[a[0]][1] + 1:
        say("usage: see the module docstring")
        return 2
    try:
        table[a[0]][0](*a[1:])
    except Exception as e:
        result("ERROR-" + a[0], "FAIL", "%s: %s" % (type(e).__name__, e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
