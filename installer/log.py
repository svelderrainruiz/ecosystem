"""Step log and time zone (ARCH-10, ARCH-11). Reference model of installer/nsis/log.nsh. Standard library only.

Step log: one JSON object per line: step, command, exit_code, output, started (UTC ISO 8601), duration_ms (INST-REQ-046/047).
Machine timestamps are always UTC with an explicit +00:00 offset; only display_hhmm() converts, to plain HH:MM in the
person's zone with no "Z" and no "UTC" (INST-REQ-053/054). The zone is stored by name only; daylight saving comes from the
OS zone database at run time (INST-REQ-052). The Windows-to-IANA table is a pinned input: zones.json must hash to
ZONES_SHA256 (INST-REQ-055); changing the table needs a change here too.
Secrets are never logged: command and output pass through redact().
"""
import hashlib
import json
import re
import struct
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HERE = Path(__file__).resolve().parent
ZONES_PATH = HERE / "zones.json"
ZONES_SHA256 = "15b4cacfbe7c996386b1eb343f2c80948ef4ecd101621629a52799d312eb108d"

_KEY = r"[\w-]*(?:password|passwd|pwd|secret|token|api[_-]?key|licen[sc]e[_-]?key|authorization)[\w-]*"
_VALUE = r"""(?:(?:bearer|basic)\s+)?(?:"[^"]*"|'[^']*'|\S+)"""
_SECRET = re.compile(r"(?i)\b(" + _KEY + r")(\s*[=:]\s*|\s+)" + _VALUE)
_USERINFO = re.compile(r"(://[^/\s:@]+:)[^@\s]+@")
_LICENCE_SHAPE = re.compile(r"\b[A-Z0-9]{4,6}(?:-[A-Z0-9]{4,6}){2,}\b")


class LogError(Exception):
    """Base of every expected refusal."""


class ZoneTableError(LogError):
    pass


class UnknownZone(LogError):
    pass


def redact(text):
    """Percent-decoding first, so a keyword or separator split by %XX is still seen (the logged text is the decoded one)."""
    text = unquote(text)
    text = _SECRET.sub(lambda m: m.group(1) + m.group(2) + "[redacted]", text)
    text = _USERINFO.sub(lambda m: m.group(1) + "[redacted]@", text)
    return _LICENCE_SHAPE.sub("[redacted]", text)


def utc_iso(moment=None):
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise LogError("naive time refused: machine times are UTC with an offset")
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


class StepLog:
    def __init__(self, path, now=lambda: datetime.now(timezone.utc), clock=time.monotonic):
        self.path, self.now, self.clock = Path(path), now, clock

    def record(self, step, command, exit_code, output="", started=None, duration_ms=0):
        entry = {
            "step": step,
            "command": redact(command if isinstance(command, str) else " ".join(command)),
            "exit_code": None if exit_code in ("error", "timeout") else int(exit_code),
            "output": redact(output),
            "started": utc_iso(started or self.now()),
            "duration_ms": int(duration_ms),
        }
        if entry["exit_code"] is None:
            entry["exec_error"] = exit_code
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def run(self, step, argv, runner=subprocess.run):
        started, t0 = self.now(), self.clock()
        done = runner(argv, capture_output=True, text=True, check=False)
        return self.record(step, argv, done.returncode, (done.stdout or "") + (done.stderr or ""),
                           started, round((self.clock() - t0) * 1000))

    def read(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_zones(path=ZONES_PATH, expected=ZONES_SHA256):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        zones = doc["zones"]
        stored = doc["sha256_of_zones"]
        doc["source"], doc["how_obtained"]
        [(z["windows"], z["iana"], z["country"]) for z in zones]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ZoneTableError(f"zone table {path} is unreadable or incomplete: {e!r}") from None
    actual = hashlib.sha256(json.dumps(zones, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if actual != expected or stored != expected:
        raise ZoneTableError("zone table does not match its pinned sha256")
    return zones


def windows_to_iana(windows_name, country=None, zones=None):
    """First row for the Windows zone, preferring the given country; unknown zones are refused."""
    rows = [z for z in (zones or load_zones()) if z["windows"] == windows_name]
    if not rows:
        raise UnknownZone(f"unknown Windows zone: {windows_name}")
    for z in rows:
        if country and z["country"] == country:
            return z["iana"]
    return rows[0]["iana"]


def choose_zone(silent_value, pc_zone, zones=None):
    """Silent key absent or empty means the PC's zone (INST-REQ-051); a listed IANA name otherwise."""
    if not silent_value:
        return pc_zone
    if silent_value not in {z["iana"] for z in (zones or load_zones())}:
        raise UnknownZone(f"zone not in the pinned list: {silent_value}")
    return silent_value


def store_zone(path, name, zones=None):
    """Stores the name only (INST-REQ-052): never an offset, never a rule set."""
    name = choose_zone(name, None, zones)
    if name is None:
        raise UnknownZone("no zone name given")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(name + "\n", encoding="utf-8")


def read_zone(path, pc_zone):
    p = Path(path)
    return p.read_text(encoding="utf-8").strip() if p.exists() else pc_zone


def utc_from_local(year, month, day, hour, minute, second, active_time_bias):
    """Integer-only twin of LogUtcNow in nsis/log.nsh: UTC = local + ActiveTimeBias minutes (bias includes daylight saving).
    Returns an ISO 8601 UTC string. Date arithmetic is days-from-civil, as in the NSIS code (no datetime)."""
    y, m = (year - 1, month + 9) if month <= 2 else (year, month - 3)
    era = y // 400
    yoe = y - era * 400
    doy = (153 * m + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    days = era * 146097 + doe - 719468
    total = days * 1440 + hour * 60 + minute + active_time_bias
    days, rem = divmod(total, 1440)
    z = days + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    mo = mp + 3 if mp < 10 else mp - 9
    if mo <= 2:
        y += 1
    return f"{y:04d}-{mo:02d}-{d:02d}T{rem // 60:02d}:{rem % 60:02d}:{second:02d}+00:00"


def _signed32(value):
    """The registry hands a DWORD back unsigned: a bias of -120 arrives as 4294967176 and must be read as -120."""
    value = int(value) & 0xFFFFFFFF
    return value - (1 << 32) if value >= (1 << 31) else value


_TZ_KEY = r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation"


def _registry_bias():
    """ActiveTimeBias from the Windows registry (stdlib winreg), or None where there is no registry."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _TZ_KEY) as k:
            return _signed32(winreg.QueryValueEx(k, "ActiveTimeBias")[0])
    except (ImportError, OSError, ValueError):
        return None


def _registry_rules():
    """The PC's own daylight-saving rule from the registry (Bias, StandardBias, DaylightBias and the two SYSTEMTIME
    transition dates), or None where there is no registry or the values are unreadable."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _TZ_KEY) as k:
            get = lambda name: winreg.QueryValueEx(k, name)[0]
            return {"bias": _signed32(get("Bias")), "standard_bias": _signed32(get("StandardBias")),
                    "daylight_bias": _signed32(get("DaylightBias")),
                    "standard_start": struct.unpack("<8H", bytes(get("StandardStart"))),
                    "daylight_start": struct.unpack("<8H", bytes(get("DaylightStart")))}
    except (ImportError, OSError, ValueError, struct.error, TypeError):
        return None


def _transition_minutes(year, st):
    """Minutes since 1970-01-01 of a SYSTEMTIME rule (month, weekday 0=Sunday, week 1-5 with 5 = last) as local wall time."""
    fixed_year, month, dow, week, hour, minute, _, _ = st
    if fixed_year:  # a nonzero year is an absolute date: week is then the day of the month
        return int((datetime(fixed_year, month, week, hour, minute) - datetime(1970, 1, 1)).total_seconds() // 60)
    first = datetime(year, month, 1)
    day = 1 + (((dow - 1) % 7) - first.weekday()) % 7 + 7 * (week - 1)
    while True:
        try:
            when = datetime(year, month, day, hour, minute)
            break
        except ValueError:
            day -= 7
    return int((when - datetime(1970, 1, 1)).total_seconds() // 60)


def _bias_from_rules(rules, moment):
    """Minutes to subtract from UTC to get local time at `moment`, daylight saving decided by the registry rule."""
    std, dlt = rules["bias"] + rules["standard_bias"], rules["bias"] + rules["daylight_bias"]
    if not rules["daylight_start"][1] or not rules["standard_start"][1]:
        return std
    utc_min = int((moment.astimezone(timezone.utc).replace(tzinfo=None) - datetime(1970, 1, 1)).total_seconds() // 60)
    year = (datetime(1970, 1, 1) + timedelta(minutes=utc_min - std)).year  # year of the local standard time, not of UTC
    start = _transition_minutes(year, rules["daylight_start"]) + std
    end = _transition_minutes(year, rules["standard_start"]) + dlt
    inside = start <= utc_min < end if start < end else not end <= utc_min < start
    return dlt if inside else std


def _registry_zone_key():
    """The PC's own Windows zone name (TimeZoneKeyName), or None where there is no registry."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _TZ_KEY) as k:
            return str(winreg.QueryValueEx(k, "TimeZoneKeyName")[0])
    except (ImportError, OSError, ValueError):
        return None


def display_hhmm(utc_text, zone_name, active_time_bias=None):
    """HH:MM in the zone. Without OS zone data (Windows has no tzdata) the fallback applies only when the PC's own
    TimeZoneKeyName maps to zone_name in the pinned table; it then applies the PC's own daylight-saving rule from the
    registry for the date shown (ActiveTimeBias only when no rule is readable). Any other zone is refused."""
    moment = datetime.fromisoformat(utc_text)
    if moment.tzinfo is None:
        raise LogError("naive time refused: machine times are UTC with an offset")
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError):
        rows = load_zones()
        if zone_name not in {z["iana"] for z in rows}:
            raise UnknownZone(f"zone not known to the OS: {zone_name}") from None
        own = _registry_zone_key()
        if own is None or not any(z["windows"] == own and z["iana"] == zone_name for z in rows):
            raise UnknownZone(f"zone data missing and not the PC's own zone: {zone_name}") from None
        bias = active_time_bias
        if bias is None:
            rules = _registry_rules()
            bias = _bias_from_rules(rules, moment) if rules else _registry_bias()
        if bias is None:
            raise UnknownZone(f"zone data missing and no time bias available for: {zone_name}") from None
        zone = timezone(-timedelta(minutes=bias))
    return moment.astimezone(zone).strftime("%H:%M")
